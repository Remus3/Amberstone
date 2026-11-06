"""RM-1743 - ruff D208, PTH201 and SIM300 are held at zero tree-wide outside the PKG tests.

None of the three rules is selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated --line-length 120``
(target py39) over the tracked Python: D208 reported 24 docstring lines indented deeper than their docstring in
``core/decision_detector.py``, ``dashboard/builders.py``, ``tests/test_coach_output_p2_2.py`` and
``tests/test_cross_mode_ds_p1l6.py`` (docstring text only; no string read at runtime was touched); PTH201 reported 6
``Path(".")`` calls in ``agents/daemon_slayer/tests/test_wiki_stats_overlay.py`` and ``tests/test_loop_executor.py``
(now ``Path()``, the same value); SIM300 reported one Yoda comparison in
``agents/agent3_testing/suite/test_agent6_failure_stub_l03.py`` (operands swapped, ``!=`` is symmetric).

The three launcher / packaged-smoke test modules in the baseline are PKG-owned (main-session exclusion list), so their
four SIM300 rows wait for that owner. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a
finding. The baseline only shrinks.

Deliberately NOT in this set: PLR1730 (``if x < 0: x = 0`` -> ``max``): 11 of its 12 rows sit in the Daemon Slayer
engine modules, an engine edit is Tier-2 and belongs to the ds lane.
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

_RULES = ("D208", "PTH201", "SIM300")
# PKG-owned test modules (main-session exclusion list): their SIM300 rows wait for that owner.
_BASELINE = {
    "tests/test_launcher_service_host.py",
    "tests/test_launcher_updater.py",
    "tests/test_run_packaged_smoke_launcher_pkg6.py",
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
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
        if rel in tracked and not rel.startswith("ops/fleet_kit/"):
            counts[rel] += 1
    return dict(counts)


def test_no_new_docindent_pathdot_or_yoda_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """Each rule reports its pattern and stays quiet on the conventional spelling."""
    cases = {
        "D208": ('def f():\n    """Doc.\n\n        over\n        more\n    """\n',
                 'def f():\n    """Doc.\n\n    fine\n    """\n'),
        "PTH201": ('from pathlib import Path\nx = Path(".")\n', 'from pathlib import Path\nx = Path()\n'),
        "SIM300": ("a = 1\nassert 2 == a\n", "a = 1\nassert a == 2\n"),
    }
    for code, (bad, good) in cases.items():
        found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
        assert {d["code"] for d in found} == {code}, (code, found)
        assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == [], code
