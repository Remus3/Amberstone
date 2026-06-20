# RC 2.0 Phase 6.1 - PUSH/PULL Timing Map

Read-only inventory of every function that reads from or writes to League, its cadence, trigger,
consuming module, and port. Goal: make champ-select + UI more responsive WITHOUT exhausting ports
or opening connection storms. All cadences cited from source (file:line). ASCII only.

Date: 2026-06-19. Topology: 1-PC (Legion, ADR-011). League :2999 + LCU lockfile + RC + vision
relay + DS + dashboard all run on Legion. Game-PC agents (`tools/gamepc_*.py`) are out of the live
pipeline (kept for legacy 2-PC / repurpose); their cadences are listed for completeness but are
NOT the live path.

---

## 1. PULL from League - Live Client API (:2999 /liveclientdata/*)

| function | direction | endpoint/port | cadence (sec) | trigger | consumer file:line | notes |
|---|---|---|---|---|---|---|
| `vision_server/_relay._fetch_liveclient_direct` | PULL | `https://GAME_HOST:2999/liveclientdata/allgamedata` | on-demand, throttled >=1.5s gap (`_SELF_READ_MIN_INTERVAL_S`); only when cache age >2.0s (`_SELF_READ_STALE_S`) | event (lazy self-heal on `get_latest_liveclient`) | `vision_server/_relay.py:113,138,187` | 1-PC self-read. Makes the RC-LiveClientRelay agent non-integral. New unverified SSL ctx + urlopen per call; timeout 1.0s |
| `core/liveclient_cache._fetch_once` | PULL (relay, not :2999 direct) | `http://127.0.0.1:8889/latest-liveclient` | 0.5s (`_DEFAULT_POLL_S`) | poll (background thread/AppLoop task) | `core/liveclient_cache.py:35,37,137,159` | Process-wide shared cache. Sole writer; all coaches/tracker/detector read `get()` lock-free. Collapsed ~6-8 polls/s into one. timeout 2.0s |
| `game_reader.poller._try_relay` | PULL | `http://127.0.0.1:8889/latest-liveclient` | driven by `POLL_GAME_MS` = 1.5s | poll (SrAramWorker game loop) | `game_reader/poller.py:35,42,70` | Primary game-state read. `RELAY_MAX_AGE_S=12.0` staleness gate. timeout 2.0s |
| `game_reader.poller.read_game` (direct fallback) | PULL | `https://GAME_HOST:2999/liveclientdata/allgamedata` | only when relay unreachable AND not `_relay_says_no_game` | event (fallback) | `game_reader/poller.py:134,153,249` | `_get()` new urlopen per call, timeout 2.0s. Short-circuited by relay 404 to avoid timeout spam |
| `game_reader.poller._read_game_fallback` | PULL | `:2999` gamestats/activeplayer/allplayers/eventdata | only when `/allgamedata` returns non-dict | event | `game_reader/poller.py:202` | 4 sequential urlopens, one per endpoint |
| `game_reader.poller._try_lcu_game_id` | PULL | `http://127.0.0.1:8889/latest-lcu` | per game-poll tick (1.5s) | poll | `game_reader/poller.py:44,105` | `LCU_RELAY_MAX_AGE=20.0`. timeout 1.0s |
| `tools/gamepc_liveclient_relay.fetch_live` | PULL (Game-PC, legacy) | `https://127.0.0.1:2999/.../allgamedata` | 1.0s in-game (`INTERVAL`), 2.0s backoff (`BACKOFF`) | poll | pushes to `:8889/upload-liveclient` | `tools/gamepc_liveclient_relay.py:54,55` | NOT live path on 1-PC; vision self-read replaces it |

Backbone (1-PC): SrAramWorker -> `_try_relay` (1.5s) hits the vision relay cache, which `liveclient_cache`
warms at 0.5s, which self-reads :2999 at >=1.5s throttle when stale. Net effective freshness of live
combat data ~= 1.5-2.0s.

---

## 2. PULL from League - LCU lockfile API (random port, riot:password)

Lockfile parsed from `C:\Riot Games\League of Legends\lockfile` -> `port:password`. All readers use
verify=off SSL, new `urllib` connection per call (NO pooling).

