"""RM-1215: an OBS reply that carries no frame says WHY.

Same root as RM-1054 and RM-1214. After RM-1214, ``get_obs_frame``'s
``on_failure`` hook reported a websocket error, a failed identify, an
overrun worker and an unexpected exception, but everything that went wrong
AFTER a successful identify still read as one undifferentiated None:
``core/obs_publisher.py`` ``grab_source_screenshot`` returned None for

- no op:7 reply inside the timeout, or the connection failing mid-request
  (``request_response`` returned None),
- ``requestStatus.result == False`` - for example a wrong
  ``frame_source_name`` (OBS-WS v5 status 600 ResourceNotFound) or a source
  that is not active (604 InvalidResourceState),
- a successful reply whose ``imageData`` is absent or undecodable,

so ``/stats`` ``obs_lane`` could not tell a misconfigured source name from
"OBS had no frame". Also ``vision_server/_frame.py`` ``_fetch_frame_direct``
let ``ImageGrab.grab()`` returning None pass as "no frame".

Acceptance: ``grab_source_screenshot`` takes an optional ``on_failure``
hook naming one reason from ``GRAB_FAILURES`` (``no_reply``,
``source_missing``, ``request_failed``, ``bad_payload``); the
``get_obs_frame`` facade carries it out through its own ``on_failure``; and
``_maybe_obs_frame`` counts it in ``obs_lane``. Decision recorded here: a
GDI ``ImageGrab.grab()`` that returns None for a due, unrefused grab is a
failure and counts as ``gdi_lane.error`` (Pillow documents no None return;
the grab was owed a frame and produced none).

Every case runs against stubbed OBS replies and a stubbed ImageGrab - no
live OBS, no real desktop grab. All authored content is 7-bit ASCII.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from core import obs_frame_source as ofs  # noqa: E402
from core import obs_publisher as pub  # noqa: E402
from tests._asyncio_isolation import run_coro  # noqa: E402
from tools import gated_vision_pillow as gvp  # noqa: E402
from vision_server import _frame  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402

GRAB_KEYS = ("no_reply", "source_missing", "request_failed", "bad_payload")


class _StubWs:
    """Async stand-in for a websockets connection. Each queued item is a
    callable taking the sent payloads (so a reply can echo the requestId);
    an empty queue blocks until the caller's wait_for times out."""

    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)

    async def recv(self):
        if self.incoming:
            return self.incoming.pop(0)(self.sent)
        await asyncio.Event().wait()
        raise AssertionError("an Event nobody sets never wakes")


def _rid(sent):
    return json.loads(sent[-1])["d"]["requestId"]


def _reply(result=True, code=None, image_data=None, with_data=True):
    """A GetSourceScreenshot op:7 reply builder for _StubWs."""
    def _build(sent):
        status = {"result": bool(result)}
        if code is not None:
            status["code"] = code
        d = {"requestId": _rid(sent), "requestType": "GetSourceScreenshot",
             "requestStatus": status}
        if with_data:
            d["responseData"] = {"imageData": image_data}
        return json.dumps({"op": 7, "d": d})
    return _build


def _jpeg_uri(raw=b"\xff\xd8\xff-fake"):
    return "data:image/jpg;base64," + base64.b64encode(raw).decode("ascii")


def _run(coro):
    # Off the main thread (tests/_asyncio_isolation): a bare asyncio.run()
    # raises "cannot be called from a running event loop" once a
    # snapshot_panels Playwright session has run on the same worker.
    return run_coro(coro)


def _grab(ws, timeout_s=2.0):
    seen: list = []
    raw = _run(pub.grab_source_screenshot(ws, "Game Capture",
                                          timeout_s=timeout_s,
                                          on_failure=seen.append))
    return raw, seen


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pub._reset_frame_slot()
    ofs._reset_for_tests()
    stats_mod._reset_obs_lane()
    stats_mod._reset_gdi_lane()
    stats_mod._reset_capture_skips()
    _frame._reset_self_read_state()
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda *a, **k: False)
    yield
    pub._reset_frame_slot()
    ofs._reset_for_tests()
    stats_mod._reset_obs_lane()
    stats_mod._reset_gdi_lane()
    stats_mod._reset_capture_skips()
    _frame._reset_self_read_state()


