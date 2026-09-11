"""Shared pytest fixtures for the RC test suite.

`reset_cs_retention_between_tests` - `dashboard._state_builder.build_state()`
holds a *process-global* last-champ_select across the fast no-draft
(ARAM / Mayhem / Arena) champ-select -> game transition (see
`dashboard/_cs_retention.py`). That persistence is correct in
production (the dashboard polls at 500ms and the view must survive the
transient loss) but it bleeds across `build_state()` test calls in a
single pytest process: a test that supplies a champ_select caches it,
then a later test expecting *no* champ_select gets the stale one
re-spliced. This autouse fixture resets the cache before every test so
isolation lives in exactly one place rather than scattered per-file
setUps. Lazy import keeps conftest collection dependency-free for
test runs that never touch the dashboard.

`redirect_shadow_paths_to_tmp` - the det-coach + HZ-C1/C2 shadow writers
default their jsonl target to a module-level `SHADOW_PATH` constant under
the repo's real data/ dir, and the dashboard state-builder calls them with
NO path argument. Any test that exercises `build_state()` therefore
appended junk rows (my_champion="Champ0", mode="client") to the PRODUCTION
shadow logs on every suite run (HZ-D4 root cause 2). Both writers read the
module global at call time (`target = path if path is not None else
SHADOW_PATH`), so monkeypatching the module attribute redirects every
default-path write to tmp_path. Explicit `path=` arguments (the normal
test seam) are unaffected. Modules that fail to import are skipped so
conftest collection stays dependency-free.
"""
from __future__ import annotations

import hashlib
import importlib
import logging
import os
import sys
import tempfile
import threading
import types
from pathlib import Path
from unittest import mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ===========================================================================
# RM-406 - IMPORT-TIME HERMETICITY
#
# Everything in this section runs when pytest IMPORTS this conftest, which is
# strictly before collection. A fixture cannot do this work, not even a
# session-scoped autouse one: both defects below are armed by a test module's
# IMPORT, and collection imports every test module in the worker before the
# first fixture runs. By the time a fixture executes, the logging handler is
# already attached to the live file and the watcher thread is already ticking.
#
# WHY THIS IS NOT PARANOIA - the census that produced this section was
# MEASURED on 2026-09-11 with `tools/live_write_tracer.py` over
# `pytest tests -n 8 --dist loadfile`, counting BYTES ACTUALLY WRITTEN and
# attributing each to the running nodeid. A before/after filesystem diff was
# deliberately NOT used: daemons and other sessions write these same trees
# concurrently on Legion, so a file that changes during a suite run attributes
# nothing to the suite.
# ===========================================================================

# One directory per worker PROCESS. `tmp_path_factory` does not exist at
# import time, and both pytest and the tracer already ignore the system temp
# tree, so plain `mkdtemp` is the right tool at this point in the lifecycle.
_SUITE_LOG_DIR = Path(tempfile.mkdtemp(prefix="rc-suite-logs-"))
_REAL_LOG_DIR = _REPO_ROOT / "logs"


def _tmp_log_path(filename):
    """Map a path under the repo's real `logs/` onto `_SUITE_LOG_DIR`.

    Anything NOT under the real log dir is returned byte-identical, so a test
    that hands a handler its own `tmp_path` keeps exactly the path it asked
    for and no assertion on that path can change meaning. That is the
    `ValueError` arm below and it is the only arm allowed to hand back the
    caller's own path.

    WHY `OSError` MUST NOT SHARE THAT ARM: `resolve()` can fail on Windows for
    a path the OS declines to canonicalise (a reserved device name, a bad
    reparse point, a dead network root). Returning `filename` there returns
    the LIVE path, so the handler opens the operator's real `logs/` file and
    the redirect becomes a silent no-op - which reinstates the exact defect
    this whole patch exists to prevent, with nothing anywhere reporting it.
    An undecidable path is therefore routed INTO tmp, never back out to the
    live tree: a stray file in a throwaway directory costs nothing, a stray
    append to the operator's log is the bug.
    """
    try:
        candidate = Path(filename)
    except TypeError:  # a file descriptor or an exotic path-like
        return filename
    try:
        resolved = candidate.resolve()
    except OSError:
        # Lexical absolutisation: no filesystem access, so it cannot raise the
        # way `resolve()` just did, and it still answers "under logs/?" for
        # every path that is not reached through a symlink.
        try:
            resolved = Path(os.path.abspath(str(candidate)))
        except (OSError, ValueError):
            digest = hashlib.sha256(
                str(filename).encode("utf-8", "replace")).hexdigest()[:16]
            return str(_SUITE_LOG_DIR / f"unresolvable-{digest}.log")
    try:
        rel = resolved.relative_to(_REAL_LOG_DIR)
    except ValueError:  # not under logs/ - hand back exactly what was asked for
        return filename
    out = _SUITE_LOG_DIR / rel
    out.parent.mkdir(parents=True, exist_ok=True)
    return str(out)


