# P2 W4 half-wave 2 - scripts/ops/rc-shell/tft/root/spec slice partition (cycle 15)

Charter lens (DEEP_AUDIT_CHARTER P2): correctness, security hardening, efficiency,
friction classes (non-finite JSON token, raw-exc-to-wire secret leak, path traversal,
cache poisoning, non-atomic write race, subprocess no-timeout, BOM/encoding, PS5.1
quirk, bare-py launcher, em-dash/smart-quote ASCII). Re-probe live; file:line sourcing only.

Census: 117 files / 24527 LOC (git ls-files scripts/ ops/ rc-shell/ tft/ root *.py/.ps1/.cmd/.bat/.spec,
minus docs/data/logs/Share/ops-audit/node_modules/.md/.json). 8 disjoint slices A-H.

Frozen-but-open (charter auth 1; NAME every frozen edit in ledger; these are LIVE runtime
-> FIX-NOW only on clear correctness/security defect + flag for restart, else DEFER):
ops/rc_supervisor.py (A), ops/rc_dev_runtime.py (A), main.py (H), ops/RC-BridgeWatcher.xml (C).

gamepc/2-PC references = P3-prune feed (note-only, no behavior edit this cycle).

## Slices (disjoint; each agent edits ONLY its list)

- A ops runtime spine (deep; 2 frozen-live): ops/rc_supervisor.py(F), ops/rc_self_monitor.py,
  ops/rc_dev_runtime.py(F), ops/rc_file_bridge.py, ops/rc_transactional_deploy.py,
  ops/rc_state_validator.py, ops/rc_incident_log.py, ops/rc_bootstrap.py, ops/_scheduler_client.py,
  ops/__init__.py  [10f/4927]
- B ops phase3 audit + loop controller (deep py + ahk): ops/phase3_file_audit.py,
  ops/phase3_file_audit_proposals.py, ops/phase3_file_rc_audit_proposals.py, ops/phase3_queue_first_audit.py,
  ops/phase3_setup.py, ops/phase3_summary.py, ops/loop/loop_controller.py, ops/loop/claude_stub.py,
  ops/loop/done_sentinel.py, ops/loop/claude_gui_bridge.ahk, ops/loop/launch_loop.ps1  [11f/1395]
- C ops installers/boot/scheduled-task XML (lighter: bare-py ban, PS5.1, ASCII, frozen XML):
  ops/rc_league_watcher.ps1, ops/run_self_healing_watchdog.ps1, ops/run_postmortem_with_restart.ps1,
  ops/phase3_install.ps1, ops/phase3_install_periodic_audit.ps1, ops/install_RC_DDragonMirror.ps1,
  ops/install_RC_LegionBridgeDaemon.ps1, ops/install_RC_PostmortemAnalyze.ps1, ops/install_RC_RewindCatchup.ps1,
  ops/install_RC_UpstreamDriftCheck.ps1, ops/install_RC_WeeklyHygiene.ps1, ops/autostart_on_login.bat,
  ops/install_startup.bat, ops/launch_new_system.bat, ops/run_deploy_test.bat, ops/setup_dirs.bat,
  ops/start_ops.bat, ops/RC-BridgeWatcher.xml(F), ops/RC-CostHealthWatchdog.xml, ops/RC-DaemonSlayer.xml,
  ops/rc_watcher_launch.vbs  [21f/1195]
- D scripts data-pipeline + match/rewind (deep): scripts/rebuild_sim_fixtures.py, scripts/rewind_scraper.py,
  scripts/data_pipeline.py, scripts/postmortem_analyze.py, scripts/rewind_catchup.py,
  scripts/retrofill_match_metrics.py, scripts/prune_synthetic_matches.py, scripts/db_size_monitor.py  [8f/4190]
- E scripts extractors/builders/audit/precommit (lighter deep): scripts/audit_api_surface.py,
  scripts/audit_ddragon_items.py, scripts/build_spell_cast_rates.py, scripts/build_champion_benchmarks.py,
  scripts/patch_champion.py, scripts/wakeup_prune.py, scripts/validate_build_data.py, scripts/merge_refresh_builds.py,
  scripts/champion_drift_alerts.py, scripts/build_champ_kda.py, scripts/parse_external_arena.py,
  scripts/team_planner_sync.py, scripts/discover_champion_codes.py, scripts/download_aram_icons.py,
  scripts/probe_missing_codes.py, scripts/extract_css_panels.py, scripts/precommit_msg_check.py,
  scripts/precommit_pycompile.py, scripts/fetch_cdragon_pbe.py, scripts/fetch_external_tft_meta.py,
  scripts/cache_ddragon_assets.py, scripts/extract_champion_profiles.py  [22f/3157]
- F tft (deep): tft/tft_coach_engine.py, tft/tft_pbe_engine.py, tft/tft_live_analysis.py, tft/tft_ocr_reader.py,
  tft/tft_pbe_data.py, tft/tft_vision_reader.py, tft/tft_state_reader.py, tft/placement_aggregator.py,
  tft/tft_data.py, tft/__init__.py  [10f/3100]
- G rc-shell Electron (deep js + node:test): rc-shell/src/main.js, rc-shell/src/overlay_state.js,
  rc-shell/src/config.js, rc-shell/src/crash_guard.js, rc-shell/src/update_channel.js, rc-shell/src/active_indicator.js,
  rc-shell/src/drag_region.js, rc-shell/src/store.js, rc-shell/src/preload.js, + rc-shell/test/*.test.js (7)  [16f/3164]
- H root surface (deep; 1 frozen-live): item_advisor.py, performance_tracker.py, role_profiles.py,
  composition_advisor.py, web_dashboard.py, main.py(F), champion_profiles.py, moon_vision_server.py, overlay.py,
  app.py, riot-commander.spec, install.bat, start_claude.ps1, bootstrap_riot_commander_dev.ps1,
  bootstrap_riot_commander_dev.cmd, start.bat, start_debug.bat, restart.bat, restart_clean.bat, kill.bat  [20f/3389]

## Gate
Baseline (cycle 14 HEAD): 15558p/0f/7s. Round A verifier re-probe -> truth_gate.py PROCEED
before merge. Per-slice tests: tests/test_p2w4_hw2_<slice>.py. No ENGINE bump, no DS :8893
restart (no DS engine file in scope). RC + supervisor restart ONLY if a live frozen runtime
file (rc_supervisor/rc_dev_runtime/main) gets a behavior FIX-NOW.
