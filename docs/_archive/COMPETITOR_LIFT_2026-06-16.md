# Competitor Lift Teardown - 2026-06-16 (Section 7b deep-dive)

Agent: Section-7b deep-dive competitor-lift research.
Targets (all verified NET-NEW vs the closed set in CLAUDE.md / prior teardowns):
1. Aggregator C (GPI - Gamer Performance Index, ML 8-axis player-skill scoring)
2. Overlay App E (in-client overlay: auto runes/builds, benchmarking overlay, enemy CD timers, post-game grading)
3. Overlay App F (live-game companion: pre-game lobby player-tags, damage breakdowns, warding heatmaps)

Method: live-render via Chrome DevTools MCP (network/XHR capture where reachable), plus
authoritative third-party teardowns and official product/marketing pages. Two targets
(Overlay App F live page, Overlay App E + Aggregator C support KBs) are Cloudflare- / login-gated, so
their in-the-clear API shapes could not be captured; mechanics below are sourced from the
rendered public product pages + independent deep reviews and are marked where inferred.
RC capability claims are from the orchestrator brief and are tagged RC-grep-needed for
the orchestrator to confirm against the live tree (this agent has read-only web access only).

NOTE on honesty: RC already has a deterministic DS engine (DPS/EHP/CC math, item ranking,
build orders, 1v1 matchup, anti-tank/heal hints, cc_blended_ehp panel) + a 0-100 PGR
heuristic + draft/pickban + duo-synergy + an Electron overlay (code-side). Several
competitor "features" are SUPERSEDED by RC and are called out as no-lift below.

================================================================================
## TARGET 1 - AGGREGATOR C GPI (Gamer Performance Index)
================================================================================

### Finding 1.1 - The 8-axis 0-100 skill radar (rank-percentile normalization)

1. WHAT: A per-player skill profile scored on 8 fixed axes - Fighting, Farming, Vision,
   Aggression, Toughness/Survivability, Teamplay, Versatility, Consistency - each 0-100,
   rendered as an octagon radar. 0 == "plays like a Bronze player on this axis",
   100 == "plays like a top Challenger". The score is a PERCENTILE position of the player
   inside their rank cohort, NOT a raw stat. Default aggregation is a 20-game rolling window.
2. HOW: Each axis is a weighted roll-up of several per-game metrics (e.g. Farming = early-game
   CS/min + total CS/min + CS-differential-vs-lane; Vision = wards placed/cleared + control
   wards + vision-score/min; Aggression = kill participation + early skirmish damage + dives;
   Toughness = deaths/game + damage-taken-mitigated + time-dead). The raw metric is converted
   to a percentile against same-role same-rank players, then the weighted blend is rescaled to
   0-100. Metric Allocation (the per-metric weights) is ROLE-DEPENDENT - e.g. early-game
   farming is weighted higher for an ADC/mid than a support. Marketed as "machine learning" but
   the observable behavior is a role-conditioned weighted-percentile model over standard
   Match-V5 / timeline metrics. (Weights + exact feature list are proprietary - inferred from
   the public category descriptions; the 0-100 rank-anchored scale and 20-game window are
   stated by Aggregator C directly.)
3. HAVE: RC has a 0-100 PGR heuristic for a SINGLE match (post-game review). RC does NOT
   appear to have a multi-game rolling skill profile, per-axis percentile-vs-cohort scoring,
   or a radar across these 8 behavioral axes. RC-grep-needed: confirm PGR is single-match only
   and that no rolling cross-match skill index exists.
4. WHERE: New dashboard route + panel (a "Player Profile / skill radar" page) backed by
   rewind_history.db (the local ~2846-match SQLite with full participant + timeline already
   in RC). A new module core/player_gpi.py computes the 8 axes from rewind_history rows;
   dashboard route /api/player-profile; a radar panel under web/js/panels/. The percentile
   normalization needs a cohort distribution - RC can self-anchor against the player's own
   match history distribution per role (no external dependency) rather than a global rank
   cohort, which is honest about RC's single-player scope.
5. EFFORT+RISK: MED. No new Riot/Claude dependency (rewind_history.db already holds the data).
   The lift is (a) a metric-extraction pass over existing timeline rows, (b) a
   percentile/z-score normalizer, (c) a radar panel + the UI-audit ritual. Risk: the
   "vs-cohort" percentile is weaker single-player (you only have your own games) - mitigate by
   normalizing per-role against the player's own rolling distribution, or seed cohort baselines
   from rewind_history aggregates. Testable deterministically (fixture matches -> expected axis
   scores).
