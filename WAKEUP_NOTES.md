# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s130 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s133 wrap — 2026-05-08 (Phase 3.1 — ESM panel split, panels/ extraction)

## What shipped
- **`tools/extract_panels.py`** (new): one-shot Python extractor — line-range based, 2-space IIFE dedent, writes all 7 panel modules + rewrites main.js in one pass.
- **`web/js/panels/right_now.js`** (new): `RN, renderRightNow, renderWhatWent, renderDigest, renderGameSense, renderStats`
- **`web/js/panels/next.js`** (new): `NX, renderNext, arenaDetectPartner, arenaPartnerLine, arenaWaveLine`
- **`web/js/panels/item_build.js`** (new): `IB, renderItemBuild, renderItemTiles, _updateItemBuildHeader, _ibPushItems, _ibMaybeRenderBuilds, _ibFetchAndRender, _ibSetStatus, _ibRenderRows, _ibMarkSelectedRow, _ibSaveChoice` — ALL _ib* functions live here to avoid circular dep
- **`web/js/panels/map_state.js`** (new): `MM` + full minimap/clock/spell system; `state.gameClock, state.adaptCounterMap, state.spellCds` initialized in module header
- **`web/js/panels/champ_select.js`** (new): `handleChampSelect, renderChampSelectPanel, renderChampSelectCoach`; imports _ib* from `./item_build.js`; `renderChampSelectCoach` rewritten to use `el("rn-action")` / `el("rn-immediate")` instead of `RN.action` to avoid cross-panel dep
- **`web/js/panels/bridge_pending.js`** (new): `renderCoachDecisions, renderRecentCoachCalls, renderBridgePending`; setIntervals run at module load
- **`web/js/panels/dev.js`** (new): `_settingsRefresh, _diagFetchAndRender/_diagWireOnce, _devViewWireOnce/_devViewFetch, _replayViewWireOnce/_replayViewRefresh/_replayLoadMatch`
- **`web/js/main.js`** (modified): 8225 → 4189 lines (4036 removed); 7 panel import block inserted after lib imports

## Key decisions
- `_ib*` functions extracted to `item_build.js` (not `champ_select.js`) — `renderItemBuild` calls them, would be circular if they lived in `champ_select.js`
- `state.gameClock / adaptCounterMap / spellCds` init lifted to `map_state.js` header; duplicate assignments in extracted functions are harmless (second wins, same value)
- `RN, NX, IB, MM` exported from their panel modules and re-imported in main.js for `applyStaleness`, `refreshMinimap`, `refreshVisionOverlay`
- `_fmtMMSS`, `_renderMmStateLine` added to `map_state.js` exports — called by code remaining in main.js

## Verification
- `node --check`: all 8 files (main.js + 7 panels) → SYNTAX OK
- HTTP 200 for all 7 panel modules from `:8888` dashboard server
- Dashboard screenshot: all panels rendering correctly after hard reload; no console errors

## Do NOT redo
- Don't re-run `extract_panels.py` — main.js is now in its post-extraction state (4189 lines)
- Don't re-extract lib/ modules — committed in s132 (7bbf032)

## What's next
1. **Phase 3.2** — CSS split: `web/css/panels/*.css` with `@import` in main CSS (short session)
2. **Phase 3.3** — `web/js/lib/state_schema.js` JSDoc typedef codegen from `api_schema.py` (deferred until Phase 3 panels proven stable)
3. **Phase 4 remaining** — dispatch-level POST validation in `dashboard/_dispatch.py` (low priority)
4. **Vision regions calibration** — blocked on live game

---

# s132 wrap — 2026-05-08 (Phase 3.1 — ESM module split, lib/ extraction)

