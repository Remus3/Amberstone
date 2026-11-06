"""Guard: docs/API.md states the :8888 refusals and the control-endpoint gate.

RM-1287. Measured against the real Handler on an ephemeral port, at lane/ds
d1ad1efa9:

  * "Error shapes" said "All error responses: {"error": "<message>"}". A no-route
    answer is 404 text/plain `not found`, and a PUT is the stdlib's 501 in HTML.
  * "Authentication" said "no auth (local HTTPS, Legion-local only)". The code
    binds `::` unless RC_DASH_BIND is set, and control POSTs are gated: with
    RC_DASH_TOKEN set a loopback caller gets 401 without X-RC-Token, and with
    none set the peer decides (403 control_peer_refused).

What runs here: the refusal table against the source both ways (ast), each table
row against the real handler on a real socket, the control list against the
source both ways, the clauses in _AUTH_CLAUSES / _ERROR_CLAUSES as verbatim text
pins, and tests measuring many of those clauses. A text pin with no measuring test
says only that the doc still states the clause.

Limits, stated on purpose: this is not a whole-text pin. Most When-cell wording,
the file citations outside a pinned clause, the advice and the "usually" sentences
can change without failing here, and a new false qualifier written around a pinned
clause is not stopped. Every request here is refused before a route runs, names a
path no route matches, or goes to a stub upstream or a closed port, so no route's
side effect can fire and the live supervisor is never reached. ASCII only.
"""
from __future__ import annotations

import ast
import json
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import core.http_host_gate as host_gate
import dashboard._handler as handler_mod
from dashboard import routes_recordings
import dashboard.server as server_mod
from dashboard._errors import GENERIC_ERROR, send_error
from dashboard._handler import Handler, is_control_endpoint

_REPO_ROOT = Path(__file__).resolve().parent.parent
_API_DOC = _REPO_ROOT / "docs" / "API.md"
_HANDLER = _REPO_ROOT / "dashboard" / "_handler.py"
_DISPATCH = _REPO_ROOT / "dashboard" / "_dispatch.py"
_SERVER = _REPO_ROOT / "dashboard" / "server.py"
_HOST_GATE = _REPO_ROOT / "core" / "http_host_gate.py"
_SERVICES = _REPO_ROOT / "ops" / "launcher" / "services.json"

_NO_ROUTE = b"/api/__s144d66_no_such_route__"
_ROW = re.compile(r"^\| (\d{3}) \| `([^`]+)` \|", re.MULTILINE)
_ANY_ROW = re.compile(r"^\s*\|?\s*\**\d{3}\**\s*\|", re.MULTILINE)
_LOCAL_HOST = b"Host: 127.0.0.1\r\n"

