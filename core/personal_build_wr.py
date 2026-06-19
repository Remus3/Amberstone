"""core/personal_build_wr.py - personal per-champion build win-rate from the
LOCAL rewind_history.db.

Closes the "personal-WR build override (local-data half)" FUTURE item from
docs/COMPETITOR_LIFT_2026-06-16.md (the Overlay App E personal-WR build override). The DS
engine recommends a default build order; this surfaces which items the OPERATOR
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

Public API:
    compute_personal_build(champion, mode="sr", *, min_games=..., db_path=None) -> dict

The dict is the GET /api/personal-build contract; see _empty() for the shape.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

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

_REWIND_DB = Path(__file__).resolve().parent.parent / "data" / "rewind_history.db"
_DDRAGON_ROOT = Path(__file__).resolve().parent.parent / "data" / "daemon_slayer"

# Boots item ids (tier-2 SR + the 22-prefixed Arena mirrors) - tagged, not dropped.
_BOOTS_IDS = frozenset({
    "3006", "3009", "3020", "3047", "3111", "3117", "3158",
    "223006", "223009", "223020", "223047", "223111", "223117", "223158",
})

_META_CACHE: Optional[dict[str, dict]] = None


def _item_meta() -> dict[str, dict]:
    """id -> {name, gold} from the newest DDragon items.json. Fail-soft {}."""
    global _META_CACHE
    if _META_CACHE is not None:
        return _META_CACHE
    out: dict[str, dict] = {}
    try:
        import json
        dirs = sorted(
            (p for p in _DDRAGON_ROOT.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
        for d in reversed(dirs):
            f = d / "items.json"
            if not f.exists():
                continue
            raw = json.loads(f.read_text(encoding="utf-8"))
            data = raw.get("data") or {}
            for iid, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                gold = (entry.get("gold") or {}).get("total") or 0
                out[str(iid)] = {"name": str(entry.get("name") or ""), "gold": int(gold)}
            break
    except Exception:  # noqa: BLE001 - metadata is a nicety; ids stand alone
        out = {}
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


def _empty(champion: object, mode: str, n_games: int, reason: str) -> dict:
    return {
        "champion": str(champion) if champion is not None else None,
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


def _rows(
    conn: sqlite3.Connection, champion: object, map_id: int
) -> list[sqlite3.Row]:
    champ_name = str(champion).strip()
    try:
        champ_id = int(champion)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        champ_id = -1
    return conn.execute(
        "SELECT p.item0, p.item1, p.item2, p.item3, p.item4, p.item5, "
        "       m.tracked_win AS win "
        "FROM matches m JOIN participants p "
        "  ON p.match_id = m.match_id "
        " AND p.champion_id = m.tracked_champion_id "
        " AND p.team_id = m.tracked_team_id "
        "WHERE (m.tracked_champion_name = ? COLLATE NOCASE "
        "       OR m.tracked_champion_id = ?) "
        "  AND m.map_id = ? "
        "  AND (m.game_duration_s IS NULL OR m.game_duration_s >= ?)",
        (champ_name, champ_id, map_id, MIN_DURATION_S),
    ).fetchall()


def compute_personal_build(
    champion: object,
    mode: str = "sr",
    *,
    min_games: int = DEFAULT_MIN_GAMES,
    min_item_games: int = DEFAULT_MIN_ITEM_GAMES,
    db_path: Optional[Path] = None,
) -> dict:
    """Personal per-champion build win-rate from the operator's own history.

    Returns the /api/personal-build contract dict. Fail-soft: a missing DB,
    unknown champion, or thin sample yields an _empty() shell (never raises).
    """
    mode = (mode or "sr").lower()
    if mode not in MODE_MAPS:
        return _empty(champion, mode, 0, "bad_mode")
    map_id = MODE_MAPS[mode]
    if db_path is not None:
        path = Path(db_path)
    else:
        path = Path(os.environ.get("RC_REWIND_DB") or _REWIND_DB)
    if not path.exists():
        return _empty(champion, mode, 0, "no_db")

    conn = None
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        rows = _rows(conn, champion, map_id)
    except Exception:  # noqa: BLE001 - fail-soft empty rather than 500 the route
        return _empty(champion, mode, 0, "read_error")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    n_games = len(rows)
    if n_games < min_games:
        return _empty(champion, mode, n_games, "insufficient")

    n_wins = sum(1 for r in rows if r["win"])
    baseline = n_wins / n_games

    # Per-item games/wins over the final-build slots (item0-5; trinket excluded).
    # Only completed legendaries + boots count - leftover components are dropped.
    meta = _item_meta()
    item_games: dict[str, int] = {}
    item_wins: dict[str, int] = {}
    build_counts: dict[tuple[str, ...], int] = {}
    for r in rows:
        won = bool(r["win"])
        core: list[str] = []
        for slot in ("item0", "item1", "item2", "item3", "item4", "item5"):
            iid = r[slot]
            if not iid:
                continue
            sid = str(iid)
            if not _is_core(sid, meta):
                continue
            item_games[sid] = item_games.get(sid, 0) + 1
            item_wins[sid] = item_wins.get(sid, 0) + (1 if won else 0)
            core.append(sid)
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
            "item_id": int(sid) if sid.isdigit() else sid,
            "name": meta.get(sid, {}).get("name", ""),
            "games": g,
            "wins": w,
            "win_rate": round(raw, 4),
            "adj_win_rate": round(est, 4),
            "lift": round(est - baseline, 4),
            "is_boots": sid in _BOOTS_IDS,
        })
    scored.sort(key=lambda d: d["lift"], reverse=True)

    most_common: list[int] = []
    if build_counts:
        modal = max(build_counts.items(), key=lambda kv: kv[1])[0]
        most_common = [int(s) if s.isdigit() else s for s in modal]

    confidence = "ok" if n_games >= _THIN_GAMES else "thin"
    champ_str = str(champion).strip()
    return {
        "champion": champ_str,
        "champion_id": int(champ_str) if champ_str.isdigit() else None,
        "mode": mode,
        "games": n_games,
        "win_rate": round(baseline, 4),
        "baseline_win_rate": round(baseline, 4),
        "confidence": confidence,
        "items": scored[:_TOP_ITEMS],
        "most_common_build": most_common,
        "source": "rewind_history.db",
    }
