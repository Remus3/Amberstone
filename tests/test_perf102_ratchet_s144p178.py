"""RM-1693 - ruff PERF102 (a dict iterated with .items() while only its keys or only its values are read) is held at zero outside the DS package.

PERF102 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39): 24
findings outside ``agents/daemon_slayer/`` - 21 in 14 modules (12 test modules, ``tools/ddragon_mirror_refresh.py``
and ``tools/daemon_slayer_wiki_ability_extract.py``) fixed here, one in the vendored kit
(``ops/fleet_kit/fleet_claims.py``, MAIN's, never edited locally) and two in
``tests/test_rank_tier_live_budget.py``, a file the ``lane/queue`` branch changes (baselined, so the set only
shrinks). ``for k, v in d.items()`` with an unused ``k`` becomes ``for v in d.values()``; an unused ``v`` becomes
``for k in d`` (or a tuple key unpacked straight from the dict). The engine package and its tests,
``agents/daemon_slayer/``, hold 57 more findings (25 test modules plus scenario_matrix.py; a ds-lane FILING, not touched here).

Equivalence: ``.values()`` / key iteration yields exactly the objects ``.items()`` paired with the dropped
name, in the same insertion order, and no rewritten loop adds or removes a key of the dict it walks. The run
uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULE = "PERF102"
_OUT_OF_SCOPE = ("agents/daemon_slayer/", "ops/fleet_kit/")
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE = {"tests/test_rank_tier_live_budget.py": 2}  # lane/queue changes this file
_FIXED = (
    "tests/test_arena_auto_flavor_mage_rm16.py",
    "tests/test_arena_mage_mislabel_item273.py",
    "tests/test_champion_loadout_collapse_aram_arena.py",
    "tests/test_champion_loadout_collapse_to_paths.py",
    "tests/test_champion_loadouts_no_unique_clash.py",
    "tests/test_dict_items_test_code_ratchet_s144p169.py",
    "tests/test_edge_watcher_p24.py",
    "tests/test_laning_scenario_precompute.py",
    "tests/test_pickban_targets.py",
    "tests/test_smoothed_rates_101qq.py",
    "tests/test_thin_aram_adc_item275.py",
    "tests/test_vision_atlas_validate.py",
    "tools/daemon_slayer_wiki_ability_extract.py",
    "tools/ddragon_mirror_refresh.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_perf102_finding_outside_the_ds_package(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"ruff {_RULE} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline row still offends with its exact count; a row that no longer does must be dropped."""
    assert {rel: tree_counts.get(rel, 0) for rel in _BASELINE} == _BASELINE


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


_PROBES = (
    "def f(d):\n    for k, v in d.items():\n        print(v)\n",
    "def f(d):\n    for k, v in d.items():\n        print(k)\n",
)


@pytest.mark.parametrize("probe", _PROBES)
def test_probe_is_live(probe):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {_RULE}


def test_values_and_key_iteration_match_items_in_order():
    d = {"b": 2, "a": 1, "c": 3}
    assert [v for _k, v in d.items()] == list(d.values())
    assert [k for k, _v in d.items()] == list(d)
    pairs = {("x", 1): 0, ("y", 2): 0}
    assert [(a, b) for (a, b), _ in pairs.items()] == [(a, b) for a, b in pairs]
