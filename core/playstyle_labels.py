"""core/playstyle_labels.py - deterministic per-champion playstyle labels.

Serves the Haiku-to-ZERO north star (BACKLOG "Playstyle-inference
deterministic labels for the snapshot card"): ZERO API, ZERO LLM. Pure local
SQL + math over the tracked player's OWN stored match history in
data/rewind_history.db, one row per game the player played.

Every label is a SELF-RELATIVE observation - "on this champion you die more
than your own cross-champion norm" - never a global or causal claim. We only
compare a champion's per-game stat means to the player's own baseline; we do
not rank against other players and we do not assert causation ("you play
worse on X"). We report what the stored record shows.

Sibling of core.session_hygiene: same read-only _open_ro() seam (mirrors
core/duration_winrate.py:57-64), same laplace/shrink/blend primitives
(core.smoothed_rates), same never-raises contract. The operator corpus is
ARAM-dominant (tracked_lane is 0 for ~all games) so we key on CHAMPION, not
lane; a lane/role split would degenerate to a single bucket. tracked_kp is
stored as an integer percent (0-100); a NULL kp drops that game from the kp
means only, never from the WR / KDA means.

Read-only. Never writes to the db. Never raises - an absent db or empty
corpus returns a well-formed ok payload with a null baseline and no champions.
"""
from __future__ import annotations

import logging
import math
import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from core.smoothed_rates import blend, laplace_rate, shrink

log = logging.getLogger("rc.playstyle_labels")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = _PROJECT_ROOT / "data" / "rewind_history.db"

# A champion below this many games does not surface display WR or labels (the
# fingerprint stays descriptive-only). Mirrors core.session_hygiene.MIN_GAMES.
MIN_GAMES = 5

# A champion mean must deviate from the player's own baseline by at least this
# RELATIVE fraction before a directional label fires. 0.20 == 20%.
REL_THRESHOLD = 0.20

# Coefficient-of-variation cutoffs for the per-champion consistency label,
# computed over the per-game (K+A)/max(1,D) ratio. Below LOW == "consistent",
# at/above HIGH == "high-variance". Between the two: no consistency label.
CV_LOW = 0.35
CV_HIGH = 0.70


