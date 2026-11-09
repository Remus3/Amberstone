"""S156 S7: window-aware self-grab for a WINDOWED League / TFT client.

Measured live 2026-11-08: the TFT client ran windowed - outer rect
(1275,642)-(2571,1401), client area 1280x720 at screen (1283,673), so its
right edge is 3 px past a 2560x1440 primary screen, not foreground. The
self-grab read the whole screen and every OCR region (tft/cv profile, core
vision_tesseract) is authored against a frame that IS the game surface and
scaled to the frame's size, so OCR read the desktop. The grab is now cut to
the client area (padded black past the screen edge), and a fullscreen client
keeps the old full-screen frame.

Every test injects the window (``_frame._game_window`` / the module's Win32
seams): no test reads the operator's real windows.
"""
from __future__ import annotations

import base64
import io
import sys

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from vision_server import _frame  # noqa: E402
from vision_server import _game_window as gw  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402

SCREEN = (0, 0, 2560, 1440)
CLIENT = (1283, 673, 2563, 1393)  # measured: 3 px past the right edge
MARK = (250, 30, 200)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    from core import obs_frame_source as ofs
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda *a, **k: False)
    monkeypatch.setattr(_frame, "_game_window", lambda: None)
    yield
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()


def _ramp(w, h):
    img = Image.new("L", (w, h))
    img.putdata([int(255 * (x / max(1, w - 1))) for _y in range(h) for x in range(w)])
    return img.convert("RGB")


def _desktop_with_game(client=CLIENT, game=None, screen=SCREEN):
    """A screen grab: a flat desktop with the game surface pasted at
    ``client`` (clipped at the screen edge like a real BitBlt)."""
    desk = Image.new("RGB", (screen[2] - screen[0], screen[3] - screen[1]),
                     (40, 90, 160))
    game = game or _ramp(client[2] - client[0], client[3] - client[1])
    desk.paste(game, (client[0] - screen[0], client[1] - screen[1]))
    return desk, game


def _win(client=CLIENT, screen=SCREEN):
    return {"hwnd": 1, "image": "tftclient-win64-shipping.exe",
            "cls": "UnrealWindow", "client": client, "screen": screen}


# -- plan_crop: the rect math --------------------------------------------------

def test_plan_measured_windowed_tft_client():
    plan = gw.plan_crop(CLIENT, SCREEN)
    assert plan["mode"] == "windowed"
    assert plan["bbox"] == CLIENT
    assert plan["visible"] == pytest.approx(1277 / 1280, abs=1e-4)


def test_plan_fullscreen_client_needs_no_crop():
    assert gw.plan_crop(SCREEN, SCREEN) == {"mode": "fullscreen"}
    # a client larger than the screen that covers it is fullscreen too
    assert gw.plan_crop((-8, -8, 2568, 1448), SCREEN) == {"mode": "fullscreen"}


def test_plan_partly_off_the_top_left_keeps_full_client_size():
    plan = gw.plan_crop((-200, -100, 1080, 620), SCREEN)
    assert plan["mode"] == "windowed"
    assert plan["bbox"] == (-200, -100, 1080, 620)
    assert plan["visible"] == pytest.approx((1080 * 620) / (1280 * 720), abs=1e-4)


def test_plan_offset_screen_origin():
    """A grab whose origin is not (0, 0) (an all-screens grab): the bbox is
    relative to the grab."""
    plan = gw.plan_crop((100, 50, 1380, 770), (-1920, 0, 2560, 1440))
    assert plan["bbox"] == (2020, 50, 3300, 770)


@pytest.mark.parametrize("client", [
    (2400, 1300, 3680, 2020),  # mostly on another monitor: under half visible
    (5000, 0, 6280, 720),      # wholly off this screen
    (0, 0, 160, 90),           # too small to be a game surface
    (100, 100, 100, 500),      # empty
    None, "junk", (0, 0, 1280.0, 720), (True, 0, 1280, 720),
])
def test_plan_refuses(client):
    assert gw.plan_crop(client, SCREEN) is None


