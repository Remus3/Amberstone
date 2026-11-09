"""RM-1689 - ruff SIM103 and PLR0124 are held at zero in the test code.

Neither is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120``
(target py39) over the tracked test code: 9 findings in 8 modules (TRY004 was measured too and deliberately NOT
taken - the ``AssertionError`` those helpers raise is a test FAILURE, ``TypeError`` would report an ERROR).

- SIM103 (5): ``if cond: return True`` / ``return False`` tails, now ``return cond``
  (agents/daemon_slayer/tests/test_antitank_axis_score_invariance_r196.py, tests/test_mojibake_hygiene.py x2,
  tests/test_smart_quote_hygiene.py x2).
- PLR0124 (4): a NaN test spelled ``v != v``, now ``math.isnan(v)``
  (tests/snapshot_panels/test_overlay_tft_view.py, tests/test_clamp_expression_ratchet_s144p124.py,
  tests/test_rm838_reply_scrub_ds.py, tests/test_wr_denominator_consistency.py). Every operand is a float, so the
  two spellings agree.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The production-side findings of
the same rules (ops/launcher, tft, tools) are out of this ratchet's scope.
"""
from __future__ import annotations

import collections
import importlib.util
import json
import math
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = ("SIM103", "PLR0124")
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/", "agents/agent3_testing/suite/")
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE: set[str] = set()


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
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


def test_no_new_sim103_or_plr0124_finding_in_the_test_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings in the test code, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_isnan_agrees_with_the_self_compare_it_replaced():
    """For every float, ``v != v`` and ``math.isnan(v)`` are the same answer, NaN and infinities included."""
    for v in (float("nan"), -float("nan"), float("inf"), -float("inf"), 0.0, -0.0, 1.5, -2.25):
        assert (v != v) == math.isnan(v)  # noqa: PLR0124 - the old spelling is the thing under comparison


def test_probe_is_live():
    """Each rule reports its pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = textwrap.dedent(
        """
        def f(x):
            if x.endswith("a"):
                return True
            return False

        def g(v):
            return v != v
        """
    )
    good = textwrap.dedent(
        """
        import math

        def f(x):
            return x.endswith("a")

        def g(v):
            return math.isnan(v)
        """
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
