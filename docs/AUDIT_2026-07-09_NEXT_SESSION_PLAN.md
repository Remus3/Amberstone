# Deep Audit + Next-Session Plan - 2026-07-09

Authored 2026-07-09 by an audit-only session (no repo mutations except this doc).
Intended executor: next session on Opus 4.8 max effort, orchestrated (worktree slices).

## How this was produced

Two multi-agent workflow passes over the whole tree, every finding independently
re-verified by a second adversarial agent (default REFUTED if not reproducible):

- Pass 1: 9 dimensions (orphan-docs, scratch-files, py-deadcode, py-funcverify,
  optimize-refactor, open-items-verify, web-js-orphan, config-test-health,
  cross-connection) - 38 agents. 3 dimensions returned degenerate placeholder output
  and were re-run.
- Pass 2: re-ran optimize-refactor, config-test-health, web-js-orphan hardened
  against placeholder returns - 18 agents.

Net: 42 verified findings (27 + 15), 4 refuted/degenerate discarded. Scale swept:
2069 .py, 448 .md, 114 .js/.mjs, 66 .css, 860 .json.

## Two clean verdicts (NO action - context only)

1. WIRING / CONNECTION TEST: INTACT. All 6 entry points traced 1-2 levels deep with
   zero broken wiring - main.py, web_dashboard.py, ops/rc_supervisor.py,
   agents/supervisor.py, tools/start_daemon_slayer.py, rc-shell src/main.js. 66 route
   modules registered in dashboard/_dispatch.py, all 16 SUPERVISOR_PROXY_PATHS
   implemented in agents/_supervisor_http.py, all 4 scheduled tasks point at existing
   scripts, all 11 rc-shell modules reachable. No dangling handlers, no missing imports,
   no module-load import cycles.
2. OPEN ITEMS ARE TRULY OPEN. The big buckets (ROADMAP overlay live-recon punch-list,
   ~30 default-OFF DS seam flips, ZOI Z2, A1/A2/D6) are legitimately live-game-blocked,
   not stale. ORCHESTRATION_PLAN is fully drained (162 DONE, 0 open; R79 "ORUN3/4 OPEN"
   note was superseded by R80). Tests and launchers are clean (0 broken collection, all
   skips are idiomatic conditional guards). The only falsely-lingering "open" work is the
   4 shipped DS plans (Lane 6) and 2 stale doc sub-claims (Lane 7).

## Guardrails (read before touching anything)

- FROZEN files (flag only, never edit): main.py, core/log_setup.py, core/moon_proxy.py,
  lcu/lcu_client.py, core/game_snapshot.py, ops/rc_dev_runtime.py, ops/rc_supervisor.py,
  app/__init__.py, app/_loop.py, app/_health_monitor.py, app/_remediation.py,
  app/_state_authority.py, app/_overlay_manager.py, app/_game_lifecycle.py. None of the
  fixes below require editing a frozen file.
- Dated artifacts (LEDGER.md, ROADMAP_HISTORY.md, history_notes.md, EXTERNAL_REVIEW_*,
  COMPETITOR_LIFT_*) are immutable: relocate only, never content-edit. No history rewrite.
- Lane 6 doc archives are OPERATOR-GATED per LIVE_GAME_GATED_SYNC.md - surface for
  go/no-go, do not relocate autonomously.
- ASCII only, no em/en-dashes. py_compile before any RC restart. Atomic writes.
  `git commit -F <tmpfile>`. Restart RC via restart_trigger.txt.
- Perf fixes (Lane 4) are opt-in / behavior-preserving by construction: keep default
  code paths byte-identical so existing tests stay green.

======================================================================
## LANE 0 - SAFETY (do FIRST, before ANY commit-all) - P1
======================================================================

### 0.1  Restore CLAUDE.md from the crash-leftover lean swap  [P1]
The tracked CLAUDE.md is currently the LEAN budget-saver stub (working-tree modified,
head reads "# RC Lean - Budget-Saver Mode"); the real full context lives ONLY in the
untracked CLAUDE.md.full (head "# Riot Commander - Agent Context"). A budget-saver
context swap (ops/budget_saver/budget-saver-unified.ps1) crashed before its finally-block
restored the full file. A naive `git add -A` / `git commit -a` would clobber the canonical
agent context repo-wide with the lean stub.
- ACTION: restore before any commit. If NOT inside a live budget-saver session:
  `git checkout -- CLAUDE.md` (HEAD is the full version), then `rm CLAUDE.md.full`.
  If a budget-saver session is still live, let its exit restore it, or copy
  CLAUDE.md.full over CLAUDE.md then remove the backup.
