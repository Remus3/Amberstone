# RC UI/UX Full Redesign - Living Plan

> **SCOPE (2026-07-26, one-tracker pass):** SUPERSEDED for overlay build detail by
> `docs/OVERLAY_BUILD_MASTER_PLAN.md` (newer, more referenced). Retained as the 2026-06-22
> redesign directive + page inventory. Open work is tracked in `ROADMAP.md` (RM-03), not here.

Operator directive 2026-06-22: redesign ALL pages (in-game + out-of-game), Gemini-directed,
grounded in `docs/design/RC2_DESIGN.html` (greenlit Hextech) + `docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_*`,
using mocks + screen captures, looped exhaustively. The 2026-06-21 dashboard-retirement is
LIFTED - the out-of-game 1920 dashboard is back in scope.

Director: `gemini-3-pro-preview` (via `ops/loop/loop_controller.py` gemini), plan dated 2026-06-22.

## Design system (unifying direction)
- 8px spacing grid (`web/css/tokens.css`). Hextech palette: canvas #0A0E14, surface #111722 /
  #16202E, surface-3 #1C2A3D, accent gold #C8AA6E, accent-2 cyan #0AC8B9, good #37D08A,
  warn #E8A33D, bad #E84057, info #7CA8FF, text #ECF2FF, dim #8FA3BF, faint #5C6E88,
  border rgba(200,170,110,.16), glow rgba(10,200,185,.30).
- Component vocabulary: `hx-card` (surface + Hextech border + gold corner brackets), `hx-chip`,
  `hx-bar` (progress), `hx-empty` (sigil empty state). Type: Segoe UI, floors 13/15/18,
  tabular-nums on every data point.
- Color semantics never hue-alone (pair with a + / - / glyph). Motion: minimal out-of-game;
  overlay 150ms fade only.

## Cycle structure (per page)
read page research + current DOM + RC2_DESIGN section -> mock (show_widget) -> gemini critique
-> build agent implements -> 5-phase audit + Playwright snapshot -> capture -> commit + push.

