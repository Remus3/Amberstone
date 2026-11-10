"""RM-1686 - ruff PLC0206 (a dict iterated by key, then indexed with that key) is held at zero in the test code.

PLC0206 is not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120``
(target py39): 8 findings in 8 modules under ``tests/``, ``agents/daemon_slayer/tests/`` and
``tools/tests/`` (six DS ``test_cc_conditional_wave*.py`` loops, one in ``test_rm175_aram_table_known_wrong.py``,
one in ``test_web_css_split_plan_rm726.py``), none in a main-session-owned module and none in a file another
lane branch changed, so the baseline is empty. The rule has no auto-fix; each loop was rewritten by hand from
``for k in d: ... d[k]`` to ``for k, v in d.items(): ... v``.

Equivalence: ``d[k]`` inside the loop read the value that ``.items()`` yields, and no loop body assigns to
``d`` (the rm175 loop mutates the SET held as the value, which is the same object ``.items()`` hands out, so
the in-place ``.add`` still lands). The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a
finding.
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

_RULES = ("PLC0206",)
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


def test_no_new_plc0206_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_items_and_index_loops_agree_and_inplace_mutation_lands():
    """The rewrite reads the same values, and mutating a set value in place still reaches the dict."""
    table = {"a": {1}, "b": {2, 3}}
    by_index = [(k, sorted(table[k])) for k in table]
    by_items = [(k, sorted(v)) for k, v in table.items()]
    assert by_index == by_items
    for bucket in table.values():
        bucket.add(9)
    assert table == {"a": {1, 9}, "b": {2, 3, 9}}


def test_probe_is_live():
    """The rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = "d = {'a': 1}\nfor k in d:\n    print(d[k])\n"
    good = "d = {'a': 1}\nfor k, v in d.items():\n    print(k, v)\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
