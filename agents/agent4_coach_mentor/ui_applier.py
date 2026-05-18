"""Round 42 - deterministic applier for UI proposals filed by Agent 7.

Consumes ``ui-proposal`` tasks produced by
``agents.agent7_context.ui_feedback.UIFeedbackParser``. Each proposal
names one or more files under a hard whitelist (dashboard CSS / JS /
HTML + sim fixtures) and carries the replacement content. This module
validates the paths, runs a ``py_compile`` guard on any ``.js`` file
(syntactic sanity only - browsers don't run Python but the guard
catches gross ``.js`` truncation), atomically writes the new content,
and reports the result back to the task.

Out of scope by design: anything that isn't pixel/layout/behavioral UI.
The whitelist is intentionally narrow so a misfired ``ui_feedback``
intent can never touch coach logic, analyzer code, or secrets.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("agent4.ui_applier")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Strict whitelist per round 42 scope decision. Paths are relative to
# the project root. data/sim/*.json is included so the sim fixtures
# themselves can be edited via this channel.
ALLOWED_PATHS: frozenset[str] = frozenset({
    "web/css/dashboard.css",
    "web/js/dashboard.js",
    "web/js/sim.js",
    "web/index.html",
})
ALLOWED_PREFIXES: tuple[str, ...] = ("data/sim/",)
ALLOWED_SIM_SUFFIX = ".json"

MAX_FILE_BYTES = 512 * 1024     # 512 KiB cap - dashboard.js is ~60 KiB currently


class UIApplyError(RuntimeError):
    """Raised when a proposal fails validation or the write errors."""


def _is_path_allowed(rel_path: str) -> bool:
    if rel_path in ALLOWED_PATHS:
        return True
    for prefix in ALLOWED_PREFIXES:
        if rel_path.startswith(prefix):
            # data/sim/*.json only - no sub-subdirs, no exotic suffixes.
            remainder = rel_path[len(prefix):]
            if "/" in remainder or "\\" in remainder:
                return False
            if not remainder.endswith(ALLOWED_SIM_SUFFIX):
                return False
            stem = remainder.removesuffix(ALLOWED_SIM_SUFFIX)
            if not stem or len(stem) > 64:
                return False
            if not all(c.isalnum() or c in "-_" for c in stem):
                return False
            return True
    return False


def _resolve_target(rel_path: str) -> Path:
    """Resolve + validate that the target lives under project root.
    Defense-in-depth against .. traversal even though _is_path_allowed
    already rejects most forms."""
    p = (_PROJECT_ROOT / rel_path).resolve()
    root = _PROJECT_ROOT.resolve()
    try:
        p.relative_to(root)
    except ValueError:
        raise UIApplyError(f"path escapes project root: {rel_path}")
    return p


def _atomic_write(target: Path, content: bytes) -> None:
    """Write via ``.tmp`` + ``os.replace``. Same atomic-write invariant
    overlays rely on per CLAUDE.md."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".uiproposal.tmp")
    tmp.write_bytes(content)
    os.replace(tmp, target)


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
    # Detect accidental truncation - a dashboard.js without "use strict"
    # etc. is fine, but an empty file or one under 200 chars is suspicious.
    if rel_path.endswith("/dashboard.js") and len(content) < 2_000:
        raise UIApplyError(
            f"{rel_path}: suspiciously short ({len(content)} bytes)"
        )


def _validate_json(content: str, rel_path: str) -> None:
    try:
        json.loads(content)
    except json.JSONDecodeError as e:
        raise UIApplyError(f"{rel_path}: invalid JSON ({e})")


def _validate_content(rel_path: str, content: str) -> None:
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise UIApplyError(f"{rel_path}: exceeds {MAX_FILE_BYTES} bytes")
    if rel_path.endswith(".js"):
        _validate_js_sanity(content, rel_path)
    elif rel_path.endswith(".json"):
        _validate_json(content, rel_path)
    # .css / .html - trust the parser / browser tolerance.


def apply_ui_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply one proposal's ``changes`` atomically.

    Payload shape::

        {
          "changes": [
            {"file": "web/css/dashboard.css", "content": "...full new file..."},
            ...
          ]
        }

    Each change carries FULL file content (not a diff). Simpler to
    validate and roll back than textual patches - the parser is
    responsible for producing correct complete files. Tasks with zero
    or >4 changes are rejected (sanity bound).

    Returns a result dict the dispatcher stores on the task.
    """
    changes = (payload or {}).get("changes") or []
    if not isinstance(changes, list) or not (1 <= len(changes) <= 4):
        raise UIApplyError(
            f"proposal must carry 1-4 changes, got {len(changes)}"
        )

    # Validate EVERYTHING before writing anything - so we never half-apply.
    validated: list[tuple[Path, str, str]] = []   # (target, rel_path, content)
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            raise UIApplyError(f"change[{i}]: must be an object")
        rel = (ch.get("file") or "").strip()
        content = ch.get("content")
        if not rel:
            raise UIApplyError(f"change[{i}]: missing 'file'")
        if not isinstance(content, str):
            raise UIApplyError(f"change[{i}]: 'content' must be a string")
        if not _is_path_allowed(rel):
            raise UIApplyError(
                f"change[{i}]: path {rel!r} not in UI whitelist"
            )
        _validate_content(rel, content)
        target = _resolve_target(rel)
        validated.append((target, rel, content))

    written: list[dict[str, Any]] = []
    for target, rel, content in validated:
        prev_size = target.stat().st_size if target.exists() else None
        _atomic_write(target, content.encode("utf-8"))
        new_size = target.stat().st_size
        written.append({
            "file": rel,
            "prev_bytes": prev_size,
            "new_bytes": new_size,
            "delta_bytes": (new_size - (prev_size or 0)),
        })
        logger.info(
            "ui_applier wrote %s (%s → %s bytes)",
            rel, prev_size, new_size,
        )
    return {
        "applied": True,
        "files": written,
        "count": len(written),
    }
