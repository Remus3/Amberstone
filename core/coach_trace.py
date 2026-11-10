"""
core/coach_trace.py - persistent ring buffer of coach API calls.

AUDIT 2026-04-28 (proposal 2.5): "Why did the coach say that?" Trace
each call's prompt + context + model response so the dashboard ops tab
can surface the exchange. Also useful for prompt tuning.

File format: JSONL at data/coach_trace.jsonl, one strict-JSON object per
line (no NaN / Infinity tokens: /api/coach/trace serialises with
allow_nan=False). Trimmed once the file passes _TRIM_TRIGGER_BYTES, down to
the newest MAX_LINES lines AND at most _TRIM_TARGET_BYTES, so a trim leaves
headroom and the next appends do not each rewrite the file. Best-effort:
a write failure logs and continues, and junk caller values (None, a
non-numeric string, NaN) are coerced, never raised - the coach must never
crash because the trace file is busy or a usage field was missing.

Lane 8 true-audit (s144 cycle 238) measured and closed: the record was built
outside the try, so int() over a junk count raised into the coach; a
non-finite float in `extra` was written as a bare NaN token that 500ed the
strict trace route; read_recent(0) returned the whole file; and with 200
lines at 1.49 MB live, every append re-read and rewrote the file because the
trim cut by line count only. Tests: tests/test_coach_trace_true_audit_s144t238.py.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any, Optional

from core.polled_json import atomic_write_text
from core.prom_metrics import Histogram

_log = logging.getLogger("rc.coach_trace")

_TRACE_FILE = Path(__file__).parent.parent / "data" / "coach_trace.jsonl"
MAX_LINES = 200          # ring-buffer size (upper bound on lines kept by a trim)
# A trim fires once the file passes the trigger and cuts to at most the
# target, so the gap between them is the append headroom before the next
# trim. The old single 1 MiB threshold with a line-count-only cut re-trimmed
# on EVERY append once MAX_LINES records outgrew it (measured live: 200 lines,
# 1491674 bytes, avg 7458 B/line).
_TRIM_TRIGGER_BYTES = 2 << 20   # 2 MiB
_TRIM_TARGET_BYTES = 1 << 20    # 1 MiB
_TRUNCATE_CHARS = 4096
_ELLIPSIS = "..."
_SCRUB_MAX_DEPTH = 16
_lock = threading.Lock()

# Prometheus instrumentation (T3 #12, 2026-05-01). Every coach API call
# round-trip lands here with `latency_ms` already measured by the caller.
_M_COACH_LATENCY = Histogram(
    "rc_coach_latency_seconds",
    "Wall-clock latency of coach API calls.",
    labelnames=("mode", "model"),
)


def _truncate(s: Any, n: int) -> str:
    """str(s) cut to at most `n` characters, ending in "..." when cut."""
    if s is None:
        return ""
    s = str(s)
    n = max(0, n)
    if len(s) <= n:
        return s
    if n <= len(_ELLIPSIS):
        return s[:n]
    return s[: n - len(_ELLIPSIS)] + _ELLIPSIS


def _num(value: Any) -> float:
    """A finite float for `value`, else 0.0 (None, junk string, NaN, inf,
    any non-number). Feeds the int() calls in append's record."""
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _rounded_or_none(value: Any, ndigits: int) -> Optional[float]:
    """round(float(value), ndigits), or None when `value` is not a finite
    number - the trace records "unknown" rather than raising or inventing 0."""
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(out, ndigits) if math.isfinite(out) else None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return int(out) if math.isfinite(out) else None


def _scrub(obj: Any, depth: int = 0) -> Any:
    """A strict-JSON-safe copy of `obj`: non-finite floats become None,
    non-JSON values become str(), and nesting past _SCRUB_MAX_DEPTH (which
    also ends a circular reference) becomes a placeholder string."""
    if depth > _SCRUB_MAX_DEPTH:
        return "<depth limit>"
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _scrub(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_scrub(v, depth + 1) for v in obj]
    return str(obj)