6. LIFT: MED. Distinctive longitudinal mechanic RC lacks, all data is local, but it is a new
   compute + UI surface (not pure presentation over existing DS math), hence not in-run-shippable.

### Finding 1.2 - Strength/Weakness auto-call-out with improvement tips

1. WHAT: GPI surfaces your 1-2 lowest axes as "weaknesses" with a plain-language improvement
   tip ("Your Vision is low for your rank - place more control wards in the 10-20min window").
2. HOW: Argmin over the 8 normalized axes vs cohort median; the tip is a templated string keyed
   to the weak axis (rule/lookup table, not generative). Trivial once 1.1 exists.
3. HAVE: RC's PGR gives single-match feedback; a cross-match "your standing weakness is X"
   call-out appears absent. RC-grep-needed.
4. WHERE: Same player_gpi.py - a deterministic weakest-axis selector + a static tip lookup
   table; rendered in the same profile panel.
5. EFFORT+RISK: LOW (rides entirely on 1.1; the tips are a static dict, no Claude needed).
6. LIFT: LOW value as a standalone but it is the payoff of 1.1 - bundle it. Not worth a
   separate slice.

================================================================================
## TARGET 2 - OVERLAY APP E.GG (in-client overlay)
================================================================================

### Finding 2.1 - Enemy/teammate ultimate + ability cooldown timers (overlay)

1. WHAT: When an enemy (or ally) casts an ultimate, the overlay auto-starts a countdown showing
   when it is back up, so you do not have to track it mentally. Same mechanic for jungle camp
   respawn timers (auto-armed on camp clear).
2. HOW: Overlay App E reads game events from the Live Client API event stream (DragonKill, etc.) and the
   per-frame game state; for ult tracking it watches for the ability-cast / spell-on-cooldown
   signal, then runs CD = base_ult_cd reduced by the champion's current ability haste, counting
   down in real time. Jungle timers are a fixed respawn-duration timer keyed off the
   last-cleared event. (The exact cast-detection signal is the proprietary part - Live Client
   :2999 does NOT expose enemy cooldowns directly, so Overlay App E infers the cast from
   damage/announcer/event cues; inferred from observed behavior + the third-party review site Z9 teardown.)
3. HAVE: RC reads Live Client :2999 and LCU and has summoner_cooldowns in /api/state
   (cooldown tracking exists for summoner spells). RC has DS ability-haste-aware CD math
   (item AH registry, per-spell cooldowns) already. RC may NOT have a live ENEMY ult-CD
   countdown surfaced in the overlay. RC-grep-needed: confirm summoner_cooldowns scope and
   whether enemy ult CDs are tracked.
4. WHERE: RC already computes ability-haste-adjusted cooldowns in DS. The lift is a
   presentation + event-trigger layer: extend core/summoner_cooldowns (or a new
   core/ability_cooldowns.py) to arm an ult timer on a detected cast, render in the Electron
   overlay (rc-shell) and the dashboard. The CD math itself is EXISTING DS data.
5. EFFORT+RISK: MED. No new external dependency (Live Client + DS CD math are in-house). Risk:
   the cast-detection trigger is the hard part - Live Client does not give enemy CDs, so RC must
   infer the cast (vision/OCR of the enemy bar, or event heuristics). Summoner-spell CDs are
   easier (already partially done). The detection plumbing is non-trivial -> not pure
   presentation -> BACKLOG.
6. LIFT: MED. The CD math is free (DS), but the live cast-trigger for ENEMY abilities is real
   plumbing. Ally/self ult timers are LOW effort (cast is self-observable); enemy is MED.

### Finding 2.2 - Benchmarking overlay (live metric vs rank-cohort baseline)

1. WHAT: A live in-game overlay that shows your current key metrics (CS/min, gold, KDA,
   damage, vision) against a benchmark for your rank "in real time", so you see mid-game whether
   you are ahead/behind the expected curve for your elo.
2. HOW: Per-time-interval cohort baselines (e.g. expected CS at 10/15/20min for your role+rank)
   are precomputed server-side from aggregated match data; the overlay diffs your live Live-Client
   value against the baseline and color-codes ahead/behind. The baseline tables are the asset;
   the live diff is a subtraction.
