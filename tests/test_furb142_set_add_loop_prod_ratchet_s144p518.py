"""FURB142 (``set.add`` in a ``for`` loop) holds at zero in production code (S144-P-518).

FURB142 is a ruff PREVIEW rule and ruff.toml does not select it, so nothing held the count. It flags
``for x in it: s.add(f(x))`` where ``s.update(f(x) for x in it)`` says the same thing in one statement
(``s`` is a set, so ``update`` of the same elements is equal, order never matters).

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over every tracked ``.py`` file:
32 findings. The 9 outside test code (scripts/audit_ddragon_items.py, scripts/rewind_scraper.py,
tools/ds_feed_watch.py (3), tools/gated_lx11_minimap_check.py, tools/md_guard_selector.py,
tools/probe_101qq_hero_rank_double.py, tools/validate_loadouts.py) are fixed here with no behaviour change.
The other 23 sit in test files (tests/, agents/daemon_slayer/tests) and are NOT held here: a later
cycle converts them and widens this scope. The baseline for the production scope is empty, so it can
only stay empty.

``ops/fleet_kit`` (vendored byte-for-byte) is out of scope. The run uses NO config (``--isolated``) so a
per-file-ignore cannot hide a finding. A probe pair proves the preview selection is live: an empty
tree result is then a real scan, not a rule that silently stopped being selectable.
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

_RULE = "FURB142"
_OUT_OF_SCOPE = ("ops/fleet_kit/",)


def _is_test_code(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    parts = rel.split("/")
    return "tests" in parts[:-1] or name.startswith("test_") or name == "conftest.py"


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


def test_production_tree_has_no_findings():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = []
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and not _is_test_code(rel):
            found.append(f"{rel}:{d['location']['row']}")
    assert not found, f"FURB142 findings in production code (use set.update(...); the baseline is empty): {sorted(found)}"


def test_scope_helper_separates_test_code():
    assert _is_test_code("tests/test_x.py")
    assert _is_test_code("agents/daemon_slayer/tests/test_y.py")
    assert _is_test_code("tools/tests/test_z.py")
    assert not _is_test_code("tools/ds_feed_watch.py")
    assert not _is_test_code("scripts/rewind_scraper.py")


def _probe(src: str) -> set[str]:
    return {d["code"] for d in _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=src)}


def test_probe_sees_a_set_add_loop():
    assert _probe("s = set()\nfor x in range(3):\n    s.add(x)\n") == {"FURB142"}


def test_probe_sees_a_set_add_of_a_computed_value():
    assert _probe("s = set()\nfor x in [1, 2]:\n    s.add(str(x))\n") == {"FURB142"}


def test_update_with_a_generator_is_quiet():
    assert _probe("s = set()\ns.update(str(x) for x in [1, 2])\n") == set()