_orig_file_handler_init = logging.FileHandler.__init__


def _hermetic_file_handler_init(self, filename, *args, **kwargs):
    """Every file-logging handler the suite builds lands in tmp, not `logs/`.

    ROOT CAUSE, and why the fix is here rather than in one module:
    `agents/_supervisor_common.py:224` runs `log = _build_logger()` at IMPORT,
    and `_build_logger` (:197) attaches its RotatingFileHandler to BOTH the
    "supervisor" logger and the "rc" logger. Every RC module logs under
    `rc.*`, so the instant any test imports anything that reaches
    `agents._supervisor_common`, the whole worker's `rc.*` traffic is teed
    into the operator's live `logs/agents/supervisor.log`. MEASURED: 182940
    bytes across 850 distinct tests in one run - by a wide margin the largest
    single leak in the census, and NOT attributable to any of those 850 tests,
    which is exactly why a per-test fix was never going to find it.

    Patching the class constructor rather than that one module is deliberate.
    `_build_logger` early-returns when `lg.handlers` is truthy, so a redirect
    that arrives after the logger is built does nothing at all; and six other
    live logs (phase_watcher, lcu_agent, liveclient_relay, data_pipeline,
    daemon_slayer_extract, hotkey_listener) were opened by the same run
    through the same mechanism in their own modules. One constructor covers
    every one of them, plus the module that has not been written yet.
    `logging.handlers.RotatingFileHandler` and the Timed/Watched variants all
    funnel through `logging.FileHandler.__init__`, so rotation targets move
    with the base file.

    What this CANNOT catch: a module that writes a log with plain file I/O
    instead of the logging package (`tools/cost_health_watchdog.py:363` does
    exactly that - see `redirect_spec_loaded_tool_logs_to_tmp`), a handler
    constructed before this conftest is imported (swept below), and anything
    written by a SUBPROCESS, which has its own interpreter and never sees
    this patch.
    """
    return _orig_file_handler_init(self, _tmp_log_path(filename), *args, **kwargs)


logging.FileHandler.__init__ = _hermetic_file_handler_init


def _repoint_existing_live_log_handlers():
    """Relocate handlers that were built BEFORE this module was imported.

    The constructor patch above only governs handlers created from here on.
    The repo-root `conftest.py` and any `-p` plugin are imported first, so a
    handler on the live tree can already exist by now. Replacing the handler
    object (rather than mutating `baseFilename` and reopening the stream) is
    the conservative move: the stream lifecycle stays entirely inside the
    logging package. One replacement per ORIGINAL handler, because
    `_build_logger` shares a single handler instance between two loggers and
    swapping per-logger would leave the second one pointed at the live file.
    """
    replacements = {}
    loggers = [logging.getLogger()]
    loggers += [lg for lg in logging.Logger.manager.loggerDict.values()
                if isinstance(lg, logging.Logger)]
    for lg in loggers:
        for handler in list(lg.handlers):
            base = getattr(handler, "baseFilename", None)
            if not base:
                continue
            moved = _tmp_log_path(base)
            if moved == base:
                continue
            repl = replacements.get(id(handler))
            if repl is None:
                repl = logging.FileHandler(moved, encoding="utf-8", delay=True)
                repl.setFormatter(handler.formatter)
                repl.setLevel(handler.level)
                replacements[id(handler)] = repl
            lg.removeHandler(handler)
            lg.addHandler(repl)
    # The originals are intentionally NOT closed. Another logger this sweep
    # has not reached yet may still hold the same object, and a closed handler
    # raises on its next emit; an orphaned open file descriptor on a log
    # nobody writes to is the cheaper of the two failure modes.


_repoint_existing_live_log_handlers()


def _disabled_hot_reload_watcher(project_root):
    """Stand-in for `core.hot_reload.start_watcher` - starts nothing.

    THE MOST DAMAGING ROW IN THE CENSUS, and the one that is not about bytes.
    `web_dashboard.py:58-61` calls `start_watcher(_APP_DIR)` at MODULE level,
    inside a bare `try/except ImportError`. So merely importing
    `web_dashboard` - which several test modules do at collection - starts a
    daemon thread that polls every non-frozen `.py` in the repo every 2
    seconds and, on any change, writes `restart_trigger.txt`
    (`core/hot_reload.py:176`). That file is the supervisor's reload signal -
    writing it is how an operator asks for a restart - so the suite hands the
    live stack a restart request as a side effect. It fired for real during
    the 2026-09-11 baseline run: 15 bytes, credited to
    `tests/test_replay_build_order_validate.py::test_first_purchase_min_earliest`,
    which has nothing whatever to do with hot reload. The thread also wrote
    `ops/runtime/hot_reload.json` from two separate workers.

    Stated precisely, because the obvious stronger claim is not supported:
    the tracer proves the PYTEST process wrote the signal. It does NOT prove
    that write is the one a given supervisor restart consumed, and it cannot -
    the PRODUCTION watcher writes the same file whenever any non-frozen .py
    changes, so editing this very conftest also triggers one. Two plausible
    authors for one observed restart is exactly the attribution problem the
    in-process tracer exists to avoid; do not close the gap by assuming.

    Attribution is meaningless for a defect like this and that is the lesson:
    the writes land on whichever test happens to be running when the 2-second
    tick comes round, so every nodeid in the report is an innocent bystander
    and no amount of reading those three tests would ever have found the
    cause. Nothing joins the thread either, so it outlives the test that made
    it - the same shape as `_no_live_tft_ocr` below.

    A never-started Thread is returned rather than None because the real
    function's contract is to return one; a caller that stores it or checks
    `.is_alive()` keeps working.
    """
    return threading.Thread(target=lambda: None, daemon=True,
                            name="hot-reload-watcher-disabled")


