"""2026-06-03 (GAP 2) - effects-text GUARANTEED-SURVIVAL WINDOW registry.

The NINTH survivability axis, and the SECOND EHP-NUMERATOR term (after the item
288 REVIVE registry). Heals + shields are SURVIVABILITY THROUGHPUT
(``ability_hps``); a flat-% DR (``_passive_mitigation_overrides``) divides the
EHP DENOMINATOR; a resist-stat grant (``_passive_resist_overrides``) raises the
armor / MR DENOMINATOR; a REVIVE (``_passive_revive_overrides``) multiplies the
NUMERATOR by a second HP pool. A GUARANTEED-SURVIVAL WINDOW is the sibling of the
revive: for a finite window the champion CANNOT be damaged or killed (she is
untargetable, in stasis, or invulnerable), so she voids ALL incoming damage for
that window. Over the modeled fight that voids a FRACTION of the incoming damage
- a champion who can become un-killable for ``window_s`` of a ``fight_window_s``
fight is worth ``(1 + window_s / fight_window_s)`` times her single-window EHP
when the ability is up. A NUMERATOR multiplier, exactly like the revive.

This is the "guaranteed-survival window (option 2)" the item 288 / 290 / 292
survivability registries repeatedly flagged as the remaining unmodeled seam ("a
binary cannot-be-hit / cannot-die window = infinite EHP for its duration ... a
DIFFERENT unmodeled representation"). The operator chose the BOUNDED additive
EHP-numerator model (the item-288 revive shape) over a divergent uptime model or
a consumer-less pure-data catalog: a window of duration ``window_s`` voids the
``window_s / fight_window_s`` share of the fight's damage (capped at the whole
fight, amortized by availability), so it is FINITE - never literally infinite -
and re-uses the revive's numerator-multiplier wiring.

Why a NEW registry (not the revive registry): mechanically distinct. A revive is
DEATH-TRIGGERED and restores a second HP pool that runs through the armor/MR
curve again; a survival window is ABILITY-CAST and voids damage outright for its
duration (no resist curve, no HP pool - it is a fraction-of-fight avoided). Both
land on the EHP NUMERATOR as ``(1 + extra)`` multipliers and compose
multiplicatively, but the source value (an avoided-fight FRACTION vs a restored
HP fraction) and the trigger (cast vs death) differ, so they stay separate
registries under separate flags.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``apply_survival_window`` defaults False;
with it OFF the multiplier is 1.0 and the EHP math is unchanged. No live :8860
default scorer flips it on; it is opt-in everywhere (mirrors
``apply_passive_revive`` / ``apply_spell_shield`` / ``apply_champion_tenacity``).

RE-RANK note: the window multiplier is a CHAMPION ability (build-independent), so
it scales the EHP NUMERATOR uniformly across the baseline AND every ranked
candidate. Like the revive (a uniform multiplicative scale), the ratio-based
``rank_items_by_ehp`` / ``rank_items_by_hybrid`` sort key is INVARIANT under that
uniform scale -> flipping it on does NOT re-rank an item-ranker; it makes the
per-row EHP scalars accurate.

AVAILABILITY gating (the item-255 ``conditional_probability`` convention): a
survival window is cooldown-gated and only avoids damage when the champion is
both off-cooldown AND actually uses it defensively in the modeled fight, so it is
amortized by an operator-tunable midpoint. A long-cooldown defensive ULT
(Tryndamere R / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R)
is up rarely but spans the fight when it fires -> ``_SURVIVAL_WINDOW_ULT_PROB``.
A short-cooldown untargetable BASIC (Vladimir W / Fizz E / Elise E Rappel / Mel
W) is up most fights but brief -> the higher ``_SURVIVAL_WINDOW_BASIC_PROB``. The
window DURATION is EXACT from the ability text; only the firing midpoint is the
assumption. Routing the trigger to a live cooldown clock is a future (Phase D)
consumer job.

``window_s`` may be flat (all seeds at the active patch) or a per-ABILITY-RANK
tuple (``rank_scaled``) / per-CHAMPION-LEVEL tuple (``level_scaled``), resolved
via ``_value_at_level`` for schema parity with the resist / spell-shield
registries.

EXHAUSTIVE roster scan (all 171 champs, every ability form whose
effects_descriptions carry a SELF window during which the champion is
untargetable / in stasis / invulnerable / cannot die). The clean self set is
exactly these 10 (6 defensive ULTS + 4 untargetable BASICS):

  ULTS:
  - Tryndamere R Undying Rage: "minimum health threshold for 5 seconds" - a
    5s cannot-die window (the canonical cheat-death). window 5.0s.
  - Kindred R Lamb's Respite: a 4s zone granting a "minimum health threshold ...
    invulnerable while remaining in the area when they reach the threshold" - the
    SELF cannot-die benefit (the ally benefit is incidental ally-grant). window 4.0s.
  - Taric R Cosmic Radiance: after a 2.5s descend, "he and nearby allied champions
    become invulnerable for 2.5 seconds" - the SELF invuln (ally portion is
    ally-grant domain, item 289). window 2.5s.
  - Kayle R Divine Judgment (SELF cast): "grants herself or a target allied
    champion invulnerability for 2.5 seconds" - the self cast (ally cast is the
    ally-grant domain, item 289). window 2.5s.
  - Lissandra R Frozen Tomb (SELF cast): "Self Cast: Lissandra instantly entombs
    herself in ice, entering stasis for 2.5 seconds" (the enemy cast is a stun,
    not a self window). window 2.5s.
  - Xayah R Featherstorm: "leaps into the air, becoming ghosted and untargetable
    for 1.5 seconds." window 1.5s.

  BASICS:
  - Vladimir W Sanguine Pool: "becoming untargetable and ghosted for 2 seconds."
    window 2.0s.
  - Elise E Rappel (form_index 1, spider form): "immediately becoming untargetable
    and unable to act, and afterwards vanishing for up to 1.95 seconds." window 1.95s.
  - Fizz E Playful / Trickster: "becoming untargetable, balancing on his trident
    for 0.75 seconds." window 0.75s.
  - Mel W Rebuttal: "a protective barrier around herself for 0.75 seconds,
    becoming invulnerable to non-turret damage." window 0.75s.

Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  - CAST-BOUND OFFENSIVE dash / strike untargetability (Zed R, Camille R, Maokai W,
    Master Yi Q Alpha Strike, Evelynn R, Aurora R, Naafiri W): the untargetability
    is a byproduct of an offensive dash / multi-strike that exists to deal damage,
    not a deployable defensive window. Same exclusion class as item 290 / 292's
    cast-bound engage immunity (Galio R / Sion R / Briar R, also excluded here).
  - PET / CLONE / SUMMON untargetability (Shaco R clone + W box, Wukong E/W clones,
    Azir W Sand Soldier, Elise W spider, Caitlyn W trap, Aphelios Q sentry, Illaoi
    tentacles, Lulu P Pix, Kayn W shadow, Neeko W clone): the untargetable unit is
    a summon, not the champion - it does not protect the caster's HP.
  - POST-DEATH decaying frenzy (Sion P, Karthus P, Kog'Maw P): the untargetable /
    stasis is the post-death window; the champion ALWAYS dies when it ends. Item
    288's revive exclusion class - NOT a survival window (modeling it would wildly
    overstate survival).
  - REVIVE domain (Zac P, Zilean R, Kayn P transform): the untargetable / invuln is
    the death-triggered resurrection STATE (Zac P is already item 288's revive; the
    untargetable is the egg state, not a separate window) or the one-time
    out-of-combat form transformation (Kayn P).
  - ALLY / TARGET / ENEMY-applied (Kalista R Oathsworn invuln, TahmKench R devoured
    ally, Urgot R / Poppy R / Syndra W enemy untargetable, Bard R AoE utility
    stasis): the window rides a different unit, not the SELF caster. The ally
    portions of Kayle R / Taric R / Lissandra R are the ally-grant domain (item
    289); only the SELF portion is this axis.
  - CONDITIONAL / POSITIONAL / DIRECTIONAL invuln (Xin Zhao R invuln only vs
    far-away champions, Pantheon E invuln only from the target direction, Gwen W
    untargetable only to enemies outside the mist): not a clean all-damage window -
    it is gated on enemy position, a different (target-state) seam. Gwen W's flat
    resist half is already in ``_passive_resist_overrides``.
  - SUSTAINED ATTACH-STATE (Yuumi W): untargetable for most of the game while
    attached to a host; not a finite cooldown-gated window (modeling it as an EHP
    multiplier would massively overstate). She acts via the host, not as a unit.
  - WINDUP-ONLY stasis before an escape (Ekko R Chronobreak ~0.5s cast-start stasis
    then heal+teleport, Ryze R arrival untargetable): the defensive value is the
    heal / teleport (a different axis), not the incidental sub-second windup; Yone E
    parks an untargetable BODY while the controlled SPIRIT stays vulnerable.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_resist_overrides import _value_at_level

# Operator-tunable availability midpoints: the expected fraction of the modeled
# fight in which the survival window is BOTH off-cooldown AND used defensively.
# Conservative + documented; Phase D feeds a live cooldown clock without
# re-authoring. Parallel to the item-288 _REVIVE_PROB (0.4) and the item-292
# spell-shield midpoints, but here gating a cast-able damage-void window.
_SURVIVAL_WINDOW_ULT_PROB = 0.35    # long-cooldown defensive ult (Tryndamere R / Kindred R / Taric R / Kayle R self / Lissandra R self / Xayah R)
_SURVIVAL_WINDOW_BASIC_PROB = 0.5   # short-cooldown untargetable basic (Vladimir W / Fizz E / Elise E Rappel / Mel W)


@dataclass(frozen=True)
class SurvivalWindowEntry:
    """One hand-authored effects-text SELF guaranteed-survival window.

    ``window_s`` is the duration (seconds) during which the champion cannot be
    damaged or killed (untargetable / stasis / invulnerable). It is EXACT from the
    ability text. A flat float (all seeds at the active patch), or a
    per-ABILITY-RANK tuple (``rank_scaled``) / per-CHAMPION-LEVEL tuple
    (``level_scaled``) resolved via ``_value_at_level``.

    The EFFECTIVE contribution is ``min(window_s / fight_window_s, 1.0) *
    conditional_probability`` - the amortized expected fraction of the fight's
    incoming damage the window voids. ``compute_ehp`` multiplies the per-type EHP
    by ``1 + sum(effective)`` (the avoided-damage-fraction NUMERATOR multiplier,
    the item-288 revive shape).

    ``conditional_probability`` amortizes the cooldown-gated cast by its expected
    availability+use midpoint.

    ``rank_scaled`` / ``level_scaled`` (mutually exclusive; rank checked first) -
    schema parity with the resist / spell-shield registries; both seeds flat.
    """

    window_s: float | tuple[float, ...]
    conditional_probability: float = _SURVIVAL_WINDOW_ULT_PROB
    rank_scaled: bool = False
    level_scaled: bool = False
    attribute: str = "Survival Window"
    note: str = ""


# (champion_id, key, form_index) -> SurvivalWindowEntry. Keyed for parity with the
# self heal/shield/DR/resist/revive + ally-grant + cc-mitigation + spell-shield
# registries; ``survival_window_multiplier`` aggregates ALL entries whose key
# champion matches (a window is champion-level for EHP). Seeded 2026-06-03 against
# verbatim effects_descriptions at patch 16.11.1.
_PASSIVE_SURVIVAL_WINDOW_OVERRIDES: dict[tuple[str, str, int], SurvivalWindowEntry] = {
    # Tryndamere R Undying Rage: "Active: Tryndamere becomes enraged, instantly
    # gaining Fury and a minimum health threshold for 5 seconds." A 5s cannot-die
    # window (health cannot drop below the threshold) - the canonical cheat-death.
    # A health-FLOOR rather than untargetable, but functionally a guaranteed-
    # survival window (he survives the 5s regardless). Long-cooldown ult midpoint.
    ("Tryndamere", "R", 0): SurvivalWindowEntry(
        window_s=5.0,
        conditional_probability=_SURVIVAL_WINDOW_ULT_PROB,
        note="Undying Rage: 5s minimum-health-threshold cannot-die window (cheat-death); amortized at the defensive-ult midpoint",
        attribute="Undying Rage",
    ),
    # Kindred R Lamb's Respite: "creating a sacred zone ... that lasts for 4
    # seconds. All units inside the zone gain a minimum health threshold ... and
    # will also become invulnerable while remaining in the area when they reach or
    # are at the threshold." The SELF cannot-die benefit (the ally benefit inside
    # the zone is incidental ally-grant). window 4.0s. Defensive-ult midpoint.
    ("Kindred", "R", 0): SurvivalWindowEntry(
        window_s=4.0,
        conditional_probability=_SURVIVAL_WINDOW_ULT_PROB,
        note="Lamb's Respite: 4s no-death zone (self cannot-die benefit; ally portion is the ally-grant domain); amortized at the defensive-ult midpoint",
        attribute="Lamb's Respite",
    ),
    # Taric R Cosmic Radiance: "calls down a star ... over 2.5 seconds. Afterwards,
    # he and nearby allied champions become invulnerable for 2.5 seconds." The SELF
    # 2.5s invuln (the ally portion is the _passive_ally_grant_overrides domain,
    # item 289). The 2.5s telegraph delay is not part of the window. window 2.5s.
    ("Taric", "R", 0): SurvivalWindowEntry(
        window_s=2.5,
        conditional_probability=_SURVIVAL_WINDOW_ULT_PROB,
        note="Cosmic Radiance: 2.5s invulnerability (self portion; the ally invuln is the ally-grant domain); amortized at the defensive-ult midpoint",
        attribute="Cosmic Radiance",
    ),
    # Kayle R Divine Judgment (SELF cast): "Kayle grants herself or a target allied
    # champion invulnerability for 2.5 seconds." The self cast is a 2.5s invuln (the
    # ally cast is the _passive_ally_grant_overrides domain, item 289 - same
    # dual-domain split as Morgana E in item 292). window 2.5s.
    ("Kayle", "R", 0): SurvivalWindowEntry(
        window_s=2.5,
        conditional_probability=_SURVIVAL_WINDOW_ULT_PROB,
        note="Divine Judgment (self cast): 2.5s invulnerability; the ally cast is the ally-grant domain; amortized at the defensive-ult midpoint",
        attribute="Divine Judgment",
    ),
    # Lissandra R Frozen Tomb (SELF cast): "Self Cast: Lissandra instantly entombs
    # herself in ice, entering stasis for 2.5 seconds and healing herself..." (the
    # enemy cast is a 1.5s stun, not a self window). The 2.5s self stasis is a clean
    # guaranteed-survival window. window 2.5s.
    ("Lissandra", "R", 0): SurvivalWindowEntry(
        window_s=2.5,
        conditional_probability=_SURVIVAL_WINDOW_ULT_PROB,
        note="Frozen Tomb (self cast): 2.5s self stasis; the enemy cast is a stun (not this axis); amortized at the defensive-ult midpoint",
        attribute="Frozen Tomb",
    ),
    # Xayah R Featherstorm: "Active: Xayah leaps into the air, becoming ghosted and
    # untargetable for 1.5 seconds." A 1.5s untargetable dodge (she fires feathers
    # during it, but the untargetability is a primary defensive use). window 1.5s.
    ("Xayah", "R", 0): SurvivalWindowEntry(
        window_s=1.5,
        conditional_probability=_SURVIVAL_WINDOW_ULT_PROB,
        note="Featherstorm: 1.5s ghosted+untargetable dodge; amortized at the defensive-ult midpoint",
        attribute="Featherstorm",
    ),
    # Vladimir W Sanguine Pool: "Active: Vladimir sinks into a pool of blood,
    # becoming untargetable and ghosted for 2 seconds." A 2s untargetable window on
    # a short cooldown -> the higher basic midpoint. window 2.0s.
    ("Vladimir", "W", 0): SurvivalWindowEntry(
        window_s=2.0,
        conditional_probability=_SURVIVAL_WINDOW_BASIC_PROB,
        note="Sanguine Pool: 2s untargetable+ghosted window; short-cooldown basic midpoint",
        attribute="Sanguine Pool",
    ),
    # Elise E Rappel (form_index 1, spider form): "Elise and her Spiderlings lift up
    # into the air ... immediately becoming untargetable and unable to act, and
    # afterwards vanishing for up to 1.95 seconds." A genuine untargetable dodge /
    # reposition (recastable early). The form_index=1 is the spider-form E. window
    # 1.95s (the max). Short-cooldown basic midpoint.
    ("Elise", "E", 1): SurvivalWindowEntry(
        window_s=1.95,
        conditional_probability=_SURVIVAL_WINDOW_BASIC_PROB,
        note="Rappel (spider form E, form_index 1): up to 1.95s untargetable lift; short-cooldown basic midpoint",
        attribute="Rappel",
    ),
    # Fizz E Playful / Trickster: "Active: Fizz dashes to the target location while
    # becoming untargetable, balancing on his trident for 0.75 seconds." The
    # canonical untargetable juke (used to dodge ults / projectiles). window 0.75s.
    ("Fizz", "E", 0): SurvivalWindowEntry(
        window_s=0.75,
        conditional_probability=_SURVIVAL_WINDOW_BASIC_PROB,
        note="Playful / Trickster: 0.75s untargetable hop (dodge juke); short-cooldown basic midpoint",
        attribute="Playful / Trickster",
    ),
    # Mel W Rebuttal: "Active: Mel forms a protective barrier around herself for
    # 0.75 seconds, becoming invulnerable to non-turret damage..." A 0.75s
    # omnidirectional damage-immunity window. window 0.75s. Short-cooldown basic.
    ("Mel", "W", 0): SurvivalWindowEntry(
        window_s=0.75,
        conditional_probability=_SURVIVAL_WINDOW_BASIC_PROB,
        note="Rebuttal: 0.75s invulnerable-to-non-turret-damage barrier; short-cooldown basic midpoint",
        attribute="Rebuttal",
    ),
}

__all__ = [
    "SurvivalWindowEntry",
    "_PASSIVE_SURVIVAL_WINDOW_OVERRIDES",
    "survival_window_multiplier",
    "_SURVIVAL_WINDOW_ULT_PROB",
    "_SURVIVAL_WINDOW_BASIC_PROB",
]

# Fallback reference fight window (seconds) when the caller passes a non-positive
# value. Mirrors ``ehp._FIGHT_WINDOW_S`` (6.0); passed IN by the consumer to keep
# the reference window single-sourced in ehp.py and avoid a module-load cycle.
_DEFAULT_FIGHT_WINDOW_S = 6.0


def survival_window_multiplier(
    champion_id: str,
    level: int,
    apply_survival_window: bool,
    fight_window_s: float = _DEFAULT_FIGHT_WINDOW_S,
) -> float:
    """Return the EHP NUMERATOR multiplier from effects-text survival windows.

    ``1 + sum(min(window_s(level) / fight_window_s, 1.0) * conditional_probability)``
    over every registered survival window matching ``champion_id``. A window voids
    ALL incoming damage for ``window_s`` of a ``fight_window_s`` fight, so it adds
    that avoided-damage FRACTION to the EHP numerator (the item-288 revive shape).
    The per-window fraction is capped at 1.0 (a window longer than the fight still
    only voids the whole fight once). When ``apply_survival_window`` is False (the
    default) the multiplier is 1.0 - the EHP math is byte-identical.

    The caller multiplies each per-type Effective HP (physical / magical / true) by
    this value; a multiplier > 1.0 = a larger Effective HP = the correct "can
    become un-killable for part of the fight -> survives more" direction. A window
    voids damage of ALL types uniformly (untargetable / invuln to everything), so
    it is a uniform numerator multiplier like the revive.
    """
    if not apply_survival_window:
        return 1.0
    cid = str(champion_id)
    lvl = int(level)
    fw = float(fight_window_s) if fight_window_s and fight_window_s > 0 else _DEFAULT_FIGHT_WINDOW_S
    extra = 0.0
    for (entry_cid, _key, _form), entry in _PASSIVE_SURVIVAL_WINDOW_OVERRIDES.items():
        if entry_cid != cid:
            continue
        win = _value_at_level(
            entry.window_s, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        if win <= 0.0:
            continue
        avoided = min(win / fw, 1.0) * float(entry.conditional_probability)
        extra += max(0.0, avoided)
    return 1.0 + extra
