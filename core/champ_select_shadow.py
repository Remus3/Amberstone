# arch: champ-select pick-advisor shadow writer | section=core | frozen=no
"""core/champ_select_shadow.py - fail-soft champ-select pick-advisor shadow writer.

The do-not-flip-blind validation substrate for the Tier-2 champ-select
pick-advisor (the last champ-select Haiku call, coaches/champ_select_coach).
The live coach still answers via Haiku; this records, alongside that live
output, what the DETERMINISTIC advisor (core.champ_select_advisor_deterministic)
WOULD have offered for the same pick state, so the precompute path can be
validated against real games offline before any flip - WITHOUT changing any
live output.

Mirrors core.hz_choice_shadow / core.det_coach_shadow: same fail-soft contract
(never raises), same default-path-under-data layout, same engine-version stamp,
same coarse-state dedup. Champ-select POSTs are debounced per pick change, so
the dedup keys on the full pick state (mode, queue, my pick, both teams, bench)
to write at most one record per distinct pick situation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rc.champ_select_shadow")

# Default shadow path - project root is two levels above this file (core/).
_APP_DIR = Path(__file__).parent.parent
SHADOW_PATH: Path = _APP_DIR / "data" / "champ_select_shadow.jsonl"

# Per-target dedup. Keyed by str(target_path) so an explicit test path and the
# live default each dedup independently.
_LAST_SIG: dict[str, str] = {}

_ADVICE_KEYS = ("advice", "swap", "summoners", "watchout")


def _sig(state: dict) -> str:
    return str((
        bool(state.get("is_aram")),
        state.get("queue_id"),
        str(state.get("my_champion") or ""),
        tuple(sorted(str(c) for c in (state.get("my_team") or []) if c)),
        tuple(sorted(str(c) for c in (state.get("their_team") or []) if c)),
        tuple(sorted(str(c) for c in (state.get("bench") or []) if c)),
    ))


def _advice_fields(d) -> dict:
    d = d if isinstance(d, dict) else {}
    return {k: d.get(k, "") for k in _ADVICE_KEYS}


def log_champ_select_advice(
    state: dict,
    native,
    deterministic,
    *,
    path: Path | None = None,
    now_iso: str | None = None,
) -> dict | None:
    """Append one champ-select validation record (native Haiku advice vs the
    deterministic advisor) to the shadow jsonl.

    Returns the record dict on a fresh write, None on a gate miss (no operator
    champion in the pick state), a dedup skip, or any failure (fail-soft).
    Never raises - safe on the route path."""
    try:
        if not isinstance(state, dict) or not state.get("my_champion"):
            return None
        target = path if path is not None else SHADOW_PATH
        tkey = str(target)
        sig = _sig(state)
        if _LAST_SIG.get(tkey) == sig:
            return None

        try:
            from agents.daemon_slayer import ENGINE_VERSION  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            ENGINE_VERSION = "?"  # type: ignore[assignment]

        ts = now_iso if now_iso is not None else datetime.now(timezone.utc).isoformat()

        record: dict = {
            "ts": ts,
            "is_aram": bool(state.get("is_aram")),
            "queue_id": state.get("queue_id"),
            "my_champion": state.get("my_champion"),
            "my_team": [c for c in (state.get("my_team") or []) if c],
            "their_team": [c for c in (state.get("their_team") or []) if c],
            "bench": [c for c in (state.get("bench") or []) if c],
            "engine_version": ENGINE_VERSION,
            "native": _advice_fields(native),
            "deterministic": _advice_fields(deterministic),
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        _LAST_SIG[tkey] = sig
        return record

    except Exception:  # noqa: BLE001
        log.debug("champ_select_shadow.log_champ_select_advice failed", exc_info=True)
        return None
