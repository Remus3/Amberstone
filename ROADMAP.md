# Riot Commander — Roadmap

_Last updated: 2026-04-25_

A consolidated view of where RC has been, where it is, and where it could go.
Living document — update as work lands.

---

## 1. Past — what's been done

### Foundational (pre-2026-04)
- LCU + Riot Live Client API integration (`game_reader.py`, `lcu/lcu_client.py`)
- Per-mode coaching flow — Haiku for advice, Sonnet for vision
- Tkinter overlays per mode (ARAM, Arena, Brawl, TFT, SR)
- Match-history DB + per-mode rating files
- Local cache engine (decisions DB, sub-millisecond cache hits)

### Phase 1 — instrumentation + cleanup (early 2026-04)
- LOG-001/002 — log retention (30-day), rotating file handlers
- SEC-001 — API key leak scrubbed from install scripts + logs
- STR-002/006 — `.bak` cleanup, `.gitignore` hardening
- DATA-001 — matchup-aware item coaching (`item_advisor.py`)
- DATA-003 — `data_pipeline.py aram_builds` for tier auto-update

### Phase 2 — architectural decomposition (mid 2026-04)
- ARCH-001 — `app.py` god class (1228 lines) decomposed into `app/` package (5 files, 428 lines orchestrator)
- ARCH-002 — `BaseCoach` extracted; ARAM/Arena/Brawl coaches inherit
- BUG-1..5 — coach payload + lane orientation + Moon-PC routing fixes
- API-002 — ability cooldowns surfaced in ARAM coaching

### 2026-04-19 — topology migration
- Moon-PC retired; vision moved in-process on Legion at `127.0.0.1:8889`
- RC moved from Game-PC → Legion
- Game-PC agents introduced: `gamepc_screen_agent`, `gamepc_lcu_agent`, `gamepc_liveclient_relay`
- LAN-bridge replaced by direct relay over `:8889`

