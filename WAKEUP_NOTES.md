# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 archived to `docs/history_notes.md`. Only the last 3 sessions kept here.

---

# s173.1 wrap — 2026-05-12 (audit thread continuation — 5 commits)

**operator slot complete** — `/what's-next` daytime run. Closes s173 audit findings #2 + #3, plus 3 bonus items spotted while in the area. All 5 commits CI-green on first push.

Operator brief: "1 then any other items listed in roadmap, readme, or other files for tasks to do, 2 will be later today in about 5 hours." Item 1 = s173 finding #2 (ENGINE_VERSION doc-sync). Item 2 = Active Match step 5 (deferred 5 hours per operator). Slot scope: anything well-scoped, no operator-approval-blocked, no live-game-blocked.

## Ships

| Commit | Theme |
|---|---|
| [5c8b53e](https://github.com/Remus3/riot-commander/commit/5c8b53e) | `docs:` sync ENGINE_VERSION 0.60.0 → 0.61.0 across 6 living docs (8 lines) — closes s173 finding #2. Historical references in archived notes + batch comments intentionally untouched. |
| [802ad90](https://github.com/Remus3/riot-commander/commit/802ad90) | `docs:` sync DS test count 929/911 → 949 across living docs — spotted drift while doing #2. Canonical 949 from `py -m pytest agents/daemon_slayer/`. Dated planning docs left at 929 (write-time accurate). |
| [38ca915](https://github.com/Remus3/riot-commander/commit/38ca915) | `test(snapshot_panels):` adversarial fixtures + mode-transition coverage; fix s151 `gameTime` ref-error. 4 new fixtures (no_coach / null_fields / empty_strings / out_of_range) + 2 new tests + closes the CLAUDE.md item-10 s151 follow-up (`panels/map_state.js:720` referenced bare `gameTime` outside the IIFE scope; only fired when `game_time_s` was numeric — adv_out_of_range surfaced it via -42). 11 of 11 tests green (was 6). |
| [16334b2](https://github.com/Remus3/riot-commander/commit/16334b2) | `refactor(champion-aliases):` unify three drift-prone maps via canonical JSON — closes s173 finding #3. New `web/data/champion_aliases.json` as source of truth; `web/js/lib/items_index.js` + `web/js/dashboard.js` fetch async; `tools/daemon_slayer_extract.py` reads at import-time. New `tests/test_champion_aliases.py` (4 regression guards). `agents/daemon_slayer/server.py:_resolve_champion_id` is a different pattern (builds revmap from DDragon data dynamically) — explicitly not a drift candidate. |
| [51e0da7](https://github.com/Remus3/riot-commander/commit/51e0da7) | `fix(console-pipe):` per-entry queue removal preserves entries on replay failure — closes BACKLOG item "Console-pipe localStorage flush failure-recovery loop". The original `flushQueueAfterSuccess` called `localStorage.removeItem(QUEUE_KEY)` BEFORE issuing replay fetches with `.catch(() => {})`; mid-flush endpoint outage lost every queued entry. Now each entry stays queued until its own 2xx; failures retry on next pipe-success (QUEUE_MAX=50 bounds growth). |

## Findings

- **The adversarial harness paid for itself on first run** — `test_adversarial[adv_out_of_range]` surfaced the s151 `gameTime` ref-error that had been pending as a "follow-up" deferral for ~10 days. The bug was previously invisible because no real game state has `game_time_s: -42`; only an adversarial fixture exercised the path. Closing the loop: BACKLOG-driven test design caught a CLAUDE.md item-10 known-unfixed bug. Worth keeping in mind for future test-coverage decisions — adversarial fixtures aren't just defense, they're discovery.
- **Champion alias unification was 5 files not 3** — the s173 wrap listed three sites (items_index.js, daemon_slayer_extract.py, dashboard.js). While implementing I checked one more candidate the audit brief had flagged (`core/champion_aliases.py` doesn't exist) and audited `agents/daemon_slayer/server.py:_resolve_champion_id` — which is a different pattern (dynamic revmap from DDragon `champions[].name`) and NOT a drift candidate. Test guard at `tests/test_champion_aliases.py:test_js_consumers_reference_canonical_file` greps both JS files to catch future regressions where someone re-hardcodes the map.
- **Console-pipe identity match by (ts, message-prefix)** — object identity doesn't survive the JSON round-trip through localStorage, so `_dropQueuedEntry` matches on (ts, message[:100]). Collisions are benign — at worst we drop a near-duplicate that retries on next flush. Heuristic chosen over assigning UUIDs at enqueue time to keep the fix surgical.

## Files touched this slot

**Doc-sync (2 commits, 9 line edits):**
- `CLAUDE.md` · `README.md` (×3 lines) · `docs/DAEMON_SLAYER.md` · `docs/ARCHITECTURE.md` · `BRIEF.md` · `NEXT_SESSION_PLAN_2026-05-10.md`

**Code + tests (3 commits, 8 files changed, 5 new):**
- `web/data/champion_aliases.json` (NEW)
- `web/js/lib/items_index.js` · `web/js/dashboard.js` · `web/js/main.js` · `web/js/panels/map_state.js`
- `tools/daemon_slayer_extract.py`
- `tests/test_champion_aliases.py` (NEW)
- `tests/snapshot_panels/test_panel_snapshots.py`
- `tests/snapshot_panels/fixtures/adv_no_coach.json` · `adv_null_fields.json` · `adv_empty_strings.json` · `adv_out_of_range.json` (4 NEW)

## Open items carried forward

- 🟡 **Active Match view step 5** — deferred per operator to ~5 hours after slot start. Sub-items: zen-lock in-game + RIGHT NOW fold + bridge-pending → dev-panel button + fleet view removal. CLAUDE.md item 18.
- 🟡 **s173.2 finding — `.claude/commands/process-bridge-tasks.md` is gitignored**. The s173.2 unification edit is live on Legion but won't ride with a fresh clone or deploy. Two paths for durability: (a) track a canonical at `tools/process-bridge-tasks-legion.md` mirroring the Peer template pattern + add it to CLAUDE.md frozen list; (b) accept local-only since the file lives alongside other local config (bridge secrets, MCP URLs). No urgency — runtime gate is correct on this machine.
- 🟡 **Live champ-select verification** — the Hunt 5 substitution from s173 (`907543f`) and the s171.8 cache-bust unification both await a real ChampSelect pop to reconfirm `_fetchDsPreview` fires with the correct mode label and the unified asset-hash propagates `champ_select.js` updates.
- 🟡 **dashboard.js console-pipe mirror** — same pre-emptive-remove bug at line 8109 left unfixed since the wrap noted dashboard.js is dead code (web/index.html only loads main.js). Sync deferred to land alongside any future dashboard.js removal.
- 🟡 **BACKLOG `MatchDB` thread-safety validation** entry is stale — `core/match_db.py` was refactored 2026-04-28 (audit proposal 1.2) from RLock to WAL + per-thread connections. The FIX-021 lock referenced in BACKLOG no longer exists. Worth a one-line BACKLOG edit when next in the area.

## Pending verification

🟢 All snapshot_panels tests + full pytest suite green throughout slot:
- After 38ca915: 821 (full) + 11 (snapshot_panels) = 832 passing
- After 16334b2: 836 passing (snapshot_panels rolled into full run + 4 new alias tests)
- After 51e0da7: snapshot_panels 11/11 — happy path unchanged for console pipe

🟡 Live verification of the s151 fix awaits next real game (current liveclient empty per startup probe). The `gameTime` ref-error in `_tickObjectiveCountdowns` fires only when `_currentGameTimeS()` returns a number, which means an active game with `game_time_s` populated. Adversarial fixture verified it; live confirm is bonus.

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
