"""Lane 8 true-audit (s144 cycle 100) of core/replay_camera.py.

One test group per finding (F1-F18). Each finding has tests that were RED
against the module as it stood on main before this cycle. The tests named
"control" pin behaviour that must not change, and pass there unless they read a
field that is new; a few F10 and F13 cases pass there too, because the old code
refused that one input by accident. The transport is a fake or a throwaway
server on an ephemeral loopback port, so nothing here touches a running client.
Every value is synthetic.
"""
from __future__ import annotations

import http.client
import http.server
import importlib.util
import io
import json
import math
import ssl
import sys
import threading
import urllib.error
import urllib.request

import pytest

from core import replay_camera as rc

GOOD_RENDER = {
    "cameraPosition": {"x": 9000.0, "y": 1900.0, "z": 800.0},
    "cameraRotation": {"x": 15.0, "y": 50.0, "z": 0.0},
    "fieldOfView": 60.0,
    "cameraMode": "fps",
}
FLT_MAX_TEXT = "340282346638528859811704183484516925440.0000000"


class _Resp:
    """A stand-in for an http.client response."""

    def __init__(self, body: bytes):
        self.body = body
        self.closed = False
        self.read_sizes = []

    def read(self, n=-1):
        self.read_sizes.append(n)
        if n is None or n < 0:
            return self.body
        return self.body[:n]

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _Wire:
    """Serves queued results; records every request and open timeout."""

    def __init__(self, *results):
        self.results = list(results)
        self.requests = []
        self.timeouts = []
        self.responses = []

    def _next(self):
        if not self.results:
            return json.dumps(GOOD_RENDER).encode("utf-8")
        return self.results.pop(0)

    def open(self, req, timeout=None, **_kw):
        self.requests.append(req)
        self.timeouts.append(timeout)
        item = self._next()
        if isinstance(item, BaseException):
            raise item
        resp = _Resp(item)
        self.responses.append(resp)
        return resp

    def posts(self) -> list:
        return [json.loads(r.data.decode("utf-8"))
                for r in self.requests if r.get_method() == "POST"]


@pytest.fixture
def wire(monkeypatch):
    """Patches BOTH transport seams, so the same test reads the module as it
    stood (module-level urlopen) and as it stands now (private opener)."""

    def install(*results) -> _Wire:
        fake = _Wire(*results)
        monkeypatch.setattr(urllib.request, "urlopen", fake.open)
        monkeypatch.setattr(rc, "_OPENER", fake, raising=False)
        return fake

    return install


@pytest.fixture
def no_sleep(monkeypatch):
    calls = []
    monkeypatch.setattr(rc.time, "sleep", calls.append)
    return calls


def _client(**kw) -> rc.RenderClient:
    kw.setdefault("settle_s", 0)
    return rc.RenderClient(**kw)


# --------------------------------------------- F1 responses are closed

def test_f1_post_closes_its_response(wire, no_sleep):
    w = wire(b"{}")
    _client()._post("/replay/render", {"a": 1})
    assert w.responses[0].closed is True


def test_f1_control_get_closes_its_response(wire):
    w = wire(b"{}")
    _client().get_render()
    assert w.responses[0].closed is True


def test_f1_an_http_error_body_is_closed(wire):
    body = io.BytesIO(b"nope")
    err = urllib.error.HTTPError("https://x/", 404, "gone", {}, body)
    wire(err)
    with pytest.raises(rc.RenderError):
        _client().get_render()
    assert body.closed


# ------------------------------------------------- F2 reads are capped

def test_f2_get_never_asks_for_more_than_the_cap(wire):
    w = wire(b"{}")
    _client().get_render()
    assert w.responses[0].read_sizes == [rc.MAX_BODY_BYTES + 1]


def test_f2_post_never_asks_for_more_than_the_cap(wire, no_sleep):
    w = wire(b"{}")
    _client()._post("/replay/render", {"a": 1})
    assert w.responses[0].read_sizes == [rc.MAX_BODY_BYTES + 1]


def test_f2_an_oversized_body_is_a_render_error(wire):
    # The capped prefix of this body is itself valid JSON once padded, so only
    # the length check can refuse it.
    body = b"{}" + b" " * rc.MAX_BODY_BYTES
    wire(body)
    with pytest.raises(rc.RenderError, match="exceeds"):
        _client().get_render()


def test_f2_a_body_exactly_at_the_cap_is_read(wire):
    wire(b"{}" + b" " * (rc.MAX_BODY_BYTES - 2))
    assert _client().get_render() == {}


