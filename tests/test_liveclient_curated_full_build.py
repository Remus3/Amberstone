"""dashboard/_liveclient.py - curated full build must not pull the DS fallback.

BACKLOG row "item_advisor residuals" (filed 2026-09-11, LEDGER 1398), residual
(a). ``item_advisor.resolve_build`` returns ``[]`` for TWO different states:

  * an UNKNOWN (non-curated) champion - ``champion not in CHAMPION_BUILDS``
  * a KNOWN curated champion whose every curated item is already owned or
    exclusion-redundant (the ``current_items`` filter empties the list)

``liveclient_summary`` branched on ``if not build:`` and so treated a finished
curated champion as having NO build, re-sourcing the DS build-order table and
emitting ``next: true`` rows for items the curated path never asked for. The
same H3 predicate defect was fixed in ``item_advisor.get_purchase_advice`` by
gating on the table; this mirrors ``tests/test_item_advisor_empty_cache.py``.

The fallback is stubbed with a sentinel item so the test does not depend on
what the static DS table happens to carry for a curated champion.
"""
from __future__ import annotations

import contextlib
import os
import time
from unittest import mock

import pytest

import item_advisor as ia
from dashboard import _liveclient

_SENTINEL = "Sentinel Fallback Item"
_ENEMIES = ["Zed", "Lux"]


def _player(champ, team, owned=None):
    return {
        "summonerName": champ,
        "championName": champ,
        "team": team,
        "items": [
            {"displayName": n, "itemID": "0", "canUse": False, "count": 1}
            for n in (owned or [])
        ],
        "scores": {"kills": 1, "deaths": 1, "assists": 1,
                   "creepScore": 50, "wardScore": 0.0},
        "summonerSpells": {},
        "level": 16,
    }


def _allgamedata(champ, owned):
    return {
        "activePlayer": {
            "summonerName": champ,
            "level": 16,
            "currentGold": 3000,
            "championStats": {
                "currentHealth": 800, "maxHealth": 1000,
                "resourceValue": 200, "resourceMax": 300,
            },
        },
        "allPlayers": [_player(champ, "ORDER", owned)]
        + [_player(e, "CHAOS") for e in _ENEMIES],
        "gameData": {"gameTime": 1800.0, "gameMode": "CLASSIC"},
    }


@contextlib.contextmanager
def _stubbed_fallback():
    stub = mock.Mock(return_value=[_SENTINEL])
    env = dict(os.environ)
    env["RC_NEXTBUY_DS_FALLBACK"] = "1"
    with mock.patch.dict(os.environ, env, clear=True), mock.patch(
        "core.next_buy_fallback.fallback_build", stub
    ):
        yield stub


def _summary(champ, owned):
    from core.liveclient_cache import Snapshot

    snap = Snapshot(data=_allgamedata(champ, owned), ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


def _next_names(out):
    return [r["name"] for r in (out.get("sr_items") or []) if r.get("next")]


def _full_curated(champ):
    # The build resolve_build would recommend from empty against THIS enemy
    # comp (threat swaps included), so owning all of it empties the list.
    return ia.resolve_build(champ, _ENEMIES, [])


@pytest.mark.parametrize("champ", sorted(ia.CHAMPION_BUILDS))
def test_full_build_curated_champion_does_not_pull_ds_fallback(champ):
    owned = _full_curated(champ)
    assert owned, f"{champ} has no curated build - test would be vacuous"
    # Precondition that makes this the conflated state: the resolved list IS
    # empty for a KNOWN champion.
    assert ia.resolve_build(champ, _ENEMIES, owned) == []
    with _stubbed_fallback() as stub:
        out = _summary(champ, owned)
    assert stub.call_count == 0, (
        f"{champ}: finished curated build was treated as no build and "
        "re-sourced from the DS fallback table"
    )
    assert _SENTINEL not in _next_names(out), out.get("sr_items")
    assert _next_names(out) == [], out.get("sr_items")
    # Owned rows still render, so the panel is not blanked by the fix.
    assert [r["name"] for r in out["sr_items"] if r.get("owned")]


def test_non_curated_champion_still_uses_ds_fallback():
    """Guard: an unknown champion keeps the RM-114 fallback."""
    assert "Aatrox" not in ia.CHAMPION_BUILDS
    with _stubbed_fallback() as stub:
        out = _summary("Aatrox", [])
    assert stub.call_count == 1
    assert _SENTINEL in _next_names(out), out.get("sr_items")


def test_partial_curated_build_still_emits_curated_next_and_skips_fallback():
    """Guard: a mid-game curated build keeps the curated path, no fallback."""
    full = _full_curated("Jinx")
    owned = full[:2]
    with _stubbed_fallback() as stub:
        out = _summary("Jinx", owned)
    assert stub.call_count == 0
    names = _next_names(out)
    assert names, out.get("sr_items")
    assert _SENTINEL not in names
    assert names[0] == full[2], names
