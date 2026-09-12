"""item_advisor.py - empty-sentinel conflation + failed-load cache poisoning.

Slice E of the lane/true-audit pass (2026-09-11). Ground truth measured against
``item_advisor.py`` at 9706c65c7 before any edit:

H3 (REAL) - ``resolve_build`` returns ``[]`` for an UNKNOWN champion (:336-337)
and ALSO ``[]`` for a KNOWN champion whose every curated item is already owned
or exclusion-redundant (:373-380). ``get_purchase_advice`` (:602-604) then
labels BOTH "Unknown champion"; its "BUILD COMPLETE" branch (:615-616) is dead
whenever ``current_items`` is passed. The frozen caller
``app/_game_lifecycle.py:472-478`` always passes ``current_items`` and renders
``adv["display"]`` straight into ``app.data["reset_item"]``, so a full-build
Jinx - one of the six curated champions - read "Unknown champion" on screen.

H1 (REAL) - ``_load_exclusions`` (:394-403) caches ``{}`` PERMANENTLY on any
read or parse error (sentinel ``is not None`` at :397) and the module imports
no logging, so after ONE transient read error ``is_redundant`` runs
exclusion-blind for the process lifetime with nothing retrying and nothing
logged. ``tools/build_portable.py:134-135`` creates ``data/`` as an EMPTY
placeholder, so a portable deploy takes this branch on its first call. The
sibling ``_load_matchup_weights`` (:272-283) takes the opposite branch (never
caches a failure, re-reads every call) and is equally silent.

H2 (REFUTED) - no consumer mutates a module dict in place; every structure
that escapes the module is a fresh ``list`` / ``str`` / ``tuple``. No test
here because there is nothing to pin.

The three "guard" tests below characterize behaviour that must NOT move so the
fix cannot over-correct (unknown champion stays unknown, a partial build still
emits a path, a successful load is still cached).
"""
from __future__ import annotations

import logging

import pytest

import item_advisor as ia

# Jinx's curated default path + boots (item_advisor.CHAMPION_BUILDS["Jinx"]).
_JINX_FULL = [
    "Yun Tal Wildarrows",
    "Berserker's Greaves",
    "Runaan's Hurricane",
    "Infinity Edge",
    "Lord Dominik's Regards",
    "Phantom Dancer",
    "Bloodthirster",
]

_REAL_EXCLUSIONS_PATH = ia._EXCLUSIONS_PATH


@pytest.fixture
def fresh_caches(monkeypatch):
    """Reset every module-level cache so each test starts from a cold load
    and leaves no poisoned cache behind for the rest of the session."""
    monkeypatch.setattr(ia, "_EXCLUSIONS_CACHE", None)
    monkeypatch.setattr(ia, "_MATCHUP_WEIGHTS", None)
    # Introduced by the fix; ``raising=False`` so the RED run fails on the
    # assertion it is meant to fail on, not on an AttributeError here.
    monkeypatch.setattr(ia, "_WARNED_LOAD_PATHS", set(), raising=False)
    yield


# --------------------------------------------------------------------------
# H3 - full-build curated champion must not read "Unknown champion"
# --------------------------------------------------------------------------


class TestFullBuildIsNotUnknownChampion:
    def test_full_build_curated_champion_is_build_complete(self):
        adv = ia.get_purchase_advice("Jinx", list(_JINX_FULL), 3000, ["Caitlyn"])
        assert adv["display"] != "Unknown champion", adv
        assert adv["display"] == "BUILD COMPLETE", adv
        assert adv.get("next_item") is None, adv
        assert adv["buy_now"] == [], adv

    def test_full_build_every_curated_champion(self):
        """Sibling sweep: the conflation is per-champion, so pin all six."""
        for champ, cfg in ia.CHAMPION_BUILDS.items():
            full = list(cfg["default"]) + [cfg["boots_item"]]
            adv = ia.get_purchase_advice(champ, full, 3000, [])
            assert adv["display"] == "BUILD COMPLETE", (champ, adv)

    def test_unknown_champion_is_still_labelled_unknown(self):
        """Guard: the fix must not relabel a genuinely unknown champion."""
        adv = ia.get_purchase_advice("NotAChampion", [], 3000, ["Caitlyn"])
        assert adv["display"] == "Unknown champion", adv
        assert adv["build_path"] == []

    def test_partial_build_curated_champion_still_emits_path(self):
        """Guard: a mid-game build keeps the PATH / next_item shape."""
        adv = ia.get_purchase_advice(
            "Jinx", ["Yun Tal Wildarrows", "Berserker's Greaves"], 1200, ["Caitlyn"]
        )
        assert adv["display"].startswith("PATH: "), adv
        assert adv["next_item"] == "Runaan's Hurricane", adv
        assert "Yun Tal Wildarrows" not in adv["remaining"]


