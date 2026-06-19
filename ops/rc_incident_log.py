"""
ops/rc_incident_log.py

Structured incident logging for the Riot Commander self-monitor.
Writes newline-delimited JSON to ops/runtime/incident_log.jsonl.
Maintains a rolling summary file readable by Claude at session start.

Log entry schema:
  ts          ISO-8601 UTC timestamp
  severity    DEBUG | INFO | WARN | ERROR | CRITICAL
  subsystem   app | supervisor | monitor | validator | deploy | coach | tft | lcu
  trigger     what caused this entry (heartbeat_stale, api_timeout, etc.)
  action      what the monitor did (none, thread_restart, hot_reload, app_restart, etc.)
  result      ok | failed | skipped | pending
  duration_ms how long the action took (-1 if not applicable)
  detail      optional human-readable note
  run_id      optional: run_id of the app process that triggered this entry

Phase 0.3 changes:
  [5] threading.Lock added - all mutations to _recent, _append_line, write_summary,
      and purge_old are serialized. IncidentLog is now safe for concurrent calls from
      the SelfMonitor-Main and SelfMonitor-Cmd threads, and from the supervisor thread.
  [4] run_id added to every log entry when supplied via IncidentLog(run_id=...) or
      via record(run_id=...) override.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# -- Constants ----------------------------------------------------------------

SEVERITIES = ("DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")
SUBSYSTEMS  = ("app", "supervisor", "monitor", "validator", "deploy", "coach", "tft", "lcu")
ACTIONS     = ("none", "health_check", "thread_restart", "panel_rebuild",
               "hot_reload", "app_restart", "rollback", "monitor_on",
               "monitor_off", "monitor_pause", "monitor_resume")
RESULTS     = ("ok", "failed", "skipped", "pending")


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class IncidentLog:
    """
    Thread-safe structured incident logger.

    Thread safety (Phase 0.3):
      A single threading.Lock serialises all state mutations:
        - _recent list append / trim
        - _append_line (file write)
        - write_summary (file write + reads)
        - purge_old (file rewrite)

      The lock is non-reentrant but all public methods acquire it independently
      and do not call each other while holding it, so there is no deadlock risk.

      Callers from different threads (SelfMonitor-Main, SelfMonitor-Cmd, supervisor
      main loop) may call record() concurrently - they will serialise at the lock.

    run_id context (Phase 0.3):
      - Set at construction time via run_id= parameter (populated by supervisor from
        the adopted/owned app run_id).
      - Can be overridden per-call via record(run_id=...).
      - Written to every entry where it is non-empty.
    """

    def __init__(
        self,
        runtime_dir:    Path,
        retention_days: int          = 7,
        run_id:         Optional[str] = None,
    ) -> None:
        self.runtime_dir    = Path(runtime_dir)
        self.log_file       = self.runtime_dir / "incident_log.jsonl"
        self.summary_file   = self.runtime_dir / "incident_summary.json"
        self.retention_days = retention_days
        self._run_id        = run_id or ""         # context run_id for all entries
        self._session_id    = ""                   # populated by set_process_identity
        self._recent: list[Dict[str, Any]] = []    # in-memory last 50 entries
        self._lock          = threading.Lock()     # serialises ALL state mutations
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def set_run_id(self, run_id: str) -> None:
        """Update the context run_id. Kept for backward compat; prefer set_process_identity."""
        with self._lock:
            self._run_id = run_id or ""

    def set_process_identity(self, run_id: str, session_id: str = "") -> None:
        """
        Set both run_id and session_id from the adopted/owned process identity.
        Called by supervisor after the first healthy heartbeat establishes owned identity.
        All subsequent entries include run_id and session_id when non-empty.
        """
        with self._lock:
            self._run_id     = run_id     or ""
            self._session_id = session_id or ""

    # -- Public API ------------------------------------------------------------

    def record(
        self,
        severity:    str,
        subsystem:   str,
        trigger:     str,
        action:      str           = "none",
        result:      str           = "ok",
        duration_ms: int           = -1,
        detail:      str           = "",
        run_id:      Optional[str] = None,   # per-call override; falls back to self._run_id
    ) -> Dict[str, Any]:
        """Append one structured entry. Returns the entry dict. Thread-safe."""
        effective_run_id = run_id if run_id is not None else self._run_id
        entry: Dict[str, Any] = {
            "ts":          _utc(),
            "severity":    severity  if severity  in SEVERITIES else "INFO",
            "subsystem":   subsystem if subsystem in SUBSYSTEMS  else "app",
            "trigger":     trigger,
            "action":      action    if action    in ACTIONS     else "none",
            "result":      result    if result    in RESULTS     else "ok",
            "duration_ms": int(duration_ms),
            "detail":      str(detail)[:300],
        }
        if effective_run_id:
            entry["run_id"] = effective_run_id

        with self._lock:
            # Read session_id, append entry, trim _recent - all under one lock acquire
            if self._session_id:
                entry["session_id"] = self._session_id
            self._append_line_locked(entry)
            self._recent.append(entry)
            if len(self._recent) > 50:
                self._recent = self._recent[-50:]
        return entry

    def write_summary(self, monitor_state: Optional[Dict[str, Any]] = None) -> None:
        """Rewrite the summary file. Thread-safe."""
        with self._lock:
            all_entries = self._load_recent_entries_locked(hours=24)
            recent_copy = list(self._recent[-20:])

        recent_errors = [e for e in all_entries if e.get("severity") in ("WARN", "ERROR", "CRITICAL")]
        counts: Dict[str, int] = {}
        for e in all_entries:
            k = f"{e.get('subsystem','?')}.{e.get('trigger','?')}"
            counts[k] = counts.get(k, 0) + 1

        summary: Dict[str, Any] = {
            "generated_at":    _utc(),
            "last_24h_count":  len(all_entries),
            "error_count_24h": len(recent_errors),
            "top_triggers":    sorted(counts.items(), key=lambda x: -x[1])[:10],
            "last_errors":     recent_errors[-10:],
            "last_50_entries": recent_copy,
        }
        if monitor_state:
            summary["monitor_state"] = monitor_state

        try:
            _atomic_write(self.summary_file, summary)
        except Exception:  # noqa: BLE001
            pass

    def purge_old(self) -> int:
        """Delete log entries older than retention_days. Thread-safe. Returns lines removed."""
        with self._lock:
            return self._purge_old_locked()

    # -- Internal (call only while holding self._lock) --------------------------

    def _append_line_locked(self, entry: Dict[str, Any]) -> None:
        """Append one JSON line to the log file. Caller must hold self._lock."""
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass  # never let logging crash the monitor

    def _load_recent_entries_locked(self, hours: int = 24) -> list[Dict[str, Any]]:
        """Load entries from last N hours from the .jsonl file. Caller must hold lock."""
        if not self.log_file.exists():
            return []
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        entries: list[Dict[str, Any]] = []
        try:
            for line in self.log_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                    if e.get("ts", "") >= cutoff:
                        entries.append(e)
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        return entries

    def _purge_old_locked(self) -> int:
        """Rewrite log file keeping only entries within retention window. Caller must hold lock."""
        if not self.log_file.exists():
            return 0
        cutoff_ts = (datetime.now(timezone.utc) -
                     timedelta(days=self.retention_days)).isoformat()
        kept: list[str] = []
        removed = 0
        try:
            for line in self.log_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("ts", "9999") >= cutoff_ts:
                        kept.append(line)
                    else:
                        removed += 1
                except Exception:  # noqa: BLE001
                    kept.append(line)  # keep malformed lines
            if removed:
                self.log_file.write_text("\n".join(kept) + "\n", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return removed
