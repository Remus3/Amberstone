"""Home-view builders for the dashboard home page.

Payload-boundary slice of the former monolithic `dashboard.builders`
(AUTONOMOUS_AUDIT spec 4.C, 2026-05-18). Holds the home summary cluster
(`_lcu_build_items`, `_build_home_summary`, `_home_tonight_pick`,
`_home_last_build`, `_home_trends_14d`, `_home_streaks`).

`dashboard.builders` re-exports these names so existing call sites keep
working without churn. Function bodies are extracted byte-verbatim -
behavior is pinned by the dashboard panel snapshot + home tests.
"""
import sqlite3

from dashboard._context import (
    APP_DIR as _APP_DIR,
    DB_CONN_LOCAL as _DB_CONN_LOCAL,
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

    # -- V3 home extras (2026-04-30): tonight_pick, last_build, trends, streaks --
    out["tonight_pick"] = _home_tonight_pick(out["this_week"])
    out["last_build"]   = _home_last_build()
    out["trends"]       = _home_trends_14d(db_path)
    out["streaks"]      = _home_streaks(db_path)
    return out


def _home_pick_tips(pick_row: dict) -> dict:
    """Deterministic Good/Bad/Ugly one-liners for the Tonight's Pick from
    the chosen this_week row's real metrics - no Claude, no Riot API.

    Three short 7-bit-ASCII strings: the headline strength (avg KDA over
    sample), the cost dimension (deaths per game), and a risk/variance
    flag that prefers a small-sample warning, then a CS sharpening cue,
    then the grade ceiling.
    """
    games = int(pick_row.get("games") or 0)
    avg_kda = float(pick_row.get("avg_kda") or 0.0)
    deaths = int(pick_row.get("deaths") or 0)
    cs_per_min = float(pick_row.get("cs_per_min") or 0.0)
    best_grade = pick_row.get("best_grade") or "-"

    game_word = "game" if games == 1 else "games"
    good = f"{avg_kda:.1f} avg KDA over {games} {game_word}"
    deaths_pg = deaths / max(games, 1)
    bad = f"{deaths_pg:.1f} deaths per game"
    if games <= 2:
        ugly = f"Small sample - {games} {game_word}"
    elif cs_per_min > 0:
        ugly = f"{cs_per_min:.1f} CS/min to sharpen"
    else:
        ugly = f"Grade ceiling {best_grade}"
    return {"good": good, "bad": bad, "ugly": ugly}


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
        "tips":     _home_pick_tips(pick),
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
      - play_days: consecutive recent days (counting back from today) with >=1 game
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
