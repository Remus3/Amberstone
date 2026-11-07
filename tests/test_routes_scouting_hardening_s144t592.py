"""S144-T-592: POST /api/scouting never echoes, fetches or caches a junk
puuid, never shapes a junk League-V4 field into a rank, and never loses the
whole roster (or emits invalid JSON) on a bad opening-tendency result.

dashboard/routes_scouting.py is a POST route a LAN peer can reach (it is not
a control endpoint). Before this pass:

* _extract_puuids accepted ANY non-blank string: a 129+ char value, a value
  carrying "/", "?", a space or a newline was sent to the Riot API (one real
  rate-limited call each), echoed back in the response and keyed into both
  the route's rank cache and core.riot_api's; it also walked the WHOLE raw
  list after the 10-player cap was already met.
* _shape_rank stringified whatever it found: a dict / list / markup tier
  became a "ranked" row whose tier and display were that text; a bool
  wins / lp read 1, a negative or fractional count passed through (a
  negative win rate), a numeric string count was coerced, a non-str
  queueType was str()-ed, and a non-list entries value was shaped (and
  CACHED) as "Unranked".
* _attach_opening called .get on whatever opening_tendencies returned, so a
  non-dict result raised outside its guard and the request became a 500
  with every rank lost; a NaN inside one player's metrics went into the body
  as a bare NaN token, which JSON.parse refuses, so the whole panel failed.
* the rank cache and elapsed_ms used the wall clock, so a clock stepped
  back served a cached row past its TTL and reported a negative elapsed_ms;
  a cache entry dated in the future read as fresh.
* every failure log line carried the raw exception text.

All tests mock core.riot_api and core.opening_tendency; none reaches Riot.
"""
from __future__ import annotations

import json
import logging
import math
from unittest import mock

import pytest

import dashboard.routes_scouting as rs


class _RawHandler:
    """Captures the raw bytes a route sends and parses them STRICTLY."""

    def __init__(self):
        self.path = "/api/scouting"
        self.code = None
        self.raw = b""

    def _send(self, code, body, ctype, cache_control=None):
        self.code = code
        self.raw = body

    def payload(self):
        def _refuse(tok):
            raise ValueError("non-standard JSON constant " + tok)
        return json.loads(self.raw.decode("utf-8"), parse_constant=_refuse)


def _post(body):
    h = _RawHandler()
    rs._serve_scouting(h, body)
    return h


def _entry(**overrides):
    entry = {"queueType": "RANKED_SOLO_5x5", "tier": "DIAMOND",
             "rank": "IV", "leaguePoints": 12, "wins": 40, "losses": 35}
    entry.update(overrides)
    return [entry]


def setup_function(_fn):
    rs._reset_cache_for_tests()


def _run(body, fetch, opening=None):
    """POST ``body`` with get_summoner_rank -> ``fetch`` (a callable)."""
    if opening is None:
        def opening(puuids, **_kw):
            return {p: None for p in puuids}
    with mock.patch.object(rs.riot_api, "is_configured", return_value=True), \
         mock.patch.object(rs.riot_api, "get_summoner_rank",
                           side_effect=fetch) as fetched, \
         mock.patch.object(rs.opening_tendency, "opening_tendencies",
                           side_effect=opening):
        h = _post(body)
    return h, fetched


# -- puuid validation at the trust boundary -------------------------------

_BAD_PUUIDS = [
    "a" * 129,              # longer than any Riot puuid (78 chars)
    "x/y",                  # path separator
    "x?y=1",                # query
    "x#frag",
    "with space",
    "line\nbreak",
    "tab\tchar",
    "caf\u00e9",            # non-ASCII
    "..",
    "%2F",
]


@pytest.mark.parametrize("bad", _BAD_PUUIDS)
def test_junk_puuid_is_never_fetched_echoed_or_cached(bad):
    h, fetched = _run({"puuids": ["ok-1", bad, "ok_2"]},
                      lambda p, region="na1": _entry())
    assert h.code == 200
    asked = [c.args[0] for c in fetched.call_args_list]
    assert asked == ["ok-1", "ok_2"]
    assert [p["puuid"] for p in h.payload()["players"]] == ["ok-1", "ok_2"]
    assert rs._cache_get(bad, rs.time.monotonic()) is None


def test_max_length_puuid_is_accepted():
    p = "A" * 128
    h, fetched = _run({"puuids": [p]}, lambda q, region="na1": _entry())
    assert [c.args[0] for c in fetched.call_args_list] == [p]
    assert h.payload()["players"][0]["ranked"] is True


def test_surrounding_whitespace_is_still_stripped():
    h, fetched = _run({"puuids": ["  ok-1 \n"]},
                      lambda q, region="na1": _entry())
    assert [c.args[0] for c in fetched.call_args_list] == ["ok-1"]


class _Boom(str):
    """A str whose strip() raises: proves the walk stopped before it."""

    def strip(self, *a):  # noqa: D401
        raise RuntimeError("walked past the cap")