- VERIFY: `head -1 CLAUDE.md` reads "# Riot Commander - Agent Context" before any commit.
- Then add `/CLAUDE.md.full` to .gitignore so the swap-backup can never be committed
  (Lane 5.2). Effort S.

======================================================================
## LANE 1 - RED MAIN (guard test failing right now) - P1
======================================================================

### 1.1  DAEMON_SLAYER.md engine banner drift -> RED guard test  [P1]
docs/DAEMON_SLAYER.md:5 says "ENGINE_VERSION 1.182.0"; live is
agents/daemon_slayer/__init__.py:18 = "1.184.0". tests/test_docs_daemon_slayer_drift.py
::test_doc_engine_version_matches_source_of_truth is RED on main. Commit 809 bumped the
engine but left the banner. DAEMON_SLAYER.md is not frozen.
- ACTION: edit docs/DAEMON_SLAYER.md:5 banner 1.182.0 -> 1.184.0 (leave patch 16.13.1;
  test count is prose-approximate, not pinned).
- VERIFY: `python -m pytest tests/test_docs_daemon_slayer_drift.py -q` -> 3 passed.
- Effort S.

======================================================================
## LANE 2 - CONFIG CORRECTNESS - P2
======================================================================

### 2.1  cost_tracker reads a phantom repo-root rc_config.json  [P2]
core/cost_tracker.py:122 sets `_RC_CFG = _APP_DIR / "rc_config.json"` where _APP_DIR is
the repo root, resolving to C:\Riot Commander\rc_config.json which does NOT exist (only
ops/rc_config.json exists; CONFIG_AUTHORITY.md:10 names ops/rc_config.json the top
authority). read_json_dict(default={}) swallows the miss - fails silent. Today both files
lack the keys so behavior = defaults, but an operator who follows CONFIG_AUTHORITY.md and
adds daily_budget_usd to ops/rc_config.json gets it silently ignored and the spend cap is
never enforced.
- ACTION: change line 122 to `_RC_CFG = _APP_DIR / "ops" / "rc_config.json"`.
- VERIFY: add/confirm a test that a daily_budget_usd key placed in ops/rc_config.json is
  honored by cost_tracker. Not frozen. Effort S.

### 2.2  Champ-select Pick&Ban fabricated ban win-rates render as "beats you X%"  [P2]
web/js/panels/champ_select.js: _PB_PLACEHOLDERS (3716) defines only a BOT entry and
_pbPlaceholdersFor (3749) falls back to BOT for every role, so BOT placeholders leak to all
roles. When liveBans has <3 entries the counter-ban fallback (3973-3982) carries fabricated
pct (Draven 78, Lucian 64, Pyke 71) with encounters/losses=0, and _csvBanReasonLabel (3832)
renders "beats you {pct}%" for any pct>0 - invented percentages with no sample. The pick
path already forces reason to "[no data]" (3931); the ban path does not. Violates the
metric-provenance rule (no inferred numbers presented as source-truth).
- ACTION: in the counter-ban fallback (3973-3982) set pct:0 for placeholder bans so
  _csvBanReasonLabel emits "" and the cell renders name-only, OR suppress placeholder ban
  rows entirely when liveBans is short.
- VERIFY: DOM test that a <3-ban champ-select shows no "beats you N%" on placeholder rows.
  Effort S.

### 2.3  last_match rank-tier averages are hand-curated fiction on a live panel  [P2]
web/js/panels/last_match.js:185-191 comment labels _RANK_TIER_AVERAGES (192-213) as
"Hand-curated placeholder data"; those hardcoded per-tier cs/kda/kp/damage/vision/healing
render (509-527) as measured benchmarks once the operator selects a tier.
- ACTION: either wire the comparison to a real rewind_history.db aggregate, or tag the
  grid as "estimate / reference" in the UI so invented tier averages are not read as
  measured. Effort M (aggregate) or S (label). Recommend the label now, aggregate later.

======================================================================
## LANE 3 - DEAD CODE REMOVAL - P2/P3
======================================================================

### 3.1  core/ops_ui_actions.py - dead Tk orphan (zero inbound refs)  [P2]
`git grep ops_ui_actions` returns only self-references; the public entrypoint
run_action_async has zero callers. It is a Tk-based deploy/rollback runner (docstring
lines 3, 13-14) that conflicts with the asyncio/no-tkinter rule and the Electron-only UI
surface. Wraps ops/rc_transactional_deploy.py but nothing instantiates it. Not frozen.
- ACTION: delete core/ops_ui_actions.py (or move to docs/_archive/). Zero blast radius.
- VERIFY: `python -m compileall .` clean + full pytest green. Effort S.

