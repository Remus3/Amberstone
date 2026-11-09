"""S156 S7 follow-up: the suite never reads the live desktop's game window.

``vision_server._frame._game_window`` is a read-only Win32 seam (S7) that
``_crop_to_game_window`` consults on every GDI grab. Left live, a test that
drives ``_fetch_frame_direct`` gets a different frame depending on whether a
League / TFT window happens to be open on the box running the suite. The
rootdir ``tests/conftest.py`` stubs the seam to ``None`` for every test, so a
test that wants a window injects one explicitly (as
tests/test_vision_game_window_s156.py does).
"""
from __future__ import annotations

from vision_server import _frame
from vision_server import _game_window as gw

_ORIGINAL_SEAM = _frame._game_window


def test_the_seam_is_stubbed_to_no_window(monkeypatch):
    # Even when the Win32 finder would report a window, the suite sees none.
    monkeypatch.setattr(gw, "find_game_window",
                        lambda: {"client": (0, 0, 10, 10), "screen": (0, 0, 10, 10)})
    assert _frame._game_window is not _ORIGINAL_SEAM
    assert _frame._game_window() is None


def test_a_test_can_still_reach_the_real_seam(monkeypatch):
    # monkeypatch.undo() drops the conftest stub (one fixture instance per test).
    monkeypatch.undo()
    assert _frame._game_window is _ORIGINAL_SEAM
