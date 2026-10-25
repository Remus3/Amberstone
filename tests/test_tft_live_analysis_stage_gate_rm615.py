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
    into the prompt (`stage_round=cs.get("stage_round", "?")`, :600) and
    `_write` publishes (:708);
  * a game left at stage 2 was never detected as over, so its augments
    leaked into the next game.

Shape of the calls, as production makes them: core/tft_worker.py:308-312
calls `notify_coach_state(state)` on every poll and `notify_round(state)`
with the SAME dict when the raw stage-round changed; coaches/tft_pbe_coach.py
:147-151 does the same. Each poll is a fresh dict (TftStateReader._parse,
tft/tft_state_reader.py:206-221, which sets "stage", "round",
"stage_round", "game_time_s", "round_event" and "variant").

Names used, cited at the fix tree:
  tft/tft_live_analysis.py  TftLiveAnalysis, notify_round, notify_coach_state,
      _is_carousel_or_spectate, _stage_gate (lazy via _gate), _gated,
      _apply_round, _AUGMENT_ROUNDS, the module-level `time` import,
      _known_augments, _last_placement, _last_round, _round_start_time,
      _scanned_planning, _scanned_mid, _coach_state.
  core/tft_stage_gate.py  QUEUE_TIMINGS, CONFIRM_READS, UNMEASURED.

The first cut of this slice was REFUTED by its verifier (wiring lag on a
confirmed re-anchor, a flicker that held the gate a round ahead); the W1-W3
cases below are its reproducers, and the call shape is now the worker's.
  tft/tft_state_reader.py  round_schedule (:271), RoundSchedule.fields (:259).
