"""Tests for tools/ds_matchdb_mcp_server.py - the local DS + match-DB MCP.

Covers three layers without a live DS engine or real socket where it can:
  1. Pure tool functions with module-level deps monkeypatched (engine-down
     fail-soft, archetype auto-resolve, match-db-missing, arg validation).
  2. The MCP protocol handlers (initialize / tools/list / tools/call
     dispatch + error shapes) called directly.
  3. A real ThreadingHTTPServer on an ephemeral port for the HTTP/auth +
     JSON-RPC envelope contract (401 gate, notifications, parse errors).

Plus a TOOLS_SCHEMA<->TOOL_FUNCS parity guard and an ASCII-only guard
(project hard rule: no em/en-dashes or smart quotes in authored files).
"""
from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import tools.ds_matchdb_mcp_server as mod


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------
class _FakeBuildResult:
    def to_dict(self):
        return {"champion": "Vayne", "archetype": "carry", "order": [],
                "order_str": "none", "unique_passive_safe": True}


class _FakeMatchDB:
    def __init__(self):
        self.calls = []

    def get_recent(self, mode, limit):
        self.calls.append(("get_recent", mode, limit))
        return [{"id": 1, "mode": mode or "SR", "champion": "Vayne",
                 "grade": "A"}]

    def get_mode_stats(self, mode, limit):
        self.calls.append(("get_mode_stats", mode, limit))
        return {"games": 3, "avg_kills": 7.0}

    def get_best_comps(self, mg, limit):
        self.calls.append(("get_best_comps", mg, limit))
        return [{"tft_comp": "Anima", "games": 4, "avg_place": 2.5}]

    def get_worst_comps(self, mg, limit):
        self.calls.append(("get_worst_comps", mg, limit))
        return [{"tft_comp": "Primordian", "games": 3, "avg_place": 6.7}]

    def get_tft_streak(self, limit):
        self.calls.append(("get_tft_streak", limit))
        return {"last_n": 5, "avg_place": 3.2, "wins": 1}


# --------------------------------------------------------------------------
# 1. Pure tool functions - fail-soft + behavior
# --------------------------------------------------------------------------
def test_ds_health_engine_down(monkeypatch):
    monkeypatch.setattr(mod, "_is_engine_up", lambda timeout=1.0: False)
    out = mod.tool_ds_health()
    assert out["engine_up"] is False
    assert "unreachable" in out["error"]


def test_ds_health_engine_up(monkeypatch):
    monkeypatch.setattr(mod, "_is_engine_up", lambda timeout=1.0: True)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"engine_version":"1.3.0","patch":"16.10.1"}'

    monkeypatch.setattr(mod, "urlopen", lambda *a, **k: _Resp())
    out = mod.tool_ds_health()
    assert out["engine_up"] is True
    assert out["health"]["engine_version"] == "1.3.0"


def test_ds_rank_items_blank_champion():
    assert "error" in mod.tool_ds_rank_items("")
    assert "error" in mod.tool_ds_rank_items("   ")


def test_ds_rank_items_engine_down(monkeypatch):
    monkeypatch.setattr(mod, "_get_archetype_for",
                        lambda c: {"primary": "carry"})
    monkeypatch.setattr(mod, "_rank_for_primary_archetype",
                        lambda *a, **k: None)
    out = mod.tool_ds_rank_items("Vayne")
    assert out["engine_up"] is False
    assert "unreachable" in out["error"]
    assert out["archetype"] == "carry"


