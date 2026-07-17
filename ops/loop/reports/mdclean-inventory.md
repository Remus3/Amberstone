# mdclean inventory - cluster C1 (2026-07-17)

Run: md-cleanup headless loop (docs/specs/2026-07-16-md-cleanup-headless-directive.md), cycle C1.
Baseline: HEAD b336a270, CI green (run 29561408083 success), RC pid 27616 alive last_reload_ok,
DS :8893 ok patch 16.14.1 ENGINE 1.216.0, LEDGER top ~911.
Method: 8 parallel read-only slice agents (A ROADMAP/WAKEUP/README, B BACKLOG, C ARCH/OPS/API/AGENTS,
D DAEMON_SLAYER, E ORCHESTRATION_PLAN, F LIVE_GATED, G OVERLAY+RC2, H other-docs census).
No repo doc was edited this cycle. Line numbers are as-of b336a270 and MUST be re-anchored at edit time.
Citation legend: LEDGER NNN = docs/LEDGER.md item; SHA = commit in local history; in-doc = self-declared
marker spot-checked; live = live probe fact. UNVERIFIED items are in mdclean-findings.md (skip list).

## Totals

| slice | file(s) | bytes | candidates | unverified | est reclaimable |
|---|---|---|---|---|---|
| A | ROADMAP + WAKEUP_NOTES + README | 103248 | 32 | 8 | ROADMAP under 80KB budget + more |
| B | BACKLOG.md | 123393 | 30 | 3 (+3 stale-path) | ~25-35KB |
| C | ARCHITECTURE/OPERATIONS/API/AGENTS | 47839 | 24 | 3 | ~5-8KB + accuracy fixes |
| D | DAEMON_SLAYER.md | 97938 | 20 | 3 | ~73KB (changelog block) |
| E | ORCHESTRATION_PLAN.md | 351719 | 12 | 4 (sha-level) | ~310KB |
| F | LIVE_GAME_GATED_SYNC.md | 181474 | 19 | 0 | ~25KB body (+70KB gated) |
| G | OVERLAY_BUILD_MASTER_PLAN + RC2_PLAN | 171560 | 18 | 0 | ~110-115KB |
| H | other docs census | 56 files | 33 dated-artifact, 2 superseded | - | archive relocations |

Grand total est reclaimable via relocate-not-delete: ~550-620KB across living docs.

## ROADMAP.md (83017B, a13f9e0d 2026-07-16)

FACT: tests/test_doc_size_budget.py::test_roadmap_md_under_budget FAILS locally at HEAD
(83017 > 81920 = 80*1024). CI green - test is not in the per-push CI selection. C2 trim fixes it.

- L11-L106 | Open items - High priority | RESTRUCTURE to NOW/NEXT/LATER w/ stable ids | LEDGER 901 trim precedent
- L16 | OQ23-25 DRAINED tombstone | PRUNE | LEDGER 875/885/886/889
- L21 | OVERLAY REDESIGN all-panels narrative | RELOCATE | LEDGER 760 + SHA 6370f7da
- L22 | NO-LIVE-LLM PRECOMPUTE shipped-slices narrative | RELOCATE (keep north-star + gated flip) | LEDGER 802 + SHAs 523206d6/c82b2446/34c46d44
- L24 | RESEARCH-REPORT NOW BETS shipped slices | RELOCATE (keep live SR validation owed) | LEDGER 631/634/765
- L26 | PER-PAGE UI/UX REVIEW 9 pages | RELOCATE (keep live-gated tail) | LEDGER 603/611/612
- L27 | HEADLESS OVERLAY-POLISH RUN banner | PRUNE | LEDGER 565/601 (L30 declares lane DRAINED)
- L28 | LIVE-RECON PUNCH-LIST | DEDUP -> docs/LIVE_GAME_GATED_SYNC.md | SHA ded5f354
- L34-L35 | HEADLESS SWARM RUN ARMED banner | PRUNE | LEDGER 487 + self-declared DRAINED/NO_WORK
- L40 | DEEP-AUDIT PROGRAM run banner | see findings (UNVERIFIED loop-end)
- L46 | P6 LOLMATH PARITY - CLOSED | PRUNE | self-declared CLOSED; detail in ROADMAP_HISTORY 2026-07-06
- L47 | Haiku-to-ZERO HZ-* fanout ~9KB line | RELOCATE (keep gated NEXT) | LEDGER 576/614
- L54 | ZOI minimap program narrative | RELOCATE (keep live-gated tail) | LEDGER 567/688/711/795 + SHA fe37c534
- L63 + L77 | archived-sweep pointer notes | PRUNE | self-declared archived
- L65-L73 | item-227..239 stacked NEXT blocks | DEDUP -> ROADMAP_HISTORY + LIVE_GAME_GATED_SYNC | self-cited
- L87 | item 209a "Carries forward: none" | PRUNE | self-declared none; CI drift guard locked
- L91-L93 + L98 | AUTONOMOUS_AUDIT s5 NEXT-pointers + tombstone | PRUNE | L98 declares SUPERSEDED/relocated; menu exhausted (CLAUDE.md Settled)
- L97 | KEYSTONE "Residual: none functional" | PRUNE | self-declared
- L48, L56, L57, L75, L95 | pre-LEDGER-floor items w/ dead SHAs | see findings (UNVERIFIED)

