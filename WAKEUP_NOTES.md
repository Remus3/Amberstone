# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-18 - s237: builders.py payload-boundary split + _enrich_from_lcu coverage (`2d1993c`, pushed)

Executed the s236 next-priority order (AUTONOMOUS_AUDIT s5): 4.E then 4.C, paired so the split is provably behavior-preserving.

- **`2d1993c` (pushed `29bb13c..2d1993c main`).** **4.E first:** `tests/test_builders_enrich.py` - 31 characterization tests for the untrusted-LCU parser `_enrich_from_lcu` (6 guard-clause bails return `{}` not None; full parse shape; the high-value regression anchors = `firstDargon` LCU-typo key, `cs=minions+neutral`, `heal_plus_shield=heals+shields`, 1-indexed `playerAugment`, single `is_me`; SR/Mayhem/Arena fixtures; odd-field coercion). Written + green on the PRE-split baseline.
- **4.C split:** `dashboard/builders.py` 1428 -> 288 LOC. Home / LCU-enrich / last-match clusters extracted **byte-verbatim** via an audit-gated atomic-splice script (boundary sentinels; script deleted after) into `builders_home.py` (353) / `builders_lcu_enrich.py` (387) / `builders_last_match.py` (478). builders.py keeps session/history/loadouts/diagnostics + **re-exports all 21 public names** -> every `from dashboard.builders import _x` caller (and web_dashboard's re-bind) unchanged. No circular import, no `builders_common` needed (shared `_load_match_rows`/`_ts_to_epoch`/`SESSION_GAP_S` only used by the retained clusters). Newly-authored module headers are ASCII; relocated bodies kept the original non-ASCII rendered-string chars verbatim.
- **Verified:** py_compile (8 modules) + ruff clean; full `tests/` **1314 passed / 30 subtests / 0 failed**; facade smoke (correct `__module__`, no cycle); RC reloaded clean (pid 17292 -> 11020, last_reload_ok=true); `/api/home/summary` `/api/last-match` `/api/history` `/api/diagnostics` all 200 live.
- **Don't-redo:** the split is done + behavior-proven - do NOT re-extract or re-investigate builders boundaries; `dashboard.builders` is now a facade, callers import unchanged.
- **NEXT (AUTONOMOUS_AUDIT s5 order, item 4):** product-level - competitive opportunity #2 (per-user pick-ban foregrounding) or #3 (on-demand VLM coach), operator-directed. Remaining 4.C MED candidates: `adaptation_hint.py` (1602) splittable autonomously; `agents/supervisor.py` (2312) is FROZEN -> needs operator approval; `effects.py` (5692) engine-core = reviewed-only, never autonomous. DS conditional arc stays operator-CLOSED (s232).

---

# 2026-05-18 - s236: dead dashboard.js quarantine + agent3 pre-existing-rot cleanup (3 commits, CI green)

Two scoped follow-ups off the `9bba79a` AUTONOMOUS_AUDIT next-priority order. All pushed, CI green.

- **`141ec91` + `7b05c78` - dashboard.js quarantine (closes AUTONOMOUS_AUDIT staged #3 - do NOT re-investigate).** `git mv web/js/dashboard.js` (8531 LOC dead, zero `<script>`/import) -> `docs/_archive/2026-05-18-dead-dashboard-js/` (100% rename, reversible). **Operator decision (AskUserQuestion): "Repoint to live UI"** - `ui_applier.py` ALLOWED_PATHS + `ui_feedback.py` parser repointed off dead dashboard.js/sim.js onto live `index.html`/`main.js`/`panels/` + `css/panels/base.css`; dead sim/JSON branch removed; smoke-verified vs the REAL live base.css. **Spec correction (don't re-litigate): `web/css/dashboard.css` is LIVE** (the `<link>`ed `@import` aggregator) - only dashboard.js was dead. A1 mirror + 10 dead-content tests deleted; `test_round42` rewritten w/ repoint guards; 9 stale comments generalized; stale `js/dashboard.js` removed from `_static.py` + `routes_state.py`; `api_surface.csv` regenerated; `API.md`/`ARCHITECTURE.md` synced.
- **`c5f42a4` - agent3 ~30-failure rot (the flagged follow-up; do NOT re-triage).** 3 distinct root causes: (1) `test_round40.py` DELETED - genuine s218 sim-removal orphan (16 tests, zero live refs). (2) `test_auto_analyze`/`round12`/`round17`/`warm_ui_watchdog` (14) were INNOCENT pollution victims - a `tests/` `unittest.IsolatedAsyncioTestCase` (`tests/preflip_mode/test_file_ingest_mirror.py`) leaks asyncio's running-loop slot under full-suite load; fixed at root via an autouse asyncio-isolation fixture in `agents/agent3_testing/suite/conftest.py` (s223/item-87 pattern), victim tests untouched. (3) `test_scheduler_lock` race = `TimeoutExpired` under saturation; bounded-retry v2 (corruption still hard-fails).
- **Key fact for next-session-me:** the true spec-triplet baseline was **33 pre-existing failures**, NOT "0" - the WAKEUP/spec "0 failed" was a `tail`-masked / tests-only number. agent3-alone went **17 -> 356 passed/0 failed**; SLICE A proved the polluter is `tests/`-only (daemon_slayer innocent). CI never runs `agents/agent3_testing` so it's unaffected.
- **Process note (don't repeat):** I mishandled full-triplet verification - launched a 2nd triplet without cleanly stopping the 1st (Git-Bash mangled `taskkill /F`), two ~3900-test runs starved each other. Per operator (option 2) the agent3 commit shipped on the deterministic agent3-alone + root-cause proof, NOT a clean full triplet. If you want the clean triplet, run it ONCE (no concurrency); expect ~0 failures.
- **NEXT (AUTONOMOUS_AUDIT s5 order):** `builders.py` split (4.C lowest-risk) + `_enrich_from_lcu` test coverage (4.E). Phase 4(d) already shipped `aaa9c5a` (pre-this-session). DS conditional arc stays operator-CLOSED.

---

# 2026-05-18 - Autonomous audit+refactor+research session shipped `9bba79a` (CI green) - executed the PIN directive

Executed WAKEUP Part-2 (the pre-authorized autonomous mega-session). Ran a competitor-research subagent + a code-health-audit subagent in parallel, implemented the highest-leverage findings, fully tested, shipped, CI verified green. Full deliverable: **`C:\Users\Administrator\Desktop\AUTONOMOUS_AUDIT_2026-05-18.md`** (research + all 15 audit findings + staged execution specs + next-session priority order) - read it for the full picture; this is the condensed hand-off.

**Shipped `9bba79a` (pushed, CI run 26021518544 = success):**
- **#1 (HIGH, real live bug):** the in-game Build Chooser threw `ReferenceError` every render - `item_build.js:361` called `_csDiffItemIds` which it never imported (`champ_select.js` defined but did not export it). Moved the helper to shared `web/js/lib/items_index.js` as `diffVariantItemIds` (avoids a new panel->panel coupling); wired the live caller; cleaned the now-permanently-dead `_csLoadout` typeof guard in item_build.js.
- **#2 (dead code):** removed the s208-carried **558-LOC** orphan cluster from `champ_select.js` (3153 -> 2595) - `_csLoadout`/`_csNormalizeMode`/`_csSetStatus`/`_csDiffItemIds`/`_csRenderBuildList`/`_csMarkSelectedRow`/`_csOnBuildRowClick`/`_csApplyLoadout`/`_csOnChampionOrModeChange`/full `_srDraft*`. All zero-caller in the live module (only dead `dashboard.js` referenced them). Audit-gated atomic splice (guards assert exact boundaries). `_csChampName`/`_csChampImg` confirmed LIVE and preserved.
- **#4 (HIGH, robustness):** `lessons_receiver._fetch_bridge` did a bare urlopen+json.loads; any bridge outage/malformed response crashed `/process-incoming-lessons`. Now fail-soft to `[]` (callers already treat `[]` as "no lessons").
- **#5 (engine drift):** `ability_dps._mitigation_factor` carried a byte-identical copy of `dps._armor_factor`'s resist curve - one-sided edit would silently desync DPS/ability-DPS/burst. Folded onto the single source of truth + 7-test parity drift-guard. **Provably behavior-preserving** (full DS value-pinning suite stayed green) -> deliberately **NO ENGINE_VERSION bump / NO DS restart** (no-op refactor; running :8893 math identical; matches ROADMAP-85 precedent).
- **only_item_ids carry-branch:** `rank_for` (carry/dps) silently dropped the candidate whitelist all 5 sibling rankers thread; ADC build-order plan restricted to a curated pool no-oped. Threaded + passed via `rank_for_primary_archetype` carry fall-through. Client-only (server `/rank` already supported `only`).
- **#10:** `bridge_monitor.py:86` bare `try:/except: pass` one-liner -> formatted + debug log. Other 251 broad-excepts reviewed: mostly deliberate documented defensive boundaries, intentionally left (no-over-engineering; audit said "not a blanket fix").
- **+20 regression tests** (7 mitigation parity / 7 lessons_receiver incl. coverage-gap #13 / 6 only_item_ids). **Full suite 3516 -> 3536 passed, 0 failed.** ruff + py_compile clean. pre-commit hooks green.

**STAGED, NOT done (deliberate scoped-grant judgment - precise specs in the Desktop .md sections 4.A-4.E):**
- **#3 dead `dashboard.js` (8531 LOC):** the audit's "just move it, lowest effort" was WRONG - it has real test/agent coupling (`tests/test_champion_aliases.py:85` dead-mirror, `agent3_testing` round tests, `agent4_coach_mentor/ui_applier.py:33` allowlist, `data/api_surface.csv`). Quarantining blind would break tests. 7-step spec in 4.A. (Classic `feedback_audit_proposals_are_intent.md`.)
- **Phase 4(d) `unique_passive_key` exposure:** pre-approved + seam confirmed trivial (`rank.py:337` `cand_key` already computed, only surfaced on dead-collision) but it is ~10 files across all 6 ranker modules + client + planner + ENGINE bump + DS restart. Risk = mechanical breadth at context tail, not design. Staged with exact spec (4.B).
- Oversized-module refactor program #6-#9 (`effects.py` 5692 / `builders.py` 1428 / `supervisor.py` 2312 / `adaptation_hint.py` 1602) - 4.C, engine one is reviewed-only-never-autonomous.

**Competitive research (full in Desktop .md s1):** RC's moat = first-principles item math (every competitor ranks by winrate correlation) + per-user model + no-bloat architecture. Top opportunities: (1) surface the math "why" on PGR/champ-select [Phase 4(d) serves this], (2) foreground per-user pick-ban, (3) on-demand screen-aware VLM coach (infra owned), (4) Arena/Mayhem augment recommender as a marketed pillar.

**Next-session priority (from the Desktop .md s5):** Phase 4(d) -> dashboard.js quarantine -> builders.py split + `_enrich_from_lcu` coverage -> product opportunities. DS conditional arc stays operator-CLOSED (not reopened).

**Discipline:** no frozen-file edits were needed (moon_proxy.py json.loads flagged, untouched - spirit of frozen rule held). Every change behavior-preserving or additive + tested. ASCII-only honored.
