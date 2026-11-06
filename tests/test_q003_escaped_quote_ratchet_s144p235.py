"""RM-1738 - ruff Q003 (avoidable escaped quote) is held at zero outside the kit and the PKG-owned tests.

Q003 is not selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 200 findings in 107 modules, every one a string such as ``"say \\"hi\\""`` that the other quote
character would spell without escapes (``'say "hi"'``). 180 findings in 102 modules were fixed with ruff's own safe
fix. The fix changes quoting only: the ``ast.dump`` of every one of the 102 modules is identical before and after, so
no string value, f-string or docstring changed.

Five modules stay on the baseline because someone else owns them: four vendored kit files under ``ops/fleet_kit/``
(byte-pinned by the kit MANIFEST, never edited locally) and ``tests/test_launcher_key_read_rm810.py`` (PKG, in
``lane_exclusions_s144.txt``). The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = ("Q003",)
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = {
    "ops/fleet_kit/fleet_board.py",  # kit-owned, byte-pinned by MANIFEST.json
    "ops/fleet_kit/fleet_identity.py",  # kit-owned
    "ops/fleet_kit/fleet_rewrite.py",  # kit-owned
    "ops/fleet_kit/fleet_watch.py",  # kit-owned
    "tests/test_launcher_key_read_rm810.py",  # PKG-owned (main session)
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
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_q003_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_probe_is_live():
    """Q003 reports an escaped quote the other quote character avoids and stays quiet on the unescapable forms."""
    bad = 'x = "say \\"hi\\""\n'
    good = textwrap.dedent(
        """
        a = 'say "hi"'
        b = "plain"
        c = "both \\" and ' quotes"
        """
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