3. HAVE: RC reads live CS/gold/level/KDA (liveclient in /api/state) and has rewind_history.db
   for personal baselines. RC has lead_projection in /api/state (some ahead/behind notion).
   A "live metric vs benchmark curve" overlay appears partially covered by lead_projection but
   likely NOT a full per-interval CS/gold/vision benchmark band. RC-grep-needed: inspect
   lead_projection contents.
4. WHERE: Precompute per-role CS/gold/XP-at-interval baselines from rewind_history.db into a
   static table (data/), then a dashboard panel + overlay widget diffs live liveclient values
   against it. Pure presentation + a one-time baseline extract over EXISTING local data.
5. EFFORT+RISK: LOW-to-MED. No new Riot/Claude dependency - baselines come from
   rewind_history.db; live values already in /api/state. The only new artifact is a precomputed
   benchmark table (a data extract, not a schema lift). Testable. This is close to
   in-run-shippable IF lead_projection does not already cover it.
6. LIFT: MED (HIGH if lead_projection is thin). Honest flag: this leans on EXISTING live data +
   a local baseline extract, no engine change - a strong presentation-layer candidate. Gate on
   the lead_projection grep.

### Finding 2.3 - Auto runes/builds import with personal-history override

1. WHAT: In champ-select, auto-imports the meta rune page + suggested build, BUT overrides the
   generic meta pick with the player's own high-win-rate build/champ when personal data beats
   the cohort (e.g. surfaces your off-meta Graves even if it is B-tier globally).
2. HOW: Builds sourced from the same public aggregate endpoints (Aggregator A/Aggregator B-class data),
   Platinum+ filtered, recency-weighted; then a personalization pass compares the player's own
   win-rate on that champ/build vs the cohort and promotes the personal build if it wins more.
   The auto-import writes the rune page into the client via LCU.
3. HAVE: RC has DS-computed build orders (metric-backed, deterministic) and archetype picks,
   plus an LCU client. RC's builds are ENGINE-COMPUTED (DS DPS/EHP optimal), which is
   ARGUABLY SUPERIOR to scraped aggregates. RC likely does NOT do LCU rune-page auto-WRITE or
   a personal-history-vs-meta override. RC-grep-needed.
4. WHERE: Two separable lifts: (a) LCU rune-page WRITE (push DS-recommended runes into the
   client) via lcu/lcu_client.py - frozen file, needs a new non-frozen wrapper; (b) a
   personal-build override using rewind_history.db win-rates layered onto DS build output in
   core/archetype_picks or core/build_order consumer.
5. EFFORT+RISK: MED. The rune WRITE touches LCU (frozen lcu_client.py -> wrapper) and is a real
   client-mutation feature (low risk but new behavior). The personal-override is LOW (local data
   over existing DS builds). No Claude dependency.
6. LIFT: MED. RC's build MATH already supersedes the meta-scrape core; the only net-new bits are
   the LCU auto-write and the personal-WR override layer. Worth it for the override; the
   auto-write is a convenience.

### Finding 2.4 - Post-game plain-English behavioral grading

1. WHAT: Post-game, compares your actions to a database of similar games at your rank and gives
   plain-English "why you scored poorly" call-outs tied to specific time windows ("you fell
   behind 8-12min after the failed dive at 7:30").
2. HOW: Per-metric percentile vs same-rank cohort + a templated explanation keyed to the worst
   time-window delta. The "plain English" is templated/rule-based, not necessarily generative.
3. HAVE: RC has a 0-100 PGR heuristic + a aggregator-G-style PGR reframe in progress + a Haiku coach.
   RC's PGR is the direct analog and is arguably AT-PARITY or ahead (it is moving to richer
   layout). The time-window call-out tying a score drop to a specific event is the one
   distinctive sub-mechanic RC may lack. RC-grep-needed: does PGR localize a score delta to a
   timeline window/event?
4. WHERE: PGR pipeline (the aggregator-G-style reframe work) - add a "biggest swing moment"
   detector over the Match-V5 timeline (largest gold/XP-delta interval + the event in it),
   rendered as a call-out in the PGR panel.
5. EFFORT+RISK: LOW-MED. Timeline data is already fetched for PGR; the lift is a delta-scan +
   a templated string. No new dependency.
