"""Input hardening for core.lead_projection (lane 8 true-audit, s144 cycle 173).

project_lead's docstring promises "never raises" and a neutral read on garbage,
and phase_for promises a fail-soft 'early'. Measured before this change:

  * a NaN numeric field, or a +inf game time (json.loads accepts the NaN /
    Infinity literals), made the composite NaN, which fell through every band
    test and shipped a CONFIDENT "even / large" directive (and a NaN game time
    picked the 'late' line table); a +inf cs / gold / level was clamped by
    _ratio instead and read as a real (ahead) signal;
  * an int too large for a float (a JSON integer literal, 400 digits) raised
    OverflowError out of project_lead and phase_for;
  * a negative count in the K/D/A string raised ZeroDivisionError
    ("0/-1/0", "-1/0/0") or read a negative tally as clearly ahead
    ("-5/0/0" -> +1.0), and a 400-digit count raised OverflowError;
  * a non-str mode raised AttributeError from project_lead and every
    per-mode accessor;
  * level_benchmark(NaN) returned the level CAP (18.0), and
    expected_gold_earned / spike_eta_seconds returned NaN, where the
    documented clamp is the base level / 0.0.

project_lead raising is not local: dashboard/_state_builder.py catches it
around compute_deterministic, so one bad field blanked the whole deterministic
block (choices, callouts and the lead read) for that tick.
"""

from __future__ import annotations

import math

import pytest

from core import lead_projection as lp

_NAN = float("nan")
_INF = float("inf")
_HUGE = 10 ** 400  # a valid JSON integer literal that no float can hold

# On every benchmark at minute 10 with an even KDA: the canonical "even" fixture
# from tests/test_lead_projection.py::test_neutral_returns_even.
_EVEN = {"game_time_s": 600, "cs": 80, "gold": 3500, "level": 6, "kda": "2/2/2"}


def _without(key: str) -> dict:
    out = dict(_EVEN)
    out.pop(key)
    return out


# --- non-finite numeric fields: treated as absent, never a NaN composite ----

@pytest.mark.parametrize("field", ["cs", "gold", "level"])
@pytest.mark.parametrize("bad", [_NAN, _INF])
def test_non_finite_axis_reads_as_absent(field, bad):
    got = lp.project_lead(dict(_EVEN, **{field: bad}))
    assert got == lp.project_lead(_without(field)), (
        f"{field}={bad!r} must read exactly like a missing {field}"
    )


@pytest.mark.parametrize("bad", [_NAN, _INF])
def test_non_finite_game_time_reads_as_absent(bad):
    got = lp.project_lead(dict(_EVEN, game_time_s=bad))
    assert got == lp.project_lead(_without("game_time_s"))


def test_nan_game_time_does_not_pick_the_late_table():
    got = lp.project_lead(dict(_EVEN, game_time_s=_NAN))
    late_even = set(lp._LINES["even"]["late"])
    assert got["line"] not in late_even


@pytest.mark.parametrize("mode", ["SR", "ARAM", "ARENA"])
def test_inf_game_time_never_yields_a_large_even(mode):
    # +inf minutes times ARAM's 0.0 CS benchmark is NaN; that NaN used to win.
    got = lp.project_lead({"game_time_s": _INF, "level": 6}, mode=mode)
    assert not (got["state"] == "even" and got["magnitude"] == "large")


def test_non_finite_game_time_falls_through_to_game_seconds():
    got = lp.project_lead(dict(_EVEN, game_time_s=_NAN, game_seconds=600))
    assert got == lp.project_lead(_EVEN)


def test_minus_inf_was_already_absent_equivalent():
    # CHARACTERIZATION, not a regression: -inf clamped to -1 on cs / gold (the
    # same as an absent 0 against a positive benchmark) and -inf game time
    # clamped to 0, so these matched the absent read before this change too.
    for field in ("cs", "gold", "game_time_s"):
        got = lp.project_lead(dict(_EVEN, **{field: -_INF}))
        assert got == lp.project_lead(_without(field))
    assert lp.phase_for(-_INF) == "early"


