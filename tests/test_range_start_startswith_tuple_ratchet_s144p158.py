"""RM-1544 - ruff PIE808 and PIE810 are held at zero across the tracked tree (one frozen row aside).

Neither rule is in ruff.toml's ``select``. The earlier ratchets (RM-1518 for ``range(0, n)``,
RM-1536 for ``startswith`` / ``endswith`` joined by ``or``) scoped out ``tests/``, ``docs/`` and
``agents/daemon_slayer``. Measured 2026-11-05 with ``ruff check --isolated --select PIE808,PIE810``
(target py39): 49 findings in 38 files (one more stays: a PKG-owned launcher test), all in test modules and dated docs scripts, plus the one frozen
supervisor row.

- PIE808: ``range(0, n)`` - the start argument defaults to 0, ``range(n)`` is the same sequence.
- PIE810: ``s.startswith(a) or s.startswith(b)`` is ``s.startswith((a, b))``, the same truth table.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = "PIE808,PIE810"
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {
    "ops/rc_supervisor.py": 1,  # FROZEN (ASKS 24): the baseline row stays until the operator approves an edit
    "tests/test_launcher_key_read_rm810.py": 1,  # blocked: main session owns the launcher tests (PKG)
}
_FIXED = (
    "tests/test_pickban_systems_p1l2.py",
    "tests/test_smoothed_rates.py",
    "tests/test_log_message_scrub_rm321.py",
    "tests/test_repo_walk.py",
    "tests/test_inbox_responder_runner.py",
    "agents/daemon_slayer/tests/test_effects_expansion.py",
    "agents/daemon_slayer/tests/test_rune_offense_grants_r145.py",
    "docs/_rescore/tally.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
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
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
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
    """A minimal offender per rule is reported, so an empty tree result is a real scan."""
    probe = (
        "def f(s):\n"
        "    for i in range(0, 3):\n"
        "        pass\n"
        "    return s.startswith('a') or s.startswith('b')\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PIE808", "PIE810"]
