"""RM-1521 - ruff PLR5501 (an ``else:`` whose only content is an ``if``) is held at the baseline.

PLR5501 is not selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: 12 production sites in 11 modules nested an
``if`` under an ``else:`` instead of writing ``elif``. This slice rewrote them with
ruff's own fix, which only re-indents: every comment between the ``else:`` and the
``if`` stays with the branch it described, and the branch order and conditions are
unchanged, so no behaviour moves.

One site is left on purpose: ``app/_game_lifecycle.py`` is a FROZEN file (CLAUDE.md
"Frozen files"), so its single finding is the baseline and drops to zero only with an
operator-approved edit of that file.

Scope: production code. ``tests/``, ``agents/daemon_slayer`` (DS lane), the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. A new finding anywhere in scope, or
a baseline file that offends more than it did, fails; a baseline entry that has
stopped offending also fails until it is dropped, so the table only shrinks.
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

_RULES = ("PLR5501",)
_OUT_OF_SCOPE = (
    "tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "core/build_planner/replan.py",
    "core/tft_worker.py",
    "core/vision_tracker.py",
    "game_reader/snapshot_normalizer.py",
    "ops/audit/p3c24_token_equiv.py",
    "ops/rc_self_monitor.py",
    "scripts/champion_drift_alerts.py",
    "tools/bootstrap_env_check.py",
    "tools/build_third_party_notices.py",
    "tools/champion_loadout_validate_meta.py",
    "tools/probe_101qq_hero_rank_double.py",
)
# file -> number of findings still there. Only shrinks.
_BASELINE: dict[str, int] = {
    "app/_game_lifecycle.py": 1,  # FROZEN: an operator-approved edit only
}


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
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_file_gains_a_finding(tree_counts):
    worse = {f: (n, _BASELINE.get(f, 0)) for f, n in tree_counts.items()
             if n > _BASELINE.get(f, 0)}
    assert not worse, f"ruff {_RULES}, file: (now, baseline): {worse}"


def test_baseline_is_exact_so_it_only_shrinks(tree_counts):
    stale = {f: (tree_counts.get(f, 0), n) for f, n in _BASELINE.items()
             if tree_counts.get(f, 0) != n}
    assert not stale, f"lower or drop these baseline rows, file: (now, baseline): {stale}"


def test_fixed_modules_stay_clean(tree_counts):
    assert not [f for f in _FIXED if f in tree_counts]


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_probe_is_live():
    """The isolated run reports a minimal offender, so a baseline-only tree result
    is a real scan and not a dead probe."""
    source = "x = 1\nif x:\n    pass\nelse:\n    if x > 2:\n        pass\n"
    found = _ruff(["--select", "PLR5501", "--stdin-filename", "probe_mod.py", "-"], stdin=source)
    assert "PLR5501" in {d["code"] for d in found}, found
