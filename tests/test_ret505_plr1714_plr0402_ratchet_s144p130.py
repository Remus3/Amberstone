"""RM-1522 - ruff RET505, PLR1714 and PLR0402 are held at the baseline.

None of the three is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: production code carried 13 RET505 findings
(an ``else:`` / ``elif`` after a branch that already returned, in 5 modules), 3 PLR1714
(``x == a or x == b``, one in the kit file) and 1 PLR0402 (``import tft.tft_set as tft_set``).

RET505 was fixed with ruff's own fix, which only de-indents the else body: the branch
that returned never falls through, so the code that follows ran only on the other path
before and still does. PLR0402 became ``from tft import tft_set`` (same module object,
same attribute name). The three PLR1714 sites are all left on purpose; whoever fixes
them writes tuple membership, never the set ruff suggests, because a ``set`` raises
TypeError on an unhashable operand where ``==`` did not (``core/match_metrics.py``
compares a payload value of unknown type).

One finding is left on purpose: ``ops/fleet_kit/fleet_suite_gate.py`` is a vendored
fleet kit file (CLAUDE.md FLEET-COMMON item 11: never edit locally) and drops to zero only
when MAIN ships a new kit version. ``core/match_metrics.py`` and
``dashboard/routes_replay_events.py`` were left by this slice and RM-1420 (a lane branch
held them) and became tuple membership in RM-1537.

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

_RULES = ("RET505", "PLR1714", "PLR0402")
_OUT_OF_SCOPE = (
    "tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "coaches/brawl_coach.py",
    "lcu/lcu_rune_writer.py",
    "ops/rc_self_monitor.py",
    "tft/rounds/ground_truth.py",
    "tools/dev_cli.py",
    "tools/gated_g103_cc_pressure.py",
)
# file -> number of findings still there. Only shrinks.
_BASELINE: dict[str, int] = {
    # RM-1537: core/match_metrics.py and dashboard/routes_replay_events.py now
    # use tuple membership (no lane branch holds them any more).
    "ops/fleet_kit/fleet_suite_gate.py": 1,  # vendored kit file: MAIN ships a new version
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
    """The isolated run reports a minimal offender for two of the rules, so a baseline-only
    tree result is a real scan and not a dead probe."""
    source = (
        "def f(x):\n"
        "    if x == 1 or x == 2:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n"
    )
    found = _ruff(["--select", ",".join(_RULES), "--stdin-filename", "probe_mod.py", "-"], stdin=source)
    assert {"RET505", "PLR1714"} <= {d["code"] for d in found}, found
