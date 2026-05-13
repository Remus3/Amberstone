# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s184 wrap — 2026-05-13 (First-purchase archetype-mismatch soft-nudge — single commit pending)

**Operator instruction:** "restart rc - and then continue DS plan." Restart picked up s182+s183 code (pid 12144 from 20:23 — replaced the running pre-s182 supervisor); then the natural next bounded ship was the first item on the s176 Phase 3 deferral list: "first-purchase-mismatch soft-nudge." After s176 shipped the dispatcher + picker UI, s182 wired the coaches, s183 fixed the JS unit rendering — this slot closes the loop by surfacing a passive UX signal when the operator's actual first item drifts from their archetype intent.

## Ships

| File | Change |
|---|---|
| [core/archetype_mismatch.py](core/archetype_mismatch.py) | **NEW (~270 LOC).** Owns the evaluator + dedup cache. Public API: `compute_nudge_payload(coach, lc, lcu_snapshot, cs_archetype_pick) -> dict` (called once per /api/state); `dismiss_nudge(champion) -> bool` (operator clicked X); `reset_nudge_state()` + `get_nudge_state_snapshot()` (test + diagnostic). Module-level `_NUDGE_STATE: dict` + `_NUDGE_LOCK: threading.Lock` cache decisions per (champion, session_token). `NudgeResult` dataclass + `to_dict`. Item-filter denylist `_NON_SIGNAL_ITEM_IDS` covers ~28 IDs (boots, Doran's, trinkets, consumables, SR starters, jungle pets). Internals: `_first_completed_item_id`, `_session_token` (game_id → synthetic fallback), `_evaluate_dispatcher` (calls `rank_for_primary_archetype` top=15, returns `(is_mismatch, top_names[:3])` or None), `_engine_mode` (liveclient game_mode → DS engine token), `_build_message`. |
| [dashboard/_liveclient.py](dashboard/_liveclient.py) | Extended `liveclient_summary` to surface two new keys: `owned_item_ids` (parallel int-id list to `owned_items` names, same order — read from raw liveclient `allPlayers[me].items[].itemID`) + `game_id` (from `gameData.gameId` / `gameID` with `""` fallback). Both needed by `archetype_mismatch` — state-builder can't reverse-lookup an item name into an ID without a resolver, and the dedup token wants liveclient's gameId when present. |
| [dashboard/_state_builder.py](dashboard/_state_builder.py) | New 14-line block after the `cs_archetype_pick` stamp: `try: from core.archetype_mismatch import compute_nudge_payload; archetype_nudge = compute_nudge_payload(coach=coach, lc=lc, lcu_snapshot=lcu_snapshot, cs_archetype_pick=cs_archetype_pick) except Exception: archetype_nudge = {}`. Returns `archetype_nudge` next to `cs_archetype_pick` in the /api/state envelope. Exception-wrapped so a fault here can't break the /api/state hot path. |
| [dashboard/routes_archetype.py](dashboard/routes_archetype.py) | Two new routes: `_serve_archetype_nudge_get` (`GET /api/archetype-nudge` — diagnostic snapshot returns `{ok, state}`); `_serve_archetype_nudge_dismiss` (`POST /api/archetype-nudge/dismiss` — body `{champion}`, returns `{ok, dismissed, champion}`, 400 on missing/empty champion or non-dict body). GET_ROUTES + POST_ROUTES extended. Module-level imports for `dismiss_nudge` + `get_nudge_state_snapshot`. |
| [dashboard/api_schema.py](dashboard/api_schema.py) | Two new pydantic models: `ArchetypeNudgeDismissRequest(_ForbidExtra) { champion: str }`; `ArchetypeNudgePayload(_AllowExtra) { fired, phase, champion, primary, first_item_id, first_item_name, message, expected_items, session_token }` — documents `state.archetype_nudge` shape. |
| [tests/test_archetype_mismatch.py](tests/test_archetype_mismatch.py) | **NEW (~340 LOC, 40 tests).** `FirstCompletedItemIdTests` (9) + `SessionTokenTests` (4) + `EngineModeTests` (4) + `ComputeNudgeNoSignalTests` (5) + `ComputeNudgePendingTests` (2) + `ComputeNudgeFiredTests` (6 — happy + dedup + engine-down + re-eval-on-new-session + no-token-empty) + `DismissNudgeTests` (4) + `NudgeResultShapeTests` (1) + `EvaluateDispatcherTests` (5 — mock `core.daemon_slayer_client.rank_for_primary_archetype` boundary; no live DS server needed). |
| [tests/test_state_builder_archetype_nudge.py](tests/test_state_builder_archetype_nudge.py) | **NEW (~140 LOC, 5 tests).** Mocks `lcu_summary` / `liveclient_summary` / `read_json` / `get_archetype_for` / `compute_nudge_payload` at the boundary. Verifies `build_state()` includes `archetype_nudge` key (empty default), carries fired payload through, carries pending phase, returns `{}` on evaluator exception. |
| [tests/test_routes_archetype_nudge.py](tests/test_routes_archetype_nudge.py) | **NEW (~125 LOC, 9 tests).** `_StubHandler` captures `_send` calls — same pattern as `test_routes_ds_preview_scorer` (s183). GET 2 + POST 5 (happy / no-entry / 400 non-dict / 400 empty / 400 missing) + RouteRegistrationTests 2 (smoke test the matchers fire). |
| [CLAUDE.md](CLAUDE.md) | New item 40 (after s182 entry, since s183 / s184 ship in order). |
| [ROADMAP.md](ROADMAP.md) | New s184 entry above the s183 line. |
| Live runtime | RC restart at 20:23 (pid 12144) picked up s182+s183; second restart at 20:37 (pid 1360) picked up s184. `last_reload_ok=true` both times. DS server :8893 confirmed up via `curl http://127.0.0.1:8893/health` returning 0.69.0 (note: HTTP not HTTPS — different from :8888 dashboard). |

## Live validation

```
$ curl -sk https://127.0.0.1:8888/api/archetype-nudge
{"ok": true, "state": {}}

$ curl -sk -X POST -H "Content-Type: application/json" -d '{"champion":"NoSuchChamp"}' https://127.0.0.1:8888/api/archetype-nudge/dismiss
{"ok": true, "dismissed": false, "champion": "NoSuchChamp"}

$ curl -sk -X POST -H "Content-Type: application/json" -d '{}' https://127.0.0.1:8888/api/archetype-nudge/dismiss
{"error": "champion required"}

$ curl -sk https://127.0.0.1:8888/api/state | py -c "import sys,json; s=json.load(sys.stdin); print('archetype_nudge:', s.get('archetype_nudge')); print('cs_archetype_pick:', s.get('cs_archetype_pick'))"
archetype_nudge: {}
cs_archetype_pick: {}
```

Both are `{}` because no active game + no LCU champ-select pick — the field is wired, just no signal to populate it. The next CS pop + game start will exercise the full evaluator.

## Findings

- **Dispatcher-driven mismatch beat item-affinity heuristics.** Initial design floated a hand-curated item → archetype tag map. Final design just asks the dispatcher "would you have recommended this item in your top 15?" — per-champion meta sensitivity for free, no tag-table to maintain. The downside is one extra DS call per (champion, session) pair, but dedup keeps it to once per game.
- **`source="default"` filter prevented DDragon-tag-only nudges.** Without this gate, every game would fire a nudge for champions where the operator never opened the picker UI (because the DDragon Fighter→bruiser default vs operator's actual first IE = mismatch). The `source` field on `cs_archetype_pick` was already there from s176, designed for exactly this purpose. Wired as: skip eval unless source ∈ {user_cs, user_ingame, nudge}.
- **`mock.patch.dict(sys.modules)` + `sys.modules.pop` was a footgun.** First version of `test_returns_none_on_exception` did the pop-and-repatch dance to test ImportError handling. Side effect: when run before `test_coach_archetype_dispatch.py`, the dispatcher mocks didn't bind to the right module object, 8 tests failed downstream. Simplified to plain `mock.patch(side_effect=RuntimeError)` — the broad `except` in `_evaluate_dispatcher` catches it regardless. Faster + isolation-safe + same coverage.
- **`owned_item_ids` extension was a 2-line liveclient change.** Already had `owned_items` as displayName list; just parallel-walk `me_pl.get("items")` for `itemID`. Same order, same length. No frontend changes needed (yet).
- **In-memory dedup vs file-persisted.** Considered `data/archetype_nudge_state.json` for restart-survival; rejected because RC restarts are common (`restart_trigger.txt` ~daily during dev) and a nudge dismissed last session has zero relevance next session. Module-level dict wins for simplicity + zero I/O. Operator's chip-dismiss survives across /api/state polls but not across restarts.

## Verification

- `py -m pytest tests/test_archetype_mismatch.py tests/test_state_builder_archetype_nudge.py tests/test_routes_archetype_nudge.py -v` → **54 passed**
- `py -m pytest tests/` → **1009 passed** (was 955 in s183 wrap; +54 new)
- `py -m pytest agents/daemon_slayer/tests/` → **1426 passed** (unchanged — DS engine math untouched)
- `py -m pytest tests/snapshot_panels/` → **11 passed** (panel JS render unchanged)
- `py -m py_compile core/archetype_mismatch.py dashboard/_state_builder.py dashboard/_liveclient.py dashboard/routes_archetype.py` → clean
- `py -m ruff check core/archetype_mismatch.py dashboard/_state_builder.py dashboard/_liveclient.py dashboard/routes_archetype.py tests/test_archetype_mismatch.py tests/test_state_builder_archetype_nudge.py tests/test_routes_archetype_nudge.py` → All checks passed
- RC restart (pid 12144 → pid 1360) verified via /api/state shape

## Open items carried forward

- 🟡 **JS chip renderer — s184.1.** Needs a small yellow info-style chip near `#ds-pill` (in `web/js/panels/item_build.js`) that polls `state.archetype_nudge.fired === true` + shows `state.archetype_nudge.message` + an X button calling `POST /api/archetype-nudge/dismiss {champion}`. Pattern: same as `#ds-pill` itself (mode-gated, fade-in on first appearance). Estimate ~50 LOC + snapshot test.
- 🟡 **Live game validation.** No game ran during s184 — the new eval logic is exercised only by unit tests. Next real CS + game start will validate: (a) `lc.owned_item_ids` actually populates from Game-PC liveclient relay; (b) `lc.game_id` actually populates (depends on Riot's LCU schema for current patch); (c) the dispatcher round-trip happens within /api/state's tick budget. Engine-down fault path is already proven.
- 🟡 **Calibration knob — top-15 threshold.** 15 is generous but arbitrary. After a few real games with fired nudges, the operator may want it tighter (top-10) or looser (top-20). Single constant `_TOP_N_THRESHOLD` in `archetype_mismatch.py`; trivial to retune.
- 🟡 **Item-filter denylist maintenance.** ~28 hardcoded IDs covering boots/Doran/trinkets/consumables/starters/jungle-pets. When Riot adds new items in next patch (16.10+), the list needs review — false-positive risk if a new starter or trinket isn't denylisted (would fire nudge for "I bought starter X first, did you mean to?").
- 🟡 **Per-game-session token edge case.** When liveclient `gameData.gameId` is absent (older LCU builds; first-tick race conditions), the synthetic fallback `{champion}@{start-floor-min}` is stable across the typical 25-min game but rolls over per minute if `game_time_s` drifts. In practice the real signal arrives mid-game when items complete — by that point `gameId` is populated. Minor edge case; flagging for awareness.
- 🟡 **Pre-existing carry-forwards from s183 remain:** Phase 6.5/5.5/4d calibration follow-ups blocked on rewind_history.db freshness; Audit finding #1 (frozen-file list duplication) needs operator approval.

---

# s183 wrap — 2026-05-13 (Dashboard JS scorer-aware unit rendering — single commit pending)

**Operator instruction:** "continue ds plan" — following s182's coach-dispatch wire-in, the most user-visible carry-forward was: "dashboard JS `#ds-pill` + `#cs-ds-block` + active-match panel still render `+Ndps` for non-DPS scorers (numerically right, label drift)." This session closes that drift. The archetype-expansion plan is archived; this is the immediate UX follow-up.

## Ships

| File | Change |
|---|---|
| [web/js/lib/scorer_units.js](web/js/lib/scorer_units.js) | **NEW (~35 LOC).** Single source of truth for the scorer → unit suffix mapping on the JS side. Mirrors the Python `_UNIT_SUFFIX` table in `coach_integration/archetype_dispatch.py:52-59` (s182): `dps`→"dps" / `ehp`→"ehp" / `hybrid`→"%" / `ability`→"adps" / `burst`→"burst" / `hps`→"hps". Exports `scorerUnit(scorer)` (single value lookup with empty-string + null tolerance + fallback to "dps") + `formatDsDelta(row)` (reads `row.delta_dps` || `row.delta`, rounds, appends `scorerUnit(row.scorer)`). Module-level `SCORER_UNIT` table kept private. |
| [web/js/lib/state_schema.js](web/js/lib/state_schema.js) | `DsPreviewItem` typedef gains optional `scorer` field; `DsPreviewResponse` typedef gains optional `scorer` + `archetype` siblings. JSDoc only — no runtime change. |
| [web/js/panels/item_build.js](web/js/panels/item_build.js) | Two callsites swapped from inline `` `+${Math.round(r.delta_dps)}dps` `` to `formatDsDelta(r)`: (a) DS chip strip rendering inside `#ib-ds-block` — chips show `Helia +25hps` for enchanter, `Warmog's +1690ehp` for tank, etc.; (b) `#ds-pill` top-pick render — pill flips unit suffix based on `top.scorer`. `dsPicks[0]` is sufficient for the pill because all rows in `daemon_slayer_picks` share the same scorer (set by `coach_integration/archetype_dispatch._build_display_rows`). New ESM import of `formatDsDelta` at module top. |
| [web/js/panels/next.js](web/js/panels/next.js) | One callsite — Next-panel Build-row fallback when coach hasn't emitted `item_extra`/`objective`. `DS: <name> +Ndps (Ng)` now uses `formatDsDelta(_dsTop)` so a Soraka game shows `DS: Helia +25hps (2200g)` not `DS: Helia +25dps`. ESM import added. |
| [web/js/panels/active_match.js](web/js/panels/active_match.js) | One callsite — `_dsIcon` tooltip (`title` attribute) flips unit. The on-icon `+N` caption is intentionally left dimensionless (small font, mode-gated visual, scorer-aware unit on hover is enough). ESM import of `scorerUnit` (not `formatDsDelta` since the round-to-int + sign-prefix is already inline). |
| [web/js/panels/champ_select.js](web/js/panels/champ_select.js) | Two callsites in the CS preview tiles + Build Chooser. (a) `_fetchDsPreview` → reads `data.scorer` from the response envelope (post-s182 top-level field) + falls back per-row to `r.scorer` (post-s183 per-row stamp); `reasons[r.item_name] = "+" + Math.round(r.delta_dps) + " " + u`. (b) `_csvBuildVariantsFor` Build Chooser → cache stores just `data.ranked`, so per-row `r.scorer` is the load-bearing field; uses `scorerUnit(r.scorer)`. ESM import of `scorerUnit` added at top. |
| [dashboard/routes_state.py](dashboard/routes_state.py) | `_serve_ds_preview_post` `result` dict comprehension stamps `"scorer": scorer` on every row of the `ranked` response array (mirrors the `display_rows` shape from `coach_integration.archetype_dispatch._build_display_rows`). The top-level `scorer` field was already present from s182; this closes the gap for callers that cache just the rows (champ-select `_CSV_DS_CACHE`). |
| [dashboard/api_schema.py](dashboard/api_schema.py) | `DsPreviewRequest` gains optional `archetype: str = ""` (s182 backfill — was already accepted by the route but not documented). `DsPreviewItem` gains `scorer: str = "dps"` (new in s183). `DsPreviewResponse` gains `scorer: str = "dps"` + `archetype: str = "carry"` (s182 backfill). Pydantic models are soft-validators (warn-only); these fields stay optional so older callers don't break. |
| [tests/test_routes_ds_preview_scorer.py](tests/test_routes_ds_preview_scorer.py) | **NEW (~190 LOC, 7 tests).** Stub HTTP handler captures `_send` calls; dispatcher boundary mocked so no live DS server needed. Cases: carry/tank/enchanter/hybrid all stamp `scorer` on every row; archetype override propagates from request body through response; empty `ranked` still returns well-formed envelope; engine-down returns 503 not 200-with-empty. |
| Living docs sync | [CLAUDE.md](CLAUDE.md) item 39 (new); [ROADMAP.md](ROADMAP.md) s183 ship entry. |
| Live runtime | **No DS server restart needed** — only the routes layer (`dashboard/routes_state.py`) + JS files changed; ENGINE_VERSION 0.69.0 unchanged on :8893. **RC supervisor restart still pending from s182** — operator's call. |

## Live validation

`node --check` clean on all 6 touched JS files. Backend test suite 955 passed (was 948 in s182 wrap — +7 new). Panel snapshot suite 11 passed. Ruff clean on the 3 touched Python files.

Operator can verify the unit flip live after `echo restart > restart_trigger.txt` picks up s182+s183 changes by browsing to `https://legion-rc:8888/?cs=1` mid-champ-select with a Soraka pick — `#cs-ds-block` tooltip should read `Helia +25 hps` not `Helia +25 dps`. Same on `#ds-pill` once a game ships with `daemon_slayer_picks[i].scorer="hps"`.

## Findings

- **Per-row `scorer` field beat per-response `scorer` for cacheable rendering.** The `_CSV_DS_CACHE` in `champ_select.js` stores only `data.ranked` (the rows, not the response envelope), so without per-row scorer the Build Chooser had no way to map a cached row back to its scorer. The s182 top-level field is correct but insufficient. Stamping `scorer` on each row mirrors the `display_rows` shape from `coach_integration.archetype_dispatch._build_display_rows` — uniform consumption across `daemon_slayer_picks` (coach output) and `/api/ds-preview` (CS preview).
- **`dashboard.js` is dead code.** Grep found 2 hardcoded "dps" strings in `web/js/dashboard.js`, but `web/index.html` only loads `/js/main.js?v=...` (which imports the panel modules), not `dashboard.js`. Skipped the dead-code edits — touching it would have shipped a no-op + bloated the diff. Confirmed by `grep dashboard.js web/index.html` returning only an unrelated comment reference.
- **`r.scorer` defaults to `"dps"` when missing — wrong unit but matches pre-s182 status quo.** `scorerUnit()` falls back to "dps" on null/empty/unknown scorer string. So pre-s182 supervisors (RC pid 15428 still running) emit `daemon_slayer_picks` without `scorer` → JS renders "+Ndps" exactly as before. Once the supervisor restart picks up s182's `display_rows` (which stamps `scorer`), the pill flips unit correctly. Zero risk of regression on the pre-s182 path.
- **`_dsIcon` caption stayed dimensionless.** The on-icon `+N` is a 11px font glanceable cue; adding a 4-char unit suffix would have crowded the 48px-wide cell. Tooltip carries the full `+Nunit` form via `formatDsDelta`-style construction inline. Operator-visible after hovering — adequate for the rare moment they need to disambiguate dps-vs-ehp on a glanceable strip.
- **DS preview cache stores rows, not envelope** is the same pattern as `_CSV_DS_CACHE` in the s171.8 Build-variant persistence work. Both rely on per-row fields rather than per-response fields. Future schema additions should follow this rule unless the data is genuinely once-per-fetch.

## Verification

- `py -m pytest tests/test_routes_ds_preview_scorer.py -v` → **7 passed**
- `py -m pytest tests/` → **955 passed** (was 948 in s182 wrap — +7 new; no regressions)
- `py -m pytest tests/snapshot_panels/` → **11 passed** (panel JS render unchanged)
- `py -m py_compile dashboard/routes_state.py dashboard/api_schema.py tests/test_routes_ds_preview_scorer.py` → clean
- `py -m ruff check dashboard/routes_state.py dashboard/api_schema.py tests/test_routes_ds_preview_scorer.py` → All checks passed!
- `node --check` on all 6 touched JS files → all OK
- DS server `:8893/health` → ENGINE_VERSION 0.69.0 unchanged (no engine code changed)

## Open items carried forward

- 🟡 **RC supervisor restart still pending from s182.** Running pythonw (pid 15428, booted 2026-05-13T00:52, hours before s182 commits) uses pre-s182 code; `state.cs_archetype_pick` is `None` in /api/state + coaches still call `rank_for()` directly. Operator can `echo restart > restart_trigger.txt` to pick up s182 + s183 together. Until then, `daemon_slayer_picks[i].scorer` is absent → JS falls back to "dps" suffix → status quo.
- 🟡 **DS server :8893 down.** Server was alive at session-start rc_facts probe (14:32 UTC) but `curl` returned schannel SEC_E_INVALID_TOKEN by the time s183 work started. Not related to this session's code — likely socket-level state from earlier in the day. Operator can relaunch via `Start-Process pythonw tools\start_daemon_slayer.py` per `reference_ds_server_not_supervisor_watched`. `/api/ds-preview` returns 503 cleanly when DS is down (verified by the new `test_engine_down_returns_503`).
- 🟡 **Calibration analysis pickup.** `core/ds_calibration` `ds_picks` rows now carry `scorer` per-row (s182 backfilled the field in `display_rows`; s183 didn't touch the calibration writer). Downstream `scripts/postmortem_analyze.py` consumers see it as additive — no breaking change, but they could disambiguate non-DPS scorer outcomes when ADR-007 phase 2 lands.
- 🟡 **Phase 6.5 / 5.5 / 4d calibration follow-ups.** Same gates: real ally-state plumbing, champion-spell healing throughput, per-champion combo templates JSON, etc. Blocked on `rewind_history.db` freshness (newest match 2025-12-16, 5 games since Dec).
- 🟡 **Audit finding #1 — frozen-file list duplication.** Still open from s173. Both `tools/process-bridge-tasks.md` and CLAUDE.md hard-code the same list; needs operator approval to refactor because both files are frozen.

---

# s182 wrap — 2026-05-13 (Coach archetype dispatch wire-in — single commit pending)

**Operator instruction:** "continue ds plan" — following s181's Phase 6, the archetype-expansion plan was complete on the engine side but the cross-phase coach-integration deferral was still open across all 6 phases. Every phase wrap noted: "no coach reads `state.cs_archetype_pick.primary` yet." This session closes that gap.

The dispatcher (`rank_for_primary_archetype()`) has been callable since s176 (Phase 3 shipped the UI + REST endpoint + dispatcher), but the actual coach pipelines were still calling `daemon_slayer_client.rank_for()` directly — the auto-attack DPS scorer regardless of the operator's pick. After this session, all 4 mode coaches consume a new helper that resolves the archetype + dispatches to the right scorer.

## Ships

| File | Change |
|---|---|
| [coach_integration/archetype_dispatch.py](coach_integration/archetype_dispatch.py) | **NEW (~210 LOC).** Exports `dispatch_for_coach(champion, *, mode_engine, level, item_ids, enemy_stats, augments=None, top=5, timeout=None)` + `CoachDispatchResult` dataclass + `display_label(scorer)` helper + module-level `_UNIT_SUFFIX` + `_DISPLAY_LABEL` tables + internal `_row_delta` / `_build_picks_str` / `_build_display_rows`. Returns `None` for empty champion or engine-down; otherwise `CoachDispatchResult` with raw `out` (dispatcher dict), `archetype`, `scorer`, `rows` (raw `out["ranked"]`), `picks_str` (scorer-aware: "dps"/"ehp"/"%"/"adps"/"burst"/"hps" suffix; hybrid uses `hybrid_delta_pct × 100`), `display_rows` (legacy 4-field shape `{id, name, delta_dps, gold}` preserved + new `delta` + `scorer` fields). `delta_dps` on non-DPS scorers carries the scorer's primary delta — numerically correct, label drift on dashboard JS deferred. |
| [coaches/aram_coach.py](coaches/aram_coach.py) | Swapped DS-before-Haiku block to import `dispatch_for_coach` + `display_label`, call helper instead of `_ds_client.rank_for()`, write `cur["daemon_slayer_picks"] = _ds_dispatch.display_rows` directly. Template `_USER_TMPL` gained `{ds_label}` placeholder so prefix is `DS top items ({ds_label} ranked, own-items-accounted): {ds_picks}`. Calibration log passes `scorer` field through. |
| [coaches/arena_coach.py](coaches/arena_coach.py) | Same swap pattern. Template `_USER_TEMPLATE` gained `{ds_label}`. Augments still propagate. |
| [coaches/brawl_coach.py](coaches/brawl_coach.py) | Same swap pattern. Inline f-string at line 433 uses `{_ds_label}`. `engine_mode` still threads through to `mode_engine`. |
| [coach_integration/_coach.py](coach_integration/_coach.py) | SR coach swap. `self._last_ds_rows` now stored as `display_rows` (list of dicts) instead of `RankedItem` dataclasses. `_pending_ds` downstream block simplified to `current["daemon_slayer_picks"] = list(_pending_ds)` (was a dict transform). User-prompt label dynamic. |
| [dashboard/_state_builder.py](dashboard/_state_builder.py) | New `_active_champion(coach, lc, lcu_snapshot)` resolver (priority: liveclient.champion → coach.champion → lcu.champ_select.local_pick.champion_name → ""). `build_state()` stamps `state["cs_archetype_pick"]` from `core.archetype_picks.get_archetype_for(active_champion)`. Empty dict on no champion or exception path. Decorative for the picker UI; coaches resolve independently. |
| [dashboard/routes_state.py](dashboard/routes_state.py) | `_serve_ds_preview_post` swapped from `rank_for()` to `rank_for_primary_archetype()`. New optional `archetype` payload field (CS picker UI hover preview). Falls back to `get_archetype_for(champion).primary`. Response gains `scorer` + `archetype` siblings. `delta_dps` field in rows preserved (scorer-specific; hybrid scales). |
| [tests/test_coach_archetype_dispatch.py](tests/test_coach_archetype_dispatch.py) | **NEW (19 tests).** Empty/engine-down (3); DPS scorer (1); Tank EHP unit (1); Hybrid %-unit (1); Mage/Assassin/Enchanter unit suffixes (3); Empty ranked (1); Archetype resolution (2); Enemy-stats kwargs threading (1); display_label (2); InternalHelperTests (4). |
| [tests/test_state_builder_archetype_pick.py](tests/test_state_builder_archetype_pick.py) | **NEW (14 tests).** ActiveChampionResolverTests (10 — priority order, LCU variants, edge cases); BuildStateStampsArchetypePickTests (4 — stamps from liveclient + LCU pre-game + empty when no champion + error fallback to empty dict). |
| [docs/_archive/NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md](docs/_archive/NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md) | Plan doc archived. All 6 phases shipped (s174-s181) + coach integration shipped (s182). |
| Living docs sync | [CLAUDE.md](CLAUDE.md) DS pointer + new item 38; [README.md](README.md) Daemon Slayer bullet extended; [docs/DAEMON_SLAYER.md](docs/DAEMON_SLAYER.md) status line; [ROADMAP.md](ROADMAP.md) DS status table + s182 ship entry. |
| DS server runtime | **No restart needed** — ENGINE_VERSION 0.69.0 unchanged. Only coach-side dispatch path changed. `/health` confirms 0.69.0 still live on :8893. |
| RC supervisor restart | **Pending — operator-driven.** State-builder + coach changes are on disk; running pythonw hasn't reloaded. Drop `echo restart > restart_trigger.txt` when ready. Until then, `state.cs_archetype_pick` absent from /api/state + coaches still on pre-s182 path. |

## Live validation

Probed the helper end-to-end (Python-level) against the running DS server on :8893. All 4 archetypes route correctly:

```
Tank archetype=tank scorer=ehp
  picks: Warmog's Armor(+1690ehp,3100g) > Heartsteel(+1521ehp,3000g) > Kaenic Rookern(+1518ehp,2900g) > Jak'Sho(+...
Mage archetype=mage scorer=ability
  picks: Void Staff(+11adps,3000g) > Rabadon's Deathcap(+11adps,3500g) > Shadowflame(+10adps,3200g) > Mejai's(+9adps,...
Enchanter archetype=enchanter scorer=hps
  picks: Echoes of Helia(+25hps,2200g) > Ardent Censer(+15hps,2200g) > Staff of Flowing Water(+12hps,2250g) > Locket(...
Carry archetype=carry scorer=dps
  picks: Blade of The Ruined King(+69dps,3200g) > Trinity Force(+49dps,3333g) > Essence Reaver(+45dps,3050g) > ...
```

`build_state()` direct invocation confirms `cs_archetype_pick` key is in the state envelope. Live `/api/state` returns `{}` for the key (no active champion right now), confirming the new code is wired (key would be absent in pre-s182 build).

## Findings

- **The helper module pattern made the 4 coach edits surgical.** Each coach had ~30 LOC of dispatch + format + calibration-log boilerplate that was 95% identical. Moving the variable parts into a single helper call lets the coaches reduce to a 3-block sequence. The user-prompt label now reflects the actual scorer (`DS top items (EHP ranked, ...)` for tank). Future coach work gets the dispatcher for free.
- **`\r\r\n` line endings in 3 of 4 coach files blocked the Edit tool.** ARAM/Arena/Brawl have doubled-CR mojibake from a prior tool. Edit tool can't match across them. Workaround: `tmp_swap_coaches.py` + `tmp_swap_labels.py` did byte-level replacement preserving EOL. Worked cleanly. SR coach uses plain `\r\n` so Edit tool worked directly. Both temp scripts deleted after use.
- **`delta_dps` field name is the load-bearing legacy compat decision.** Dashboard JS reads `state.coach.daemon_slayer_picks[i].delta_dps` to render #ds-pill. Renaming outright would have broken the pill. Keeping the field name + populating with the scorer's primary delta means existing dashboard renders today (numerically right, label drifts on non-DPS scorers). Adding `scorer` + `delta` siblings unlocks follow-up JS update without breaking compat. Same pattern as s171 `local_cell` defensive coercion.
- **Empty dispatcher rows distinct from engine-down.** Helper returns `None` for engine unreachable + `CoachDispatchResult(rows=[], picks_str="none")` for engine-up-but-empty. Coaches write empty payload in both cases but picks_str differentiates: "unavailable" vs "none". Operator reading LLM tip can tell whether DS was down vs no improvements found.
- **The `_active_champion()` priority order is liveclient > coach > LCU.** Because (a) once a game runs, liveclient is canonical (LCU goes silent); (b) coach JSONs may be stale by milliseconds; (c) LCU CS local pick is the only signal pre-game. Returns "" only when all absent — state-builder degrades to "no archetype stamp" rather than guessing.

## Verification

- `py -m pytest tests/test_coach_archetype_dispatch.py -v` → **19 passed**
- `py -m pytest tests/test_state_builder_archetype_pick.py -v` → **14 passed**
- `py -m pytest tests/` → **948 passed** (was 915 — +33 new; no regressions)
- `py -m pytest agents/daemon_slayer/tests/` → **1426 passed** (unchanged — DS engine math unchanged)
- `py -m py_compile` on all touched files → clean
- DS server `:8893/health` → `engine_version: "0.69.0"` (unchanged)
- Live helper invocation: 4 archetypes route through correctly

## Open items carried forward

- 🟡 **RC supervisor restart needed.** Running pythonw is using pre-s182 code. Operator can `echo restart > restart_trigger.txt`. Until then: `state.cs_archetype_pick` absent + coaches use pre-s182 path.
- 🟡 **Dashboard JS scorer-aware unit rendering.** `#ds-pill` + `#cs-ds-block` + active-match panel render "+Ndps" for all scorers. Numerically correct; label drift only. Follow-up: read `daemon_slayer_picks[i].scorer` + dispatcher's `scorer`/`archetype` siblings on `/api/ds-preview` to render correct unit suffix.
- 🟡 **Calibration analysis update.** `core/ds_calibration` `ds_picks` rows carry `scorer` sibling. Downstream consumer scripts (Stage 5 / `scripts/postmortem_analyze.py` ADR-007) unchanged — they see the new field as additive extra dict key.
- 🟡 **Archetype-expansion plan archived.** `NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md` moved to `docs/_archive/`. All 6 phases + coach integration shipped.
- 🟡 **Phase 6.5 + 5.5 + 4d calibration follow-ups.** Real ally-state plumbing, per-champion combo templates JSON, per-champion max_priority/form_index overrides. Deferred; not blocking; gated on rewind_history.db freshness (last match 2025-12-16, 5 games since Dec).
- 🟡 **Audit finding #1 — frozen-file list duplication.** Still open from s173. `tools/process-bridge-tasks.md` hard-codes the list separately from CLAUDE.md. Both frozen; needs operator approval.
