"""FURB148 (unused enumerate half) and FURB145 (slice copy) hold at zero (S144-P-515).

Both are ruff PREVIEW rules and ruff.toml selects neither, so nothing held the count. FURB148 flags
``for i, x in enumerate(seq)`` where one half is never read (use ``for x in seq`` or
``for i in range(len(seq))``); FURB145 flags ``seq[:]`` used as a copy (use ``seq.copy()``).

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over every tracked ``.py`` file
(production, ``tests/``, ``tools/tests``, ``agents/daemon_slayer`` and ``agents/agent3_testing`` included): 5
findings in 5 files, all fixed here with no behaviour change (tft/cv/ocr_fields.py, tests/test_moon_sync_poller.py,
agents/agent3_testing/suite/test_round14.py, agents/daemon_slayer/tests/test_passive_heal_overrides_per_charge_item252.py,
tests/test_replay_build_order_validate_robustness.py). The baseline is empty, so it can only stay empty.

``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding. A probe pair proves the preview selection is live: an empty tree
result is then a real scan, not a rule that silently stopped being selectable. (ruff reports an unused
enumerate VALUE only for an underscore-named dummy, and a slice copy only of a binding it knows is a list, so
the probes are written that way.)
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

_RULES = "FURB148,FURB145"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_tree_has_no_findings():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = []
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            found.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not found, f"FURB148 / FURB145 findings (spell them out; the baseline is empty): {sorted(found)}"


def _probe(src: str) -> set[str]:
    return {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=src)}


def test_probe_sees_an_unused_enumerate_index():
    assert _probe("def f(xs):\n    for i, x in enumerate(xs):\n        print(x)\n") == {"FURB148"}


def test_probe_sees_an_unused_enumerate_value():
    assert _probe("xs = [1, 2]\nfor i, _x in enumerate(xs):\n    print(i)\n") == {"FURB148"}


def test_probe_sees_a_slice_copy():
    assert _probe("xs = [1, 2]\nys = xs[:]\n") == {"FURB145"}


def test_used_halves_and_copy_method_are_quiet():
    assert _probe(
        "def f(xs):\n    for i, x in enumerate(xs):\n        print(i, x)\n    return xs.copy()\n"
    ) == set()