### 3.2  web/js/panels/ward_cue.js - orphaned render, live data+CSS  [P2]
renderWardCue exported at ward_cue.js:122 with ZERO importers (main.js wires sibling cues
but not this one). Backend lc.ward_cue (core/ward_cue.py) still computes and css @import
dashboard.css:37 still ships. Half-connected.
- ACTION: DECIDE deliberately - either wire renderWardCue(lc) into the main.js live-render
  loop, or delete ward_cue.js + ward_cue.test.mjs + the dashboard.css:37 @import together.
  Do not leave half-connected. Effort S.

### 3.3  web/js/panels/cc_pairing.js - deliberately unwired orphan  [P2]
renderCcPairing exported at cc_pairing.js:105, zero importers; tests explicitly assert it
is NOT wired (tests/test_cc_pairing_panel_dom.py:65, tests/test_cs3_panel_relocation_dom.py
:165). css @import dashboard.css:48 still ships. Relocation-stranded.
- ACTION: remove cc_pairing.js + cc_pairing.css @import (dashboard.css:48) if superseded by
  cc_conditional_pressure, else wire it. Keep the DOM test only if the module is retained.
  Effort S.

### 3.4  web/js/ws_client.js - dead Phase-3 WS stub  [P3]
Zero importers; self-invoking stub targeting retired legion-pc.local:8891, superseded by
main.js's own inline WebSocket relay (main.js:6215).
- ACTION: delete web/js/ws_client.js AND remove its 3 asset-hash/summary entries so the
  ADR-008 hash set stays honest: dashboard/_static.py:45, dashboard/routes_state.py:434,
  ops/phase3_summary.py:82. Effort S.

### 3.5  web/css/stub.css - orphan stylesheet (prior DEFER can close)  [P3]
Only CSS not reachable (not <link>ed, not @imported). Refs only in
tests/test_dark_values_ratchet_oq6.py:54 and ops/phase3_summary.py:81. Prior triage
ops/audit/P2_FINDINGS.md:478 = DEFER.
- ACTION: delete web/css/stub.css + drop those 2 entries in the same change. Effort S.

### 3.6  Dead placeholder branch in champ_select.js (cosmetic)  [P3]
_CSV_ARCHETYPES (2162-2168) sets implemented:true for all six; the guard at 2549
`if (!a.implemented) push('placeholder')` is unreachable.
- ACTION: optional - drop the dead guard + implemented field, or leave for future
  archetypes. No behavior impact. Effort S.

### 3.7  config/settings.json - fully dead config  [P3]
Keys memory_warn_mb/memory_limit_mb/memory_watchdog_interval_s/game_poll_ms/data_poll_ms
(lines 2-10) have NO reader anywhere; not in config_validator.validate_all(). The watchdog
and poll loops use hardcoded defaults. CONFIG_AUTHORITY.md:177 wrongly claims it is
"read by LCU/UI code only".
- ACTION: delete config/settings.json + its packaging entry tools/build_portable.py:117,
  and correct CONFIG_AUTHORITY.md:177 to state it has no runtime reader. Effort S.

======================================================================
## LANE 4 - PERFORMANCE (opt-in, behavior-preserving) - P2/P3
======================================================================
Note: caches/resolvers are already well-built (single-writer snapshots, per-process
memoization, TTL + single-flight on the DS matchup). These are the narrow real wins.

### 4.1  HOT-01: DS DPS scorer computes 3 phases per candidate, ranker uses 1  [P2]
dps.py:957-966 always builds phase_dps for early+mid+late; rank.py:964-982 reads only
weighted_dps (selected phase) + stats['mp']. 2/3 of the rotation convolution is discarded
per candidate (~125-175 candidates per rank; ds-preview/build-order drive this).
- ACTION: add opt-in `only_phase: str | None` to compute_dps; when set, compute
  _phase_weighted_dps for just the selected phase. rank_items passes only_phase=selected.
  Default None -> full 3-phase output so /dps CLI + tests stay byte-identical.
- VERIFY: existing DS tests green + a microbench on rank_items. Effort M.

