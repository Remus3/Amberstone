"""RM-1411 - bugbear in ops/ + scripts/ and PIE790 are held at zero.

ruff.toml selects the whole B family but per-file-ignores it for ``ops/*.py`` and
``scripts/*.py`` ("procedural, bugbear too strict"), and ``ops/audit/...`` sits
under that glob, so a real bugbear finding there never surfaced. Measured
2026-11-04 with ``ruff check --isolated --select B`` (the config's own B ignores
kept): 4 B023 findings in one module, ops/audit/ds_perm_swarm/live_flip_eyeball.py
(two closures over the per-champion loop's ``champ`` / ``mode``; now
``functools.partial``). PIE790 (a ``pass`` after a docstring or a comment) is not
selected anywhere: 5 sites in 3 files, now dropped.

The ratchet runs ruff with NO config (``--isolated``, so the per-file-ignores
cannot hide anything) over the tracked ops/ and scripts/ .py files for the B
family minus the five rules ruff.toml ignores tree-wide on purpose, and over
every tracked .py for PIE790. Zero is the baseline: nothing is grandfathered.
"""
from __future__ import annotations

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

# The B rules ruff.toml ignores for the whole tree on purpose (same list).
_B_TREE_IGNORES = "B006,B007,B008,B027,B904"
_FIXED_B023 = "ops/audit/ds_perm_swarm/live_flip_eyeball.py"
_FIXED_PIE790 = (
    "coaches/_base_coach.py",
    "coaches/tft_coach.py",
    "tests/phase2_smoke/test_snapshot_translation.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _tracked(prefixes: tuple[str, ...]) -> list[str]:
    rels = sorted(relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",)))
    return [r for r in rels if r.startswith(prefixes)]


def _hits(findings: list[dict]) -> list[str]:
    out = []
    for d in findings:
        rel = d["filename"]
        try:
            rel = relative_posix(Path(rel).resolve())
        except ValueError:
            pass
        out.append(f"{rel}:{d['location']['row']} {d['code']}")
    return sorted(out)


@pytest.fixture(scope="module")
def ops_scripts_bugbear() -> list[dict]:
    files = _tracked(("ops/", "scripts/"))
    assert files, "no tracked ops/ or scripts/ .py - the tracked-file walk broke"
    return _ruff(["--select", "B", "--ignore", _B_TREE_IGNORES, *files])


@pytest.fixture(scope="module")
def pie790() -> list[dict]:
    # The whole tree on one command line is too long for Windows: lint ".", keep
    # the tracked files (the same filter the other ruff ratchets use).
    tracked = set(_tracked(("",)))
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = _ruff(["--select", "PIE790", "."])
    return [d for d in found if relative_posix(Path(d["filename"]).resolve()) in tracked]


def test_ops_and_scripts_carry_no_bugbear_finding(ops_scripts_bugbear):
    assert not ops_scripts_bugbear, (
        "bugbear finding in ops/ or scripts/ (ruff.toml's per-file-ignore hides it): "
        f"{_hits(ops_scripts_bugbear)}"
    )


def test_no_unnecessary_pass_statement(pie790):
    assert not pie790, f"PIE790 (a pass after a docstring / comment): {_hits(pie790)}"


@pytest.mark.parametrize("rel", [_FIXED_B023, *_FIXED_PIE790])
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_the_eyeball_no_longer_closes_over_the_loop():
    src = (REPO_ROOT / _FIXED_B023).read_text(encoding="ascii")
    assert "functools.partial(rank_items_by_burst" in src
    assert "functools.partial(rank_items," in src


def test_the_b_probe_is_live():
    """A B023 closure in an ops/ path IS flagged by the isolated run (and the
    repo config would hide it) - so an empty result above is a clean tree, not a
    dead probe."""
    code = (
        "fs = []\n"
        "for i in range(3):\n"
        "    def f():\n"
        "        return i\n"
        "    fs.append(f)\n"
    )
    found = _ruff(["--select", "B", "--ignore", _B_TREE_IGNORES,
                   "--stdin-filename", "ops/_probe.py", "-"], stdin=code)
    assert [d["code"] for d in found] == ["B023"]


def test_the_pie790_probe_is_live():
    code = 'def f():\n    """doc"""\n    pass\n'
    found = _ruff(["--select", "PIE790", "--stdin-filename", "x.py", "-"], stdin=code)
    assert [d["code"] for d in found] == ["PIE790"]
