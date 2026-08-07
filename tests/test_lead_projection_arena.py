"""Regression tests for the ARENA lead projection (core.lead_projection).

WHY: dashboard/_deterministic_coaching.py calls project_lead(gs, mode="ARENA"),
but the weight table only carried SR + ARAM, so ARENA silently fell back to the
SR profile. The SR profile's heaviest axis is cs (0.40) and Arena has NO lane CS
at all, so every Arena player carried a permanent -0.40 drag on the composite:
a fed Arena player was coached as if they were losing. Measured on the unfixed
module (15 min, level 16, no parseable kda string):
    {'state': 'behind', 'magnitude': 'clear',
     'line': 'Behind: scale, only fight with your team.'}

These tests pin (1) ARENA owning its own weight profile, (2) a fed Arena state
never reading "behind", (3) a losing Arena state STILL reading "behind" so the
fix is not a tautology, and (4) Arena directives never using lane / CS / wave /
tower vocabulary that does not exist in a 2v2v2v2 round-based mode.
"""

from __future__ import annotations

import pytest

from core import lead_projection as lp
from core.lead_projection import project_lead

# Vocabulary that is meaningful on Summoner's Rift but has no referent in Arena
# (no minions, no lanes, no waves, no towers, no jungler, no baron). Every entry
# is asserted to be PRESENT in the shared _LINES table first, so this list can
# never silently degrade into a no-op guard.
_SR_ONLY_VOCAB = (
    "last-hitting",
    "cs",
    "wave",
    "tower",
    "farm",
    "jungler",
    "baron",
)


def _arena_gs(*, t_s, gold, level, kda=None):
    """Arena-shaped game state. Arena has no lane CS, so cs is never set - that
    is exactly the condition that made the SR fallback invert the verdict."""
    gs = {"game_time_s": t_s, "cs": 0, "gold": gold, "level": level}
    if kda is not None:
        gs["kda"] = kda
    return gs


def _flatten(table):
    """Every directive string in a (state -> phase -> tuple) line table."""
    out = []
    for by_phase in table.values():
        for lines in by_phase.values():
            out.extend(lines)
    return out


# --- (a) ARENA owns a weight profile --------------------------------------

def test_arena_has_its_own_weight_profile():
    assert "ARENA" in lp._WEIGHTS


def test_arena_profile_zeroes_cs_and_keeps_the_shared_weight_mass():
    arena = lp._WEIGHTS["ARENA"]
    assert arena["cs"] == 0.0
    assert set(arena) == set(lp._WEIGHTS["SR"])
    assert sum(arena.values()) == pytest.approx(sum(lp._WEIGHTS["ARAM"].values()))


# --- (b) a fed Arena player is never coached as if they are losing ---------

def test_fed_arena_state_is_not_behind():
    out = project_lead(
        _arena_gs(t_s=900, gold=1200, level=16, kda="12/1/10"), mode="ARENA"
    )
    assert out["state"] != "behind"
    assert out["state"] == "ahead"


def test_fed_arena_state_without_a_kda_string_is_not_behind():
    # The measured defect shape: no parseable kda, so the SR cs axis alone drove
    # the verdict to "behind" for a level-16 player at 15 minutes.
    #
    # FIXTURE CORRECTED 2026-08-06 (RM-158 residual, per-mode levelling curve).
    # The original fixture paired level 16 with gold 1200, which at minute 15 is
    # 77% BELOW the 350/min gold benchmark - a real deficit on a real axis, so
    # "behind" is the right verdict for it. It only read not-behind because the
    # mode-blind SR level bench (6.0 at minute 15, against Arena's measured
    # 14.85) drove the level axis to its +1.0 clamp and swamped the gold drag.
    # The assertion was passing BECAUSE of the defect this slice removes. Gold
    # now sits on its benchmark so "fed" means fed on every axis that exists,
    # and the test proves what its name claims. See also the cs-independence
    # test below, which pins the ACTUAL cs-drag guard in a way no curve change
    # can mask.
    out = project_lead(_arena_gs(t_s=900, gold=5250, level=16), mode="ARENA")
    assert out["state"] != "behind"


def test_arena_verdict_is_independent_of_cs():
    """The real cs-drag guard, stated on the cs axis itself.

    The test above asserts a whole-verdict outcome, so ANY axis can carry it and
    a future weight or benchmark change can make it pass or fail for reasons
    that have nothing to do with cs. This one varies ONLY cs and requires the
    verdict to be byte-identical, which is exactly what ``cs: 0.0`` in the ARENA
    weight row means. It cannot be masked by the level curve, the gold
    benchmark, or the kda proxy.
    """
    base = _arena_gs(t_s=900, gold=5250, level=15, kda="5/2/4")
    for cs in (0, 40, 120, 300):
        probe = dict(base, cs=cs)
        assert project_lead(probe, mode="ARENA") == project_lead(base, mode="ARENA"), cs


