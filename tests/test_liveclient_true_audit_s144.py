"""s144 true-audit regressions for ``dashboard/_liveclient.py``.

``liveclient_summary`` turns the foreign Live Client ``:2999`` frame (via the
vision relay cache) into the ``liveclient`` block of ``/api/state``;
``lcu_summary`` reads the agent-posted LCU snapshot off the ``:8889`` relay.
Every finding below had RED tests on the pre-fix module; the valid-input
pins (``*_unchanged`` / ``*_canonical``, the bool / str / None time cases, the
"-inf" ts case and the non-dict envelope case) are characterization and passed
before the fix too:

  L1  a NaN / inf EventTime was emitted as ``down_at_s: nan`` (``/api/state``
      is ``json.dumps`` with the default ``allow_nan=True``, so the body
      carried a bare ``NaN`` token the browser's ``JSON.parse`` rejects), and
      a long-int EventTime raised OverflowError in ``float()``, dropping EVERY
      event of that kind.
  L2  one objective event with an unhashable KillerName, or one roster row
      with an unhashable championName, nulled ``objective_events`` (None =
      "no event data") for every take in the game.
  L3  a junk itemID became an id string: ``"None"``, ``"True"``, ``"3031.0"``,
      ``"-7"``, ``"{'a': 1}"`` (and ``""`` in the per-team pools).
  L4  a junk gameId became the per-game dedup token: True -> "True", 1.5 ->
      "1.5", -5 -> "-5", a dict -> its repr.
  L5  ``kda`` interpolated raw scoreboard values ("None/{'a': 1}/1e+308"), and
      a negative score drove kill participation to "200%".
  L6  a negative or huge gameTime rendered "-1:55" or a 30-digit clock; a
      level of 1e300 was forwarded as a 301-digit int.
  L7  a non-str championName / displayName / gameMode / structure name was
      forwarded as-is (a list champion or a None displayName also lost the
      whole ``sr_items`` build view through an AttributeError).
  L8  ``lcu_summary`` read a NaN / inf / far-future ``ts`` as fresh forever
      and returned a non-dict ``data`` (list / str) against its dict contract.
"""
from __future__ import annotations

import io
import json
import time
from unittest import mock

import pytest

from core.liveclient_cache import Snapshot
from dashboard import _liveclient


def _player(name, team, **kw):
    p = {"summonerName": name, "championName": name, "team": team,
         "items": [], "scores": {"kills": 1, "deaths": 0, "assists": 0,
                                 "creepScore": 0}}
    p.update(kw)
    return p


def _frame(events=None, game_time=600.0, players=None, gd_extra=None,
           ap_extra=None):
    gd = {"gameTime": game_time, "gameMode": "CLASSIC"}
    gd.update(gd_extra or {})
    ap = {"summonerName": "Me", "level": 5, "currentGold": 100,
          "championStats": {}}
    ap.update(ap_extra or {})
    return {
        "activePlayer": ap,
        "allPlayers": players if players is not None
        else [_player("Me", "ORDER"), _player("Foe", "CHAOS")],
        "events": {"Events": events or []},
        "gameData": gd,
    }


def _summary(frame):
    snap = Snapshot(data=frame, ts=time.time())
    with mock.patch("core.liveclient_cache.get", return_value=snap):
        return _liveclient.liveclient_summary()


# ---------------------------------------------------------------- L1 times

_BAD_TIMES = [float("nan"), float("inf"), -float("inf"), 10 ** 400, -1.0,
              1e300, True, "12", None]
_BAD_TIME_IDS = ["nan", "inf", "-inf", "long-int", "negative", "huge",
                 "bool", "str", "none"]


def _events_of(kind, t, extra=None):
    ev = {"EventName": kind, "EventTime": t}
    ev.update(extra or {})
    return ev


