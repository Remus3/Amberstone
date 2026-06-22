# RC UI/UX Full Redesign - Living Plan

Operator directive 2026-06-22: redesign ALL pages (in-game + out-of-game), Gemini-directed,
grounded in `docs/design/RC2_DESIGN.html` (greenlit Hextech) + `docs/research/RC2_RESEARCH_*`,
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
- 4. home - WIP (identity + Tonight's-pick hero + form strip)
- 5. lobby - TODO (pre-game context)
- 6. history - TODO (dense tabular)
- 7. historical-pgr - TODO (inherits PGR)
- 8. session - TODO (aggregate stat cards + sparklines)
- 9. user-builds - TODO (item grid, 44px targets)
- 10. build-insights - TODO (side-by-side analytics cards)
- 11. replay - TODO (scrub bar + event chips)
- 12. settings - TODO (8px form grid, 44px targets)

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
