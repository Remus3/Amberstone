"""RM-406 - the suite must not write the operator's live tree.

WHAT WAS MEASURED, AND HOW
--------------------------
2026-09-11, `tools/live_write_tracer.py` loaded as `-p tools.live_write_tracer`
over `pytest tests -n 8 --dist loadfile` on Legion. The tracer wraps
`builtins.open`, `io.open`, `os.replace` and `os.rename` IN-PROCESS, counts
BYTES ACTUALLY WRITTEN (never opens), and attributes each write to the running
pytest nodeid.

A before/after filesystem snapshot was deliberately NOT used, and that choice
is the reason these numbers mean anything. A sibling repo measured a
300-second IDLE control on this same box - no suite running at all - and four
live files changed regardless, because the supervisor, the coaches and other
concurrent sessions write `logs/`, `data/` and `ops/runtime/` continuously. A
file that changes during a suite run therefore attributes NOTHING to the
suite. The tracer is process-local, so an event recorded by it was performed
by that pytest process and by nothing else.

WHY THE CENSUS IS PINNED HERE AS DATA
-------------------------------------
Prose rots and is never re-run. A number in a test reds on drift. The census
below is the BEFORE state - what the suite actually did before the fixtures in
`tests/conftest.py` were extended - kept so that a reader can see the size of
each leak and, for every row, which named mechanism now prevents it. The
AFTER state is pinned too, further down, against a re-measurement.

WHAT THIS GUARD CANNOT DO - FOUR STATED LIMITS, EACH MEASURED
-------------------------------------------------------------
An adversarial pass on 2026-09-11 refuted the first draft of this docstring,
which claimed "removing any one redirect from conftest.py turns this file
red". It does not, and the honest version is worth more than the slogan:

1. DELETING A WHOLE REDIRECT reds the matching mechanism, because the checks
   below read the LIVE module attributes and take the UNION of this file's
   `_REQUIRED_*` tuples with conftest's tables. NARROWING one reliably does
   not. `_check_logging_handler_ctor` verifies the constructor identity and
   sweeps the handlers attached IN THIS WORKER; a `_tmp_log_path` edited to
   pass one filename straight through leaves both arms satisfied, and under
   `--dist loadfile` the test that would have attached that handler need not
   even share this worker. The demonstrated mutation was `hotkey_listener.log`.
2. IT CANNOT DETECT A NEW LEAK. Detection is the tracer's job and it needs a
   full instrumented run; this guard proves that each already-identified
   mechanism is still armed and that the tables it depends on still describe
   real files.
3. IT IS BLIND TO SUBPROCESSES - a spawned supervisor, a `py_compile` in a
   child, a PowerShell call - because every mechanism here is in-process, and
   so was the measurement.
4. THE TREE SCAN SEES TRACKED FILES ONLY. `tests/_repo_walk` enumerates the
   git index first (ADR-015), so a brand-new UNTRACKED `core/*_shadow.py`
   is invisible to `test_every_shadow_writer_is_registered_for_redirect`
   until it is added. That is the right default for a repo guard - an
   untracked file is not yet part of the project - but it means the one
   assertion here that can catch a leak before it happens has a window
   exactly as wide as the gap between writing a module and staging it.

Deliberately NOT solved by adding live `logs/` paths to conftest's
`_PROD_ARTIFACT_GUARD`: see the 2026-07-28 note in that file. A size-snapshot
guard cannot tell "a test wrote a prod path" from "a live daemon appended to
its own log", it fired on a clean run, and a guard that fires on correct
behaviour is one people learn to ignore. Prevention by redirect is the
mechanism here; the size guard stays for paths no daemon touches.
"""
from __future__ import annotations

import importlib
import logging
import re
import sys
import types
from functools import lru_cache
from pathlib import Path

import pytest

from tests import _repo_walk
from tests import conftest as rc_conftest

REPO_ROOT = _repo_walk.REPO_ROOT

