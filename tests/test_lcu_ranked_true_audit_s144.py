"""s144 true-audit of core/lcu_ranked.py (the home rank-identity header).

The LCU current-ranked-stats payload is bytes RC did not author. Before
this audit one junk field cost the whole rank (a str leaguePoints made the
read None, so a Platinum player read "Unranked"), while other junk was
RENDERED: a non-str or non-ASCII tier or division went into the header
text and the data-tier attribute, a negative or bool count produced a win
rate outside 0..100, a JSON big int raised inside the display format, a
"false" isProvisional string read as provisional, a provisional entry
reported games played under "wins", a payload with no queueMap read as
DEFINITIVELY unranked, and every failure was logged at DEBUG only.

The contract pinned here: one bad value drops that value only; a tier that
is not a short ASCII A-Z word means "could not read" (None); display text
is ASCII built from validated parts only; failures warn once per streak
naming the field and the TYPE, never the value.

These tests mock the LCU read - they never hit a live client. Every id and
value is synthetic.
"""
from __future__ import annotations

import logging

import pytest

import core.lcu_ranked as lr


class _FakeLcu:
    def __init__(self, payload=None, exc=None):
        self._payload = payload
        self._exc = exc

    def _request(self, method, endpoint, data=None):
        if self._exc is not None:
            raise self._exc
        return self._payload


def _solo(**overrides):
    entry = {
        "queueType": "RANKED_SOLO_5x5",
        "tier": "PLATINUM",
        "division": "II",
        "leaguePoints": 47,
        "wins": 31,
        "losses": 27,
        "isProvisional": False,
    }
    entry.update(overrides)
    return {"queueMap": {"RANKED_SOLO_5x5": entry}}


@pytest.fixture(autouse=True)
def _fresh_warn_state():
    reset = getattr(lr, "_reset_warnings", lambda: None)
    reset()
    yield
    reset()


def _warnings(caplog):
    return [r for r in caplog.records
            if r.name == lr.log.name and r.levelno >= logging.WARNING]


# -- tier: never rendered unless it is a short ASCII word ------------------

@pytest.mark.parametrize("tier", [
    {"name": "PLATINUM"},
    ["PLATINUM"],
    12,
    "PLATIN\u00dcM",
    "PLAT INUM",
    "PLATINUM\n",
    "PLAT\x00INUM",
    "A" * 200,
    "GOLD<b>",
], ids=lambda v: type(v).__name__)
def test_unreadable_tier_is_could_not_read_not_rendered(tier):
    assert lr.parse_ranked_stats(_solo(tier=tier)) is None


def test_null_or_absent_tier_is_still_unranked():
    out = lr.parse_ranked_stats(_solo(tier=None))
    assert out["ranked"] is False and out["display"] == "Unranked"
    payload = _solo()
    del payload["queueMap"]["RANKED_SOLO_5x5"]["tier"]
    out = lr.parse_ranked_stats(payload)
    assert out["ranked"] is False and out["display"] == "Unranked"


def test_lower_case_and_padded_tier_still_reads():
    out = lr.parse_ranked_stats(_solo(tier="  platinum "))
    assert out["ranked"] is True
    assert out["tier"] == "PLATINUM"


def test_unknown_but_well_formed_tier_still_reads():
    """A new Riot tier (EMERALD arrived in 2023) must not be refused."""
    out = lr.parse_ranked_stats(_solo(tier="OBSIDIAN"))
    assert out["ranked"] is True
    assert out["display"] == "OBSIDIAN II 47 LP"


# -- division: an enum, and apex tiers carry none ---------------------------

@pytest.mark.parametrize("division", [["II"], {"d": "II"}, 2, "V", "II\u00b7", "ii ii"])
def test_junk_division_drops_the_division_only(division):
    out = lr.parse_ranked_stats(_solo(division=division))
    assert out["ranked"] is True
    assert out["tier"] == "PLATINUM"
    assert out["division"] is None
    assert out["display"] == "PLATINUM 47 LP"


@pytest.mark.parametrize("tier", ["MASTER", "GRANDMASTER", "CHALLENGER"])
def test_apex_tier_shows_no_division(tier):
    out = lr.parse_ranked_stats(_solo(tier=tier, division="I", leaguePoints=250))
    assert out["division"] is None
    assert out["display"] == f"{tier} 250 LP"


