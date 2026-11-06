"""RM-1753 - ruff SIM102 (a nested ``if`` that is the only statement of its parent ``if``) held at a shrink-only baseline.

Measured 2026-11-06 with ``ruff check --isolated`` (target py39): 42 findings outside the DS tree and the vendored
kit. Twelve are now one ``if A and B:`` each, in four production modules (``composition_advisor.py`` x5,
``role_profiles.py`` x2, ``core/config_validator.py`` x3, ``core/vision_fusion.py`` x2). Every site had no ``else`` on
either ``if``, so the merged condition runs the same body for exactly the same inputs, and ``and`` short-circuits in
the same order the nested form evaluated its tests.

A second slice (RM-1754) merged 8 more, one per module in ``core/`` x5 and ``vision_server/`` x3; the merge
kept every ``and`` operand in the nested form's order, and only the ``elif state == STOPPED`` site in
``core/obs_recorder.py`` moved a nested ``if`` into an ``elif`` test, where its chain has no later branch.

The other 22 are the baseline below: one frozen file (``ops/rc_supervisor.py``), one file the uiux lane's branch
changes (``agents/agent5_ui/champion_fallback.py``) and the rest left for later slices. The count per file can only
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

_RULE = "SIM102"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "agents/daemon_slayer/": "the DS lane's tree",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE = {
    "agents/agent2_backend/migration_rewind.py": 1,
    "agents/agent5_ui/champion_fallback.py": 1,
    "coach_integration/_sr_prompt.py": 1,
    "dashboard/_handler.py": 1,
    "game_reader/snapshot_normalizer.py": 1,
    "item_advisor.py": 1,
    "ops/rc_self_monitor.py": 3,
    "ops/rc_supervisor.py": 2,
    "scripts/fetch_cdragon_pbe.py": 1,
    "tft/tft_coach_engine.py": 1,
    "tools/champion_loadout_align.py": 2,
    "tools/champion_loadout_cleanup_pollution_item213.py": 2,
    "tools/champion_loadout_collapse_to_paths.py": 1,
    "tools/ds_cdragon_drift_audit.py": 1,
    "tools/gated_g232_layout_diff.py": 1,
    "tools/package_portable.py": 1,
    "tools/upstream_drift_check.py": 1,
}
_FIXED = (
    "composition_advisor.py",
    "role_profiles.py",
    "core/config_validator.py",
    "core/vision_fusion.py",
    "core/branch_review.py",
    "core/decision_detector.py",
    "core/live_benchmark_band_shadow.py",
    "core/obs_recorder.py",
    "core/session_hygiene.py",
    "vision_server/_frame.py",
    "vision_server/_inference.py",
    "vision_server/_relay.py",
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
    block = "if x:\n    if y:\n        z = 1\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=block)
    assert any(d["code"] == _RULE for d in found), [d["code"] for d in found]


def test_the_merged_condition_form_is_not_reported():
    """The form the sweep applied is the one SIM102 accepts, so the held scope cannot be satisfied vacuously."""
    assert not _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin="if x and y:\n    z = 1\n")