def test_crop_pads_the_off_screen_part_black():
    desk, game = _desktop_with_game()
    out = gw.crop_to_plan(desk, gw.plan_crop(CLIENT, SCREEN))
    assert out.size == (1280, 720)
    assert out.getpixel((0, 0)) == game.getpixel((0, 0))
    assert out.getpixel((1276, 400)) == game.getpixel((1276, 400))
    assert out.getpixel((1279, 400)) == (0, 0, 0)  # the 3 px past the edge


def test_crop_to_plan_passes_fullscreen_and_none_through():
    desk, _ = _desktop_with_game()
    assert gw.crop_to_plan(desk, {"mode": "fullscreen"}) is desk
    assert gw.crop_to_plan(desk, None) is desk


# -- _frame: the grab is cut to the client area -------------------------------

def test_windowed_client_is_cut_out(monkeypatch):
    desk, game = _desktop_with_game()
    monkeypatch.setattr(_frame, "_game_window", lambda: _win())
    out = _frame._crop_to_game_window(desk)
    assert out.size == (1280, 720)
    assert out.getpixel((640, 360)) == game.getpixel((640, 360))
    lc = _frame.last_capture_window()
    assert lc["mode"] == "windowed" and lc["client"] == CLIENT
    assert lc["visible"] == pytest.approx(0.9977, abs=1e-4)


def test_fullscreen_client_keeps_the_full_frame(monkeypatch):
    desk, _ = _desktop_with_game()
    monkeypatch.setattr(_frame, "_game_window", lambda: _win(client=SCREEN))
    assert _frame._crop_to_game_window(desk) is desk
    assert _frame.last_capture_window()["mode"] == "fullscreen"


def test_no_game_window_keeps_the_full_frame():
    desk, _ = _desktop_with_game()
    assert _frame._crop_to_game_window(desk) is desk
    assert _frame.last_capture_window()["mode"] == "screen"


def test_grab_of_another_size_is_never_cut(monkeypatch):
    """A grab that is not the screen the window was measured on (a
    DPI-virtualised grab, a test stub) keeps the full frame."""
    monkeypatch.setattr(_frame, "_game_window", lambda: _win())
    small = _ramp(1920, 1080)
    assert _frame._crop_to_game_window(small) is small
    assert _frame.last_capture_window()["mode"] == "screen"


def test_window_seam_error_keeps_the_full_frame(monkeypatch):
    def _boom():
        raise RuntimeError("win32 gone")
    monkeypatch.setattr(_frame, "_game_window", _boom)
    desk, _ = _desktop_with_game()
    assert _frame._crop_to_game_window(desk) is desk
    monkeypatch.setattr(_frame, "_game_window", lambda: {"client": "x"})
    assert _frame._crop_to_game_window(desk) is desk


