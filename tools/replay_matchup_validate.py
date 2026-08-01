"""tools/replay_matchup_validate.py - the Haiku-flip GATE (DS Lane A, W3B 2026-06-02).

Replay-validation harness for the deterministic 1v1 matchup engine
(``agents.daemon_slayer.matchup.compute_matchup``). It REPORTS one number: how
often the engine's favored champion in a lane head-to-head actually came out
ahead in the real game. That number is the gate that decides whether the engine
is a trustworthy enough signal to flip a live coach off its Claude Haiku
"who-wins-this-trade" call.

How it works
------------
1. Select Summoner's Rift / Classic matches from the local ``rewind_history.db``
   (game_mode='CLASSIC'; the SR queue family). Limit with ``--limit N``.
2. Per match, pair same-lane opponents across the two teams by ``team_position``
   (TOP vs TOP, JUNGLE vs JUNGLE, MIDDLE vs MIDDLE, BOTTOM vs BOTTOM,
   UTILITY vs UTILITY). Team 100 = participant_id 1-5, team 200 = 6-10.
3. For each ordered pair (champ on team 100 = A, champ on team 200 = B) call
   ``compute_matchup(snapshot, A, B, level_a=L, level_b=L, mode='SR')`` IN-PROCESS
   (not the network client - far faster for thousands of calls). Itemless, at a
   representative early-lane level (default 6 and 9, reported separately).
   Favored = A if net_swing > 0 else B. Pairs with |net_swing| below a small
   dead-band are counted as "even" and excluded from the agreement denominator.
4. GROUND TRUTH (a proxy, honestly lower-fidelity): from ``timeline_frames`` read
   each participant's ``total_gold`` at the ~10-minute frame. The actual lane
   "winner" = the participant with the higher gold at 10 min. This is influenced
   by ganks / jungle pathing / roams, so it is a noisy proxy for the pure 1v1
   trade the engine models - treat the agreement number with that caveat.
5. AGREEMENT = (pairs where engine-favored champ == higher-gold champ) /
   (decisive pairs). Reported at each level, overall and per-role, with sample
   size n, the even-band exclusion count, and a 95% Wilson interval.

Interpreting the result
-----------------------
- agreement ~50% = the engine is a coin-flip / carries no signal. Do NOT flip any
  coach off Haiku on the strength of it.
- agreement meaningfully > 50% (e.g. >= 55-58% with n in the thousands) = the
  engine carries real predictive signal and is a defensible deterministic
  substitute for the LLM trade judgment for THIS lane-outcome proxy.
This harness only reports the number. A human / orchestrator decides the flip.

Output
------
- A JSON gate artifact at ``ops/runtime/matchup_validation.json`` (override with
  ``--out``). This is the durable deliverable.
- A concise human summary table on stdout.

Fail-soft: a malformed match or pair never aborts the run - it is skipped and
counted. ASCII-only by hard rule.

"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# Resolve project root so the agents.daemon_slayer import works regardless of CWD.
_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ----------------------------------------------------------------- tunable defaults
_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_OUT = _ROOT / "ops" / "runtime" / "matchup_validation.json"
_DEFAULT_LIMIT = 400
_DEFAULT_LEVELS = (6, 9)
_DEFAULT_GOLD_FRAME_MIN = 10

# |net_swing| below this counts as "even" - excluded from the agreement denominator.
_EVEN_BAND = 0.02

# The five SR lane positions; pairing is strictly same-position across teams.
_LANES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")

# game_mode value that identifies Summoner's Rift / Classic in rewind_history.db.
_SR_GAME_MODE = "CLASSIC"


# ------------------------------------------------------------------------- datatypes
@dataclass
class LanePair:
    """One same-lane head-to-head extracted from a replay."""

    match_id: str
    lane: str
    champ_a: str  # team 100 side
    champ_b: str  # team 200 side
    gold_a: float  # team 100 gold at the chosen frame
    gold_b: float  # team 200 gold at the chosen frame
    # participant ids (needed for the trade / solo-kill ground truth). Default 0
    # so the existing positional constructions (gold-only tests) stay valid.
    pid_a: int = 0
    pid_b: int = 0


@dataclass
class LevelResult:
    """Agreement scoring for a single replay level."""

    level: int
    n_decisive: int = 0
    n_agree: int = 0
    n_even: int = 0  # engine called it even (below dead-band) - excluded
    n_gold_tie: int = 0  # gold was equal at the frame - excluded (gold mode)
    n_engine_none: int = 0  # compute_matchup returned no usable swing - excluded
    n_no_duel: int = 0  # the lane pair never solo-killed each other (trade mode)
    n_kill_tie: int = 0  # equal solo-kill counts (trade mode) - excluded
    per_role: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def record(self, role: str, agreed: bool) -> None:
        self.n_decisive += 1
        if agreed:
            self.n_agree += 1
        slot = self.per_role.setdefault(role, {"n": 0, "agree": 0})
        slot["n"] += 1
        if agreed:
            slot["agree"] += 1

    @property
    def agreement(self) -> Optional[float]:
        if self.n_decisive <= 0:
            return None
        return self.n_agree / self.n_decisive

    def to_dict(self) -> dict:
        lo, hi = wilson_interval(self.n_agree, self.n_decisive)
        per_role_out = {}
        for role, slot in sorted(self.per_role.items()):
            n = slot["n"]
            per_role_out[role] = {
                "n": n,
                "agree": slot["agree"],
                "agreement": (slot["agree"] / n) if n else None,
            }
        return {
            "level": self.level,
            "n_decisive": self.n_decisive,
            "n_agree": self.n_agree,
            "agreement": self.agreement,
            "wilson_95_lo": lo,
            "wilson_95_hi": hi,
            "excluded": {
                "even_band": self.n_even,
                "gold_tie": self.n_gold_tie,
                "engine_none": self.n_engine_none,
                "no_duel": self.n_no_duel,
                "kill_tie": self.n_kill_tie,
            },
            "per_role": per_role_out,
        }


# ------------------------------------------------------------------------- statistics
def wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    """95% Wilson score interval for a binomial proportion. None if n == 0."""
    if n <= 0:
        return (None, None)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    lo = (centre - margin) / denom
    hi = (centre + margin) / denom
    return (max(0.0, lo), min(1.0, hi))


# --------------------------------------------------------------------------- db reads
def select_sr_match_ids(conn: sqlite3.Connection, limit: int) -> List[str]:
    """Return SR/Classic match_ids that carry a timeline, most-recent first.

    ``limit <= 0`` means all. Fail-soft: a missing column degrades to an empty
    list rather than raising.
    """
    sql = (
        "SELECT match_id FROM matches "
        "WHERE game_mode = ? AND has_timeline = 1 "
        "ORDER BY game_creation_ts DESC"
    )
    try:
        rows = conn.execute(sql, (_SR_GAME_MODE,)).fetchall()
    except sqlite3.Error:
        return []
    ids = [r[0] for r in rows if r and r[0]]
    if limit and limit > 0:
        ids = ids[:limit]
    return ids


def _nearest_frame_ts(conn: sqlite3.Connection, match_id: str, target_ms: int) -> Optional[int]:
    """Distinct frame timestamp closest to ``target_ms`` for this match, or None."""
    try:
        rows = conn.execute(
            "SELECT DISTINCT timestamp_ms FROM timeline_frames WHERE match_id = ?",
            (match_id,),
        ).fetchall()
    except sqlite3.Error:
        return None
    stamps = [r[0] for r in rows if r and r[0] is not None]
    if not stamps:
        return None
    return min(stamps, key=lambda t: abs(t - target_ms))


def extract_lane_pairs(conn: sqlite3.Connection, match_id: str, gold_frame_min: int) -> List[LanePair]:
    """Pair same-lane opponents in one match and attach gold at the chosen frame.

    Returns one LanePair per lane that has BOTH a team-100 and a team-200 entry
    with a resolvable gold figure. Fail-soft: any DB error -> empty list.
    """
    try:
        prows = conn.execute(
            "SELECT participant_id, team_id, champion_name, team_position "
            "FROM participants WHERE match_id = ?",
            (match_id,),
        ).fetchall()
    except sqlite3.Error:
        return []

    # Map participant_id -> (champ, lane, team) for the well-formed rows only.
    by_lane: Dict[str, Dict[int, Tuple[int, str]]] = {}
    for pid, team_id, champ, pos in prows:
        if pid is None or not champ or not pos:
            continue
        lane = str(pos).upper()
        if lane not in _LANES:
            continue
        # team 100 -> side A, team 200 -> side B (fall back to participant_id band).
        side = "A"
        if team_id == 200:
            side = "B"
        elif team_id == 100:
            side = "A"
        elif pid is not None and int(pid) > 5:
            side = "B"
        by_lane.setdefault(lane, {})[int(pid)] = (champ, side)

    frame_ts = _nearest_frame_ts(conn, match_id, gold_frame_min * 60 * 1000)
    if frame_ts is None:
        return []

    # Gold per participant at the chosen frame.
    try:
        grows = conn.execute(
            "SELECT participant_id, total_gold FROM timeline_frames "
            "WHERE match_id = ? AND timestamp_ms = ?",
            (match_id, frame_ts),
        ).fetchall()
    except sqlite3.Error:
        return []
    gold_by_pid: Dict[int, float] = {}
    for pid, gold in grows:
        if pid is None or gold is None:
            continue
        gold_by_pid[int(pid)] = float(gold)

    pairs: List[LanePair] = []
    for lane, members in by_lane.items():
        side_a = [(pid, champ) for pid, (champ, s) in members.items() if s == "A"]
        side_b = [(pid, champ) for pid, (champ, s) in members.items() if s == "B"]
        if len(side_a) != 1 or len(side_b) != 1:
            # Skip lanes that are not a clean 1v1 (missing / doubled).
            continue
        pid_a, champ_a = side_a[0]
        pid_b, champ_b = side_b[0]
        if pid_a not in gold_by_pid or pid_b not in gold_by_pid:
            continue
        pairs.append(
            LanePair(
                match_id=match_id,
                lane=lane,
                champ_a=champ_a,
                champ_b=champ_b,
                gold_a=gold_by_pid[pid_a],
                gold_b=gold_by_pid[pid_b],
                pid_a=pid_a,
                pid_b=pid_b,
            )
        )
    return pairs


def extract_kill_counts(
    conn: sqlite3.Connection,
    match_id: str,
    pid_a: int,
    pid_b: int,
) -> Dict[str, Tuple[int, int]]:
    """Count CHAMPION_KILL events between two participants (the trade truth).

    Returns ``{"solo": (a_kills_b, b_kills_a), "any": (a_kills_b, b_kills_a)}``
    where ``solo`` counts only un-assisted kills (assisting_ids_json empty = a
    true 1v1 duel outcome) and ``any`` counts every direct A-on-B kill (includes
    gank-assisted, more samples but noisier). Fail-soft: a DB error or a
    malformed assists json -> the affected row is skipped, never raises.
    """
    try:
        rows = conn.execute(
            "SELECT killer_id, victim_id, assisting_ids_json FROM timeline_events "
            "WHERE match_id = ? AND event_type = 'CHAMPION_KILL' "
            "AND killer_id IN (?, ?) AND victim_id IN (?, ?)",
            (match_id, pid_a, pid_b, pid_a, pid_b),
        ).fetchall()
    except sqlite3.Error:
        return {"solo": (0, 0), "any": (0, 0)}

    a_b_any = b_a_any = a_b_solo = b_a_solo = 0
    for killer, victim, assists_json in rows:
        if killer is None or victim is None:
            continue
        try:
            killer = int(killer)
            victim = int(victim)
        except (TypeError, ValueError):
            continue
        is_a_on_b = killer == pid_a and victim == pid_b
        is_b_on_a = killer == pid_b and victim == pid_a
        if not (is_a_on_b or is_b_on_a):
            continue
        solo = _assists_empty(assists_json)
        if is_a_on_b:
            a_b_any += 1
            if solo:
                a_b_solo += 1
        else:
            b_a_any += 1
            if solo:
                b_a_solo += 1
    return {"solo": (a_b_solo, b_a_solo), "any": (a_b_any, b_a_any)}


def _assists_empty(assists_json: object) -> bool:
    """True when a CHAMPION_KILL had NO assisters (a true 1v1 solo kill).

    The column is a JSON array string; empty/absent/``[]`` means solo. Any parse
    trouble is treated as NOT solo (conservative - keeps a doubtful kill out of
    the clean solo bucket). Never raises.
    """
    if assists_json is None:
        return True
    s = str(assists_json).strip()
    if s in ("", "[]", "null"):
        return True
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, list) and len(parsed) == 0


# --------------------------------------------------------------------- engine scoring
def score_pair(
    pair: LanePair,
    level: int,
    snapshot: object,
    matchup_fn: Callable,
    even_band: float = _EVEN_BAND,
) -> Tuple[str, bool]:
    """Score one lane pair at one level against the gold ground truth.

    Returns ``(status, agreed)`` where status is one of:
      - "engine_none" : compute_matchup produced no usable net_swing (data gap)
      - "even"        : |net_swing| below the dead-band (engine calls it even)
      - "gold_tie"    : both participants had equal gold (no decisive truth)
      - "decisive"    : a real comparison was made; ``agreed`` is meaningful

    ``agreed`` is True only when status == "decisive" and the engine-favored
    champion matches the higher-gold champion. Fail-soft: any exception from the
    matchup engine maps to "engine_none".
    """
    try:
        result = matchup_fn(
            snapshot,
            pair.champ_a,
            pair.champ_b,
            level_a=level,
            level_b=level,
            mode="SR",
        )
    except Exception:  # noqa: BLE001
        return ("engine_none", False)

    if result is None:
        return ("engine_none", False)
    net_swing = getattr(result, "net_swing", None)
    if net_swing is None:
        return ("engine_none", False)
    try:
        net_swing = float(net_swing)
    except (TypeError, ValueError):
        return ("engine_none", False)

    if abs(net_swing) < even_band:
        return ("even", False)

    if pair.gold_a == pair.gold_b:
        return ("gold_tie", False)

    engine_favors_a = net_swing > 0.0
    gold_favors_a = pair.gold_a > pair.gold_b
    return ("decisive", engine_favors_a == gold_favors_a)


def score_pair_trade(
    pair: LanePair,
    level: int,
    snapshot: object,
    matchup_fn: Callable,
    a_kills_b: int,
    b_kills_a: int,
    even_band: float = _EVEN_BAND,
) -> Tuple[str, bool]:
    """Score one lane pair against the SOLO-KILL (duel) ground truth at one level.

    The engine half is identical to ``score_pair`` (favored = A when net_swing >
    0). The ground truth is the direct-kill differential between the two laners:
    the duel "winner" is whoever killed the other more. status:
      - "engine_none" : compute_matchup gave no usable net_swing
      - "even"        : |net_swing| below the dead-band
      - "no_duel"     : the pair never killed each other (no signal)
      - "kill_tie"    : equal kill counts (no decisive truth)
      - "decisive"    : a real comparison; ``agreed`` is meaningful

    This is a MORE-DIRECT proxy for the 1v1 trade the chip claims than lane gold,
    though still noisy (a "solo" kill can be a missed-assist gank, duels are
    sparse). Fail-soft: a matchup exception maps to "engine_none".
    """
    try:
        result = matchup_fn(
            snapshot, pair.champ_a, pair.champ_b,
            level_a=level, level_b=level, mode="SR",
        )
    except Exception:  # noqa: BLE001
        return ("engine_none", False)
    if result is None:
        return ("engine_none", False)
    net_swing = getattr(result, "net_swing", None)
    if net_swing is None:
        return ("engine_none", False)
    try:
        net_swing = float(net_swing)
    except (TypeError, ValueError):
        return ("engine_none", False)
    if abs(net_swing) < even_band:
        return ("even", False)

    if a_kills_b == 0 and b_kills_a == 0:
        return ("no_duel", False)
    if a_kills_b == b_kills_a:
        return ("kill_tie", False)

    engine_favors_a = net_swing > 0.0
    duel_favors_a = a_kills_b > b_kills_a
    return ("decisive", engine_favors_a == duel_favors_a)


# ----------------------------------------------------------------------- orchestration
def run_validation(
    db_path: Path,
    levels: Sequence[int],
    limit: int,
    gold_frame_min: int,
    snapshot: object,
    matchup_fn: Callable,
    even_band: float = _EVEN_BAND,
) -> dict:
    """Walk the SR replays, score every lane pair at each level, build the report."""
    conn = sqlite3.connect(str(db_path))
    try:
        match_ids = select_sr_match_ids(conn, limit)
        results: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}

        n_matches_used = 0
        n_matches_skipped = 0
        n_pairs_total = 0

        for mid in match_ids:
            try:
                pairs = extract_lane_pairs(conn, mid, gold_frame_min)
            except Exception:  # noqa: BLE001
                n_matches_skipped += 1
                continue
            if not pairs:
                n_matches_skipped += 1
                continue
            n_matches_used += 1
            n_pairs_total += len(pairs)
            for pair in pairs:
                for lvl in levels:
                    lr = results[lvl]
                    status, agreed = score_pair(pair, lvl, snapshot, matchup_fn, even_band)
                    if status == "engine_none":
                        lr.n_engine_none += 1
                    elif status == "even":
                        lr.n_even += 1
                    elif status == "gold_tie":
                        lr.n_gold_tie += 1
                    else:  # decisive
                        lr.record(pair.lane, agreed)
    finally:
        conn.close()

    report = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "db": str(db_path),
        "game_mode": _SR_GAME_MODE,
        "gold_frame_min": gold_frame_min,
        "even_band": even_band,
        "limit": limit,
        "matches_selected": len(match_ids),
        "matches_used": n_matches_used,
        "matches_skipped": n_matches_skipped,
        "pairs_total": n_pairs_total,
        "levels": [results[lvl].to_dict() for lvl in levels],
        "interpretation": (
            "agreement ~0.50 = coin-flip / no signal (do NOT flip coaches off "
            "Haiku); agreement meaningfully >0.50 (e.g. >=0.55 with large n) = the "
            "engine carries real predictive signal vs the lane-gold proxy and is a "
            "defensible deterministic substitute for the LLM trade judgment. Gold "
            "at the chosen frame is a noisy proxy (ganks/jungle/roams), so this is "
            "an honest lower-fidelity signal, not a pure 1v1 oracle."
        ),
    }
    return report


def run_trade_validation(
    db_path: Path,
    levels: Sequence[int],
    limit: int,
    gold_frame_min: int,
    snapshot: object,
    matchup_fn: Callable,
    even_band: float = _EVEN_BAND,
) -> dict:
    """Score the engine against the SOLO-KILL duel ground truth (the trade chip).

    Reuses the same SR-match selection + lane pairing as the gold path, but the
    truth is the direct-kill differential from ``timeline_events``. Produces TWO
    parallel scorings per level: ``solo`` (un-assisted kills, the cleanest 1v1
    signal) and ``any`` (all direct kills, more samples / noisier). The pairing
    still needs the gold frame only to resolve the participant ids cleanly.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        match_ids = select_sr_match_ids(conn, limit)
        solo: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}
        anyk: Dict[int, LevelResult] = {lvl: LevelResult(level=lvl) for lvl in levels}

        n_matches_used = 0
        n_matches_skipped = 0
        n_pairs_total = 0
        n_pairs_with_solo_duel = 0
        n_pairs_with_any_duel = 0

        for mid in match_ids:
            try:
                pairs = extract_lane_pairs(conn, mid, gold_frame_min)
            except Exception:  # noqa: BLE001
                n_matches_skipped += 1
                continue
            if not pairs:
                n_matches_skipped += 1
                continue
            n_matches_used += 1
            n_pairs_total += len(pairs)
            for pair in pairs:
                try:
                    kc = extract_kill_counts(conn, mid, pair.pid_a, pair.pid_b)
                except Exception:  # noqa: BLE001
                    kc = {"solo": (0, 0), "any": (0, 0)}
                a_solo, b_solo = kc["solo"]
                a_any, b_any = kc["any"]
                if a_solo or b_solo:
                    n_pairs_with_solo_duel += 1
                if a_any or b_any:
                    n_pairs_with_any_duel += 1
                for lvl in levels:
                    _accumulate_trade(solo[lvl], pair, lvl, snapshot, matchup_fn,
                                      a_solo, b_solo, even_band)
                    _accumulate_trade(anyk[lvl], pair, lvl, snapshot, matchup_fn,
                                      a_any, b_any, even_band)
    finally:
        conn.close()

    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "db": str(db_path),
        "game_mode": _SR_GAME_MODE,
        "ground_truth": "solo_kill_duel",
        "even_band": even_band,
        "limit": limit,
        "matches_selected": len(match_ids),
        "matches_used": n_matches_used,
        "matches_skipped": n_matches_skipped,
        "pairs_total": n_pairs_total,
        "pairs_with_solo_duel": n_pairs_with_solo_duel,
        "pairs_with_any_duel": n_pairs_with_any_duel,
        "levels_solo": [solo[lvl].to_dict() for lvl in levels],
        "levels_any": [anyk[lvl].to_dict() for lvl in levels],
        "interpretation": (
            "Ground truth = direct-kill differential between the two laners (who "
            "killed whom). 'solo' counts only un-assisted kills (cleanest 1v1); "
            "'any' counts all direct kills (more samples, gank noise). agreement "
            ">0.50 here means the engine predicts the actual DUEL outcome (the "
            "question the trade chip claims to answer), which gold-at-10min does "
            "not directly test. Duels are sparse + a 'solo' kill can be a "
            "missed-assist gank, so still treat as a noisy proxy, not an oracle."
        ),
    }


