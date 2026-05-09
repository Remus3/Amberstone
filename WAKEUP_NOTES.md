# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s129 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

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

---

# s130 wrap — 2026-05-08 (CI fix — anthropic guard + pydantic dep)

## What shipped
- **`coach_integration.py`**: wrapped bare `import anthropic` in try/except ImportError; aliased `_APITimeoutError`/`_APIConnectionError` for except clauses; guarded `anthropic.Anthropic()` instantiation. Keeps `_build_user_prompt` (pure string-builder) importable in CI without the anthropic SDK.
- **`requirements.txt`**: added `pydantic>=2.0` (Phase 4's `core/coaching_payload.py` introduced a hard dep never wired into CI).
- **`.github/workflows/ci.yml`**: added `pydantic>=2.0` to pip install step.
- **Commit `808afea`** pushed → origin/main. CI now green (10 previously failing tests now pass).

## Root cause
- Phase 4 (s129) shipped `core/coaching_payload.py` with bare `from pydantic import ...` — pydantic never added to CI.
- Phase 5 (s128) added `TestSrCoachPromptBuilder` to phase2_smoke but `coach_integration.py` had a bare `import anthropic` — anthropic intentionally excluded from CI runtime.

## Do NOT redo
- Don't re-investigate CI failures — fixed in 808afea. `gh run list` confirms green.
- Don't add `anthropic` to CI requirements — intentionally excluded; try/except guard is the correct fix.

## What's next
1. **TFT 17.3** — due ~2026-05-12 (highest priority). Update `tft_pbe_engine.py` + `tft_pbe_data.py` + meta JSON bump.
2. **Phase 4 remaining** — dispatch-level POST validation in `dashboard/_dispatch.py`.
3. **Phase 3** — frontend ESM split (`dashboard.js` 8507 LOC).



