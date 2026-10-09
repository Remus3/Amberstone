# Competitor lift teardown - 2026-07-30 (Section 7b deep-dive)

**Category: TFT ANALYTICS / TFT LIVE COMPANION.**

Method: live network + payload capture via Chrome DevTools MCP against the
rendered pages, cross-page arithmetic to verify published formulas, primary
sources (GitHub issue, Overlay Platform M GEP docs) for the data-route question, and a
read of RC's own `tft/` lane for every HAVE claim. Every RC file/line cited
below was read from disk this session.

---

## 0. Why this category, and why it is not a re-run

`ROADMAP.md` RM-01 retires the competitor-lift rotation for the
overlay / companion / stat-site category (DRAINED 4x). The rotation instruction
is to pick "a genuinely un-torn-down category". TFT is that category, by
measurement, not taste:

- A keyword census over all 25 prior `COMPETITOR_LIFT_*.md` files (repo root
  plus `docs/_archive/` plus the 2026-07-28 consolidation dir) returns exactly
  ONE file mentioning TFT: `docs/_archive/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md`,
  and only as finding F7, graded "LOW / HIGH effort / NO - new data domain".
- `TFT aggregator U`, `TFT Aggregator T` and `TFT aggregator V` have ZERO hits across every prior
  lift doc.
- The 2026-06-22 "new data domain" grade was wrong then and is wrong now: RC has
  a full TFT lane already on disk (`tft/`, 3117 lines across 9 modules, plus
  `core/tft_worker.py`). There is no new domain to stand up. Every finding below
  lands in a module that already exists.

This also sits directly on the standing north star (drive live Haiku usage to
ZERO by precomputing). RC's TFT coach is today a *pure LLM judgement* path: it
formats game state into a prompt and asks Haiku. Four of the findings below
replace a Haiku judgement with deterministic arithmetic.

---

## 1. Verdict table

| # | Finding | Target | Effort | Risk | LIFT |
|---|---|---|---|---|---|
| F20 | RC ships a STALE + WRONG shop-odds table (Set 14 constants in a Set 17 game) | roll-math lane | LOW | LOW | **HIGH - bug, fix now** |
| F22 | 30 fields of `tft_set17_meta.json` carry mojibaked em-dashes, and they reach the Haiku prompt | RC internal | LOW | LOW | **HIGH - ASCII rule violation** |
| F19 | Markov-chain hit-probability ("do I roll?") as deterministic math | roll-math lane | MED | LOW | **HIGH - kills an LLM judgement** |
| F8 | Comp identity by centroid clustering, not a hand-written comp list | TFT Aggregator T | MED | MED | **HIGH - live board -> comp** |
| F1 | Dual-baseline co-occurrence delta (`delta` / `delta2`), formula verified | TFT aggregator U | LOW | LOW | **HIGH - method, no dependency** |
| F16 | NEGATIVE: no Riot TFT live-board API exists; RC's OCR path is correct | data route | n/a | n/a | **HIGH - closes a hunt** |
| F10 | Aperture auto-widening with disclosure to the client | TFT Aggregator T | LOW | LOW | MED |
| F17 | Overlay Platform M GEP field list as a free OCR/vision target spec | data route | LOW | LOW | MED |
| F4 | Full 8-bucket placement histogram instead of a scalar average | TFT aggregator U | LOW | LOW | MED |
| F12 | Comp "difficulty" from the pick-rate / placement gap | TFT Aggregator T | MED | LOW | MED |
| F21 | RC's Set 17 comp table is 7 patches stale (17.1 PBE vs live 17.8) | TFT Aggregator T | MED | MED | MED |
| F3 | Empirical BiS by item PAIR and TRIO, not a hand-written `bis` list | TFT aggregator U | MED | MED | MED |
| F2 | `adjDelta`, a confounder-adjusted item delta | TFT aggregator U | MED | MED | MED |
| F13 | Per-day trend series for meta-drift detection | TFT Aggregator T | LOW | MED | MED |
| F15 | Empirical per-comp levelling plan | TFT Aggregator T | MED | MED | MED |
| F5 | Board-vs-board head-to-head matchup winrate | TFT aggregator U | HIGH | MED | LOW |
| F6 | Conditioning on item-count and star-level | TFT aggregator U | LOW | LOW | LOW |
| F7 | Stats delivered by SSR document embed, zero XHR | TFT aggregator U | LOW | LOW | LOW |
| F9 | Auto-naming a cluster by distinctiveness score | TFT Aggregator T | MED | LOW | LOW |
| F11 | Per-cluster build `score` = conditional share, verified | TFT Aggregator T | LOW | LOW | LOW |
| F14 | Per-region/rank/day sample-size census endpoint | TFT Aggregator T | LOW | MED | LOW |
| F18 | Riot policy on real-time performance-altering overlays | data route | n/a | n/a | UNVERIFIED |

---

## 2. Targets and why each was picked

| target | shape | license / terms | why picked |
|---|---|---|---|
| **TFT aggregator U** | Next.js SSR stat site | proprietary, no license offered; `robots.txt` allows crawling | the only target that publishes a *derived statistical* quantity (`delta`, `delta2`, `adjDelta`) rather than raw rates, so the formula is recoverable by arithmetic |
| **TFT Aggregator T** | public unauthenticated REST API + Overlay Platform M companion | proprietary; `robots.txt` `Disallow:` (empty = allow all); no data licence offered | the only target that leaks its actual *clustering model* (centroid vectors) over the wire |
| **the live-state data route** (Riot `:2999` vs Overlay Platform M GEP vs OCR) | protocol question behind every TFT companion | n/a - protocol facts | RC uses OCR for TFT; if a structured live route existed, that is the single highest-value change in the lane. It does not. Recording the negative stops a future hunt |
| **the roll-math lane** (`wongkj12/TFT-Rolling-Odds-Calculator`, `brandon-nguyen-lam/TFT-Rolling-Sim`, esportstales, tftactics.gg) | open-source calculators + odds references | **BOTH repos: NO `LICENSE` file, NO `package.json`. All rights reserved by default. DO-NOT-VENDOR.** | pure math with zero runtime dependency - the cheapest possible Haiku-to-ZERO win |

