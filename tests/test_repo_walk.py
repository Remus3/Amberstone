"""Guards for tests/_repo_walk.py - the shared repo-root enumeration helper.

The helper exists so root-walking guards stop hand-rolling divergent skip sets,
and its dominant failure mode is silence: an enumeration that returns nothing
makes every consuming guard pass, and looks exactly like a clean repo. Most of
what is asserted here is therefore anti-vacuity, not feature coverage.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import pytest

from tests import _repo_walk as rw


def _record_scandir(monkeypatch, sink: list[str]) -> None:
    """Route every os.scandir call through ``sink`` (directory argument).

    Both the pathlib globber (``glob.py`` ``with os.scandir(path)``) and
    ``os.walk`` (``os.py`` ``scandir(top)``) look the name up on the ``os``
    module at CALL time, so patching the attribute intercepts either walk
    mechanism. The tests below still assert the walk ROOT was recorded, so a
    future mechanism that binds ``scandir`` early cannot make the "no excluded
    directory was entered" assertion pass vacuously.
    """
    real = os.scandir

    def hook(path=".", *args, **kwargs):
        if isinstance(path, int):
            # POSIX shutil.rmtree (pytest's tmp_path cleanup) scans by file
            # descriptor; an fd is not a directory path and os.fspath raises.
            return real(path, *args, **kwargs)
        raw = os.fspath(path)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        sink.append(raw)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", hook)


def _rel_dirs(recorded: list[str], base: Path) -> list[str]:
    """Recorded scandir directories re-expressed forward-slash relative to base."""
    prefix = str(base)
    out = []
    for raw in recorded:
        if raw == prefix:
            out.append("")
        elif raw.startswith(prefix + os.sep) or raw.startswith(prefix + "/"):
            out.append(raw[len(prefix) + 1:].replace("\\", "/"))
        else:
            out.append(raw.replace("\\", "/"))
    return out


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


def test_css_and_html_patterns_select_something():
    """ROADMAP NOW-3: the walker is the ADR-015 route for ASCII hygiene over
    stylesheets and pages, so prove it reaches them before a guard leans on it.

    Until 2026-09-20 every one of this module's seventeen consumers asked for
    `*.py` (or `*.py` plus `*.js`) and nothing asked for `*.css` or `*.html`,
    so this pattern pair had never been exercised here.
    `tests/test_css_html_ascii_hygiene.py` is the consumer.
    """
    css = rw.repo_files(patterns=("*.css",))
    html = rw.repo_files(patterns=("*.html",))
    assert len(css) > 40, f"only {len(css)} tracked .css - the sweep went vacuous"
    assert len(html) > 5, f"only {len(html)} tracked .html - the sweep went vacuous"
    assert all(p.suffix == ".css" for p in css)
    assert all(p.suffix == ".html" for p in html)
    # Both trees that carry them, not just `web/`.
    rel = {rw.relative_posix(p) for p in css + html}
    assert "web/css/dashboard.css" in rel
    assert "lane-widget/src/renderer/index.html" in rel


def test_self_check_passes_on_the_real_checkout():
    rw.self_check()


def test_self_check_raises_on_a_vacuous_tree(tmp_path):
    """The anti-vacuity guard must actually fire, not just exist."""
    (tmp_path / "lonely.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="collapsed|missing anchor"):
        rw.self_check(tmp_path)


# ---------------------------------------------------------------------------
# Pruning: the walker must never DESCEND an excluded tree, not merely filter
# its hits out afterwards. Measured 2026-09-19 on Legion: the rglob-then-filter
# shape made one iter_repo_files() cost 22500 os.scandir calls and 5.08 s for
# 2479 files, 16760 of those calls inside .claude/worktrees and 1008 inside
# ops/runtime/responder_export - trees whose every hit the filter then threw
# away. Sixteen guards pay that per call.
# ---------------------------------------------------------------------------

_LIVE_FORBIDDEN_PREFIXES = (".claude", "ops/runtime", "moon_sync_inbox")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")


def test_fallback_walk_prunes_excluded_trees_at_directory_level(
        tmp_path, monkeypatch):
    """No git (tracked set None): excluded directories are never entered.

    The decoys sit two or more levels under the excluded segment, so a
    file-level post-filter passes the RESULT assertion while still paying the
    descent; the scandir record is what distinguishes pruning from filtering.
    """
    base = tmp_path.resolve()
    legit = {"top.py", "core/a.py", "tests/b.py", "ops/runtime/keep.py"}
    for rel in legit:
        _touch(base / rel)
    _touch(base / "README.md")  # wrong pattern, must not be yielded
    decoys = (
        ".claude/worktrees/agent-x/core/z.py",
        ".claude/worktrees/agent-x/tests/deep/er/z.py",
        "ops/runtime/responder_export/abcdef123456/core/z.py",
        "ops/runtime/responder_export/abcdef123456/tests/z.py",
    )
    for rel in decoys:
        _touch(base / rel)

    # Force the git-absent branch regardless of where tmp_path lives.
    monkeypatch.setattr(rw, "tracked_relpaths", lambda root="": None)

    recorded: list[str] = []
    _record_scandir(monkeypatch, recorded)
    got = list(rw.iter_repo_files(base, ("*.py",)))
    dirs = _rel_dirs(recorded, base)

    assert "" in dirs, "os.scandir hook never saw the walk root - not intercepting"
    entered = sorted(
        d for d in dirs
        if d.startswith(".claude") or d.startswith("ops/runtime/responder_export")
    )
    assert not entered, f"walker descended excluded trees: {entered}"
    assert all(isinstance(p, Path) and p.is_absolute() for p in got)
    assert {p.relative_to(base).as_posix() for p in got} == legit
    assert got == sorted(got), "ordering is no longer sorted"


def test_live_walk_never_enters_scratch_trees(monkeypatch):
    """On the real checkout, neither walk path enters a scratch tree.

    Tracked path: no scandir call under .claude / ops/runtime /
    moon_sync_inbox (the index is the candidate list, so the honest count is
    zero calls anywhere - asserted as a bound, not just a prefix check).
    Fallback path: no call under any EXCLUDED segment, and it must have
    recorded the repo root so the hook is proven to intercept. ``ops/runtime``
    ITSELF is legitimately entered there: ``runtime`` is not an EXCLUDED_DIRS
    segment (ADR-015 names ``responder_export`` as the entry, nothing wider),
    and the ``tracked_only=False`` arm exists so a guard's net-new-site control
    can see UNTRACKED files - ``git ls-files ops/runtime`` is empty (measured
    2026-09-19), so a walk that skipped the directory would change that arm's
    output, not merely its cost. Both anchored at >= 1000 files.
    """
    base = rw.REPO_ROOT.resolve()
    recorded: list[str] = []
    _record_scandir(monkeypatch, recorded)
    tracked_files = list(rw.iter_repo_files())
    n_tracked_calls = len(recorded)
    fallback_files = list(rw.iter_repo_files(tracked_only=False))
    dirs = _rel_dirs(recorded, base)
    tracked_dirs = dirs[:n_tracked_calls]
    fallback_dirs = dirs[n_tracked_calls:]

    assert len(tracked_files) >= 1000, len(tracked_files)
    assert len(fallback_files) >= 1000, len(fallback_files)

    entered = sorted(
        d for d in tracked_dirs
        if any(d.startswith(p) for p in _LIVE_FORBIDDEN_PREFIXES)
    )
    assert not entered, (
        f"tracked path made {len(entered)} scandir calls inside scratch trees "
        f"(of {n_tracked_calls} total); first: {entered[:5]}")
    assert n_tracked_calls < len(tracked_files), (
        f"tracked path enumerated {n_tracked_calls} directories for "
        f"{len(tracked_files)} files - it is walking the disk again")

    assert "" in fallback_dirs, (
        "fallback walk never scandir'd the repo root - hook not intercepting")
    entered = sorted(
        d for d in fallback_dirs
        if any(seg in rw.EXCLUDED_DIRS for seg in d.strip("/").split("/"))
    )
    assert not entered, (
        f"fallback path made {len(entered)} scandir calls inside excluded "
        f"trees (of {len(fallback_dirs)} total); first: {entered[:5]}")


def test_index_path_equals_tracked_and_on_disk_and_not_excluded():
    """Equivalence self-check: the tracked path yields exactly the index
    entries that match the pattern, are not excluded, and exist as files.
    """
    base = rw.REPO_ROOT.resolve()
    tracked = rw.tracked_relpaths(str(base))
    assert tracked is not None, "git index unreadable in the checkout"
    expected = {
        p for p in tracked
        if fnmatch.fnmatch(p.rsplit("/", 1)[-1], "*.py")
        and not rw.is_excluded(p)
        and (base / p).is_file()
    }
    got = {rw.relative_posix(p, base) for p in rw.iter_repo_files(base, ("*.py",))}
    assert len(got) >= 1000, len(got)
    assert got == expected, (
        f"missing={sorted(expected - got)[:5]} extra={sorted(got - expected)[:5]}")


@pytest.mark.parametrize("pattern", ["core/*.py", "**/*.py", "tests\\test_*.py"])
def test_non_basename_pattern_is_rejected_loudly(pattern):
    """A directory component or `**` cannot match a basename, so it would
    yield an EMPTY walk that reads as clean. The module's contract is that
    empty is never clean, so the call must raise instead of returning nothing.
    """
    with pytest.raises(ValueError, match="basename globs only"):
        list(rw.iter_repo_files(rw.REPO_ROOT, (pattern,)))
