"""s144 true-audit of core/self_cast_log.py (RM-606 self ability-usage log).

All payloads are synthetic: invented champion names, invented Riot IDs, no
captured data. Each defect below has at least one test that was red before
the fix; the other tests pin the boundary on the valid side:

1. A >1e308 int gameTime / resourceValue / resourceMax / abilityLevel raised
   OverflowError out of reading_from_allgamedata (and out of the unwrapped
   offline detect_from_frames); a negative or absurd clock, value or max was a
   Reading (a resourceValue of -50 is a fake 450-point "cast"); a fractional
   abilityLevel 2.7 was rank 2 and an abilityLevel of 99 read the last rank.
2. active_champion_name took the FIRST player whose game name matched, so a
   second player sharing the game name (another tag line) listed first gave
   the wrong champion's cost table; an ambiguous base-name match is now None.
3. One frame whose champion lookup failed swapped the live detector for an
   empty-cost one, dropping the pending candidate and its baseline; the cost
   table was also parsed while the state lock was held, and a detector built
   from a failed load stayed costless until the champion changed.
4. A junk per-rank cost was DROPPED, shifting every later rank down one place;
   a >1e308 int cost raised; a failed load was cached as {} for the process
   lifetime; current.txt naming "../x" read outside the DS data root.
5. per_slot_totals raised on a non-mapping event, a str confidence or an
   unhashable slot, and a NaN confidence passed any min_confidence;
   validate_against_match_v5 truncated a fractional truth, compared a negative
   one, raised on a junk cost entry and read a sqlite3.Row (the
   rewind_history.db row its comment names) as "no truth".
6. events() handed out the stored dicts, so a consumer that mutated one
   rewrote the log.
"""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from core import self_cast_log as scl

MANA_COSTS = {
    "Q": ("MANA", (50.0, 60.0, 70.0, 80.0, 90.0)),
    "W": ("MANA", (30.0, 30.0, 30.0, 30.0, 30.0)),
    "E": ("MANA", (85.0, 85.0, 85.0, 85.0, 85.0)),
    "R": ("MANA", (100.0, 100.0, 100.0)),
}

HUGE = 10 ** 400


def _agd(t=100.0, value=300.0, maximum=500.0, rtype="MANA",
         ranks=(1, 1, 1, 0), champ="Synthchamp", players=None):
    return {
        "activePlayer": {
            "riotIdGameName": "Player1",
            "summonerName": "Player1#TST",
            "abilities": {
                "Q": {"abilityLevel": ranks[0]},
                "W": {"abilityLevel": ranks[1]},
                "E": {"abilityLevel": ranks[2]},
                "R": {"abilityLevel": ranks[3]},
            },
            "championStats": {"resourceValue": value, "resourceMax": maximum,
                              "resourceType": rtype},
        },
        "allPlayers": ([{"riotIdGameName": "Player1", "championName": champ}]
                       if players is None else players),
        "gameData": {"gameTime": t},
    }


class _Snap:
    def __init__(self, data):
        self.data = data


# -- 1. readings --------------------------------------------------------------

@pytest.mark.parametrize("kw", [
    {"t": HUGE}, {"value": HUGE}, {"maximum": HUGE},
    {"t": -5.0}, {"t": 10 ** 7},
    {"value": -50.0}, {"value": 10 ** 6},
    {"maximum": -1.0}, {"maximum": 10 ** 6},
])
def test_overflowing_or_out_of_range_reading_is_none(kw):
    assert scl.reading_from_allgamedata(_agd(**kw)) is None


def test_offline_detect_skips_an_overflowing_frame():
    frames = [_agd(t=10.0, value=400.0), _agd(t=HUGE),
              _agd(t=10.5, value=350.0), _agd(t=11.0, value=351.0)]
    ev = scl.detect_from_frames(frames, MANA_COSTS)
    assert [e["slot_guess"] for e in ev] == ["Q"]