# -- vocabulary -----------------------------------------------------------------

def test_grab_failure_vocabulary():
    assert tuple(pub.GRAB_FAILURES) == GRAB_KEYS


def test_every_grab_reason_is_a_fetch_reason_and_an_obs_lane_key():
    assert set(GRAB_KEYS) <= set(ofs.OBS_FETCH_FAILURES)
    assert set(ofs.OBS_FETCH_FAILURES) <= set(stats_mod.OBS_LANE_FAILURES)
    lane = stats_mod.get_stats()["obs_lane"]
    for k in GRAB_KEYS:
        assert lane[k] == 0


# -- grab_source_screenshot names the reason ----------------------------------

def test_wrong_source_name_reports_source_missing():
    raw, seen = _grab(_StubWs([_reply(result=False, code=600,
                                      with_data=False)]))
    assert raw is None
    assert seen == ["source_missing"]


@pytest.mark.parametrize("code", [604, 702, None, "600"])
def test_other_refused_requests_report_request_failed(code):
    raw, seen = _grab(_StubWs([_reply(result=False, code=code,
                                      with_data=False)]))
    assert raw is None
    assert seen == ["request_failed"]


def test_no_reply_inside_the_timeout_reports_no_reply():
    raw, seen = _grab(_StubWs([]), timeout_s=0.1)
    assert raw is None
    assert seen == ["no_reply"]


def test_connection_failing_mid_request_reports_no_reply():
    class _Dead(_StubWs):
        async def send(self, msg):
            raise ConnectionError("closed")
    raw, seen = _grab(_Dead())
    assert raw is None
    assert seen == ["no_reply"]


@pytest.mark.parametrize("image_data,with_data", [
    (None, False),          # no responseData at all
    (None, True),           # responseData without imageData
    ("", True),             # empty imageData
    (12345, True),          # not a string
    ("data:image/jpg;base64,", True),  # decodes to nothing
])
def test_success_without_a_usable_image_reports_bad_payload(image_data,
                                                            with_data):
    raw, seen = _grab(_StubWs([_reply(image_data=image_data,
                                      with_data=with_data)]))
    assert raw is None
    assert seen == ["bad_payload"]
    assert pub.peek_frame(max_age_s=5.0) is None


def test_a_good_grab_reports_nothing_and_warms_the_slot():
    raw, seen = _grab(_StubWs([_reply(image_data=_jpeg_uri(b"abc"))]))
    assert raw == b"abc"
    assert seen == []
    assert pub.peek_frame(max_age_s=5.0) == b"abc"


def test_a_raising_hook_never_escapes_the_grab():
    def _bad(reason):
        raise ValueError(reason)
    raw = _run(pub.grab_source_screenshot(
        _StubWs([_reply(result=False, code=600, with_data=False)]),
        "Nope", timeout_s=2.0, on_failure=_bad))
    assert raw is None


def test_no_hook_keeps_the_old_contract():
    raw = _run(pub.grab_source_screenshot(
        _StubWs([_reply(result=False, code=600, with_data=False)]),
        "Nope", timeout_s=2.0))
    assert raw is None


# -- the facade carries the grab reason out -----------------------------------

def _facade_on(monkeypatch, ws):
    cfg = {"frame_source": True, "frame_source_name": "Wrong Name",
           "frame_timeout_s": 1.0}
    monkeypatch.setattr(ofs, "_get_obs_cfg", lambda: cfg)
    monkeypatch.setattr(pub, "peek_frame", lambda max_age_s=3.0: None)
    import websockets

    class _Conn:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _Conn())

    async def _yes(self, ws_, password):
        return True
    monkeypatch.setattr(pub.OBSPublisher, "_identify", _yes)


def test_get_obs_frame_reports_source_missing(monkeypatch):
    _facade_on(monkeypatch, _StubWs([_reply(result=False, code=600,
                                            with_data=False)]))
    seen: list = []
    assert ofs.get_obs_frame(on_failure=seen.append) is None
    assert seen == ["source_missing"]


