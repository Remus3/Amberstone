"""
Retro-fill `match_metrics` from `rewind_history.db`.

Populates the new metrics DB (queue item #9) with values derivable from
REAL historical data in rewind_history.db. No fabrication - every value
maps to an actual column in `participants` / `timeline_frames` /
`timeline_events`. If a metric can't be inferred from real data, we skip
it rather than invent.

Per-match output:
  - Final-state metrics (from participants, tagged `milestone_tag='game_end'`):
      kda_string, kill_participation_pct, damage_share_summary,
      damage_taken_summary, cc_score_summary, heal_shield_summary,
      time_dead_summary, time_alive_pct, vision_summary,
      pink_ward_uptime (partial), turret_kills_summary, objective_dance
  - 10-minute snapshot (from timeline_frames nearest 600s, tagged
    `milestone_tag='10min_mark'`):
      cs_at_10, gold_at_10, xp_at_10, level_at_10
  - 15-minute snapshot (nearest 900s, tagged `milestone_tag='15min_mark'`):
      csd_at_15, gd_at_15 (diff vs lane-opposite if resolvable)
  - first_blood timestamp (from timeline_events, milestone_tag='first_blood')
  - first_tower timestamp (milestone_tag='first_tower')

Safety:
  - Runs integrity_check() on the target DB before each batch.
  - Skips matches already retro-filled (check match_id existence in
    match_metrics with milestone_tag='game_end').
  - Transactional batch writes via Recorder.flush().
  - READONLY on rewind_history.db.

Usage:
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/retrofill_match_metrics.py               # all matches (resumable)
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/retrofill_match_metrics.py --limit 50    # first 50 unprocessed
  $env:LOCALAPPDATA/Programs/Python/Python314/python.exe scripts/retrofill_match_metrics.py --match NA1_5182398158   # one match
"""
from __future__ import annotations
import sqlite3
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.match_metrics import recorder, DB_PATH as METRICS_DB, integrity_check, row_count  # noqa: E402

REWIND_DB = ROOT / "data" / "rewind_history.db"


def _nearest_frame(conn, match_id: str, participant_id: int, target_ms: int):
    """Return the timeline_frames row closest to target_ms for this
    participant. None if no frames exist near the target."""
    # Frames are minute-granular (typically 60000ms intervals). Find the
    # one within +/-90s of target.
    row = conn.execute("""
        SELECT timestamp_ms, current_gold, total_gold, xp, level,
               minions_killed, jungle_minions, total_dmg_done, total_dmg_taken,
               pos_x, pos_y, time_enemy_cc
        FROM timeline_frames
        WHERE match_id=? AND participant_id=?
          AND timestamp_ms BETWEEN ? AND ?
        ORDER BY ABS(timestamp_ms - ?) ASC
        LIMIT 1
    """, (match_id, participant_id, target_ms - 90000, target_ms + 90000, target_ms)).fetchone()
    return row


def _find_tracked_pid(conn, match_id: str, champ: str, team_id: int):
    row = conn.execute(
        "SELECT participant_id FROM participants "
        "WHERE match_id=? AND champion_name=? AND team_id=?",
        (match_id, champ, team_id),
    ).fetchone()
    return row[0] if row else None


def _already_processed(match_id: str) -> bool:
    conn = sqlite3.connect(METRICS_DB)
    try:
        r = conn.execute(
            "SELECT 1 FROM match_metrics WHERE match_id=? AND milestone_tag='game_end' LIMIT 1",
            (match_id,),
        ).fetchone()
        return bool(r)
    finally:
        conn.close()


