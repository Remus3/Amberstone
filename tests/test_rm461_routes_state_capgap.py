"""RM-461 (4) - ``_capgap_shadow_eval`` enemy ``championName`` type check.

The enemy list was built with ``str(p.get("championName") or "")`` guarded
only by truthiness, so a wrong-type name was STRINGIFIED rather than
refused: ``5`` became "5", ``True`` became "True", ``["Zed"]`` became
"['Zed']", and each was handed to ``build_capability_gap`` as an enemy
champion. ``_resolve_my_champion`` (RM-456) already routes the operator's
own name through the module's ``_as_str``; the enemy read now does the same,
so a non-string name is skipped and a valid string is forwarded unchanged.

JS consumers: none. ``_capgap_shadow_eval`` feeds only the default-OFF
capability-gap shadow log; it is not emitted in /api/state.
"""
from __future__ import annotations

from unittest import mock

import pytest

from dashboard import routes_state as rs

_NON_STR = [5, 1.5, True, ["Zed"], {"n": "Zed"}]
_NON_STR_IDS = ["int", "float", "bool", "list", "dict"]


def _data(enemy_names):
    players = [{"summonerName": "Me", "championName": "Ashe", "team": "ORDER"}]
    players += [{"summonerName": f"E{i}", "championName": n, "team": "CHAOS"}
                for i, n in enumerate(enemy_names)]
    return {"activePlayer": {"summonerName": "Me"}, "allPlayers": players}


def _enemies_passed(data):
    calls = []

    def fake(my_champ, enemies, mode="SR"):
        calls.append((my_champ, list(enemies), mode))
        return {"applies": True}

    with mock.patch("core.ds_capability_gap.build_capability_gap", fake):
        res = rs._capgap_shadow_eval(data)
    assert res == {"applies": True}
    assert len(calls) == 1
    assert calls[0][0] == "Ashe"
    return calls[0][1]


@pytest.mark.parametrize("bad", _NON_STR, ids=_NON_STR_IDS)
def test_non_string_enemy_name_is_skipped_not_stringified(bad):
    assert _enemies_passed(_data(["Zed", bad, "Lux"])) == ["Zed", "Lux"]


@pytest.mark.parametrize("empty", [None, "", 0, False, []],
                         ids=["None", "empty", "zero", "False", "emptylist"])
def test_missing_or_falsey_enemy_name_still_skipped(empty):
    assert _enemies_passed(_data(["Zed", empty])) == ["Zed"]


def test_well_formed_enemy_names_unchanged():
    assert _enemies_passed(_data(["Zed", "Lux", "Kai'Sa"])) == ["Zed", "Lux", "Kai'Sa"]