**License gate, explicitly.** Both GitHub repos were checked at the repository
root for a `LICENSE` file AND for a `package.json` declaration, per the two
traps. Neither file exists in either repo. Absence of a LICENSE is NOT
permission - that is already settled doctrine in `CLAUDE.md`. Verdict for both:
**DO-NOT-VENDOR, technique-only.** The Markov formulation in F19 is a
mathematical technique and a protocol fact, not copyrightable expression; the
plan below is a re-implementation from the described behaviour, and no source
from either repo was copied or is reproduced here.

**A robots.txt that allows crawling is not a data licence.** Both sites allow
crawling. Neither offers redistribution terms. Any finding that proposes
consuming a live third-party feed (F8, F13, F21, F3) inherits the same
dependency decision the operator already made once for 101.qq.com duo-synergy
(item 277): live-first with a static seed fallback and a kill switch. That
precedent is the template, not a licence.

---

## 3. RC ground truth - the HAVE baseline for the whole lane

Read from disk this session. Every finding's HAVE column refers back to this.

- `tft/tft_state_reader.py:20` - RC polls
  `https://{GAME_HOST}:2999/liveclientdata/allgamedata` for TFT.
- `tft/tft_ocr_reader.py:29-32` - `_REGIONS` extracts exactly FOUR scalars:
  `stage_round`, `level`, `gold` (and `hp` derived at `:323`).
- `tft/tft_vision_reader.py:24` `_EXTRACT_PROMPT` - Sonnet vision extracts
  `traits_active`, `board_units`, `bench_units`, `shop_units`, `augments`,
  `augment_choices`. It explicitly does NOT extract per-unit items or hex
  positions, and reads only YOUR board (`:5`).
- `tft/tft_data.py:10` `TIER_ODDS`, `:24` `POOL_SIZES`, `:27` `UNITS_PER_COST` -
  static constants. The module docstring says outright: "Currently seeded for
  TFT Set 14 (patch 15.x baseline)."
- `tft/tft_coach_engine.py:442-452` - the ONLY consumer of `TIER_ODDS`. It
  formats the odds into prompt text and hands the decision to Haiku.
  `POOL_SIZES` and `UNITS_PER_COST` have **zero** consumers repo-wide.
- `data/meta/tft_set17_meta.json` - hand-maintained: 53 comps with hand-written
  `bis` / `alt` item lists and hex `positioning`. `_source` =
  "aggregator C Apr 9 2026 + TFT guide author X + TFT guide site W [em-dash] Set 17 PBE
  Patch 17.1", `_updated` = "2026-05-08".
- `tft/placement_aggregator.py` - RC's own positional heatmap, built from the
  coach's OWN past text output, not from observed boards.
- `core/smoothed_rates.py` - the existing shared Laplace/shrink primitive. This
  is the reuse point for F2, not a new module.
- `core/tft_worker.py:44` - `POLL_INTERVAL_S = 1.5`.

Repo-wide grep for `hypergeom` / `binom` / `p_hit` across RC's TFT lane: zero
hits. RC computes no TFT probability anywhere.

---

## 4. Findings - TFT aggregator U

### F1 - Dual-baseline co-occurrence delta. HIGH.

1. **WHAT.** For every pair (unit A, unit B) that appear on the same board, the
   site publishes TWO deltas, not one: `delta` and `delta2`. They are the same
   pair placement measured against two different baselines. This is the
   mechanic that separates "this pair is good" from "this pair is good *for
   A*" - the distinction RC's synergy language currently cannot make.

2. **HOW - verified by cross-page arithmetic, both directions.**
   - Leona page: `base.place` = 4.64. Its `units` entry for Diana:
     `place` 5.01, `delta` 0.13, `delta2` 0.37.
   - Diana page: `base.place` = 4.88. Its `units` entry for Leona:
     `place` 5.00, `delta` 0.36, `delta2` 0.12.
   - Solve: on the Leona page, `delta2` 0.37 = 5.01 - 4.64 (SELF base).
     `delta` 0.13 = 5.01 - 4.88 (PARTNER base). On the Diana page the roles
     swap exactly: `delta2` 0.12 = 5.00 - 4.88 (self), `delta` 0.36 =
     5.00 - 4.64 (partner).
   - Independent third check: Ornn never appeared as a page. From the Diana
     page, Ornn `place` 4.70 `delta` 0.29 implies Ornn base = 4.41. From the
     Leona page, Ornn `place` 5.01 `delta` 0.60 implies Ornn base = 4.41.
     Two pages, one unseen unit, identical derived baseline.
   - **Formula: `delta` = pairPlace - partnerBasePlace;
     `delta2` = pairPlace - selfBasePlace.** Verified to 2 decimal places.
   - Payload shape (SSR, see F7):
     `{id, count, place, top4, won, delta, delta2}`.

3. **HAVE.** No. RC has no TFT pair statistic at all. RC's LoL-side duo-synergy
   (`core/smoothed_rates_101qq.py`, `core/synergy_external_source.py`) is a
   single-baseline win-rate lane and does not carry the dual-baseline idea.

4. **WHERE.** `core/smoothed_rates.py` for the shrinkage, a new
   `tft/tft_pair_stats.py` for the two-baseline computation, consumed by
   `tft/tft_coach_engine.py:219 _build_prompt` (or, better, bypassing the prompt
   entirely per the north star).

5. **EFFORT + RISK.** LOW/LOW *as a method*. The arithmetic is two subtractions
   over data RC could compute from its own stored TFT games. No new dependency
   is required to adopt the METHOD. Adopting their DATA is a separate decision
   (see section 2).

6. **LIFT: HIGH.** The formula is now fully known and costs nothing to
   implement. The dual baseline is the actual insight: it is what lets a coach
   say "Ornn is fine, but he is not fine *with your Leona*".

### F2 - `adjDelta`, a confounder-adjusted item delta. MED.

