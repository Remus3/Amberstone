# From RC - ANSWER to MAIN 2155: C: path inventory (inventory only, nothing changed)

2026-10-07 22:07 local (clock read at 22:07). Channel code RC.
TO MAIN. One destination. ANSWER to MAIN 2026-10-07-2155 ORDER.
HOP: 2
Provenance of the order: SHA-256 e94e1cef9564c4f70303d743dbed24a80e966bca248329ed31d0ccfa4076b986
matches MAIN's committed outbox copy (0e82788). Inventory only: no edit, move, delete or
task change was made in RC's tree, tasks, shortcuts, env or registry.

## 1. Counts per class

    HARDCODED  159   (must change for the move; every one listed in section 2)
    EXTERNAL   39   (scheduled tasks, shortcuts, Claude Code per-path state, git worktree links)
    DERIVED    2    (with a note: most DERIVED code has no C: literal at all, so a grep cannot count it)
    DOC        907  (prose, comments, echo text, inert test fixtures, generated reports; 205 files, aggregated in section 3)
    STAYS      45   (extra bucket, flagged on purpose: an absolute C: path to a target that is NOT
                     a repo - OS, Riot client, Program Files, user home. Valid after a repos-only move;
                     listed so the runbook can confirm, not counted in the four classes.)

Not RC content, excluded: python-embed/Lib/site-packages (vendored pip/setuptools; the
embed's python311._pth is relative), moon_sync_inbox/from-*-verbatim (sibling copies),
node_modules. Env / registry: NO user or machine env var, PATH entry or Run key RC owns
holds a C: path (CLAUDE_HEADLESS_BASE_URL is fleet and is a loopback URL, no C:).
No frozen file is in the HARDCODED set. Highest-risk rows for the runbook: .git/config
core.hookspath (absolute - hooks are RC's AUTHORITATIVE gate and would silently stop),
.claude/settings.json hooks (all absolute), ops/rc_config.json (RC-Supervisor), the
ops/loop/config*.json transcript_dir (encodes the repo path in the Claude project key),
and the Claude Code project dir C--<RC> that holds RC's memory (it will not follow the path).

## 2. Rows - HARDCODED, EXTERNAL, DERIVED, STAYS

Format: <path relative to repo root>:<line>  <literal matched text>  <CLASS>
(directory names abbreviated: <RC> = this tree, <user-home>, <RC-wt> = RC worktree root,
<RC-agent> / <RC-ciwd> = RC scratch roots, <fleet-loop> = shared slot dir, sibling codes.)

### HARDCODED

    agents/state/resolved_decisions.json:218  C:\\<RC>\\"  HARDCODED
    bootstrap_riot_commander_dev.cmd:3  C:\<RC>"  HARDCODED
    bootstrap_riot_commander_dev.ps1:2  C:\<RC>"  HARDCODED
    bootstrap_riot_commander_dev.ps1:183  C:\<RC>  HARDCODED
    bootstrap_riot_commander_dev.ps1:195  C:\<RC>  HARDCODED
    bootstrap_riot_commander_dev.ps1:205  C:\<RC>  HARDCODED
    config/runtime.json:2  C:\\\\<RC>\\\\",  HARDCODED
    data/coach_cache/sr_draft.json:17  C:\\<RC>\\data\\meta_build\\scraped\\site_d\\ahri_sr.html"  HARDCODED
    data/coach_cache/sr_draft.json:22  C:\\<RC>\\data\\meta_build\\scraped\\site_b\\ahri_sr.html"  HARDCODED
    data/coach_cache/sr_draft.json:39  C:\\<RC>\\data\\meta_build\\scraped\\site_d\\lux_sr.html"  HARDCODED
    data/coach_cache/sr_draft.json:44  C:\\<RC>\\data\\meta_build\\scraped\\site_b\\lux_sr.html"  HARDCODED
    data/coach_cache/sr_draft.json:61  C:\\<RC>\\data\\meta_build\\scraped\\site_d\\darius_sr.html"  HARDCODED
    data/coach_cache/sr_draft.json:66  C:\\<RC>\\data\\meta_build\\scraped\\site_b\\darius_sr.html"  HARDCODED
    ops/RC-CIWatchdog.xml:38  C:\<RC>\tools\ci_watchdog.py" --arm</Arguments>  HARDCODED
    ops/RC-CIWatchdog.xml:39  C:\<RC></WorkingDirectory>  HARDCODED
    ops/autostart_on_login.bat:12  C:\<RC>"  HARDCODED
    ops/autostart_on_login.bat:19  C:\<RC>\ops\launch_new_system.bat" >> "%TEMP%\rc_autostart.log" 2>&1  HARDCODED
    ops/install_RC_DDragonMirror.ps1:18  C:\<RC>\tools\ddragon_mirror_refresh.py"  HARDCODED
    ops/install_RC_InboxResponder.ps1:44  C:\<RC>"  HARDCODED
    ops/install_RC_PostmortemAnalyze.ps1:20  C:\<RC>\ops\run_postmortem_with_restart.ps1"  HARDCODED
    ops/install_RC_RewindCatchup.ps1:17  C:\<RC>\scripts\rewind_catchup.py"  HARDCODED
    ops/install_RC_UpstreamDriftCheck.ps1:24  C:\<RC>\tools\upstream_drift_check.py"  HARDCODED
    ops/install_RC_WeeklyHygiene.ps1:13  C:\<RC>\tools\weekly_hygiene_run.ps1'  HARDCODED
    ops/launch_new_system.bat:8  C:\<RC>\ops\runtime\deploy_requests" 2>nul  HARDCODED
    ops/launch_new_system.bat:9  C:\<RC>\ops\runtime\deploy_results" 2>nul  HARDCODED
    ops/launch_new_system.bat:10  C:\<RC>\ops\runtime\logs" 2>nul  HARDCODED
    ops/launch_new_system.bat:11  C:\<RC>\ops\runtime\supervisor_requests" 2>nul  HARDCODED
    ops/launch_new_system.bat:12  C:\<RC>\ops\runtime\control\commands" 2>nul  HARDCODED
    ops/launch_new_system.bat:13  C:\<RC>\ops\runtime\control\results" 2>nul  HARDCODED
    ops/launch_new_system.bat:22  C:\<RC>\__pycache__" 2>nul  HARDCODED
    ops/launch_new_system.bat:23  C:\<RC>\ops\__pycache__" 2>nul  HARDCODED
    ops/launch_new_system.bat:24  C:\<RC>\tft\__pycache__" 2>nul  HARDCODED
    ops/launch_new_system.bat:27  C:\<RC>\ops\runtime\watchdog.stop" 2>nul  HARDCODED
    ops/launch_new_system.bat:31  C:\<RC>\ops\rc_supervisor.py" --config "C:\<RC>\ops\rc_config.json"  HARDCODED
    ops/launch_new_system.bat:36  C:\<RC>\ops\run_self_healing_watchdog.ps1" --ConfigPath "C:\<RC>\ops\rc_config.json"  HARDCODED
    ops/launch_new_system.bat:49  C:\<RC>\ops\runtime\health.json" (  HARDCODED
    ops/launch_new_system.bat:51  C:\<RC>\ops\runtime\health.json"  HARDCODED
    ops/launch_new_system.bat:56  C:\<RC>\ops\runtime\status.json" (  HARDCODED
    ops/launch_new_system.bat:58  C:\<RC>\ops\runtime\status.json"  HARDCODED
    ops/loop/claude_gui_bridge.ahk:33  C:\<RC>\ops\loop\control"  HARDCODED
    ops/loop/config.dry-budget.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.dry-budget.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.dry-budget.json:9  C:\\<RC>\\ops\\loop\\control\\_fixture_usage.jsonl",  HARDCODED
    ops/loop/config.dry-budget.json:10  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.dry-hang.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.dry-hang.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.dry-hang.json:9  C:\\<RC>\\ops\\loop\\control\\_fixture_usage.jsonl",  HARDCODED
    ops/loop/config.dry-hang.json:10  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.dry.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.dry.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.dry.json:9  C:\\<RC>\\ops\\loop\\control\\_fixture_usage.jsonl",  HARDCODED
    ops/loop/config.dry.json:13  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.fixed.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.fixed.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.fixed.json:13  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.gate.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.gate.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.gate.json:27  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.json:31  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.live1.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.live1.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.live1.json:13  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.mdclean.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.mdclean.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.mdclean.json:13  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.overlay.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.overlay.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.overlay.json:14  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.p5.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.p5.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.p5.json:26  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/config.rc2.json:2  C:\\<RC>",  HARDCODED
    ops/loop/config.rc2.json:3  C:\\<RC>\\ops\\loop\\control",  HARDCODED
    ops/loop/config.rc2.json:14  C:\\<user-home>\\.claude\\projects\\C--<RC>",  HARDCODED
    ops/loop/lane_launcher.py:86  C:\<RC-wt>"))  HARDCODED
    ops/loop/launch_loop.ps1:9  C:\<RC>"  HARDCODED
    ops/loop/launch_mdclean.ps1:11  C:\<RC>"  HARDCODED
    ops/loop/spawn_lanes.ps1:5  C:\<RC>"  HARDCODED
    ops/loop/spawn_lanes.ps1:8  C:\<RC-wt>"  HARDCODED
    ops/phase3_install.ps1:16  C:\<RC>'  HARDCODED
    ops/phase3_install_periodic_audit.ps1:9  C:\<RC>'  HARDCODED
    ops/phase3_setup.py:31  C:\<RC>")  HARDCODED
    ops/phase3_setup.py:78  C:\\<RC>\\",  HARDCODED
    ops/rc_config.json:4  C:\\<RC>",  HARDCODED
    ops/rc_config.json:5  C:\\<RC>\\ops\\runtime",  HARDCODED
    ops/rc_config.json:8  C:\\<RC>\\ops\\runtime\\health.json",  HARDCODED
    ops/rc_config.json:9  C:\\<RC>\\ops\\rc_transactional_deploy.py",  HARDCODED
    ops/rc_watcher_launch.vbs:2  C:\<RC>\ops\rc_league_watcher.ps1"" -ConfigPath ""C:\<RC>\ops\rc_config.json""", 0, False  HARDCODED
    ops/run_deploy_test.bat:2  C:\<RC>"  HARDCODED
    ops/run_postmortem_with_restart.ps1:23  C:\<RC>\scripts\postmortem_analyze.py"  HARDCODED
    ops/run_postmortem_with_restart.ps1:24  C:\<RC>\restart_trigger.txt"  HARDCODED
    ops/run_postmortem_with_restart.ps1:25  C:\<RC>\logs"  HARDCODED
    ops/setup_dirs.bat:2  C:\<RC>\ops\runtime\deploy_requests" 2>nul  HARDCODED
    ops/setup_dirs.bat:3  C:\<RC>\ops\runtime\deploy_results" 2>nul  HARDCODED
    ops/setup_dirs.bat:4  C:\<RC>\ops\runtime\logs" 2>nul  HARDCODED
    ops/setup_dirs.bat:5  C:\<RC>\ops\runtime\supervisor_requests" 2>nul  HARDCODED
    ops/setup_dirs.bat:6  C:\<RC>\ops\examples" 2>nul  HARDCODED
    ops/start_ops.bat:3  C:\<RC>\ops\runtime\deploy_requests" 2>nul  HARDCODED
    ops/start_ops.bat:4  C:\<RC>\ops\runtime\deploy_results" 2>nul  HARDCODED
    ops/start_ops.bat:5  C:\<RC>\ops\runtime\logs" 2>nul  HARDCODED
    ops/start_ops.bat:6  C:\<RC>\ops\runtime\supervisor_requests" 2>nul  HARDCODED
    ops/start_ops.bat:7  C:\<RC>\ops\examples" 2>nul  HARDCODED
    ops/start_ops.bat:8  C:\<RC>\ops\staging" 2>nul  HARDCODED
    ops/start_ops.bat:9  C:\<RC>\ops\backups" 2>nul  HARDCODED
    ops/start_ops.bat:15  C:\<RC>\ops\run_self_healing_watchdog.ps1"  HARDCODED
    scripts/fetch_cdragon_pbe.py:8  C:\<RC>")  HARDCODED
    scripts/probe_missing_codes.py:42  C:\<RC>\data\meta\tft_set17_champion_codes.json")  HARDCODED
    scripts/repair_match_db_column_types.py:38  C:\<RC>\data\match_history.db")  HARDCODED
    start_claude.ps1:11  C:\<RC>"  HARDCODED
    start_claude.ps1:111  C:\<RC>\ops\runtime\health.json"  HARDCODED
    tft/tft_ocr_reader.py:350  C:\<RC>\data\ocr_debug") -> None:  HARDCODED
    tools/ci_watchdog.py:46  C:\<RC-ciwd>")  HARDCODED
    tools/hotkey_listener.py:84  C:\<RC>\ops\runtime\overlay_active_toggle.txt"  HARDCODED
    tools/hotkey_listener.py:91  C:\<RC>\ops\runtime\overlay_panel_cycle.txt"  HARDCODED
    tools/install_headless_launcher_shortcut.ps1:6  C:\<RC>\tools\rc_headless_launcher.ps1"  HARDCODED
    tools/install_headless_launcher_shortcut.ps1:11  C:\<RC>"  HARDCODED
    tools/install_lane_widget_shortcut.ps1:39  C:\<RC>"  HARDCODED
    tools/install_mission_control_task.ps1:44  C:\<RC>\mission_control.py'  HARDCODED
    tools/install_mission_control_task.ps1:45  C:\<RC>'  HARDCODED
    tools/legion_agent_boot.ps1:22  C:\<RC-agent>'  HARDCODED
    tools/legion_agent_boot.ps1:77  C:\<RC-agent>\lcu_agent.py'  HARDCODED
    tools/legion_agent_boot.ps1:86  C:\<RC-agent>\$s"  HARDCODED
    tools/legion_on.ps1:55  C:\<RC>\tools\start_daemon_slayer.py'  HARDCODED
    tools/legion_on.ps1:57  C:\<RC>' -WindowStyle Hidden  HARDCODED
    tools/legion_on.ps1:81  C:\<RC>\rc-shell\node_modules\electron\dist\electron.exe'  HARDCODED
    tools/legion_on.ps1:87  C:\<RC>\rc-shell" "' + $electron + '" .'  HARDCODED
    tools/p3_ascii_census.py:27  C:\<RC>"  HARDCODED
    tools/phase_watcher_install.ps1:28  C:\<RC-agent>",  HARDCODED
    tools/phase_watcher_install.ps1:29  C:\<RC-agent>\event_captures",  HARDCODED
    tools/preflight.cmd:8  C:\<RC>"  HARDCODED
    tools/rollback_last.cmd:8  C:\<RC>"  HARDCODED
    tools/snapshot.cmd:8  C:\<RC>"  HARDCODED
    tools/text_first_guard.py:30  C:\<RC>\ops\runtime\allow_visual.flag")  HARDCODED
    .claude/settings.json (gitignored):28  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\pytest_guard.py  HARDCODED
    .claude/settings.json (gitignored):32  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\edit_lint_check  HARDCODED
    .claude/settings.json (gitignored):44  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\precommit_gate.  HARDCODED
    .claude/settings.json (gitignored):54  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\precommit_gate.  HARDCODED
    .claude/settings.json (gitignored):64  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\text_first_guar  HARDCODED
    .claude/settings.json (gitignored):88  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\rc_facts.py\"",  HARDCODED
    .claude/settings.json (gitignored):93  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\caveman_default  HARDCODED
    .claude/settings.json (gitignored):115  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe\" \"C:\\<RC>\\tools\\stop_claim_gate.  HARDCODED
    .claude/settings.json (gitignored):127  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\rc_facts.py\" -  HARDCODED
    .claude/settings.json (gitignored):131  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\pythonw.exe\" \"C:\\<RC>\\tools\\moon_sync_polle  HARDCODED
    ops/moon_sync_repos.json (gitignored):4  C:\\<LW>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):5  C:\\<RSC>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):6  C:\\<CS>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):7  C:\\<EW>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):8  C:\\<SS>"  HARDCODED
    ops/moon_sync_repos.json (gitignored):11  C:\\<LW>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):12  C:\\<RSC>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):13  C:\\<CS>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):14  C:\\<EW>",  HARDCODED
    ops/moon_sync_repos.json (gitignored):15  C:\\<SS>"  HARDCODED
    ops/moon_sync_repos.json (gitignored):76  C:\\<LL>",  HARDCODED
    .git/config (untracked):core.hookspath  C:\<RC>\.githooks  HARDCODED
    docs/ui_audit/cycle01/_shot.ps1 (gitignored scratch):2  C:\<RC>\docs\ui_audit\cycle01\live_task.png  HARDCODED
    docs/_scratch/bylevel_drift_probe.py (gitignored scratch):19  C:\<RC>  HARDCODED

### EXTERNAL

    schtask:\RC-CIWatchdog:Action (Disabled)  "C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe" "C:\<RC>\tools\ci_watchdog.py" --arm WD=C:\<RC>  EXTERNAL
    schtask:\RC-ClaudeQuotaWatch:Action (Ready)  "C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe" "C:\<RC>\tools\claude_quota_watch.py"  EXTERNAL
    schtask:\RC-CostHealthWatchdog:Action (Ready)  "C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe" "C:\<RC>\tools\cost_health_watchdog.py" WD=C:\<RC>  EXTERNAL
    schtask:\RC-DaemonSlayer:Action (Running)  "C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe" "C:\<RC>\tools\start_daemon_slayer.py"  EXTERNAL
    schtask:\RC-DDragonMirrorRefresh:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\ddragon_mirror_refresh.py" --check-changed  EXTERNAL
    schtask:\RC-DS-MatchDB-MCP:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\start_ds_matchdb_mcp.py"  EXTERNAL
    schtask:\RC-HotkeyListener:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\hotkey_listener.py" WD=C:\<RC>  EXTERNAL
    schtask:\RC-InboxResponder:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\inbox_responder_runner.py" --cycle WD=C:\<RC>  EXTERNAL
    schtask:\RC-LCUAgent:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\lcu_agent.py"  EXTERNAL
    schtask:\RC-LiveClientRelay:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\liveclient_relay.py"  EXTERNAL
    schtask:\RC-LiveFlipWatcher:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\live_flip_watcher.py" WD=C:\<RC>  EXTERNAL
    schtask:\RC-MissionControl:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\mission_control.py" WD=C:\<RC>  EXTERNAL
    schtask:\RC-MoonSyncPoller:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\moon_sync_poller.py" WD=C:\<RC>  EXTERNAL
    schtask:\RC-PatchRefresh:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\scripts\data_pipeline.py" all  EXTERNAL
    schtask:\RC-Phase3-PeriodicAudit:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe -m ops.phase3_file_audit WD=C:\<RC>  EXTERNAL
    schtask:\RC-Phase3-Supervisor:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe -m agents.supervisor WD=C:\<RC>  EXTERNAL
    schtask:\RC-PostmortemAnalyze:Action (Ready)  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\<RC>\ops\run_postmortem_with_restart.ps1"  EXTERNAL
    schtask:\RC-ReplayChainWatch:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\replay_chain_watch.py" WD=C:\<RC>  EXTERNAL
    schtask:\RC-ReplayRosterPull:Action (Running)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\replay_roster_pull.py" --quiet --log-file "C:\<RC>\logs\replay_roster.log" WD=C:\<RC>  EXTERNAL
    schtask:\RC-RewindCatchup:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\scripts\rewind_catchup.py"  EXTERNAL
    schtask:\RC-RoflArchive:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\rofl_archiver.py" --pull --lcu-path --extract --highlights --quiet WD=C:\<RC>  EXTERNAL
    schtask:\RC-RoflDedupe:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\rofl_dedupe.py" --apply WD=C:\<RC>  EXTERNAL
    schtask:\RC-Supervisor:Action (Running)  "C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe" "C:\<RC>\ops\rc_supervisor.py" --config "C:\<RC>\ops\rc_config.json"  EXTERNAL
    schtask:\RC-TeamClaudeProxy:Action (Ready)  wscript.exe "C:\<user-home>\<proxy>_proxy_hidden.vbs"  EXTERNAL
    schtask:\RC-UpstreamDriftCheck:Action (Ready)  C:\<user-home>\AppData\Local\Programs\Python\Python314\pythonw.exe "C:\<RC>\tools\upstream_drift_check.py" --bridge-note  EXTERNAL
    schtask:\RC-WeeklyHygiene:Action (Disabled)  powershell.exe -WindowStyle Hidden -NonInteractive -ExecutionPolicy Bypass -File "C:\<RC>\tools\weekly_hygiene_run.ps1"  EXTERNAL
    shortcut:C:\<user-home>\Desktop\Amberstone Offline.lnk  Target=C:\<RC>\atlas.html WD=C:\<RC>\  EXTERNAL
    shortcut:C:\<user-home>\Desktop\Amberstone repo.lnk  Target=C:\<RC>  EXTERNAL
    shortcut:C:\<user-home>\Desktop\Amberstone.lnk  Target=C:\<RC>\rc-shell\node_modules\electron\dist\electron.exe . WD=C:\<RC>\rc-shell  EXTERNAL
    shortcut:C:\<user-home>\Desktop\Lane Widget.lnk  Target=C:\<RC>\rc-shell\node_modules\electron\dist\electron.exe "C:\<RC>\lane-widget" WD=C:\<RC>\lane-widget  EXTERNAL
    shortcut:C:\<user-home>\Desktop\Legion OFF.lnk  Target=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\<RC>\tools\legion_off.ps1" WD=C:\<RC>  EXTERNAL
    shortcut:C:\<user-home>\Desktop\Legion ON.lnk  Target=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\<RC>\tools\legion_on.ps1" WD=C:\<RC>  EXTERNAL
    shortcut:C:\<user-home>\Desktop\LIVE_GAME_GATED_SYNC.md.lnk  Target=C:\<RC>\docs\LIVE_GAME_GATED_SYNC.md WD=C:\<RC>\docs  EXTERNAL
    shortcut:C:\<user-home>\Desktop\RC-NEXT-SESSION.lnk  Target=C:\<RC>\RC-NEXT-SESSION.txt WD=C:\<RC>  EXTERNAL
    shortcut:C:\<user-home>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\<RC>.lnk  Target=C:\<RC>  EXTERNAL
    claude-code:C:\<user-home>\.claude.json projects keys  C:\<RC> and C:/<RC> (trust + per-project settings; 5 stale keys C:\<RC>\.claude\worktrees\<name>; MCP entry node C:\<RC>\tools\usage-mcp-server.js)  EXTERNAL
    claude-code:C:\<user-home>\.claude\projects\C--<RC>\  project dir keyed by repo path (transcripts + memory\, 538 memory entries - MEMORY.md lives here); 6 more keyed dirs (C--<RC>--claude-worktrees-*, C--<RC-wt>-rc-lane-queue, responder-export, scratchpad)  EXTERNAL
    claude-code:C:\<user-home>\<claude-config-2>\projects\C--<RC>\  second-account project dir keyed by repo path (has memory\)  EXTERNAL
    git-internal:.git/worktrees/<name>/gitdir + <worktree>/.git (x61 worktrees)  gitdir: C:/<RC>/.git/worktrees/<name> and C:/<RC-wt>/<name>/.git  EXTERNAL

### DERIVED

    tools/start_daemon_slayer.py:38  C:\ProgramData")  DERIVED  (env ProgramData first, C: only as fallback)
    tools/start_ds_matchdb_mcp.py:38  C:\ProgramData")  DERIVED  (env ProgramData first, C: only as fallback)
    (plus every module that resolves its root from __file__ / cwd / git; the move-safe default)

### STAYS

    bootstrap_riot_commander_dev.ps1:30  C:\Program Files\Git\cmd\git.exe",  STAYS
    bootstrap_riot_commander_dev.ps1:31  C:\Program Files\Git\bin\git.exe",  STAYS
    bootstrap_riot_commander_dev.ps1:32  C:\Program Files (x86)\Git\cmd\git.exe",  STAYS
    bootstrap_riot_commander_dev.ps1:33  C:\Program Files (x86)\Git\bin\git.exe"  STAYS
    core/build_order_precompute.py:983  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" tools/start_daemon_slayer.py` and re  STAYS
    core/build_order_variants.py:568  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe" tools/start_daemon_slayer.py` and re  STAYS
    core/hud_settings.py:33  C:\Riot Games\League of Legends\Config")  STAYS
    core/league_settings.py:29  C:\Riot Games\League of Legends\Config\game.cfg"  STAYS
    core/vision_tesseract.py:31  C:\Program Files\Tesseract-OCR\tesseract.exe"  STAYS
    game_reader/poller.py:73  C:\Riot Games\League of Legends\lockfile"),  STAYS
    game_reader/poller.py:74  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    lcu/lcu_client.py:39  C:\Riot Games\League of Legends\lockfile"),  STAYS
    lcu/lcu_client.py:40  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    ops/loop/config.fixed.json:4  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe\" ops/loop/done_sentinel.py --tests <  STAYS
    ops/loop/config.gate.json:19  C:\\<user-home>\\AppData\\Roaming\\npm\\claude.cmd",  STAYS
    ops/loop/config.json:22  C:\\<user-home>\\AppData\\Roaming\\npm\\claude.cmd",  STAYS
    ops/loop/config.overlay.json:11  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe\" ops/loop/done_sentinel.py --tests <  STAYS
    ops/loop/config.p5.json:10  C:\\<user-home>\\AppData\\Roaming\\npm\\claude.cmd",  STAYS
    ops/loop/config.rc2.json:11  C:\\<user-home>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe\" ops/loop/done_sentinel.py --tests <  STAYS
    ops/loop/launch_loop.ps1:11  C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"  STAYS
    ops/loop/launch_mdclean.ps1:13  C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"  STAYS
    ops/loop/slots.py:40  C:\ProgramData\<fleet-loop>\slots")  STAYS
    scripts/discover_champion_codes.py:18  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    scripts/discover_champion_codes.py:19  C:\Riot Games\League of Legends\lockfile"),  STAYS
    scripts/probe_missing_codes.py:10  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    scripts/probe_missing_codes.py:11  C:\Riot Games\League of Legends\lockfile"),  STAYS
    scripts/team_planner_sync.py:23  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    scripts/team_planner_sync.py:24  C:\Riot Games\League of Legends\lockfile"),  STAYS
    tft/tft_ocr_reader.py:24  C:\Program Files\Tesseract-OCR\tesseract.exe"  STAYS
    tools/ci_watchdog.py:374  C:\Program Files\GitHub CLI\gh.exe"  STAYS
    tools/lcu_agent.py:151  C:\Riot Games\League of Legends\lockfile"),  STAYS
    tools/lcu_agent.py:152  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    tools/legion_on.ps1:69  C:\Windows\explorer.exe' -ArgumentList 'shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude'  STAYS
    tools/live_write_tracer.py:119  C:\ProgramData\<fleet-loop>",)  STAYS
    tools/phase_watcher.py:88  C:\Riot Games\League of Legends\lockfile"),  STAYS
    tools/phase_watcher.py:89  C:\Riot Games\League of Legends (PBE)\lockfile"),  STAYS
    tools/rc_headless_launcher.ps1:27  C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe"  STAYS
    tools/rofl_archiver.py:44  C:\Riot Games\League of Legends\lockfile")  STAYS
    vision_server/_inference.py:373  C:\Program Files\Tesseract-OCR\tesseract.exe"  STAYS
    .claude/settings.json (gitignored):76  C:/<user-home>/.perseus-vault/bin/perseus-vault.exe\" maintain --db \"C:/<user-home>/.perseus-vault/data/perse  STAYS
    .claude/settings.json (gitignored):102  C:/<user-home>/.perseus-vault/bin/perseus-vault.exe\" prepare --task \"<RC> League TFT coaching dashboard Daem  STAYS
    .mcp.json (gitignored):7  C:\\<user-home>\\.perseus-vault\\data\\perseus-vault.db"  STAYS
    .mcp.json (gitignored):9  C:\\<user-home>\\.perseus-vault\\bin\\perseus-vault.exe"  STAYS
    ops/moon_sync_repos.json (gitignored):60  C:\\<user-home>\\.config\\<proxy>.state.json",  STAYS
    docs/ui_audit/cycle01/_shot.ps1 (gitignored scratch):1  C:\Program Files\Google\Chrome\Application\chrome.exe  STAYS

## 3. DOC - aggregated per file (path  hit-lines)

Tracked prose and comments, inert test-fixture literals (tests/, lane-widget/test/),
generated audit reports (ops/audit/) and the example config. docs/_archive is one row.
Gitignored runtime records under ops/runtime/ (pytest captures, validation reports) and
ops/loop/control/ scratch also carry C:\<RC> strings; they are records, not config -
regenerated on the next run, not edited.

    BACKLOG.md  12
    CLAUDE.md  6
    RC-NEXT-SESSION.txt  1
    bootstrap_riot_commander_dev.ps1  3
    core/build_order_precompute.py  1
    core/build_order_variants.py  1
    core/laning_scenario_precompute.py  1
    core/operator_push.py  1
    core/pickban_targets.py  1
    core/ports.py  1
    core/vision_token.py  1
    data/rewind_scraper.log  1
    docs/ARCHITECTURE.md  1
    docs/CHERRY_AUGMENT_SCAFFOLD_NOTES.md  4
    docs/CI_WATCHDOG_PLAN.md  3
    docs/CONCURRENT_HEADLESS_CONTRACT.md  4
    docs/COST_LATENCY_SWEEP_2026-08-02.md  2
    docs/CROSS_REPO_CONVERGENCE_CHARTER.md  4
    docs/DISCOVERY_AXIS_RC_2026-09-13.md  4
    docs/LEDGER.md  54
    docs/LIVE_GAME_GATED_SYNC.md  1
    docs/MISSION_CONTROL_PLAN.md  5
    docs/OPERATIONS.md  27
    docs/ORCHESTRATION_PLAN.md  2
    docs/ORPHAN_SUITE_AUDIT_2026-09-11.md  3
    docs/PORTABLE_PROJECT_CONVENTIONS.md  1
    docs/PRE_RELEASE_NAME_SCRUB.md  1
    docs/PUBLIC_FLIP_GO_NO_GO.md  1
    docs/RENAME_SWEEP_AMBERSTONE.md  1
    docs/RESPONDER_RUNNER_SPEC.md  6
    docs/ROADMAP_HISTORY.md  12
    docs/_archive/** (all files, aggregate)  51
    docs/_overlap/RESULT.md  1
    docs/_rescore/tally.py  2
    docs/_rescore/tally_report.md  2
    docs/_rsc_score/CALIBRATION_REPLICATION.md  1
    docs/_rsc_score/P1_RESULT.md  1
    docs/_rsc_score/calibrate.py  3
    docs/_rsc_score/calibrate_rep.py  3
    docs/_scratch_fparm_B.md  1
    docs/_scratch_gitbucket_D.md  11
    docs/adr/ADR-006-riot-api-key-policy.md  1
    docs/audits/LF_WRITER_DIRECT_COVERAGE_2026-09-11.md  2
    docs/claude-md-history.md  7
    docs/handoff/DONE_RITUAL_OPTIMIZED.md  3
    docs/handoff/POWERSHELL_7_MIGRATION.md  9
    docs/history_notes.md  117
    docs/qa/OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md  1
    docs/qa/SPATIAL_BRAND_SPEC_2026-07-22.md  1
    docs/qa/UI_UX_QUEUE_2026-07-21.md  1
    docs/specs/2026-07-16-fable5-forward-leap-kickoff.md  3
    docs/specs/2026-07-19-silent-except-triage.md  2
    docs/specs/2026-09-20-shared-git-root-bucket-rc-share-scan.md  6
    docs/specs/LANE_A_SCENARIO_PRECOMPUTE_SPEC.md  5
    docs/specs/channel_round_2026-09-20_triage.md  5
    docs/specs/leap/kickoff_LEAP-01.txt  1
    docs/specs/leap/kickoff_LEAP-02.txt  1
    docs/specs/leap/kickoff_LEAP-03.txt  1
    docs/specs/leap/kickoff_LEAP-04.txt  1
    docs/specs/leap/kickoff_LEAP-05.txt  1
    docs/specs/leap/kickoff_LEAP-06.txt  1
    docs/specs/leap/kickoff_LEAP-07.txt  1
    docs/specs/leap/kickoff_LEAP-08.txt  1
    docs/specs/mission_control_removal_gap_analysis.md  2
    docs/superpowers/plans/2026-07-04-player-snapshot-card.md  5
    docs/superpowers/plans/2026-07-31-mission-control-s10-decouple.md  3
    lane-widget/README.md  1
    lane-widget/test/governor.test.js  7
    lane-widget/test/locks.test.js  4
    lane-widget/test/model.test.js  6
    lane-widget/test/poll.test.js  12
    lane-widget/test/render.test.js  5
    lane-widget/test/repos.test.js  41
    lcu/lcu_postgame_collector.py  1
    ops/RC-CIWatchdog.xml  1
    ops/audit/P2_FINDINGS.md  1
    ops/audit/lolmath_ds_sweep/g5_live_rank_probe.py  1
    ops/audit/lolmath_ds_sweep/g5_pool_probe.py  1
    ops/audit/lolmath_ds_sweep/rescrape.mjs  1
    ops/audit/lolmath_ds_sweep/sweep.mjs  1
    ops/audit/lolmath_ds_sweep/ultimate.mjs  1
    ops/audit/p0_truth_gate_report.json  2
    ops/audit/p1a_truth_gate_report.json  2
    ops/audit/p1b_truth_gate_report.json  2
    ops/audit/p1c_truth_gate_report.json  2
    ops/audit/p2a_truth_gate_report.json  2
    ops/audit/p2b_claims.json  1
    ops/audit/p2b_truth_gate_report.json  2
    ops/audit/p2w1_app_truth_gate_report.json  2
    ops/audit/p2w1_coach_truth_gate_report.json  2
    ops/audit/p2w1_dash_truth_gate_report.json  2
    ops/audit/p2w1_truth_gate_report.json  2
    ops/audit/p2w2_ds_hw2_truth_gate_report.json  2
    ops/audit/p2w2_ds_truth_gate_report.json  2
    ops/audit/p2w3_web_truth_gate_report.json  2
    ops/audit/p2w4_hw2_pytest.txt  9
    ops/audit/p2w4_tools_truth_gate_report.json  2
    ops/audit/p2w5_truth_gate_report.json  1
    ops/install_RC_InboxResponder.ps1  3
    ops/launch_new_system.bat  2
    ops/loop/CDRAGON_FLIP_FINDINGS.md  2
    ops/loop/config.json  2
    ops/loop/director_prompt.md  1
    ops/loop/lane_launcher.py  1
    ops/loop/launch_queue_loop.ps1  3
    ops/loop/prompts/drain_w23_common.md  2
    ops/loop/prompts/drain_w23_merger.md  3
    ops/loop/prompts/drain_w23_verifier.md  1
    ops/loop/prompts/lane_research_prompt.md  2
    ops/loop/prompts/lane_ui_prompt.md  1
    ops/loop/queue_loop.py  2
    ops/moon_sync_repos.example.json  7
    ops/phase3_install.ps1  1
    ops/phase3_setup.py  1
    ops/rc_transactional_deploy.py  1
    ops/tls/_bridge_msg.txt  1
    scripts/rewind_scraper.py  1
    tests/_kit_platform.py  1
    tests/fixtures/stop_claim_gate_false_positives.jsonl  74
    tests/test_aram_item_interaction_snapshot_tracked.py  1
    tests/test_champion_loadout_autogen.py  1
    tests/test_ci_watchdog.py  2
    tests/test_config_validator.py  1
    tests/test_dashboard_error_scrub_rm134.py  2
    tests/test_home_summary_cache.py  1
    tests/test_inbox_responder_exec.py  3
    tests/test_inbox_responder_export.py  1
    tests/test_inbox_responder_mutants.py  2
    tests/test_inbox_responder_runner.py  5
    tests/test_inbox_responder_spawn.py  12
    tests/test_inbox_responder_validator.py  2
    tests/test_lane_launcher.py  1
    tests/test_lane_pid_reuse.py  1
    tests/test_lcu_lockfile_notice_dedupe.py  2
    tests/test_lcu_push_watcher.py  2
    tests/test_loop_concurrency.py  2
    tests/test_loop_control_idempotency.py  5
    tests/test_loop_director_prompt_rules.py  1
    tests/test_loop_executor.py  1
    tests/test_loop_module_root_resolution.py  1
    tests/test_loop_status_route.py  5
    tests/test_moon_sync_poller.py  1
    tests/test_moon_sync_status_route.py  4
    tests/test_no_console_flash_scheduled_tools.py  2
    tests/test_no_hardcoded_home_path.py  6
    tests/test_operator_push.py  1
    tests/test_p2w1_dash_e.py  3
    tests/test_postmortem_runner_pipe.py  1
    tests/test_precommit_gate.py  5
    tests/test_pytest_guard.py  2
    tests/test_queue_loop.py  2
    tests/test_rank_tier_live_budget.py  2
    tests/test_rc_dev_runtime_atomic_write_retry.py  2
    tests/test_routes_diag_lane8_cycle18.py  2
    tests/test_routes_loadout_lane8_cycle38.py  1
    tests/test_routes_pickban_id_cap.py  1
    tests/test_routes_state_health_scrub.py  2
    tests/test_rune_pages_route.py  1
    tests/test_session_intents.py  1
    tests/test_sibling_name_sweep.py  27
    tests/test_slot_bucket_audit_rm504.py  2
    tests/test_sr_user_builds_lane8_cycle22.py  1
    tests/test_stop_claim_gate.py  6
    tests/test_stop_claim_gate_deferred_rm498.py  2
    tests/test_stop_claim_gate_long_run_rm431.py  1
    tests/test_vision_server_http_hardening.py  1
    tests/test_vision_server_reap_orphans.py  5
    tools/DEV_WORKFLOW.md  1
    tools/LAUNCH_STRATEGY.md  1
    tools/champion_loadout_autogen.py  1
    tools/ci_watchdog_fix.md  1
    tools/daemon_slayer_build_orders_generate.py  1
    tools/daemon_slayer_pickban_targets_generate.py  1
    tools/directed-headless-upgrade.md  11
    tools/done.md  6
    tools/ds_matchdb_mcp_server.py  2
    tools/extract_panels.py  1
    tools/headless-ds.md  2
    tools/headless-gated.md  3
    tools/headless-queue.md  10
    tools/headless-repo.md  8
    tools/headless-research.md  4
    tools/headless-true-audit.md  9
    tools/headless-uiux.md  4
    tools/headless-upgrade.md  7
    tools/headless_run.ps1  1
    tools/hotkey_listener.py  3
    tools/keybind_listener.py  3
    tools/liveclient_relay.py  2
    tools/orchestrated-run.md  1
    tools/phase_watcher.py  3
    tools/phase_watcher_install.ps1  2
    tools/precommit_gate.py  1
    tools/preflight.cmd  1
    tools/repo-insights.md  2
    tools/rollback_last.cmd  1
    tools/screen_agent.py  4
    tools/snapshot.cmd  1
    tools/start_daemon_slayer.py  1
    tools/start_ds_matchdb_mcp.py  1
    tools/stop_claim_gate.py  4
    tools/sync-all-md.md  3
    tools/usage-mcp-server.js  1
    tools/weekly-hygiene.md  2
    tools/weekly_hygiene_run.ps1  1

## 4. C: worktrees and scratch dirs RC owns (git cherry main <branch>, run 2026-10-07)

Root C:\<RC-wt>\ (default of ops/loop/lane_launcher.py WORKTREE_BASE, env RC_LANE_WORKTREE_BASE overrides).
NEEDED = keep / recreate at E:. NOT NEEDED = all commits on main (cherry "-" only or 0/0),
safe to prune instead of moving. REVIEW = carries a "+" commit whose subject is not on main.

    C:\<RC-wt>\rc-lane-{ds,queue,repo,research,true-audit,uiux}  lane/*  +0 -0  NEEDED (lane infra; clean; can be re-added at E: rather than moved)
    C:\<RC-wt>\rc-ingest   ingest/rc-fleet-ideas  +0 -0  NOT NEEDED
    C:\<RC-wt>\rc-lift1    ingest/lift1           +0 -0  NOT NEEDED
    C:\<RC-wt>\rc-lift2    ingest/lift2           +0 -0  NOT NEEDED
    C:\<RC-wt>\lift1-{ci-fix,draft-log,ds-audits,ds-batch,ds-batch-fix,lc-hygiene,mark-hotkey,opening-tendency,raw-docs,scrubber-minimap,self-cast,session-recorder,skill-points,wr-helper}  "-" only  NOT NEEDED (14)
    C:\<RC-wt>\lift1-{death-recap,event-sse,item-tape,obs-record}  "+" but same subjects on main (re-patched at ingest)  NOT NEEDED (4)
    C:\<RC-wt>\lift1-death-reel      +2 (1 subject not on main: drive-less test paths)        REVIEW
    C:\<RC-wt>\lift1-review-player   +2 -2 (1 not on main: drive-less sidecar fixture)         REVIEW
    C:\<RC-wt>\lift1-vod-retention   +4 (3 not on main: sidecar shape, drop drive-letter literals, PROVEN marks)  REVIEW
    C:\<RC-wt>\lift2-{y01,y02,y03,y04,y05,y06,y09,y12,y44}  "-" only  NOT NEEDED (9)
    C:\<RC-wt>\lift2-{y07,y08,y11-y13}  "+" but same subjects on main  NOT NEEDED (3)
    C:\<RC-wt>\lift2-y45             +2 (1 not on main: privacy sweep + own-tailnet gate)      REVIEW
    C:\<RC-wt>\before_sweep_s2.txt   stray scratch file                                         NOT NEEDED
    In-tree C:\<RC>\.claude\worktrees\ (moves with the tree; gitdir links still need repair):
    agent-{a1f2b1c7,a28bb1b0,a5ae4bf4,abd89ea3,af827986}...  "+" = pre-squash slice history; hand-off: all content in 5c2cadb4e  NOT NEEDED (5)
    agent-a4cfeb79...  +0 -1 (hand-off "merged as 7e32c2933"; cherry confirms)                  NOT NEEDED
    agent-{a2da8cd3,a51771ce,a54aeb55,ab80357a,acb7535b,acf850b2,adf821a1,a475ee38,af0001a3}...  "-" only or 0/0  NOT NEEDED (9)
    agent-a74306a8...  LOCKED at main HEAD (a live agent session holds it)                      NEEDED until its agent ends
    drain-wave2-atomic        drain/wave2-atomic        +1 -4   hand-off KEEP (review before -D)  REVIEW
    drain-wave2-tail-backlog  drain/wave2-tail-backlog  +4 -9 (2 subjects not on main: RM-432 ADR-016, RM-229)  REVIEW
    Branch-only, no worktree: worktree-agent-a0a31cf1 +1 (hand-off: superseded by kit v4) REVIEW;
    ingest/rc-p210, ingest/rc-p24, ingest/rc-p25 +0 -1 NOT NEEDED.
    Hand-off-listed but ABSENT now: worktree-wf_0815ac54-8f2-4/-5, RM-256 / RM-297b branches,
    detached C:\<RC-wt>\done-20261004 - nothing to move.

Totals: 61 worktrees (43 under C:\<RC-wt>, 18 in-tree). NEEDED 7 (6 lanes + 1 locked);
REVIEW 7 worktrees + 1 branch; everything else NOT NEEDED. Dirty: none (only the main
checkout has uncommitted files - an un-acked DDragon refresh, not authored by this run).

Scratch dirs: C:\<RC-agent>\ (tools/legion_agent_boot.ps1, phase_watcher_install.ps1) and
C:\<RC-ciwd>\ (tools/ci_watchdog.py WORKTREE, task RC-CIWatchdog Disabled) are referenced
but ABSENT on disk - nothing to move; the code defaults stay HARDCODED rows above.
Other C: roots RC uses but does not own: C:\ProgramData\<fleet-loop>\slots (fleet slot
dir, byte-pinned ops/loop/slots.py DEFAULT_ROOT - a joint act if it moves), C:\Riot Games\
(League client), C:\<user-home>\ (interpreter, claude.cmd, vault).

## 5. Batched - other items owed to MAIN

- Item F (fold inbox handling into the lane/loop tick, MAIN 0310 / 0327) is still OPEN;
  RC-InboxResponder is unattended until then. The ANSWER for F follows when it lands.
- Nothing else owed. This note is the one answer to 2155; no follow-ups.

TERMINAL for this order unless MAIN's runbook asks a new question.
