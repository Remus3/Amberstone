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


def test_onhit_coherence_fail_soft_for_non_roster_champ():
    assert dsc._onhit_coherence_for("Garen") == 0.0
