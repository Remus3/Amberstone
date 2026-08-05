# Mission Control S10 Decouple Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Mission Control out of the RC game dashboard into its own process,
port and asset tree, reachable by IP over the tailnet and gated by a bearer
token, so no dashboard or game-overlay change can break the control plane.

**Architecture:** A new `mission_control.py` entry plus an `mc/` package serves
HTTPS on `:8895`, bound to loopback and the tailnet address only. It imports the
EXISTING `dashboard.routes_loop_status` / `routes_loop_control` modules rather
than forking them, and all control-plane logic stays in `ops/loop/*`. A new
stdlib-only `dashboard/_matchers.py` breaks the last import edge that would drag
pydantic and game schema code into the new process. The dashboard's Mission
Control card, JS, CSS and route registrations are deleted last, after the new
surface is proven live.

**Tech Stack:** Python 3.14 stdlib only (`http.server`, `ssl`, `hmac`,
`pathlib`). No new dependencies. Vanilla ESM JavaScript, no framework. pytest.
`node --test` for the pure JS module. Windows Task Scheduler for lifecycle.

**Spec:** `docs/superpowers/specs/2026-07-31-mission-control-s10-decouple-design.md`

## Global Constraints

- **7-bit ASCII only** in all authored content - code, comments, docstrings,
  `.md`, commit messages. No em-dashes or en-dashes (U+2013, U+2014), no smart
  quotes (U+201C U+201D U+2018 U+2019). Use ` - ` for a clause break.
- **Every new `.py` file starts with an arch header**:
  `# arch: <one-line purpose> | section=mc | frozen=no`
- **Atomic writes only** for any file this code writes:
  `tmp.write_text(...); tmp.replace(target)`.
- **Never `Stop-Process`** - use `taskkill /F /PID <pid>`.
- **`py_compile` before any restart.** Syntax errors crash silently under
  `pythonw.exe`.
- **No frozen file is touched by this plan.** Confirmed against the CLAUDE.md
  frozen list: `web_dashboard.py`, `dashboard/*`, `web/*`, `ops/loop/*` route
  consumers are all non-frozen. If a task appears to require editing
  `ops/rc_supervisor.py`, `main.py`, or any `app/*` module, STOP and ask.
- **Never edit `ops/loop/slots.py` or `ops/loop/winmutex.py`** - byte-identical
  by contract with the Sibling-A repo, pinned by `SHARED_SHA256`.
- **Never fire lanes 7 or 8.** They have never been fired, deliberately.
- **Run the full suite from the REPO ROOT**, never from a subdirectory.
- **`node --check` is not a valid syntax check** for import-leading JS files -
  it exits 0 on a duplicate `const`. Use `tests/test_web_js_esm_parse.py`.
- Commit messages: use `git commit -F <tmpfile>` with an ASCII-only file.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `dashboard/_matchers.py` | The two path-matcher factories, stdlib only. Sole reason it exists: let the loop routes be imported without pulling in pydantic. |
| `mc/__init__.py` | Package marker. |
| `mc/auth.py` | Bearer-token resolution and the POST gate. Nothing else. |
| `mc/routes.py` | Assembles GET/POST tables from the existing dashboard route modules. No route logic of its own. |
| `mc/handler.py` | Minimal `BaseHTTPRequestHandler`: `_send`, static serving, GET/POST dispatch, auth call-out. |
| `mc/server.py` | Bind, TLS, `serve_forever`. Fails loud. |
| `mission_control.py` | Process entry point. Logging setup, then `mc.server.main()`. |
| `web/mc/index.html` | The control-plane page. Imports no game code. |
| `web/mc/mc.css` | All Mission Control styling, tokens inlined. |
| `web/mc/mc.js` | The renderer, relocated from `dev.js`. |
| `tests/test_mission_control_server.py` | Auth, bind scope, import isolation, de-registration and residue guards. |

**Moved:**

| From | To |
|---|---|
| `web/js/lib/arm_confirm.js` | `web/mc/arm_confirm.js` |
| `web/js/lib/arm_confirm.test.mjs` | `web/mc/arm_confirm.test.mjs` |

**Modified:**

| Path | Change |
|---|---|
| `dashboard/_dispatch.py:43-51` | Move `equals`/`prefix` bodies out, re-export from `_matchers`. Drop the two loop-route registrations at `:147` and `:210`. |
| `dashboard/routes_loop_status.py:80` | Import `equals` from `_matchers`. |
| `dashboard/routes_loop_control.py:88` | Import `equals` from `_matchers`. Update the trust-model docstring. |
| `web/js/panels/dev.js` | Delete lines 9-10 (the arm_confirm import) and 341-1019 (the Mission Control block). |
| `web/js/main.js:843` | Remove the `renderLoopStatus()` call. |
| `web/index.html:1625-1637` | Delete the Mission Control card. |
| `web/css/panels/header.css:2956-3178` | Delete the Mission Control CSS. TWO blocks, not one - see Task 9 Step 6. |
| `tests/test_mission_control_panel.py` | Re-point four path constants and one literal-string assertion. |
| `tests/test_interrupt_panel.py` | Re-point two path constants. |
| `tests/test_web_ascii_sweep.py:79` | Re-point the `arm_confirm.js` path. |

**Task order is load-bearing.** Tasks 1-7 build and prove the new surface while
the dashboard keeps working. Task 8 deploys and verifies it live. Only Task 9
removes the old one. Reversing 8 and 9 leaves a window with no working control
plane.

---

### Task 1: Break the pydantic import edge

Importing `dashboard._dispatch` executes `from dashboard.api_schema import ...`,
which imports pydantic. Both loop-route modules import `equals` from there, so
without this task the new process inherits a failure domain it exists to escape.
`equals` and `prefix` are pure two-line factories with no dependencies.

**Files:**
- Create: `dashboard/_matchers.py`
- Modify: `dashboard/_dispatch.py:41-51`, `dashboard/routes_loop_status.py:80`, `dashboard/routes_loop_control.py:88`
- Test: `tests/test_mission_control_server.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `dashboard._matchers.equals(path: str) -> Callable[[str], bool]` and
  `dashboard._matchers.prefix(p: str) -> Callable[[str], bool]`. Task 4 relies on
  the loop-route modules no longer importing `_dispatch`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mission_control_server.py`:

```python
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
        "import sys; import importlib; importlib.import_module(%r); "
        "bad=[m for m in %r if m in sys.modules]; "
        "print('LEAKED:'+','.join(bad)); sys.exit(1 if bad else 0)"
        % (module, forbidden)
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_mission_control_server.py -v
```

