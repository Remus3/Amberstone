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
    "log_tail": [<str>, ...],
    "updated_at": <iso8601 Z>
  }
"""
from __future__ import annotations

import json
from dashboard._errors import send_error
import logging
import os
import re
import subprocess
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
