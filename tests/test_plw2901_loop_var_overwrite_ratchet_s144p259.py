"""S144-P-259 - ruff PLW2901 (a ``for`` loop variable overwritten inside its own loop) held at a shrink-only baseline.

Measured 2026-11-06 with ``ruff check --isolated`` (target py39): 117 findings, 9 of them in the vendored kit
and the DS tree (fenced below); 97 remain in held scope after this slice. The first slice renamed the loop target to ``raw_line`` and kept the stripped value
under the old name in 11 sites across 10 modules (``core/branch_review.py``, ``core/coach_trace.py``,
``core/death_recap.py`` _read_jsonl, ``core/moment_marks.py`` x2, ``core/ds_calibration_agreement.py``,
``core/metrics_cache.py``, ``lib/ingest_receipt.py``, ``scripts/repair_tft_match_rows.py``, ``ops/loop/steer.py``,
``ops/loop/loop_controller.py``). Each was ``for line in X:`` then ``line = line.strip()``; the body only ever read
the stripped value, and ``line`` is still bound to it after the loop, so behaviour is unchanged.

The count per file can only fall: a file that reaches zero must leave ``_BASELINE``, and a new finding anywhere fails.
The held scope is every tracked ``.py`` file NOT under the two fences below. The run uses NO config (``--isolated``),
so a per-file-ignore cannot hide a finding.
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

_RULE = "PLW2901"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "agents/daemon_slayer/": "the DS lane's tree",
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE = {
    "agents/_supervisor_http.py": 1,
    "agents/agent1_lead/scheduler.py": 3,
    "coaches/adaptation_hint_digest.py": 2,
    "coaches/aram_coach.py": 1,
    "coaches/tft_coach.py": 1,
    "core/build_order_precompute.py": 1,
    "core/cohort_baseline.py": 1,
    "core/death_recap.py": 1,
    "core/log_scrub.py": 1,
    "core/patch_impact.py": 3,
    "dashboard/_deterministic_coaching.py": 1,
    "dashboard/routes_adaptive_summoners.py": 1,
    "dashboard/routes_diag.py": 1,
    "dashboard/routes_pickban.py": 1,
    "dashboard/routes_playstyle_labels.py": 1,
    "dashboard/routes_spike_curve.py": 1,
    "dashboard/routes_state.py": 1,
    "dashboard/server.py": 1,
    "docs/_rsc_score/calibrate.py": 2,
    "docs/_rsc_score/calibrate_rep.py": 1,
    "lcu/lcu_postgame_collector.py": 1,
    "ops/loop/repo_review.py": 2,
    "ops/rc_transactional_deploy.py": 1,
    "scripts/build_carry_benchmarks.py": 2,
    "scripts/rewind_catchup.py": 1,
    "tests/test_gated_lx05_tape_check.py": 1,
    "tests/test_pytest_per_run_temproot_rm878.py": 1,
    "tests/test_requirements_currency_rm515.py": 1,
    "tests/test_responder_grammar_table.py": 1,
    "tests/test_routes_state_audit_memo.py": 1,
    "tests/test_task_queue_gate_limbo_reconciler.py": 1,
    "tests/test_task_queue_reconciler.py": 1,
    "tests/test_text_line_endings.py": 1,
    "tests/test_tft_coach_lane8_cycle34.py": 1,
    "tests/test_vision_merge_augment_rehome_b01b.py": 1,
    "tests/test_web_js_unimported_calls_s144q43.py": 1,
    "tft/rounds/ground_truth.py": 1,
    "tft/tft_coach_engine.py": 3,
    "tft/tft_placement.py": 1,
    "tft/tft_prompt.py": 2,
    "tools/aram_shadow_report.py": 1,
    "tools/arena_shadow_report.py": 2,
    "tools/atlas_fonts.py": 1,
    "tools/build_third_party_notices.py": 4,
    "tools/champ_select_shadow_report.py": 1,
    "tools/ci_impact_selector.py": 1,
    "tools/ci_watchdog.py": 1,
    "tools/credential_history_scan.py": 1,
    "tools/det_coach_shadow_report.py": 1,
    "tools/ds_parity_run.py": 1,
    "tools/ds_wiki_staleness_check.py": 1,
    "tools/gated_ds_flag_eyeball.py": 1,
    "tools/gated_g237_lband_shadow.py": 1,
    "tools/gated_g313_mayhem_aug.py": 1,
    "tools/gated_g314_tower_input.py": 2,
    "tools/gated_lx05_tape_check.py": 2,
    "tools/gated_lx07_recap_check.py": 1,
    "tools/gated_tft15_planner.py": 1,
    "tools/gated_tft_qa_summary.py": 1,
    "tools/hz_shadow_report.py": 1,
    "tools/inbox_responder_runner.py": 2,
    "tools/laning_verdict_information_probe.py": 1,
    "tools/live_benchmark_band_report.py": 1,
    "tools/macro_response_shadow_report.py": 1,
    "tools/moon_sync_poller.py": 1,
    "tools/objective_playbook_shadow_report.py": 1,
    "tools/ocr_shadow_report.py": 1,
    "tools/rc_facts.py": 1,
    "tools/repin_subagent_cli.py": 1,
    "tools/replay_laning_verdict_validate.py": 2,
    "tools/replay_matchup_validate.py": 3,
    "tools/replay_pickban_validate.py": 2,
    "tools/repo_insights.py": 1,
    "tools/stop_claim_gate.py": 2,
}
_FIXED = (
    "core/branch_review.py",
    "core/coach_trace.py",
    "core/moment_marks.py",
    "core/ds_calibration_agreement.py",
    "core/metrics_cache.py",
    "lib/ingest_receipt.py",
    "scripts/repair_tft_match_rows.py",
    "ops/loop/steer.py",
    "ops/loop/loop_controller.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULE, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _in_scope(rel: str) -> bool:
    return not any(rel.startswith(prefix) for prefix in _NOT_THIS_SCOPE)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if _in_scope(t)}
    assert len(held) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULE} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_modules_are_clean_tracked_and_in_scope(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert _in_scope(rel), rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: the rule does fire on the pattern it exists for."""
    src = "for line in rows:\n    line = line.strip()\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=src)
    assert len(found) == 1 and found[0]["code"] == _RULE


def test_the_renamed_readers_still_strip_each_line(tmp_path):
    """Behaviour pin for the rename: surrounding whitespace is dropped and blank lines skipped."""
    from core.branch_review import _rows

    rows = list(_rows(['  {"a": 1}  ', "", "   ", '{"b": 2}\n', "not json", "[1]"]))
    assert rows == [{"a": 1}, {"b": 2}]
