"""tools/replay_pickban_validate.py - counter-quality GATE for the pickban DB.

Replay-validation harness for the de-biased pick/ban targets DB
(``data/daemon_slayer/<patch>/pickban_targets.json``). It REPORTS one number:
how often the DB's claimed favorite in a lane head-to-head actually came out
ahead in the real game. That number is the gate that decides whether the
pickban DB is a trustworthy enough counter source to drive champ-select pick/ban
suggestions (the flip itself is an operator product-direction call - this
harness only produces the verdict, never flips anything).

How it works
------------
1. Select Summoner's Rift / Classic matches from the local ``rewind_history.db``
   (game_mode='CLASSIC'). Limit with ``--limit N`` (0 = all).
2. Per match, pair same-lane opponents across the two teams by ``team_position``
   (team 100 = side A, team 200 = side B). Champion names in both the DB and the
   replay use the DDragon-KEY form (Khazix / Velkoz), so they match directly.
3. For each pair (A vs B) read the DB CLAIM: B in A.counters -> B favored; B in
   A.good_against -> A favored; symmetrically A in B.counters / B.good_against.
   Agreeing claims collapse to one; conflicting claims (top_k truncation can
   list a pair on only one side) are excluded. No claim -> excluded.
4. GROUND TRUTH (a proxy, honestly lower-fidelity): the lane "winner" is the
   participant with higher ``total_gold`` at the ~10-minute frame (gold mode),
   and/or whoever solo-killed the other more from ``timeline_events`` (trade
   mode). Both are noisy (ganks / roams / jungle), so treat the number as a
   lower-bound signal, not an oracle.
5. AGREEMENT = (pairs where DB-favored champ == real winner) / (decisive pairs),
   with n, exclusion counts, and a 95% Wilson interval. GATE: Wilson lower bound
   > 0.50 = the DB carries signal beyond a coin-flip (the flip is then defensible
   as a FUTURE operator call); CI bracketing 0.50 = coin-flip (do NOT flip; keep
   the DB a secondary hint, mirroring the matchup-engine W3B finding).

Output: a JSON gate artifact at ``ops/runtime/pickban_validation.json`` (gitignored
runtime artifact; override with ``--out``) + a concise stdout summary.

Fail-soft: a malformed match / pair / claim never aborts the run - it is skipped
and counted. ASCII-only by hard rule. No network, no LLM, stdlib + sqlite3 only.

REAL-DB VERDICT (2026-06-02, --limit 0 over rewind_history.db, 614 matches /
3064 pairs): NO_SIGNAL. gold ground truth n=416 agreement 46.9% Wilson
[42.1, 51.7]; solo-kill-duel n=184 agreement 48.4% Wilson [41.3, 55.5]. Both
CIs bracket 0.50 = a coin-flip. This mirrors the matchup-engine W3B finding -
the pickban DB is derived from the same compute_matchup engine, so it inherits
the coin-flip. CONCLUSION: do NOT flip champ-select pick/ban onto this DB; it
stays a SECONDARY hint. (2646/3064 pairs were no_claim - the top_k DB only
opines on a small fraction of random lane matchups, which is expected.)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
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
from typing import Dict, List, Optional, Sequence, Tuple

_THIS = Path(__file__).resolve()
_ROOT = _THIS.parent.parent
_DEFAULT_DB = _ROOT / "data" / "rewind_history.db"
_DEFAULT_OUT = _ROOT / "ops" / "runtime" / "pickban_validation.json"
_DS_DATA = _ROOT / "data" / "daemon_slayer"
_DEFAULT_LIMIT = 0  # 0 = all SR matches
_DEFAULT_GOLD_FRAME_MIN = 10
_LANES = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
_SR_GAME_MODE = "CLASSIC"
# Gate threshold: a Wilson lower bound above this clears the coin-flip bar.
_GATE_LO = 0.50


@dataclass
class LanePair:
    match_id: str
    lane: str
    champ_a: str
    champ_b: str
    gold_a: float = 0.0
    gold_b: float = 0.0
    pid_a: int = 0
    pid_b: int = 0


@dataclass
class ScoreBucket:
    label: str
    n_decisive: int = 0
    n_agree: int = 0
    n_no_claim: int = 0
    n_conflict: int = 0
    n_tie: int = 0  # equal ground truth (gold tie / kill tie) - excluded
    n_no_duel: int = 0  # trade mode: pair never killed each other
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
        return (self.n_agree / self.n_decisive) if self.n_decisive else None

    def to_dict(self) -> dict:
        lo, hi = wilson_interval(self.n_agree, self.n_decisive)
        per_role = {}
        for role, slot in sorted(self.per_role.items()):
            n = slot["n"]
            per_role[role] = {
                "n": n,
                "agree": slot["agree"],
                "agreement": (slot["agree"] / n) if n else None,
            }
        return {
            "label": self.label,
            "n_decisive": self.n_decisive,
            "n_agree": self.n_agree,
            "agreement": self.agreement,
            "wilson_95_lo": lo,
            "wilson_95_hi": hi,
            "gate_clears_coinflip": (lo is not None and lo > _GATE_LO),
            "excluded": {
                "no_claim": self.n_no_claim,
                "conflict": self.n_conflict,
                "tie": self.n_tie,
                "no_duel": self.n_no_duel,
            },
            "per_role": per_role,
        }


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    """95% Wilson score interval for a binomial proportion. None if n == 0."""
    if n <= 0:
        return (None, None)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return (max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom))


def _current_patch() -> str:
    try:
        return (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load_targets(path: Optional[Path] = None) -> Dict[str, Dict[str, set]]:
    """champ -> {'counters': {names}, 'good_against': {names}}; {} fail-soft."""
    if path is None:
        patch = _current_patch()
        if not patch:
            return {}
        path = _DS_DATA / patch / "pickban_targets.json"
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    targets = raw.get("targets") if isinstance(raw, dict) else None
    if not isinstance(targets, dict):
        return {}
    out: Dict[str, Dict[str, set]] = {}
    for champ, entry in targets.items():
        if not isinstance(entry, dict):
            continue
        c = {str(e.get("champion")) for e in entry.get("counters", []) if isinstance(e, dict) and e.get("champion")}
        g = {str(e.get("champion")) for e in entry.get("good_against", []) if isinstance(e, dict) and e.get("champion")}
        out[str(champ)] = {"counters": c, "good_against": g}
    return out


def db_claim(targets: Dict[str, Dict[str, set]], a: str, b: str) -> Optional[str]:
    """Return 'A' or 'B' (the DB-favored side) for the lane pair, or None.

    Collects every claim the DB makes about this unordered pair from both
    champions' lists; agreeing claims collapse to one, conflicting claims
    (possible under top_k truncation) -> None (excluded), no claim -> None.
    """
    votes: set = set()
    ta = targets.get(a, {})
    tb = targets.get(b, {})
    if b in ta.get("counters", set()):
        votes.add("B")
    if b in ta.get("good_against", set()):
        votes.add("A")
    if a in tb.get("counters", set()):
        votes.add("A")
    if a in tb.get("good_against", set()):
        votes.add("B")
    if len(votes) == 1:
        return next(iter(votes))
    return None


def select_sr_match_ids(conn: sqlite3.Connection, limit: int) -> List[str]:
    sql = (
        "SELECT match_id FROM matches WHERE game_mode = ? AND has_timeline = 1 "
        "ORDER BY game_creation_ts DESC"
    )
    try:
        rows = conn.execute(sql, (_SR_GAME_MODE,)).fetchall()
    except sqlite3.Error:
        return []
    ids = [r[0] for r in rows if r and r[0]]
    return ids[:limit] if (limit and limit > 0) else ids


def _nearest_frame_ts(conn: sqlite3.Connection, match_id: str, target_ms: int) -> Optional[int]:
    try:
        rows = conn.execute(
            "SELECT DISTINCT timestamp_ms FROM timeline_frames WHERE match_id = ?",
            (match_id,),
        ).fetchall()
    except sqlite3.Error:
        return None
    stamps = [r[0] for r in rows if r and r[0] is not None]
    return min(stamps, key=lambda t: abs(t - target_ms)) if stamps else None


def extract_lane_pairs(conn: sqlite3.Connection, match_id: str, gold_frame_min: int) -> List[LanePair]:
    try:
        prows = conn.execute(
            "SELECT participant_id, team_id, champion_name, team_position "
            "FROM participants WHERE match_id = ?",
            (match_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    by_lane: Dict[str, Dict[int, Tuple[str, str]]] = {}
    for pid, team_id, champ, pos in prows:
        if pid is None or not champ or not pos:
            continue
        lane = str(pos).upper()
        if lane not in _LANES:
            continue
        side = "B" if (team_id == 200 or (team_id != 100 and int(pid) > 5)) else "A"
        by_lane.setdefault(lane, {})[int(pid)] = (champ, side)

    frame_ts = _nearest_frame_ts(conn, match_id, gold_frame_min * 60 * 1000)
    gold_by_pid: Dict[int, float] = {}
    if frame_ts is not None:
        try:
            grows = conn.execute(
                "SELECT participant_id, total_gold FROM timeline_frames "
                "WHERE match_id = ? AND timestamp_ms = ?",
                (match_id, frame_ts),
            ).fetchall()
            for pid, gold in grows:
                if pid is not None and gold is not None:
                    gold_by_pid[int(pid)] = float(gold)
        except sqlite3.Error:
            pass

    pairs: List[LanePair] = []
    for lane, members in by_lane.items():
        side_a = [(pid, c) for pid, (c, s) in members.items() if s == "A"]
        side_b = [(pid, c) for pid, (c, s) in members.items() if s == "B"]
        if len(side_a) != 1 or len(side_b) != 1:
            continue
        pid_a, champ_a = side_a[0]
        pid_b, champ_b = side_b[0]
        pairs.append(LanePair(
            match_id=match_id, lane=lane, champ_a=champ_a, champ_b=champ_b,
            gold_a=gold_by_pid.get(pid_a, 0.0), gold_b=gold_by_pid.get(pid_b, 0.0),
            pid_a=pid_a, pid_b=pid_b,
        ))
    return pairs


def _assists_empty(assists_json: object) -> bool:
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


def extract_kill_counts(conn: sqlite3.Connection, match_id: str, pid_a: int, pid_b: int) -> Tuple[int, int]:
    """Return (a_solo_kills_b, b_solo_kills_a) un-assisted (the duel truth)."""
    try:
        rows = conn.execute(
            "SELECT killer_id, victim_id, assisting_ids_json FROM timeline_events "
            "WHERE match_id = ? AND event_type = 'CHAMPION_KILL' "
            "AND killer_id IN (?, ?) AND victim_id IN (?, ?)",
            (match_id, pid_a, pid_b, pid_a, pid_b),
        ).fetchall()
    except sqlite3.Error:
        return (0, 0)
    a_b = b_a = 0
    for killer, victim, assists in rows:
        if killer is None or victim is None:
            continue
        try:
            killer, victim = int(killer), int(victim)
        except (TypeError, ValueError):
            continue
        if not _assists_empty(assists):
            continue
        if killer == pid_a and victim == pid_b:
            a_b += 1
        elif killer == pid_b and victim == pid_a:
            b_a += 1
    return (a_b, b_a)


def score_gold(pair: LanePair, claim: Optional[str]) -> Tuple[str, bool]:
    if claim is None:
        return ("no_claim", False)
    if pair.gold_a == pair.gold_b:
        return ("tie", False)
    real = "A" if pair.gold_a > pair.gold_b else "B"
    return ("decisive", claim == real)


def score_trade(pair: LanePair, claim: Optional[str], a_kills_b: int, b_kills_a: int) -> Tuple[str, bool]:
    if claim is None:
        return ("no_claim", False)
    if a_kills_b == 0 and b_kills_a == 0:
        return ("no_duel", False)
    if a_kills_b == b_kills_a:
        return ("tie", False)
    real = "A" if a_kills_b > b_kills_a else "B"
    return ("decisive", claim == real)


def _apply(bucket: ScoreBucket, pair: LanePair, status: str, agreed: bool) -> None:
    if status == "no_claim":
        bucket.n_no_claim += 1
    elif status == "conflict":
        bucket.n_conflict += 1
    elif status == "tie":
        bucket.n_tie += 1
    elif status == "no_duel":
        bucket.n_no_duel += 1
    else:
        bucket.record(pair.lane, agreed)


def run_validation(db_path: Path, targets: Dict[str, Dict[str, set]], limit: int,
                   gold_frame_min: int, ground_truth: str) -> dict:
    conn = sqlite3.connect(str(db_path))
    gold = ScoreBucket(label="gold_at_frame")
    trade = ScoreBucket(label="solo_kill_duel")
    n_used = n_skipped = n_pairs = 0
    try:
        for mid in select_sr_match_ids(conn, limit):
            try:
                pairs = extract_lane_pairs(conn, mid, gold_frame_min)
            except Exception:
                n_skipped += 1
                continue
            if not pairs:
                n_skipped += 1
                continue
            n_used += 1
            n_pairs += len(pairs)
            for pair in pairs:
                claim = db_claim(targets, pair.champ_a, pair.champ_b)
                if ground_truth in ("gold", "both"):
                    st, ag = score_gold(pair, claim)
                    _apply(gold, pair, st, ag)
                if ground_truth in ("trade", "both"):
                    a_b, b_a = extract_kill_counts(conn, mid, pair.pid_a, pair.pid_b)
                    st, ag = score_trade(pair, claim, a_b, b_a)
                    _apply(trade, pair, st, ag)
    finally:
        conn.close()

    buckets = {}
    if ground_truth in ("gold", "both"):
        buckets["gold"] = gold.to_dict()
    if ground_truth in ("trade", "both"):
        buckets["trade"] = trade.to_dict()

    verdict = _verdict(buckets)
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "db": str(db_path),
        "game_mode": _SR_GAME_MODE,
        "gold_frame_min": gold_frame_min,
        "limit": limit,
        "matches_used": n_used,
        "matches_skipped": n_skipped,
        "pairs_total": n_pairs,
        "gate_threshold_lo": _GATE_LO,
        "verdict": verdict,
        "buckets": buckets,
        "interpretation": (
            "agreement ~0.50 = the pickban DB is a coin-flip vs real lane outcomes "
            "(keep it a secondary hint, do NOT flip champ-select pick/ban onto it); "
            "Wilson lower bound > 0.50 = real counter signal (the flip is then a "
            "defensible FUTURE operator product call). Gold-at-frame + solo-kill are "
            "noisy proxies (ganks/roams), so this is a lower-fidelity gate."
        ),
    }


def _verdict(buckets: dict) -> str:
    """signal if any bucket clears the coin-flip gate, else no_signal/insufficient."""
    decisive = any(b.get("n_decisive", 0) > 0 for b in buckets.values())
    if not decisive:
        return "insufficient_data"
    if any(b.get("gate_clears_coinflip") for b in buckets.values()):
        return "signal"
    return "no_signal"


def _write_report(report: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    os.replace(str(tmp), str(out_path))


def _fmt_pct(x: Optional[float]) -> str:
    return "  n/a" if x is None else f"{x * 100:5.1f}%"


def print_summary(report: dict) -> None:
    print("")
    print("=== Replay pickban-DB counter-quality gate ===")
    print(f"db={report['db']}  verdict={report['verdict']}  "
          f"matches_used={report['matches_used']}  pairs={report['pairs_total']}")
    for key, b in report["buckets"].items():
        ci = ""
        if b["wilson_95_lo"] is not None:
            ci = f"[{b['wilson_95_lo'] * 100:4.1f}, {b['wilson_95_hi'] * 100:4.1f}]"
        print(f"  {key:>6}: n={b['n_decisive']:>5}  agree={_fmt_pct(b['agreement'])}  "
              f"95%Wilson={ci:>16}  clears_coinflip={b['gate_clears_coinflip']}")
        exc = b["excluded"]
        print(f"          excluded no_claim={exc['no_claim']} conflict={exc['conflict']} "
              f"tie={exc['tie']} no_duel={exc['no_duel']}")
    print("")
    print("interpretation:")
    print("  " + report["interpretation"])
    print("")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay-validate the pickban-targets DB (counter-quality gate).")
    ap.add_argument("--db", default=str(_DEFAULT_DB))
    ap.add_argument("--limit", type=int, default=_DEFAULT_LIMIT, help="Max SR matches (0=all). Default %(default)s.")
    ap.add_argument("--gold-frame", type=int, default=_DEFAULT_GOLD_FRAME_MIN)
    ap.add_argument("--out", default=str(_DEFAULT_OUT))
    ap.add_argument("--targets", default=None, help="Override pickban_targets.json path.")
    ap.add_argument("--ground-truth", choices=("gold", "trade", "both"), default="both")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: db not found: {db_path}", file=sys.stderr)
        return 2
    targets = load_targets(Path(args.targets) if args.targets else None)
    if not targets:
        print("ERROR: pickban targets empty / not found", file=sys.stderr)
        return 2

    report = run_validation(db_path, targets, args.limit, args.gold_frame, args.ground_truth)
    _write_report(report, Path(args.out))
    print_summary(report)
    print(f"gate artifact written: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