def test_extract_stops_once_the_cap_is_known():
    raw = [f"p{i}" for i in range(rs._MAX_FANOUT + 1)] + [_Boom("late")]
    h, _ = _run({"puuids": raw}, lambda q, region="na1": None)
    assert h.code == 200
    body = h.payload()
    assert body["capped"] is True
    assert len(body["players"]) == rs._MAX_FANOUT


def test_exactly_the_cap_is_not_capped():
    raw = [f"p{i}" for i in range(rs._MAX_FANOUT)] + ["p0", "", 7, "x/y"]
    h, _ = _run({"puuids": raw}, lambda q, region="na1": None)
    body = h.payload()
    assert body["capped"] is False
    assert len(body["players"]) == rs._MAX_FANOUT


# -- League-V4 field validation -------------------------------------------

_BAD_FIELDS = [
    {"tier": {"name": "GOLD"}},
    {"tier": ["GOLD"]},
    {"tier": 7},
    {"tier": True},
    {"rank": False},
    {"tier": "<b>GOLD</b>"},
    {"tier": "GOLD IV"},
    {"rank": {"r": "IV"}},
    {"rank": "IV<script>"},
    {"rank": 4},
    {"leaguePoints": True},
    {"leaguePoints": "12"},
    {"leaguePoints": -5},
    {"leaguePoints": 12.5},
    {"leaguePoints": float("nan")},
    {"leaguePoints": float("inf")},
    {"leaguePoints": 10 ** 400},
    {"wins": True},
    {"wins": -3},
    {"wins": 3.5},
    {"wins": "40"},
    {"wins": 10 ** 20},
    {"losses": False},
    {"losses": -1},
    {"losses": float("nan")},
]


@pytest.mark.parametrize("bad", _BAD_FIELDS, ids=lambda d: repr(d)[:40])
def test_junk_rank_field_fails_that_player_soft_and_is_not_cached(bad):
    calls = []

    def fetch(p, region="na1"):
        calls.append(p)
        return _entry(**bad) if p == "bad" else _entry()

    h, _ = _run({"puuids": ["good", "bad"]}, fetch)
    assert h.code == 200
    by = {p["puuid"]: p for p in h.payload()["players"]}
    assert by["good"]["ranked"] is True
    assert by["good"]["display"] == "DIAMOND IV 12 LP"
    assert by["bad"]["ranked"] is False
    assert by["bad"].get("error") is True
    assert by["bad"]["tier"] is None
    assert by["bad"]["display"] == "Unranked"
    # Not cached: the next poll asks Riot again.
    _run({"puuids": ["bad"]}, fetch)
    assert calls.count("bad") == 2


def test_non_str_queue_type_reads_as_absent_not_as_text():
    h, _ = _run({"puuids": ["a"]},
                lambda p, region="na1": _entry(queueType=["RANKED_SOLO_5x5"]))
    row = h.payload()["players"][0]
    # A non-str queueType is not the solo entry, but the only entry still
    # has a valid tier, so the fallback picks it; queue reads absent.
    assert row["ranked"] is True
    assert row["queue"] is None


def test_junk_queue_text_reads_as_absent():
    h, _ = _run({"puuids": ["a"]},
                lambda p, region="na1": _entry(queueType="SOLO <b>"))
    row = h.payload()["players"][0]
    assert row["ranked"] is True
    assert row["queue"] is None


@pytest.mark.parametrize("entries", [{"tier": "GOLD"}, "GOLD", 7, True])
def test_non_list_entries_is_an_error_not_a_cached_unranked(entries):
    calls = []

    def fetch(p, region="na1"):
        calls.append(p)
        return entries

    h, _ = _run({"puuids": ["a"]}, fetch)
    row = h.payload()["players"][0]
    assert row["ranked"] is False
    assert row.get("error") is True
    _run({"puuids": ["a"]}, fetch)
    assert len(calls) == 2


def test_valid_float_counts_and_absent_fields_keep_their_meaning():
    h, _ = _run({"puuids": ["a", "b"]},
                lambda p, region="na1": (
                    _entry(wins=40.0, losses=35.0, leaguePoints=12.0)
                    if p == "a" else
                    [{"queueType": "RANKED_SOLO_5x5", "tier": "MASTER"}]))
    by = {p["puuid"]: p for p in h.payload()["players"]}
    assert by["a"]["wins"] == 40 and isinstance(by["a"]["wins"], int)
    assert by["a"]["lp"] == 12 and by["a"]["display"] == "DIAMOND IV 12 LP"
    assert by["a"]["win_rate_pct"] == 53
    # Absent rank / lp / counts: unchanged from before this pass.
    assert by["b"]["ranked"] is True
    assert by["b"]["division"] is None
    assert by["b"]["lp"] == 0
    assert by["b"]["wins"] == 0 and by["b"]["losses"] == 0
    assert by["b"]["win_rate_pct"] is None
    assert by["b"]["display"] == "MASTER"


# -- opening-tendency attachment ------------------------------------------

@pytest.mark.parametrize("ret", [None, [], "x", 7])
def test_non_dict_opening_result_keeps_every_rank(ret):
    h, _ = _run({"puuids": ["a", "b"]}, lambda p, region="na1": _entry(),
                opening=lambda puuids, **_kw: ret)
    assert h.code == 200
    body = h.payload()
    assert body["ok"] is True
    assert [p["ranked"] for p in body["players"]] == [True, True]
    assert all(p["opening"] is None for p in body["players"])


