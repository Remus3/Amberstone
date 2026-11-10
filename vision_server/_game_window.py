# arch: game window rect + client-area crop plan for the self-grab | section=vision | frozen=no
"""Locate the League / TFT game window and plan a crop to its client area.

S156 S7 (measured live 2026-11-08): the operator runs the standalone TFT
client WINDOWED - an ``UnrealWindow`` titled ``TFT`` of
``TFTClient-Win64-Shipping.exe``, outer rect 1296x759 at (1275,642), client
area 1280x720 at screen (1283,673), so its right edge sits 3 px past a
2560x1440 primary screen. The vision self-grab (``vision_server/_frame.py``)
read the whole primary screen, and every OCR region (``tft/cv`` profile,
``core/vision_tesseract`` for SR) is authored against a frame that IS the
game surface and scaled to the frame's size - so a windowed client read as a
1280x720 game scaled into a quarter of a 2560x1440 desktop, and OCR read
nothing useful.

This module answers "where is the game's client area on the primary screen"
so the grab can be cropped to it: the cropped frame is the game surface at
the window's own size, and the consumers' existing size-scaling puts every
region where it belongs. A fullscreen client (client area == the screen)
needs no crop and the frame is the old full-screen grab, byte for byte.

Read-only Win32 via ctypes (no new dependency): window class / title /
rects, the owning pid and its image name (PROCESS_QUERY_LIMITED_INFORMATION,
as core.vision_profiles' foreground probe does). Nothing is sent to the game
window and nothing is injected (Vanguard). Rects are read under a per-monitor
DPI-aware thread context so they are physical pixels, the same space
PIL.ImageGrab grabs in. Every function is fail-soft: an error is "no window"
and the caller keeps the full-screen grab.

s144 true-audit (S144-T-648..651): every Win32 call goes through PRIVATE
``ctypes.WinDLL`` instances with declared prototypes (``_win32``). The
shared ``ctypes.windll`` objects are process-wide, so declaring types on
them would leak into every other caller; and an UNDECLARED call converts a
Python int as a C ``int``, so a window handle with bit 31 set raised inside
the enumeration callback and that game window was silently skipped. Window
handles are compared by ``_hwnd_key`` (their low 32 bits - the only
significant ones on 64-bit Windows), because the callback and
``GetForegroundWindow`` can spell one handle two ways.
"""
from __future__ import annotations

import sys
from typing import Optional

Rect = tuple  # (left, top, right, bottom), right / bottom exclusive

# Window class -> the game image that must own it. Measured: TFT's game
# window is class "UnrealWindow" (S134 P0 and S156). League's in-game window
# class "RiotWindowClass" is not re-measured this session (no live SR game);
# the image-name check below is what makes a window a game window either way.
GAME_WINDOW_CLASSES = {
    "UnrealWindow": "tftclient-win64-shipping.exe",
    "RiotWindowClass": "league of legends.exe",
}
# A windowed client less visible than this on the primary screen (moved to
# another monitor) is not cropped: the old full-screen grab stands.
MIN_VISIBLE_FRACTION = 0.5
# A client area smaller than this is not a game surface (a minimised or
# collapsed window reports 0x0 or a tiny rect).
MIN_CLIENT_W, MIN_CLIENT_H = 320, 180

_DPI_PER_MONITOR_AWARE_V2 = -4
# Window class names are at most 256 characters (WNDCLASS docs).
_CLASS_NAME_CHARS = 256
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def rect_area(r) -> int:
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def rect_intersection(a, b) -> Rect:
    left, t = max(a[0], b[0]), max(a[1], b[1])
    r, btm = min(a[2], b[2]), min(a[3], b[3])
    return (left, t, max(left, r), max(t, btm))


def _valid_rect(r) -> bool:
    return (isinstance(r, (tuple, list)) and len(r) == 4
            and all(isinstance(v, int) and not isinstance(v, bool) for v in r)
            and r[2] > r[0] and r[3] > r[1])