# -------------------------------------------- F3 failures are typed

@pytest.mark.parametrize("failure", [
    urllib.error.URLError("refused"),
    urllib.error.HTTPError("https://x/", 404, "gone", {}, io.BytesIO(b"")),
    TimeoutError("timed out"),
    ConnectionResetError("reset"),
    http.client.IncompleteRead(b""),
])
def test_f3_a_transport_failure_is_a_render_error(wire, failure):
    wire(failure)
    with pytest.raises(rc.RenderError):
        _client().get_render()


def test_f3_a_post_transport_failure_is_a_render_error_and_never_settles(
        wire, no_sleep):
    wire(urllib.error.URLError("refused"))
    with pytest.raises(rc.RenderError):
        _client(settle_s=1)._post("/replay/render", {"a": 1})
    assert no_sleep == []


@pytest.mark.parametrize("body", [
    b"not json", b"", b"\xff\xfe\xfa", b"[" * 200000,
], ids=["not-json", "empty", "not-utf8", "deep-nesting"])
def test_f3_an_unreadable_body_is_a_render_error(wire, body):
    wire(body)
    with pytest.raises(rc.RenderError):
        _client().get_render()


@pytest.mark.parametrize("body", [b"[]", b"7", b"null", b'"fps"', b"true"])
def test_f3_a_body_that_is_not_an_object_is_a_render_error(wire, body):
    wire(body)
    with pytest.raises(rc.RenderError):
        _client().get_render()


def test_f3_the_render_error_keeps_its_cause(wire):
    cause = urllib.error.URLError("refused")
    wire(cause)
    with pytest.raises(rc.RenderError) as got:
        _client().get_render()
    assert got.value.__cause__ is cause


# -------------------- F4 a loopback call never leaves through a proxy

class _Handler(http.server.BaseHTTPRequestHandler):
    def _send_short_body(self):
        # Declares more than it sends, then the connection closes.
        body = json.dumps(GOOD_RENDER).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body) + 500))
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.hits.append(self.path)
        if self.server.short_body:
            self._send_short_body()
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.server.hits.append(self.path)
        if self.server.short_body:
            self._send_short_body()
            return
        if self.path == "/replay/render" and self.server.redirect:
            self.send_response(302)
            self.send_header("Location", "/stolen")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.dumps(GOOD_RENDER).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.hits = []
    srv.redirect = False
    srv.short_body = False
    thread = threading.Thread(target=srv.serve_forever, name="s144-render",
                              daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def _base(srv) -> str:
    return f"http://127.0.0.1:{srv.server_address[1]}"


def test_f4_a_proxy_in_the_environment_is_ignored(server, monkeypatch):
    # With this environment urllib's default opener sends a 127.0.0.1 request
    # to the proxy: urllib.request.proxy_bypass("127.0.0.1") reads False.
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    # A fresh copy of the module, because the opener is built at import: the
    # already imported one read its proxies before this environment existed.
    spec = importlib.util.spec_from_file_location("_rc_proxy_probe", rc.__file__)
    fresh = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, fresh)
    spec.loader.exec_module(fresh)
    got = fresh.RenderClient(base=_base(server), timeout_s=5,
                             settle_s=0).get_render()
    assert got["cameraMode"] == "fps"
    assert server.hits == ["/replay/render"]


def test_f4_control_a_real_exchange_parses_a_real_body(server):
    cam = rc.camera_from(_client(base=_base(server), timeout_s=5).get_render())
    assert (cam.x, cam.y, cam.z) == (9000.0, 1900.0, 800.0)


# -------------------------------------------- F5 redirects are refused

def test_f5_a_redirect_is_refused_and_never_followed(server):
    server.redirect = True
    with pytest.raises(rc.RenderError):
        _client(base=_base(server), timeout_s=5).get_render()
    assert server.hits == ["/replay/render"]


# ----------------------------------- F16 a truncated body is a failure

def test_f16_a_get_shorter_than_its_content_length_is_refused(server):
    # read(amount) returns a short body without IncompleteRead, and this one
    # is complete JSON, so nothing else can notice.
    server.short_body = True
    with pytest.raises(rc.RenderError, match="shorter"):
        _client(base=_base(server), timeout_s=5).get_render()