try:
    from core import hot_reload as _hot_reload_mod
except Exception:  # noqa: BLE001 - keep conftest collection dependency-free
    _hot_reload_mod = None
else:
    _hot_reload_mod.start_watcher = _disabled_hot_reload_watcher


# Every `core.*_shadow` module that owns a module-global `SHADOW_PATH`,
# enumerated rather than sampled. Four of these were listed here before
# RM-406; the 2026-09-11 census caught four MORE appending to the live corpora
# (aram_coach 2946 bytes, objective_playbook 1260, macro_response 960,
# anvil 541), which is the signature of a hand-maintained list rather than a
# missing mechanism - the mechanism worked perfectly for the rows it knew
# about. The remaining five are listed for the same reason: a shadow writer
# that has not leaked YET differs from one that has only in which test got
# written first. Pinned by `tests/test_suite_does_not_write_live_tree.py`,
# which fails if `core/` grows a `SHADOW_PATH` this tuple does not carry.
_SHADOW_MODULES = (
    "core.anvil_shadow",
    "core.aram_coach_shadow",
    "core.arena_coach_shadow",
    "core.augment_shadow",
    "core.champ_select_shadow",
    "core.det_coach_shadow",
    "core.ds_coach_shadow",
    "core.hz_build_shadow",
    "core.hz_choice_shadow",
    "core.live_benchmark_band_shadow",
    "core.macro_response_shadow",
    "core.objective_playbook_shadow",
    "core.replay_narrative_shadow",
)


@pytest.fixture(autouse=True)
def reset_cs_retention_between_tests():
    try:
        from dashboard._cs_retention import reset_cs_retention
    except Exception:  # noqa: BLE001
        yield
        return
    reset_cs_retention()
    yield


@pytest.fixture(autouse=True)
def reset_lockfile_notice_between_tests():
    """`lcu/lockfile_notice.py` dedupes the LCU lockfile-missing notice across
    every client in the process, so its episode state is process-global for the
    same reason the cache above is: correct in production, cross-contaminating
    between tests. Without this, one test's open gap episode suppresses the
    next test's first notice and the failure reads as "no logs triggered"."""
    try:
        from lcu.lockfile_notice import current
    except Exception:  # noqa: BLE001
        yield
        return
    attached = current()
    if attached is not None:
        attached.reset()
    yield


@pytest.fixture(autouse=True)
def reset_idempotency_table_between_tests():
    """`dashboard/_idempotency.py` holds the operator-intent replay table in a
    process-global OrderedDict with a 900 s TTL, so a key remembered by one
    test is still remembered by every later test in the same worker.

    LANE 8 CYCLE 29. That leak produced a CI failure which read as a platform
    bug and was not one. `test_session_intents.py` and
    `test_loop_control_contention.py` share the literal key
    a1b2c3d4-0000-4000-8000-000000000001; when xdist put both files on one
    worker, the second file's halt_save POST replayed the first file's answer,
    performed NO side effect, and the contention test failed with
    "replace_fails(...) never fired: 0 matching attempts" - which looks exactly
    like the win32-only fault injector this lane fixed in cycle 26, and is
    instead ordinary cross-file state leakage. It reproduces on Windows in
    under two seconds by running those two files in one process.

    Isolating here rather than per-file on purpose: the correct fixture already
    existed in test_loop_control_idempotency.py:56 and had done since S2, which
    is precisely why the class stayed open - a guard that one file opts into
    does not cover the file that has not been written yet."""
    try:
        from dashboard import _idempotency
    except Exception:  # noqa: BLE001
        yield
        return
    _idempotency.clear()
    yield
    _idempotency.clear()


@pytest.fixture(autouse=True)
def redirect_shadow_paths_to_tmp(monkeypatch, tmp_path):
    """Suite hermeticity: no test may append to the repo's real shadow logs
    (data/det_coach_shadow.jsonl / hz_choice_shadow.jsonl /
    hz_build_shadow.jsonl). See the module docstring for the HZ-D4 root
    cause. monkeypatch restores the real SHADOW_PATH after each test."""
    for mod_name in _SHADOW_MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            continue
        current = getattr(mod, "SHADOW_PATH", None)
        if current is not None:
            # The real basename, not the module stem. `core.ds_coach_shadow`
            # writes `ds_coach_hints_shadow.jsonl`, so deriving the name from
            # the module would silently rename the corpus under a test's feet
            # and any assertion on `SHADOW_PATH.name` would flip.
            monkeypatch.setattr(mod, "SHADOW_PATH",
                                tmp_path / "shadow" / Path(current).name)


