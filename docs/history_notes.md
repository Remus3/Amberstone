# RC session history archive

Sessions older than the last 2–3 full sessions are progressively compacted here.
Current WAKEUP_NOTES.md keeps only the most recent 2–3 sessions.
Compaction rule: 3+ sessions old → 1-2 line summary entry below.

---

# s173.4 wrap — 2026-05-12 (orphan team-strip retirement, 1 commit)

**Operator-approved retirement** of the 2026-04-23 "Per-enemy alive/dead tiles" stack-of-ideas bullet from README. Three orphan render functions in `map_state.js` (`renderTeamTile`/`renderAllyStrip`/`renderEnemyStrip`) + ~155 lines of orphan CSS at `grid.css:198-352` + their main.js call site + `state.adaptCounterMap` writer/reader all deleted in one pass. No behavior change — strips early-returned `if (!row || !wrap) return;` on DOM IDs that didn't exist since the 2026-04-23 visual-space decision.

## Ships

| File | Change |
|---|---|
| [web/js/panels/map_state.js](web/js/panels/map_state.js) | -158 lines. Deleted `renderTeamTile` (~74 LOC), `renderAllyStrip` (~18), `renderEnemyStrip` (~21), `state.adaptCounterMap` init (2 sites), the `.respawn-timer` forEach in `_tickSpellCooldowns`, and `_snapshotSpells(p.enemy_spells)` (orphan-only feed). `_tickSpellCooldowns` selector simplified from `.tile-spell[data-cd-key], .self-spell[data-cd-key]` → `.self-spell[data-cd-key]`. Export list pared. Kept: `_snapshotSpells(p.ally_spells)` (feeds self-spell pill if data lands). |
| [web/js/main.js](web/js/main.js) | -14 lines. Dropped 3 orphan imports + the `state.adaptCounterMap` writer block + `renderEnemyStrip` re-render call at L1366. |
| [tools/extract_panels.py](tools/extract_panels.py) | Synced MAP_STATE_HEADER + MAP_STATE_FOOTER + PANEL_IMPORTS templates so re-running the extractor doesn't regenerate the orphans. |
| [web/css/panels/grid.css](web/css/panels/grid.css) | -155 lines. Deleted `.team-strip*`, `.team-tile*`, `.tile-spell*`, `.team-tile-wrap`, `.respawn-timer`, `@keyframes targetPulse`, `@keyframes enemyDangerPulse`. |
| [web/css/panels/header.css](web/css/panels/header.css) | +5 lines. Moved `@keyframes spellReady` from grid.css to here — it's used by `.self-spell.cd-ready-flash` (active code). |
| [web/css/panels/input_activity.css](web/css/panels/input_activity.css) | -2 lines. Dropped responsive overrides for `.team-tile` + `.tile-spell` from the narrow-viewport media query. |
| [README.md](README.md) | Removed the "### Possible follow-ups" section (header + intro + bullet — the bullet was the only entry). |
| `~/.claude/projects/.../memory/reference_orphan_team_strips.md` | Deleted (memory of the orphan code now stale; git captures the "why"). MEMORY.md index entry removed. |

## Findings

- **`@keyframes spellReady` was the only cross-file dependency inside the orphan block.** Header.css's `.self-spell.cd-ready-flash` rule referenced the keyframe by name. Moved the keyframe definition to header.css to co-locate with the live consumer. Visual behavior unchanged.
- **`web/js/dashboard.js` still carries duplicate orphan code** (renderTeamTile at L1844, renderAllyStrip at L1961, renderEnemyStrip at L1980, the writer at L3261-3264, etc.). Per s173.1 WAKEUP, dashboard.js is dead code (web/index.html only loads main.js) and will be cleaned wholesale on its eventual removal. Left untouched per that earlier decision; the working orphan in map_state.js (the live ESM module) is fully gone.
- **`state.adaptCounterMap` is no longer in the shared `state` object.** Only writer + reader pair was the orphan path. The `for (const c of (data.counters || []))` loop in main.js that fed it is also gone — its only purpose was to populate the map for `renderTeamTile`. The text-line counter rendering at L1367+ uses `data.counters` directly, unaffected.

## Verification

- `py -m pytest tests/ -q --timeout=60` → 839 passed (no regression from s173.3)
- `py -m ruff check .` → All checks passed
- Game-PC monitor 1 capture post-edit: dashboard renders cleanly, all 5 panels intact (Next / Right Now / Map State / Adaptation / Item Build), no JS console errors visible, layout unbroken. Strips weren't visible pre-edit either (early-return on missing DOM IDs); the visual result is identical.

## Open items closed this slot

- ✅ README.md "Per-enemy alive/dead tiles" bullet retired
- ✅ Orphan render functions in map_state.js eliminated
- ✅ Server-side `enemy_team` vs JS-side `enemy_comp` field-name drift moot (reader is gone)
- ✅ Memory `reference_orphan_team_strips` retired (now obsolete)

---

# s173.3 wrap — 2026-05-12 (audit finding #1 — config half closed + CI sync test, 1 commit)

**Operator-approved unification** of the second half of s173 finding #1: `tools/bridge_watcher_config.json` `legion.escalate_always` was carrying a 15-entry list (14 frozen + `restart_trigger.txt` sentinel) that lagged CLAUDE.md's authoritative 28-entry list by 14 paths. This was a real safety gap, not pure doc drift — the watcher's `_has_frozen_intent()` gate only checks paths listed in `escalate_always`, so a bridge auto-action task like "edit `tools/bridge_post_result.py` to add logging" would have slipped past the gate.

## Ships

| File | Change |
|---|---|
| [tools/bridge_watcher_config.json](tools/bridge_watcher_config.json) | `legion.escalate_always` grown 15 → 29 entries (28 CLAUDE.md frozen + `restart_trigger.txt`). Added `_escalate_always_doc` field pointing to the sync test. **Frozen file edit** per operator approval. |
| [tests/test_frozen_files_sync.py](tests/test_frozen_files_sync.py) (NEW) | 3 tests: (1) every CLAUDE.md frozen path appears in `escalate_always`; (2) any `escalate_always` extras must be on the `EXTRA_PROTECTED` allowlist (currently only `restart_trigger.txt`); (3) parser sanity check (≥20 paths). CLAUDE.md becomes de-facto SSoT enforced at CI time. |

## Findings

- **CLAUDE.md as de-facto SSoT chosen over a new `data/frozen_files.json` file.** Considered extracting the list to a shared data file with both CLAUDE.md and config.json deferring to it, but: (a) it would be one more drift surface, (b) the test already pins the existing two surfaces, (c) consumers (`bridge_watcher_actions.py` + `bridge_watcher_classify.py`) don't need to change. The simpler approach trades a richer architecture for one less file to maintain.
- **Game-PC and Peer `escalate_always` lists left alone.** They're separate node configs with different frozen paths (Game-PC's `C:\RC-Agent\*.py` agents; Peer's `restart_trigger.txt`-only). CLAUDE.md's frozen list is Legion-centric. If/when Game-PC develops its own analog of CLAUDE.md frozen lists (e.g., from gamepc_boot.ps1 hardening), the test pattern here is reusable.
- **`EXTRA_PROTECTED` is the test-side allowlist** for paths that should escalate but aren't source files. Currently only `restart_trigger.txt` (supervisor sentinel — operator writes are legit, bridge auto-action writes are not). If we ever add more sentinels, the test will require a one-line update there + a comment.

## Verification

- `py -m pytest tests/test_frozen_files_sync.py -v` → 3/3 passed
- `py -m ruff check tests/test_frozen_files_sync.py` → clean
- Full suite: `py -m pytest tests/` → 839 passed (was 836 — exactly +3 from this slot)
- Parser probe: CLAUDE.md=28 frozen · config=29 escalate · symmetric diff = `{restart_trigger.txt}` only

## Open items closed this slot

- ✅ s173 finding #1 fully closed (skill-spec half in s173.2; config half here)

---

# s173.2 wrap — 2026-05-12 (audit finding #1 — skill-spec half closed, 1 commit)

**Operator-approved unification** of the Legion `/process-bridge-tasks` skill spec's SAFETY GATE inline frozen list with CLAUDE.md's authoritative list. One-line prose edit; no behavior change, no test changes.

## Ship

| File | Before | After |
|---|---|---|
| [.claude/commands/process-bridge-tasks.md:9](.claude/commands/process-bridge-tasks.md) | SAFETY GATE quoted 14 entries (`main.py`, `core/log_setup.py`, …, `app/_game_lifecycle.py`) — a stale snapshot, 14 of CLAUDE.md's 28 entries. | "any file from CLAUDE.md's *Frozen files* hard-rule list (loaded into your context as project instructions — that list is authoritative; do not rely on a snapshot embedded in this skill)" — model already has CLAUDE.md in session context, so the gate auto-syncs forever. |

## Findings / scope clarifications

- **The s173 audit named the wrong file.** Hunt #3 in s173 wrote `tools/process-bridge-tasks.md` (the Game-PC variant — which actually has NO SAFETY GATE at all, only the Legion `.claude/commands/process-bridge-tasks.md` variant does). Drift was real but localized to the Legion skill spec. Audit finding cleanly closes; entry path corrected.
- **Three places ever carried the list, not two.** The full audit during this slot found: CLAUDE.md (28 canonical) · `.claude/commands/process-bridge-tasks.md` (14) · `tools/bridge_watcher_config.json` `legion.escalate_always` (15, with `restart_trigger.txt` extra). Peer's `tools/process-bridge-tasks-peer.md` had already migrated to the abstract phrasing ("any frozen file from Peer's CLAUDE.md hard-rule list") — that's the model copied here.
- **bridge_watcher_config.json deferred per operator** ("we can follow up with 2 later"). Different consumer ergonomics: it's read by a Python process at startup, can't parse markdown, and the file itself is frozen — proper unification needs `data/frozen_files.json` shared source + sync test + edit-to-frozen approval. Carried forward in the open-items list above.
- **`.claude/commands/` is gitignored** (`.gitignore:54` — "Local-only Claude / MCP config (may contain server URLs, tokens)"). The skill-spec edit is live on this Legion machine but not tracked; a fresh Legion clone would not inherit it. Two follow-up paths if durability matters: (a) seed a tracked canonical at `tools/process-bridge-tasks-legion.md` (mirroring the Peer pattern) and copy-on-deploy; (b) accept the local-only nature since the file lives alongside other local config. Operator decision deferred — added to carried-forward.

## Verification

No code changes; ruff/pytest not relevant. Skill re-load on next /process-bridge-tasks invocation will surface the new prose (the `system-reminder` skill load mid-slot already showed the updated text).

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

---

# s171 wrap — 2026-05-12 (LCU + DS + UX bug crawl — 8 commits)

Operator surfaced ~15 distinct issues across two duo-queue games, mostly LCU push gaps + in-game UX. Single biggest find: `lcuCmd`/`lcuPollResult` were referenced 22 times in `main.js` but never declared at module scope (regression from s133 38ac760 Phase 3.1 ESM split) — every Find Match / Cancel / queue-change click silently threw ReferenceError. Restored as module-local helpers. 8 commits shipped end-to-end with live verification at each stage.

## Ships