Expected: `test_matchers_module_is_stdlib_only` and
`test_dispatch_still_exports_matchers` FAIL with `ModuleNotFoundError: No module
named 'dashboard._matchers'`. `test_loop_routes_do_not_import_dispatch` FAILS
with `LEAKED:pydantic,dashboard.api_schema,dashboard._dispatch`.

- [ ] **Step 3: Create `dashboard/_matchers.py`**

```python
# arch: path-matcher factories (stdlib-only, importable without pydantic) | section=dashboard | frozen=no
"""The two route path matchers, split out of _dispatch.py on 2026-07-31.

Reason for the split, so it is not "simplified" back later: importing
dashboard._dispatch executes `from dashboard.api_schema import ...`, which
imports pydantic. Mission Control (mc/) imports the two loop-route modules in
its own process and must NOT inherit that dependency - the whole point of S10
is that the control plane does not share a failure domain with dashboard
schema code. Keep this module stdlib-only. It is guarded by
tests/test_mission_control_server.py::test_matchers_module_is_stdlib_only.

_dispatch re-exports both names, so the 40-plus route modules that do
`from dashboard._dispatch import equals` keep working unchanged.
"""
from __future__ import annotations

from typing import Callable


def equals(path: str) -> Callable[[str], bool]:
    """Match exactly `path`, or `path?...` (path with a query string)."""
    return lambda p: p == path or p.startswith(path + "?")


def prefix(p: str) -> Callable[[str], bool]:
    """Match anything starting with prefix `p`."""
    return lambda x: x.startswith(p)
```

- [ ] **Step 4: Replace the bodies in `dashboard/_dispatch.py`**

Delete lines 41-51 (the `# -- matcher factories` comment block through the end
of `prefix`) and put this in their place:

```python
# -- matcher factories ------------------------------------------------
# Bodies live in dashboard/_matchers.py (2026-07-31, Mission Control S10) so
# they can be imported without pulling in api_schema + pydantic. Re-exported
# here because 40-plus route modules already import them from this module.
from dashboard._matchers import equals, prefix  # noqa: E402,F401
```

- [ ] **Step 5: Re-point the two loop-route imports**

In `dashboard/routes_loop_status.py`, line 80, change:

```python
from dashboard._dispatch import equals
```

to:

```python
from dashboard._matchers import equals
```

Make the identical change in `dashboard/routes_loop_control.py` at line 88.

- [ ] **Step 6: Run the tests**

```bash
python -m pytest tests/test_mission_control_server.py tests/test_loop_status_route.py tests/test_interrupt_route.py -v
```

Expected: all PASS.

- [ ] **Step 7: Prove nothing else regressed**

The re-export touches every route module in the app, so this is the one task
that needs a broad run even though it looks tiny.

```bash
python -m pytest tests/ -x -q -n 8
```

Expected: PASS. If a module fails on `equals` or `prefix`, the re-export line
is missing or misplaced - it must come before any route module is imported.

- [ ] **Step 8: Commit**

```bash
git add dashboard/_matchers.py dashboard/_dispatch.py dashboard/routes_loop_status.py dashboard/routes_loop_control.py tests/test_mission_control_server.py
git commit -m "refactor(dashboard): split path matchers out of _dispatch for S10"
```

---

### Task 2: Bearer-token auth gate

Fails CLOSED. A server with no token configured refuses every POST rather than
falling open - the inverse of RC's usual fail-soft rule, and deliberate, because
this surface can kill processes.

**Files:**
- Create: `mc/__init__.py`, `mc/auth.py`
- Test: `tests/test_mission_control_server.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `mc.auth.resolve_token() -> str | None` and
  `mc.auth.check(auth_header: str | None) -> tuple[bool, int, dict]` returning
  `(ok, status, body)` where `status`/`body` are meaningful only when `ok` is
  False. Task 3's `do_POST` calls `check`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mission_control_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_mission_control_server.py -k auth -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mc'`.

- [ ] **Step 3: Create `mc/__init__.py`**

```python
# arch: Mission Control standalone serving layer (S10) | section=mc | frozen=no
"""Mission Control - the RC control plane, served as its own process.

S10 (2026-07-31) moved the SERVING layer out of the RC game dashboard. The
LOGIC did not move: lanes, launcher, steer, interrupt and intents all still
live in ops/loop/*, and the HTTP routes are the existing
dashboard.routes_loop_{status,control} modules, imported rather than forked.

Nothing in this package may import game-dashboard code. See
tests/test_mission_control_server.py for the guard that enforces it.
"""
```

- [ ] **Step 4: Create `mc/auth.py`**

```python
# arch: Mission Control bearer-token gate (POST only, fails closed) | section=mc | frozen=no
"""Bearer-token auth for the Mission Control POST surface.

Resolution order mirrors core/vision_token.py, first hit wins:
  1. env RC_MC_TOKEN
  2. config/mission_control_token.txt (first line, stripped)

There is NO hardcoded fallback and NO fail-open. If neither source yields a
token, every POST is refused with 503. This is the inverse of RC's usual
fail-soft rule and it is deliberate: S9 added an action that KILLS PROCESSES,
so an unconfigured control plane must refuse rather than serve.

GET is not gated here. The bind scope (loopback + tailnet only, see
mc/server.py) is the perimeter for read-only status.

The token is never logged, never echoed in a response body, and never placed
in a URL or query string.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "mission_control_token.txt"

_BEARER = "Bearer "

# Byte-identical for "no header" and "wrong token" - a caller must not be able
# to tell which of the two it hit.
_UNAUTHORIZED = {"ok": False, "error": "unauthorized"}
_UNCONFIGURED = {"ok": False, "error": "auth not configured"}


def resolve_token() -> str | None:
    """The active token, or None when the server has none configured."""
    env = os.environ.get("RC_MC_TOKEN", "").strip()
    if env:
        return env
    try:
        first = TOKEN_FILE.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return first or None


def check(auth_header: str | None) -> tuple[bool, int, dict]:
    """Gate one request. Returns (ok, status, body).

    status and body are only meaningful when ok is False; the caller sends
    them verbatim and does no further work."""
    token = resolve_token()
    if token is None:
        return False, 503, dict(_UNCONFIGURED)
    if not auth_header or not auth_header.startswith(_BEARER):
        return False, 401, dict(_UNAUTHORIZED)
    supplied = auth_header[len(_BEARER):].strip()
    if not hmac.compare_digest(supplied, token):
        return False, 401, dict(_UNAUTHORIZED)
    return True, 200, {}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_mission_control_server.py -k auth -v
```

Expected: 8 PASS.

- [ ] **Step 6: Commit**

```bash
git add mc/__init__.py mc/auth.py tests/test_mission_control_server.py
git commit -m "feat(mc): bearer-token auth gate, fails closed when unconfigured"
```

