"""Phase 3 supervisor — the single process that owns everything on Legion-PC.

Per §10 responsibilities:

  * Start the WS relay server on 0.0.0.0:8891.
  * Start the web UI HTTP server on 0.0.0.0:8890 (serves ``web/``).
  * Run the async event loop for Agents 0, 1, 3 (pure Python).
  * Spawn ephemeral ``claude`` sessions on Agent 1 dispatches for 2/4/5/6.
  * Maintain a warm Agent 7 session during play windows (stub — warm
    lifecycle hooks are scaffolded here and will be filled by the
    user-context build session).
  * Heartbeat to ``agents/state/lockfile`` every 5 seconds.
  * Verify SMB ``cmdkey`` presence at startup; if absent, log WARNING and
    disable cross-machine dispatch until re-verified.
  * Graceful shutdown on SIGTERM / SIGBREAK.

The process also acquires a PID lock against ``agents/state/lockfile`` —
duplicate launches abort cleanly (matching the existing RC-Supervisor pattern).

This skeleton is intentionally MVP:
  * Ephemeral LLM dispatch is implemented as a subprocess stub that writes
    a ``spawn_claude_<agent>_<task>.log`` file under ``logs/agents/``. The
    charter prompts that each agent gets invoked with are filled in by
    each agent's own build session (they aren't part of this setup task).
  * Deterministic agents (0, 1, 3) run in-process; agents 2/4/5/6 spawn
    subprocess; agent 7 warm-session plumbing is stubbed.

Standalone run:
  python -m agents.supervisor
"""
from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import logging
import logging.handlers
import os
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.agent0_gatekeeper.evaluator import Evaluator, Task as Agent0Task
from agents.agent1_lead.scheduler import Scheduler, TaskStatus
from agents.agent2_backend.db_schema import init_all as init_all_dbs
from lib.modes import verify_modes as _verify_modes
from agents.agent2_backend.db_migrate_kda import ensure_all as _ensure_kda_columns_all
from agents.agent2_backend.file_ingest import FileIngest
from agents.agent2_backend.ws_server import WSServer
from agents.agent7_context.warm_session import (
    WarmAgent7Session,
    WarmSessionError,
    warm_spawn_factory,
)

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
# --append-system-prompt at spawn time. Missing charters are non-fatal —
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
# select) — ≥2 minutes idle". We auto-schedule an analyzer run this
# long after a game ends so adaptation_buckets absorb the newest match.
IDLE_ANALYZE_SEC = 120

# Op allowlist for the dispatch loop: these run through the deterministic
# handler regardless of the owner_agent field. Keeps the audit trail
# honest (owner_agent records who *owns* the work) without accidentally
# spawning an LLM for a pure-Python operation.
DETERMINISTIC_OPS = frozenset({
    "game-summary",       # agent 2 in charter, but consumer is plain Python
    "ui-proposal",        # round 42 — agent7 sim-mode UI feedback applier
})

# Round 43: explicit allowlist of op names that may reach the
# deterministic path without a dedicated in-process handler. They fall
# into two categories:
#   1. Notifications / record-keeping tasks (advisories, user notes)
#      that exist to produce audit trail + dashboard visibility; the
#      act of filing IS the work.
#   2. Real ops that have handlers registered in ``_run_deterministic``.
# Anything outside this set hitting the deterministic path is a bug —
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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Captured once at module import (~process start for `python -m
# agents.supervisor`). The 5s heartbeat (refresh_lock) re-stamps this
# value UNCHANGED so _Phase3Watcher in ops/rc_supervisor.py can compare
# it against the import-chain mtimes and auto-restart a supervisor that
# is serving stale code after a deploy — the 2026-05-17 incident, where
# a ~27h-old process never picked up keystone 3eb2e2d and silently
# broadcast un-mirrored WS health.
_STARTED_AT: str = _iso_now()


# AUDIT 2026-04-28 (P-audit4-m03): patterns for secret-shaped substrings
# that should never land in a per-task log. Conservative — false positives
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
    # this process. Same handler instances — Python's logging.Handler.emit holds
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

    # Sentinel exists — check if the owning pid is still alive.
    try:
        prior_pid = int(sentinel.read_text(encoding="ascii").strip() or "0")
    except (OSError, ValueError):
        prior_pid = 0

    if prior_pid and _pid_alive(prior_pid):
        log.error("another supervisor is alive (pid=%s) — aborting", prior_pid)
        return False

    # Stale sentinel — reclaim atomically.
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
            f"resolved_decisions.json missing at {path} — run "
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
            f"resolved_decisions.json version mismatch — "
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


