"""
coaches/champ_pool_recommender.py - champ-select pool recommendation.

AUDIT 2026-04-28 (suggestion 2.6): given the enemy comp seen in champ-
select and the user's pool of comfort picks, score each pick against
recorded performance vs that exact (or similar) enemy comp using
data/rewind_history.db (2846 matches as of writing).

API:
    recommend(my_pool, enemy_comp, *, min_games=3) -> list[dict]

Each recommendation row carries:
    {champion, champ_id, games, wins, win_pct, avg_kda, score,
     sample: "vs comp" | "vs any", total_games_on_champ}

`sample = "vs comp"` means we found enough games matching the exact
enemy comp; `"vs any"` falls back to the full champion history when we
couldn't gather min_games of comp-matched data. A game matches the comp
when at least two of its enemy champions are in `enemy_comp`, compared by
champion ID (lane 8 s144 cycle 237: participants carry Riot's internal
name - "Kaisa", "Chogath" - so a display-name compare never matched 22
champions). A name the champion index cannot resolve is still compared by
name.

Performance score is a simple win-pct weighted by sample size so a
70% wr in 4 games doesn't outrank 60% wr in 40 games.

Inputs are untrusted shapes: a bare string is one name (never iterated
per character), non-string members are dropped, duplicates collapse to
one row, and a junk `min_games` (bool, non-int) falls back to the default
while a value below 1 is clamped to 1. A rewind DB that is missing,
locked, corrupt or missing a table answers [] and logs a warning; the DB
is opened read-only.

Wiring: no production caller - the dashboard route was retired in item
186. scripts/build_champ_kda.py BUILDS the KDA file this module reads; it
does not import `recommend()`. The function remains available for any
future dashboard or coach surface.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from core.resolved_wr import resolution_select, resolved_wr, wr_pct

_log = logging.getLogger("rc.champ_pool_recommender")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB    = _PROJECT_ROOT / "data" / "rewind_history.db"
_DDR_CHAMPS   = _PROJECT_ROOT / "data" / "meta" / "ddragon_champions.json"
# AUDIT 2026-04-29: pre-aggregated KDA file produced by
# scripts/build_champ_kda.py. When present, _kda_for reads from this
# instead of folding 2.5M timeline_events live (~10s cold) -> ~50 ms
# warm-DB lookup. A missing file, a champion absent from it, or a junk
# entry falls through to live SQL. The file is NOT checked for staleness
# against the DB: rebuild it with scripts/build_champ_kda.py.
_KDA_FILE = _PROJECT_ROOT / "data" / "coach_reference" / "champ_kda.json"

_DEFAULT_MIN_GAMES = 3
_KDA_KEYS = ("kills", "deaths", "assists", "games")

# Lazy-loaded user puuid + champion-name -> id map.
_user_puuid: Optional[str] = None
_name_to_id: dict[str, int] = {}
_id_to_name: dict[int, str] = {}
_kda_materialized: Optional[dict] = None
_kda_mtime: float = 0.0
_cache_lock = threading.Lock()


def _load_champ_index() -> None:
    """Populate name <-> id maps from DDragon champion data. A junk shape
    (non-dict root, non-dict ``data``, non-dict entry) is skipped, never
    raised; a missing or non-string display name falls back to the slug."""
    global _name_to_id, _id_to_name
    if _name_to_id:
        return
    try:
        data = json.loads(_DDR_CHAMPS.read_text(encoding="utf-8"))
    # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _log.warning("ddragon_champions read failed: %s", exc)
        return
    champs = data.get("data") if isinstance(data, dict) else None
    if not isinstance(champs, dict):
        _log.warning("ddragon_champions has no champion map (got %s)",
                     type(champs).__name__)
        return
    new_n2i: dict[str, int] = {}
    new_i2n: dict[int, str] = {}
    for slug, entry in champs.items():
        if not isinstance(entry, dict):
            continue
        try:
            cid = int(entry.get("key"))
        except (TypeError, ValueError):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            name = slug
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
    """Read-only connection to the rewind DB, or None when it is absent
    or cannot be opened. Read-only (URI ``mode=ro``) so a race with the
    exists() check can never create an empty DB and no statement here
    can write; the caller closes it."""
    if not _REWIND_DB.exists():
        return None
    try:
        c = sqlite3.connect(_REWIND_DB.resolve().as_uri() + "?mode=ro",
                            uri=True)
    except sqlite3.Error as exc:
        _log.warning("rewind_history open: %s", exc)
        return None
    c.row_factory = sqlite3.Row
    return c


def _participant_has_win(c: sqlite3.Connection) -> bool:
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(participants)")}
    except sqlite3.Error:
        return False
    return "win" in cols


def _games_on_champ(c: sqlite3.Connection, puuid: str, champ_id: int) -> list[dict]:
    """All games the user played that champion. Returns rows with
    match_id, team_id, win and the enemy team as two CSVs: champion IDs
    (``enemy_ids_csv``) and Riot's internal names (``enemy_comp_csv``).

    RM-610: remake signals (game_duration_s, early surrender) ride along
    when the schema has them so core.resolved_wr can drop remakes from the
    WR denominator.

    S144-T-94: ``teams`` is LEFT-joined and the seat's own
    ``participants.win`` answers when no team row exists (measured: all
    60 of the user's Arena seats have none, and the inner join dropped
    every one). Where both exist the team row stays the authority."""
    extra = resolution_select(c, "m")
    win = "COALESCE(t.win, p.win)" if _participant_has_win(c) else "t.win"
    return [dict(r) for r in c.execute(
        f"""
        SELECT m.match_id, p.team_id,
               {win} AS win{extra},
               COALESCE((SELECT GROUP_CONCAT(p2.champion_id)
                         FROM participants p2
                         WHERE p2.match_id = m.match_id
                           AND p2.team_id != p.team_id), '') AS enemy_ids_csv,
               COALESCE((SELECT GROUP_CONCAT(p2.champion_name)
                         FROM participants p2
                         WHERE p2.match_id = m.match_id
                           AND p2.team_id != p.team_id), '') AS enemy_comp_csv
        FROM matches m
        JOIN participants p ON p.match_id = m.match_id AND p.puuid = ?
        LEFT JOIN teams t ON t.match_id = m.match_id AND t.team_id = p.team_id
        WHERE p.champion_id = ?
        """,
        (puuid, champ_id),
    ).fetchall()]


def _load_materialized_kda() -> Optional[dict]:
    """AUDIT 2026-04-29: load champ_kda.json if mtime changed. The file
    is keyed champ_id-as-string -> {games, kills, deaths, assists}. A
    root or ``champions`` value that is not a dict caches as {} (no
    entries, so every champion uses live SQL) instead of raising later."""
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
        # RM-291A: UnicodeDecodeError is a ValueError, not an OSError.
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return _kda_materialized   # keep prior cache on parse error
        champs = data.get("champions") if isinstance(data, dict) else None
        if not isinstance(champs, dict):
            _log.warning("champ_kda.json has no champion map (got %s);"
                         " live SQL answers", type(champs).__name__)
            champs = {}
        _kda_materialized = champs
        _kda_mtime = mt
    return _kda_materialized


def _count(value: Any) -> Optional[int]:
    """A non-negative integral count, or None for anything else (bool,
    string, None, negative, fractional)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _materialized_entry(entry: Any) -> Optional[tuple[int, int, int, int]]:
    """(kills, deaths, assists, games) from one champ_kda.json entry, or
    None when it is junk. A missing key reads 0; a present junk value
    voids the whole entry so live SQL answers."""
    if not isinstance(entry, dict):
        return None
    vals = []
    for key in _KDA_KEYS:
        v = _count(entry.get(key, 0))
        if v is None:
            return None
        vals.append(v)
    return (vals[0], vals[1], vals[2], vals[3])