# ---------------------------------------------------------------------------
# THE CENSUS. Columns: repo-relative path, bytes written, distinct tests,
# disposition, mechanism key, reason.
#
# `mechanism` names an entry in `_MECHANISMS` below and is what makes a row
# falsifiable. An EXCEPTION row carries no mechanism and must carry a reason.
# ---------------------------------------------------------------------------
_FIXED = "FIXED"
_EXCEPTION = "EXCEPTION"

_CENSUS = (
    # --- appends to live logs -------------------------------------------
    # 182940/850 is what THIS tree measured on 2026-09-11. An earlier run the
    # same day recorded 182674/849 for the same row - log volume tracks which
    # tests happen to share a worker, so this figure is an order of magnitude,
    # not a constant. Pinned anyway: the point of the number is that a reader
    # who re-measures and gets 200 bytes knows the fix held, and one who gets
    # 180000 knows it did not.
    ("logs/agents/supervisor.log", 182940, 850, _FIXED, "logging-handler-ctor",
     "agents/_supervisor_common.py:224 builds the logger at IMPORT and tees "
     "the 'rc' logger into it, so every rc.* record in the worker landed here"),
    ("logs/cost_health_watchdog.log", 2035, 3, _FIXED, "spec-loaded-tool-logs",
     "tools/cost_health_watchdog.py:363 writes with plain file I/O, and the "
     "tests load the tool by file path so it is absent from sys.modules"),
    ("logs/hotkey_listener.log", 267, 2, _FIXED, "logging-handler-ctor",
     "tools/hotkey_listener.py:95 resolves its log from __file__ inside the "
     "logger builder - no module constant exists to patch"),
    # --- appends to live shadow / trace corpora --------------------------
    ("data/aram_coach_shadow.jsonl", 2946, 2, _FIXED, "shadow-paths",
     "core/aram_coach_shadow.py:34 SHADOW_PATH was absent from _SHADOW_MODULES"),
    ("data/objective_playbook_shadow.jsonl", 1260, 4, _FIXED, "shadow-paths",
     "core/objective_playbook_shadow.py:28 SHADOW_PATH, same omission"),
    ("data/macro_response_shadow.jsonl", 960, 4, _FIXED, "shadow-paths",
     "core/macro_response_shadow.py:29 SHADOW_PATH, same omission"),
    ("data/anvil_shadow.jsonl", 541, 1, _FIXED, "shadow-paths",
     "core/anvil_shadow.py:39 SHADOW_PATH, same omission"),
    ("data/coach_tick_trace.jsonl", 286, 2, _FIXED, "prod-path-globals",
     "coaches/_base_coach.py:660 derives the path from _APP_DIR at call time"),
    # --- live state JSON replaced wholesale via atomic rename ------------
    ("data/ratings/last_tft.json", 2736, 3, _FIXED, "perf-tracker-ratings",
     "performance_tracker.py:191 takes its root as an argument; "
     "app/_game_lifecycle.py:178 hands it the live SCRIPT_DIR"),
    ("data/tft_live_data.json", 2094, 6, _FIXED, "prod-path-globals",
     "core/tft_worker.py:158 writes into the data_dir handed to it at "
     "app/_game_lifecycle.py:112, which is SCRIPT_DIR / 'data'"),
    ("data/tft_coaching_data.json", 1183, 7, _FIXED, "prod-path-globals",
     "core/tft_worker.py:157 by the same route, plus "
     "core/feature_policy.py:422 writing the disabled placeholder"),
    ("data/placement_heatmap.json", 1155, 9, _FIXED, "prod-path-globals",
     "tft/placement_aggregator.py:113-115 atomic-writes _HEATMAP_FILE"),
    ("ops/runtime/coaching_ts_arena.json", 1003, 9, _FIXED, "prod-path-globals",
     "core/coaching_timestamps.py:33 _RUNTIME_DIR, read at call time"),
    ("ops/runtime/coaching_ts_aram.json", 928, 9, _FIXED, "prod-path-globals",
     "core/coaching_timestamps.py:33, same constant"),
    ("ops/runtime/coaching_ts_tft.json", 342, 6, _FIXED, "prod-path-globals",
     "core/coaching_timestamps.py:33, same constant"),
    ("ops/runtime/hot_reload.json", 388, 3, _FIXED, "hot-reload-disabled",
     "written by the watcher THREAD web_dashboard.py:59 starts at import, so "
     "the three credited nodeids are bystanders, not causes"),
    # --- the one that is not about bytes ---------------------------------
    ("restart_trigger.txt", 15, 1, _FIXED, "hot-reload-disabled",
     "core/hot_reload.py:176 - the suite handed the supervisor a restart "
     "request. That the pytest process WROTE the signal is proven; that any "
     "one observed restart consumed THIS write is not, because the "
     "production watcher writes the same file on any .py change"),
    # --- recorded, deliberately not prevented ----------------------------
    ("moon_sync_inbox/rc_audit_probe_inside.txt", 13, 1, _EXCEPTION, "",
     "RC's OWN inbox, not a sibling's. The write IS the assertion - "
     "tests/test_vision_server_http_hardening.py proves a file inside the "
     "inbox is still served - and the test removes it again. Redirecting it "
     "would delete the positive control."),
)

