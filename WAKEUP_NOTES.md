# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s151 wrap — 2026-05-09 (augment-pill flicker fix + ESM-split _ibBuilds orphan)

## What shipped (commit `8db992b`)
- **Augment-pill flicker root-cause fix.** `dashboard/_state_builder.py:117` now passes `aram_mode/arena_mode/brawl_mode/tft_mode` through the trimmed health envelope. Without them, JS `onHealth` fell through to `tag="sr"` whenever `has_game=True` and no specific flag was set, racing `onState`'s `mode_key="arena"` from the same `/api/state` payload — `body[data-mode]` flapped every cadence cycle, flashing every mode-gated CSS rule (augments-pill the most visible casualty).
- **`_ibBuilds` orphan const fixed.** Const declaration moved from `web/js/panels/champ_select.js:207` (referenced nowhere in that module post-split) into `web/js/panels/item_build.js:264` next to its 17 callers. Phase 3 ESM split moved the references but left the data behind. Every `renderItemBuild` call with `state.mode in {sr,aram,brawl}` + champion known had been throwing `ReferenceError`, silently aborting the rest of `onState` (Minimap/Stats/GameSense/WhatWent/Digest/Adaptation never reached). Arena/TFT/client hit the early-return so the regression hid behind recent Arena play.
- **Verified end-to-end via Playwright.** `renderItemBuild` confirmed throw-free on sr/aram/brawl/arena. `champ_select.js` exports still callable. Synthetic arena payload renders 2 Recommended + 3 Owned tiles + 3 DS chips, in that order — DS does NOT replace Item Build, it's a sibling section. API smoke 6/7 200 (`/api/ds-preview` correctly POST-only).

## Key decisions
- **Patched at the data-pass-through layer, not the JS dispatcher.** `_state_builder.py` is the canonical health-envelope assembler; surfacing the four mode flags fixes the flicker for both `/api/state` REST polls and the `/api/state-stream` SSE channel in one edit. JS `onHealth` left as-is.
- **Moved `_ibBuilds`, didn't duplicate it.** `champ_select.js` had no remaining call sites; declaring it in two modules would just invite the next forgotten edit.

## Follow-up still open (NOT shipped)
- **`map_state.js:720` `ReferenceError: gameTime is not defined`** — same Phase 3 ESM split miss. Bare `gameTime.textContent = str` at line 720, while line 721 is the working `MM.gameTime.textContent = str`. Fires once per second on every page load. Suggested fix: delete line 720 (line 721 covers it). Reported but left for separate session — out of scope after the user approved the `_ibBuilds` fix.

## What's next
- `gameTime` cleanup at `map_state.js:720` — 1-line delete, 30-second job.
- **FU01 minimap-locate** — independent + ready anytime. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** augment-pill flicker is fixed at the source (state-builder); don't go patching `onHealth` in main.js. `_ibBuilds` is now in `panels/item_build.js` — don't re-add it to `champ_select.js`.

## Blockers
- None.
