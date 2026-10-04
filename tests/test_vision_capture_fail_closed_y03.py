"""Y-03: vision capture fails closed (external reference K).

Three named skip reasons, ONE ``reason`` vocabulary shared by the in-process
self-grab (vision_server/_frame.py) and the standalone upload agent
(tools/screen_agent.py):

  locked          - the input desktop cannot be opened (locked workstation or a
                    secure desktop such as UAC). Applies to every source.
  not_foreground  - League of Legends.exe does not hold the foreground window
                    and has not held it within a short grace window. GDI path
                    only: the OBS ``source='obs'`` lane captures a scene, not
                    the desktop, so it is unaffected.
  blank           - the frame is near-uniform by luminance range on a
                    downscaled grey copy.

All three are counted in vision stats (``get_stats()["capture_skip"]``).

The blank threshold was MEASURED (2026-10-04, this slice): the twelve real
2560x1440 League stills in data/vision_calib_reference (including the grey
self_dead death screen) have a 64-px-thumbnail luminance range of 118..184
(re-measured with the shipped core.screen_grab.luma_range);
uniform frames at 0/16/128/255 grey, JPEG q85 at 1280x720 and 2560x1440, have
range 0. The cut-off sits far from both clusters.

The probes read only the foreground window's owning image name and whether
the input desktop opens; nothing is injected (Vanguard).
"""
from __future__ import annotations

import base64
import importlib.util
import io
import shutil
import time

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from core import screen_grab  # noqa: E402
from vision_server import _frame  # noqa: E402
from vision_server import _stats as stats_mod  # noqa: E402

REASONS = ("locked", "not_foreground", "blank")


def _textured(w=1280, h=720):
    """A non-uniform frame: horizontal grey ramp (luminance range ~255)."""
    img = Image.new("L", (w, h))
    img.putdata([int(255 * (x / max(1, w - 1))) for _y in range(h) for x in range(w)])
    return img.convert("RGB")


def _jpeg_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()
    # OBS lane off unless a test turns it on.
    from core import obs_frame_source as ofs
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: False)
    # Never write a reference still from a test.
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda *a, **k: False)
    yield
    _frame._reset_self_read_state()
    stats_mod._reset_capture_skips()


def _counts():
    cs = stats_mod.get_stats()["capture_skip"]
    return {r: cs[r] for r in REASONS}


# -- the reason vocabulary + stats exposure ----------------------------------

def test_reason_vocabulary_is_exactly_three_and_non_empty():
    assert tuple(stats_mod.CAPTURE_SKIP_REASONS) == REASONS
    assert len(stats_mod.CAPTURE_SKIP_REASONS) == 3  # empty enumeration fails


def test_stats_expose_three_counters_at_zero():
    cs = stats_mod.get_stats()["capture_skip"]
    assert _counts() == {"locked": 0, "not_foreground": 0, "blank": 0}
    assert cs["last_reason"] is None


def test_record_capture_skip_counts_and_names_last_reason():
    for r in REASONS:
        stats_mod._record_capture_skip(r)
    stats_mod._record_capture_skip("blank")
    cs = stats_mod.get_stats()["capture_skip"]
    assert _counts() == {"locked": 1, "not_foreground": 1, "blank": 2}
    assert cs["last_reason"] == "blank"
    assert cs["last_ts"] > 0


def test_record_capture_skip_rejects_unknown_reason():
    with pytest.raises(ValueError):
        stats_mod._record_capture_skip("sleepy")


def test_stats_snapshot_is_a_copy():
    snap = stats_mod.get_stats()["capture_skip"]
    snap["blank"] = 999
    assert stats_mod.get_stats()["capture_skip"]["blank"] == 0


# -- blank detector (shared core helper) ------------------------------------

@pytest.mark.parametrize("val", [0, 16, 128, 255])
def test_uniform_frames_are_blank(val):
    img = Image.new("RGB", (2560, 1440), (val, val, val))
    assert screen_grab.frame_is_blank(img)
    # Survives the JPEG round trip the self-grab uses.
    assert screen_grab.frame_is_blank(Image.open(io.BytesIO(_jpeg_bytes(img))))


