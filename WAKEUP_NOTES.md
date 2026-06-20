# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-20 (RC 2.0 /RC2-Continue - Phase 3.3 overlay shadow-wire + hit-target)

P3.3 (typography/hit-targets/hierarchy + pulse-rationing wire), headless-safe slice. Commit
`87f41baf`. Tier-1 JS-logic + overlay CSS. NO ENGINE / 0 frozen / no DS / no Share. Stage = LIVE
(code done; pulse flip operator-eyeball-owed). Banner 27 -> 28 / 62 = ~45%.

- overlay_priority.js: NEW `signalFromState(p, band)` - the one pure coach-envelope -> selectPrimary
  signal map (band passthrough, choices detect, Phase-4 crossing-edge predicates
  spike_crossed/objective_steal_now/lethal_incoming default-false + honored-if-set). Dual ESM/CJS.
- right_now.js: SHADOW consumer - each render stamps data-s0-cue/-tier/-pulse on #right-now via
  signalFromState->selectPrimary->shouldPulse, try-guarded, ZERO live pulse change. Eyeball-able at ?overlay=1.
- overlay.css: section-7 floor - #rn-choices .rc-chip min-height 44px (overlay-scoped; dashboard keeps 42).
- TDD: +8 signalFromState node tests (RED 8f/21p -> GREEN 29/29) + 1 overlay snapshot hit-target (test_overlay_view 13/13).
- OWED LIVE FLIP (NOT headless): re-point .action per-band pulse (right_now.js:490-500) + overlay_pulse.js
  MutationObserver to consume data-s0-pulse (fire only Emergency + one-shot-Urgent cross). SHARED
  dashboard+overlay behavior -> docs/LIVE_GAME_GATED_SYNC.md; eyeball a real game first. Hextech literal
  swap = E11 (overlay uses --signal-* tokens, inherits the global cutover).

NEXT via /RC2-Continue: P3.4 dashboard-stays-when-overlay-active (E1 keepCompanion shipped; verify +
any residual), 3.5 settings-without-hotkeys, 3.6 dashboard condensation. Then Phase 4 (Electron
sizing/DPI), Phase 5 coaching, E10/E11/E12/E7/E2. Memory: project_rc2_build.

---

# 2026-06-20 (RC 2.0 /RC2-Continue - Phase 3.1 + 3.2 overlay condensation)

Resumed the RC 2.0 program (P3/P4 unblocked by the Hextech greenlight). Accidental computer
restart mid-session between 3.1 and 3.2 - git was clean, P3.1 already pushed, recovered cleanly.

- P3.1 (75a2c10b): docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md - the in-match glance-test spec.
  3-tier model (Ambient/Urgent/Emergency) on classifyAction bands, S0 single-winner arbitration
  ladder (lethal 100 -> none 0), motion rationing, Hextech color bins, 3.2/3.3 handoff. Tier-0 doc.
