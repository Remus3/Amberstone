"""RM-1214: the GDI self-grab and the OBS fetch leave a counted trace.

Same root as RM-1054. Before this slice:

- ``vision_server/_frame.py`` ``_fetch_frame_direct`` logged a failed
  ``ImageGrab.grab()`` or JPEG encode at DEBUG ("frame self-grab failed")
  and returned None silently when ``PIL.ImageGrab`` would not import, so
  ``/stats`` could not tell "the GDI grab broke" from "no grab was due".
- ``core/obs_frame_source.py`` ``get_obs_frame`` returned None for EVERY
  failure, so an OBS websocket error, a failed identify (auth), an overrun
  worker and an unexpected exception all read exactly like "the flag is
  off" or "OBS had no frame", and ``_maybe_obs_frame`` could count none of
  them.

Acceptance: a GDI grab failure is counted in a ``/stats`` ``gdi_lane``
block (NOT a ``capture_skip`` reason: that vocabulary is pinned equal to
tools/screen_agent.py ``SKIP_COUNTS`` and means "refused"), and
``get_obs_frame``'s failure path is split from its "nothing to return" path
through an ``on_failure`` callback, which ``_maybe_obs_frame`` routes into
the RM-1054 ``obs_lane`` block. A good grab, the flag off and an OBS reply
with no frame record nothing.

Every case runs against stubbed ImageGrab / OBS clients - no live OBS, no
real desktop grab. All authored content is 7-bit ASCII.
"""
from __future__ import annotations

import sys
import threading

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from core import obs_frame_source as ofs  # noqa: E402
from vision_server import _frame  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402

GDI_KEYS = ("unavailable", "error")
# RM-1215 appended the GetSourceScreenshot reasons; their tests live in
# tests/test_vision_obs_grab_reasons_s144q47.py.
OBS_KEYS = ("undecodable", "error", "ws_error", "auth", "timeout",
            "no_reply", "source_missing", "request_failed", "bad_payload")


def _textured(w=64, h=36):
    """A non-uniform frame: horizontal grey ramp (not Y-03 blank)."""
    img = Image.new("L", (w, h))
    img.putdata([int(255 * (x / max(1, w - 1))) for _y in range(h) for x in range(w)])
    return img.convert("RGB")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    stats_mod._reset_obs_lane()
    stats_mod._reset_gdi_lane()
    ofs._reset_for_tests()
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda *a, **k: False)
    yield
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    stats_mod._reset_obs_lane()
    stats_mod._reset_gdi_lane()
    ofs._reset_for_tests()


def _gdi_lane():
    return stats_mod.get_stats()["gdi_lane"]


def _obs_lane():
    return stats_mod.get_stats()["obs_lane"]


def _gdi_on(monkeypatch, grab):
    """OBS off, foreground gate open, ImageGrab.grab replaced by ``grab``."""
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(_frame, "_gdi_gate", lambda: None)
    from PIL import ImageGrab
    monkeypatch.setattr(ImageGrab, "grab", grab)


# -- gdi_lane exposure ----------------------------------------------------------

def test_stats_expose_gdi_lane_counters_at_zero():
    lane = _gdi_lane()
    assert tuple(stats_mod.GDI_LANE_FAILURES) == GDI_KEYS
    assert {k: lane[k] for k in GDI_KEYS} == {"unavailable": 0, "error": 0}
    assert lane["last_reason"] is None and lane["last_ts"] == 0.0


def test_gdi_lane_snapshot_is_a_copy():
    snap = _gdi_lane()
    snap["error"] = 99
    assert _gdi_lane()["error"] == 0


def test_record_gdi_lane_failure_rejects_unknown_reason():
    with pytest.raises(ValueError):
        stats_mod._record_gdi_lane_failure("blank")


def test_obs_lane_vocabulary_carries_the_fetch_reasons():
    assert tuple(stats_mod.OBS_LANE_FAILURES) == OBS_KEYS
    assert set(ofs.OBS_FETCH_FAILURES) <= set(OBS_KEYS)


# -- the GDI self-grab ---------------------------------------------------------

