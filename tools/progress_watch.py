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

VERDICTS. running, blocked (kit v14 state), done, failed, malformed, and for a
running / blocked file whose age passes its ETA: overrun_1.5x (REPORT), stale
(> 2x), overrun_3x (REPORT). The watch pass never kills, restarts or writes a
progress file - it reads and reports.

REAPER (RM-728, KF-P11; `--reap`, plan-only unless `--apply`). The watch pass
alone let the dir grow without bound (152 files at the 2026-10-09 review, rows
'running' for days): no writer expires its own file, and the kit's
close_progress() fires only from spawn() / run_lane, never for an interactive
sub-agent's row. The reaper closes that loop, touching ONLY files it can prove
are item-12 records - a top-level *.json regular file whose stem is a kit task
stem and whose "task" field equals that stem - and never lane-*.json,
inbox-responder.json or loop.json (named by their readers). It never kills a
process and never unlinks a row (its only unlinks are its own tmp, and its
own aside once a newer row superseded it - the bytes a replace would drop):
  * a running / blocked row silent past 2x its ETA (item 12) is rewritten as
    failed in the kit's close_progress() shape (fields kept, "reason" added),
    compare-and-swap on the bytes AND (mtime, size) it classified (RM-785 a)
    with a create-only commit (RM-816): the row is MOVED aside to a private
    name, the aside is compared (no writer races that name), and the failed
    row lands by a no-replace move, so a writer that came back at ANY point
    wins (measured in a free race: 0 of 300 writes lost, 53 of 300 before).
    The price is a short gap in which the target does not exist; a pass
    that dies inside it leaves its aside, and the next applying pass moves
    it back while the target is still missing. Held - the kit's
    progress_abandoned() rule - unless its recorded owner is PROVEN dead or
    the silence is past the kit's ABANDON_S grace (OWNER_ALIVE_GRACE_S): an
    unknown owner, no owner field included, is held like a live one
    (RM-785 b);
  * a done / failed row older than PRUNE_AGE_S by BOTH 'updated' and mtime
    goes to the Recycle Bin through core.recycle_bin.recycle_checked, the
    same bytes + (mtime, size) check run immediately before the call; a
    refusal keeps the file, a nuked result halts the pass. The window left
    is the recycle call itself, ACCEPTED (RM-816): a write landing inside it
    goes to the bin with the row (FOF_ALLOWUNDO, restorable), so it is
    recoverable, not destroyed, and it needs a writer to revive a row that
    has been finished for PRUNE_AGE_S. Reverses if: a recycled row is found
    holding a write newer than the reaper's read, or recycle_checked stops
    sending to an undo-able bin;
  * the keep-list name match case-folds (RM-785 c: NTFS is case-blind);
  * a progress dir that does not resolve inside the repo root is refused.

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
  python tools/progress_watch.py --reap       # + reaper plan (changes nothing)
  python tools/progress_watch.py --reap --apply   # + mark failed / Recycle Bin
