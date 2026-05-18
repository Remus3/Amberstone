"""Single source of truth for supported Phase 3 mode names.

PHASE3_MODES is derived from ``resolved_decisions.json``'s ``db.files``
key at import time.  Import from here instead of hardcoding the tuple.
"""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DECISIONS_PATH = _PROJECT_ROOT / "agents" / "state" / "resolved_decisions.json"


def _load() -> tuple[str, ...]:
    data = json.loads(_DECISIONS_PATH.read_text(encoding="utf-8"))
    files: list[str] = data["db"]["files"]  # e.g. ["sr_draft.db", ...]
    return tuple(f.removesuffix(".db") for f in files)


PHASE3_MODES: tuple[str, ...] = _load()


def verify_modes() -> None:
    """Re-read resolved_decisions.json and assert PHASE3_MODES is still current.

    Called at supervisor start so any drift between the in-memory value
    and the file is caught loudly before any work begins.
    """
    current = _load()
    if current != PHASE3_MODES:
        raise RuntimeError(
            f"lib.modes.PHASE3_MODES drift detected - "
            f"in-memory {list(PHASE3_MODES)!r} vs "
            f"resolved_decisions.json {list(current)!r}. "
            "Restart the supervisor to pick up the updated mode list."
        )
