"""core/hz_build_shadow.py - fail-soft HZ-C2 precomputed-BUILD-choice shadow.

The "do-not-flip-blind" validation substrate for the HZ-C2 precomputed BUILD
A/B choice-coach (``core.precomputed_build_coach``). The live coach still
answers "do I pivot anti-tank, and what do I buy" via its Haiku call; this
module records, alongside that live output, which durability VARIANT the
precomputed HZ-B2 table WOULD recommend for the same enemy comp - including
whether the seed table even COVERED the champion - so the precompute path can
be validated against real games offline before any coach flip. WITHOUT changing
any live output.

Mirrors core.hz_choice_shadow / core.det_coach_shadow: same fail-soft contract
(never raises), same default-path-under-data layout, same engine-version stamp,
same coarse-state dedup so the 2Hz /api/state poll does not flood the log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.hz_build_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "hz_build_shadow.jsonl"

# Per-target dedup keyed by str(target_path).
_LAST_SIG: dict[str, str] = {}


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
    signal. The gate only requires an operator champion.

    ``native_action`` / ``native_choices`` capture the LIVE coach output for the
    same tick so the precompute can be compared against what Haiku actually
    said before any flip (the do-not-flip-blind comparison)."""
    try:
        if not my_champion or not isinstance(my_champion, str):
            return None

        enemies = [str(e) for e in (enemy_comp or []) if e]
        choice_list = list(choices or [])
        target = path if path is not None else SHADOW_PATH

        try:
            gt_bucket = int((game_time_s or 0) // 5)
        except (TypeError, ValueError):
            gt_bucket = 0
        sig = str((
            mode, my_champion, tuple(enemies), lean, item_count,
            gt_bucket, bool(covered), len(choice_list),
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
            "enemy_comp": enemies,
            "lean": lean,
            "covered": bool(covered),
            "item_count": item_count,
            "game_time_s": game_time_s,
            "engine_version": ENGINE_VERSION,
            "choices": choice_list,
            "native_action": native_action,
            "native_choices": list(native_choices or []),
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[str(target)] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("hz_build_shadow.log_precomputed_build failed", exc_info=True)
        return None
