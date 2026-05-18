"""
core/bridge_monitor.py - RC's mirror of Peer's bridge_monitor sidecar.

Polls dashboard._bridge_log every 2s, surfaces inbound peer traffic to the
RC log, and auto-responds to a narrow ping/pong shape so the peer (Peer)
can probe RC's half of the channel.

Contract per docs io RC peer/PEER_VIP_BRIDGE_MONITOR_FOR_RC_2026-05-02.md:
  Filter rule:
    ts > last_seen_ts AND not source.startswith("legion") AND source != "self-test"
  Auto-pong gate:
    kind == "task" AND summary.strip().lower() == "ping" AND target.lower() == "rc"
    -> bridge_post(source="rc-monitor", summary="pong", kind="result",
                   body={replier:"rc-bridge_monitor", in_reply_to_summary:"ping", auto:true},
                   in_reply_to=<original-id>)

State file: ops/runtime/bridge_monitor_state.json (atomic-written).
Cold-boot starts last_seen_ts at time.time() so historical entries don't
re-trigger.

Run via .start_background() - prefers AppLoop, falls back to daemon thread.
Mirrors core/vision_tracker.py's lifecycle pattern.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.bridge_monitor")
_APP_DIR = Path(__file__).parent.parent
_DEFAULT_STATE_PATH = _APP_DIR / "ops" / "runtime" / "bridge_monitor_state.json"
_DEFAULT_POLL_S = 2.0
_RECENT_CAP = 10


class BridgeMonitor:
    def __init__(self,
                 state_path: Path = _DEFAULT_STATE_PATH,
                 poll_s: float = _DEFAULT_POLL_S) -> None:
        self._state_path = state_path
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[asyncio.Task] = None
        self._last_seen_ts: float = 0.0
        self._inbound_count: int = 0
        self._auto_pong_count: int = 0
        self._recent: deque = deque(maxlen=_RECENT_CAP)
        self._hydrate()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start_background(self) -> None:
        """Launch the poller. Prefers AppLoop, falls back to daemon thread."""
        if (self._thread and self._thread.is_alive()) or self._task is not None:
            return
        self._stop.clear()
        try:
            from app._loop import get_loop as _get_loop
            sched = _get_loop()
        except Exception:
            sched = None
        if sched is not None:
            self._task = sched.spawn_task(self._loop_async())
            _log.info("bridge_monitor started (poll=%.1fs, async, last_seen_ts=%.0f)",
                      self._poll_s, self._last_seen_ts)
        else:
            self._thread = threading.Thread(
                target=self._loop, name="bridge-monitor", daemon=True)
            self._thread.start()
            _log.info("bridge_monitor started (poll=%.1fs, thread, last_seen_ts=%.0f)",
                      self._poll_s, self._last_seen_ts)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass
            self._task = None

    # ── State ─────────────────────────────────────────────────────────────

    def state(self) -> dict:
        with self._lock:
            return {
                "reason":           "poll",
                "ts":               time.time(),
                "last_seen_ts":     self._last_seen_ts,
                "inbound_count":    self._inbound_count,
                "auto_pong_count":  self._auto_pong_count,
                "recent":           list(self._recent),
                "configured":       True,
                "remote_url_set":   True,
            }

    def _hydrate(self) -> None:
        """Load last_seen_ts from disk so a restart doesn't replay history.
        Cold-boot (no state file) starts at time.time() - matches Peer."""
        try:
            if self._state_path.exists():
                d = json.loads(self._state_path.read_text(encoding="utf-8"))
                ts = float(d.get("last_seen_ts") or 0)
                if ts > 0:
                    self._last_seen_ts = ts
                    self._inbound_count = int(d.get("inbound_count") or 0)
                    self._auto_pong_count = int(d.get("auto_pong_count") or 0)
                    return
        except Exception as exc:
            _log.debug("bridge_monitor hydrate failed: %s", exc)
        # Cold start - only react to entries posted from now on.
        self._last_seen_ts = time.time()

    def _write_atomic(self, *, reason: str = "poll") -> None:
        try:
            payload = self.state()
            payload["reason"] = reason
            tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            # os.replace can transiently raise WinError 5 when a reader has
            # the dst open; brief retries clear it. (Same fix as
            # atomic_write_json - see reference_os_replace_winerror5 memory.)
            for delay in (0, 0.025, 0.050, 0.200):
                if delay:
                    time.sleep(delay)
                try:
                    tmp.replace(self._state_path)
                    return
                except PermissionError:
                    continue
        except Exception as exc:
            _log.debug("bridge_monitor state write failed: %s", exc)

    # ── Poll loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                _log.debug("bridge_monitor loop: %s", exc)
            self._stop.wait(self._poll_s)

    async def _loop_async(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                _log.debug("bridge_monitor loop: %s", exc)
            try:
                await asyncio.sleep(self._poll_s)
            except asyncio.CancelledError:
                return

    def _poll_once(self) -> None:
        # Read directly from the in-process bridge log - same module that
        # web_dashboard's POST /api/bridge writes into. No HTTP overhead.
        from dashboard._bridge_log import bridge_since, bridge_post
        new_entries = bridge_since(self._last_seen_ts, limit=50)
        if not new_entries:
            return
        wrote_state = False
        for entry in new_entries:
            ts = float(entry.get("ts") or 0)
            if ts <= self._last_seen_ts:
                continue
            source = (entry.get("source") or "").lower()
            # Filter: skip our own outbound (legion-*) and self-tests.
            if source.startswith("legion") or source.startswith("rc-monitor") or source == "self-test":
                self._last_seen_ts = ts
                continue
            with self._lock:
                self._inbound_count += 1
                self._recent.append({
                    "ts":          ts,
                    "source":      entry.get("source"),
                    "kind":        entry.get("kind"),
                    "summary":     (entry.get("summary") or "")[:120],
                    "id":          entry.get("id"),
                    "in_reply_to": entry.get("in_reply_to"),
                })
            _log.info("bridge_monitor: inbound source=%s kind=%s summary=%r",
                      entry.get("source"), entry.get("kind"),
                      (entry.get("summary") or "")[:80])
            # Auto-pong gate
            kind = (entry.get("kind") or "").lower()
            summary = (entry.get("summary") or "").strip().lower()
            target = (entry.get("target") or "").lower()
            if kind == "task" and summary == "ping" and target == "rc":
                try:
                    bridge_post(
                        source="rc-monitor",
                        summary="pong",
                        kind="result",
                        body={
                            "replier":              "rc-bridge_monitor",
                            "in_reply_to_summary":  "ping",
                            "auto":                 True,
                        },
                        in_reply_to=entry.get("id"),
                    )
                    with self._lock:
                        self._auto_pong_count += 1
                    _log.info("bridge_monitor: auto-pong fired in reply to %s",
                              entry.get("id"))
                except Exception as exc:
                    _log.warning("bridge_monitor: auto-pong failed: %s", exc)
            self._last_seen_ts = ts
            wrote_state = True
        if wrote_state:
            self._write_atomic(reason="poll")


# Module-level singleton + convenience launcher
_singleton: Optional[BridgeMonitor] = None


def get_monitor() -> BridgeMonitor:
    global _singleton
    if _singleton is None:
        _singleton = BridgeMonitor()
    return _singleton


def start() -> BridgeMonitor:
    m = get_monitor()
    m.start_background()
    return m
