# Next session plan - 2026-05-11 (post-s169 wipe)

Carries forward from s169 (ADR-007 phase 1 + migration discussion + keybind
deploy). Operator wiping session to free token budget.

## What's already shipped + LIVE - operator can League immediately

| Surface | State |
|---|---|
| `core/decision_detector.py` | 6 detectors registered. Tightened low-HP + new jungler-gank + throwing-lead live. |
| `data/decisions_heartbeat.json` | Phase 3 supervisor (PID 11712) writes on each eval. Endpoint at `GET /api/decisions/heartbeat` returns live counter. |
| Dashboard `#trigger-pill` | In header row 2, polls 2 Hz, green/amber/grey. Hidden in client/tft modes. |
| Banner `#coach-decisions` | Pre-existing UI shows pending decision; A/B buttons click-to-resolve. |
| Game-PC keybind listener | **PID 5944 alive** at `C:\RC-Agent\gamepc_keybind_listener.py`. Left Alt + 1 = A · Left Alt + 2 = B · Left Alt + 3 = dismiss. Log at `C:\RC-Agent\keybind_listener.err.log`. **Not autostarted on reboot - manual restart if Game-PC reboots before scheduled-task is set up.** |
| RC main | Restarted via `restart_trigger.txt` after `routes_diag.py` route additions. Endpoint live. |
| Phase 3 supervisor | Restarted (taskkill + schtasks); picked up new detectors + FU01 minimap-locate. |
| Git | `83c4f0f` pushed to origin/main. Working tree clean. |
| Test suite | 719/719 green. |

**Operator can open League right now.** Decision_detector will eval on
each game-state poll (~1 Hz). When a detector fires, the banner appears
mid-dashboard with A/B buttons. Left Alt + 1/2/3 keybinds also work in-game.

## Immediate next-session priorities (in order)

### P1 - Claude Desktop 5-min live test on Legion (DEFERRED FROM s169)

Operator wants to swap `claude-rc.ps1` (Legion desktop shortcut) AND
`start_gamepc_claude.ps1` (Game-PC bridge launcher) from launching the
**Claude CLI in WT** to launching **Claude Code hosted in Claude
Desktop**. Both files currently invoke `claude --name "X" --dangerously-skip-permissions`
inside a helper `.cmd`. Both Anthropic Claude Desktop installations are
already present:

- Legion: Microsoft Store Appx `Claude_pzs8sxrjxfjjc` (`shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude` to launch)
- Game-PC: `C:\Users\Administrator\AppData\Local\AnthropicClaude\Claude.exe`

**Test steps**:
1. From Legion, manually launch Claude Desktop with the RC workspace
   (`C:\Riot Commander`). Try `Claude.exe "C:\Riot Commander"` first,
   then `claude://workspace/C:/Riot%20Commander` URI scheme if the
   direct arg doesn't take.
2. Inside the desktop app, verify:
   - Slash commands work (`/help`)
   - The Claude Code engine is active (not just chat)
   - SessionStart hooks fire (the `rc_facts.py` SessionStart hook should
     dump the RC live-state summary on session open)
   - File reads/edits work via the desktop UI
3. **If clean**: rewrite both launchers. Schema: spawn Claude.exe with
   workspace path arg, idempotency check via `Get-Process Claude` +
   window-title match. Drop `--name "X"` and `--dangerously-skip-permissions`
   (CLI-only flags; Desktop has its own permission UI which gets approved
   once).
4. **If desktop refuses workspace arg**: belt-and-suspenders - Desktop
   primary for interactive (operator manually opens workspace), CLI
   stays hidden as bridge-daemon companion. (Bridge automation already
   uses headless `claude --print /process-bridge-tasks` - that code path
   is unaffected regardless.)
5. Update `gamepc_boot.ps1` AGENTS array: swap the `gamepc_hotkey_listener.py`
   entry for `gamepc_keybind_listener.py`. Add `gamepc_keybind_listener.py`
   to Legion's `/agent/` allowlist (likely in `dashboard/_static.py` or
   wherever the boot-script-served files are gated).

The 5-min test is gating - don't rewrite launchers until the live test
proves Desktop hosts Claude Code as expected.

### P2 - `/unalive` + `/pre-flight` Phase A (Legion-local)

Per s169 discussion: operator wants two new slash commands.