---

### Task 3: Route tables and the minimal handler

The handler is deliberately small. It reimplements only what the two route
modules actually consume: `_send(status, body_bytes, ctype)` and a parsed JSON
POST body. `tests/test_loop_status_route.py` already drives those routes against
a 6-line `FakeHandler`, which is the proof the contract is this narrow.

**Files:**
- Create: `mc/routes.py`, `mc/handler.py`
- Test: `tests/test_mission_control_server.py` (append)

**Interfaces:**
- Consumes: `mc.auth.check` from Task 2.
- Produces: `mc.routes.GET_ROUTES` / `mc.routes.POST_ROUTES`, each a
  `list[tuple[Callable[[str], bool], Callable]]`; and
  `mc.handler.Handler`, a `BaseHTTPRequestHandler` subclass. Task 5 passes
  `Handler` to the server constructor.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mission_control_server.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_mission_control_server.py -k "mc_routes or mc_package or handler_send" -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mc.routes'`.

- [ ] **Step 3: Create `mc/routes.py`**

```python
# arch: Mission Control route tables (imports, never forks, the loop routes) | section=mc | frozen=no
"""GET/POST tables for the Mission Control server.

These are the SAME route modules the dashboard used to serve, imported
directly. There is no second copy of any handler, and there must never be:
the repo already carries one byte-identical-by-contract pair and does not
need a second class of them.

Import safety is load-bearing and guarded. Both modules import their path
matcher from dashboard._matchers (NOT dashboard._dispatch), which is what
keeps pydantic and the game route tree out of this process. See
tests/test_mission_control_server.py::test_mc_package_imports_no_game_code.
"""
from __future__ import annotations

from dashboard import routes_loop_control, routes_loop_status

GET_ROUTES: list = (
    list(routes_loop_status.GET_ROUTES) + list(routes_loop_control.GET_ROUTES)
)
POST_ROUTES: list = (
    list(routes_loop_status.POST_ROUTES) + list(routes_loop_control.POST_ROUTES)
)
```

- [ ] **Step 4: Create `mc/handler.py`**

```python
# arch: Mission Control HTTP handler (minimal, no dashboard Handler) | section=mc | frozen=no
"""The Mission Control request handler.

Deliberately minimal. It implements exactly what the two loop-route modules
consume - `_send(code, body, ctype)` and a parsed JSON POST body - plus static
file serving for web/mc/. It does NOT subclass or import the dashboard's
Handler, which carries game state, supervisor proxying and vision auth.

CSRF: the bearer requirement on POST is itself the cross-origin defence. A
browser cannot attach an Authorization header cross-origin without a CORS
preflight, and this server answers no preflight, so a hostile page cannot
drive this surface even from a machine that can reach it.

Static assets are served no-store: web/mc/ is outside the dashboard's
compute_asset_hash sweep, so there is no cache-busting hash on these URLs and
a cached mc.js would silently serve stale control-plane code.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from mc import auth, routes

log = logging.getLogger("rc.mc.handler")

WEB_DIR = Path(__file__).resolve().parent.parent / "web" / "mc"

# RC is single-operator and these bodies are tiny (an action plus an
# idempotency key). Mirrors the dashboard's 1 MiB cap.
_MAX_POST_BYTES = 1 * 1024 * 1024

# RM-152: the size cap is not a bound on TIME. Copy
# `dashboard/_handler.Handler._read_body_deadlined` verbatim - it arms this
# budget on the socket for the body read only and restores the previous
# timeout in a finally, so nothing else on the connection sees a deadline.
_BODY_READ_TIMEOUT_S = 10.0

_CTYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "RCMissionControl/1.0"

    # -- response helper the route modules call ----------------------

    def _send(self, code: int, body: bytes, ctype: str,
              cache_control: str | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control or "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # client hung up; nothing to do and nothing to log loudly

    def _send_json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args) -> None:
        """Route access logs into RC logging instead of stderr."""
        log.info("%s %s", self.address_string(), fmt % args)

    # -- static ------------------------------------------------------

    def _serve_static(self) -> bool:
        rel = "index.html" if self.path in ("/", "") else self.path.lstrip("/")
        rel = rel.split("?", 1)[0]
        target = (WEB_DIR / rel).resolve()
        # Path traversal guard: the resolved path must stay inside WEB_DIR.
        if not str(target).startswith(str(WEB_DIR.resolve())):
            return False
        if not target.is_file():
            return False
        ctype = _CTYPES.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)
        return True

    # -- verbs -------------------------------------------------------

    def do_GET(self) -> None:
        try:
            for matcher, handler in routes.GET_ROUTES:
                if matcher(self.path):
                    handler(self)
                    return
            if self._serve_static():
                return
            self._send_json(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # noqa: BLE001 - never take the server down
            log.warning("do_GET %s: %s", self.path, exc)
            self._send_json(500, {"ok": False, "error": "internal error"})

    def do_POST(self) -> None:
        try:
            ok, status, body = auth.check(self.headers.get("Authorization"))
            if not ok:
                self._send_json(status, body)
                return
            n = int(self.headers.get("Content-Length", "0"))
            if n < 0 or n > _MAX_POST_BYTES:
                self._send_json(413, {"ok": False, "error": "payload too large"})
                return
            # RM-152: the size cap above does not bound a client that declares
            # a legal length and then sends nothing; that pins one
            # ThreadingHTTPServer worker per connection. Read the body under a
            # wall-clock deadline armed on the socket and restored right after.
            #
            # Do NOT reach for the simpler class-level `timeout` instead. The
            # reason is NOT that it truncates a streamed or slow-to-produce
            # response - MEASURED 2026-08-04 on the dashboard twin, it does not:
            # an 8 MiB proxied payload arrived byte-complete at a reader stalled
            # 3s mid-stream, and the SSE stream still delivered frames, because
            # the send buffer absorbs the write. What it breaks is the READ
            # side. socketserver arms it on the connection in `setup()`, so it
            # deadlines the request line and headers too, and a client slow to
            # speak - or one whose headers arrive in two packets with a gap - is
            # aborted outright. MC's pollers open a fresh HTTP/1.0 connection
            # per tick, so every one of them would be exposed. Mirror
            # `dashboard/_handler.Handler._read_body_deadlined`, including its
            # no-socket fall-through: this read runs before any auth gate, and
            # an exception raised here is answered as a 400 by the `except`
            # below, which would mask the reply the request had earned.
            try:
                raw = self._read_body_deadlined(n) if n else b""
            except TimeoutError:
                self._send_json(408, {"ok": False, "error": "body read timeout"})
                return
            payload = json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
            for matcher, handler in routes.POST_ROUTES:
                if matcher(self.path):
                    handler(self, payload)
                    return
            self._send_json(404, {"ok": False, "error": "not found"})
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "invalid json"})
        except Exception as exc:  # noqa: BLE001 - never take the server down
            log.warning("do_POST %s: %s", self.path, exc)
            self._send_json(500, {"ok": False, "error": "internal error"})
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_mission_control_server.py -v
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add mc/routes.py mc/handler.py tests/test_mission_control_server.py
git commit -m "feat(mc): route tables and minimal handler, no game-code imports"
```

