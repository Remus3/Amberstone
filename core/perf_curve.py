"""Per-minute averaged performance curve over the local rewind_history.db.

A per-mode curve of the tracked player's average cumulative gold (or creep
score) at each game minute, split into the games the player WON vs LOST -
the per-minute "performance graph" popularized by public player-analytics
sites, here computed over the operator's OWN match corpus (no global /
cross-player data, no Riot or Claude call). Reading the split: a win curve
that pulls away from the loss curve early reads as "I snowball my leads";
a loss curve that flattens around a minute reads as "my losses stall there".

Read-only. Mirrors core.duration_winrate's map_id mode mapping + MIN_DURATION_S
remake gate + conn-injection seam (so tests inject an in-memory db and the
suite stays clean-checkout safe; the db is gitignored).

The tracked participant's per-minute frames are reached by the same join
core.player_gpi uses (matches.tracked_champion_id + tracked_team_id ->
participants.participant_id) then participants.participant_id ->
timeline_frames. total_gold + minions_killed + jungle_minions are cumulative
to each frame in the Match-V5 timeline, so the per-minute value is the running
total at that minute (exactly a gold/CS curve). Damage is intentionally NOT
offered here: timeline total_dmg is cumulative AND all-units (not to-champs),
so a damage curve would mislead - a separate batch with the right field.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger("rc.perf_curve")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REWIND_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

# map_id per mode - same convention as core.duration_winrate / core.player_gpi.
MODE_MAPS: dict[str, int] = {"sr": 11, "aram": 12, "arena": 30}
VALID_MODES = ("sr", "aram", "arena")
# ARAM-dominant corpus -> default to the most-populated curve (mirror
# duration_winrate).
DEFAULT_MODE = "aram"

VALID_METRICS = ("gold", "cs")
DEFAULT_METRIC = "gold"

MIN_DURATION_S = 300      # drop remakes / very-early surrenders (mirror player_gpi)
MAX_MINUTE = 45           # cap the curve; a real game frame never exceeds this
MIN_GAMES_N = 5           # below this a minute's average is untrustworthy -> None


def _open_ro() -> Optional[sqlite3.Connection]:
    if not _REWIND_DB.exists():
        return None
    try:
        return sqlite3.connect(f"file:{_REWIND_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("perf_curve open: %s", exc)
        return None


def compute_perf_curve(mode: str = DEFAULT_MODE,
                       champion: Optional[int] = None,
                       metric: str = DEFAULT_METRIC,
                       conn: Optional[sqlite3.Connection] = None) -> dict:
    """Per-minute average of ``metric`` for the tracked player, win vs loss.

    ``mode`` in VALID_MODES (else DEFAULT_MODE). ``metric`` in VALID_METRICS
    (else DEFAULT_METRIC): "gold" -> cumulative total_gold, "cs" -> cumulative
    minions_killed + jungle_minions. ``champion`` is an optional Riot integer
    champion id (filters tracked_champion_id). ``conn`` injects a db connection
    for tests; when None a read-only handle to the local rewind db is opened +
    closed. Never raises - an unavailable db or empty corpus returns an ok
    payload with minutes == [].
    """
    if mode not in MODE_MAPS:
        mode = DEFAULT_MODE
    if metric not in VALID_METRICS:
        metric = DEFAULT_METRIC
    map_id = MODE_MAPS[mode]
    value_sql = ("f.total_gold" if metric == "gold"
                 else "COALESCE(f.minions_killed, 0) + COALESCE(f.jungle_minions, 0)")

    own = conn is None
    if own:
        conn = _open_ro()

    rows: list = []
    if conn is not None:
        try:
            where = ["m.map_id = ?", "m.has_stats = 1", "m.game_duration_s >= ?"]
            params: list = [map_id, MIN_DURATION_S]
            if champion is not None:
                where.append("m.tracked_champion_id = ?")
                params.append(int(champion))
            sql = (
                "SELECT m.match_id, m.tracked_win, p.participant_id, "
                "f.timestamp_ms, " + value_sql + " AS val "
                "FROM matches m "
                "JOIN participants p ON p.match_id = m.match_id "
                "AND p.champion_id = m.tracked_champion_id "
                "AND p.team_id = m.tracked_team_id "
                "JOIN timeline_frames f ON f.match_id = m.match_id "
                "AND f.participant_id = p.participant_id "
                "WHERE " + " AND ".join(where) + " "
                "ORDER BY m.match_id, p.participant_id, f.timestamp_ms"
            )
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.warning("perf_curve query: %s", exc)
            rows = []
        finally:
            if own:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    # Per match: lock onto the first participant_id seen (sentinel tracked ids
    # can multi-match the join; mirror player_gpi's keep-first dedup) and keep
    # one cumulative value per (match, minute) - the last frame wins if two
    # frames ever land in the same minute bucket.
    locked_pid: dict[str, int] = {}
    win_by_match: dict[str, bool] = {}
    per_match_minute: dict[str, dict[int, float]] = {}
    for match_id, tracked_win, pid, ts_ms, val in rows:
        if match_id not in locked_pid:
            locked_pid[match_id] = pid
            win_by_match[match_id] = bool(tracked_win)
            per_match_minute[match_id] = {}
        if pid != locked_pid[match_id]:
            continue
        if val is None:
            continue
        minute = int(ts_ms or 0) // 60000
        if minute < 0 or minute > MAX_MINUTE:
            continue
        per_match_minute[match_id][minute] = float(val)

    # Aggregate across matches per minute, split win vs loss.
    win_sum: dict[int, float] = {}
    win_cnt: dict[int, int] = {}
    loss_sum: dict[int, float] = {}
    loss_cnt: dict[int, int] = {}
    for match_id, minute_vals in per_match_minute.items():
        won = win_by_match.get(match_id, False)
        for minute, val in minute_vals.items():
            if won:
                win_sum[minute] = win_sum.get(minute, 0.0) + val
                win_cnt[minute] = win_cnt.get(minute, 0) + 1
            else:
                loss_sum[minute] = loss_sum.get(minute, 0.0) + val
                loss_cnt[minute] = loss_cnt.get(minute, 0) + 1

    last_minute = -1
    for minute in list(win_cnt) + list(loss_cnt):
        if (win_cnt.get(minute, 0) >= MIN_GAMES_N
                or loss_cnt.get(minute, 0) >= MIN_GAMES_N):
            last_minute = max(last_minute, minute)

    minutes = []
    for minute in range(0, last_minute + 1):
        wc = win_cnt.get(minute, 0)
        lc = loss_cnt.get(minute, 0)
        win_avg = round(win_sum[minute] / wc, 1) if wc >= MIN_GAMES_N else None
        loss_avg = round(loss_sum[minute] / lc, 1) if lc >= MIN_GAMES_N else None
        if win_avg is None and loss_avg is None:
            continue
        minutes.append({
            "minute": minute,
            "win_avg": win_avg,
            "win_n": wc,
            "loss_avg": loss_avg,
            "loss_n": lc,
        })

    n_games = len(per_match_minute)
    return {
        "ok": True,
        "mode": mode,
        "metric": metric,
        "champion": champion,
        "n_games": n_games,
        "min_games_n": MIN_GAMES_N,
        "minutes": minutes,
    }