# The three orphaned scratch files the atomic writer left behind
# (data/ratings/last_tft.json.<pid>.<hex>.tmp, 912 bytes each) are not listed
# as their own rows: they are the tmp half of the last_tft.json row above and
# disappear with it. They are noted because a leaked scratch file is the only
# visible symptom of an atomic write whose rename never happened.
_ORPHAN_TMP_PARENT = "data/ratings/last_tft.json"

# Files the BEFORE run opened for write and wrote ZERO bytes to. Recorded
# rather than fixed: a zero-byte open leaves the live tree byte-identical, so
# it is a hygiene observation, not a pollution finding. The lock files in
# particular are supposed to be opened - that is what a lock is.
# Five of the seven stopped being opened at all as a side effect of the
# logging-handler redirect, which moves the OPEN and not merely the write;
# only the two .lock entries survived into the AFTER run. The list is kept at
# its BEFORE length on purpose - this tuple documents what was measured, and
# shrinking it to match the current state would erase the evidence that the
# handler fix reached further than the bytes suggested.
_ZERO_BYTE_OPENS = (
    "ops/runtime/coaching_data.lock",
    "ops/runtime/decisions.lock",
    "logs/phase_watcher.log",
    "logs/lcu_agent.log",
    "logs/liveclient_relay.log",
    "logs/data_pipeline.log",
    "logs/daemon_slayer_extract.log",
)

# Every module whose file must still exist for the redirect tables to mean
# anything. Checked against the repo-root enumeration, so a rename or a
# deletion reds this guard instead of silently disarming a redirect.
# ---------------------------------------------------------------------------
# THE AFTER STATE. Re-measured 2026-09-11 on the tree that carries the
# conftest redirects, with `tools/live_write_tracer.py` over
# `pytest tests -q -p no:randomly -n 8 --dist loadfile` (21846 passed, 97
# skipped, 4934 subtests, exit 0), merging all nine per-process reports.
#
# THE WHOLE RESULT, so nobody has to take a summary on trust:
#   wrote_units            13 units across 1 path
#   that path              moon_sync_inbox/rc_audit_probe_inside.txt
#   opened_for_write_only  ops/runtime/coaching_data.lock (1 test)
#                          ops/runtime/decisions.lock (11 tests)
#   everything else        zero
#
# 201079 units over 17 paths BEFORE, 0 over 0 AFTER once the one deliberate
# EXCEPTION is set aside. The exception is not an oversight and not a rounding
# error - it is the single row the census declares as deliberately NOT
# prevented, and the AFTER run reproducing exactly it and nothing else is the
# strongest available evidence that the other sixteen rows are closed.
#
# The assertions below are JOINS against the census table rather than restated
# literals, because a literal compared to itself proves nothing: adding an
# EXCEPTION row without re-measuring reds them, and so does flipping a FIXED
# row to EXCEPTION.
_AFTER_LIVE_WRITE_UNITS = 13
_AFTER_LIVE_WRITE_PATHS = ("moon_sync_inbox/rc_audit_probe_inside.txt",)
# Two of the seven BEFORE zero-byte opens survived. The other five stopped
# being opened at all as a side effect of the logging-handler redirect, which
# moves the OPEN and not merely the write - predicted in the `_ZERO_BYTE_OPENS`
# note below and independently reproduced by this run.
_AFTER_ZERO_BYTE_OPENS = (
    "ops/runtime/coaching_data.lock",
    "ops/runtime/decisions.lock",
)