# -------- Web UI HTTP server -----------------------------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Web handler for the Phase 3 UI.

    Audit L4: deny dotfiles and common secret filenames so a misplaced
    ``.env`` in ``web/`` never reaches the wire, even inside the LAN.

    Added 2026-04-22: ``POST /api/input`` → Agent 7 NL parser. The parser
    files any resulting task via Agent 1's scheduler and returns the
    parse result as JSON.
    """
    _DENYLIST_NAMES = {".env", ".git", ".htpasswd", "secrets.json",
                       "api-key-claude.txt", "credentials.json"}

    def _is_forbidden(self, path: str) -> bool:
        # strip query string
        clean = path.split("?", 1)[0].split("#", 1)[0]
        basename = clean.rsplit("/", 1)[-1].lower()
        if basename.startswith("."):
            return True
        return basename in self._DENYLIST_NAMES

    def do_GET(self) -> None:
        if self._is_forbidden(self.path):
            self.send_error(403, "Forbidden")
            return
        if self.path == "/api/queue":
            return self._handle_queue_snapshot()
        if self.path.startswith("/api/adaptation"):
            return self._handle_adaptation()
        if self.path == "/api/env":
            return self._handle_env()
        if self.path.startswith("/api/minimap-crop"):
            return self._handle_minimap_crop()
        if self.path.startswith("/api/insight-card"):
            return self._handle_insight_card()
        if self.path.startswith("/api/activity"):
            return self._handle_activity()
        if self.path.startswith("/api/task/"):
            return self._handle_task_detail()
        if self.path.startswith("/api/trending"):
            return self._handle_trending()
        if self.path.startswith("/api/session-games"):
            return self._handle_session_games()
        if self.path.startswith("/api/session"):
            return self._handle_session()
        if self.path.startswith("/api/advisories"):
            return self._handle_advisories()
        if self.path.startswith("/api/time-of-day"):
            return self._handle_time_of_day()
        if self.path.startswith("/api/day-of-week"):
            return self._handle_day_of_week()
        if self.path.startswith("/api/duration"):
            return self._handle_duration()
        if self.path.startswith("/api/digest"):
            return self._handle_digest()
        if self.path.startswith("/api/locked-champion"):
            return self._handle_locked_champion()
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._is_forbidden(self.path):
            self.send_error(403, "Forbidden")
            return
        # Route /api/* HEAD through do_GET. Handlers check
        # ``self.command == "HEAD"`` and skip body writes per RFC 7231.
        if self.path.startswith("/api/"):
            return self.do_GET()
        super().do_HEAD()

    def do_POST(self) -> None:
        if self.path == "/api/input":
            return self._handle_input()
        if self.path == "/api/analyze":
            return self._handle_analyze()
        if self.path == "/api/file-task":
            return self._handle_file_task()
        if self.path.startswith("/api/task/") and self.path.endswith("/dismiss"):
            return self._handle_task_dismiss()
        self.send_error(404, "Not Found")

    # ------ API handlers --------------------------------------------
    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        # 256 KiB cap on request body — prevent accidental huge uploads.
        if length <= 0 or length > 256 * 1024:
            return b""
        return self.rfile.read(length)

    def _send_json(self, status: int, obj: Any) -> None:
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle_input(self) -> None:
        t0 = time.monotonic()
        raw = self._read_body()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"bad json: {e}"})
            return
        text = (payload.get("text") or "").strip()
        if not text:
            self._send_json(400, {"error": "missing 'text' field"})
            return

        # Round 42: sim-mode UI-feedback routing. Body carries
        # ``sim_context: true`` + optional ``history`` (last ~5 turns
        # client-side) + ``sim_fixture`` name. When present, the
        # message is scoped strictly to dashboard UI.
        sim_context = bool(payload.get("sim_context"))
        history = payload.get("history") or []
        if not isinstance(history, list):
            history = []
        sim_fixture = (payload.get("sim_fixture") or "").strip() or None

        sup = self.server.supervisor
        warm = sup.warm_agent7
        spawn_fn = spawn_ephemeral_llm
        spawn_path = "ephemeral_cli"
        if warm is not None:
            warm_spawn = warm_spawn_factory(warm)
            def _spawn_with_fallback(agent, task_id, op, pl):
                try:
                    return warm_spawn(agent, task_id, op, pl)
                except WarmSessionError as exc:
                    log.warning("warm session failed, falling back to ephemeral: %s", exc)
                    return spawn_ephemeral_llm(agent, task_id, op, pl)
            spawn_fn = _spawn_with_fallback
            spawn_path = "warm_then_ephemeral"

        if sim_context:
            from agents.agent7_context.ui_feedback import UIFeedbackParser
            ui_parser = UIFeedbackParser(
                scheduler=sup.scheduler, llm_spawn=spawn_fn,
            )
            try:
                ui_result = ui_parser.parse(
                    text, history=history[-5:], sim_fixture=sim_fixture,
                )
            except Exception as e:          # noqa: BLE001
                log.exception("ui_feedback parse raised: %s", e)
                self._send_json(500, {"error": str(e)})
                return
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            sup.record_input_latency(elapsed_ms)
            self._send_json(200, {
                "reply": ui_result.reply,
                "intent": ui_result.intent,
                "filed": ui_result.filed,
                "used_llm": ui_result.used_llm,
                "spawn_path": spawn_path if ui_result.used_llm else None,
                "proposed_changes": ui_result.proposed_changes,
                "refused": ui_result.refused,
                "refused_reason": ui_result.refused_reason,
                "bypass_dev": ui_result.bypass_dev,
                "sim_mode": True,
                "elapsed_ms": round(elapsed_ms, 1),
            })
            return

        from agents.agent7_context import InputParser
        parser = InputParser(
            scheduler=sup.scheduler,
            llm_spawn=spawn_fn,
        )
        try:
            result = parser.parse(text)
        except Exception as e:         # noqa: BLE001
            log.exception("agent7 parse raised: %s", e)
            self._send_json(500, {"error": str(e)})
            return

        elapsed_ms = (time.monotonic() - t0) * 1000.0
        sup.record_input_latency(elapsed_ms)
        self._send_json(200, {
            "reply": result.reply,
            "intent": result.intent,
            "filed": result.filed,
            "used_llm": result.used_llm,
            "spawn_path": spawn_path if result.used_llm else None,
            "elapsed_ms": round(elapsed_ms, 1),
        })

    def _handle_queue_snapshot(self) -> None:
        sched = self.server.supervisor.scheduler
        self._send_json(200, sched.snapshot())

    def _handle_env(self) -> None:
        """GET /api/env — selective environment surface for the dashboard.

        Only exposes flags the UI needs; never full env (which could
        leak the API key path). Keep this whitelist short.
        Also reports warm-session status, input-latency rollup, and
        auto-analyze state so the dashboard shows health at a glance.
        """
        whitelist = ("RC_COACH_ADAPTATION",)
        out: dict[str, Any] = {k: os.environ.get(k, "") for k in whitelist}
        sup = self.server.supervisor
        warm = sup.warm_agent7
        out["warm_agent7"] = warm.stats() if warm else {"warm": False}
        out["input_latency"] = sup.input_latency_stats()
        out["auto_analyze"] = sup.auto_analyze_stats()
        self._send_json(200, out)

    def _handle_minimap_crop(self) -> None:
        """GET /api/minimap-crop?mode=sr — fetches the latest Game-PC frame
        from the vision server, crops the minimap region, returns PNG.

        Mode-specific bboxes are empirically calibrated for 1920×1080
        windowed-borderless. Override via query string
        ``?bbox=x1,y1,x2,y2`` for debugging.

        Never blocks the supervisor — fails closed with a clear status
        if the vision server is cold or PIL isn't available.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or ["sr"])[0].lower()
        bbox_raw = (qs.get("bbox") or [""])[0]

        # Bbox resolution order: ?bbox= override → persisted calibration in
        # data/vision_regions.json (`_minimap_<mode>` key) → hardcoded
        # 1920×1080 fallback. Arena has no minimap — falls through to 404.
        if bbox_raw:
            try:
                from agents._minimap_bbox import parse_http_override as _parse_bbox
                bbox = _parse_bbox(bbox_raw)
            except ValueError as ve:
                self._send_json(
                    400,
                    {"error": f"bbox must be x1,y1,x2,y2 with r>l,b>t,coords in [0,10000]: {ve}"},
                )
                return
        else:
            from agents._minimap_bbox import resolve as _resolve_minimap_bbox
            bbox = _resolve_minimap_bbox(mode)
            if bbox is None:
                self._send_json(404, {"error": f"no minimap for mode {mode!r}"})
                return

        try:
            import io
            import base64
            import urllib.request
            from PIL import Image
            from core.vision_token import get_vision_token
        except ImportError as e:
            self._send_json(500, {"error": f"missing dependency: {e}"})
            return

        tok = get_vision_token()

        # Fast path: a dedicated Game-PC minimap stream uploads pre-cropped
        # frames to source=minimap at high cadence (5-10Hz). When fresh,
        # serve it directly — no decode/re-encode on the supervisor.
        # Falls through to the slow path on any failure.
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8889/latest-frame?source=minimap",
                headers={"X-RC-Token": tok},
            )
            with urllib.request.urlopen(req, timeout=1.5) as r:
                fast = json.loads(r.read())
            fast_b64 = fast.get("b64") if isinstance(fast, dict) else None
            fast_ts = float(fast.get("ts", 0) or 0)
            if fast_b64 and (time.time() - fast_ts) < 3.0:
                raw = base64.b64decode(fast_b64)
                # Source frame is JPEG from the agent; re-encode only if the
                # caller specifically wants PNG semantics. For overlay use,
                # JPEG is fine and ~5x smaller — pass through as-is.
                ctype = "image/jpeg" if fast_b64.startswith("/9j/") else "image/png"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(raw)
                return
        except Exception:
            pass

        # Slow path: crop on demand from the global full-frame cache.
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:8889/latest-frame",
                headers={"X-RC-Token": tok},
            )
            with urllib.request.urlopen(req, timeout=2.0) as r:
                frame = json.loads(r.read())
        except Exception as e:              # noqa: BLE001
            self._send_json(502, {"error": f"vision server unreachable: {e}"})
            return

        b64 = frame.get("b64") if isinstance(frame, dict) else None
        if not b64:
            self._send_json(504, {"error": "vision server has no cached frame"})
            return

        try:
            img = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            crop = img.crop(bbox)
            buf = io.BytesIO()
            crop.save(buf, format="PNG", optimize=True)
            body = buf.getvalue()
        except Exception as e:              # noqa: BLE001
            self._send_json(500, {"error": f"crop failed: {e}"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        # No cache — the minimap should refresh with each poll.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _handle_task_detail(self) -> None:
        """GET /api/task/<id> — current snapshot of a single task plus
        its event history from the jsonl. Powers the activity-ticker
        click-to-detail modal.
        """
        # Path: /api/task/<id>
        parts = self.path.split("?", 1)[0].split("/")
        if len(parts) < 4 or not parts[3]:
            self._send_json(400, {"error": "task id required"})
            return
        task_id = parts[3].strip()
        if len(task_id) > 64 or not all(c.isalnum() or c in "-_" for c in task_id):
            self._send_json(400, {"error": "invalid task id"})
            return
        sched = self.server.supervisor.scheduler
        task = sched.get(task_id)
        # Walk the jsonl for this task's event history — small scan,
        # queue log is KB-range.
        events: list[dict[str, Any]] = []
        try:
            with sched._queue_log.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = rec.get("task") or {}
                    if t.get("id") == task_id:
                        events.append({
                            "ts": rec.get("ts"),
                            "event": rec.get("event"),
                            "status": t.get("status"),
                        })
        except OSError:
            pass

        if task is None and not events:
            self._send_json(404, {"error": "task not found"})
            return

        payload_preview: dict[str, Any] = {}
        result_preview: Any = None
        if task is not None:
            # Clip large payload fields so modal doesn't blow up.
            for k, v in (task.payload or {}).items():
                sv = json.dumps(v, default=str) if not isinstance(v, str) else v
                if len(sv) > 400:
                    sv = sv[:400] + "…"
                payload_preview[k] = sv
            if task.result is not None:
                rs = json.dumps(task.result, default=str)
                result_preview = rs if len(rs) <= 800 else rs[:800] + "…"

        self._send_json(200, {
            "id": task_id,
            "op": task.op if task else None,
            "owner_agent": task.owner_agent if task else None,
            "status": task.status if task else None,
            "priority": task.priority if task else None,
            "created_at": task.created_at if task else None,
            "updated_at": task.updated_at if task else None,
            "categories": list(task.categories) if task else None,
            "payload_preview": payload_preview,
            "result_preview": result_preview,
            "last_error": task.last_error if task else None,
            "events": events,
        })

    # Advisory ops are filed by the cold-streak detector + insight
    # detector (and future similar producers) — READY tasks carrying
    # user-visible notices.
    ADVISORY_OPS = frozenset({"cold-streak-advisory", "coaching-insight-advisory"})

    def _handle_advisories(self) -> None:
        """GET /api/advisories[?mode=aram&limit=10&include_completed=0]

        Returns the list of advisory tasks (currently cold-streak
        notifications) the user should see on the dashboard. Default
        scope is READY only so dismissed advisories disappear cleanly.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode_filter = (qs.get("mode") or [""])[0].strip() or None
        include_completed = (qs.get("include_completed") or ["0"])[0] in ("1", "true")
        try:
            limit = max(1, min(50, int((qs.get("limit") or ["10"])[0])))
        except ValueError:
            limit = 10

        sched = self.server.supervisor.scheduler
        statuses = ["ready"] + (["completed"] if include_completed else [])
        entries: list[dict[str, Any]] = []
        for status in statuses:
            for t in sched.list_by_status(status):
                if t.op not in self.ADVISORY_OPS:
                    continue
                p = t.payload or {}
                if mode_filter and p.get("mode") != mode_filter:
                    continue
                entry = {
                    "id": t.id,
                    "op": t.op,
                    "status": t.status,
                    "created_at": t.created_at,
                    "priority": t.priority,
                    "mode": p.get("mode"),
                    "message": p.get("message"),
                    "detected_at": p.get("detected_at"),
                }
                if t.op == "cold-streak-advisory":
                    entry.update({
                        "champion": p.get("champion"),
                        "delta": p.get("delta"),
                        "sample": p.get("sample"),
                        "baseline_kda_ratio": p.get("baseline_kda_ratio"),
                        "recent_kda_ratio": p.get("recent_kda_ratio"),
                    })
                elif t.op == "coaching-insight-advisory":
                    entry.update({
                        "insight_type": p.get("insight_type"),
                        "severity": p.get("severity"),
                        "champion": p.get("champion"),
                    })
                entries.append(entry)
        # Sort newest-first then clip.
        entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
        self._send_json(200, {"advisories": entries[:limit]})

    def _handle_task_dismiss(self) -> None:
        """POST /api/task/<id>/dismiss — completes the task with a
        ``{dismissed_at, source: "user"}`` result marker. Useful for
        advisory tasks the user has read and wants out of the active list.
        """
        # Path: /api/task/<id>/dismiss
        parts = self.path.split("?", 1)[0].split("/")
        # ["", "api", "task", "<id>", "dismiss"]
        if len(parts) < 5 or parts[1] != "api" or parts[2] != "task" \
                or parts[4] != "dismiss" or not parts[3]:
            self._send_json(400, {"error": "malformed dismiss url"})
            return
        task_id = parts[3].strip()
        if len(task_id) > 64 or not all(c.isalnum() or c in "-_" for c in task_id):
            self._send_json(400, {"error": "invalid task id"})
            return

        sched = self.server.supervisor.scheduler
        existing = sched.get(task_id)
        if existing is None:
            self._send_json(404, {"error": "task not found"})
            return
        # Idempotent: dismissing an already-completed task is a 200 no-op.
        if existing.status == "completed":
            self._send_json(200, {
                "id": task_id, "status": "completed",
                "already_completed": True,
            })
            return

        result = {
            "dismissed_at": _iso_now(),
            "source": "user",
            "prior_status": existing.status,
        }
        t = sched.complete(task_id, result=result)
        if t is None:
            self._send_json(500, {"error": "complete() returned None"})
            return
        self._send_json(200, {
            "id": task_id,
            "status": t.status,
            "dismissed_at": result["dismissed_at"],
        })

    def _handle_activity(self) -> None:
        """GET /api/activity?limit=N — last N scheduler events for the
        dashboard activity ticker. Keeps the autonomous framework's
        work visible to the operator.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        try:
            limit = int((qs.get("limit") or ["10"])[0])
        except ValueError:
            limit = 10
        sched = self.server.supervisor.scheduler
        self._send_json(200, {
            "events": sched.recent_events(limit=limit),
            "snapshot": sched.snapshot(),
        })

    def _handle_insight_card(self) -> None:
        """GET /api/insight-card?champion=X&mode=Y[&enemies=A,B]

        Returns ``{"card": "<text>"}`` with a compact summary line for
        copying to Discord / clipboard / voice-to-text. Empty string if
        the champion has no bucket yet.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or ["aram"])[0]
        champion = (qs.get("champion") or [""])[0].strip()
        enemies_raw = (qs.get("enemies") or [""])[0].strip()
        enemies = [e.strip() for e in enemies_raw.split(",") if e.strip()] \
                  if enemies_raw else None
        if not champion:
            self._send_json(400, {"error": "champion required"})
            return
        try:
            from coaches.adaptation_hint import insight_card
        except Exception as e:              # noqa: BLE001
            self._send_json(500, {"error": str(e)})
            return
        card = insight_card(champion, mode, enemies=enemies)
        self._send_json(200, {
            "champion": champion,
            "mode": mode,
            "enemies": enemies,
            "card": card,
            "chars": len(card),
        })

    def _handle_adaptation(self) -> None:
        """GET /api/adaptation?champion=X&mode=Y[&enemies=A,B,C]

        Returns Agent 4's aggregates for the requested champion in the
        requested mode, plus the top activated matchups. Without
        ``champion``: returns ``top_champions`` for the mode.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or ["aram"])[0]
        champion = (qs.get("champion") or [""])[0].strip()
        enemies_raw = (qs.get("enemies") or [""])[0].strip()
        enemies = [e.strip() for e in enemies_raw.split(",") if e.strip()] if enemies_raw else None
        top_n = int((qs.get("top") or ["10"])[0] or "10")

        try:
            from coaches.adaptation_hint import for_champion, format_hint_line, top_champions
        except Exception as e:               # noqa: BLE001
            log.exception("adaptation helper import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return

        if champion:
            data = for_champion(champion, mode)
            data["hint"] = format_hint_line(champion, mode, enemies=enemies)
            self._send_json(200, data)
            return

        self._send_json(200, {
            "mode": mode,
            "top": top_champions(mode, n=top_n, min_games=1),
        })

    def _handle_trending(self) -> None:
        """GET /api/trending?mode=aram[&n=3]

        Returns the hot/cold KDA streaks for ``mode`` via
        ``coaches.adaptation_hint.kda_trends``. Without ``mode``, returns
        a map of mode → trends so the dashboard can pick without a
        round-trip per mode.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        try:
            n = max(1, min(10, int((qs.get("n") or ["3"])[0])))
        except ValueError:
            n = 3
        try:
            from coaches.adaptation_hint import kda_trends, SUPPORTED_MODES
        except Exception as e:                  # noqa: BLE001
            log.exception("trending helper import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        if mode:
            self._send_json(200, kda_trends(mode, n=n))
            return
        self._send_json(200, {
            "by_mode": {m: kda_trends(m, n=n) for m in SUPPORTED_MODES}
        })

    def _handle_session(self) -> None:
        """GET /api/session[?since=today|24h|7d|<ISO>]

        Returns ``session_summary`` across all mode DBs. Default
        ``since`` is local midnight (today's games).
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        since_spec = (qs.get("since") or ["today"])[0].strip() or "today"
        try:
            from coaches.adaptation_hint import session_summary, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("session helper import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, session_summary(_parse_since(since_spec)))

    def _handle_session_games(self) -> None:
        """GET /api/session-games[?since=today|24h|7d|<ISO>&limit=N]

        Chronological per-match timeline since ``since``. Supports
        an optional ``limit`` (tail clamp, most-recent N).
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        since_spec = (qs.get("since") or ["today"])[0].strip() or "today"
        limit_raw = (qs.get("limit") or [""])[0].strip()
        limit: int | None = None
        if limit_raw:
            try:
                limit = max(1, min(500, int(limit_raw)))
            except ValueError:
                limit = None
        try:
            from coaches.adaptation_hint import session_games, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("session_games import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        games = session_games(_parse_since(since_spec), limit=limit)
        self._send_json(200, {"since": since_spec, "games": games})

    def _handle_time_of_day(self) -> None:
        """GET /api/time-of-day[?mode=aram&since=today|24h|7d|<ISO>&min=3]

        Returns per-hour win-rate + KDA buckets for the requested mode
        (or all modes). Used by the dashboard's "when am I best?" view.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            min_games = max(1, min(50, int((qs.get("min") or ["3"])[0])))
        except ValueError:
            min_games = 3
        try:
            from coaches.adaptation_hint import time_of_day_analysis, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("time_of_day import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, time_of_day_analysis(
            mode=mode, since_iso=since, min_games=min_games,
        ))

    def _handle_day_of_week(self) -> None:
        """GET /api/day-of-week[?mode=aram&since=today|30d|<ISO>&min=3]"""
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            min_games = max(1, min(50, int((qs.get("min") or ["3"])[0])))
        except ValueError:
            min_games = 3
        try:
            from coaches.adaptation_hint import day_of_week_analysis, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("day_of_week import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, day_of_week_analysis(
            mode=mode, since_iso=since, min_games=min_games,
        ))

    def _handle_duration(self) -> None:
        """GET /api/duration[?mode=X&champion=Y&since=Z&min=N]

        Buckets matches by game length into stomp / quick / standard /
        long tiers. Per-tier win-rate + KDA. Filterable by champion for
        "my Tristana is a late-game carry" style insights.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        champion = (qs.get("champion") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            min_games = max(1, min(50, int((qs.get("min") or ["3"])[0])))
        except ValueError:
            min_games = 3
        try:
            from coaches.adaptation_hint import duration_analysis, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("duration_analysis import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, duration_analysis(
            mode=mode, champion=champion, since_iso=since,
            min_games=min_games,
        ))

    def _handle_digest(self) -> None:
        """GET /api/digest[?mode=X&since=Y&top=N]

        Bundles the top actionable insights (cold streaks, time-of-day
        outliers, weak days, problem durations) into a single ranked
        list. One-shot endpoint for dashboards / voice assistants.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        mode = (qs.get("mode") or [""])[0].strip() or None
        since_spec = (qs.get("since") or [""])[0].strip() or ""
        try:
            top_n = max(1, min(30, int((qs.get("top") or ["5"])[0])))
        except ValueError:
            top_n = 5
        try:
            from coaches.adaptation_hint import coaching_digest, _parse_since
        except Exception as e:                  # noqa: BLE001
            log.exception("coaching_digest import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        since = _parse_since(since_spec) if since_spec else None
        self._send_json(200, coaching_digest(
            mode=mode, since_iso=since, top_n=top_n,
        ))

    def _handle_locked_champion(self) -> None:
        """GET /api/locked-champion[?fresh=1]

        Best-effort champion identification when the live-client
        pipeline isn't producing data. Tries LCU → match_db → recent
        user-notes. Cached 10s by default; ``?fresh=1`` forces re-probe.
        """
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(self.path).query)
        force = (qs.get("fresh") or ["0"])[0] in ("1", "true")
        try:
            from agents.agent5_ui.champion_fallback import current_champion
        except Exception as e:  # noqa: BLE001
            log.exception("champion_fallback import failed: %s", e)
            self._send_json(500, {"error": str(e)})
            return
        self._send_json(200, current_champion(force_fresh=force))

    def _handle_file_task(self) -> None:
        """POST /api/file-task — file a task directly into the running
        supervisor's in-memory heap.

        Request body (JSON)::

            {
              "op": "some-op",          # required
              "owner_agent": "6",       # required — string "0".."7"
              "priority": 50,           # optional int (default 100)
              "categories": [1, 5],     # optional int list
              "payload": {...},         # optional dict
              "user_override": false,   # optional bool
              "blocks": [],             # optional task_id list
              "blocked_by": []          # optional task_id list
            }

        Returns the filed task's id + status so callers can track it.
        Goes through all existing gating (hard-gate, frozen-file guard,
        Agent 0 review). Fails with 400 on malformed input.

        LAN trust model: same as /api/input — whoever can reach 8890
        can dispatch tasks. Don't expose 8890 beyond LAN.
        """
        raw = self._read_body()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError as e:
            self._send_json(400, {"error": f"bad json: {e}"})
            return

        op = (body.get("op") or "").strip()
        owner = str(body.get("owner_agent") or "").strip()
        if not op or not owner:
            self._send_json(400, {"error": "op and owner_agent are required"})
            return

        try:
            priority = int(body.get("priority", 100))
        except (TypeError, ValueError):
            self._send_json(400, {"error": "priority must be int"})
            return

        cats_raw = body.get("categories") or []
        if not isinstance(cats_raw, list) or not all(isinstance(c, int) for c in cats_raw):
            self._send_json(400, {"error": "categories must be list[int]"})
            return

        payload = body.get("payload") or {}
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "payload must be object"})
            return

        sup = self.server.supervisor
        try:
            task = sup.scheduler.file_task(
                op=op,
                owner_agent=owner,
                priority=priority,
                categories=list(cats_raw),
                payload=payload,
                user_override=bool(body.get("user_override", False)),
                blocks=list(body.get("blocks") or []),
                blocked_by=list(body.get("blocked_by") or []),
            )
        except Exception as e:       # noqa: BLE001
            log.exception("file_task from HTTP raised: %s", e)
            self._send_json(500, {"error": str(e)})
            return

        self._send_json(200, {
            "id": task.id,
            "status": task.status,
            "priority": task.priority,
            "owner_agent": task.owner_agent,
            "op": task.op,
            "categories": task.categories,
            "frozen_file_hits": task.payload.get("_frozen_file_hits"),
        })

    def _handle_analyze(self) -> None:
        """POST /api/analyze — optional JSON body ``{"mode": "aram"}`` to run
        one mode, otherwise runs all. Synchronous — returns the summary.
        Intended for on-demand refresh from the iPad after a match ends.
        """
        raw = self._read_body()
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}

        mode = (body.get("mode") or "").strip() or None
        try:
            from agents.agent4_coach_mentor import analyze_mode, analyze_all
            result = analyze_mode(mode) if mode else analyze_all()
        except ValueError as e:
            self._send_json(400, {"error": str(e)})
            return
        except FileNotFoundError as e:
            self._send_json(404, {"error": str(e)})
            return
        except Exception as e:               # noqa: BLE001
            log.exception("analyze raised: %s", e)
            self._send_json(500, {"error": str(e)})
            return

        self._send_json(200, result if mode else {"per_mode": result})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.info("web %s - %s", self.address_string(), format % args)