def test_default_window_seam_is_fail_soft(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(gw, "find_game_window", lambda: 1 / 0)
    assert _frame._game_window() is None


def _gdi(monkeypatch, img):
    from PIL import ImageGrab
    grabs = []

    def _grab(*a, **k):
        grabs.append((a, k))
        return img
    monkeypatch.setattr(ImageGrab, "grab", _grab)
    monkeypatch.setattr(_frame, "_input_desktop_locked", lambda: False)
    monkeypatch.setattr(_frame, "_league_foreground", lambda: True)
    return grabs


def _decode(frame):
    return Image.open(io.BytesIO(base64.b64decode(frame["b64"]))).convert("RGB")


def test_self_grab_serves_the_windowed_game_surface(monkeypatch):
    game = Image.new("RGB", (1280, 720), (20, 20, 20))
    game.paste(Image.new("RGB", (200, 100), MARK), (100, 50))
    game.paste(_ramp(400, 300), (800, 300))
    desk, _ = _desktop_with_game(game=game)
    grabs = _gdi(monkeypatch, desk)
    monkeypatch.setattr(_frame, "_game_window", lambda: _win())
    frame = _frame._fetch_frame_direct()
    assert grabs == [((), {})]  # still ONE plain primary-screen grab
    assert (frame["width"], frame["height"]) == (1280, 720)
    px = _decode(frame).getpixel((200, 100))
    assert all(abs(a - b) <= 24 for a, b in zip(px, MARK))  # JPEG q85


def test_self_grab_fullscreen_unchanged(monkeypatch):
    desk = _ramp(2560, 1440)
    _gdi(monkeypatch, desk)
    monkeypatch.setattr(_frame, "_game_window", lambda: _win(client=SCREEN))
    frame = _frame._fetch_frame_direct()
    assert (frame["width"], frame["height"]) == (1280, 720)


def test_foreground_gate_still_runs_first(monkeypatch):
    desk, _ = _desktop_with_game()
    grabs = _gdi(monkeypatch, desk)
    monkeypatch.setattr(_frame, "_league_foreground", lambda: False)
    monkeypatch.setattr(_frame, "_game_window", lambda: _win())
    assert _frame._fetch_frame_direct() is None
    assert grabs == []


# -- the regions land on the game surface -------------------------------------

def test_tft_profile_regions_land_on_the_windowed_client(monkeypatch):
    """The TFT profile scales every box to the frame's size. On the cut
    frame a box reads the game's own pixels; on the uncut desktop the same
    box (scaled to 2560x1440) reads the desktop - the reported defect."""
    from tft.cv.profile import load_profile
    prof = load_profile()
    if prof is None or not prof.boxes:
        pytest.skip("no TFT region profile in this tree")
    name = sorted(prof.boxes)[0]
    l, t, r, b = prof.box(name, (1280, 720))
    game = Image.new("RGB", (1280, 720), (20, 20, 20))
    game.paste(Image.new("RGB", (r - l, b - t), MARK), (l, t))
    desk, _ = _desktop_with_game(game=game)
    monkeypatch.setattr(_frame, "_game_window", lambda: _win())
    cut = _frame._crop_to_game_window(desk)
    cl, ct, cr, cb = prof.box(name, cut.size)
    assert cut.getpixel(((cl + cr) // 2, (ct + cb) // 2)) == MARK
    fl, ft, fr, fb = prof.box(name, desk.size)
    assert desk.getpixel(((fl + fr) // 2, (ft + fb) // 2)) != MARK


# -- find_game_window (Win32 seams injected) ----------------------------------

class _FakeUser32:
    def __init__(self, fg=0, w=2560, h=1440):
        self._fg, self._w, self._h = fg, w, h

    def GetForegroundWindow(self):  # noqa: N802 - Win32 name
        return self._fg

    def GetSystemMetrics(self, i):  # noqa: N802
        return self._w if i == 0 else self._h


def _wins():
    return [{"hwnd": 11, "image": "league of legends.exe",
             "cls": "RiotWindowClass", "client": (0, 0, 1920, 1080)},
            {"hwnd": 22, "image": "tftclient-win64-shipping.exe",
             "cls": "UnrealWindow", "client": CLIENT}]


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path")
def test_find_prefers_the_foreground_game_window(monkeypatch):
    monkeypatch.setattr(gw, "_enum_game_windows", _wins)
    monkeypatch.setattr(gw, "_user32", lambda: _FakeUser32(fg=22))
    w = gw.find_game_window()
    assert w["hwnd"] == 22 and w["client"] == CLIENT and w["screen"] == SCREEN


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path")
def test_find_falls_back_to_the_topmost(monkeypatch):
    monkeypatch.setattr(gw, "_enum_game_windows", _wins)
    monkeypatch.setattr(gw, "_user32", lambda: _FakeUser32(fg=999))
    assert gw.find_game_window()["hwnd"] == 11


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path")
def test_find_none_without_game_windows_or_on_error(monkeypatch):
    monkeypatch.setattr(gw, "_enum_game_windows", list)
    assert gw.find_game_window() is None

    def _boom():
        raise OSError("no user32")
    monkeypatch.setattr(gw, "_enum_game_windows", _boom)
    assert gw.find_game_window() is None


def test_find_none_off_windows(monkeypatch):
    monkeypatch.setattr(gw.sys, "platform", "linux")
    assert gw.find_game_window() is None
    assert gw.primary_screen_rect() is None


def test_game_classes_map_to_game_images_only():
    """A class is a game window only when the GAME image owns it: the League
    lobby client (RCLIENT, LeagueClientUx.exe) is never a capture target."""
    assert gw.GAME_WINDOW_CLASSES == {
        "UnrealWindow": "tftclient-win64-shipping.exe",
        "RiotWindowClass": "league of legends.exe"}
    assert "RCLIENT" not in gw.GAME_WINDOW_CLASSES