# Stated clauses, pinned verbatim: an earlier draft of this guard stayed green
# when a verifier flipped values inside clauses like these.
_AUTH_CLAUSES = (
    "`dashboard/server.py` binds `::` unless `RC_DASH_BIND` names another address",
    "The `dev` launcher profile leaves it unset, so `:8888` listens on every address "
    "of this machine, the LAN and the tailnet included",
    "the `packaged` profile sets `127.0.0.1`",
    "and every POST under `/api/decisions/`",
    "Each of those is gated one of two ways",
    "With `RC_DASH_TOKEN` set, every peer",
    "The control list (`is_control_endpoint`, `dashboard/_handler.py`)",
    "With none set, the peer decides (`control_peer_allowed`, `dashboard/server.py`)",
    "the server's own gates ask no credential of a GET or of a POST outside the "
    "control list",
    "One route module adds its own check: `dashboard/routes_recordings.py` asks "
    "for the same token when `RC_DASH_TOKEN` is set",
    "every peer, loopback included, must send it as `X-RC-Token`, or the answer "
    "is 401",
    "Loopback, this machine's own address, the tailnet and any CIDR in "
    "`RC_DASH_CONTROL_NETS` pass; anything else, a LAN host included, gets 403",
    "A local reverse proxy or tunnel connects from loopback, so everyone it "
    "forwards passes",
)
_ERROR_CLAUSES = (
    "The first three rows run on every method, before any route",
    "The 404 answers a POST that no route matches, and a GET that neither a route "
    "nor a proxy path matches",
    "The others are POST only",
    "`_same_origin_ok`",
    "Nothing answering there is 502 JSON `supervisor_unreachable`",
    "an upstream error keeps its status with a fixed JSON `error` line, never the "
    "upstream body",
    "`/api/minimap-crop` answers 204 in both cases",
    "All are JSON with the token under `error`, except the 404, which is "
    "`text/plain`; a refused HEAD gets the headers alone",
    "with an HTML body, not JSON (a HEAD gets the headers alone)",
    "501 for a method with no handler",
    "only GET and POST are served",
    "414 or 431 for a request line or header line over its 64 KiB limit",
    "431 for 100 or more header lines",
    "A GET under `SUPERVISOR_PROXY_PATHS` (`dashboard/_handler.py`) that no route "
    "claims goes to the `:8890` supervisor",
    "and reaches none of the above",
    "with the line `internal error - see logs` unless the route passes its own",
    "400 or 505 for a request line or HTTP version it cannot parse, which can "
    "arrive as bare HTML with no status line",
    "An HTTP/0.9 GET is closed with no reply",
    "or an IPv6 zone id; a plain IP literal passes",
    "With the TLS pair (`ops/tls/rc.pem`, `ops/tls/rc-key.pem`) a plain-HTTP "
    "connection to `:8888` gets a 301 to HTTPS",
    "without the pair the server speaks plain HTTP and all of it applies",
    "A failure sent through `send_error` (`dashboard/_errors.py`) is status 500 "
    "by default",
    "the exception itself is never in the body",
    "An exception nothing catches (one that leaves the route and its dispatcher) is "
    "answered by the handler itself, GET or POST: the same 500 with the same line, "
    "and the connection is closed",
    "If the route had already begun its reply, nothing more is written and the "
    "connection closes",
)


def _doc_section(heading: str) -> str:
    text = _API_DOC.read_text(encoding="utf-8")
    start = text.find(f"\n{heading}\n")
    assert start != -1, f"docs/API.md has no {heading!r} section"
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


def _flat(heading: str) -> str:
    """A section with its line wrapping removed, for clause checks."""
    return " ".join(_doc_section(heading).split())


def _doc_rows() -> set[tuple[int, str]]:
    section = _doc_section("## Error shapes")
    rows = _ROW.findall(section)
    assert rows, "the Error shapes section has no refusal table"
    assert len(rows) == len(set(rows)), f"a refusal row is repeated: {rows}"
    assert len(rows) == len(_ANY_ROW.findall(section)), (
        "a status row does not have the `token` shape, so it escapes the checks")
    return {(int(status), token) for status, token in rows}


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path.name} has no function {name}")


def _constant(path: Path, name: str) -> object:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call):     # frozenset({...})
                value = value.args[0]
            return ast.literal_eval(value)
    raise AssertionError(f"{path.name} has no module constant {name}")


def _do_post_refusals() -> set[tuple[int, str]]:
    """Every (status, token) do_POST sends: a JSON error or the bare 404 text."""
    found = set()
    for node in ast.walk(_function(_HANDLER, "do_POST")):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_send"):
            continue
        status = ast.literal_eval(node.args[0])
        body = ast.literal_eval(node.args[1]).decode("ascii")
        found.add((status, json.loads(body)["error"]
                   if body.startswith("{") else body))
    return found


def _head_refusals() -> set[tuple[int, str]]:
    """Every (status, token) the host gate's _head_refusal returns."""
    found = set()
    for node in ast.walk(_function(_HOST_GATE, "_head_refusal")):
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
            elts = node.value.elts
            found.add((ast.literal_eval(elts[2]), ast.literal_eval(elts[4])))
    return found


