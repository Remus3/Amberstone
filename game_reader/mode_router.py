# arch: queue/map -> mode-key routing + TFT early-exit | section=vision | frozen=no
"""game_reader.mode_router - TFT detection + mode-keyed helpers.

Module-level functions (not a mixin) - called from
`_NormalizerMixin._process_game` to short-circuit the TFT branch and to
size SR-vs-ARAM tower counts. Keep this small; it is the natural place to
add new mode-routing logic (queue-id heuristics, ARAM Mayhem variants, etc.).
"""

import logging
import math

_log = logging.getLogger("game_reader.mode_router")

# ARAM map family (Howling Abyss + variants). 3 turrets per team.
ARAM_GAME_MODES = ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM")
ARAM_TOWER_COUNT = 3
SR_TOWER_COUNT = 11


def _coerce_int(value, default: int = 0) -> int:
    """Coerce a Live Client JSON numeric to an int, or `default` on garbage.

    RM-344. Deliberately a LOCAL copy of
    `snapshot_normalizer._coerce_int` / `_coerce_num` rather than an import:
    `snapshot_normalizer` imports THIS module at its own line 22, so importing
    back is a hard circular ImportError ("cannot import name '_coerce_int'
    from partially initialized module") - measured, not assumed.

    Why it is needed here at all: `_process_game` early-returns
    `tft_minimal_state(...)` BEFORE the SR/ARAM branch where those helpers are
    applied, so the TFT path reached the wire completely unhardened. The
    hazard is the one `_coerce_num`'s docstring already records - `json.loads`
    accepts the NaN / Infinity / -Infinity literals as a CPython extension,
    and the primary relay read path (`game_reader.poller.read_game`) calls
    `_process_game` UNWRAPPED, so a raise kills the poll tick. Measured
    pre-fix on the bare `int()` calls below: `None` -> TypeError, `NaN` ->
    ValueError, `Infinity` -> OverflowError.

    `None` is not a hypothetical here: `active.get("currentHP", ...)` returns
    `None` for a key PRESENT with a JSON `null`, because a present key defeats
    the `.get` default - the fallback chain only fires on an ABSENT key.

    Semantics match the snapshot_normalizer pair exactly, so the two cannot
    drift in behaviour: a numeric-looking string ("13") is PRESERVED, since
    that is real upstream type drift and the value is still the truth; only
    non-numeric or non-finite input takes `default`.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return int(default)
    return int(f) if math.isfinite(f) else int(default)


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

    # RM-344: every one of these is read straight off the wire and was fed to
    # a bare `int()` (or interpolated raw into `objectives`). Coerce at the
    # point of READ, with each field's own terminal `.get` default, so one bad
    # field degrades ONE field instead of killing the unwrapped poll tick.
    # This does not re-walk the `.get` fallback chain: a present-but-null
    # `currentHP` takes 100, not a sibling `health` - preserving the existing
    # `.get` semantics rather than silently changing them.
    tft_level  = _coerce_int(active.get("level", game_info.get("level", 1)), 1)
    tft_gold   = _coerce_int(active.get("currentGold", active.get("gold", 0)), 0)
    tft_hp     = _coerce_int(active.get("currentHP",   active.get("health", 100)), 100)
    tft_stage  = _coerce_int(game_info.get("stage",       active.get("stage",  1)), 1)
    tft_round  = _coerce_int(game_info.get("roundNumber", active.get("round",  1)), 1)
    return {
        "game_mode":    game_mode,
        "game_time":    time_str,
        "game_seconds": game_seconds,
        "champion":     "TFT",
        "hp_pct":       tft_hp,
        "hp_abs":       tft_hp,
        "hp_max":       100,
        "mana_pct":     100,
        "gold":         tft_gold,
        "cs":           0,
        "cs_per_min":   0.0,
        "level":        tft_level,
        "kda":          "0/0/0",
        "items":        [],
        "ally_comp":    [],
        "enemy_comp":   [],
        "objectives":   f"Stage {tft_stage}-{tft_round}",
        "dead_enemies": [],
        "alive_enemies":[],
    }
