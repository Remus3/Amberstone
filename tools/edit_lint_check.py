"""PostToolUse hook: ruff + glyph + CREDENTIAL scan on Edit|Write targets.

Reads $CLAUDE_FILE_PATHS (space-separated) and runs:
  1. $env:LOCALAPPDATA/Programs/Python/Python314/python.exe -m ruff check --fix <python files>  (auto-fix when possible)
  2. byte scan for U+2014 / U+2013 / U+201C / U+201D / U+2018 / U+2019
  3. credential-shape scan (tools/credential_patterns.py)

Hook output is shown to the model. Stay terse. Arms 1 and 2 are advisory and
exit 0 so the operator's flow is never stopped by hook noise; Claude reads the
warning in tool output and self-corrects on the next edit.

ARM 3 IS DIFFERENT AND EXITS 2. This hook is the ONLY RC control whose
population includes UNTRACKED files - measured in
`docs/specs/2026-09-20-shared-git-root-bucket-rc-share-scan.md` Q3, which found
that a credential in a file that is not staged, not in a push range and not in
the git index is invisible to 100 per cent of RC's other controls. A
credential-shaped literal is not hook noise, so it is surfaced loudly rather
than folded into the advisory stream. The write has already happened by the
time a PostToolUse hook runs; exit 2 surfaces the finding to the model, it does
not roll anything back.

NO MATCHED VALUE IS EVER PRINTED, LOGGED OR WRITTEN. Arm 3 reports file, line
and pattern CLASS. See the contract at the head of tools/credential_patterns.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

try:
    from tools import credential_patterns
except ImportError:  # hook runs as a bare script, so sys.path[0] is tools/
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import credential_patterns

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
            proc = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--fix", *py_files],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=_NO_WINDOW,
            )
            # Surface ruff output so the model sees lint errors immediately
            # after each edit, not just at commit time via precommit_gate.
            ruff_out = (proc.stdout or "").strip()
            ruff_err = (proc.stderr or "").strip()
            if ruff_out or ruff_err:
                combined = "\n".join(
                    s for s in (ruff_out, ruff_err) if s
                )
                sys.stderr.write(f"[edit_lint_check] ruff:\n{combined}\n")
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

    # Arm 3: credential shapes. The scan is wrapped so a bug in the arm cannot
    # crash the write path - but the EMIT below sits OUTSIDE that guard, so a
    # genuine finding can never be swallowed by the same except that catches
    # this module's own faults.
    cred_flagged: list[str] = []
    cred_faults: list[str] = []
    for p in paths:
        try:
            findings = credential_patterns.scan_file(p)
            if findings:
                cred_flagged.extend(
                    credential_patterns.format_findings(str(p), findings)
                )
            elif credential_patterns.was_truncated(p):
                cred_faults.append(f"  {p}: larger than the scan budget, head only")
        except Exception as exc:  # noqa: BLE001 - fail-safe: never break a write
            # Type name only. Exception text can carry file content.
            cred_faults.append(f"  {p}: credential scan skipped ({type(exc).__name__})")

    if cred_flagged:
        sys.stderr.write("CREDENTIAL SHAPE FOUND - DO NOT COMMIT; ROTATE IF REAL:\n")
        sys.stderr.write("\n".join(cred_flagged) + "\n")
        sys.stderr.write(
            "No value is printed, by design - open the file:line yourself.\n"
            "Exempt a deliberate fixture line with: "
            + credential_patterns.PRAGMA
            + "\n"
        )
    if cred_faults:
        sys.stderr.write("[edit_lint_check] credential arm, non-blocking notes:\n")
        sys.stderr.write("\n".join(cred_faults) + "\n")

    return 2 if cred_flagged else 0


if __name__ == "__main__":
    sys.exit(main())
