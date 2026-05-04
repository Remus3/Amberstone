"""Champion stat resolution — base + level scaling + items, mode-aware.

Phase 2 step 1 + step 2 deliverables. Pure stat math; ``dps.py`` layers
DPS scoring on top. Mode hook applies ARAM stat multipliers (currently
just ``aramAttackSpeed`` on bonus AS); damage multipliers stay in DPS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from .augments import compute_augment_stats
from .data_loader import DataSnapshot
from .effects import ITEM_EFFECTS
from .stats import (
    CHAMPION_SCALING_RULES,
    PASSTHROUGH_STAT_FIELDS,
    RESOLVED_STAT_ORDER,
    aggregate_item_stats,
    clamp_level,
)


@dataclass(frozen=True)
class ResolvedStats:
    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    stats: dict[str, float]
    gold_spent: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)
    # Pre-item, post-level base stats. Exposed for Phase 4 expansion's
    # callable bonus_damage entries (TriForce spellblade scales off
    # base_ad, not total_ad). Backward-compat default = empty dict.
    base_stats: dict[str, float] = field(default_factory=dict)
    # Phase 6: arena augment apiNames applied (in input order). Empty for
    # non-arena modes or when no augments were passed.
    augments: tuple[str, ...] = field(default_factory=tuple)

    def get(self, key: str, default: float = 0.0) -> float:
        return self.stats.get(key, default)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "gold_spent": self.gold_spent,
            "stats": dict(self.stats),
            "base_stats": dict(self.base_stats),
            "notes": list(self.notes),
            "augments": list(self.augments),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) — lvl {self.level} "
            f"— mode {self.mode} — gold spent {self.gold_spent}"
        )
        rows = [head, "-" * len(head)]
        if self.item_ids:
            rows.append(f"items: {', '.join(self.item_ids)}")
        else:
            rows.append("items: (none)")
        rows.append("")
        for key in RESOLVED_STAT_ORDER:
            if key not in self.stats:
                continue
            val = self.stats[key]
            if key in {"as"}:
                rows.append(f"  {key:<12} {val:.3f}")
            elif key in {"crit", "lifesteal", "spellvamp"}:
                rows.append(f"  {key:<12} {val * 100:.1f}%")
            else:
                rows.append(f"  {key:<12} {val:.1f}")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


def _scale_champion_base(champ_stats: dict, level: int) -> tuple[dict[str, float], dict[str, float]]:
    """Return ``(scaled, raw_base)`` where scaled is canonical-key → value at level
    and raw_base preserves the unscaled base values needed for AS combine math.
    """
    scaled: dict[str, float] = {}
    raw_base: dict[str, float] = {}
    for rule in CHAMPION_SCALING_RULES:
        base = float(champ_stats.get(rule.base_field, 0.0))
        per = float(champ_stats.get(rule.perlevel_field, 0.0))
        scaled[rule.canonical_key] = rule.formula(base, per, level)
        raw_base[rule.canonical_key] = base
    for canonical_key, ddragon_field in PASSTHROUGH_STAT_FIELDS.items():
        v = float(champ_stats.get(ddragon_field, 0.0))
        scaled[canonical_key] = v
        raw_base[canonical_key] = v
    return scaled, raw_base


def _combine_items(
    scaled: dict[str, float],
    raw_base: dict[str, float],
    item_totals: dict[str, float],
    level: int,
) -> dict[str, float]:
    """Stack item flat/pct totals onto the leveled champion stats.

    Default rule: ``flat`` adds, ``pct`` multiplies the (base + flat) sum.
    Special cases (because in-game math differs from the default):

    * **AS**: items add into the bonus_pct sum that multiplies the BASE AS,
      alongside the per-level bonus. Engine recomputes from base × (1 + Σpct).
    * **MS**: ``(base + flat) × (1 + pct)`` — standard, matches default.
    * **Crit**: capped at 1.0 (100%) post-stack.
    """
    out = dict(scaled)

    # AS: rebuild from base AS so item pct stacks alongside per-level bonus.
    base_as = raw_base.get("as", 0.0)
    bonus_as_from_levels = 0.0
    if base_as > 0:
        # bonus pct from levels = (scaled - base) / base
        bonus_as_from_levels = (scaled["as"] - base_as) / base_as
    bonus_as_from_items = item_totals.get("as_pct", 0.0)
    out["as"] = base_as * (1 + bonus_as_from_levels + bonus_as_from_items)

    # MS: explicit (base + flat) × (1 + pct).
    ms_flat = item_totals.get("ms_flat", 0.0)
    ms_pct = item_totals.get("ms_pct", 0.0)
    out["ms"] = (raw_base.get("ms", 0.0) + ms_flat) * (1 + ms_pct)

    # Pct-only stats — stack additively (e.g. lifesteal 0.18 = +18%).
    for key in ("lifesteal", "spellvamp"):
        out[key] = out.get(key, 0.0) + item_totals.get(f"{key}_pct", 0.0)

    # AP — champion record has no base AP; surface from items.
    out["ap"] = out.get("ap", 0.0) + item_totals.get("ap_flat", 0.0)

    # Generic (flat adds, then pct multiplies) — covers crit too.
    GENERIC_FLAT_PCT = ("hp", "mp", "hpregen", "mpregen", "armor", "mr", "ad", "crit")
    for key in GENERIC_FLAT_PCT:
        flat = item_totals.get(f"{key}_flat", 0.0)
        pct = item_totals.get(f"{key}_pct", 0.0)
        out[key] = (out.get(key, 0.0) + flat) * (1 + pct)

    if out.get("crit", 0.0) > 1.0:
        out["crit"] = 1.0

    return out


def _apply_mode_modifiers(
    scaled: dict[str, float],
    raw_base: dict[str, float],
    mode: str,
    champion: dict,
) -> tuple[dict[str, float], list[str]]:
    """Phase 2 step 2 hook — apply mode-specific stat multipliers.

    Currently: ARAM ``aramAttackSpeed`` (multiplier on bonus AS). Damage
    multipliers (``aramDamageDealt``) live in the DPS layer, not here —
    they don't change AD/AP, only output. Other ARAM modifiers
    (Tenacity / Healing / Shielding / DamageTaken / AbilityHaste) are
    intentionally not applied at the stat layer; they belong in their
    respective consumers (sustain calc, EHP calc, AH lookup).
    """
    notes: list[str] = []
    if mode == "ARAM":
        lolmath = champion.get("lolmath", {}) or {}
        aram = lolmath.get("aram_modifiers", {}) or {}
        aram_as = float(aram.get("aramAttackSpeed", 1.0))
        if aram_as != 1.0:
            base_as = raw_base.get("as", 0.0)
            bonus_as = scaled.get("as", 0.0) - base_as
            scaled["as"] = base_as + bonus_as * aram_as
            notes.append(f"ARAM aramAttackSpeed={aram_as:.2f} on bonus AS")
    return scaled, notes


def build_champion(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    augments: Optional[Iterable[str | int]] = None,
) -> ResolvedStats:
    """Resolve a champion's stats at ``level`` with the given items equipped.

    Unknown item IDs raise ``KeyError`` from ``DataSnapshot.item``. Pass an
    explicit empty list (or omit) for naked stats.

    ``augments`` (Phase 6) is an iterable of arena augment apiNames or ids;
    each is resolved against ``snapshot.arena_augment(...)`` and stat overlays
    from :func:`agents.daemon_slayer.augments.compute_augment_stats` are
    applied additively after items, before mode modifiers. Augments outside
    the registered overlay set are silently ignored — registry coverage
    grows incrementally without breaking calls. Augments are honored
    regardless of mode (arena coach is the only natural caller, but the
    engine doesn't gate them — it's the caller's job to not pass arena
    augments into an SR query).
    """
    level = clamp_level(level)
    champ = snapshot.champion(champion_id)
    champ_stats = champ.get("stats", {})

    item_id_list: tuple[str, ...] = tuple(str(i) for i in (item_ids or ()))
    item_records = [snapshot.item(i) for i in item_id_list]
    gold_spent = sum(int((rec.get("gold") or {}).get("total", 0)) for rec in item_records)
    item_stat_blocks = [rec.get("stats", {}) for rec in item_records]
    item_totals = aggregate_item_stats(item_stat_blocks)

    aug_list: tuple[str, ...] = tuple(str(x) for x in (augments or ()))
    augment_overlay = compute_augment_stats(aug_list, snapshot) if aug_list else {}

    scaled, raw_base = _scale_champion_base(champ_stats, level)

    # Phase 4 batch 20 (2026-05-04): item-passive bonus AD as a percentage of
    # leveled base AD (Sterak's "+45% base AD as bonus AD"). Walked here —
    # AFTER _scale_champion_base resolves leveled base AD, BEFORE
    # _combine_items folds item totals into the final block — so the
    # passive AD lands in ad_flat just like any other item-side AD bonus.
    # NOTE: ``scaled`` carries the LEVELED base AD (the value League's UI
    # calls "base AD"). ``raw_base`` is the unscaled level-1 base used by
    # _combine_items for AS rebuild math — the wrong source for "% of base
    # AD" passives. dps.py uses the same convention via
    # resolved.base_stats (= scaled).
    leveled_base_ad = scaled.get("ad", 0.0)
    if leveled_base_ad > 0:
        passive_bonus_ad = 0.0
        for iid in item_id_list:
            eff = ITEM_EFFECTS.get(iid)
            if eff and eff.bonus_ad_pct_base_ad > 0:
                passive_bonus_ad += eff.bonus_ad_pct_base_ad * leveled_base_ad
        if passive_bonus_ad > 0:
            item_totals["ad_flat"] = item_totals.get("ad_flat", 0.0) + passive_bonus_ad

    final = _combine_items(scaled, raw_base, item_totals, level)
    if augment_overlay:
        for k, v in augment_overlay.items():
            final[k] = final.get(k, 0.0) + v
        if final.get("crit", 0.0) > 1.0:
            final["crit"] = 1.0
    final, mode_notes = _apply_mode_modifiers(final, raw_base, mode, champ)

    notes: list[str] = list(mode_notes)
    if mode not in ("SR", "ARAM"):
        notes.append(f"mode={mode} — modifier table not plugged in for this mode")
    if aug_list and not augment_overlay:
        notes.append(f"augments={list(aug_list)} — none in stat-overlay registry yet")

    return ResolvedStats(
        champion_id=champion_id,
        champion_name=champ.get("name", champion_id),
        level=level,
        item_ids=item_id_list,
        mode=mode,
        stats=final,
        gold_spent=gold_spent,
        notes=tuple(notes),
        base_stats=scaled,
        augments=aug_list,
    )