def _schema_refusals() -> set[tuple[int, str]]:
    """The (status, token) dispatch_post sends for a schema failure."""
    found = set()
    for node in ast.walk(_function(_DISPATCH, "dispatch_post")):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_send"):
            inner = next(n for n in ast.walk(node.args[1]) if isinstance(n, ast.Dict))
            pairs = dict(zip(inner.keys, inner.values, strict=True))
            token = next(ast.literal_eval(v) for k, v in pairs.items()
                         if ast.literal_eval(k) == "error")
            found.add((ast.literal_eval(node.args[0]), token))
    return found


@pytest.fixture
def served(monkeypatch):
    """The real dashboard Handler on a real socket, with no dash token set.

    The Host allowlist is injected (core/http_host_gate.py: tests never read the
    live per-host file), and monkeypatch puts the process-wide cache back.
    """
    monkeypatch.setattr(host_gate, "_allowed_names_cache", host_gate._LOOPBACK_NAMES)
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


def _reply(port: int, raw: bytes, *, half_close: bool = False) -> bytes:
    """Send a hand-built request; return every byte the server sent back."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(raw)
        if half_close:
            sock.shutdown(socket.SHUT_WR)
        sock.settimeout(10)
        out = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                return out
            out += chunk


def _exchange(port: int, raw: bytes) -> tuple[int, str, bytes]:
    """Send a hand-built request; return (status, content type, body)."""
    head, _, body = _reply(port, raw).partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    ctype = next((ln.split(":", 1)[1].strip() for ln in lines[1:]
                  if ln.lower().startswith("content-type:")), "")
    return int(lines[0].split()[1]), ctype, body


def _post(path: bytes = _NO_ROUTE, body: bytes = b"{}", extra: bytes = b"",
          length: object = None) -> bytes:
    declared = len(body) if length is None else length
    return (b"POST " + path + b" HTTP/1.1\r\n" + _LOCAL_HOST + extra
            + b"Content-Length: " + str(declared).encode() + b"\r\n\r\n" + body)


# Row -> the request that earns it. Keyed the same way as the doc table, so the
# coverage test below fails on a row added to either side with no probe.
_PROBES = {
    (400, "bad_header_block"):
        b"GET /api/x HTTP/1.1\r\n" + _LOCAL_HOST + b"no colon here\r\nX-B: 1\r\n\r\n",
    (400, "bad_request_target"):
        b"GET http://127.0.0.1/ HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n",
    (421, "misdirected_host"):
        b"GET /api/state HTTP/1.1\r\nHost: not-this-box.example\r\n\r\n",
    (403, "cross_origin"): _post(extra=b"Origin: https://not-this-box.example\r\n"),
    (411, "length_required"):
        b"POST " + _NO_ROUTE + b" HTTP/1.1\r\n" + _LOCAL_HOST
        + b"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
    (400, "bad_body"): _post(body=b"[1,2]"),
    (413, "payload_too_large"): _post(body=b"", length=2 << 20),
    (408, "body_read_timeout"): _post(body=b"x", length=50),
    (401, "unauthorized"): _post(path=b"/api/command"),
    (403, "control_peer_refused"): _post(path=b"/api/command"),
    (400, "bad_request_body"): _post(path=b"/api/ds-preview", body=b'{"champion":5}'),
    (404, "not found"): _post(),
}


def test_the_table_equals_what_the_source_sends_both_ways():
    source = _do_post_refusals() | _head_refusals() | _schema_refusals()
    assert source, "the source walk found no refusal at all"
    assert _doc_rows() == source


def test_the_source_walk_reaches_all_three_gate_groups():
    """An empty group would make the set equality above quietly smaller."""
    assert (421, "misdirected_host") in _head_refusals()
    assert (403, "cross_origin") in _do_post_refusals()
    assert (404, "not found") in _do_post_refusals()
    assert _schema_refusals() == {(400, "bad_request_body")}


def test_every_row_has_a_probe():
    assert set(_PROBES) == _doc_rows()


@pytest.mark.parametrize("row", sorted(_PROBES), ids=lambda r: f"{r[0]}-{r[1]}")
def test_each_row_is_what_the_real_handler_answers(row, served, monkeypatch):
    status, token = row
    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    if row == (401, "unauthorized"):
        monkeypatch.setenv("RC_DASH_TOKEN", "synthetic-dash-token")
    if row == (403, "control_peer_refused"):
        monkeypatch.setattr(handler_mod, "control_peer_allowed",
                            lambda *_a, **_k: False)
    if row == (408, "body_read_timeout"):
        monkeypatch.setattr(handler_mod, "_BODY_READ_TIMEOUT_S", 0.2)

    got_status, ctype, body = _exchange(served, _PROBES[row])

    assert got_status == status
    if row == (404, "not found"):
        assert (ctype, body) == ("text/plain", b"not found")
    else:
        assert ctype == "application/json"
        assert json.loads(body)["error"] == token


def test_the_schema_refusal_carries_the_fields_the_doc_says(served):
    _, _, body = _exchange(served, _PROBES[(400, "bad_request_body")])
    assert "fields" in json.loads(body)
    assert "`fields`" in _doc_section("## Error shapes")


@pytest.mark.parametrize("method", [b"PUT", b"DELETE", b"OPTIONS", b"HEAD"])
def test_a_method_with_no_handler_is_the_stdlib_501_the_doc_names(method, served):
    status, ctype, _ = _exchange(
        served, method + b" /api/state HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n")
    assert status == 501
    assert ctype.startswith("text/html")
    section = _doc_section("## Error shapes")
    assert "501" in section
    assert f"`{method.decode()}`" in section


@pytest.mark.parametrize(
    ("raw", "status"),
    [(b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n", 414),
     (b"GET /api/x HTTP/1.1\r\n" + _LOCAL_HOST + b"X-A: " + b"a" * 70000 + b"\r\n\r\n",
      431)],
    ids=["line-414", "header-431"])
def test_an_overlong_line_is_the_stdlib_html_answer_the_doc_names(raw, status, served):
    got_status, ctype, _ = _exchange(served, raw)
    assert got_status == status
    assert ctype.startswith("text/html")
    assert "414 or 431" in _doc_section("## Error shapes")


def test_the_cap_and_deadline_in_the_table_are_the_source_constants():
    table = _doc_section("## Error shapes")
    assert handler_mod._MAX_POST_BYTES == 1 << 20
    assert "over 1 MiB" in table
    assert handler_mod._BODY_READ_TIMEOUT_S == 10.0
    assert "within 10 s" in table


def test_the_stale_blanket_claims_are_gone():
    errors = _doc_section("## Error shapes").lower()
    auth = _doc_section("## Authentication").lower()
    assert "all error responses" not in errors
    assert "legion-local only" not in auth
    assert "no auth" not in auth


@pytest.mark.parametrize("clause", _AUTH_CLAUSES)
def test_an_authentication_clause_is_still_stated(clause):
    assert clause in _flat("## Authentication")


@pytest.mark.parametrize("clause", _ERROR_CLAUSES)
def test_an_error_shape_clause_is_still_stated(clause):
    assert clause in _flat("## Error shapes")


def test_a_get_with_no_route_is_the_same_404(served):
    raw = b"GET " + _NO_ROUTE + b" HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n"
    assert _exchange(served, raw) == (404, "text/plain", b"not found")


def test_a_head_gate_runs_on_a_method_with_no_handler(served):
    raw = b"PUT /api/state HTTP/1.1\r\nHost: not-this-box.example\r\n\r\n"
    assert _exchange(served, raw)[0] == 421


def test_a_refused_head_gets_the_headers_alone(served):
    raw = b"HEAD /api/state HTTP/1.1\r\nHost: not-this-box.example\r\n\r\n"
    assert _exchange(served, raw) == (421, "application/json", b"")


def test_the_64_kib_limit_is_the_boundary_not_just_a_number_over_it(served):
    fits = b"GET /" + b"a" * 65000 + b" HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n"
    assert _exchange(served, fits)[0] == 404


@pytest.mark.parametrize(("lines", "status"), [(99, 404), (100, 431)],
                         ids=["99-lines-fit", "100-lines-refused"])
def test_100_header_lines_is_the_431_boundary(lines, status, served):
    """Host counts as one of the lines."""
    headers = b"".join(b"X-%d: 1\r\n" % i for i in range(lines - 1))
    raw = b"GET " + _NO_ROUTE + b" HTTP/1.1\r\n" + _LOCAL_HOST + headers + b"\r\n"
    assert _exchange(served, raw)[0] == status


def test_the_stdlib_html_reply_has_a_body_except_for_head(served):
    def _answer(method: bytes) -> tuple[int, str, bytes]:
        return _exchange(
            served, method + b" /api/state HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n")

    status, ctype, body = _answer(b"HEAD")
    assert (status, ctype.startswith("text/html"), body) == (501, True, b"")
    status, ctype, body = _answer(b"PUT")
    assert (status, ctype.startswith("text/html")) == (501, True)
    assert b"<html" in body


def test_the_proxy_target_is_the_port_the_doc_names():
    assert handler_mod.SUPERVISOR_ORIGIN.endswith(":8890")


def test_the_symbols_the_clauses_cite_still_exist():
    assert callable(handler_mod._same_origin_ok)
    assert callable(handler_mod.is_control_endpoint)
    assert callable(server_mod.control_peer_allowed)
    assert handler_mod.SUPERVISOR_PROXY_PATHS


@pytest.mark.parametrize(
    ("request_line", "code"),
    [(b"GET /a b c HTTP/1.1", b"400"),
     (b"GET /x HTTP/abc", b"400"),
     (b"GET /x HTTP/2.0", b"505")],
    ids=["bad-line", "bad-version", "unsupported-version"])
def test_an_unparsable_request_line_is_a_stdlib_html_answer(request_line, code, served):
    reply = _reply(served, request_line + b"\r\n" + _LOCAL_HOST + b"\r\n")
    assert b"Error code: " + code in reply
    assert b"<html" in reply


def test_an_http_09_get_is_closed_with_no_reply(served):
    """The write side closes because a 3.12 server (CI) still reads a head after
    an HTTP/0.9 line; see tests/test_host_allowlist_rm759.py."""
    assert _reply(served, b"GET /api/state\r\n", half_close=True) == b""


def test_an_http_09_post_is_the_stdlib_400_not_a_silent_close(served):
    reply = _reply(served, b"POST /api/state\r\n", half_close=True)
    assert b"Error code: 400" in reply


@pytest.mark.parametrize(
    ("host", "status"),
    [(b"localhost", 404), (b"203.0.113.9", 404), (b"[2001:db8::1]", 404),
     (b"[fe80::1%25x]", 421), (b"not-this-box.example", 421)],
    ids=["allowed-name", "v4-literal", "v6-literal", "zone-id", "foreign-name"])
def test_the_host_gate_row_is_what_the_gate_decides(host, status, served):
    """The allowed name is the control: a gate refusing every name fails here."""
    raw = b"GET " + _NO_ROUTE + b" HTTP/1.1\r\nHost: " + host + b"\r\n\r\n"
    assert _exchange(served, raw)[0] == status


@pytest.mark.parametrize(
    "raw",
    [_post(length=-1, body=b""),
     b"POST " + _NO_ROUTE + b" HTTP/1.1\r\n" + _LOCAL_HOST + b"Content-Length: abc\r\n\r\n",
     _post(body=b"{not json"),
     _post(body=b"[1,2]")],
    ids=["negative-length", "non-integer-length", "not-json", "not-an-object"])
def test_every_bad_body_trigger_the_row_names(raw, served):
    status, _, body = _exchange(served, raw)
    assert (status, json.loads(body)["error"]) == (400, "bad_body")


def test_a_foreign_referer_alone_is_refused_too(served):
    raw = _post(extra=b"Referer: https://not-this-box.example/page\r\n")
    status, _, body = _exchange(served, raw)
    assert (status, json.loads(body)["error"]) == (403, "cross_origin")


def test_options_star_passes_the_target_gate_and_reaches_the_stdlib(served):
    raw = b"OPTIONS * HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n"
    assert _exchange(served, raw)[0] == 501


def test_the_plain_http_301_is_still_in_the_source():
    assert b"HTTP/1.1 301 Moved" in _SERVER.read_bytes()
    assert b"https://{host}:{PORT}" in _SERVER.read_bytes()


def test_without_the_tls_pair_the_listener_speaks_plain_http(tmp_path):
    srv, scheme = server_mod._build_server(tmp_path, Handler, host="127.0.0.1", port=0)
    try:
        assert scheme == "http"
    finally:
        srv.server_close()


def test_the_bind_default_and_the_profiles_are_what_the_doc_says():
    assert server_mod.bind_host({}) == "::"
    assert server_mod.bind_host({"RC_DASH_BIND": "127.0.0.1"}) == "127.0.0.1"
    profiles = json.loads(_SERVICES.read_text(encoding="utf-8"))["profiles"]
    assert profiles["dev"]["env"]["RC_DASH_BIND"] is None
    assert profiles["packaged"]["env"]["RC_DASH_BIND"] == "127.0.0.1"


@pytest.fixture
def closed_supervisor(monkeypatch):
    """Point the proxy at a port nothing listens on, never the live :8890."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(handler_mod, "SUPERVISOR_ORIGIN", f"http://127.0.0.1:{port}")


