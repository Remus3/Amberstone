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

    def test_py_file_in_tests_is_not_watched(self):
        # s134: RC never imports tests/; 9 of the 18 in-match restarts of TFT
        # match 20261025-070350 were test-file edits (RESTART_DIAG.md).
        assert not _should_watch("tests/test_example.py")

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
            assert "tests/test_thing.py" not in rels
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
    # s134: RC never imports tests/ or the gitignored lane driver files under
    # ops/loop/control/ - the two trees behind 16 of the 18 in-match restarts.
    "tests/unit/sub/z.py",
    "ops/loop/control/lane_prompts/s134_lane_driver.py",
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
    "tests",
    "ops/loop/control",
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
        if isinstance(path, int):
            # POSIX shutil.rmtree (pytest's tmp_path cleanup) scans by file
            # descriptor; an fd is not a directory path and os.fspath raises.
            return real_scandir(path, *args, **kwargs)
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


# ---------------------------------------------------------------------------
# s134: watch only what RC loads, defer while a game is live, log every act.
#
# Measured incident (ops/runtime/tft_qa/RESTART_DIAG.md): 18 RC restarts in
# one TFT match, every one caused by an edit to a file the RC process never
# imports - tests/*, agents/agent1_lead/*, agents/agent3_testing/* and the
# gitignored ops/loop/control/lane_prompts/s134_lane_*.py. Each restart drops
# live TFT state. The watcher logged nothing, so the evidence self-erased.
# ---------------------------------------------------------------------------

import logging  # noqa: E402
import sys  # noqa: E402
import types  # noqa: E402

import core.hot_reload as hr  # noqa: E402

# The incident's edited files, repo-relative, one per distinct tree.
_INCIDENT_FILES = (
    "tests/test_progress_reaper_rm816.py",
    "tests/test_tft_set_resolver.py",
    "agents/agent1_lead/scheduler.py",
    "agents/agent3_testing/suite/test_scheduler_queue_lock.py",
    "ops/loop/control/lane_prompts/s134_lane_driver.py",
    "ops/loop/control/lane_prompts/s134_lane_progress.py",
)

# Files the RC process does load in the fixture below.
_RC_LOADED = (
    "core/live.py",
    "dashboard/routes_x.py",
    "agents/daemon_slayer/dps.py",
    "ops/loop/lanes.py",
    "web_dashboard.py",
)

_LOG = "rc.hot_reload"


def _tree(root: Path) -> Path:
    for rel in _INCIDENT_FILES + _RC_LOADED + ("agents/daemon_slayer/server.py",):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("X = 1\n", encoding="utf-8")
    (root / "ops" / "runtime").mkdir(parents=True, exist_ok=True)
    return root


