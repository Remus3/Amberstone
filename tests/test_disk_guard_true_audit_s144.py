"""Lane 8 (true-audit) s144 cycle 61: core/disk_guard.py hardening.

One test (or one parametrized group) per finding F1-F9 from the cycle report.
All synthetic: free space, OBS status and ownership are injected; nothing
touches a real recording volume or a real OBS."""
from __future__ import annotations

import json
import logging
import math

import pytest

from core import disk_guard as dg
from tests._asyncio_isolation import run_coro

GB = 1_000_000_000


class _Probe:
    def __init__(self, free, owns=(False, False), status=None, record_dir="/synthetic/rec"):
        self.free = free
        self.owns = owns
        self.status = status
        self.record_dir_value = record_dir
        self.stops = 0
        self.stop_exc = None
        self.own_exc = None
        self.free_exc = None

    async def record_status(self):
        return self.status

    def record_dir(self):
        return self.record_dir_value

    def ownership(self):
        if self.own_exc is not None:
            raise self.own_exc
        return self.owns

    async def stop_owned(self, actions):
        self.stops += 1
        if self.stop_exc is not None:
            raise self.stop_exc

    def free_fn(self, _path):
        if self.free_exc is not None:
            raise self.free_exc
        return self.free


def _guard(probe, banner_path, **kw):
    return dg.DiskGuard(
        status_fn=probe.record_status, record_dir_fn=probe.record_dir,
        ownership_fn=probe.ownership, stop_fn=probe.stop_owned,
        free_bytes_fn=probe.free_fn, banner_path=banner_path, **kw)


def _banner(path):
    return json.loads(path.read_text(encoding="ascii"))


# -- F1: the not-owned banner must not claim a recording is running ----------

def test_f1_not_owned_banner_text_claims_no_running_recording():
    # RC refuses to start below 28 GB free but the game record (with its
    # record_dir) stays until game end, so a sub-20 GB trip with NOTHING
    # recording reaches the not-owned branch. Its text must stay true then.
    assert "did not start this recording" not in dg.BANNER_TEXT_OPERATOR
    assert "so it was left running" not in dg.BANNER_TEXT_OPERATOR


def test_f1_refused_start_trip_uses_not_owned_text(tmp_path):
    p = _Probe(free=10 * GB, owns=(False, False), status=None)
    g = _guard(p, tmp_path / "b.json")
    res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is True and p.stops == 0
    assert _banner(tmp_path / "b.json")["text"] == dg.BANNER_TEXT_OPERATOR


# -- F2: a failed stop must not be reported as a stopped recording -----------

def test_f2_stop_failure_banner_does_not_say_stopped(tmp_path):
    p = _Probe(free=5 * GB, owns=(True, False))
    p.stop_exc = RuntimeError("synthetic stop failure")
    g = _guard(p, tmp_path / "b.json")
    run_coro(g.check_once(now=0.0))
    assert p.stops == 1
    text = _banner(tmp_path / "b.json")["text"]
    assert text == dg.BANNER_TEXT_NOT_STOPPED
    assert "stopped to protect" not in text


def test_f2_stop_success_keeps_stopped_text(tmp_path):
    p = _Probe(free=5 * GB, owns=(True, False))
    g = _guard(p, tmp_path / "b.json")
    run_coro(g.check_once(now=0.0))
    assert _banner(tmp_path / "b.json")["text"] == dg.BANNER_TEXT


def test_f2_ownership_read_failure_is_not_reported_as_operator_owned(tmp_path, caplog):
    p = _Probe(free=5 * GB)
    p.own_exc = RuntimeError("synthetic ownership failure")
    g = _guard(p, tmp_path / "b.json")
    with caplog.at_level(logging.WARNING, logger="rc.disk_guard"):
        res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is True and p.stops == 0
    assert _banner(tmp_path / "b.json")["text"] == dg.BANNER_TEXT_NOT_STOPPED
    assert any("ownership" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)


# -- F3: a failed banner write is retried on the next check ------------------

