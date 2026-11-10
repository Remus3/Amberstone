"""S144-P-661 - ruff D413 (no blank line after the last docstring section) is held at a shrink-only baseline.

D413 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 46 findings in 41 files, every one a docstring whose last section (Returns / Args /
Parameters / Examples) runs straight into the closing quotes. Twelve production modules (12 findings:
agent2_backend/pipeline/orchestrator, coach_integration/enemy_stats, coaches/aram_team_analyzer,
coaches/champ_select_coach, coaches/loadout_resolver, core/anthropic_client, core/aram_coach_shadow,
core/arena_coach_shadow, core/coaching_timestamps, core/district_fusion, lcu/lcu_pregame,
ops/rc_transactional_deploy) got the one blank line ruff asks for - whitespace inside a docstring only, no token
changes outside a string, so behaviour and every line cite by symbol are unchanged.

A second slice (S144-P-662) gave ten more core modules (aram_deterministic_coach, arena_augment_playline,
arena_deterministic_coach, decision_detector, event_callouts, feature_policy, heal_threat, macro_context,
macro_response, obj_participation) the same one blank line.

Not touched, and named in ``_BASELINE`` with their counts (24 sites in 19 files), so the baseline drains in later
slices or when the owner lands:

- ``agents/daemon_slayer/`` and ``core/ds_*`` carry the ds lane's engine tree and its unlanded edits.
- ``tools/ds_cdragon_drift_audit.py`` is the ds lane's tool.
- The rest are small production modules left for a later slice (one finding each, mostly).

``ops/fleet_kit/`` is vendored byte-for-byte and pinned by its MANIFEST, so it is not scanned. The run uses NO
config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline only shrinks.
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

_RULES = ("D413",)
_VENDORED = "ops/fleet_kit/"
# file -> finding count. The baseline only shrinks: a new finding fails, and an entry that stops offending (or
# offends less) fails test_baseline_is_exact.
_BASELINE = {
    "agents/daemon_slayer/_item_proc_heal.py": 1,
    "agents/daemon_slayer/ability_dps.py": 1,
    "agents/daemon_slayer/effects.py": 2,
    "agents/daemon_slayer/geometry.py": 3,
    "agents/daemon_slayer/missile.py": 1,
    "agents/daemon_slayer/recharge_ledger.py": 1,
    "core/ds_antitank_hint.py": 1,
    "core/ds_calibration.py": 1,
    "core/ds_capability_gap.py": 1,
    "core/ds_scaling_hint.py": 1,
    "core/objective_playbook.py": 1,
    "core/post_game_rubric.py": 1,
    "core/post_game_score.py": 1,
    "core/precomputed_replay_narrative.py": 1,
    "core/replay_narrative_shadow.py": 1,
    "core/vision_fusion.py": 1,
    "dashboard/_deterministic_coaching.py": 2,
    "dashboard/builders_last_match.py": 2,
    "tools/ds_cdragon_drift_audit.py": 1,
}


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
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_VENDORED):
            counts[rel] += 1
    return dict(counts)


def test_no_new_d413_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"ruff {_RULES} findings above the baseline, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends at its recorded count; one that shrank must be lowered or dropped."""
    stale = {rel: (n, tree_counts.get(rel, 0)) for rel, n in _BASELINE.items() if tree_counts.get(rel, 0) != n}
    assert not stale, f"baseline file: (recorded, measured): {stale}"


def test_probe_is_live():
    """D413 reports a last section glued to the closing quotes and stays quiet once a blank line follows it."""
    bad = 'def f():\n    """Doc.\n\n    Returns:\n        int\n    """\n    return 1\n'
    good = 'def f():\n    """Doc.\n\n    Returns:\n        int\n\n    """\n    return 1\n'
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
