"""core/live_benchmark_band_shadow.py - fail-soft LBAND1 band shadow writer.

The "do-not-flip-blind" validation substrate for the LBAND1 live
personal-percentile benchmark bander (``core.live_benchmark_band``). That
module is a pure generator with NO live-coach consumer yet (item 443): at a
checkpoint moment it bands the player's live CS / level against their OWN
historical percentile distribution on the same champion. Before any coach
surfaces those bands, they must be validated on real games. This module
records, alongside live coaching, what LBAND1 WOULD have offered for the same
game state - WITHOUT changing any live output - so the band accuracy can be
reviewed offline first.

Mirrors core.hz_choice_shadow / core.hz_build_shadow / core.det_coach_shadow:
same fail-soft contract (never raises), same default-path-under-data layout,
same engine-version stamp, same coarse-state dedup so the 2Hz /api/state poll
does not flood the log. Unlike the HZ writers it logs ONLY actual band firings
(a non-checkpoint tick yields no band - an expected, uninteresting "miss" - so
recording misses would be pure noise; LBAND1 only fires in a ~90s window per
game).

Every record line is strict JSON (no bare NaN / Infinity token): cs / level /
game_time_s outside their vocabulary are logged as null, a band entry that is
not a JSON-clean dict with a non-blank "band" is dropped, and a call with no
such band left is a gate miss (s144 true-audit).
"""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.live_benchmark_band_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "live_benchmark_band_shadow.jsonl"

# Per-target dedup. The dashboard polls /api/state every ~500ms, so without
# this the same coarse state would be logged ~2x/sec. Keyed by str(target_path)
# so an explicit test path and the live default each dedup independently.
_LAST_SIG: dict[str, str] = {}

# Serializes the dedup check, the append and the sig update. Concurrent
# /api/state builds both passed an unlocked check and both appended: measured
# at audit time, 1020 of 3495 live rows repeated the previous row's sig about
# 70 microseconds later (s144 true-audit F1).
_LOCK = threading.Lock()

# Field vocabularies (s144 true-audit). Same bounds as core.live_benchmark_band.
_MAX_CHAMPION_CHARS = 64
_MAX_MODE_CHARS = 32
_MAX_ACTION_CHARS = 500
_MAX_CS = 10 ** 5
_MIN_LEVEL = 1
_MAX_LEVEL = 30
_MAX_GAME_TIME_S = 10 ** 6


def _label(value, max_chars: int) -> str | None:
    """A stripped non-blank str of at most ``max_chars``, else None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_chars:
        return None
    return text


def _count(value, lo: int, hi: int) -> int | None:
    """An int (not bool) or integral finite float in lo..hi, as an int."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if not math.isfinite(value) or not value.is_integer():
            return None
        n = int(value)
    else:
        return None
    return n if lo <= n <= hi else None


def _clock(value) -> int | float | None:
    """A game time in 0.._MAX_GAME_TIME_S seconds (int kept int), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_GAME_TIME_S else None
    if isinstance(value, float) and math.isfinite(value) and 0.0 <= value <= _MAX_GAME_TIME_S:
        return value + 0.0  # -0.0 -> 0.0
    return None


def _clean_bands(bands) -> list[dict]:
    """The JSON-clean band dicts of a list / tuple, as detached copies.

    A non-dict entry, a dict without a non-blank str "band", and a dict that
    strict JSON cannot carry (NaN, inf, a set, an object) are dropped; the
    copy is the strict-JSON round trip, so the record never aliases the
    caller's dicts."""
    if not isinstance(bands, (list, tuple)):
        return []
    out: list[dict] = []
    for b in bands:
        if not isinstance(b, dict):
            continue
        label = b.get("band")
        if not isinstance(label, str) or not label.strip():
            continue
        try:
            text = json.dumps(b, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            continue
        out.append(json.loads(text))
    return out


def _band_key(bands: list) -> tuple:
    """Stable identity tuple over the banded result for dedup."""
    out = []
    for b in bands:
        if isinstance(b, dict):
            out.append((b.get("checkpoint"), b.get("metric"), b.get("band")))
    return tuple(out)


def log_live_bands(
    mode: str,
    champion: str,
    *,
    bands: list | None,
    game_time_s: float | None = None,
    cs=None,
    level=None,
    native_action: str | None = None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one LBAND1 validation record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss (no champion
    or no bands fired), a dedup skip, or any failure (fail-soft). Never raises -
    safe on the hot path.

    A record is written ONLY when at least one band actually fired (the caller
    is at a checkpoint with a trustworthy distribution); an off-checkpoint tick
    yields no band and is not logged. ``native_action`` captures the live coach
    action for the same tick so the band can be reviewed in context.

    ``champion`` is stripped and 1..64 chars and ``mode`` 1..32 chars, else a
    gate miss. ``cs`` (0..10**5) and ``level`` (1..30) are an int or integral
    float, ``game_time_s`` a number in 0..10**6; anything else is logged as
    null. ``native_action`` is a str capped at 500 chars, else null; a non-str
    ``now_iso`` uses the real clock; ``path`` may be a str.
    """
    try:
        champ = _label(champion, _MAX_CHAMPION_CHARS)
        mode_label = _label(mode, _MAX_MODE_CHARS)
        if champ is None or mode_label is None:
            return None
        band_list = _clean_bands(bands)
        if not band_list:
            return None

        target = Path(path) if path is not None else SHADOW_PATH

        gt = _clock(game_time_s)
        cs_n = _count(cs, 0, _MAX_CS)
        level_n = _count(level, _MIN_LEVEL, _MAX_LEVEL)
        action = native_action[:_MAX_ACTION_CHARS] if isinstance(native_action, str) else None
        gt_bucket = None if gt is None else int(gt // 5)
        sig = str((mode_label, champ, gt_bucket, cs_n, level_n, _band_key(band_list)))

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        with _LOCK:
            if _LAST_SIG.get(str(target)) == sig:
                return None

            if isinstance(now_iso, str):
                ts = now_iso
            else:
                ts = datetime.now(timezone.utc).isoformat()

            record: dict = {
                "ts": ts,
                "mode": mode_label,
                "champion": champ,
                "game_time_s": gt,
                "cs": cs_n,
                "level": level_n,
                "engine_version": ENGINE_VERSION,
                "bands": band_list,
                "native_action": action,
            }
            line = json.dumps(record, allow_nan=False)

            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(line + "\n")
            _LAST_SIG[str(target)] = sig

        return record

    except Exception:
        log.debug("live_benchmark_band_shadow.log_live_bands failed", exc_info=True)
        return None
