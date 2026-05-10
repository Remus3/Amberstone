# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s162 wrap — 2026-05-10 (Pre-Game Lobby page redesign — flow_01 ready for review)

Long UI session. Operator-driven incremental redesign of the entire Lobby view as Phase 3 step 1 of the 14-fixture game-flow build per `feedback_phase3_fixture_ritual.md`. Operator signaled end-of-page with **"Page done — ready for review"** + plans `/done` + `/clear`. Next session **opens with the visual-hierarchy audit** before moving to step 2.

## What shipped (Phase 1 + 2 prep work)

- **Phase 1 — live menu cleanup:** removed Loadouts, Diagnostics, Coach Calls, Bridge Pending, Fleet view sections + dropdown entries. Backend routes preserved (ops tools depend). VIEW_IDS pruned in `web/js/lib/state.js`.
- **Phase 2a — dev panel slim:** dropped RC log tail + Vision Status cards from `view-dev`; only Sim Fixtures list remains.
- **Phase 2b — sim banner de-banner:** layout-pushing DEV PREVIEW banner replaced with a fixed-position corner pill (top-right). `?banner=0` URL param suppresses the pill entirely for clean screenshots.
- **Phase 2c — fixture archive:** 46 prior fixtures moved to `data/sim/_archive/`; manifest reset to `version: 3` with empty `fixtures: []`.
- **Sim mode EventSource stub:** when `?sim=…` is active, `window.EventSource` is replaced with an inert FakeEventSource so the live `/api/state-stream` SSE doesn't race the FakeSocket fixture replay (was causing fixture data to be overwritten by live LCU during dev preview).

## What shipped (Phase 3 step 1 — flow_01_lobby_solo)

### Layout / typography
- All panel titles unified at 15px white centered uppercase (`.lv-panel-title` / `.lv-friends-title`). Section header is `Pre-Game Lobby · live`; per-panel titles render INSIDE each card (NORMAL DRAFT, PARTY, YOUR MAINS / PARTY MAINS tabs, My Top 8).
- View dropdown menu entry renamed `Lobby` → `Pre-Game Lobby` (also `VIEW_LABELS` updated).
- Vertical buffer trimmed across the whole view: `.view-section` margin-top 12→4, padding-top 16→8; `.lobby-view-card` padding 14→8; lobby grid row-gap 14→4 (col-gap kept 14); `.view-section-head` margin/padding-bottom 14/10→8/6.
- `data-view`-based hide rule for in-game pills (champion/zone/cs/vis/gold/lvl/ult/win/game-time): visible only on `view="active-match"` or `view="last-match"`. Replaces the brittle `data-mode="client"` gate that didn't fire in the LCU-says-SR-but-LCU-phase=Lobby state.

### QUEUE panel
- 6-button action strip: `[Accept On/Off] [Party Open/Closed] [Primary Lane] [Secondary Lane] [Cancel Queue] [Find Match]`. Static 110×64px buttons, 2-line content centered. Cancel = red filled, Find Match = green filled with gold pulse animation when `search_state === "Searching"`.
- Lane picker popup repositioned ABOVE the lane-pair wrapper, centered on Primary+gap+Secondary midpoint. Hover shows full UPPERCASE lane name (TOP/JUNGLE/MIDDLE/BOTTOM/SUPPORT/FILL) above icons.
- FILL primary → secondary auto-pinned to FILL; primary FILL→specific role → secondary becomes "needs-pick" (X marker dashed border).
- Change Lobby Mode dropdown: 4-column grid (SR / ARAM / Rotating / TFT). 16 queue choices. Co-op vs AI + Tutorial removed per operator. Click-outside closes.
- queue-block uses `justify-content: space-evenly` so buttons-row + Change Lobby Mode are mirrored vertically (equal space top/middle/bottom).

