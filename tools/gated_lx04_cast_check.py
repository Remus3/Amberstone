"""gated_lx04_cast_check.py - replay one LX-03 recording through the self cast log for LX-04.

LX-04 (RM-606) asks whether ``core.self_cast_log.detect_from_frames``, run over
the frames of a REAL recorded session (LX-03, ``logs/sessions/<gameId>.jsonl``),
gives per-slot cast totals within tolerance of the Match-V5 ``spell1Casts`` ..
``spell4Casts`` truth for the same game, and asks for the module's postulated
constants (FALL_THRESHOLD, GAP_S, the partial-cost tolerance, the validator
tolerance) to be re-measured on real data. Doing that by hand means re-deriving
the champion, the cost table, the poll cadence and the truth row every pass;
this tool prints it in ONE command.

It is READ-ONLY: it reads the session through the recorder's own reader
(``core.live_session_recorder.read_session``), runs the module's own detector
and validator, and, with ``--truth-db``, opens ``data/rewind_history.db`` in
sqlite ``mode=ro``. It never writes, moves, locks or deletes anything, and it
never ticks a row - its output is the INPUT to the four-part evidence contract
in ``docs/LIVE_GAME_GATED_SYNC.md``, never the evidence itself. A hand-built
session and a hand-built truth row pass these checks just as well; that is the
substitution the LX-04 row names.

WHAT IT REPORTS:
  - frames, readings the detector could parse, the resource types seen, the
    active champion(s) and the DS cost table used (resource + per-rank costs
    per slot, and whether each slot is observable from the resource bar).
  - the events: count, per-slot totals, counts per confidence tier, gap events
    (span set), and the unattributed events (slot_guess None) with a cost
    summary - per-second drains and toggles are expected to land there.
  - re-measure inputs: the game-time step between readings (median / p95 /
    max, how many exceed GAP_S), the falls between readings that stayed under
    FALL_THRESHOLD, and, for every non-gap attributed event, its shortfall
    under the matched cost against ``partial_tolerance``.
  - truth: with ``--truth-db`` the match whose id ends in ``_<stem>`` (the
    stem is the LCU game id LX-03 writes) and its ONE participant on the
    session's champion; with ``--truth-json`` a saved Match-V5 participant
    object. Then ``validate_against_match_v5`` per slot and a verdict.

NO ID IS EVER PRINTED (RM-906): not the stem, not the match id, not a player
name. Champion names, queue ids, counts and costs are printed.

USAGE
    python tools/gated_lx04_cast_check.py logs/sessions/<file>.jsonl
    python tools/gated_lx04_cast_check.py <file> --truth-db data/rewind_history.db --json
    python tools/gated_lx04_cast_check.py <file> --truth-json <participant.json>

Exit 2 = not a file or not a readable session (bad header, newer schema), or a
``--truth-json`` that is not a readable JSON object.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import self_cast_log as scl  # noqa: E402
from core.live_session_recorder import SessionFormatError, read_session  # noqa: E402

NOGAMEID_PREFIX = "nogameid-"
VERDICTS = ("PASS", "FAIL", "NO_TRUTH", "NO_COSTS", "NOT_OBSERVABLE",
            "NO_READINGS", "CHAMPION_UNKNOWN")
TRUTH_STATUSES = ("none", "ok", "nogameid_stem", "no_match_row",
                  "champion_not_unique", "db_error", "json_not_participant")


def canonical(name: Any) -> str:
    """DDragon id for a Live Client display name or a Match-V5 championName."""
    if not isinstance(name, str) or not name.strip():
        return ""
    try:
        from core.archetype_picks import canonical_champion_id
        return canonical_champion_id(name.strip()) or name.strip()
    except Exception:  # noqa: BLE001
        return name.strip()


def _pct(sorted_vals: List[float], q: float) -> Optional[float]:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, math.ceil(q * len(sorted_vals)) - 1))
    return round(sorted_vals[idx], 3)


def _summary(vals: List[float]) -> Dict[str, Any]:
    s = sorted(vals)
    return {"n": len(s), "min": round(s[0], 3) if s else None,
            "median": _pct(s, 0.5), "p95": _pct(s, 0.95),
            "max": round(s[-1], 3) if s else None}


def _readings(snaps: List[Any]) -> List[scl.Reading]:
    out = []
    for snap in snaps:
        r = scl.reading_from_allgamedata(snap)
        if r is not None:
            out.append(r)
    return out


def cadence(readings: List[scl.Reading]) -> Dict[str, Any]:
    """Game-time steps between successive DISTINCT readings (the detector
    skips a repeated frame), and how many exceed GAP_S."""
    steps = [b.t - a.t for a, b in zip(readings, readings[1:]) if b.t > a.t]
    out = _summary(steps)
    out["over_gap_s"] = sum(1 for d in steps if d > scl.GAP_S)
    out["gap_s"] = scl.GAP_S
    return out


def sub_threshold_falls(readings: List[scl.Reading]) -> Dict[str, Any]:
    """Falls between successive readings with an unchanged resourceMax that
    stayed under FALL_THRESHOLD: the casts (or noise) the threshold hides."""
    falls = []
    for a, b in zip(readings, readings[1:]):
        if b.t <= a.t or a.rtype != b.rtype or a.maximum != b.maximum:
            continue
        f = a.value - b.value
        if 0.0 < f < scl.FALL_THRESHOLD:
            falls.append(f)
    out = _summary(falls)
    out["fall_threshold"] = scl.FALL_THRESHOLD
    return out


def shortfalls(events: List[Dict[str, Any]], readings: List[scl.Reading],
               costs: scl.CostTable) -> Dict[str, Any]:
    """For each attributed non-gap event, matched cost minus the observed
    fall, and that shortfall as a fraction of partial_tolerance(cost)."""
    by_t = {round(r.t, 3): r for r in readings}
    gaps, fracs, over = [], [], 0
    for e in events:
        if e.get("span") is not None or e.get("slot_guess") not in scl.SLOTS:
            continue
        r = by_t.get(e.get("t"))
        fall = scl._num(e.get("cost"))
        if r is None or fall is None:
            continue
        _s, cost, _c = scl.match_slot(fall, r.ranks, costs, r.rtype)
        if cost is None:
            continue
        short = cost - fall
        gaps.append(short)
        if short > 0:
            frac = short / scl.partial_tolerance(cost)
            fracs.append(frac)
            over += frac > 0.8
    out = _summary(gaps)
    out["frac_of_tolerance"] = _summary(fracs)
    out["near_edge"] = over  # shortfall above 80 percent of the tolerance
    out["partial_abs"] = scl.PARTIAL_ABS
    out["partial_rel"] = scl.PARTIAL_REL
    return out


def cost_view(costs: scl.CostTable) -> Dict[str, Any]:
    out = {}
    for slot in scl.SLOTS:
        entry = costs.get(slot)
        res, per = (entry if isinstance(entry, (tuple, list)) and len(entry) == 2
                    else (None, None))
        out[slot] = {"resource": res,
                     "costs": list(per) if isinstance(per, (tuple, list)) else None,
                     "observable": scl._observable(entry)}
    return out


def truth_from_db(db: Path, stem: str, cid: str) -> tuple[str, Optional[dict], Optional[dict]]:
    """(status, participant row, match facts) from rewind_history.db, read-only.
    The match is the one whose id ends in '_<stem>'; the participant is the ONE
    row on the session's champion."""
    if stem.startswith(NOGAMEID_PREFIX) or not stem.isdigit():
        return "nogameid_stem", None, None
    try:
        conn = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error:
        return "db_error", None, None
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT match_id, queue_id, game_mode, game_duration_s FROM matches",
        ).fetchall()
        hits = [r for r in rows
                if isinstance(r["match_id"], str)
                and r["match_id"].rsplit("_", 1)[-1] == stem]
        if len(hits) != 1:
            return "no_match_row", None, None
        m = hits[0]
        facts = {"queue_id": m["queue_id"], "game_mode": m["game_mode"],
                 "game_duration_s": m["game_duration_s"]}
        parts = conn.execute(
            "SELECT * FROM participants WHERE match_id = ?", (m["match_id"],),
        ).fetchall()
    except sqlite3.Error:
        return "db_error", None, None
    finally:
        conn.close()
    mine = [p for p in parts if canonical(p["champion_name"]) == cid]
    if len(mine) != 1:
        return "champion_not_unique", None, facts
    return "ok", dict(mine[0]), facts