1. **WHAT.** Per-item-on-unit stats carry `adjDelta` instead of a raw delta.
2. **HOW.** Observed: Gargoyle Stoneplate on Leona has `place` 4.31 against a
   Leona base of 4.64, so the RAW delta is -0.33, but `adjDelta` is -0.162 -
   roughly half the magnitude, same sign. Warmogs: raw -0.34, `adjDelta`
   -0.127. Leona's own `baseAdjDelta` is +0.0108 (near zero, as a
   self-comparison should be). The systematic shrink toward zero, same sign, is
   consistent with regressing out the obvious confounder: a unit holding three
   items sits on a stronger board by construction. The site publishes
   `itemCountData` (Leona at 0 items places 4.93, at 3 items 4.23), which is
   exactly the confounder that needs removing. **The precise estimator is NOT
   published and is UNVERIFIED** - I recovered the behaviour, not the formula.
3. **HAVE.** Partially. `core/smoothed_rates.py` is RC's Laplace/shrink
   primitive but it shrinks for SAMPLE SIZE, which is a different correction
   from confounder adjustment. RC has no confounder adjustment anywhere.
4. **WHERE.** `core/smoothed_rates.py` gains a sibling adjustment, applied at
   the point any TFT item recommendation is scored.
5. **EFFORT + RISK.** MED/MED - the honest version is "condition on item count
   and star level before differencing", which RC can do exactly because
   `itemCountData` and `starLevelData` (F6) are the strata.
6. **LIFT: MED.** Right idea, unproven formula. Implement the stratified
   version RC can defend, not a guess at theirs.

### F3 - Empirical BiS by item PAIR and TRIO. MED.

1. **WHAT.** Separate `items` (40 singles), `itemPairs` (70), `itemTrios` (125)
   arrays, each with its own `count` / `place` / `top4` / `won` / `adjDelta`.
2. **HOW.** Top Leona trio: Gargoyle + Gargoyle + Warmogs, `count` 2191,
   `place` 4.04, `adjDelta` -0.411. Note the DUPLICATE item in the trio, and
   note that the best trio beats the best single (4.04 vs 4.31) by more than
   the singles differ from each other, which is the whole argument for scoring
   combinations rather than summing singles.
3. **HAVE.** No. `data/meta/tft_set17_meta.json` carries hand-written
   `items: {unit: {bis: [...], alt: [...]}}` lists per comp, sourced from three
   guide sites in May 2026. That is an opinion snapshot, not a measurement, and
   it is 7 patches stale (F21).
4. **WHERE.** Replace the hand-written `bis` / `alt` fields with a generated
   table; consumer is `tft/tft_coach_engine.py`.
5. **EFFORT + RISK.** MED/MED - the schema change is small, but the data has to
   come from somewhere (own games are far too few; a third-party feed is a
   dependency decision).
6. **LIFT: MED.** Clearly better than a hand list, gated on the data question.

### F4 - Full placement histogram, not a scalar. MED.

1. **WHAT.** `placeDistribution` is an 8-element array of raw counts, one per
   finishing position.
2. **HOW.** Leona: `[3140, 4418, 4908, 5038, 5084, 4976, 4921, 4218]`, summing
   to 36703, which equals `base.count` exactly. TFT Aggregator T does the same thing in
   a different shape (F8: `places` is a 9-element array where element 9 is the
   total). Two independent products both keep the histogram rather than the
   mean, because in TFT the mean hides the shape: a 4.5 average from a bimodal
   "1st or 8th" comp is a completely different recommendation from a 4.5 flat.
3. **HAVE.** No. RC's TFT rating store (`data/ratings/`) records placement per
   game but nothing aggregates a distribution;
   `tft/placement_aggregator.py` aggregates board POSITIONS, a different thing
   despite the name.
4. **WHERE.** A new aggregate alongside `tft/placement_aggregator.py`; render in
   the TFT panel.
5. **EFFORT + RISK.** LOW/LOW on RC's own data - it is a bincount.
6. **LIFT: MED.** Cheap, and it is the correct primitive to store *before* any
   averaging, so doing it now avoids a re-do later.

### F5 - Board-vs-board head-to-head winrate. LOW.

1. **WHAT.** `unitMatchups` (43 entries) and `traitMatchups` (87) give a raw
   `winrate` for combat rounds where your board met a board containing unit or
   trait X.
2. **HOW.** `{unitId: "TFT17_Chogath", winrate: 0.5226}`,
   `{traitId: "TFT17_Timebreaker", traitTier: 3, winrate: 0.5943}`. Note this
   requires per-ROUND combat outcomes plus the opponent's board - data the
   post-game Riot TFT match API does not carry, which is precisely why TFT Aggregator T
   markets round-by-round capture from its companion app (see F16/F17).
3. **HAVE.** No, and RC cannot get the input: `tft/tft_vision_reader.py:5` reads
   only YOUR units, and the vision prompt at `:41` explicitly says to ignore the
   enemy half during combat.
4. **WHERE.** Would require an opponent-board vision pass plus round-outcome
   capture.
5. **EFFORT + RISK.** HIGH/MED - a new vision surface and a new store.
6. **LIFT: LOW.** Interesting, but it is the most expensive input in the lane
   and the payoff is a mid-game nicety.

### F6 - Conditioning on item count and star level. LOW.

1. **WHAT.** `itemCountData` (placement by 0/1/2/3 items held) and
   `starLevelData` (by 1/2/3/4 star).
2. **HOW.** Leona `itemCountData`: 0 items -> 4.93, 1 -> 4.82, 2 -> 5.18,
   3 -> 4.23. `starLevelData`: 1-star -> 5.78, 2-star -> 5.07, 3-star -> 4.26,
   4-star -> 3.26 (`count` 546, so 4-star exists in Set 17 and is measurable).
   The non-monotonic 2-item dip is the tell that these are raw strata, not a
   model.
3. **HAVE.** Partially - RC's vision reads star level for board units
   ("Aatrox 2-star", `tft/tft_vision_reader.py:58`) but never conditions any
   recommendation on it.
4. **WHERE.** Strata keys wherever F2/F3 land.
5. **EFFORT + RISK.** LOW/LOW.
6. **LIFT: LOW** standalone; it is really the enabling detail for F2.

### F7 - Stats shipped in the document, zero XHR. LOW.

