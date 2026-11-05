"""core/hz_build_shadow.py - fail-soft HZ-C2 precomputed-BUILD-choice shadow.

The "do-not-flip-blind" validation substrate for the HZ-C2 precomputed BUILD
A/B choice-coach (``core.precomputed_build_coach``). The live coach still
answers "do I pivot anti-tank, and what do I buy" via its Haiku call; this
module records, alongside that live output, which durability VARIANT the
precomputed HZ-B2 table WOULD recommend for the same enemy comp - including
whether the seed table even COVERED the champion - so the precompute path can
be validated against real games offline before any coach flip. WITHOUT changing
any live output.

Mirrors core.hz_choice_shadow / core.det_coach_shadow: fail-soft (never raises),
default path under data/, engine-version stamp, coarse-state dedup. s144: rows
are typed strict JSON on one LF line, appended under a lock; failures WARN.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.hz_build_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "hz_build_shadow.jsonl"
# Per-target coarse-state dedup sig and last LOGGED game_time_s (the
# stale-snapshot freshness guard), both keyed by str(target_path).
_LAST_SIG: dict[str, str] = {}
_LAST_GT: dict[str, float] = {}


def log_precomputed_build(
    mode: str,
    my_champion: str,
    enemy_comp: list | None,
    *,
    lean: str | None,
    choices: list | None,
    covered: bool = False,
    native_action: str | None = None,
    native_choices: list | None = None,
    item_count=None,
    game_time_s: float | None = None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one HZ-C2 validation record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup
    skip, or any failure (fail-soft). Never raises - safe on the hot path. A
    coverage MISS (``covered=False``, ``lean`` may be None, ``choices`` empty)
    is recorded too: the seed coverage rate on real games is a validation
    signal. The gate requires a non-blank operator champion string and a game
    clock that is None (unknown) or a finite real number.

    ``native_action`` / ``native_choices`` capture the LIVE coach output for the
    same tick so the precompute can be compared against what Haiku actually
    said before any flip (the do-not-flip-blind comparison).

    s144 row contract: text fields are strings capped at ``_MAX_TEXT`` or null;
    ``enemy_comp`` is a list of non-blank name strings (at most
    ``_MAX_ENEMIES``); ``choices`` / ``native_choices`` are lists of dicts (at
    most ``_MAX_CHOICES``); ``covered`` is True only for True; ``item_count``
    is a non-negative int or null. The row is strict JSON (a NaN anywhere is
    a refusal) on one LF-terminated line, appended under ``_LOCK`` so
    concurrent /api/state builders cannot both write one tick, after a torn
    tail is terminated. A write failure WARNs once a minute and does not
    advance the dedup."""
    try:
        if not isinstance(my_champion, str) or not my_champion.strip():
            return None
        # RM-1589: NaN / Infinity / bool / string clocks are not a tick.
        if game_time_s is not None and _clock(game_time_s) is None:
            return None
        clock = _clock(game_time_s)

        champ = _text(my_champion)
        mode_s = _text(mode)
        lean_s = _text(lean)
        native = _text(native_action)
        enemies = _names(enemy_comp)
        choice_list = _dicts(choices)
        native_list = _dicts(native_choices)
        covered_b = covered is True
        items = _count(item_count)

        target = _target(path)
        tkey = str(target)

        with _LOCK:
            # Stale-snapshot freshness guard: a post-game liveclient cache
            # keeps serving the final snapshot at a FROZEN game_time_s (cycle
            # 54 observed a ~22-min WAIT-RESPAWN tail at one identical
            # game_time after a game ended). The coarse-state sig re-logs such
            # a tick whenever an incidental field (item_count) drifts, bloating
            # the jsonl + diluting the coverage/dedup denominator. Suppress a
            # tick whose game_time_s equals the last LOGGED tick for this
            # target. Exact equality ONLY - a new game resets game_time below
            # the frozen value, so a "<=" test would wrongly suppress the
            # entire opening of the next game.
            if clock is not None and _LAST_GT.get(tkey) == clock:
                return None

            gt_bucket = int(clock // 5) if clock is not None else 0
            sig = str((
                mode_s, champ, tuple(enemies), lean_s, items,
                gt_bucket, covered_b, len(choice_list),
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
                "enemy_comp": enemies,
                "lean": lean_s,
                "covered": covered_b,
                "item_count": items,
                "game_time_s": game_time_s,
                "engine_version": _text(ENGINE_VERSION) or "?",
                "choices": choice_list,
                "native_action": native,
                "native_choices": native_list,
            }
            try:
                text = json.dumps(record, allow_nan=False)
            except (TypeError, ValueError) as exc:
                # RM-1591: a NaN or an unserialisable object inside a
                # choice is refused, never written as non-strict JSON.
                _warn_once("encode", "hz build shadow row refused", exc)
                return None
            line = (text + "\n").encode("utf-8")

            try:
                _append_line(target, line)
            except OSError as exc:
                _warn_once("write:" + tkey, "hz build shadow write failed", exc)
                return None
            _LAST_SIG[tkey] = sig
            if clock is not None:
                _LAST_GT[tkey] = clock

        return json.loads(text)

    except Exception as exc:  # noqa: BLE001 - fail-soft hot-path contract
        _warn_once("unexpected", "hz build shadow failed", exc)
        return None


# Helpers live BELOW the writer so the log_precomputed_build line citation in
# tests/test_rm443_core_loader_retry.py stays exact.

# RM-1593: one writer at a time, so the dedup check, the append and the
# dedup update are one step for every thread of the dashboard process.
# Measured 2026-11-05 on the live jsonl: 3 rows began mid-record, the
# signature of two unserialised appends overwriting each other's tail.
_LOCK = threading.Lock()

# RM-1592: the longest text value a row carries (Haiku build prose is a
# sentence or two; anything longer is upstream junk, kept as a prefix).
_MAX_TEXT = 2000
# RM-1590 / -228: Arena carries the widest enemy roster; a build A/B is two
# choices. Anything beyond these caps is junk, kept as a prefix.
_MAX_ENEMIES = 16
_MAX_CHOICES = 8

# RM-1595: a failing write WARNs at most once per key per interval.
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


def _names(value: object) -> list[str]:
    """The non-blank string entries of a list / tuple, capped; [] otherwise
    (a bare string is ONE value, not a sequence of one-letter champions)."""
    if not isinstance(value, (list, tuple)):
        return []
    out = [v[:_MAX_TEXT] for v in value if isinstance(v, str) and v.strip()]
    return out[:_MAX_ENEMIES]


def _dicts(value: object) -> list[dict]:
    """The dict entries of a list / tuple, capped; [] otherwise."""
    if not isinstance(value, (list, tuple)):
        return []
    return [v for v in value if isinstance(v, dict)][:_MAX_CHOICES]


def _count(value: object) -> int | None:
    """A non-negative int (bool excluded), or None."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _target(path: object) -> Path:
    """The jsonl target: the caller's Path as given (a subclass is kept), a
    str coerced to a Path, or the module default."""
    if path is None:
        return SHADOW_PATH
    if isinstance(path, Path):
        return path
    return Path(path)


def _append_line(target: Path, line: bytes) -> None:
    """Append one LF-terminated row as bytes (RM-1594: text mode wrote
    CRLF on Windows - 57427 of 57427 live rows, measured 2026-11-05). A file
    whose last byte is not LF (a crash mid-append, or a NUL-filled extent) is
    terminated first, so the torn row stays one unreadable line instead of
    swallowing the new one. Raises OSError."""
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


__all__ = ["SHADOW_PATH", "log_precomputed_build"]
