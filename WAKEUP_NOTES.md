# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s119 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

# s120 wrap — 2026-05-08 (RC dev panel shipped)

## What shipped
- **RC dev panel** (`dashboard/routes_dev.py`, `web/index.html`, `web/js/dashboard.js`, `web/css/dashboard.css`, commit 7424e24): `⚙ Dev / Sim Preview` nav item now opens a proper `#view-dev` view with three cards: SIM FIXTURES (26 fixtures, color-coded mode tags, Per-fixture Preview links, Exit Sim link when in sim mode), VISION STATUS (new `GET /api/dev/vision-status` backend proxying `:8889/health` + `/latest-frame/meta` via `X-RC-Token`), RC LOG TAIL (last 60 lines from `/api/logs?n=60`, auto-scrolls to bottom). CSS view-switching rules wired for `data-view="dev"`. Previously the menu item did a URL redirect to `?sim=default`; now it navigates to `#dev` view without reloading.

## Do NOT redo
- The dev panel CSS required two separate edits to dashboard.css (main-hide rule + section-show rule). Both are in place. Don't add a third.
- Vision status uses `X-RC-Token` header (not `Authorization: Bearer`) — that's how `:8889` authenticates.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12. Same process as 17.2.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **Investigate RC-DaemonSlayer exit 1** — check `logs/daemon_slayer_startup.log` after next reboot/restart of the DS task.

---


