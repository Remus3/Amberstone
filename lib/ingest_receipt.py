# arch: append-only per-game ingest receipt for the live rewind writer | section=lib | frozen=no
"""Per-game ingest receipt (Y-08, external reference M - behaviour only).

``lib/rewind_live_writer.py`` runs a target-pinned staged chain after every
game end. Before Y-08 it left no success trace anywhere: the only evidence a
game reached ``data/rewind_history.db`` was the row itself, so "the last game
never landed" and "nothing ran" looked identical. This module is the receipt:
one JSON line per chain END, appended to ``RECEIPT_PATH``.

Storage decision: a jsonl file under ``ops/runtime/`` (gitignored, .gitignore
``ops/runtime/``), NOT a table in ``rewind_history.db`` and NOT
``data/runtime/`` (which is not gitignored). Why not the DB: the schema there
is owned by ``scripts/rewind_scraper.py`` / ``scripts/rewind_catchup.py``, a
new table would be a schema change on the store every rewind reader opens, and
a receipt write would have to contend for the writer's ``_WRITE_LOCK`` and the
sqlite write lock at exactly the moment the ingest itself failed. A plain
append cannot corrupt the ingest store and stays readable when the DB is not.

Row (``v`` = 1): ``ts`` (epoch s), ``target`` (``<PLATFORM>_<gameId>`` or
null), ``status`` (the writer's status NAME, verbatim), ``attempts``,
``elapsed_s`` (since the chain was scheduled at game end), ``parked`` (the
target was handed to the ``fetch_retry`` drain), ``pinned``, ``fallback``,
``cause``. The status class is NOT stored: it is derived at read time by
``classify`` so the tally rule lives in one place.

Contract:
  * ``append_receipt`` NEVER raises - it runs on the writer's Timer thread.
  * A "nothing to do" end writes no row: a ``*retry_scheduled`` status is
    not an end, and ``duplicate_target`` means another chain owns the game
    and will write ITS receipt.
  * An unknown status is recorded (hiding it is the defect) but is never
    counted as success: only ``CLASS_INGESTED`` is success.
  * Append-only. A torn last line (crash mid-write) is skipped by the reader,
    never repaired in place. Lines are written with one ``write`` call under
    a process lock; the file is never rewritten, so tmp+replace does not apply.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

_log = logging.getLogger("rc.lib.ingest_receipt")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
RECEIPT_PATH = _PROJECT_ROOT / "ops" / "runtime" / "rewind_ingest_receipts.jsonl"

SCHEMA_VERSION = 1

CLASS_INGESTED = "ingested"   # the target IS in the rewind DB
CLASS_EXCLUDED = "excluded"   # by design never ingested (event mode, remake)
CLASS_DEFERRED = "deferred"   # handed to / left for the catchup drain
CLASS_FAILED = "failed"       # ended without the game and without a hand-off
CLASS_UNKNOWN = "unknown"     # a status this module cannot name

# Every TERMINAL status lib/rewind_live_writer.py can return, by name.
# tests/test_ingest_receipt_y08.py scans the writer source and fails when a
# new status appears here in no class.
STATUS_CLASSES: dict[str, frozenset[str]] = {
    CLASS_INGESTED: frozenset({"ok", "already_present"}),
    CLASS_EXCLUDED: frozenset({"event_mode_excluded", "short_game"}),
    CLASS_DEFERRED: frozenset({"target_not_indexed", "detail_rate_limited",
                               "staged_cap_reached", "rate_limited"}),
    CLASS_FAILED: frozenset({"no_puuid", "no_api_key", "no_id", "no_detail",
                             "error"}),
}

_BY_STATUS = {s: cls for cls, members in STATUS_CLASSES.items() for s in members}

# Not a chain end at all, or another chain's game: no receipt.
_NOT_A_RECEIPT = frozenset({"duplicate_target"})

_APPEND_LOCK = threading.Lock()

# Tail window the reader keeps. One row per game end; 200 is weeks of play.
READ_LIMIT = 200


def classify(status: Any) -> str:
    """Status NAME -> class. Anything unrecognised is ``CLASS_UNKNOWN``."""
    if not isinstance(status, str):
        return CLASS_UNKNOWN
    return _BY_STATUS.get(status, CLASS_UNKNOWN)


def is_success(status: Any) -> bool:
    return classify(status) == CLASS_INGESTED


def is_non_terminal(status: Any) -> bool:
    # The legacy unpinned path spells one of them bare: "retry_scheduled".
    return isinstance(status, str) and (
        status == "retry_scheduled" or status.endswith("_retry_scheduled")
        or status in _NOT_A_RECEIPT)


def should_record(status: Any) -> bool:
    return not is_non_terminal(status)


def _finite(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _short_str(x: Any, limit: int = 64) -> str:
    if isinstance(x, str):
        return x[:limit]
    return ""


def build_row(result: dict[str, Any], *, scheduled_at: Any = None,
              attempt: Any = 0, now: Any = None) -> dict[str, Any]:
    """The receipt row for one chain end. Pure; tolerant of any input."""
    ts = _finite(now)
    if ts is None:
        ts = float(time.time())
    started = _finite(scheduled_at)
    try:
        attempts = int(attempt) + 1
    except (TypeError, ValueError, OverflowError):
        attempts = None
    status = result.get("status")
    target = result.get("match_id")
    return {
        "v": SCHEMA_VERSION,
        "ts": ts,
        "target": target if isinstance(target, str) and target else None,
        "status": status if isinstance(status, str) else repr(status)[:64],
        "attempts": attempts,
        "elapsed_s": (round(ts - started, 3) if started is not None else None),
        "parked": bool(result.get("parked") is True),
        "pinned": bool(result.get("pinned") is True),
        "fallback": bool(result.get("fallback") is True),
        "cause": _short_str(result.get("cause")),
    }


def _append_line(path: Path, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _APPEND_LOCK:
        with open(path, "a", encoding="ascii", newline="\n") as fh:
            fh.write(line)


def append_receipt(result: Any, *, scheduled_at: Any = None, attempt: Any = 0,
                   now: Any = None, path: Path | None = None) -> bool:
    """Append one receipt for a chain end. True when a row was written.

    Never raises: any failure (bad shape, disk, encoding) is logged at debug
    and returns False, because the caller is the writer's Timer thread.
    """
    try:
        if not isinstance(result, dict):
            return False
        if not should_record(result.get("status")):
            return False
        row = build_row(result, scheduled_at=scheduled_at, attempt=attempt,
                        now=now)
        line = json.dumps(row, ensure_ascii=True, allow_nan=False) + "\n"
        _append_line(Path(path) if path is not None else RECEIPT_PATH, line)
        return True
    except Exception as exc:  # noqa: BLE001 - never raise into the writer
        _log.debug("ingest receipt append failed: %s", exc)
        return False


def read_receipts(path: Path | None = None,
                  limit: int = READ_LIMIT) -> list[dict[str, Any]]:
    """The last ``limit`` well-formed rows, oldest first. Never raises."""
    p = Path(path) if path is not None else RECEIPT_PATH
    out: deque[dict[str, Any]] = deque(maxlen=max(1, int(limit)))
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    row = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(row, dict) and isinstance(row.get("status"), str):
                    out.append(row)
    except OSError:
        return []
    return list(out)
