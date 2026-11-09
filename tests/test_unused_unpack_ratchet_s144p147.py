"""RM-1533 - ruff RUF059 (a tuple-unpacked name that is never read) is held at a baseline that
only shrinks.

RUF059 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target
py39): production code carried 23 sites in 12 modules. Each was ``a, err = request(...)`` or
``(ts, cg, tg, ...) = row`` where one or more of the names is bound and never read. The fix keeps
the unpack (the arity check it performs is real: a 4-tuple row still fails loudly when the shape
changes) and renames the dead names with a leading underscore, which is the signal to a reader and
to ruff that the value is deliberately discarded. It is behaviour-neutral: only a local name
changes.

The baseline is the findings that stay because someone else owns the file: the frozen
``app/_game_lifecycle.py`` (CLAUDE.md frozen list, no inline edit), the vendored fleet kit
(byte-pinned to MAIN's MANIFEST) and ``docs/_rescore/aggregation_sweep.py`` (a pre-registered
analysis script whose bytes are cited by the adjudication notes next to it). A baseline entry that
stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding anywhere else
fails ``test_no_new_findings``.

Scope: production code. ``tests/``, ``tools/tests/``, ``agents/daemon_slayer``, the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope. The run
uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("RUF059",)
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
    "docs/_rescore/aggregation_sweep.py": 1,
    "ops/fleet_kit/fleet_gitlock.py": 1,
    "ops/fleet_kit/fleet_rewrite.py": 1,
}
_FIXED = (
    "core/comp_coverage.py",
    "core/vod_alignment.py",
    "dashboard/routes_ban_suggest.py",
    "dashboard/routes_pickban.py",
    "lcu/snapshot_shape.py",
    "ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py",
    "scripts/probe_missing_codes.py",
    "scripts/retrofill_match_metrics.py",
    "tools/lcu_agent.py",
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
                  stdin="def f(r):\n    a, err = r()\n    return a\n")
    assert {d["code"] for d in found} == set(_RULES), found


def test_an_underscore_name_is_the_discard_signal():
    """The premise of the fix: the leading underscore is what RUF059 honours."""
    found = _ruff(["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"],
                  stdin="def f(r):\n    a, _err = r()\n    return a\n")
    assert found == []


def test_renaming_an_unpacked_name_keeps_the_arity_check():
    """A renamed discard still unpacks the whole tuple, so a shape change still raises."""
    row = (1, 2, 3, 4)
    ts, _cg, tg, _xp = row
    assert (ts, tg) == (1, 3)
    with pytest.raises(ValueError):
        ts, _cg, tg, _xp = (1, 2, 3)