### Mains panel (YOUR MAINS / PARTY MAINS tabs)
- Tab toggle: green border = selected / red border = deselected. Default tab driven by `lobby.party_size` (1 → YOUR, ≥2 → PARTY); operator-toggle wins once clicked.
- 5-section card layout per row: `Champion (icon + 📋 copy) · Mastery · Recent · Overall (2x2: games / W-L / WR% / total KDA) · Averaged (Gold/CS/Vis on top, H/S/Tnk on bottom)`.
- Summoner name centered above Mastery # (operator's name on YOUR MAINS, party member's name on PARTY MAINS — pulled from fixture or `lobby.members[non-self][i]`).
- Username color palette via `data-color-idx` (self → lavender, members 1–4 → mint/amber/teal/coral). Same idx links Party panel rows to PARTY MAINS cards.
- YOUR MAINS shows 4 cards (operator's top mastery champs). PARTY MAINS shows 4 party-member cards (placeholder when solo).
- Click PARTY MAINS card OR Party row → cross-highlight both with white border (`.is-selected`). Doc click clears.
- Copy clipboard format: `Moonbeam - Vayne - Mastery 8 : 388 K points · 47 Games All-Time · 60% WR`.

### Party panel (top-right)
- Title `PARTY` centered above member rows. Member-count subtitle dropped.
- Per-row 6-col grid: `name | icon-spacer | role | rank | top-3-champs-for-role | actions`. Role + rank shifted LEFT one col vs prior layout to make room for the new top-3-champs col.
- Top-3 champs render as truncated 4-char-max names joined with ` | ` (e.g., `Vayn | Jinx | Kai`). Operator flagged truncation review for next session (4 vs 5 chars).
- Names display short (no `#tag`); copy actions still write the full Riot ID.
- YOU pip removed (border accent on self row signals it). LEADER pip moved RIGHT into actions group, changed ★ → 👑 crown, sized like kick/promote (26×26).
- Right-side actions: `[👑 if leader] [📋 copy] [⬆ promote — leader only] [✕ kick — leader only]`. Promote/Kick fire `window.confirm()`.
- Unranked rendering: `Level NNN : Unranked` (in solo too).
- Peak rank shows season label (e.g., `Peak: S 15 Master 142 LP`) — best of this season vs last season.
- 5 members fit comfortably (gap 1px). Override scoped to party panel only — home.css's auto-fit grid no longer wraps the rows into 2 columns.

### My Top 8 panel (was Recently Played With)
- Repurposed entirely. Existing `_renderFriendsRecent` + Recently Played CSS preserved IN main.js for reuse on a future panel.
- Title: `My Top 8`. Always renders 8 shells (filled or 50%-opacity dashed placeholders).
- Each filled row: `name | games | role | rank | tag | online dot | ➕ invite | ▲▼ reorder | ✕ remove`.
- Add via search input at bottom (Enter or ➕). Rejects duplicates. 9th-attempt prompts to remove someone first ("You need to remove someone from your Top 8, who will it be?" with numbered list).
- User tag click → `prompt()` to edit. Remove → `confirm()`. Reorder via ▲▼ swap with neighbor. Invite → `confirm()` then Phase B pushes LCU.
- Persistence: `localStorage.rc-top8-list`. Sim mode reads `lcu.top8` from fixture first (fixture wins, doesn't pollute operator's localStorage).
- Top 8 rows whose riot_id matches a current party member get `is-in-party` class with light green tint + green border. Tint clears when they leave.
- Search row drops the games/role/rank/tag/dot preview cells (`grid-column: 1/6` on the input) so the operator has 5× wider typing area.

## Bug fixes landed (cross-cutting)

- **handleChampSelect ReferenceError chain** (`b...c5...`): `panels/champ_select.js` was calling `renderLobbyPanel`, `renderHomePanel`, `_viewResolveAndApply`, `_maybeRefreshLobbyView` — all defined in main.js's module scope, none imported. Every call threw `ReferenceError`, silently swallowed by SSE try/catch → lobby view never re-rendered after `state.latest.lcu` was set, even when the operator was in a real lobby. Fix: orchestration moved to a new `handleLcuEnvelope(lcu)` wrapper in main.js that calls handleChampSelect for the champ-select-specific bits and the cross-cutting renders directly. All 4 call sites updated (WS onmessage, SSE handler, HTTP fallback x2). Eliminated the "refresh loses lobby data" behavior the operator hit repeatedly.
- **home-overlay + lobby-overlay leakage:** `renderHomePanel` and `renderLobbyPanel` now hard-gate on `body.dataset.view === "home"` so the overlays don't leak onto Lobby/Dev/etc. views (was previously firing because `_homeShouldShow(lcu)` returned true based on phase alone).
- **Background agent (separate session):** `67e50d2 fix(icons): resolve Kai'Sa + DDragon-rename champion icons on home view` — `_resolveChampId` made authoritative across home-view recent-5 / Tonight's Pick / hero motif / dev replay panel.

## Phase B follow-ups (DO NOT START until operator OKs)

LCU agent on Game-PC (`tools/gamepc_lcu_agent.py`) needs to forward into `state.latest.lcu`:
- `lobby.members[].summoner_level` (for Unranked fallback display)
- `lobby.members[].rank` + `peak_rank` (with `season` label) — Riot Personal-tier API key already approved (FU04, ADR-006, see `core/riot_api.py` from s148)
- `lobby.members[].position_preferences` + `lobby.party_type` (for new lane picker + party-toggle write-back)
- `lobby.members[].top_role_champs` (top 3 champs per role from rewind_history.db)
- `lobby.local_member.auto_accept` (LCU `/lol-matchmaking/v1/ready-check/auto-accept`)
- `main_champs` + `party_mains` (top-1 champ per non-self member, joined w/ champion-mastery)
- `top8` enrichment (online status from `/lol-chat/v1/friends`, games count + role from rewind_history.db) — Phase A reads operator-curated localStorage list

LCU push commands needed (`/lcu-cmd` queue):
- `lobby.set_party_type` · `lobby.set_position_prefs` · `lobby.set_auto_accept` · `lobby.invite_player` · `lobby.kick_member` · `lobby.promote_leader` · `lobby.create_practice_tool`

Other follow-ups:
- **Truncation review** for Party panel top-3-champs col (currently 4-char max — operator flagged 4 vs 5 char review).
- **Settings page hex palette** for editable per-member username colors (linked to the existing `[data-color-idx]` system).
- **Brawl removal sweep** — chip already spawned (Riot deprecated Brawl).
- The relocated `_positionLobbyTitles` JS helper is now a no-op stub — kept for any orphan callers; safe to delete in a cleanup pass.

## Files touched (s162)

- `web/index.html` — heavy rewrite of view-lobby section markup; cache buster `?v=2026051001` → `2026051037`.
- `web/css/panels/header.css` — extensive (view-section + lobby card + queue-block + mains + party + Top 8 + Recently Played styles).
- `web/css/panels/active_match.css`, `panels/team_context.css`, `panels/input_activity.css`, `dashboard.css` — comment updates only (Edge → Chrome, baseline 1920×1080).
- `web/js/main.js` — handleLcuEnvelope wrapper, lobby view render rewrites, Top 8 CRUD, Mains tabbed panel, party row 6-col grid, click-to-select, copy-to-clipboard format, JS-based title positioning (later removed), color palette via data-color-idx, friends-recent code preserved as `_renderFriendsRecent`.
- `web/js/panels/champ_select.js` — handleChampSelect cleaned (orchestration moved out).
- `web/js/lib/state.js` — VIEW_IDS pruned + label rename.
- `web/js/sim.js` — corner pill replaces banner, EventSource stub, fixture-driven `lcu` envelope replay.
- `web/js/panels/dev.js` — render simplified (log tail + vision dropped); preview link clears `#hash`.
- `data/sim/flow_01_lobby_solo.json` — new fixture: solo (sort of — 5 members for layout testing) with `lcu.lobby.members`, `main_champs`, `party_mains`, `friends_recent`, `top8`, position prefs, ranks, peak ranks, top role champs.
- `data/sim/manifest.json` — reset, lists `flow_01_lobby_solo` only.
- `data/sim/_archive/` — 46 prior fixtures moved here.

## Next session — review-first per ritual

Per `feedback_phase3_fixture_ritual.md`, when operator declares fixture done:
1. **Run visual-hierarchy audit subagent** on the rendered Pre-Game Lobby view (sim fixture `flow_01_lobby_solo`). Capture monitor 0 first; brief the agent with the screenshot + relevant CSS files + the spec lineage (operator wants tight density, viewing-distance fonts per `feedback_font_size_viewing_distance.md`, neo-fintech palette). Format: prioritized must-fix / consider / looks-good. ≤250 words.
2. **Review with operator** — they decide per-item.
3. **Iterate fixes** inline. Re-screenshot.
4. After alignment, **start Phase 3 step 2 (`flow_02_lobby_with_others`)** — the spec there is mostly identical to step 1 but explicitly multi-member from the start. Likely a renaming pass since the current `flow_01_lobby_solo` is already showing 5 members for layout dev.

---

# s161 wrap — 2026-05-10 (s153–s161 chain: SR-lobby flicker + Active Match scaffold + ZEN/DEV/tooltip polish)

Long live-fire session. Operator was mid-Arena game when it started, finished SR draft mid-session, lobbied between games. Nine commits, three independent bug chains plus Active Match step 1.

## What shipped

### Mode-flicker chain (closed)
- **s153 (`96bf4ee`)** — `dashboard/_state_builder.py` mirrors the s150 LCU lobby/CS pre-flip into the corresponding `*_mode` / `has_game` flag on the envelope-local copy of `health` so HTTP `/api/state`'s `onHealth` resolver sees in-game flags during the pre-flip window. Tests: `tests/preflip_mode/test_state_builder_preflip.py` +4.
- **s157 (`0e3d87a`)** — same mirror for the WS push path. Discovered s153 only patched HTTP — supervisor's `agents/agent2_backend/file_ingest.py` reads `health.json` raw and broadcasts to `:8891/push`, bypassing the mirror. Extracted `resolve_mode_key` + `apply_preflip_mirror` helpers in `_state_builder.py` and called them from `_check_one` (with `loop.run_in_executor` so the sync `lcu_summary` HTTP doesn't block the supervisor event loop). 25/25 existing preflip tests still green. **Verified live**: pill flipped CLIENT → SR and held steady across 35s.
- **s158 (`bd0c88e`)** — mode/view transition log. `setMode` and `applyView` now stamp into `window.__rcDebugLog` ring buffer (50 entries) + `console.log [rc-mode] [rc-view]` lines + a floating `#rc-dbg` overlay activated by `?dbg=1` URL or `localStorage.rcDebug='1'`.