---

### Task 4: End-to-end auth behaviour over a real socket

Task 2 tested the gate function. This tests the wired server: that a POST
without a token never reaches the route, and that one with a token does. The
unit test cannot catch a handler that checks auth AFTER dispatching.

**Files:**
- Test: `tests/test_mission_control_server.py` (append)

**Interfaces:**
- Consumes: `mc.handler.Handler` from Task 3.
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mission_control_server.py`:

```python
import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_mission_control_server.py -k live -v
```

Expected: FAIL - the fixture and helpers do not exist yet on first write; after
adding them, `test_live_post_without_token_never_reaches_the_route` is the one
that proves ordering. If it passes trivially, check that `_spy` really is wired.

- [ ] **Step 3: Confirm the implementation already satisfies them**

No new implementation code. `mc/handler.py` from Task 3 calls `auth.check`
before reading the body or scanning `POST_ROUTES`. If any test fails, the fix
belongs in `do_POST` ordering, not in the test.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_mission_control_server.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_mission_control_server.py
git commit -m "test(mc): prove auth runs before dispatch over a real socket"
```

---

### Task 5: Server bind, TLS and the process entry

Two things here differ from the dashboard on purpose: the bind is an explicit
narrow list rather than a wildcard, and a bind failure exits non-zero instead of
warning and idling.

**Files:**
- Create: `mc/server.py`, `mission_control.py`
- Test: `tests/test_mission_control_server.py` (append)

**Interfaces:**
- Consumes: `mc.handler.Handler` from Task 3.
- Produces: `mc.server.PORT` (int, 8895), `mc.server.BIND_ADDRESSES`
  (`list[str]`), `mc.server.main() -> int` returning a process exit code.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mission_control_server.py`:

```python
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
    """A control plane must not restart itself because an unrelated .py
    changed. Guarding the absence, because adding it back would look like
    a helpful consistency fix."""
    import inspect
    from mc import server
    src = inspect.getsource(server)
    assert "hot_reload" not in src
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_mission_control_server.py -k "bind or hot_reload" -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mc.server'`.

- [ ] **Step 3: Create `mc/server.py`**

```python
# arch: Mission Control HTTPS server (:8895, tailnet + loopback only) | section=mc | frozen=no
"""Bind, TLS and serve for Mission Control.

Three deliberate differences from dashboard/server.py, each with a reason:

  1. EXPLICIT NARROW BIND, not a dual-stack wildcard. One socket per address
     in BIND_ADDRESSES. A wildcard bind would put a process-killing surface
     on the LAN, which operator decision 2026-07-31 rules out.
  2. BIND FAILURE EXITS NON-ZERO. dashboard/server.py logs a warning and
     returns when the port is unavailable, leaving RC up and the dashboard
     silently absent. For a control plane that is the worst shape a failure
     can take, so this exits and lets the scheduled task's restart policy
     (RestartCount=3, RestartInterval=1min) engage and record it.
  3. NO HOT-RELOAD WATCHER. core.hot_reload is deliberately not started.

TLS reuses the existing mkcert material at ops/tls/rc.pem. A SAN is
host-scoped, not port-scoped, and tools/regen_rc_cert.ps1 already lists
legion-rc, legion-rc.tailc150de.ts.net and 100.70.22.55, so :8895 validates
with NO cert regen. -k is not acceptable on a surface that can kill.
"""
from __future__ import annotations

import logging
import socket
import ssl
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from mc.handler import Handler

log = logging.getLogger("rc.mc.server")

ROOT = Path(__file__).resolve().parent.parent
PORT = 8895
# Loopback plus the Tailscale address. NOT the LAN address (192.168.8.230)
# and NOT a wildcard - see the module docstring.
BIND_ADDRESSES = ["127.0.0.1", "100.70.22.55"]

CERT_PATH = ROOT / "ops" / "tls" / "rc.pem"
KEY_PATH = ROOT / "ops" / "tls" / "rc-key.pem"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(CERT_PATH), keyfile=str(KEY_PATH))
    return ctx


def _make_server(address: str, ctx: ssl.SSLContext) -> ThreadingHTTPServer:
    """One bound, TLS-wrapped server. Raises on failure - callers do not
    swallow it, they exit."""
    srv = ThreadingHTTPServer((address, PORT), Handler)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    return srv


def main() -> int:
    """Serve until killed. Returns a process exit code; never returns 0
    from a failure path."""
    if not (CERT_PATH.exists() and KEY_PATH.exists()):
        log.error("Mission Control: TLS material missing at %s / %s. "
                  "A control plane that can kill processes does not serve "
                  "plaintext - refusing to start.", CERT_PATH, KEY_PATH)
        return 2

    try:
        ctx = _ssl_context()
    except (ssl.SSLError, OSError) as exc:
        log.error("Mission Control: TLS setup failed: %s", exc)
        return 2

    servers = []
    try:
        for address in BIND_ADDRESSES:
            servers.append(_make_server(address, ctx))
            log.info("Mission Control listening on https://%s:%d/", address, PORT)
    except OSError as exc:
        for srv in servers:
            srv.server_close()
        log.error("Mission Control: bind failed on :%d (%s). Exiting so the "
                  "scheduled task records the failure.", PORT, exc)
        return 3

    threads = []
    for srv in servers[1:]:
        t = threading.Thread(target=srv.serve_forever, daemon=True,
                             name=f"MissionControl-{srv.server_address[0]}")
        t.start()
        threads.append(t)
    try:
        servers[0].serve_forever()
    except KeyboardInterrupt:
        log.info("Mission Control: interrupted, shutting down")
    finally:
        for srv in servers:
            srv.server_close()
    return 0
```

Note on `BIND_ADDRESSES`: if the Tailscale address is not yet up when the task
starts at logon, binding `100.70.22.55` raises `OSError` and the process exits.
That is intended - the restart policy retries, and by the third attempt
Tailscale is up. A process that silently served loopback-only would look
healthy while being unreachable from the phone.

- [ ] **Step 4: Create `mission_control.py`**

