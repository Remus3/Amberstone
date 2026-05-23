"""Phase 3 supervisor - the single process that owns everything on Legion-PC.

Per §10 responsibilities:

  * Start the WS relay server on 0.0.0.0:8891.
  * Start the web UI HTTP server on 0.0.0.0:8890 (serves ``web/``).
  * Run the async event loop for Agents 0, 1, 3 (pure Python).
  * Spawn ephemeral ``claude`` sessions on Agent 1 dispatches for 2/4/5/6.
  * Maintain a warm Agent 7 session during play windows (stub - warm
    lifecycle hooks are scaffolded here and will be filled by the
    user-context build session).
  * Heartbeat to ``agents/state/lockfile`` every 5 seconds.
  * Verify SMB ``cmdkey`` presence at startup; if absent, log WARNING and
    disable cross-machine dispatch until re-verified.
  * Graceful shutdown on SIGTERM / SIGBREAK.

The process also acquires a PID lock against ``agents/state/lockfile`` -
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

# -------------------------------------------------------------------------
# s243 behavior-preserving split (AUTONOMOUS_AUDIT 4.C). This module is now
# a thin FACADE. The implementation was extracted byte-verbatim into three
# siblings; this file keeps `Supervisor` + the `_run`/`main` entry point
# (so `python -m agents.supervisor` and the test monkeypatch contract are
# unchanged) and re-exports the full surface so every caller/test importing
# `agents.supervisor.<name>` keeps working with zero edits:
#   * agents/_supervisor_common.py     - constants, leaf helpers, `log`
#   * agents/_supervisor_ephemeral.py  - ephemeral claude dispatch
#   * agents/_supervisor_http.py       - _QuietHandler / _WebServer / start_web_server
# `Supervisor` MUST stay defined here: tests patch
# `agents.supervisor.{IDLE_ANALYZE_SEC,WARM_UI_*}` and reassign
# `sup_mod.{_PROJECT_ROOT,LOG_ROOT}`, all read by Supervisor methods - the
# patch only reaches them while the class resolves THIS module's globals.
# The original import block below is kept intact (F401 is ignored
# project-wide) so `agents.supervisor.shutil`/`.subprocess` resolve for
# `test_supervisor_stub`'s patches. Do not "tidy" it.
# -------------------------------------------------------------------------

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


from agents._supervisor_common import (
    AGENT_CHARTERS,
    AGENT_MODELS,
    CLAUDE_CLI,
    DEFAULT_SPAWN_BUDGET_USD,
    DEFAULT_SPAWN_TIMEOUT_SEC,
    DETERMINISTIC_OPS,
    EXPECTED_DECISIONS_VERSION,
    HEARTBEAT_INTERVAL,
    IDLE_ANALYZE_SEC,
    LOCKFILE,
    LOG_ROOT,
    SMB_TARGET,
    STATE_DIR,
    WARM_UI_CHECK_INTERVAL_SEC,
    WARM_UI_CLOSE_GRACE_SEC,
    WEB_PORT,
    WEB_ROOT,
    WS_PORT,
    _BRIDGE_PUB_ALERT_S,
    _BRIDGE_PUB_CHECK_INTERVAL_S,
    _BRIDGE_PUB_PEERS,
    _BRIDGE_PUB_REFILE_COOLDOWN_S,
    _DETERMINISTIC_HANDLED_OPS,
    _DETERMINISTIC_RECORDKEEPING_OPS,
    _PROJECT_ROOT,
    _SECRET_PATTERNS,
    _STARTED_AT,
    _bridge_pub_should_file,
    _build_logger,
    _iso_now,
    _pid_alive,
    _port_available,
    _redact_secrets,
    _verify_decisions_version,
    acquire_lock,
    log,
    refresh_lock,
    smb_credential_present,
)
from agents._supervisor_ephemeral import (
    EphemeralSpawnFailed,
    EphemeralStubNotWired,
    _format_task_prompt,
    spawn_ephemeral_llm,
)
from agents._supervisor_http import _QuietHandler, _WebServer, start_web_server

__all__ = [
    "AGENT_CHARTERS",
    "AGENT_MODELS",
    "CLAUDE_CLI",
    "DEFAULT_SPAWN_BUDGET_USD",
    "DEFAULT_SPAWN_TIMEOUT_SEC",
    "DETERMINISTIC_OPS",
    "EXPECTED_DECISIONS_VERSION",
    "EphemeralSpawnFailed",
    "EphemeralStubNotWired",
    "HEARTBEAT_INTERVAL",
    "IDLE_ANALYZE_SEC",
    "LOCKFILE",
    "LOG_ROOT",
    "SMB_TARGET",
    "STATE_DIR",
    "Supervisor",
    "WARM_UI_CHECK_INTERVAL_SEC",
    "WARM_UI_CLOSE_GRACE_SEC",
    "WEB_PORT",
    "WEB_ROOT",
    "WS_PORT",
    "_BRIDGE_PUB_ALERT_S",
    "_BRIDGE_PUB_CHECK_INTERVAL_S",
    "_BRIDGE_PUB_PEERS",
    "_BRIDGE_PUB_REFILE_COOLDOWN_S",
    "_DETERMINISTIC_HANDLED_OPS",
    "_DETERMINISTIC_RECORDKEEPING_OPS",
    "_PROJECT_ROOT",
    "_QuietHandler",
    "_SECRET_PATTERNS",
    "_STARTED_AT",
    "_WebServer",
    "_bridge_pub_should_file",
    "_build_logger",
    "_format_task_prompt",
    "_iso_now",
    "_pid_alive",
    "_port_available",
    "_redact_secrets",
    "_run",
    "_verify_decisions_version",
    "acquire_lock",
    "log",
    "main",
    "refresh_lock",
    "shutil",
    "smb_credential_present",
    "spawn_ephemeral_llm",
    "start_web_server",
    "subprocess",
]


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
        # Round 23 - retro-fit KDA columns on pre-existing DBs. No-op on
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
                    f"port {port} ({label}) is already in use - another supervisor? "
                    f"run: `netstat -ano | findstr :{port}` to identify the holder"
                )

        if not smb_credential_present():
            log.warning(
                "SMB credential for %s not found via cmdkey - disabling cross-machine dispatch",
                SMB_TARGET,
            )
            self.cross_machine_enabled = False

        self._agent0 = Evaluator(game_state_probe=self._game_state_probe)
        self._scheduler = Scheduler(agent0_evaluate=self._agent0.evaluate)

        self._ws = WSServer(host="0.0.0.0", port=WS_PORT)
        await self._ws.start()

        # Warm Agent 7 session - lazy, opens on first /api/input call OR
        # file_ingest's client→game transition trigger below.
        self._warm_agent7 = WarmAgent7Session()

        # File-watcher ingest: bridges the existing RC coaching JSONs to
        # the /push stream until the Game-PC Forwarder is deployed (§12).
        # Charter: warm starts when game begins - hook the mode transition.
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
        asyncio.create_task(self._bridge_publisher_watchdog())  # Audit7 H-01

        # Decision detector loop (T3 #15, 2026-05-01) - relocated from
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
        subscriber disconnects - a page reload reconnects within a few
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
                    log.info("warm watchdog: 0 push subscribers - grace timer started")
                elif now - zero_since >= WARM_UI_CLOSE_GRACE_SEC:
                    log.info(
                        "warm watchdog: closing warm session after %ds with no UI subscribers",
                        int(now - zero_since),
                    )
                    self._warm_agent7.close()
                    zero_since = None
        except asyncio.CancelledError:
            pass

    # ---- bridge health-publisher watchdog (Audit7 H-01) --------------
    async def _bridge_publisher_watchdog(self) -> None:
        """Detect a silent peer bridge health-publisher and file a
        deduped Agent-1 triage task. The bridge task loop can be alive
        while only the publisher sub-process is dead (2026-05-18: gamepc
        silent ~2.7h, peer fresh at 25s) - the rc_facts probe rendered it
        but nothing escalated. Fully guarded: any read/scheduler fault
        is swallowed so the loop never dies.

        Dedup: one task per node per outage. ``fired_at`` records the
        monotonic time of the last filing; a node is re-armed the moment
        its publisher recovers (age back under threshold), and a still-
        ongoing outage only re-files after ``_BRIDGE_PUB_REFILE_COOLDOWN_S``
        so a multi-hour outage doesn't spam the queue. Mirrors the
        proposal's dedup_key intent ("re-files only when aged out").
        """
        peer_dir = _PROJECT_ROOT / "ops" / "runtime" / "peer_health"
        fired_at: dict[str, float] = {}
        try:
            while not self._stop.is_set():
                await asyncio.sleep(_BRIDGE_PUB_CHECK_INTERVAL_S)
                if self._scheduler is None:
                    continue
                now_mono = time.monotonic()
                for node in _BRIDGE_PUB_PEERS:
                    try:
                        rec_path = peer_dir / f"{node}.json"
                        if not rec_path.exists():
                            continue  # never deployed - not an alarm
                        rec = json.loads(rec_path.read_text(encoding="utf-8"))
                        recv = rec.get("received_at") or 0
                        age_s = max(0.0, time.time() - recv)
                    except Exception as e:  # noqa: BLE001
                        log.debug("bridge-pub watchdog read %s: %s", node, e)
                        continue
                    should_file, rearm = _bridge_pub_should_file(
                        age_s, fired_at.get(node), now_mono)
                    if rearm:
                        fired_at.pop(node, None)  # recovered → re-arm
                    if not should_file:
                        continue
                    try:
                        self._scheduler.file_task(
                            op="bridge-publisher-stale",
                            owner_agent="1",
                            priority=50,
                            payload={
                                "node": node,
                                "age_s": int(age_s),
                                "threshold_s": int(_BRIDGE_PUB_ALERT_S),
                                "detail": (
                                    f"{node} bridge health-publisher silent "
                                    f"{int(age_s)}s - bridge task loop may "
                                    f"still be alive (only the publisher "
                                    f"sub-process). False-confidence shape."
                                ),
                                "suggested_action": (
                                    f"Restart the {node} health publisher via "
                                    f"tools/gamepc_boot.ps1 "
                                    f"(RC-WatcherHealthPublisher-{node}); see "
                                    f"the s167 boot-hardening deferral."
                                ),
                                "source": "bridge_publisher_watchdog",
                            },
                        )
                        fired_at[node] = now_mono
                        log.warning(
                            "bridge-pub watchdog: filed Agent-1 task for "
                            "%s (age=%ds)", node, int(age_s),
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning(
                            "bridge-pub watchdog: file_task for %s "
                            "failed: %s", node, e,
                        )
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
        without error - this keeps legacy agent0/1/3 tasks working
        while new deterministic ops can register handlers here.
        """
        log_path = LOG_ROOT / f"agent{task.owner_agent}.log"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(
                f"{_iso_now()} DETERMINISTIC agent={task.owner_agent} "
                f"task={task.id} op={task.op} "
                f"payload={json.dumps(task.payload, default=str)[:400]}\n"
            )

        # Op-specific handlers - grow this registry carefully.
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
                # Real DB error - surface as task failure.
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
        # else is a fabricated op - fail loudly so the user sees WHY.
        if (task.op in _DETERMINISTIC_RECORDKEEPING_OPS
                or task.op.startswith("test-")):
            return {
                "dispatched": True,
                "substrate": "deterministic",
                "noop": True,
                "reason": "record-keeping op - filing is the work",
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
        """File-ingest callback - fires when ``ops/runtime/health.json.mode``
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

        # Champ-select prime - warm before pick phase so mid-draft
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
                    log.debug("warm already hot - skipping champ-select prime")
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
                log.debug("no running loop - skipping auto-analyze schedule")
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
        # Read whichever mode coaching file has the most recent mtime -
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
        # modified last_<mode>.json - performance_tracker._latest_rating_file
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
                # didn't have one - it's more authoritative post-match.
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
        charter's 2-min idle window. Idempotent - if one's already
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

        Gets cancelled on a new game start. Any exception is logged -
        analyzer failures never crash the supervisor loop.
        """
        try:
            await asyncio.sleep(IDLE_ANALYZE_SEC)
            from agents.agent2_backend.win_reconcile import reconcile_all
            from agents.agent4_coach_mentor import analyze_all

            log.info("auto-analyze starting (post-game idle)")
            self._auto_analyze_scheduled_at = None
            self._auto_analyze_running_since = time.monotonic()

            # Step 1: reconcile win signals. Fast - runs SQL only.
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

            # Step 3: cold-streak detector - autonomously files advisory
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

            # Step 4: general digest-driven insight detector - catches
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

            # Step 5: auto-dismiss stale advisories - keeps the queue
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
        """Snapshot for /api/env - captures pending / running / last-run
        state so the dashboard can show "refresh in 1:47" or "refreshing...".
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
                # Scheduled but not yet flipped to running - transient.
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
