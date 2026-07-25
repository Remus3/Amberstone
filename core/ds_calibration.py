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
    match_key: str = "",
) -> None:
    """Append one DS observation to the calibration log.

    Args:
        champion:    champion name (e.g. "Ahri")
        mode:        coaching mode string (e.g. "ARAM", "SR", "ARENA", "BRAWL")
        level:       current champion level
        owned_items: item IDs currently in inventory (list of str or int)
        ds_picks:    list of dicts with keys item_id, item_name, delta_dps, gold
        game_id:     optional Riot match/game id for exact cross-reference
        match_key:   stable per-match key from ``core.live_metrics.match_key``
                     (D-01b). ARAM / Arena never surface a Live Client game_id,
                     so those rows were 100 percent unjoinable; this key groups
                     every tick of one game even with no game_id. Appended at
                     the END of the signature and written as a NEW record field
                     - ``game_id`` keeps its exact old meaning and value, so
                     every existing consumer and every historical row still
                     parse unchanged. Falls back to ``game_id`` when empty.

    Record shape (additive):
        ts / champion / mode / level / owned_items / ds_picks / game_id
        + match_key  <- new; "" only when neither key was resolvable
    """
    entry = {
        "ts": time.time(),
        "champion": champion,
        "mode": mode,
        "level": level,
        "owned_items": [str(i) for i in owned_items],
        "ds_picks": ds_picks,
        "game_id": game_id,
        "match_key": match_key or game_id,
    }
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass
