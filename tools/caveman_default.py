"""caveman_default.py - SessionStart hook: declare CAVEMAN + WENYAN-FULL as the
default output dialect for every Legion Claude Code session (operator 2026-06-27).

Wired in .claude/settings.json SessionStart hooks (the prior file was missing, so
the fleet caveman-default was silently dead - revived here). stdout is injected as
session context. Must be fast (timeout 5) and must NEVER raise - a crashing hook
would noise every session start. Pairs with tools/caveman.md (the skill body).
"""
from __future__ import annotations

import sys

_BANNER = (
    "# Output dialect: CAVEMAN + WENYAN-FULL (default, operator 2026-06-27)\n"
    "\n"
    "Default to caveman terseness in WENYAN-FULL classical Chinese (wen yan wen) "
    "for chat / prose output - target 80-90 percent character reduction. Keep "
    "BYTE-EXACT + strict 7-bit ASCII (never compressed or translated): file paths, "
    "shell commands, code, identifiers, machine-parsed tokens, and ALL committed "
    "repo artifacts (code / docstrings / .md / commit messages / .ps1 - the "
    "CLAUDE.md hard rule; PowerShell ParseFile mangles a non-ASCII .ps1). Answer "
    "the operator's clarifying questions in plain English, NOT wenyan. Reference: "
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
