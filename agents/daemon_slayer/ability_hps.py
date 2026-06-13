"""2026-05-30 (DS scraper-review slice; additive, no ENGINE bump) - champion ABILITY healing/shielding scorer.

Sibling of ``ability_dps.py``. Where ``ability_dps`` evaluates the
``attribute_kind == "damage"`` blocks of each active spell (Q/W/E/R), this
module evaluates the ``"heal"`` and ``"shield"`` blocks - making
champion-spell heal/shield throughput DATA-DRIVEN from the scraped
``champion_abilities.json`` (96 heal + 56 shield blocks at 16.11.1) instead
of leaving them on the cutting-room floor.

Context (2026-05-30 DS review): the scraper-refactor conversation flagged
that ability heal/shield "still has hardcoded values" - in RC's case the
champion-ability heal/shield blocks were extracted but NEVER CONSUMED
(``ability_dps`` filters to ``"damage"`` blocks at the block-select step;
``hps.py`` only scores the curated ENCHANTER ITEM registry). This closes
that gap for the ACTIVE abilities by reusing the exact per-cast evaluation
machinery ``ability_dps`` uses for damage:

* rank-at-level via ``_resolve_max_priority`` + ``rank_at_level``
* per-block scaling via ``_evaluate_block`` (base + AP/AD/HP coeffs); the
  AP fed to procs is amp-adjusted (Rabadon's 30%, Mejai's stacks, HP->AP
  cross-derivation) exactly as ``compute_ability_dps`` does so heal-on-AP
  agrees with the damage scorer
* per-cast rate via measured ``get_spell_casts_per_sec`` then a
  ``1 / cooldown`` fallback gated by mana uptime
* ARAM ``aramHealing`` / ``aramShielding`` mode multipliers (reused from
  ``hps._aram_heal_shield_modifiers`` so the heal and shield halves stay
  independent - 24 champs carry split values at 16.10.1+)

This is a PURELY ADDITIVE scorer: it introduces no change to the existing
DPS / EHP / ability-DPS / HPS-item rankers. ``compute_hps`` (``hps.py``)
consumes ``compute_ability_hps`` via a function-level import, folding its
output into the enchanter HPS total; it is also the data-driven substrate a
coach surface can read.

v2 (2026-05-30 item 226 NEXT, additive, no ENGINE bump) extends the v1
active-slot-only scorer with two opt-in paths, both BYTE-IDENTICAL to v1
when they do not apply:

* PASSIVE-P slot (``include_passive=True``, default ON). The P key is now
  walked alongside Q/W/E/R, resolved at the level-scaled rank
  ``rank_at_level("P", level)`` (== level-1, the same model ``ability_dps``
  uses for passives). DATA-AVAILABILITY CEILING at 16.11.1: the extractor
  emits ZERO heal/shield ``damage_blocks`` on any P form (Aatrox
  Deathbringer Stance / Dr. Mundo regen / Vladimir Crimson Pact heals live
  in stripped ``effects`` description text, NOT in the parsed blocks). So
  including P is currently a no-op for the entire roster - it future-proofs
  the path for a patch that surfaces a P heal block without re-touching the
  scorer. We do NOT fabricate passive heals that the snapshot does not
  carry. Set ``include_passive=False`` for the exact v1 Q/W/E/R-only walk.
* TARGET-RELATIVE + CASTER-MISSING-HP heal/shield units
  (``resolve_target_relative=True``, default OFF). v1 flags these as
  ``unresolved`` (lower bound 0). v2 resolves them against documented
  representative stats so they contribute a real lower-bound amount:
  - ``% of target's maximum health`` (Taric W shield) -> ``target_max_hp``
  - ``% of target's missing health`` (Fiddlesticks/Seraphine W) ->
    ``target_max_hp * target_missing_hp_pct``
  - ``% missing health`` / ``% of his missing health`` /
    ``% of missing health`` (Volibear W, Yorick Q, TahmKench Q, Dr. Mundo R,
    Gangplank W, Olaf W) -> CASTER missing-HP =
    ``caster_max_hp * caster_missing_hp_pct``
  When ``target_max_hp == 0`` (the default) the target-relative units still
  resolve to 0 - so flipping ``resolve_target_relative`` on without passing
  a representative ``target_max_hp`` changes nothing. Pass a representative
  enemy HP (and the missing-HP fractions) to get a non-zero lower bound. The
  v1 default keeps these UNRESOLVED so the existing pins (and the v1
  ``_eval_heal_shield_block`` call shape) stay byte-identical.

v3 (2026-06-01 GAP-2 effects-text HEAL registry, additive, byte-identical at
the v1/v2 defaults) adds support for a synthetic ``attribute_kind="heal"``
block carrying ``bilinear_terms`` - an AP / bonus-AD scaled %-of-HP self-heal
(``factor * ctx[a] * ctx[b]``) that no single linear heal unit expresses. The
blocks are injected by ``abilities.AbilitiesSnapshot.load(apply_passive_heal=
True)`` from ``_passive_heal_overrides`` (Viego P / Karma W f1 / Kayn R - heals
that live only in stripped ``effects_descriptions`` text). ``_eval_heal_shield_
block`` evaluates the bilinear terms against a ``bilinear_ctx`` dict built once
per call; snapshot heal/shield blocks carry no ``bilinear_terms`` so this is a
no-op for them. Every seeded heal scales on a target / caster-MISSING HP
quantity, so it resolves to 0 unless the caller opts into
``resolve_target_relative`` + passes the HP assumption - the default
``compute_ability_hps`` call stays byte-identical even with the flag on.

v4 (2026-06-01 item 253 - AS-aware heal seam, additive, byte-identical at the
defaults) adds a ``bonus_as`` entry to ``bilinear_ctx`` so a heal term can scale
on the caster's bonus attack speed (the one named clean headless heal term the
bilinear registry could not previously express). ``bonus_as`` is bonus attack
speed in PERCENTAGE POINTS (total AS minus the champion's INNATE base AS over
the innate base, the "% per 100% bonus AS" convention - it credits both the
per-level and item AS bonus). It is a pure caster stat (always resolved); the
sole consumer (Viego P's omitted "+5% per 100% bonus attack speed of target max
HP" term) gates on its ``target_max_hp`` half, so a build with no AS bonus and
the default ``resolve_target_relative=False`` are both byte-identical. This is
the LAST named clean headless heal lift - the AS-scaled heal class is the single
Viego P term (the roster scan found no other heal or shield scaling on AS).

v5 (2026-06-01 item 260 - effects-text-only SHIELD registry, additive, byte-
identical at the defaults) closes the SHIELD half of this scorer. The 56 snapshot
shield blocks were already scored (``_select_kind_blocks(form, "shield", ...)``);
``_passive_shield_overrides`` now injects synthetic ``attribute_kind="shield"``
blocks for the effects-text-only shields that parse to NO shield block (Malphite
Granite Shield, Blitzcrank Mana Barrier, Vi/Shen/Rakan/Yasuo P, Skarner W,
Volibear E, Viktor Q, Camille P). They ride this same evaluator unchanged - the
only addition is the ``% maximum mana`` -> ``caster_max_mp`` unit in
``_HEAL_UNIT_TO_CTX`` (Blitzcrank's mana shield; no snapshot block uses a mana
unit so the default path is byte-identical). Injected by
``abilities.AbilitiesSnapshot.load(apply_passive_shield=True)``; default OFF.

Deliberate omissions (mirror ``ability_dps``):
* Multi-block heal/shield forms default to ``block_strategy="first"`` (the
  first heal block + first shield block), matching ``ability_dps``'s
  damage-block default so "Total"/"Maximum" variant blocks are not
  double-counted. Pass ``block_strategy="sum"`` to add all blocks.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Iterable, Optional

from .abilities import load_default
from .ability_dps import (
    SPELL_KEYS,
    AbilityContext,
    _form_cooldown_at_rank,
    _form_cost_at_rank,
    _mana_uptime_factor,
    _resolve_form_index_overrides,
    _resolve_max_priority,
    clamp_level,
    rank_at_level,
)
from .data_loader import DataSnapshot
from .effects import (
    collect_effects,
    total_ap_amp_multiplier,
    total_bonus_ap_from_hp,
    total_caster_hp_scaled_ap_amp,
    total_stacked_ap,
)
from .engine import build_champion
from .hps import _aram_heal_shield_modifiers
from .ult_rates import get_spell_casts_per_sec

_BLOCK_STRATEGIES: frozenset[str] = frozenset({"first", "sum"})

# --- raw_modifiers heal/shield evaluation ---------------------------------
#
# The extractor TYPES only ``attribute_kind == "damage"`` blocks into the
# scaling fields (base / ap_pct / ...) the damage evaluator reads. heal +
# shield blocks keep their numbers ONLY in ``raw_modifiers`` (a list of
# {values:[per-rank], units:[per-rank]} dicts), so ``_evaluate_block`` (which
# reads the typed fields) returns 0 for every heal/shield block. This module
# parses ``raw_modifiers`` directly - the caster-side units a resting
# throughput number can resolve. Units NOT in this map (target-relative,
# missing-health, life-steal, per-stack/soul/mist) contribute 0 and are
# tracked as ``unresolved`` so the number never silently overstates.
_HEAL_UNIT_TO_CTX: dict[str, str | None] = {
    "": None,                       # flat base term
    "% ap": "ap",
    "% of sona's ap": "ap",
    "% bonus ad": "bonus_ad",
    "% ad": "total_ad",
    "% maximum health": "caster_max_hp",
    "% of maximum health": "caster_max_hp",
    "% bonus health": "caster_bonus_hp",
    "% of his bonus health": "caster_bonus_hp",
    # item 260 (effects-text-only SHIELD registry): Blitzcrank Mana Barrier is
    # the sole mana-scaled shield. ``caster_max_mp`` already exists on
    # AbilityContext; no snapshot heal/shield block uses a mana unit, so this is
    # byte-identical on the default path.
    "% maximum mana": "caster_max_mp",
}

# --- v2 target-relative + caster-missing-HP units (opt-in) -----------------
#
# These units scale heal/shield off a stat that is NOT a resting caster stat:
# the TARGET's HP, or the CASTER's MISSING HP (a state-dependent quantity).
# v1 leaves them ``unresolved`` (lower bound 0). v2's ``resolve_target_relative``
# path resolves each one against a documented assumption. Each entry maps a
# unit string to a "stat-kind" symbol that ``_resolve_extra_units`` turns into
# a concrete value using the per-call assumptions (target_max_hp +
# target_missing_hp_pct + caster_missing_hp_pct). Bare units NOT in this map
# remain unresolved (the lower-bound contract holds for life-steal / per-soul /
# per-mist / per-health-lost units we still cannot resolve at rest).
_TARGET_REL_STAT_KIND: dict[str, str] = {
    "% of target's maximum health": "target_max_hp",
    "% of target's missing health": "target_missing_hp",
    "% missing health": "caster_missing_hp",
    "% of his missing health": "caster_missing_hp",
    "% of missing health": "caster_missing_hp",
}

# Attribute names tagged heal/shield by the extractor that are NOT a direct,
# recurring heal/shield amount: cost reductions, percentage MULTIPLIERS,
# permanent max-HP grants, regen, conversion ratios, stat readouts, and the
# downgrade ("Reduced ...") / per-AA-hit variants that would double-count or
# mis-cadence against a per-cast model. Matched case-insensitively as a
# substring; such blocks are skipped entirely.
_META_HEAL_SHIELD_RE = re.compile(
    r"(reduced|percentage|increased heal|bonus health|base health|"
    r"health regen|regenerat|threshold|wall health|"
    r"heal and shield power|shield to healing|health cost|"
    r"on-hit|per hit|per 1 fury|per ally)",
    re.IGNORECASE,
)


def _is_meta_heal_shield(attribute: str) -> bool:
    """True when a heal/shield-tagged block is NOT a direct recurring amount."""
    return bool(_META_HEAL_SHIELD_RE.search(attribute or ""))


def _value_at_rank(values: list, rank: int) -> float:
    """Pick the per-rank value, clamping a 1-element list to that value.

    Non-finite values (NaN / +-inf) are rejected to 0.0 alongside
    unparseable ones: ``float("nan")`` / ``float("inf")`` do NOT raise, so a
    malformed scraped ``values`` entry would otherwise propagate a bare
    ``NaN`` / ``Infinity`` token through ``heal_per_cast`` -> ``heal_per_sec``
    -> the ``to_dict`` payload, which ``json.dumps`` emits verbatim and the
    dashboard's ``JSON.parse`` then rejects. The active 16.12.1 snapshot
    carries no non-finite numerics, so this is a defense-in-depth guard at
    the single chokepoint every heal/shield block value flows through.
    """
    if not values:
        return 0.0
    idx = 0 if rank < 0 else rank
    if idx >= len(values):
        idx = len(values) - 1
    try:
        out = float(values[idx])
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _resolve_extra_units(
    ctx,
    *,
    target_max_hp: float,
    target_missing_hp_pct: float,
    caster_missing_hp_pct: float,
) -> dict[str, float]:
    """Build the v2 opt-in unit -> resolved-value map for one ``ctx``.

    Returns a ``{lowercased_unit: stat_value}`` dict that
    ``_eval_heal_shield_block`` multiplies by ``value / 100``. The
    target-relative + caster-missing-HP units are computed from the
    documented per-call assumptions; a unit whose stat resolves to 0 (e.g.
    ``target_max_hp == 0``) still appears in the map so it is treated as
    RESOLVED (contributes 0, no unresolved flag) - that is the documented
    lower-bound behavior.
    """
    caster_max_hp = float(getattr(ctx, "caster_max_hp", 0.0) or 0.0)
    target_missing_hp = target_max_hp * target_missing_hp_pct
    caster_missing_hp = caster_max_hp * caster_missing_hp_pct
    kind_value = {
        "target_max_hp": target_max_hp,
        "target_missing_hp": target_missing_hp,
        "caster_missing_hp": caster_missing_hp,
    }
    return {
        unit: kind_value[kind] for unit, kind in _TARGET_REL_STAT_KIND.items()
    }


def _eval_heal_shield_block(
    block, rank: int, ctx, extra_units: Optional[dict] = None,
    bilinear_ctx: Optional[dict] = None, level: Optional[int] = None,
) -> tuple[float, bool]:
    """Evaluate one heal/shield block's raw_modifiers at ``rank``.

    Returns ``(amount, had_unresolved_unit)``. A flat term (empty unit) is
    added directly; a recognized percent unit multiplies the matching
    ``ctx`` stat / 100. An unrecognized unit contributes 0 and flips the
    unresolved flag so callers can note the value is a lower bound.

    ``level`` (GAP-2 LINEAR effects-text HEAL registry, opt-in) is the champion
    level. It is consulted ONLY for a synthetic heal block flagged
    ``level_scaled=True`` (a SPELL-slot effects-text heal whose per-rank
    ``values`` list is actually a per-LEVEL tuple - Rakan Q / Talon Q): the
    value is read at ``level-1`` instead of the spell rank. Every snapshot
    block + every P-slot synthetic block leaves ``level_scaled`` False, so the
    index is ``rank`` and the call is byte-identical when ``level`` is None.

    ``extra_units`` (v2, opt-in) is a ``{lowercased_unit: stat_value}`` map
    of target-relative / caster-missing-HP units to resolve. When ``None``
    (the v1 default) those units stay UNRESOLVED, so the v1 call shape is
    byte-identical. A unit present in BOTH the caster map and ``extra_units``
    is resolved by the caster map first (caster-side wins).

    ``bilinear_ctx`` (GAP-2 effects-text HEAL registry, opt-in) is a
    ``{ctx_attr: resolved_value}`` map for evaluating the synthetic heal
    block's ``bilinear_terms`` (each ``(factor, a, b)`` contributes
    ``factor * bilinear_ctx[a] * bilinear_ctx[b]`` - an AP / bonus-AD scaled
    %-of-HP product). Snapshot heal/shield blocks carry no ``bilinear_terms``
    so this is a no-op for them (byte-identical). A bilinear term whose HP
    factor is resolved to 0 (``resolve_target_relative=False``) contributes 0
    silently, mirroring the linear lower-bound behavior.
    """
    total = 0.0
    unresolved = False
    eff_rank = (
        (level - 1)
        if (level is not None and getattr(block, "level_scaled", False))
        else rank
    )
    for mod in block.raw_modifiers:
        if not isinstance(mod, dict):
            continue
        values = mod.get("values") or []
        units = mod.get("units") or []
        unit_raw = next((u for u in units if u), "")
        unit = str(unit_raw).strip().lower()
        val = _value_at_rank(values, eff_rank)
        if unit == "":
            total += val
            continue
        if unit in _HEAL_UNIT_TO_CTX:
            ctx_attr = _HEAL_UNIT_TO_CTX[unit]
            if ctx_attr is None:
                total += val
            else:
                total += (val / 100.0) * getattr(ctx, ctx_attr, 0.0)
        elif extra_units is not None and unit in extra_units:
            total += (val / 100.0) * extra_units[unit]
        else:
            unresolved = True
    if bilinear_ctx is not None and getattr(block, "bilinear_terms", ()):
        for factor, attr_a, attr_b in block.bilinear_terms:
            total += (
                float(factor)
                * float(bilinear_ctx.get(attr_a, 0.0))
                * float(bilinear_ctx.get(attr_b, 0.0))
            )
    return total, unresolved


# --- AOE heal per-target multiplicity registry (item 337, forward-marker) --
#
# A forward-marker sibling registry capturing the per-cast TARGET MULTIPLICITY
# of AOE / per-ally heals - the representative count of allied champions a
# team-heal lands on in a teamfight. ``compute_ability_hps`` models only the
# single-target heal amount (``heal_per_cast``) and hardwires the ally count to
# 1 in ``heal_per_sec``; the ``AbilitySpellHps`` schema has NO field for
# multiplicity, so the TOTAL throughput of an AOE team-heal (Soraka R, Janna R,
# Milio R, Seraphine W, Fiora R) is structurally inexpressible today - the flat
# per-cast scalar can only hold the one-ally amount and discards the team-wide
# total.
#
# NOTHING consumes this registry at ship: ``compute_ability_hps`` does not read
# it, so ``heal_per_cast`` / ``heal_per_sec`` / ``total_heal_per_sec`` and both
# ``to_dict`` surfaces are byte-identical and ENGINE_VERSION does NOT bump. This
# mirrors how the item-336 per-spell CC RANGE registry and the item-130
# per-spell CC DURATIONS registry shipped forward-marker first. A future
# EHP-vs-sustain /
# team-heal-throughput consumer reads ``assumed_targets`` and multiplies
# ``heal_per_cast`` by it.
#
# The ``assumed_targets`` VALUE follows the operator-tunable ``assumed_charges``
# / ``assumed_stacks`` convention (a representative teamfight ally count), NOT a
# verbatim data field. What IS verbatim from
# ``data/daemon_slayer/16.11.1/champion_abilities.json`` (ground-truth probed
# 2026-06-07) is that each seeded spell is an AOE / per-ally heal:
#   Soraka R Wish "healing herself and all allied champions"            -> 4.0
#   Milio R Breath of Life "healing ... nearby allied champions"        -> 4.0
#   Janna R Monsoon "healing herself and nearby allies every 0.25s"     -> 4.0
#   Seraphine W Surround Sound "... increased for each ally"            -> 3.0
#   Fiora R Grand Challenge "heals Fiora and all allies within the area" -> 2.0
#
# Schema: _AOE_HEAL_TARGETS[champion_id][spell_key] = assumed_targets (float)
def _build_aoe_heal_targets() -> dict[str, dict[str, float]]:
    """Build the AOE-heal target-multiplicity registry via setdefault.

    Returns a fresh dict of champion_id -> spell_key -> assumed_targets.
    Uses ``setdefault(champ, {})[spell] = float`` so future waves can
    contribute spells to the same champion without clobbering prior entries
    (the same builder pattern as ``_build_per_spell_cc_durations``).
    """
    registry: dict[str, dict[str, float]] = {}
    # Soraka R Wish: global team heal ("all allied champions").
    registry.setdefault("Soraka", {})["R"] = 4.0
    # Milio R Breath of Life: AOE heal ("nearby allied champions").
    registry.setdefault("Milio", {})["R"] = 4.0
    # Janna R Monsoon: AOE channel heal ("nearby allies every 0.25 seconds").
    registry.setdefault("Janna", {})["R"] = 4.0
    # Seraphine W Surround Sound: per-ally heal ("increased for each ally").
    registry.setdefault("Seraphine", {})["W"] = 3.0
    # Fiora R Grand Challenge: small Victory Zone ("all allies within the area").
    registry.setdefault("Fiora", {})["R"] = 2.0
    return registry


_AOE_HEAL_TARGETS: dict[str, dict[str, float]] = _build_aoe_heal_targets()


def _aoe_heal_targets_for(champion_id: str, spell_key: str) -> float | None:
    """Return the assumed AOE-heal target count for a champ+spell, or None.

    Forward-marker accessor (no production consumer at ship). Returns the
    representative teamfight ally count an AOE heal lands on, or ``None`` when
    the champion+spell is not a registered AOE / per-ally heal.
    """
    spells = _AOE_HEAL_TARGETS.get(champion_id)
    if not spells:
        return None
    return spells.get(spell_key)


# --- Result types ---------------------------------------------------------


@dataclass(frozen=True)
class AbilitySpellHps:
    """Per-spell healing/shielding throughput for one Q/W/E/R."""

    key: str
    form_name: str
    form_index: int
    rank: int
    cooldown: float
    heal_per_cast: float          # pre-mode (raw, post-scaling)
    shield_per_cast: float        # pre-mode
    casts_per_sec: float
    casts_per_sec_source: str
    mana_uptime_factor: float
    heal_per_sec: float           # heal_per_cast x casts_per_sec x heal_mult
    shield_per_sec: float         # shield_per_cast x casts_per_sec x shield_mult
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "form_name": self.form_name,
            "form_index": self.form_index,
            "rank": self.rank,
            "cooldown": self.cooldown,
            "heal_per_cast": self.heal_per_cast,
            "shield_per_cast": self.shield_per_cast,
            "casts_per_sec": self.casts_per_sec,
            "casts_per_sec_source": self.casts_per_sec_source,
            "mana_uptime_factor": self.mana_uptime_factor,
            "heal_per_sec": self.heal_per_sec,
            "shield_per_sec": self.shield_per_sec,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class AbilityHpsResult:
    """Total champion-ability healing/shielding throughput for a build."""

    champion_id: str
    champion_name: str
    level: int
    item_ids: tuple[str, ...]
    mode: str
    ap: float                     # amp-adjusted AP the heals scale on
    heal_mult: float              # aramHealing; 1.0 outside ARAM
    shield_mult: float            # aramShielding; 1.0 outside ARAM
    total_heal_per_sec: float
    total_shield_per_sec: float
    total_ability_hps: float      # total_heal_per_sec + total_shield_per_sec
    spells: tuple[AbilitySpellHps, ...]
    block_strategy: str = "first"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion_id": self.champion_id,
            "champion_name": self.champion_name,
            "level": self.level,
            "item_ids": list(self.item_ids),
            "mode": self.mode,
            "ap": self.ap,
            "heal_mult": self.heal_mult,
            "shield_mult": self.shield_mult,
            "total_heal_per_sec": self.total_heal_per_sec,
            "total_shield_per_sec": self.total_shield_per_sec,
            "total_ability_hps": self.total_ability_hps,
            "spells": [s.to_dict() for s in self.spells],
            "block_strategy": self.block_strategy,
            "notes": list(self.notes),
        }

    def format_table(self) -> str:
        head = (
            f"{self.champion_name} ({self.champion_id}) - lvl {self.level} "
            f"- mode {self.mode}  [ABILITY HPS]"
        )
        rows = [head, "-" * len(head)]
        rows.append(f"items: {', '.join(self.item_ids) if self.item_ids else '(none)'}")
        rows.append(f"caster ap: {self.ap:.0f}")
        if self.heal_mult != 1.0 or self.shield_mult != 1.0:
            rows.append(
                f"aramHealing x{self.heal_mult:.3f}  "
                f"aramShielding x{self.shield_mult:.3f}"
            )
        rows.append("")
        rows.append(
            f"  {'key':>3}  {'name':<22}  {'rank':>4}  {'cd':>5}  "
            f"{'heal/cast':>9}  {'shld/cast':>9}  {'heal/s':>7}  {'shld/s':>7}"
        )
        rows.append("  " + "-" * 78)
        for s in self.spells:
            rows.append(
                f"  {s.key:>3}  {s.form_name[:22]:<22}  {s.rank:>4}  "
                f"{s.cooldown:>5.1f}  {s.heal_per_cast:>9.1f}  "
                f"{s.shield_per_cast:>9.1f}  {s.heal_per_sec:>7.2f}  "
                f"{s.shield_per_sec:>7.2f}"
            )
        rows.append("")
        rows.append(f"  total_heal_per_sec    {self.total_heal_per_sec:8.2f}")
        rows.append(f"  total_shield_per_sec  {self.total_shield_per_sec:8.2f}")
        rows.append(f"  total_ability_hps     {self.total_ability_hps:8.2f}")
        if self.notes:
            rows.append("")
            for n in self.notes:
                rows.append(f"  note: {n}")
        return "\n".join(rows)


# --- Core scorer ----------------------------------------------------------


def _select_kind_blocks(
    form, kind: str, rank: int, ctx, strategy: str,
    extra_units: Optional[dict] = None,
    bilinear_ctx: Optional[dict] = None,
    level: Optional[int] = None,
) -> tuple[float, bool]:
    """Sum the evaluated heal- or shield-kind blocks per strategy.

    Skips meta blocks (cost reductions / multipliers / HP grants - see
    ``_META_HEAL_SHIELD_RE``). ``strategy="first"`` evaluates only the first
    NON-meta block of ``kind`` (so "Minimum/Maximum/Total" band variants of
    the same heal do not double-count); ``strategy="sum"`` adds every
    non-meta block. ``extra_units`` (v2, opt-in) is threaded to
    ``_eval_heal_shield_block`` to resolve target-relative / missing-HP
    units; ``None`` keeps the v1 lower-bound behavior. Returns
    ``(amount, had_unresolved_unit)``.
    """
    blocks = tuple(
        b for b in form.damage_blocks
        if b.attribute_kind == kind and not _is_meta_heal_shield(b.attribute)
    )
    if not blocks:
        return 0.0, False
    if strategy == "first":
        return _eval_heal_shield_block(
            blocks[0], rank, ctx, extra_units, bilinear_ctx, level,
        )
    total = 0.0
    unresolved = False
    for b in blocks:
        amt, unres = _eval_heal_shield_block(
            b, rank, ctx, extra_units, bilinear_ctx, level,
        )
        total += amt
        unresolved = unresolved or unres
    return total, unresolved


def _empty_result(
    champion_id: str,
    champion_name: str,
    level: int,
    item_ids: tuple[str, ...],
    mode: str,
    ap: float,
    heal_mult: float,
    shield_mult: float,
    block_strategy: str,
    notes: tuple[str, ...],
) -> AbilityHpsResult:
    return AbilityHpsResult(
        champion_id=champion_id,
        champion_name=champion_name,
        level=level,
        item_ids=item_ids,
        mode=mode,
        ap=ap,
        heal_mult=heal_mult,
        shield_mult=shield_mult,
        total_heal_per_sec=0.0,
        total_shield_per_sec=0.0,
        total_ability_hps=0.0,
        spells=(),
        block_strategy=block_strategy,
        notes=notes,
    )


def compute_ability_hps(
    snapshot: DataSnapshot,
    champion_id: str,
    level: int,
    item_ids: Optional[Iterable[str | int]] = None,
    mode: str = "SR",
    augments: Optional[Iterable] = None,
    max_priority: Optional[Iterable[str]] = None,
    form_index_overrides: Optional[dict[str, int]] = None,
    block_strategy: str = "first",
    abilities=None,
    include_passive: bool = True,
    resolve_target_relative: bool = False,
    target_max_hp: float = 0.0,
    target_missing_hp_pct: float = 0.0,
    caster_missing_hp_pct: float = 0.0,
) -> AbilityHpsResult:
    """Compute champion-ability healing + shielding throughput per second.

    Mirrors ``ability_dps.compute_ability_dps`` but evaluates the ``"heal"``
    and ``"shield"`` blocks of each P/Q/W/E/R rather than ``"damage"`` blocks.
    Returns a zero-throughput result for champions with no active-ability
    heal/shield blocks (the common case for most of the roster).

    v2 opt-in args (all default to v1-byte-identical behavior):

    * ``include_passive`` (default True) walks the P key alongside Q/W/E/R,
      resolved at ``rank_at_level("P", level)``. At 16.11.1 the extractor
      emits no P-slot heal/shield blocks, so this is currently a no-op for
      the whole roster - it future-proofs the path. ``False`` = exact v1
      Q/W/E/R-only walk.
    * ``resolve_target_relative`` (default False) resolves target-relative /
      caster-missing-HP units (``% of target's maximum health``, ``% missing
      health``, etc.) against ``target_max_hp`` + ``target_missing_hp_pct`` +
      ``caster_missing_hp_pct``. Default OFF keeps those units UNRESOLVED
      (lower bound 0). With it ON and ``target_max_hp == 0`` the target units
      still resolve to 0 - pass a representative enemy HP for a real lower
      bound. The caster-missing-HP units use ``caster_max_hp`` from the
      resolved build times ``caster_missing_hp_pct``.
    """
    if block_strategy not in _BLOCK_STRATEGIES:
        raise ValueError(
            f"block_strategy must be one of {sorted(_BLOCK_STRATEGIES)}, "
            f"got {block_strategy!r}"
        )
    level = clamp_level(level)

    resolved = build_champion(
        snapshot, champion_id, level, item_ids=item_ids, mode=mode,
        augments=augments,
    )
    champ_id = resolved.champion_id

    heal_mult, shield_mult = _aram_heal_shield_modifiers(snapshot, champ_id, mode)
    safe_heal_mult = heal_mult if heal_mult > 0 else 1.0
    safe_shield_mult = shield_mult if shield_mult > 0 else 1.0

    # Build the per-cast context, then mirror compute_ability_dps's AP
    # amp chain so AP-scaling heals see Rabadon's / Mejai's / HP->AP. The
    # target_* args are zero - heal/shield blocks scale on caster stats,
    # never on target resists/HP.
    ctx = AbilityContext.from_build(
        stats=resolved.stats,
        base_stats=resolved.base_stats,
        target_armor=0.0,
        target_mr=0.0,
        target_max_hp=0.0,
        target_bonus_hp=0.0,
    )
    item_effects = collect_effects(resolved.item_ids)
    ap_from_hp = total_bonus_ap_from_hp(item_effects, ctx.caster_bonus_hp)
    stacked_ap = total_stacked_ap(item_effects)
    ap_total = ctx.ap + ap_from_hp + stacked_ap
    ap_amp = total_ap_amp_multiplier(item_effects)
    hp_ap_amp = total_caster_hp_scaled_ap_amp(item_effects, ctx.caster_max_hp)
    ap_total = ap_total * ap_amp * hp_ap_amp
    ctx = replace(ctx, ap=ap_total)

    # v2 opt-in: resolve target-relative + caster-missing-HP units against the
    # documented per-call assumptions. None keeps the v1 lower-bound contract
    # (those units stay unresolved). Built once from the finalized ctx.
    extra_units = (
        _resolve_extra_units(
            ctx,
            target_max_hp=target_max_hp,
            target_missing_hp_pct=target_missing_hp_pct,
            caster_missing_hp_pct=caster_missing_hp_pct,
        )
        if resolve_target_relative
        else None
    )
    # GAP-2 effects-text HEAL registry (bilinear AP/AD-on-HP) support. Built
    # once from the finalized ctx + the per-call HP assumptions. Caster stats
    # are always available; the target / caster-MISSING HP factors are resolved
    # ONLY under resolve_target_relative (0 otherwise) so a bilinear %-of-HP
    # heal stays gated exactly like its linear sibling. A no-op for every
    # snapshot heal/shield block (they carry no bilinear_terms) -> byte-
    # identical when no synthetic heal block is injected.
    _caster_max_hp = float(getattr(ctx, "caster_max_hp", 0.0) or 0.0)
    # v4 (item 253) AS-aware heal seam: bonus attack speed in PERCENTAGE POINTS
    # (50.0 = 50% bonus AS), matching the "% per 100% bonus AS" / _per_100
    # denominator convention. League's "bonus attack speed" = total AS minus the
    # champion's INNATE base AS (the flat champion-record "attackspeed" stat,
    # e.g. Viego 0.658), NOT resolved.base_stats["as"] which folds the per-level
    # AS growth INTO "base" - per-level AS growth IS bonus AS in League, so the
    # innate-base denominator credits both the per-level and item bonus. A pure
    # caster stat (always resolved); the only AS-scaled heal term (Viego P) gates
    # on its target_max_hp half, so the default resolve_target_relative=False
    # path stays byte-identical (the bilinear product is 0). A missing champion
    # record / zero base AS falls back to 0.0 (the term contributes 0 - an honest
    # lower bound).
    try:
        _innate_base_as = float(
            (snapshot.champion(champ_id).get("stats") or {}).get("attackspeed", 0.0)
            or 0.0
        )
    except Exception:
        _innate_base_as = 0.0
    _total_as = float((resolved.stats or {}).get("as", 0.0) or 0.0)
    _bonus_as_pct = (
        ((_total_as - _innate_base_as) / _innate_base_as * 100.0)
        if _innate_base_as > 0
        else 0.0
    )
    bilinear_ctx = {
        "ap": float(getattr(ctx, "ap", 0.0) or 0.0),
        "bonus_ad": float(getattr(ctx, "bonus_ad", 0.0) or 0.0),
        "total_ad": float(getattr(ctx, "total_ad", 0.0) or 0.0),
        "bonus_as": _bonus_as_pct,
        "caster_max_hp": _caster_max_hp,
        "caster_bonus_hp": float(getattr(ctx, "caster_bonus_hp", 0.0) or 0.0),
        "caster_missing_hp": (
            _caster_max_hp * caster_missing_hp_pct if resolve_target_relative else 0.0
        ),
        "target_max_hp": target_max_hp if resolve_target_relative else 0.0,
        "target_missing_hp": (
            target_max_hp * target_missing_hp_pct if resolve_target_relative else 0.0
        ),
    }
    keys = (("P",) + tuple(SPELL_KEYS)) if include_passive else tuple(SPELL_KEYS)

    snap_abilities = abilities if abilities is not None else load_default()
    try:
        forms_by_key = snap_abilities.get_abilities(champ_id)
    except KeyError:
        return _empty_result(
            champ_id, resolved.champion_name, level, resolved.item_ids, mode,
            ap_total, heal_mult, shield_mult, block_strategy,
            (f"no abilities snapshot entry for {champ_id!r}",),
        )

    mp, _src = _resolve_max_priority(champ_id, max_priority)
    form_idx_map, _fsrc = _resolve_form_index_overrides(
        champ_id, form_index_overrides,
    )

    spells: list[AbilitySpellHps] = []
    total_heal_ps = 0.0
    total_shield_ps = 0.0

    for key in keys:
        forms = forms_by_key.get(key) or ()
        if not forms:
            continue
        form_idx = form_idx_map.get(key, 0)
        if form_idx < 0 or form_idx >= len(forms):
            form_idx = 0
        form = forms[form_idx]
        rank = rank_at_level(key, level, max_priority=mp)
        if rank < 0:
            continue

        heal_per_cast, heal_unres = _select_kind_blocks(
            form, "heal", rank, ctx, block_strategy, extra_units, bilinear_ctx,
            level,
        )
        shield_per_cast, shield_unres = _select_kind_blocks(
            form, "shield", rank, ctx, block_strategy, extra_units, bilinear_ctx,
            level,
        )
        if heal_per_cast <= 0.0 and shield_per_cast <= 0.0:
            continue
        spell_notes: tuple[str, ...] = ()
        if heal_unres or shield_unres:
            spell_notes = (
                "lower bound: a state-dependent unit (missing-HP / target / "
                "per-stack) was not resolved at rest",
            )

        fallback = forms[0] if form_idx != 0 else None
        base_cd = _form_cooldown_at_rank(form, rank, fallback_form=fallback)
        cost = _form_cost_at_rank(form, rank)

        # P (passive) has no measured cast cadence - ``get_spell_casts_per_sec``
        # only accepts Q/W/E/R and raises on "P". A passive heal/shield fires
        # on-hit / on-event, so fall straight through to the cooldown-derived
        # rate (or 0 when the form has no cooldown). Q/W/E/R use the measured
        # rate exactly as v1.
        measured = (
            None if key == "P"
            else get_spell_casts_per_sec(resolved.champion_name, key, mode)
        )
        cps_source = "measured"
        mana_uptime = 1.0
        if measured is None or measured <= 0:
            if base_cd > 0:
                mana_uptime = _mana_uptime_factor(cost, base_cd, ctx, form.resource)
                casts_per_sec = (1.0 / base_cd) * mana_uptime
                cps_source = "theoretical_cooldown"
            else:
                casts_per_sec = 0.0
                cps_source = "none"
        else:
            casts_per_sec = measured

        heal_ps = heal_per_cast * casts_per_sec * safe_heal_mult
        shield_ps = shield_per_cast * casts_per_sec * safe_shield_mult
        total_heal_ps += heal_ps
        total_shield_ps += shield_ps

        spells.append(AbilitySpellHps(
            key=key,
            form_name=form.name,
            form_index=form_idx,
            rank=rank,
            cooldown=base_cd,
            heal_per_cast=heal_per_cast,
            shield_per_cast=shield_per_cast,
            casts_per_sec=casts_per_sec,
            casts_per_sec_source=cps_source,
            mana_uptime_factor=mana_uptime,
            heal_per_sec=heal_ps,
            shield_per_sec=shield_ps,
            notes=spell_notes,
        ))

    notes: list[str] = []
    if not spells:
        notes.append(
            "no active-ability heal/shield blocks for this champion "
            "(no P-slot heal/shield blocks exist in the snapshot at 16.11.1)"
        )
    if mode == "ARAM" and (heal_mult != 1.0 or shield_mult != 1.0):
        notes.append(
            f"ARAM aramHealing={heal_mult:.3f} aramShielding={shield_mult:.3f} "
            f"applied per-side"
        )
    if block_strategy != "first":
        notes.append(f"block_strategy={block_strategy!r}")

    return AbilityHpsResult(
        champion_id=champ_id,
        champion_name=resolved.champion_name,
        level=level,
        item_ids=resolved.item_ids,
        mode=mode,
        ap=ap_total,
        heal_mult=heal_mult,
        shield_mult=shield_mult,
        total_heal_per_sec=total_heal_ps,
        total_shield_per_sec=total_shield_ps,
        total_ability_hps=total_heal_ps + total_shield_ps,
        spells=tuple(spells),
        block_strategy=block_strategy,
        notes=tuple(notes),
    )