def _open_ro(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        log.warning("playstyle_labels open: %s", exc)
        return None


def _load_rows(conn: sqlite3.Connection,
               queue_ids: Optional[Iterable[int]]) -> list:
    """Return the tracked player's games with usable KDA.

    Drops rows with a null kill/death/assist (cannot fingerprint). Each item:
    (champ_id, champ_name, win, kills, deaths, assists, kp | None).
    """
    where = ["tracked_kills IS NOT NULL", "tracked_deaths IS NOT NULL",
             "tracked_assists IS NOT NULL"]
    params: list = []
    if queue_ids is not None:
        ids = [int(q) for q in queue_ids]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        where.append(f"queue_id IN ({placeholders})")
        params.extend(ids)
    sql = ("SELECT tracked_champion_id, tracked_champion_name, tracked_win, "
           "tracked_kills, tracked_deaths, tracked_assists, tracked_kp "
           "FROM matches WHERE " + " AND ".join(where))
    out = []
    for cid, cname, win, k, d, a, kp in conn.execute(sql, params).fetchall():
        out.append((
            cid,
            cname or "",
            int(bool(win)),
            int(k),
            int(d),
            int(a),
            None if kp is None else float(kp),
        ))
    return out


def _mean(values: list) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _kda_ratio(k: int, d: int, a: int) -> float:
    return (k + a) / max(1, d)


def _cv(values: list) -> Optional[float]:
    """Coefficient of variation (sample std / mean) over values.

    None when fewer than 2 values or a non-positive mean (CV is undefined /
    unstable there). Deterministic - not smoothed, it is a spread descriptor.
    """
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    if m <= 0:
        return None
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(var) / m


def _rel_label(tag_hi: str, verdict_hi: str, tag_lo: str, verdict_lo: str,
               basis: str, champ_val: Optional[float],
               base_val: Optional[float], rel: float) -> Optional[dict]:
    """A signed self-relative label, or None when the deviation is within band.

    Fires the HIGH label when champ_val >= base*(1+rel), the LOW label when
    champ_val <= base*(1-rel). Returns None on missing / neutral / zero-base.
    """
    if champ_val is None or base_val is None or base_val <= 0:
        return None
    hi = base_val * (1.0 + rel)
    lo = base_val * (1.0 - rel)
    if champ_val >= hi:
        tag, verdict = tag_hi, verdict_hi
    elif champ_val <= lo:
        tag, verdict = tag_lo, verdict_lo
    else:
        return None
    return {
        "tag": tag,
        "verdict": verdict,
        "basis": basis,
        "value": round(champ_val, 3),
        "baseline": round(base_val, 3),
    }


def _labels_for(champ: dict, baseline: dict, rel: float) -> list:
    """Deterministic self-relative VERDICT labels for one champion bucket.

    Each label compares a champion mean to the player's own cross-champion
    baseline, so the whole set is honest observation, never causal advice.
    """
    labels = []

    death = _rel_label(
        "death-prone", "dies more than your own norm on this champ",
        "death-averse", "survives better than your own norm on this champ",
        "deaths", champ["means"]["deaths"], baseline["deaths"], rel)
    if death:
        labels.append(death)

    kills = _rel_label(
        "kill-focused", "takes more kills than your own norm on this champ",
        "low-kill", "takes fewer kills than your own norm on this champ",
        "kills", champ["means"]["kills"], baseline["kills"], rel)
    if kills:
        labels.append(kills)

    involve = _rel_label(
        "team-involved", "higher kill participation than your own norm here",
        "solo-leaning", "lower kill participation than your own norm here",
        "kp", champ["means"]["kp"], baseline["kp"], rel)
    if involve:
        labels.append(involve)

    cv = champ["kda_cv"]
    if cv is not None:
        if cv >= CV_HIGH:
            labels.append({
                "tag": "high-variance",
                "verdict": "coinflip games - your result swings hard on this champ",
                "basis": "kda_cv", "value": round(cv, 3), "baseline": None,
            })
        elif cv < CV_LOW:
            labels.append({
                "tag": "consistent",
                "verdict": "steady games - low swing in your result on this champ",
                "basis": "kda_cv", "value": round(cv, 3), "baseline": None,
            })
    return labels


def compute_playstyle_labels(db_path: Path = DEFAULT_DB,
                             min_games: int = MIN_GAMES,
                             rel_threshold: float = REL_THRESHOLD,
                             queue_ids: Optional[Iterable[int]] = None,
                             conn: Optional[sqlite3.Connection] = None) -> dict:
    """Deterministic per-champion playstyle fingerprint over the own corpus.

    min_games: a champion under this games this many games surfaces no display
        WR and no labels (means stay for transparency). rel_threshold: the
        relative deviation from the player's baseline a champion mean must
        clear before a directional label fires. queue_ids: optional queue
        filter (default all). conn: optional injected sqlite handle (else a
        read-only handle to db_path is opened + closed).

    Never raises. An absent db / empty corpus yields ok=True, n=0, a null
    baseline, and no champions.
    """
    own = conn is None
    if own:
        conn = _open_ro(Path(db_path))

    rows: list = []
    if conn is not None:
        try:
            rows = _load_rows(conn, queue_ids)
        except sqlite3.Error as exc:
            log.warning("playstyle_labels query: %s", exc)
            rows = []
        finally:
            if own:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass

    total_games = len(rows)
    total_wins = sum(r[2] for r in rows)
    overall_wr = laplace_rate(total_wins, total_games)

    # ---- player baseline (cross-champion means) --------------------------
    all_k = [r[3] for r in rows]
    all_d = [r[4] for r in rows]
    all_a = [r[5] for r in rows]
    all_kp = [r[6] for r in rows if r[6] is not None]
    baseline = {
        "kills": _mean(all_k),
        "deaths": _mean(all_d),
        "assists": _mean(all_a),
        "kp": _mean(all_kp),
        "kda_ratio": _mean([_kda_ratio(k, d, a)
                            for k, d, a in zip(all_k, all_d, all_a)]),
    }

    # ---- per-champion buckets --------------------------------------------
    buckets: dict = {}
    for cid, cname, win, k, d, a, kp in rows:
        b = buckets.get(cid)
        if b is None:
            b = buckets[cid] = {
                "champion_id": cid, "champion_name": cname,
                "games": 0, "wins": 0,
                "_k": [], "_d": [], "_a": [], "_kp": [], "_ratio": [],
            }
        # Prefer a non-empty name if a later row carries one.
        if not b["champion_name"] and cname:
            b["champion_name"] = cname
        b["games"] += 1
        b["wins"] += win
        b["_k"].append(k)
        b["_d"].append(d)
        b["_a"].append(a)
        if kp is not None:
            b["_kp"].append(kp)
        b["_ratio"].append(_kda_ratio(k, d, a))

    champions = []
    for b in buckets.values():
        g = b["games"]
        w = b["wins"]
        rate = laplace_rate(w, g)
        champ = {
            "champion_id": b["champion_id"],
            "champion_name": b["champion_name"],
            "games": g,
            "wins": w,
            "wr": round(rate, 4) if g >= min_games else None,
            "wr_blended": round(blend(rate, overall_wr, shrink(g)), 4),
            "means": {
                "kills": round(_mean(b["_k"]), 3),
                "deaths": round(_mean(b["_d"]), 3),
                "assists": round(_mean(b["_a"]), 3),
                "kp": (None if not b["_kp"] else round(_mean(b["_kp"]), 3)),
                "kda_ratio": round(_mean(b["_ratio"]), 3),
            },
            "kda_cv": (None if _cv(b["_ratio"]) is None
                       else round(_cv(b["_ratio"]), 3)),
            "labels": [],
        }
        if g >= min_games:
            champ["labels"] = _labels_for(champ, baseline, rel_threshold)
        champions.append(champ)

    # Widest evidence first; stable tie-break on champion id.
    champions.sort(key=lambda c: (-c["games"], c["champion_id"]))

    rounded_baseline = {
        key: (None if val is None else round(val, 3))
        for key, val in baseline.items()
    }

    return {
        "ok": True,
        "n": total_games,
        "min_games": min_games,
        "rel_threshold": rel_threshold,
        "overall_wr": round(overall_wr, 4),
        "overall_wins": total_wins,
        "baseline": rounded_baseline,
        "champions": champions,
    }
