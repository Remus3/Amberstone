"""
core/coaching_timestamps.py
Phase 3 Step 1 -- Per-mode coaching timestamp writer.

Writes ops/runtime/coaching_ts_<mode>.json after each successful coaching
payload write for a given mode.  Consumed by MetricsCache to compute the
most recent successful coaching timestamp across all modes.

Design rules:
  - One artifact per mode under ops/runtime/ so writers never contend on
    a shared file.
  - Atomic write via .tmp then replace (same pattern as coach_integration).
  - Non-fatal: any write error is silently ignored.
  - Only called on SUCCESSFUL coaching payload writes; never on
    status/error/timeout/disabled-placeholder writes.
  - No Tk.  No threading of its own.  No GameEnvelope touch.
  - Python 3.9 compatible.

Artifact path: ops/runtime/coaching_ts_<mode>.json
Artifact shape: {"ts": "<ISO-8601 UTC>", "mode": "<mode>"}
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_log = logging.getLogger("rc.coaching_ts")

_PROJECT_DIR = Path(__file__).parent.parent
_RUNTIME_DIR = _PROJECT_DIR / "ops" / "runtime"

# Valid mode keys -- one artifact per mode
_VALID_MODES = {"sr", "aram", "arena", "brawl", "tft"}


def write_coaching_ts(mode: str,
                      runtime_dir: Optional[Path] = None) -> None:
    """
    Write a per-mode coaching timestamp artifact after a successful coaching write.

    Parameters
    ----------
    mode        : "sr" | "aram" | "arena" | "brawl" | "tft"
    runtime_dir : optional override for ops/runtime/ (test seam only)

    Non-fatal: errors are caught and logged at DEBUG level.
    """
    # P2-W1-B (2026-06-11): honor the non-fatal contract for non-str modes
    # too - mode.lower() on None/int raised AttributeError before the try.
    if not isinstance(mode, str):
        _log.debug("coaching_ts: non-str mode %r -- skipped", mode)
        return
    mode_key = mode.lower().strip()
    if mode_key not in _VALID_MODES:
        _log.debug("coaching_ts: unknown mode %r -- skipped", mode_key)
        return

    rt = Path(runtime_dir) if runtime_dir is not None else _RUNTIME_DIR
    try:
        rt.mkdir(parents=True, exist_ok=True)
        ts_file = rt / f"coaching_ts_{mode_key}.json"
        ts_tmp  = ts_file.with_suffix(".tmp")
        ts_tmp.write_text(
            json.dumps({
                "ts":   datetime.now(timezone.utc).isoformat(),
                "mode": mode_key,
            }),
            encoding="utf-8",
        )
        ts_tmp.replace(ts_file)
    except Exception as exc:
        _log.debug("coaching_ts: write failed for mode %r: %s", mode_key, exc)
