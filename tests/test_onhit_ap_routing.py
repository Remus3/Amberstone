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
