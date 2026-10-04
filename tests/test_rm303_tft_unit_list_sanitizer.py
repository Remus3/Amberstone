# arch: regression - RM-303 one sanitizer for TFT board/bench/shop + numeric hp clamp | section=tft | frozen=no
"""RM-303 - the trait scrub + roster whitelist ran on shop_units ONLY, so a
trait read as a champion was published on the board / bench (and fed to the
prompt), and the hp clamp was isinstance-gated so the STRING "999" passed.
"""

import json

import pytest

import tft.tft_live_analysis as tla


def _bare(path):
    obj = object.__new__(tla.TftLiveAnalysis)
    obj._data_file = path
    obj._last_write = {}
    return obj


def _publish(tmp_path, vs):
    p = tmp_path / "tft_live_data.json"
    _bare(p)._write(vs, {}, {"stage_round": "3-2"})
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("field", ["board_units", "bench_units", "shop_units"])
def test_trait_name_rejected_in_every_list(tmp_path, field):
    vs = {field: ["Vanguard", "Jinx", "Space Groove/Stargazer"], "hp": 50}
    d = _publish(tmp_path, vs)
    assert d[field] == ["unknown", "Jinx", "unknown"]


@pytest.mark.parametrize("field", ["board_units", "bench_units"])
def test_star_annotation_kept_for_real_champion(tmp_path, field):
    vs = {field: ["Aatrox 2-star", "Caitlyn (3-star)", "empty"], "hp": 50}
    d = _publish(tmp_path, vs)
    assert d[field] == ["Aatrox 2-star", "Caitlyn (3-star)", "empty"]


@pytest.mark.parametrize("raw,want", [("999", 0), (999, 0), ("42", 42),
                                      ("abc", None), (-5, 0), (73, 73)])
def test_hp_coerced_before_clamp(tmp_path, raw, want):
    d = _publish(tmp_path, {"hp": raw})
    assert d["hp"] == want


def test_prompt_board_is_sanitized():
    got = tla.TftLiveAnalysis._clean_units(
        tla._sanitize_units(["Vanguard", "Jinx 2-star"]), set())
    assert got == ["Jinx 2-star"]


def test_whitelist_has_no_set17_false_negative():
    """The row's DO-NOT: widening the whitelist to the board must not rewrite
    a legitimate champion. Measured against the tracked Set 17 roster."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    codes = json.loads((root / "data/meta/tft_set17_champion_codes.json")
                       .read_text(encoding="utf-8"))
    assert len(codes) >= 60
    missing = [n for n in codes if n.lower() not in tla._TFT_CHAMP_LOWER]
    assert missing == []
