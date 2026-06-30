"""R41 (DIRECTOR REFILL 2026-06-30) - ally mark-detonation magic-damage registry.

An "ally-detonation mark" is a debuff a champion lays on the TARGET that an ALLY
consumes for bonus damage - the mark-enabler's contribution to the TEAM's damage,
NOT her own. It is categorically distinct from the two existing mark registries:
  * ``_ability_amp_overrides`` amplifies only the CASTER's OWN one spell;
  * ``_target_vulnerability_overrides`` is an all-source +X% increased-damage-taken
    multiplier (a percentage on EVERY source's damage).
An ally-detonation mark instead adds a DISCRETE chunk of bonus damage that an ally
deals when it consumes the mark. R12's ``_target_vulnerability_overrides`` module
explicitly handed this seam off: Imperial Mandate's detonation "belongs in an
ally-detonation / current-HP-burst seam ... not this all-source-%amp registry".
R41 is that seam.

PURE registry (no engine imports, like ``_target_vulnerability_overrides``): it
returns the PRE-mitigation raw detonation magic damage. The callers
(``dps.compute_dps`` / ``burst.compute_burst_damage``) apply their own MR
mitigation (the existing magic-routing factor), mode multiplier, magic amp, and
the assumed-ally-proc-rate amortization (``_ASSUMED_ALLY_DETONATION_PROB`` = 0.5 -
assume an ally actually consumes the mark about half the time it is up). Both
``compute_*`` gain an ``assume_ally_detonation`` flag, DEFAULT-OFF and
byte-identical when off (the section-5 default-inert contract); the live
default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md).

Two damage shapes a row can carry:
  * FLAT_MAGIC - a flat bonus that scales with the CASTER's level
    (``flat_lo`` : ``flat_hi`` over levels 1..18). Leona P Sunlight.
  * CURRENT_HP_MAGIC - a fraction of the target's CURRENT health
    (``current_hp_coeff`` x target_current_hp). Schema-supported for a future
    current-HP detonation source; UNSEEDED today (see the NON-FIT note).

DPS vs burst amortization: a detonation is a per-EVENT chunk. ``ally_detonation_
burst_raw`` returns the per-event magic (one consume in the burst window).
``ally_detonation_dps_raw`` divides each source's event magic by its ``cadence_s``
(how often the mark can be re-applied and re-consumed) so a one-shot chunk reads
as a per-second rate - the same time-amortization the takedown / antitank cadence
seams use to express an event as sustained value. Both are then scaled by the
proc-rate prob in the caller.

Seeded (VERIFIED vs patch-16.13.1 champion_abilities.json, Meraki content 25.15):
  * Leona P "Sunlight" (champion_abilities.json data.Leona.P effects_descriptions):
    "Innate: Leona's abilities mark enemies hit for 2.5 seconds, refreshing on
    subsequent hits. Allied champions' damaging attacks and abilities against a
    marked target will consume the mark to deal 32 : 151 (based on level) bonus
    magic damage." -> FLAT_MAGIC, flat_lo=32, flat_hi=151, MAGIC, cadence 2.5s (the
    Sunlight mark/refresh window - a conservative re-proc cadence for DPS; the
    detonation can recur about once per mark cycle).

Handoff EXECUTED (R43, 2026-06-30) - ``_NONFIT_DETONATION_CANDIDATES`` is EMPTY:
  * Imperial Mandate (4005): the R41 directive named it a "10% current HP magic"
    detonation (carried from R12's 16.12.1 note), but that premise was STALE. The
    official Riot DDragon 16.13.1 ``item.json`` shows Imperial Mandate REWORKED to
    "Control: Gain 20 Ability Haste for abilities with Immobilizing effects" +
    "Command: On Immobilizing an enemy champion, mark them as 7% Vulnerable for 4
    seconds" - an all-source damage-amp mark (the 16.12.1 "Coordinated Fire" 10%
    current-HP detonation is GONE; only the stale Meraki mirror, content_patch=None,
    still carries it). R41 recorded it as a non-fit handoff; R43 seeded the reworked
    7% Vulnerable into ``_target_vulnerability_overrides`` (4005 / Arena 224005 /
    ARAM 324005) and removed it from this seam. No live item carries a current-HP
    ally detonation today; future detonation non-fits are recorded here with their
    real mechanic, mirroring the ``_NONFIT_VULN_CANDIDATES`` INERT-with-reason doctrine.
"""
from __future__ import annotations

from dataclasses import dataclass

# Assume an ally consumes the mark about half the time it is live (the
# availability midpoint the antitank / allyamp conditional seams also use).
_ASSUMED_ALLY_DETONATION_PROB = 0.5

# Caster-level endpoints the flat ramp interpolates between (levels 1..18).
_RAMP_MIN_LEVEL = 1
_RAMP_MAX_LEVEL = 18


@dataclass(frozen=True)
class AllyDetonationEntry:
    """One ally mark-detonation source.

    ``source_key`` is a provenance label - the ability slot ("P") for a champion
    mark, or the item id string for an item mark. ``kind`` is "FLAT_MAGIC" |
    "CURRENT_HP_MAGIC". ``flat_lo`` / ``flat_hi`` are the per-event magic damage at
    levels 1 / 18 for a FLAT_MAGIC row (lerp between). ``current_hp_coeff`` is the
    fraction of the target's CURRENT health for a CURRENT_HP_MAGIC row.
    ``cadence_s`` is how often the mark can be re-applied + re-consumed (the DPS
    time-amortization divisor). ``note`` is one-line provenance / verification.
    """

    source_key: str
    kind: str
    flat_lo: float = 0.0
    flat_hi: float = 0.0
    current_hp_coeff: float = 0.0
    cadence_s: float = 0.0
    note: str = ""


