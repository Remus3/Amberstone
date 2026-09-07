# Champ Select QA - Operator Review 2026-07-03 (RULINGS FINAL)

Method: top-to-bottom operator walkthrough, Claude as advocate. 4 rounds, all rulings
final. Implementation slices follow (worktree agents, verifier-gated, 5-phase audit
before commit). Source inventory: 6-mapper workflow over champ_select.js /
champ_select_view.css / index.html / builders / fixtures (2026-07-03).

## A. Pre-verified findings - RULINGS

| # | Finding | Ruling |
|---|---------|--------|
| A1 | Queue-2400 vocab mismatch: `_csvDetectMode`=aram (champ_select.js:375) vs capability-gap dispatcher mode="KIWI" (:2336) | FIX - align frontend+backend vocab, regression test |
| A2 | `.csv-sugg-bans` + `.csv-sugg-pickorder` hidden since 2026-05-23 (css:86-87) but JS still fetches+renders | REMOVE JS writes + fetches |
| A3 | Mood tabs hidden (css:1730-1737) but mood state still filters pick recs via sessionStorage | REMOVE mood ENTIRELY - raw top-3 by score, strip client filter + any backend param |
| A4 | Deprecated YOUR RECORD block fetch path (champ_select.js:4136-4172, 4415-4417) | REMOVE code path |
| A5 | Capability-gap card never rendered (RC_CAPGAP_SURFACE OFF) | FLIP ON - code default ON, env override stays |
| A6 | `_csvSetupTimerTick` claimed no-op since s214 | VERIFY then strip if dead |
| A7 | Dual-score ban toggle inside hidden A2 wrapper (dead UI, :2087-2127) | REMOVE with A2 |

## B. Element rulings - FINAL

| # | Element | Ruling |
|---|---------|--------|
| B1 | Ally roster + trade/swap popup | KEEP |
| B2 | Archetype picker + DS top-3 preview | KEEP |
| B3 | Enemy roster (WR slot / tags / confidence) | KEEP |
| B4 | Portrait row + LOCK IN | KEEP |
| B5 | Summoner spell strip (9-cell) | COMPACT: 2 current spells + edit affordance expands full picker |
| B6 | Build chooser | MERGE with B7: one build section, variant rows select, ordered sequence strip reflects selection, ONE push (keep Runes/Spells/Build checkboxes) |
| B7 | Build order card | MERGED into B6 |
| B8 | CC blended EHP chip | CLUSTER: collapsed TEAM ANALYSIS block, one-line verdict header, expand for detail |
| B9 | CC conditional pressure chip | CLUSTER with B8 |
| B10 | Capability gap card | =A5, flip ON |
| B11 | Personal best build card | KEEP |
| B12 | CC pairing card (CS1) | REMOVE from champ select (backend /api/cc-pairing stays) |
| B13 | Pick & Ban picks sub-panel | KEEP (mood-free after A3) |
| B14 | Pick & Ban bans sub-panel | KEEP |
| B15 | Ally-picks-by-role mirror | REMOVE (duplicates ALLIES card) |
| B16 | Explanation lines + cleanse advisory | KEEP |
| B17 | Counter picks (hero + 4) | KEEP |
| B18 | Team damage lean bar | CLUSTER into TEAM ANALYSIS block |
| B19 | Cooldown watch | REMOVE from champ select (overlay surfaces it in-game when it matters; backend stays) |
| B20 | DS profile card | MOVE to Builds/DS view |
| B21 | DS skill order card | KEEP (only DS card staying) |
| B22 | DS knobs + DS stat-check | MOVE to Builds/DS view (CS3 family) |
| B23 | Player GPI radar | REMOVE from champ select (lives on history/PGR surfaces) |
| B24 | ARAM bench + comp verdict | KEEP |
| B25 | Arena duo + augments pane | KEEP |

Core-set misbehavior check: operator reports NONE in the kept core set.

## C. Panel visibility settings - DESIGN LOCKED

- Tabs: SR / ARAM / Arena / TFT / Out-of-game (5). Brawl inherits SR (retired s214, no tab).
- Scope: ALL main dashboard panels get per-mode rows (not just the legacy 5).
  Champ-select-page internal cards stay hand-curated (this QA), NOT in the system.
- Storage: expand CONTEXTS in web/js/panels/panel_visibility.js (in-game-sr /
  in-game-aram / in-game-arena / in-game-tft / out-game); `normalizeVisibility()`
  migration copies legacy `in-game` prefs to every mode context (fail-open).
- Re-apply hook already wired (main.js:573 setMode -> applyPanelVisibility).
- Overlay widget system (rc-overlay-layout) untouched - separate by design.

## D. Decisions log

- 2026-07-03 QA rounds 1-4 complete; all rulings above final. Implementation
  dispatched: slice A (champ_select rework), slice B (per-mode visibility),
  slice C (Builds/DS receiving side), slice D (backend: capgap default ON,
  vocab fix, mood strip). Next pages queue after champ select ships.
- 2026-07-03 SHIPPED (LEDGER 765, merges through `bc705c79`): all rulings
  implemented - 4 verifier-CONFIRMED worktree slices, 5-phase audit (2
  MUST-FIX fixed in-slice: .csv-ta-body[hidden] collapse pin + focus-visible
  rings), 3 cross-slice test alignments, suite 10566/2skip green, RC
  restarted pid 3644, capgap live-verified serving. Follow-ups: orphaned
  cooldown_watch.js / ban_suggest_toggle.js / buildOrderCardHtml (kept, not
  deleted); pre-existing ARAM/Arena #csv-picks-target stale placeholder;
  B37 in-game capgap eyeball (LIVE_GAME_GATED_SYNC). NEXT PAGE: operator
  picks the next surface for the same QA method.