### LCU agent (Game-PC `C:\RC-Agent\gamepc_lcu_agent.py`)
- **s154 (`3a3bf58`)** — queue_id fallback to `/lol-gameflow/v1/session.gameData.queue.id` when the CS-session endpoint omits `gameData` during BAN_PICK. Without this, `champ_select.queue_id=0` → `cs.sr_draft=False` → DS engine-profile chooser stayed hidden during draft. Repo + deployed copy both patched; agent restarted (pid 11072 → 15476).
- **s155 (`5c39b9b`)** — `lock_pick` race-tolerance: cast `actorCellId`/`localPlayerCellId` to int explicitly; treat "already locked on requested champ" as success (handles dashboard-button vs in-game-button race + apply_runes/apply_item_set serializing ahead of lock_pick). Dashboard `champ_select.js` lock button now polls the agent reply via `lcuPollResult` and stamps `cs-my-state` with `✓ LOCK SENT` / `✓ ALREADY LOCKED` / `✗ Lock failed: <err>`. Agent restarted (pid 15476 → 10508).

### Daemon Slayer "ds not loaded at all" chain (closed)
- **s156 (`6c4a940`)** — two stacked failures, each silently swallowed by SR coach's DEBUG-level except:
  1. Champion-id format mismatch — coaches feed display name (`Kai'Sa`) but DDragon/DS keys are DDragon-ID (`Kaisa`). Fix: `agents/daemon_slayer/server.py` builds a lazy reverse map (display→ID, cached per snapshot) and all 4 champion-taking routes (`/stats`, `/dps`, `/rank`, `/beam`) resolve through it. Covers MonkeyKing/Wukong, Renata/Renata Glasc, Nunu/Nunu & Willump, and the apostrophe family (Kai'Sa, K'Sante, Rek'Sai, Cho'Gath, Kha'Zix, Vel'Koz, Kog'Maw, Bel'Veth). +8 server tests.
  2. Trinkets eat 6-slot DS budget — once user bought 5 components + Farsight, `resolve_many` returned 6 ids and `/rank` refused with HTTP 422. Fix: `core/daemon_slayer_resolver.py` adds `resolve_inventory` (drops 3340/3363/3364 trinkets, 2003/2031/2055 wards/potions, 2138-2140 elixirs); SR coach `coach_integration/_coach.py:281` switched. +7 resolver tests. **Live verified**: `daemon_slayer_picks=5` populated within 2 coach ticks; `#ds-pill` rendered `◆ Stormrazor +116dps`.

