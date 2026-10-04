"""RM-604 / X-04 (external reference F, clean-room): pure live event deriver.

derive_events(prev, cur) over consecutive normalized Live Client snapshots
(the liveclient_cache payload that /api/state and the RM-605 recorder read).
Contract pinned here:
  - first knowledge is state: prev None (or cur None) -> no events;
  - a None reading never transitions anything (field-level and row-level);
  - death/respawn keyed by championName; level_up; item_completed (completed
    ids only); objective_taken incl. voidgrub (HordeKill) and the RM-601
    stolen flag; skill_point is a RESERVED kind name and is never emitted.
All fixtures are synthetic (no real Riot IDs).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import live_event_deriver as led  # noqa: E402

LEG = frozenset({"3031", "6655"})  # synthetic completed-id set for tests


def _p(champ, team="ORDER", dead=False, level=1, items=(), name=None, respawn=0.0):
    return {
        "championName": champ,
        "summonerName": name or f"Synth{champ}#T1",
        "team": team,
        "isDead": dead,
        "respawnTimer": respawn,
        "level": level,
        "items": [{"itemID": i, "slot": n} for n, i in enumerate(items)],
    }


def _snap(t, players, events=None):
    return {
        "activePlayer": {"summonerName": "SynthLux#T1"},
        "allPlayers": players,
        "gameData": {"gameMode": "CLASSIC", "gameTime": t},
        "events": {"Events": list(events or [])},
    }


def _ev(eid, name, t, killer="SynthLux#T1", **kw):
    d = {"EventID": eid, "EventName": name, "EventTime": t, "KillerName": killer}
    d.update(kw)
    return d


def _base(t=100.0, **kw):
    lux = _p("Lux", level=kw.get("lux_level", 3), dead=kw.get("lux_dead", False),
             items=kw.get("lux_items", ()), name="SynthLux#T1",
             respawn=kw.get("lux_respawn", 0.0))
    zed = _p("Zed", team="CHAOS", level=4, dead=kw.get("zed_dead", False))
    return _snap(t, [lux, zed], kw.get("events"))


def _kinds(evs):
    return [e["kind"] for e in evs]


# -- first knowledge is state ---------------------------------------------

def test_first_snapshot_emits_nothing():
    cur = _base(lux_dead=True, lux_level=6, lux_items=(3031,),
                events=[_ev(1, "DragonKill", 90.0, DragonType="Fire")])
    assert led.derive_events(None, cur, completed_ids=LEG) == []


def test_cur_none_emits_nothing():
    assert led.derive_events(_base(), None, completed_ids=LEG) == []


def test_non_dict_rows_emit_nothing():
    assert led.derive_events("x", _base(), completed_ids=LEG) == []
    assert led.derive_events(_base(), 5, completed_ids=LEG) == []


# -- death / respawn ------------------------------------------------------

def test_death_and_respawn_keyed_by_champion():
    a = _base(100.0)
    b = _base(101.0, zed_dead=True)
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert _kinds(evs) == ["death"]
    assert evs[0]["champion"] == "Zed"
    assert evs[0]["team"] == "CHAOS"
    assert evs[0]["active"] is False
    assert evs[0]["game_time"] == 101.0
    c = _base(130.0)
    evs2 = led.derive_events(b, c, completed_ids=LEG)
    assert _kinds(evs2) == ["respawn"]
    assert evs2[0]["champion"] == "Zed"


def test_active_player_flag_and_respawn_timer():
    a = _base(100.0)
    b = _base(101.0, lux_dead=True, lux_respawn=12.5)
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert evs == [{"kind": "death", "game_time": 101.0, "champion": "Lux",
                    "team": "ORDER", "active": True, "respawn_in_s": 12.5}]


def test_stolen_string_isdead_reads_through_coercion():
    a = _base(100.0)
    b = _base(101.0)
    b["allPlayers"][1]["isDead"] = "True"
    assert _kinds(led.derive_events(a, b, completed_ids=LEG)) == ["death"]


# -- None never transitions -----------------------------------------------

def test_none_field_never_transitions():
    a = _base(100.0)
    b = _base(101.0, zed_dead=True)
    b["allPlayers"][1]["isDead"] = None
    assert led.derive_events(a, b, completed_ids=LEG) == []
    # and None -> known is first knowledge, not a transition
    c = _base(102.0, zed_dead=True)
    assert led.derive_events(b, c, completed_ids=LEG) == []


def test_none_row_between_two_readings_never_transitions():
    a = _base(100.0)
    c = _base(102.0, zed_dead=True)
    assert led.derive_events(a, None, completed_ids=LEG) == []
    assert led.derive_events(None, c, completed_ids=LEG) == []


def test_junk_level_and_items_are_none_readings():
    a = _base(100.0)
    b = _base(101.0, lux_items=(3031,))
    b["allPlayers"][0]["level"] = True          # bool is not a level
    a["allPlayers"][0]["items"] = None          # no item reading
    assert led.derive_events(a, b, completed_ids=LEG) == []


def test_missing_player_in_cur_emits_nothing():
    a = _base(100.0)
    b = _base(101.0, zed_dead=True)
    b["allPlayers"] = b["allPlayers"][:1]
    assert led.derive_events(a, b, completed_ids=LEG) == []


def test_duplicate_champion_names_are_ambiguous_and_skipped():
    a = _snap(100.0, [_p("Lux"), _p("Lux", team="CHAOS", name="Other#T2")])
    b = _snap(101.0, [_p("Lux", dead=True), _p("Lux", team="CHAOS", name="Other#T2")])
    assert led.derive_events(a, b, completed_ids=LEG) == []


def test_backwards_game_time_is_a_new_first_snapshot():
    a = _base(1500.0)
    b = _base(10.0, zed_dead=True)
    assert led.derive_events(a, b, completed_ids=LEG) == []


# -- level / items --------------------------------------------------------

def test_level_up_from_to():
    a = _base(100.0, lux_level=5)
    b = _base(101.0, lux_level=7)
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert evs == [{"kind": "level_up", "game_time": 101.0, "champion": "Lux",
                    "team": "ORDER", "active": True, "from": 5, "to": 7}]


def test_item_completed_only_for_completed_ids():
    a = _base(100.0, lux_items=(1001,))
    b = _base(101.0, lux_items=(1001, 1052, 3031))   # 1052 is a component
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert _kinds(evs) == ["item_completed"]
    assert evs[0]["item_id"] == 3031
    assert evs[0]["champion"] == "Lux"


def test_second_copy_of_completed_item_emits_again():
    a = _base(100.0, lux_items=(3031,))
    b = _base(101.0, lux_items=(3031, 3031))
    assert _kinds(led.derive_events(a, b, completed_ids=LEG)) == ["item_completed"]


def test_unchanged_inventory_emits_nothing():
    a = _base(100.0, lux_items=(3031,))
    b = _base(101.0, lux_items=(3031,))
    assert led.derive_events(a, b, completed_ids=LEG) == []


def test_completed_ids_default_is_fail_soft(monkeypatch):
    def boom():
        raise RuntimeError("no catalog")
    monkeypatch.setattr(led, "_load_completed_ids", boom)
    a = _base(100.0)
    b = _base(101.0, lux_items=(3031,), zed_dead=True)
    # no catalog -> no item events, other kinds unaffected
    assert _kinds(led.derive_events(a, b)) == ["death"]


# -- objectives -----------------------------------------------------------

def test_objective_taken_new_events_only_with_voidgrub_and_stolen():
    old = [_ev(1, "DragonKill", 300.0, DragonType="Fire")]
    a = _base(400.0, events=old)
    new = old + [
        _ev(2, "HordeKill", 401.0, killer="SyntheticZed#T9", Stolen="True"),
        _ev(3, "ChampionKill", 401.5),
        _ev(4, "DragonKill", 401.8, DragonType="Elder", Stolen="False"),
    ]
    b = _base(402.0, events=new)
    b["allPlayers"][1]["summonerName"] = "SyntheticZed#T9"
    a["allPlayers"][1]["summonerName"] = "SyntheticZed#T9"
    evs = led.derive_events(a, b, completed_ids=LEG)
    assert evs == [
        {"kind": "objective_taken", "game_time": 402.0, "event_id": 2,
         "objective": "voidgrub", "at_s": 401.0, "killer_team": "enemy",
         "stolen": True},
        {"kind": "objective_taken", "game_time": 402.0, "event_id": 4,
         "objective": "dragon", "at_s": 401.8, "killer_team": "ally",
         "stolen": False, "dragon_type": "Elder"},
    ]


def test_objective_events_none_reading_never_transitions():
    a = _base(400.0)
    a["events"] = None
    b = _base(401.0, events=[_ev(5, "BaronKill", 400.5)])
    assert led.derive_events(a, b, completed_ids=LEG) == []


def test_objective_without_event_id_is_skipped():
    a = _base(400.0)
    b = _base(401.0, events=[{"EventName": "BaronKill", "EventTime": 400.5}])
    assert led.derive_events(a, b, completed_ids=LEG) == []


# -- reserved / shape -----------------------------------------------------

def test_skill_point_is_reserved_and_never_emitted():
    assert led.SKILL_POINT == "skill_point"
    assert led.SKILL_POINT in led.RESERVED_KINDS
    assert led.SKILL_POINT not in led.EMITTED_KINDS
    a = _base(100.0)
    a["activePlayer"]["abilities"] = {"Q": {"abilityLevel": 1}}
    b = _base(101.0)
    b["activePlayer"]["abilities"] = {"Q": {"abilityLevel": 2}}
    assert led.derive_events(a, b, completed_ids=LEG) == []


def test_replay_frame_envelope_is_unwrapped():
    a = {"kind": "frame", "seq": 1, "snapshot": _base(100.0)}
    b = {"kind": "frame", "seq": 2, "snapshot": _base(101.0, zed_dead=True)}
    assert _kinds(led.derive_events(a, b, completed_ids=LEG)) == ["death"]


def test_inputs_are_not_mutated():
    a = _base(100.0, lux_items=(1001,))
    b = _base(101.0, lux_items=(1001, 3031), zed_dead=True, lux_level=4,
              events=[_ev(9, "BaronKill", 100.5)])
    a0, b0 = copy.deepcopy(a), copy.deepcopy(b)
    led.derive_events(a, b, completed_ids=LEG)
    assert a == a0 and b == b0


def test_liveclient_summary_shares_the_objective_name_map():
    from dashboard import _liveclient
    assert _liveclient.OBJECTIVE_EVENT_NAMES is led.OBJECTIVE_EVENT_NAMES
    assert led.OBJECTIVE_EVENT_NAMES["HordeKill"] == "voidgrub"
