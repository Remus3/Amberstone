"""Pure builder helpers for dashboard endpoints.

Extracted verbatim from web_dashboard.py (slice 2B, 2026-05-01).
Each function reads from data/* sqlite DBs or json files and returns
a plain dict - no IO side-effects, no http handler coupling.

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


def _lcu_build_items(raw_data: str | None) -> list[int]:
    """Resolve the operator's 6 build-slot item ids (slots 0-5, trinket
    slot 6 excluded) from a match row's ``raw_data`` blob.

    Deliberate lightweight subset of :func:`_enrich_from_lcu`'s
    puuid -> participantId -> ``stats.itemN`` walk - the home Recent-5
    strip only needs the build items, not the full 10-player roster.
    Returns ``[]`` for matches that predate the s219 LCU-ingest pipeline
    (no ``lcu_match_detail``) or on any structural mismatch - the
    frontend then renders empty placeholder slots.
    """
    if not raw_data:
        return []
    import json
    try:
        rd = json.loads(raw_data)
    except Exception:
        return []
    lcu_detail = rd.get("lcu_match_detail") or {}
    tracked_puuid = (rd.get("tracked_puuid") or "").strip()
    if not lcu_detail or not tracked_puuid:
        return []
    identities = lcu_detail.get("participantIdentities") or []
    participants = lcu_detail.get("participants") or []
    if not identities or not participants:
        return []
    me_pid = None
    for ident in identities:
        player = ident.get("player") or {}
        if str(player.get("puuid") or "").strip() == tracked_puuid:
            me_pid = ident.get("participantId")
            break
    if me_pid is None:
        return []
    for p in participants:
        if p.get("participantId") == me_pid:
            s = p.get("stats") or {}
            return [int(s.get(f"item{i}") or 0) for i in range(6)]
    return []


def _build_home_summary() -> dict:
    """Aggregate read-only data for the dashboard home view.

    Source of truth: data/match_history.db (live-captured per game,
    today's matches present). rewind_history.db is NOT used here -
    it's stale until the user runs a manual backfill pass.

    Win/loss is not stored on rows - we surface grade (S-F) instead
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
        # Recent 5 games. TFT is excluded - those rows store the comp
        # name (e.g. "Dark Star Vertical") in the champion column, which
        # renders as a fake "champion" on the home view. Hidden at the
        # read layer; the rows still exist in match_history.db for any
        # downstream consumer that wants TFT-aware aggregation.
        # s218: surface cs + cs_per_min (already in matches schema).
        # `items` + `mode_subtype` are placeholder fields for the home
        # view's per-row rendering - neither is captured in
        # match_history.db today (would need an end-of-game ingest hook
        # for items, and a queue_id store to distinguish ARAM Classic
        # from ARAM Mayhem). TODO(s218-dummy-data): wire when ingest ships.
        cur = conn.execute(
            "SELECT timestamp, mode, champion, grade, kda_str, "
            "       game_time_s, kills, deaths, assists, cs, cs_per_min, "
            "       label, raw_data "
            "FROM matches WHERE mode != 'TFT' "
            "ORDER BY timestamp DESC LIMIT 5"
        )
        for (ts, mode, champ, grade, kda, dur, k, d, a, cs, cspm,
             label, raw_data) in cur:
            out["recent"].append({
                "timestamp": ts, "mode": mode, "champion": champ or "?",
                "grade": grade or "-", "kda": kda or f"{k}/{d}/{a}",
                "duration_s": int(dur or 0), "label": label or "",
                "cs": int(cs or 0), "cs_per_min": float(cspm or 0.0),
                # s219 LCU-ingest build items when present; [] for matches
                # that predate the ingest pipeline (frontend renders empty
                # slots). mode_subtype still awaits a queue_id store to
                # split ARAM Classic from ARAM Mayhem - passthrough hook.
                "items": _lcu_build_items(raw_data),
                "mode_subtype": None,
            })
        # Today's session - group all rows whose timestamp date == today.
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
            grades[g or "-"] = grades.get(g or "-", 0) + 1
            modes[mode or "?"] = modes.get(mode or "?", 0) + 1
            tk += int(k or 0); td += int(d or 0); ta += int(a or 0)
        out["today"] = {
            "games": len(rows),
            "grades": grades,
            "modes": modes,
            "total_kda": f"{tk}/{td}/{ta}",
            "avg_kda": round((tk + ta) / max(td, 1), 2) if rows else 0.0,
        }
        # This week (last 7 days) - top 5 most-played champions. TFT
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
            row["grades"].append(g or "-")
            row["modes"].add(mode or "?")
        ranked = sorted(champ_agg.items(), key=lambda kv: -kv[1]["games"])[:5]
        for champ, r in ranked:
            best = sorted(r["grades"], key=lambda x: "SABCDF-".index(x) if x in "SABCDF-" else 99)[0]
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
    # Services snapshot - RC + vision + dashboard self.
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
# manifest as nothing in the DB) are NOT a boundary on their own -
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
                "grade": grade or "-", "kda": kda or f"{k}/{d}/{a}",
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
        14d            - last 14 days
        season         - current season (best-effort: last 90d)
        prior_season   - 90 → 180d ago
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
                "favorite":  row[2] or "-",
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
        # Strip raw item_ids from this view - we just want labels.
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
                                    "detail": f"unreachable ({type(exc).__name__}) - normal if no game"})
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


