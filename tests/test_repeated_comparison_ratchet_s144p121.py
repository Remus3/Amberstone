"""RM-1420 - PLR1714 (repeated ``x == a or x == b``) is held at a shrinking baseline.

PLR1714 is not selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: 17 sites in 16 files. This slice
rewrote 11 sites in 10 production modules as one membership test against a
TUPLE (``x in (a, b)``). A tuple, not the set literal ruff suggests: ``in`` on a
tuple compares with ``==`` exactly like the chain it replaces and accepts an
unhashable operand, where a set literal would raise TypeError on one.

Out of this slice on purpose (not edited by it): ``ops/fleet_kit/`` (vendored
byte-for-byte), ``core/match_metrics.py`` and ``dashboard/routes_replay_events.py``
(changed by the true-audit lane branch awaiting landing) and three test files.

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

_RULE = "PLR1714"
_FIXED = (
    "core/damage_mix.py",
    "core/prompt_sanitize.py",
    "core/vision_tesseract.py",
    "dashboard/builders_last_match.py",
    "dashboard/routes_static.py",
    "tft/tft_state_reader.py",
    "tools/gated_rm869_vision_fields.py",
    "tools/replay_laning_verdict_validate.py",
    "tools/repo_insights.py",
    "tools/strip_smart_quotes.py",
)
# file -> number of findings still there. Only shrinks.
_BASELINE = {
    "ops/fleet_kit/fleet_suite_gate.py": 1,
}


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
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_file_gains_a_finding(tree_counts):
    worse = {f: (n, _BASELINE.get(f, 0)) for f, n in tree_counts.items()
             if n > _BASELINE.get(f, 0)}
    assert not worse, f"ruff {_RULE}, file: (now, baseline): {worse}"


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


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is
    a clean tree and not a dead probe."""
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"],
                  stdin="x = 'a'\nv = x == 'a' or x == 'b'\n")
    assert _RULE in {d["code"] for d in found}, found


def test_tuple_membership_accepts_an_unhashable_operand():
    """Why the rewrites use a tuple: a set literal would raise on a list."""
    operand = ["MAGIC"]
    assert (operand in ("MAGIC", "MAGICAL")) is False
    with pytest.raises(TypeError):
        operand in {"MAGIC", "MAGICAL"}  # noqa: B015


@pytest.mark.parametrize("raw, want", [
    ("MAGIC", "magical"), ("magical", "magical"), (" Magic ", "magical"),
    ("PHYSICAL", "physical"), ("TRUE", "true"), ("", ""), (None, ""), ("ARCANE", ""),
])
def test_damage_type_normalizer_keeps_its_truth_table(raw, want):
    from core import damage_mix

    assert damage_mix._normalize_damage_type(raw) == want


@pytest.mark.parametrize("ch, want", [("\n", "\n"), ("\t", "\t"), ("\r", " "), (" ", " "), ("a", "a")])
def test_prompt_sanitize_keeps_newline_and_tab_and_blanks_other_space(ch, want):
    from core import prompt_sanitize

    assert prompt_sanitize._strip_char(ch) == want


@pytest.mark.parametrize("path, want", [
    ("/", True), ("/index.html", True), ("/?x=1", True), ("/index.html?x=1", True),
    ("/index.htm", False), ("/api/state", False), ("", False),
])
def test_index_matcher_keeps_its_truth_table(path, want):
    from dashboard import routes_static

    assert routes_static._index_matcher(path) is want