def _accumulate_trade(lr: LevelResult, pair: LanePair, level: int, snapshot,
                      matchup_fn: Callable, a_kills_b: int, b_kills_a: int,
                      even_band: float) -> None:
    """Score one (pair, level) into a trade LevelResult bucket."""
    status, agreed = score_pair_trade(
        pair, level, snapshot, matchup_fn, a_kills_b, b_kills_a, even_band)
    if status == "engine_none":
        lr.n_engine_none += 1
    elif status == "even":
        lr.n_even += 1
    elif status == "no_duel":
        lr.n_no_duel += 1
    elif status == "kill_tie":
        lr.n_kill_tie += 1
    else:
        lr.record(pair.lane, agreed)


def _fmt_pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_summary(report: dict) -> None:
    """Concise human-readable summary table on stdout (ASCII only)."""
    print("")
    print("=== Replay matchup validation (Haiku-flip gate) ===")
    print(
        f"db={report['db']}  mode={report['game_mode']}  "
        f"gold_frame={report['gold_frame_min']}min  even_band={report['even_band']}"
    )
    print(
        f"matches: selected={report['matches_selected']} used={report['matches_used']} "
        f"skipped={report['matches_skipped']}  pairs={report['pairs_total']}"
    )
    print("")
    print(f"{'level':>5}  {'n':>6}  {'agree':>6}  {'95% Wilson':>16}  excluded(even/tie/none)")
    print("-" * 72)
    for lv in report["levels"]:
        exc = lv["excluded"]
        ci = ""
        if lv["wilson_95_lo"] is not None:
            ci = f"[{lv['wilson_95_lo'] * 100:4.1f}, {lv['wilson_95_hi'] * 100:4.1f}]"
        print(
            f"{lv['level']:>5}  {lv['n_decisive']:>6}  {_fmt_pct(lv['agreement'])}  "
            f"{ci:>16}  {exc['even_band']}/{exc['gold_tie']}/{exc['engine_none']}"
        )
    # Per-role breakdown for each level.
    for lv in report["levels"]:
        if not lv["per_role"]:
            continue
        print("")
        print(f"  level {lv['level']} per-role:")
        for role, slot in lv["per_role"].items():
            print(f"    {role:<8} n={slot['n']:>4}  agree={_fmt_pct(slot['agreement'])}")
    print("")
    print("interpretation:")
    print("  " + report["interpretation"])
    print("")