def test_f16_a_post_shorter_than_its_content_length_is_refused(server, no_sleep):
    server.short_body = True
    with pytest.raises(rc.RenderError, match="shorter"):
        _client(base=_base(server), timeout_s=5)._post("/replay/render", {"a": 1})
    assert no_sleep == []


def test_f16_control_a_post_with_an_empty_body_succeeds(server, no_sleep):
    _client(base=_base(server), timeout_s=5)._post("/replay/render", {"a": 1})
    assert server.hits == ["/replay/render"]
    assert len(no_sleep) == 1


# -------------------------------- F17 a send-time encoding failure is typed

@pytest.mark.parametrize("base", [
    "http://" + "a" * 64 + ".invalid",   # an IDNA label over 63 characters
    "http://127.0.0.1:1/" + chr(0xe9),   # a path the request line cannot encode
], ids=["long-host-label", "non-ascii-path"])
def test_f17_a_base_that_cannot_be_sent_is_a_render_error(base):
    with pytest.raises(rc.RenderError):
        _client(base=base, timeout_s=1).get_render()


# ------------------------------------- F18 the TLS context is really wired

def test_f18_the_opener_uses_the_loopback_tls_context():
    # Production's base is https, and a default context would refuse the
    # client's self-signed cert. The fake and plain-http tests cannot see this.
    handlers = [h for h in rc._OPENER.handlers
                if isinstance(h, urllib.request.HTTPSHandler)]
    assert len(handlers) == 1
    assert handlers[0]._context is rc._CTX
    assert rc._CTX.verify_mode == ssl.CERT_NONE


# ------------------------------------------ F6 RenderClient configuration

@pytest.mark.parametrize("wait", [1e308, 3600.5])
def test_f6_an_absurd_wait_is_refused_at_construction(wait):
    # Either would raise OverflowError later: the timeout at send time, the
    # settle only after the write had gone out.
    with pytest.raises(ValueError):
        rc.RenderClient(timeout_s=wait)
    with pytest.raises(ValueError):
        rc.RenderClient(settle_s=wait)


def test_f6_control_the_longest_wait_is_allowed():
    client = rc.RenderClient(timeout_s=3600.0, settle_s=3600.0)
    assert (client.timeout_s, client.settle_s) == (3600.0, 3600.0)


@pytest.mark.parametrize("base", [
    "file:///tmp/x", "ftp://127.0.0.1", "127.0.0.1:2999", "https://", "", None,
    7,
])
def test_f6_a_bad_base_is_refused_at_construction(base):
    with pytest.raises(ValueError):
        rc.RenderClient(base=base)


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf, True, "5",
                                     None, 10**400])
def test_f6_a_bad_timeout_is_refused_at_construction(timeout):
    with pytest.raises(ValueError):
        rc.RenderClient(timeout_s=timeout)


@pytest.mark.parametrize("settle", [-1, math.nan, math.inf, True, "1", None])
def test_f6_a_bad_settle_is_refused_at_construction(settle):
    with pytest.raises(ValueError):
        rc.RenderClient(settle_s=settle)


@pytest.mark.parametrize("base", ["https://127.0.0.1:2999/",
                                  "http://127.0.0.1:2999"])
def test_f6_control_good_bases_are_kept_without_the_trailing_slash(base):
    assert rc.RenderClient(base=base).base == base.rstrip("/")


def test_f6_control_a_zero_settle_is_allowed():
    assert rc.RenderClient(settle_s=0).settle_s == 0


def test_f6_control_the_timeout_reaches_the_wire(wire):
    w = wire(b"{}")
    _client(timeout_s=3.5).get_render()
    assert w.timeouts == [3.5]


# --------------------------------------- F7 camera_from never fabricates

@pytest.mark.parametrize("render", [None, {}, [], "fps", 7])
def test_f7_a_render_without_a_camera_is_refused_not_zeroed(render):
    with pytest.raises(rc.RenderError):
        rc.camera_from(render)


@pytest.mark.parametrize("position", [
    None, [], "here", {}, {"x": 1.0, "y": 2.0}, {"x": 1.0, "z": 3.0},
    {"x": None, "y": 2.0, "z": 3.0}, {"x": "east", "y": 2.0, "z": 3.0},
    {"x": math.nan, "y": 2.0, "z": 3.0}, {"x": 1.0, "y": math.inf, "z": 3.0},
    {"x": True, "y": 2.0, "z": 3.0}, {"x": 10**400, "y": 2.0, "z": 3.0},
    {"x": "1_000", "y": 2.0, "z": 3.0}, {"x": "nan", "y": 2.0, "z": 3.0},
    {"x": {}, "y": 2.0, "z": 3.0},
])
def test_f7_a_malformed_position_is_refused(position):
    with pytest.raises(rc.RenderError):
        rc.camera_from({"cameraPosition": position, "fieldOfView": 60.0})


