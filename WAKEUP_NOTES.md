# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s131 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s135 wrap — 2026-05-08 (Phase 3.1 — CSS panel split)

## What shipped
- **`scripts/extract_css_panels.py`** (new): one-shot extractor — 13 sections by line-range, writes `web/css/panels/*.css`, rewrites `dashboard.css` as 25-line `@import` router.
- **`web/css/panels/`** (new): 13 panel CSS files — `base.css` (106 lines), `header.css` (1637), `grid.css` (463), `bridge_pending.css` (375), `map_state.css` (580), `right_now.css` (97), `next.css` (47), `item_build.css` (441), `input_activity.css` (506), `champ_select.css` (364), `home.css` (841), `primitives.css` (290), `dev.css` (54).
- **`web/css/dashboard.css`** (modified): 5812 → 25 lines (Google Fonts @import + 13 panel @imports).

## Key decisions
- `champ_select.css` merges two non-contiguous source ranges (lines 4264–4276 + 5118–5468); the home overlay CSS between them goes into `home.css`. Cascade order is safe — distinct class namespaces (`cs-*` vs `home-*`).
- Static handler `prefix("/css/")` already covers subdirs — no server change needed.

## Verification
- All 13 panel files + dashboard.css: HTTP 200 from RC.
- Game-PC dashboard screenshot: all panels render correctly, no layout regressions.

## Do NOT redo
- Don't re-run `extract_css_panels.py` — dashboard.css is now the @import router; re-running would split an already-split file.

## What's next
1. **Phase 3.2** — `tools/gen_state_schema.py` introspects `dashboard/_state_builder.py` → `web/js/lib/state_schema.js` JSDoc `@typedef` blocks + pre-commit hook sync.
2. **Phase 3.3** — Playwright snapshot tests (5 panels × 26 sim fixtures = 130 PNGs), wire to CI.
3. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
4. **Vision regions calibration** — blocked on live game.

---

# s134 wrap — 2026-05-08 (null session — no work done)

## What shipped
- Nothing. Session opened with `/done` immediately.

## RC state at close
- pid=1108, alive=True, last_reload_ok=True
- mode_key=client, lcu_phase=Unknown (not in game)
- No unpushed commits. No pending lessons.

## What's next
1. **Phase 3.2** — CSS split: `web/css/panels/*.css` with `@import` in main CSS
2. **Phase 3.3** — JS typedef codegen from `api_schema.py` (deferred until Phase 3 panels proven stable)
3. **Phase 4 remaining** — dispatch-level POST validation (low priority)
4. **Vision regions calibration** — blocked on live game

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
