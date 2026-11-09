"""S144-P-473 - no tracked ``.py`` assigns a ``lambda`` to a name (E731), outside a shrinking baseline.

ruff.toml ignores E731 ("intentional one-liners in RC") for the WHOLE tree. Measured 2026-11-08 with
``ruff check --isolated --select E731`` over every tracked ``.py``: 34 findings in 11 files, 3 of them production
(``coaches/aram_team_analyzer.py`` ``norm``, ``core/synergy_external_source.py`` ``_utcnow``, ``tools/drift_guard.py``
``_norm``) and the rest test stubs. A named lambda has no ``__name__`` of its own in a traceback (``<lambda>``), and
the ``_utcnow`` injectable clock is exactly the seam a test patches, so a ``def`` reads better in the one place it
matters. Those 27 sites in 9 files became ``def`` (or a small factory for the repeated stub shape); the 7 left are
DS tests another lane branch owns, held in ``_BASELINE`` (rel path -> count), which only shrinks.

The ratchet runs ruff with NO config, so the waiver cannot hide a hit, over the tracked files only:

- a file outside ``_BASELINE`` carries no lambda assignment;
- a ``_BASELINE`` file may not gain one, and an entry whose count dropped fails until it is lowered or dropped.

Fix a hit with a nested ``def`` (or a factory returning one); never an inline ``noqa``.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

# DS tests (lane/ds owns them while it has unlanded commits). The set only shrinks.
_BASELINE = {
    "agents/daemon_slayer/tests/test_build_recommendation_p1l5.py": 6,
    "agents/daemon_slayer/tests/test_engine_robustness_p1l12.py": 1,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", "E731", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _tracked_counts() -> Counter:
    # The whole tree on one command line is too long for Windows: lint ".", keep the tracked files.
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: Counter = Counter()
    for d in _ruff([".", "--exclude", "data,logs,ops/runtime"]):
        try:
            rel = relative_posix(Path(d["filename"]).resolve())
        except ValueError:
            continue
        if rel in tracked:
            counts[rel] += 1
    return counts


def test_no_new_lambda_assignment_and_the_baseline_only_shrinks():
    counts = _tracked_counts()
    new = {f: n for f, n in counts.items() if f not in _BASELINE}
    assert not new, f"a lambda is assigned to a name (use a def): {sorted(new.items())}"
    grew = {f: (counts[f], cap) for f, cap in _BASELINE.items() if counts[f] > cap}
    assert not grew, f"a baselined file gained a lambda assignment (found, cap): {grew}"
    healed = {f: (counts[f], cap) for f, cap in _BASELINE.items() if counts[f] < cap}
    assert not healed, f"lower or drop these _BASELINE entries (found, cap): {healed}"


@pytest.mark.parametrize(
    "code",
    [
        "f = lambda x: x\n",
        "def g():\n    h = lambda: None\n    return h\n",
        "_utcnow: object = lambda: 1\n",
    ],
)
def test_the_probe_is_live(code):
    """The isolated run flags each shape (the repo config would hide it), so an empty tree result is a clean tree,
    not a dead probe."""
    assert [d["code"] for d in _ruff(["--stdin-filename", "x.py", "-"], stdin=code)] == ["E731"]


def test_the_safe_spellings_are_not_flagged():
    code = (
        "def f(x):\n    return x\n\n\n"
        "g = sorted([1], key=lambda v: v)\n"
        "table = {'a': lambda: 1}\n"
    )
    assert _ruff(["--stdin-filename", "x.py", "-"], stdin=code) == []


def test_ruff_toml_still_waives_the_rule():
    """This ratchet exists because ruff.toml waives E731; if the waiver is lifted the ordinary lint covers it and
    this file should be retired, not left as a second copy."""
    text = (REPO_ROOT / "ruff.toml").read_text(encoding="utf-8")
    ignore_block = text.split("\nignore = [", 1)[1].split("\n]", 1)[0]
    assert '"E731"' in ignore_block


def test_baseline_files_exist():
    for rel in _BASELINE:
        assert (REPO_ROOT / rel).is_file(), rel
