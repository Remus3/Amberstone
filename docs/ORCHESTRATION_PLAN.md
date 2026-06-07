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
| C3 | ui-audit | Post Game Review SR + ARAM + Arena: 5-phase audit + visual validation. | OPEN | - |
| D1 | lift | DS relative-score bar (Aggregator P lift, BACKLOG.md:21): per-row score_pct fill (delta_dps/top_delta*100). Codeable with fixtures; render-gated on locked champ. | OPEN | - |
| D2 | lift | draft tool L (the community fork) Elo log-odds draft aggregator (BACKLOG.md:78): clean algorithm reimplement (NO vendor) over pairwise WR from rewind_history.db. | OPEN | - |
| E1 | research | Per-role grading rubric calibration (BACKLOG.md:100): tune core/post_game_rubric.py weight vectors from public per-role reference data. | OPEN | - |
| E2 | research | LCU data.json diff vs the reference catalog (BACKLOG.md:19) for richer endpoints. Log findings only; no live capture. | OPEN | - |
| E3 | research | Competitor-tool lift secondary sweep, framed by technical substance only (keep third-party names out of repo). Output new NOW/FUTURE/CLOSED candidates into the Findings log. | OPEN | - |
| F1 | monitoring | Phone monitoring loop-status panel reading ops/loop/control/{cycle.txt,controller.log,claude.done} + last commit (Tailscale-viewable) + daily upstream content-drift poll (tools/upstream_drift_check.py + scheduled task). | OPEN | - |

## EXCLUDED (live-game / operator-gated; the director MUST NOT pick these)

- DS Phase-D default-ON flag flips (apply_passive_damage, non-every-AA on_hit, per-stack assumed_stacks) - need real-game re-ranking validation.
- Live caster-stat producer for /anti-tank P3.2 activation + live survivability scorer (egg-resist / Orianna E) - need a live AbilitiesSnapshot / game.
- Champ-select brief Haiku -> deterministic flip - needs live shadow-log accrual + operator OK.
- Game-PC :8892 visual screenshot captures (MCP down post-1PC). C-phase visual validation uses the Claude_Preview MCP against :8888 instead.
- Anything in the CLAUDE.md "Settled - do not re-litigate" set.

## Findings log (executor appends; newest first)

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
