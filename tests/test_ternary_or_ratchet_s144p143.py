"""RM-1529 - FURB110 (``x if x else y`` written as ``x or y``) is held at a baseline that only shrinks.

FURB110 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39):
production code carried 27 sites; 17 files hand-wrote ``value if value else fallback`` where
``value or fallback`` is the same expression (the condition and the chosen branch read the same name,
so truthiness is tested once either way and no call is repeated).

The baseline is the findings that stay, each for a named reason:

- ``app/_overlay_manager.py``: a frozen file (CLAUDE.md), not edited without operator approval.
- ``tools/ddragon_mirror_refresh.py``, ``tools/upstream_drift_check.py``: held by another lane branch
  at the time of this slice; the next cycle that sees them landed drops the rows.
- ``tools/ds_form_index_prefilter.py`` and ``docs/_rsc_score/calibrate.py``: ruff offers no fix because the
  tested expression is a call or has a side effect, so ``or`` would not be a pure rewrite.
- ``docs/_rescore/tally.py``, ``docs/_rsc_score/tally_ab.py``: dated analysis scripts under docs/.

A baseline entry that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding
anywhere else fails ``test_no_new_findings``.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer`` and the
``agents/agent3_testing/suite`` test suite are out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding.
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

_RULE = "FURB110"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
)
# file -> finding count that stays (reasons in the module docstring). Only shrinks.
_BASELINE = {
    "app/_overlay_manager.py": 1,
    "docs/_rescore/tally.py": 1,
    "docs/_rsc_score/calibrate.py": 1,
    "docs/_rsc_score/tally_ab.py": 2,
    "tools/ddragon_mirror_refresh.py": 1,
    "tools/ds_form_index_prefilter.py": 1,
    "tools/upstream_drift_check.py": 1,
}
_FIXED = (
    "coaches/loadout_resolver.py",
    "core/disk_guard.py",
    "core/ds_antitank_hint.py",
    "core/ds_capability_gap.py",
    "core/ds_scaling_hint.py",
    "core/operator_notify.py",
    "core/operator_push.py",
    "core/precomputed_laning_coach.py",
    "core/vision_server_argv.py",
    "dashboard/routes_lobby_aux.py",
    "ops/audit/ds_perm_swarm/run_consolidate.py",
    "ops/loop/repo_review.py",
    "scripts/postmortem_analyze.py",
    "tft/tft_live_analysis.py",
    "tft/tft_standalone.py",
    "tools/p3_ascii_census.py",
    "tools/stop_claim_gate.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


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
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "def f(x):\n    return x if x else 'd'\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {_RULE}


@pytest.mark.parametrize("value", [0, 0.0, "", None, [], {}, (), False, 1, "a", [0], {"k": 1}, (None,)])
def test_rewrite_is_equivalent(value):
    """The premise of each fix: ``x or y`` returns the same object ``x if x else y`` does."""
    sentinel = object()
    assert (value if value else sentinel) is (value or sentinel)
