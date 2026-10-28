"""Dead-code drift guard: scripts/extract_css_panels.py stays deleted (s144 repo lane).

scripts/extract_css_panels.py was the s135 (2026-05-08) Phase 3.1 one-shot
that split a 5812-line web/css/dashboard.css into 13 files under
web/css/panels/ and rewrote dashboard.css as an @import router. It was
removed in session 144 because it was dead on two independent facts, and
dangerous besides:

  1. ZERO consumers. No .py / .js / .ps1 / .bat / .json / .yml / .html /
     .xml / CI / scheduled-task reference outside dated history
     (docs/history_notes.md, docs/LEDGER.md, docs/audits/, docs/_archive/).
     The repo review filed it as a finished one-shot (B27-02, RM-721), and
     docs/history_notes.md already says "Don't re-run" it.
  2. Its input contract is gone. Every SECTIONS / CHAMP_SELECT_RANGES line
     range addresses the 5812-line PRE-split dashboard.css; that file is now
     an 89-line router importing 64 panel files, not the 13 it knew.

Dangerous: a run read the router as if it were the old monolith, overwrote
the 10 of its 13 panel files that are still tracked with slices of @import
lines or nothing (and re-created the 3 since removed: bridge_pending.css,
dev.css, champ_select.css), and rewrote dashboard.css with only 13 of the 64 imports - all through
Path.write_text with no newline=, so on Windows the rewritten tracked files
also turned CRLF (the RM-481 writer class).

Same shape as tests/test_orphan_tools_extract_panels_s144.py and
tests/test_orphan_scripts_item195.py. If you find yourself adding it back,
first confirm a real consumer exists.
"""
from __future__ import annotations

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix

_DELETED = "scripts/extract_css_panels.py"


def test_extract_css_panels_one_shot_stays_deleted() -> None:
    assert not (REPO_ROOT / _DELETED).exists(), (
        f"{_DELETED} reappeared. It is a spent one-shot whose line ranges "
        "address a dashboard.css that no longer exists; running it "
        "overwrites tracked web/css/panels files and drops most of the "
        "dashboard.css @import router. Confirm a real consumer before "
        "restoring it."
    )


def test_no_tracked_text_still_invokes_the_one_shot() -> None:
    """No runnable tracked file may call the deleted script.

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
        if "extract_css_panels" in text:
            offenders.append(rel)
    # An empty walk would pass vacuously; the tree holds thousands of these.
    assert scanned > 500, f"walk saw only {scanned} files - the scan is broken"
    assert offenders == [], f"live references to the deleted one-shot: {offenders}"
