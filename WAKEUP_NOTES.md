# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-23 (R25 DIRECTOR REFILL) - live in-game overlay capture (E.1 cleared) + DOM-producer S0-pulse test

Re-probed live state and found the perishable resource the prior cycles lacked: a live SR game UP
(Syndra AP mage vs a Braum/Gragas tank+CC comp) AND the rc-shell Electron overlay RUNNING over League
(electron PID 9736, title "RC . Syndra") - the precondition that was UN-confirmable headless at R24.
Interviewed the gemini director (gemini-3-pro-preview, loop_controller.gemini()); fed the live context,
it decisively picked candidate (a): the OWED in-game overlay eye-line + S0-pulse capture (E.1), over the
operator-gated RC_COMP_HP_LEAN flip ("can be done anytime"). Commit 12a97f9c, pushed. Tier-1 frontend.

CAPTURED (live, real coach state): Playwright on the LIVE https://legion-rc:8888/?overlay=1 (not a
fixture, not 127.0.0.1) read body[data-shell]=overlay; #right-now s0Cue=choices / s0Tier=urgent /
s0Pulse=0 (a SUSTAINED one-shot-urgent CHOICES cue did NOT arm a pulse -> producer-side motion rationing
verified live, no over-fire); CALL action data-call-band=fight, gold 3px bar rgb(200,170,110), white verb,
glyph U+25BA (item 591 band channel live-faithful); eye-line widgets positioned, spike + fight-model
hidden in the coach panelset, CALL 22px. A Legion desktop screenshot caught the REAL Electron overlay
compositing TRANSPARENTLY over the live Rift (CALL "SETUP DRAKE FIGHT" gold bar + WARD UP + minimap-rect
float over the game). :8889/latest-frame was dead (screen_agent not posting, http 000) - desktop +
Playwright routes used instead.

VERIFY-THE-PREMISE (test gap): the node chain tests never import right_now.js + the DOM consumer tests
manually SET #right-now[data-s0-pulse], so NO test exercised the right_now.js PRODUCER render that stamps
it. New tests/snapshot_panels/test_overlay_view.py::test_overlay_s0_pulse_rations_sustained_choices_via_producer
drives the real renderRightNow producer (arm then ration) + reads the stamp back. 82 passed + 14 subtests
in the overlay Tier-1 selection (the lone teardown ERROR is the live RC writing data/ during the game -
mtimes this-second-fresh, my test touches them 0 times; CI-clean). 0 non-ASCII; verifier-equivalent via
the Plan-spec file:line premise check.

NEXT: shadow-aggregator lane DRAINED + overlay-polish CSS/JS lane DRAINED + DS scorer-valuation CLOSED.
E.1 CAPTURE cleared; the ACTIVE knob-interaction half (Alt+Shift+A live re-rank) stays OWED (needs a
physical hotkey over League - synthesized presses leak to the game). Carry-forward operator-gated: the
RC_COMP_HP_LEAN default-ON flip (eyeball-validated R24/R25; needs the in-code gate-drop in
coach_integration/enemy_stats.py OR approval for the FROZEN supervisor env). Next unit = another
gemini-directed NON-DS-scorer refill.

---

# 2026-06-23 (R24 DIRECTOR REFILL same-lane) - macro_response_shadow register aggregator + RC_COMP_HP_LEAN eyeball

Continued R23's lane (the last un-aggregated shadow log). Two slices shipped; a live SR game
was up (AP Seraphine vs a 3-tank comp), so the directive-unlocked live-gated eyeball ran too.

