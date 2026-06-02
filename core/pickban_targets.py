# arch: deterministic pick/ban targets reader (matchup-engine DB) | section=core | frozen=no
"""Deterministic pick/ban targets reader (no LLM, no network, no engine call).

PURPOSE
    Read-time lookup over a precomputed per-champion pick/ban targets DB so the
    champ-select coach can suggest bans (counters) + good-against picks WITHOUT
    a Claude Haiku call. Serves the PRIMARY north star: drive live Haiku usage
    to ZERO. The DB is generated offline by
    ``tools/daemon_slayer_pickban_targets_generate.py`` and committed at
    ``data/daemon_slayer/<patch>/pickban_targets.json``.

WHAT v1 IS (honest scope)
    Every entry is a SOFT counter signal derived from a single itemless
    level-9 1v1 matchup verdict from the SHIPPED, deterministic Daemon Slayer
    matchup engine (``agents.daemon_slayer.matchup.compute_matchup``). It is
    NOT a full draft-counter model - no synergy, no team-comp shape, no role
    context, no rune modelling. It is an honest deterministic proxy for the
    kind of "who counters whom" hint a coach would otherwise ask Haiku for,
    and it is reproducible. The engine's 1v1 verdict is the truth; do not
    over-read a single bar.

SHAPE (per champion, DDragon id keys)
    ``counters``     = the champs that BEAT this champ (the most NEGATIVE
                       this-vs-B net_swing) - ban candidates / be wary.
    ``good_against`` = the champs this champ BEATS (the most POSITIVE
                       this-vs-B net_swing) - favored matchups.
    Each is a list of ``{"champion": "<id>", "net_swing": <float>}`` sorted
    strongest-first.

FAIL-SOFT
    A missing / unreadable / malformed DB yields ``{}`` and every lookup
    yields ``[]``. The coach surface degrades to "no suggestion", never an
    exception. This mirrors ``core.event_callouts`` / ``core.lead_projection``
    (the W2 deterministic lane modules).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

# Project root: core/ -> C:\Riot Commander\
_ROOT = Path(__file__).resolve().parent.parent
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"

# Patch fallback when current.txt is missing (guards a fresh checkout only).
_FALLBACK_PATCH = "16.11.1"

# Cache keyed by (mode, patch) -> loaded payload dict. mtime-aware: a stale
# entry is dropped when the file on disk is newer than what we cached.
_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}


def _resolve_patch() -> str:
    """Read the active patch from current.txt; fall back to _FALLBACK_PATCH."""
    try:
        txt = _CURRENT_TXT.read_text(encoding="utf-8").strip()
        if txt:
            return txt
    except Exception:  # noqa: BLE001 - fail-soft to fallback
        pass
    return _FALLBACK_PATCH


def _db_path(patch: str) -> Path:
    """Path to the committed pick/ban targets DB for ``patch``."""
    return _DS_DIR / patch / "pickban_targets.json"


def load_pickban_targets(mode: str = "sr", patch: Optional[str] = None) -> dict:
    """Return the pick/ban targets payload for the active patch (or ``{}``).

    ``mode`` is reserved for a future per-mode DB; v1 ships a single SR table
    and ``mode`` only participates in the cache key. ``patch`` defaults to the
    value in ``data/daemon_slayer/current.txt``. Cached + mtime-aware;
    fail-soft to ``{}`` on any read / parse error.
    """
    use_patch = patch or _resolve_patch()
    key = (mode, use_patch)
    path = _db_path(use_patch)

    try:
        mtime = path.stat().st_mtime
    except Exception:  # noqa: BLE001 - missing file -> empty
        _CACHE.pop(key, None)
        return {}

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {}
    except Exception:  # noqa: BLE001 - malformed -> empty
        payload = {}

    _CACHE[key] = (mtime, payload)
    return payload


def _targets_for(champion: str, mode: str, patch: Optional[str]) -> dict:
    """Return the per-champion targets sub-dict (``{}`` when absent)."""
    if not champion:
        return {}
    payload = load_pickban_targets(mode=mode, patch=patch)
    targets = payload.get("targets")
    if not isinstance(targets, dict):
        return {}
    entry = targets.get(champion)
    return entry if isinstance(entry, dict) else {}


def _slice_list(rows: object, top_n: int) -> list[dict]:
    """Coerce + slice a stored row list to the first ``top_n`` valid dicts."""
    if not isinstance(rows, list) or top_n <= 0:
        return []
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict) and row.get("champion"):
            out.append(row)
        if len(out) >= top_n:
            break
    return out


def counters_for(
    champion: str,
    mode: str = "sr",
    top_n: int = 5,
    patch: Optional[str] = None,
) -> list[dict]:
    """Champs that BEAT ``champion`` (ban candidates), strongest-first.

    Each entry is ``{"champion": "<id>", "net_swing": <float>}`` (net_swing is
    ``champion``-vs-that-champ, so it is NEGATIVE when they beat ``champion``).
    Fail-soft -> ``[]`` on missing DB / champ.
    """
    entry = _targets_for(champion, mode, patch)
    return _slice_list(entry.get("counters"), top_n)


def good_against(
    champion: str,
    mode: str = "sr",
    top_n: int = 5,
    patch: Optional[str] = None,
) -> list[dict]:
    """Champs ``champion`` BEATS (favored matchups), strongest-first.

    Each entry is ``{"champion": "<id>", "net_swing": <float>}`` (POSITIVE
    net_swing = ``champion`` favored). Fail-soft -> ``[]``.
    """
    entry = _targets_for(champion, mode, patch)
    return _slice_list(entry.get("good_against"), top_n)


def ban_suggestions(
    my_champion: str,
    enemy_comp: Optional[list] = None,
    mode: str = "sr",
    top_n: int = 3,
    patch: Optional[str] = None,
) -> list[dict]:
    """Suggest bans = ``my_champion``'s strongest counters not already picked.

    Given the locked champ + the (partial) enemy comp, return the champs that
    beat ``my_champion`` hardest, EXCLUDING any already in ``enemy_comp`` (no
    point banning a champ the enemy already locked). Fail-soft -> ``[]``.

    v1 honesty: this is a self-defence heuristic - "ban what beats my pick" -
    derived from the same itemless lvl-9 duel verdicts, NOT a draft-theory
    ban model. ``enemy_comp`` is a list of DDragon ids (other shapes are
    tolerated: only string entries filter).
    """
    picked = {str(c) for c in (enemy_comp or []) if isinstance(c, str)}
    # Pull a wider counter slice, then filter out the already-picked, then cap.
    raw = counters_for(my_champion, mode=mode, top_n=max(top_n * 4, top_n),
                       patch=patch)
    out: list[dict] = []
    for row in raw:
        champ = row.get("champion")
        if champ and champ not in picked:
            out.append(row)
        if len(out) >= top_n:
            break
    return out
