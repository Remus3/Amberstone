"""Archetype-aware DEFAULT for the ``target_current_hp_pct`` seam (R55).

Pure leaf module - ZERO imports so it can be imported from
``core.daemon_slayer_client`` (the :8860 HTTP boundary) WITHOUT importing the
``agents.daemon_slayer`` engine package in-process. That import is structurally
forbidden by the split-brain guard (tests/test_ds_preview_e2e_p1l21.py
TestNoEngineSplitBrain): the client must reach the engine only over HTTP, never
run a second in-process copy at a possibly-different ENGINE_VERSION. The
resolver is a caller-side policy value (an archetype -> assumed-current-HP
fraction), not engine math, so it lives here in ``core`` next to its only
consumer, the dispatcher.

The ``target_current_hp_pct`` seam (item 374) scales ONLY the three genuine
%-CURRENT-HP item procs (BotRK 3153 / Hellfire Hatchet 4017 / Fulmination
443055) by a caller-supplied fraction of the target's current HP. This module
maps a champion archetype to a conservative DEFAULT value for that fraction:

  * BURST archetypes (assassin / mage / burst): the proc lands while the target
    is near FULL HP (the burst pattern is a single quick combo), so the current
    HP the proc keys off is ~= max HP -> 1.0.

  * SUSTAINED / juggernaut archetypes (carry / adc / marksman / bruiser /
    fighter / juggernaut / skirmisher): the fight grinds the target down over
    many auto-attacks, so the AVERAGE current HP the %-current-HP proc sees
    across the fight is well below full - a conservative ~50% -> 0.5.

  * Non-damage / identity / unknown labels (tank / enchanter / support / "" /
    anything unrecognized): fall back to the seam's own identity default 1.0
    (byte-identical to not modeling the grind-down at all).

This is the DEFAULT-OFF archetype default for the seam: nothing calls it unless
a caller opts in via ``assume_archetype_hp_pct=True``. The 0.5 value is a
conservative DESIGN value pending operator / live validation - the lolmath
baseline for an average-current-HP-over-fight is unreachable (the domain is
parked), so 0.5 is chosen as a defensible midpoint, not a measured constant.
"""
from __future__ import annotations

# Sustained / juggernaut damage archetypes whose %-current-HP procs grind the
# target down over a prolonged fight -> assume ~50% average current HP.
_SUSTAINED = frozenset(
    {
        "carry",
        "dps",
        "adc",
        "marksman",
        "bruiser",
        "fighter",
        "juggernaut",
        "skirmisher",
    }
)


def archetype_target_current_hp_pct(archetype: str) -> float:
    """Return the archetype-aware DEFAULT current-HP fraction for the seam.

    0.5 for a SUSTAINED / juggernaut archetype (target ground down over the
    fight); 1.0 otherwise - BURST archetypes (target near full when the proc
    lands) AND non-damage / identity / unknown labels (identity default,
    byte-identical to not modeling the grind-down). Case-insensitive; a
    ``None`` / empty / unrecognized string resolves to 1.0.
    """
    arch = (archetype or "").strip().lower()
    if arch in _SUSTAINED:
        return 0.5
    return 1.0
