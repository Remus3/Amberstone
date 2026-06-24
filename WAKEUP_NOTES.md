# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-23 (R30 - SLOW per-page UI/UX design review, pages 1-2 of 9: HOME + LOBBY)

Interactive operator session (NOT the headless loop). The R29 NEXT directive: a slow, deliberate
per-page design review of EACH dashboard view - validate WHY each panel is there, decide
remove/add/alter (genuine design judgement, not token compliance). 2 pages shipped, 2 commits pushed,
gate green (228 snapshot + 14 new tests; ruff clean; 5-phase UI audit CLEAN each page). Tier-1 frontend
+ 2 dashboard builder fixes; no engine/DS/Share/ENGINE_VERSION.

CADENCE (proven, reuse pages 3-9): recon each view at 923+1920 via live-:8888 Playwright
(`ops/runtime/ui_recon/recon.py <view>`) -> READ the screenshots + ground-truth file:line -> PRESENT
keep/remove/add/alter + one framed scope AskUserQuestion -> build the picked slice (RED-first TDD,
5-phase UI-audit subagent gate before commit, commit+push). Gemini director interviewed ONCE for per-view
design intent (`ops/runtime/ui_recon/gemini_out.txt` - PART B one-liners drive the rest).

HOME (`a946f9bb`, full slice 1-7): idle "Ready when you are" greeting -> last-5 W/L momentum verdict
(`_homeMomentumVerdict`); primary Find Match CTA added (was the missing "next action"); duplicate
play-streak + "Advisories: None" noise killed; small-sample (1-2 game) Good/Bad suppressed
(`builders_home._home_pick_tips`); 3 stat chips unified to ONE 14d timeframe (was today 0/0/0 next to 14d
CS/GOLD; degenerate K/A-recording-gap days skipped so no false 0.0). `test_home_review_r30.py` (8) + tips
small-sample. HARNESS LESSON: home double-fetches at boot (ui_mock + `/api/home/summary` which the conftest
mock_server answers `{}`); route BOTH paths in tests or pass 2 clobbers injected state to empty.

LOBBY (`b7500807`, polish+wire): YOUR MAINS "AVG/Match" grid was all dashes via a KEY MISMATCH (builder
emitted `cs_pm/vision_pm/dmg_pm`; frontend `_mcAveragedHtml` reads `kp/cs/vision/dmg/cs_per_min/avg5`).
`routes_lobby_aux._query_mains_for_puuid` now emits the consumed keys from rewind participants: cs/vision/dmg
per-game, KP% via a team-kill self-join (`_kp_by_champ`), AVG5 last-5 KDA grade (`_avg5_grade`). Live-verified
`/api/mains` (Vayne KP 51% / CS 87 / dmg 35.4K / AVG5 C). + "CHAMPIONMASTERY" header jam fixed (emptied the
"Champion" label that overflowed its 76px icon track) + MY TOP 8 radii/gaps -> tokens. Hermetic
`test_lobby_mains_averaged.py` (6, temp DB - not the gitignored rewind DB). Dense `.lv-top8-*` 14px LEFT
(overflows at 16); the named deferred `.lv-fr-*` is DEAD/preserved code (`_renderFriendsRecent` uncalled).

NEXT (operator: CONTINUE the review next session, pages 3-9, after /done + /clear): Post Game Review
(last-match, `last_match.css` - PGR card-radius `--radius-sm`->`--panel-radius` deferred), Session, History,
User Builds, Build Insights, Settings, Replay, + in-game champ-select / active-match / overlay (live-gated).
Respect: operator-locked `last_match.css` sub-floors (`:160/862/1138/1244`); replay scroll-wrap is correct
(do NOT "fix"). Reuse the harness + `gemini_out.txt` at `ops/runtime/ui_recon/`. The full resume prompt was
handed to the operator in chat.

---

# 2026-06-23 (R29 cc-chips + USER-DRIVEN companion-fit / hexcore legibility / default window size)

R29 Gemini-director cycle, then an interactive operator session. 4 commits, all pushed, gate green
(227 tests: hygiene + full snapshot suite; ruff clean).
1. cc-threat-chips grid sweep (1b159617) - the R29 director-picked unit (cc_blended_ehp_threat +
   cc_conditional_pressure, adjacent mirrored champ-select chips): off-grid spacing/radii ->
   --space-* / --panel-radius-sm; RED-first tests/snapshot_panels/test_cc_threat_chips_view.py.
