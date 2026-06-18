# Competitor Lift Teardown - 2026-06-18 (R2, Section 7b deep-dive)

**Targets:** four heavyweight public player-analytics tools NOT covered by the
prior teardowns - **aggregator B**, **aggregator A** (web + Desktop app, incl. OP Score),
**Aggregator Z1**, **aggregator G**. (R1 today = Aggregator H; prior = calc.gg
2026-05-30, seb16120 + simulator tool R 2026-06-08, Aggregator C GPI + Overlay App E +
Overlay App F 2026-06-16.)

**Method:** four heavyweight parallel general-purpose research agents (depth over
breadth per Section 7b), one per target, each carrying the full don't-redo set
+ the 6-point depth checklist (WHAT / HOW / HAVE-grep-RC-cite / WHERE /
EFFORT+RISK / LIFT). EVERY load-bearing HAVE claim was re-verified by the
orchestrator against the live RC tree before publishing - which caught a wrong
agent HAVE (see below). Lift policy: re-implement in RC's own code, never vendor.

**Access caveat (honest):** aggregator B / aggregator A / aggregator Z1 are Cloudflare / anti-bot
gated to headless fetchers (WebFetch 403). aggregator G's `aggregator G build API`
XHR shapes WERE captured firsthand; the other three rest on each site's own
help/product text via search + reputable third-party teardowns, tagged where
the exact shape was not byte-captured. Marketing copy was treated as a claim,
not implementation.

## Bottom line

RC broadly supersedes or already-has nearly the entire surface across all four:
the per-champion DPS/EHP/build math (DS engine), the 8-axis longitudinal skill
radar (`core/player_gpi.py`), self-relative percentile banding
(`core/benchmarks.py`, `core/live_benchmark_band.py`), the item/skill/rune/spell
win-probability decomposition (build-insights WPA lane, COMPLETE), 1v1 matchup,
duo-synergy, draft Elo, win-rate-by-game-length (shipped R1 today), and - the
key verify-gate catch - the **aggregator-G-style win-probability "match flow" curve**,
which `web/js/panels/pgr_winprob.js` already ships (the aggregator G agent's "best
NOW" was REFUTED at the gate: it read only `post_game_phases.js` and missed the
graph panel next to it).

One genuine own-player gap survived verification and is ALSO the best in-run
candidate: a **per-minute averaged performance curve** (Aggregator Z1's signature
"performance graph") - average cumulative gold / CS per game minute over the
operator's own corpus, split wins vs losses. RC reads the per-minute
`timeline_frames` for single matches and collapses each game to one number in
`player_gpi`, but never aggregated a per-minute curve across games. **That
finding (F-DPM) was SHIPPED in-run this cycle** as a "Game Flow" tab on the
Build Insights view. Everything else is FUTURE or CLOSED.

## SHIPPED this run - F-DPM per-minute performance curve

- WHAT: the tracked player's average cumulative gold (or creep score) at each
  game minute, split into the games WON (green) vs LOST (red), per mode, as an
  inline-SVG dual line. A win line pulling away early reads as snowballing
  leads; a flat loss line reads as stalling there.
- HOW: join `matches.tracked_champion_id + tracked_team_id` ->
  `participants.participant_id` -> `timeline_frames` (same join `player_gpi`
  uses), bucket each frame by `timestamp_ms // 60000`, average the cumulative
  `total_gold` (or `minions_killed + jungle_minions`) across games per minute,
  split by `tracked_win`. Sentinel-id double-join deduped keep-first per match;
  MIN_GAMES_N=5 gate per (minute, result); MAX_MINUTE=45 cap.
- HAVE (pre-this-cycle): NO as a feature. `player_gpi.py:128-146` collapses each
  game to a single end-of-game per-minute scalar (dpm/cspm/gpm), no intra-game
  curve, no aggregation across games. The replay surface reads per-minute frames
  but single-match only. Confirmed no `perf_curve` / per-minute averaged-curve
  symbol in the tree.
- WHERE (as shipped): `core/perf_curve.py` (pure aggregation, `conn=` test seam)
  -> `dashboard/routes_perf_curve.py` GET `/api/perf-curve?mode=&metric=&champion=`
  (registered in `dashboard/_dispatch.py`) -> `web/js/panels/perf_curve.js`
  (self-contained SVG panel) mounted as the Build Insights "Game Flow" tab
  (`web/index.html`, dispatched from `build_insights.js::_renderActive`).
