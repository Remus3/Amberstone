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
    table is silent is itself a validation signal. The gate requires an
    operator champion (a real in-game tick) and refuses a test-only signature
    (``is_test_signature``: no game clock, or a placeholder champion); the
    caller additionally gates on a live liveclient champion."""
    try:
        if not my_champion or not isinstance(my_champion, str):
            return None
        # RM-872: refuse BEFORE the dedup, so a refused row records no
        # signature that could suppress the next real tick in its bucket.
        if is_test_signature(my_champion, game_time_s):
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


# RM-872 - the test-only row signature. Placed below the writer so the
# SHADOW_PATH / log_objective_playbook line citations in
# tests/test_suite_does_not_write_live_tree.py and
# tests/test_rm443_core_loader_retry.py stay exact.
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
