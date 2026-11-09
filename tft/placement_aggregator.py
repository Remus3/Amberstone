"""
tft/placement_aggregator.py - Positional heatmap builder for TFT units.

Reads the TFT rating JSON files in data/ratings/ that carry
tft_unit_positions (or the legacy tft_unit_placement string), aggregates
placement frequency per unit per board cell, and writes
data/placement_heatmap.json.

Scope, measured 2026-11-09: since the 2026-04-27 unification
(performance_tracker.py, the comment above RATINGS_DIR) data/ratings/ holds
one last_<mode>.json per mode, not one file per game, so the aggregate
covers the latest TFT game plus any leftover TFT-category file there
(for example a pre-unification last_game_rating.json). A rating written under RC_ACCOUNT_ID
lives one directory deeper and is not read here. Lane filing S144-T-661.

Called from performance_tracker._tft_heatmap after a TFT rating is saved.
The ratings files are RC-authored, but a unit name and cell come from the
model's UnitPlacement line (tft/tft_live_analysis.py), so every file, field
and cell is validated here and a malformed one is skipped, never fatal to
the whole build.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from core.polled_json import atomic_write_json

logger = logging.getLogger("rc.tft.heatmap")

_ROOT = Path(__file__).parent.parent
_RATINGS_DIR = _ROOT / "data" / "ratings"
_HEATMAP_FILE = _ROOT / "data" / "placement_heatmap.json"

_ROW_MAP = {"A": 4, "B": 3, "C": 2, "D": 1}
# The board is 4 rows (A-D) by 7 columns (1-7).
_CELL_RE = re.compile(r"[A-D][1-7]")
_SENTINELS = frozenset({"", "-", "n/a", "none"})
# A unit name (two characters or more), whitespace, a row letter and ONE column digit not followed by
# another digit ("D10" is off the board, never read as "D1"). The name may
# hold an apostrophe (Cho'Gath), an ampersand (Nunu & Willump), a dot
# (Dr. Mundo), a hyphen and spaces.
_PLACEMENT_RE = re.compile(r"([A-Za-z][A-Za-z'&. \-]+?)\s+([A-Da-d])([0-9])(?![0-9])")


def parse_unit_placement(text) -> dict:
    """
    Parse a placement string like "Karma D3, Jhin D6, Cho'Gath A1" into
    {unit_name: cell} with cell a "<row><col>" string, e.g. {"Karma": "D3"}.
    A non-string, a sentinel ("-", "N/A", "none") or an off-board cell
    yields no entry.
    """
    positions = {}
    if not isinstance(text, str) or text.strip().lower() in _SENTINELS:
        return positions
    for m in _PLACEMENT_RE.finditer(text):
        name = m.group(1).strip(" ,.")
        row = m.group(2).upper()
        col = int(m.group(3))
        if name and row in _ROW_MAP and 1 <= col <= 7:
            positions[name] = f"{row}{col}"
    return positions


def _valid_positions(raw) -> dict:
    """Keep only {non-blank str name: on-board cell} pairs from a stored
    tft_unit_positions value; anything else (a list, a string, a junk cell)
    contributes nothing."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for unit, cell in raw.items():
        if not isinstance(unit, str) or not unit.strip():
            continue
        if not isinstance(cell, str):
            continue
        norm = cell.strip().upper()
        if _CELL_RE.fullmatch(norm):
            out[unit.strip()] = norm
    return out


def _read_rating(f: Path):
    """The parsed body of one rating file, or None when it cannot be read.
    Only a file-read or decode failure is expected here; it is logged with
    the file's name and the file is skipped."""
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("placement heatmap: skipped unreadable rating file %s: %s",
                       f.name, type(exc).__name__)
        return None


def build_heatmap(ratings_dir: Path | None = None) -> dict:
    """
    Read every rating JSON file in ratings_dir (default: the module's
    _RATINGS_DIR, resolved at call time) that is a TFT rating with unit
    positions and aggregate them into a frequency map per unit per cell.
    Returns the heatmap dict (also suitable for direct JSON dump).
    """
    if ratings_dir is None:
        ratings_dir = _RATINGS_DIR
    ratings_dir = Path(ratings_dir)
    # unit -> cell -> count
    freq: dict = defaultdict(lambda: defaultdict(int))
    games_seen = 0
    per_unit_games: dict = defaultdict(int)

    for f in sorted(ratings_dir.glob("*.json")):
        d = _read_rating(f)
        if not isinstance(d, dict) or d.get("mode_category") != "TFT":
            continue

        positions = _valid_positions(d.get("tft_unit_positions"))
        if not positions:
            # Fall back to the legacy tft_unit_placement string.
            positions = parse_unit_placement(d.get("tft_unit_placement"))
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
        ranked = sorted(cells.items(), key=lambda x: -x[1])
        cell_data = {
            cell: {"count": count, "pct": round(count / total * 100, 1)}
            for cell, count in ranked
        }
        result_positions[unit] = {
            "cells": cell_data,
            # Most frequent cell; a tie goes to the first one seen.
            "top_cell": ranked[0][0] if ranked else None,
            "games": total,
        }

    return {
        "version": 2,
        "games_counted": games_seen,
        "last_updated": datetime.now().isoformat(timespec="seconds"),
        "positions": result_positions,
    }


def update_heatmap(ratings_dir: Path | None = None,
                   heatmap_file: Path | None = None) -> int:
    """
    Build the heatmap from ratings_dir and write it atomically to
    heatmap_file (defaults: the module's _RATINGS_DIR and _HEATMAP_FILE,
    resolved at call time). Returns the number of games counted.
    """
    if ratings_dir is None:
        ratings_dir = _RATINGS_DIR
    if heatmap_file is None:
        heatmap_file = _HEATMAP_FILE
    ratings_dir = Path(ratings_dir)
    ratings_dir.mkdir(parents=True, exist_ok=True)
    heatmap = build_heatmap(ratings_dir)
    atomic_write_json(Path(heatmap_file), heatmap)
    n = heatmap["games_counted"]
    logger.info("Placement heatmap updated: %d games, %d units tracked",
                n, len(heatmap["positions"]))
    return n


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = update_heatmap()
    print(f"Heatmap built from {n} TFT games -> {_HEATMAP_FILE}")
