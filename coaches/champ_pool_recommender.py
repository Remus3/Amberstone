"""
coaches/champ_pool_recommender.py - champ-select pool recommendation.

AUDIT 2026-04-28 (suggestion 2.6): given the enemy comp seen in champ-
select and the user's pool of comfort picks, score each pick against
recorded performance vs that exact (or similar) enemy comp using
data/rewind_history.db (2846 matches as of writing).

API:
    recommend(my_pool, enemy_comp, *, min_games=3) -> list[dict]

Each recommendation row carries:
    {champion, games, wins, win_pct, avg_kda, score,
     sample: "vs comp" | "vs any"}

`sample = "vs comp"` means we found enough games matching the exact
enemy comp; `"vs any"` falls back to the full champion history when we
couldn't gather min_games of comp-matched data.

Performance score is a simple win-pct weighted by sample size so a
70% wr in 4 games doesn't outrank 60% wr in 40 games.

Wiring: dashboard route was retired in item 186 (zero callers). The
`recommend()` function is still imported directly by scripts/build_champ_kda.py
and remains available for any future dashboard or coach surface.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Optional

_log = logging.getLogger("rc.champ_pool_recommender")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB    = _PROJECT_ROOT / "data" / "rewind_history.db"
_DDR_CHAMPS   = _PROJECT_ROOT / "data" / "meta" / "ddragon_champions.json"
# AUDIT 2026-04-29: pre-aggregated KDA file produced by
# scripts/build_champ_kda.py. When fresh, _kda_for reads from this
# instead of folding 2.5M timeline_events live (~10s cold) -> ~50 ms
# warm-DB lookup. Missing / stale file falls through to live SQL.
_KDA_FILE = _PROJECT_ROOT / "data" / "coach_reference" / "champ_kda.json"

# Lazy-loaded user puuid + champion-name -> id map.
_user_puuid: Optional[str] = None
_name_to_id: dict[str, int] = {}
_id_to_name: dict[int, str] = {}
_kda_materialized: Optional[dict] = None
_kda_mtime: float = 0.0
_cache_lock = threading.Lock()


def _load_champ_index() -> None:
    """Populate name ↔ id maps from DDragon champion data."""
    global _name_to_id, _id_to_name
    if _name_to_id:
        return
    try:
        data = json.loads(_DDR_CHAMPS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("ddragon_champions read failed: %s", exc)
        return
    new_n2i: dict[str, int] = {}
    new_i2n: dict[int, str] = {}
    for slug, entry in (data.get("data") or {}).items():
        try:
            cid = int(entry.get("key"))
        except (TypeError, ValueError):
            continue
        name = entry.get("name") or slug
        # Index by both the display name + the slug so callers can use
        # either ("Cho'Gath" or "Chogath").
        new_n2i[name.lower()] = cid
        new_n2i[slug.lower()] = cid
        new_i2n[cid] = name
    _name_to_id = new_n2i
    _id_to_name = new_i2n


def _resolve_user_puuid(c: sqlite3.Connection) -> Optional[str]:
    """Pick the puuid that played the most tracked-champion games. In
    practice this is unambiguous - the DB only has one user's history."""
    global _user_puuid
    if _user_puuid is not None:
        return _user_puuid
    row = c.execute(
        """
        SELECT p.puuid, COUNT(*) AS games
        FROM matches m
        JOIN participants p
          ON p.match_id = m.match_id AND p.champion_id = m.tracked_champion_id
        WHERE m.tracked_champion_id IS NOT NULL
        GROUP BY p.puuid
        ORDER BY games DESC
        LIMIT 1
        """
    ).fetchone()
    _user_puuid = row["puuid"] if row else None
    if _user_puuid:
        _log.info("rewind_history user puuid resolved (%d games on top puuid)",
                  row["games"])
    return _user_puuid


def _open() -> Optional[sqlite3.Connection]:
    if not _REWIND_DB.exists():
        return None
    try:
        c = sqlite3.connect(str(_REWIND_DB))
        c.row_factory = sqlite3.Row
        return c
    except sqlite3.Error as exc:
        _log.warning("rewind_history open: %s", exc)
        return None


def _games_on_champ(c: sqlite3.Connection, puuid: str, champ_id: int) -> list[dict]:
    """All games the user played that champion. Returns rows with
    match_id, team_id, win, kills/deaths/assists. Enemy-team champions
    surfaced in a sub-query is left to the caller (kept cheap)."""
    return [dict(r) for r in c.execute(
        """
        SELECT m.match_id, p.team_id,
               t.win,
               COALESCE((SELECT GROUP_CONCAT(p2.champion_name)
                         FROM participants p2
                         WHERE p2.match_id = m.match_id
                           AND p2.team_id != p.team_id), '') AS enemy_comp_csv
        FROM matches m
        JOIN participants p ON p.match_id = m.match_id AND p.puuid = ?
        JOIN teams      t ON t.match_id = m.match_id AND t.team_id = p.team_id
        WHERE p.champion_id = ?
        """,
        (puuid, champ_id),
    ).fetchall()]


