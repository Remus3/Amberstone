# UI/UX PROGRAM - master QA ledger (operator-present, started 2026-07-22)

Method: memory `feedback_operator_ui_qa_method` - MAP (read-only fan-out) -> ADVOCATE ROUNDS
(batched Qs, each with a keep/move/remove/fix rec AND a counter-argument) -> ACT (worktree
slices, verifier gate, 5-phase fixture audit before commit). Every ruling recorded here.

Source brief: `docs/qa/UI_UX_QUEUE_2026-07-21.md`. Treats the E11 sweep as INCOMPLETE.

## Operator's four asks (do not narrow)

1. Colour is optically off + panels do not cohere - explore a THEME SWAP, not cell patches.
   (NOT the old bare-hex compliance hunt - that comes back empty.)
2. 2-3 LAYOUT ALTERNATIVES per page to choose between, not one proposal to approve.
3. Content audit: some daily-read data points redundant, others missing.
4. Earlier per-page reviews never finished; E11 sweep INCOMPLETE.

## Session framing rulings (2026-07-22, round 0)

| # | Question | Ruling |
|---|----------|--------|
| F1 | When to build the 2560x1440 overlay pseudo-screen | **Build now, in infra phase** - overlay is half the colour complaint, can't theme-swap it without a headless render target |
| F2 | Scheduling the .rofl q2400 backfill (Home/PGR Unknown 0-0-0) | **Parallel track now** - independent of UI, unblocks Home/PGR/Session content rulings |
| F3 | Theme-swap ambition | **2-3 alternative candidate themes** to pick between, then refine one |
| F4 | First per-page slice after design-system | **Home first** |

## Phase plan

- PHASE 0 (infra, parallel): (0a) overlay pseudo-screen @ 2560x1440 headless; (0b) mock
  completeness check for out-of-game pages; (0c PARALLEL) .rofl Layer-1 backfill for q2400.
- PHASE 1 (design-system MAP): cross-page palette/contrast/panel-chrome/overlay inventory ->
  2-3 theme candidates rendered on the mock pages.
- PHASE 2 (advocate rounds): design-system first, then Home, then remaining pages.
- PHASE 3 (ACT): slices behind verifier gate + 5-phase fixture audit, commit, CI green.

## Known defects to route (from queue section B)

Home: Unknown/0-0-0 rows (->0c), stray no-data dot on 14D CS/MIN, bare `.` on TONIGHT'S PICK
good/bad, nav grid omits Champ Select/Active Match/Pre-Game Lobby/Build Insights, panels stuck
on "loading..." forever after one transient fetch fail (no retry/error state).
PGR: `-`/"No grade yet" AND `OVERALL D` together, phantom v2 Refresh-from-Riot button, reference
block reads as own stats (provenance not unmissable).
Replay: right pane clips header ("GOL"), dead slider.
Settings: voice picker empty option list.
Global: footer says "Legion-PC" (retired), large dead space below fold on Home/PGR/Session,
`performance_tracker.py:39` grade labels carry a — escape rendering an em-dash in-UI + written
into data/ratings/last_sr.json + last_arena.json (repo-wide scope unmeasured).
Overlay: THREATS row empty placeholder circles (5 SR/12 Arena), dead DMG/SURV/UTIL steppers
(RM-05 ruled DEAD, removal never landed), complete-build renders bare DAEMON SLAYER/META BUILD
headers with nothing under, R40 draft-elo chip mounted inside hidden `.am-pane-head`
(overlay.css:482) so it can never paint, low-contrast enemy-spell chip labels, unlabeled minimap
ZOI number (no legend), `health.overlay_visible` FALSE while visibly rendering, ARAM balance grid
-> its own draggable widget (verify it landed), G2-35 stats panel needs pace-projected baseline,
G2-34 objective gauges collapse horizontally.

## Verified defects (confirmed live against source, not trusting the queue)

- Footer `Legion-PC`: `web/index.html:2251` (`<span>Legion-PC ... </span>`). One-liner but the
  replacement text is an operator-read UI string -> defer wording to advocate round.
- Em-dash escapes: `performance_tracker.py:37-39` - `—` in ALL SIX `GRADE_LABEL` entries
  (queue logged only line 39). Renders em-dash in-UI + serializes into `data/ratings/last_sr.json`
  + `last_arena.json`. Fix needs the Data-Fixes backfill tail (recover already-written rows),
  not just the source edit. Repo-wide `—`/`–` escape scope still to be swept.

## Rulings ledger

### Design-system round 1 (2026-07-22) - theme direction

