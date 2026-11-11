"""q090: over HTTP a non-integer level / slots in a DS POST body answers 400.

The s159 L9 residue run (hand-off NEXT ACTION 5) POSTed the two follow-up
probes RM-1328 wrote, `{"champion":"Ahri","mode":"SR","level":Infinity}` to
/api/ds-preview and the same body with `"slots":"abc"` to /api/build-order.
Both answered 400 `bad_request_body`; the follow-up file expected 200.

Decision (s160): STALE EXPECTATION, not a contract bug. The 400 is the
shipped contract.

  * RM-243 (`0872a4992`, 2026-10-03, LEDGER 1512) made `dispatch_post`
    REFUSE a body that fails its route's request model, with 400
    `bad_request_body` and a `fields` list, and never dispatch it.
    `DsPreviewRequest.level`, `BuildOrderRequest.level` and
    `BuildOrderRequest.slots` are `int`, so pydantic refuses NaN, +-Infinity,
    1e400, "abc", "6.5", a list, an object, null and a fractional number.
    `tests/test_post_body_validator_rejects_rm243.py` pins the ds-preview
    `level` case on purpose, and docs/API.md lists the 400.
  * RM-1328 (`d9dd37ffe`, 2026-10-31, after RM-243) added
    `routes_state._payload_int` and tested it by calling the route
    functions DIRECTLY, past the gate. Its "should answer 200, not 500" live
    probe carried a handler-level result to the HTTP level. Live, those
    bodies were already 400 at the gate, before and after RM-1328.
  * Root cause of the wrong expectation: `dashboard/api_schema.py` still
    said the models were soft-warn and that `dispatch_post` calls the route
    whatever the result - false since RM-243 - and a trust-boundary test
    pinned the word "soft" in that docstring. Both are corrected with this
    file.

Alternatives rejected: loosen the three fields (`Any` or a pre-validator
that maps a bad value to the default) so the route's fall-to-default
answers 200 - that undoes a deliberate, tested, documented gate, and no
in-tree sender can send a non-integer (active_match.js sends `level | 0`,
champ_select.js a literal 6, build_order.js constants), so the 400 costs no
real caller anything and tells a bad one what is wrong.

What `_payload_int` still does over HTTP: it takes the default for what the
model ADMITS but is no level (a JSON boolean, 0) and clamps an in-range
integer; for routes with no request model (`/api/console-error` lineno /
colno) it is the only guard.

What runs here: the two s159 probes, byte for byte, against the real Handler
on an ephemeral loopback port (no live RC, no DS: the engine entry points
are spies), a positive control on the same socket, and the gate / route
split for every token RM-1328's test feeds the routes. ASCII only.
"""
from __future__ import annotations

import json
import socket
import threading
from http.server import ThreadingHTTPServer
from unittest import mock

import pytest

import core.http_host_gate as host_gate
from dashboard import _dispatch
from dashboard._handler import Handler

_LOCAL_HOST = b"Host: 127.0.0.1\r\n"
_TARGET = ('"target_armor": 50, "target_mr": 40, "target_max_hp": 2000, '
           '"target_bonus_hp": 0')

# The s159 probes as RM-1328's follow-up wrote them (raw JSON text: the bare
# Infinity token is not strict JSON, and json.loads accepts it).
_S159_PROBES = (
    (b"/api/ds-preview", "level",
     b'{"champion":"Ahri","mode":"SR","level":Infinity}'),
    (b"/api/build-order", "slots",
     b'{"champion":"Ahri","mode":"SR","slots":"abc"}'),
)

# RM-1328's bad-token set (tests/test_ds_route_level_parse_s144q58.py).
_RM1328_TOKENS = ("NaN", "Infinity", "-Infinity", "1e400", '"abc"', '"6.5"',
                  "[1]", '{"a": 1}', "true")
# The one token the request model admits (pydantic lax mode reads a JSON
# boolean as an int); the route then takes its default (RM-1328).
_ADMITTED = frozenset({"true"})

_ROUTES = (
    ("/api/ds-preview", "level", 6),
    ("/api/build-order", "level", 11),
    ("/api/build-order", "slots", 6),
)


def _ok_preview() -> dict:
    return {"ok": True, "scorer": "dps", "archetype": "carry",
            "ranked": [], "fell_back": False}


class _FakePlan:
    def to_dict(self) -> dict:
        return {"order": []}


