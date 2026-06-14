"""Agent 1 - Lead: the single writer of ``agents/state/task_queue.jsonl``.

Responsibilities (§7, §11.7):

  * In-memory priority queue of :class:`QueueTask`.
  * Append-only JSONL persistence of every status transition.
  * Recovery on startup: replay the JSONL and reconstruct in-memory state.
  * Gate policy:
      - Hard gates (categories 1, 7, 8) → ``needs_explicit_approval``.
        Caller (supervisor UI) must approve before the task becomes dispatchable.
      - Soft gate via Agent 0 (category 5, cross-machine) → ``agent0_review``.
        Agent 0 accepts or rejects autonomously.
      - Ungated (2, 3, 4, 6) → straight to ``ready``.
  * User-override flag bypasses Agent 0 rejection (§7).
  * Dispatch: the scheduler exposes ``next_ready()`` - the supervisor pulls
    the highest-priority ready task and invokes the right substrate.
"""
from __future__ import annotations

import heapq
import itertools
import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Platform-specific file-lock primitives. On Windows we use msvcrt, on
# POSIX fcntl. Spec targets Windows but scripts run under WSL bash so we
# handle both. See audit P-audit-h2.
try:
    import msvcrt  # type: ignore[import-not-found]
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False
try:
    import fcntl  # type: ignore[import-not-found]
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

_APPEND_LOCK_RETRY_SEC = 0.05
_APPEND_LOCK_MAX_WAIT_SEC = 5.0

# Compaction policy: the queue log is append-only, but every reader
# (`_load`, `_latest_status_from_log`, `recent_events`) scans the whole
# file. Without periodic compaction the file grows unbounded and slows
# the cold-start `_load()`. Compaction keeps only the latest event per
# task_id - `_load()` already has latest-wins semantics, so this preserves
# the in-memory state reconstruction exactly.
_COMPACT_INTERVAL_S = 3600.0  # hourly check
_COMPACT_THRESHOLD_BYTES = 2 * 1024 * 1024  # compact above 2 MB

# Reconciler policy (audit-8 H-02): in_progress envelopes that never
# receive a terminal completed/failed event are state-machine leaks.
# Stale threshold = 30 minutes per the audit-8 proposal; reconcile cadence
# 5 minutes keeps the scan cheap (in-memory dict iteration only).
_RECONCILE_STALE_SEC = 1800.0     # 30 min - audit-8 H-02 threshold
_RECONCILE_INTERVAL_S = 300.0     # 5 min between scans
_RECONCILE_TIMEOUT_REASON = "timeout-no-terminal-event"

logger = logging.getLogger("agent1.scheduler")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE_DIR = _PROJECT_ROOT / "agents" / "state"
QUEUE_LOG = STATE_DIR / "task_queue.jsonl"

# S7 hard gates: categories 1 (destructive file ops), 7 (git-adjacent),
# 8 (large file ops). Declared by the task author; we enforce here.
HARD_GATES = {1, 7, 8}
SOFT_AGENT0 = {5}  # cross-machine

# Files that must not be modified without explicit user approval. Synced
# with CLAUDE.md SHard rules. If a task payload references any of these
# paths, the scheduler auto-adds category 1 (hard gate) unless the task
# carries user_override=True. Makes the "charter rule" runtime-enforced
# rather than just prose.
FROZEN_FILES = frozenset({
    "main.py",
    "core/log_setup.py",
    "core/moon_proxy.py",
    "lcu/lcu_client.py",
    "core/game_snapshot.py",
    "ops/rc_dev_runtime.py",
    "ops/rc_supervisor.py",
    "app/__init__.py",
    "app/_health_monitor.py",
    "app/_remediation.py",
    "app/_state_authority.py",
    "app/_overlay_manager.py",
    "app/_game_lifecycle.py",
})