@pytest.mark.parametrize("lvl,want", [
    (HUGE, 0), (2.7, 0), (99, 0), (7, 0), (-1, 0), ("3", 0), (True, 0),
    (3.0, 3), (6, 6), (0, 0),
])
def test_ability_level_must_be_an_integral_rank_0_to_6(lvl, want):
    r = scl.reading_from_allgamedata(_agd(ranks=(lvl, 1, 1, 0)))
    assert r is not None
    assert r.ranks["Q"] == want


def test_zero_clock_and_full_range_values_are_still_readings():
    r = scl.reading_from_allgamedata(_agd(t=0.0, value=0.0, maximum=0.0))
    assert r is not None and r.t == 0.0
    assert scl.reading_from_allgamedata(_agd(value=10 ** 5, maximum=10 ** 5))


# -- 2. active champion -------------------------------------------------------

def _ap(**ids):
    d = _agd()
    d["activePlayer"].pop("riotIdGameName")
    d["activePlayer"].pop("summonerName")
    d["activePlayer"].update(ids)
    return d


def test_exact_riot_id_beats_an_earlier_shared_game_name():
    d = _ap(riotId="Same#AAA", riotIdGameName="Same")
    d["allPlayers"] = [
        {"riotId": "Same#BBB", "riotIdGameName": "Same",
         "riotIdTagLine": "BBB", "championName": "Wrongchamp"},
        {"riotId": "Same#AAA", "riotIdGameName": "Same",
         "riotIdTagLine": "AAA", "championName": "Rightchamp"},
    ]
    assert scl.active_champion_name(d) == "Rightchamp"


def test_composed_game_name_and_tag_line_is_an_exact_match():
    d = _ap(riotIdGameName="Same", riotIdTagLine="AAA")
    d["allPlayers"] = [
        {"riotIdGameName": "Same", "riotIdTagLine": "BBB",
         "championName": "Wrongchamp"},
        {"riotIdGameName": "Same", "riotIdTagLine": "AAA",
         "championName": "Rightchamp"},
    ]
    assert scl.active_champion_name(d) == "Rightchamp"


def test_ambiguous_base_name_match_is_none():
    d = _ap(riotIdGameName="Same")
    d["allPlayers"] = [
        {"riotIdGameName": "Same", "championName": "Onechamp"},
        {"riotIdGameName": "Same", "championName": "Otherchamp"},
    ]
    assert scl.active_champion_name(d) is None


def test_unique_base_name_match_still_resolves():
    d = _ap(summonerName="Solo#TST")
    d["allPlayers"] = [
        {"riotIdGameName": "Someone", "championName": "Nochamp"},
        {"riotIdGameName": "Solo", "championName": "Yeschamp"},
    ]
    assert scl.active_champion_name(d) == "Yeschamp"


# -- 3. live adapter ----------------------------------------------------------

def test_a_frame_with_no_champion_keeps_the_detector_and_its_candidate(
        monkeypatch):
    scl.reset()
    monkeypatch.setattr(scl, "load_cost_table", lambda cid: MANA_COSTS)
    try:
        scl.on_snapshot(_Snap(_agd(t=10.0, value=400.0)))
        scl.on_snapshot(_Snap(_agd(t=10.5, value=350.0)))
        # allPlayers missing on the confirming frame: lookup fails.
        n = scl.on_snapshot(_Snap(_agd(t=11.0, value=351.0, players=[])))
        assert n == 1
        assert [e["slot_guess"] for e in scl.events()] == ["Q"]
    finally:
        scl.reset()


def test_a_new_champion_still_gets_a_new_detector(monkeypatch):
    scl.reset()
    loaded = []

    def _load(cid):
        loaded.append(cid)
        return MANA_COSTS

    monkeypatch.setattr(scl, "load_cost_table", _load)
    try:
        scl.on_snapshot(_Snap(_agd(t=10.0, value=400.0, champ="Onechamp")))
        scl.on_snapshot(_Snap(_agd(t=10.5, value=350.0, champ="Twochamp")))
        assert scl.on_snapshot(
            _Snap(_agd(t=11.0, value=351.0, champ="Twochamp"))) == 0
        assert len(loaded) == 2
    finally:
        scl.reset()


