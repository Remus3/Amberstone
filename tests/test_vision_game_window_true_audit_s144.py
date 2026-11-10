"""s144 true-audit of ``vision_server/_game_window.py`` (S144-T-648..651).

Findings pinned here, each RED against the S156 S7 module:

- S144-T-648: the EnumWindows callback hands Win32 calls a raw Python int.
  ctypes converts an undeclared argument as a C ``int``, so an HWND with
  bit 31 set (a sign-extended 64-bit value, e.g. 0xFFFFFFFF8A3C0F12) raised
  ``ArgumentError: int too long to convert`` inside the callback, the
  blanket except swallowed it, and that game window was SKIPPED - the
  windowed client went uncropped and OCR read nothing, the exact S7 defect.
- S144-T-649: ``GetForegroundWindow`` returned through the default C ``long``
  restype, so the same window read as -1975775470 there and as
  18446744071733776146 from the callback: the foreground preference was
  lost and the topmost game window won instead.
- S144-T-650: ``_DpiAware`` set ``restype`` / ``argtypes`` on the SHARED
  ``ctypes.windll.user32`` function object, a process-wide mutation every
  other caller of that function inherited.
- S144-T-651: ``find_game_window`` read the screen metrics unchecked and
  returned ``screen=(0, 0, 0, 0)`` on a failed read, against its own
  docstring ("in physical screen pixels") and against
  ``primary_screen_rect``, which already refused that.

Real-Win32 tests are read-only: they query a window handle that does not
exist and the calling thread's own DPI context, and restore it.
"""
from __future__ import annotations

import ctypes
import sys

import pytest

from vision_server import _game_window as gw

win32_only = pytest.mark.skipif(sys.platform != "win32", reason="Win32 path")

# A window handle with bit 31 set, as EnumWindows (HWND = c_void_p) delivers
# it on 64-bit Windows, and as an undeclared C long restype returns it.
HIGH = 0x8A3C0F12
HIGH_SIGN_EXTENDED = 0xFFFFFFFF00000000 | HIGH
HIGH_AS_C_LONG = HIGH - (1 << 32)
CLIENT = (1283, 673, 2563, 1393)


# -- S144-T-648 / 649: handle normalisation ------------------------------------

def test_hwnd_key_maps_every_spelling_of_one_handle_to_one_key():
    assert gw._hwnd_key(HIGH_SIGN_EXTENDED) == HIGH
    assert gw._hwnd_key(HIGH_AS_C_LONG) == HIGH
    assert gw._hwnd_key(HIGH) == HIGH
    assert gw._hwnd_key(22) == 22


@pytest.mark.parametrize("junk", [None, 0, "x", 1.5, True, [], object()])
def test_hwnd_key_of_junk_is_zero_never_raises(junk):
    assert gw._hwnd_key(junk) == 0


class _FakeUser32:
    def __init__(self, fg=0, w=2560, h=1440):
        self._fg, self._w, self._h = fg, w, h

    def GetForegroundWindow(self):  # noqa: N802 - Win32 name
        return self._fg

    def GetSystemMetrics(self, i):  # noqa: N802
        return self._w if i == 0 else self._h


def _two_windows():
    return [{"hwnd": 11, "image": "league of legends.exe",
             "cls": "RiotWindowClass", "client": (0, 0, 1920, 1080)},
            {"hwnd": HIGH_SIGN_EXTENDED, "image": "tftclient-win64-shipping.exe",
             "cls": "UnrealWindow", "client": CLIENT}]


@win32_only
def test_find_matches_a_high_bit_foreground_window(monkeypatch):
    """S144-T-649: the foreground TFT window (second in z-order) wins even
    when its handle reads differently through the two ctypes paths."""
    monkeypatch.setattr(gw, "_enum_game_windows", _two_windows)
    monkeypatch.setattr(gw, "_user32", lambda: _FakeUser32(fg=HIGH_AS_C_LONG))
    w = gw.find_game_window()
    assert w is not None and w["client"] == CLIENT
    assert w["image"] == "tftclient-win64-shipping.exe"


@win32_only
def test_declared_prototypes_accept_a_high_bit_handle():
    """S144-T-648: every handle-taking call the walk makes is declared, so a
    high-bit HWND reaches Win32 (here: a non-existent window -> 0) instead
    of raising in ctypes' default int conversion."""
    u = gw._user32()
    assert u.IsWindowVisible(HIGH_SIGN_EXTENDED) == 0
    assert u.IsIconic(HIGH_SIGN_EXTENDED) == 0
    buf = ctypes.create_unicode_buffer(256)
    assert u.GetClassNameW(HIGH_SIGN_EXTENDED, buf, 256) == 0
    assert u.GetForegroundWindow.restype is not ctypes.c_long


