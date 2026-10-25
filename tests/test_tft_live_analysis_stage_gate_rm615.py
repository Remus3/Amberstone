"""RM-615 (X-15): tft/tft_live_analysis.py runs every stage read through the
plausibility gate (core/tft_stage_gate.py) before acting on it, and a
genuine new game bypasses the gate.

Before RM-615 `TftLiveAnalysis.notify_round` (pre-fix tft/tft_live_analysis.py
:476-485) trusted every read:
  * any stage > 2 -> stage <= 2 read was a NEW GAME, so one OCR misread mid
    game cleared the accumulated augments and the last placement;
  * any change reset the round timer, so a flicker re-armed the planning
    vision scan (a paid call) for a round that had not started;
  * `_coach_state` took the misread label, which `_run_analysis` formats
    into the prompt (`stage_round=cs.get("stage_round", "?")`) and `_write`
    publishes;
  * a game left at stage 2 was never detected as over, so its augments
    leaked into the next game.

Shape of the calls, as production makes them: core/tft_worker.py:308-312
calls `notify_coach_state(state)` on every poll and `notify_round(state)`
with the SAME dict only when the raw stage-round changed (initial (0, 0),
:265); coaches/tft_pbe_coach.py:147-151 does the same. Each poll is a fresh
dict (TftStateReader._parse, tft/tft_state_reader.py, which sets "stage",
"round", "stage_round", "game_time_s", "round_event" and "variant").

Two earlier cuts were REFUTED by independent verifiers; W1-W3 below are the
first verifier's wiring reproducers (a round accepted on a poll with no raw
change never reached `_last_round`).

Names used, cited at the fix tree:
  tft/tft_live_analysis.py  TftLiveAnalysis, notify_round, notify_coach_state,
      _is_carousel_or_spectate, _stage_gate (lazy via _gate), _gated,
      _apply_round, _reader_pace, _AUGMENT_ROUNDS, the module-level `time`
      import, _known_augments, _last_placement, _last_round,
      _round_start_time, _scanned_planning, _scanned_mid, _coach_state.
  core/tft_stage_gate.py  QUEUE_TIMINGS, UNMEASURED, WINDOW_READS,
      SWITCH_MIN_READS, SWITCH_MARGIN, PACE_SAFETY, pace_floor_from_table.
  tft/tft_state_reader.py  `time_table` (the set-aware accessor _reader_pace
      reads since S134 M1d), `_TIME_TO_ROUND`, `_TIME_TO_ROUND_SET18`,
      round_schedule, RoundSchedule.fields.
  tft/tft_set.py  resolve_set.
"""
from __future__ import annotations

import types

import pytest

from core import tft_stage_gate as g
from tft import tft_live_analysis as tla
from tft import tft_state_reader


def _mk():
    """A TftLiveAnalysis with no SDK client and no vision reader (the
    tests/test_tft_live_analysis_lane8_cycle43.py:86 shape). `_stage_gate`
    is deliberately NOT set: the gate must come up lazily for objects built
    without __init__, with its pace read from the reader's table."""
    la = tla.TftLiveAnalysis.__new__(tla.TftLiveAnalysis)
    la._last_round = (0, 0)
    la._coach_state = {}
    la._known_augments = ["Pandora's Items", "Cybernetic Uplink"]
    la._last_placement = "Jinx D7"
    la._round_start_time = 0.0
    la._scanned_planning = False
    la._scanned_mid = False
    return la


def _st(stage, rnd, gt, variant="standard", **extra):
    d = {"stage": stage, "round": rnd, "stage_round": f"{stage}-{rnd}",
         "game_time_s": gt, "variant": variant, "round_event": "pvp",
         "is_carousel": False, "level": 6}
    d.update(extra)
    return d


def _poll(la, state):
    """One worker poll in the PRODUCTION call shape (core/tft_worker.py:265
    `_last_sr = (0, 0)`, :308-312): notify_coach_state every poll,
    notify_round only when the RAW stage-round changed."""
    la.notify_coach_state(state)
    sr = (state.get("stage", 0), state.get("round", 0))
    if sr != getattr(la, "_t_raw_sr", (0, 0)):
        la._t_raw_sr = sr
        la.notify_round(state)


