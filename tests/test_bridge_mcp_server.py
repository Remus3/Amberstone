"""Tests for tools/bridge_mcp_server.py - the local cross-Claude bridge MCP.

Mirrors the layered approach of tests/test_ds_matchdb_mcp_server.py:
  1. Pure tool functions with the HTTP shuttle + filesystem deps
     monkeypatched (input validation, normalization, fail-soft on
     dashboard-down).
  2. The MCP protocol handlers (initialize / tools/list / tools/call
     dispatch + error shapes) called directly.
  3. A real ThreadingHTTPServer on an ephemeral port for the HTTP/auth +
     JSON-RPC envelope contract.

Plus a TOOLS_SCHEMA<->TOOL_FUNCS parity guard and an ASCII-only guard
(project hard rule: no em/en-dashes or smart quotes in authored files).
"""
from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

import tools.bridge_mcp_server as mod


# --------------------------------------------------------------------------
# Fakes / helpers
# --------------------------------------------------------------------------
class _Captured:
    """Captures the last HTTP shuttle call (url + payload) for assertions."""

    def __init__(self):
        self.get_url = None
        self.post_url = None
        self.post_payload = None
        self.get_response = {"now": 1234.0, "messages": []}
        self.post_response = {"ok": True, "ts": 1234.5,
                              "id": "task-abc", "kind": "task"}

    def install(self, monkeypatch):
        def fake_get(url, timeout=4.0):
            self.get_url = url
            return self.get_response

        def fake_post(url, payload, timeout=4.0):
            self.post_url = url
            self.post_payload = payload
            return self.post_response

        monkeypatch.setattr(mod, "_http_get_json", fake_get)
        monkeypatch.setattr(mod, "_http_post_json", fake_post)