# ---- Last Match -------------------------------------------------------------

def _enrich_from_lcu(lcu_detail: dict, tracked_puuid: str) -> dict:
    """Parse a full LCU /lol-match-history/v1/games/{gameId} payload into
    the shape the Post Game Review page renders.

    Locates the operator's participant via puuid -> participantId, then
    extracts: win/loss, full build (item0-item6), summoner spells,
    runes (keystone + tree paths + stat perks), damage breakdown,
    Arena augments, vision, and the full 10-player roster (KDA + items
    + champion + summoner names + is_me flag). Team-level objectives
    are surfaced alongside (dragons, baron, towers, first-blood/tower,
    bans).

    Returns an empty dict on any structural mismatch - caller treats
    None / {} as "no enriched data yet, render placeholders".
    """
    if not isinstance(lcu_detail, dict) or not tracked_puuid:
        return {}

    identities = lcu_detail.get("participantIdentities") or []
    participants = lcu_detail.get("participants") or []
    if not identities or not participants:
        return {}

    # Resolve operator's participantId via puuid match
    me_pid = None
    for ident in identities:
        player = ident.get("player") or {}
        if str(player.get("puuid") or "").strip() == tracked_puuid:
            me_pid = ident.get("participantId")
            break
    if me_pid is None:
        return {}

    # Build identity lookup
    ident_by_pid: dict = {}
    for ident in identities:
        pid = ident.get("participantId")
        if pid is not None:
            ident_by_pid[pid] = ident.get("player") or {}

    # Operator's participant + stats
    me_part: dict = {}
    for p in participants:
        if p.get("participantId") == me_pid:
            me_part = p
            break
    if not me_part:
        return {}
    s = me_part.get("stats") or {}

    out: dict = {}
    out["champion_id"] = me_part.get("championId")
    out["team_id"]     = me_part.get("teamId")
    out["win"]         = bool(s.get("win"))
    out["champ_level"] = int(s.get("champLevel") or 0)
    out["spell1_id"]   = me_part.get("spell1Id")
    out["spell2_id"]   = me_part.get("spell2Id")
    out["items"]       = [int(s.get(f"item{i}") or 0) for i in range(7)]
    out["runes"] = {
        "keystone":       s.get("perk0"),
        "primary_style":  s.get("perkPrimaryStyle"),
        "sub_style":      s.get("perkSubStyle"),
        "primary":        [s.get(f"perk{i}") for i in range(4)],
        "secondary":      [s.get(f"perk{i}") for i in range(4, 6)],
    }
    out["damage"] = {
        "dealt_to_champs":     int(s.get("totalDamageDealtToChampions") or 0),
        "physical_to_champs":  int(s.get("physicalDamageDealtToChampions") or 0),
        "magic_to_champs":     int(s.get("magicDamageDealtToChampions") or 0),
        "true_to_champs":      int(s.get("trueDamageDealtToChampions") or 0),
        "taken":               int(s.get("totalDamageTaken") or 0),
        "self_mitigated":      int(s.get("damageSelfMitigated") or 0),
        "to_objectives":       int(s.get("damageDealtToObjectives") or 0),
        "to_turrets":          int(s.get("damageDealtToTurrets") or 0),
    }
    # s219 v6: healing + shielding contribution to teammates (self-heal
    # excluded - that's a stat about your own sustain, not team-care).
    out["support"] = {
        "total_heal":              int(s.get("totalHeal") or 0),
        "heal_on_teammates":       int(s.get("totalHealsOnTeammates") or 0),
        "shield_on_teammates":     int(s.get("totalDamageShieldedOnTeammates") or 0),
        "heal_plus_shield":        int(s.get("totalHealsOnTeammates") or 0)
                                    + int(s.get("totalDamageShieldedOnTeammates") or 0),
        "units_healed":            int(s.get("totalUnitsHealed") or 0),
    }
    out["arena_augments"] = [int(s.get(f"playerAugment{i}") or 0)
                              for i in range(1, 7)]
    out["vision"] = {
        "score":          int(s.get("visionScore") or 0),
        "wards_placed":   int(s.get("wardsPlaced") or 0),
        "wards_killed":   int(s.get("wardsKilled") or 0),
        "control_wards":  int(s.get("visionWardsBoughtInGame") or 0),
    }

    # Full 10-player roster
    roster: list = []
    for p in participants:
        s2 = p.get("stats") or {}
        pid = p.get("participantId")
        player = ident_by_pid.get(pid, {})
        roster.append({
            "participant_id":    pid,
            "team_id":           p.get("teamId"),
            "champion_id":       p.get("championId"),
            "game_name":         player.get("gameName") or player.get("summonerName") or "",
            "tag_line":          player.get("tagLine") or "",
            "is_me":             pid == me_pid,
            "kills":             int(s2.get("kills") or 0),
            "deaths":            int(s2.get("deaths") or 0),
            "assists":           int(s2.get("assists") or 0),
            "cs":                int(s2.get("totalMinionsKilled") or 0)
                                  + int(s2.get("neutralMinionsKilled") or 0),
            "gold":              int(s2.get("goldEarned") or 0),
            "damage_to_champs":  int(s2.get("totalDamageDealtToChampions") or 0),
            "damage_taken":      int(s2.get("totalDamageTaken") or 0),
            "vision_score":      int(s2.get("visionScore") or 0),
            "champ_level":       int(s2.get("champLevel") or 0),
            "items":             [int(s2.get(f"item{i}") or 0) for i in range(7)],
            "summoner1":         p.get("spell1Id"),
            "summoner2":         p.get("spell2Id"),
            # s219 v7: per-player augments for ARAM Mayhem (KIWI) +
            # Arena (CHERRY). Empty list when the LCU fields aren't
            # populated (typical SR / non-augment modes return 0s).
            "augments":          [int(s2.get(f"playerAugment{i}") or 0)
                                   for i in range(1, 7)],
            "win":               bool(s2.get("win")),
        })
    out["roster"] = roster

    # Team-level objectives
    teams_out: list = []
    for t in (lcu_detail.get("teams") or []):
        teams_out.append({
            "team_id":           t.get("teamId"),
            "win":               (str(t.get("win") or "").lower() == "win"),
            "first_blood":       bool(t.get("firstBlood")),
            "first_tower":       bool(t.get("firstTower")),
            "first_baron":       bool(t.get("firstBaron")),
            "first_dragon":      bool(t.get("firstDargon")),  # sic: LCU typo
            "first_inhibitor":   bool(t.get("firstInhibitor")),
            "baron_kills":       int(t.get("baronKills") or 0),
            "dragon_kills":      int(t.get("dragonKills") or 0),
            "tower_kills":       int(t.get("towerKills") or 0),
            "inhibitor_kills":   int(t.get("inhibitorKills") or 0),
            "rift_herald_kills": int(t.get("riftHeraldKills") or 0),
            "horde_kills":       int(t.get("hordeKills") or 0),
            "bans":              list(t.get("bans") or []),
        })
    out["teams"] = teams_out

    # Top-level match metadata
    out["game_id"]            = lcu_detail.get("gameId")
    out["game_mode"]          = lcu_detail.get("gameMode")
    out["queue_id"]           = lcu_detail.get("queueId")
    out["map_id"]             = lcu_detail.get("mapId")
    out["game_duration_s"]    = int(lcu_detail.get("gameDuration") or 0)
    out["game_creation_ts"]   = lcu_detail.get("gameCreation")
    out["game_creation_date"] = lcu_detail.get("gameCreationDate")
    out["game_version"]       = lcu_detail.get("gameVersion")
    out["end_of_game_result"] = lcu_detail.get("endOfGameResult")
    # s220 surrender tag: LCU stamps these on every participant's stats
    # (game-wide value). Surfacing-only - lets the hero badge an FF'd
    # loss vs a played-out one, and flag an early-surrender remake.
    # Pre-s220 ingested rows lack the keys → bool(None) → False.
    out["ended_in_surrender"]       = bool(s.get("gameEndedInSurrender"))
    out["ended_in_early_surrender"] = bool(s.get("gameEndedInEarlySurrender"))

    return out


