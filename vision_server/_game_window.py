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


def rect_area(r) -> int:
    return max(0, r[2] - r[0]) * max(0, r[3] - r[1])


def rect_intersection(a, b) -> Rect:
    l, t = max(a[0], b[0]), max(a[1], b[1])
    r, btm = min(a[2], b[2]), min(a[3], b[3])
    return (l, t, max(l, r), max(t, btm))


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


# -- Win32 (read-only) ------------------------------------------------------------

def _user32():
    import ctypes  # noqa: PLC0415 - Windows-only, imported lazily
    return ctypes.windll.user32


class _DpiAware:
    """Per-monitor DPI-aware thread context for the rect reads, restored on
    exit. A host without the API (pre-1607) reads in its default context."""

    def __enter__(self):
        self._prev = None
        try:
            import ctypes  # noqa: PLC0415
            fn = ctypes.windll.user32.SetThreadDpiAwarenessContext
            fn.restype = ctypes.c_void_p
            fn.argtypes = [ctypes.c_void_p]
            self._fn = fn
            self._prev = fn(ctypes.c_void_p(_DPI_PER_MONITOR_AWARE_V2))
        except Exception:  # noqa: BLE001
            self._prev = None
        return self

    def __exit__(self, *exc):
        if self._prev:
            try:
                import ctypes  # noqa: PLC0415
                self._fn(ctypes.c_void_p(self._prev))
            except Exception:  # noqa: BLE001
                pass
        return False


def _image_of_pid(pid: int) -> str:
    """Lower-cased image name of ``pid``, "" on any error."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
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
    user32 = ctypes.windll.user32
    rc = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    return (pt.x, pt.y, pt.x + rc.right - rc.left, pt.y + rc.bottom - rc.top)


def _enum_game_windows() -> list:
    """Visible, non-minimised top-level game windows in z-order (topmost
    first): [{"hwnd", "image", "cls", "client"}]."""
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415
    user32 = ctypes.windll.user32
    found: list = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(64)
            if not user32.GetClassNameW(hwnd, buf, 64):
                return True
            want = GAME_WINDOW_CLASSES.get(buf.value)
            if not want:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value or _image_of_pid(pid.value) != want:
                return True
            client = _client_rect(hwnd)
            if client is not None:
                found.append({"hwnd": int(hwnd), "image": want,
                              "cls": buf.value, "client": client})
        except Exception:  # noqa: BLE001 - one odd window never ends the walk
            pass
        return True

    user32.EnumWindows(proto(_cb), 0)
    return found


def primary_screen_rect() -> Optional[Rect]:
    """The primary screen in physical pixels: (0, 0, w, h), or None."""
    if sys.platform != "win32":
        return None
    try:
        with _DpiAware():
            u = _user32()
            w, h = int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        return (0, 0, w, h) if w > 0 and h > 0 else None
    except Exception:  # noqa: BLE001
        return None


def find_game_window() -> Optional[dict]:
    """The game window to capture: ``{"hwnd", "image", "cls", "client",
    "screen"}`` (``client`` and ``screen`` in physical screen pixels), or
    None (no game window, not Windows, or any error). The foreground game
    window wins; otherwise the topmost one."""
    if sys.platform != "win32":
        return None
    try:
        with _DpiAware():
            wins = _enum_game_windows()
            if not wins:
                return None
            fg = int(_user32().GetForegroundWindow() or 0)
            u = _user32()
            screen = (0, 0, int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1)))
        pick = next((w for w in wins if w["hwnd"] == fg), wins[0])
        return dict(pick, screen=screen)
    except Exception:  # noqa: BLE001
        return None
