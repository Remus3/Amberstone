# arch: deep-audit P2-W1-dash-A regression tests | section=tests | frozen=no
"""Deep-audit cycle 8, slice A (dashboard spine/infra/bridge) regression tests.

Single-file slice test per the cycle-8 charter. Covers the behavior fixes this
slice landed:

  - routes_static._serve_web_asset path-traversal hardening: a backslash-based
    ".." segment bypassed the "/"-split ".." filter and the str.startswith()
    web-root check (which is satisfied by sibling paths like web_dashboard.py),
    letting a non-browser client read source files outside web/. The fix
    normalizes backslashes in the ".." filter AND confirms containment with
    Path.relative_to instead of a string-prefix startswith().

All file/data shapes used here were confirmed live before authoring:
  - dashboard.routes_static._serve_web_asset(h) calls h._send(code, body, ctype)
    (routes_static.py:53-74).
  - web/css/dashboard.css exists and serves 200 (probed live, 2352 bytes).
  - the dispatcher routes /css/, /js/, /data/, /icons/positions|lobby/ here
    (routes_static.GET_ROUTES).
"""
from __future__ import annotations

from dashboard import routes_static


class StubHandler:
    """Minimal BaseHTTPRequestHandler stand-in capturing _send(...)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.sent: tuple | None = None

    def _send(self, code: int, body: bytes, ctype: str, *a, **k) -> None:
        self.sent = (code, body, ctype)


def _get(path: str) -> tuple[int, bytes, str]:
    h = StubHandler(path)
    routes_static._serve_web_asset(h)
    assert h.sent is not None, "handler never called _send"
    return h.sent


# --------------------------------------------------------------------------- traversal
def test_backslash_traversal_does_not_leak_source():
    """/css/..\\..\\web_dashboard.py must NOT serve the sibling source file.

    Regression: the backslash escaped the "/"-split ".." filter and the
    resolved path str-prefix-matched the web root, returning 200 with the
    web_dashboard.py source body.
    """
    code, body, _ctype = _get(r"/css/..\..\web_dashboard.py")
    assert code != 200, (
        "path traversal leaked a file outside web/ "
        f"(got {code}, {len(body)} bytes)"
    )
    assert code in (400, 404)
    # And the body must not contain the source file's contents.
    assert b"web_dashboard" not in body or code in (400, 404)


def test_backslash_traversal_into_data_prefix_blocked():
    """The /data/ prefix also routes to _serve_web_asset - same guard."""
    code, _body, _ctype = _get(r"/data/..\..\web_dashboard.py")
    assert code != 200
    assert code in (400, 404)


def test_forward_slash_dotdot_still_blocked():
    """The original "/"-split ".." filter must keep rejecting forward-slash."""
    code, _body, _ctype = _get("/css/../web_dashboard.py")
    assert code == 400


def test_legit_asset_still_served():
    """The hardening must not break normal static serving."""
    code, body, ctype = _get("/css/dashboard.css")
    assert code == 200
    assert len(body) > 0
    assert "text/css" in ctype


def test_nullbyte_rejected():
    code, _body, _ctype = _get("/css/dashboard\x00.css")
    assert code == 400
