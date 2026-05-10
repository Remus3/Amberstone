# Riot Commander — Roadmap

_Now + Next only. Full history in `docs/_archive/CHANGELOG.md`. Aspirational in `BACKLOG.md`._

---

## Open items — High priority

- ✅ **TFT 17.3 patch** — shipped 0e9617b (2026-05-08). Morgana 4g, Anima/Stargazer reworks, Primordian AVOID, AP comps buffed.
- ✅ **Riot API key policy reversal** — ADR-006 shipped (s145, 2026-05-09). Personal-tier key permitted for full-team champ-select context + post-game review. Live in-game advisory stays LCU/LiveClient-only per Riot ToS. Implementation tickets: FU02 + FU04 (next).
- ✅ **FU04 — Riot Personal-tier API key application** — submitted + approved same-day on 2026-05-09 (App ID 834837, well inside the documented 2–6 week window). f1c8b10. Bundle preserved at `Desktop/FU04-Application-Evidence/`; key staged in `API-Key-Riot.txt` (gitignored on Legion only).
- ✅ **FU02 — `core/riot_api.py` + champ-select team-context fan-out** — shipped s148 (`dfa13f0`). Personal-tier key resolver, dual token bucket (20/s + 100/120s + 429 cooldown), SQLite cache (immutable + 5-min TTL), six endpoint wrappers (Account-V1, Match-V5 ids/detail/timeline, League-V4, Mastery-V4), priority-1/priority-2 fan-out via daemon thread with swappable dispatcher, progressive reveal, backend ranked-name-blanking. `/metrics` exposes `rc_riot_api_calls_total{endpoint,outcome}`. 63 new tests, 565 total. **Last mile remaining:** Game-PC `tools/gamepc_lcu_agent.py` doesn't yet POST to `/api/team-context/refresh` on `ChampSelect` transition — manual roster posts work; LCU agent extension is independent.
- **FU01 — minimap-locate** — 3-path resolver (override → PersistedSettings → hardcoded). Independent. `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- ✅ **LCU agent → team-context refresh wiring** — shipped s149 (`e7b5af1`). Game-PC `tools/gamepc_lcu_agent.py` POSTs roster (with PUUIDs) to `https://192.168.8.230:8888/api/team-context/refresh` on ChampSelect entry + on lock/swap. Bridge-secret resolver (env → `bridge_secret.txt` → `local_paths.json`); LCU champion-id→name cache; edge-trigger w/ 3s repost rate-limit. 30 new tests, 595 total. Game-PC deployed live (RC-LCU PID 16080); resolver self-test confirmed. Live verification awaits next CS pop.
- ✅ **DS surfacing — header pill + ARAM Build-row fallback + match-record wire** — shipped s152 (`091d18c`). Glanceable `#ds-pill` in header row 2 (info-blue, ◆ glyph, mode-gated), Next panel ARAM/Brawl `Build` row falls back to `DS: <name> +Ndps` when coach hasn't emitted `item_extra`/`objective` (coach copy still wins), and `performance_tracker.save_rating` folds the engine's last DS pick set into `matches.raw_data["daemon_slayer_picks"]` so calibration analysis loses the JSONL ⨝ on (champion, mode, ~ts). 8 new tests, 624 total. Smoketested live: pill rendering `Stormrazor +54dps` from real coach state.
- 🚫 **FU03 — clipboard helper** — permanently superseded by FU04 same-day approval (Personal keys don't expire; daily-renewal helper unnecessary).
- **rewind_history.db staleness** — blocked on live SR game (last entry Dec 2025; needs game_id wired to new session records).
- **Vision regions calibration** — tune `data/vision_regions.json` bboxes. Blocked on live game for calibration frame.
- **Bridge Watcher acceptance-criteria** — need 50+ real-traffic auto-action samples (currently synthetic only). Watch `auto_ok_since_boot` vs `auto_err_since_boot` on RC heartbeat.
- **gamepc_boot.ps1 hardening** — add `RC-WatcherHealthPublisher-GamePC` + `RC-BridgeWatcher-GamePC` to idempotent start sequence; currently missing (must be `Start-ScheduledTask`'d manually after socket exhaustion events).

## Open items — Medium priority

- **Auto-ops verb expansion** — once Phase 3 auto-action success rate clears 95%, add: `tail .* log`, `restart agent .*`, `verify .*` to Legion `auto_ops_verbs`.
- **Game-PC + Peer auto-action lanes** — watchers installed but `--enable-auto-action-lanes` is OFF. Enable when success rate is proven.
- **RC-DaemonSlayer task context** — runs as SYSTEM; `_log_startup` writes silently fail. Change to LogonTrigger + Administrator context if traceability matters after next boot.

## Future-Proofing Plan (retired 2026-05-09 — all 7 phases ✅)

Retired to `docs/_archive/RC_FUTUREPROOFING_PLAN_retired_2026-05-09.md` after all phases shipped.

| Phase | Status |
|---|---|
| 1 — Knowledge architecture | ✅ Done (fc1361b — s125+s126) |
| 2.1 — champion_profiles split | ✅ Done (s127 — 902→29 LOC + 168 JSONs) |
| 5 — CI + smoke harness | ✅ Done (d21f533 — 343→380 tests, ruff 0 violations, CI gate live) |
| 4 — Contracts/schemas | ✅ Done (791e2db — s143 dispatch soft-warn validator + 26 tests; closes s129 4.1+4.3 partial) |
| 3 — Frontend modules | ✅ Done (s137 — 3.1+3.2+3.3; 6-fixture Playwright snapshots, WS-stub isolation) |
| 2.3 — coach_integration split | ✅ Done (s138 — 1225 LOC → _profiles/\_sr\_prompt/\_coach pkg, 386 tests) |
| 6 — Bridge consolidation | ✅ Done (s144 — `tools/bridge_cli.py` + 7 shims, BridgeMetrics namespace in `core/prom_metrics.py`, 42 tests; state consolidation + 5 watcher daemons explicitly out of scope) |
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
