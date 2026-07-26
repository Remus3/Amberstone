"""The postgame narrative must see the WHOLE game, and name what happened.

Measured 2026-07-26 against data/rewind_history.db: the loader's flat
`ORDER BY timestamp_ms LIMIT 600` truncated 2677 of 2961 matches. On a clean
22-minute sample it stopped at 11 minutes and the narrative saw 2 of 9
BUILDING_KILL events, so baron, late objectives and inhibitors were invisible
in 90 percent of games.
"""
from __future__ import annotations

import sqlite3

from coaches import replay_coach as rc
from core import precomputed_replay_narrative as pn

_COLS = ("match_id", "timestamp_ms", "event_type", "participant_id",
         "item_id", "killer_id", "victim_id", "building_type", "monster_type",
         "shutdown_bounty", "bounty")


def _db(tmp_path, rows):
    path = tmp_path / "rewind.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE timeline_events ({})".format(
            ", ".join(f"{c} TEXT" if c in ("match_id", "event_type",
                                           "building_type", "monster_type")
                      else f"{c} INTEGER" for c in _COLS)))
    conn.execute("CREATE TABLE matches (match_id TEXT)")
    conn.execute("CREATE TABLE participants (match_id TEXT)")
    conn.execute("INSERT INTO matches VALUES ('M1')")
    conn.executemany(
        "INSERT INTO timeline_events ({}) VALUES ({})".format(
            ", ".join(_COLS), ", ".join("?" * len(_COLS))),
        [tuple(r.get(c) for c in _COLS) for r in rows])
    conn.commit()
    conn.close()
    return path


def _ev(ts, etype, **kw):
    row = {"match_id": "M1", "timestamp_ms": ts, "event_type": etype}
    row.update(kw)
    return row


def test_a_late_objective_survives_the_loader_row_cap(tmp_path, monkeypatch):
    # 700 early filler purchases then one late baron. A flat first-N-by-time
    # cap drops the baron; the narrative must not be blind to it.
    rows = [_ev(1000 + i, "ITEM_PURCHASED", participant_id=1, item_id=1055)
            for i in range(700)]
    rows.append(_ev(1_800_000, "ELITE_MONSTER_KILL", killer_id=1,
                    monster_type="BARON_NASHOR"))
    rows.append(_ev(1_500_000, "BUILDING_KILL", killer_id=1,
                   building_type="INHIBITOR_BUILDING"))
    monkeypatch.setattr(rc, "_REWIND_DB", _db(tmp_path, rows))

    blob = rc._load_match("M1")
    kinds = {e["event_type"] for e in blob["events"]}
    assert "ELITE_MONSTER_KILL" in kinds
    assert "BUILDING_KILL" in kinds


def test_the_loader_still_returns_events_in_time_order(tmp_path, monkeypatch):
    # Prioritising match-shaping events must not leave the caller with a list
    # that is no longer chronological - every consumer assumes time order.
    rows = [_ev(500_000, "CHAMPION_KILL", killer_id=1, victim_id=6),
            _ev(1000, "ITEM_PURCHASED", participant_id=1, item_id=1055),
            _ev(900_000, "BUILDING_KILL", killer_id=1,
                building_type="TOWER_BUILDING")]
    monkeypatch.setattr(rc, "_REWIND_DB", _db(tmp_path, rows))
    times = [e["timestamp_ms"] for e in rc._load_match("M1")["events"]]
    assert times == sorted(times)


def test_the_loader_is_still_bounded(tmp_path, monkeypatch):
    rows = [_ev(i, "CHAMPION_KILL", killer_id=1, victim_id=6)
            for i in range(2000)]
    monkeypatch.setattr(rc, "_REWIND_DB", _db(tmp_path, rows))
    assert len(rc._load_match("M1")["events"]) <= rc._EVENT_ROW_CAP


# ------------------------------------------------------ naming the moment

