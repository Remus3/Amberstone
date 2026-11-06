"""RM-1519 - ruff FURB136 (a hand-written min / max) is held at a shrinking baseline.

FURB136 is not selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: ten production sites in nine modules
spelled a clamp as ``x if x > 0 else 0``, ``a if a < b else b`` and the like.
This slice rewrote them as ``max`` / ``min`` with the operand order that keeps
the old result for NaN and for the int-versus-float tie (``max(0, n)`` returns
the literal 0 when ``n`` is 0.0 or NaN, exactly as the conditional did).

Scope: production code. ``tests/``, ``agents/daemon_slayer`` (DS lane, five
sites left), the ``agents/agent3_testing/suite`` test suite and
``tools/ds_cross_eval`` are out of scope.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. A new finding anywhere in scope, or
a baseline file that offends more than it did, fails; a baseline entry that has
stopped offending also fails until it is dropped, so the table only shrinks.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("FURB136",)
_OUT_OF_SCOPE = (
    "tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "core/district_fusion.py",
    "core/lcu_pool.py",
    "core/lead_projection.py",
    "core/minimap_districts.py",
    "core/objective_playbook.py",
    "lcu/draft_log.py",
    "lcu/lcu_pregame.py",
    "tft/local_player.py",
    "tools/mine_event_patterns.py",
)
# file -> number of findings still there. Only shrinks. Empty: nothing in scope offends.
_BASELINE: dict[str, int] = {}


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


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_file_gains_a_finding(tree_counts):
    worse = {f: (n, _BASELINE.get(f, 0)) for f, n in tree_counts.items()
             if n > _BASELINE.get(f, 0)}
    assert not worse, f"ruff {_RULES}, file: (now, baseline): {worse}"


def test_baseline_is_exact_so_it_only_shrinks(tree_counts):
    stale = {f: (tree_counts.get(f, 0), n) for f, n in _BASELINE.items()
             if tree_counts.get(f, 0) != n}
    assert not stale, f"lower or drop these baseline rows, file: (now, baseline): {stale}"


def test_fixed_modules_stay_clean(tree_counts):
    assert not [f for f in _FIXED if f in tree_counts]


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("source", [
    "n = 3\nv = n if n > 0 else 0\n",
    "a, b = 1.0, 2.0\nv = a if a < b else b\n",
])
def test_probe_is_live(source):
    """The isolated run reports a minimal offender, so an empty tree result is a
    clean tree and not a dead probe."""
    found = _ruff(["--select", "FURB136", "--stdin-filename", "probe_mod.py", "-"], stdin=source)
    assert "FURB136" in {d["code"] for d in found}, found


_NAN = float("nan")


@pytest.mark.parametrize("value, want", [
    (5, 5), (0, 0), (-3, 0), (2.9, 2), (-0.5, 0), ("7", 7), ("x", 0), (None, 0),
])
def test_district_fusion_int0_keeps_its_table(value, want):
    from core import district_fusion

    assert district_fusion._int0(value) == want


@pytest.mark.parametrize("value, want", [
    (3, 3), (0, 0), (-1, 0), (True, 0), ("3", 0), (None, 0), (2.9, 2),
])
def test_objective_playbook_count_keeps_its_table(value, want):
    from core import objective_playbook

    assert objective_playbook._count({"k": value}, "k") == want


@pytest.mark.parametrize("value, want", [
    (4, 4), (0, 0), (-4, 0), (True, 0), (3.0, 3), (3.5, 0), (_NAN, 0), (None, 0), ("9", 9),
])
def test_lcu_pregame_as_int_keeps_its_table(value, want):
    from lcu import lcu_pregame

    assert lcu_pregame._as_int(value) == want


@pytest.mark.parametrize("value, want", [
    (12, 12), (0, 0), (-12, 0), (True, 0), (7.0, 7), (7.5, 0), ("34", 34), ("-1", 0), ("x", 0),
])
def test_local_player_real_id_keeps_its_table(value, want):
    from tft import local_player

    assert local_player.real_id(value) == want


@pytest.mark.parametrize("value, want", [
    (-0.5, 0.0), (0.0, 0.0), (0.4, 0.4), (1.0, 1.0), (1.7, 1.0),
])
def test_minimap_clamp01_keeps_its_table(value, want):
    from core import minimap_districts

    assert minimap_districts._clamp01(value) == want
    assert type(minimap_districts._clamp01(value)) is float


def test_minimap_clamp01_lets_nan_through_as_before():
    from core import minimap_districts

    out = minimap_districts._clamp01(_NAN)
    assert math.isnan(out)  # NaN is neither below 0 nor above 1: unchanged


def test_draft_log_session_game_id_keeps_its_table():
    from lcu import draft_log

    assert draft_log.session_game_id({"gameId": 99}) == 99
    assert draft_log.session_game_id({"gameId": -5}) == 0
    assert draft_log.session_game_id({}) == 0
    assert draft_log.session_game_id(None) == 0


def test_lead_projection_level_benchmark_is_capped_and_floored():
    from core import lead_projection as lp

    assert lp.level_benchmark(-10.0) == lp.level_benchmark(0.0)
    assert lp.level_benchmark(10_000.0) == lp.MAX_CHAMPION_LEVEL
    assert lp.level_benchmark(_NAN) == lp.MAX_CHAMPION_LEVEL  # NaN fell to the cap before too


def test_lead_projection_minutes_for_level_never_goes_negative():
    from core import lead_projection as lp

    base, _rate = lp.level_curve("SR")
    assert lp.minutes_for_level(base - 5.0) == 0.0
    assert lp.minutes_for_level(base) == 0.0
    assert lp.minutes_for_level(base + 3.0) > 0.0


def test_mine_event_patterns_verdict_survives_a_zero_loss_mean():
    from tools import mine_event_patterns as mep

    got = mep.verdict([1.0, 2.0, 3.0], [-1.0, 0.0, 1.0], 3, 0.1, 0.5)
    assert got["verdict"] == "SEPARATES"  # denominator floors at 1e-9, no ZeroDivisionError
    assert mep.verdict([1.0, 2.0], [0.0, 0.0], 3, 0.1, 0.5)["verdict"] == "INSUFFICIENT"
