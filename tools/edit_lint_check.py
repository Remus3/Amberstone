"""PostToolUse hook: ruff check + em-dash / smart-quote grep on Edit|Write targets.

Reads $CLAUDE_FILE_PATHS (space-separated) and runs:
  1. C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe -m ruff check --fix <python files>  (auto-fix when possible)
  2. byte scan for U+2014 / U+2013 / U+201C / U+201D / U+2018 / U+2019

Hook output is shown to the model. Stay terse. Exit 0 always (advisory, non-blocking)
so the operator's flow is never stopped by hook noise; Claude reads the warning
in tool output and can self-correct on the next edit.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Hooks run under windowless pythonw.exe; a console-subsystem child (the `py`
# launcher + ruff) would otherwise get a fresh console allocated - an on-screen
# + taskbar flash on every edit. CREATE_NO_WINDOW suppresses it (Windows-only;
# 0 elsewhere).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_BANNED = {
    chr(0x2014): "em-dash",
    chr(0x2013): "en-dash",
    chr(0x201C): "smart-dquote-open",
    chr(0x201D): "smart-dquote-close",
    chr(0x2018): "smart-quote-open",
    chr(0x2019): "smart-quote-close",
}

_FROZEN_SKIP = ("logs/", "docs/_archive/", ".pyc", ".git/", "__pycache__/")


def _is_skippable(p: Path) -> bool:
    s = str(p).replace("\\", "/")
    return any(skip in s for skip in _FROZEN_SKIP)


def _scan_banned(path: Path) -> list[str]:
    try:
        data = path.read_bytes()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    hits: list[str] = []
    for cp, name in _BANNED.items():
        count = text.count(cp)
        if count > 0:
            hits.append(f"{name} x{count}")
    return hits


def main() -> int:
    raw = os.environ.get("CLAUDE_FILE_PATHS", "").strip()
    if not raw:
        return 0
    paths = [Path(p) for p in raw.split() if p]
    paths = [p for p in paths if p.exists() and not _is_skippable(p)]
    if not paths:
        return 0

    py_files = [str(p) for p in paths if p.suffix == ".py"]
    if py_files:
        try:
            subprocess.run(
                ["py", "-m", "ruff", "check", "--fix", *py_files],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    flagged: list[str] = []
    for p in paths:
        hits = _scan_banned(p)
        if hits:
            flagged.append(f"  {p}: {', '.join(hits)}")
    if flagged:
        sys.stderr.write("BANNED-GLYPH FOUND (CLAUDE.md hard rule):\n")
        sys.stderr.write("\n".join(flagged) + "\n")
        sys.stderr.write("Fix: tools/strip_em_dashes.py + tools/strip_smart_quotes.py\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
