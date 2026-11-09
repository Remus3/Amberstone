"""RM-1542 - ruff RUF102, ISC003 and FURB157 are held at zero across the tracked tree.

None of the three is in ruff.toml's ``select``, so a finding could land unnoticed.
Measured 2026-11-05 with ``ruff check --isolated --select RUF102,ISC003,FURB157``
(target py39): 9 findings in 8 test modules, none in production code.

- RUF102: a ``# noqa: WPS433`` (a flake8-wemake code ruff does not know, so it
  suppressed nothing) on the deliberate in-test import of ``CoachChoice`` in the
  four ``test_{aram,arena,brawl,sr}_coach_choices_emit`` modules.
- ISC003: a string built with a leading ``+`` between two literals (five sites in
  three test modules); adjacent literals concatenate at compile time, same value.
- FURB157: ``decimal.Decimal("12")`` where ``decimal.Decimal(12)`` is the same value.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = "RUF102,ISC003,FURB157"
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "tests/test_aram_balance_fetch_failure.py",
    "tests/test_aram_coach_choices_emit.py",
    "tests/test_arena_coach_choices_emit.py",
    "tests/test_brawl_coach_choices_emit.py",
    "tests/test_sr_coach_choices_emit.py",
    "tests/test_ds_extract_lolmath_chunk_drift.py",
    "tests/test_ds_pick_consumption_p1l11.py",
    "tests/test_relay_age_true_audit_s144.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
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
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


def test_probe_is_live():
    """A minimal offender per rule is reported, so an empty tree result is a real scan."""
    probe = (
        "import decimal\n"
        "x = 'a' \\\n"
        "    + 'b'\n"
        "y = decimal.Decimal('12')\n"
        "z = 1  # noqa: WPS433\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["FURB157", "ISC003", "RUF102"]


def test_concatenated_javascript_fixtures_keep_their_value():
    """The merged literals in the DS chunk-drift fixture still form the same chunk text."""
    from tests import test_ds_extract_lolmath_chunk_drift as mod

    bodies = mod._split_bodies()
    root = bodies["u/root_meta.js"]
    assert root.startswith(',2,(a,i,e)=>{i.exports={Aatrox:"General",Ahri:"Squishy"}},3,(a,i,e)=>')
    assert ',4,a=>{"use strict";let i={Aatrox:{ratings:{healing:10,shielding:0}},Ahri:{ratings:' in root
    assert root.endswith(";}")


def test_brawl_prompt_inject_keeps_its_two_lines():
    from tests import test_ds_pick_consumption_p1l11 as mod

    out = mod._brawl_prompt_inject("a, b", "dps")
    assert out == "=== 0:00 | BRAWL ===\n\nDS top items (dps ranked, own-items-accounted): a, b"
