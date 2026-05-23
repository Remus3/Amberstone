"""
scripts/build_champ_kda.py - pre-aggregate per-champion KDA totals
from data/rewind_history.db so /api/recommend-champ doesn't have to
re-fold 2.5M timeline_events on cold-cache.

Output: data/coach_reference/champ_kda.json
Shape:
    {
      "generated_at": "<utc iso>",
      "user_puuid":   "<sha-prefix>",
      "champions": {
        "<champ_id>": {
          "name":    "Vayne",
          "games":   166,
          "kills":   1234,
          "deaths":  890,
          "assists": 1450
        },
        ...
      }
    }

Run weekly (or after a big rewind_history backfill). Drops the
recommender's cold-call time from ~474 ms to ~50 ms - the fold of
timeline_events is the bottleneck.

Caller (coaches/champ_pool_recommender) reads the JSON if present and
falls back to the live SQL when missing. Either path returns the
same shape, so the warm path is unaffected.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REWIND_DB = ROOT / "data" / "rewind_history.db"
OUT       = ROOT / "data" / "coach_reference" / "champ_kda.json"
DDR       = ROOT / "data" / "meta" / "ddragon_champions.json"


def _champ_name_index() -> dict[int, str]:
    """champ_id → display-name lookup."""
    if not DDR.exists():
        return {}
    try:
        data = json.loads(DDR.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[int, str] = {}
    for slug, entry in (data.get("data") or {}).items():
        try:
            cid = int(entry.get("key"))
        except (TypeError, ValueError):
            continue
        out[cid] = entry.get("name") or slug
    return out


def _resolve_user_puuid(c: sqlite3.Connection) -> str | None:
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
    return row[0] if row else None


def main() -> int:
    if not REWIND_DB.exists():
        print(f"error: {REWIND_DB} not found", file=sys.stderr)
        return 1

    t_total = time.perf_counter()
    name_idx = _champ_name_index()
    c = sqlite3.connect(str(REWIND_DB))
    try:
        puuid = _resolve_user_puuid(c)
        if not puuid:
            print("error: no tracked-champion games in rewind_history.db", file=sys.stderr)
            return 1
        print(f"user puuid: {puuid[:16]}...")

        # Per-champion games + team_won.
        rows = c.execute(
            """
            SELECT p.champion_id, COUNT(*) AS games
            FROM participants p
            WHERE p.puuid = ?
            GROUP BY p.champion_id
            """,
            (puuid,),
        ).fetchall()
        print(f"champions played: {len(rows)}")

        out: dict[str, dict] = {}
        t_q = time.perf_counter()
        for champ_id, games in rows:
            kk = c.execute(
                """
                SELECT COUNT(*) FROM timeline_events e
                JOIN participants me
                  ON me.match_id = e.match_id
                 AND me.participant_id = e.killer_id
                WHERE e.event_type = 'CHAMPION_KILL'
                  AND me.puuid = ? AND me.champion_id = ?
                """,
                (puuid, champ_id),
            ).fetchone()[0]
            dd = c.execute(
                """
                SELECT COUNT(*) FROM timeline_events e
                JOIN participants me
                  ON me.match_id = e.match_id
                 AND me.participant_id = e.victim_id
                WHERE e.event_type = 'CHAMPION_KILL'
                  AND me.puuid = ? AND me.champion_id = ?
                """,
                (puuid, champ_id),
            ).fetchone()[0]
            aa = c.execute(
                """
                SELECT COUNT(*) FROM timeline_events e
                JOIN participants me
                  ON me.match_id = e.match_id
                WHERE e.event_type = 'CHAMPION_KILL'
                  AND me.puuid = ? AND me.champion_id = ?
                  AND e.assisting_ids_json LIKE '%' || me.participant_id || '%'
                """,
                (puuid, champ_id),
            ).fetchone()[0]
            out[str(champ_id)] = {
                "name":    name_idx.get(int(champ_id), str(champ_id)),
                "games":   int(games),
                "kills":   int(kk),
                "deaths":  int(dd),
                "assists": int(aa),
            }
        print(f"per-champion KDA aggregated in {(time.perf_counter()-t_q)*1000:.0f}ms")
    finally:
        c.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user_puuid":   (puuid or "")[:16],
        "champions":    out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    from core.polled_json import atomic_write_json
    atomic_write_json(OUT, payload)
    elapsed = time.perf_counter() - t_total
    print(f"wrote {OUT}  ({len(out)} champs, {elapsed:.1f}s total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
