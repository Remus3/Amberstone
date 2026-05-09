# Riot Commander — Roadmap

_Now + Next only. Full history in `docs/_archive/CHANGELOG.md`. Aspirational in `BACKLOG.md`._

---

## Open items — High priority

- ✅ **TFT 17.3 patch** — shipped 0e9617b (2026-05-08). Morgana 4g, Anima/Stargazer reworks, Primordian AVOID, AP comps buffed.
- **rewind_history.db staleness** — blocked on live SR game (last entry Dec 2025; needs game_id wired to new session records).
- **Vision regions calibration** — tune `data/vision_regions.json` bboxes. Blocked on live game for calibration frame.
- **Bridge Watcher acceptance-criteria** — need 50+ real-traffic auto-action samples (currently synthetic only). Watch `auto_ok_since_boot` vs `auto_err_since_boot` on RC heartbeat.
- **gamepc_boot.ps1 hardening** — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence; currently missing (must be `Start-ScheduledTask`'d manually after socket exhaustion events).

## Open items — Medium priority

- **Auto-ops verb expansion** — once Phase 3 auto-action success rate clears 95%, add: `tail .* log`, `restart agent .*`, `verify .*` to Legion `auto_ops_verbs`.
- **Game-PC + Peer auto-action lanes** — watchers installed but `--enable-auto-action-lanes` is OFF. Enable when success rate is proven.
- **RC-DaemonSlayer task context** — runs as SYSTEM; `_log_startup` writes silently fail. Change to LogonTrigger + Administrator context if traceability matters after next boot.

## Future-Proofing Plan (separate doc)

Phased refactor plan (doc architecture → god module decomp → frontend ESM → schemas → CI):
`C:\Users\Administrator\Desktop\RC_FUTUREPROOFING_PLAN.md`

| Phase | Status |
|---|---|
| 1 — Knowledge architecture | ✅ Done (fc1361b — s125+s126) |
| 2.1 — champion_profiles split | ✅ Done (s127 — 902→29 LOC + 168 JSONs) |
| 5 — CI + smoke harness | ✅ Done (d21f533 — 343→380 tests, ruff 0 violations, CI gate live) |
| 4 — Contracts/schemas | 🟠 In progress (s129 — 4.1+4.2+4.3 partial) |
| 3 — Frontend modules | ✅ Done (s137 — 3.1+3.2+3.3; 6-fixture Playwright snapshots, WS-stub isolation) |
| 2.3 — coach_integration split | ✅ Done (s138 — 1225 LOC → _profiles/\_sr\_prompt/\_coach pkg, 386 tests) |
| 6 — Bridge consolidation | 🔴 Blocked (frozen-file approval needed) |
| 2.2 — game_reader split | ✅ Done (ea7589e — s139, 1474 LOC → mixin pkg, 386 tests) |
| 2.4 — vision server split | ✅ Done (9cf262a — s140, 710 LOC → shim + vision_server/ pkg, 386 tests) |
| 7 — Process polish | ✅ Done (s141 48d11be + s142, phase-marker normalization + archmap journal + WAKEUP_NOTES auto-prune + Conventional Commits commit-msg hook, 412 tests) |

---

## Fleet status at a glance

| Layer | State |
|---|---|
| RC supervisor + main | Stable (pid=1108 at last check) |
| Web dashboard `:8888` | All endpoints green |
| Vision relay `:8889` | Stale-frame rejection live; auth via rotated token |
| MCP server `:8892` (Game-PC) | HTTP 200 |
| Bridge Watcher (Legion) | pid=15004 cadence=active; 24h ring live |
| Game-PC bridge daemon | watcher=alive queue=0 |
| Peer bridge daemon | watcher=alive queue=0 |
| Coaches | All 4 modes DS-before-Haiku ✅ |
| Daemon Slayer `:8893` | ENGINE 0.60.0 · 547 items · 911 tests |
| TFT | Set 17 patch 17.3 live (0e9617b) |

---

## Cross-cutting principles (never violate)

- **Frozen files** — see CLAUDE.md. Explicit operator sign-off required for any change.
- **Atomic writes only** — `tmp.write_text(...); tmp.replace(target)`. Overlays + dashboard poll mid-write.
- **`py_compile` before restart** — syntax errors crash silently under `pythonw.exe`.
- **Restart via `restart_trigger.txt`** — never `Stop-Process`; `taskkill /F /PID` for hard kills.
- **Coach prompt edits require RC restart** — batch edits, restart once.
- **Don't break the cross-Claude bridge** — `vision_token` + `mcp_token` are SEPARATE; never let one resolver fall back to the other's file.
