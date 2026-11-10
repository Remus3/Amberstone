"""RM-1526 - ruff PERF102 (iterating `.items()` and using only the key or only the value) is
held at a baseline that only shrinks.

PERF102 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target
py39): production code carried 14 sites in 9 modules outside the owned paths below. Each was
``for _k, v in d.items()`` (or the nested ``for _a, (x, y) in d.items()`` unpack) where the
underscore name is never read; ``for v in d.values()`` yields the same objects in the same order
without building a (key, value) tuple per step. The fix is behaviour-neutral for any dict-like
that has ``values()`` and no side effect on iteration; ruff marks it an unsafe fix only because it
cannot see a custom ``items()``, and every receiver here is a plain dict or a ``Mapping``.

The baseline is the findings that stay because someone else owns the file: the vendored fleet kit
(byte-pinned to MAIN's MANIFEST) and two modules changed on another lane branch
(``tools/daemon_slayer_wiki_ability_extract.py``, ``tools/ddragon_mirror_refresh.py``; their
entries left once that lane's cd7fb1a5c fixed them). A baseline entry that stops offending fails
``test_baseline_is_exact`` until it is dropped; a new finding anywhere else fails
``test_no_new_findings``.

Scope: production code. ``tests/``, ``tools/tests/``, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope. The run
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

_RULES = ("PERF102",)
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE = {
    "ops/fleet_kit/fleet_claims.py": 1,
}
_FIXED = (
    "core/data_retention.py",
    "core/rune_wpa.py",
    "core/summoner_spell_wpa.py",
    "ops/audit/lolmath_ds_sweep/g5_pool_probe.py",
    "tools/champion_loadout_cleanup_pollution_item213.py",
    "tools/champion_loadout_invariants.py",
    "tools/daemon_slayer_abilities_extract.py",
    "tools/ds_cc_conditional_to_json.py",
    "tools/hotfix_ranged_only_melee_loadouts.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
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
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports minimal offenders, so an empty tree result is a real scan."""
    found = _ruff(["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"],
                  stdin="def f(d):\n    for _k, v in d.items():\n        print(v)\n")
    assert {d["code"] for d in found} == set(_RULES), found


def test_values_iteration_equals_items_iteration():
    """The premise of the fix: same objects, same order, including the nested unpack."""
    d = {"b": (1, True, [1]), "a": (2, False, [2]), "c": (3, True, [])}
    assert [v for _k, v in d.items()] == list(d.values())
    assert [(x, y, z) for _k, (x, y, z) in d.items()] == [(x, y, z) for x, y, z in d.values()]
    nested = {"p": {"q": 1, "r": 2}, "s": {"t": 3}}
    assert [c for _a, inner in nested.items() for _b, c in inner.items()] == [
        c for inner in nested.values() for c in inner.values()]
