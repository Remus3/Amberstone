# Riot Commander — Roadmap

_Last updated: 2026-05-04 (s95 — DS item coverage complete, ARAM DS-before-Haiku)_

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

### 2026-05-01 — engineering-audit Tier 2 #6 / #8 / Tier 3 / Tier 4

- T2 #6 — tkinter shim removal: −968 LOC across 12 source files + 5 docs (overlay manager, coach overlay attach/detach, ui aram pregame deiconify)
- T2 #8 C1–C5 — `tk.Tk()` replaced with asyncio scheduler; 5 module pollers + 3 LCU pollers + BaseCoach loops moved to AppLoop. Production tree is now genuinely tkinter-free
- T3 #11 — OBS WebSocket publisher (opt-in, 264 LOC)
- T3 #12 — `core/prom_metrics.py` zero-dep + `dashboard/routes_metrics.py` `/metrics`, ~0.3 ms render
- T3 #13 — `riot-commander.spec` PyInstaller spec (opt-in starter)
- T3 #14 — `core/coaching_data_lock` upgraded to portalocker
- T3 #15 — DecisionLoop daemon thread → `agents/supervisor.py` (separate process), cross-process lock
- T4 #16 — SSE `/api/state-stream` route + `EventSource` subscriber (eliminates ~30 fetches/min when idle)
- T4 #17 — loadout diff highlight (amber ring on items differing across variants)
- T4 #18 — `/api/decisions/log?limit=N` + Recent Coach Calls panel + dedicated `/coach-calls` sub-page
- Tailnet primary: cross-Claude bridge migrated from LAN IPs to MagicDNS hostnames (`legion-rc`, `gamepc-rc`, `peer-host`); cert SAN expanded; rc_rootCA.pem distributed via /agent/

### 2026-05-02 — patch 26.9 build refresh (Phase 0/1/2/3)

Operator request: research arena/aram-mayhem/SR itemization for current patch +
update base builds for all champs (multi-source comparison).

- **Phase 0 — Research (4 docs)**: `docs/ARENA_META_RESEARCH_2026-05-02.md`,
  `docs/SR_ITEMIZATION_CHANGES_2026-05-02.md`,
  `docs/ARAM_MAYHEM_RESEARCH_2026-05-02.md`, `docs/BUILD_REFRESH_STRATEGY_2026-05-02.md`
- **Phase 1 — top-30 per mode**: 3 parallel agents, multi-source cross-ref. SR (aggregator A + aggregator C), ARAM (aggregator K + aggregator A), Arena (aggregator J). 95 champs total
- **Phase 2 — next-30 single-source**: 3 parallel agents, 99 champs total
- **Phase 3 — tail**: full 172/172 roster across all 3 modes
- **New canonical files**: `arena_champion_builds.json` (63 entries, NEW),
  expanded `aram_champion_builds.json` (167) + `sr_champion_builds.json` (73)
- **New tooling**: `scripts/validate_build_data.py` (cross-mode item contamination
  guard, respects DDragon dual-IDs), `scripts/merge_refresh_builds.py` (field-preserving merge),
  `scripts/parse_external_arena.py` (Arena-specific parser)
- **Coach wire-in**: `coaches/_arena_item_advisor.py` reads from
  `arena_champion_builds.json` first; falls back to `aram_champion_builds.json` for
  ~100 champs not yet in arena dataset. Anti-heal + anti-tank pivots + LDR→Mortal
  substitution work on either path.
- **Hexoptics correction**: DDragon dual-IDs (2523 SR/ARAM, 222523 Arena-only)
  documented; contamination filter respects aliases.

### 2026-05-02 — RC↔Peer cross-Claude bridge live

- HTTPS endpoint + Bearer token + `ops/local_paths.json` (gitignored). Opt-in.
  Wire format spec in [`docs io RC peer/RC_BRIDGE_CONTRACT.md`](./docs%20io%20RC%20atx/RC_BRIDGE_CONTRACT.md).
- RC inbox at `POST /api/bridge/inbox` shipped 2026-05-02. Bidirectional handshake
  confirmed over Tailscale (`legion-rc` ↔ `peer-host`).
