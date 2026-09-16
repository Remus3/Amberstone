"""RM-417 field 1 of N - ``arena_teams()`` member ``championId``.

RM-313 coerced ``championId`` in ``_team_picks`` only. ``arena_teams`` still
forwarded ``m.get("championId", 0)`` verbatim, so on an LCU build that emits
champ-select ids as JSON strings the RM-313 repair was PARTIAL: the Arena
pane reads ``arena_teams[].cells[]`` first and only falls back to ``my_team``.

JS consumer census for THIS field (web/js/panels/champ_select.js, Arena pane
and Arena enemies column), grepped before the flip:
  * ``(c && c.championId) === myCid`` where ``myCid = cs.my_champion | 0`` is
    always an int - UNSAFE ON STRING (a string id never matches, so the
    wrong cell is badged as ME). Repaired by the coercion.
  * ``!c.championId`` empty-cell gates (two sites) - the STRING "0" is
    truthy, so a no-pick read as a pick. Repaired by the coercion.
  * ``_csChampName(c.championId)`` and ``CHAMPS.byId[String(c.championId)]``
    - type-neutral.
No consumer compares this field against a string, so no consumer is broken
by emitting an int.

Acceptance (per the row): route through the module's existing ``_as_int``
preserving the ``0`` default; every emitted id is an int for a string-typed
session; a well-formed session's values are UNCHANGED.
"""
from __future__ import annotations

import pytest

from lcu.champ_select_shape import arena_teams


def _session(champ_ids, local_cell=0):
    members = [{"cellId": i, "championId": cid} for i, cid in enumerate(champ_ids)]
    return {
        "localPlayerCellId": local_cell,
        "additionalSubteamData": [
            {"subteamId": 1, "name": "Team 1", "members": members[:3]},
            {"subteamId": 2, "name": "Team 2", "members": members[3:]},
        ],
    }


def _champ_ids(out):
    return [c["championId"] for t in out for c in t["cells"]]


def test_string_typed_session_emits_int_ids():
    out = arena_teams(_session(["67", "0", "103", "22", "0", "1"]))
    ids = _champ_ids(out)
    assert ids == [67, 0, 103, 22, 0, 1]
    assert all(type(i) is int for i in ids)


@pytest.mark.parametrize("bad", [None, "", "nan", "abc", [67], {"id": 67}],
                         ids=["None", "empty", "nan", "abc", "list", "dict"])
def test_unparseable_id_degrades_to_the_zero_default(bad):
    out = arena_teams(_session([bad, 67, 0, 0, 0, 0]))
    assert _champ_ids(out)[0] == 0
    assert _champ_ids(out)[1] == 67


def test_absent_id_keeps_the_zero_default():
    sess = _session([67, 0, 0, 0, 0, 0])
    del sess["additionalSubteamData"][0]["members"][0]["championId"]
    assert _champ_ids(arena_teams(sess))[0] == 0


def test_well_formed_session_values_unchanged():
    sess = _session([67, 0, 103, 22, 0, 1], local_cell=4)
    out = arena_teams(sess)
    assert _champ_ids(out) == [67, 0, 103, 22, 0, 1]
    assert [t["is_me"] for t in out] == [False, True]
    assert [c["cellId"] for t in out for c in t["cells"]] == [0, 1, 2, 3, 4, 5]
