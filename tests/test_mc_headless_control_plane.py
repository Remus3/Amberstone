# arch: the :8895 control plane survives the web-UI retirement intact | section=tests | frozen=no
"""Regression pin for Option A: retire the VIEW half, keep the CONTROL half.

The Mission Control web UI (`web/mc/`) was retired on 2026-09-20. The decision
was explicitly NOT "delete Mission Control" - it was "keep the control plane
headless". That distinction is easy to erode by accident, because a later
cleanup pass looking at a process whose page is gone can reasonably conclude
the process is gone too. This file is what makes that conclusion fail loudly.

Four things are asserted, each a named cost of the removal:

  1. every CONTROL action is still reachable through the real route table;
  2. the bearer perimeter still refuses an unauthenticated POST BEFORE the
     route runs - "reachable" must not mean "open";
  3. the static surface is gone, and `/` is now a JSON 404 rather than a page;
  4. `/api/loop-monitor` is NOT an MC surface and was NOT touched. The removal
     analysis named it "the surface most likely to be mistaken for MC's", so
     it is pinned here rather than left to a reader's judgement.

The arm-then-confirm gate that came out of `web/mc/arm_confirm.js` has its own
file - tests/test_arm_confirm_server_gate.py. It is not re-asserted here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================== 1. control actions survive

def test_every_control_action_is_still_dispatchable():
    """The nine actions the removal promised to keep, named one by one."""
    from dashboard import routes_loop_control as ctl

    for action in ("stop", "resume", "set_directive", "clear_directive",
                   "fire_lane", "queue_intent", "steer",
                   "interrupt_preview", "interrupt"):
        assert action in ctl._VALID_ACTIONS, f"{action} lost in the UI removal"


def test_the_control_endpoint_is_still_registered_on_mc():
    from mc import routes

    post_paths = [m for m, _fn in routes.POST_ROUTES]
    assert any(m("/api/loop-control") for m in post_paths)


def test_the_status_endpoint_is_still_registered_on_mc():
    from mc import routes

    get_paths = [m for m, _fn in routes.GET_ROUTES]
    assert any(m("/api/loop-status") for m in get_paths)


def test_the_two_route_modules_are_still_imported_not_forked():
    """mc/routes.py must keep IMPORTING the dashboard modules.

    A copy would be a second class of byte-identical-by-contract file, which
    mc/routes.py:5-7 says the repo must never grow.
    """
    from dashboard import routes_loop_control, routes_loop_status
    from mc import routes

    assert routes.POST_ROUTES[-1] in list(routes_loop_control.POST_ROUTES)
    assert list(routes_loop_status.GET_ROUTES)[0] in routes.GET_ROUTES


# ============================================== 2. bearer perimeter survives

def test_an_unauthenticated_post_is_401_and_never_reaches_a_route(monkeypatch):
    """Reachable is not the same as open.

    Drives `Handler.do_POST` end to end rather than calling `auth.check`
    directly. The direct-call version of this test was green and proved
    nothing: moving the auth call to AFTER the route loop in mc/handler.py
    would have left it passing while every POST ran first and was refused
    afterwards. This version fails on exactly that mistake, because the route
    table is replaced with one that records being reached.
    """
    from mc import handler, routes

    monkeypatch.setenv("RC_MC_TOKEN", "a-real-token")
    reached = []
    monkeypatch.setattr(
        routes, "POST_ROUTES",
        [(lambda p: True, lambda h, b: reached.append(b))])

    class Fake:
        path = "/api/loop-control"
        headers = {}

        def __init__(self):
            self.sent = None
            self.rfile = None

        def _send(self, code, body, ctype, cache_control=None):
            self.sent = (code, body, ctype)

        _send_json = handler.Handler._send_json

    f = Fake()
    f.headers = {"Content-Length": "2"}
    handler.Handler.do_POST(f)
    code, raw, _ctype = f.sent
    assert code == 401
    assert json.loads(raw.decode("utf-8")) == {"ok": False, "error": "unauthorized"}
    assert reached == [], "the route ran before the bearer check"


def test_a_wrong_token_is_401_with_the_same_body_as_no_token(monkeypatch):
    """No oracle: a caller must not learn which of the two it hit."""
    from mc import auth

    monkeypatch.setenv("RC_MC_TOKEN", "a-real-token")
    _ok1, s1, b1 = auth.check(None)
    _ok2, s2, b2 = auth.check("Bearer wrong")
    assert (s1, b1) == (s2, b2)


def test_an_unconfigured_control_plane_still_fails_closed(monkeypatch, tmp_path):
    """503, never fail-open. mc/auth.py:8-11 - S9 added an action that kills."""
    from mc import auth

    monkeypatch.delenv("RC_MC_TOKEN", raising=False)
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "absent.txt")
    ok, status, _body = auth.check("Bearer anything")
    assert ok is False and status == 503


def test_the_token_file_path_is_unchanged_by_the_removal():
    """config/mission_control_token.txt is GITIGNORED.

    It is therefore invisible to `git rm`, which means a removal that only
    deleted tracked files would have left a live bearer secret on disk for a
    dead service. The service is NOT dead and the token is still required, so
    the correct handling was to leave the file exactly where it is - and this
    test is the record of that decision, not just of the path.
    """
    from mc import auth

    assert auth.TOKEN_FILE == ROOT / "config" / "mission_control_token.txt"


# ============================================== 3. the static surface is gone

def test_the_web_mc_tree_no_longer_exists():
    assert not (ROOT / "web" / "mc").exists()


def test_the_handler_serves_no_static_files():
    from mc import handler

    assert not hasattr(handler, "WEB_DIR")
    assert not hasattr(handler, "_CTYPES")
    assert not hasattr(handler.Handler, "_serve_static")


def test_an_unmatched_get_is_a_json_404_not_a_page():
    """`/` used to serve index.html. It must now be the route table's 404."""
    from mc import handler

    class Fake:
        path = "/"

        def __init__(self):
            self.sent = None

        def _send(self, code, body, ctype, cache_control=None):
            self.sent = (code, body, ctype)

        _send_json = handler.Handler._send_json

    f = Fake()
    handler.Handler.do_GET(f)
    code, body, ctype = f.sent
    assert code == 404
    assert ctype == "application/json"
    assert json.loads(body.decode("utf-8")) == {"ok": False, "error": "not found"}


