"""Temporal-axis adaptation analytics.

Payload-boundary slice of the former monolithic `coaches.adaptation_hint`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the time-of-day /
day-of-week / duration breakdowns. `coaches.adaptation_hint` re-exports
these names so existing call sites keep working unchanged; bodies are
byte-verbatim - behavior pinned by the test_round* suite.
"""
from __future__ import annotations

import sqlite3

from coaches._adaptation_common import SUPPORTED_MODES, _db, logger


def time_of_day_analysis(
    mode: str | None = None,
    since_iso: str | None = None,
    min_games: int = 3,
) -> dict:
    """Bucket matches by local hour-of-day and return per-hour stats.

    ``mode`` restricts to a single mode DB; ``None`` sums across all.
    ``since_iso`` clamps history (default: all time).
    ``min_games`` controls what counts as an insight-worthy bucket -
    buckets below threshold are still returned but flagged
    ``insight=False`` so callers can filter cheaply.

    Returns::

        {
          "mode": mode or "all",
          "since": since_iso or None,
          "buckets": [
            {"hour": 0, "games": N, "wins": W, "losses": L,
             "win_rate": 0.5 or None, "kda_ratio": 2.3 or None,
             "insight": True or False},
            ...
          ],
          "best": {"hour": 15, ...} or None,
          "worst": {"hour": 2, ...} or None,
          "total_games": M,
        }
    """
    from datetime import datetime
    modes = (mode,) if mode else SUPPORTED_MODES

    # bucket[h] = {"games","wins","losses","k","d","a","kda_sample"}
    buckets: dict[int, dict] = {
        h: {"games": 0, "wins": 0, "losses": 0,
            "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
        for h in range(24)
    }
    total_games = 0

    for m in modes:
        db = _db(m)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                where = ""
                params: tuple = ()
                if since_iso:
                    where = "WHERE started_at >= ?"
                    params = (since_iso,)
                cur = conn.execute(
                    f"SELECT started_at, win{extra} FROM matches {where}",
                    params,
                )
                for r in cur:
                    ts = r["started_at"]
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    # Convert to local time - rewind history is UTC; the
                    # user cares what wall-clock hour they played at.
                    hour = dt.astimezone().hour
                    b = buckets[hour]
                    b["games"] += 1
                    total_games += 1
                    if r["win"] == 1:
                        b["wins"] += 1
                    elif r["win"] == 0:
                        b["losses"] += 1
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            b["k_sum"] += k; b["d_sum"] += d; b["a_sum"] += a
                            b["kda_sample"] += 1
        except sqlite3.Error as e:
            logger.debug("time_of_day err %s: %s", m, e)
            continue

    out_buckets: list[dict] = []
    for h in range(24):
        b = buckets[h]
        reported = b["wins"] + b["losses"]
        wr = (b["wins"] / reported) if reported else None
        kda_ratio = None
        if b["kda_sample"]:
            k = b["k_sum"] / b["kda_sample"]
            d = b["d_sum"] / b["kda_sample"]
            a = b["a_sum"] / b["kda_sample"]
            kda_ratio = round((k + a) / max(d, 1.0), 2)
        out_buckets.append({
            "hour": h,
            "games": b["games"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": (round(wr, 3) if wr is not None else None),
            "kda_ratio": kda_ratio,
            "kda_sample": b["kda_sample"],
            "insight": b["games"] >= min_games,
        })

    # Best/worst based on win_rate, broken by KDA ratio. Only consider
    # insight-worthy buckets so a single-game outlier can't top the list.
    insightful = [b for b in out_buckets if b["insight"] and b["win_rate"] is not None]
    best = worst = None
    if insightful:
        best = max(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
        worst = min(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
    return {
        "mode": mode or "all",
        "since": since_iso,
        "total_games": total_games,
        "buckets": out_buckets,
        "best": best,
        "worst": worst,
    }


_WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


_DURATION_TIERS = (
    ("stomp",    0,    15 * 60),
    ("quick",    15 * 60, 25 * 60),
    ("standard", 25 * 60, 35 * 60),
    ("long",     35 * 60, 10 ** 9),   # open-ended upper bound
)


def duration_analysis(
    mode: str | None = None,
    champion: str | None = None,
    since_iso: str | None = None,
    min_games: int = 3,
) -> dict:
    """Bucket matches by game duration and return per-tier win-rate + KDA.

    Tiers: stomp (<15min), quick (15-25), standard (25-35), long (35+).
    ``champion`` filters to one champ (cross-mode if ``mode`` is None).
    Returns the same shape as time_of_day_analysis: per-tier buckets
    plus ``best`` / ``worst`` picked from insight-worthy tiers.
    """
    modes = (mode,) if mode else SUPPORTED_MODES

    # Per-tier accumulator indexed by tier name.
    buckets: dict[str, dict] = {
        name: {
            "games": 0, "wins": 0, "losses": 0,
            "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0,
            "lo_sec": lo, "hi_sec": hi,
        }
        for (name, lo, hi) in _DURATION_TIERS
    }
    total_games = 0

    def _tier_for(dur: int) -> str | None:
        for (name, lo, hi) in _DURATION_TIERS:
            if lo <= dur < hi:
                return name
        return None

    for m in modes:
        db = _db(m)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                clauses = ["duration_sec IS NOT NULL", "duration_sec > 0"]
                params: list = []
                if since_iso:
                    clauses.append("started_at >= ?")
                    params.append(since_iso)
                if champion:
                    clauses.append("champion = ?")
                    params.append(champion)
                where = "WHERE " + " AND ".join(clauses)
                cur = conn.execute(
                    f"SELECT duration_sec, win{extra} FROM matches {where}",
                    tuple(params),
                )
                for r in cur:
                    dur = int(r["duration_sec"])
                    tier = _tier_for(dur)
                    if tier is None:
                        continue
                    b = buckets[tier]
                    b["games"] += 1
                    total_games += 1
                    if r["win"] == 1:
                        b["wins"] += 1
                    elif r["win"] == 0:
                        b["losses"] += 1
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            b["k_sum"] += k; b["d_sum"] += d; b["a_sum"] += a
                            b["kda_sample"] += 1
        except sqlite3.Error as e:
            logger.debug("duration_analysis err %s: %s", m, e)
            continue

    out_buckets: list[dict] = []
    for (name, _, _) in _DURATION_TIERS:
        b = buckets[name]
        reported = b["wins"] + b["losses"]
        wr = (b["wins"] / reported) if reported else None
        kda_ratio = None
        if b["kda_sample"]:
            kk = b["k_sum"] / b["kda_sample"]
            dd = b["d_sum"] / b["kda_sample"]
            aa = b["a_sum"] / b["kda_sample"]
            kda_ratio = round((kk + aa) / max(dd, 1.0), 2)
        out_buckets.append({
            "tier": name,
            "lo_sec": b["lo_sec"],
            "hi_sec": b["hi_sec"] if b["hi_sec"] < 10 ** 8 else None,
            "games": b["games"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": (round(wr, 3) if wr is not None else None),
            "kda_ratio": kda_ratio,
            "kda_sample": b["kda_sample"],
            "insight": b["games"] >= min_games,
        })

    insightful = [b for b in out_buckets if b["insight"] and b["win_rate"] is not None]
    best = worst = None
    if insightful:
        best = max(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
        worst = min(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
    return {
        "mode": mode or "all",
        "champion": champion,
        "since": since_iso,
        "total_games": total_games,
        "buckets": out_buckets,
        "best": best,
        "worst": worst,
    }


def day_of_week_analysis(
    mode: str | None = None,
    since_iso: str | None = None,
    min_games: int = 3,
) -> dict:
    """Bucket matches by local weekday (0=Mon .. 6=Sun).

    Same shape as :func:`time_of_day_analysis` but axis is weekday
    instead of hour. ``best``/``worst`` are picked only from buckets
    meeting ``min_games``.
    """
    from datetime import datetime
    modes = (mode,) if mode else SUPPORTED_MODES

    buckets: dict[int, dict] = {
        d: {"games": 0, "wins": 0, "losses": 0,
            "k_sum": 0, "d_sum": 0, "a_sum": 0, "kda_sample": 0}
        for d in range(7)
    }
    total_games = 0

    for m in modes:
        db = _db(m)
        if db is None:
            continue
        try:
            with sqlite3.connect(db) as conn:
                conn.row_factory = sqlite3.Row
                cols = {r[1] for r in conn.execute("PRAGMA table_info(matches)")}
                has_kda = {"kills", "deaths", "assists"} <= cols
                extra = ", kills, deaths, assists" if has_kda else ""
                where = ""
                params: tuple = ()
                if since_iso:
                    where = "WHERE started_at >= ?"
                    params = (since_iso,)
                cur = conn.execute(
                    f"SELECT started_at, win{extra} FROM matches {where}",
                    params,
                )
                for r in cur:
                    ts = r["started_at"]
                    if not ts:
                        continue
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    wd = dt.astimezone().weekday()   # 0=Mon
                    b = buckets[wd]
                    b["games"] += 1
                    total_games += 1
                    if r["win"] == 1:
                        b["wins"] += 1
                    elif r["win"] == 0:
                        b["losses"] += 1
                    if has_kda:
                        k, d, a = r["kills"], r["deaths"], r["assists"]
                        if k is not None and d is not None and a is not None:
                            b["k_sum"] += k; b["d_sum"] += d; b["a_sum"] += a
                            b["kda_sample"] += 1
        except sqlite3.Error as e:
            logger.debug("day_of_week err %s: %s", m, e)
            continue

    out_buckets: list[dict] = []
    for d in range(7):
        b = buckets[d]
        reported = b["wins"] + b["losses"]
        wr = (b["wins"] / reported) if reported else None
        kda_ratio = None
        if b["kda_sample"]:
            kk = b["k_sum"] / b["kda_sample"]
            dd = b["d_sum"] / b["kda_sample"]
            aa = b["a_sum"] / b["kda_sample"]
            kda_ratio = round((kk + aa) / max(dd, 1.0), 2)
        out_buckets.append({
            "weekday": d,
            "name": _WEEKDAY_NAMES[d],
            "games": b["games"],
            "wins": b["wins"],
            "losses": b["losses"],
            "win_rate": (round(wr, 3) if wr is not None else None),
            "kda_ratio": kda_ratio,
            "kda_sample": b["kda_sample"],
            "insight": b["games"] >= min_games,
        })

    insightful = [b for b in out_buckets if b["insight"] and b["win_rate"] is not None]
    best = worst = None
    if insightful:
        best = max(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
        worst = min(insightful, key=lambda b: (b["win_rate"], b["kda_ratio"] or 0))
    return {
        "mode": mode or "all",
        "since": since_iso,
        "total_games": total_games,
        "buckets": out_buckets,
        "best": best,
        "worst": worst,
    }
