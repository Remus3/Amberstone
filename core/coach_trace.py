"""
core/coach_trace.py - persistent ring buffer of coach API calls.

AUDIT 2026-04-28 (proposal 2.5): "Why did the coach say that?" Trace
each call's prompt + context + model response so the dashboard ops tab
can surface the exchange. Also useful for prompt tuning.

File format: JSONL at data/coach_trace.jsonl. Capped at MAX_LINES - older
lines are dropped on append. Best-effort: a write failure logs and
continues; the coach must never crash because the trace file is busy.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from core.prom_metrics import Histogram

_log = logging.getLogger("rc.coach_trace")

_TRACE_FILE = Path(__file__).parent.parent / "data" / "coach_trace.jsonl"
MAX_LINES = 200          # ring-buffer size
_lock = threading.Lock()

# Prometheus instrumentation (T3 #12, 2026-05-01). Every coach API call
# round-trip lands here with `latency_ms` already measured by the caller.
_M_COACH_LATENCY = Histogram(
    "rc_coach_latency_seconds",
    "Wall-clock latency of coach API calls.",
    labelnames=("mode", "model"),
)


def _truncate(s: Any, n: int) -> str:
    if s is None:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "..."


def append(
    *,
    mode: str,
    model: str,
    system_prompt: str = "",
    user_prompt: str = "",
    response: str = "",
    latency_ms: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
    extra: Optional[dict] = None,
) -> None:
    """Append one coach-call record. Best-effort; never raises to caller.

    Prompts/responses are truncated to 4 KB each - the dashboard surfaces
    the full prompt only on demand, and the trace file otherwise grows
    proportional to call count, not content size."""
    rec = {
        "ts":            time.time(),
        "mode":          mode,
        "model":         model,
        "latency_ms":    int(latency_ms),
        "tokens_in":     int(tokens_in),
        "tokens_out":    int(tokens_out),
        "cache_read":    int(cache_read),
        "cache_write":   int(cache_write),
        "system_prompt": _truncate(system_prompt, 4096),
        "user_prompt":   _truncate(user_prompt, 4096),
        "response":      _truncate(response, 4096),
    }
    if extra:
        rec["extra"] = extra
    try:
        _M_COACH_LATENCY.observe(
            (latency_ms or 0) / 1000.0,
            mode=mode or "_unknown",
            model=model or "_unknown",
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("prom_metrics coach_latency: %s", exc)
    try:
        with _lock:
            _TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            with _TRACE_FILE.open("a", encoding="utf-8") as f:
                f.write(line)
            # Trim if oversize. Cheap to keep last MAX_LINES; rare path.
            if _TRACE_FILE.stat().st_size > 1 << 20:  # 1 MiB
                _trim()
    except Exception as exc:  # noqa: BLE001
        _log.debug("coach_trace append failed: %s", exc)


def record_enemy_target(
    *,
    mode: str,
    champion: str,
    base_max_hp: float,
    applied_max_hp: float,
    hp_scale: float,
    tanky_count: int,
    bonus_hp: float = 0.0,
) -> None:
    """Plumb the DSV5 applied comp-conditioned enemy max-HP modifier delta.

    Deterministic-verification seam: the comp-HP-lean target uplift that DSV1's
    burn valuation consumes is otherwise invisible in the trace (only the final
    item ranking shows). Recording ``base_max_hp`` (flat curve) alongside
    ``applied_max_hp`` (post comp-scale) + ``hp_scale`` + ``tanky_count`` lets a
    test - or the ops trace tab - confirm exactly which modifier was applied for
    a given comp. Best-effort; reuses the ``append`` ring buffer + ``extra``.
    """
    append(
        mode=mode,
        model="_enemy_target",
        extra={
            "kind":           "enemy_target",
            "champion":       str(champion),
            "base_max_hp":    round(float(base_max_hp), 1),
            "applied_max_hp": round(float(applied_max_hp), 1),
            "hp_scale":       round(float(hp_scale), 4),
            "tanky_count":    int(tanky_count),
            "bonus_hp":       round(float(bonus_hp), 1),
        },
    )


def _trim() -> None:
    try:
        lines = _TRACE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) <= MAX_LINES:
            return
        kept = lines[-MAX_LINES:]
        tmp = _TRACE_FILE.with_suffix(_TRACE_FILE.suffix + ".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, _TRACE_FILE)
    except Exception as exc:  # noqa: BLE001
        _log.debug("coach_trace trim failed: %s", exc)


def read_recent(limit: int = 50) -> list:
    """Return the most recent `limit` records (newest last) - list[dict]."""
    try:
        if not _TRACE_FILE.exists():
            return []
        lines = _TRACE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        out = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        _log.debug("coach_trace read_recent failed: %s", exc)
        return []