def test_cost_table_is_loaded_outside_the_state_lock(monkeypatch):
    scl.reset()
    held = []

    def _load(cid):
        held.append(scl._state_lock.locked())
        return MANA_COSTS

    monkeypatch.setattr(scl, "load_cost_table", _load)
    try:
        scl.on_snapshot(_Snap(_agd(t=10.0, value=400.0)))
        assert held == [False]
    finally:
        scl.reset()


def test_a_costless_detector_retries_the_load_without_losing_state(
        monkeypatch):
    scl.reset()
    tables = [{}]
    calls = []

    def _load(cid):
        calls.append(cid)
        return tables[0]

    monkeypatch.setattr(scl, "load_cost_table", _load)
    try:
        scl.on_snapshot(_Snap(_agd(t=10.0, value=400.0)))
        scl.on_snapshot(_Snap(_agd(t=20.0, value=400.0)))
        assert len(calls) == 1  # no retry inside COST_RETRY_S
        tables[0] = MANA_COSTS
        t0 = 10.0 + scl.COST_RETRY_S
        # The retry frame is also the candidate frame: the baseline survives.
        scl.on_snapshot(_Snap(_agd(t=t0, value=350.0)))
        assert len(calls) == 2
        scl.on_snapshot(_Snap(_agd(t=t0 + 0.5, value=351.0)))
        assert [e["slot_guess"] for e in scl.events()] == ["Q"]
        scl.on_snapshot(_Snap(_agd(t=t0 + 100.0, value=351.0)))
        assert len(calls) == 2  # a detector with costs never reloads
    finally:
        scl.reset()


def test_a_failing_load_retries_once_per_spacing_and_on_a_new_game(
        monkeypatch):
    scl.reset()
    calls = []
    monkeypatch.setattr(scl, "load_cost_table",
                        lambda cid: calls.append(cid) or {})
    try:
        t = 10.0
        while t <= 10.0 + 3 * scl.COST_RETRY_S:
            scl.on_snapshot(_Snap(_agd(t=t, value=400.0)))
            t += 0.5
        assert len(calls) == 4  # the first build plus one per spacing
        # Game time ran backwards (a new game, same champion): retry now.
        scl.on_snapshot(_Snap(_agd(t=1.0, value=400.0)))
        assert len(calls) == 5
    finally:
        scl.reset()


class _RacyLock:
    """A real lock that, when armed, simulates reset() landing between the
    two lock blocks of one on_snapshot call."""

    def __init__(self):
        self._lock = threading.Lock()
        self.entries = 0
        self.armed = False

    def __enter__(self):
        self.entries += 1
        if self.armed and self.entries == 2:
            scl._detector = None
            scl._champion = None
        self._lock.acquire()
        return self

    def __exit__(self, *exc):
        self._lock.release()

    def locked(self):
        return self._lock.locked()


def test_reset_between_the_locks_never_leaves_a_costless_detector(
        monkeypatch):
    scl.reset()
    racy = _RacyLock()
    monkeypatch.setattr(scl, "_state_lock", racy)
    monkeypatch.setattr(scl, "load_cost_table", lambda cid: MANA_COSTS)
    try:
        scl.on_snapshot(_Snap(_agd(t=10.0, value=400.0)))
        racy.entries, racy.armed = 0, True
        assert scl.on_snapshot(_Snap(_agd(t=10.5, value=400.0))) == 0
        racy.armed = False
        for t, v in ((11.0, 400.0), (11.5, 350.0), (12.0, 351.0)):
            scl.on_snapshot(_Snap(_agd(t=t, value=v)))
        assert [e["slot_guess"] for e in scl.events()] == ["Q"]
    finally:
        scl._detector = None
        scl._champion = None
        scl._events.clear()


