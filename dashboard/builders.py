"""Pure builder helpers for dashboard endpoints.

Originally extracted verbatim from web_dashboard.py (slice 2B,
2026-05-01). The home / LCU-enrich / last-match payload clusters were
split into sibling modules on 2026-05-18 (AUTONOMOUS_AUDIT spec 4.C) to
keep this module focused on the session / history / loadouts /
diagnostics surface. The split modules are re-exported at the bottom so
every existing `from dashboard.builders import _x` call site (and
`web_dashboard.py`'s re-bind under the original underscored names) keeps
working without churn.

Each function reads from data/* sqlite DBs or json files and returns a
plain dict - no IO side-effects, no http handler coupling.
"""
import sqlite3

from dashboard._context import (
    APP_DIR as _APP_DIR,
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
    log as _log,
    read_json as _read_json,
    ro_conn as _ro_conn,
)


# -- Session / History / Loadouts / Diagnostics endpoints (2026-04-26) --
# Shared helper: groups match_history.db rows into sessions where each
# session is a run of consecutive matches with no >=SESSION_GAP_S gap
# between them. Sessions span midnight; Riot client restarts (which
# manifest as nothing in the DB) are NOT a boundary on their own -
# only the gap rule decides.
SESSION_GAP_S = 2 * 3600   # 2 hours


def _compute_last20(rconn, queue_ids: tuple[int, ...] | None = None) -> dict:
    """Last-20 decided matches as a newest-first W/L pip trail.

    Takes an already-open read-only rewind_history.db connection and
    returns ``{results, wins, losses, win_rate}`` where ``results`` is a
    newest-first list of ``"W"``/``"L"`` (len <= 20), ``wins``/``losses``
    are the counts, and ``win_rate`` is the L20 win-rate percent (rounded
    1dp) or ``None`` when nothing is decided. Returns ``{}`` on a missing
    conn or any sqlite error so callers can render an empty strip without
    a crash. Single source of the last-20 logic shared by ``_build_history``
    (History season block) and ``_build_home_summary`` (home hero strip).

    ``queue_ids`` (HOME mode tabs): when set, only matches whose
    ``queue_id`` is in the tuple count - the home strip scopes the trail
    to the active mode tab. None keeps today's exact global behavior
    (the History call site stays unfiltered).
    """
    if rconn is None:
        return {}
    sql = ("SELECT tracked_win FROM matches "
           "WHERE tracked_win IS NOT NULL ")
    params: tuple = ()
    if queue_ids:
        sql += ("AND queue_id IN (" +
                ",".join("?" * len(queue_ids)) + ") ")
        params = tuple(queue_ids)
    sql += "ORDER BY game_creation_ts DESC LIMIT 20"
    try:
        recent = [int(r[0]) for r in rconn.execute(sql, params)]
    except sqlite3.Error as exc:
        _log.debug("last20 compute: %s", exc)
        return {}
    lw = sum(1 for w in recent if w == 1)
    ll = sum(1 for w in recent if w == 0)
    ld = lw + ll
    return {
        "results":  ["W" if w == 1 else "L" for w in recent],
        "wins":     lw,
        "losses":   ll,
        "win_rate": round(lw * 100.0 / ld, 1) if ld else None,
    }


def _load_match_rows(limit: int | None = None) -> list[dict]:
    db = _APP_DIR / "data" / "match_history.db"
    conn = _ro_conn(db)
    if conn is None:
        return []
    # TFT rows store the comp name in the champion column ("Dark Star
    # Vertical" etc.), which is meaningless on champion-centric views
    # (Recent 5, History sessions, session summary). Filter at the
    # loader so every consumer (`_build_home_summary`, `_build_history`,
    # `_build_session_summary`) inherits the same exclusion. Underlying
    # rows stay in match_history.db for any TFT-aware consumer.
    # raw_data carries the LCU end-of-game blob (lcu_match_detail) from
    # which the per-match win/loss is resolved (item 77 WIN-CAPTURE
    # keystone) - match_history.db has no win column. Pre-ingest rows
    # resolve to win=None (no result tint, not a guessed outcome).
    from dashboard.builders_home import _lcu_win
    sql = ("SELECT timestamp, mode, champion, grade, kda_str, "
           "       game_time_s, kills, deaths, assists, label, raw_data "
           "FROM matches WHERE mode != 'TFT' "
           "ORDER BY timestamp DESC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    try:
        rows = []
        for ts, mode, champ, grade, kda, dur, k, d, a, label, raw_data in conn.execute(sql):
            rows.append({
                "timestamp": ts, "mode": mode or "?", "champion": champ or "?",
                "grade": grade or "-", "kda": kda or f"{k}/{d}/{a}",
                "duration_s": int(dur or 0),
                "kills": int(k or 0), "deaths": int(d or 0), "assists": int(a or 0),
                "label": label or "",
                "win": _lcu_win(raw_data),
            })
        return rows
    except sqlite3.Error:
        getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(db), None)
        return []


def _ts_to_epoch(ts: str) -> int:
    """match_history timestamps are 'YYYY-MM-DD HH:MM:SS' strings."""
    from datetime import datetime
    try:
        return int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp())
    except Exception:  # noqa: BLE001
        return 0


