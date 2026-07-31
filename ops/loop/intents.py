#!/usr/bin/env python
r"""Session intents - the CONSUMER half of Mission Control shortcuts 1 and 2.

    INTENT_FILES = {"halt_save":     "INTENT_HALT_SAVE.json",
                    "done_continue": "INTENT_DONE_CONTINUE.json"}

S2 (shipped, `dashboard/routes_loop_control.py`) is the PRODUCER: an operator
fire writes one of those files atomically with `consumed: false`, and halt_save
additionally raises the existing `control/STOP`. Nothing read them back. This
module is what reads them, and it is the only thing that writes the bootstrap
prompt to `Desktop/RC-NEXT-SESSION.txt`.

QUEUED INTENTS NEVER KILL. Nothing here signals, terminates or interrupts a
process. `pending()` answers a question and `consume()` writes two files. The
running session decides WHEN to call them, which is what "at its next safe
boundary" means in the plan - the boundary is the done ritual, not a poll that
can land in the middle of a merge.

PROMPT FIRST, MARKER SECOND. `consume()` writes the Desktop prompt before it
marks the intent consumed. A crash between the two leaves `consumed: false`, so
the retry rewrites the same bytes and the operator loses nothing. Marking first
would strand the intent as done with no prompt on disk and no way to ask for it
again.

OVERWRITE, NOT ACCUMULATE. `Desktop/RC-NEXT-SESSION.txt` is a single well-known
path with no timestamp suffix (operator decision 2026-07-30). Prior contents
are recoverable from the session transcript.

READS DO NOT WRITE - same doctrine as `lanes.py`. `pending()` never mutates, so
a status poll can call it as often as it likes without racing a consumer.

THE FILENAMES ARE A SEAM, NOT A CONSTANT. They are duplicated in the route
module because that module must stay importable with this one absent. The
duplication is pinned by a contract test that compares the two mappings, not by
a comment - a divergence would otherwise be silent, with each half passing its
own tests while the producer wrote a file the consumer never opens.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Mirrors dashboard.routes_loop_control._INTENT_FILES. Pinned by
# tests/test_session_intents.py::test_filenames_match_the_route_not_a_copy.
INTENT_FILES = {
    "halt_save": "INTENT_HALT_SAVE.json",
    "done_continue": "INTENT_DONE_CONTINUE.json",
}

# halt_save outranks done_continue: it carries STOP, so if both are somehow
# queued the operator has asked to park the work, and parking wins over
# continuing. Order is the priority.
PRIORITY = ("halt_save", "done_continue")

# REPO NAMESPACE (operator 2026-07-30). The Desktop is SHARED between repos, so
# every artifact this design puts there is prefixed with the repo that owns it:
# RC-NEXT-SESSION.txt here, LW-NEXT-SESSION.txt in Sibling-A,
# RM-NEXT-SESSION.txt in RM. Three sessions may run concurrently and must never
# read, overwrite or clear each other's hand-off - the same rule that makes
# touching a sibling repo's file system a deliberate cross-repo act rather than
# a side effect. The intent files themselves already live under this repo's own
# ops/loop/control/, so they cannot collide; the Desktop is the one shared
# surface, which is exactly why the prefix is enforced and not merely defaulted.
#
# Each repo ships its own copy of this module and edits ONE line. Deriving the
# prefix from the directory name was rejected: a worktree, a rename or a clone
# to a different path would silently re-point the write.
REPO_PREFIX = "RC"

# Relative to the user profile. Mirrors routes_loop_control.NEXT_SESSION_PATH.
DEFAULT_NEXT_SESSION_PATH = f"Desktop/{REPO_PREFIX}-NEXT-SESSION.txt"

DEFAULT_ROOT = Path(__file__).resolve().parent / "control"

# Env overrides exist for the CLI (tools/session_intent.py) so a test can drive
# the real entry point without ever touching the live control dir or the real
# Desktop. Absent => the live paths.
ENV_ROOT = "RC_INTENT_CONTROL_DIR"
ENV_HOME = "RC_INTENT_HOME"


def control_dir(root=None) -> Path:
    """Resolve the control dir: explicit arg > env override > live default."""
    if root is not None:
        return Path(root)
    env = os.environ.get(ENV_ROOT)
    return Path(env) if env else DEFAULT_ROOT


def _home(home=None) -> Path:
    if home is not None:
        return Path(home)
    env = os.environ.get(ENV_HOME)
    return Path(env) if env else Path.home()


def _awrite(path: Path, text: str) -> None:
    """Atomic write (tmp + os.replace); readers poll these paths mid-write.

    Writes BYTES, not text. `Path.write_text` opens in text mode, and on
    Windows that silently rewrites every LF as CRLF - measured 2026-07-30 on
    the first live consume, which reported 1375 bytes while the Desktop file
    held 1395. The prompt is a machine hand-off that gets re-fed verbatim, and
    a byte count that does not match the file is a lie in a status line.
    Round-tripping through `read_text` hides this, so the guard test asserts
    raw bytes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def _read_doc(path: Path) -> dict | None:
    """Read one intent file. A malformed file is absent, never an exception.

    The control dir is polled by a dashboard route and by a done ritual; a
    half-written or hand-edited file must degrade to "nothing queued" rather
    than take the caller down.
    """
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def pending(root=None) -> dict | None:
    """The highest-priority UNCONSUMED intent, or None. Never writes.

    The returned dict is the on-disk document plus `_path` (str) so a caller
    that already peeked can hand it straight to `consume()` without a re-read.
    """
    base = control_dir(root)
    for intent in PRIORITY:
        path = base / INTENT_FILES[intent]
        doc = _read_doc(path)
        if doc is None or doc.get("consumed"):
            continue
        # Trust the filename over a mismatched `intent` field: the filename is
        # what the producer routed on.
        doc["intent"] = intent
        doc["_path"] = str(path)
        return doc
    return None


