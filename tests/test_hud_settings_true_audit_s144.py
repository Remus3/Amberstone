"""s144 true-audit of core/hud_settings.py.

read_hud_settings feeds core.vision_profiles.active_config_key (region set +
HUD color layer for every OCR tick) and core.live_session_recorder. Its
docstring promises "missing files -> friendly zeros, never raises". Measured
before this audit:

- a Width / Height / ColorPalette of ``inf`` or ``1e400`` raised OverflowError,
  so active_config_key fell to "unknown" AND never installed the color layer;
- a negative Width read as ok=True with config_key "-1920x1080|...";
- a UTF-8 BOM (PowerShell 5.1 ``Set-Content -Encoding UTF8``, old Notepad) lost
  the ``[General]`` header in game.cfg and blanked PersistedSettings.json;
- a PersistedSettings.json nested past ~1000 levels (json accepts 3000) raised
  RecursionError out of the flattening walk;
- RC_LEAGUE_CONFIG, which core.league_settings honours, was ignored here, so
  the minimap and the OCR read different installs;
- a present-but-broken settings file degraded silently (the logger was unused);
- the not-readable branch dropped the width / height keys.
"""
from __future__ import annotations

import json
import logging
import pathlib

import pytest

from core import hud_settings

_CFG = "[General]\nWidth=1920\nHeight=1080\n[HUD]\nShowTeamFramesOnLeft=0\n"


def _persisted(palette="0", gamma="0.5000"):
    return json.dumps({"files": [{"name": "Game.cfg", "sections": [{"name": "General", "settings": [
        {"name": "ColorGamma", "value": gamma},
        {"name": "ColorPalette", "value": palette},
    ]}]}]})


@pytest.fixture(autouse=True)
def _fresh_warn_state(monkeypatch):
    monkeypatch.delenv("RC_LEAGUE_CONFIG", raising=False)
    hud_settings._reset_warnings()
    yield
    hud_settings._reset_warnings()


def _files(tmp_path: pathlib.Path, cfg=_CFG, persisted=None):
    g = tmp_path / "game.cfg"
    g.write_text(cfg, encoding="utf-8")
    p = tmp_path / "PersistedSettings.json"
    p.write_text(persisted if persisted is not None else _persisted(), encoding="utf-8")
    return g, p


# --- never raises on junk numbers --------------------------------------------------

@pytest.mark.parametrize("width", ["inf", "1e400", "-inf", "nan"])
def test_non_finite_width_is_not_ok_and_never_raises(tmp_path, width):
    g, p = _files(tmp_path, cfg=f"[General]\nWidth={width}\nHeight=1080\n")
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is False
    assert s["width"] is None
    assert s["config_key"] == "unknown"


@pytest.mark.parametrize("width", ["-1920", "0", "0.5", "10001", "1e300"])
def test_out_of_range_width_is_refused(tmp_path, width):
    g, p = _files(tmp_path, cfg=f"[General]\nWidth={width}\nHeight=1080\n")
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is False
    assert s["width"] is None
    assert s["config_key"] == "unknown"


def test_in_range_bounds_are_accepted(tmp_path):
    g, p = _files(tmp_path, cfg="[General]\nWidth=10000\nHeight=1\n")
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is True
    assert (s["width"], s["height"]) == (10000, 1)
    assert s["config_key"].startswith("10000x1|")


def test_fractional_width_still_truncates_like_before(tmp_path):
    g, p = _files(tmp_path, cfg="[General]\nWidth=1920.0\nHeight=1080.7\n")
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert (s["width"], s["height"]) == (1920, 1080)


@pytest.mark.parametrize("palette", ["inf", "1e400", "nan", True])
def test_junk_color_palette_never_raises_and_is_not_colorblind(tmp_path, palette):
    body = json.dumps({"name": "ColorPalette", "value": palette})
    g, p = _files(tmp_path, persisted=body)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is True
    assert s["colorblind"] is False


def test_json_big_int_palette_never_raises(tmp_path):
    body = '{"name": "ColorPalette", "value": 1' + "0" * 400 + "}"
    g, p = _files(tmp_path, persisted=body)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is True
    assert s["colorblind"] is False


