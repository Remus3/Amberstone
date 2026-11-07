"""RM-1410 - an unused loop-control variable is dropped, and a ratchet holds it.

ruff.toml ignores B007 ("intentional in callbacks"), so nothing stopped
``for k, v in d.items()`` whose body never reads ``k`` (or an ``enumerate`` index
nothing uses) from landing. Measured 2026-11-04 with ``ruff check --select B007``:
75 loop-control variables in 52 files. Fourteen production modules carried 16 of
them; each is dropped (``.values()`` / a bare loop target) or renamed with a
leading underscore, and one (tools/ds_cross_eval/probe_champion.py) was a
``for slot in range(6): pass`` loop that did nothing at all. A loop target that
looks bound reads as if the body used it; the next editor trusts it.

The ratchet:

- a FIXED module carries no B007 finding again;
- any other tracked .py with one fails unless _BASELINE lists it, and a listed
  file may not gain one (its count may not rise);
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
    "core/augment_recommender.py",
    "core/decision_detector.py",
    "dashboard/builders_home.py",
    "dashboard/routes_pickban.py",
    "lcu/lcu_postgame_collector.py",
    "tft/cv/ocr_fields.py",
    "tools/build_third_party_notices.py",
    "tools/champion_loadout_align.py",
    "tools/champion_loadout_autogen.py",
    "tools/champion_loadout_cleanup_pollution_item213.py",
    "tools/ds_cc_conditional_to_json.py",
    "tools/ds_cross_eval/probe_champion.py",
    "tools/gated_lx05_tape_check.py",
    "tools/strip_smart_quotes.py",
)

# rel path -> number of B007 findings it may keep. Only shrinks. Test scaffolding
# (the DS tests belong to lane ds).
_BASELINE = {
    "agents/daemon_slayer/tests/test_ability_resolution_p1l20.py": 1,
    "agents/daemon_slayer/tests/test_allyamp_item304.py": 1,
    "agents/daemon_slayer/tests/test_antitank_item308.py": 1,
    "agents/daemon_slayer/tests/test_cc_conditional_wave20.py": 1,
    "agents/daemon_slayer/tests/test_cc_conditional_wave21.py": 8,
    "agents/daemon_slayer/tests/test_cc_conditional_wave22.py": 5,
    "agents/daemon_slayer/tests/test_cc_output_item294.py": 1,
    "agents/daemon_slayer/tests/test_extendedduel_item309.py": 1,
    "agents/daemon_slayer/tests/test_mobility_item297.py": 1,
    "agents/daemon_slayer/tests/test_objdamage_item303.py": 1,
    "agents/daemon_slayer/tests/test_passive_heal_overrides_per_charge_item252.py": 1,
    "agents/daemon_slayer/tests/test_per_spell_cc_registry_wave2.py": 1,
    "agents/daemon_slayer/tests/test_scaling_item299.py": 2,
    "agents/daemon_slayer/tests/test_server_routes_p1l8.py": 1,
    "agents/daemon_slayer/tests/test_sustain_item298.py": 1,
    "agents/daemon_slayer/tests/test_threatrange_item301.py": 1,
    "agents/daemon_slayer/tests/test_waveclear_item300.py": 1,
    "agents/daemon_slayer/tests/test_zonecontrol_item302.py": 1,
}


def _findings_by_file() -> dict[str, int]:
    """rel path -> number of B007 findings (the config ignores the rule, so select it)."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "B007",
         "--no-fix", "--no-cache", "--output-format", "json", "."],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    out: dict[str, int] = {}
    for d in json.loads(proc.stdout):
        if d["code"] != "B007":
            continue
        rel = Path(d["filename"]).resolve().relative_to(REPO_ROOT.resolve()).as_posix()
        if rel in tracked:
            out[rel] = out.get(rel, 0) + 1
    return out


@pytest.fixture(scope="module")
def found() -> dict[str, int]:
    return _findings_by_file()


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_has_no_unused_loop_variable(found, rel):
    assert rel not in found, f"{rel} carries {found.get(rel)} unused loop variable(s) again (RM-1410)"


@pytest.mark.parametrize("rel", FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_no_unused_loop_variable_outside_the_baseline(found):
    new = sorted(set(found) - set(_BASELINE))
    assert not new, f"unused loop variable in {new}: iterate .values() / drop the target, or prefix it with _"


def test_a_baselined_file_gains_no_unused_loop_variable(found):
    grew = {rel: (n, found[rel]) for rel, n in _BASELINE.items() if found.get(rel, 0) > n}
    assert not grew, f"unused loop variables rose (baseline, now): {grew}"


def test_baseline_only_shrinks(found):
    healed = {rel: (n, found.get(rel, 0)) for rel, n in _BASELINE.items() if found.get(rel, 0) < n}
    assert not healed, f"fewer findings than baselined, lower or drop (baseline, now): {healed}"


def test_baseline_entries_are_tracked_files():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel


def test_the_fixed_set_and_baseline_are_disjoint():
    assert not set(FIXED) & set(_BASELINE)


def test_the_probe_is_not_vacuous(found):
    # The baseline is non-empty by construction, so an empty result means the
    # ruff run or the tracked-file filter broke, not that the tree is clean.
    assert found, "ruff reported no B007 at all - the probe is broken"
