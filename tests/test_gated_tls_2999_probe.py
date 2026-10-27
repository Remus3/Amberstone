"""tests/test_gated_tls_2999_probe.py

`tools/gated_tls_2999_probe.py` is the RM-752 follow-up probe: during a League
game it asks Riot's :2999 Live Client which TLS contexts it accepts, so the
relay's deliberate TLSv1 floor gets a measured keep / raise decision. Every test
here runs against a loopback TLS server this test starts, or against fakes; no
test touches :2999, :8888, :8889 or the relay process.
"""
from __future__ import annotations

import ast
import contextlib
import datetime
import http.client
import http.server
import ipaddress
import json
import socket
import ssl
import threading

import pytest

from tests._module_view import bind_urlopen
from tools import gated_tls_2999_probe as gtp

_HOST = "127.0.0.1"
# Synthetic gamestats body: the keys :2999 serves, no player data.
_GAMESTATS = {"gameMode": "CLASSIC", "gameTime": 312.5, "mapName": "Map11",
              "mapNumber": 11, "mapTerrain": "Default"}


def _self_signed(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "gated-tls-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address(_HOST))]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path = tmp_path / "gated-tls-cert.pem"
    key_path = tmp_path / "gated-tls-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    return cert_path, key_path


class _Gamestats(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - http.server API
        if self.path != gtp._PATH:
            self.send_error(404)
            return
        body = json.dumps(_GAMESTATS).encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):
        pass


@contextlib.contextmanager
def _served(tmp_path, max_version=None, ciphers=None):
    cert_path, key_path = _self_signed(tmp_path)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    if max_version is not None:
        ctx.maximum_version = max_version
    if ciphers is not None:
        ctx.set_ciphers(ciphers)
    srv = http.server.ThreadingHTTPServer((_HOST, 0), _Gamestats)
    srv.daemon_threads = True
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="gated-tls")
    t.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)


def _probe_all(port):
    return [gtp.probe_one(name, build(), host=_HOST, port=port, timeout=5.0)
            for name, build in gtp.CONTEXTS]


def _by(results):
    return {r["context"]: r for r in results}


# --- the contexts -----------------------------------------------------------

def test_context_floors_match_their_names():
    built = {name: build() for name, build in gtp.CONTEXTS}
    assert [n for n, _ in gtp.CONTEXTS] == ["relay", "floor12", "floor12_legacy",
                                             "tls13_only"]
    assert built["relay"].minimum_version == ssl.TLSVersion.TLSv1
    assert built["floor12"].minimum_version == ssl.TLSVersion.TLSv1_2
    assert built["floor12_legacy"].minimum_version == ssl.TLSVersion.TLSv1_2
    assert built["tls13_only"].minimum_version == ssl.TLSVersion.TLSv1_3
    for ctx in built.values():
        assert ctx.verify_mode == ssl.CERT_NONE
        assert ctx.check_hostname is False


def test_legacy_ciphers_widen_the_default_list():
    default = {c["name"] for c in gtp.client_context_noverify().get_ciphers()}
    legacy = {c["name"] for c in gtp.floor12_legacy_context().get_ciphers()}
    assert default <= legacy
    assert {c["name"] for c in gtp.relay_context().get_ciphers()} == legacy


def test_floor12_is_the_rm752_factory_itself():
    from core import tls_policy
    assert gtp.client_context_noverify is tls_policy.client_context_noverify


# --- relay parity -----------------------------------------------------------

def test_relay_parity_holds_on_the_tracked_relay():
    digest = gtp.relay_tls_digest()
    assert gtp.relay_parity() is True, (
        "tools/liveclient_relay.py changed a TLS-relevant statement. Re-read its "
        "_ssl_ctx setup and request path against relay_context(), then set "
        f"_RELAY_TLS_SHA256 = {digest!r}")