def test_f7_control_a_camera_really_at_zero_is_read():
    cam = rc.camera_from({"cameraPosition": {"x": 0, "y": 0.0, "z": 0}})
    assert (cam.x, cam.y, cam.z) == (0.0, 0.0, 0.0)


def test_f7_control_numeric_string_axes_still_read():
    cam = rc.camera_from({"cameraPosition": {"x": "12.5", "y": "3", "z": "4"}})
    assert (cam.x, cam.y, cam.z) == (12.5, 3.0, 4.0)


@pytest.mark.parametrize("fov", ["wide", math.nan, math.inf, -1.0, True, {}])
def test_f7_a_malformed_fov_is_refused(fov):
    with pytest.raises(rc.RenderError):
        rc.camera_from({**GOOD_RENDER, "fieldOfView": fov})


@pytest.mark.parametrize("render", [
    {"cameraPosition": GOOD_RENDER["cameraPosition"]},
    {"cameraPosition": GOOD_RENDER["cameraPosition"], "fieldOfView": None},
])
def test_f7_control_an_absent_fov_reads_as_unknown(render):
    assert rc.camera_from(render).fov == 0.0


@pytest.mark.parametrize("mode", [{"a": 1}, ["fps"], 7, True])
def test_f7_a_non_string_mode_reads_empty_not_its_repr(mode):
    assert rc.camera_from({**GOOD_RENDER, "cameraMode": mode}).mode == ""


def test_f7_control_a_string_mode_is_kept():
    assert rc.camera_from(GOOD_RENDER).mode == "fps"


# ------------------------------- F8 the camera's own rotation is carried

def test_f8_camera_from_carries_yaw_and_pitch():
    cam = rc.camera_from(GOOD_RENDER)
    assert (cam.yaw, cam.pitch) == (15.0, 50.0)


@pytest.mark.parametrize("rotation", [
    "tilted", [], {"x": "left", "y": 50.0}, {"x": 15.0, "y": math.nan},
    {"x": True, "y": 50.0},
])
def test_f8_a_malformed_rotation_is_refused(rotation):
    with pytest.raises(rc.RenderError):
        rc.camera_from({**GOOD_RENDER, "cameraRotation": rotation})


def test_f8_control_an_absent_rotation_reads_as_unknown():
    render = {k: v for k, v in GOOD_RENDER.items() if k != "cameraRotation"}
    cam = rc.camera_from(render)
    assert (cam.yaw, cam.pitch) == (None, None)


def test_f8_the_solve_uses_the_rotation_the_camera_reported():
    # A real render pose must drive both directions without the caller
    # restating it: this camera is yawed 15 and pitched 50, not 0 and 56.
    cam = rc.camera_from({**GOOD_RENDER, "cameraPosition":
                          {"x": 7000.0, "y": 4000.0, "z": 3000.0}})
    intr = rc.LEGION_2560x1440_FOV60
    want = rc.map_to_screen(cam, 7500.0, 6000.0, intr, 15.0, 50.0)
    assert rc.map_to_screen(cam, 7500.0, 6000.0, intr) == want
    assert rc.screen_to_map(cam, want, intr) == rc.screen_to_map(
        cam, want, intr, 15.0, 50.0)
    back = rc.screen_to_map(cam, want, intr)
    assert abs(back[0] - 7500.0) < 1.0
    assert abs(back[1] - 6000.0) < 1.0


def test_f8_an_explicit_pose_beats_the_reported_one():
    cam = rc.camera_from({**GOOD_RENDER, "cameraPosition":
                          {"x": 7000.0, "y": 4000.0, "z": 3000.0}})
    intr = rc.LEGION_2560x1440_FOV60
    assert rc.map_to_screen(cam, 7500.0, 6000.0, intr, 0.0, 56.0) != \
        rc.map_to_screen(cam, 7500.0, 6000.0, intr)
    assert rc.map_to_screen(cam, 7500.0, 6000.0, intr, 0.0, 56.0) == \
        rc.map_to_screen(cam, 7500.0, 6000.0, intr, yaw_deg=0.0, pitch_deg=56.0)