def test_lower_case_division_is_normalised():
    out = lr.parse_ranked_stats(_solo(division=" iv "))
    assert out["division"] == "IV"
    assert out["display"] == "PLATINUM IV 47 LP"


# -- counts: one junk value drops that value only ---------------------------

@pytest.mark.parametrize("lp", [
    "N/A", "47", {"lp": 47}, ["47"], float("nan"), float("inf"),
    -float("inf"), 12.5, -1, True, 10 ** 30, 10 ** 5000,
], ids=lambda v: type(v).__name__)
def test_junk_league_points_drops_lp_and_keeps_the_rank(lp):
    out = lr.parse_ranked_stats(_solo(leaguePoints=lp))
    assert out is not None, repr(lp)[:40]
    assert out["ranked"] is True
    assert out["tier"] == "PLATINUM"
    assert out["lp"] is None
    assert out["display"] == "PLATINUM II"


def test_integral_float_league_points_is_accepted():
    out = lr.parse_ranked_stats(_solo(leaguePoints=47.0))
    assert out["lp"] == 47
    assert type(out["lp"]) is int
    assert out["display"] == "PLATINUM II 47 LP"


def test_zero_lp_is_shown_not_dropped():
    out = lr.parse_ranked_stats(_solo(leaguePoints=0))
    assert out["lp"] == 0
    assert out["display"] == "PLATINUM II 0 LP"


@pytest.mark.parametrize("field", ["wins", "losses"])
@pytest.mark.parametrize("value", [
    -5, True, 12.5, float("nan"), float("inf"), "12", {"n": 1}, 10 ** 30,
])
def test_junk_count_drops_that_count_and_the_win_rate(field, value):
    out = lr.parse_ranked_stats(_solo(**{field: value}))
    assert out["ranked"] is True
    assert out["display"] == "PLATINUM II 47 LP"
    assert out[field] is None
    assert out["win_rate_pct"] is None
    other = "losses" if field == "wins" else "wins"
    assert out[other] == (27 if other == "losses" else 31)


def test_win_rate_never_leaves_0_to_100():
    """wins 10, losses -5 used to report a 200 percent win rate."""
    out = lr.parse_ranked_stats(_solo(wins=10, losses=-5))
    assert out["win_rate_pct"] is None
    out = lr.parse_ranked_stats(_solo(wins=-10, losses=20))
    assert out["win_rate_pct"] is None


def test_counts_are_plain_ints():
    out = lr.parse_ranked_stats(_solo(wins=31.0, losses=27))
    assert type(out["wins"]) is int and out["wins"] == 31
    assert out["win_rate_pct"] == 53


# -- isProvisional is a real bool only -------------------------------------

@pytest.mark.parametrize("flag", ["false", "0", 1, [False], {"v": False}])
def test_non_bool_provisional_flag_is_not_provisional(flag):
    out = lr.parse_ranked_stats(_solo(isProvisional=flag))
    assert out["provisional"] is False


def test_true_provisional_flag_still_reads():
    out = lr.parse_ranked_stats(_solo(isProvisional=True))
    assert out["provisional"] is True


# -- provisional placements report wins as wins ----------------------------

def test_provisional_reports_real_wins_and_losses():
    out = lr.parse_ranked_stats(_solo(tier="NONE", division="NA", leaguePoints=0,
                                      wins=2, losses=1, isProvisional=True))
    assert out["ranked"] is False
    assert out["provisional"] is True
    assert out["wins"] == 2
    assert out["losses"] == 1
    assert out["display"] == "Placements (3 played)"


def test_provisional_with_one_junk_count_counts_the_good_one():
    out = lr.parse_ranked_stats(_solo(tier="", wins=2, losses="x", isProvisional=True))
    assert out["provisional"] is True
    assert out["wins"] == 2
    assert out["losses"] is None
    assert out["display"] == "Placements (2 played)"


# -- a payload with no queue map is "could not read", not "unranked" --------

@pytest.mark.parametrize("payload", [{}, {"queueMap": None}, {"queueMap": ["x"]},
                                     {"errorCode": "RPC_ERROR", "httpStatus": 404}])
def test_missing_queue_map_is_could_not_read(payload):
    assert lr.parse_ranked_stats(payload) is None