def plan_crop(client, screen) -> Optional[dict]:
    """How to cut the game surface out of a grab of ``screen``.

    ``client`` is the game's client area and ``screen`` the grabbed screen,
    both in screen coordinates. Returns None when there is nothing to cut
    (no / junk / tiny client, or one mostly off this screen), else
    ``{"mode": "fullscreen"}`` when the client covers the whole screen, or
    ``{"mode": "windowed", "bbox": (l, t, r, b), "visible": f}`` where
    ``bbox`` is the client relative to the grab's origin - it may extend past
    the grab; PIL pads that part black, so the cut keeps the client's full
    size and every region stays where the game drew it.
    """
    if not (_valid_rect(client) and _valid_rect(screen)):
        return None
    cw, ch = client[2] - client[0], client[3] - client[1]
    if cw < MIN_CLIENT_W or ch < MIN_CLIENT_H:
        return None
    visible = rect_area(rect_intersection(client, screen)) / float(cw * ch)
    if rect_intersection(client, screen) == tuple(screen):
        # the client covers the whole screen: borderless / exclusive fullscreen
        return {"mode": "fullscreen"}
    if visible < MIN_VISIBLE_FRACTION:
        return None
    ox, oy = screen[0], screen[1]
    bbox = (client[0] - ox, client[1] - oy, client[2] - ox, client[3] - oy)
    return {"mode": "windowed", "bbox": bbox, "visible": round(visible, 4)}


def crop_to_plan(img, plan):
    """``img`` cut to a windowed ``plan`` (``plan_crop``), else ``img``."""
    if not plan or plan.get("mode") != "windowed":
        return img
    return img.crop(tuple(plan["bbox"]))


def _hwnd_key(hwnd) -> int:
    """One comparable key per window handle: its low 32 bits, 0 for junk.

    The enumeration callback (HWND = c_void_p) hands a sign-extended handle
    over as an unsigned 64-bit int, a C ``long`` restype as a negative one;
    both name the same window."""
    if isinstance(hwnd, bool) or not isinstance(hwnd, int):
        return 0
    return hwnd & 0xFFFFFFFF


# -- Win32 (read-only) ------------------------------------------------------------

_WIN32: Optional[tuple] = None


def _win32() -> tuple:
    """``(user32, kernel32)``: private WinDLL instances with every function
    this module calls declared, built once. Raises off Windows."""
    global _WIN32
    if _WIN32 is not None:
        return _WIN32
    import ctypes  # noqa: PLC0415 - Windows-only, imported lazily
    from ctypes import wintypes  # noqa: PLC0415

    u = ctypes.WinDLL("user32")
    k = ctypes.WinDLL("kernel32")
    hwnd, handle, dword = wintypes.HWND, wintypes.HANDLE, wintypes.DWORD

    def proto(fn, restype, *argtypes):
        fn.restype, fn.argtypes = restype, list(argtypes)

    proto(u.IsWindowVisible, wintypes.BOOL, hwnd)
    proto(u.IsIconic, wintypes.BOOL, hwnd)
    proto(u.GetClassNameW, ctypes.c_int, hwnd, wintypes.LPWSTR, ctypes.c_int)
    proto(u.GetWindowThreadProcessId, dword, hwnd, ctypes.POINTER(dword))
    proto(u.GetClientRect, wintypes.BOOL, hwnd, ctypes.POINTER(wintypes.RECT))
    proto(u.ClientToScreen, wintypes.BOOL, hwnd, ctypes.POINTER(wintypes.POINT))
    proto(u.GetForegroundWindow, hwnd)
    proto(u.GetSystemMetrics, ctypes.c_int, ctypes.c_int)
    proto(u.EnumWindows, wintypes.BOOL,
          ctypes.WINFUNCTYPE(wintypes.BOOL, hwnd, wintypes.LPARAM), wintypes.LPARAM)
    try:  # Windows 10 1607+; absent before, and _DpiAware tolerates that
        proto(u.SetThreadDpiAwarenessContext, ctypes.c_void_p, ctypes.c_void_p)
    except AttributeError:
        pass
    proto(k.OpenProcess, handle, dword, wintypes.BOOL, dword)
    proto(k.QueryFullProcessImageNameW, wintypes.BOOL,
          handle, dword, wintypes.LPWSTR, ctypes.POINTER(dword))
    proto(k.CloseHandle, wintypes.BOOL, handle)
    _WIN32 = (u, k)
    return _WIN32


