"""
core/metrics_cache.py
Phase 1 Step 2 - Internal observability surface for Amberstone.

Runs a background thread that reads existing runtime artifacts on a fixed
interval and caches a small derived MetricsSummary.  Consumers call
get_summary() to obtain a thread-safe frozen copy; no file I/O happens
in the caller's thread.

Design rules:
  - Read-only: never writes to any file.
  - Non-fatal AND ISOLATED: missing files, invalid JSON, wrong-typed JSON,
    partial writes and empty logs are all tolerated, and a fault in one
    source file may only blank THAT file's fields.  Every reader runs in
    its own guard, so a bad status.json cannot empty the incident tail or
    the policy block.  Tolerated does not mean silent - each fault is
    named in the summary's refresh_error field.

    Scope of the 2026-08-31 (lane 8 cycle 40) change, stated precisely
    because the previous wording of this block overclaimed in one
    direction and underclaimed in another:

      - Already true before: the four classes named above - missing files,
        INVALID json, partial writes, empty logs - were genuinely
        tolerated, because json.loads raised and _load_json swallowed it.
      - Not true before: WRONG-TYPED json (a file holding a valid list,
        string or number) was not tolerated at all.  It sailed past
        _load_json and reached a .get() call.
      - Not true before: isolation.  All six readers shared one
        try/except, so the first to raise aborted every later one.  One
        wrong-typed field in a coaching timestamp artifact blanked the
        incident list and all nine policy fields, which it has nothing to
        do with.
      - Also corrected: this block used to promise fields set to
        "unknown".  No field is ever set to "unknown"; the _UNKNOWN
        constant was defined and never assigned in the module's whole
        history, and has been removed.  Unavailable fields are None.
  - Derived-state only: no new control-plane fields invented here.
  - No Tk / UI involvement in any path through this module.
  - Python 3.9 compatible: no X|Y unions, no walrus operator, no match.

Input files (all under ops/runtime/):
  status.json              - supervisor state (may predate Phase 0.13a fields)
  monitor_state.json       - SelfMonitor internal state
  health.json              - DevRuntime heartbeat (app liveness + mode)
  incident_log.jsonl       - structured incident entries (may not exist)
  coaching_ts_<mode>.json  - per-mode coaching timestamp artifacts, one per
                             mode in (sr, aram, arena, brawl, tft) (Phase 3
                             Step 1; superseded the Phase 2 Step 1 SR-only
                             last_coaching_ts.json, which this list still
                             named until lane 8 cycle 40)

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


# ---------------------------------------------------------------------------
# Public summary type (plain dataclass-style, 3.9 compat)
# ---------------------------------------------------------------------------

class MetricsSummary:
    """
    Frozen snapshot of the most recent cached metrics.
    All fields may be None if the source file was unavailable or unusable.

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
      last_coaching_ts        str | None  - ISO-8601 UTC timestamp of the most recent
                                            successful coaching write across ALL modes;
                                            None if none has been written yet.  (Phase 3
                                            Step 1 widened this from the Phase 2 Step 1
                                            SR-only path; the "SR-path only" note that
                                            sat here was stale from that widening until
                                            lane 8 cycle 40.)
      last_5_incidents        list        - list of compact incident dicts (may be empty)
      refreshed_at            str         - ISO-8601 UTC timestamp of last refresh
      refresh_error           str | None  - every fault seen during the last refresh,
                                            "; "-joined and each prefixed with the source
                                            artifact it came from; None when clean
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
        """Return a plain dict copy suitable for JSON serialisation.

        Covers every name in __slots__ - the hand-written dict literal this
        replaced emitted 12 of 21 and silently dropped the whole Phase 2
        Step 2 policy block.  It had no consumer at the time, which is
        precisely why the omission survived unnoticed; driving the keys off
        __slots__ means a field added later cannot be forgotten here.

        last_5_incidents is deep-copied for the same reason get_summary()
        rebuilds it: the literal returned the internal list by reference, so
        a caller appending to it mutated the cache.
        """
        out: Dict[str, Any] = {}
        for name in self.__slots__:
            value = getattr(self, name)
            if name == "last_5_incidents":
                value = [dict(entry) for entry in value]
            out[name] = value
        return out