def _enrich_match_timeline(timeline: dict, lcu_detail: dict,
                           my_team_id) -> dict:
    """Parse a Riot Match-V5 timeline payload (…/matches/{id}/timeline)
    into the per-minute differential series + objective-event ribbon the
    Post Game Review "Timeline" tab renders (s220 Item E, phase 1).

    Match-V5 nests the per-minute frames under ``info``; a flat top-level
    ``frames`` list is also accepted (defensive). Participant→team comes
    from the stashed LCU match detail - Match-V5 timelines only map
    participantId→puuid, not teamId.

    All diffs are ally_total − enemy_total, so a positive value means the
    operator's team was ahead. Per-frame participant `position` data is
    deliberately NOT parsed here - that's the phase-2 interactive replay
    minimap, which reads the same Match-V5 timeline.

    Output shape:
      {
        "frame_interval_ms": 60000,
        "duration_s": 1930,
        "minutes": [0, 1, 2, ...],            # one x value per frame
        "series": {"gold": [...], "xp": [...], "cs": [...]},
        "final":  {"gold": int, "xp": int, "cs": int},
        "events": [{"t_s", "clock", "kind", "team", "label"}, ...],
      }
    Returns {} on any structural problem (Arena / round-based modes carry
    no per-minute frames - the caller renders a placeholder)."""
    if not isinstance(timeline, dict):
        return {}
    info = timeline.get("info")
    src = info if (isinstance(info, dict) and info.get("frames")) else timeline
    frames = src.get("frames")
    if not isinstance(frames, list) or not frames:
        return {}

    # participantId -> teamId from the detail payload.
    pid_team: dict = {}
    for p in (lcu_detail.get("participants") or []):
        pid = p.get("participantId")
        if pid is not None:
            try:
                pid_team[int(pid)] = p.get("teamId")
            except (TypeError, ValueError):
                continue
    if not pid_team:
        return {}
    teams_seen = sorted({v for v in pid_team.values() if v is not None})
    my_tid = my_team_id if my_team_id in teams_seen else (
        teams_seen[0] if teams_seen else 100)

    interval = int(src.get("frameInterval") or 60000)

    minutes: list = []
    s_gold: list = []
    s_xp: list = []
    s_cs: list = []
    for idx, fr in enumerate(frames):
        pf = fr.get("participantFrames") or {}
        ally = {"gold": 0, "xp": 0, "cs": 0}
        enemy = {"gold": 0, "xp": 0, "cs": 0}
        for raw_pid, pdata in pf.items():
            if not isinstance(pdata, dict):
                continue
            try:
                pid = int(pdata.get("participantId") or raw_pid)
            except (TypeError, ValueError):
                continue
            bucket = ally if pid_team.get(pid) == my_tid else enemy
            bucket["gold"] += int(pdata.get("totalGold") or 0)
            bucket["xp"]   += int(pdata.get("xp") or 0)
            bucket["cs"]   += (int(pdata.get("minionsKilled") or 0)
                               + int(pdata.get("jungleMinionsKilled") or 0))
        ts_ms = fr.get("timestamp")
        if ts_ms is None:
            ts_ms = idx * interval
        minutes.append(round(ts_ms / 60000.0))
        s_gold.append(ally["gold"] - enemy["gold"])
        s_xp.append(ally["xp"] - enemy["xp"])
        s_cs.append(ally["cs"] - enemy["cs"])

    def _ev_team(ev: dict) -> str:
        try:
            killer = int(ev.get("killerId") or 0)
        except (TypeError, ValueError):
            killer = 0
        if killer in pid_team:
            return "ally" if pid_team[killer] == my_tid else "enemy"
        ktid = ev.get("killerTeamId")
        if ktid in teams_seen:
            return "ally" if ktid == my_tid else "enemy"
        # BUILDING_KILL.teamId is the team that LOST the structure.
        lost = ev.get("teamId")
        if lost in teams_seen:
            return "enemy" if lost == my_tid else "ally"
        return "neutral"

    _MON = {
        "DRAGON":       ("dragon",  "Dragon"),
        "RIFTHERALD":   ("herald",  "Rift Herald"),
        "BARON_NASHOR": ("baron",   "Baron"),
        "HORDE":        ("grubs",   "Void Grubs"),
        "ATAKHAN":      ("atakhan", "Atakhan"),
    }
    events: list = []
    first_blood_taken = False
    for fr in frames:
        for ev in (fr.get("events") or []):
            if not isinstance(ev, dict):
                continue
            et = ev.get("type") or ""
            t_s = int(ev.get("timestamp") or 0) // 1000
            clock = f"{t_s // 60}:{t_s % 60:02d}"
            if et == "CHAMPION_KILL" and not first_blood_taken:
                first_blood_taken = True
                events.append({"t_s": t_s, "clock": clock,
                               "kind": "first_blood", "team": _ev_team(ev),
                               "label": "First Blood"})
            elif et == "ELITE_MONSTER_KILL":
                kind, lbl = _MON.get(ev.get("monsterType") or "",
                                     ("objective", "Objective"))
                sub = ev.get("monsterSubType") or ""
                if kind == "dragon" and sub:
                    pretty = sub.replace("_DRAGON", "").replace("_", " ").title()
                    if pretty:
                        lbl = f"{pretty} Dragon"
                events.append({"t_s": t_s, "clock": clock, "kind": kind,
                               "team": _ev_team(ev), "label": lbl})
            elif et == "BUILDING_KILL":
                bt = ev.get("buildingType") or ""
                if bt == "TOWER_BUILDING":
                    events.append({"t_s": t_s, "clock": clock,
                                   "kind": "tower", "team": _ev_team(ev),
                                   "label": "Tower"})
                elif bt == "INHIBITOR_BUILDING":
                    events.append({"t_s": t_s, "clock": clock,
                                   "kind": "inhibitor", "team": _ev_team(ev),
                                   "label": "Inhibitor"})
    events.sort(key=lambda e: e["t_s"])
    # Bound payload - a stomp can rack up 20+ structures; 60 keeps the
    # ribbon readable and raw_data lean.
    if len(events) > 60:
        events = events[:60]

    dur = int(lcu_detail.get("gameDuration") or 0)
    if dur <= 0 and frames:
        last_ts = frames[-1].get("timestamp") or 0
        dur = int(last_ts / 1000)

    return {
        "frame_interval_ms": interval,
        "duration_s": dur,
        "minutes": minutes,
        "series": {"gold": s_gold, "xp": s_xp, "cs": s_cs},
        "final": {
            "gold": s_gold[-1] if s_gold else 0,
            "xp":   s_xp[-1] if s_xp else 0,
            "cs":   s_cs[-1] if s_cs else 0,
        },
        "events": events,
    }