def test_f8_control_a_camera_with_no_rotation_uses_the_measured_defaults():
    cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=60.0)
    intr = rc.LEGION_2560x1440_FOV60
    assert rc.map_to_screen(cam, 7500.0, 6000.0, intr) == rc.map_to_screen(
        cam, 7500.0, 6000.0, intr, 0.0, 56.0)
    pixel = rc.ScreenPos(1400.0, 900.0)
    assert rc.screen_to_map(cam, pixel, intr) == rc.screen_to_map(
        cam, pixel, intr, 0.0, 56.0)


def test_f8_a_reported_pitch_of_zero_is_not_treated_as_unknown():
    # A level camera has a real reading of 0: it must not fall to the default.
    # It sits well above the point and looks along +z, so the point is in view.
    level = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=60.0,
                           yaw=0.0, pitch=0.0)
    intr = rc.LEGION_2560x1440_FOV60
    assert rc.map_to_screen(level, 7500.0, 6000.0, intr) == rc.map_to_screen(
        level, 7500.0, 6000.0, intr, 0.0, 0.0)
    assert rc.map_to_screen(level, 7500.0, 6000.0, intr) != rc.map_to_screen(
        level, 7500.0, 6000.0, intr, 0.0, rc.DEFAULT_PITCH_DEG)


def test_f8_an_explicit_yaw_of_zero_beats_the_reported_yaw():
    cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=60.0,
                         yaw=20.0, pitch=56.0)
    intr = rc.LEGION_2560x1440_FOV60
    assert rc.map_to_screen(cam, 7500.0, 6000.0, intr, yaw_deg=0.0) != \
        rc.map_to_screen(cam, 7500.0, 6000.0, intr)


# --------------------------------- F9 intrinsics match the view they solve

def test_f9_the_legion_intrinsics_declare_their_fov():
    assert rc.LEGION_2560x1440_FOV60.fov == 60.0


def test_f9_the_solve_refuses_intrinsics_from_another_fov():
    # 40.0 is the client's default fieldOfView, the shipped solve is for 60.
    cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=40.0)
    intr = rc.LEGION_2560x1440_FOV60
    with pytest.raises(ValueError, match="fieldOfView"):
        rc.screen_to_map(cam, rc.ScreenPos(1400.0, 900.0), intr)
    with pytest.raises(ValueError, match="fieldOfView"):
        rc.map_to_screen(cam, 7500.0, 6000.0, intr)


@pytest.mark.parametrize("fov", [math.nan, -60.0])
def test_f9_an_impossible_camera_fov_is_refused_not_skipped(fov):
    # NaN passed every "> 0" guard, so the check was skipped and a point came
    # back. Only 0.0 means unknown.
    cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=fov)
    intr = rc.LEGION_2560x1440_FOV60
    with pytest.raises(ValueError, match="fieldOfView"):
        rc.screen_to_map(cam, rc.ScreenPos(1400.0, 900.0), intr)
    with pytest.raises(ValueError, match="fieldOfView"):
        rc.map_to_screen(cam, 7500.0, 6000.0, intr)


def test_f9_control_an_unknown_fov_on_either_side_is_not_checked():
    unknown_cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=0.0)
    pixel = rc.ScreenPos(1400.0, 900.0)
    assert rc.screen_to_map(unknown_cam, pixel,
                            rc.LEGION_2560x1440_FOV60) is not None
    known_cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=40.0)
    no_fov = rc.Intrinsics(1259.0, 735.0, 1291.0)
    assert rc.screen_to_map(known_cam, pixel, no_fov) is not None


@pytest.mark.parametrize("kw", [
    {"focal_px": 0.0}, {"focal_px": -1291.0}, {"focal_px": math.nan},
    {"focal_px": math.inf}, {"principal_x": math.nan},
    {"principal_y": math.inf}, {"ground_y": math.nan}, {"fov": -1.0},
    {"fov": math.nan}, {"focal_px": True}, {"focal_px": "1291"},
])
def test_f9_impossible_intrinsics_are_refused_at_construction(kw):
    args = {"principal_x": 1259.0, "principal_y": 735.0, "focal_px": 1291.0}
    args.update(kw)
    with pytest.raises(ValueError):
        rc.Intrinsics(**args)


def test_f9_control_the_new_field_is_last_and_optional():
    intr = rc.Intrinsics(1.0, 2.0, 3.0, 4.0)
    assert (intr.principal_x, intr.principal_y, intr.focal_px, intr.ground_y,
            intr.fov) == (1.0, 2.0, 3.0, 4.0, 0.0)