# ---------------------------------------------------------------------------
# MetricsCache
# ---------------------------------------------------------------------------

class MetricsCache:
    """
    Background metrics cache for Amberstone.

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
        except Exception:  # noqa: BLE001
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
        """Signal the refresh loop to stop.

        Waits for the worker on the DAEMON THREAD path only.  On the
        AppLoop path there is nothing to wait on from here: the task is
        cancelled and cancellation is observed by the loop thread.  The
        cancel itself is safe from any thread - AppLoop.spawn_task uses
        asyncio.run_coroutine_threadsafe when called off the loop thread
        (app/_loop.py:75-79), so _task is a concurrent.futures.Future
        whose cancel() is thread-safe.  Blocking on it here would risk
        deadlocking shutdown against the very loop being stopped.
        """
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_s)
        if self._task is not None:
            try: self._task.cancel()
            except Exception: pass  # noqa: BLE001
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
            # .get with a default, not [], so the "Never raises" promise
            # above holds for any entry shape a future writer produces.
            copy.last_5_incidents = [
                {
                    "ts":        e.get("ts", ""),
                    "severity":  e.get("severity", ""),
                    "subsystem": e.get("subsystem", ""),
                    "trigger":   e.get("trigger", ""),
                    "detail":    e.get("detail", ""),
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
        """Read all source files and update the internal summary atomically.

        Each reader is invoked inside its OWN guard.  A reader that raises
        blanks only the fields it owns; every other reader still runs and
        still populates.  Faults are accumulated and surfaced together on
        refresh_error rather than the first one aborting the pass.
        """
        new = MetricsSummary()
        new.refreshed_at = datetime.now(timezone.utc).isoformat()
        faults: List[str] = []

        # (source label, thunk).  The label is the file the reader owns, so
        # refresh_error names the artifact an operator has to go and look at.
        steps = (
            ("status.json",        lambda: self._read_status(new, faults)),
            ("monitor_state.json", lambda: self._read_monitor_state(new, faults)),
            ("health.json",        lambda: self._read_health(new, faults)),
            # Phase 3 Step 1: independent of process_running
            ("coaching_ts_*.json", lambda: self._read_last_coaching_ts(new, faults)),
            ("incident_log.jsonl", lambda: self._read_incident_tail_into(new)),
            ("feature_policy",     lambda: self._read_policy_state(new, faults)),
        )
        for label, step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001
                faults.append(f"{label}: {type(exc).__name__}: {exc}")

        new.refresh_error = "; ".join(faults) if faults else None

        with self._lock:
            self._summary = new

    # -- File readers --------------------------------------------------------
    # Each reader owns one source artifact and is invoked under its own guard
    # in _refresh, so a fault here cannot reach any other reader's fields.

    def _load_json(
        self,
        rel_path: str,
        faults: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Load a JSON mapping relative to runtime_dir.

        Returns None for: an absent file, unreadable bytes, invalid JSON, or
        JSON that parses to anything other than an object.  That last case is
        the one this guard exists for - the annotation has always promised a
        mapping, but the bare json.loads return let a list, string or number
        through to callers that immediately called .get() on it.

        An absent file is normal and is never a fault.  A file that IS there
        and cannot be used IS a fault, and is appended to `faults` when a
        collector is supplied, so tolerating it does not make it silent.
        """
        path = self._runtime_dir / rel_path
        try:
            if not path.exists():
                return None
            parsed = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            if faults is not None:
                faults.append(f"{rel_path}: {type(exc).__name__}: {exc}")
            return None
        if not isinstance(parsed, dict):
            if faults is not None:
                faults.append(
                    f"{rel_path}: expected a JSON object, got {type(parsed).__name__}"
                )
            return None
        return parsed

    @staticmethod
    def _as_int(value: Any, field: str, faults: Optional[List[str]]) -> Optional[int]:
        """Coerce an upstream-supplied field to int without trusting shape.

        int() on a value read straight out of somebody else's JSON is
        unguarded arithmetic: a string like "n/a" raises ValueError and a
        dict raises TypeError.  Both used to abort the whole refresh.
        """
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            if faults is not None:
                faults.append(f"{field}: {type(exc).__name__}: {exc}")
            return None

    def _read_status(
        self, s: MetricsSummary, faults: Optional[List[str]] = None
    ) -> None:
        """Populate supervisor fields from status.json."""
        data = self._load_json("status.json", faults)
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

    def _read_monitor_state(
        self, s: MetricsSummary, faults: Optional[List[str]] = None
    ) -> None:
        """Populate monitor fields from monitor_state.json.

        The three fields are read independently: a wrong-typed
        consecutive_fails must not suppress ladder_index or the circuit
        breaker, which is what the unguarded int() calls used to do.
        """
        data = self._load_json("monitor_state.json", faults)
        if data is None:
            return
        s.consecutive_fails = self._as_int(
            data.get("consecutive_fails"), "monitor_state.json:consecutive_fails", faults
        )
        # Field is "ladder_index" in the live file
        s.ladder_idx = self._as_int(
            data.get("ladder_index"), "monitor_state.json:ladder_index", faults
        )
        # circuit_breaker.tripped
        cb = data.get("circuit_breaker")
        if isinstance(cb, dict):
            tripped = cb.get("tripped")
            s.circuit_breaker_tripped = bool(tripped) if tripped is not None else None

    def _read_health(
        self, s: MetricsSummary, faults: Optional[List[str]] = None
    ) -> None:
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
        data = self._load_json("health.json", faults)
        if data is None:
            return
        mode = data.get("mode")
        s.current_mode = str(mode) if mode is not None else None

    def _read_last_coaching_ts(
        self, s: MetricsSummary, faults: Optional[List[str]] = None
    ) -> None:
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
            # Per-mode isolation: an unusable sr artifact must not stop the
            # aram one from being considered.
            data = self._load_json(f"coaching_ts_{mode}.json", faults)
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

    def _read_policy_state(
        self, s: MetricsSummary, faults: Optional[List[str]] = None
    ) -> None:
        """
        Read effective policy state from core.feature_policy.get_policy_state().
        Phase 2 Step 2 - MetricsCache is read-only; feature_policy owns the matrix.
        Non-fatal: any import or call error leaves policy fields as None, and
        is recorded on refresh_error rather than discarded.
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
        except Exception as exc:  # noqa: BLE001
            # policy fields stay None on any error, but the error is named
            if faults is not None:
                faults.append(f"feature_policy: {type(exc).__name__}: {exc}")

    def _read_incident_tail_into(self, s: MetricsSummary) -> None:
        """Assign the incident tail onto the summary.

        Kept separate from _read_incident_tail so _refresh can drive every
        reader through one uniform (label, thunk) guard table.
        """
        s.last_5_incidents = self._read_incident_tail()

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
            # Read ONE byte before the window when there is one, purely to
            # tell an aligned boundary from a genuine mid-line split.
            #
            # The old code discarded the first line whenever seek_pos > 0.
            # That is wrong when the seek happens to land exactly on a line
            # start: the "partial" line is then a COMPLETE entry and a good
            # incident is thrown away.  Measured 2026-08-31 (lane 8 cycle 40)
            # over 240 record widths: 2 of them land aligned, and both lost a
            # whole entry.  Alignment is not exotic - it is guaranteed for
            # every fixed-width record whose length divides INCIDENT_TAIL_BYTES.
            #
            # The extra byte does not weaken the bounded-memory promise: the
            # read is INCIDENT_TAIL_BYTES + 1.
            probe_pos = seek_pos - 1 if seek_pos > 0 else 0
            with log_path.open("rb") as fh:
                fh.seek(probe_pos)
                raw = fh.read()
            # Decode, split lines
            text = raw.decode("utf-8", errors="replace")
            if seek_pos > 0:
                # text[0] is the byte immediately BEFORE the window.  If it is
                # a newline the window starts on a record boundary and nothing
                # is partial.
                boundary_aligned = text[:1] == "\n"
                lines = text[1:].splitlines()
                if not boundary_aligned and lines:
                    lines = lines[1:]
            else:
                lines = text.splitlines()
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
                except Exception:  # noqa: BLE001
                    pass  # skip malformed lines silently
            return entries[-MAX_INCIDENTS:]
        except Exception:  # noqa: BLE001
            return []