# --------------------------------------------------------------------------
# H1 - a failed exclusions load must not be cached as a success-shaped {}
# --------------------------------------------------------------------------


def _missing(tmp_path):
    return tmp_path / "does_not_exist.json"


def _malformed_text(tmp_path):
    p = tmp_path / "malformed.json"
    p.write_text("{not json", encoding="utf-8")
    return p


def _wrong_shape(tmp_path):
    p = tmp_path / "list_shaped.json"
    p.write_text('["boots", "trinket"]', encoding="utf-8")
    return p


_BAD_FILES = [_missing, _malformed_text, _wrong_shape]


class TestExclusionsLoadFailureIsNotPermanent:
    @pytest.mark.parametrize("make_bad", _BAD_FILES, ids=lambda f: f.__name__)
    def test_failure_returns_empty_then_retries_on_next_call(
        self, fresh_caches, monkeypatch, tmp_path, make_bad
    ):
        monkeypatch.setattr(ia, "_EXCLUSIONS_PATH", make_bad(tmp_path))
        first = ia._load_exclusions()
        assert first == {}, first
        # The failure must NOT have been promoted into the cache.
        assert ia._EXCLUSIONS_CACHE is None, (
            "failed load was cached as {} - is_redundant() would run "
            "exclusion-blind for the process lifetime"
        )
        # File becomes readable again (transient lock / AV scan / deploy fixed).
        monkeypatch.setattr(ia, "_EXCLUSIONS_PATH", _REAL_EXCLUSIONS_PATH)
        second = ia._load_exclusions()
        assert second, "second call did not retry the load"
        assert "boots" in second, sorted(second)[:5]

    @pytest.mark.parametrize("make_bad", _BAD_FILES, ids=lambda f: f.__name__)
    def test_failure_is_redundant_degrades_to_owned_only(
        self, fresh_caches, monkeypatch, tmp_path, make_bad
    ):
        """While the file is unreadable the advisor must still answer, and
        the answer must be the owned-only degradation - never a raise."""
        monkeypatch.setattr(ia, "_EXCLUSIONS_PATH", make_bad(tmp_path))
        assert ia.is_redundant("Mortal Reminder", ["Mortal Reminder"]) == (
            True, "already owned",
        )
        # Exclusion-group knowledge is unavailable: LDR vs Mortal falls open.
        assert ia.is_redundant("Lord Dominik's Regards", ["Mortal Reminder"]) == (
            False, "",
        )

    def test_failure_warns_once_per_path(
        self, fresh_caches, monkeypatch, tmp_path, caplog
    ):
        monkeypatch.setattr(ia, "_EXCLUSIONS_PATH", _missing(tmp_path))
        with caplog.at_level(logging.WARNING, logger="item_advisor"):
            ia._load_exclusions()
            ia._load_exclusions()
            ia._load_exclusions()
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert "does_not_exist.json" in warnings[0].getMessage()

    def test_successful_load_is_still_cached(self, fresh_caches):
        """Guard: the fix must not turn the success path into a per-call read."""
        first = ia._load_exclusions()
        assert first and "boots" in first
        assert ia._EXCLUSIONS_CACHE is first
        assert ia._load_exclusions() is first


# --------------------------------------------------------------------------
# H1 sibling - matchup weights loader is equally silent on failure
# --------------------------------------------------------------------------


class TestMatchupWeightsLoadFailure:
    def test_missing_file_warns_once_and_returns_none(
        self, fresh_caches, monkeypatch, tmp_path, caplog
    ):
        # ``_MATCHUP_WEIGHTS_PATH`` is hoisted by the fix; before it the loader
        # builds its path inline and this setattr is inert (RED by no warning).
        monkeypatch.setattr(
            ia, "_MATCHUP_WEIGHTS_PATH", _missing(tmp_path), raising=False
        )
        with caplog.at_level(logging.WARNING, logger="item_advisor"):
            assert ia._load_matchup_weights() is None
            assert ia._load_matchup_weights() is None
            assert ia.get_matchup_context(["Malphite", "Warwick"]) == ""
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert "does_not_exist.json" in warnings[0].getMessage()

    def test_successful_load_is_cached_and_context_nonempty(self, fresh_caches):
        """Guard: the real file still loads once and drives get_matchup_context."""
        w = ia._load_matchup_weights()
        assert isinstance(w, dict) and w
        assert ia._load_matchup_weights() is w
        # Any override champion present in the shipped table yields a note.
        overrides = w.get("enemy_item_overrides", {})
        assert overrides, "shipped matchup_weights.json carries no overrides"
        champ = next(iter(overrides))
        assert ia.get_matchup_context([champ]).startswith(f"vs {champ}: ")
