"""scripts/postmortem_analyze.py - offline death-pattern analyzer (ADR-007 phase 2).

Mines `data/rewind_history.db` for the tracked PUUID(s)' CHAMPION_KILL events
(as victim), classifies each death against a small fixed taxonomy, aggregates
counts + Laplace-smoothed rates (`core/smoothed_rates.py`), and writes the
top-3 patterns to `data/coaching/death_patterns.json`. The live mode coaches
read that file at startup and inject the top-3 as PERSONAL CONTEXT so advice
is calibrated to the operator's actual recurring mistakes instead of a
generic checklist.

Output schema (v1):
    {
      "schema_version": 1,
      "generated_at": "<utc iso>",
      "puuids": [...],
      "total_deaths": N,
      "total_matches": M,
      "patterns": {
        "<pattern_key>": {
          "count": int,
          "rate": float,        # laplace-smoothed share of all deaths
          "confidence": float,  # shrink(count, k=5) in [0,1)
          "label": "human readable",
          "description": "what it means + how to avoid"
        }, ...
      },
      "top3": ["<key>", "<key>", "<key>"]
    }

Patterns (8; all computable from existing schema, no derived data layer):
  - caught_4plus:     died with >=4 enemies involved (assists>=3); severe positioning
  - small_skirmish:   died with 1-2 assists; 2v1/3v2 trade lost
  - solo_1v1_loss:    died with 0 assists (lost a clean 1v1)
  - early_pre_3min:   died before 3:00 in-game (invade / first-wave)
  - midgame_collapse: died in 8:00-15:00 window (early-mid transition errors)
  - solo_pickoff:     no ally CHAMPION_KILL within 8s before this death
  - late_throw:       died after 25:00 in-game (late-game positioning errors)
  - rapid_repeat:     died <=60s after a previous death by the same victim (tilt cluster)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.smoothed_rates import laplace_rate, shrink  # noqa: E402

DEFAULT_DB = ROOT / "data" / "rewind_history.db"
DEFAULT_OUTPUT = ROOT / "data" / "coaching" / "death_patterns.json"
CATCHUP_STATE = ROOT / "data" / "rewind_catchup.state.json"

EARLY_THRESHOLD_MS = 3 * 60 * 1000
LATE_THRESHOLD_MS = 25 * 60 * 1000
SOLO_PICKOFF_WINDOW_MS = 8 * 1000
RAPID_REPEAT_WINDOW_MS = 60 * 1000
MIDGAME_LOW_THRESHOLD_MS = 8 * 60 * 1000
MIDGAME_HIGH_THRESHOLD_MS = 15 * 60 * 1000
SMALL_SKIRMISH_MIN_ASSISTS = 1
SMALL_SKIRMISH_MAX_ASSISTS = 2

PATTERN_META = {
    "caught_4plus": {
        "label": "Caught by 4+",
        "description": "died with 4+ enemies on you; positioning error, watch minimap for missing enemies before stepping up",
    },
    "small_skirmish": {
        "label": "Small skirmish loss",
        "description": "died in a 2v1/3v2-style trade with limited team support; reconsider engage timing or rotate with the full team",
    },
    "solo_1v1_loss": {
        "label": "Lost 1v1",
        "description": "died in a clean 1v1 with no assists; matchup/skill/build mismatch - reconsider trade timing or build path",
    },
    "early_pre_3min": {
        "label": "Early-game deaths",
        "description": "died before 3 min; respect level-1 invade pathing and first-wave trade-windows",
    },
    "midgame_collapse": {
        "label": "Mid-game collapse",
        "description": "died during the 8-15 minute window; this is the transition where roams and objective pace flip the game - keep wards refreshed and avoid solo skirmishes off-objective",
    },
    "solo_pickoff": {
        "label": "Solo pickoffs",
        "description": "died alone with no ally death in the 8s before; ward the entry path or rotate with the team",
    },
    "late_throw": {
        "label": "Late-game throws",
        "description": "died past 25 min; late deaths cost objectives - play for vision + grouping over hero plays",
    },
    "rapid_repeat": {
        "label": "Rapid repeat deaths",
        "description": "died again within 60s of the previous death; reset emotionally + check map before re-engaging",
    },
}

PATTERN_KEYS = tuple(PATTERN_META.keys())


@dataclass(frozen=True)
class DeathEvent:
    match_id: str
    timestamp_ms: int
    victim_id: int
    killer_id: int | None
    assists: tuple[int, ...]


def _load_default_puuids() -> list[str]:
    """Resolve operator PUUIDs from catchup state.json (current + stale)."""
    if not CATCHUP_STATE.exists():
        return []
    try:
        data = json.loads(CATCHUP_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out: list[str] = []
    cur = data.get("puuid")
    stale = data.get("stale_puuid")
    if isinstance(cur, str) and cur:
        out.append(cur)
    if isinstance(stale, str) and stale and stale not in out:
        out.append(stale)
    return out


def _resolve_participant_ids(
    conn: sqlite3.Connection, puuids: list[str]
) -> dict[str, int]:
    """Map (match_id) -> participant_id for the FIRST matching puuid in `puuids`."""
    if not puuids:
        return {}
    placeholders = ",".join("?" * len(puuids))
    sql = f"SELECT match_id, participant_id FROM participants WHERE puuid IN ({placeholders})"
    return {row[0]: row[1] for row in conn.execute(sql, puuids)}


def _classify_death(death: DeathEvent, prior_ally_deaths: list[int], prior_self_death_ts_ms: int | None) -> set[str]:
    """Pure classifier. `prior_ally_deaths` = ally death timestamps strictly before `death.timestamp_ms`.

    Assist-band patterns are mutually exclusive via elif (caught_4plus / small_skirmish /
    solo_1v1_loss); time-band + window patterns are independent set-additive checks.
    """
    tags: set[str] = set()
    n_assists = len(death.assists)
    if n_assists >= 3:
        tags.add("caught_4plus")
    elif SMALL_SKIRMISH_MIN_ASSISTS <= n_assists <= SMALL_SKIRMISH_MAX_ASSISTS:
        tags.add("small_skirmish")
    elif n_assists == 0:
        tags.add("solo_1v1_loss")
    if death.timestamp_ms < EARLY_THRESHOLD_MS:
        tags.add("early_pre_3min")
    if MIDGAME_LOW_THRESHOLD_MS <= death.timestamp_ms <= MIDGAME_HIGH_THRESHOLD_MS:
        tags.add("midgame_collapse")
    if death.timestamp_ms >= LATE_THRESHOLD_MS:
        tags.add("late_throw")
    window_start = death.timestamp_ms - SOLO_PICKOFF_WINDOW_MS
    ally_in_window = any(window_start <= t < death.timestamp_ms for t in prior_ally_deaths)
    if not ally_in_window:
        tags.add("solo_pickoff")
    if prior_self_death_ts_ms is not None and (death.timestamp_ms - prior_self_death_ts_ms) <= RAPID_REPEAT_WINDOW_MS:
        tags.add("rapid_repeat")
    return tags


def iter_deaths(conn: sqlite3.Connection, puuids: list[str]) -> list[DeathEvent]:
    """Return all CHAMPION_KILL events where one of the given PUUIDs is the victim."""
    pid_map = _resolve_participant_ids(conn, puuids)
    if not pid_map:
        return []
    out: list[DeathEvent] = []
    placeholders = ",".join("?" * len(pid_map))
    sql = f"""
        SELECT te.match_id, te.timestamp_ms, te.victim_id, te.killer_id, te.assisting_ids_json
        FROM timeline_events te
        WHERE te.event_type = 'CHAMPION_KILL'
          AND te.match_id IN ({placeholders})
        ORDER BY te.match_id, te.timestamp_ms
    """
    for match_id, ts, victim_id, killer_id, assist_json in conn.execute(sql, list(pid_map.keys())):
        if victim_id != pid_map.get(match_id):
            continue
        try:
            assists = tuple(json.loads(assist_json or "[]"))
        except (TypeError, ValueError):
            assists = ()
        out.append(DeathEvent(match_id=match_id, timestamp_ms=int(ts), victim_id=int(victim_id),
                              killer_id=int(killer_id) if killer_id is not None else None,
                              assists=tuple(int(a) for a in assists if isinstance(a, int))))
    return out


def _ally_deaths_per_match(conn: sqlite3.Connection, match_ids: set[str], self_pid_by_match: dict[str, int]) -> dict[str, list[tuple[int, int]]]:
    """For each match, list (timestamp_ms, victim_id) of every CHAMPION_KILL, so the classifier
    can filter by team membership at the call site."""
    if not match_ids:
        return {}
    placeholders = ",".join("?" * len(match_ids))
    sql = f"""
        SELECT match_id, timestamp_ms, victim_id
        FROM timeline_events
        WHERE event_type = 'CHAMPION_KILL' AND match_id IN ({placeholders})
        ORDER BY match_id, timestamp_ms
    """
    out: dict[str, list[tuple[int, int]]] = {}
    for match_id, ts, victim_id in conn.execute(sql, list(match_ids)):
        out.setdefault(match_id, []).append((int(ts), int(victim_id)))
    return out


def _team_id_by_match(conn: sqlite3.Connection, match_ids: set[str], self_pid_by_match: dict[str, int]) -> dict[str, dict[int, int]]:
    """Map match_id -> {participant_id: team_id} so we can distinguish ally vs enemy deaths."""
    if not match_ids:
        return {}
    placeholders = ",".join("?" * len(match_ids))
    sql = f"SELECT match_id, participant_id, team_id FROM participants WHERE match_id IN ({placeholders})"
    out: dict[str, dict[int, int]] = {}
    for match_id, pid, team_id in conn.execute(sql, list(match_ids)):
        out.setdefault(match_id, {})[int(pid)] = int(team_id)
    return out


def classify_all(conn: sqlite3.Connection, deaths: list[DeathEvent]) -> dict[str, int]:
    """Aggregate pattern counts across all deaths."""
    counts = dict.fromkeys(PATTERN_KEYS, 0)
    if not deaths:
        return counts
    match_ids = {d.match_id for d in deaths}
    self_pid_by_match = {d.match_id: d.victim_id for d in deaths}
    ally_deaths_per_match = _ally_deaths_per_match(conn, match_ids, self_pid_by_match)
    team_id_by_match = _team_id_by_match(conn, match_ids, self_pid_by_match)
    prev_self_death_ts: dict[str, int] = {}
    for death in deaths:
        self_team = team_id_by_match.get(death.match_id, {}).get(death.victim_id)
        ally_ts = [
            ts for ts, vid in ally_deaths_per_match.get(death.match_id, [])
            if vid != death.victim_id
            and team_id_by_match.get(death.match_id, {}).get(vid) == self_team
            and ts < death.timestamp_ms
        ]
        prior_self = prev_self_death_ts.get(death.match_id)
        tags = _classify_death(death, ally_ts, prior_self)
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
        prev_self_death_ts[death.match_id] = death.timestamp_ms
    return counts


def build_report(deaths: list[DeathEvent], counts: dict[str, int], puuids: list[str]) -> dict:
    total = len(deaths)
    matches = len({d.match_id for d in deaths})
    patterns_out: dict[str, dict] = {}
    for key in PATTERN_KEYS:
        n = counts.get(key, 0)
        rate = laplace_rate(n, total) if total > 0 else 0.0
        conf = shrink(n)
        patterns_out[key] = {
            "count": n,
            "rate": round(rate, 4),
            "confidence": round(conf, 4),
            "label": PATTERN_META[key]["label"],
            "description": PATTERN_META[key]["description"],
        }
    top3 = sorted(PATTERN_KEYS, key=lambda k: (-patterns_out[k]["count"], k))[:3]
    top3 = [k for k in top3 if patterns_out[k]["count"] > 0]
    return {
        "schema_version": 1,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "puuids": list(puuids),
        "total_deaths": total,
        "total_matches": matches,
        "patterns": patterns_out,
        "top3": top3,
    }


def write_atomic(target: pathlib.Path, payload: dict) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".postmortem.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=False)
            f.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline death-pattern analyzer (ADR-007 phase 2).")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to rewind_history.db")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output JSON path")
    parser.add_argument("--puuid", action="append", default=None,
                        help="PUUID to analyze (may repeat). Default: read from rewind_catchup.state.json")
    parser.add_argument("--dry-run", action="store_true", help="Compute + print report, do not write")
    args = parser.parse_args(argv)

    puuids = args.puuid if args.puuid else _load_default_puuids()
    if not puuids:
        print("No PUUIDs supplied + none in catchup state; pass --puuid", file=sys.stderr)
        return 2

    db_path = pathlib.Path(args.db)
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 3

    conn = sqlite3.connect(str(db_path))
    try:
        deaths = iter_deaths(conn, puuids)
        counts = classify_all(conn, deaths)
        report = build_report(deaths, counts, puuids)
    finally:
        conn.close()

    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0

    out = pathlib.Path(args.output)
    write_atomic(out, report)
    print(f"wrote {out} ({report['total_deaths']} deaths / {report['total_matches']} matches)")
    print(f"top3: {report['top3']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
