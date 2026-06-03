"""2026-06-03 (GAP 2) - effects-text CHAMPION-INNATE CC-MITIGATION registry.

The SEVENTH survivability axis, and the FIRST that is NOT an Effective-HP term at
all - it feeds the CC-blended discount, not the EHP numerator/denominator. The
six prior axes (heal + shield THROUGHPUT, a flat-% damage-reduction DENOMINATOR
multiplier, a resist-stat DENOMINATOR add, a death-triggered second-life
NUMERATOR multiplier, all SELF, plus the ALLY-targeted resist + revive grants)
all move a champion's Effective HP. This registry moves the OTHER survivability
lever the engine already models: ``cc_blended_ehp`` discounts a champion's EHP by
the enemy CC pressure she eats (CC she cannot act through erodes effective
survivability). A champion with an INNATE tenacity / crowd-control-immunity
ABILITY eats LESS of that pressure, so her CC-adjusted EHP should be discounted
LESS. The clean half of the "guaranteed-survival" family the ally-grant registry
(item 289) and the DR registry both flagged as excluded: the CC-survival half is
a finite DURATION scale (a tenacity fraction), unlike the damage-immunity half
(invulnerability / stasis = infinite EHP), which stays a different, unmodeled
seam.

This is the CHAMPION-ability sibling of the two tenacity sources the cc_blended
discount already credits:
  - ``_item_tenacity`` (item 236): flat per-ITEM tenacity (Mercury's / Sterak's).
  - ``cc_pressure._TENACITY_MAP`` (ARAM): the per-champion ARAM mode tenacity STAT.
Neither covers a champion's tenacity / CC-immunity ABILITY (Garen W's 60%
tenacity burst, Olaf R's full CC immunity, Malzahar P's CC immunity). This
registry is that third source, combined MULTIPLICATIVELY with the item source on
the same ``ehp.effective_cc_duration`` seam (League tenacity stacks
multiplicatively: each source reduces the REMAINING CC duration).

The CONSUMER seam is the existing cc_blended path: ``compute_ehp`` gains
``apply_champion_tenacity`` (default False = byte-identical). When on AND an enemy
comp is supplied, the champion tenacity fraction shrinks ``enemy_cc_pressure_s``
exactly like the item-tenacity credit, raising ``cc_blended_ehp`` (and re-ranking
``rank_items_by_ehp(score_by="cc_blended")`` - a CC-survival item is worth
marginally less to a champion who is already innately CC-resistant). Route-
reachable on ``/ehp`` / ``/rank-tank`` / ``/hybrid`` / ``/rank-bruiser``. The
default-on flip stays the Phase D job (a live "saner not different" re-rank).

DEFAULT BEHAVIOR IS BYTE-IDENTICAL: ``champion_cc_tenacity_fraction`` returns 0.0
when ``apply_champion_tenacity`` is False, and the consumer combines a 0.0
fraction as the no-op ``(1 - 0.0)`` multiplier. Opt-in everywhere (mirrors
``apply_build_tenacity`` / ``apply_passive_resist`` / ``apply_passive_revive``).

EXHAUSTIVE roster scan (all 171 champs, every ability form whose
effects_descriptions carry a SELF tenacity / crowd-control-immunity that is a
sustained DEFENSIVE uptime, not a cast-bound dash window). The clean self set is:

  - Garen W Courage: "For the first 0.75 seconds, Garen additionally grants
    himself a shield and 60% tenacity." A real 60% tenacity STAT for a short
    window -> amortized at the brief-window midpoint. Flat (all W ranks).
  - Olaf R Ragnarok: "Active: Olaf becomes enraged for 3 seconds, cleansing
    himself of all crowd control and becoming immune to them..." Full (100%) CC
    immunity for a 3s active on a 100/90/80s cooldown -> amortized at the
    active-ult midpoint. Flat.
  - Malzahar P Void Shift: "Malzahar gains crowd control immunity and 90% damage
    reduction." A passive CC immunity that is up until he takes damage / acts
    aggressively -> amortized at the passive midpoint (above an active ult, below
    a permanent stat). Flat. (The 90% damage reduction is the SEPARATE
    ``_passive_mitigation_overrides`` axis; only the CC immunity is THIS axis.)

Documented EXCLUSIONS (scanned, deliberately NOT seeded - with the reason class):
  - CAST-BOUND dash / channel CC-immunity (Sion R Unstoppable Onslaught, Warwick
    R Infinite Duress, Pantheon R Grand Starfall, Kled R Chaaaaaaaarge!!! + P
    dismount, Galio R Hero's Entrance, Briar R Certain Death): the CC immunity
    lasts only during the ability's OWN dash / channel and exists to land the
    engage, not to survive a sustained CC chain. Crediting it as fight-long
    tenacity would overstate the defensive value (the same "offensive window, not
    added survivability" exclusion class the revive registry used for the
    decaying-frenzy passives). A future engage-window seam could model it; it is
    not a defensive tenacity uptime.
  - SPELL-SHIELD / block-one mechanics (Fiora W Riposte's timed damage+CC block,
    Morgana E Black Shield's single-CC absorb): a binary block of ONE incoming CC
    instance, not a duration scale on every CC. This is the separate spell-shield
    sub-axis (a probabilistic CC-INSTANCE negation), deliberately not folded into
    the multiplicative-tenacity seam.
  - ALLY-TARGETED CC mitigation (Milio R's ally tenacity grant + cleanse, Morgana
    E Black Shield on an ally): rides a TEAMMATE, so it belongs to the
    ``_passive_ally_grant_overrides`` ally domain (a different consumer that
    scores the protected ally), not this SELF caster registry.
  - ONE-TIME CLEANSE (Kled P dismount, Alistar R Unbreakable Will's cleanse):
    removes the CC currently on the champion ONCE; it is not a tenacity that
    shortens future CC over a window. The Alistar R 45/55/65% incoming-damage
    reduction is the ``_passive_mitigation_overrides`` axis, not this one.
  - FALSE POSITIVE: Bard R Tempered Fate "Epic monsters and turrets ... immune to
    crowd control" describes the TARGETS exempt from his stun, not a Bard self
    grant.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._passive_resist_overrides import _value_at_level

# Operator-tunable amortization midpoints: the expected fraction of the modeled
# fight's incoming CC that the window negates. Documented + conservative; Phase D
# feeds a live uptime without re-authoring. Parallel to
# ``_passive_resist_overrides._ACTIVE_RESIST_PROB`` (0.3) and the revive midpoints.
_CC_IMMUNITY_ACTIVE_PROB = 0.3   # a deliberate 3s defensive ult pop (Olaf R)
_CC_IMMUNITY_PASSIVE_PROB = 0.4  # a passive immunity up until hit (Malzahar P)
_BRIEF_TENACITY_PROB = 0.15      # a sub-second tenacity burst tied to a steroid (Garen W)


@dataclass(frozen=True)
class CcMitigationEntry:
    """One hand-authored effects-text SELF champion CC-mitigation grant.

    ``tenacity_pct`` is the NOMINAL tenacity PERCENT the ability confers (a flat
    float, or a per-ABILITY-RANK tuple when ``rank_scaled``): a real tenacity stat
    (Garen W 60) or a full crowd-control immunity expressed as 100. The EFFECTIVE
    contribution is ``(tenacity_pct / 100) * conditional_probability`` - the
    amortized expected fraction of incoming CC the window shortens.

    ``conditional_probability`` amortizes a short active / a conditional passive by
    its expected uptime+success midpoint (a permanent stat would use 1.0).

    ``rank_scaled`` (item 267 convention): ``tenacity_pct`` is a per-ABILITY-RANK
    tuple resolved from champion level via engine-default skill priority.
    ``level_scaled``: a per-CHAMPION-LEVEL tuple read at ``level-1``. Mutually
    exclusive; rank is checked first. (Both seeds are flat at the active patch.)
    """

    tenacity_pct: float | tuple[float, ...] = 0.0
    conditional_probability: float = 1.0
    rank_scaled: bool = False
    level_scaled: bool = False
    attribute: str = "CC Mitigation"
    note: str = ""


# (champion_id, key, form_index) -> CcMitigationEntry. Keyed for parity with the
# self heal/shield/DR/resist/revive + ally-grant registries. Seeded 2026-06-03
# against verbatim effects_descriptions at patch 16.11.1.
_CHAMPION_CC_MITIGATION_OVERRIDES: dict[tuple[str, str, int], CcMitigationEntry] = {
    # Garen W Courage: "For the first 0.75 seconds, Garen additionally grants
    # himself a shield and 60% tenacity." A real 60% tenacity STAT, but only for a
    # 0.75s window of the W -> amortized at the brief-window midpoint. Flat (all
    # W ranks grant 60%). The shield half is ability_hps throughput, NOT this axis.
    ("Garen", "W", 0): CcMitigationEntry(
        tenacity_pct=60.0,
        conditional_probability=_BRIEF_TENACITY_PROB,
        note="Courage: 60% tenacity for the first 0.75s of W (flat all ranks); amortized at the brief-window midpoint; the shield is ability_hps throughput",
        attribute="Courage",
    ),
    # Olaf R Ragnarok: "Active: Olaf becomes enraged for 3 seconds, cleansing
    # himself of all crowd control and becoming immune to them..." Full (100%) CC
    # immunity for a 3s active on a 100/90/80s CD -> amortized at the active-ult
    # midpoint. Flat (the immunity is total at every R rank; only the CD shortens).
    # The passive bonus armor/MR is the SELF resist axis (_passive_resist), not this.
    ("Olaf", "R", 0): CcMitigationEntry(
        tenacity_pct=100.0,
        conditional_probability=_CC_IMMUNITY_ACTIVE_PROB,
        note="Ragnarok: 100% CC immunity for the 3s active (flat all R ranks); amortized at the active-ult midpoint; the passive armor/MR is the _passive_resist axis",
        attribute="Ragnarok",
    ),
    # Malzahar P Void Shift: "Malzahar gains crowd control immunity and 90% damage
    # reduction." A passive immunity that is up until he is hit / acts -> amortized
    # at the passive midpoint (above an active ult, below a permanent stat). Flat.
    # The 90% damage reduction is the SEPARATE _passive_mitigation axis.
    ("Malzahar", "P", 0): CcMitigationEntry(
        tenacity_pct=100.0,
        conditional_probability=_CC_IMMUNITY_PASSIVE_PROB,
        note="Void Shift: 100% CC immunity (passive, up until hit); amortized at the passive midpoint; the 90% damage reduction is the _passive_mitigation axis",
        attribute="Void Shift",
    ),
}

__all__ = [
    "CcMitigationEntry",
    "_CHAMPION_CC_MITIGATION_OVERRIDES",
    "champion_cc_tenacity_fraction",
    "_CC_IMMUNITY_ACTIVE_PROB",
    "_CC_IMMUNITY_PASSIVE_PROB",
    "_BRIEF_TENACITY_PROB",
]


def champion_cc_tenacity_fraction(
    champion_id: str, level: int, apply_champion_tenacity: bool
) -> float:
    """Return the combined INNATE tenacity FRACTION in ``[0.0, 1.0)`` for a champ.

    Sums, over every registered self CC-mitigation grant matching ``champion_id``,
    the effective per-entry tenacity ``(tenacity_pct(level) / 100) * prob``, and
    STACKS them MULTIPLICATIVELY per League's tenacity rule (each source reduces
    the REMAINING CC duration): ``1 - prod(1 - eff_frac_i)``. The result is the
    combined fraction the consumer scales the eaten CC by ``(1 - fraction)`` -
    exactly the ``_item_tenacity.total_item_tenacity`` shape, so the two compose on
    the same ``effective_cc_duration`` seam.

    When ``apply_champion_tenacity`` is False (the default) the fraction is 0.0 -
    byte-identical.
    """
    if not apply_champion_tenacity:
        return 0.0
    cid = str(champion_id)
    lvl = int(level)
    remaining = 1.0
    for (entry_cid, _key, _form), entry in _CHAMPION_CC_MITIGATION_OVERRIDES.items():
        if entry_cid != cid:
            continue
        pct = _value_at_level(
            entry.tenacity_pct, lvl, entry.level_scaled,
            key=_key, rank_scaled=entry.rank_scaled,
        )
        eff = max(0.0, min(1.0, (pct / 100.0) * float(entry.conditional_probability)))
        if eff:
            remaining *= (1.0 - eff)
    return 1.0 - remaining
