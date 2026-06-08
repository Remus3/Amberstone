# Post-Game Review reframe - S2 design spec

Status: DESIGN (item 275, 2026-06-02). No UI code shipped in this pass.
Implements stage S2 of the s220 aggregator-G-style single-match Post Game Review
reframe. Each stage (S2-S5) is its own session plus the per-page UI-audit
ritual (`feedback_phase3_fixture_ritual`).

## Goal

Reframe the per-match Post Game Review (current `web/js/panels/last_match.js`
`renderLastMatch`, dashboard pages #14/15/16 SR/ARAM/Arena) into a richer
aggregator-G-style single-match layout: a hero performance band, a "phases that
mattered" win-probability graph, a lane/role comparison, and the full build
(items + skills + runes + spells) annotated with RC's local WPA lenses.

Every data source is LOCAL: `data/rewind_history.db` + the WPA model. Zero
Claude calls, zero live Riot dependency. This is a presentation/compose
effort over already-shipped engines, NOT new scoring from scratch.

## Existing assets (verified live 2026-06-02 - do NOT rebuild)

| Asset | Route / module | What it gives the reframe |
|---|---|---|
| Per-match teams + stats | `/api/last-match` (`routes_last_match.py`) | The current PGR payload: both rosters, KDA, items, grade, the tabbed render |
| 0-100 performance score | `/api/post-game-rubric` (`routes_post_game_rubric.py`) `total_score` | Role-weighted component rubric (cs / vision / kda / objectives) + per-component breakdown. A 0-100 ALREADY EXISTS - reconcile, do not re-pitch building one |
| Win-prob "phases that mattered" | `/api/post-game-wpa` (`routes_post_game_wpa.py`) | Per-frame team win-probability curve over the match (the WPA model walked frame by frame) - the aggregator G "what swung the game" graph |
| Item-WPA | `/api/item-wpa` (`core/item_wpa.py`) + Build Insights view (item 273 G) | Per-completed-legendary selection-bias-corrected residual over the corpus |
| Skill-WPA | `/api/skill-wpa` (`core/skill_wpa.py`, item 275) | Per-(champion, first-maxed basic Q/W/E) residual - the skill-order lens |
| Raw loadout | `participants` table (`rewind_history.db`) | Per-participant runes (`perks_json` / `rune_keystone_id` / `rune_*`), summoner spells (`summoner1_id`/`summoner2_id`), augments (`player_augment1..6`), skill casts, full damage split |
| Shrink primitive | `core/smoothed_rates.shrink` | Laplace/confidence damping shared by both WPA lenses |

NOTE on the "0-100 deferred to ROADMAP-S3" Settled line: that referred to a
NEW aggregator-G-style headline score. The `routes_post_game_rubric` `total_score`
(a role-weighted STAT rubric) is a DIFFERENT, already-shipped number. S2 must
DECIDE whether the hero band reuses `total_score` as-is, blends it with a
WPA-derived term, or introduces a new headline (open decision below).

## Proposed S2 layout (aggregator-G-style, single match)

Top-to-bottom, one scrollable single-match view (reusing the existing
`#view-...` PGR routing + the v2.1 token system):

1. HERO BAND - operator champion + result + the headline 0-100 score (big),
   role-percentile chip, KDA, one-line verdict. Source: `/api/last-match`
   hero block + `/api/post-game-rubric` `total_score` + per-component bars.
2. WIN-PROB GRAPH - the "phases that mattered" curve from `/api/post-game-wpa`,
   x = game time, y = team win-prob, annotated with the swing events
   (kills/objectives the WPA model already attributes). The aggregator G headline.
3. LANE / ROLE COMPARISON - operator vs lane opponent (same `team_position`):
   gold@N, cs@N, damage, KP. Source: `participants` + `timeline_frames`.
4. BUILD STRIP - items (with each completed legendary's item-WPA residual as
   a small +/- pp chip from `/api/item-wpa`), skill max-order (with the
   first-maxed-basic skill-WPA chip from `/api/skill-wpa`), runes + summoner
   spells (descriptive, no WPA - they have no purchase-frame; see item 275).
5. TEAM SCOREBOARD - both rosters (the existing `lm-tc-*` table), kept.

The item-WPA / skill-WPA chips are the CONNECTIVE tissue that ties RC's
corpus lenses into the single-match view: "you maxed W first (career +4.2pp)
and bought Item X (career +3.1pp)".

## Staging

- S2 SHIPPED (item 275, `77c3cc3`): hero band 0-100 (`_setHeroScore`) +
  phases-that-mattered cards (`post_game_phases.js`) were already present from
  s220; the genuinely-missing piece was the "your build, graded by your career"
  WPA strip - `web/js/panels/pgr_build_wpa.js` composing career item-WPA +
  skill-WPA chips on the reviewed match's loadout, mounted under the hero.
- S3 SHIPPED: win-prob "phases that mattered" GRAPH -
  `web/js/panels/pgr_winprob.js` draws an inline-SVG team win-probability curve
  over game time (50% baseline, ally/enemy area shade, the top swing phases as
  annotated dots with mm:ss + signed-pp tooltips) from `/api/post-game-wpa`.
  team100 win-prob is mirrored to the operator's perspective via
  `enriched.team_id` (tracked_side is null in the live payload). Mounts in the
  AI Analysis tab next to the phases cards; fail-soft hidden on event modes /
  no timeline. `?ui_mock=1` -> `web/data/ui_mock/pgr_winprob.json`.
- S4 SHIPPED: lane / role COMPARISON - `web/js/panels/pgr_lane_compare.js`
  pairs the operator to the same-role enemy by Riot participant-slot convention
  (pid i <-> i +/- 5; the payload has NO `team_position`) and compares FINAL
  gold / cs / damage / kill-participation as head-to-head split bars. @N
  (gold@10 / cs@10) is DEFERRED honestly - the payload's `timeline.series` is a
  team-aggregate diff, not per-participant, so there is no per-player frame to
  source @N from (noted in the panel js comment). Mode-aware: hides for ARAM /
  Arena (no lane pairing). Mounts in the Build tab; `?ui_mock=1` ->
  `web/data/ui_mock/pgr_lane_compare.json`.
- S5 augment loadout variant SHIPPED (`web/js/panels/pgr_loadout.js`, wired
  last_match.js:50/442, mount index.html:1753): mode-aware descriptive loadout
  strip - SR/ARAM show the rune page, Arena shows the 6 picked augments instead
  of runes (spec line 85). Descriptive only, no WPA. `?ui_mock=1` fixtures per
  mode.
- S5 per-player @N SHIPPED (PGR1, commit c162e5bd): `_enrich_match_timeline`
  now emits an `at_n` per-participant snapshot (gold + cs from the Match-V5
  timeline frame nearest 10 min; sub-10-min games fall back to the last frame)
  and `_fold_at_n_into_roster` copies gold_at_n/cs_at_n/at_n_minute onto each
  roster row. `pgr_lane_compare.js` leads the card with gold@N / cs@N
  head-to-head rows when both me + opponent carry the snapshot, degrading to
  final-stats-only otherwise. The S4 "@N deferred - no per-participant
  timeline" note is RESOLVED (the team-aggregate series was a reducer choice,
  not a data gap - the raw frames always had per-participant gold/cs).
