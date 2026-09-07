# arch: GET /api/loop-status route table - S10 Task 9 de-registered it from the :8888 dispatch table; only mc/routes.py imports it now (:8895) | section=dashboard | frozen=no
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
  budget.json     {adjudicator, adjudicator_usd, claude_usd_info, cycle} and
                  executor_usd on the sdk channel. The gemini_usd /
                  gemini_ceiling pair was dropped 2026-08-01 with the vendor;
                  a budget.json written by an older run still carries them and
                  readers must treat both as optional.
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

from dashboard._matchers import equals

log = logging.getLogger("rc.web_dashboard")

ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = ROOT / "ops" / "loop" / "control"
CONFIG_PATH = ROOT / "ops" / "loop" / "config.json"
CONTROLLER_LOG = CONTROL_DIR / "controller.log"

# Tail length for the controller.log preview (newest LOG_TAIL_LINES lines).
LOG_TAIL_LINES = 12

# Where lane_launcher._log_path writes one log per lane run.
LANE_LOG_DIR = ROOT / "ops" / "loop" / "reports"
LANE_LOG_TAIL_LINES = 12
# lane_<lane>_<run_id>.log - the lane id may itself contain a hyphen
# ("true-audit"), so the run id is taken as the LAST underscore-separated part
# rather than the second.
_LANE_LOG_RE = re.compile(r"^lane_(?P<rest>.+)_(?P<run>[^_]+)\.log$")

# "... cycle 10: claude.done sha=8474f4b2 tests=7024 regress=False"
_DONE_LOG_RE = re.compile(
    r"cycle\s+(\d+):\s+claude\.done\s+sha=(\w+)\s+tests=(\S+)\s+regress=(\w+)"
)


# --------------------------------------------------------------------------- fail-soft IO
def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _decode_lane_log(raw: bytes) -> str:
    """Decode a lane log, which is legitimately TWO encodings in one file.

    MEASURED on the real file 2026-08-02: `run_lane.ps1` writes its header with
    `Out-File -Encoding utf8` (UTF-8, with a BOM) and the worker's own output
    then arrives through `*>>`, whose default on Windows PowerShell 5.1 is
    UTF-16LE. So a 4298-byte log was UTF-8 for 119 bytes and UTF-16LE for the
    remaining 4179 - 2066 of them NUL. Decoding the whole thing as UTF-8 yields
    "C\\x00y\\x00c\\x00l\\x00e" and puts that in front of the operator.

    The runner has since been fixed to write UTF-8 throughout, but every log
    from before that change still exists and is exactly the one someone reads
    when asking what the last run did, so this stays.

    STRATEGY: drop NUL bytes, then decode the rest as UTF-8 with replacement.

    This looks blunt and is deliberately chosen over splitting the file at its
    encoding boundary. MEASURED against the real log: the boundary approach
    handled the header and the body correctly and then mangled the LAST line
    into CJK (the ASCII byte pairs re-read as CJK code points), because the
    file switches encoding THREE times,
    not once - `Out-File -Encoding utf8` header, `*>>` UTF-16LE body, then an
    `Out-File -Append -Encoding utf8` footer carrying the exit code. Any
    fixed number of segments is a guess about a file whose shape is decided by
    which cmdlet wrote last.

    Stripping NULs has no such assumption. UTF-16LE ASCII is exactly
    "ASCII byte, 0x00" pairs, so removing the NULs yields the original text for
    any number of switches, in any order; UTF-8 regions contain no NULs and are
    passed through untouched.

    The tradeoff, stated rather than hidden: a genuinely non-ASCII character
    inside a UTF-16 region loses its high byte and lands as a replacement
    character. That is acceptable here and nowhere near the common case - the
    repo is 7-bit ASCII by hard rule and lane logs are CLI output - and a
    mangled box-drawing glyph is a far smaller cost than a mangled final line,
    which is the line carrying the exit code.
    """
    if not raw:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    if raw.count(0):
        raw = raw.replace(b"\x00", b"")
    return raw.decode("utf-8", "replace")


