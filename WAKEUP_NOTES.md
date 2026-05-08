# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s118 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

# s119 wrap — 2026-05-08 (Roadmap — 5 items shipped)

## What shipped
- **Phase 4 SessionStart enrichment** (`tools/rc_facts.py`, d069e4d): `_watcher_summary()` adds bridge watcher pid/cadence/queue/auto_ok/err/suppressed (since boot) + esc_24h as a Legion section line. Bridge section gains 24h activity counts (tasks/results/notes). `267014` added to allow-list → RC-VisionServer no longer fires as false anomaly.
- **DS startup diagnostics** (`tools/start_daemon_slayer.py`, 04e63d4): wraps `serve_forever()` in try-except; appends timestamped entries to `logs/daemon_slayer_startup.log` on port-skip, startup, and failure. Next task failure will be diagnosable.
- **SR coach objective_window fix** (`coach_integration.py`, e8d976b): `_state_signature` now has a fallback for `objective_window=None` → reads `objective_timers` dict, emits 1 when dragon/baron < 90s. All 5 non-obvious key mismatches are now fixed. 53 coach tests pass.
- **Bridge introspection** (`dashboard/_bridge_log.py` + `routes_bridge.py`, 5a790d2): `bridge_since()` gains `source` kwarg; `/api/bridge` route adds `?source=<node>&hours=N` params. Example: `?source=gamepc&kind=result&hours=24` → 20 entries. Default limit 20→100.
- **ROADMAP closures**: items_index auto-rotation (already in `cmd_all()`), vision_token rotation policy (documented, next rotation ~2026-08-01).

## Do NOT redo
- RC-VisionServer `result=267014` is now in the allow-list. It's no longer an anomaly.
- RC-DaemonSlayer `result=1` (from May 5) — server IS running via a manual start on May 6. Not a functional problem; diagnostic logging will capture the next failure.
- `coach_integration.py` is NOT frozen (memory was wrong). The objective_window fix was safe to make directly.

## Open work (priority order)
1. **rewind_history.db staleness** — blocked on live SR game.
2. **Vision regions calibration** — blocked on live game.
3. **TFT 17.3** — due ~2026-05-12. Same process as 17.2.
4. **Bridge Watcher acceptance-criteria** — need 50+ auto-action samples; currently 0.
5. **Auto-ops verb expansion** — after 95% success rate.
6. **RC dev mode toggle** — next unblocked Future item: dev panel with fixture switcher, force-vision, log tail.
7. **Investigate RC-DaemonSlayer exit 1** — check `logs/daemon_slayer_startup.log` after next reboot.

---