@pytest.mark.parametrize("t", _BAD_TIMES, ids=_BAD_TIME_IDS)
def test_l1_bad_event_time_skips_only_that_event(t):
    events = [
        _events_of("InhibKilled", t, {"InhibKilled": "Barracks_T2_L1"}),
        _events_of("InhibKilled", 50.0, {"InhibKilled": "Barracks_T2_C1"}),
        _events_of("TurretKilled", t, {"TurretKilled": "Turret_T2_L_03_A"}),
        _events_of("TurretKilled", 40.0, {"TurretKilled": "Turret_T2_C_05_A"}),
        _events_of("MinionsSpawning", t),
        _events_of("MinionsSpawning", 65.0, {"EventID": 3}),
        _events_of("DragonKill", t, {"KillerName": "Foe"}),
        _events_of("BaronKill", 1300.0, {"KillerName": "Foe"}),
    ]
    out = _summary(_frame(events=events))
    assert out["inhib_events"] == [{"down_at_s": 50.0,
                                    "name": "Barracks_T2_C1"}]
    assert out["turret_events"] == [{"down_at_s": 40.0,
                                     "name": "Turret_T2_C_05_A"}]
    assert out["minion_events"] == [{"at_s": 65.0}]
    assert out["minion_spawn_events"] == [{"spawn_at_s": 65.0,
                                           "event_id": 3}]
    assert out["objective_events"] == [{"name": "baron",
                                        "killer_team": "enemy",
                                        "down_at_s": 1300.0,
                                        "stolen": False}]


def test_l1_summary_is_strict_json_on_non_finite_times():
    events = [_events_of(k, float("nan"), {"KillerName": "Foe"})
              for k in ("InhibKilled", "TurretKilled", "MinionsSpawning",
                        "DragonKill")]
    out = _summary(_frame(events=events))
    json.dumps(out, allow_nan=False)


def test_l1_valid_int_and_float_times_unchanged():
    events = [_events_of("TurretKilled", 0, {"TurretKilled": "A"}),
              _events_of("TurretKilled", 812.25, {"TurretKilled": "B"})]
    out = _summary(_frame(events=events))
    assert out["turret_events"] == [{"down_at_s": 0.0, "name": "A"},
                                    {"down_at_s": 812.25, "name": "B"}]


# ---------------------------------------------------------- L2 objectives

def test_l2_unhashable_killer_skips_nothing_else():
    events = [_events_of("DragonKill", 5.0, {"KillerName": ["x"]}),
              _events_of("BaronKill", 9.0, {"KillerName": "Foe"})]
    out = _summary(_frame(events=events))
    assert out["objective_events"] == [
        {"name": "dragon", "killer_team": "unknown", "down_at_s": 5.0,
         "stolen": False},
        {"name": "baron", "killer_team": "enemy", "down_at_s": 9.0,
         "stolen": False},
    ]


def test_l2_unhashable_roster_champion_keeps_objectives():
    players = [_player("Me", "ORDER"), _player("Foe", "CHAOS"),
               _player("Odd", "CHAOS", championName={"a": 1})]
    events = [_events_of("BaronKill", 9.0, {"KillerName": "Foe"})]
    out = _summary(_frame(events=events, players=players))
    assert out["objective_events"] == [
        {"name": "baron", "killer_team": "enemy", "down_at_s": 9.0,
         "stolen": False}]
    assert out["enemy_team"] == ["Foe", ""]


def test_l2_unhashable_event_name_skips_nothing_else():
    events = [{"EventName": ["DragonKill"], "EventTime": 5.0},
              _events_of("BaronKill", 9.0, {"KillerName": "Foe"})]
    out = _summary(_frame(events=events))
    assert out["objective_events"] == [
        {"name": "baron", "killer_team": "enemy", "down_at_s": 9.0,
         "stolen": False}]


def test_l2_raising_stolen_coercion_skips_only_that_event():
    events = [_events_of("BaronKill", 9.0, {"KillerName": "Foe"}),
              _events_of("DragonKill", 5.0, {"KillerName": "Foe"})]
    real = _liveclient.as_bool
    calls = {"n": 0}

    def flaky(v, default):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real(v, default)

    with mock.patch.object(_liveclient, "as_bool", flaky):
        out = _summary(_frame(events=events))
    assert out["objective_events"] == [
        {"name": "dragon", "killer_team": "enemy", "down_at_s": 5.0,
         "stolen": False}]


# ------------------------------------------------------------- L3 item ids

_JUNK_ITEMS = [{"itemID": None, "displayName": "A"},
               {"itemID": True, "displayName": "B"},
               {"itemID": 3031.0, "displayName": "C"},
               {"itemID": -7, "displayName": "D"},
               {"itemID": {"a": 1}, "displayName": "E"},
               {"itemID": "30 31", "displayName": "F"},
               {"itemID": "".join(map(chr, (0x663, 0x660, 0x663, 0x661))),
                "displayName": "G"},
               {"displayName": "H"},
               {"itemID": 0, "displayName": "I"},
               {"itemID": 2 ** 40, "displayName": "J"}]


