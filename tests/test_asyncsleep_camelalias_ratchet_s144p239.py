"""RM-1742 - ruff ASYNC251 and N813 are held at zero tree-wide.

Neither rule is selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated --line-length 120`` (target
py39) over the tracked Python: ASYNC251 reported 2 ``time.sleep(0.02)`` calls inside ``async def drive()`` bodies in
``agents/agent3_testing/suite/test_round12.py`` (each only lets a file mtime tick over between two ``_tick`` calls, so
they are now ``await asyncio.sleep(0.02)`` and no longer block the event loop), and N813 reported 3 CamelCase
``Handler`` classes imported under lowercase aliases in ``tests/test_host_allowlist_servers_rm819.py`` (the aliases are
now ``DsHandler`` / ``McHandler`` / ``VisionHandler`` (CamelCase, N813 accepts nothing lowercase); the dict the helper returns is unchanged).

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

_RULES = ("ASYNC251", "N813")
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
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_async_sleep_or_camel_alias_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """Each rule reports its pattern and stays quiet on the conventional spelling."""
    bad_async = "import time\n\nasync def drive():\n    time.sleep(1)\n"
    good_async = "import asyncio\n\nasync def drive():\n    await asyncio.sleep(1)\n"
    bad_alias = "from json import JSONDecoder as dec\n"
    good_alias = "from json import JSONDecoder as DecCls\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad_async)
    assert {d["code"] for d in found} == {"ASYNC251"}, found
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad_alias)
    assert {d["code"] for d in found} == {"N813"}, found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good_async) == []
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good_alias) == []