- **Path-name asymmetry**: RC reads at `/api/bridge`, Peer reads at `/api/bridge/messages`.
  RC added `/api/bridge/messages` alias 2026-05-02 for symmetry.
- **`bridge_monitor.py` sidecar** auto-pongs `kind=task summary=ping target=rc` in <100 ms.

### 2026-05-03 — Bridge Watcher infrastructure (Phase 0/1/2/3)

Operator goal: replace per-tick UI noise from `/loop /process-bridge-tasks`
crons with a silent Python daemon. Plan:
[`tools/BRIDGE_WATCHER_PLAN.md`](./tools/BRIDGE_WATCHER_PLAN.md). Commit
`6a2e958` ships all four phases atomically.

- **Phase 0 — MVP**: `tools/bridge_watcher.py` (silent poll/classify/escalate
  daemon, PID lock, atomic-write health + state files with WinError-5 retry),
  `tools/bridge_watcher_classify.py` (pure classifier, 18/18 self-tests),
  `dashboard/routes_bridge_pending.py` (`GET /api/bridge/pending`),
  `RC-BridgeWatcher` scheduled task (logon trigger, restart-on-failure 3x/1m)
- **Phase 1 — rollout**: `tools/bridge_watcher_install.ps1` (idempotent, PS5.1 +
  PS6+ compatible, cert-bypass shim, hostname-detect), `bridge_watcher_hook.ps1`
  (UserPromptSubmit one-line emitter for no-dashboard nodes), `bridge_watcher_config.json`
  (per-node config: legion/gamepc/peer). Game-PC + Peer installed same session.
- **Phase 2 — auto-action**: `tools/bridge_watcher_actions.py` (claude --print
  invocation with allowlist enforcement; intent-verb frozen-file gate; 16 KB body
  cap with `bridge_action_artifacts/<task_id>.json` overflow; daily $/USD cap with
  midnight reset). `--enable-auto-action-lanes <read|read,ops>` opt-in flag.
  `Edit`, `Write`, `NotebookEdit` always blocked. Live on Legion's `read` lane
  with 8s round-trip, $0.01-$0.05 per call.
- **Phase 3 — ops lane**: tightened Legion `bash_restricted` (removed
  `powershell -c *`, `py *.py`; explicit narrow whitelist for `git pull origin
  main`, `regen_rc_cert.ps1`, `curl` to specific endpoints, `type *.json/*.md/*.log`).
  `restart_trigger.txt` added to `escalate_always`. `--permission-mode bypassPermissions`
  for headless sub-Claude (allowlist already enforces safety).

**Live validation** (8 synthetic envelopes, 3 OK + 5 err caught real bugs):
all 5 errors led to parser/config patches that are now in production. Real-traffic
acceptance criteria (≥90% read / ≥95% ops) needs accumulation of 50+ samples.

