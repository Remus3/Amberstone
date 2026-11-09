"""PLW1510 - test code states ``check=`` on every ``subprocess.run`` (S144-P-600).

The production ratchet (``tests/test_subprocess_run_check_kw_prod_ratchet_s144p476.py``) covers
the production tree and leaves ``tests/`` out of scope. Test code carries the same ambiguity: a
``subprocess.run`` without ``check=`` leaves the reader to guess whether a non-zero exit was meant
to be ignored or was forgotten. ``check=False`` is the Python default, so the bytes run and the
behaviour are identical; the keyword only records that the test reads ``returncode`` / ``stdout``
(or deliberately ignores them) itself.

Measured 2026-11-09 with ``ruff check --isolated`` (target py39) over the tracked ``tests/`` tree:
361 findings in 299 files. Slice 1 (this one) states ``check=False`` at 35 sites in ten files (the
ten with the most sites that no other lane branch had changed, none of them launcher / packaging
test files); every other offending file sits in ``_BASELINE`` below, which only shrinks. A row
that stops offending (or offends less) fails ``test_baseline_is_exact`` until it shrinks or goes;
a finding beyond the baseline fails ``test_no_new_findings``; a ``_FIXED`` file that offends again
fails ``test_fixed_file_stays_clean``.

Scope: tracked ``.py`` files under ``tests/`` (including ``tests/<subdir>/``). ``*/tests/`` inside
other packages, ``agents/daemon_slayer`` and ``agents/agent3_testing/suite`` are not scanned. The
run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULE = "PLW1510"
# file -> finding count that stays. Only shrinks.
_BASELINE = {
    "tests/_repo_walk.py": 1,
    "tests/_ruff_version.py": 1,
    "tests/phase_b_champ_select/test_champ_select_shape_rc2.py": 1,
    "tests/snapshot_panels/test_overlay_phase_surfaces.py": 2,
    "tests/snapshot_panels/test_xss_escaping.py": 1,
    "tests/test_a001_test_code_idiom_ratchet_s144p182.py": 1,
    "tests/test_agent3_suite_idiom_ratchet_s144p231.py": 1,
    "tests/test_agent_relay_audit.py": 1,
    "tests/test_ambiguous_name_ratchet_s144p475.py": 1,
    "tests/test_anthropic_key_true_audit_s144.py": 1,
    "tests/test_anvil_shadow_probe_rm873.py": 1,
    "tests/test_aram_balance_fetch_failure.py": 1,
    "tests/test_aram_coach_cites_s144p51.py": 1,
    "tests/test_aram_comp_verdict_variants_rm850.py": 1,
    "tests/test_aram_item_interaction_snapshot_tracked.py": 1,
    "tests/test_aram_mayhem_augment_reco_rm860.py": 2,
    "tests/test_arena_coach_shadow_ts_cites_s144p51.py": 1,
    "tests/test_ascii_escape_py_atomic_write_rm258.py": 1,
    "tests/test_ascii_source_sweep.py": 2,
    "tests/test_async_blocking_prod_ratchet_s144p213.py": 1,
    "tests/test_asyncsleep_camelalias_ratchet_s144p239.py": 1,
    "tests/test_atlas_dust.py": 1,
    "tests/test_audit_api_surface_gitignored_s144d13.py": 1,
    "tests/test_b4_branch_review_panel_dom.py": 1,
    "tests/test_b4_client_directive_gate.py": 1,
    "tests/test_base_coach_dclass_cites_s144p51.py": 1,
    "tests/test_batch_embed_stamp_gate_a45b.py": 1,
    "tests/test_batch_set_p_clears_first_rm826.py": 1,
    "tests/test_batch_system_tools_rm826.py": 1,
    "tests/test_bootstrap_dev_no_overwrite_s144p218.py": 1,
    "tests/test_branch_idiom_ratchet_s144p163.py": 1,
    "tests/test_bug_class_lint_bundle2_zero_ratchet_s144p321.py": 1,
    "tests/test_bug_class_lint_bundle3_zero_ratchet_s144p328.py": 1,
    "tests/test_bug_class_lint_bundle4_zero_ratchet_s144p329.py": 1,
    "tests/test_bug_class_lint_bundle5_zero_ratchet_s144p330.py": 1,
    "tests/test_bug_class_lint_bundle6_zero_ratchet_s144p332.py": 1,
    "tests/test_bug_class_lint_bundle_zero_ratchet_s144p319.py": 1,
    "tests/test_bugbear_gap_and_pie790_ratchet_s144p111.py": 1,
    "tests/test_build_portable_bundle_pkg.py": 1,
    "tests/test_build_python_embed_atomic_write_rm258.py": 1,
    "tests/test_cc_conditional_externalization_item245.py": 1,
    "tests/test_champ_select_ban_provenance_dom.py": 1,
    "tests/test_champ_select_pick_placeholder_provenance.py": 1,
    "tests/test_champ_select_rune_follows_build.py": 1,
    "tests/test_ci_docs_guard_coverage.py": 1,
    "tests/test_ci_sibling_sweep_tree_wiring.py": 1,
    "tests/test_ci_watchdog.py": 1,
    "tests/test_clamp_expression_ratchet_s144p124.py": 1,
    "tests/test_claude_settings_template.py": 1,
    "tests/test_cli_logging_print_conversion_s144p214.py": 1,
    "tests/test_coach_choices_trigger_render.py": 1,
    "tests/test_collapsible_if_ratchet_s144p161.py": 1,
    "tests/test_collection_idiom_ratchet_s144p141.py": 1,
    "tests/test_compare_101qq_atomic_write_rm258.py": 1,
    "tests/test_container_builtin_return_ratchet_s144p160.py": 1,
    "tests/test_cost_tracker_compensating_cites_s144p52.py": 1,
    "tests/test_cost_tracker_vision_bucket_removed_s144p61.py": 1,
    "tests/test_css_html_ascii_hygiene.py": 1,
    "tests/test_csv_push_swap_wipe.py": 1,
    "tests/test_csv_push_toggles_phase5.py": 1,
    "tests/test_d417_docstring_param_ratchet_s144p509.py": 1,
    "tests/test_dashboard_condense_rc2.py": 1,
    "tests/test_data_retention_rm117_tracked_patches.py": 1,
    "tests/test_dead_weight_lint_bundle_ratchet_s144p270.py": 1,
    "tests/test_dict_fromkeys_ratchet_s144p137.py": 1,
    "tests/test_dict_fromkeys_test_code_ratchet_s144p164.py": 1,
    "tests/test_dict_items_test_code_ratchet_s144p169.py": 1,
    "tests/test_dict_iter_unused_half_ratchet_s144p139.py": 1,
    "tests/test_doc_action_ref_hygiene.py": 1,
    "tests/test_docindent_pathdot_yoda_ratchet_s144p240.py": 1,
    "tests/test_docs_ds_archetype_picker_s134d14.py": 1,
    "tests/test_docs_ds_calibration_pipeline_s134d12.py": 1,
    "tests/test_download_aram_icons_no_import_probe_s144p22.py": 1,
    "tests/test_ds_engine_logger_boot_order_s144d59.py": 1,
    "tests/test_ds_engine_logger_main_backstop_s144d60.py": 2,
    "tests/test_ds_engine_logger_scrub_s144d58.py": 1,
    "tests/test_ds_extract_import_no_log_rm828b.py": 1,
    "tests/test_ds_pick_consumption_p1l11.py": 1,
    "tests/test_edit_lint_check_cp1252_rm818.py": 2,
    "tests/test_edit_lint_check_stdin_payload.py": 1,
    "tests/test_env_name_case_prod_ratchet_s144p215.py": 1,
    "tests/test_exception_chain_ratchet_s144p153.py": 1,
    "tests/test_extract_champion_profiles_no_import_write_s144p25.py": 1,
    "tests/test_fetch_cdragon_pbe_no_import_fetch_s144p23.py": 1,
    "tests/test_first_element_slice_test_code_ratchet_s144p167.py": 1,
    "tests/test_fleet_kit_v12_race_guards.py": 1,
    "tests/test_fleet_kit_v13_identity.py": 2,
    "tests/test_fleet_kit_v19.py": 2,
    "tests/test_fleet_kit_v26.py": 1,
    "tests/test_furb105_print_empty_string_ratchet_s144p133.py": 1,
    "tests/test_furb140_starmap_zero_ratchet_s144p521.py": 1,
    "tests/test_furb142_set_add_loop_ratchet_s144p518.py": 1,
    "tests/test_furb148_furb145_zero_ratchet_s144p515.py": 1,
    "tests/test_furb154_furb156_zero_ratchet_s144p517.py": 1,
    "tests/test_furb192_prod_ratchet_s144p188.py": 1,
    "tests/test_gated_g101_cs_cards.py": 2,
    "tests/test_gated_g103_cc_pressure.py": 2,
    "tests/test_gated_g417_onhit_render.py": 2,
    "tests/test_gated_g418_jhin_lethality.py": 1,
    "tests/test_gated_live_probe_relay_auth.py": 1,
    "tests/test_gen_archmap_atomic_write_rm258.py": 1,
    "tests/test_gen_archmap_gitignored_file_s144d14.py": 1,
    "tests/test_gen_archmap_gitignored_scratch_s144d04.py": 1,
    "tests/test_gitignore_negations_are_effective.py": 1,
    "tests/test_global_return_perf_ratchet_s144p117.py": 1,
    "tests/test_headless_env.py": 1,
    "tests/test_hook_log_live_isolation.py": 1,
    "tests/test_hook_output_channel.py": 2,
    "tests/test_hz_mismatch_diagnose_atomic_write_rm258.py": 1,
    "tests/test_idempotent_stream_gate.py": 1,
    "tests/test_idiom_zero_ratchet_s144p180.py": 1,
    "tests/test_import_alias_test_code_ratchet_s144p165.py": 1,
    "tests/test_inbox_responder_export.py": 1,
    "tests/test_inference_prompt_cites_s144p51.py": 1,
    "tests/test_input_parser_redos_codeql.py": 1,
    "tests/test_install_bat_embedded_pins_rm764.py": 1,
    "tests/test_install_bat_key_stage_rm779.py": 1,
    "tests/test_install_startup_shortcut_rm826.py": 2,
    "tests/test_isc001_same_line_concat_ratchet_s144p507.py": 1,
    "tests/test_isc002_backslash_concat_ratchet_s144p237.py": 1,
    "tests/test_kit_v10_spawn_routes.py": 1,
    "tests/test_lambda_assignment_ratchet_s144p473.py": 1,
    "tests/test_lane_run_ledger.py": 1,
    "tests/test_lane_worktree_eol_rm343.py": 1,
    "tests/test_launcher_cutover_ps1.py": 3,
    "tests/test_launcher_embed_fitness_a45b.py": 1,
    "tests/test_launcher_first_run.py": 2,
    "tests/test_launcher_key_read_rm810.py": 3,
    "tests/test_launcher_update_cycle_pkg6b.py": 1,
    "tests/test_legacy_lcu_panel_phase_rm382.py": 1,
    "tests/test_live_log_isolation_rm812.py": 1,
    "tests/test_liveclient_shape_audit_rm601.py": 1,
    "tests/test_local_hosts_config.py": 2,
    "tests/test_log_scrub_residuals_rm811b.py": 2,
    "tests/test_logger_leak_census.py": 1,
    "tests/test_loop_concurrency.py": 1,
    "tests/test_loop_executor.py": 2,
    "tests/test_match_metrics_true_audit_s144.py": 1,
    "tests/test_mcp_mc_hardening_rm811.py": 1,
    "tests/test_md_guard_selector_bound_argv_s144q40b.py": 1,
    "tests/test_md_guard_selector_browser_tree_rm1657.py": 1,
    "tests/test_md_guard_selector_option_args_s144q41.py": 1,
    "tests/test_md_guard_selector_residue_s144q40.py": 1,
    "tests/test_mission_control_server.py": 1,
    "tests/test_mutable_default_arg_ratchet_s144p318.py": 1,
    "tests/test_n805_first_arg_ratchet_s144p238.py": 1,
    "tests/test_naive_datetime_prod_ratchet_s144p340.py": 1,
    "tests/test_nan_selfcompare_prod_ratchet_s144p173.py": 1,
    "tests/test_noqa_concat_ratchet_s144p156.py": 1,
    "tests/test_now6_logger_leak_regression.py": 1,
    "tests/test_now7_logger_leak_detector.py": 1,
    "tests/test_obs_recorder.py": 1,
    "tests/test_overlay_callouts_ui_audit.py": 1,
    "tests/test_overlay_drag_listener_leak_behavior.py": 1,
    "tests/test_overlay_idle_rc2.py": 1,
    "tests/test_overlay_priority_rc2.py": 1,
    "tests/test_overlay_pulse_flip_rc2.py": 1,
    "tests/test_overlay_settings_rc2.py": 1,
    "tests/test_package_portable_atomic_write_rm258.py": 1,
    "tests/test_perf102_ratchet_s144p178.py": 1,
    "tests/test_phase3_bind_loopback_rm231.py": 1,
    "tests/test_phase3_setup_rerun_bytes_rm820.py": 1,
    "tests/test_pie810_startswith_tuple_ratchet_s144p150.py": 1,
    "tests/test_plr1730_minmax_ratchet_s144p127.py": 1,
    "tests/test_plr5501_collapsible_else_if_ratchet_s144p128.py": 1,
    "tests/test_plw2901_loop_var_overwrite_ratchet_s144p259.py": 1,
    "tests/test_polled_json_lane8_cycle24.py": 1,
    "tests/test_polled_json_resolver_cites_s144p51.py": 1,
    "tests/test_postmortem_runner_pipe.py": 2,
    "tests/test_precedence_and_dead_branch_ratchet_s144p112.py": 1,
    "tests/test_precommit_gate_cp1252_rm818.py": 2,
    "tests/test_precommit_gate_message_file.py": 2,
    "tests/test_precommit_gate_stdin_fault_rm783.py": 1,
    "tests/test_private_exception_name_ratchet_s144p512.py": 1,
    "tests/test_probe_missing_codes_writer_polled_json_s144p20.py": 1,
    "tests/test_process_start_tripwire_rm880d.py": 1,
    "tests/test_pt001_fixture_parens_ratchet_s144p234.py": 1,
    "tests/test_pt012_raises_block_ratchet_s144p184.py": 1,
    "tests/test_pt018_ruf036_prod_ratchet_s144p175.py": 1,
    "tests/test_pt019_fixture_param_ratchet_s144p493.py": 1,
    "tests/test_pyi_fly_prod_ratchet_s144p216.py": 1,
    "tests/test_pytest_basetemp_scratchpad_temp1.py": 1,
    "tests/test_pytest_guard.py": 1,
    "tests/test_pytest_guard_true_audit_s144t176.py": 1,
    "tests/test_pytest_idiom_ratchet_s144p171.py": 2,
    "tests/test_pytest_per_run_temproot_rm878.py": 1,
    "tests/test_q001_multiline_quote_ratchet_s144p236.py": 1,
    "tests/test_q003_escaped_quote_ratchet_s144p235.py": 1,
    "tests/test_raise_comprehension_ratchet_s144p157.py": 1,
    "tests/test_range_start_startswith_tuple_ratchet_s144p158.py": 1,
    "tests/test_range_startswith_dictcomp_ratchet_s144p123.py": 1,
    "tests/test_rc2_p73_quarantine.py": 1,
    "tests/test_redundant_collection_call_ratchet_s144p115.py": 1,
    "tests/test_redundant_return_compare_ratchet_s144p162.py": 1,
    "tests/test_regex_flag_alias_ratchet_s144p152.py": 1,
    "tests/test_regex_match_and_implicit_optional_ratchet_s144p113.py": 1,
    "tests/test_removeprefix_merged_branch_ratchet_s144p135.py": 1,
    "tests/test_repair_mojibake_atomic_write_rm258.py": 1,
    "tests/test_repeated_comparison_ratchet_s144p121.py": 1,
    "tests/test_repin_subagent_cli_atomic_write_rm258.py": 1,
    "tests/test_replay_minimap_crosscheck.py": 1,
    "tests/test_replay_pickban_validate_atomic_write_rm258.py": 1,
    "tests/test_reraise_exc_info_ratchet_s144p118.py": 1,
    "tests/test_responder_grammar_table.py": 1,
    "tests/test_restart_patch_step_rm826.py": 1,
    "tests/test_ret503_test_code_ratchet_s144p245.py": 1,
    "tests/test_ret505_plr1714_plr0402_ratchet_s144p130.py": 1,
    "tests/test_return_nan_idiom_ratchet_s144p172.py": 1,
    "tests/test_return_ratchet_s144p144.py": 1,
    "tests/test_rewrite_sha_citations_atomic_write_rm258.py": 1,
    "tests/test_riot_api_cache_eviction.py": 1,
    "tests/test_rm750_ds_keepalive.py": 1,
    "tests/test_rm825_jsonrpc_scrub_host_residuals.py": 2,
    "tests/test_rm830_quoted_path_sweep.py": 2,
    "tests/test_rm875_apply_mode_modifiers_archetype_dispatch.py": 1,
    "tests/test_rofl_stats_backfill.py": 1,
    "tests/test_ruf005_core_ratchet_s144p271.py": 1,
    "tests/test_ruf012_classvar_prod_ratchet_s144p211.py": 1,
    "tests/test_ruf050_ruf070_ratchet_s144p516.py": 1,
    "tests/test_ruf056_falsy_dict_get_ratchet_s144p520.py": 1,
    "tests/test_run_deploy_test_continuations_rm826.py": 1,
    "tests/test_runtime_outputs_untracked_rm715_s144p221.py": 1,
    "tests/test_s324_hash_usedforsecurity_prod_ratchet_s144p212.py": 1,
    "tests/test_sanitize_agent6_atomic_write_rm258.py": 1,
    "tests/test_sanitize_agent6_reports.py": 1,
    "tests/test_scheduled_task_docstring_commands.py": 1,
    "tests/test_session_checklist_item13.py": 1,
    "tests/test_session_intents.py": 1,
    "tests/test_session_intents_true_audit_s144t169.py": 2,
    "tests/test_sibling_name_sweep.py": 6,
    "tests/test_sibling_sweep_prefilter_f2.py": 1,
    "tests/test_sibling_sweep_run_record_rm688.py": 1,
    "tests/test_sim102_nested_if_ratchet_s144p254.py": 1,
    "tests/test_sim103_ratchet_s144p145.py": 1,
    "tests/test_sim108_ternary_ratchet_s144p252.py": 1,
    "tests/test_sim115_open_context_prod_ratchet_s144p210.py": 1,
    "tests/test_small_idiom_ratchet_s144p122.py": 1,
    "tests/test_sorted_all_and_slots_core_ratchet_s144p249.py": 1,
    "tests/test_sorted_all_and_slots_ratchet_s144p248.py": 1,
    "tests/test_sorted_all_and_slots_rest_ratchet_s144p250.py": 1,
    "tests/test_sorted_first_min_test_code_ratchet_s144p168.py": 1,
    "tests/test_startswith_tuple_and_identity_comprehension_ratchet_s144p114.py": 1,
    "tests/test_state_relay_pool_threads_s144q18.py": 1,
    "tests/test_stats_panel_kp_live.py": 1,
    "tests/test_status_helper_rc2.py": 1,
    "tests/test_stop_claim_gate_alt_scan_s144q04.py": 1,
    "tests/test_stop_claim_gate_artifact_scan_rm421.py": 1,
    "tests/test_stop_claim_gate_git_options_redos.py": 1,
    "tests/test_stop_claim_gate_heredoc_summary_scan_rm829.py": 1,
    "tests/test_stop_claim_gate_option_scan_rm765.py": 1,
    "tests/test_stop_claim_gate_span_scan_rm814.py": 1,
    "tests/test_strip_em_dashes_atomic_write_rm258.py": 1,
    "tests/test_strip_smart_quotes_atomic_write_rm258.py": 1,
    "tests/test_strip_u2500_atomic_write_rm258.py": 1,
    "tests/test_suite_tmp_hygiene_rm828.py": 1,
    "tests/test_supervisor_rc_log_tee_rm909d.py": 1,
    "tests/test_supervisor_sentinel_selfheal.py": 1,
    "tests/test_team_planner_sync_no_import_probe_s144p21.py": 1,
    "tests/test_ternary_or_ratchet_s144p143.py": 1,
    "tests/test_test_code_misc_idiom_ratchet_s144p246.py": 1,
    "tests/test_text_first_guard.py": 2,
    "tests/test_tft_engine_guards.py": 1,
    "tests/test_tft_meta_provenance_rm846.py": 2,
    "tests/test_tft_rounds_store.py": 1,
    "tests/test_third_party_notices_atomic_write_rm258.py": 1,
    "tests/test_third_party_notices_pkg.py": 1,
    "tests/test_truth_gate.py": 1,
    "tests/test_truth_gate_git_paths_rm861.py": 1,
    "tests/test_try401_sim110_furb171_ratchet_s144p148.py": 1,
    "tests/test_type_ignore_code_needless_lambda_ratchet_s144p149.py": 1,
    "tests/test_u2500_candidate_sweep.py": 1,
    "tests/test_unspecified_encoding_prod_ratchet_s144p303.py": 1,
    "tests/test_unused_import_ratchet_s144p108.py": 1,
    "tests/test_unused_local_ratchet_s144p106.py": 1,
    "tests/test_unused_loop_variable_ratchet_s144p110.py": 1,
    "tests/test_unused_loop_variable_ratchet_s144p251.py": 1,
    "tests/test_unused_noqa_ratchet_s144p103.py": 1,
    "tests/test_unused_unpack_ratchet_s144p147.py": 1,
    "tests/test_useless_yield_fixture_ratchet_s144p170.py": 2,
    "tests/test_vision_sync_dir_rm828c.py": 1,
    "tests/test_vision_watchdog_hardening_s144t076.py": 1,
    "tests/test_voice_coach_ps_injection.py": 1,
    "tests/test_web_ascii_sweep_atomic_write_rm258.py": 1,
    "tests/test_web_js_esm_parse.py": 3,
    "tests/test_web_js_unimported_calls_s144q43.py": 1,
    "tests/test_whitespace_docstring_prod_ratchet_s144p189.py": 1,
    "tests/test_ws_server_port_in_use_rm756.py": 1,
    "tests/test_yoda_condition_test_code_ratchet_s144p166.py": 1,
    "tests/test_yoda_perf403_c408_ratchet_s144p146.py": 1,
}
_FIXED = (
    "tests/test_api_key_single_lookup_env_apikey.py",
    "tests/test_ci_checkout_history_depth.py",
    "tests/test_drift_guard.py",
    "tests/test_git_hook_gate_e2e.py",
    "tests/test_inbox_reported_record.py",
    "tests/test_inbox_responder_runner.py",
    "tests/test_loop_audit_range.py",
    "tests/test_loop_status_route_lane8_cycle68.py",
    "tests/test_postmortem_task_hidden_launch.py",
    "tests/test_tracked_json_producers_emit_lf_bytes.py",
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
    for d in _ruff(["--select", _RULE, "tests"]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith("tests/"):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


def test_fixed_and_baseline_are_disjoint():
    assert not set(_FIXED) & set(_BASELINE)


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_file_stays_clean(rel, tree_counts):
    assert (REPO_ROOT / rel).is_file(), f"{rel} missing - update _FIXED"
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "import subprocess\nsubprocess.run(['x'])\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
    ok = "import subprocess\nsubprocess.run(['x'], check=False)\n"
    assert not _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=ok)
