"""Pure builder helpers for dashboard endpoints.

Extracted verbatim from web_dashboard.py (slice 2B, 2026-05-01).
Each function reads from data/* sqlite DBs or json files and returns
a plain dict — no IO side-effects, no http handler coupling.

`web_dashboard.py` re-imports these into its module namespace under
their original underscored names (`_build_home_summary`, etc.) so all
existing call sites keep working without churn.
"""
import sqlite3

from dashboard._context import (
    APP_DIR as _APP_DIR,
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
    log as _log,
    read_json as _read_json,
    ro_conn as _ro_conn,
)


def _build_home_summary() -> dict:
    """Aggregate read-only data for the dashboard home view.

    Source of truth: data/match_history.db (live-captured per game,
    today's matches present). rewind_history.db is NOT used here —
    it's stale until the user runs a manual backfill pass.

    Win/loss is not stored on rows — we surface grade (S-F) instead
    as the per-game performance signal.
    """
    from datetime import datetime, timedelta
    out = {"today": {}, "recent": [], "this_week": [], "services": []}
    db_path = _APP_DIR / "data" / "match_history.db"
    conn = _ro_conn(db_path)
    if conn is None:
        out["error"] = "match_history.db missing"
        return out
    try:
        # Recent 5 games. TFT is excluded — those rows store the comp
        # name (e.g. "Dark Star Vertical") in the champion column, which
        # renders as a fake "champion" on the home view. Hidden at the
        # read layer; the rows still exist in match_history.db for any
        # downstream consumer that wants TFT-aware aggregation.
        # s218: surface cs + cs_per_min (already in matches schema).
        # `items` + `mode_subtype` are placeholder fields for the home
        # view's per-row rendering — neither is captured in
        # match_history.db today (would need an end-of-game ingest hook
        # for items, and a queue_id store to distinguish ARAM Classic
        # from ARAM Mayhem). TODO(s218-dummy-data): wire when ingest ships.
        cur = conn.execute(
            "SELECT timestamp, mode, champion, grade, kda_str, "
            "       game_time_s, kills, deaths, assists, cs, cs_per_min, label "
            "FROM matches WHERE mode != 'TFT' "
            "ORDER BY timestamp DESC LIMIT 5"
        )
        for ts, mode, champ, grade, kda, dur, k, d, a, cs, cspm, label in cur:
            out["recent"].append({
                "timestamp": ts, "mode": mode, "champion": champ or "?",
                "grade": grade or "—", "kda": kda or f"{k}/{d}/{a}",
                "duration_s": int(dur or 0), "label": label or "",
                "cs": int(cs or 0), "cs_per_min": float(cspm or 0.0),
                # Placeholders pending ingestion extension:
                "items": [],
                "mode_subtype": None,
            })
        # Today's session — group all rows whose timestamp date == today.
        # TFT excluded for the same reason as Recent 5: keeps the "N
        # games today" header consistent with the row list below it.
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT mode, champion, grade, kills, deaths, assists "
            "FROM matches WHERE timestamp LIKE ? || '%' "
            "  AND mode != 'TFT'",
            (today,)
        ).fetchall()
        grades: dict[str, int] = {}
        modes:  dict[str, int] = {}
        tk = td = ta = 0
        for mode, champ, g, k, d, a in rows:
            grades[g or "—"] = grades.get(g or "—", 0) + 1
            modes[mode or "?"] = modes.get(mode or "?", 0) + 1
            tk += int(k or 0); td += int(d or 0); ta += int(a or 0)
        out["today"] = {
            "games": len(rows),
            "grades": grades,
            "modes": modes,
            "total_kda": f"{tk}/{td}/{ta}",
            "avg_kda": round((tk + ta) / max(td, 1), 2) if rows else 0.0,
        }
        # This week (last 7 days) — top 5 most-played champions. TFT
        # rows excluded for the same reason as Recent 5: the "champion"
        # column carries a comp name, not a champion.
        # s218: aggregate cs + per-champion K/D/A totals so the home
        # view can render "1.8 22/10/18" KDA breakdowns + per-week CS.
        week_cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        cur = conn.execute(
            "SELECT champion, mode, grade, kills, deaths, assists, cs, cs_per_min, game_time_s "
            "FROM matches WHERE timestamp >= ? AND champion != '' "
            "  AND mode != 'TFT'",
            (week_cutoff,)
        )
        champ_agg: dict[str, dict] = {}
        for champ, mode, g, k, d, a, cs, cspm, dur in cur:
            row = champ_agg.setdefault(champ, {
                "games": 0, "k": 0, "d": 0, "a": 0,
                "cs_total": 0, "time_total_s": 0.0,
                "grades": [], "modes": set(),
            })
            row["games"] += 1
            row["k"] += int(k or 0); row["d"] += int(d or 0); row["a"] += int(a or 0)
            row["cs_total"] += int(cs or 0)
            row["time_total_s"] += float(dur or 0)
            row["grades"].append(g or "—")
            row["modes"].add(mode or "?")
        ranked = sorted(champ_agg.items(), key=lambda kv: -kv[1]["games"])[:5]
        for champ, r in ranked:
            best = sorted(r["grades"], key=lambda x: "SABCDF—".index(x) if x in "SABCDF—" else 99)[0]
            mins = r["time_total_s"] / 60.0 if r["time_total_s"] else 0.0
            out["this_week"].append({
                "champion": champ, "games": r["games"],
                "avg_kda": round((r["k"] + r["a"]) / max(r["d"], 1), 2),
                "kills": r["k"], "deaths": r["d"], "assists": r["a"],
                "cs_total": r["cs_total"],
                "cs_per_min": round(r["cs_total"] / mins, 1) if mins > 0 else 0.0,
                "best_grade": best,
                "modes": sorted(r["modes"]),
            })
    except sqlite3.Error:
        # Evict poisoned conn so the next call reopens cleanly.
        getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(db_path), None)
        raise
    # Services snapshot — RC + vision + dashboard self.
    h = _read_json("ops/runtime/health.json")
    out["services"].append({
        "name": "RC", "ok": bool(h.get("alive")),
        "detail": f"pid {h.get('pid','?')} · {h.get('mode','?')}",
    })
    # Vision server probe (loopback, fast)
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://127.0.0.1:8889/health", timeout=1) as r:
            out["services"].append({
                "name": "Vision", "ok": r.status == 200, "detail": "127.0.0.1:8889",
            })
    except Exception:
        out["services"].append({"name": "Vision", "ok": False, "detail": "down"})

    # ── V3 home extras (2026-04-30): tonight_pick, last_build, trends, streaks ──
    out["tonight_pick"] = _home_tonight_pick(out["this_week"])
    out["last_build"]   = _home_last_build()
    out["trends"]       = _home_trends_14d(db_path)
    out["streaks"]      = _home_streaks(db_path)
    return out