def _polls(la, sr, t0, n, variant="standard"):
    t = t0
    for _ in range(n):
        _poll(la, _st(*sr, t, variant=variant))
        t += 1.5
    return t


@pytest.fixture
def clock(monkeypatch):
    """A fake wall clock for the round timer (tft_live_analysis calls
    time.time() for _round_start_time); each read advances it 1 s."""
    now = [1000.0]

    def _time():
        now[0] += 1.0
        return now[0]
    monkeypatch.setattr(tla, "time", types.SimpleNamespace(time=_time, sleep=lambda s: None))
    return now


def test_ocr_backward_glitch_is_not_a_new_game():
    la = _mk()
    _poll(la, _st(4, 2, 820.0))
    started = la._round_start_time
    la._scanned_planning = True
    _poll(la, _st(2, 1, 822.0))             # OCR misread mid game
    assert la._known_augments == ["Pandora's Items", "Cybernetic Uplink"]
    assert la._last_placement == "Jinx D7"
    assert la._last_round == (4, 2)
    assert la._round_start_time == started
    assert la._scanned_planning is True     # no re-armed planning scan
    assert la._coach_state["stage_round"] == "4-2"
    assert (la._coach_state["stage"], la._coach_state["round"]) == (4, 2)


def test_forward_glitch_does_not_reset_the_round_timer():
    la = _mk()
    _poll(la, _st(3, 2, 500.0))
    started = la._round_start_time
    la._scanned_planning = True
    _poll(la, _st(6, 1, 502.0))
    assert la._last_round == (3, 2)
    assert la._round_start_time == started
    assert la._scanned_planning is True
    assert la._coach_state["stage_round"] == "3-2"


def test_real_advance_resets_the_round_timer(clock):
    la = _mk()
    _poll(la, _st(3, 2, 500.0))
    before = la._round_start_time
    la._scanned_planning = True
    la._scanned_mid = True
    _poll(la, _st(3, 3, 545.0))
    assert la._last_round == (3, 3)
    assert la._round_start_time > before
    assert la._scanned_planning is False and la._scanned_mid is False
    assert la._coach_state["stage_round"] == "3-3"
    assert la._known_augments                # an advance clears nothing


def test_genuine_new_game_bypasses_the_gate():
    la = _mk()
    _polls(la, (5, 3), 1300.0, 3)           # the previous game's clock, confirmed
    _poll(la, _st(1, 2, 40.0))              # the game clock restarted ...
    _poll(la, _st(1, 2, 41.5))              # ... and stayed restarted
    assert la._known_augments == []
    assert la._last_placement == ""
    assert la._last_round == (1, 2)
    assert la._coach_state["stage_round"] == "1-2"


def test_new_game_after_a_game_left_at_stage_2_is_detected():
    """Pre-fix the detector needed the old stage > 2, so a game abandoned at
    stage 2 leaked its augments into the next one."""
    la = _mk()
    _polls(la, (2, 3), 400.0, 3)
    _poll(la, _st(1, 1, 5.0))
    _poll(la, _st(1, 1, 6.5))
    assert la._known_augments == []
    assert la._last_placement == ""


def test_new_game_reset_runs_on_the_coach_state_poll_alone():
    """The worker calls notify_round only when the RAW read changed, so the
    new-game reset cannot depend on it."""
    la = _mk()
    _polls(la, (5, 3), 1300.0, 3)
    la.notify_coach_state(_st(1, 2, 40.0))
    la.notify_coach_state(_st(1, 2, 41.5))
    assert la._known_augments == []


@pytest.mark.parametrize("glitch", [0.5, 1020.0, 3000.0])
def test_one_glitched_clock_value_does_not_clear_the_augments(glitch):
    la = _mk()
    t = _polls(la, (4, 2), 1000.0, 7)
    _poll(la, _st(4, 2, glitch))
    _polls(la, (4, 2), t, 4)
    assert la._known_augments == ["Pandora's Items", "Cybernetic Uplink"]


def test_no_clock_keeps_the_legacy_new_game_rule():
    la = _mk()
    _poll(la, _st(4, 2, 0.0))               # reader default when gameTime is absent
    _poll(la, _st(2, 1, 0.0))
    assert la._known_augments == []
    assert la._last_round == (2, 1)


