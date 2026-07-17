"""Slice B Task 7 (2026-07-16) - rank_onhit_for client + onhit dispatcher
branch tests. Mirrors tests/test_archetype_dispatcher.py style: the
underlying scorer call is mocked so the test doesn't touch the live DS
server on :8893.

Task 9/10 append more tests to this same file (roster seed/disjoint +
default_for_champion routing) once core/ds_onhit_ap_roster.py lands.
"""
from __future__ import annotations

from unittest.mock import patch

import core.daemon_slayer_client as dsc


def test_dispatch_routes_onhit():
    with patch.object(dsc, "rank_onhit_for", return_value=[]) as m:
        out = dsc.rank_for_primary_archetype(
            "Gwen", archetype="onhit", level=13, mode="SR", item_ids=[]
        )
    assert m.called
    assert out["ok"] is True and out["scorer"] == "onhit" and out["ranked"] == []


def test_dispatch_onhit_row_projects_conventional_delta_key():
    """Task 7 followup - the per-row projection must carry the generic
    "delta" key (the convention every other single-metric sibling branch
    follows: tank/mage/assassin/enchanter + the ds.dps carry fallback).
    Regression guard for the review finding: onhit used to emit ONLY
    "delta_dps", so a future direct row["delta"] access would KeyError.
    """
    stub_row = dsc.OnhitRankedItem(
        item_id="3006",
        item_name="Berserker's Greaves",
        gold=1100,
        delta_dps=42.5,
        new_dps=142.5,
        ability_dps=20.0,
        auto_dps=22.5,
        dps_per_1k_gold=38.6,
        is_terminal=False,
        tags=(),
    )
    with patch.object(dsc, "rank_onhit_for", return_value=[stub_row]) as m:
        out = dsc.rank_for_primary_archetype(
            "Gwen", archetype="onhit", level=13, mode="SR", item_ids=[]
        )
    assert m.called
    assert out["ok"] is True and out["scorer"] == "onhit"
    row = out["ranked"][0]
    assert row["delta"] == stub_row.delta_dps
    assert row["item_id"] == stub_row.item_id
    # delta_dps stays too (explicit for onhit-aware consumers) - both keys
    # carry the same value.
    assert row["delta_dps"] == stub_row.delta_dps


def test_onhit_coherence_fail_soft_for_non_roster_champ():
    assert dsc._onhit_coherence_for("Garen") == 0.0


# --- Slice B Task 9 (2026-07-16) - roster + loader ---------------------------
#
# Broad-scan classifier (tools/ds_onhit_ap_prefilter.py) scanned all 173
# champions for (AP-axis via agents.daemon_slayer.onhit_dps._onhit_ap_axis)
# AND (AS/on-hit-reliant); live-calibrated all 21 flagged candidates against
# :8893/rank-onhit at coherence 0.0/0.3/0.6/1.0. Only the seed 3 survived the
# conservative keep bar - see .superpowers/sdd/task-9-report.md for the full
# per-candidate evidence and drop reasons.
import json
import pathlib


def test_roster_seed_and_disjoint():
    roster = json.loads(
        pathlib.Path("core/ds_onhit_ap_roster.json").read_text(encoding="utf-8")
    )["champions"]
    assert {"Gwen", "Kayle", "KogMaw"} <= set(roster)
    from core.archetype_picks import _AP_ASSASSIN_IDS

    assert set(roster).isdisjoint(_AP_ASSASSIN_IDS)
    assert "Syndra" not in roster and "Akali" not in roster


def test_coherence_resolver_reads_flat_roster():
    # proves load_onhit_ap_roster flattens the nested json so
    # _onhit_coherence_for returns a scalar, not a dict-that-fail-softs-to-0.0
    assert dsc._onhit_coherence_for("Gwen") == 1.0
    assert dsc._onhit_coherence_for("KogMaw") == 0.6


# --- Slice B Task 9 followup (2026-07-16) - _flatten malformed-input coverage --
#
# Review left two Minor gaps on the loader flatten - the highest-risk surface
# here (a silent flatten regression no-ops the whole Slice B coherence gate,
# see the CRITICAL SHAPE CONTRACT note atop core/ds_onhit_ap_roster.py). Task
# 9's own report flagged this exact hole: "No test currently exercises that
# skip path specifically." _flatten is a pure function - it never touches the
# module cache/lock - so every case below calls it directly on in-memory
# dicts; no file I/O and no cache-reset seam needed. reset_roster_cache()
# (the report's second Minor: an unused test seam) had zero callers anywhere
# in the repo and no case below needs cache state cleared, so it was removed
# as dead code in core/ds_onhit_ap_roster.py rather than kept alive by a test
# written just to call it.
from core.ds_onhit_ap_roster import _flatten


def test_flatten_happy_path_nested_dict():
    raw = {
        "champions": {
            "Gwen": {"coherence": 1.0},
            "Kayle": {"coherence": 0.3},
            "KogMaw": {"coherence": 0.6},
        }
    }
    assert _flatten(raw) == {"Gwen": 1.0, "Kayle": 0.3, "KogMaw": 0.6}


def test_flatten_skips_bare_scalar_entry():
    # entry value is a bare float, not a {"coherence": ...} dict
    raw = {"champions": {"Bad": 0.5, "Gwen": {"coherence": 1.0}}}
    out = _flatten(raw)
    assert "Bad" not in out
    assert out == {"Gwen": 1.0}


def test_flatten_skips_entry_missing_coherence_key():
    raw = {"champions": {"Bad": {}, "Gwen": {"coherence": 1.0}}}
    out = _flatten(raw)
    assert "Bad" not in out
    assert out == {"Gwen": 1.0}


def test_flatten_skips_non_numeric_coherence():
    raw = {
        "champions": {
            "BadString": {"coherence": "not-a-number"},
            "BadNone": {"coherence": None},
            "Gwen": {"coherence": 1.0},
        }
    }
    out = _flatten(raw)
    assert "BadString" not in out
    assert "BadNone" not in out
    assert out == {"Gwen": 1.0}


def test_flatten_missing_champions_wrapper_returns_empty():
    assert _flatten({}) == {}
    assert _flatten({"not_champions": {"Gwen": {"coherence": 1.0}}}) == {}


def test_flatten_non_dict_top_level_returns_empty():
    assert _flatten([]) == {}
    assert _flatten("not-a-dict") == {}
    assert _flatten(None) == {}


# --- Slice B Task 10 (2026-07-16) - default_for_champion routing -------------
#
# Routes the on-hit-AP roster (Gwen/Kayle/KogMaw) to the ds.onhit scorer by
# default, adjacent to the existing _AP_ASSASSIN_IDS curated override. Controls
# prove the AP-assassin path (Akali/Ekko -> assassin) and the plain AP-mage
# default path (Syndra/Cassiopeia -> mage) are both untouched.
import pytest

from core.archetype_picks import default_for_champion


@pytest.mark.parametrize("champ", ["Gwen", "Kayle", "KogMaw"])
def test_routes_to_onhit(champ):
    p, s = default_for_champion(champ)
    assert p == "onhit" and s and s != "onhit"


@pytest.mark.parametrize("champ,exp", [("Syndra","mage"),("Cassiopeia","mage"),("Akali","assassin"),("Ekko","assassin")])
def test_controls_unchanged(champ, exp):
    assert default_for_champion(champ)[0] == exp
