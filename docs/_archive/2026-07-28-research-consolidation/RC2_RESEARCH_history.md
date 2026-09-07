# RC 2.0 Phase-1 Research (stage 1.7) - HISTORY / Match-List UX

Topic: match-history list UX across aggregator A, Aggregator B, league-of-graphs, aggregator G, Overlay App E.
Goal: distill scannable long-list patterns that a LOCAL single-player tool (RC, one
account, ~2846 matches in `data/rewind_history.db`) can legally re-implement.

ASCII only. No em/en dashes or smart quotes (repo hard rule). All "does RC HAVE
it" cites are grep-verified file:line against the live tree on 2026-06-19.

---

## 0. RC's CURRENT history surface (ground truth)

RC has a 3-card History view, NOT a flat scrollable match list. Structure:

- View shell + 4 scope tabs (14 Days / Whole Season / Prior Season / Whole DB):
  `web/index.html:1240-1269` (`#view-history`, `#history-scope-tabs`).
- Fetch + render: `web/js/main.js:1781-1956`.
  - Left card = SESSIONS list, one row per play-session:
    `main.js:1794-1811` renders `date | <N>g | <duration>m`.
  - Middle card = MATCHES for the selected session:
    `_historyRenderMatches` `main.js:1895-1917` renders one li per match as
    `[grade] champion - mode | KDA | timestamp`.
  - Right card = SEASON STATS (total / avg KDA / most-played / WR-needs-key):
    `index.html:1260-1266`, populated `main.js:1813-1817`.
- API: `GET /api/history?scope=` -> `dashboard/routes_history.py:40-49` ->
  `_build_history` `dashboard/builders.py:149-202`.
- Row/session field shape from the DB loader `_load_match_rows`
  `builders.py:33-63`: per match RC already has timestamp, mode, champion,
  grade, kda_str, duration_s, kills, deaths, assists, label.
- Session grouping = a real gap-based sessionizer `_group_sessions`
  `builders.py:75-100` (closes a session at `SESSION_GAP_S`); per-session
  aggregate `_agg_session` `builders.py:103-135` already computes games,
  started/last, time_played, total+avg KDA, grade histogram, mode histogram,
  and a per-champion games/KDA list.
- Click-through: a match row deep-links to a detached read-only "historical PGR"
  (full single-match scoreboard) keyed on the row timestamp:
  `_wireMatchRowToHistoricalPgr` `main.js:1926-1943` ->
  `web/js/panels/historical_pgr.js` (renders hero + stats grid + both rosters
  with per-row MVP/SVP score chips, `historical_pgr.js:264-365`).
- Deep-link focus: Home "Recent 5" and "Tonight's Pick" can jump into History
  and highlight a specific match row / champion (`main.js:1819-1891`).
- Two DBs: live `data/match_history.db` (fresh, RC-written, feeds History) and
  `data/rewind_history.db` (~2846 full Match-V5 matches, feeds Season totals
  only today). Live writer `lib/rewind_live_writer.py` backfills rewind ~90s
  post game-end. Scraper schema `scripts/rewind_scraper.py:81-116` (matches +
  participants + teams + timeline tables, queue/patch/champion indexed).

RC's GAPS vs the reference sites (what this doc targets):
1. No win/loss visual signal on a match row (no result border, no W/L color) -
   RC shows grade + KDA but the row never says "did I win". `kda_str` + grade
   only; win lives in rewind/enriched, not the History row.
2. No flat "last N games" scannable strip (W/L pip trail, recent-form sparkline).
3. No in-list expand (every detail click leaves the list for a separate view).
4. No filtering at all (no champion / queue / role / win filter on the list).
5. Per-row payload is text-heavy (champion - mode | KDA | timestamp), no item
   icons, no CS, no per-game color-coding, no multikill/grade-as-pip.
6. The rich rewind_history.db (2846 matches, items, CS, queue, win) is almost
   unused by the History surface - only an aggregate COUNT/AVG query touches it.

---

