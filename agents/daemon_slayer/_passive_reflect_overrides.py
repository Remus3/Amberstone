"""R49 (2026-06-30) - effects-text-only ON-BEING-HIT reflect damage registry.

Rammus W Defensive Ball Curl reflects magic damage to basic attackers. It was a
documented NOT-seeded case in ``_passive_damage_overrides`` (item 513): "Rammus
W (TOTAL-resist on-being-hit reflect - no caster total-MR _SCALING_TARGETS field
AND wrong cadence for that empowered-AA seam)". This module is that dedicated
reflect seam.

How it differs from ``_passive_damage_overrides`` (the empowered-AA seam):
  - REACTIVE: triggered by INCOMING basic attacks, not an outgoing empowered AA.
  - TOTAL-resist scaling: the magnitude scales on the CASTER's TOTAL armor +
    TOTAL magic resistance (not bonus). The full-armor target (``caster_armor``)
    already existed; the full-MR target (``caster_mr``) is added alongside this
    module in ``_registries._SCALING_TARGETS`` + ``ability_dps.AbilityContext``
    (the documented missing field).
  - cadence is seconds-between-incoming-attacks (``reflect_cadence_s``), so the
    per-proc magnitude amortizes into per-second DPS as ``proc / cadence_s``.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``dps.compute_dps`` /
``burst.compute_burst_damage`` only fold the reflect when the opt-in
``assume_passive_reflect=True`` flag is set. With the flag OFF (the default) the
registry is never read, so every scorer is unchanged. The live default-ON flip
is operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

Modeling lower-bound (documented): the % terms scale on the caster's resolved
build armor/MR, which do NOT include Defensive Ball Curl's OWN active bonus
resists (League recalculates the reflect over the W duration including the
flat + % self-buff; that self-buff lives in ``_passive_resist_overrides`` as the
EHP seam). So the reflect magnitude here is a lower bound until a W-active stat
context feeds the buffed resists - the same resting-lower-bound contract the
other default-OFF seams use.

Keyed ``(champion_id, key, form_index)`` - the same shape as the sibling
override registries.
"""
from __future__ import annotations

from dataclasses import dataclass

# A burst combo exposes the reflector to incoming attacks for a short window;
# the reflect-proc count over that window is window / reflect_cadence_s. 3.0s is
# a documented assumed full-combo + follow-up exposure (operator-tunable,
# Live-game-gated-refinable) - the same midpoint convention as the other burst
# seams' assumed proc counts.
_ASSUMED_REFLECT_BURST_WINDOW_S: float = 3.0

# RANGED-EXPOSURE amortization (G2-12 live calibration, 2026-07-20).
#
# WHY: ``reflect_cadence_s`` (1.0s) and ``_ASSUMED_REFLECT_BURST_WINDOW_S``
# (3.0s) together assert that the CARRIER is taking one incoming basic attack
# every second for the whole fight. That is the MELEE-tank case the Thorns /
# Defensive Ball Curl mechanic is built around (Rammus is attackrange 125; the
# thing auto-attacking him is standing on top of him), and it stays credited at
# full strength here.
#
# It is NOT the RANGED case. A 650-range carry holding Thornmail spends most of
# a fight outside melee reach and is auto-attacked only in the windows where an
# enemy ADC / dive actually reaches her - so a flat 1-incoming-basic-per-second
# assumption over-credits her reflect stream. MEASURED (Caitlyn L14, real live
# build ['2501','3032','3031','3075','6695'] vs armor 60 / MR 40 / 2200 HP):
# seam OFF weighted_dps 219.145, seam ON 238.788 -> the reflect was crediting
# +8.96% of her TOTAL damage output. Operator ruling after seeing it live: too
# high; Thornmail did not contribute anywhere near a tenth of his damage.
#
# WHAT: the exposure factor scales the CREDIT, not the mechanic - melee 1.0
# (byte-identical to the pre-2026-07-20 behavior for every melee carrier,
# including the only registered champion entry, Rammus), ranged
# ``_REFLECT_RANGED_EXPOSURE``. Applied identically to the champion stream and
# the item Thorns stream, in BOTH consumers (``dps.compute_dps`` amortized DPS
# and ``burst.compute_burst_damage`` window damage), so the two never disagree.
#
# VALUE: 0.35 is an operator-tunable midpoint in the same class as
# ``_item_general_dr._GENERAL_DR_UPTIME`` (0.4),
# ``ehp._ASSUMED_INCOMING_AA_SHARE`` (0.5) and
# ``dps._ASSUMED_CASTER_MISSING_HP`` (0.35 = half of the 0.70 cap). It is a
# JUDGEMENT call, not a measured incoming-attack rate - DS has no live
# incoming-attack telemetry. At 0.35 the measured Caitlyn case drops from
# +8.96% to +3.14% of total DPS. Change this ONE literal to retune; the seam is
# still default-OFF (``assume_passive_reflect=False``), so the byte-identical
# baseline is untouched regardless of this value.
_REFLECT_RANGED_EXPOSURE: float = 0.35


