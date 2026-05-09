# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s132 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s137 wrap — 2026-05-08 (Phase 3.3 — Playwright panel snapshot tests)

## What shipped
- **`tests/snapshot_panels/`** (new): 6-fixture Playwright harness — lobby/sr/aram/arena/brawl/tft × 4 panels = 24 screenshots per run.
- **`tests/snapshot_panels/conftest.py`**: `_MockServer` (ThreadingHTTPServer serving `web/` + fixture-driven `/api/*`), `pw_browser` session-scoped fixture, `_WS_STUB` JS snippet.
- **`tests/snapshot_panels/test_panel_snapshots.py`**: parametrized `test_panels[fixture]` — loads fixture, waits for `#rn-action` coaching text (or 800ms for lobby), asserts all 4 panels visible, screenshots each.
- **`.github/workflows/ci.yml`**: added `playwright install --with-deps chromium` step + `panel snapshot tests` step.
- Commit: **02ed835** pushed → origin/main.

## Key decisions
- Root cause of flaky failures: the dashboard's WebSocket connects to the **real supervisor on :8891** (not just the mock HTTP server). The real supervisor sends live `mode="client"` health/state, overriding the fixture and hiding `#item-build`. Fix: `_WS_STUB` injected via `page.add_init_script()` makes `window.WebSocket` immediately fire `onclose` without connecting.
- SSE format: the mock sends `store["data"]` (raw `StateResponse` JSON with `mode_key`) directly. The JS `setupStateStream()` reads `st.mode_key`, not a WS-style envelope wrapper.
- Arena/TFT: both pass cleanly once WS is stubbed. TFT doesn't use `#item-build` for build paths but the panel IS visible (CSS only hides it for `data-mode="client"`).

## Do NOT redo
- Don't re-investigate the `#item-build` visibility issue — it was the WS (:8891) overriding fixture. Stubbing WS fixed it in 02ed835.
- Don't try to remove the WS stub; it's intentional isolation for test determinism.

## What's next
1. **Phase 2.3** — `coach_integration.py` (1217 LOC) split into `coach_integration/` package.
2. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
3. **Vision regions calibration** — blocked on live game.

---

# s136 wrap — 2026-05-08 (Phase 3.2 — JSDoc typedef codegen)

## What shipped
- **`tools/gen_state_schema.py`** (new): introspects `dashboard/api_schema.py` + `core/coaching_payload.py` pydantic models; emits `web/js/lib/state_schema.js`. `--check` mode exits 1 if out of sync.
- **`web/js/lib/state_schema.js`** (new, generated): 12 `@typedef` blocks — `CoachPayload` union + 5 per-mode payloads (Aram/Arena/Brawl/Sr/Tft) + 6 HTTP shapes (StateResponse/HealthBlock/etc). `StateResponse.coach` overridden to `CoachPayload` type.
- **`web/jsconfig.json`** (new): `checkJs: false`, `include: js/**/*.js` — VS Code resolves imports without TypeScript compilation.
- **`.githooks/pre-commit`** (modified): schema sync check added after archmap check.
- **`docs/ARCHITECTURE.md`** (auto-updated): archmap regenerated for new `gen_state_schema.py` entry.
- Commit: **e65135c** pushed → origin/main.

## Key decisions
- Script introspects `model_fields[name].annotation` directly (pydantic v2 resolves string annotations from `from __future__ import annotations` at class creation time — always actual type objects).
- `StateResponse.coach` is `dict[str,Any]` in Python but overridden to `CoachPayload` in `_OVERRIDES` — this is the whole point of the typedef file.
- `export {}` at end of `state_schema.js` makes it an ES module (required for `@import` to work from other ESM files).

## Do NOT redo
- Don't re-run `gen_state_schema.py` manually if you just changed a pydantic model — the pre-commit hook will catch it and print the hint. Just run it once and commit.

## What's next
1. **Phase 3.3** — Playwright snapshot tests: 5 panels × 26 sim fixtures = 130 PNG snapshots, wire to CI.
2. **Phase 2.3** — `coach_integration.py` (1217 LOC) split into `coach_integration/` package.
3. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
4. **Vision regions calibration** — blocked on live game.

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