def test_textured_frame_is_not_blank():
    assert not screen_grab.frame_is_blank(_textured())


def test_threshold_boundary():
    """Two flat halves differing by exactly the threshold are blank; one more
    grey level is not. Pins the comparison direction (<=)."""
    t = screen_grab.BLANK_LUMA_RANGE_MAX

    def halves(delta):
        img = Image.new("L", (1280, 720), 40)
        img.paste(40 + delta, (640, 0, 1280, 720))
        return img.convert("RGB")
    assert screen_grab.frame_is_blank(halves(t))
    assert not screen_grab.frame_is_blank(halves(t + 1))


def test_threshold_sits_well_below_measured_real_frames():
    # Lowest measured real League still = 118 (see module docstring).
    assert 0 < screen_grab.BLANK_LUMA_RANGE_MAX < 118 // 4


# -- locked probe (shared core helper) --------------------------------------

def test_input_desktop_locked_when_open_fails():
    closed = []
    assert screen_grab.input_desktop_locked(
        _open_input_desktop=lambda: 0, _close_desktop=closed.append) is True
    assert closed == []


def test_input_desktop_unlocked_closes_handle():
    closed = []
    assert screen_grab.input_desktop_locked(
        _open_input_desktop=lambda: 1234, _close_desktop=closed.append) is False
    assert closed == [1234]


def test_input_desktop_probe_error_reads_locked():
    def boom():
        raise OSError("probe failed")
    assert screen_grab.input_desktop_locked(
        _open_input_desktop=boom, _close_desktop=lambda h: None) is True


def test_grab_native_names_locked_reason(monkeypatch):
    monkeypatch.setattr(screen_grab, "input_desktop_locked", lambda: True)
    out = screen_grab.grab_native()
    assert out["ok"] is False
    assert out["reason"] == "locked"


# -- _maybe_self_grab: locked ----------------------------------------------

def test_locked_desktop_returns_none_without_grabbing(monkeypatch):
    calls = []
    monkeypatch.setattr(_frame, "_input_desktop_locked", lambda: True)
    monkeypatch.setattr(_frame, "_fetch_frame_direct",
                        lambda: calls.append(1) or {"b64": "x"})
    assert _frame._maybe_self_grab() is None
    assert calls == []
    assert _counts()["locked"] == 1
    assert _frame.last_capture_skip()["reason"] == "locked"
    assert _frame.get_latest_frame().get("b64") is None


# -- GDI path: not_foreground + grace ----------------------------------------

def _gdi(monkeypatch, img, fg):
    grabs = []
    from PIL import ImageGrab

    def _grab(*a, **k):
        grabs.append(1)
        return img
    monkeypatch.setattr(ImageGrab, "grab", _grab)
    monkeypatch.setattr(_frame, "_input_desktop_locked", lambda: False)
    if fg is not None:  # None = leave the image-name seam to the caller
        monkeypatch.setattr(_frame, "_league_foreground", lambda: fg)
    return grabs


def test_not_foreground_stub_skips_the_grab(monkeypatch):
    grabs = _gdi(monkeypatch, _textured(), fg=False)
    assert _frame._maybe_self_grab() is None
    assert grabs == []  # the GDI BitBlt never ran
    assert _counts()["not_foreground"] == 1
    assert _frame.last_capture_skip()["reason"] == "not_foreground"


def test_foreground_grab_is_served(monkeypatch):
    grabs = _gdi(monkeypatch, _textured(), fg=True)
    out = _frame._maybe_self_grab()
    assert out is not None and out["source"] == "self_grab"
    assert grabs == [1]
    assert _counts() == {"locked": 0, "not_foreground": 0, "blank": 0}


def test_grace_window_allows_brief_alt_tab(monkeypatch):
    grabs = _gdi(monkeypatch, _textured(), fg=False)
    _frame._league_fg_last_seen = time.time() - (_frame._FOREGROUND_GRACE_S / 2)
    assert _frame._maybe_self_grab() is not None
    assert grabs == [1]
    assert _counts()["not_foreground"] == 0


