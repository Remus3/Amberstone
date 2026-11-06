"""RM-1699 - FURB192 (``sorted(x)[0]`` / ``sorted(x)[-1]`` instead of ``min`` / ``max``) held at a baseline that only shrinks.

The rule is not selected by ruff.toml, and the test-code ratchet (RM-1685) keeps production out of scope.
Measured 2026-11-05 with ``ruff check --isolated`` (target py39): production code carried 6 sites in 5 modules.
Five are fixed; each sorted the whole sequence to read its first element, and each reads an iterable that is
already known to be non-empty at that point (a ``if not ok: return`` guard, an ``if carry_games:`` guard, an
``if got`` conditional expression, a per-champion list that always holds at least one grade), so ``min`` can
not raise where ``sorted(...)[0]`` did not. ``min`` returns the first minimal element, as the stable sort did.

The baseline is the finding that stays: ``ops/launcher/updater.py`` is in the packaged-app tree, which the main
session owns (lane exclusions). A baseline entry that stops offending fails ``test_baseline_is_exact`` until it
is dropped; a new finding anywhere else fails ``test_no_new_findings``.

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

_RULE = "FURB192"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "ops/launcher/updater.py": 1,
}
_FIXED = (
    "dashboard/builders_home.py",
    "tft/engine/comps.py",
    "tools/ds_feed_index.py",
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
    probe = "def f(xs):\n    return sorted(xs)[0]\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {_RULE}