"""
from __future__ import annotations

import pytest

from core import tft_stage_gate as g
from tft import tft_live_analysis as tla
from tft import tft_state_reader


def _mk():
    """A TftLiveAnalysis with no SDK client and no vision reader (the
    tests/test_tft_live_analysis_lane8_cycle43.py:86 shape). `_stage_gate`
    is deliberately NOT set: the gate must come up lazily for objects built
    without __init__."""
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


@pytest.fixture
def clock(monkeypatch):
    """A fake wall clock for the round timer (tft_live_analysis calls
    time.time() for _round_start_time); each read advances it 1 s."""
    import types
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


def test_real_advance_resets_the_round_timer():
    la = _mk()
    _poll(la, _st(3, 2, 500.0))
    la._scanned_planning = True
    la._scanned_mid = True
    _poll(la, _st(3, 3, 545.0))
    assert la._last_round == (3, 3)
    assert la._round_start_time > 0
    assert la._scanned_planning is False and la._scanned_mid is False
    assert la._coach_state["stage_round"] == "3-3"
    assert la._known_augments                # an advance clears nothing


def test_genuine_new_game_bypasses_the_gate():
    la = _mk()
    _poll(la, _st(5, 3, 1300.0))
    _poll(la, _st(1, 2, 40.0))              # the game clock restarted
    assert la._known_augments == []
    assert la._last_placement == ""
    assert la._last_round == (1, 2)
    assert la._coach_state["stage_round"] == "1-2"


def test_new_game_after_a_game_left_at_stage_2_is_detected():
    """Pre-fix the detector needed the old stage > 2, so a game abandoned at
    stage 2 leaked its augments into the next one."""
    la = _mk()
    _poll(la, _st(2, 3, 400.0))
    _poll(la, _st(1, 1, 5.0))
    assert la._known_augments == []
    assert la._last_placement == ""


def test_new_game_reset_runs_on_the_coach_state_poll_alone():
    """The worker calls notify_round only when the RAW read changed, so the
    new-game reset cannot depend on it."""
    la = _mk()
    _poll(la, _st(5, 3, 1300.0))
    la.notify_coach_state(_st(1, 2, 40.0))
    assert la._known_augments == []


def test_no_clock_keeps_the_legacy_new_game_rule():
    la = _mk()
    _poll(la, _st(4, 2, 0.0))               # reader default when gameTime is absent
    _poll(la, _st(2, 1, 0.0))
    assert la._known_augments == []
    assert la._last_round == (2, 1)


def test_one_observation_per_state_object():
    """notify_coach_state + notify_round with the same dict is ONE read: a
    glitch handed to BOTH on each of two polls is still held (double counting
    would have confirmed it)."""
    la = _mk()
    _poll(la, _st(4, 2, 820.0))
    t = 821.5
    for _ in range(g.CONFIRM_READS - 1):
        s = _st(2, 1, t)
        la.notify_coach_state(s)
        la.notify_round(s)
        t += 1.5
    assert la._last_round == (4, 2)
    assert la._coach_state["stage_round"] == "4-2"


def test_confirmed_re_anchor_lands_without_notify_round():
    """Verifier reproducer W1: in the worker shape only the FIRST of three
    identical reads reaches notify_round, so the confirmation on the third
    must move the round from notify_coach_state. The first cut left
    _last_round at (4, 2) while _coach_state said 2-1."""
    la = _mk()
    _poll(la, _st(4, 2, 820.0))
    t = 821.5
    for _ in range(g.CONFIRM_READS):
        _poll(la, _st(2, 1, t))
        t += 1.5
    assert la._coach_state["stage_round"] == "2-1"
    assert la._last_round == (2, 1)
    assert la._known_augments                # a confirmed re-anchor is not a new game


def test_flicker_reverts_and_restores_the_round_bookkeeping(clock):
    """A one-round-ahead misread followed by the true round: the gate
    reverts, and the round timer / planning flags the misread replaced come
    back, so no planning scan is re-armed for a round that never began."""
    la = _mk()
    _poll(la, _st(3, 3, 600.0))
    started = la._round_start_time
    la._scanned_planning = True
    _poll(la, _st(3, 4, 601.5))             # misread, taken provisionally
    assert la._last_round == (3, 4) and la._scanned_planning is False
    _poll(la, _st(3, 3, 603.0))             # the true round again: revert
    assert la._last_round == (3, 3)
    assert la._round_start_time == started
    assert la._scanned_planning is True
    assert la._coach_state["stage_round"] == "3-3"


def test_genuine_round_after_a_flicker_starts_its_timer(clock):
    """Verifier reproducer W2: 3-3, misread 3-4, 3-3 x4, then the genuine
    3-4. The first cut never moved _last_round to (3, 4) and skipped that
    round's planning scan."""
    la = _mk()
    _poll(la, _st(3, 3, 600.0))
    _poll(la, _st(3, 4, 601.5))
    for i in range(4):
        _poll(la, _st(3, 3, 603.0 + 1.5 * i))
    assert la._last_round == (3, 3)
    before = la._round_start_time
    la._scanned_planning = True
    t = 640.0
    for _ in range(g.CONFIRM_READS):        # the suspect round, read steadily
        _poll(la, _st(3, 4, t))
        t += 1.5
    assert la._last_round == (3, 4)
    assert la._round_start_time > before
    assert la._scanned_planning is False
    assert la._coach_state["stage_round"] == "3-4"


def test_unrated_jump_confirmed_moves_the_round():
    """Verifier reproducer W3: Hyper Roll 2-1 -> 2-5 confirmed. The first cut
    left _last_round at (2, 1), an _AUGMENT_ROUNDS member
    (tft/tft_live_analysis.py `_AUGMENT_ROUNDS`), so _loop kept running the
    20 s augment scans."""
    la = _mk()
    _poll(la, _st(2, 1, 200.0, variant="hyper_roll"))
    t = 230.0
    for _ in range(g.CONFIRM_READS):
        _poll(la, _st(2, 5, t, variant="hyper_roll"))
        t += 1.5
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


def test_variant_selects_the_queue_timing():
    la = _mk()
    _poll(la, _st(2, 1, 200.0, variant="hyper_roll"))
    assert la._stage_gate.timing is g.QUEUE_TIMINGS["hyper_roll"]
    _poll(la, _st(2, 2, 230.0, variant="standard"))
    assert la._stage_gate.timing is g.QUEUE_TIMINGS["standard"]
    _poll(la, _st(2, 3, 260.0, variant=None))
    assert la._stage_gate.timing is g.UNMEASURED


@pytest.mark.parametrize("bad", [None, "not a dict", 7])
def test_non_dict_state_never_raises(bad):
    la = _mk()
    la.notify_coach_state(bad)
    la.notify_round({} if bad is None else {"stage": None})
    assert la._last_round == (0, 0)