def test_ds_rank_items_auto_resolves_archetype(monkeypatch):
    seen = {}

    def fake_rank(champ, arch, **kw):
        seen["champ"] = champ
        seen["arch"] = arch
        seen["kw"] = kw
        return {"ok": True, "scorer": "ability", "archetype": arch,
                "ranked": [], "fell_back": False}

    monkeypatch.setattr(mod, "_get_archetype_for",
                        lambda c: {"primary": "mage"})
    monkeypatch.setattr(mod, "_rank_for_primary_archetype", fake_rank)
    out = mod.tool_ds_rank_items("Veigar", level=9,
                                 owned_item_ids=["3020", "", None],
                                 target_mr=30.0, top=5)
    assert seen["arch"] == "mage"          # blank -> resolved primary
    assert seen["kw"]["level"] == 9
    assert seen["kw"]["item_ids"] == ["3020"]  # falsy ids filtered
    assert seen["kw"]["target_mr"] == 30.0
    assert seen["kw"]["top"] == 5
    assert out["scorer"] == "ability"


def test_ds_rank_items_explicit_archetype_wins(monkeypatch):
    seen = {}
    monkeypatch.setattr(mod, "_get_archetype_for",
                        lambda c: {"primary": "carry"})
    monkeypatch.setattr(
        mod, "_rank_for_primary_archetype",
        lambda champ, arch, **kw: seen.update(arch=arch) or
        {"ok": True, "scorer": "ehp", "archetype": arch, "ranked": []})
    mod.tool_ds_rank_items("Malphite", archetype="TANK")
    assert seen["arch"] == "tank"          # explicit, lowercased


def test_ds_build_order_blank_champion():
    assert "error" in mod.tool_ds_build_order("")


def test_ds_build_order_engine_down(monkeypatch):
    monkeypatch.setattr(mod, "_get_archetype_for",
                        lambda c: {"primary": "carry"})
    monkeypatch.setattr(mod, "_plan_build_order", lambda *a, **k: None)
    out = mod.tool_ds_build_order("Vayne")
    assert out["engine_up"] is False


def test_ds_build_order_happy(monkeypatch):
    monkeypatch.setattr(mod, "_get_archetype_for",
                        lambda c: {"primary": "carry"})
    monkeypatch.setattr(mod, "_plan_build_order",
                        lambda *a, **k: _FakeBuildResult())
    out = mod.tool_ds_build_order("Vayne", slots=6)
    assert out["champion"] == "Vayne"
    assert out["unique_passive_safe"] is True


def test_ds_archetype_for(monkeypatch):
    monkeypatch.setattr(mod, "_get_archetype_for",
                        lambda c: {"primary": "carry", "secondary": "bruiser",
                                   "source": "default"})
    assert "error" in mod.tool_ds_archetype_for("")
    out = mod.tool_ds_archetype_for("Vayne")
    assert out["primary"] == "carry"


def test_match_recent_db_missing(monkeypatch):
    monkeypatch.setattr(mod, "_get_match_db", lambda: None)
    out = mod.tool_match_recent()
    assert "not found" in out["error"]


def test_match_recent_happy_and_cap(monkeypatch):
    fake = _FakeMatchDB()
    monkeypatch.setattr(mod, "_get_match_db", lambda: fake)
    out = mod.tool_match_recent(mode="ARAM", limit=9999)
    assert out["mode"] == "ARAM"
    assert out["count"] == 1
    assert fake.calls[-1] == ("get_recent", "ARAM", 200)  # capped at 200


def test_match_mode_stats_requires_mode(monkeypatch):
    monkeypatch.setattr(mod, "_get_match_db", lambda: _FakeMatchDB())
    assert "error" in mod.tool_match_mode_stats("")


def test_match_mode_stats_happy(monkeypatch):
    fake = _FakeMatchDB()
    monkeypatch.setattr(mod, "_get_match_db", lambda: fake)
    out = mod.tool_match_mode_stats("SR", limit=10)
    assert out["stats"]["games"] == 3
    assert fake.calls[-1] == ("get_mode_stats", "SR", 10)


def test_match_tft_comps_routing(monkeypatch):
    fake = _FakeMatchDB()
    monkeypatch.setattr(mod, "_get_match_db", lambda: fake)
    best = mod.tool_match_tft_comps(which="best")
    assert best["which"] == "best" and best["comps"][0]["tft_comp"] == "Anima"
    worst = mod.tool_match_tft_comps(which="WORST", min_games=3)
    assert worst["which"] == "worst"
    assert worst["comps"][0]["tft_comp"] == "Primordian"
    bad = mod.tool_match_tft_comps(which="bogus")
    assert "error" in bad