2. Companion-fit reflow, ALL out-of-game views (a731c8ce home; 31f4a327 settings/lobby/user-builds/PGR).
   The rc-shell out-of-game companion loads the full 1920-authored :8888 dashboard in a ~923px window;
   the wide grids overflowed/clipped. @media (max-width:1200px) single-columns .home-body / .home-hero /
   .home-coach-pick-body, .settings-body, .lobby-view-grid, .ub-layout, .lm-row-half / .lm-hero. KEY
   LESSON: a flex child with an EXPLICIT min-height flex-collapses under a tall flex-column parent and
   spills onto the next card -> set min-height:auto at the companion width (home-hero + lm-hero). replay
   already scroll-wraps its grid (verified contained, not clipped). 1920 desktop UNTOUCHED.
   test_home_companion_view.py (3) + test_companion_reflow.py (9).
3. Hexcore legibility pass (31f4a327, guided by a parallel review subagent): lobby .lv-mc-avg-lbl/-val +
   .lv-top8-cell sub-floor bumps (12/14px -> --fs-xs/--fs-sm), + --text-faint (~3:1) -> --text-dim (~5.5:1)
   contrast lifts on settings spend-gate, home hero-sub/pick-tip, build-insights numeric columns, PGR
   rank-cell. operator-locked last_match.css sub-floor exceptions (:160/862/1138/1244) LEFT UNTOUCHED.
4. Default companion window size -> 923x1316 (7117ff19): rc-shell/src/config.js standard preset
   (DEFAULT_PRESET that resolveConfig falls back to) 520x900 -> 923x1316; tall -> 1100x1560 (monotonic
   Compact/Standard/Tall ladder); compact unchanged. 29 config.test.js green; resolveConfig({},{}) = 923x1316.

NEXT (OPERATOR DIRECTIVE, NEXT SESSION after /clear): a SLOW, deliberate per-page UI/UX design review -
go through EACH dashboard view one at a time, validate WHY each piece/panel is there, decide what to
REMOVE / ADD / ALTER (not just token compliance - genuine design judgement). Recon technique = render
each view at 923 + 1920 via live :8888 Playwright (mode=client out of game). Carry the deferred legibility
P2/P3: lobby .lv-fr-* fonts (11/12px), PGR card radius --radius-sm->--panel-radius, a raw-radii / off-grid-gap
token sweep across the lobby/replay/PGR blocks that missed the v2.1 pass. The FULL next-session prompt was
handed to the operator in chat.

Don't-redo: home/settings/lobby/user-builds/PGR companion-fit SHIPPED (a731c8ce/31f4a327); default window
size SHIPPED (7117ff19); cc-chips grid-swept (1b159617); replay scroll-wrap verified fine (do NOT "fix" it).

---

# 2026-06-23 (R28 DIRECTOR REFILL) - un-audited UI surface 5-phase audit: spike_markers grid sweep

Re-probed: mode=client, NO live game (LCU EndOfGame, /api/state liveclient EMPTY, League in lobby) - so
the 2 OWED live-gated items (E.1 physical knob; RC_COMP_HP_LEAN flip) were UN-buildable this cycle.
Interviewed the gemini director (gemini-3-pro-preview, loop_controller.gemini(); scratch script deleted);
fed live state + the candidate menu, it picked (b) un-audited UI 5-phase audit over the heavily-mined (a)
competitor-lift lane (7 prior COMPETITOR_LIFT docs). It NAMED carry_share/ds_antitank panels - both
HALLUCINATED (do not exist); intent valid, specifics not (audit-proposals-are-intent).

