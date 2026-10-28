"""s144 true-audit of core/league_settings.py (RM-1111 and siblings).

read_hud_settings feeds minimap_rect_payload, which dashboard/_state_builder.py
calls on every /api/state build in sr / aram / brawl for the overlay minimap
outline. The module docstring promises "every entry point returns None rather
than raising". Measured before this audit:

- a UTF-8 BOM (PowerShell 5.1 ``Set-Content -Encoding UTF8``, old Notepad) hid
  the first section header: a BOM before ``[HUD]`` returned None (no minimap
  outline), a BOM before ``[General]`` lost the native size (RM-1111);
- a UTF-16 file (Notepad "Unicode") read as no [HUD] at all;
- a Width / Height of ``inf`` or ``1e400`` raised OverflowError on every poll;
  0, a negative or 99999999 was returned as a native size;
- a MinimapScale of ``nan`` / ``inf`` was returned as-is, so the geometry
  silently used its 1.62 calibration instead of the documented default 1.0;
- a path with an embedded NUL raised ValueError, and an int path was stat'ed
  as a file descriptor before Path() raised TypeError;
- an empty or padded RC_LEAGUE_CONFIG disabled the minimap where
  core.hud_settings (which documents the same resolution) used the default
  path or the stripped value, so the two readers read different installs;
- the read was unbounded (a mis-pointed RC_LEAGUE_CONFIG pulled a whole file);
- the parse cache grew one entry per distinct path for the process lifetime;
- minimap_rect_payload raised on a None / nan / inf target size;
- a present-but-unusable file degraded silently.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

from core import league_settings
from core.league_settings import minimap_rect_payload, read_hud_settings

_LOGGER = "core.league_settings"

_BASE = (
    "[General]\nWidth=2560\nHeight=1440\n"
    "[HUD]\nMinimapScale=1.6200\nFlipMiniMap=0\n"
)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.delenv("RC_LEAGUE_CONFIG", raising=False)

    def _clear():
        league_settings._CACHE.clear()
        reset = getattr(league_settings, "_reset_warnings", None)
        if reset is not None:
            reset()

    _clear()
    yield
    _clear()


def _write_bytes(tmp_path: Path, data: bytes, name: str = "game.cfg") -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == _LOGGER and r.levelno >= logging.WARNING]


# --- encodings ------------------------------------------------------------------

def test_utf8_bom_before_hud_keeps_the_hud_section(tmp_path):
    p = _write_bytes(tmp_path, b"\xef\xbb\xbf[HUD]\nMinimapScale=1.5\nFlipMiniMap=1\n")
    s = read_hud_settings(p)
    assert s is not None
    assert s.minimap_scale == pytest.approx(1.5)
    assert s.flip_minimap is True


def test_utf8_bom_before_general_keeps_the_native_size(tmp_path):
    p = _write_bytes(tmp_path, b"\xef\xbb\xbf" + _BASE.encode("ascii"))
    s = read_hud_settings(p)
    assert s is not None
    assert (s.native_w, s.native_h) == (2560, 1440)
    assert s.minimap_scale == pytest.approx(1.62)


@pytest.mark.parametrize("codec", ["utf-16", "utf-16-le", "utf-16-be"])
def test_utf16_with_bom_parses_like_utf8(tmp_path, codec):
    data = _BASE.encode(codec)
    if codec != "utf-16":  # the explicit-endian codecs write no BOM themselves
        data = ("\ufeff" + _BASE).encode(codec)
    s = read_hud_settings(_write_bytes(tmp_path, data))
    assert s is not None
    assert (s.native_w, s.native_h) == (2560, 1440)
    assert s.minimap_scale == pytest.approx(1.62)


def test_bom_led_payload_equals_bom_less_payload(tmp_path):
    plain = minimap_rect_payload(_write_bytes(tmp_path, _BASE.encode(), "a.cfg"))
    bom = minimap_rect_payload(_write_bytes(tmp_path, b"\xef\xbb\xbf" + _BASE.encode(), "b.cfg"))
    assert plain is not None
    assert bom == plain


# --- numbers --------------------------------------------------------------------

@pytest.mark.parametrize("width", ["inf", "-inf", "1e400", "nan"])
def test_non_finite_width_never_raises_and_is_no_size(tmp_path, width):
    p = _write_bytes(tmp_path, _BASE.replace("Width=2560", f"Width={width}").encode())
    s = read_hud_settings(p)
    assert s is not None
    assert s.native_w is None
    assert s.native_h == 1440


@pytest.mark.parametrize("height", ["0", "-5", "0.5", "10001", "10000.5", "99999999"])
def test_out_of_range_height_is_no_size(tmp_path, height):
    p = _write_bytes(tmp_path, _BASE.replace("Height=1440", f"Height={height}").encode())
    s = read_hud_settings(p)
    assert s is not None
    assert s.native_h is None
    assert s.native_w == 2560


@pytest.mark.parametrize("height,expected", [("1", 1), ("10000", 10000), ("1440.9", 1440)])
def test_in_range_height_boundaries_are_kept(tmp_path, height, expected):
    p = _write_bytes(tmp_path, _BASE.replace("Height=1440", f"Height={height}").encode())
    assert read_hud_settings(p).native_h == expected


@pytest.mark.parametrize("scale", ["nan", "inf", "-inf", "1e400"])
def test_non_finite_scale_degrades_to_the_documented_default(tmp_path, scale):
    p = _write_bytes(tmp_path, _BASE.replace("1.6200", scale).encode(), "s.cfg")
    s = read_hud_settings(p)
    assert s is not None
    assert s.minimap_scale == 1.0
    one = _write_bytes(tmp_path, _BASE.replace("1.6200", "1.0").encode(), "one.cfg")
    assert minimap_rect_payload(p) == minimap_rect_payload(one)


# --- paths ----------------------------------------------------------------------

def test_embedded_nul_path_returns_none(tmp_path):
    assert read_hud_settings(str(tmp_path) + "\x00game.cfg") is None
    assert minimap_rect_payload(str(tmp_path) + "\x00game.cfg") is None


def test_int_path_is_not_stat_as_a_file_descriptor(tmp_path):
    p = _write_bytes(tmp_path, _BASE.encode())
    fd = os.open(p, os.O_RDONLY)
    try:
        assert read_hud_settings(fd) is None
    finally:
        os.close(fd)


@pytest.mark.parametrize("bad", [b"game.cfg", 1.5, object()])
def test_non_path_argument_returns_none(bad):
    assert read_hud_settings(bad) is None


def test_pathlike_argument_is_accepted(tmp_path):
    p = Path(_write_bytes(tmp_path, _BASE.encode()))
    assert read_hud_settings(p).native_w == 2560


@pytest.mark.parametrize("env", ["", "   "])
def test_blank_env_falls_back_to_the_default_path(tmp_path, monkeypatch, env):
    p = _write_bytes(tmp_path, _BASE.encode())
    monkeypatch.setattr(league_settings, "_DEFAULT_CFG", p)
    monkeypatch.setenv("RC_LEAGUE_CONFIG", env)
    s = read_hud_settings()
    assert s is not None
    assert s.native_w == 2560


def test_padded_env_is_stripped(tmp_path, monkeypatch):
    p = _write_bytes(tmp_path, _BASE.encode())
    monkeypatch.setenv("RC_LEAGUE_CONFIG", "  " + p + "  ")
    s = read_hud_settings()
    assert s is not None
    assert s.native_w == 2560


# --- bounds ---------------------------------------------------------------------

def test_oversize_file_is_refused_without_a_full_read(tmp_path, monkeypatch):
    monkeypatch.setattr(league_settings, "_MAX_FILE_BYTES", 64, raising=False)
    p = _write_bytes(tmp_path, _BASE.encode() + b"; pad\n" * 40)
    assert read_hud_settings(p) is None
    assert p not in league_settings._CACHE


def test_oversize_stat_skips_the_read(tmp_path, monkeypatch):
    # the stat size is checked first, so an oversize file is never opened
    monkeypatch.setattr(league_settings, "_MAX_FILE_BYTES", 16)
    calls = []
    monkeypatch.setattr(league_settings, "_read_cfg", lambda p: calls.append(p) or "")
    assert read_hud_settings(_write_bytes(tmp_path, _BASE.encode())) is None
    assert calls == []


def test_read_cap_holds_when_the_file_grows_after_stat(tmp_path, monkeypatch):
    # the read itself is capped too: a file that grew between the stat and the
    # open is refused, not read whole
    monkeypatch.setattr(league_settings, "_MAX_FILE_BYTES", 16)
    with pytest.raises(OSError):
        league_settings._read_cfg(_write_bytes(tmp_path, _BASE.encode()))
    small = _write_bytes(tmp_path, b"[HUD]\nA=1\n", "s.cfg")  # 10 bytes, under 16
    assert league_settings._read_cfg(small) == "[HUD]\nA=1\n"


def test_file_at_the_cap_is_read(tmp_path, monkeypatch):
    data = _BASE.encode()
    monkeypatch.setattr(league_settings, "_MAX_FILE_BYTES", len(data), raising=False)
    assert read_hud_settings(_write_bytes(tmp_path, data)).native_w == 2560


def test_parse_cache_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(league_settings, "_CACHE_MAX", 4, raising=False)
    paths = [_write_bytes(tmp_path, _BASE.encode(), f"g{i}.cfg") for i in range(10)]
    for p in paths:
        assert read_hud_settings(p) is not None
    assert len(league_settings._CACHE) <= 4
    assert paths[-1] in league_settings._CACHE


# --- payload targets ------------------------------------------------------------

@pytest.mark.parametrize("tw,th", [
    (None, 1080), (1920, None), (float("nan"), 1080), (1920, float("inf")),
    (True, 1080), (0, 1080), (1920, -1), ("1920", 1080),
    (10 ** 400, 1080), (1920, 10001),
])
def test_payload_bad_target_returns_none(tmp_path, tw, th):
    p = _write_bytes(tmp_path, _BASE.encode())
    assert minimap_rect_payload(p, tw, th) is None


def test_payload_float_target_still_works(tmp_path):
    p = _write_bytes(tmp_path, _BASE.encode())
    assert minimap_rect_payload(p, 1920.0, 1080.0) == minimap_rect_payload(p, 1920, 1080)


# --- diagnostics ----------------------------------------------------------------

def test_present_but_unusable_file_warns_once_per_streak_without_the_path(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    bad = tmp_path / "dir.cfg"
    bad.mkdir()
    assert read_hud_settings(str(bad)) is None
    assert read_hud_settings(str(bad)) is None
    recs = _warnings(caplog)
    assert len(recs) == 1
    assert str(tmp_path) not in recs[0].getMessage()
    assert "game.cfg" in recs[0].getMessage()

    # a clean read ends the streak, so the next failure warns again
    assert read_hud_settings(_write_bytes(tmp_path, _BASE.encode())) is not None
    assert read_hud_settings(str(bad)) is None
    assert len(_warnings(caplog)) == 2


def test_cache_hit_also_ends_a_warned_streak(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    good = _write_bytes(tmp_path, _BASE.encode())
    assert read_hud_settings(good) is not None  # parsed and cached
    bad = tmp_path / "dir.cfg"
    bad.mkdir()
    assert read_hud_settings(str(bad)) is None
    assert read_hud_settings(good) is not None  # a cache hit, not a re-read
    assert read_hud_settings(str(bad)) is None
    assert len(_warnings(caplog)) == 2


def test_oversize_file_warns(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    monkeypatch.setattr(league_settings, "_MAX_FILE_BYTES", 16, raising=False)
    assert read_hud_settings(_write_bytes(tmp_path, _BASE.encode())) is None
    assert len(_warnings(caplog)) == 1


def test_missing_file_is_silent(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger=_LOGGER)
    assert read_hud_settings(str(tmp_path / "absent.cfg")) is None
    assert _warnings(caplog) == []