@pytest.fixture
def failing_supervisor(monkeypatch):
    """A stub upstream whose 404 body must not come back through :8888."""
    class _Upstream(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"synthetic-upstream-body")

        def log_message(self, *_a):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    upstream.daemon_threads = True
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(handler_mod, "SUPERVISOR_ORIGIN",
                        f"http://127.0.0.1:{upstream.server_address[1]}")
    try:
        yield
    finally:
        upstream.shutdown()
        upstream.server_close()
        thread.join(timeout=5)


def _proxied_get(path: bytes) -> bytes:
    return b"GET " + path + b" HTTP/1.1\r\n" + _LOCAL_HOST + b"\r\n"


def test_a_proxied_get_with_nothing_answering_is_the_502(served, closed_supervisor):
    assert "/api/queue" in handler_mod.SUPERVISOR_PROXY_PATHS
    status, ctype, body = _exchange(served, _proxied_get(b"/api/queue"))
    assert (status, ctype) == (502, "application/json")
    assert json.loads(body)["error"] == "supervisor_unreachable"


def test_a_proxied_upstream_error_keeps_status_and_drops_the_body(served, failing_supervisor):
    status, ctype, body = _exchange(served, _proxied_get(b"/api/queue"))
    assert (status, ctype) == (404, "application/json")
    assert b"synthetic-upstream-body" not in body
    assert json.loads(body)["error"] == "not found"


