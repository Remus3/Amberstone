# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s120 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s123 wrap — 2026-05-08 (rc_facts bridge probe + DS exit 1 investigation)

## What shipped
- **rc_facts.py bridge probe rewrite** (commit 04a305b): replaced stale `bridge_log.jsonl` age-based anomaly ("auto-flow loop may be dead") with `/api/health/all` peer probe. Now shows `gamepc bridge daemon: watcher=alive queue=0 age=Xs` and `peer bridge daemon: ...` — fires real anomaly only if `watcher_alive=false`, peer stale, or queue > 10.
- **DS server health line** added to Legion section in rc_facts: `DS server :8893: ok patch=16.9.1 alive=True`.
- **RC-DaemonSlayer false anomaly suppressed**: result=1 is silenced in the task list when `daemon_slayer.alive=True` from health/all (the server IS running; the task's stale exit code was a red herring).

## Findings (no code change needed)
- **Bridge auto-flow `/loop` is obsolete**: `RC-BridgeDaemon` + `RC-BridgeWatcher-GamePC` on Game-PC handle it as scheduled tasks. Confirmed both Running. Memory `reference_bridge_autoflow.md` was already accurate.
- **RC-DaemonSlayer exit 1 root cause**: DS server alive and healthy (PID 19268 pythonw.exe, `/health` returns OK). The exit 1 on 5/5 was a one-off manual `schtasks /Run` that failed — task runs as SYSTEM which silently can't write to `logs/` (`_log_startup` swallows the OSError). BootTrigger run at 5/1 boot started the server successfully and it's been running ever since.

## Do NOT redo
- Don't re-investigate the bridge auto-flow loop — it's daemon-managed, not `/loop`-managed. The old `/loop` is dead and gone.
- Don't re-investigate DS exit 1 as a live failure — it's resolved (false alarm). If DS ever goes down, rc_facts will flag it via the `DS server :8893:` line, not the task result.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12 (4 days). Same process as 17.2.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **gamepc_boot.ps1 hardening** — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence.
7. **RC-DaemonSlayer task context** — runs as SYSTEM; `_log_startup` writes silently fail. Low-risk (server alive), but consider changing to LogonTrigger + Administrator context if traceability matters after next boot.

---

# s122 wrap — 2026-05-08 (Game-PC socket recovery + TDD skill)

## What shipped
- **Game-PC socket exhaustion diagnosed & fixed**: STATUP.GG (Overlay Platform M overlay) leaked 17,463 kernel handles, exhausting the socket buffer pool (`WSAENOBUFS`). All Game-PC outbound TCP was silently broken — agents were running but unable to POST to Legion. Fixed with `taskkill /F /PID 3340`. Diagnostic: `Get-Process | Sort-Object HandleCount -Descending`.
- **Game-PC watcher tasks restarted**: `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` were in `Ready` (stopped) state after 2h of socket failures. Started via `Start-ScheduledTask`. Legion peer health restored: `age_s=27.7, stale=False`.
- **TDD skill installed**: `test-driven-development.md` → `.claude/commands/` (from addyosmani/agent-skills). Red-Green-Refactor cycle + Prove-It bug pattern + test pyramid. Auto-invokes on code changes. Python examples adapted for RC.

## Do NOT redo
- STATUP.GG socket exhaustion is transient — Overlay Platform M relaunches with League. If Game-PC goes stale again, always check handle counts first before investigating network/firewall.
- `gamepc_boot.ps1` does NOT restart `RC-WatcherHealthPublisher-GamePC` or `RC-BridgeWatcher-GamePC` — they need `Start-ScheduledTask` if they stop. This is a known gap.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **Investigate RC-DaemonSlayer exit 1** — check `logs/daemon_slayer_startup.log`.
7. **gamepc_boot.ps1 hardening** — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence.

---

# s121 wrap — 2026-05-08 (token cost reduction)

## What shipped
- **Fleet model downgrade**: all 3 machines switched from `sonnet[1m]` → `claude-sonnet-4-6` standard 200k via `/config`. Legion=default effort (removed `effortLevel: "high"`), Game-PC=medium, Peer=default.
- **Legion plugin cull** (`~/.claude/settings.json`): disabled 5 unused plugins — `nimble`, `ralph-loop`, `playwright`, `chrome-devtools-mcp`, `firecrawl`. Kept `github` + `pyright-lsp`. Saves ~15-20k tokens of skill descriptions per turn.
- **MEMORY.md pruned**: removed 6 stale FIXED/RESOLVED entries (dashboard queue, rune shard3, game_ingest dups, arena augments, SR coach hash bug, SR RECOMMENDED panel).
- **Peer applied same changes** via bridge task (confirmed via hook): disabled playwright, ralph-loop, chrome-devtools-mcp, firecrawl; model already sonnet; no stale memories.
- **Game-PC**: no `enabledPlugins` section — already clean; already on sonnet/medium.
- **Cost diagnosis**: Opus usage in billing = `advisor()` calls only (both machines on Sonnet already). Primary levers: plugin cull (done), shorter sessions, advisor() discipline.

## Do NOT redo
- Game-PC has no plugins installed — no `enabledPlugins` key needed. Don't add one.
- Peer already confirmed their changes — don't re-dispatch the plugin cull task.
- The Opus in usage dashboard is advisor() tool calls, NOT a model misconfiguration.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **Investigate RC-DaemonSlayer exit 1** — check `logs/daemon_slayer_startup.log`.

---