def test_non_finite_opening_metric_never_reaches_the_body():
    def opening(puuids, **_kw):
        return {"a": {"games": 3, "rate": float("nan")},
                "b": {"games": 4, "rate": 0.5}}

    h, _ = _run({"puuids": ["a", "b"]}, lambda p, region="na1": _entry(),
                opening=opening)
    body = h.payload()          # strict parse: a bare NaN token raises
    by = {p["puuid"]: p for p in body["players"]}
    assert by["a"]["opening"] is None
    assert by["b"]["opening"] == {"games": 4, "rate": 0.5}


def test_non_dict_opening_value_reads_none():
    h, _ = _run({"puuids": ["a", "b"]}, lambda p, region="na1": _entry(),
                opening=lambda puuids, **_kw: {"a": "junk", "b": [1]})
    assert all(p["opening"] is None for p in h.payload()["players"])


# -- clocks ---------------------------------------------------------------

def test_cache_entry_from_the_future_is_a_miss():
    rs._cache_put("a", 1000.0, rs._unranked("a"))
    assert rs._cache_get("a", 1000.0) is not None
    assert rs._cache_get("a", 500.0) is None


@pytest.mark.parametrize("bad_now", [float("nan"), float("inf"), None, True])
def test_cache_refuses_a_non_finite_clock(bad_now):
    rs._cache_put("a", bad_now, rs._unranked("a"))
    assert "a" not in rs._CACHE
    assert rs._cache_get("a", 1000.0) is None
    rs._cache_put("a", 1000.0, rs._unranked("a"))
    assert rs._cache_get("a", bad_now) is None


def test_wall_clock_step_back_does_not_affect_the_route():
    seq = iter([1_000_000.0, 990_000.0, 980_000.0, 970_000.0] * 50)
    with mock.patch.object(rs.time, "time", side_effect=lambda: next(seq)):
        h, _ = _run({"puuids": ["a"]}, lambda p, region="na1": _entry())
    assert 0 <= h.payload()["elapsed_ms"] < 60_000


def test_the_route_never_reads_the_wall_clock():
    def _no_wall_clock():
        raise AssertionError("wall clock read")

    with mock.patch.object(rs.time, "time", side_effect=_no_wall_clock):
        h, _ = _run({"puuids": ["a"]}, lambda p, region="na1": _entry())
        h2, _ = _run({"puuids": ["a"]}, lambda p, region="na1": _entry())
    assert h.code == 200 and h2.code == 200
    assert h2.payload()["players"][0]["cached"] is True


# -- logging --------------------------------------------------------------

def test_failure_logs_name_the_type_never_the_text(caplog):
    secret = "SECRETTEXT\nFAKE LOG LINE"

    def fetch(p, region="na1"):
        raise RuntimeError(secret)

    def opening(puuids, **_kw):
        raise OSError(secret)

    with caplog.at_level(logging.DEBUG, logger="rc.web_dashboard"):
        h, _ = _run({"puuids": ["a"]}, fetch, opening=opening)
    assert h.code == 200
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRETTEXT" not in text
    assert "RuntimeError" in text and "OSError" in text


def test_outer_failure_logs_type_only_and_sends_generic_500(caplog):
    secret = "SECRETTEXT-outer"  # rc-credential-scan: allow-fixture
    with caplog.at_level(logging.DEBUG, logger="rc.web_dashboard"), \
         mock.patch.object(rs.riot_api, "is_configured",
                           side_effect=ValueError(secret)):
        h = _post({"puuids": ["a"]})
    assert h.code == 500
    assert "SECRETTEXT" not in h.raw.decode("utf-8")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRETTEXT" not in text and "ValueError" in text


def test_valid_body_is_strict_json():
    h, _ = _run({"puuids": ["a"]}, lambda p, region="na1": _entry())
    body = h.payload()
    assert body["ok"] is True
    assert not any(isinstance(v, float) and not math.isfinite(v)
                   for v in body["players"][0].values())


def test_padded_tier_no_longer_leaks_padding_into_display():
    # Before: display " GOLD  I 0 LP" (format_rank_entry was handed the raw,
    # unstripped entry while the tier field itself was stripped).
    h, _ = _run({"puuids": ["a"]},
                lambda p, region="na1": _entry(tier=" Gold ", rank=" i ",
                                               leaguePoints=0))
    row = h.payload()["players"][0]
    assert row["tier"] == "GOLD"
    assert row["display"] == "GOLD I 0 LP"


def test_a_non_finite_value_that_slips_through_is_a_500_not_bad_json():
    def _poison(players, puuids):
        for row in players:
            row["opening"] = {"rate": float("inf")}

    with mock.patch.object(rs, "_attach_opening", side_effect=_poison):
        h, _ = _run({"puuids": ["a"]}, lambda p, region="na1": _entry())
    assert h.code == 500
    assert h.payload()["ok"] is False
