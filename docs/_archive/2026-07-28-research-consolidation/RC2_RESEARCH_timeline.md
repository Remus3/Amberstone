# RC 2.0 Phase-1 Research - Stage 1.8: TIMELINE-BREAKDOWN references

Grounded, cited survey of how match-stats tools visualize match TIMELINES, and what
of it is legally liftable into Riot Commander's stdlib-Python + vanilla-JS dashboard.

ASCII only. No em/en dashes or smart quotes (repo hard rule). Cite-first.

- Author pass date: 2026-06-19
- Scope: gold/XP-diff-over-time line graphs, lane state at 10/15, teamfight timelines,
  objective/kill event markers, power-spike windows, "where the game was lost" narratives.
- Method: WebSearch/WebFetch over league-of-graphs / aggregator G / aggregator A / aggregator C +
  general time-series data-viz best practice. Repo grep for the live timeline surface.
  Several .gg pages return HTTP 403 to automated fetch; those patterns are sourced from
  secondary write-ups + the publicly-documented behavior, flagged inline where so.

---

## 0. RC's CURRENT timeline surface (ground truth from repo)

RC is FURTHER ALONG than "none/minimal". It already has a hand-rolled inline-SVG
charting layer and a normalized Match-V5 timeline store. There is NO external charting
library anywhere in `web/` (grep for chart.js/d3/plotly/uplot/echarts/highcharts = 0 hits).
Everything is authored `<svg>` + `<polyline>` + `<path d=...>` strings built in JS.

What exists today:

| Surface | File:line | What it renders |
|---|---|---|
| Win-probability curve (PGR) | `web/js/panels/pgr_winprob.js:203-215` | Inline `<svg viewBox>` + `<polyline class="pwp-line">`; area split above/below the 50% midline; swing-event dots. The one real "timeline graph" RC ships. |
| WPA swing-phase cards | `web/js/panels/post_game_phases.js` | Top-3 game-swinging moments as TEXT cards (kill/tower/baron + WPA delta + prob transition). No graph. |
| Replay event ribbon panel | `web/js/panels/replay_events.js` | Consumes `/api/replay/events`; event list for the replay/scrubber page. |
| Per-minute perf curve | `web/js/panels/perf_curve.js` | Win-vs-loss `<polyline>` of gold or CS per minute across the rewind corpus. |
| Composite OP-score curve | `web/js/panels/op_score.js` | Win-vs-loss per-minute composite 0-100 line. |
| Power-spike sparkline | `web/js/panels/spike_curve.js` | 40px ally/enemy combat-strength-vs-minute sparkline, "now" marker, spike peaks. |
| Diff sparklines | `web/js/panels/last_match.js` (`_tlSparkline`) | 100x40 gold/XP/CS diff sparklines via `<path d>` area+line. |

Python data + routes that already feed time-series:

| Module | File | Role |
|---|---|---|
| Rewind timeline store | `data/rewind_history.db` | 5 tables; `timeline_frames` (per-minute per-participant) + `timeline_events` (discrete). ~2900 matches. |
| Replay read API | `core/replay_history.py` -> `dashboard/routes_replay_events.py` | `GET /api/replay/events?match_id=...` serves CHAMPION_KILL / BUILDING_KILL / ELITE_MONSTER_KILL / TURRET_PLATE_DESTROYED. |
| WPA trainer/scorer | `core/post_game_score.py` -> `dashboard/routes_post_game_wpa.py` | `GET /api/post-game-wpa` returns per-event win-prob deltas + ranked top phases. |
| Match-V5 timeline enrich | `dashboard/builders_lcu_enrich.py` | Parses `/timeline` into gold/xp/cs differential series + at-N snapshots. |

### The exact Match-V5 timeline shape RC has (verified by live DB query)

`data/rewind_history.db`, normalized from the raw Match-V5 `/matches/{id}/timeline`:

- `timeline_frames`: one row per (frame, participant). Interval ~60000 ms (1 min;
  Riot boundary jitter ~+/-110 ms). Columns: `timestamp_ms`, `participant_id`,
  `current_gold`, `total_gold`, `gold_per_second`, `xp`, `level`, `minions_killed`,
  `jungle_minions`, `pos_x`, `pos_y`, `time_enemy_cc_spent`, plus full
  `*_dmg_done` / `*_dmg_taken` / `total_healed` / `self_mitigated`.