_FLOOR = "    _ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1\n"
_CIPHERS = '    _ssl_ctx.set_ciphers("ALL:@SECLEVEL=0")\n'
_USE = '            kwargs["context"] = _ssl_ctx\n'
_OPEN = "        with urllib.request.urlopen(url, **kwargs) as r:\n"
_CTOR = "_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)\n"


def _relay_text():
    return gtp._RELAY_SRC.read_text(encoding="utf-8").replace("\r\n", "\n")


def _write(tmp_path, text):
    src = tmp_path / "liveclient_relay.py"
    src.write_bytes(text.encode("utf-8"))
    return src


# (old, new): every edit changes what the relay's TLS does, or which context its
# request uses. old=None appends new at the end of the module.
_TLS_EDITS = {
    "floor raised": (_FLOOR, _FLOOR.replace("TLSv1\n", "TLSv1_2\n")),
    "floor commented out": (_FLOOR, "    # " + _FLOOR.lstrip() + "    pass\n"),
    "ciphers commented out": (_CIPHERS, "    # " + _CIPHERS.lstrip() + "    pass\n"),
    "protocol changed": (_CTOR, _CTOR.replace("PROTOCOL_TLS_CLIENT", "PROTOCOL_TLS")),
    "later floor override": (None, "_ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2\n"),
    "options augmented": (None, "_ssl_ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1\n"),
    "annotated floor": (_FLOOR, "    _ssl_ctx.minimum_version: object = "
                                "ssl.TLSVersion.TLSv1_2\n"),
    "setattr": (None, "setattr(_ssl_ctx, 'minimum_version', ssl.TLSVersion.TLSv1_2)\n"),
    "alias": (None, "_c = _ssl_ctx\n_c.minimum_version = ssl.TLSVersion.TLSv1_2\n"),
    "tuple target": (None, "_ssl_ctx.minimum_version, _x = ssl.TLSVersion.TLSv1_2, 1\n"),
    "request context swapped": (_USE, '            kwargs["context"] = '
                                      "ssl.create_default_context()\n"),
    "urlopen context swapped": (_OPEN, "        with urllib.request.urlopen(url, timeout=2, "
                                       "context=ssl.create_default_context()) as r:\n"),
    "second kwargs write": (_USE, _USE + '            kwargs["context"] = '
                                         "ssl.create_default_context()\n"),
    "floor under if False": (_FLOOR, "    pass\nif False:\n" + _FLOOR),
    "floor in an uncalled function": (_FLOOR, "    pass\ndef _never():\n" + _FLOOR),
    "del options": (None, "del _ssl_ctx.options\n"),
    "opener with its own context": (None, "_opener = urllib.request.build_opener("
                                          "urllib.request.HTTPSHandler(context=None))\n"),
    "new http library": (None, "import requests\n"),
    "https url dropped": ('    "https://127.0.0.1:2999/liveclientdata/allgamedata",\n', ""),
    "fetch_live skips https": ("    for url in LIVE_URLS:\n",
                               "    for url in LIVE_URLS[1:]:\n"),
}


@pytest.mark.parametrize("name", sorted(_TLS_EDITS))
def test_relay_parity_reads_false_after_a_tls_edit(tmp_path, name):
    old, new = _TLS_EDITS[name]
    text = _relay_text()
    if old is None:
        edited = text + new
    else:
        assert text.count(old) == 1, f"edit anchor gone from the relay: {old!r}"
        edited = text.replace(old, new)
    assert edited != text
    assert gtp.relay_parity(_write(tmp_path, edited)) is False


@pytest.mark.parametrize("edit", ["comment", "crlf", "spacing", "non-tls constant"])
def test_relay_parity_ignores_comments_formatting_and_non_tls_code(tmp_path, edit):
    text = _relay_text()
    if edit == "comment":
        edited = text.replace(_FLOOR, "    # a note\n" + _FLOOR)
    elif edit == "crlf":
        edited = text.replace("\n", "\r\n")
    elif edit == "spacing":
        edited = text.replace(_FLOOR, _FLOOR.replace(" = ", "  =  "))
    else:
        assert "INTERVAL = 1.0" in text
        edited = text.replace("INTERVAL = 1.0", "INTERVAL = 2.0")
    assert edited != text
    assert gtp.relay_parity(_write(tmp_path, edited)) is True


