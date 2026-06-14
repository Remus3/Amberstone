"""
core/metrics_cache.py
Phase 1 Step 2 - Internal observability surface for Riot Commander.

Runs a background thread that reads existing runtime artifacts on a fixed
interval and caches a small derived MetricsSummary.  Consumers call
get_summary() to obtain a thread-safe frozen copy; no file I/O happens
in the caller's thread.

Design rules:
  - Read-only: never writes to any file.
  - Non-fatal: missing files, invalid JSON, partial writes, empty logs
    are all silently tolerated; affected fields are set to None / "unknown".
  - Derived-state only: no new control-plane fields invented here.
  - No Tk / UI involvement in any path through this module.
  - Python 3.9 compatible: no X|Y unions, no walrus operator, no match.

Input files (all under ops/runtime/):
  status.json              - supervisor state (may predate Phase 0.13a fields)
  monitor_state.json       - SelfMonitor internal state
  health.json              - DevRuntime heartbeat (app liveness + mode)
  incident_log.jsonl       - structured incident entries (may not exist)
  last_coaching_ts.json    - SR coaching timestamp artifact (Phase 2 Step 1)

Tail-reading strategy for incident_log.jsonl:
  Only the last INCIDENT_TAIL_BYTES bytes of the file are read on each
  refresh cycle.  The bounded read is done with a seek to
  max(0, file_size - INCIDENT_TAIL_BYTES) so the full file is never
  loaded into memory.  Partial first lines from the tail are discarded.
  This caps memory per cycle at ~8 KB regardless of log file size.
"""
from __future__ import annotations

import json
import asyncio
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REFRESH_INTERVAL_S: float = 5.0          # background refresh cadence
INCIDENT_TAIL_BYTES: int = 8 * 1024      # read at most this many bytes from log tail
MAX_INCIDENTS: int = 5                   # incidents to surface in summary
_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Public summary type (plain dataclass-style, 3.9 compat)
# ---------------------------------------------------------------------------

