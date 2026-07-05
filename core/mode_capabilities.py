# arch: static per-mode capability truth table (fail-CLOSED) | section=core | frozen=no
"""core.mode_capabilities - intrinsic, immutable per-mode capabilities.

Ward availability (and future intrinsic mode properties) is a fact about
the game mode, NOT an operator toggle, so it lives in a static
fail-CLOSED truth table: unknown mode, unknown capability, or any error
-> False. This is deliberately NOT core/feature_policy.py, whose
safe-default is True (correct for operator features, WRONG for a
capability that must fail closed outside SR).

Normalization accepts canonical constants ("SR"), lowercase keys ("sr"),
and raw Riot game_mode strings ("CLASSIC" / "KIWI" / "CHERRY" / ...) via
core.game_snapshot.mode_from_game_mode_string. That helper defaults ANY
unrecognized string to MODE_SR (core/game_snapshot.py:80), which would
be fail-OPEN here - so _normalize only trusts its SR answer for raw
strings explicitly known to mean Summoner's Rift ("CLASSIC"). Everything
else that falls through to the SR default is rejected (PRACTICETOOL,
TUTORIAL, garbage), matching the pre-existing `game_mode == "CLASSIC"`
ward literal in game_reader/snapshot_normalizer.py exactly.

district_config values are the config/minimap_grids/*.json file stems
("sr", "aram", "arena", "brawl"); TFT has no minimap grid -> None.

Spec: docs/ZOI_DISTRICT_ORCHESTRATION_PLAN.md section 5 (Ward-gate).
"""

from core.game_snapshot import (
    MODE_ARAM,
    MODE_ARENA,
    MODE_BRAWL,
    MODE_SR,
    MODE_TFT,
    mode_from_game_mode_string,
)

# Raw Riot game_mode strings that legitimately mean Summoner's Rift.
# mode_from_game_mode_string defaults unrecognized input to MODE_SR, so
# a raw string is only accepted as SR when listed here (fail-CLOSED).
_RAW_SR_STRINGS = frozenset({"CLASSIC"})

MODE_CAPABILITIES = {
    MODE_SR:    {"has_wards": True,  "district_config": "sr"},
    MODE_ARAM:  {"has_wards": False, "district_config": "aram"},
    MODE_ARENA: {"has_wards": False, "district_config": "arena"},
    MODE_BRAWL: {"has_wards": False, "district_config": "brawl"},
    MODE_TFT:   {"has_wards": False, "district_config": None},
}


def _normalize(mode):
    """Map any mode spelling to a MODE_CAPABILITIES key, or None.

    Accepts canonical ("SR"), lowercase ("sr"), and raw Riot strings
    ("CLASSIC", "KIWI", "CHERRY", "ARAM_UNRANKED_5X5", ...). Unknown /
    None / non-string / garbage -> None so callers fail closed. Never
    raises.
    """
    try:
        if not isinstance(mode, str):
            return None
        stripped = mode.strip()
        if not stripped:
            return None
        upper = stripped.upper()
        for canonical in MODE_CAPABILITIES:
            if upper == canonical.upper():
                return canonical
        mapped = mode_from_game_mode_string(stripped)
        if mapped == MODE_SR and upper not in _RAW_SR_STRINGS:
            # mode_from_game_mode_string's SR is its catch-all default;
            # only explicit SR spellings may claim SR capabilities.
            return None
        if mapped in MODE_CAPABILITIES:
            return mapped
        return None
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return None


def has_capability(mode, cap) -> bool:
    """True iff `mode` intrinsically has boolean capability `cap`.

    FAIL-CLOSED: unknown mode, unknown cap, non-boolean capability
    value, or any error -> False. Never raises.
    """
    try:
        canonical = _normalize(mode)
        if canonical is None:
            return False
        caps = MODE_CAPABILITIES.get(canonical)
        if not isinstance(caps, dict):
            return False
        return caps.get(cap) is True
    except Exception:  # noqa: BLE001 - fail-CLOSED contract, never raise
        return False


def district_config(mode):
    """Minimap-grid config stem for `mode` ("sr", "aram", ...) or None.

    The stem resolves to config/minimap_grids/<stem>.json. Fail-soft:
    unknown mode, missing entry, or any error -> None. Never raises.
    """
    try:
        canonical = _normalize(mode)
        if canonical is None:
            return None
        caps = MODE_CAPABILITIES.get(canonical)
        if not isinstance(caps, dict):
            return None
        value = caps.get("district_config")
        return value if isinstance(value, str) else None
    except Exception:  # noqa: BLE001 - fail-soft contract, never raise
        return None
