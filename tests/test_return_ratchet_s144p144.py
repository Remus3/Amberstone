"""RM-1530 - RET504 (assign then return) and RET503 (implicit return in a value-returning function) are held at a baseline that only shrinks.

Neither rule is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39):
production code carried 13 sites. Seven files assigned a value to a local and returned it on the next
line (RET504), and one HTTP handler class ended three ``-> None`` methods with a bare ``super().do_X()``
call after every other branch had ``return``-ed a value (RET503); each now returns the expression directly.
RM-1692 then ended ``scripts/cache_ddragon_assets.py`` ``fetch`` with an explicit ``return False``.

The baseline is the findings that stay, each for a named reason:

- ``ops/fleet_kit/fleet_suite_gate.py``: a vendored kit file pinned by ``ops/fleet_kit/MANIFEST.json``; never
  edited locally.
- ``tools/sibling_name_sweep.py``: ``rc`` is assigned inside ``try`` and read again in ``finally``, so the
  assignment is not unnecessary; ruff's finding is a false positive here.

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
from tests._ruff_version import MEASURED_RUFF, fail_if_the_landing_box_moved, ruff_minor

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("RET504", "RET503")
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
)
# file -> finding count that stays (reasons in the module docstring). Only shrinks.
_BASELINE = {
    "ops/fleet_kit/fleet_suite_gate.py": 1,
    "tools/sibling_name_sweep.py": 1,
}
_FIXED = (
    "agents/_supervisor_http.py",
    "agents/agent2_backend/migration_rewind.py",
    "dashboard/_champ_select_deterministic.py",
    "lcu/lcu_rune_writer.py",
    "scripts/cache_ddragon_assets.py",
    "scripts/retrofill_match_metrics.py",
    "tools/daemon_slayer_extract.py",
    "tools/inbox_responder_runner.py",
    "tools/replay_matchup_validate.py",
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
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    minor = ruff_minor()
    if minor != MEASURED_RUFF:
        fail_if_the_landing_box_moved(minor)
        pytest.skip(f"ruff {minor} differs from the measured {MEASURED_RUFF} (RM-1657)")
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


_PROBES = (
    ("RET504", "def f(x):\n    y = x + 1\n    return y\n"),
    ("RET503", "def f(x):\n    if x:\n        return 1\n    print(x)\n"),
)


@pytest.mark.parametrize("rule,probe", _PROBES)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--select", rule, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {rule}
