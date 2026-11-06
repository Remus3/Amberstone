"""RM-1700 - W291, W293, D200 and D202 held in production code at a baseline that only shrinks.

ruff.toml selects none of these, and no earlier ratchet covers them. Measured 2026-11-05 with
``ruff check --isolated`` (target py39): production code carried 48 findings in 7 modules. Twenty-five
are fixed (trailing whitespace on comment rules and one docstring line, whitespace-only blank lines, a blank
line after a function docstring, a one-line docstring spread over three lines); none touches executable code.
D208 (over-indented docstring) is deliberately NOT held: the flagged docstrings indent a bullet list on purpose.

The baseline is the finding that stays: ``ops/rc_supervisor.py`` is a frozen file (CLAUDE.md), carrying 23
trailing-whitespace lines in comments. A baseline entry that stops offending fails ``test_baseline_is_exact``
until it is dropped; a new finding anywhere else fails ``test_no_new_findings``.

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

_RULES = "W291,W293,D200,D202"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "ops/rc_supervisor.py": 23,
}
_FIXED = (
    "core/coach_choices.py",
    "core/safe_coach_output.py",
    "item_advisor.py",
    "ops/rc_self_monitor.py",
    "tft/tft_coach_engine.py",
    "tft/tft_ocr_reader.py",
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
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
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
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


@pytest.mark.parametrize(
    ("code", "probe"),
    [
        ("W291", "x = 1 \n"),
        ("W293", "def f():\n    x = 1\n    \n    return x\n"),
        ("D200", 'def f():\n    """\n    One line.\n    """\n    return 1\n'),
        ("D202", 'def f():\n    """Doc."""\n\n    return 1\n'),
    ],
)
def test_probe_is_live(code, probe):
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert code in {d["code"] for d in found}