_PRODUCER_FILES = (
    "agents/_supervisor_common.py",
    "coaches/_base_coach.py",
    "core/coaching_timestamps.py",
    "core/feature_policy.py",
    "core/hot_reload.py",
    "performance_tracker.py",
    "tft/placement_aggregator.py",
    "tools/cost_health_watchdog.py",
    "tools/hotkey_listener.py",
    "web_dashboard.py",
)

# A module-level `SHADOW_PATH = ...` or `SHADOW_PATH: Path = ...`. The looser
# `^SHADOW_PATH\b` was tried first and matched a line of PROSE in conftest's
# own docstring that happens to begin with the word - an empty-grep-style
# false positive in the opposite direction.
_SHADOW_ASSIGN = re.compile(r"^SHADOW_PATH\s*[:=]", re.M)

# THE REQUIREMENT, held here rather than read out of conftest.
#
# The first cut of this guard iterated `conftest._PROD_PATH_GLOBALS` directly
# and was therefore unfalsifiable in the one way that matters: deleting a row
# disarmed the redirect AND removed it from the check, so the mutation the
# guard exists to catch made the guard greener, not redder. The checks below
# take the UNION of this list and conftest's, so a new conftest row is still
# verified while a deleted one still reds.
_REQUIRED_PATH_GLOBALS = (
    ("core.coaching_timestamps", "_RUNTIME_DIR"),
    ("core.feature_policy", "_DATA_DIR"),
    ("tft.placement_aggregator", "_RATINGS_DIR"),
    ("tft.placement_aggregator", "_HEATMAP_FILE"),
    ("app._game_lifecycle", "SCRIPT_DIR"),
    ("coaches._base_coach", "_APP_DIR"),
)
_REQUIRED_WRITE_GLOBALS = (
    ("core.coach_trace", "_TRACE_FILE"),
    ("core.ds_calibration", "_LOG_PATH"),
)
_REQUIRED_SPEC_LOADED_LOGS = (
    ("tools/cost_health_watchdog.py", "_LOG"),
)


def _is_outside_repo(value) -> bool:
    """True when a path-like value does not resolve under the repo root."""
    try:
        Path(value).resolve().relative_to(REPO_ROOT)
    except (OSError, TypeError, ValueError):
        return True
    return False


def _live_log_handlers() -> list:
    """Every attached handler whose file sits under the repo's real logs/."""
    real_logs = REPO_ROOT / "logs"
    offenders = []
    loggers = [logging.getLogger()]
    loggers += [lg for lg in logging.Logger.manager.loggerDict.values()
                if isinstance(lg, logging.Logger)]
    for lg in loggers:
        for handler in lg.handlers:
            base = getattr(handler, "baseFilename", None)
            if not base:
                continue
            try:
                Path(base).resolve().relative_to(real_logs)
            except (OSError, ValueError):
                continue
            offenders.append((lg.name, base))
    return offenders


# ---------------------------------------------------------------------------
# MECHANISMS. Each returns a list of human-readable failures; empty means the
# mechanism is armed RIGHT NOW, inside this running test.
# ---------------------------------------------------------------------------

def _check_logging_handler_ctor() -> list:
    bad = []
    if logging.FileHandler.__init__ is not rc_conftest._hermetic_file_handler_init:
        bad.append("logging.FileHandler.__init__ is not conftest's hermetic "
                   "wrapper - a later import replaced or restored it")
    for name, base in _live_log_handlers():
        bad.append(f"logger {name!r} still writes {base}")
    return bad