def _home_tonight_pick(this_week: list) -> dict | None:
    """Top of this_week by avg_kda; tie-broken by games-played. The
    coach-prompt-style "play this tonight" suggestion."""
    if not this_week:
        return None
    ranked = sorted(this_week,
                    key=lambda r: (-(r.get("avg_kda") or 0), -(r.get("games") or 0)))
    pick = ranked[0]
    return {
        "champion": pick.get("champion"),
        "avg_kda":  pick.get("avg_kda"),
        "games":    pick.get("games"),
        "grade":    pick.get("best_grade"),
        "modes":    pick.get("modes") or [],
        "reason":   f"{pick.get('avg_kda', 0):.1f} KDA over {pick.get('games', 0)} game"
                    + ("s" if (pick.get('games') or 0) != 1 else "")
                    + " this week",
    }


def _home_last_build() -> dict | None:
    """Most recent local-player row from postgame_stats.db, joined to its
    match for captured_at. Walks each mode's tables (aram/sr/arena/brawl),
    picks the latest by captured_at, returns champ + 6 item ids + spells.
    Skips item slot 6 (trinket / ward, not a build slot)."""
    db = _APP_DIR / "data" / "postgame_stats.db"
    conn = _ro_conn(db)
    if conn is None:
        return None
    best = None  # (captured_at, mode, champion, items, spells)
    try:
        for mode in ("aram", "sr", "arena", "brawl"):
            try:
                cur = conn.execute(
                    f"SELECT m.captured_at, p.champion_name, "
                    f"       p.item0_id, p.item1_id, p.item2_id, "
                    f"       p.item3_id, p.item4_id, p.item5_id, "
                    f"       p.spell1_name, p.spell2_name "
                    f"FROM {mode}_player_stats p "
                    f"JOIN {mode}_matches m ON m.match_id = p.match_id "
                    f"WHERE p.is_local_player = 1 AND p.champion_name != '' "
                    f"ORDER BY m.captured_at DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and (best is None or (row[0] or "") > (best[0] or "")):
                    items = [int(x) for x in row[2:8] if x]
                    best = (row[0], mode, row[1], items,
                            [row[8] or "", row[9] or ""])
            except sqlite3.OperationalError:
                continue
    except sqlite3.Error:
        getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(db), None)
        return None
    if not best:
        return None
    captured_at, mode, champion, items, spells = best
    return {
        "champion": champion, "mode": mode.upper(),
        "items": items, "spells": [s for s in spells if s],
        "captured_at": captured_at,
    }