## WAKEUP_NOTES.md (14874B, a13f9e0d 2026-07-16)

- L3 | 4.6KB single-line archive inventory (s27-s137...) | RESTRUCTURE to last-archived date + pointer | archives self-declared in LEDGER + history_notes
- L7-L16 | OVERNIGHT AUTONOMOUS DIRECTIVE 2026-07-13 | RELOCATE (expired) | LEDGER 875 + 908 + 910/911
- L55-L62 | 2026-07-16 Locke session (4th-newest) | RELOCATE -> history_notes | LEDGER 907/908; keep-2-3 rule keeps 909/910/911 sessions

## README.md (5357B, ca09402c 2026-07-14)

- L35-L45 | "six scoring modes" + 6-row table | PRUNE/refresh | LEDGER 911 (7th scorer ds.onhit, ENGINE 1.216.0)
- L48 | "547 items), 20,190 tests" | DEDUP-flag | counts drift; canonical = /sync-all-md ground truth
- L46 | "three-quarters of roster" coverage prose | COPY-VERBATIM-ONLY flag | DS-batch-only recompute rule
- L76 | "ROADMAP.md - full milestone ledger" | DEDUP fix pointer -> docs/LEDGER.md | ROADMAP.md:3 self-declares Now+Next only

## BACKLOG.md (123393B, be9b73ce 2026-07-14)

META: 20 of 26 spot-checked SHAs cited in BACKLOG do not resolve in local history (pruned worktree
SHAs; history reaches 2026-04-26, 3540 commits). LEDGER ids are the reliable anchors. Path check:
36/39 cited paths exist; 3 stale paths flagged below.