# The shapes that make a mention a DEPENDENCY rather than a remark. A comment
# explaining why a file was removed is not a live reference and must not be
# flagged - that would only teach the next author to delete the explanation.
# What must never reappear is a load, an import or a path construction.
_LIVE_REFERENCE_SHAPES = (
    "import ", "from ", "require(", "href=", "src=", "fetch(",
    "open(", "read_bytes", "read_text", "Path(", "WEB_DIR", "rglob",
)

_DELETED_TOKENS = ("web/mc", "web\\mc", "mc.js", "mc.css", "arm_confirm.js",
                   "arm_confirm.test.mjs")


@pytest.mark.parametrize("token", _DELETED_TOKENS)
def test_no_live_module_loads_a_deleted_web_mc_file(token):
    """Prove-it-dead, kept as a test so the dependency cannot quietly return.

    Scope is the PRODUCTION tree only. Tests and docs may legitimately name a
    removed file while explaining why it is removed - this file does it in its
    own docstring - so the assertion is about REFERENCE SHAPE, not about the
    word appearing. An empty grep is a claim about a pattern, so the shapes
    above are enumerated explicitly rather than left to a single regex.
    """
    # Scope WIDENED after an adversarial pass pointed out the first version
    # could not see a reference from web/*.html, app/, tools/, scripts/, or any
    # .ps1 / .bat / .json - which is most of the tree that could actually load
    # a web asset. An empty grep is a claim about a pattern, and the pattern
    # was the weak part, not the tree.
    roots = [ROOT / "mc", ROOT / "dashboard", ROOT / "web", ROOT / "ops",
             ROOT / "app", ROOT / "tools", ROOT / "scripts", ROOT / "core"]
    suffixes = (".py", ".js", ".css", ".html", ".mjs", ".json", ".ps1",
                ".bat", ".cmd", ".ahk", ".sh")
    hits = []
    seen_any = False
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            seen_any = True
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if token in line and any(s in line for s in _LIVE_REFERENCE_SHAPES):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{i}")
    assert seen_any, "the scan walked ZERO files - an empty enumeration passes"
    assert not hits, f"{token} is still LOADED by live code: {hits}"


# ============================================== 4. loop-monitor is NOT MC's

def test_loop_monitor_is_registered_on_the_game_dashboard_not_on_mc():
    """The surface most likely to be deleted by mistake. Pinned both ways.

    The first version of this test guarded the dashboard half behind
    `hasattr(_dispatch, "build_get_routes")` - a function that does not exist,
    so the guard was always False and the assertion behind it was a tautology.
    An adversarial pass caught it. The real assembly point is
    `dashboard._dispatch._gather_get`, and it is called here for real, which is
    what makes this a claim about :8888 rather than about a name.
    """
    from dashboard import _dispatch, routes_loop_monitor
    from mc import routes as mc_routes

    # The registration itself, read from the module that owns it.
    own = [m for m, _fn in routes_loop_monitor.GET_ROUTES]
    assert any(m("/api/loop-monitor") for m in own)
    assert any(m("/loop-monitor") for m in own)

    # And it is genuinely spliced into the :8888 GET table.
    dash = _dispatch._gather_get()
    assert dash, "the dashboard GET table is empty - the probe is wrong"
    assert any(m("/api/loop-monitor") for m, _fn in dash)
    assert any(m("/loop-monitor") for m, _fn in dash)

    # And it is NOT on Mission Control, in either direction.
    assert not any(m("/api/loop-monitor") for m, _fn in mc_routes.GET_ROUTES)
    assert not any(m("/loop-monitor") for m, _fn in mc_routes.GET_ROUTES)
    # The converse: the loop CONTROL route is on MC and not on :8888.
    assert not any(m("/api/loop-control") for m, _fn in dash)


def test_the_loop_monitor_page_no_longer_fetches_a_route_this_port_lacks():
    """The pre-existing dangling fetch, fixed rather than inherited.

    The page used to `jget('/api/loop-status')` against :8888, which has not
    served that route since S10 (dashboard/_dispatch.py registers only
    routes_loop_monitor). It 404'd on every load and failed soft into
    "loop-status unavailable", so it looked like a missing feature rather than
    a bug. It is gone; this asserts it stays gone.
    """
    src = (ROOT / "dashboard" / "routes_loop_monitor.py").read_text(
        encoding="utf-8")
    assert "jget('/api/loop-status')" not in src
    assert 'jget("/api/loop-status")' not in src
    # The one endpoint this page legitimately fetches is still fetched.
    assert "jget('/api/loop-monitor')" in src