6. LIFT: LOW. RC largely supersedes the grading; only the "swing-moment localizer" is net-new,
   and it folds naturally into the existing PGR reframe rather than a standalone slice.

================================================================================
## TARGET 3 - OVERLAY APP F.GG (live-game companion)
================================================================================

### Finding 3.1 - Pre-game lobby player-tagging (smurf / loss-streak / one-trick / tilt)

1. WHAT: On the live-game / lobby page, every player in the match is auto-annotated with short
   behavioral TAGS derived from recent games: "Potential Smurf", "On a loss streak",
   "Win streak", "One-trick (X)", "Otp/Main role", "Plays aggressive", "Tilt-prone", plus
   recent-game KDA, champion mastery, and rank. Gives you read on opponents/allies before lock-in.
2. HOW: Heuristic thresholds over the player's recent-N-match record (pulled via Riot
   Match-V5 + ranked endpoints): smurf == low-account-level/few-games + very-high win-rate +
   high KDA; loss/win streak == consecutive same-result tail of recent matches; one-trick ==
   one champion is >= ~X% of recent games; tilt-prone == sharp KDA/result drop in the last few
   games. The tags are rule-based classifiers over Match-V5 aggregates, refreshed per lobby.
   (Exact thresholds are proprietary - inferred from observed tag behavior; the underlying data
   is standard Match-V5 + League-V4 ranked.)
3. HAVE: RC has draft/pickban targets and duo-synergy, reads LCU champ-select, and HAS a local
   match corpus (rewind_history.db) + a valid Riot key (champ-select/post-game full-team
   context is in policy per ADR-006). RC does NOT appear to surface per-opponent behavioral
   tags in champ-select. RC-grep-needed: confirm champ-select panel does not already tag lobby
   players.
4. WHERE: New core/lobby_tags.py: on LCU champ-select, pull each participant's recent matches
   via the existing Riot key access module, run the threshold classifiers, emit tags into the
   existing cs_archetype_pick / champ-select payload; render as chips in the champ-select panel.
5. EFFORT+RISK: MED. Uses the EXISTING Riot key (in policy for champ-select team context) - but
   it is a NEW per-lobby Riot Match-V5 fan-out (10 players x recent matches = real API volume,
   rate-limit aware) -> "new-dep" in the sense of new external API load (not a new credential).
   No Claude, no DS schema change. The classifiers are deterministic + testable on fixtures.
   Risk: Match-V5 rate limits on a personal key for a 10-player fan-out; event modes excluded
   (known). Mitigate with caching + only the local player's allies if rate-limited.
6. LIFT: MED. Genuinely net-new and high-utility, all the classifier logic is deterministic over
   data RC can already fetch, but the per-lobby Riot fan-out is new API surface (rate-limit work)
   -> BACKLOG, not in-run-shippable.

### Finding 3.2 - Per-champion / per-skill / per-phase damage breakdown

1. WHAT: A breakdown of damage dealt split by source - per champion, per ABILITY (Q/W/E/R +
   auto + items), and per game PHASE (early/mid/late) - for every player live and post-game.
2. HOW: Live Client / Match-V5 damage attribution aggregated and bucketed by ability slot and by
   time interval. Mostly a reporting/visualization layer over telemetry that already exists in
   the data feed.