| function | direction | endpoint | cadence (sec) | trigger | consumer file:line | notes |
|---|---|---|---|---|---|---|
| `LcuClient.get_queue_state` | PULL | `/lol-matchmaking/v1/ready-check` | 1.0s (`start_auto_accept(interval=1.0)`) | poll (`_auto_accept_tick`) | `lcu/lcu_client.py:98,101,127`; `main.py:239` | Ready-check accept loop. Also calls `_maybe_apply_runes` each tick |
| `LcuClient.get_champ_select` (in `_maybe_apply_runes`) | PULL | `/lol-champ-select/v1/session` | 1.0s (rides auto-accept tick) | poll | `lcu/lcu_client.py:229,159` | Reads localPlayerCellId/myTeam to detect lock-in for runes |
| `RuneWriter._poll` -> `get_champ_select` | PULL | `/lol-champ-select/v1/session` | **2.0s** (`POLL_INTERVAL`) | poll (RuneWriter loop) | `lcu/lcu_rune_writer.py:387,445,446`; `main.py:255` | SLOWEST champ-select poll. Also calls `_detect_game_mode` -> `/lol-lobby/v2/lobby` each tick |
| `RuneWriter._detect_game_mode` | PULL | `/lol-lobby/v2/lobby` | 2.0s (rides RuneWriter poll) | poll | `lcu/lcu_rune_writer.py:539` | Per-tick lobby read for game mode |
| `GameReader.read_champ_select` -> `_lcu_get` | PULL | `/lol-champ-select/v1/session` | on-demand (not on the 1.5s game loop; called by client-mode paths) | event | `game_reader/poller.py:235,291` | Separate lockfile auth (`_ensure_lcu`), timeout 3.0s |
| `LcuClient.get_current_rune_page` / `get_all_rune_pages` | PULL | `/lol-perks/v1/currentpage`, `/lol-perks/v1/pages` | on-demand (before each rune write) | event | `lcu/lcu_client.py:254,262` | Read-before-write so DELETE stays under 3-page cap |
| `LcuPregame.get_gameflow_phase` | PULL | `/lol-gameflow/v1/phase` | on-demand | event | `lcu/lcu_pregame.py:254` | Helper; not on a fixed loop in the live path |

### Game-PC LCU agent (legacy, `tools/gamepc_lcu_agent.py`) - three independent loops

| loop | endpoints polled | cadence (sec) | file:line | notes |
|---|---|---|---|---|
| `_state_push_loop` (capture_state) | gameflow-phase, ready-check, lobby, champ-select session, gameflow session, mastery, summoner lookups | 1.0s (`INTERVAL`) | `tools/gamepc_lcu_agent.py:110,632` | Full snapshot -> POST `:8889/upload-lcu`. Mastery TTL 300s, summoner-lookup TTL 600s |
| `_auto_features_loop` | ready-check accept + summoner override | 0.5s (`AUTO_INTERVAL`) | `tools/gamepc_lcu_agent.py:111` | Must be << 12s accept window |
| `_cmd_poll_loop` | drain Legion `/lcu-cmd-pending` | 0.5s (`CMD_INTERVAL`) | `tools/gamepc_lcu_agent.py:112` | Executes queued PUSH commands |
| `gamepc_phase_watcher` | WAMP push events (event-driven) | event; degrades to 5.0s poll if `websocket-client` missing | `tools/gamepc_phase_watcher.py:14,26` | Game-PC-only DXGI capture trigger; additive, not state path |

NOTE: on 1-PC the agent's `capture_state` 1.0s push is the cadence that actually feeds the dashboard's
champ-select view (`/latest-lcu` -> `build_state`), because the in-process `LcuClient`/`RuneWriter`
read champ-select for rune/spell WRITES, not for dashboard rendering. See Findings.

---

## 3. PUSH to League (LCU writes)

All writes go through `LcuClient._request` / agent `lcu_request` (verify=off, new connection per call,
timeout 2-3s). Triggered by events, never on a tight loop.

