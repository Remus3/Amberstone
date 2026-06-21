"""Characterization tests for the League game.cfg HUD-settings reader.

core/league_settings.read_hud_settings parses the [HUD] + [General] sections of
League's game.cfg to recover MinimapScale / FlipMiniMap / native render size.
It MUST fail soft (return None) when the file is absent or unparseable so a
clean checkout / CI / non-Legion host never crashes. ASCII-only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.league_settings import (
    LeagueHudSettings,
    minimap_rect_payload,
    read_hud_settings,
)

# A faithful slice of the operator's live game.cfg (values confirmed live
# 2026-06-21): leading blank lines, keys before the first section, [General]
# and [HUD] sections, a stray percent to prove no interpolation crash.
_SAMPLE = """

CursorScale=0.5000
[General]
Width=2560
Height=1440
WindowMode=2
[Performance]
ShadowsEnabled=1 ; 50% quality
[HUD]
MinimapScale=1.6200
FlipMiniMap=0
MinimapMoveSelf=1
GlobalScale=0.0000
"""


def _write(tmp_path: Path, text: str) -> str:
    p = tmp_path / "game.cfg"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_parses_live_hud_fields(tmp_path):
    s = read_hud_settings(_write(tmp_path, _SAMPLE))
    assert isinstance(s, LeagueHudSettings)
    assert s.minimap_scale == pytest.approx(1.62)
    assert s.flip_minimap is False
    assert s.native_w == 2560
    assert s.native_h == 1440


def test_flip_true_when_one(tmp_path):
    s = read_hud_settings(_write(tmp_path, _SAMPLE.replace("FlipMiniMap=0", "FlipMiniMap=1")))
    assert s.flip_minimap is True


def test_missing_file_returns_none(tmp_path):
    assert read_hud_settings(str(tmp_path / "does_not_exist.cfg")) is None


def test_unparseable_or_no_hud_returns_none(tmp_path):
    # no [HUD] section -> None (cannot ground the minimap)
    s = read_hud_settings(_write(tmp_path, "[General]\nWidth=1920\n"))
    assert s is None


def test_missing_scale_defaults_to_one(tmp_path):
    text = _SAMPLE.replace("MinimapScale=1.6200\n", "")
    s = read_hud_settings(_write(tmp_path, text))
    assert s is not None
    assert s.minimap_scale == pytest.approx(1.0)
    assert s.flip_minimap is False


def test_percent_in_value_does_not_crash(tmp_path):
    # a stray % must not raise (no configparser interpolation)
    text = _SAMPLE + "\n[Extra]\nNote=100%done\n"
    s = read_hud_settings(_write(tmp_path, text))
    assert s is not None
    assert s.minimap_scale == pytest.approx(1.62)


def test_non_numeric_scale_falls_back(tmp_path):
    text = _SAMPLE.replace("MinimapScale=1.6200", "MinimapScale=garbage")
    s = read_hud_settings(_write(tmp_path, text))
    assert s is not None
    assert s.minimap_scale == pytest.approx(1.0)


def test_payload_shape_for_overlay(tmp_path):
    payload = minimap_rect_payload(path=_write(tmp_path, _SAMPLE))
    assert payload is not None
    for k in ("x", "y", "w", "h", "flip", "source", "native_w", "native_h"):
        assert k in payload
    assert payload["source"] == "settings"
    assert payload["w"] == payload["h"]
    assert payload["flip"] is False
    assert payload["native_w"] == 2560
    # bottom-right anchored on the 1920x1080 design canvas
    assert payload["x"] + payload["w"] <= 1920
    assert 300 <= payload["w"] <= 320


def test_payload_none_when_file_absent(tmp_path):
    assert minimap_rect_payload(path=str(tmp_path / "nope.cfg")) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
