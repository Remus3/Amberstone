"""FURB140 (``[f(*t) for t in it]`` spelled as a comprehension) holds at zero across the whole tree (S144-P-521).

FURB140 is a ruff PREVIEW rule and ruff.toml does not select it, so nothing held the count. It flags a
comprehension that only unpacks each item into a call, where ``itertools.starmap(f, it)`` says the same thing
(the same calls on the same tuples in the same order; the result is wrapped in ``list`` / ``set`` where a
list / set was built, so every consumer sees the same value).

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over every tracked ``.py`` file:
7 findings, one each in core/playstyle_labels.py, scripts/audit_ddragon_items.py, tft/rounds/schema.py,
tools/edit_lint_check.py, tests/test_gated_g101_cs_cards.py, tests/test_rank_tier_live_budget.py and
tests/test_tft_stage_gate_rm615.py. All seven are converted by S144-P-521, so the baseline is empty and can
only stay empty.

``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding. A probe pair proves the preview selection is live: an empty tree
result is then a real scan, not a rule that silently stopped being selectable.
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

_RULE = "FURB140"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
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
            found.append(f"{rel}:{d['location']['row']}")
    assert not found, f"FURB140 findings (use itertools.starmap(...); the baseline is empty): {sorted(found)}"


def _probe(src: str) -> set[str]:
    return {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=src)}


def test_probe_sees_a_starred_call_comprehension():
    assert _probe("pairs = [(1, 2)]\nout = [max(*p) for p in pairs]\n") == {"FURB140"}


def test_probe_sees_a_tuple_unpacking_comprehension():
    assert _probe("pairs = [(1, 2)]\nout = [pow(a, b) for a, b in pairs]\n") == {"FURB140"}


def test_starmap_is_quiet():
    src = "from itertools import starmap\npairs = [(1, 2)]\nout = list(starmap(pow, pairs))\n"
    assert _probe(src) == set()