def test_grace_window_expires(monkeypatch):
    grabs = _gdi(monkeypatch, _textured(), fg=False)
    _frame._league_fg_last_seen = time.time() - (_frame._FOREGROUND_GRACE_S + 1)
    assert _frame._maybe_self_grab() is None
    assert grabs == []
    assert _counts()["not_foreground"] == 1


def test_foreground_sighting_refreshes_grace(monkeypatch):
    _gdi(monkeypatch, _textured(), fg=True)
    before = time.time()
    _frame._maybe_self_grab()
    assert _frame._league_fg_last_seen >= before


@pytest.mark.parametrize("image", ["league of legends.exe",
                                   "amberstone shell.exe", "electron.exe"])
def test_overlay_or_league_foreground_lets_grab_proceed(monkeypatch, image):
    """The RC overlay (rc-shell, focusable while ACTIVE) can hold foreground
    for ~20s mid-game; its transparent frame over League is still game content,
    so the GDI gate must not go dark. Packaged name = electron-builder
    productName "Amberstone Shell"; live launches run node_modules electron.exe."""
    grabs = _gdi(monkeypatch, _textured(), fg=None)
    monkeypatch.setattr(_frame, "_foreground_image", lambda: image)
    out = _frame._maybe_self_grab()
    assert out is not None and out["source"] == "self_grab"
    assert grabs == [1]
    assert _counts()["not_foreground"] == 0


def test_other_foreground_image_still_skips(monkeypatch):
    grabs = _gdi(monkeypatch, _textured(), fg=None)
    monkeypatch.setattr(_frame, "_foreground_image", lambda: "explorer.exe")
    assert _frame._maybe_self_grab() is None
    assert grabs == []
    assert _counts()["not_foreground"] == 1


def test_obs_source_is_not_foreground_gated(monkeypatch):
    from core import obs_frame_source as ofs
    raw = _jpeg_bytes(_textured(640, 360))
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: raw)
    grabs = _gdi(monkeypatch, _textured(), fg=False)
    out = _frame._maybe_self_grab()
    assert out is not None and out["source"] == "obs"
    assert grabs == []
    assert _counts()["not_foreground"] == 0


# -- blank frames dropped ----------------------------------------------------

def test_synthetic_all_black_frame_is_dropped(monkeypatch):
    saved = []
    from core import vision_profiles
    monkeypatch.setattr(vision_profiles, "save_reference_image",
                        lambda img, *a, **k: saved.append(img) or True)
    grabs = _gdi(monkeypatch, Image.new("RGB", (2560, 1440), (0, 0, 0)), fg=True)
    assert _frame._maybe_self_grab() is None
    assert grabs == [1]
    assert saved == []  # a black frame never becomes a calibration still
    assert _counts()["blank"] == 1
    assert _frame.get_latest_frame().get("b64") is None


def test_blank_obs_frame_is_dropped(monkeypatch):
    from core import obs_frame_source as ofs
    raw = _jpeg_bytes(Image.new("RGB", (640, 360), (0, 0, 0)))
    monkeypatch.setattr(ofs, "obs_frame_source_enabled", lambda: True)
    monkeypatch.setattr(ofs, "get_obs_frame", lambda *a, **k: raw)
    assert _frame._maybe_obs_frame() is None
    assert _counts()["blank"] == 1


# -- the standalone agent (tools/screen_agent.py) ----------------------------

@pytest.fixture()
def agent(tmp_path):
    """Load a COPY of the agent from a dir with no repo above it (that is how
    it is deployed), so the import also proves it needs no core module and
    its log file lands in tmp, not the tree."""
    from pathlib import Path
    src = Path(_frame.__file__).resolve().parent.parent / "tools" / "screen_agent.py"
    dst_dir = tmp_path / "tools"
    dst_dir.mkdir()
    dst = dst_dir / "screen_agent.py"
    shutil.copyfile(src, dst)
    spec = importlib.util.spec_from_file_location("_y03_screen_agent", dst)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    yield mod
    import logging
    for h in list(logging.getLogger().handlers):
        if getattr(h, "baseFilename", "").startswith(str(tmp_path)):
            logging.getLogger().removeHandler(h)
            h.close()


