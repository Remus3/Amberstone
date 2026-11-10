"""ARAM tenacity coach-prompt consumer.

Closes the ENGINE 1.25.0 (2026-05-21) BACKLOG carry-forward "Future EHP
enemy-CC model for aram_tenacity_mult". The engine has exposed
``scaled["aram_tenacity_mult"]`` since 1.19.0 and the
``effective_cc_duration(base_cc_s, tenacity_mult)`` helper at
``agents/daemon_slayer/ehp.py`` has been ready since 1.25.0 - this module
is the first live consumer.

The modified set is read from the live snapshot, never recited here: 17
champions at 16.10.1, 16 since 16.20.1 (Bel'Veth reset to 1.0), measured
16 at 16.22.1 - 14 at 1.20x and Elise / Fizz at 1.10x, all assassins or
skirmishers.

tenacity_mult > 1.0 = LONGER CC on that champion (ARAM nerf for high-
mobility assassins). 1.0 = no modifier. The Meraki bulk convention is
"effective CC duration multiplier" not "tenacity %".

``aram_tenacity_line`` is intentionally render-side: it returns a single
prompt-friendly line that the ARAM coach interpolates into its user
template. The line is empty whenever no modifier applies (SR, unknown
champion, exactly 1.0) so the coach's prompt size is unchanged in the
common case.

CHAMPION NAMES (s144 true-audit, S144-T-712 / S144-T-142): the map is
keyed by the DDragon id ("Khazix", "Nunu"), but the ARAM coach passes the
Live Client ``championName``, which is the DISPLAY name ("Kha'Zix",
"Nunu & Willump"). Every lookup resolves the name through an alias map
built from the same champions.json ``name`` field: exact id, then exact
display name, then a case- and punctuation-insensitive form. A spelling
two ids share is dropped rather than guessed. Before this, 2 of the 16
modified champions at 16.22.1 rendered no line in any game. The enemy
line labels each champion with its snapshot display name.

VALUE HYGIENE: ``json.loads`` accepts ``NaN`` / ``Infinity``. A
multiplier must be a finite number above zero (a bool is not a number
here); anything else is treated as "no modifier" for that champion. A
junk row (non-dict ``lolmath`` / ``aram_modifiers``) is skipped, never
raised: this loader runs at ``import coaches.aram_coach``.

Patch + snapshot are read once at module import (mirrors the death-
patterns + lessons cache discipline); a restart picks up a new patch. A
failed read logs ONE warning naming the failure class (never a path or
file contents) and the lines stay empty until a restart.

Sibling: ``core/aram_balance_context.py`` carries the same loader shape
and alias resolution for the damage-balance line. ASCII only (CLAUDE.md
hard rule).
"""

from __future__ import annotations

import json
import logging
import math
import pathlib
from typing import Any, Dict, Mapping

from agents.daemon_slayer.ehp import effective_cc_duration

log = logging.getLogger(__name__)

_DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)

# A patch token names ONE directory under _DATA_DIR. A separator, a
# parent reference or a drive colon would let current.txt point the read
# somewhere else, so such a token is refused rather than followed.
_PATCH_FORBIDDEN = ("/", "\\", ":", "..")


def _read_champion_data() -> tuple[Dict[str, Any], str]:
    """Read current.txt + <patch>/champions.json ONCE.

    Returns ``(data, "")`` with the ``data`` dict on success, or
    ``({}, reason)`` naming the failure class. Never raises and never puts
    file contents or a path into ``reason``.
    """
    try:
        # utf-8-sig: a PowerShell 5.1 ``-Encoding UTF8`` write leaves a BOM,
        # which a plain utf-8 read keeps as part of the patch token.
        patch = (_DATA_DIR / "current.txt").read_text(
            encoding="utf-8-sig").strip()
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, ValueError) as exc:
        return {}, f"current.txt unreadable ({type(exc).__name__})"
    if not patch:
        return {}, "current.txt is blank"
    if any(bad in patch for bad in _PATCH_FORBIDDEN):
        return {}, "current.txt patch token refused (path segment)"
    try:
        raw = json.loads(
            (_DATA_DIR / patch / "champions.json").read_text(encoding="utf-8"))
    # json.JSONDecodeError and UnicodeDecodeError are both ValueErrors; a
    # deeply nested document raises RecursionError from the decoder.
    except (OSError, ValueError, RecursionError) as exc:
        return {}, f"champions.json unreadable ({type(exc).__name__})"
    if not isinstance(raw, dict):
        return {}, "champions.json is not a JSON object"
    data = raw.get("data")
    if not isinstance(data, dict) or not data:
        return {}, "champions.json has no champion rows"
    return data, ""


