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

# Per-target last LOGGED game_time_s, for the stale-snapshot freshness guard
# (see log_precomputed_choices). Keyed by str(target_path) like _LAST_SIG.
_LAST_GT: dict[str, float] = {}

# RM-158 writer gate. The shipped laning_scenarios_arena.json is a byte copy of
# the SR table (ARENA had no gross-income row, so the generator had nothing left
# to differentiate at schema v3), which means the PRECOMPUTE column of an arena
# record is SR content wearing an arena label. The native half of the same
# record - native_action, champion, band, level, game_time_s - is a genuine
# Arena observation and must survive, so the record is written PRE-FLAGGED
# rather than suppressed: a consumer excludes the poisoned column by testing
# this key, and keeps the observation. Self-clearing - the tag stops being
# stamped the moment a table with ARENA's own economy is served.
SR_COPY_TAG: str = "sr_copy_rm158"
PRECOMPUTE_SOURCE_KEY: str = "precompute_source"

_DS_MODE_BY_KEY: dict[str, str] = {"sr": "SR", "aram": "ARAM", "arena": "ARENA"}


def precompute_source_tag(mode: object) -> str | None:
    """``SR_COPY_TAG`` when ``mode``'s served laning table carries SR's economy.

    The test is the ROOT CAUSE, not a content heuristic: a per-mode table whose
    ``dimensions.economy.income_per_min`` equals the SR rate, for a mode whose
    registered rate is NOT the SR rate, was generated without that mode's income
    row and is the SR table. Cheap on the hot path - ``load_laning_scenarios``
    is mtime-cached and the caller has already loaded the same payload to build
    ``choices``. Fail-soft ``None`` on any error (never raises).
    """
    try:
        from core import lead_projection as _lead  # noqa: PLC0415
        from core.laning_scenario_precompute import (  # noqa: PLC0415
            load_laning_scenarios,
        )

        mode_key = str(mode or "").lower()
        ds_mode = _DS_MODE_BY_KEY.get(mode_key)
        if ds_mode is None:
            return None
        sr_rate = float(_lead.gold_income_per_min("SR"))
        registered = float(_lead.gold_income_per_min(ds_mode))
        if registered == sr_rate:
            # SR itself, or a mode that legitimately shares the SR rate - the
            # signature cannot distinguish a copy from a correct table here.
            return None
        economy = (load_laning_scenarios(mode_key).get("dimensions") or {}).get(
            "economy"
        ) or {}
        income = economy.get("income_per_min")
        if income is None:
            return None
        return SR_COPY_TAG if float(income) == sr_rate else None
    except Exception:  # noqa: BLE001 - the coach hot path must never raise
        return None


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
    cv_override: dict | None = None,
    verdict_blocks: dict | None = None,
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
        tkey = str(target)

        # Stale-snapshot freshness guard: a post-game liveclient cache keeps
        # serving the final snapshot at a FROZEN game_time_s (cycle 54 observed
        # a ~22-min WAIT-RESPAWN tail at one identical game_time after a game
        # ended). The coarse-state sig re-logs such a tick whenever an
        # incidental field (item_count) drifts, bloating the jsonl + diluting
        # the coverage/dedup denominator. Suppress a tick whose game_time_s is
        # byte-identical to the last LOGGED tick for this target. Exact equality
        # ONLY - a new game resets game_time below the frozen value, so a "<="
        # test would wrongly suppress the entire opening of the next game.
        if game_time_s is not None and _LAST_GT.get(tkey) == game_time_s:
            return None

        try:
            gt_bucket = int((game_time_s or 0) // 5)
        except (TypeError, ValueError):
            gt_bucket = 0
        # The CV override (enemy dead/missing, my low HP) flips intra-bucket
        # without any band/mana/cd change, so its kind is part of the coarse
        # sig - a CV transition (e.g. enemy laner dies) logs a fresh row rather
        # than being deduped away. None when CV adds nothing (RC2 P5.1).
        cv_kind = cv_override.get("kind") if isinstance(cv_override, dict) else None
        sig = str((
            mode, my_champion, enemy, band, mana_state, cd_state,
            level, item_count, gt_bucket, bool(covered), len(choice_list),
            cv_kind,
        ))
        if _LAST_SIG.get(tkey) == sig:
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
            # RC2 P5.1 CV override ({verdict,confidence,reason,kind}) or None.
            # Shadow-only: hz_shadow_report re-measures agreement WITH this
            # layer applied before any served flip (do-not-flip-blind).
            "cv_override": cv_override if isinstance(cv_override, dict) else None,
            # v4 (Lane A) cooldown_window + spike_timing blocks for the resolved
            # cell ({cooldown_window:{...}, spike_timing:{...}}) or None when the
            # cell is uncovered / v3. Shadow-only: lets a future hz_shadow_report
            # pass measure cooldown-window / spike-timing agreement (spec 7.4)
            # before any served flip (do-not-flip-blind).
            "verdict_blocks": verdict_blocks if isinstance(verdict_blocks, dict) else None,
        }

        # RM-158: stamp the provenance of the PRECOMPUTE column when the served
        # table for this mode carries SR's economy. Only a record that actually
        # HAS a precompute column can carry a poisoned one, so a coverage-miss
        # record (empty choices - a pure native observation) is never tagged.
        if choice_list:
            tag = precompute_source_tag(mode)
            if tag:
                record[PRECOMPUTE_SOURCE_KEY] = tag

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[tkey] = sig
        if game_time_s is not None:
            _LAST_GT[tkey] = game_time_s

        return record

    except Exception:  # noqa: BLE001
        log.debug("hz_choice_shadow.log_precomputed_choices failed", exc_info=True)
        return None
