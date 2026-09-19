"""Tests for core/hot_reload.py - watchdog file scanning + freeze rules."""

import os
import tempfile
import time
from collections import Counter
from pathlib import Path

import pytest

from core.hot_reload import _should_watch, _is_frozen, _scan_py_files


class TestFrozenGuard:
    """_is_frozen() returns True exactly for CLAUDE.md frozen files."""

    def test_frozen_paths_are_frozen(self):
        assert _is_frozen("main.py")
        assert _is_frozen("core/log_setup.py")
        assert _is_frozen("core/moon_proxy.py")
        assert _is_frozen("app/__init__.py")
        assert _is_frozen("app/_loop.py")
        assert _is_frozen("ops/rc_supervisor.py")

    def test_non_frozen_paths_are_not_frozen(self):
        assert not _is_frozen("core/hot_reload.py")
        assert not _is_frozen("web_dashboard.py")
        assert not _is_frozen("tools/edit_lint_check.py")
        assert not _is_frozen("dashboard/server.py")

    def test_frozen_never_watched(self):
        for p in ["main.py", "core/log_setup.py", "app/__init__.py"]:
            assert not _should_watch(p), f"frozen file {p} should not be watched"


class TestShouldWatch:
    """_should_watch() gates on dir, suffix, and freeze status."""

    def test_py_file_in_core_is_watched(self):
        assert _should_watch("core/hot_reload.py")

    def test_py_file_in_dashboard_is_watched(self):
        assert _should_watch("dashboard/server.py")

    def test_py_file_in_agents_is_watched(self):
        assert _should_watch("agents/some_agent.py")

    def test_py_file_in_tools_is_watched(self):
        assert _should_watch("tools/edit_lint_check.py")

    def test_py_file_in_tests_is_watched(self):
        assert _should_watch("tests/test_example.py")

    def test_git_dir_skipped(self):
        assert not _should_watch(".git/objects/something.py")

    def test_pycache_skipped(self):
        assert not _should_watch("core/__pycache__/module.pyc")

    def test_logs_skipped(self):
        assert not _should_watch("logs/2026-01-01.log")

    def test_data_dir_skipped(self):
        assert not _should_watch("data/something.py")

    def test_web_dir_skipped(self):
        assert not _should_watch("web/js/panel.js")

    def test_non_py_file_not_watched(self):
        assert not _should_watch("core/hot_reload.md")
        assert not _should_watch("core/hot_reload.txt")

    def test_archive_skipped(self):
        assert not _should_watch("docs/_archive/old_module.py")


class TestSkipDirsAreSegmentAnchored:
    """_SKIP_DIRS entries are DIRECTORY names, so they must match on path
    SEGMENT boundaries - never as a raw substring of the whole path.

    The shipped test above only ever exercised the TOP-LEVEL shape of each
    skip dir ("data/something.py", "web/js/panel.js"), which is precisely why
    it could not see the defect: an unanchored `s in r` also drops any file
    whose path merely CONTAINS a token anywhere, including inside its own
    basename. Measured against this tree, that silently excluded 23 live
    non-frozen .py files - among them web_dashboard.py, the module that
    starts the watcher.

    Every path asserted watched below is a real file in this repo except the
    two basename probes at the end, which are representative shapes.
    """

    def test_data_token_inside_basename_is_watched(self):
        assert _should_watch("core/data_retention.py")
        assert _should_watch("core/coaching_data_lock.py")
        assert _should_watch("agents/daemon_slayer/data_loader.py")

    def test_web_token_inside_basename_is_watched(self):
        assert _should_watch("tools/web_ascii_sweep.py")
        assert _should_watch("web_dashboard.py")

    def test_basename_is_never_treated_as_a_directory_segment(self):
        # A skip token that appears only in the FILE name must not skip.
        assert _should_watch("core/webhook_client.py")
        assert _should_watch("tools/logs_rotate.py")

    def test_top_level_skip_dirs_still_skipped(self):
        # The behaviour the original test pinned must not regress.
        assert not _should_watch("data/x.py")
        assert not _should_watch("web/js/panel.js")
        assert not _should_watch("data/coaching/snapshot.py")

    def test_multi_segment_skip_entry_still_honoured(self):
        assert not _should_watch("docs/_archive/foo.py")

    def test_multi_segment_skip_entry_honoured_at_depth(self):
        assert not _should_watch("tools/docs/_archive/foo.py")

    def test_nested_skip_dir_skipped_at_any_depth(self):
        assert not _should_watch("core/build_planner/__pycache__/mod.py")
        assert not _should_watch("agents/daemon_slayer/data/mod.py")
        assert not _should_watch("tools/logs/rotated/old.py")

    def test_partial_segment_is_not_a_skip_dir(self):
        # "data" must not match the segment "database", nor "web" "webhooks".
        assert _should_watch("core/database/pool.py")
        assert _should_watch("tools/webhooks/send.py")


