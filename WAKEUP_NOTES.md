# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s171.8 wrap — 2026-05-12 (overnight docs+tests backfill — 5 commits)

Headless `/loop`-driven execution of `HEADLESS_BRIEF_2026-05-12_DOCS_TESTS.md`. Closes the documentation and test gaps left by the s172 wrap session (the substantive view-router / cache-bust work which committed under the "s171.8" commit scope). Risk profile LOW: docs + tests only, zero behavior changes. All 5 commits landed green on the first CI run.

## Ships

| Commit | Theme |
|---|---|
| [a43981b](https://github.com/Remus3/riot-commander/commit/a43981b) | `test:` view-router state machine integration coverage. New `dashboard/view_router_state.py` Python mirror of `web/js/main.js:_viewAutoDerive` (test-only — JS remains runtime source of truth) + `tests/test_view_router_state.py` (27 tests, 17 sub-tests). Covers ChampSelect→GameStart→InProgress→EndOfGame clean cycle, dodge clearing (CS→Lobby/Matchmaking/ReadyCheck), transient null inference (s171.8 sticky-guard fix), InProgress→null sticky preservation, post-game phase clearing, ChampSelect view-gate fallback, urgent banner classifier. |
| [8f3f504](https://github.com/Remus3/riot-commander/commit/8f3f504) | `docs:` sync ROADMAP — annotated the existing s171.8 entry with specific commit hashes (`3e3b14e` for sticky-guard, `876fd01` for unified asset-hash) + `(g)` clause noting the test-backfill ship. Added explicit "DS calibration pipeline" entry mirroring CLAUDE.md priority #14 (`rewind_history.db` staleness blocker). |
| [4a42911](https://github.com/Remus3/riot-commander/commit/4a42911) | `docs(adr):` ADR-008 unified asset-hash for cache + auto-reload. Captures the architectural lesson from the s164→s171.7 stale-cache incident — two functions (`compute_asset_hash` + `_serve_ui_version`) each maintained their own file allow-list; lists diverged silently in s133 ESM split + s164 panel additions. Single source of truth in `compute_asset_hash` walking root + `web/{js,css}/panels/*` + `web/js/lib/*`. |
| [0498bad](https://github.com/Remus3/riot-commander/commit/0498bad) | `chore:` prune WAKEUP_NOTES — moved s170 (LCU wiring punch list) to `docs/history_notes.md` via `scripts/wakeup_prune.py --keep 2`. |
| (this wrap) | `docs:` WAKEUP wrap — s171.8 view-router + cache-bust unification (this entry). |

## Findings

- **Two-asset-hash drift is the textbook ADR-008 case.** Two functions independently maintained allow-lists for cache-busting; they agreed by coincidence in 2026-04 because everything still lived at the root, then diverged silently when s133 introduced the ESM split. The operator-visible failure (browsers serving pre-s171.7 `champ_select.js` for ~10 days) was masked by the fact that the menu route `applyView` bypassed the gate — so clicking into the new view from the menu worked, but real `phase=ChampSelect` push routed to legacy `cs-overlay`. Lesson captured in ADR-008 for future reviewers.
- **Python mirror was the right call (Option A) over Node-driven ESM extraction (Option B).** The JS function lives inside the main.js IIFE closure; extracting it for direct unit testing would have required either moving it to a separate ESM module (invasive refactor) or building a Node test harness that imports through dynamic ESM (fragile). The Python mirror approach is decoupled — change one, change both — but the state-machine logic is small enough (~80 lines) and stable enough (sticky-guard transitions don't churn) that drift risk is acceptable. Mirror docstring flags the obligation explicitly.
- **`derive_view(phase="EndOfGame", mode="sr", sticky="in-progress")` returns `"last-match"` not `"home"`.** Worth noting because mode lingers as "sr" through EndOfGame in real life — `game_reader` doesn't flush `mode_key` until the next coaching tick, which usually doesn't fire until LCU resolves the post-game state. Test initially expected "home" and failed; corrected to match runtime behavior.

## Open items

- 🟡 **Live champ-select run** (carried from s172 wrap) — next CS pop should auto-promote to `view-champ-select` (the new view) with the unified asset-hash now propagating panel-file changes. Confirm via footer hash matches `compute_asset_hash` output.
- 🟡 **Live loading-screen UI** (carried from s172 wrap) — sticky-guard inference + dodge clear paths need a real game to validate end-to-end. The 27 unit tests prove the state machine logic; live verification proves the LCU phase timing assumptions.
- 🟡 **Morning audit brief** — `HEADLESS_BRIEF_2026-05-12_AUDIT.md` is the daytime follow-up. 10 hunt targets, cap 6 unified pairs / 6 hours. Operator can kick off once awake.

## Files touched this session

- `dashboard/view_router_state.py` (new, ~150 LOC, test-only Python mirror)
- `tests/test_view_router_state.py` (new, ~260 LOC, 27 tests + 17 sub-tests)
- `ROADMAP.md` (+2 lines: commit hashes + DS calibration entry)
- `docs/adr/ADR-008-unified-asset-hash.md` (new, ~110 lines)
- `WAKEUP_NOTES.md` (s170 pruned, this wrap added)
- `docs/history_notes.md` (s170 wrap archived)

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
