"""Tests for core/hot_reload.py - watchdog file scanning + freeze rules."""

import tempfile
import time
from pathlib import Path

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
