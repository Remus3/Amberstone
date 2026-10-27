"""Lane 8 true-audit (s144): dashboard/routes_vision_calibrator.py.

The calibrator routes take POST bodies and query strings from the :8888
dashboard, write the TRACKED data/vision_regions.json and the per-config
vision profiles, and proxy the :8889 frame with the vision token. Findings,
each pinned here by a test that was red before the fix:

F1  A NaN / Infinity / 1e400 coordinate (``json.loads`` accepts all three, and
    the dashboard handler parses bodies with it) made ``validate_regions``
    raise ValueError / OverflowError instead of returning a refusal, so the
    POST answered 500 "internal error" instead of 400. Same root cause in the
    callee ``core.vision_profiles.validate_base`` (the profile save path).
F2  The range check ran AFTER ``int()`` truncation, so -0.5 became 0 and
    10000.5 became 10000 and both passed the off-canvas guard.
F3  A region name had no length, character or count bound: a megabyte name or
    a control character was persisted to the tracked regions file, and the
    whole name was echoed back in the 400 error text.
F4  The frame proxy used the process-default urllib opener, which honours
    HTTP_PROXY / the registry proxy for 127.0.0.1, so the X-RC-Token header
    went to the proxy (measured: ``proxy_bypass("127.0.0.1:8889")`` is False
    with HTTP_PROXY set). The relay read was also unbounded.
F5  A non-numeric frame ``ts`` dropped a present frame as "relay unavailable",
    and a non-finite one produced ``age_s`` NaN, which ``json.dumps`` writes
    as the bare token NaN - not JSON, so the page's ``response.json()``
    fails. The reference-frame payload had the same NaN path.
F6  ``load_regions`` returned any JSON value, so a list or a string in the
    regions file went out as ``"regions": [...]`` although the docstring
    promises {} on a malformed file.
F7  ``_send_json`` allowed NaN, so any non-finite number that reached a
    response produced invalid JSON instead of the generic 500.
"""
from __future__ import annotations

import http.server
import importlib.util
import json
import math
import socket
import threading
import types
import urllib.request

import pytest

from core import vision_profiles as vp
from dashboard import routes_vision_calibrator as vc

_TOKEN = "TESTTOKEN-not-a-real-token-0000"


def _strict(body: bytes):
    """Parse a response the way a browser does: NaN / Infinity are errors."""
    def _refuse(tok):
        raise ValueError(f"non-JSON constant {tok}")
    return json.loads(body.decode("utf-8"), parse_constant=_refuse)


class _FakeHandler:
    def __init__(self, path: str = "/api/vision-regions"):
        self.path = path
        self.sent = None

    def _send(self, code, body, ctype):
        self.sent = (code, body, ctype)

    @property
    def code(self):
        return self.sent[0]

    @property
    def payload(self):
        return _strict(self.sent[1])


# -- F1 non-finite coordinates ---------------------------------------------

_NON_FINITE = ["NaN", "Infinity", "-Infinity", "1e400"]