def print_trade_summary(report: dict) -> None:
    """Concise human-readable summary for the solo-kill trade report (ASCII)."""
    print("")
    print("=== Replay matchup validation - SOLO-KILL TRADE ground truth ===")
    print(
        f"db={report['db']}  mode={report['game_mode']}  even_band={report['even_band']}"
    )
    print(
        f"matches: selected={report['matches_selected']} used={report['matches_used']} "
        f"skipped={report['matches_skipped']}  pairs={report['pairs_total']}  "
        f"pairs_with_duel solo={report['pairs_with_solo_duel']} any={report['pairs_with_any_duel']}"
    )
    for label, key in (("SOLO (1v1)", "levels_solo"), ("ANY (incl gank)", "levels_any")):
        print("")
        print(f"  -- {label} --")
        print(f"  {'level':>5}  {'n':>6}  {'agree':>6}  {'95% Wilson':>16}")
        print("  " + "-" * 44)
        for lv in report[key]:
            ci = ""
            if lv["wilson_95_lo"] is not None:
                ci = f"[{lv['wilson_95_lo'] * 100:4.1f}, {lv['wilson_95_hi'] * 100:4.1f}]"
            print(
                f"  {lv['level']:>5}  {lv['n_decisive']:>6}  {_fmt_pct(lv['agreement'])}  "
                f"{ci:>16}"
            )
    print("")
    print("interpretation:")
    print("  " + report["interpretation"])
    print("")