def _check_hot_reload_disabled() -> list:
    hot_reload = importlib.import_module("core.hot_reload")
    if hot_reload.start_watcher is not rc_conftest._disabled_hot_reload_watcher:
        return ["core.hot_reload.start_watcher is the REAL watcher - importing "
                "web_dashboard will start a thread that writes "
                "restart_trigger.txt and bounces the live supervisor"]
    return []


@lru_cache(maxsize=1)
def _discovered_shadow_modules() -> tuple:
    """Dotted names of every non-test module with a module-global SHADOW_PATH.

    Cached: the scan reads every tracked .py, and two separate assertions want
    the answer.
    """
    found = []
    for path in _repo_walk.repo_files(patterns=("*.py",)):
        rel = _repo_walk.relative_posix(path)
        if rel.startswith("tests/"):
            continue  # a fixture is not a production writer
        try:
            src = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _SHADOW_ASSIGN.search(src):
            found.append(rel[:-len(".py")].replace("/", "."))
    return tuple(sorted(found))


def _check_shadow_paths() -> list:
    bad = []
    required = set(rc_conftest._SHADOW_MODULES) | set(_discovered_shadow_modules())
    for mod_name in sorted(required):
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{mod_name} does not import: {exc!r}")
            continue
        current = getattr(mod, "SHADOW_PATH", None)
        if current is None:
            bad.append(f"{mod_name} no longer defines SHADOW_PATH")
        elif not _is_outside_repo(current):
            bad.append(f"{mod_name}.SHADOW_PATH -> {current}")
    return bad


def _check_prod_path_globals() -> list:
    bad = []
    required = set(_REQUIRED_PATH_GLOBALS)
    required |= {(m, a) for m, a, _leaf, _is_dir
                 in rc_conftest._PROD_PATH_GLOBALS}
    for mod_name, attr in sorted(required):
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{mod_name} does not import: {exc!r}")
            continue
        if not hasattr(mod, attr):
            bad.append(f"{mod_name} no longer defines {attr}")
            continue
        current = getattr(mod, attr)
        if not _is_outside_repo(current):
            bad.append(f"{mod_name}.{attr} -> {current}")
    return bad


def _check_prod_write_globals() -> list:
    bad = []
    required = set(_REQUIRED_WRITE_GLOBALS)
    required |= {(m, a) for m, a, _fname in rc_conftest._PROD_WRITE_GLOBALS}
    for mod_name, attr in sorted(required):
        try:
            mod = importlib.import_module(mod_name)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"{mod_name} does not import: {exc!r}")
            continue
        current = getattr(mod, attr, None)
        if current is None:
            bad.append(f"{mod_name} no longer defines {attr}")
        elif not _is_outside_repo(current):
            bad.append(f"{mod_name}.{attr} -> {current}")
    return bad


def _check_perf_tracker_ratings() -> list:
    perf = importlib.import_module("performance_tracker")
    resolved = perf._ratings_dir(REPO_ROOT)
    if not _is_outside_repo(resolved):
        return [f"performance_tracker._ratings_dir(REPO_ROOT) -> {resolved}"]
    return []


def _check_spec_loaded_tool_logs() -> list:
    bad = []
    required = set(_REQUIRED_SPEC_LOADED_LOGS)
    required |= {(r, a) for r, a, _fname in rc_conftest._SPEC_LOADED_TOOL_LOGS}
    for rel, attr in sorted(required):
        tool_path = (REPO_ROOT / rel).resolve()
        copies = list(rc_conftest._iter_loaded_copies(tool_path))
        for mod in copies:
            current = getattr(mod, attr, None)
            if current is not None and not _is_outside_repo(current):
                bad.append(f"{rel} copy {mod.__name__!r}.{attr} -> {current}")
    return bad