# ----------------------------------------------- F10 parse_screen_pos

@pytest.mark.parametrize("raw", [
    "nan,nan", "nan,1", "1,nan", "NaN,NaN", "inf,1", "1,-inf", "1_000,2",
    "1,2_000", "0x10,2", "1e400,2", ",", "1,", ",1", "1,2,3",
    # Arabic-Indic digits: float() takes them, the wire never sends them.
    chr(0x661) + chr(0x662) + "," + chr(0x663),
    f"{FLT_MAX_TEXT},12.5", f"12.5,{FLT_MAX_TEXT}", f"-{FLT_MAX_TEXT},12.5",
])
def test_f10_a_non_position_reads_as_none(raw):
    assert rc.parse_screen_pos(raw) is None


@pytest.mark.parametrize("raw,want", [
    ("12.5,7.25", (12.5, 7.25)), (" 12.5 , 7.25 ", (12.5, 7.25)),
    ("-3.5,0", (-3.5, 0.0)), ("1e2,2", (100.0, 2.0)),
])
def test_f10_control_real_positions_parse(raw, want):
    got = rc.parse_screen_pos(raw)
    assert (got.x, got.y) == want


# ---------------------------------------------------- F11 solve_scale

def test_f11_a_camera_still_on_z_gets_no_scale_not_a_zero_one():
    # The docstring promises None when the camera did not move on an axis.
    # This returned (10.0, -0.0), and back_project then collapsed every
    # champion onto the camera's own z with a numeric-looking answer.
    a = rc.CameraState(x=1000.0, y=1900.0, z=2000.0, fov=40.0)
    b = rc.CameraState(x=1100.0, y=1900.0, z=2000.0, fov=40.0)
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          b, rc.ScreenPos(490.0, 400.5)) is None


def test_f11_a_camera_still_on_x_gets_no_scale_not_a_zero_one():
    a = rc.CameraState(x=1000.0, y=1900.0, z=2000.0, fov=40.0)
    b = rc.CameraState(x=1000.0, y=1900.0, z=2100.0, fov=40.0)
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          b, rc.ScreenPos(490.5, 390.0)) is None


def test_f11_control_a_champion_that_did_not_slide_gets_no_scale():
    a = rc.CameraState(x=1000.0, y=1900.0, z=2000.0, fov=40.0)
    b = rc.CameraState(x=1100.0, y=1900.0, z=2100.0, fov=40.0)
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          b, rc.ScreenPos(500.0, 390.0)) is None
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          b, rc.ScreenPos(490.0, 400.0)) is None


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_f11_a_non_finite_input_gets_no_scale(bad):
    a = rc.CameraState(x=1000.0, y=1900.0, z=2000.0, fov=40.0)
    b = rc.CameraState(x=1100.0, y=1900.0, z=2100.0, fov=40.0)
    assert rc.solve_scale(a, rc.ScreenPos(bad, 400.0),
                          b, rc.ScreenPos(490.0, 390.0)) is None
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          b, rc.ScreenPos(490.0, bad)) is None
    moved = rc.CameraState(x=bad, y=1900.0, z=2100.0, fov=40.0)
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          moved, rc.ScreenPos(490.0, 390.0)) is None


def test_f11_a_scale_that_overflows_is_none_not_infinite():
    a = rc.CameraState(x=0.0, y=1900.0, z=0.0, fov=40.0)
    b = rc.CameraState(x=1e308, y=1900.0, z=10.0, fov=40.0)
    assert rc.solve_scale(a, rc.ScreenPos(500.0, 400.0),
                          b, rc.ScreenPos(500.001, 390.0)) is None


# ---------------------------------------------------- F12 back_project

def test_f12_a_non_finite_result_is_none_not_a_coordinate():
    cam = rc.CameraState(x=7000.0, y=1900.0, z=7000.0, fov=40.0)
    centre = rc.ScreenPos(960.0, 540.0)
    pixel = rc.ScreenPos(1060.0, 640.0)
    assert rc.back_project(cam, pixel, centre, (math.nan, 10.0)) is None
    assert rc.back_project(cam, pixel, centre, (10.0, math.inf)) is None
    assert rc.back_project(cam, rc.ScreenPos(math.nan, 640.0), centre,
                           (10.0, 10.0)) is None


