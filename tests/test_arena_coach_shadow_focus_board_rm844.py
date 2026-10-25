"""RM-844 - the focus board's kill-order pick shadow-logged beside the Arena
``target_priority`` rule. SHADOW-ONLY: the served coach never changes.

Grounded before writing (file:line at main 4b0bc3ce4):

* ``core/arena_coach_shadow.py:78`` ``log_arena_coach(det_block, live_block,
  lc, mode_key, *, round_label, path, now_iso)``; the record fields
  (``:140-148``); the per-path dedup (``_LAST_SIG``, ``:38``, keyed by
  ``str(target)``, so every test uses its own tmp_path).
* ``core/arena_target_rule.py:33`` ``target_priority(alive_opponents,
  frontline_names)``, output shapes ``"Kill {name} first - squishy threat;
  tanks last"`` (``:56-58``) and ``"Kill {name} first - no squishy target"``
  (``:61``).
* ``dashboard/_deterministic_coaching.py:1362`` ``shadow_log_arena_coach``:
  alive opponents from ``coach["teams"]`` (``:1419-1431``), the
  ``build_block`` call (``:1485-1494``, ``core/arena_deterministic_coach.py:260``)
  and the ``log_arena_coach`` call (``:1499-1501``).
* The adapter is ``core.focus_board_live`` (tests/test_focus_board_live_rm844.py
  cites its inputs).
"""

from __future__ import annotations

import copy
import json

import pytest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.focus_board import compute_focus_board
from core import arena_coach_shadow as shadow
from core import focus_board_live as fbl
from core.arena_target_rule import target_priority
from dashboard._deterministic_coaching import shadow_log_arena_coach

_NOW = "2026-10-24T00:00:00+00:00"

_PRE_RM844_KEYS = {
    "ts", "mode", "champ", "round", "enemy_comp", "deterministic", "live_haiku",
}

_DET = {
    "action": "FIGHT SMART",
    "round_strategy": "Your HP 80% - trade efficiently and kite",
    "fight_rule": "",
    "augment_advice": "",
    "anvil_advice": "",
    "target_priority": "Kill Kai'Sa first - squishy threat; tanks last",
    "risk": "",
    "choices": [],
}


@pytest.fixture(scope="module")
def snapshot():
    return DataSnapshot.load()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.delenv(fbl.KILL_SWITCH_ENV, raising=False)
    fbl.reset_for_tests()
    yield
    fbl.reset_for_tests()


@pytest.fixture()
def real_engine(snapshot):
    fbl._set_engine_for_tests((snapshot, compute_focus_board))
    return snapshot


def _player(name, raw, team, level, items, summ):
    return {"summonerName": summ, "riotIdGameName": summ.split("#")[0],
            "championName": name, "rawChampionName": raw, "team": team,
            "level": level,
            "items": [{"itemID": i, "slot": n} for n, i in enumerate(items)],
            "scores": {"kills": 0, "deaths": 0, "assists": 0}}


def _lc() -> dict:
    return {
        "champion": "Jinx",
        "level": 12,
        "enemy_team": ["Wukong", "Dr. Mundo", "Kai'Sa"],
        "activePlayer": {"summonerName": "Me#TST", "riotIdGameName": "Me"},
        "allPlayers": [
            _player("Jinx", "game_character_displayname_Jinx", "100", 12,
                    [3006, 3031], "Me#TST"),
            _player("Karma", "game_character_displayname_Karma", "100", 12,
                    [3504], "Duo#TST"),
            _player("Wukong", "game_character_displayname_MonkeyKing", "200",
                    12, [3071], "FoeA#TST"),
            _player("Dr. Mundo", "game_character_displayname_DrMundo", "200",
                    11, [3084], "FoeB#TST"),
            _player("Kai'Sa", "game_character_displayname_Kaisa", "300", 12,
                    [], "FoeC#TST"),
        ],
    }


def _coach() -> dict:
    return {
        "champion": "Jinx",
        "hp_pct": 80,
        "camp_phase": False,
        "round": 4,
        "alive_teams": 3,
        "teams": [
            {"name": "Jinx", "is_you": True},
            {"name": "Karma", "is_partner": True},
            {"name": "Wukong", "is_dead": False},
            {"name": "Dr. Mundo", "is_dead": False},
            {"name": "Kai'Sa", "is_dead": False},
        ],
        "items": [],
    }