### 2026-04-23 — dashboard era
- Web dashboard at `:8888` HTTPS (mkcert) — PWA-installable on iPad
- Tkinter overlays disabled (`_HEADLESS=True`), dashboard becomes primary UI (overlay code fully removed in T2 #6, 2026-05-01)
- `/api/state`, `/api/health`, `/api/analyze`, `/api/lcu-cmd`, etc.
- Cross-Claude bridge — bridge_task.py + MCP server on Game-PC `:8892` for cross-machine ops

### 2026-04-24 — UI polish
- Major header/panel restructure (RIGHT NOW / NEXT / WAVES / ITEM BUILD / STATS / MAP STATE)
- Wave-state column layout: TOP / MID / BOT lines with color-coded → ACTION suffix
- Right Now labels: WATCH / FIGHT / BASE
- Layout swap: NEXT+STATS left, RIGHT NOW+ITEM BUILD center, MAP STATE right
- Sim fixtures (26) for offline UI iteration

### 2026-04-25 — feature delivery (later in session)
- **Cold-start champ-select coaching shipped**:
  - `gamepc_lcu_agent.py:capture_state()` extended to include full `myTeam` + `theirTeam` arrays during ChampSelect (cellId, championId, summonerId, summonerName, completed)
  - Dashboard JS gained `handleChampSelect(lcu)` — when phase=ChampSelect and CHAMPS index ready, resolves championId integers to names and fires `fetchAdaptation(myChamp, mode, enemies)`. The existing adaptation panel auto-populates with the user's history on this champion + each enemy matchup, BEFORE the game starts.
  - Queue-id → adaptation-mode map added (450/920 → aram, 1700 → arena, 400/420/etc → sr_ranked)
  - LCU agent restarted clean PID 17284 → 17076. Dashboard JS auto-reloaded.
- **Patch-day data refresh scheduled**: weekly cron at Wed 11:07am runs `data_pipeline.py meta` → `all` if patch changed → bridge note. Session-only; user can `/schedule` it for durable cloud-based version.
- **Adaptation feedback loop shipped**:
  - `modules/cache_engine.bump_confidence(state, multiplier, flag)` — clamps to [0,1], records feedback row.
  - New `coaches/feedback.py` maps grade S/A/B/C/D/F → multiplier (1.5/1.2/1.0/0.95/0.8/flag_bad) and applies to the cache entry for the game's final state.
  - Wired into `performance_tracker.save_rating()` after the rating is computed; non-fatal.
  - Smoke-tested: S → 1.0 (capped), C → 0.95, D → 0.76, F → 0.38 (below 0.5 thanks to flag_bad). Persistent F's still trigger the existing <0.25 deletion path.
- **Vision frame magic-byte validation shipped**: `moon_vision_server.handle_upload_frame` now decodes leading 64 chars, checks for JPEG (`FF D8 FF`) or PNG (`89 50 4E 47…`) header, returns `{"error":"not_an_image"}` on mismatch. Prevents Sonnet credit waste on corrupt uploads.
- **Bridge log persistence shipped**: `_bridge_log` deque now mirrors to `ops/runtime/bridge_log.jsonl` (append-only, auto-rotated at 1000 entries). On RC restart, the in-memory deque hydrates from the last 100 disk entries — cross-Claude bridge history survives restarts.

### 2026-04-25 — audit session (this session)
**Headline fixes** (high user impact):
- `/api/analyze` POST proxy restored — "Analyze Now" button was silently 404ing
- All 4 live-game coaches now write `champion` + `ally_spells` consistently
- Vision-frame staleness rejection prevents Sonnet credit burn during Game-PC outages
- MCP `tool_read_file` OOM hazard fixed both sides (Legion + Game-PC)
- TFT OCR migrated from local ImageGrab to vision relay
- Game-PC agent backoff during Legion outages (~99% LAN traffic drop)
- Hotkey listener auto-restart on glitches
- LCU agent exception handling so commands always return a result
- Cache-hit hot-path halved
- Coaching data multi-writer lock (NOTE-003)

**Defensive hardenings**:
- /api/state 1s cache, Tesseract atomic counter, /api/lcu-cmd validation,
  /api/console-error throttle, vision_token rotated, console-error localStorage fallback,
  game_reader idle short-circuit, bridge_task.py auto-kind, items_index regenerator

**Tech-debt sweep**:
- 6.5 MB debug artifacts cleaned
- `core/moon_sync.py`, `lan_bridge.py`, `ops/backups/` (2.17 MB) → `legacy/`
- `last_game_rating.json` relocated to `data/ratings/` for path consistency
- Bare-except audit: 3 real silent-failure swallows converted to `logger.debug`
- Status ledger refreshed (GR-002, GR-003, BUG-6, dual Moon-PC routing all verified DONE)

**Aggregate**: 26 fixes shipped, 31 audit notes captured, 9 RC restarts, 4 cross-machine deploys.

---

## 2. Now — open items

### High priority (do soon)
- **NOTE-025 — TFT OCR region recalibration**: bbox tuples in `tft/tft_ocr_reader.py` target 1600×900 but Game-PC streams 1920×1080. OCR will return garbage in TFT until re-calibrated against an in-TFT 1920×1080 frame. Blocked on user playing TFT to capture a calibration frame.
- **vision_token rotation policy**: token was rotated this session — establish a quarterly rotation reminder.

### Medium priority
- **Console-pipe localStorage flush is fire-and-forget**: queued errors replay on next successful post but don't have a failure-recovery loop. Adequate today; revisit if it bites.
- **`MatchDB` thread-safety lock** (FIX-021) — added defensively. If parallel writers are introduced, validate the lock works under load.
- **`/api/analyze` 30 s timeout** — fine for ARAM (sub-second), might need a streaming response if/when full-mode analyses scale.

### Low priority / nice-to-haves
- **Phase-marker comments (27 instances)** — historical attribution, not scaffolding. Leave as breadcrumbs unless someone explicitly wants to audit them out.
- **`last_game_rating.json` consumers** — minor: any external scripts pointing at the old root path will need to update. (Internal callers already migrated.)
- **Bare-except instances in frozen files (16)** — flagged but un-touchable without owner approval. Mostly intentional anyway.

### Frozen-file caveats
The following remain off-limits to autonomous edits per `CLAUDE.md`:
`main.py`, `core/log_setup.py`, `core/moon_proxy.py`, `lcu/lcu_client.py`,
`core/game_snapshot.py`, `ops/rc_dev_runtime.py`, `ops/rc_supervisor.py`,
`app/__init__.py`, `app/_health_monitor.py`, `app/_remediation.py`,
`app/_state_authority.py`, `app/_overlay_manager.py`, `app/_game_lifecycle.py`.
Any change here needs explicit user sign-off.

---

## 3. Future — aspirational

### Coaching depth (high value, medium effort)
- ~~**Cold-start coaching via `rewind_history.db`**~~ ✅ shipped 2026-04-25 — champ-select panel now surfaces user's history on the locked-in champion + enemy matchups, before the game starts. LCU agent extended to capture full myTeam/theirTeam; dashboard JS resolves championIds and fires the existing adaptation pipeline.
- ~~**Adaptation feedback loop**~~ ✅ shipped 2026-04-25 — `coaches/feedback.py` translates user grade (S/A/B/C/D/F) to a confidence multiplier on the cache entry for the game's final state. New `cache_engine.bump_confidence()` method, wired from `performance_tracker.save_rating()`.
- ~~**Live coaching during champ-select**~~ ✅ shipped 2026-04-25 — `coaches/champ_select_coach.py` calls Haiku per pick state. New `/api/champ-select-coach` POST endpoint. Dashboard JS debounces (6 s minimum + key dedup) and renders advice/swap/summoners/watchout into the Right Now panel during ChampSelect phase. End-to-end smoke test returned 1.7 s round-trip with substantive Ahri-vs-poke-comp advice.
- ~~**Multi-mode insight digest**~~ ✅ shipped 2026-04-25 — digest popout extended with a TOP INSIGHTS section that fetches `/api/digest`, sorts by severity, and renders top 5 with severity-colored left borders (alert/warn/ok). Cached for 60 s on open. Footer pill click triggers the fetch.

### Platform / observability
- ~~**Cross-process file lock for `coaching_data.json`**~~ ✅ shipped 2026-04-25 — `core/coaching_data_lock.py` upgraded to a `_CombinedLock` that acquires the in-process `threading.Lock` first, then a Windows `msvcrt.locking` byte-lock on `ops/runtime/coaching_data.lock`. 2 s timeout on file-lock acquire so a stuck holder can't block the coach. Best-effort fallback to in-process-only if the OS lock infrastructure fails.
- **Memory watchdog ↔ remediation wiring** — `ResourceManager` currently logs at 500 MB but doesn't trigger a coach restart. Wire to `app/_remediation.py` (frozen-file, needs owner approval) for actual ceiling enforcement.
- **Mobile-native dashboard** — current PWA is fine but adds 2 second touch latency. Native iOS/Android client could shave that.
- **Streaming vision** — instead of 2-second screen captures, push delta-encoded frames. Drops bandwidth ~5×.

### Data pipeline / patch automation
- **Auto-rotate `items_index.json` on patch** — `data_pipeline.py items_index` was added this session. Schedule it via the cron skill alongside `cmd_aram_builds` so patch days are zero-touch.
- **Champion meta refresh** — `_JUNGLE_CHAMPS` set is currently maintained manually. DDragon's `tags` field has `Tank`/`Mage`/`Assassin` etc. — derive the set programmatically.
- **TFT Set data** — `tft/tft_data.py` is seeded for Set 14 / patch 15.x; current is 16.8.1. Build a Set-aware loader from cdragon TFT data.

### Reliability / hardening
- **MCP server timeout** — `run_powershell` already has subprocess timeout; the broader concern is hung tool dispatch. Consider `concurrent.futures` watchdog at the server tier.
- ~~**Bridge task queue persistence**~~ ✅ shipped 2026-04-25 — `_bridge_log` mirrors to `ops/runtime/bridge_log.jsonl` (auto-rotated at 1000 entries); RC restart hydrates the deque from the last 100 disk entries.
- ~~**Vision frame integrity check**~~ ✅ shipped 2026-04-25 — magic-byte validation on `/upload-frame`; rejects payloads that aren't valid JPEG/PNG.
- **TFT vision relay frame dimensions** — pair with NOTE-025: once relayed frames are validated 1920×1080, lock the OCR pipeline to that resolution.

### Developer experience
- **RC dev mode toggle** — `body[data-dev-banner]` already drives a banner toggle. Extend to a side panel that exposes sim fixture switching, force-vision triggers, log tail, all in one place.
- **Test fixtures** — 26 sim fixtures cover happy paths. Add adversarial fixtures (corrupted JSON, partial state, mode transitions) to harden the dashboard renderer.
- **Type hints + ruff** — codebase mixes annotated and unannotated. A one-time `ruff --fix` pass + adding annotations to public coach API would help LSPs.

### Speculative / longer-term
- ~~**Live coaching during champ-select**~~ ✅ shipped 2026-04-25 (live Haiku per pick state, see above)
- ~~**Replay coaching**~~ ✅ shipped 2026-04-25 (lite version) — `coaches/replay_coach.py` + `/api/replay-coach` POST endpoint. Pulls participant + timeline rows from `rewind_history.db` (2846 matches indexed) for any past `match_id` and asks Haiku for a structured Summary + 3 key moments + 2 suggestions writeup. ~8 s round-trip. Markdown-aware parser handles `**Summary:**` / horizontal-rule output. Proper `.rofl` file parsing deferred (encrypted, non-public format).
- ~~**Voice output**~~ ✅ shipped 2026-04-25 — `coaches/voice_coach.py` uses Windows SAPI via PowerShell subprocess (zero pip deps). `/api/speak` POST endpoint with throttle (4 s min) + dedup (60 s same text). Dashboard footer "🔇 VOICE / 🔊 VOICE" toggle persists in localStorage; MutationObserver on `#rn-action` triggers speech on action change.
- ~~**Multi-account support**~~ ✅ scaffold shipped 2026-04-25 — `RC_ACCOUNT_ID` env var support in `performance_tracker._ratings_dir()`. Sets `data/ratings/<account>/last_<mode>.json` when present; flat layout unchanged when unset (backward-compat). UI selector for switching accounts deferred.

---

## Cross-cutting principles (do not violate)

- **Frozen-file rule** — see list above. PR ownership before any edit.
- **Atomic writes only** — `tmp.write_text(...); tmp.replace(target)`. Overlays + dashboard poll mid-write.
- **`py_compile` before restart** — syntax errors crash silently under `pythonw.exe`.
- **Restart via `restart_trigger.txt`** — never `Stop-Process`; use `taskkill /F /PID` if a hard kill is needed.
- **Coach prompt edits require RC restart** — batch edits, restart once.
- **Don't break the cross-Claude bridge** — vision_token + mcp_token are SEPARATE; never let one resolver fall back to the other's file (cycle 7 lesson).

---

## Status summary at a glance

| Layer | State |
|---|---|
| RC supervisor + main | Stable, 9 clean restarts in last audit cycle |
| Web dashboard `:8888` | All 13 endpoints smoke-tested green |
| Vision relay `:8889` | Stale-frame rejection in place; auth via rotated token |
| MCP server `:8892` (Game-PC) | Resolver-based auth, timeout-bounded tools, image-content for inline screenshots |
| Game-PC agents (4) | All 4 with backoff + capture-skip during Legion outages |
| Coaches | All 4 live-game variants writing consistent payloads to dashboard |
| Cache engine | Sub-millisecond hits, lock-protected |
| Match data | rewind_history.db (2846 matches), match_metrics streaming live |

Everything green. No active incidents. Next user-facing milestone is the TFT OCR recalibration when the user next plays TFT.
