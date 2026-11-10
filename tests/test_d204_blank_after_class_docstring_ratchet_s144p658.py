"""S144-P-658 - ruff D204 (no blank line after a class docstring) is held at a shrink-only baseline.

D204 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 77 findings in 43 files, every one a class whose docstring is followed directly by its first
statement. Ten production modules (23 findings) got the one blank line ruff asks for - whitespace only, no token
changes, so behaviour and every line cite by symbol are unchanged.

A second slice (S144-P-659, 2026-11-10) did the same for eight more small production modules (agent7_context x2,
coach_integration/enemy_stats, coaches/tft_coach, core/archetype_mismatch, config_validator, decision_detector,
liveclient_cache; 8 findings, whitespace only).

Not touched, and named in ``_BASELINE`` with their counts (43 sites in 24 files), because someone else owns them:

- ``core/game_snapshot.py`` is a frozen file (CLAUDE.md).
- ``ops/launcher/updater.py`` is PKG-owned (the lane exclusion list).
- ``agents/daemon_slayer/`` is the ds lane's engine tree.
- ``core/coaching_payload.py`` and ``dashboard/view_router_state.py`` carry another lane's unlanded edits.
- ``agents/agent0_gatekeeper/evaluator.py`` and ``core/damage_mix.py`` carry the true-audit lane's unlanded edits.
- the rest are test modules left for a later slice.

``ops/fleet_kit/`` is vendored byte-for-byte and pinned by its MANIFEST, so it is not scanned (three findings there, in one file).
The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline only shrinks.
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

_RULES = ("D204",)
_VENDORED = "ops/fleet_kit/"
# file -> finding count. The baseline only shrinks: a new finding fails, and an entry that stops offending (or
# offends less) fails test_baseline_is_exact.
_BASELINE = {
    "agents/agent0_gatekeeper/evaluator.py": 1,
    "agents/daemon_slayer/_effects_types.py": 4,
    "agents/daemon_slayer/_rank_mage.py": 2,
    "agents/daemon_slayer/ability_dps.py": 3,
    "agents/daemon_slayer/burst.py": 4,
    "agents/daemon_slayer/dps.py": 1,
    "agents/daemon_slayer/onhit_dps.py": 1,
    "agents/daemon_slayer/tests/test_rank.py": 2,
    "core/coaching_payload.py": 3,
    "core/damage_mix.py": 1,
    "core/game_snapshot.py": 5,
    "dashboard/view_router_state.py": 1,
    "ops/launcher/updater.py": 1,
    "tests/fu02_team_context/test_team_context.py": 1,
    "tests/phase2_smoke/test_sr_aram_worker.py": 2,
    "tests/phase2_smoke/test_tft_worker.py": 3,
    "tests/snapshot_panels/test_mock_server_teardown_s144q13.py": 1,
    "tests/test_build_order.py": 1,
    "tests/test_coach_archetype_dispatch.py": 1,
    "tests/test_ds_preview_capgap.py": 1,
    "tests/test_hotkey_moment_mark.py": 1,
    "tests/test_jade_coach_path.py": 1,
    "tests/test_lcu_pool.py": 1,
    "tests/test_routes_ds_preview_scorer.py": 1,
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


def test_no_new_d204_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"ruff {_RULES} findings above the baseline, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends at its recorded count; one that shrank must be lowered or dropped."""
    stale = {rel: (n, tree_counts.get(rel, 0)) for rel, n in _BASELINE.items() if tree_counts.get(rel, 0) != n}
    assert not stale, f"baseline file: (recorded, measured): {stale}"


def test_probe_is_live():
    """D204 reports a class docstring glued to its body and stays quiet once a blank line follows it."""
    bad = 'class A:\n    """Doc."""\n    x = 1\n'
    good = 'class A:\n    """Doc."""\n\n    x = 1\n'
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
