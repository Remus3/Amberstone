"""RM-1751 - ruff SIM108 (if/else block that assigns one name) held at zero outside a named baseline.

Measured 2026-11-06 with ``ruff check --isolated`` (target py39): 16 findings outside the DS tree and the vendored
kit. Nine production sites are now one conditional expression each (``core/build_order.py``,
``core/minimap_geometry.py``, ``core/riot_api_cache.py``, ``core/ward_producer.py``, ``core/zoi_field.py``,
``coaches/sr_user_builds.py``, ``lcu/snapshot_shape.py``, ``tools/session_checklist.py``,
``tools/upstream_drift_check.py``). The condition, both arms and the arm that is evaluated are unchanged: a
conditional expression is as lazy as the block it replaces.

Six files are the named baseline, one finding each. They stay as they are this cycle and the count per file can only
fall: a file that reaches zero must leave ``_BASELINE``, and a new finding anywhere fails.

The held scope is every tracked ``.py`` file NOT under the two fences below. The run uses NO config (``--isolated``),
so a per-file-ignore cannot hide a finding.
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

_RULE = "SIM108"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "agents/daemon_slayer/": "the DS lane's tree",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE = {
    "agents/agent4_coach_mentor/analyzer.py": 1,
    "dashboard/_deterministic_coaching.py": 1,
    "docs/_rsc_score/tally_ab.py": 1,
    "tests/_replace_faults.py": 1,
    "tests/test_math_core_golden.py": 1,
    "tests/test_rank_tier_live_budget.py": 1,
}
_FIXED = (
    "coaches/sr_user_builds.py",
    "core/build_order.py",
    "core/minimap_geometry.py",
    "core/riot_api_cache.py",
    "core/ward_producer.py",
    "core/zoi_field.py",
    "lcu/snapshot_shape.py",
    "tools/session_checklist.py",
    "tools/upstream_drift_check.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULE} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_baseline_and_fences_name_real_paths():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _BASELINE:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
    for prefix in _NOT_THIS_SCOPE:
        assert (REPO_ROOT / prefix).is_dir(), prefix


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    block = "if x:\n    y = 1\nelse:\n    y = 2\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=block)
    assert any(d["code"] == _RULE for d in found), [d["code"] for d in found]


def test_the_conditional_expression_form_is_not_reported():
    """The form the sweep applied is the one SIM108 accepts, so the held scope cannot be satisfied vacuously."""
    assert not _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin="y = 1 if x else 2\n")
