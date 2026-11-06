"""Round 42 - deterministic applier for UI proposals filed by Agent 7.

Consumes ``ui-proposal`` tasks produced by
``agents.agent7_context.ui_feedback.UIFeedbackParser``. Each proposal
names one or more files under a hard whitelist (the live dashboard
shell + the per-panel JS/CSS ESM modules) and carries the replacement
content. This module validates the paths, runs a brace/paren sanity
smoke test on any ``.js`` file (catches gross truncation - browsers,
not Python, run the file), atomically writes the new content, and
reports the result back to the task.

Out of scope by design: anything that isn't pixel/layout/behavioral UI.
The whitelist is intentionally narrow so a misfired ``ui_feedback``
intent can never touch coach logic, analyzer code, or secrets.

s236 (dashboard.js quarantine): the allowlist was repointed off the
dead ``web/js/dashboard.js`` / ``web/css/dashboard.css`` aggregator /
``web/js/sim.js`` (sim removed s218) onto the live UI - ``index.html``,
the ``main.js`` ESM entrypoint, and the per-panel ``web/js/panels/*``
+ ``web/css/panels/*`` modules (s133 ESM split; ``panels/base.css``
holds the ``:root`` palette + base font tokens).

s144 true-audit cycle 153 (RM-1900..RM-1907). The payload is untrusted
(part of it can come from an LLM answer on the ui_feedback path), so:

- every malformed payload, change, path or content raises
  ``UIApplyError`` - the one class the supervisor converts into a task
  failure - never AttributeError / TypeError / UnicodeEncodeError;
- ``_is_path_allowed`` returns False for a non-str instead of raising
  (ui_feedback calls it on the LLM path), and a panel stem must be ASCII
  ``[A-Za-z0-9_-]`` and not a Windows reserved device name (con, nul, ...);
- containment is checked against the WHITELISTED path itself, not just
  the project root: a symlink or junction anywhere on the way (for example
  ``web/js/panels`` linked to ``coaches/``) makes the resolved target differ
  from the lexical one and the proposal is refused;
- one proposal may not name the same file twice (case-insensitively on
  Windows);
- a target that exists but is not a regular file is refused before any
  write, and a write that fails part-way ROLLS BACK every file already
  written (prior bytes restored, newly created files removed), so a
  proposal is applied whole or not at all;
- content must encode as UTF-8 and carry no NUL; CRLF / CR are written as
  LF (every live target is LF-only, the repo rule).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from core.polled_json import atomic_write_bytes

logger = logging.getLogger("agent4.ui_applier")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Strict whitelist per round 42 scope decision, repointed to the live
# UI (s236). Paths are relative to the project root. Exact files first;
# the per-panel module dirs are prefix-allowed (flat, one extension).
ALLOWED_PATHS: frozenset[str] = frozenset({
    "web/index.html",
    "web/js/main.js",
})
# (prefix, required-suffix) for the live per-panel ESM/CSS modules. The
# panels dirs are flat (no sub-subdirs) - _is_path_allowed enforces it.
ALLOWED_DIR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("web/js/panels/", ".js"),
    ("web/css/panels/", ".css"),
)

MAX_FILE_BYTES = 512 * 1024     # 512 KiB cap - main.js is the largest live target
MAX_CHANGES = 4

_STEM_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)
# Windows device names: "<name>.<anything>" opens the device, not a file.
_RESERVED_STEMS = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


class UIApplyError(RuntimeError):
    """Raised when a proposal fails validation or the write errors."""


def _is_path_allowed(rel_path: Any) -> bool:
    if not isinstance(rel_path, str):
        return False
    if rel_path in ALLOWED_PATHS:
        return True
    for prefix, suffix in ALLOWED_DIR_PREFIXES:
        if rel_path.startswith(prefix):
            # Flat module dir only - no sub-subdirs, single fixed suffix.
            remainder = rel_path[len(prefix):]
            if not remainder.endswith(suffix):
                return False
            stem = remainder[: -len(suffix)]
            if not stem or len(stem) > 64:
                return False
            if stem.lower() in _RESERVED_STEMS:
                return False
            # ASCII-only charset also excludes "/", "\\" and ".".
            return all(c in _STEM_CHARS for c in stem)
    return False


def _norm(p: Path) -> str:
    return os.path.normcase(str(p))


def _resolve_target(rel_path: str) -> Path:
    """Resolve + validate the target.

    The resolved path must stay under the project root (defense in depth
    against ``..``) AND must equal the lexical ``root / rel_path``: a
    symlink or junction on any component would redirect the write to a
    file the whitelist never named, so it is refused (RM-1904)."""
    root = _PROJECT_ROOT.resolve()
    p = (root / rel_path).resolve()
    try:
        p.relative_to(root)
    except ValueError as exc:
        raise UIApplyError(f"path escapes project root: {rel_path}") from exc
    if _norm(p) != _norm(root / rel_path):
        raise UIApplyError(
            f"path {rel_path!r} resolves through a link outside its whitelisted dir"
        )
    return p


def _atomic_write(target: Path, content: bytes) -> None:
    """Write via ``.tmp`` + ``os.replace``. Same atomic-write invariant
    overlays rely on per CLAUDE.md."""
    atomic_write_bytes(target, content)


def _validate_js_sanity(content: str, rel_path: str) -> None:
    """Cheap guards against obvious damage on .js files."""
    # Balanced braces + parens - a smoke test, not full parse.
    open_c, close_c = content.count("{"), content.count("}")
    if abs(open_c - close_c) > 2:
        raise UIApplyError(
            f"{rel_path}: unbalanced braces (open={open_c} close={close_c})"
        )
    open_p, close_p = content.count("("), content.count(")")
    if abs(open_p - close_p) > 2:
        raise UIApplyError(
            f"{rel_path}: unbalanced parens (open={open_p} close={close_p})"
        )
    # Detect accidental truncation of the main ESM entrypoint - it is
    # always well over 2 KB, so a tiny payload means a truncated write.
    # Small per-panel modules legitimately exist, so this guard is
    # scoped to main.js only.
    if rel_path.endswith("/main.js") and len(content) < 2_000:
        raise UIApplyError(
            f"{rel_path}: suspiciously short ({len(content)} bytes)"
        )


def _validate_content(rel_path: str, content: str) -> bytes:
    """Validate ``content`` and return the exact bytes to write."""
    if "\x00" in content:
        raise UIApplyError(f"{rel_path}: content carries a NUL character")
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise UIApplyError(
            f"{rel_path}: content is not encodable as UTF-8 "
            f"(position {exc.start})"
        ) from exc
    if len(data) > MAX_FILE_BYTES:
        raise UIApplyError(f"{rel_path}: exceeds {MAX_FILE_BYTES} bytes")
    if rel_path.endswith(".js"):
        _validate_js_sanity(content, rel_path)
    # .css / .html - trust the parser / browser tolerance.
    return data


def _read_prior(target: Path, rel: str) -> bytes | None:
    """Current bytes of ``target`` (None when absent), for rollback."""
    try:
        if not target.exists():
            return None
        if not target.is_file():
            raise UIApplyError(f"{rel}: target exists and is not a regular file")
        return target.read_bytes()
    except OSError as exc:
        raise UIApplyError(
            f"{rel}: cannot read current file ({type(exc).__name__})"
        ) from exc


def _rollback(done: list[tuple[Path, str, bytes | None]]) -> list[str]:
    """Undo already-applied writes, newest first. Returns the rel paths
    that could NOT be restored (logged at ERROR)."""
    failed: list[str] = []
    for target, rel, prior in reversed(done):
        try:
            if prior is None:
                target.unlink(missing_ok=True)
            else:
                _atomic_write(target, prior)
        except OSError:
            logger.exception("ui_applier rollback failed for %s", rel)
            failed.append(rel)
    return failed


def apply_ui_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one proposal's ``changes`` atomically, all or nothing.

    Payload shape::

        {
          "changes": [
            {"file": "web/css/panels/base.css", "content": "...full new file..."},
            ...
          ]
        }

    Each change carries FULL file content (not a diff). Simpler to
    validate and roll back than textual patches - the parser is
    responsible for producing correct complete files. Tasks with zero
    or >4 changes are rejected (sanity bound). Every rejection and every
    write failure raises ``UIApplyError``; a write failure first restores
    every file this call already wrote.

    Returns a result dict the dispatcher stores on the task.
    """
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise UIApplyError(
            f"proposal payload must be an object, got {type(payload).__name__}"
        )
    changes = payload.get("changes") or []
    if not isinstance(changes, list):
        raise UIApplyError(
            f"proposal 'changes' must be a list, got {type(changes).__name__}"
        )
    if not (1 <= len(changes) <= MAX_CHANGES):
        raise UIApplyError(
            f"proposal must carry 1-{MAX_CHANGES} changes, got {len(changes)}"
        )

    # Validate EVERYTHING before writing anything - so we never half-apply.
    # (target, rel_path, data, prior bytes or None)
    validated: list[tuple[Path, str, bytes, bytes | None]] = []
    seen: set[str] = set()
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            raise UIApplyError(f"change[{i}]: must be an object")
        raw_rel = ch.get("file")
        if raw_rel is None:
            raw_rel = ""
        if not isinstance(raw_rel, str):
            raise UIApplyError(f"change[{i}]: 'file' must be a string")
        rel = raw_rel.strip()
        content = ch.get("content")
        if not rel:
            raise UIApplyError(f"change[{i}]: missing 'file'")
        if not isinstance(content, str):
            raise UIApplyError(f"change[{i}]: 'content' must be a string")
        if not _is_path_allowed(rel):
            raise UIApplyError(
                f"change[{i}]: path {rel!r} not in UI whitelist"
            )
        data = _validate_content(rel, content)
        target = _resolve_target(rel)
        key = _norm(target)
        if key in seen:
            raise UIApplyError(f"change[{i}]: {rel!r} named twice in one proposal")
        seen.add(key)
        validated.append((target, rel, data, _read_prior(target, rel)))

    written: list[dict[str, Any]] = []
    done: list[tuple[Path, str, bytes | None]] = []
    for target, rel, data, prior in validated:
        try:
            # atomic_write_bytes replaces in one step and removes its own
            # scratch file on failure, so a failed write left ``target``
            # as it was: only the EARLIER files need restoring.
            _atomic_write(target, data)
        except OSError as exc:
            unrestored = _rollback(done)
            msg = (
                f"{rel}: write failed ({type(exc).__name__}); "
                f"rolled back {len(done) - len(unrestored)} earlier file(s)"
            )
            if unrestored:
                msg += f"; COULD NOT restore {', '.join(unrestored)}"
            raise UIApplyError(msg) from exc
        done.append((target, rel, prior))
        try:
            new_size = target.stat().st_size
        except OSError:
            new_size = len(data)
        prev_size = None if prior is None else len(prior)
        written.append({
            "file": rel,
            "prev_bytes": prev_size,
            "new_bytes": new_size,
            "delta_bytes": (new_size - (prev_size or 0)),
        })
        logger.info(
            "ui_applier wrote %s (%s -> %s bytes)",
            rel, prev_size, new_size,
        )
    return {
        "applied": True,
        "files": written,
        "count": len(written),
    }