def _user32():
    return _win32()[0]


class _DpiAware:
    """Per-monitor DPI-aware thread context for the rect reads, restored on
    exit (also when the body raises). A host without the API (pre-1607)
    reads in its default context."""

    def __enter__(self):
        self._prev = None
        self._fn = None
        try:
            fn = _win32()[0].SetThreadDpiAwarenessContext
            self._prev = fn(_DPI_PER_MONITOR_AWARE_V2)
            self._fn = fn
        except Exception:  # noqa: BLE001 - no API / not Windows: default context
            self._prev = None
        return self

    def __exit__(self, *exc):
        if self._prev and self._fn is not None:
            try:
                self._fn(self._prev)
            except Exception:  # noqa: BLE001 - restore is best effort
                pass
        return False


def _image_of_pid(pid: int) -> str:
    """Lower-cased image name of ``pid``, "" on any error."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    kernel32 = _win32()[1]
    h = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(h)


def _client_rect(hwnd) -> Optional[Rect]:
    """The client area of ``hwnd`` in screen coordinates, or None."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    user32 = _user32()
    rc = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return (pt.x, pt.y, pt.x + rc.right - rc.left, pt.y + rc.bottom - rc.top)


def _window_entry(user32, hwnd) -> Optional[dict]:
    """``{"hwnd", "image", "cls", "client"}`` when ``hwnd`` is a visible,
    non-minimised game window owned by its game image, else None. The
    handle is passed to Win32 unchanged (the prototypes are declared) and
    keyed by ``_hwnd_key``."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
        return None
    buf = ctypes.create_unicode_buffer(_CLASS_NAME_CHARS)
    if not user32.GetClassNameW(hwnd, buf, _CLASS_NAME_CHARS):
        return None
    want = GAME_WINDOW_CLASSES.get(buf.value)
    if not want:
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value or _image_of_pid(pid.value) != want:
        return None
    client = _client_rect(hwnd)
    if client is None:
        return None
    return {"hwnd": _hwnd_key(hwnd), "image": want, "cls": buf.value,
            "client": client}


def _enum_game_windows() -> list:
    """Visible, non-minimised top-level game windows in z-order (topmost
    first): [{"hwnd", "image", "cls", "client"}]."""
    user32 = _user32()
    found: list = []

    def _cb(hwnd, _lparam):
        try:
            entry = _window_entry(user32, hwnd)
            if entry is not None:
                found.append(entry)
        except Exception:  # noqa: BLE001 - one odd window never ends the walk
            pass
        return True

    user32.EnumWindows(user32.EnumWindows.argtypes[0](_cb), 0)
    return found


def _screen_of(user32) -> Optional[Rect]:
    """The primary screen ``(0, 0, w, h)`` from ``user32``'s metrics, or None
    when the read failed (a zero or negative size)."""
    w, h = int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    return (0, 0, w, h) if w > 0 and h > 0 else None


def primary_screen_rect() -> Optional[Rect]:
    """The primary screen in physical pixels: (0, 0, w, h), or None."""
    if sys.platform != "win32":
        return None
    try:
        with _DpiAware():
            return _screen_of(_user32())
    except Exception:  # noqa: BLE001
        return None


def find_game_window() -> Optional[dict]:
    """The game window to capture: ``{"hwnd", "image", "cls", "client",
    "screen"}`` (``client`` and ``screen`` in physical screen pixels), or
    None (no game window, a failed screen read, not Windows, or any error).
    The foreground game window wins; otherwise the topmost one."""
    if sys.platform != "win32":
        return None
    try:
        with _DpiAware():
            wins = _enum_game_windows()
            if not wins:
                return None
            u = _user32()
            fg = _hwnd_key(u.GetForegroundWindow())
            screen = _screen_of(u)
        if screen is None:
            return None
        pick = next((w for w in wins if fg and _hwnd_key(w["hwnd"]) == fg), wins[0])
        return dict(pick, screen=screen)
    except Exception:  # noqa: BLE001
        return None