**Plan revisions folded** (per peer review): §6 Game-PC paths corrected
(`tools/` → `C:\RC-Agent\`); §6 Peer `auto_ops_verbs` populated + timeout 60s→90s;
§7 body cap 4 KB→16 KB; §7 `Edit` stays out of allowlist; §8 `claim_lock` w/ 60s
TTL; §11 installer handles "cron already dead" gracefully.

**Counter naming clarity**: heartbeat now emits `*_since_boot` (accurate semantics)
+ `*_24h` aliases (deprecated, one release window) per Peer feedback.

### 2026-05-04 — Daemon Slayer item coverage complete (s92–s95, batches 38–62)

Sessions s92–s95 completed the full item modeling sweep for the Daemon Slayer engine. All DDragon purchasable items are now in the `ItemEffect` registry; 8 items remain blocked by genuine schema limits (see CLAUDE.md DS section for details).

**s92 (batches 38–49):** Giant Slayer schema, MR-reduction schema, Arena 226xxx/228xxx/22xxxx mirror pool, component items, boots, 1xxx component sweep. ENGINE_VERSION 0.53.0 → 603 tests.
**s93 (batches 50–53):** `armor_reduction_flat`/`mr_reduction_flat`; Fated Ashes Inflame; Night Harvester + Luden's Echo (ability-cast via `every_n_seconds` binding-constraint); Stormsurge Squall; Hamstringer Scour crit-bleed. ENGINE_VERSION 0.54.0 → 829 tests.
**s94 (batches 54–56):** `bonus_ap_stacked` (Mejai's), `bonus_as_conditional` (Yun Tal); `ap_amp_pct_per_100_caster_hp` (Demonic Embrace); coverage gate test; 46 defensive-only entries completing DDragon coverage (547 entries). ENGINE_VERSION 0.56.0 → 856 tests.
**s95 (batches 57–62):** `caster_bonus_armor`/`caster_lethality` CallContext fields; Void Immolation, Golden Spatula, Darksteel Talons, Bastionbreaker, Reality Fracture; Zaz'Zak's Realmspike (Void Explosion); Bloodsong (Spellblade + Expose Weakness damage amp); Cruelty dual-variant (Arena 447109 + SR 667109, Watch Them Fall). ENGINE_VERSION 0.58.0 → **911 tests**.

**ARAM coach DS-before-Haiku refactor** (s95, commit `3b84949`):
- DS `rank_for()` moved from post-Haiku to pre-Haiku in `coaches/aram_coach.py`
- DS picks injected into the user turn as: `DS top items (DPS ranked): InfinityEdge(+142dps,3400g) > ...`
- Pre-DS hardcoded item rules removed from system prompt (BUILD COMMITMENT, DAMAGE-TYPE ALIGNMENT, ITEM MUTUAL EXCLUSIONS, Banned components — all replaced by DS per-champion math)
- System prompt shrank from ~1,849 → ~1,170 tokens (37% reduction)
- Post-Haiku DS block now reuses `_ds_rows` for UI write (no second engine call)

### 2026-05-03 — assorted hardening

- `c58e689` — restart-RC verb intent-gate hardened
- Path-name aliases for `/api/bridge/messages`
- Game-PC `Stop` hook chat-bleed bug rooted out (was `bridge_post.py` in
  settings.json firing on every assistant turn)
- `process-bridge-tasks.md` skill rewritten for "Step 1 ALWAYS runs the fetch"
  semantics; `process-bridge-tasks-peer.md` template added
- Counter rename `*_24h` → `*_since_boot` (with backward-compat aliases)

### 2026-05-03 — overnight rollouts (post-research review)

After reviewing 32 repos (open-design, ruflo, browserbase/skills, n8n-mcp,
mattpocock/skills, codex skills, hackingtool, karpathy, archon, rtk, plus 22
awesome-lists), shipped fleet-wide:

- **`/diagnose` skill** (mattpocock-derived 5-phase debugging loop) at
  `tools/diagnose.md` + `.claude/commands/diagnose.md`. Frozen.
- **`/caveman` skill** (mattpocock-derived token-efficient compressed-output
  mode, ~75% reduction) at `tools/caveman.md` + `.claude/commands/caveman.md`.
  Frozen.
- **`bridge_post_result.py --suggestions`** (n8n-mcp-style array of actionable
  next-steps in error/escalate result bodies). Backward compatible.
  `tools/process-bridge-tasks*.md` updated to mention.
- **`CLAUDE.md` "state assumptions" rule** (Karpathy-derived): when a request
  is ambiguous, surface the interpretation in one sentence before working.
- **Frozen list expanded** to include the new `tools/diagnose.md`,
  `tools/caveman.md`, `tools/bridge_post_result.py`,
  `tools/bridge_pull_tasks.py`, `tools/process-bridge-tasks.md`,
  plus the bridge_watcher family (already included via prior commits).
- **rtk-ai/rtk install deferred on Legion + Game-PC** — Windows-native mode is
  CLAUDE.md-injection-only (no real Bash hook); ROI doesn't justify install
  risk. Peer dispatch task includes "if Linux/WSL, install" branch.
- **Game-PC + Peer dispatch tasks** sent in parallel to:
  re-pull the patched `bridge_watcher.py` + `bridge_watcher_actions.py`,
  drop `/diagnose` + `/caveman` into `~/.claude/commands/`,
  pull schema-bumped `bridge_post_result.py`, restart their watcher tasks.

**Documented for the operator overnight:** four desktop applicability files
(`rc-applicability.md`, `peer-applicability.md`, `gamepc-applicability.md`,
`fleet-applicability.md`) ranking all 32 reviewed repos 5★ → 1★, with trash
tier removed per request.

### 2026-05-05 — s105 (zero-cost bridge daemons — Game-PC + Peer)

- **`tools/gamepc_bridge_daemon.py`** `ddaec17` — Game-PC zero-cost bridge sentinel. Polls Legion bridge via `bridge_pull_tasks.py --target gamepc` every 30s; only invokes `claude --dangerously-skip-permissions -p /process-bridge-tasks` when count > 0. Installed as `RC-BridgeDaemon` scheduled task (pythonw.exe, AtLogon, restart 3×/1min). Replaces `/loop 1m /process-bridge-tasks` terminal pattern. Confirmed working on Game-PC.
- **`tools/peer_bridge_daemon.py`** `ddaec17` — Peer variant; self-contained inline urllib fetch to `127.0.0.1:8888/api/bridge/messages`; handles bare-list + RC dict formats; reads processed IDs from `rc-bridge-tasks-processed.txt`. Deployment task sent to Peer via bridge.
- **`tools/gamepc_boot.ps1`** `ddaec17` — section 6 now installs/starts RC-BridgeDaemon instead of terminal /loop; fetches `gamepc_bridge_daemon.py` fresh from `/agent/` on each boot.
- **`dashboard/routes_static.py`** — `gamepc_bridge_daemon.py` + `peer_bridge_daemon.py` added to `_AGENT_ALLOWED`.
- **Auth** — `ANTHROPIC_API_KEY` stored in `~/.claude/settings.local.json` env block on Game-PC for headless `--print` sessions; key is available to all claude invocations including scheduled-task context.

### 2026-05-05 — s103 (DS champ-select panel + dashboard bug fixes)

- **DS Engine champ-select build preview** `112350a` — `#cs-ds-block` panel in `#cs-overlay` shows DS-ranked item tiles with +Ndps tooltips before the game starts. Fires once per (champion, mode) pair via new `/api/ds-preview` POST endpoint. `_CS_DS` tracker prevents re-hitting DS on every 2s ally/enemy draft change.
- **SR RECOMMENDED panel fix** `5ee58b6` — `_state_builder.py` returned `mode_key="game"` for SR; JS `driveNow` check failed so all SSE SR state was silently ignored. Corrected to `mode_key="sr"`. `sr_items` fallback (liveclient-derived) now populates NEXT TO BUY when `item_build` is null.
- **Augments pill SR/non-augment modes** `5ee58b6` — CSS static-pill rule was overriding `.hidden` class with `display:inline-flex`. Fixed to `display:none !important` for augments-pill.hidden.
- **Item icon cache race** `f5ce231` — items resolved before `items_index.json` loads were cached as `null` in `_itemResolveCache`; idempotency sig guard then prevented re-render after ITEMS loaded. Fix: clear cache + tile sigs on ITEMS load.
- **`/done` §6b living-doc sync** `d6fbce0` — done command now surgically updates ROADMAP/CLAUDE.md/README as part of exit ritual.

---

## 2. Now — open items

### High priority (do soon)
- **NOTE-025 — TFT OCR region recalibration**: bbox tuples in `tft/tft_ocr_reader.py` target 1600×900 but Game-PC streams 1920×1080. OCR will return garbage in TFT until re-calibrated against an in-TFT 1920×1080 frame. Blocked on user playing TFT to capture a calibration frame.
- ~~**vision_token rotation policy**~~ ✅ done — rotation procedure is fully documented in `core/vision_token.py` (6-step process + `debug()` helper). Token was last rotated 2026-04-28. Next rotation target: **~2026-08-01** (quarterly). Rotate via: generate `secrets.token_hex(16)` → write to `config/vision_token.txt` on Legion + `tools/vision_token.txt` on Game-PC → restart both sides → verify `get_vision_token_source()` returns `"config"` on both.
- **Bridge Watcher acceptance-criteria measurement**: Plan §11 calls for ≥90% success on auto-read and ≥95% on auto-ops. Currently at 3 OK / 5 err on synthetic tests (errors all caught real bugs that are now fixed). Need 50+ real-traffic samples to validate — auto-accumulates as cross-Claude work happens. Watch `auto_ok_since_boot` vs `auto_err_since_boot` on RC heartbeat.
- **Game-PC + Peer auto-action opt-in decision**: their watchers are installed but auto-action lanes are OFF. To enable: edit their `RC-BridgeWatcher-{Node}` XML, add `--enable-auto-action-lanes read[,ops]`, restart task. They also need to re-pull patched `bridge_watcher.py` + `bridge_watcher_actions.py` (3 parser bug fixes from 2026-05-03 live validation).
- ~~**`/api/bridge/pending` dashboard panel + accept/defer/dismiss POST handlers**~~ ✅ shipped 2026-05-03 — Bridge Pending sub-page (`view-bridge-pending`) lists escalations with task_id / from / kind / summary / reason / prompt; menu badge shows pending depth; 20s poll, idempotent sig-based renders. Per-row buttons POST `/api/bridge/pending/<id>/{accept,defer,dismiss}` to `routes_bridge_pending_actions.py` (new sibling, not frozen): accept stamps `claimed_by=operator`; defer extends ttl_at by 24h; dismiss removes from queue (watcher's `processed_ids` dedup prevents re-add).

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

### Bridge Watcher hardening (medium effort, high payoff)

- ~~**Adaptive idle/active polling cadence + `/sleep` `/wake` slash commands**~~ ✅ shipped 2026-05-07 (commit 05983a4) — `_read_mode()` reads `ops/runtime/bridge_watcher_mode.json`; active=15s, sleep=300s, auto=self-managing. `GET/POST /api/bridge/cadence` endpoint. Cross-node control deferred (classifier frozen).
- ~~**Sliding 24h-window counters**~~ ✅ shipped 2026-05-07 (commit f6095a0) — `event_ring_24h` persisted in state; `*_24h` heartbeat fields now reflect true 24h windows. Ring survives restarts.
- ~~**Push notifications for escalations**~~ ✅ shipped 2026-05-07 (commit f6095a0) — `_send_push_notification()` spawns headless `claude --print --allowed-tools PushNotification`; throttled 3/hr.
- ~~**Auto-action restraint by node load**~~ ✅ shipped 2026-05-08 (commit f3ae4cb) — `_check_rc_health()` pure function; suppresses auto-lanes when RC is dead/booting/stale-heartbeat/grace-restart. `auto_suppressed_since_boot` + `_24h` counters in heartbeat. 9 new selftests; 30/30 pass.
- ~~**Bridge Watcher artifact rotation**~~ ✅ shipped 2026-05-07 (commit 6dd91ff) — `_rotate_artifacts()` runs once per day; deletes `bridge_action_artifacts/` files older than 7 days OR in processed_ids. Defensive per-file error handling.
- **Auto-ops verb expansion**: current Legion `auto_ops_verbs` are conservative (4 entries). Once Phase 3 success rate clears 95%, add: `tail .* log` → `Bash(type tail-N)`, `restart agent .*` → `schtasks /Run /TN`, `verify .*` → `curl health`.
- **Per-call cost histogram**: track median/p95 cost per lane in Prometheus; alert if p95 doubles week-over-week (model regression or prompt drift).
- ~~**Watcher self-healing**~~ ✅ shipped 2026-05-07 (commit 6dd91ff) — daemon watchdog thread wakes every 30s; calls `os._exit(1)` if main loop stalled > `max(120s, eff_poll*3)`. Threshold scales with cadence so sleep-mode doesn't false-fire.
- ~~**Watcher dry-run mode**~~ ✅ shipped 2026-05-07 (commit 6dd91ff) — `--dry-run` flag classifies but never writes pending queue or spawns claude --print; heartbeat emits `dry_run=true`. Useful for tuning classifier patterns against real traffic without spend.

### Cross-Claude infrastructure expansion

- ~~**Shared lessons sync (Phase 2+3)**~~ ✅ shipped 2026-05-06 — `core/lessons_sender.py` + `core/lessons_receiver.py` + CLI wrappers + `.claude/commands/process-incoming-lessons.md`. Phase 3 `_lessons_summary()` in `rc_facts.py` emits a lessons block in the SessionStart hook when the ledger is non-empty. Operator-driven send (`tools/lessons_send.py`); auto-triage on receive. Phase 4 polish (confidence scoring, symmetry check, auto-revert) remains.
- ~~**SessionStart enrichment (Phase 4)**~~ ✅ shipped 2026-05-08 — `_watcher_summary()` added to `tools/rc_facts.py`: watcher pid/cadence/queue/auto_ok/err/suppressed (since boot) + esc_24h rendered as a single Legion line. Bridge section gains 24h activity counts (tasks/results/notes). Also fixed: `267014` added to allow-list so RC-VisionServer no longer fires as a false anomaly.
- **Bridge contract v1**: today's spec is v0; bump after the auto-action lane proves stable. Add: `body_path` field formal definition, `claimed_by`/`claimed_at` standardization, `ttl_at` semantics.
- ~~**Bridge introspection MCP tool**~~ ✅ endpoint shipped 2026-05-08 — `/api/bridge` now accepts `source=<node>`, `kind=<kind>`, `hours=N` params. Example: `?source=gamepc&kind=result&hours=24`. Default limit bumped to 100. MCP tool wrapper (for cross-session REPL access) remains as optional polish.

### Operational polish (small, high-leverage)

- ~~**`/api/bridge/pending` POST handlers**~~ ✅ shipped 2026-05-03 — accept/defer/dismiss in `routes_bridge_pending_actions.py` (sibling of the frozen GET module). Operator can now triage escalations directly in the dashboard sub-page.
- **`bridge_watcher_install.ps1` self-update**: when Phase 4+ ships an updated watcher, the installer should detect a stale local copy and prompt to re-pull.
- ~~**Per-node `bridge_watcher_health.json` aggregation on Legion**~~ ✅ shipped 2026-05-06 — `routes_health_peer.py` endpoint + `tools/bridge_watcher_health_publisher.py` sidecar deployed on Game-PC + Peer. Both nodes publish every 60s; `/api/health/all` `peers` block shows watcher_alive, queue_depth, auto_ok/err, escalations, tokens_today for each peer. Confirmed live and fresh.
- **Watcher dry-run mode**: `--dry-run` flag that classifies but never spawns claude --print or writes pending file. Useful for tuning patterns against real traffic without spend.
- **Frozen-file auto-detector**: today the frozen list is hand-maintained in CLAUDE.md + config. Generate it from a `# frozen` doc-comment in the file headers; check in CI.

### Coaching depth (carry-forward from earlier roadmap)



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
- ~~**Auto-rotate `items_index.json` on patch**~~ ✅ already covered — `cmd_all()` in `data_pipeline.py` calls `cmd_items_index()` and RC-PatchRefresh runs `all` weekly on Wednesdays.
- ~~**Champion meta refresh**~~ ✅ shipped 2026-05-08 (commit 6bec3ce) — `_has_smite()` static method replaces the champion-name heuristic as tier-2 fallback; `_JUNGLE_CHAMPS` kept as tier-3 last resort. Smite detection works for any champion including off-meta picks and new releases. 8 new tests.
- ~~**TFT Set data**~~ ✅ patched to 17.2 (2026-05-08, commit be3d168) — `tft_pbe_engine.py` system prompt updated: Encounters (21 total), God Blessings (24 choices across 6 gods), trait balance (Timebreaker rework, Meeple nerf, Stargazer Fountain disabled). `ENCOUNTERS` + `GOD_BLESSINGS` dicts added to `tft_pbe_data.py`. `tft_set17_meta.json` bumped to patch 17.2. Next: 17.3 due ~2026-05-12.

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
| Coaches | All 4 live-game variants writing consistent payloads; all 4 DS-before-Haiku ✅ (ARAM, Arena, Brawl, SR — commit b4609b4) |
| Cache engine | Sub-millisecond hits, lock-protected |
| Match data | rewind_history.db (2846 matches), match_metrics streaming live |

Everything green. No active incidents. Next user-facing milestone is the TFT OCR recalibration when the user next plays TFT.