def test_one_observation_per_state_object():
    """notify_coach_state + notify_round with the same dict is ONE read: a
    misread handed to BOTH on each of half the polls a majority needs is
    still held (double counting would have reached the majority)."""
    la = _mk()
    _poll(la, _st(4, 2, 820.0))
    t = 821.5
    for _ in range(g.SWITCH_MIN_READS // 2):
        s = _st(2, 1, t)
        la.notify_coach_state(s)
        la.notify_round(s)
        t += 1.5
    assert la._last_round == (4, 2)
    assert la._coach_state["stage_round"] == "4-2"


def test_w1_majority_move_lands_without_notify_round():
    """In the worker shape only the FIRST of several identical reads reaches
    notify_round, so a majority move on a later read must move the round from
    notify_coach_state. The first cut left _last_round at (4, 2) while
    _coach_state said 2-1."""
    la = _mk()
    _poll(la, _st(4, 2, 820.0))
    _polls(la, (2, 1), 821.5, g.SWITCH_MIN_READS)
    assert la._coach_state["stage_round"] == "2-1"
    assert la._last_round == (2, 1)
    assert la._known_augments                # a majority move is not a new game


def test_flicker_reverts_and_restores_the_round_bookkeeping(clock):
    """A one-round-ahead misread followed by the true round: the gate
    reverts, and the round timer / planning flags the misread replaced come
    back, so no planning scan is re-armed for a round that never began."""
    la = _mk()
    t = _polls(la, (3, 3), 590.0, g.WINDOW_READS)
    started = la._round_start_time
    la._scanned_planning = True
    _poll(la, _st(3, 4, t))                 # misread, taken on a clean window
    assert la._last_round == (3, 4) and la._scanned_planning is False
    _poll(la, _st(3, 3, t + 1.5))           # the true round again: revert
    assert la._last_round == (3, 3)
    assert la._round_start_time == started
    assert la._scanned_planning is True
    assert la._coach_state["stage_round"] == "3-3"


def test_w2_genuine_round_after_a_flicker_starts_its_timer(clock):
    """3-3, misread 3-4, 3-3 x4, then the genuine 3-4. The first cut never
    moved _last_round to (3, 4) and skipped that round's planning scan."""
    la = _mk()
    t = _polls(la, (3, 3), 590.0, g.WINDOW_READS)
    _poll(la, _st(3, 4, t))
    t = _polls(la, (3, 3), t + 1.5, 4)
    assert la._last_round == (3, 3)
    before = la._round_start_time
    la._scanned_planning = True
    _polls(la, (3, 4), t + 30.0, g.WINDOW_READS)   # the genuine round, read steadily
    assert la._last_round == (3, 4)
    assert la._round_start_time > before
    assert la._scanned_planning is False
    assert la._coach_state["stage_round"] == "3-4"


def test_w3_unrated_jump_by_majority_moves_the_round():
    """Hyper Roll 2-1 -> 2-5. The first cut left _last_round at (2, 1), an
    _AUGMENT_ROUNDS member, so _loop kept running the 20 s augment scans."""
    la = _mk()
    _poll(la, _st(2, 1, 200.0, variant="hyper_roll"))
    _polls(la, (2, 5), 230.0, g.SWITCH_MIN_READS, variant="hyper_roll")
    assert la._last_round == (2, 5)
    assert (2, 1) in tla.TftLiveAnalysis._AUGMENT_ROUNDS


def test_held_view_takes_the_round_fields_of_the_accepted_round(monkeypatch):
    """A held read must not carry its own round fields either: a misread
    onto a carousel round would park _loop on the carousel branch."""
    calls = []

    class _Sched:
        def fields(self, stage, rnd):
            calls.append((stage, rnd))
            return {"round_event": "pvp", "is_pve": False, "is_god_round": False,
                    "tempo_note": "", "round_schedule": "stub"}

    monkeypatch.setattr(tft_state_reader, "round_schedule", lambda *a, **k: _Sched())
    la = _mk()
    _poll(la, _st(4, 2, 820.0))
    _poll(la, _st(2, 4, 822.0, round_event="carousel"))
    assert calls and calls[-1] == (4, 2)
    assert la._coach_state["round_event"] == "pvp"
    assert la._coach_state["round_schedule"] == "stub"
    assert la._is_carousel_or_spectate() is False


def test_non_int_spelling_of_the_round_is_normalised():
    la = _mk()
    _poll(la, _st("3", "2", 500.0))
    assert la._last_round == (3, 2)
    assert (la._coach_state["stage"], la._coach_state["round"]) == (3, 2)


def test_variant_selects_the_queue_timing():
    la = _mk()
    _poll(la, _st(2, 1, 200.0, variant="hyper_roll"))
    assert la._stage_gate.timing is g.QUEUE_TIMINGS["hyper_roll"]
    assert la._stage_gate.rate is None
    _poll(la, _st(2, 2, 230.0, variant="standard"))
    assert la._stage_gate.timing is g.QUEUE_TIMINGS["standard"]
    _poll(la, _st(2, 3, 260.0, variant=None))
    assert la._stage_gate.timing is g.UNMEASURED


def test_gate_takes_its_pace_from_the_reader_table(monkeypatch):
    """The pace is computed from tft_state_reader's own round table at run
    time, never copied: a re-measured table (a Set 18 ~63 s/round schedule)
    flows in, and an unreadable one means no rate, never a guessed one."""
    la = _mk()
    _poll(la, _st(2, 1, 200.0))
    assert la._stage_gate.rate == g.pace_floor_from_table(tft_state_reader.time_table())
    assert la._stage_gate.rate is not None

    table63 = [(63.0 * i, *g.stage_round_of(i + 1)) for i in range(20)]
    monkeypatch.setattr(tft_state_reader, "time_table", lambda *a, **k: table63)
    la2 = _mk()
    _poll(la2, _st(2, 1, 300.0))
    assert la2._stage_gate.rate == pytest.approx(g.PACE_SAFETY * 63.0)

    monkeypatch.setattr(tft_state_reader, "time_table", lambda *a, **k: "unreadable")
    la3 = _mk()
    _poll(la3, _st(2, 1, 300.0))
    assert la3._stage_gate.rate is None


def test_new_game_refreshes_the_pace(monkeypatch):
    la = _mk()
    _polls(la, (5, 3), 1300.0, 3)
    old = la._stage_gate.rate
    table63 = [(63.0 * i, *g.stage_round_of(i + 1)) for i in range(20)]
    monkeypatch.setattr(tft_state_reader, "time_table", lambda *a, **k: table63)
    _poll(la, _st(1, 1, 5.0))
    _poll(la, _st(1, 1, 6.5))               # new game
    assert la._stage_gate.rate == pytest.approx(g.PACE_SAFETY * 63.0) != old


@pytest.mark.parametrize("set_n, table_name", [
    (18, "_TIME_TO_ROUND_SET18"), (17, "_TIME_TO_ROUND")])
def test_gate_pace_follows_the_resolved_set(monkeypatch, set_n, table_name):
    """S134 M1d: _reader_pace reads time_table() (the resolved set's table),
    not the legacy `_TIME_TO_ROUND` name, so a Set 18 game is rated on the
    Set 18 timings."""
    from tft import tft_set
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: set_n)
    la = _mk()
    _poll(la, _st(2, 1, 200.0))
    want = g.pace_floor_from_table(getattr(tft_state_reader, table_name))
    assert want is not None
    assert la._stage_gate.rate == pytest.approx(want)


def test_set18_pace_never_reads_the_legacy_table_name(monkeypatch):
    """A Set 18 game's pace survives an unreadable legacy table, so the seam
    is the set-aware accessor, never a direct `_TIME_TO_ROUND` read."""
    from tft import tft_set
    monkeypatch.setattr(tft_set, "resolve_set", lambda *a, **k: 18)
    monkeypatch.setattr(tft_state_reader, "_TIME_TO_ROUND", "unreadable")
    la = _mk()
    _poll(la, _st(2, 1, 200.0))
    assert la._stage_gate.rate == pytest.approx(
        g.pace_floor_from_table(tft_state_reader._TIME_TO_ROUND_SET18))


@pytest.mark.parametrize("bad", [None, "not a dict", 7])
def test_non_dict_state_never_raises(bad):
    la = _mk()
    la.notify_coach_state(bad)
    la.notify_round({} if bad is None else {"stage": None})
    assert la._last_round == (0, 0)
