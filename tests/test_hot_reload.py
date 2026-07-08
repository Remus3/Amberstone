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

    def test_share_dir_skipped(self):
        assert not _should_watch("Share/src/agents/module.py")

    def test_data_dir_skipped(self):
        assert not _should_watch("data/something.py")

    def test_web_dir_skipped(self):
        assert not _should_watch("web/js/panel.js")

    def test_non_py_file_not_watched(self):
        assert not _should_watch("core/hot_reload.md")
        assert not _should_watch("core/hot_reload.txt")

    def test_archive_skipped(self):
        assert not _should_watch("docs/_archive/old_module.py")


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
