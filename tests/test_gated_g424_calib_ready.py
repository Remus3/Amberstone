"""Tests for tools/gated_g424_calib_ready.py (G4-24 PREP, s144 lane gated c80).

Every input is hand-built (RM-906: no real game, match or player id). The tool is
a read-only grader; these tests pin its verdicts and the source facts the doc row
cites. No screen, relay, :2999 or real game.cfg is touched.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from core import hud_settings as hs
from core import vision_profiles as vp
from tools import gated_g424_calib_ready as g424

ROOT = Path(__file__).resolve().parent.parent
LAY0 = {"GlobalScale": "0.0000", "ShowTeamFramesOnLeft": "0", "MirroredScoreboard": "0",
        "FlipMiniMap": "0", "MinimapScale": "1.6200"}


def _key(res: str = "2560x1440", **over) -> str:
    lay = dict(LAY0, **over)
    return "|".join([res] + [f"{k}={lay[k]}" for k in hs._LAYOUT_KEYS])


def _hud(ck: str, **over) -> dict:
    return {"config_key": ck, "layout": dict(LAY0, **over)}


CAL = _key()


def _write(d: Path, stem: str, ck: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.json").write_text(json.dumps({"config_key": ck}), encoding="utf-8")


def _root(tmp_path: Path, profiles=(), refs=(), states=()) -> Path:
    for ck in profiles:
        _write(tmp_path / g424.PROFILES_REL, vp._safe(ck), ck)
    for ck in refs:
        _write(tmp_path / g424.REF_REL, vp._safe(ck), ck)
    for ck in states:
        _write(tmp_path / g424.REF_REL, vp._safe(ck) + "__self_dead", ck)
    return tmp_path


def test_parse_key_roundtrip_and_unknown():
    res, tog = g424.parse_key(CAL)
    assert res == "2560x1440" and tog == LAY0
    for bad in ("unknown", "", None, "2560x1440|GlobalScale", "noresolution|A=1"):
        assert g424.parse_key(bad) is None


def test_calibrated_on_exact_key(tmp_path):
    root = _root(tmp_path, profiles=[CAL], refs=[CAL])
    out, code = g424.run(root, hud=_hud(CAL))
    assert (out["verdict"], code, out["predicted_tier"]) == ("CALIBRATED", 0, "profile")
    assert out["layout_matches_a_profile"] is True


def test_ready_to_calibrate_when_only_a_still(tmp_path):
    live = _key(MinimapScale="0.9300")
    root = _root(tmp_path, profiles=[CAL], refs=[CAL, live])
    out, code = g424.run(root, hud=_hud(live, MinimapScale="0.9300"))
    assert (out["verdict"], code) == ("READY_TO_CALIBRATE", 3)
    assert out["predicted_tier"] == "resolution_seed"  # 2560x1440 is in SEED_BASES
    assert out["nearest_profiles"][0]["differs"] == {"MinimapScale": ["0.9300", "1.6200"]}


def test_needs_reference_and_named_state_is_not_a_base_still(tmp_path):
    live = _key(GlobalScale="1.0000")
    root = _root(tmp_path, profiles=[CAL], refs=[CAL], states=[live])
    out, code = g424.run(root, hud=_hud(live, GlobalScale="1.0000"))
    assert (out["verdict"], code) == ("NEEDS_REFERENCE", 3)
    assert live not in out["base_stills"]


def test_key_unknown_still_reports_layout_distance(tmp_path):
    root = _root(tmp_path, profiles=[CAL])
    out, code = g424.run(root, hud=_hud("unknown", GlobalScale="1.0000",
                                        MinimapScale="1.0000"))
    assert (out["verdict"], code, out["predicted_tier"]) == ("KEY_UNKNOWN", 4,
                                                             "legacy_seed")
    assert out["layout_matches_a_profile"] is False
    assert out["nearest_profiles"][0]["differs"] == {
        "GlobalScale": ["1.0000", "0.0000"], "MinimapScale": ["1.0000", "1.6200"]}


def test_unseeded_resolution_predicts_legacy(tmp_path):
    live = _key(res="1920x1080")
    out, _code = g424.run(_root(tmp_path, profiles=[CAL]), hud=_hud(live))
    assert out["predicted_tier"] == "legacy_seed"
    # Same toggles at another resolution is NOT a layout match.
    assert out["nearest_profiles"][0]["differs"] == {"_res": ["1920x1080", "2560x1440"]}
    assert out["layout_matches_a_profile"] is False


def test_bad_files_are_skipped_not_fatal(tmp_path):
    d = tmp_path / g424.PROFILES_REL
    d.mkdir(parents=True)
    (d / "junk.json").write_text("{not json", encoding="utf-8")
    (d / "list.json").write_text("[1, 2]", encoding="utf-8")
    (d / "nokey.json").write_text(json.dumps({"config_key": "unknown"}), encoding="utf-8")
    assert g424.scan_keys(d) == []
    assert g424.scan_keys(tmp_path / "absent") == []


def test_tool_is_read_only_at_source():
    src = inspect.getsource(g424)
    for banned in ("write_text", "write_bytes", ".replace(", "unlink", "rename(",
                   "save_profile", "capture_reference", "save_reference_image",
                   "urlopen", "requests"):
        assert banned not in src, banned


@pytest.mark.parametrize("fact", ["layout", "ref"])
def test_source_facts_the_row_cites(fact):
    if fact == "layout":
        # config_key = WxH plus exactly these toggles, in this order.
        assert hs._LAYOUT_KEYS == ("GlobalScale", "ShowTeamFramesOnLeft",
                                   "MirroredScoreboard", "FlipMiniMap", "MinimapScale")
        src = inspect.getsource(hs.read_hud_settings)
        assert '"|".join(parts)' in src and 'config_key = "unknown"' in src
    else:
        # load_profile uses a profile only on the exact key (tier "profile"),
        # and G2-41's probe refuses a decisive verdict on any other source.
        src = inspect.getsource(vp.load_profile)
        assert "p = profile_path(ck)" in src and '"source": "profile"' in src
        g241 = (ROOT / "tools" / "gated_g241_ocr_native.py").read_text(encoding="utf-8")
        assert 'get("source") != "profile"' in g241