@pytest.mark.parametrize("gamma", ["inf", "-inf", "nan", True])
def test_junk_color_slider_never_requests_correction(tmp_path, gamma):
    body = json.dumps({"name": "ColorGamma", "value": gamma})
    g, p = _files(tmp_path, persisted=body)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["color_correction_needed"] is False


def test_real_palette_and_slider_still_flag(tmp_path):
    g, p = _files(tmp_path, persisted=_persisted(palette="2", gamma="0.7000"))
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["colorblind"] is True
    assert s["color_correction_needed"] is True


# --- encoding -----------------------------------------------------------------------

def test_utf8_bom_game_cfg_keeps_general_section(tmp_path):
    g, p = _files(tmp_path)
    g.write_bytes(b"\xef\xbb\xbf" + _CFG.encode("ascii"))
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is True
    assert (s["width"], s["height"]) == (1920, 1080)


def test_utf8_bom_persisted_settings_is_parsed(tmp_path):
    g, p = _files(tmp_path)
    p.write_bytes(b"\xef\xbb\xbf" + _persisted(palette="1").encode("ascii"))
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["colorblind"] is True


def test_spaced_section_header_is_recognised(tmp_path):
    g, p = _files(tmp_path, cfg="[ General ]\nWidth=1920\nHeight=1080\n")
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is True


# --- structure ----------------------------------------------------------------------

def test_deeply_nested_persisted_settings_never_raises(tmp_path):
    depth = 3000
    body = '{"a":' * depth + json.dumps({"name": "ColorPalette", "value": "1"}) + "}" * depth
    json.loads(body)  # json itself accepts it - the walk must too
    g, p = _files(tmp_path, persisted=body)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["colorblind"] is True


def test_first_seen_setting_wins_in_document_order(tmp_path):
    body = json.dumps({"files": [
        {"settings": [{"name": "ColorPalette", "value": "0"}]},
        {"name": "ColorPalette", "value": "3"},
    ]})
    g, p = _files(tmp_path, persisted=body)
    assert hud_settings._read_persisted_flat(p)["ColorPalette"] == "0"


def test_first_seen_dict_child_wins_in_document_order(tmp_path):
    body = json.dumps({"a": {"name": "ColorPalette", "value": "0"},
                       "b": {"name": "ColorPalette", "value": "3"}})
    g, p = _files(tmp_path, persisted=body)
    assert hud_settings._read_persisted_flat(p)["ColorPalette"] == "0"


def test_outer_dict_own_setting_precedes_its_children(tmp_path):
    body = json.dumps({"name": "ColorPalette", "value": "1",
                       "kids": [{"name": "ColorPalette", "value": "0"}]})
    g, p = _files(tmp_path, persisted=body)
    assert hud_settings._read_persisted_flat(p)["ColorPalette"] == "1"


def test_not_readable_branch_carries_width_and_height(tmp_path):
    s = hud_settings.read_hud_settings(game_cfg=tmp_path / "nope.cfg",
                                       persisted=tmp_path / "nope.json")
    assert s["ok"] is False
    assert s["width"] is None and s["height"] is None
    assert set(s) >= {"ok", "width", "height", "config_key", "layout", "color",
                      "color_correction_needed", "colorblind", "cfg"}


@pytest.mark.parametrize("bad", [123, 1.5, "bad\x00name.cfg"])
def test_unusable_game_cfg_path_is_friendly_not_raised(tmp_path, bad):
    s = hud_settings.read_hud_settings(game_cfg=bad, persisted=tmp_path / "nope.json")
    assert s["ok"] is False
    assert s["config_key"] == "unknown"


@pytest.mark.parametrize("nameless", ["", ".", "C:/", "C:"])
def test_nameless_game_cfg_path_is_friendly_not_raised(nameless):
    s = hud_settings.read_hud_settings(game_cfg=nameless)
    assert s["ok"] is False
    assert s["config_key"] == "unknown"


@pytest.mark.parametrize("nameless", [".", " . ", "C:/", "C:"])
def test_nameless_rc_league_config_env_is_friendly_not_raised(monkeypatch, nameless):
    monkeypatch.setenv("RC_LEAGUE_CONFIG", nameless)
    s = hud_settings.read_hud_settings()
    assert s["ok"] is False
    assert s["config_key"] == "unknown"