def resolve_next_session_path(doc, home=None) -> Path:
    """Where the bootstrap prompt goes, from the intent doc, safely.

    The intent file is written by a local route on a single-operator surface,
    but it is still an on-disk document that decides a write target. Anything
    that is not a plain relative path UNDER the user profile falls back to the
    default rather than being honoured: absolute paths, drive letters, `..`
    segments, empty and non-string values.

    It must ALSO stay inside this repo's namespace. A filename that is not
    `REPO_PREFIX-`-prefixed falls back too, so an RC session can never be
    talked into overwriting `LW-NEXT-SESSION.txt` by a doctored or stale intent
    doc. Cross-repo writes are a deliberate act, never a fallback.
    """
    raw = (doc or {}).get("next_session_path")
    candidate = (raw if isinstance(raw, str) else "").strip().replace("\\", "/")
    parts = [p for p in candidate.split("/") if p not in ("", ".")]
    rooted = candidate.startswith("/") or ":" in candidate
    owned = bool(parts) and parts[-1].startswith(f"{REPO_PREFIX}-")
    if not parts or rooted or ".." in parts or Path(candidate).is_absolute() \
            or not owned:
        parts = DEFAULT_NEXT_SESSION_PATH.split("/")
    return _home(home).joinpath(*parts)


def _nothing_to_consume(base: Path) -> dict:
    """Distinguish "already handed off" from "nothing was ever queued".

    Both are refusals, but the done ritual reports them differently: one means
    the prompt is already on the Desktop, the other means the operator never
    fired anything.
    """
    for intent in PRIORITY:
        path = base / INTENT_FILES[intent]
        doc = _read_doc(path)
        if doc is not None and doc.get("consumed"):
            return {"ok": False, "reason": "already_consumed",
                    "intent": intent, "path": str(path)}
    return {"ok": False, "reason": "no_pending_intent"}


def consume(doc=None, *, prompt, root=None, home=None) -> dict:
    """Write the bootstrap prompt, then mark the intent consumed.

    Returns {"ok": True, "intent", "key", "wrote", "bytes"} on a real consume,
    or {"ok": False, "reason": "no_pending_intent"|"already_consumed"} - both
    of which are normal answers, not errors. A replay writes NOTHING: it does
    not touch the Desktop file and does not restamp the intent marker.

    Raises ValueError on an empty prompt. Writing an empty hand-off file
    would look exactly like a successful hand-off and would silently lose the
    session, so it is a caller bug, not a degraded mode.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("consume() requires a non-empty prompt")

    base = control_dir(root)
    if doc is None:
        doc = pending(root=base)
        if doc is None:
            return _nothing_to_consume(base)
    intent = doc.get("intent")
    if intent not in INTENT_FILES:
        return {"ok": False, "reason": "no_pending_intent"}
    path = Path(doc.get("_path") or (base / INTENT_FILES[intent]))

    # Re-read rather than trusting the caller's snapshot: the peek may be old.
    on_disk = _read_doc(path)
    if on_disk is None or on_disk.get("consumed"):
        return {"ok": False, "reason": "already_consumed", "intent": intent,
                "path": str(path)}

    target = resolve_next_session_path(on_disk, home=home)
    _awrite(target, prompt)

    marker = dict(on_disk)
    marker["intent"] = intent
    marker["consumed"] = True
    marker["consumed_ts"] = time.time()
    marker["next_session_written"] = str(target)
    _awrite(path, json.dumps(marker, indent=2) + "\n")

    return {"ok": True, "intent": intent, "key": on_disk.get("key"),
            "wrote": str(target), "bytes": len(prompt.encode("utf-8"))}
