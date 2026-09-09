"""Guards for tests/_repo_walk.py - the shared repo-root enumeration helper.

The helper exists so root-walking guards stop hand-rolling divergent skip sets,
and its dominant failure mode is silence: an enumeration that returns nothing
makes every consuming guard pass, and looks exactly like a clean repo. Most of
what is asserted here is therefore anti-vacuity, not feature coverage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import _repo_walk as rw


def test_root_resolves_to_the_repo_checkout():
    assert (rw.REPO_ROOT / "CLAUDE.md").is_file()
    assert (rw.REPO_ROOT / "tests" / "_repo_walk.py").is_file()


def test_excluded_dirs_covers_the_measured_contaminators():
    """The four trees that actually nest inside this checkout.

    `.claude` (worktree convention + `moon_sync_inbox/from-CS-verbatim/.claude`),
    `python-embed` (1842 untracked .py), `moon_sync_inbox` (51 untracked .py,
    gitignored sibling mail) and `_archive` (dated artifacts). Measured
    2026-09-07; each was missing from at least one guard's hand-rolled set.
    """
    # `responder_export` added 2026-09-09 (RM-394): the inbox responder writes
    # a full COPY OF THE REPO under ops/runtime/responder_export/<sha>/, which
    # made five root-walking guards red on Legion and green in CI. The tracked
    # set already removes it; this entry is the fallback path, and it is pinned
    # HERE so it cannot be dropped silently - a gate pass found it was
    # otherwise held only indirectly, by another guard's synthetic fixture.
    for name in (".claude", "worktrees", "python-embed", "moon_sync_inbox",
                 "_archive", ".git", "node_modules", "__pycache__", ".venv",
                 "responder_export"):
        assert name in rw.EXCLUDED_DIRS, f"{name} dropped from EXCLUDED_DIRS"


def test_is_excluded_matches_segments_not_substrings():
    assert rw.is_excluded("docs/_archive/2026-05-16/x.py")
    assert rw.is_excluded(".claude/worktrees/abc/core/x.py")
    assert rw.is_excluded(Path("python-embed") / "Lib" / "os.py")
    # A segment that merely CONTAINS an excluded name is not excluded.
    assert not rw.is_excluded("core/build_order.py")
    assert not rw.is_excluded("tools/_archive_helper.py")
    assert not rw.is_excluded("docs/archive_notes.py")


def test_tracked_relpaths_is_populated_and_never_empty_on_success():
    tracked = rw.tracked_relpaths(str(rw.REPO_ROOT))
    assert tracked is not None, "git ls-files failed in the repo checkout"
    assert len(tracked) > 1000, f"suspiciously small git index: {len(tracked)}"
    assert "CLAUDE.md" in tracked
    assert "core/build_order.py" in tracked


def test_tracked_relpaths_returns_none_not_empty_outside_a_repo(tmp_path):
    """A git failure must be distinguishable from "nothing is tracked".

    An empty frozenset would filter every candidate out and present as a clean
    tree; `None` makes the caller fall back to the directory skips instead.
    """
    result = rw.tracked_relpaths(str(tmp_path))
    assert result is None or len(result) > 0


def test_enumeration_reaches_real_files():
    files = rw.repo_files()
    assert len(files) > 1000, f"only {len(files)} .py enumerated"
    rel = {rw.relative_posix(p) for p in files}
    assert "web_dashboard.py" in rel
    assert "core/build_order.py" in rel
    assert "tests/conftest.py" in rel


def test_enumeration_excludes_the_vendored_trees():
    rel = {rw.relative_posix(p) for p in rw.repo_files()}
    for prefix in ("python-embed/", "moon_sync_inbox/", ".claude/",
                   "docs/_archive/", "_scratch/"):
        offenders = sorted(r for r in rel if r.startswith(prefix))
        assert not offenders, f"{prefix} leaked into the walk: {offenders[:3]}"


def test_directory_skips_alone_hold_when_the_git_index_is_unavailable():
    """The backstop half: with tracked_only off, the vendored trees stay out.

    This is what keeps the walker sane if `git ls-files` ever fails - the point
    of carrying EXCLUDED_DIRS at all rather than leaning entirely on the index.
    """
    rel = {rw.relative_posix(p) for p in rw.repo_files(tracked_only=False)}
    assert len(rel) > 1000
    for prefix in ("python-embed/", "moon_sync_inbox/", ".claude/"):
        assert not [r for r in rel if r.startswith(prefix)], prefix


def test_multiple_patterns_do_not_duplicate():
    both = rw.repo_files(patterns=("*.py", "*.py"))
    once = rw.repo_files(patterns=("*.py",))
    assert both == once


def test_js_pattern_selects_something():
    js = rw.repo_files(patterns=("*.js",))
    assert len(js) > 20, f"only {len(js)} tracked .js - the sweep went vacuous"
    assert all(p.suffix == ".js" for p in js)


def test_self_check_passes_on_the_real_checkout():
    rw.self_check()


def test_self_check_raises_on_a_vacuous_tree(tmp_path):
    """The anti-vacuity guard must actually fire, not just exist."""
    (tmp_path / "lonely.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="collapsed|missing anchor"):
        rw.self_check(tmp_path)