class TestScanPyFiles:
    """_scan_py_files returns {rel_path: mtime} for watchable .py files."""

    def test_scan_finds_py_files_in_temp_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Create a few python files in watchable dirs.
            (root / "core").mkdir()
            (root / "tools").mkdir()
            (root / "tests").mkdir()
            # Unwatchable dirs.
            (root / ".git").mkdir()
            (root / "__pycache__").mkdir()
            (root / "web").mkdir()

            (root / "core" / "test_module.py").write_text("# test")
            (root / "tools" / "tool.py").write_text("# tool")
            (root / "tests" / "test_thing.py").write_text("# test")
            # Should be skipped.
            (root / ".git" / "ignored.py").write_text("# git")
            (root / "__pycache__" / "cached.py").write_text("# cache")
            (root / "web" / "panel.js").write_text("// js")

            files = _scan_py_files(root)
            # Keys use forward-slashed relative paths.
            rels = set(files.keys())

            assert "core/test_module.py" in rels
            assert "tools/tool.py" in rels
            assert "tests/test_thing.py" in rels
            assert ".git/ignored.py" not in rels
            assert "__pycache__/cached.py" not in rels
            assert "web/panel.js" not in rels

    def test_scan_returns_floats(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "core").mkdir()
            (root / "core" / "mod.py").write_text("# test")
            files = _scan_py_files(root)
            # Keys are forward-slashed relative paths even on Windows.
            assert "core/mod.py" in files
            assert isinstance(files["core/mod.py"], float)
            assert files["core/mod.py"] > 0


# Files the scanner must return from the fixture tree below.
_LEGIT_FILES: frozenset[str] = frozenset({
    "core/a.py",
    "ops/loop/b.py",
    "tools/c.py",
    "root.py",
})

# Decoy files, each at least two directory levels deep inside a tree the
# scanner must never DESCEND (not merely filter out after enumerating).
# The first two are the measured live offenders: 40 agent worktrees under
# .claude/ (~197k files) and the gitignored responder_export copies of the
# whole repo under ops/runtime/ (~14k files), which together drove ~37,000
# filesystem metadata ops per second from the idle RC process.
_DECOY_FILES: frozenset[str] = frozenset({
    ".claude/worktrees/agent-x/core/z.py",
    "ops/runtime/responder_export/abcdef123456/core/z.py",
    ".git/hooks/sub/z.py",
    "data/coaching/sub/z.py",
    "web/js/panels/z.py",
    "moon_sync_inbox/sub/deep/z.py",
    "node_modules/pkg/lib/z.py",
    "docs/_archive/old/z.py",
})

# The directory at the top of each decoy tree - the exact directory the
# scanner must never enter. Declared, not derived from the first path
# segment: "ops/runtime/..." lives under the legitimate watch dir "ops".
_DECOY_TREES: frozenset[str] = frozenset({
    ".claude",
    "ops/runtime",
    ".git",
    "data",
    "web",
    "moon_sync_inbox",
    "node_modules",
    "docs/_archive",
})

# The ONLY directories a scan of the fixture tree may enumerate ("" is the
# repo root, listed non-recursively for root-level *.py). Every watch dir
# that does not exist in the fixture (agents, dashboard, tests) is absent
# on purpose: a missing watch dir must cost a stat, not an enumeration.
_ALLOWED_DIRS: frozenset[str] = frozenset({
    "",
    "core",
    "ops",
    "ops/loop",
    "tools",
})


