"""core/personal_build_wr.py - personal per-champion build win-rate from the
LOCAL rewind_history.db.

Closes the "personal-WR build override (local-data half)" FUTURE item from
docs/_archive/COMPETITOR_LIFT_2026-06-16.md (the Overlay App E personal-WR build
override). The DS engine recommends a default build order; this surfaces which items the OPERATOR
actually wins with on a given champion, computed from their OWN match history -
no Riot API, no Claude, no DS schema lift. Mirrors core/player_gpi's local-DB,
self-relative, fail-soft design and reuses core/smoothed_rates so a 2-0 item does
not outrank a 40-26 one.

This is an ADDITIVE read (NOT a change to the DS default ranking): a "your best
build" signal alongside the engine recommendation. Items are scored by their
confidence-weighted win-rate LIFT vs the player's own baseline win-rate on the
champion - a positive lift means "you win more when this item is in the final
build", shrunk toward the baseline by sample size so a thin item cannot dominate.

The build snapshot is the END-OF-GAME item set (rewind_history stores final
items), so components have mostly already completed into legendaries; the item0-5
slots are dominated by finished items + boots. item6 (trinket) is excluded.

Sample rules (s144 true-audit, RM-1908..RM-1916):
- only a RESOLVED game counts: tracked_win 0 / 1 (or a bool). An unknown result
  (NULL, 2, text) is skipped, never read as a loss; "games" is resolved games.
- a match counts once even when the participants table holds its tracked row
  twice (that table has no unique key, so a re-scrape can duplicate a row), and
  an item counts once per game even when it fills two slots.
- an item id is an ASCII-digit id from an int, an integral float or a padded
  digit string; anything else in a slot is skipped.
- ties (equal lift, equal modal-build count) are broken by stable keys, never
  by SQLite row order.
- the DB is opened READ-ONLY, so a read never creates or writes it.

Public API:
    compute_personal_build(champion, mode="sr", *, min_games=..., db_path=None) -> dict

The dict is the GET /api/personal-build contract; see _empty() for the shape.
``confidence`` is one of ok | thin | insufficient (verdicts about the data) or
bad_mode | bad_champion | no_db | read_error (the request or the store is
unusable). Never raises.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

from core.failed_load_gate import FailedLoadGate
from core.smoothed_rates import DEFAULT_K, blend, shrink

# Rift map ids, same basis as core.player_gpi.MODE_MAPS.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}

DEFAULT_MIN_GAMES = 8        # below this the per-item baseline is too thin to surface
DEFAULT_MIN_ITEM_GAMES = 4   # an item needs this many games before it is scored
MIN_DURATION_S = 300         # drop remakes / very-early surrenders
_THIN_GAMES = 20             # min_games <= n < this -> "thin" confidence
_TOP_ITEMS = 6               # cap the returned ranked-item list
# End-of-game snapshots include unfinished components; rank only completed
# legendaries + boots so "your best build" is not muddied by leftover parts.
LEGENDARY_GOLD_FLOOR = 2000

# Largest id accepted for a champion or an item. Real ids are well under it
# (Arena mirrors are 6 digits); anything past it is junk, and it keeps every
# bound parameter inside SQLite's 64-bit INTEGER.
_MAX_ID = 10 ** 9
# Digits in the largest accepted id, checked BEFORE int(): int() raises
# ValueError on a digit string past sys.get_int_max_str_digits() (4300).
_MAX_ID_DIGITS = len(str(_MAX_ID))
_MAX_CHAMPION_CHARS = 64

_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"
_DDRAGON_ROOT = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"
_PATCH_DIR_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SLOTS = ("item0", "item1", "item2", "item3", "item4", "item5")

# Boots item ids (tier-2 SR + the 22-prefixed Arena mirrors) - tagged, not dropped.
_BOOTS_IDS = frozenset({
    "3006", "3009", "3020", "3047", "3111", "3117", "3158",
    "223006", "223009", "223020", "223047", "223111", "223117", "223158",
})

_META_CACHE: Optional[dict[str, dict]] = None
# RM-443: a failed load is NOT cached - retried after the gate's backoff and
# warned once per failure streak (core/failed_load_gate.py).
_META_GATE = FailedLoadGate()
_log = logging.getLogger(__name__)


def _norm_id(value: object) -> Optional[str]:
    """Canonical ASCII-digit id string for *value*, or None when it is not one.

    Accepts a non-bool int, an integral finite float (a REAL column) and a
    padded ASCII-digit string; the result has no sign and no leading zeros.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, str):
        text = value.strip()
        if not (text and text.isascii() and text.isdigit()):
            return None
        text = text.lstrip("0") or "0"
        if len(text) > _MAX_ID_DIGITS:
            return None
        value = int(text)
    if isinstance(value, int) and 0 < value < _MAX_ID:
        return str(value)
    return None