## 1. Reference patterns (the dominant industry shape)

Cross-site finding: aggregator A is the canonical match-history list; Aggregator B, league-of-
graphs, aggregator G and Overlay App E are variations on the same row anatomy. The shared
grammar of a scannable LoL match row is:

  [win/loss color block] [champ icon + level] [summoner spells + 2 runes]
  [KDA big + ratio small, color-coded] [CS + CS/min] [KP%] [vision]
  [6 item slots + trinket] [queue + time-ago] [expand caret]

aggregator A's recent-games block shows the last 20 matches with color-coded KDA, CS
per minute, vision score, and damage dealt; each row links to a full match page
with item builds, skill order, gold timeline, and teamfight participation
(Wombo Combo Aggregator A guide). The win/loss state is conveyed by row color-coding.

Below: each pattern gets the 6-point LIFT checklist
(WHAT / HOW / RC-HAS / WHERE / EFFORT+RISK / VERDICT).

---

### P1. Result-first compact row (win/loss color + KDA + champ)

- WHAT: The single most important scannability primitive. A blue (win) / red
  (loss) left block or row tint lets you read W/L down a column in one pass,
  with champion icon, color-coded KDA (green good / red feeding), and queue.
- HOW: Left border / background tint keyed on win bool; KDA colored by ratio
  thresholds; fixed-width columns so the eye tracks vertically. aggregator A, Aggregator B,
  league-of-graphs, aggregator G all use this exact left-color convention.
- RC HAVE IT? PARTIAL-NO. Row markup is `[grade] champ - mode | KDA | ts`
  (`main.js:1907-1910`) with NO win signal. RC DOES have a grade pip class
  (`home-recent-grade`) and the win bool exists downstream
  (`historical_pgr.js:189` reads `enriched.win`) but the History row never
  surfaces it. Win is NOT in `_load_match_rows` output (`builders.py:52-59`).
- WHERE IT INTEGRATES: add `win` to the SELECT in `_load_match_rows`
  (`builders.py:44-47`; match_history.db) + propagate through `_agg_session`
  rows; tint the li in `_historyRenderMatches` (`main.js:1899-1915`) via a
  `data-result=win|loss` attribute + a CSS left-border rule.
- EFFORT+RISK: LOW. One column added to an existing SELECT, one dataset attr,
  one CSS rule. Risk: match_history.db must actually store win (verify column;
  rewind has `tracked_win`, `rewind_scraper.py:103`). Tier-1 (one builder + one
  panel), no engine touch.
- LIFT VERDICT: HIGH. Biggest scannability win for the least code; pure
  convention, no copied assets or markup.

### P2. Last-20 win/loss pip strip + recent-form summary

- WHAT: A horizontal trail of W/L pips (or a "12W 8L, 60%" chip) summarizing
  recent form above the list. aggregator A surfaces a "last 20 games" recent-games
  block; Overlay App E shows each player's "recent performance" before the game even
  starts (Wombo Combo Overlay App E review). Aggregator B keeps 6 months of summoner stats with
  KDA + champion pool you can filter by mode.
- HOW: Aggregate the most recent N (15-20) matches into wins/losses/WR + an
  avg-KDA, render as a compact pip row + one stat line. Optionally a tiny
  recent-form sparkline.
- RC HAVE IT? PARTIAL. RC already computes per-session grade + mode histograms
  and avg KDA in `_agg_session` (`builders.py:124-135`) and a Home 14d trend
  exists (`builders_home._home_trends_14d`, imported `builders.py:284-290`).
  But there is NO last-20 W/L strip on the History view; Season WR is stubbed
  "(needs Riot key)" (`index.html:1265`) even though rewind_history.db has
  `tracked_win` for 2846 matches.
- WHERE IT INTEGRATES: new tiny builder over rewind_history.db
  (`SELECT tracked_win ... ORDER BY game_creation_ts DESC LIMIT 20`) returned
  inside `_build_history` (`builders.py:149-202`, alongside `season_stats`);
  render a pip strip in the History head (`index.html:1241-1249`) and fill the
  real WR into `#history-season-wr` (`main.js` season block 1813-1817).