# Match-V5 routing cluster by platform id. Match-V5 (incl. /timeline)
# uses the regional cluster, not the platform cluster. Default americas.
_MV5_REGION_BY_PLATFORM = {
    "NA1": "americas", "BR1": "americas", "LA1": "americas",
    "LA2": "americas", "OC1": "americas",
    "EUW1": "europe", "EUN1": "europe", "TR1": "europe", "RU": "europe",
    "KR": "asia", "JP1": "asia",
}


def _attach_match_timeline(enriched: dict, lcu_detail: dict) -> None:
    """Fetch the Riot Match-V5 timeline for this game and attach the
    parsed result to ``enriched["timeline"]`` (s220 Item E, phase 1).

    The LCU exposes no per-game timeline endpoint, so the authoritative
    source is Match-V5 (…/matches/{platform}_{gameId}/timeline) - exactly
    the consumer s148 anticipated. ``core.riot_api.get_match_timeline``
    is immutable-cached: one Riot call per match, then served from cache.

    Degrades silently - when the Riot key is missing/revoked (returns
    None) or anything raises, ``enriched["timeline"]`` is simply not set
    and the frontend shows its "Timeline pending" placeholder. This must
    never break /api/last-match."""
    try:
        platform = str(lcu_detail.get("platformId") or "").upper()
        game_id = lcu_detail.get("gameId")
        if not platform or not game_id:
            return
        match_id = f"{platform}_{game_id}"
        region = _MV5_REGION_BY_PLATFORM.get(platform, "americas")
        from core import riot_api  # lazy - avoids import cost on cold paths
        timeline = riot_api.get_match_timeline(match_id, region=region)
        if not isinstance(timeline, dict):
            return
        parsed = _enrich_match_timeline(
            timeline, lcu_detail, enriched.get("team_id"))
        if parsed:
            enriched["timeline"] = parsed
    except Exception as exc:  # never break the page over a timeline
        _log.warning("_attach_match_timeline: %s", exc)


