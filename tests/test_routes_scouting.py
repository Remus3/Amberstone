"""RC 2.0 E9 - player-scouting backend (dashboard/routes_scouting.py).

Phase 1: ranks only (mains / tags are FUTURE). Given a champ-select or
live roster's puuids, return per-player solo-queue rank via the Riot key
(ADR-006, core/riot_api.py). Rate-limit-aware: cache, cap the fan-out at
10 players, fail-soft on any single-player error.

These tests mock core.riot_api - they NEVER hit a live Riot API. JSON
shape only; no web render this pass.
"""
from __future__ import annotations

import json
from unittest import mock

import dashboard.routes_scouting as rs


# -- fake request handler (mirrors BaseHTTPRequestHandler surface) -------

class _FakeHandler:
    """Captures the (code, body, ctype) a route writes via _send."""

    def __init__(self, path):
        self.path = path
        self.sent = None  # (code, dict)

    def _send(self, code, body, ctype, cache_control=None):
        payload = json.loads(body.decode("utf-8")) if body else {}
        self.sent = (code, payload)


def _post(handler, body):
    """Find the POST handler for /api/scouting and invoke it."""
    for matcher, fn in rs.POST_ROUTES:
        if matcher(handler.path):
            fn(handler, body)
            return handler.sent
    raise AssertionError("no POST route matched " + handler.path)


# Two solo-rank League-V4 entry lists keyed by the puuid we feed in.
_RANKS = {
    "puuid-a": [
        {"queueType": "RANKED_SOLO_5x5", "tier": "DIAMOND",
         "rank": "IV", "leaguePoints": 12, "wins": 40, "losses": 35},
    ],
    "puuid-b": [
        {"queueType": "RANKED_FLEX_SR", "tier": "GOLD",
         "rank": "II", "leaguePoints": 50, "wins": 10, "losses": 8},
    ],
    # puuid-c is intentionally absent -> unranked.
}


def _fake_get_summoner_rank(puuid, region="na1"):
    return _RANKS.get(puuid)  # None for unknown -> unranked path


def setup_function(_fn):
    rs._reset_cache_for_tests()


# -- shape + happy path --------------------------------------------------

def test_returns_per_player_rank_shape():
    handler = _FakeHandler("/api/scouting")
    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_fake_get_summoner_rank), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler,
                              {"puuids": ["puuid-a", "puuid-b", "puuid-c"]})
    assert code == 200
    assert payload["ok"] is True
    players = payload["players"]
    assert isinstance(players, list)
    assert len(players) == 3
    by_puuid = {p["puuid"]: p for p in players}

    a = by_puuid["puuid-a"]
    assert a["ranked"] is True
    assert a["tier"] == "DIAMOND"
    assert a["division"] == "IV"
    assert a["lp"] == 12
    assert a["display"] == "DIAMOND IV 12 LP"

    # puuid-b has only a flex entry; pick_solo_rank falls back to it.
    b = by_puuid["puuid-b"]
    assert b["ranked"] is True
    assert b["tier"] == "GOLD"

    # puuid-c never resolved -> graceful unranked, never fabricated.
    c = by_puuid["puuid-c"]
    assert c["ranked"] is False
    assert c["tier"] is None
    assert c["display"] == "Unranked"


# -- rate-limit awareness: fan-out cap at 10 -----------------------------

def test_fanout_capped_at_ten_players():
    handler = _FakeHandler("/api/scouting")
    seen = []

    def _track(puuid, region="na1"):
        seen.append(puuid)
        return None

    many = [f"p{i}" for i in range(25)]
    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_track), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler, {"puuids": many})
    assert code == 200
    # Only the first 10 distinct puuids are fanned out.
    assert len(seen) == 10
    assert len(payload["players"]) == 10
    assert payload.get("capped") is True


# -- caching: a repeat lookup does not re-call the Riot API --------------

def test_cache_avoids_duplicate_riot_calls():
    handler1 = _FakeHandler("/api/scouting")
    handler2 = _FakeHandler("/api/scouting")
    calls = []

    def _count(puuid, region="na1"):
        calls.append(puuid)
        return _RANKS.get(puuid)

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_count), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        _post(handler1, {"puuids": ["puuid-a"]})
        _post(handler2, {"puuids": ["puuid-a"]})
    # Second request served from the scouting cache - one Riot call total.
    assert calls == ["puuid-a"]
    assert handler2.sent[1]["players"][0]["cached"] is True


# -- duplicate puuids in one request are de-duped ------------------------

def test_duplicate_puuids_deduped():
    handler = _FakeHandler("/api/scouting")
    calls = []

    def _count(puuid, region="na1"):
        calls.append(puuid)
        return _RANKS.get(puuid)

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_count), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler,
                              {"puuids": ["puuid-a", "puuid-a", "puuid-a"]})
    assert calls == ["puuid-a"]
    assert len(payload["players"]) == 1


# -- fail-soft paths -----------------------------------------------------

def test_no_key_returns_graceful_degraded():
    handler = _FakeHandler("/api/scouting")
    with mock.patch.object(rs.riot_api, "is_configured", return_value=False):
        code, payload = _post(handler, {"puuids": ["puuid-a"]})
    assert code == 200
    assert payload["ok"] is False
    assert payload["reason"] == "riot_key_unconfigured"
    assert payload["players"] == []