def _home_trends_14d(db_path) -> dict:
    """14-day daily aggregates of cs_per_min, gold_per_min, KDA from
    match_history.db. Each metric is a list of {date, value} entries
    in chronological order, padded with None for days with no games."""
    from datetime import datetime, timedelta
    out = {"cs_per_min": [], "gold_per_min": [], "kda": []}
    conn = _ro_conn(db_path)
    if conn is None:
        return out
    days = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(13, -1, -1)]
    by_day_cs: dict[str, list] = {d: [] for d in days}
    by_day_gp: dict[str, list] = {d: [] for d in days}
    by_day_kda: dict[str, list] = {d: [] for d in days}
    try:
        cutoff = days[0]
        cur = conn.execute(
            "SELECT timestamp, cs_per_min, gold_per_min, kills, deaths, assists "
            "FROM matches WHERE timestamp >= ?", (cutoff,)
        )
        for ts, csm, gpm, k, d, a in cur:
            day = (ts or "")[:10]
            if day not in by_day_cs:
                continue
            if csm and csm > 0:
                by_day_cs[day].append(float(csm))
            if gpm and gpm > 0:
                by_day_gp[day].append(float(gpm))
            kda_v = (int(k or 0) + int(a or 0)) / max(int(d or 0), 1)
            by_day_kda[day].append(kda_v)
    except sqlite3.Error:
        getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(db_path), None)
        return out
    for d in days:
        out["cs_per_min"].append(
            {"date": d, "value": round(sum(by_day_cs[d]) / len(by_day_cs[d]), 2)
             if by_day_cs[d] else None})
        out["gold_per_min"].append(
            {"date": d, "value": round(sum(by_day_gp[d]) / len(by_day_gp[d]), 1)
             if by_day_gp[d] else None})
        out["kda"].append(
            {"date": d, "value": round(sum(by_day_kda[d]) / len(by_day_kda[d]), 2)
             if by_day_kda[d] else None})
    return out


def _home_streaks(db_path) -> dict:
    """Active streak signals derived from match_history.db:
      - play_days: consecutive recent days (counting back from today) with ≥1 game
      - good_grades: consecutive most-recent matches at S/A grade
    Both reset when the chain breaks."""
    from datetime import datetime, timedelta
    out = {"play_days": 0, "good_grades": 0}
    conn = _ro_conn(db_path)
    if conn is None:
        return out
    try:
        # Distinct days with games, recent cutoff 30 days
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        days_with_games = {
            (r[0] or "")[:10]
            for r in conn.execute(
                "SELECT timestamp FROM matches WHERE timestamp >= ?", (cutoff,))
            if r[0]
        }
        today = datetime.now().date()
        streak = 0
        for i in range(30):
            d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in days_with_games:
                streak += 1
            elif i == 0:
                continue   # allow today to be empty without breaking streak
            else:
                break
        out["play_days"] = streak
        # Latest run of S/A grades
        good = 0
        for (g,) in conn.execute(
            "SELECT grade FROM matches ORDER BY timestamp DESC LIMIT 50"):
            if (g or "").upper() in ("S", "A"):
                good += 1
            else:
                break
        out["good_grades"] = good
    except sqlite3.Error:
        getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(db_path), None)
    return out