def _compute_wrong_team_from_enriched(enriched: dict, op_k: int, op_d: int, op_a: int) -> list[dict]:
    """Team-level "what went wrong" signals derived from LCU enrichment.

    enriched.teams provides:  win, first_blood, first_tower, first_baron,
      first_dragon, first_inhibitor, baron_kills, dragon_kills, tower_kills,
      inhibitor_kills, rift_herald_kills, horde_kills, bans.

    Heuristics per mode bucket:
      - SR (queueId 400/420/430/440):
          objective-control + soul + baron + tower diff
      - ARAM / Mayhem (queueId 450 / 2400 / KIWI mode):
          tower diff + KDA disparity (only rift to push on)
      - Arena (queueId 1700/1710 / CHERRY mode):
          deferred - 4 subteam paradigm doesn't fit win/loss heuristics
      - Other: degrade gracefully to operator-side death/KDA proxies.

    Each emitted item is {text, why} - `why` backs the tooltip on hover.
    """
    out: list[dict] = []

    teams = enriched.get("teams") or []
    if len(teams) < 2:
        return out
    my_tid = enriched.get("team_id")
    me = next((t for t in teams if t.get("team_id") == my_tid), None)
    opp = next((t for t in teams if t.get("team_id") != my_tid), None)
    if not me or not opp:
        return out

    queue_id  = enriched.get("queue_id") or 0
    game_mode = (enriched.get("game_mode") or "").upper()
    is_arena   = queue_id in (1700, 1710) or game_mode == "CHERRY"
    is_aram    = (queue_id == 450 or queue_id == 2400
                  or game_mode in ("ARAM", "KIWI"))
    is_sr      = (queue_id in (400, 420, 430, 440)
                  or (game_mode == "CLASSIC" and not is_aram))

    if is_arena:
        # Arena's 4-team structure doesn't fit a single ally/enemy frame
        # cleanly. Skip team-level heuristics; the chronic + right
        # sections still fire on operator-side stats.
        return out

    # ── First-objective losses (works in SR + ARAM) ────────────────────
    if opp.get("first_blood") and not me.get("first_blood"):
        out.append({
            "text": "Lost first blood",
            "why":  ("Enemy team took first blood - early gold + tempo "
                     "advantage. Worth reviewing the lane / fight that opened "
                     "the match in the deep Review page."),
        })
    if opp.get("first_tower") and not me.get("first_tower"):
        out.append({
            "text": "Lost first tower",
            "why":  ("Enemy team took the first tower (250g globally + "
                     "platings + first-tower trinket bounty). Indicates "
                     "early lane pressure was conceded - common cause: "
                     "death timer + freeze break."),
        })

    # ── Tower differential (SR only - ARAM has its own framing below) ─
    my_towers  = int(me.get("tower_kills") or 0)
    opp_towers = int(opp.get("tower_kills") or 0)
    if is_sr and opp_towers - my_towers >= 4:
        out.append({
            "text": f"Tower diff −{opp_towers - my_towers} (lost {opp_towers}-{my_towers})",
            "why":  (f"Enemy took {opp_towers} towers to your {my_towers} - "
                     f"map pressure was lopsided. Each tower is ~430g + "
                     f"vision real estate. Re-watching mid-game roams in "
                     f"the deep Review page would surface where the trades "
                     f"went sideways."),
        })

    if is_sr:
        # ── Dragon control + soul ─────────────────────────────────────
        my_drag  = int(me.get("dragon_kills") or 0)
        opp_drag = int(opp.get("dragon_kills") or 0)
        if opp_drag >= 4 and not me.get("win"):
            out.append({
                "text": f"Enemy got soul ({opp_drag} drakes)",
                "why":  (f"4+ dragons = Dragon Soul, a permanent team-wide "
                         f"power-spike. You finished with {my_drag}; review "
                         f"early drake setups + vision in the deep Review."),
            })
        elif opp_drag - my_drag >= 2:
            out.append({
                "text": f"Dragon control lost ({my_drag}-{opp_drag})",
                "why":  (f"Enemy took {opp_drag} dragons to your {my_drag}. "
                         f"Each dragon stack is a teamwide bonus - review "
                         f"who was contesting + your top-side trades that "
                         f"enabled the call."),
            })

        # ── Baron giveaway ────────────────────────────────────────────
        my_baron  = int(me.get("baron_kills") or 0)
        opp_baron = int(opp.get("baron_kills") or 0)
        if opp_baron > 0 and my_baron == 0:
            out.append({
                "text": f"Gave up Baron(s) ×{opp_baron}",
                "why":  (f"Enemy took {opp_baron} Baron Nashor with zero "
                         f"answer from your team. Baron buff fuels minion "
                         f"empowerment + sieges; review vision setup before "
                         f"the pit fight in the deep Review."),
            })

        # ── Rift Herald ───────────────────────────────────────────────
        my_herald  = int(me.get("rift_herald_kills") or 0)
        opp_herald = int(opp.get("rift_herald_kills") or 0)
        if opp_herald > 0 and my_herald == 0:
            out.append({
                "text": "Gave up Rift Herald",
                "why":  ("Enemy took Herald with no answer. Each Herald is "
                         "~5 plates of pressure on whichever lane it gets "
                         "dumped in - review jungle / mid pathing 8-14min."),
            })

    elif is_aram:
        # ARAM Mayhem (KIWI) and ARAM Classic - tower-diff is the
        # main team-level signal; dragons/baron don't exist.
        if opp_towers > 0 and my_towers == 0:
            out.append({
                "text": f"Lost every tower trade ({opp_towers}-0)",
                "why":  (f"Enemy team broke {opp_towers} of your towers "
                         f"without taking one back - pure attrition loss. "
                         f"Common in ARAM when comp lacks AOE waveclear "
                         f"vs siege champions."),
            })

    # ── Roster aggregates (works in any 5v5 mode) ─────────────────────
    roster = enriched.get("roster") or []
    if roster:
        my_side  = [r for r in roster if r.get("team_id") == my_tid]
        opp_side = [r for r in roster if r.get("team_id") != my_tid]
        if my_side and opp_side:
            my_k  = sum(int(r.get("kills") or 0)  for r in my_side)
            my_d  = sum(int(r.get("deaths") or 0) for r in my_side)
            opp_k = sum(int(r.get("kills") or 0)  for r in opp_side)
            opp_d = sum(int(r.get("deaths") or 0) for r in opp_side)
            if opp_k >= my_k * 1.5 and opp_k - my_k >= 10:
                out.append({
                    "text": f"Team kill deficit ({my_k}-{opp_k})",
                    "why":  (f"Enemy outscored your team {opp_k} kills to "
                             f"{my_k} (1.5×+ ratio with a 10+ gap). Each "
                             f"team-fight you took was net-losing - review "
                             f"engage timings + comp synergy."),
                })
            my_gold  = sum(int(r.get("gold") or 0) for r in my_side)
            opp_gold = sum(int(r.get("gold") or 0) for r in opp_side)
            if opp_gold - my_gold >= 8000:
                out.append({
                    "text": f"Gold deficit −{(opp_gold - my_gold)//1000}k",
                    "why":  (f"Enemy ended {opp_gold - my_gold}g ahead "
                             f"({(opp_gold/1000):.1f}k vs {(my_gold/1000):.1f}k). "
                             f"That's roughly an extra completed mythic + "
                             f"finisher across the team - review mid-game "
                             f"objective trades."),
                })

    # ── Operator-side proxies (always fire if applicable) ─────────────
    if op_d >= 10:
        out.append({
            "text": f"Death count cost the team ({op_d} deaths)",
            "why":  (f"{op_d} deaths is a 10+ threshold. Even with the "
                     f"objectives + team aggregates above, each personal "
                     f"death is gold + 30+s map pressure handed back."),
        })

    if not out:
        out.append({
            "text": "No team-level red flags this match",
            "why":  ("LCU enrichment surfaced team data but nothing tripped "
                     "the heuristics (no early-objective loss, tower diff "
                     "<4, no soul/baron giveaway, no major gold/kill gap)."),
        })

    return out