@pytest.fixture
def engine():
    """Spies on both DS entry points, so no route can reach a real engine."""
    with mock.patch("core.daemon_slayer_client.rank_for_primary_archetype",
                    return_value=_ok_preview()) as rank, \
            mock.patch("core.build_order.plan_build_order",
                       return_value=_FakePlan()) as plan:
        yield {"/api/ds-preview": rank, "/api/build-order": plan}


@pytest.fixture
def served(monkeypatch):
    """The real dashboard Handler on a loopback socket, no dash token set."""
    monkeypatch.setattr(host_gate, "_allowed_names_cache",
                        host_gate._LOOPBACK_NAMES)
    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def _post(port: int, path: bytes, body: bytes) -> tuple[int, str, bytes]:
    raw = (b"POST " + path + b" HTTP/1.1\r\n" + _LOCAL_HOST
           + b"Content-Type: application/json\r\nConnection: close\r\n"
           + b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(raw)
        sock.settimeout(10)
        out = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            out += chunk
    head, _, payload = out.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    ctype = next((ln.split(":", 1)[1].strip() for ln in lines[1:]
                  if ln.lower().startswith("content-type:")), "")
    return int(lines[0].split()[1]), ctype, payload


@pytest.mark.parametrize("path,field,body", _S159_PROBES,
                         ids=["ds-preview-level-Infinity",
                              "build-order-slots-abc"])
def test_s159_probe_is_400_bad_request_body_over_the_real_handler(
        served, engine, path, field, body):
    status, ctype, payload = _post(served, path, body)
    assert status == 400, payload[:300]
    assert ctype == "application/json"
    out = json.loads(payload)
    assert out["error"] == "bad_request_body"
    assert [f["field"] for f in out["fields"]] == [field], out
    # The route never ran, so no engine call was made.
    assert engine[path.decode()].call_count == 0
    # RM-134: the refusal never echoes the offending input.
    assert b"Infinity" not in payload and b"abc" not in payload


@pytest.mark.parametrize("path,field,good,want", [
    (b"/api/ds-preview", "level", "9", 9),
    (b"/api/build-order", "slots", "4", 4),
], ids=["ds-preview-level-9", "build-order-slots-4"])
def test_a_valid_integer_still_reaches_the_route_over_the_real_handler(
        served, engine, path, field, good, want):
    # Positive control on the same socket: the gate must not refuse a legal
    # body, or the 400 above would prove nothing about the field.
    body = ('{"champion":"Ahri","mode":"SR","archetype":"carry",'
            f'"{field}":{good},{_TARGET}}}').encode()
    status, ctype, payload = _post(served, path, body)
    assert status == 200, payload[:300]
    assert ctype == "application/json"
    assert json.loads(payload)["ok"] is True
    spy = engine[path.decode()]
    assert spy.call_count == 1
    assert spy.call_args.kwargs[field] == want


class _H:
    def __init__(self, path: str) -> None:
        self.path = path
        self.headers: dict = {}
        self.sent: tuple | None = None

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.sent = (status, body, content_type)


@pytest.mark.parametrize("path,field,default", _ROUTES,
                         ids=[f"{p}-{f}" for p, f, _ in _ROUTES])
def test_gate_and_route_split_for_every_rm1328_token(
        engine, path, field, default):
    """The real dispatch_post and the real route table, per RM-1328 token.

    Every token but a JSON boolean is refused at the gate (400, route not
    run); a boolean passes the model and the route takes its default. A
    change on either side - a looser model, or a gate that stops refusing -
    turns this red, which is the point: it is the live contract.
    """
    spy = engine[path]
    for tok in _RM1328_TOKENS:
        spy.reset_mock()
        body = json.loads('{"champion": "Ahri", "mode": "SR", '
                          f'"archetype": "carry", "{field}": {tok}, {_TARGET}}}')
        h = _H(path)
        assert _dispatch.dispatch_post(h, body) is True
        status, wire, _ = h.sent
        if tok in _ADMITTED:
            assert status == 200, (tok, wire[:200])
            assert spy.call_count == 1, tok
            assert spy.call_args.kwargs[field] == default, tok
        else:
            assert status == 400, (tok, wire[:200])
            out = json.loads(wire)
            assert out["error"] == "bad_request_body", tok
            assert [f["field"] for f in out["fields"]] == [field], (tok, out)
            assert spy.call_count == 0, tok