- S5 remaining (minor, FUTURE): responsive polish + a dedicated per-page audit
  pass. ARAM/Arena lane-compare stays hidden by design (no role slots), so the
  @N row is SR-shape only.

## Open decisions for S2 (operator-gated, surface at S2 start)

1. Headline score = `routes_post_game_rubric.total_score` as-is, OR a blend
   that folds a WPA-derived performance term. (Recommend: reuse `total_score`
   for S2, leave a blend to S3 once the win-prob graph is in.)
2. Per-page vs single richer page: keep the SR/ARAM/Arena split (3 pages) or
   one adaptive page. (Recommend: one adaptive page, mode-conditional blocks
   for augments/runes - mirrors the item-180 Arena 6x2 honesty.)
3. Whether the build-strip WPA chips fetch per-render (cached routes, ~1.2s
   cold) or are precomputed into the `/api/last-match` payload. (Recommend:
   per-render with the existing 5-min route caches; the corpus lenses are
   stable, the cache covers it.)

## Honest constraints

- All WPA lenses (item + skill) are DESCRIPTIVE personal-corpus residuals,
  NOT meta winrates and NOT redistributable. The chips must carry the same
  honest caption the Build Insights view already uses.
- Runes / summoner spells have no purchase-frame, so they get a descriptive
  display only (no WPA residual) - do NOT fabricate a runes-WPA number
  (item 275 verify-first established the ~0.5-baseline degeneracy).
- min_n + shrink stay load-bearing on every chip; a low-N item/skill must
  render its residual muted (or omit the chip), never as a confident number.