@pytest.mark.parametrize("text", ["", "def broken(:\n"])
def test_relay_parity_is_false_for_an_unparseable_relay(tmp_path, text):
    assert gtp.relay_parity(_write(tmp_path, text)) is False


def test_canon_drops_empty_and_none_fields():
    fn = ast.parse("def f(x):\n    return x\n").body[0]
    flat = json.dumps(gtp._canon(fn))
    assert "type_params" not in flat and "returns" not in flat
    assert "lineno" not in flat and '"FunctionDef"' in flat


def test_relay_parity_is_false_for_a_missing_file(tmp_path):
    assert gtp.relay_parity(tmp_path / "absent.py") is False


# --- real loopback handshakes -----------------------------------------------

def test_a_modern_server_accepts_every_context_and_reads_raise(tmp_path):
    with _served(tmp_path) as port:
        results = _probe_all(port)
    by = _by(results)
    for name in ("relay", "floor12", "floor12_legacy", "tls13_only"):
        r = by[name]
        assert r["handshake"] is True, r
        assert r["status"] == 200, r
        assert r["json_keys"] == sorted(_GAMESTATS), r
        assert r["tls_version"] == "TLSv1.3", r
        assert r["cipher"], r
    assert gtp.verdict(True, True, results) == "RAISE"
    # Values never reach the report, only keys.
    assert "312.5" not in json.dumps(results)


def test_a_tls12_capped_server_rejects_only_tls13_only(tmp_path):
    with _served(tmp_path, max_version=ssl.TLSVersion.TLSv1_2) as port:
        results = _probe_all(port)
    by = _by(results)
    assert by["floor12"]["tls_version"] == "TLSv1.2"
    assert gtp.is_ok(by["floor12"])
    assert gtp.is_rejected(by["tls13_only"]), by["tls13_only"]
    assert by["tls13_only"]["error_class"] == "ssl"
    assert gtp.verdict(True, True, results) == "RAISE"


def test_a_sha1_cipher_only_server_reads_raise_floor_keep_ciphers(tmp_path):
    # A TLSv1_2 peer that offers only a SHA1-MAC suite: Python's default cipher
    # string excludes it (!SHA1), the relay's SECLEVEL=0 list carries it.
    with _served(tmp_path, max_version=ssl.TLSVersion.TLSv1_2,
                 ciphers="ECDHE-ECDSA-AES128-SHA:@SECLEVEL=0") as port:
        results = _probe_all(port)
    by = _by(results)
    assert gtp.is_ok(by["relay"]), by["relay"]
    assert gtp.is_rejected(by["floor12"]), by["floor12"]
    assert gtp.is_ok(by["floor12_legacy"]), by["floor12_legacy"]
    assert by["floor12_legacy"]["cipher"] == "ECDHE-ECDSA-AES128-SHA"
    assert gtp.verdict(True, True, results) == "RAISE-FLOOR-KEEP-CIPHERS"


def test_a_wrong_path_is_a_handshake_but_not_ok(tmp_path):
    with _served(tmp_path) as port:
        r = gtp.probe_one("relay", gtp.relay_context(), host=_HOST, port=port,
                          path="/liveclientdata/allgamedataX", timeout=5.0)
    assert r["handshake"] is True and r["status"] == 404
    assert not gtp.is_ok(r) and not gtp.is_rejected(r)


def test_a_closed_port_is_never_a_rejection():
    with socket.socket() as s:
        s.bind((_HOST, 0))
        port = s.getsockname()[1]
    r = gtp.probe_one("floor12", gtp.client_context_noverify(), host=_HOST,
                      port=port, timeout=5.0)
    assert r["handshake"] is False
    assert r["error_class"] in {"refused", "timeout"}
    assert not gtp.is_rejected(r)