```python
# arch: Mission Control process entry (:8895) | section=mc | frozen=no
"""Mission Control entry point.

Run under pythonw.exe by the RC-MissionControl scheduled task. Deliberately
independent of RC: this process is NOT supervisor-managed and does NOT watch
restart_trigger.txt, so an RC restart for a game-overlay change cannot touch
the control plane. That independence is the whole point of S10.

Its own log file, not the shared logs/YYYY-MM-DD.log - two processes
appending to one file on Windows is a lock hazard, and a control-plane log
interleaved with game-dashboard chatter is hardest to read at exactly the
moment it matters.
"""
from __future__ import annotations

import datetime as _dt
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y-%m-%d")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(logs / f"mission_control-{stamp}.log",
                                      encoding="utf-8")],
    )


def main() -> int:
    _setup_logging()
    from mc import server
    return server.main()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Compile and run the tests**

```bash
python -m py_compile mission_control.py mc/server.py mc/handler.py mc/auth.py mc/routes.py
python -m pytest tests/test_mission_control_server.py -v
```

Expected: py_compile silent, all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add mc/server.py mission_control.py tests/test_mission_control_server.py
git commit -m "feat(mc): :8895 server, narrow bind, loud on bind failure"
```

---

### Task 6: The standalone asset tree

Copy, do not move, the JS in this task. The dashboard must keep working until
Task 9 removes it, so both copies exist briefly and that is intentional.

**Files:**
- Create: `web/mc/index.html`, `web/mc/mc.css`, `web/mc/mc.js`
- Move: `web/js/lib/arm_confirm.js` -> `web/mc/arm_confirm.js`,
  `web/js/lib/arm_confirm.test.mjs` -> `web/mc/arm_confirm.test.mjs`
- Modify: `web/js/panels/dev.js:10` (import path, temporary)

**Interfaces:**
- Consumes: the routes served by Task 3 at `/api/loop-status` and
  `/api/loop-control`.
- Produces: a page whose entry function is `renderLoopStatus()`, invoked on load
  and on a timer from `mc.js` itself rather than from a view router.

- [ ] **Step 1: Move `arm_confirm` with git so history follows**

```bash
mkdir -p "web/mc"
git mv web/js/lib/arm_confirm.js web/mc/arm_confirm.js
git mv web/js/lib/arm_confirm.test.mjs web/mc/arm_confirm.test.mjs
```

- [ ] **Step 2: Keep the dashboard working across the move**

`web/js/panels/dev.js:10` currently reads:

```javascript
import { createArmController } from '../lib/arm_confirm.js';
```

Change it to:

```javascript
import { createArmController } from '../../mc/arm_confirm.js';
```

This line is deleted entirely in Task 9. It exists only so the dashboard is not
broken between here and there.

- [ ] **Step 3: Verify the moved JS test still runs**

```bash
node --test web/mc/arm_confirm.test.mjs
```

Expected: PASS. If it fails on an import path, fix the import inside
`arm_confirm.test.mjs` - it references its sibling module.

- [ ] **Step 4: Create `web/mc/mc.js` from the dev.js block**

Copy `web/js/panels/dev.js` lines **341 through 1018** verbatim into
`web/mc/mc.js`, then apply exactly these edits:

1. Prepend the header and the one import:

```javascript
// Mission Control - the RC control plane, standalone (S10, 2026-07-31).
//
// This file imports NO game-dashboard code, by design. During S9 a single
// `mk` ReferenceError in web/js/panels/dev.js - game-dashboard code, not
// Mission Control code - left the INTERRUPT victim list unrendered while the
// armed kill button still displayed. That is the measurement S10 exists to
// answer, so keep this file's import list at exactly one entry.
import { createArmController } from './arm_confirm.js';
```

2. The relocated code calls a DOM helper named `mk` that came from `dev.js`'s
   enclosing scope. Add it explicitly near the top, below the import:

```javascript
// Was an enclosing-scope helper in dev.js. Defined here so it is impossible
// for this file to reference a binding it does not own - the exact defect
// class S9 hit.
function mk(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
```

Before writing that helper, read the real `mk` in `dev.js` and reproduce its
behaviour exactly. Do not guess from call sites - grep it:

```bash
grep -n "function mk\|const mk\|mk =" web/js/panels/dev.js
```

3. Every `fetch("/api/loop-control", {...})` call must now send the token. Find
   all of them (there are 5, at relative offsets from lines 350, 441, 497, 601,
   639 in the original) and route them through one helper. Add near the top:

```javascript
// Bearer token. Prompted once, kept in localStorage. A 401 clears it and
// re-prompts; a 503 means the SERVER has no token configured, which is a
// deploy problem the operator must fix on Legion - retrying cannot help.
const TOKEN_KEY = "rc_mc_token";

function mcToken() {
  let t = localStorage.getItem(TOKEN_KEY);
  if (!t) {
    t = window.prompt("Mission Control token");
    if (t) localStorage.setItem(TOKEN_KEY, t);
  }
  return t || "";
}

function mcPost(body) {
  return fetch("/api/loop-control", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer " + mcToken(),
    },
    body: JSON.stringify(body),
  }).then((r) => {
    if (r.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      throw new Error("unauthorized - token cleared, retry to re-enter it");
    }
    if (r.status === 503) {
      throw new Error("auth not configured on the server");
    }
    return r.json();
  });
}
```

Replace each of the 5 `fetch("/api/loop-control", ...)` call sites with
`mcPost(<the same body object>)`.

**Watch the double-parse.** Each existing site is shaped
`fetch(...).then((r) => r.json()).then((data) => ...)`. `mcPost` ALREADY returns
parsed JSON, so the `.then((r) => r.json())` link must be DELETED at every site,
not carried over. Leaving it in makes `data` a rejected promise and every button
silently does nothing - which is exactly the failure shape S9 hit and the shape
no source-literal test catches.

4. Append a self-driving bootstrap. In the dashboard, `renderLoopStatus()` was
   called by the view router at `web/js/main.js:843`. There is no router here:

```javascript
// No view router in this page - it IS the view. Render on load, then poll.
renderLoopStatus();
setInterval(() => renderLoopStatus(), 5000);
```

- [ ] **Step 5: Create `web/mc/mc.css`**

Copy `web/css/panels/header.css` lines **2957 through 3178** verbatim into
`web/mc/mc.css`.

**This is TWO blocks and the obvious grep finds only one of them.** Searching
for "Mission Control" matches the S4 sub-block comment at 3018 (lock rows and
arm/confirm) and nothing else. The FOUNDATION - `.loop-status-body`,
`.loop-state-row`, `.loop-dot`, `.loop-mode`, `.loop-line`, `.loop-log`,
`.loop-btn`, `.loop-ta`, `.loop-controls`, `.loop-dir-row`, `.loop-ctl-msg` -
sits above it from 2957, under a comment reading
`/* Headless loop status card (Settings; reads /api/loop-status)`. Copy only
3018+ and the page renders with its rows unstyled. Start at 2957, the comment
line, and take everything through 3178 (the line before `.mode-pill` at 3179).