| function | direction | endpoint (method) | cadence/trigger | consumer file:line | notes |
|---|---|---|---|---|---|
| `LcuClient.accept_queue` | PUSH | `/lol-matchmaking/v1/ready-check/accept` (POST) | event - fires once when ready-check `InProgress` + not responded | `lcu/lcu_client.py:95,127` | Guarded; not spammed |
| `RuneWriter._write_page` | PUSH | `/lol-perks/v1/pages` (POST) + `/lol-perks/v1/currentpage` (PUT) + `/lol-perks/v1/pages/{id}` (DELETE) | event - on champ/mode change only (`_last_applied_*` guard) | `lcu/lcu_rune_writer.py:629,672,676,649` | 3 retries, exp backoff 0.5/1/2s. DELETE stale RC pages first |
| `LcuClient.apply_recommended_rune_page` | PUSH | same perks endpoints | event (alt path via auto-accept tick) | `lcu/lcu_client.py:407,443,455,462` | Frozen file. Same 3-page-cap DELETE dance |
| `RuneWriter._sync_spells` -> `set_summoner_spells` | PUSH | `/lol-champ-select/v1/session/my-selection` (PATCH) | EVERY 2.0s poll, but idempotent (PATCH only when live pair differs) | `lcu/lcu_rune_writer.py:499,529`; `lcu/lcu_pregame.py:205,243` | CS2 self-correct. No write when already correct |
| `LcuPregame.pick_champion` / `hover_champion` | PUSH | `/lol-champ-select/v1/session/actions/{id}` (PATCH) | event (dashboard lock/hover command) | `lcu/lcu_pregame.py:167,174` | |
| `LcuPregame.bench_swap_fast` | PUSH | `/lol-champ-select/v1/session/bench/swap/{id}` (POST) | event (dashboard bench swap) | `lcu/lcu_pregame.py:190` | Bypasses 5s client cooldown |
| agent `execute_command` (apply_item_set/_batch, apply_runes, delete_stale, invite, etc.) | PUSH | `/lol-item-sets/...` (PUT), `/lol-perks/...`, `/lol-lobby/...` | event (dashboard -> `:8889` cmd queue -> agent drain 0.5s) | `tools/gamepc_lcu_agent.py:983,1031,1086` | Legacy agent path; on 1-PC equivalent writes go direct via `LcuClient` |

---

## 4. INTERNAL ports + cadences

| surface | port | cadence (sec) | trigger | file:line | notes |
|---|---|---|---|---|---|
| Game-poll worker (`_drain_game_q`) | n/a (drives :8889 reads) | 1.5s (`POLL_GAME_MS`) | AppLoop schedule | `app/_game_lifecycle.py:35,249,269` | Master tick for SR/ARAM/Arena live coaching |
| TFT drain (`_drain_tft_q`) | n/a | 1.5s | AppLoop schedule | `app/_game_lifecycle.py:120,303` | |
| Dashboard `/api/state` build cache | :8888 | 1.0s TTL (`_state_payload_cached`) | per request/tick | `dashboard/routes_state.py:96,103` | N tabs + SSE + poller dedupe to one `build_state()`/sec |
| Dashboard SSE `/api/state-stream` | :8888 | 1.0s tick (`_SSE_TICK_S`); emit on hash change; 15s forced heartbeat (`_SSE_HEARTBEAT_S`); 600s conn cap; max 8 subs | long-lived push | `dashboard/routes_state.py:126-129,171,191` | PRIMARY UI delivery. `time.sleep(1.0)` per tick |
| Front-end SSE consumer | :8888 | server-driven (~1.0s) | `EventSource("/api/state-stream")` | `web/js/main.js:6481,6486` | Skips poller while SSE fresh (<4s) |
| Front-end LCU poller (fallback) | :8888 | 2.0s (`setInterval(pollLcu, 2000)`) | poll, gated by `Date.now()-lastSseTs<4000` and `document.hidden` | `web/js/main.js:6527,6536,6555` | Only fires when SSE dead/hidden/exhausted |
| Deterministic-coach DS call (`laning_choices`->`matchup`) | DS :8893 | <=1 call per ~3s per distinct state (`_CACHE_TTL_S=3.0`, sig bucketed 5s) | per `build_state` when live game | `dashboard/_deterministic_coaching.py:159,451,475`; `core/daemon_slayer_client.py:1209,1245` | POST `/v2/matchup`. TTL stops 2x/sec hammering of :8893 |
| Active-match panel (`/api/ds-preview`, `/api/vision-state`) | :8888 | `_AM_TICK_MS` setInterval | poll while AM view active | `web/js/panels/active_match.js:116,726,737` | |
| Home panel | :8888 | `_HOME.intervalMs` + 5s alerts mirror | poll | `web/js/main.js:3338,3339` | |
| Activity feed | :8888 | 10.0s (`setInterval(refreshActivity,10000)`) | poll | `web/js/main.js:235` | |
| Champion fallback | :8888 | 15.0s (`refreshChampionFallback`) | poll | `web/js/main.js:1271` | `/api/locked-champion` |
| Staleness sweep | client only | 0.5s (`applyStaleness`) | local timer | `web/js/main.js:1452` | No network |
| Health rollup `/api/health/all` | :8888 -> :8889, :8893 | on request | event | `dashboard/routes_state.py:215,220` | Fans out to vision + DS health |
| Phase-3 WS stub (`ws_client.js`) | :8891 | heartbeat only | - | `web/js/ws_client.js:5,6` | DEAD for state; only paints heartbeat frames. Real data is SSE |

