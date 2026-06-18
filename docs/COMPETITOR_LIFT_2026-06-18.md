# Competitor Lift Teardown - 2026-06-18 (R1, Section 7b deep-dive)

**Target:** Aggregator H (aggregator H) - a heavyweight public League stats
site not covered by the prior teardowns (calc.gg 2026-05-30, the seb16120 stat
advisor + simulator tool R 2026-06-08, Aggregator C GPI + Overlay App E + Overlay App F 2026-06-16).

**Method:** one heavyweight general-purpose research agent (depth over breadth per
Section 7b), 6-point depth checklist per finding (WHAT / HOW / HAVE-grep-RC-cite /
WHERE / EFFORT+RISK / LIFT verdict). Every load-bearing HAVE/WHERE claim was
re-verified against the live RC tree (file:line) by the orchestrator before
publishing. Lift policy: re-implement in RC's own code only, never vendor.

## Bottom line

RC broadly supersedes or already-has most of Aggregator H' surface: the
per-champion DPS/EHP/build math (DS engine), the longitudinal multi-axis skill
profile (`core/player_gpi.py`, the GPI radar shipped 2026-06-16), live metric-vs-
baseline banding (`core/live_benchmark_band.py`), and the per-item/skill/rune/spell
win-probability decomposition (the build-insights WPA lane, COMPLETE). One genuine,
distinctive gap surfaced that is ALSO the best in-run candidate: Aggregator H'
signature **win-rate-by-game-length curve**. It is a pure aggregation over
`game_duration_s` + `tracked_win` that RC already reads from the local
`rewind_history.db`, needs no new external dependency / Riot or Claude call / DS
schema change, and is highly testable. **That finding (F1) was SHIPPED in-run this
cycle** as a new "Game Length" tab on the Build Insights view. Everything else is
FUTURE or CLOSED.

## SHIPPED this run - F1 win-rate-by-game-length

