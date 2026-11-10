"""S144-P-649 - ruff TC001 (a first-party import used only in annotations) is held at zero bar four named files.

TC001 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 16 findings in 12 files, every one in a module carrying ``from __future__ import annotations``
(so the annotation is never evaluated at runtime). Twelve findings in eight files are fixed here and now sit under
``if TYPE_CHECKING:``: ``Fetched`` in ``lib/game_data/build.py``, ``CrossEval`` / ``ChampModeWin`` in
``ops/audit/ds_perm_swarm/consolidate.py`` and ``perm_score.py``, and ``PanelSpec`` / ``Probe`` / ``Profile`` in
``tft/cv/layout.py``, plus ``DataSnapshot`` / ``AbilitiesSnapshot`` / ``Augment`` in four Daemon Slayer engine modules
(``_ad_axis_ability``, ``_rank_mage``, ``augment_formula_eval``, ``dsp_live_consumers``). No other module imports those names from the fixed modules (grep at the measurement).

Four baseline rows stay, each a file this lane may not edit: ``app/__init__.py`` (frozen, needs explicit approval),
``core/damage_mix.py`` (the ``lane/true-audit`` branch changes it) and ``agents/daemon_slayer/dps_sweep.py`` /
``matchup.py`` (the ``lane/ds`` branch changes them); the merger or the owning lane moves the import and drops the row. Each row pins its COUNT, so a second annotation-only import in a baselined file still fails.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline only ever shrinks.
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

_RULES = ("TC001",)
# file -> findings. Only shrinks: a row that reaches zero must be dropped.
_BASELINE = {
    "app/__init__.py": 1,  # FROZEN (CLAUDE.md frozen list)
    "core/damage_mix.py": 1,  # lane/true-audit changes this file
    "agents/daemon_slayer/dps_sweep.py": 1,  # lane/ds changes this file
    "agents/daemon_slayer/matchup.py": 1,  # lane/ds changes this file
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
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


def test_no_new_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline row still offends with exactly its count; a stale row must be dropped (the set only shrinks)."""
    assert {rel: tree_counts.get(rel, 0) for rel in _BASELINE} == _BASELINE


def test_probe_is_live():
    """TC001 fires on an annotation-only first-party import and stays quiet under ``TYPE_CHECKING``."""
    bad = (
        "from __future__ import annotations\n"
        "from core.polled_json import atomic_write_text\n"
        "def f(m: atomic_write_text) -> None:\n"
        "    return None\n"
    )
    good = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from core.polled_json import atomic_write_text\n"
        "def f(m: atomic_write_text) -> None:\n"
        "    return None\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
