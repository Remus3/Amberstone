"""Champion-aggregate / KDA-trend adaptation surface.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the leaderboard / streak
data (`top_champions`, `kda_trends`). `coaches.adaptation_hint`
re-exports these names so existing call sites keep working unchanged;
bodies are byte-verbatim - behavior pinned by the test_round* suite.
"""
from __future__ import annotations

import json
import sqlite3

from coaches._adaptation_common import _db, logger


def top_champions(mode: str, n: int = 10, min_games: int = 20) -> list[dict]:
    """Top-N champions by games_played in ``mode`` with at least
    ``min_games`` sample. Useful for dashboards + LLM context.
    """
    db = _db(mode)
    if db is None:
        return []
    out: list[dict] = []
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT champion, games_played, wins, losses,
                       avg_rating, aggregates_json
                FROM adaptation_buckets
                WHERE games_played >= ?
                ORDER BY games_played DESC
                LIMIT ?
                """,
                (min_games, n),
            ).fetchall()
    except sqlite3.Error as e:
        logger.debug("top_champions err %s: %s", mode, e)
        return []
    for r in rows:
        try:
            aj = json.loads(r["aggregates_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            aj = {}
        out.append({
            "champion": r["champion"],
            "games_played": int(r["games_played"]),
            "wins": int(r["wins"]),
            "losses": int(r["losses"]),
            "win_rate": float(r["avg_rating"]),
            "recent_win_rate": aj.get("recent_win_rate"),
            "recent_sample_size": int(aj.get("recent_sample_size") or 0),
            "avg_duration_sec": aj.get("avg_duration_sec"),
            "avg_kda": aj.get("avg_kda"),
            "recent_kda": aj.get("recent_kda"),
        })
    return out


def kda_trends(mode: str, n: int = 3, min_sample: int = 5) -> dict:
    """Identify champions on KDA streaks (hot or cold) in ``mode``.

    Uses ``recent_kda.delta_ratio`` - positive means the last-N window
    is outperforming the all-time baseline, negative means the player
    is underperforming on that champion recently.

    Returns ``{"mode": mode, "hot": [...], "cold": [...]}`` where each
    entry has ``{champion, baseline_ratio, recent_ratio, delta,
    sample}``. Both lists are sorted by |delta| desc. Empty lists if
    the mode DB is missing or no champion has enough sample.
    """
    db = _db(mode)
    empty = {"mode": mode, "hot": [], "cold": []}
    if db is None:
        return empty
    entries: list[dict] = []
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT champion, aggregates_json FROM adaptation_buckets"
            ).fetchall()
    except sqlite3.Error as e:
        logger.debug("kda_trends err %s: %s", mode, e)
        return empty
    for r in rows:
        try:
            aj = json.loads(r["aggregates_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        avg = aj.get("avg_kda")
        rec = aj.get("recent_kda")
        if not avg or not rec:
            continue
        if int(rec.get("sample") or 0) < min_sample:
            continue
        delta = float(rec.get("delta_ratio") or 0.0)
        entries.append({
            "champion": r["champion"],
            "baseline_ratio": float(avg.get("ratio") or 0.0),
            "recent_ratio": float(rec.get("ratio") or 0.0),
            "delta": delta,
            "sample": int(rec.get("sample") or 0),
        })
    hot = sorted((e for e in entries if e["delta"] > 0),
                 key=lambda e: e["delta"], reverse=True)[:n]
    cold = sorted((e for e in entries if e["delta"] < 0),
                  key=lambda e: e["delta"])[:n]
    return {"mode": mode, "hot": hot, "cold": cold}
