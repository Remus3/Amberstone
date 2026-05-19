"""Internal: shared constants, leaf helpers, and the module logger for
the Phase 3 supervisor.

Behavior-preserving split (s243) of agents/supervisor.py - see that
module's split note. Leaf module: depends only on the stdlib. Do NOT add
imports of agents.supervisor / _supervisor_http / _supervisor_ephemeral
here - that would create a cycle. The public surface is re-exported by
agents.supervisor; import from there (not this module) in tests/callers.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = _PROJECT_ROOT / "agents" / "state"
LOCKFILE = STATE_DIR / "lockfile"
WEB_ROOT = _PROJECT_ROOT / "web"
LOG_ROOT = _PROJECT_ROOT / "logs" / "agents"

WS_PORT = 8891
WEB_PORT = 8890
HEARTBEAT_INTERVAL = 5.0
SMB_TARGET = "192.168.8.237"

# AUDIT P-audit3-h03 (2026-04-22): pin the framework version the code
# was built against. On startup, resolved_decisions.json must match.
# Bump this constant whenever resolved_decisions.json version increments
# AND the code has been updated to honour the new contract.
EXPECTED_DECISIONS_VERSION = "phase3-1.1"

AGENT_MODELS = {
    "2": "claude-sonnet-4-6",
    "3": "claude-sonnet-4-6",
    "4": "claude-sonnet-4-6",
    "5": "claude-sonnet-4-6",
    "6": "claude-opus-4-7",
    "7": "claude-haiku-4-5",
}

# Where each agent's charter lives. Loaded and passed via
# --append-system-prompt at spawn time. Missing charters are non-fatal -
# the agent still spawns with just its model; we log a WARNING.
AGENT_CHARTERS = {
    "2": _PROJECT_ROOT / "agents" / "agent2_backend" / "charter.md",
    "3": _PROJECT_ROOT / "agents" / "agent3_testing" / "charter.md",
    "4": _PROJECT_ROOT / "agents" / "agent4_coach_mentor" / "charter.md",
    "5": _PROJECT_ROOT / "agents" / "agent5_ui" / "charter.md",
    "6": _PROJECT_ROOT / "agents" / "agent6_auditor" / "charter.md",
    "7": _PROJECT_ROOT / "agents" / "agent7_context" / "charter.md",
}

# Spawn defaults (tunable per-task via payload["spawn_budget_usd"] /
# payload["spawn_timeout_sec"]).
DEFAULT_SPAWN_BUDGET_USD = 2.0
DEFAULT_SPAWN_TIMEOUT_SEC = 900   # 15 min
CLAUDE_CLI = "claude"

# Agent 7 charter: "Warm ends when UI closes". A brief grace after the
# last /push subscriber disconnects so tab refreshes don't flush the
# conversation context.
WARM_UI_CLOSE_GRACE_SEC = 300         # 5 min
WARM_UI_CHECK_INTERVAL_SEC = 30

# Agent 4 charter: "runs at system idle (not in-game, not in champ
# select) - ≥2 minutes idle". We auto-schedule an analyzer run this
# long after a game ends so adaptation_buckets absorb the newest match.
IDLE_ANALYZE_SEC = 120

# Op allowlist for the dispatch loop: these run through the deterministic
# handler regardless of the owner_agent field. Keeps the audit trail
# honest (owner_agent records who *owns* the work) without accidentally
# spawning an LLM for a pure-Python operation.
DETERMINISTIC_OPS = frozenset({
    "game-summary",       # agent 2 in charter, but consumer is plain Python
    "ui-proposal",        # round 42 - agent7 sim-mode UI feedback applier
})

# Round 43: explicit allowlist of op names that may reach the
# deterministic path without a dedicated in-process handler. They fall
# into two categories:
#   1. Notifications / record-keeping tasks (advisories, user notes)
#      that exist to produce audit trail + dashboard visibility; the
#      act of filing IS the work.
#   2. Real ops that have handlers registered in ``_run_deterministic``.
# Anything outside this set hitting the deterministic path is a bug -
# almost certainly Agent 7's LLM fallback fabricating a free-form op
# name. Fail loudly so the UI surfaces the problem instead of showing
# a completed-but-no-op task.
_DETERMINISTIC_HANDLED_OPS = frozenset({
    "game-summary",
    "ui-proposal",
})
_DETERMINISTIC_RECORDKEEPING_OPS = frozenset({
    "cold-streak-advisory",
    "coaching-insight-advisory",
    "user-note",
    "user-direct-order",
    "user-destructive-request",
    "user-unparsed",
    "ui-feedback-unhandled",
    "bridge-publisher-stale",   # Audit7 H-01 - filing IS the alarm
})

# Audit7 H-01 (2026-05-18) - bridge health-publisher staleness alarm.
# Peers POST their watcher heartbeat ~every 60s to /api/health/peer/<node>,
# persisted at ops/runtime/peer_health/<node>.json. When that file goes
# silent the bridge *task loop* may still be alive (only the publisher
# sub-process died) - a false-confidence shape the rc_facts probe
# rendered but nothing escalated (2026-05-18: gamepc silent ~2.7h while
# peer was fresh at 25s). The watchdog files a deduped Agent-1 triage
# task on threshold cross.
_BRIDGE_PUB_PEERS = ("gamepc", "peer")
_BRIDGE_PUB_ALERT_S = 1800.0            # 30 min silent → escalate
_BRIDGE_PUB_CHECK_INTERVAL_S = 300.0    # poll cadence (publisher posts ~60s)
_BRIDGE_PUB_REFILE_COOLDOWN_S = 21600.0  # one task per node per 6h outage


def _bridge_pub_should_file(
    age_s: float,
    prev_fired_mono: "float | None",
    now_mono: float,
    *,
    alert_s: float = _BRIDGE_PUB_ALERT_S,
    cooldown_s: float = _BRIDGE_PUB_REFILE_COOLDOWN_S,
) -> "tuple[bool, bool]":
    """Pure dedup decision for the bridge-publisher watchdog (Audit7
    H-01). Returns ``(should_file, rearm)``:

      - healthy (age <= alert): ``(False, True)`` - publisher recovered;
        clear the node's fired_at so a fresh outage re-alarms.
      - stale, within re-file cooldown of the last filing: ``(False, False)``
      - stale, never filed or cooldown elapsed: ``(True, False)``
    """
    if age_s <= alert_s:
        return (False, True)
    if prev_fired_mono is not None and (now_mono - prev_fired_mono) < cooldown_s:
        return (False, False)
    return (True, False)


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Captured once at module import (~process start for `python -m
# agents.supervisor`). The 5s heartbeat (refresh_lock) re-stamps this
# value UNCHANGED so _Phase3Watcher in ops/rc_supervisor.py can compare
# it against the import-chain mtimes and auto-restart a supervisor that
# is serving stale code after a deploy - the 2026-05-17 incident, where
# a ~27h-old process never picked up keystone 3eb2e2d and silently
# broadcast un-mirrored WS health.
_STARTED_AT: str = _iso_now()


# AUDIT 2026-04-28 (P-audit4-m03): patterns for secret-shaped substrings
# that should never land in a per-task log. Conservative - false positives
# are fine, missing a real key is not.
_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)ANTHROPIC_API_KEY\s*[:=]\s*\S+"),
    re.compile(r"(?i)api[_\-]?key[\"'\s:=]+[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-]{20,}"),
)


def _redact_secrets(s: str) -> str:
    """Replace secret-shaped substrings with [REDACTED-SECRET]. Idempotent.
    Empty/non-str inputs pass through untouched."""
    if not isinstance(s, str) or not s:
        return s or ""
    for p in _SECRET_PATTERNS:
        s = p.sub("[REDACTED-SECRET]", s)
    return s


def _build_logger() -> logging.Logger:
    lg = logging.getLogger("supervisor")
    if lg.handlers:
        return lg
    lg.setLevel(logging.INFO)
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(
        LOG_ROOT / "supervisor.log", maxBytes=3 * 1024 * 1024, backupCount=3, encoding="utf-8",
    )
    h.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    lg.addHandler(h)
    # Also to stderr for foreground runs.
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    lg.addHandler(sh)
    # T3 #15 follow-on (2026-05-01): also route rc.* loggers (decision_detector,
    # liveclient_cache, etc.) into supervisor.log when those modules run inside
    # this process. Same handler instances - Python's logging.Handler.emit holds
    # a per-handler lock so concurrent writes interleave safely.
    rc_lg = logging.getLogger("rc")
    if not rc_lg.handlers:
        rc_lg.setLevel(logging.INFO)
        rc_lg.addHandler(h)
        rc_lg.addHandler(sh)
    return lg


log = _build_logger()


# -------- PID lock ----------------------------------------------------

def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        # On Windows os.kill raises on many cases; fall back to tasklist.
        if sys.platform.startswith("win"):
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", f"PID eq {pid}"], text=True, timeout=5,
                )
                return str(pid) in out
            except (subprocess.SubprocessError, OSError):
                return False
        return False
    return True


def acquire_lock() -> bool:
    """Acquire the supervisor singleton lock.

    Audit L1: avoid TOCTOU by using ``O_CREAT|O_EXCL`` on a sentinel file
    for the claim step, then writing the metadata to the real lockfile.
    Stale sentinels (dead pid) are reclaimed after the exclusive-create
    fails.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    sentinel = STATE_DIR / "lockfile.sentinel"

    def _write_lock_metadata() -> None:
        LOCKFILE.write_text(
            json.dumps({
                "pid": os.getpid(),
                "started_at": _STARTED_AT,
                "host": socket.gethostname(),
            }),
            encoding="utf-8",
        )

    # Try exclusive-create first.
    try:
        fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        _write_lock_metadata()
        return True
    except FileExistsError:
        pass

    # Sentinel exists - check if the owning pid is still alive.
    try:
        prior_pid = int(sentinel.read_text(encoding="ascii").strip() or "0")
    except (OSError, ValueError):
        prior_pid = 0

    if prior_pid and _pid_alive(prior_pid):
        log.error("another supervisor is alive (pid=%s) - aborting", prior_pid)
        return False

    # Stale sentinel - reclaim atomically.
    log.warning("reclaiming stale lock from pid=%s", prior_pid)
    try:
        sentinel.unlink()
    except OSError:
        pass
    try:
        fd = os.open(str(sentinel), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
    except FileExistsError:
        log.error("lost race to another reclaiming starter")
        return False
    _write_lock_metadata()
    return True


def _verify_decisions_version() -> None:
    """AUDIT P-audit3-h03 (2026-04-22): fail closed if
    ``agents/state/resolved_decisions.json`` version drifts from the
    constant this codebase was built against. Stops accidental
    downgrade or hand-edit from booting silently.
    """
    path = STATE_DIR / "resolved_decisions.json"
    if not path.exists():
        raise RuntimeError(
            f"resolved_decisions.json missing at {path} - run "
            "`python ops/phase3_setup.py` to restore"
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"resolved_decisions.json is malformed JSON: {e}"
        ) from e
    actual = str(data.get("version") or "")
    if actual != EXPECTED_DECISIONS_VERSION:
        raise RuntimeError(
            f"resolved_decisions.json version mismatch - "
            f"expected {EXPECTED_DECISIONS_VERSION!r}, got {actual!r}. "
            "Either update the code to honour the new contract, or "
            "restore the decisions file from backup."
        )


def _port_available(host: str, port: int) -> bool:
    """Audit L2: quick TCP bind check so supervisor fails with a clear message
    rather than raising deep inside an asyncio serve() call."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        return False
    finally:
        sock.close()
    return True


def refresh_lock() -> None:
    if not LOCKFILE.exists():
        LOCKFILE.parent.mkdir(parents=True, exist_ok=True)
    LOCKFILE.write_text(
        json.dumps({
            "pid": os.getpid(),
            "started_at": _STARTED_AT,
            "heartbeat_at": _iso_now(),
            "host": socket.gethostname(),
        }),
        encoding="utf-8",
    )


# -------- cmdkey check ------------------------------------------------

def smb_credential_present(target: str = SMB_TARGET) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        out = subprocess.check_output(
            ["cmdkey", f"/list:{target}"], text=True, timeout=5, stderr=subprocess.STDOUT,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("cmdkey probe failed: %s", e)
        return False
    # Windows English localisation outputs "Target:" when an entry exists.
    return "Target:" in out or "target=" in out.lower()
