"""tft/engine/compare.py - board power compare (docs/TFT_PROGRAM.md section 1.4
category 17, section 5 output 4): own board versus the opponent faced, and
versus every opponent's last-seen board.

Power dimensions, all derived from the boards and set game data:
  units            units on the board
  star_cost        gold value: sum of cost x 3^(star - 1) (a 2-star 4-cost = 12)
  completed_items  items that are not loose components (crafted, emblems, other)
  trait_tiers      sum of the active trait tiers (active_traits counts them)
plus "contested": the unit apiNames both boards hold. No fight simulation
(ADR-018 non-goal) and no verdict beyond which side leads on each dimension.

A board is a list / tuple of unit rows or comps.Unit values; anything else is
an empty board. A raw row goes through comps.normalize_unit, but a Unit is
handed back unchecked, so every Unit field read here is checked here: a junk
api drops the unit, a junk star counts as 1 (and never past MAX_STAR), a junk
or negative cost falls back to the set data's (no cost = no gold value) and
only text item entries count. Never raises on junk boards or player keys.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from tft.engine import engine_meta
from tft.engine.comps import MAX_STAR, SetData, Unit, _key_text, as_int, board_traits, copies, normalize_unit

DIMENSIONS = ("units", "star_cost", "completed_items", "trait_tiers")
TOP_TRAITS = 3


def _non_negative(value) -> Optional[int]:
    n = as_int(value)
    return n if n is not None and n >= 0 else None


def _checked(unit: Unit, setdata: SetData) -> Optional[Unit]:
    if not isinstance(unit.api, str) or not unit.api.strip():
        return None
    star = min(MAX_STAR, max(1, as_int(unit.star) or 1))
    cost = _non_negative(unit.cost)
    if cost is None:
        cost = _non_negative(setdata.unit_cost(unit.api))
    raw_items = unit.items if isinstance(unit.items, (list, tuple)) else ()
    items = tuple(i for i in raw_items if isinstance(i, str) and i)
    return Unit(api=unit.api, star=star, items=items, cost=cost)


def board_units(board: Any, setdata: SetData) -> tuple:
    """The board's units, each field checked (see the module header); never truth-tests the board."""
    if not isinstance(board, (list, tuple)):
        return ()
    out = []
    for raw in board:
        unit = normalize_unit(raw, setdata)
        checked = _checked(unit, setdata) if unit is not None else None
        if checked is not None:
            out.append(checked)
    return tuple(out)


def _power(units: tuple, setdata: SetData) -> dict:
    active = [t for t in board_traits(units, setdata) if t.active]
    items = [i for unit in units for i in unit.items]
    return {
        "units": len(units),
        "star_cost": sum((unit.cost or 0) * copies(unit.star) for unit in units),
        "completed_items": sum(1 for i in items if setdata.item_kind(i) != "component"),
        "components": sum(1 for i in items if setdata.item_kind(i) == "component"),
        "active_traits": len(active),
        "trait_tiers": sum(t.tier for t in active),
        "top_traits": [{"trait": t.trait, "count": t.count, "tier": t.tier} for t in active[:TOP_TRAITS]],
    }


def board_power(board: Any, setdata: SetData) -> dict:
    return _power(board_units(board, setdata), setdata)


def _compare_units(mine_units: tuple, theirs_units: tuple, setdata: SetData) -> dict:
    mine, theirs = _power(mine_units, setdata), _power(theirs_units, setdata)
    delta = {d: mine[d] - theirs[d] for d in DIMENSIONS}
    leads = {"own": [d for d in DIMENSIONS if delta[d] > 0],
             "other": [d for d in DIMENSIONS if delta[d] < 0],
             "even": [d for d in DIMENSIONS if delta[d] == 0]}
    contested = {u.api for u in mine_units} & {u.api for u in theirs_units}
    return dict(engine_meta(), own=mine, other=theirs, delta=delta, leads=leads,
                contested=sorted(contested))


def compare_boards(own: Any, other: Any, setdata: SetData) -> dict:
    return _compare_units(board_units(own, setdata), board_units(other, setdata), setdata)


def compare_lobby(own: Any, others: Any, setdata: SetData) -> list:
    """compare_boards against each opponent, strongest (star_cost) first.

    others = {player_key: board}; a plain list of boards is keyed by its index.
    Every row's player_key is text (an int too long for decimal is "int:0x...").
    """
    if isinstance(others, (list, tuple)):
        others = {str(i): board for i, board in enumerate(others)}
    if not isinstance(others, Mapping):
        return []
    mine = board_units(own, setdata)
    rows = []
    for key in sorted(others, key=_key_text):
        row = _compare_units(mine, board_units(others[key], setdata), setdata)
        row["player_key"] = _key_text(key)
        rows.append(row)
    rows.sort(key=lambda r: (-r["other"]["star_cost"], r["player_key"]))
    return rows