- `timeline_events`: one row per discrete event. Types present include CHAMPION_KILL,
  CHAMPION_SPECIAL_KILL, ELITE_MONSTER_KILL, BUILDING_KILL, TURRET_PLATE_DESTROYED,
  ITEM_PURCHASED/SOLD/DESTROYED/UNDO, LEVEL_UP, SKILL_LEVEL_UP, WARD_PLACED/KILL,
  DRAGON_SOUL_GIVEN, GAME_END. Combat rows carry `killer_id`, `victim_id`,
  `assisting_ids_json`, `bounty`, `kill_pos_x/y`, and a `victim_damage_json` breakdown.
  Monster rows carry `monster_type` (DRAGON/BARON/RIFT_HERALD/HORDE/ATAKHAN) +
  `monster_subtype` (INFERNAL/MOUNTAIN/CLOUD/...). Building rows carry `building_type`,
  `lane_type`, `tower_type`, `team_id`.

Implication: every data primitive needed for gold/XP-diff lines, an objective/kill
event ribbon, lane-state-at-10/15, teamfight clustering, and power-spike bands is ALREADY
in the DB. The gap is almost entirely the FRONT-END timeline view, not the data layer.

---

## 1. External pattern survey

### Pattern A - Gold/XP differential-over-time line (the canonical view)

- **WHAT.** A single line over the match time axis showing one team's lead: gold diff
  (team gold minus enemy gold) and, on a toggle, XP diff. Zero is the meaningful center;
  above zero = your team ahead, below = behind. Riot's own client match-history gold graph,
  league-of-graphs, aggregator A, and aggregator G all ship a version. aggregator A explicitly lets you
  "compare gold, experience, and objective data for both teams" on the match detail page
  (aggregator A help center). Riot client shows "champion kills, deaths, assists, total gold,
  and final builds" plus the gold-diff graph.
- **HOW.** Per-minute samples (Match-V5 `participantFrames[].totalGold` / `.xp`, summed per
  team, differenced) -> a line, very commonly an AREA filled toward the zero baseline and
  color-split by sign (diverging RdBu-style: one hue above, one below, neutral at zero).
  Diverging color with a labeled center line is the documented best practice for
  "meaningful zero / profit-vs-loss" data (Wilke, Datylon, Domo).
- **RC HAVE?** Data: YES. `timeline_frames.total_gold` + `.xp` per participant, plus
  `builders_lcu_enrich.py` already derives gold/xp/cs differential series. Render: PARTIAL.
  The split-area-around-a-midline technique already exists for win-prob at
  `web/js/panels/pgr_winprob.js:143` (area split by clipping the polyline against the
  midline) and the diff sparkline at `last_match.js` (`_tlSparkline`). No full-size,
  axis-labeled gold-diff chart yet.
- **WHERE.** New PGR sub-panel mounted from `web/js/panels/last_match.js`, fed by a thin
  new route over `core/replay_history.py` (or extend `routes_post_game_wpa.py`); reuse the
  `pwp-svg` split-area pattern + `pgr_winprob.css`.
- **EFFORT+RISK.** LOW-MED. Data + a near-identical render idiom already in repo. Risk:
  team-side perspective flip (already solved in pgr_winprob.js for team 100 vs 200 - copy
  that logic, do not re-derive).
- **LIFT: HIGH.** Highest value-to-effort item. Reimplements a ubiquitous, legally-generic
  chart on data RC already stores, using an SVG idiom RC already wrote.

### Pattern B - Objective + kill EVENT RIBBON on the time axis

- **WHAT.** A horizontal strip aligned to the same time axis as the gold line, with marker
  glyphs at event timestamps: kills (colored by team), tower/inhib falls, dragon (by
  element), herald, baron, soul. Both teams above/below a center rail. This is the standard
  companion to the gold graph on aggregator A / aggregator G / league-of-graphs and on pro broadcasts.
- **HOW.** Place a marker at `x = event.timestamp / gameDuration`. Glyph + color encode
  type/team. Hover -> tooltip (who/what/when, bounty). Annotating significant events with
  markers + tooltips is the explicit time-series best practice (chartmakers.io, usefuldatatips).
