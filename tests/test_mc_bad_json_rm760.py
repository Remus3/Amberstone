# arch: RM-760b - Mission Control answers 400, never 500, on a hostile JSON body | section=tests | frozen=no
"""RM-760b: a malformed or over-deep POST body is the CALLER's fault.

`mc/handler.py` only caught `json.JSONDecodeError`. Two bodies a client can
send defeat that catch, because the stdlib raises something else for them:

  * deep nesting (`[` x 100000) - `RecursionError`;
  * a 5000-digit integer - `ValueError` from the int max-str-digits limit.

Both fell through to the catch-all and came back as a 500 "internal error",
logged at WARNING as a server fault. The fix wraps only the body parse, so a
route handler that raises is still a 500 - the control below pins that the
catch was not widened over the route table.

The handler is driven end to end through `Handler.do_POST` with a fake
request object (the pattern in tests/test_mc_headless_control_plane.py), with
a real bearer token so the body parse is actually reached.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TOKEN = "rm760b-test-token"


def _post(monkeypatch, body: bytes, route=None):
    """Drive do_POST with `body`; return (status, parsed json, reached list)."""
    from mc import handler, routes

    monkeypatch.setenv("RC_MC_TOKEN", _TOKEN)
    reached = []

    def _default_route(h, payload):
        reached.append(payload)
        h._send_json(200, {"ok": True})

    monkeypatch.setattr(
        routes, "POST_ROUTES",
        [(lambda p: True, route or _default_route)])

    class Fake:
        path = "/api/loop-control"

        def __init__(self):
            self.sent = None
            self.headers = {
                "Authorization": "Bearer " + _TOKEN,
                "Content-Length": str(len(body)),
            }
            self.rfile = io.BytesIO(body)

        def _send(self, code, raw, ctype, cache_control=None):
            self.sent = (code, raw, ctype)

        _send_json = handler.Handler._send_json

    f = Fake()
    handler.Handler.do_POST(f)
    code, raw, _ctype = f.sent
    return code, json.loads(raw.decode("utf-8")), reached


@pytest.mark.parametrize("body", [
    pytest.param(b"[" * 100000, id="deep-nesting"),
    pytest.param(b"1" * 5000, id="5000-digit-int"),
    pytest.param(b'{"a": ' + b"[" * 100000, id="deep-nesting-in-object"),
    pytest.param(b"{x", id="malformed"),
])
def test_hostile_body_is_400_invalid_json_and_no_route_runs(monkeypatch, body):
    code, payload, reached = _post(monkeypatch, body)
    assert code == 400
    assert payload == {"ok": False, "error": "invalid json"}
    assert reached == [], "a route ran on an unparseable body"


def test_a_valid_body_still_reaches_the_route(monkeypatch):
    code, payload, reached = _post(monkeypatch, b'{"action": "stop"}')
    assert code == 200 and payload == {"ok": True}
    assert reached == [{"action": "stop"}]


def test_a_route_raising_valueerror_is_still_a_500(monkeypatch):
    """Control: the catch covers the PARSE only, never the route table."""
    def _boom(h, payload):
        raise ValueError("route bug, not a client error")

    code, payload, _reached = _post(monkeypatch, b'{"action": "stop"}', _boom)
    assert code == 500
    assert payload == {"ok": False, "error": "internal error"}


def test_a_route_raising_recursionerror_is_still_a_500(monkeypatch):
    def _boom(h, payload):
        raise RecursionError("route bug")

    code, payload, _reached = _post(monkeypatch, b'{"action": "stop"}', _boom)
    assert code == 500
    assert payload == {"ok": False, "error": "internal error"}
