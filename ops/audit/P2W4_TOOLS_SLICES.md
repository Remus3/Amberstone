# P2 W4 half-wave 1 - tools/ slice partition (cycle 14)

Charter lens (DEEP_AUDIT_CHARTER P2): correctness, security hardening, efficiency,
friction classes (non-finite JSON token, raw-exc-to-wire secret leak, path traversal,
cache poisoning, non-atomic write race, subprocess no-timeout, BOM/encoding, PS5.1
quirk, bare-py launcher). Re-probe live; verifiable file:line sourcing only.

tools/ census: 164 git-tracked files / 43633 LOC. scripts/ops/rc-shell/tft/root/spec
(114 / 24433) DEFERRED to cycle 15 half-wave 2.

Frozen-but-open (charter auth 1; every frozen edit NAMED in ledger): bridge_watcher_classify.py,
bridge_watcher_actions.py, bridge_watcher_action_prompt.md, bridge_watcher_history.py,
bridge_watcher_install.ps1, bridge_watcher_hook.ps1, bridge_watcher_config.json,
bridge_post_result.py, bridge_pull_tasks.py, process-bridge-tasks.md, diagnose.md, caveman.md.

gamepc_* = P3-prune VERDICT (KEEP-live-relocated / ARCHIVE / DELETE / RENAME) with live
evidence, NOT deep audit. Note: RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener run
LIVE on Legion now (ADR-011 relocation) - verify which gamepc_*.py each task actually launches
before any prune verdict.

## Slices (disjoint; each agent edits ONLY its list)

- A Bridge family (deep; frozen-heavy, security-critical): bridge_watcher.py, bridge_mcp_server.py,
  bridge_cli.py, bridge_watcher_actions.py(F), bridge_watcher_history.py(F), bridge_watcher_classify.py(F),
  peer_bridge_daemon.py, legion_bridge_daemon.py, bridge_dispatch_enable_lanes.py, verify_bridge_roundtrip.py,
  bridge_watcher_health_publisher.py, start_bridge_mcp.py, bridge_pull_tasks.py(F), bridge_post_result.py(F),
  bridge_heartbeat.py, bridge_post.py, bridge_ping.py, bridge_task.py, bridge_fetch.py,
  bridge_watcher_config.json(F), bridge_watcher_install.ps1(F), bridge_watcher_update_check.ps1,
  bridge_watcher_hook.ps1(F), bridge_setup.ps1, bridge_watcher_action_prompt.md(F), BRIDGE_WATCHER_PLAN.md,
  BRIDGE_WATCHER_INSTALL_PS1_LANES_DIFF.md, AUTO_OPS_VERB_EXPANSION_GATE_PROBE.md, process-bridge-tasks.md(F),
  process-bridge-tasks-peer.md, PEER_ROADMAP_SUGGESTIONS.md
- B DS upstream extractors (deep): daemon_slayer_cdragon_ratio_extract.py, daemon_slayer_extract.py,
  daemon_slayer_wiki_stats_extract.py, daemon_slayer_abilities_extract.py, daemon_slayer_cdragon_spell_extract.py,
  daemon_slayer_wiki_ability_extract.py, ds_cdragon_drift_audit.py, ds_windup_offset_compare.py,
  migrate_abilities_nested_hp_s223.py, migrate_abilities_units_2026_05_30.py, migrate_abilities_unit_variants_s224.py
- C DS extractor tests (W5-light lens: assertion correctness, stale pins): tools/tests/test_wiki_stats_extract.py,
  tools/tests/test_cdragon_ratio_extract.py, tools/tests/test_cdragon_spell_extract.py,
  tools/tests/test_wiki_ability_extract.py, tools/tests/test_upstream_drift_check.py, tools/tests/test_cdragon_drift_audit.py
- D DS tooling (deep): ds_matchdb_mcp_server.py, ds_share_sync.py, gist_share_sync.py,
  daemon_slayer_build_orders_generate.py, daemon_slayer_pickban_targets_generate.py, ds_cc_conditional_to_json.py,
  ds_block_scanner.py, ds_execute_prefilter.py, ds_cond_pair_prefilter.py, ds_unmapped_key_prefilter.py,
  ds_form_index_prefilter.py, ds_max_priority_prefilter.py, ds_cond_inspect.py, ds_extendedduel_build.py,
  ds_antitank_build.py, ds_mobility_build.py, ds_sustain_build.py, ds_zonecontrol_build.py, ds_allyamp_build.py,
  ds_objdamage_build.py, ds_waveclear_build.py, ds_threatrange_build.py, ds_scaling_build.py, ds_cc_output_build.py,
  start_daemon_slayer.py, start_ds_matchdb_mcp.py, install_daemon_slayer_task.ps1
