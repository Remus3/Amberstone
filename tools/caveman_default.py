"""caveman_default.py - per-repo SessionStart hook: declare CAVEMAN ULTRA as the
default output dialect for Claude Code sessions opened in THIS repo (operator
2026-06-27). It is not machine-wide: it runs only where this repo's project
.claude/settings.json wires it (template: ops/claude_settings.example.json), so
a session in another tree or another machine does not get it (MAIN FIX
2026-10-21 1254 item 20).

Wired in .claude/settings.json SessionStart hooks (the prior file was missing, so
the fleet caveman-default was silently dead - revived here). stdout is injected as
session context. Must be fast (timeout 5) and must NEVER raise - a crashing hook
would noise every session start. Pairs with tools/caveman.md (the skill body).

DIALECT HISTORY: a 2026-06-27 experiment layered WENYAN-FULL (classical Chinese)
on top of caveman for extra token economy; the operator reverted it the same day
(too lossy / hard to skim) back to CAVEMAN ULTRA - terse plain-ASCII caveman, no
classical Chinese.
"""
from __future__ import annotations

import sys

_BANNER = (
    "# Output dialect: CAVEMAN ULTRA (default, operator 2026-06-27)\n"
    "\n"
    "Default to CAVEMAN ULTRA for chat / prose output - maximum caveman terseness "
    "in plain 7-bit ASCII English: drop articles + filler, short clauses, no "
    "hedging, target 80-90 percent character reduction. NOT wenyan / classical "
    "Chinese (that experiment was reverted 2026-06-27). Keep BYTE-EXACT + strict "
    "7-bit ASCII (never paraphrased): file paths, shell commands, code, "
    "identifiers, machine-parsed tokens, and ALL committed repo artifacts (code / "
    "docstrings / .md / commit messages / .ps1 - the CLAUDE.md hard rule). Answer "
    "the operator's clarifying questions in plain English. Reference: "
    "tools/caveman.md.\n"
)


def main() -> int:
    try:
        sys.stdout.write(_BANNER)
    except Exception:  # noqa: BLE001 - a hook must never break session start
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