- **RC HAVE?** Data: YES, fully. `timeline_events` has every type with `timestamp_ms`,
  team, sub-type, and `kill_pos_x/y`; `/api/replay/events` already serves the strong-event
  subset and `replay_events.js` already consumes it. Aligned-ribbon render: NO.
- **WHERE.** Render the ribbon directly under the Pattern-A gold chart in the PGR (shared x
  scale). Source = existing `/api/replay/events`; presentation layer = new SVG marker row,
  extend `replay_events.js` or a sibling panel.
- **EFFORT+RISK.** LOW. The API and consumer exist; this is pure presentation (position +
  glyph + tooltip on a shared scale). Risk: glyph asset sourcing - use simple shapes/letters
  (no Riot art) to stay clean.
- **LIFT: HIGH.** Cheap, high-readability, and it makes the gold line legible ("the line
  dropped HERE because Baron"). Pairs with A as one shipped slice.

### Pattern C - Lane state at fixed minutes (gold/XP/CS diff @10 and @15)

- **WHAT.** Per-lane snapshot rows at canonical breakpoints (the laning-phase 10/14/15-min
  marks): your gold/CS/XP vs your lane opponent, as a +/- number and/or a small diverging
  bar. league-of-graphs and aggregator A lean on "@10 / @15" lane-diff as the standard laning grade.
- **HOW.** Pick the frame nearest 600000 / 900000 ms, diff the matched-role participants.
  Diverging horizontal bars from a zero center; label the center (best practice for
  meaningful-zero data, Wilke/Domo).
- **RC HAVE?** Data: YES - frames carry per-participant gold/xp/cs and roles are derivable;
  `builders_lcu_enrich.py` already computes at-N snapshots, and a `pgr_lane_compare.js`
  panel already does FINAL-state lane comparison. Time-sliced @10/@15 view: PARTIAL (final,
  not the timed breakpoints; check whether `pgr_lane_compare.js` already exposes an at_n).
- **WHERE.** Extend `pgr_lane_compare.js` to accept a minute breakpoint; reuse its row layout.
- **EFFORT+RISK.** LOW-MED. Mostly a frame-selection + diff query; UI row already exists.
  Risk: role/opponent matching for ARAM/Arena (no lanes) - gate to SR.
- **LIFT: HIGH.** Small surface, strong coaching signal, reuses an existing panel.

### Pattern D - Power-spike windows / "game flow" bands

- **WHAT.** Early/mid/late phase bands plus markers for when a champ/team is strongest
  (item/level spikes). Aggregator C is the reference: power spikes are organized across
  early/mid/late phases as "typical expectations for activities and flow", with live
  spike notifications and a gold/XP lead feed (aggregator C blog).
- **HOW.** Shaded vertical regions behind the gold line for phase windows; tick markers at
  spike timestamps (2-item, level 6/11/16). Shaded regions + reference lines to mark
  periods is documented best practice (usefuldatatips, chartmakers.io).
- **RC HAVE?** Adjacent: YES. `spike_curve.js` already plots an ally/enemy combat-strength
  curve with spike-peak triangles + a "now" marker; the Daemon Slayer engine computes
  real per-champ power. Post-game phase-band overlay on the match timeline: NO.
- **WHERE.** Background `<rect>` bands + spike ticks layered under the Pattern-A chart;
  band boundaries from item/level timestamps in `timeline_events`. DS supplies spike timing.
- **EFFORT+RISK.** MED. Defining "the spike moment" per champ is judgment; phase bands
  (0-14 / 14-25 / 25+) are trivial, spike ticks need a DS hook.
- **LIFT: MED.** Phase bands LOW/HIGH-value; precise power-spike ticks MED (DS dependency).
  Ship bands first, ticks later.

### Pattern E - "Where the game was won/lost" narrative (aggregator G Story)

- **WHAT.** An auto-generated narrative of the few pivotal moments and the single biggest
  swing, anchored to the timeline. aggregator G markets "Story" / AI-Score and "AI-driven
  insights reveal match flow"; aggregator A has a timeline OP-Score with keyworded moments.
- **HOW.** Rank events by win-prob impact, surface the top few as captioned markers/cards on
  the timeline ("Baron at 24:30 -> +18% win prob"). This is data storytelling: annotate the
  key events to focus attention (chartmakers.io, evalacademy).
- **RC HAVE?** YES, essentially the whole engine. `core/post_game_score.py` computes WPA
  per event; `/api/post-game-wpa` returns ranked `top_phases`; `post_game_phases.js`
  already renders them as cards and `pgr_winprob.js` already dots the swing moments on the
  curve. RC arguably already SHIPS a basic version of this pattern.
- **WHERE.** Connect the existing phase cards to the new gold chart + ribbon (click a card
  -> highlight that x on the timeline). Mostly wiring of parts that all exist.
- **EFFORT+RISK.** LOW. No new model; it is integration + a caption string. WPA is an RC
  heuristic with no Claude/Riot dependency (consistent with the planned PGR-reframe scope).
- **LIFT: HIGH (as integration).** Glue, not greenfield. Turns separate panels into one
  coherent "story" surface.

### Pattern F - Teamfight timeline (kill clustering)

- **WHAT.** Group nearby kills into teamfights and mark each fight on the axis with a
  win/loss + net-kill outcome (a coarser ribbon than per-kill).
- **HOW.** Cluster CHAMPION_KILL rows by time-proximity (e.g. within ~20s), tally
  team kills, place a sized/colored marker per fight.
- **RC HAVE?** Data: YES (kill timestamps + teams + `kill_pos_x/y` in `timeline_events`).
  Clustering logic: NO.
- **WHERE.** A derived layer over `/api/replay/events`; could be its own ribbon row or a
  toggle on Pattern B.
- **EFFORT+RISK.** MED. Clustering heuristic + outcome scoring is net-new (small) code.
- **LIFT: MED.** Nice once B exists; defer behind A/B/C.

### Pattern G - Map heatmap of deaths/kills (position)

- **WHAT.** A minimap scatter/heatmap of where kills/deaths happened.
- **HOW.** Plot `kill_pos_x/y` onto a Summoner's Rift image, normalized to map bounds.
- **RC HAVE?** Data: YES (`kill_pos_x/y` and per-frame `pos_x/y`). Render: NO. Note: this
  is POSITION, not a time axis - adjacent to the brief but not a timeline chart, and the
  map-image asset has licensing nuance.
- **EFFORT+RISK.** MED-HIGH (asset + coordinate calibration).
- **LIFT: LOW.** Out of the time-series scope; park it.

---

## 2. Charting technology - lightweight options for a no-build, vanilla-JS dashboard

RC ships zero charting deps today and authors SVG by hand. Findings:

- **Stay hand-rolled SVG (RECOMMENDED for A/B/C/E).** RC already has the exact idioms:
  split-area-around-a-midline (`pgr_winprob.js:143-215`), diff sparkline `<path d>`
  (`last_match.js`), per-minute `<polyline>` (`perf_curve.js`, `op_score.js`). A gold-diff
  chart + event ribbon are squarely within what these already do. Zero new dependency, zero
  build step, fits ADR-008 asset-hash auto-reload, and matches the existing visual language.
  This is the lowest-risk path and what the bulk of the lift should use.
- **uPlot - the one external option worth knowing.** Canvas2D, MIT license, NO dependencies,
  ~47-50 KB minified single IIFE file (drop-in `<script>`, no build tooling), handles
  100k+ points and live streaming cheaply (uPlot README/repo). It is purpose-built for
  time-series lines. It would only earn its keep if RC later wants dense interactive
  multi-series charts (e.g. all 10 players' gold, smooth zoom/pan) where hand-SVG gets
  unwieldy. For the Phase-1 PGR scope it is OVERKILL - note it as a FUTURE option, do not
  pull it in now.
- **Others considered, not recommended now.** Chart.js (~60 KB, canvas, good mid-ground but
  a real dep + config surface); Chartist / SVG.js (small, SVG, but still a dep RC does not
  need given its existing SVG code); d3 (powerful, heavy, build-oriented - wrong fit for a
  no-build vanilla dashboard). (Sources: fusioncharts/luzmo/medium 2026 charting roundups.)

Verdict: **Reuse RC's own SVG layer for the timeline brief. Keep uPlot on the shelf** for a
possible future dense-interactive pass only.

---

## 3. Data-viz best-practice cheatsheet (apply to all timeline panels)

Distilled from the time-series / diverging-color sources:

- One message per chart; structure the data to the message first (Metabase).
- Diverging color around a LABELED zero center for the gold/XP diff and lane-diff bars -
  one hue above, one below, neutral at zero; intensity grows with magnitude (Wilke "Color
  basics", Datylon, Domo). Reuse RC's ally/enemy palette so red/blue stays consistent.
- Annotate key events with markers + tooltips; do not clutter - call out only the pivotal
  ones (the ribbon shows all; the "Story" captions only the top few) (chartmakers.io,
  usefuldatatips, evalacademy).
- Shaded regions / reference lines to mark periods (phase bands, the @10/@15 breakpoints)
  (usefuldatatips, chartmakers.io).
- Share ONE x time-scale across the gold chart, the event ribbon, and the power bands so
  they read as a single coherent timeline.

---

## 4. Recommended Phase-1 slice (build order)

1. **Pattern A** gold/XP-diff chart (HIGH) - reuse `pgr_winprob` split-area idiom on
   `timeline_frames` data; new PGR sub-panel + thin route.
2. **Pattern B** objective/kill ribbon (HIGH) - present existing `/api/replay/events` on A's
   shared x-scale.
3. **Pattern E** "Story" wiring (HIGH) - link the existing WPA `top_phases` cards to A+B
   (click-to-highlight); no new model.
4. **Pattern C** lane @10/@15 (HIGH) - extend `pgr_lane_compare.js` with a minute breakpoint.
5. **Pattern D** phase bands (MED) then power-spike ticks (MED, DS hook).
6. **Pattern F** teamfight clustering (MED), **Pattern G** map heatmap (LOW) - defer.

Each PGR page change must run the per-page UI-audit ritual BEFORE commit (CLAUDE.md rule).

---

## 5. Sources

- Aggregator A - Viewing detailed match data (help center): https://aggregator-a.invalid/help/articles/31091817743129-Viewing-detailed-match-data
- Aggregator A - timeline OP Score keywords: https://aggregator-a.invalid/help/articles/38185639004569-What-do-the-timeline-OP-Score-keywords-mean
- AGGREGATOR G Story / AI-Score: https://aggregator-g.invalid/story  and  https://m.aggregator-g.invalid/
- Aggregator C - power spikes / game flow: https://aggregator-c.invalid/blog/how-to-understand-power-spikes-using-aggregator-c/
- Aggregator C - overlay / live companion (gold-lead, spike feed): https://aggregator-c.invalid/blog/lol-how-to-use-aggregator-c-overlay-live-companion/
- Aggregator H (stats coverage / map control / per-minute): https://aggregator-h.invalid/
- LeagueMath - mapwide gold and XP: https://www.leaguemath.com/mapwide-resources-gold-xp/
- Line charts / time-series best practice: https://chartmakers.io/blog/line-charts-time-series-data  ·  https://usefuldatatips.com/tips/visualization/line-chart-best-practices  ·  https://www.metabase.com/blog/how-to-visualize-time-series-data  ·  https://www.evalacademy.com/articles/data-visualization-applications-line-charts
- Esports data-viz overview: https://www.numberanalytics.com/blog/data-visualization-esports-game-analytics
- Diverging color scales / meaningful zero: https://clauswilke.com/dataviz/color-basics.html  ·  https://www.datylon.com/resources/chart-library/diverging-bar-chart  ·  https://www.domo.com/learn/charts/divergent-bar-charts
- uPlot (size/deps/license/perf, drop-in): https://github.com/leeoniya/uPlot
- 2026 JS charting roundups (uPlot/Chart.js/visx sizing): https://www.fusioncharts.com/blog/best-javascript-charting-libraries/  ·  https://www.luzmo.com/blog/javascript-chart-libraries
- Concept reference (gold-diff timeline UI): https://dribbble.com/shots/24169430-League-of-Legend-Gold-Diff-Timeline

Note: aggregator G, aggregator A article bodies, and some aggregator C pages returned HTTP 403 to
automated fetch; their documented behaviors above are drawn from the reachable help-center
text + secondary write-ups and are flagged where the primary page was not machine-readable.