## Priority order + status
- 0. FOUNDATION (Hextech tokens + base palette cutover + component primitives) - DONE ce3149fc (196 tests)
- 1. in-game overlay - DONE (palette + eye-line layout #2 + per-widget hide + S0 pulse, 2026-06-22)
- 2. champ-select - DONE d33f40a0 (Hextech reskin; P2 counter-hero + P8 AD/AP meter deferred)
- 3. post-game-review (PGR) - DONE a5db9691 (score-hero gold reskin; decomposition/carry/@15 deferred)
- (global) page titles -> Hextech gold - DONE f3ce6e40
- 4. home - DONE 2b250b60 (Tonight's-pick teal-glow hero + form strip + main.js #home repaint fix)
- 5. lobby - DONE 8069d0b9 (hx-card brackets + offline dim + 3 hit-target fixes)
- 6. history - DONE 711fa3d7 (3-card view + W/L glyph + result tint hooks)
- 7. historical-pgr - DONE (inherited via the last_match.css PGR reskin; verified by capture)
- 8. session - DONE 4e29ac49 (aggregate stat-cards, --fs-stat datums)
- 9. user-builds - DONE 591ff515 (active build card gold brackets)
- 10. build-insights - DONE 247e8dff (tab strip + WPA tables; chart sub-panels token-consuming)
- 11. replay - DONE 8ac8e8ff (scrub bar + event chips + E12-1 100vh->flex fix)
- 12. settings - DONE 5719f823 (8px form grid + 44px targets + gold focus rings)

## REDESIGN COMPLETE 2026-06-22
All 12 pages + overlay reskinned onto the Hextech foundation; 15 commits, all pushed.
Final gate: 228 snapshot-panels + design-token tests green. Per-page screenshots in
tests/snapshot_panels/screenshots/. NO sub-panel sweep needed: the conditional content
panels (cc_*/ds_*/op_score/perf_curve/pgr_* etc.) are token-consuming, so the foundation
palette cutover converted them to Hextech automatically; 0 undefined-var fallbacks remain;
the only raw hex left (7) are intentional brand tints (bridge salmon, enemy-red, augment/rank
tier colors). DEFERRED feature lifts (need backend data, noted per page): champ-select P2
live counter-pick hero + P8 ally AD/AP meter; PGR score-decomposition bars + carry-metrics +
@15; home rank/LP header + tracked_win W/L color; history season WR + filters; lobby
last-session recap + ready-check auto-accept; session sparklines. OWED: live in-game overlay
capture of the eye-line layout + S0 pulse (no live game this run).

## Feature-lift tail (gemini 2026-06-22, verified ground truth)
Render backend data the greenlit mocks show but the DOM does not yet. Per-item backing data
verified (file:line + live curl) before building. Director rulings:
- Q1 1a counter-picks (already wired/rendering via _csvRenderCounterPicks champ_select.js:1101):
  ELEVATE to a prominent single-decision hero card (top counter dominates, remaining 4 compact).
- Q2 2c PGR @15: DROPPED - no backing data server-side (no 15-min timeline snapshot); defer to a
  dedicated data epic, not a render lift.
- Q3 5 ready-check auto-accept (autonomous default-ON, no control surface): ADD control+status
  route + UI toggle (invisible autonomous state is a UX anti-pattern).
Build order: (1) 1a counter-hero, (2) 1b ally AD/AP meter, (3) 3 home last-20 W/L strip + WR,
(4) 2a+2b PGR decomposition 5-bar + carry kp/gold-share, (5) 4 history season WR + filters,
(6) 5 ready-check toggle (GET/POST /api/lcu/auto-accept). Standing acceptance per item: tokens-only
(no raw hex), interactive >=44px, status never hue-alone (glyph), Segoe UI min 13px tabular-nums,
RED-first tests, Playwright snapshot, idempotent renders + asset-hash hot reload. Each its own
commit + push. Verified-NOT-built: 1b (no team aggregator), 5 route. Verified RENDER-ONLY: 2a/2b,
3 strip, 4 WR+filters. Verified ALREADY-DONE base: 1a fetch/render, 3 rank/LP header.

### FEATURE-LIFT TAIL COMPLETE 2026-06-22 (ledger item 590, 6 commits pushed)
All buildable lifts shipped + live-proven; cross-lift regression 236/236 snapshot+backend green.
- 1a counter-pick hero `b3fa4a7f` - 1b ally AD/AP meter `b686da59` (new /api/champ-select/team-damage-mix)
- 3 home last-20 W/L strip + WR `87240826` (last20 injected into /api/home/summary)
- 2a PGR decomposition 5-bar `cf1896ae` (consumes components+weights_used; 2b carry metrics were
  ALREADY shipped s219; 2c @15 DROPPED - no backing data)
- 4 history season WR + filters `4d5a9425` (retired the "needs Riot key" stub; caught+fixed a
  win_rate percent-vs-fraction unit bug)
- 5 ready-check toggle `8370fe7d` - new core/auto_accept_pref.py + GET/POST /api/lcu/auto-accept +
  operator-AUTHORIZED minimal frozen lcu_client.py gate; UNIFIED into the existing lobby Auto-Accept
  toggle (one control, both mechanisms) rather than a 2nd switch.
OWED (still): live in-game overlay capture (eye-line layout + S0 pulse) - no live game this run.

## Per-page moves (gemini 2026-06-22, condensed)
- champ-select: strict vertical columns (bans / picks / counters); good-warn-bad + glyph on matchup ratings; accent-2 cyan outline on augment recos.
- pgr: 0-100 score in gold, 54px tabular hero; lane-compare side-by-side horizontal bars; timeline as horizontal card track.
- home: tonight-pick hero card (canvas + cyan glow); profile stats as hx-chips; cut redundant center-view nav.
- lobby: top-8 mains as dense chip grid; dim text for offline/low-priority members; roster as hx-cards with 16202E heads.
- history: high-density rows on #111722; W/L glyph + good/bad; tabular KDA + CS/min.
- session: large numeric cards (18px head / 32px datum); accent-2 trend sparklines.
- user-builds: item grid, 44px targets; corner brackets on the active build card.
- build-insights: side-by-side hx-cards; tabular winrate %.
- replay: timeline scrub bar; diagnostic event callout chips.
- settings: strict 8px label/input grid; 44px toggles/inputs.

## Acceptance criteria (per page)
- No raw hex in that page CSS/JS (consume tokens / hx-* primitives).
- All interactive elements >= 44px hit-target.
- Segoe UI, min 13px, tabular-nums active on data points.
- Status never hue-alone (glyph present).
- Passes the 5-phase audit (structure / typography / hit-targets / ascii / hierarchy).
- Playwright snapshot tests updated + green. Idempotent renders, asset-hash hot reload (no restart).

## Sequencing / risks
- FOUNDATION first (mitigates hardcoded-color breakage when the grid/palette lands).
- Shared-file collisions: `header.css` carries lobby + home + champ-select chrome -> sequence
  those three, do NOT parallel-edit header.css. `base.css` / `tokens.css` are foundation-only.
- Each page is its own commit + push + CI. Live in-game capture of overlay changes OWED.
