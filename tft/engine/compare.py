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
"""
from __future__ import annotations

from typing import Any, Mapping

from tft.engine import engine_meta
from tft.engine.comps import SetData, as_units, board_traits, copies

DIMENSIONS = ("units", "star_cost", "completed_items", "trait_tiers")
TOP_TRAITS = 3


def board_power(board: Any, setdata: SetData) -> dict:
    units = as_units(board or [], setdata)
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


def compare_boards(own: Any, other: Any, setdata: SetData) -> dict:
    mine, theirs = board_power(own, setdata), board_power(other, setdata)
    delta = {d: mine[d] - theirs[d] for d in DIMENSIONS}
    leads = {"own": [d for d in DIMENSIONS if delta[d] > 0],
             "other": [d for d in DIMENSIONS if delta[d] < 0],
             "even": [d for d in DIMENSIONS if delta[d] == 0]}
    own_apis = {u.api for u in as_units(own or [], setdata)}
    other_apis = {u.api for u in as_units(other or [], setdata)}
    return dict(engine_meta(), own=mine, other=theirs, delta=delta, leads=leads,
                contested=sorted(own_apis & other_apis))


def compare_lobby(own: Any, others: Mapping, setdata: SetData) -> list:
    """compare_boards against each opponent, strongest (star_cost) first."""
    rows = []
    for key in sorted(others or {}, key=str):
        row = compare_boards(own, others[key], setdata)
        row["player_key"] = key
        rows.append(row)
    rows.sort(key=lambda r: (-r["other"]["star_cost"], str(r["player_key"])))
    return rows