def test_agent_constants_match_core(agent):
    assert agent.BLANK_LUMA_RANGE_MAX == screen_grab.BLANK_LUMA_RANGE_MAX
    assert agent.BLANK_THUMB_WIDTH == screen_grab.BLANK_THUMB_WIDTH
    assert agent.FOREGROUND_GRACE_S == _frame._FOREGROUND_GRACE_S
    assert agent.GAME_CONTENT_IMAGES == _frame._GAME_CONTENT_IMAGES
    assert "league of legends.exe" in agent.GAME_CONTENT_IMAGES
    assert tuple(agent.SKIP_COUNTS) == REASONS


def test_agent_gate_locked(agent, monkeypatch):
    monkeypatch.setattr(agent, "_input_desktop_locked", lambda: True)
    monkeypatch.setattr(agent, "_league_foreground", lambda: True)
    assert agent.capture_gate(primary=True) == "locked"
    assert agent.capture_gate(primary=False) == "locked"


def test_agent_gate_not_foreground_primary_only(agent, monkeypatch):
    monkeypatch.setattr(agent, "_input_desktop_locked", lambda: False)
    monkeypatch.setattr(agent, "_league_foreground", lambda: False)
    agent._fg_last_seen = 0.0
    assert agent.capture_gate(primary=True) == "not_foreground"
    # The --no-primary UI-debug channel streams the dashboard on purpose.
    assert agent.capture_gate(primary=False) is None


@pytest.mark.parametrize("image", ["amberstone shell.exe", "electron.exe"])
def test_agent_gate_overlay_foreground_counts_as_game(agent, monkeypatch, image):
    monkeypatch.setattr(agent, "_input_desktop_locked", lambda: False)
    monkeypatch.setattr(agent, "_foreground_image", lambda: image)
    agent._fg_last_seen = 0.0
    assert agent.capture_gate(primary=True) is None
    monkeypatch.setattr(agent, "_foreground_image", lambda: "explorer.exe")
    agent._fg_last_seen = 0.0
    assert agent.capture_gate(primary=True) == "not_foreground"


def test_agent_gate_grace(agent, monkeypatch):
    monkeypatch.setattr(agent, "_input_desktop_locked", lambda: False)
    monkeypatch.setattr(agent, "_league_foreground", lambda: False)
    agent._fg_last_seen = time.time() - agent.FOREGROUND_GRACE_S / 2
    assert agent.capture_gate(primary=True) is None


def test_agent_drops_black_frame(agent, monkeypatch):
    monkeypatch.setattr(agent, "_bettercam_image",
                        lambda idx: Image.new("RGB", (1920, 1080), (0, 0, 0)))
    with pytest.raises(agent.CaptureRefused) as ei:
        agent.capture(0, drop_blank=True)
    assert ei.value.reason == "blank"
    # Positive control: a textured frame encodes normally.
    monkeypatch.setattr(agent, "_bettercam_image", lambda idx: _textured(640, 360))
    b64, fmt, w, h = agent.capture(0, drop_blank=True)
    assert base64.b64decode(b64)[:3] == b"\xff\xd8\xff"


def test_agent_loop_skip_is_counted_and_not_a_failure(agent, monkeypatch):
    """A skip must not upload and must not feed the failure backoff."""
    monkeypatch.setattr(agent, "_enum_monitor_rects", lambda: [])
    reasons = iter(["not_foreground", "locked", "blank", "blank"])

    def _gated(*a, **k):
        raise agent.CaptureRefused(next(reasons))
    monkeypatch.setattr(agent, "_gated_capture", _gated)
    monkeypatch.setattr(agent, "upload",
                        lambda *a, **k: pytest.fail("skipped frame uploaded"))
    sleeps = []

    class _Stop(Exception):
        pass

    def _sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 4:
            raise _Stop
    monkeypatch.setattr(agent.time, "sleep", _sleep)
    with pytest.raises(_Stop):
        agent.loop(2.0, 0, "legion", True)
    assert agent.SKIP_COUNTS == {"locked": 1, "not_foreground": 1, "blank": 2}
    # No exponential backoff: every sleep is within the base interval.
    assert all(s <= 2.0 for s in sleeps)