def reflect_exposure_factor(is_melee: bool) -> float:
    """Credit multiplier for the reflect stream by wielder attack range.

    ``1.0`` for a melee wielder (the mechanic's intended user - unchanged),
    ``_REFLECT_RANGED_EXPOSURE`` for a ranged wielder, whose fight-long
    exposure to incoming basic attacks is a fraction of the melee case.

    The caller supplies the predicate it already owns: ``dps.compute_dps``
    passes ``CallContext.is_melee`` (``dps.MELEE_RANGE_CEILING`` 350) and
    ``burst.compute_burst_damage`` passes ``rank._champion_is_melee``
    (``MELEE_ATTACKRANGE_CEILING`` 250, the DSV9 shield-cut convention right
    above it). The two thresholds agree on every 16.14.1 champion - the range
    histogram is empty between Nilah 225 and Xayah 525 (``dps.py`` line 78) -
    so no champion is classified differently by the two consumers.
    """
    return 1.0 if is_melee else _REFLECT_RANGED_EXPOSURE


@dataclass(frozen=True)
class PassiveReflectEntry:
    """One hand-authored on-being-hit reflect formula.

    ``base`` is the flat reflect per incoming attack, as a per-ABILITY-rank
    tuple (Rammus W has 5 ranks; the flat half is rank-flat -> a 1-element
    tuple, clamped to its last element at every rank by ``reflect_per_proc``).
    ``caster_armor_pct`` / ``caster_mr_pct`` are % of the caster's TOTAL armor /
    TOTAL magic resistance. ``reflect_cadence_s`` is the assumed seconds between
    incoming basic attacks that trigger the reflect (operator-tunable); the DPS
    seam amortizes the per-proc magnitude as ``proc / cadence_s``.

    ``damage_type`` is one of ``"MAGIC"`` / ``"PHYSICAL"`` / ``"TRUE"``; the
    consumer mitigates the reflect by the matching resistance curve.
    """

    base: tuple[float, ...]
    damage_type: str
    caster_armor_pct: float = 0.0
    caster_mr_pct: float = 0.0
    reflect_cadence_s: float = 1.0
    note: str = ""
    attribute: str = "Reflect"
    # R68: % of the caster's BONUS armor (build armor above the leveled
    # base) - the Thornmail Thorns axis. END-appended with a default so
    # every existing positional construction keeps working.
    caster_bonus_armor_pct: float = 0.0


# (champion_id, key, form_index) -> PassiveReflectEntry.
# Seeded 2026-06-30 against verbatim 16.13.1 effects_descriptions.
_PASSIVE_REFLECT_OVERRIDES: dict[tuple[str, str, int], PassiveReflectEntry] = {
    # Rammus W Defensive Ball Curl: "Whenever Rammus is struck by a basic attack,
    # the attacker is dealt 15 (+ 10% total armor) (+ 10% total magic resistance)
    # magic damage." (16.13.1, parse_status no_damage - effects-text-only.) The
    # flat 15 + the two 10% terms are rank-flat (the W rank scales the self-buff
    # resists, captured in _passive_resist_overrides; the reflect FORMULA itself
    # is rank-independent), so base is a single-element tuple. reflect_cadence_s
    # 1.0 = one assumed incoming basic / s from the focusing attacker
    # (operator-tunable). The % scales on the build's resolved TOTAL armor/MR;
    # W-active self-buff resists are NOT folded here (lower bound - documented).
    ("Rammus", "W", 0): PassiveReflectEntry(
        base=(15.0,),
        caster_armor_pct=10.0,
        caster_mr_pct=10.0,
        damage_type="MAGIC",
        reflect_cadence_s=1.0,
        note=(
            "Defensive Ball Curl: reflects 15 (+ 10% total armor) (+ 10% total "
            "magic resistance) magic to basic attackers; 16.13.1; "
            "reflect_cadence_s 1.0 = assumed 1 incoming basic/s (operator-tunable); "
            "W-active self-buff resists not folded into caster armor/MR here "
            "(lower bound)"
        ),
        attribute="Defensive Ball Curl",
    ),
}