Then prepend the design tokens the block references. Find which tokens are
actually used rather than copying the dashboard's whole token file:

```bash
grep -o "var(--[a-z0-9-]*)" web/mc/mc.css | sort -u
```

For each token reported, look up its value in `web/css/` and inline it into a
`:root { }` block at the top of `mc.css`. Undefined CSS variables fail SILENTLY -
the property inherits instead of erroring and nothing greps as broken - so
verify every one resolves.

- [ ] **Step 6: Create `web/mc/index.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RC Mission Control</title>
  <link rel="stylesheet" href="/mc.css" />
</head>
<body>
  <header class="mc-head">
    <h1>MISSION CONTROL</h1>
    <span class="mc-sub">RC control plane - independent of the game dashboard</span>
  </header>
  <main>
    <div class="loop-status-body" id="loop-status-body">
      <div class="home-empty">loading loop status...</div>
    </div>
  </main>
  <script type="module" src="/mc.js"></script>
</body>
</html>
```

The `id="loop-status-body"` and the `home-empty` class are load-bearing - the
relocated renderer looks the element up by that exact id, and before S4 the id
existed nowhere in the markup so the panel never rendered at all. Do not rename
either without changing `mc.js` in the same edit.

- [ ] **Step 7: Validate the JS the only way that works**

```bash
python -m pytest tests/test_web_js_esm_parse.py -v
node --test web/mc/arm_confirm.test.mjs
```

Expected: both PASS. Do NOT substitute `node --check web/mc/mc.js` - it returns
exit 0 on a duplicate `const` in an import-leading file, which this is.

- [ ] **Step 8: Commit**

```bash
git add web/mc web/js/panels/dev.js
git commit -m "feat(mc): standalone asset tree, arm_confirm moved with its suite"
```

---

### Task 7: Re-point the tests that pin file paths

Five of the eight test files are path-agnostic and move unchanged. Three pin
paths on disk and must be re-pointed, including one that asserts a literal
import string rather than a path constant.

**Files:**
- Modify: `tests/test_mission_control_panel.py`, `tests/test_interrupt_panel.py`, `tests/test_web_ascii_sweep.py:79`

**Interfaces:**
- Consumes: the `web/mc/` tree from Task 6.
- Produces: nothing.

- [ ] **Step 1: Re-point `tests/test_mission_control_panel.py`**

Lines 22-25 currently read:

```python
INDEX = ROOT / "web" / "index.html"
DEV_JS = ROOT / "web" / "js" / "panels" / "dev.js"
ARM_JS = ROOT / "web" / "js" / "lib" / "arm_confirm.js"
CSS = ROOT / "web" / "css" / "panels" / "header.css"
```

Replace with:

```python
INDEX = ROOT / "web" / "mc" / "index.html"
MC_JS = ROOT / "web" / "mc" / "mc.js"
ARM_JS = ROOT / "web" / "mc" / "arm_confirm.js"
CSS = ROOT / "web" / "mc" / "mc.css"
```

**Rename `DEV_JS` to `MC_JS` throughout** (operator ruling 2026-07-31). A
constant named after a file it no longer points to misleads every future reader
of these tests. This is a mechanical rename - find every reference, including
any derived module-level reader such as `_DEV`, and rename consistently:

```bash
grep -n "DEV_JS\|_DEV\b" tests/test_mission_control_panel.py tests/test_interrupt_panel.py
```

Rename the derived reader to match (`_DEV` -> `_MC`). Do not leave a mixed
pair - a `MC_JS` constant feeding a `_DEV` variable is the same defect one level
down.

- [ ] **Step 2: Fix the literal-string assertion**

Line 94 asserts the import path as a STRING, so a path-constant edit does not
cover it:

```python
    assert "from '../lib/arm_confirm.js'" in _DEV
```

The module is now a sibling, so change it to:

```python
    assert "from './arm_confirm.js'" in _DEV
```

- [ ] **Step 3: Update the two slice markers**

Lines 386-387 slice by comment marker:

```python
        "index.html card": _slice(_INDEX, "<!-- Mission Control S4", "</section>"),
        "header.css block": _slice(_CSS, "/* Mission Control S4", ".mode-pill"),
```

The new files have no such markers. Slice the whole file instead, since both are
now entirely Mission Control:

```python
        "index.html card": _INDEX,
        "mc.css block": _CSS,
```

- [ ] **Step 4: Re-point `tests/test_interrupt_panel.py`**

Lines 26-27:

```python
DEV_JS = ROOT / "web" / "js" / "panels" / "dev.js"
CSS = ROOT / "web" / "css" / "panels" / "header.css"
```

become:

```python
MC_JS = ROOT / "web" / "mc" / "mc.js"
CSS = ROOT / "web" / "mc" / "mc.css"
```

Apply the same `DEV_JS` -> `MC_JS` rename here, derived readers included.

Also update the docstrings at `test_mission_control_panel.py:4-5` and
`test_interrupt_panel.py:5` that cite `web/js/lib/arm_confirm.test.mjs`, and the
comment at `test_interrupt_panel.py:213` that cites `dev.js:168` and `dev.js:778`
- those line numbers are now wrong. Re-derive them:

```bash
grep -n "createArmController" web/mc/mc.js
```

- [ ] **Step 5: Re-point the ASCII sweep**

`tests/test_web_ascii_sweep.py:79` names `web/js/lib/arm_confirm.js`. Update it
to `web/mc/arm_confirm.js`, otherwise the sweep silently stops covering that
file - it will not fail, it will just check nothing.

- [ ] **Step 6: Run the whole Mission Control test set**

```bash
python -m pytest tests/test_mission_control_panel.py tests/test_interrupt_panel.py tests/test_interrupt_route.py tests/test_interrupt_tier.py tests/test_loop_status_route.py tests/test_lane_launcher.py tests/test_steer_channel.py tests/test_web_ascii_sweep.py tests/test_mission_control_server.py -v
```

Expected: 159-plus PASS, 0 fail. Report the exact count observed in THIS run.

- [ ] **Step 7: Commit**

```bash
git add tests/
git commit -m "test(mc): re-point panel and ascii-sweep paths at web/mc"
```

---

### Task 8: Deploy and verify live, BEFORE removing anything

Order matters. Landing the removal first leaves a window with no working control
plane at all.

**Files:**
- Create: `config/mission_control_token.txt` (gitignored - verify it is)
- Create: `tools/install_mission_control_task.ps1`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: a live `RC-MissionControl` scheduled task.

