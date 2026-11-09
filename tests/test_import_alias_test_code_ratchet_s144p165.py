"""RM-1682 - ruff PLR0402 (``import a.b as b`` where ``from a import b`` says the same) is held at zero in the test code.

PLR0402 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120``
(target py39): 71 findings in 50 modules under ``tests/``, ``agents/daemon_slayer/tests/`` and
``tools/tests/``, all fixed to ``from a import b``.

Equivalence: ``import a.b as b`` binds ``sys.modules["a.b"]``; ``from a import b`` binds ``getattr(a, "b")``
after importing ``a.b`` if the attribute is missing. They differ only when the package ``__init__`` rebinds
``b`` to something that is not the submodule (a re-exported function of the same name, say), which would
silently change which object the test patches. ``test_every_fixed_pair_binds_the_submodule`` measures that
for every distinct (package, module) pair that was rewritten: the attribute IS the sys.modules entry. The run
uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. No baseline.
"""
from __future__ import annotations

import collections
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

_RULES = ("PLR0402",)
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
_FIXED = (
    "agents/daemon_slayer/tests/test_aa_empower_authored_item258.py",
    "agents/daemon_slayer/tests/test_anivia_egg_resist_item316.py",
    "agents/daemon_slayer/tests/test_item_aa_damage_reduction_r80.py",
    "agents/daemon_slayer/tests/test_item_crit_damage_reduction_r77.py",
    "agents/daemon_slayer/tests/test_item_enemy_as_slow_r86.py",
    "agents/daemon_slayer/tests/test_missing_hp_heal_amp_item515.py",
    "agents/daemon_slayer/tests/test_passive_damage_per_stack_item249.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_as_aware_item253.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_item250.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_linear_item251.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_linear_reopen_item254.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_per_charge_item252.py",
    "agents/daemon_slayer/tests/test_passive_mitigation_overrides_item261.py",
    "agents/daemon_slayer/tests/test_passive_mitigation_snapshot_r35.py",
    "agents/daemon_slayer/tests/test_passive_resist_overrides_item264.py",
    "agents/daemon_slayer/tests/test_passive_resist_per_stack_item272.py",
    "agents/daemon_slayer/tests/test_passive_revive_overrides_item288.py",
    "agents/daemon_slayer/tests/test_passive_shield_overrides_item260.py",
    "agents/daemon_slayer/tests/test_passive_survival_window_overrides_item293.py",
    "agents/daemon_slayer/tests/test_phantom_residual_2026_05_31.py",
    "agents/daemon_slayer/tests/test_stacking_pct_resist_reduction_drift.py",
    "agents/daemon_slayer/tests/test_target_vulnerability_overrides_r12.py",
    "agents/daemon_slayer/tests/test_target_vulnerability_overrides_r43.py",
    "agents/daemon_slayer/tests/test_unique_passive_strongest_wins.py",
    "tests/test_aram_coach_item_interaction_wiring.py",
    "tests/test_cc_conditional_impact_context.py",
    "tests/test_control_endpoint_auth.py",
    "tests/test_cwd_relative_data_paths_s144q11.py",
    "tests/test_dead_endpoint_cleanup_item186.py",
    "tests/test_dead_symbols_rm195.py",
    "tests/test_docs_api_error_shapes_s144d66.py",
    "tests/test_docs_ds_key_data_types_s144d05.py",
    "tests/test_gen_archmap_atomic_write_rm258.py",
    "tests/test_guard_data_split_rc2.py",
    "tests/test_inbox_reported_record.py",
    "tests/test_loop_audit_range.py",
    "tests/test_p2w1_core_f.py",
    "tests/test_phase3_setup_rerun_bytes_rm820.py",
    "tests/test_poller_lane8_cycle14.py",
    "tests/test_poller_true_audit_s144.py",
    "tests/test_rc_facts_atomic_writers_rm258.py",
    "tests/test_rc_facts_lcu_phase_rm462.py",
    "tests/test_rc_facts_missed_run_skip_s147.py",
    "tests/test_rc_facts_port_probe.py",
    "tests/test_rc_facts_task_health.py",
    "tests/test_relay_age_backward_step_rm269.py",
    "tests/test_rm413_wal_pragma_result_checked.py",
    "tests/test_rm750_ds_keepalive.py",
    "tests/test_rm835_dashboard_reply_scrub.py",
    "tests/test_rm838_reply_scrub_non_ds.py",
)

_PAIRS = (
    ("agents", "daemon_slayer"),
    ("agents.agent2_backend", "win_reconcile"),
    ("agents.daemon_slayer", "combo"),
    ("agents.daemon_slayer", "dps"),
    ("agents.daemon_slayer", "ehp"),
    ("coaches", "aram_coach"),
    ("core", "decision_detector"),
    ("core", "draft_elo_db"),
    ("core", "ds_support_route_overrides"),
    ("core", "hotkeys"),
    ("core", "item_wpa"),
    ("core", "polled_json"),
    ("core", "post_game_rubric"),
    ("core", "post_game_score"),
    ("core", "riot_api_cache"),
    ("core", "rune_wpa"),
    ("core", "skill_wpa"),
    ("core", "summoner_spell_wpa"),
    ("core", "theme"),
    ("core", "vision_token"),
    ("dashboard", "_dispatch"),
    ("dashboard", "api_schema"),
    ("dashboard", "routes_personal_vs"),
    ("dashboard", "routes_pickban"),
    ("dashboard", "routes_recordings"),
    ("game_reader", "poller"),
    ("lib", "rewind_live_writer"),
    ("modules", "cache_engine"),
    ("ops", "phase3_setup"),
    ("scripts", "rewind_catchup"),
    ("scripts", "rewind_scraper"),
    ("tests", "guard_data"),
    ("tools", "rc_facts"),
    ("unittest", "mock"),
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    assert any(rel.startswith(_TEST_DIRS) for rel in tracked), "no tracked test module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_TEST_DIRS):
            counts[rel] += 1
    return dict(counts)


def test_no_plr0402_finding_in_the_test_code(tree_counts):
    assert not tree_counts, f"ruff {_RULES} findings in the test code, file: count: {tree_counts}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize(("package", "name"), _PAIRS)
def test_every_fixed_pair_binds_the_submodule(package, name):
    """The equivalence premise: the package attribute is the very module `import a.b as b` would bind."""
    module = importlib.import_module(f"{package}.{name}")
    assert getattr(importlib.import_module(package), name) is module
    assert sys.modules[f"{package}.{name}"] is module


def test_probe_is_live():
    """The rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = "import os.path as path\n"
    good = "from os import path\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