## What shipped
- **`web/index.html`**: `<script type="module" src="/js/main.js">` (sim.js stays regular script to patch fetch/WS before module eval)
- **`web/js/main.js`** (new, 8225 lines): `dashboard.js` IIFE unwrapped; import block at top; all lib/ duplicates removed
- **`web/js/lib/helpers.js`** (new): `_to12`, `el`, `safe`, `fmtList`, `fitText`, `logLine`, `isArenaPayload`, `classifyAction`, `_opGlyph`, `_formatRelativeAge`
- **`web/js/lib/state.js`** (new): `state`, `CADENCE`, `VIEW_IDS`, `VIEW_LABELS`, `_VIEW`
- **`web/js/lib/items_index.js`** (new): `ITEMS`, `ITEM_COSTS`, `CHAMPS`, `SPELLS` + all resolver fns + async loaders; dispatches `rc:items-ready` event
- **`web/js/lib/idempotent_render.js`** (new): `idempotentRender`, `makeSig`
- **Commit `7bbf032`** pushed → origin/main.

## Key decisions
- No bundler — native ESM, Edge 89+ compatible (Game-PC is current Edge).
- `sim.js` as regular script before the module: guarantees fetch/WS patches visible to module at eval time.
- Race fix (`_lastItemBuildState` re-drive) preserved via `rc:items-ready` custom event listener — avoids circular dep (items_index can't import `renderItemBuild`).
- `dashboard.js` kept in place (unmodified) as the prior-art reference.

## Verification
- `node --check web/js/main.js` → SYNTAX OK
- All 4 lib/ modules + main.js: HTTP 200 from RC
- No error entries in RC log after serving the new module

## Do NOT redo
- Don't re-extract lib/ helpers — all 4 modules are committed and verified.
- Don't modify `dashboard.js` — it's the reference; only `main.js` is the active file.

## What's next
1. **Phase 3.1 continuation** — extract individual panels into `web/js/panels/*.js` (right_now, next, item_build, map_state, champ_select, bridge_pending, dev). Each is a 300–600 line block.
2. **CSS split** — `web/css/panels/*.css` with `@import` in main CSS (can be a separate short session).
3. **JS typedef codegen** — `web/js/lib/state_schema.js` from `api_schema.py` (deferred until Phase 3 panels done).
4. **Phase 4 remaining** — dispatch-level POST validation (low priority).

---

# s131 wrap — 2026-05-08 (TFT 17.3 patch update)

## What shipped
- **`tft/tft_pbe_data.py`**: header bumped to 17.3. Morgana moved from 5-cost → 4-cost. Anima (6) note updated (loot every combat). Stargazer note updated (HP regen rework). Marauder note updated (omnivamp nerfed all tiers). Encounters: Double Duplicators (Tiny/3-5), Reroll Start (8→5 rerolls). META_COMPS updated: AP Vanguards/Redeemer/Anima rise; Primordian moved to B ("AVOID").
- **`tft/tft_pbe_engine.py`**: System prompt updated to 17.3. PATCH 17.3 CHANGES block added. KEY CARRIES updated (Morgana 4g, AP carries noted as buffed). META S-TIER COMPS updated. NEVER list: added Horizon Focus (removed from game) + Primordian vertical. Trait notes updated (Anima, Stargazer, Marauder).
- **Commit `0e9617b`** pushed → origin/main. 380 tests pass, py_compile clean.

## Key 17.3 changes captured
- Morgana: 5→4 cost (Magic Tank) — Redeemer comp more accessible
- Anima (6): loot every combat (was: wins only)
- Stargazer: reworked to HP regen + stacking stats; Fountain removed
- Marauder: omnivamp nerfed (20→18%, 40→35%, 60→55%)
- Apex Primordian gutted (AS/armor/MR/grid damage all slashed) — comp is dead
- AP carries buffed: Aurelion Sol, Karma, LeBlanc, Sona
- Horizon Focus removed from game
- Encounters: Double Duplicators (Tiny, 3-5), Reroll Start (8→5 rerolls)

## Do NOT redo
- Don't re-update TFT files — 17.3 is current as of commit 0e9617b.
- Don't re-run tests — 380 pass clean.

## What's next
1. **Phase 4 remaining** — dispatch-level POST validation in `dashboard/_dispatch.py` (low-priority; read-path covered).
2. **Phase 3** — frontend ESM split (`dashboard.js` 8507 LOC). Next major futureproofing phase.
3. **Vision regions calibration** — blocked on live game.