def test_grab_exception_is_counted_as_error(monkeypatch):
    def _boom():
        raise OSError("screen grab failed")
    _gdi_on(monkeypatch, _boom)
    assert _frame._fetch_frame_direct() is None
    lane = _gdi_lane()
    assert lane["error"] == 1 and lane["unavailable"] == 0
    assert lane["last_reason"] == "error" and lane["last_ts"] > 0


def test_encode_failure_is_counted_as_error(monkeypatch):
    _gdi_on(monkeypatch, lambda: _textured())

    def _bad_downscale(img):
        raise RuntimeError("encode")
    monkeypatch.setattr(_frame, "_downscaled", _bad_downscale)
    assert _frame._fetch_frame_direct() is None
    assert _gdi_lane()["error"] == 1


def test_imagegrab_unimportable_is_counted_as_unavailable(monkeypatch):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(_frame, "_gdi_gate", lambda: None)
    import PIL as pil_pkg
    monkeypatch.delattr(pil_pkg, "ImageGrab", raising=False)
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", None)
    assert _frame._fetch_frame_direct() is None
    lane = _gdi_lane()
    assert lane["unavailable"] == 1 and lane["error"] == 0
    assert lane["last_reason"] == "unavailable"


def test_good_grab_records_nothing(monkeypatch):
    _gdi_on(monkeypatch, lambda: _textured())
    got = _frame._fetch_frame_direct()
    assert got is not None and got["source"] == "self_grab"
    assert _gdi_lane()["last_reason"] is None
    assert {k: _gdi_lane()[k] for k in GDI_KEYS} == {"unavailable": 0, "error": 0}


def test_blank_grab_stays_a_capture_skip_not_a_gdi_failure(monkeypatch):
    _gdi_on(monkeypatch, lambda: Image.new("RGB", (64, 36), (0, 0, 0)))
    assert _frame._fetch_frame_direct() is None
    assert stats_mod.get_stats()["capture_skip"]["blank"] == 1
    assert _gdi_lane()["last_reason"] is None


def test_gate_refusal_records_no_gdi_failure(monkeypatch):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    monkeypatch.setattr(_frame, "_gdi_gate", lambda: "not_foreground")
    assert _frame._fetch_frame_direct() is None
    assert stats_mod.get_stats()["capture_skip"]["not_foreground"] == 1
    assert _gdi_lane()["last_reason"] is None


def test_reset_zeroes_the_gdi_lane_block():
    stats_mod._record_gdi_lane_failure("error")
    stats_mod._reset_gdi_lane()
    lane = _gdi_lane()
    assert lane["error"] == 0 and lane["last_reason"] is None


# -- get_obs_frame: failure split from "nothing to return" ------------------------

def _cfg_on(monkeypatch, **extra):
    cfg = {"frame_source": True}
    cfg.update(extra)
    monkeypatch.setattr(ofs, "_get_obs_cfg", lambda: cfg)
    from core import obs_publisher as pub
    monkeypatch.setattr(pub, "peek_frame", lambda max_age_s=3.0: None)


def _collect():
    seen: list = []
    return seen, seen.append


def test_ws_error_reports_ws_error(monkeypatch):
    _cfg_on(monkeypatch, port=1)
    import websockets

    def _refuse(*a, **k):
        raise ConnectionRefusedError("obs down")
    monkeypatch.setattr(websockets, "connect", _refuse)
    seen, cb = _collect()
    assert ofs.get_obs_frame(timeout_s=0.2, on_failure=cb) is None
    assert seen == ["ws_error"]


def test_identify_failure_reports_auth(monkeypatch):
    _cfg_on(monkeypatch)
    import websockets

    class _Conn:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(websockets, "connect", lambda *a, **k: _Conn())
    from core import obs_publisher as pub

    async def _no(self, ws, password):
        return False
    monkeypatch.setattr(pub.OBSPublisher, "_identify", _no)
    seen, cb = _collect()
    assert ofs.get_obs_frame(timeout_s=0.2, on_failure=cb) is None
    assert seen == ["auth"]


