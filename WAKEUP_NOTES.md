# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s135 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s138 wrap — 2026-05-09 (Phase 2.3 — coach_integration split)

## What shipped
- **`coach_integration/` package** (new): split `coach_integration.py` (1225 LOC, `\r\r\n` line-ending artifact) into `_profiles.py` (181 LOC), `_sr_prompt.py` (455 LOC), `_coach.py` (607 LOC), `__init__.py` (6 LOC facade). All frozen-file callers (`app/__init__.py`, `main.py`) unchanged.
- **`tools/build_portable.py`**: removed `"coach_integration.py"` from `_ROOT_PY_FILES`, added `"coach_integration"` to `_SOURCE_PACKAGES`.
- **`docs/ARCHITECTURE.md`**: archmap regenerated for new package sub-modules.
- **FUTUREPROOFING_PLAN.md** (`Desktop`): Phase 3.3 and Phase 2.3 marked done; status table updated.
- 386 tests pass, ruff 0 violations.

## Key decisions
- Actual structure was SR-only (not multi-mode dispatch) — planned `dispatch.py/budget.py/cache_keys.py/writers.py` split didn't match reality; used `_profiles/_sr_prompt/_coach` instead.
- File had `\r\r\n` double-CR endings making Python splitlines() double-count lines (2449 apparent, 1225 real). Stripped on extraction.
- Path fix: `Path(__file__).parent` → `.parent.parent` in `_sr_prompt.py` and `_coach.py` since files are now one level deeper.
- `main.py` (frozen) sets `_ci._APP_DIR = APP_DIR` — attribute injection onto package `__init__`; never READ, harmless.

## Do NOT redo
- Don't re-investigate the line-count discrepancy — it was `\r\r\n` endings, stripped at extraction.
- Don't try to put `CoachIntegration` in a smaller file — the class is naturally 578 lines.

## What's next
1. **Phase 2.2** — `game_reader.py` (1473 LOC) split into `core/game_reader/` package.
2. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
3. **Vision regions calibration** — blocked on live game.

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
