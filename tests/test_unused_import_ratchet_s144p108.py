"""RM-1408 - an unused import is dropped from twelve modules, and a ratchet holds it.

ruff.toml ignores F401 ("too noisy, especially in __init__.py"), so nothing stopped
a dead import from landing. Measured 2026-11-04 with ``ruff check --select F401
--isolated``: 242 unused imports in 118 files; 156 of them in 66 production
modules (outside tests, audit probes, the vendored kit and ``__init__.py``).
Twelve production modules carried 23 of them, every one the leftover of a removed
use and none of it a re-export: no tracked file reads ``<module>.<name>`` or
imports the name from it (``supervisor`` alone held ten, among them
``http.server``, ``socket``, ``re``, ``sys`` and the ``Agent0Task`` /
``TaskStatus`` aliases). A dead import reads as a dependency: the next editor
assumes the module still needs ``socket`` or ``uuid``. Those twelve are cleaned
(FIXED).

RM-1409 cleans twelve more stdlib leftovers (one each, in coaches, core,
dashboard, game_reader, ops and tools; none re-exported, none patched by name in
a test) and moves them from _BASELINE to FIXED.

The rest are in the shrinking _BASELINE (rel path -> count): frozen files, files
another lane branch changed, the DS engine (lane ds), deliberate facades
(``coaches/adaptation_hint.py`` re-exports its split modules, ``effects.py`` its
types) and stdlib leftovers a later slice drops. ``__init__.py`` re-exports stay
out of scope, as does test code.

The ratchet:

- a FIXED module carries no unused import again;
- any other in-scope tracked .py with an unused import fails unless _BASELINE
  lists it, and a listed file may not gain one (its count may not rise);
- a _BASELINE entry whose count dropped fails until it is lowered or dropped.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

FIXED = (
    "agents/agent1_lead/scheduler.py",
    "agents/agent2_backend/pipeline/orchestrator.py",
    "agents/supervisor.py",
    "coach_integration/_coach.py",
    "coaches/experimental_builder.py",
    "coaches/loadout_resolver.py",
    "coaches/replay_coach.py",
    "coaches/voice_coach.py",
    "core/benchmarks.py",
    "core/decision_detector.py",
    "core/feature_policy.py",
    "core/metrics_cache.py",
    "core/replay_history.py",
    "dashboard/_state_builder.py",
    "dashboard/routes_duo_synergy.py",
    "dashboard/routes_recordings.py",
    "game_reader/poller.py",
    "modes/shared_vision.py",
    "ops/loop/claude_stub.py",
    "ops/loop/done_sentinel.py",
    "ops/rc_incident_log.py",
    "tools/bootstrap_env_check.py",
    "tools/live_flip_watcher.py",
    "tools/start_daemon_slayer.py",
)

# Out of scope: test code, audit probes, the byte-pinned vendored kit and package
# re-export modules.
_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/", "ops/audit/", "agents/agent3_testing/")

# rel path -> number of unused imports it may keep. Only shrinks.
_BASELINE = {
    "agents/agent2_backend/migration_rewind.py": 1,
    "agents/daemon_slayer/_effects_data.py": 1,
    "agents/daemon_slayer/_effects_types.py": 1,
    "agents/daemon_slayer/_registries.py": 1,
    "agents/daemon_slayer/ability_dps.py": 10,
    "agents/daemon_slayer/beam.py": 1,
    "agents/daemon_slayer/burst.py": 2,
    "agents/daemon_slayer/cc_pressure.py": 1,
    "agents/daemon_slayer/effects.py": 9,
    "agents/daemon_slayer/scenario_matrix.py": 1,
    "agents/daemon_slayer/self_shred.py": 1,
    "agents/daemon_slayer/server.py": 1,
    "app/_game_lifecycle.py": 2,
    "coaches/_adaptation_common.py": 1,
    "coaches/adaptation_hint.py": 33,
    "coaches/adaptation_hint_cli.py": 1,
    "composition_advisor.py": 7,
    "core/build_order_variants.py": 1,
    "core/log_setup.py": 2,
    "core/rofl_stats_backfill.py": 2,
    "dashboard/_dispatch.py": 1,
    "dashboard/_writers.py": 1,
    "dashboard/routes_loadout.py": 1,
    "dashboard/routes_lobby_aux.py": 1,
    "dashboard/routes_replay_events.py": 1,
    "ops/loop/lanes.py": 1,
    "scripts/build_carry_benchmarks.py": 1,
    "scripts/build_champion_benchmarks.py": 2,
    "scripts/install_hooks.py": 1,
    "scripts/merge_refresh_builds.py": 2,
    "tools/build_portable.py": 1,
    "tools/champion_loadout_align.py": 1,
    "tools/dev_cli.py": 1,
    "tools/ds_wiki_staleness_check.py": 2,
    "tools/gated_lx01_draft_check.py": 1,
    "tools/inbox_responder_runner.py": 1,
    "tools/lcu_agent.py": 1,
    "tools/replay_session.py": 1,
    "tools/run_phase2_perf.py": 1,
    "tools/session_steer.py": 1,
    "tools/validate_loadouts.py": 1,
    "web_dashboard.py": 18,
}


def _in_scope(rel: str) -> bool:
    return not (rel.startswith(_SKIP_PREFIXES) or "/tests/" in rel or rel.endswith("__init__.py"))


def _unused_imports_by_file() -> dict[str, int]:
    """rel path -> number of F401 findings in scope.

    ``--isolated`` drops ruff.toml, whose ``ignore`` carries F401 and whose
    per-file-ignores would otherwise hide a file; the tracked-file filter stands
    in for its ``exclude`` list.
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F401", "--isolated",
         "--target-version", "py39", "--no-fix", "--no-cache", "--output-format", "json", "."],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    out: dict[str, int] = {}
    for d in json.loads(proc.stdout):
        if d["code"] != "F401":
            continue
        rel = Path(d["filename"]).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        if rel in tracked and _in_scope(rel):
            out[rel] = out.get(rel, 0) + 1
    return out


