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

import json
import math
from collections import Counter
from pathlib import Path

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


class TestCanonicalNameKeyNotStolenByMirror:
    """R135: a canonical 4-digit item must own its own display-name key even
    when it grants ZERO movement speed.

    The mode mirrors (22xxxx Arena, 12xxxx ARAM, 44xxxx) share a display name
    with their 4-digit base but carry different stats (memory
    reference_item_name_is_not_the_id). _item_index() skipped zero-MS entries
    before they could claim the name key, so a bare-name lookup silently
    returned the MIRROR's movement speed for an item that has none on SR.

    Verified against data/meta/ddragon_items.json this run:
      3083  Warmog's Armor      pct 0     vs 443083 pct 0.04
      3193  Gargoyle Stoneplate pct 0     vs 443193 pct 0.10
      3430  Rite Of Ruin        pct 0     vs 123430 pct 0.04
    """

    @pytest.mark.parametrize("name", [
        "Warmog's Armor",
        "Gargoyle Stoneplate",
        "Rite of Ruin",
    ])
    def test_zero_ms_canonical_name_returns_zero(self, name):
        assert cms.item_ms(name) == {"flat": 0.0, "pct": 0.0}

    @pytest.mark.parametrize("iid,pct", [(443083, 0.04), (443193, 0.10), (123430, 0.04)])
    def test_mirror_still_resolves_by_explicit_id(self, iid, pct):
        # By-id stays authoritative: asking for the mirror by id still pays out.
        assert cms.item_ms(iid)["pct"] == pytest.approx(pct)

    def test_canonical_with_real_ms_is_unchanged(self):
        # 3009 Boots of Swiftness HAS movement speed, so it already claimed its
        # own name key. Guard that the fix does not regress the working path.
        assert cms.item_ms("Boots of Swiftness")["flat"] == 55.0


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


# -- roster distribution, read OFF DISK ---------------------------------------
#
# The mirror's shape used to be asserted only in prose (the module docstring
# claimed _FALLBACK_MS was "the most common base MS", which was FALSE - 335 is
# the mode with 42 champions; 345 is only fourth with 28). These helpers read
# the same file the module reads, so the shape is machine-checked instead.
# Never hardcode a roster dict here - read the contract off disk.