# RF5 (test hermeticity sibling sweep). Two production writers hardcode a
# module-global prod path and take NO ``path`` argument, so a caller has no tmp
# seam at all - the only defense against pollution is redirecting the global:
#   core.coach_trace.append()    -> _TRACE_FILE = data/coach_trace.jsonl
#   core.ds_calibration.log_ds_run() -> _LOG_PATH = data/ds_calibration.jsonl
# Both read the global at call time, so setattr redirects the write itself.
# (The shadow writers are handled above; ds_coach_shadow / decision_detector /
# loop_controller are already driven with an explicit path= or per-test
# monkeypatch by every caller.) monkeypatch restores the real globals after
# each test. Mirrors the SHADOW_PATH precedent (item 386) + the loop_controller
# CTL redirect (test_p2w4_hw2_b, OPEN2).
_PROD_WRITE_GLOBALS = (
    ("core.coach_trace", "_TRACE_FILE", "coach_trace.jsonl"),
    ("core.ds_calibration", "_LOG_PATH", "ds_calibration.jsonl"),
)


@pytest.fixture(autouse=True)
def redirect_prod_write_paths_to_tmp(monkeypatch, tmp_path_factory):
    # Mint an ISOLATED temp dir (not the test's own tmp_path) so this autouse
    # net never leaves a stray "prodwrite" entry inside a test's tmp_path - the
    # cache-prune tests scan tmp_path.iterdir() and a shared subdir breaks them.
    base = tmp_path_factory.mktemp("prodwrite")
    for mod_name, attr, fname in _PROD_WRITE_GLOBALS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001
            continue
        if hasattr(mod, attr):
            monkeypatch.setattr(mod, attr, base / fname)


# RM-406. Module-level PATH constants that resolve a repo subtree at IMPORT
# and are then read at CALL time. That second half is what makes them
# patchable at all: a constant baked into a default ARGUMENT is bound at
# `def` time and no amount of setattr will move it.
#
# Each row below was traced to a real leak in the 2026-09-11 census, with the
# producing line cited so a future reader can re-derive it rather than trust
# this comment:
#   core/coaching_timestamps.py:33  _RUNTIME_DIR  -> ops/runtime/coaching_ts_<mode>.json
#                                   (aram 9 tests, arena 9, tft 6)
#   core/feature_policy.py:59       _DATA_DIR     -> data/tft_{coaching,live}_data.json
#                                   via write_disabled_placeholder(:422-425)
#   tft/placement_aggregator.py:20  _RATINGS_DIR  -> mkdir target of update_heatmap(:111)
#   tft/placement_aggregator.py:21  _HEATMAP_FILE -> data/placement_heatmap.json (9 tests)
#   app/_game_lifecycle.py:34       SCRIPT_DIR    -> data/tft_live_data.json +
#                                   data/tft_coaching_data.json, reached through
#                                   `data_dir=SCRIPT_DIR / "data"` (:112) handed to
#                                   TftWorker, which writes both at
#                                   core/tft_worker.py:157-158
#
# `app/_game_lifecycle.py` is on the FROZEN list. Nothing here edits it - this
# rebinds a module ATTRIBUTE at runtime, exactly as the existing SHADOW_PATH
# and _SPEND_DIR redirects do, and the file on disk is untouched.
#
# What this CANNOT catch: a writer whose destination arrives as a constructor
# argument with no module-level origin at all (core/tft_worker.py's
# `self._data_dir` is only reachable here because the App hands it
# SCRIPT_DIR), and any test that passes a production path EXPLICITLY - the
# override arguments these modules expose for tests are honoured ahead of the
# global, which is correct, and means an explicit prod path still lands on
# the live tree.
_PROD_PATH_GLOBALS = (
    # (module, attribute, leaf under the shared base, target is a directory)
    ("core.coaching_timestamps", "_RUNTIME_DIR", "coaching_ts", True),
    ("core.feature_policy", "_DATA_DIR", "feature_policy_data", True),
    ("tft.placement_aggregator", "_RATINGS_DIR", "placement_ratings", True),
    ("tft.placement_aggregator", "_HEATMAP_FILE", "placement_heatmap.json", False),
    ("app._game_lifecycle", "SCRIPT_DIR", "app_root", True),
    ("coaches._base_coach", "_APP_DIR", "base_coach_root", True),
)