- E Champion loadout family (deep for live validators; verdict for dated one-shots): champion_loadout_cleanup_pollution_item213.py,
  champion_loadout_collapse_to_paths.py, champion_loadout_autogen.py, champion_loadout_align.py,
  champion_loadout_handcurate.py, champion_loadout_invariants.py, champion_loadout_validate_meta.py,
  champion_loadout_backfill_item208_carry.py, champion_loadout_sweep_item_s8.py, champion_loadout_handcurate_merge.py,
  validate_loadouts.py
- F Dated one-shots + replay/recover/101qq (VERDICT + danger-if-rerun check; light): hotfix_thin_aram_pollution_item276.py,
  regen_ranged_marksman_builds_item213.py, hotfix_sibling_pollution_item269.py, hotfix_arena_mage_mislabel_item273.py,
  hotfix_zaahen_loadout_item277.py, hotfix_thin_aram_adc_item275.py, hotfix_sr_adc_loadouts_item167.py,
  hotfix_kaisa_aram_ashe_sr_item263.py, migrate_carry_summoners_flash_barrier.py, backfill_match_ingest_misattribution.py,
  recover_match_via_match_v5.py, replay_matchup_validate.py, replay_pickban_validate.py, probe_101qq_hero_rank_double.py,
  compare_101qq_vs_ddragon.py, match_monitor.py
- G Packaging/install/boot/cert/gates/guards/ASCII-strip (deep): build_portable.py, run_packaged_smoke.py,
  build_installer.py, package_portable.py, bootstrap_env_check.py, regen_rc_cert.ps1, truth_gate.py, precommit_gate.py,
  pytest_guard.py, text_first_guard.py, edit_lint_check.py, scheduled_boot_verify.py, strip_smart_quotes.py,
  repair_mojibake.py, strip_u2500.py, strip_em_dashes.py, build_portable.cmd, package_portable.cmd, build_installer.cmd,
  run_packaged_smoke.cmd, bootstrap_env_check.cmd, install_headless_launcher_shortcut.ps1, rc_headless_launcher.ps1,
  headless_run.ps1, install-rc-rootca-on-gamepc.cmd, reset-rc-rootca-on-gamepc.cmd, verify-rc-rootca-on-gamepc.cmd,
  preflight.cmd, snapshot.cmd, rollback_last.cmd, dev_cli.cmd, DISTRIBUTION_LAYOUT.md, LAUNCH_STRATEGY.md, PYTHON_BUNDLING_STRATEGY.md
- H Live utility + lessons + cost/usage/drift + dev + skill-md (deep code; .md note-only for P8): rc_facts.py,
  upstream_drift_check.py, cost_health_watchdog.py, hz_shadow_report.py, dev_cli.py, gen_archmap.py, gen_state_schema.py,
  extract_panels.py, calibrate_vision.py, ddragon_mirror_refresh.py, slice_orchestrator.py, usage-mcp-server.js,
  lessons_pull.py, lessons_post.py, lessons_status.py, lessons_send.py, lessons_send_dryrun.py, weekly_hygiene_run.ps1,
  gemini_audit.ps1, gemini_ask.ps1, gemini_audit_prompt.md, legion_on.ps1, legion_off.ps1, run_phase2_perf.py,
  run_phase2_smoke.py, run_phase3_snapshot_regressions.py, run_phase2_perf.cmd, run_phase2_smoke.cmd,
  run_phase3_snapshot_regressions.cmd, DEV_WORKFLOW.md, done.md, done-peer.md, ship-batch.md, test-first-autopilot.md,
  sync-all-md.md, headless-upgrade.md, diagnose.md(F), caveman.md(F)
- I gamepc_* P3-prune VERDICT (NOT deep audit; live-evidence classification): gamepc_lcu_agent.py,
  gamepc_phase_watcher.py, gamepc_mcp_server.py, gamepc_screen_agent.py, gamepc_bridge_daemon.py,
  gamepc_hotkey_listener.py, gamepc_keybind_listener.py, gamepc_liveclient_relay.py, gamepc_boot.ps1,
  gamepc_phase_watcher_install.ps1, start_gamepc_claude.ps1, GAMEPC_CLAUDE.md, done-gamepc.md, wrap-gamepc.md
