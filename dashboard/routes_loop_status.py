# arch: GET /api/loop-status (headless-loop progress surface) | section=dashboard | frozen=no
"""GET /api/loop-status - at-a-glance headless-loop progress for mobile.

A thin, additive, read-only aggregator over the headless-loop control files
(``ops/loop/control/*``, written by ``ops/loop/loop_controller.py`` +
``ops/loop/done_sentinel.py``) plus the last git commit. NO engine math, NO
new dependency, NO writes - it only reads. Surfaced as a SETTINGS card so the
operator can watch a Gemini-directed loop from the phone over Tailscale
(https://legion-rc:8888 -> Settings) without shelling into Legion.

Sources (each read is individually fail-soft -> None / [] on any error):

  STOP            present => the loop halted; the file body is the reason.
  cycle.txt       the current cycle number (controller writes it per cycle;
                  a fresh loop init unlinks it, so absent == never-started).
  claude.done     transient JSON the executor writes as its LAST cycle step
                  ({cycle, sha, tests_pass, regressions, ts}); the controller
                  unlinks it after consuming, so it is usually ABSENT at rest.
  controller.log  append log; the "claude.done sha=..." lines are the durable
                  per-cycle summary fallback when the sentinel is gone.
  budget.json     {gemini_usd, gemini_ceiling, claude_usd_info, cycle}.
  ahk_mode.txt    live | dry.
  config.json     max_cycles (the run ceiling, for "cycle N / max").

State (derived, never trusted from a single field):
  stopped  STOP file exists (stop_reason = its text).
  running  no STOP and cycle.txt is present.
  idle     neither (never started or cleaned).

Mission Control S4 adds two LOCK blocks. Both answer FREE / RUNNING /
RECLAIMABLE and both decide by PROBING the pid, never by stat-ing the file - a
lock whose holder is dead is indistinguishable from a live one by file
inspection alone (measured: control/RUNNING.lock carried pid 9380, long gone).
RECLAIMABLE must never render as RUNNING.

  lanes            ops/loop/lanes.lane_state() over control/lanes/0.lock - the
                   mutual-exclusion lock for the six headless lanes (S1).
  controller_lock  the same three-state probe over control/RUNNING.lock, the
                   loop controller's own single-flight lock. Separate file,
                   separate lifetime; it is what makes the stale-lock case
                   visible today, since the lanes dir does not exist until the
                   first lane fires.

READS DO NOT WRITE. This is the dashboard poll path (every 4s). Nothing here
creates the lanes dir, clears a stale lock or touches control/ in any way -
reclaiming is a deliberate act inside try_acquire_lane, never a side effect of
rendering. Pinned by test_poll_path_writes_nothing.

Response (always HTTP 200 unless an unexpected top-level error -> 500):
  {
    "ok": true,
    "state": "stopped|running|idle",
    "stop_reason": <str|null>,
    "mode": <str|null>,
    "cycle": <int|null>,
    "max_cycles": <int|null>,
    "last_done": {"cycle","sha"(8),"tests_pass","regressions","ts","source"} | null,
    "budget": {<budget.json dict>} | null,
    "last_commit": {"sha","subject","iso"} | null,
    "lanes": {"state","lane","pid","run_id","worktree","age_s"} | null,
    "controller_lock": {"state","pid","run_id","age_s"} | null,
    "log_tail": [<str>, ...],
    "updated_at": <iso8601 Z>
  }
"""
from __future__ import annotations

import importlib
import json
from dashboard._errors import send_error
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dashboard._dispatch import equals

log = logging.getLogger("rc.web_dashboard")

ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = ROOT / "ops" / "loop" / "control"
CONFIG_PATH = ROOT / "ops" / "loop" / "config.json"
CONTROLLER_LOG = CONTROL_DIR / "controller.log"

# Tail length for the controller.log preview (newest LOG_TAIL_LINES lines).
LOG_TAIL_LINES = 12