def _as_win(value: object) -> Optional[bool]:
    """tracked_win -> True / False for a resolved result, None when unknown."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return value == 1
    return None


def _floor(value: object, default: int) -> int:
    """A sample floor: a non-bool int clamped to >= 1; anything else -> default."""
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, value)
    return default


def _gold_total(gold: object) -> int:
    """DDragon ``gold.total`` as a non-negative int; junk reads as 0."""
    total = gold.get("total") if isinstance(gold, dict) else None
    if isinstance(total, bool):
        return 0
    if isinstance(total, float):
        if not math.isfinite(total):
            return 0
        total = int(total)
    return total if isinstance(total, int) and total > 0 else 0


def _parse_items(raw: object) -> dict[str, dict]:
    """id -> {name, gold} from one parsed items.json; {} when unusable.

    A malformed ENTRY is skipped (or keeps a 0 gold / empty name), never the
    whole file: one bad row must not demote every legendary to a component.
    """
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for iid, entry in data.items():
        sid = _norm_id(iid)
        if sid is None or not isinstance(entry, dict):
            continue
        name = entry.get("name")
        out[sid] = {"name": name if isinstance(name, str) else "",
                    "gold": _gold_total(entry.get("gold"))}
    return out


def _item_meta() -> dict[str, dict]:
    """id -> {name, gold} from the newest USABLE DDragon items.json. Fail-soft {}.

    Patch dirs are tried newest first; an unreadable or unusable items.json
    falls back to the next older one. Finding none is a FAILURE (not cached,
    retried after the gate's backoff), never a cached empty map.
    """
    global _META_CACHE
    if _META_CACHE is not None:
        return _META_CACHE
    if not _META_GATE.should_attempt():
        return {}
    problem = "no usable items.json"
    out: dict[str, dict] = {}
    try:
        # RM-990: semver dirs compared as integers; a name sort read 16.9.1
        # after 16.21.1, and gold here decides which items count as completed.
        dirs = sorted(
            (p for p in _DDRAGON_ROOT.iterdir() if p.is_dir() and _PATCH_DIR_RE.match(p.name)),
            key=lambda p: tuple(int(x) for x in p.name.split(".")),
        )
    except OSError as exc:
        dirs = []
        problem = f"cannot list {_DDRAGON_ROOT.name}: {exc}"
    for d in reversed(dirs):
        f = d / "items.json"
        if not f.is_file():
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        # ValueError covers bad JSON and bad UTF-8; RecursionError is a
        # pathologically nested file (json.loads recurses per level).
        except (OSError, ValueError, RecursionError) as exc:
            problem = f"{d.name}/items.json unreadable: {exc}"
            continue
        out = _parse_items(raw)
        if out:
            break
        problem = f"{d.name}/items.json has no usable item entries"
    if not out:
        if _META_GATE.record_failure():
            _log.warning("personal_build_wr: item metadata load failed: %s", problem)
        return {}
    _META_GATE.record_success()
    _META_CACHE = out
    return out


def _is_core(sid: str, meta: dict[str, dict]) -> bool:
    """A completed legendary or boots - not a leftover component."""
    if sid in _BOOTS_IDS:
        return True
    return meta.get(sid, {}).get("gold", 0) >= LEGENDARY_GOLD_FLOOR


def reset_cache() -> None:
    """Drop the cached item-meta map so the next read re-pulls. Used by tests."""
    global _META_CACHE
    _META_CACHE = None
    _META_GATE.reset()


def _empty(champion: Optional[str], mode: Optional[str], n_games: int,
           reason: str) -> dict:
    return {
        "champion": champion,
        "champion_id": None,
        "mode": mode,
        "games": n_games,
        "win_rate": None,
        "baseline_win_rate": None,
        "confidence": reason,
        "items": [],
        "most_common_build": [],
        "source": "rewind_history.db",
    }


def _norm_mode(mode: object) -> Optional[str]:
    """'sr' for None / blank, the stripped lowercase str otherwise; None if not a str."""
    if mode is None:
        return "sr"
    if not isinstance(mode, str):
        return None
    return mode.strip().lower() or "sr"


def _norm_champion(champion: object) -> Optional[tuple[str, int]]:
    """(lookup name, champion id or -1) for a usable champion, else None.

    A champion is a non-blank str (a display name or an ASCII-digit id) or a
    non-bool int id. A bool, None, float or bytes is NOT an id (int(True) is 1,
    Annie), a blank name would match rows whose tracked name was never
    captured, and a non-ASCII digit string is a name, not an id.
    """
    if isinstance(champion, bool):
        return None
    if isinstance(champion, int):
        return (str(champion), champion) if 0 < champion < _MAX_ID else None
    if not isinstance(champion, str):
        return None
    name = champion.strip()
    if not name or len(name) > _MAX_CHAMPION_CHARS:
        return None
    try:
        name.encode("utf-8")  # a lone surrogate cannot be bound by sqlite3
    except UnicodeEncodeError:
        return None
    sid = _norm_id(name)
    return name, (int(sid) if sid is not None else -1)


def _db_path(db_path: object) -> Optional[Path]:
    if db_path is None:
        return Path(os.environ.get("RC_REWIND_DB") or _REWIND_DB)
    try:
        return Path(db_path)
    except TypeError:  # not a str / PathLike, or an __fspath__ that is not a str
        return None


def _connect_ro(path: Path) -> sqlite3.Connection:
    """Read-only connection: never creates the file, never writes it."""
    # as_uri() percent-encodes a '#', '%' or '?' in the path (an f-string
    # "file:{path}" does not); same form as core/aram_item_interaction.py.
    return sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)


def _rows(
    conn: sqlite3.Connection, name: str, champ_id: int, map_id: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT m.match_id AS mid, "
        "       p.item0, p.item1, p.item2, p.item3, p.item4, p.item5, "
        "       m.tracked_win AS win "
        "FROM matches m JOIN participants p "
        "  ON p.match_id = m.match_id "
        " AND p.champion_id = m.tracked_champion_id "
        " AND p.team_id = m.tracked_team_id "
        "WHERE (m.tracked_champion_name = ? COLLATE NOCASE "
        "       OR m.tracked_champion_id = ?) "
        "  AND m.map_id = ? "
        "  AND (m.game_duration_s IS NULL OR m.game_duration_s >= ?) "
        "ORDER BY m.match_id, p.rowid",
        (name, champ_id, map_id, MIN_DURATION_S),
    ).fetchall()


def _games(rows: list[sqlite3.Row]) -> list[tuple[bool, list[str]]]:
    """(won, distinct item ids) per resolved match; first row per match wins."""
    seen: set = set()
    out: list[tuple[bool, list[str]]] = []
    for r in rows:
        mid = r["mid"]
        if mid in seen:
            continue
        seen.add(mid)
        won = _as_win(r["win"])
        if won is None:
            continue
        items: list[str] = []
        for slot in _SLOTS:
            sid = _norm_id(r[slot])
            if sid is not None and sid not in items:
                items.append(sid)
        out.append((won, items))
    return out


def compute_personal_build(
    champion: object,
    mode: object = "sr",
    *,
    min_games: object = DEFAULT_MIN_GAMES,
    min_item_games: object = DEFAULT_MIN_ITEM_GAMES,
    db_path: object = None,
) -> dict:
    """Personal per-champion build win-rate from the operator's own history.

    Returns the /api/personal-build contract dict. Fail-soft: a bad mode or
    champion, a missing or unreadable DB, or a thin sample yields an _empty()
    shell (never raises).
    """
    champ = _norm_champion(champion)
    norm_mode = _norm_mode(mode)
    if norm_mode is None or norm_mode not in MODE_MAPS:
        return _empty(champ[0] if champ else None, norm_mode, 0, "bad_mode")
    map_id = MODE_MAPS[norm_mode]
    if champ is None:
        return _empty(None, norm_mode, 0, "bad_champion")
    name, champ_id = champ
    min_games = _floor(min_games, DEFAULT_MIN_GAMES)
    min_item_games = _floor(min_item_games, DEFAULT_MIN_ITEM_GAMES)

    path = _db_path(db_path)
    # is_file, not exists: a Windows device name (CON, NUL, con.db) "exists",
    # and a read-only URI open of one blocks forever.
    if path is None or not path.is_file():
        return _empty(name, norm_mode, 0, "no_db")

    conn = None
    try:
        conn = _connect_ro(path)
        conn.row_factory = sqlite3.Row
        games = _games(_rows(conn, name, champ_id, map_id))
    except (sqlite3.Error, OSError, ValueError) as exc:
        # fail-soft empty rather than 500 the route; read_error is not cached
        # by the route, so this logs at debug to stay quiet on a poll loop.
        _log.debug("personal_build_wr: rewind db read failed: %s", exc)
        return _empty(name, norm_mode, 0, "read_error")
    finally:
        if conn is not None:
            conn.close()

    n_games = len(games)
    if n_games < min_games:
        return _empty(name, norm_mode, n_games, "insufficient")

    n_wins = sum(1 for won, _ in games if won)
    baseline = n_wins / n_games

    # Per-item games/wins over the final-build slots (item0-5; trinket excluded).
    # Only completed legendaries + boots count - leftover components are dropped.
    meta = _item_meta()
    item_games: dict[str, int] = {}
    item_wins: dict[str, int] = {}
    build_counts: dict[tuple[str, ...], int] = {}
    for won, items in games:
        core = [sid for sid in items if _is_core(sid, meta)]
        for sid in core:
            item_games[sid] = item_games.get(sid, 0) + 1
            item_wins[sid] = item_wins.get(sid, 0) + (1 if won else 0)
        key = tuple(sorted(core))
        if key:
            build_counts[key] = build_counts.get(key, 0) + 1

    scored = []
    for sid, g in item_games.items():
        if g < min_item_games:
            continue
        w = item_wins[sid]
        raw = w / g
        weight = shrink(g, DEFAULT_K)          # n / (n + K)
        est = blend(raw, baseline, weight)     # toward the player's baseline
        scored.append({
            "item_id": int(sid),
            "name": meta.get(sid, {}).get("name", ""),
            "games": g,
            "wins": w,
            "win_rate": round(raw, 4),
            "adj_win_rate": round(est, 4),
            "lift": round(est - baseline, 4),
            "is_boots": sid in _BOOTS_IDS,
        })
    # Lift first; ties go to the larger sample, then the lower id.
    scored.sort(key=lambda d: (-d["lift"], -d["games"], d["item_id"]))

    most_common: list[int] = []
    if build_counts:
        # Highest count; a tie goes to the fuller build, then the lower ids.
        modal = min(build_counts.items(),
                    key=lambda kv: (-kv[1], -len(kv[0]), [int(s) for s in kv[0]]))[0]
        most_common = [int(s) for s in modal]

    confidence = "ok" if n_games >= _THIN_GAMES else "thin"
    return {
        "champion": name,
        "champion_id": champ_id if champ_id > 0 else None,
        "mode": norm_mode,
        "games": n_games,
        "win_rate": round(baseline, 4),
        "baseline_win_rate": round(baseline, 4),
        "confidence": confidence,
        "items": scored[:_TOP_ITEMS],
        "most_common_build": most_common,
        "source": "rewind_history.db",
    }
