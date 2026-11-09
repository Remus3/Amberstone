"""S144-P-292 - a living docs/ subdirectory *.md never names a repo script that is gone as if it were live.

Closes the last gap of the missing-script cite family: tools/*.md (p284), root-level docs/*.md (p285), the root README
and CI / hook config (p290) and every other sub-project markdown (p291) are guarded; this guard covers the markdown
files BELOW docs/ - ``docs/adr/``, ``docs/handoff/``, ``docs/releases/``, ``docs/superpowers/``, ``docs/_overlap/``,
``docs/_rescore/`` and ``docs/_rsc_score/``.

Measured 2026-11-06 over the 124 tracked ``*.md`` below docs/ subdirectories: 15 of them carry a bare cite of an
untracked script under the p284 scanner. Fourteen are dated records and are out of scope by name (``_DATED_ROOTS``):
``docs/_archive/`` (every file there is a dated artifact by the repo's own rule), ``docs/specs/`` (specs and kickoff
briefs written against the tree of their date), ``docs/qa/`` (dated QA runs), ``docs/audits/`` (dated findings) and
``docs/research/`` (dated consolidation). The one living hit, ``docs/handoff/POWERSHELL_7_MIGRATION.md``, cited the
removed ``ops/launch_new_system.bat`` as a live shim; it now says so and the guard ships at zero with an empty
``_ALLOWED``.

The same p284 scanner is used: a cite of an untracked ``<top-dir>/<path>.<ext>`` needs a history word within three
lines, or an entry in ``_ALLOWED`` (file, path), which only shrinks.
"""
from __future__ import annotations

import subprocess

from tests._repo_walk import REPO_ROOT
from tests.test_command_doc_script_cites_s144p284 import scan_source

# Dated records: a cite of a file that existed then is history, whatever the nearby words.
_DATED_ROOTS = (
    "docs/_archive/",
    "docs/specs/",
    "docs/qa/",
    "docs/audits/",
    "docs/research/",
)

# (file, cited path) -> why it is not a dangling pointer. Only shrinks; ships empty.
_ALLOWED: set[tuple[str, str]] = set()


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _scoped(tracked: frozenset[str]) -> list[str]:
    return sorted(
        p for p in tracked
        if p.endswith(".md")
        and p.startswith("docs/")
        and p.count("/") >= 2
        and not p.startswith(_DATED_ROOTS)
    )


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _scoped(tracked):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        found.update((rel, cited) for _line, cited in scan_source(src, tracked))
    return found


def test_scope_is_enumerated():
    scoped = _scoped(_tracked())
    assert "docs/handoff/POWERSHELL_7_MIGRATION.md" in scoped
    assert any(p.startswith("docs/adr/") for p in scoped)
    assert "docs/LEDGER.md" not in scoped and "docs/ARCHITECTURE.md" not in scoped
    assert not any(p.startswith(_DATED_ROOTS) for p in scoped)
    assert len(scoped) >= 40


def test_no_bare_cite_of_a_missing_script_in_a_docs_subdir_md():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "markdown file cites a repo script that is not tracked and carries no history word within 3 lines "
        f"(say it was removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_dated_roots_exist():
    tracked = _tracked()
    for root in _DATED_ROOTS:
        assert any(p.startswith(root) and p.endswith(".md") for p in tracked), (
            f"dated root names no tracked markdown file: {root}"
        )


def test_scanner_is_live_on_this_scope():
    """A dangling cite in a scoped file would be reported; a history-worded one would not."""
    tracked = _tracked()
    bare = "Run `python tools/agent9_gone/run.py` nightly.\n"
    assert scan_source(bare, tracked) == [(1, "tools/agent9_gone/run.py")]
    history = "The script `tools/agent9_gone/run.py` was removed in 2026.\n"
    assert scan_source(history, tracked) == []
