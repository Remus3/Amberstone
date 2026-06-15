"""Champion stat resolution - base + level scaling + items, mode-aware.

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
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode} - gold spent {self.gold_spent}"
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


# item 232 - wiki mode_modifiers ADDEND axes (ar=Arena / swift=Swiftplay) map
# to a canonical scaling-rule stat + which term they adjust. hp_lvl/dam_lvl/etc
# are ADDENDS to the per-level growth coefficient; hp_base/arm_base add to the
# base value. Multiplier modes (urf/ofa/usb/nb) carry NO addend axis here -
# their dmg_dealt/dmg_taken multipliers live in dps.py / ehp.py (item 232 M
# slice). ms_mod / total_as are intentionally NOT mapped (no clean canonical
# growth-rule target; logged as a deferred edge).
_ADDEND_AXIS_MAP: dict[str, tuple[str, str]] = {
    "hp_base": ("hp", "base"),
    "hp_lvl": ("hp", "per"),
    "arm_base": ("armor", "base"),
    "arm_lvl": ("armor", "per"),
    "dam_lvl": ("ad", "per"),
    "as_lvl": ("as", "per"),
}


def _resolve_mode_addends(
    snapshot: "DataSnapshot", champion_id: str, mode: str
) -> dict[str, dict[str, float]] | None:
    """Resolve ar/swift stat-growth ADDENDS for a champion (item 232).

    Returns ``{canonical_key: {"base": addend, "per": addend}}`` for an addend
    mode, or None when the mode carries no addend axis (SR / ARAM / the
    multiplier modes / absent sidecar). Opt-in: only called from
    build_champion when apply_mode_modifiers is set.
    """
    try:
        mm = snapshot.mode_modifier(champion_id, mode)
    except Exception:
        return None
    if not isinstance(mm, dict):
        return None
    out: dict[str, dict[str, float]] = {}
    for axis, val in mm.items():
        target = _ADDEND_AXIS_MAP.get(axis)
        if target is None:
            continue
        key, kind = target
        try:
            out.setdefault(key, {})[kind] = float(val)
        except (TypeError, ValueError):
            continue
    return out or None


def _scale_champion_base(
    champ_stats: dict,
    level: int,
    mode_addends: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """Return ``(scaled, raw_base)`` where scaled is canonical-key -> value at level
    and raw_base preserves the unscaled base values needed for AS combine math.

    ``mode_addends`` (item 232, default None -> byte-identical) adds the ar/swift
    per-level / base stat-growth overrides before the growth formula applies.
    """
    scaled: dict[str, float] = {}
    raw_base: dict[str, float] = {}
    for rule in CHAMPION_SCALING_RULES:
        base = float(champ_stats.get(rule.base_field, 0.0))
        per = float(champ_stats.get(rule.perlevel_field, 0.0))
        if mode_addends:
            add = mode_addends.get(rule.canonical_key)
            if add:
                base += add.get("base", 0.0)
                per += add.get("per", 0.0)
        scaled[rule.canonical_key] = rule.formula(base, per, level)
        raw_base[rule.canonical_key] = base
    for canonical_key, ddragon_field in PASSTHROUGH_STAT_FIELDS.items():
        v = float(champ_stats.get(ddragon_field, 0.0))
        scaled[canonical_key] = v
        raw_base[canonical_key] = v
    return scaled, raw_base


# League hard-caps attack speed at 2.5 attacks/sec. Mirrors the existing
# crit clamp to 1.0 - a build that stacks past 2.5 AS gets no further
# attacks in-game, so the engine must not credit DPS for the excess.
ATTACK_SPEED_CAP = 2.5


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
      alongside the per-level bonus. Engine recomputes from base x (1 + sumpct).
    * **MS**: ``(base + flat) x (1 + pct)`` - standard, matches default.
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

    # MS: explicit (base + flat) x (1 + pct).
    ms_flat = item_totals.get("ms_flat", 0.0)
    ms_pct = item_totals.get("ms_pct", 0.0)
    out["ms"] = (raw_base.get("ms", 0.0) + ms_flat) * (1 + ms_pct)

    # Pct-only stats - stack additively (e.g. lifesteal 0.18 = +18%).
    for key in ("lifesteal", "spellvamp"):
        out[key] = out.get(key, 0.0) + item_totals.get(f"{key}_pct", 0.0)

    # AP - champion record has no base AP; surface from items.
    out["ap"] = out.get("ap", 0.0) + item_totals.get("ap_flat", 0.0)

    # Generic (flat adds, then pct multiplies) - covers crit too.
    GENERIC_FLAT_PCT = ("hp", "mp", "hpregen", "mpregen", "armor", "mr", "ad", "crit")
    for key in GENERIC_FLAT_PCT:
        flat = item_totals.get(f"{key}_flat", 0.0)
        pct = item_totals.get(f"{key}_pct", 0.0)
        out[key] = (out.get(key, 0.0) + flat) * (1 + pct)

    if out.get("crit", 0.0) > 1.0:
        out["crit"] = 1.0
    if out.get("as", 0.0) > ATTACK_SPEED_CAP:
        out["as"] = ATTACK_SPEED_CAP

    return out


def _apply_mode_modifiers(
    scaled: dict[str, float],
    raw_base: dict[str, float],
    mode: str,
    champion: dict,
) -> tuple[dict[str, float], list[str]]:
    """Phase 2 step 2 hook - apply mode-specific stat multipliers.

    ARAM modifiers applied here:
      * ``aramAttackSpeed`` - multiplier on bonus AS. Lifts effective AS.
      * ``aramAbilityHaste`` - integer flat delta in ability-haste points.
        Surfaced into ``scaled["aram_ability_haste"]`` (default 0). Not
        folded into ``scaled["ability_haste"]`` yet (no engine consumer
        for ability-haste exists in the current scorer suite); the value
        is exposed so downstream callers can compose cooldown math on it
        once the consumer ships.
      * ``aramTenacity`` - multiplier on effective CC duration applied
        against THIS champion. Surfaced into
        ``scaled["aram_tenacity_mult"]`` (default 1.0). Same exposure-only
        posture as the AH delta; an EHP-side scorer that ingests enemy CC
        duration can read this value directly to amortize it.

    aramHealing / aramShielding / aramDamageDealt / aramDamageTaken are
    NOT applied here - they remain in their dedicated consumers (HPS,
    DPS, EHP) where the per-side math lives.
    """
    notes: list[str] = []
    if mode != "ARAM":
        return scaled, notes
    lolmath = champion.get("lolmath", {}) or {}
    aram = lolmath.get("aram_modifiers", {}) or {}

    aram_as = float(aram.get("aramAttackSpeed", 1.0))
    if aram_as != 1.0:
        base_as = raw_base.get("as", 0.0)
        bonus_as = scaled.get("as", 0.0) - base_as
        scaled["as"] = base_as + bonus_as * aram_as
        notes.append(f"ARAM aramAttackSpeed={aram_as:.2f} on bonus AS")

    # ARAM ability-haste delta (22 champs non-zero in 16.10.1 - Aurora +10,
    # Azir +20, Brand -10, Camille +10, Corki -20, Hecarim +10, Irelia +20,
    # Katarina +10, Leblanc +20, Lucian +10, Mel -10, Milio -10, Naafiri +10,
    # Rakan +10, Seraphine -20, Sion -10, Smolder -10, Soraka +10, Syndra +5,
    # Teemo -15, Ziggs -20, Zyra -10). Exposure-only; no scorer reads it yet.
    aram_ah = float(aram.get("aramAbilityHaste", 0.0))
    scaled["aram_ability_haste"] = aram_ah
    if aram_ah != 0.0:
        notes.append(f"ARAM aramAbilityHaste={aram_ah:+.0f}")

    # ARAM tenacity (17 champs non-1.0 in 16.10.1 - all assassin-shaped
    # +20% / +10% values). Exposure-only; EHP scorer can read this once
    # it ingests enemy CC duration.
    aram_ten = float(aram.get("aramTenacity", 1.0))
    scaled["aram_tenacity_mult"] = aram_ten
    if aram_ten != 1.0:
        notes.append(f"ARAM aramTenacity={aram_ten:.2f}x effective CC duration")

    return scaled, notes


def build_champion(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    augments: Optional[Iterable[str | int]] = None,
    apply_mode_modifiers: bool = False,
) -> ResolvedStats:
    """Resolve a champion's stats at ``level`` with the given items equipped.

    Unknown item IDs raise ``KeyError`` from ``DataSnapshot.item``. Pass an
    explicit empty list (or omit) for naked stats.

    ``augments`` (Phase 6) is an iterable of arena augment apiNames or ids;
    each is resolved against ``snapshot.arena_augment(...)`` and stat overlays
    from :func:`agents.daemon_slayer.augments.compute_augment_stats` are
    applied additively after items, before mode modifiers. Augments outside
    the registered overlay set are silently ignored - registry coverage
    grows incrementally without breaking calls. Augments are honored
    regardless of mode (arena coach is the only natural caller, but the
    engine doesn't gate them - it's the caller's job to not pass arena
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

    # item 232 - ar/swift stat-growth addends (opt-in; default None -> byte-
    # identical). Resolved before scaling so the per-level overrides feed the
    # growth formula. Multiplier modes (urf/ofa/usb/nb/aram) resolve to None
    # here - their dmg mults live in dps.py/ehp.py, not the base-stat layer.
    mode_addends = (
        _resolve_mode_addends(snapshot, champion_id, mode)
        if apply_mode_modifiers
        else None
    )
    scaled, raw_base = _scale_champion_base(champ_stats, level, mode_addends)

    # Phase 4 batch 20 (2026-05-04): item-passive bonus AD as a percentage of
    # leveled base AD (Sterak's "+45% base AD as bonus AD"). Walked here -
    # AFTER _scale_champion_base resolves leveled base AD, BEFORE
    # _combine_items folds item totals into the final block - so the
    # passive AD lands in ad_flat just like any other item-side AD bonus.
    # NOTE: ``scaled`` carries the LEVELED base AD (the value League's UI
    # calls "base AD"). ``raw_base`` is the unscaled level-1 base used by
    # _combine_items for AS rebuild math - the wrong source for "% of base
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

    # Phase 4 batch 27 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's total max mana (Manamune / Muramana's "Awe" - +2% max
    # mana as bonus AD). Same wiring shape as the Sterak's walk above, but
    # keyed off mana instead of base AD. Walked AFTER aggregate_item_stats
    # produces ``item_totals["mp_flat"]`` so the items' own mana pools
    # (Manamune 500, Muramana 1000) are included in the conversion base.
    # Awe is mana -> AD one-way - no feedback loop, no need to iterate to a
    # fixed point. Manaless champions (energy users) have ``scaled["mp"]``
    # = 0; if their build also has no item mp_flat the Awe contribution
    # resolves to 0, so the walk is safe to run unconditionally.
    total_max_mp = scaled.get("mp", 0.0) + item_totals.get("mp_flat", 0.0)
    if total_max_mp > 0:
        passive_ad_from_mp = 0.0
        for iid in item_id_list:
            eff = ITEM_EFFECTS.get(iid)
            if eff and eff.bonus_ad_pct_max_mp > 0:
                passive_ad_from_mp += eff.bonus_ad_pct_max_mp * total_max_mp
        if passive_ad_from_mp > 0:
            item_totals["ad_flat"] = item_totals.get("ad_flat", 0.0) + passive_ad_from_mp

    # Phase 4 batch 28 (2026-05-04): item-passive bonus AP as a percentage of
    # the wielder's BONUS mana (Archangel's Staff / Seraph's Embrace
    # "Awe" - +1% / +2% bonus mana as AP). Mirror of the Awe-AD walk
    # above, with two key differences: (1) targets ``ap_flat`` instead
    # of ``ad_flat``, (2) keyed off BONUS mana (item-contributed only -
    # ``item_totals.get("mp_flat", 0.0)``) NOT max mana. The asymmetry
    # vs the Manamune family is by design - DDragon + Meraki both pin
    # the AP-side Awe to "bonus mana" specifically. Archangel-line items
    # have no AP stat in the resolved block until this walk fires
    # (their listed AP is in the DDragon stat block, item-aggregated
    # via ``ap_flat``); the Awe contribution adds to that.
    bonus_max_mp = item_totals.get("mp_flat", 0.0)
    if bonus_max_mp > 0:
        passive_ap_from_bonus_mp = 0.0
        for iid in item_id_list:
            eff = ITEM_EFFECTS.get(iid)
            if eff and eff.bonus_ap_pct_bonus_mp > 0:
                passive_ap_from_bonus_mp += eff.bonus_ap_pct_bonus_mp * bonus_max_mp
        if passive_ap_from_bonus_mp > 0:
            item_totals["ap_flat"] = item_totals.get("ap_flat", 0.0) + passive_ap_from_bonus_mp

    # Phase 4 batch 32 (2026-05-04): item-passive bonus AD as a percentage of
    # the wielder's bonus HP. Overlord's Bloodmail "Tyranny" grants bonus AD
    # = 2.5% bonus HP. Bonus HP in League = HP from items only (not base HP
    # from leveling). Approximation: item_totals["hp_flat"] = item-contributed
    # HP, the correct value - champion per-level HP is BASE HP, not bonus HP.
    # Walked AFTER aggregate_item_stats produces item_totals["hp_flat"] so
    # Overlord's own 550 HP is included in the conversion base.
    # One-way, no feedback loop (HP -> AD only). Same wiring pattern as the
    # Sterak's (bonus_ad_pct_base_ad, batch 20) and Manamune (bonus_ad_pct_max_mp,
    # batch 27) walks above.
    bonus_hp_from_items = item_totals.get("hp_flat", 0.0)
    if bonus_hp_from_items > 0:
        passive_ad_from_bonus_hp = 0.0
        for iid in item_id_list:
            eff = ITEM_EFFECTS.get(iid)
            if eff and eff.bonus_ad_pct_bonus_hp > 0:
                passive_ad_from_bonus_hp += eff.bonus_ad_pct_bonus_hp * bonus_hp_from_items
        if passive_ad_from_bonus_hp > 0:
            item_totals["ad_flat"] = item_totals.get("ad_flat", 0.0) + passive_ad_from_bonus_hp

    final = _combine_items(scaled, raw_base, item_totals, level)
    if augment_overlay:
        for k, v in augment_overlay.items():
            final[k] = final.get(k, 0.0) + v
        if final.get("crit", 0.0) > 1.0:
            final["crit"] = 1.0
        if final.get("as", 0.0) > ATTACK_SPEED_CAP:
            final["as"] = ATTACK_SPEED_CAP
    final, mode_notes = _apply_mode_modifiers(final, raw_base, mode, champ)

    notes: list[str] = list(mode_notes)
    if mode_addends:
        notes.append(
            f"mode={mode} stat-growth addends applied: {sorted(mode_addends)}"
        )
    if mode not in ("SR", "ARAM"):
        notes.append(f"mode={mode} - modifier table not plugged in for this mode")
    if aug_list and not augment_overlay:
        notes.append(f"augments={list(aug_list)} - none in stat-overlay registry yet")

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