_MECHANISMS = {
    "logging-handler-ctor": _check_logging_handler_ctor,
    "hot-reload-disabled": _check_hot_reload_disabled,
    "shadow-paths": _check_shadow_paths,
    "prod-path-globals": _check_prod_path_globals,
    "perf-tracker-ratings": _check_perf_tracker_ratings,
    "spec-loaded-tool-logs": _check_spec_loaded_tool_logs,
}


# ---------------------------------------------------------------------------
# STATIC HALF - the census must keep describing this tree.
# ---------------------------------------------------------------------------

def test_repo_enumeration_is_not_vacuous():
    """An empty walk and a spotless tree are the same verdict to every
    assertion below, so prove the walker still reaches real files first."""
    _repo_walk.self_check()
    modules = _repo_walk.repo_files(patterns=("*.py",))
    assert len(modules) >= 1000, (
        "repo-root enumeration collapsed to "
        f"{len(modules)} tracked .py files - every scan in this file would "
        "then pass for the wrong reason. Fix the walker, do not lower this."
    )


def test_every_named_producer_file_still_exists():
    """A redirect whose target module was renamed is a redirect that silently
    does nothing - `importlib.import_module` raises, conftest swallows it, and
    the leak comes back with no test failing."""
    found = {_repo_walk.relative_posix(p)
             for p in _repo_walk.repo_files(patterns=("*.py",))}
    assert found, "enumeration returned nothing - see the anchor test above"
    missing = [rel for rel in _PRODUCER_FILES if rel not in found]
    assert not missing, (
        "census names producer file(s) that are no longer tracked at that "
        f"path: {missing}. Re-derive the producer and update both this list "
        "and the matching conftest redirect."
    )


def test_every_shadow_writer_is_registered_for_redirect():
    """A module-global `SHADOW_PATH` anywhere in the tree must be redirected.

    This is the one assertion here that can catch a leak that has not happened
    yet. Four of the census rows above are shadow corpora whose modules were
    simply absent from a hand-maintained tuple - the mechanism worked, the list
    was short. Enumerating the tree instead of the tuple closes that class.
    """
    registered = set(rc_conftest._SHADOW_MODULES)
    discovered = _discovered_shadow_modules()
    assert len(discovered) >= 13, (
        f"only {len(discovered)} SHADOW_PATH modules found, expected at least "
        "13. Either a shadow module was legitimately deleted - in which case "
        "lower this floor deliberately, in the same commit - or the scan "
        "broke. An empty scan would pass the assertion below for the wrong "
        "reason, which is the only thing this floor exists to prevent; it "
        "does NOT diagnose which of the two happened."
    )
    unregistered = sorted(set(discovered) - registered)
    assert not unregistered, (
        "module(s) define a module-global SHADOW_PATH but are not in "
        f"tests/conftest.py::_SHADOW_MODULES: {unregistered}. Add them - an "
        "unlisted shadow writer appends to the operator's live corpus on "
        "every suite run."
    )


@pytest.mark.parametrize(
    "row", _CENSUS, ids=[row[0] for row in _CENSUS])
def test_census_row_is_well_formed(row):
    """Every row is either FIXED with a live mechanism, or an EXCEPTION with a
    reason. A row that is neither is a leak nobody decided about."""
    rel, written, tests, disposition, mechanism, reason = row
    assert written > 0 and tests > 0, f"{rel}: a zero row is not a finding"
    assert reason.strip(), f"{rel}: every row must carry its reason inline"
    if disposition == _FIXED:
        assert mechanism in _MECHANISMS, (
            f"{rel}: names mechanism {mechanism!r}, which does not exist")
    else:
        assert disposition == _EXCEPTION, f"{rel}: unknown disposition"
        assert not mechanism, f"{rel}: an EXCEPTION must name no mechanism"


