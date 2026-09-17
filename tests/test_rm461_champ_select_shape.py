"""RM-461 (3) - champ-select cell ids RM-417 / RM-456 did not reach.

``trades[].cellId``, ``swap_entries`` (``position_swaps`` /
``pick_order_swaps``) ``cellId`` and ``active_round`` ``actorCellId`` were
forwarded uncoerced, while ``my_team`` / ``their_team`` / ``arena_teams``
cellIds already go through ``_as_int(value, None)``.

Rule (RM-417 per-field, RM-456 bool decision): route through the module's
own ``_as_int`` with default None. A missing or uncoercible cell stays None,
NEVER 0 (cell 0 is a real player), and a bool is refused (True is not
cell 1). Valid int cells, including 0, are unchanged.

JS consumer census (web/js + web/legacy_index.html), grepped first:
  * ``active_round.cell_ids``: champ_select.js builds
    ``new Set(cs.active_round.cell_ids)`` and tests
    ``cellSet.has(peerCellId)`` where ``peerCellId`` is ``p.cellId`` only when
    ``typeof === "number"``. Set.has is SameValueZero, so a string "3" never
    matched the int 3 from my_team - coercion makes it match. A None cell
    is dropped from the list, exactly as a null actorCellId already was.
    The list is also joined into a render-dedupe key; ints join the same.
  * ``trades`` / ``position_swaps`` / ``pick_order_swaps``: no JS or Python
    reader of the SHAPED lists (tools/lcu_agent.py swap handlers re-GET the
    raw session). The type contract is aligned with my_team for consistency.
"""
from __future__ import annotations

import math

import pytest

from lcu.champ_select_shape import active_round, shape_champ_select, swap_entries

_BAD = [None, True, False, "abc", "", 1.5j, float("nan"), math.inf, [3], {"c": 3}]
_BAD_IDS = ["None", "True", "False", "abc", "empty", "complex", "nan", "inf",
            "list", "dict"]


def _shape(sess, queue_id=420):
    sess = {"localPlayerCellId": 0, "gameData": {"queue": {"id": queue_id}},
            **sess}

    def request(method, path):
        if path == "/lol-champ-select/v1/session":
            return sess, None
        return {}, None

    return shape_champ_select(request, "ChampSelect")["champ_select"]


# --- swap_entries -------------------------------------------------------

@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_swap_entry_bad_cell_is_none_not_zero(bad):
    out = swap_entries([{"id": 4, "cellId": bad, "state": "AVAILABLE"}])
    assert out == [{"id": 4, "cellId": None, "state": "AVAILABLE"}]


def test_swap_entry_absent_cell_stays_none():
    assert swap_entries([{"id": 4, "state": "SENT"}]) == [
        {"id": 4, "cellId": None, "state": "SENT"}]


@pytest.mark.parametrize("v,expect", [(0, 0), (4, 4), ("3", 3), (2.0, 2)],
                         ids=["zero", "int", "numeric-str", "float"])
def test_swap_entry_coercible_cell(v, expect):
    out = swap_entries([{"id": 1, "cellId": v, "state": "SENT"}])
    assert out[0]["cellId"] == expect
    assert type(out[0]["cellId"]) is int


@pytest.mark.parametrize("key", ["positionSwaps", "pickOrderSwaps"])
def test_swap_lists_in_shape_are_coerced(key):
    dst = "position_swaps" if key == "positionSwaps" else "pick_order_swaps"
    cs = _shape({key: [{"id": 1, "cellId": "2", "state": "AVAILABLE"},
                       {"id": 2, "cellId": True, "state": "AVAILABLE"}]})
    assert cs[dst] == [{"id": 1, "cellId": 2, "state": "AVAILABLE"},
                       {"id": 2, "cellId": None, "state": "AVAILABLE"}]


# --- trades -------------------------------------------------------------

@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_trade_bad_cell_is_none_not_zero(bad):
    cs = _shape({"trades": [{"id": 9, "cellId": bad, "state": "AVAILABLE"}]})
    assert cs["trades"] == [{"id": 9, "cellId": None, "state": "AVAILABLE"}]


def test_trade_absent_cell_stays_none():
    cs = _shape({"trades": [{"id": 9, "state": "BUSY"}]})
    assert cs["trades"] == [{"id": 9, "cellId": None, "state": "BUSY"}]


@pytest.mark.parametrize("v,expect", [(0, 0), (5, 5), ("4", 4)],
                         ids=["zero", "int", "numeric-str"])
def test_trade_coercible_cell(v, expect):
    cs = _shape({"trades": [{"id": 9, "cellId": v, "state": "AVAILABLE"}]})
    assert cs["trades"][0]["cellId"] == expect
    assert type(cs["trades"][0]["cellId"]) is int


# --- active_round -------------------------------------------------------

def _actions(*cells, kind="pick"):
    return {"actions": [[{"actorCellId": c, "type": kind, "isInProgress": True}
                         for c in cells]]}


@pytest.mark.parametrize("bad", _BAD, ids=_BAD_IDS)
def test_active_round_bad_actor_cell_is_dropped_not_zero(bad):
    out = active_round(_actions(bad, 3))
    assert out == {"type": "pick", "cell_ids": [3]}


def test_active_round_string_cells_emit_ints():
    out = active_round(_actions("0", "4", kind="ban"))
    assert out == {"type": "ban", "cell_ids": [0, 4]}
    assert all(type(c) is int for c in out["cell_ids"])


def test_active_round_absent_actor_cell_dropped():
    sess = {"actions": [[{"type": "pick", "isInProgress": True},
                         {"actorCellId": 2, "type": "pick", "isInProgress": True}]]}
    assert active_round(sess) == {"type": "pick", "cell_ids": [2]}


def test_active_round_all_bad_cells_keeps_round_with_empty_list():
    # Same as today's all-null case: the round type is still known.
    assert active_round(_actions(None, "x")) == {"type": "pick", "cell_ids": []}


def test_well_formed_payload_unchanged_including_cell_zero():
    cs = _shape({
        **_actions(0, 5),
        "trades": [{"id": 9, "cellId": 0, "state": "AVAILABLE"}],
        "positionSwaps": [{"id": 1, "cellId": 5, "state": "SENT"}],
        "pickOrderSwaps": [{"id": 2, "cellId": 0, "state": "RECEIVED"}],
    })
    assert cs["active_round"] == {"type": "pick", "cell_ids": [0, 5]}
    assert cs["trades"] == [{"id": 9, "cellId": 0, "state": "AVAILABLE"}]
    assert cs["position_swaps"] == [{"id": 1, "cellId": 5, "state": "SENT"}]
    assert cs["pick_order_swaps"] == [{"id": 2, "cellId": 0, "state": "RECEIVED"}]
