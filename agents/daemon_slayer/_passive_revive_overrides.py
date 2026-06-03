"""2026-06-03 (GAP 2) - effects-text-only REVIVE / second-life registry.

The FIFTH survivability axis, and the FIRST that is NOT an Effective-HP
DENOMINATOR term. Heals + shields are SURVIVABILITY THROUGHPUT
(``ability_hps``); a flat-% DR (``_passive_mitigation_overrides``) is the
survivability DENOMINATOR MULTIPLIER; a resist-stat grant
(``_passive_resist_overrides``) raises the armor / MR DENOMINATOR directly. A
REVIVE is a different shape entirely: a death-triggered SECOND HP POOL. The
champion takes fatal damage, enters a resurrection state, and (if she survives
the egg / bloblet window) is restored to a fraction of max health and fights on.
Over a fight that is an Effective-HP NUMERATOR multiplier: a champion who can
come back with a second life is worth ``(1 + revived_fraction)`` times her
single-life EHP when the passive is up.

This is the "DIFFERENT non-EHP-denominator seam" the item-272 resist registry
flagged for Anivia P (the -40:20 egg armor / MR is the can't-act resurrection
state - item 272 correctly EXCLUDED it from the resist-DENOMINATOR axis; this
registry models the REVIVE itself, not that egg resist). It is NOT a resist
grant and must NOT be modeled as one.

Why a NEW registry (not the DR / resist registry): a revive multiplies the EHP
NUMERATOR (a second HP pool), whereas DR divides the denominator and a resist
grant raises the armor/MR denominator. ``compute_ehp`` applies the revive
multiplier to the per-type Effective HP AFTER the resist curve (the second life
runs through the SAME armor/MR the first life did, so its EHP is exactly
``revived_fraction`` of the first life's EHP - multiplying the final per-type
EHP is correct). ZERO synthetic block.

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``apply_passive_revive`` defaults False;
with it OFF the multiplier is 1.0 and the EHP math is unchanged. No live :8893
default scorer flips it on; it is opt-in everywhere (mirrors
``apply_passive_mitigation`` / ``apply_passive_resist`` / ``apply_build_tenacity``).

RE-RANK note: the revive multiplier is a CHAMPION passive (build-independent),
so it scales the EHP NUMERATOR uniformly across the baseline AND every ranked
candidate. Like the DR registry (a uniform multiplicative scale), the
ratio-based ``rank_items_by_ehp`` / ``rank_items_by_hybrid`` sort key is
INVARIANT under that uniform scale -> flipping it on does NOT re-rank an
item-ranker; it makes the per-row EHP scalars accurate. (Contrast the resist
registry, which goes through the NON-LINEAR resist curve and CAN re-rank.)

CONDITIONAL gating (the item-255 ``conditional_probability`` convention): a
revive is a long-cooldown passive that must ALSO survive its egg / bloblet
window, so it is amortized by ``_REVIVE_PROB`` - the expected fraction of the
modeled fight in which the revive is BOTH off-cooldown AND survives. The
restored-health FRACTION is EXACT from the ability text (Anivia restores ALL
health; Zac revives at 10:50% by level); only the availability+survival midpoint
is the assumption. Routing the trigger to a live passive-cooldown clock + a real
egg-survival estimate is a future (Phase D) consumer job.

``level_scaled`` (default False) - set True for a revive whose restored FRACTION
scales "based on level" (Zac 10%:50%). The per-level tuple
(``_lerp_per_level(low, high)``) is read at champion LEVEL (``level-1``). A
flat-fraction revive (Anivia, always full health) leaves it False.

EXHAUSTIVE roster scan (all 171 champs, every ability form whose
effects_descriptions carry a death-triggered self-revive / resurrection that
RESTORES a sustained HP pool). The clean SELF-revive set is exactly these 2:
  - Anivia P Rebirth: "upon taking fatal damage, Anivia enters resurrection for
    6 seconds and restores all of her health ... revived with her current
    health." Full-HP second life on a 240s cooldown. revived_fraction 1.0.
  - Zac P Cell Division: "upon taking fatal damage, Zac enters resurrection ...
    splits into four bloblets ... revived with 10:50% maximum health. Zac will
    die once all bloblets are killed." Partial second life on a 300s cooldown,
    gated on bloblet survival. revived_fraction 10:50% by level (level_scaled).

Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason
class):
  - POST-DEATH DECAYING FRENZY (restores HP but it drains every tick, healing is
    0% effective, and the champion ALWAYS dies when it ends - an OFFENSIVE window
    after death, not a sustained second HP pool; modeling it as an EHP multiplier
    would wildly overstate survival): Sion P Glory in Death (100% max health then
    -2.3:24.4/0.264s, no heal), Karthus P Death Defied (7s zombie cast window, NO
    HP restore), Kog'Maw P Icathian Surprise (4s then suicide bomb, NO HP
    restore).
  - ALLY-TARGETED revive (the revive rides an ALLY, not the caster - the
    self-EHP scorer scores the caster, so an ally revive is a different seam, the
    Orianna-E ball-attached class): Zilean R Chronoshift, Renata W Bailout,
    Akshan W Going Rogue (revives dead allies on a Scoundrel takedown).
  - NOT A REVIVE (matched the death-substring but restores no HP pool): Annie P
    (loses stacks on death), Draven P (loses Adoration on death), Aurora R /
    Yone E (death only gates an unrelated recast), Shaco R (clone explodes on
    death), Ekko R Chronobreak (an ACTIVE heal+dash he casts, not a
    death-triggered second life).
  - ITEM revive (Guardian Angel) is item-side, not a champion passive - out of
    this registry's (champion, ability_key, form_index) scope.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_damage_overrides import _lerp_per_level

# Operator-tunable midpoint for a death-triggered REVIVE (the expected fraction
# of the modeled fight in which the revive is BOTH off-cooldown AND survives its
# egg / bloblet window). A revive passive is long-cooldown (Anivia 240s / Zac
# 300s) and conditional on the resurrection form surviving, so 0.4 is a
# conservative "available and survives" midpoint - lower than the form-occupancy
# 0.5 (a revive is rarer than a stance toggle) and above the active-resist 0.3
# (when up, a revive is a guaranteed full/partial second life, not a brief
# uptime). Documented + conservative; Phase D feeds the live passive-cooldown
# state + a real egg-survival estimate without re-authoring. The restored-health
# FRACTION is EXACT from the ability text; only this midpoint is the assumption.
# Parallel to ``_passive_resist_overrides._ACTIVE_RESIST_PROB`` /
# ``_FORM_OCCUPANCY_PROB``.
_REVIVE_PROB = 0.4


@dataclass(frozen=True)
class PassiveReviveEntry:
    """One hand-authored effects-text-only death-triggered self-revive.

    ``revived_hp_fraction`` is the fraction of MAX HP the champion is restored to
    on revive (Anivia 1.0 = all health; Zac a per-level tuple 0.10:0.50 when
    ``level_scaled``). It is EXACT from the ability text - the second life's
    Effective HP is ``revived_hp_fraction`` of the first life's (the revived HP
    runs through the same armor/MR curve), so ``compute_ehp`` multiplies the
    final per-type EHP by ``1 + revived_hp_fraction * conditional_probability``.

    ``conditional_probability`` (default ``_REVIVE_PROB``) amortizes the
    long-cooldown + must-survive-the-resurrection-window gate by its expected
    uptime+survival midpoint.

    ``level_scaled`` (default False) - set True when ``revived_hp_fraction`` is a
    per-level tuple read at champion level (``level-1``), not a flat fraction.
    """

    revived_hp_fraction: float | tuple[float, ...]
    conditional_probability: float = _REVIVE_PROB
    note: str = ""
    attribute: str = "Passive Revive"
    level_scaled: bool = False


# (champion_id, key, form_index) -> PassiveReviveEntry. Keyed for parity with the
# heal/shield/DR/resist registries; ``revive_multiplier`` aggregates ALL entries
# whose key champion matches (a revive is champion-level for EHP). Seeded
# 2026-06-03 against verbatim effects_descriptions at patch 16.11.1.
_PASSIVE_REVIVE_OVERRIDES: dict[tuple[str, str, int], PassiveReviveEntry] = {
    # Anivia P Rebirth: "Innate: Periodically, upon taking fatal damage, Anivia
    # enters resurrection for 6 seconds and restores all of her health. ... If
    # Anivia remains alive by the end of the duration, she is revived with her
    # current health." FULL-HP second life on a 240s cooldown. revived_fraction
    # 1.0 (restores ALL health). The -40:20 (by level) egg armor / MR is the
    # can't-act resurrection-STATE resist that item 272 correctly EXCLUDED from
    # the resist-denominator axis - NOT modeled here either (this entry is the
    # REVIVE, the second HP pool, not the egg resist). Amortized at _REVIVE_PROB
    # (the 240s cooldown + egg survival).
    ("Anivia", "P", 0): PassiveReviveEntry(
        revived_hp_fraction=1.0,
        conditional_probability=_REVIVE_PROB,
        note="Rebirth: restores ALL health (full second life) on a 240s cooldown; revived_fraction 1.0; egg armor/MR is the item-272-excluded can't-act state (not modeled here); amortized at the revive midpoint",
        attribute="Rebirth",
    ),
    # Zac P Cell Division: "Innate - Cell Division: Periodically, upon taking
    # fatal damage, Zac enters resurrection ... splits into four uncontrollable
    # bloblets ... After the duration, Zac is revived with 10 : 50% maximum
    # health. Zac will die once all bloblets are killed." PARTIAL second life on
    # a 300s cooldown, gated on bloblet survival. revived_fraction 10:50% "based
    # on level" -> _lerp_per_level(0.10, 0.50), level_scaled. The transient
    # "instantly restoring 50%" mid-resurrection value is NOT the second-life
    # pool - the FINAL revive HP (10:50% by level) is. Amortized at _REVIVE_PROB
    # (the 300s cooldown + bloblet survival).
    ("Zac", "P", 0): PassiveReviveEntry(
        revived_hp_fraction=_lerp_per_level(0.10, 0.50),
        conditional_probability=_REVIVE_PROB,
        note="Cell Division: revived with 10:50% (based on level) max health on a 300s cooldown, gated on bloblet survival; revived_fraction level_scaled; amortized at the revive midpoint",
        attribute="Cell Division",
        level_scaled=True,
    ),
}

__all__ = [
    "PassiveReviveEntry",
    "_PASSIVE_REVIVE_OVERRIDES",
    "revive_multiplier",
    "_REVIVE_PROB",
]


def _fraction_at_level(
    frac: float | tuple[float, ...], level: int, level_scaled: bool
) -> float:
    """Resolve a revived-HP fraction at the champion level.

    A ``level_scaled`` fraction carries a per-level tuple (``_lerp_per_level``)
    read at ``level-1`` (clamped to the tuple bounds); a flat fraction is its
    float.
    """
    if level_scaled and isinstance(frac, (tuple, list)):
        if not frac:
            return 0.0
        idx = max(0, min(int(level) - 1, len(frac) - 1))
        return float(frac[idx])
    if isinstance(frac, (tuple, list)):
        # Defensive: a tuple on a non-level_scaled entry resolves at its first.
        return float(frac[0]) if frac else 0.0
    return float(frac)


def revive_multiplier(
    champion_id: str, level: int, apply_passive_revive: bool
) -> float:
    """Return the EHP NUMERATOR multiplier from effects-text revive passives.

    ``1 + sum(revived_hp_fraction(level) * conditional_probability)`` over every
    registered revive matching ``champion_id``. A revive restores a second HP
    pool; its Effective HP is ``revived_hp_fraction`` of the first life's (the
    revived HP runs through the same armor/MR curve), so the multiplier scales
    the final per-type EHP. When ``apply_passive_revive`` is False (the default)
    the multiplier is 1.0 - the EHP math is byte-identical.

    The caller multiplies each per-type Effective HP (physical / magical / true)
    by this value; a multiplier > 1.0 = a larger Effective HP = the correct
    "can come back with a second life -> survives more" direction.
    """
    if not apply_passive_revive:
        return 1.0
    cid = str(champion_id)
    lvl = int(level)
    extra = 0.0
    for (entry_cid, _key, _form), entry in _PASSIVE_REVIVE_OVERRIDES.items():
        if entry_cid != cid:
            continue
        frac = _fraction_at_level(
            entry.revived_hp_fraction, lvl, entry.level_scaled
        )
        extra += max(0.0, frac) * float(entry.conditional_probability)
    return 1.0 + extra
