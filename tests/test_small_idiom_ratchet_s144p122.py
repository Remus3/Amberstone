"""RM-1517 - five small-idiom ruff rules are held at a shrinking baseline.

None of these rules is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree, then this slice fixed the production
sites in 10 modules:

- PLC0207 ``s.split(sep)[0]`` splits more times than needed: now ``split(sep, 1)[0]``
  (``split(maxsplit=1)[0]`` for the whitespace form). Same first field.
- SIM118 ``k in d.keys()`` / ``for k in d.keys()``: now the dict itself.
- SIM212 ``'a' if not x else x``: now ``x or 'a'`` (same truthiness test).
- C400 ``list(<genexp>)``: now a list comprehension.
- FURB171 ``x in (a,)`` / ``x not in (a,)``: now ``==`` / ``!=``.

Not edited on purpose: ``agents/daemon_slayer`` and ``tools/ds_cross_eval`` (DS lane
territory) and test files; they are the exact baseline below. The three
``except Exception as exc: raise exc`` wrappers in the Brawl, Arena and ARAM
coaches (TRY203) are a FILING: removing them dedents a 230 - 400 line body.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. A new finding anywhere, or a
baseline file that offends more than it did, fails; a baseline entry that has
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

_RULES = ("PLC0207", "SIM118", "SIM212", "C400", "FURB171")
_FIXED = (
    "composition_advisor.py",
    "core/vod_retention.py",
    "dashboard/routes_pickban.py",
    "game_reader/snapshot_normalizer.py",
    "tft/tft_live_analysis.py",
    "tft/tft_scouting.py",
    "tools/backup_irreplaceable.py",
    "tools/compare_101qq_vs_ddragon.py",
    "tools/live_flip_watcher.py",
    "tools/probe_101qq_hero_rank_double.py",
    "tests/test_gated_lx09_mark_check.py",
    "tests/test_overlay_default_layout_collision.py",
    "tests/test_repin_subagent_cli_rm795.py",
    "tests/test_rm876_structural_mount_spellings.py",
    "tests/test_routes_state_health_scrub.py",
)
# file -> number of findings still there. Only shrinks.
_BASELINE = {
    "agents/daemon_slayer/engine.py": 1,
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
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
    for d in _ruff(["--select", ",".join(_RULES), "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
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


@pytest.mark.parametrize("rule, source", [
    ("PLC0207", "s = 'a#b'\nv = s.split('#')[0]\n"),
    ("SIM118", "d = {}\nv = 1 in d.keys()\n"),
    ("SIM212", "x = []\nv = 'a' if not x else x\n"),
    ("C400", "v = list(i for i in range(3))\n"),
    ("FURB171", "x = 1\nv = x in (1,)\n"),
])
def test_probe_is_live(rule, source):
    """The isolated run reports a minimal offender per rule, so an empty tree
    result is a clean tree and not a dead probe."""
    found = _ruff(["--select", rule, "--stdin-filename", "probe_mod.py", "-"], stdin=source)
    assert rule in {d["code"] for d in found}, found


@pytest.mark.parametrize("raw, want", [
    ("Name#TAG", "name"), ("Name#a#b", "name"), ("  Name ", "name"), ("#TAG", ""),
    ("", ""), (None, ""), (12345, ""),
])
def test_normalized_name_keeps_its_first_field(raw, want):
    from game_reader import snapshot_normalizer as sn

    assert sn._normalize_name(raw) == want


@pytest.mark.parametrize("seam, want", [
    ("targetfoo_bar_baz", "foo"), ("preset=x_y", "x"), ("plain", "plain"),
    ("target_x", "target_x"),
])
def test_live_flip_short_keeps_the_first_field(seam, want):
    from tools import live_flip_watcher

    assert live_flip_watcher._short(seam) == want