def test_empty_queue_map_is_still_definitively_unranked():
    out = lr.parse_ranked_stats({"queueMap": {}})
    assert out["ranked"] is False
    assert out["display"] == "Unranked"


def test_home_header_still_renders_unranked_when_the_map_is_missing():
    from dashboard import builders_home

    out = builders_home._home_rank_identity(_FakeLcu({}))
    assert out["ranked"] is False
    assert out["display"] == "Unranked"


# -- the parse itself never raises, and display is always ASCII -------------

class _Boom:
    def __str__(self):
        raise RuntimeError("boom")

    __repr__ = __str__

    def __bool__(self):
        raise RuntimeError("boom")


_HOSTILE = ("N/A", {}, ["3"], _Boom(), float("nan"), float("inf"), "12.5",
            10 ** 5000, -1, True, None, "\u00e9", "x" * 5000)


@pytest.mark.parametrize("field", ["tier", "division", "leaguePoints", "wins",
                                   "losses", "isProvisional"])
def test_parse_never_raises_and_display_is_ascii(field):
    for value in _HOSTILE:
        out = lr.parse_ranked_stats(_solo(**{field: value}))
        assert out is None or isinstance(out, dict)
        if out is not None:
            assert out["display"].isascii(), (field, out["display"][:40])
            assert len(out["display"]) <= 48, field


def test_hostile_solo_entry_container_never_raises():
    for entry in (_Boom(), 5, "x", ["a"]):
        out = lr.parse_ranked_stats({"queueMap": {"RANKED_SOLO_5x5": entry}})
        assert out is not None and out["ranked"] is False


# -- failures are warned once per streak, type only, never the value --------

def test_unreadable_tier_warns_once_per_streak_without_the_value(caplog):
    caplog.set_level(logging.DEBUG, logger=lr.log.name)
    secretish = "TIER-SENTINEL-\u00e9"
    for _ in range(3):
        assert lr.read_ranked_identity(_FakeLcu(_solo(tier=secretish))) is None
    hits = _warnings(caplog)
    assert len(hits) == 1
    msg = hits[0].getMessage()
    assert "tier" in msg and "str" in msg
    assert "SENTINEL" not in msg


def test_a_clean_read_ends_the_streak(caplog):
    caplog.set_level(logging.DEBUG, logger=lr.log.name)
    lr.read_ranked_identity(_FakeLcu(_solo(tier=["x"])))
    lr.read_ranked_identity(_FakeLcu(_solo()))
    lr.read_ranked_identity(_FakeLcu(_solo(tier=["x"])))
    assert len(_warnings(caplog)) == 2


def test_a_dropped_count_is_warned_once_naming_the_type(caplog):
    caplog.set_level(logging.DEBUG, logger=lr.log.name)
    for _ in range(3):
        out = lr.read_ranked_identity(_FakeLcu(_solo(leaguePoints="LP-SENTINEL")))
        assert out["lp"] is None
    hits = _warnings(caplog)
    assert len(hits) == 1
    msg = hits[0].getMessage()
    assert "leaguePoints" in msg and "str" in msg
    assert "SENTINEL" not in msg


def test_a_missing_queue_map_is_warned(caplog):
    caplog.set_level(logging.DEBUG, logger=lr.log.name)
    assert lr.read_ranked_identity(_FakeLcu({"httpStatus": 404})) is None
    hits = _warnings(caplog)
    assert len(hits) == 1
    assert "queueMap" in hits[0].getMessage()


def test_a_raising_read_warns_once_with_the_type_only(caplog):
    caplog.set_level(logging.DEBUG, logger=lr.log.name)
    for _ in range(3):
        out = lr.read_ranked_identity(_FakeLcu(exc=OSError("Basic SECRET-SENTINEL")))
        assert out is None
    hits = _warnings(caplog)
    assert len(hits) == 1
    msg = hits[0].getMessage()
    assert "OSError" in msg
    assert "SENTINEL" not in msg
    assert all("SENTINEL" not in r.getMessage() for r in caplog.records)


def test_lcu_down_is_normal_and_never_warns(caplog):
    caplog.set_level(logging.DEBUG, logger=lr.log.name)
    for _ in range(3):
        assert lr.read_ranked_identity(_FakeLcu(None)) is None
    assert _warnings(caplog) == []