@pytest.fixture(scope="session")
def _live_state_base(tmp_path_factory):
    """One directory per worker for the redirects below.

    Session-scoped for the reason `_fusion_shadow_base` gives: the consumer
    is autouse, so a function-scoped `mktemp` would mint ~18k directories per
    run for no benefit. The cost of sharing is that state written by one test
    is visible to the next, which is acceptable here because every test that
    asserts on CONTENT passes its own explicit path - these globals only ever
    serve the default, i.e. the production, case.
    """
    return tmp_path_factory.mktemp("livestate")


@pytest.fixture(autouse=True)
def redirect_prod_path_globals_to_tmp(monkeypatch, _live_state_base):
    """Point every import-time production path constant at tmp.

    `coaches._base_coach._APP_DIR` deserves its own note, because redirecting
    it changes more than one line. Besides `data/coach_tick_trace.jsonl`
    (:660, the measured leak) it also feeds `read_api_key(_APP_DIR)` (:362)
    and `data/force_scan.json` (:488). The api-key read is the only one with
    behavioural weight: under the redirect the file is absent, so the key
    falls back to `ANTHROPIC_API_KEY` and `self._client` stays None. That is
    not a new state - it is EXACTLY what every CI runner already does, since
    no runner carries `API-Key-Claude.txt`. A test that depended on a live
    client could therefore never have been green on push, so nothing here
    depends on it. Redirecting `force_scan.json` is a bonus: reading the
    operator's live scan-force flag is its own hermeticity defect.
    """
    for mod_name, attr, leaf, is_dir in _PROD_PATH_GLOBALS:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001 - a missing subsystem is not a failure
            continue
        if not hasattr(mod, attr):
            continue
        target = _live_state_base / leaf
        # Producers mkdir their own leaf dirs but not always their parents,
        # and a file target's parent is nobody's job at all.
        (target if is_dir else target.parent).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mod, attr, target)


@pytest.fixture(autouse=True)
def redirect_performance_tracker_ratings_to_tmp(monkeypatch, _live_state_base):
    """`performance_tracker` takes its root as an ARGUMENT, so wrap, not patch.

    `_ratings_dir(sd)` (performance_tracker.py:191) builds
    `Path(sd) / RATINGS_DIR`, and `save_tft_rating` / `save_rating` receive
    `sd` from their caller - `app/_game_lifecycle.py:178` passes the live
    `SCRIPT_DIR`. There is no module global to move, and rebinding
    `RATINGS_DIR` to an absolute tmp path would break the legitimate seam:
    pathlib lets an absolute right-hand operand win, so every test that
    passes its OWN tmp root and then asserts on
    `<root>/data/ratings/last_sr.json` would start failing.
    Substituting only when the caller hands over the REAL repo root keeps
    that seam exact and closes the leak (data/ratings/last_tft.json, 2736
    bytes over 3 tests, plus 3 orphaned `.tmp` files the atomic writer left
    behind when the rename raced).
    """
    try:
        import performance_tracker as _pt
    except Exception:  # noqa: BLE001
        return
    original = getattr(_pt, "_ratings_dir", None)
    if original is None:
        return

    def _hermetic_ratings_dir(script_dir, _orig=original):
        try:
            is_prod_root = Path(script_dir).resolve() == _REPO_ROOT
        except (OSError, TypeError, ValueError):
            is_prod_root = False
        if not is_prod_root:
            return _orig(script_dir)
        target = _live_state_base / "perf_tracker_ratings"
        target.mkdir(parents=True, exist_ok=True)
        return target

    monkeypatch.setattr(_pt, "_ratings_dir", _hermetic_ratings_dir)


# RM-406. Tools that a test loads by FILE PATH rather than by import name,
# and that write a live log with plain file I/O instead of the logging
# package. Both halves matter, and each defeats a different fix:
#   - plain file I/O walks straight past `_hermetic_file_handler_init`
#     (tools/cost_health_watchdog.py:363 does `_LOG.open("a")`);
#   - `importlib.util.spec_from_file_location` (tests/test_cost_health_watchdog.py:15
#     and tests/test_cost_health_watchdog_glob_rm165.py:33) mints a module
#     object that is NOT registered under its dotted name, so
#     `importlib.import_module("tools.cost_health_watchdog")` returns a
#     DIFFERENT object and patching that one reaches nothing.
# Measured leak: logs/cost_health_watchdog.log, 2035 bytes over 3 tests.
#
# The sweep below looks for the copy in TWO places, and the second one is the
# whole trick. `module_from_spec` does not register anything: a first cut of
# this fixture scanned `sys.modules` for a module whose `__file__` is the
# tool, found nothing, and left the full 2035 bytes still landing on the live
# log - green fixture, zero effect. The loaded copy only ever exists as an
# ATTRIBUTE of the test module that made it, so the attribute scan is the arm
# that actually works; the `sys.modules` arm is kept for a loader that does
# register its copy.
_SPEC_LOADED_TOOL_LOGS = (
    ("tools/cost_health_watchdog.py", "_LOG", "cost_health_watchdog.log"),
)


