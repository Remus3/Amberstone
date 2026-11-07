"""RM-1415 - four flake8-comprehensions rules are held at zero.

None of these is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: 17 sites in 14 files, all fixed by
this slice, so the table is empty and any new site fails.

- C401 ``set(x for x in it)``: a set comprehension, no throwaway generator.
- C402 ``dict((k, v) for ...)``: a dict comprehension.
- C405 ``set((a, b))``: a set literal.
- C414 ``sorted(list(x))``: ``sorted`` already returns a new list.

C416 (``{k: v for k, v in pairs}``) is a sibling rule held by its own shrinking
baseline in tests/test_startswith_tuple_and_identity_comprehension_ratchet_
s144p114.py; it is not repeated here.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore
cannot hide a finding, and keeps only tracked files.
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

_RULES = "C401,C402,C405,C414"
_FIXED = (
    "agents/daemon_slayer/tests/test_ds_sweep_vamp_r193_cleave.py",
    "agents/daemon_slayer/tests/test_passive_health_overrides_r46.py",
    "core/prom_metrics.py",
    "dashboard/routes_pickban.py",
    "lcu/snapshot_shape.py",
    "ops/audit/lolmath_ds_sweep/gen_md.py",
    "tests/test_build_order_precompute.py",
    "tests/test_ci_watchdog.py",
    "tests/test_gated_g101_cs_cards.py",
    "tests/test_hz_mismatch_diagnose.py",
    "tests/test_loadout_ranged_only_melee_gate.py",
    "tests/test_playstyle_labels.py",
    "tools/ds_cross_eval/probe_champion.py",
    "tools/repo_insights.py",
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


def test_tree_has_no_redundant_collection_call():
    # The whole tree on one command line is too long for Windows: lint ".", keep
    # the tracked files (the filter the other ruff ratchets use).
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = []
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            found.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not found, f"ruff {_RULES}: {found}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("v = set(x for x in range(3))\n", "C401"),
        ("v = dict((x, x) for x in range(3))\n", "C402"),
        ("v = set((1, 2))\n", "C405"),
        ("v = sorted(list({3, 1}))\n", "C414"),
    ],
)
def test_each_probe_is_live(code, expected):
    """Each rule flags a minimal offender - so an empty tree result is a clean
    tree, not a dead probe."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=code)
    assert expected in {d["code"] for d in found}, found