# R68 (2026-07-03) - ITEM-keyed Thorns reflect, same seam. Keyed by item-id
# STRING (the shape resolved.item_ids carries; precedent
# _target_vulnerability_overrides._ITEM_VULN_OVERRIDES). Seeded against
# verbatim Meraki 16.13.1 items_meraki.json passives[name="Thorns"].
# Mirror ids: the DS 16.13.1 pool (items.json data keys) carries Thornmail
# mirrors 223075 (Arena map-30) + 323075; Bramble mirrors 223076/323076 do
# NOT exist in the pool, so they are NOT registered (a phantom id the
# ranker can never surface). Grievous Wounds (3s on champion hit) is NOT
# modeled here - it is a healing debuff, outside this damage lane.
_THORNMAIL_ENTRY = PassiveReflectEntry(
    base=(20.0,),
    damage_type="MAGIC",
    reflect_cadence_s=1.0,
    note=(
        "Thornmail Thorns: 'When struck by a basic attack [[on-hit]], deal "
        "20 (+ 10% bonus armor) magic damage to the attacker' (Meraki "
        "16.13.1); Grievous Wounds (3s vs champions) NOT modeled - healing "
        "debuff, outside this damage lane; reflect_cadence_s 1.0 = assumed "
        "1 incoming basic/s (operator-tunable)"
    ),
    attribute="Thorns",
    caster_bonus_armor_pct=10.0,
)
_BRAMBLE_ENTRY = PassiveReflectEntry(
    base=(10.0,),
    damage_type="MAGIC",
    reflect_cadence_s=1.0,
    note=(
        "Bramble Vest Thorns: 'When struck by a basic attack [[on-hit]], "
        "deal 10 magic damage to the attacker' (Meraki 16.13.1); Grievous "
        "Wounds (3s vs champions) NOT modeled - healing debuff, outside "
        "this damage lane; reflect_cadence_s 1.0 = assumed 1 incoming "
        "basic/s (operator-tunable)"
    ),
    attribute="Thorns",
)

_ITEM_REFLECT_OVERRIDES: dict[str, PassiveReflectEntry] = {
    "3075": _THORNMAIL_ENTRY,
    "223075": _THORNMAIL_ENTRY,  # Arena map-30 Thornmail mirror.
    "323075": _THORNMAIL_ENTRY,  # 32-prefixed Thornmail mirror in the pool.
    "3076": _BRAMBLE_ENTRY,
}

# Display names for consumer notes - the entries share attribute="Thorns"
# (the unique-passive family name), so the note needs the item name here.
_ITEM_REFLECT_NAMES: dict[str, str] = {
    "3075": "Thornmail",
    "223075": "Thornmail",
    "323075": "Thornmail",
    "3076": "Bramble Vest",
}


def reflect_entry(
    champion_id: str, key: str = "W", form_index: int = 0
) -> "PassiveReflectEntry | None":
    """Return the champion's reflect entry, or ``None`` when unregistered.

    A ``None`` return means the ``assume_passive_reflect`` seam adds nothing -
    byte-identical for every champion without a reflect formula.
    """
    if not champion_id:
        return None
    return _PASSIVE_REFLECT_OVERRIDES.get((champion_id, key, form_index))


def reflect_per_proc(
    entry: "PassiveReflectEntry | None",
    caster_total_armor: float,
    caster_total_mr: float,
    rank: int = 0,
    caster_bonus_armor: float = 0.0,
) -> float:
    """Pre-mitigation reflect magnitude per incoming attack.

    ``base[rank]`` (clamped to the last element) + ``caster_armor_pct`` % of the
    caster's TOTAL armor + ``caster_mr_pct`` % of the caster's TOTAL magic
    resistance + ``caster_bonus_armor_pct`` % of the caster's BONUS armor
    (R68 - the Thornmail Thorns axis; END-appended kwarg so every existing
    call keeps its meaning). ``rank`` is the 0-indexed ability rank
    (rank-flat for the seeded Rammus W, so the default 0 is exact).
    """
    if entry is None or not entry.base:
        return 0.0
    idx = max(0, min(rank, len(entry.base) - 1))
    proc = float(entry.base[idx])
    proc += entry.caster_armor_pct / 100.0 * max(0.0, float(caster_total_armor))
    proc += entry.caster_mr_pct / 100.0 * max(0.0, float(caster_total_mr))
    proc += (
        entry.caster_bonus_armor_pct / 100.0
        * max(0.0, float(caster_bonus_armor))
    )
    return proc


def item_reflect_entry(
    item_ids, caster_bonus_armor: float = 0.0
) -> "tuple[str, PassiveReflectEntry] | None":
    """Return ``(item_id, entry)`` for the build's strongest thorn item.

    Thorns is a UNIQUE passive (Bramble Vest is Thornmail's component), so
    a build owning several thorn items is credited ONCE - the strongest
    per-proc at the given caster bonus armor. Returns ``None`` when the
    build owns no registered thorn item, so the ``assume_passive_reflect``
    consumers add nothing (byte-identical for thorn-less builds). Accepts
    int or string ids (normalized via ``str`` - the
    ``_target_vulnerability_overrides`` convention).
    """
    best: "tuple[str, PassiveReflectEntry] | None" = None
    best_proc = 0.0
    seen: set[str] = set()
    for iid in item_ids or ():
        sid = str(iid)
        if sid in seen:
            continue
        seen.add(sid)
        entry = _ITEM_REFLECT_OVERRIDES.get(sid)
        if entry is None:
            continue
        # Item entries scale on bonus armor only (caster_armor_pct ==
        # caster_mr_pct == 0), so total armor/MR of 0 is exact here.
        proc = reflect_per_proc(
            entry, 0.0, 0.0, caster_bonus_armor=caster_bonus_armor
        )
        if best is None or proc > best_proc:
            best = (sid, entry)
            best_proc = proc
    return best
