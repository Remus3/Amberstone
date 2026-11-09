"""RM-1737 - ruff PT001 is held at zero in the test code.

PT001 is not selected by ruff.toml. Measured 2026-11-06 with
``ruff check --isolated --line-length 120`` (target py39) over the tracked test code: 141 findings in 99 modules, every
one ``@pytest.fixture()`` where the house style is the bare ``@pytest.fixture`` (``fixture-parentheses`` defaults to
false). 137 findings in 96 modules were fixed with ruff's own safe fix: the decorator loses its empty parentheses and
nothing else changes (``@pytest.fixture()`` and ``@pytest.fixture`` register the identical fixture).

Three modules stay on the baseline because someone else owns them this session: the two ``test_build_portable_*``
modules (PKG, in ``lane_exclusions_s144.txt``) and ``agents/agent3_testing/suite/test_win_reconcile.py`` (changed on
``lane/true-audit``). The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("PT001",)
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/", "agents/agent3_testing/suite/")
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = {
    "tests/test_build_portable_backend_manifest_pkg6b.py",  # PKG-owned (main session)
    "tests/test_build_portable_bundle_pkg.py",  # PKG-owned (main session)
    "agents/agent3_testing/suite/test_win_reconcile.py",  # lane/true-audit changed it; drop once that lands
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
    assert any(rel.startswith(_TEST_DIRS) for rel in tracked), "no tracked test module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_TEST_DIRS):
            counts[rel] += 1
    return dict(counts)


def test_no_new_pt001_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """PT001 reports the empty-parentheses decorator and stays quiet on the bare and the argument-bearing forms."""
    bad = textwrap.dedent(
        """
        import pytest

        @pytest.fixture()
        def thing():
            return 1
        """
    )
    good = textwrap.dedent(
        """
        import pytest

        @pytest.fixture
        def thing():
            return 1

        @pytest.fixture(scope="module")
        def other():
            return 2
        """
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
