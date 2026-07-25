"""DS pick-vs-outcome calibration aggregator (RM-32 / D-01).

WHAT
    ``core/ds_calibration.py`` is the PRODUCER half: every coaching tick
    appends one line to ``data/ds_calibration.jsonl`` recording what Daemon
    Slayer recommended (ts / champion / mode / level / owned_items /
    ds_picks[item_id, item_name, delta_dps, gold, scorer]). Nothing consumed
    it - RM-32 parked the consumer as "data-blocked". This module is that
    consumer: it joins the accrued recommendation log against real match
    OUTCOMES in ``data/rewind_history.db`` and answers two questions.

      1. AGREEMENT - when DS recommended item X in game G and the operator
         did not already own it, did the operator actually buy X later in
         that same game?
      2. OUTCOME CORRELATION - do the games (and the observations) where the
         recommendation was followed win more often than the ones where it
         was not?

    Both are reported per (mode x scorer) cell.

HARD FIREWALL
    DESCRIPTIVE / EMPIRICAL ONLY. Same firewall as
    ``core/aram_item_interaction.py``: this surface must NEVER feed back into
    ``agents/daemon_slayer`` rank. DS answers "what is optimal in
    simulation"; this answers "what the operator actually did and how those
    games ended". Wiring one into the other would launder a tiny personal
    corpus - and the operator's own buying habits - into the engine's
    optimality math. ``tests/test_ds_calibration_agreement.py`` pins the
    firewall in both directions.

OBSERVATION UNIT (the load-bearing scope cut)
    A coaching tick fires roughly every 30s, so one game emits the SAME
    recommendation dozens of times. Counting ticks would pseudo-replicate a
    handful of games into thousands of fake observations. The unit is
    therefore ONE observation per ``(game_id, item_id, scorer)``, taken at
    the EARLIEST tick that recommended it while it was not already owned.

FOLLOWED, DEFINED
    An observation is ``followed`` when the tracked participant has an
    ``ITEM_PURCHASED`` timeline event for that item id at a wall clock at or
    after the recommending tick (minus ``PURCHASE_GRACE_S`` of tick jitter).
    Timeline event stamps are ms from game start; ``matches.game_creation_ts``
    converts them into the same wall clock the jsonl ``ts`` uses. When a
    joined match has no purchase events for the tracked participant, the
    final ``participants.item0..item6`` inventory is the fallback signal and
    the ordering test is waived (counted as ``games_inventory_fallback``).

STATISTICAL DISCIPLINE
    Every rate goes through ``core.smoothed_rates`` (Laplace shrink toward
    0.5 plus the n/(n+k) confidence weight), and ``MIN_BUCKET_N`` is a HARD
    gate: a cell below it is omitted entirely, never surfaced with a shy
    number. The count of omitted cells is reported.

Read-only, connection-injected (tests inject an in-memory sqlite fixture and
a record list; the db and the jsonl are both gitignored, so the suite stays
clean-checkout safe). Never raises - one unreadable match is logged and
skipped.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Iterable, Optional, Sequence

from core.smoothed_rates import DEFAULT_ALPHA, DEFAULT_K, laplace_rate, shrink

log = logging.getLogger("rc.ds_calibration_agreement")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _PROJECT_ROOT / "data" / "rewind_history.db"
DEFAULT_LOG = _PROJECT_ROOT / "data" / "ds_calibration.jsonl"

# Hard per-cell sample gate. Below this a follow-rate or a win-rate over the
# operator's own corpus is noise, so the cell is omitted from the payload.
MIN_BUCKET_N = 20

# Tick-jitter tolerance: the ds_picks were computed from a snapshot slightly
# before the line was appended, so a purchase landing a few seconds "before"
# the logged ts still counts as a follow.
PURCHASE_GRACE_S = 10.0

# ds_picks written before the scorer column existed carry no scorer key.
UNKNOWN_SCORER = "unknown"

_ITEM_COLS = ("item0", "item1", "item2", "item3", "item4", "item5", "item6")


# --------------------------------------------------------------------------
# Record loading.
# --------------------------------------------------------------------------

def load_records(path: Path | str | None = None) -> list[dict]:
    """Parse ``data/ds_calibration.jsonl`` into a list of record dicts.

    Fail-soft on every axis: a missing file yields ``[]``, a malformed line is
    counted in the log and skipped, a non-dict line is skipped.
    """
    src = Path(path) if path is not None else DEFAULT_LOG
    out: list[dict] = []
    bad = 0
    try:
        with open(src, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if isinstance(entry, dict):
                    out.append(entry)
                else:
                    bad += 1
    except OSError as exc:
        log.warning("load_records %s: %s", src, exc)
        return []
    if bad:
        log.warning("load_records %s: skipped %d malformed lines", src, bad)
    return out


def _game_key(match_id: str) -> str:
    """``"NA1_5557010443" -> "5557010443"`` (the bare gameId the log stores)."""
    return str(match_id or "").rsplit("_", 1)[-1]


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Match-side facts.
# --------------------------------------------------------------------------

def _match_index(conn: sqlite3.Connection) -> dict[str, dict]:
    """``{bare_game_id: {match_id, gct_s, win, champion_id, team_id}}``.

    One scan of the ``matches`` table (a few thousand rows), indexed on the
    numeric suffix of ``match_id`` so the join is exact rather than a LIKE
    pattern (``_`` is a LIKE wildcard and would over-match).
    """
    try:
        rows = conn.execute(
            "SELECT match_id, game_creation_ts, tracked_win, "
            "tracked_champion_id, tracked_team_id FROM matches"
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("_match_index: %s", exc)
        return {}
    index: dict[str, dict] = {}
    for match_id, gct_ms, win, champ_id, team_id in rows:
        key = _game_key(match_id)
        if not key:
            continue
        index[key] = {
            "match_id": match_id,
            "gct_s": (float(gct_ms) / 1000.0) if gct_ms is not None else None,
            "win": None if win is None else bool(win),
            "champion_id": _as_int(champ_id),
            "team_id": _as_int(team_id),
        }
    return index


def _tracked_participant(conn: sqlite3.Connection, meta: dict) -> Optional[tuple]:
    """``(participant_id, final_inventory_set)`` for the tracked player.

    Resolves on ``champion_id == matches.tracked_champion_id``, narrowed by
    ``team_id`` when more than one row matches (a champion can be picked by
    both teams outside of draft). ``None`` when it cannot be resolved.
    """
    try:
        rows = conn.execute(
            "SELECT participant_id, team_id, "
            + ", ".join(_ITEM_COLS)
            + " FROM participants WHERE match_id=? AND champion_id=?",
            (meta["match_id"], meta["champion_id"]),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("_tracked_participant %s: %s", meta.get("match_id"), exc)
        return None
    if not rows:
        return None
    if len(rows) > 1 and meta.get("team_id") is not None:
        narrowed = [r for r in rows if _as_int(r[1]) == meta["team_id"]]
        if narrowed:
            rows = narrowed
    row = rows[0]
    pid = _as_int(row[0])
    if pid is None:
        return None
    inventory = {v for v in (_as_int(x) for x in row[2:]) if v}
    return (pid, inventory)


def _purchase_times(conn: sqlite3.Connection, match_id: str,
                    participant_id: int) -> dict[int, float]:
    """``{item_id: earliest purchase offset in seconds from game start}``."""
    try:
        rows = conn.execute(
            "SELECT item_id, MIN(timestamp_ms) FROM timeline_events "
            "WHERE match_id=? AND event_type='ITEM_PURCHASED' "
            "AND participant_id=? GROUP BY item_id",
            (match_id, participant_id),
        ).fetchall()
    except sqlite3.Error as exc:
        log.warning("_purchase_times %s: %s", match_id, exc)
        return {}
    out: dict[int, float] = {}
    for item_id, ts_ms in rows:
        iid = _as_int(item_id)
        if iid is None or ts_ms is None:
            continue
        out[iid] = float(ts_ms) / 1000.0
    return out


# --------------------------------------------------------------------------
# Aggregation.
# --------------------------------------------------------------------------

class _Cell:
    __slots__ = ("n", "followed", "wins_followed", "n_followed",
                 "wins_unfollowed", "n_unfollowed")

    def __init__(self) -> None:
        self.n = 0
        self.followed = 0
        self.wins_followed = 0.0
        self.n_followed = 0
        self.wins_unfollowed = 0.0
        self.n_unfollowed = 0


def compute_ds_calibration_agreement(
    conn: sqlite3.Connection,
    records: Optional[Iterable[dict]] = None,
    *,
    min_n: int = MIN_BUCKET_N,
    alpha: float = DEFAULT_ALPHA,
    shrink_k: float = DEFAULT_K,
    log_path: Path | str | None = None,
) -> dict:
    """Join DS recommendations against match outcomes; report agreement.

    ``records`` is the parsed ds_calibration log; when ``None`` it is loaded
    from ``log_path`` (default ``data/ds_calibration.jsonl``). ``conn`` is a
    read-only handle to ``rewind_history.db`` - injected so tests can pass an
    in-memory fixture.

    Each emitted cell is one ``(mode, scorer)`` pair carrying::

        n                        observations (game x item x scorer)
        followed                 how many were actually bought afterwards
        follow_rate              followed / n
        follow_rate_smoothed     Laplace shrink toward 0.5
        confidence               n / (n + k)
        n_followed / n_unfollowed
        winrate_followed / winrate_unfollowed          raw
        winrate_followed_smoothed / ..._unfollowed_smoothed
        winrate_delta_shrunk     smoothed gap x min(confidence of both arms)

    Cells with ``n < min_n`` are omitted and counted in
    ``cells_dropped_below_min_n``. Never raises.
    """
    t0 = time.time()
    if records is None:
        records = load_records(log_path)
    records = list(records)

    index = _match_index(conn)

    # ---- bucket the ticks by game -------------------------------------
    by_game: dict[str, list[dict]] = {}
    no_game_id = 0
    for entry in records:
        gid = str(entry.get("game_id") or "").strip()
        if not gid:
            # D-01b: a REAL Riot id can now arrive only via ``match_key``, which
            # ``core/live_metrics.match_key()`` mints as ``live_<gameId>``. Accept
            # that form so the producer-side key is actually read.
            #
            # Synthetic ``sess_<mode>_<champ>_<seq>`` keys are deliberately NOT
            # accepted here. They group every tick of one game (which is what the
            # producer fix buys) but they can never resolve against
            # rewind_history.db, so admitting them would move ~5967 ARAM/Arena
            # rows out of ``records_without_game_id`` and into ``games_unjoined``
            # while adding exactly zero joins - a worse diagnostic, not a better
            # one. Grouping without an outcome is not a join.
            match_key = str(entry.get("match_key") or "").strip()
            if match_key.startswith("live_"):
                gid = match_key[len("live_"):].strip()
        if not gid:
            no_game_id += 1
            continue
        by_game.setdefault(gid, []).append(entry)

    cells: dict[tuple[str, str], _Cell] = {}
    games_joined = 0
    games_unjoined = 0
    games_unresolved = 0
    games_inventory_fallback = 0
    observations = 0
    followed_total = 0
    game_follow: list[tuple[bool, float]] = []  # (win, per-game follow rate)

    for gid, ticks in by_game.items():
        meta = index.get(gid)
        if meta is None:
            games_unjoined += 1
            continue
        try:
            resolved = _tracked_participant(conn, meta)
            if resolved is None:
                games_unresolved += 1
                continue
            pid, inventory = resolved
            purchases = _purchase_times(conn, meta["match_id"], pid)
            fallback = not purchases
            if fallback:
                games_inventory_fallback += 1
            gct_s = meta.get("gct_s")
            win = bool(meta.get("win"))

            ticks.sort(key=lambda e: float(e.get("ts") or 0.0))
            # earliest recommending tick per (item_id, scorer), skipping any
            # pick the operator already owned at that moment
            seen: dict[tuple[int, str], tuple[float, str]] = {}
            for entry in ticks:
                owned = {v for v in
                         (_as_int(i) for i in (entry.get("owned_items") or []))
                         if v is not None}
                mode = str(entry.get("mode") or "?").upper()
                ts = float(entry.get("ts") or 0.0)
                for pick in (entry.get("ds_picks") or []):
                    if not isinstance(pick, dict):
                        continue
                    iid = _as_int(pick.get("item_id"))
                    if iid is None or iid in owned:
                        continue
                    scorer = str(pick.get("scorer") or UNKNOWN_SCORER)
                    key = (iid, scorer)
                    if key not in seen:
                        seen[key] = (ts, mode)

            g_n = 0
            g_followed = 0
            for (iid, scorer), (ts, mode) in seen.items():
                bought_s = purchases.get(iid)
                if fallback:
                    was_followed = iid in inventory
                elif bought_s is None:
                    was_followed = False
                elif gct_s is None:
                    was_followed = True  # cannot order it; buying it counts
                else:
                    was_followed = (gct_s + bought_s) >= (ts - PURCHASE_GRACE_S)

                cell = cells.setdefault((mode, scorer), _Cell())
                cell.n += 1
                g_n += 1
                observations += 1
                if was_followed:
                    cell.followed += 1
                    cell.n_followed += 1
                    cell.wins_followed += float(win)
                    followed_total += 1
                    g_followed += 1
                else:
                    cell.n_unfollowed += 1
                    cell.wins_unfollowed += float(win)

            games_joined += 1
            if g_n:
                game_follow.append((win, g_followed / g_n))
        except Exception as exc:  # noqa: BLE001 - one bad match cannot abort
            log.warning("compute_ds_calibration_agreement: game %s -> %s",
                        gid, exc)
            continue

    out_cells: list[dict] = []
    omitted = 0
    for (mode, scorer), cell in cells.items():
        if cell.n < min_n:
            omitted += 1
            continue
        wr_f = (cell.wins_followed / cell.n_followed) if cell.n_followed else None
        wr_u = (cell.wins_unfollowed / cell.n_unfollowed
                if cell.n_unfollowed else None)
        sm_f = (round(laplace_rate(cell.wins_followed, cell.n_followed, alpha), 4)
                if cell.n_followed else None)
        sm_u = (round(laplace_rate(cell.wins_unfollowed, cell.n_unfollowed, alpha), 4)
                if cell.n_unfollowed else None)
        if sm_f is not None and sm_u is not None:
            conf = min(shrink(float(cell.n_followed), shrink_k),
                       shrink(float(cell.n_unfollowed), shrink_k))
            delta = round((sm_f - sm_u) * conf, 4)
        else:
            delta = None
        out_cells.append({
            "mode": mode,
            "scorer": scorer,
            "n": cell.n,
            "followed": cell.followed,
            "follow_rate": round(cell.followed / cell.n, 4),
            "follow_rate_smoothed": round(
                laplace_rate(cell.followed, cell.n, alpha), 4),
            "confidence": round(shrink(float(cell.n), shrink_k), 4),
            "n_followed": cell.n_followed,
            "n_unfollowed": cell.n_unfollowed,
            "winrate_followed": None if wr_f is None else round(wr_f, 4),
            "winrate_unfollowed": None if wr_u is None else round(wr_u, 4),
            "winrate_followed_smoothed": sm_f,
            "winrate_unfollowed_smoothed": sm_u,
            "winrate_delta_shrunk": delta,
        })
    out_cells.sort(key=lambda c: (c["mode"], c["scorer"]))

    wins = [r for w, r in game_follow if w]
    losses = [r for w, r in game_follow if not w]

    return {
        "ok": True,
        "min_n": min_n,
        "alpha": alpha,
        "shrink_k": shrink_k,
        "ticks": len(records),
        "observations": observations,
        "followed": followed_total,
        "follow_rate_overall": (round(followed_total / observations, 4)
                                if observations else None),
        "follow_rate_overall_smoothed": (
            round(laplace_rate(followed_total, observations, alpha), 4)
            if observations else None),
        "cells": out_cells,
        "cells_dropped_below_min_n": omitted,
        "games": {
            "joined": games_joined,
            "wins": sum(1 for w, _ in game_follow if w),
            "losses": sum(1 for w, _ in game_follow if not w),
            "mean_follow_rate_win": (round(sum(wins) / len(wins), 4)
                                     if wins else None),
            "mean_follow_rate_loss": (round(sum(losses) / len(losses), 4)
                                      if losses else None),
        },
        "coverage": {
            "records": len(records),
            "records_without_game_id": no_game_id,
            "games_in_log": len(by_game),
            "games_joined": games_joined,
            "games_unjoined": games_unjoined,
            "games_participant_unresolved": games_unresolved,
            "games_inventory_fallback": games_inventory_fallback,
        },
        "elapsed_ms": int((time.time() - t0) * 1000),
    }


def compute_ds_calibration_agreement_from_db(
    db_path: Path | str | None = None,
    log_path: Path | str | None = None,
    *,
    min_n: int = MIN_BUCKET_N,
    records: Optional[Sequence[dict]] = None,
) -> dict:
    """Open ``rewind_history.db`` read-only, aggregate, close.

    ``{"ok": False, "error": "rewind_history.db missing"}`` when the db is
    absent, so a clean checkout gets a clear answer rather than a traceback.
    """
    src = Path(db_path) if db_path is not None else DEFAULT_DB
    if not src.exists():
        return {"ok": False, "error": f"rewind_history.db missing: {src}"}
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    try:
        return compute_ds_calibration_agreement(
            conn, records, min_n=min_n, log_path=log_path)
    finally:
        conn.close()
