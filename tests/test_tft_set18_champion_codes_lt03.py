"""LT-03 (session 134): the Set 18 team-planner code map.

data/meta/tft_set18_champion_codes.json was read 2026-10-25 from the local
League client in a live Set 18 lobby by scripts/discover_champion_codes.py's
passive path: GET /lol-tft-team-planner/v1/previous-context ("setId":
"TFTSet18") and GET /lol-game-data/assets/v1/tftchampions-teamplanner.json
(display_name + team_planner_code per unit). No POST / PUT / PATCH / DELETE.

Cross-checks measured at capture: 65 units, 65 distinct codes 1001-1085;
every name is in the CommunityDragon Set 18 roster (the roster's other 9
entries are the "Lux (<trait>)" variants the planner shows as one "Lux");
every planner tier equals that unit's CommunityDragon cost. The same
game-data table agrees with the legacy-probe Set 17 file on 63 of its 64
units (only Morgana differs: file 0, game data 88).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import discover_champion_codes as dcc
from tft import tft_set

REPO_ROOT = Path(__file__).resolve().parent.parent
CODES = REPO_ROOT / "data" / "meta" / "tft_set18_champion_codes.json"

# Spot values read from the live client 2026-10-25.
MEASURED = {
    "Ahri": 1001, "Elder Dragon": 1020, "Gromp": 1026, "Kha'Zix": 1036,
    "Kobuko": 1085, "Lux": 1029, "Yunara": 1083, "Zyra": 1084,
}


def _doc() -> dict:
    return json.loads(CODES.read_bytes().decode("utf-8"))


def test_set18_codes_file_is_a_flat_name_to_int_map():
    doc = _doc()
    assert isinstance(doc, dict) and len(doc) == 65
    assert all(isinstance(k, str) and k and type(v) is int for k, v in doc.items())
    assert len(set(doc.values())) == len(doc), "two units share a code"
    assert min(doc.values()) == 1001 and max(doc.values()) == 1085


def test_set18_codes_bytes_are_the_script_format():
    raw = CODES.read_bytes()
    assert b"\r" not in raw and all(b < 0x80 for b in raw)
    assert raw == dcc.encode(_doc())


def test_set18_measured_spot_values():
    doc = _doc()
    assert {k: doc.get(k) for k in MEASURED} == MEASURED


def test_set18_codes_cover_the_cdragon_roster_except_lux_variants():
    roster = set(tft_set.roster(18, root=REPO_ROOT))
    names = set(_doc())
    assert len(roster) >= 60  # anchored: an empty roster cannot pass
    assert names <= roster, sorted(names - roster)
    rest = roster - names
    assert rest and all(n.startswith("Lux (") for n in rest), sorted(rest)


def test_codes_path_names_the_set_file(tmp_path):
    assert dcc.codes_path("TFTSet18", tmp_path) == (
        tmp_path / "data" / "meta" / "tft_set18_champion_codes.json")
    with pytest.raises(ValueError):
        dcc.codes_path("TFTSet", tmp_path)


def test_codes_from_game_data_reads_one_set():
    table = {
        "TFTSet17": [{"display_name": "Jinx", "team_planner_code": 18}],
        "TFTSet18": [{"display_name": "Ahri", "team_planner_code": 1001},
                     {"display_name": "Zyra", "team_planner_code": 1084}],
    }
    assert dcc.codes_from_game_data(table, "TFTSet18") == {"Ahri": 1001, "Zyra": 1084}


@pytest.mark.parametrize("table", [
    {},
    {"TFTSet18": []},
    {"TFTSet18": [{"display_name": "Ahri", "team_planner_code": "1001"}]},
    {"TFTSet18": [{"display_name": "", "team_planner_code": 1}]},
    {"TFTSet18": [{"display_name": "Ahri", "team_planner_code": 1001},
                  {"display_name": "Ahri", "team_planner_code": 1002}]},
], ids=["no-set", "empty-set", "str-code", "blank-name", "name-two-codes"])
def test_codes_from_game_data_refuses_bad_tables(table):
    with pytest.raises(ValueError):
        dcc.codes_from_game_data(table, "TFTSet18")


class _GetOnlyLcu:
    """Records every call; any non-GET verb fails the test."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, ep):
        self.calls.append(ep)
        return 200, json.dumps(self.routes[ep])

    def request(self, method, ep, body=None):
        raise AssertionError(f"passive path issued {method} {ep}")


def test_passive_path_issues_only_gets_and_writes_atomically(tmp_path):
    lcu = _GetOnlyLcu({
        dcc.PLANNER_CONTEXT: {"optionalTeamId": "", "setId": "TFTSet18"},
        dcc.PLANNER_GAME_DATA: {"TFTSet18": [
            {"display_name": "Kobuko", "team_planner_code": 1085}]},
    })
    assert dcc.passive(lcu, None, tmp_path, dry_run=False) == 0
    assert lcu.calls == [dcc.PLANNER_CONTEXT, dcc.PLANNER_GAME_DATA]
    out = tmp_path / "data" / "meta" / "tft_set18_champion_codes.json"
    assert json.loads(out.read_bytes()) == {"Kobuko": 1085}
    assert sorted(p.name for p in out.parent.iterdir()) == [out.name]


def test_passive_dry_run_writes_nothing(tmp_path):
    lcu = _GetOnlyLcu({
        dcc.PLANNER_CONTEXT: {"setId": "TFTSet17"},
        dcc.PLANNER_GAME_DATA: {"TFTSet17": [
            {"display_name": "Jinx", "team_planner_code": 18}]},
    })
    assert dcc.passive(lcu, None, tmp_path, dry_run=True) == 0
    assert not (tmp_path / "data").exists()