- WHAT: the tracked player's win % bucketed by match duration, per mode, as
  horizontal bars. An upward slope across longer-game buckets reads as a
  scaling / late-game tendency; a downward slope as an early-game / snowball
  tendency. (Aggregator H ships this server-side over its global corpus;
  RC computes it over the operator's OWN corpus = personal + descriptive.)
- HOW: group `matches` rows by a duration bucket, win% = wins/games per bucket.
  Inputs (`matches.game_duration_s`, `tracked_win`, `map_id`, `tracked_champion_id`)
  all live on one table - no participants/teams join. Mode filter via `map_id`
  (11/12/30) reusing the `core.player_gpi.MODE_MAPS` convention so map 12 folds
  every ARAM queue automatically.
- HAVE (pre-this-cycle): NO as a feature. RC read the exact inputs
  (`core/replay_history.py:38,79,91`; `core/aftergame_summary.py:109-131`) but never
  bucketed win-rate by duration (`core/aftergame_summary.py` used duration only as a
  per-game scalar). Confirmed no prior `duration_winrate` / `winrate_by` / `game_length`
  symbol in the tree.
- WHERE (as shipped): `core/duration_winrate.py` (pure aggregation, `conn=` test
  seam) -> `dashboard/routes_duration_winrate.py` GET `/api/duration-winrate?mode=&champion=`
  (registered in `dashboard/_dispatch.py`) -> `web/js/panels/duration_winrate.js`
  (self-contained chart panel) mounted as the Build Insights "Game Length" tab
  (`web/index.html`, dispatched from `build_insights.js::_renderActive`).
- EFFORT+RISK: LOW. Presentation/aggregation over EXISTING local data; no new
  dependency, no schema lift; Tier-1. Risk = single-player per-bucket sample
  thinness, mitigated by a MIN_BUCKET_N=5 gate (a thin bucket renders "-").
- LIFT: HIGH (shipped).

### Data-quality root-cause caught at the verify gate (NOT in the agent's spec)

`matches.game_duration_s` is NOT uniformly seconds: MIN=66, p50=1211, p99=2395, but
MAX=1988073 (4 rows >= 100000 are ms-encoded / corrupt, with a clean 3600-100000s
gap of ZERO rows). A naive open-ended top bucket would have swallowed those 4 rows
and reported a garbage long-game win-rate. The shipped module drops them via a
`MAX_DURATION_S=7200` ceiling (no real game reaches 2h) + the `MIN_DURATION_S=300`
remake gate (mirrors player_gpi). Validated live over the real corpus: ARAM n=2044
shows a clean downward slope (56.2 / 51.1 / 49.4 / 48.2 = a snowball tendency); SR
n=683 peaks 30-35m at 60.2 then drops to 41.0 at 35m+. The curve is meaningful and
non-trivial over real data.

## Findings + triage

| ID | Surface | Finding | Triage | Reason |
|----|---------|---------|--------|--------|
| F1 | Champion stats | Win-rate-by-game-length curve | **NOW (SHIPPED)** | HIGH value, LOW risk, pure aggregation over data RC already reads; no new dep/schema |
| F2 | Champion stats | Global win/pick/ban + popularity | FUTURE | Needs a new global champ-stats feed; conflicts with single-player scope |
| F3 | Build pages | Builds/runes/skills/counters/synergy, WR-tagged | CLOSED | RC engine-computed builds + WPA lane + matchup + duo-synergy at-parity or superior |
| F4 | Profile | Power Circle (Combat/Income/Map Control) | CLOSED | `core/player_gpi.py` 8-axis radar covers the metric families (shipped 2026-06-16) |
| F5 | Profile | "Better than X% of players" percentile | CLOSED/LOW | Self-relative percentile exists (`core/benchmarks.rank_value`); cross-player version needs data RC lacks |
| F6 | Profile | Live-game checker (10-player rank/WR/streaks) | FUTURE | Same as the Overlay App F 3.1 lobby-tags item already on BACKLOG; a new per-lobby Riot fan-out, not owned-data presentation |
| F7 | Global/tier | Objective rates / tier lists / leaderboards | FUTURE/CLOSED | Global corpus / ladder feed needed; own-corpus game-length distribution subsumed by F1 |

### F2 - global win/pick/ban + popularity prose
- WHAT/HOW: per-champion global win/pick/ban + avg KDA over all-server matches, daily refresh.
- HAVE: PARTIAL / by-design-different. RC is single-player; it has the player's own per-champion
  stats (`core/benchmarks.py`, `core/player_gpi.py`) but no global cross-player aggregate.
  RC's pick/ban intelligence is draft-context (`dashboard/routes_pickban.py`, `core/draft_elo.py`).
- WHERE/EFFORT/RISK: would require a NEW external global-stats feed; conflicts with the single-player
  design center. LIFT: LOW / FUTURE.

### F3 - builds / runes / skills / counters / synergy (WR-tagged)
- HAVE: YES, RC supersedes. Builds + skill order are ENGINE-computed (`core/build_order.py`,
  `agents/daemon_slayer/*`, `core/precomputed_build_coach.py`) not scraped; item/skill/rune/spell
  WPA decomposition is COMPLETE (`core/item_wpa.py`, `core/rune_wpa.py`, `core/skill_wpa.py`,
  `core/summoner_spell_wpa.py`, build-insights view); 1v1 matchup SHIPPED
  (`agents/daemon_slayer/matchup.py` + `web/js/panels/ds_matchup.js`); teammate synergy SHIPPED
  (`core/smoothed_rates_101qq.py` duo-synergy); draft counter/synergy via `core/draft_elo.py`.
  LIFT: CLOSED.

### F4 - Power Circle (Combat / Income / Map Control vs bracket)
- HAVE: YES (functional equivalent). `core/player_gpi.py` computes an 8-axis longitudinal skill
  profile over `rewind_history.db` (aggression/farming/vision/objectives/survival/tempo +
  versatility + consistency), self-relative percentiles, with a weakest-axis improvement tip.
  Same metric families, radar-shaped. LIFT: CLOSED.

### F5 - "better than X% of players" percentile framing
- HAVE: PARTIAL. RC has the percentile machinery self-relative (`core/benchmarks.rank_value`
  p25/p50/p75 of the player's OWN history; `core/player_gpi.py` axis percentiles). It cannot
  honestly say "better than X% of OTHER players" - no global cross-player distribution. The
  honest self-relative version already exists. LIFT: CLOSED / LOW.

### F6 - live-game checker (champ-select 10-player tags)
- HAVE: PARTIAL. RC reads LCU champ-select + has draft/pickban context
  (`dashboard/routes_pickban.py`, `core/pickban_targets.py`, `web/js/panels/champ_select.js`)
  + a valid Riot key (champ-select team context in policy, ADR-006), but surfaces no per-opponent
  WR/behavioral tags. SAME as the Overlay App F 3.1 lobby-tags finding already triaged to BACKLOG
  (2026-06-16). EFFORT: a NEW per-lobby 10-player Riot Match-V5 fan-out (rate-limit work).
  LIFT: FUTURE (already on BACKLOG - do not re-pitch as new).

### F7 - global objective rates / tier lists / leaderboards
- HAVE: NO, out of scope. Needs a global cross-player corpus / ladder feed RC does not hold.
  The only owned-data slice (the player's-own game-length DISTRIBUTION) is subsumed by F1's module.
  LIFT: FUTURE / CLOSED.

## Access / rendering gaps

- aggregator H is Cloudflare-gated to automated fetchers: WebFetch returned HTTP 403 on
  every Aggregator H URL; the firecrawl CLI is present but unauthenticated; Windows-MCP Scrape
  uses the same 403 path. A connected Chrome extension could render firsthand but would require an
  interactive prompt, inappropriate for a headless run and not load-bearing.
- Consequence: the EXISTENCE of the win-rate-by-game-length / by-games-played / by-experience
  graphs is confirmed via authoritative secondary sources (LoG's own product announcement, a 2026
  third-party teardown, and `/champions/winrates-by-xp` result titles). The EXACT LoG duration
  bucket boundaries were not byte-captured; F1 therefore picked RC-appropriate bins
  (`<15 / 15-20 / 20-25 / 25-30 / 30-35 / 35m+`) tuned to the ARAM-dominant corpus rather than
  LoG's SR-tuned bins. All RC HAVE/WHERE claims were verified firsthand against the live tree.

## Net

One HIGH-lift LOW-risk presentation finding (F1) shipped in-run as the Build Insights Game Length
tab, validated live over the real corpus. F2/F6/F7 are FUTURE (new external dependency or already
on BACKLOG); F3/F4/F5 are CLOSED (RC at-parity or superior). No new BACKLOG items required - F6 is
already tracked (Overlay App F 3.1 lobby-tags).