# -- 4. DS cost data ----------------------------------------------------------

def _ds_root(tmp_path, kit, patch="16.1.1"):
    root = tmp_path / "ds"
    (root / patch).mkdir(parents=True)
    (root / "current.txt").write_text(patch + "\n", encoding="utf-8")
    (root / patch / "champion_abilities.json").write_text(
        json.dumps({"data": {"Synthchamp": kit}}), encoding="utf-8")
    return root


def test_junk_per_rank_cost_keeps_later_ranks_in_place(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "_COST_CACHE", {})
    root = _ds_root(tmp_path, {"Q": [{"resource": "MANA",
                                      "cost": [50, None, 70, "x", 90]}]})
    res, costs = scl.load_cost_table("Synthchamp", root)["Q"]
    assert res == "MANA"
    assert len(costs) == 5
    table = {"Q": (res, costs)}
    assert scl._live_costs({"Q": 3}, table, "MANA") == [("Q", 70.0)]
    assert scl._live_costs({"Q": 2}, table, "MANA") == []
    assert scl._live_costs({"Q": 5}, table, "MANA") == [("Q", 90.0)]


def test_overflowing_cost_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "_COST_CACHE", {})
    root = tmp_path / "ds"
    (root / "16.1.1").mkdir(parents=True)
    (root / "current.txt").write_text("16.1.1", encoding="utf-8")
    (root / "16.1.1" / "champion_abilities.json").write_text(
        '{"data": {"Synthchamp": {"Q": [{"resource": "MANA", "cost": ['
        + "9" * 400 + ', 60]}]}}}', encoding="utf-8")
    res, costs = scl.load_cost_table("Synthchamp", root)["Q"]
    assert scl._live_costs({"Q": 2}, {"Q": (res, costs)}, "MANA") == [
        ("Q", 60.0)]
    assert scl._live_costs({"Q": 1}, {"Q": (res, costs)}, "MANA") == []


def test_failed_load_is_not_cached_for_the_process(tmp_path, monkeypatch):
    monkeypatch.setattr(scl, "_COST_CACHE", {})
    root = tmp_path / "ds"
    (root / "16.1.1").mkdir(parents=True)
    (root / "current.txt").write_text("16.1.1", encoding="utf-8")
    target = root / "16.1.1" / "champion_abilities.json"
    target.write_text("{truncated", encoding="utf-8")
    assert scl.load_cost_table("Synthchamp", root) == {}
    target.write_text(json.dumps({"data": {"Synthchamp": {
        "Q": [{"resource": "MANA", "cost": [50]}]}}}), encoding="utf-8")
    assert scl.load_cost_table("Synthchamp", root)["Q"] == ("MANA", (50.0,))


@pytest.mark.parametrize("patch", ["../outside", "..", ".", "a/b", "a\\b",
                                   "x" * 65])
def test_current_patch_must_be_one_path_segment(tmp_path, monkeypatch, patch):
    monkeypatch.setattr(scl, "_COST_CACHE", {})
    root = tmp_path / "ds"
    root.mkdir()
    (root / "current.txt").write_text(patch, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "champion_abilities.json").write_text(json.dumps({"data": {
        "Synthchamp": {"Q": [{"resource": "MANA", "cost": [50]}]}}}),
        encoding="utf-8")
    assert scl.load_cost_table("Synthchamp", root) == {}


# -- 5. offline validator -----------------------------------------------------

def test_per_slot_totals_survives_junk_events():
    evs = [None, "x", 5,
           {"slot_guess": "Q", "confidence": "abc"},
           {"slot_guess": ["Q"], "confidence": 0.9},
           {"slot_guess": "Q", "confidence": float("nan")},
           {"slot_guess": "Q", "confidence": True},
           {"slot_guess": "Q", "confidence": 0.9}]
    assert scl.per_slot_totals(evs, min_confidence=0.5) == {
        "Q": 1, "W": 0, "E": 0, "R": 0, "unattributed": 1}
    assert scl.per_slot_totals(evs) == {
        "Q": 4, "W": 0, "E": 0, "R": 0, "unattributed": 1}