def test_l3_junk_item_ids_never_become_ids():
    players = [_player("Me", "ORDER", items=list(_JUNK_ITEMS)),
               _player("Foe", "CHAOS", items=list(_JUNK_ITEMS)),
               _player("Al", "ORDER", items=list(_JUNK_ITEMS))]
    out = _summary(_frame(players=players))
    assert out["owned_item_ids"] == []
    assert out["enemy_item_ids"] == []
    assert out["ally_item_ids"] == []
    assert [it["itemID"] for it in out["allPlayers"][0]["items"]] == \
        [None] * len(_JUNK_ITEMS)


@pytest.mark.parametrize("field", ["itemID", "count"])
@pytest.mark.parametrize("bad", [float("inf"), -float("inf")],
                         ids=["inf", "-inf"])
def test_l3_inf_item_field_never_blanks_the_summary(field, bad):
    # core/ward_cue.py _coerce_int caught TypeError / ValueError only, so
    # int(inf) raised OverflowError out of compute_ward_cue and the outer
    # except returned {} for the whole summary.
    item = {"itemID": 2055, "count": 2, "slot": 0}
    item[field] = bad
    players = [_player("Me", "ORDER", championName="Jinx",
                       items=[item, {"itemID": 3340, "canUse": True}]),
               _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert out["game_time_s"] == 600
    assert out["ward_cue"]["trinket_ready"] is True
    assert out["ward_cue"]["control_ward"] is False


def test_l3_valid_item_ids_unchanged():
    items = [{"itemID": 3031, "displayName": "Infinity Edge", "slot": 0},
             {"itemID": "3006", "displayName": "Berserker's Greaves",
              "slot": 1},
             {"itemID": 3340, "displayName": "Stealth Ward", "slot": 6}]
    players = [_player("Me", "ORDER", items=items),
               _player("Foe", "CHAOS", items=[{"itemID": 3075}])]
    out = _summary(_frame(players=players))
    assert out["owned_item_ids"] == ["3031", "3006"]
    assert out["ally_item_ids"] == ["3031", "3006", "3340"]
    assert out["enemy_item_ids"] == ["3075"]
    assert out["allPlayers"][0]["items"] == [
        {"itemID": 3031, "slot": 0}, {"itemID": 3006, "slot": 1},
        {"itemID": 3340, "slot": 6}]


# ------------------------------------------------------------- L4 game id

@pytest.mark.parametrize("gid", [True, 1.5, -5, {"a": 1}, [1], "abc",
                                 "1.5", "-5", "+5", "1e9", 2 ** 63,
                                 chr(0x661) + chr(0x662)],
                         ids=["bool", "float", "negative", "dict", "list",
                              "word", "float-str", "neg-str", "plus-str",
                              "exp-str", "over-int64", "arabic-digits"])
def test_l4_junk_game_id_is_absent(gid):
    out = _summary(_frame(gd_extra={"gameId": gid}))
    assert out["game_id"] == ""


@pytest.mark.parametrize("gid,expect", [(123456789, "123456789"),
                                        ("987654321", "987654321"),
                                        (" 42 ", "42"), ("00012", "12"),
                                        (0, ""), ("", ""), (None, "")])
def test_l4_valid_game_id_canonical(gid, expect):
    out = _summary(_frame(gd_extra={"gameId": gid}))
    assert out["game_id"] == expect


def test_l4_game_id_fallback_key_still_read():
    out = _summary(_frame(gd_extra={"gameID": 777}))
    assert out["game_id"] == "777"
    out = _summary(_frame(gd_extra={"gameId": True, "gameID": 778}))
    assert out["game_id"] == "778"
    out = _summary(_frame(gd_extra={"gameId": 5, "gameID": 778}))
    assert out["game_id"] == "5"


# ------------------------------------------------------------ L5 kda / kp

def test_l5_kda_never_interpolates_junk():
    players = [_player("Me", "ORDER",
                       scores={"kills": None, "deaths": {"a": 1},
                               "assists": 1e308, "creepScore": 0}),
               _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert out["kda"] == "0/0/0"


def test_l5_kda_valid_values_unchanged():
    players = [_player("Me", "ORDER",
                       scores={"kills": 3, "deaths": 2.0, "assists": "5",
                               "creepScore": 0}),
               _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert out["kda"] == "3/2/5"


def test_l5_negative_scores_never_inflate_kp():
    players = [_player("Me", "ORDER",
                       scores={"kills": 5, "deaths": 0, "assists": -3,
                               "creepScore": 0}),
               _player("Al", "ORDER", scores={"kills": -4, "assists": 0}),
               _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert out["kda"] == "5/0/0"
    assert out["kill_participation_pct"] == "100%"


# ----------------------------------------------------------- L6 clock/level

@pytest.mark.parametrize("gt", [-5, -0.5, 1e308, 10 ** 400, 1e6 + 1],
                         ids=["neg", "neg-frac", "huge", "long-int",
                              "over-bound"])
def test_l6_out_of_range_game_time_reads_zero(gt):
    out = _summary(_frame(game_time=gt))
    assert (out["game_time_s"], out["game_time"]) == (0, "0:00")


@pytest.mark.parametrize("gt,expect", [(0, "0:00"), (65.9, "1:05"),
                                       (3600, "60:00"), (1e6, "16666:40")])
def test_l6_in_range_game_time_unchanged(gt, expect):
    assert _summary(_frame(game_time=gt))["game_time"] == expect


@pytest.mark.parametrize("lvl", [0, -3, 101, 1e300, 10 ** 400],
                         ids=["zero", "neg", "over", "huge", "long-int"])
def test_l6_out_of_range_level_is_none(lvl):
    assert _summary(_frame(ap_extra={"level": lvl}))["level"] is None


# --------------------------------------------------------- L7 str fields

def test_l7_non_str_champion_is_none_and_build_view_survives_junk_name():
    players = [_player("Me", "ORDER", championName=["x"]),
               _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert out["champion"] is None
    assert out["allPlayers"][0]["championName"] == ""
    assert out["ally_team"] == [""]


def test_l7_non_str_display_name_is_blank_and_sr_items_still_built():
    items = [{"itemID": 1055, "displayName": None},
             {"itemID": 3006, "displayName": 5},
             {"itemID": 1036, "displayName": "Long Sword"}]
    players = [_player("Me", "ORDER", championName="Jinx", items=items),
               _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert out["owned_items"] == ["", "", "Long Sword"]
    assert "sr_items" in out
    assert {"name": "Long Sword", "owned": True, "next": False} in \
        out["sr_items"]


def test_l7_non_str_mode_and_structure_names():
    events = [_events_of("InhibKilled", 5.0, {"InhibKilled": {"a": 1}}),
              _events_of("TurretKilled", 6.0, {"TurretKilled": 12})]
    out = _summary(_frame(events=events, gd_extra={"gameMode": ["x"]}))
    assert out["game_mode"] is None
    assert out["inhib_events"] == [{"down_at_s": 5.0, "name": None}]
    assert out["turret_events"] == [{"down_at_s": 6.0, "name": None}]


def test_l7_non_str_identity_fields_in_lean_roster():
    me = _player("Me", "ORDER", riotIdGameName=7, rawChampionName=None)
    me["team"] = ["T"]
    players = [me, _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players,
                          ap_extra={"riotIdGameName": {"a": 1}}))
    row = out["allPlayers"][0]
    assert (row["riotIdGameName"], row["team"], row["rawChampionName"]) == \
        ("", "", "")
    assert out["activePlayer"]["riotIdGameName"] == ""
    json.dumps(out, allow_nan=False)


def test_l7_non_str_active_player_summoner_name_is_blank():
    # The activePlayer identity is "" (its missing default) for a non-str
    # summonerName, never a raw list handed to active_match.js.
    out = _summary(_frame(ap_extra={"summonerName": ["Me"]}))
    assert out["activePlayer"]["summonerName"] == ""
    assert _summary(_frame())["activePlayer"]["summonerName"] == "Me"


def test_l7_nan_in_every_passthrough_leaf_stays_strict_json():
    nan = float("nan")
    items = [{"itemID": nan, "displayName": nan, "slot": nan, "canUse": nan,
              "count": nan}]
    players = [
        {"summonerName": "Me", "riotIdGameName": nan, "championName": nan,
         "rawChampionName": nan, "team": "ORDER", "position": nan,
         "level": nan, "items": items,
         "scores": {"kills": nan, "deaths": nan, "assists": nan,
                    "creepScore": nan}},
        {"summonerName": "Foe", "championName": "Foe", "team": "CHAOS",
         "position": nan, "items": items, "scores": {"kills": nan}},
    ]
    events = [{"EventName": k, "EventTime": 5.0, "EventID": nan,
               "KillerName": nan, "DragonType": nan, "Stolen": nan,
               "InhibKilled": nan, "TurretKilled": nan}
              for k in ("InhibKilled", "TurretKilled", "MinionsSpawning",
                        "DragonKill")]
    frame = _frame(events=events, players=players,
                   gd_extra={"gameMode": nan, "gameId": nan},
                   ap_extra={"riotIdGameName": nan, "level": nan,
                             "championStats": {"resourceType": nan,
                                               "currentHealth": nan}})
    out = _summary(frame)
    assert out["game_time_s"] == 600
    json.dumps(out, allow_nan=False)


def test_l7_lean_roster_slot_valid_kept_junk_none():
    items = [{"itemID": 3031, "slot": 0}, {"itemID": 3006, "slot": 5},
             {"itemID": 1055}, {"itemID": 1036, "slot": True},
             {"itemID": 1037, "slot": -1}, {"itemID": 1038, "slot": 100},
             {"itemID": 1039, "slot": 10 ** 6}, {"itemID": 1040, "slot": "2"}]
    players = [_player("Me", "ORDER", items=items), _player("Foe", "CHAOS")]
    out = _summary(_frame(players=players))
    assert [it["slot"] for it in out["allPlayers"][0]["items"]] == \
        [0, 5, None, None, None, None, None, None]


def test_l7_non_str_team_and_summoner_name_on_other_rows():
    odd = _player("Odd", "CHAOS")
    odd["summonerName"] = 5
    odd["team"] = ["CHAOS"]
    players = [_player("Me", "ORDER"), _player("Foe", "CHAOS"), odd]
    out = _summary(_frame(players=players))
    assert out["allPlayers"][2]["summonerName"] == ""
    assert out["allPlayers"][2]["team"] == ""
    assert [p["team"] for p in out["players"]] == ["ORDER", "CHAOS", ""]


# ------------------------------------------------------------ L8 lcu_summary

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _lcu(body):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    with mock.patch("urllib.request.urlopen", return_value=_Resp(raw)):
        return _liveclient.lcu_summary()


@pytest.mark.parametrize("raw", [b'{"ts": NaN, "data": {"phase": "x"}}',
                                 b'{"ts": Infinity, "data": {"phase": "x"}}',
                                 b'{"ts": -Infinity, "data": {"phase": "x"}}'],
                         ids=["nan", "inf", "-inf"])
def test_l8_non_finite_ts_is_stale(raw):
    assert _lcu(raw) == {}


def test_l8_far_future_ts_is_stale():
    assert _lcu({"ts": time.time() + 3600, "data": {"phase": "x"}}) == {}


@pytest.mark.parametrize("data", [[1, 2], "abc", 5, True],
                         ids=["list", "str", "int", "bool"])
def test_l8_non_dict_data_is_empty(data):
    assert _lcu({"ts": time.time(), "data": data}) == {}


@pytest.mark.parametrize("raw", [b"[1, 2]", b'"no error here"', b"5",
                                 b"null"],
                         ids=["list", "str", "int", "null"])
def test_l8_non_dict_envelope_is_empty(raw):
    # Characterization: the isinstance(wrap, dict) guard is defensive - the
    # outer except already turned these into {} - so this pins the contract,
    # it does not discriminate the guard (an equivalent mutant).
    assert _lcu(raw) == {}


def test_l8_fresh_dict_snapshot_unchanged():
    now = time.time()
    assert _lcu({"ts": now, "data": {"phase": "InProgress"}}) == \
        {"phase": "InProgress"}
    assert _lcu({"ts": int(now) - 2, "data": {"phase": "Lobby"}}) == \
        {"phase": "Lobby"}
    assert _lcu({"ts": now - 6, "data": {"phase": "x"}}) == {}
    assert _lcu({"ts": now, "error": "down"}) == {}
    assert _lcu({"ts": now}) == {}
