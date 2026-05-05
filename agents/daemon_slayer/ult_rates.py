"""Per-champion ult cast rate lookup for ability-triggered items.

Derived from rewind_history.db (spell4_casts / game_duration_s) with
median aggregation per champion × mode. Used by Malignance Hatefog to
convert ult frequency into a DPS-time proc rate.

Fallback chain: champion+mode → champion global → dataset median (0.0073/s).
Returns 0.0 only when the JSON file is missing entirely — safe no-op for
any proc that multiplies by this value.
"""
from __future__ import annotations

import json
from pathlib import Path

_RATE_FILE = Path(__file__).parent.parent.parent / "data" / "daemon_slayer" / "ult_cast_rates.json"

_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_RATE_FILE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _cache = {"by_champ_mode": {}, "global_fallback": 0.0073}
    return _cache


def get_ult_casts_per_sec(champion_name: str, mode: str) -> float:
    """Return median ult casts/sec for champion+mode from rewind_history data."""
    data = _load()
    champ_data = data.get("by_champ_mode", {}).get(champion_name, {})
    rate = champ_data.get(mode)
    if rate is not None:
        return float(rate)
    rate = champ_data.get("global")
    if rate is not None:
        return float(rate)
    return float(data.get("global_fallback", 0.0073))