def test_f3_failed_banner_write_is_retried(tmp_path, monkeypatch):
    path = tmp_path / "b.json"
    real = dg._atomic_write_json
    calls = {"n": 0}

    def flaky(pth, data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("synthetic locked target")
        real(pth, data)

    monkeypatch.setattr(dg, "_atomic_write_json", flaky)
    p = _Probe(free=5 * GB, owns=(True, False))
    g = _guard(p, path)
    run_coro(g.check_once(now=0.0))
    assert not path.exists()
    run_coro(g.check_once(now=60.0))
    assert path.exists() and _banner(path)["active"] is True


def _flaky_writer(monkeypatch, fail_on):
    real = dg._atomic_write_json
    calls = {"n": 0}

    def flaky(pth, data):
        calls["n"] += 1
        if calls["n"] in fail_on:
            raise PermissionError("synthetic locked target")
        real(pth, data)

    monkeypatch.setattr(dg, "_atomic_write_json", flaky)


def test_f3_failed_write_after_a_good_write_is_retried(tmp_path, monkeypatch):
    path = tmp_path / "b.json"
    _flaky_writer(monkeypatch, fail_on={2})
    p = _Probe(free=500 * GB, owns=(True, False))
    g = _guard(p, path)
    run_coro(g.check_once(now=0.0))   # inactive write succeeds
    p.free = 5 * GB
    run_coro(g.check_once(now=60.0))  # trip write fails
    assert _banner(path)["active"] is False
    run_coro(g.check_once(now=120.0))  # retried
    assert _banner(path)["active"] is True


def test_f3_banner_state_current_after_failed_write_then_recovery(tmp_path, monkeypatch):
    path = tmp_path / "b.json"
    _flaky_writer(monkeypatch, fail_on={2})
    p = _Probe(free=500 * GB, owns=(True, False))
    g = _guard(p, path)
    run_coro(g.check_once(now=0.0))   # inactive write succeeds
    p.free = 5 * GB
    run_coro(g.check_once(now=60.0))  # trip write fails
    p.free = 500 * GB
    run_coro(g.check_once(now=120.0))  # recovered: file already inactive
    assert _banner(path)["active"] is False
    assert g.banner_state()["active"] is False


def test_f3_banner_write_failure_warns(tmp_path, monkeypatch, caplog):
    def boom(_pth, _data):
        raise PermissionError("synthetic locked target")

    monkeypatch.setattr(dg, "_atomic_write_json", boom)
    p = _Probe(free=5 * GB, owns=(True, False))
    g = _guard(p, tmp_path / "b.json")
    with caplog.at_level(logging.WARNING, logger="rc.disk_guard"):
        run_coro(g.check_once(now=0.0))
    # "banner write failed", not bare "banner": the trip warning's actions
    # dict carries a "banner" key, so the bare word matched without the fix
    assert any("banner write failed" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)
    assert "synthetic locked target" not in caplog.text


def test_f3_unchanged_state_is_written_once(tmp_path, monkeypatch):
    real = dg._atomic_write_json
    calls = {"n": 0}

    def counting(pth, data):
        calls["n"] += 1
        real(pth, data)

    monkeypatch.setattr(dg, "_atomic_write_json", counting)
    p = _Probe(free=5 * GB, owns=(True, False))
    g = _guard(p, tmp_path / "b.json")
    for i in range(3):
        run_coro(g.check_once(now=60.0 * i))
    assert calls["n"] == 1


# -- F4: a stale active banner from an earlier process is cleared ------------

def test_f4_stale_active_banner_from_previous_process_is_cleared(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"active": True, "text": dg.BANNER_TEXT,
                                "updated": 1.0}), encoding="ascii")
    p = _Probe(free=500 * GB, owns=(True, False))
    g = _guard(p, path)
    res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is False
    assert _banner(path)["active"] is False


# -- F5: a blind guard (free space unreadable) says so ----------------------

def test_f5_free_space_read_raising_warns_once_per_streak(tmp_path, caplog):
    p = _Probe(free=500 * GB)
    p.free_exc = OSError("synthetic volume gone")
    g = _guard(p, tmp_path / "b.json")
    with caplog.at_level(logging.WARNING, logger="rc.disk_guard"):
        for i in range(3):
            res = run_coro(g.check_once(now=60.0 * i))
            assert res["tripped"] is False and res["free_bytes"] is None
    blind = [r for r in caplog.records
             if r.levelno >= logging.WARNING and "free space" in r.getMessage()]
    assert len(blind) == 1
    # the raw exception text is not logged, only its type
    assert "synthetic volume gone" not in caplog.text


def test_f5_free_none_with_record_dir_warns_and_rearms(tmp_path, caplog):
    p = _Probe(free=None)
    g = _guard(p, tmp_path / "b.json")
    with caplog.at_level(logging.WARNING, logger="rc.disk_guard"):
        run_coro(g.check_once(now=0.0))
        run_coro(g.check_once(now=60.0))
        p.free = 500 * GB
        run_coro(g.check_once(now=120.0))
        p.free = None
        run_coro(g.check_once(now=180.0))
    blind = [r for r in caplog.records
             if r.levelno >= logging.WARNING and "free space" in r.getMessage()]
    assert len(blind) == 2


def test_f5_no_record_dir_is_not_blindness(tmp_path, caplog):
    p = _Probe(free=None, record_dir=None)
    g = _guard(p, tmp_path / "b.json")
    with caplog.at_level(logging.WARNING, logger="rc.disk_guard"):
        run_coro(g.check_once(now=0.0))
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# -- F6: non-finite / non-numeric outputBytes never drive the rate ----------