| # | Question | Ruling |
|---|----------|--------|
| DS1 | 3 competing chrome systems (gold-hairline / no-border / white-glass) | **Collapse to ONE chrome** - every panel adopts a single border/backing/radius; kill the white-glass hairline |
| DS2 | Which candidate themes to render | **Hextech-Unified + Deep Terminal** (2, not 3; Warm Editorial + Slate Cool dropped) |
| DS3 | Overlay theme target | **Share the chosen palette, keep a documented in-game legibility variant** (stronger border/backing over game pixels) |
| DS4 | Off-theme orphans champ_select + ds_statcheck | **Fold ds_statcheck into the theme pass now; champ_select converts in its own champ-select slice** |

Findings backing these: `docs/qa/DESIGN_SYSTEM_MAP_2026-07-22.md`. Real fault set = structural chrome
split + palette fragmentation + `--faint #5C6E88` AA contrast fail (~3.4:1). NOT a hue-compliance
issue (old pass was right to come back empty on that question).

### SPATIAL BRAND round (2026-07-22) - operator pivoted to define the envelope FIRST

Full detail: `docs/qa/SPATIAL_BRAND_SPEC_2026-07-22.md`. Measured desktop (2560x1440, work area
2560x1400, client 1280x720 centered) + swept 6 competitors live (Overlay App E/Aggregator A/Coaching App Z7/Overlay App F/
Aggregator C/Aggregator B/Overlay App Z5) + web research.

| # | Ruling |
|---|--------|
| SP1 | Out-of-game = ONE **full floating landscape hub** (~1400-1600 wide), overlaps client when open. Retires the 920x1280 portrait + the "live in the empty gutter" premise (no competitor does it; it caused the overflow pain) |
| SP2 | Sizing = **resolution-adaptive auto-fit + manual scale % + remembered position** (Aggregator A model) - the overflow cure |
| SP3 | Overlay stays a separate surface; overlay-settings target = layout Type + Size% + Transparency% + drag Position (+Reset) |
| SP4 | Hextech-Unified theme validated as genre-native; the Hextech-vs-Terminal palette pick resumes against the landscape hub |

### PARKED WORK (built this session, UNMERGED in worktrees)
- Theme candidates (Hextech-Unified + Deep Terminal, unified chrome, ds_statcheck fix, ?theme seam,
  4 comparison renders). Palette PICK deferred (operator pivoted before choosing).
- Overlay pseudo-screen (tools/pseudo_screen_overlay.py + fixtures + main.js seam). Decided infra.
- .rofl q2400 backfill (core/rofl_stats_backfill.py + CLI + 7 tests). Live --commit pending post-merge.
All await: verifier gate + git show --stat check + merge. Competitor apps left installed/logged-in on
Legion (operator's to keep or remove via Revo).

## Build tracks status (2026-07-22) - all in worktrees, UNMERGED (holding until theme agent done)

- **Overlay pseudo-screen: BUILT + rendered.** `tools/pseudo_screen_overlay.py` (committed harness,
  modes sr/aram/mayhem/complete), fixtures `active_match_aram_mayhem.json` +
  `active_match_complete.json`, `main.js` `_amMockUrl` 2-line seam. SR HUD rendered 7 widgets @
  2560x1440. Finding: `aram_balance.js:46` `_AB_ARAM_MODES={"aram","kiwi"}` already covers Mayhem
  (mode "aram") - no panel edit. Defect B#3: the finished-build state shows a "will render mid-game"
  PLACEHOLDER (not literally bare headers) - that placeholder is the real UX bug. Caveat: live :8888
  serves MAIN, so new fixtures render only post-merge.
- **.rofl q2400 backfill: BUILT (code+tests, live DB untouched).** `core/rofl_stats_backfill.py`
  +`backfill_tracked_summary` (UPDATE tracked_* where NULL, Riot-ID join, never puuid, never touches
  queue_id) + closed net-new tracked_* hole; `tools/rofl_tracked_backfill.py` CLI (--commit gated,
  dry-run default); 7 new hermetic TDD tests PASS. Agent claims the other 13 fails are a 0-byte-DB
  worktree artifact that pass on Legion main - VERIFY at merge, do not trust. Live --commit backfill
  runs AFTER merge (recovers ~15 of 120 NULL-tracked rows that have an archived .rofl).
- **Theme candidates: IN FLIGHT** (Hextech-Unified + Deep Terminal, unified chrome, ds_statcheck fix,
  ?theme swap seam, comparison renders of Home+Session under both).

Merge order when theme lands: verify each with `git show --stat` (staged-deletion guard), verifier
gate, then merge overlay + rofl (disjoint) + theme; run live --commit rofl backfill; render faithful
comparison for the operator's palette pick.
