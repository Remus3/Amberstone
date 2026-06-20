"""core/macro_response_shadow.py - fail-soft RC2 P5.7 (WS4) macro shadow.

The "do-not-flip-blind" validation substrate for the deterministic lost-objective
/ stagnation macro response (``core.macro_response``). The macro ROW ships
additive today (a new advisory the coach did not emit), but a FUTURE flip of a
served Haiku FIELD onto these directives would be gated. This module records, per
live tick, the deterministic macro directive alongside the native Haiku
``objective`` prose to ``data/macro_response_shadow.jsonl`` so the triggers can be
confirmed to fire at the right moments on accrued real games BEFORE any
served-field flip.

Mirrors ``core.objective_playbook_shadow`` / ``core.hz_choice_shadow``: same
fail-soft contract (never raises), same default-path-under-data layout, same
engine-version stamp, same coarse-state dedup + exact-game_time freshness guard
so the 2Hz /api/state poll does not flood the log.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.macro_response_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "macro_response_shadow.jsonl"

# Per-target coarse-state dedup, keyed by str(target_path) (mirrors
# objective_playbook_shadow) so an explicit test path and the live default dedup
# independently.
_LAST_SIG: dict[str, str] = {}

# Per-target last LOGGED game_time_s, for the exact-equality freshness guard.
_LAST_GT: dict[str, float] = {}


def log_macro_response(
    mode: str,
    my_champion: str,
    *,
    macro: dict | None = None,
    native_objective: str | None = None,
    lead_state: str | None = None,
    phase: str | None = None,
    game_time_s: float | None = None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one WS4 macro-response validation record to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss, a dedup skip,
    or any failure (fail-soft). Never raises - safe on the hot path.

    A record is written even when ``macro`` is None (no lost-objective / stall in
    range): a tick where Haiku emits an ``objective`` but the deterministic macro
    table is silent is itself a validation signal. The gate only requires an
    operator champion (a real in-game tick); the caller additionally gates on a
    live liveclient champion + SR mode."""
    try:
        if not my_champion or not isinstance(my_champion, str):
            return None

        mac = macro if isinstance(macro, dict) else None
        macro_tag = mac.get("tag") if mac else None
        macro_line = mac.get("line") if mac else None
        native = native_objective if isinstance(native_objective, str) else None

        target = path if path is not None else SHADOW_PATH
        tkey = str(target)

        # Exact-game_time freshness guard (mirrors objective_playbook_shadow): a
        # post-game liveclient cache keeps serving the final snapshot at a FROZEN
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
            mode, my_champion, gt_bucket, macro_tag, macro_line,
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
            "macro_tag": macro_tag,
            "macro_line": macro_line,
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
        log.debug("macro_response_shadow.log_macro_response failed", exc_info=True)
        return None


__all__ = ["SHADOW_PATH", "log_macro_response"]
