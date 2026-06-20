# GAMEPC_PURGE_SPEC - Make Riot Commander a Legion-only codebase

Status: SPEC ONLY (no source edits performed by this pass).
Author pass: 2026-06-20. Ground truth = Read/Grep cited file:line below.
Trigger: RC consolidated to 1-PC (Legion) 2026-05-29 per ADR-011. Game-PC is
out of the League/RC pipeline. "We are Legion." ADR-011 itself lists this exact
work as deferred Phase-11 cleanup (docs/adr/ADR-011-one-pc-consolidation.md:72-74:
"archive of the gamepc_*.py originals, ARCHITECTURE topology rewrite",
"Legion<->Game-PC bridge teardown").

Buckets:
  DOC-PURGE       rewrite 2-PC-era topology prose to Legion-only
  RENAME-REWIRE   rename mis-named gamepc_*.py + fix every referencer
  SEVER           remove cross-Claude Game-PC bridge peer + gamepc MCP
  FROZEN-PURGE    edit authorized for this purge but file is on the frozen list
  REGEN-DATA      generated artifact - regenerate after rename, do not hand-edit
  PRESERVE        immutable dated history / generated - DO NOT EDIT
  FALSE-POSITIVE  matched the search but carries no Game-PC coupling

Confirmed up front (operator-stated, verified):
- Scheduled-task NAMES RC-LCUAgent / RC-LiveClientRelay / RC-HotkeyListener are
  already Legion-neutral. DO NOT rename tasks. Only the gamepc_*.py FILENAMES are
  mis-named. NOTE: no ops/*.xml exists for these three relocated agents (Glob
  ops/*.xml = RC-DaemonSlayer, RC-CostHealthWatchdog, RC-BridgeWatcher,
  RC-CIWatchdog, RC-Supervisor only). They are registered live via schtasks, not
  checked-in XML. The only checked-in task-install surface for renamed files is
  tools/gamepc_phase_watcher_install.ps1 (RC-PhaseWatcher) + the schtasks
  examples embedded in each agent docstring + tools/gamepc_boot.ps1.
- core/moon_proxy.py = Moonbeam vision proxy (FROZEN). Confirmed FALSE-POSITIVE
  for "moon-pc": grep shows only "moon_proxy"/"MoonProxy" (core/moon_proxy.py:3,
  19,61,207). No gamepc, no moon-pc host. Do NOT touch.
- No agents/daemon_slayer/** file matches gamepc (Grep agents/daemon_slayer/**
  = no files). => ds_share_sync NOT required for this purge unless a slice
  edits a mirrored tools/ file (none of the renamed files are DS-mirrored).
- "moon-pc" / "moonpc" / "two-PC": zero code hits beyond moon_proxy false
  positive; "2-PC"/"2 PC" appear only as prose in docs (handled by DOC-PURGE).

================================================================================
## Section A - Bucket table (files with REAL refs)
================================================================================

### RENAME-REWIRE - the six mis-named relocated-agent source files
| File | Bucket | Action |
|---|---|---|
| tools/gamepc_lcu_agent.py | RENAME-REWIRE | -> tools/lcu_agent.py; rewrite header "Game-PC agent" -> "Legion-local LCU agent (relocated 2026-05-29, ADR-011)"; drop Game-PC deploy steps |
| tools/gamepc_liveclient_relay.py | RENAME-REWIRE | -> tools/liveclient_relay.py; same header rewrite; relay now self-heals in-process |
| tools/gamepc_hotkey_listener.py | RENAME-REWIRE | -> tools/hotkey_listener.py; header rewrite |
| tools/gamepc_keybind_listener.py | RENAME-REWIRE | -> tools/keybind_listener.py; header rewrite (note: NOT in /agent allowlist nor boot.ps1; optional ADR-007 listener) |
| tools/gamepc_screen_agent.py | RENAME-REWIRE | -> tools/screen_agent.py; header rewrite (2-PC-era name; now Legion self-grab source) |
| tools/gamepc_phase_watcher.py | RENAME-REWIRE | -> tools/phase_watcher.py; header rewrite; update self-ref to installer path |

### RENAME-REWIRE - referencers of the six files (must move in the SAME slice)
| File | Bucket | Action |
|---|---|---|
| tools/gamepc_phase_watcher_install.ps1 | RENAME-REWIRE | -> tools/phase_watcher_install.ps1; update WatcherPath/Url to phase_watcher.py; RC-PhaseWatcher task name is fine to KEEP (Legion-neutral) but recast Game-PC prose |
| tools/gamepc_boot.ps1 | RENAME-REWIRE + DOC-PURGE | rename -> tools/legion_agent_boot.ps1 (or keep name, operator call); update $AGENT_SCRIPTS / $SUPPORT_SCRIPTS / Start-Process arg paths to new filenames (lines 45-46, 108-148); recast "Game-PC boot" banner; SEE Section C (also an MCP-launch + bridge-daemon host) |
| dashboard/routes_static.py | RENAME-REWIRE | _AGENT_ALLOWED set (lines 130-164) lists old filenames; replace gamepc_*.py entries with new names (or remove if agent-fetch deploy is retired - operator call). FROZEN? NO (not on frozen list) |
| coaches/loadout_resolver.py | DOC-PURGE | docstring ref "gamepc_lcu_agent command queue" (line 5) -> "lcu_agent command queue" |
| modes/shared_vision.py | DOC-PURGE | comment refs (lines 21-22, 38, 48, 85) "Game-PC screen agent" / gamepc_screen_agent.py -> Legion-local screen_agent.py |
| dashboard/_liveclient.py | DOC-PURGE | docstring (lines 7-8, 49) names gamepc_lcu_agent.py / gamepc_liveclient_relay.py -> new names |
| dashboard/_state_cooldowns.py | DOC-PURGE | docstring (line 5) gamepc_liveclient_relay.py -> liveclient_relay.py |
| game_reader/poller.py | DOC-PURGE | comments (lines 46, 74, 136, 144, 192) "Game-PC contention"/"localhost-only on Game-PC" -> Legion-local wording |
| tools/ds_matchdb_mcp_server.py | DOC-PURGE | comments (lines 7, 133, 187) reference gamepc_mcp_server as auth/bind sibling -> update or drop |
| tools/legion_bridge_daemon.py | DOC-PURGE | docstring (line 7) "Mirrors tools/gamepc_bridge_daemon.py" -> drop gamepc sibling once daemon removed (see SEVER) |

### RENAME-REWIRE - test files importing the renamed modules (SAME slice as the .py they import)
| File | Bucket | Action |
|---|---|---|
| tests/phase_b_champ_select/test_lcu_agent_phase_b.py | RENAME-REWIRE | `import gamepc_lcu_agent` (line 29) + docstring (3) + drift literal (437) -> lcu_agent |
| tests/phase_b_champ_select/test_lcu_mastery.py | RENAME-REWIRE | `import gamepc_lcu_agent` (line 23) + docstring (3) |
| tests/phase_b_champ_select/test_lcu_lobby_members.py | RENAME-REWIRE | `import gamepc_lcu_agent` (line 21) + docstring (3) |
| tests/fu02_team_context/test_lcu_agent_refresh.py | RENAME-REWIRE | `import gamepc_lcu_agent` (line 26) + docstring (3) |
| tests/test_apply_runes_page_filter.py | RENAME-REWIRE | _AGENT path const (line 22) "tools"/"gamepc_lcu_agent.py" + docstring (1) |
| tests/test_csv_rune_push_on_selection_change.py | RENAME-REWIRE | GAMEPC_AGENT const (line 43) + docstring (21) + assert msg (194) |
| tests/test_lcu_item_sets_wipe_stale.py | RENAME-REWIRE | _AGENT_PATH const (line 38) + loader spec name (47) + docstring (42) |
| tests/test_gamepc_phase_watcher.py | RENAME-REWIRE | _WATCHER_PATH const (line 32), spec name (38), many docstring refs -> phase_watcher.py; rename file -> tests/test_phase_watcher.py |
| tests/test_gamepc_mcp_watchdog.py | SEVER (delete) | imports tools.gamepc_mcp_server (line 27); the server is severed - delete this test with the server (see Section C). If MCP server is instead archived not deleted, keep+rename |
| tests/test_active_match_mock_fixtures.py | DOC-PURGE | comment cite (line 145) "gamepc_lcu_agent.py:536" -> new path |
| tests/test_bare_py_ban.py | DOC-PURGE/RENAME | line 60 allowlists "tools/gamepc_phase_watcher_install.ps1" as retired surface -> update to phase_watcher_install.ps1 (or remove if installer retired) |

### SEVER - cross-Claude Game-PC bridge peer + gamepc MCP
| File | Bucket | Action |
|---|---|---|
| .mcp.json | SEVER | remove the entire "gamepc" mcpServers entry (lines 3-10). Leaves `{ "mcpServers": {} }` (no peer MCP entry exists here today) |
| tools/gamepc_mcp_server.py | SEVER | delete (or archive to docs/_archive/). Binds :8892 on Game-PC; no Legion consumer remains once .mcp.json + game-monitor repointed |
| tools/gamepc_bridge_daemon.py | SEVER | delete/archive. Game-PC-side bridge sentinel (TARGET="gamepc", line 29). Legion peer gone |
| tools/GAMEPC_CLAUDE.md | SEVER | delete/archive. Game-PC peer's CLAUDE.md (28 gamepc hits); also remove from routes_static _AGENT_ALLOWED |
| tools/start_gamepc_claude.ps1 | SEVER | delete/archive. Launches Claude on Game-PC; remove from _AGENT_ALLOWED + boot.ps1 fallback |
| tools/done-gamepc.md | SEVER | delete/archive. Game-PC /done slash command; remove from _AGENT_ALLOWED + boot.ps1 SLASH map |
| tools/wrap-gamepc.md | SEVER | delete/archive. Game-PC wrap command |
| .claude/commands/game-monitor.md | SEVER (repoint) | line 9 uses mcp__gamepc__capture_monitor -> repoint to Legion-local capture (see Section C). FROZEN? NO |
| tools/scheduled_boot_verify.py | SEVER | dispatches a bridge task target="gamepc" (line 60). Repoint to target="legion" or drop the gamepc post-boot check |
| tools/rc_facts.py | SEVER | hardcoded _GAMEPC_MCP_HEALTH (line 39), _GAMEPC_TOKEN (40), _gamepc_mcp_anomaly() (207), entire "## Game-PC" report section (326-380). Remove the Game-PC block; keep Peer. NOTE already has RC_GAMEPC_RETIRED demotion (56) - this is the full removal |
| tools/bridge_dispatch_enable_lanes.py | SEVER (de-scope) | VALID_TARGETS=("gamepc","peer") (line 51) + usage examples -> drop gamepc; leave peer |
| dashboard/routes_health_peer.py | SEVER | _VALID_NODES={"gamepc","peer"} (line 31) -> {"peer"}. FROZEN? NO |
| dashboard/_bridge_log.py | SEVER | gamepc_result_age_s() (lines 159-172) + kind/target doc (15) -> remove gamepc-specific accessor (or generalize to peer). FROZEN? NO |
| dashboard/routes_metrics.py | SEVER | _G_BRIDGE_AGE gauge rc_bridge_gamepc_result_age_seconds (line 44) + import gamepc_result_age_s (70-71) -> remove or rename to peer. FROZEN? NO |
| web/js/main.js | SEVER | bridge.gamepc_result_age_s usage (lines 7145-7161) -> remove/rename; peer loop (7165-7189) already generic over j.peers keys so it self-prunes once routes_health_peer drops gamepc |
| tools/verify_bridge_roundtrip.py | SEVER (verify) | references gamepc peer in roundtrip self-test -> drop gamepc leg, keep peer |
| tools/verify-rc-rootca-on-gamepc.cmd | SEVER | delete/archive. Game-PC cert installer |
| tools/install-rc-rootca-on-gamepc.cmd | SEVER | delete/archive. Game-PC cert installer |
| tools/chrome-import-rc-rootca.txt | DOC-PURGE | Game-PC browser cert note -> recast or archive |
| ops/install_RC_LegionBridgeDaemon.ps1 | DOC-PURGE | mentions gamepc sibling daemon; update prose once gamepc daemon removed |

### DOC-PURGE - living docs (rewrite 2-PC topology to Legion-only)
| File | Bucket | Action |
|---|---|---|
| CLAUDE.md | FROZEN-PURGE? NO (not frozen, but CI-size-budgeted <60KB) | Topology table (Game-PC row), frozen-file list (gamepc_*.py paths once renamed), vision-pipeline prose ("gamepc_screen_agent.py 2-PC-era name"), "Game-PC out of pipeline" lines -> Legion-only. KEEP size budget in mind |
| docs/ARCHITECTURE.md | DOC-PURGE | module map + topology -> Legion-only; update renamed file paths |
| docs/OPERATIONS.md | DOC-PURGE | scheduled-task list + ops commands referencing Game-PC -> Legion-only |
| docs/BRIDGE.md | DOC-PURGE | wire format names target "gamepc" peer -> recast as Peer-only peer; note Game-PC peer severed |
| ROADMAP.md | DOC-PURGE | Game-PC / 2-PC open items -> close/relabel |
| BACKLOG.md | DOC-PURGE | (grep flagged) Game-PC aspirational items -> recast |
| docs/API.md | DOC-PURGE | endpoint docs referencing gamepc agents -> new names |
| docs/AGENTS.md | DOC-PURGE | Phase 3 framework Game-PC mentions -> Legion-only |
| README (rc-shell/README.md) | DOC-PURGE | 2-PC mentions -> Legion-only |
| docs/RC2_PLAN.md | DOC-PURGE | (modified in working tree) Game-PC mentions -> Legion-only |
| docs/adr/ADR-011-one-pc-consolidation.md | DOC-PURGE (recast, KEEP) | ADR stays as the record; mark the deferred Phase-11 items (lines 72-74) DONE; recast Game-PC as retired, not pending |
| docs/adr/ADR-005-tailscale-magicdns.md | DOC-PURGE | gamepc-rc hostname example -> annotate retired-from-pipeline |
| docs/adr/ADR-007-event-coach-pivot.md | DOC-PURGE | Game-PC keybind-listener prose -> Legion-local |

### DOC-PURGE - slash-command + tools/*.md command files
| File | Bucket | Action |
|---|---|---|
| .claude/commands/done.md | DOC-PURGE | bridge gamepc probe (line 79) + "bridge loop (gamepc)" banner (168) -> drop gamepc leg or switch to peer |
| .claude/commands/process-bridge-tasks.md | DOC-PURGE | <gamepc|peer> reply-to (line 11) -> peer-only (Game-PC no longer dispatches) |
| .claude/commands/orchestrated-run.md | DOC-PURGE | "Game-PC :8892" validation note (line 33) -> remove |
| .claude/commands/headless-upgrade.md | DOC-PURGE | Game-PC MCP :8892 + clean-room sandbox sections (lines 68,76,104,140) -> remove Game-PC sandbox path |
| .claude/commands/gemini-headless-upgrade.md | DOC-PURGE | mcp__gamepc__capture_monitor (110), :8892 (121), gamepc sandbox (186) -> Legion-local |
| .claude/commands/weekly-hygiene.md | DOC-PURGE (KEEP intent) | already treats gamepc :8892 / 2-PC as retired-infra hits (lines 45,58); update once purge lands so it no longer expects them |
| tools/process-bridge-tasks.md | FROZEN-PURGE | frozen file; gamepc reply-to mention -> peer-only. LIST under frozen bucket |
| tools/process-bridge-tasks-peer.md | DOC-PURGE | cross-refs gamepc variant -> update |
| tools/diagnose.md | FROZEN-PURGE | frozen; check for gamepc mentions -> Legion-only |
| tools/caveman.md | FROZEN-PURGE | frozen; check for gamepc mentions |

### FROZEN-PURGE - frozen-list files needing edits (authorized for this purge)
| File | Bucket | Action |
|---|---|---|
| CLAUDE.md frozen-file LIST entry | FROZEN-PURGE | the frozen list itself names tools/process-bridge-tasks.md, tools/diagnose.md, tools/caveman.md, etc.; AND once gamepc_*.py are renamed, any frozen-list path must update. Verify none of the SIX renamed agents are on the frozen list (they are NOT - frozen list has lcu/lcu_client.py, core/game_snapshot.py, app/*, ops/* supervisors, bridge_watcher_*, bridge_post_result.py, bridge_pull_tasks.py, dashboard/routes_bridge_pending.py, ops/RC-BridgeWatcher.xml - none are gamepc_*.py) |
| tools/process-bridge-tasks.md | FROZEN-PURGE | see DOC-PURGE row; listed here because frozen |
| tools/diagnose.md | FROZEN-PURGE | scan + Legion-only |
| tools/caveman.md | FROZEN-PURGE | scan + Legion-only |
| .gitignore | DOC-PURGE | grep flagged; check gamepc patterns (event_captures etc.) - keep ignore rules, update comments only |

NOTE: core/moon_proxy.py IS frozen and DID match the search but is FALSE-POSITIVE
(Moonbeam proxy). Do NOT edit. lcu/lcu_client.py is frozen; verify it carries no
gamepc string (grep clean in this pass).

### REGEN-DATA - generated artifacts (regenerate, do not hand-edit)
| File | Bucket | Action |
|---|---|---|
| data/api_surface.csv | REGEN-DATA | rows cite tools/gamepc_lcu_agent.py:NNN (lines 11,14-17,191-195+). Regenerate via the api-surface generator AFTER rename so it picks up tools/lcu_agent.py. Flag: do not sed the CSV |
| data/event_captures/** (.gitkeep) | REGEN-DATA/PRESERVE | sidecar capture dir; .gitkeep stays. Any captured frames are runtime data - leave |

### FALSE-POSITIVE
| File | Bucket | Why |
|---|---|---|
| core/moon_proxy.py | FALSE-POSITIVE | "moon_proxy"/"MoonProxy" only; Moonbeam vision proxy, FROZEN, no Game-PC coupling |
| web/data/ui_mock/active_match_arena.json | FALSE-POSITIVE/REGEN | "game-pc-league" channel string in a mock fixture; cosmetic. Update string if desired, not load-bearing |
| docs/research/RC2_* , docs/RC2_*_QA.md | DOC-PURGE (low pri) | RC2 research notes mention 2-PC history; recast if swept, else leave as research |

### PRESERVE - DO NOT EDIT (immutable dated history / generated)
docs/history_notes.md ; docs/ROADMAP_HISTORY.md ; docs/_archive/** ;
"docs io RC peer/**" ; agents/agent6_auditor/reports/** ;
agents/agent6_auditor/proposals/** ; ops/audit/** dated *.md + *.json
(P0/P1/P2/P3 workmaps, truth-gate json, slices) ; docs/LEDGER.md ;
all *.log + *.log.N + *.jsonl ; ops/tls/_bridge_msg.txt (bridge artifact).
(Grep matched all of these; they are history/artifacts and are explicitly out
of scope per the operator PRESERVE list.)

================================================================================
## Section B - RENAME-REWIRE detail (old -> new + full referencer list)
================================================================================

Rename map (operator may tweak target names):
  tools/gamepc_lcu_agent.py          -> tools/lcu_agent.py
  tools/gamepc_liveclient_relay.py   -> tools/liveclient_relay.py
  tools/gamepc_hotkey_listener.py    -> tools/hotkey_listener.py
  tools/gamepc_keybind_listener.py   -> tools/keybind_listener.py
  tools/gamepc_screen_agent.py       -> tools/screen_agent.py
  tools/gamepc_phase_watcher.py      -> tools/phase_watcher.py
  tools/gamepc_phase_watcher_install.ps1 -> tools/phase_watcher_install.ps1
  tools/gamepc_boot.ps1              -> tools/legion_agent_boot.ps1 (or keep)
  tests/test_gamepc_phase_watcher.py -> tests/test_phase_watcher.py

IMPORTANT import mechanism: tests do NOT import via package. They do
`sys.path.insert(0, str(PROJECT_ROOT / "tools"))` then `import gamepc_lcu_agent`
(tools/ has no __init__.py). So the bare module name in the `import` statement
must change, AND every path-constant that hardcodes the filename. Per-file:

tools/lcu_agent.py (was gamepc_lcu_agent.py) referencers:
  - tools/gamepc_lcu_agent.py:2,12,13  (own header/deploy lines - rewrite)
  - tests/phase_b_champ_select/test_lcu_agent_phase_b.py:3, 29, 437
  - tests/phase_b_champ_select/test_lcu_mastery.py:3, 23
  - tests/phase_b_champ_select/test_lcu_lobby_members.py:3, 21
  - tests/fu02_team_context/test_lcu_agent_refresh.py:3, 26
  - tests/test_apply_runes_page_filter.py:1, 22
  - tests/test_csv_rune_push_on_selection_change.py:21, 43, 194
  - tests/test_lcu_item_sets_wipe_stale.py:38, 42, 47
  - tests/test_active_match_mock_fixtures.py:145  (comment cite)
  - coaches/loadout_resolver.py:5  (docstring)
  - dashboard/_liveclient.py:7, 49  (docstring)
  - dashboard/routes_static.py:132  (_AGENT_ALLOWED)
  - data/api_surface.csv:11,14,15,16,17,191,192,193,194,195,...  (REGEN)
  - docs/API_SURFACE_AUDIT.md  (PRESERVE-ish doc; update only if swept)
  - tools/gamepc_phase_watcher.py:139  (comment "mirrors gamepc_lcu_agent")
  - tools/gamepc_keybind_listener.py:82  (comment cite)

tools/liveclient_relay.py (was gamepc_liveclient_relay.py) referencers:
  - tools/gamepc_liveclient_relay.py:2,12,13  (own header)
  - dashboard/_liveclient.py:8
  - dashboard/_state_cooldowns.py:5
  - dashboard/routes_static.py:131  (_AGENT_ALLOWED)
  - tools/gamepc_boot.ps1:45, 127  ($AGENT_SCRIPTS, hidden-launch loop)
  - vision_server/_relay.py  (grep hit - verify docstring only)

tools/hotkey_listener.py (was gamepc_hotkey_listener.py) referencers:
  - tools/gamepc_hotkey_listener.py:1,21,22,23,184,209  (own header/logs)
  - dashboard/routes_static.py:133  (_AGENT_ALLOWED)
  - tools/gamepc_boot.ps1:45, 127  ($AGENT_SCRIPTS, hidden-launch loop)

tools/keybind_listener.py (was gamepc_keybind_listener.py) referencers:
  - tools/gamepc_keybind_listener.py:2,26,27,32,82  (own header)
  - NOT in routes_static _AGENT_ALLOWED, NOT in gamepc_boot.ps1 (optional install)
  - schtasks example in its own docstring (line 31-32) -> Legion wording

tools/screen_agent.py (was gamepc_screen_agent.py) referencers:
  - tools/gamepc_screen_agent.py:2,8,10,35,38,42,44  (own header/deploy)
  - modes/shared_vision.py:21,22,48  (comments)
  - dashboard/routes_static.py:131  (_AGENT_ALLOWED - "gamepc_screen_agent.py")
  - tools/gamepc_boot.ps1:45, 97-114  ($AGENT_SCRIPTS, $SCREEN, commented launch)
  - tools/gamepc_mcp_server.py:29  ("same monitor enum as gamepc_screen_agent")
    (mcp_server is SEVERed anyway)
  - tools/gamepc_phase_watcher.py:15,75,331,445(test),514(test),608(test),610(test)
  - vision_server/_frame.py  (grep hit - verify docstring only)

tools/phase_watcher.py (was gamepc_phase_watcher.py) referencers:
  - tools/gamepc_phase_watcher.py:1,4,15,27,28,75,139,331  (own header/comments)
  - tools/gamepc_phase_watcher_install.ps1:1,9,65,66 (-> phase_watcher_install.ps1)
  - tests/test_gamepc_phase_watcher.py:1,17,32,36,38,445,514,608,610
  - tests/test_bare_py_ban.py:60  (allowlist "gamepc_phase_watcher_install.ps1")
  - dashboard/routes_static.py:162,163  (_AGENT_ALLOWED: phase_watcher.py + install.ps1)

Scheduled-task / installer surface (RENAME-REWIRE):
  - tools/gamepc_phase_watcher_install.ps1: WatcherPath=Join-Path InstallDir
    "gamepc_phase_watcher.py" (line 65), Url ".../gamepc_phase_watcher.py" (66).
    Task name RC-PhaseWatcher (line 31) is Legion-neutral - KEEP. Update the two
    filename literals + Game-PC prose (lines 1-25).
  - tools/gamepc_boot.ps1: $AGENT_SCRIPTS array (line 45), $SUPPORT_SCRIPTS (46),
    Start-Process arg paths (108-114 screen commented, 119-123 lcu, 127-133 relay
    +hotkey, 148 mcp). The boot script ALSO launches the (SEVERed) MCP server
    (138-155) + bridge daemon (162-176) - see Section C; once those are removed
    this script shrinks to: refresh + launch lcu_agent/liveclient_relay/
    hotkey_listener. RC-PhaseWatcher install stays separate.

MCP config (RENAME side = none; this is SEVER):
  - .mcp.json gamepc entry -> removed entirely (Section C). No rename needed.

================================================================================
## Section C - SEVER detail
================================================================================

### gamepc MCP - producers, config, consumers
Producer:  tools/gamepc_mcp_server.py (binds :8892 on Game-PC; tools exposed:
           run_powershell, read_file, write_file, list_dir, path_exists,
           capture_monitor, get_system_info). DELETE/ARCHIVE.
Config:    .mcp.json lines 3-10 - the "gamepc" http server entry pointing at
           http://192.168.8.237:8892/mcp with a bearer token. REMOVE.
Boot:      tools/gamepc_boot.ps1:69-75 (firewall rule RC-MCP :8892) +
           138-155 (launch/verify :8892 bind). REMOVE both blocks.
Consumers of mcp__gamepc__* tools (must repoint to Legion-local capture):
  - .claude/commands/game-monitor.md:9 - "Capture monitor 1 on Game-PC via
    mcp__gamepc__capture_monitor (max_width 1280, jpeg q75)". REPOINT.
    Recommended repoint: Legion-local screen capture. Options, in order of
    preference per CLAUDE.md R3 (visual tools are the sanctioned game-monitor
    use): (a) the in-process vision-server frame - GET
    https://127.0.0.1:8889/latest-frame (already the coaches' path,
    modes/shared_vision._capture_screen) and compare bytes; or (b) Legion
    desktop capture via Windows-MCP Screenshot / computer-use screenshot
    (allow_visual.flag path) since League now runs ON Legion. Pick ONE and
    write it into the skill GATE/OTHERWISE block; drop the Game-PC monitor-index
    note. NOTE the skill body is duplicated in CLAUDE's loaded skill text - the
    on-disk .claude/commands/game-monitor.md is the edit target.
  - .claude/commands/gemini-headless-upgrade.md:110 - same mcp__gamepc__
    capture_monitor reference in the UI-audit ritual. REPOINT to Legion capture.
  - .claude/commands/orchestrated-run.md:33, headless-upgrade.md:76,140 -
    "Game-PC :8892" / clean-room sandbox. REMOVE the Game-PC sandbox path
    (Game-PC is out of the pipeline; run/parse on Legion or note as N/A).
  - tools/scheduled_boot_verify.py - probes 192.168.8.237:8892/health implicitly
    via the gamepc bridge target (line 60). DROP the gamepc post-boot leg.
  - tools/rc_facts.py:39 _GAMEPC_MCP_HEALTH "http://gamepc-rc:8892/health",
    :40 _GAMEPC_TOKEN, :207 _gamepc_mcp_anomaly(), :356 MCP probe line. REMOVE.

### game-monitor skill change (explicit)
File: .claude/commands/game-monitor.md
  - DELETE the "Capture monitor 1 on Game-PC via mcp__gamepc__capture_monitor"
    instruction (line 9).
  - REPLACE with a Legion-local capture instruction (recommend GET
    https://127.0.0.1:8889/latest-frame, the same frame coaches read, OR Legion
    Windows-MCP/computer-use screenshot of the League window now running on
    Legion). Keep the rest of the contract (mode_key gate, 3-5 line surface,
    staleness compare, no mid-fight commentary).
  - Remove the Game-PC monitor-index disambiguation note.

### bridge-peer files (Game-PC peer severed; Peer peer STAYS)
Delete/archive (Game-PC-only infra):
  - tools/gamepc_bridge_daemon.py        (TARGET="gamepc" sentinel, line 29)
  - tools/gamepc_mcp_server.py           (:8892 MCP)
  - tools/GAMEPC_CLAUDE.md               (peer CLAUDE.md)
  - tools/start_gamepc_claude.ps1        (launch Claude on Game-PC)
  - tools/done-gamepc.md                 (peer /done)
  - tools/wrap-gamepc.md                 (peer /wrap)
  - tools/verify-rc-rootca-on-gamepc.cmd (peer cert)
  - tools/install-rc-rootca-on-gamepc.cmd(peer cert)
  - tests/test_gamepc_mcp_watchdog.py    (tests the severed server)
De-scope gamepc (keep Peer leg):
  - tools/bridge_dispatch_enable_lanes.py: VALID_TARGETS (line 51) -> ("peer",);
    drop gamepc usage examples (25,27,96).
  - tools/scheduled_boot_verify.py: target="gamepc" -> "legion" or remove (60).
  - tools/verify_bridge_roundtrip.py: drop gamepc roundtrip leg, keep peer.
  - tools/legion_bridge_daemon.py:7 docstring "Mirrors gamepc_bridge_daemon" ->
    drop gamepc sibling mention.
Boot persistence (gamepc_boot.ps1 lines 157-210): RC-BridgeDaemon +
  RC-BridgeWatcher-GamePC + RC-WatcherHealthPublisher-GamePC are Game-PC tasks -
  this whole boot script is Game-PC-side; once Game-PC leaves, the script is
  archived with the peer. (If any of it is reused as a Legion launcher, strip to
  the three relocated agents only.)

### health / dashboard peer rows
  - dashboard/routes_health_peer.py:31 _VALID_NODES={"gamepc","peer"} -> {"peer"}.
    This drops POST /api/health/peer/gamepc + the gamepc index row.
  - dashboard/_bridge_log.py:159-172 gamepc_result_age_s() -> remove, or rename
    to atx_result_age_s() if the dashboard wants the Peer age. Also doc line 15
    target "legion"|"gamepc" -> "legion"|"peer".
  - dashboard/routes_metrics.py:43-46 gauge rc_bridge_gamepc_result_age_seconds +
    :70-71 import/use gamepc_result_age_s -> remove or rename to peer.
  - web/js/main.js:7145-7161 bridge.gamepc_result_age_s -> remove/rename. The
    peers loop (7165-7189) is generic over Object.keys(j.peers) so it auto-prunes
    gamepc once routes_health_peer stops emitting it; no JS change needed there
    beyond the gamepc_result_age_s special-case.
  - ops/runtime/peer_health/gamepc.json (runtime data, if present) - stale after
    sever; harmless, optional cleanup (not in git).

Peer peer STAYS: core/bridge.py (routes to Peer, no gamepc refs - grep clean),
tools/peer_bridge_daemon.py, _VALID_NODES peer, all peer slash commands. Do NOT
touch the Peer leg.

================================================================================
## Section D - Disjoint FILE-SET partition (parallel build agents)
================================================================================

Six non-overlapping slices. Each rename + ALL its referencers live in ONE slice
so no two agents edit the same file. Frozen edits are isolated to slice 6.

SLICE 1 - LCU agent rename (heaviest test fan-out)
  RENAME: tools/gamepc_lcu_agent.py -> tools/lcu_agent.py
  EDIT:   tests/phase_b_champ_select/test_lcu_agent_phase_b.py
          tests/phase_b_champ_select/test_lcu_mastery.py
          tests/phase_b_champ_select/test_lcu_lobby_members.py
          tests/fu02_team_context/test_lcu_agent_refresh.py
          tests/test_apply_runes_page_filter.py
          tests/test_csv_rune_push_on_selection_change.py
          tests/test_lcu_item_sets_wipe_stale.py
          tests/test_active_match_mock_fixtures.py (comment only)
          coaches/loadout_resolver.py (docstring)
          dashboard/_liveclient.py (docstring; lcu+relay both named here -
            COORDINATION: also touched by slice 2. To keep disjoint, assign
            dashboard/_liveclient.py + dashboard/_state_cooldowns.py to SLICE 2
            and have slice 2 update BOTH lcu_agent and liveclient_relay name in
            them. Slice 1 does NOT edit dashboard/_liveclient.py.)

SLICE 2 - relay + screen agent rename + shared dashboard/vision docstrings
  RENAME: tools/gamepc_liveclient_relay.py -> tools/liveclient_relay.py
          tools/gamepc_screen_agent.py      -> tools/screen_agent.py
  EDIT:   dashboard/_liveclient.py (BOTH lcu_agent + liveclient_relay names)
          dashboard/_state_cooldowns.py
          modes/shared_vision.py
          vision_server/_relay.py (verify/docstring)
          vision_server/_frame.py (verify/docstring)
          game_reader/poller.py (Game-PC contention comments)

SLICE 3 - phase watcher + keybind/hotkey listeners rename + installer
  RENAME: tools/gamepc_phase_watcher.py         -> tools/phase_watcher.py
          tools/gamepc_phase_watcher_install.ps1 -> tools/phase_watcher_install.ps1
          tools/gamepc_hotkey_listener.py        -> tools/hotkey_listener.py
          tools/gamepc_keybind_listener.py       -> tools/keybind_listener.py
          tests/test_gamepc_phase_watcher.py     -> tests/test_phase_watcher.py
  EDIT:   tests/test_phase_watcher.py (path consts + spec name)
          tests/test_bare_py_ban.py (allowlist line 60)

SLICE 4 - _AGENT_ALLOWED + boot script (rename-rewire owner of routes_static +
          gamepc_boot.ps1; these reference MANY renamed files so they get their
          own slice to avoid collisions)
  EDIT:   dashboard/routes_static.py (_AGENT_ALLOWED lines 130-164: rename the 5
            gamepc_*.py + phase_watcher + install.ps1 entries; REMOVE the SEVERed
            entries GAMEPC_CLAUDE.md, start_gamepc_claude.ps1, done-gamepc.md,
            gamepc_bridge_daemon.py, gamepc_mcp_server.py)
  RENAME: tools/gamepc_boot.ps1 -> tools/legion_agent_boot.ps1 (strip MCP +
            Game-PC-bridge blocks; update agent filename paths; recast banner)
  NOTE: routes_static.py NOT frozen. This slice depends on slices 1-3 final
        names being agreed (use the rename map in Section B; names are fixed).

SLICE 5 - SEVER bridge peer + gamepc MCP + health/dashboard peer rows
  DELETE/ARCHIVE: tools/gamepc_mcp_server.py, tools/gamepc_bridge_daemon.py,
            tools/GAMEPC_CLAUDE.md, tools/start_gamepc_claude.ps1,
            tools/done-gamepc.md, tools/wrap-gamepc.md,
            tools/verify-rc-rootca-on-gamepc.cmd,
            tools/install-rc-rootca-on-gamepc.cmd,
            tests/test_gamepc_mcp_watchdog.py
  EDIT:   .mcp.json (drop gamepc entry)
          dashboard/routes_health_peer.py (_VALID_NODES -> {"peer"})
          dashboard/_bridge_log.py (drop/rename gamepc_result_age_s)
          dashboard/routes_metrics.py (drop/rename gamepc gauge)
          web/js/main.js (drop gamepc_result_age_s special-case)
          tools/rc_facts.py (remove Game-PC section + consts)
          tools/scheduled_boot_verify.py (target gamepc -> legion)
          tools/bridge_dispatch_enable_lanes.py (VALID_TARGETS -> peer)
          tools/verify_bridge_roundtrip.py (drop gamepc leg)
          tools/legion_bridge_daemon.py (docstring)
          ops/install_RC_LegionBridgeDaemon.ps1 (docstring)
          .claude/commands/game-monitor.md (repoint capture to Legion-local)
          .claude/commands/gemini-headless-upgrade.md (repoint capture)
          .claude/commands/orchestrated-run.md (drop :8892 note)
          .claude/commands/headless-upgrade.md (drop Game-PC sandbox)
          .claude/commands/done.md (drop gamepc bridge probe)
          .claude/commands/process-bridge-tasks.md (peer-only reply-to)
          .claude/commands/process-bridge-tasks-peer.md (xref)
          .claude/commands/weekly-hygiene.md (update retired-infra expectation)
          tools/chrome-import-rc-rootca.txt (recast/archive)

SLICE 6 - living docs + FROZEN-PURGE (isolated: only slice touching frozen files
          and the big living docs; avoids any code-file collision)
  EDIT:   CLAUDE.md (Topology table, frozen-file list paths after rename,
            vision-pipeline prose, Game-PC lines; mind <60KB budget)
          docs/ARCHITECTURE.md, docs/OPERATIONS.md, docs/BRIDGE.md,
          docs/API.md, docs/AGENTS.md, ROADMAP.md, BACKLOG.md,
          docs/RC2_PLAN.md, rc-shell/README.md,
          docs/adr/ADR-011-one-pc-consolidation.md (mark Phase-11 done),
          docs/adr/ADR-005-tailscale-magicdns.md,
          docs/adr/ADR-007-event-coach-pivot.md
          FROZEN: tools/process-bridge-tasks.md, tools/diagnose.md,
            tools/caveman.md (scan + Legion-only; LIST as frozen edits)
          .gitignore (comment-only)

SLICE 7 (serial, AFTER slices 1-2 merge) - REGEN
  data/api_surface.csv: regenerate with the api-surface generator so it cites
  tools/lcu_agent.py. Do NOT hand-edit. (Depends on slice 1 rename landing.)

Collision audit: routes_static.py only in slice 4; gamepc_boot.ps1 only in
slice 4; dashboard/_liveclient.py only in slice 2; rc_facts.py only in slice 5;
CLAUDE.md only in slice 6; api_surface.csv only in slice 7. No file appears in
two slices. The only cross-slice ORDERING constraint: slice 4 + slice 7 depend
on the agreed rename map (fixed in Section B) and on slices 1-3 having renamed
the files; run slices 1-3 first (or in parallel with the map frozen), then 4-6,
then 7.

================================================================================
## Section E - Verification plan
================================================================================

py_compile targets (after rename; run with the Python314 interpreter):
  tools/lcu_agent.py tools/liveclient_relay.py tools/hotkey_listener.py
  tools/keybind_listener.py tools/screen_agent.py tools/phase_watcher.py
  dashboard/routes_static.py dashboard/routes_health_peer.py
  dashboard/_bridge_log.py dashboard/routes_metrics.py dashboard/_liveclient.py
  dashboard/_state_cooldowns.py game_reader/poller.py modes/shared_vision.py
  coaches/loadout_resolver.py tools/rc_facts.py tools/scheduled_boot_verify.py
  tools/bridge_dispatch_enable_lanes.py tools/verify_bridge_roundtrip.py
  tools/legion_bridge_daemon.py

Targeted test runs (Tier-1 per renamed module - run ONLY these, not full suite,
since this is a rename/doc purge not an engine change):
  tests/phase_b_champ_select/   (lcu_agent import path)
  tests/fu02_team_context/test_lcu_agent_refresh.py
  tests/test_apply_runes_page_filter.py
  tests/test_csv_rune_push_on_selection_change.py
  tests/test_lcu_item_sets_wipe_stale.py
  tests/test_phase_watcher.py   (renamed)
  tests/test_bare_py_ban.py     (bare-py allowlist drift)
  tests/test_active_match_mock_fixtures.py
  Confirm tests/test_gamepc_mcp_watchdog.py is DELETED (no orphan import of
  tools.gamepc_mcp_server remains -> grep must return zero).
  Run dashboard route tests touching health peer + metrics if present
  (grep tests for routes_health_peer / routes_metrics).

ds_share_sync: NOT required - no agents/daemon_slayer/** file edited, no
DS-mirrored tools/ file renamed. (Verify with: grep agents/daemon_slayer for
gamepc = zero, already confirmed this pass.) If a slice unexpectedly edits a
mirrored tools/ file, run tools/ds_share_sync.py --check before push.

Scheduled tasks to re-register (LIVE, on Legion - not checked-in XML):
  RC-LCUAgent, RC-LiveClientRelay, RC-HotkeyListener point at the OLD
  C:\RC-Agent\gamepc_*.py paths (or wherever the relocated copies live). After
  rename, the live task TR= command-line still references the old filename ->
  update each task's action path to the new filename. Task NAMES stay. Use
  schtasks /Query /TN <name> /XML to read current TR, then re-register with the
  new path. RC-PhaseWatcher likewise if active. (These are runtime registrations;
  no repo file changes them - flag for the operator to re-run the install step.)

game-monitor smoke: with a live game (mode_key in {sr,arena,aram,tft,brawl} and
liveclient non-null), invoke the game-monitor skill and confirm it captures via
the new Legion-local path (GET :8889/latest-frame or Legion screenshot) and
surfaces the 3-5 line tick WITHOUT calling mcp__gamepc__capture_monitor. If no
live game, confirm the gate emits zero text (no gamepc tool call).

Bridge sanity: curl -k https://127.0.0.1:8888/api/health/all -> peers block
should list peer only (no gamepc key). /metrics should not expose
rc_bridge_gamepc_result_age_seconds (or it is renamed to peer).

Restart: dashboard route + JS edits (routes_static asset hash, main.js) auto-
reload per ADR-008 for asset-only; routes_*.py changes need an RC restart
(echo restart > restart_trigger.txt) then verify ops/runtime/health.json new pid
+ alive + last_reload_ok. DS server NOT affected.

================================================================================
## Section F - Risks / blockers / unclassifiable
================================================================================

R1 (HIGH) - Live scheduled tasks are the real rewire, not repo XML. There is NO
  ops/*.xml for RC-LCUAgent/RC-LiveClientRelay/RC-HotkeyListener (Glob confirms
  only 5 unrelated XMLs). The task action paths live in Task Scheduler, pointing
  at C:\RC-Agent\gamepc_*.py. Renaming the repo file does NOT update the live
  task. The operator must re-register (or re-run the install/boot step) so the
  tasks launch the new filenames. Until then the OLD-named copy in C:\RC-Agent\
  must remain, or the relocated agents stop launching at logon. RECOMMEND: keep
  old C:\RC-Agent\ copies until tasks are re-pointed, OR have the boot script
  copy new->old name. This is a runtime/ops step OUTSIDE the repo edit.

R2 (MED) - gamepc_boot.ps1 is multi-purpose: it is BOTH the renamed-agent
  launcher AND the Game-PC bridge/MCP installer AND the Claude-Desktop opener.
  It is fundamentally a Game-PC-side script (self-elevates, installs RC-MCP
  firewall, RC-BridgeDaemon, hardens RC-BridgeWatcher-GamePC). Deciding its fate
  (archive whole vs strip to a Legion launcher) is an operator call. SPEC default:
  SEVER the MCP + bridge-daemon + Claude-Desktop blocks; if nothing Legion-side
  needs a logon launcher for the 3 relocated agents (they have their own
  RC-* tasks), archive the whole script. Flagged, not auto-decided.

R3 (MED) - game-monitor repoint target is a design choice. :8889/latest-frame is
  the lowest-friction (text-path, no visual tool) but only yields the vision
  frame, not arbitrary monitors. Legion Windows-MCP/computer-use screenshot is
  the richer but heavier option (needs allow_visual.flag). SPEC recommends
  :8889/latest-frame as primary with Legion screenshot as the escalation; final
  pick is operator/Gemini-director's.

R4 (LOW) - data/api_surface.csv regen depends on the api-surface generator
  existing + runnable. Locate the generator (grep for api_surface writer) before
  slice 7; if absent, the CSV stale-path is cosmetic (it is a generated audit
  artifact) and can be left with a FLAG rather than blocking the purge.

R5 (LOW) - _bridge_log.gamepc_result_age_s() removal vs rename. If the dashboard
  bridge-health dot should still show the Peer peer age, rename to
  atx_result_age_s() + update routes_metrics + main.js consistently. If the dot
  is fine showing only the rollup, delete. Operator preference; SPEC leaves both
  paths documented. main.js peers loop self-prunes either way.

R6 (LOW) - CLAUDE.md <60KB CI budget. The DOC-PURGE shrinks more than it adds
  (removing Game-PC topology row, gamepc paths from frozen list), so budget risk
  is low, but verify size after edit.

R7 (INFO) - docs/API_SURFACE_AUDIT.md + ops/audit/** + agent6 reports cite old
  gamepc paths but are DATED ARTIFACTS (PRESERVE). Do not edit. Their stale
  paths are historically correct.

Unclassifiable hits (none blocking):
  - web/data/ui_mock/active_match_arena.json "game-pc-league" channel string:
    cosmetic mock fixture; update or leave (FALSE-POSITIVE-ish).
  - ops/tls/_bridge_msg.txt: a one-off bridge message artifact (PRESERVE).
  - docs/research/RC2_*.md, docs/RC2_*_QA.md, docs/RC2_TODO_QA.md: RC2 research
    notes referencing 2-PC history; recast only if a docs sweep wants them,
    otherwise leave as research record.

End of SPEC.
