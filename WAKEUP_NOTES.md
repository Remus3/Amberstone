# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-22 (overlay-polish run) - band channel on the PRIMARY action line

Operator directive: route cycles to the in-game Electron overlay until it matches the agreed
glance-first design. GATE this cycle: mode=client / liveclient null - no live game, so the live
in-game capture is OWED (carry-forward) and I worked the overlay-polish lane against the live
backend per the directive's gate fallback. Ledger item 591, commit `41c6ae50` (pushed).

A read-only Plan gap-analysis vs `docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md` +
`docs/OVERLAY_DOCTRINE.md` narrowly REFUTED the ROADMAP "lane DRAINED" claim - exactly ONE
buildable slice remained. When the 460px dock was retired (item 564) and S0 moved from
`#rn-action` to the `w-call` widget, the band-color binding did NOT migrate (it lived on
`web/css/panels/right_now.css .action-urgent`/`.action-good`, but `#rn-action` is now
`display:none` in the overlay), so the overlay ACTION line rendered flat WHITE for every coach
band (`overlay.css:298-303`) - urgent (retreat/dead/recall) and good (push/secured) read
identically - and the `overlay.css:570` combat-shed comment ("the band color carry the read")
described behavior that did not exist. Everything else in the spec was confirmed already-shipped /
operator-gated-flip / Phase-4-deferred.

SHIPPED: `web/js/panels/active_match.js` stamps `data-call-band` from the shipped
`classifyAction(action)` + prepends an `aria-hidden` band glyph built with `String.fromCharCode`
(U+26A0 warn / U+2713 check / U+25BA play, so the file stays 7-bit ASCII), gated on
`body[data-shell="overlay"]` so the 1920 dashboard render is byte-identical. `web/css/overlay.css`
keys a glyph color + 3px color-bar left border off the band: urgent=red (the ONE reserved
emergency pop-out, rule 4) / fight=gold / good=green; the verb TEXT stays white (doctrine 164).
RED-first `test_overlay_call_action_band_channel` asserts `data-call-band == classifyAction(verb)`
(the WIRING, guards the fixture-shaped-to-bug mode) + the glyph/bar token colors + the white verb;
27/27 overlay tests green; 0 non-ASCII bytes; EOL-consistent. Live-verified on the legion-rc:8888
origin (band=good, green check-glyph + green bar, white verb) - vs the LIVE backend, not just the
fixture. Tier-1 frontend (overlay.css NOT frozen + the overlay renderer); asset-hash hot-reload,
NO engine / DS / Share / ENGINE_VERSION change.

OWED CLEARED later this session: the operator started a Caitlyn SR practice game, so I drove the
live in-game capture. On the legion-rc:8888 origin the band channel rendered the FIGHT/gold path
live (gold play-glyph + gold bar + white verb on "SETUP DRAKE WARD" then "HOLD LANE SCALING"), the
eye-line layout #2 defaults held (w-call 760,140 / w-lead 786 / w-callouts 1486, position:fixed),
the S0 pulse stayed correctly UNARMED for the non-emergency cue, and the :8889 self_grab frame
(1280x720 jpeg, primary=true, X-RC-Token auth) confirmed the vision pipeline AND showed the overlay
composited over the real game. good/green (ui_mock) + fight/gold (live) are both proven; urgent/red
is the same code path (unit-tested).

NEXT: the overlay-polish lane is genuinely DRAINED. Interviewed the gemini director
(gemini-3-pro-preview, via the loop_controller gemini() pattern) for the next NON-OVERLAY unit ->
it recommended the DS scorer-valuation residual (AP DoT-burn vs burst EHP-gating + kill-state
passive weighting for low-kill-share/utility archetypes). VERIFICATION CORRECTIONS (audit-proposals-
are-intent): the cited files all EXIST (core/damage_mix.py, carry_share.py, ds_calibration.py,
coach_trace.py) BUT the BASE scorers are ALREADY SHIPPED (test_dsv1_ability_burn_valuation.py +
test_dsv2_killstate_passives.py, DSV1/DSV2 items 429-437), so the genuine remaining work is the
CALIBRATION RESIDUAL only (the ROADMAP G5/G6 design-level lane, Gemini-consult-first), and it is
TIER-2 (scorer/item-effect -> ENGINE_VERSION bump + dual suite + DS restart + Share mirror), NOT
gemini's stated Tier-1. The next-session prompt is built on this (verify the residual is a REAL
measurable false-positive, rewind-WIN-anchored, BEFORE building).

---

# 2026-06-22 (UI feature-lift tail) - render the backend data the mocks show

Follow-on to the item-589 Hextech reskin: render data the greenlit mocks show but the DOM did
not yet (BACKEND-GATED, not pure CSS). Ledger item 590. gemini-directed; plan + rulings in
docs/RC2_REDESIGN_PLAN.md (Feature-lift tail). 6 commits pushed; cross-lift regression 236/236
snapshot+backend tests green. Tier-1 frontend + 2 thin read routes + 1 minimal frozen edit; NO
engine / DS / Share / ENGINE_VERSION change.

