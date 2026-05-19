"""Session timeline adaptation surface.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the cross-mode "what did
I play" aggregates (`session_summary`, `session_games`).
`coaches.adaptation_hint` re-exports these names so existing call sites
keep working unchanged; bodies are byte-verbatim - behavior pinned by
the test_round* suite.
"""
from __future__ import annotations

import sqlite3

from coaches._adaptation_common import (
    SUPPORTED_MODES,
    _db,
    _start_of_today_iso,
    logger,
)


def session_summary(since_iso: str | None = None) -> dict:
    """Aggregate every ``matches`` row across all mode DBs where
    ``started_at >= since_iso``.

    Default ``since_iso``: start of today, local timezone.

    Returns::

        {
          "since": "<iso>",
          "games": 12,
          "wins": 7,
          "losses": 5,
          "win_rate": 0.583,
          "avg_kda": {"k": 9.5, "d": 6.1, "a": 14.3, "ratio": 3.9, "sample": 12},
          "per_mode": {"aram": {...}, "sr_ranked": {...}},
          "champions": [
            {"champion": "Ahri", "games": 4, "wins": 3, "kda_ratio": 4.1, ...},
            ...
          ]
        }

    Never raises on missing DBs; each absent mode becomes an empty slot
    in ``per_mode`` with zero counts.
    """
    since = since_iso or _start_of_today_iso()
    totals = {"games": 0, "wins": 0, "losses": 0,
              "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
    per_mode: dict[str, dict] = {}
    champ_acc: dict[str, dict] = {}   # keyed by champion only (cross-mode)

    for mode in SUPPORTED_MODES:
        db = _db(mode)
        mode_slot = {"games": 0, "wins": 0, "losses": 0,
                     "kda_sample": 0, "kda_ratio": None}
        per_mode[mode] = mode_slot
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                # KDA columns may not exist if this DB predates round 23
                # *and* startup migration hasn't run.
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                rows = conn.execute(
                    f"""SELECT champion, win, duration_sec{extra}
                        FROM matches WHERE started_at >= ?""",
                    (since,),
                ).fetchall()
        except sqlite3.Error as e:
            logger.debug("session_summary err %s: %s", mode, e)
            continue
        mode_k = mode_d = mode_a = mode_ksample = 0
        for r in rows:
            champ = r["champion"] or "Unknown"
            totals["games"] += 1
            mode_slot["games"] += 1
            ca = champ_acc.setdefault(champ, {
                "champion": champ, "games": 0, "wins": 0, "losses": 0,
                "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0,
                "modes": set(),
            })
            ca["games"] += 1
            ca["modes"].add(mode)
            win = r["win"]
            if win == 1:
                totals["wins"] += 1; mode_slot["wins"] += 1; ca["wins"] += 1
            elif win == 0:
                totals["losses"] += 1; mode_slot["losses"] += 1; ca["losses"] += 1
            if has_kda:
                k, d, a = r["kills"], r["deaths"], r["assists"]
                if k is not None and d is not None and a is not None:
                    totals["k_sum"] += k; totals["d_sum"] += d; totals["a_sum"] += a
                    totals["kda_sample"] += 1
                    ca["k_sum"] += k; ca["d_sum"] += d; ca["a_sum"] += a
                    ca["kda_sample"] += 1
                    mode_k += k; mode_d += d; mode_a += a; mode_ksample += 1
        if mode_ksample:
            mk = mode_k / mode_ksample
            md = mode_d / mode_ksample
            ma = mode_a / mode_ksample
            mode_slot["kda_sample"] = mode_ksample
            mode_slot["kda_ratio"] = round((mk + ma) / max(md, 1.0), 2)

    # Overall KDA.
    avg_kda: dict | None = None
    if totals["kda_sample"]:
        k = totals["k_sum"] / totals["kda_sample"]
        d = totals["d_sum"] / totals["kda_sample"]
        a = totals["a_sum"] / totals["kda_sample"]
        avg_kda = {
            "k": round(k, 2), "d": round(d, 2), "a": round(a, 2),
            "ratio": round((k + a) / max(d, 1.0), 2),
            "sample": totals["kda_sample"],
        }

    wr = (totals["wins"] / (totals["wins"] + totals["losses"])
          if (totals["wins"] + totals["losses"]) else None)

    champs_list = []
    for ca in champ_acc.values():
        c_games = ca["games"]
        c_kda = None
        if ca["kda_sample"]:
            k = ca["k_sum"] / ca["kda_sample"]
            d = ca["d_sum"] / ca["kda_sample"]
            a = ca["a_sum"] / ca["kda_sample"]
            c_kda = round((k + a) / max(d, 1.0), 2)
        reported = ca["wins"] + ca["losses"]
        champs_list.append({
            "champion": ca["champion"],
            "games": c_games,
            "wins": ca["wins"],
            "losses": ca["losses"],
            "win_rate": (round(ca["wins"] / reported, 3) if reported else None),
            "kda_ratio": c_kda,
            "kda_sample": ca["kda_sample"],
            "modes": sorted(ca["modes"]),
        })
    champs_list.sort(key=lambda c: (-c["games"], -(c["kda_ratio"] or 0.0)))

    return {
        "since": since,
        "games": totals["games"],
        "wins": totals["wins"],
        "losses": totals["losses"],
        "win_rate": (round(wr, 3) if wr is not None else None),
        "avg_kda": avg_kda,
        "per_mode": per_mode,
        "champions": champs_list,
    }


def session_games(since_iso: str | None = None, limit: int | None = None) -> list[dict]:
    """Chronological timeline of matches across all mode DBs since
    ``since_iso`` (default: start of today, local time).

    Each row::

        {
          "started_at": "<iso>", "ended_at": "<iso or None>",
          "mode": "aram", "champion": "Ahri",
          "win": 1 or 0 or None,
          "duration_sec": 1234,
          "kda": {"k": 10, "d": 3, "a": 15} or None,
          "kda_ratio": 8.33 or None,
          "source": "live-phase3",
        }

    Sorted oldest-first so the dashboard can render a simple scrolling
    feed without re-sorting. ``limit`` clamps the tail (most recent N).
    Missing DBs / missing KDA cols are handled gracefully.
    """
    since = since_iso or _start_of_today_iso()
    rows: list[dict] = []
    for mode in SUPPORTED_MODES:
        db = _db(mode)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                cur = conn.execute(
                    f"""SELECT started_at, ended_at, champion, win,
                               duration_sec, source{extra}
                        FROM matches WHERE started_at >= ?
                        ORDER BY started_at""",
                    (since,),
                )
                for r in cur:
                    kda = None
                    kda_ratio = None
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            kda = {"k": k, "d": d, "a": a}
                            kda_ratio = round((k + a) / max(d, 1), 2)
                    rows.append({
                        "started_at": r["started_at"],
                        "ended_at": r["ended_at"],
                        "mode": mode,
                        "champion": r["champion"],
                        "win": r["win"],
                        "duration_sec": r["duration_sec"],
                        "kda": kda,
                        "kda_ratio": kda_ratio,
                        "source": r["source"],
                    })
        except sqlite3.Error as e:
            logger.debug("session_games err %s: %s", mode, e)
            continue
    rows.sort(key=lambda r: r["started_at"] or "")
    if limit is not None and limit > 0 and len(rows) > limit:
        rows = rows[-limit:]
    return rows
