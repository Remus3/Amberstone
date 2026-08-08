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

import importlib
from pathlib import Path
from unittest import mock

import pytest

_SHADOW_MODULES = (
    "core.hz_choice_shadow",
    "core.hz_build_shadow",
    "core.det_coach_shadow",
    "core.live_benchmark_band_shadow",
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
        if hasattr(mod, "SHADOW_PATH"):
            fname = mod_name.rsplit(".", 1)[-1] + ".jsonl"
            monkeypatch.setattr(mod, "SHADOW_PATH", tmp_path / "shadow" / fname)


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
_REPO_ROOT = Path(__file__).resolve().parents[1]

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
