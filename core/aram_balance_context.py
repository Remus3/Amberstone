"""ARAM per-champ damage-balance coach-prompt consumer (BACKLOG F6).

Surfaces the patch ``aram_modifiers`` ``aramDamageDealt`` /
``aramDamageTaken`` multipliers for the operator's own champion as a
single deterministic prompt line, mirroring the SHIPPED
``core/aram_tenacity_context.py`` pattern (snapshot-backed loader read
once at import + render-side mode-gated line + fail-soft to empty).

``aramDamageDealt`` > 1.0 means the champion deals MORE damage in ARAM
(an ARAM buff); < 1.0 means LESS (a nerf). ``aramDamageTaken`` > 1.0
means the champion TAKES more damage (squishier in ARAM); < 1.0 means
it takes less (tankier). A neutral champion sits at (1.0, 1.0).

The line is intentionally render-side: empty whenever no modifier
applies (SR, unknown champion, exactly (1.0, 1.0)) so the coach prompt
size is unchanged in the neutral case. Patch + snapshot are read once at
module import; a restart picks up a new patch.

The ENEMY-side balance line is a deliberate NON-GOAL. 126/172 champs are
non-neutral at 16.12.1, so an enemy-damage rollup would render in nearly
every game and add prompt noise without a clean operator action. The
self-only delta is a self-tuning signal (play more/less aggressively
given your own buff/nerf), unlike tenacity's enemy line which marks an
exploitable per-target CC window. ASCII only (CLAUDE.md hard rule).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)


def _load_balance_map() -> Dict[str, tuple[float, float]]:
    """Read patch + champions.json once; return {champion: (dealt, taken)}.

    Neutral champions at (1.0, 1.0) are intentionally OMITTED so a missing
    entry signals "no modifier" without an extra equality check at call
    time.

    PER-FIELD fallback: a non-numeric value on ONE of the two fields
    falls back to 1.0 for THAT field only and does NOT drop the whole
    champion (diverges intentionally from the tenacity loader's whole-
    champ ``continue``). A champion is only omitted when BOTH fields
    resolve to 1.0.

    Fail-soft on missing files / malformed JSON / unexpected data shape:
    returns ``{}`` and the consumer renders an empty line.
    """
    try:
        patch_file = _DATA_DIR / "current.txt"
        patch = patch_file.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return {}
    if not patch:
        return {}
    champs_file = _DATA_DIR / patch / "champions.json"
    try:
        raw = json.loads(champs_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    data = raw.get("data") or {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, tuple[float, float]] = {}
    for cid, champ in data.items():
        if not isinstance(champ, dict):
            continue
        lolmath = champ.get("lolmath") or {}
        aram = lolmath.get("aram_modifiers") or {}
        try:
            dealt = float(aram.get("aramDamageDealt", 1.0))
        except (TypeError, ValueError):
            dealt = 1.0
        try:
            taken = float(aram.get("aramDamageTaken", 1.0))
        except (TypeError, ValueError):
            taken = 1.0
        if dealt != 1.0 or taken != 1.0:
            result[cid] = (dealt, taken)
    return result


_BALANCE_MAP: Dict[str, tuple[float, float]] = _load_balance_map()


def get_balance_mults(champion: str | None) -> tuple[float, float]:
    """Return the (aramDamageDealt, aramDamageTaken) pair for ``champion``.

    Falls back to the neutral ``(1.0, 1.0)`` for a missing / unknown /
    falsy champion. Mode-agnostic helper for callers that already know
    they are in ARAM; use ``aram_balance_line`` for the mode-gated prompt
    path.
    """
    if not champion:
        return (1.0, 1.0)
    return _BALANCE_MAP.get(champion, (1.0, 1.0))


def aram_balance_line(champion: str | None, mode: str | None) -> str:
    """Render a one-line ARAM damage-balance context for the coach prompt.

    Returns an empty string when:
      * mode is not ARAM / ARAM Mayhem (KIWI)
      * champion is missing or neutral (1.0, 1.0)

    For a modified champion, returns a line like:

        ARAM balance: you deal +5%, take -5% damage

    Only the non-neutral clauses are emitted (a dealt-only champion drops
    the "take" clause and vice versa); the percentages are signed so the
    direction is directly readable.
    """
    if not mode:
        return ""
    if mode not in _ARAM_MODES and mode.upper() not in _ARAM_MODES:
        return ""
    dealt, taken = get_balance_mults(champion)
    deal_pct = round((dealt - 1.0) * 100)
    take_pct = round((taken - 1.0) * 100)
    if deal_pct == 0 and take_pct == 0:
        return ""
    clauses = []
    if deal_pct != 0:
        clauses.append(f"deal {deal_pct:+d}%")
    if take_pct != 0:
        clauses.append(f"take {take_pct:+d}%")
    return "ARAM balance: you " + ", ".join(clauses) + " damage"


__all__ = ["aram_balance_line", "get_balance_mults", "_BALANCE_MAP"]
