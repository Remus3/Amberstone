# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s173 wrap — 2026-05-12 (anti-drift audit run — 2 commits)

**audit run complete** — 2 pairs unified, ~30 min elapsed. Both green on first CI run.

Daytime execution of `HEADLESS_BRIEF_2026-05-12_AUDIT.md` (anti-drift hunt across 10 candidate pairs in the spirit of ADR-008). Risk profile LOW-MEDIUM: structural unification of independently-maintained lists/maps. Two pairs closed; six skipped (intentional difference, dead code, or already-unified); two deferred (frozen-touching or multi-language).

## Ships

| Commit | Theme |
|---|---|
| [3096e8c](https://github.com/Remus3/riot-commander/commit/3096e8c) | `refactor(supervisor):` defer post-game candidates to `_state_builder.MODE_FILES`. New `MODE_FILES: tuple[str, ...]` derived from `MODE_TO_FILE.values()` via `dict.fromkeys()` (deduped, insertion-order). `agents/supervisor._file_post_game_summary` now consumes it via local import (avoids module-load-order coupling) with a hardcoded fallback for dev runs that lack the dashboard package. Behavior byte-identical — same 5 paths in the same order. |
| [907543f](https://github.com/Remus3/riot-commander/commit/907543f) | `refactor(champ_select):` defer legacy dsMode ternary to `_csvDsModeFor`. The s164 view's `_csvDsModeFor` (4 branches inc. brawl) and the legacy cs-overlay's inline ternary (3 branches) both mapped mode → DS engine name. ESM hoisting cross-references the helper fine; substitution is byte-identical for all current `modeMap` outputs (which never produce "brawl" since modeMap covers SR queue_ids only and falls back to "aram"). |

## Hunt outcomes (10 of 10 examined)

| # | Pair | Outcome |
|---|---|---|
| 1 | `resolve_mode_key` (dashboard vs file_ingest) | **Already unified** — `agents/agent2_backend/file_ingest.py:50` imports from `dashboard._state_builder`. Single source of truth. Not a finding. |
| 2 | `WATCHED` + `MODE_TO_FILE` + supervisor candidates | **Unified — 3096e8c.** Three enumerations of the per-mode coaching JSON path set. WATCHED has different intent (WS broadcast labels, includes auxiliary tft_live_data + comp_state), `MODE_TO_FILE` is canonical mode→path, supervisor candidates was a third independent list now derived from MODE_FILES. |
| 3 | Frozen file list (CLAUDE.md vs `tools/process-bridge-tasks.md`) | **Skip — touches frozen.** Real drift (CLAUDE.md has 27 entries; the in-prompt skill spec has 14), but `tools/process-bridge-tasks.md` is itself frozen per CLAUDE.md. Operator approval required to unify. Logged as open audit finding below. |
| 4 | `VIEW_IDS` (state.js vs HTML sections vs CSS body[data-view] vs dashboard.js) | **No actionable drift.** `web/js/dashboard.js:445` carries a stale legacy list incl. "diagnostics/coach-calls/bridge-pending/fleet/loadouts" — but `web/index.html` only loads `js/main.js` (the ESM entrypoint that imports from `state.js`). dashboard.js is dead code in production; removing it requires updating multiple `agent3_testing` tests that read it as text. `dashboard/view_router_state.py:VIEW_IDS` is an explicit Python mirror with a docstring-flagged sync obligation. No clean single-commit unification. |
| 5 | `_csvDsModeFor` vs inline ternary | **Unified — 907543f.** |
| 6 | LCU phase "in-game-ish" checks (`_viewAutoDerive` vs `handleLcuEnvelope` vs `gamepc_lcu_agent.py`) | **Different intents.** `main.js:491-497` is a state machine for `_VIEW.gameStarted` sticky-tracking; `main.js:1908-1910` gates a button on "past lobby"; `main.js:4265` gates "lobby-ish" pre-match flow; `file_ingest._compute_effective_mode` overlays LCU phase onto health.mode. Each check selects a different phase set; no two are duplicating the same intent. Skip. |
| 7 | DS `ENGINE_VERSION` (code vs docs vs response) | **Skip — doc maintenance, not structural drift.** Code at 0.61.0 since s167; CLAUDE.md/DAEMON_SLAYER.md/ARCHITECTURE.md/README.md still say 0.60.0. The structural shape (one source in `__init__.py`, exposed via `/health`) is fine — docs just lag. Worth a one-line doc-sync commit but doesn't match the audit's "two implementations diverging" pattern. Logged as open finding. |
| 8 | LiveClient relay max-age (8.0/12.0/20.0) | **Intentional.** `poller.RELAY_MAX_AGE_S=12.0` has a fall-through-to-direct path; `decision_detector._RELAY_MAX_AGE_S=8.0` and `vision_tracker._RELAY_MAX_AGE_S=8.0` simply skip the tick. Different fall-through semantics — not the same intent. Skip. |
| 9 | Cache-buster URL format | **Already unified — s171.8 (ADR-008).** Both `inject_asset_hash` and `_serve_ui_version` defer to `compute_asset_hash`. No remaining drift. |
| 10 | Champion alias maps (`items_index.js` vs `daemon_slayer_extract.py` vs `dashboard.js`) | **Defer — multi-language unification.** Real drift across 3 hand-maintained tables (`wukong→MonkeyKing`, `renataglasc→Renata`, `nunuwillump→Nunu`), but unifying requires a new JSON source-of-truth + edits to one Python build tool + one JS runtime module + a key-normalization decision. Larger than one-commit scope. Logged as open finding. |

## Open audit findings (for next session)

1. **Frozen-file list drift** (Hunt 3) — CLAUDE.md frozen list (27 entries) vs in-prompt skill spec (14 entries) for `process-bridge-tasks`. The skill spec is in `tools/process-bridge-tasks.md` (frozen), or in a `.claude/` skill file (need to locate). Fix would either inline CLAUDE.md grep at skill execution time, or sync the static list. Operator decision required.
2. **DS `ENGINE_VERSION` doc-sync** (Hunt 7) — Bump CLAUDE.md:6, docs/DAEMON_SLAYER.md:5, docs/ARCHITECTURE.md:147, README.md:244 + :302, NEXT_SESSION_PLAN_2026-05-10.md:12 from `0.60.0` to `0.61.0`. One-line edits each, but they should be batch-updated when the next ENGINE bump lands (better: auto-inject via a doc-prelude step).
3. **Champion alias unification** (Hunt 10) — 3 hand-maintained tables. Proposal: add `web/data/champion_aliases.json` with `{"wukong":"MonkeyKing","nunuwillump":"Nunu","renataglasc":"Renata"}` keyed on lowercase-alphanumeric of the source name. `web/js/lib/items_index.js:_CHAMP_RENAME_OVERRIDES` reads it (fetch on first import or hardcode same constant). `tools/daemon_slayer_extract.py:_LOLMATH_TO_DDRAGON_ALIAS` reads it (apply lowercase normalization to lolmath camelCase keys before lookup). Bigger than one-commit scope; warrants its own session.

## Files touched this session

- `dashboard/_state_builder.py` (+7 lines: `MODE_FILES` tuple)
- `agents/supervisor.py` (+16 / −9 lines: candidates list deferred)
- `web/js/panels/champ_select.js` (+6 / −4 lines: ternary → helper call)
- `WAKEUP_NOTES.md` (this entry)

## Pending verification

🟡 **Live champ-select** — the Hunt 5 substitution is byte-identical at runtime for all current `modeMap` outputs, but a live SR draft / ARAM / Arena CS would reconfirm `_fetchDsPreview` fires with the correct mode label. The previous s171.7 cache-staleness already cleared so dashboard auto-reload should pick up `907543f` within one 4s poll cycle (footer hash should change).

---

# s171.8 wrap — 2026-05-12 (overnight docs+tests backfill — 5 commits)

**headless run complete** — 5 commits, ~10 min elapsed. Operator: run morning audit brief (`HEADLESS_BRIEF_2026-05-12_AUDIT.md`) when ready.

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