def _group_sessions(rows: list[dict]) -> list[list[dict]]:
    """Group descending-timestamp match rows into sessions.

    Walks rows newest-first; closes a session when the gap to the
    PREVIOUS (older-than-current-but-newer-in-our-iteration) match is
    >=SESSION_GAP_S, where the gap is measured from the older match's
    end (timestamp + game_time_s) to the newer match's start.
    """
    sessions: list[list[dict]] = []
    current: list[dict] = []
    for row in rows:
        if not current:
            current.append(row); continue
        prev = current[-1]  # newer than `row` since rows are DESC
        # `row` is OLDER than `prev`. Gap = prev start - row end.
        prev_start = _ts_to_epoch(prev["timestamp"])
        row_end = _ts_to_epoch(row["timestamp"]) + (row["duration_s"] or 0)
        gap = prev_start - row_end
        if gap >= SESSION_GAP_S:
            sessions.append(current)
            current = [row]
        else:
            current.append(row)
    if current:
        sessions.append(current)
    return sessions


def _agg_session(rows: list[dict]) -> dict:
    """Reduce a list of match rows into a session summary dict."""
    if not rows:
        return {}
    grades, modes, champs = {}, {}, {}
    tk = td = ta = 0
    total_dur = 0
    for r in rows:
        grades[r["grade"]] = grades.get(r["grade"], 0) + 1
        modes[r["mode"]]   = modes.get(r["mode"], 0) + 1
        c = champs.setdefault(r["champion"], {"games": 0, "k": 0, "d": 0, "a": 0})
        c["games"] += 1
        c["k"] += r["kills"]; c["d"] += r["deaths"]; c["a"] += r["assists"]
        tk += r["kills"]; td += r["deaths"]; ta += r["assists"]
        total_dur += r["duration_s"]
    champ_list = [
        {"champion": ch, "games": v["games"],
         "kda": f"{v['k']}/{v['d']}/{v['a']}"}
        for ch, v in sorted(champs.items(), key=lambda kv: -kv[1]["games"])
    ]
    # rows[0] is newest (we kept DESC), rows[-1] is oldest
    return {
        "games": len(rows),
        "started_at": rows[-1]["timestamp"],
        "last_at":    rows[0]["timestamp"],
        "time_played_s": total_dur,
        "total_kda": f"{tk}/{td}/{ta}",
        "avg_kda":  round((tk + ta) / max(td, 1), 2),
        "grades": grades,
        "modes":  modes,
        "champions": champ_list,
        "matches": rows,
    }


def _build_session_summary() -> dict:
    rows = _load_match_rows(limit=200)
    sessions = _group_sessions(rows)
    if not sessions:
        return {"games": 0, "window_label": "no matches"}
    current = sessions[0]
    summary = _agg_session(current)
    summary["window_label"] = f"current session · {summary['started_at']} → {summary['last_at']}"
    return summary