def _module_file_matches(mod, tool_path) -> bool:
    mod_file = getattr(mod, "__file__", None)
    if not mod_file:
        return False
    try:
        return Path(mod_file).resolve() == tool_path
    except OSError:
        return False


def _iter_loaded_copies(tool_path):
    """Every live module object whose source file is ``tool_path``."""
    seen = set()
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        if _module_file_matches(mod, tool_path) and id(mod) not in seen:
            seen.add(id(mod))
            yield mod
        try:
            members = list(vars(mod).values())
        except TypeError:  # a module with no __dict__ (namespace shims)
            continue
        for member in members:
            if not isinstance(member, types.ModuleType):
                continue
            if id(member) in seen or not _module_file_matches(member, tool_path):
                continue
            seen.add(id(member))
            yield member


@pytest.fixture(scope="session", autouse=True)
def redirect_spec_loaded_tool_logs_to_tmp():
    """Repoint `_LOG`-style globals on file-path-loaded tool modules.

    SESSION scope is required and is not a performance choice: the modules in
    question are executed at test-module import, i.e. during collection, so
    they exist by the time the first test runs - but scanning `sys.modules`
    on every one of ~18k tests would cost more than the leak does. Running
    once, after collection, is both sufficient and cheap.

    Not restored afterwards, deliberately: the module objects are private to
    the test files that loaded them and the process is ending anyway.
    """
    for rel, attr, fname in _SPEC_LOADED_TOOL_LOGS:
        tool_path = (_REPO_ROOT / rel).resolve()
        for mod in _iter_loaded_copies(tool_path):
            if hasattr(mod, attr):
                setattr(mod, attr, _SUITE_LOG_DIR / fname)
    yield


@pytest.fixture(autouse=True)
def redirect_cost_tracker_spend_dir_to_tmp(monkeypatch, tmp_path_factory):
    """S5: no test may book synthetic spend into the operator's real ledger.

    `core/cost_tracker.py:120` resolves `_SPEND_DIR` to `data/spend/` at
    import time, and `get_tracker()` (:543) memoizes ONE process-global
    `CostTracker` bound to it. Every coach reaches that singleton through
    `coaches/_base_coach.py:713 _record_coach_call` and every non-coach call
    site through `core.cost_tracker.record_anthropic_response` (:563), so any
    test that drives a real coach with a mocked Anthropic client writes real
    financial telemetry. MEASURED 2026-08-06 by instrumenting `record_call`
    over the whole `tests/` suite: 32 leaked calls per run, all 10-in / 20-out
    under aram_coach / arena_coach, from exactly two files
    (`test_aram_state_debounce.py`, `test_arena_state_debounce.py`). On disk
    that had accumulated to 40 of 84 day-files carrying 13141 synthetic calls
    worth $1.156408, plus a phantom `1970-01-12.json` minted by the debounce
    ceiling test patching `time.time` (which `date.today()` reads through).
    A SECOND, DISTINCT write reached the per-match sidecars rather than a
    day-file, and its producer is UNIDENTIFIED. `core/match_db.py:177` fires
    `get_tracker().note_match_boundary()` on every saved match, which is the
    only route to those files, and the production ledger held two all-zero
    `by_gate` records 41 MILLISECONDS apart at 2026-08-04 22:16:28 - not two
    real matches. Ruled out, each by probe rather than by reading: no test in
    `tests/` calls `save_match` at all (the only match in
    `test_last_match_ingest_gameid.py` is a line-5 docstring mention; the file
    does raw sqlite3 INSERTs, and an instrumented run records zero
    `note_match_boundary` calls); `test_spend_gates_cutoff.py` calls it four
    times but always on a `CostTracker(spend_dir=tmp_path)` (:20-25); nothing
    under `agents/`, `scripts/`, `ops/` or `tools/` calls either function; and
    the live RC process is excluded because `core/match_db.py:170` logs "Match
    saved" at INFO on every save and `logs/2026-08-04.log` has no such line -
    at 22:16:28 it shows a 57-second heartbeat-only gap with "LCU lockfile not
    found" either side, so no game was running. That leaves an out-of-process
    run that does not write `logs/YYYY-MM-DD.log`. Do not guess which; the
    redirect below closes the route regardless of the caller, which is why the
    unknown does not block the fix. `tools/repair_spend_ledger.py` recovered
    the rows already written.

    PREVENTION, not detection: re-pointing the module global and clearing the
    memoized singleton means a future test cannot reintroduce the leak by
    forgetting to isolate - there is nothing to forget. Isolation lives in one
    place rather than in each `setUp`, matching the SHADOW_PATH precedent
    above. `monkeypatch` restores both after each test.

    What it CANNOT catch: a test that constructs `CostTracker(spend_dir=...)`
    with an explicit production path, or one that writes `data/spend/*.json`
    with plain file I/O instead of going through the tracker. The session
    guard in `assert_prod_artifacts_unchanged` is the backstop for those.
    """
    try:
        from core import cost_tracker as _ct
    except Exception:  # noqa: BLE001 - keep conftest collection dependency-free
        yield
        return
    base = tmp_path_factory.mktemp("spend")
    monkeypatch.setattr(_ct, "_SPEND_DIR", base, raising=False)
    monkeypatch.setattr(_ct, "_MATCH_OPEN_PATH",
                        base / "_match_open.json", raising=False)
    monkeypatch.setattr(_ct, "_RECENT_MATCHES_PATH",
                        base / "recent_matches.json", raising=False)
    # The singleton may already hold a production-bound tracker from an
    # earlier import; clearing it forces the next get_tracker() to rebuild
    # against the redirected dir.
    monkeypatch.setattr(_ct, "_singleton", None, raising=False)
    yield