def _flat_at_level(lo: float, hi: float, level: int) -> float:
    """Lerp a flat ``lo`` : ``hi`` (based on level) figure over levels 1..18.

    Clamps the level to [1, 18]. ``level=1`` returns ``lo``, ``level=18`` returns
    ``hi``. A flat (``lo == hi``) row is level-independent.
    """
    lvl = level
    if lvl < _RAMP_MIN_LEVEL:
        lvl = _RAMP_MIN_LEVEL
    elif lvl > _RAMP_MAX_LEVEL:
        lvl = _RAMP_MAX_LEVEL
    t = (lvl - _RAMP_MIN_LEVEL) / (_RAMP_MAX_LEVEL - _RAMP_MIN_LEVEL)
    return lo + (hi - lo) * t


# champion_id -> AllyDetonationEntry. A champion ABILITY that lays an
# ally-consumed mark.
_CHAMPION_DETONATION_OVERRIDES: dict[str, AllyDetonationEntry] = {
    "Leona": AllyDetonationEntry(
        source_key="P",
        kind="FLAT_MAGIC",
        flat_lo=32.0,
        flat_hi=151.0,
        cadence_s=2.5,
        note="P Sunlight: allies consume the 2.5s mark for 32:151 (based on "
        "level) bonus magic damage (champion_abilities.json 16.13.1).",
    ),
}

# item-id STRING -> AllyDetonationEntry. An ITEM passive that lays an ally-consumed
# mark. EMPTY: Imperial Mandate 4005 was reworked out of the current-HP detonation
# in 16.13.1 (see _NONFIT_DETONATION_CANDIDATES); no live item carries this today.
_ITEM_DETONATION_OVERRIDES: dict[str, AllyDetonationEntry] = {}

# Non-fit handoff registry: items evaluated for the detonation seam but characterized
# elsewhere. EMPTY since R43 - Imperial Mandate 4005 (the lone prior entry) was a
# 16.13.1 rework to a 7% Vulnerable all-source mark (NOT a current-HP detonation) and
# is now seeded in _target_vulnerability_overrides (R43 executed the R41 handoff).
_NONFIT_DETONATION_CANDIDATES: dict[str, str] = {}


def champion_detonation_for(champion_id: str) -> AllyDetonationEntry | None:
    """Return the champion-ability detonation source for ``champion_id`` or None."""
    if not champion_id:
        return None
    return _CHAMPION_DETONATION_OVERRIDES.get(champion_id)


def item_detonation_for(item_id) -> AllyDetonationEntry | None:
    """Return the item detonation source for ``item_id`` (int or str) or None."""
    return _ITEM_DETONATION_OVERRIDES.get(str(item_id))


def _entry_event_magic(
    entry: AllyDetonationEntry, level: int, target_current_hp: float
) -> float:
    """Pre-mitigation magic damage for ONE detonation event of ``entry``.

    FLAT_MAGIC -> ``_flat_at_level(flat_lo, flat_hi, level)``. The current-HP term
    (``current_hp_coeff`` x ``target_current_hp``) is added for a CURRENT_HP_MAGIC
    row and is zero for a flat row, so a FLAT_MAGIC source ignores the target HP.
    """
    flat = _flat_at_level(entry.flat_lo, entry.flat_hi, level)
    return flat + entry.current_hp_coeff * max(0.0, target_current_hp)


def _sources(champion_id: str, item_ids) -> list[AllyDetonationEntry]:
    """Every active detonation source the wielder owns (champion + build items).

    A unique item id is counted at most once (de-dup guard) so an accidental dup in
    the resolved build list cannot double-apply.
    """
    out: list[AllyDetonationEntry] = []
    champ_entry = champion_detonation_for(champion_id)
    if champ_entry is not None:
        out.append(champ_entry)
    seen: set[str] = set()
    for iid in item_ids or ():
        sid = str(iid)
        if sid in seen:
            continue
        seen.add(sid)
        item_entry = _ITEM_DETONATION_OVERRIDES.get(sid)
        if item_entry is not None:
            out.append(item_entry)
    return out


def ally_detonation_burst_raw(
    champion_id: str, level: int, item_ids=(), target_current_hp: float = 0.0
) -> float:
    """Pre-mitigation per-EVENT detonation magic for the wielder (one consume).

    Sum over the champion's mark source and each registered build item's mark of
    one detonation event's magic damage. Returns 0.0 when the wielder owns no
    registered detonation source - so a caller that gates on
    ``assume_ally_detonation`` stays byte-identical for every unmarked champion /
    build.
    """
    return sum(
        _entry_event_magic(e, level, target_current_hp)
        for e in _sources(champion_id, item_ids)
    )


def ally_detonation_dps_raw(
    champion_id: str, level: int, item_ids=(), target_current_hp: float = 0.0
) -> float:
    """Pre-mitigation detonation magic expressed as a per-SECOND rate.

    Each source's per-event magic divided by its ``cadence_s`` (how often the mark
    can be re-applied + re-consumed), summed. A source with no positive cadence
    contributes 0 (cannot be expressed as a rate). Returns 0.0 for an unmarked
    wielder (the byte-identical default).
    """
    total = 0.0
    for e in _sources(champion_id, item_ids):
        if e.cadence_s > 0.0:
            total += _entry_event_magic(e, level, target_current_hp) / e.cadence_s
    return total


__all__ = [
    "AllyDetonationEntry",
    "champion_detonation_for",
    "item_detonation_for",
    "ally_detonation_burst_raw",
    "ally_detonation_dps_raw",
    "_ASSUMED_ALLY_DETONATION_PROB",
    "_CHAMPION_DETONATION_OVERRIDES",
    "_ITEM_DETONATION_OVERRIDES",
    "_NONFIT_DETONATION_CANDIDATES",
]
