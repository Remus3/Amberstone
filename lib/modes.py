"""Single source of truth for supported Phase 3 mode names.

PHASE3_MODES is derived from ``resolved_decisions.json``'s ``db.files``
key at import time.  Import from here instead of hardcoding the tuple.

Every consumer turns a mode name into a FILE NAME (coaches/
_adaptation_common.py ``DB_DIR / f"{mode}.db"``, agents/agent2_backend/
pipeline/orchestrator.py ``COACH_CACHE_DIR / f"{mode}.json"``, which it
writes), so the list is checked here, once, before any of them sees it
(S144-T-603): ``db.files`` must be a non-empty JSON list of distinct
strings, each a lower-case ASCII name of 1-32 letters, digits and
underscores starting with a letter, followed by ``.db``, and never a
Windows reserved device name (con, prn, aux, nul, com0-9, lpt0-9). A file
that cannot be read, decoded or parsed, or that breaks that shape, raises
ModesConfigError (a RuntimeError) naming the file and the failing entry by
index; it never echoes the bad value.

The file is read as strict UTF-8, the same as the supervisor's version gate
(agents/_supervisor_common._verify_decisions_version), so a BOM-prefixed
copy is refused by both rather than accepted by one.

This module always reads the TRACKED file under agents/state/; it does not
follow RC_PHASE3_STATE_DIR (RM-170), because the test runtime points that
variable at an empty temp root and the mode list is a code-level constant.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DECISIONS_PATH = _PROJECT_ROOT / "agents" / "state" / "resolved_decisions.json"

# Explicit ASCII classes (no \w, no IGNORECASE) and fullmatch, so a trailing
# newline, a non-ASCII letter or a path separator can never match.
_MODE_FILE_RE = re.compile(r"([a-z][a-z0-9_]{0,31})\.db")
_RESERVED_DEVICE_RE = re.compile(r"(?:con|prn|aux|nul|com[0-9]|lpt[0-9])")


class ModesConfigError(RuntimeError):
    """resolved_decisions.json cannot supply a valid Phase 3 mode list."""


def _fail(detail: str) -> ModesConfigError:
    return ModesConfigError(
        f"{_DECISIONS_PATH.name}: {detail} - restore it from git, or run "
        "`python ops/phase3_setup.py`"
    )


def _parse(data: object) -> tuple[str, ...]:
    db = data.get("db") if isinstance(data, dict) else None
    if not isinstance(db, dict):
        raise _fail("top level must be an object with a 'db' object")
    files = db.get("files")
    if not isinstance(files, list):
        raise _fail("db.files must be a list")
    if not files:
        raise _fail("db.files is empty")
    modes: list[str] = []
    for i, entry in enumerate(files):
        match = _MODE_FILE_RE.fullmatch(entry) if isinstance(entry, str) else None
        if match is None:
            raise _fail(f"db.files[{i}] is not a mode file name (<name>.db)")
        mode = match.group(1)
        if _RESERVED_DEVICE_RE.fullmatch(mode):
            raise _fail(f"db.files[{i}] is a Windows reserved device name")
        if mode in modes:
            raise _fail(f"db.files[{i}] repeats an earlier entry")
        modes.append(mode)
    return tuple(modes)


def _load() -> tuple[str, ...]:
    try:
        text = _DECISIONS_PATH.read_text(encoding="utf-8")
    except OSError as e:
        raise _fail(f"cannot be read ({type(e).__name__})") from e
    except UnicodeDecodeError as e:
        raise _fail("is not valid UTF-8") from e
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as e:
        # JSONDecodeError is a ValueError; a pathologically nested document
        # exhausts the decoder's recursion limit instead.
        raise _fail(f"is not valid JSON ({type(e).__name__})") from e
    return _parse(data)


PHASE3_MODES: tuple[str, ...] = _load()


def verify_modes() -> None:
    """Re-read resolved_decisions.json and assert PHASE3_MODES is still current.

    Called at supervisor start so any drift between the in-memory value
    and the file is caught loudly before any work begins. A file that has
    since become unreadable or malformed raises ModesConfigError; a valid
    file whose list differs (order included) raises RuntimeError naming both
    lists, which are shape-checked names by then.
    """
    current = _load()
    if current != PHASE3_MODES:
        raise RuntimeError(
            f"lib.modes.PHASE3_MODES drift detected - "
            f"in-memory {list(PHASE3_MODES)!r} vs "
            f"resolved_decisions.json {list(current)!r}. "
            "Restart the supervisor to pick up the updated mode list."
        )