- **`/unalive`** - kill all RC/Agent processes (whitelist), log the
  full state before kill including any unexpected processes/listeners,
  restart minimums (supervisor + bridge daemon). Cross-machine via bridge
  task is Phase B (later).
- **`/pre-flight`** - validate everything post-restart. Port bindings,
  HTTP probes, scheduled-task state, cache-buster freshness, ENGINE_VERSION
  ↔ DS server, decisions_heartbeat freshness in-game, git status,
  disk space, tailnet reachability. Color-coded TUI matching
  `gamepc_boot.ps1` pattern; auto-close after 10s on all-green.

Phase A scope: Legion-local `tools/unalive.ps1` + `tools/preflight.ps1`
+ corresponding `.claude/commands/unalive.md` + `.claude/commands/preflight.md`
skill specs. Manual invocation. No cross-machine bridge yet.

Phase B (later session): cross-machine fan-out.
Phase C (later session): autorun via SessionStart hook + ONLOGON
scheduled task with the soft-delay push/pull the operator described.

### P3 - Schedule the Game-PC keybind listener

If P1's live test is clean and the boot script gets updated to include
`gamepc_keybind_listener.py`, then `gamepc_boot.ps1` will restart it on
next Game-PC reboot. Until then, the listener (PID 5944) dies on reboot.

Add `RC-KeybindListener` scheduled task on Game-PC (ONLOGON, hidden,
runs the absolute python path per the s168 `RC-LCU` lesson - don't use
`Execute: py` which fails ERROR_FILE_NOT_FOUND under scheduled-task
context).

## Deferred (not blocking)

| Item | Why deferred |
|---|---|
| ADR-007 phase 2 (postmortem pipeline) | Data-rich; needs design pass. `scripts/postmortem_analyze.py` mining rewind_history.db for death patterns → `data/coaching/death_patterns.json` → coach prompts |
| ADR-007 phase 3 (prose-coach deprecation) | Wait for phase-1 detectors to prove out in real games first |
| Phase 3 UI steps 5-14 | UI work, paused per s166 operator directive |
| RC-LCU task `Execute: py` fix | Cosmetic; manual relaunch works |
| Legion migration | Decided (Option B); execute when 27" monitor desk is set up. **All migration prep at `C:\Users\Administrator\Desktop\Legion-Migration-Plan\` (outside repo).** Don't lose track of this - it's the folder with the discussion summary + install checklist + spoof analysis + hwid_audit artifacts. |

## Important context for next-session-you (read before acting)

1. **`/clear` between sessions is operator policy** - every focused task
   is one session. WAKEUP_NOTES + CLAUDE.md + MEMORY.md cover the
   carry-over.
2. **The legion-migration-plan folder is OUTSIDE the repo** - don't try
   to grep it from `C:\Riot Commander\`. It's at
   `C:\Users\Administrator\Desktop\Legion-Migration-Plan\`. Mentioned
   here so you know it exists.
3. **Phase 3 supervisor restart is sticky** - PID 11712 picked up the
   new detectors. Don't restart it unless code in `agents/supervisor.py`
   or `core/decision_detector.py` changes.
4. **Decision_detector heartbeat file** at `data/decisions_heartbeat.json`
   is gitignored (catchall under `data/`). Confirms detector loop alive
   ONLY when in-game; pre-game it stays at counter 0.
5. **Operator's keyboard**: tenkeyless. Numpad NOT available. All keybind
   defaults must use number row + modifiers. Left Alt + 1/2/3 is the
   accepted pattern (Ctrl+1/2/3 collides with League's item-cast).
6. **Operator pushed for the 27" gaming setup soon** - "next few days".
   Legion migration is an upcoming major event. Don't make architectural
   choices that assume 2-PC forever.

## Bootstrap on session open

After /clear, recommended boot:
1. Read CLAUDE.md (already happens via auto-load)
2. Read MEMORY.md (already auto-loaded via the auto-memory system)
3. Read WAKEUP_NOTES.md (last 3 sessions: s167, s168, s169)
4. Read THIS file (`NEXT_SESSION_PLAN_2026-05-11.md`)
5. `git log --oneline -5` to confirm working tree state
6. Greet operator with "where do you want to start: P1 Claude Desktop test, P2 unalive/pre-flight Phase A, or something else?"