- EFFORT+RISK: LOW. Additive presentation/aggregation over EXISTING local data;
  no new dependency, no Riot/Claude call, no DS schema change; touches no
  existing code path. Tier-1. Damage-per-minute deliberately EXCLUDED (timeline
  `total_dmg` is cumulative AND all-units, not to-champs - would mislead; a
  separate batch needs the right field).
- LIFT: HIGH (shipped). Live-verified aram/gold n=2004, sr/cs n=618; the
  win/loss gold separation is real (ARAM wins ahead by min5 4320 vs 4152,
  widening to min15 11503 vs 10906; SR wins ahead by min14 5973 vs 5414).

### Verify-gate catch (the aggregator G "NOW" was already shipped)

The aggregator G agent proposed the win-probability trajectory curve as the best NOW
lift. The orchestrator verified against the live tree FIRST and found
`web/js/panels/pgr_winprob.js` (PGR reframe S3) already renders exactly that -
an inline-SVG team-win-probability line over game time off the same
`/api/post-game-wpa` `events[]` array, with a ui_mock fixture + DOM test. The
agent had checked only `post_game_phases.js` (the top-3 cards) and missed the
graph. Reclassified CLOSED. This is why every HAVE claim is re-verified before
acting (mirrors the Aggregator H gate).

## Findings + triage

| ID | Target | Finding | Triage | Reason |
|----|--------|---------|--------|--------|
| F-DPM | Aggregator Z1 | Per-minute averaged performance curve (gold/CS, win-vs-loss) | **NOW (SHIPPED)** | HIGH value, LOW risk, pure aggregation over timeline RC already reads; no new dep/schema. The one own-player viz RC lacked |
| F-UGG1 | aggregator B | gold_share + carry-efficiency (kp/gold-share) in the per-match grade | FUTURE | gold_share verified 0 hits repo-wide (real gap), BUT its home is `core/post_game_rubric.py` = Tier-2 grade re-baseline + a product/calibration call (not auto-flip) |
| F-AGGREGATOR A1 | aggregator A | OP Score per-INTERVAL performance curve | FUTURE | Distinct from F-DPM (performance score, not gold) and from pgr_winprob (win-prob); needs a NEW per-interval scoring model + validation. MED |
| F-DLOL1 | aggregator G | Win-probability "match flow" curve | CLOSED | Already shipped: `web/js/panels/pgr_winprob.js` (PGR reframe S3) |
| F-DLOL2 | aggregator G | Lane-vs-full +/- WPA totals rider | FUTURE/LOW | Small sum over the same `events[]`; marginal, defer |
| F-DPM2 | Aggregator Z1 | Damage-share / DPM per-minute curve | FUTURE | The cumulative-all-units `total_dmg` trap; needs a to-champions per-frame field RC does not store |
| F-* | all | Global tier-lists / pick-ban / cross-player MMR / "better than X% of OTHERS" / live-lobby 10-player scout / pro DB | FUTURE/CLOSED | Need a global cross-player corpus RC does not hold (single-player by design); live-scout = the Overlay App F lobby-tags item already on BACKLOG |
| F-* | aggregator A/aggregator G | per-game absolute 0-10 / AI grade, MVP/ACE, AI win-prediction, AI chatbot | CLOSED | RC's rubric + WPA is richer/own-corpus; ML win-pred is CLOSED; an LLM chatbot runs counter to the Haiku-to-ZERO charter |
| F-* | all | builds / runes / skills / counters / synergy, WR-tagged | CLOSED | RC engine-computed builds + WPA + matchup + duo-synergy at-parity or superior |

## Net

After firsthand verification of every HAVE claim, three of the four agents' top
"NOW" picks collapsed (aggregator G = already shipped; aggregator B = Tier-2/product-gated;
aggregator A = MED new-scoring) leaving ONE clean HIGH-lift LOW-risk own-data finding
(F-DPM), shipped in-run as the Build Insights "Game Flow" tab and validated live
over the real corpus. F-UGG1 / F-AGGREGATOR A1 / F-DLOL2 / F-DPM2 -> BACKLOG (FUTURE);
the global-corpus and AI-grade families are CLOSED (RC single-player / superseded
/ charter-conflicting). No competitor in this wave exposed an own-player
mechanic RC lacks beyond F-DPM.
