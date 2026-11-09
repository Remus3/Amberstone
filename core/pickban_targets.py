# arch: deterministic pick/ban targets reader (matchup-engine DB) | section=core | frozen=no
"""Deterministic pick/ban targets reader (no LLM, no network, no engine call).

PURPOSE
    Read-time lookup over a precomputed per-champion pick/ban targets DB so the
    champ-select coach can suggest bans (counters) + good-against picks WITHOUT
    a Claude Haiku call. Serves the PRIMARY north star: drive live Haiku usage
    to ZERO. The DB is generated offline by
    ``tools/daemon_slayer_pickban_targets_generate.py`` and committed at
    ``data/daemon_slayer/<patch>/pickban_targets.json``.

    Reach (measured s144 cycle 245): no production module imports this reader
    today - ``dashboard/routes_pickban.py`` and ``dashboard/routes_ban_suggestions.py``
    carry their own counter sources. It is a library surface (tests and the
    offline tools name it), so say "unexercised, not unreachable".

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
    ``counters``     = the champs that BEAT this champ - ban candidates / be wary.
    ``good_against`` = the champs this champ BEATS - favored matchups.
    Each is a list of ``{"champion": "<id>", "net_swing": <float>, "rel": <float>}``
    sorted strongest-first by ``rel`` (the DE-BIASED relative-strength score, not
    raw net_swing). ``rel`` subtracts each candidate's global duel dominance so
    the lists are per-champ-SPECIFIC counters, not the same handful of globally
    strong duelists on every champ. ``net_swing`` is the raw this-vs-B value
    (NEGATIVE when they beat this champ); ``rel`` is the sort key. Tables built
    before the de-bias carry no ``rel``; a missing score is accepted.

ROW VALIDITY (read side; the committed tables all pass it unchanged)
    A row is kept only when it is a dict whose ``champion`` is a non-empty str
    that is not the looked-up champion itself, and whose ``net_swing`` / ``rel``,
    WHEN PRESENT, are finite non-bool reals. A repeated champion keeps its first
    (strongest) row. Junk rows are skipped, never returned, and the cap applies
    after the filter. Returned rows are COPIES: mutating them never reaches the
    cache.

PATCH
    ``patch`` names a directory under ``data/daemon_slayer``, so it must look
    like a version (``16.22.1`` or ``16.22``); anything else - a separator,
    ``..``, a non-str - reads as no table. ``current.txt`` is read BOM-tolerant
    (first line only); when it is missing or not a version, the NEWEST patch
    directory (numeric order) holding a table is used, then ``_FALLBACK_PATCH``.

FAIL-SOFT
    A missing / unreadable / malformed DB yields ``{}`` and every lookup
    yields ``[]``; so does a wrong-typed argument (champion, mode, top_n,
    patch). The coach surface degrades to "no suggestion", never an
    exception. Only a read (``OSError``) or parse (``ValueError`` /
    ``RecursionError``) failure is absorbed - anything else is a bug and
    raises. A malformed table logs one WARNING per file version (cached);
    a transient read error logs at DEBUG and is not cached (RM-443).
"""
from __future__ import annotations

import copy
import json
import logging
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Project root: core/ -> <repo>\
_ROOT = Path(__file__).resolve().parent.parent
_DS_DIR = _ROOT / "data" / "daemon_slayer"
_CURRENT_TXT = _DS_DIR / "current.txt"

# Last-resort patch when current.txt is unusable AND no patch directory holds
# a table (a stripped checkout). Normally _newest_table_patch() answers first.
_FALLBACK_PATCH = "16.11.1"

_DB_NAME = "pickban_targets.json"

# A patch is a directory name: two or three dot-separated small integers.
_PATCH_RE = re.compile(r"\d{1,3}\.\d{1,3}(?:\.\d{1,3})?")

# Cache keyed by (mode, patch) -> ((st_mtime_ns, st_size), payload). A rewrite
# changes the size or the ns mtime, so a coarse-clock same-second rewrite is
# still seen; a stale entry is replaced when the file identity differs.
_CACHE: dict[tuple[str, str], tuple[tuple[int, int], dict]] = {}


def _valid_patch(patch: object) -> bool:
    return isinstance(patch, str) and _PATCH_RE.fullmatch(patch) is not None


def _patch_key(patch: str) -> tuple[int, ...]:
    return tuple(int(p) for p in patch.split("."))


def _newest_table_patch() -> Optional[str]:
    """Newest (numeric order) patch directory that holds a table, or None."""
    try:
        names = [p.name for p in _DS_DIR.iterdir()]
    except OSError:
        return None
    best: Optional[str] = None
    for name in names:
        if not _valid_patch(name) or not (_DS_DIR / name / _DB_NAME).is_file():
            continue
        if best is None or _patch_key(name) > _patch_key(best):
            best = name
    return best


def _resolve_patch() -> str:
    """Active patch from current.txt, else the newest table, else fallback."""
    try:
        text = _CURRENT_TXT.read_text(encoding="utf-8-sig")
    except (OSError, ValueError):
        text = ""
    lines = text.strip().splitlines()
    first = lines[0].strip() if lines else ""
    if _valid_patch(first):
        return first
    return _newest_table_patch() or _FALLBACK_PATCH


def _db_path(patch: str) -> Path:
    """Path to the committed pick/ban targets DB for ``patch``."""
    return _DS_DIR / patch / _DB_NAME


