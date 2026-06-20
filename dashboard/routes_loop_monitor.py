# arch: GET /api/loop-monitor (per-tool-call timeline) | section=dashboard | frozen=no
"""GET /api/loop-monitor - per-tool-call timeline for the active session.

The TIMELINE complement to GET /api/loop-status (cycle / budget / state). It
parses the active session transcript JSONL - the very files
``ops/loop/loop_controller.meter()`` reads for billing - and pairs each
``tool_use`` block (in an assistant message) with its later ``tool_result``
block (in a user message) by ``id`` / ``tool_use_id``. The wall-clock duration
of every call is ``result.timestamp - use.timestamp``.

It answers the operator question the loop never surfaced: "this cycle has been
running 30 minutes - WHY?". The ``summary`` collapses repeated calls so a
14-run pytest battery shows as one ``Bash:pytest x14 = 26m`` row (the
"unnecessary test battery" smell), and ``inflight`` lists any ``tool_use`` with
no result yet - the live "stuck on X for Nm" signal.

Read-only, fail-soft, NO engine math, NO writes, NO new dependency. Selection of
the active transcript mirrors loop_controller.session_files(): the pinned
``session_jsonl`` from ops/loop/config.json when set, else the newest top-level
``*.jsonl`` in ``transcript_dir``. Only the main (top-level) transcript is
parsed in v1; a long subagent call appears as one in-flight ``Agent`` row.

Response (always HTTP 200 unless an unexpected top-level error -> 500):
  {
    "ok": true,
    "session": <basename|null>,
    "tool_count": <int>,                       # tool_use events in the window
    "window": {"first_iso": <str|null>, "last_iso": <str|null>},
    "summary": [ {sig, name, count, total_s, max_s, errors} ... ],  # total_s desc
    "recent": [ {name, sig, target, start_iso, duration_s, is_error, inflight} ],
    "inflight": [ {name, sig, target, start_iso, elapsed_s} ... ],
    "updated_at": <iso8601 Z>
  }
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from dashboard._dispatch import equals
from dashboard._errors import send_error

log = logging.getLogger("rc.web_dashboard")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "ops" / "loop" / "config.json"
# Fallback transcript dir when config.json has none (mirrors the live path).
DEFAULT_TRANSCRIPT_DIR = (
    Path.home() / ".claude" / "projects" / "C--Riot-Commander"
)

# Newest-N tool calls returned in `recent`; tail cap so a multi-hour session
# JSONL (tens of MB) never blows memory - the deque keeps only the last lines,
# which is exactly the recent activity the operator is watching.
RECENT_N = 50
MAX_LINES = 8000

# Shell tools whose `command` carries the real signature (so a pytest battery
# is distinguishable from a git/curl run instead of all bucketing as "Bash").
_SHELL = {"Bash", "PowerShell"}
# Checked in order; first substring hit wins. py_compile before python so
# "python -m py_compile" buckets as py_compile, pytest before python likewise.
_KEYWORDS = (
    "pytest", "py_compile", "ruff", "taskkill", "schtasks", "restart_trigger",
    "git", "curl", "python", "node", "npm", "echo",
)


# --------------------------------------------------------------------------- fail-soft IO
def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(s) -> float | None:
    """ISO8601 (e.g. '2026-05-21T19:48:20.881Z') -> epoch seconds. None on junk."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- session selection
def _transcript_dir() -> Path:
    cfg = _read_json(CONFIG_PATH) or {}
    td = cfg.get("transcript_dir")
    return Path(td) if td else DEFAULT_TRANSCRIPT_DIR


