"""S144-P-640 - ruff N811, N814 and N815 are held at zero outside the frozen set.

None of the three is selected by ruff.toml. Measured 2026-11-09 with ``ruff check --isolated --line-length 120``
(target py39) over the tracked Python: 17 findings in 10 files (N811 x10, N814 x3, N815 x3 and one unrelated
PLW0602 that is not part of this ratchet). Twelve were fixed here: alias names that read as a constant imported
under a lower-case name (renamed, or the module is imported and the attribute read), ``SimpleNamespace as NS``
(imported plainly), the dashboard handler's two ``core.log_scrub`` aliases (imported straight under their
module-private names, which also drops a second binding), and three ``ast.NodeVisitor`` ``visit_Xxx`` class
attributes whose mixedCase spelling is the stdlib dispatch contract (a reasoned ``noqa: N815``).

``app/_game_lifecycle.py`` is FROZEN (CLAUDE.md: no edit without explicit approval), so its four findings are the
whole baseline and it is the only entry that may stay. The run uses NO config (``--isolated``) so a per-file-ignore
cannot hide a finding. The baseline only shrinks.
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

_RULES = ("N811", "N814", "N815")
# Frozen files only. An entry that stops offending fails test_baseline_is_exact; a new entry is refused by review.
_BASELINE: dict[str, int] = {"app/_game_lifecycle.py": 4}


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
    assert not new, f"ruff {_RULES} findings above the baseline, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends at its recorded count; a shrunk entry must be lowered or dropped."""
    stale = {rel: (n, tree_counts.get(rel, 0)) for rel, n in _BASELINE.items() if tree_counts.get(rel, 0) != n}
    assert not stale, f"baseline entries that no longer match, file: (recorded, measured): {stale}"


def test_baseline_names_only_frozen_files():
    """The baseline is the frozen set and nothing else: a non-frozen file is fixed, never parked here."""
    frozen = {"app/_game_lifecycle.py", "app/_loop.py", "app/__init__.py", "app/_health_monitor.py",
              "app/_remediation.py", "app/_state_authority.py", "app/_overlay_manager.py", "main.py",
              "core/log_setup.py", "core/moon_proxy.py", "lcu/lcu_client.py", "core/game_snapshot.py",
              "ops/rc_dev_runtime.py", "ops/rc_supervisor.py"}
    assert set(_BASELINE) <= frozen, sorted(set(_BASELINE) - frozen)


def test_probe_is_live():
    """Each rule fires on a known-bad snippet and the probe stays quiet on the conventional spelling."""
    bad = (
        "import ast\n"
        "from types import SimpleNamespace as NS\n"
        "from mod import SOME_CONSTANT as lower_alias\n"
        "class V(ast.NodeVisitor):\n"
        "    visit_Lambda = ast.NodeVisitor.generic_visit\n"
    )
    good = (
        "import ast\n"
        "from types import SimpleNamespace\n"
        "from mod import SOME_CONSTANT as UPPER_ALIAS\n"
        "class V(ast.NodeVisitor):\n"
        "    visit_Lambda = ast.NodeVisitor.generic_visit  # noqa: N815\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
