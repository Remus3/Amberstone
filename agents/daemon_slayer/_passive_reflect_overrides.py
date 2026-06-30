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
) -> float:
    """Pre-mitigation reflect magnitude per incoming attack.

    ``base[rank]`` (clamped to the last element) + ``caster_armor_pct`` % of the
    caster's TOTAL armor + ``caster_mr_pct`` % of the caster's TOTAL magic
    resistance. ``rank`` is the 0-indexed ability rank (rank-flat for the seeded
    Rammus W, so the default 0 is exact).
    """
    if entry is None or not entry.base:
        return 0.0
    idx = max(0, min(rank, len(entry.base) - 1))
    proc = float(entry.base[idx])
    proc += entry.caster_armor_pct / 100.0 * max(0.0, float(caster_total_armor))
    proc += entry.caster_mr_pct / 100.0 * max(0.0, float(caster_total_mr))
    return proc
