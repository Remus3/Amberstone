#!/usr/bin/env python
r"""Session intents - the CONSUMER half of Mission Control shortcuts 1 and 2.

    INTENT_FILES = {"halt_save":     "INTENT_HALT_SAVE.json",
                    "done_continue": "INTENT_DONE_CONTINUE.json"}

S2 (shipped, `dashboard/routes_loop_control.py`) is the PRODUCER: an operator
fire writes one of those files atomically with `consumed: false`, and halt_save
additionally raises the existing `control/STOP`. Nothing read them back. This
module is what reads them, and it writes the bootstrap prompt to
`RC-NEXT-SESSION.txt` in the REPO ROOT (moved off the Desktop 2026-09-06 so it
is tracked; the Desktop keeps a shortcut to it).

QUEUED INTENTS NEVER KILL. Nothing here signals, terminates or interrupts a
process. `pending()` answers a question and `consume()` writes two files. The
running session decides WHEN to call them, which is what "at its next safe
boundary" means in the plan - the boundary is the done ritual, not a poll that
can land in the middle of a merge.

PROMPT FIRST, MARKER SECOND. `consume()` writes the prompt before it
marks the intent consumed. A crash between the two leaves `consumed: false`, so
the retry rewrites the same bytes and the operator loses nothing. Marking first
would strand the intent as done with no prompt on disk and no way to ask for it
again.

OVERWRITE, NOT ACCUMULATE. `RC-NEXT-SESSION.txt` is a single well-known path
with no timestamp suffix (operator decision 2026-07-30). Prior contents are now
recoverable from git history, which is the point of the 2026-09-06 move - the
Desktop copy had no diff and no versions, and went three days stale unnoticed.

READS DO NOT WRITE - same doctrine as `lanes.py`. `pending()` never mutates, so
a status poll can call it as often as it likes without racing a consumer.

THE FILENAMES ARE A SEAM, NOT A CONSTANT. They are duplicated in the route
module because that module must stay importable with this one absent. The
duplication is pinned by a contract test that compares the two mappings, not by
a comment - a divergence would otherwise be silent, with each half passing its
own tests while the producer wrote a file the consumer never opens.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

# core/polled_json.py holds the repo's atomic-write contract - LANE 8 CYCLE 48,
# RM-250. The plain import is tried FIRST so the dashboard and the test suite
# share one module object; the absolute-path bind is the fallback for the
# launcher's context, where these ops/loop modules are loaded BY FILE PATH and
# the repo root is not on sys.path, so `import core.polled_json` raises
# ModuleNotFoundError (measured; guarded by
# tests/test_loop_control_sibling_writers_lane8_cycle48.py).
try:
    from core.polled_json import atomic_write_bytes as _atomic_write_bytes
except ModuleNotFoundError:
    _pj_name = "rc_core_polled_json"
    if _pj_name in sys.modules:
        _atomic_write_bytes = sys.modules[_pj_name].atomic_write_bytes
    else:
        try:
            _pj_spec = importlib.util.spec_from_file_location(
                _pj_name,
                Path(__file__).resolve().parents[2] / "core" / "polled_json.py")
            _pj = importlib.util.module_from_spec(_pj_spec)
            sys.modules[_pj_name] = _pj
            _pj_spec.loader.exec_module(_pj)
        except OSError as _exc:
            # exec_module on a missing or unreadable file raises
            # FileNotFoundError, not ModuleNotFoundError. This module is
            # imported by NAME from the loop-control route, whose handler
            # catches only ModuleNotFoundError, so an OSError here would turn a
            # designed 503 into a 500. Do not leave a half-initialised module
            # object cached under the bind name for the next caller to find.
            sys.modules.pop(_pj_name, None)
            raise ModuleNotFoundError(
                "core/polled_json.py could not be loaded by absolute path"
            ) from _exc
        _atomic_write_bytes = _pj.atomic_write_bytes

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

# REPO NAMESPACE (operator 2026-07-30). Originally this existed because the
# Desktop was a SHARED surface and five projects wrote hand-offs onto it. Since
# 2026-09-06 the file lives in each repo's OWN root, so cross-repo collision is
# no longer possible by construction and the prefix is not load-bearing for that
# any more. It is KEPT for two reasons that still hold: the Desktop SHORTCUTS
# are still a shared surface and need distinguishable names, and the prefix is
# what stops a doctored or stale intent doc from naming an arbitrary write
# target in the repo root. Do not drop it to save eight characters.
#
# Each repo ships its own copy of this module and edits ONE line. Deriving the
# prefix from the directory name was rejected: a worktree, a rename or a clone
# to a different path would silently re-point the write.
REPO_PREFIX = "RC"

# Relative to the REPO ROOT. Mirrors routes_loop_control.NEXT_SESSION_PATH.
DEFAULT_NEXT_SESSION_PATH = f"{REPO_PREFIX}-NEXT-SESSION.txt"

DEFAULT_ROOT = Path(__file__).resolve().parent / "control"

# Env overrides exist for the CLI (tools/session_intent.py) so a test can drive
# the real entry point without ever touching the live control dir or the real
# Desktop. Absent => the live paths.
ENV_ROOT = "RC_INTENT_CONTROL_DIR"
# Renamed from RC_INTENT_HOME 2026-09-06 with the target itself: it no longer
# resolves under the user profile, so calling it "home" would have left a name
# asserting something untrue.
ENV_BASE = "RC_INTENT_BASE"

# The hand-off now lands in the REPO ROOT, not on the Desktop (operator
# 2026-09-06). A Desktop file is untracked, unversioned and unreviewable - it
# had gone three days stale with nothing able to notice, and no diff to show
# what the last session actually handed over. In the repo it is versioned like
# every other artifact, and the Desktop keeps a SHORTCUT to it so the operator
# reaches it exactly as before.
REPO_ROOT = Path(__file__).resolve().parents[2]


def control_dir(root=None) -> Path:
    """Resolve the control dir: explicit arg > env override > live default."""
    if root is not None:
        return Path(root)
    env = os.environ.get(ENV_ROOT)
    return Path(env) if env else DEFAULT_ROOT


def _base(base=None) -> Path:
    """Where the hand-off is rooted: explicit arg > env override > repo root."""
    if base is not None:
        return Path(base)
    env = os.environ.get(ENV_BASE)
    return Path(env) if env else REPO_ROOT


def _awrite(path: Path, text: str) -> None:
    """Atomic write (tmp + os.replace); readers poll these paths mid-write.

    Writes BYTES, not text. `Path.write_text` opens in text mode, and on
    Windows that silently rewrites every LF as CRLF - measured 2026-07-30 on
    the first live consume, which reported 1375 bytes while the Desktop file
    held 1395. The prompt is a machine hand-off that gets re-fed verbatim, and
    a byte count that does not match the file is a lie in a status line.
    Round-tripping through `read_text` hides this, so the guard test asserts
    raw bytes.

    LANE 8 CYCLE 48 (RM-250): the byte-mode write above was already right, but
    the replace was BARE. A reader holding the INTENT file open share-locks it
    on Windows and `os.replace` then raises WinError 5, so the consume that
    marks an intent `consumed: True` (:230) could fail against the very poller
    it is reporting to. The scratch name was also `str(path) + ".tmp"`, derived
    from the DESTINATION alone and therefore shared by every writer of that
    file. core/polled_json supplies both the bounded ~275 ms PermissionError
    backoff and a per-writer scratch name, so this delegates instead.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(path, text.encode("utf-8"))


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


