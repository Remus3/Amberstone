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

NEXT: the overlay-polish lane is now genuinely DRAINED (this was the one (d) slice; the rest is
shipped / operator-gated / Phase-4-deferred). OWED: live in-game capture of the band channel + S0
over a real game. With no overlay slice left, the next unit is non-overlay (interview the gemini
director per the gate fallback) OR clear the OWED capture when a practice game is up.

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

---

# 2026-06-22 (headless continue 22 / R20) - Aggregator N lift: ARAM balance grid panel

Item 588, commit `e0f0ffac` (feature, pushed) + docs-sync. Tier-1 frontend (read-side route + panel +
pure accessor); NO engine / DS schema / ENGINE_VERSION / Share change (held 1.151.0); RC restarted
(pid 9480 -> 25356) to load the new route. gemini+ahk loop executor cycle 9. Directive = ORCHESTRATION_PLAN
R20 DIRECTOR REFILL - Section-7b competitor deep-dive lift of Aggregator N + ship any HIGH/LOW-risk presentation
finding in-run.

WHAT (lift). Aggregator N (aggregator N) heavyweight one-agent teardown, 6-point checklist, output
`docs/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md` (F1-F7). VERIFIED PREMISE (ground truth, not the agent's
word): `data/daemon_slayer/16.12.1/champions.json` `lolmath.aram_modifiers` carries all 7 ARAM fields
(Dealt/Taken/Healing/Shielding/Tenacity/AbilityHaste/AttackSpeed) for all 172 champs, but
`core/aram_balance_context.py` consumed only dealt+taken as a coach-PROMPT line and ZERO web panel
rendered any of it (grep-confirmed). So F1 = HIGH-value / LOW-risk / presentation-only over local data.

WHAT (ship). F1 SHIPPED IN-RUN: new `balance_grid_for`/`balance_grid_map` accessors (existing prompt
symbols byte-identical) + `GET /api/aram-balance` (`dashboard/routes_aram_balance.py`, 134 non-neutral
champs, live-proven 200/16.12.1/Aatrox +5%) + mode-gated `web/js/panels/aram_balance.js` grid (self from
`coach.champion`; ally/enemy from `liveclient.allPlayers`; signed green/red deltas, AH additive) + css/
index/main.js wiring. asset-hash auto-reload for JS/CSS; the new route needed the RC restart.

DEVIATION (intent over literal). Build spec assumed top-level `st.champion`/`st.my_team`; ground truth is
`coach.champion` + `liveclient.allPlayers` (the build agent self-corrected from the active_match.js
precedent). Single worktree build agent NOT parallel slices: the feature's wiring files (index.html /
main.js / dashboard.css / _dispatch.py) are shared, so parallel disjoint worktrees would only collide -
verifier-gated single agent is the correct shape for a cohesive vertical slice.

VERIFY. RED-first `tests/test_aram_balance_grid.py` (13). 1 worktree build agent -> read-only verifier
CONFIRM (re-ran 13 green, ruff clean, route 200, byte-identical existing defs, ASCII, node --check, no
frozen files) -> ff-only merge. Full RC suite `9391 passed / 2 skip / 103 subtests` (= R19's 9378 + 13
new), the SAME 12 pre-existing fails (3x CoachWire ARAM-template, 7 ds_pick_consumption ARAM subfails,
overlay.css sub-floor, spell_autopush on dirty `data/spell_prefs.json`) - 0 regressions. git: only the 9
intended files changed, none under `agents/daemon_slayer/` so DS suite not re-run + no DS Share sync owed.

CARRY-FORWARD (VISUAL OWED). The populated ARAM-mode panel capture: the panel is mode-gated and live state
is idle (mode=client); this headless cycle cannot drive `?ui_mock=1&mode=aram` - `preview_start` refuses to
attach to the supervisor-owned `:8888` (freeing the port kills the live runtime) and computer-use/Chrome
navigation needs an interactive `request_access` the away operator can't grant (would block the run). Per
Section-3b option 3 the code-side 5-phase audit + verifier + live backend proof stand in-slice; the
populated capture is OWED - drive it on the next cycle that has a live ARAM game or a connected
claude-in-chrome. Also still dirty + uncommitted: `data/spell_prefs.json` (runtime drift, not authored).

TRIAGE. F2 per-slot item win-rate ladder over rewind_history.db -> BACKLOG (MED-HIGH, thin solo sample);
F3/F5 already-have; F4 forbidden external winrate; F7 new TFT domain - all defer.
