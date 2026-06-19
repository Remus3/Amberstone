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


# RF5 suite-wide regression assert: no test may mutate a production
# coaching / loop / in-game artifact across the whole session. These paths are
# written ONLY by a live coach, the headless loop, or an in-game detector, so
# they stay byte-stable during an offline test run; any size change means a
# test wrote a prod path instead of tmp (the exact OPEN2 / RF5 regression).
# Scoped to artifacts the idle-client daemon never touches - health.json,
# logs/, lessons_*, and bridge_monitor are excluded because the live supervisor
# + cross-Claude bridge legitimately tick those during a run.
_PROD_ARTIFACT_GUARD = (
    "ops/loop/control/controller.log",
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
)
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _prod_artifact_sizes() -> dict:
    out = {}
    for rel in _PROD_ARTIFACT_GUARD:
        p = _REPO_ROOT / rel
        out[rel] = p.stat().st_size if p.exists() else None
    return out


@pytest.fixture(scope="session", autouse=True)
def assert_prod_artifacts_unchanged():
    before = _prod_artifact_sizes()
    yield
    after = _prod_artifact_sizes()
    changed = [
        rel + " " + str(before[rel]) + "->" + str(after[rel])
        for rel in _PROD_ARTIFACT_GUARD
        if before[rel] != after[rel]
    ]
    assert not changed, (
        "suite mutated a production artifact - a test wrote a prod path "
        "instead of tmp (RF5 hermeticity regression): " + "; ".join(changed)
    )