def _build_fixture_tree(root: Path) -> None:
    for rel in _LEGIT_FILES | _DECOY_FILES:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# fixture", encoding="utf-8")


def _record_enumerated_dirs(monkeypatch, root: Path) -> list[str]:
    """Run _scan_py_files(root) with os.scandir instrumented.

    Returns every directory passed to os.scandir during the scan, as a
    root-relative posix path ("" for the root itself), in call order and
    WITH repeats, so a double walk is visible as a duplicate entry.

    Both walkers go through os.scandir on this interpreter: pathlib.rglob
    (the pre-fix walker, which visits each directory twice and passes a
    trailing separator) and os.walk (the pruning walker). Verified live on
    Python 3.14.4 before this test was written - the assertion below that
    the root itself was recorded is the in-test guard that the hook is
    still real and has not silently gone blind.
    """
    recorded: list[str] = []
    real_scandir = os.scandir
    root_norm = os.path.normcase(os.path.normpath(str(root)))

    def _wrapped(path=".", *args, **kwargs):
        p = os.path.normcase(os.path.normpath(os.fspath(path)))
        if p == root_norm or p.startswith(root_norm + os.sep):
            rel = os.path.relpath(p, root_norm)
            recorded.append("" if rel == "." else rel.replace("\\", "/"))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", _wrapped)
    _scan_py_files(root)
    monkeypatch.undo()
    assert "" in recorded, (
        "instrumentation went blind: os.scandir never saw the root; "
        "the walker no longer routes through os.scandir on this Python"
    )
    return recorded