def test_empty_puuids_ok_empty_list():
    handler = _FakeHandler("/api/scouting")
    with mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler, {"puuids": []})
    assert code == 200
    assert payload["ok"] is True
    assert payload["players"] == []


def test_single_player_error_does_not_break_batch():
    """A raised exception on one puuid must not fail the whole batch."""
    handler = _FakeHandler("/api/scouting")

    def _flaky(puuid, region="na1"):
        if puuid == "puuid-b":
            raise RuntimeError("simulated transport blip")
        return _RANKS.get(puuid)

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_flaky), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler,
                              {"puuids": ["puuid-a", "puuid-b"]})
    assert code == 200
    by_puuid = {p["puuid"]: p for p in payload["players"]}
    # a still resolved; b failed soft to unranked-with-error marker.
    assert by_puuid["puuid-a"]["ranked"] is True
    assert by_puuid["puuid-b"]["ranked"] is False
    assert by_puuid["puuid-b"].get("error") is True


def test_bad_body_returns_ok_empty():
    handler = _FakeHandler("/api/scouting")
    with mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler, {"not_puuids": 1})
    assert code == 200
    assert payload["players"] == []


# -- ASCII hygiene -------------------------------------------------------

def test_display_strings_ascii():
    handler = _FakeHandler("/api/scouting")
    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_fake_get_summoner_rank), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        _post(handler, {"puuids": ["puuid-a", "puuid-c"]})
    for p in handler.sent[1]["players"]:
        assert all(ord(c) < 128 for c in p["display"]), repr(p["display"])


# -- RM-349 sibling: the guard must cover the SHAPE, not just the fetch --
#
# _scout_one promises "A raised exception from the Riot layer fails THIS
# player to unranked-with-error so the batch always completes", but its
# try wrapped only riot_api.get_summoner_rank(...). _shape_rank(...) and
# _cache_put(...) ran after it, and _shape_rank coerces the League-V4
# wire fields bare - int(entry.get("wins") or 0) and its losses twin -
# the same expressions as the core/lcu_ranked.py anchor. ("or 0" absorbs
# every FALSY value, so only a TRUTHY non-numeric is reachable; lp is
# already isinstance-guarded here and is NOT part of this defect.)
#
# The promise is what breaks: _serve_scouting builds players via a list
# comprehension, so one bad player escapes to the outer handler and the
# response degrades to a 500 with "players": [] - every OTHER player's
# rank lost to one malformed entry.


def _entry(**overrides):
    entry = {"queueType": "RANKED_SOLO_5x5", "tier": "DIAMOND",
             "rank": "IV", "leaguePoints": 12, "wins": 40, "losses": 35}
    entry.update(overrides)
    return [entry]


def test_malformed_wins_does_not_break_the_batch():
    """RM-349 sibling acceptance: a hostile wins value fails ONE player."""
    handler = _FakeHandler("/api/scouting")

    def _hostile(puuid, region="na1"):
        if puuid == "puuid-b":
            return _entry(wins={"count": 40})
        return _RANKS.get(puuid)

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_hostile), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler, {"puuids": ["puuid-a", "puuid-b"]})

    assert code == 200
    by_puuid = {p["puuid"]: p for p in payload["players"]}
    # The whole point: puuid-a survives puuid-b being malformed.
    assert by_puuid["puuid-a"]["ranked"] is True
    assert by_puuid["puuid-b"]["ranked"] is False
    assert by_puuid["puuid-b"].get("error") is True


def test_malformed_losses_does_not_break_the_batch():
    """The sibling coercion one line down from wins."""
    handler = _FakeHandler("/api/scouting")

    def _hostile(puuid, region="na1"):
        return _entry(losses=["35"]) if puuid == "puuid-b" else _RANKS.get(puuid)

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_hostile), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler, {"puuids": ["puuid-a", "puuid-b"]})

    assert code == 200
    by_puuid = {p["puuid"]: p for p in payload["players"]}
    assert by_puuid["puuid-a"]["ranked"] is True
    assert by_puuid["puuid-b"].get("error") is True


def test_raising_riot_helper_outside_the_fetch_is_caught():
    """pick_solo_rank and format_rank_entry are called by _shape_rank, i.e.
    outside the fetch. A raise from either must degrade one player too."""
    handler = _FakeHandler("/api/scouting")

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_fake_get_summoner_rank), \
         mock.patch.object(rs.riot_api, "format_rank_entry",
                           side_effect=RuntimeError("formatter blew up")), \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        code, payload = _post(handler, {"puuids": ["puuid-a"]})

    assert code == 200
    assert payload["players"][0].get("error") is True


def test_malformed_player_is_not_cached_as_a_good_row():
    """_cache_put also sat outside the guard. A degraded row must not be
    written to the cache as though it were a clean read."""
    handler = _FakeHandler("/api/scouting")

    def _hostile(puuid, region="na1"):
        return _entry(wins={"count": 1})

    with mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=_hostile) as fetch, \
         mock.patch.object(rs.riot_api, "is_configured", return_value=True):
        _post(handler, {"puuids": ["puuid-b"]})
        first_calls = fetch.call_count
        _post(_FakeHandler("/api/scouting"), {"puuids": ["puuid-b"]})
        # A poisoned row must not be served from cache on the next request.
        assert fetch.call_count > first_calls