- P3.2 (39303acb + db6f77d4): web/js/lib/overlay_priority.js (selectPrimary + shouldPulse, dual
  ESM/CJS, 21/21 node TDD - the test was pre-authored+untracked from a prior cycle) + overlay
  callout 2-row density clamp (CSS #rn-callouts nth-child(n+3) + snapshot). Tier-1, no ENGINE/DS/frozen.
- NOT wired (DELIBERATE, do NOT flip headlessly): the pulse-rationing consumer re-point
  (right_now.js .action pulse :490-500 + overlay_pulse.js -> shouldPulse) is a SHARED dashboard+overlay
  BEHAVIOR change -> carried to 3.3; needs shadow + 5-phase UI audit + operator eyeball on the live headline.
- Banner 27/62 = ~44%. Task pane: 9 phase chips (P1/P2 completed, P3 in_progress).

NEXT via /RC2-Continue: P3.3 (typography/hit-targets/hierarchy + Hextech bins + the pulse wiring above),
then 3.4 dashboard-stays-when-overlay-active, 3.5 settings-without-hotkeys, 3.6 dashboard condensation.
Then Phase 4 (Electron sizing/DPI), Phase 5 coaching, E10/E11/E12/E7/E2. Memory: project_rc2_build.

---

# 2026-06-20 (RC 2.0 program kickoff - operator overnight directive)

RC 2.0 = overlay/UX + coaching + responsiveness + hygiene program. Plan + live % in docs/RC2_PLAN.md
(9 phases / 62 stages). Resume with the /RC2-Continue command. 11 commits, pushed, CI green. NO DS/ENGINE.

- Phase 1 research (9 surfaces + LCU IO timing-map) + design HTML (3 themes) -> operator GREENLIT Hextech.
  Deliverables: docs/research/RC2_RESEARCH_*.md, docs/design/RC2_DESIGN.html, docs/DS_COMPLETENESS_GAP.md
  (DS ~90-93%), docs/RC2_TODO_QA.md (97 items + TOP-10), docs/research/RC2_COACHING_SPEC.md.
- Shipped E-batch: E6 SPELL FLIP-BACK FIX (ab54c64a - _sync_spells re-pushed the default every 1s poll; now
  push-once + respect/remember manual per champ+mode + /api/champ-select/spell-winrates); E3 win-capture
  (ad4c9906 - history/home W/L + 51.6% season WR from tracked_win, was on disk unused); E5 laning hold-band
  (4da01fbe, shadow); E8 design-system reduced-motion/glyphs/statusFor (19f8116f); E9 rank header+scouting
  (978490e3, Riot key=API-Key-Riot.txt); E4 counter-picks+ban-collapse (fd95801c); E1 dashboard-persist+pinned
  +panel-toggles (a61703ef); P6.2 poll 2->1s (1011f47d).
- RC RESTARTED pid 19356 -> E3/E5/E6/E9 + P6.2 LIVE. rc-shell disappear-fix + pinned need an Electron RELAUNCH (owed).
- Operator: League borderless @ 2560x1440; per-panel in/out-game toggles; ASCII retro approved ALL files +
  frozen + git HISTORY rewrite (E10 NOT done yet).

NEXT via /RC2-Continue: E10 ASCII+history-rewrite (alone, force-push), E11 Hextech reskin, E12 responsiveness
levers (SSE/build TTL), E7 bench+LCU-pooling (frozen lcu_client), E2 DS 3-game live-flip. Verify spell-fix LIVE
next champ-select. Stage 25/62 = 40%. Memory: project_rc2_build.

---

# 2026-06-19 (live ARAM session) - 2 live bug fixes + supervisor 72h-ETL fleet fix (LEDGER 519-521)

Live ARAM Mayhem play, operator-directed mid-game fixes + continuous overlay/dashboard monitoring.
3 commits, pushed, CI green. NO DS/ENGINE touch (no Share sync).

- BUILD-CHIP owned-aware (d90badb5, L519): _next_item_str indexed order[owned_count], blind to WHICH
  items owned -> recommended items already held on a deviation (live: Wooglet's over a burn line vs an
  87-MR comp). Threaded owned_ids through build_choices->_variant_outcome->_next_item_str; returns
  first UN-owned; legacy count-index when owned_ids absent. Caller passes gs[my_item_ids]. 4 TDD tests.
- PGR AUTO-SHOW (68b6cc54, L520): view router dropped to home post-game; PGR only refetched if already
  on last-match, but mid-game you are on active-match -> never surfaced. main.js game-end edge now sets
  last-match as the MANUAL view (one-shot, not an auto-derive change -> no view-fight; next CS clears
  it). asset-hashed -> browser auto-reload, no restart. Python view-router mirror unchanged.
- SUPERVISOR 72h-ETL (d53ae8bb + live tasks, L521): found dead (State=Ready) ~21:18; NO
  <ExecutionTimeLimit> -> Windows default PT72H; boot 6/16 21:16 + 72h = 6/19 21:17 hard-kill,
  RestartCount=0 -> app unsupervised ~1h. Not a crash (Operational log disabled). Same default killed
  RC-BridgeWatcher (revived) + threatened DaemonSlayer. Live fix: ETL=PT0S on all 3 + RestartOnFailure
  on the 2 logon daemons; frozen rc_supervisor.py + RC-BridgeWatcher.xml NOT edited. Documented
  RC-Supervisor.xml.

GATED eyeballed (report for loop to flip): DSP3 resolver proven (6 Cluster-A ON->override primary,
source=aram_win; all default-OFF, flip-point=ARAM archetype-resolve); Lux DSP8(tank)->mag-pen +
DSV3(squishy)->Shadowflame SANE; build-chooser ARAM push verified (Wooglet's=OFF-rank #1).
NEXT: verify build-chip + PGR auto-show LIVE next game (fixes deploy on next game-end). RECO: enable
TaskScheduler Operational log; operator-approve persisting ETL into frozen RC-BridgeWatcher.xml.
[[reference_two_supervisors]] [[project_rc_supervisor_restart]]

---

# 2026-06-19 (gemini-loop R7-regress-fix cycle) - passive_as unit-mismatch fix (LEDGER 518)

Gemini AUDITOR flagged R7 (item 517) REGRESS. `agents/daemon_slayer/dps.py` per-stack self-AS
seam added `passive_as_bonus()`'s bonus-AS FRACTION (Irelia full L18 = 1.0; Jax L11 ~0.75)
directly to `stats_for_rotation["as"]` = FINAL attacks/sec (engine.py:195 `base_as*(1+bonus)`,
2.5-capped) -> over-credited AS by 1/base_as (~1.5x). Commit `ee90195d`; Tier-2, NO ENGINE bump
(stays 1.147.0), 0 frozen, Share re-synced same commit.

- FIX: fold the fraction onto the champ INNATE base AS - `+ innate_base_as * passive_as`
  (`champ["stats"]["attackspeed"]`, champ = snapshot.champion(...) dps.py:695 in scope); 2.5
  re-clamp kept; seam note reworded to "+X% bonus AS ... folded onto base AS".
- TDD RED-first: NEW `SeamAddsBaseAsScaledFraction` pins by colinearity (weighted_dps affine in
  rotation AS; off / pure-AS-Dagger(1042)-cal / on colinear; ON gain == c1*(base_as*pa) NOT
  c1*pa). RED 135.24 vs predicted_correct 118.75 -> GREEN (20/20). R7's 19 tests only asserted
  direction (on>off), true under both formulas -> missed the magnitude bug.
- NO bump: seam DEFAULT-OFF + operator-gated (not live), buggy math never hit a live consumer.
  SIBLING (FUTURE, not touched): Yun Tal cond_as (0.08, dps.py:849, batch 54) is the same unit
  class, pre-existing+tiny+separately pinned -> logged ORCH Findings.
- VERIFY: R7 20; DS-dir 7414 / 1 skip / 1942 subs; RC 8644 / 2 skip / 110 subs (lone fail = the
  expected Share-drift guard -> ds_share_sync re-mirror GREEN, --check in sync, 366 files);
  verifier CONFIRM all 6 claims (determinism teardown ERROR = live vision daemon mutating
  data/vision_state.json mid-run, environmental); ruff+py_compile clean; Share staged same commit.
- [[feedback_verify_before_declare_broken]] / [[reference_share_mirror_tools_drift]] /
  [[reference_ds_bump_run_tests_dir]] / [[feedback_ds_commit_share_test_mirror]].
