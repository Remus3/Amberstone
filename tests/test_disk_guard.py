"""RM-637 (directive X-37, ADR-016 "Disk budget"): disk guard math and the
ownership-scoped trip. All synthetic: free-space and OBS status are injected,
nothing touches a real disk volume or a real OBS."""
from __future__ import annotations

import json

import pytest

from core import disk_guard as dg
from tests._asyncio_isolation import run_coro

GB = 1_000_000_000


def test_adr_constants():
    assert dg.FLOOR_BYTES == 20 * GB
    assert dg.FINALIZE_BUFFER_BYTES == 2 * GB
    assert dg.START_HEADROOM_BYTES == 8 * GB
    assert dg.CAP_BYTES == 60 * GB
    assert dg.FALLBACK_RATE_BPS == 5.0e6
    assert dg.CHECK_INTERVAL_S == 60.0


def test_threshold_never_below_floor():
    # 5 MB/s x 60 s x 1.5 + 2 GB = 2.45 GB, dominated by the 20 GB floor.
    assert dg.trip_threshold_bytes(5.0e6) == dg.FLOOR_BYTES
    assert dg.trip_threshold_bytes(0.0) == dg.FLOOR_BYTES


def test_threshold_formula_above_floor():
    rate = 300e6  # absurd encoder: 300 MB/s
    expect = rate * 60.0 * 1.5 + 2 * GB
    assert expect > dg.FLOOR_BYTES
    assert dg.trip_threshold_bytes(rate) == pytest.approx(expect)


def test_should_trip_boundary():
    assert dg.should_trip(20 * GB - 1, 5.0e6) is True
    assert dg.should_trip(20 * GB, 5.0e6) is False


@pytest.mark.parametrize("free,rc_bytes,ok,frag", [
    (28 * GB, 0, True, ""),
    (28 * GB - 1, 0, False, "free"),
    (100 * GB, 52 * GB, True, ""),
    (100 * GB, 52 * GB + 1, False, "cap"),
    (10 * GB, 59 * GB, False, "free"),
])
def test_start_precondition(free, rc_bytes, ok, frag):
    got, reason = dg.start_precondition(free, rc_bytes)
    assert got is ok
    if not ok:
        assert frag in reason


def test_start_precondition_unknown_free_refuses():
    ok, reason = dg.start_precondition(None, 0)
    assert ok is False and "unknown" in reason


def test_rate_estimator_live_and_fallback():
    est = dg.RateEstimator()
    assert est.effective_rate() == dg.FALLBACK_RATE_BPS
    est.update(0, 0.0)
    est.update(42_000_000, 10.0)
    assert est.effective_rate() == pytest.approx(4.2e6)
    # A failed read (None) does not poison the measured rate...
    est.update(None, 20.0)
    assert est.effective_rate() == pytest.approx(4.2e6)
    # ...but a counter reset (new recording) restarts measurement.
    est.update(1000, 30.0)
    est.update(5_001_000, 31.0)
    assert est.effective_rate() == pytest.approx(5.0e6)


def test_rate_estimator_no_measurement_uses_fallback():
    est = dg.RateEstimator()
    est.update(100, 5.0)
    est.update(100, 5.0)  # zero dt
    assert est.effective_rate() == dg.FALLBACK_RATE_BPS


def test_trip_actions_are_ownership_scoped():
    a = dg.trip_actions(rc_owns_record=True, rc_owns_replay=False)
    assert a == {"stop_record": True, "stop_replay_buffer": False, "banner": True}
    b = dg.trip_actions(rc_owns_record=False, rc_owns_replay=False)
    assert b == {"stop_record": False, "stop_replay_buffer": False, "banner": True}
    c = dg.trip_actions(rc_owns_record=False, rc_owns_replay=True)
    assert c["stop_record"] is False and c["stop_replay_buffer"] is True


def test_rc_recorded_bytes_counts_only_rc_sidecar_paths(tmp_path):
    rec = tmp_path / "recordings"
    rec.mkdir()
    vids = tmp_path / "vids"
    vids.mkdir()
    a = vids / "a.mp4"
    a.write_bytes(b"x" * 100)
    b = vids / "b.mp4"
    b.write_bytes(b"x" * 50)
    stray = vids / "stray.mp4"  # in the folder but no sidecar: never counted
    stray.write_bytes(b"x" * 999)
    (rec / "1.json").write_text(json.dumps({"owner": "rc", "obs_output_path": str(a)}))
    (rec / "2.json").write_text(json.dumps({"owner": "operator", "obs_output_path": str(b)}))
    (rec / "3.json").write_text(json.dumps({"owner": "rc", "obs_output_path": str(a)}))
    (rec / "4.json").write_text("{not json")
    (rec / "5.json").write_text(json.dumps({"owner": "rc", "obs_output_path": str(vids / "gone.mp4")}))
    assert dg.rc_recorded_bytes(rec) == 100


class _Probe:
    def __init__(self, free, owns, status=None):
        self.free = free
        self.owns = owns
        self.status = status
        self.stops = 0

    async def record_status(self):
        return self.status

    def record_dir(self):
        return "/synthetic/rec"

    def ownership(self):
        return self.owns

    async def stop_owned(self, actions):
        self.stops += 1


def _guard(probe, tmp_path):
    return dg.DiskGuard(
        status_fn=probe.record_status, record_dir_fn=probe.record_dir,
        ownership_fn=probe.ownership, stop_fn=probe.stop_owned,
        free_bytes_fn=lambda _p: probe.free,
        banner_path=tmp_path / "disk_guard.json")


def test_producer_trip_stops_only_rc_owned(tmp_path):
    p = _Probe(free=5 * GB, owns=(True, False),
               status={"outputActive": True, "outputBytes": 1})
    g = _guard(p, tmp_path)
    res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is True
    assert p.stops == 1
    assert g.banner_state()["active"] is True
    assert json.loads((tmp_path / "disk_guard.json").read_text())["active"] is True


def test_producer_trip_operator_owned_banner_only(tmp_path):
    p = _Probe(free=5 * GB, owns=(False, False),
               status={"outputActive": True, "outputBytes": 1})
    g = _guard(p, tmp_path)
    res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is True
    assert p.stops == 0
    assert g.banner_state()["active"] is True


def test_producer_no_trip_clears_banner(tmp_path):
    p = _Probe(free=5 * GB, owns=(True, False))
    g = _guard(p, tmp_path)
    run_coro(g.check_once(now=0.0))
    p.free = 500 * GB
    res = run_coro(g.check_once(now=60.0))
    assert res["tripped"] is False
    assert g.banner_state()["active"] is False


def test_producer_uses_live_rate_from_output_bytes(tmp_path):
    p = _Probe(free=500 * GB, owns=(True, False),
               status={"outputActive": True, "outputBytes": 0})
    g = _guard(p, tmp_path)
    run_coro(g.check_once(now=0.0))
    p.status = {"outputActive": True, "outputBytes": 300_000_000 * 60}
    res = run_coro(g.check_once(now=60.0))
    assert res["rate_bps"] == pytest.approx(300e6)
    assert res["rate_source"] == "live"


def test_producer_status_read_failure_uses_fallback(tmp_path):
    p = _Probe(free=500 * GB, owns=(True, False), status=None)
    g = _guard(p, tmp_path)
    res = run_coro(g.check_once(now=0.0))
    assert res["rate_bps"] == dg.FALLBACK_RATE_BPS
    assert res["rate_source"] == "fallback"


def test_producer_unknown_free_space_never_stops(tmp_path):
    p = _Probe(free=None, owns=(True, False))
    g = _guard(p, tmp_path)
    res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is False and p.stops == 0