SHIPPED (each: gemini spec -> build agent -> orchestrator FRESH re-verify (diff + tests + hex/ASCII
+ test-body read) -> commit + push + restart/live-curl for routes):
- 1a counter-pick HERO card `4d0172b6` (counters[0] dominant + compact [1..4]; backend was already
  wired RC2 E4 - prominence elevation only).
- 1b ally AD/AP meter `66375d63` - NEW GET /api/champ-select/team-damage-mix (info.attack vs
  info.magic tally) -> dual-color bar; live 58/42.
- 3 home last-20 W/L strip + WR `c3bf040d` - shared _compute_last20() extracted from _build_history
  (byte-identical, 7/7 regression), last20 injected into /api/home/summary; live 7-13 35.0%.
- 2a PGR decomposition 5-bar `a461980b` - last_match.js consumes the rubric components+weights_used
  (saturation = comp/(2*weight)); route already returned them. 2b carry metrics ALREADY shipped
  (s219 _setStatsGrid) - not rebuilt. 2c @15 DROPPED (no backing data, gemini ruling).
- 4 history season WR + filters `c0ce9faf` - retired the "needs Riot key" stub; global client-side
  champion/mode/result/grade filters. CAUGHT+FIXED an agent unit-bug: win_rate is a PERCENT live
  (51.6) but the agent rendered it *100 -> "5160%" and shaped the ui_mock fixture to the bug;
  corrected JS + fixture (lesson: live-curl the unit before trusting a fixture-passing test).
- 5 ready-check toggle `8e972a14` - NEW non-frozen core/auto_accept_pref.py + GET/POST
  /api/lcu/auto-accept; operator-AUTHORIZED minimal frozen lcu_client.py gate (_auto_accept_tick
  wraps accept_queue in `if is_enabled()`, default ON = byte-identical). The in-process force-accept
  loop is a SEPARATE mechanism from the existing #lv-auto-accept (which set_configs the RC-LCUAgent
  via :8889); UNIFIED into the existing toggle (one control gates both) instead of a 2nd switch.
  Live GET/POST round-trip + 400 proven; pref left ON.

CONFIRM-PER-ITEM caught 2 "already done" (2b carry, 1a/3 base) + the lift-4 unit bug - the
"verify the data per item, never scaffold on the research claim" directive paid off repeatedly.

OWED (carry-forward, unchanged from item 589): live in-game overlay capture (eye-line layout +
S0 pulse) - mode=client all session, no live game to capture.

NEXT: feature-lift tail is EXHAUSTED. Remaining RC2 work = the OWED overlay capture (needs a live
game) + any new research/DS sweeps per ROADMAP/BACKLOG.

---

# 2026-06-22 (UI redesign session) - full Hextech redesign of all 12 pages + overlay

Operator: "redesign of all pages ... in + out of game ... use gemini + the ui/ux research +
screen captures + mocks -> loop exhaustively." Gemini-directed (gemini-3-pro-preview via
ops/loop/loop_controller.py). Living plan + per-page status + deferred lifts:
docs/RC2_REDESIGN_PLAN.md. Ledger item 589. The 2026-06-21 "dashboard RETIRED" decision was
REVERSED - dashboard is back in scope (overlay.css + docs/OVERLAY_DOCTRINE.md comments updated;
do NOT re-apply the retirement).

SHIPPED (17 commits, all pushed, CI green, final gate 228 snapshot+token tests):
- Foundation ce3149fc: base.css/tokens.css palette -> Hextech; NEW web/css/hextech.css
  (hx-card gold brackets / hx-chip / hx-bar / hx-empty sigil); fixed undefined --clock/--label.
- Overlay: palette overlay-scope, eye-line default layout (operator chose #2 over left-column),
  per-widget hide, S0 pulse flipped live, font tokens. Global page titles -> gold (f3ce6e40).
- 12 pages reskinned onto the foundation + captured (tests/snapshot_panels/screenshots/<page>.png;
  non-tested pages gained snapshot tests): champ-select d33f40a0, PGR a5db9691, home 2b250b60
  (+ main.js #home repaint fix), lobby 8069d0b9 (+ 3 hit-target fixes), history 711fa3d7,
  session 4e29ac49, user-builds 591ff515, build-insights 247e8dff, replay 8ac8e8ff (+ E12-1
  100vh->flex), settings 5719f823; historical-pgr inherited. Each CSS-only/near-zero-JS,
  scope-guarded, all data/LCU wiring preserved.

NO sub-panel sweep needed (measured by grep, not assumed): content panels are token-consuming so
the foundation cutover converted them; 0 undefined-var fallbacks remain; the only 7 raw hex left
are intentional brand tints (bridge salmon, enemy-red, augment/rank tier colors).

NEXT (new session - deferred FEATURE lifts, need backend data/render NOT CSS; per page in
RC2_REDESIGN_PLAN.md): champ-select P2 counter-pick hero + P8 ally AD/AP meter; PGR
score-decomposition bars + carry-metrics + @15; home rank/LP + tracked_win W/L color; history
season WR + filters; lobby last-session recap + ready-check auto-accept. OWED: live in-game
overlay capture (eye-line layout + S0 pulse) - no live game this run.