- [ ] **Step 1: Confirm the token file will not be committed**

```bash
git check-ignore -v config/mission_control_token.txt
```

Expected: a matching `.gitignore` rule is printed. If nothing prints, the file
is NOT ignored - add `config/mission_control_token.txt` to `.gitignore` and
commit that before continuing. A committed control-plane token is a real leak.

- [ ] **Step 2: Generate and write the token**

```bash
python -c "import secrets; print(secrets.token_hex(16))"
```

Write the output as the sole line of `config/mission_control_token.txt`. Do this
BEFORE arming the task: a tokenless server serves a perfectly readable page
whose every button returns 503, which is correct fail-closed behaviour but reads
exactly like a bug.

- [ ] **Step 3: Smoke-test in the foreground first**

```bash
python mission_control.py
```

Expected: two log lines in `logs/mission_control-<today>.log`, one per bind
address. Leave it running for the next step; Ctrl-C after.

- [ ] **Step 4: Prove the cert validates with no `-k`**

From Legion, in a second shell:

```bash
curl --fail https://legion-rc:8895/api/loop-status
```

Expected: JSON, no certificate warning, no `-k`. If this fails on the
certificate, STOP - do not add `-k` and do not proceed. Re-check
`tools/regen_rc_cert.ps1` SAN coverage and `ops/tls/rc.pem`.

- [ ] **Step 5: Write the task installer**

Create `tools/install_mission_control_task.ps1`:

```powershell
# Registers RC-MissionControl. Independent of RC's supervisor by design:
# an RC restart for a game-overlay change must not touch the control plane.
# RestartCount/RestartInterval are load-bearing - choosing a scheduled task
# over an rc_supervisor entry gave up auto-restart, and ONLOGON fires once.
$python  = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python314\pythonw.exe'
$script  = 'C:\Riot Commander\mission_control.py'
$workdir = 'C:\Riot Commander'

$action    = New-ScheduledTaskAction -Execute $python -Argument "`"$script`"" -WorkingDirectory $workdir
$trigger   = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId 'Administrator' -RunLevel Highest
$settings  = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName 'RC-MissionControl' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Write-Host 'RC-MissionControl registered. Start it with: schtasks /Run /TN RC-MissionControl'
```

- [ ] **Step 6: Register and start the task**

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File "C:/Riot Commander/tools/install_mission_control_task.ps1"
schtasks /Run /TN RC-MissionControl
```

Note the known trap: `schtasks /End` then `/Run` can race and leave the process
dead with Last Result 0. If the port does not answer, check for a live pid
before concluding the task is broken.

- [ ] **Step 7: Run the live acceptance criteria**

Each of these is a separate observation. Record what you actually saw, not what
you expected.

```bash
curl --fail https://100.70.22.55:8895/api/loop-status
```
Expected: JSON. This is criterion 1 (reachable by IP, cert valid).

```bash
curl -X POST --fail https://legion-rc:8895/api/loop-control -H "Content-Type: application/json" -d "{\"action\":\"stop\"}"
```
Expected: 401. This is criterion 4a (no token is refused).

```bash
curl --fail --connect-timeout 5 https://192.168.8.230:8895/api/loop-status
```
Expected: connection refused or timeout. This is criterion 3 (bind scope holds).

Now the restart-independence proof (criterion 2). Record the Mission Control pid
first, then bounce RC:

```bash
echo restart > "C:/Riot Commander/restart_trigger.txt"
```

Wait about 10 seconds, confirm `ops/runtime/health.json` shows a NEW RC pid, and
confirm `:8895` still answers with the SAME Mission Control pid throughout.

Then the watchdog proof (criterion 6). Take the Mission Control pid and:

```bash
taskkill /F /PID <mission_control_pid>
```

Wait up to 90 seconds. Expected: the task restarts it and `:8895` answers again
on a NEW pid. Never use `Stop-Process` - it hangs the MCP pipe.

- [ ] **Step 8: Commit the installer**

```bash
git add tools/install_mission_control_task.ps1
git commit -m "ops(mc): RC-MissionControl task installer with restart policy"
```

---

### Task 9: Remove Mission Control from the RC dashboard

Only now, with the new surface proven live. After this, `/api/loop-status` and
`/api/loop-control` return 404 on `:8888`, which is the correct loud failure for
any caller still pointed at the old URLs.

**Files:**
- Modify: `web/js/panels/dev.js`, `web/js/main.js:843`, `web/index.html:1625-1637`, `web/css/panels/header.css:3017-3178`, `dashboard/_dispatch.py:147,210`
- Test: `tests/test_mission_control_server.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Write the failing residue guards**

Append to `tests/test_mission_control_server.py`:

```python
_MC_IDENTIFIERS = [
    "_loopControl", "_LOCK_STATES", "_loopAge", "_loopLockRow",
    "_MC_SHORTCUTS", "_mcSetTimer", "_mcMsg", "_mcFire", "_LANE_LABELS",
    "_mcSteerKey", "_mcRunId", "_mcFireLane", "_mcPaintLanes", "_MC_IRQ_ID",
    "_mcIrqForget", "_mcVictimLine", "_mcIrqPreview", "_mcIrqFire",
    "_mcPaintInterrupt", "_mcPaint", "renderLoopStatus",
    "loop-status-body", "api/loop-status", "api/loop-control",
    "arm_confirm",
]


def test_dashboard_carries_no_mission_control_residue():
    """Set-equality style so a PARTIAL deletion fails. A half-removed panel
    is worse than either end state: the card renders and does nothing."""
    targets = [
        ROOT / "web" / "js" / "panels" / "dev.js",
        ROOT / "web" / "js" / "main.js",
        ROOT / "web" / "index.html",
        ROOT / "web" / "css" / "panels" / "header.css",
    ]
    found = {}
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = [ident for ident in _MC_IDENTIFIERS if ident in text]
        if hits:
            found[path.name] = hits
    assert found == {}, f"Mission Control residue left behind: {found}"


def test_dashboard_no_longer_registers_the_loop_routes():
    from dashboard import _dispatch
    for matcher, _ in _dispatch.get_routes():
        assert not matcher("/api/loop-status")
    for matcher, _ in _dispatch.post_routes():
        assert not matcher("/api/loop-control")
```

Before running this, confirm the two dispatch accessor names. Grep them:

```bash
grep -n "^def get_routes\|^def post_routes\|^def _get_routes\|^def _post_routes" dashboard/_dispatch.py
```

Use the real names in the test.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_mission_control_server.py -k "residue or no_longer_registers" -v
```

Expected: both FAIL, listing the identifiers still present.

- [ ] **Step 3: Delete the dev.js block**