### Active Match view (step 1 scaffold)
- **s159 (`3f72795`)** — new view ID `active-match` in `VIEW_IDS` + `VIEW_LABELS`. Menu entry between Lobby and Last Match. `<section id="view-active-match">` in `web/index.html` with 3 panes (CALL · BUILD · MAP). `web/css/panels/active_match.css` (new). `web/js/panels/active_match.js` (new) exports `renderActiveMatch(payload, ctx)` + `activeMatchEnabled()` flag check (`?am=1` URL or `localStorage.activeMatch='1'`, sticky once URL flag fires). `main.js _viewAutoDerive` auto-promotes to `active-match` when enabled AND in-game. Dispatcher hook in `onState`.
- **s160 (`57886e1`)** — grid restructure per operator: 2 columns instead of 3. Left column stacks CALL on top of BUILD (1.1fr); right column is MAP spanning both rows (2fr — ~2× s159 width). Template: `grid-template-areas: "call map" / "build map"`.
- **s161 (`8a857c4`)** — ZEN pill removed from footer prefs-chip (`_refreshPrefsChip` no longer pushes `zen:off`). DEV banner toggle (`#dev-banner-toggle`) hidden permanently with inline `display:none !important` (element preserved so JS hooks resolve). `.app-tooltip` font bumped 14→17px / line-height 1.4→1.45 / max-width 400→480 / padding 8 14→10 16. CSS cache-buster bumped twice this session (2026042614 → 2026051000 → 2026051001).

