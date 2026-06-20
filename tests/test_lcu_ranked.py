"""RC 2.0 E9 - rank-identity header backend (core/lcu_ranked.py).

TDD characterization of the LCU ranked-stats read. The operator plays
mostly ARAM / Arena / event modes, so solo-queue rank is frequently
STALE or UNRANKED - the graceful empty state is a first-class path, not
an afterthought.

Endpoint (verified against the canonical LCU swagger, 2026-06-20):
  GET /lol-ranked/v1/current-ranked-stats -> LolRankedRankedStats
    queueMap            : object keyed by queue type (RANKED_SOLO_5x5, ...)
    highestRankedEntry  : LolRankedRankedQueueStats
  Per-queue entry (LolRankedRankedQueueStats):
    tier (str) division (str) leaguePoints (int) queueType (str)
    wins (int) losses (int) isProvisional (bool)

These tests mock the LCU read - they NEVER hit a live client.
"""
from __future__ import annotations

import core.lcu_ranked as lr


class _FakeLcu:
    """Stand-in for lcu.lcu_client.LcuClient with just the surface
    core/lcu_ranked needs: a _request(method, endpoint) that returns the
    mocked ranked-stats payload (or None to simulate a down client)."""

    def __init__(self, payload):
        self._payload = payload
        self.calls: list[tuple[str, str]] = []

    def _request(self, method, endpoint, data=None):
        self.calls.append((method, endpoint))
        return self._payload


def _solo_payload():
    """A realistic current-ranked-stats blob with a Platinum solo entry."""
    return {
        "queueMap": {
            "RANKED_SOLO_5x5": {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "PLATINUM",
                "division": "II",
                "leaguePoints": 47,
                "wins": 31,
                "losses": 27,
                "isProvisional": False,
            },
            "RANKED_FLEX_SR": {
                "queueType": "RANKED_FLEX_SR",
                "tier": "GOLD",
                "division": "I",
                "leaguePoints": 12,
                "wins": 4,
                "losses": 3,
                "isProvisional": False,
            },
        },
        "highestRankedEntry": {
            "queueType": "RANKED_SOLO_5x5",
            "tier": "PLATINUM",
            "division": "II",
            "leaguePoints": 47,
        },
    }


# -- endpoint constant pinned -------------------------------------------

def test_endpoint_constant_is_current_ranked_stats():
    assert lr.RANKED_STATS_ENDPOINT == "/lol-ranked/v1/current-ranked-stats"


# -- happy path: solo entry parses --------------------------------------

def test_reads_solo_queue_rank():
    lcu = _FakeLcu(_solo_payload())
    out = lr.read_ranked_identity(lcu)
    assert out is not None
    assert out["ranked"] is True
    assert out["tier"] == "PLATINUM"
    assert out["division"] == "II"
    assert out["lp"] == 47
    assert out["queue"] == "RANKED_SOLO_5x5"
    # Human-readable display string for the header.
    assert out["display"] == "PLATINUM II 47 LP"
    # The LCU read hit the verified endpoint exactly once.
    assert lcu.calls == [("GET", lr.RANKED_STATS_ENDPOINT)]


def test_solo_winrate_surfaced():
    out = lr.read_ranked_identity(_FakeLcu(_solo_payload()))
    assert out["wins"] == 31
    assert out["losses"] == 27
    # 31 / (31+27) = 0.5345 -> rounded to a whole percent for the header.
    assert out["win_rate_pct"] == 53


# -- graceful empty states ----------------------------------------------

def test_unranked_tier_none_is_graceful_empty():
    """LCU returns tier 'NONE' / division 'NA' for an unranked solo queue."""
    payload = {
        "queueMap": {
            "RANKED_SOLO_5x5": {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "NONE",
                "division": "NA",
                "leaguePoints": 0,
                "wins": 0,
                "losses": 0,
                "isProvisional": False,
            },
        },
    }
    out = lr.read_ranked_identity(_FakeLcu(payload))
    assert out is not None
    assert out["ranked"] is False
    assert out["tier"] is None
    assert out["display"] == "Unranked"
    # Never fabricate LP for an absent rank.
    assert out["lp"] is None


def test_empty_queue_map_is_graceful_empty():
    out = lr.read_ranked_identity(_FakeLcu({"queueMap": {}}))
    assert out is not None
    assert out["ranked"] is False
    assert out["display"] == "Unranked"


def test_lcu_down_returns_none():
    """_request returns None when the client is not connected - fail-soft."""
    out = lr.read_ranked_identity(_FakeLcu(None))
    assert out is None


def test_malformed_payload_returns_none():
    out = lr.read_ranked_identity(_FakeLcu(["not", "a", "dict"]))
    assert out is None


def test_none_client_returns_none():
    """A None LcuClient (never constructed) must not raise."""
    assert lr.read_ranked_identity(None) is None


# -- provisional placement games surface but do not fabricate -----------

def test_provisional_entry_marked():
    payload = {
        "queueMap": {
            "RANKED_SOLO_5x5": {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "NONE",
                "division": "NA",
                "leaguePoints": 0,
                "wins": 2,
                "losses": 1,
                "isProvisional": True,
            },
        },
    }
    out = lr.read_ranked_identity(_FakeLcu(payload))
    assert out["ranked"] is False
    assert out["provisional"] is True
    assert out["display"] == "Placements (3 played)"


# -- ASCII hygiene (hard repo rule) -------------------------------------

def test_display_strings_are_ascii():
    for payload in (_solo_payload(), {"queueMap": {}}):
        out = lr.read_ranked_identity(_FakeLcu(payload))
        assert all(ord(c) < 128 for c in out["display"]), repr(out["display"])
