"""Dashboard state-shape builder + sim-scenario loader.

Tier 2 helper-shake (2026-05-01): extracted from web_dashboard.py.

`build_state()` is the canonical /api/state payload assembler — it picks
the active coaching artifact based on `ops/runtime/health.json`, overlays
fresh Live Client API fields on top so the dashboard placeholders
(game_time, kda, level, gold, hp, mana, cs) populate immediately, and
returns the merged dict the dashboard polls at 500ms.

`sim_states()` lazy-loads `data/sim_states.json` once into a module-level
cache. The sim scenarios feed the `/api/sim-state` route used by the
dashboard's preview-mode scenario picker.

`MODE_TO_FILE` is the public mapping consumed by `build_state()` and
exposed for any caller that wants to know which artifact corresponds to
a given mode key.

Imports `lcu_summary` + `liveclient_summary` directly from
`dashboard._liveclient` (no re-export round-trip through web_dashboard)
and `read_json` directly from `dashboard._context`.
"""
from __future__ import annotations

import json
from pathlib import Path

from dashboard._context import APP_DIR, read_json
from dashboard._liveclient import lcu_summary, liveclient_summary


MODE_TO_FILE = {
    "aram":   "data/aram_coaching_data.json",
    "arena":  "data/arena_coaching_data.json",
    "brawl":  "data/brawl_coaching_data.json",
    "tft":    "data/tft_coaching_data.json",
    # SR + client share the root coaching_data.json
    "game":   "coaching_data.json",
    "client": "coaching_data.json",
    "sr":     "coaching_data.json",
}


def build_state() -> dict:
    health = read_json("ops/runtime/health.json")
    # mode resolution: prefer specific mode flag from health, fall back to .mode
    mode_key = "client"
    if health.get("aram_mode"):    mode_key = "aram"
    elif health.get("arena_mode"): mode_key = "arena"
    elif health.get("tft_mode"):   mode_key = "tft"
    elif health.get("has_game"):   mode_key = "game"
    else:                          mode_key = health.get("mode", "client")

    coach_file = MODE_TO_FILE.get(mode_key, "coaching_data.json")
    coach = read_json(coach_file)

    # Overlay live API fields onto coach data so the dashboard placeholders
    # (game_time, kda, level, gold, hp, mana, cs) populate immediately.
    # Coach values win when present (e.g. coach computes win_pct from comp).
    lc = liveclient_summary()
    if lc:
        for k, v in lc.items():
            if coach.get(k) in (None, "", 0):
                coach[k] = v

    return {
        "mode_key": mode_key,
        "coach_source": coach_file,
        "health": {
            "alive":          health.get("alive"),
            "pid":            health.get("pid"),
            "mode":           health.get("mode"),
            "has_game":       health.get("has_game"),
            "ui_pulse_age_s": health.get("ui_pulse_age_s"),
            "game_poll_age_s": health.get("game_poll_worker_age_s"),
        },
        "coach": coach,
        "liveclient": lc,
        "lcu": lcu_summary(),
    }


_SIM_STATES_PATH: Path = APP_DIR / "data" / "sim_states.json"
_SIM_STATES_CACHE: dict | None = None


def sim_states() -> dict:
    global _SIM_STATES_CACHE
    if _SIM_STATES_CACHE is None:
        _SIM_STATES_CACHE = json.loads(_SIM_STATES_PATH.read_text(encoding="utf-8"))
    return _SIM_STATES_CACHE