# --- negative counts are not real game state --------------------------------

def test_game_number_rejects_what_is_not_a_game_count():
    for bad in (_NAN, _INF, -_INF, _HUGE, -1, -0.5, True, False, "7", None, [3]):
        assert lp._game_number(bad) is None, bad
    assert lp._game_number(0) == 0.0
    assert lp._game_number(42) == 42.0
    assert lp._game_number(1e308) == 1e308


def test_negative_level_reads_as_absent_not_maximally_behind():
    # At minute 0 the level bench is the spawn level, so an absent level is
    # even and a raw -40 clamped to -1.0 and read as behind.
    state = {"game_time_s": 0, "level": -40, "kda": "0/0/0"}
    got = lp.project_lead(state)
    assert got == lp.project_lead({"game_time_s": 0, "kda": "0/0/0"})
    assert got["state"] == "even"


@pytest.mark.parametrize("field", ["cs", "gold"])
def test_negative_cs_or_gold_reads_as_absent(field):
    # CHARACTERIZATION for cs / gold: a negative value and the absent 0 both
    # hit the -1 clamp against a positive benchmark, so this held before too.
    got = lp.project_lead(dict(_EVEN, **{field: -40}))
    assert got == lp.project_lead(_without(field))


def test_negative_game_time_falls_through_to_game_seconds():
    got = lp.project_lead(dict(_EVEN, game_time_s=-5, game_seconds=600))
    assert got == lp.project_lead(_EVEN)


# --- ints too large for a float ---------------------------------------------

@pytest.mark.parametrize("field", ["game_time_s", "cs", "gold", "level"])
def test_huge_int_field_never_raises(field):
    got = lp.project_lead(dict(_EVEN, **{field: _HUGE}))
    assert got == lp.project_lead(_without(field))


def test_phase_for_huge_int_is_early_not_overflow():
    assert lp.phase_for(_HUGE) == "early"


@pytest.mark.parametrize("bad", [_NAN, _INF, "nan", "inf"])
def test_phase_for_non_finite_is_the_documented_early(bad):
    assert lp.phase_for(bad) == "early"


def test_phase_for_still_classifies_real_times():
    assert lp.phase_for(0) == "early"
    assert lp.phase_for(-30) == "early"
    assert lp.phase_for(900) == "mid"
    assert lp.phase_for(1800.0) == "late"


# --- K/D/A string ------------------------------------------------------------

@pytest.mark.parametrize("kda", ["0/-1/0", "-1/0/0", "0/0/-1", "-5/0/0", "3/-2/1"])
def test_negative_kda_count_is_neutral_not_a_crash(kda):
    assert lp._kda_ratio(kda) == 0.0


@pytest.mark.parametrize("kda", ["0/-1/0", "-1/0/0"])
def test_project_lead_survives_a_negative_kda(kda):
    got = lp.project_lead(dict(_EVEN, kda=kda))
    assert got == lp.project_lead(dict(_EVEN, kda="garbage"))


def test_huge_kda_count_does_not_overflow():
    big = "9" * 400
    assert lp._kda_ratio(f"{big}/0/0") == pytest.approx(1.0)
    assert lp._kda_ratio(f"0/{big}/0") == pytest.approx(-1.0)


def test_kda_characterization_is_unchanged():
    assert lp._kda_ratio("0/0/0") == 0.0
    assert lp._kda_ratio("6/0/4") == pytest.approx(10 / 11)
    assert lp._kda_ratio("0/6/0") == pytest.approx(-6 / 7)
    assert lp._kda_ratio(" 2 / 2 / 2 ") == pytest.approx(2 / 7)


# --- mode argument -----------------------------------------------------------

