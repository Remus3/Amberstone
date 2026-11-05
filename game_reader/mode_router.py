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
    `snapshot_normalizer` imports THIS module at module level (its
    `from .mode_router import is_tft_mode, ...` line), so importing
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

    OverflowError is caught too (s144 true-audit M1): `json.loads` turns a
    long JSON integer literal into a Python int, and `float()` of an int past
    ~1.8e308 raises OverflowError, not ValueError - measured killing the TFT
    tick on a 400-digit `currentGold`. The snapshot_normalizer pair catches
    it as well, so the two still agree.
    """
    try:
        f = float(value)
    except (TypeError, ValueError, OverflowError):
        return int(default)
    return int(f) if math.isfinite(f) else int(default)


def _clamped(value, default: int, lo: int, hi: int) -> int:
    """`_coerce_int`, then held inside [lo, hi] (s144 true-audit M4)."""
    return max(lo, min(hi, _coerce_int(value, default)))


# s144 true-audit M4: per-field bounds for the TFT minimal state. HP is held
# to the dict's OWN `hp_max` (100), and HP <= 0 reads as 0 - the ONE alive
# rule in tft/local_player.py treats HP <= 0 as eliminated, and the TFT
# standalone feed already serves 0 for that, never the negative value. The
# other four are MAGNITUDE guards, not game rules: wide enough never to hide
# a real value (TFT level tops out at 10), tight enough that a 1e308 cannot
# become a 309-digit field or a 600-character `objectives` string.
_TFT_HP_MAX = 100
_TFT_LEVEL_MAX = 99
_TFT_GOLD_MAX = 99999
_TFT_STAGE_MAX = 99
_TFT_ROUND_MAX = 99


def is_tft_mode(game_mode: str) -> bool:
    """Return True for any TFT/teamfight-tactics game mode string.

    A SUBSTRING test on a str ("TFT_TUTORIAL" is TFT). Anything that is not
    a str is False (s144 true-audit M2 / M3): `"TFT" in 5` raised TypeError
    out of the unwrapped `_process_game`, and `"TFT" in ["TFT"]` /
    `{"TFT": 1}` matched a container gameMode as TFT.
    """
    return isinstance(game_mode, str) and "TFT" in game_mode


def is_aram_mode(game_mode: str) -> bool:
    """Return True for any ARAM-family mode (incl. Mayhem KIWI).

    An exact match on a str only; a non-str gameMode is False (M2 / M3).
    """
    return isinstance(game_mode, str) and game_mode in ARAM_GAME_MODES


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

    Never raises on a wrong-shaped argument (s144 true-audit M5): a non-dict
    `active` / `game_info` reads as {}, a non-list `events` as [], and a
    non-str `game_mode` as "TFT". The one production caller
    (`_NormalizerMixin._process_game`) already guards the first three; this
    is the function's own contract, not the caller's.
    """
    if not isinstance(active, dict):
        active = {}
    if not isinstance(game_info, dict):
        game_info = {}
    if not isinstance(events, (list, tuple)):
        events = []
    if not isinstance(game_mode, str):
        game_mode = "TFT"
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
    # `.get` semantics rather than silently changing them. s144 M4: each one
    # is then held inside its bounds (see _TFT_HP_MAX and its siblings).
    tft_level  = _clamped(active.get("level", game_info.get("level", 1)), 1,
                          1, _TFT_LEVEL_MAX)
    tft_gold   = _clamped(active.get("currentGold", active.get("gold", 0)), 0,
                          0, _TFT_GOLD_MAX)
    tft_hp     = _clamped(active.get("currentHP",   active.get("health", 100)), 100,
                          0, _TFT_HP_MAX)
    tft_stage  = _clamped(game_info.get("stage",       active.get("stage",  1)), 1,
                          1, _TFT_STAGE_MAX)
    tft_round  = _clamped(game_info.get("roundNumber", active.get("round",  1)), 1,
                          1, _TFT_ROUND_MAX)
    return {
        "game_mode":    game_mode,
        "game_time":    time_str,
        "game_seconds": game_seconds,
        "champion":     "TFT",
        "hp_pct":       tft_hp,
        "hp_abs":       tft_hp,
        "hp_max":       _TFT_HP_MAX,
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
