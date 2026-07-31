# arch: tests for the Mission Control standalone server | section=tests | frozen=no
"""Guards for the S10 decoupling.

The load-bearing one is test_loop_routes_do_not_import_dispatch: it is the
only thing standing between "Mission Control is a separate process" and
"Mission Control is a separate process that still dies with dashboard schema
code". It runs in a SUBPROCESS because an in-process check can be masked by
an earlier test having already imported pydantic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