@pytest.fixture(scope="session")
def _fusion_shadow_base(tmp_path_factory):
    """One temp dir per worker for the fusion-shadow redirect below.

    Session-scoped on purpose: the redirect is autouse, so a function-scoped
    `mktemp` would create a directory for every one of the ~18k tests. Measured
    at 1.4s for bare mkdirs locally, but it is pure waste on a slower CI disk
    and the push job runs against a 40-minute ceiling it has already touched.
    Tests that assert on shadow CONTENT set their own `RC_FUSION_SHADOW_PATH`
    to a per-test tmp_path, so sharing this directory is safe for the net.
    """
    return tmp_path_factory.mktemp("fusionshadow")


@pytest.fixture(autouse=True)
def redirect_fusion_shadow_to_tmp(monkeypatch, _fusion_shadow_base):
    """RM-155: keep the suite from writing `data/fusion_shadow.jsonl`.

    `modes.shared_vision._fusion_shadow_path()` resolves its target through the
    `RC_FUSION_SHADOW_PATH` env var at CALL time and falls back to the
    production path, so the module-global redirects above cannot reach it - it
    is a function, not a `SHADOW_PATH` constant. Individual tests set the env
    var, but any test that drives `read_tiered()` without doing so appended a
    real record to the production corpus.

    That made the suite NON-IDEMPOTENT in a fresh tree: the corpus is
    gitignored, so run 1 skipped `test_real_fusion_shadow_corpus_invariants`
    and passed while writing one record; run 2 then found a 1-record corpus,
    no longer skipped, and failed `assert narrowed > 0`. Setting the env var
    for EVERY test closes it at the root rather than per-test.
    """
    monkeypatch.setenv(
        "RC_FUSION_SHADOW_PATH",
        str(_fusion_shadow_base / "fusion_shadow.jsonl"),
    )


# RF5 suite-wide regression assert: no test may mutate a production
# coaching / loop / in-game artifact across the whole session. These paths are
# written ONLY by a live coach, the headless loop, or an in-game detector, so
# they stay byte-stable during an offline test run; any size change means a
# test wrote a prod path instead of tmp (the exact OPEN2 / RF5 regression).
# Scoped to artifacts the idle-client daemon never touches - health.json,
# logs/, lessons_*, and bridge_monitor are excluded because the live supervisor
# + cross-Claude bridge legitimately tick those during a run.
# NOTE 2026-07-28: `ops/loop/control/controller.log` was REMOVED from this
# tuple. It is not written by tests - it is written by the LIVE loop
# controller, a long-running production process that is up whenever the loop
# is running, which on Legion is most of the time. The guard cannot tell "a
# test wrote a prod path" from "a daemon appended to its own log", so it fired
# on a clean run (520607 -> 521318 bytes during a 191s suite) and reported a
# hermeticity regression that no test caused. A guard that fires on correct
# behaviour is one people learn to ignore, which costs more than the coverage
# it provided over a file no test should be touching anyway.
_PROD_ARTIFACT_GUARD = (
    "data/det_coach_shadow.jsonl",
    "data/hz_choice_shadow.jsonl",
    "data/hz_build_shadow.jsonl",
    "data/ds_coach_hints_shadow.jsonl",
    "data/live_benchmark_band_shadow.jsonl",
    "data/coach_trace.jsonl",
    "data/ds_calibration.jsonl",
    "data/decisions_log.jsonl",
    "data/decisions_pending.json",
    "data/decisions_heartbeat.json",
    "data/vision_state.json",
    # RM-173 (2026-08-06). The Phase 3 supervisor's singleton claim. A test
    # that constructs a Supervisor and calls stop() without relocating
    # STATE_DIR deletes the LIVE daemon's lock pair, and the damage is
    # invisible: the lockfile is rewritten within 5s by the next heartbeat,
    # the sentinel is not, and every health signal keeps reading green while
    # the singleton is disarmed. Measured 2026-08-06 - absent 02:54 to 20:44,
    # then again the same evening. Two known callers were relocated; this
    # entry is the MECHANISM that catches the third. It is quiet in normal
    # operation because the file is written exactly once per daemon start and
    # never touched again, and a supervisor restart mid-suite only changes its
    # size if the pid's digit count changes.
    "agents/state/lockfile.sentinel",
)

