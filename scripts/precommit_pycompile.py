"""
scripts/precommit_pycompile.py - pre-commit guard.

AUDIT 2026-04-28 (proposal 4.1): py_compile every staged .py file before
the commit lands. CLAUDE.md already mandates py_compile before any
restart; a syntax error under pythonw.exe crashes silently. Catching it
here keeps a broken file from ever entering history.

Install once per clone:
    git config core.hooksPath .githooks

The repo-tracked .githooks/pre-commit shim invokes this script.
"""
from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def staged_python_files() -> list[Path]:
    """Files added/modified/copied in the upcoming commit (excluding deletes)."""
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=str(ROOT), text=True,
    )
    return [ROOT / line for line in out.splitlines() if line.endswith(".py")]


def main() -> int:
    files = staged_python_files()
    if not files:
        return 0
    failed: list[tuple[Path, str]] = []
    for p in files:
        if not p.exists():
            # Edge case: file staged but later removed/moved before commit.
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as exc:
            failed.append((p, str(exc)))
        except SyntaxError as exc:
            failed.append((p, f"{exc.__class__.__name__}: {exc}"))
    if failed:
        print(f"pre-commit: py_compile failed on {len(failed)} file(s):", file=sys.stderr)
        for p, msg in failed:
            rel = p.relative_to(ROOT) if p.is_relative_to(ROOT) else p
            print(f"  {rel}: {msg}", file=sys.stderr)
        print(
            "\nFix the syntax errors above and re-run `git commit`. To bypass\n"
            "(rarely correct), pass --no-verify.",
            file=sys.stderr,
        )
        return 1
    print(f"pre-commit: py_compile OK ({len(files)} file(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
