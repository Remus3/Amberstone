"""core/hz_choice_shadow.py - fail-soft HZ-C1 precomputed-choice shadow writer.

The "do-not-flip-blind" validation substrate for the HZ-C1 precomputed A/B
choice-coach (``core.precomputed_laning_coach``). The live coach still answers
"trade / all-in / back off" via its Haiku call; this module records, alongside
that live output, what the PRECOMPUTED laning table WOULD have offered for the
same game state - including whether the seed table even COVERED the matchup -
so the precompute path can be validated against real games offline before any
coach is flipped off its Haiku call. WITHOUT changing any live output.

Mirrors core.det_coach_shadow / core.ds_coach_shadow: same fail-soft contract
(never raises), same default-path-under-data layout, same engine-version stamp,
same coarse-state dedup so the 2Hz /api/state poll does not flood the log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.hz_choice_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "hz_choice_shadow.jsonl"

# Per-target dedup. The dashboard polls /api/state every ~500ms, so without
# this the same coarse state would be logged ~2x/sec. Keyed by str(target_path)
# so an explicit test path and the live default each dedup independently.
_LAST_SIG: dict[str, str] = {}


def log_precomputed_choices(
    mode: str,
    my_champion: str,
    enemy: str | None,
    *,
    choices: list | None,
    band: str | None = None,
    mana_state: str | None = None,
    cd_state: str | None = None,
    covered: bool = False,
    native_action: str | None = None,
    native_choices: list | None = None,
    game_time_s: float | None = None,
    level=None,
    item_count=None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one HZ-C1 validation record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup
    skip, or any failure (fail-soft). Never raises - safe on the hot path.

    A record is written even when the seed table did NOT cover the matchup
    (``covered=False``, ``enemy`` may be None and ``choices`` empty): the
    coverage rate of the seed table on real games is itself a validation
    signal. The gate only requires an operator champion (a real in-game tick);
    ``enemy`` None is allowed for the coverage-miss record.

    ``native_action`` / ``native_choices`` capture the LIVE coach output (the
    Haiku prose action + its native A/B choices) for the same tick, so the
    precompute can be compared against what Haiku actually said before any
    flip - the comparison the do-not-flip-blind gate ultimately needs."""
    try:
        if not my_champion or not isinstance(my_champion, str):
            return None

        choice_list = list(choices or [])
        target = path if path is not None else SHADOW_PATH

        try:
            gt_bucket = int((game_time_s or 0) // 5)
        except (TypeError, ValueError):
            gt_bucket = 0
        sig = str((
            mode, my_champion, enemy, band, mana_state, cd_state,
            level, item_count, gt_bucket, bool(covered), len(choice_list),
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
            "enemy": enemy,
            "band": band,
            "mana_state": mana_state,
            "cd_state": cd_state,
            "covered": bool(covered),
            "game_time_s": game_time_s,
            "level": level,
            "item_count": item_count,
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
        log.debug("hz_choice_shadow.log_precomputed_choices failed", exc_info=True)
        return None