@pytest.mark.parametrize("bad", [5, None, 1.5, ["ARAM"], b"ARAM", True, "   "])
def test_junk_mode_reads_as_sr_live(bad):
    assert lp.project_lead(_EVEN, mode=bad) == lp.project_lead(_EVEN, mode="SR")
    assert lp.level_curve(bad) == lp.level_curve("SR")
    assert lp.gold_income_per_min(bad) == lp.gold_income_per_min("SR")


@pytest.mark.parametrize("bad", [5, 1.5, ["ARAM"], b"ARAM", True, "   ", "\t"])
def test_junk_mode_is_not_registered(bad):
    # The *_is_registered gates exist so an offline per-mode generator REFUSES
    # a mode it cannot differentiate; junk must not pass as the SR default.
    assert lp.level_curve_is_registered(bad) is False
    assert lp.gold_income_is_registered(bad) is False


@pytest.mark.parametrize("default", [None, ""])
def test_explicit_default_mode_stays_registered(default):
    # CHARACTERIZATION: ``mode or "SR"`` made None and "" the SR default.
    assert lp.level_curve_is_registered(default) is True
    assert lp.gold_income_is_registered(default) is True


def test_mode_is_case_and_whitespace_insensitive():
    state = {"game_time_s": 600, "level": 11, "kda": "2/2/2"}
    assert lp.project_lead(state, mode=" aram ") == lp.project_lead(state, mode="ARAM")
    assert lp.level_curve(" arena\n") == lp.level_curve("ARENA")
    assert lp.level_curve_is_registered(" arena ") is True


def test_blank_mode_is_the_sr_default():
    assert lp.level_curve("   ") == lp.level_curve("SR")
    assert lp.project_lead(_EVEN, mode="") == lp.project_lead(_EVEN, mode="SR")


# --- offline economy helpers: characterization only ---------------------------
# Their NaN behaviour is deliberately NOT changed here:
# tests/test_clamp_expression_ratchet_s144p124.py pins level_benchmark(NaN) to
# the cap, and no live path can hand them a NaN (project_lead now rejects one
# before minutes reach level_benchmark). Filed in the cycle report instead.

def test_live_path_never_hands_level_benchmark_a_nan(monkeypatch):
    seen = []
    real = lp.level_benchmark

    def spy(minutes, mode="SR"):
        seen.append(minutes)
        return real(minutes, mode)

    monkeypatch.setattr(lp, "level_benchmark", spy)
    for bad in (_NAN, _INF, _HUGE):
        lp.project_lead(dict(_EVEN, game_time_s=bad))
    assert seen and all(math.isfinite(m) for m in seen)


def test_economy_characterization_is_unchanged():
    assert lp.level_benchmark(10.0, "SR") == pytest.approx(6.0)
    assert lp.level_benchmark(-3.0, "ARENA") == pytest.approx(3.0)
    assert lp.level_benchmark(_INF, "ARAM") == lp.MAX_CHAMPION_LEVEL
    assert lp.expected_gold_earned(2.0, "ARAM") == pytest.approx(1200.0)
    assert lp.expected_gold_earned(-1.0) == 0.0
    assert lp.spike_eta_seconds(0.0, 450.0) == pytest.approx(60.0)
    assert lp.spike_eta_seconds(500.0, 450.0) == 0.0


# --- the output contract holds over a garbage sweep --------------------------

def test_output_contract_holds_over_a_garbage_sweep():
    values = [_NAN, _INF, -_INF, _HUGE, -_HUGE, -1, 0, 1e308, True, "7", None]
    for field in ("game_time_s", "cs", "gold", "level"):
        for value in values:
            for mode in ("SR", "ARAM", "ARENA", 7):
                out = lp.project_lead(dict(_EVEN, **{field: value}), mode=mode)
                assert set(out) == {"state", "magnitude", "line", "source_tag"}
                assert out["state"] in {"ahead", "even", "behind"}
                assert out["magnitude"] in {"slight", "clear", "large"}
                assert isinstance(out["line"], str) and out["line"]