def _kda_for(c: sqlite3.Connection, puuid: str, champ_id: int) -> tuple[int, int, int, int]:
    """(kills, deaths, assists, games) summed across the user's games on
    the champion. AUDIT 2026-04-29: prefers data/coach_reference/
    champ_kda.json (built by scripts/build_champ_kda.py) when present -
    that path is ~50 ms vs ~474 ms for the live timeline_events fold.
    Live SQL is the fallback when the file is missing, doesn't have
    this champ_id (e.g. user picked up a new champ since last build), or
    its entry is junk."""
    cache = _load_materialized_kda()
    if cache:
        entry = cache.get(str(champ_id))
        if entry:
            got = _materialized_entry(entry)
            if got is not None:
                return got
            _log.debug("champ_kda.json entry for %s is junk; live SQL",
                       champ_id)
    # Live-SQL fallback (original implementation).
    # timeline_events has CHAMPION_KILL events. Match-scoped JOIN against
    # participants by puuid + champion_id gives the user's row in each
    # match - kills/deaths are counted by killer_id/victim_id. Assists
    # match the participant id as a WHOLE element of the JSON id list
    # ("[1, 2, 3]" -> ",1,2,3,"), never as a substring: the old LIKE
    # matched participant 1 inside "[10, 3]" (measured +17% on the live
    # DB). No JSON1 dependency, and a malformed list cannot raise.
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
               AND (',' || REPLACE(REPLACE(REPLACE(
                      COALESCE(e.assisting_ids_json, ''),
                      '[', ''), ']', ''), ' ', '') || ',')
                   LIKE ('%,' || me.participant_id || ',%')) AS assists,
          (SELECT COUNT(*) FROM participants p
             WHERE p.puuid = ? AND p.champion_id = ?) AS games
        """,
        (puuid, champ_id, puuid, champ_id, puuid, champ_id, puuid, champ_id),
    ).fetchone()
    if not cur:
        return (0, 0, 0, 0)
    return (cur["kills"] or 0, cur["deaths"] or 0,
            cur["assists"] or 0, cur["games"] or 0)


def _names(value: Any) -> list[str]:
    """Stripped non-empty string members of *value*. A bare string is ONE
    name (a str is itself iterable, so it used to be read per character);
    None, a non-iterable or a non-string member contributes nothing."""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    try:
        items = list(value)
    except TypeError:
        return []
    return [v.strip() for v in items if isinstance(v, str) and v.strip()]


def _min_games(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if value is not None:
            _log.debug("recommend: junk min_games %r - using %d",
                       value, _DEFAULT_MIN_GAMES)
        return _DEFAULT_MIN_GAMES
    return max(1, value)


def _csv_ids(csv: Any) -> set[int]:
    out: set[int] = set()
    for raw_tok in str(csv or "").split(","):
        tok = raw_tok.strip()
        try:
            out.add(int(tok))
        except ValueError:
            continue
    return out


def _csv_names(csv: Any) -> set[str]:
    return {n.strip().lower() for n in str(csv or "").split(",") if n.strip()}


def _enemy_overlap(game: dict, target_ids: set[int],
                   target_names: set[str]) -> int:
    """How many of the game's enemy champions are in the target comp:
    by ID for resolved names, by internal name for the rest (a target
    name lands in exactly one of the two sets, so nothing counts twice)."""
    n = len(_csv_ids(game.get("enemy_ids_csv")) & target_ids)
    if target_names:
        n += len(_csv_names(game.get("enemy_comp_csv")) & target_names)
    return n


def _score(win_pct: float, games: int) -> float:
    """Confidence-weighted win pct. games=0 -> 0; games>=30 -> ~win_pct."""
    if games <= 0:
        return 0.0
    weight = games / (games + 8.0)        # asymptote at 1.0; ~50% weight at 8 games
    baseline = 0.50                        # neutral pull toward 50% wr
    return baseline + (win_pct - baseline) * weight


def recommend(my_pool: Iterable[str],
              enemy_comp: Iterable[str],
              *, min_games: int = _DEFAULT_MIN_GAMES) -> list[dict]:
    """Score each champion in `my_pool` against the recorded performance
    vs `enemy_comp`. Returns rows sorted by `score` (desc).

    Empty, missing or unreadable rewind history -> returns [] (a SQLite
    failure is logged as a warning, never raised to the caller)."""
    _load_champ_index()
    need = _min_games(min_games)
    pool = _names(my_pool)
    target_ids: set[int] = set()
    target_names: set[str] = set()
    for name in _names(enemy_comp):
        cid = _name_to_id.get(name.lower())
        if cid:
            target_ids.add(cid)
        else:
            target_names.add(name.lower())
    c = _open()
    if c is None:
        return []
    try:
        return _recommend_rows(c, pool, target_ids, target_names, need)
    except sqlite3.Error as exc:
        _log.warning("recommend: rewind_history query failed: %s", exc)
        return []
    finally:
        try:
            c.close()
        except sqlite3.Error:
            pass


def _recommend_rows(c: sqlite3.Connection, pool: list[str],
                    target_ids: set[int], target_names: set[str],
                    need: int) -> list[dict]:
    puuid = _resolve_user_puuid(c)
    if not puuid:
        return []
    out: list[dict] = []
    seen: set[int] = set()
    for champ in pool:
        cid = _name_to_id.get(champ.lower())
        if not cid:
            _log.debug("recommend: unknown champion %r - skipping", champ)
            continue
        if cid in seen:
            continue
        seen.add(cid)
        games = _games_on_champ(c, puuid, cid)
        if not games:
            continue
        # Bucket: games where enemy comp overlaps target by >= 2.
        comp_games = [g for g in games
                      if _enemy_overlap(g, target_ids, target_names) >= 2]
        sample_label = "vs comp" if len(comp_games) >= need else "vs any"
        sample = comp_games if sample_label == "vs comp" else games
        # RM-610: one resolved denominator (no remakes, no unknown
        # results) shared with every personal-WR builder.
        wins, played, _display = resolved_wr(sample)
        win_pct = (wr_pct(wins, played, None) or 0.0) / 100.0
        kk, dd, aa, _ = _kda_for(c, puuid, cid)
        out.append({
            "champion":  _id_to_name.get(cid, champ),
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