# ----------------------------------------------------------------------------- loaders
def _load_snapshot():
    """Load the DS DataSnapshot once (in-process). Imported lazily so the unit
    tests, which stub the engine, never need the real data files."""
    from agents.daemon_slayer.data_loader import DataSnapshot

    return DataSnapshot.load()


def _load_matchup_fn() -> Callable:
    from agents.daemon_slayer.matchup import compute_matchup

    return compute_matchup


def _write_report(report: dict, out_path: Path) -> None:
    """Atomic JSON write of the gate artifact (ASCII-only)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(str(tmp), str(out_path))


def _parse_levels(raw: str) -> List[int]:
    out: List[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        out.append(int(chunk))
    return out or list(_DEFAULT_LEVELS)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay-validate the DS matchup engine (Haiku-flip gate).")
    ap.add_argument("--db", default=str(_DEFAULT_DB), help="Path to rewind_history.db")
    ap.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help="Max SR matches to replay (0 = all). Default %(default)s.",
    )
    ap.add_argument(
        "--levels",
        default=",".join(str(x) for x in _DEFAULT_LEVELS),
        help="Comma-separated replay levels. Default %(default)s.",
    )
    ap.add_argument(
        "--gold-frame",
        type=int,
        default=_DEFAULT_GOLD_FRAME_MIN,
        help="Minute of the timeline frame used as lane-gold ground truth. Default %(default)s.",
    )
    ap.add_argument("--out", default=str(_DEFAULT_OUT), help="Output JSON gate artifact path.")
    ap.add_argument(
        "--ground-truth",
        choices=("gold", "trade", "both"),
        default="both",
        help="Which ground truth(s) to score against: lane gold at the frame, "
             "the solo-kill duel differential, or both. Default %(default)s.",
    )
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2

    levels = _parse_levels(args.levels)

    print("Loading DS snapshot (in-process)...", file=sys.stderr)
    snapshot = _load_snapshot()
    matchup_fn = _load_matchup_fn()

    gold_report = None
    trade_report = None
    if args.ground_truth in ("gold", "both"):
        gold_report = run_validation(
            db_path=db_path, levels=levels, limit=args.limit,
            gold_frame_min=args.gold_frame, snapshot=snapshot, matchup_fn=matchup_fn,
        )
    if args.ground_truth in ("trade", "both"):
        trade_report = run_trade_validation(
            db_path=db_path, levels=levels, limit=args.limit,
            gold_frame_min=args.gold_frame, snapshot=snapshot, matchup_fn=matchup_fn,
        )

    # The on-disk artifact: a single-mode report keeps the legacy top-level shape;
    # 'both' nests them under gold/trade with a thin envelope.
    if gold_report is not None and trade_report is not None:
        out_report = {
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "ground_truth": "both",
            "gold": gold_report,
            "trade": trade_report,
        }
    else:
        out_report = gold_report if gold_report is not None else trade_report

    out_path = Path(args.out)
    _write_report(out_report, out_path)
    if gold_report is not None:
        print_summary(gold_report)
    if trade_report is not None:
        print_trade_summary(trade_report)
    print(f"gate artifact written: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
