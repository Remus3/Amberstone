# arch: tests for the Mission Control standalone server | section=tests | frozen=no
"""Guards for the S10 decoupling.

The load-bearing one is test_loop_routes_do_not_import_dispatch: it is the
only thing standing between "Mission Control is a separate process" and
"Mission Control is a separate process that still dies with dashboard schema
code". It runs in a SUBPROCESS because an in-process check can be masked by
an earlier test having already imported pydantic.
"""
from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _import_probe(module: str, forbidden: list[str]) -> tuple[int, str]:
    """Import `module` in a clean interpreter; report any forbidden module
    that ended up in sys.modules. Returns (returncode, stdout+stderr)."""
    code = (
        f"import sys; import importlib; importlib.import_module({module!r}); "
        f"bad=[m for m in {forbidden!r} if m in sys.modules]; "
        "print('LEAKED:'+','.join(bad)); sys.exit(1 if bad else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_matchers_module_is_stdlib_only():
    """dashboard._matchers must not drag in pydantic or api_schema."""
    rc, out = _import_probe(
        "dashboard._matchers",
        ["pydantic", "dashboard.api_schema", "dashboard._dispatch"],
    )
    assert rc == 0, out


def test_loop_routes_do_not_import_dispatch():
    """Importing either loop route must not reach _dispatch/pydantic."""
    for mod in ("dashboard.routes_loop_status", "dashboard.routes_loop_control"):
        rc, out = _import_probe(
            mod, ["pydantic", "dashboard.api_schema", "dashboard._dispatch"]
        )
        assert rc == 0, f"{mod}: {out}"


def test_dispatch_still_exports_matchers():
    """40-plus route modules import equals/prefix from _dispatch. The
    re-export keeps them working, so this asserts identity, not equality."""
    from dashboard import _dispatch, _matchers
    assert _dispatch.equals is _matchers.equals
    assert _dispatch.prefix is _matchers.prefix


def test_auth_no_token_configured_is_503(tmp_path, monkeypatch):
    """Fail CLOSED. A tokenless server refuses POSTs; it never falls open."""
    from mc import auth
    monkeypatch.delenv("RC_MC_TOKEN", raising=False)
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")
    ok, status, body = auth.check("Bearer anything")
    assert ok is False
    assert status == 503
    assert body["error"] == "auth not configured"


def test_auth_missing_and_malformed_header_is_401(tmp_path, monkeypatch):
    from mc import auth
    monkeypatch.setenv("RC_MC_TOKEN", "s3cret")
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")
    for header in (None, "", "s3cret", "Basic s3cret", "Bearer", "bearer s3cret"):
        ok, status, body = auth.check(header)
        assert ok is False, header
        assert status == 401, header
        assert body["error"] == "unauthorized"


def test_auth_wrong_token_is_401_with_no_oracle(tmp_path, monkeypatch):
    """The wrong-token body must be byte-identical to the missing-header
    body, so a caller cannot distinguish 'no header' from 'bad token'."""
    from mc import auth
    monkeypatch.setenv("RC_MC_TOKEN", "s3cret")
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")
    _, _, missing = auth.check(None)
    _, status, wrong = auth.check("Bearer wrong")
    assert status == 401
    assert wrong == missing


def test_auth_correct_token_passes(tmp_path, monkeypatch):
    from mc import auth
    monkeypatch.setenv("RC_MC_TOKEN", "s3cret")
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")
    ok, status, _ = auth.check("Bearer s3cret")
    assert ok is True
    assert status == 200


def test_auth_file_is_used_when_env_absent(tmp_path, monkeypatch):
    from mc import auth
    monkeypatch.delenv("RC_MC_TOKEN", raising=False)
    tf = tmp_path / "mission_control_token.txt"
    tf.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", tf)
    assert auth.resolve_token() == "from-file"
    ok, _, _ = auth.check("Bearer from-file")
    assert ok is True


def test_auth_env_wins_over_file(tmp_path, monkeypatch):
    from mc import auth
    tf = tmp_path / "mission_control_token.txt"
    tf.write_text("from-file\n", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", tf)
    monkeypatch.setenv("RC_MC_TOKEN", "from-env")
    assert auth.resolve_token() == "from-env"


def test_auth_blank_sources_resolve_to_none(tmp_path, monkeypatch):
    """A whitespace-only token file is 'unconfigured', not a token of spaces."""
    from mc import auth
    monkeypatch.setenv("RC_MC_TOKEN", "   ")
    tf = tmp_path / "mission_control_token.txt"
    tf.write_text("\n", encoding="utf-8")
    monkeypatch.setattr(auth, "TOKEN_FILE", tf)
    assert auth.resolve_token() is None


def test_auth_uses_constant_time_compare():
    """A plain == on a secret is a timing oracle. Assert the real call."""
    import inspect
    from mc import auth
    assert "compare_digest" in inspect.getsource(auth.check)


def test_mc_routes_expose_both_endpoints():
    from mc import routes
    get_paths = [m for m, _ in routes.GET_ROUTES]
    post_paths = [m for m, _ in routes.POST_ROUTES]
    assert any(m("/api/loop-status") for m in get_paths)
    assert any(m("/api/loop-control") for m in post_paths)
    assert not any(m("/api/state") for m in get_paths)


def test_mc_package_imports_no_game_code():
    """The whole point of S10. mc.routes must not reach pydantic, the
    dashboard Handler, or any dashboard route module other than the two
    loop ones."""
    rc, out = _import_probe(
        "mc.routes",
        [
            "pydantic",
            "dashboard.api_schema",
            "dashboard._dispatch",
            "dashboard._handler",
            "dashboard._context",
            "dashboard.builders",
            "dashboard._state_builder",
            "dashboard.routes_state",
            "web_dashboard",
        ],
    )
    assert rc == 0, out


def test_handler_send_signature_matches_route_expectations():
    """Routes call h._send(status, bytes, ctype) positionally. If the
    signature drifts, every route 500s at runtime and no unit test on the
    routes themselves would notice."""
    import inspect
    from mc.handler import Handler
    params = list(inspect.signature(Handler._send).parameters)
    assert params[:4] == ["self", "code", "body", "ctype"]


# --------------------------------------------------------------------------- fix round 1 (reviewer findings)

def test_static_guard_blocks_sibling_directory_prefix_collision(tmp_path, monkeypatch):
    """FINDING 1. A plain str(target).startswith(str(WEB_DIR)) is a STRING
    prefix check, not a path-component check: a sibling directory whose
    name merely starts with the same characters (web/mc-evil/ beside
    web/mc/) passes it, because the string "..../mc-evil/secret.txt"
    starts with the string "..../mc". Live-verified: pointing WEB_DIR at a
    real web/mc/ and requesting /../mc-evil/secret.txt served the sibling
    file with HTTP 200. A correct guard must reject this even though plain
    '..' escapes (covered implicitly here too) already passed before this
    fix - the sibling-prefix case is the one that did not."""
    from mc import handler
    web_root = tmp_path / "fakeweb2"
    real_dir = web_root / "mc"
    real_dir.mkdir(parents=True)
    evil_dir = web_root / "mc-evil"
    evil_dir.mkdir()
    (evil_dir / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    monkeypatch.setattr(handler, "WEB_DIR", real_dir)

    class Fake:
        path = "/../mc-evil/secret.txt"

        def __init__(self):
            self.sent = None

        def _send(self, code, body, ctype, cache_control=None):
            self.sent = (code, body, ctype)

    f = Fake()
    served = handler.Handler._serve_static(f)
    assert served is False, "sibling directory mc-evil/ must not be reachable via .."
    assert f.sent is None, f"secret content must never be sent, got {f.sent!r}"


def test_post_rejects_negative_content_length_without_reading_body(monkeypatch):
    """FINDING 2. n = int(Content-Length) accepts negative values, and
    `n > _MAX_POST_BYTES` is never true for a negative n, so the size cap
    is skipped and rfile.read(n) runs with n unmodified. On a real
    socket-backed rfile, read(-1) reads until EOF - unbounded, defeating
    the exact cap this line exists to enforce. Live-verified: a mocked
    rfile receives n=-1 for Content-Length: -1. The fix must reject a
    negative Content-Length before rfile.read is ever called - checked
    here directly by recording every call the route layer makes to
    rfile.read, independent of whatever status code downstream route
    logic happens to produce from whatever bytes it is handed."""
    from mc import handler
    monkeypatch.setenv("RC_MC_TOKEN", "s3cret")

    class RecordingRfile:
        def __init__(self):
            self.calls = []

        def read(self, n):
            self.calls.append(n)
            return b"{}"

    class Fake:
        path = "/api/loop-control"
        headers = {"Authorization": "Bearer s3cret", "Content-Length": "-1"}

        def __init__(self):
            self.sent = None
            self.rfile = RecordingRfile()

        def _send(self, code, body, ctype, cache_control=None):
            self.sent = (code, body, ctype)

        def _send_json(self, code, payload):
            self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    f = Fake()
    handler.Handler.do_POST(f)
    assert f.rfile.calls == [], (
        f"rfile.read was called with {f.rfile.calls} for a negative "
        "Content-Length - the cap was bypassed"
    )
    assert f.sent is not None
    code, raw_body, _ctype = f.sent
    assert code == 400
    assert json.loads(raw_body)["error"] == "invalid content-length"


def test_post_non_numeric_content_length_is_400_not_500(monkeypatch):
    """FINDING 3 (minor). A non-numeric Content-Length currently raises
    inside int() and is caught only by do_POST's generic except Exception,
    producing a 500 where a 400 is correct - the request is malformed, not
    an internal server fault. No data leak, just an imprecise status."""
    from mc import handler
    monkeypatch.setenv("RC_MC_TOKEN", "s3cret")

    class Fake:
        path = "/api/loop-control"
        headers = {"Authorization": "Bearer s3cret", "Content-Length": "not-a-number"}

        def __init__(self):
            self.sent = None

        def _send(self, code, body, ctype, cache_control=None):
            self.sent = (code, body, ctype)

        def _send_json(self, code, payload):
            self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    f = Fake()
    handler.Handler.do_POST(f)
    assert f.sent is not None
    code, raw_body, _ctype = f.sent
    assert code == 400
    assert json.loads(raw_body)["error"] == "invalid content-length"


# --------------------------------------------------------------------------- task 4 (real socket, auth-before-dispatch)

@pytest.fixture
def live_mc(monkeypatch, tmp_path):
    """A real Mission Control handler on a loopback socket, plain HTTP.

    TLS is not exercised here - it is a stdlib concern and the acceptance
    run covers it live. What matters is that auth sits in front of dispatch.
    """
    from mc import auth, handler as mc_handler
    monkeypatch.setenv("RC_MC_TOKEN", "test-token")
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")

    fired: list = []

    def _spy(h, body):
        fired.append(body)
        h._send(200, b'{"ok": true, "spied": true}', "application/json")

    monkeypatch.setattr(
        mc_handler.routes, "POST_ROUTES",
        [(lambda p: p == "/api/loop-control", _spy)],
    )
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mc_handler.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield srv.server_address, fired
    finally:
        srv.shutdown()
        srv.server_close()


def _post(addr, path, body, token=None):
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=10)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("POST", path, json.dumps(body), headers)
    resp = conn.getresponse()
    out = (resp.status, json.loads(resp.read().decode("utf-8")))
    conn.close()
    return out


def test_live_post_without_token_never_reaches_the_route(live_mc):
    """The property a unit test cannot prove: auth runs BEFORE dispatch."""
    addr, fired = live_mc
    status, body = _post(addr, "/api/loop-control", {"action": "stop"})
    assert status == 401
    assert body["error"] == "unauthorized"
    assert fired == [], "route executed despite a rejected request"


def test_live_post_with_token_reaches_the_route(live_mc):
    addr, fired = live_mc
    status, body = _post(addr, "/api/loop-control", {"action": "stop"}, token="test-token")
    assert status == 200
    assert body["spied"] is True
    assert fired == [{"action": "stop"}]


def test_live_get_is_open(live_mc):
    """Status must be readable with no token - bind scope is its perimeter."""
    addr, _ = live_mc
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=10)
    conn.request("GET", "/api/loop-status")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 200


def test_live_static_traversal_is_refused(live_mc):
    addr, _ = live_mc
    conn = http.client.HTTPConnection(addr[0], addr[1], timeout=10)
    conn.request("GET", "/../../CLAUDE.md")
    resp = conn.getresponse()
    resp.read()
    conn.close()
    assert resp.status == 404


# --------------------------------------------------------------------------- task 5 (bind, TLS, process entry)

def test_bind_scope_is_loopback_and_tailnet_only():
    """A wildcard bind would silently expose the control plane on the LAN.
    Operator decision 2026-07-31: tailnet + loopback only."""
    from mc import server
    assert server.PORT == 8895
    assert set(server.BIND_ADDRESSES) == {"127.0.0.1", "100.70.22.55"}
    for addr in server.BIND_ADDRESSES:
        assert addr not in ("0.0.0.0", "::", ""), "wildcard bind"
    assert "192.168.8.230" not in server.BIND_ADDRESSES, "LAN bind"


def test_bind_failure_exits_non_zero(monkeypatch):
    """dashboard/server.py:195 warns and keeps going when the port is taken.
    Copied here that yields a control plane that is silently absent."""
    from mc import server

    def _boom(*a, **kw):
        raise OSError(10048, "address in use")

    monkeypatch.setattr(server, "_make_server", _boom)
    assert server.main() != 0


def test_no_hot_reload_watcher():
    """core.hot_reload must never be imported by either Mission Control
    entry point. Checked with _import_probe (clean subprocess), the same
    technique test_loop_routes_do_not_import_dispatch uses above, so an
    earlier test having already imported hot_reload elsewhere in this
    process cannot mask a real leak here.

    A substring scan over inspect.getsource() was tried first and
    rejected: it is defeated by anything that assembles the module name
    at runtime (e.g. "core." + "hot_" + "reload") or by a
    differently-named watcher doing the same job, and it never looked at
    mission_control.py at all - the actual process entry point.

    Scope, stated honestly: this is an IMPORT-TIME guard. It proves
    mc.server and mission_control do not import core.hot_reload, directly
    or transitively, merely by being imported. It does NOT prove main()
    never constructs an equivalent watcher lazily at runtime - that needs
    a runtime/behavioral check, not an import-time one."""
    for mod in ("mc.server", "mission_control"):
        rc, out = _import_probe(mod, ["core.hot_reload"])
        assert rc == 0, f"{mod}: {out}"