| Commit | Theme |
|---|---|
| [73b66ec](https://github.com/Remus3/riot-commander/commit/73b66ec) | s171 — `lcuCmd`/`lcuPollResult` restore + 6 new lobby LCU handlers (set_party_type/set_position_prefs/invite_player/create_practice_tool/promote_leader/kick_member) + 5 P&B commands to allowlist (set_pick_intent/set_ban_intent/request_position_swap/request_pick_order_swap/set_augment_intent) + new champ-select view lock button + DS-driven build chooser + post-CS view-routing sticky guard + Top 8 server-side persistence (`/api/top8`) + `/api/mains` backend (rewind_history.db join) + auto_accept default flipped True→False + championPickIntent hover fallback + Active Match step 4 map overlay (static SR/ARAM base + champion-dot canvas overlay + MIA badges + JG-gank warning) + DS icon URL fix (perk-images→item-icons) |
| [a4f81a9](https://github.com/Remus3/riot-commander/commit/a4f81a9) | s171.1 — active-match opt-in→opt-out (`?am=0` to opt out), render `coach.immediate` as RIGHT NOW (was being dropped), expand auto-clear stale-manual list |
| [8f78199](https://github.com/Remus3/riot-commander/commit/8f78199) | s171.2 — tighten active-match gate to phase=InProgress (was falling through to stale `state.mode` during champ-select), freshness guard in `renderActiveMatch` (clears stale Kai'Sa "Recall now…" between games) |
| [94cee62](https://github.com/Remus3/riot-commander/commit/94cee62) | s171.3 — `my_completed` from `sess.actions[][]` (was reading non-existent `myTeam[i].completed`, always False), surface `local_cell` (P&B fetch needed it for role resolution) |
| [8bae267](https://github.com/Remus3/riot-commander/commit/8bae267) | s171.4 — enemy-aware DS ranking. New `core/enemy_aware_stats.py` computes target_armor/_mr/_max_hp from liveclient `allPlayers[i].items[]` via ddragon_items.json stat lookup → passes to `rank_for()`. Verified live: vs early-game enemies → Stormrazor/IE top; vs synthetic 150 armor/2500 HP → Blade of Ruined King +101 dps top |
| [f00a8d7](https://github.com/Remus3/riot-commander/commit/f00a8d7) | s171.5 — target_stats caption in DS strip (`DS ENGINE · vs 95 armor · 63 mr · 2210 hp · live · 5 enemies`) |
| [8a90b73](https://github.com/Remus3/riot-commander/commit/8a90b73) | s171.6 — defensive-pick ranker. New `core/defensive_picks.py` classifies enemy team's threat profile (AD/AP/burst/tank, `_KNOWN_BURSTERS` set) → recommends from 22-item curated catalog (Plated/Randuin/Frozen Heart/Maw/Sterak/GA/Zhonya/etc.). DEFENSE row renders in BUILD pane when `burst_threat≥5 OR ad_threat≥7 OR ap_threat≥7` |
| [d12a330](https://github.com/Remus3/riot-commander/commit/d12a330) | s171.7 — champ-select view opt-in→opt-out so ARAM Mayhem operator sees the new view (lock button + ARAM bench + DS picks) without `?cs=1` |

## Game-PC redeploys this session

LCU agent redeployed 3 times via http.server :8765 dance (`reference_gamepc_http_server_redeploy.md`):
- pid 4636 → 7940 (s171 — 5 new commands + championPickIntent + auto_accept=False)
- pid 7940 → 6672 (s171.6 hop — promote_leader/kick_member added)
- pid 6672 → 1976 (s171.3 — `my_completed` from actions[] + local_cell)

Live pid 1976 confirmed running.

## Diagnosis-only finds (not bugs in our code)

- **Phase 3 supervisor mode-detector stale-lock**: after a game ended at 00:25:21, the supervisor stayed in `mode=client` for the entire next game's champ-select + loading because LCU lockfile check fails (Phase 3 runs on Legion, lockfile is on Game-PC). Decision detector + game poller both correctly gated their loops on the relay's `RELAY_MAX_AGE_S` (8s/12s). Recovery happens when the next game starts and `gamepc_liveclient_relay.py` pushes fresh data. **Not a regression** — but worth a next-session look if it recurs.
- **`gamepc_liveclient_relay.py` standby for :2999 — correct behavior.** League's :2999 LiveClient API only listens once `League of Legends.exe` is running (not `LeagueClient.exe`). Relay agent's SYN_SENT socket waits.

## Decisions / notes for next-session-you

- **`lcuCmd`/`lcuPollResult` are now at module scope in `main.js`** (line 39+). Don't add duplicates inside `_lobbyViewWireOnce` or similar — they'd shadow.
- **`activeMatchEnabled` / `loadingViewEnabled` / `champSelectViewEnabled` all default-on now.** All three accept `?<flag>=0` for opt-out + `localStorage.<key>='0'` for sticky. The view-router's auto-derive expects this — don't revert to opt-in without updating the derive chain.
- **`_VIEW.gameStarted` sticky guard** (`web/js/lib/state.js`) latches to `champ-select → game-start → in-progress`, only clears on stable post-game phases. Rides through transient phase=null/Lobby during CS→loading→game flip. Don't add a manual "reset on game start" — would re-introduce the flip-back-to-pregame-lobby bug.
- **`my_completed` derivation** in `gamepc_lcu_agent.py:_team_picks` walks `sess.actions[][]` for the local cell's pick action. **LCU's `myTeam[i]` has NO `completed` field** — historical reads were always False. Same gotcha applies if you ever need per-ally lock state.
- **`target_stats.source`** field in `/api/ds-preview` response distinguishes `live-items` / `explicit-override` / `mode-level-curve` / `default-zero`. UI hides caption when source=default-zero.
- **Defensive-pick threshold tuning**: currently `burst≥5 OR ad≥7 OR ap≥7`. If operator complains about DEFENSE row spam, raise burst threshold; if it under-fires, lower to 4.
- **Build-variant persistence is the last deferred item** (operator's "kaisa experimental" complaint). Currently the build chooser shows a single DS variant — no choice to persist. Requires re-introducing multi-variant + sessionStorage save + active-match read path. Substantial.

## Open items handed off

- 🟡 **Live ARAM Mayhem verification** — operator was entering CS at wrap. New champ-select view should auto-promote; ARAM bench + build chooser + lock button should be functional.
- 🟡 **Build-variant persistence** (champ-select → in-game) — deferred per above.
- 🟡 **Working-tree triage** (still unresolved from s168): `agents/_minimap_bbox.py` + `agents/supervisor.py` + `tests/fu01_minimap/test_http_override.py` carry pre-session FU01 refinement (extracted `parse_http_override` helper). Audit reports under `agents/agent6_auditor/proposals/20260511-200200-sixth-audit/` document the proposed changes. Operator should decide: commit / retire / in-progress.
- 🟡 `data/top8_list.json` carries the operator's actual Top 8 entry now (`xChunjae#Mage`). Probably should be `.gitignore`'d — it's user data, not source.

## Files touched this session

- `core/enemy_aware_stats.py` (new) · `core/defensive_picks.py` (new)
- `dashboard/routes_state.py` (ds-preview enriched 2x) · `dashboard/routes_loadout.py` (allowlist) · `dashboard/routes_lobby_aux.py` (new — /api/top8 + /api/mains) · `dashboard/_dispatch.py` (registered new routes)
- `tools/gamepc_lcu_agent.py` (championPickIntent + my_completed + local_cell + 6 new handlers + auto_accept default flip)
- `web/index.html` (cache buster 2026051125 → 2026051210)
- `web/js/main.js` (restored lcuCmd/lcuPollResult + frontend toggle wiring + auto-clear expansion + sticky guard)
- `web/js/lib/state.js` (added `_VIEW.gameStarted`)
- `web/js/panels/champ_select.js` (lock button, DS-driven build chooser, opt-in→opt-out)
- `web/js/panels/active_match.js` (default-on, render `immediate`, step 4 map overlay, target_stats caption, DEFENSE row, freshness guard)
- `web/css/panels/champ_select_view.css` (lock-button styles)
- `data/top8_list.json` (new — server-side Top 8 persistence)
- `docs/ARCHITECTURE.md` (auto-synced by archmap)

---

# s170 wrap — 2026-05-11 (LCU wiring punch list — items #1 #2 #3 #4 #5 #7 shipped, #6 parking-lot)

Operator opened by asking "what is needed to finish the LCU wiring to the UI output for things like pre-game lobby and, champion select, and DS output to active match" — informational query that produced a 7-item punch list. Then operator said "continue" repeatedly, working through items 1–4 + 7 in one continuation. Items 5 and 6 ended the session as bridge-dispatched (waiting on Game-PC Claude) and parking-lot (requires live Arena lobby) respectively.

## Ships (in chronological order this session)

- **Item #7 — My Top 8 dummy purge** (`web/js/main.js:3456`). Auto-prune list of 8 known sim-fixture `riot_id`s (`FrenLuvr#NA1`, `Brawler#NA1`, `SmurfLord#PRO`, `WardBot#SUP`, `CarryHarder#NA1`, `SkillIssue#TT`, `NoobieMcGee#NEW`, `SamplePlayer Sock#NA1`) filtered out of `localStorage.rc-top8-list` on `_top8Load()` read; cleaned list written back. Idempotent. Real `SamplePlayer#Vayne` cannot collide because matching is on full riot_id including tagline.
- **Item #1 — LCU lobby members forwarder** (`tools/gamepc_lcu_agent.py:188-336`). `state["lobby"]` now carries `members[]`, `local_member`, `is_leader`, `party_id`, `party_type`, `can_search`, `queue_name`, `search_state` — driven off `/lol-lobby/v2/lobby` + `/lol-matchmaking/v1/search`. Per-member: puuid, summoner_id, riot_id (composed from gameName + tagLine), summoner_level, ready, position_preferences. 22 tests under `tests/phase_b_champ_select/test_lcu_lobby_members.py`. **Game-PC redeployed via http.server :8765 → Invoke-WebRequest dance (pid 15480 confirmed alive).**
- **Item #1 follow-on — is_self via summoner-id match + name enrichment** (same file). Current LCU builds emit empty `gameName`/`tagLine` on lobby members and don't set `isLocalMember`. Fix: compare `member.summonerId` to local summonerId (resolved via `_resolve_local_summoner_id`, already cached for mastery hook); enrich missing names via `/lol-summoner/v1/summoners/{sid}` (per-id 10-min TTL cache `_summoner_lookup_cache`). 9 additional tests. **Game-PC redeployed AGAIN.** Verification awaits next Lobby phase (operator entered ChampSelect mid-session).
- **Item #2 — DS enemy-stats heuristic helper** (`coach_integration/enemy_stats.py`, new). `compute_enemy_stats(mode, game_seconds, level, bonus_hp_override, enemy_levels)` returns level-scaled `EnemyStats(armor, mr, max_hp, bonus_hp)` per mode (SR/ARAM/Arena/Brawl). Replaces all 4 coaches' hardcoded `target_armor=80.0`. Coaches' existing item-aware `_estimate_target_bonus_hp` preserved via `bonus_hp_override`. 27 tests under `tests/test_enemy_stats.py`. Live via restart.
- **Item #3 — Active Match per-tick DS rerank + icon strip** (`web/js/panels/active_match.js`). `_maybeRefreshDsPicks()` POSTs to existing `/api/ds-preview` with current `{champion, mode, level, items}`; 4s input-fingerprint cooldown so DS engine isn't hammered. `_dsIcon()` renders CommunityDragon item icon (44px) with green "OWNED" overlay + `+Ndps` delta caption. Fallback tile when icon CDN 404s (Arena re-skins). Coach-emitted `daemon_slayer_picks` remains the fallback when live rerank hasn't responded yet.
- **Item #4 — Pick & Ban Recommendations backend join** (`dashboard/routes_pickban.py`, new + `dashboard/_dispatch.py` wired). `GET /api/champ-select/pickban-recs?role=X[&queue=Y]` returns operator-aware performance row + ban suggestions from `rewind_history.db`. Role normalization handles both LCU (BOTTOM/UTILITY) and dashboard (BOT/SUP) forms. Performance: highest-WR champ with ≥3 games. Bans: top 3 enemy-at-role champs with ≥2 encounters and ≥50% loss rate. Mastery + meta rows still on placeholders (Tier 2). Read-only SQLite connection (WAL-safe). 17 tests under `tests/test_routes_pickban.py`. Wired into `web/js/panels/champ_select.js:_csvRenderPickBan` via `_csvFetchPickBanRecs` with 60s cache + re-render on fetch land. **Live verified: 33ms response, real `MissFortune 4/6 67% WR` with ban suggestions Nilah/Twitch/Mel (all 100% loss-rate).**

## Bridge-dispatched and resolved

- **Item #5 — RC-LCU scheduled task action path fix** (bridge task-id `task-454fde72f190`, completed by Game-PC Claude at 1778559598, 63s round-trip). Before: `Execute: py` (failed ERROR_FILE_NOT_FOUND under scheduled-task context — same root cause as RC-PatchRefresh per `project_rc_patchrefresh_fixed.md`). After: `Execute: C:/Users/Administrator/AppData/Local/Python/pythoncore-3.14-64/python.exe`. Running agent (pid 15480) deliberately NOT restarted by Game-PC Claude — fix applies on next reboot. Pattern established: dispatch Game-PC system fixes via `bridge_cli.py task --target gamepc` with self-contained PowerShell instructions; round-trip in ~60s when /loop is running.

## Parking-lot

- **Item #6 — `set_augment_intent` LCU endpoint discovery**. Blocked on live Arena lobby. Discovery pattern from s168 (lockfile → basic auth → enumerate `/lol-cherry/v1/*` paths) can run when next Arena queue pops. Until then, agent's stub at `tools/gamepc_lcu_agent.py:777` returns `augment_intent_unsupported`.

## Test posture at wrap

- Project sweep: **788 passed** (was 719 at s169 wrap; +22 lobby members + 9 enrichment + 27 enemy_stats + 17 routes_pickban = +75 tests).
- Snapshot panels: untouched (no active-match snapshot tests; champ_select snapshot fixtures already had placeholder render).

## Live verification at wrap

- RC pid=12852 alive, last_reload_ok=true (restarted twice this session — once for coach changes, once for new route module).
- Game-PC LCU agent pid=15480 alive, posting fresh state. Verified phase=ChampSelect with mastery + champ_select populated.
- `GET /api/champ-select/pickban-recs?role=BOT` returns 200 with real data.
- http.server on :8765 shut down (both redeploys completed).
- Cache buster: 2026051122 → 2026051125 (bumped three times — Top 8 wipe, active-match step 2/3, P&B recs wiring).

## Decisions / non-obvious notes for next-session-you

- **Game-PC redeploy is fiddly.** SMB pull from `\\192.168.8.230\C$\...` is blocked (no peer creds cached). Workaround: `cd <staging>; py -m http.server 8765` on Legion + `Invoke-WebRequest` on Game-PC. Document this in OPERATIONS.md if it recurs more (s168 + s170 both used it).
- **`Get-WmiObject` is broken on operator's PowerShell.** Throws `0x800703E6 / BadImageFormatException`. Use `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` instead. Updated all redeploy command blocks to use Get-CimInstance.
- **PUUIDs in `rewind_history.db` are stale.** The `v8HzkOaP...` puuid (operator's old) is the most frequent participant entry but is invalid for Match-V5 calls per s167. For internal queries against participants table it's fine (it's just an internal join key). The routes_pickban endpoint uses `_resolve_operator_puuid()` which picks most frequent — works because we're doing a self-join inside the DB, not calling Riot Web.
- **DS rerank cooldown is 4s, not coach-tick aligned.** Active Match view fires `/api/ds-preview` on input fingerprint change OR every 4s, whichever is sooner. Coach tick is variable (5-15s). Live rerank takes priority over coach-emitted picks when both are present.
- **`compute_enemy_stats(level=11, mode="sr")` returns armor=95, mr=63, max_hp=2210, bonus_hp=1610.** Old hardcoded value was target_armor=80.0 only — all other fields were defaults (0). That means historical DS picks were missing target_mr/target_max_hp/target_bonus_hp entirely. **DS calibration baseline shifts on first in-game tick after s170.** Watch the first 2-3 games' picks; if they look wildly different from coach narration, the heuristic may need tuning.
- **`_lobbyViewRefresh` lobby field expectations are NOT all live yet.** It also expects per-member `rank`, `played_with_me_count`, `is_online` — those need Legion-side joins (Riot Web rank + rewind_history.db games + LCU `/lol-chat/v1/friends`). Agent forwards what LCU emits; Legion enrichment is follow-on.
- **`_PB_LIVE_CACHE` is per-role-per-queue, 60s TTL.** During an active champ-select session the WR data isn't changing, so 60s is plenty. If you ever want sub-minute freshness (e.g. running multiple sessions back-to-back with new games landing in between), bump the TTL down OR add a manual refresh button.

## Files touched

- `tools/gamepc_lcu_agent.py` (+~200 LOC: `_LOBBY_QUEUE_NAMES`, `_slim_lobby_member`, `_derive_search_state`, `_lookup_summoner_by_id`, `_resolve_local_puuid`, `_reset_summoner_lookup_cache_for_tests`, capture_state lobby block extension)
- `tests/phase_b_champ_select/test_lcu_lobby_members.py` (new, ~330 LOC, 31 tests)
- `coach_integration/enemy_stats.py` (new, ~165 LOC, EnemyStats + compute_enemy_stats)
- `coach_integration/_coach.py` (+~20 LOC: SR coach DS call uses helper)
- `coaches/aram_coach.py` (+~15 LOC: ARAM DS call uses helper, item-aware bonus_hp override)
- `coaches/arena_coach.py` (+~17 LOC: same pattern for Arena)
- `coaches/brawl_coach.py` (+~15 LOC: same pattern for Brawl)
- `tests/test_enemy_stats.py` (new, ~190 LOC, 27 tests)
- `web/js/panels/active_match.js` (+~100 LOC: `_maybeRefreshDsPicks`, `_dsIcon`, `_dsIconFallback`, BUILD body rewrite)
- `dashboard/routes_pickban.py` (new, ~210 LOC: `/api/champ-select/pickban-recs` endpoint)
- `dashboard/_dispatch.py` (+2 LOC: route registration)
- `tests/test_routes_pickban.py` (new, ~240 LOC, 17 tests)
- `web/js/panels/champ_select.js` (+~85 LOC: `_CSV_PB_CACHE`, `_csvFetchPickBanRecs`, `_csvMergePickBanData`, `_csvRenderPickBan` extension)
- `web/js/main.js` (+~15 LOC: `_TOP8_FAKE_RIOT_IDS` + filter on `_top8Load`)
- `web/index.html` (cache buster ×3: 2026051122 → 2026051125)

## Open items handed off

- ✅ **Bridge task `task-454fde72f190` resolved** by Game-PC Claude. RC-LCU scheduled task now uses absolute python path; auto-relaunch on reboot fixed.
- 🟡 **Lobby-phase live verification of is_self + name enrichment.** Operator was in ChampSelect at wrap. Next Lobby phase exercises this path.
- 🟡 **Active Match view live verification.** Operator was in ChampSelect; once they enter a game, `?am=1` (or `localStorage.activeMatch=1`) auto-promotes and the per-tick rerank + icon strip light up.
- 🟡 **P&B Recommendations live verification.** Operator was mid-CS at wrap; the new Performance row on the champ-select view's P&B panel should overlay live data within 60s of CS entry.
- 🟡 **Item #6** — Arena augment intent endpoint discovery. Next Arena queue pop.
- 🟡 (Unchanged from s169) ADR-007 phase 2 (postmortem pipeline), phase 3 (prose-coach deprecation).
- 🟡 (Unchanged from s168/s169) P1b augment registry, P5 default DS build #4, P3/P4 history+replay UI.

---

# s169 wrap — 2026-05-11 (ADR-007 event-coach pivot — phase 1 ship, decision_detector expansion + heartbeat pill)

Operator-initiated discussion → architectural pivot doc + phase-1 ship in one session. Goal: shift coaching from continuous narration ("you're low HP — back!") to event-driven decision forks ("enemy JG missing 25s — safe/punish?"). Discovered mid-session that `core/decision_detector.py` (Tier 3 #15, 2026-05-01) ALREADY implements the architecture — `DECISION_REGISTRY`, `Decision` dataclass with A/B options, daemon loop, atomic store, JSONL log, dashboard banner + record_choice. Only 4 detectors shipped though, and the log showed only smoke-test entries (matches operator's "5 games in 5 months"). Pivot is therefore extension, not new build.

## Ships

- **ADR-007 (docs/adr/ADR-007-event-coach-pivot.md)** — formal pivot doc. Documents `decision_detector` as the foundation; lays out the 3 concurrent workstreams (detector library expansion, glanceable heartbeat surface, postmortem-from-rewind_history.db). Phase-1 scope explicitly = this session's ships. Phase-2 (postmortem pipeline) + phase-3 (prose-coach deprecation) deferred.
- **Tightened `detect_low_hp_backable`** (s169 reaction to "tell me 3× I'm low HP" complaint): HP threshold 40%→25% (you're committed to back, not deciding) + alive_for 45s→90s (post-respawn pre-fight has stable framing). Same 60s bucket id stays — re-fire was already prevented; the tightening reduces false-positive *rate* per game.
- **2 new detectors** in `core/decision_detector.py`:
  - `detect_jungler_gank_likely` — enemy JG (Smite-identified) missing ≥20s AND last seen OUTSIDE their own jungle quadrant. SR-only; defers to `objective_contest` when drake/baron is imminent. Bucketed to 90s windows. Options: `safe / punish`.
  - `detect_throwing_lead` — 2+ self-deaths in last 90s, clustered ≤45s apart, past 8min mark. Stateless (event-driven). Options: `reset / force`.
- **Heartbeat counter** on `DecisionLoop`:
  - `_eval_count` bumps after each successful eval cycle; resets on new-match game_time reversal (already-existing reset path).
  - `heartbeat()` method + module-level `read_heartbeat()` helper.
  - File-backed at `data/decisions_heartbeat.json` so the dashboard (RC main process) can read what the Phase 3 supervisor's loop wrote. `read_heartbeat()` recomputes `age_s` + `alive` at read time so a stuck supervisor flips `alive=False` on its own.
- **New API routes** (registered in `dashboard/routes_diag.py`):
  - `GET /api/decisions/heartbeat` — pill data source.
  - `POST /api/decisions/respond_active` — body `{choice_index: 0|1, dismiss?: bool, note?: str}` — resolves first pending decision by mapping to `options[choice_index]`. Single endpoint for the Game-PC keybind listener (Numpad 1/2/0 stay constant across detector types).
  - **POST validation loosened** — was hardcoded `choice ∈ {contest, give, skip}`; now validates against the actual pending decision's `options` list + `"skip"`. New detectors use options like `safe/punish`, `reset/force` so the old check rejected them.
- **Dashboard `#trigger-pill`** (header row 2, next to `#ds-pill`):
  - `web/index.html` adds the `<span class="trigger-pill" id="trigger-pill">● 0</span>`.
  - `web/css/panels/map_state.css` adds `.trigger-pill` styles with `.alive` (green) / `.stale` (amber) / `.dead` (grey) / `.pending` (blue outline) variants. Hidden on client/tft modes.
  - `web/js/panels/trigger_pill.js` polls both `/api/decisions/heartbeat` and `/api/decisions` at 2 Hz; displays `● N` counter (asterisked when pending). Tooltip carries diagnostic: counter / last-eval age / game_time / detector count / pending count.
  - `web/js/main.js` adds the side-effect import (panel self-starts on import).
  - Cache buster 2026051121 → 2026051122.
- **Game-PC keybind listener** (`tools/gamepc_keybind_listener.py`) — install-only; not auto-deployed. Hooks Left Alt + 1/2/3 via `keyboard` lib, POSTs to `/api/decisions/respond_active`. 250ms debounce. ENV overrides for keybinds (`RC_KEY_A` / `_B` / `_DISMISS`). Self-contained — own ssl context + urllib post, no RC imports. Documented schtasks install pattern in the docstring. **Left Alt chosen over Ctrl** because Ctrl+1..6 are League's item-cast binds — Alt+1..6 are unbound by default (operator request 2026-05-11: tenkeyless keyboard, wants number-row above QWERTY).
- **25 new tests** under `tests/test_decision_detector_adr007.py` — pure-function tests for all 3 detector changes + DecisionLoop heartbeat + file-backed read roundtrip. Full suite **719 passes** (was 694).

## Live verification

- RC restarted via `restart_trigger.txt` → endpoint live; `curl -ks https://127.0.0.1:8888/api/decisions/heartbeat` returns the no-file sentinel + `detectors: 6` confirming both new detectors registered.
- Phase 3 supervisor restarted via `taskkill /F /PID 16436` + `schtasks /Run /TN "RC-Phase3-Supervisor"` — new PID 11712 picked up the new code (per-tick the supervisor will run the 6 detectors + write heartbeat once a game starts).
- Dashboard screenshot from Game-PC monitor 1 confirmed no broken UI (pill correctly hidden in client mode). Polling logs show /api/decisions + /api/decisions/heartbeat at 2 Hz cadence — trigger_pill.js loaded and running.
- POST validation tested: `respond_active` with no pending returns 404 cleanly.

## Decisions / non-obvious notes for next-session-you

- **Detector signature stays pure**: `(snapshot, vision_state) → Optional[Decision]`. New "needs prev_snapshot" data (HP delta, gold delta) belongs in a separate loop-owned context dict — DO NOT extend the signature for one-off needs.
- **Cross-process heartbeat is file-backed**, same pattern as `DecisionStore`. The DecisionLoop singleton lives in the Phase 3 supervisor process; the dashboard reads via `read_heartbeat()` from `data/decisions_heartbeat.json`. No IPC, no socket — keeps it simple.
- **Rate-cap math**: `_MAX_PER_GAME = 5`, `_MIN_GAP_S = 30`. Now 6 detectors compete for those 5 slots. Watch the first 3 real games' logs — if any of the new detectors gets starved (always after low_hp_back / objective_contest in the gap), bump the cap.
- **Dispatch order matters**: POST_ROUTES registers `equals("/api/decisions/respond_active")` BEFORE `prefix("/api/decisions/")` so the equals match wins. Reversing the order would route `/respond_active` to `_serve_decision_choice_post` with id="respond_active" → 404.
- **`/api/decisions/respond_active` is keybind-shaped**, not banner-shaped. Banner buttons keep using `POST /api/decisions/<id>` with explicit choice string. Different audiences: keybind doesn't know the id, banner does.
- **Keybind listener needs `pip install keyboard`** on Game-PC. Schtasks docstring includes the install steps. Not yet deployed — operator should deploy when ready to live-test keybind flow. Without it, the dashboard banner buttons are the only A/B input.
- **The pill is hidden in client/tft modes** (CSS rule mirrors ds-pill). Operator won't see it on the home overlay or in TFT; intended.
- **`detect_low_hp_backable` tightening reduces fire rate**. Bucket is still 60s — re-fire was already prevented by the bucket id stability. The threshold tightening cuts the absolute rate (`<25%` is rare unless committed to back).

## Files touched

- `docs/adr/ADR-007-event-coach-pivot.md` (new, ~120 LOC)
- `core/decision_detector.py` (+~285 LOC: 2 detectors + heartbeat + write/read pair)
- `dashboard/routes_diag.py` (+118 LOC: 2 new handlers + relaxed POST validator + route table)
- `web/index.html` (+10 LOC: trigger-pill span + cache buster bump)
- `web/css/panels/map_state.css` (+42 LOC: .trigger-pill block)
- `web/js/main.js` (+2 LOC: side-effect import)
- `web/js/panels/trigger_pill.js` (new, ~85 LOC)
- `tools/gamepc_keybind_listener.py` (new, ~150 LOC)
- `tests/test_decision_detector_adr007.py` (new, ~330 LOC, 25 tests)
- `WAKEUP_NOTES.md` / `docs/history_notes.md` (this wrap + s166 archive)

## Open items handed off

- 🟡 **Game-PC keybind listener deployment** — `tools/gamepc_keybind_listener.py` not yet copied to Game-PC. Operator decides whether to install + run for live test. Banner buttons work without it.
- 🟡 **Live game observation** — first real-game test of the new detectors. Watch `data/decisions_log.jsonl` for fires; tune thresholds if any detector skip-rate exceeds 70%.
- 🟡 **ADR-007 phase 2 (postmortem pipeline)** — `scripts/postmortem_analyze.py` mining rewind_history.db for per-player death patterns. Deferred to s170+.
- 🟡 **ADR-007 phase 3 (prose-coach deprecation)** — mode coaches still narrate in parallel with decision_detector. Detector-by-detector deprecation pass deferred until phase-1 detectors prove out in real games.
- 🟡 (Unchanged from s168) RC-LCU scheduled-task `Execute: py` → absolute python path on Game-PC.
- 🟡 (Unchanged from s168) P1b augment registry, P5 default DS build #4, P3/P4 history+replay UI.

---

# s168 wrap — 2026-05-11 (FU01 minimap-locate + LCU mastery endpoint live-fix + Game-PC redeploy)

Continuation per `NEXT_SESSION_PLAN_2026-05-10.md`. After s167 closed P1a/P2/P7/P8/P9, the remaining 🟡 backend items were either UI-blocked, data-blocked (sparse rewind), or operator-clarification-blocked (P6 Claude Desktop key). **FU01 minimap-locate** was the highest-leverage open item. Operator opened League mid-session, unblocking the s167 LCU mastery Game-PC redeploy — which surfaced a stale-endpoint bug, fixed and re-deployed in the same session.

## Ships

- **FU01 — minimap-locate 3-path resolver.** New module `agents/_minimap_bbox.py`; `agents/supervisor.py:597` rewired. Resolution order: HTTP `?bbox=` override (untouched) → `data/vision_regions.json` `_minimap_<mode>` key → hardcoded 1920×1080 fallback. The persisted key uses `_*` prefix so `core/vision_tesseract._regions()`'s metadata filter ignores it — no collision with OCR region namespace.
- **LCU mastery endpoint fix + Game-PC redeploy.** The s167 mastery hook called `/lol-collections/v1/inventories/<sid>/champion-mastery` — a path that returns HTTP 404 on current LCU builds (Riot migrated the API namespace). First live LCU contact during the Game-PC redeploy revealed this. Correct endpoint discovered via path-enumeration probe: `/lol-champion-mastery/v1/local-player/champion-mastery` (no sid in path; returns local player's mastery directly). Patched in `tools/gamepc_lcu_agent.py:241-251` + 6 mock-path occurrences in `tests/phase_b_champ_select/test_lcu_mastery.py` updated; full 10/10 mastery tests + 694/694 project sweep still green. Game-PC's `C:\RC-Agent\gamepc_lcu_agent.py` redeployed to fixed version via one-shot Legion `:8765` `http.server` + Game-PC `Invoke-WebRequest` (SMB blocked, no peer creds cached).
- **LCU mastery state-shape flatten fix.** First Lobby-phase live probe (after the endpoint patch) revealed the s167 code-path placed mastery at `state["lcu"]["lcu"]["mastery"]` — double-nested — because Legion's bridge handler already wraps the entire agent state as `legion_state["lcu"]`, and the agent was additionally doing `state.setdefault("lcu", {})["mastery"] = mastery`. Flattened to write at `state["mastery"]` and `state["summoner_id"]` at the top level of the agent's state, so Legion's wrap produces the intended `state["lcu"]["mastery"]` path. Tests updated (assertion paths + `idle` test now checks `state["mastery"]` is absent rather than `state["lcu"]`). Live-verified: `phase=Lobby` immediately produced `state["lcu"]["mastery"]` with 40 entries — top 5 ADCs (Jinx 33507 pts, Kai'Sa, Vayne, Caitlyn, Tristana) matching operator's `SamplePlayer#Vayne` main. Game-PC redeployed for a 3rd time this session via the same `http.server` mechanism.

## Tests

- `tests/fu01_minimap/test_minimap_bbox.py` — 19 tests: no-file → fallback; partial entries; wrong arity (3-tuple); wrong type (string); non-numeric (`"twenty"`); degenerate bbox (`l>=r`, `t>=b`); corrupted JSON; top-level non-object; case-insensitive mode lookup; `load_persisted` direct API; file-read exception swallowed via `mock.patch.object(Path, "read_text", side_effect=OSError)`.
- `tests/phase_b_champ_select/test_lcu_mastery.py` — 10 mock-path-updated tests still green after the endpoint patch (`/lol-collections/v1/inventories/<sid>/...` → `/lol-champion-mastery/v1/local-player/...`).

## Test posture at wrap

- DS suite: **949/949** (unchanged from s167).
- Project sweep: **694/694** (+19 fu01; +0 net from mastery patch — same 10 tests pass against the new path). Note: s167 wrap reported "601/601 (+10 LCU mastery)" — the 694 reflects the full `tests/` tree including snapshot/fixture suites that aren't separately tallied in session notes.

## Decisions / non-obvious notes for next-session-you

- **Behavior is byte-identical until calibration entries are added.** No `_minimap_<mode>` keys exist in `data/vision_regions.json` today — `resolve()` falls back to the same hardcoded bbox the inline dict had. Live `curl https://127.0.0.1:8888/api/minimap-crop?mode=sr` against the still-running pre-FU01 phase3 supervisor returns 200 with the cached vision frame (verified at session start). After phase3 restart, response will be identical.
- **Phase 3 supervisor was NOT restarted.** `agents/supervisor.py` is the `RC-Phase3-Supervisor` scheduled task (pid 16436 at session start; listens :8890/:8891 — separate from main RC's :8888). It doesn't watch `restart_trigger.txt`. To force pick-up: `taskkill /F /PID <pid>` + `schtasks /Run /TN "RC-Phase3-Supervisor"`. Skipped here because the change is additive — no observable difference until calibration is written. Next natural reboot / supervisor cycle picks it up.
- **Calibration recipe** (for the operator when needed): edit `data/vision_regions.json`, add `"_minimap_sr": [l, t, r, b]` (likewise for `aram`/`brawl`), then `curl -k -o /tmp/m.png "https://127.0.0.1:8888/api/minimap-crop?mode=sr"` and tweak until centered. Bbox is validated for shape (4 ints, `r>l`, `b>t`) — bad entries silently fall back to hardcoded.
- **Pending Desktop/Tickets/ paperwork.** Original ticket file `RC_TICKET_FU01_minimap_locate.md` no longer exists on disk (Desktop/Tickets/ is gone — was the "transfer plan" pack reviewed in s144). Spec inferred from ROADMAP + `docs/history_notes.md:509-513`.
- **LCU endpoint discovery method.** When an LCU path returns 404, enumerate candidates against the live client. The probe pattern used here: read the lockfile (`C:\Riot Games\League of Legends\lockfile`) → build basic auth header (`riot:<pw>`) → try a list of plausible paths and print HTTP code per path. Faster than reading Riot docs (which lag behind client builds). Both `/lol-champion-mastery/v1/local-player/champion-mastery` and `/lol-champion-mastery/v1/{puuid}/champion-mastery` work; chose `local-player` since it doesn't require a path-param resolve.
- **Game-PC deploy mechanism — one-shot http.server.** SMB pull (`\\192.168.8.230\C$\...`) failed (no peer creds cached on Game-PC). Workaround: `cd <staging-dir> && py -m http.server 8765` on Legion (run_in_background=true) + `Invoke-WebRequest` on Game-PC + `taskkill` the listener afterward. Routine pattern; document in OPERATIONS.md if it recurs. Backup of pre-fix file at `C:\RC-Agent\gamepc_lcu_agent.py.bak-s168-pre-endpoint-fix`; s149 vintage at `C:\RC-Agent\gamepc_lcu_agent.py.bak-s149-2026-05-11`.
- **RC-LCU scheduled task is broken.** `(Get-ScheduledTask -TaskName 'RC-LCU').Actions` uses `Execute: py` (the Windows Python launcher) which fails ERROR_FILE_NOT_FOUND under scheduled-task context (memory `project_rc_patchrefresh_fixed.md` predates this discovery for RC-PatchRefresh; same root cause). Live workaround: `Start-Process -FilePath 'C:\Users\Administrator\AppData\Local\Python\pythoncore-3.14-64\python.exe' -ArgumentList 'C:\RC-Agent\gamepc_lcu_agent.py' -WindowStyle Hidden`. Fix the task action to use the absolute path when the operator next reboots; otherwise auto-relaunch on reboot will silently fail.

## Open items handed off (unchanged from s167 plus FU01)

- 🟡 **Triage uncommitted working tree** (operator-flagged at end of s168). After `git commit 0c876ef + 5715004` shipped this session, the working tree still carries pre-session changes I deliberately did NOT bundle. Next-session-you: ask the operator whether each set is **commit / retire / in-progress** so the tree doesn't accumulate orphans.
  - **Audit-5 source code** (uncommitted modifications): `agents/supervisor.py` (h01 `_warm_agent7_alive` init at line 1540 + h02 null-guard in `_warm_agent7_handle` at line 1809) + `agents/agent7_context/warm_session.py` (m01 `stats()` lock-guard). Small, additive, thread-safety + warm-session-init fixes. Apparently applied by an audit sub-agent at some point; never landed.
  - **Audit-5 proposal artifacts** (untracked): `agents/agent6_auditor/proposals/20260506-070234-fifth-audit/P-audit5-h01-warm-agent7-alive-init.result.md` + `…-h02-warm-agent7-actually-warm.result.md` + `…-m01-warm-stats-lock.result.md`. These document the audit's findings; likely belong with the source-code changes above.
  - **Runtime state churn** (uncommitted, normal): `data/ds_calibration.jsonl`, `data/placement_heatmap.json`, `data/ratings/last_{arena,sr,tft}.json`, `data/tft_live_data.json`. These mutate every game; not session-authored. Probably should be `.gitignore`'d if not already (verify).
  - **DB backups + script state** (untracked): `data/match_history.db.bak-2026-05-09-pre-darkstar-purge`, `data/match_history.db.bak-2026-05-10-prune-synthetic`, `data/rewind_history.db.bak-pre-catchup-2026-05-10`, `data/rewind_catchup.state.json`. The `.bak`s are insurance for s167's DB ops; `rewind_catchup.state.json` is the resumable sentinel for the catchup script. Almost certainly should be `.gitignore`'d.
  - **Screenshots** (untracked): `dashboard-full.jpeg`, `ds-pill-{after,live}.jpeg`, `item-build-full.jpeg`, `last-match-arena-ds.jpeg`. Ad-hoc UI captures. Move to `docs/_archive/screenshots/` or delete?
  - **Exploration doc** (untracked): `rc-tutor-decision-matrix.md` — looks like operator's design notes. Operator should decide whether to commit, move to `docs/`, or retire.
  - **MCP cache** (untracked): `.playwright-mcp/` — ephemeral; `.gitignore` it.
- 🟡 RC-LCU scheduled-task action path: change `Execute: py` → absolute python path (matches the running command-line of other Game-PC python agents).
- 🟡 Phase 3 supervisor restart to pick up FU01 live.
- 🟡 P6 (Sonnet/Haiku key routing) — needs operator clarification.
- 🟡 P1b augment registry — architectural; needs `as_pct` channel design pass.
- 🟡 P5 Default DS build #4 — waits on richer rewind data.
- 🟡 P3/P4 (History season-WR + Replay tab) — UI work, deferred per s166 directive.
- 🟡 UI Phase 3 steps 5–14 — UI work, deferred per s166 directive.

---

# s167 wrap — 2026-05-11 (backend sweep per NEXT_SESSION_PLAN_2026-05-10.md)

UI paused per s166 operator directive. Five backend ships in one commit (`1522b90`). Doc sync follow-up (`be86469`).

## Ships

1. **DS per-level DPS curve helper** (P1a) — `compute_dps_curve()` + `DpsCurvePoint` + `DPS_CURVE_LEVELS=(1,6,11,16,18)` in `agents/daemon_slayer/dps.py`. Pure additive; reuses `compute_dps()` per level. ENGINE_VERSION 0.60.0 → 0.61.0. 12 new tests (35 total in test_dps; 949 in DS suite). DS server restarted via `pythonw tools/start_daemon_slayer.py` after `taskkill /F /PID 13320` — `/health` confirms 0.61.0.
2. **rewind_history.db catchup** (P2) — `scripts/rewind_catchup.py` paginates Match-V5 → 5-table schema. **PUUID gotcha:** DB had stale `v8HzkOaP3OKe…`; current is `jVoxvNpcLTzD…` (Riot rotated). Script auto-resolves via Account-V1 from DB Riot ID (`SamplePlayer#Vayne`); state stores both stale + fresh for tracked-player detection. **`core/riot_api.get_recent_matches` extended** with `start`/`startTime`/`endTime`/`queue`/`type`. Idempotent + resumable via `data/rewind_catchup.state.json`. **2846 → 2851 matches** (only 5 games since 2025-12-15). DB was `-r--`; `attrib -r` cleared it.
3. **LCU mastery wired** (P8) — `tools/gamepc_lcu_agent.py` adds `_resolve_local_summoner_id` (cached) + `_maybe_refresh_mastery` (5-min TTL). Hits `/lol-summoner/v1/current-summoner` → `/lol-collections/v1/inventories/<sid>/champion-mastery`. Surfaced at `state["lcu"]["mastery"]` + `state["lcu"]["summoner_id"]` on Lobby / Matchmaking / ReadyCheck / ChampSelect / GameStart / InProgress / WaitingForStats. 10 tests under `tests/phase_b_champ_select/test_lcu_mastery.py`. **Last mile:** Game-PC redeploy needed before mastery appears live — Legion edit only.
4. **API surface audit** (P9) — `scripts/audit_api_surface.py` greps 4 surface regex sets. Writes `docs/API_SURFACE_AUDIT.md` (1363 lines, dedup'd by endpoint) + `data/api_surface.csv` (557 callsites). Counts: 89 internal `/api/*` / 70 LCU `/lol-*` / 6 web / 2 LiveClient. Foundation for future endpoint plumbing.
5. **Synthetic match pruning** (P7) — `scripts/prune_synthetic_matches.py`. Conservative heuristic: `champion = 'Dark Star Vertical'` OR `champion = '' AND game_time_s = 0`. Backup: `data/match_history.db.bak-2026-05-10-prune-synthetic`. **Deleted 56 rows (200 → 144).** `ds_calibration.jsonl` clean.

## Decisions / non-obvious notes for next-session-you

- **DPS curve scope was small.** Augment registry expansion (P1b) needs `as_pct` overlay channel architectural work; existing 10-entry registry stays.
- **rewind catchup is not "overnight" anymore.** Operator played 5 games in 5 months. Catchup runs in <30s. Schedule hourly via `schtasks` once operator resumes regular play; not needed right now.
- **PUUID rotation is silent.** Match-V5 returned HTTP 400 `"Exception decrypting <puuid>"` for the stale value. 78-char shape was fine; Riot's internal mapping was invalid. Account-V1 by Riot ID is the recovery path. **Do not assume stored PUUIDs survive long-term.**
- **DS server is NOT supervisor-restarted.** When you bump ENGINE_VERSION you must `taskkill /F /PID <pid>` + `pythonw tools/start_daemon_slayer.py`. Otherwise `/health` keeps reporting the old version and `tests/phase8_smoke/test_sr_draft_profile_engine.py::test_live_three_profiles` fails.
- **P6 (Sonnet/Haiku → Claude Desktop key) blocked on operator clarification.** Current path: `coaches/_base_coach.py:read_api_key()` reads `API-Key-Claude.txt` then `$ANTHROPIC_API_KEY`. CLI's `~/.claude/` is separate from this file — coaches already do NOT route through CLI's key. Operator needs to specify intent (replace file? billing visibility?).
- **NEXT_SESSION_PLAN_2026-05-10.md fully addressed for backend.** Remaining items are explicitly UI (deferred) or operator-clarification (P6).

## Test posture at wrap

- DS suite: **949/949** (+12 curve + version-pin updates)
- Project sweep: **601/601** (+10 LCU mastery)
- Phase_b suite: **40/40** (was 30; +10 mastery)

## Open items handed off

- 🟡 Game-PC redeploy of `tools/gamepc_lcu_agent.py` (LCU mastery hook).
- 🟡 P6 (Sonnet/Haiku key routing) — needs operator clarification.
- 🟡 P1b augment registry — architectural; needs `as_pct` channel design pass.
- 🟡 P5 Default DS build #4 — waits on richer rewind data.
- 🟡 P3/P4 (History season-WR + Replay tab) — UI work, deferred.
- 🟡 UI Phase 3 steps 5–14 — UI work, deferred per s166 directive.

---

# s165 wrap — 2026-05-10 (flow_03 mode-conditional Champ Select — central + enemies for all 4 modes)

Phase 3 step 3 follow-up from s164. Champ-select view's central panel (My Pick + Build Chooser) and enemies panel now branch per mode (SR / ARAM / Arena / Brawl). Allies + Pick&Ban panels LOCKED per operator — untouched. Single commit shipped: `91a42e1` (1112 ins / 34 del across 7 files, 3 new).

## What shipped (s165)

### Mode-detection plumbing
- New `_csvDetectMode(cs)` helper → `sr|aram|arena|brawl` from `queue_id` + `is_aram`/`is_brawl` flags (450/920 → ARAM, 1700/1710 → Arena, 480 or `is_brawl` → Brawl, default SR).
- `renderChampSelectView()` stamps `section.dataset.csMode = mode`; CSS branches via `#view-champ-select[data-cs-mode="..."]` selectors.
- Sub-line now shows mode label (SR DRAFT / ARAM / ARENA / BRAWL) instead of just queue id.

### `_csvRenderTeam()` — opts arg
- 6th positional `opts` arg added: `{ cellCount, showGuess, allowRolePip }`. Backward-compat with the previous 5-arg call sites (defaults: cellCount=5, showGuess=true, allowRolePip=true).
- ARAM/Brawl ally + enemy lists pass `showGuess: false, allowRolePip: false` — drops the (guess) annotation and role pip since those modes have no role assignment.

### Central pane variants (`_csvRenderCentralPane`)
- SR: existing My Pick + 3-variant SR Build Chooser (Lethal Tempo default / Press the Attack / Hail of Blades). Was empty placeholder.
- ARAM: My Pick + 5-cell horizontal Bench (`csv-bench`) under My Pick + ARAM Build Chooser. Click bench cell → fires `bench_swap` LCU command + visual pulse feedback.
- Arena: card header text swaps to "My Duo + Augments". Duo header (me + duo, 2 cells side-by-side), 3 augment slots (silver/gold/prismatic with active-round highlight), augment options list. Click option → fires `set_augment_intent`.
- Brawl: My Pick + Brawl Build Chooser (same 3-variant template as ARAM since builds are nearly identical).

### Enemies panel
- SR: unchanged (5 cells with role pips + (guess)).
- ARAM/Brawl: 5 cells, no role/guess. **Bug fix**: enemy summ block was `position:absolute; left:50%` from SR layout, which clipped champion names ("/eigar" / "12irand" overlap). CSS override resets to `position:static; justify-self:end` on `[data-cs-mode="aram"]`/`[="brawl"]` so the lock/timer flows naturally to the right edge.
- Arena: dedicated `_csvRenderEnemiesArena()` renders 3 sub-team cards stacked (TEAM 2 / TEAM 3 / TEAM 4, each with 2 champion cells).

### Grid relayout for non-SR modes
- `[data-cs-mode="aram"]` / `[="arena"]` / `[="brawl"]` hide the Pick&Ban panel and change grid-template-areas to `"allies mypick enemies"` (single row) so allies fills the freed row-2 space. SR keeps the 2-row layout.

### Fixtures (3 new)
- `data/sim/flow_03b_aram_select.json` — qid 450, is_aram=true, 5v5 (Garen/Malphite/Vayne/Taric/Volibear vs Veigar/Lux/Brand/Karthus/Soraka), bench=[MasterYi, Amumu, Irelia, Jinx, Pyke], Vayne mid-pick (37s timer).
- `data/sim/flow_03c_arena_select.json` — qid 1700, 4 arena_teams (me=Vayne+Taric, then Sett+Veigar / Garen+Lux / Annie+Mordekaiser), augments.options has 3 silver candidates, my_slots all empty (PICKING silver).
- `data/sim/flow_03d_brawl_select.json` — qid 480, is_brawl=true, 5v5 no roles.

### CSS additions (~450 lines)
- `.csv-bench` / `.csv-bench-cell` (horizontal strip with hover + is-pending pulse)
- `.csv-build-row` (radio-style variants, 14px checkbox + label + runes + 6 item icons; 24px item cells)
- `.csv-duo-row` / `.csv-duo-cell` (Arena allies, ME = indigo, DUO = green when locked, hourglass colors for hovering)
- `.csv-augment-slot` (silver/gold/prismatic borders, active-round inset shadow, filled-state bg)
- `.csv-augment-option` (clickable rows with tier-colored left border)
- `.csv-arena-team` (sub-team card with TEAM N head + 2-cell grid row)

## Files touched (s165)

- `web/js/panels/champ_select.js` — `_csvDetectMode`, `_csvRenderCentralPane`, `_csvBenchHtml/Wire`, `_csvBuildVariantsFor/RowsHtml/Wire`, `_csvArenaPaneHtml`, `_csvWireArenaAugments`, `_csvRenderEnemiesArena` added; `_csvRenderTeam` gained opts arg; `renderChampSelectView` rewritten for mode branching.
- `web/css/panels/champ_select_view.css` — appended ~450 lines of mode-conditional + new-block styles.
- `web/index.html` — 2 cache-buster bumps (CSS 2026051100 → 2026051111; JS 2026051041 → 2026051110).
- `data/sim/manifest.json` — 3 new entries.
- `data/sim/flow_03b/c/d_*.json` — 3 new fixtures.

## Phase B follow-ups (LCU agent on Game-PC)

The dashboard fires these but `tools/gamepc_lcu_agent.py` hasn't been updated yet:
- `bench_swap` — already supported (was used by legacy ARAM bench in `#cs-overlay`). Verify it still works from the new view.
- `set_augment_intent` — NEW. Needs LCU endpoint discovery (Cherry/Arena augment-pick verb). Currently no-ops.

Plus the agent needs to populate:
- `cs.bench` (already done for ARAM)
- `cs.arena_teams` + `cs.augments.{my_slots, options, current_round}` — entirely new for Arena. Fixture-only today.
- `cs.is_brawl` — set when LCU queue_id is 480.

Real build-chooser variants (currently static placeholders) come from `/api/loadout/list` — wire-up is also Phase B.

## What's deferred

Operator did NOT ask for an audit pass on this work — just the mode-conditional layout. Visual-hierarchy audit subagent ritual from `feedback_phase3_fixture_ritual.md` applies if operator declares the page done; this session is more of a step-3 follow-up than a fresh page. Defer until operator signals.

## Next session opener

- Tomorrow-you: if operator wants the visual audit on the 4 modes, run subagent per ritual.
- If operator wants Phase B wiring instead, target `tools/gamepc_lcu_agent.py` — add `set_augment_intent` handler + populate `cs.arena_teams` + `cs.augments` from LCU `/lol-cherry/v1/*` endpoints (need to discover the exact path).
- Either path is fine — both unblock real-fire testing of the new view.

---

# s164 wrap — 2026-05-10 (Champ Select view scaffold — flow_03 + Pick/Ban panel + trade popup)

Long UI iteration session. Phase 3 step 3 — built the new top-level `view-champ-select` page from scratch and iterated heavily on every panel. Single commit shipped: `c0e6043` (1986 ins / 4 del across 10 files, 3 new files).

## What shipped (s164)

### View scaffold + routing
- New `champ-select` view added to `VIEW_IDS` / `VIEW_LABELS` (between `lobby` and `active-match`).
- `<section id="view-champ-select">` in `web/index.html` with 3-col grid: Allies + Pick&Ban Recommendations (col 1), My Pick + Build Chooser (col 2), Enemies (col 3).
- Auto-promotes on `phase=ChampSelect` when `?cs=1` / `localStorage.csView='1'`. Legacy `#cs-overlay` hidden when on the new view.
- `header.css` `body[data-view="champ-select"]` rules for showing the section + hiding the main panels + home-overlay.
- New CSS file `web/css/panels/champ_select_view.css` (742 lines) — all `.csv-*` styles for the new view.

### Ally team panel
- 5 rows with champion icon (32px) | champion name | username | role pip layout.
- Username column hardcoded at `--csv-champname-col: 90px` (after iterations: 88→110→100→90 nudges). The hardcoded value aligns the lock/timer column near "A" of "Allies" header on the 1920-wide viewport. JS-based alignment was attempted multiple times (Range API, span wrap, clone, canvas measureText) — all returned wrong values due to body's `zoom: 1.33` and Chromium quirks; final solution is the hardcoded var.
- Self-row gets the gold "BOT" pip styling matching the pick/ban panel's role chip.
- Lock 🔒 / live countdown (cyan blue + 1px black outline, no "s" suffix per operator) at the start of the summoner col. Both share an 18px right-aligned slot so the timer's right edge never exceeds the lock's right edge.
- Click on username opens the SWAP/TRADE popup. Champion-icon and role-pip clicks were wired then explicitly removed per operator — only username triggers trades now.

### Enemy team panel
- Same row template + 2px gold/red active-round border via inset box-shadow.
- Lock/timer absolutely positioned at `left: 50%` (centered vertically under the "ENEMIES" title); role pip placed in grid col 4 explicitly so it doesn't auto-flow into the now-empty 1fr summ col.
- "(guess)" italic gray tag added between centered lock/timer and the role pip — vertically aligned across all rows.

### Pick & Ban Recommendations panel
- Lives in left column below the Allies card. Panel header removed (operator preferred PICK/BAN labels in the role row as the column markers).
- Header row: PICK label (col 1) + role chip removed + BAN slot (col 3, BAN sits in a 70px sub-slot right-aligned so the distance from BAN-right to panel-right mirrors PICK-left to panel-left).
- 3 pick rows (Performance / Mastery / Meta) — each is a 3-col grid: champ-col (icon + name, source label moved into the reason col header) | reason col (PERFORMANCE/MASTERY/META label + 1-line WHY text) | bans col (3 ban suggestions w/ icon + pct + name).
- Mood toggle row: PICK ONE label + 4 two-line buttons (Comfort Pick / Limit Test / Something New / Comp Synergy). Default Comfort; persists in `sessionStorage.csv-mood`.
- Quick-select clicks: ban icon → `set_ban_intent`, pick icon → `set_pick_intent`. Pick clicks gated on `cs.phase === "FINALIZATION"` OR `cs.my_completed` (operator: "no accidentally banning my own champion"). Once selected: red border on selected, others get `.is-disabled` (pointer-events: none + dimmed) so the operator can't switch their committed choice.
- Border colors: pick = green, ban = red, both selected and on hover.

### Trade popup (SWAP / TRADE)
- Singleton appended to `<html>` (NOT `<body>`) to bypass body's `zoom: 1.33` — `transform: scale(1.33)` with `transform-origin: 0 0` provides matching visual size without scaling its own position values.
- Structure: SWAP/TRADE header row above 3 equal-width buttons (`flex: 1 1 0; min-width: 88px;`). Buttons: champion name (uppercase) / Nth Pick / role (TOP/JUNGLE/MID/BOTTOM/SUPPORT). Pick-order button hides on non-SR-draft modes (`cs.sr_draft === false`).
- Render-then-measure positioning: park off-screen → measure with `visibility: hidden` → compute final left+top → reveal. Horizontally centered on the ALLIES panel; vertically attached just below the clicked username (originally tried username-center but operator's iterations on zoom revealed the offset issue).
- Buttons fire: CHAMPION → `trade_request`, Nth PICK → `request_pick_order_swap`, ROLE → `request_position_swap`.
- LED-dot animation explored (clockwise pseudo-element traveling around cell perimeter every 3s) but removed — wasn't rendering reliably due to body zoom + the cell's containing-block constraints.

### Sim fixtures
- `data/sim/flow_02_lobby_with_others.json` — clone of flow_01 with reframed meta + caption for the canonical 14-step fixture series (Phase 3 step 2).
- `data/sim/flow_03_champ_select.json` — SR Ranked draft mid-pick, Vayne locked BOT, 4 ally + 3 enemy picks done, 6 bans in, 22s on timer, `active_round: { type: "pick", cell_ids: [3, 6] }` so Lulu + enemy LeeSin show the gold border.

## Phase B follow-ups (LCU agent on Game-PC)

The dashboard fires these LCU commands but `tools/gamepc_lcu_agent.py` doesn't yet handle them. Each currently no-ops:
- `set_ban_intent` — set the user's current ban-action champion intent
- `set_pick_intent` — set the user's current pick-action champion intent
- `request_position_swap` — initiate lane swap with target cell
- `request_pick_order_swap` — initiate pick-order swap with target cell
- `trade_request` already supported (used by legacy ARAM bench swap) — verify it works for SR champion trades too

Plus the dashboard expects `cs.active_round` to be populated by the LCU agent based on the LCU's `actions[]` array — currently fixture-only.

## What's deferred (next session per operator)

> "do /done /clear and continue in another session the central panel and the enemies panel redesign for ALL Game modes. *these changes are not going to be just for SR -> I am taking the extra time to do the needed changes for compensating what i can for all the other games modes.*"

Central panel (My Pick + Build Chooser) and enemies panel redesign for ALL game modes (SR draft, ARAM, Arena, Brawl) — explicit operator request. The current scaffold uses SR draft assumptions throughout; ARAM/Arena need mode-specific layouts (no bans, different team sizes, bench swaps, etc.).

## Files touched (s164)

- `data/sim/manifest.json` — added flow_02 + flow_03 entries.
- `data/sim/flow_02_lobby_with_others.json` (new) — 436 lines.
- `data/sim/flow_03_champ_select.json` (new) — 88 lines.
- `web/css/dashboard.css` — added `@import './panels/champ_select_view.css';`.
- `web/css/panels/champ_select_view.css` (new) — 742 lines, all `.csv-*` styles.
- `web/css/panels/header.css` — 3 lines (data-view rules for showing the new section + hiding main + home-overlay).
- `web/index.html` — 61 lines (menu entry + section markup + cache buster bump).
- `web/js/lib/state.js` — 4 lines (VIEW_IDS + VIEW_LABELS).
- `web/js/main.js` — 16 lines (_viewAutoDerive + applyView + handleLcuEnvelope hooks + onState re-fire).
- `web/js/panels/champ_select.js` — 627 lines (renderChampSelectView + _csvRenderTeam + _csvRenderPickBan + _csvShowTradeChoice + helpers).

## Next session opener

Start with flow_03 loaded (`?sim=flow_03_champ_select&cs=1`). Per operator: "the central panel and the enemies panel redesign for ALL Game modes". Central panel = My Pick + Build Chooser pane in the middle column. Enemies panel = right column. Both need mode-conditional layouts that handle SR draft (current scaffold) + ARAM (no bans, bench swaps available) + Arena (2v2v2v2, augments) + Brawl (random 5v5). The Pick & Ban panel and Allies panel are LOCKED — don't re-iterate.

---

# s163 wrap — 2026-05-10 (Pre-Game Lobby v3 polish + conflict UI + AVG/Match grade)

Long UI iteration session on `flow_01_lobby_solo`. Operator-driven incremental polish per the Phase 3 fixture ritual; visual-hierarchy audit subagent ran mid-session and surfaced 5 must-fix items, all addressed. **Page locked for both solo + multi-member states** (placeholder-driven; no separate flow_02 fixture pass needed). Single commit shipped: `e316291` (913 ins / 181 del across 7 files).

## What shipped (s163)

### Layout / visual polish
- **PARTY title true-centered with rank pip** (col 4 grid placement on the title with same template as rows).
- **Top-2 champs in PARTY** (was top-3) so role/rank columns vertically line up with MY TOP 8.
- **Fonts above 13px floor** per `feedback_font_size_viewing_distance.md`: rank pips 9→13px, role pip 11→13px, lv-mc-cat 10→13px, lv-mc-avg-lbl 9→11px, lv-top8-rank-pip 10→13px (with 2/6→1/4 padding tighten + letter-spacing 0 to fit "Diamond IV 30 LP" without truncation).
- **6px gap** between PARTY col 2 (lane prefs) and col 3 (role pip).
- **"live" sub-label hidden** when healthy; only renders on error with bumped 14px red `.is-error` styling.
- **Drop shadow** on `.app-tooltip` and `.lq-mode-menu` (2-layer rgba black) — popovers visually float above content they overlap.
- **Page fits 1080-viewport without scrollbar** — trimmed `.view-section` (margin 4→2, padding 8/4 → 4/2) and `.view-section-head` (margin/padding 8/6 → 4/4).
- **QUEUE panel stretches** to match PARTY height; CHANGE LOBBY MODE button gets even space-evenly buffer.

### MY TOP 8
- **Names left-aligned, tag (notes) right-aligned**.
- **Rank tier color coding** extended from PARTY via shared `.lv-rank-*` (Iron→Challenger).
- **Single green hue for in-party rows** (reverted s162's per-member color matrix); same hue mirrored onto matching PARTY rows via new `.is-top8-mate` class.
- **Unranked entries → "LVL ### : Unranked"** with italic dim treatment, matching PARTY's `.lv-party-empty`.
- Online/offline dot removed from search row.

### PARTY panel
- **Self-row mirror**: col 2 renders operator's `_LV.prefPrimary`/`_LV.prefSecondary` lane icons (mirrors QUEUE picker); col 3 renders DB-assessed role pip (`m.assessed_role` field, fallback `m.preferred_role`).
- **5-slot renderer** with dashed `.is-placeholder` rows for empty seats — auto-populates/depopulates on LCU push.
- **Leader crown swapped** to real League captain-icon-crown PNG (CommunityDragon mirror, downloaded to `web/icons/lobby/captain-icon-crown.png`, served via new `/icons/lobby/` static route in `routes_static.py`).
- **Copy SVG**: 📋 → Phosphor copy-simple (currentColor inheritance via `.lv-copy-svg`).
- **Level → LVL** abbreviation in unranked fallback.
- **Role shorthand normalizer** `_roleShort()`: JGL/JG/JUNGLE → JNG, SUPP/UTILITY/SUPPORT → SUP.

### Primary-lane CONFLICT detection (s162 v15)
- Pre-pass in `_renderPartyMembers` builds a `conflictMap` over (self, members) Primary lane prefs. Non-FILL collisions get classed `is-conflict-self` (red, when self involved) or `is-conflict-other` (orange, no self). Re-runs on every `_setLanePref` change.
- **Self-side**: red 2px outline on Primary lane icon (PARTY) + matching member's; QUEUE Primary button gets red border + diagonal "CONFLICT" pseudo-element overlay (rotate -30deg, 55% opacity bad-color).
- **Non-self pair**: both icons get orange outline; QUEUE button stays clean.

### MAINS panel
- **Overall now 2x2 grid**: `[Games] [K/D/A — D in red]` over `[W - L] [N.NN KDA]`.
- **AVG/Match grid** (renamed from "Averaged"): row 1 `KP% / Vision / CS`, row 2 `AVG 5 / Dmg / CS-per-min`. **Gold dropped**, Vision moved up.
- **AVG 5 grade letter** (S/A/B/C/D, 17px / 900 weight, color-coded — gold/green/info/clock/bad). New `_avg5RankClass()`.
- **KP% 5-tier color bands** (s162 v10) — ≥70 S gold, 60-69 A info, 50-59 B good, 40-49 C clock, <40 D bad.
- **Total games sums per-mode** (RIFT + ARAM + ARENA from `overall.modes`); hover tooltip is a 3-col table via new `data-tt-html` attr on the games span (tooltip system patched to honor it via mouseover selector + innerHTML render path).

### Lane picker
- **Primary/Secondary swap** when picking same role for both — operator-side conflict resolution.
- **Lane popup icons fixed** — root cause was missing `/icons/positions/` static route (was 404'ing); added to `routes_static.py` + `/icons/lobby/`.

## Files touched (s163)

- `dashboard/routes_static.py` — `/icons/positions/` + `/icons/lobby/` routes (+2 lines).
- `data/sim/flow_01_lobby_solo.json` — new fields: `position_preferences`, `assessed_role`, `kp`, `avg5`, `dmg`, `cs_per_min`, `modes` (rift/aram/arena breakdown).
- `web/css/panels/base.css` — tooltip drop shadow (8 lines).
- `web/css/panels/header.css` — extensive (+408 lines).
- `web/index.html` — title spans for grid placement, AVG/Match label, search-row dot removed, cache busters bumped 2026051037 → 2026051050.
- `web/js/main.js` — extensive (+571 lines): `_LV_ICON_CROWN` + `_LV_ICON_COPY` constants, `_roleShort` helper, `_kpTierClass` + `_avg5RankClass` band helpers, `_mcOverallHtml` + `_mcAveragedHtml` + `_mcGamesCellHtml` extracted helpers, `_top8FormatRank` unranked path, conflict pre-pass, IIFE refactor for placeholder slots, `data-tt-html` tooltip path.
- `web/icons/lobby/captain-icon-crown.png` — new asset (2995 bytes, CommunityDragon).

## Phase B follow-ups (LCU agent on Game-PC)

LCU agent (`tools/gamepc_lcu_agent.py`) needs to forward into `state.latest.lcu`:
- `lobby.local_member.assessed_role` — most-played role from rewind_history.db (drives self-row PARTY col 3 pip).
- `lobby.local_member.position_preferences.first/.second` — read direction (current code is write-only via `_setLanePref`).
- `main_champs.champions[].averaged.kp` — kill-participation %, computed per champion.
- `main_champs.champions[].averaged.avg5` — last-5-match performance grade (S/A/B/C/D), rubric: KDA + KP% + DMG share + CS @10/20 + win/loss → percentile bucket.
- `main_champs.champions[].averaged.dmg` + `.cs_per_min` — already wired in fixture.
- `main_champs.champions[].overall.modes` — `{rift, aram, arena}` per-mode game counts + wins (drives total games + tooltip breakdown).
- `party_mains[*].averaged.*` + `overall.modes` — same as above for non-self members.
- `party.members[*].position_preferences` — already wired in fixture; needs LCU read path.

## Next session

Per operator: page is **locked**, ready to apply for live Lobby/Pre-Game.
Next session opens with **flow_02_lobby_with_others** — per s162 ritual, this is mostly a renaming pass since flow_01 already exercises 5-member layout. Then move to **flow_03 Champ-Select**.

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

---

# s149 wrap — 2026-05-09 (LCU agent → /api/team-context/refresh wiring)

## What shipped
- **FU02 last mile** (commit `e7b5af1`): Game-PC `tools/gamepc_lcu_agent.py` now POSTs the 10-player roster (with PUUIDs) to Legion `:8888/api/team-context/refresh` on ChampSelect entry + on lock/swap. Bearer auth via `bridge_shared_secret`. +238 LOC, no removals.
- **Bridge-secret resolver**: `RC_BRIDGE_SECRET` env → `bridge_secret.txt` → `local_paths.json{bridge_shared_secret}` → `""`. Empty = warn-once + skip POST (no historical default).
- **Champion-id → name cache**: lazy-loaded once per agent boot from LCU's `/lol-game-data/assets/v1/champion-summary.json`. Unknown ids translate to `""` so the dashboard renders blank rather than numeric garbage.
- **Edge-trigger semantics**: POSTs on (a) entering ChampSelect, (b) `(cellId, championId)` signature change. Rate-limited to `TEAM_CONTEXT_REPOST_S=3.0s` between re-fires; resets state on leave so next CS always re-fires the initial POST. Failure isolated from `/upload-lcu` cadence.
- **30 new tests** in `tests/fu02_team_context/test_lcu_agent_refresh.py`: resolver priority, pick-signature stability, body translation, POST helper, edge-trigger rate-limit + leave-reset + failure-doesn't-latch. **Total suite: 595 pass** (was 565). Ruff clean.
- **Game-PC deployed live**: `bridge_secret.txt` written via gamepc MCP, agent fetched from `:8888/agent/`, RC-LCU restarted (PID 16080). Resolver self-test confirmed `secret_len=43 first4=at_Y last2=WQ`. `/api/team-context` returns `null` cold, ready to fill.
- **Docs sync**: `tools/GAMEPC_CLAUDE.md` now documents the new POST + the bridge-secret deploy steps.

## Key decisions
- **Stdlib-only on Game-PC.** No `from core import bridge` — agent runs from `C:\RC-Agent\` where the project tree isn't importable. File-based resolver mirrors the pattern in `bridge_watcher_health_publisher.py:_resolve_token`.
- **Send display-name strings, not numeric ids.** Route's `_skeleton_entry` stores `locked_champion: str` for direct dashboard render; route's `_champ_name_to_id()` reverses via DDragon for mastery. Sticking with the FU02-shipped contract avoided a server-side schema change.
- **Edge-fire from `_state_push_loop`, not a new thread.** POST is fire-and-forget over Tailnet (~200ms) and only runs once per change. Spawning a fourth thread for one-shot POSTs was overkill.
- **`puuid` added to `_team_picks()` snapshot** — also makes /upload-lcu consumers richer with no new endpoint shape needed.

## What's next
- **Live verification** — waiting on next CS pop. Watch for `[team-context] refresh OK queue=… roster=…` in agent stdout (hidden — easier probe: `curl -k https://127.0.0.1:8888/api/team-context | py -m json.tool`).
- **FU01 minimap-locate** — still independent. 3-path resolver for `agents/supervisor.py:597`. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **Don't redo:** FU02 wiring is shipped end-to-end (panel + fan-out + LCU agent). Bridge secret is on Game-PC (`C:\RC-Agent\bridge_secret.txt`). Agent (PID 16080) is healthy and heartbeating.

## Blockers
- None. Verification is observational — picks itself up on the next champ-select.

---

# s148 wrap — 2026-05-09 (FU02 fan-out shipped + TFT match-history filter)

## What shipped
- **FU02 main work** (commit `dfa13f0`): `core/riot_api.py` (240 LOC) + `core/riot_api_cache.py` (260 LOC) + fan-out wired into `dashboard/routes_team_context.py`. Personal-tier key resolver, dual token bucket (20/s + 100/120s + 429 cooldown), SQLite cache (immutable for match data + Account, 5-min TTL for ranks + mastery), six endpoint wrappers (Account-V1, Match-V5 ids/detail/timeline, League-V4, Mastery-V4), priority-1 (rank+mastery) + priority-2 (mains/winrate/streak) fan-out via daemon thread, progressive reveal via `_update_entry` + `_mark_complete`, swappable `_FANOUT_DISPATCHER` so tests stub it out, backend ranked-name-blanking (queue 420/440) defense-in-depth.
- **63 new tests** across `test_riot_api.py`, `test_riot_api_cache.py`, `test_fanout.py` — rate-limiter dual-window math, cache miss/hit/expiry/concurrency, all six endpoints with mocked HTTP, key-resolver failure paths, fan-out worker progressive reveal + per-entry failure isolation, ranked-queue gate, default-dispatcher API-key gate. **Total suite: 565 pass** (was 496). Ruff clean.
- **Live-fired** the worker against the real Personal-tier key with fake PUUIDs — bucket held, `partial` flipped to `false` after deadline, `/metrics` exposes `rc_riot_api_calls_total{endpoint,outcome}` + bucket gauges.
- **Dark Star Vertical TFT filter** (commit `b12c71c`): `dashboard/builders.py` now excludes `mode='TFT'` from the Recent 5 + This Week + today-aggregate queries on the home view, AND from the shared `_load_match_rows` loader (cascades to History view sessions + session summary). Underlying rows stay in `match_history.db` for any TFT-aware consumer.

## Key decisions
- **Fan-out dispatcher is pluggable.** Module-level `_FANOUT_DISPATCHER` callable in `routes_team_context.py`; default checks `riot_api.is_configured()` and spawns a daemon thread; tests overwrite it with a recorder. Avoided monkey-patching `core.riot_api` internals from the test layer.
- **TFT filter is read-side, not data-deletion.** `match_history.db` rows untouched. Per memory `feedback_field_remove_visual_only.md`: "remove a field" means visual; data plumbing stays alive.
- **SQLite write-serialization.** Switched to `RLock` and serialized `set_immutable`/`set_ttl` via the instance lock — Windows + WAL + per-call connections + tight thread contention produced occasional "database is locked" errors. Cache is rate-limiter-bounded so write parallelism cost is trivial.
- **Champion-name → ID lookup** via DDragon `champion.json` glob, lazy-loaded in `routes_team_context._champ_name_to_id`. Soft-fail: missing IDs just skip the mastery call for that entry.

## What's next
- **FU01 minimap-locate** — still independent + ready anytime. 3-path resolver (override → PersistedSettings → hardcoded fallback) for `agents/supervisor.py:597`. Ticket at `Desktop/Tickets/RC_TICKET_FU01_minimap_locate.md`.
- **LCU agent extension** to actually POST to `/api/team-context/refresh` on `ChampSelect` transition. Currently Game-PC's `tools/gamepc_lcu_agent.py` collects myTeam/theirTeam but doesn't forward to the team-context endpoint — was deliberately deferred this session (panel + fan-out are wired; agent hookup is the last mile). Not in CLAUDE.md priorities yet.
- **Live verification with real PUUIDs** — needs an actual ChampSelect or a manual roster post with real `puuid` strings to confirm rank/mastery/mains all populate end-to-end against Riot's API.
- **Don't redo:** FU02 runtime fan-out is fully shipped. The panel stub from s146 is now backed by real data. Don't re-ship.

## Blockers
- None. FU01 is unblocked; LCU agent extension is unblocked.

---

# s147 wrap — 2026-05-09 (FU04 close — Personal-tier API key issued same-day)

## What shipped
- **FU04 application submitted and approved same-day** on developer.riotgames.com (App ID 834837, well inside the documented 2–6 week window). Personal keys never expire → FU03 clipboard helper permanently superseded.
- **Evidence bundle** at `Desktop/FU04-Application-Evidence/` (4 PNGs + README; mirror at Game-PC `C:\fu04-evidence\`). Operator added 6 confirmation PNGs (1.PNG–6.PNG) post-approval.
- **Capture pipeline patched mid-session:** .NET `CopyFromScreen` raced against Edge's hardware compositor during view transitions, saving stale framebuffer content. Rewrote PS capture to use `PrintWindow` API with `PW_RENDERFULLCONTENT` flag — reads window surface directly, race-free. Helper at `C:\fu04-evidence\_capture_window.ps1`.
- **Caught + excluded** the dashboard's `LAST MATCH` view from evidence — it's actually the live in-game coaching surface (NEXT/RIGHT NOW/FIGHT/BASE/MAP STATE), exactly what Riot forbids in Web-API context. SESSION view used instead for scene 3.
- **HISTORY view scored the strongest evidence slot** (scene 4) — 2846 matches + literal "needs Riot key" UI label in SEASON STATS column.
- **Form-side overflow strategy:** Product Description ~1500 char limit hit; compliance/rate-math/endpoint list moved to "Anything Else" field. Both documented in bundle README.
- **Commit f1c8b10** `feat(adr): FU04 close — Personal-tier API key issued 2026-05-09 (s147)` — ADR-006 status; CLAUDE.md priorities (FU04 ✅, FU02 UNBLOCKED, FU03 🚫); `.gitignore` gains `API-Key-Riot.txt` (was missing — caught at FU04 close).

## Key decisions
- **Key file canonical, env optional, Legion-only.** `C:\Riot Commander\API-Key-Riot.txt` (42 bytes, no newline) mirrors `API-Key-Claude.txt`. Optional User-level `RIOT_API_KEY` env on Legion for parity. Game-PC has no Riot Web API code.
- **Scene 02 carries double duty:** champ-select capture shows existing build chooser (top) AND FU02 team-context panel (bottom) — same cs-overlay surface, both annotated in README.

## What's next
- **FU02 runtime fan-out** is the immediate next session: `core/riot_api.py` (rate limiter at 20/s + 100/2min, SQLite cache at `data/riot_api_cache.db`, 4 endpoint wrappers — Account-V1 / Match-V5 / League-V4 / Champion-Mastery-V4), the cache-then-fan-out pump on `POST /api/team-context/refresh`, progressive reveal over the ~90s champ-select window. Ticket at `Desktop/Tickets/RC_TICKET_FU02_riot_api_module.md`.
- **FU01 minimap-locate** is still independent and ready anytime.
- Don't redo: FU03 clipboard helper is *permanently* superseded. Don't draft / don't ship.

---

# s145 wrap — 2026-05-09 (ticket review + Riot API key policy reversal)

## What shipped
- **Reviewed 12 RC_TICKET_*.md from `Desktop/Tickets/`** (a "transfer plan" pack adapted from another project). All rejected for premise mismatches against RC's architecture (no flat-string coach state, no WebSocket LCU, no YOLO, no numpy, no async runtime, hardcoded minimap bbox, etc.). Per-ticket rationale lives in the session transcript.
- **Two real concerns surfaced** during review and were addressed via follow-up tickets:
  1. Hardcoded minimap bbox in `agents/supervisor.py:597` is brittle to HUD-scale changes / left-side toggle / non-1080p. → FU01.
  2. Full-team context enrichment (loss streak, mains, rank, mastery on locked champ) requires Riot Web API — LCU/scrapers can't reach it. → ADR-006 + FU02–FU04.
- **ADR-006 — Riot API key policy reversal** (`docs/adr/ADR-006-riot-api-key-policy.md`): Personal-tier key permitted for champ-select + post-game enrichment only. Single-user shape. Live in-game advisory remains LCU/LiveClient-only per Riot ToS. Memory `reference_no_riot_api_key.md` rewritten as superseded; MEMORY.md index updated.
- **4 follow-up tickets drafted** to `C:/Users/Administrator/Desktop/Tickets/`:
  - **FU01** minimap-locate — 3-path resolver (override → PersistedSettings → hardcoded fallback).
  - **FU02** `core/riot_api.py` + champ-select team-context — rate limiter + SQLite cache + progressive reveal + ranked-queue name obfuscation gate.
  - **FU03** `scripts/stage_riot_key.py` — clipboard helper for daily dev-key staging during the Personal-tier approval wait. Throwaway after approval.
  - **FU04** Riot Personal-tier API key application — research-grounded form-field walkthrough + ready-to-paste description + screenshot checklist + post-submit playbook.
- **Retired** `RC_FUTUREPROOFING_PLAN.md` from Desktop → `docs/_archive/RC_FUTUREPROOFING_PLAN_retired_2026-05-09.md` (with `.rgignore` restored). All 7 phases ✅.

## Key decisions
- **Personal tier, not Production.** Personal = non-expiring, no domain verification, same 20/s + 100/2min throughput as Dev. Production requires verified domain + ToS + Privacy Policy + hosted site — overkill for single-user.
- **Channel is a web form, not email.** developer.riotgames.com → Register Product → Personal. Reviews via portal Project Discussion tab. Realistic approval window: 2–6 weeks.
- **Web API key MUST NOT power live in-game advisory** per Riot policy. RC's live coaching loop runs on LCU + LiveClient + local vision and is unaffected by this ADR.
- **Cold all-10-player champ-select fan-out is ~80–150 calls** vs the 100/2min ceiling. Cache-immutable (Match-V5, Account-V1) + TTL (League-V4, Mastery) + progressive reveal over 90s window + priority queue (locked-champ mastery + rank fire first; mains + streak as bandwidth allows).

## What's next
- **Recommended:** FU02 panel stub (route + ESM panel + CSS scaffolding + `TeamContext` payload schema) → captures honest screenshots → submit FU04 application. The 2–6 week Riot clock dominates downstream timeline.
- **Alternate:** FU01 minimap-locate (S, fully independent, removes a silent-failure mode you've already hit).
- FU03 only useful during the dev-key bridge period — not yet needed.

---

# s144 wrap — 2026-05-09 (Phase 6 — bridge CLI consolidation)

## What shipped
- **`tools/bridge_cli.py`** (574 LOC) — single argparse-subparser entrypoint with subcommands `task | post-result | pull | fetch | ping | heartbeat | post`. SSL ctx, urllib helpers, processed-tasks file, last-seen file, vision-health probe, and Stop-hook transcript parsing — each previously duplicated 2–7× across the originals — now live exactly once.
- **7 thin shims** (16–26 LOC each, 139 LOC total) replace the 7 originals (772 LOC total). Each shim imports `bridge_cli.main` and prepends its subcommand to argv. Cron contracts preserved exactly — `bridge_pull_tasks.py --target legion` still emits `{now, target, count, tasks}`; the `/process-bridge-tasks` skill spec was untouched.
- **`BridgeMetrics` namespace** in `core/prom_metrics.py` — counters `posts_total{kind,target}`, `fetches_total{status}`, `pulls_total{target,status}`; gauge `pull_pending{target}`. Class-level Counter/Gauge so registration happens on import.
- **`tests/phase6_bridge_cli/test_bridge_cli.py`** (new) — 42 tests: argparse contracts, envelope shapes (task with/without prompt, post-result with --suggestions/--exit-code/--from-stdin/--reply-to=peer routing via core.bridge.send), pull filtering (target match, rc alias on legion, answered/processed exclusion, sort-oldest-first, fetch-error path), fetch hook (last-seen file write, peer filtering case-insensitive), Stop-hook transcript extraction, heartbeat `--once` mode, BridgeMetrics class registration, parametrized subprocess --help dispatch over each shim.
- **Live verified**: `py tools/bridge_pull_tasks.py --target legion` → exact pre-shim JSON shape; `py tools/bridge_ping.py` → POST + GET read-back + vision health all OK, exit 0. RC supervisor untouched (RC-BridgeWatcher daemon excluded from rewrite scope).
- **Plan + living docs synced**: `RC_FUTUREPROOFING_PLAN.md` Phase 6 → 🟢 done (1/1 session); Phase 4.2 tool-rewrite checkbox flipped (s144 Findings); BACKLOG's "Bridge contract v1" item closed; CLAUDE.md priority #6 ✅; ROADMAP table updated; ARCHITECTURE.md auto-regenerated. 476 CI-scoped tests pass (was 440 + 42 mine + drift). Ruff clean. archmap clean.
- **Cleaned leftovers**: deleted `web/js/main.js.bak` (Phase 3.1), 3 `dev-panel*.jpeg` screenshots, `_audit5_tasks.tmp.jsonl`, 0-byte `agentsstatetask_queue.jsonl`. Kept `.playwright-mcp/` cache (used by snapshot tests).

## Key decisions
- **Scope**: plan said "12 scripts → shims"; actual CLI surface is 7 small scripts. The 5 `bridge_watcher*.py` daemons (2486 LOC combined) are long-lived processes, not CLI commands — out of rewrite scope.
- **Argparse over Click**: zero new dep, equivalent readability via `add_subparsers(dest="cmd", required=True)`.
- **State consolidation deferred**: per-process `%LOCALAPPDATA%` files (`rc-bridge-tasks-processed.txt`, `rc-bridge-last-seen.txt`) stay where they are — the watcher daemons own the `bridge_*` files in `ops/runtime/`, and refactoring those touches frozen daemon internals.
- **`heartbeat --once`** added for testability — original was an unkillable `while True:`. Default behaviour unchanged.
- **Frozen-list unchanged**: `bridge_post_result.py` and `bridge_pull_tasks.py` keep `frozen=yes` headers. Future contract changes still require operator approval — but the implication now extends to `bridge_cli.py` since the shims delegate to it.

## Commits
- **75603fe** — `feat(bridge): Phase 6 — consolidate 7 small bridge CLIs into bridge_cli.py (s144)`
- **f764e35** — `docs: sync living docs — Phase 6 complete (s144)`
- Pushed: `87eacc2..f764e35  main -> main`

## What's next
- Futureproofing plan now has every actionable phase ✅. Open RC work is operational, not refactor: vision regions calibration (blocked on live game), gamepc_boot.ps1 hardening, Bridge Watcher acceptance-criteria (need 50+ real-traffic samples), DS calibration pipeline (rewind_history.db staleness).
- Watcher-daemon refactor (`bridge_watcher*.py` → envelope-aware, shared state, BridgeMetrics-instrumented) remains a future Phase if the watcher lifecycle ever opens up.

---

# s143 wrap — 2026-05-09 (Phase 4.1 — dispatch-level soft-warn validator)

## What shipped
- **`dashboard/_dispatch.py`** gained `_validate_request_body(path, body)` called at the top of `dispatch_post` before route lookup. Path-keyed against `_REQUEST_MODELS` (5 paths today: `/api/input`, `/api/command`, `/api/ds-preview`, `/api/bridge/inbox`, `/api/speak`). Soft-warn — never raises, never blocks dispatch; route handlers still run their own existing validation.
- **`tests/phase4_dispatch_validate/`** (new) — 26 tests: registry shape, valid bodies (5 routes × minimal + ds-preview full), invalid bodies (missing required, wrong type, extras-on-`_ForbidExtra`, allow-extra-on-`_AllowExtra`), non-dict bodies (None/list/str/int parametrized), query-string handling, and a `dispatch_post` integration test that monkeypatches `_gather_post` to confirm validator fires before route dispatch.
- **Live verified**: POSTed `{}` to `https://127.0.0.1:8888/api/input` → route returned `400 empty_text` AND log emitted `WARNING rc.dispatch request_body[/api/input] text: Field required` (validator fired). POSTed `{"text":"phase4 smoke"}` → `200 ok`, no warnings.
- **Plan + CLAUDE.md updated**: `RC_FUTUREPROOFING_PLAN.md` Phase 4 closed (4.1 codegen target + 4.3 dashboard JS sub-checkbox flipped — Phase 3.2 had already shipped them; dispatch checkbox flipped + s143 Findings appended; status table 🟠→🟢 2/2 sessions). CLAUDE.md priority #4 ✅. 440 tests pass (was 412, +26 new + 2 drift). Ruff clean. archmap clean. Commit: **791e2db**.

## Key decisions
- **Soft-warn, opt-in by path** (not central hard-validate). Adding a route to `_REQUEST_MODELS` is one line; missing routes pass through silently. Mirrors the operator-approved Phase 4.3 `validate_coaching_payload` pattern. Hard-gating per-route is a future tightening once we trust the contract is stable.
- **5 paths covered, 16 unmodeled paths pass through silently**: loadout/sr-draft/replay-coach/coach-toggle/experimental-*/aram-analyze/decisions-*/health-peer-* don't have Request models in `api_schema.py` yet. No false-warning noise on routes without a model.
- **`_dispatch.py` had `\r\r\n` (double-CR) endings** — same Phase 2.3 gotcha as `coach_integration.py`. Normalized to LF on this edit; commit diff shows `+394/-113` because of the EOL normalization, NOT because the rewrite was extensive.
- **caplog gotcha noted**: `LogRecord.message` is unset until `getMessage()` is called. First-cut test helper used `r.message % r.args`; switched to `r.getMessage()` (canonical). Worth remembering for any future caplog-based test.
- **Phase 4 fully closes** even though 4.3 still has unchecked boxes — those (`bridge_log.py` mirror, OBS publisher) were explicitly marked "out of scope" / "non-existent in tree" in the s129 Findings.

## Do NOT redo
- Don't add hard-rejection (HTTP 400) for invalid bodies in `_dispatch.py` without operator buy-in — soft-warn was the explicitly approved pattern. Silently dropping requests that previously worked would be a regression.
- Don't add the unmodeled 16 POST routes to `_REQUEST_MODELS` without first authoring their pydantic Request models in `api_schema.py` — the lookup will crash if a path maps to None or to something not a `BaseModel` subclass.
- Don't try to hard-rewrite `dashboard/_dispatch.py` to use `_AllowExtra` everywhere "to silence warnings" — `_ForbidExtra` on `InputRequest`/`CommandRequest` is intentional (these have a finite-keyword API surface and any extra field IS a contract drift signal).
- Don't reintroduce CRLF or `\r\r\n` to `_dispatch.py` — file is now LF, archmap header still recognized, all hooks pass.

## What's next
1. **Phase 6 — Bridge consolidation** — still blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`). Only un-shipped phase from the futureproofing plan.
2. **Game-PC LCU agent — phase=Offline persistent** — flagged at session start (probe showed phase=Offline age=-27s); separate diagnosis task if it persists into next session.
3. **Vision regions calibration** — blocked on live game.
4. **Optional follow-on for Phase 4**: extend `_REQUEST_MODELS` coverage to the 16 unmodeled POST routes once their schemas are authored in `api_schema.py`. Low-priority polish; not blocking.

---

# s142 wrap — 2026-05-09 (Phase 7 — WAKEUP_NOTES auto-prune + Conventional Commits hook)

## What shipped
- **`scripts/wakeup_prune.py`** (new, 130 LOC): pure-Python helper that splits WAKEUP_NOTES.md by `\n---\n\n`, identifies sessions via `^# s\d+ wrap` regex, keeps the first N (default 3), and atomically moves the remainder to `docs/history_notes.md` newest-first. Modes: default (prune), `--dry-run`, `--check` (exits 1 if over limit). Idempotent — re-running is a no-op. Self-heals legacy buggy files missing the blank-line-before-rule (28 unit tests cover the round-trip).
- **`.githooks/commit-msg`** (new) + **`scripts/precommit_msg_check.py`** (new, 110 LOC): commit-msg hook validating Conventional Commits subject lines. Pattern: `^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([\w./\- ]+\))?!?:\s+\S`. Skips Merge/Revert/Reapply/fixup!/squash!/amend! auto-subjects; soft-warns over 100 chars; bypassable via `--no-verify`. Activates the moment `git config core.hooksPath .githooks` is set (already required for pre-commit).
- **`tests/phase7_polish/`** (new): 28 unit tests covering split/render round-trip + blank-line preservation + buggy-input self-heal + 4 prune scenarios + check mode + every recent commit shape from `git log` + all canonical types + scopes with `./-/` chars + breaking-change `!` + all skip-prefixes + 9 reject cases.
- **`/done` skill section 6c rewritten** in both project-local (`.claude/commands/done.md`) and user-level (`~/.claude/commands/done.md`) — replaced the 5-step manual archive workflow with a single `py scripts/wakeup_prune.py --keep 3` invocation.
- **Living docs synced**: ROADMAP.md + CLAUDE.md priorities + RC_FUTUREPROOFING_PLAN.md (Desktop) all reflect Phase 7 → ✅ Done. Archmap regenerated to index 2 new phase-7 markers (`scripts/wakeup_prune.py:4`, `scripts/precommit_msg_check.py:4`).
- 414 tests pass (was 386, +28 new), ruff 0 violations, archmap `--check` clean.

## Key decisions
- **Archive target = `docs/history_notes.md`, NOT `docs/_archive/CHANGELOG.md`** as plan said. The existing /done skill already pointed at history_notes.md and 27+ sessions are already archived there. Switching now would either invalidate the existing archive or require a one-shot migration with no upside.
- **`--check` mode but NOT wired into pre-commit (yet)**. Pre-commit-hook enforcement of "WAKEUP_NOTES has ≤3 sessions" would block commits whenever the operator forgot to prune. That's annoying and recoverable. The helper is idempotent and the /done skill calls it; trust the skill, don't bolt on a forcing function.
- **Hook validates SUBJECT line only**. Body and trailers are unrestricted (so `Co-Authored-By:` trailers, multi-paragraph bodies, etc. all pass through). Standard Conventional Commits behavior.
- **Render bug found via dogfood**: first-cut helper stripped trailing `\n` per block + joined with `\n---\n\n`, producing `bullet\n---\n\n# next` (missing blank line above rule). Fixed by `rstrip + add \n` per block, joined with `\n---\n\n`. Round-trip on a buggy legacy file now self-heals to canonical form. Tests for both directions added.
- **Period normalization on phase-marker notes**: docstring lines ending in `.` were stripped to match the existing convention (other markers in the journal don't end in periods). Pre-commit `gen_archmap.py --check` enforces drift.
- **Two done.md copies**: project-local (`C:/Riot Commander/.claude/commands/done.md`) is committed source-of-truth; user-level (`~/.claude/commands/done.md`) is a personal mirror. Edited both for consistency.

## Do NOT redo
- Don't try to switch the WAKEUP_NOTES archive to `docs/_archive/CHANGELOG.md` — `docs/history_notes.md` is the established archive and 27+ sessions are already there.
- Don't add `wakeup_prune.py --check` to pre-commit hook without operator buy-in — it would block commits during normal in-progress work.
- Don't tighten the commit-msg regex to disallow scopes with spaces or `/` — multiple recent commits (e.g. `feat(scripts/wakeup): …`) intentionally use those.
- Don't strip the `Reapply ` skip-prefix — it's emitted by `git revert <revert-commit>` and is a legitimate auto-subject.
- Don't reintroduce `b.strip("\n")` in `render()` — it was the cause of the lost-blank-line bug; test `test_render_preserves_blank_line_before_separator` is the regression.

## What's next
1. **Phase 6 — Bridge consolidation** — still blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`).
2. **Phase 4 remaining** — dispatch-level POST validation in `_dispatch.py` (low priority).
3. **Game-PC LCU agent not posting** — flagged at session start (SessionStart anomaly); separate task, surface for diagnosis if it persists.
4. **Vision regions calibration** — blocked on live game.

---

# s141 wrap — 2026-05-09 (Phase 7 — phase-marker comment normalization)

## What shipped
- **12 RC orchestration phase-markers** converted to `# arch: phase <id> [(YYYY-MM-DD)] — <one-line note>` form across 10 files: `core/bridge_envelope.py`, `core/metrics_cache.py`, `ops/rc_self_monitor.py` (×4), `tools/build_portable.py`, `tft/tft_state_reader.py`, `game_reader/snapshot_normalizer.py`, `agents/agent2_backend/migration_rewind.py`, `tft/tft_live_analysis.py`, `tft/tft_coach_engine.py`.
- **`tools/gen_archmap.py`** extended: new `PHASE_RE` regex + `_collect_phase_markers()` + `_render_phase_journal()`; new sentinel block `<!-- phasejournal:start/end -->` rendered between archmap and god-modules sections of `docs/ARCHITECTURE.md`. Self-skip via `PHASE_SCAN_SKIP_FILES = {"tools/gen_archmap.py"}` to avoid the docstring's example markers polluting output.
- **`docs/ARCHITECTURE.md`**: new "Phase journal" section auto-populated with 11 entries, sorted dated-first by date desc, then undated by phase id.
- **`RC_FUTUREPROOFING_PLAN.md`** (Desktop): Phase 7 phase-marker checkbox + `.rgignore` checkbox flipped; status table updated to 🟠 in-progress (s141).
- 386 tests pass, ruff 0 violations, archmap `--check` clean, py_compile clean. Commit: **48d11be** pushed → origin/main.

## Key decisions
- **Plan estimate vs reality**: plan said "27 phase-markers"; actual universe is ~200+ across 4 numbering systems (RC orchestration Phase 0.X, RC futureproofing 1–7, RC Tier 1–4 milestones, DS engine internal Phase 4 batches in `agents/daemon_slayer/`). Narrowed to RC orchestration/architecture markers only.
- **Excluded**: DS engine batch tags (~100+, own batch system, all dated 2026-05-04, self-document via DS roadmap) and Tier markers (mostly inside frozen files like `web_dashboard.py`, `main.py`, `app/__init__.py`).
- **Skipped frozen file**: `ops/rc_supervisor.py:1188` (FROZEN per CLAUDE.md). Phase 0.13 marker at `ops/rc_self_monitor.py:197` covers same phase; journal not impoverished.
- **Format edge case**: `phase 0.3 (fix 3)` collides with optional `(YYYY-MM-DD)` group; convention is to put qualifiers in the note (`phase 0.3 — note (fix 3)`).
- **Format edge case**: marker line MUST be a complete one-line sentence; the regex is line-based and truncates multi-line continuations. Continuations stay on subsequent comment lines as regular text, not part of the journal note.

## Do NOT redo
- Don't try to mass-convert DS engine `# Phase 4 batch N (2026-05-04):` tags — explicitly out of scope; DS has its own batching system.
- Don't try to convert Tier markers (`Tier 2 #6`, `T2 #8`, `Tier 3 #15`, `Tier 4 #16`) — most live in frozen files; separate convention.
- Don't add phase markers without dates going forward — new markers should include `(YYYY-MM-DD)`. The legacy undated markers were converted as-is to avoid speculative dating.
- Don't edit the `<!-- phasejournal:start/end -->` block manually — pre-commit hook will reject.

## What's next
1. **Phase 7 remaining** — `/wrap` auto-prune of WAKEUP_NOTES, Conventional Commits commit-msg hook. Each warrants its own scoped session.
2. **Phase 6 — Bridge consolidation** — still blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`).
3. **Game-PC LCU agent not posting** — flagged at session start (SessionStart anomaly); separate task, surface for diagnosis if it persists.

---

# s140 wrap — 2026-05-09 (Phase 2.4 — moon_vision_server split)

## What shipped
- **`vision_server/` package** (new): split `moon_vision_server.py` (710 LOC) into 7 internal modules — `_config.py` (75), `_stats.py` (65), `_frame.py` (117), `_relay.py` (118), `_inference.py` (264), `_http.py` (245), `__init__.py` (79). Real code lives here.
- **`moon_vision_server.py`** (kept): reduced to 21-LOC entrypoint shim — `from vision_server import main; sys.exit(main())`. Preserves the file path that `RC-VisionServer` scheduled task and `dashboard/server.py:191` spawn-by-path.
- **`tools/build_portable.py`**: added `moon_vision_server.py` to `_ROOT_PY_FILES` (closed pre-existing bundle gap) + `vision_server` to `_SOURCE_PACKAGES`.
- **`docs/ARCHITECTURE.md`**: god-module table updated, archmap auto-regenerated.
- 386 tests pass, ruff clean, `:8889/health` verified post-restart (PID 17508→10476). Commit: **9cf262a** pushed → origin/main.

## Key decisions
- **Shim pattern, not package replacement**: `moon_vision_server.py` is spawned by file path from two callers (scheduled task XML + dashboard subprocess). Editing those would require touching frozen-adjacent task XML; keeping a 21-LOC shim is cheaper and preserves the contract.
- **Sub-file deviation from plan**: plan listed 4 files (frame_upload, frame_cache, tier_routes, sonnet_escalation). Actual = 6 internal because plan missed LCU relay, liveclient relay, stats, HTTP handler, config. Combined frame_upload+frame_cache (share state) and combined tier_routes+sonnet_escalation into `_inference.py` (both inference handlers feeding same stats).
- **Cross-module state**: `_frame` and `_relay` directly mutate `_stats._stats[k]["bytes"]` under `_stats._stats_lock`. Kept the direct mutation — wrapping it in setters would just create indirection.
- **Pre-existing bundle gap**: `moon_vision_server.py` was NEVER in `_ROOT_PY_FILES` — portable builds have been shipping without the vision server. Fix bundled with this change.

## Do NOT redo
- Don't try to import from `moon_vision_server` (Python module) — the file is path-spawned, not import-consumed. Use `from vision_server import …` instead.
- Don't delete `moon_vision_server.py` thinking it's dead code — RC-VisionServer scheduled task XML hardcodes that path.
- Don't switch `python.exe` → `pythonw.exe` in the task XML without operator approval; that's a console-window cosmetic, not a Phase 2.4 scope item.

## What's next
1. **Phase 6 — Bridge consolidation** — blocked on operator approval for frozen files (`bridge_post_result.py`, `bridge_pull_tasks.py`, `process-bridge-tasks.md`).
2. **Game-PC LCU agent not posting** — SessionStart anomaly flagged at session start; separate task, surface for diagnosis.
3. **Vision regions calibration** — blocked on live game.

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

- **s135 (2026-05-08)** Phase 3.1 CSS split — `scripts/extract_css_panels.py` one-shot extractor; 13 CSS panel files in `web/css/panels/`; `dashboard.css` → 25-line @import router (5812→25 LOC). Dashboard screenshot verified.
- **s133 (2026-05-08)** Phase 3.1 ESM panels — `tools/extract_panels.py`; 7 panel JS modules extracted from main.js (8225→4189 lines). Commit `38ac760`.
- **s132 (2026-05-08)** Phase 3.1 ESM lib/ — `web/js/main.js` + 4 lib modules (helpers/state/items_index/idempotent_render); ESM module type on index.html. Commit `7bbf032`.
- **s131 (2026-05-08)** TFT 17.3 patch update — Morgana 4g, Anima/Stargazer reworks, Primordian AVOID, AP comps buffed, Horizon Focus removed. `tft_pbe_data.py` + `tft_pbe_engine.py`. Commit `0e9617b`. 380 tests pass.
- **s130 (2026-05-08)** CI fix — anthropic try/except guard in `coach_integration.py`; pydantic added to `requirements.txt` + CI. Commit `808afea`. 380 tests green.
- **s129 (2026-05-08)** Phase 4 contracts/schemas — `core/coaching_payload.py` (5 pydantic models, soft-validate), `dashboard/api_schema.py`, `core/bridge_envelope.py`, `docs/API.md` (40 routes). Commit `31bbe4f`. 4.2 tool rewrites blocked (frozen files). JS typedef codegen deferred to Phase 3.

---

# s128 wrap — 2026-05-08 (Phase 5 — CI gate + smoke harness COMPLETE)

- Commit `d21f533`. Fixed test_app_authority.py (52→0 failures, _HeadlessApp subclass). Arena/Brawl golden fixtures added (343→380 tests). phase2_smoke suite (31 tests, all 5 coach modes). CI: ruff + phase8_smoke wired. ruff.toml 101→0 violations. Bug fix: tft_live_analysis.py:274 `_j.loads`→`_pj.loads`.

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

---

# s108 wrap — 2026-05-06 (WT flash fixes — Legion + Game-PC)

- `dashboard/server.py`: `creationflags=0x08000000` on vision server Popen (commit `cab0ce4`). Game-PC `gamepc_bridge_daemon.py`: `--dangerously-skip-permissions` fix + DEVNULL suppression — stopped 807+ crash-loop invocations per day.

---

# s107 wrap — 2026-05-06 (API cost audit + dynamic debounce + CLAUDE.md slim)

## What shipped
- **Vision loop gate** — `_run_vision()` guards in ARAM/Arena/Brawl coaches: `if self._fetch_game_data() is None: return`. Kills 24/7 Sonnet burn when no game is active (was 84% of LoLOverlay key spend on May 4).
- **Dynamic debounce** — all 3 coaches: `_STABLE_DEBOUNCE_S` class attr (ARAM 25s / Arena 22s / Brawl 20s). `_on_state_received` sets `self._DEBOUNCE_S` to stable rate when no meaningful state change; snaps back to fast rate on dead_enemies / items / level / hp_pct drop ≥10.
- **CLAUDE.md slimmed** from 355→109 lines. Deep docs moved to `docs/AGENTS.md` (new) + `docs/DAEMON_SLAYER.md` (new). Bridge spawn cost note added.
- **Settings cleanup** — both `.claude/settings.json` files: removed `typescript-lsp` plugin; `additionalDirectories` `C:/` → `C:/Riot Commander`.
- Commits: `5658b1f` (vision gate + debounce + CLAUDE.md slim)

---

# s117 wrap — 2026-05-08 (TFT patch 17.2)
TFT patch 17.2: tft_pbe_engine.py system prompt + tft_pbe_data.py ENCOUNTERS (21) + GOD_BLESSINGS (24) + trait balance. tft_set17_meta.json -> 17.2. commit be3d168. DDragon still shows "16.9.1" (stale cache) — actual patch 26.9; coaching functional.

---

# s166 — 2026-05-10 (Phase B LCU agent handlers + Loading view scaffold; UI paused)

5 new dashboard-→ LCU command handlers (ban/pick intent + position/pick-order swap + augment-intent stub) shipped in `tools/gamepc_lcu_agent.py` so s164+s165 dashboard commands actually route to the client; champ-select state extended (`active_round`, `is_brawl`, swap lists, `arena_teams`, `augments` scaffold, per-player `summoners`). Phase 3 step 4 Loading Screen view scaffold (`view-loading`, `flow_04` fixture, opt-in via `?ld=1` / GameStart phase). 30 new tests under `tests/phase_b_champ_select/test_lcu_agent_phase_b.py` (665 total). Operator paused UI work at session end and directed `NEXT_SESSION_PLAN_2026-05-10.md` as bootstrap for s167.

---

**s125 — 2026-05-08** (9234d0f) Phase 1.1 knowledge architecture: docs/_archive/ created, 23 dated artifacts moved, 4 living docs authored (ARCHITECTURE.md 136 lines, OPERATIONS.md 153, BRIDGE.md 136, ROADMAP.md 64). Bootstrap reduced from 2000+ → 492 lines.

**s124 — 2026-05-08** (no commit) RC_FUTUREPROOFING_PLAN.md authored on Desktop by Opus 4.7 1M context — 7-phase leverage-ordered refactor plan. No code changes.

---

- **s123 2026-05-08** — rc_facts bridge probe rewrite (04a305b): `/api/health/all` peer probe replaces stale log-age heuristic. DS server health line added. RC-DaemonSlayer false exit-1 anomaly suppressed (server healthy; task runs as SYSTEM, can't write logs).
- **s122 2026-05-08** — Game-PC socket exhaustion (STATUP.GG/Overlay Platform M 17,463 kernel handles → WSAENOBUFS). `taskkill /F /PID 3340`; restarted RC-WatcherHealthPublisher-GamePC + RC-BridgeWatcher-GamePC tasks. TDD skill installed fleet-wide.
- **s121 2026-05-08** — Fleet model downgrade → `claude-sonnet-4-6` 200k. 5 plugins disabled on Legion (nimble, ralph-loop, playwright, chrome-devtools-mcp, firecrawl); Peer mirrored via bridge task. MEMORY.md pruned 6 stale entries.
- **s120 2026-05-08** — RC dev panel shipped (7424e24): `⚙ Dev / Sim Preview` view with SIM FIXTURES, VISION STATUS, RC LOG TAIL cards; `dashboard/routes_dev.py` + CSS view-switch.
- **s119 2026-05-08** — Roadmap: 5 items shipped — Phase 4 SessionStart enrichment (d069e4d), DS startup diagnostics (04e63d4), SR coach objective_window fix (e8d976b), bridge introspection `?source=` param (5a790d2), ROADMAP closures (items_index rotation, vision_token policy).
- **s118 2026-05-08** — Bridge Watcher node-load restraint (f3ae4cb): `_check_rc_health()` downgrades auto-action to escalate when RC degraded; push notifications suppressed during degraded cycles; 30/30 selftests pass; watcher pid=15004.
- **s116 2026-05-08** — Game-PC boot fix + Smite jungler detection (1ef54e3/2229d89/6bec3ce): `gamepc_boot.ps1` now calls `start_gamepc_claude.ps1`; Smite-based 3-tier jungler cascade in `game_reader.py`; 8 new tests.
- **s115 2026-05-07** — DS calibration game_id wiring (d66d14b): `gamepc_lcu_agent.py` fetches `gameData.gameId` in-game; `game_reader.py` reads `/latest-lcu` relay; `coach_integration.py` passes game_id to `log_ds_run()`.
- **s114 2026-05-07** — Bridge Watcher Phase 3 (6dd91ff): `--dry-run` mode, artifact rotation, self-healing watchdog thread; 21/21 selftests.
- **s113 2026-05-07** — Bridge Watcher Phase 2 (05983a4): adaptive cadence (`_read_mode()`), active/sleep/auto modes, `/api/bridge/cadence`, `/sleep`+`/wake` slash commands.
- **s112 2026-05-07** — Bridge Watcher Phase 1 (f6095a0): sliding 24h event ring, push notifications, RC-DaemonSlayer result=1 fix.
- **s111 2026-05-06** — Infrastructure fixes: RC-BridgeWatcher + RC-Phase3-Supervisor restarted; `claude-rc.ps1` `/loop` removed; ROADMAP fleet-health items marked ✅.
- **s110 2026-05-06** — Cross-Claude sync Phase 3 + DS/roadmap doc cleanup. `_lessons_summary()` in `rc_facts.py` for SessionStart hook (4c4ce1a); ROADMAP/CLAUDE/README doc cleanup (b6d02ae).
- **s109 2026-05-06** — Memory library: 6 new memory entries (feedback + reference patterns). No code changes to RC repo.

---

## s106 wrap — 2026-05-05 (DaemonSlayer flash fix + preflight expansion)

### What shipped
- **`ops/RC-DaemonSlayer.xml`** — `python.exe` → `pythonw.exe`; task reinstalled. No more console flash on boot/restart. DS live at `:8893` engine=0.60.0 patch=16.9.1.
- **`start_claude.ps1`** — added RC-DaemonSlayer + RC-Phase3-Supervisor + RC-BridgeWatcher preflight checks; `:8893` + `:8890` HTTP probes; final `claude` launch fixed to `--name "Legion"`. commit `0d1b545`.

### Do NOT redo
- RC-DaemonSlayer XML is already pythonw.exe.

---

## s92–s103 detailed notes (2026-05-04 – 2026-05-05)

### s103 — 2026-05-05 (DS champ-select panel + dashboard bug fixes)
- **DS champ-select panel** `112350a` — `#cs-ds-block` + `/api/ds-preview` endpoint. Fires once per (champion, mode). Item tiles with +Ndps tooltips.
- **SR SSE mode fix** `5ee58b6` — `_state_builder.py` returned `mode_key="game"`; JS `driveNow` dropped all SR state. Fixed to `"sr"`.
- **Item icon cache race** `f5ce231` — `_itemResolveCache` cached null before `items_index.json` loaded; idempotency sig blocked re-render. Fix: clear cache + tile sigs on ITEMS load.
- **Augments pill fix** `5ee58b6` — CSS `static-pill` overrode `.hidden`; now `display:none !important`.
- **`/done` §6b living-doc sync** `d6fbce0` — ROADMAP/CLAUDE.md/README updated as part of done ritual.

### s102 — 2026-05-05 (SR coach signature hash fix + RECOMMENDED panel)
- **SR coach hash fix** (frozen, user-approved) — `_state_signature` fallbacks had wrong key names vs `_convert` output. hp_bucket/mana_bucket/gold_bucket/level all fixed. Coach now re-fires on HP changes, gold/item thresholds, level-ups, deaths.
- **RECOMMENDED panel** — `dashboard.js` falls back to `sr_items` when `item_build` empty; `next: true` items populate RECOMMENDED.
- **SR API key** — `API-Key-Claude.txt` written from CLI env to unblock SR coaching.

### s101 — 2026-05-05 (DS health indicator + Item Build DS picks panel)
- **DS health in `/api/health/all`** `50248a7` — probes `:8893/health`; DS down → yellow rollup.
- **Health dot tooltip** — DS engine status: `DS engine up · v0.60.0 · 547i/168c`.
- **Item Build panel DS section** — `#ib-ds-block` renders `daemon_slayer_picks` as `.ds-chip` compact chips with green delta-dps text.

### s100 — 2026-05-05 (Tiered vision + open-items cleanup)
- **Tiered vision** `46e9fb8` — `GameVisionReader.read_tiered()` + `read_or_escalate()` wired into ARAM/Arena/Brawl. OCR first; `timer` canary gates Sonnet escalation. Expand by calibrating `data/vision_regions.json`.
- **Open items** `41c87bc` — rune writer SR shard3: 5002→5001; items_index.json alias collision sorted by ID length; Yunara phantom dups: zero-duration exit + 90-min dedup.

### s99 — 2026-05-05 (Daemon Slayer batch 64 — Malignance + Stage 5 calibration)
- **Batch 64** `e7c4cd9` — Malignance Hatefog promoted (ENGINE_VERSION 0.60.0, 929 tests). New `CallContext.ult_casts_per_sec` + `ult_rates.py` (172 champions from rewind_history.db). Deferred: 3 (Lightning Braid, Kinkou Jitte, Mejai's Arena).
- **Stage 5 calibration pipeline** — `core/ds_calibration.py` + `data/ds_calibration.jsonl`; all 4 coaches log DS picks per tick.

### s98 — 2026-05-05 (Daemon Slayer batch 63 — blocked items resolved)
- **Batch 63** `e56e878` — Hellfire Hatchet (CD=15s confirmed), Fiendhunter Bolts (CD=45s confirmed), Innervating Locket Fill the Soul promoted. ENGINE_VERSION 0.59.0, 922 tests.
- Key insight: check Meraki `passives[].cooldown` before deferring "ability-triggered" items.

### s96 — 2026-05-04 (ARAM DS-before-Haiku refactor + documentation sweep)
- **ARAM coach DS-before-Haiku** `3b84949` — DS `rank_for()` before `messages.create()`; `{ds_picks}` injected into user turn; pre-DS hardcoded item rules removed (−37% system prompt ~1,849→1,170 tokens).
- **Documentation sweep** — CLAUDE.md, README.md, ROADMAP.md updated. `DS_COMPLETION_ROADMAP.txt` created on Desktop.

### s95 — 2026-05-04 (Daemon Slayer batches 57–62)
- Batches 57–60 `9f128c4..864e65d` — `caster_bonus_armor` + `caster_lethality` added; Void Immolation, Golden Spatula, Darksteel Talons, Bastionbreaker, Reality Fracture promoted. ENGINE_VERSION 0.57.0, 899 tests.
- Batch 61 `2148ed2` — Zaz'Zak's Realmspike + Bloodsong (spellblade + Expose Weakness damage_amp). 899 tests.
- Batch 62 `dcfeb63` — Cruelty dual-variant (Arena 447109 + SR 667109). ENGINE_VERSION 0.58.0, 911 tests.

### s94 — 2026-05-04 (Daemon Slayer batches 54–56)
- Batch 54 `ded3d01` — `bonus_ap_stacked` (Mejai's) + `bonus_as_conditional` (Yun Tal 27% uptime) + Sword of the Divine. ENGINE_VERSION 0.55.0, 843 tests.
- Batch 55 `e054c1c` — 46 defensive_only entries; DDragon purchasable coverage COMPLETE (547 entries, 850 tests). Coverage gate test added.
- Batch 56 `ede9c89` — `ap_amp_pct_per_100_caster_hp` schema; Demonic Embrace Arena. ENGINE_VERSION 0.56.0, 856 tests.

### s93 — 2026-05-04 (Daemon Slayer batches 50–53)
- Batch 50 — `armor_reduction_flat` + `mr_reduction_flat` schema; Flesheater promoted.
- Batch 51 — Fated Ashes (Inflame) + 5 defensive components.
- Batch 52 — Night Harvester, Luden's Echo, Bloodletter's Curse SR; ability-cast schema resolved via `every_n_seconds`.
- Batch 53 `255dd22` — Hamstringer Scour + Stormsurge Squall. ENGINE_VERSION 0.54.0, 829 tests.

### s92 — 2026-05-04 (Daemon Slayer batches 38–49)
- Batches 38–41 `0369403..bc61b4c` — Giant Slayer schema; `mr_reduction_pct`; Arena re-skins; Navori key collision fix. 494 tests.
- Batches 42–43 `b92301f` — Arena 222xxx/223xxx/224xxx/32xxxx mirrors; 83 defensive_only. 530 tests.
- Batches 44–45 `6eaccae` — Sheen spellblade; Tiamat Cleave; Bami's Cinder Immolate; boots. 558 tests.
- Batches 46–47 `8795097` — Divine Sunderer Arena; Demonic Embrace; Blighting Jewel. 587 tests.
- Batches 48–49 `1230dca` — 1xxx components complete; Spellslinger's Shoes dual-pen; Arena Arena. ENGINE_VERSION 0.53.0, 603 tests.

---

## Session ledger s27–s91 (condensed — from WAKEUP_NOTES compaction 2026-05-04)

All narrative detail in `ROADMAP.md §1` and `git log`.

| Session | Date | Key commit(s) | Theme |
|---|---|---|---|
| s27 (a–u) | 2026-05-01 | 778971d..957dab7 | All Tier 1–4 audit items; asyncio migration (T2 #8 C1–C5); tkinter-free |
| s28 | 2026-05-02 | a38d002..7307e6a | RC↔Peer cross-Claude bridge live (Tailscale); inheritance arc |
| s29 | 2026-05-02 | 7223afe, c4c9e07 | Game-PC joined tailnet as `gamepc-rc`; bridge_monitor sidecar live |
| s30 | 2026-05-02 | 645e041..4c2514d | One-click gamepc_boot.ps1; cross-Claude learning-sync vision doc |
| s31 | 2026-05-02 | — | Phase 3 supervisor; dashboard OWNED fix; cron echo silenced |
| s32 | 2026-05-02 | c58e689, dc73303 | Live stat mirror; ally_comp overwrite fix |
| s33–s36 | 2026-05-02–03 | 0302fc7..0fcf102 | Action label decay fix; bridge `/messages` alias; arena advisor v1 |
| s37–s45 | 2026-05-03 | (DS Phase 1) | Daemon Slayer extractor; lolmath chunk topology; champion builds refresh |
| s46–s55 | 2026-05-03 | (DS Phase 2) | DS engine scaffolding; stat walk; on-hit framework; 40 items |
| s56–s65 | 2026-05-03 | (DS Phase 3) | DS Arena items; beam search; augment schema; 150+ items |
| s66–s75 | 2026-05-03–04 | (DS Phase 4) | DS spellblade/unique-passive; Arena mirror pass; 300+ items |
| s76–s80 | 2026-05-04 | (DS batch 20–24) | Rune writer shard3 fix; Bridge Watcher hardening; Bridge Pending UI |
| s81–s84 | 2026-05-04 | (DS batch 25–28) | Arena augment persistence; Meraki bulk switch; vision tracker polish |
| s85–s88 | 2026-05-04 | 0cecfa3..28d2a93 | DS batches 29–32; magic_amp schema; Rabadon's; 550 tests |
| s89 | 2026-05-04 | 0cecfa3 | DS batch 33: ability-burn promos, caster_bonus_hp, 367 tests |
| s90 | 2026-05-04 | 1bd105d, 6b04992 | DS batches 34–35: magic_amp_pct schema, dual-pen, spellblade |
| s91 | 2026-05-04 | 8f7811b, 8d208c3 | DS batches 36–37: TRUE damage type, Arena 443/447 sweeps, 428 tests |