SLICE 1 (primary): tools/macro_response_shadow_report.py + 23 hermetic tests (commit 0949fde5).
NOT an objective-category copy. VERIFY-THE-PREMISE (live census): the det side is a single
macro_stagnation tag with 3 lead-keyed generic stall nudges, so an objective-category match
false-scores ~0.5%. Re-derived an ACTION-REGISTER metric: each side ACTIVE-PUSH (rotate/group/
setup/take/push/force...) vs PASSIVE-SCALE (farm/scale/safe/hold/defend...) by earliest WHOLE-
TOKEN (load-bearing: defend contains end, 536 rows); NO skip de-leak (measured 0.556%, below the
floor). NEW by_lead_state_register block is the real signal since det is constant per lead: live
ahead 0.935 / even 0.907 / BEHIND 0.000 (det PASSIVE "keep scaling/safe" vs Haiku ACTIVE "rotate
baron/force end" x407) = the do-not-flip finding. Headline 89% clears the 0.70 floor but the hint
redirects to the per-lead block. HOLD. Tier-1 (Share sync skipped); verifier-CONFIRM; 0 non-ASCII.

SLICE 2 (live-gated OWED, directive-unlocked): the RC_COMP_HP_LEAN AP-mage-vs-2+-tank eyeball
(OWED since ledger 592) cleared - me=Seraphine vs Braum/ChoGath/Gragas (3 tanks). hp_scale 1.20x,
max_hp 2980->3576. Ranker OFF-vs-ON (headless, no live-process touch): Seraphine routes to HPS/
enchanter (seam NO-OP); pure mages boost ONLY Liandry's (+6.5 dps/+17%, proportional), flat items
byte-identical = SANER NOT DIFFERENT, do-not-flip-blind SATISFIED. Visible top-6 impact narrow
(Liandry's already rank-1). Recorded in docs/LIVE_GAME_GATED_SYNC.md. FLIP stays operator-gated
(supervisor env frozen; global default change is deliberate).

NEXT: shadow-aggregator lane now DRAINED (det_coach 595 / objective_playbook 596 / macro_response
597). Carry-forward OWED: live overlay eye-line + S0-pulse capture (needs the rc-shell Electron
overlay running over League - not confirmable this headless session). DS scorer-valuation CLOSED.

---

# 2026-06-23 (R23 DIRECTOR REFILL same-lane) - objective_playbook_shadow agreement aggregator

Continued R22's lane (it teed up two un-aggregated shadow logs). A live SR practice game
came up mid-session (mode_key=sr, liveclient True) but this was a headless tooling unit -
the live-gated lanes need a specific comp/overlay, not this game. Plan subagent emitted the
spec off a live 18.9k-row census; built inline (sole author, 2 files), verified fresh.
Commit 6a615fad, pushed, CI green. Tier-1 (no engine/DS/Share/ENGINE_VERSION; hook SKIPPED
Share sync, confirming Tier-1).

VERIFY-THE-PREMISE payoff: these logs are NOT the det_coach shape (no choice-lists /
source_tag - each row is a single tag+line directive vs free-form native_objective prose),
so the det_coach trade/build/macro taxonomy does NOT transfer. The two logs SPLIT:
objective_playbook fits an OBJECTIVE-CATEGORY metric (genuine 54.5% raw, clean det=dragon /
native=baron confusion); macro_response's det side is a GENERIC stall nudge (single
macro_stagnation tag) so the same metric scores a false 0.5% - it needs a DIFFERENT
action-register metric, deliberately deferred (NOT forced).

Shipped tools/objective_playbook_shadow_report.py (mirrors det_coach_shadow_report; markup
strip + whole-token classifier + 2 de-leaks: skip-clause excision, respawn demotion). Live
(19,131 rows): 13,445 both-present, 37% alignment -> HOLD (Haiku names BARON when the
dragon-playbook fires, x6,255). RED-first 22/22 hermetic, 0 non-ASCII.

NEXT same-lane: macro_response_shadow action-register aggregator (active-push vs
passive-scale by lead_state - re-derive, do NOT copy det_coach/objective domains). Live-gated
OWED: RC_COMP_HP_LEAN AP-mage-vs-2+-tank eyeball + overlay eye-line/S0-pulse. DS
scorer-valuation track stays CLOSED.