def _build_history(scope: str) -> dict:
    """List all sessions in scope. Scopes:
        14d            - last 14 days
        season         - current season (best-effort: last 90d)
        prior_season   - 90 -> 180d ago
        all            - every match in match_history.db
    """
    from datetime import datetime, timedelta
    now = datetime.now()
    rows = _load_match_rows(limit=None)
    if scope == "14d":
        cutoff = (now - timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [r for r in rows if r["timestamp"] >= cutoff]
    elif scope == "season":
        cutoff = (now - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [r for r in rows if r["timestamp"] >= cutoff]
    elif scope == "prior_season":
        old = (now - timedelta(days=180)).strftime("%Y-%m-%d %H:%M:%S")
        new = (now - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [r for r in rows if old <= r["timestamp"] < new]
    sessions_groups = _group_sessions(rows)
    sessions_out = []
    for grp in sessions_groups:
        s = _agg_session(grp)
        date = (s.get("started_at") or "")[:10]
        dur_min = (s["time_played_s"] // 60) if s.get("time_played_s") else 0
        s["date"] = date
        s["duration_label"] = f"{dur_min}m"
        sessions_out.append(s)
    # Season stats from rewind_history.db (full historical set).
    # WIN-CAPTURE keystone P2 (item 77): rewind.matches.tracked_win is the
    # clean single-account 0/1 win column for 2900+ matches, so the real
    # season win-rate + a last-20 W/L strip come straight from it (retires
    # the History "(needs Riot key)" WR stub). match_history.db has no win
    # column, so these aggregates intentionally read rewind, not the
    # session rows above.
    season_stats = {}
    last20: dict = {}
    rdb = _APP_DIR / "data" / "rewind_history.db"
    rconn = _ro_conn(rdb)
    if rconn is not None:
        try:
            row = rconn.execute(
                "SELECT COUNT(*), AVG(CASE WHEN tracked_deaths > 0 "
                "  THEN (tracked_kills + tracked_assists) * 1.0 / tracked_deaths "
                "  ELSE tracked_kills + tracked_assists END), "
                "  (SELECT tracked_champion_name FROM matches "
                "   WHERE tracked_champion_name != '' "
                "   GROUP BY tracked_champion_name "
                "   ORDER BY COUNT(*) DESC LIMIT 1), "
                "  SUM(CASE WHEN tracked_win = 1 THEN 1 ELSE 0 END), "
                "  SUM(CASE WHEN tracked_win = 0 THEN 1 ELSE 0 END) "
                "FROM matches"
            ).fetchone()
            wins = int(row[3] or 0)
            losses = int(row[4] or 0)
            decided = wins + losses
            season_stats = {
                "total":     int(row[0] or 0),
                "avg_kda":   round(float(row[1] or 0), 2),
                "favorite":  row[2] or "-",
                "wins":      wins,
                "losses":    losses,
                "win_rate":  round(wins * 100.0 / decided, 1) if decided else None,
            }
            # Last 20 decided matches, newest-first, as a W/L pip trail.
            last20 = _compute_last20(rconn)
        except sqlite3.Error as exc:
            getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(rdb), None)
            _log.debug("history season stats: %s", exc)
    return {"scope": scope, "sessions": sessions_out,
            "season_stats": season_stats, "last20": last20}


def _build_loadouts_all(mode: str) -> dict:
    """Return all champions + their variants for a given mode."""
    from coaches.loadout_resolver import list_variants, _load_loadouts
    loadouts = _load_loadouts().get("champions", {}) or {}
    out_champs = []
    for champ_name in sorted(loadouts.keys()):
        rows = list_variants(champ_name, mode)
        if not rows:
            continue
        # Strip raw item_ids from this view - we just want labels.
        slim = [{"key": r["key"], "label": r["label"], "is_default": r["is_default"],
                 "keystone": r.get("keystone", "")} for r in rows]
        out_champs.append({"champion": champ_name, "variants": slim})
    return {"mode": mode, "champions": out_champs}


def _live_metrics_enabled() -> bool:
    """Diagnostics flag: True when live-metrics capture is on (env
    RC_LIVE_METRICS=1 OR config live_metrics_enabled). Lazy import so a
    builders import never hard-depends on core.live_metrics."""
    try:
        from core import live_metrics
        return live_metrics.enabled()
    except Exception:  # noqa: BLE001
        import os
        return os.environ.get("RC_LIVE_METRICS", "0") == "1"


def _build_diagnostics() -> dict:
    """Connection status + log tail + health snapshot for the
    Diagnostics view. Folds in the connection-check use case from
    the dropped Current Match view."""
    out = {
        "connections": [],
        "log_tail": [],
        "health": _read_json("ops/runtime/health.json"),
        # env RC_LIVE_METRICS=1 OR config live_metrics_enabled (re-read live).
        "live_metrics_enabled": _live_metrics_enabled(),
    }
    h = out["health"]
    out["connections"].append({
        "name": "RC supervisor", "ok": bool(h.get("alive")),
        "detail": f"pid {h.get('pid','?')} · mode {h.get('mode','?')} · reload_ok {h.get('last_reload_ok')}"
    })
    # Vision relay (loopback)
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://127.0.0.1:8889/health", timeout=1) as r:
            out["connections"].append({"name": "Vision relay", "ok": r.status == 200,
                                        "detail": "127.0.0.1:8889"})
    except Exception as exc:  # noqa: BLE001
        out["connections"].append({"name": "Vision relay", "ok": False,
                                    "detail": f"down ({type(exc).__name__})"})
    # Live Client API (local on Legion post 1-PC consolidation)
    try:
        import urllib.request as _ur
        from core.game_host import GAME_HOST
        with _ur.urlopen(f"http://{GAME_HOST}:2999/liveclientdata/activeplayer", timeout=2) as r:
            out["connections"].append({"name": "Live Client API", "ok": r.status == 200,
                                        "detail": f"{GAME_HOST}:2999"})
    except Exception as exc:  # noqa: BLE001
        out["connections"].append({"name": "Live Client API", "ok": False,
                                    "detail": f"unreachable ({type(exc).__name__}) - normal if no game"})
    # Tail today's log
    try:
        from datetime import datetime
        log_path = _APP_DIR / "logs" / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")
            out["log_tail"] = content.splitlines()[-40:]
    except Exception as exc:  # noqa: BLE001
        _log.debug("diag log tail: %s", exc)
    return out


# --- Payload-boundary split (4.C, 2026-05-18) ---------------------------
# The home / LCU-enrich / last-match clusters live in sibling modules.
# Re-exported here so every existing `from dashboard.builders import _x`
# call site keeps working unchanged (the original module contract).
from dashboard.builders_home import (  # noqa: E402,F401
    _build_home_summary,
    _home_streaks,
    _home_tonight_pick,
    _home_trends_14d,
    _lcu_build_items,
)
from dashboard.builders_lcu_enrich import (  # noqa: E402,F401
    _attach_match_timeline,
    _enrich_from_lcu,
    _enrich_match_timeline,
)
from dashboard.builders_last_match import (  # noqa: E402,F401
    _build_last_match,
    _clamp_baseline,
    _compute_quick_review,
    _compute_wrong_team_from_enriched,
)