- L3-L5 | header charter cites "CLAUDE.md ledger" | RESTRUCTURE fix pointer -> docs/LEDGER.md | ledger relocated 2026-06-02
- L13 | OQ24 residuals tail-1 Stormrazor CLOSED para (~2.5KB) | PRUNE partial (keep tails 2-4) | LEDGER 888
- L15-L18 | RESOLVED 2026-07-09 all-3-reds block | PRUNE | LEDGER 826
- L21 | boot-utility SHIPPED narrative | PRUNE partial (keep flip line) | LEDGER 827 + 0aa116af + boot_utility.py on disk
- L23-L30 | R66 adversarial refute pass block | PRUNE | LEDGER 753-757 + 905 (residual #7 re-verified)
- L46 | 2026-05-21 sweep history note | PRUNE | self-declared archived; stale CLAUDE.md-ledger pointer
- L48 | R125 ult power-spike trailing R126 prose | DEDUP partial -> ROADMAP Lane-E row | files exist
- L50 | aram_tenacity_mult SHIPPED ~8.6KB line | PRUNE | SHAs adfab719/6db55f12 + s232-CLOSED arc (CLAUDE.md Settled)
- L51 | obj_participation OPTION (c) | see findings (UNVERIFIED SHA, self-marked CLOSED twice)
- L52 | Dead Man's Plate stacks-schema | see findings (UNVERIFIED SHA, ENGINE superseded)
- L53 | DS V2 next slices ALL 4 SHIPPED | PRUNE + STALE-PATH (docs/DS_V2_PLAN.md -> docs/_archive/ at b1c01c49) | self-marked CLOSED
- L57 | Interactive Item Shaper s214 note | DEDUP -> L42 newer entry (OQ14/LEDGER 735) | core/shaper.py shipped
- L58 | DS competitor-lift gate slate | PRUNE + STALE-PATH (web/js/panels/cooldown_watch.js deleted daf04998? see LEDGER 765 orphan sweep; routes_cooldown_watch.py exists) | items 218-220
- L59 | LIFT1 FUTURE gaps | PRUNE | self-declared FULLY closed + LEDGER 371/374
- L62 | item-WPA Build Insights | PRUNE (keep don't-reopen anchor) | LEDGER 374/389 + files on disk
- L65 | antiheal/grievous SHIPPED | PRUNE | core/heal_threat.py on disk (reused LEDGER 908/909)
- L66 | prompt-restructure CLOSED-not-viable | PRUNE (guard test on disk pins the don't-re-attempt) | tests/test_prompt_cache_floor_item286.py
- L67 | HZ replay-narrative substrate | PRUNE partial (keep dormant-surface flip) | LEDGER 506 + files on disk
- L69 | HZ-B fully-static regen | PRUNE | LEDGER 905 records --static in production
- L83 | HZ-B table regen FUTURE | PRUNE | LEDGER 506 + superseded by 16.14.1 regen (LEDGER 905)
- L86-L88 | Developer experience section (only closed item) | PRUNE section | items 153-155 pre-LEDGER-floor, self-marked closed
- L92 | Pre-release name-scrub | DEDUP -> docs/PRE_RELEASE_NAME_SCRUB.md pointer | doc exists
- L94 | Haiku-skip debounce | PRUNE partial (keep flip-only line) | LEDGER 506/507
- L104 | garbled competitor-teardown URL anchor | RESTRUCTURE | superseded by executed 2026-07-05 queue
- L118-L121 | CLOSED LCU/Pengu triage block | DEDUP -> CLAUDE.md Settled | canonical there
- L131 | draft_elo SHIPPED para | PRUNE | files on disk + b06ec877/4852bea3 reference panel
- L138-L151 | 5 pure-history SHIPPED paras | PRUNE + STALE-PATH (ban_suggest_toggle.js deleted daf49498? per LEDGER 765) | files on disk
- L149 | Riot per-role grading rubric | PRUNE | SHA 42780b3d verified + LEDGER 335
- L172 | Aggregator C GPI radar SHIPPED | PRUNE (keep 1-line FUTURE tail) | LEDGER 450/451/511 + player_gpi.js on disk
- L294-L303 | OBS+CV+minimap section | DEDUP -> docs/OBS_CV_MINIMAP_PLAN.md + ROADMAP ZOI row | doc exists

## docs/ARCHITECTURE.md (23686B, b1c01c49 2026-07-09)

- L9-L14 | machines table + tailnet para | DEDUP -> CLAUDE.md Topology | live facts match
- L16 | Game-PC teardown dated narrative | RESTRUCTURE to 1 line | CLAUDE.md Settled items 267/276
- L24 | retired screen_agent row in active data-flows table | PRUNE | item 276; historical note already at L215/L226
- L31-L36 | 3rd copy of relay self-heal narrative | DEDUP intra-doc -> L226-L234
- L219-L224 | deploy-allowlist prune plan-text | RELOCATE -> BACKLOG (see findings UNVERIFIED)
- L226-L234 | item-276 ship narrative 9 lines | RELOCATE -> history_notes, keep 2-line state | LEDGER 685/688/711
- L242 | "Six archetype scorers" | PRUNE stale count (7 live) | daemon_slayer_client.py rank_onhit_for + CLAUDE.md "all 7"
- L243-L247 | hardcoded engine-identity counts (196/125, 1.38-1.40) | DEDUP -> DAEMON_SLAYER.md banner | WP-F6a rule forbids restating
- L277-L287 | god-modules section all-struck-DONE + broken Desktop pointer | RELOCATE | RC_FUTUREPROOFING_PLAN.md absent (ls verified)
- L281-L285, L299 | non-ASCII glyphs (U+2705, U+2260) | RESTRUCTURE ASCII | grep-verified

## docs/OPERATIONS.md (16882B, c839b7a9 2026-07-12)

- L44-L59 | "Do NOT use restart.bat" | CONTRADICTION w/ CLAUDE.md Restart workflow (restart.bat = hard fallback) | resolve in C5; CLAUDE.md side goes to proposal file
- L63-L85 | scheduled-tasks table 17 rows | RESTRUCTURE (live = 18 RC-*) | live probe
- L113 | cites Claude memory topic unreachable to repo readers | RESTRUCTURE
- L171-L186 | persistence operator-gated para vs own L69 row | RESTRUCTURE | LEDGER 386
- L247-L248 | dated play-cadence rationale | see findings (UNVERIFIED)
- L260-L266 | Python path section | DEDUP -> L9-L13 + CLAUDE.md Paths

## docs/API.md (3996B, 49b1c9ea 2026-06-24)

- L8-L60 | GET/POST tables missing ~30 newer endpoints | RESTRUCTURE regen from dispatcher | ARCHITECTURE archmap + OPERATIONS name the absent routes
- L45 + L50 | /api/input duplicated row | RESTRUCTURE
- L4 | middot U+00B7 | RESTRUCTURE ASCII

## docs/AGENTS.md (3275B, 49b1c9ea 2026-06-24)

- L18 | cross-machine task policy | RESTRUCTURE stale framing | 1-PC + bridge decomm 2026-06-24
- L20 | SMB push in live role list | PRUNE | smb_push.py:47-52 self-declares retired (ADR-011/012)
- L23 | "19-file pytest suite" | PRUNE stale count | dir = 46 files (ls)
- L33 | task_queue.jsonl ~828KB | PRUNE stale size | wc = ~4.5MB
- L10, L18-L25, L47 | non-ASCII arrows/middots | RESTRUCTURE ASCII

## docs/DAEMON_SLAYER.md (97938B, a13f9e0d 2026-07-16)

RULE: every count-bearing string (coverage %, entries/champs, test counts) is COPY-VERBATIM-ONLY
from LEDGER/CLAUDE.md or left untouched - zero recomputation (nested registry mis-parses).

- L17-L113 | changelog block = ~75% of file bytes, newest entry 1.144.0 vs live 1.216.0 (60+ versions stale) | RELOCATE -> history_notes + CHANGELOG pointers; L25 gap-note pointer style is the proven pattern | Share/CHANGELOG.md + agents/daemon_slayer/CHANGELOG.md + history_notes items 148/172/237/302 hold the content
- L19 | stale version pin in gap-note | PRUNE | __init__.py:18 = 1.216.0
- L92-L95 | wave SHAs 084cc50/c16c3a2/4d60420/7530002 | PRUNE dead refs | git cat-file fatal + log --all 0 hits
- L15 | s223-s232 sweep narrative in 3917-char line | RESTRUCTURE compress | CLAUDE.md Settled carries the one-liner; counts verbatim-only
- L120 | "32 routes" | PRUNE refresh | server.py 34 paths; omits /v2/matchup + /v2/fight-report
- L126 + L132 | duplicate hybrid.py rows | DEDUP intra-doc
- L140 | "tests/ 11701" missed the a13f9e0d sync | PRUNE refresh copy LEDGER 911 "11754" verbatim
- L144-L146 | ItemEffect/CallContext field lists missing newer fields | RESTRUCTURE | L28/L32 name them
- L169 | "Six canonical archetypes" | PRUNE | LEDGER 911 7th onhit; contradicts own L5/L15
- L172 | 6-button 3x2 picker grid | RESTRUCTURE add LEDGER-911 caveat verbatim (no manual onhit option)
- L174-L182 | brawl_coach.py presented active | RESTRUCTURE annotate legacy | CLAUDE.md Settled s214
- L192-L194 | calibration "Status: accumulating" | see findings (freshness UNVERIFIED)
- 18 lines | non-ASCII glyphs | RESTRUCTURE ASCII | python ord>127 scan
- L127, L10+L123 | roster/item counts | COPY-VERBATIM-ONLY flags (DS-batch docs-sync job)

## docs/ORCHESTRATION_PLAN.md (351719B, be9b73ce 2026-07-14)

MAP: 446 lines, 11 top-level sections; 8/8 session rounds fully DONE (zero OPEN/WIP rows; newest
R129 = LEDGER 903, 1c6e1fc1 verified). Findings log 62 entries vs own keep-newest-~10 policy (L350-352).
Post-cleanup target ~35-40KB (head + EXCLUDED + active-round anchor + newest ~10 findings), directly
serving the PLAN_CTX_CAP director-context budget.

- L349-L446 | findings log: relocate ~52 of 62 -> ORCHESTRATION_FINDINGS_ARCHIVE.md | doc's own policy + 2026-07-01 relocation precedent + LEDGER 903 | ~105KB
- L271-L337 | ORCHESTRATED-RUN RELAUNCH round, 51 rows DONE | RESTRUCTURE keep header as anchor, relocate rows | LEDGER 784 + 903/be9b73ce | ~70KB
- L213-L270 | DIRECTOR REFILL 2026-06-25, 43 rows DONE | RELOCATE | LEDGER 763 | ~72.5KB
- L20-L104 | original queue ~50 rows DONE | RELOCATE | SHAs 505274c1/e14eedbd + LEDGER 875 inline | ~38KB
- L105-L132 | OPERATOR REFILL DSP swarm DONE | RELOCATE | LEDGER 876+889 | ~5KB
- L192-L212 | DIRECTOR REFILL 2026-06-22 DONE | RELOCATE | b49ef1a7 verified | ~5KB
- L133-L191 | 2026-06-17/18/19 rounds DONE | RELOCATE | in-doc DONE markers; sha-level UNVERIFIED (findings) | ~16KB
- L442-L446 | newest-first ordering broken by tail appends | RESTRUCTURE fold into kept block
- L9-L16 | per-cycle contract summary | DEDUP-minor vs ops/loop/director_prompt.md (see findings)
- L1-L19 + L338-L348 | head protocol + EXCLUDED | KEEP as-is (durable contract)

## docs/LIVE_GAME_GATED_SYNC.md (181474B, a13f9e0d 2026-07-16)

CONSTRAINT: .claude/workflows/live-gated-resync.js REWRITES header + sections A-F + drain plan each
pass but PRESERVES the Live-flip ledger (L929-L1980) VERBATIM (append-only; verifier requires >400
lines + harvests OWED from ledger text). Ledger relocation is OPERATOR-GATED (in-doc L952-953 +
feedback_no_history_rewrite) and requires a same-change live-gated-resync.js edit (writer prompt
L210, verifier L235). Body restructure is resync-compatible.

- L929-L1980 | live-flip ledger 103741B | RELOCATE (OPERATOR-GATED, keep OWED-bearing + 2 SYNC entries) | dup of docs/LEDGER.md seam history
- L136-L716 | sections A-H 47424B, 67/82 verdicts confirmed-done | RESTRUCTURE via /live-gated-resync rebuild to ~16-row set | ded5f354 | ~20KB
- L138-L146 | A1 VALIDATED/CLOSED | PRUNE | LEDGER 859
- L147-L151 | A2 closed | PRUNE | LEDGER 867
- L164-L168 | A7 closed | PRUNE | LEDGER 867
- L188-L191 | A13 close-condition met | PRUNE | in-doc L70 + LEDGER 859/867
- L67-L75 | 2026-07-12 DRAIN RESULT | RESTRUCTURE compress to ledger pointer | LEDGER 867; C15/C16 narrative restated L90-93 + memory
- L29-L37 | resync-pruned list | RESTRUCTURE compress (verbatim dup at L957-962)
- L53-L58 | TWO LIVE BUGS half-stale | RESTRUCTURE keep D6 only | LEDGER 859/867
- L109-L116 | next-session play order stale | RESTRUCTURE | resync rewrites
- L794-L865 | undated drain plan gating on closed rows | RESTRUCTURE | LEDGER 867; workflow emits fresh dated plan
- L346-L361 | B45/B46 flip-done halves | RESTRUCTURE compress flip history, keep calibration tails | LEDGER 799 + 90a74972
- L539-L543 | C15/C16 superseded framing | DEDUP -> L90-93 + memory | LEDGER 867
- L572-L573 | D7-hist CLOSED | PRUNE | in-doc marker + ledger dup L961
- L121-L122 | Z1+Z3 closed | PRUNE | in-doc + LEDGER 796
- L905-L925 | hygiene (b) 7 rows [ARCHIVED 2026-07-09] | PRUNE executed proposals
- L868-L903 | hygiene (a) stale ground truth (1.181.0, ~14364) | RESTRUCTURE refresh or relocate open rows
- L743-L773 | D1/F5/OQ22 DISCHARGE rows | RESTRUCTURE compress to one-line fences

## docs/OVERLAY_BUILD_MASTER_PLAN.md (72157B, 20df6d2b 2026-07-09)

- L26-L272 | SECTIONS A-D all WPs DONE per Section J | RESTRUCTURE to status lines | SHAs 7205d73c/adedacde/4f1d4126/cedb78c2/c24c5162 verified | ~27KB
- L279-L370 | E.1/E.2 reconcile residue | RESTRUCTURE | LEDGER 744 applied
- L411 | F1-01 LIVE-CONFIRMED narrative | PRUNE to status line | LEDGER 685 (23e624a5)
- L413 | F1-03 RESOLVED-BY Section B | PRUNE | adedacde/be48d3f7
- L463-L474 | F.5 stale STILL-OPEN header + 4 DONE rows | PRUNE (keep F5-L03) | e599e610/c20d75da/decd681f/76a783b4 + LEDGER 685
- L470 | WP-F5-M01 cites non-existent SHA e4b08ba | PRUNE fix | LEDGER 685: real fix 5bfa7ea5
- L478-L488 | WP-F6a spec | PRUNE to status line | b0720386 + LEDGER 683
- L631-L682 | SECTION H waves W0-W5 executed | RELOCATE (keep W6 T0 stragglers) | Section J
- L683-L790 | SECTION I spent run mechanics | RELOCATE | Section J I3 DONE
- L828 | GATED list still names F1-01 | RESTRUCTURE drop | LEDGER 685
- KEEP: Section G doctrine, Section J tracker, WP-E5/F4a/F6c, F.2/F.6b/F.7 gated lists (open tail for /overlay-build-continue)

## docs/RC2_PLAN.md (99403B, b1c01c49 2026-07-09)

- L222-L247 | FINDINGS LOG 24 SHIPPED mega-entries = 72442B (73% of file) | RELOCATE -> history_notes (keep heading + pointer) | near-verbatim dups of LEDGER 533/540/544; SHAs 92ca2279/fd5e6872/08ec3ebd/dbbd7a8d verified
- L13-L15 | 3.6KB progress-recompute single line | RESTRUCTURE to short banner | stage tables carry same SHAs
- L58-L64 | HARD PAUSE decision block | RESTRUCTURE spent | superseded in-doc by L66-L71 GREENLIGHT
- L73-L83 | TOP-10 answers | DEDUP -> docs/RC2_QA_CONSOLIDATED.md | stage 8.3 f05b853d verified
- KEEP: stage tables L115-L201 (ARE the status), OPERATOR DIRECTIVE L26-L44, RESUME PROTOCOL + DELIVERABLE INDEX L205-L221

## Other-docs census (slice H; 56 files)

LIVING (19): PRE_RELEASE_NAME_SCRUB, UI_SCALE_SPEC_V2, cost_trace (NOTE: git tracks docs/COST_TRACE.md,
disk is cost_trace.md - case mismatch), GEMINI_REVIEW_CONSUMPTION (NOTE: its pointer file
ops/runtime/gemini_review_consumed.txt never created), PGR_REFRAME_S2, GEMINI_AUDIT_CONFIG,
DEEP_AUDIT_CHARTER, CHERRY_AUGMENT_SCAFFOLD_NOTES, DS_PERMUTATION_SWARM_PLAN, UI_CAPTURE_RECIPES,
OVERLAY_DOCTRINE (canonical design law), RC2_REDESIGN_PLAN, CI_WATCHDOG_PLAN, ELECTRON_OVERLAY
(stale "Status: PLAN (no code yet)" header worth refresh), DARK_VALUES_AUDIT_2026-07-01 (ratchet-test
companion, 94 gated rows pending), OBS_CV_MINIMAP_PLAN, ZOI_DISTRICT_ORCHESTRATION_PLAN,
RC2_QA_CONSOLIDATED, NO_LLM_PRECOMPUTE_PLAN.

ARCHIVE-SIBLING (2, leave): ORCHESTRATION_FINDINGS_ARCHIVE (275947B), ROADMAP_HISTORY (426234B).

SUPERSEDED (2): CHAMP_SELECT_UI_SPEC -> RC2_REDESIGN_PLAN (LEDGER 589);
UI_OVERLAY_REDESIGN_SPEC_2026-07-06 -> docs/specs/2026-07-11-overlay-item{1,4,8} (LEDGER 860).

DATED-ARTIFACT (33): 16 COMPETITOR_LIFT_* (2026-06-08..07-14), 11 EXTERNAL_REVIEW_* (all UNTRACKED
per .gitignore:246 - archive relocation would be disk-move only), OVERLAY_QA_2026-06-29 (LEDGER
686/688 done), LOOP_IMPROVEMENTS_2026-06-27 (NOTE: tests/test_loop_gemini_timeout.py cites it -
retarget ref if relocated), AUDIT_2026-07-09_NEXT_SESSION_PLAN (LEDGER 822 executed),
OPERATOR_DECISION_QUEUE_2026-07-01 (LEDGER 734), DS_COMPLETENESS_GAP (self-pinned KEEP-IN-PLACE:
line-number xrefs from RC2_PLAN/OVERLAY_BUILD_MASTER_PLAN/LIVE_GAME_GATED_SYNC - do NOT relocate).

Side notes: docs/UI_OVERLAY_REDESIGN_2026-07-06_buildrows.test.mjs.txt is a non-md sibling of the
superseded 07-06 spec.

## Cross-cutting findings

1. SHA-rot: old short SHAs cited in ROADMAP/BACKLOG (pre-rewrite/worktree-branch) mostly do NOT
   resolve locally. Cleanup edits must anchor on LEDGER ids, not cited SHAs.
2. ROADMAP size budget test fails locally at HEAD (83017 > 81920); CI green because the test is not
   in per-push selection. C2 fixes it.
3. Non-ASCII pockets confirmed in ARCHITECTURE/AGENTS/API/DAEMON_SLAYER (middots, arrows, checkmarks,
   U+2260). In-scope for cleanup edits; the repo-wide smart-quote retro-sweep stays operator-gated.
4. LIVE_GATED ledger relocation + live-flip ledger edits are OPERATOR-GATED; body edits are
   resync-compatible. Any ledger change needs a same-change live-gated-resync.js update.
5. DS coverage/count prose: COPY-VERBATIM-ONLY everywhere (README, ARCHITECTURE, DAEMON_SLAYER).
6. OPERATIONS.md vs CLAUDE.md restart.bat contradiction -> resolve OPERATIONS side in C5; CLAUDE.md
   side (if any) goes in the C7 proposal file only.
7. cost_trace.md vs COST_TRACE.md git/disk case mismatch - fix candidate in C7.

## Cluster routing

- C2 ROADMAP: slice A ROADMAP items (fixes failing size-budget test).
- C3 BACKLOG: slice B items + 3 stale-paths.
- C4 WAKEUP: slice A WAKEUP items (keep 909/910/911 sessions verbatim).
- C5 living set: slice C items (ARCH/OPS/API/AGENTS) + README slice-A items.
- C6 DS+ORCH+LIVE_GATED: slice D changelog relocation, slice E round/findings relocation, slice F
  body-only restructure (ledger = operator-gated, propose only). OVERLAY/RC2 (slice G) also lands
  here if C6 has room, else fold into C7.
- C7 cross-ref: dedup pointers, census relocations (dated artifacts -> docs/_archive/), superseded
  headers, README, CLAUDE.md proposal file (restart.bat contradiction, "all 7" scorer count already
  correct there, topology dedup direction).
- C8: glyph check, CI confirm, /done.