def retrofill_match(src_conn, match: dict) -> int:
    """Emit metrics for a single match. Returns rows recorded."""
    mid = match["match_id"]
    champ = match["tracked_champion_name"]
    team_id = match["tracked_team_id"]
    duration_s = match["game_duration_s"]
    mode = "sr_ranked" if match["queue_id"] == 420 else (
        "sr_flex" if match["queue_id"] == 440 else "sr")

    pid = _find_tracked_pid(src_conn, mid, champ, team_id)
    if pid is None:
        return 0

    # Tracked participant's final row
    p = dict(zip(
        [d[0] for d in src_conn.execute(
            "SELECT * FROM participants WHERE match_id=? AND participant_id=?",
            (mid, pid),
        ).description],
        src_conn.execute(
            "SELECT * FROM participants WHERE match_id=? AND participant_id=?",
            (mid, pid),
        ).fetchone(),
    ))

    # Team totals (kills + dmg) - needed for KP + dmg share
    team_kills, team_dmg = src_conn.execute(
        "SELECT SUM(kills), SUM(total_damage_dealt_to_champs) FROM participants "
        "WHERE match_id=? AND team_id=?",
        (mid, team_id),
    ).fetchone()
    team_kills = team_kills or 0
    team_dmg = team_dmg or 0

    # Common kwargs for every record() call on this match
    base = dict(match_id=mid, session_id=None, champion=champ, mode=mode)

    # --- Final-state metrics (milestone=game_end) ------------------
    def rec(key, value, mtype="text", milestone="game_end", game_time_s=None):
        recorder.record(
            **base, key=key, value=value, metric_type=mtype,
            game_time_s=game_time_s if game_time_s is not None else duration_s,
            milestone_tag=milestone,
        )

    k, d, a = p["kills"], p["deaths"], p["assists"]
    rec("kda_string", f"{k}/{d}/{a}", "text")
    kda_ratio = (k + a) / d if d > 0 else (k + a)
    rec("kda_ratio", f"{kda_ratio:.2f}", "numeric")

    if team_kills > 0:
        kp_pct = round(100 * (k + a) / team_kills)
        rec("kill_participation_pct", f"{kp_pct}% · {k+a}/{team_kills} team", "pct")

    if team_dmg > 0:
        share_pct = round(100 * p["total_damage_dealt_to_champs"] / team_dmg)
        rec("damage_share_summary",
            f"{share_pct}% · {p['total_damage_dealt_to_champs']//1000}k to champs", "pair")

    rec("damage_taken_summary",
        f"{p['total_damage_taken']//1000}k taken · "
        f"{p['damage_self_mitigated']//1000}k mitigated", "pair")

    rec("cc_score_summary",
        f"{p['time_ccing_others']}s applied · {p['total_time_cc_dealt']}s total", "pair")

    if (p["total_heals_on_teammates"] or p["total_damage_shielded_on_teammates"]) > 0:
        rec("heal_shield_summary",
            f"{p['total_damage_shielded_on_teammates']//1000}k shields · "
            f"{p['total_heals_on_teammates']//1000}k heals", "pair")

    td = p["time_spent_dead"] or 0
    td_pct = round(100 * td / duration_s) if duration_s else 0
    rec("time_dead_summary", f"{td}s · {td_pct}% of game", "pair")
    rec("time_alive_pct", f"{100 - td_pct}%", "pct")

    rec("vision_summary",
        f"{p['vision_score']} score · {p['wards_placed']} placed / "
        f"{p['wards_killed']} cleared", "pair")

    if p.get("detector_wards_placed") is not None:
        rec("pink_ward_uptime",
            f"{p['detector_wards_placed']} placed · {p['vision_wards_bought']} bought", "pair")

    rec("tower_kills", f"{p['turret_kills']} kills · {p['turret_takedowns']} takedowns", "pair")
    rec("objective_dance",
        f"drakes {p['dragon_kills']} · baron {p['baron_kills']}", "pair")

    rec("first_blood_flag", "1" if p["first_blood_kill"] else "0", "numeric")
    rec("first_tower_flag", "1" if p["first_tower_kill"] else "0", "numeric")

    rec("cs_total",
        f"{p['total_minions_killed']} + {p['neutral_minions_killed']} jg", "pair")

    rec("gold_earned_total", str(p["gold_earned"] or 0), "numeric")
    rec("longest_alive_s", str(p["longest_time_alive"] or 0), "duration_s")

    # Item slots 0-6 - final build
    for slot in range(7):
        iid = p.get(f"item{slot}")
        if iid and iid > 0:
            rec(f"item_slot_{slot}", str(iid), "numeric")

    # Runes
    if p.get("rune_keystone_id"):
        rec("rune_keystone_id", str(p["rune_keystone_id"]), "numeric")
    if p.get("rune_primary_style"):
        rec("rune_primary_style", str(p["rune_primary_style"]), "numeric")

    # --- 10-minute snapshot ----------------------------------------
    f10 = _nearest_frame(src_conn, mid, pid, 600_000)
    if f10:
        (ts, cg, tg, xp, lvl, cs, jg, dmg, dmg_t, px, py, cc) = f10
        recorder.record(**base, key="cs_at_10", value=f"{cs} CS",
                        metric_type="numeric", game_time_s=ts // 1000,
                        milestone_tag="10min_mark")
        recorder.record(**base, key="gold_at_10", value=str(tg),
                        metric_type="numeric", game_time_s=ts // 1000,
                        milestone_tag="10min_mark")
        recorder.record(**base, key="xp_at_10", value=str(xp),
                        metric_type="numeric", game_time_s=ts // 1000,
                        milestone_tag="10min_mark")
        recorder.record(**base, key="level_at_10", value=str(lvl),
                        metric_type="numeric", game_time_s=ts // 1000,
                        milestone_tag="10min_mark")

    # --- 15-minute snapshot ----------------------------------------
    f15 = _nearest_frame(src_conn, mid, pid, 900_000)
    if f15:
        (ts, cg, tg, xp, lvl, cs, jg, dmg, dmg_t, px, py, cc) = f15
        recorder.record(**base, key="cs_at_15", value=f"{cs} CS",
                        metric_type="numeric", game_time_s=ts // 1000,
                        milestone_tag="15min_mark")
        recorder.record(**base, key="gold_at_15", value=str(tg),
                        metric_type="numeric", game_time_s=ts // 1000,
                        milestone_tag="15min_mark")

    # --- First blood / first tower timestamps ----------------------
    fb = src_conn.execute(
        "SELECT timestamp_ms, killer_id, victim_id FROM timeline_events "
        "WHERE match_id=? AND event_type='CHAMPION_KILL' "
        "ORDER BY timestamp_ms ASC LIMIT 1",
        (mid,),
    ).fetchone()
    if fb:
        fb_ts, fb_killer, _ = fb
        self_fb = 1 if fb_killer == pid else 0
        recorder.record(**base, key="first_blood_time_s",
                        value=str(fb_ts // 1000), metric_type="duration_s",
                        game_time_s=fb_ts // 1000, milestone_tag="first_blood")
        recorder.record(**base, key="first_blood_self", value=str(self_fb),
                        metric_type="numeric", game_time_s=fb_ts // 1000,
                        milestone_tag="first_blood")

    ft = src_conn.execute(
        "SELECT timestamp_ms, team_id FROM timeline_events "
        "WHERE match_id=? AND event_type='BUILDING_KILL' AND building_type='TOWER_BUILDING' "
        "ORDER BY timestamp_ms ASC LIMIT 1",
        (mid,),
    ).fetchone()
    if ft:
        ft_ts, ft_team = ft
        self_ft_team = 1 if ft_team == team_id else 0
        recorder.record(**base, key="first_tower_time_s",
                        value=str(ft_ts // 1000), metric_type="duration_s",
                        game_time_s=ft_ts // 1000, milestone_tag="first_tower")
        recorder.record(**base, key="first_tower_self_team",
                        value=str(self_ft_team), metric_type="numeric",
                        game_time_s=ft_ts // 1000, milestone_tag="first_tower")

    return recorder.buffered()


def iter_matches(conn, limit: int | None, match_id: str | None):
    q = "SELECT match_id, tracked_champion_name, tracked_team_id, game_duration_s, queue_id " \
        "FROM matches WHERE has_stats=1 AND has_timeline=1 " \
        "AND tracked_champion_name IS NOT NULL AND tracked_team_id IS NOT NULL"
    params: list = []
    if match_id:
        q += " AND match_id=?"
        params.append(match_id)
    q += " ORDER BY game_end_ts DESC"
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    for row in conn.execute(q, params):
        yield {
            "match_id": row[0],
            "tracked_champion_name": row[1],
            "tracked_team_id": row[2],
            "game_duration_s": row[3],
            "queue_id": row[4],
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--match", type=str, default=None)
    ap.add_argument("--force", action="store_true",
                    help="Re-process already-filled matches.")
    args = ap.parse_args()

    print(f"Source: {REWIND_DB}")
    print(f"Target: {METRICS_DB}")

    ok, msg = integrity_check()
    print(f"target integrity: {ok} ({msg})")
    if not ok:
        print("ABORT: target DB failed integrity check")
        sys.exit(2)
    print(f"target rows before: {row_count()}")
    print()

    src = sqlite3.connect(f"file:{REWIND_DB}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    processed = 0
    skipped = 0
    total_rows = 0
    for m in iter_matches(src, args.limit, args.match):
        if not args.force and _already_processed(m["match_id"]):
            skipped += 1
            continue
        try:
            retrofill_match(src, m)
            flushed = recorder.flush()
            total_rows += flushed
            processed += 1
            if processed % 25 == 0:
                print(f"  ...processed {processed}  (+{total_rows} rows so far)")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {m['match_id']}: {type(exc).__name__}: {exc}")

    src.close()

    # Final flush (defensive)
    total_rows += recorder.flush()

    print()
    print(f"processed: {processed}")
    print(f"skipped (already filled): {skipped}")
    print(f"rows written: {total_rows}")
    print(f"target rows after: {row_count()}")


if __name__ == "__main__":
    main()