"""
from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import math
import os
import re
import stat
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRESS_REL = Path("ops") / "loop" / "control" / "progress"
PROGRESS_DIR = ROOT / PROGRESS_REL
STATE_PATH = ROOT / "ops" / "runtime" / "progress_watch.json"
KIT_HEADLESS = ROOT / "ops" / "fleet_kit" / "fleet_headless.py"

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

# Every kit PROGRESS_STATES value (fleet_headless.py; "blocked" since kit
# v14). LIVE = the states a writer is still expected to update.
STATUSES = ("running", "blocked", "done", "failed")
LIVE_STATUSES = ("running", "blocked")
FINISHED_STATUSES = ("done", "failed")
ALERT_VERDICTS = ("failed", "overrun_1.5x", "stale", "overrun_3x", "malformed")
KEY_PREFIX = "progress_watch"

# ---- reaper (RM-728). Verdicts past 2x ETA (item 12) are reap candidates.
REAP_VERDICTS = ("stale", "overrun_3x")
# A finished row older than this (by 'updated' AND mtime) goes to the bin
# (repo review B22-01: "prune finished progress files older than 7 days").
PRUNE_AGE_S = 7 * 86400
# The kit's ABANDON_S (fleet_headless.py, v16): a row silent this long is
# abandoned even when its owner process is alive - or unknown (RM-785 b).
# Pinned by a test.
OWNER_ALIVE_GRACE_S = 7200
# Read by name by their consumers (lane widget, inbox responder, loop
# controller): never reaped, whatever their state.
KEEP_GLOBS = ("lane-*.json", "inbox-responder.json", "loop.json")
# The kit's write_progress task-stem rule (fleet_headless._TASK).
TASK_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REASON_MAX = 120                   # the kit's close_progress reason cap
# RM-816: a row the mark path moved aside, '<stem>.json.<pid>.reap'. Not a
# *.json name, so no scan reads it as a record.
ASIDE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json)\.\d+\.reap$")
EXIT_REFUSED = 3
EXIT_HALTED = 4


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
    if status not in LIVE_STATUSES:
        out["verdict"] = status
        return out
    if ts is None:
        raise ValueError(f"{status} but 'updated' {doc.get('updated')!r} is unparseable")
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
        verdict = status
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
    _atomic_write(p, data)


def _replace(src: Path, dst: Path) -> None:
    """Path.replace; a module seam so a test can interpose a writer (RM-785)."""
    Path(src).replace(dst)


def _atomic_write(p: Path, data: bytes) -> bool:
    """tmp + replace in the target's own dir (the watcher's own state file).
    The tmp name ends in .tmp, so a *.json scan of the progress dir never
    reads it as a record. A progress row the reaper rewrites does NOT come
    through here: a replace would overwrite a writer that came back, so that
    path is _swap_if_unchanged's create-only commit (RM-816)."""
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        for attempt in range(6):        # a polling reader can share-lock the target
            try:
                _replace(tmp, p)
                return True
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
        return False                    # unreachable: the last attempt raises
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
    order = ("overrun_3x", "stale", "overrun_1.5x", "failed", "malformed", "blocked",
             "running", "done")
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
            elif v in ("running", "blocked", "overrun_1.5x", "stale", "overrun_3x"):
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


# ---------------------------------------------------------------- reaper (RM-728)

_KIT = None


def _kit():
    """The vendored kit's fleet_headless, bound by file path (consumed, never
    edited; byte-pinned by ops/fleet_kit/MANIFEST.json). Raises if unloadable."""
    global _KIT
    if _KIT is None:
        spec = importlib.util.spec_from_file_location(
            "rc_fleet_kit_fleet_headless_pw", KIT_HEADLESS)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _KIT = mod
    return _KIT


def main_root(path=ROOT) -> Path:
    """The MAIN checkout for path - the kit's main_checkout(), so a linked
    worktree answers its main tree, where every writer puts the progress dir
    (kit v12). Falls back to path itself when the kit cannot load."""
    try:
        return Path(_kit().main_checkout(path)).resolve()
    except Exception:  # noqa: BLE001 - the fallback is the pre-kit answer
        return Path(path).resolve()


def _alive_default(owner):
    """The kit's owner_alive(owner): True / False / None. None (unknown) for a
    row with no owner or when the kit cannot load; unknown holds a row like
    True does, until the abandon grace (RM-785 b)."""
    if not isinstance(owner, dict):
        return None
    try:
        return _kit().owner_alive(owner)
    except Exception:  # noqa: BLE001
        return None


def _recycle_default(path):
    """core.recycle_bin.recycle_checked: bin-policy preflight, FOF_ALLOWUNDO,
    then a confirmed $I record - it refuses rather than permanently delete."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import core.recycle_bin as rb
    return rb.recycle_checked(path)


def _inside(child: Path, root: Path) -> bool:
    c, r = os.path.normcase(str(child)), os.path.normcase(str(root))
    try:
        return os.path.commonpath([c, r]) == r
    except ValueError:             # different drives
        return False


def _plain_file(p: Path) -> bool:
    """A regular file that is not a link / reparse point (lstat, never follows)."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if getattr(st, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        return False
    return stat.S_ISREG(st.st_mode) and not stat.S_ISLNK(st.st_mode)


def _iso_local(epoch: float) -> str:
    """The kit's _iso() shape: local time with its offset, whole seconds."""
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def _sig(p: Path):
    """(st_mtime_ns, st_size) by lstat, or None when p cannot be stat'ed."""
    try:
        st = os.lstat(p)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _unchanged(p: Path, raw: bytes, sig) -> bool:
    """RM-785 (a): p still holds exactly the bytes the reaper classified AND
    its (mtime, size) have not moved since - stat'ed before that read, so a
    write landing between the stat and the read also reads as a change. A
    writer that re-wrote identical bytes moved the mtime: it is alive."""
    if sig is None or _sig(p) != sig:
        return False
    try:
        same = p.read_bytes() == raw
    except OSError:
        return False
    return same and _sig(p) == sig


