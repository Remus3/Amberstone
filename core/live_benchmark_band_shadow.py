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
"""

from __future__ import annotations

import json
import logging
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
    """
    try:
        if not champion or not isinstance(champion, str):
            return None
        band_list = list(bands or [])
        if not band_list:
            return None

        target = path if path is not None else SHADOW_PATH

        try:
            gt_bucket = int((game_time_s or 0) // 5)
        except (TypeError, ValueError):
            gt_bucket = 0
        sig = str((mode, champion, gt_bucket, cs, level, _band_key(band_list)))
        if _LAST_SIG.get(str(target)) == sig:
            return None

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "mode": mode,
            "champion": champion,
            "game_time_s": game_time_s,
            "cs": cs,
            "level": level,
            "engine_version": ENGINE_VERSION,
            "bands": band_list,
            "native_action": native_action,
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[str(target)] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("live_benchmark_band_shadow.log_live_bands failed", exc_info=True)
        return None
