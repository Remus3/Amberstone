"""core/objective_playbook_shadow.py - fail-soft RC2 P5.5 (WS3) playbook shadow.

The "do-not-flip-blind" validation substrate for the deterministic objective
playbook (``core.objective_playbook``): per live tick it records the
deterministic playbook directive beside the native Haiku ``objective`` prose to
``data/objective_playbook_shadow.jsonl`` so agreement is measured on accrued
real games BEFORE any served-field flip (the playbook ROW already ships additive).

Mirrors ``core.hz_choice_shadow``: never raises, default path under data/,
engine-version stamp, coarse-state dedup plus an exact-game_time freshness guard
so the 2Hz /api/state poll does not flood the log. s144: rows are typed, LF-only,
strict JSON, appended under a lock, and a write failure WARNs once a minute."""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.objective_playbook_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "objective_playbook_shadow.jsonl"

# Per-target coarse-state dedup, keyed by str(target_path) (mirrors
# hz_choice_shadow) so an explicit test path and the live default dedup
# independently.
_LAST_SIG: dict[str, str] = {}

# Per-target last LOGGED game_time_s, for the exact-equality freshness guard.
_LAST_GT: dict[str, float] = {}


def log_objective_playbook(
    mode: str,
    my_champion: str,
    *,
    playbook: dict | None = None,
    native_objective: str | None = None,
    lead_state: str | None = None,
    phase: str | None = None,
    game_time_s: float | None = None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one WS3 playbook validation record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup skip,
    or any failure (fail-soft). Never raises - safe on the hot path.

    A record is written even when ``playbook`` is None (no contestable objective
    in range): a tick where Haiku emits an ``objective`` but the deterministic
    table is silent is itself a validation signal. The gate requires an
    operator champion (a real in-game tick) and refuses a test-only signature
    (``is_test_signature``: no game clock, or a placeholder champion) and a
    clock that is not a finite real number; the caller additionally gates on a
    live liveclient champion.

    Every text field is a string capped at ``_MAX_TEXT`` or null (a non-string
    upstream value is recorded as null, never verbatim). The row is strict
    JSON on one LF-terminated line, appended under ``_LOCK`` so concurrent
    /api/state builders cannot both write one tick; a torn tail left by a crash
    is terminated first so the new row is never glued onto it."""
    try:
        if not isinstance(my_champion, str) or not my_champion.strip():
            return None
        # RM-872: refuse BEFORE the dedup, so a refused row records no
        # signature that could suppress the next real tick in its bucket.
        if is_test_signature(my_champion, game_time_s):
            return None
        # RM-1583: NaN / Infinity / bool / string clocks are not a tick.
        clock = _clock(game_time_s)
        if clock is None:
            return None

        play = playbook if isinstance(playbook, dict) else None
        playbook_tag = _text(play.get("tag")) if play else None
        playbook_line = _text(play.get("line")) if play else None
        native = _text(native_objective)
        mode_s = _text(mode)
        lead = _text(lead_state)
        phase_s = _text(phase)
        champ = _text(my_champion)

        target = _target(path)
        tkey = str(target)

        with _LOCK:
            # Exact-game_time freshness guard (mirrors hz_choice_shadow): a
            # post-game liveclient cache keeps serving the final snapshot at a
            # FROZEN game_time_s; suppress a tick whose game_time equals the
            # last LOGGED tick for this target. Exact equality ONLY - a new
            # game resets game_time below the frozen value.
            if _LAST_GT.get(tkey) == clock:
                return None

            gt_bucket = int(clock // 5)
            sig = str((
                mode_s, champ, gt_bucket, playbook_tag, playbook_line,
                lead, native,
            ))
            if _LAST_SIG.get(tkey) == sig:
                return None

            try:
                from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
            except Exception:  # noqa: BLE001 - stamp only; the row still lands
                ENGINE_VERSION = "?"  # type: ignore[assignment]

            ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

            record: dict = {
                "ts": _text(ts),
                "mode": mode_s,
                "my_champion": champ,
                "game_time_s": game_time_s,
                "phase": phase_s,
                "lead_state": lead,
                "playbook_tag": playbook_tag,
                "playbook_line": playbook_line,
                # The live Haiku objective prose for the same tick - the
                # comparison the do-not-flip-blind gate needs before any
                # served-field flip.
                "native_objective": native,
                "engine_version": _text(ENGINE_VERSION) or "?",
            }
            line = (json.dumps(record, allow_nan=False) + "\n").encode("utf-8")

            try:
                _append_line(target, line)
            except OSError as exc:
                _warn_once(tkey, "objective playbook shadow write failed", exc)
                return None
            _LAST_SIG[tkey] = sig
            _LAST_GT[tkey] = clock

        return record

    except Exception as exc:  # noqa: BLE001 - fail-soft hot-path contract
        _warn_once("unexpected", "objective playbook shadow failed", exc)
        return None


# Helpers and the RM-872 test-only signature live BELOW the writer so the
# SHADOW_PATH / log_objective_playbook line citations in
# tests/test_suite_does_not_write_live_tree.py and
# tests/test_rm443_core_loader_retry.py stay exact.

# RM-1586: one writer at a time, so the dedup check, the append and the
# dedup update are one step for every thread of the dashboard process.
_LOCK = threading.Lock()

# RM-1584: the longest text value a row carries (Haiku objective prose is a
# sentence or two; anything longer is upstream junk, kept as a prefix).
_MAX_TEXT = 2000

# RM-1588: a failing write WARNs at most once per key per interval.
_WARN_INTERVAL_S = 60.0
_WARN_AT: dict[str, float] = {}
_now = time.monotonic


def _clock(value: object) -> float | None:
    """The game clock as a finite float, or None for anything else (bool,
    string, bytes, container, NaN, +/-Infinity, an int beyond float range)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except (OverflowError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _text(value: object) -> str | None:
    """A string capped at _MAX_TEXT, or None for any non-string value."""
    if not isinstance(value, str):
        return None
    return value[:_MAX_TEXT]


def _target(path: object) -> Path:
    """The jsonl target: the caller's Path as given (a subclass is kept), a
    str coerced to a Path, or the module default."""
    if path is None:
        return SHADOW_PATH
    if isinstance(path, Path):
        return path
    return Path(path)


def _append_line(target: Path, line: bytes) -> None:
    """Append one LF-terminated row as bytes. A file whose last byte is not
    LF (a crash mid-append) is terminated first, so the torn row stays one
    unreadable line instead of swallowing the new one. Raises OSError."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a+b") as fh:
        fh.seek(0, 2)
        end = fh.tell()
        if end:
            fh.seek(end - 1)
            if fh.read(1) != b"\n":
                line = b"\n" + line
        fh.write(line)


def _warn_once(key: str, what: str, exc: BaseException) -> None:
    """WARNING once per key per _WARN_INTERVAL_S, DEBUG otherwise. Never
    raises; the message carries the exception class and text only."""
    try:
        now = _now()
        last = _WARN_AT.get(key)
        if last is not None and now - last < _WARN_INTERVAL_S:
            log.debug("%s: %s: %s", what, type(exc).__name__, exc)
            return
        _WARN_AT[key] = now
        log.warning("%s (%s: %s); rows are dropped until it recovers",
                    what, type(exc).__name__, exc)
    except Exception:  # noqa: BLE001 - logging must not break the hot path
        return


# RM-872 - the test-only row signature.
#
# Measured 2026-10-25 on the live data/objective_playbook_shadow.jsonl: 3314 of
# 49788 rows were suite leakage, written through dashboard/_state_builder.py
# before RM-406 redirected this module in tests/conftest.py. Every one had
# game_time_s None (build_state harnesses that hand liveclient_summary a bare
# {"champion": ...}) or the generated placeholder champion "Champ0"; no other
# row had either. A real tick never does: the only production liveclient
# source, dashboard/_liveclient.py liveclient_summary, stamps game_time_s (an
# int, 0 at load) before it can stamp champion and returns {} on any failure,
# and no League champion is named Champ<digits>. Refuse, not tag: a tag makes
# every reader learn a flag (the RM-852 / RM-867 reasoning).
_PLACEHOLDER_PREFIX = "Champ"


def is_test_signature(my_champion: object, game_time_s: object) -> bool:
    """True for a row only a test can produce: no game clock, or a generated
    placeholder champion name (``Champ0``, ``Champ12``). A game clock of 0 is
    real (load screen). Never raises."""
    if game_time_s is None:
        return True
    if not isinstance(my_champion, str):
        return False
    tail = my_champion[len(_PLACEHOLDER_PREFIX):]
    return (my_champion.startswith(_PLACEHOLDER_PREFIX) and tail.isascii()
            and tail.isdigit())


__all__ = ["SHADOW_PATH", "is_test_signature", "log_objective_playbook"]
