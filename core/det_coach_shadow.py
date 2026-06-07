"""core/det_coach_shadow.py - fail-soft B1 deterministic-coaching validation writer.

This is the "do-not-flip-blind" validation substrate. resolve_choices() in
dashboard/_deterministic_coaching.py REPLACES the coach's native A/B choices
with the deterministic DS-matchup choices whenever the latter are non-empty;
the discarded native choices are otherwise unrecorded, so the live flip can
never be validated against what Haiku would have offered. This module appends
one JSON line per distinct coarse game state capturing BOTH surfaces (the
deterministic choices/callouts/lead AND the native choices that were thrown
away) so the flip can be audited offline, WITHOUT changing any live output.

Mirrors core.ds_coach_shadow: same fail-soft contract (never raises), same
default-path-under-data layout, same best-effort engine-version stamp.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.det_coach_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "det_coach_shadow.jsonl"

# Per-target dedup. The dashboard polls /api/state every ~500ms, so without
# this the same coarse state would be logged ~2x/sec. Keyed by str(target_path)
# so an explicit test path and the live default each dedup independently.
_LAST_SIG: dict[str, str] = {}


def log_det_coaching(
    mode: str,
    my_champion: str,
    enemy_champions: list[str] | None,
    *,
    det: dict | None,
    native_choices: list | None,
    game_time_s: float | None = None,
    level=None,
    item_count=None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one validation record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup
    skip, or any failure (fail-soft). Never raises - safe on the hot path.
    """
    try:
        # A real game requires both an operator champion and an enemy comp;
        # anything else is a lobby/idle tick we do not validate.
        if not my_champion or not isinstance(my_champion, str):
            return None
        if not enemy_champions:
            return None

        det = det if isinstance(det, dict) else {}
        det_choices = det.get("choices") or []
        replaced = bool(det_choices)

        enemies = [str(e) for e in enemy_champions]
        native_list = list(native_choices or [])

        target = path if path is not None else SHADOW_PATH

        try:
            gt_bucket = int((game_time_s or 0) // 5)
        except (TypeError, ValueError):
            gt_bucket = 0
        sig = str((
            mode, my_champion, tuple(enemies), level, item_count,
            gt_bucket, replaced, len(det_choices), len(native_list),
        ))
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
            "my_champion": my_champion,
            "enemy_champions": enemies,
            "game_time_s": game_time_s,
            "level": level,
            "item_count": item_count,
            "engine_version": ENGINE_VERSION,
            "replaced": replaced,
            "det_choices": det_choices,
            "callouts": det.get("callouts") or [],
            "lead_projection": det.get("lead_projection") or {},
            "native_choices": native_list,
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[str(target)] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("det_coach_shadow.log_det_coaching failed", exc_info=True)
        return None
