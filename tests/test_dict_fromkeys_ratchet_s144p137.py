"""RM-1525 - ruff C420 (a dict comprehension that is `dict.fromkeys`) is held at a baseline
that only shrinks.

C420 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target
py39): production code carried 29 sites in 21 modules outside the owned paths below, every one
``{k: <constant> for k in <iterable>}`` with an immutable value (0, 0.0, False, None, or a
module constant that is an int). ``dict.fromkeys(it, v)`` builds the same dict in the same key
order; it would be WRONG for a mutable value (every key would share one object), which is why
ruff only flags the constant form and why this ratchet does not widen to the unsafe fixes.

The baseline is the findings that stay because someone else owns the file: the vendored fleet
kit (byte-pinned to MAIN's MANIFEST) and the frozen ``app/_game_lifecycle.py``. The two modules
once held for another lane branch (``tools/daemon_slayer_wiki_stats_extract.py``,
``tools/upstream_drift_check.py``) were fixed in RM-1699 after that lane stopped touching them. A baseline entry
that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding
anywhere else fails ``test_no_new_findings``.

Scope: production code. ``tests/``, ``tools/tests/``, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope. The
run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("C420",)
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE = {
    "app/_game_lifecycle.py": 1,
    "ops/fleet_kit/fleet_board.py": 2,
}
_FIXED = (
    "agents/agent2_backend/db_migrate_kda.py",
    "core/build_planner/kit_synergy.py",
    "core/damage_mix.py",
    "core/district_fusion.py",
    "core/obs_publisher.py",
    "core/opening_tendency.py",
    "core/ops_panels.py",
    "core/self_cast_log.py",
    "core/ward_events.py",
    "ops/audit/lolmath_ds_sweep/g7_comp_harness.py",
    "scripts/postmortem_analyze.py",
    "scripts/tft_patch_delta.py",
    "tft/cv/layout.py",
    "tools/aram_raw_replay.py",
    "tools/champion_loadout_invariants.py",
    "tools/daemon_slayer_cdragon_ratio_extract.py",
    "tools/daemon_slayer_wiki_stats_extract.py",
    "tools/gated_g246_killer_readers.py",
    "tools/gated_lx01_draft_check.py",
    "tools/gated_lx09_mark_check.py",
    "tools/slice_orchestrator.py",
    "tools/upstream_drift_check.py",
    "vision_server/_stats.py",
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
                  stdin="def f(keys):\n    return {k: 0 for k in keys}\n")
    assert {d["code"] for d in found} == set(_RULES), found


def test_fromkeys_equals_the_comprehension():
    """The premise of the fix: same keys, same order, same values, a fresh dict per call."""
    for keys in ((), ("a",), ("b", "a", "c"), ("a", "a", "b")):
        for value in (0, 0.0, False, None):
            assert dict.fromkeys(keys, value) == {k: value for k in keys}  # noqa: C420 - premise
            assert list(dict.fromkeys(keys, value)) == list({k: value for k in keys})  # noqa: C420 - premise
    a, b = dict.fromkeys(("x",), 0), dict.fromkeys(("x",), 0)
    a["x"] += 1
    assert b == {"x": 0}