3. HAVE: RC's DS engine computes per-spell DPS/burst and damage composition deterministically
   (this is DS's core competency - per-spell CC, per-spell damage, archetype scorers). RC's
   THEORETICAL per-ability damage is richer than Overlay App F's observed split. What RC may lack is
   the OBSERVED post-game per-ability damage split from the actual match (vs DS's theoretical
   model). RC-grep-needed.
4. WHERE: If wanted, a PGR panel that buckets observed match damage by source - but the
   Match-V5 timeline does not cleanly attribute damage per ability slot, so this is largely
   already covered by DS's theoretical breakdown.
5. EFFORT+RISK: LOW to do a theoretical breakdown (DS already has it); HIGH to get a TRUE
   observed per-ability split (Riot does not expose per-ability damage cleanly).
6. LIFT: LOW / SUPERSEDED. RC's DS per-spell damage math already exceeds this; do not build a
   weaker observed version. No lift.

### Finding 3.3 - Personalized warding heatmap

1. WHAT: A map heatmap of "optimal" ward spots, blended from the player's own ward history and
   popular high-elo warding patterns, shown per-matchup/phase.
2. HOW: Aggregate ward-placement coordinates from match timelines (own + cohort), bin to a grid,
   render as a heatmap over the minimap image. Requires ward x/y coordinates from the timeline.
3. HAVE: RC has a vision pipeline (vision_tracker derives fog from Live Client position
   freshness) but NOTE: a documented RC constraint is that Live Client gives a ROLE string, NOT
   coordinates, and map dots are "impossible from Live Client". Ward COORDINATES would have to
   come from the Match-V5 timeline (post-game), not live. RC likely does NOT have a warding
   heatmap. RC-grep-needed.
4. WHERE: A POST-GAME panel (not live - live coords are unavailable per RC's own constraint):
   extract WARD_PLACED events with x/y from the Match-V5 timeline in rewind_history.db, bin to a
   grid, render a heatmap canvas over a static minimap asset.
5. EFFORT+RISK: MED. Post-game only (live is blocked by the known no-coordinates constraint).
   Data is in rewind_history timelines (ward events carry position). New canvas/heatmap render +
   a grid-binning pass. No Claude; no new Riot dep beyond what PGR already fetches. New UI
   surface -> not pure presentation over DS.
6. LIFT: MED (post-game only). Net-new and self-contained on local timeline data, but it is a new
   compute + canvas panel and is constrained to post-game by RC's live-coordinate limitation ->
   BACKLOG.

================================================================================
## SUMMARY TABLE
================================================================================

| Target | Finding | RC-HAVE? | LIFT | RC integration point | Effort/Risk |
|---|---|---|---|---|---|
| Aggregator C | 1.1 8-axis 0-100 skill radar (rolling, rank-percentile) | no (PGR is single-match) | MED | core/player_gpi.py + /api/player-profile + radar panel; data from rewind_history.db | MED / no new dep |
| Aggregator C | 1.2 weakest-axis call-out + tip | partial (single-match only) | LOW | bundle into player_gpi.py (static tip dict) | LOW / rides on 1.1 |
| Overlay App E | 2.1 enemy/ally ult + jungle CD timers | partial (summoner_cooldowns; DS has CD math) | MED | core/ability_cooldowns.py + overlay; CD math from DS | MED / cast-detect plumbing |
| Overlay App E | 2.2 live benchmarking overlay (metric vs rank curve) | partial (lead_projection) | MED-HIGH | precompute interval baselines from rewind_history.db + diff live liveclient; panel + overlay | LOW-MED / no new dep |
| Overlay App E | 2.3 auto runes/builds + personal-WR override | partial (DS builds superior; no LCU write) | MED | LCU rune-write wrapper + personal-WR override over DS builds | MED / touches frozen LCU via wrapper |
| Overlay App E | 2.4 post-game swing-moment localizer | mostly (PGR + reframe) | LOW | add timeline-delta "biggest swing" detector to PGR reframe | LOW-MED / folds into PGR |
| Overlay App F | 3.1 pre-game lobby player-tags (smurf/streak/OTP/tilt) | no | MED | core/lobby_tags.py over Riot Match-V5; chips in champ-select panel | MED / new per-lobby Riot fan-out (rate limit) |
| Overlay App F | 3.2 per-ability/per-phase damage breakdown | yes - DS supersedes (theoretical) | LOW/none | n/a (DS per-spell math already richer) | SUPERSEDED |
| Overlay App F | 3.3 personalized warding heatmap | no | MED | PGR-side: WARD events x/y from rewind_history timelines -> grid heatmap canvas | MED / post-game only (live coords blocked) |

================================================================================
## TRIAGE / SHIPPABILITY
================================================================================

In-run-shippable candidate (HIGH-lift AND low-risk, presentation over EXISTING data, no new
Riot/Claude dep, no DS schema lift, testable):
- **Overlay App E 2.2 - live benchmarking overlay** is the strongest single candidate IF lead_projection
  does not already cover per-interval CS/gold/vision baselines. It rides entirely on EXISTING
  live /api/state values + a one-time baseline extract from rewind_history.db (a data extract,
  not a schema lift). Gate strictly on grepping lead_projection first - if it already bands live
  metrics vs a curve, this collapses to no-lift.

Everything else is BACKLOG/FUTURE:
- Aggregator C 1.1/1.2: MED - new compute + new UI surface (not pure presentation), but all-local
  data and a clean longitudinal feature RC lacks. Best BACKLOG pickup.
- Overlay App E 2.1 (enemy CD timers): MED - DS CD math is free but live enemy-cast detection is real
  plumbing; ally/self ult timers are the cheaper subset.
- Overlay App E 2.3: MED - personal-WR override is cheap; LCU rune-write touches a frozen file (wrapper).
- Overlay App F 3.1 (lobby tags): MED - deterministic classifiers but a NEW per-lobby Riot fan-out
  with rate-limit work; net-new and high-utility, good BACKLOG.
- Overlay App F 3.3 (ward heatmap): MED - post-game only (RC's no-live-coordinate constraint),
  self-contained on local timeline data.

SUPERSEDED (no lift - RC already ahead):
- Overlay App F 3.2 per-ability damage breakdown: DS per-spell DPS/burst math already exceeds the
  observed split. Do not build a weaker version.
- Overlay App E 2.4 grading is mostly at-parity with RC's PGR + the in-progress aggregator G reframe; only the
  swing-moment localizer is net-new and it folds into existing PGR work.

CAVEATS:
- Overlay App F live pages are Cloudflare-gated and Overlay App E/Aggregator C support KBs are login-gated, so
  no in-the-clear API payloads were captured; mechanic shapes are from rendered public product
  pages + independent teardowns and are marked inferred where the exact thresholds/weights are
  proprietary.
- All RC-HAVE assessments are web-inference only and tagged RC-grep-needed; the orchestrator must
  confirm against the live tree (especially lead_projection scope, summoner_cooldowns scope, and
  whether champ-select already tags lobby players) before committing any lift.

================================================================================
## ORCHESTRATOR VERIFICATION + OUTCOME (2026-06-16, run -03)
================================================================================

The agent's RC-HAVE flags were ground-truth re-verified against the live tree
(feedback_verify_generated_reports). Results:

- Overlay App E 2.2 (live benchmarking): PARTIALLY SUPERSEDED + the net-new half SHIPPED.
  RC already bands live CS/gold/level via core/lead_projection.project_lead, but
  against a FLAT heuristic curve (~8 cs/min), NOT a personal one. RC ALSO has
  per-champion PERSONAL percentile distributions (core/benchmarks.rank_value over
  data/coach_reference/champion_benchmarks.json, 186 champ entries with
  p25/p50/p75) - but consumed ONLY post-game (core/aftergame_summary). The genuine
  net-new delta was wiring the personal percentile into a LIVE read. SHIPPED this
  run as core/live_benchmark_band.py [LBAND1, commit a8158629] - SR-only, cs+level
  only (gold excluded: live on-hand vs benchmark total/at-frame semantic mismatch),
  checkpoint-gated (~10:00 / ~15:00), >=5-games gate. Pure generator, no live-coach
  consumer yet (the live wire-in is FUTURE, do-not-flip-blind). +10 hermetic tests.

- Overlay App F 3.2 (per-ability damage): SUPERSEDED (DS per-spell DPS/burst is richer). No lift.
- Overlay App E 2.4 (grading) + 2.1-ult-CD (self/ally): mostly at-parity with PGR / DS CD math.

BACKLOG (FUTURE - new dependency / new compute+UI / live coords / product call):
- Aggregator C 1.1+1.2 (8-axis longitudinal player skill radar, rolling percentile)
  - MED, new compute + UI over rewind_history.db, no new dep.
- Overlay App F 3.1 (pre-game lobby player tags: smurf/streak/OTP/tilt) - MED, new
  per-lobby Riot Match-V5 fan-out (rate-limit work).
- Overlay App F 3.3 (post-game warding heatmap from timeline WARD x/y) - MED, new
  compute + canvas panel, post-game only (RC live-coordinate constraint).
- Overlay App E 2.1 (ENEMY ult-CD timers) - MED, enemy cast-detection plumbing (Live
  Client does not expose enemy CDs).
- Overlay App E 2.3 (LCU rune-page auto-write + personal-WR build override) - MED, touches
  frozen lcu_client.py via a wrapper.
- LBAND1 live wire-in: feed live_benchmark_band into the deterministic-coaching
  /api/state surface + the overlay, validate vs a real/replayed game, then flip.

No HIGH-lift-low-risk finding beyond the LBAND1 slice already shipped; all others
correctly deferred to BACKLOG per the Section-7b ACT gate.