- EFFORT+RISK: LOW-MED. One SQL + one render block; replaces a known stub. Risk:
  rewind win is for the TRACKED player only (correct for a single-account tool).
  Tier-1.
- LIFT VERDICT: HIGH. Directly fills RC's "did I win / am I on a heater" gap and
  retires the "(needs Riot key)" placeholder using data already on disk.

### P3. Expand-in-place match detail (accordion row)

- WHAT: Clicking a row expands it INLINE to a full scoreboard (both teams, KDA,
  damage bars, items, build order, gold graph) without leaving the list. aggregator A
  rows expand to item builds + skill order + gold timeline + teamfight
  participation; the help center documents a detailed round/phase breakdown view.
- HOW: A caret toggles a hidden detail sub-panel under the clicked row; lazy-
  fetch the heavy detail on first expand; only one open at a time.
- RC HAVE IT? PARTIAL (different model). RC already renders a FULL single-match
  detail, but as a SEPARATE routed view (`#historical-pgr`,
  `historical_pgr.js`) reached by leaving the list (`main.js:1926-1943`). The
  detail payload already exists: `GET /api/last-match?match_ts=`
  (`historical_pgr.js:120`). RC has the data + the renderer; it lacks the
  inline-accordion presentation.
- WHERE IT INTEGRATES: in `_historyRenderMatches` (`main.js:1895-1917`) append a
  collapsed `<div class="match-detail" hidden>` per row; on click, fetch
  `/api/last-match?match_ts=` (already wired) and mount a slimmed historical_pgr
  render into it instead of (or in addition to) routing away.
