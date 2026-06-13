#!/usr/bin/env python3
"""PostToolUse fast syntax gate (tiered-verification default, 2026-06-13).

Reads the Claude Code PostToolUse hook payload on stdin. DEFAULT behavior is a
FAST py_compile syntax check on edited *.py files only - it does NOT run the
test suite. This implements the operator-accepted tiered-verification tradeoff
(CLAUDE.md "Execution Efficiency & Tooling Rules" R5-R7): Tier-0 cosmetic and
Tier-1 local-logic edits must not pay the Tier-2 full-suite tax on every edit.

py_compile still guards the most dangerous class (a syntax error crashes
silently under pythonw.exe - CLAUDE.md hard rule). Tier-2 work
(schema / engine / ENGINE_VERSION / item-effect) runs the full suite explicitly,
model-driven, per R5. Set RC_FULL_SUITE=1 to restore the prior behavior
(auto `pytest -x --ff -q` on every code edit) for an automated Tier-2 batch.

Docs-only edits (*.md / *.txt / docs/ tree) skip everything. Always exits 0
(informational, never blocks the tool).
"""
import json
import os
import py_compile
import subprocess
import sys

CODE_SKIP_SUFFIXES = (".md", ".txt")


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


def _full_suite() -> int:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-x", "--ff", "-q"],
        capture_output=True,
        text=True,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    tail = combined.splitlines()[-20:]
    sys.stdout.write("\n".join(tail) + "\n")
    return 0


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

    # Tier-2 opt-in: restore the old auto-suite behavior for a batch.
    if os.environ.get("RC_FULL_SUITE") == "1":
        return _full_suite()

    py_files = [p for p in paths if p.replace("\\", "/").lower().endswith(".py")]
    if not py_files:
        print("[pytest_guard] non-python code edit - suite NOT run (tiered default)")
        return 0
    return _fast_compile(py_files)


if __name__ == "__main__":
    sys.exit(main())