def test_a_kill_between_two_other_players_names_both_champions():
    # "a kill traded" throws away killer_id and victim_id, which the row has.
    ev = {"event_type": "CHAMPION_KILL", "timestamp_ms": 725_000,
          "killer_id": 3, "victim_id": 8}
    names = {3: "Vayne", 8: "Lee Sin"}
    text = pn._describe_moment(ev, operator_pid=1, names=names)
    assert "Vayne" in text and "Lee Sin" in text
    assert "12:05" in text


def test_the_operator_is_still_addressed_in_the_second_person():
    ev = {"event_type": "CHAMPION_KILL", "timestamp_ms": 60_000,
          "killer_id": 1, "victim_id": 8}
    text = pn._describe_moment(ev, operator_pid=1, names={1: "Vayne",
                                                         8: "Lee Sin"})
    assert "you" in text.lower()
    assert "Lee Sin" in text


def test_an_unknown_participant_degrades_to_the_generic_line():
    # No names available must not produce "None kills None".
    ev = {"event_type": "CHAMPION_KILL", "timestamp_ms": 60_000,
          "killer_id": 3, "victim_id": 8}
    text = pn._describe_moment(ev, operator_pid=1, names={})
    assert "None" not in text


def test_describe_moment_still_works_without_a_names_argument():
    ev = {"event_type": "CHAMPION_KILL", "timestamp_ms": 60_000,
          "killer_id": 3, "victim_id": 8}
    assert pn._describe_moment(ev, 1)


# ------------------------------------------- naming the objective, not "a team"
#
# The taxonomy below is the live one, counted over rewind_history.db:
#   ELITE_MONSTER_KILL  HORDE 3336 / RIFTHERALD 664 / BARON_NASHOR 577 /
#                       DRAGON 2479 across 6 subtypes + ELDER_DRAGON 43 +
#                       UNKNOWN 51 / ATAKHAN 143
#   BUILDING_KILL       OUTER 6684 / NEXUS_TURRET 4810 / INHIBITOR 4803 /
#                       BASE 3661 / INNER 2462
# monster_subtype and tower_type were both being thrown away by the renderer.


def _monster(monster_type, subtype=None, killer_id=3, ts=1_500_000):
    return {"event_type": "ELITE_MONSTER_KILL", "timestamp_ms": ts,
            "monster_type": monster_type, "monster_subtype": subtype,
            "killer_id": killer_id}


def test_drake_subtype_is_named():
    expected = {
        "FIRE_DRAGON": "Infernal",
        "EARTH_DRAGON": "Mountain",
        "WATER_DRAGON": "Ocean",
        "AIR_DRAGON": "Cloud",
        "CHEMTECH_DRAGON": "Chemtech",
        "HEXTECH_DRAGON": "Hextech",
    }
    for subtype, label in expected.items():
        text = pn._describe_moment(_monster("DRAGON", subtype), 1, {3: "Vayne"})
        assert label in text, f"{subtype} rendered as {text}"


def test_elder_dragon_is_named_and_outranks_a_normal_drake():
    elder = _monster("DRAGON", "ELDER_DRAGON")
    drake = _monster("DRAGON", "FIRE_DRAGON")
    assert "Elder" in pn._describe_moment(elder, 1, {3: "Vayne"})
    assert pn._moment_impact(elder, 1) > pn._moment_impact(drake, 1)


def test_unknown_drake_subtype_degrades_without_emitting_none():
    for subtype in (None, "UNKNOWN", ""):
        text = pn._describe_moment(_monster("DRAGON", subtype), 1, {3: "Vayne"})
        assert "None" not in text
        assert text.strip()


def test_atakhan_and_rift_herald_are_named():
    assert "Atakhan" in pn._describe_moment(_monster("ATAKHAN"), 1, {3: "Vayne"})
    assert "Rift Herald" in pn._describe_moment(
        _monster("RIFTHERALD"), 1, {3: "Vayne"})


def test_voidgrubs_rank_far_below_baron():
    # HORDE is the most common elite monster in the corpus by a wide margin and
    # was scoring 45, the same as a Rift Herald and 1.5x a plain champion kill.
    # Three spawn and they are a minor objective.
    horde = pn._moment_impact(_monster("HORDE"), 1)
    baron = pn._moment_impact(_monster("BARON_NASHOR"), 1)
    plain_kill = pn._moment_impact(
        {"event_type": "CHAMPION_KILL", "timestamp_ms": 1, "killer_id": 3}, 1)
    assert horde < plain_kill < baron