def test_the_minimap_crop_is_204_when_nothing_answers(served, closed_supervisor):
    assert _exchange(served, _proxied_get(b"/api/minimap-crop"))[0] == 204


def test_the_minimap_crop_is_204_on_an_upstream_error(served, failing_supervisor):
    assert _exchange(served, _proxied_get(b"/api/minimap-crop"))[0] == 204


def test_an_exception_nothing_catches_gets_the_generic_500(served, monkeypatch):
    # RM-1288: this used to pin "no reply". The full contract (GET, a reply
    # already begun, a client that went away) is
    # tests/test_dashboard_uncaught_route_s144d68.py.
    def _boom(*_a, **_k):
        raise RuntimeError("synthetic route failure")

    monkeypatch.setattr(handler_mod._dispatch, "dispatch_post", _boom)
    status, ctype, body = _exchange(served, _post())
    assert (status, ctype) == (500, "application/json")
    assert json.loads(body) == {"error": GENERIC_ERROR}


def test_send_error_answers_500_with_the_line_and_never_the_exception():
    sent = []

    class _Double:
        @staticmethod
        def _send(status, body, ctype):
            sent.append((status, body, ctype))

    secret = "synthetic-secret-in-the-exception"  # rc-credential-scan: allow-fixture
    send_error(_Double, RuntimeError(secret))
    send_error(_Double, RuntimeError(secret), public_msg="a route's own line")
    assert [s[0] for s in sent] == [500, 500]
    assert all(secret.encode() not in s[1] for s in sent)
    assert json.loads(sent[0][1])["error"] == GENERIC_ERROR
    assert json.loads(sent[1][1])["error"] == "a route's own line"
    assert f"`{GENERIC_ERROR}`" in _flat("## Error shapes")


