"""RM-1684 - ruff RUF015 (a list built only to read its first element) is held at zero in the test code.

RUF015 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120``
(target py39): 52 findings in 28 modules under ``tests/``, ``agents/daemon_slayer/tests/`` and
``tools/tests/``, none in a main-session-owned module, so the baseline is empty. Each was rewritten by ruff's
own (unsafe-marked) fix: ``[x for x in xs if p(x)][0]`` becomes ``next(x for x in xs if p(x))`` and
``list(d)[0]`` becomes ``next(iter(d))``.

Equivalence: both spellings return the first element in iteration order and build no other element's value
beyond the first match, so every swapped line reads the same value. The only difference is the failure type on
an EMPTY source (``StopIteration`` instead of ``IndexError``), which fails the same test either way; no
swapped line sits under ``pytest.raises(IndexError)`` (measured by running every touched module). The run uses
NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("RUF015",)
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = set()


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


def test_no_new_ruf015_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_first_element_spellings_agree():
    """The rewrite reads the same element; only the empty-source exception type differs."""
    rows = [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": "b", "v": 3}]
    hits = [r for r in rows if r["k"] == "b"]
    assert hits[0] == next(r for r in rows if r["k"] == "b")
    mapping = {"x": 1, "y": 2}
    keys = list(mapping)
    assert keys[0] == next(iter(mapping))
    misses = [r for r in rows if r["k"] == "zz"]
    with pytest.raises(IndexError):
        misses[0]
    with pytest.raises(StopIteration):
        next(r for r in rows if r["k"] == "zz")


def test_probe_is_live():
    """The rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = "rows = [1, 2]\nfirst = [r for r in rows if r][0]\n"
    good = "rows = [1, 2]\nfirst = next(r for r in rows if r)\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
