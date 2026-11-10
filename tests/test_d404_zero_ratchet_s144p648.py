"""S144-P-648 - ruff D404 (docstring first word "This") is held at zero tree-wide bar four named files.

D404 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 40 findings in 40 files, every one a docstring opening "This <noun> ..." (or "THIS ..."): 35
test modules (the "This test file is pure ASCII" hygiene docstrings and "This ratchet exists because ..." ones) and
five production docstrings (``core.local_hosts.tailnet_ipv4``, ``tools.inbox_responder_runner._trim`` and the three
baseline files below). 36 are reworded ("The ...", or an imperative first word for the two production functions
above); the 4 left sit in files another
lane branch carries unlanded changes to, so they stay in ``_BASELINE`` until that lane lands (the baseline only
shrinks). No behaviour change: docstring text only.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("D404",)
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE = {
    "ops/loop/inbox_tick.py",              # lane/queue carries an unlanded change to it
    "tools/credential_history_scan.py",    # lane/queue carries an unlanded change to it
    "tools/stop_claim_gate.py",            # lane/queue carries an unlanded change to it
    "tests/test_ds_sweep_panel_dom.py",    # lane/ds carries an unlanded change to it
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
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """The rule fires on a known-bad docstring and the probe stays quiet on the conventional spelling."""
    bad = 'def f():\n    """This function returns one."""\n    return 1\n'
    good = 'def f():\n    """Return one."""\n    return 1\n'
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