@pytest.mark.parametrize(
    ("peer", "local", "environ", "admitted"),
    [("127.0.0.1", "127.0.0.1", {}, True),
     ("::1", "::1", {}, True),
     ("192.0.2.10", "192.0.2.10", {}, True),
     ("100.64.0.5", "100.64.0.1", {}, True),
     ("192.0.2.10", "192.0.2.20", {}, False),
     ("100.64.0.5", "192.0.2.20", {}, False),
     ("192.0.2.10", "192.0.2.20", {"RC_DASH_CONTROL_NETS": "192.0.2.0/24"}, True)],
    ids=["loopback", "loopback-v6", "this-machine", "tailnet", "lan-host",
         "tailnet-numbered-peer-on-the-lan-address", "control-nets"])
def test_the_peer_summary_is_what_the_gate_decides(peer, local, environ, admitted):
    assert server_mod.control_peer_allowed(peer, local, environ) is admitted


def test_the_recordings_check_asks_only_when_a_token_is_set(monkeypatch):
    class _NoToken:
        headers: dict = {}

    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    assert routes_recordings._auth_ok(_NoToken) is True
    monkeypatch.setenv("RC_DASH_TOKEN", "synthetic-dash-token")
    assert routes_recordings._auth_ok(_NoToken) is False


def test_the_control_list_equals_the_source_both_ways():
    auth = _doc_section("## Authentication")
    named = set(re.findall(r"/api/[\w/-]*", auth)) | set(re.findall(r"`(/[^`]+)`", auth))
    source = set(_constant(_HANDLER, "_CONTROL_ENDPOINTS"))
    source |= set(_constant(_HANDLER, "_CONTROL_PREFIXES"))
    assert named == source
    assert all(is_control_endpoint(path) for path in named)


