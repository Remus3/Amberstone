# arch: queue/map → mode-key routing + TFT early-exit | section=vision | frozen=no
"""game_reader.mode_router - TFT detection + mode-keyed helpers.

Module-level functions (not a mixin) - called from
`_NormalizerMixin._process_game` to short-circuit the TFT branch and to
size SR-vs-ARAM tower counts. Keep this small; it is the natural place to
add new mode-routing logic (queue-id heuristics, ARAM Mayhem variants, etc.).
"""

import logging

_log = logging.getLogger("game_reader.mode_router")

# ARAM map family (Howling Abyss + variants). 3 turrets per team.
ARAM_GAME_MODES = ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM")
ARAM_TOWER_COUNT = 3
SR_TOWER_COUNT = 11


def is_tft_mode(game_mode: str) -> bool:
    """Return True for any TFT/teamfight-tactics game mode string."""
    return "TFT" in (game_mode or "")


def is_aram_mode(game_mode: str) -> bool:
    """Return True for any ARAM-family mode (incl. Mayhem KIWI)."""
    return (game_mode or "") in ARAM_GAME_MODES


def tower_count_for(game_mode: str) -> int:
    """Per-team turret count by map family."""
    return ARAM_TOWER_COUNT if is_aram_mode(game_mode) else SR_TOWER_COUNT


def tft_minimal_state(game_mode: str, active: dict, game_info: dict,
                       events: list, time_str: str, game_seconds: float):
    """Build the minimal TFT state dict. Returns None if a GameEnd event is
    present (caller should treat as game-over, same as SR/ARAM path).

    TFT has a different data structure; the dedicated TFT coach handles
    full state parsing via tft_state_reader.py - this just emits enough
    fields for the overlay to detect TFT mode and route there.
    """
    for ev in events:
        if isinstance(ev, dict) and ev.get("EventName") == "GameEnd":
            _log.info("TFT GameEnd detected")
            return None

    tft_level  = active.get("level", game_info.get("level", 1))
    tft_gold   = active.get("currentGold", active.get("gold", 0))
    tft_hp     = active.get("currentHP",   active.get("health", 100))
    tft_stage  = game_info.get("stage",       active.get("stage",  1))
    tft_round  = game_info.get("roundNumber", active.get("round",  1))
    return {
        "game_mode":    game_mode,
        "game_time":    time_str,
        "game_seconds": game_seconds,
        "champion":     "TFT",
        "hp_pct":       int(tft_hp),
        "hp_abs":       int(tft_hp),
        "hp_max":       100,
        "mana_pct":     100,
        "gold":         int(tft_gold),
        "cs":           0,
        "cs_per_min":   0.0,
        "level":        int(tft_level),
        "kda":          "0/0/0",
        "items":        [],
        "ally_comp":    [],
        "enemy_comp":   [],
        "objectives":   f"Stage {tft_stage}-{tft_round}",
        "dead_enemies": [],
        "alive_enemies":[],
    }