def _multiplier(value: Any) -> float | None:
    """A usable multiplier from a JSON number or numeric string: finite and
    above zero, else None. A bool is refused: ``float(True)`` is 1.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return out if math.isfinite(out) and out > 0.0 else None


def _tenacity_from(data: Mapping[Any, Any]) -> Dict[str, float]:
    """{champion id: aramTenacity} for every row whose multiplier is usable
    and not 1.0. A non-str id or a non-dict row / ``lolmath`` /
    ``aram_modifiers`` is skipped."""
    result: Dict[str, float] = {}
    for cid, champ in data.items():
        if not isinstance(cid, str) or not cid or not isinstance(champ, dict):
            continue
        lolmath = champ.get("lolmath")
        if not isinstance(lolmath, dict):
            continue
        aram = lolmath.get("aram_modifiers")
        if not isinstance(aram, dict):
            continue
        mult = _multiplier(aram.get("aramTenacity", 1.0))
        if mult is not None and mult != 1.0:
            result[cid] = mult
    return result


def _load_tenacity_map() -> Dict[str, float]:
    """Read patch + champions.json; return {champion id: tenacity_mult}.

    Champions with the default 1.0 multiplier are intentionally OMITTED
    from the map so a missing entry signals "no modifier" without an
    extra equality check at call time.

    Fail-soft on missing files / malformed JSON / unexpected shape:
    returns ``{}`` and the consumer renders an empty line.
    """
    data, _reason = _read_champion_data()
    return _tenacity_from(data)


def _norm(name: str) -> str:
    """Case- and punctuation-insensitive form: "Kha'Zix" -> "khazix"."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _display_names(data: Mapping[Any, Any]) -> Dict[str, str]:
    """{champion id: stripped display name} for rows carrying a non-blank
    ASCII ``name`` (the label the enemy line prints)."""
    out: Dict[str, str] = {}
    for cid, champ in data.items():
        if not isinstance(cid, str) or not cid or not isinstance(champ, dict):
            continue
        name = champ.get("name")
        if isinstance(name, str) and name.strip() and name.isascii():
            out[cid] = name.strip()
    return out


def _aliases_from(data: Mapping[Any, Any]) -> Dict[str, str]:
    """{name form: champion id}.

    Exact ids beat exact display names; an exact display name shared by
    two ids maps to neither. A normalised form maps only when exactly one
    id produces it and no exact key already holds that spelling.
    """
    ids = [cid for cid in data if isinstance(cid, str) and cid]
    name_owners: Dict[str, set] = {}
    for cid, name in _display_names(data).items():
        name_owners.setdefault(name, set()).add(cid)
    exact: Dict[str, str] = {
        name: next(iter(cids))
        for name, cids in name_owners.items() if len(cids) == 1
    }
    exact.update({cid: cid for cid in ids})
    norm_owners: Dict[str, set] = {}
    for key, cid in exact.items():
        n = _norm(key)
        if n:
            norm_owners.setdefault(n, set()).add(cid)
    aliases = dict(exact)
    for n, cids in norm_owners.items():
        if len(cids) == 1 and n not in aliases:
            aliases[n] = next(iter(cids))
    return aliases


def _build_maps() -> tuple[Dict[str, float], Dict[str, str], Dict[str, str]]:
    """One read of champions.json -> (tenacity map, alias map, display map).

    A failed read logs ONE warning naming the failure class and returns
    three empty maps, so the own and enemy lines degrade together.
    """
    data, reason = _read_champion_data()
    if reason:
        log.warning("aram_tenacity_context: %s - ARAM tenacity lines are "
                    "empty until a restart", reason)
        return {}, {}, {}
    return _tenacity_from(data), _aliases_from(data), _display_names(data)