# --- probe_one never raises -------------------------------------------------

class _RaisingConn:
    def __init__(self, exc):
        self._exc = exc
        self.closed = False

    def connect(self):
        raise self._exc

    def close(self):
        self.closed = True


@pytest.mark.parametrize("exc, cls", [
    (ssl.SSLEOFError(8, "UNEXPECTED_EOF_WHILE_READING"), "ssl"),
    (ConnectionResetError(10054, "reset"), "reset"),
    (ConnectionAbortedError(10053, "aborted"), "reset"),
    (ConnectionRefusedError(10061, "refused"), "refused"),
    (TimeoutError("timed out"), "timeout"),
    (http.client.RemoteDisconnected("gone"), "reset"),
    (OSError(10065, "unreachable"), "os"),
])
def test_probe_one_classifies_and_closes(exc, cls):
    conns = []

    def factory(*_a, **_k):
        conns.append(_RaisingConn(exc))
        return conns[-1]

    r = gtp.probe_one("relay", gtp.relay_context(), conn_factory=factory)
    assert r["handshake"] is False
    assert r["error_class"] == cls
    assert conns[0].closed is True
    assert isinstance(r["elapsed_ms"], float)


# --- the verdict ------------------------------------------------------------

def _ok(name):
    return {"context": name, "handshake": True, "status": 200,
            "json_keys": sorted(_GAMESTATS), "error_class": None}


def _rej(name, cls="ssl"):
    return {"context": name, "handshake": False, "status": None,
            "json_keys": None, "error_class": cls}


def _down(name, cls="refused"):
    return {"context": name, "handshake": False, "status": None,
            "json_keys": None, "error_class": cls}


@pytest.mark.parametrize("in_game, parity, rows, expected", [
    (True, True, [_ok("relay"), _ok("floor12"), _ok("floor12_legacy")], "RAISE"),
    (True, True, [_ok("relay"), _rej("floor12"), _ok("floor12_legacy")],
     "RAISE-FLOOR-KEEP-CIPHERS"),
    (True, True, [_ok("relay"), _rej("floor12"), _rej("floor12_legacy")], "KEEP"),
    (True, True, [_ok("relay"), _rej("floor12", "reset"),
                  _rej("floor12_legacy", "reset")], "KEEP"),
    (False, True, [_ok("relay"), _ok("floor12")], "NOT-YET"),
    (True, False, [_ok("relay"), _ok("floor12")], "NOT-YET"),
    (True, True, [_down("relay"), _ok("floor12")], "NOT-YET"),
    (True, True, [_rej("relay"), _rej("floor12"), _rej("floor12_legacy")], "NOT-YET"),
    (True, True, [_ok("relay"), _down("floor12", "timeout")], "NOT-YET"),
    (True, True, [_ok("relay"), _rej("floor12"), _down("floor12_legacy", "timeout")],
     "NOT-YET"),
    (True, True, [_ok("relay"), _rej("floor12")], "NOT-YET"),
    (True, True, [{**_ok("relay"), "json_keys": ["errorCode"]}, _ok("floor12")],
     "NOT-YET"),
    (True, True, [{**_ok("relay"), "status": 404}, _ok("floor12")], "NOT-YET"),
])
def test_verdict_table(in_game, parity, rows, expected):
    assert gtp.verdict(in_game, parity, rows) == expected


def test_tls13_only_never_moves_the_verdict():
    base = [_ok("relay"), _ok("floor12"), _ok("floor12_legacy")]
    assert gtp.verdict(True, True, base + [_rej("tls13_only")]) == "RAISE"
    keep = [_ok("relay"), _rej("floor12"), _rej("floor12_legacy")]
    assert gtp.verdict(True, True, keep + [_ok("tls13_only")]) == "KEEP"


# --- /api/state and the :8889 envelope --------------------------------------

