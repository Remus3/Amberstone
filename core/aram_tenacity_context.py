"""ARAM tenacity coach-prompt consumer.

Closes the ENGINE 1.25.0 (2026-05-21) BACKLOG carry-forward "Future EHP
enemy-CC model for aram_tenacity_mult". The engine has exposed
``scaled["aram_tenacity_mult"]`` since 1.19.0 and the
``effective_cc_duration(base_cc_s, tenacity_mult)`` helper at
``agents/daemon_slayer/ehp.py`` has been ready since 1.25.0 - this module
is the first live consumer.

17 ARAM champs carry a non-1.0 aramTenacity multiplier at patch 16.10.1
(all assassins/skirmishers): 15 at 1.20x (Akali / Bel'Veth / Ekko /
Evelynn / Katarina / Kayn / Kha'Zix / Lucian / Nunu / Pyke / Qiyana /
Quinn / Rengar / Talon / Zed) and 2 at 1.10x (Elise / Fizz).

tenacity_mult > 1.0 = LONGER CC on that champion (ARAM nerf for high-
mobility assassins). 1.0 = no modifier. The Meraki bulk convention is
"effective CC duration multiplier" not "tenacity %".

``aram_tenacity_line`` is intentionally render-side: it returns a single
prompt-friendly line that the ARAM coach interpolates into its user
template. The line is empty whenever no modifier applies (SR, ARAM Mayhem
falls through ARAM rules, unknown champion, exactly 1.0) so the coach's
prompt size is unchanged in the 90% case.

Patch + snapshot are read once at module import (mirrors the death-
patterns + lessons cache discipline); a restart picks up a new patch.
"""

from __future__ import annotations

import json
import pathlib
from typing import Dict

from agents.daemon_slayer.ehp import effective_cc_duration

_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)


def _load_tenacity_map() -> Dict[str, float]:
    """Read patch + champions.json once; return {champion_name: tenacity_mult}.

    Champions with the default 1.0 multiplier are intentionally OMITTED
    from the map so a missing entry signals "no modifier" without an
    extra equality check at call time.

    Fail-soft on missing files / malformed JSON: returns ``{}`` and the
    consumer renders an empty line.
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
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    data = raw.get("data") or {}
    if not isinstance(data, dict):
        return {}
    result: Dict[str, float] = {}
    for cid, champ in data.items():
        if not isinstance(champ, dict):
            continue
        lolmath = champ.get("lolmath") or {}
        aram = lolmath.get("aram_modifiers") or {}
        try:
            mult = float(aram.get("aramTenacity", 1.0))
        except (TypeError, ValueError):
            continue
        if mult != 1.0:
            result[cid] = mult
    return result


_TENACITY_MAP: Dict[str, float] = _load_tenacity_map()


def get_tenacity_mult(champion: str | None) -> float:
    """Return the aramTenacity multiplier for ``champion`` (1.0 if none).

    Mode-agnostic helper for callers that already know they're in ARAM.
    Use ``aram_tenacity_line`` for the mode-gated prompt path.
    """
    if not champion:
        return 1.0
    return _TENACITY_MAP.get(champion, 1.0)


def aram_tenacity_line(champion: str | None, mode: str | None) -> str:
    """Render a one-line ARAM tenacity context for the coach user prompt.

    Returns an empty string when:
      * mode is not ARAM / ARAM Mayhem (KIWI)
      * champion is missing or not in the modified-tenacity map
      * the tenacity multiplier is exactly 1.0

    For a modified champion, returns a line like:

        ARAM tenacity: 1.20x effective CC duration on you (1.0s root -> 1.20s)

    The worked example uses 1.0s as the base so the multiplier is
    directly readable; the helper from ``ehp.effective_cc_duration``
    drives the math so future tenacity-direction changes flow through
    one seam.
    """
    if not mode:
        return ""
    if mode not in _ARAM_MODES and mode.upper() not in _ARAM_MODES:
        return ""
    mult = get_tenacity_mult(champion)
    if mult == 1.0:
        return ""
    worked = effective_cc_duration(1.0, mult)
    return (
        f"ARAM tenacity: {mult:.2f}x effective CC duration on you "
        f"(1.0s root -> {worked:.2f}s)"
    )


def enemy_aram_tenacity_line(
    enemies: list[str | None] | tuple[str | None, ...] | None,
    mode: str | None,
) -> str:
    """Render a one-line ENEMY tenacity context for the coach user prompt.

    Symmetric to ``aram_tenacity_line`` but for the enemy team: when an
    enemy carries a non-1.0 ``aramTenacity`` multiplier, the operator's
    CC on that enemy follows the same multiplier (longer CC sticks
    longer; the operator-facing value is "your CC on them lasts X.XXx
    base"). For the 17 modified champs at 16.10.1 the multipliers are
    all > 1.0 so this is unambiguously a follow-up window for the
    operator's team.

    Returns an empty string when:
      * mode is not ARAM / ARAM Mayhem (KIWI)
      * ``enemies`` is None / empty / contains only default-tenacity champs
      * all entries are missing or default-1.0

    For one or more modified enemies, returns a single line like:

        Enemy ARAM tenacity (your CC on them lasts longer): Zed 1.20x, Talon 1.20x

    Sort order is descending multiplier then alphabetical so the highest-
    value follow-up target sorts first; this keeps the line readable when
    only one enemy is modified (the common case).
    """
    if not mode:
        return ""
    if mode not in _ARAM_MODES and mode.upper() not in _ARAM_MODES:
        return ""
    if not enemies:
        return ""
    modified: list[tuple[str, float]] = []
    for name in enemies:
        if not name:
            continue
        mult = _TENACITY_MAP.get(name)
        if mult is None:
            continue
        modified.append((name, mult))
    if not modified:
        return ""
    modified.sort(key=lambda nm: (-nm[1], nm[0]))
    chunks = [f"{name} {mult:.2f}x" for name, mult in modified]
    return (
        "Enemy ARAM tenacity (your CC on them lasts longer): "
        + ", ".join(chunks)
    )


__all__ = [
    "aram_tenacity_line",
    "enemy_aram_tenacity_line",
    "get_tenacity_mult",
]
