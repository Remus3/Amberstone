"""core/objective_playbook_shadow.py - fail-soft RC2 P5.5 (WS3) playbook shadow.

The "do-not-flip-blind" validation substrate for the deterministic objective
playbook (``core.objective_playbook``). The playbook ROW ships additive today (a
new advisory the coach did not emit), but a FUTURE flip of the served Haiku
``objective`` FIELD onto the deterministic directive is gated. This module
records, per live tick, the deterministic playbook directive alongside the native
Haiku ``objective`` prose to ``data/objective_playbook_shadow.jsonl`` so
agreement can be measured on accrued real games BEFORE any served-field flip.

Mirrors ``core.hz_choice_shadow``: same fail-soft contract (never raises), same
default-path-under-data layout, same engine-version stamp, same coarse-state
dedup + exact-game_time freshness guard so the 2Hz /api/state poll does not flood
the log.
"""

from __future__ import annotations

import json
import logging
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
    table is silent is itself a validation signal. The gate only requires an
    operator champion (a real in-game tick); the caller additionally gates on a
    live liveclient champion."""
    try:
        if not my_champion or not isinstance(my_champion, str):
            return None

        play = playbook if isinstance(playbook, dict) else None
        playbook_tag = play.get("tag") if play else None
        playbook_line = play.get("line") if play else None
        native = native_objective if isinstance(native_objective, str) else None

        target = path if path is not None else SHADOW_PATH
        tkey = str(target)

        # Exact-game_time freshness guard (mirrors hz_choice_shadow): a post-game
        # liveclient cache keeps serving the final snapshot at a FROZEN
        # game_time_s; suppress a tick whose game_time is byte-identical to the
        # last LOGGED tick for this target. Exact equality ONLY - a new game
        # resets game_time below the frozen value.
        if game_time_s is not None and _LAST_GT.get(tkey) == game_time_s:
            return None

        try:
            gt_bucket = int((game_time_s or 0) // 5)
        except (TypeError, ValueError):
            gt_bucket = 0

        sig = str((
            mode, my_champion, gt_bucket, playbook_tag, playbook_line,
            lead_state, native,
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
            "game_time_s": game_time_s,
            "phase": phase,
            "lead_state": lead_state,
            "playbook_tag": playbook_tag,
            "playbook_line": playbook_line,
            # The live Haiku objective prose for the same tick - the comparison
            # the do-not-flip-blind gate needs before any served-field flip.
            "native_objective": native,
            "engine_version": ENGINE_VERSION,
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[tkey] = sig
        if game_time_s is not None:
            _LAST_GT[tkey] = game_time_s

        return record

    except Exception:  # noqa: BLE001
        log.debug("objective_playbook_shadow.log_objective_playbook failed", exc_info=True)
        return None


__all__ = ["SHADOW_PATH", "log_objective_playbook"]