def _rows(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


# -- reading the rule's pick back -------------------------------------------------

@pytest.mark.parametrize("opps,frontline,want", [
    (["Lux", "Malphite"], {"Malphite"}, "Lux"),         # squishy shape
    (["Malphite", "Leona"], {"Malphite", "Leona"}, "Malphite"),  # no-squishy
    (["Dr. Mundo"], set(), "Dr. Mundo"),                # multi-word name
    (["Kai'Sa"], set(), "Kai'Sa"),
])
def test_rule_pick_round_trips_every_target_rule_shape(opps, frontline, want):
    assert shadow._rule_pick(target_priority(opps, frontline)) == want


@pytest.mark.parametrize("line", ["", None, 7, "Zed first, Lulu last."])
def test_rule_pick_unparseable_is_blank(line):
    assert shadow._rule_pick(line) == ""


# -- the shadow record ------------------------------------------------------------

def test_record_carries_rule_pick_and_board_pick(tmp_path, real_engine):
    target = tmp_path / "arena_coach_shadow.jsonl"
    rec = shadow.log_arena_coach(_DET, {}, _lc(), "arena", round_label=4,
                                 path=target, now_iso=_NOW)
    assert rec is not None
    [row] = _rows(target)
    assert row == rec
    # The rule stays the authoritative column, verbatim.
    assert row["deterministic"] == _DET
    fb = row["focus_board"]
    assert fb["status"] == fbl.STATUS_OK, fb["notes"]
    assert fb["rule_pick"] == "Kai'Sa"
    assert fb["board_pick"] == fb["kill_order_names"][0]
    assert fb["board_pick"] == fb["top_kill"]["champion_name"]
    assert fb["rule_pick_board_rank"] == fb["kill_order"].index("Kaisa")
    assert fb["agree"] is (fb["rule_pick_board_rank"] == 0)
    assert fb["allies"] == ["Karma"] and fb["mode"] == "ARENA"


def test_rule_pick_not_on_the_board_has_no_rank(tmp_path, real_engine):
    det = dict(_DET, target_priority="Kill Garen first - no squishy target")
    rec = shadow.log_arena_coach(det, {}, _lc(), "arena", round_label=4,
                                 path=tmp_path / "s.jsonl", now_iso=_NOW)
    fb = rec["focus_board"]
    assert fb["rule_pick"] == "Garen"
    assert fb["rule_pick_board_rank"] is None
    assert fb["agree"] is False


def test_ds_failure_still_writes_the_whole_row(tmp_path, monkeypatch):
    def broken():
        raise ImportError("boom")
    monkeypatch.setattr(fbl, "_load_engine", broken)
    fbl._ENGINE_GATE.record_failure()        # as if the warm thread had failed
    target = tmp_path / "s.jsonl"
    rec = shadow.log_arena_coach(_DET, {}, _lc(), "arena", round_label=4,
                                 path=target, now_iso=_NOW)
    [row] = _rows(target)
    assert row == rec
    assert row["deterministic"] == _DET
    fb = row["focus_board"]
    assert fb["status"] == fbl.STATUS_UNAVAILABLE
    assert fb["board_pick"] == "" and fb["agree"] is None
    assert fb["rule_pick"] == "Kai'Sa"


def test_adapter_raising_never_drops_the_row(tmp_path, monkeypatch):
    def raising(*_a, **_k):
        raise RuntimeError("SECRET-LEAK-MARKER")
    monkeypatch.setattr(fbl, "board_for_lc", raising)
    target = tmp_path / "s.jsonl"
    rec = shadow.log_arena_coach(_DET, {}, _lc(), "arena", round_label=4,
                                 path=target, now_iso=_NOW)
    assert rec is not None and len(_rows(target)) == 1
    assert rec["focus_board"]["status"] == fbl.STATUS_ERROR
    assert "SECRET-LEAK-MARKER" not in json.dumps(rec)


def test_kill_switch_restores_the_pre_rm844_row(tmp_path, monkeypatch, real_engine):
    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    target = tmp_path / "s.jsonl"
    shadow.log_arena_coach(_DET, {}, _lc(), "arena", round_label=4,
                           path=target, now_iso=_NOW)
    [row] = _rows(target)
    assert set(row) == _PRE_RM844_KEYS


def test_lc_without_roster_never_loads_the_engine(tmp_path, monkeypatch):
    # Recording spy (a raising one would be swallowed by the fail-soft path).
    loads = []
    monkeypatch.setattr(fbl, "_load_engine", lambda: loads.append(1))
    rec = shadow.log_arena_coach(_DET, {}, {"champion": "Jinx"}, "arena",
                                 round_label=1, path=tmp_path / "s.jsonl",
                                 now_iso=_NOW)
    fbl._join_warm_for_tests(5)
    assert loads == []
    assert rec["focus_board"]["status"] == fbl.STATUS_NO_ROSTER


# -- the coach output is untouched --------------------------------------------------

def test_coach_output_byte_identical_with_and_without_the_board(
        tmp_path, monkeypatch, real_engine):
    coach, lc = _coach(), _lc()
    coach_before = json.dumps(coach, sort_keys=True)
    lc_before = copy.deepcopy(lc)

    on = tmp_path / "on.jsonl"
    shadow_log_arena_coach(coach, lc, "arena", path=on,
                           live_path=tmp_path / "missing.json")
    monkeypatch.setenv(fbl.KILL_SWITCH_ENV, "0")
    off = tmp_path / "off.jsonl"
    shadow_log_arena_coach(coach, lc, "arena", path=off,
                           live_path=tmp_path / "missing.json")

    # The served coach dict and the live summary are never mutated.
    assert json.dumps(coach, sort_keys=True) == coach_before
    assert lc == lc_before

    [row_on] = _rows(on)
    [row_off] = _rows(off)
    # The deterministic block (target_priority included) is byte-identical.
    assert (json.dumps(row_on["deterministic"], sort_keys=True)
            == json.dumps(row_off["deterministic"], sort_keys=True))
    assert row_on["deterministic"]["target_priority"].startswith("Kill ")
    assert "focus_board" not in row_off
    fb = row_on["focus_board"]
    assert fb["status"] == fbl.STATUS_OK, fb["notes"]
    assert fb["rule_pick"] == shadow._rule_pick(
        row_on["deterministic"]["target_priority"])
    assert fb["board_pick"]