def test_the_bind_and_gate_names_are_the_ones_in_the_source():
    auth = _doc_section("## Authentication")
    assert f"`{_constant(_SERVER, 'HOST')}`" in auth
    assert f"`{_constant(_SERVER, 'BIND_ENV')}`" in auth
    server_text = _SERVER.read_text(encoding="utf-8")
    handler_text = _HANDLER.read_text(encoding="utf-8")
    for name, source in (("RC_DASH_TOKEN", handler_text),
                         ("X-RC-Token", handler_text),
                         ("RC_DASH_CONTROL_NETS", server_text)):
        assert name in source, f"{name} left the source"
        assert f"`{name}`" in auth, f"{name} left the doc"


def test_the_one_route_level_token_check_is_named_and_still_the_only_one():
    """The doc's "One route module" clause: re-derived by reading the env var."""
    dashboard_dir = _REPO_ROOT / "dashboard"
    readers = sorted(
        path.name for path in dashboard_dir.glob("*.py")
        if 'environ.get("RC_DASH_TOKEN"' in path.read_text(encoding="utf-8"))
    assert readers == ["_handler.py", "routes_recordings.py"]
    assert "`dashboard/routes_recordings.py`" in _doc_section("## Authentication")


def test_a_set_token_gates_a_loopback_caller_too(served, monkeypatch):
    """The doc's "every peer, loopback included" clause, on the real handler."""
    monkeypatch.setenv("RC_DASH_TOKEN", "synthetic-dash-token")
    status, _, _ = _exchange(served, _post(path=b"/api/command"))
    assert status == 401
    assert "every peer, loopback included" in _doc_section("## Authentication")


def test_a_non_control_post_is_not_gated_by_the_peer(served, monkeypatch):
    """The doc's "no credential" half: a refused peer still reaches dispatch."""
    monkeypatch.delenv("RC_DASH_TOKEN", raising=False)
    monkeypatch.setattr(handler_mod, "control_peer_allowed", lambda *_a, **_k: False)
    status, _, body = _exchange(served, _post())
    assert (status, body) == (404, b"not found")
    assert "no credential" in _doc_section("## Authentication")