def test_f12_control_a_missing_scale_stays_a_loud_type_error():
    # solve_scale's None must never become a coordinate.
    cam = rc.CameraState(x=7000.0, y=1900.0, z=7000.0, fov=40.0)
    centre = rc.ScreenPos(960.0, 540.0)
    with pytest.raises(TypeError):
        rc.back_project(cam, centre, centre, None)


# ---------------------------------------- F13 geometry on bad numbers

@pytest.mark.parametrize("pixel", [
    rc.ScreenPos(math.nan, 900.0), rc.ScreenPos(1400.0, math.nan),
    rc.ScreenPos(math.inf, 900.0), rc.ScreenPos(1400.0, -math.inf),
])
def test_f13_screen_to_map_never_returns_a_non_finite_point(pixel):
    cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=60.0)
    assert rc.screen_to_map(cam, pixel, rc.LEGION_2560x1440_FOV60) is None


@pytest.mark.parametrize("field", ["x", "y", "z"])
def test_f13_a_non_finite_camera_has_no_map_point(field):
    args = {"x": 7000.0, "y": 4000.0, "z": 3000.0, "fov": 60.0, field: math.nan}
    cam = rc.CameraState(**args)
    assert rc.screen_to_map(cam, rc.ScreenPos(1400.0, 900.0),
                            rc.LEGION_2560x1440_FOV60) is None


@pytest.mark.parametrize("map_x,map_z", [
    (math.nan, 6000.0), (7500.0, math.nan), (math.inf, 6000.0),
])
def test_f13_map_to_screen_never_returns_a_non_finite_pixel(map_x, map_z):
    cam = rc.CameraState(x=7000.0, y=4000.0, z=3000.0, fov=60.0)
    assert rc.map_to_screen(cam, map_x, map_z,
                            rc.LEGION_2560x1440_FOV60) is None


@pytest.mark.parametrize("field", ["x", "y", "z"])
def test_f13_a_non_finite_camera_has_no_pixel(field):
    args = {"x": 7000.0, "y": 4000.0, "z": 3000.0, "fov": 60.0, field: math.nan}
    cam = rc.CameraState(**args)
    assert rc.map_to_screen(cam, 7500.0, 6000.0,
                            rc.LEGION_2560x1440_FOV60) is None


def test_f13_control_a_camera_below_the_ground_has_no_map_point():
    cam = rc.CameraState(x=7000.0, y=10.0, z=3000.0, fov=60.0)
    assert rc.screen_to_map(cam, rc.ScreenPos(1400.0, 900.0),
                            rc.LEGION_2560x1440_FOV60) is None


@pytest.mark.parametrize("yaw,pitch", [
    (math.nan, 56.0), (0.0, math.nan), (math.inf, 56.0), (0.0, -math.inf),
    (True, 56.0), ("0", 56.0), (None, 56.0),
])
def test_f13_a_bad_angle_is_a_value_error_from_camera_basis(yaw, pitch):
    with pytest.raises(ValueError):
        rc.camera_basis(yaw, pitch)


@pytest.mark.parametrize("height,pitch", [
    (1911.0, 0.0), (1911.0, -56.0), (1911.0, 91.0), (1911.0, 180.0),
    (1911.0, math.nan), (1911.0, math.inf), (-1.0, 56.0), (math.nan, 56.0),
    (math.inf, 56.0), (True, 56.0), (1911.0, None),
    (1.0, 5e-324), (1.0, 1e-320), (1e308, 1e-3),   # zero or infinite distance
])
def test_f13_look_at_offset_refuses_a_camera_that_never_meets_the_ground(
        height, pitch):
    with pytest.raises(ValueError):
        rc.look_at_offset(height, pitch)


def test_f13_control_look_at_offset_edges_are_kept():
    assert rc.look_at_offset(0.0, 56.0) == 0.0
    assert abs(rc.look_at_offset(1911.0, 90.0)) < 1e-9


# --------------------------------------------- F14 set_camera arguments

@pytest.mark.parametrize("x,y,z", [
    (math.nan, 1.0, 2.0), (1.0, math.inf, 2.0), (1.0, 2.0, -math.inf),
    (True, 1.0, 2.0), ("1", 1.0, 2.0), (None, 1.0, 2.0), (10**400, 1.0, 2.0),
    (1.0, True, 2.0), (1.0, "2", 2.0), (1.0, 2.0, True), (1.0, 2.0, "3"),
])
def test_f14_a_bad_coordinate_is_refused_before_any_write(wire, no_sleep,
                                                          x, y, z):
    w = wire()
    with pytest.raises(ValueError):
        _client().set_camera(x, y, z)
    assert w.requests == []


