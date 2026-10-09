#!/usr/bin/env python3
"""PostToolUse fast syntax gate (tiered-verification default, 2026-06-13).

Reads the Claude Code PostToolUse hook payload on stdin and runs a FAST
py_compile syntax check on edited *.py files only. It never runs a test suite.
This implements the operator-accepted tiered-verification tradeoff (CLAUDE.md
"Execution Efficiency & Tooling Rules" R5-R7): Tier-0 cosmetic and Tier-1
local-logic edits must not pay the Tier-2 full-suite tax on every edit.

py_compile still guards the most dangerous class (a syntax error crashes
silently under pythonw.exe - CLAUDE.md hard rule). A whole suite runs ONLY
through the kit's machine-wide gate, ops/fleet_kit/fleet_suite_gate.py
(FLEET-COMMON 16c; the TIER TABLE in tools/done.md). The RC_FULL_SUITE=1 branch
that re-ran a serial whole-repo `pytest -x --ff -q` on every code edit was
REMOVED 2026-10-09 (MAIN kit-v13 ORDER section 2, PERF-AUDIT item 10): it ran
outside the suite gate, with no timeout. The variable is now ignored apart from
a one-line pointer, so nobody mistakes the silence for a green suite.

The hook spawns no process at all (tests/test_pytest_guard.py pins that), which
is also why it left HOOK_SPAWNERS in tests/test_no_console_flash_scheduled_tools.py.

Docs-only edits (*.md / *.txt / docs/ tree) skip everything. Always exits 0
(informational, never blocks the tool).
"""
import json
import os
import py_compile
import sys

CODE_SKIP_SUFFIXES = (".md", ".txt")

RETIRED_SUITE_NOTE = (
    "RC_FULL_SUITE is retired - run a whole suite through "
    "ops/fleet_kit/fleet_suite_gate.py (TIER TABLE in tools/done.md)"
)


def _is_docs_only(path: str) -> bool:
    p = path.replace("\\", "/").lower()
    if p.endswith(CODE_SKIP_SUFFIXES):
        return True
    return "/docs/" in p or p.startswith("docs/")


def _collect_paths(payload: dict) -> list:
    ti = payload.get("tool_input") or {}
    paths = []
    for key in ("file_path", "notebook_path"):
        v = ti.get(key)
        if isinstance(v, str) and v:
            paths.append(v)
    edits = ti.get("edits")
    if isinstance(edits, list):
        for e in edits:
            if isinstance(e, dict) and isinstance(e.get("file_path"), str):
                paths.append(e["file_path"])
    return paths


def _fast_compile(py_files: list) -> int:
    errors = []
    for f in py_files:
        try:
            py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"  {f}: {exc.msg.splitlines()[0][:160]}")
        except OSError:
            pass
    if errors:
        sys.stdout.write("[pytest_guard] py_compile FAILED:\n" + "\n".join(errors) + "\n")
    else:
        sys.stdout.write(
            f"[pytest_guard] py_compile OK ({len(py_files)} file(s)); "
            "suite NOT run (tiered default - run tiered tests per R5-R7)\n"
        )
    return 0


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, TypeError):
        payload = {}

    paths = _collect_paths(payload)
    # Empty / unknown payload -> skip (no code identifiable to test).
    if not paths:
        print("[pytest_guard] no edit paths in payload - skipped")
        return 0
    # All paths are docs/text -> skip.
    if all(_is_docs_only(p) for p in paths):
        joined = ", ".join(paths)
        print(f"[pytest_guard] docs-only edit ({joined}) - skipped")
        return 0

    if os.environ.get("RC_FULL_SUITE") == "1":
        print(f"[pytest_guard] {RETIRED_SUITE_NOTE}")

    py_files = [p for p in paths if p.replace("\\", "/").lower().endswith(".py")]
    if not py_files:
        print("[pytest_guard] non-python code edit - suite NOT run (tiered default)")
        return 0
    return _fast_compile(py_files)


if __name__ == "__main__":
    sys.exit(main())
