"""core/replay_narrative_shadow.py - fail-soft replay-narrative validation writer.

The do-not-flip-blind validation substrate for the postgame replay coach. The
served path ``coaches/replay_coach.analyze_match`` (Haiku) is currently DORMANT;
this module records, alongside whatever that live coach output would be, what the
DETERMINISTIC narrative builder (core.precomputed_replay_narrative.build_narrative)
produces for the same match, so the precompute path can be validated against real
matches offline BEFORE any flip - WITHOUT changing any live output.

SHADOW-ONLY: nothing here flips the live coach, and this module is not wired into
any served route. It is the recorder, not a flip.

Mirrors core.det_coach_shadow / core.champ_select_shadow: same fail-soft contract
(never raises), same default-path-under-data layout, same best-effort
engine-version stamp, same per-target coarse-state dedup, same atomic append.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.replay_narrative_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "replay_narrative_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently. A replay narrative is a per-match
# artifact, so the dedup keys on match_id - re-coaching the same match writes at
# most one record per target.
_LAST_SIG: dict[str, str] = {}


def log_replay_narrative(
    match_id: str,
    narrative: dict | None,
    *,
    native: dict | None = None,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one replay-narrative validation record to the shadow jsonl.

    Args:
        match_id: the rewind_history.db match id the narrative was built for.
        narrative: the dict from core.precomputed_replay_narrative.build_narrative
            (summary / key_moments / lessons / grade). Non-dict coerces to {}.
        native: optional live-coach output (coaches/replay_coach.analyze_match
            shape) to record alongside the deterministic narrative for offline
            comparison. The live path is DORMANT, so this is normally None.
        path: optional explicit shadow path (tests pass their own tmp_path).
        now_iso: optional ISO timestamp override (tests pin this).

    Returns:
        The record dict on a fresh write, None on a gate miss (blank match_id),
        a dedup skip, or any failure (fail-soft). Never raises - safe on any
        call path.
    """
    try:
        if not match_id or not isinstance(match_id, str):
            return None

        narrative = narrative if isinstance(narrative, dict) else {}
        native_dict = native if isinstance(native, dict) else {}

        target = path if path is not None else SHADOW_PATH
        tkey = str(target)
        sig = match_id
        if _LAST_SIG.get(tkey) == sig:
            return None

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "match_id": match_id,
            "engine_version": ENGINE_VERSION,
            "ok": bool(narrative.get("ok")),
            "summary": narrative.get("summary") or "",
            "key_moments": narrative.get("key_moments") or [],
            "lessons": narrative.get("lessons") or [],
            "grade": narrative.get("grade") or {},
            "native": native_dict,
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic append: read the existing file, append the new line, write the
        # whole buffer to a tmp sibling, then replace the target in one rename.
        # Mirrors the repo "tmp.write_text(...); tmp.replace(target)" hard rule
        # so a concurrent reader never sees a partially written tail.
        existing = ""
        try:
            existing = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        buffer = existing + json.dumps(record) + "\n"
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(buffer, encoding="utf-8")
        tmp.replace(target)
        _LAST_SIG[tkey] = sig

        return record

    except Exception:  # noqa: BLE001
        log.debug("replay_narrative_shadow.log_replay_narrative failed", exc_info=True)
        return None
