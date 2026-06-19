"""
tft/placement_aggregator.py - Positional heatmap builder for TFT units.

Reads all completed game ratings from data/ratings/*.json that contain
tft_unit_positions, aggregates placement frequency per unit per board cell,
and writes data/placement_heatmap.json.

Called from app.py on game end (after save_tft_rating).
"""
import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("rc.tft.heatmap")

_ROOT = Path(__file__).parent.parent
_RATINGS_DIR = _ROOT / "data" / "ratings"
_HEATMAP_FILE = _ROOT / "data" / "placement_heatmap.json"

_ROW_MAP = {"A": 4, "B": 3, "C": 2, "D": 1}


def parse_unit_placement(text: str) -> dict:
    """
    Parse placement string like "Karma D3, Jhin D6, Cho'Gath A1" into
    {unit_name: (row_letter, col_int)} dict.
    """
    positions = {}
    if not text or text in ("-", "N/A", "none"):
        return positions
    for m in re.finditer(
        r"([A-Za-z][A-Za-z''& \-]+?)\s+([A-Da-d])(\d)", text
    ):
        name = m.group(1).strip(" ,.")
        row  = m.group(2).upper()
        col  = int(m.group(3))
        if name and row in _ROW_MAP and 1 <= col <= 7:
            positions[name] = f"{row}{col}"
    return positions


def build_heatmap(ratings_dir: Path = _RATINGS_DIR) -> dict:
    """
    Read all rating JSON files that have tft_unit_positions and aggregate
    into a frequency map per unit per board cell.
    Returns the heatmap dict (also suitable for direct JSON dump).
    """
    # unit -> cell -> count
    freq: dict = defaultdict(lambda: defaultdict(int))
    games_seen = 0
    per_unit_games: dict = defaultdict(int)

    for f in sorted(ratings_dir.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue

        if d.get("mode_category") != "TFT":
            continue

        positions = d.get("tft_unit_positions", {})
        if not positions:
            # Try to parse from tft_unit_placement string (legacy)
            raw = d.get("tft_unit_placement", "")
            if raw:
                positions = parse_unit_placement(raw)

        if not positions:
            continue

        games_seen += 1
        for unit, cell in positions.items():
            freq[unit][cell] += 1
            per_unit_games[unit] += 1

    # Convert to percentage + ranked positions
    result_positions = {}
    for unit, cells in freq.items():
        total = per_unit_games[unit]
        cell_data = {}
        for cell, count in sorted(cells.items(), key=lambda x: -x[1]):
            cell_data[cell] = {
                "count": count,
                "pct": round(count / total * 100, 1),
            }
        # Top position = most frequent cell
        top_cell = max(cells, key=cells.get) if cells else None
        result_positions[unit] = {
            "cells": cell_data,
            "top_cell": top_cell,
            "games": total,
        }

    return {
        "version": 2,
        "games_counted": games_seen,
        "last_updated": datetime.now().isoformat(timespec="seconds"),
        "positions": result_positions,
    }


def update_heatmap() -> int:
    """
    Build heatmap from all ratings and write to placement_heatmap.json.
    Returns number of games processed.
    """
    _RATINGS_DIR.mkdir(parents=True, exist_ok=True)
    heatmap = build_heatmap()
    tmp = _HEATMAP_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(heatmap, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_HEATMAP_FILE)
    n = heatmap["games_counted"]
    logger.info("Placement heatmap updated: %d games, %d units tracked",
                n, len(heatmap["positions"]))
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = update_heatmap()
    print(f"Heatmap built from {n} TFT games -> {_HEATMAP_FILE}")