def check(path: Path, truth_db: Optional[Path] = None,
          truth_participant: Optional[Mapping[str, Any]] = None,
          champion_id: Optional[str] = None,
          costs: Optional[scl.CostTable] = None,
          data_root: Optional[Path] = None) -> dict:
    """Summarise one session file. Raises SessionFormatError on a bad file."""
    header, frames = read_session(path)
    snaps = [f.get("snapshot") for f in frames if isinstance(f.get("snapshot"), dict)]
    readings = _readings(snaps)
    champs: List[str] = []
    for snap in snaps:
        c = scl.active_champion_name(snap)
        if c and c not in champs:
            champs.append(c)
    cid = champion_id or (canonical(champs[0]) if len(champs) == 1 else "")
    if costs is None:
        costs = scl.load_cost_table(cid, data_root) if cid else {}
    events = scl.detect_from_frames(snaps, costs)
    rtypes = Counter(r.rtype for r in readings)
    tracked = sum(n for t, n in rtypes.items() if scl.is_tracked_resource(t))
    unattr = [e for e in events if e.get("slot_guess") not in scl.SLOTS]

    out: dict = {
        "stem_kind": "nogameid" if path.stem.startswith(NOGAMEID_PREFIX) else "gameid",
        "mode_key": header.get("mode_key"),
        "patch": header.get("patch"),
        "frames": len(frames),
        "readings": len(readings),
        "game_time_last": round(readings[-1].t, 3) if readings else None,
        "resource_types": dict(sorted(rtypes.items())),
        "tracked_readings": tracked,
        "champions": champs,
        "champion_id": cid or None,
        "costs": cost_view(costs),
        "events": len(events),
        "totals": scl.per_slot_totals(events),
        "by_confidence": {str(k): v for k, v in
                          sorted(Counter(e.get("confidence") for e in events).items(),
                                 key=lambda kv: -(kv[0] or 0))},
        "gap_events": sum(1 for e in events if e.get("span") is not None),
        "unattributed_costs": _summary([e["cost"] for e in unattr
                                        if scl._num(e.get("cost")) is not None]),
        "unattributed_top": [[c, n] for c, n in Counter(
            round(e["cost"]) for e in unattr
            if scl._num(e.get("cost")) is not None).most_common(5)],
        "cadence": cadence(readings),
        "sub_threshold": sub_threshold_falls(readings),
        "shortfall": shortfalls(events, readings, costs),
        "match_abs_tol": scl.MATCH_ABS_TOL,
        "match_rel_tol": scl.MATCH_REL_TOL,
    }

    status, row, facts = "none", None, None
    if truth_participant is not None:
        row = dict(truth_participant)
        has = any(scl._count(row.get(k), 10 ** 5) is not None
                  for keys in scl._TRUTH_KEYS.values() for k in keys)
        status = "ok" if has else "json_not_participant"
        if not has:
            row = None
    elif truth_db is not None:
        status, row, facts = truth_from_db(Path(truth_db), path.stem, cid)
    out["truth_status"] = status
    out["truth_match"] = facts
    if row is not None:
        v = scl.validate_against_match_v5(events, row, costs)
        for s in v["slots"].values():
            s["rel_diff"] = (round(s["diff"] / s["truth"], 3)
                             if s["compared"] and s["truth"] else None)
        out["validation"] = v
    else:
        out["validation"] = None

    if not readings:
        verdict = "NO_READINGS"
    elif not tracked:
        verdict = "NOT_OBSERVABLE"
    elif not cid:
        verdict = "CHAMPION_UNKNOWN"
    elif not any(c["observable"] for c in out["costs"].values()):
        verdict = "NO_COSTS"
    elif out["validation"] is None:
        verdict = "NO_TRUTH"
    else:
        verdict = "PASS" if out["validation"]["pass"] else "FAIL"
    out["verdict"] = verdict
    return out