### 4.2  HOT-02: build_state re-fetches liveclient frame the cache already holds  [P2]
_liveclient.py:76-86 liveclient_summary() does its own urlopen('.../latest-liveclient',
timeout=1) on every /api/state build (2/s), while core/liveclient_cache.py background-polls
the identical endpoint every 0.5s into an immutable Snapshot. A stalled relay can hang the
/api/state critical path up to 1s despite a fresh cached frame.
- ACTION: source liveclient_summary() from core.liveclient_cache.get(): if snap.data is
  None or snap.age_s > 5 return {}, else parse snap.data. Keep lcu_summary()'s own fetch
  (cache does not poll /latest-lcu). Removes a per-build round-trip + the 1s stall.
- VERIFY: /api/state parity when cache warm (it always is; main.py starts it). Effort M.

### 4.3  HOT-03: coach poll tick runs blocking disk IO (+ retry sleep) on the loop  [P2]
_base_coach.py:370-378 _poll_loop calls _poll_tick() synchronously every 1.5s on the shared
AppLoop; the ARAM override (aram_coach.py:513-521) does load_json + safe_write every in-game
tick, and safe_write (_base_coach.py:83-99) has a blocking time.sleep in its PermissionError
retry - on the event-loop thread, under Defender/AV lock races.
- ACTION: `await asyncio.to_thread(self._poll_tick)` in _poll_loop (matches the existing
  _run_vision offload at :458). Optionally cache my_team in-instance to stop the per-tick
  re-read. Effort M.