def _roster_rows():
    """(ddragon_key, entry) rows from the champion mirror the module reads."""
    raw = json.loads(cms._CHAMPS_PATH.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    return sorted(data.items())


def _roster_movespeeds():
    return [float(e["stats"]["movespeed"]) for _k, e in _roster_rows()]


def _movespeed_histogram():
    return Counter(_roster_movespeeds())


def _modal_movespeed():
    """The single most common base MS. Asserts uniqueness so a future patch
    that creates a tie fails loudly rather than picking an arbitrary winner."""
    hist = _movespeed_histogram()
    ranked = hist.most_common()
    assert len(ranked) > 1, "degenerate roster: only one distinct movespeed"
    assert ranked[0][1] > ranked[1][1], f"modal base MS is tied: {ranked[:3]}"
    return ranked[0][0]


class TestRosterDistributionCharacterization:
    """Characterization pins on data/meta/ddragon_champions.json. A DDragon
    patch refresh may legitimately move these numbers - update them from the
    mirror, do not delete the pin."""

    def test_roster_size(self):
        rows = _roster_rows()
        assert len(rows) == 173

    def test_every_champion_has_a_positive_movespeed(self):
        offenders = []
        for key, entry in _roster_rows():
            ms = (entry.get("stats") or {}).get("movespeed")
            if not isinstance(ms, (int, float)) or isinstance(ms, bool) or ms <= 0:
                offenders.append((key, ms))
        assert offenders == [], f"champions with missing/non-positive MS: {offenders}"

    def test_observed_range(self):
        speeds = _roster_movespeeds()
        assert min(speeds) == 315.0  # Rell
        assert max(speeds) == 355.0  # Master Yi

    def test_modal_movespeed_is_335_not_the_fallback(self):
        hist = _movespeed_histogram()
        assert _modal_movespeed() == 335.0
        assert hist[335.0] == 43
        # The claim the module docstring used to make, pinned as false:
        assert hist[cms._FALLBACK_MS] < hist[335.0]

    def test_full_histogram(self):
        assert dict(_movespeed_histogram()) == {
            315.0: 1,
            325.0: 19,
            # 16.15.1 moved Alistar 330 -> 335.
            330.0: 37,
            335.0: 43,
            340.0: 37,
            345.0: 28,
            350.0: 7,
            355.0: 1,
        }


class TestFallbackConsistentWithTheRoster:
    """_FALLBACK_MS is a live constant (core/mia_reachability.py:165 reaches it
    whenever a track carries no champion). Every factual claim the module makes
    about it must be checkable against the mirror."""

    def test_fallback_lies_inside_the_observed_range(self):
        speeds = _roster_movespeeds()
        assert min(speeds) <= cms._FALLBACK_MS <= max(speeds)

    def test_fallback_is_conservative_not_modal(self):
        # "Conservative for reachability" means the ring must not UNDER-reach:
        # the fallback should sit at or above most of the roster. Measured
        # 2026-07-28: 165 of 173 champions (95.4 pct) are at or below 345.
        speeds = _roster_movespeeds()
        covered = sum(1 for s in speeds if s <= cms._FALLBACK_MS)
        assert covered / len(speeds) >= 0.90, (
            f"_FALLBACK_MS {cms._FALLBACK_MS} covers only {covered}/{len(speeds)} "
            "of the roster - it is no longer conservative for reachability"
        )
        assert cms._FALLBACK_MS >= _modal_movespeed()

    def test_module_text_makes_no_unchecked_modality_claim(self):
        """THE DEFECT CLASS: a hardcoded live constant whose comment justifies
        it with a factual claim about data on disk that nobody checks. If the
        module says the fallback is the most common base MS, it must BE the
        most common base MS."""
        src = Path(cms.__file__).read_text(encoding="utf-8")
        phrases = ("most common", "most frequent", "commonest", "modal ")
        claims = [
            ln.strip()
            for ln in src.splitlines()
            if any(p in ln.casefold() for p in phrases)
        ]
        if not claims:
            return  # corrected prose makes no modality claim - nothing to check
        assert cms._FALLBACK_MS == _modal_movespeed(), (
            "module text claims the fallback is the most common base MS, but "
            f"the mirror's mode is {_modal_movespeed()} and _FALLBACK_MS is "
            f"{cms._FALLBACK_MS}. Offending lines: {claims}"
        )


class TestRosterTotalCoverage:
    """Every champion in the mirror must resolve from BOTH the DDragon id key
    and the display name, to the same value, without touching the fallback.
    This is the test that catches a mirror regression or a name-normalization
    break ("Nunu & Willump", "Kha'Zix", "Wukong"/"MonkeyKing", "Renata Glasc").
    """

    def test_all_champions_resolve_from_id_and_name_without_fallback(
        self, monkeypatch
    ):
        # Sentinel fallback: a champion whose real base MS is 345.0 would be
        # indistinguishable from a fallthrough under the shipped constant.
        sentinel = -1.0
        monkeypatch.setattr(cms, "_FALLBACK_MS", sentinel)
        cms._reset_caches()

        failures = []
        for key, entry in _roster_rows():
            want = float(entry["stats"]["movespeed"])
            for form in (key, entry.get("id"), entry.get("name")):
                if not isinstance(form, str):
                    failures.append((key, form, "non-string form in mirror"))
                    continue
                got = cms.base_ms(form)
                if got == sentinel:
                    failures.append((key, form, "FELL THROUGH to _FALLBACK_MS"))
                elif got != want:
                    failures.append((key, form, f"got {got}, want {want}"))
        assert failures == [], f"{len(failures)} champion lookups broke: {failures[:20]}"

    def test_tricky_display_names_resolve_to_the_mirror_value(self):
        by_name = {e["name"]: float(e["stats"]["movespeed"]) for _k, e in _roster_rows()}
        for name in (
            "Nunu & Willump",
            "Kha'Zix",
            "Wukong",
            "Renata Glasc",
            "Cho'Gath",
            "Dr. Mundo",
            "Bel'Veth",
        ):
            assert name in by_name, f"mirror no longer carries {name!r}"
            assert cms.base_ms(name) == by_name[name]

    def test_display_name_and_ddragon_key_agree(self):
        # Wukong is the canonical key/name divergence (key MonkeyKing).
        assert cms.base_ms("Wukong") == cms.base_ms("MonkeyKing")
        assert cms.base_ms("Nunu & Willump") == cms.base_ms("Nunu")


class TestRosterPathNeverRaises:
    """Fail-soft contract: nothing added above may make the module raise."""

    def test_mangled_roster_forms_never_raise(self):
        for _key, entry in _roster_rows():
            name = entry["name"]
            for form in (
                name,
                name.upper(),
                name.lower(),
                f"  {name}  ",
                name.replace(" ", ""),
                name + "\x00",
                name * 3,
            ):
                out = cms.base_ms(form)
                assert isinstance(out, float)
                assert out > 0.0

    def test_adversarial_inputs_never_raise(self):
        class _Explosive:
            def __str__(self):
                raise RuntimeError("boom")

            def __repr__(self):
                raise RuntimeError("boom")

        def _bad_gen():
            yield 1001
            raise RuntimeError("boom")

        for bad in (None, 0, -1, 3.5, b"Aatrox", object(), _Explosive(), [[]], {1: 2}):
            assert isinstance(cms.base_ms(bad), float)
            assert isinstance(cms.item_ms(bad), dict)
            assert isinstance(cms.est_ms(bad, bad), float)
            assert isinstance(cms.distance_frac_per_s(bad), float)

        assert cms.item_ms(_bad_gen()) == {"flat": 0.0, "pct": 0.0}
        assert cms.est_ms("Aatrox", _bad_gen()) > 0.0

    def test_fallback_still_reachable_and_positive(self):
        # The shipped constant is unchanged by this slice.
        assert cms._FALLBACK_MS == 345.0
        assert cms.base_ms("DefinitelyNotAChampion") == 345.0
