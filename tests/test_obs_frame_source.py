"""Wave-1 agent-obs (spec O) - OBS occlusion-proof frame provider tests.

Everything runs against a stubbed WS layer - NO live OBS. Covers:

  1. core/obs_publisher.py request/response lane: an op:6 Request sender
     with requestId correlation and an op:7 RequestResponse awaiter
     (request_response), plus grab_source_screenshot which decodes the
     base64 GetSourceScreenshot imageData payload to raw bytes and
     populates the keep-warm frame slot (store_frame / peek_frame).
  2. core/obs_frame_source.py sync facade get_obs_frame: DEFAULT OFF
     returns None with no fetch attempted; flag-on serves the keep-warm
     slot first, falls to a one-shot fetch, and degrades to None on any
     error (fail-soft, never raises).
  3. Flag-off inertness of the two consumer swap points:
     vision_server._frame._maybe_obs_frame and
     core.minimap_blob_detect._grab_obs_minimap never consult OBS when
     obs.frame_source is off, and prefer OBS when it is on.

All authored content is 7-bit ASCII.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import threading
import time
from pathlib import Path

import pytest
from tests._asyncio_isolation import run_coro as _run_coro

_REPO_ROOT = Path(__file__).resolve().parent.parent

_BANNED_CHARS = "\u2013\u2014\u2018\u2019\u201c\u201d"


class _StubWs:
    """Minimal async stand-in for a websockets client connection.

    ``incoming`` may hold plain strings (served as-is) or callables taking
    the list of sent payloads (so a reply can echo the requestId the code
    under test just generated).
    """

    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.incoming:
            item = self.incoming.pop(0)
            if callable(item):
                return item(self.sent)
            return item
        await asyncio.Event().wait()  # block until wait_for() times out


def _sent_request_id(sent):
    """requestId of the most recent op:6 payload the code under test sent."""
    d = json.loads(sent[-1])
    return d["d"]["requestId"]


def _op7_reply(request_id, image_bytes=None, result=True):
    d = {
        "requestId": request_id,
        "requestType": "GetSourceScreenshot",
        "requestStatus": {"result": bool(result), "code": 100 if result else 604},
    }
    if image_bytes is not None:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        d["responseData"] = {"imageData": "data:image/jpg;base64," + b64}
    return json.dumps({"op": 7, "d": d})


@pytest.fixture(autouse=True)
def _clean_slot_and_cfg():
    """Reset the keep-warm slot + the facade config cache around each test."""
    from core import obs_frame_source, obs_publisher
    obs_publisher._reset_frame_slot()
    obs_frame_source._reset_for_tests()
    yield
    obs_publisher._reset_frame_slot()
    obs_frame_source._reset_for_tests()


# ---------------------------------------------------------------------------
# 1. op:6 request sender / op:7 awaiter (core/obs_publisher.py)
# ---------------------------------------------------------------------------

def test_request_response_emits_op6_getsourcescreenshot_shape():
    from core.obs_publisher import request_response

    ws = _StubWs([lambda sent: _op7_reply(_sent_request_id(sent))])
    _run_coro(request_response(
        ws, "GetSourceScreenshot",
        {"sourceName": "Game Capture", "imageFormat": "jpg", "imageWidth": 1280},
        timeout_s=2.0))

    sent = json.loads(ws.sent[0])
    assert sent["op"] == 6
    assert sent["d"]["requestType"] == "GetSourceScreenshot"
    assert isinstance(sent["d"]["requestId"], str) and sent["d"]["requestId"]
    assert sent["d"]["requestData"] == {
        "sourceName": "Game Capture", "imageFormat": "jpg", "imageWidth": 1280,
    }


def test_request_response_correlates_request_id():
    """A stray op:7 with a foreign requestId is skipped; the matching one wins."""
    from core.obs_publisher import request_response

    stray = json.dumps({"op": 7, "d": {"requestId": "someone-else"}})
    event = json.dumps({"op": 5, "d": {"eventType": "Noise"}})
    ws = _StubWs([stray, event,
                  lambda sent: _op7_reply(_sent_request_id(sent))])

    d = _run_coro(request_response(ws, "GetSourceScreenshot", {}, timeout_s=2.0))
    assert isinstance(d, dict)
    assert d["requestId"] == _sent_request_id(ws.sent)


def test_request_response_timeout_returns_none():
    from core.obs_publisher import request_response

    ws = _StubWs([])  # never answers
    t0 = time.monotonic()
    d = _run_coro(request_response(ws, "GetSourceScreenshot", {}, timeout_s=0.2))
    assert d is None
    assert time.monotonic() - t0 < 5.0


def test_request_response_send_error_returns_none():
    from core.obs_publisher import request_response

    class _DeadWs:
        async def send(self, msg):
            raise ConnectionError("closed")

        async def recv(self):
            raise ConnectionError("closed")

    d = _run_coro(request_response(_DeadWs(), "GetSourceScreenshot", {},
                                   timeout_s=0.2))
    assert d is None


# ---------------------------------------------------------------------------
# 2. grab_source_screenshot + keep-warm slot
# ---------------------------------------------------------------------------

def test_grab_decodes_base64_imagedata_to_bytes_and_warms_slot():
    from core.obs_publisher import grab_source_screenshot, peek_frame

    payload = b"\xff\xd8\xff-fake-jpeg-bytes"
    ws = _StubWs([lambda sent: _op7_reply(_sent_request_id(sent), payload)])

    raw = _run_coro(grab_source_screenshot(ws, "Game Capture",
                                           image_width=1280, timeout_s=2.0))
    assert raw == payload
    assert peek_frame(max_age_s=5.0) == payload


def test_grab_omits_image_width_when_native():
    from core.obs_publisher import grab_source_screenshot

    ws = _StubWs([lambda sent: _op7_reply(_sent_request_id(sent), b"x")])
    _run_coro(grab_source_screenshot(ws, "Game Capture", image_width=0,
                                     timeout_s=2.0))
    sent = json.loads(ws.sent[0])
    assert "imageWidth" not in sent["d"]["requestData"]
    assert sent["d"]["requestData"]["imageFormat"] == "jpg"


def test_grab_request_failure_returns_none():
    from core.obs_publisher import grab_source_screenshot, peek_frame

    ws = _StubWs([lambda sent: _op7_reply(_sent_request_id(sent),
                                          image_bytes=None, result=False)])
    raw = _run_coro(grab_source_screenshot(ws, "Nope", timeout_s=2.0))
    assert raw is None
    assert peek_frame(max_age_s=5.0) is None


def test_peek_frame_stale_returns_none():
    from core.obs_publisher import peek_frame, store_frame

    store_frame(b"old")
    assert peek_frame(max_age_s=0.0) is None
    assert peek_frame(max_age_s=60.0) == b"old"


def test_async_loop_keep_warm_is_flag_gated():
    """Source pin: the publish loop only grabs frames when frame_source is
    truthy in config - the existing text-push behavior is untouched when the
    new path is unused."""
    from core.obs_publisher import OBSPublisher

    src = inspect.getsource(OBSPublisher._async_loop)
    assert "frame_source" in src
    assert "grab_source_screenshot" in src
    assert "_drain_pending" in src  # existing drain behavior preserved


# ---------------------------------------------------------------------------
# 3. sync facade core/obs_frame_source.get_obs_frame
# ---------------------------------------------------------------------------

def test_get_obs_frame_default_off_returns_none(monkeypatch):
    from core import obs_frame_source as ofs

    monkeypatch.setattr(ofs, "_get_obs_cfg", lambda: {})
    # if the facade wrongly attempted a fetch, it would return b"leak"
    monkeypatch.setattr(ofs, "_fetch_once", lambda cfg, t: b"leak")
    assert ofs.get_obs_frame() is None
    assert ofs.obs_frame_source_enabled() is False


def test_get_obs_frame_explicit_false_returns_none(monkeypatch):
    from core import obs_frame_source as ofs

    monkeypatch.setattr(ofs, "_get_obs_cfg",
                        lambda: {"enabled": True, "frame_source": False})
    monkeypatch.setattr(ofs, "_fetch_once", lambda cfg, t: b"leak")
    assert ofs.get_obs_frame() is None


def test_get_obs_frame_serves_keep_warm_slot(monkeypatch):
    from core import obs_frame_source as ofs
    from core.obs_publisher import store_frame

    monkeypatch.setattr(ofs, "_get_obs_cfg", lambda: {"frame_source": True})
    monkeypatch.setattr(ofs, "_fetch_once", lambda cfg, t: b"should-not-fetch")
    store_frame(b"warm-frame")
    assert ofs.get_obs_frame() == b"warm-frame"


def test_get_obs_frame_falls_to_one_shot_fetch(monkeypatch):
    from core import obs_frame_source as ofs

    monkeypatch.setattr(ofs, "_get_obs_cfg", lambda: {"frame_source": True})
    monkeypatch.setattr(ofs, "_fetch_once", lambda cfg, t: b"one-shot")
    assert ofs.get_obs_frame() == b"one-shot"


def test_get_obs_frame_fetch_failure_returns_none(monkeypatch):
    from core import obs_frame_source as ofs

    monkeypatch.setattr(ofs, "_get_obs_cfg", lambda: {"frame_source": True})
    monkeypatch.setattr(ofs, "_fetch_once", lambda cfg, t: None)
    assert ofs.get_obs_frame() is None


def test_get_obs_frame_never_raises_on_cfg_error(monkeypatch):
    from core import obs_frame_source as ofs

    def _boom():
        raise RuntimeError("corrupt config")

    monkeypatch.setattr(ofs, "_get_obs_cfg", _boom)
    assert ofs.get_obs_frame() is None
    assert ofs.obs_frame_source_enabled() is False


# ---------------------------------------------------------------------------
# 4. consumer swap points - flag-off inertness + flag-on preference
# ---------------------------------------------------------------------------

def test_vision_frame_flag_off_never_consults_obs(monkeypatch):
    from core import obs_frame_source as ofs
    from vision_server import _frame

    def _must_not_fetch(*a, **k):
        raise AssertionError("get_obs_frame called with flag off")

    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(ofs, "get_obs_frame", _must_not_fetch)
    assert _frame._maybe_obs_frame() is None


def test_vision_frame_obs_first_when_flag_on(monkeypatch):
    from core import obs_frame_source as ofs
    from vision_server import _frame

    raw = b"\xff\xd8\xff-not-a-real-jpeg"
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: raw)

    frame = _frame._fetch_frame_direct()
    assert isinstance(frame, dict)
    assert frame["source"] == "obs"
    assert frame["format"] == "jpeg"
    assert base64.b64decode(frame["b64"]) == raw


def test_vision_frame_obs_failure_degrades_to_none(monkeypatch):
    """OBS enabled but the fetch fails -> _maybe_obs_frame None, so the
    caller falls through to the untouched GDI block."""
    from core import obs_frame_source as ofs
    from vision_server import _frame

    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: None)
    assert _frame._maybe_obs_frame() is None


def test_vision_fetch_frame_direct_tries_obs_first():
    """Source pin: the GDI self-grab body is preceded by the OBS attempt."""
    from vision_server import _frame

    src = inspect.getsource(_frame._fetch_frame_direct)
    assert "_maybe_obs_frame" in src
    assert src.index("_maybe_obs_frame") < src.index("from PIL import ImageGrab")


def test_blob_obs_grab_flag_off_never_consults_obs(monkeypatch):
    from core import minimap_blob_detect as mbd
    from core import obs_frame_source as ofs

    if mbd.np is None:
        pytest.skip("numpy unavailable")

    def _must_not_fetch(*a, **k):
        raise AssertionError("get_obs_frame called with flag off")

    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(ofs, "get_obs_frame", _must_not_fetch)
    rect = {"x": 1600, "y": 761, "w": 312, "h": 312}
    assert mbd._grab_obs_minimap(rect) is None


def test_blob_obs_grab_decodes_and_crops(monkeypatch):
    from core import minimap_blob_detect as mbd
    from core import obs_frame_source as ofs

    if mbd.np is None:
        pytest.skip("numpy unavailable")
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001
        pytest.skip("PIL unavailable")

    img = Image.new("RGB", (192, 108), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    raw = buf.getvalue()

    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: raw)

    rect = {"x": 960, "y": 540, "w": 960, "h": 540}  # bottom-right quarter
    crop = mbd._grab_obs_minimap(rect)
    assert crop is not None
    assert crop.shape[0] == 54 and crop.shape[1] == 96


def test_blob_native_grab_prefers_obs(monkeypatch):
    from core import minimap_blob_detect as mbd

    if mbd.np is None:
        pytest.skip("numpy unavailable")
    sentinel = mbd.np.zeros((8, 8, 3), dtype=mbd.np.uint8)
    monkeypatch.setattr(mbd, "_grab_obs_minimap", lambda rect: sentinel)
    out = mbd._grab_native_minimap({"x": 0, "y": 0, "w": 10, "h": 10})
    assert out is sentinel


def test_blob_native_grab_source_falls_back_to_gdi():
    """Source pin: the OBS attempt precedes the existing ImageGrab path."""
    from core import minimap_blob_detect as mbd

    src = inspect.getsource(mbd._grab_native_minimap)
    assert "_grab_obs_minimap" in src
    assert src.index("_grab_obs_minimap") < src.index("ImageGrab")


# ---------------------------------------------------------------------------
# 5. config knob - committed shape is DEFAULT OFF
# ---------------------------------------------------------------------------

def test_example_config_obs_block_default_off():
    cfg = json.loads((_REPO_ROOT / "config" /
                      "coach_settings.example.json").read_text(encoding="utf-8"))
    obs = cfg.get("obs")
    assert isinstance(obs, dict)
    assert obs.get("enabled") is False
    assert obs.get("frame_source") is False


# ---------------------------------------------------------------------------
# 6. ASCII hygiene (repo hard rule)
# ---------------------------------------------------------------------------

def test_no_banned_codepoints():
    for rel in ("core/obs_frame_source.py", "core/obs_publisher.py",
                "vision_server/_frame.py", "core/minimap_blob_detect.py",
                "tests/test_obs_frame_source.py",
                "config/coach_settings.example.json"):
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        for ch in _BANNED_CHARS:
            assert ch not in text, f"banned codepoint {ch!r} in {rel}"
