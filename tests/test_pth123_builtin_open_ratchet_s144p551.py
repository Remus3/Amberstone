"""S144-P-551 - ruff PTH123 (builtin open) held at a named baseline.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39): 269 findings across the tree. Ten sites in
nine files became ``Path(x).open(...)``: the plain text reads of the lolmath sweep probes and the audit one-shots
(``ops/audit/lolmath_ds_sweep/g2_remeasure_probe.py``, ``g7_comp_harness.py``, ``gen_md.py`` read and its one LF write,
``ops/audit/opponent_prior_gonogo.py``, ``ops/audit/p3c24_token_equiv.py``) and four test helpers
(``tests/test_aram_item_interaction.py``, ``tests/test_lane_launcher.py``, ``tests/test_vision_profile_derive.py``,
``tests/test_vision_profile_seeds.py``). ``Path.open`` is ``io.open`` with the path bound, so mode, encoding and the
keyword ``newline="\n"`` behave as the builtin did (pinned below on real bytes). A ``newline`` is always passed by
keyword, never positionally (the CRLF-harness trap RM-2037 class 2 folded).

The rest stays baselined by group, each with its reason in ``_BASELINE``. The baseline only shrinks: ANY new finding, or
a further finding in a baselined file, fails ``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``)
so a per-file-ignore cannot hide a finding, and ``--preview`` because the PTH family differs under it.
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

_RULES = "PTH123"
# Scopes fenced for a named reason; a new entry needs its reason here.
_NOT_THIS_SCOPE = {
    "ops/fleet_kit/": "vendored byte-for-byte, pinned by ops/fleet_kit/MANIFEST.json",
}
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    # FROZEN files (CLAUDE.md): not edited from a lane
    "ops/rc_dev_runtime.py": 1,
    "ops/rc_supervisor.py": 1,
    # packaging owner's (ops/launcher/*, rc-shell/*): excluded from lane edits
    "ops/launcher/service_host.py": 2,
    "ops/launcher/updater.py": 4,
    # atomic-IO implementations and fault-injection seams: they open by builtin name on purpose (builtins.open, never a Path method under test) and the atomic-write guard keys on these shapes
    "core/polled_json.py": 1,
    "ops/rc_transactional_deploy.py": 5,
    "oss/win32_atomic_io/src/win32_atomic_io/_atomic.py": 1,
    "oss/win32_atomic_io/tests/_fault_scope.py": 2,
    "tests/_replace_faults.py": 3,
    "tests/test_live_write_tracer_selftest.py": 3,
    "tests/test_rm464_scoped_path_fault.py": 2,
    # the file was changed on another lane branch at measurement time (git diff main...lane/<x>): that lane's, converted once it lands
    "core/ds_calibration.py": 1,
    "dashboard/routes_loop_status.py": 1,
    "ops/loop/loop_controller.py": 2,
    "tools/ds_allyamp_build.py": 2,
    "tools/ds_antitank_build.py": 2,
    "tools/ds_cc_output_build.py": 2,
    "tools/ds_extendedduel_build.py": 2,
    "tools/ds_mobility_build.py": 2,
    "tools/ds_objdamage_build.py": 2,
    "tools/ds_scaling_build.py": 2,
    "tools/ds_sustain_build.py": 2,
    "tools/ds_threatrange_build.py": 2,
    "tools/ds_waveclear_build.py": 2,
    "tools/ds_zonecontrol_build.py": 2,
    "tools/sibling_name_sweep.py": 1,
    "tools/stop_claim_gate.py": 4,
    # unconverted: binary / exclusive-create / handle-held opens and writers that other ratchets (RM-481 LF, RM-258 atomic) read by shape, plus plain reads not yet swept
    "agents/daemon_slayer/tests/test_aa_empower_authored_item258.py": 2,
    "agents/daemon_slayer/tests/test_ability_amp_overrides_2026_05_31.py": 1,
    "agents/daemon_slayer/tests/test_anivia_egg_resist_item316.py": 1,
    "agents/daemon_slayer/tests/test_bruiser_mitigation_item262.py": 1,
    "agents/daemon_slayer/tests/test_cc_conditional_wave12.py": 5,
    "agents/daemon_slayer/tests/test_cc_conditional_wave13.py": 9,
    "agents/daemon_slayer/tests/test_cc_conditional_wave14.py": 2,
    "agents/daemon_slayer/tests/test_cc_conditional_wave15.py": 2,
    "agents/daemon_slayer/tests/test_cc_conditional_wave16.py": 5,
    "agents/daemon_slayer/tests/test_cc_conditional_wave17.py": 3,
    "agents/daemon_slayer/tests/test_cc_conditional_wave7_tags.py": 1,
    "agents/daemon_slayer/tests/test_cross_spell_amp_item257.py": 2,
    "agents/daemon_slayer/tests/test_effects_expansion.py": 1,
    "agents/daemon_slayer/tests/test_enchanter_pool_hsp_rm90.py": 1,
    "agents/daemon_slayer/tests/test_geometry_item232.py": 1,
    "agents/daemon_slayer/tests/test_hps_ability_wire.py": 1,
    "agents/daemon_slayer/tests/test_item_proc_heal_rm103.py": 2,
    "agents/daemon_slayer/tests/test_kit_conversion_gate_rm86.py": 2,
    "agents/daemon_slayer/tests/test_mana_haste_item234.py": 1,
    "agents/daemon_slayer/tests/test_mana_sim.py": 1,
    "agents/daemon_slayer/tests/test_mode_modifiers_item232.py": 1,
    "agents/daemon_slayer/tests/test_null_damage_type_overrides_2026_05_31.py": 1,
    "agents/daemon_slayer/tests/test_passive_damage_bilinear_item248.py": 1,
    "agents/daemon_slayer/tests/test_passive_damage_caster_resist_item513.py": 1,
    "agents/daemon_slayer/tests/test_passive_damage_exotic_item247.py": 1,
    "agents/daemon_slayer/tests/test_passive_damage_per_stack_item249.py": 2,
    "agents/daemon_slayer/tests/test_passive_heal_overrides_as_aware_item253.py": 2,
    "agents/daemon_slayer/tests/test_passive_heal_overrides_item250.py": 2,
    "agents/daemon_slayer/tests/test_passive_heal_overrides_per_charge_item252.py": 2,
    "agents/daemon_slayer/tests/test_passive_shield_overrides_item260.py": 2,
    "agents/daemon_slayer/tests/test_quinn_rm89_a20.py": 1,
    "agents/daemon_slayer/tests/test_rank_assassin_runes.py": 1,
    "agents/daemon_slayer/tests/test_rune_procs.py": 2,
    "agents/daemon_slayer/tests/test_rune_procs_expansion.py": 2,
    "agents/daemon_slayer/tests/test_rune_procs_per_attack.py": 2,
    "agents/daemon_slayer/tests/test_rune_procs_shield_bash_dsp4.py": 2,
    "agents/daemon_slayer/tests/test_staged_amp_block_route_item246.py": 1,
    "agents/daemon_slayer/tests/test_target_vulnerability_overrides_r12.py": 2,
    "agents/daemon_slayer/tests/test_target_vulnerability_overrides_r43.py": 2,
    "coaches/_base_coach.py": 1,
    "core/death_patterns_loader.py": 1,
    "core/death_recap.py": 2,
    "core/ds_calibration_agreement.py": 1,
    "core/hud_settings.py": 1,
    "core/league_settings.py": 1,
    "core/live_session_recorder.py": 2,
    "core/rofl_stats_backfill.py": 1,
    "dashboard/routes_diag.py": 1,
    "dashboard/routes_recordings.py": 1,
    "dashboard/routes_static.py": 1,
    "lib/ingest_receipt.py": 2,
    "ops/audit/p2w5_partition.py": 2,
    "ops/audit/p2w5h2_partition.py": 3,
    "ops/loop/headless_env.py": 1,
    "ops/loop/lane_run_ledger.py": 2,
    "ops/loop/lanes.py": 1,
    "ops/loop/queue_loop.py": 1,
    "ops/loop/slots.py": 1,
    "ops/loop/steer.py": 1,
    "tests/_basetemp_guard.py": 1,
    "tests/test_agent_task_log_retention.py": 1,
    "tests/test_atomic_write_guard_rm258_rm261.py": 1,
    "tests/test_build_order_boots.py": 1,
    "tests/test_coach_parse_json_fence.py": 1,
    "tests/test_coach_trace_lf_s144p186.py": 1,
    "tests/test_death_recap_rm608.py": 1,
    "tests/test_decision_detector_lane8_cycle12.py": 1,
    "tests/test_decisions_log_tail_rm238.py": 2,
    "tests/test_ds_calibration_log_lf_s144p185.py": 1,
    "tests/test_event_callouts.py": 1,
    "tests/test_fleet_test_guard_lane_driver_rm874.py": 2,
    "tests/test_hook_invocation_log.py": 1,
    "tests/test_inbox_responder_runner.py": 2,
    "tests/test_item_wpa.py": 1,
    "tests/test_log_appenders_lf_s144p195.py": 1,
    "tests/test_log_rotation_rm718a.py": 2,
    "tests/test_loop_control_contention.py": 1,
    "tests/test_moon_sync_poller.py": 1,
    "tests/test_ops_audit_perm_swarm_runners_atomic_s144p208.py": 1,
    "tests/test_performance_tracker_lane8_cycle23.py": 1,
    "tests/test_queue_loop.py": 2,
    "tests/test_repin_designed_negative_rc5.py": 1,
    "tests/test_repin_subagent_cli_rm795.py": 2,
    "tests/test_rune_wpa.py": 1,
    "tests/test_shadow_appenders_lf_s144p190.py": 1,
    "tests/test_silent_except_arena_augment_cache.py": 1,
    "tests/test_spell_prefs_atomic_rm297d.py": 1,
    "tests/test_steer_channel.py": 3,
    "tests/test_stop_claim_gate_subagent_evidence_rm687.py": 1,
    "tests/test_summspell_wpa.py": 1,
    "tests/test_tft_sources_tft_log.py": 5,
    "tests/test_tracked_writer_lf_sweep.py": 1,
    "tests/test_vision_profile_2560_ocr_boxes.py": 2,
    "tft/rounds/store.py": 1,
    "tft/sources/tft_log.py": 1,
    "tools/bot_merge_check.py": 1,
    "tools/build_portable.py": 1,
    "tools/ci_impact_selector.py": 1,
    "tools/det_coach_shadow_report.py": 1,
    "tools/inbox_responder_runner.py": 2,
    "tools/landing_sampler.py": 2,
    "tools/moon_sync_poller.py": 3,
    "tools/phase_watcher.py": 1,
    "tools/pytest_guard.py": 1,
    "tools/shadow_archive_split.py": 1,
}
_FIXED = (
    "ops/audit/lolmath_ds_sweep/g2_remeasure_probe.py",
    "ops/audit/lolmath_ds_sweep/g7_comp_harness.py",
    "ops/audit/lolmath_ds_sweep/gen_md.py",
    "ops/audit/opponent_prior_gonogo.py",
    "ops/audit/p3c24_token_equiv.py",
    "tests/test_aram_item_interaction.py",
    "tests/test_lane_launcher.py",
    "tests/test_vision_profile_derive.py",
    "tests/test_vision_profile_seeds.py",
    # S144-P-552: plain text / binary reads of tools/ and the four tools/tests extractor `__file__` source reads
    "tools/p3_ascii_census.py",
    "tools/p3_ascii_sweep.py",
    "tools/perseus_sync.py",
    "tools/tests/test_cdragon_ratio_extract.py",
    "tools/tests/test_cdragon_spell_extract.py",
    "tools/tests/test_wiki_ability_extract.py",
    "tools/tests/test_wiki_stats_extract.py",
    # S144-P-553: eleven more tools/ opens (binary hash / line reads, plain JSON reads, five LF writes with keyword newline)
    "tools/build_python_embed.py",
    "tools/ds_cc_conditional_to_json.py",
    "tools/hz_shadow_arena_contamination.py",
    "tools/live_write_tracer.py",
    "tools/logger_leak_census.py",
    "tools/precommit_gate.py",
    "tools/truth_gate.py",
    # S144-P-554: ten daemon_slayer tests whose single open is the module-source read of an ASCII / source-text pin (binary or utf-8 text)
    "agents/daemon_slayer/tests/test_passive_heal_overrides_linear_item251.py",
    "agents/daemon_slayer/tests/test_passive_heal_overrides_linear_reopen_item254.py",
    "agents/daemon_slayer/tests/test_passive_mitigation_overrides_item261.py",
    "agents/daemon_slayer/tests/test_passive_resist_form_gated_item271.py",
    "agents/daemon_slayer/tests/test_passive_resist_overrides_item264.py",
    "agents/daemon_slayer/tests/test_passive_resist_per_stack_item272.py",
    "agents/daemon_slayer/tests/test_passive_resist_unlabeled_block_item270.py",
    "agents/daemon_slayer/tests/test_passive_revive_overrides_item288.py",
    "agents/daemon_slayer/tests/test_passive_survival_window_overrides_item293.py",
    "agents/daemon_slayer/tests/test_phantom_residual_2026_05_31.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
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
    assert not over, f"ruff {_RULES} findings above the baseline, file: count: {over}"


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
    """A positive control: the rule fires on the pattern the baseline exists for."""
    probe = "with open('a', encoding='utf-8') as fh:\n    fh.read()\n"
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert [d["code"] for d in found] == ["PTH123"]


def test_path_open_reads_text_like_the_builtin(tmp_path):
    """The converted reads: same text, CRLF folded to LF by universal newlines."""
    src = tmp_path / "in.json"
    src.write_bytes(b'{"a": 1}\r\n')
    with open(src, encoding="utf-8") as old:  # noqa: PTH123 - the control
        expected = old.read()
    with Path(str(src)).open(encoding="utf-8") as new:
        assert new.read() == expected == '{"a": 1}\n'


def test_path_open_keyword_newline_writes_lf_bytes(tmp_path):
    """The converted LF write (gen_md): a keyword newline emits LF on any platform."""
    out = tmp_path / "out.md"
    with Path(str(out)).open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("a\nb\n")
    assert out.read_bytes() == b"a\nb\n"