def _touch(root: Path, rel: str, text: str = "X = 2\n") -> None:
    """Rewrite rel and push its mtime well past the 0.5 s buffer."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    before = p.stat().st_mtime if p.exists() else time.time()
    p.write_text(text, encoding="utf-8")
    t = before + 10.0
    os.utime(p, (t, t))


class _Game:
    """Settable in-game verdict: None = no game, a string = the reason."""

    def __init__(self, reason=None):
        self.reason = reason
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.reason


def _watcher(root: Path, loaded=_RC_LOADED, game=None):
    return hr.HotReloadWatcher(
        root,
        status_path=root / "ops" / "runtime" / "hot_reload.json",
        loaded=lambda: frozenset(loaded),
        game=game if game is not None else _Game(),
    )


def _records(caplog, needle: str) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == _LOG and needle in r.getMessage()]


class TestWatchScopeIsWhatRcLoads:
    """Path filter: tests/ and ops/loop/control/ are never candidates."""

    @pytest.mark.parametrize("rel", [
        "tests/test_progress_reaper_rm816.py",
        "tests/unit/deep/test_x.py",
        # RM-699: a tests directory at ANY depth.
        "agents/daemon_slayer/tests/test_x.py",
        "tools/tests/test_x.py",
        "ops/loop/control/lane_prompts/s134_lane_driver.py",
        ".claude/worktrees/agent-x/core/live.py",
        "ops/runtime/responder_export/abcdef123456/core/x.py",
    ])
    def test_never_a_candidate(self, rel):
        assert not _should_watch(rel)

    @pytest.mark.parametrize("rel", [
        # RC imports these lazily (dashboard/routes_loop_status.py _lanes,
        # importlib) - they stay candidates and are watched only if loaded.
        "ops/loop/lanes.py",
        "agents/daemon_slayer/dps.py",
        "core/live.py",
        # RM-699 acceptance: runtime siblings of the test trees stay.
        "agents/daemon_slayer/engine.py",
        "tools/edit_lint_check.py",
        "web_dashboard.py",
    ])
    def test_still_a_candidate(self, rel):
        assert _should_watch(rel)

    def test_loaded_repo_files_maps_modules_under_root_only(self, tmp_path):
        root = tmp_path / "repo"
        ns = types.SimpleNamespace
        mods = {
            "core.live": ns(__file__=str(root / "core" / "live.py")),
            "core.pkg": ns(__file__=str(root / "core" / "pkg" / "__init__.py")),
            "outside": ns(__file__=str(tmp_path / "other" / "x.py")),
            # Prefix trap: "repo2" starts with "repo" as a string.
            "sibling": ns(__file__=str(tmp_path / "repo2" / "core" / "b.py")),
            "namespace_pkg": ns(__file__=None),
            "builtin": ns(),
            "extension": ns(__file__=str(root / "core" / "fast.pyd")),
        }
        got = hr._loaded_repo_files(root, mods)
        assert got == {"core/live.py", "core/pkg/__init__.py"}

    def test_loaded_repo_files_default_reads_sys_modules(self):
        root = Path(hr.__file__).resolve().parent.parent
        got = hr._loaded_repo_files(root)
        # This very module and the module under test are loaded right now.
        assert "core/hot_reload.py" in got
        assert "tests/test_hot_reload.py" in got


class TestWatcherTriggers:

    def test_loaded_change_outside_game_triggers_and_logs(self, tmp_path, caplog):
        root = _tree(tmp_path)
        w = _watcher(root)
        _touch(root, "core/live.py")
        with caplog.at_level(logging.INFO, logger=_LOG):
            assert w.tick() == "triggered"
        assert (root / "restart_trigger.txt").read_text() == "auto-hot-reload"
        lines = _records(caplog, "core/live.py")
        assert len(lines) == 1 and "trigger" in lines[0]

    def test_incident_files_never_trigger_nor_defer(self, tmp_path, caplog):
        root = _tree(tmp_path)
        # Even a loaded-set that CLAIMS the tests/ and ops/loop/control/
        # files (a pytest process does load tests/*) must not make them
        # candidates: those two trees are excluded by path. The agents/
        # files are excluded because RC has not loaded them.
        hard = tuple(r for r in _INCIDENT_FILES if not r.startswith("agents/"))
        assert len(hard) == 4  # anchor: the claim is not vacuous
        game = _Game()
        w = _watcher(root, loaded=_RC_LOADED + hard, game=game)
        with caplog.at_level(logging.DEBUG, logger=_LOG):
            for in_game in (None, "process league of legends.exe"):
                game.reason = in_game
                for rel in _INCIDENT_FILES:
                    _touch(root, rel)
                    assert w.tick() in ("idle", "ignored"), rel
        assert not (root / "restart_trigger.txt").exists()
        assert _records(caplog, "deferred") == []
        assert _records(caplog, "triggered") == []

    def test_unloaded_ds_module_does_not_trigger(self, tmp_path):
        # agents/daemon_slayer/server.py runs in the separate :8860 process;
        # RC has not loaded it, so an edit there is not RC's to reload.
        root = _tree(tmp_path)
        w = _watcher(root)
        _touch(root, "agents/daemon_slayer/server.py")
        assert w.tick() == "ignored"
        assert not (root / "restart_trigger.txt").exists()

    def test_loaded_ds_module_still_triggers(self, tmp_path):
        root = _tree(tmp_path)
        w = _watcher(root)
        _touch(root, "agents/daemon_slayer/dps.py")
        assert w.tick() == "triggered"

    def test_new_unloaded_file_does_not_trigger(self, tmp_path):
        root = _tree(tmp_path)
        w = _watcher(root)
        _touch(root, "core/brand_new_module.py")
        assert w.tick() == "ignored"
        assert not (root / "restart_trigger.txt").exists()

    def test_no_change_is_idle(self, tmp_path):
        root = _tree(tmp_path)
        w = _watcher(root)
        assert w.tick() == "idle"
        assert not (root / "restart_trigger.txt").exists()

    def test_game_check_not_consulted_without_a_loaded_change(self, tmp_path):
        root = _tree(tmp_path)
        game = _Game()
        w = _watcher(root, game=game)
        w.tick()
        _touch(root, "tests/test_tft_set_resolver.py")
        w.tick()
        assert game.calls == 0


class TestWatcherDefersDuringGame:

    def test_deferred_then_fires_once_after_game(self, tmp_path, caplog):
        root = _tree(tmp_path)
        trig = root / "restart_trigger.txt"
        game = _Game("process tftclient-win64-shipping.exe")
        w = _watcher(root, game=game)
        with caplog.at_level(logging.INFO, logger=_LOG):
            _touch(root, "core/live.py")
            assert w.tick() == "deferred"
            assert not trig.exists()
            # Still in game, nothing new: stays pending, no new log line.
            assert w.tick() == "deferred"
            _touch(root, "dashboard/routes_x.py")
            assert w.tick() == "deferred"
            assert not trig.exists()
            deferrals = _records(caplog, "deferred")
            assert len(deferrals) == 2, deferrals
            assert "core/live.py" in deferrals[0]
            assert "tftclient-win64-shipping.exe" in deferrals[0]
            assert "dashboard/routes_x.py" in deferrals[1]
            assert "core/live.py" not in deferrals[1]

            game.reason = None
            assert w.tick() == "triggered"
            assert trig.read_text() == "auto-hot-reload"
            fired = _records(caplog, "triggered")
            assert len(fired) == 1
            assert "core/live.py" in fired[0]
            assert "dashboard/routes_x.py" in fired[0]

            trig.unlink()
            assert w.tick() == "idle"
            assert not trig.exists()

    def test_status_file_shows_pending_while_deferred(self, tmp_path):
        import json
        root = _tree(tmp_path)
        w = _watcher(root, game=_Game("lcu phase InProgress"))
        _touch(root, "core/live.py")
        w.tick()
        doc = json.loads((root / "ops" / "runtime" / "hot_reload.json")
                         .read_text(encoding="utf-8"))
        assert doc["pending"] == ["core/live.py"]
        assert doc["deferred_reason"] == "lcu phase InProgress"

    def test_broken_pending_file_blocks_the_deferred_trigger(self, tmp_path, caplog):
        root = _tree(tmp_path)
        game = _Game("process league of legends.exe")
        w = _watcher(root, game=game)
        _touch(root, "core/live.py", "def broken(:\n")
        assert w.tick() == "deferred"
        game.reason = None
        with caplog.at_level(logging.INFO, logger=_LOG):
            assert w.tick() == "compile_failed"
        assert not (root / "restart_trigger.txt").exists()
        assert any("core/live.py" in m for m in _records(caplog, "py_compile"))
        # Pending is cleared: the next fix edit triggers on its own.
        assert w.tick() == "idle"


class TestGameActivity:

    def _ga(self, names=(), phase=None, clock=None, counter=None):
        def _names():
            if counter is not None:
                counter["procs"] += 1
            return frozenset(names)

        def _phase():
            if counter is not None:
                counter["lcu"] += 1
            return phase
        return hr.GameActivity(process_names=_names, lcu_phase=_phase,
                               clock=clock or (lambda: 0.0))

    @pytest.mark.parametrize("proc", [
        "League of Legends.exe", "league of legends.exe",
        "TFTClient-Win64-Shipping.exe",
    ])
    def test_game_process_means_in_game(self, proc):
        reason = self._ga(names={"explorer.exe", proc}).check()
        assert reason and proc.lower() in reason.lower()

    @pytest.mark.parametrize("phase", ["InProgress", "GameStart", "Reconnect"])
    def test_live_lcu_phase_means_in_game(self, phase):
        assert phase in (self._ga(phase=phase).check() or "")

    @pytest.mark.parametrize("phase", [
        None, "", "Lobby", "ChampSelect", "WaitingForStats", "PreEndOfGame",
        "EndOfGame", "None",
    ])
    def test_out_of_game(self, phase):
        assert self._ga(names={"explorer.exe"}, phase=phase).check() is None

    def test_process_check_cached_for_ten_seconds(self):
        now = {"t": 100.0}
        counter = {"procs": 0, "lcu": 0}
        ga = self._ga(names={"chrome.exe"}, clock=lambda: now["t"],
                      counter=counter)
        ga.check()
        now["t"] = 105.0
        ga.check()
        assert counter["procs"] == 1
        now["t"] = 110.5
        ga.check()
        assert counter["procs"] == 2
        assert hr.PROCESS_CACHE_S == 10.0

    def test_lcu_not_asked_when_game_process_running(self):
        counter = {"procs": 0, "lcu": 0}
        ga = self._ga(names={"League of Legends.exe"}, phase="InProgress",
                      counter=counter)
        assert ga.check()
        assert counter["lcu"] == 0

    def test_check_never_raises(self):
        def _boom():
            raise RuntimeError("probe failed")
        ga = hr.GameActivity(process_names=_boom, lcu_phase=_boom,
                             clock=lambda: 0.0)
        assert ga.check() is None

    def test_default_process_names_reads_psutil_lower_cased(self, monkeypatch):
        # A fake psutil, never the live process table: a suite run while the
        # operator plays must not see the real game (same rule as conftest's
        # _no_live_standalone_tft).
        class _Proc:
            def __init__(self, name):
                self.info = {"name": name}

        class _Gone:
            @property
            def info(self):
                raise RuntimeError("process exited mid-scan")

        fake = types.ModuleType("psutil")
        fake.process_iter = lambda attrs=None: iter([
            _Proc("TFTClient-Win64-Shipping.exe"), _Proc(None), _Gone(),
            _Proc("Explorer.EXE"),
        ])
        monkeypatch.setitem(sys.modules, "psutil", fake)
        names = hr._default_process_names()
        assert names == frozenset({"tftclient-win64-shipping.exe",
                                   "explorer.exe"})

    def test_default_process_names_without_psutil_is_empty(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "psutil", None)  # import -> ImportError
        assert hr._default_process_names() == frozenset()

    def test_default_lcu_phase_reads_the_agent_snapshot(self, monkeypatch):
        import dashboard._liveclient as lc
        monkeypatch.setattr(lc, "lcu_summary", lambda: {"phase": "InProgress"})
        assert hr._default_lcu_phase() == "InProgress"
        monkeypatch.setattr(lc, "lcu_summary", lambda: {})
        assert hr._default_lcu_phase() is None