class _Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status = status

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.mark.parametrize("state, in_game, game_mode", [
    ({"mode_key": "aram", "liveclient": {"game_mode": "KIWI", "game_time": "1:30",
                                         "game_time_s": 90.0}},
     True, "KIWI"),
    ({"mode_key": "jade", "liveclient": {"game_mode": "CLASSIC"}}, True, "CLASSIC"),
    ({"mode_key": "sr", "liveclient": {"game_mode": "PRACTICETOOL"}}, True,
     "PRACTICETOOL"),
    ({"mode_key": "tft", "liveclient": {"game_mode": "TFT", "game_time": 9}},
     False, "TFT"),
    ({"mode_key": "client", "liveclient": {}}, False, None),
    ({"mode_key": "sr", "liveclient": None}, False, None),
])
def test_read_state_counts_only_league_modes(monkeypatch, state, in_game, game_mode):
    bind_urlopen(monkeypatch, gtp,
                 lambda *_a, **_k: _Resp(json.dumps(state).encode()))
    out = gtp.read_state()
    assert out["in_league_game"] is in_game
    assert out["game_mode"] == game_mode
    assert out["error"] is None


def test_read_state_fails_soft(monkeypatch):
    def boom(*_a, **_k):
        raise ConnectionRefusedError(10061, "refused")
    bind_urlopen(monkeypatch, gtp, boom)
    out = gtp.read_state()
    assert out["in_league_game"] is False
    assert out["error"].startswith("ConnectionRefusedError")


class _Opener:
    def __init__(self, resp):
        self._resp = resp
        self.headers = None

    def open(self, req, timeout):
        self.headers = dict(req.header_items())
        if isinstance(self._resp, BaseException):
            raise self._resp
        return self._resp


def test_envelope_keeps_source_and_age_never_the_payload(monkeypatch):
    env = {"data": {"activePlayer": {"summonerName": "Synthetic#0001"}},
           "ts": 1000.0, "size": 0, "source": "self_read"}
    opener = _Opener(_Resp(json.dumps(env).encode()))
    monkeypatch.setattr(gtp, "resolve_token", lambda: ("tok-synthetic", "config"))
    monkeypatch.setattr(gtp, "_OPENER", opener)
    out = gtp.read_liveclient_source(now=lambda: 1003.5)
    assert out == {"token_source": "config", "status": 200, "source": "self_read",
                   "age_s": 3.5, "error": None}
    assert "Synthetic" not in json.dumps(out)
    assert opener.headers.get("X-rc-token") == "tok-synthetic"


def test_envelope_without_token_makes_no_request(monkeypatch):
    opener = _Opener(AssertionError("no request without a token"))
    monkeypatch.setattr(gtp, "resolve_token", lambda: ("", "none"))
    monkeypatch.setattr(gtp, "_OPENER", opener)
    out = gtp.read_liveclient_source()
    assert out["error"] == "no vision token" and opener.headers is None


def test_envelope_404_is_recorded(monkeypatch):
    err = gtp.urllib.error.HTTPError(gtp._LIVECLIENT_URL, 404, "Not Found", {}, None)
    monkeypatch.setattr(gtp, "resolve_token", lambda: ("tok-synthetic", "config"))
    monkeypatch.setattr(gtp, "_OPENER", _Opener(err))
    assert gtp.read_liveclient_source()["status"] == 404


# --- collect and main -------------------------------------------------------

def _collect(before, after, results, is_league=True):
    states = iter([before, after])
    rows = iter(results)
    return gtp.collect(state_fn=lambda: next(states),
                       source_fn=lambda: {"source": "agent_push"},
                       probe_fn=lambda name, ctx: next(rows),
                       parity_fn=lambda: True,
                       listener_fn=lambda: {"is_league": is_league},
                       now=lambda: 5.0)


_UP = {"in_league_game": True, "game_time_s": 90}


