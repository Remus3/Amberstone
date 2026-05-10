# arch: builds /api/state payload | section=dashboard | frozen=no
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

from coaches.sr_draft_profile import is_sr_draft_queue
from core.coaching_payload import validate_coaching_payload
from core.queue_modes import mode_key_from_queue_id
from dashboard._context import APP_DIR, read_json
from dashboard._liveclient import lcu_summary, liveclient_summary
from dashboard.routes_team_context import get_team_context


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


def _preflip_mode_from_lcu(lcu_snapshot: dict | None) -> str | None:
    """Derive a dashboard mode_key from LCU lobby/champ-select queue_id.

    Champ-select wins over lobby (more specific). Returns ``None`` when
    no recognised queue_id is available, so the caller falls back to the
    health.mode default ("client").
    """
    if not isinstance(lcu_snapshot, dict):
        return None
    cs = lcu_snapshot.get("champ_select")
    if isinstance(cs, dict):
        m = mode_key_from_queue_id(cs.get("queue_id"))
        if m:
            return m
    lobby = lcu_snapshot.get("lobby")
    if isinstance(lobby, dict) and not lobby.get("is_custom"):
        m = mode_key_from_queue_id(lobby.get("queue_id"))
        if m:
            return m
    return None


def build_state() -> dict:
    health = read_json("ops/runtime/health.json")
    lcu_snapshot = lcu_summary()
    # mode resolution: prefer specific mode flag from health (LiveClient is
    # authoritative once the game is running). When LiveClient is dark
    # (lobby/champ-select pre-game), pre-flip from the LCU lobby/champ-
    # select queue_id so the dashboard switches to the right mode panel
    # before the in-game match starts.
    mode_key = "client"
    if health.get("aram_mode"):    mode_key = "aram"
    elif health.get("arena_mode"): mode_key = "arena"
    elif health.get("tft_mode"):   mode_key = "tft"
    elif health.get("has_game"):   mode_key = "sr"
    else:
        pre = _preflip_mode_from_lcu(lcu_snapshot)
        mode_key = pre or health.get("mode", "client")

    coach_file = MODE_TO_FILE.get(mode_key, "coaching_data.json")
    coach = read_json(coach_file)
    validate_coaching_payload(coach)

    # Overlay live API fields onto coach data so the dashboard placeholders
    # (game_time, kda, level, gold, hp, mana, cs) populate immediately.
    # Coach values win when present (e.g. coach computes win_pct from comp).
    lc = liveclient_summary()
    if lc:
        for k, v in lc.items():
            if coach.get(k) in (None, "", 0):
                coach[k] = v

    # Phase 8 step 1: derive sr_draft flag from queue_id and stamp it
    # alongside the existing is_aram sibling. Phase 8's UI gates the
    # 3-build chooser on this flag.
    cs = lcu_snapshot.get("champ_select") if isinstance(lcu_snapshot, dict) else None
    if isinstance(cs, dict):
        cs["sr_draft"] = is_sr_draft_queue(cs.get("queue_id"))

    # FU02: splice the latest team_context payload (5+5 enrichment) into
    # coach. Stays None until the Game-PC LCU agent posts to
    # /api/team-context/refresh. Dashboard panel reads coach.team_context
    # and falls back to skeleton rows when fields are empty.
    coach["team_context"] = get_team_context()

    return {
        "mode_key": mode_key,
        "coach_source": coach_file,
        "health": {
            "alive":          health.get("alive"),
            "pid":            health.get("pid"),
            "mode":           health.get("mode"),
            "has_game":       health.get("has_game"),
            # Per-mode flags drive `onHealth` mode resolution in the
            # dashboard. Without them, has_game=True would always fall
            # through to `tag="sr"` and flap against onState's mode_key
            # ("arena"/"aram"/"brawl"/"tft"), flashing mode-gated UI like
            # the augments pill on every health tick.
            "aram_mode":      health.get("aram_mode"),
            "arena_mode":     health.get("arena_mode"),
            "brawl_mode":     health.get("brawl_mode"),
            "tft_mode":       health.get("tft_mode"),
            "ui_pulse_age_s": health.get("ui_pulse_age_s"),
            "game_poll_age_s": health.get("game_poll_worker_age_s"),
        },
        "coach": coach,
        "liveclient": lc,
        "lcu": lcu_snapshot,
    }


_SIM_STATES_PATH: Path = APP_DIR / "data" / "sim_states.json"
_SIM_STATES_CACHE: dict | None = None


def sim_states() -> dict:
    global _SIM_STATES_CACHE
    if _SIM_STATES_CACHE is None:
        _SIM_STATES_CACHE = json.loads(_SIM_STATES_PATH.read_text(encoding="utf-8"))
    return _SIM_STATES_CACHE
