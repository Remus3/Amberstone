# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s172 wrap — 2026-05-12 (view-router + cache-bust unification — 6 commits; commits scoped "s171.8")

Continuation of s171. Operator opened with "check the github for errors" — 10 consecutive red CI runs caused by 4 ruff errors (including a real F601 dict-key collision bug). Cleared CI, then chained into s168 audit-6 ship + Node.js 24 bump + the substantive view-router / supervisor / cache-bust work. Capped with operator's "the champ-select tab from the RC menu is what we worked on but that is not what is surfaced during champ select" diagnosis — root-caused to two divergent asset-hash file lists drifted since s164, fixed by unifying.

## Ships (chronological)

| Commit | Theme |
|---|---|
| [eba274b](https://github.com/Remus3/riot-commander/commit/eba274b) | fix(ci): clear 4 ruff errors blocking s171.* — including F601 dup `local_cell` key in gamepc_lcu_agent silently overwriting defensive coercion |
| [2e94a76](https://github.com/Remus3/riot-commander/commit/2e94a76) | FU01 audit-6 ship — `parse_http_override` helper validates `?bbox=` against r>l/b>t/coord-range; 6 new tests. Also gitignored `data/top8_list.json` + `data/decisions_heartbeat.json` (runtime-mutated). |
| [afe25ae](https://github.com/Remus3/riot-commander/commit/afe25ae) | ci: `actions/checkout@v4→v6` + `setup-python@v5→v6` (Node.js 24, pre Sept 2026 deprecation) |
| [3e3b14e](https://github.com/Remus3/riot-commander/commit/3e3b14e) | Loading-view sticky-guard inference (`!phase` after CS → game-start) + dodge clear (CS → Lobby/Matchmaking → null). Phase 3 mode overlay in `file_ingest._compute_effective_mode` — LCU phase fills in when Legion can't see Game-PC lockfile (warm-Agent-7 prime fires on time). |
| [1aba0da](https://github.com/Remus3/riot-commander/commit/1aba0da) | Build-variant persistence — `_csvBuildVariantsFor` merges DS engine row + user-saved variants from `/api/loadout/list`; click saves to `rc-ingame-build-<champion>` (same key item_build.js reads). Expanded `compute_asset_hash` to walk panels/*. |
| [876fd01](https://github.com/Remus3/riot-commander/commit/876fd01) | `/api/ui-version` now defers to `compute_asset_hash` — unified the two drifted file lists. Fixes the s164→s171.7 cache staleness where browsers served pre-s171.7 champ_select.js (opt-in gate) the entire window. |

## The meta-bug worth remembering

Two functions independently maintained file allow-lists for cache-busting:
- `dashboard/_static.compute_asset_hash` — drives the `?v=...` query-string rewrite (6 files, root only)
- `dashboard/routes_state._serve_ui_version` — drives the 4s auto-reload poller (4 files, different list, no overlap on main.js or panels)

Both supposedly answered the same question — "did any served-asset change?" — but disagreed since s164 introduced `champ_select.js`. Result: operator's browser served stale code for ~10 days post-s171.7, never received the opt-in→opt-out flip, and saw legacy `cs-overlay` instead of `view-champ-select` during real champ-selects. The menu route bypassed the gate (applyView direct), masking the symptom. Now both defer to `compute_asset_hash` walking root + `web/{js,css}/panels/*` + `web/js/lib/*`.

## Pending verification

🟡 **Live champ-select run** — operator can't play right now. Next CS pop should auto-promote to `view-champ-select` (the one we built) instead of legacy lobby+cs-overlay. Confirm via footer hash `37ba4a3d6f` (already live; auto-reload pulled it during this session).

🟡 **Live loading-screen UI** — sticky-guard inference should now show `view-loading` reliably during the CS→game gap. Both the new branch (`gameStarted=="champ-select" && !phase → "game-start"`) and the dodge-clear (`gameStarted=="champ-select" && phase in (Lobby,Matchmaking,ReadyCheck,None) → null`) need a real game to validate.

🟡 **Phase 3 warm-Agent-7 prime** — `file_ingest._compute_effective_mode` should now fire `client → champ_select` and `champ_select → game` transitions early in the game lifecycle even without health.mode confirming. Watch supervisor log for the "warm session primed on champ-select transition" line.

## Process side-notes

- RC-Supervisor scheduled task was in `Ready` state (last run 2026-05-09) — restart_trigger.txt writes were being ignored. Kicked back to `Running` mid-session.
- `data/top8_list.json` started carrying real operator data (`xChunjae#Mage`) — gitignored + `git rm --cached`'d.
- 3 new tests for `_compute_effective_mode` in `test_round12.py` (9 total there now).

## Open items handed off

- Operator overnight: doc/test backfill brief — see `HEADLESS_BRIEF_2026-05-12_DOCS_TESTS.md`. Self-paced `/loop`. 5 tasks, capped at 4 hours / 5 commits.
- Operator daytime: anti-drift audit brief — see `HEADLESS_BRIEF_2026-05-12_AUDIT.md`. 10 hunt targets, cap 6 unified pairs / 6 hours. Kick off only after overnight brief reports complete.

## Files touched this session

- `tools/gamepc_lcu_agent.py` (F601 fix)
- `dashboard/routes_lobby_aux.py` (E401 fix x2)
- `tests/test_enemy_stats.py` (B017 fix)
- `agents/_minimap_bbox.py` + `agents/supervisor.py` + `tests/fu01_minimap/test_http_override.py` (FU01 audit-6)
- `.github/workflows/ci.yml` (Node 24 bump)
- `.gitignore` (top8_list, decisions_heartbeat)
- `web/js/main.js` (sticky-guard inference)
- `web/js/panels/champ_select.js` (build-variant persistence)
- `web/css/panels/champ_select_view.css` ("saved" tag style)
- `web/index.html` (cache buster bump — auto-rewritten by inject_asset_hash anyway)
- `dashboard/_static.py` (panels glob in compute_asset_hash)
- `dashboard/routes_state.py` (`/api/ui-version` → compute_asset_hash)
- `agents/agent2_backend/file_ingest.py` (LCU phase overlay)
- `agents/agent3_testing/suite/test_round12.py` (3 new tests)
- `HEADLESS_BRIEF_2026-05-12_DOCS_TESTS.md` + `HEADLESS_BRIEF_2026-05-12_AUDIT.md` (new — overnight + morning briefs)

---

# s171 wrap — 2026-05-12 (LCU + DS + UX bug crawl — 8 commits)

Operator surfaced ~15 distinct issues across two duo-queue games, mostly LCU push gaps + in-game UX. Single biggest find: `lcuCmd`/`lcuPollResult` were referenced 22 times in `main.js` but never declared at module scope (regression from s133 38ac760 Phase 3.1 ESM split) — every Find Match / Cancel / queue-change click silently threw ReferenceError. Restored as module-local helpers. 8 commits shipped end-to-end with live verification at each stage.

## Ships

| Commit | Theme |
|---|---|
| [73b66ec](https://github.com/Remus3/riot-commander/commit/73b66ec) | s171 — `lcuCmd`/`lcuPollResult` restore + 6 new lobby LCU handlers (set_party_type/set_position_prefs/invite_player/create_practice_tool/promote_leader/kick_member) + 5 P&B commands to allowlist (set_pick_intent/set_ban_intent/request_position_swap/request_pick_order_swap/set_augment_intent) + new champ-select view lock button + DS-driven build chooser + post-CS view-routing sticky guard + Top 8 server-side persistence (`/api/top8`) + `/api/mains` backend (rewind_history.db join) + auto_accept default flipped True→False + championPickIntent hover fallback + Active Match step 4 map overlay (static SR/ARAM base + champion-dot canvas overlay + MIA badges + JG-gank warning) + DS icon URL fix (perk-images→item-icons) |
| [a4f81a9](https://github.com/Remus3/riot-commander/commit/a4f81a9) | s171.1 — active-match opt-in→opt-out (`?am=0` to opt out), render `coach.immediate` as RIGHT NOW (was being dropped), expand auto-clear stale-manual list |
| [8f78199](https://github.com/Remus3/riot-commander/commit/8f78199) | s171.2 — tighten active-match gate to phase=InProgress (was falling through to stale `state.mode` during champ-select), freshness guard in `renderActiveMatch` (clears stale Kai'Sa "Recall now…" between games) |
| [94cee62](https://github.com/Remus3/riot-commander/commit/94cee62) | s171.3 — `my_completed` from `sess.actions[][]` (was reading non-existent `myTeam[i].completed`, always False), surface `local_cell` (P&B fetch needed it for role resolution) |
| [8bae267](https://github.com/Remus3/riot-commander/commit/8bae267) | s171.4 — enemy-aware DS ranking. New `core/enemy_aware_stats.py` computes target_armor/_mr/_max_hp from liveclient `allPlayers[i].items[]` via ddragon_items.json stat lookup → passes to `rank_for()`. Verified live: vs early-game enemies → Stormrazor/IE top; vs synthetic 150 armor/2500 HP → Blade of Ruined King +101 dps top |
| [f00a8d7](https://github.com/Remus3/riot-commander/commit/f00a8d7) | s171.5 — target_stats caption in DS strip (`DS ENGINE · vs 95 armor · 63 mr · 2210 hp · live · 5 enemies`) |
| [8a90b73](https://github.com/Remus3/riot-commander/commit/8a90b73) | s171.6 — defensive-pick ranker. New `core/defensive_picks.py` classifies enemy team's threat profile (AD/AP/burst/tank, `_KNOWN_BURSTERS` set) → recommends from 22-item curated catalog (Plated/Randuin/Frozen Heart/Maw/Sterak/GA/Zhonya/etc.). DEFENSE row renders in BUILD pane when `burst_threat≥5 OR ad_threat≥7 OR ap_threat≥7` |
| [d12a330](https://github.com/Remus3/riot-commander/commit/d12a330) | s171.7 — champ-select view opt-in→opt-out so ARAM Mayhem operator sees the new view (lock button + ARAM bench + DS picks) without `?cs=1` |

## Game-PC redeploys this session

LCU agent redeployed 3 times via http.server :8765 dance (`reference_gamepc_http_server_redeploy.md`):
- pid 4636 → 7940 (s171 — 5 new commands + championPickIntent + auto_accept=False)
- pid 7940 → 6672 (s171.6 hop — promote_leader/kick_member added)
- pid 6672 → 1976 (s171.3 — `my_completed` from actions[] + local_cell)

Live pid 1976 confirmed running.

## Diagnosis-only finds (not bugs in our code)

- **Phase 3 supervisor mode-detector stale-lock**: after a game ended at 00:25:21, the supervisor stayed in `mode=client` for the entire next game's champ-select + loading because LCU lockfile check fails (Phase 3 runs on Legion, lockfile is on Game-PC). Decision detector + game poller both correctly gated their loops on the relay's `RELAY_MAX_AGE_S` (8s/12s). Recovery happens when the next game starts and `gamepc_liveclient_relay.py` pushes fresh data. **Not a regression** — but worth a next-session look if it recurs.
- **`gamepc_liveclient_relay.py` standby for :2999 — correct behavior.** League's :2999 LiveClient API only listens once `League of Legends.exe` is running (not `LeagueClient.exe`). Relay agent's SYN_SENT socket waits.

## Decisions / notes for next-session-you

- **`lcuCmd`/`lcuPollResult` are now at module scope in `main.js`** (line 39+). Don't add duplicates inside `_lobbyViewWireOnce` or similar — they'd shadow.
- **`activeMatchEnabled` / `loadingViewEnabled` / `champSelectViewEnabled` all default-on now.** All three accept `?<flag>=0` for opt-out + `localStorage.<key>='0'` for sticky. The view-router's auto-derive expects this — don't revert to opt-in without updating the derive chain.
- **`_VIEW.gameStarted` sticky guard** (`web/js/lib/state.js`) latches to `champ-select → game-start → in-progress`, only clears on stable post-game phases. Rides through transient phase=null/Lobby during CS→loading→game flip. Don't add a manual "reset on game start" — would re-introduce the flip-back-to-pregame-lobby bug.
- **`my_completed` derivation** in `gamepc_lcu_agent.py:_team_picks` walks `sess.actions[][]` for the local cell's pick action. **LCU's `myTeam[i]` has NO `completed` field** — historical reads were always False. Same gotcha applies if you ever need per-ally lock state.
- **`target_stats.source`** field in `/api/ds-preview` response distinguishes `live-items` / `explicit-override` / `mode-level-curve` / `default-zero`. UI hides caption when source=default-zero.
- **Defensive-pick threshold tuning**: currently `burst≥5 OR ad≥7 OR ap≥7`. If operator complains about DEFENSE row spam, raise burst threshold; if it under-fires, lower to 4.
- **Build-variant persistence is the last deferred item** (operator's "kaisa experimental" complaint). Currently the build chooser shows a single DS variant — no choice to persist. Requires re-introducing multi-variant + sessionStorage save + active-match read path. Substantial.

## Open items handed off

- 🟡 **Live ARAM Mayhem verification** — operator was entering CS at wrap. New champ-select view should auto-promote; ARAM bench + build chooser + lock button should be functional.
- 🟡 **Build-variant persistence** (champ-select → in-game) — deferred per above.
- 🟡 **Working-tree triage** (still unresolved from s168): `agents/_minimap_bbox.py` + `agents/supervisor.py` + `tests/fu01_minimap/test_http_override.py` carry pre-session FU01 refinement (extracted `parse_http_override` helper). Audit reports under `agents/agent6_auditor/proposals/20260511-200200-sixth-audit/` document the proposed changes. Operator should decide: commit / retire / in-progress.
- 🟡 `data/top8_list.json` carries the operator's actual Top 8 entry now (`xChunjae#Mage`). Probably should be `.gitignore`'d — it's user data, not source.

## Files touched this session

- `core/enemy_aware_stats.py` (new) · `core/defensive_picks.py` (new)
- `dashboard/routes_state.py` (ds-preview enriched 2x) · `dashboard/routes_loadout.py` (allowlist) · `dashboard/routes_lobby_aux.py` (new — /api/top8 + /api/mains) · `dashboard/_dispatch.py` (registered new routes)
- `tools/gamepc_lcu_agent.py` (championPickIntent + my_completed + local_cell + 6 new handlers + auto_accept default flip)
- `web/index.html` (cache buster 2026051125 → 2026051210)
- `web/js/main.js` (restored lcuCmd/lcuPollResult + frontend toggle wiring + auto-clear expansion + sticky guard)
- `web/js/lib/state.js` (added `_VIEW.gameStarted`)
- `web/js/panels/champ_select.js` (lock button, DS-driven build chooser, opt-in→opt-out)
- `web/js/panels/active_match.js` (default-on, render `immediate`, step 4 map overlay, target_stats caption, DEFENSE row, freshness guard)
- `web/css/panels/champ_select_view.css` (lock-button styles)
- `data/top8_list.json` (new — server-side Top 8 persistence)
- `docs/ARCHITECTURE.md` (auto-synced by archmap)

---

# s170 wrap — 2026-05-11 (LCU wiring punch list — items #1 #2 #3 #4 #5 #7 shipped, #6 parking-lot)

Operator opened by asking "what is needed to finish the LCU wiring to the UI output for things like pre-game lobby and, champion select, and DS output to active match" — informational query that produced a 7-item punch list. Then operator said "continue" repeatedly, working through items 1–4 + 7 in one continuation. Items 5 and 6 ended the session as bridge-dispatched (waiting on Game-PC Claude) and parking-lot (requires live Arena lobby) respectively.

## Ships (in chronological order this session)

- **Item #7 — My Top 8 dummy purge** (`web/js/main.js:3456`). Auto-prune list of 8 known sim-fixture `riot_id`s (`FrenLuvr#NA1`, `Brawler#NA1`, `SmurfLord#PRO`, `WardBot#SUP`, `CarryHarder#NA1`, `SkillIssue#TT`, `NoobieMcGee#NEW`, `SamplePlayer Sock#NA1`) filtered out of `localStorage.rc-top8-list` on `_top8Load()` read; cleaned list written back. Idempotent. Real `SamplePlayer#Vayne` cannot collide because matching is on full riot_id including tagline.
- **Item #1 — LCU lobby members forwarder** (`tools/gamepc_lcu_agent.py:188-336`). `state["lobby"]` now carries `members[]`, `local_member`, `is_leader`, `party_id`, `party_type`, `can_search`, `queue_name`, `search_state` — driven off `/lol-lobby/v2/lobby` + `/lol-matchmaking/v1/search`. Per-member: puuid, summoner_id, riot_id (composed from gameName + tagLine), summoner_level, ready, position_preferences. 22 tests under `tests/phase_b_champ_select/test_lcu_lobby_members.py`. **Game-PC redeployed via http.server :8765 → Invoke-WebRequest dance (pid 15480 confirmed alive).**
- **Item #1 follow-on — is_self via summoner-id match + name enrichment** (same file). Current LCU builds emit empty `gameName`/`tagLine` on lobby members and don't set `isLocalMember`. Fix: compare `member.summonerId` to local summonerId (resolved via `_resolve_local_summoner_id`, already cached for mastery hook); enrich missing names via `/lol-summoner/v1/summoners/{sid}` (per-id 10-min TTL cache `_summoner_lookup_cache`). 9 additional tests. **Game-PC redeployed AGAIN.** Verification awaits next Lobby phase (operator entered ChampSelect mid-session).
- **Item #2 — DS enemy-stats heuristic helper** (`coach_integration/enemy_stats.py`, new). `compute_enemy_stats(mode, game_seconds, level, bonus_hp_override, enemy_levels)` returns level-scaled `EnemyStats(armor, mr, max_hp, bonus_hp)` per mode (SR/ARAM/Arena/Brawl). Replaces all 4 coaches' hardcoded `target_armor=80.0`. Coaches' existing item-aware `_estimate_target_bonus_hp` preserved via `bonus_hp_override`. 27 tests under `tests/test_enemy_stats.py`. Live via restart.
- **Item #3 — Active Match per-tick DS rerank + icon strip** (`web/js/panels/active_match.js`). `_maybeRefreshDsPicks()` POSTs to existing `/api/ds-preview` with current `{champion, mode, level, items}`; 4s input-fingerprint cooldown so DS engine isn't hammered. `_dsIcon()` renders CommunityDragon item icon (44px) with green "OWNED" overlay + `+Ndps` delta caption. Fallback tile when icon CDN 404s (Arena re-skins). Coach-emitted `daemon_slayer_picks` remains the fallback when live rerank hasn't responded yet.
- **Item #4 — Pick & Ban Recommendations backend join** (`dashboard/routes_pickban.py`, new + `dashboard/_dispatch.py` wired). `GET /api/champ-select/pickban-recs?role=X[&queue=Y]` returns operator-aware performance row + ban suggestions from `rewind_history.db`. Role normalization handles both LCU (BOTTOM/UTILITY) and dashboard (BOT/SUP) forms. Performance: highest-WR champ with ≥3 games. Bans: top 3 enemy-at-role champs with ≥2 encounters and ≥50% loss rate. Mastery + meta rows still on placeholders (Tier 2). Read-only SQLite connection (WAL-safe). 17 tests under `tests/test_routes_pickban.py`. Wired into `web/js/panels/champ_select.js:_csvRenderPickBan` via `_csvFetchPickBanRecs` with 60s cache + re-render on fetch land. **Live verified: 33ms response, real `MissFortune 4/6 67% WR` with ban suggestions Nilah/Twitch/Mel (all 100% loss-rate).**

## Bridge-dispatched and resolved

- **Item #5 — RC-LCU scheduled task action path fix** (bridge task-id `task-454fde72f190`, completed by Game-PC Claude at 1778559598, 63s round-trip). Before: `Execute: py` (failed ERROR_FILE_NOT_FOUND under scheduled-task context — same root cause as RC-PatchRefresh per `project_rc_patchrefresh_fixed.md`). After: `Execute: C:/Users/Administrator/AppData/Local/Python/pythoncore-3.14-64/python.exe`. Running agent (pid 15480) deliberately NOT restarted by Game-PC Claude — fix applies on next reboot. Pattern established: dispatch Game-PC system fixes via `bridge_cli.py task --target gamepc` with self-contained PowerShell instructions; round-trip in ~60s when /loop is running.

## Parking-lot

- **Item #6 — `set_augment_intent` LCU endpoint discovery**. Blocked on live Arena lobby. Discovery pattern from s168 (lockfile → basic auth → enumerate `/lol-cherry/v1/*` paths) can run when next Arena queue pops. Until then, agent's stub at `tools/gamepc_lcu_agent.py:777` returns `augment_intent_unsupported`.

## Test posture at wrap

- Project sweep: **788 passed** (was 719 at s169 wrap; +22 lobby members + 9 enrichment + 27 enemy_stats + 17 routes_pickban = +75 tests).
- Snapshot panels: untouched (no active-match snapshot tests; champ_select snapshot fixtures already had placeholder render).

## Live verification at wrap

- RC pid=12852 alive, last_reload_ok=true (restarted twice this session — once for coach changes, once for new route module).
- Game-PC LCU agent pid=15480 alive, posting fresh state. Verified phase=ChampSelect with mastery + champ_select populated.
- `GET /api/champ-select/pickban-recs?role=BOT` returns 200 with real data.
- http.server on :8765 shut down (both redeploys completed).
- Cache buster: 2026051122 → 2026051125 (bumped three times — Top 8 wipe, active-match step 2/3, P&B recs wiring).

## Decisions / non-obvious notes for next-session-you

- **Game-PC redeploy is fiddly.** SMB pull from `\\192.168.8.230\C$\...` is blocked (no peer creds cached). Workaround: `cd <staging>; py -m http.server 8765` on Legion + `Invoke-WebRequest` on Game-PC. Document this in OPERATIONS.md if it recurs more (s168 + s170 both used it).
- **`Get-WmiObject` is broken on operator's PowerShell.** Throws `0x800703E6 / BadImageFormatException`. Use `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` instead. Updated all redeploy command blocks to use Get-CimInstance.
- **PUUIDs in `rewind_history.db` are stale.** The `v8HzkOaP...` puuid (operator's old) is the most frequent participant entry but is invalid for Match-V5 calls per s167. For internal queries against participants table it's fine (it's just an internal join key). The routes_pickban endpoint uses `_resolve_operator_puuid()` which picks most frequent — works because we're doing a self-join inside the DB, not calling Riot Web.
- **DS rerank cooldown is 4s, not coach-tick aligned.** Active Match view fires `/api/ds-preview` on input fingerprint change OR every 4s, whichever is sooner. Coach tick is variable (5-15s). Live rerank takes priority over coach-emitted picks when both are present.
- **`compute_enemy_stats(level=11, mode="sr")` returns armor=95, mr=63, max_hp=2210, bonus_hp=1610.** Old hardcoded value was target_armor=80.0 only — all other fields were defaults (0). That means historical DS picks were missing target_mr/target_max_hp/target_bonus_hp entirely. **DS calibration baseline shifts on first in-game tick after s170.** Watch the first 2-3 games' picks; if they look wildly different from coach narration, the heuristic may need tuning.
- **`_lobbyViewRefresh` lobby field expectations are NOT all live yet.** It also expects per-member `rank`, `played_with_me_count`, `is_online` — those need Legion-side joins (Riot Web rank + rewind_history.db games + LCU `/lol-chat/v1/friends`). Agent forwards what LCU emits; Legion enrichment is follow-on.
- **`_PB_LIVE_CACHE` is per-role-per-queue, 60s TTL.** During an active champ-select session the WR data isn't changing, so 60s is plenty. If you ever want sub-minute freshness (e.g. running multiple sessions back-to-back with new games landing in between), bump the TTL down OR add a manual refresh button.

## Files touched

- `tools/gamepc_lcu_agent.py` (+~200 LOC: `_LOBBY_QUEUE_NAMES`, `_slim_lobby_member`, `_derive_search_state`, `_lookup_summoner_by_id`, `_resolve_local_puuid`, `_reset_summoner_lookup_cache_for_tests`, capture_state lobby block extension)
- `tests/phase_b_champ_select/test_lcu_lobby_members.py` (new, ~330 LOC, 31 tests)
- `coach_integration/enemy_stats.py` (new, ~165 LOC, EnemyStats + compute_enemy_stats)
- `coach_integration/_coach.py` (+~20 LOC: SR coach DS call uses helper)
- `coaches/aram_coach.py` (+~15 LOC: ARAM DS call uses helper, item-aware bonus_hp override)
- `coaches/arena_coach.py` (+~17 LOC: same pattern for Arena)
- `coaches/brawl_coach.py` (+~15 LOC: same pattern for Brawl)
- `tests/test_enemy_stats.py` (new, ~190 LOC, 27 tests)
- `web/js/panels/active_match.js` (+~100 LOC: `_maybeRefreshDsPicks`, `_dsIcon`, `_dsIconFallback`, BUILD body rewrite)
- `dashboard/routes_pickban.py` (new, ~210 LOC: `/api/champ-select/pickban-recs` endpoint)
- `dashboard/_dispatch.py` (+2 LOC: route registration)
- `tests/test_routes_pickban.py` (new, ~240 LOC, 17 tests)
- `web/js/panels/champ_select.js` (+~85 LOC: `_CSV_PB_CACHE`, `_csvFetchPickBanRecs`, `_csvMergePickBanData`, `_csvRenderPickBan` extension)
- `web/js/main.js` (+~15 LOC: `_TOP8_FAKE_RIOT_IDS` + filter on `_top8Load`)
- `web/index.html` (cache buster ×3: 2026051122 → 2026051125)

## Open items handed off

- ✅ **Bridge task `task-454fde72f190` resolved** by Game-PC Claude. RC-LCU scheduled task now uses absolute python path; auto-relaunch on reboot fixed.
- 🟡 **Lobby-phase live verification of is_self + name enrichment.** Operator was in ChampSelect at wrap. Next Lobby phase exercises this path.
- 🟡 **Active Match view live verification.** Operator was in ChampSelect; once they enter a game, `?am=1` (or `localStorage.activeMatch=1`) auto-promotes and the per-tick rerank + icon strip light up.
- 🟡 **P&B Recommendations live verification.** Operator was mid-CS at wrap; the new Performance row on the champ-select view's P&B panel should overlay live data within 60s of CS entry.
- 🟡 **Item #6** — Arena augment intent endpoint discovery. Next Arena queue pop.
- 🟡 (Unchanged from s169) ADR-007 phase 2 (postmortem pipeline), phase 3 (prose-coach deprecation).
- 🟡 (Unchanged from s168/s169) P1b augment registry, P5 default DS build #4, P3/P4 history+replay UI.