# --------------------------------------------------------------------------
# 1. Pure tool functions - validation, normalization, fail-soft
# --------------------------------------------------------------------------
def test_bridge_search_default_since_zero(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    out = mod.tool_bridge_search()
    assert "since=0" in cap.get_url
    assert "limit=100" in cap.get_url
    assert out["count"] == 0
    assert out["messages"] == []


def test_bridge_search_hours_overrides_since(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    fixed_now = 10_000.0
    monkeypatch.setattr(mod.time, "time", lambda: fixed_now)
    mod.tool_bridge_search(since=1.0, hours=2.0)
    # hours wins; 2 hours = 7200s, since_ts = 10000 - 7200 = 2800
    assert "since=2800" in cap.get_url


def test_bridge_search_limit_cap_500(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    mod.tool_bridge_search(limit=99999)
    assert "limit=500" in cap.get_url


def test_bridge_search_filters_appended(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    mod.tool_bridge_search(kind="task", target="LEGION", source="Atx")
    assert "kind=task" in cap.get_url
    assert "target=legion" in cap.get_url  # normalized lowercase
    assert "source=peer" in cap.get_url


def test_bridge_search_dashboard_down_returns_error_dict(monkeypatch):
    def boom(url, timeout=4.0):
        raise URLError("connection refused")

    monkeypatch.setattr(mod, "_http_get_json", boom)
    out = mod.tool_bridge_search()
    assert "unreachable" in out["error"]
    assert out["url"] == mod.LEGION_BRIDGE_URL


def test_bridge_post_note_blank_source():
    assert "source required" in mod.tool_bridge_post_note("", "x")["error"]
    assert "source required" in mod.tool_bridge_post_note("  ", "x")["error"]


def test_bridge_post_note_blank_summary():
    assert "summary required" in mod.tool_bridge_post_note("legion", "")["error"]


def test_bridge_post_note_happy(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    out = mod.tool_bridge_post_note("LEGION", "hello world")
    assert out["ok"] is True
    assert cap.post_url == mod.LEGION_BRIDGE_URL
    assert cap.post_payload == {"source": "legion", "summary": "hello world",
                                 "kind": "note"}


def test_bridge_post_task_required_fields():
    assert "source required" in mod.tool_bridge_post_task(
        "", "peer", "x", {})["error"]
    assert "target required" in mod.tool_bridge_post_task(
        "legion", "", "x", {})["error"]
    assert "summary required" in mod.tool_bridge_post_task(
        "legion", "peer", "", {})["error"]


def test_bridge_post_task_body_must_be_dict(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    out = mod.tool_bridge_post_task("legion", "peer", "x", body=[1, 2])
    assert "body must be a JSON object" in out["error"]
    assert out["got"] == "list"
    # Did not even reach the HTTP shuttle:
    assert cap.post_url is None


def test_bridge_post_task_auto_stamps_id(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    # Real dashboard echoes the posted id back; fake the same so we can
    # assert the round-trip plumbing.
    cap.post_response = {"ok": True, "ts": 1.0, "id": None, "kind": "task"}
    out = mod.tool_bridge_post_task("legion", "peer", "do thing",
                                     body={"prompt": "x"})
    assert cap.post_payload["id"].startswith("task-")
    assert len(cap.post_payload["id"]) > len("task-")
    # Dashboard returned id=None, so the auto-stamped id should fill in.
    assert out["id"] == cap.post_payload["id"]
    assert cap.post_payload["kind"] == "task"
    assert cap.post_payload["target"] == "peer"


def test_bridge_post_task_explicit_id_wins(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    cap.post_response = {"ok": True, "ts": 1.0, "id": "task-pinned-1234",
                          "kind": "task"}
    mod.tool_bridge_post_task("legion", "peer", "x", body={},
                              id="task-pinned-1234")
    assert cap.post_payload["id"] == "task-pinned-1234"


def test_bridge_post_task_dashboard_echoed_id_preserved(monkeypatch):
    """If the dashboard returns an id (which it does in the real handler),
    that id is reflected in the ack - the local fill-in is only a
    safety net for the (theoretical) blank-echo case."""
    cap = _Captured(); cap.install(monkeypatch)
    cap.post_response = {"ok": True, "ts": 1.0, "id": "task-server-stamped",
                          "kind": "task"}
    out = mod.tool_bridge_post_task("legion", "peer", "x", body={})
    assert out["id"] == "task-server-stamped"


def test_bridge_post_result_requires_in_reply_to():
    assert "in_reply_to required" in mod.tool_bridge_post_result(
        "legion", "peer", "x", in_reply_to="", body={})["error"]


def test_bridge_post_result_happy(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    cap.post_response = {"ok": True, "ts": 1.0, "id": "r1", "kind": "result"}
    out = mod.tool_bridge_post_result("legion", "peer", "done",
                                       in_reply_to="task-xyz",
                                       body={"exit_code": 0})
    assert out["kind"] == "result"
    assert cap.post_payload == {"source": "legion", "summary": "done",
                                 "kind": "result", "target": "peer",
                                 "in_reply_to": "task-xyz",
                                 "body": {"exit_code": 0}}


def test_bridge_post_lesson_happy(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    cap.post_response = {"ok": True, "ts": 1.0, "id": None, "kind": "lesson"}
    out = mod.tool_bridge_post_lesson("legion", "peer", "lesson summary",
                                       body={"text": "do x not y"})
    assert out["ok"] is True
    assert cap.post_payload["kind"] == "lesson"


def test_bridge_post_lesson_body_optional_defaults_to_empty(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    mod.tool_bridge_post_lesson("legion", "peer", "ls", body=None)
    assert cap.post_payload["body"] == {}


def test_bridge_post_http_error_carries_status(monkeypatch):
    class _Err(HTTPError):
        def __init__(self):
            super().__init__("u", 400, "bad", {}, None)

        def read(self):
            return b'{"error":"missing_summary"}'

    def boom(*a, **kw):
        raise _Err()

    monkeypatch.setattr(mod, "_http_post_json", boom)
    out = mod.tool_bridge_post_note("legion", "x")
    assert out["http_status"] == 400
    assert "missing_summary" in out["response_body"]


def test_bridge_pending_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_PENDING_PATH", tmp_path / "nope.json")
    out = mod.tool_bridge_pending()
    assert out["watcher_status"] == "no_file"
    assert out["tasks"] == []
    assert out["schema_version"] == 1


def test_bridge_pending_with_file(monkeypatch, tmp_path):
    p = tmp_path / "pending.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "tasks": [{"task_id": "task-1", "summary": "do x"}],
    }), encoding="utf-8")
    monkeypatch.setattr(mod, "_PENDING_PATH", p)
    out = mod.tool_bridge_pending()
    assert out["schema_version"] == 1
    assert out["tasks"][0]["task_id"] == "task-1"


def test_bridge_pending_corrupt_file_returns_error(monkeypatch, tmp_path):
    p = tmp_path / "pending.json"
    p.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(mod, "_PENDING_PATH", p)
    out = mod.tool_bridge_pending()
    assert "JSONDecodeError" in out["error"]


def test_bridge_pending_non_dict_payload_normalized(monkeypatch, tmp_path):
    p = tmp_path / "pending.json"
    p.write_text(json.dumps(["unexpected", "list"]), encoding="utf-8")
    monkeypatch.setattr(mod, "_PENDING_PATH", p)
    out = mod.tool_bridge_pending()
    assert out["schema_version"] == 1
    assert out["tasks"] == []


def test_bridge_status_proxies_status_url(monkeypatch):
    cap = _Captured(); cap.install(monkeypatch)
    cap.get_response = {"configured": True, "secret_present": True}
    out = mod.tool_bridge_status()
    assert cap.get_url == mod.LEGION_BRIDGE_STATUS_URL
    assert out["configured"] is True


def test_resolve_token_env_override(monkeypatch):
    monkeypatch.setenv("RC_MCP_TOKEN", "  envtok456  ")
    assert mod._resolve_token() == "envtok456"


# --------------------------------------------------------------------------
# 2. MCP protocol handlers (direct)
# --------------------------------------------------------------------------
def test_handle_initialize():
    r = mod.handle_initialize({})
    assert r["protocolVersion"] == mod.PROTOCOL_VERSION
    assert r["serverInfo"]["name"] == "rc-bridge-mcp"


def test_handle_tools_list_parity():
    tools = mod.handle_tools_list({})["tools"]
    names = {t["name"] for t in tools}
    assert names == set(mod.TOOL_FUNCS.keys())
    for t in tools:
        assert t["name"] and t["description"] and "inputSchema" in t


def test_handle_tools_call_unknown_tool():
    r = mod.handle_tools_call({"name": "nope", "arguments": {}})
    assert r["isError"] is True
    assert "unknown tool" in r["content"][0]["text"]


def test_handle_tools_call_bad_arguments():
    r = mod.handle_tools_call({"name": "bridge_post_note",
                               "arguments": {"wrong_kw": 1}})
    assert r["isError"] is True
    assert "bad arguments" in r["content"][0]["text"]


def test_handle_tools_call_tool_exception(monkeypatch):
    def boom(**k):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(mod.TOOL_FUNCS, "bridge_pending", boom)
    r = mod.handle_tools_call({"name": "bridge_pending", "arguments": {}})
    assert r["isError"] is True
    assert "RuntimeError: kaboom" in r["content"][0]["text"]


def test_handle_tools_call_happy(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_PENDING_PATH", tmp_path / "nope.json")
    r = mod.handle_tools_call({"name": "bridge_pending", "arguments": {}})
    assert "isError" not in r
    payload = json.loads(r["content"][0]["text"])
    assert payload["watcher_status"] == "no_file"


# --------------------------------------------------------------------------
# 3. Real HTTP server - auth + JSON-RPC envelope contract
# --------------------------------------------------------------------------
@pytest.fixture()
def server():
    srv = ThreadingHTTPServer((mod.HOST, 0), mod._Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://{mod.HOST}:{port}", mod.AUTH_TOKEN
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _post(base, token, body):
    req = Request(f"{base}/mcp", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json",
                           "Authorization": f"Bearer {token}"},
                  method="POST")
    with urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_http_auth_required(server):
    base, _ = server
    req = Request(f"{base}/mcp", data=b"{}", method="POST",
                  headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as ei:
        urlopen(req, timeout=5)
    assert ei.value.code == 401


def test_http_auth_wrong_token(server):
    base, _ = server
    with pytest.raises(HTTPError) as ei:
        _post(base, "wrong-token", {"jsonrpc": "2.0", "id": 1,
                                    "method": "initialize"})
    assert ei.value.code == 401


def test_http_initialize(server):
    base, tok = server
    st, env = _post(base, tok, {"jsonrpc": "2.0", "id": 1,
                                "method": "initialize"})
    assert st == 200
    assert env["result"]["serverInfo"]["name"] == "rc-bridge-mcp"
    assert env["id"] == 1


def test_http_tools_list(server):
    base, tok = server
    _, env = _post(base, tok, {"jsonrpc": "2.0", "id": 2,
                               "method": "tools/list"})
    assert len(env["result"]["tools"]) == len(mod.TOOL_FUNCS)


def test_http_tools_call_pending_no_file(server, monkeypatch, tmp_path):
    base, tok = server
    monkeypatch.setattr(mod, "_PENDING_PATH", tmp_path / "nope.json")
    _, env = _post(base, tok, {"jsonrpc": "2.0", "id": 3,
                               "method": "tools/call",
                               "params": {"name": "bridge_pending",
                                          "arguments": {}}})
    payload = json.loads(env["result"]["content"][0]["text"])
    assert payload["watcher_status"] == "no_file"


def test_http_notification_returns_202(server):
    base, tok = server
    req = Request(f"{base}/mcp",
                  data=json.dumps({"jsonrpc": "2.0",
                                   "method": "notifications/initialized"}).encode(),
                  headers={"Content-Type": "application/json",
                           "Authorization": f"Bearer {tok}"},
                  method="POST")
    with urlopen(req, timeout=5) as resp:
        assert resp.status == 202


def test_http_parse_error(server):
    base, tok = server
    req = Request(f"{base}/mcp", data=b"{not json",
                  headers={"Content-Type": "application/json",
                           "Authorization": f"Bearer {tok}"},
                  method="POST")
    with urlopen(req, timeout=5) as resp:
        env = json.loads(resp.read().decode())
    assert env["error"]["code"] == -32700


def test_http_method_not_found(server):
    base, tok = server
    _, env = _post(base, tok, {"jsonrpc": "2.0", "id": 9,
                               "method": "bogus/method"})
    assert env["error"]["code"] == -32601


def test_http_health_endpoint(server):
    base, tok = server
    req = Request(f"{base}/health",
                  headers={"Authorization": f"Bearer {tok}"})
    with urlopen(req, timeout=5) as resp:
        body = json.loads(resp.read().decode())
    assert body["alive"] is True
    assert set(body["tools"]) == set(mod.TOOL_FUNCS.keys())


def test_http_unknown_path_404(server):
    base, tok = server
    req = Request(f"{base}/nope", headers={"Authorization": f"Bearer {tok}"})
    with pytest.raises(HTTPError) as ei:
        urlopen(req, timeout=5)
    assert ei.value.code == 404


# --------------------------------------------------------------------------
# 4. ASCII-only guard (project hard rule)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("rel", [
    "tools/bridge_mcp_server.py",
    "tools/start_bridge_mcp.py",
])
def test_authored_files_are_ascii(rel):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    data = (root / rel).read_bytes()
    bad = [(i, hex(b)) for i, b in enumerate(data) if b > 127]
    assert not bad, f"{rel} has non-ASCII bytes: {bad[:5]}"


# --------------------------------------------------------------------------
# 5. Hung-tool dispatch watchdog
# --------------------------------------------------------------------------
def test_fast_tool_returns_normally_under_watchdog(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_PENDING_PATH", tmp_path / "nope.json")
    t0 = time.perf_counter()
    r = mod.handle_tools_call({"name": "bridge_pending", "arguments": {}})
    elapsed = time.perf_counter() - t0
    assert "isError" not in r
    payload = json.loads(r["content"][0]["text"])
    assert payload["watcher_status"] == "no_file"
    assert elapsed < 1.0


def test_slow_tool_hits_watchdog_timeout(monkeypatch):
    started = threading.Event()

    def _hang(**kw):
        started.set()
        time.sleep(30)
        return {"never": "returned"}

    monkeypatch.setitem(mod.TOOL_FUNCS, "bridge_pending", _hang)
    monkeypatch.setitem(mod.TOOL_TIMEOUT_OVERRIDES, "bridge_pending", 0.3)
    t0 = time.perf_counter()
    r = mod.handle_tools_call({"name": "bridge_pending", "arguments": {}})
    elapsed = time.perf_counter() - t0
    assert started.is_set()
    assert r["isError"] is True
    assert r.get("_timeout") is True
    assert "timed out" in r["content"][0]["text"]
    assert elapsed < 5.0


def test_dispatch_pool_is_bounded_and_reused():
    assert isinstance(mod._DISPATCH_POOL,
                      concurrent.futures.ThreadPoolExecutor)
    assert mod._DISPATCH_POOL._max_workers <= 16
    before = mod._DISPATCH_POOL
    for _ in range(25):
        mod._dispatch_tool("bridge_pending",
                           lambda **k: {"tasks": []}, {})
    assert mod._DISPATCH_POOL is before


def test_dispatch_tool_propagates_structured_errors():
    def _boom(**k):
        raise RuntimeError("kaboom")

    r = mod._dispatch_tool("x", _boom, {})
    assert r["isError"] is True
    assert "RuntimeError: kaboom" in r["content"][0]["text"]

    def _needs_arg(required):
        return {"ok": required}

    r2 = mod._dispatch_tool("x", _needs_arg, {"wrong": 1})
    assert r2["isError"] is True
    assert "bad arguments" in r2["content"][0]["text"]
