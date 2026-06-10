# Orchestration Plan - Gemini-Directed Fanout Run

LIVING DOC. The gemini director reads this each cycle and picks the next OPEN
session (top-to-bottom, phase order A -> F). The executor cycle updates it:
flip the picked session OPEN -> WIP -> DONE, fill the Commit sha, and append any
newly discovered work to the Findings log at the bottom. When no session is OPEN,
the director emits NO_WORK and the loop self-terminates.

Per-cycle contract (enforced by ops/loop/director_prompt.md):
orchestrator multi-agent fanout (disjoint-file worktree subagents, sole merger,
verifier-gate each slice before merge) -> TDD (failing test first) -> py_compile
before any restart -> full pytest suite green -> UI sessions also pass the 5-phase
fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) + a
Claude_Preview visual check vs /api/state -> commit with a descriptive message ->
push to origin/main -> /done ritual (append docs/LEDGER.md, sync ROADMAP + this
file) -> py ops/loop/done_sentinel.py. No AskUserQuestion; auto-pick safest option.

ASCII only. No em-dashes, en-dashes, or smart quotes.

## Sessions

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| A1 | DS-surface | DS Profile panel (design + axes batch 1: mobility, sustain, scaling, waveclear). New dashboard/routes_ds_profile.py + web/js/panels/ds_profile.js + CSS + web/data/ui_mock fixtures. Mirror dashboard/routes_ds_sweep.py + web/js/panels/ds_sweep.js. 5-phase UI audit + visual check. | DONE | 8e376858 |
| A2 | DS-surface | DS Profile axes batch 2: added threat-range, zone-control, objective-damage, extended-duel to the A1 /api/ds-profile surface (4 -> 8 axes) + dsp-flag markers. matchup split to A2b (pairwise, not a single-champ axis). 5-phase audit ship-ready. | DONE | 3f23e18c |
| A2b | DS-surface | DS Profile matchup readout: surface agents/daemon_slayer/matchup.compute_matchup (already wired at /v2/matchup) as a pairwise lane-matchup card keyed on a selected enemy + levels + items - a DISTINCT surface from the single-champ radar, NOT a 0-100 profile axis. | DONE | 0a017dc4 |
| A3 | DS-coach | Wire the 2 highest-value axes into coach context: anti-tank build hint (vs high-HP enemies) + scaling power-curve, into modes/* prompts. Shadow-log first, then surface. | DONE | 52f76059 |
| B1 | coach-wire | Wire core/laning_verdicts.py + core/event_callouts.py + core/lead_projection.py (pure generators, zero live-coach consumer) into the live coach dict + callouts.js / right_now.js / next.js. Shadow-log validation first. | DONE | 48411bfc |
| C1 | ui-audit | Champ-Select ARAM + Champ-Select Arena: 5-phase fixture audit + Claude_Preview visual validation vs /api/state. Per docs/UI_SCALE_SPEC_V2.md. | DONE | b4bfa05a |
| C2 | ui-audit | Active Match SR + ARAM + Arena: 5-phase audit + visual validation. | DONE | e81495e0 |
| C3 | ui-audit | Post Game Review SR + ARAM + Arena: 5-phase audit + visual validation. | DONE | aa0a5a7e |
| D1 | lift | DS relative-score bar (Aggregator P lift, BACKLOG.md:21): per-row score_pct fill (delta_dps/top_delta*100). Codeable with fixtures; render-gated on locked champ. | DONE | ab176543 |
| D2 | lift | draft tool L (the community fork) Elo log-odds draft aggregator (BACKLOG.md:78): clean algorithm reimplement (NO vendor) over pairwise WR from rewind_history.db. | DONE | 21bf98ef |
| E1 | research | Per-role grading rubric calibration (BACKLOG.md:100): tune core/post_game_rubric.py weight vectors from public per-role reference data. | DONE | 42780b3d |
| E2 | research | LCU data.json diff vs the reference catalog (BACKLOG.md:19) for richer endpoints. Log findings only; no live capture. | DONE | item 348 |
| E3 | research | Competitor-tool lift secondary sweep, framed by technical substance only (keep third-party names out of repo). Output new NOW/FUTURE/CLOSED candidates into the Findings log. | DONE | item 348 |
| F1 | monitoring | Phone monitoring loop-status panel reading ops/loop/control/{cycle.txt,controller.log,claude.done} + last commit (Tailscale-viewable) + daily upstream content-drift poll (tools/upstream_drift_check.py + scheduled task). | DONE | 5bc8f02f+d3fcc070 |
| HZ-A1 | haiku-zero | Lane A laning-scenario precompute (charter 4b PRIMARY). Build core/laning_scenario_precompute.py: for (champ x matchup x level-band x mana-state x cooldown-state) emit trade/all-in/back-off verdicts via agents/daemon_slayer/{scenario_matrix,combo,mana_sim,fight_report}.py + core/laning_verdicts.py. Persist versioned JSON to data/daemon_slayer/laning_scenarios/. Characterization tests vs DS math. BUILD + PERSIST ONLY - the live coach flip is EXCLUDED (needs real-game validation). | DONE | 85b13b7c |
| HZ-A2 | haiku-zero | Lane A extension: add recall/back-timing + power-spike-ETA verdicts (gold-income + item-completion driven, reuse core/lead_projection.py) to the HZ-A1 lookup tables. Characterization tests. BUILD + PERSIST ONLY. | DONE | dc5e6293 |
| LIFT1 | lift | OPERATOR-QUEUED 2026-06-08 (review NEXT, ahead of HZ-B): deep-dive competitor-lift review per headless-upgrade Section 7b (heavyweight general-purpose agent + browser/Firecrawl MCP; 6-point depth checklist per finding WHAT / HOW / HAVE (grep RC + cite file) / WHERE (RC integration point) / EFFORT+RISK / LIFT verdict HIGH-MED-LOW) of 3 tools: (1) https://seb16120.github.io/LoL-Target-Vs-Opponent-What-stat-to-buy/ - target-vs-opponent "what stat to buy" advisor (overlaps DS anti-tank axis A3 core/ds_antitank_hint.py + armor/MR pen build hints + core/damage_mix.py + the HZ-B build-order precompute); (2) https://simulator-tool-r.invalid/ - LoL damage/combat simulator (overlaps the DS engine compute_dps / compute_matchup / fight_report; check for a DS-validation or sim-surface lift); (3) https://www.reddit.com/r/simulator-tool-r/ - community context for #2. Output docs/COMPETITOR_LIFT_<date>.md. ACT: a HIGH-lift that is LOW-risk (presentation over EXISTING DS math, no new dependency/schema lift, testable) ships IN-RUN as its own slice (+Section 3b UI proof if frontend); a HIGH-lift with a new dependency / schema lift / product-direction call -> BACKLOG + issue (FUTURE); MED/LOW always defer. Lift LEGALLY (re-implement in RC's own code, never vendor). Research + triage NOW/FUTURE/CLOSED, do NOT auto-build everything. | DONE | 4b15b031 |
| LOBBY1 | ui-bug | OPERATOR-REPORTED 2026-06-08 (pre-game lobby): "Invite from my top 8 does not work" - inviting a friend from the operator's top-8 list fails. Investigate ROOT CAUSE first (the lobby invite flow: LCU `/lol-lobby/v2/lobby/invitations` + how the dashboard top-8 / friends surface builds the invite payload - summonerId vs puuid form); fix + regression test. LIVE-GATED: final verification needs a real lobby (do code-side + mark live-verification owed if no lobby). | DONE | 1f4f4118 |
| PGR1 | ui-ux | OPERATOR-REPORTED 2026-06-08 (Post Game Review): advance the s220 aggregator-G-style PGR reframe - "what's next" stage. Read the staged s220 plan (S2-S5, the single-match richer layout + 0-100 RC heuristic score over enriched stats, NO Claude/Riot dep - CLAUDE.md Settled) + docs/ROADMAP_HISTORY, pick the next UNSHIPPED stage, ship ONE stage + Section-3b per-page UI-audit + Claude_Preview visual vs /api/state. | DONE | c162e5bd |
| REPLAY1 | ui-bug | OPERATOR-REPORTED 2026-06-08 (Replay page): match ingestion is not up to date after each game. Investigate the post-game ingest chain (the 90s post-gameEnd Match-V5 fetch + INSERT in `core` rewind live writer [reference_rewind_live_writer] -> rewind_history.db -> the replay/replay-page data source + its cache/refresh); root-cause the staleness (timer not firing? cache TTL? page not re-fetching?). Fix + test. LIVE-GATED final verify. | DONE | 647b455e |
| HIST1 | ui-bug | OPERATOR-REPORTED 2026-06-08 (Session + History pages): clicking a populated match row does NOTHING. Wire the row click. Investigate the session/history panel JS (web/js/panels) - the match rows render but have no click handler (or it no-ops); should open that match's detail (-> HIST2 detached PGR). Fix + DOM test + Section-3b audit. | DONE | ac404c13 |
| HIST2 | ui-ux | OPERATOR-REPORTED 2026-06-08 (Session + History pages): a clicked match should populate + switch to a DETACHED historical PGR frame showing the PGR info "as if the match had just ended", SEPARATE from the live in-use last-match PGR (with a back action to return). Reuse the PGR/last-match render against a historical match-id source; MUST NOT mutate or clobber the live last-match PGR state. Tests + Section-3b UI-audit + visual. Pairs with HIST1. | DONE | ac404c13 |
| CS1 | ui-feature | OPERATOR-REPORTED 2026-06-08 (Champ Select): missing the CC-conditional pairing UI elements. Surface the DS cc_conditional pairing data on champ select (the engine has a saturated cc_conditional ecosystem - agents/daemon_slayer cc_conditional registry/accessors). Investigate the existing cc surface + the champ-select panel (web/js/panels/champ_select.js), add the pairing UI + route if needed + test + Section-3b audit + visual. | DONE | 541cd9d3 |
| CS2 | ui-bug | OPERATOR-REPORTED 2026-06-08 (Champ Select): operator must MANUALLY fix summoner spells - on first champ-select load the client defaults to Flash+Heal or Flash+Teleport at random instead of the intended set (Flash+Teleport). Investigate whether RC can push the correct summoner spells via LCU on champ-select enter (mirror lcu/lcu_rune_writer's auto-push pattern; `/lol-champ-select/v1/session/my-selection` spell1Id/spell2Id) - either ADD a spell auto-push (per-champ/per-mode default) or, if RC already pushes and is wrong, fix the source; if purely client-side + unreachable, document as client-only + close. LIVE-GATED. | DONE | 29cd2788 |
| CS3 | ui-ux | OPERATOR-REPORTED 2026-06-08 (Champ Select): the combo timeline / dps scaling / fight model / relative item power panels do NOT need to be seen during champ select -> MOVE them OFF the champ-select page to a more appropriate surface (e.g. an Active-Match / DS / Build view). Relocate placement only - KEEP all data wiring intact (feedback_field_remove_visual_only: this is a move, not a teardown). Tests + Section-3b audit on BOTH the source (champ-select, panels gone) and destination pages. | DONE | d68cddd3 |
| HZ-B1 | haiku-zero | Lane B build-order precompute. Build core/build_order_precompute.py: optimal build orders per (champ x mode x enemy-comp-archetype) from Meraki aram_modifiers + agents/daemon_slayer/rank.py + core/build_order.py + curated loadouts. Persist to data/daemon_slayer/build_orders/. Characterization tests. BUILD + PERSIST ONLY. | DONE | 3a129071 |
| HZ-B2 | haiku-zero | Lane B enemy-comp branch: anti-tank (high-HP comp) vs anti-squishy build-order variants layered on HZ-B1, using the DS anti-tank axis (A3). Characterization tests. BUILD + PERSIST ONLY. | DONE | 8d8bc311 |
| HZ-C1 | haiku-zero | Lane C deterministic choice-coach generator: read the HZ-A / HZ-B tables and emit core/coach_output.py A/B choices (#rn-immediate chips) for laning trade decisions. SHADOW-LOG alongside the live Haiku coach (log both, do NOT replace). Tests. No live flip. | DONE | 3581afed |
| HZ-D1 | haiku-zero | Lane D Electron overlay: advance rc-shell/ per docs/ELECTRON_OVERLAY.md - read it, pick the next UNSHIPPED code-side phase (Phase 2+), Vanguard-safe (DWM window, NO DXGI capture, Borderless). Ship the headless-safe slice; leave live-visual-only work WIP with a note. Tests where applicable. | WIP | 0b2eea62 |

## EXCLUDED (live-game / operator-gated; the director MUST NOT pick these)

- DS Phase-D default-ON flag flips (apply_passive_damage, non-every-AA on_hit, per-stack assumed_stacks) - need real-game re-ranking validation.
- Live caster-stat producer for /anti-tank P3.2 activation + live survivability scorer (egg-resist / Orianna E) - need a live AbilitiesSnapshot / game.
- Champ-select brief Haiku -> deterministic flip - needs live shadow-log accrual + operator OK.
- Game-PC :8892 visual screenshot captures (MCP down post-1PC). C-phase visual validation uses the Claude_Preview MCP against :8888 instead.
- Anything in the CLAUDE.md "Settled - do not re-litigate" set.
- Haiku-to-ZERO LIVE coach flips: removing/replacing a live Haiku call with the HZ-* precompute tables. Per charter 4b "do not flip blind" - needs real/replayed-game validation + operator OK. The HZ-* sessions BUILD + PERSIST + SHADOW-LOG only; Haiku stays the interim floor until validated.

## Findings log (executor appends; newest first)

- 2026-06-10 HZ-D1 slice 1 (loop run 2026-06-10-01, merge 0b2eea62): the
  frameless companion was never draggable - Phase 1 deferred the drag region to
  "CSS in the page" and the dashboard never got one. Shipped shell-side instead:
  NEW pure module rc-shell/src/drag_region.js (CSS + idempotent mount JS),
  injected by main.js on did-finish-load via webContents.insertCSS +
  executeJavaScript - no dashboard change, preload stays empty (sandbox:true
  preloads cannot require local modules, so the preload route is a dead-end).
  Overlay gets the same injection: inert while click-through, grabbable when
  ACTIVE = the overlay is now user-movable (a Phase 4 interactive control).
  Overlay position is NOT persisted yet (companion position is) - candidate for
  the next D1 slice. Live drag-feel capture OWED (headless run). node 77 -> 85.

- 2026-06-09 HZ-C1 STALE-PREMISE -> plan flipped DONE (commit 3581afed, LEDGER
  item 366). The director flagged it (3581afed may have shipped); VERIFIED true
  (the D1/D2/B1 stale-shipped trap). HZ-C1's full scope shipped 2026-06-09 01:56
  in a separate /gemini-headless-upgrade run (run 2026-06-09-01): NEW
  core/precomputed_laning_coach.py (one HZ-A laning cell -> two grounded A/B
  CoachChoice, pure static read, no Haiku / no :8893) + core/hz_choice_shadow.py
  (shadow-log alongside live Haiku, seed-coverage hits/misses) wired into
  dashboard/_state_builder.py via
  _deterministic_coaching.shadow_log_precomputed_choices (additive, fail-soft, NO
  live output change); +48 tests. GROUND TRUTH this cycle: all 6 deliverable files
  present on disk; the 3 HZ-C1 test files (test_precomputed_laning_coach.py /
  test_hz_choice_shadow.py / test_hz_c1_wiring.py) 50/50 PASS fresh; LEDGER item
  366 + ROADMAP line 20 + WAKEUP already synced for the whole HZ-C arc (commits
  72e5bf0d + 41750fa1) - ONLY this plan's HZ-C1 row (OPEN) + findings were never
  flipped. NO code change (re-implementing would clobber the live item-366 module
  + 48 tests). NO new LEDGER item (a stale-premise doc flip is not an item
  completion - the A2b/HZ-A1 false-alarm precedent below). The rest of the HZ-C
  arc was DISCOVERED + shipped the same run (NOT plan rows, so the director cannot
  re-pick them; all ledgered): HZ-C2 build A/B over HZ-B2 (item 367, 5627053b),
  hz_shadow_report flip-readiness gate (item 368, 1d116194), native coach-signal
  capture (item 369, 1f702711), full 171-champ SR seed expansion + slim/compact v3
  schema (item 370, 4202760c; laning JSON now LFS-tracked,
  reference_git_lfs_laning_artifact). BUILD + PERSIST + SHADOW only; the live coach
  flip stays EXCLUDED (charter 4b do-not-flip-blind). NEXT OPEN = HZ-D1 (Electron
  overlay Phase 2+); the gated post-HZ-D path is real-game shadow accrual ->
  precompute-vs-Haiku agreement (item-369 native capture) -> the coach flip.
- 2026-06-08 HZ-B2 DONE (commit 8d8bc311) + draft-elo clean-checkout test fix
  (d9347d62, item 363). HZ-B2: anti_tank vs anti_squishy build-order VARIANTS layered
  on HZ-B1 via the DS anti-tank axis (A3, core/ds_antitank_hint). Single coupled engine
  slice (1 worktree agent + merger ground-truth verify). DISTINCT from HZ-B1's fixed
  comp-shape biases: the two durability EXTREMES as a champion-decision pair, each
  modulated per champ by the A3 anti-tank score (a kit that already shreds -> softer
  synthetic wall). SIBLING module core/build_order_variants.py (keeps HZ-B1's schema +
  23 tests byte-identical) -> data/daemon_slayer/build_orders/<patch>/
  build_order_variants_<mode>.json (10-champ SR seed x 2 = 20 cells). +28 tests. BUILD +
  PERSIST only. MERGER independently re-probed the agent's "1 pre-existing failure"
  claim: test_target_state_caller_p1l4.py::test_live_items_path_only_wired_to_ds_preview
  is a WORKTREE-PATH artifact (the test skips any path containing .claude, so a checkout
  under .claude/worktrees/ skips the whole tree); it PASSES on main (full tests/ 5529
  passed / 0 fail). Earlier this turn (operator-flagged) the draft-elo + ban-suggest
  tests (16 fail + 6 err on a clean checkout) were fixed root-cause (item 363): they
  depended on the gitignored live rewind_history.db; open_ro now honors an RC_REWIND_DB
  env override + a self-contained tests/_draft_elo_fixture.py. Memory
  feedback_clean_checkout_probe written (I had wrongly dismissed the same cluster as a
  worktree artifact at item 362; the operator was right - reproduce the clean condition
  before dismissing a fresh-env failure). **NEXT OPEN = HZ-C1** (deterministic A/B
  choice-coach over HZ-A/HZ-B, shadow-log, no flip), then HZ-D1.
- 2026-06-08 HZ-B1 DONE (commit 3a129071; + cc_pairing guard fix 76691def).
  Lane B build-order precompute per (champ x mode x enemy-comp-archetype). Single
  coupled engine slice (1 worktree agent + merger ground-truth verify, the HZ-A2
  precedent). CONFIRMED-NEW-AXIS: the shipped build_orders_{sr,aram,arena}.json
  (item 265/266) key on a DAMAGE-PROFILE axis (ad/ap/balanced over a CONSTANT enemy
  stat block), NOT enemy-comp-archetype - HZ-B1 varies the enemy stat SHAPE.
  TAXONOMY (4 classes re-parameterizing plan_build_order levers): frontline_heavy /
  burst_heavy / poke / mixed. NEW core/build_order_precompute.py (generator + reader +
  CLI, HZ-A1 idioms) -> data/daemon_slayer/build_orders/<patch>/ (NEW subdir, the
  item-265/266 table untouched); 10-champ SR seed x 4 = 40 cells. +23 characterization
  tests. BUILD + PERSIST only (live coach flip EXCLUDED, charter 4b; read by HZ-C1).
  MERGER CAUGHT a REAL CS1 regression the subagent dismissed as "pre-existing":
  agents/daemon_slayer/tests/test_cc_conditional_forward_marker.py::NoConsumerWireTests
  failed on main - cc_pairing.py (item 359) wired a new cc_conditional consumer without
  updating the operator-gated forward-marker allowlist. CI MISSED it (CI = py_compile +
  ruff + Share-check only, NO pytest; the CS1 gate ran tests/ but not the DS-dir suite).
  Fixed (76691def, cc_pairing -> _ALLOWED_SOURCE_FILES, the operator CS1 request is the
  gate-crossing) + Share re-synced. The subagent's "tests/ 16 failed + 6 errors" was a
  worktree-missing-gitignored-data artifact, DISPROVEN: merged-main tests/ 5501 passed /
  0 fail, DS-dir 7043 / 0, ds_share_sync --check green, ENGINE 1.120.0. PROCESS NOTE: CI
  does NOT run pytest - the local gate MUST run BOTH tests/ AND agents/daemon_slayer/tests/
  before declaring green. **NEXT OPEN = HZ-B2** (anti-tank/anti-squishy variants), then
  HZ-C1 / HZ-D1.
- 2026-06-08 CS3 DONE (commit d68cddd3). Moved the 4 DS analysis panels OFF
  champ-select to the Active Match view (operator-chosen destination via one framed
  AskUserQuestion). Single coupled UI slice (1 worktree agent + merger verify). MAPPED
  by rendered title: combo timeline = csv-sugg-ds-combo, dps scaling = csv-sugg-ds-sweep,
  fight model = csv-sugg-ds-matchup (the 1v1 verdict, the only fight panel), relative
  item power = csv-ds-relscore. LEFT on champ-select: ds-profile / ds-knobs / ds-statcheck
  + the CS1 cc-pairing. RELOCATE not teardown - mounts moved index.html (same ids, routes
  + render fns UNCHANGED), invocations moved champ_select.js -> active_match.js fed a
  synthetic champ-select state from the LIVE coach payload (my_champion via the canonical
  _resolveChampId/CHAMPS.byId, matchup enemy = first liveclient enemy, relscore = owned
  items), fail-soft hidden with no live data. The merge full-suite gate caught the slice's
  lone red - a BRITTLE test (test_spike_curve.py::test_active_match_uses_champs_for_id_lookup
  exact-substring `import { ITEMS, CHAMPS }` broke when CS3 appended _resolveChampId to that
  destructure); robustified to a regex, intent preserved (CHAMPS.byId guard untouched). Full
  RC tests/ 5478 passed / 2 skip / 0 fail; ruff + node --check clean; 5-phase audit PASS on
  BOTH pages. OWED (live-gated): in-game visual capture of the 4 panels populated at once.
  The operator UI/UX batch (LOBBY1..CS3) is now FULLY SHIPPED. **NEXT OPEN = HZ-B1** (Lane B
  build-order precompute), then HZ-B2 / HZ-C1 / HZ-D1.
- 2026-06-08 HIST1+HIST2 + CS1 + CS2 DONE (3 parallel disjoint-file worktree
  slices, merged + full-suite-verified; commits ac404c13 / 541cd9d3 / 29cd2788).
  Operator "continue next open items in parallel". The merger cherry-picked the 3
  worktree branches onto main (web/index.html auto-merged clean - HIST added a new
  #view-historical-pgr section, CS1 added a champ-select mount div, non-overlapping
  hunks), then re-ran on the MERGED tree: 99 new+engine tests green + full RC tests/
  5455 passed / 2 skip / 0 fail (the lone red was the PRE-EXISTING ROADMAP doc-size
  budget red, untouched by the merge, cleared this commit by trimming the line-22
  batch entry); ruff + node --check + py_compile clean on every changed file; RC
  restarted pid 16308 reload_ok. All 3 had REAL premises (NOT the D1/D2/B1 stale-
  shipped trap). **HIST1+HIST2** (item 358): the Session/History match rows were
  inert (no click handler) + the PGR builder was latest-only; added match_ts to
  _build_last_match + ?match_ts= to /api/last-match + a NEW detached
  #view-historical-pgr (own hpgr- state, the live last-match PGR provably
  unclobbered). **CS1** (item 359): cc_conditional was saturated but only surfaced
  as scalars; NEW agents/daemon_slayer/cc_pairing.compute_cc_pairing join + GET
  /api/cc-pairing + a champ-select pairing panel (which ally enables the picked
  champ's conditional CC). **CS2** (item 360): the LCU summoner-spell push was gated
  behind a SUCCESSFUL rune-page write (skipped on the 3-page-cap failure, item 210);
  made it self-correcting + rune-independent in RuneWriter._poll() (Flash+TP SR /
  Flash+Snowball ARAM, PATCH only on a live mismatch). OWED (live-gated): CS1
  champ-select visual capture + CS2 real-champ-select end-to-end Flash+TP correction.
  CS3 was DEFERRED from this parallel batch (it edits champ_select.js + index.html,
  the same files CS1 touches -> guaranteed worktree merge conflict; sequence it AFTER
  CS1 landed). **NEXT OPEN = CS3** (move combo/dps/fight-model/item-power panels OFF
  champ-select, relocate-only), then HZ-B1.
- 2026-06-08 LIFT1 DONE (commit 4b15b031, docs/COMPETITOR_LIFT_2026-06-08.md).
  Deep-dive lift review (2 heavyweight agents, 6-point checklist, every HAVE/WHERE
  premise re-verified live) of the seb16120 target-vs-opponent stat advisor +
  simulator tool R.com (+ r/simulator tool R). VERDICT: RC SUPERSEDES both - simulator tool R's
  full surface (combo / 1v1 / DPS-TTK / EHP / build-sort / sandbox) already shipped
  via the 2026-05-30 calc.gg lift (combo.py / matchup.py / dps.py / fight_report.py +
  ds_combo.js / ds_matchup.js); the stat advisor is a manual-entry defensive-EHP calc
  RC beats automatically (ehp.py + core/defensive_picks.py + the live
  cc_blended_ehp_threat panel). NO HIGH-lift+LOW-risk finding -> per the ACT gate
  (MED/LOW always defer) NO in-run code slice. 2 FUTURE gaps -> BACKLOG: T1-F3
  enemy-pen-aware effective resists (ehp.py compute_ehp documented Phase-1 omission;
  MED engine schema lift, operator-gated) + T2-F4 rune/keystone in the combo SURFACE
  (routes_ds_combo.py threads no runes= param; MED route+panel wire-up + Sec-3b UI
  ritual). Minor deferred: T2-F3 TTK headline, T1-F4 per-stat EHP/gold. Docs-only:
  DS 7024 / RC 5352 passed, 0 regressions. NEXT OPEN = the operator UI/UX + bug
  batch (LOBBY1..CS3), then HZ-B.

- 2026-06-08 OPERATOR UI/UX + BUG BATCH queued (mid-loop interrupt, post-HZ-A2).
  The operator supplied a batch of page-specific issues to work NEXT; added as OPEN
  sessions (placed ahead of HZ-B so the loop picks them in upcoming cycles, after
  LIFT1): LOBBY1 (top-8 invite broken), PGR1 (s220 PGR reframe next stage), REPLAY1
  (match ingestion stale after each game), HIST1 (session/history match-row click is
  a no-op), HIST2 (detached historical PGR frame, separate from the live PGR), CS1
  (missing CC-conditional pairing UI on champ select), CS2 (summoner-spell defaults
  wrong on first champ-select load - investigate an LCU auto-push), CS3 (move combo
  timeline / dps scaling / fight model / relative item power OFF champ select). The
  "Continue ELECTRON_OVERLAY.md roadmap" item = the EXISTING HZ-D1 session (not
  duplicated). Several are LIVE-GATED (LOBBY1 / REPLAY1 / CS2 need a real lobby /
  game) + several touch a page (Section-3b UI-audit + visual required). Each row is
  framed INVESTIGATE-ROOT-CAUSE-FIRST; the executor verifies the premise live before
  fixing (some may be stale-premise, the D1/D2/B1 pattern). Operator can reorder via
  the loop control panel.
- 2026-06-08 REPLAY1 DONE (commit 647b455e). Replay / rewind ingest froze at
  2026-05-23 while the operator kept playing. ROOT CAUSE (verified live):
  scripts/rewind_catchup.py::resolve_current_puuid derived the account from the
  DB MAJORITY puuid - after the operator switched Riot ID (SamplePlayer#Vayne ->
  #Trist) the DB stayed dominated by ~2900 old-account rows, so resolution kept
  re-locking the OLD account + never discovered the new one (the new account has
  0 rows yet = chicken-and-egg). lib/rewind_live_writer.py read the stale puuid
  from rewind_catchup.state.json + only saw already-ingested old matches -> every
  90s post-gameEnd write was a silent already_present no-op. Probed: state puuid
  -> old Vayne (old URF matches, all in DB); current Trist account had 37
  un-ingested matches; get_account_by_riot_id("SamplePlayer","Trist") -> the right
  puuid with recent games. FIX: a persisted `riot_id` in the state sentinel is an
  authoritative sticky override - resolve_current_puuid resolves it via Account-V1
  BEFORE the DB-majority fallback (new priority step 3); main() persists
  args.riot_id. DATA RECOVERY (same fix): ran catchup --riot-id "SamplePlayer#Trist"
  -> state.json corrected (puuid+riot_id), 37 matches backfilled, rewind DB newest
  2026-05-23 -> 2026-06-08; live writer now resolves the current account
  (verified _resolve_latest_puuid). TDD tests/test_rewind_catchup_puuid.py (7)
  pins the priority order. RC suite 5376 / 2 skip / 0 fail; ruff clean. Backend +
  data only (no UI - replay page reads the now-fresh DB unchanged); state.json +
  rewind_history.db are gitignored (not committed). LIVE end-to-end (next-game
  auto-ingest) OWED. FUTURE (robustness): the live writer still reads puuid from
  state.json - a future account switch needs one catchup --riot-id run (or wiring
  the live LCU current-summoner Riot ID into the writer) before auto-ingest
  resumes; logged not built.
- 2026-06-08 PGR1 DONE (commit c162e5bd). s220 PGR reframe: shipped the last
  deferred S5 piece - per-player gold@10 / cs@10 in the lane-comparison card.
  DISCOVERY: S2/S3/S4 + the S5 Arena-augment loadout variant (pgr_loadout.js)
  were ALREADY shipped + wired (the PGR_REFRAME_S2.md staging doc was just not
  synced); the genuine gap was the @N lane head-to-head S4 punted as "no
  per-participant timeline". GROUND TRUTH: rewind_history.db.timeline_frames
  (664752 rows) AND the Match-V5 timeline both carry per-participant frames
  (total_gold + minions_killed + jungle_minions) - the team-aggregate series was
  a reducer choice, not a data gap. FIX: _enrich_match_timeline emits an `at_n`
  per-participant snapshot (frame nearest 10 min; sub-10-min -> last frame);
  _fold_at_n_into_roster copies gold_at_n/cs_at_n/at_n_minute onto each roster
  row (called from _attach_match_timeline); pgr_lane_compare.js leads with
  gold@N / cs@N head-to-head rows (reuses _rowHtml grid), degrades to final-only
  when absent. TDD +6 timeline tests + DOM/fixture flip of the stale "deferred"
  guard. RC suite 5369 / 2 skip / 0 fail; ruff + node --check clean; 5-phase UI
  audit PASS (0 MUST-FIX); verifier CONFIRM (the lone REFUTE was a mis-worded
  ruff claim on my side - .py ruff clean, not a code defect). Backend Python
  module -> RC restarted (pid 3292, last_reload_ok). VISUAL CAPTURE OWED
  (carry-forward): Game-PC :8892 MCP down (project_gamepc_mcp_boot_gap) +
  Claude_Preview can't attach the self-signed HTTPS :8888 - capture the @N row
  via ?ui_mock=1#last-match next time a visual path is up. S5 residual (FUTURE,
  minor): responsive polish; ARAM/Arena lane-compare stays hidden by design.
- 2026-06-08 LOBBY1 DONE (commit 1f4f4118). Top 8 / friends invites silently
  failed ("could not resolve summoner: <rid>"). ROOT CAUSE: lobby.invite_player
  (tools/gamepc_lcu_agent.py, non-frozen) resolved Name#TAG -> summonerId ONLY via
  /lol-summoner/v1/summoners/by-name/<name>, which Riot removed in the Riot ID
  migration (404s on current clients); the Top 8 add-flow (main.js:5003) only
  captures Name#TAG (no summonerId/puuid) so the dead path was the SOLE route ->
  100% failure. FIX: new _resolve_invitee_summoner_id layers resolution most-
  reliable-first - explicit summonerId -> puuid (/summoners-by-puuid-cached) ->
  scan /lol-chat/v1/friends (invite targets ARE friends; that resource carries
  gameName/gameTag/summonerId) -> legacy by-name LAST for ancient builds. Handler
  also accepts puuid + reports resolved_via. TDD: tests/test_lobby_invite_resolution.py
  (10 pass / 1 live-skip) reproduces the failure + pins resolution order, body
  shape {[{"toSummonerId":..}]}, and the dashboard allowlist. RC suite 5362 passed /
  2 skip / 0 fail. ORCHESTRATION CALL (auto-pick under no-AskUserQuestion): one
  tightly-coupled backend slice (agent + its test), so ran inline as sole
  orchestrator with the read-only verifier subagent as the pre-commit ground-truth
  gate (CONFIRM all 6 claims; siblings 46/0/0) rather than degenerate a 2-file
  coupled fix into worktree fan-out. BACKEND-ONLY (LCU agent) - NO web/route/asset
  delta, so NO 5-phase UI audit + NO RC restart (and no live lobby to capture).
  OWED (FUTURE): (1) LIVE end-to-end invite verification needs a real lobby +
  online friend (RC_LIVE_LOBBY=1 RC_LIVE_INVITE_RID=...); (2) inviting a NON-friend
  by Riot ID still depends on the dead by-name fallback - a modern alias-lookup
  (gameName/tagLine -> puuid) is owed but unverifiable offline, so not shipped
  blind; (3) RC-LCUAgent must reload to pick up the new code for live effect.
- 2026-06-08 HZ-A2 DONE (item 353, commit dc5e6293). Lane A extension: a
  gold-income + item-completion driven economy block layered onto the HZ-A1
  laning-scenario cells. NEW pure primitives in core/lead_projection.py (the
  shared macro-economy authority, project_lead untouched): minutes_for_level (the
  band<->minute bridge off the existing level benchmark), gold_income_per_min +
  expected_gold_earned (gross-income benchmark, ARAM 600 > SR 450), a
  cumulative-gold spike ladder (component 1100 / first_item 3000 / two_item 6200 /
  three_item 9400 + SPIKE_COMPLETE), next_spike, spike_threshold,
  spike_eta_seconds. core/laning_scenario_precompute.py: economy_cell +
  _recall_verdict compose those into a per-cell {recall, next_spike, spike_eta_s,
  gold_at_band} block threaded into every leaf via _cell_from_result; schema
  laning_scenarios/v1 -> v2 + an economy dimensions stanza. DESIGN CALL (auto-pick
  under no-AskUserQuestion): recall is gold/spike + mana driven, NOT trade-verdict
  driven - the combat verdict is a fight read, not an economy one; the cell-level
  economy input is the mana state. Rules: low-mana mana champ (manaless excluded)
  -> recall_now; unspent completed-item gold + no imminent spike -> recall_now;
  next spike within 60s -> back_soon; core build complete -> hold. ORCHESTRATION
  CALL: HZ-A2 is a hard LINEAR A->B dependency (the precompute imports the
  lead_projection primitives) over ~120 coupled LOC, so "true-concurrency"
  worktree fan-out degenerates to sequential + a guaranteed-red B slice; per the
  framework's own "engine slice first, then dependents" + auto-pick-safest, ran it
  as the sole orchestrator with TDD (31 red -> green) and the read-only verifier
  subagent as the pre-commit ground-truth gate (the integrity-critical part of the
  pattern). Regenerated SR seed table (1600 cells, v2, 1001402 bytes): recall_now
  940 / back_soon 440 / hold 220; next_spike component/two_item/three_item/complete
  across L2/L6/L11/L16 (verifier loaded the JSON + walked all 1600 leaves: 0
  missing economy). +35 tests (tests/test_lead_projection_economy.py 19,
  tests/test_laning_scenario_economy.py 16); HZ-A1 schema assertion bumped v1->v2.
  verifier CONFIRM all 6 claims (76/0 on the 4 module files; full RC suite 5352
  passed / 1 skip / 85 subtests / 0 fail; ruff clean). BUILD + PERSIST only - the
  live coach flip stays EXCLUDED (charter 4b do-not-flip-blind). NO engine touch
  (ENGINE 1.120.0, no DS bounce; ds_share_sync --check green - laning_scenarios is
  NOT part of the Share package, HZ-A1 precedent); no web/route/asset -> no
  UI-audit, no RC restart (table read by FUTURE consumer HZ-C1). The directive's
  "clear false-alarm blockers in ROADMAP/BACKLOG" was a no-op: the HZ-A1 false
  alarm was resolved last cycle (HEAD 0f32dd81) and never entered ROADMAP/BACKLOG
  as a blocker (grep clean). NEXT OPEN = HZ-B1 (Lane B build-order precompute).
- 2026-06-08 REGRESSION FALSE ALARM (gemini director, /gemini-headless-upgrade cycle).
  Director claimed the WAKEUP "+16 characterization tests" for
  core/laning_scenario_precompute.py were never committed ("no test files in the commit
  diff") and ordered them re-authored. GROUND TRUTH (checked 4 ways - Glob, git show
  --stat 85b13b7c, full file read, fresh pytest): tests/test_laning_scenario_precompute.py
  EXISTS (186 lines, 16 tests), was committed IN the feature commit 85b13b7c
  ("tests/test_laning_scenario_precompute.py | 186 +"), and is 16/16 GREEN this run (use
  Programs\Python\Python314\python.exe - the `py` launcher resolves to a pythoncore with no
  pytest). Read-only verifier subagent independently re-CONFIRMED (file-exists YES,
  in-commit-85b13b7c YES, 16/16 pass, engine-characterization test
  test_cell_verdict_matches_compute_matchup at line 111 pins cell["verdict"] ==
  compute_matchup). ROOT CAUSE: HEAD is the trailing docs-sync commit 49da557a (LEDGER 352
  + ROADMAP/WAKEUP, NO test files); the director diffed THAT instead of the feature commit
  one below it (85b13b7c). RESOLUTION: NO code change - declined to author duplicate tests
  (would collide with the shipped file). HZ-A1 + its 16 tests stay DONE (LEDGER item 352);
  no LEDGER entry added (a false-alarm rebuttal is not an item completion). NEXT OPEN
  unchanged = HZ-A2 (recall/back-timing + power-spike-ETA).
- 2026-06-08 HZ-A1 DONE (commit 85b13b7c). NEW core/laning_scenario_precompute.py:
  an offline deterministic sweep of the SHIPPED matchup engine
  (agents.daemon_slayer.matchup.compute_matchup) over (my_champ x enemy x
  level-band x mana-state x cooldown-state) -> trade / all_in / back_off / even
  verdicts; generator + fail-soft reader (load_laning_scenarios + lookup, mtime
  cache) + CLI; atomic versioned JSON ->
  data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_<mode>.json.
  Dimensions: 4 level-bands (L2/L6/L11/L16) x mana full/low x cd all_up/no_ult.
  mana-state low = the affordable combo prefix from mana_sim's per-cast cost
  ledger (manaless -> low==full, flagged); cd no_ult drops R. KEY MODEL FIX
  caught in build: the enemy is modelled at FULL resources (sequence_b = full
  rotation) so a same-level full-state mirror is symmetric (even) - the first cut
  left the enemy on the engine default (with AA, no E) and skewed even the mirror
  to back_off -0.10. Committed SR seed = 10-champ archetype-diverse SAMPLE (not a
  tier list), itemless v1, 1600 leaf cells / 667KB; verdict dist even 793 /
  back_off 696 / trade 111 / all_in 0 (0 all_in is HONEST for itemless - all_in
  needs full HP removal; it surfaces once an item axis lands, HZ-A2 /
  build-order precompute). 16 characterization tests pin cells == compute_matchup;
  verifier CONFIRM on the slice (16/16, 3 files present, ruff + py_compile clean).
  Full RC suite 5316 passed / 1 skip (the lone "fail" the verifier flagged was the
  PRE-EXISTING ROADMAP doc-size budget red, FIXED in the same commit by relocating
  shipped item 344 -> docs/ROADMAP_HISTORY.md: ROADMAP 82898 -> 79228 < 81920). NO
  engine touch -> ENGINE 1.120.0, no DS bounce, no Share sync; no web/ -> no
  UI-audit; RC not restarted (no route/asset delta - the table is read by a FUTURE
  consumer, HZ-C1). BUILD + PERSIST + READ only; live coach flip EXCLUDED (charter
  4b do-not-flip-blind). DISCOVERED/deferred: ARAM + Arena mode tables are a
  --mode away (the generator does all 3) but the laning-trade framing is SR;
  full-roster coverage is a --champions/--enemies expand (172^2 pairs) deferred
  offline for cost. NEXT OPEN = HZ-A2 (recall/back-timing + power-spike-ETA).
- 2026-06-08 RESEED (operator-directed, /gemini-headless-upgrade relaunch). A1-F1 were
  FULLY CLOSED -> director correctly emitted NO_WORK and self-terminated. Operator chose
  to refill with the charter 4b PRIMARY north star (drive live Haiku usage to ZERO).
  Seeded HZ-A1/A2 (Lane A laning-scenario precompute), HZ-B1/B2 (Lane B build-order
  precompute), HZ-C1 (Lane C deterministic choice-coach, shadow-log), HZ-D1 (Lane D
  Electron overlay). All scoped BUILD + PERSIST + SHADOW-LOG only; live coach flips stay
  EXCLUDED (charter "do not flip blind", needs real-game validation). Substrate paths
  verified present (scenario_matrix/combo/mana_sim/fight_report/rank/build_order/
  laning_verdicts/lead_projection/coach_output, rc-shell, ELECTRON_OVERLAY.md).
- 2026-06-07 E2 + E3 + F1 DONE + DS scout EXHAUSTED (item 348; parallel "next open
  items" dispatch). **Fanout A1-F1 now FULLY CLOSED -> NO_WORK; loop self-terminates.**
  No code shipped (research / reconcile only); RC not restarted; ENGINE 1.120.0.
  - **E2** (LCU richer-endpoint diff, research): RC's live `/lol-` surface vs the
    KebsCS reference catalog (reference-only, NOT vendored). Top-3 actionable richer
    endpoints, none blocked: (1) mastery-by-puuid FULL-TEAM
    `/lol-champion-mastery/v1/player/{puuid}/champion-mastery` (RC reads only SELF
    today, tools/gamepc_lcu_agent.py:454) -> champ-select "ally one-trick / off-role"
    signal into existing pickban / team-context panels (H); (2) match `game-timelines`
    + fuller `/games/{gameId}` parse (coaches/lcu_postgame_collector.py:764,
    dashboard/builders_lcu_enrich.py:17) -> per-frame gold/xp + ITEM_PURCHASED /
    SKILL_LEVEL_UP for the BACKLOG:24 spell-WPA / skill-order extension + s220 PGR
    curves (H); (3) career-stats per-champ aggregates for ally comfort (M).
    BLOCKED / dead-end (do NOT re-pick): augment LCU API (`/lol-cherry/*` absent,
    ADR-settled); any Arena / Cherry / Mayhem lobby-create payload (zero in corpus,
    needs live capture).
  - **E3** (technical-substance lift sweep, no vendor names): NO new NOW-bucket
    candidate exists (headless-safe lift lane exhausted). 5 new FUTURE candidates
    (all live / product / min-N gated): per-summspell+keystone WPA residual;
    recall-affordability / back-timing advisor; live enemy damage-type-split
    armor/MR chip; objective-tempo x level/recall cross-ref; forward spike-ETA from
    gold-income. Biggest un-shipped (logged, unbuilt): per-lobby-player threat tags
    (9x Match-V5 fan-out + product call). 3 STALE-SHIPPED premises to skip (the
    D1/D2/B1 trap): anti-heal callout (core/heal_threat.py item 285), inhibitor
    callout (core/event_callouts.py:329), per-item WPA tierlist (item 273) - their
    "open" verdicts live in DATED COMPETITOR_LIFT docs, left UNEDITED per the
    dated-artifact rule.
  - **F1** (monitor panel + drift poll): stale-premise - BOTH halves already shipped
    (monitor = item 346, 5bc8f02f panel + 3b3ea2e1 reconcile; drift poll = d3fcc070
    tools/upstream_drift_check.py + RC-UpstreamDriftCheck 03:45). DONE. The control
    half (Tailscale STOP / directive page) is a separate deferred item, not F1 scope.
  - **DS forward-marker scout** (item 348, worktree): EXHAUSTED. Entire un-taken
    LIFT_FOUND queue from items 344/345 REJECTED vs live loaders (cc_conditional
    get_max_conditional_cc_seconds = already-surfaced + registry-fn; cross-spell-amp
    / passive_heal / passive_damage candidates = registries NOT loaded into
    DataSnapshot or engine literals; survivability = off-channel; bilinear =
    synthetic-only DamageBlock-arg). The 2 mined sidecars (wiki_stats /
    cdragon_spell_stats) are FULLY mined; the unmined wiki_ability_stats carries no
    clean scalar (every `*_raw` is unparsed wiki markup `{{fd|0.25}}` /
    `{{ap|20 to 12}}` / `Varied` / `none`). Confirms items 344/345: further DS
    magnitude growth needs a NEW extractor key (patch-refresh schema change), NOT
    another scan. Worktree clean, ENGINE 1.120.0 untouched. Memory
    `reference_ds_forward_marker_exhausted` written.
- 2026-06-07 E1 DONE (item 335, commit 42780b3d). NOT a stale premise
  (unlike D1/D2/B1): core/post_game_rubric.py existed + was LIVE-wired
  (dashboard/routes_post_game_rubric.py -> web/js/panels/last_match.js hero
  grade chip) but its weights were hand-estimated "STARTING" values never
  calibrated against data. GROUND TRUTH: over 5957 ranked-SR participant
  rows in data/rewind_history.db (map 11 CLASSIC >=15min, real obj via
  core.obj_participation), the CURRENT rubric scored the MEDIAN game a D for
  TOP/JG/MID/ADC and C for SUP (scores 33-46) - violating the module's own
  documented "median 1.0-profile -> ~50 (B)" invariant. Root cause: dpm
  baselines ran 40-80% low (TOP 480 vs real 717), KDA baselines ran high
  (TOP 2.50 vs real 1.78), and weight sums (3.70-4.60) fell below the 5.0
  the x10 multiplier needs for a 50 median. PUBLIC SOURCE (unrankedsmurfs)
  confirms Riot publishes NO exact weights - only per-role EMPHASIS ordering
  (CS-led TOP/MID, obj/KP-heaviest JG, vision + strict-KDA + CC SUP,
  carry-damage ADC). FIX (two grounded axes): (1) _ROLE_BASELINES re-anchored
  to the empirical real per-role medians; (2) _DEFAULT_WEIGHTS re-ordered to
  the source emphasis with every role's vector summing to 5.0 (median ->
  50.0 = B floor). VALIDATED on the same corpus: median now grades B for all
  5 roles (TOP 51.5 / JG 53.3 / MID 52.0 / ADC 53.5 / SUP 54.6) with a sane
  S+..D spread. New durable db-independent invariants
  (CalibrationInvariantTests): per-role weight sum == 5.0 + baseline-profile
  grades exactly B at 50.0. Blast radius: 1 source + 4 test files; the obj
  dilution/compose tests (route + postmortem) needed ally-objective padding
  so the operator share stays below the 2x-median obj clamp (high-share
  games correctly saturate now that obj baselines are the real ~0.13-0.375
  medians). verifier CONFIRM from clean state (6 files 197/0; full RC 5257
  passed / 1 skip / 0 fail; ruff clean; 5 weight sums all 5.0). No engine
  touch -> ENGINE 1.120.0, no DS bounce, no Share sync; RC restarted (route
  reload). FUTURE: CC-score is a source-cited SUP signal with no rubric axis
  yet (documented gap); obj baselines are SR-only (event modes still 0).
  NEXT OPEN = E2 (LCU data.json diff research).
- 2026-06-06 D2 DONE (item 334, ship commit 21bf98ef). STALE-PREMISE
  (verify-premise, the D1 + B1 precedent): the draft tool L (the community fork) Elo log-odds draft
  aggregator was ALREADY SHIPPED 2026-05-20. core/draft_elo.py (pure math:
  winrate_to_rating = -400*log10(1/wr-1), rating_to_winrate = 1/(1+10^(-d/400)),
  team_score = sum(ally champ+pair+matchup) - sum(enemy champ+pair), +
  top_contributions hover decomposition) + core/draft_elo_db.py
  (rewind_history.db sqlite priors solo/pair/matchup, read-only mode=ro conn,
  Laplace-smoothed via core.smoothed_rates per CLAUDE.md #90, NO aggregator D) +
  dashboard/routes_draft_elo.py (GET /api/draft-elo, 5min TTL) +
  web/js/panels/draft_elo.js (champ-select chip + n= density + hover-only
  contribution strip). Ship chain 21bf98ef aggregator + a148f779 frontend chip
  + daa5a098 / 97ab12e9 per-row contribution hover + 87efa337 ESC. The directive
  read BACKLOG.md:78 FUTURE entry but missed the (SHIPPED 2026-05-20 ab3f553 +
  00051f3) reconciliation marker just below it; re-implementing would clobber a
  live 42-test module, so NO source change. GROUND TRUTH this cycle: live
  /api/draft-elo (ally 22,67,64,89,412 vs enemy 51,141,238,555,235) -> ok=true
  with real rewind-db ratings (solo_counts e.g. [33,64] / [35,72]; computed
  champ/pair/matchup ratings). Coverage already complete - tests/test_draft_elo.py
  (28) + tests/test_draft_elo_panel_dom.py (14 hover contract) +
  tests/snapshot_panels/test_draft_elo_panel.py = 42 passed; UNLIKE D1 there is
  NO owed clause (the snapshot view test already exists). Full RC suite 5255
  passed / 1 skip / 0 fail / 85 subtests (observed this run, unchanged - zero
  test delta). No source change -> no asset-hash reload, no RC restart; ENGINE
  1.120.0, no DS bounce, no Share sync. NEXT OPEN = E1 (per-role grading rubric
  calibration).
- 2026-06-06 D1 DONE (item 333, commit ab176543): DS relative-score bar.
  STALE-PREMISE (verify-premise, cycle-3/4 precedent): the feature was ALREADY
  SHIPPED as item 220 (2026-05-30) - dashboard/routes_ds_relscore.py (GET
  /api/ds-relscore, score_pct = round(delta_dps/top_delta*100,1), row0=100.0,
  READ-ONLY auto-resolved target, render-gated) + web/js/panels/ds_relscore.js
  (#csv-ds-relscore champ-select bar) + a backend route test
  (test_routes_ds_relscore.py) + a panel-smoke test
  (test_ds_relscore_panel_dom.py), wired in _dispatch.py + index.html +
  champ_select.js, LIVE-verified this cycle (Caitlyn SR: 12 rows, Runaan's
  100.0 -> 62.1). Re-implementing would duplicate item 220, so NO source change.
  The one open clause = item 220's "LIVE VISUAL CAPTURE owed" (Game-PC :8892
  down; Claude_Preview cannot attach the self-signed :8888). DISCHARGED
  CI-durably (the C1/C2/C3 pattern): NEW tests/snapshot_panels/
  test_ds_relscore_view.py renders the real renderDsRelscore bar into the live
  #csv-ds-relscore mount (the champ_select fixtures do not lock my_champion, so
  it drives the panel directly with a synthetic locked champ + a stubbed
  /api/ds-relscore payload), asserts the .dsr-bar-fill widths track score_pct
  (row0=100%, non-increasing) + the pct labels, and screenshots the panel.
  Test-only. 2 new tests, ruff + ASCII clean, verifier CONFIRM + full suite
  5255/0. Full RC suite 5255 passed / 1 skip / 0 fail / 85 subtests (+2). No
  source change -> no asset-hash reload, no RC restart; ENGINE 1.120.0, no DS
  bounce. NEXT OPEN = D2 (draft tool L (the community fork) Elo log-odds draft aggregator).
- 2026-06-06 C3 DONE (item 332, commit aa0a5a7e + docs sync): Post Game Review
  (last-match) SR + ARAM + Arena 5-phase fixture audit + reproducible visual
  validation. AUDIT: 3 parallel read-only mode-lens subagents (SR #14 / ARAM #15
  / Arena #16) ran STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY against
  last_match.css (~1290) + last_match.js (~1347, incl inline px) + the
  last_match_<m> fixtures + index.html #view-last-match vs UI_SCALE_SPEC_V2.
  Typography already on v2.1 tokens (every font-size a --fs-* token except ~5
  sub-floor labels carrying inline documented operator-exception rationale); 0
  in-scope MUST-FIX. Sole-merger call: the ARAM/Arena agents flagged the U+00B7
  meta separator + a "Review ->" tab arrow as ASCII MUST-FIX, but these are
  PRE-EXISTING (U+00B7 is a convention across 11 panels; last_match.css carries
  ~972 comment-art non-ASCII bytes) and OUTSIDE the actively-enforced em/en-dash
  + smart-quote set (all 3 agents verified ZERO U+2013/2014/2018/2019/201C/201D),
  and CI does not gate them (the C2 suite was green with U+2500 present) ->
  deferred to the operator-gated repo-wide ASCII sweep (FUTURE), not churned
  piecemeal. VISUAL: NEW tests/snapshot_panels/test_last_match_view.py renders
  the full #view-last-match for all 3 modes via the headless mock-server +
  Playwright at 1920x1080 (drive /?ui_mock=1&mode=<m>#last-match -> _lmMockUrl ->
  renderLastMatch; wait on #lm-mode-tag != "-"). Asserts per mode: view mounts,
  hero champion + grade render, mode tag (Ranked Solo / ARAM / ARENA) matches,
  Arena neutral ARENA pill vs SR VICTORY, no JS errors; screenshots each. NEW
  web/data/ui_mock/last_match_sr.json (SR Ranked Solo fixture) + an sr branch in
  _lmMockUrl give PGR-SR the same CI coverage as ARAM/Arena. 6 new tests, ruff +
  node --check + ASCII clean, verifier CONFIRM 6/0 + full suite 5253/0. Full RC
  suite 5253 passed / 1 skip / 0 fail / 85 subtests (+6). web/js asset-hash
  reload (ADR-008), no RC restart; no engine touch -> ENGINE 1.120.0, no DS
  bounce, no Share sync.
- FUTURE (C3 audit SHOULD/NICE + deferred ASCII debt): (1) repo-wide
  operator-gated ASCII sweep of last_match.css/js (~972 + 213 pre-existing
  non-ASCII: box-drawing/arrow comment art + the U+00B7 meta separator shared by
  11 panels - main.js/right_now.js/next.js/team_context.js/...). (2)
  .lm-hero-champ (champion-name role=button deep-link) lacks min-height --hit-min
  42px (~41px today); add min-height + inline-flex centering (shared hero element
  -> lands on all 3 PGR modes). (3) Arena _setHero hard-codes the "ARENA" result
  pill + ignores enriched.subteam_placement - surface the real placement (e.g.
  "2nd / 6"). (4) Arena _setTeamComp groups all 5 non-operator subteams into one
  ENEMY block - a subteam-grouped roster reads truer.
- 2026-06-06 C2 DONE (item 331, commit e81495e0 + docs sync): Active Match
  SR + ARAM + Arena 5-phase fixture audit + reproducible visual validation.
  AUDIT: 3 parallel read-only mode-lens subagents (SR #11 / ARAM #12 /
  Arena #13) each ran STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY
  against active_match.css + active_match.js (incl. its inline-style px) +
  the active_match_<m> fixtures + index.html #view-active-match vs
  UI_SCALE_SPEC_V2. SPLIT verdict: SR NEEDS-FIX (3 MUST-FIX); ARAM + Arena
  SHIP-READY. Sole-merger resolution: the SR auditor was right - the
  active_match.js inline styles carry NO inline rationale (unlike the
  cd_ledger.css precedent) and the CALL pane is the dominant in-game
  content. FIXED in-slice: (a) active_match.css 2 non-ASCII U+00D7 (x)
  signs in comments -> ASCII; (b) active_match.js 3 sub-floor inline
  font-size px on readable DOM text -> v2.1 tokens (_line value 13 ->
  --fs-md, _line label 10 -> --fs-xs, _dsIcon delta 11 -> --fs-xs).
  VISUAL: NEW tests/snapshot_panels/test_active_match_view.py renders the
  full #view-active-match for all 3 modes through the headless mock-server
  + Playwright harness at 1920x1080 (drive /?ui_mock=1&mode=<m>#active-match
  -> _amMockLoad -> renderActiveMatch; wait on #am-sub "phase InProgress").
  Asserts per mode: view mounts, CALL pane live coach line renders, map
  mounts with alt "<mode> map", draft-elo chip enabled SR/ARAM + hidden
  Arena (the 5v5 gate), no JS errors; screenshots each. 7 new tests, ruff
  + node --check + ASCII clean, verifier CONFIRM 7/0 + full suite 5247/0.
  Full RC suite 5247 passed / 1 skip / 0 fail / 85 subtests (+7). web/css|js
  asset-hash reload (ADR-008), no RC restart; no engine touch -> ENGINE
  1.120.0, no DS bounce, no Share sync. Also relocated the shipped cdragon
  ROADMAP item 1 -> docs/ROADMAP_HISTORY.md to bring ROADMAP.md back under
  its 80KB doc-size budget (was 81993 > 81920; pre-existing red latent
  since the C1 docs-only commit).
- FUTURE (C2 audit SHOULD/NICE, deferred - do NOT auto-flip): the density-
  constrained sub-floor micro-labels NOT bumped (kept at px): active_match.js
  map status 11px + gank band 12px (absolutely-positioned HUD overlays on
  the map image), _dsIcon/_defIcon OWNED 9px stamps + _defIcon caption 10px
  + _dsIconFallback 9px tile (inside 44-62px icon cells where >=16px
  overflows), MIA canvas badge 10px (canvas-rasterized, CSS tokens cannot
  apply). Document each with an inline operator-exception rationale
  (cd_ledger.css precedent) or bump on a future dense-overlay pass. Off-grid
  spacing (am-grid gap 14, pane padding 10/14) is pre-existing, deferred.
- 2026-06-06 C1 DONE (item 330, commit b4bfa05a): Champ-Select ARAM + Arena
  5-phase fixture audit + reproducible visual validation. AUDIT: 2 parallel
  read-only subagents (ARAM + Arena), each ran STRUCTURE/TYPOGRAPHY/HIT-TARGETS/
  ASCII/HIERARCHY against champ_select_view.css (mode blocks ~1659-1995 ARAM /
  ~2482-2804 Arena + shared base) + champ_select.js + the ui_mock fixtures vs
  docs/UI_SCALE_SPEC_V2.md. BOTH returned SHIP-READY, 0 MUST-FIX - the CSS was
  already swept onto v2.1 tokens by prior rounds (s164/s212/s214/s234/s239,
  items 178/181/202); the sub-floor px that remain (.csv-bench-empty 13,
  .csv-duo-cell-tag 11, .csv-arena-cell-name 13, .csv-pr-chip 14) all carry the
  inline "documented operator exception" rationale the spec permits. VISUAL: the
  C-phase Claude_Preview check A1/A2/A2b kept OWING is now discharged in a
  CI-durable form - NEW tests/snapshot_panels/test_champ_select_view.py renders
  the full-page #view-champ-select for both modes through the existing headless
  mock-server + Playwright harness at the 1920x1080 design baseline (drive path
  /?ui_mock=1&mode=<m>#champ-select -> _csMockLoad fetches
  /data/ui_mock/champ_select_<m>.json -> data-cs-mode stamp). Asserts per mode:
  view mounts, mode-specific structure renders (ARAM 10-cell bench / Arena duo
  row + augment slots), SR-only Pick & Ban hidden, no JS errors; screenshots the
  view. Operator-eyeballed both captures: ARAM (Jinx HOVERING + LOCK IN + COMP
  VERDICT swap->Ashe w/ green bench swap-ring + summspell D/F strip + enemies)
  and Arena (duo me+Lulu+waiting / Silver-Gold-Prismatic augment slots / 5
  stacked enemy sub-teams) both read clean at baseline, no horizontal scroll.
  5 new tests, ruff + py_compile + ASCII clean, verifier subagent CONFIRM 5/0.
  Full RC suite 5240 passed / 1 skip / 0 fail / 85 subtests (+5). No web/ source
  delta (audit found nothing to fix) -> no asset-hash reload, no RC restart; no
  engine touch -> ENGINE 1.120.0, no DS restart, no Share sync.
- FUTURE (C1 audit SHOULD/NICE, deferred - operator-tuned, do NOT auto-flip):
  (1) champ_select_view.css:264 .csv-lock-btn min-height 32px < --hit-min 42px -
  carries an explicit operator prominence-reduction rationale ("round 3"), so a
  bump would re-litigate that decision; formalize the comment or bump only on
  operator OK. (2) .csv-bench-cell has no min-width floor (bench cells clear 42px
  at the 1920 baseline but could dip below it on a narrower-than-baseline window;
  spec targets 1920 only). (3) Arena enemy .csv-arena-cell 3rd cell is a
  forward-flex scaffold (live Arena is 2/team) rendering one empty dashed cell
  per team; drop to a 2-col row only if the 3-cell scaffold is confirmed dead.
- 2026-06-06 B1 DONE (item 329; commits b8e7647a slice / 21f6aaf9 merge /
  48411bfc fix). STALE-PREMISE: the B1 row's "zero live-coach consumer" was
  wrong - all 3 generators were ALREADY wired live into /api/state by commit
  679c8928 (Haiku-elim W3A): dashboard/_deterministic_coaching.py
  (compute_deterministic + resolve_choices, TTL-cached, fail-soft) +
  _state_builder.py:312-347 ship coach.choices / state.callouts /
  state.lead_projection, and the panels (callouts.js #rn-lead + #rn-callouts,
  coach_choices.js #rn-choices) already render them. Verified live: /api/state
  carried callouts + lead_projection + 3 choices; 153 generator/wire/panel
  tests green. The one UNSHIPPED B1 clause was "shadow-log validation first":
  resolve_choices BLIND-FLIPS native -> deterministic choices live (sec-4b
  do-not-flip-blind) and the DISCARDED native choices were unrecorded, so the
  flip could not be validated. Shipped NEW core/det_coach_shadow.py (fail-soft
  jsonl, per-path dedup, mirrors A3 core/ds_coach_shadow) +
  dashboard._deterministic_coaching.shadow_log_det that records det
  choices/callouts/lead AND the discarded native choices side-by-side to
  data/det_coach_shadow.jsonl (gitignored), zero live-output change. 1 worktree
  slice (verifier CONFIRM 41/0) + 1 LIVE-CAUGHT fix: the first cut logged native
  AFTER resolve_choices overwrote coach["choices"] (native == det garbage, found
  via the live jsonl - NOT the worktree gate); reordered shadow_log_det before
  the overwrite + added a native!=det regression test. Full RC suite 5235 passed
  / 1 skip / 0 fail (+8). No web/ delta (panels pre-wired) -> no UI-audit. No
  engine touch -> ENGINE 1.120.0, no DS restart, no Share sync; RC restarted
  (route reload) pid 27300. NEXT: the jsonl now accrues det-vs-native validation
  data - a future cycle can analyze it to confirm/tune the live flip before
  declaring the laning-Haiku surface validated.
- 2026-06-06 A3 DONE (item 328, commit 52f76059): DS-coach SHADOW-LOG substrate
  shipped (NOT yet surfaced). 3 disjoint verifier-CONFIRMED worktree slices
  (verifier 13/0 + 17/0 + 6/0) + 1 base-coach integration: NEW pure generators
  core/ds_antitank_hint.build_antitank_hint (anti-tank build hint vs high-HP
  enemy comps over compute_antitank + core.archetype_picks tank/bruiser count)
  and core/ds_scaling_hint.build_scaling_hint (early/mid/late power-curve +
  outscale/falloff/even verdict over compute_scaling), a fail-soft jsonl writer
  core/ds_coach_shadow.log_coach_hints (DI-testable, lazy import, never raises),
  and a fire-and-forget hook BaseCoach._shadow_log_hints in _maybe_coach that
  canonicalizes champ name-forms and records both hints to
  data/ds_coach_hints_shadow.jsonl (gitignored) alongside live coaching WITHOUT
  touching the Haiku prompt / UI / coach output. Full RC suite 5227 passed / 1
  skip / 0 fail (+41); ruff + py_compile clean; ASCII-only. NO engine file
  touched -> ENGINE stays 1.120.0, no DS restart, no Share sync. SURFACING into
  coach context is the deliberate FUTURE step (gated on shadow-log accrual +
  validation; section-4b do-not-flip-blind, the champ-select Haiku-elim pattern).
  Calibration note: slice 1 set ANTITANK_STRONG=0.8 (Vayne 0.95 / Fiora 0.90
  clear lean-in; flat-damage mages at 0.0 -> recommend items) since no champ
  reaches the spec's 1.2 on a single mechanism.
- 2026-06-06 cycle-5 REGRESS on A2b = FALSE POSITIVE (3rd consecutive; cycles
  3/4/5 each flagged the same non-bug). This-run ground truth: `git grep` for the
  corruption marker across every tracked code file (*.css *.js *.py) returns ZERO
  matches; web/css/dashboard.css line 42 and tests/snapshot_panels/
  test_ds_matchup_panel.py line 47 both hold the correct CSS import directive;
  docs/ORCHESTRATION_PLAN.md lines below read correctly. Tests this run: 13
  implicated (parity guard + ds_matchup snapshot) passed; FULL RC suite 5186
  passed / 1 skip / 0 fail / 85 subtests. ROOT CAUSE of the loop: the auditor
  re-detects the bug-DESCRIPTION quoted verbatim inside the loop's own control
  files (ops/loop/control/directive.md + _gemini_in.txt) and the prior FP
  entries - it is documentation OF a non-bug, never source corruption. NO source
  change made (none warranted). A2b stays DONE. Escalated to the DIRECTOR via
  gemini_ask.txt: advance to A3, stop re-issuing this verdict.
- 2026-06-06 REGRESS verdict on A2b = FALSE POSITIVE (verify-only cycle, no
  source fix; ground truth HEAD 8188baf3). The auditor flagged a botched
  find/replace that would have turned the leading @import token into a stray
  test_dashboard_css_panel_imports_parity.py filename fragment in
  tests/snapshot_panels/test_ds_matchup_panel.py + docs/LEDGER.md +
  WAKEUP_NOTES.md. GROUND TRUTH: that string exists ONLY in the loop's own
  control files (ops/loop/control/directive.md + _gemini_in.txt, which quote the
  bug verbatim) and in untracked _verify_*.txt scratch logs - NEVER in source.
  test_ds_matchup_panel.py line 47 + web/css/dashboard.css line 42 both carry the
  correct @import './panels/ds_matchup.css'; the LEDGER / WAKEUP _imports_parity
  hits are legit prose references to the real bundle-parity guard test, not
  corruption. Verified live: snapshot_panels + the parity guard 92 passed; FULL
  RC suite 5186 passed / 1 skip / 0 fail; git diff empty (working tree == HEAD).
  A2b stands DONE. Director: advance to A3 - there is no regression to fix.
- 2026-06-06 A2b DONE (commit 0a017dc4): NEW GET /api/ds-matchup +
  champ-select ds_matchup card. Surfaces the EXISTING compute_matchup engine
  via the existing /v2/matchup client wire (core/daemon_slayer_client.matchup);
  thin read-only dashboard route (dashboard/routes_ds_matchup.py mirrors
  routes_ds_profile: 5-min TTL cache, numeric->slug resolver, fail-soft
  503/400/no_matchup) + a presentational card (web/js/panels/ds_matchup.js +
  ds_matchup.css) keyed champ_a=cs.my_champion vs champ_b=first committed enemy.
  Payload adds swing_pct (0-100, 50=even) + favored (A/B/even) over the raw
  MatchupResult. Shipped as 2 disjoint verifier-CONFIRMED worktree slices
  (backend 21/0, frontend 8/0) + 1 UI-audit fix. Full RC suite 5185 passed / 0
  fail; ruff + node --check clean. Live route probed green (Vayne vs Caitlyn:
  back_off, favored B, net_swing -0.148; L6 -0.303; numeric 67/51 resolves;
  missing param 400). 5-phase UI audit: 1 MUST-FIX FIXED (scheduler wiring was
  dead - card rendered one tick late vs siblings; + regression test), 1
  SHOULD-FIX FIXED (header overflow guard). VISUAL CAPTURE OWED (carry-forward):
  Game-PC :8892 MCP down (SessionStart re-confirmed /health None) +
  Claude_Preview cannot attach self-signed HTTPS :8888 (same A1/A2 blocker).
- FUTURE (A2b UI audit SHOULD/NICE, deferred): (1) ds_matchup.js _signature
  omits a_can_full_combo / b_can_full_combo / notes - a payload changing ONLY a
  combo flag or note text skips the sig-dedup rebuild (stale notes; low odds).
  (2) NICE: .dsm-swing-end labels lack white-space:nowrap (could wrap at extreme
  narrow width). (3) NICE: _notesHtml renders the .dsm-cast "full combo" tag
  immediately before "...lands full combo" (doubled phrase; cosmetic).

- 2026-06-06 A2 DONE (commit 3f23e18c): /api/ds-profile + the panel grew 4 -> 8
  axes (added threatrange/zonecontrol/objdamage/extendedduel from the existing
  pure scorers; headlines threatrange_score/zonecontrol_score/objdamage_score/
  duel_score; per-axis bool flag + dsp-flag marker: is_artillery->artillery,
  controls_terrain->terrain, pressures_structures->towers, ramps->ramps). Shipped
  as 2 disjoint verified worktree slices (route + panel), each independently
  re-run before merge. 5-phase UI audit SHIP-READY (0 MUST-FIX, 0 SHOULD-FIX).
  RC suite 5156 passed / 0 fail; DS suite 6705 passed / 0 fail; ruff clean. Live
  route probed green (Vayne: objdamage HIGH pressures_structures, extendedduel
  ramp, threatrange medium, zonecontrol sparse 0). VISUAL CAPTURE OWED
  (carry-forward): Game-PC :8892 MCP down + Claude_Preview cannot attach the
  self-signed HTTPS :8888 (same A1 blocker).
- 2026-06-06 A2b SPLIT: matchup was NOT made a profile axis. compute_matchup is
  a pairwise 1v1 (needs champ_a + champ_b + per-side level + items + a
  DataSnapshot) and already has its own surface (/v2/matchup); a single fixed
  "axis" value for the locked champ would be arbitrary/misleading. Logged as new
  OPEN session A2b - a dedicated matchup card keyed on a selected enemy.
- FUTURE (NICE, from A2 5-phase audit): ds_profile.css .dsp-label has no
  white-space:nowrap guard (9-char "OBJECTIVE" fits 5.5em today, parity with
  "WAVECLEAR"); .dsp-detail flex has no min-width:0 / flex-wrap (overlaps the A1
  .dsp-detail overflow NICE); 8 stacked rows is a denser card than 4 - revisit
  only if the live Suggestions stack reads tall. All cosmetic; deferred.
- 2026-06-06 A1 DONE: GET /api/ds-profile + champ-select DS-Profile panel (4 axes
  mobility/sustain/scaling/waveclear) shipped as 2 disjoint verified slices.
  5-phase UI audit PASS (0 MUST-FIX, 0 SHOULD-FIX). Live route probed green; full
  RC suite 5153 passed. VISUAL CAPTURE OWED (carry-forward): Claude_Preview cannot
  attach to the HTTPS self-signed live :8888, and Game-PC :8892 MCP is down
  (project_gamepc_mcp_boot_gap). Capture the locked-champ Suggestions card next
  time a visual path is available.
- FUTURE (NICE): web/css/panels/ds_profile.css .dsp-detail has no
  overflow/text-overflow/min-width:0 guard (clipped by ancestor overflow:hidden
  today - cosmetic only).
- A2 NEXT: add threat-range / zone-control / objective-damage / extended-duel /
  matchup axes to the same /api/ds-profile surface (engine fns already exist:
  threatrange.py / zonecontrol.py / objdamage.py / extendedduel.py).