# S5 backstop for the cost ledger. `data/spend/` is a DIRECTORY of day-files,
# so a single size check cannot cover it: the set membership matters as much as
# the bytes (the leak minted a whole phantom `1970-01-12.json`). Three files are
# deliberately EXCLUDED because a live coach legitimately writes them mid-run on
# Legion, where RC-Supervisor is up most of the time - the same false-positive
# that got `ops/loop/control/controller.log` removed from the tuple above:
#   <today>.json           - today's ledger, written on every live API call
#   _match_open.json       - re-snapshotted by note_match_boundary on match save
#   recent_matches.json    - ditto
# Everything older than today is immutable in production, so any change there is
# a test writing a prod path. Prevention for today's file is the autouse
# `redirect_cost_tracker_spend_dir_to_tmp` fixture; this guard catches what a
# redirect cannot (raw file I/O, or an explicit production `spend_dir=`).
_SPEND_DIR_GUARD = _REPO_ROOT / "data" / "spend"


def _spend_ledger_snapshot() -> dict:
    """{filename -> size} for every historic day-file in data/spend/."""
    from datetime import date as _date
    if not _SPEND_DIR_GUARD.is_dir():
        return {}
    skip = {_date.today().isoformat() + ".json",
            "_match_open.json", "recent_matches.json"}
    return {p.name: p.stat().st_size
            for p in _SPEND_DIR_GUARD.iterdir()
            if p.is_file() and p.name not in skip}


def _prod_artifact_sizes() -> dict:
    out = {}
    for rel in _PROD_ARTIFACT_GUARD:
        p = _REPO_ROOT / rel
        out[rel] = p.stat().st_size if p.exists() else None
    return out


@pytest.fixture(scope="session", autouse=True)
def _no_live_tft_ocr():
    """No test may start the live TFT OCR capture thread.

    SESSION-scoped deliberately. The first version of this fixture was
    function-scoped, and a TftOcr thread still leaked - caught by
    ``tests/test_no_live_ocr_thread_in_suite.py`` on the very next run. A
    function-scoped patch is not in force while MODULE- or SESSION-scoped
    fixtures build their objects, so any reader constructed in a broader-scoped
    fixture slipped straight past it. Session scope closes that window.

    ``tft/tft_state_reader.py:60-68`` starts a daemon thread in
    ``TftStateReader.__init__`` whenever ``TftOcrReader().available`` is true,
    and that thread does REAL screen capture plus REAL HTTP to ``:8889`` every
    2 seconds, forever - nothing joins it, so it outlives the test that made
    it. ``available`` is true on any host with pytesseract, i.e. Legion, and
    false on the CI runner, which is why this never showed up on push.

    MEASURED 2026-07-28: a full dual suite under ``-n 8 --dist loadfile`` hung
    for 2h29m rather than the noted 145s - worker ``gw6`` went down and the
    controller then wedged in ``pytest_sessionfinish`` with ``OSError: cannot
    send (already closed?)``. ``--timeout=600`` never fired because the hang is
    outside any test. That the thread caused the crash is SUSPECTED, not
    proven; that the suite spawns unjoined real-capture threads is proven, and
    is a hermeticity defect regardless.

    Gating on the class property rather than on each construction site is
    deliberate: patching the three known callers in
    ``tests/phase2_smoke/test_snapshot_translation.py`` would leave the next
    one to reintroduce it silently. Pinned by
    ``tests/test_no_live_ocr_thread_in_suite.py``, which also asserts this
    fixture is in force so the pin cannot pass vacuously.

    A test that genuinely needs the real reader must undo this itself AND stop
    what it starts.
    """
    try:
        from tft.tft_ocr_reader import TftOcrReader
    except Exception:  # noqa: BLE001 - no TFT stack present is not a failure
        yield
        return
    # mock.patch rather than monkeypatch: monkeypatch is function-scoped and
    # pytest refuses to use it from a session-scoped fixture.
    patcher = mock.patch.object(
        TftOcrReader, "available", property(lambda self: False))
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()


@pytest.fixture(scope="session", autouse=True)
def assert_prod_artifacts_unchanged():
    before = _prod_artifact_sizes()
    spend_before = _spend_ledger_snapshot()
    yield
    after = _prod_artifact_sizes()
    changed = [
        rel + " " + str(before[rel]) + "->" + str(after[rel])
        for rel in _PROD_ARTIFACT_GUARD
        if before[rel] != after[rel]
    ]
    spend_after = _spend_ledger_snapshot()
    for name in sorted(set(spend_before) | set(spend_after)):
        b = spend_before.get(name)
        a = spend_after.get(name)
        if b != a:
            changed.append("data/spend/" + name + " " + str(b) + "->" + str(a))
    assert not changed, (
        "suite mutated a production artifact - a test wrote a prod path "
        "instead of tmp (RF5 hermeticity regression): " + "; ".join(changed)
    )