def test_arena_and_sr_disagree_on_the_fed_no_cs_state():
    # Guard against a future edit that re-points ARENA at the SR profile.
    gs = _arena_gs(t_s=900, gold=1200, level=16, kda="12/1/10")
    assert project_lead(gs, mode="ARENA") != project_lead(gs, mode="SR")


# --- (c) not a tautology: a losing Arena state still reads behind ----------

def test_losing_arena_state_is_still_behind():
    out = project_lead(
        _arena_gs(t_s=900, gold=200, level=16, kda="0/9/1"), mode="ARENA"
    )
    assert out["state"] == "behind"


def test_even_arena_state_reads_even():
    # FIXTURE CORRECTED 2026-08-06 (RM-158 residual, per-mode levelling curve).
    # "Even" has to mean even on Arena's OWN curve. Level 9 at minute 15 is five
    # levels under the MEASURED Arena mean of 13.83 and under the 14.85 bench -
    # that is a genuine deficit and it now reads behind, correctly. The fixture
    # was labelled even because the mode-blind SR bench put the expected level
    # at 6.0, which made a 5-level Arena deficit look like a 3-level surplus.
    # Level 15 sits on the Arena bench, so this is a real even state.
    out = project_lead(
        _arena_gs(t_s=900, gold=5250, level=15, kda="2/3/1"), mode="ARENA"
    )
    assert out["state"] == "even"


def test_an_arena_level_deficit_still_reads_behind():
    # Non-vacuity for the correction above: the level axis must still be able to
    # DRIVE a behind verdict on its own, with gold and kda neutral. Level 9 is
    # the exact state the old fixture called "even".
    out = project_lead(
        _arena_gs(t_s=900, gold=5250, level=9, kda="2/3/1"), mode="ARENA"
    )
    assert out["state"] == "behind"


# --- (d) no lane / CS vocabulary in any Arena directive -------------------

def test_sr_lines_actually_contain_the_banned_vocabulary():
    # Meta-guard: proves each banned substring is a real SR-ism being replaced,
    # not a string that never appeared and would pass vacuously.
    sr_blob = " ".join(_flatten(lp._LINES)).lower()
    for term in _SR_ONLY_VOCAB:
        assert term in sr_blob, term


def test_arena_line_table_has_no_lane_vocabulary():
    for line in _flatten(lp._ARENA_LINES):
        low = line.lower()
        for term in _SR_ONLY_VOCAB:
            assert term not in low, (term, line)


def test_arena_projections_never_return_lane_vocabulary():
    # Drives the real entry point so the table must actually be WIRED, not just
    # present. The grid spans all three phases and all three states.
    grid = [
        (300, 3000, 8, "6/0/2"),
        (300, 1750, 4, "1/2/1"),
        (300, 300, 2, "0/5/0"),
        (900, 1200, 16, "12/1/10"),
        (900, 5250, 9, "2/3/1"),
        (900, 200, 16, "0/9/1"),
        (1800, 12000, 18, "20/2/15"),
        (1800, 10500, 16, "3/5/2"),
        (1800, 2000, 14, "1/12/2"),
    ]
    seen_states = set()
    for t_s, gold, level, kda in grid:
        out = project_lead(
            _arena_gs(t_s=t_s, gold=gold, level=level, kda=kda), mode="ARENA"
        )
        seen_states.add(out["state"])
        low = out["line"].lower()
        for term in _SR_ONLY_VOCAB:
            assert term not in low, (term, out["line"])
    assert seen_states == {"ahead", "even", "behind"}


def test_arena_lines_keep_the_shared_contract():
    assert set(lp._ARENA_LINES) == set(lp._LINES)
    for state, by_phase in lp._ARENA_LINES.items():
        assert set(by_phase) == set(lp._LINES[state]), state
        for phase, lines in by_phase.items():
            assert len(lines) == 3, (state, phase)
            for line in lines:
                assert line.isascii(), line
                assert len(line.split()) <= 10, line


# --- the unknown-mode fallback must stay safe -----------------------------

def test_unknown_mode_still_falls_back_to_sr():
    gs = {"game_time_s": 600, "cs": 20, "gold": 3500, "level": 6, "kda": "2/2/2"}
    assert project_lead(gs, mode="URF") == project_lead(gs, mode="SR")