def test_f14_control_set_camera_writes_then_reads_back_what_landed(
        wire, no_sleep):
    landed = {**GOOD_RENDER, "cameraPosition": {"x": 5.0, "y": 6.0, "z": 7.0}}
    w = wire(b"{}", json.dumps(landed).encode("utf-8"))
    cam = _client().set_camera(1, 2, 3)
    assert w.posts() == [{"cameraPosition": {"x": 1.0, "y": 2.0, "z": 3.0}}]
    assert (cam.x, cam.y, cam.z) == (5.0, 6.0, 7.0)


def test_f14_control_a_write_settles_after_it_is_sent(wire, no_sleep):
    wire(b"{}", json.dumps(GOOD_RENDER).encode("utf-8"))
    _client(settle_s=1.5).set_camera(1.0, 2.0, 3.0)
    assert no_sleep == [1.5]


def test_f14_the_post_never_sends_a_non_json_token(wire, no_sleep):
    wire(b"{}")
    with pytest.raises(ValueError):
        _client()._post("/replay/render", {"a": math.nan})


# -------------------------------------------- F15 camera_writable

def _render_at(x: float) -> bytes:
    return json.dumps({**GOOD_RENDER, "cameraPosition":
                       {"x": x, "y": 1900.0, "z": 800.0}}).encode("utf-8")


@pytest.mark.parametrize("delta", [10.0, -10.0, 50.0, -50.0, 0.0, 0, math.nan,
                                   math.inf, True, "1500", None])
def test_f15_a_probe_too_small_to_tell_is_refused_before_any_write(
        wire, no_sleep, delta):
    # A 10-unit probe that never moved read abs(0 - 10) < 50, so a camera
    # whose writes are ignored reported itself writable.
    w = wire(_render_at(9000.0))
    with pytest.raises(ValueError):
        _client().camera_writable(probe_delta=delta)
    assert w.requests == []


def test_f15_control_writable_when_the_write_lands(wire, no_sleep):
    w = wire(_render_at(9000.0), b"{}", _render_at(10500.0), b"{}")
    assert _client().camera_writable() is True
    assert w.posts()[-1]["cameraPosition"]["x"] == 9000.0


def test_f15_control_not_writable_when_the_write_is_ignored(wire, no_sleep):
    w = wire(_render_at(9000.0), b"{}", _render_at(9000.0), b"{}")
    assert _client().camera_writable() is False
    assert w.posts()[-1]["cameraPosition"]["x"] == 9000.0


def test_f15_control_a_negative_probe_measures_too(wire, no_sleep):
    wire(_render_at(9000.0), b"{}", _render_at(7500.0), b"{}")
    assert _client().camera_writable(probe_delta=-1500.0) is True


def test_f15_the_restore_is_a_write_only_and_returns_the_measurement(
        wire, no_sleep):
    # The restore's read-back used to be able to throw the measurement away.
    w = wire(_render_at(9000.0), b"{}", _render_at(10500.0), b"{}")
    assert _client().camera_writable() is True
    assert [r.get_method() for r in w.requests] == ["GET", "POST", "GET",
                                                    "POST"]


def test_f15_the_camera_is_restored_when_the_read_back_fails(wire, no_sleep):
    # The camera HAS moved by now, so a failed read must not leave it there.
    w = wire(_render_at(9000.0), b"{}", urllib.error.URLError("gone"), b"{}")
    with pytest.raises(rc.RenderError):
        _client().camera_writable()
    assert [p["cameraPosition"]["x"] for p in w.posts()] == [10500.0, 9000.0]


def test_f15_a_failed_restore_is_loud_not_a_clean_answer(wire, no_sleep):
    # The operator's camera is left moved: that must never read as a result.
    wire(_render_at(9000.0), b"{}", _render_at(10500.0),
         urllib.error.URLError("gone"))
    with pytest.raises(rc.RenderError):
        _client().camera_writable()


def test_f15_no_write_happens_when_the_first_read_is_unusable(wire, no_sleep):
    # A fabricated (0, 0, 0) "before" would have been restored over a real
    # camera position.
    w = wire(json.dumps({"cameraMode": "fps"}).encode("utf-8"))
    with pytest.raises(rc.RenderError):
        _client().camera_writable()
    assert w.posts() == []
