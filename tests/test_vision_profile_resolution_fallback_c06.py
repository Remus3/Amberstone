"""C-06 / RM-26: SEED profiles must be reachable from a REAL HUD config_key.

core.vision_profiles.seed_profiles writes each seed under the resolution-only
config_key "WxH" (vision_profiles.py seed_profiles), but a live machine's
config_key is the full settings signature "WxH|GlobalScale=..|.." built in
core.hud_settings.read_hud_settings. Before the fix those never matched, so a
3440x1440 first run fell straight through to the UNSCALED 1920x1080 legacy_seed.

These tests pin the three-tier resolution order:
  1. exact profile file for the config_key  -> source "profile"
  2. resolution-only profile file (WxH)     -> source "resolution_seed"
  3. legacy 1920x1080 baseline              -> source "legacy_seed"
"""
from __future__ import annotations

import pytest

from core import vision_profiles as vp

_SEED_REGIONS = {"hp": [1700, 1300, 1900, 1360]}
_SEED_BASE = [3440, 1440]
_FULL_KEY = ("3440x1440|GlobalScale=0.0000|ShowTeamFramesOnLeft=0"
             "|MirroredScoreboard=0|FlipMiniMap=0|MinimapScale=0.5000")


@pytest.fixture()
def profiles_dir(tmp_path, monkeypatch):
    d = tmp_path / "profiles"
    monkeypatch.setattr(vp, "PROFILES_DIR", d)
    return d


def _write_seed(config_key=None, regions=None, base=None):
    res = vp.save_profile(config_key or f"{_SEED_BASE[0]}x{_SEED_BASE[1]}",
                          _SEED_REGIONS if regions is None else regions,
                          _SEED_BASE if base is None else base)
    assert res["ok"]


def test_full_config_key_reaches_the_resolution_seed(profiles_dir):
    """The bug: a full HUD config_key must find the "3440x1440" seed file."""
    _write_seed()
    prof = vp.load_profile(_FULL_KEY)
    assert prof["source"] == "resolution_seed"
    assert prof["base"] == _SEED_BASE
    assert prof["regions"] == _SEED_REGIONS
    # the requested key is echoed back, not the seed key
    assert prof["config_key"] == _FULL_KEY
    assert prof["resolution_key"] == "3440x1440"


def test_exact_profile_still_wins_over_the_resolution_seed(profiles_dir):
    """Tier 1 is unchanged: a calibrated per-config profile beats the seed."""
    _write_seed()
    vp.save_profile(_FULL_KEY, {"hp": [1, 2, 3, 4]}, [3440, 1440])
    prof = vp.load_profile(_FULL_KEY)
    assert prof["source"] == "profile"
    assert prof["regions"] == {"hp": [1, 2, 3, 4]}


def test_no_seed_for_that_resolution_still_falls_to_legacy(profiles_dir):
    """Tier 3 is unchanged when no seed exists for the live resolution."""
    prof = vp.load_profile("7680x2160|GlobalScale=0.0000")
    assert prof["source"] == "legacy_seed"
    assert prof["base"] == [1920, 1080]


def test_unparseable_config_key_still_falls_to_legacy(profiles_dir):
    """A key with no leading WxH token cannot manufacture a resolution hit."""
    _write_seed()
    prof = vp.load_profile("never_calibrated_config")
    assert prof["source"] == "legacy_seed"
    assert prof["base"] == [1920, 1080]


def test_resolution_key_equal_to_config_key_is_not_double_read(profiles_dir):
    """Calling with the bare "WxH" key is a tier-1 hit, never tier 2."""
    _write_seed()
    prof = vp.load_profile("3440x1440")
    assert prof["source"] == "profile"


def test_live_width_height_preferred_over_config_key_string(profiles_dir,
                                                            monkeypatch):
    """Tier 2 prefers the REAL width/height from read_hud_settings over any
    parse of the key string, so an opaque key still resolves."""
    import core.hud_settings as hs

    _write_seed()
    monkeypatch.setattr(vp, "active_config_key", lambda: "opaque_key")
    monkeypatch.setattr(hs, "read_hud_settings",
                        lambda *a, **k: {"ok": True, "width": 3440,
                                         "height": 1440,
                                         "config_key": "opaque_key"})
    prof = vp.load_profile()
    assert prof["source"] == "resolution_seed"
    assert prof["config_key"] == "opaque_key"
    assert prof["base"] == _SEED_BASE


def test_broken_hud_settings_does_not_raise(profiles_dir, monkeypatch):
    """Fail-soft: an exploding settings read degrades to the key parse."""
    import core.hud_settings as hs

    def _boom(*a, **k):
        raise RuntimeError("no game.cfg")

    _write_seed()
    monkeypatch.setattr(hs, "read_hud_settings", _boom)
    monkeypatch.setattr(vp, "active_config_key", lambda: _FULL_KEY)
    prof = vp.load_profile()
    assert prof["source"] == "resolution_seed"


def test_every_seed_base_is_reachable_from_a_real_hud_config_key(
        profiles_dir, tmp_path, monkeypatch):
    """End-to-end: build each config_key with the REAL read_hud_settings parser
    (from a synthetic game.cfg) and confirm the shipped seed answers it."""
    from core.hud_settings import read_hud_settings

    legacy = tmp_path / "vision_regions.json"
    legacy.write_text('{"hp": [800, 900, 1100, 960]}\n', encoding="utf-8")
    monkeypatch.setattr(vp, "_LEGACY_REGIONS", legacy)

    out = vp.seed_profiles()
    assert out["ok"], out["errors"]
    assert out["written"] == len(vp.SEED_BASES)

    for w, h in vp.SEED_BASES:
        cfg = tmp_path / f"game_{w}x{h}.cfg"
        cfg.write_text(
            f"[General]\nWidth={w}\nHeight={h}\n"
            "[HUD]\nGlobalScale=0.0000\nShowTeamFramesOnLeft=0\n"
            "MirroredScoreboard=0\nFlipMiniMap=0\nMinimapScale=0.5000\n",
            encoding="utf-8")
        ck = read_hud_settings(game_cfg=cfg, persisted=tmp_path / "nope.json")["config_key"]
        assert ck.startswith(f"{w}x{h}|")
        prof = vp.load_profile(ck)
        assert prof["source"] == "resolution_seed", ck
        assert prof["base"] == [w, h]
        # proportionally scaled, NOT the unscaled 1080p baseline
        assert prof["regions"]["hp"] != [800, 900, 1100, 960]
