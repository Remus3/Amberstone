"""Tests for core.champion_movespeed (spec E-pre, ZOI/district Wave 1).

Champion movement-speed primitives for the future MIA-reachability
consumer. Ground truth verified before scaffolding:
  - data/meta/ddragon_champions.json: {"data": {<DDragonId>: {"id", "name",
    "stats": {"movespeed": <int>}}}} (Aatrox=345, MissFortune=325,
    MonkeyKing/"Wukong"=340).
  - data/meta/ddragon_items.json: {"data": {<id-str>: {"name",
    "stats": {"FlatMovementSpeedMod": <units>,
              "PercentMovementSpeedMod": <unit-fraction>}}}}
    (1001 "Boots" flat 25, 3009 "Boots of Swiftness" flat 55,
     2065 "Shurelya's Battlesong" pct 0.04).
  - MS stat vocabulary: agents/daemon_slayer/stats.py:107-108.
  - SR map extent ~14800 game units: core/vision_tracker.py:55.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import math

import pytest

import core.champion_movespeed as cms

_FALLBACK = 345.0


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Each test starts from cold module caches (lazy-load seam)."""
    cms._reset_caches()
    yield
    cms._reset_caches()


# -- base_ms ------------------------------------------------------------------

class TestBaseMs:
    def test_known_champ_345(self):
        assert cms.base_ms("Aatrox") == 345.0

    def test_ddragon_id_form(self):
        assert cms.base_ms("MissFortune") == 325.0

    def test_display_name_form(self):
        assert cms.base_ms("Miss Fortune") == 325.0

    def test_apostrophe_display_name_matches_id(self):
        by_name = cms.base_ms("Kha'Zix")
        by_id = cms.base_ms("Khazix")
        assert by_name == by_id
        assert 300.0 <= by_name <= 400.0

    def test_wukong_alias_both_forms(self):
        assert cms.base_ms("Wukong") == 340.0
        assert cms.base_ms("MonkeyKing") == 340.0

    def test_case_insensitive(self):
        assert cms.base_ms("missfortune") == 325.0
        assert cms.base_ms("MISS FORTUNE") == 325.0

    def test_unknown_champ_fallback(self):
        assert cms.base_ms("DefinitelyNotAChampion") == _FALLBACK

    def test_none_fallback(self):
        assert cms.base_ms(None) == _FALLBACK

    def test_garbage_type_fallback(self):
        assert cms.base_ms(42) == _FALLBACK
        assert cms.base_ms({"champion": "Ahri"}) == _FALLBACK
        assert cms.base_ms(["Ahri"]) == _FALLBACK
        assert cms.base_ms("") == _FALLBACK

    def test_missing_data_file_fallback(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cms, "_CHAMPS_PATH", tmp_path / "nope.json")
        assert cms.base_ms("Aatrox") == _FALLBACK

    def test_corrupt_data_file_fallback(self, monkeypatch, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(cms, "_CHAMPS_PATH", bad)
        assert cms.base_ms("Aatrox") == _FALLBACK


# -- item_ms ------------------------------------------------------------------

class TestItemMs:
    def test_none_is_zero(self):
        assert cms.item_ms(None) == {"flat": 0.0, "pct": 0.0}

    def test_empty_is_zero(self):
        assert cms.item_ms([]) == {"flat": 0.0, "pct": 0.0}

    def test_flat_by_id_str(self):
        out = cms.item_ms(["1001"])
        assert out["flat"] == 25.0
        assert out["pct"] == 0.0

    def test_flat_by_id_int(self):
        out = cms.item_ms([1001])
        assert out["flat"] == 25.0

    def test_flat_by_name(self):
        out = cms.item_ms(["Boots of Swiftness"])
        assert out["flat"] == 55.0

    def test_pct_item(self):
        out = cms.item_ms(["2065"])
        assert out["flat"] == 0.0
        assert out["pct"] == pytest.approx(0.04)

    def test_flat_and_pct_sum(self):
        out = cms.item_ms(["1001", "2065"])
        assert out["flat"] == 25.0
        assert out["pct"] == pytest.approx(0.04)

    def test_liveclient_dict_forms(self):
        # dashboard/_liveclient.py:131,135 - items carry itemID + displayName.
        assert cms.item_ms([{"itemID": 1001}])["flat"] == 25.0
        assert cms.item_ms([{"displayName": "Boots of Swiftness"}])["flat"] == 55.0

    def test_bare_string_treated_as_single_item(self):
        # A bare str is one item name, never iterated char-by-char.
        assert cms.item_ms("Boots of Swiftness")["flat"] == 55.0

    def test_unknown_items_zero(self):
        out = cms.item_ms(["999999", "Not An Item", None, {}, []])
        assert out == {"flat": 0.0, "pct": 0.0}

    def test_garbage_scalar_zero(self):
        assert cms.item_ms(3.14159) == {"flat": 0.0, "pct": 0.0}
        assert cms.item_ms(object()) == {"flat": 0.0, "pct": 0.0}

    def test_missing_data_file_zero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cms, "_ITEMS_PATH", tmp_path / "nope.json")
        assert cms.item_ms(["1001"]) == {"flat": 0.0, "pct": 0.0}


