"""RM-1679 - ruff RET504 and PLR1714 are held at zero in the test code.

Neither rule is in ruff.toml's ``select``. Measured 2026-11-05 with
``ruff check --isolated --line-length 120 --select RET504,PLR1714`` (target py39): 12 findings in
12 test modules under ``tests/``, ``agents/daemon_slayer/tests/`` and ``tools/tests/``.

- RET504 (9): a local assigned and returned on the next line. Inlined; the one trailing comment on
  such a return (tests/test_loadout_auto_keystone.py) moved above it.
- PLR1714 (3): ``a != b and a != c`` / ``x == p or y == p`` rewritten as one ``in`` / ``not in`` test
  against a tuple. Equivalent for the plain str / bytes values compared here (no NaN operand).

Scope is the test directories only; production modules are left to their owners. The run uses NO
config (``--isolated``) so a per-file-ignore cannot hide a finding, with ruff's 120-column budget set
to the project's. Two further findings of the same sweep sit in files another owner holds
(tests/conftest.py PLR5501, tests/test_launcher_key_read_rm810.py PIE810) and are not part of this
guard's rules.
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

_RULES = "RET504,PLR1714"
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/")
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "agents/daemon_slayer/tests/test_cc_conditional_wave14.py",
    "agents/daemon_slayer/tests/test_rank_mode_legality_p1l23.py",
    "agents/daemon_slayer/tests/test_spike_markers_2026_05_30.py",
    "tests/test_ds_extract_lolmath_ratings.py",
    "tests/test_loadout_auto_keystone.py",
    "tests/test_rank_tier_live_budget.py",
    "tests/test_rc_facts_missed_run_skip_s147.py",
    "tests/test_repair_spend_ledger.py",
    "tests/test_rune_pages_true_audit_s144t103.py",
    "tests/test_session_intents.py",
    "tests/test_shadow_archive_split_rm859.py",
    "tests/test_smart_quote_hygiene.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    assert any(rel.startswith(_TEST_DIRS) for rel in tracked), "no tracked test module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_TEST_DIRS):
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
    """Each rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = (
        "def f():\n"
        "    x = compute()\n"
        "    return x\n"
        "\n"
        "\n"
        "def g(a, b, c):\n"
        "    return a != b and a != c\n"
    )
    good = (
        "def f():\n"
        "    x = compute()\n"
        "    log(x)\n"
        "    return x\n"
        "\n"
        "\n"
        "def g(a, b, c):\n"
        "    return a not in (b, c)\n"
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert sorted(d["code"] for d in found) == ["PLR1714", "RET504"]
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
