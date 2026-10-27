"""gated_g717_arena_readback.py - G7-17 read-back: the RM-868 post-fix Arena cohort in ONE command.

G7-17 (docs/LIVE_GAME_GATED_SYNC.md GATE 7) waits on one real Arena game played
AFTER an RC restart that loads the RM-868 fix (``d47e9906b`` + ``4d07738aa``),
and asks four things of it: (a) ``data/arena_coaching_data.json`` reads
``camp_phase: true`` at least once; (b) the new ``data/arena_coach_shadow.jsonl``
rows carry deterministic ``BUY ITEMS`` > 0 and no placeholder row; (c)
``tools/arena_shadow_report.py --since <restart>`` scores the post-fix cohort
only; (d) on the first item anvil a ``data/anvil_shadow.jsonl`` row names the
on-screen cards (the GATE 5 DRAIN CARD G5-01 predicate). This tool reads all
four at once, after the game, from the MAIN checkout's ``data/``.

THE CUTOFF IS COMPARED AS A TIME, NEVER AS A STRING. The shadow writer stamps
``ts`` as UTC ``isoformat()`` (``core/arena_coach_shadow.py`` ``log_arena_coach``)
and ``arena_shadow_report._since_filter`` compares ``ts >= since`` as STRINGS, so
a ``--since`` written in local time with an offset (``11:00-05:00``) admits every
UTC row stamped 11:00-16:00Z, five hours of pre-restart rows. This tool parses
the cutoff, converts it to UTC, and hands the report the UTC ``isoformat()``,
the one spelling its string compare orders correctly. The default cutoff is
``ops/runtime/health.json`` ``started_at`` (UTC isoformat, written at RC boot).

PREDICATES (stated in docs/LIVE_GAME_GATED_SYNC.md G7-17 before any game):
  restart  PASS iff the cutoff is at or after FIX_COMMITTED_UTC (a restart
           before the fix landed cannot be running it); else FAIL.
  camp     PASS iff a coaching-file snapshot taken at or after the cutoff has
           ``mode`` arena and ``camp_phase`` True, OR a cohort row carries
           deterministic BUY ITEMS (``core/arena_action_rule.py`` rule 1: only a
           truthy camp_phase yields it, and the row's camp_phase is the coaching
           file's, ``dashboard/_deterministic_coaching.py``); else NOT_SEEN.
  cohort   FAIL iff any cohort row is a placeholder row (no Haiku action AND a
           round in ``_ARENA_PLACEHOLDER_ROUNDS`` 0 / "" / None - the exact
           ``_arena_artifact_is_blank`` predicate the fix stops writing); PASS
           iff at least one sample row exists and deterministic BUY ITEMS > 0;
           else INCOMPLETE. A blank Haiku action on a REAL round still logs by
           design (RM-868), so it is counted and shown, never failed.
  report   RECORDED iff the cohort has at least one live-fight comparable
           round; the class agreement and the state are printed verbatim,
           whatever they are (the flip stays operator-gated even at ready).
  anvil    CANDIDATE iff an arena row stamped at or after the cutoff exists:
           its offered cards must still be matched by eye against the anvil
           on screen, so this tool never passes it; else NO_ROW.

READ-ONLY: it reads files only; it never writes, moves, locks or deletes
anything, prints no game id, and never ticks a row - its output is the INPUT
to the four-part evidence contract, never the evidence by itself.

USAGE (from a worktree it reads the MAIN checkout's data/; run after the game,
or with --samples during it to poll the coaching file across a camp)
    python tools/gated_g717_arena_readback.py
    python tools/gated_g717_arena_readback.py --since 2026-10-27T13:00:00-05:00 --json
    python tools/gated_g717_arena_readback.py --samples 30 --interval 10
Exit 0 = every machine-readable check met (anvil CANDIDATE still needs the
eye), 1 = INCOMPLETE, 2 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools import arena_shadow_report as asr  # noqa: E402
from tools.gated_frame_readback import main_checkout  # noqa: E402

SHADOW_REL = Path("data") / "arena_coach_shadow.jsonl"
ANVIL_REL = Path("data") / "anvil_shadow.jsonl"
COACH_REL = Path("data") / "arena_coaching_data.json"
HEALTH_REL = Path("ops") / "runtime" / "health.json"
# Committer time of 4d07738aa, the later of the two RM-868 fix commits
# (d47e9906b 01:28:45-05:00, 4d07738aa 01:28:48-05:00, both 2026-10-25).
FIX_COMMITTED_UTC = datetime(2026, 10, 25, 6, 28, 48, tzinfo=timezone.utc)
BUY_ITEMS = "BUY ITEMS"
# dashboard/_deterministic_coaching.py _ARENA_PLACEHOLDER_ROUNDS (pinned by test).
PLACEHOLDER_ROUNDS = (0, "", None)


def parse_utc(text: Any) -> datetime | None:
    """An ISO time as an aware UTC datetime; a naive value is read as UTC."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_jsonl(path: Path) -> list[dict]:
    """The dict rows of a jsonl file; a missing file or a bad line is skipped."""
    rows: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return rows
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def after(rows: list[dict], cutoff: datetime) -> list[dict]:
    """The rows whose ``ts`` parses to a time at or after ``cutoff``."""
    out = []
    for r in rows:
        ts = parse_utc(r.get("ts"))
        if ts is not None and ts >= cutoff:
            out.append(r)
    return out


