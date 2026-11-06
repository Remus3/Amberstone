"""RM-1732 - four prose claims that had gone stale are corrected, and the checkable ones are pinned.

BACKLOG's "REFRESHED 2026-10-24 (s133 research lane cycle 1)" row listed these as queue-ready Tier-0 docs rows;
each was re-read at HEAD on 2026-11-06 before the edit:

- ``core/provider_cascade.py`` and ``core/pro_match_index.py`` have no runtime importer (a substring search of every
  tracked non-test ``.py``), and neither docstring said so. Each carries an "Unwired:" line now. The claim is a
  statement about the import graph, so it is re-derived here: wiring either module fails the test until the
  docstring line is dropped.
- ``config/CONFIG_AUTHORITY.md`` opened with a "Phase 1 Step 1" banner from the phase plan it was written under.
- ``tools/perseus_sync.py`` named "the ``memory/*.md`` files" as a source of truth, though the repo has no
  ``memory/`` directory (its own source 2 is the Claude project memory directory).
- ``tests/test_next_session_desktop_write.py`` described the hand-off as a Desktop file; it is the tracked
  repo-root ``RC-NEXT-SESSION.txt`` since 2026-09-06.
"""
from __future__ import annotations

import ast

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_UNWIRED = {
    "core/provider_cascade.py": "provider_cascade",
    "core/pro_match_index.py": "pro_match_index",
}


def _tracked_py() -> dict[str, str]:
    out = {}
    for p in repo_files(REPO_ROOT, ("*.py",)):
        out[relative_posix(p)] = p.read_text(encoding="utf-8", errors="replace")
    assert len(out) > 100, "the tracked-file walk returned almost nothing"
    return out


def _is_test_code(rel: str) -> bool:
    return rel.startswith("tests/") or "/tests/" in rel


@pytest.mark.parametrize("rel,name", sorted(_UNWIRED.items()))
def test_the_unwired_claim_matches_the_import_graph(rel, name):
    files = _tracked_py()
    importers = sorted(r for r, src in files.items() if r != rel and name in src and not _is_test_code(r))
    doc = ast.get_docstring(ast.parse(files[rel])) or ""
    claims_unwired = "Unwired: no runtime module imports this one" in doc
    if importers:
        assert not claims_unwired, f"{rel} is imported by {importers} but its docstring still says Unwired"
    else:
        assert claims_unwired, f"{rel} has no runtime importer and its docstring does not say so"


@pytest.mark.parametrize("rel,name", sorted(_UNWIRED.items()))
def test_probe_sees_the_test_importers(rel, name):
    """Positive control: the search finds the test files that DO import the module, so an empty runtime result
    is a real scan of a tree where the name is searchable."""
    files = _tracked_py()
    assert any(name in src for r, src in files.items() if r != rel and _is_test_code(r))


def test_config_authority_has_no_phase_banner():
    text = (REPO_ROOT / "config" / "CONFIG_AUTHORITY.md").read_text(encoding="utf-8")
    assert "Phase 1 Step 1" not in text
    assert text.startswith("# CONFIG_AUTHORITY.md\n")


def test_perseus_sync_names_no_nonexistent_memory_directory():
    src = (REPO_ROOT / "tools" / "perseus_sync.py").read_text(encoding="utf-8")
    assert "the\n`memory/*.md` files" not in src
    assert not (REPO_ROOT / "memory").exists(), "a repo memory/ directory exists now; re-read the docstring"


def test_desktop_write_test_docstring_names_the_repo_root_file():
    src = (REPO_ROOT / "tests" / "test_next_session_desktop_write.py").read_text(encoding="utf-8")
    head = " ".join(src.split('"""', 2)[1].split())
    assert not head.startswith("Every /done writes Desktop/")
    assert "to the repo root" in head
