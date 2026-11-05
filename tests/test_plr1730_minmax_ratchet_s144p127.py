"""RM-1520 - ruff PLR1730 (an if-statement that is a hand-written min / max) is held at zero.

PLR1730 is not selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: 30 production sites in 17 modules spelled a
clamp as ``if x < 0: x = 0`` or ``if v > best: best = v``. This slice rewrote them as
``x = max(x, 0)`` / ``best = max(best, v)`` with the operand order that keeps the old
result for NaN (a NaN compares False both ways, so the variable keeps its value),
for -0.0 against 0.0 and for the int-versus-float tie (``max(a, b)`` returns ``a`` on
a tie, exactly as the unchanged variable did).

Scope: production code. ``tests/``, ``agents/daemon_slayer`` (DS lane), the
``agents/agent3_testing/suite`` test suite and ``tools/ds_cross_eval`` are out of scope.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. A new finding anywhere in scope, or
a baseline file that offends more than it did, fails; a baseline entry that has
stopped offending also fails until it is dropped, so the table only shrinks.
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

_RULES = ("PLR1730",)
_OUT_OF_SCOPE = (
    "tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "tools/ds_cross_eval/",
)
_FIXED = (
    "coach_integration/enemy_stats.py",
    "coaches/aram_coach.py",
    "coaches/arena_coach.py",
    "coaches/brawl_coach.py",
    "core/death_recap.py",
    "core/district_fusion.py",
    "core/lead_projection.py",
    "core/post_game_rubric.py",
    "core/precomputed_replay_narrative.py",
    "core/prompt_sanitize.py",
    "core/vision_atlas_precompute.py",
    "core/zoi_influence.py",
    "dashboard/routes_ds_profile.py",
    "dashboard/routes_personal_vs.py",
    "dashboard/routes_pickban.py",
    "dashboard/routes_spike_curve.py",
    "tools/screen_agent.py",
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
    "n = 3\nif n < 0:\n    n = 0\n",
    "b = 1.0\nv = 2.0\nif v > b:\n    b = v\n",
])
def test_probe_is_live(source):
    """The isolated run reports a minimal offender, so an empty tree result is a
    clean tree and not a dead probe."""
    found = _ruff(["--select", "PLR1730", "--stdin-filename", "probe_mod.py", "-"], stdin=source)
    assert "PLR1730" in {d["code"] for d in found}, found


_NAN = float("nan")


@pytest.mark.parametrize("level, armor, mr, max_hp, bonus_hp", [
    (-3, 45.0, 33.0, 1110.0, 510.0),   # below level 1 floors at level 1
    (1, 45.0, 33.0, 1110.0, 510.0),
    (9, 85.0, 57.0, 1990.0, 1390.0),
    (18, 130.0, 84.0, 2980.0, 2380.0),
    (40, 130.0, 84.0, 2980.0, 2380.0),  # above level 18 caps at level 18
])
def test_enemy_stats_level_clamp_keeps_its_table(level, armor, mr, max_hp, bonus_hp):
    from coach_integration import enemy_stats as es

    got = es.compute_enemy_stats("sr", 0.0, level)
    assert (got.armor, got.mr, got.max_hp, got.bonus_hp) == (armor, mr, max_hp, bonus_hp)


def test_enemy_stats_bonus_hp_override_is_capped_not_floored():
    from coach_integration import enemy_stats as es

    assert es.compute_enemy_stats("sr", 0.0, 18, bonus_hp_override=99999).bonus_hp == 3500.0
    assert es.compute_enemy_stats("aram", 0.0, 18, bonus_hp_override=5).bonus_hp == 5.0


@pytest.mark.parametrize("value, want", [
    (-5, ""), (-1, ""), (0, ""), (3, "abc"), (50, "abcdef"),
])
def test_prompt_sanitize_negative_max_len_floors_at_zero(value, want):
    from core import prompt_sanitize

    assert prompt_sanitize.clean("abcdef", max_len=value) == want


def test_lead_projection_clamps_keep_their_table():
    from core import lead_projection as lp

    base, _rate = lp.level_curve("SR")
    assert lp.minutes_for_level(base - 5.0) == 0.0
    assert lp.level_benchmark(10_000.0) == lp.MAX_CHAMPION_LEVEL
    assert lp.level_benchmark(-10.0) == lp.level_benchmark(0.0)


def test_max_keeps_the_old_nan_and_tie_behaviour():
    """The rewrite is only safe because max(x, bound) returns x when the compare
    is False, which is what the removed if-statement did."""
    assert max(_NAN, 0.0) != max(_NAN, 0.0)  # NaN stays NaN, as `if nan < 0` left it
    assert str(max(-0.0, 0.0)) == "-0.0"
    assert type(max(2, 2.0)) is int and type(min(2.0, 2)) is float