def _dumps(rec: dict) -> str:
    """One strict-JSON line for `rec`. The fast path is a plain dump; any
    value it cannot write strictly (NaN, an object, a cycle) falls back to
    the scrubbed copy, so the call record itself is never lost."""
    try:
        return json.dumps(rec, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return json.dumps(_scrub(rec), ensure_ascii=False, allow_nan=False)


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

    Prompts/responses are truncated to 4096 characters each - the dashboard
    surfaces the full prompt only on demand, and the trace file otherwise
    grows proportional to call count, not content size. A numeric field that
    is not a finite number is recorded as 0."""
    try:
        rec = {
            "ts":            time.time(),
            "mode":          mode,
            "model":         model,
            "latency_ms":    int(_num(latency_ms)),
            "tokens_in":     int(_num(tokens_in)),
            "tokens_out":    int(_num(tokens_out)),
            "cache_read":    int(_num(cache_read)),
            "cache_write":   int(_num(cache_write)),
            "system_prompt": _truncate(system_prompt, _TRUNCATE_CHARS),
            "user_prompt":   _truncate(user_prompt, _TRUNCATE_CHARS),
            "response":      _truncate(response, _TRUNCATE_CHARS),
        }
        if extra:
            rec["extra"] = extra
        line = _dumps(rec) + "\n"
    except Exception as exc:  # noqa: BLE001 - contract: never raise to the coach
        _log.debug("coach_trace record build failed: %s", exc)
        return
    try:
        _M_COACH_LATENCY.observe(
            rec["latency_ms"] / 1000.0,
            mode=mode or "_unknown",
            model=model or "_unknown",
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("prom_metrics coach_latency: %s", exc)
    try:
        with _lock:
            _TRACE_FILE.parent.mkdir(parents=True, exist_ok=True)
            # newline="\n": LF on Windows too, matching _trim's LF rewrite of
            # this same file (RM-481 residual, RM-1698).
            with _TRACE_FILE.open("a", encoding="utf-8", newline="\n") as f:
                f.write(line)
            if _TRACE_FILE.stat().st_size > _TRIM_TRIGGER_BYTES:
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
    A value that is not a finite number is recorded as None, never raised.
    """
    try:
        champ = _truncate(champion, 64)
    except Exception as exc:  # noqa: BLE001 - contract: never raise to the caller
        _log.debug("coach_trace enemy_target champion unprintable: %s", exc)
        champ = ""
    append(
        mode=mode,
        model="_enemy_target",
        extra={
            "kind":           "enemy_target",
            "champion":       champ,
            "base_max_hp":    _rounded_or_none(base_max_hp, 1),
            "applied_max_hp": _rounded_or_none(applied_max_hp, 1),
            "hp_scale":       _rounded_or_none(hp_scale, 4),
            "tanky_count":    _int_or_none(tanky_count),
            "bonus_hp":       _rounded_or_none(bonus_hp, 1),
        },
    )


def _trim() -> None:
    """Keep the newest lines: at most MAX_LINES and at most
    _TRIM_TARGET_BYTES (the newest line is always kept). Caller holds _lock."""
    try:
        lines = _TRACE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        kept: list = []
        total = 0
        for raw_line in reversed(lines):
            if len(kept) >= MAX_LINES:
                break
            size = len(raw_line.encode("utf-8")) + 1
            if kept and total + size > _TRIM_TARGET_BYTES:
                break
            kept.append(raw_line)
            total += size
        kept.reverse()
        atomic_write_text(_TRACE_FILE, "\n".join(kept) + "\n")
    except Exception as exc:  # noqa: BLE001
        _log.debug("coach_trace trim failed: %s", exc)


def _nonfinite_to_none(_token: str) -> None:
    """json parse_constant hook: a legacy NaN / Infinity token reads as None,
    so one old line cannot 500 the strict /api/coach/trace serialiser."""
    return


def read_recent(limit: int = 50) -> list:
    """Return the most recent `limit` records (newest last) - list[dict].

    A non-positive or non-integer `limit` returns []; lines that are not a
    JSON object are skipped."""
    try:
        n = int(limit)
    except (TypeError, ValueError, OverflowError):
        return []
    try:
        if not _TRACE_FILE.exists():
            return []
        lines = _TRACE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        _log.debug("coach_trace read_recent failed: %s", exc)
        return []
    out = []
    for raw_line in reversed(lines):
        if len(out) >= n:  # also ends a non-positive n at once: []
            break
        line = raw_line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line, parse_constant=_nonfinite_to_none)
        except (ValueError, RecursionError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    out.reverse()
    return out
