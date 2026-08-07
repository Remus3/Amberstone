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
import time
from datetime import datetime, timezone
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env_port(name: str, default: int) -> int:
    """Read an int port from the environment, falling back to ``default``.

    RM-170 (2026-08-06): the ports and the state dir are env-overridable so a
    test can spawn a supervisor on FREE ports with a throwaway state dir while
    the live RC-Phase3-Supervisor still holds :8890/:8891. The DEFAULTS are
    unchanged, so the live supervisor (which sets none of these) behaves
    exactly as before. A malformed value falls back to the default rather than
    crashing the daemon at import time.
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# RM-170: overriding STATE_DIR relocates the lockfile, the lockfile sentinel,
# the orphan-tmp reap glob AND the resolved_decisions.json load together, which
# is exactly the set a hermetic supervisor test has to move as a unit.
STATE_DIR = Path(os.environ.get("RC_PHASE3_STATE_DIR") or (_PROJECT_ROOT / "agents" / "state"))
LOCKFILE = STATE_DIR / "lockfile"
WEB_ROOT = _PROJECT_ROOT / "web"
LOG_ROOT = _PROJECT_ROOT / "logs" / "agents"

# CAUTION: these resolve at IMPORT time, and tests/test_ports.py asserts the
# repo-wide port registry equals these two values. Pass the overrides in a
# CHILD process env (as agent3_testing/suite/test_supervisor.py does); do NOT
# export RC_PHASE3_WEB_PORT / RC_PHASE3_WS_PORT into a pytest process itself,
# or that registry assertion flips repo-wide with no obvious cause.
WS_PORT = _env_port("RC_PHASE3_WS_PORT", 8891)
WEB_PORT = _env_port("RC_PHASE3_WEB_PORT", 8890)
HEARTBEAT_INTERVAL = 5.0
# Legacy 2-PC SMB-push target (Game-PC LAN IP). Retired post-1PC (ADR-011):
# Game-PC is out of the pipeline, so the cross-machine push path is dead and
# this is only read by the no-op smb_credential_present() safeguard. Kept for
# the re-exported surface + tests; do not wire new cross-machine writes to it.
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
# select) - >=2 minutes idle". We auto-schedule an analyzer run this
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
})

# Audit-8 H-02 reconciler: task_queue.jsonl state-machine leak guard.
# Periodic scan closes IN_PROGRESS envelopes that never received a
# terminal event (e.g. supervisor crash mid-dispatch, ephemeral session
# aborted, audit cron exceeded budget). Threshold + interval mirror the
# bridge watchdog cadence so the two background loops co-exist cheaply.
_RECONCILE_INTERVAL_S = 300.0    # 5 min between scans
_RECONCILE_STALE_S = 1800.0      # 30 min before in_progress is considered stale

# Gate-limbo reaper (WP-F5-H02): dead-letter needs_approval / agent0_review
# / retry_pending envelopes that have waited on an external actor far past
# any reasonable window. Generous threshold (7 days) so a genuine pending
# approval is never reaped out from under the operator.
_GATE_LIMBO_STALE_S = 7 * 86400.0   # 7 days


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

def _atomic_write_json(target: Path, obj: object) -> None:
    """Write ``obj`` as JSON to ``target`` atomically (CLAUDE.md hard rule).

    The lockfile is polled by the frozen ``_Phase3Watcher`` in
    ``ops/rc_supervisor.py`` every cycle; a direct ``write_text`` is
    observable mid-write and a torn read decodes as missing_lockfile,
    contributing a spurious unhealthy signal toward a false restart. Write
    to a PID-unique temp in the same dir (so the rename is same-filesystem
    and never collides with a concurrent reclaiming starter), then
    ``os.replace`` - atomic on POSIX and Windows.

    Audit L-02 (2026-07-12): retry ``os.replace`` up to 3 times on transient
    Windows PermissionError (reference_os_replace_winerror5), then always
    unlink the ``.tmp`` sibling via finally so a crash or WinError 5 never
    orphans a per-PID temp file into ``agents/state/``.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    try:
        for attempt in range(3):
            try:
                os.replace(tmp, target)
                return
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.06)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


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
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return str(pid) in out
            except (subprocess.SubprocessError, OSError):
                return False
        return False
    return True


def _reap_orphan_lockfile_tmps() -> None:
    """Delete ``lockfile.<pid>.tmp`` files where ``<pid>`` is not a live process.

    Called once at ``acquire_lock()`` startup. Cleans up tmps orphaned by a
    prior crash or transient WinError 5 before the current supervisor takes
    ownership (audit L-02, 2026-07-12).
    """
    for p in STATE_DIR.glob("lockfile.*.tmp"):
        stem = p.name  # "lockfile.<pid>.tmp"
        parts = stem.rsplit(".", 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[1])
        except ValueError:
            continue
        if not _pid_alive(pid):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


def acquire_lock() -> bool:
    """Acquire the supervisor singleton lock.

    Audit L1: avoid TOCTOU by using ``O_CREAT|O_EXCL`` on a sentinel file
    for the claim step, then writing the metadata to the real lockfile.
    Stale sentinels (dead pid) are reclaimed after the exclusive-create
    fails.
    """
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _reap_orphan_lockfile_tmps()
    sentinel = STATE_DIR / "lockfile.sentinel"

    def _write_lock_metadata() -> None:
        _atomic_write_json(LOCKFILE, {
            "pid": os.getpid(),
            "started_at": _STARTED_AT,
            "host": socket.gethostname(),
        })

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
    _atomic_write_json(LOCKFILE, {
        "pid": os.getpid(),
        "started_at": _STARTED_AT,
        "heartbeat_at": _iso_now(),
        "host": socket.gethostname(),
    })


# -------- cmdkey check ------------------------------------------------

def smb_credential_present(target: str = SMB_TARGET) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        out = subprocess.check_output(
            ["cmdkey", f"/list:{target}"], text=True, timeout=5, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("cmdkey probe failed: %s", e)
        return False
    # Windows English localisation outputs "Target:" when an entry exists.
    return "Target:" in out or "target=" in out.lower()