### 4.4  HOT-04: shadow-log block assembled every tick, deduped only after  [P3]
_state_builder.py:612-616 unconditionally calls shadow_log_aram_coach/arena_coach every
build; each assembles a full deterministic block (+ a duplicate read of
aram_coaching_data.json already read at build_state:325) BEFORE the writer dedups
(_deterministic_coaching.py:1114). Runs at ~2/s during a live game for shadow-only telemetry.
- ACTION: gate the assembly behind a cheap coarse-state sig (champ, enemy_comp, level,
  item_count, game_time//5) mirroring _LAST_GOOD/_STATE_SINCE; pass the already-read coach
  dict into _live_aram_block instead of re-reading. Effort M.

### 4.5  HOT-05: DS ranker recomputes champion-invariant base scaling per candidate  [P3]
rank.py:954-978 loops candidates with constant champion_id/level/mode; each compute_dps
rebuilds _scale_champion_base (engine.py:330) and _phase_rotations (dps.py:956, no memo).
- ACTION: cache _phase_rotations per champion_id on the frozen DataSnapshot via
  object.__setattr__ (pattern at data_loader.py:462-466). Longer-term: hoist the
  level-scaled base block out of the candidate loop. Effort L. Compounds with HOT-01.

### 4.6  HOT-06: fmt_abilities / read_api_key reimplemented across coaches  [P3]
_base_coach.py:227-248 fmt_abilities vs aram_coach.py:459-477 _fmt_abilities are
byte-identical; read_api_key is re-rolled in tft_coach.py + tft_pbe_coach.py.
- ACTION: delete the dups, import from coaches._base_coach. Pure DRY, no behavior change.
  Effort S.

### 4.7  HOT-07: ARAM rune/build-note loaders re-parse patch-static JSON per call  [P3]
aram_coach.py _load_rune_rec (412-436) + _load_build_note (441-456) json.loads on every
_run_coach dispatch (679-680); sibling _arena_item_advisor.py already once-caches.
- ACTION: module-level once-cache keyed by filename (mirror _arena_builds_cache), optional
  mtime invalidation. (experimental_builds.json at 686-688 is the same pattern - fold in.)
  Effort S.

======================================================================
## LANE 5 - SCRATCH / GITIGNORE HYGIENE - P2/P3
======================================================================

### 5.1  Delete commit_tmp.txt leftover + gitignore  [P2]
Byte-identical to HEAD commit 063defd3's message (consumed `git commit -F` temp). Not
matched by the /_*.txt ignore.
- ACTION: `rm commit_tmp.txt`; add `/commit_tmp.txt` (or broaden to `/commit_*.txt`) to
  .gitignore. Effort S.

### 5.2  Gitignore CLAUDE.md.full  [P2]
Untracked swap-backup, one `git add -A` from being committed. Add `/CLAUDE.md.full` to
.gitignore (do this as part of Lane 0; delete the backup only AFTER CLAUDE.md is restored).

### 5.3  Gitignore the shadow logs  [P2]
core/augment_shadow.py:36 writes data/augment_shadow.jsonl and core/anvil_shadow.py writes
data/anvil_shadow.jsonl; both are untracked and NOT ignored, unlike ~10 sibling
data/*_shadow.jsonl already listed at .gitignore:52-61.
- ACTION: add a durable glob `data/*_shadow.jsonl` (covers augment + anvil + future
  writers) rather than two more literal lines. Effort S.

### 5.4  Commit budget-saver-unified.ps1  [P2]
ops/budget_saver/budget-saver-unified.ps1 is a real 119-line launcher unifying the tracked
budget-saver-*.ps1 siblings; no inline secrets (sources gitignored env.local.ps1). Untracked.
- ACTION: confirm the operator wants the unified launcher tracked, then commit it alongside
  the siblings. Effort S.

### 5.5  Commit the 6 deliberate modified tracked files (by path)  [P3]
git status shows deliberate edits: data/meta/ddragon_items.json (em-dash -> ASCII hygiene),
ops/budget_saver/lean-settings.json (permissions block), 4 agents/agent6_auditor/reports/
*.md. Stage EXPLICITLY BY PATH - do NOT `git add -A` / `git commit -a`.
- EXCLUDE: (a) CLAUDE.md until Lane 0 restore; (b) data/force_scan.json (runtime churn,
  see 5.6). NOTE: lean-settings.json enables bypassPermissions/skipDangerousModePermission
  Prompt - confirm intended before committing. Effort S.

### 5.6  data/force_scan.json runtime churn (operator call)  [P3]
Tracked file that mutates every arena game (single {"force": <epoch>} field, written by
dashboard/_writers.py, coaches/arena_coach.py, core/hotkeys.py, tools/lcu_agent.py).
- ACTION: operator decision - `git rm --cached data/force_scan.json` + gitignore to stop
  churn, OR keep a committed default seed intentionally. Not a leftover. Effort S.

======================================================================
## LANE 6 - DOC ARCHIVE (OPERATOR-GATED) - P3
======================================================================
LIVE_GAME_GATED_SYNC.md:795-815 already enumerates these; the relocate simply has not run.
Surface for go/no-go, then execute as ONE slice with all back-refs updated in the same
commit. Leave append-only LEDGER/history pointers as-is (no history rewrite).

### 6.1  Archive 4 shipped DS plans  [P3]
Move to docs/_archive/: DS_V2_PLAN.md, DS_SOURCE_ADOPTION_PLAN.md, DS_GAP_COMPLETION_PLAN.md,
DS_ABILITY_RATIO_RESOURCE_PLAN.md. Update back-refs in the same slice:
- docs/ARCHITECTURE.md:247 (-> DS_V2_PLAN) and docs/DAEMON_SLAYER.md:79 (-> DS_V2_PLAN)
- tools/ds_windup_offset_compare.py:4 (-> DS_SOURCE_ADOPTION_PLAN)
KEEP docs/DS_PERMUTATION_SWARM_PLAN.md (live gemini-loop charter, cited by
ops/audit/ds_perm_swarm/__init__.py:6) and docs/DS_COMPLETENESS_GAP.md (see 7.2).
Do NOT touch ops/audit/ds_perm_swarm/__init__.py:6 (it points at the KEPT swarm plan).

### 6.2  Archive other spent one-shots  [P3]
- docs/API_SURFACE_AUDIT.md -> _archive (docs/API.md is canonical).
- docs/RC2_TODO_QA.md -> _archive; retarget the RC2_QA_CONSOLIDATED.md:6 pointer.
- docs/LCU_PHASE_CAPTURE_WATCHER_PLAN.md, docs/research/GAMEPC_PURGE_SPEC.md -> _archive
  (only docstring/LEDGER refs, safe).
- docs/CAPTURE_101QQ_INSTRUCTIONS.md -> _archive ONLY WITH path updates: hard-coded in
  tests/test_probe_101qq_script.py:41 (_DOC_INSTRUCTIONS, would FileNotFoundError), plus
  comment refs core/synergy_external_source.py:11, tools/probe_101qq_hero_rank_double.py:13,
  tests/test_rc2_p73_quarantine.py:14.

### 6.3  Archive settled COMPETITOR_LIFT cluster - with a code-ref caveat  [P3]
Move settled dated lifts to docs/_archive/ following the existing convention. DO NOT move
docs/COMPETITOR_LIFT_2026-06-08.md blind: it is cited BY LINE NUMBER in live code + tests
(agents/daemon_slayer/ehp.py, dashboard/routes_ds_combo.py, several test files, + Share/src
mirror, ~14 citations). Either update every citation in lockstep (Share staged same commit)
or leave 06-08 in root. KEEP docs/COMPETITOR_LIFT_2026-07-05_R81.md in root (newest).

### 6.4  tools/ April distribution docs - NOT a simple relocate  [P3]
tools/DISTRIBUTION_LAYOUT.md, LAUNCH_STRATEGY.md, PYTHON_BUNDLING_STRATEGY.md are wired into
the portable-build pipeline: tools/build_portable.py:124-127 bundles them,
tools/run_packaged_smoke.py:374-383 asserts LAUNCH_STRATEGY.md present. FIRST decide whether
the portable build pipeline is still live under ADR-011. If retired, decommission
build_portable.py/package_portable.py/run_packaged_smoke.py WITH the docs as one unit. If
live, leave the docs in place (they are inputs, not dead).

### 6.5  Archive the RC2_STALE_FILE_CENSUS itself (last)  [P3]
docs/research/RC2_STALE_FILE_CENSUS.md over-flags CHERRY_AUGMENT_SCAFFOLD_NOTES,
DS_ABILITY_RATIO_RESOURCE_PLAN, DS_SOURCE_ADOPTION_PLAN which the newer gated-sync list
KEEPS (CHERRY = live owed-Cherry recipe; the DS plans = staged cutover hooks). Treat
LIVE_GAME_GATED_SYNC.md (b) as authoritative. The census is a spent Phase-7.2 deliverable -
archive once its section-A/C worklist is drained.

DO NOT archive the docs/research/RC2_RESEARCH_* 10-file cohort - they are live linked
deliverables from docs/RC2_PLAN.md:118-126,171,216 (this was a REFUTED finding).

======================================================================
## LANE 7 - DOC STALE-FIX (no code) - P3
======================================================================

### 7.1  Refresh the D6 row in LIVE_GAME_GATED_SYNC.md  [P3]
Lines 50-52 cite only fix 79c4e9e9 and say "both shadow files ABSENT on disk". A newer fix
landed (10374d02, round-based force_scan trigger) and data/augment_shadow.jsonl now exists
(966B). LEDGER 820 records it live.
- ACTION: cite 10374d02 as current fix, note augment_shadow.jsonl now seeds, keep D6 OPEN
  pending a live Arena augment/anvil phase. No code change.

### 7.2  Add a dated SNAPSHOT banner to DS_COMPLETENESS_GAP.md  [P3]
:22 pins engine 1.147.0 and :156 "34 open gated boxes" - superseded (live 1.184.0; B45/B46/
B47 + DSP11 C4 flipped). Do NOT archive: cross-referenced by line number in
OVERLAY_BUILD_MASTER_PLAN.md:496 and LIVE_GAME_GATED_SYNC.md:275 (load-bearing).
- ACTION: add a top banner "SNAPSHOT as of 2026-06-19; live counts superseded - see LEDGER
  and LIVE_GAME_GATED_SYNC". No relocate.

======================================================================
## Suggested orchestration for the next session (Opus 4.8 max)
======================================================================

Lane 0 and Lane 1 are gating and tiny - do them inline FIRST (sequential), commit Lane 1
by path, confirm main green. Then fan out the rest as worktree slices on disjoint file sets
(supervisor merges, read-only verifier gate before each merge):

- Slice A (config+data-provenance): Lane 2 (2.1 cost_tracker, 2.2 pickban, 2.3 last_match).
- Slice B (dead-code): Lane 3 (3.1-3.7). Each removal followed by compileall + pytest.
- Slice C (perf): Lane 4 - do 4.1/4.2/4.3 (the P2s) first, each behind a green DS/state
  test + a microbench; 4.4-4.7 as a second wave.
- Slice D (hygiene): Lane 5 - path-scoped commits, honor the exclude list.
- Lane 6 is operator-gated: present the list, execute only on approval, one slice with
  back-refs. Lane 7 is doc-only, safe to batch with Lane 6.

TDD where behavior changes (2.1, 2.2, 4.x): failing test first, then implement. Restart RC
via restart_trigger.txt after Lane 4 lands, verify /api/health/all + a live /api/state build.
Close with /done (commit + push), then /live-gated-resync if Lane 6/7 touched the gated doc.

## Do-not-redo / already-clean (skip these)
- Whole-tree py dead-code re-audit: clean baseline, only ops_ui_actions.py surfaced.
- Broken imports / import cycles / route wiring: all INTACT, do not re-sweep.
- Test collection + launchers + scheduled tasks: clean.
- ORCHESTRATION_PLAN drained; the live-gated DS/overlay/ZOI items stay OPEN by design.