def _lane_log() -> dict | None:
    """The tail of the log the operator is most likely asking about.

    Answers the "MC shows nothing new" report: the only log this route exposed
    was the loop CONTROLLER's, which has been stopped since 2026-07-28, so a
    running lane had no surface at all. A lane's own log is the one that moves.

    Selection is HELD-FIRST, newest-by-mtime second. A held lane is what the
    operator is watching; newest is only a fallback for when nothing is running.

    Returns None - never raises - when there is no reports dir, no lane log in
    it, or anything else goes wrong. This is inside a 5s poll.
    """
    try:
        d = LANE_LOG_DIR
        if not d.is_dir():
            return None
        cands = []
        for p in d.iterdir():
            m = _LANE_LOG_RE.match(p.name)
            if not m or not p.is_file():
                continue
            cands.append((p, m.group("rest"), m.group("run")))
        if not cands:
            return None

        held_lane = held_run = None
        lock = _lane_lock()
        if isinstance(lock, dict) and lock.get("state") == "RUNNING":
            held_lane, held_run = lock.get("lane"), lock.get("run_id")

        def rank(item):
            p, lane, run = item
            is_held = (held_lane is not None
                       and lane == held_lane and run == held_run)
            try:
                mtime = p.stat().st_mtime
            except OSError:
                mtime = 0.0
            return (1 if is_held else 0, mtime)

        path, lane, run = max(cands, key=rank)
        try:
            raw = path.read_bytes()
            mtime = path.stat().st_mtime
        except OSError:
            return None
        lines = _decode_lane_log(raw).splitlines()
        tail = lines[-LANE_LOG_TAIL_LINES:]
        return {
            "name": path.name,
            "lane": lane,
            "run_id": run,
            "lines": tail,
            "truncated": len(lines) > len(tail),
            "age_s": max(0.0, time.time() - mtime),
            "held": bool(held_lane is not None and lane == held_lane
                         and run == held_run),
        }
    except Exception as exc:  # noqa: BLE001 - a log preview must never 500 the poll
        log.warning("loop-status: lane_log failed: %s", exc)
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


_LAUNCHER_MODULE = "ops.loop.lane_launcher"


def _lanes_available() -> dict | None:
    """Which lanes exist, and which can actually START (S5).

    The panel renders a button per lane and must grey out the ones with no
    command doc yet. Deriving that list HERE, from the launcher's own map, is
    what keeps the UI honest as S6 and S8 wire the remaining lanes - a
    hardcoded client-side list would drift the moment a lane lands.
    """
    try:
        lanes = _lanes()
    except Exception as exc:  # noqa: BLE001
        log.warning("loop-status: lanes import failed: %s", exc)
        return None
    wired: list = []
    try:
        launcher = sys.modules.get(_LAUNCHER_MODULE) or \
            importlib.import_module(_LAUNCHER_MODULE)
        wired = sorted(getattr(launcher, "LANE_COMMANDS", {}))
    except Exception as exc:  # noqa: BLE001 - an absent launcher means none wired
        log.warning("loop-status: launcher unavailable: %s", exc)
    return {"all": list(getattr(lanes, "LANES", ())), "wired": wired}


_STEER_MODULE = "ops.loop.steer"


def _steer_summary() -> dict | None:
    """Pending steer counts (S7). Read-only - `pending` never writes."""
    try:
        steer = sys.modules.get(_STEER_MODULE) or \
            importlib.import_module(_STEER_MODULE)
        return dict(steer.summary())
    except Exception as exc:  # noqa: BLE001 - an absent channel is not an error
        log.warning("loop-status: steer summary unavailable: %s", exc)
        return None


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
        "lanes_available": _lanes_available(),
        "steer": _steer_summary(),
        "controller_lock": _controller_lock(),
        "log_tail": log_tail,
        # The lane's OWN log. log_tail above is the loop controller's, and the
        # controller has been stopped since 2026-07-28 - so before this field
        # existed a running lane had no surface in Mission Control at all.
        "lane_log": _lane_log(),
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
