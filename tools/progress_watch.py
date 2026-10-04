#!/usr/bin/env python3
"""progress_watch.py - read ops/loop/control/progress/*.json and say which
long jobs have stopped reporting (Y-06, external reference J).

WHY. FLEET-COMMON item 12 makes every long job write a progress file
{"task", "pct", "step", "eta_s", "status": running|done|failed, "updated"} and
says a file that stops updating for 2x its ETA is a failure. The writer side
exists (the kit's write_progress in ops/fleet_kit/fleet_headless.py, read-only
here, and ops/loop/drain_waves_2_3.py _progress) but nothing READ the files,
so the rule could not fire. This is the RC-local reader of that EXISTING
format. It is not a fleet-wide job-health contract (that stays MAIN fleet-kit
v5's) and it keeps its state private; it shares no watcher module.

ETA_S SEMANTICS (Step 0, measured 2026-10-04 over every writer of the dir):
  * fleet_headless.write_progress stores whatever the caller passes, clamped
    to an int >= 0 or null. It has no RC caller.
  * drain_waves_2_3._progress re-states a WHOLE-TASK figure at every step
    (the launcher writes the full wave ETA each time; per-run files carry the
    run's timeout) and writes eta_s null on a failed start.
  * agent-written files (preamble rule) carry a REMAINING estimate that
    shrinks as pct grows (75% -> 500, 85% -> 300), i.e. per-step.
  Both readings put the next expected write at or before updated + eta_s, so
  the one rule "running and now - updated > 2x eta_s" is right for per-step
  and merely LENIENT (late, never false) for whole-task. The false-alarm case
  is a running file with eta_s 0 / null / junk: that is floored to MIN_ETA_S.

VERDICTS. running, done, failed, malformed, and for a running file whose age
passes its ETA: overrun_1.5x (REPORT), stale (> 2x), overrun_3x (REPORT).
Nothing is ever killed or restarted - this tool only reads and reports.

ALERTS. One alert per (task, verdict) transition into failed / overrun_1.5x /
stale / overrun_3x / malformed, delivered as a NOTE on the steer channel
(ops/loop/steer.py append, tier='note'). Never chat. A changed 'updated'
(or, for a malformed file, a changed mtime) clears the task's alerts so a
relapse alerts again. The very first run (no state file) is a silent
baseline; a file first seen on a LATER run was created since the last look
and alerts normally. An alert is recorded as sent only after the send
returned, so a failed send is retried next run.

SELF-CHECK. A run that reads zero progress files - dir missing, dir empty, or
every file unreadable - adds to a streak; at K consecutive runs the watcher
flags ITSELF (one selfcheck note, exit code 2 while it lasts). A watcher that
exits 0 having looked at nothing is the failure this guards.

Usage:
  python tools/progress_watch.py              # classify, alert, save state
  python tools/progress_watch.py --dry-run    # classify only: no send, no write
  python tools/progress_watch.py --json       # machine-readable report
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRESS_DIR = ROOT / "ops" / "loop" / "control" / "progress"
STATE_PATH = ROOT / "ops" / "runtime" / "progress_watch.json"

STATE_SCHEMA = 1
# Floor for a RUNNING file's eta_s when it is 0 / null / junk. Derived from
# FLEET-COMMON item 12 itself: progress files are required of work "expected
# to take over 5 minutes", so 300 s is the smallest ETA such a job can mean.
MIN_ETA_S = 300
STALE_FACTOR = 2.0                 # FLEET-COMMON item 12: "2x its own ETA"
OVERRUN_REPORT = (1.5, 3.0)        # report-only rungs either side of STALE
# Consecutive zero-read runs before the watcher flags itself: one torn read
# and one retry are tolerated, the third in a row is not.
SELF_CHECK_K = 3

STATUSES = ("running", "done", "failed")
ALERT_VERDICTS = ("failed", "overrun_1.5x", "stale", "overrun_3x", "malformed")
KEY_PREFIX = "progress_watch"


# ---------------------------------------------------------------- timestamps

_FRACTION = re.compile(r"(\.\d{1,6})\d+")
_COMPACT_TZ = re.compile(r"([+-]\d{2})(\d{2})$")


def parse_updated(value) -> float | None:
    """Epoch seconds for an 'updated' value, or None.

    Accepts every shape the live dir holds (measured 2026-10-04): naive local
    ('2026-10-04T00:19:44', read as LOCAL time), tz-aware with '+HH:MM', 'Z',
    or '-HHMM' (strftime %z), fractions longer than 6 digits (PowerShell's
    round-trip format writes 7), and a bare date (local midnight).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    s = _FRACTION.sub(r"\1", s)
    if "T" in s:
        s = _COMPACT_TZ.sub(r"\1:\2", s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    try:
        return float(dt.timestamp())   # naive -> local time, by definition
    except (OverflowError, OSError, ValueError):
        return None


def _eta(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return int(value) if value > 0 else None


# ---------------------------------------------------------------- classify

def classify(doc: dict, now: float) -> dict:
    """Verdict for one parsed progress document. Raises ValueError with the
    reason when the document is not a usable progress record."""
    status = doc.get("status")
    if status not in STATUSES:
        raise ValueError(f"status {status!r} not in {STATUSES}")
    out = {"status": status, "pct": doc.get("pct"), "step": str(doc.get("step") or ""),
           "updated": doc.get("updated"), "age_s": None, "eta_s": doc.get("eta_s"),
           "eta_used": None, "eta_floored": False, "ratio": None}
    ts = parse_updated(doc.get("updated"))
    if ts is not None:
        out["age_s"] = max(0.0, now - ts)     # a future stamp reads as fresh
    if status != "running":
        out["verdict"] = status
        return out
    if ts is None:
        raise ValueError(f"running but 'updated' {doc.get('updated')!r} is unparseable")
    eta = _eta(doc.get("eta_s"))
    floored = eta is None or eta < MIN_ETA_S
    eta_used = MIN_ETA_S if floored else eta
    ratio = out["age_s"] / eta_used
    if ratio >= OVERRUN_REPORT[1]:
        verdict = "overrun_3x"
    elif ratio > STALE_FACTOR:
        verdict = "stale"
    elif ratio >= OVERRUN_REPORT[0]:
        verdict = "overrun_1.5x"
    else:
        verdict = "running"
    out.update(verdict=verdict, eta_used=eta_used, eta_floored=floored,
               ratio=round(ratio, 3))
    return out


def scan(progress_dir: Path, now: float) -> tuple[list, list, int, str]:
    """(tasks, malformed, files_seen, dir_state). Never raises on file content."""
    d = Path(progress_dir)
    if not d.is_dir():
        return [], [], 0, "missing"
    tasks, malformed = [], []
    files = sorted(p for p in d.glob("*.json") if p.is_file())
    for p in files:
        stem = p.stem
        try:
            mtime_ns = p.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        reason = None
        try:
            doc = json.loads(p.read_bytes().decode("utf-8-sig"))
            if not isinstance(doc, dict):
                raise ValueError(f"top level is {type(doc).__name__}, not an object")
            row = classify(doc, now)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            reason = f"{type(exc).__name__}: {exc}"[:200]
        if reason is not None:
            malformed.append({"file": p.name, "reason": reason})
            tasks.append({"task": stem, "verdict": "malformed", "reason": reason,
                          "stamp": f"mtime:{mtime_ns}"})
            continue
        row["task"] = stem
        row["stamp"] = str(row["updated"])
        tasks.append(row)
    return tasks, malformed, len(files), ("empty" if not files else "ok")


# ---------------------------------------------------------------- state

def _load_state(path: Path) -> tuple[dict | None, bool]:
    """(state or None for first sight, state_reset)."""
    p = Path(path)
    if not p.exists():
        return None, False
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("schema") == STATE_SCHEMA \
                and isinstance(doc.get("tasks"), dict):
            return doc, False
    except (OSError, ValueError):
        pass
    return None, True


def _save_state(path: Path, state: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(state, indent=1, ensure_ascii=True, sort_keys=True) + "\n").encode("ascii")
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        for attempt in range(6):        # a polling reader can share-lock the target
            try:
                tmp.replace(p)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------- transport

def _steer_module():
    """ops/loop/steer.py, bound by file path (ops/ is not a package import
    from tools/). Loaded lazily: a dry run never touches the transport."""
    name = "ops.loop.steer"
    if name in sys.modules:
        return sys.modules[name]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import importlib
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError:
        spec = importlib.util.spec_from_file_location(
            "rc_loop_steer_pw", ROOT / "ops" / "loop" / "steer.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def steer_send(text: str, key: str) -> None:
    """Deliver one alert as a NOTE: it lands at the consumer's next safe
    boundary and stays in the append-only steer ledger for audit."""
    _steer_module().append(text, tier="note", key=key, source=KEY_PREFIX)


def _ascii(s) -> str:
    return str(s).encode("ascii", "replace").decode("ascii").replace("\n", " ")


def _age_phrase(age_s) -> str:
    if age_s is None:
        return "?"
    m = int(age_s) // 60
    return f"{m // 60}h{m % 60:02d}m" if m >= 60 else f"{m}m{int(age_s) % 60:02d}s"


def alert_text(row: dict) -> str:
    v = row["verdict"]
    task = row["task"]
    if v == "malformed":
        return _ascii(f"progress_watch: progress file {task}.json is unreadable "
                      f"({row.get('reason')})")
    if v == "failed":
        return _ascii(f"progress_watch: task {task} reported FAILED at pct "
                      f"{row.get('pct')}: {row.get('step', '')[:160]}")
    label = {"overrun_1.5x": "OVERRUN 1.5x (report)", "stale": "STALE",
             "overrun_3x": "OVERRUN 3x (report)"}[v]
    floor = " (eta floored)" if row.get("eta_floored") else ""
    return _ascii(f"progress_watch: task {task} {label} - running, last update "
                  f"{_age_phrase(row.get('age_s'))} ago, eta_s {row.get('eta_s')}"
                  f"{floor}, {row.get('ratio')}x; step: {row.get('step', '')[:160]}. "
                  "Report only - nothing was stopped.")


# ---------------------------------------------------------------- run

def run(*, progress_dir=PROGRESS_DIR, state_path=STATE_PATH, now=None, send=None,
        dry_run=False, k=SELF_CHECK_K) -> dict:
    now = time.time() if now is None else float(now)
    send = steer_send if send is None else send
    tasks, malformed, files_seen, dir_state = scan(progress_dir, now)
    files_read = sum(1 for t in tasks if t["verdict"] != "malformed")
    prev_state, state_reset = _load_state(state_path)
    baseline = prev_state is None
    prev_tasks = {} if baseline else prev_state["tasks"]

    sent, would_alert, send_failures = [], [], 0
    new_tasks = {}
    for row in tasks:
        stem, verdict = row["task"], row["verdict"]
        prev = prev_tasks.get(stem)
        alerted = list(prev.get("alerted") or []) \
            if isinstance(prev, dict) and prev.get("stamp") == row["stamp"] else []
        if verdict in ALERT_VERDICTS and verdict not in alerted:
            key = f"{KEY_PREFIX}:{stem}:{verdict}"
            if baseline:
                alerted.append(verdict)          # first sight: record, stay silent
            elif dry_run:
                would_alert.append(key)
            else:
                try:
                    send(alert_text(row), key)
                except Exception:  # noqa: BLE001 - an undelivered alert retries next run
                    send_failures += 1
                else:
                    alerted.append(verdict)
                    sent.append(key)
        row["alerted"] = alerted
        new_tasks[stem] = {"stamp": row["stamp"], "verdict": verdict, "alerted": alerted}

    prev_streak = 0 if baseline else int(prev_state.get("zero_read_streak") or 0)
    streak = prev_streak + 1 if files_read == 0 else 0
    self_failed = streak >= k
    self_alerted = (not baseline) and bool(prev_state.get("selfcheck_alerted")) \
        and streak > 0
    if self_failed and not self_alerted:
        key = f"{KEY_PREFIX}:selfcheck"
        text = _ascii(f"progress_watch: SELF-CHECK FAILED - {streak} consecutive runs "
                      f"read zero progress files (dir {dir_state}, {files_seen} seen, "
                      f"{len(malformed)} unreadable). The watcher is doing no work.")
        if dry_run:
            would_alert.append(key)
        else:
            try:
                send(text, key)
            except Exception:  # noqa: BLE001
                send_failures += 1
            else:
                self_alerted = True
                sent.append(key)

    report = {
        "now": now, "dry_run": bool(dry_run), "baseline": baseline,
        "state_reset": state_reset, "dir_state": dir_state,
        "files_seen": files_seen, "files_read": files_read,
        "malformed": malformed, "tasks": tasks, "sent": sent,
        "would_alert": would_alert, "send_failures": send_failures,
        "zero_read_streak": streak, "self_check_failed": self_failed,
        "exit_code": 2 if self_failed else 0,
    }
    if not dry_run:
        _save_state(state_path, {
            "schema": STATE_SCHEMA, "updated": now,
            "runs": (0 if baseline else int(prev_state.get("runs") or 0)) + 1,
            "zero_read_streak": streak, "selfcheck_alerted": self_alerted,
            "last": {"files_seen": files_seen, "files_read": files_read,
                     "malformed": len(malformed), "sent": len(sent),
                     "send_failures": send_failures},
            "tasks": new_tasks,
        })
    return report


def format_report(rep: dict) -> str:
    order = ("overrun_3x", "stale", "overrun_1.5x", "failed", "malformed", "running", "done")
    lines = [f"progress_watch: {rep['files_read']}/{rep['files_seen']} files read "
             f"(dir {rep['dir_state']}){' [dry-run]' if rep['dry_run'] else ''}"
             f"{' [baseline]' if rep['baseline'] else ''}"]
    for v in order:
        rows = [t for t in rep["tasks"] if t["verdict"] == v]
        if not rows:
            continue
        lines.append(f"  {v} ({len(rows)}):")
        for t in rows:
            if v == "malformed":
                lines.append(f"    {t['task']}: {t['reason']}")
            elif v in ("running", "overrun_1.5x", "stale", "overrun_3x"):
                lines.append(f"    {t['task']}: age {_age_phrase(t['age_s'])}, eta_s "
                             f"{t['eta_s']}{' (floored)' if t['eta_floored'] else ''}, "
                             f"{t['ratio']}x")
            else:
                lines.append(f"    {t['task']}: age {_age_phrase(t['age_s'])}")
    for key in rep["sent"]:
        lines.append(f"  sent: {key}")
    for key in rep["would_alert"]:
        lines.append(f"  would alert: {key}")
    if rep["send_failures"]:
        lines.append(f"  SEND FAILURES: {rep['send_failures']} (retried next run)")
    if rep["self_check_failed"]:
        lines.append(f"  SELF-CHECK FAILED: zero files read for {rep['zero_read_streak']} runs")
    return "\n".join(_ascii(line) for line in lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dir", type=Path, default=PROGRESS_DIR)
    ap.add_argument("--state", type=Path, default=STATE_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="classify only: send nothing, write no state")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-k", type=int, default=SELF_CHECK_K)
    a = ap.parse_args(argv)
    rep = run(progress_dir=a.dir, state_path=a.state, dry_run=a.dry_run, k=max(1, a.k))
    print(json.dumps(rep, indent=1, ensure_ascii=True) if a.json else format_report(rep))
    return rep["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
