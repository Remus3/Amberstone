"""RM-1690 - ruff PLR0124 (a name compared with itself) is held at zero outside a named core/ baseline.

Not selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated --line-length 120`` over the tracked
production code (every tracked .py outside the test directories): 25 findings in 21 modules, all of them the
NaN test spelled ``v != v`` / ``v == v``.

Eight modules outside core/ are converted: tft/sources/eog_file.py, tft/tft_coach_engine.py,
tft/tft_final_board.py, tft/tft_live_analysis.py, dashboard/routes_tft.py, tools/gated_g101_cs_cards.py,
tools/gated_g314_tower_input.py and tools/gated_lx01_draft_check.py. A float operand becomes ``math.isnan(v)``
(or ``math.isfinite(f)`` where the same line also rejects both infinities). Where the operand can also be an int
(``_is_num`` in gated_g101, ``_num`` in gated_lx01) the replacement is
``not (isinstance(v, float) and math.isnan(v))``: ``math.isnan`` of an int beyond float range raises
OverflowError, ``v == v`` never did, so a bare ``math.isnan(v)`` would change behaviour.

The core/ modules in ``_BASELINE`` are left for a later slice (other lanes edit core/ in this session). The
baseline only shrinks: a new finding anywhere else fails, and an entry that stops offending fails
test_baseline_is_exact. The test code has its own ratchet (test_return_nan_idiom_ratchet_s144p172.py).
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

_RULE = "PLR0124"
_TEST_DIRS = ("tests/", "agents/daemon_slayer/tests/", "tools/tests/", "agents/agent3_testing/suite/")
# Measured 2026-11-05; each row is a core/ module that still spells the NaN test as a self-compare.
_BASELINE = {
    "core/champion_movespeed.py",
    "core/death_recap.py",
    "core/highlight_reel.py",
    "core/liveclient_cache.py",
    "core/macro_context.py",
    "core/mia_reachability.py",
    "core/minimap_identity.py",
    "core/self_cast_log.py",
    "core/vision_template_match.py",
    "core/vod_retention.py",
    "core/zoi_capability.py",
    "core/zoi_field.py",
    "core/zoi_influence.py",
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    assert any(rel.startswith("core/") for rel in tracked), "no tracked core module was seen"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_TEST_DIRS):
            counts[rel] += 1
    return dict(counts)


def test_no_new_self_compare_in_the_production_code(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULE} findings outside the baseline, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_converted_modules_use_the_named_spelling():
    """The eight converted modules import math and carry no bare self-compare of their operand."""
    for rel in (
        "tft/sources/eog_file.py", "tft/tft_coach_engine.py", "tft/tft_final_board.py",
        "tft/tft_live_analysis.py", "dashboard/routes_tft.py", "tools/gated_g101_cs_cards.py",
        "tools/gated_g314_tower_input.py", "tools/gated_lx01_draft_check.py",
    ):
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "\nimport math\n" in src, rel
        assert "math.isnan(" in src or "math.isfinite(" in src, rel


def test_int_operand_form_keeps_a_huge_int_a_number():
    """``v == v`` is True for any int; the float-guarded spelling must agree, where bare math.isnan raises."""
    huge = 10 ** 400
    with pytest.raises(OverflowError):
        math.isnan(huge)

    def is_num(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and not (isinstance(v, float) and math.isnan(v))

    assert is_num(huge) is True
    assert is_num(3) is True
    assert is_num(2.5) is True
    assert is_num(float("inf")) is True
    assert is_num(float("nan")) is False
    assert is_num(True) is False
    assert is_num("1") is False


def test_probe_is_live():
    """The rule reports the pattern and stays quiet on the sound spelling, so an empty result is a real scan."""
    bad = textwrap.dedent(
        """
        def g(v):
            return v != v
        """
    )
    good = textwrap.dedent(
        """
        import math

        def g(v):
            return math.isnan(v)
        """
    )
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == {_RULE}, found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
