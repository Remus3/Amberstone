"""S144-P-643 - ruff TC002 (a third-party import used only in annotations) is held at zero tree-wide.

TC002 is not selected by ruff.toml. Measured 2026-11-09 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 6 findings in 5 files, every one in a module carrying ``from __future__ import annotations``
(so the annotation is never evaluated at runtime): ``import pytest`` used only as ``pytest.MonkeyPatch`` /
``pytest.LogCaptureFixture`` in four test modules, and ``Request`` / ``Response`` from ``websockets.http11`` used only in
the ``_process_request`` signature of ``agents/agent2_backend/ws_server.py``. Each import now sits under
``if TYPE_CHECKING:``.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline is empty and only ever
shrinks; a new annotation-only third-party import goes under ``TYPE_CHECKING`` (or is used at runtime).
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

_RULES = ("TC002",)
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
    """TC002 fires on an annotation-only third-party import and stays quiet under ``TYPE_CHECKING``."""
    bad = (
        "from __future__ import annotations\n"
        "import pytest\n"
        "def f(m: pytest.MonkeyPatch) -> None:\n"
        "    return None\n"
    )
    good = (
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import pytest\n"
        "def f(m: pytest.MonkeyPatch) -> None:\n"
        "    return None\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