def test_census_totals_are_pinned():
    """The headline numbers, so a future reader can size the problem without
    re-running the tracer - and so a silent edit to the table is visible.

    The sum is over THIS TABLE, not over a tracer artifact. It is a
    hand-curated subset by construction: the tracer also credits the `*.tmp`
    half of every atomic write, which the table folds into its destination
    row, so `201079` is re-derivable from the rows here and NOT by adding up
    a raw report. Said plainly because the opposite reading - that this is a
    machine total - would send a re-measurer looking for a number that never
    existed.
    """
    fixed = [r for r in _CENSUS if r[3] == _FIXED]
    assert len(_CENSUS) == 18
    assert len(fixed) == 17
    assert sum(r[1] for r in fixed) == 201079
    assert max(r[2] for r in fixed) == 850  # logs/agents/supervisor.log
    assert len(_ZERO_BYTE_OPENS) == 7
    # A JOIN, not a restatement. The first draft compared this constant to its
    # own literal, which is true by construction and proves nothing; what
    # matters is that the orphaned tmp files belong to a row that still exists.
    assert _ORPHAN_TMP_PARENT in {row[0] for row in _CENSUS}


def test_zero_byte_open_paths_are_inside_the_watched_tree():
    """`_ZERO_BYTE_OPENS` had only its length asserted, so its seven entries
    could have been any strings at all. They are only meaningful if the tracer
    would in fact have watched them, which means living under one of its
    watched subtrees."""
    watched = ("ops/runtime/", "logs/", "data/", "moon_sync_inbox/")
    stray = [p for p in _ZERO_BYTE_OPENS if not p.startswith(watched)]
    assert not stray, (
        f"zero-byte-open entries outside every watched subtree: {stray} - the "
        "tracer would never have reported them, so they cannot have been "
        "measured")
    assert all(p.endswith((".log", ".lock")) for p in _ZERO_BYTE_OPENS)


def test_after_measurement_is_exactly_the_census_exceptions():
    """The AFTER pin, joined to the table rather than restated.

    This is the assertion that carries the cycle's claim. Every path the
    instrumented AFTER run still wrote must be a row the census DECLARED as
    deliberately unprevented, and every such row must appear in the AFTER
    run - so a FIXED row that starts leaking again, or a new EXCEPTION added
    without re-measuring, both red here.
    """
    exceptions = {row[0]: row[1] for row in _CENSUS if row[3] == _EXCEPTION}
    assert exceptions, "an empty exception set would make this vacuous"
    assert set(_AFTER_LIVE_WRITE_PATHS) == set(exceptions), (
        "the AFTER measurement and the census EXCEPTION rows disagree: "
        f"measured {sorted(_AFTER_LIVE_WRITE_PATHS)}, declared "
        f"{sorted(exceptions)}. Re-run the tracer rather than editing either "
        "list to match the other.")
    assert _AFTER_LIVE_WRITE_UNITS == sum(exceptions.values()), (
        f"AFTER total {_AFTER_LIVE_WRITE_UNITS} != the declared exception "
        f"bytes {sum(exceptions.values())}")
    fixed_paths = {row[0] for row in _CENSUS if row[3] == _FIXED}
    assert not (set(_AFTER_LIVE_WRITE_PATHS) & fixed_paths), (
        "a row claimed FIXED still received data in the AFTER run")


def test_after_zero_byte_opens_are_a_subset_of_the_before_list():
    """The five that stopped being opened are a real, predicted outcome; a
    zero-byte open appearing in the AFTER set that was never in the BEFORE
    census would be a NEW open nobody measured."""
    before = set(_ZERO_BYTE_OPENS)
    after = set(_AFTER_ZERO_BYTE_OPENS)
    assert after, "an empty AFTER set would make the subset check vacuous"
    assert after <= before, f"unmeasured zero-byte opens: {sorted(after - before)}"
    assert len(after) == 2 and all(p.endswith(".lock") for p in after), (
        "the two survivors are both lock files, which is the point: a lock is "
        "SUPPOSED to be opened, so these are hygiene observations and not "
        "pollution findings")


