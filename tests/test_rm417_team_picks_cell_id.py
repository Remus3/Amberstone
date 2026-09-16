"""RM-417 field 2 of N - ``_team_picks`` ``cellId`` (my_team / their_team).

``_team_picks`` emitted ``p.get("cellId")`` verbatim while the SAME module
already coerces ``localPlayerCellId`` to an int. On an LCU build that emits
champ-select ids as JSON strings, every strict comparison of a team cell
against the int ``local_cell`` failed.

JS consumer census for THIS field, grepped before the flip:
  * web/js/panels/champ_select.js active-round border:
    ``typeof p.cellId === "number"`` - a string cellId never painted the
    border. Repaired by the coercion.
  * champ_select.js role lookup and cleanse-advisory spell lookup:
    ``p.cellId === cs.local_cell`` / ``p.cellId === myCell`` where
    ``local_cell`` is always an int - UNSAFE ON STRING, repaired.
  * web/js/panels/ds_matchup.js: ``p.cellId != null && p.cellId ===
    cs.local_cell`` - same, repaired.
  * champ_select.js hover cache key ``p.cellId|0`` - type-neutral.
No consumer compares this field against a string. Python readers that match
on ``cellId`` read the RAW LCU session, not this shaped payload.

DEFAULT: absent or unparseable stays ``None``, NOT 0. Cell 0 is a real cell
(the first player), and the JS consumers guard with ``!= null`` /
``typeof === "number"``; defaulting to 0 would make a malformed row match
the local player whenever the local cell is 0.
"""
from __future__ import annotations

import pytest

from lcu.champ_select_shape import _team_picks, shape_champ_select


def _team(cells):
    return [{"cellId": c, "championId": 67, "puuid": f"p{i}"}
            for i, c in enumerate(cells)]


def test_string_typed_session_emits_int_cell_ids():
    out = _team_picks(_team(["0", "1", "4"]), local_cell=1)
    assert [p["cellId"] for p in out] == [0, 1, 4]
    assert all(type(p["cellId"]) is int for p in out)


def test_string_typed_session_through_the_shaper_matches_local_cell():
    sess = {"localPlayerCellId": "3", "myTeam": _team(["3", "4"]),
            "theirTeam": _team(["5", "6"]), "actions": []}

    def request(method, path, body=None):
        return (sess if "champ-select" in path else {}), None

    cs = shape_champ_select(request, "ChampSelect")["champ_select"]
    mine = [p for p in cs["my_team"] if p["cellId"] == cs["local_cell"]]
    assert len(mine) == 1
    assert all(type(p["cellId"]) is int for p in cs["my_team"] + cs["their_team"])


@pytest.mark.parametrize("bad", [None, "", "nan", "abc", [1], {"c": 1}],
                         ids=["None", "empty", "nan", "abc", "list", "dict"])
def test_unparseable_cell_id_is_none_not_zero(bad):
    out = _team_picks(_team([bad, 2]), local_cell=0)
    assert out[0]["cellId"] is None
    assert out[1]["cellId"] == 2


def test_absent_cell_id_stays_none():
    team = _team([0])
    del team[0]["cellId"]
    assert _team_picks(team)[0]["cellId"] is None


def test_well_formed_session_values_unchanged():
    out = _team_picks(_team([0, 1, 2, 3, 4]), local_cell=2)
    assert [p["cellId"] for p in out] == [0, 1, 2, 3, 4]
    assert [p["summonerName"] for p in out] == [
        "Ally 1", "Ally 2", "You", "Ally 4", "Ally 5"]
    assert [p["championId"] for p in out] == [67] * 5