class TestScanPrunesInsteadOfFiltering:
    """_scan_py_files must PRUNE skipped trees, never enumerate-then-filter.

    pathlib.rglob never prunes: it enumerates every directory under the
    start point and only then hands each result to _should_watch. On the
    live tree that meant descending .claude/worktrees (~197k files) and
    ops/runtime/responder_export (~14k files) every 2s poll. The fix is
    scoping - a walk that never enters a skipped directory - so these
    tests pin the ENUMERATED DIRECTORY SET, not a count and not a rate.
    """

    def test_enumerated_directory_set_is_exactly_the_allowed_set(
        self, monkeypatch,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _build_fixture_tree(root)
            recorded = _record_enumerated_dirs(monkeypatch, root)
            seen = set(recorded)

            # Anchor: an empty enumeration must NOT pass this test.
            assert seen, "scanner enumerated nothing at all"
            assert _ALLOWED_DIRS, "allowed set is empty - test is inert"

            # Every decoy file must sit inside a declared decoy tree, or the
            # descent assertion below could not see it.
            for f in _DECOY_FILES:
                assert any(f.startswith(t + "/") for t in _DECOY_TREES), f
            descended = sorted(
                d for d in seen
                if d and any(
                    d == t or d.startswith(t + "/") for t in _DECOY_TREES
                )
            )
            assert descended == [], (
                f"scanner DESCENDED into decoy trees: {descended}"
            )
            assert seen == _ALLOWED_DIRS, (
                f"unexpected enumeration: extra={sorted(seen - _ALLOWED_DIRS)} "
                f"missing={sorted(_ALLOWED_DIRS - seen)}"
            )

    def test_returned_files_are_exactly_the_legit_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _build_fixture_tree(root)
            got = set(_scan_py_files(root))
            assert got, "scanner returned no files"
            assert got == set(_LEGIT_FILES), (
                f"extra={sorted(got - _LEGIT_FILES)} "
                f"missing={sorted(_LEGIT_FILES - got)}"
            )

    def test_each_allowed_directory_is_enumerated_at_most_once(
        self, monkeypatch,
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _build_fixture_tree(root)
            recorded = _record_enumerated_dirs(monkeypatch, root)
            counts = Counter(recorded)
            assert counts, "scanner enumerated nothing at all"
            repeats = {d: n for d, n in counts.items() if n > 1}
            assert repeats == {}, (
                f"directories enumerated more than once per scan: {repeats}"
            )


class TestScanOpCount:
    """Pin the per-scan SYSCALL SHAPE, not just the enumerated path set.

    The round-1 pruning walker fixed the descent (the path-set tests above)
    but still issued one os.stat() per accepted file AFTER os.walk had
    already scandir'ed the directory and thrown the DirEntry away: measured
    live, 2,331 stats per 2s poll, and the idle process still sat at ~5,858
    metadata ops/sec. The path-set tests are blind to that residual because
    a stat is not an enumeration. These two tests pin the op count.

    Portability: on Windows a DirEntry carries st_mtime from the directory
    listing, so entry.stat(follow_symlinks=False) costs no syscall at all.
    On Linux (CI) it does its own lstat at the C level. On BOTH platforms it
    never calls the Python-level os.stat / os.lstat, so the zero-count
    assertion below holds everywhere. Path.stat() DOES route through
    os.stat (verified on Python 3.14.4 before this test was written), so a
    regression to pathlib per-file stats is visible here.
    """

    def test_scan_issues_no_per_file_stat_calls(self, monkeypatch):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _build_fixture_tree(root)
            calls: Counter = Counter()
            real_stat, real_lstat = os.stat, os.lstat

            def _stat(*args, **kwargs):
                calls["stat"] += 1
                return real_stat(*args, **kwargs)

            def _lstat(*args, **kwargs):
                calls["lstat"] += 1
                return real_lstat(*args, **kwargs)

            monkeypatch.setattr(os, "stat", _stat)
            monkeypatch.setattr(os, "lstat", _lstat)
            files = _scan_py_files(root)
            monkeypatch.undo()

            # Anchor: an empty tree (or a scanner that returns nothing)
            # would trivially issue zero stats. Require the real result.
            assert len(files) >= 4, f"scanner returned too few files: {files}"
            assert set(files) == set(_LEGIT_FILES), (
                f"extra={sorted(set(files) - _LEGIT_FILES)} "
                f"missing={sorted(_LEGIT_FILES - set(files))}"
            )
            assert all(isinstance(m, float) and m > 0 for m in files.values())
            assert calls["stat"] + calls["lstat"] == 0, (
                f"scan issued Python-level stat calls: {dict(calls)} "
                f"for {len(files)} accepted files - the walker is throwing "
                "away the DirEntry and re-statting each file"
            )

    def test_scan_scandir_calls_equal_allowed_dir_count(self, monkeypatch):
        """Exactly one os.scandir per allowed directory - no more, no less.

        The "at most once" test above tolerates FEWER calls, so a walker
        that enumerated the root twice but skipped a subdir, or a pathlib
        walker that hid its listing behind a different primitive, could
        slip past it. Pin the exact count against the declared set.
        """
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            _build_fixture_tree(root)
            recorded = _record_enumerated_dirs(monkeypatch, root)
            assert _ALLOWED_DIRS, "allowed set is empty - test is inert"
            assert len(recorded) == len(_ALLOWED_DIRS), (
                f"expected exactly {len(_ALLOWED_DIRS)} os.scandir calls "
                f"(one per allowed dir), got {len(recorded)}: {recorded}"
            )
            assert set(recorded) == _ALLOWED_DIRS


class TestResponderExportCopiesAreNotWatched:
    """ops/runtime/ holds gitignored responder_export/<sha12>/ copies of the
    whole repo. Their .py files must never enter the watched set: an edit
    inside a copy would restart RC, and the live watched set measured ~3x
    the real tree (hot_reload.json file_count 7105 vs 4772 .py files under
    responder_export alone).
    """

    @pytest.mark.parametrize("rel", [
        "ops/runtime/responder_export/abcdef123456/core/x.py",
        "ops/runtime/hot_reload_probe.py",
    ])
    def test_should_watch_rejects_ops_runtime(self, rel):
        assert not _should_watch(rel)

    def test_scan_excludes_responder_export_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            copy = root / "ops" / "runtime" / "responder_export" / "abcdef123456"
            (copy / "core").mkdir(parents=True)
            (copy / "core" / "x.py").write_text("# copy", encoding="utf-8")
            (root / "ops" / "loop").mkdir(parents=True)
            (root / "ops" / "loop" / "real.py").write_text("# real", encoding="utf-8")
            got = set(_scan_py_files(root))
            assert "ops/loop/real.py" in got  # anchor: the walk did run
            assert (
                "ops/runtime/responder_export/abcdef123456/core/x.py" not in got
            )