def _action(block: Any) -> str:
    if not isinstance(block, dict):
        return ""
    a = block.get("action")
    return a.strip() if isinstance(a, str) else ""


def is_placeholder(rec: dict) -> bool:
    """No Haiku action AND a placeholder round (``_arena_artifact_is_blank``)."""
    return not _action(rec.get("live_haiku")) and rec.get("round") in PLACEHOLDER_ROUNDS


def check_restart(cutoff: datetime | None, source: str) -> dict[str, Any]:
    if cutoff is None:
        return {"status": "INCOMPLETE", "source": source,
                "note": "no cutoff: pass --since or keep ops/runtime/health.json started_at"}
    ok = cutoff >= FIX_COMMITTED_UTC
    return {"status": "PASS" if ok else "FAIL", "source": source,
            "cutoff_utc": cutoff.isoformat(), "fix_committed_utc": FIX_COMMITTED_UTC.isoformat()}


def snapshot_coach(path: Path) -> dict[str, Any]:
    """One read of the coaching file: mode, camp_phase, round, game time, mtime."""
    try:
        mtime = path.stat().st_mtime
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {"present": False}
    if not isinstance(data, dict):
        return {"present": False}
    return {"present": True,
            "mtime_utc": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
            "mode": data.get("mode"), "camp_phase": data.get("camp_phase"),
            "round": data.get("round"), "game_time_s": data.get("game_time_s")}


def check_cohort(rows: list[dict]) -> dict[str, Any]:
    samples = [r for r in rows if not asr.is_focus_board_relog(r)]
    det = Counter(_action(r.get("deterministic")) or "(blank)" for r in samples)
    placeholder = sum(1 for r in samples if is_placeholder(r))
    blank_haiku = sum(1 for r in samples if not _action(r.get("live_haiku")))
    buy = det.get(BUY_ITEMS, 0)
    if placeholder:
        status = "FAIL"
    elif samples and buy > 0:
        status = "PASS"
    else:
        status = "INCOMPLETE"
    return {"status": status, "rows": len(rows), "samples": len(samples),
            "relogs": len(rows) - len(samples), "buy_items": buy,
            "placeholder_rows": placeholder, "blank_haiku_rows": blank_haiku,
            "det_actions": dict(det.most_common())}


def check_camp(snaps: list[dict], cutoff: datetime | None, buy_items: int) -> dict[str, Any]:
    seen = 0
    for s in snaps:
        t = parse_utc(s.get("mtime_utc"))
        if (s.get("present") and s.get("mode") == "arena" and s.get("camp_phase") is True
                and (cutoff is None or (t is not None and t >= cutoff))):
            seen += 1
    status = "PASS" if (seen or buy_items) else "NOT_SEEN"
    return {"status": status, "snapshots": len(snaps), "camp_true_snapshots": seen,
            "buy_items_rows": buy_items, "last": snaps[-1] if snaps else None}


def check_report(shadow: Path, cutoff: datetime | None) -> dict[str, Any]:
    if cutoff is None:
        return {"status": "INCOMPLETE", "note": "no cutoff"}
    rep = asr.build_report(shadow, since=cutoff.isoformat())
    agr = rep.get("agreement", {})
    fr = rep.get("flip_readiness", {})
    return {"status": "RECORDED" if agr.get("comparable", 0) else "NO_DATA",
            "since": rep.get("since"), "comparable": agr.get("comparable", 0),
            "agree": agr.get("agree", 0), "state": fr.get("state"),
            "reason": fr.get("reason"),
            "before_since": rep.get("coverage", {}).get("before_since")}