def resolve_next_session_path(doc, base=None) -> Path:
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
    return _base(base).joinpath(*parts)


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


def write_prompt(*, prompt, base=None) -> dict:
    """Write the Desktop hand-off. No intent required, none consumed.

    ADDED 2026-09-06, because the two things below were conflated and the
    coupling silently broke the ordinary case:

      * WRITING the hand-off is unconditional - every session ends by handing
        the next one a running start (tools/done.md section 10, "ALWAYS").
      * CONSUMING a queued intent happens only when the operator fired the
        dashboard button (section 10b).

    `consume()` did both, so it was the only writer, and it correctly refuses
    with `no_pending_intent` when nothing is queued - which is the NORMAL state
    at the end of a session. Net effect: the prompt was printed into chat and
    the Desktop file went stale for three days while every sibling project's
    was current. The stale copy's own header named a headless lane, which is
    the only route that had a pending intent.

    Deliberately reuses `resolve_next_session_path` and `_awrite` rather than
    joining a path here. The Desktop is shared between five projects and the
    namespacing rule lives in that resolver; a second caller re-implementing it
    is how one rule becomes two readings.

    Raises ValueError on an empty prompt, for the same reason `consume()` does:
    an empty hand-off file is indistinguishable from a successful one and
    silently loses the session.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("write_prompt() requires a non-empty prompt")
    # No doc: resolve_next_session_path falls back to DEFAULT_NEXT_SESSION_PATH,
    # which is already REPO_PREFIX-namespaced. Passing None is the point - there
    # is no intent doc to honour and none should be invented.
    target = resolve_next_session_path(None, base=base)
    _awrite(target, prompt)
    return {"ok": True, "wrote": str(target),
            "bytes": len(prompt.encode("utf-8"))}


def consume(doc=None, *, prompt, root=None, base=None) -> dict:
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

    # NAMED ctl, NOT base. The `base` PARAMETER is where the hand-off is rooted;
    # this is the control dir the intent files live in. They were both called
    # `base` for about ten minutes on 2026-09-06 and the local silently shadowed
    # the parameter, so every consume wrote the hand-off into ops/loop/control/
    # instead of the repo root - caught by the existing tests, which is why they
    # assert the resolved PATH and not merely that a write happened.
    ctl = control_dir(root)
    if doc is None:
        doc = pending(root=ctl)
        if doc is None:
            return _nothing_to_consume(ctl)
    intent = doc.get("intent")
    if intent not in INTENT_FILES:
        return {"ok": False, "reason": "no_pending_intent"}
    path = Path(doc.get("_path") or (ctl / INTENT_FILES[intent]))

    # Re-read rather than trusting the caller's snapshot: the peek may be old.
    on_disk = _read_doc(path)
    if on_disk is None or on_disk.get("consumed"):
        return {"ok": False, "reason": "already_consumed", "intent": intent,
                "path": str(path)}

    target = resolve_next_session_path(on_disk, base=base)
    _awrite(target, prompt)

    marker = dict(on_disk)
    marker["intent"] = intent
    marker["consumed"] = True
    marker["consumed_ts"] = time.time()
    marker["next_session_written"] = str(target)
    _awrite(path, json.dumps(marker, indent=2) + "\n")

    return {"ok": True, "intent": intent, "key": on_disk.get("key"),
            "wrote": str(target), "bytes": len(prompt.encode("utf-8"))}