def test_required_tables_are_pinned():
    """The three test-side tables above are the half of each union that cannot
    be deleted from conftest, so they are the half that must not shrink.

    Without a floor the union is only as strong as the WEAKER list: dropping a
    row from the tuple here AND from the matching conftest table shrinks the
    requirement to nothing while every assertion downstream still passes, which
    is the same unfalsifiability the union was introduced to fix. Raise a
    number here when a redirect is genuinely added; never lower one to make a
    deletion green.
    """
    assert len(_REQUIRED_PATH_GLOBALS) == 6, (
        "the six module path globals whose redirect prevents the "
        "prod-path-globals census rows (coach_tick_trace, tft_live_data, "
        "tft_coaching_data, placement_heatmap, the three coaching_ts_*.json)"
    )
    assert len(_REQUIRED_WRITE_GLOBALS) == 2, (
        "core.coach_trace._TRACE_FILE and core.ds_calibration._LOG_PATH - the "
        "pre-existing RF5 pair, the only rows test_prod_write_globals_are_"
        "also_redirected can still prove armed if conftest's table is emptied"
    )
    assert len(_REQUIRED_SPEC_LOADED_LOGS) == 1, (
        "tools/cost_health_watchdog.py::_LOG - the sole spec-loaded tool log "
        "in the census, and the only writer that plain-file-I/Os a live log"
    )


# ---------------------------------------------------------------------------
# RUNTIME HALF - the mechanisms must be armed during an actual test.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(_MECHANISMS))
def test_mechanism_is_armed_during_a_test(name):
    """Falsifiable by construction: delete the matching redirect from
    `tests/conftest.py` and the corresponding parametrisation goes red,
    because these read the LIVE module attributes rather than the table."""
    failures = _MECHANISMS[name]()
    assert not failures, (
        f"hermeticity mechanism {name!r} is not in force - the suite will "
        "write the operator's live tree: " + "; ".join(failures))


def test_every_fixed_row_has_an_armed_mechanism():
    """The join between the two halves. A row can only claim FIXED while the
    mechanism it names is actually holding."""
    broken = {}
    for rel, _written, _tests, disposition, mechanism, _reason in _CENSUS:
        if disposition != _FIXED:
            continue
        failures = _MECHANISMS[mechanism]()
        if failures:
            broken[rel] = failures
    assert not broken, f"FIXED rows whose mechanism is down: {broken}"


def test_spec_loaded_copy_finder_is_not_vacuous():
    """`_check_spec_loaded_tool_logs` passes trivially when this worker holds
    no spec-loaded copy of the tool, which is most of the time - so the
    parametrised mechanism test above proves nothing about the fragile half.

    The fragile half is the FINDER. A first cut of the conftest fixture
    scanned `sys.modules` for a module whose `__file__` is the tool, found
    nothing (because `importlib.util.module_from_spec` registers nothing) and
    left the full 2035 bytes landing on the live log - green fixture, zero
    effect. The arm that works is the one that looks at test-module
    ATTRIBUTES. This proves that arm still works, using a synthetic copy so
    nothing executes the real tool.
    """
    tool_path = (REPO_ROOT / "tools" / "cost_health_watchdog.py").resolve()
    assert tool_path.exists(), f"{tool_path} - the census names this producer"

    holder = types.ModuleType("_rm406_finder_probe_holder")
    planted = types.ModuleType("_rm406_finder_probe_copy")
    planted.__file__ = str(tool_path)
    holder.some_attribute_name = planted
    sys.modules[holder.__name__] = holder
    try:
        found = list(rc_conftest._iter_loaded_copies(tool_path))
    finally:
        del sys.modules[holder.__name__]
    assert any(mod is planted for mod in found), (
        "conftest._iter_loaded_copies no longer finds a module reachable only "
        "as an ATTRIBUTE of another module. That is exactly the shape "
        "`spec_from_file_location` produces, so the cost_health_watchdog "
        "redirect would silently reach nothing.")


def test_prod_write_globals_are_also_redirected():
    """The pre-existing RF5 table, re-asserted from the same place as the new
    ones. It was never proven armed at runtime before - only assumed."""
    failures = _check_prod_write_globals()
    assert not failures, "; ".join(failures)