def test_match_tft_streak(monkeypatch):
    monkeypatch.setattr(mod, "_get_match_db", lambda: None)
    assert "not found" in mod.tool_match_tft_streak()["error"]
    monkeypatch.setattr(mod, "_get_match_db", lambda: _FakeMatchDB())
    out = mod.tool_match_tft_streak(limit=5)
    assert out["streak"]["last_n"] == 5


def test_get_match_db_none_when_path_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, "_match_db", None)
    monkeypatch.setattr(mod, "_MATCH_DB_PATH", tmp_path / "nope.db")
    assert mod._get_match_db() is None


def test_resolve_token_env_override(monkeypatch):
    monkeypatch.setenv("RC_MCP_TOKEN", "  envtok123  ")
    assert mod._resolve_token() == "envtok123"


# --------------------------------------------------------------------------
# 2. MCP protocol handlers (direct)
# --------------------------------------------------------------------------
def test_handle_initialize():
    r = mod.handle_initialize({})
    assert r["protocolVersion"] == mod.PROTOCOL_VERSION
    assert r["serverInfo"]["name"] == "ds-matchdb-mcp"


def test_handle_tools_list_parity():
    tools = mod.handle_tools_list({})["tools"]
    names = {t["name"] for t in tools}
    assert names == set(mod.TOOL_FUNCS.keys())  # schema<->impl parity
    for t in tools:
        assert t["name"] and t["description"] and "inputSchema" in t


def test_handle_tools_call_unknown_tool():
    r = mod.handle_tools_call({"name": "nope", "arguments": {}})
    assert r["isError"] is True
    assert "unknown tool" in r["content"][0]["text"]


def test_handle_tools_call_bad_arguments():
    r = mod.handle_tools_call({"name": "ds_archetype_for",
                               "arguments": {"wrong_kw": 1}})
    assert r["isError"] is True
    assert "bad arguments" in r["content"][0]["text"]


def test_handle_tools_call_tool_exception(monkeypatch):
    def boom(**k):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(mod.TOOL_FUNCS, "ds_health", boom)
    r = mod.handle_tools_call({"name": "ds_health", "arguments": {}})
    assert r["isError"] is True
    assert "RuntimeError: kaboom" in r["content"][0]["text"]


def test_handle_tools_call_happy(monkeypatch):
    monkeypatch.setattr(mod, "_is_engine_up", lambda timeout=1.0: False)
    r = mod.handle_tools_call({"name": "ds_health", "arguments": {}})
    assert "isError" not in r
    payload = json.loads(r["content"][0]["text"])
    assert payload["engine_up"] is False


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
    assert env["result"]["serverInfo"]["name"] == "ds-matchdb-mcp"
    assert env["id"] == 1


def test_http_tools_list(server):
    base, tok = server
    _, env = _post(base, tok, {"jsonrpc": "2.0", "id": 2,
                               "method": "tools/list"})
    assert len(env["result"]["tools"]) == len(mod.TOOL_FUNCS)


def test_http_tools_call_match_db_missing(server, monkeypatch):
    base, tok = server
    monkeypatch.setattr(mod, "_get_match_db", lambda: None)
    _, env = _post(base, tok, {"jsonrpc": "2.0", "id": 3,
                               "method": "tools/call",
                               "params": {"name": "match_tft_streak",
                                          "arguments": {}}})
    payload = json.loads(env["result"]["content"][0]["text"])
    assert "not found" in payload["error"]


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
    "tools/ds_matchdb_mcp_server.py",
    "tools/start_ds_matchdb_mcp.py",
])
def test_authored_files_are_ascii(rel):
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    data = (root / rel).read_bytes()
    bad = [(i, hex(b)) for i, b in enumerate(data) if b > 127]
    assert not bad, f"{rel} has non-ASCII bytes: {bad[:5]}"