@pytest.fixture(scope="module")
def found() -> dict[str, int]:
    return _unused_imports_by_file()


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_has_no_unused_import(found, rel):
    assert rel not in found, f"{rel} carries {found.get(rel)} unused import(s) again (RM-1408)"


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_no_unused_import_outside_the_baseline(found):
    new = sorted(set(found) - set(_BASELINE))
    assert not new, f"unused import in {new}: drop it (or re-export it with a noqa that says why)"


def test_a_baselined_file_gains_no_unused_import(found):
    grew = {rel: (n, found[rel]) for rel, n in _BASELINE.items() if found.get(rel, 0) > n}
    assert not grew, f"unused imports rose (baseline, now): {grew}"


def test_baseline_only_shrinks(found):
    healed = {rel: (n, found.get(rel, 0)) for rel, n in _BASELINE.items() if found.get(rel, 0) < n}
    assert not healed, f"fewer unused imports than baselined, lower or drop (baseline, now): {healed}"


def test_baseline_entries_are_tracked_and_in_scope():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel
        assert _in_scope(rel), rel


def test_the_fixed_set_and_baseline_are_disjoint():
    assert not set(FIXED) & set(_BASELINE)


def test_the_probe_is_not_vacuous(found):
    # The baseline is non-empty by construction, so an empty result means the
    # ruff run or the tracked-file filter broke, not that the tree is clean.
    assert found, "ruff reported no F401 at all - the probe is broken"


def test_scope_filter_keeps_production_and_drops_tests_and_packages():
    assert _in_scope("core/benchmarks.py")
    assert _in_scope("tools/lcu_agent.py")
    assert not _in_scope("tests/test_x.py")
    assert not _in_scope("agents/daemon_slayer/tests/test_x.py")
    assert not _in_scope("core/__init__.py")
    assert not _in_scope("ops/fleet_kit/fleet_gitlock.py")
