"""RM-1677 - ruff PIE807, RET501 and PLR1711 are held at zero across the tracked tree (one row aside).

None of the three rules is in ruff.toml's ``select``. Measured 2026-11-05 with
``ruff check --isolated --select PIE807,RET501,PLR1711`` (target py39): 106 findings in 75 files,
all but one in test modules plus ``core/death_patterns_loader.py``.

- PIE807: ``lambda: {}`` / ``lambda: []`` is the builtin ``dict`` / ``list`` with no argument.
- RET501: ``return None`` in a function whose only possible return value is None is a bare ``return``.
- PLR1711: a trailing ``return`` / ``return None`` at the end of a function body is dead.

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

_RULES = "PIE807,RET501,PLR1711"
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {
    "tests/test_rc_facts_launcher_cutover_a45d.py": 1,  # blocked: a launcher-cutover test the PKG owner may hold
}
_FIXED = (
    "core/death_patterns_loader.py",
    "tests/conftest.py",
    "tests/test_routes_build_order.py",
    "tests/test_smoothed_rates_101qq_lock.py",
    "tests/test_rc_facts_task_health.py",
    "tools/tests/test_meraki_perlevel_bulk.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
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
        "def f(items):\n"
        "    items.append(lambda: {})\n"
        "    return None\n"
        "\n"
        "\n"
        "def g(items):\n"
        "    if items:\n"
        "        return None\n"
        "    items.append(1)\n"
        "\n"
        "\n"
        "def h(items):\n"
        "    items.append(1)\n"
        "    return\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["PIE807", "PLR1711", "PLR1711", "RET501", "RET501"]