def _compute_quick_review(current: dict, history: list[dict]) -> dict:
    """Compute the 3-section Quick Review for the Last Match page.

    `current` is the just-finished match row (parsed). `history` is the
    operator's most recent N non-TFT matches EXCLUDING `current`, used as
    the baseline for "chronic fail" assessment.

    Returns:
      {
        "right":      [{text, why}, ...],   # positive callouts about this match
        "wrong_team": [{text, why}, ...],   # team-level issues this match
        "my_chronic": [{text, why}, ...],   # repeated patterns across history
      }

    v1 heuristics - operator-revisable. The `why` field is shown in a
    tooltip on hover so the analysis stays explainable. Team data is not
    in match_history.db today (only operator-centric stats); the
    wrong_team section degrades gracefully until the Riot Match-V5
    enrich flow ships.
    """
    right: list[dict] = []
    wrong_team: list[dict] = []
    my_chronic: list[dict] = []

    def _kda(k: int, d: int, a: int) -> float:
        return round((k + a) / max(d, 1), 2)

    k = int(current.get("kills") or 0)
    d = int(current.get("deaths") or 0)
    a = int(current.get("assists") or 0)
    cspm = float(current.get("cs_per_min") or 0.0)
    grade = (current.get("grade") or "").upper().strip()
    kp = current.get("kp_pct")

    cur_kda = _kda(k, d, a)

    # ── right: this-match positives ─────────────────────────────────────
    if grade in ("S", "A"):
        right.append({
            "text": f"Top-tier performance ({grade})",
            "why": f"Match graded {grade} - operator scored in the top tier on "
                   f"the per-mode rubric used by the Home page Recent 5.",
        })
    if cur_kda >= 3.0:
        right.append({
            "text": f"Excellent KDA ({cur_kda})",
            "why": f"{k}/{d}/{a} = (K+A)/D = {cur_kda}, well above the 3.0 "
                   f"threshold used as the strong-performance gate.",
        })
    if cspm >= 8.0 and current.get("mode") == "SR":
        right.append({
            "text": f"Solid farm ({cspm:.1f} CS/min)",
            "why": f"{int(current.get('cs') or 0)} CS at {cspm:.1f}/min - at "
                   f"or above the 8.0 CS/min standard for SR.",
        })
    if isinstance(kp, (int, float)) and kp >= 70:
        right.append({
            "text": f"High team-fight participation ({int(kp)}% KP)",
            "why": f"You took part in {int(kp)}% of team kills - strong "
                   f"presence in skirmishes / objective fights.",
        })
    if k >= 10 and d <= 5:
        right.append({
            "text": f"Carry-tier kill output ({k} kills, {d} deaths)",
            "why": "10+ kills with ≤5 deaths is a snowball signal - you "
                   "converted leads without giving them back.",
        })

    if not right:
        right.append({
            "text": "No standout positives this match",
            "why": "None of the v1 thresholds tripped (S/A grade, KDA≥3, "
                   "CS/min≥8, KP≥70%, or 10+ kills with ≤5 deaths).",
        })

    # ── wrong_team: team-level issues this match ────────────────────────
    # If LCU enrichment is present, surface real team-level signals
    # (objectives lost, comp asymmetry, gold deficit). Falls back to
    # operator-side proxies (death spike + sub-1 KDA) when enrichment
    # is missing (e.g. agent hasn't pushed yet, or pre-s219 row).
    enriched = current.get("enriched") if isinstance(current, dict) else None
    if isinstance(enriched, dict) and enriched.get("teams"):
        wrong_team.extend(_compute_wrong_team_from_enriched(enriched, k, d, a))
    else:
        wrong_team.append({
            "text": "Team data unavailable",
            "why": "LCU match detail not ingested yet. The Game-PC LCU "
                   "agent auto-POSTs on EndOfGame; this section unlocks "
                   "team objectives + roster signals once that lands.",
        })
        if d >= 10:
            wrong_team.append({
                "text": f"Death count cost the team ({d} deaths)",
                "why": f"{d} deaths is a 10+ threshold - even with high KP "
                       f"({int(kp) if isinstance(kp,(int,float)) else '?'}%), "
                       f"each death is gold + 30+s map pressure handed back.",
            })
        if cur_kda < 1.0 and (k + d + a) > 0:
            wrong_team.append({
                "text": f"Sub-1 KDA ({cur_kda})",
                "why": f"{k}/{d}/{a} = {cur_kda} - below the 1.0 baseline; "
                       f"deaths outpaced (kills + assists), so each fight "
                       f"likely net-negative for the team.",
            })

    # ── my_chronic: repeated patterns across history ────────────────────
    if history:
        deaths_hist = sorted(int(r.get("deaths") or 0) for r in history)
        median_d = deaths_hist[len(deaths_hist) // 2] if deaths_hist else 0
        if d > median_d + 3 and median_d > 0:
            my_chronic.append({
                "text": f"Deaths above your average ({d} vs ~{median_d} median)",
                "why": f"Across your last {len(history)} non-TFT games, your "
                       f"median deaths is {median_d}. This match's {d} is "
                       f"3+ above that - repeating pattern of overcommitting.",
            })

        cspm_hist = [float(r.get("cs_per_min") or 0.0) for r in history
                     if (r.get("mode") == "SR")]
        if cspm_hist and current.get("mode") == "SR":
            median_cspm = sorted(cspm_hist)[len(cspm_hist) // 2]
            if cspm < median_cspm - 1.0:
                my_chronic.append({
                    "text": f"CS/min below your SR median ({cspm:.1f} vs ~{median_cspm:.1f})",
                    "why": f"Your SR median over the last {len(cspm_hist)} games "
                           f"is {median_cspm:.1f} CS/min. This match's "
                           f"{cspm:.1f} is 1+ below - wave-management/death-cost "
                           f"pattern worth a deeper review.",
                })

        grades_hist = [(r.get("grade") or "").upper().strip() for r in history]
        bad_grades = [g for g in grades_hist if g in ("D", "F")]
        if len(bad_grades) >= max(3, len(history) // 3):
            my_chronic.append({
                "text": f"Recent grade slump ({len(bad_grades)}/{len(history)} at D/F)",
                "why": f"{len(bad_grades)} of your last {len(history)} games "
                       f"graded D or F - a third+ of recent matches in the "
                       f"weak-performance tier. Worth a focused review session.",
            })

    if not my_chronic:
        my_chronic.append({
            "text": "No chronic pattern detected (yet)",
            "why": "Not enough recent matches to compute baselines, or this "
                   "match's stats are within ±1 SD of your medians.",
        })

    return {
        "right":      right,
        "wrong_team": wrong_team,
        "my_chronic": my_chronic,
    }


def _build_last_match(baseline: int = 20) -> dict:
    """Latest non-TFT match for the Last Match page.

    Source: data/match_history.db (operator-centric - KDA / CS / gold /
    grade / DS picks). rewind_history.db is stale (Dec 2025) so we do
    NOT enrich from Match-V5 here; the v2 Refresh button will trigger
    that path.

    Returns:
      {
        "found": bool,
        "match": { ... full operator-side stats ... } | None,
        "history_count": int,   # how many rows backed the Quick Review baseline
        "quick_review": {right, wrong_team, my_chronic},  # see _compute_quick_review
      }
    """
    import json
    # s220: baseline window is operator-configurable from the Settings
    # page (localStorage rc-pgr-baseline → ?baseline= query param).
    # Clamp to a sane range; default 20 preserves pre-s220 behavior.
    try:
        baseline = int(baseline)
    except (TypeError, ValueError):
        baseline = 20
    baseline = max(5, min(50, baseline))
    out: dict = {"found": False, "match": None, "history_count": 0}
    db_path = _APP_DIR / "data" / "match_history.db"
    conn = _ro_conn(db_path)
    if conn is None:
        out["error"] = "match_history.db missing"
        return out
    try:
        cur = conn.execute(
            "SELECT id, timestamp, mode, champion, grade, kda_str, "
            "       game_time_s, kills, deaths, assists, cs, cs_per_min, "
            "       gold, gold_per_min, kp_pct, label, raw_data "
            "FROM matches WHERE mode != 'TFT' "
            "ORDER BY timestamp DESC LIMIT 1"
        )
        latest = cur.fetchone()
        if not latest:
            return out

        (mid, ts, mode, champ, grade, kda_str, dur,
         k, d, a, cs, cspm, gold, gpm, kp, label, raw) = latest

        ds_picks: list = []
        coach_action: str = ""
        lcu_detail: dict = {}
        tracked_puuid: str = ""
        lcu_ingested_at: str = ""
        if raw:
            try:
                rd = json.loads(raw)
                ds_picks        = rd.get("daemon_slayer_picks") or []
                coach_action    = (rd.get("coach_action") or "").strip()
                lcu_detail      = rd.get("lcu_match_detail") or {}
                tracked_puuid   = (rd.get("tracked_puuid") or "").strip()
                lcu_ingested_at = rd.get("lcu_ingested_at") or ""
            except Exception:
                pass

        kda_ratio = round((int(k or 0) + int(a or 0)) / max(int(d or 0), 1), 2)

        # s220 Item E: attach the Match-V5 per-minute timeline (gold/xp/cs
        # differential + objective ribbon) onto the enriched blob for the
        # Post Game Review "Timeline" tab. Server-side fetch - the LCU has
        # no timeline endpoint; Match-V5 is the source (immutable-cached,
        # degrades to a placeholder when the Riot key is unavailable).
        enriched = (_enrich_from_lcu(lcu_detail, tracked_puuid)
                    if (lcu_detail and tracked_puuid) else None)
        if enriched and lcu_detail:
            _attach_match_timeline(enriched, lcu_detail)

        match_row = {
            "id":               int(mid),
            "timestamp":        ts,
            "mode":             mode,
            "champion":         champ or "?",
            "grade":            grade or "-",
            "kda_str":          kda_str or f"{k or 0}/{d or 0}/{a or 0}",
            "kda_ratio":        kda_ratio,
            "duration_s":       int(dur or 0),
            "kills":            int(k or 0),
            "deaths":           int(d or 0),
            "assists":          int(a or 0),
            "cs":               int(cs or 0),
            "cs_per_min":       float(cspm or 0.0),
            "gold":             int(gold or 0) if gold is not None else None,
            "gold_per_min":     float(gpm or 0.0) if gpm is not None else None,
            "kp_pct":           float(kp) if kp is not None else None,
            "label":            label or "",
            "coach_action":     coach_action,
            "ds_picks":         ds_picks,
            "lcu_ingested_at":  lcu_ingested_at,
            "enriched":         enriched,
        }

        # Baseline rows for chronic-fail computation (exclude this one)
        history: list[dict] = []
        cur = conn.execute(
            "SELECT mode, grade, kills, deaths, assists, cs, cs_per_min "
            "FROM matches WHERE mode != 'TFT' AND id != ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (int(mid), baseline)
        )
        for h_mode, h_grade, hk, hd, ha, h_cs, h_cspm in cur:
            history.append({
                "mode": h_mode, "grade": h_grade,
                "kills": hk, "deaths": hd, "assists": ha,
                "cs": h_cs, "cs_per_min": h_cspm,
            })

        out["found"] = True
        out["match"] = match_row
        out["history_count"] = len(history)
        out["quick_review"] = _compute_quick_review(match_row, history)

    except Exception as exc:
        _log.warning("_build_last_match: %s", exc)
        out["error"] = str(exc)
    finally:
        conn.close()
    return out
