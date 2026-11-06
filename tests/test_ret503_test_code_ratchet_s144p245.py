"""RM-1745 - ruff RET503 is held at zero in the test code.

RET503 (a function that returns a value on some path falls off its end on another) is held in production code by
tests/test_return_ratchet_s144p144.py, which leaves every test directory out of scope. Measured 2026-11-06 with
``ruff check --isolated --line-length 120 --select RET503`` (target py39): 11 findings in 11 test modules.

- Six unittest helpers searched a collection and ended on ``self.fail(...)``. ``self.fail`` raises, so the end of
  the function was never reached; each now spells that as ``raise self.failureException(...)``, which is exactly
  what ``TestCase.fail`` does.
- Four stub websocket ``recv`` coroutines ended on ``await asyncio.Event().wait()`` of an Event nobody sets, so
  they never resume; each now follows the await with ``raise AssertionError(...)``.
- One stub ``recv`` ended on ``await asyncio.sleep(3600)``; it now returns ``None`` explicitly (the value it
  already produced after the sleep).

Scope is the test directories only. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a
finding. The baseline only shrinks.
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

_RULES = "RET503"
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/", "agents/agent3_testing/suite/")
# file -> finding count that stays because another owner holds the file. Only shrinks.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "agents/daemon_slayer/tests/test_champ_ability_formula_p1l10.py",
    "agents/daemon_slayer/tests/test_focus_board.py",
    "agents/daemon_slayer/tests/test_kit_penetration_r190.py",
    "tests/test_config_validator.py",
    "tests/test_cross_mode_ds_p1l6.py",
    "tests/test_dashboard_error_scrub_rm134.py",
    "tests/test_obs_frame_source.py",
    "tests/test_obs_keep_warm_grab_failures_s144q48.py",
    "tests/test_obs_publisher_audit.py",
    "tests/test_p2w1_core_f.py",
    "tests/test_vision_obs_grab_reasons_s144q47.py",
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
    """The rule reports its pattern and stays quiet on the explicit spelling, so an empty result is a real scan."""
    bad = (
        "def f(xs, k):\n"
        "    for x in xs:\n"
        "        if x == k:\n"
        "            return x\n"
        "    print(k)\n"
    )
    good = bad + "    return None\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert [d["code"] for d in found] == ["RET503"]
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
