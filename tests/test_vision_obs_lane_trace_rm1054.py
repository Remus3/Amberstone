"""RM-1054: an OBS-lane failure in the vision process leaves a counted trace.

Before this slice ``vision_server/_frame.py`` ``_maybe_obs_frame`` logged its
two failure lines (Pillow could not decode the OBS bytes; any other failure
in the lane, the JPEG re-encode included) at DEBUG, below the vision log's
INFO level, and counted nothing, so a gated S6 drain reading ``/stats``
could not tell "OBS yielded nothing" from "the OBS bytes were undecodable".

Acceptance: an undecodable payload and an encode failure each bump a
distinct counter in ``get_stats()["obs_lane"]``; a good JPEG, the flag off
and an empty OBS reply record nothing.

Design (recorded, not assumed): the counters are a SEPARATE block, not two
new ``capture_skip`` reasons. ``CAPTURE_SKIP_REASONS`` is the Y-03 REFUSAL
vocabulary shared with tools/screen_agent.py (``SKIP_COUNTS``, pinned equal
by tests/test_vision_capture_fail_closed_y03.py), and its ``last_reason``
means "a capture was refused"; an OBS decode failure refuses nothing - the
GDI grab still runs.

Every case runs against a ``get_obs_frame`` stub - no live OBS, no real
desktop grab. All authored content is 7-bit ASCII.
"""
from __future__ import annotations

import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from vision_server import _frame  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402

OBS_KEYS = ("undecodable", "error")


def _textured(w, h):
    """A non-uniform frame: horizontal grey ramp (not Y-03 blank)."""
    img = Image.new("L", (w, h))
    img.putdata([int(255 * (x / max(1, w - 1))) for _y in range(h) for x in range(w)])
    return img.convert("RGB")


def _encode(img, fmt):
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    stats_mod._reset_obs_lane()
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda *a, **k: False)
    yield
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    stats_mod._reset_obs_lane()


def _obs(monkeypatch, payload, enabled=True):
    from core import obs_frame_source as ofs
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: enabled)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: payload)


def _obs_lane():
    return stats_mod.get_stats()["obs_lane"]


def _counts():
    lane = _obs_lane()
    return {k: lane[k] for k in OBS_KEYS}


def _skips():
    cs = stats_mod.get_stats()["capture_skip"]
    return {r: cs[r] for r in stats_mod.CAPTURE_SKIP_REASONS}


# -- exposure -----------------------------------------------------------------

def test_stats_expose_obs_lane_counters_at_zero():
    lane = _obs_lane()
    assert tuple(stats_mod.OBS_LANE_FAILURES) == OBS_KEYS
    assert _counts() == {"undecodable": 0, "error": 0}
    assert lane["last_reason"] is None
    assert lane["last_ts"] == 0.0


def test_obs_lane_snapshot_is_a_copy():
    snap = _obs_lane()
    snap["undecodable"] = 999
    assert _obs_lane()["undecodable"] == 0


def test_record_obs_lane_failure_rejects_unknown_reason():
    with pytest.raises(ValueError):
        stats_mod._record_obs_lane_failure("sleepy")


# -- undecodable bytes are counted, distinct from "OBS yielded nothing" -------

@pytest.mark.parametrize("payload", [
    b"\xff\xd8\xff-not-a-real-jpeg",
    b"\x00" * 64,
    "\xff\xd8\xff-text",  # non-bytes: PIL refuses it at decode
], ids=["jpeg-magic-garbage", "zeros", "non-bytes"])
def test_undecodable_obs_payload_is_counted(monkeypatch, payload):
    _obs(monkeypatch, payload)
    assert _frame._maybe_obs_frame() is None
    assert _counts() == {"undecodable": 1, "error": 0}
    lane = _obs_lane()
    assert lane["last_reason"] == "undecodable"
    assert lane["last_ts"] > 0
    # A decode failure refuses no capture: the Y-03 refusal counters stay 0.
    assert set(_skips().values()) == {0}


def test_truncated_obs_jpeg_is_counted_each_time(monkeypatch):
    whole = _encode(_textured(640, 360), "JPEG")
    _obs(monkeypatch, whole[: len(whole) // 2])
    assert _frame._maybe_obs_frame() is None
    assert _frame._maybe_obs_frame() is None
    assert _counts() == {"undecodable": 2, "error": 0}


def test_encode_failure_is_counted_as_error(monkeypatch):
    _obs(monkeypatch, _encode(_textured(640, 360), "PNG"))

    def _boom(img):
        raise OSError("encoder exploded")
    monkeypatch.setattr(_frame, "_downscaled", _boom)
    assert _frame._maybe_obs_frame() is None
    assert _counts() == {"undecodable": 0, "error": 1}
    assert _obs_lane()["last_reason"] == "error"


# -- the quiet paths record nothing -------------------------------------------

def test_good_jpeg_records_nothing(monkeypatch):
    _obs(monkeypatch, _encode(_textured(640, 360), "JPEG"))
    assert _frame._maybe_obs_frame() is not None
    assert _counts() == {"undecodable": 0, "error": 0}
    assert _obs_lane()["last_reason"] is None


def test_good_png_reencode_records_nothing(monkeypatch):
    _obs(monkeypatch, _encode(_textured(640, 360), "PNG"))
    assert _frame._maybe_obs_frame() is not None
    assert _counts() == {"undecodable": 0, "error": 0}


@pytest.mark.parametrize("payload", [None, b""], ids=["none", "empty"])
def test_obs_yielding_nothing_records_nothing(monkeypatch, payload):
    _obs(monkeypatch, payload)
    assert _frame._maybe_obs_frame() is None
    assert _counts() == {"undecodable": 0, "error": 0}


def test_flag_off_records_nothing(monkeypatch):
    _obs(monkeypatch, b"\xff\xd8\xff-not-a-real-jpeg", enabled=False)
    assert _frame._maybe_obs_frame() is None
    assert _counts() == {"undecodable": 0, "error": 0}


def test_blank_obs_frame_stays_a_capture_skip_not_an_obs_failure(monkeypatch):
    _obs(monkeypatch, _encode(Image.new("RGB", (640, 360), (0, 0, 0)), "JPEG"))
    assert _frame._maybe_obs_frame() is None
    assert _counts() == {"undecodable": 0, "error": 0}
    assert _skips()["blank"] == 1


# -- the test helper -------------------------------------------------------------

def test_reset_zeroes_the_obs_lane_block(monkeypatch):
    _obs(monkeypatch, b"\x00" * 64)
    _frame._maybe_obs_frame()
    assert _counts()["undecodable"] == 1
    stats_mod._reset_obs_lane()
    assert _counts() == {"undecodable": 0, "error": 0}
    assert _obs_lane()["last_reason"] is None