def test_per_slot_totals_junk_min_confidence_counts_everything():
    evs = [{"slot_guess": "Q", "confidence": 0.1}]
    for bad in (float("nan"), "x", None):
        assert scl.per_slot_totals(evs, min_confidence=bad)["Q"] == 1


@pytest.mark.parametrize("truth", [12.7, -3, True, 10 ** 6, float("inf")])
def test_validator_rejects_a_non_count_truth(truth):
    v = scl.validate_against_match_v5(
        [{"slot_guess": "Q", "confidence": 0.9}],
        {"spell1_casts": truth}, MANA_COSTS)
    assert v["slots"]["Q"]["truth"] is None
    assert v["slots"]["Q"]["compared"] is False


def test_validator_integral_float_truth_is_a_count():
    v = scl.validate_against_match_v5(
        [{"slot_guess": "Q", "confidence": 0.9}],
        {"spell1_casts": 1.0}, MANA_COSTS)
    assert v["slots"]["Q"]["truth"] == 1
    assert v["slots"]["Q"]["compared"] is True


@pytest.mark.parametrize("entry", ["MANA", ("MANA",), ("MANA", ("x", None)),
                                   ("MANA", 5), None, ("MANA", (HUGE,))])
def test_validator_junk_cost_entry_is_not_observable(entry):
    v = scl.validate_against_match_v5(
        [], {"spell1_casts": 3}, {"Q": entry})
    assert v["slots"]["Q"]["compared"] is False
    assert v["pass"] is False


def test_validator_non_mapping_costs_is_not_observable():
    v = scl.validate_against_match_v5([], {"spell1_casts": 3}, None)
    assert v["pass"] is False


def test_validator_reads_a_sqlite_row():
    con = sqlite3.connect(":memory:")
    try:
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE p (spell1_casts INTEGER, spell2_casts "
                    "INTEGER, spell3_casts INTEGER, spell4_casts INTEGER)")
        con.execute("INSERT INTO p VALUES (2, 0, 0, 0)")
        row = con.execute("SELECT * FROM p").fetchone()
    finally:
        con.close()
    ev = [{"slot_guess": "Q", "confidence": 0.9}] * 2
    v = scl.validate_against_match_v5(ev, row, MANA_COSTS)
    assert v["slots"]["Q"]["truth"] == 2
    assert v["slots"]["Q"]["compared"] is True
    assert v["pass"] is True


# -- 6. events() --------------------------------------------------------------

def test_events_returns_copies(monkeypatch):
    scl.reset()
    monkeypatch.setattr(scl, "load_cost_table", lambda cid: MANA_COSTS)
    try:
        for t, v in ((10.0, 400.0), (10.5, 350.0), (11.0, 351.0)):
            scl.on_snapshot(_Snap(_agd(t=t, value=v)))
        got = scl.events()
        got[0]["slot_guess"] = "tampered"
        got.clear()
        assert [e["slot_guess"] for e in scl.events()] == ["Q"]
    finally:
        scl.reset()


def test_events_is_safe_against_a_concurrent_reset(monkeypatch):
    scl.reset()
    monkeypatch.setattr(scl, "load_cost_table", lambda cid: MANA_COSTS)
    errs = []

    def _reader():
        try:
            for _ in range(200):
                scl.events()
        except Exception as exc:  # noqa: BLE001 - the test records any raise
            errs.append(exc)

    th = threading.Thread(target=_reader, name="scl-reader")
    th.start()
    for i in range(200):
        scl.on_snapshot(_Snap(_agd(t=10.0 + i, value=400.0 - (i % 2) * 60)))
        if i % 50 == 0:
            scl.reset()
    th.join(5)
    scl.reset()
    assert errs == []