def test_overrunning_worker_reports_timeout(monkeypatch):
    _cfg_on(monkeypatch)
    monkeypatch.setattr(ofs, "_JOIN_GRACE_S", 0.0)
    release = threading.Event()

    async def _stuck(cfg, timeout_s):
        release.wait(5.0)
    monkeypatch.setattr(ofs, "_fetch_async", _stuck)
    seen, cb = _collect()
    try:
        assert ofs.get_obs_frame(timeout_s=0.05, on_failure=cb) is None
        assert seen == ["timeout"]
    finally:
        release.set()
        for t in threading.enumerate():
            if t.name == "obs-frame-oneshot":
                t.join(5.0)


def test_worker_exception_reports_error(monkeypatch):
    _cfg_on(monkeypatch)

    def _not_a_coroutine(cfg, timeout_s):
        raise RuntimeError("loop")
    monkeypatch.setattr(ofs, "_fetch_async", _not_a_coroutine)
    seen, cb = _collect()
    assert ofs.get_obs_frame(timeout_s=0.2, on_failure=cb) is None
    assert seen == ["error"]


def test_unexpected_exception_reports_error(monkeypatch):
    def _boom():
        raise RuntimeError("cfg")
    monkeypatch.setattr(ofs, "_get_obs_cfg", _boom)
    seen, cb = _collect()
    assert ofs.get_obs_frame(on_failure=cb) is None
    assert seen == ["error"]


def test_obs_with_no_frame_reports_nothing(monkeypatch):
    _cfg_on(monkeypatch)

    async def _nothing(cfg, timeout_s):
        return None
    monkeypatch.setattr(ofs, "_fetch_async", _nothing)
    seen, cb = _collect()
    assert ofs.get_obs_frame(timeout_s=0.2, on_failure=cb) is None
    assert seen == []


def test_flag_off_and_a_served_frame_report_nothing(monkeypatch):
    seen, cb = _collect()
    monkeypatch.setattr(ofs, "_get_obs_cfg", dict)
    assert ofs.get_obs_frame(on_failure=cb) is None
    _cfg_on(monkeypatch)
    monkeypatch.setattr(ofs, "_fetch_once", lambda cfg, t: b"frame")
    assert ofs.get_obs_frame(on_failure=cb) == b"frame"
    assert seen == []


def test_a_raising_callback_never_escapes(monkeypatch):
    def _boom():
        raise RuntimeError("cfg")
    monkeypatch.setattr(ofs, "_get_obs_cfg", _boom)

    def _bad_cb(reason):
        raise ValueError(reason)
    assert ofs.get_obs_frame(on_failure=_bad_cb) is None


def test_no_callback_keeps_the_old_contract(monkeypatch):
    _cfg_on(monkeypatch)
    monkeypatch.setattr(ofs, "_fetch_async",
                        lambda cfg, timeout_s: (_ for _ in ()).throw(RuntimeError("x")))
    assert ofs.get_obs_frame(timeout_s=0.2) is None


# -- _maybe_obs_frame routes the fetch reason into obs_lane ----------------------

@pytest.mark.parametrize("reason", ["ws_error", "auth", "timeout", "error"])
def test_fetch_failure_reaches_obs_lane(monkeypatch, reason):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)

    def _stub(*a, on_failure=None, **k):
        on_failure(reason)
    monkeypatch.setattr(ofs, "get_obs_frame", _stub)
    assert _frame._maybe_obs_frame() is None
    lane = _obs_lane()
    assert lane[reason] == 1 and lane["last_reason"] == reason


def test_unknown_fetch_reason_counts_as_error(monkeypatch):
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)

    def _stub(*a, on_failure=None, **k):
        # Mirror the real facade: a raising hook is swallowed (ofs._notify),
        # so only the hook's own mapping can put this in "error".
        ofs._notify(on_failure, "mystery")
    monkeypatch.setattr(ofs, "get_obs_frame", _stub)
    assert _frame._maybe_obs_frame() is None
    assert _obs_lane()["error"] == 1


def test_real_fetch_failure_end_to_end(monkeypatch):
    """No get_obs_frame stub: the real facade's ws_error reaches /stats."""
    _cfg_on(monkeypatch, port=1, frame_timeout_s=0.2)
    import websockets

    def _refuse(*a, **k):
        raise ConnectionRefusedError("obs down")
    monkeypatch.setattr(websockets, "connect", _refuse)
    assert _frame._maybe_obs_frame() is None
    assert _obs_lane()["ws_error"] == 1
