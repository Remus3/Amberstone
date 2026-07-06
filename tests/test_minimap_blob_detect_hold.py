"""Regression tests for current_minimap_dots hold-last-good on a TRANSIENT grab
failure (ZOI overlay flicker fix, 2026-07-05).

Root cause: a grab that returns crop=None (both grabbers return None on failure)
was stamped dots=[] identically to a legit-empty frame, so a momentary grab miss
flickered /api/state.zoi (and the minimap overlay) to empty ~1 Hz. The fix holds
the last-good dots for _HOLD_LAST_GOOD_S across a failed grab, while a legit-empty
frame (grab succeeded, no champions in view) still returns [] so the overlay
clears at a real game-end.
"""
import pytest

np = pytest.importorskip("numpy")

import core.minimap_blob_detect as mbd

RECT = {"x": 0, "y": 0, "w": 10, "h": 10}
DOT = {"team": "red", "x_frac": 0.5, "y_frac": 0.5, "px": 100, "confidence": 1.0}


@pytest.fixture(autouse=True)
def _reset_cache():
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[], good_wall=0.0)
    yield
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[], good_wall=0.0)


def _fake_crop():
    return np.zeros((20, 20, 3), dtype=np.uint8)


def _set_clock(monkeypatch, t):
    monkeypatch.setattr("time.time", lambda: t)


def _good_grab(monkeypatch, dots):
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda r: _fake_crop())
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda r: None)
    monkeypatch.setattr(mbd, "detect_team_dots", lambda *a, **k: list(dots))


def _grab_fails(monkeypatch):
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda r: None)
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda r: None)


def _grab_empty_frame(monkeypatch):
    # grab SUCCEEDS (non-None crop) but detects no champions -> legit empty.
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda r: _fake_crop())
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda r: None)
    monkeypatch.setattr(mbd, "detect_team_dots", lambda *a, **k: [])


def test_hold_last_good_on_transient_grab_failure(monkeypatch):
    _set_clock(monkeypatch, 100.0)
    _good_grab(monkeypatch, [DOT])
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]
    # 1s later the grab fails: must HOLD last-good, not flicker to [].
    _set_clock(monkeypatch, 101.0)
    _grab_fails(monkeypatch)
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]


def test_legit_empty_frame_returns_empty(monkeypatch):
    _set_clock(monkeypatch, 100.0)
    _good_grab(monkeypatch, [DOT])
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]
    # a real frame with no champions in view passes through as [] (NOT held).
    _set_clock(monkeypatch, 101.0)
    _grab_empty_frame(monkeypatch)
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == []


def test_hold_expires_after_window_returns_empty(monkeypatch):
    _set_clock(monkeypatch, 100.0)
    _good_grab(monkeypatch, [DOT])
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]
    # past the hold window a persistent grab failure clears (real game-end).
    _set_clock(monkeypatch, 100.0 + mbd._HOLD_LAST_GOOD_S + 0.5)
    _grab_fails(monkeypatch)
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == []


def test_exception_path_bounded_by_hold_window(monkeypatch):
    _set_clock(monkeypatch, 100.0)
    _good_grab(monkeypatch, [DOT])
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]

    def _boom(r):
        raise RuntimeError("grab blew up")

    monkeypatch.setattr(mbd, "_grab_native_minimap", _boom)
    monkeypatch.setattr(mbd, "_grab_frame_minimap", _boom)
    # within window: an exception is a failure, hold last-good.
    _set_clock(monkeypatch, 101.0)
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]
    # past window: the previously-unbounded except path now clears.
    _set_clock(monkeypatch, 105.0)
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == []


def test_present_dots_byte_identical_inertness(monkeypatch):
    # When dots are stably present every tick, the served output is unchanged
    # from the pre-fix behavior (additive-only guarantee).
    _set_clock(monkeypatch, 100.0)
    _good_grab(monkeypatch, [DOT])
    first = mbd.current_minimap_dots(RECT, ttl_s=0.0)
    _set_clock(monkeypatch, 100.5)
    second = mbd.current_minimap_dots(RECT, ttl_s=0.0)
    assert first == [DOT]
    assert second == [DOT]


def test_rect_change_clears_not_holds(monkeypatch):
    # A minimap-rect change (recalibration) must not serve dots anchored to the
    # old rect; a failed grab with a changed rect clears.
    _set_clock(monkeypatch, 100.0)
    _good_grab(monkeypatch, [DOT])
    assert mbd.current_minimap_dots(RECT, ttl_s=0.0) == [DOT]
    _set_clock(monkeypatch, 100.5)
    _grab_fails(monkeypatch)
    other = {"x": 5, "y": 5, "w": 20, "h": 20}
    assert mbd.current_minimap_dots(other, ttl_s=0.0) == []