def test_objective_names_the_taker_when_known():
    text = pn._describe_moment(_monster("BARON_NASHOR"), 1, {3: "Vayne"})
    assert "Baron" in text
    assert "Vayne" in text


def test_objective_taken_by_the_operator_is_second_person():
    text = pn._describe_moment(
        _monster("BARON_NASHOR", killer_id=1), 1, {1: "Vayne"})
    assert "Baron" in text
    assert "you" in text.lower()


def test_objective_with_no_known_taker_does_not_emit_none():
    text = pn._describe_moment(_monster("BARON_NASHOR"), 1, {})
    assert "None" not in text
    assert "Baron" in text


def _building(building_type, tower_type=None, killer_id=3):
    return {"event_type": "BUILDING_KILL", "timestamp_ms": 1_200_000,
            "building_type": building_type, "tower_type": tower_type,
            "killer_id": killer_id}


def test_tower_tier_is_named_not_just_tower_building():
    expected = {"OUTER_TURRET": "Outer", "INNER_TURRET": "Inner",
                "BASE_TURRET": "Base", "NEXUS_TURRET": "Nexus"}
    for tower_type, label in expected.items():
        text = pn._describe_moment(
            _building("TOWER_BUILDING", tower_type), 1, {3: "Vayne"})
        assert label in text, f"{tower_type} rendered as {text}"
        assert "Tower Building" not in text


def test_inhibitor_is_named_and_scores_above_a_plain_tower():
    # The inhibitor rows carry building_type=INHIBITOR_BUILDING with a NULL
    # tower_type, and the impact branch only ever read tower_type - so all 4803
    # inhibitors in the corpus scored 35, the ordinary-tower value, despite the
    # branch intending 50.
    inhib = _building("INHIBITOR_BUILDING")
    outer = _building("TOWER_BUILDING", "OUTER_TURRET")
    assert "Inhibitor" in pn._describe_moment(inhib, 1, {3: "Vayne"})
    assert pn._moment_impact(inhib, 1) > pn._moment_impact(outer, 1)


def test_tower_tiers_are_ordered_by_impact():
    tiers = [pn._moment_impact(_building("TOWER_BUILDING", t), 1)
             for t in ("OUTER_TURRET", "INNER_TURRET",
                       "BASE_TURRET", "NEXUS_TURRET")]
    assert tiers == sorted(tiers)
    assert len(set(tiers)) == 4


def test_building_with_no_type_does_not_emit_none():
    text = pn._describe_moment(_building(None, None), 1, {})
    assert "None" not in text
    assert text.strip()


# ------------------------------------------------------------ duplicates

def _blob(events):
    return {"match": {"match_id": "M1", "game_duration_s": 1800},
            "participants": [], "events": events}


def test_identical_events_cannot_produce_repeated_key_moments():
    # Three matches in the live db carry 6x and 12x duplicated rows, which
    # surfaced as five identical key moments in one narrative.
    dupe = {"event_type": "CHAMPION_KILL", "timestamp_ms": 105_000,
            "killer_id": 9, "victim_id": 5, "bounty": 400}
    out = pn.build_narrative(_blob([dict(dupe) for _ in range(6)]))
    texts = [m["text"] for m in out["key_moments"]]
    assert len(texts) == len(set(texts))
    assert len(texts) == 1


def test_distinct_events_at_the_same_clock_are_both_kept():
    # Two different players dying in the same second is a real teamfight, not
    # a duplicate. The guard must key on identity, not on the clock.
    a = {"event_type": "CHAMPION_KILL", "timestamp_ms": 105_000,
         "killer_id": 9, "victim_id": 5, "bounty": 400}
    b = {"event_type": "CHAMPION_KILL", "timestamp_ms": 105_000,
         "killer_id": 9, "victim_id": 4, "bounty": 300}
    out = pn.build_narrative(_blob([a, b]))
    assert len(out["key_moments"]) == 2