## Key decisions

- **Pre-flip mirror lives at the envelope layer, not in RC's app-state.** `_state_builder.py` and `file_ingest.py` both compute the mirror at emit-time. `app/_health_monitor.py` (frozen) keeps writing the raw `health.json` — tweaking RC's `_arena_mode/_aram_mode` flags during lobby would have side-effected other RC code paths that assume those mean "real game in progress."
- **DS server gets the resolver, not the clients.** Server-side display-name resolution at `agents/daemon_slayer/server.py:215` benefits all coaches (SR + ARAM + Brawl + Arena) without 4 parallel client-side patches. `resolve_many` stays untouched for calibration / mirror callers; new `resolve_inventory` is the inventory-only sibling.
- **Active Match opt-in via flag, not a default flip.** `?am=1` + sticky localStorage so the operator can A/B against the existing layout before it becomes default. Steps 2-5 will refine the layout in-place — no UI risk to non-opted-in users.
- **CSS cache-buster bumped twice.** Browsers cached the s159 layout after the s160 grid rewrite; a single `?v=` bump per session is fine, two is fine when content actually changes mid-session.

## Follow-up still open (NOT shipped)

- **`web/js/panels/map_state.js:720`** — bare `gameTime.textContent` reference, line 721 is `MM.gameTime.textContent`. Pending since s151. Fires once per second; ~200 console errors per session. Fix: delete line 720.
- **Bridge-pending view** — operator wants kept (the `routes_bridge_pending.py` route IS frozen per CLAUDE.md so don't delete) but moved off the main view dropdown into a hidden access button on the Dev panel. Step 5 of the Active Match plan handles this.
- **Fleet view** — operator wants removed entirely. Step 5 of the plan.

## What's next — Active Match steps 2–5 (operator-locked)

Operator's locked decisions from this session, before /clear:
- All in-game modes share the layout (`sr / aram / arena / brawl`). TFT excluded.
- STATS panel removal scope: in-game only; preserve for last-match.
- NEXT folds into RIGHT NOW as a continuous block (reformat content, simplify).
- Build sequence is the agreed Day 1–5; tonight shipped Day 1 only.

### Step 2 — DS engine in BUILD pane (icons + owned-as-text + per-tick rerank)

`web/js/panels/active_match.js#renderActiveMatch` BUILD branch needs:
- **Item icons**, left-to-right by DS priority (highest delta_dps first).
- Use the existing icon-resolver pattern from `web/js/panels/item_build.js` (look for `_iconForItem` / `dataDragon` URL builder — already handles 16.9.1 patch).
- **Owned items as plain text** — operator quote: "the purchased items can be a list/text view - i know i have them I bought them in game." Comma-separated, single line, dim color.
- **DS picks must update on every coach tick AND on every shop buy.** Currently `_last_ds_rows` is set only inside the SR coach's per-tick path (`coach_integration/_coach.py:297`). Two ways to add shop-buy responsiveness:
  - (a) Cheap: re-rank inside `renderItemBuild`/`renderActiveMatch` when `state.latest.sr.items` differs from the items the picks were computed against.
  - (b) Expensive but more correct: add a fast `/api/ds-rerank` endpoint on the dashboard that calls `daemon_slayer_client.rank_for` synchronously with the current items+champion+level. Frontend hits it whenever owned items change.
  - **Recommend (a)** for v1 — `daemon_slayer_picks` is already keyed by champion+items in the JSON, the JS can detect drift and just re-render from a cached rank_for response. Keep server simple.

### Step 3 — Enemy-comp threading

`coach_integration/_coach.py:280-288` calls `rank_for` with hardcoded `target_armor=80.0`, no `target_mr`, no `target_max_hp`, no `target_bonus_hp`. That's why DS picks "never differ on enemy composition." Fix:
- Compute `target_armor` / `target_mr` from the enemy team's owned items + each enemy champion's base armor/MR @ current level. Sum of (enemy_armor + enemy_bonus_armor_from_items) / 5.
- Compute `target_max_hp` / `target_bonus_hp` similarly. Existing helper at `core/daemon_slayer_resolver.total_bonus_hp` already does the bonus-HP sum from item ids.
- Pull enemy items from `state.latest.sr.enemy_team` (each row has `items` per `coach_integration/_coach.py` payload shape — verify by reading `coaching_data.json` mid-game).
- ARAM/Brawl/Arena coaches have similar hardcoded values — same threading pattern.
- New tests: `tests/phase2_smoke/test_enemy_comp_threading.py` with synthetic enemy team payloads → verify `rank_for` is called with non-zero target_armor/mr/bonus_hp.

### Step 4 — Static SR map + ZOI/threat overlay

MAP pane currently shows placeholder text. Replace with:
- `<img src="/static/map_sr.png">` (need to source/commit a clean static SR map asset under `web/img/map_sr.png`). Repeat for `map_aram.png`, `map_arena.png`, `map_brawl.png` — all 4 modes.
- Overlay `<canvas>` or `<div>` layer absolutely-positioned over the img, painting:
  - **Red** ZOI threat (enemy projected position circles)
  - **Yellow** gank lane corridors (high-traffic ward gaps)
  - **Purple** MIA pings (recent enemy-out-of-vision events from `vision_tracker`)
  - **White** ward dots (existing `data/vision_state.json`)
- `vision_tracker.py` already publishes `data/vision_state.json` with timestamps + positions. Source: `reference_vision_tracker` memory.
- Operator quote: "the map is not being used for the intended purpose either - I would rather a STATIC map of the mode, and the ZOI threat / gank / MIA / hard coloring." Hard coloring = solid fills, not the soft heat-map gradients in the current minimap render.

### Step 5 — Zen-lock + RIGHT NOW fold + housekeeping

- **Zen mode locked while in-game.** Currently zen is a manual toggle. When `state.mode in {sr,aram,arena,brawl}` AND view is `active-match`, force `body[data-zen="1"]`. Restore previous zen state when view changes or game ends.
- **NEXT folded into RIGHT NOW.** Operator wants a single continuous block, not two adjacent panels. Tonight's CALL pane already concats `action / objective / next` — refine the formatting. STATS removed in-game per operator.
- **Bridge-pending → dev panel button.** Don't delete `routes_bridge_pending.py` (frozen). Drop the `bridge-pending` entry from `VIEW_IDS` and from `#view-menu`. Add a `<button id="dev-open-bridge-pending">` inside `#view-dev` that toggles a `<details>` block (or pops a modal) showing the bridge-pending content. Hidden from main directory.
- **Fleet view deletion.** Drop `fleet` from `VIEW_IDS`, remove `<section id="view-fleet">`, drop the menu entry, delete `web/js/panels/fleet.js` if it exists. Save the operator a click in the dropdown.
- **CSS cleanup.** Remove `body[data-view="bridge-pending"] *` rules from `header.css` after the entry is gone. Same for `body[data-view="fleet"]`.

## What NOT to redo

- **Pre-flip mirror is at the envelope layer** (HTTP `_state_builder.py` + WS `file_ingest.py`). Don't go patching `app/_health_monitor.py` (frozen) or RC's app-state to set `_arena_mode` during lobby.
- **DS resolver is server-side** (`agents/daemon_slayer/server.py`). Don't add a client-side champion-id normalizer.
- **`resolve_inventory` is the new inventory-only path.** `resolve_many` keeps the full set for calibration/mirror callers — don't change its behavior.
- **Active Match auto-promote is `?am=1`-gated.** Don't flip it to default-on until steps 2–5 land and operator confirms.

## Live state at /clear

- RC pid 14884 (last restart for s156 SR coach pickup), `last_reload_ok=true`.
- DS server respawned for s156, `engine_version=0.60.0`, `patch=16.9.1`, 705 items, 172 champs.
- Phase-3 supervisor restarted for s157 (pid was 16436 at last check).
- Game-PC LCU agent restarted twice (pid 11072 → 15476 → 10508).
- Cross-Claude bridge healthy at session start (gamepc + peer daemons alive).

## Blockers
- None.

---

# s152 wrap — 2026-05-09 (DS pill in header + ARAM Build-row fallback + match-record wire)

## What shipped (commits `091d18c` + `0bed0cc`)
- **`#ds-pill` in header row 2.** New glanceable surface for the engine's top pick — `◆ <Item> +Ndps`, info-blue (distinct from gold augments-pill). [web/index.html:113](web/index.html:113), [web/css/panels/map_state.css:166](web/css/panels/map_state.css:166), [web/js/panels/item_build.js:265](web/js/panels/item_build.js:265). Sig-keyed paint so cadence churn doesn't flicker; mode-gated to in-game (CSS hides client/tft).
- **Next/ARAM `Build` row DS fallback.** [web/js/panels/next.js:130](web/js/panels/next.js:130) — when the coach hasn't emitted `item_extra` or `objective`, the row falls back to `DS: <name> +Ndps (Ng)` from `daemon_slayer_picks[0]`. Coach copy still wins when present (precedence preserved). Both branches verified live via Playwright direct-import eval.
- **Match-record DS wire.** `performance_tracker._ds_picks_snapshot(sd, category)` reads the per-mode coaching JSON and folds the engine's last DS pick set into `matches.raw_data["daemon_slayer_picks"]` at game-end save. Calibration analysis loses the JSONL ⨝ on (champion, mode, ~ts) — single SELECT now covers it. [performance_tracker.py:48](performance_tracker.py:48) + [performance_tracker.py:340](performance_tracker.py:340).
- **8 new tests** in `tests/phase2_smoke/test_perf_tracker_ds_snapshot.py` — category mapping pin (SR/ARAM/ARENA/BRAWL only; TFT explicitly excluded) + soft-fail paths (missing file, unparseable JSON, wrong field type, non-dict top-level). **Total suite: 624 pass** (was 616).
- **Smoketested live**. Header pill rendered `Stormrazor +54dps` from real coach state. RC reload (PID 2388) clean.

## Key decisions
- **Co-locate DS pill render with item-build panel.** `IB.dsPill` ref + paint live in [panels/item_build.js](web/js/panels/item_build.js); no separate panel module. Single source of truth for any DS-related render — chips + pill update in lock-step from one `dsPicks` array.
- **Build row uses fallback, not replacement.** Coach copy ALWAYS wins when present. The DS surface is a "fill the gap" path — the engine fires every coaching cycle so the row is never empty.
- **DB wire reads from coaching JSON, not in-flight rank_for() call.** Decoupled from coach lifecycle; if save_rating fires after coach has stopped writing, picks are still readable from the on-disk file. Soft-fails to `[]` so DS persistence is observability, never gates the match save.
- **TFT explicitly excluded from `_DS_COACH_FILE_BY_CATEGORY`.** TFT has no DPS framework — pinning the mapping in tests so a future "wire TFT" change is deliberate.

## Follow-up still open (NOT shipped)
- **`map_state.js:720` `gameTime is not defined`** — STILL pending from s151. Bare `gameTime.textContent` at line 720; line 721 is the working `MM.gameTime.textContent`. Fires once per second on every page load; visible in console as ~200 errors per session. Suggested fix: delete line 720.

## What's next
- `map_state.js:720` cleanup — 1-line delete, 30-second job, has been pending since s151.
- **FU01 minimap-locate** — independent + ready anytime. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** DS pill + Build-row fallback + raw_data wire are shipped end-to-end. Tests pass. Don't re-add the pill to a different header row, and don't move the DS render out of `panels/item_build.js`.

## Blockers
- None.
