"""RM-1531 - SIM103 (needless bool: ``if c: return True`` then ``return False``) is held at a baseline that only shrinks.

The rule is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated`` (target py39):
production code carried 22 sites. Ten modules had a function that tested a condition only to return the
literal True or False; each now returns the condition itself. Every rewritten function is annotated or used
as a bool and every operand is already a bool-valued expression (comparisons, ``any``/``all``/``in``,
``startswith``), so the returned type does not change.

RM-1699 fixed ``core/item_wpa.py`` and ``tools/daemon_slayer_abilities_extract.py`` once lane/ds no longer held them.

The baseline is the findings that stay, each for a named reason:

- ``ops/launcher/service_host.py``: the packaged-app tree is owned by the main session (lane exclusions).

S144-P-571 fixed ``tools/repair_mojibake.py`` and ``tools/strip_smart_quotes.py`` (two sites each): the
``_is_external_data`` tail and the ``_skip`` tail now return their condition. Only predicate bodies changed; no
apply path, no sweep run (the smart-quote retro-sweep itself stays operator-gated). The behavioural parity of the
tool copies with the drift guards is pinned by tests/test_py_source_ascii_rm300.py.

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

_RULE = "SIM103"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reasons in the module docstring). Only shrinks.
_BASELINE = {
    "ops/launcher/service_host.py": 1,
}
_FIXED = (
    "agents/agent0_gatekeeper/evaluator.py",
    "agents/agent4_coach_mentor/ui_applier.py",
    "core/item_wpa.py",
    "core/log_retention.py",
    "core/minimap_presence.py",
    "core/post_game_score.py",
    "tft/tft_standalone.py",
    "tools/arena_shadow_report.py",
    "tools/daemon_slayer_abilities_extract.py",
    "tools/hz_shadow_report.py",
    "tools/p3_ascii_census.py",
    "tools/repair_mojibake.py",
    "tools/strip_em_dashes.py",
    "tools/strip_smart_quotes.py",
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
    probe = "def f(x):\n    if x > 1:\n        return True\n    return False\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert {d["code"] for d in found} == {_RULE}