- EFFORT+RISK: MED. Reuses the existing endpoint + most of historical_pgr's
  render fns, but needs an in-list mount target + one-open-at-a-time state +
  the "no clobber" discipline historical_pgr already documents
  (`historical_pgr.js:9-23`). Risk: layout/scroll jank in the middle card;
  Tier-1 but with the UI-audit ritual (web/* change).
- LIFT VERDICT: MED. High UX value and the backend is free, but it is a real
  front-end build (accordion + state) and RC's routed detail already covers the
  core need, so it ranks below P1/P2/P4.

### P4. List filtering (champion / queue / result)

- WHAT: Filter the list by champion, queue/mode, role, and win/loss. Aggregator B
  separates by Ranked Solo / Flex / Normal / ARAM and lets you filter the
  champion pool by mode (Aggregator C/Aggregator B); aggregator A statistics views filter by role.
- HOW: A filter bar (champion search + queue dropdown + W/L toggle) over the
  client-side list, or pushed into the query. For a local DB, queue and champion
  are already indexed (`rewind_scraper.py:113-115`:
  `idx_matches_queue`, `idx_matches_champion`).
- RC HAVE IT? NO for History. RC has ZERO filters on the History list. (It DOES
  have a champion filter on the separate Loadouts view, `main.js:1959-1972`, as
  a proven in-repo pattern to copy.) RC also already deep-links a champion focus
  INTO history (`rc-history-focus-champion`, `main.js:1822-1858`) - a filter is
  the natural generalization.
- WHERE IT INTEGRATES: add a filter bar to `#view-history` head
  (`index.html:1241-1249`); filter client-side in `_historyFetchAndRender`
  (`main.js:1786-1893`) since the scope payload is already fully in memory; or
  add `champion=`/`queue=` params to `_serve_history` (`routes_history.py:40-49`)
  backed by the existing indexes for the Whole-DB scope.
- EFFORT+RISK: LOW-MED. Client-side filter is trivial (data is already loaded);
  the Loadouts filter is a copy-paste template. Risk: filtering interacts with
  the session-grouping (filtering then re-grouping vs filtering within sessions);
  decide once. Tier-1.
- LIFT VERDICT: HIGH (champion + queue + W/L). Cheap, high-value for a 2846-match
  archive, and RC already ships the exact filter widget on another view.

### P5. Richer row payload (items, CS, per-game grade pip)

- WHAT: Put item icons (6 + trinket), CS / CS-min, and a per-game grade/score
  pip directly in the row. aggregator A rows carry CS/min, vision, damage; aggregator G and
  Aggregator C attach a per-game AI/performance score; the grade IS the at-a-glance
  quality signal.
- HOW: Render small item imgs + a numeric CS + reuse the existing grade pip;
  keep the row one line tall with fixed columns.
- RC HAVE IT? PARTIAL. RC has grade per row (`main.js:1906-1907`,
  `home-recent-grade` pip) and CS/items EXIST in rewind + in the historical_pgr
  detail (`historical_pgr.js:217` CS, `:334-338` item imgs, with a working
  DDragon item-icon helper `_itemImgTag` `historical_pgr.js:51-59`). The History
  ROW itself shows none of it (no items, no CS). The MVP/SVP per-game score
  heuristic already exists (`historical_pgr.js:369-396` `_rosterScores`).
- WHERE IT INTEGRATES: extend `_load_match_rows` SELECT (`builders.py:44-47`) or
  the rewind path to carry cs + item ids; render in `_historyRenderMatches`
  (`main.js:1899-1915`) reusing `_itemImgTag` (lift the helper out of
  historical_pgr into a shared lib).
- EFFORT+RISK: MED. The icon helper + grade pip are reusable, but match_history.db
  may not store per-match item ids (rewind does, via participants table); sourcing
  items means joining rewind. Watch row height / font floors
  (memory: font_size_viewing_distance). Tier-1.
- LIFT VERDICT: MED. Clear polish, but gated on which DB feeds the row and adds
  visual density that needs the UI-audit ritual; do after P1/P2/P4.

### P6. Session / day grouping with per-group summary header

- WHAT: Group matches into play-sessions or days with a header showing
  games + W-L + net result for the block, so a long list chunks into scannable
  runs. This is aggregator A/Overlay App E-style "today/recent" chunking.
- HOW: A gap-based sessionizer (2h idle gap is standard) with a header line per
  group: date, game count, W-L, avg KDA, champ mix.
- RC HAVE IT? YES - this is RC's strongest existing asset and BEATS the reference
  sites. `_group_sessions` (`builders.py:75-100`) is a real gap sessionizer;
  `_agg_session` (`builders.py:103-135`) already yields games / W?/ time /
  avg-KDA / grade-hist / mode-hist / per-champ. The session list IS the left card
  (`main.js:1794-1811`). Session-boundary rules are documented
  (memory: session_boundary_rules - 2h gap, span midnight).
- WHERE IT INTEGRATES: already integrated. The only gap: the session header
  shows `date | Ng | duration` but NOT W-L for the block (because win isn't
  loaded - see P1). Once P1 lands, add "Xw-Yl" to the session row
  (`main.js:1798-1800`) and the detail head (`main.js:1807`).
- EFFORT+RISK: TRIVIAL once P1 lands (one string concat). Tier-0/1.
- LIFT VERDICT: LOW (as new lift - mostly already done). Listed to confirm RC
  should NOT rebuild this; just enrich the header with W-L after P1.

### P7. Per-game performance score / grade as the scan key

- WHAT: A single 0-100 (op score) or letter grade per game, used as the primary
  quality glance and sortable. aggregator G = "AI-Score" per game; aggregator A = OP Score;
  Aggregator B/Aggregator C = a per-game rating.
- HOW: Compute a blended score (KDA, damage, gold, CS, vision, tanked) per game;
  show as a colored pill; optionally sort the list by it.
- RC HAVE IT? YES (heuristic). RC has a grade per match
  (`builders._load_match_rows` grade col) AND a 6-factor lobby-relative score
  heuristic (`historical_pgr.js:369-396`, weights 0.30 KDA / 0.28 dmg / 0.16
  gold / 0.12 cs / 0.08 vision / 0.06 tank). ROADMAP also tracks a deferred
  0-100 PGR score (CLAUDE.md "s220 PGR 0-100 score is deferred"). NO Claude/Riot
  dependency - it is an RC heuristic, which matches the op-score model exactly.
- WHERE IT INTEGRATES: the grade pip is already in the row (`main.js:1906-1907`).
  To go op-score-style, surface the numeric score (reuse `_rosterScores`) as the
  pip and allow sort-by-score in `_historyRenderMatches`.
- EFFORT+RISK: LOW-MED. Heuristic exists; making it the row's sort key is a small
  JS change. Risk: do not surface raw model/AI claims - keep it an honest local
  heuristic (matches RC's existing framing). Tier-1.
- LIFT VERDICT: MED. RC is already 80% here; promoting the existing score into
  the row + a sort toggle is the cheap delta.

---

## 2. Cross-cutting notes for a LOCAL single-player tool

- Single account simplifies everything: no region/summoner switching (the bulk
  of Aggregator B/aggregator A filter UI is multi-account plumbing RC can DROP). RC's filters
  should be champion / queue / result / role only.
- Data is already local + indexed: rewind_history.db has queue + champion
  indexes (`rewind_scraper.py:113-115`) and 2846 matches with win/items/CS, so
  every reference "recent 20 / WR / filter" pattern is a local SQL away with no
  network and no rate limit.
- RC's session grouping is a genuine differentiator: the reference sites show a
  flat list; RC already chunks by real play-sessions. Lean into that (per-session
  W-L headers, session WR) rather than flattening to mimic aggregator A.
- Win is the missing keystone: P1, P2, P6's header, and a result filter (P4) all
  unblock the moment `win` is loaded into the History row. Land P1 first.
- Legal: all of the above are conventions + computed-from-own-data layouts
  (win-color, pip strip, accordion, filter bar, op-score-style pill). No markup,
  CSS, or asset is copied from any site. Champion/item icons are already served
  locally from DDragon (`historical_pgr.js:51-67`), the sanctioned source.

---

## 3. LIFT ranking (summary)

| # | Pattern                                   | Verdict | Effort | Unblocks |
|---|-------------------------------------------|---------|--------|----------|
| P1 | Result-first row (win color + KDA)       | HIGH    | LOW    | P2,P4,P6 |
| P2 | Last-20 W/L strip + real season WR        | HIGH    | LOW-MED| -        |
| P4 | List filters (champ/queue/result)         | HIGH    | LOW-MED| -        |
| P3 | Expand-in-place accordion detail          | MED     | MED    | -        |
| P5 | Richer row (items/CS/grade pip)           | MED     | MED    | -        |
| P7 | Per-game op-score as scan/sort key        | MED     | LOW-MED| -        |
| P6 | Session grouping + W-L header             | LOW*    | TRIVIAL| (*done)  |

Recommended sequence: P1 -> P2 -> P4 (the three HIGH, all Tier-1, all unblocked
by adding `win` to the row), then P6's header enrich (free after P1), then P7 /
P5 / P3 as polish each behind the web/* UI-audit ritual.

---

## Sources

- Aggregator A features guide (row contents, last-20, expandable detail):
  https://review-site-z9.invalid/blog/game-analytics/aggregator-a-features-complete-guide
- Aggregator A detailed match-history-by-round (help center):
  https://aggregator-a.invalid/help/articles/48465997176089-How-to-view-detailed-match-history-by-round
- Overlay App E overlay review (pre-game recent performance, post-game popup):
  https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review
- Aggregator B / Aggregator C match-history + champion pool + filters:
  https://aggregator-c.invalid/ugg/
- Aggregator B FAQ (6-month summoner stats, mode separation): https://aggregator-b.invalid/faq
- Aggregator H (champion/summoner stats hub): https://aggregator-h.invalid/
- Aggregator G (per-game AI-Score model): https://aggregator-g.invalid/
