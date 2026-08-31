"""Deep-audit cycle 7 P2 W1 slice F - core infra/metrics/workers regression pins.

Pins the behavior fixes shipped by the slice-F audit:

  1. core/polled_json.py - atomic_write_json / atomic_write_text retry the
     tmp->dst os.replace on transient PermissionError (WinError 5 under a
     concurrent reader), same pattern as ops/rc_supervisor.atomic_write_json
     and core/bridge_monitor._write_atomic (reference_os_replace_winerror5).
  2. core/hotkeys.py - the polled data/force_scan.json marker is written via
     the shared atomic JSON writer (hard rule: atomic writes only; the
     sibling writer dashboard/_writers.py was already atomic).
  3. core/obs_publisher.py - the publisher drains buffered incoming
     OBS-WebSocket messages each tick (OBS replies op=7 to every request;
     unread replies fill the websockets recv queue, backpressure pauses the
     transport and the keepalive then flaps the connection) and identifies
     with eventSubscriptions=0 (no event consumer exists).
  4. core/cost_tracker.py - a malformed daily_budget_usd / warn_at_fraction
     config value no longer raises out of allow_call()/banner_state()
     (callers swallow the exception which silently disabled the cap and
     500'd /api/cost); it is logged and treated as unlimited / default.
  5. core/live_metrics.py - synthetic per-match session ids are minted under
     a lock so concurrent coach ticks can never share one id.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest
from tests._asyncio_isolation import run_coro as _run_coro

_REPO_ROOT = Path(__file__).resolve().parent.parent

_BANNED_CHARS = "\u2013\u2014\u2018\u2019\u201c\u201d"


# ---------------------------------------------------------------------------
# 1. polled_json - os.replace retry-with-backoff
# ---------------------------------------------------------------------------

def test_atomic_write_json_retries_transient_permission_error(tmp_path, monkeypatch):
    from core import polled_json

    target = tmp_path / "out.json"
    calls = {"n": 0}
    real_replace = polled_json.os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky_replace)
    monkeypatch.setattr(polled_json.time, "sleep", lambda s: None)

    polled_json.atomic_write_json(target, {"k": 1})

    assert calls["n"] == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"k": 1}


def test_atomic_write_json_reraises_after_exhausted_retries(tmp_path, monkeypatch):
    from core import polled_json

    def always_denied(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(polled_json.os, "replace", always_denied)
    monkeypatch.setattr(polled_json.time, "sleep", lambda s: None)

    with pytest.raises(PermissionError):
        polled_json.atomic_write_json(tmp_path / "out.json", {"k": 1})


def test_atomic_write_text_retries_transient_permission_error(tmp_path, monkeypatch):
    from core import polled_json

    target = tmp_path / "trigger.txt"
    calls = {"n": 0}
    real_replace = polled_json.os.replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(polled_json.os, "replace", flaky_replace)
    monkeypatch.setattr(polled_json.time, "sleep", lambda s: None)

    polled_json.atomic_write_text(target, "restart")

    assert calls["n"] == 2
    assert target.read_text(encoding="utf-8") == "restart"


# ---------------------------------------------------------------------------
# 2. hotkeys - force_scan.json marker goes through the shared atomic writer
# ---------------------------------------------------------------------------

def test_force_scan_marker_uses_shared_atomic_writer(tmp_path, monkeypatch):
    """core.hotkeys must write the polled marker via the shared
    atomic_write_json helper (module-level import, patchable here).
    Pre-fix this fails: the module wrote via a bare Path.write_text."""
    import core.hotkeys as hotkeys

    written = {}

    def fake_atomic(path, payload, **kw):
        written["path"] = Path(path)
        written["payload"] = payload

    # raising=True (default): red pre-fix because the name does not exist.
    monkeypatch.setattr(hotkeys, "atomic_write_json", fake_atomic)
    monkeypatch.setattr(hotkeys, "_APP_DIR", tmp_path)
    monkeypatch.setattr(hotkeys, "_coaches", [])

    hotkeys._trigger_force_scan()

    assert written["path"] == tmp_path / "data" / "force_scan.json"
    assert isinstance(written["payload"].get("force"), float)


def test_force_scan_marker_lands_on_disk_valid_json(tmp_path, monkeypatch):
    import core.hotkeys as hotkeys

    monkeypatch.setattr(hotkeys, "_APP_DIR", tmp_path)
    monkeypatch.setattr(hotkeys, "_coaches", [])

    hotkeys._trigger_force_scan()

    marker = tmp_path / "data" / "force_scan.json"
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data.get("force", 0) > 0
    leftovers = list(marker.parent.glob("*.tmp"))
    assert leftovers == []


# ---------------------------------------------------------------------------
# 3. obs_publisher - identify subscriptions + incoming-message drain
# ---------------------------------------------------------------------------

class _StubWs:
    """Minimal async stand-in for a websockets client connection."""

    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.incoming:
            return self.incoming.pop(0)
        # Nothing pending: block forever so wait_for() times out.
        await asyncio.Event().wait()


def test_identify_subscribes_to_no_events():
    from core.obs_publisher import OBSPublisher

    hello = json.dumps({"op": 0, "d": {}})
    identified = json.dumps({"op": 2, "d": {}})
    ws = _StubWs([hello, identified])

    ok = _run_coro(OBSPublisher()._identify(ws, password=""))

    assert ok is True
    sent = json.loads(ws.sent[0])
    assert sent["op"] == 1
    assert sent["d"]["rpcVersion"] == 1
    assert sent["d"]["eventSubscriptions"] == 0


def test_identify_auth_response_still_computed():
    """Auth path regression pin: secret/response hash chain unchanged."""
    import base64
    import hashlib

    from core.obs_publisher import OBSPublisher

    salt, challenge, password = "s4lt", "ch4ll", "pw"
    hello = json.dumps({
        "op": 0,
        "d": {"authentication": {"salt": salt, "challenge": challenge}},
    })
    identified = json.dumps({"op": 2, "d": {}})
    ws = _StubWs([hello, identified])

    ok = _run_coro(OBSPublisher()._identify(ws, password=password))

    assert ok is True
    sent = json.loads(ws.sent[0])
    secret = base64.b64encode(
        hashlib.sha256((password + salt).encode("utf-8")).digest()
    ).decode("ascii")
    expected = base64.b64encode(
        hashlib.sha256((secret + challenge).encode("utf-8")).digest()
    ).decode("ascii")
    assert sent["d"]["authentication"] == expected


def test_drain_pending_empties_buffered_messages():
    from core.obs_publisher import OBSPublisher

    ws = _StubWs([json.dumps({"op": 7, "d": {"requestId": f"rc-{i}"}})
                  for i in range(5)])

    _run_coro(OBSPublisher()._drain_pending(ws))

    assert ws.incoming == []


def test_drain_pending_tolerates_closed_connection():
    from core.obs_publisher import OBSPublisher

    class _ClosedWs:
        async def recv(self):
            raise ConnectionError("closed")

    _run_coro(OBSPublisher()._drain_pending(_ClosedWs()))  # must not raise


def test_async_loop_wires_the_drain():
    """Source guard: the publish loop drains pending messages each tick."""
    import inspect

    from core.obs_publisher import OBSPublisher

    src = inspect.getsource(OBSPublisher._async_loop)
    assert "_drain_pending" in src


# ---------------------------------------------------------------------------
# 4. cost_tracker - malformed budget config must not raise
# ---------------------------------------------------------------------------

def _tracker(tmp_path, cfg):
    from core.cost_tracker import CostTracker
    return CostTracker(config_provider=lambda: cfg, spend_dir=tmp_path)


def test_allow_call_malformed_budget_does_not_raise(tmp_path):
    t = _tracker(tmp_path, {"daily_budget_usd": "five dollars"})
    assert t.allow_call() is True  # unlimited, logged - never an exception


def test_banner_state_malformed_budget_returns_ok(tmp_path):
    t = _tracker(tmp_path, {"daily_budget_usd": "5,00"})
    assert t.banner_state() == "ok"


def test_numeric_string_budget_still_enforced(tmp_path):
    t = _tracker(tmp_path, {"daily_budget_usd": "1.0"})
    assert t.allow_call() is True
    # 1M input tokens on opus pricing = $15 > $1 budget.
    t.record_call(model="claude-opus-4-7", input_tokens=1_000_000,
                  purpose="test")
    assert t.allow_call() is False
    assert t.banner_state() == "over"


def test_malformed_warn_fraction_falls_back_to_default(tmp_path):
    t = _tracker(tmp_path, {"daily_budget_usd": 10.0,
                            "warn_at_fraction": "most"})
    assert t.banner_state() == "ok"  # no spend recorded; must not raise


# ---------------------------------------------------------------------------
# 5. live_metrics - synthetic session ids unique under thread contention
# ---------------------------------------------------------------------------

def test_synthetic_session_ids_unique_across_threads():
    import sys

    from core import live_metrics

    class Holder:
        pass

    results = []
    results_lock = threading.Lock()
    n_threads, n_iter = 8, 200
    old_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        def worker():
            local = []
            for _ in range(n_iter):
                h = Holder()  # fresh holder -> always mints a new session
                sid = live_metrics._resolve_match_id(
                    h, {"game_time_s": 1.0, "champion": "X"}, {}, "aram")
                local.append(sid)
            with results_lock:
                results.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        sys.setswitchinterval(old_interval)

    assert len(results) == n_threads * n_iter
    assert len(set(results)) == len(results), "duplicate synthetic session ids"


# ---------------------------------------------------------------------------
# ASCII hygiene for every file this slice touched
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel", [
    "core/polled_json.py",
    "core/hotkeys.py",
    "core/obs_publisher.py",
    "core/cost_tracker.py",
    "core/live_metrics.py",
    "core/metric_streamer.py",
    "tests/test_p2w1_core_f.py",
])
def test_no_banned_typography(rel):
    text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
    # CATCH-ALL, not the six historical glyphs. `_BANNED_CHARS` names the
    # six for a readable diagnostic, but CLAUDE.md's rule is "7-bit ASCII
    # authored content", and a guard scoped to six codepoints cannot
    # enforce it. tools/precommit_gate.py:_glyph_hits was widened the same
    # way on 2026-07-28 after U+00D7 reached the repo through a gate
    # "working exactly as written"; that widening reached the gate and not
    # this test, so four U+00B7 sat in core/obs_publisher.py - a file this
    # very parametrize list names - and this assertion passed green.
    bad = sorted({c for c in text if ord(c) > 126})
    named = sorted({c for c in bad if c in _BANNED_CHARS})
    assert not bad, (
        f"{rel} contains non-ASCII: "
        f"{[f'U+{ord(c):04X}' for c in bad]}"
        + (f" (banned glyphs: {[hex(ord(c)) for c in named]})" if named else "")
    )