---

## FINDINGS

### A. Where champ-select reactions are SLOW

The champ-select RENDER path on 1-PC is a chain of ~1.0s stages, and the in-process rune/spell
WRITE path is even slower at 2.0s:

1. **SLOWEST champ-select cadence: `RuneWriter.POLL_INTERVAL = 2.0s`** (`lcu/lcu_rune_writer.py:387`,
   loop at `:445/:432`). This governs how fast RC reacts to a champ hover/lock for rune + summoner-
   spell auto-apply. A pick made just after a tick waits up to 2.0s before runes/spells push.
   The sibling `_detect_game_mode` lobby read and `_sync_spells` PATCH inherit this 2.0s.

2. **Dashboard champ-select VIEW freshness** is the sum of three ~1.0s stages, NOT phase-gated off
   by mode:
   - LCU agent `capture_state` push (legacy path) at 1.0s (`tools/gamepc_lcu_agent.py:110`), OR on
     1-PC the dashboard reads `/latest-lcu` which is only as fresh as whatever last populated it;
   - `build_state()` 1.0s TTL cache (`dashboard/routes_state.py:103`);
   - SSE 1.0s tick (`routes_state.py:126`).
   Worst case a champ-select change is visible to the operator in ~2-3s end-to-end.

3. **Phase gating is NOT the bottleneck for poll RATE** but it does scope WHICH reads happen:
   the agent only reads `/lol-champ-select/v1/session` when `phase in (ChampSelect, GameStart,
   InProgress)` (`gamepc_lcu_agent.py:718`); `LcuClient._maybe_apply_runes` resets when not in a
   session (`lcu_client.py:163`). ARAM Mayhem (KIWI, queue 2400) historically fell through mode
   detection (`gamepc_lcu_agent.py:122-125`); that is fixed but is the kind of phase/queue gate that
   silently disables the bench/quick-swap UI for a mode.

4. The in-process `LcuClient` auto-accept tick reads champ-select at **1.0s** (`lcu_client.py:101`)
   - faster than RuneWriter - but it only drives rune apply via `_maybe_apply_runes`, it does NOT
   feed the dashboard.

### B. Where a tighter cadence RISKS port exhaustion / connection storms

Every LCU + :2999 reader opens a **new `urllib` connection per call with NO keep-alive/pooling**
(`lcu/lcu_client.py:82-88`, `game_reader/poller.py:249-252`, `vision_server/_relay.py:118-122`,
`gamepc_lcu_agent.py:194-197`). Risk concentrates where loops multiply:

1. **RuneWriter at 2.0s already issues 2 GETs/tick** (champ-select session + lobby) plus, on
   change, up to DELETE+POST+PUT+PATCH. Dropping it to e.g. 0.5s quadruples LCU socket churn during
   the exact champ-select window when the client is most transiently busy (the code comments already
   call this out at `lcu_rune_writer.py:664`). New ephemeral TCP+TLS handshake each call -> TIME_WAIT
   accumulation on the loopback if cadence is pushed hard across multiple loops.

2. **Stacked loops hit the same LCU port concurrently**: in-process `LcuClient` auto-accept (1.0s) +
   `RuneWriter` (2.0s) + (legacy) agent state-push (1.0s) + auto-features (0.5s) + cmd-drain (0.5s).
   On 1-PC the agent loops are redundant with `LcuClient`; if both run, that is ~5 independent
   pollers against one lockfile port. Tightening any without consolidating risks a connection storm.

3. **:2999 self-read is deliberately throttled to >=1.5s** (`vision_server/_relay.py:106`) precisely
   to avoid hammering Riot's localhost endpoint; the `liveclient_cache` 0.5s poll is safe ONLY
   because it targets the in-process :8889 cache, not :2999. Do not point a 0.5s loop at :2999.

