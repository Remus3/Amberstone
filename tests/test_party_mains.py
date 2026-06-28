"""PARTY MAINS lobby enrichment - dashboard/_party_mains.py.

Covers the pure builder (shape, self-exclusion, fail-soft drops) and the
non-blocking enrich glue (cached injection + the no-op guards). The Riot API +
champion-name lookups are monkeypatched; no network, no real threads (the cache
is pre-seeded fresh so the background refresh never triggers in a test).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.archetype_picks as AP  # noqa: E402
import core.riot_api as RA  # noqa: E402
import dashboard._party_mains as PM  # noqa: E402


def _member(riot_id, game, tag, *, is_self=False, name=None):
    return {"riot_id": riot_id, "game_name": game, "tag_line": tag,
            "is_self": is_self, "summoner_name": name or game}


def setup_function(_):
    PM._reset_cache_for_tests()


def _patch(monkeypatch, *, account, tops, champ="Jinx"):
    monkeypatch.setattr(RA, "get_account_by_riot_id", lambda g, t, **k: account)
    monkeypatch.setattr(RA, "get_top_champion_masteries", lambda p, **k: tops)
    monkeypatch.setattr(AP, "champion_name_by_key", lambda cid: champ)


def test_build_party_mains_shape(monkeypatch):
    _patch(monkeypatch, account={"puuid": "P-Duo"},
           tops=[{"championId": 222, "championLevel": 7, "championPoints": 43989}])
    members = [_member("Me#NA1", "Me", "NA1", is_self=True),
               _member("Duo#NA1", "Duo", "NA1")]
    assert PM.build_party_mains(members) == [
        {"name": "Jinx", "player": "Duo", "mastery_level": 7, "mastery_points": 43989},
    ]


def test_build_excludes_self_and_riotidless(monkeypatch):
    _patch(monkeypatch, account={"puuid": "P"},
           tops=[{"championId": 1, "championLevel": 5, "championPoints": 100}],
           champ="Annie")
    members = [
        _member("Me#NA1", "Me", "NA1", is_self=True),   # self -> excluded
        {"riot_id": "x", "is_self": False},              # no game/tag -> excluded
        _member("Duo#NA1", "Duo", "NA1"),                # eligible
    ]
    out = PM.build_party_mains(members)
    assert len(out) == 1 and out[0]["name"] == "Annie" and out[0]["player"] == "Duo"


def test_build_failsoft_drops_failed_account(monkeypatch):
    _patch(monkeypatch, account=None, tops=None)
    assert PM.build_party_mains([_member("Duo#NA1", "Duo", "NA1")]) == []


def test_build_drops_when_no_mastery(monkeypatch):
    _patch(monkeypatch, account={"puuid": "P"}, tops=[])  # empty mastery list
    assert PM.build_party_mains([_member("Duo#NA1", "Duo", "NA1")]) == []


def _seed_fresh(members, data):
    PM._cache.update(key=PM._member_key(members), data=data,
                     fetched_at=time.time(), ttl=PM._TTL_S)


def test_enrich_injects_cached():
    members = [_member("Me#NA1", "Me", "NA1", is_self=True),
               _member("Duo#NA1", "Duo", "NA1")]
    card = {"name": "Jinx", "player": "Duo", "mastery_level": 7, "mastery_points": 1}
    _seed_fresh(members, [card])
    out = PM.enrich_party_mains({"lobby": {"members": members}})
    assert out["party_mains"] == [card]


def test_enrich_noop_solo():
    snap = {"lobby": {"members": [_member("Me#NA1", "Me", "NA1", is_self=True)]}}
    assert "party_mains" not in PM.enrich_party_mains(snap)


def test_enrich_noop_no_lobby():
    assert "party_mains" not in PM.enrich_party_mains({"phase": "InProgress"})


def test_enrich_noop_already_enriched():
    snap = {"party_mains": [{"name": "X"}], "lobby": {"members": [1, 2, 3]}}
    assert PM.enrich_party_mains(snap)["party_mains"] == [{"name": "X"}]


def test_enrich_nondict_passthrough():
    assert PM.enrich_party_mains(None) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
