"""Append-only DS pick calibration log.

Called from coaches after rank_for() runs so each coaching cycle produces one
entry in data/ds_calibration.jsonl. At calibration time (Stage 5) the log is
joined against rewind_history.db on (champion, mode, approximate timestamp) to
compare DS-recommended items vs. actually purchased items vs. win/loss outcome.

One entry per coaching tick (~30s cadence). The calibration analysis script
uses the last entry per game (largest owned_items list) for the final-build
comparison. Non-fatal: any write failure is silently swallowed so calibration
logging never breaks coach operation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_LOG_PATH = Path(__file__).parent.parent / "data" / "ds_calibration.jsonl"


def log_ds_run(
    champion: str,
    mode: str,
    level: int,
    owned_items: list,
    ds_picks: list,
    game_id: str = "",
) -> None:
    """Append one DS observation to the calibration log.

    Args:
        champion:    champion name (e.g. "Ahri")
        mode:        coaching mode string (e.g. "ARAM", "SR", "ARENA", "BRAWL")
        level:       current champion level
        owned_items: item IDs currently in inventory (list of str or int)
        ds_picks:    list of dicts with keys item_id, item_name, delta_dps, gold
        game_id:     optional Riot match/game id for exact cross-reference
    """
    entry = {
        "ts": time.time(),
        "champion": champion,
        "mode": mode,
        "level": level,
        "owned_items": [str(i) for i in owned_items],
        "ds_picks": ds_picks,
        "game_id": game_id,
    }
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