class _WebServer(socketserver.ThreadingTCPServer):
    """Wraps the supervisor handle so HTTP handlers can access the
    scheduler + ephemeral-spawn closure."""
    daemon_threads = True
    supervisor: "Supervisor"


def start_web_server(port: int = WEB_PORT, supervisor: "Supervisor" | None = None) -> socketserver.TCPServer:
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(WEB_ROOT), **kw)  # noqa: E731
    srv = _WebServer(("0.0.0.0", port), handler)
    srv.supervisor = supervisor  # type: ignore[assignment]
    t = threading.Thread(target=srv.serve_forever, name="web-http", daemon=True)
    t.start()
    log.info("web HTTP server listening on 0.0.0.0:%d (root=%s)", port, WEB_ROOT)
    return srv


# -------- Ephemeral LLM dispatch stub -------------------------------

class EphemeralStubNotWired(RuntimeError):
    """Retained for backwards-compat and for the explicit no-charter path.

    After the real subprocess spawn landed (2026-04-22), this is only
    raised when the ``claude`` CLI itself is missing from PATH — the
    dispatcher still translates it into ``Scheduler.fail()`` so tasks
    stay visible.
    """


class EphemeralSpawnFailed(RuntimeError):
    """Raised when claude subprocess exits non-zero or times out."""


