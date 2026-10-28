"""s144 true-audit (cycle 29): core/decision_detector.py liveness + rate cap.

The heartbeat file is written by the DecisionLoop in the supervisor process
and aged by read_heartbeat() in the RC main process - a wall-clock `ts`
compared across a process boundary, the RM-269 class core/relay_age.py
owns. Measured before the fix:

1. read_heartbeat(): a last_eval_unix from the FUTURE (a backward NTP
   step after the write) read alive=True with a negative age, so a dead
   loop reported alive until wall time caught up (RM-1045 remainder).
2. read_heartbeat(): a non-finite stamp (JSON 1e400 decodes to inf) read
   alive=True with age_s=-inf, which the route serialises as the non-JSON
   token -Infinity; an int too large for a float (10**400) raised
   OverflowError out of read_heartbeat; a bool was aged as a time.
3. DecisionLoop.heartbeat(): the same negative-age-reads-alive decision
   in-process.
4. DecisionLoop._apply_rate_cap(): the min-gap window was measured on the
   wall clock, so a backward step mid-game dropped every NEW decision
   until wall time passed the previous emit again.
"""
from __future__ import annotations

import json
import math
import time

import pytest

import core.decision_detector as dd
from core.decision_detector import Decision, DecisionLoop, DecisionStore
from core.relay_age import FUTURE_TOLERANCE_S


def _write_hb(path, last) -> None:
    path.write_text(json.dumps({
        "counter": 3,
        "last_eval_unix": last,
        "age_s": 0.1,
        "alive": True,
        "game_time": 100.0,
        "detectors": 6,
    }), encoding="utf-8")


@pytest.fixture
def hb_path(tmp_path, monkeypatch):
    path = tmp_path / "decisions_heartbeat.json"
    monkeypatch.setattr(dd, "_HEARTBEAT_PATH", path)
    return path


class TestReadHeartbeatFutureStamp:

    def test_future_stamp_beyond_tolerance_is_not_alive(self, hb_path):
        _write_hb(hb_path, time.time() + 3600.0)
        hb = dd.read_heartbeat()
        assert hb["alive"] is False

    def test_fresh_stamp_positive_control(self, hb_path):
        _write_hb(hb_path, time.time() - 1.0)
        hb = dd.read_heartbeat()
        assert hb["alive"] is True
        assert 0.0 <= hb["age_s"] < 5.0

    def test_jitter_inside_tolerance_stays_alive(self, hb_path):
        # A stamp a fraction of a second ahead is float / scheduling jitter
        # on one host, not a clock step.
        _write_hb(hb_path, time.time() + FUTURE_TOLERANCE_S / 4)
        hb = dd.read_heartbeat()
        assert hb["alive"] is True


class TestReadHeartbeatJunkStamp:

    def test_infinite_stamp_is_not_alive_and_serialises_strictly(
            self, hb_path):
        hb_path.write_text('{"counter": 1, "last_eval_unix": 1e400}',
                           encoding="utf-8")
        hb = dd.read_heartbeat()
        assert hb["alive"] is False
        assert hb["age_s"] is None
        # The route does json.dumps(payload); a strict encoder must accept
        # it (no -Infinity / NaN token reaches a client).
        json.dumps(hb, allow_nan=False)

    def test_overflowing_int_stamp_does_not_raise(self, hb_path):
        hb_path.write_text(
            '{"counter": 1, "last_eval_unix": 1' + "0" * 400 + "}",
            encoding="utf-8")
        hb = dd.read_heartbeat()
        assert hb["alive"] is False
        assert hb["age_s"] is None

    def test_bool_stamp_is_not_a_time(self, hb_path):
        _write_hb(hb_path, True)
        hb = dd.read_heartbeat()
        assert hb["alive"] is False
        assert hb["age_s"] is None

    @pytest.mark.parametrize("last", ["1700000000", None, -5, 0, [1.0]])
    def test_non_number_or_non_positive_stamp_reads_never_ran(
            self, hb_path, last):
        _write_hb(hb_path, last)
        hb = dd.read_heartbeat()
        assert hb["alive"] is False
        assert hb["age_s"] is None


def _tmp_store(tmp_path) -> DecisionStore:
    return DecisionStore(pending_path=tmp_path / "pending.json",
                         log_path=tmp_path / "log.jsonl")


class TestInProcessHeartbeat:

    def test_future_stamp_is_not_alive(self, tmp_path):
        loop = DecisionLoop(store=_tmp_store(tmp_path))
        with loop._heartbeat_lock:
            loop._eval_count = 4
            loop._last_eval_unix = time.time() + 3600.0
        hb = loop.heartbeat()
        assert hb["alive"] is False

    def test_fresh_stamp_positive_control(self, tmp_path):
        loop = DecisionLoop(store=_tmp_store(tmp_path))
        with loop._heartbeat_lock:
            loop._last_eval_unix = time.time() - 0.5
        assert loop.heartbeat()["alive"] is True


def _decision(i: int) -> Decision:
    return Decision(id=f"d{i}", type="t", title="t", subtitle="s",
                    options=["a", "b"], created_at_unix=0.0,
                    created_at_game_time=0.0, expires_at_game_time=60.0)


class _NoPendingStore:
    def list_pending(self):
        return []


class TestRateCapClock:

    def test_backward_wall_step_does_not_suppress_new_decisions(
            self, monkeypatch):
        loop = DecisionLoop(store=_NoPendingStore())
        wall = [1_800_000_000.0]
        mono = [1000.0]
        monkeypatch.setattr(dd.time, "time", lambda: wall[0])
        monkeypatch.setattr(dd.time, "monotonic", lambda: mono[0])
        assert [d.id for d in loop._apply_rate_cap([_decision(1)])] == ["d1"]
        # 60 s of real time pass, but NTP steps the wall clock back an hour.
        mono[0] += 60.0
        wall[0] -= 3600.0
        kept = loop._apply_rate_cap([_decision(2)])
        assert [d.id for d in kept] == ["d2"]

    def test_min_gap_still_enforced_positive_control(self, monkeypatch):
        loop = DecisionLoop(store=_NoPendingStore())
        mono = [1000.0]
        monkeypatch.setattr(dd.time, "monotonic", lambda: mono[0])
        assert len(loop._apply_rate_cap([_decision(1)])) == 1
        mono[0] += dd._MIN_GAP_S / 2
        assert loop._apply_rate_cap([_decision(2)]) == []
        mono[0] += dd._MIN_GAP_S
        assert len(loop._apply_rate_cap([_decision(3)])) == 1

    def test_first_decision_passes_even_at_a_small_monotonic_clock(
            self, monkeypatch):
        # Never-emitted must not be encoded as t=0.0: a monotonic clock may
        # read under _MIN_GAP_S shortly after boot.
        loop = DecisionLoop(store=_NoPendingStore())
        monkeypatch.setattr(dd.time, "monotonic", lambda: 1.0)
        assert len(loop._apply_rate_cap([_decision(1)])) == 1


def test_round_trip_of_written_heartbeat_is_finite(hb_path, tmp_path):
    loop = DecisionLoop(store=_tmp_store(tmp_path))
    with loop._heartbeat_lock:
        loop._last_eval_unix = time.time()
    loop._write_heartbeat()
    hb = dd.read_heartbeat()
    assert hb["alive"] is True
    assert math.isfinite(hb["age_s"])