def test_directory_as_game_cfg_or_persisted_is_friendly(tmp_path):
    s = hud_settings.read_hud_settings(game_cfg=tmp_path, persisted=tmp_path)
    assert s["ok"] is False
    g, _p = _files(tmp_path)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=tmp_path)
    assert s["ok"] is True
    assert s["color"] == {}


def test_device_name_path_is_refused_before_open(monkeypatch):
    # A Windows device name stats as a character device; opening and reading
    # CON / COM1 blocks. Prove the refusal happens before open() is reached.
    import stat as _stat

    class _St:
        st_mode = _stat.S_IFCHR | 0o666

    opened = []

    def _no_open(*args, **kwargs):
        opened.append(args)
        raise AssertionError("a device path reached open()")

    monkeypatch.setattr(hud_settings.os, "stat", lambda p: _St())
    # module-level name shadows the builtin for hud_settings only
    monkeypatch.setattr(hud_settings, "open", _no_open, raising=False)
    s = hud_settings.read_hud_settings(game_cfg="CON", persisted="COM1")
    assert s["ok"] is False
    assert opened == []
    assert hud_settings._read_persisted_flat("COM1") == {}
    assert opened == []


@pytest.mark.parametrize("bad", [123, 1.5, "bad\x00name.json"])
def test_unusable_persisted_path_keeps_the_game_cfg(tmp_path, bad):
    g, _p = _files(tmp_path)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=bad)
    assert s["ok"] is True
    assert s["color"] == {}


def test_oversized_files_are_refused_not_read_whole(tmp_path, monkeypatch):
    monkeypatch.setattr(hud_settings, "_MAX_FILE_BYTES", 64)
    g, p = _files(tmp_path, cfg=_CFG + ";" + "x" * 200 + "\n",
                  persisted=_persisted(palette="1") + " " * 200)
    s = hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    assert s["ok"] is False
    assert s["config_key"] == "unknown"
    assert hud_settings._read_persisted_flat(p) == {}


# --- machine environment ------------------------------------------------------------

def test_rc_league_config_env_is_honoured_with_sibling_persisted(tmp_path, monkeypatch):
    g, p = _files(tmp_path, persisted=_persisted(palette="1"))
    monkeypatch.setenv("RC_LEAGUE_CONFIG", str(g))
    s = hud_settings.read_hud_settings()
    assert s["ok"] is True
    assert s["colorblind"] is True


def test_explicit_game_cfg_reads_its_own_sibling_persisted(tmp_path):
    g, p = _files(tmp_path, persisted=_persisted(palette="1"))
    s = hud_settings.read_hud_settings(game_cfg=g)
    assert s["colorblind"] is True


# --- degraded states are logged, once per streak -----------------------------------

def test_present_but_broken_persisted_warns_once_per_streak(tmp_path, caplog):
    g, p = _files(tmp_path, persisted="{not json")
    caplog.set_level(logging.WARNING, logger="rc.vision")
    for _ in range(3):
        hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    hits = [r for r in caplog.records if "PersistedSettings" in r.getMessage()]
    assert len(hits) == 1
    assert str(tmp_path) not in hits[0].getMessage()
    # recovery resets the streak, a second break warns again
    p.write_text(_persisted(), encoding="utf-8")
    hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    p.write_text("[", encoding="utf-8")
    hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    hits = [r for r in caplog.records if "PersistedSettings" in r.getMessage()]
    assert len(hits) == 2


def test_present_game_cfg_without_resolution_warns_once(tmp_path, caplog):
    g, p = _files(tmp_path, cfg="[General]\nWidth=inf\nHeight=1080\n")
    caplog.set_level(logging.WARNING, logger="rc.vision")
    for _ in range(3):
        hud_settings.read_hud_settings(game_cfg=g, persisted=p)
    hits = [r for r in caplog.records if "game.cfg" in r.getMessage()]
    assert len(hits) == 1


def test_missing_files_are_silent(tmp_path, caplog):
    caplog.set_level(logging.DEBUG, logger="rc.vision")
    hud_settings.read_hud_settings(game_cfg=tmp_path / "nope.cfg",
                                   persisted=tmp_path / "nope.json")
    g = tmp_path / "game.cfg"
    g.write_text(_CFG, encoding="utf-8")
    hud_settings.read_hud_settings(game_cfg=g, persisted=tmp_path / "nope.json")
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