_TENACITY_MAP: Dict[str, float]
_ALIASES: Dict[str, str]
_DISPLAY: Dict[str, str]
_TENACITY_MAP, _ALIASES, _DISPLAY = _build_maps()


def _champion_id(champion: Any) -> str:
    """Resolve an id or display name to the champion id, or "" when the
    input is not a non-blank str or names no known champion. Falls back to
    the raw spelling when it is itself a key of ``_TENACITY_MAP`` (keeps a
    caller that swaps the map in isolation working)."""
    if not isinstance(champion, str):
        return ""
    name = champion.strip()
    if not name:
        return ""
    cid = _ALIASES.get(name) or _ALIASES.get(_norm(name), "")
    if not cid and name in _TENACITY_MAP:
        return name
    return cid


def _is_aram(mode: Any) -> bool:
    if not isinstance(mode, str):
        return False
    gate = mode.strip()
    return gate in _ARAM_MODES or gate.upper() in _ARAM_MODES


def get_tenacity_mult(champion: str | None) -> float:
    """Return the aramTenacity multiplier for ``champion`` (1.0 if none).

    ``champion`` may be a DDragon id or a Live Client display name; a
    missing, unknown, blank or non-str value is 1.0. Mode-agnostic helper
    for callers that already know they're in ARAM. Use
    ``aram_tenacity_line`` for the mode-gated prompt path.
    """
    cid = _champion_id(champion)
    if not cid:
        return 1.0
    return _TENACITY_MAP.get(cid, 1.0)


def aram_tenacity_line(champion: str | None, mode: str | None) -> str:
    """Render a one-line ARAM tenacity context for the coach user prompt.

    Returns an empty string when:
      * mode is not a str naming ARAM / ARAM Mayhem (KIWI)
      * champion is missing or not in the modified-tenacity map
      * the tenacity multiplier is exactly 1.0

    For a modified champion, returns a line like:

        ARAM tenacity: 1.20x effective CC duration on you (1.0s root -> 1.20s)

    The worked example uses 1.0s as the base so the multiplier is
    directly readable; the helper from ``ehp.effective_cc_duration``
    drives the math so future tenacity-direction changes flow through
    one seam.
    """
    if not _is_aram(mode):
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
    base"). Every modified champion in the live snapshot is above 1.0,
    so this is a follow-up window for the operator's team.

    Returns an empty string when:
      * mode is not a str naming ARAM / ARAM Mayhem (KIWI)
      * ``enemies`` is not a list / tuple, or is empty
      * no entry resolves to a modified champion (missing, unknown,
        non-str or default-1.0 entries are skipped)

    For one or more modified enemies, returns a single line like:

        Enemy ARAM tenacity (your CC on them lasts longer): Zed 1.20x, Talon 1.20x

    Each champion is listed once, under its snapshot display name. Sort
    order is descending multiplier then alphabetical so the highest-
    value follow-up target sorts first.
    """
    if not _is_aram(mode):
        return ""
    if not isinstance(enemies, (list, tuple)) or not enemies:
        return ""
    modified: Dict[str, tuple[str, float]] = {}
    for name in enemies:
        cid = _champion_id(name)
        if not cid or cid in modified:
            continue
        mult = _TENACITY_MAP.get(cid)
        if mult is None:
            continue
        modified[cid] = (_DISPLAY.get(cid, cid), mult)
    if not modified:
        return ""
    rows = sorted(modified.values(), key=lambda nm: (-nm[1], nm[0]))
    chunks = [f"{label} {mult:.2f}x" for label, mult in rows]
    return (
        "Enemy ARAM tenacity (your CC on them lasts longer): "
        + ", ".join(chunks)
    )


__all__ = [
    "aram_tenacity_line",
    "enemy_aram_tenacity_line",
    "get_tenacity_mult",
]