def check_anvil(rows: list[dict]) -> dict[str, Any]:
    arena = [r for r in rows if r.get("mode") == "arena"]
    if not arena:
        return {"status": "NO_ROW", "rows": len(rows)}
    last = arena[-1]
    native = last.get("native") if isinstance(last.get("native"), dict) else {}
    return {"status": "CANDIDATE", "rows": len(arena),
            "last": {"ts": last.get("ts"), "champion": last.get("champion"),
                     "round": last.get("round"), "offered": last.get("offered"),
                     "take": native.get("take")},
            "note": "match offered against the anvil cards on screen before any tick"}


def report(data_root: Path, cutoff: datetime | None, source: str,
           snaps: list[dict]) -> dict[str, Any]:
    shadow = data_root / SHADOW_REL
    cohort_rows = after(load_jsonl(shadow), cutoff) if cutoff else []
    cohort = check_cohort(cohort_rows)
    anvil_rows = after(load_jsonl(data_root / ANVIL_REL), cutoff) if cutoff else []
    checks = {
        "restart": check_restart(cutoff, source),
        "camp": check_camp(snaps, cutoff, cohort["buy_items"]),
        "cohort": cohort,
        "report": check_report(shadow, cutoff),
        "anvil": check_anvil(anvil_rows),
    }
    states = {k: v["status"] for k, v in checks.items()}
    if "FAIL" in states.values():
        verdict = "FAIL"
    elif (states["restart"] == "PASS" and states["camp"] == "PASS"
          and states["cohort"] == "PASS" and states["report"] == "RECORDED"
          and states["anvil"] == "CANDIDATE"):
        verdict = "PASS"
    else:
        verdict = "INCOMPLETE"
    # No path in the output: a drain pastes it into a tracked doc.
    return {"schema": "gated_g717_arena_readback/v1", "verdict": verdict, "checks": checks}


def resolve_cutoff(since: str | None, data_root: Path) -> tuple[datetime | None, str]:
    if since:
        return parse_utc(since), "--since"
    try:
        h = json.loads((data_root / HEALTH_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None, "health.json unreadable"
    return parse_utc(h.get("started_at") if isinstance(h, dict) else None), "health.json started_at"


def render(rep: dict[str, Any]) -> str:
    c = rep["checks"]
    lines = [f"G7-17 read-back: {rep['verdict']}"]
    r = c["restart"]
    lines.append(f"- restart: {r['status']} cutoff {r.get('cutoff_utc')} ({r['source']}),"
                 f" fix committed {r.get('fix_committed_utc')}")
    k = c["camp"]
    lines.append(f"- camp: {k['status']} camp_phase true in {k['camp_true_snapshots']}/"
                 f"{k['snapshots']} snapshots, BUY ITEMS rows {k['buy_items_rows']}")
    h = c["cohort"]
    lines.append(f"- cohort: {h['status']} {h['samples']} samples ({h['relogs']} relogs),"
                 f" BUY ITEMS {h['buy_items']}, placeholder {h['placeholder_rows']},"
                 f" blank Haiku {h['blank_haiku_rows']}, det {h['det_actions']}")
    p = c["report"]
    lines.append(f"- report: {p['status']} agree {p.get('agree')}/{p.get('comparable')}"
                 f" state {p.get('state')} (left out {p.get('before_since')})")
    a = c["anvil"]
    lines.append(f"- anvil: {a['status']} {a.get('last') or ''}")
    lines.append("Not a tick: record value + source + ts + predicate in the G7-17 row.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=None,
                    help="cohort cutoff, any ISO time (default: health.json started_at)")
    ap.add_argument("--data-root", default=None, help="checkout whose data/ is read")
    ap.add_argument("--samples", type=int, default=1, help="coaching-file reads")
    ap.add_argument("--interval", type=float, default=10.0, help="seconds between reads")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    data_root = Path(a.data_root) if a.data_root else (main_checkout(_ROOT) or _ROOT)
    cutoff, source = resolve_cutoff(a.since, data_root)
    snaps = []
    for i in range(max(1, a.samples)):
        if i:
            time.sleep(max(0.0, a.interval))
        snaps.append(snapshot_coach(data_root / COACH_REL))
    rep = report(data_root, cutoff, source, snaps)
    print(json.dumps(rep, indent=2) if a.json else render(rep))
    return {"PASS": 0, "INCOMPLETE": 1}.get(rep["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
