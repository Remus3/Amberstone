"""RC 2.0 E9 - rank-identity header wired into the home payload.

The home summary gains a `rank` field sourced from core/lcu_ranked. The
operator plays mostly ARAM / Arena / event modes, so the absent / unranked
state is the common case and must render a graceful header, never a
fabricated rank.

Tests pin the pure helper `_home_rank_identity` and the key-presence in
the assembled payload. LCU is mocked; no live client.
"""
from __future__ import annotations

from unittest import mock

import dashboard.builders_home as bh


class _FakeLcu:
    def __init__(self, payload):
        self._payload = payload

    def _request(self, method, endpoint, data=None):
        return self._payload


def _solo_payload():
    return {
        "queueMap": {
            "RANKED_SOLO_5x5": {
                "queueType": "RANKED_SOLO_5x5",
                "tier": "EMERALD", "division": "III",
                "leaguePoints": 33, "wins": 12, "losses": 9,
                "isProvisional": False,
            },
        },
    }


def test_home_rank_identity_ranked():
    out = bh._home_rank_identity(_FakeLcu(_solo_payload()))
    assert out["ranked"] is True
    assert out["tier"] == "EMERALD"
    assert out["display"] == "EMERALD III 33 LP"


def test_home_rank_identity_unranked_graceful():
    """No LCU / down client -> graceful unranked header, not None-crash."""
    out = bh._home_rank_identity(_FakeLcu(None))
    assert out["ranked"] is False
    assert out["display"] == "Unranked"
    assert out["tier"] is None


def test_home_rank_identity_none_client():
    out = bh._home_rank_identity(None)
    assert out["ranked"] is False
    assert out["display"] == "Unranked"


def test_build_home_summary_carries_rank_key():
    """`_build_home_summary` always includes a `rank` field. The DB read is
    real (read-only); we patch the LCU factory so no client is needed."""
    with mock.patch.object(bh, "_get_lcu_for_rank", return_value=_FakeLcu(_solo_payload())):
        summary = bh._build_home_summary()
    assert "rank" in summary
    assert summary["rank"]["tier"] == "EMERALD"
    assert summary["rank"]["display"] == "EMERALD III 33 LP"


def test_build_home_summary_rank_graceful_when_no_lcu():
    with mock.patch.object(bh, "_get_lcu_for_rank", return_value=None):
        summary = bh._build_home_summary()
    assert "rank" in summary
    assert summary["rank"]["ranked"] is False
    assert summary["rank"]["display"] == "Unranked"