# RM-816: a POSIX rename replaces an existing target, so there the
# create-only move is a hard link plus an unlink. A test flips this to run
# the POSIX path on NTFS (which has hard links too).
_LINK_MOVE = os.name != "nt"


def _move(src: Path, dst: Path) -> None:
    """Create-only move FROM A PRIVATE NAME (the reaper's tmp or aside):
    FileExistsError when dst exists, never a replace. Windows os.rename
    already refuses an existing target; on POSIX it is os.link (refused on an
    existing name) then an unlink of src - safe only because no writer uses
    src. A module seam for the race tests."""
    if _LINK_MOVE:
        os.link(src, dst)
        os.unlink(src)
    else:
        os.rename(src, dst)


def _capture(p: Path, aside: Path) -> None:
    """Move the PUBLIC name aside: ONE os.rename on every platform, atomic.
    Never _move: on POSIX that is link + unlink BY NAME, and a writer's
    replace landing between the two would be unlinked (the RM-816 verifier
    find). This rename can only replace the reaper's own pid-scoped aside
    name (POSIX), never a writer's file; Windows refuses even that. A
    module seam for the race tests."""
    os.rename(p, aside)


def _drop(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def _put_back(aside: Path, p: Path) -> None:
    """A captured row goes back under its own name, create-only. A target
    that exists again is a writer's row written after the capture, so the
    aside is the older copy and is dropped."""
    try:
        _move(aside, p)
    except FileExistsError:
        _drop(aside)


def _swap_if_unchanged(p: Path, data: bytes, raw: bytes, sig) -> bool:
    """RM-816: replace p with data only if p still holds what the reaper
    classified, with no window in which a writer's write can be lost.
    1. capture: rename p aside (_capture, atomic). A writer write after this
       creates p again, and nothing the reaper does next can overwrite it.
    2. compare the ASIDE (a private name: no writer races it). A change means
       a writer landed before the capture: put it back, return False.
    3. commit create-only. A writer that came back after the capture owns p,
       so the move is refused and the writer wins (False).
    The compare on p first is only a cheap early-out, retried with the
    capture when a polling reader share-locks the file (PermissionError)."""
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    aside = p.with_name(f"{p.name}.{os.getpid()}.reap")
    try:
        tmp.write_bytes(data)
        for attempt in range(6):
            if not _unchanged(p, raw, sig):
                return False
            try:
                _capture(p, aside)
                break
            except (FileNotFoundError, FileExistsError):
                return False
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
        if not _unchanged(aside, raw, sig):
            _put_back(aside, p)
            return False
        try:
            _move(tmp, p)
        except FileExistsError:
            _drop(aside)                # a writer's newer row owns p
            return False
        except OSError:
            _put_back(aside, p)
            raise
        _drop(aside)                    # the classified row, now superseded
        return True
    finally:
        _drop(tmp)


def _mark_failed(path: Path, expected_raw: bytes, expected_sig, reason: str,
                 now: float) -> bool:
    """Rewrite one live row as failed in the kit's close_progress() shape
    (every field kept; status, updated and reason set), built from the bytes
    the reaper classified. Compare-and-swap with a create-only commit
    (_swap_if_unchanged, RM-816): a writer that came back at any point wins
    and False is returned (RM-785 (a) left the replace call itself open)."""
    doc = json.loads(expected_raw.decode("utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("status") not in LIVE_STATUSES:
        return False
    doc.update(status="failed", updated=_iso_local(now), reason=reason)
    data = json.dumps(doc, ensure_ascii=True).encode("ascii")
    return _swap_if_unchanged(path, data, expected_raw, expected_sig)


def _recover_asides(d: Path, entries: list, apply: bool, held) -> bool:
    """RM-816: an aside left by a pass that died between its capture and its
    commit goes back under its own name while that name is still free (apply
    only). A target that exists again is a writer's newer row: the aside is
    reported and left as is. True when anything was moved back."""
    moved = False
    for a in entries:
        m = ASIDE_RE.match(a.name)
        if not m or not _plain_file(a):
            continue
        if not apply:
            held(a.name, "aside of an earlier reaper pass; an applying pass moves it back")
            continue
        try:
            _move(a, d / m.group(1))
            moved = True
        except FileExistsError:
            held(a.name, "aside of an earlier reaper pass; its target was rewritten, left as is")
        except OSError as exc:
            held(a.name, f"aside of an earlier reaper pass; not moved back ({type(exc).__name__})")
    return moved


def reap(*, progress_dir=PROGRESS_DIR, root=None, now=None, apply=False, recycle=None,
         alive=None, keep=KEEP_GLOBS, prune_age_s=PRUNE_AGE_S) -> dict:
    """RM-728: mark abandoned live rows failed and move old finished rows to
    the Recycle Bin. Plan-only (changes nothing) unless apply=True. Touches
    only top-level *.json regular files that carry the ownership marker
    ("task" == the file stem, a kit task stem) and are not kept by name."""
    now = time.time() if now is None else float(now)
    recycle = _recycle_default if recycle is None else recycle
    alive = _alive_default if alive is None else alive
    root_p = main_root() if root is None else Path(root).resolve()
    d = Path(progress_dir).resolve()
    rep = {"apply": bool(apply), "now": now, "root": str(root_p), "progress_dir": str(d),
           "dir_state": "ok", "marked": [], "would_mark": [], "recycled": [],
           "would_recycle": [], "held": [], "refused": [], "ignored": 0,
           "halted": None, "exit_code": 0}

    def held(name, why):
        rep["held"].append({"file": name, "why": _ascii(why)[:160]})

    if not _inside(d, root_p):
        rep["dir_state"] = "refused"
        rep["exit_code"] = EXIT_REFUSED
        return rep
    if not d.is_dir():
        rep["dir_state"] = "missing"
        return rep
    try:
        entries = sorted(d.iterdir(), key=lambda q: q.name)
    except OSError:
        rep["dir_state"] = "unreadable"
        return rep
    if _recover_asides(d, entries, apply, held):
        try:
            entries = sorted(d.iterdir(), key=lambda q: q.name)
        except OSError:
            rep["dir_state"] = "unreadable"
            return rep
    for p in entries:
        name = p.name
        if ASIDE_RE.match(name):
            continue                                # reported by _recover_asides
        if not name.endswith(".json"):
            rep["ignored"] += 1                     # not a progress record: not ours
            continue
        stem = name[:-len(".json")]
        folded = name.casefold()            # RM-785 (c): NTFS names are case-blind
        if any(fnmatch.fnmatchcase(folded, g.casefold()) for g in keep):
            held(name, "kept by name (read by its consumer)")
            continue
        if not TASK_STEM.match(stem):
            held(name, "not a kit task stem")
            continue
        if not _plain_file(p):
            held(name, "not a regular file")
            continue
        try:
            st = os.lstat(p)                # BEFORE the read (see _unchanged)
            raw = p.read_bytes()
            doc = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            held(name, f"unreadable ({type(exc).__name__})")
            continue
        sig, mtime = (st.st_mtime_ns, st.st_size), st.st_mtime
        if not isinstance(doc, dict) or doc.get("task") != stem:
            held(name, "no ownership marker (its task field is not the file stem)")
            continue
        try:
            row = classify(doc, now)
        except ValueError as exc:
            held(name, f"not a progress record ({exc})")
            continue

        if row["status"] in LIVE_STATUSES:
            if row["verdict"] not in REAP_VERDICTS:
                continue
            # RM-785 (b): the kit's progress_abandoned() - a live row is
            # abandoned only when its owner is PROVEN dead or it has been
            # silent past ABANDON_S. An unknown owner (no owner field, or a
            # probe that cannot tell) is held like a live one until then: a
            # long step past 2x its ETA is a STALE report, not a failure.
            owner_state = alive(doc.get("owner"))
            if owner_state is not False and row["age_s"] <= OWNER_ALIVE_GRACE_S:
                held(name, "owner alive, inside the kit's abandon grace"
                     if owner_state is True else
                     "owner unknown, inside the kit's abandon grace")
                continue
            reason = _ascii(f"reaped by progress_watch: silent {_age_phrase(row['age_s'])}, "
                            f"past 2x eta {row['eta_used']}s"
                            + ("; owner dead" if owner_state is False
                               else "; past the abandon grace"))[:REASON_MAX]
            if not apply:
                rep["would_mark"].append(stem)
                continue
            try:
                ok = _mark_failed(p, raw, sig, reason, now)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                held(name, f"mark failed did not write ({type(exc).__name__})")
                continue
            if ok:
                rep["marked"].append(stem)
            else:
                held(name, "changed since read; left to its writer")
            continue

        ts = parse_updated(doc.get("updated"))
        if ts is None:
            held(name, "finished but 'updated' is unparseable")
            continue
        if now - max(ts, mtime) <= prune_age_s:     # BOTH clocks must be old
            continue
        if not apply:
            rep["would_recycle"].append(stem)
            continue
        if not _unchanged(p, raw, sig):             # immediately before the act
            held(name, "changed since read; left to its writer")
            continue
        res = recycle(p)
        detail = _ascii(getattr(res, "detail", ""))[:200]
        if getattr(res, "ok", False):
            rep["recycled"].append(stem)
        elif getattr(res, "nuked", False):
            rep["halted"] = f"{name}: {detail}"
            rep["exit_code"] = EXIT_HALTED
            break
        else:
            rep["refused"].append({"file": name, "detail": detail})
    return rep


def format_reap(rep: dict) -> str:
    mode = "apply" if rep["apply"] else "plan only"
    lines = [f"progress_watch reaper ({mode}): dir {rep['dir_state']}; "
             f"marked {len(rep['marked'])}, recycled {len(rep['recycled'])}, "
             f"would mark {len(rep['would_mark'])}, would recycle "
             f"{len(rep['would_recycle'])}, held {len(rep['held'])}, "
             f"refused {len(rep['refused'])}, ignored {rep['ignored']}"]
    if rep["dir_state"] == "refused":
        lines.append(f"  REFUSED: {rep['progress_dir']} is not inside {rep['root']}")
    lines += [f"  marked failed: {s}" for s in rep["marked"]]
    lines += [f"  would mark failed: {s}" for s in rep["would_mark"]]
    lines += [f"  recycled: {s}" for s in rep["recycled"]]
    lines += [f"  would recycle: {s}" for s in rep["would_recycle"]]
    lines += [f"  held: {h['file']} - {h['why']}" for h in rep["held"]]
    lines += [f"  refused: {r['file']} - {r['detail']}" for r in rep["refused"]]
    if rep["halted"]:
        lines.append(f"  HALTED (file left the dir but is not in the bin): {rep['halted']}")
    return "\n".join(_ascii(line) for line in lines)


def main(argv=None, now=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--dir", type=Path, default=None,
                    help="progress dir (default: the MAIN checkout's ops/loop/control/progress)")
    ap.add_argument("--root", type=Path, default=None,
                    help="repo root the reaped dir must sit inside (default: the MAIN checkout)")
    ap.add_argument("--state", type=Path, default=STATE_PATH)
    ap.add_argument("--dry-run", action="store_true",
                    help="classify only: send nothing, write no state; forces --reap plan-only")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("-k", type=int, default=SELF_CHECK_K)
    ap.add_argument("--reap", action="store_true",
                    help="RM-728 reaper pass first; plan only unless --apply")
    ap.add_argument("--apply", action="store_true",
                    help="with --reap: mark abandoned rows failed, recycle old finished rows")
    a = ap.parse_args(argv)
    if a.apply and not a.reap:
        ap.error("--apply needs --reap")
    root = main_root() if a.root is None else a.root.resolve()
    pdir = root / PROGRESS_REL if a.dir is None else a.dir
    reaped = None
    if a.reap:
        reaped = reap(progress_dir=pdir, root=root, now=now,
                      apply=a.apply and not a.dry_run)
    rep = run(progress_dir=pdir, state_path=a.state, now=now, dry_run=a.dry_run,
              k=max(1, a.k))
    if reaped is not None:
        rep["reap"] = reaped
    if a.json:
        print(json.dumps(rep, indent=1, ensure_ascii=True))
    else:
        print(format_report(rep) if reaped is None
              else format_reap(reaped) + "\n" + format_report(rep))
    return reaped["exit_code"] if reaped and reaped["exit_code"] else rep["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
