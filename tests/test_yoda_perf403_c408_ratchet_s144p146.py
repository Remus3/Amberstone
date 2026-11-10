"""RM-1532 - ruff SIM300, PERF403, C408 and C416 are held at a baseline that only shrinks.

None of the four rules is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated``
(target py39): production code carried 11 SIM300 sites, 5 PERF403 sites, 5 C408 sites and 1 C416 site.

- SIM300 (yoda condition) fires when the left operand looks like a constant, and ruff reads every
  UPPER_CASE name as one - module globals (``_LOCK_OWNER_PID``, ``_CACHE_MTIME``, ``_STATE_CACHE_GEN``)
  and also the numpy channel arrays ``R``/``G``/``B`` and the dimensions ``H``/``W``. Each compared pair
  now reads value-first (``os.getpid() != _LOCK_OWNER_PID``, ``mx == R``, ``size > H``); ``==`` and ``!=``
  are symmetric and the ordering swaps flip the operator, so no result changes.
- PERF403: ``for k, v in d.items(): flags[k] = v`` is ``flags.update(d)``; the ``**splat`` loop in
  ``tools/ds_parity_map.py`` is ``carried.update({key: key for key in got if key in params})`` (same keys,
  same insertion order, same overwrite rule).
- C408: two ``dict(a=..)`` calls with literal keywords are dict literals.

The baseline is the findings that stay, each for a named reason:

- (``coaches/sr_draft_profile.py`` left this list in RM-1536: the true-audit landing put two yoda
  comparisons of module globals back; they now read ``mt == _PRESETS_MTIME``.)
- ``ops/launcher/update_cycle.py`` and ``tools/build_portable.py``: the packaged-app tree is owned by the
  main session (lane exclusions).
- (``tools/daemon_slayer_abilities_extract.py`` left this list in S144-P-526: its SIM103 row was fixed in
  RM-1699 and the last PERF403, ``for field, vals in typed.items(): block[field] = vals``, is now
  ``block.update(typed)`` - same keys, same insertion order, same overwrite rule.)

A baseline entry that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding
anywhere else fails ``test_no_new_findings``.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the vendored
``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run uses NO config
(``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("SIM300", "PERF403", "C408", "C416")
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count (all four rules) that stays (reasons in the module docstring). Only shrinks.
_BASELINE = {
    "ops/launcher/update_cycle.py": 3,
    "tools/build_portable.py": 1,
}
_FIXED = (
    "agents/_supervisor_common.py",
    "coaches/sr_draft_profile.py",
    "coaches/sr_user_builds.py",
    "core/aram_balance_context.py",
    "core/build_planner/kit_synergy.py",
    "core/minimap_blob_detect.py",
    "core/minimap_identity.py",
    "dashboard/routes_state.py",
    "tools/daemon_slayer_abilities_extract.py",
    "tools/ds_cross_eval/probe_champion.py",
    "tools/ds_parity_map.py",
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
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {'/'.join(_RULES)} findings beyond the baseline, file: count: {extra}"


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


@pytest.mark.parametrize(
    ("rule", "probe"),
    [
        ("SIM300", "LIMIT = 3\n\n\ndef f(x):\n    return LIMIT == x\n"),
        ("PERF403", "def f(a):\n    out = {}\n    for k, v in a.items():\n        out[k] = v\n    return out\n"),
        ("C408", "X = dict(a=1)\n"),
        ("C416", "def f(a):\n    return {k: v for k, v in a}\n"),
    ],
)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender for each rule, so an empty tree result is a real scan."""
    found = _ruff(["--select", rule, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {rule}