# "... cycle 10: claude.done sha=38158e1d tests=7024 regress=False"
_DONE_LOG_RE = re.compile(
    r"cycle\s+(\d+):\s+claude\.done\s+sha=(\w+)\s+tests=(\S+)\s+regress=(\w+)"
)


# --------------------------------------------------------------------------- fail-soft IO
def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path):
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw.strip())
    except (ValueError, AttributeError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- git seam (monkeypatched in tests)
# Spawning git (a console app) from pythonw.exe pops a console window unless we
# suppress it. /api/loop-status is polled every 4s by the loop-monitor page, so
# an unsuppressed window steals desktop focus on every poll. CREATE_NO_WINDOW
# (Windows only; 0 elsewhere) mirrors the dashboard/server.py vision-spawn idiom.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def _last_commit() -> dict | None:
    """The repo HEAD as {sha(8), subject, iso}. Fail-soft to None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-1", "--format=%h%x1f%s%x1f%cI"],
            capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        line = (out.stdout or "").strip()
        if not line:
            return None
        parts = line.split("\x1f")
        if len(parts) < 3:
            return None
        return {"sha": parts[0], "subject": parts[1], "iso": parts[2]}
    except Exception as exc:  # noqa: BLE001 - git env is heterogeneous; never fatal
        log.warning("loop-status: last_commit failed: %s", exc)
        return None


# --------------------------------------------------------------------------- last-cycle summary
def _last_done() -> dict | None:
    """Prefer the live claude.done sentinel; fall back to the controller.log."""
    sentinel = _read_json(CONTROL_DIR / "claude.done")
    if isinstance(sentinel, dict):
        return {
            "cycle": sentinel.get("cycle"),
            "sha": str(sentinel.get("sha") or "")[:8],
            "tests_pass": sentinel.get("tests_pass"),
            "regressions": bool(sentinel.get("regressions")),
            "ts": sentinel.get("ts"),
            "source": "sentinel",
        }
    log_text = _read_text(CONTROLLER_LOG)
    if not log_text:
        return None
    matches = list(_DONE_LOG_RE.finditer(log_text))
    if not matches:
        return None
    m = matches[-1]  # newest completed cycle
    return {
        "cycle": int(m.group(1)),
        "sha": m.group(2)[:8],
        "tests_pass": m.group(3),
        "regressions": m.group(4).strip().lower() == "true",
        "ts": None,
        "source": "log",
    }


# --------------------------------------------------------------------------- lock states (S4)
# S1 owns ops/loop/lanes.py. Late-bound exactly as routes_loop_control does, so
# this read-only route stays importable when lanes.py is absent - the loop
# status must not go down with the lane lock.
_LANES_MODULE = "ops.loop.lanes"

# None means "take the lanes.py contract default" - see _lane_lock. Tests
# redirect it at a tmp dir; production never sets it.
LANES_ROOT = None

# The loop controller's own single-flight lock. Different file, different owner
# and different lifetime from the lane lock; both are reported, never merged.
CONTROLLER_LOCK_NAME = "RUNNING.lock"


def controller_lock_path() -> Path:
    """Resolved at CALL time off CONTROL_DIR, never bound at import.

    A module-level `CONTROL_DIR / name` constant would ignore a monkeypatched
    CONTROL_DIR, so the test sandbox would silently read the operator's real
    control dir and the suite would pass while measuring the wrong file.
    """
    return CONTROL_DIR / CONTROLLER_LOCK_NAME


def _lanes():
    cached = sys.modules.get(_LANES_MODULE)
    if cached is not None:
        return cached
    return importlib.import_module(_LANES_MODULE)


def _lane_lock() -> dict | None:
    """`lane_state()` for the six-lane mutex, or None when S1 is unavailable.

    Reads only. `lane_state` is documented never to mutate, and `lock_path`
    creates nothing, so polling this leaves control/ byte-identical.

    LANES_ROOT stays None in production: the contract default IS
    ops/loop/control/lanes, and passing it explicitly here would let this route
    and POST /api/loop-control drift onto two different lock dirs. That seam was
    flagged as unpinned in the plan; it is pinned by
    test_status_and_control_share_one_lane_root.
    """
    try:
        return dict(_lanes().lane_state(root=LANES_ROOT))
    except Exception as exc:  # noqa: BLE001 - a missing/broken S1 must not 500 the poll
        log.warning("loop-status: lane_state failed: %s", exc)
        return None


def _controller_lock() -> dict | None:
    """FREE / RUNNING / RECLAIMABLE for control/RUNNING.lock.

    Same rule as the lane lock: the verdict comes from probing the recorded pid.
    A lock whose holder is gone reads RECLAIMABLE, never RUNNING - collapsing
    the two is what made a dead loop report as live.
    """
    try:
        lanes = _lanes()
    except Exception as exc:  # noqa: BLE001
        log.warning("loop-status: lanes import failed: %s", exc)
        return None
    lock = controller_lock_path()
    free = {"state": lanes.FREE, "pid": None, "run_id": None, "age_s": None}
    if not lock.exists():
        return free
    rec = _read_json(lock)
    rec = rec if isinstance(rec, dict) else {}
    try:
        pid = int(rec.get("pid"))
    except (TypeError, ValueError):
        pid = None
    ts = rec.get("ts")
    try:
        ts = float(ts)
    except (TypeError, ValueError):
        try:
            ts = lock.stat().st_mtime
        except OSError:
            ts = None
    out = {
        "state": lanes.RUNNING,
        "pid": pid,
        "run_id": (None if rec.get("run_id") is None else str(rec["run_id"])),
        "age_s": None if ts is None else max(0.0, time.time() - ts),
    }
    if pid is None:
        # Unreadable holder: presumed live only inside the write grace window,
        # the same tolerance lanes.py applies to a half-written lock.
        if out["age_s"] is not None and out["age_s"] > lanes.WRITE_GRACE_S:
            out["state"] = lanes.RECLAIMABLE
    elif not lanes.slots.pid_alive(pid):
        out["state"] = lanes.RECLAIMABLE
    return out


# --------------------------------------------------------------------------- builder
def build_loop_status() -> dict:
    stop_exists = (CONTROL_DIR / "STOP").exists()
    stop_reason = (_read_text(CONTROL_DIR / "STOP") or "").strip() or None
    cycle = _parse_int(_read_text(CONTROL_DIR / "cycle.txt"))

    if stop_exists:
        state = "stopped"
    elif cycle is not None:
        state = "running"
    else:
        state = "idle"

    mode = (_read_text(CONTROL_DIR / "ahk_mode.txt") or "").strip() or None

    budget_raw = _read_json(CONTROL_DIR / "budget.json")
    budget = budget_raw if isinstance(budget_raw, dict) else None

    config_raw = _read_json(CONFIG_PATH)
    max_cycles = None
    if isinstance(config_raw, dict) and isinstance(config_raw.get("max_cycles"), int):
        max_cycles = config_raw["max_cycles"]

    log_text = _read_text(CONTROLLER_LOG)
    log_tail = log_text.splitlines()[-LOG_TAIL_LINES:] if log_text else []

    try:
        last_commit = _last_commit()
    except Exception as exc:  # noqa: BLE001 - the seam must never break the route
        log.warning("loop-status: last_commit raised: %s", exc)
        last_commit = None

    return {
        "ok": True,
        "state": state,
        "stop_reason": stop_reason,
        "mode": mode,
        "cycle": cycle,
        "max_cycles": max_cycles,
        "last_done": _last_done(),
        "budget": budget,
        "last_commit": last_commit,
        "lanes": _lane_lock(),
        "controller_lock": _controller_lock(),
        "log_tail": log_tail,
        "updated_at": _now_iso(),
    }


def _serve_loop_status(h) -> None:
    """GET /api/loop-status handler."""
    try:
        payload = build_loop_status()
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - last-resort guard
        log.warning("api/loop-status: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/loop-status"), _serve_loop_status),
]

POST_ROUTES: list = []
