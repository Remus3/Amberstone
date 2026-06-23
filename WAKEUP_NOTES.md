# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-23 (R26 DIRECTOR REFILL) - VERIFY-THE-PREMISE refuted (c); UI-audit pivot found a DEAD panel

Re-probed: live SR game UP (Syndra AP mage vs Braum/Gragas/Master Yi) + the rc-shell overlay running
(PID 9736). Interviewed the gemini director (gemini-3-pro-preview, loop_controller.gemini()); fed the
live state, it decisively picked candidate (c) - the OWED E.1 "Alt+Shift+A live re-rank" knob round-trip
- to spend the perishable window. A Plan subagent + ground-truth file:line check REFUTED it for a
headless session: Alt+Shift+A (rc-shell/src/main.js:1058) is a click-through ACTIVE TOGGLE, not a
re-rank; the non-hotkey IPC twin (set-active -> setOverlayActive) already exists + is unit-tested but is
unreachable headless (rc-shell = plain `electron .`, no debug port; window.rcShell is preload-only,
absent in a :8888 browser). So (c) needs the operator's PHYSICAL press - NOT a headless build (recorded
in LIVE_GAME_GATED_SYNC.md E.1).

Faithful to the director's INTENT (spend the live window) but respecting ground truth, pivoted to (b): a
live-populated un-audited UI surface audit. Target = ds_statcheck (champ-select Stat Sandbox). THE FIND:
the panel had NEVER rendered since it shipped - renderDsStatcheck indexed resolveChampNames (a POSITIONAL
slug array) by numeric champId (names[222] = always undefined -> early return), and showed via
style.display while the mount (index.html:1219) carries the [hidden] attribute. That is exactly why it
carried a permanently-OWED visual capture: nobody ever saw it render. Root-cause fix mirrors the 5
siblings (names[0] + blockEl.hidden = true/false); a 6-caller sweep proved the bug ISOLATED.

5-phase fixture audit shipped WITH the fix (panel never seen before): HIT-TARGETS - the 4 editable inputs
were ~21px tall, added min-height var(--hit-min) 42px + spec padding/radius; TYPOGRAPHY - 7 label/metadata
--fs-2xs(13px) -> --fs-xs(16px), title -> --fs-sm(18px), bringing it to the sibling DS-panel cluster
baseline (ds_knobs/ds_profile/ds_relscore/cc_pairing carry zero --fs-2xs). New RED-first Playwright guard
(test_ds_statcheck_view.py, mirrors test_ds_relscore_view) 2/2 + existing ds_statcheck coverage 35/35
green; verifier-gated SHIP; 0 non-ASCII. Commit e37838b4, pushed. Tier-1 (hook SKIPPED Share sync).
Screenshot local-only (gitignored).

NEXT: open follow-on = a broader SHIPPED-PANEL render-gate audit (ds_statcheck was dead for months
undetected; this sweep only covered resolveChampNames callers). Carry-forward OWED: E.1 ACTIVE knob
(operator-physical only); RC_COMP_HP_LEAN default-ON flip (operator-gated). Don't-redo: shadow-aggregator
lane DRAINED (595/596/597); overlay-polish DRAINED (591); DS scorer-valuation CLOSED (592); candidate (c)
operator-physical-blocked.
