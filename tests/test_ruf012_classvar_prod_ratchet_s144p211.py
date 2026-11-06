"""RM-1719 - ruff RUF012 (mutable class attribute without ClassVar) held in production code.

ruff.toml selects RUF012 nowhere and no earlier ratchet covers it. Measured 2026-11-06 with
``ruff check --isolated`` (target py39): production code carried 24 findings in 13 files. Twenty
are fixed: each shared table (tiered-field lists, validator dicts, crop regions, mode paths, respawn
and jungle tables, the supervisor denylist) now declares ``ClassVar[...]`` so a type checker and a reader
see a class-wide constant, not a per-instance default. The change is annotation-only; no value moves,
and a grep found no rebind of any of them on a ``self`` or an instance of the declaring class.

The findings that stay: ``lcu/lcu_client.py`` ``_PERK_CONFIGS`` (a FROZEN file, CLAUDE.md "Frozen
files"; an edit needs explicit operator approval), and the three ``TIERED_FIELDS`` /
``TIERED_VALIDATORS`` / ``SHADOW_FIELDS`` defaults of ``modes/shared_vision.GameVisionReader``, which
its docstring documents as set PER INSTANCE and which the aram / arena / brawl coaches do rebind
(``r.TIERED_FIELDS = ...``); a ``ClassVar`` there would contradict the design (verifier, 2026-11-06). A baseline row that stops offending fails
``test_baseline_is_exact`` until it is dropped; a new finding anywhere else fails ``test_no_new_findings``.

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

_RULE = "RUF012"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "lcu/lcu_client.py": 1,
    "modes/shared_vision.py": 3,
}
_FIXED = (
    "agents/_supervisor_http.py",
    "coaches/aram_coach.py",
    "coaches/arena_coach.py",
    "coaches/brawl_coach.py",
    "core/match_metrics.py",
    "game_reader/poller.py",
    "game_reader/snapshot_normalizer.py",
    "lib/scrapers/site_b.py",
    "lib/scrapers/site_d.py",
    "tft/tft_live_analysis.py",
    "tft/tft_vision_reader.py",
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
def test_fixed_module_stays_clean(rel, tree_counts):
    assert (REPO_ROOT / rel).is_file(), f"{rel} missing - update _FIXED"
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "class A:\n    X = []\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
