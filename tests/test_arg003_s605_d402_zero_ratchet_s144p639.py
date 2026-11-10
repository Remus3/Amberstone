"""S144-P-639 - ruff ARG003, S605 and D402 are held at zero tree-wide.

None of the three is selected by ruff.toml. Measured 2026-11-09 with ``ruff check --isolated --line-length 120``
(target py39) over the tracked Python: 4 findings in 3 test modules. ARG003 x2 was a fake ``cv2`` stub whose
classmethods named an unused ``flag`` parameter (both callers pass it positionally, so it is now ``_flag``); S605 x1
was the ``os.system("exit 0")`` the process-start tripwire test must make, a constant command carrying a reasoned
``noqa``; D402 x1 was a helper docstring whose first line read like its own signature.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline is empty and only
shrinks.
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

_RULES = ("ARG003", "S605", "D402")
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
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """Each rule fires on a known-bad snippet and the probe stays quiet on the conventional spelling."""
    bad = (
        "import os\n"
        "class A:\n"
        "    @classmethod\n"
        "    def m(cls, unused):\n"
        "        return 1\n"
        "def f():\n"
        '    """f() returns one."""\n'
        '    os.system("exit 0")\n'
    )
    good = (
        "import os\n"
        "class A:\n"
        "    @classmethod\n"
        "    def m(cls, _unused):\n"
        "        return 1\n"
        "def f():\n"
        '    """Return one."""\n'
        '    os.system("exit 0")  # noqa: S605\n'
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