def _format_task_prompt(agent: str, task_id: str, op: str, payload: dict) -> str:
    """Build the user prompt the ephemeral claude session will see."""
    lines = [
        f"# Task dispatch — agent{agent}",
        "",
        f"- Task id: `{task_id}`",
        f"- Operation: `{op}`",
        f"- Dispatched by: Agent 1 (scheduler) on {_iso_now()}",
        "",
        "## Payload",
        "",
        "```json",
        json.dumps(payload, indent=2),
        "```",
        "",
        "## Instructions",
        "",
        "You are running as an ephemeral session under the Riot Commander",
        "Phase 3 framework. Your charter is in the system prompt above.",
        "Complete the task, then exit. Write any report artifacts the",
        "charter requires. Your final stdout message will be captured as",
        "the task result in `agents/state/task_queue.jsonl`.",
    ]
    return "\n".join(lines)


def spawn_ephemeral_llm(agent: str, task_id: str, op: str, payload: dict) -> dict:
    """Spawn a real ``claude`` subprocess for the given agent + task.

    Invocation:
        claude -p <prompt>
               --model <AGENT_MODELS[agent]>
               --dangerously-skip-permissions
               --append-system-prompt <charter-text>
               --no-session-persistence
               --output-format json
               --max-budget-usd <budget>

    stdout/stderr are streamed to ``logs/agents/agent<N>.log`` and
    captured. On exit code 0 we attempt to parse stdout as JSON; on any
    other exit code we raise ``EphemeralSpawnFailed`` which the dispatch
    loop translates into ``Scheduler.fail()``.

    Payload overrides:
      - ``spawn_budget_usd``: float dollar cap (default 2.0)
      - ``spawn_timeout_sec``: int seconds (default 900)
      - ``additional_dirs``: list[str] of extra --add-dir args
    """
    log_path = LOG_ROOT / f"agent{agent}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    per_task_log = LOG_ROOT / f"task-{task_id}.log"

    model = AGENT_MODELS.get(agent)
    if model is None:
        raise EphemeralStubNotWired(f"no model mapping for agent{agent}")

    # Locate the claude CLI — fall back to EphemeralStubNotWired so the
    # dispatcher reports a clean failure rather than a shell error.
    claude_bin = shutil.which(CLAUDE_CLI)
    if claude_bin is None:
        raise EphemeralStubNotWired(
            f"`{CLAUDE_CLI}` not found on PATH — install Claude Code CLI "
            f"or ensure it's on the supervisor's PATH"
        )

    # Load charter. AUDIT P-audit3-m01 (2026-04-22): if the agent has a
    # declared charter path but the file is missing or unreadable, FAIL
    # LOUDLY instead of dispatching without — missing-charter spawns
    # silently widen authority and burn budget with no scope constraint.
    charter = ""
    charter_path = AGENT_CHARTERS.get(agent)
    if charter_path is not None:
        if not charter_path.exists():
            raise EphemeralStubNotWired(
                f"charter missing for agent{agent} at {charter_path}"
            )
        try:
            charter = charter_path.read_text(encoding="utf-8")
        except OSError as e:
            raise EphemeralStubNotWired(
                f"charter unreadable for agent{agent} at {charter_path}: {e}"
            ) from e
        if not charter.strip():
            raise EphemeralStubNotWired(
                f"charter empty for agent{agent} at {charter_path}"
            )

    user_prompt = _format_task_prompt(agent, task_id, op, payload)
    budget = float(payload.get("spawn_budget_usd", DEFAULT_SPAWN_BUDGET_USD))
    timeout = int(payload.get("spawn_timeout_sec", DEFAULT_SPAWN_TIMEOUT_SEC))

    # Argument construction: on Windows, `shutil.which("claude")` resolves
    # to `claude.CMD` (a batch wrapper around node). Batch scripts mangle
    # quoted multi-line prompts on the command line — newlines and
    # interleaved quotes silently get truncated. So we pipe the prompt
    # via stdin and let claude's default --input-format=text consume it.
    cmd: list[str] = [
        claude_bin,
        "--print",
        "--model", model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--output-format", "json",
        "--max-budget-usd", f"{budget:.2f}",
    ]
    if charter:
        cmd.extend(["--append-system-prompt", charter])
    for extra_dir in payload.get("additional_dirs", []) or []:
        cmd.extend(["--add-dir", str(extra_dir)])

    stamp = _iso_now()
    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"{stamp} SPAWN agent={agent} task={task_id} op={op} "
            f"model={model} budget_usd={budget:.2f} timeout_sec={timeout} "
            f"charter_bytes={len(charter)} prompt_bytes={len(user_prompt)}\n"
        )

    # Spawn. CREATE_NO_WINDOW keeps pythonw.exe-hosted supervisor quiet.
    creation_flags = 0
    if sys.platform.startswith("win"):
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=user_prompt,
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{_iso_now()} TIMEOUT agent={agent} task={task_id} after={timeout}s\n")
        raise EphemeralSpawnFailed(
            f"claude subprocess timed out after {timeout}s for task {task_id}"
        ) from e

    elapsed = time.time() - t0

    # Mirror the full exchange into a per-task log file so the report can
    # be inspected without tail-chasing the rolling agent log.
    # AUDIT 2026-04-28 (P-audit4-m03): redact secret-shaped strings before
    # write. The supervisor injects ANTHROPIC_API_KEY into the spawn env;
    # an agent that introspects os.environ (or a traceback that exposes
    # KeyError on the var) would otherwise leak the key into a file on
    # disk readable by anyone with shell access.
    try:
        per_task_log.write_text(
            f"=== task {task_id} agent{agent} op={op} ===\n"
            f"cmd-length: {sum(len(a) for a in cmd)} chars\n"
            f"model: {model}\n"
            f"budget_usd: {budget:.2f}\n"
            f"timeout_sec: {timeout}\n"
            f"elapsed_sec: {elapsed:.1f}\n"
            f"exit_code: {proc.returncode}\n\n"
            f"--- stdout ---\n{_redact_secrets(proc.stdout)}\n\n"
            f"--- stderr ---\n{_redact_secrets(proc.stderr)}\n",
            encoding="utf-8",
        )
    except OSError as e:
        log.warning("per-task log write failed: %s", e)

    if proc.returncode != 0:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"{_iso_now()} FAIL agent={agent} task={task_id} exit={proc.returncode} "
                f"stderr={proc.stderr[:200]!r}\n"
            )
        raise EphemeralSpawnFailed(
            f"claude exit {proc.returncode} for task {task_id}: "
            f"{proc.stderr.strip()[:400]}"
        )

    # Parse the JSON envelope. Fall back to raw stdout if parse fails —
    # better to surface whatever the model returned than claim failure.
    result: Any
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {"raw_stdout": proc.stdout.strip()}

    with log_path.open("a", encoding="utf-8") as f:
        f.write(
            f"{_iso_now()} OK agent={agent} task={task_id} elapsed={elapsed:.1f}s "
            f"stdout_bytes={len(proc.stdout)}\n"
        )

    return {
        "ok": True,
        "substrate": "ephemeral_claude_cli",
        "model": model,
        "exit_code": 0,
        "elapsed_sec": round(elapsed, 2),
        "result": result,
        "task_log": str(per_task_log),
    }