def _loads_with(template: str, tok: str):
    """Parse ``template`` with TOK replaced, exactly as the dashboard handler
    parses a body (plain ``json.loads``, which accepts all four tokens)."""
    return json.loads(template.replace("TOK", tok))


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f1_validate_regions_refuses_non_finite_without_raising(tok):
    regions = _loads_with('{"hp": [TOK, 0, 10, 10]}', tok)
    ok, err, clean = vc.validate_regions(regions)
    assert ok is False
    assert err and "hp" in err
    assert clean == {}


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f1_post_with_non_finite_coordinate_is_400_and_writes_nothing(
        tok, tmp_path, monkeypatch):
    target = tmp_path / "vision_regions.json"
    target.write_text('{"hp": [1, 2, 3, 4]}\n', encoding="utf-8")
    monkeypatch.setattr(vc, "REGIONS_PATH", target)
    body = _loads_with('{"regions": {"hp": [0, 0, TOK, 10]}}', tok)
    h = _FakeHandler()
    vc._serve_regions_post(h, body)
    assert h.code == 400
    assert h.payload["ok"] is False
    assert target.read_text(encoding="utf-8") == '{"hp": [1, 2, 3, 4]}\n'


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f1_profile_post_with_non_finite_coordinate_never_saves(
        tok, monkeypatch):
    calls = []
    monkeypatch.setattr(vp, "save_profile", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(vp, "active_config_key", lambda: "cfg")
    body = _loads_with('{"regions": {"hp": [0, 0, 10, TOK]}, '
                       '"base": [2560, 1440]}', tok)
    h = _FakeHandler()
    vc._serve_regions_post(h, body)
    assert h.code == 400
    assert calls == []


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f1_validate_base_refuses_non_finite_without_raising(tok):
    base = _loads_with("[TOK, 1440]", tok)
    ok, err, clean = vp.validate_base(base)
    assert ok is False
    assert err
    assert clean is None


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f1_profile_post_with_non_finite_base_is_400(tok, monkeypatch):
    calls = []
    monkeypatch.setattr(vp, "save_profile", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(vp, "active_config_key", lambda: "cfg")
    body = _loads_with('{"regions": {"hp": [0, 0, 10, 10]}, '
                       '"base": [2560, TOK]}', tok)
    h = _FakeHandler()
    vc._serve_regions_post(h, body)
    assert h.code == 400
    assert calls == []


# -- F2 range checked on the raw value ---------------------------------------

@pytest.mark.parametrize("box", [
    [-0.5, 0, 10, 10],
    [0, -0.25, 10, 10],
    [0, 0, 10000.5, 10],
    [0, 0, 10, 10000.001],
])
def test_f2_out_of_range_fraction_is_not_truncated_into_range(box):
    ok, err, _ = vc.validate_regions({"hp": box})
    assert ok is False
    assert "out of range" in err


def test_f2_in_range_fractions_still_truncate_as_before():
    ok, err, clean = vc.validate_regions({"hp": [0.9, 1.2, 10.7, 20.99]})
    assert ok, err
    assert clean == {"hp": [0, 1, 10, 20]}


@pytest.mark.parametrize("base", [[10000.5, 1440], [2560, 10000.25]])
def test_f2_validate_base_checks_the_raw_value(base):
    ok, err, _ = vp.validate_base(base)
    assert ok is False
    assert err == "base out of range"


def test_f2_validate_base_edges_unchanged():
    assert vp.validate_base([10000, 1]) == (True, None, [10000, 1])
    assert vp.validate_base([2560.7, 1440.2]) == (True, None, [2560, 1440])
    assert vp.validate_base([0.5, 1440])[0] is False


# -- F3 region name and count bounds ------------------------------------------

def test_f3_name_at_the_length_cap_is_accepted():
    name = "n" * vc._NAME_MAX
    ok, err, clean = vc.validate_regions({name: [0, 0, 1, 1]})
    assert ok, err
    assert list(clean) == [name]


def test_f3_overlong_name_is_refused_and_not_echoed():
    name = "x" * (vc._NAME_MAX + 1) + "TAILMARK"
    ok, err, _ = vc.validate_regions({name: [0, 0, 1, 1]})
    assert ok is False
    assert "TAILMARK" not in err
    assert len(err) < 200


def test_f3_one_past_the_length_cap_is_refused():
    ok, _, clean = vc.validate_regions({"n" * (vc._NAME_MAX + 1): [0, 0, 1, 1]})
    assert ok is False
    assert clean == {}


def test_f2_the_coordinate_ceiling_itself_is_still_accepted():
    for box in ([0, 0, vc._COORD_MAX, 1], [0, 0, float(vc._COORD_MAX), 1]):
        ok, err, clean = vc.validate_regions({"hp": box})
        assert ok, err
        assert clean == {"hp": [0, 0, vc._COORD_MAX, 1]}


@pytest.mark.parametrize("name", ["hp\n", "a\x00b", "tab\tname", "bell\x07",
                                  "del\x7f", "c1\x85"])
def test_f3_control_characters_in_a_name_are_refused(name):
    ok, err, _ = vc.validate_regions({name: [0, 0, 1, 1]})
    assert ok is False
    assert name not in err


def test_f3_a_bad_box_error_never_echoes_a_raw_control_name():
    # The name check runs first, so a control name can never reach the
    # f"{name}: ..." box messages.
    ok, err, _ = vc.validate_regions({"evil\nFORGED": [1, 2]})
    assert ok is False
    assert "\n" not in err


def test_f3_region_count_cap():
    at_cap = {f"r{i}": [0, 0, 1, 1] for i in range(vc._REGIONS_MAX)}
    ok, err, clean = vc.validate_regions(at_cap)
    assert ok, err
    assert len(clean) == vc._REGIONS_MAX
    over = dict(at_cap, extra=[0, 0, 1, 1])
    ok, err, clean = vc.validate_regions(over)
    assert ok is False
    assert clean == {}


def test_f3_real_profile_names_fit_the_bounds():
    # Measured at audit time: the live profiles hold <= 33 regions with
    # names <= 28 printable ASCII characters; the tracked regions file 21.
    tracked = json.loads(vc.REGIONS_PATH.read_text(encoding="utf-8"))
    ok, err, clean = vc.validate_regions(tracked)
    assert ok, err
    assert len(clean) == len(tracked)


# -- F4 frame proxy: no environment proxy, bounded read ------------------------

class _ProxyTrap:
    """A TCP listener standing in for an HTTP proxy; records what it is sent."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.sock.settimeout(0.2)
        self.port = self.sock.getsockname()[1]
        self.received = b""
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="proxy-trap",
                                       daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                continue
            with conn:
                conn.settimeout(1.0)
                try:
                    self.received += conn.recv(65536)
                    conn.sendall(b"HTTP/1.0 502 Bad Gateway\r\n"
                                 b"Content-Length: 0\r\n\r\n")
                except OSError:
                    pass

    def close(self):
        self._stop.set()
        self.thread.join(timeout=2)
        self.sock.close()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_f4_frame_proxy_never_sends_the_token_to_an_env_proxy(monkeypatch):
    # urllib's process-global opener reads the proxy settings ONCE, on the
    # first urlopen() call, and keeps them. Start this test from a fresh one
    # and put the original back afterwards, so a regression here can never
    # freeze the trap proxy into every later urlopen() in this worker.
    monkeypatch.setattr(urllib.request, "_opener", None)
    trap = _ProxyTrap()
    try:
        for k in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{trap.port}")
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{trap.port}")
        monkeypatch.setattr(vc, "_vision_token", lambda: _TOKEN)
        frame_url = f"http://127.0.0.1:{_free_port()}/latest-frame"
        monkeypatch.setattr(vc, "_FRAME_URL", frame_url)
        out = vc.fetch_frame()
    finally:
        trap.close()
    assert out["ok"] is False
    assert _TOKEN.encode() not in trap.received
    # A proxied request line carries the absolute URL, and only the code under
    # test knows this one (a fresh port). The proxy env is process-wide, so a
    # leftover thread of an earlier test in this worker that calls urlopen()
    # during the window reaches the trap too ("received == b''" read that as
    # this route's request in the s144 L3 gated Tier-2 run, gw3).
    assert frame_url.encode() not in trap.received
    assert b"/latest-frame" not in trap.received


class _FrameServer:
    def __init__(self, body: bytes):
        payload = body

        class _H(http.server.BaseHTTPRequestHandler):
            seen_tokens: list = []

            def do_GET(self):  # noqa: N802 - stdlib name
                _H.seen_tokens.append(self.headers.get("X-RC-Token"))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.handler = _H
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), _H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       name="frame-server", daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)


def test_f4_default_fetch_reads_a_real_relay_with_the_token(monkeypatch):
    body = json.dumps({"b64": "QUJD", "width": 1280, "height": 720,
                       "ts": 100.0}).encode()
    srv = _FrameServer(body)
    try:
        monkeypatch.setattr(vc, "_vision_token", lambda: _TOKEN)
        monkeypatch.setattr(vc, "_FRAME_URL",
                            f"http://127.0.0.1:{srv.port}/latest-frame")
        out = vc.fetch_frame(_now=lambda: 102.5)
    finally:
        srv.close()
    assert out == {"ok": True, "b64": "QUJD", "width": 1280, "height": 720,
                   "format": "jpeg", "age_s": 2.5}
    assert srv.handler.seen_tokens == [_TOKEN]


def test_f4_a_relay_redirect_is_not_followed_with_the_token(monkeypatch):
    trap = _ProxyTrap()

    class _Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib name
            self.send_response(302)
            self.send_header("Location",
                             f"http://127.0.0.1:{trap.port}/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Redirect)
    t = threading.Thread(target=httpd.serve_forever, name="redirect-server",
                         daemon=True)
    t.start()
    try:
        monkeypatch.setattr(vc, "_vision_token", lambda: _TOKEN)
        monkeypatch.setattr(
            vc, "_FRAME_URL",
            f"http://127.0.0.1:{httpd.server_address[1]}/latest-frame")
        out = vc.fetch_frame(_now=lambda: 2.0)
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=2)
        trap.close()
    assert out["ok"] is False
    assert trap.received == b""


def test_f4_an_oversize_relay_body_is_refused(monkeypatch):
    # The first _FRAME_MAX_BYTES + 1 bytes are a complete, valid frame (the
    # rest is JSON whitespace), so only the size check can refuse it - a
    # truncated read alone would still parse.
    body = json.dumps({"b64": "A" * 64, "width": 1, "height": 1,
                       "ts": 1.0}).encode() + b" " * 4096
    srv = _FrameServer(body)
    try:
        monkeypatch.setattr(vc, "_vision_token", lambda: _TOKEN)
        monkeypatch.setattr(vc, "_FRAME_URL",
                            f"http://127.0.0.1:{srv.port}/latest-frame")
        monkeypatch.setattr(vc, "_FRAME_MAX_BYTES", 1024)
        out = vc.fetch_frame(_now=lambda: 2.0)
    finally:
        srv.close()
    assert out["ok"] is False
    assert "A" * 64 not in json.dumps(out)


# -- F5 frame fields: finite age, sane dimensions ------------------------------

def _frame(**fields):
    base = {"b64": "QUJD", "width": 1920, "height": 1080, "ts": 1.0}
    base.update(fields)
    return json.dumps(base).encode()


@pytest.mark.parametrize("ts", ["abc", None, [1], {"a": 1}, True])
def test_f5_a_junk_ts_keeps_the_frame(ts):
    out = vc.fetch_frame(_fetch=lambda: _frame(ts=ts), _now=lambda: 5.0)
    assert out["ok"] is True
    assert out["b64"] == "QUJD"
    assert out["age_s"] is None


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f5_a_non_finite_ts_gives_no_age_and_valid_json(tok):
    raw = _frame().replace(b'"ts": 1.0', b'"ts": ' + tok.encode())
    assert tok.encode() in raw
    out = vc.fetch_frame(_fetch=lambda: raw, _now=lambda: 5.0)
    assert out["ok"] is True
    assert out["age_s"] is None
    _strict(json.dumps(out).encode())


def test_f5_a_huge_now_minus_ts_stays_finite():
    out = vc.fetch_frame(_fetch=lambda: _frame(ts=-1e308),
                         _now=lambda: 1e308)
    assert out["age_s"] is None or math.isfinite(out["age_s"])


@pytest.mark.parametrize("w,h", [("1920", 1080), (True, 1080), (-5, 1080),
                                 (0, 1080), (1920.5, 1080), (1920, 10 ** 9)])
def test_f5_junk_dimensions_are_dropped_and_base_is_not_derived(w, h):
    out = vc.fetch_frame(_fetch=lambda: _frame(width=w, height=h),
                         _now=lambda: 5.0)
    assert out["ok"] is True
    good_w = type(w) is int and 0 < w <= 10000
    good_h = type(h) is int and 0 < h <= 10000
    assert out["width"] == (w if good_w else None)
    assert out["height"] == (h if good_h else None)


def test_f5_the_dimension_ceiling_itself_is_kept():
    out = vc.fetch_frame(
        _fetch=lambda: _frame(width=vc._COORD_MAX, height=vc._COORD_MAX),
        _now=lambda: 5.0)
    assert (out["width"], out["height"]) == (vc._COORD_MAX, vc._COORD_MAX)


@pytest.mark.parametrize("fmt,want", [
    ("jpeg", "jpeg"), ("png", "png"), (None, "jpeg"), (7, "jpeg"),
    ("png;base64,AAAA", "jpeg"), ("", "jpeg"), (["png"], "jpeg"),
])
def test_f5_frame_format_is_an_allow_listed_image_type(fmt, want):
    out = vc.fetch_frame(_fetch=lambda: _frame(format=fmt), _now=lambda: 5.0)
    assert out["format"] == want


def test_f4_a_module_imported_under_an_env_proxy_still_bypasses_it(
        monkeypatch):
    # A default ProxyHandler reads the environment when the opener is BUILT,
    # at import time - before the env-proxy test above sets HTTP_PROXY - so
    # that test alone cannot see one. Import a fresh copy of the module with
    # the proxy already in the environment (never registered in sys.modules).
    trap = _ProxyTrap()
    try:
        for k in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{trap.port}")
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{trap.port}")
        spec = importlib.util.spec_from_file_location("_rvc_fresh_s144",
                                                      vc.__file__)
        fresh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fresh)
        fresh._vision_token = lambda: _TOKEN
        fresh._FRAME_URL = f"http://127.0.0.1:{_free_port()}/latest-frame"
        out = fresh.fetch_frame()
    finally:
        trap.close()
    assert out["ok"] is False
    assert trap.received == b""


def test_f5_an_integral_float_dimension_counts():
    out = vc.fetch_frame(_fetch=lambda: _frame(width=1920.0, height=1080.0),
                         _now=lambda: 5.0)
    assert (out["width"], out["height"]) == (1920, 1080)
    assert type(out["width"]) is int


def _write_reference(tmp_path, monkeypatch, meta_text):
    monkeypatch.setattr(vp, "REFERENCE_DIR", tmp_path)
    monkeypatch.setattr(vp, "active_config_key", lambda: "cfg")
    (tmp_path / "cfg.jpg").write_bytes(b"\xff\xd8not-really-a-jpeg")
    if meta_text is not None:
        (tmp_path / "cfg.json").write_text(meta_text, encoding="utf-8")


@pytest.mark.parametrize("meta_text", [
    '{"width": 2560, "height": 1440, "ts": "abc"}',
    '{"width": 2560, "height": 1440, "ts": [1]}',
    '{"width": 2560, "height": 1440, "ts": true}',
    '{"width": 2560, "height": 1440, "ts": NaN}',
    '{"width": 2560, "height": 1440, "ts": 1e400}',
    '{"width": 2560, "height": 1440, "ts": 0}',
    '{"width": 2560, "height": 1440}',
])
def test_f5_reference_route_with_a_junk_sidecar_ts_has_no_age(
        meta_text, tmp_path, monkeypatch):
    _write_reference(tmp_path, monkeypatch, meta_text)
    h = _FakeHandler("/api/vision-frame?source=reference")
    vc._serve_frame_get(h)
    assert h.code == 200
    p = h.payload
    assert p["ok"] is True
    assert p["age_s"] is None
    assert p["base"] == [2560, 1440]


@pytest.mark.parametrize("meta_text", ["[1, 2]", '"x"', None, "{broken"])
def test_f5_reference_with_a_non_object_or_missing_sidecar_is_served(
        meta_text, tmp_path, monkeypatch):
    _write_reference(tmp_path, monkeypatch, meta_text)
    ref = vp.load_reference()
    assert ref["ok"] is True
    assert ref["width"] is None and ref["age_s"] is None


@pytest.mark.parametrize("tok", _NON_FINITE)
def test_f5_load_reference_itself_never_returns_a_non_finite_age(
        tok, tmp_path, monkeypatch):
    _write_reference(tmp_path, monkeypatch,
                     '{"width": 2560, "height": 1440, "ts": TOK}'.replace(
                         "TOK", tok))
    assert vp.load_reference()["age_s"] is None


def test_f5_load_reference_with_a_huge_integer_ts_has_no_age(tmp_path,
                                                            monkeypatch):
    _write_reference(tmp_path, monkeypatch,
                     '{"width": 2560, "height": 1440, "ts": 1' + "0" * 400
                     + "}")
    assert vp.load_reference()["age_s"] is None


@pytest.mark.parametrize("w,h", [(2560, "x"), ("x", 1440)])
def test_f5_reference_with_one_junk_dim_has_no_base(w, h, monkeypatch):
    ref = {"ok": True, "b64": "REF", "width": w, "height": h, "age_s": 1.0}
    monkeypatch.setattr(vp, "load_reference", lambda *a, **k: dict(ref))
    h_ = _FakeHandler("/api/vision-frame?source=reference")
    vc._serve_frame_get(h_)
    assert "base" not in h_.payload


def test_f5_a_zero_relay_ts_is_no_stamp_like_the_reference_route():
    out = vc.fetch_frame(_fetch=lambda: _frame(ts=0), _now=lambda: 5.0)
    assert out["age_s"] is None


def test_f4_the_relay_read_asks_for_at_most_the_cap_plus_one(monkeypatch):
    asked = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            asked.append(n)
            return _frame()

    class _Opener:
        def open(self, req, timeout=None):
            return _Resp()

    monkeypatch.setattr(vc, "_OPENER", _Opener())
    monkeypatch.setattr(vc, "_vision_token", lambda: _TOKEN)
    out = vc.fetch_frame(_now=lambda: 5.0)
    assert out["ok"] is True
    assert asked == [vc._FRAME_MAX_BYTES + 1]


def test_f5_legacy_seed_ignores_dims_of_a_failed_reference_load(monkeypatch):
    monkeypatch.setattr(vp, "load_profile", lambda *a, **k: {
        "source": "legacy_seed", "base": [1920, 1080],
        "regions": {"hp": [10, 20, 30, 40]}})
    monkeypatch.setattr(vp, "load_reference", lambda *a, **k: {
        "ok": False, "width": 1920, "height": 1080})
    h = _FakeHandler("/api/vision-regions?source=profile")
    vc._serve_regions_get(h)
    assert h.payload["base"] == [2560, 1440]


def test_f5_reference_with_a_real_ts_still_reports_its_age(tmp_path,
                                                           monkeypatch):
    _write_reference(tmp_path, monkeypatch,
                     '{"width": 2560, "height": 1440, "ts": 1000.0}')
    monkeypatch.setattr(vp.time, "time", lambda: 1012.34)
    assert vp.load_reference()["age_s"] == 12.3


@pytest.mark.parametrize("width,want", [("abc", [2560, 1440]),
                                        (None, [2560, 1440]),
                                        (1920.0, [1920, 1080]),
                                        (1920, [1920, 1080])])
def test_f5_legacy_seed_scaling_never_raises_on_junk_reference_dims(
        width, want, monkeypatch):
    monkeypatch.setattr(vp, "load_profile", lambda *a, **k: {
        "source": "legacy_seed", "base": [1920, 1080],
        "regions": {"hp": [10, 20, 30, 40]}})
    monkeypatch.setattr(vp, "load_reference", lambda *a, **k: {
        "ok": True, "width": width, "height": 1080})
    h = _FakeHandler("/api/vision-regions?source=profile")
    vc._serve_regions_get(h)
    assert h.code == 200
    assert h.payload["base"] == want


def test_f5_reference_states_listing_drops_junk_dims(monkeypatch):
    refs = {"base": {"ok": True, "width": float("nan"), "height": 1440},
            "hover": {"ok": True, "width": 2560, "height": "1440"}}
    monkeypatch.setattr(vp, "list_reference_states",
                        lambda *a, **k: ["base", "hover"])
    monkeypatch.setattr(vp, "load_reference",
                        lambda *a, state=None, **k: dict(refs[state or "base"]))
    h = _FakeHandler("/api/vision-reference-states")
    vc._serve_reference_states_get(h)
    assert h.code == 200
    assert h.payload["states"] == [
        {"state": "base", "exists": True, "width": None, "height": 1440},
        {"state": "hover", "exists": True, "width": 2560, "height": None},
    ]


def test_f5_frame_get_without_dims_carries_no_base(monkeypatch):
    real = vc.fetch_frame
    monkeypatch.setattr(vc, "fetch_frame", lambda: real(
        _fetch=lambda: _frame(width="x", height=1080), _now=lambda: 5.0))
    h = _FakeHandler("/api/vision-frame")
    vc._serve_frame_get(h)
    assert h.code == 200
    assert "base" not in h.payload


@pytest.mark.parametrize("b64", [123, ["QUJD"], {"x": 1}, True])
def test_f5_a_non_string_b64_is_no_frame(b64):
    out = vc.fetch_frame(_fetch=lambda: _frame(b64=b64), _now=lambda: 5.0)
    assert out == {"ok": False, "error": "no frame available yet"}


def test_f5_a_non_object_relay_body_is_friendly():
    out = vc.fetch_frame(_fetch=lambda: b"[1, 2, 3]", _now=lambda: 5.0)
    assert out["ok"] is False


def test_f5_reference_frame_with_nan_age_is_valid_json(monkeypatch):
    ref = {"ok": True, "b64": "REF", "width": 2560, "height": 1440,
           "age_s": float("nan"), "config_key": "cfg", "format": "jpeg"}
    monkeypatch.setattr(vp, "load_reference", lambda *a, **k: dict(ref))
    h = _FakeHandler("/api/vision-frame?source=reference")
    vc._serve_frame_get(h)
    assert h.code == 200
    p = h.payload
    assert p["ok"] is True
    assert p["age_s"] is None
    assert p["base"] == [2560, 1440]


def test_f5_reference_frame_with_junk_dims_has_no_base(monkeypatch):
    ref = {"ok": True, "b64": "REF", "width": "2560", "height": None,
           "age_s": 3.0}
    monkeypatch.setattr(vp, "load_reference", lambda *a, **k: dict(ref))
    h = _FakeHandler("/api/vision-frame?source=reference")
    vc._serve_frame_get(h)
    p = h.payload
    assert p["ok"] is True
    assert p["width"] is None and p["height"] is None
    assert "base" not in p
    assert p["age_s"] == 3.0


# -- F6 load_regions shape -----------------------------------------------------

@pytest.mark.parametrize("text", ['[1, 2, 3]', '"hp"', "7", "null", "true"])
def test_f6_a_non_object_regions_file_loads_as_empty(text, tmp_path):
    p = tmp_path / "vision_regions.json"
    p.write_text(text, encoding="utf-8")
    assert vc.load_regions(path=p) == {}


def test_f6_undecodable_or_broken_file_loads_as_empty(tmp_path):
    p = tmp_path / "vision_regions.json"
    p.write_bytes(b"\xff\xfe\x00garbage")
    assert vc.load_regions(path=p) == {}
    p.write_text("{not json", encoding="utf-8")
    assert vc.load_regions(path=p) == {}


def test_f6_get_regions_with_a_list_file_answers_an_empty_object(
        tmp_path, monkeypatch):
    p = tmp_path / "vision_regions.json"
    p.write_text("[1, 2]", encoding="utf-8")
    monkeypatch.setattr(vc, "REGIONS_PATH", p)
    h = _FakeHandler("/api/vision-regions")
    vc._serve_regions_get(h)
    assert h.code == 200
    assert h.payload == {"ok": True, "regions": {}}


def test_f6_load_regions_does_not_swallow_a_programming_error(monkeypatch,
                                                              tmp_path):
    p = tmp_path / "vision_regions.json"
    p.write_text("{}", encoding="utf-8")

    def _boom(*a, **k):
        raise TypeError("programming error")
    # The module's own `json` binding, never the process-wide json.loads.
    monkeypatch.setattr(vc, "json", types.SimpleNamespace(loads=_boom))
    with pytest.raises(TypeError):
        vc.load_regions(path=p)


# -- F7 responses are always strict JSON ---------------------------------------

def test_f7_get_regions_with_a_nan_file_is_valid_json(tmp_path, monkeypatch):
    p = tmp_path / "vision_regions.json"
    p.write_text('{"hp": [NaN, 0, 1, 1]}', encoding="utf-8")
    monkeypatch.setattr(vc, "REGIONS_PATH", p)
    h = _FakeHandler("/api/vision-regions")
    vc._serve_regions_get(h)
    payload = h.payload  # strict parse; raises on a bare NaN token
    assert payload["ok"] is False
    assert h.code == 500


def test_f7_send_json_never_emits_a_bare_nan():
    h = _FakeHandler()
    with pytest.raises(ValueError):
        vc._send_json(h, 200, {"x": float("nan")})
    assert h.sent is None