def render(s: dict) -> str:
    """Human-readable text summary (no id of any kind)."""
    lines = [
        f"verdict={s['verdict']} stem_kind={s['stem_kind']} mode_key={s['mode_key']} "
        f"patch={s['patch']} frames={s['frames']} readings={s['readings']} "
        f"game_time_last={s['game_time_last']}",
        f"champions={s['champions']} champion_id={s['champion_id']} "
        f"resource_types={s['resource_types']}",
        "costs " + " ".join(
            f"{k}={v['resource']}:{v['costs']}:{'obs' if v['observable'] else 'no'}"
            for k, v in s["costs"].items()),
        f"events={s['events']} totals={s['totals']} gap_events={s['gap_events']} "
        f"by_confidence={s['by_confidence']}",
        f"unattributed_costs={s['unattributed_costs']} top={s['unattributed_top']}",
        f"cadence={s['cadence']}",
        f"sub_threshold={s['sub_threshold']}",
        f"shortfall={s['shortfall']}",
        f"truth_status={s['truth_status']} truth_match={s['truth_match']}",
    ]
    v = s.get("validation")
    if v:
        for slot, d in v["slots"].items():
            lines.append(f"  {slot} log={d['log']} truth={d['truth']} diff={d['diff']} "
                         f"allowed={d['allowed']} within={d['within']} "
                         f"compared={d['compared']} rel_diff={d['rel_diff']}")
        lines.append(f"  pass={v['pass']} unattributed={v['unattributed']}")
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="read-only LX-04 replay of one session through the self cast log")
    ap.add_argument("session", help="logs/sessions/<gameId>.jsonl (an LX-03 recording)")
    t = ap.add_mutually_exclusive_group()
    t.add_argument("--truth-db", default=None,
                   help="data/rewind_history.db (opened read-only)")
    t.add_argument("--truth-json", default=None,
                   help="a saved Match-V5 participant object (spell1Casts..spell4Casts)")
    ap.add_argument("--champion-id", default=None,
                    help="DDragon id override when the session cannot name one champion")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = ap.parse_args(argv)
    p = Path(args.session)
    if not p.is_file():
        print("not a file (path not echoed: its stem may be a real game id)", file=sys.stderr)
        return 2
    participant = None
    if args.truth_json:
        try:
            participant = json.loads(Path(args.truth_json).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"truth json not readable: {type(exc).__name__}", file=sys.stderr)
            return 2
        if not isinstance(participant, dict):
            print("truth json is not an object", file=sys.stderr)
            return 2
    try:
        s = check(p, truth_db=Path(args.truth_db) if args.truth_db else None,
                  truth_participant=participant, champion_id=args.champion_id)
    except (SessionFormatError, OSError, RecursionError) as exc:
        detail = "" if isinstance(exc, OSError) else f": {exc}"
        print(f"not a readable session: {type(exc).__name__}{detail}", file=sys.stderr)
        return 2
    print(json.dumps(s, indent=1, ensure_ascii=True) if args.json else render(s))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
