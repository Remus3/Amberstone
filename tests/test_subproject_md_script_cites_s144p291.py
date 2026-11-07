"""S144-P-291 - a sub-project / agent / config / loop-prompt *.md never names a repo script that is gone as if it were live.

Closes the markdown half of the missing-script cite family: tools/*.md (p284), docs/*.md (p285), the root README
and CI / hook config (p290) are covered; this guard covers every OTHER tracked ``*.md`` - ``.github/``, ``config/``,
``lane-widget/``, ``oss/``, ``ops/migrate/``, ``ops/loop/*.md`` and ``ops/loop/prompts/``, ``tests/README.md``,
``agents/*/charter.md``, ``agents/daemon_slayer/*.md``, ``agents/agent6_auditor/safeguards/``.

Measured 2026-11-06 over those 31 files: ZERO bare cites of an untracked script (the one hit in the tree,
``agents/daemon_slayer/CHANGELOG.md``, is an append-only release log: a record of what existed then). The guard
ships at zero so a new doc cannot start with a dangling pointer.

Out of scope: dated or append-only records (``_DATED_ROOTS``: auditor proposals and reports, ``ops/audit/``,
``ops/loop/reports/``, the CHANGELOG), the vendored kit, and the main-session owned rule / ledger files. ``docs/``
subdirectories (specs, adr, qa, audits, handoff and the rest) are NOT scanned by this or any guard: the p285 guard
reads only the root-level ``docs/*.md``. Measured 2026-11-06, 15 of the 124 files below ``docs/`` carry a bare
cite of an untracked script; most are dated specs or QA records, so they are a FILING (S144-P-291 report), not
swept here. The same p284 scanner is used: a cite of an untracked ``<top-dir>/<path>.<ext>`` needs a
history word within three lines, or an entry in ``_ALLOWED`` (file, path), which only shrinks.
"""
from __future__ import annotations

import subprocess

from tests._repo_walk import REPO_ROOT
from tests.test_command_doc_script_cites_s144p284 import scan_source

# Dated / append-only records: a cite of a file that existed then is history, whatever the nearby words.
_DATED_ROOTS = (
    "agents/agent6_auditor/proposals/",
    "agents/agent6_auditor/reports/",
    "ops/audit/",
    "ops/loop/reports/",
)
_DATED_FILES = frozenset({"agents/daemon_slayer/CHANGELOG.md"})
# Covered by a sibling guard (tools/*.md p284, root-level docs/*.md p285, README.md p290), vendored (kit), or held
# by the main session (rules, ledgers, hand-off). The docs/ SUBDIRECTORIES are excluded here and covered by no
# guard (see the module docstring).
_ELSEWHERE_ROOTS = ("docs/", "tools/", "ops/fleet_kit/")
_ELSEWHERE_FILES = frozenset({
    "README.md", "CLAUDE.md", "ROADMAP.md", "BACKLOG.md", "WAKEUP_NOTES.md",
})

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
        and not p.startswith(_DATED_ROOTS + _ELSEWHERE_ROOTS)
        and p not in _DATED_FILES
        and p not in _ELSEWHERE_FILES
    )


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _scoped(tracked):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for _line, cited in scan_source(src, tracked):
            found.add((rel, cited))
    return found


def test_scope_is_enumerated():
    scoped = _scoped(_tracked())
    assert ".github/CONTRIBUTING.md" in scoped
    assert "tests/README.md" in scoped
    assert "agents/agent7_context/charter.md" in scoped
    assert "config/CONFIG_AUTHORITY.md" in scoped
    assert "agents/daemon_slayer/CHANGELOG.md" not in scoped
    assert "docs/LEDGER.md" not in scoped and "tools/done.md" not in scoped
    assert len(scoped) >= 25


def test_no_bare_cite_of_a_missing_script_in_a_subproject_md():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "markdown file cites a repo script that is not tracked and carries no history word within 3 lines "
        f"(say it was removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_exempt_files_exist():
    tracked = _tracked()
    gone = sorted((_DATED_FILES | _ELSEWHERE_FILES) - tracked)
    assert not gone, f"exempt file is not tracked any more - drop it from its set: {gone}"
    for root in _DATED_ROOTS + _ELSEWHERE_ROOTS:
        assert any(p.startswith(root) for p in tracked), f"exempt root names nothing tracked: {root}"


def test_scanner_is_live_on_this_scope():
    """A dangling cite in a scoped file would be reported; a history-worded one would not."""
    tracked = _tracked()
    bare = "Run `python agents/agent9_gone/run.py` nightly.\n"
    assert scan_source(bare, tracked) == [(1, "agents/agent9_gone/run.py")]
    history = "The script `agents/agent9_gone/run.py` was removed in 2026.\n"
    assert scan_source(history, tracked) == []