def _load(mode: object, patch: object) -> dict:
    """Cached payload (the SHARED object - callers must not leak it)."""
    if not isinstance(mode, str):
        return {}
    if patch is None or patch == "":
        patch = _resolve_patch()
    if not _valid_patch(patch):
        return {}
    key = (mode, patch)
    path = _db_path(patch)

    try:
        st = path.stat()
    except OSError:
        _CACHE.pop(key, None)
        return {}
    ident = (st.st_mtime_ns, st.st_size)

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == ident:
        return cached[1]

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        # RM-443: a transient read error is NOT cached (the file will not
        # change again, so an entry under this identity would pin the empty
        # payload). Malformed CONTENT is deterministic per identity - cached.
        log.debug("pickban targets %s unreadable: %s", patch,
                  type(exc).__name__)
        return {}
    try:
        payload = json.loads(text)
    except (ValueError, RecursionError) as exc:
        log.warning("pickban targets %s malformed (%s); serving none",
                    patch, type(exc).__name__)
        payload = {}
    if not isinstance(payload, dict):
        log.warning("pickban targets %s root is %s, not an object; serving "
                    "none", patch, type(payload).__name__)
        payload = {}

    _CACHE[key] = (ident, payload)
    return payload


def load_pickban_targets(mode: str = "sr", patch: Optional[str] = None) -> dict:
    """Return the pick/ban targets payload for the active patch (or ``{}``).

    ``mode`` is reserved for a future per-mode DB; v1 ships a single SR table
    and ``mode`` (a str, else ``{}``) only participates in the cache key.
    ``patch`` defaults to the value in ``data/daemon_slayer/current.txt``
    (see PATCH in the module docstring). Cached + identity-aware; fail-soft
    to ``{}``. The return is a deep COPY, so a caller may mutate it freely.
    A table nested too deep to copy (``json.loads`` accepts ~990 levels,
    ``deepcopy`` recurses out near ~500) reads as ``{}``, never a raise.
    """
    try:
        return copy.deepcopy(_load(mode, patch))
    except RecursionError:
        log.warning("pickban targets %s nested too deep to copy; serving "
                    "none", patch)
        return {}


def _targets_for(champion: object, mode: object, patch: object) -> dict:
    """Return the per-champion targets sub-dict (``{}`` when absent)."""
    if not isinstance(champion, str) or not champion:
        return {}
    targets = _load(mode, patch).get("targets")
    if not isinstance(targets, dict):
        return {}
    entry = targets.get(champion)
    return entry if isinstance(entry, dict) else {}


def _valid_count(top_n: object) -> bool:
    return isinstance(top_n, int) and not isinstance(top_n, bool) and top_n > 0


def _finite_or_absent(row: dict, field: str) -> bool:
    if field not in row:
        return True
    value = row[field]
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _valid_rows(rows: object, champion: str, exclude: frozenset = frozenset()):
    """Yield COPIES of the valid, de-duplicated rows, in stored order."""
    if not isinstance(rows, list):
        return
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("champion")
        if not isinstance(name, str) or not name or name == champion:
            continue
        if not (_finite_or_absent(row, "net_swing")
                and _finite_or_absent(row, "rel")):
            continue
        if name in seen:
            continue
        seen.add(name)
        if name in exclude:
            continue
        yield dict(row)


def _rows(champion: object, field: str, mode: object, top_n: object,
          patch: object, exclude: frozenset = frozenset()) -> list[dict]:
    if not _valid_count(top_n):
        return []
    entry = _targets_for(champion, mode, patch)
    out: list[dict] = []
    for row in _valid_rows(entry.get(field), champion, exclude):
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

    Each entry is ``{"champion": "<id>", "net_swing": <float>, "rel": <float>}``
    (net_swing is ``champion``-vs-that-champ, so it is NEGATIVE when they beat
    ``champion``; ``rel`` may be absent on a pre-de-bias table). ``top_n`` is a
    positive int, else ``[]``. Fail-soft -> ``[]`` on missing DB / champ.
    """
    return _rows(champion, "counters", mode, top_n, patch)


def good_against(
    champion: str,
    mode: str = "sr",
    top_n: int = 5,
    patch: Optional[str] = None,
) -> list[dict]:
    """Champs ``champion`` BEATS (favored matchups), strongest-first.

    Each entry is ``{"champion": "<id>", "net_swing": <float>, "rel": <float>}``
    (POSITIVE net_swing = ``champion`` favored). ``top_n`` is a positive int,
    else ``[]``. Fail-soft -> ``[]``.
    """
    return _rows(champion, "good_against", mode, top_n, patch)


def _picked_ids(enemy_comp: object) -> frozenset:
    """The string ids in ``enemy_comp``; a bare str is ONE id."""
    if isinstance(enemy_comp, str):
        return frozenset((enemy_comp,)) if enemy_comp else frozenset()
    if isinstance(enemy_comp, (bytes, bytearray)) or not isinstance(
            enemy_comp, Iterable):
        return frozenset()
    return frozenset(c for c in enemy_comp if isinstance(c, str) and c)


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
    point banning a champ the enemy already locked). The exclusion runs over
    the WHOLE stored counter list before the cap, so however many enemies are
    locked, the next unpicked counter still surfaces. Fail-soft -> ``[]``.

    v1 honesty: this is a self-defence heuristic - "ban what beats my pick" -
    derived from the same itemless lvl-9 duel verdicts, NOT a draft-theory
    ban model. ``enemy_comp`` is an iterable of DDragon ids (only non-empty
    string entries filter; a bare string is one id; a non-iterable filters
    nothing).
    """
    return _rows(my_champion, "counters", mode, top_n, patch,
                 exclude=_picked_ids(enemy_comp))