GROUND TRUTH: --fs-2xs is fully swept from web/ (ds_statcheck was the last, R26); remaining UI debt =
hardcoded off-grid px. A Plan subagent surveyed un-audited + headless-RENDERABLE panels and picked
spike_markers (the Power Spikes strip, #am-spike-markers in the active-match BUILD pane): shipped
2026-05-30 alongside tokens.css yet hardcoded off-grid spacing (6px gaps, 3px 2px paddings) + raw 4px
card+cell radii - the ds_statcheck class, ZERO item-184 exception annotations. Its 4 BUILD-pane siblings
(cd_ledger/draft_elo/spike_curve/ward_heat) were correctly REJECTED: all carry item-184 operator-exception
annotations (settled audit, do NOT re-litigate). Overlay-gated cues rejected on the reachability gate.

THE FIX (web/css/panels/spike_markers.css, CSS token swap, presentation-only): off-grid 6px/3px/2px
spacing -> --space-1/--space-2 8px grid; 4px radii -> --panel-radius-sm (10px). Typography already on
--fs-* (untouched); 1px intra-cell hairline kept (commented). NEW tests/snapshot_panels/
test_spike_markers_view.py: RED-first (computed radius==10px / head gap==8px; RED at 4px/6px) + structure
+ ASCII + screenshot. Commit 1ae7dc52, pushed. Tier-1 frontend (no engine/DS/Share/ENGINE_VERSION).
verifier CONFIRM; 219 snapshot+DOM tests green; ruff clean; 0 non-ASCII.

NEXT: the un-audited UI-surface audit lane has more candidates (DS sandbox ds_combo/ds_matchup/ds_sweep,
cc_blended_ehp_threat, cc_conditional_pressure - VERIFY the reachable render path first). Carry-forward
OWED (live-gated, not headless): E.1 ACTIVE knob (operator-PHYSICAL); RC_COMP_HP_LEAN flip (operator-gated).
Don't-redo: render-gate sweep COMPLETE; competitor-lift lane heavily mined (7 docs); shadow-aggregator
DRAINED (595/596/597); overlay-polish DRAINED (591); DS scorer-valuation CLOSED (592).

---

# 2026-06-23 (R27 DIRECTOR REFILL) - render-gate sweep CLEAN (bug isolated) + ctx-panel dedup desync fix

The R26 follow-on. Re-probed: mode=client, NO live game (League client in lobby; rc-shell overlay
CLIENT state PID 9736) - so live-gated work was UN-validatable this cycle. Interviewed the gemini
director (gemini-3-pro-preview, loop_controller.gemini()); fed live state + the candidate menu, it
picked the headless-buildable LEAD (broader SHIPPED-PANEL render-gate audit). Scratch interview
script deleted. Ground-truth fix to its scope: dashboard.js is dead code (Settled), live controller
is main.js; no overlay.js exists.

THE AUDIT (3 parallel read-only agents, ~56 panels, disjoint slices; 4 failure modes: [hidden]-attr-
vs-style.display / positional-vs-id index / stale gate accessor / unwired renderer). VERDICT = NEGATIVE:
the ds_statcheck dead-panel bug is ISOLATED - no other panel is dead. Independently re-verified the
lone genuine [hidden]+style.display overlap MYSELF (#am-spike-markers, index.html:2126 + active_match.js
:1062/1067): NOT dead - spike_markers.js:147 sets .hidden=false on the content path -> removes the attr.

THE REAL FIND + FIX (came out of tracing #am-spike-markers): a SYSTEMIC latent idempotency edge in the
3 ctx-driven active-match panels (spike_markers/spike_curve/draft_elo). Each dedups render by content
SIGNATURE; the outer active_match.js _render*FromCtx HIDE paths clobber mount.innerHTML="" behind the
renderer (e.g. active_match.js:1062-1063), desyncing the stamped sig from the now-empty DOM. After a
transient liveclient dropout (champ briefly absent) + a re-show with IDENTICAL data, the sig-dedup
early-returns and the cleared innerHTML never repaints -> a VISIBLE-BUT-EMPTY panel on the in-game
overlay until the next level/item change. Fix (1 line each): the dedup guard also requires innerHTML
!=="" before short-circuiting -> an externally-emptied mount always repaints; zero rendered-output
delta in normal operation. RED-first tests/snapshot_panels/test_render_dedup_reshow.py 4/4 (RED first:
reshowLen==0 x3). 128 panel/surface tests green; ruff clean; hygiene 13/13; 0 non-ASCII. Tier-1 frontend
(no engine/DS/Share/ENGINE_VERSION; no DS restart; no 5-phase audit - zero visual delta). Commit
29c48b21 -> rebased bf2ff10d (concurrent weekly-health push), pushed.

NEXT: render-gate sweep DONE - do NOT re-run (bug isolated to the already-fixed ds_statcheck). Carry-
forward OWED, both need a live game / operator action (neither headless-buildable): E.1 ACTIVE knob
round-trip (operator-PHYSICAL only); RC_COMP_HP_LEAN default-ON flip (operator-gated). Don't-redo:
shadow-aggregator lane DRAINED (595/596/597); overlay-polish DRAINED (591); DS scorer-valuation CLOSED
(592); candidate (c) operator-physical-blocked.