def test_collect_needs_the_game_before_and_after():
    rows = [_ok("relay"), _ok("floor12"), _ok("floor12_legacy"), _ok("tls13_only")]
    down = {"in_league_game": False, "game_time_s": 90}
    assert _collect(_UP, _UP, rows)["verdict"] == "RAISE"
    assert _collect(_UP, down, rows)["verdict"] == "NOT-YET"
    assert _collect(down, _UP, rows)["verdict"] == "NOT-YET"


@pytest.mark.parametrize("gts", [0, None, "1:30", True, -1])
def test_collect_needs_the_game_past_loading(gts):
    rows = [_ok("relay"), _ok("floor12"), _ok("floor12_legacy"), _ok("tls13_only")]
    loading = {"in_league_game": True, "game_time_s": gts}
    rep = _collect(loading, _UP, rows)
    assert rep["past_loading"] is False
    assert rep["verdict"] == "NOT-YET"


@pytest.mark.parametrize("owners", [[False, False], [True, False], [False, True]])
def test_collect_needs_league_to_own_the_port_before_and_after(owners):
    rows = [_ok("relay"), _ok("floor12"), _ok("floor12_legacy"), _ok("tls13_only")]
    up = _UP
    seq = iter(owners)
    states = iter([up, up])
    it = iter(rows)
    rep = gtp.collect(state_fn=lambda: next(states), source_fn=dict,
                      probe_fn=lambda name, ctx: next(it), parity_fn=lambda: True,
                      listener_fn=lambda: {"is_league": next(seq)}, now=lambda: 5.0)
    assert rep["in_league_game"] is False
    assert rep["verdict"] == "NOT-YET"


class _FakePsutil:
    def __init__(self, conns, names, deny=False):
        self._conns = conns
        self._names = names
        self._deny = deny

    def net_connections(self, kind):
        assert kind == "tcp"
        return self._conns

    def Process(self, pid):  # noqa: N802 - psutil API
        if self._deny:
            raise PermissionError("denied")
        return type("P", (), {"name": lambda _s: self._names[pid]})()


def _listen(port, pid):
    laddr = type("A", (), {"port": port})()
    return type("C", (), {"laddr": laddr, "pid": pid, "status": "LISTEN"})()


@pytest.mark.parametrize("conns, names, is_league", [
    ([_listen(2999, 41)], {41: "League of Legends.exe"}, True),
    ([_listen(2999, 41)], {41: "svchost.exe"}, False),
    ([_listen(2999, 41), _listen(2999, 42)],
     {41: "League of Legends.exe", 42: "svchost.exe"}, False),
    ([_listen(8889, 41)], {41: "League of Legends.exe"}, False),
    ([], {}, False),
])
def test_read_listener_names_the_owner(conns, names, is_league):
    out = gtp.read_listener(_FakePsutil(conns, names))
    assert out["is_league"] is is_league
    assert out["error"] is None


def test_read_listener_fails_closed_on_a_denied_read():
    out = gtp.read_listener(_FakePsutil([_listen(2999, 41)], {}, deny=True))
    assert out["is_league"] is False
    assert out["error"] == "PermissionError"


def test_collect_records_the_interpreter_and_order():
    rows = [_ok("relay"), _ok("floor12"), _ok("floor12_legacy"), _ok("tls13_only")]
    rep = _collect(_UP, _UP, rows)
    assert rep["openssl"] == ssl.OPENSSL_VERSION
    assert [r["context"] for r in rep["results"]] == [n for n, _ in gtp.CONTEXTS]
    assert rep["wall"] == 5.0


@pytest.mark.parametrize("verdict, code", [("RAISE", 0), ("KEEP", 0),
                                           ("RAISE-FLOOR-KEEP-CIPHERS", 0),
                                           ("NOT-YET", 1)])
def test_main_exit_code(monkeypatch, capsys, verdict, code):
    rep = {"verdict": verdict, "results": [], "relay_parity": True}
    monkeypatch.setattr(gtp, "collect", lambda: rep)
    assert gtp.main(["--json"]) == code
    assert json.loads(capsys.readouterr().out)["verdict"] == verdict
