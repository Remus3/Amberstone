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

CHAMPION NAMES (s144 true-audit cycle 115): the maps are keyed by the
DDragon id ("MissFortune", "Kaisa", "Nunu"), but the ARAM coach passes
the Live Client ``championName``, which is the DISPLAY name ("Miss
Fortune", "Kai'Sa", "Nunu & Willump"). Every lookup therefore resolves
the name through an alias map built from the same champions.json
``name`` field: exact id or exact display name first, then a
case- and punctuation-insensitive form, which is dropped when two ids
share it rather than guessed. Before this, 15 of the 123 non-neutral
champions on patch 16.21.1 rendered an empty line in every game.

VALUE HYGIENE: ``json.loads`` accepts ``NaN`` / ``Infinity``. A
multiplier must be a finite number above zero (a bool is not a
number here); anything else is neutral for that field. The flat
``aramAbilityHaste`` must be finite and may be negative.

The ENEMY-side balance line is a deliberate NON-GOAL. 126/172 champs are
non-neutral at 16.12.1, so an enemy-damage rollup would render in nearly
every game and add prompt noise without a clean operator action. The
self-only delta is a self-tuning signal (play more/less aggressively
given your own buff/nerf), unlike tenacity's enemy line which marks an
exploitable per-target CC window. ASCII only (CLAUDE.md hard rule).
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_ARAM_MODES = frozenset(
    ("ARAM", "KIWI", "ARAM_5V5", "ARAM_MAYHEM", "aram", "kiwi")
)

# A patch token names ONE directory under _DATA_DIR. A separator, a
# parent reference or a drive colon would let current.txt point the read
# somewhere else, so such a token is refused rather than followed.
_PATCH_FORBIDDEN = ("/", "\\", ":", "..")

_NEUTRAL: tuple[float, float] = (1.0, 1.0)


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
    except (OSError, ValueError, RecursionError) as exc:
        return {}, f"champions.json unreadable ({type(exc).__name__})"
    if not isinstance(raw, dict):
        return {}, "champions.json is not a JSON object"
    data = raw.get("data")
    if not isinstance(data, dict) or not data:
        return {}, "champions.json has no champion rows"
    return data, ""


def _aram_block(champ: Any) -> Dict[str, Any] | None:
    """The ``lolmath.aram_modifiers`` dict of one champion row, or None
    when the row, its ``lolmath`` or the block is not a dict."""
    if not isinstance(champ, dict):
        return None
    lolmath = champ.get("lolmath")
    if lolmath is None:
        return {}
    if not isinstance(lolmath, dict):
        return None
    aram = lolmath.get("aram_modifiers")
    if aram is None:
        return {}
    if not isinstance(aram, dict):
        return None
    return aram


def _number(value: Any) -> float | None:
    """A finite float from a JSON number or numeric string, else None.
    A bool is refused: ``float(True)`` would read as a real 1.0."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _multiplier(value: Any) -> float | None:
    """A usable multiplier: finite and above zero, else None."""
    out = _number(value)
    return out if out is not None and out > 0.0 else None


def _balance_from(data: Dict[str, Any]) -> Dict[str, tuple[float, float]]:
    result: Dict[str, tuple[float, float]] = {}
    for cid, champ in data.items():
        aram = _aram_block(champ)
        if aram is None or not isinstance(cid, str):
            continue
        dealt = _multiplier(aram.get("aramDamageDealt", 1.0))
        taken = _multiplier(aram.get("aramDamageTaken", 1.0))
        pair = (1.0 if dealt is None else dealt,
                1.0 if taken is None else taken)
        if pair != _NEUTRAL:
            result[cid] = pair
    return result


def _load_balance_map() -> Dict[str, tuple[float, float]]:
    """Read patch + champions.json; return {champion id: (dealt, taken)}.

    Neutral champions at (1.0, 1.0) are intentionally OMITTED so a missing
    entry signals "no modifier" without an extra equality check at call
    time.

    PER-FIELD fallback: an unusable value on ONE of the two fields (not
    a number, not finite, a bool, zero or negative) falls back to 1.0 for
    THAT field only and does NOT drop the whole champion (diverges
    intentionally from the tenacity loader's whole-champ ``continue``). A
    champion is only omitted when BOTH fields resolve to 1.0, or when its
    row / ``lolmath`` / ``aram_modifiers`` is not a dict.

    Fail-soft on missing files / malformed JSON / unexpected data shape:
    returns ``{}`` and the consumer renders an empty line.
    """
    data, _reason = _read_champion_data()
    return _balance_from(data)


# ---------------------------------------------------------------------
# Full-grid accessor (item: ARAM balance-adjustment grid panel).
#
# The SHIPPED loader above carries ONLY dealt+taken for the coach prompt.
# The dashboard grid panel surfaces all seven Riot ARAM modifiers RC
# already loads. This is a SEPARATE map + accessor so the prompt path
# stays byte-identical; it is never read by the coach.
#
# FIELD SEMANTICS:
#   aramDamageDealt / aramDamageTaken / aramHealing / aramShielding /
#   aramTenacity / aramAttackSpeed  are MULTIPLIERS (neutral = 1.0).
#   aramAbilityHaste  is ADDITIVE FLAT (neutral = 0).
# A field is "neutral" (omitted) when a multiplier == 1.0 or AH == 0.
# An unusable value (see _multiplier / _number) is omitted the same way.
# A champion with no non-neutral field is omitted from the map entirely.
# ---------------------------------------------------------------------

_GRID_MULT_FIELDS = (
    "aramDamageDealt",
    "aramDamageTaken",
    "aramHealing",
    "aramShielding",
    "aramTenacity",
    "aramAttackSpeed",
)
_GRID_FLAT_FIELDS = ("aramAbilityHaste",)


def _grid_from(data: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    result: Dict[str, Dict[str, float]] = {}
    for cid, champ in data.items():
        aram = _aram_block(champ)
        if aram is None or not isinstance(cid, str):
            continue
        fields: Dict[str, float] = {}
        for key in _GRID_MULT_FIELDS:
            val = _multiplier(aram.get(key, 1.0))
            if val is not None and val != 1.0:
                fields[key] = val
        for key in _GRID_FLAT_FIELDS:
            val = _number(aram.get(key, 0.0))
            if val is not None and val != 0.0:
                fields[key] = val
        if fields:
            result[cid] = fields
    return result


def _load_balance_grid_map() -> Dict[str, Dict[str, float]]:
    """Read patch + champions.json; return {champion id: {field: value}}.

    Only NON-NEUTRAL, usable fields are kept per champion (a finite
    multiplier above zero and != 1.0, or a finite aramAbilityHaste != 0).
    A champion with zero such fields is OMITTED from the map (no
    empty-dict entries).

    Fail-soft on missing files / malformed JSON / unexpected data shape:
    returns ``{}`` (the route then renders an empty grid).
    """
    data, _reason = _read_champion_data()
    return _grid_from(data)


def _norm(name: str) -> str:
    """Case- and punctuation-insensitive form: "Kai'Sa" -> "kaisa"."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _aliases_from(data: Dict[str, Any]) -> Dict[str, str]:
    """{name form: champion id}. Exact ids beat exact display names; a
    normalised form maps only when exactly one id produces it and no exact
    key already holds that spelling."""
    exact: Dict[str, str] = {}
    for cid, champ in data.items():
        if not isinstance(cid, str) or not cid:
            continue
        name = champ.get("name") if isinstance(champ, dict) else None
        if isinstance(name, str) and name.strip():
            exact.setdefault(name.strip(), cid)
    exact.update({cid: cid for cid in data if isinstance(cid, str) and cid})
    owners: Dict[str, set] = {}
    for key, cid in exact.items():
        n = _norm(key)
        if n:
            owners.setdefault(n, set()).add(cid)
    aliases = dict(exact)
    for n, cids in owners.items():
        if len(cids) == 1 and n not in aliases:
            aliases[n] = next(iter(cids))
    return aliases


def _build_maps() -> tuple[Dict[str, tuple[float, float]],
                           Dict[str, Dict[str, float]],
                           Dict[str, str]]:
    """One read of champions.json -> (balance map, grid map, alias map).
    A failed read logs ONE warning naming the failure class and returns
    three empty maps, so the coach line and the grid degrade together."""
    data, reason = _read_champion_data()
    if reason:
        log.warning("aram_balance_context: %s - ARAM balance line and grid "
                    "are empty until a restart", reason)
        return {}, {}, {}
    return _balance_from(data), _grid_from(data), _aliases_from(data)


_BALANCE_MAP: Dict[str, tuple[float, float]]
_BALANCE_GRID_MAP: Dict[str, Dict[str, float]]
_ALIASES: Dict[str, str]
_BALANCE_MAP, _BALANCE_GRID_MAP, _ALIASES = _build_maps()


def _champion_id(champion: Any) -> str:
    """Resolve an id or display name to the champion id, or "" when the
    input is not a non-blank str or names no known champion."""
    if not isinstance(champion, str):
        return ""
    name = champion.strip()
    if not name:
        return ""
    return _ALIASES.get(name) or _ALIASES.get(_norm(name), "")


def get_balance_mults(champion: str | None) -> tuple[float, float]:
    """Return the (aramDamageDealt, aramDamageTaken) pair for ``champion``
    (a DDragon id or a Live Client display name).

    Falls back to the neutral ``(1.0, 1.0)`` for a missing / unknown /
    falsy / non-str champion. Mode-agnostic helper for callers that
    already know they are in ARAM; use ``aram_balance_line`` for the
    mode-gated prompt path.
    """
    cid = _champion_id(champion)
    if not cid:
        return _NEUTRAL
    return _BALANCE_MAP.get(cid, _NEUTRAL)


def aram_balance_line(champion: str | None, mode: str | None) -> str:
    """Render a one-line ARAM damage-balance context for the coach prompt.

    Returns an empty string when:
      * mode is not a str naming ARAM / ARAM Mayhem (KIWI)
      * champion is missing, unknown or neutral (1.0, 1.0)

    For a modified champion, returns a line like:

        ARAM balance: you deal +5%, take -5% damage

    Only the non-neutral clauses are emitted (a dealt-only champion drops
    the "take" clause and vice versa); the percentages are signed so the
    direction is directly readable.
    """
    if not isinstance(mode, str):
        return ""
    gate = mode.strip()
    if gate not in _ARAM_MODES and gate.upper() not in _ARAM_MODES:
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


def balance_grid_for(champion: str | None) -> Dict[str, float]:
    """Return the non-neutral ARAM-modifier dict for one ``champion`` (a
    DDragon id or a Live Client display name).

    Falls back to ``{}`` for a missing / unknown / falsy / non-str
    champion or a fully-neutral champion. Keys are the raw Riot field
    names (``aramDamageDealt`` etc.); values are the multipliers / flat AH.
    """
    cid = _champion_id(champion)
    if not cid:
        return {}
    return dict(_BALANCE_GRID_MAP.get(cid, {}))


def balance_grid_map() -> Dict[str, Dict[str, float]]:
    """Return the full ``{champion id: {non-neutral field: value}}`` map.

    Fully-neutral champions are omitted. A copy (outer and inner dicts) is
    returned so a caller cannot mutate the module-level cache.
    """
    return {cid: dict(fields) for cid, fields in _BALANCE_GRID_MAP.items()}


__all__ = [
    "aram_balance_line",
    "get_balance_mults",
    "_BALANCE_MAP",
    "balance_grid_for",
    "balance_grid_map",
]
