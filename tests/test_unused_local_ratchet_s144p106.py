"""RM-1406 - an assigned-but-never-read local is dropped, and a ratchet holds it.

ruff.toml ignores F841 ("noisy in callbacks"), so nothing stopped a dead
assignment from landing. Measured 2026-11-04 with ``ruff check --select F841``:
56 unused locals in 41 files. Ten production modules carried 15 of them, every
one the leftover of a removed read (a ``lane_partner`` loop whose result nothing
used, a ``has_sustain`` flag no branch tested, an ``aram_tip`` the SR prompt
deliberately omits, ``vs_tanks`` / ``vs_healing`` fields read and dropped,
dead ``my_d`` / ``opp_d`` death sums). A dead local reads as logic: the next
editor assumes the value reaches the output. Those ten are cleaned (FIXED).
The rest are in the shrinking _BASELINE (rel path -> count): frozen files, files
another lane branch changed, and test or probe scaffolding.

The ratchet:

- a FIXED module carries no unused local again;
- any other tracked .py with an unused local fails unless _BASELINE lists it,
  and a listed file may not gain one (its count may not rise);
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
    "coach_integration/_coach.py",
    "coach_integration/_sr_prompt.py",
    "coaches/brawl_coach.py",
    "composition_advisor.py",
    "dashboard/_liveclient.py",
    "dashboard/builders_last_match.py",
    "scripts/rewind_scraper.py",
    "tools/daemon_slayer_pickban_targets_generate.py",
    "tools/ds_cc_output_build.py",
    "tools/phase_watcher.py",
    "agents/agent3_testing/suite/test_round34.py",
    "agents/agent3_testing/suite/test_round35.py",
    "agents/agent3_testing/suite/test_round36.py",
    "agents/agent3_testing/suite/test_round37.py",
    "agents/agent3_testing/suite/test_round38.py",
    "agents/daemon_slayer/tests/test_ability_resolution_p1l20.py",
    "agents/daemon_slayer/tests/test_block_index_overrides.py",
    "agents/daemon_slayer/tests/test_effects_expansion.py",
    "agents/daemon_slayer/tests/test_ehp_shield_phase15.py",
    "agents/daemon_slayer/tests/test_rank_enchanter.py",
    "agents/daemon_slayer/tests/test_rank_offclass_win_exempt.py",
    "tests/phase2_smoke/test_snapshot_translation.py",
    "tests/phase8_smoke/test_sr_user_builds.py",
    "tests/snapshot_panels/test_spike_curve.py",
    "tests/test_aram_balance_grid.py",
    "tests/test_b4_shadow_match_id.py",
    "tests/test_data_retention.py",
    "tests/test_historical_pgr_dom.py",
    "tests/test_overlay_settings_panel_dom.py",
    "tests/test_routes_build_order.py",
    "tests/test_routes_cc_blended_ehp_threat.py",
    "tests/test_routes_cc_conditional_pressure.py",
    "tests/test_routes_peel_priority.py",
    "tests/test_snowball_elasticity.py",
    "tests/test_tft_coach_engine_audit.py",
    "tests/test_vision_atlas_precompute.py",
)

# rel path -> number of unused locals it may keep. Only shrinks.
# Frozen: core/log_setup.py, lcu/lcu_client.py. agents/daemon_slayer/ability_dps.py
# keeps a dead `true_score` for the next DS batch. RM-1676 cleaned the 26 test
# modules that were baselined here (now in FIXED). RM-1539 cleaned tools/ddragon_mirror_refresh.py, the
# dsv5 probe script and performance_tracker.py (an unread _identify_comp call).
_BASELINE = {
    "agents/daemon_slayer/ability_dps.py": 1,
    "core/log_setup.py": 1,
    "lcu/lcu_client.py": 1,
}


def _unused_locals_by_file() -> dict[str, int]:
    """rel path -> number of F841 findings (the config ignores the rule, so select it)."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F841",
         "--no-fix", "--no-cache", "--output-format", "json", "."],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    out: dict[str, int] = {}
    for d in json.loads(proc.stdout):
        if d["code"] != "F841":
            continue
        rel = Path(d["filename"]).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        if rel in tracked:
            out[rel] = out.get(rel, 0) + 1
    return out


@pytest.fixture(scope="module")
def found() -> dict[str, int]:
    return _unused_locals_by_file()


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_has_no_unused_local(found, rel):
    assert rel not in found, f"{rel} carries {found.get(rel)} unused local(s) again (RM-1406)"


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_no_unused_local_outside_the_baseline(found):
    new = sorted(set(found) - set(_BASELINE))
    assert not new, f"unused local in {new}: drop the assignment (or use the value)"


def test_a_baselined_file_gains_no_unused_local(found):
    grew = {rel: (n, found[rel]) for rel, n in _BASELINE.items() if found.get(rel, 0) > n}
    assert not grew, f"unused locals rose (baseline, now): {grew}"


def test_baseline_only_shrinks(found):
    healed = {rel: (n, found.get(rel, 0)) for rel, n in _BASELINE.items() if found.get(rel, 0) < n}
    assert not healed, f"fewer unused locals than baselined, lower or drop (baseline, now): {healed}"


def test_baseline_entries_are_tracked_files():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel


def test_the_fixed_set_and_baseline_are_disjoint():
    assert not set(FIXED) & set(_BASELINE)


def test_the_probe_is_not_vacuous(found):
    # The baseline is non-empty by construction, so an empty result means the
    # ruff run or the tracked-file filter broke, not that the tree is clean.
    assert found, "ruff reported no F841 at all - the probe is broken"
