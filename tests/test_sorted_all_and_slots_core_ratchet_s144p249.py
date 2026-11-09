"""RM-1748 - ruff RUF022 (unsorted ``__all__``) and RUF023 (unsorted ``__slots__``) held at zero in ``core/``.

Continues RM-1747 (``tools/``, ``lib/``, ``tft/``, ``game_reader/``, ``vision_server/``, ``agents/``). Measured
2026-11-06 with ``ruff check --isolated`` (target py39): 27 findings in 24 ``core/`` modules. This slice sorted 20
findings in 19 modules with ruff's own fix; the order of an ``__all__`` or ``__slots__`` carries no meaning for an
import or an attribute lookup, and no fixed module iterates its own ``__slots__`` (checked by grep).

NOT held, each for a named reason (a fixed ``_NOT_HELD`` list, so the exception cannot grow silently):

- ``core/game_snapshot.py``: frozen file (3 ``__slots__`` rows).
- ``core/metrics_cache.py``: ``MetricsSummary.to_dict`` iterates ``__slots__`` to build its dict, so the order IS the
  serialised key order; sorting it would change the output and the tuple carries comments ruff will not move.
- ``core/ds_antitank_hint.py``, ``core/ds_capability_gap.py``, ``core/macro_response.py``: NOT in this list any more
  (S144-P-598, 2026-11-09). They were deferred while the true-audit lane branch edited them; that branch carries no
  unlanded commit on any of the three, so each ``__all__`` is sorted with ruff's own fix and they joined the held set.

The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. The held scope has no baseline.
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

_RULES = ("RUF022", "RUF023")
_NOT_HELD = {
    "core/game_snapshot.py": "frozen",
    "core/metrics_cache.py": "to_dict iterates __slots__, so the order is the output order",
}
_FIXED = (
    "core/aram_balance_context.py",
    "core/aram_coach_shadow.py",
    "core/aram_item_interaction.py",
    "core/arena_augment_playline.py",
    "core/arena_coach_shadow.py",
    "core/ds_antitank_hint.py",
    "core/ds_calibration_agreement.py",
    "core/ds_capability_gap.py",
    "core/failed_load_gate.py",
    "core/feature_policy.py",
    "core/focus_board_live.py",
    "core/laning_cv_overrides.py",
    "core/lcu_events.py",
    "core/macro_response.py",
    "core/objective_playbook.py",
    "core/precomputed_build_coach.py",
    "core/precomputed_laning_coach.py",
    "core/riot_api.py",
    "core/shaper.py",
    "core/sr_aram_worker.py",
    "core/tft_worker.py",
    "core/ward_cue.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def core_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len([t for t in tracked if t.startswith("core/")]) > 50, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["core"]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel not in _NOT_HELD:
            counts[rel] += 1
    return dict(counts)


def test_core_has_no_unsorted_all_or_slots_outside_the_named_exceptions(core_counts):
    assert not core_counts, f"ruff {_RULES} findings in core/, file: count: {core_counts}"


def test_the_fixed_and_excepted_modules_are_tracked_core_modules():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in (*_FIXED, *_NOT_HELD):
        assert rel in tracked, rel
        assert rel.startswith("core/"), rel
    assert not set(_FIXED) & set(_NOT_HELD)


def test_metrics_cache_exception_is_still_true():
    """The order-is-output reason holds only while ``to_dict`` iterates ``__slots__``; if it stops, sort the tuple."""
    text = (REPO_ROOT / "core" / "metrics_cache.py").read_text(encoding="utf-8")
    assert "for name in self.__slots__:" in text


@pytest.mark.parametrize(
    ("rule", "probe"),
    [
        ("RUF022", "__all__ = ['b', 'a']\n"),
        ("RUF023", "class C:\n    __slots__ = ('b', 'a')\n"),
    ],
)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert any(d["code"] == rule for d in found), (rule, [d["code"] for d in found])