def _active_session_path() -> Path | None:
    """Pinned session_jsonl if set+present, else newest top-level *.jsonl.

    Mirrors loop_controller.session_files() selection (top-level only - subagent
    transcripts live under <session>/subagents/ and are excluded in v1)."""
    cfg = _read_json(CONFIG_PATH) or {}
    pin = cfg.get("session_jsonl")
    if pin:
        p = Path(pin)
        if p.exists():
            return p
    try:
        tops = sorted(_transcript_dir().glob("*.jsonl"),
                      key=lambda q: q.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return tops[0] if tops else None


# --------------------------------------------------------------------------- signature / target hints
def _sig(name: str, inp: dict) -> str:
    """A grouping key. Shell tools -> '<name>:<keyword>' so pytest batteries
    cluster; everything else groups by tool name."""
    if name in _SHELL:
        low = str(inp.get("command") or "").lower()
        for kw in _KEYWORDS:
            if kw in low:
                return f"{name}:{kw}"
        tok = low.split()
        return f"{name}:{tok[0]}" if tok else name
    return name


def _target(name: str, inp: dict) -> str:
    """A short human hint of what the call acted on (file / command / pattern)."""
    for k in ("file_path", "pattern", "url", "notebook_path"):
        v = inp.get(k)
        if v:
            return str(v)[:80]
    cmd = inp.get("command")
    if cmd:
        return str(cmd)[:80]
    for k in ("description", "prompt", "query"):
        v = inp.get(k)
        if v:
            return str(v)[:80]
    return ""


# --------------------------------------------------------------------------- builder
def build_loop_timeline(session_path: Path | None = None, *,
                        recent_n: int = RECENT_N, now_ts: float | None = None,
                        max_lines: int = MAX_LINES) -> dict:
    now = now_ts if now_ts is not None else time.time()
    sp = session_path or _active_session_path()
    out = {
        "ok": True,
        "session": (sp.name if sp else None),
        "tool_count": 0,
        "window": {"first_iso": None, "last_iso": None},
        "summary": [],
        "recent": [],
        "inflight": [],
        "updated_at": _now_iso(),
    }
    if not sp or not sp.exists():
        return out

    uses: dict[str, dict] = {}     # id -> {name, sig, target, start_ts, start_iso}
    results: dict[str, dict] = {}  # id -> {end_ts, is_error}
    try:
        with sp.open(encoding="utf-8", errors="replace") as fh:
            lines = deque(fh, maxlen=max_lines)
    except OSError:
        return out

    for line in lines:
        try:
            o = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        m = o.get("message")
        if not isinstance(m, dict):
            continue
        content = m.get("content")
        if not isinstance(content, list):
            continue
        ts = _parse_ts(o.get("timestamp"))
        if ts is None:
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "tool_use":
                tid = b.get("id")
                if not tid:
                    continue
                name = b.get("name") or "?"
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                uses[tid] = {
                    "name": name, "sig": _sig(name, inp), "target": _target(name, inp),
                    "start_ts": ts, "start_iso": o.get("timestamp"),
                }
            elif bt == "tool_result":
                tid = b.get("tool_use_id")
                if tid:
                    results[tid] = {"end_ts": ts, "is_error": bool(b.get("is_error"))}

    calls = []
    for tid, u in uses.items():
        r = results.get(tid)
        if r:
            dur = max(0.0, r["end_ts"] - u["start_ts"])
            inflight, is_err = False, r["is_error"]
        else:
            dur = max(0.0, now - u["start_ts"])
            inflight, is_err = True, False
        calls.append({**u, "duration_s": round(dur, 2),
                      "inflight": inflight, "is_error": is_err})
    calls.sort(key=lambda c: c["start_ts"])

    out["tool_count"] = len(calls)
    if calls:
        out["window"] = {"first_iso": calls[0]["start_iso"],
                         "last_iso": calls[-1]["start_iso"]}

    agg: dict[str, dict] = {}
    for c in calls:
        a = agg.setdefault(c["sig"], {"sig": c["sig"], "name": c["name"],
                                      "count": 0, "total_s": 0.0, "max_s": 0.0,
                                      "errors": 0})
        a["count"] += 1
        a["total_s"] += c["duration_s"]
        a["max_s"] = max(a["max_s"], c["duration_s"])
        if c["is_error"]:
            a["errors"] += 1
    summary = sorted(agg.values(), key=lambda a: a["total_s"], reverse=True)
    for a in summary:
        a["total_s"] = round(a["total_s"], 2)
        a["max_s"] = round(a["max_s"], 2)
    out["summary"] = summary

    out["recent"] = [
        {"name": c["name"], "sig": c["sig"], "target": c["target"],
         "start_iso": c["start_iso"], "duration_s": c["duration_s"],
         "is_error": c["is_error"], "inflight": c["inflight"]}
        for c in reversed(calls[-recent_n:])
    ]
    out["inflight"] = [
        {"name": c["name"], "sig": c["sig"], "target": c["target"],
         "start_iso": c["start_iso"], "elapsed_s": c["duration_s"]}
        for c in calls if c["inflight"]
    ]
    return out


# --------------------------------------------------------------------------- handler
def _serve_loop_monitor(h) -> None:
    """GET /api/loop-monitor handler."""
    try:
        payload = build_loop_timeline()
        h._send(200, json.dumps(payload).encode("utf-8"), "application/json")
    except Exception as exc:  # noqa: BLE001 - last-resort guard, never 500 raw
        log.warning("api/loop-monitor: %s", exc)
        try:
            send_error(h, exc)
        except Exception:  # noqa: BLE001
            pass


GET_ROUTES = [
    (equals("/api/loop-monitor"), _serve_loop_monitor),
]

POST_ROUTES: list = []
