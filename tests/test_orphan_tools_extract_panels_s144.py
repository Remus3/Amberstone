"""Dead-code drift guard: tools/extract_panels.py stays deleted (s144 repo lane).

tools/extract_panels.py was the s133 (2026-05-08) one-shot that split
web/js/main.js into the first ES panel modules under web/js/panels/. It was
removed in session 144 because it was dead on two independent facts, and
dangerous besides:

  1. ZERO consumers. No .py / .js / .ps1 / .bat / .json / .yml / .html /
     settings / scheduled-task reference outside tests/ and dated history
     (docs/history_notes.md, docs/LEDGER.md, ops/audit/*.md). The only
     tracked readers were two tests that parsed its source as text
     (tests/test_tools_ascii_hygiene.py, tests/test_bridge_decommissioned_oq2.py).
  2. Its input contract is gone. Every L(start, end) line range addresses the
     6223-line PRE-split main.js (LEDGER 1096); main.js has since been
     rewritten many times, and the panel files it once generated are now
     hand-maintained.

Dangerous: it ran at MODULE SCOPE, so even an import rewrote web/js/main.js
(after a main.js.bak copy) and overwrote six tracked panel files with no
backup, all from stale line ranges - in text mode with no newline=, so on
Windows the rewritten tracked files also turned CRLF (the RM-481 writer
class). A re-run corrupted the tree rather than re-extracting.

Same shape as tests/test_orphan_scripts_item195.py. If you find yourself
adding it back, first confirm a real consumer exists.
"""
from __future__ import annotations

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_DELETED = "tools/extract_panels.py"


def test_extract_panels_one_shot_stays_deleted() -> None:
    assert not (REPO_ROOT / _DELETED).exists(), (
        f"{_DELETED} reappeared. It is a spent one-shot whose line ranges "
        "address a main.js that no longer exists; running or importing it "
        "overwrites web/js/main.js and tracked panel files. Confirm a real "
        "consumer before restoring it."
    )


def test_no_tracked_text_still_invokes_the_one_shot() -> None:
    """No runnable tracked file may call the deleted tool.

    Prose history (docs/, *.md) and tests/ (this guard names the file) are
    out of scope; data/ and web/data/ are bulk game data, not callers.
    *.xml covers the tracked scheduled-task definitions.
    """
    patterns = ("*.py", "*.ps1", "*.bat", "*.cmd", "*.json", "*.yml",
                "*.yaml", "*.js", "*.mjs", "*.html", "*.xml")
    skip = ("tests/", "docs/", "data/", "web/data/")
    scanned = 0
    offenders = []
    for path in iter_repo_files(REPO_ROOT, patterns):
        rel = relative_posix(path)
        if rel.startswith(skip) or "/tests/" in rel:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        if "extract_panels.py" in text:
            offenders.append(rel)
    # An empty walk would pass vacuously; the tree holds thousands of these.
    assert scanned > 500, f"walk saw only {scanned} files - the scan is broken"
    assert offenders == [], f"live references to the deleted one-shot: {offenders}"