class _WalkUser32:
    """Fake user32 for ``_window_entry``: refuses an undeclared big int the
    way ctypes' default conversion does, so the entry logic must normalise
    nothing it passes on - it hands the handle through unchanged."""

    def __init__(self, cls="UnrealWindow", visible=True, iconic=False, pid=4242):
        self.cls, self.visible, self.iconic, self.pid = cls, visible, iconic, pid
        self.seen = []

    def IsWindowVisible(self, h):  # noqa: N802
        self.seen.append(h)
        return self.visible

    def IsIconic(self, h):  # noqa: N802
        return self.iconic

    def GetClassNameW(self, h, buf, n):  # noqa: N802
        buf.value = self.cls[: n - 1]
        return len(buf.value)

    def GetWindowThreadProcessId(self, h, ref):  # noqa: N802
        ref._obj.value = self.pid
        return 1


@pytest.fixture
def walk(monkeypatch):
    monkeypatch.setattr(gw, "_image_of_pid",
                        lambda pid: "tftclient-win64-shipping.exe" if pid == 4242 else "x.exe")
    monkeypatch.setattr(gw, "_client_rect", lambda h: CLIENT)


def test_window_entry_keys_a_high_bit_window(walk):
    u = _WalkUser32()
    e = gw._window_entry(u, HIGH_SIGN_EXTENDED)
    assert e == {"hwnd": HIGH, "image": "tftclient-win64-shipping.exe",
                 "cls": "UnrealWindow", "client": CLIENT}
    assert u.seen == [HIGH_SIGN_EXTENDED]


@pytest.mark.parametrize("kw", [
    {"visible": False}, {"iconic": True}, {"cls": "RCLIENT"},
    {"cls": "Chrome_WidgetWin_1"}, {"pid": 0}, {"pid": 7}])
def test_window_entry_refuses_non_game_windows(walk, kw):
    assert gw._window_entry(_WalkUser32(**kw), HIGH) is None


def test_window_entry_null_handle_is_none(walk):
    assert gw._window_entry(_WalkUser32(), None) is None
    assert gw._window_entry(_WalkUser32(), 0) is None


def test_window_entry_without_a_client_rect_is_none(walk, monkeypatch):
    monkeypatch.setattr(gw, "_client_rect", lambda h: None)
    assert gw._window_entry(_WalkUser32(), HIGH) is None


# -- S144-T-650: no process-wide ctypes mutation -------------------------------

@win32_only
def test_dpi_context_leaves_the_shared_windll_untouched(monkeypatch):
    shared = ctypes.windll.user32.SetThreadDpiAwarenessContext
    # monkeypatch puts the shared object's own values back afterwards
    monkeypatch.setattr(shared, "argtypes", None)
    monkeypatch.setattr(shared, "restype", ctypes.c_int)
    with gw._DpiAware():
        pass
    assert shared.argtypes is None
    assert shared.restype is ctypes.c_int


@win32_only
def test_dpi_context_is_restored_on_exit_even_after_an_error():
    u = ctypes.WinDLL("user32")
    u.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    u.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    before = u.GetThreadDpiAwarenessContext()
    with pytest.raises(RuntimeError):
        with gw._DpiAware():
            raise RuntimeError("boom")
    assert u.AreDpiAwarenessContextsEqual(before, u.GetThreadDpiAwarenessContext())


# -- S144-T-651: junk screen metrics -------------------------------------------

@win32_only
@pytest.mark.parametrize("w,h", [(0, 0), (0, 1440), (2560, -1)])
def test_find_refuses_a_failed_screen_read(monkeypatch, w, h):
    monkeypatch.setattr(gw, "_enum_game_windows", _two_windows)
    monkeypatch.setattr(gw, "_user32", lambda: _FakeUser32(fg=11, w=w, h=h))
    assert gw.find_game_window() is None


@win32_only
def test_find_and_primary_screen_agree_on_the_screen(monkeypatch):
    monkeypatch.setattr(gw, "_enum_game_windows", _two_windows)
    monkeypatch.setattr(gw, "_user32", lambda: _FakeUser32(fg=11))
    assert gw.find_game_window()["screen"] == gw.primary_screen_rect() == (0, 0, 2560, 1440)
