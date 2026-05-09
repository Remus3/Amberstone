# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s123 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s129 wrap — 2026-05-08 (Phase 4 — Contracts/schemas partial DONE)

## What shipped
- **`core/coaching_payload.py`** (new): pydantic v2 models for all 5 coach modes — `AramPayload`, `ArenaPayload`, `BrawlPayload`, `SrPayload`, `TftPayload`. All use `extra="allow"`. `validate_coaching_payload(data)` dispatches by mode, logs per-field warnings, never raises. Called in `dashboard/_state_builder.build_state()` on every `/api/state` read.
- **`dashboard/api_schema.py`** (new): outer HTTP API shape models — `StateResponse`, `HealthAllResponse`, `InputRequest`, `CommandRequest`, `DsPreviewRequest/Response`, `BridgeInboxRequest`, `SpeakRequest`, `OkResponse`, `ErrorResponse`.
- **`core/bridge_envelope.py`** (new): `BridgeEnvelope` pydantic v2 model with `suggestions`, `body_path`, `claimed_by`, `ttl_at` fields; `is_expired()`, `to_wire()`, `parse_envelope()` helpers.
- **`docs/API.md`** (new): 40 routes across 15 route files (GET + POST), body schemas, descriptions.
- **Futureproofing plan** updated: Phase 5 archived (was unchecked), Phase 4 checkboxes filled + findings added.
- **Commit `31bbe4f`** pushed → origin/main.

## Key decisions
- `extra="allow"` on all coaching models — coaches add LLM-derived fields freely; schema only enforces declared types.
- Soft-validate on read in `_state_builder.py` (never raise, log warning) — keeps dashboard alive even if coach output drifts.
- 4.2 tool rewrites (12 bridge CLIs) **blocked** — `bridge_post_result.py` and `bridge_pull_tasks.py` are frozen. Needs same frozen-file approval as Phase 6.
- JS typedef codegen (`web/js/lib/state_schema.js`) deferred to Phase 3 (requires ESM split first).

## Do NOT redo
- Don't re-add coaching models — `core/coaching_payload.py` is complete with all 5 modes.
- Don't re-generate API.md — it's committed and up to date with all 15 route files.
- Don't re-run archmap — pre-commit hook ran it cleanly; archmap is in sync.

## What's next
1. **TFT 17.3** — due ~2026-05-12 (highest time priority). Same process as 17.2: update `tft_pbe_engine.py` + `tft_pbe_data.py` + meta JSON bump.
2. **Phase 4 remaining** — dispatch-level POST validation in `dashboard/_dispatch.py` (low-priority; read-path is already covered).
3. **Phase 3** — frontend ESM split (`dashboard.js` 8507 LOC). After that, JS typedef codegen from `api_schema.py` becomes viable.

---

# s128 wrap — 2026-05-08 (Phase 5 — CI gate + smoke harness COMPLETE)

## What shipped
- **`tests/snapshot_regressions/test_app_authority.py`** fixed: 52 → 0 failures. Root cause: `app` was refactored to use `StateAuthority` + `GameLifecycleManager`; headless stub didn't initialize them. Fix: `_HeadlessApp` subclass with `_current_envelope` property proxying `app.state.envelope`. Test count: 289 → 343 passing.
- **Arena/Brawl golden fixtures** added: `ARENA_STATE` + `BRAWL_STATE` in `state_dicts.py`, two golden JSON files, 10 new snapshot tests.
- **`tests/phase2_smoke/test_coach_state_parsing.py`** (new, 31 tests): smoke harness for all 5 coach modes — SR (`_build_user_prompt`), ARAM/Arena/Brawl (`_parse_state`), TFT (`_coach_board_to_placement`). No API calls.
- **CI** (`.github/workflows/ci.yml`): added `ruff` install + `ruff check .` step; added `phase8_smoke`; removed `--ignore=test_app_authority.py`. 380 tests pass in CI shape.
- **`ruff.toml`**: 101 → 0 violations. Added ignores for RC patterns (B904/B007/B027/E731/UP037); frozen-file per-file ignores (app/ F821, bridge tools UP/E/B); auto-fixed 51 mechanical issues.
- **Bug fix**: `tft/tft_live_analysis.py:274` — `_j.loads` → `_pj.loads` (would NameError if manual_level path hit).
- **Commit `d21f533`** pushed → origin/main.

## Key decisions
- `_HeadlessApp` subclass pattern (not monkey-patching OverlayApp) keeps production code clean.
- Coach smoke tests test the state-parsing layer (raw Riot API format), not the processed game_reader output. Phase 4.3 schema validation deferred.
- ruff frozen-file per-file-ignores prevent accidental `--fix` to `bridge_pull_tasks.py` etc.
- Branch protection on GitHub (`require CI "check" green`) left as manual UI action — chip created for next session.

## Do NOT redo
- Don't re-fix test_app_authority.py — all 54 tests now pass.
- Don't re-run ruff --fix — 0 violations, nothing to fix.
- Don't re-add arena/brawl golden files — already checked in.

## What's next
1. **TFT 17.3** — due ~2026-05-12 (highest time priority). Same process as 17.2.
2. **Phase 4** — Contracts/schemas: pydantic `api_schema.py` + coaching payload. Next in futureproofing order.
3. **Branch protection** — enable in GitHub UI: Settings → Branches → require status check "check".

---

# s127 wrap — 2026-05-08 (Phase 2.1 — champion_profiles.py split COMPLETE)

## What shipped
- **`champion_profiles.py`** shrunk from 902 → 29 LOC. Now a thin JSON loader.
- **`data/champion_profiles/*.json`** — 168 champion files, each a flat dict with `dmg/role/mana/sustain/mechanic/aram` fields. All checked in.
- **`scripts/extract_champion_profiles.py`** — one-shot migration helper left in tree as migration doc.
- **`docs/ARCHITECTURE.md`** — god-module table updated; archmap regenerated via pre-commit.
- **`ROADMAP.md`** — Phase 2.1 ✅ Done.
- Commit **8fa11f4** pushed → origin/main (172 files changed: 1399 insertions, 906 deletions).

## Key decisions
- Thin loader stays at **root `champion_profiles.py`** (not `core/`). `ops/rc_dev_runtime.py` (frozen) watches `"champion_profiles"` as a module-name string — moving it would require a frozen-file edit. Zero caller changes.
- Import surface preserved exactly: 12 module-level exports (`CHAMPIONS, TANKS, FIGHTERS, MAGES, ASSASSINS, MARKSMEN, SUPPORTS, AD_CHAMPS, AP_CHAMPS, HYBRID_CHAMPS, SUSTAIN_CHAMPS, MANA_CHAMPS`).
- Pre-existing test failure in `tests/snapshot_regressions/test_app_authority.py` is unrelated — confirmed via git stash; 289 other tests all pass.

## Do NOT redo
- Don't re-run the extractor — 168 JSONs already committed. It's idempotent but unnecessary.
- Don't re-backfill `# arch:` header on `champion_profiles.py` — already updated to "thin loader".

## What's next
1. **Phase 5** — CI + smoke harness (cheapest regression insurance; recommended before Phase 2.2+).
2. **TFT 17.3** — due ~2026-05-12 (higher time priority).
3. **Phase 4** — Contracts/schemas (pydantic `api_schema.py` + coaching payload).