def test_get_obs_frame_good_grab_reports_nothing(monkeypatch):
    _facade_on(monkeypatch, _StubWs([_reply(image_data=_jpeg_uri(b"xyz"))]))
    seen: list = []
    assert ofs.get_obs_frame(on_failure=seen.append) == b"xyz"
    assert seen == []


def test_a_grab_that_names_no_reason_still_reports_nothing(monkeypatch):
    """A grab stand-in that returns None without calling the hook keeps the
    RM-1214 "OBS had no frame" path: no reason is invented."""
    _facade_on(monkeypatch, _StubWs([]))

    async def _quiet(ws, source, image_width=0, timeout_s=1.0,
                     on_failure=None):
        return None
    monkeypatch.setattr(pub, "grab_source_screenshot", _quiet)
    seen: list = []
    assert ofs.get_obs_frame(on_failure=seen.append) is None
    assert seen == []


def test_source_missing_reaches_obs_lane_end_to_end(monkeypatch):
    """No get_obs_frame stub: a wrong source name lands in /stats obs_lane."""
    _facade_on(monkeypatch, _StubWs([_reply(result=False, code=600,
                                            with_data=False)]))
    assert _frame._maybe_obs_frame() is None
    lane = stats_mod.get_stats()["obs_lane"]
    assert lane["source_missing"] == 1
    assert lane["last_reason"] == "source_missing"
    assert lane["undecodable"] == 0 and lane["error"] == 0


@pytest.mark.parametrize("reason", GRAB_KEYS)
def test_each_grab_reason_is_counted_by_its_own_name(monkeypatch, reason):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)

    def _stub(*a, on_failure=None, **k):
        ofs._notify(on_failure, reason)
    monkeypatch.setattr(ofs, "get_obs_frame", _stub)
    assert _frame._maybe_obs_frame() is None
    lane = stats_mod.get_stats()["obs_lane"]
    assert lane[reason] == 1 and lane["error"] == 0


# -- GDI: ImageGrab.grab() returning None is a counted failure ----------------

def test_imagegrab_returning_none_counts_as_gdi_error(monkeypatch):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(_frame, "_gdi_gate", lambda: None)
    from PIL import ImageGrab
    monkeypatch.setattr(ImageGrab, "grab", lambda *a, **k: None)
    assert _frame._fetch_frame_direct() is None
    lane = stats_mod.get_stats()["gdi_lane"]
    assert lane["error"] == 1 and lane["last_reason"] == "error"


def test_imagegrab_good_frame_still_counts_nothing(monkeypatch):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(_frame, "_gdi_gate", lambda: None)
    from PIL import ImageGrab
    img = Image.new("L", (64, 36))
    img.putdata([int(255 * (x / 63)) for _y in range(36) for x in range(64)])
    monkeypatch.setattr(ImageGrab, "grab", lambda *a, **k: img.convert("RGB"))
    out = _frame._fetch_frame_direct()
    assert out is not None and out["source"] == "self_grab"
    lane = stats_mod.get_stats()["gdi_lane"]
    assert lane["error"] == 0 and lane["last_reason"] is None


# -- the gated readback passes the new reasons through ------------------------

def test_stats_counters_keeps_the_grab_reasons():
    body = {"stats": {},
            "obs_lane": {"undecodable": 0, "error": 0, "ws_error": 0,
                         "auth": 0, "timeout": 0, "no_reply": 1,
                         "source_missing": 3, "request_failed": 2,
                         "bad_payload": 4, "last_reason": "source_missing",
                         "last_ts": 3.0}}
    out = gvp.stats_counters(body)["obs_lane"]
    assert out["source_missing"] == 3 and out["request_failed"] == 2
    assert out["no_reply"] == 1 and out["bad_payload"] == 4
    assert out["last_reason"] == "source_missing"


def test_stats_counters_omits_grab_reasons_from_an_older_server():
    body = {"stats": {},
            "obs_lane": {"undecodable": 0, "error": 0, "ws_error": 1,
                         "auth": 0, "timeout": 0, "last_reason": "ws_error",
                         "last_ts": 3.0}}
    out = gvp.stats_counters(body)["obs_lane"]
    for k in GRAB_KEYS:
        assert k not in out