def _detect_frozen_references(payload: dict[str, Any]) -> list[str]:
    """Scan payload values for references to any frozen file path.

    Returns the list of frozen files mentioned - empty when none.
    Scans string/list/dict values recursively. Matches on normalized
    forward-slash paths so ``app\\__init__.py`` and ``app/__init__.py``
    both hit. Bounded scan depth prevents deep-nested payload runaway.
    """
    hits: list[str] = []
    seen: set[int] = set()

    def _walk(v: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if id(v) in seen:
            return
        seen.add(id(v))
        if isinstance(v, str):
            norm = v.replace("\\", "/").lower()
            for fp in FROZEN_FILES:
                if fp.lower() in norm and fp not in hits:
                    hits.append(fp)
        elif isinstance(v, dict):
            for sub in v.values():
                _walk(sub, depth + 1)
        elif isinstance(v, (list, tuple)):
            for item in v:
                _walk(item, depth + 1)

    _walk(payload)
    return hits


class TaskStatus:
    PENDING = "pending"
    NEEDS_APPROVAL = "needs_explicit_approval"
    READY = "ready"
    AGENT0_REVIEW = "agent0_review"
    RETRY_PENDING = "retry_pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


@dataclass
class QueueTask:
    id: str
    op: str
    owner_agent: str              # "0", "1", ..., "7"
    priority: int                 # lower = more urgent (heap min-order)
    categories: list[int] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = TaskStatus.PENDING
    created_at: str = ""
    updated_at: str = ""
    blocks: list[str] = field(default_factory=list)   # task ids this blocks
    blocked_by: list[str] = field(default_factory=list)
    user_override: bool = False   # direct user order - bypass Agent 0 reject
    retry_count: int = 0
    last_error: str | None = None
    result: Any = None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Scheduler:
    def __init__(
        self,
        queue_log: Path | None = None,
        agent0_evaluate: Callable | None = None,
        compact_interval_s: float = _COMPACT_INTERVAL_S,
        compact_threshold_bytes: int = _COMPACT_THRESHOLD_BYTES,
    ) -> None:
        # Resolve QUEUE_LOG at call time so tests / runtime reconfig
        # that monkeypatch the module-level constant take effect.
        self._queue_log = queue_log if queue_log is not None else QUEUE_LOG
        self._tasks: dict[str, QueueTask] = {}
        # heap holds (priority, counter, task_id) - counter breaks ties by
        # insertion order so heap is FIFO within same priority.
        self._heap: list[tuple[int, int, str]] = []
        self._counter = itertools.count()
        self._lock = threading.RLock()
        self._agent0_evaluate = agent0_evaluate
        self._compact_interval_s = float(compact_interval_s)
        self._compact_threshold_bytes = int(compact_threshold_bytes)
        self._compact_stop = threading.Event()
        self._compact_thread: threading.Thread | None = None
        self._load()
        if self._compact_interval_s > 0:
            self._start_compactor()

    # ----- persistence --------------------------------------------
    @staticmethod
    def _lock_file_exclusive(f: Any) -> None:
        """Block on a cross-process exclusive lock with a retry budget."""
        deadline = time.monotonic() + _APPEND_LOCK_MAX_WAIT_SEC
        while True:
            try:
                if _HAS_MSVCRT:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                elif _HAS_FCNTL:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    # No locking primitives available - proceed without.
                    # Logged once at module level via the scheduler.
                    return
                return
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    logger.error("append lock wait exceeded %ss - proceeding unlocked",
                                 _APPEND_LOCK_MAX_WAIT_SEC)
                    return
                time.sleep(_APPEND_LOCK_RETRY_SEC)

    @staticmethod
    def _unlock_file(f: Any) -> None:
        try:
            if _HAS_MSVCRT:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            elif _HAS_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def _append_log(self, event_type: str, task: QueueTask, extra: dict | None = None) -> None:
        rec: dict[str, Any] = {
            "event": event_type,
            "ts": _iso_now(),
            "task": asdict(task),
        }
        if extra:
            rec["extra"] = extra
        line = json.dumps(rec, separators=(",", ":"), default=str) + "\n"
        self._queue_log.parent.mkdir(parents=True, exist_ok=True)
        # Process-level lock on the append path. In-process calls are
        # already serialised by self._lock (RLock); this protects against
        # a second Python process writing to the same jsonl file (e.g.
        # the supervisor process + an ops/ helper script).
        with self._queue_log.open("a", encoding="utf-8") as f:
            try:
                self._lock_file_exclusive(f)
                f.write(line)
                f.flush()
            finally:
                self._unlock_file(f)

    # ----- compaction ---------------------------------------------
    def compact(self) -> tuple[int, int]:
        """Rewrite ``task_queue.jsonl`` to keep only the latest event per task_id.

        Returns ``(lines_before, lines_after)``. Safe to call from any
        thread - holds the in-process RLock and the cross-process file
        lock for the entire read-truncate-rewrite cycle so concurrent
        ``_append_log`` calls from any process block until done.

        Latest-wins matches ``_load()`` semantics, so the reconstructed
        in-memory state after compaction is identical to before. Corrupt
        lines are dropped (already logged by ``_load`` on next reload).
        """
        if not self._queue_log.exists():
            return (0, 0)

        with self._lock:
            try:
                with self._queue_log.open("r+", encoding="utf-8") as f:
                    self._lock_file_exclusive(f)
                    try:
                        f.seek(0)
                        lines = f.read().splitlines()

                        # dict preserves insertion order; del+set on hit
                        # keeps the most-recent occurrence of each task_id
                        # at the end, so iteration order matches "newest
                        # last" which `recent_events()` relies on.
                        latest: dict[str, str] = {}
                        non_empty = 0
                        for line in lines:
                            line = line.strip()
                            if not line:
                                continue
                            non_empty += 1
                            try:
                                rec = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            tid = (rec.get("task") or {}).get("id")
                            if not tid:
                                continue
                            if tid in latest:
                                del latest[tid]
                            latest[tid] = line

                        if len(latest) >= non_empty:
                            return (non_empty, non_empty)

                        new_content = "".join(latest[tid] + "\n" for tid in latest)
                        f.seek(0)
                        f.truncate()
                        f.write(new_content)
                        f.flush()
                        logger.info(
                            "task_queue.jsonl compact: %d → %d lines",
                            non_empty, len(latest),
                        )
                        return (non_empty, len(latest))
                    finally:
                        self._unlock_file(f)
            except OSError as exc:
                logger.warning("task_queue.jsonl compact failed: %s", exc)
                return (0, 0)

    def _maybe_compact(self) -> None:
        try:
            size = self._queue_log.stat().st_size
        except OSError:
            return
        if size < self._compact_threshold_bytes:
            return
        self.compact()

    def _compact_loop(self) -> None:
        while not self._compact_stop.is_set():
            try:
                self._maybe_compact()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("compact loop iteration failed: %s", exc)
            self._compact_stop.wait(self._compact_interval_s)

    def _start_compactor(self) -> None:
        t = threading.Thread(
            target=self._compact_loop, daemon=True, name="agent1-compact",
        )
        self._compact_thread = t
        t.start()
        logger.info(
            "task_queue.jsonl compactor started (interval=%.0fs threshold=%dB)",
            self._compact_interval_s, self._compact_threshold_bytes,
        )

    def stop_compactor(self) -> None:
        """Stop the periodic compactor thread (mostly for tests)."""
        self._compact_stop.set()
        if self._compact_thread is not None:
            self._compact_thread.join(timeout=3)
            self._compact_thread = None

    def _load(self) -> None:
        if not self._queue_log.exists():
            return
        loaded = 0
        corrupt = 0
        with self._queue_log.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as e:
                    # AUDIT P-audit3-m04 (2026-04-22): surface corruption
                    # loudly instead of silently dropping the line. The
                    # queue log is the scheduler's system of record.
                    logger.error(
                        "task_queue.jsonl line %d corrupt (%s): %r",
                        lineno, e, line[:120],
                    )
                    corrupt += 1
                    continue
                t = rec.get("task") or {}
                if not t.get("id"):
                    continue
                self._tasks[t["id"]] = QueueTask(**t)
                loaded += 1
        if corrupt:
            logger.error(
                "task_queue.jsonl: %d corrupt line(s) dropped on load - "
                "consider filing an audit-queue-corruption task",
                corrupt,
            )

        # Rebuild heap from non-terminal tasks.
        terminal = {TaskStatus.COMPLETED, TaskStatus.DEAD_LETTER, TaskStatus.FAILED}
        for tid, task in self._tasks.items():
            if task.status in terminal:
                continue
            heapq.heappush(self._heap, (task.priority, next(self._counter), tid))

        logger.info("scheduler loaded %d tasks (%d non-terminal in heap)", loaded, len(self._heap))

    # ----- public API ---------------------------------------------
    def file_task(
        self,
        op: str,
        owner_agent: str,
        priority: int = 100,
        categories: list[int] | None = None,
        payload: dict | None = None,
        user_override: bool = False,
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        task_id: str | None = None,
    ) -> QueueTask:
        with self._lock:
            tid = task_id or f"t-{uuid.uuid4().hex[:12]}"
            # Audit M4: drop any blocked_by ids that don't resolve - silently
            # blocking forever is worse than warning and running.
            raw_blocked_by = list(blocked_by or [])
            resolved_blocked_by: list[str] = []
            for bid in raw_blocked_by:
                if bid in self._tasks:
                    resolved_blocked_by.append(bid)
                else:
                    logger.warning(
                        "file_task %s: unknown blocked_by id %r - dropping", op, bid,
                    )
            # Frozen-file guardrail - scan payload for CLAUDE.md SHard
            # rules files. Without user_override, auto-add category 1 so
            # the task lands in NEEDS_APPROVAL rather than READY.
            final_categories = list(categories or [])
            frozen_hits = _detect_frozen_references(payload or {})
            if frozen_hits and not user_override:
                if 1 not in final_categories:
                    final_categories.append(1)
                logger.warning(
                    "file_task %s: frozen-file references detected (%s) - "
                    "gating to NEEDS_APPROVAL; pass user_override=True to bypass",
                    op, ", ".join(frozen_hits),
                )

            task = QueueTask(
                id=tid,
                op=op,
                owner_agent=str(owner_agent),
                priority=priority,
                categories=final_categories,
                payload=dict(payload or {}),
                created_at=_iso_now(),
                updated_at=_iso_now(),
                user_override=user_override,
                blocks=list(blocks or []),
                blocked_by=resolved_blocked_by,
            )
            if frozen_hits:
                task.payload.setdefault("_frozen_file_hits", frozen_hits)

            # Initial status via gate policy.
            cats = set(task.categories)
            if cats & HARD_GATES:
                task.status = TaskStatus.NEEDS_APPROVAL
            elif cats & SOFT_AGENT0:
                task.status = TaskStatus.AGENT0_REVIEW
            else:
                task.status = TaskStatus.READY

            self._tasks[tid] = task
            self._append_log("filed", task)

            if task.status == TaskStatus.READY:
                heapq.heappush(self._heap, (task.priority, next(self._counter), tid))
            elif task.status == TaskStatus.AGENT0_REVIEW:
                # Immediately run evaluator if wired.
                self._agent0_review(task)
            logger.info("filed task %s op=%s owner=%s status=%s", tid, op, owner_agent, task.status)
            return task

    def approve(self, task_id: str) -> QueueTask | None:
        """User approves a hard-gated task. Moves to READY."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            if t.status != TaskStatus.NEEDS_APPROVAL:
                return t
            t.status = TaskStatus.READY
            t.updated_at = _iso_now()
            heapq.heappush(self._heap, (t.priority, next(self._counter), t.id))
            self._append_log("approved", t)
            return t

    def deny(self, task_id: str, reason: str = "user denied") -> QueueTask | None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            t.status = TaskStatus.DEAD_LETTER
            t.last_error = reason
            t.updated_at = _iso_now()
            self._append_log("denied", t)
            return t

    def _agent0_review(self, task: QueueTask) -> None:
        if self._agent0_evaluate is None:
            # Agent 0 not wired - tasks sit in agent0_review until enabled.
            logger.warning("agent0 not configured - task %s stalled in agent0_review", task.id)
            return
        # Build an agent0 Task from payload - caller is expected to have
        # populated payload.remote_path, payload.payload_ext, payload.tag.
        from agents.agent0_gatekeeper import Task as Agent0Task

        a0_task = Agent0Task(
            op=task.op,
            originating_agent=task.owner_agent,
            remote_path=task.payload.get("remote_path", ""),
            payload_ext=task.payload.get("payload_ext", ""),
            tag=task.payload.get("tag"),
            signature=task.payload.get("signature"),
        )
        decision = self._agent0_evaluate(a0_task)
        if decision.accepted:
            task.status = TaskStatus.READY
            task.updated_at = _iso_now()
            heapq.heappush(self._heap, (task.priority, next(self._counter), task.id))
            self._append_log("agent0_accepted", task,
                             extra={"criteria_passed": decision.criteria_passed})
            return

        rej = decision.rejection
        task.last_error = f"agent0:{rej.reason_code}:{rej.reason_label}:{rej.message}"

        if task.user_override:
            logger.warning("user_override=True - forcing task %s past agent0 rejection %s",
                           task.id, rej.reason_code)
            task.status = TaskStatus.READY
            task.updated_at = _iso_now()
            heapq.heappush(self._heap, (task.priority, next(self._counter), task.id))
            self._append_log("agent0_rejected_overridden", task,
                             extra={"reason_code": rej.reason_code, "label": rej.reason_label})
            return

        if rej.disposition == "retry_once" and task.retry_count == 0:
            task.retry_count += 1
            task.status = TaskStatus.RETRY_PENDING
            task.updated_at = _iso_now()
            self._append_log("agent0_rejected_retry", task,
                             extra={"reason_code": rej.reason_code, "label": rej.reason_label})
            return

        task.status = TaskStatus.DEAD_LETTER
        task.updated_at = _iso_now()
        self._append_log("agent0_rejected_dead", task,
                         extra={"reason_code": rej.reason_code, "label": rej.reason_label})

    # ----- retry management ---------------------------------------
    def promote_retry(self, task_id: str) -> QueueTask | None:
        """Called by supervisor when a retry_pending task is eligible again."""
        with self._lock:
            t = self._tasks.get(task_id)
            if not t or t.status != TaskStatus.RETRY_PENDING:
                return t
            self._agent0_review(t)
            return t

    # ----- dispatch -----------------------------------------------
    def _blocked(self, task: QueueTask) -> bool:
        for bid in task.blocked_by:
            dep = self._tasks.get(bid)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return True
        return False

    def _latest_status_from_log(self, task_id: str) -> str | None:
        """Return the most-recent on-disk status for *task_id* in task_queue.jsonl.

        Scans the log forward, keeping the last match - the JSONL is
        append-only so the final entry for a task is authoritative.
        Returns None when the log is absent or the task has no entries.

        Used by next_ready() to reject stale in-memory heap entries that a
        concurrent Scheduler process already completed or failed.
        """
        if not self._queue_log.exists():
            return None
        latest: str | None = None
        try:
            with self._queue_log.open("r", encoding="utf-8") as f:
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
                        s = t.get("status")
                        if s:
                            latest = s
        except OSError:
            pass
        return latest

    def next_ready(self) -> QueueTask | None:
        """Pop the highest-priority READY task whose dependencies are satisfied.

        Blocked tasks are re-queued for a later pass and the scan continues
        to lower-priority candidates - a blocked high-prio task must not
        starve ready lower-prio ones.

        Cross-process guard (P-audit3-followup-single-scheduler): before
        marking a candidate in-progress, re-reads its latest status from
        task_queue.jsonl so that a concurrent Scheduler instance that already
        wrote a terminal event does not get re-dispatched by a stale heap.
        """
        with self._lock:
            requeue: list[tuple[int, int, str]] = []
            picked: QueueTask | None = None
            while self._heap:
                prio, _c, tid = heapq.heappop(self._heap)
                t = self._tasks.get(tid)
                if not t:
                    continue
                if t.status != TaskStatus.READY:
                    continue
                if self._blocked(t):
                    requeue.append((prio, next(self._counter), tid))
                    continue
                # Disk-verify before dispatch: a second Scheduler process may
                # have already transitioned this task (e.g. to 'completed')
                # without our in-memory state knowing.
                disk_status = self._latest_status_from_log(tid)
                if disk_status and disk_status != TaskStatus.READY:
                    t.status = disk_status
                    t.updated_at = _iso_now()
                    logger.warning(
                        "next_ready: task %s heap says READY but disk=%s "
                        "- dropping stale entry (cross-process race guard)",
                        tid, disk_status,
                    )
                    continue
                t.status = TaskStatus.IN_PROGRESS
                t.updated_at = _iso_now()
                self._append_log("dispatched", t)
                picked = t
                break
            for entry in requeue:
                heapq.heappush(self._heap, entry)
            return picked

    def complete(self, task_id: str, result: Any = None) -> QueueTask | None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            t.status = TaskStatus.COMPLETED
            t.result = result
            t.updated_at = _iso_now()
            self._append_log("completed", t)
            return t

    def fail(self, task_id: str, error: str) -> QueueTask | None:
        with self._lock:
            t = self._tasks.get(task_id)
            if not t:
                return None
            t.status = TaskStatus.FAILED
            t.last_error = error
            t.updated_at = _iso_now()
            self._append_log("failed", t)
            return t

    # ----- inspection ---------------------------------------------
    def get(self, task_id: str) -> QueueTask | None:
        return self._tasks.get(task_id)

    def list_by_status(self, status: str) -> list[QueueTask]:
        return [t for t in self._tasks.values() if t.status == status]

    def snapshot(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for t in self._tasks.values():
            counts[t.status] = counts.get(t.status, 0) + 1
        return {
            "total": len(self._tasks),
            "by_status": counts,
            "ts": _iso_now(),
        }

    def recent_events(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most-recent N events from ``task_queue.jsonl`` in
        reverse-chronological order. Each entry carries only the fields
        the dashboard ticker needs so the response stays small.
        """
        if not self._queue_log.exists():
            return []
        cap = max(1, min(int(limit or 10), 200))
        events: list[dict[str, Any]] = []
        try:
            with self._queue_log.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    t = rec.get("task") or {}
                    events.append({
                        "ts": rec.get("ts"),
                        "event": rec.get("event"),
                        "task_id": t.get("id"),
                        "op": t.get("op"),
                        "owner_agent": t.get("owner_agent"),
                        "status": t.get("status"),
                        "priority": t.get("priority"),
                    })
        except OSError:
            return []
        # Trim to the last `cap` entries then reverse for newest-first.
        return list(reversed(events[-cap:]))

    # ----- reconciliation (audit-8 H-02) --------------------------
    @staticmethod
    def _parse_iso_ts(ts: str | None) -> datetime | None:
        """Parse an ISO-8601 timestamp string to an aware datetime.

        Returns ``None`` for malformed / missing input so the caller
        can fall through to "skip this task" instead of raising. Both
        ``+00:00`` and ``Z`` suffixes are accepted; naive timestamps
        are treated as UTC (defensive - the scheduler always writes
        ``+00:00`` via ``_iso_now()``).
        """
        if not ts:
            return None
        try:
            s = ts.replace("Z", "+00:00") if ts.endswith("Z") else ts
            dt = datetime.fromisoformat(s)
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def reconcile_stale_in_progress(
        self,
        stale_seconds: float = _RECONCILE_STALE_SEC,
        reason: str = _RECONCILE_TIMEOUT_REASON,
    ) -> list[str]:
        """Close out any IN_PROGRESS task whose ``updated_at`` is older
        than ``stale_seconds``. Emits a terminal ``failed`` event for
        each via ``self.fail()`` so the per-task last-event view
        converges and the audit math (filed == completed + failed +
        dead-letter + ready-still-pending) reconciles.

        Audit-8 H-02 closes the state-machine leak where 449 dispatched
        envelopes never reached a terminal event. The 30-minute window
        matches the audit-8 proposal; bound generously to avoid racing
        long-running LLM tasks that legitimately stay in_progress.

        Returns the list of reconciled task IDs (empty when nothing
        was stale). Safe to call from any thread - takes the same RLock
        as ``fail()``.
        """
        if stale_seconds <= 0:
            return []
        now = datetime.now(timezone.utc)
        reconciled: list[str] = []
        with self._lock:
            # Snapshot ids first so we can call fail() (which takes the
            # same lock) without mutating the dict mid-iteration.
            stale_ids: list[str] = []
            for tid, t in self._tasks.items():
                if t.status != TaskStatus.IN_PROGRESS:
                    continue
                dt = self._parse_iso_ts(t.updated_at)
                if dt is None:
                    continue
                age_s = (now - dt).total_seconds()
                if age_s >= stale_seconds:
                    stale_ids.append(tid)
            for tid in stale_ids:
                t = self._tasks.get(tid)
                if t is None or t.status != TaskStatus.IN_PROGRESS:
                    continue
                self.fail(tid, error=reason)
                reconciled.append(tid)
            if reconciled:
                logger.warning(
                    "reconciler: closed %d stale in_progress task(s) "
                    "older than %.0fs (reason=%s): %s",
                    len(reconciled), stale_seconds, reason,
                    ", ".join(reconciled[:10])
                    + (" ..." if len(reconciled) > 10 else ""),
                )
        return reconciled


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = Scheduler()
    print(json.dumps(s.snapshot(), indent=2))
