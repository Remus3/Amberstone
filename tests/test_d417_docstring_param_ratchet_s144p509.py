"""D417 - a docstring parameter section that omits a parameter (S144-P-509).

ruff.toml does not select D417, so nothing held the count. D417 fires only when a function already has a
``Parameters`` / ``Args`` section and that section leaves one of the signature's parameters out: a
half-documented signature that reads as complete. ruff also needs the numpy shape ``name : type`` with the
description on an INDENTED line below it; the older one-line ``name : text`` entries were invisible to it,
which is how four production docstrings that did name their parameters were reported as missing them.

Measured 2026-11-09 with ``ruff check --isolated`` (target py39) over every tracked ``.py`` file
(production, ``tests/``, ``agents/daemon_slayer`` and ``agents/agent3_testing`` included): 5 findings in 5
modules. Three are fixed here (core/coaching_timestamps.py ``write_coaching_ts``, core/feature_policy.py
``is_allowed``, ops/rc_transactional_deploy.py ``wait_for_heartbeat``: docstring text only, no behaviour
change). Two stay as the baseline because another lane branch carries unlanded edits to the file (a
rebase conflict for the merger if this lane touched it too): core/ds_calibration.py ``log_ds_run`` (4
parameters undescribed) and agents/daemon_slayer/ability_dps.py ``compute_ability_dps`` (17 undescribed;
the whole Args section is missing, so it is a rewrite, not a gap). The baseline only shrinks.

A baseline row that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding
anywhere else fails ``test_no_new_findings``. ``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The
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

_RULE = "D417"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)
# file -> finding count that stays (another lane's unlanded edits; module docstring). Only shrinks.
_BASELINE = {
    "core/ds_calibration.py": 1,
    "agents/daemon_slayer/ability_dps.py": 1,
}


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
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


def test_baseline_names_only_tracked_files():
    """A baseline row must name a real tracked file, so a rename cannot silently orphan it."""
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert set(_BASELINE) <= tracked, set(_BASELINE) - tracked


_UNDESCRIBED = (
    "def f(mode, other):\n"
    '    """Summary.\n\n'
    "    Parameters\n    ----------\n"
    "    mode : str\n        The mode.\n"
    '    """\n'
)
_DESCRIBED = _UNDESCRIBED.replace(
    '    """\n', "    other : str\n        The other.\n" + '    """\n')
_ONE_LINE = (
    "def f(mode, other):\n"
    '    """Summary.\n\n'
    "    Parameters\n    ----------\n"
    "    mode : the mode\n    other : the other\n"
    '    """\n'
)


def _probe(src: str) -> list[dict]:
    return _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=src)


def test_probe_is_live():
    """The isolated run reports a docstring that omits one parameter, so an empty tree result is a real scan."""
    assert {d["code"] for d in _probe(_UNDESCRIBED)} == {_RULE}


def test_a_complete_parameter_section_is_quiet():
    assert _probe(_DESCRIBED) == []


def test_one_line_numpy_entries_are_not_recognised():
    """The shape the three fixed docstrings used: names present, description on the same line. ruff misses it."""
    assert {d["code"] for d in _probe(_ONE_LINE)} == {_RULE}