# -- est_ms -------------------------------------------------------------------

class TestEstMs:
    def test_no_items_equals_base(self):
        assert cms.est_ms("Aatrox") == cms.base_ms("Aatrox") == 345.0
        assert cms.est_ms("Aatrox", items=None) == 345.0
        assert cms.est_ms("Aatrox", items=[]) == 345.0

    def test_flat_composition(self):
        assert cms.est_ms("Aatrox", ["1001"]) == pytest.approx(370.0)

    def test_flat_then_pct_composition(self):
        # (base + flat) * (1 + pct)
        expect = (345.0 + 25.0) * 1.04
        assert cms.est_ms("Aatrox", ["1001", "2065"]) == pytest.approx(expect)

    def test_self_consistent_with_parts(self):
        items = ["3009", "2065"]
        base = cms.base_ms("Miss Fortune")
        parts = cms.item_ms(items)
        expect = (base + parts["flat"]) * (1.0 + parts["pct"])
        assert cms.est_ms("Miss Fortune", items) == pytest.approx(expect)

    def test_level_accepted_and_ignored(self):
        # Base MS does not scale with level in League; param kept for the
        # future MIA consumer's signature stability.
        assert cms.est_ms("Aatrox", None, 18) == cms.est_ms("Aatrox")
        assert cms.est_ms("Aatrox", None, "not-a-level") == 345.0

    def test_unknown_champ_uses_fallback_base(self):
        assert cms.est_ms(None, ["1001"]) == pytest.approx(_FALLBACK + 25.0)

    def test_fail_soft_garbage_everything(self):
        out = cms.est_ms(12345, "garbage-items", object())
        assert isinstance(out, float)
        assert math.isfinite(out)
        assert out > 0.0


# -- distance_frac_per_s ------------------------------------------------------

class TestDistanceFracPerS:
    def test_default_sr_extent(self):
        assert cms.distance_frac_per_s(370.0) == pytest.approx(370.0 / 14800.0)

    def test_explicit_extent(self):
        assert cms.distance_frac_per_s(300.0, map_extent=1000.0) == pytest.approx(0.3)

    def test_cross_map_time_sanity(self):
        # A 345-MS champion crosses ~14800 units in ~43s; box-fraction/s
        # inverse must land in a plausible 30-60s window.
        frac = cms.distance_frac_per_s(345.0)
        assert frac > 0.0
        assert 30.0 < (1.0 / frac) < 60.0

    def test_garbage_ms_zero(self):
        assert cms.distance_frac_per_s(None) == 0.0
        assert cms.distance_frac_per_s("fast") == 0.0
        assert cms.distance_frac_per_s(float("nan")) == 0.0
        assert cms.distance_frac_per_s(-10.0) == 0.0

    def test_bad_extent_zero(self):
        assert cms.distance_frac_per_s(345.0, map_extent=0.0) == 0.0
        assert cms.distance_frac_per_s(345.0, map_extent=-5.0) == 0.0
        assert cms.distance_frac_per_s(345.0, map_extent=None) == 0.0