# ── Session / History / Loadouts / Diagnostics endpoints (2026-04-26) ──
# Shared helper: groups match_history.db rows into sessions where each
# session is a run of consecutive matches with no ≥SESSION_GAP_S gap
# between them. Sessions span midnight; Riot client restarts (which
# manifest as nothing in the DB) are NOT a boundary on their own —
# only the gap rule decides.
SESSION_GAP_S = 2 * 3600   # 2 hours
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
    sql = ("SELECT timestamp, mode, champion, grade, kda_str, "
           "       game_time_s, kills, deaths, assists, label "
           "FROM matches WHERE mode != 'TFT' "
           "ORDER BY timestamp DESC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    try:
        rows = []
        for ts, mode, champ, grade, kda, dur, k, d, a, label in conn.execute(sql):
            rows.append({
                "timestamp": ts, "mode": mode or "?", "champion": champ or "?",
                "grade": grade or "—", "kda": kda or f"{k}/{d}/{a}",
                "duration_s": int(dur or 0),
                "kills": int(k or 0), "deaths": int(d or 0), "assists": int(a or 0),
                "label": label or "",
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
    except Exception:
        return 0


def _group_sessions(rows: list[dict]) -> list[list[dict]]:
    """Group descending-timestamp match rows into sessions.

    Walks rows newest-first; closes a session when the gap to the
    PREVIOUS (older-than-current-but-newer-in-our-iteration) match is
    ≥SESSION_GAP_S, where the gap is measured from the older match's
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
        14d            — last 14 days
        season         — current season (best-effort: last 90d)
        prior_season   — 90 → 180d ago
        all            — every match in match_history.db
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
    # Season stats from rewind_history.db (full historical set)
    season_stats = {}
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
                "   ORDER BY COUNT(*) DESC LIMIT 1) "
                "FROM matches"
            ).fetchone()
            season_stats = {
                "total":     int(row[0] or 0),
                "avg_kda":   round(float(row[1] or 0), 2),
                "favorite":  row[2] or "—",
            }
        except sqlite3.Error as exc:
            getattr(_DB_CONN_LOCAL, "conns", {}).pop(str(rdb), None)
            _log.debug("history season stats: %s", exc)
    return {"scope": scope, "sessions": sessions_out, "season_stats": season_stats}


def _build_loadouts_all(mode: str) -> dict:
    """Return all champions + their variants for a given mode."""
    from coaches.loadout_resolver import list_variants, _load_loadouts
    loadouts = _load_loadouts().get("champions", {}) or {}
    out_champs = []
    for champ_name in sorted(loadouts.keys()):
        rows = list_variants(champ_name, mode)
        if not rows:
            continue
        # Strip raw item_ids from this view — we just want labels.
        slim = [{"key": r["key"], "label": r["label"], "is_default": r["is_default"],
                 "keystone": r.get("keystone", "")} for r in rows]
        out_champs.append({"champion": champ_name, "variants": slim})
    return {"mode": mode, "champions": out_champs}


def _build_diagnostics() -> dict:
    """Connection status + log tail + health snapshot for the
    Diagnostics view. Folds in the connection-check use case from
    the dropped Current Match view."""
    import os
    out = {
        "connections": [],
        "log_tail": [],
        "health": _read_json("ops/runtime/health.json"),
        "live_metrics_enabled": os.environ.get("RC_LIVE_METRICS", "0") == "1",
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
    except Exception as exc:
        out["connections"].append({"name": "Vision relay", "ok": False,
                                    "detail": f"down ({type(exc).__name__})"})
    # Game-PC liveclient relay (LAN)
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://192.168.8.237:2999/liveclientdata/activeplayer", timeout=2) as r:
            out["connections"].append({"name": "Live Client API (Game-PC)", "ok": r.status == 200,
                                        "detail": "192.168.8.237:2999"})
    except Exception as exc:
        out["connections"].append({"name": "Live Client API (Game-PC)", "ok": False,
                                    "detail": f"unreachable ({type(exc).__name__}) — normal if no game"})
    # Tail today's log
    try:
        from datetime import datetime
        log_path = _APP_DIR / "logs" / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        if log_path.exists():
            content = log_path.read_text(encoding="utf-8", errors="replace")
            out["log_tail"] = content.splitlines()[-40:]
    except Exception as exc:
        _log.debug("diag log tail: %s", exc)
    return out