4. **`os.replace` WinError 5 flakes** under concurrent read on atomic writes (`spell_prefs.json`
   write already retries with backoff, `lcu_rune_writer.py:354-368`). Any new high-frequency writer
   to a polled JSON file must use the same lock + bounded-retry pattern (memory
   `reference_os_replace_winerror5`).

5. **iphlpsvc portproxy hazard** (memory `reference_iphlpsvc_portproxy_2999`): a stray self-loop
   `netsh interface portproxy` rule on :2999 produces SSL EOF, not a clean refusal. If a tighter
   :2999 cadence suddenly throws `UNEXPECTED_EOF_WHILE_READING`, check
   `netsh interface portproxy show all` FIRST - it is not a cadence bug.

6. **SSE subscriber cap is 8** (`_SSE_MAX_SUBSCRIBERS`, `routes_state.py:129`). Faster ticks do not
   add connections, but more tabs hitting the cap silently fall back to the 2.0s HTTP poller.

### C. Concrete low-risk levers

**P6.2 - faster champ-select poll, ALL modes**
- **L1 (S / low risk):** drop `RuneWriter.POLL_INTERVAL` 2.0 -> 1.0s (`lcu/lcu_rune_writer.py:387`).
  Only +1 champ-select GET + 1 lobby GET per second; `_sync_spells`/`_write_page` stay idempotent
  + change-gated so no extra WRITES. Halves rune/spell reaction latency. Effort S, Risk LOW.
- **L2 (S / low risk):** cache the lobby `gameMode` for the champ-select duration instead of
  re-reading `/lol-lobby/v2/lobby` every RuneWriter tick (`lcu_rune_writer.py:539`) - mode does not
  change mid-champ-select. Removes one GET/tick, funding L1's extra read. Effort S, Risk LOW.
- **L3 (M / low-med risk):** on 1-PC, retire the redundant agent loops and make `LcuClient` the
  single champ-select reader at 1.0s, OR have the dashboard's `build_state` source champ-select from
  the in-process `LcuClient` directly rather than the `/latest-lcu` relay hop - removes one ~1.0s
  stage from the render chain. Effort M, Risk LOW-MED (touches state-builder wiring).

**P6.3 - UI responsiveness**
- **L4 (S / low risk):** lower `_SSE_TICK_S` 1.0 -> 0.5s AND the `build_state` TTL (`routes_state.py:103`)
  to 0.5s together (they must match per the comment at `:96`). Halves UI update latency; no new
  connections (SSE is push). Cost is 2x `build_state()`/sec - bounded by the `_deterministic_coaching`
  3.0s DS-call TTL so :8893 is NOT hit more often. Effort S, Risk LOW. Watch the
  `_SLOW_BUILD_WARN_S` log to confirm build stays under the tick.
- **L5 (S / low risk):** the fallback LCU poller is already SSE-gated (`main.js:6533`); leave at 2.0s.
  No change needed - flag only so P6.3 does not "speed up" a path that would then double-hit :8888.

**P6.4 - port safety**
- **L6 (M / med risk, high payoff):** introduce a single pooled LCU connection (keep-alive
  `http.client.HTTPSConnection` reused under a lock) behind `LcuClient._request` so all LCU reads/
  writes share one socket instead of one-per-call. Eliminates the TIME_WAIT churn that otherwise
  caps how fast ANY LCU loop can safely run. Effort M, Risk MED (frozen file `lcu/lcu_client.py` -
  needs operator grant; `game_reader/poller.py` is non-frozen and could pilot it first).
- **L7 (S / low risk):** add a shared min-interval guard (like `_SELF_READ_MIN_INTERVAL_S`) around
  any consolidated LCU champ-select reader so multiple callers cannot independently push the
  effective rate past a safe floor. Effort S, Risk LOW.
- **L8 (S / low risk):** keep the :2999 self-read throttle at >=1.5s; do not lower it. Document it
  as the hard floor for direct Riot reads. Effort S, Risk LOW (doc/guard only).

---

## Frozen-file note (for implementers)

`lcu/lcu_client.py`, `core/game_snapshot.py`, `app/_game_lifecycle.py`, `app/__init__.py` are on the
CLAUDE.md frozen list - L3/L6 touching them need explicit operator approval. NON-frozen and safe to
edit for P6.2-6.4: `lcu/lcu_rune_writer.py`, `lcu/lcu_pregame.py`, `game_reader/poller.py`,
`vision_server/_relay.py`, `dashboard/routes_state.py`, `dashboard/_deterministic_coaching.py`,
`web/js/main.js`.