@pytest.mark.parametrize("junk", [float("inf"), float("nan"), 10 ** 400,
                                  "123000000", -5, float("-inf")])
def test_f6_rate_estimator_rejects_junk_output_bytes(junk):
    est = dg.RateEstimator()
    est.update(0, 0.0)
    est.update(42_000_000, 10.0)
    est.update(junk, 20.0)
    assert est.effective_rate() == pytest.approx(4.2e6)
    # junk is not stored as the baseline: the next real read measures
    # against the last REAL sample
    est.update(42_000_000 + 4_200_000 * 20, 30.0)
    assert est.effective_rate() == pytest.approx(4.2e6)


def test_f6_inf_output_bytes_never_false_trips(tmp_path):
    p = _Probe(free=500 * GB, owns=(True, False),
               status={"outputActive": True, "outputBytes": 0})
    g = _guard(p, tmp_path / "b.json")
    run_coro(g.check_once(now=0.0))
    p.status = {"outputActive": True, "outputBytes": float("inf")}
    res = run_coro(g.check_once(now=60.0))
    assert res["tripped"] is False and p.stops == 0
    assert math.isfinite(res["rate_bps"])


@pytest.mark.parametrize("junk", [float("inf"), float("nan"), "fast", None])
def test_f6_threshold_non_finite_rate_uses_fallback(junk):
    assert dg.trip_threshold_bytes(junk) == dg.trip_threshold_bytes(dg.FALLBACK_RATE_BPS)


def test_f6_rate_estimator_rejects_non_finite_clock():
    est = dg.RateEstimator()
    est.update(0, 0.0)
    est.update(10_000_000, float("nan"))
    est.update(20_000_000, 2.0)
    assert est.effective_rate() == pytest.approx(10e6)


# -- F7: start_precondition fails closed on junk inputs ---------------------

@pytest.mark.parametrize("free", [float("nan"), float("inf"), "500000000000",
                                  True, -1])
def test_f7_start_precondition_junk_free_refuses(free):
    ok, reason = dg.start_precondition(free, 0)
    assert ok is False and reason


@pytest.mark.parametrize("rc_bytes", [float("nan"), float("inf"), -1 * GB,
                                      "0", True])
def test_f7_start_precondition_junk_rc_bytes_refuses(rc_bytes):
    ok, reason = dg.start_precondition(500 * GB, rc_bytes)
    assert ok is False and reason


def test_f7_start_precondition_valid_still_ok():
    assert dg.start_precondition(500 * GB, 0) == (True, "")
    assert dg.start_precondition(500 * GB, None) == (True, "")
    assert dg.start_precondition(500.0 * GB, 1.5 * GB) == (True, "")


@pytest.mark.parametrize("junk", [float("nan"), "lots", True, -1])
def test_f7_check_once_junk_free_is_unknown_not_a_crash(tmp_path, junk):
    p = _Probe(free=junk, owns=(True, False))
    g = _guard(p, tmp_path / "b.json")
    res = run_coro(g.check_once(now=0.0))
    assert res["tripped"] is False and res["free_bytes"] is None
    assert p.stops == 0


# -- F8: a non-positive interval would busy-spin run() ----------------------

@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_f8_bad_interval_is_refused(tmp_path, bad):
    p = _Probe(free=500 * GB)
    with pytest.raises(ValueError):
        _guard(p, tmp_path / "b.json", interval_s=bad)


# -- F9: one recording named two ways counts once; relative paths never ----

def test_f9_rc_recorded_bytes_normalises_path_spellings(tmp_path):
    rec = tmp_path / "recordings"
    rec.mkdir()
    vids = tmp_path / "vids"
    vids.mkdir()
    a = vids / "a.mp4"
    a.write_bytes(b"x" * 100)
    # string-built on purpose: pathlib would fold the ".." away itself
    dotted = str(vids) + "/../vids/a.mp4"
    (rec / "1.json").write_text(json.dumps({"owner": "rc", "obs_output_path": str(a)}))
    (rec / "2.json").write_text(json.dumps({"owner": "rc", "obs_output_path": dotted}))
    assert dg.rc_recorded_bytes(rec) == 100


def test_f9_rc_recorded_bytes_ignores_relative_paths(tmp_path, monkeypatch):
    rec = tmp_path / "recordings"
    rec.mkdir()
    (tmp_path / "rel.mp4").write_bytes(b"x" * 70)
    monkeypatch.chdir(tmp_path)
    (rec / "1.json").write_text(json.dumps({"owner": "rc", "obs_output_path": "rel.mp4"}))
    assert dg.rc_recorded_bytes(rec) == 0
