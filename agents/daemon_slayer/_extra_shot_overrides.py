"""Extra-shot PROC behaviour - the half of an every-AA second shot that a
damage registry cannot express (RM-42 follow-on, 2026-08-04).

`_passive_damage_overrides` carries a second shot's DAMAGE. It has no channel
for the two things such a shot ALSO does, and both change item valuation more
than the damage does:

  * it APPLIES ON-HIT EFFECTS - so every `every_n_attacks` item proc in the
    build fires more often than once per basic attack, and
  * it CRITICALLY STRIKES on its own roll - so the shot's damage carries the
    build's crit expectation instead of being flat.

Crediting only the damage is what left RM-42's ordering claim open at ENGINE
1.273.0: a flat physical addend folded onto the attack clock raises the value
of ATTACK SPEED, which is exactly what the on-hit items already carried, so
Akshan's crit core did not move (Hexoptics C44 went #19 -> #18).

SCOPE. This registry is deliberately NOT "every champion with a second hit".
The entry bar is the same one `_AA_ROUTED_ON_HIT_KEYS` uses - the shot must
land on EVERY basic attack with no internal cooldown, no mark to consume and no
empowered-first-hit gate - because `on_hit_applications` is a steady-state
multiplier on the attack count and a periodic shot would be over-credited by
it. A champion belongs here only if it is already on that allowlist.

CONSUMER: `dps.compute_dps(apply_extra_shot_procs=True)` - DEFAULT-OFF, and
reachable from `rank.rank_items` / `POST /rank` / `core.daemon_slayer_client`.
With the flag omitted nothing here is imported or read.

PAIRING, and it is a real caveat rather than a formality: this seam and
`apply_passive_damage` model two halves of ONE physical event. Arming this one
alone credits the shot's PROCS and its crit-scaled damage without... nothing -
the crit term multiplies the passive damage, which only exists when
`apply_passive_damage` is also on. So this seam ON and that one OFF gives the
proc half only, which is a coherent but PARTIAL model. Flip them together when
the default-ON question is finally asked; `test_extra_shot_procs_rm42.py` pins
the two-flag interaction so the partial case cannot ship unnoticed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtraShotEntry:
    """One champion's every-AA extra shot, described by what it DOES.

    ``on_hit_applications`` is the number of ADDITIONAL on-hit applications
    per basic attack (1.0 = the shot applies on-hit exactly once more). It
    scales only the ``every_n_attacks`` proc branch in
    ``dps._periodic_proc_dps``; time-driven procs are untouched, because a
    second shot does not make a Sunfire aura tick faster.

    ``can_crit`` says the shot rolls its own critical strike. When True the
    champion's registered passive-damage magnitude is scaled by the SAME
    ``(1 + crit * crit_bonus)`` factor the base auto-attack uses.
    """

    on_hit_applications: float
    can_crit: bool
    attribute: str
    note: str


# Akshan P Dirty Fighting. DDragon 16.15.1, verbatim:
#   "Whenever Akshan uses a basic attack, he fires an additional shot after a
#    delay that deals 50% AD physical damage, increased to 100% AD against
#    minions."
#   "The additional shot applies on-hit effects, triggers on-attack effects,
#    and can critically strike[ for (22.5% + 12%) bonus damage. ][ 100% base
#    damage + 30% bonus critical damage. ]"
#
# on_hit_applications = 1.0 is read straight off "applies on-hit effects,
# triggers on-attack effects" for a shot that fires on EVERY basic attack: one
# extra application, not a fraction and not two.
#
# can_crit = True with NO bespoke multiplier, and that is a deliberate refusal.
# The crit clause ships TWO bracketed variants in the same string - "(22.5% +
# 12%) bonus damage" and "100% base damage + 30% bonus critical damage" - which
# are alternate renderings the tooltip selects between, not a single authored
# number this registry could quote. Picking one would be inventing a value the
# data does not unambiguously state. So the shot is credited with the engine's
# OWN standard crit expectation, which is what "can critically strike" means by
# default and is the least-invention reading. If a wiki-verified bespoke
# multiplier is ever established, it belongs as a new field here, NOT as a
# tuned fudge on the damage magnitude in _passive_damage_overrides.
EXTRA_SHOT_OVERRIDES: dict[str, ExtraShotEntry] = {
    "Akshan": ExtraShotEntry(
        on_hit_applications=1.0,
        can_crit=True,
        attribute="Dirty Fighting",
        note=(
            "Second shot on every basic attack: applies on-hit effects and "
            "triggers on-attack effects (one extra application), and rolls its "
            "own critical strike. Crit uses the engine's standard "
            "(1 + crit * crit_bonus) - DDragon ships two bracketed variants of "
            "the bonus and neither is quotable as the number."
        ),
    ),
}


def extra_shot_entry(champion_id: str) -> ExtraShotEntry | None:
    """Return the champion's extra-shot entry, or ``None``.

    ``None`` for every unregistered champion, which is what makes the seam
    byte-identical for them even with the flag armed.
    """
    return EXTRA_SHOT_OVERRIDES.get(champion_id)


def on_hit_attack_multiplier(champion_id: str) -> float:
    """Multiplier on the ATTACK COUNT that drives ``every_n_attacks`` procs.

    ``1.0`` (the exact identity) for an unregistered champion, so the caller's
    arithmetic is unchanged rather than merely equal.
    """
    entry = EXTRA_SHOT_OVERRIDES.get(champion_id)
    if entry is None:
        return 1.0
    return 1.0 + float(entry.on_hit_applications)
