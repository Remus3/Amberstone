#!/usr/bin/env python3
"""PostToolUse fast syntax gate (tiered-verification default, 2026-06-13).

Reads the Claude Code PostToolUse hook payload on stdin and runs a FAST
syntax check on edited *.py files only. It never runs a test suite.
This implements the operator-accepted tiered-verification tradeoff (CLAUDE.md
"Execution Efficiency & Tooling Rules" R5-R7): Tier-0 cosmetic and Tier-1
local-logic edits must not pay the Tier-2 full-suite tax on every edit.

The syntax check still guards the most dangerous class (a syntax error crashes
silently under pythonw.exe - CLAUDE.md hard rule). It is the builtin
compile(source, path, "exec") (MAIN FIX 2026-10-21 1254 #12): py_compile wrote
a .pyc into __pycache__/ beside every edited file; compile() writes nothing.
The CLAUDE.md "py_compile before restart" rule is about that syntax check,
which this still is. A whole suite runs ONLY
through the kit's machine-wide gate, ops/fleet_kit/fleet_suite_gate.py
(FLEET-COMMON 16c; the TIER TABLE in tools/done.md). The RC_FULL_SUITE=1 branch
that re-ran a serial whole-repo `pytest -x --ff -q` on every code edit was
REMOVED 2026-10-09 (MAIN kit-v13 ORDER section 2, PERF-AUDIT item 10): it ran
outside the suite gate, with no timeout. The variable is now ignored apart from
a one-line pointer, so nobody mistakes the silence for a green suite.

The hook spawns no process at all (tests/test_pytest_guard.py pins that), which
is also why it left HOOK_SPAWNERS in tests/test_no_console_flash_scheduled_tools.py.

Docs-only edits (*.md / *.txt / docs/ tree) skip everything, but a Python
source file (*.py / *.pyw) is never docs-only, wherever it lives: eight tracked
scripts sit under docs/, and a checkout path with a docs/ segment used to skip
every edit (true-audit S144-T-544). A SyntaxWarning (an invalid escape, a
return in finally) is not a crash, so compile() runs with warnings ignored:
silent on stderr, and never a false failure under PYTHONWARNINGS=error
(S144-T-545). Always exits 0 (informational, never blocks the tool).

OUTPUT (MAIN FIX 1254 #2; fleet UI/UX standard section 5, FLEET-COMMON item
15). Silent unless there is something to say. Then ONE stdout line
    {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                            "additionalContext": "<one line>"}}
on exit 0, no ANSI. The old plain stdout on exit 0 never reached the model,
so a syntax error after an edit was invisible. Any internal fault exits 0 in
silence.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path

CODE_SKIP_SUFFIXES = (".md", ".txt")
PY_SUFFIXES = (".py", ".pyw")
_MAX_CONTEXT_CHARS = 2000

RETIRED_SUITE_NOTE = (
    "RC_FULL_SUITE is retired - run a whole suite through "
    "ops/fleet_kit/fleet_suite_gate.py (TIER TABLE in tools/done.md)"
)


def _is_python(path: str) -> bool:
    return path.replace("\\", "/").lower().endswith(PY_SUFFIXES)


def _is_docs_only(path: str) -> bool:
    if _is_python(path):
        return False  # S144-T-544: a source file is code wherever it lives
    p = path.replace("\\", "/").lower()
    if p.endswith(CODE_SKIP_SUFFIXES):
        return True
    return "/docs/" in p or p.startswith("docs/")


def _collect_paths(payload: dict) -> list:
    """Edited paths named by the payload, in order, each once (S144-T-546/547)."""
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return []
    found = []
    for key in ("file_path", "notebook_path"):
        found.append(ti.get(key))
    edits = ti.get("edits")
    if isinstance(edits, list):
        found.extend(e.get("file_path") for e in edits if isinstance(e, dict))
    paths = []
    for v in found:
        if isinstance(v, str) and v and v not in paths:
            paths.append(v)
    return paths


def _syntax_error(path: str) -> str | None:
    """One-line syntax finding for `path`, or None when it compiles.

    compile() on the raw bytes honours a BOM and a coding cookie exactly as
    the interpreter does, and - unlike py_compile - writes no bytecode.
    """
    try:
        with Path(path).open("rb") as fh:
            source = fh.read()
    except OSError:
        return None  # vanished or unreadable: nothing to say
    try:
        # S144-T-545: a SyntaxWarning is not a crash. Ignored, it neither
        # leaks to stderr nor (under PYTHONWARNINGS=error) becomes a false
        # SyntaxError report.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            compile(source, path, "exec", dont_inherit=True)
    except SyntaxError as exc:
        line = exc.lineno or 0
        msg = " ".join(str(exc.msg or "invalid syntax").split())[:160]
        return f"{path}:{line} {type(exc).__name__}: {msg}"
    except ValueError as exc:  # e.g. source with a NUL byte
        return f"{path}:0 {type(exc).__name__}: {' '.join(str(exc).split())[:160]}"
    except (MemoryError, RecursionError) as exc:
        # A source nested too deep to parse / compile. py_compile reported it;
        # so must this, rather than letting main()'s guard swallow it silently.
        return f"{path}:0 {type(exc).__name__}: the source is nested too deep to compile"
    return None


def _emit(text: str) -> None:
    """ONE stdout line of PostToolUse additionalContext (ASCII, no ANSI)."""
    one = " ".join(text.split())
    if len(one) > _MAX_CONTEXT_CHARS:
        one = one[: _MAX_CONTEXT_CHARS - 3] + "..."
    line = json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse", "additionalContext": one}})
    try:
        if sys.stdout is not None:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


def _read_payload() -> dict:
    # stdin as BYTES, decoded UTF-8, BOM stripped (RM-784 sibling): a text
    # read went through the console code page (cp1252 has no 0x81, so a
    # UTF-8 path holding U+0101 faulted) and a PS 5.1 BOM was never stripped.
    try:
        stream = sys.stdin
        data = (getattr(stream, "buffer", None) or stream).read() if stream is not None else ""
    except (OSError, ValueError, AttributeError):
        data = ""
    if isinstance(data, (bytes, bytearray)):
        data = bytes(data).decode("utf-8", errors="replace")
    raw = (data or "").lstrip(chr(0xFEFF))
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, TypeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _run() -> int:
    paths = _collect_paths(_read_payload())
    # Empty / unknown payload, or docs/text only -> nothing to check, silent.
    if not paths or all(_is_docs_only(p) for p in paths):
        return 0

    notes = []
    if os.environ.get("RC_FULL_SUITE") == "1":
        notes.append(RETIRED_SUITE_NOTE)

    py_files = [p for p in paths if _is_python(p)]
    errors = [e for e in (_syntax_error(f) for f in py_files) if e]
    if errors:
        notes.insert(0, "SYNTAX CHECK FAILED (a syntax error crashes silently under "
                        "pythonw.exe): " + "; ".join(errors))
    if notes:
        _emit("[pytest_guard] " + " | ".join(notes))
    return 0


def main() -> int:
    try:
        return _run()
    except Exception:  # noqa: BLE001 - informational hook, never break an edit
        return 0


if __name__ == "__main__":
    sys.exit(main())
