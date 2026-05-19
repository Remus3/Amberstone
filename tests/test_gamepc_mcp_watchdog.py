"""Watchdog-only tests for tools/gamepc_mcp_server.py.

The gamepc MCP server is deployed ON Game-PC (binds 0.0.0.0 for the
Legion<->Game-PC LAN); the source lives in this repo and is imported
here. These tests are deliberately scoped to the new hung-tool dispatch
watchdog and the run_powershell interaction - they do NOT spawn a real
PowerShell subprocess, take a screenshot, or open a socket. Pure stubs.

Key contract under test (from the backlog item):
  * every tool handler invocation is bounded by a single shared, bounded
    executor (no per-call thread explosion);
  * a hung handler returns a structured MCP error, not a hang/crash, and
    the dispatch path stays usable for the next call;
  * run_powershell keeps its OWN tighter subprocess timeout and is NOT
    double-wrapped/shortened: its dispatch ceiling sits strictly ABOVE
    its own hard subprocess ceiling so the watchdog is a pure backstop
    there;
  * the capture_monitor image-content envelope is preserved for the
    success path.
"""
from __future__ import annotations

import concurrent.futures
import threading
import time

import tools.gamepc_mcp_server as mod


def test_fast_tool_unaffected_by_watchdog(monkeypatch):
    monkeypatch.setitem(mod.TOOL_FUNCS, "get_system_info",
                        lambda **k: {"hostname": "stub", "ok": True})
    t0 = time.perf_counter()
    r = mod.handle_tools_call({"name": "get_system_info", "arguments": {}})
    elapsed = time.perf_counter() - t0
    assert "isError" not in r
    assert "stub" in r["content"][0]["text"]
    assert elapsed < 1.0


def test_slow_tool_hits_watchdog_and_returns_structured_error(monkeypatch):
    started = threading.Event()

    def _hang(**kw):
        started.set()
        time.sleep(30)
        return {"never": True}

    monkeypatch.setitem(mod.TOOL_FUNCS, "get_system_info", _hang)
    monkeypatch.setitem(mod.TOOL_TIMEOUT_OVERRIDES, "get_system_info", 0.3)

    t0 = time.perf_counter()
    r = mod.handle_tools_call({"name": "get_system_info", "arguments": {}})
    elapsed = time.perf_counter() - t0

    assert started.is_set()
    assert r["isError"] is True
    assert r.get("_timeout") is True
    assert "timed out" in r["content"][0]["text"]
    assert elapsed < 5.0          # ~0.3s timeout, not the 30s sleep


def test_dispatch_path_usable_after_timeout(monkeypatch):
    def _hang(**kw):
        time.sleep(30)
        return {}

    monkeypatch.setitem(mod.TOOL_FUNCS, "get_system_info", _hang)
    monkeypatch.setitem(mod.TOOL_TIMEOUT_OVERRIDES, "get_system_info", 0.2)
    bad = mod.handle_tools_call({"name": "get_system_info", "arguments": {}})
    assert bad.get("_timeout") is True

    monkeypatch.setitem(mod.TOOL_FUNCS, "path_exists",
                        lambda **k: {"exists": False})
    ok = mod.handle_tools_call({"name": "path_exists",
                                "arguments": {"path": "x"}})
    assert "isError" not in ok
    assert "exists" in ok["content"][0]["text"]


def test_run_powershell_not_double_wrapped():
    """run_powershell's dispatch ceiling MUST sit strictly above its own
    subprocess hard ceiling so the watchdog never preempts/shortens it -
    it is a pure backstop there, the subprocess timeout governs."""
    ps_ceiling = mod._timeout_for("run_powershell")
    assert ps_ceiling > float(mod.PS_HARD_CEILING)
    # And it is a genuine per-tool override, not the generic default.
    assert ps_ceiling != mod.DISPATCH_TIMEOUT_S
    assert "run_powershell" in mod.TOOL_TIMEOUT_OVERRIDES


def test_run_powershell_own_timeout_still_fires_first(monkeypatch):
    """Simulate run_powershell self-governing: it returns its OWN
    {'error':'timeout'} dict well within its (large) dispatch ceiling.
    The watchdog must pass that through untouched - no _timeout flag,
    no double application."""
    def _ps_self_timeout(command, timeout_s=60):
        # Mimic tool_run_powershell's TimeoutExpired branch shape.
        return {"error": "timeout", "timeout_s": timeout_s,
                "stdout": "", "stderr": ""}

    monkeypatch.setitem(mod.TOOL_FUNCS, "run_powershell", _ps_self_timeout)
    r = mod.handle_tools_call({"name": "run_powershell",
                               "arguments": {"command": "Start-Sleep 9999",
                                             "timeout_s": 5}})
    # Soft error dict -> normal text envelope, NOT the watchdog isError.
    assert "isError" not in r
    assert '"error": "timeout"' in r["content"][0]["text"]
    assert "_timeout" not in r


def test_dispatch_pool_bounded_and_reused():
    assert isinstance(mod._DISPATCH_POOL,
                      concurrent.futures.ThreadPoolExecutor)
    assert mod._DISPATCH_POOL._max_workers <= 16
    before = mod._DISPATCH_POOL
    for _ in range(20):
        mod._dispatch_tool("get_system_info", lambda **k: {"ok": 1}, {})
    assert mod._DISPATCH_POOL is before


def test_capture_monitor_image_envelope_preserved(monkeypatch):
    """The success path still image-wraps capture_monitor output (the
    watchdog only short-circuits on isError)."""
    monkeypatch.setitem(
        mod.TOOL_FUNCS, "capture_monitor",
        lambda **k: {"b64": "QUJD", "media_type": "image/jpeg",
                     "format": "jpeg", "width": 4, "height": 4,
                     "monitor_index": 0})
    r = mod.handle_tools_call({"name": "capture_monitor", "arguments": {}})
    assert "isError" not in r
    assert r["content"][0]["type"] == "image"
    assert r["content"][0]["data"] == "QUJD"
    assert r["content"][1]["type"] == "text"


def test_bad_arguments_structured_through_watchdog():
    r = mod._dispatch_tool("path_exists",
                           lambda path: {"exists": True}, {"wrong_kw": 1})
    assert r["isError"] is True
    assert "bad arguments" in r["content"][0]["text"]


def test_gamepc_server_is_ascii():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    data = (root / "tools" / "gamepc_mcp_server.py").read_bytes()
    bad = [(i, hex(b)) for i, b in enumerate(data) if b > 127]
    assert not bad, f"non-ASCII bytes: {bad[:5]}"