# -------- Supervisor --------------------------------------------------

class Supervisor:
    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._ws: WSServer | None = None
        self._web: socketserver.TCPServer | None = None
        self._scheduler: Scheduler | None = None
        self._agent0: Evaluator | None = None
        self._file_ingest: FileIngest | None = None
        self._warm_agent7: WarmAgent7Session | None = None
        self._warm_agent7_alive: bool = False
        self.cross_machine_enabled: bool = True
        # Rolling ring buffer of /api/input latencies (ms). Cap at 20.
        self._input_latencies: list[float] = []
        self._input_latency_lock = threading.Lock()
        # Pending post-game analyzer run (Agent 4 charter idle trigger).
        self._auto_analyze_task: asyncio.Task | None = None
        self._auto_analyze_scheduled_at: float | None = None     # monotonic
        self._auto_analyze_running_since: float | None = None    # monotonic
        self._auto_analyze_last_done_at: float | None = None     # monotonic
        self._auto_analyze_last_summary: dict | None = None
        # Tier 3 #15 (2026-05-01): DecisionLoop relocated from RC main
        # process. Daemon thread; started in start(), stopped in stop().
        # Cross-process file locking on data/decisions_pending.json lives
        # in core.decision_detector._decisions_critical_section so the
        # dashboard's record_choice() handler in RC main stays safe.
        self._decision_loop: Any = None

    # ---- startup -----------------------------------------------------
    async def start(self) -> None:
        log.info("supervisor starting (pid=%d)", os.getpid())
        # AUDIT P-audit3-h03: fail closed on decisions-file drift.
        _verify_decisions_version()
        # AUDIT P-audit4-m02: assert PHASE3_MODES still matches db.files.
        _verify_modes()
        init_all_dbs()
        # Round 23 — retro-fit KDA columns on pre-existing DBs. No-op on
        # already-migrated DBs; fast on fresh DBs (columns land via CREATE
        # TABLE in SCHEMA_STATEMENTS, ALTER just sees them present).
        try:
            _ensure_kda_columns_all()
        except Exception as e:  # noqa: BLE001
            log.warning("KDA column migration failed: %s", e)

        # Audit L2: preflight the ports so failure is a clear log line.
        for port, label in ((WEB_PORT, "web"), (WS_PORT, "ws")):
            if not _port_available("0.0.0.0", port):
                raise RuntimeError(
                    f"port {port} ({label}) is already in use — another supervisor? "
                    f"run: `netstat -ano | findstr :{port}` to identify the holder"
                )

        if not smb_credential_present():
            log.warning(
                "SMB credential for %s not found via cmdkey — disabling cross-machine dispatch",
                SMB_TARGET,
            )
            self.cross_machine_enabled = False

        self._agent0 = Evaluator(game_state_probe=self._game_state_probe)
        self._scheduler = Scheduler(agent0_evaluate=self._agent0.evaluate)

        self._ws = WSServer(host="0.0.0.0", port=WS_PORT)
        await self._ws.start()

        # Warm Agent 7 session — lazy, opens on first /api/input call OR
        # file_ingest's client→game transition trigger below.
        self._warm_agent7 = WarmAgent7Session()

        # File-watcher ingest: bridges the existing RC coaching JSONs to
        # the /push stream until the Game-PC Forwarder is deployed (§12).
        # Charter: warm starts when game begins — hook the mode transition.
        self._file_ingest = FileIngest(
            self._ws,
            on_mode_transition=self._on_mode_transition,
        )
        self._file_ingest.start()

        self._web = start_web_server(WEB_PORT, supervisor=self)

        # Bootstrap tasks.
        asyncio.create_task(self._heartbeat_loop())
        asyncio.create_task(self._dispatch_loop())
        asyncio.create_task(self._warm_ui_watchdog())

        # Decision detector loop (T3 #15, 2026-05-01) — relocated from
        # dashboard/server.py. Polls the Live Client relay + vision_state
        # and reconciles data/decisions_pending.json. The dashboard reads
        # pending + writes choices via DecisionStore directly; cross-
        # process file locking serializes the two writers.
        try:
            from core.decision_detector import get_loop as _get_decision_loop
            self._decision_loop = _get_decision_loop()
            self._decision_loop.start_background()
        except Exception as e:  # noqa: BLE001
            log.warning("decision_detector failed to start: %s", e)
            self._decision_loop = None

        log.info("supervisor started: ws=:%d web=:%d xmachine=%s", WS_PORT, WEB_PORT, self.cross_machine_enabled)

    # ---- shutdown ----------------------------------------------------
    async def stop(self) -> None:
        log.info("supervisor stopping")
        self._stop.set()
        if self._decision_loop is not None:
            try:
                self._decision_loop.stop()
            except Exception as e:  # noqa: BLE001
                log.debug("decision_loop.stop() raised: %s", e)
            self._decision_loop = None
        if self._warm_agent7:
            self._warm_agent7.close()
        if self._file_ingest:
            await self._file_ingest.stop()
        if self._ws:
            await self._ws.stop()
        if self._web:
            self._web.shutdown()
            self._web.server_close()
        # Lock metadata + sentinel both go.
        for p in (LOCKFILE, STATE_DIR / "lockfile.sentinel"):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        log.info("supervisor stopped")

    # ---- heartbeat ---------------------------------------------------
    async def _heartbeat_loop(self) -> None:
        try:
            while not self._stop.is_set():
                refresh_lock()
                await asyncio.sleep(HEARTBEAT_INTERVAL)
        except asyncio.CancelledError:
            pass

    # ---- warm-session UI-close watchdog ------------------------------
    async def _warm_ui_watchdog(self) -> None:
        """Per Agent 7 charter, warm ends when the UI closes. We grant a
        ``WARM_UI_CLOSE_GRACE_SEC`` grace period after the last /push
        subscriber disconnects — a page reload reconnects within a few
        seconds and the warm conversation context survives that.

        No subscribers + no warm session → no-op.
        Subscribers present → keep alive.
        Zero subscribers for more than the grace period → warm.close().
        """
        zero_since: float | None = None
        try:
            while not self._stop.is_set():
                await asyncio.sleep(WARM_UI_CHECK_INTERVAL_SEC)
                if self._warm_agent7 is None or self._ws is None:
                    continue
                stats = self._warm_agent7.stats()
                if not stats.get("warm"):
                    zero_since = None
                    continue
                if self._ws.push_subscribers > 0:
                    zero_since = None
                    continue
                # Zero subscribers.
                now = time.monotonic()
                if zero_since is None:
                    zero_since = now
                    log.info("warm watchdog: 0 push subscribers — grace timer started")
                elif now - zero_since >= WARM_UI_CLOSE_GRACE_SEC:
                    log.info(
                        "warm watchdog: closing warm session after %ds with no UI subscribers",
                        int(now - zero_since),
                    )
                    self._warm_agent7.close()
                    zero_since = None
        except asyncio.CancelledError:
            pass

    # ---- dispatch ----------------------------------------------------
    async def _dispatch_loop(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._scheduler.next_ready() if self._scheduler else None
            except Exception as e:  # noqa: BLE001
                log.exception("scheduler.next_ready raised: %s", e)
                task = None

            if task is None:
                await asyncio.sleep(0.5)
                continue

            agent = task.owner_agent
            try:
                # Known deterministic ops bypass the owner-agent →
                # substrate map so they never accidentally spawn an
                # LLM. Keep this list short and explicit.
                if task.op in DETERMINISTIC_OPS:
                    result = await asyncio.to_thread(self._run_deterministic, task)
                elif agent in ("0", "1", "3"):
                    result = await asyncio.to_thread(self._run_deterministic, task)
                elif agent in ("2", "4", "5", "6"):
                    if agent == "2" and not self.cross_machine_enabled and "push" in task.op:
                        raise RuntimeError("cross-machine disabled (no cmdkey)")
                    result = await asyncio.to_thread(
                        spawn_ephemeral_llm, agent, task.id, task.op, task.payload,
                    )
                elif agent == "7":
                    result = await asyncio.to_thread(self._warm_agent7_handle, task)
                else:
                    raise RuntimeError(f"unknown owner agent: {agent}")
                self._scheduler.complete(task.id, result=result)
            except Exception as e:  # noqa: BLE001
                log.exception("task %s failed: %s", task.id, e)
                self._scheduler.fail(task.id, error=str(e))

    # ---- substrate handlers ------------------------------------------
    def _run_deterministic(self, task) -> dict:
        """Dispatch pure-Python (no LLM) tasks to op-specific handlers.

        Logs the dispatch first, then routes by ``task.op``. Unknown
        ops fall through to the logging no-op so the task completes
        without error — this keeps legacy agent0/1/3 tasks working
        while new deterministic ops can register handlers here.
        """
        log_path = LOG_ROOT / f"agent{task.owner_agent}.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"{_iso_now()} DETERMINISTIC agent={task.owner_agent} "
                f"task={task.id} op={task.op} "
                f"payload={json.dumps(task.payload, default=str)[:400]}\n"
            )

        # Op-specific handlers — grow this registry carefully.
        if task.op == "game-summary":
            from agents.agent2_backend.game_ingest import (
                IngestError, ingest_game_summary,
            )
            try:
                result = ingest_game_summary(task.payload or {})
                return {
                    "dispatched": True,
                    "substrate": "deterministic",
                    "handler": "game_ingest.ingest_game_summary",
                    **result,
                }
            except IngestError as e:
                # Real DB error — surface as task failure.
                raise RuntimeError(f"game-summary ingest failed: {e}") from e

        if task.op == "ui-proposal":
            from agents.agent4_coach_mentor.ui_applier import (
                UIApplyError, apply_ui_proposal,
            )
            try:
                result = apply_ui_proposal(task.payload or {})
                return {
                    "dispatched": True,
                    "substrate": "deterministic",
                    "handler": "ui_applier.apply_ui_proposal",
                    **result,
                }
            except UIApplyError as e:
                raise RuntimeError(f"ui-proposal apply failed: {e}") from e

        # Round 43: strict allowlist. Record-keeping ops intentionally
        # no-op (filing them IS the work). Test-prefixed ops are
        # permitted so pytest doesn't have to register fakes. Anything
        # else is a fabricated op — fail loudly so the user sees WHY.
        if (task.op in _DETERMINISTIC_RECORDKEEPING_OPS
                or task.op.startswith("test-")):
            return {
                "dispatched": True,
                "substrate": "deterministic",
                "noop": True,
                "reason": "record-keeping op — filing is the work",
            }
        raise RuntimeError(
            f"no deterministic handler for op={task.op!r} "
            f"(owner_agent={task.owner_agent}). If Agent 7's LLM fallback "
            f"produced this, re-run with the constrained op vocabulary."
        )

    def _warm_agent7_handle(self, task) -> dict:
        if self._warm_agent7 is None:
            return spawn_ephemeral_llm("7", task.id, task.op, task.payload)
        if not self._warm_agent7_alive:
            log.info("warming agent7 session for task %s", task.id)
            self._warm_agent7_alive = True
        spawn = warm_spawn_factory(self._warm_agent7)
        try:
            return spawn("7", task.id, task.op, task.payload)
        except WarmSessionError as e:
            log.warning("warm send failed, fallback ephemeral: %s", e)
            return spawn_ephemeral_llm("7", task.id, task.op, task.payload)

    def _on_mode_transition(self, prev: str, new: str) -> None:
        """File-ingest callback — fires when ``ops/runtime/health.json.mode``
        transitions between client and game.

        Two actions wired:
          * **game-start** (non-game → game): prime the warm Agent 7
            session so the user's first /api/input is fast.
          * **game-end** (game → non-game): schedule an auto-run of the
            analyzer after IDLE_ANALYZE_SEC so adaptation_buckets and
            matchup_modifiers incorporate the most-recent match. Per
            Agent 4 charter: "runs at system idle (not in-game, not in
            champ select)". If another game begins within that window,
            cancel the pending analyze.

        Safe: ping/analyzer failures are logged and swallowed.
        """
        log.info("mode transition: %s → %s", prev, new)
        new_norm = (new or "").lower()
        prev_norm = (prev or "").lower()

        # game-start: warm prime.
        if (self._warm_agent7 is not None
                and new_norm in ("game", "in_progress")
                and prev_norm not in ("game", "in_progress")):
            try:
                self._warm_agent7.send(
                    "System notice: a new game just started. Reply with the "
                    "token READY and nothing else. Do not use tools.",
                    max_tokens=10,
                )
                log.info("warm session primed on game-start transition")
            except Exception as e:  # noqa: BLE001
                log.debug("warm prime ping failed: %s", e)

        # Champ-select prime — warm before pick phase so mid-draft
        # queries are sub-second. Skip if already warm.
        champ_select_states = ("champ_select", "pregame", "lobby_champ_select")
        if (self._warm_agent7 is not None
                and new_norm in champ_select_states
                and prev_norm not in champ_select_states + ("game", "in_progress")):
            try:
                if not self._warm_agent7.stats().get("warm"):
                    self._warm_agent7.send(
                        "System notice: champ-select in progress. Reply READY only.",
                        max_tokens=10,
                    )
                    log.info("warm session primed on champ-select transition")
                else:
                    log.debug("warm already hot — skipping champ-select prime")
            except Exception as e:  # noqa: BLE001
                log.debug("warm prime ping (champ-select) failed: %s", e)

        # Cancel any pending post-game analyze when another game begins.
        if new_norm in ("game", "in_progress"):
            self._cancel_pending_auto_analyze("game started")
            return

        # game-end: schedule auto-analyze on game→non-game transitions
        # AND file a post-game summary note so the dashboard's activity
        # ticker shows something visible as soon as the match ends.
        if prev_norm in ("game", "in_progress") and new_norm not in ("game", "in_progress"):
            self._file_post_game_summary(prev_norm, new_norm)
            loop = asyncio.get_running_loop() if asyncio.get_event_loop().is_running() else None
            if loop is None:
                log.debug("no running loop — skipping auto-analyze schedule")
                return
            # Schedule safely via call_soon_threadsafe since file_ingest
            # runs in a background thread of its own.
            try:
                loop.call_soon_threadsafe(self._schedule_auto_analyze)
            except RuntimeError as e:
                log.debug("schedule auto-analyze failed: %s", e)

    def _file_post_game_summary(self, prev: str, new: str) -> None:
        """Capture post-game state from the newest coaching JSON + the
        rating file, file a ``game-summary`` task. Owner agent is 2
        (deterministic backend) so the supervisor's dispatch loop runs
        the in-process ingester rather than spawning an LLM.
        """
        if self._scheduler is None:
            return
        # Read whichever mode coaching file has the most recent mtime —
        # that's the one the just-finished game was using. Source of truth
        # for the file set is dashboard._state_builder.MODE_FILES so this
        # list can't drift from MODE_TO_FILE (ADR-008 pattern). Local
        # import keeps module load order independent of dashboard package.
        try:
            from dashboard._state_builder import MODE_FILES as _MODE_FILES
        except Exception as _imp_exc:  # noqa: BLE001
            log.debug("MODE_FILES import failed; using hardcoded fallback: %s", _imp_exc)
            _MODE_FILES = (
                "data/aram_coaching_data.json",
                "data/arena_coaching_data.json",
                "data/brawl_coaching_data.json",
                "data/tft_coaching_data.json",
                "coaching_data.json",
            )
        candidates = [_PROJECT_ROOT / rel for rel in _MODE_FILES]
        newest = None
        newest_mtime = 0.0
        for p in candidates:
            try:
                m = p.stat().st_mtime
                if m > newest_mtime:
                    newest, newest_mtime = p, m
            except OSError:
                continue
        summary_payload: dict[str, Any] = {
            "prev_mode": prev,
            "new_mode": new,
            "finished_at": _iso_now(),
        }
        if newest is not None:
            try:
                data = json.loads(newest.read_text(encoding="utf-8"))
                for k in ("mode", "game_mode", "game_time", "game_time_s",
                          "kda", "hp_pct", "items_display", "item_build",
                          "champion", "augments", "win_pct", "action"):
                    if k in data:
                        summary_payload[k] = data[k]
                summary_payload["source"] = newest.name
            except (OSError, json.JSONDecodeError) as e:
                log.debug("post-game summary read failed for %s: %s", newest, e)

        # Also pull the most recent per-mode rating file for grade + stats.
        # 2026-04-27: switched from the legacy data/ratings/last_game_rating.json
        # (which ignored RC_ACCOUNT_ID namespacing) to the most-recently-
        # modified last_<mode>.json — performance_tracker._latest_rating_file
        # is the authoritative locator.
        try:
            from performance_tracker import _latest_rating_file as _lrf  # type: ignore
            rating_path = _lrf(str(_PROJECT_ROOT))
        except Exception as e:
            log.debug("rating-file locator import failed: %s", e)
            rating_path = None
        try:
            if rating_path and rating_path.exists():
                rating_data = json.loads(rating_path.read_text(encoding="utf-8"))
                for k in ("rating", "label", "stats", "notes", "mode_category"):
                    if k in rating_data:
                        summary_payload[k] = rating_data[k]
                # Prefer the rating file's champion if coaching JSON
                # didn't have one — it's more authoritative post-match.
                if "champion" in rating_data and "champion" not in summary_payload:
                    summary_payload["champion"] = rating_data["champion"]
                if "game_mode" in rating_data and "game_mode" not in summary_payload:
                    summary_payload["game_mode"] = rating_data["game_mode"]
        except (OSError, json.JSONDecodeError) as e:
            log.debug("rating file read failed: %s", e)

        try:
            self._scheduler.file_task(
                op="game-summary",
                owner_agent="2",       # deterministic backend ingester
                priority=60,
                categories=[],
                payload=summary_payload,
                user_override=True,    # system-filed
            )
            log.info("post-game summary filed (prev=%s new=%s champ=%s)",
                     prev, new, summary_payload.get("champion", "?"))
        except Exception as e:  # noqa: BLE001
            log.debug("post-game summary filing failed: %s", e)

    # ---- auto-analyze lifecycle --------------------------------------
    def _schedule_auto_analyze(self) -> None:
        """Start a background coroutine that runs the analyzer after the
        charter's 2-min idle window. Idempotent — if one's already
        pending, do nothing (caller may call multiple times as
        transitions fire)."""
        if getattr(self, "_auto_analyze_task", None) and not self._auto_analyze_task.done():
            return
        self._auto_analyze_scheduled_at = time.monotonic()
        self._auto_analyze_task = asyncio.create_task(self._auto_analyze_after_idle())

    def _cancel_pending_auto_analyze(self, reason: str) -> None:
        task = getattr(self, "_auto_analyze_task", None)
        if task is not None and not task.done():
            task.cancel()
            self._auto_analyze_scheduled_at = None
            log.info("auto-analyze cancelled: %s", reason)

    async def _auto_analyze_after_idle(self) -> None:
        """Sleeps IDLE_ANALYZE_SEC, then:

        1. Reconciles live-phase3 rows against postgame_stats.db to fill
           in NULL wins (postgame collector has had time to populate).
        2. Runs analyze_all so the new win signals flow into buckets /
           matchup modifiers / recency_30d.

        Gets cancelled on a new game start. Any exception is logged —
        analyzer failures never crash the supervisor loop.
        """
        try:
            await asyncio.sleep(IDLE_ANALYZE_SEC)
            from agents.agent2_backend.win_reconcile import reconcile_all
            from agents.agent4_coach_mentor import analyze_all

            log.info("auto-analyze starting (post-game idle)")
            self._auto_analyze_scheduled_at = None
            self._auto_analyze_running_since = time.monotonic()

            # Step 1: reconcile win signals. Fast — runs SQL only.
            reconcile_result = await asyncio.to_thread(reconcile_all)
            total_patched = sum(
                r.get("patched", 0) for r in reconcile_result.values()
                if isinstance(r, dict)
            )
            if total_patched:
                log.info("win reconciler patched %d live row(s)", total_patched)

            # Step 2: analyzer reads the now-reconciled data.
            result = await asyncio.to_thread(analyze_all)
            total_champs = sum(r.get("champion_buckets", 0) for r in result.values() if isinstance(r, dict))
            total_items = sum(r.get("top_items_total", 0) for r in result.values() if isinstance(r, dict))

            # Step 3: cold-streak detector — autonomously files advisory
            # tasks for champions whose last-10 KDA has tanked. Runs
            # off-thread since it touches SQLite + the cooldown file.
            advisories: dict = {"filed": [], "skipped_cooldown": [], "below_threshold": 0}
            if self._scheduler is not None:
                try:
                    from agents.agent4_coach_mentor.cold_streak_detector import detect_and_file
                    advisories = await asyncio.to_thread(detect_and_file, self._scheduler)
                    if advisories.get("filed"):
                        log.info(
                            "cold-streak detector filed %d advisory task(s)",
                            len(advisories["filed"]),
                        )
                except Exception as e:  # noqa: BLE001
                    log.exception("cold-streak detector failed: %s", e)

            # Step 4: general digest-driven insight detector — catches
            # worst-hour slumps, weak weekdays, bad duration tiers.
            # Skips cold_streak type (already handled above).
            insight_summary: dict = {"filed": [], "skipped_cooldown": []}
            if self._scheduler is not None:
                try:
                    from agents.agent4_coach_mentor.insight_detector import (
                        detect_insights_and_file,
                    )
                    insight_summary = await asyncio.to_thread(
                        detect_insights_and_file, self._scheduler,
                    )
                    if insight_summary.get("filed"):
                        log.info(
                            "insight detector filed %d coaching advisory task(s)",
                            len(insight_summary["filed"]),
                        )
                except Exception as e:  # noqa: BLE001
                    log.exception("insight detector failed: %s", e)

            # Step 5: auto-dismiss stale advisories — keeps the queue
            # fresh so the user only sees actionable recent signals.
            sweeper_summary: dict = {"dismissed": [], "inspected": 0}
            if self._scheduler is not None:
                try:
                    from agents.agent4_coach_mentor.advisory_sweeper import sweep_stale
                    sweeper_summary = await asyncio.to_thread(
                        sweep_stale, self._scheduler,
                    )
                    if sweeper_summary.get("dismissed"):
                        log.info(
                            "advisory sweeper dismissed %d stale task(s)",
                            len(sweeper_summary["dismissed"]),
                        )
                except Exception as e:  # noqa: BLE001
                    log.exception("advisory sweeper failed: %s", e)

            self._auto_analyze_last_summary = {
                "champion_buckets": total_champs,
                "top_items_total": total_items,
                "modes": list(result.keys()),
                "win_patched": total_patched,
                "advisories_filed": len(advisories.get("filed", [])),
                "insight_advisories_filed": len(insight_summary.get("filed", [])),
                "stale_advisories_dismissed": len(sweeper_summary.get("dismissed", [])),
            }
            log.info("auto-analyze done: %d champion buckets updated", total_champs)
        except asyncio.CancelledError:
            log.debug("auto-analyze cancelled during idle wait")
            self._auto_analyze_scheduled_at = None
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("auto-analyze failed: %s", e)
            self._auto_analyze_last_summary = {"error": str(e)}
        finally:
            self._auto_analyze_running_since = None
            self._auto_analyze_last_done_at = time.monotonic()

    def auto_analyze_stats(self) -> dict:
        """Snapshot for /api/env — captures pending / running / last-run
        state so the dashboard can show "refresh in 1:47" or "refreshing…".
        """
        now = time.monotonic()
        scheduled = self._auto_analyze_scheduled_at
        running = self._auto_analyze_running_since
        done_at = self._auto_analyze_last_done_at

        state = "idle"
        fires_in_sec: float | None = None
        running_sec: float | None = None
        last_run_ago_sec: float | None = None

        if running is not None:
            state = "running"
            running_sec = round(now - running, 1)
        elif scheduled is not None:
            elapsed = now - scheduled
            remaining = IDLE_ANALYZE_SEC - elapsed
            if remaining > 0:
                state = "pending"
                fires_in_sec = round(remaining, 1)
            else:
                # Scheduled but not yet flipped to running — transient.
                state = "pending"
                fires_in_sec = 0.0
        if done_at is not None:
            last_run_ago_sec = round(now - done_at, 1)

        return {
            "state": state,
            "fires_in_sec": fires_in_sec,
            "running_sec": running_sec,
            "last_run_ago_sec": last_run_ago_sec,
            "last_summary": self._auto_analyze_last_summary,
            "idle_threshold_sec": IDLE_ANALYZE_SEC,
        }

    def _game_state_probe(self) -> str:
        # Reads the existing RC app's health file for current mode/state.
        health = _PROJECT_ROOT / "ops" / "runtime" / "health.json"
        try:
            data = json.loads(health.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return "NONE"
        return str(data.get("game_state") or data.get("mode") or "NONE")

    # ---- public accessors --------------------------------------------
    @property
    def scheduler(self) -> Scheduler:
        assert self._scheduler is not None
        return self._scheduler

    @property
    def warm_agent7(self) -> WarmAgent7Session | None:
        return self._warm_agent7

    # ---- input latency rollup ----------------------------------------
    def record_input_latency(self, elapsed_ms: float) -> None:
        with self._input_latency_lock:
            self._input_latencies.append(float(elapsed_ms))
            if len(self._input_latencies) > 20:
                self._input_latencies = self._input_latencies[-20:]

    def input_latency_stats(self) -> dict:
        with self._input_latency_lock:
            buf = list(self._input_latencies)
        if not buf:
            return {"n": 0, "avg_ms": None, "min_ms": None, "max_ms": None, "p95_ms": None}
        avg = sum(buf) / len(buf)
        p95_idx = max(0, int(round(0.95 * (len(buf) - 1))))
        p95 = sorted(buf)[p95_idx]
        return {
            "n": len(buf),
            "avg_ms": round(avg, 1),
            "min_ms": round(min(buf), 1),
            "max_ms": round(max(buf), 1),
            "p95_ms": round(p95, 1),
        }


# -------- entry point -------------------------------------------------

async def _run() -> int:
    if not acquire_lock():
        return 2
    sup = Supervisor()
    loop = asyncio.get_running_loop()
    stop_evt = asyncio.Event()

    def _handle_signal(*_a: Any) -> None:
        loop.call_soon_threadsafe(stop_evt.set)

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        with contextlib.suppress(NotImplementedError, ValueError):
            loop.add_signal_handler(sig, _handle_signal)

    try:
        await sup.start()
        await stop_evt.wait()
    finally:
        await sup.stop()
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
