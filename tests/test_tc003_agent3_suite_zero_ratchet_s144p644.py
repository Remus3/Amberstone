"""S144-P-644 - ruff TC003 (a stdlib import used only in annotations) is held at zero in the agent3 suite tree.

TC003 is not selected by ruff.toml. Measured 2026-11-09 with ``ruff check --isolated --line-length 120`` (target py39):
110 findings tree-wide, 16 of them in 16 modules of ``agents/agent3_testing/suite`` (``from pathlib import Path`` used
only in test-function signatures in 15, ``import threading`` used only in a ``list[threading.Thread]`` annotation in
one). Every one of those modules carries ``from __future__ import annotations``, so the annotation is never evaluated
at runtime; each import now sits under ``if TYPE_CHECKING:``.

Scope is that one directory: it is one cycle-sized slice, and a tree-wide baseline of the other ~94 findings (mostly
``tests/``) would be a long exception list rather than a ratchet. Widen ``_SCOPE`` as further slices land. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide
a finding. The baseline is empty and only ever shrinks.
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

_RULES = ("TC003",)
_SCOPE = "agents/agent3_testing/suite"
# Empty baseline: it only shrinks, so nothing may be added.
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
def scope_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    in_scope = {rel for rel in tracked if rel.startswith(_SCOPE + "/")}
    assert len(in_scope) > 30, "the tracked-file walk found almost nothing under the scope"
    counts: collections.Counter = collections.Counter()
    for d in _ruff([_SCOPE]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in in_scope:
            counts[rel] += 1
    return dict(counts)


def test_no_new_finding(scope_counts):
    new = {rel: n for rel, n in scope_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(scope_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(scope_counts), sorted(_BASELINE - set(scope_counts))


def test_probe_is_live():
    """TC003 fires on an annotation-only stdlib import and stays quiet under ``TYPE_CHECKING``."""
    bad = (
        "from __future__ import annotations\n"
        "from pathlib import Path\n"
        "def f(p: Path) -> None:\n"
        "    return None\n"
    )
    good = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from pathlib import Path\n"
        "def f(p: Path) -> None:\n"
        "    return None\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
