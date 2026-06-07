"""core/ds_coach_shadow.py - fail-soft DS-coach shadow-log writer.

Appends one JSON line per call to a .jsonl file so deterministic DS-coach
hints can be analysed offline WITHOUT affecting live coaching output.

Builders are injected at call-time so this module is testable without the
sibling generator modules (core.ds_antitank_hint, core.ds_scaling_hint),
which are built in parallel slices and may not exist at import time.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.ds_coach_shadow")

# Default shadow path - project root is two levels above this file (core/)
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "ds_coach_hints_shadow.jsonl"


def log_coach_hints(
    mode: str,
    my_champion: str,
    enemy_champions: list[str] | None,
    *,
    game_time_s: float | None = None,
    antitank_builder=None,
    scaling_builder=None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one hint record to the shadow jsonl.

    Returns the record dict on success, None on any failure (fail-soft).
    Never raises - safe to call from the hot coach path.
    """
    try:
        # Resolve builders lazily; swallow missing-module errors
        if antitank_builder is None:
            try:
                from core.ds_antitank_hint import build_antitank_hint as antitank_builder  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                log.debug("ds_antitank_hint unavailable - skipping antitank hint")
                return None

        if scaling_builder is None:
            try:
                from core.ds_scaling_hint import build_scaling_hint as scaling_builder  # noqa: PLC0415
            except Exception:  # noqa: BLE001
                log.debug("ds_scaling_hint unavailable - skipping scaling hint")
                return None

        # Resolve engine version best-effort
        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()
        enemies = list(enemy_champions or [])

        record: dict = {
            "ts": ts,
            "mode": mode,
            "my_champion": my_champion,
            "enemy_champions": enemies,
            "game_time_s": game_time_s,
            "engine_version": ENGINE_VERSION,
            "antitank": antitank_builder(my_champion, enemies, mode),
            "scaling": scaling_builder(my_champion, enemies, mode, game_time_s),
        }

        target = path if path is not None else SHADOW_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

        return record

    except Exception:  # noqa: BLE001
        log.debug("ds_coach_shadow.log_coach_hints failed", exc_info=True)
        return None
