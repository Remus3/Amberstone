"""True-audit (s144 lane true-audit): dashboard/_diagnostics.py, the /api/diagnostics cache.

`diagnostics_cached()` fronts `_build_diagnostics()` (a ~2-3 s fan-out: two
loopback HTTP probes, a log tail, health.json) with a 30 s TTL and a
single-flight lock. `dashboard/routes_diag.py` `_serve_diagnostics` sends its
bytes verbatim as `application/json` on :8888.

Characterization (green before and after the rewrite):
  - a second call inside the TTL reuses the payload (one build);
  - a call after the TTL rebuilds;
  - concurrent callers share ONE build (single-flight);
  - a build that raises propagates to the caller (routes_diag scrubs it) and
    is NOT cached, so the next call retries.

Findings, each red before the fix:
  F1 WALL-CLOCK TTL. Freshness was `time.time() < expires`. A backward wall
     clock step (NTP correction, manual set, resume from sleep with a skewed
     RTC) of N seconds kept serving the old payload for N + 30 s, however much
     real time passed. Fix: the TTL runs on time.monotonic().
  F2 NON-STRICT JSON ON THE WIRE. The payload embeds health.json verbatim, and
     dashboard/_context.read_json parses it with json.loads, which accepts the
     NaN / Infinity literals and turns 1e400 into inf (the same class
     dashboard/routes_metrics.py `_num` already rejects for the same file).
     json.dumps then emitted the bare tokens `NaN` / `Infinity`, which are not
     JSON (RFC 8259): any strict parser - a browser JSON.parse, `jq`, a
     parse_constant-strict Python reader - rejects the WHOLE diagnostics body.
     Fix: a non-finite float is serialized as null and the dump is
     allow_nan=False, so the body is always strict JSON.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

import dashboard._diagnostics as diag


def _strict_loads(raw: bytes):
    def _refuse(token):
        raise ValueError(f"non-strict JSON constant {token!r}")

    return json.loads(raw.decode("utf-8"), parse_constant=_refuse)


class _Clock:
    """A fake `time` module: wall and monotonic move independently."""

    def __init__(self, wall: float = 1_800_000_000.0, mono: float = 5_000.0):
        self.wall = wall
        self.mono = mono

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.mono += seconds


@pytest.fixture
def fresh(monkeypatch):
    """Empty cache, counted builder, fake clock."""
    monkeypatch.setattr(diag, "_DIAG_CACHE", {})
    clock = _Clock()
    monkeypatch.setattr(diag, "time", clock)
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        return {"build": calls["n"], "health": {}}

    monkeypatch.setattr(diag, "_build_diagnostics", _build)
    return clock, calls


# ---- characterization -------------------------------------------------------

def test_second_call_inside_ttl_reuses_the_payload(fresh):
    clock, calls = fresh
    first = diag.diagnostics_cached()
    clock.advance(diag._DIAG_TTL_S - 1)
    assert diag.diagnostics_cached() == first
    assert calls["n"] == 1


def test_call_after_ttl_rebuilds(fresh):
    clock, calls = fresh
    diag.diagnostics_cached()
    clock.advance(diag._DIAG_TTL_S + 0.5)
    payload = diag.diagnostics_cached()
    assert calls["n"] == 2
    assert _strict_loads(payload)["build"] == 2


def test_payload_is_utf8_json_bytes(fresh):
    payload = diag.diagnostics_cached()
    assert isinstance(payload, bytes)
    assert _strict_loads(payload) == {"build": 1, "health": {}}


def test_concurrent_callers_share_one_build(monkeypatch):
    monkeypatch.setattr(diag, "_DIAG_CACHE", {})
    calls = {"n": 0}
    gate = threading.Event()

    def _slow_build():
        calls["n"] += 1
        gate.wait(5)
        return {"build": calls["n"]}

    monkeypatch.setattr(diag, "_build_diagnostics", _slow_build)
    results: list = []
    threads = [
        threading.Thread(target=lambda: results.append(diag.diagnostics_cached()),
                         name=f"diag-test-{i}")
        for i in range(6)
    ]
    for t in threads:
        t.start()
    time.sleep(0.2)
    gate.set()
    for t in threads:
        t.join(10)
    assert calls["n"] == 1
    assert len(results) == 6 and len(set(results)) == 1


def test_build_failure_propagates_and_is_not_cached(fresh, monkeypatch):
    clock, calls = fresh
    state = {"fail": True}
    good = diag._build_diagnostics

    def _maybe_fail():
        if state["fail"]:
            raise RuntimeError("probe exploded")
        return good()

    monkeypatch.setattr(diag, "_build_diagnostics", _maybe_fail)
    with pytest.raises(RuntimeError):
        diag.diagnostics_cached()
    state["fail"] = False
    payload = diag.diagnostics_cached()
    assert _strict_loads(payload)["build"] == 1


# ---- F1: the TTL must not ride the wall clock --------------------------------

def test_f1_backward_wall_clock_step_does_not_pin_a_stale_payload(fresh):
    clock, calls = fresh
    diag.diagnostics_cached()
    # The wall clock is corrected back one hour; real (monotonic) time then
    # moves past the TTL. The payload is stale and must be rebuilt.
    clock.wall -= 3600.0
    clock.wall += diag._DIAG_TTL_S + 1
    clock.mono += diag._DIAG_TTL_S + 1
    payload = diag.diagnostics_cached()
    assert calls["n"] == 2
    assert _strict_loads(payload)["build"] == 2


def test_f1_forward_wall_clock_step_does_not_expire_early(fresh):
    clock, calls = fresh
    diag.diagnostics_cached()
    clock.wall += 7200.0  # wall jumps two hours, real time does not move
    diag.diagnostics_cached()
    assert calls["n"] == 1


# ---- F2: the body is always strict JSON -------------------------------------

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_f2_non_finite_health_float_serializes_as_null(monkeypatch, bad):
    monkeypatch.setattr(diag, "_DIAG_CACHE", {})
    monkeypatch.setattr(diag, "_build_diagnostics", lambda: {
        "connections": [{"name": "RC supervisor", "ok": True, "detail": "pid 1"}],
        "health": {"ui_pulse_age_s": bad, "pid": 7,
                   "nested": {"ages": [1.5, bad, {"x": bad}]}},
        "log_tail": ["line"],
    })
    out = _strict_loads(diag.diagnostics_cached())
    assert out["health"]["ui_pulse_age_s"] is None
    assert out["health"]["nested"]["ages"] == [1.5, None, {"x": None}]
    # Finite values and the rest of the payload are untouched.
    assert out["health"]["pid"] == 7
    assert out["connections"][0]["name"] == "RC supervisor"
    assert out["log_tail"] == ["line"]


def test_f2_strict_json_through_the_real_health_reader(monkeypatch, tmp_path):
    """End to end through dashboard/_context.read_json: a health.json holding
    the NaN / Infinity literals and an overflowing 1e400 (all accepted by
    json.loads) still yields a strict-JSON diagnostics body."""
    import dashboard._context as ctx
    from dashboard import builders

    (tmp_path / "ops" / "runtime").mkdir(parents=True)
    (tmp_path / "ops" / "runtime" / "health.json").write_bytes(
        b'{"alive": true, "pid": 9, "ui_pulse_age_s": NaN,'
        b' "game_poll_worker_age_s": Infinity, "x": 1e400}'
    )
    monkeypatch.setattr(ctx, "APP_DIR", tmp_path)
    monkeypatch.setattr(builders, "_APP_DIR", tmp_path)
    # Keep the two loopback probes off the network: refuse instantly, in
    # dashboard.builders only (tests/_module_view.py, RM-801).
    from tests._module_view import bind_urlopen

    def _refuse(*_a, **_k):
        raise OSError("probe disabled in test")

    bind_urlopen(monkeypatch, builders, _refuse)
    monkeypatch.setattr(diag, "_DIAG_CACHE", {})
    monkeypatch.setattr(diag, "_build_diagnostics", builders._build_diagnostics)
    out = _strict_loads(diag.diagnostics_cached())
    assert out["health"]["alive"] is True
    assert out["health"]["ui_pulse_age_s"] is None
    assert out["health"]["game_poll_worker_age_s"] is None
    assert out["health"]["x"] is None
