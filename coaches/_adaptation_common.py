"""Shared internals for the ``coaches.adaptation_hint`` concern modules.

Acyclic foundation: this module imports nothing from the facade or any
concern submodule, so the dependency graph stays a DAG
(``_adaptation_common`` <- every concern module <- the facade).

Payload-boundary slice of the former monolithic
``coaches.adaptation_hint`` (AUTONOMOUS_AUDIT spec 4.C, 2026-05-18).
Holds the bits every concern needs: the supported-mode set, the per-mode
DB-path resolver, the threshold constants, the logger, and the
session-default timestamp helper.

``DB_DIR`` is the canonical default, but the test suite monkeypatches
``coaches.adaptation_hint.DB_DIR`` (round14/16/18/23/.../38). ``_db``
therefore resolves the directory off the *facade* at call time so that
contract is preserved post-split with zero test changes.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("coaches.adaptation_hint")

# coaches/_adaptation_common.py is one level under the project root -
# identical resolution to the pre-split coaches/adaptation_hint.py.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# RM-170: env-overridable so a test can point the mode DBs at a tmp dir.
# Default unchanged. All five modules that define this path read the SAME
# var, so an override cannot split schema-init from ingest.
DB_DIR = Path(os.environ.get("RC_PHASE3_DB_DIR") or (_PROJECT_ROOT / "data" / "db"))

from lib.modes import PHASE3_MODES as SUPPORTED_MODES

# How many top counter-matchups to surface.
_DEFAULT_TOP_COUNTERS = 3
# Matchup must have at least this sample size to be considered for a hint.
_MIN_SAMPLE = 5
# Only flag a matchup when it meaningfully deviates from baseline.
_MIN_ABSOLUTE_DELTA = 0.15


def _db(mode: str) -> Path | None:
    if mode not in SUPPORTED_MODES:
        return None
    # The test suite does `monkeypatch.setattr(coaches.adaptation_hint,
    # "DB_DIR", tmp_path)` (and one direct `ah.DB_DIR = ...`). Resolve the
    # base directory off the already-imported facade at call time so that
    # patch contract still redirects every concern submodule. Never
    # imports anything here (sys.modules lookup only) - no circular-import
    # risk, no import-lock contention, and it never raises.
    base = DB_DIR
    _facade = sys.modules.get("coaches.adaptation_hint")
    if _facade is not None:
        base = getattr(_facade, "DB_DIR", DB_DIR)
    p = base / f"{mode}.db"
    return p if p.exists() else None


def _start_of_today_iso() -> str:
    """Local midnight, ISO-8601 with tz - used as default ``since`` for
    session_summary."""
    from datetime import datetime, timezone
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()