class MetricsSummary:
    """
    Frozen snapshot of the most recent cached metrics.
    All fields may be None/"unknown" if the source file was unavailable.

    Fields:
      supervisor_state        str | None  - "healthy_ready" | "tolerated_startup_wait" |
                                            "unhealthy_restart_required" | None
      process_running         bool | None - supervisor's _app_alive() result
      awaiting_first_heartbeat bool | None
      stable_ticks            int | None  - NOT in status.json; always None in Step 2
      consecutive_fails       int | None  - from monitor_state.json
      ladder_idx              int | None  - from monitor_state.json ("ladder_index" key)
      circuit_breaker_tripped bool | None - from monitor_state.json
      current_mode            str | None  - from health.json "mode" field
      last_coaching_ts        str | None  - ISO-8601 UTC timestamp of last successful
                                            SR coaching write; None if not yet written
                                            (Phase 2 Step 1: SR-path only in this pass)
      last_5_incidents        list        - list of compact incident dicts (may be empty)
      refreshed_at            str         - ISO-8601 UTC timestamp of last refresh
      refresh_error           str | None  - last error message if refresh raised
      policy_source_status    str | None  - default|loaded|last_known_good|invalid_reload_retained|missing
      policy_last_reload_ts   str | None  - ISO-8601 UTC of last successful policy load
      policy_last_warning     str | None  - last-one-wins policy warning text
      policy_sr_live_coaching      str | None  - effective decision for sr.live_coaching
      policy_aram_live_coaching    str | None  - effective decision for aram.live_coaching
      policy_arena_live_coaching   str | None  - effective decision for arena.live_coaching
      policy_brawl_live_coaching   str | None  - effective decision for brawl.live_coaching
      policy_tft_live_coaching     str | None  - effective decision for tft.live_coaching
      policy_tft_vision_analysis   str | None  - effective decision for tft.tft_vision_analysis
    """

    __slots__ = (
        "supervisor_state",
        "process_running",
        "awaiting_first_heartbeat",
        "stable_ticks",
        "consecutive_fails",
        "ladder_idx",
        "circuit_breaker_tripped",
        "current_mode",
        "last_coaching_ts",
        "last_5_incidents",
        "refreshed_at",
        "refresh_error",
        # Phase 2 Step 2: policy observability fields
        "policy_source_status",
        "policy_last_reload_ts",
        "policy_last_warning",
        "policy_sr_live_coaching",
        "policy_aram_live_coaching",
        "policy_arena_live_coaching",
        "policy_brawl_live_coaching",
        "policy_tft_live_coaching",
        "policy_tft_vision_analysis",
    )

    def __init__(self) -> None:
        self.supervisor_state:         Optional[str]  = None
        self.process_running:          Optional[bool] = None
        self.awaiting_first_heartbeat: Optional[bool] = None
        self.stable_ticks:             Optional[int]  = None   # not in status.json
        self.consecutive_fails:        Optional[int]  = None
        self.ladder_idx:               Optional[int]  = None
        self.circuit_breaker_tripped:  Optional[bool] = None
        self.current_mode:             Optional[str]  = None
        self.last_coaching_ts:         Optional[str]  = None
        self.last_5_incidents:         List[Dict[str, Any]] = []
        self.refreshed_at:             str = ""
        self.refresh_error:            Optional[str]  = None
        # Phase 2 Step 2: policy observability
        self.policy_source_status:      Optional[str] = None
        self.policy_last_reload_ts:     Optional[str] = None
        self.policy_last_warning:       Optional[str] = None
        self.policy_sr_live_coaching:   Optional[str] = None
        self.policy_aram_live_coaching:  Optional[str] = None
        self.policy_arena_live_coaching: Optional[str] = None
        self.policy_brawl_live_coaching: Optional[str] = None
        self.policy_tft_live_coaching:   Optional[str] = None
        self.policy_tft_vision_analysis: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict copy suitable for JSON serialisation."""
        return {
            "supervisor_state":         self.supervisor_state,
            "process_running":          self.process_running,
            "awaiting_first_heartbeat": self.awaiting_first_heartbeat,
            "stable_ticks":             self.stable_ticks,
            "consecutive_fails":        self.consecutive_fails,
            "ladder_idx":               self.ladder_idx,
            "circuit_breaker_tripped":  self.circuit_breaker_tripped,
            "current_mode":             self.current_mode,
            "last_coaching_ts":         self.last_coaching_ts,
            "last_5_incidents":         self.last_5_incidents,
            "refreshed_at":             self.refreshed_at,
            "refresh_error":            self.refresh_error,
        }


# ---------------------------------------------------------------------------
# MetricsCache
# ---------------------------------------------------------------------------

class MetricsCache:
    """
    Background metrics cache for Riot Commander.

    Usage:
        mc = MetricsCache(Path("ops/runtime"))
        mc.start()
        ...
        summary = mc.get_summary()   # thread-safe frozen copy
        ...
        mc.stop()

    The cache starts a single daemon thread that wakes every
    REFRESH_INTERVAL_S seconds, reads the runtime files, and updates the
    internal summary.  get_summary() returns a deep-copied snapshot so the
    caller never holds a reference to the mutable internal state.
    """

    def __init__(
        self,
        runtime_dir: Path,
        refresh_interval_s: float = REFRESH_INTERVAL_S,
    ) -> None:
        self._runtime_dir = Path(runtime_dir)
        self._refresh_interval = refresh_interval_s

        self._summary = MetricsSummary()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._task: Optional[Any] = None  # asyncio.Task / Future

    # -- Public API ----------------------------------------------------------

    def start(self) -> None:
        """Start the background refresh loop.  No-op if already running.
        Prefers spawning on the main AppLoop; falls back to a daemon thread
        when no loop exists. The first refresh runs synchronously here so
        get_summary() returns real data immediately, regardless of path."""
        if (self._thread and self._thread.is_alive()) or self._task is not None:
            return
        self._stop_event.clear()
        # Immediate first refresh - matches the behavior the thread loop
        # provided (it called _refresh() before the first wait).
        self._refresh()
        try:
            from app._loop import get_loop as _get_loop
            _sched = _get_loop()
        except Exception:
            _sched = None
        if _sched is not None:
            self._task = _sched.spawn_task(self._loop_async())
        else:
            self._thread = threading.Thread(
                target=self._loop,
                name="MetricsCache",
                daemon=True,
            )
            self._thread.start()

    def stop(self, timeout_s: float = 10.0) -> None:
        """Signal the refresh loop to stop and wait for the worker."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass
            self._task = None

    def get_summary(self) -> MetricsSummary:
        """
        Return a thread-safe snapshot of the current summary.
        Never raises.  Returns an empty MetricsSummary if no refresh has
        completed yet.

        Snapshot safety: all scalar fields are immutable (str/bool/int/None).
        last_5_incidents entries are rebuilt as new dicts so callers cannot
        mutate internal cache state through returned incident entries.
        """
        with self._lock:
            copy = MetricsSummary()
            copy.supervisor_state         = self._summary.supervisor_state
            copy.process_running          = self._summary.process_running
            copy.awaiting_first_heartbeat = self._summary.awaiting_first_heartbeat
            copy.stable_ticks             = self._summary.stable_ticks
            copy.consecutive_fails        = self._summary.consecutive_fails
            copy.ladder_idx               = self._summary.ladder_idx
            copy.circuit_breaker_tripped  = self._summary.circuit_breaker_tripped
            copy.current_mode             = self._summary.current_mode
            copy.last_coaching_ts         = self._summary.last_coaching_ts
            # Rebuild each compact incident dict explicitly so no internal dict
            # is shared with the caller.  Each entry has exactly 5 string fields.
            copy.last_5_incidents = [
                {
                    "ts":        e["ts"],
                    "severity":  e["severity"],
                    "subsystem": e["subsystem"],
                    "trigger":   e["trigger"],
                    "detail":    e["detail"],
                }
                for e in self._summary.last_5_incidents
            ]
            copy.refreshed_at             = self._summary.refreshed_at
            copy.refresh_error            = self._summary.refresh_error
            # Phase 2 Step 2: policy fields
            copy.policy_source_status      = self._summary.policy_source_status
            copy.policy_last_reload_ts     = self._summary.policy_last_reload_ts
            copy.policy_last_warning       = self._summary.policy_last_warning
            copy.policy_sr_live_coaching   = self._summary.policy_sr_live_coaching
            copy.policy_aram_live_coaching  = self._summary.policy_aram_live_coaching
            copy.policy_arena_live_coaching = self._summary.policy_arena_live_coaching
            copy.policy_brawl_live_coaching = self._summary.policy_brawl_live_coaching
            copy.policy_tft_live_coaching   = self._summary.policy_tft_live_coaching
            copy.policy_tft_vision_analysis = self._summary.policy_tft_vision_analysis
        return copy

    # -- Background loop -----------------------------------------------------

    def _loop(self) -> None:
        """Background thread fallback: refresh on interval until stop().
        The immediate first refresh now runs in start(); this loop just
        sleeps + refreshes."""
        while not self._stop_event.wait(timeout=self._refresh_interval):
            self._refresh()

    async def _loop_async(self) -> None:
        """AppLoop-resident equivalent of _loop. start() runs the first
        _refresh() synchronously so this just iterates the steady state."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self._refresh_interval)
            except asyncio.CancelledError:
                return
            self._refresh()

    def _refresh(self) -> None:
        """Read all source files and update the internal summary atomically."""
        new = MetricsSummary()
        new.refreshed_at = datetime.now(timezone.utc).isoformat()
        try:
            self._read_status(new)
            self._read_monitor_state(new)
            self._read_health(new)
            self._read_last_coaching_ts(new)   # Phase 3 Step 1: independent of process_running
            new.last_5_incidents = self._read_incident_tail()
            self._read_policy_state(new)
        except Exception as exc:
            new.refresh_error = f"{type(exc).__name__}: {exc}"

        with self._lock:
            self._summary = new

    # -- File readers (each is independently fault-tolerant) -----------------

    def _load_json(self, rel_path: str) -> Optional[Dict[str, Any]]:
        """Load a JSON file relative to runtime_dir. Returns None on any error."""
        path = self._runtime_dir / rel_path
        try:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            return None

    def _read_status(self, s: MetricsSummary) -> None:
        """Populate supervisor fields from status.json."""
        data = self._load_json("status.json")
        if data is None:
            return
        # arch: phase 0.7 - supervisor_state added to status.json; tolerate absence in older files
        raw_state = data.get("supervisor_state")
        s.supervisor_state = str(raw_state) if raw_state is not None else None
        # process_running always present
        pr = data.get("process_running")
        s.process_running = bool(pr) if pr is not None else None
        # awaiting_first_heartbeat
        afh = data.get("awaiting_first_heartbeat")
        s.awaiting_first_heartbeat = bool(afh) if afh is not None else None
        # stable_ticks is NOT in status.json - would need a new supervisor field
        s.stable_ticks = None

    def _read_monitor_state(self, s: MetricsSummary) -> None:
        """Populate monitor fields from monitor_state.json."""
        data = self._load_json("monitor_state.json")
        if data is None:
            return
        cf = data.get("consecutive_fails")
        s.consecutive_fails = int(cf) if cf is not None else None
        # Field is "ladder_index" in the live file
        li = data.get("ladder_index")
        s.ladder_idx = int(li) if li is not None else None
        # circuit_breaker.tripped
        cb = data.get("circuit_breaker")
        if isinstance(cb, dict):
            tripped = cb.get("tripped")
            s.circuit_breaker_tripped = bool(tripped) if tripped is not None else None

    def _read_health(self, s: MetricsSummary) -> None:
        """Populate mode from health.json.

        current_mode derivation rule (conservative):
          - Requires BOTH a parseable health.json mode field AND
            s.process_running == True (from status.json already read).
          - If process_running is False or None, current_mode is set to None
            to avoid surfacing a stale mode value from a dead-process heartbeat.
          - If health.json is missing or invalid, current_mode is None.
          - If status.json was missing/invalid (process_running is None),
            current_mode is also None - cannot trust the heartbeat without
            knowing process state.
        """
        # Gate on process_running before reading health.json at all.
        # None means status.json was unavailable - treat as conservative.
        if s.process_running is not True:
            s.current_mode = None
            return
        data = self._load_json("health.json")
        if data is None:
            return
        mode = data.get("mode")
        s.current_mode = str(mode) if mode is not None else None

    def _read_last_coaching_ts(self, s: MetricsSummary) -> None:
        """
        Read per-mode coaching timestamp artifacts and populate s.last_coaching_ts
        with the most recent valid timestamp across all modes.

        Phase 3 Step 1: extends Phase 2 Step 1 SR-only path to cover all modes.
        Artifacts: ops/runtime/coaching_ts_<mode>.json  (mode: sr/aram/arena/brawl/tft)
        Each artifact shape: {"ts": "<ISO-8601 UTC>", "mode": "<mode>"}

        last_coaching_ts = most recent successful coaching timestamp across all modes.
        Missing or malformed individual mode artifacts are non-fatal and ignored.
        """
        _MODES = ("sr", "aram", "arena", "brawl", "tft")
        latest: Optional[str] = None
        for mode in _MODES:
            data = self._load_json(f"coaching_ts_{mode}.json")
            if data is None:
                continue
            ts = data.get("ts")
            if not ts:
                continue
            ts_str = str(ts)
            # Keep the lexicographically latest ISO-8601 UTC string.
            # ISO-8601 UTC strings with consistent formatting sort correctly
            # as plain strings.
            if latest is None or ts_str > latest:
                latest = ts_str
        s.last_coaching_ts = latest

    def _read_policy_state(self, s: MetricsSummary) -> None:
        """
        Read effective policy state from core.feature_policy.get_policy_state().
        Phase 2 Step 2 - MetricsCache is read-only; feature_policy owns the matrix.
        Non-fatal: any import or call error leaves policy fields as None.
        """
        try:
            from core.feature_policy import get_policy_state as _gps
            ps = _gps()
            s.policy_source_status  = ps.get("policy_source_status")
            s.policy_last_reload_ts = ps.get("policy_last_reload_ts")
            s.policy_last_warning   = ps.get("policy_last_warning")
            dec = ps.get("effective_decisions") or {}
            s.policy_sr_live_coaching   = (dec.get("sr")   or {}).get("live_coaching")
            s.policy_aram_live_coaching  = (dec.get("aram")  or {}).get("live_coaching")
            s.policy_arena_live_coaching = (dec.get("arena") or {}).get("live_coaching")
            s.policy_brawl_live_coaching = (dec.get("brawl") or {}).get("live_coaching")
            s.policy_tft_live_coaching   = (dec.get("tft")   or {}).get("live_coaching")
            s.policy_tft_vision_analysis = (dec.get("tft")   or {}).get("tft_vision_analysis")
        except Exception:
            pass  # policy fields stay None on any error

    def _read_incident_tail(self) -> List[Dict[str, Any]]:
        """
        Read the last INCIDENT_TAIL_BYTES of incident_log.jsonl and return
        the most recent MAX_INCIDENTS compact incident dicts.

        Tail strategy:
          1. Open the file and seek to max(0, size - INCIDENT_TAIL_BYTES).
          2. Read from that offset to EOF.
          3. Discard the first (potentially partial) line.
          4. Parse each remaining line as JSON; skip malformed lines.
          5. Return the last MAX_INCIDENTS entries as compact dicts.

        No full-file read ever occurs in this method.
        """
        log_path = self._runtime_dir / "incident_log.jsonl"
        if not log_path.exists():
            return []
        try:
            file_size = log_path.stat().st_size
            if file_size == 0:
                return []
            seek_pos = max(0, file_size - INCIDENT_TAIL_BYTES)
            with log_path.open("rb") as fh:
                fh.seek(seek_pos)
                raw = fh.read()
            # Decode, split lines
            text = raw.decode("utf-8", errors="replace")
            lines = text.splitlines()
            # If we seeked into the middle of a file, the first line is partial
            if seek_pos > 0 and lines:
                lines = lines[1:]
            entries: List[Dict[str, Any]] = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    entries.append({
                        "ts":        e.get("ts", ""),
                        "severity":  e.get("severity", ""),
                        "subsystem": e.get("subsystem", ""),
                        "trigger":   e.get("trigger", ""),
                        "detail":    str(e.get("detail", ""))[:120],
                    })
                except Exception:
                    pass  # skip malformed lines silently
            return entries[-MAX_INCIDENTS:]
        except Exception:
            return []
