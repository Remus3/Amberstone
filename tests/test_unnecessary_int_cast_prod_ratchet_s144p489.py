"""RUF046 - a production ``int(round(x))`` is spelled ``round(x)`` (S144-P-489).

ruff.toml does not select RUF046 and no earlier ratchet covers it. In Python 3 the one-argument
``round`` already returns an ``int`` (for ``float``, ``Decimal`` and the numpy scalars the vision
code passes, numpy 2 included), so the outer ``int(...)`` is a no-op that makes the reader wonder
whether ``round`` could return a float. A NaN or infinity raises ``ValueError`` / ``OverflowError``
from ``round`` itself, so the failure mode is identical with and without the cast.

Measured 2026-11-09 with ``ruff check --isolated`` (target py39) over the tracked production tree:
71 findings in 42 files, every one an ``int(round(...))`` or similar already-int cast. This slice
drops the cast at the 29 sites in eight vision / minimap modules (the pixel-box arithmetic of
``core/minimap_blob_detect``, ``core/minimap_geometry``, ``core/minimap_identity``,
``core/vision_region_atlas``, ``core/vision_tesseract``, ``tft/tft_ocr_reader``,
``tft/tft_vision_reader`` and ``tools/vision_atlas_validate``). The rest sit in the baseline below,
which only shrinks: a row that stops offending fails ``test_baseline_is_exact`` until it is
dropped, and a new finding anywhere else fails ``test_no_new_findings``. ``agents/supervisor.py``
stays in the baseline because another lane branch changed it.

Slice 2 (S144-P-501) drops the cast at the 12 sites in ten core modules (aram_item_interaction_context,
death_recap, decision_detector, laning_cv_overrides, live_item_tape_store, operator_push,
precomputed_laning_coach, replay_seek, resolved_wr, self_cast_log); every site is ``int(round(x))`` over
a float, so the value and the type are the same and the NaN / infinity failure mode is unchanged.

Slice 3 (S144-P-502) drops the cast at the 14 sites in twelve more modules, three of them ``math.ceil`` /
``math.floor`` (which return ``int`` since Python 3): coach_integration/archetype_dispatch, core/math_core,
core/vision_template_match, core/zoi_influence, dashboard/_wave_timing, routes_ds_combo, routes_ds_shape,
routes_duo_synergy, routes_pickban (two sites), routes_replay_events, tft/engine/recommend and
tft/tft_scouting (two sites).

Slice 4 (S144-P-503) drops the cast at the 13 sites in nine files (ops/audit/ds_latency_probe,
ops/loop/lane_progress, scripts/postmortem_analyze (two), tools/gated_g239_wave_clock (two),
tools/gated_g241_ocr_native, tools/gated_lx04_cast_check, tools/gated_lx11_minimap_check (three,
two on one line), tools/repair_spend_ledger, tools/run_phase2_perf); no other lane branch
changed any of them. The baseline then kept agents/supervisor.py (another lane branch changed it)
and the two cdragon extractors (slice 5 below clears the extractors).

Slice 5 (S144-P-506) drops the cast at the last two sites outside ``agents/supervisor.py``:
``tools/daemon_slayer_cdragon_ratio_extract.py`` (``enum = round(si)``) and
``tools/daemon_slayer_cdragon_spell_extract.py`` (``out.append(round(n))``); both ``_num`` helpers return a
``float``, so the NaN / infinity failure mode is unchanged. No lane branch changes either file (measured
``git log main..lane/<x> --`` over every lane), so the baseline keeps one row: ``agents/supervisor.py``.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the
vendored ``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run
uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULE = "RUF046"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (module docstring). Only shrinks.
_BASELINE = {
    "agents/supervisor.py": 1,
}
_FIXED = (
    "coach_integration/archetype_dispatch.py",
    "ops/audit/ds_latency_probe.py",
    "ops/loop/lane_progress.py",
    "scripts/postmortem_analyze.py",
    "tools/gated_g239_wave_clock.py",
    "tools/gated_g241_ocr_native.py",
    "tools/gated_lx04_cast_check.py",
    "tools/gated_lx11_minimap_check.py",
    "tools/repair_spend_ledger.py",
    "tools/run_phase2_perf.py",
    "core/aram_item_interaction_context.py",
    "core/death_recap.py",
    "core/decision_detector.py",
    "core/laning_cv_overrides.py",
    "core/live_item_tape_store.py",
    "core/math_core.py",
    "core/minimap_blob_detect.py",
    "core/minimap_geometry.py",
    "core/minimap_identity.py",
    "core/operator_push.py",
    "core/precomputed_laning_coach.py",
    "core/replay_seek.py",
    "core/resolved_wr.py",
    "core/self_cast_log.py",
    "core/vision_region_atlas.py",
    "core/vision_template_match.py",
    "core/vision_tesseract.py",
    "core/zoi_influence.py",
    "dashboard/_wave_timing.py",
    "dashboard/routes_ds_combo.py",
    "dashboard/routes_ds_shape.py",
    "dashboard/routes_duo_synergy.py",
    "dashboard/routes_pickban.py",
    "dashboard/routes_replay_events.py",
    "tft/engine/recommend.py",
    "tft/tft_ocr_reader.py",
    "tft/tft_scouting.py",
    "tft/tft_vision_reader.py",
    "tools/vision_atlas_validate.py",
    "tools/daemon_slayer_cdragon_ratio_extract.py",
    "tools/daemon_slayer_cdragon_spell_extract.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin,
        check=False, **kwargs,
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
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert (REPO_ROOT / rel).is_file(), f"{rel} missing - update _FIXED"
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "def f(x):\n    return int(round(x))\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
    ok = "def f(x):\n    return round(x)\n"
    assert not _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=ok)


@pytest.mark.parametrize("value", [2.5, 3.5, -2.5, 0.49999, 1e15])
def test_round_alone_is_the_same_int(value):
    """The change is behaviour-neutral: one-argument round() is already an int."""
    assert round(value) == int(round(value))
    assert type(round(value)) is int


def test_round_of_numpy_scalar_is_an_int():
    np = pytest.importorskip("numpy")
    for scalar in (np.float32(2.5), np.float64(7.5)):
        assert type(round(scalar)) is int
        assert round(scalar) == int(round(scalar))