def _load_materialized_kda() -> Optional[dict]:
    """AUDIT 2026-04-29: load champ_kda.json if mtime changed. The file
    is keyed champ_id-as-string → {games, kills, deaths, assists}."""
    global _kda_materialized, _kda_mtime
    if not _KDA_FILE.exists():
        return None
    try:
        mt = _KDA_FILE.stat().st_mtime
    except OSError:
        return None
    if _kda_materialized is not None and mt == _kda_mtime:
        return _kda_materialized
    with _cache_lock:
        if _kda_materialized is not None and mt == _kda_mtime:
            return _kda_materialized
        try:
            data = json.loads(_KDA_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _kda_materialized   # keep prior cache on parse error
        _kda_materialized = (data.get("champions") or {}) if isinstance(data, dict) else None
        _kda_mtime = mt
    return _kda_materialized


def _kda_for(c: sqlite3.Connection, puuid: str, champ_id: int) -> tuple[int, int, int, int]:
    """(kills, deaths, assists, games) summed across the user's games on
    the champion. AUDIT 2026-04-29: prefers data/coach_reference/
    champ_kda.json (built by scripts/build_champ_kda.py) when present -
    that path is ~50 ms vs ~474 ms for the live timeline_events fold.
    Live SQL is the fallback when the file is missing or doesn't have
    this champ_id (e.g. user picked up a new champ since last build)."""
    cache = _load_materialized_kda()
    if cache:
        entry = cache.get(str(champ_id))
        if entry:
            return (int(entry.get("kills", 0)),
                    int(entry.get("deaths", 0)),
                    int(entry.get("assists", 0)),
                    int(entry.get("games", 0)))
    # Live-SQL fallback (original implementation).
    # timeline_events has CHAMPION_KILL events. Match-scoped JOIN against
    # participants by puuid + champion_id gives the user's row in each
    # match - kills/deaths are counted by killer_id/victim_id; assists
    # use a JSON-substring LIKE which is good enough for an O(2.5M-row)
    # one-shot read once per recommendation request.
    cur = c.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM timeline_events e
             JOIN participants me
               ON me.match_id = e.match_id
              AND me.participant_id = e.killer_id
             WHERE e.event_type = 'CHAMPION_KILL'
               AND me.puuid = ? AND me.champion_id = ?) AS kills,
          (SELECT COUNT(*) FROM timeline_events e
             JOIN participants me
               ON me.match_id = e.match_id
              AND me.participant_id = e.victim_id
             WHERE e.event_type = 'CHAMPION_KILL'
               AND me.puuid = ? AND me.champion_id = ?) AS deaths,
          (SELECT COUNT(*) FROM timeline_events e
             JOIN participants me
               ON me.match_id = e.match_id
             WHERE e.event_type = 'CHAMPION_KILL'
               AND me.puuid = ? AND me.champion_id = ?
               AND e.assisting_ids_json LIKE '%' || me.participant_id || '%') AS assists,
          (SELECT COUNT(*) FROM participants p
             WHERE p.puuid = ? AND p.champion_id = ?) AS games
        """,
        (puuid, champ_id, puuid, champ_id, puuid, champ_id, puuid, champ_id),
    ).fetchone()
    if not cur:
        return (0, 0, 0, 0)
    return (cur["kills"] or 0, cur["deaths"] or 0,
            cur["assists"] or 0, cur["games"] or 0)


def _comp_overlap(comp_csv: str, target: set[str]) -> int:
    if not comp_csv or not target:
        return 0
    cs = {c.strip().lower() for c in comp_csv.split(",") if c.strip()}
    return len(cs & target)


def _score(win_pct: float, games: int) -> float:
    """Confidence-weighted win pct. games=0 → 0; games≥30 → ~win_pct."""
    if games <= 0:
        return 0.0
    weight = games / (games + 8.0)        # asymptote at 1.0; ~50% weight at 8 games
    baseline = 0.50                        # neutral pull toward 50% wr
    return baseline + (win_pct - baseline) * weight


def recommend(my_pool: Iterable[str],
              enemy_comp: Iterable[str],
              *, min_games: int = 3) -> list[dict]:
    """Score each champion in `my_pool` against the recorded performance
    vs `enemy_comp`. Returns rows sorted by `score` (desc).

    Empty rewind history → returns []."""
    _load_champ_index()
    c = _open()
    if c is None:
        return []
    try:
        puuid = _resolve_user_puuid(c)
        if not puuid:
            return []

        target_enemy = {n.strip().lower() for n in enemy_comp if n}
        out: list[dict] = []
        for champ in my_pool:
            if not champ:
                continue
            cid = _name_to_id.get(str(champ).lower())
            if not cid:
                _log.debug("recommend: unknown champion %r - skipping", champ)
                continue
            games = _games_on_champ(c, puuid, cid)
            if not games:
                continue
            # Bucket: games where enemy comp overlaps target by >= 2.
            comp_games = [g for g in games
                          if _comp_overlap(g["enemy_comp_csv"], target_enemy) >= 2]
            sample_label = "vs comp" if len(comp_games) >= min_games else "vs any"
            sample = comp_games if sample_label == "vs comp" else games
            wins = sum(1 for g in sample if g["win"])
            played = len(sample)
            win_pct = wins / played if played else 0.0
            kk, dd, aa, _ = _kda_for(c, puuid, cid)
            out.append({
                "champion":  _id_to_name.get(cid, str(champ)),
                "champ_id":  cid,
                "games":     played,
                "wins":      wins,
                "win_pct":   round(win_pct * 100, 1),
                "avg_kda":   round((kk + aa) / max(dd, 1), 2),
                "score":     round(_score(win_pct, played) * 100, 1),
                "sample":    sample_label,
                "total_games_on_champ": len(games),
            })
        out.sort(key=lambda r: r["score"], reverse=True)
        return out
    finally:
        try:
            c.close()
        except sqlite3.Error:
            pass