Delete `web/js/panels/dev.js` lines **341-1019** (the
`// -- Headless loop status (2026-06-07)` comment through the closing brace of
`renderLoopStatus` and its trailing blank line). Then delete lines **9-10**:

```javascript
// Mission Control S4: arm-then-confirm for the two queued shortcuts.
import { createArmController } from '../../mc/arm_confirm.js';
```

Delete bottom-up (block first, then the import) so the earlier line numbers stay
valid while you work.

- [ ] **Step 4: Remove the router call**

`web/js/main.js:843` calls `renderLoopStatus()`. Leaving it is a ReferenceError
that breaks the ENTIRE settings view - the same defect class S9 hit, in reverse.
The line reads:

```javascript
    if (viewId === "settings")    { _settingsRefresh(); _settingsLobbyWireOnce(); _syncAutoAcceptUI(); renderSpendGates(); renderLoopStatus(); _settingsFilterWireOnce(); }
```

Remove only the `renderLoopStatus();` call, leaving the other five intact. Also
remove `renderLoopStatus` from the `import` statement at the top of `main.js`
that pulls it in from `./panels/dev.js` - find it with:

```bash
grep -n "renderLoopStatus" web/js/main.js
```

- [ ] **Step 5: Delete the index.html card**

Delete `web/index.html` lines **1625-1637**: the blank line, the six-line
`<!-- Mission Control S4 ... -->` comment, and the `<div class="settings-card">`
block through its closing `</div>`. Keep line 1638's `</div>` - that closes the
settings view body.

- [ ] **Step 6: Delete the header.css block**

Delete `web/css/panels/header.css` lines **2956-3178**: the blank line at 2956,
the `/* Headless loop status card ... */` comment at 2957, and every rule
through the line before `.mode-pill` at 3179.

**Do not stop at 3018.** That is where the `/* Mission Control S4` comment sits
and it is the middle of the region, not its start. Deleting only 3017-3178
leaves roughly 60 lines of orphaned `.loop-*` rules that style nothing - and the
residue guard in Step 1 will fail on `loop-status-body`, correctly.

Verified while planning: no non-Mission-Control code uses any `loop-*` class, so
this deletion is safe in full. One loose end to fix in the same edit - the
comment at `web/css/panels/header.css:2836` describes `.set-action-btn` as
"Mirrors `.loop-btn` chrome". `.set-action-btn` duplicates those properties
rather than depending on them, so nothing breaks visually, but the comment would
point at a rule that no longer exists. Reword it to describe the chrome directly
instead of naming `.loop-btn`.

- [ ] **Step 7: De-register the routes**

In `dashboard/_dispatch.py`, delete the line at **:147**:

```python
                      + list(routes_loop_status.GET_ROUTES)
```

and the line at **:210**:

```python
                       + list(routes_loop_control.POST_ROUTES)
```

Then remove the now-unused `routes_loop_status` / `routes_loop_control` names
from the lazy import statements inside the two cache builder functions. Leave
the modules themselves in `dashboard/` - `mc/routes.py` imports them.

- [ ] **Step 8: Verify the dashboard JS still parses**

```bash
python -m pytest tests/test_web_js_esm_parse.py -v
```

Expected: PASS. This is the check that catches a mis-sliced deletion; a bare
`node --check` would not.

- [ ] **Step 9: Run the full suite from the repo root**

```bash
python -m pytest tests/ -q -n 8
```

Expected: PASS. Report the exact pass/fail counts from THIS run - never carry a
count forward from an earlier run or from another agent's report.

- [ ] **Step 9b: Lint and drift gates**

Acceptance criterion 8 is "full suite green, ruff clean, drift_guard 0" - the
suite is only one third of it, and the other two are the ones a fresh clone
would not catch for you.

```bash
python -m ruff check mc/ mission_control.py dashboard/_matchers.py dashboard/_dispatch.py tests/test_mission_control_server.py
python -m pytest tests/test_drift_guard.py -v
```

Expected: ruff reports `All checks passed`, drift_guard PASSES. New `mc/*.py`
files are auto-enrolled in the repo-wide `rglob("*.py")` hygiene sweeps
(`tests/test_skip_condition_hygiene.py`, `tests/test_dead_endpoint_cleanup_item186.py`)
by the full-suite run above, so a missing `# arch:` header surfaces there.

- [ ] **Step 10: Restart RC and confirm the routes are gone**

```bash
echo restart > "C:/Riot Commander/restart_trigger.txt"
```

Wait about 10 seconds, then:

```bash
curl -k -o /dev/null -w "%{http_code}\n" https://127.0.0.1:8888/api/loop-status
```

Expected: `404`. This is criterion 5.

Confirm `ops/runtime/health.json` shows a new pid with `alive=true` and
`last_reload_ok=true`, and load `https://legion-rc:8888/` to confirm the
Settings view still renders - that is what Step 4 protects.

- [ ] **Step 11: Run the 5-phase UI audit on the new page**

Run the UI-fixture audit ritual (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII /
HIERARCHY) against `https://legion-rc:8895/`. Every MUST-FIX is resolved in this
same task, not deferred.

Then click through arm-then-confirm in a real browser: arm a shortcut, confirm
it, and arm-then-disarm one. Binding lifetime is invisible to every test in this
plan and to mutation testing - only a live click found the two S9 defects.

- [ ] **Step 12: Commit**

```bash
git add web/ dashboard/_dispatch.py tests/
git commit -F <tmpfile>
```

Commit message (write to an ASCII-only temp file first):

```
refactor(dashboard): remove Mission Control, now served standalone on :8895

Completes S10. The control plane no longer shares a process, dispatch table,
JS bundle or page with the game dashboard. /api/loop-status and
/api/loop-control are 404 on :8888 by design - a loud failure for any caller
still pointed at the old URLs, and there are none in-repo.
```

---

## Post-Implementation

- [ ] Append the per-item entry to `docs/LEDGER.md` (newest-first). NEVER to
      `CLAUDE.md` - it is CI size-budgeted under 60KB.
- [ ] Update `ROADMAP.md:90`: move the S10 `[!]` row to `[x]` with the merge SHA.
- [ ] Update `docs/MISSION_CONTROL_PLAN.md` with an "S10 as shipped" section
      matching the S5-S9 precedent.
- [ ] Add `RC-MissionControl` to the scheduled-task list in
      `docs/OPERATIONS.md`.
- [ ] Update `docs/ARCHITECTURE.md` with the `mc/` package and the `:8895`
      surface.
- [ ] Run `python tools/perseus_sync.py` after the docs land, then
      `--verify` to confirm `embedded == active`.
- [ ] Record in memory: a SAN is host-scoped not port-scoped, so a new PORT on a
      covered host needs no cert regen.