1. **WHAT.** TFT aggregator U makes NO API call for its statistics.
2. **HOW.** Captured every network request on `/units`, `/units/leona` and
   `/team-compositions`. Filtering the 250 resource entries down to
   fetch/XHR leaves only advertising and analytics traffic - not one stat call.
   The entire payload sits in the `__NEXT_DATA__` script element:
   49653 chars for the units index, 65219 for a unit detail page. The aperture
   is a 4-field object `{patch: {_0: 16150}, rankGroup, gameType, queue}`; the
   patch integer 16150 decodes as LoL patch 16.15 (confirmed independently by
   TFT Aggregator T's `full_padded_patch: "0016.0015"`).
3. **HAVE.** Yes, in spirit - RC already precomputes to JSON and serves it
   (`data/daemon_slayer/`, ADR-008 asset-hash). Worth recording only because it
   confirms the precompute-and-embed pattern RC is already committed to is what
   the most statistically serious site in the category also does.
4. **WHERE.** n/a - validation, not work.
5. **EFFORT + RISK.** n/a.
6. **LIFT: LOW.** Confirmation, not a lift.

---

## 5. Findings - TFT Aggregator T

TFT Aggregator T exposes a public unauthenticated REST API. Endpoints captured live:
`api-hc.TFT aggregator T/tft-stat-api/patch`, `/tft-stat-api/games?days=7`,
`/tft-comps-api/comps_data?queue=1100`, `/tft-comps-api/comps_stats?...`,
`/tft-comps-api/unit_items_processed`, plus
`data.TFT aggregator T/lookups/TFTSet17_latest_en_us.json`.

### F8 - Comp identity by centroid clustering. HIGH.

1. **WHAT.** TFT Aggregator T does not maintain a list of comps. It CLUSTERS finished
   boards in a numeric feature space each patch, and every stat is reported per
   cluster. The centroid vectors are shipped to the browser.

2. **HOW - the model, off the wire.**
   - `comps_data` returns `results.data.cluster_details`, keyed by cluster id:
     69 clusters under run id 409 (`cluster_id: 409`, members `409000`...`409068`).
   - Each cluster carries `centroid`: a **102-dimensional float vector**.
     For cluster 409000 the dimensions above 0.5 are indices
     0 (1.2483), 23 (4.3776), 32 (3.3583), 33 (2.6189), 35 (2.9102),
     44 (2.9411), 49 (0.8114), 58 (1.1624), 68 (0.7842), 73 (0.7276),
     75 (0.7392), 77 (0.7479), 84 (0.7962), 93 (0.7750), 98 (10). Everything
     else is near zero. The mid-range values (2.6 to 4.4) line up in count with
     the cluster's units and the ~0.73-0.80 band lines up with its traits, so
     the space is plainly unit-occupancy plus trait-activation.
     **The exact per-index mapping is UNVERIFIED** - I did not recover the
     dimension ordering, and index 98 holding exactly `10` is unexplained.
   - `units_string` and `traits_string` are the human-readable projection of
     the centroid, e.g. cluster 409000 =
     "TFT17_Aatrox, TFT17_Jax, TFT17_Lulu, TFT17_Maokai, TFT17_Milio,
     TFT17_Pantheon, TFT17_TwistedFate".
   - **There is a noise bucket.** `games` carries a cluster `"-1"` with
     `count` 832 and `avg` 5.8041, against `"Overall"` `count` 1207400
     `avg` 4.5. Boards that match no centroid place about 1.3 worse than
     average. That is a clusterer with a distance threshold (DBSCAN-like, or
     k-means with a reject radius) - and it is also, incidentally, the single
     most coachable number in this whole document: incoherent boards lose.
   - `comps_stats` returns per cluster a `places` array of NINE integers. For
     cluster 409000: `[1170, 1433, 1200, 1081, 1059, 1071, 1253, 1171, 9438]`.
     The first eight sum to exactly 9438, which is element nine and also the
     sibling `count` field. So element nine is the total and elements one
     through eight are the placement histogram (same primitive as F4).

3. **HAVE.** No, and RC does the opposite. `data/meta/tft_set17_meta.json`
   holds 53 HAND-WRITTEN comps, each with hand-listed `core_units`,
   `flex_units`, `lv4`/`lv7`/`lv9` boards, `bis` items and hex `positioning`,
   sourced from three guide sites on 2026-05-08.

4. **WHERE.** Two separable pieces, and the split matters:
   - *The classifier* (nearest-centroid assignment of a partial live board) is
     pure local math: a new `tft/tft_comp_classifier.py` consuming
     `tft_vision_reader`'s `board_units` + `traits_active`, called from
     `tft/tft_coach_engine.py`. **No dependency, no LLM.**
   - *The centroids* have to come from somewhere: either fitted from RC's own
     stored games (too few), or taken as a live third-party feed (the 101.qq.com
     precedent), or approximated by seeding centroids from the existing 53
     hand comps - which is a legitimate cold-start and needs no new data at all.

5. **EFFORT + RISK.** MED/MED. The seeded-centroid version is MED/LOW and
   requires no external data: turn the 53 existing hand comps into 53 occupancy
   vectors and classify against them. That alone converts "which comp am I
   playing" from a Haiku judgement into a distance computation.

6. **LIFT: HIGH.** This is the headline. It gives RC a deterministic
   live board -> comp identity, which is the precondition for every other
   precomputed TFT recommendation, and the cold-start path needs zero new data.

### F9 - Auto-naming a cluster by distinctiveness score. LOW.

1. **WHAT.** A cluster's display name is derived, not authored.
2. **HOW.** Each cluster carries `name`, an array of
   `{name, type: "unit"|"trait", score}` sorted by how distinctive that element
   is to the cluster - e.g. 409000 gives
   `TFT17_ResistTank` (trait, 0.9955), `TFT17_Jax` (unit, 4.4754),
   `TFT17_Lulu` (unit, 2.8179) - and `name_string` is the top-N join
   (409045 -> "TFT17_DRX, TFT17_Kindred").
3. **HAVE.** No - RC's comp names are hand-authored keys ("AP Vanguards").
4. **WHERE.** Falls out of F8 free if F8 is built.
5. **EFFORT + RISK.** MED/LOW.
6. **LIFT: LOW.** Cosmetic unless F8 ships, and RC's hand names are better
   English than a joined identifier list.

### F10 - Aperture auto-widening, disclosed to the client. MED.

1. **WHAT.** The stats request carries `permit_filter_adjustment=true`, and the
   response carries a `filter_adjustment` object back.
2. **HOW.** Captured response:
   `{override_applied: false, rank_filter: "CHALLENGER,DIAMOND,EMERALD,GRANDMASTER,MASTER,PLATINUM", sample_size: 2185624}`.
   The client ASKS for permission to be overridden; the server widens the rank
   aperture when the requested slice is too thin, then reports back both that it
   did (`override_applied`) and what aperture it actually used
   (`rank_filter`) plus the resulting `sample_size`. The user is never silently
   shown a number computed over a different population than they selected.
3. **HAVE.** Partially, and this is the interesting part. RC already has the
   *statistical* half - `core/smoothed_rates.py` shrinks thin samples - but not
   the *disclosure* half. RC's existing doctrine
   (`feedback_metric_provenance_tagging`) is exactly this idea; TFT Aggregator T is a
   worked example of it as a wire contract rather than a UI label.
4. **WHERE.** Any RC route that takes a rank/patch/mode filter and can under-
   fill it. Return the effective aperture alongside the numbers.
5. **EFFORT + RISK.** LOW/LOW - it is a response-shape addition.
6. **LIFT: MED.** Cheap, generalizes beyond TFT to every filtered RC stat
   surface, and it is a pattern RC already believes in but has not made
   machine-readable.

### F11 - Per-cluster build score is a conditional share. LOW.

1. **WHAT.** Each cluster's `builds` entries rank an exact 3-item build on a
   unit.
2. **HOW.** Cluster 409045, Akali: `buildName` = Deathblade + Hextech Gunblade +
   Power Gauntlet, `count` 60511, `avg` 3.7613, `num_items` 3,
   `score` 0.4767, `place_change` -0.295, `unit_numitems_count` 126731.
   `count / unit_numitems_count` = 0.4775 against a published `score` of 0.4767
   - a 0.17 percent relative gap, consistent with the two figures coming from
   slightly different aggregation snapshots. So **`score` is the conditional
   share of that exact item triple among all 3-item Akali builds in that
   cluster**, and `place_change` (-0.295) is the placement delta against the
   in-cluster baseline. Only the single top build per unit is exposed (4 units,
   4 build rows for that cluster).
3. **HAVE.** No.
4. **WHERE.** Same landing zone as F3.
5. **EFFORT + RISK.** LOW/LOW.
6. **LIFT: LOW.** A detail of F3, recorded so a future session does not
   re-derive it.

### F12 - Comp difficulty from the pick / placement gap. MED.

1. **WHAT.** Each cluster carries `difficulty`, `diff_pick`, `diff_place`.
2. **HOW.** Cluster 409045: `difficulty` 0.01, `diff_pick` 0.061,
   `diff_place` 0.051. The naming and magnitudes are consistent with a
   comparison of the comp's pick rate and placement between a high-rank cohort
   and the overall cohort - a comp that good players pick much more and place
   much better with is "hard". **The exact estimator is UNVERIFIED**; I have the
   inputs and the sign, not the formula.
3. **HAVE.** No - and the idea generalizes past TFT. Daemon Slayer ranks builds
   by simulated output with no notion of execution difficulty, so a build that
   is optimal-but-unplayable ranks identically to an easy one.
4. **WHERE.** TFT: alongside F8. LoL: a much larger question for
   `agents/daemon_slayer/` and out of scope here.
5. **EFFORT + RISK.** MED/LOW for TFT (needs a rank-split sample).
6. **LIFT: MED.** The concept is more valuable than the TFT instance.

### F13 - Per-day trend series. MED.

1. **WHAT.** Each cluster carries `trends`, a per-day series.
2. **HOW.** Cluster 409045:
   `{day: "2026-07-24", count: 62501, avg: 3.9986, pick: 0.1335}`,
   `{day: "2026-07-25", count: 64933, avg: 4.0128, pick: 0.1358}`,
   `{day: "2026-07-26", count: 65205, avg: 4.0190, pick: 0.1356}` - so daily
   `count`, mean placement and pick share. This is how a site detects a comp
   going stale *within* a patch rather than only at the patch boundary.
   TFT aggregator U does the same with `dateStats` (3 days) and `regionDateStats`
   (40 region-day cells).
3. **HAVE.** Partially. RC has `data/meta_build/` and a nightly regen
   (`reference_build_order_regen_full_roster_and_nightly`) but no intra-patch
   drift signal on the TFT side.
4. **WHERE.** A time dimension on whatever store F8 lands in.
5. **EFFORT + RISK.** LOW/MED - trivial to store, but only meaningful with
   enough daily volume, which RC's own games will never have.
6. **LIFT: MED.** Gated on the same data-source decision as F3/F8.

### F14 - Sample-size census endpoint. LOW.

1. **WHAT.** `/tft-stat-api/games?days=7` returns a 3321-row census.
2. **HOW.** Rows are `{day, srq: [region, rank, queue], patch: [patch, ""], count}`,
   e.g. `{day: 0, srq: ["BR1","BRONZE","1100"], patch: ["17.8",""], count: 488}`.
   The companion `/tft-stat-api/patch` returns
   `{patch: "17.8", full_padded_patch: "0016.0015", count: 3990573,
   start: "2026-07-28T20:51:14.312Z"}`. Publishing the denominator per
   region/rank/queue/patch/day is what makes the F10 aperture logic auditable.
3. **HAVE.** Partially - RC tracks its own corpus size but does not expose a
   per-slice census.
4. **WHERE.** Would attach to the same route as F10.
5. **EFFORT + RISK.** LOW/MED.
6. **LIFT: LOW.** Only matters at their data volume.

### F15 - Empirical per-comp levelling plan. MED.

1. **WHAT.** Each cluster carries `levelling`, e.g. `"lvl 6"` for 409045 - the
   level the cluster's successful players actually stop at, measured rather
   than prescribed.
2. **HOW.** Single string per cluster in the payload captured.
3. **HAVE.** No, and RC's version is hard-coded prose.
   `tft/tft_coach_engine.py:24` embeds a fixed rule in the prompt:
   "LEVEL TIMING: Lv6@3-2, Lv7@4-1, Lv8@4-2(rolldown), Lv9@5-1+ ... Never
   suggest Lv9 before stage 5." That is one global rule applied to all 53 comps,
   when levelling is the most comp-specific decision in TFT (a reroll comp and a
   fast-9 comp want opposite answers).
4. **WHERE.** Per-comp field in the comp table; consumed at
   `tft/tft_coach_engine.py:24`/`:219`.
5. **EFFORT + RISK.** MED/MED.
6. **LIFT: MED.** The HAVE gap here is sharper than the finding: RC currently
   gives every comp the same levelling advice.

---

## 6. Findings - the live-state data route

### F16 - NEGATIVE: there is no Riot TFT live-board API. RC's OCR path is correct. HIGH.

1. **WHAT.** No capture-free structured source of TFT board / bench / shop /
   trait state exists from Riot. Every TFT companion that has this data reads
   the game process, not an API.

2. **HOW.**
   - `RiotGames/developer-relations` issue **#373**, "[REQUEST][TFT] Live Client
     Data API few info for TFT", opened **2020-09-24**, labelled
     `scope: tft` + `type: feature request`, is **still OPEN with no Riot staff
     reply and no assignee**. The request states that
     `https://127.0.0.1:2999/liveclientdata/allgamedata` in a TFT game returns
     essentially the LoL-shaped JSON, and explicitly asks for the missing
     pieces: per-player shop, bench, field, active synergies, carousel, items
     and battle results. Nearly six years, no response, no implementation.
   - The structured data therefore comes from Overlay Platform M's Game Events Provider
     (F17), which is a process-level integration, not a Riot endpoint.

3. **HAVE.** RC already polls exactly that endpoint at
   `tft/tft_state_reader.py:20` and already compensates with OCR
   (`tft/tft_ocr_reader.py`) plus Sonnet vision (`tft/tft_vision_reader.py`).
   **RC's architecture here is correct and needs no change.**

4. **WHERE.** Nowhere. This finding is a fence.

5. **EFFORT + RISK.** n/a.

6. **LIFT: HIGH - as a recorded negative.** This is the TFT twin of the settled
   "LCU augment API is a confirmed dead-end, augment OCR is the proven path"
   line. It belongs in the same settled list so no future session spends a cycle
   hunting for a TFT live API. It also retroactively justifies RC's OCR
   investment, which looks like a workaround until you know no alternative
   exists.

### F17 - The Overlay Platform M GEP field list as a free OCR target spec. MED.

1. **WHAT.** Overlay Platform M publishes the exact TFT field surface its provider
   exposes. That list is a specification of what a mature TFT companion
   consumes, written by the people who had to extract all of it - RC can read it
   as a target list for its OWN vision/OCR path without touching Overlay Platform M.

2. **HOW.** From the Overlay Platform M TFT GEP documentation, the exposed categories are:
   `game_info`, `live_client_data`, `me` (summoner_name, xp, health, rank,
   gold), `match_info` (pseudo_match_id, battle_state, match_state, round_type,
   round_outcome, opponent, game_mode, local_player_damage, item_select),
   `roster` (full player list with index, health, xp, rank, tag_line), `store`
   (shop_pieces), `board` (board_pieces with position, level, items), `bench`
   (bench_pieces with position, level, items), `carousel` (carousel_pieces with
   items), and `augments` (offered + picked). Events include round_start,
   round_end, battle_start, battle_end, match_start, match_end.

3. **HAVE - the gap, precisely.** RC extracts:
   - OCR (`tft/tft_ocr_reader.py:29-32`): `stage_round`, `level`, `gold`, `hp`.
   - Vision (`tft/tft_vision_reader.py:24`): `traits_active`, `board_units`,
     `bench_units`, `shop_units`, `augments`, `augment_choices`.
   RC does NOT have, and the list above names: **per-unit ITEMS** (on board and
   bench), **per-unit hex POSITION**, the **opponent roster** (other players'
   health / level / rank), **round_outcome** (did I win the fight),
   **local_player_damage**, and **carousel contents**.
   Two of those are load-bearing for findings above: per-unit items gates F3
   (empirical BiS is unusable if RC cannot see what the player is holding), and
   round_outcome gates F5.
   Note `tft/placement_aggregator.py` already parses hex positions - but out of
   the coach's own past TEXT output, not out of an observation, so it is a
   record of what RC recommended, not of what happened.

4. **WHERE.** `tft/tft_vision_reader.py` `_EXTRACT_PROMPT` (:24) and its crop
   list (`:83-85`), plus `data/vision_regions.json` calibration for any OCR-able
   scalar. Per-unit items are the highest-value single addition.

5. **EFFORT + RISK.** LOW to spec, MED to implement (a vision prompt and crop
   change, live-gated for calibration). **No Overlay Platform M dependency is proposed or
   needed** - only their published field list is used, as a checklist.

6. **LIFT: MED.** It converts "what should RC's TFT vision read next" from a
   guess into a ranked gap list, and the ranking is validated by a product that
   ships.

### F18 - Riot policy on real-time performance-altering overlays. UNVERIFIED.

1. **WHAT.** Search results assert a Riot policy that in-game apps and overlays
   "may not include any real-time data that would improve a player's performance
   immediately by altering player behavior".
2. **HOW.** **I did not verify this against Riot's actual policy text.** It came
   from a search-result summary, not a primary source. It is recorded here only
   because it would bound several findings if true.
3. **HAVE.** RC is a local, single-user, non-distributed tool, so the practical
   exposure differs from a distributed Overlay Platform M app regardless.
4. **WHERE.** n/a until verified.
5. **EFFORT + RISK.** n/a.
6. **LIFT: UNVERIFIED - do not act on this line.** If any finding here is ever
   taken toward distribution, read the actual Riot developer policy first.

---

## 7. Findings - the roll-math lane

### F19 - Markov-chain hit probability as deterministic math. HIGH.

1. **WHAT.** "Should I roll?" is the central recurring TFT decision and it has a
   closed-form answer. The open-source calculators in this lane compute the full
   probability distribution over how many copies of a target unit you will see
   for a given gold spend - no model, no LLM, no data feed.

2. **HOW - the technique, from the described behaviour (no source copied).**
   - State: the number of copies of the target unit obtained, 0 through 9.
   - Transition: a 10x10 matrix whose entries are, per shop slot,
     P(slot rolls the target's cost tier | player level) multiplied by
     P(slot is this specific unit | that tier) = copiesRemaining /
     tierPoolRemaining.
   - Gold to shops: 2 gold = 5 shop slots, so g gold gives 5g/2 slots, and the
     distribution after spending g is the matrix raised to that power applied to
     the starting state.
   - Inputs: player level, gold to spend, copies already owned, copies taken by
     other players.
   - Output: the full distribution over copies obtained, not a point estimate.
   - **Honest limitation, worth designing around.** Raising a FIXED matrix to a
     power cannot truly model pool depletion, because the per-slot hit
     probability changes every time a copy is removed. The fixed-matrix version
     is an approximation that is fine over a short roll-down and drifts over a
     long one. RC's implementation should either accept that explicitly, or
     carry remaining-pool in the state, which is the more defensible choice and
     is the difference between "a calculator" and "a coach that is right at
     stage 4-2".

3. **HAVE.** No. RC has the CONSTANTS and never uses them for arithmetic:
   `tft/tft_data.py:24` `POOL_SIZES` and `:27` `UNITS_PER_COST` have **zero
   consumers repo-wide** (verified by grep - the only hits are the definitions
   themselves and the Share mirror). `TIER_ODDS` has exactly one consumer,
   `tft/tft_coach_engine.py:442-452`, which formats it into prompt text
   ("Roll odds at Lv8: 1c=15% 2c=20% ...") and hands the decision to Haiku.
   **The probability question is currently answered by an LLM reading a table.**

4. **WHERE.** A new `tft/tft_roll_odds.py` (pure function, no I/O), consumed by
   `tft/tft_coach_engine.py` in place of the `:442-452` odds-text block. The
   inputs it needs are all already available: `level` and `gold` from
   `tft/tft_ocr_reader.py`, board and bench units from
   `tft/tft_vision_reader.py`. Copies taken by other players is the only input
   RC cannot see (that is an F17 gap), and the sane default is to assume the
   average depletion rather than zero.

5. **EFFORT + RISK.** MED/LOW. Pure math, no new data, no new dependency, fully
   unit-testable against hand-computed cases. The only real risk is the
   constants being wrong, which is F20, and which must be fixed first.

6. **LIFT: HIGH.** This is the cleanest Haiku-to-ZERO win in the entire TFT
   lane: a decision currently delegated to a language model, replaced by
   arithmetic that is both cheaper and strictly more correct. It is also the
   finding with the fewest external dependencies of anything in this document.

### F20 - RC ships a stale and WRONG shop-odds table. HIGH - this is a bug.

1. **WHAT.** `tft/tft_data.py` carries Set 14 constants and RC is playing
   Set 17. The odds table is wrong at the levels where the decision matters.

2. **HOW - measured against two independent sources that agree.**
   RC `TIER_ODDS` (`tft/tft_data.py:10`) versus published Set 17 tables:

   | level | RC (1c/2c/3c/4c/5c) | esportstales Set 17 | tftactics.gg | verdict |
   |---|---|---|---|---|
   | 6 | 35/35/25/5/0 | 30/40/25/5/0 | 30/40/25/5/0 | **RC WRONG, both sources agree** |
   | 7 | 22/30/33/15/0 | 19/30/40/10/1 | 19/30/35/10/1 | RC wrong, sources disagree on 3c |
   | 8 | 15/20/35/25/5 | 17/24/32/24/3 | 18/25/32/22/3 | RC wrong, sources disagree |
   | 9 | 10/15/30/30/15 | 15/18/25/30/12 | 10/20/25/35/10 | RC wrong, sources disagree |
   | 10 | 5/10/20/35/30 | 5/10/20/40/25 | 5/10/20/40/25 | **RC WRONG, both sources agree** |

   `POOL_SIZES` (copies per champion, `tft/tft_data.py:24`): RC has
   `{1:29, 2:22, 3:18, 4:12, 5:10}`; esportstales gives Set 17 as
   `{1:30, 2:25, 3:18, 4:10, 5:9}`. Four of five tiers differ.

   **Two claims, held to different standards.** That RC's table is stale is
   VERIFIED - two independent sources agree exactly with each other and disagree
   with RC at levels 6 and 10, and RC's own module docstring admits the Set 14
   provenance. What the CORRECT Set 17 values are at levels 7 through 9 is
   **UNVERIFIED**: the two third-party tables disagree with each other there,
   and tftactics.gg self-flags its own table as labelled "Set 14" despite the
   Set 17 page heading. Champion counts per cost also disagree (tftactics says
   10 four-costs and 9 five-costs; RC's own `data/meta/tft_set17_meta.json`
   `unit_costs` has 63 units at 14/13/13/13/10 per cost). **Do not copy either
   third-party table into RC.** The authoritative source is the in-client
   odds display or the Riot patch notes, and reading it is a live-gated task.

3. **HAVE.** The bug IS the have. RC is live-feeding a wrong odds table into the
   TFT coaching prompt at levels 6 through 10 - which is to say, at every level
   where a player actually asks whether to roll.

4. **WHERE.** `tft/tft_data.py:10-27`, and the identical duplicated block in
   `tft/tft_pbe_data.py:9-22` (`TIER_ODDS` and `POOL_SIZES` are copy-pasted into
   the PBE module, so both must be fixed together - and a shared constant with
   one owner would be the better shape). Consumers: `tft/tft_coach_engine.py:442`
   and `tft/tft_pbe_engine.py:266`.

5. **EFFORT + RISK.** LOW to fix, once the correct numbers are in hand. The
   correct numbers require one live-gated read of the in-client odds table.
   Tier-1 change (constants in one module plus its twin), so `py_compile` plus
   the TFT module tests.

6. **LIFT: HIGH.** It is a live correctness bug in shipped behaviour, found by
   measurement, and it blocks F19 (there is no point computing exact
   probabilities from wrong constants). Fix it first.

### F21 - RC's Set 17 comp table is 7 patches stale. MED.

1. **WHAT.** `data/meta/tft_set17_meta.json` was built against Set 17 **PBE
   patch 17.1** and is dated **2026-05-08**. Live TFT is on **patch 17.8**.
2. **HOW.** The file's own `_source` reads "aggregator C Apr 9 2026 +
   TFT guide author X + TFT guide site W [em-dash] Set 17 PBE Patch 17.1" and `_updated` is
   "2026-05-08". Live patch verified independently and concurrently from two
   captures: TFT Aggregator T `/tft-stat-api/patch` returns `patch: "17.8"` over
   3990573 games, and TFT aggregator U page titles read "Set 17 Patch 17.8".
   Seven patches of balance changes separate RC's comp/BiS/positioning
   recommendations from the game being played, and PBE-era balance is exactly
   the balance most likely to have been changed.
3. **HAVE.** The staleness IS the have. The file carries 53 comps with
   hand-written item and positioning advice, all of it PBE-era.
4. **WHERE.** `data/meta/tft_set17_meta.json`; consumed by
   `tft/tft_coach_engine.py:87 _load_trait_augment_data` and the comp lookup.
5. **EFFORT + RISK.** MED/MED. Re-authoring 53 comps by hand is the current
   process and it clearly does not survive contact with a patch cadence - which
   is the real argument for F8's generated table over a hand-maintained one.
6. **LIFT: MED.** The specific refresh is a chore; the finding is that a
   hand-maintained comp table has a demonstrated 7-patch decay and needs either
   automation or an explicit staleness banner in the UI.

### F22 - Mojibaked em-dashes in a data file, reaching the Haiku prompt. HIGH - ASCII rule violation.

1. **WHAT.** `data/meta/tft_set17_meta.json` contains 294 non-ASCII bytes across
   **30 string fields**, including doubly-corrupted em-dashes.
2. **HOW.** Byte-level scan of the file: the sequence decodes as
   `U+00C3 U+00A2 U+00C2 U+0080 U+00C2 U+0094`, which is a UTF-8 em-dash
   (`U+2014`) that was decoded as latin-1 and re-encoded as UTF-8 - so the file
   is already corrupted on disk, not merely non-ASCII. Also present: `U+2192`
   (right arrow, 4 occurrences) and `U+2605` (black star, 18 occurrences).
   The affected fields are not inert metadata: they include
   `trait_augments._categories.emblem`, `.combat_boost`, `.utility`, `.scaling`,
   and 25 `trait_augments.<Trait>.<Tier>.decision_note` entries - and
   `decision_note` is loaded by `tft/tft_coach_engine.py:87
   _load_trait_augment_data` and formatted into the prompt by
   `_build_augment_context` (`:135`). So the corruption is sent to Haiku on
   every augment round.
3. **HAVE.** This is a violation of the repo hard rule. `CLAUDE.md` records the
   2026-05-18 retroactive purge as covering code and JSON, with only logs,
   `docs/_archive/`, `.jsonl` ledgers and binaries excluded. This file is none
   of those. Either it post-dates the purge (it is dated 2026-05-08 but may have
   been added later) or it was missed.
4. **WHERE.** `data/meta/tft_set17_meta.json`. `tools/strip_em_dashes.py` exists
   and is documented as reusable for exactly this drift check - but note it will
   need to handle the *double-encoded* form, which is not a literal `U+2014` and
   so may not match a naive sweep. That is probably why it survived.
5. **EFFORT + RISK.** LOW/LOW. Tier-0 data fix. Worth running the sweep across
   `data/meta/` generally rather than only this file, since a tool that misses
   the double-encoded form will have missed it everywhere.
6. **LIFT: HIGH.** Cheap, it is a standing hard-rule violation, it is currently
   shipping corrupted text into an LLM prompt, and it suggests the existing
   sweep tool has a blind spot worth closing.

---

## 8. What was NOT found - honest negatives

- **No product in this category computes pool depletion from live opponent
  boards.** Every roll calculator asks the user to type in how many copies
  others hold. The scouting data exists in the companion apps but is not wired
  to the probability math in any product examined. If RC ever gets opponent
  board reads (F17), it would be doing something none of these do.
- **No public product exposes an augment-conditional-on-comp statistic.**
  TFT Aggregator T's per-cluster `top_augments` was an empty array on the cluster
  inspected; TFT aggregator U' `augments` / `aug1s` / `aug2s` / `aug3s` were all
  empty arrays on the unit page captured. The capability is clearly modelled in
  both schemas but was not populated at capture time.
- **TFT aggregator U makes no API call at all** (F7), so there is no REST surface
  to characterize there - only the SSR document embed.

---

## 9. Recommended slice ordering

Deterministic, dependency-free, and in this order because each unblocks the next:

1. **F22** - strip the mojibake (Tier-0, minutes, closes a hard-rule violation).
2. **F20** - correct the odds and pool constants (needs one live-gated read of
   the in-client odds table; do NOT copy a third-party table).
3. **F19** - `tft/tft_roll_odds.py`, the Markov hit-probability function, and
   cut `tft/tft_coach_engine.py:442-452` over to it. First real Haiku-to-ZERO
   step in the TFT lane.
4. **F8 cold-start** - turn the existing 53 hand comps into occupancy vectors
   and classify the live board by nearest centroid. No new data, no LLM.
5. **F1** - dual-baseline pair deltas, method only.

Everything else is BACKLOG, and the F3 / F8-full / F13 / F21 cluster all hinge
on one unmade decision: whether RC takes a live third-party TFT feed at all.
That decision has a precedent (101.qq.com, item 277) but it is the operator's,
not a research finding.
