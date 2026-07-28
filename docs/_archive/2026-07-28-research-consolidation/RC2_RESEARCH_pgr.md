# RC 2.0 Phase-1 Research - Stage 1.6: POST-GAME-REVIEW references

Grounded, cited survey of how external League stats tools build their post-game-analysis
surfaces (aggregator G, league-of-graphs, aggregator A, Aggregator B, Aggregator C GPI, Overlay App E), and what of it
is legally re-implementable into Riot Commander's stdlib-Python + vanilla-JS dashboard.

ASCII only. No em/en dashes or smart quotes (repo hard rule). Cite-first.

- Author pass date: 2026-06-19
- Scope: per-role grading rubrics, gold/CS/XP diff @10/@15, damage share, vision score,
  objective + kill participation, "what to improve" coaching summaries, lane-vs-lane
  comparison, single-match deep layouts, the aggregator-G-style 0-100 score.
- Method: WebSearch/WebFetch over aggregator A / aggregator G / Aggregator B / aggregator C / league-of-graphs /
  overlay app E, plus repo grep of the live PGR surface. NOTE: most `.gg` help/article pages return
  HTTP 403 to automated fetch; those patterns are sourced from the search-result snippets +
  publicly documented behavior and flagged inline where the exact internals are proprietary
  (aggregator G especially publishes no weight breakdown).

---

## 0. RC's CURRENT PGR surface (ground truth from repo)

RC is FAR along here - the single-match Post Game Review already ships most of the
aggregator G/aggregator A/aggregator C pattern set. The "Last Match" view (route `last-match`, internally
"Post Game Review") is the surface. There is NO external chart/grade library; every score,
radar, and curve is authored in stdlib Python + vanilla JS.

What exists today:

| Surface | File:line | What it renders |
|---|---|---|
| aggregator-G-style 0-100 hero match score | `web/js/panels/last_match.js:771-807` (`_scoreTier`, `_setHeroScore`) | Operator's 0-100 score + tier label (Excellent/Good/OK/Bad) in the hero. |
| Per-player 0-100 + MVP/SVP roster | `web/js/panels/last_match.js:854-922` (`_renderMvpCard`, `_rosterScores`) | aggregator-A-style MVP (best on winning side) / SVP (best on losing side) cards + per-row 0-100 chip. Weighted blend of KDA/damage/gold/CS/vision/tanked, each lobby-normalized. |
| Per-ROLE letter grade (S+..D) | `core/post_game_rubric.py` -> `web/js/panels/last_match.js:814-847` (`_setHeroRoleGrade`) via `GET /api/post-game-rubric` | Role-aware rubric: per-role weight vector + empirical baselines from 5957 ranked rows. |
| 8-axis GPI radar (longitudinal) | `core/player_gpi.py` -> `GET /api/player-profile` | Aggregator-C-profile-style radar: aggression/farming/vision/... 0-100, self-relative percentile. |
| Lane / role head-to-head | `web/js/panels/pgr_lane_compare.js` (`renderPgrLaneCompare`) | Operator vs same-role enemy: gold@N / cs@N + final gold/cs/damage/KP bars with +/- deltas. |
| Win-probability curve + swing phases | `web/js/panels/pgr_winprob.js`, `post_game_phases.js` <- `core/post_game_score.py` via `GET /api/post-game-wpa` | Inline-SVG win-prob curve + top-3 WPA "phases that mattered" cards. |
| "What to improve" quick review | `dashboard/builders_last_match.py:205` (`_compute_quick_review`) | 3 columns of `{text, why}`: right (positives), wrong_team (team issues), my_chronic (repeated cross-history patterns). |
| Team-aggregate comparison bars | `web/js/panels/last_match.js:992-1057` (`_setChart`) | Ally-vs-enemy kills/deaths/damage/tanked/gold/vision + towers/dragons/barons/heralds (SR). |
| Per-minute diff sparklines | `web/js/panels/last_match.js:1070-1155` (`_setTimeline`, `_tlSparkline`) | gold/xp/cs diff (ally minus enemy) sparklines + objective-event ribbon. |
| Build graded by career (WPA) | `web/js/panels/pgr_build_wpa.js` (`renderPgrBuildWpa`) | Career item-WPA + skill-WPA chips on this match's loadout. |
| Rank-tier comparison row | `web/js/panels/last_match.js:187-208, 469-509` | Hand-curated iron..challenger per-mode averages (cs/kda/kp/damage/vision...) for context. |

Sibling Python feeders already present: `core/carry_share.py` (gold_share + KP),
`core/obj_participation.py` (objective participation), `core/aftergame_summary.py`,
`core/match_metrics.py` (per-game-time milestone metric store with provenance tiers).

Key architectural facts:
- The 0-100 hero score and the per-role letter grade are TWO DISTINCT systems that compose
  visually: `_rosterScores` is lobby-relative (aggregator A flavor); `post_game_rubric` is
  role-baseline-relative (Riot S-grade flavor). Both already shipped (item 131, item 335).
- `post_game_rubric.py` is explicitly calibrated to the public unrankedsmurfs writeup of
  Riot's S-grade emphasis ordering (`core/post_game_rubric.py:3-8`); Riot's exact weights
  are NOT public, so RC uses source-cited emphasis ordering + empirical local baselines.
- A `carry_efficiency` fold (aggregator-B-style gold-share + KP additive axis) is already CODED but
  DEFAULT-OFF behind a flag (`core/post_game_rubric.py:405-489`); enabling it is a gated
  grade re-baseline, not new code.

Implication for RC 2.0: this is a polish + fill-gaps surface, not a green-field build. The
high-value lifts are the few missing patterns (damage-per-gold, vision-per-min normalization,
@10/@15 timeline grade context, a tighter "what to improve" narrative), NOT re-pitching a
score that already exists.

---

## 1. aggregator A - OP Score + MVP/ACE

**WHAT.** OP Score is aggregator A's 0-10 (displayed) per-player rating computed from kills, deaths,
assists, CS, and gold. A timeline OP Score is recomputed every 5 min on Summoner's Rift and
every 3 min in ARAM; the value at match end is the recorded score. MVP = highest OP Score on
the WINNING team; ACE = highest on the LOSING team. aggregator A also surfaces up to 14 shaped
keywords from the score curve (e.g. "Tenacity", "Unstoppable", "Indomitable Will"). OP Score
is flagged beta. (Sources: aggregator A Help Center "OP Score explained" + "Understanding MVP and
ACE criteria", via search snippets - both pages 403 on direct fetch.)

**HOW.** A composite of the standard KDA + CS + gold scalars, recomputed at a fixed timeline
cadence so the score has a per-phase trajectory (not just a final number), then ranked within
the 10-player lobby to assign MVP/ACE.

**RC ALREADY HAS IT.** YES (substantially). MVP/SVP per side + per-row 0-100 lobby-ranked
score is live in `web/js/panels/last_match.js:854-922` (`_rosterScores` blends KDA + damage +
gold + CS + vision + tanked, lobby-normalized). RC labels the loser's best "SVP" rather than
"ACE" but it is the identical pattern. GAP vs aggregator A: RC's score is FINAL-only; aggregator A recomputes
on a 5min/3min timeline. RC has the per-minute timeline data to do this
(`data/rewind_history.db` `timeline_frames`, see `dashboard/builders_lcu_enrich.py`) but does
not yet compute a per-phase OP-Score trajectory in the roster card.

**WHERE IT INTEGRATES.** `_rosterScores` already consumes the roster; a timeline variant would
read `timeline_frames` per participant (gold/cs/xp at each frame) and emit a small score curve.
The `op_score.js` panel (cited in `RC2_RESEARCH_timeline.md`) already draws a per-minute 0-100
composite for the rewind corpus, so the curve-drawing primitive exists.

**EFFORT+RISK.** MED effort / LOW risk for a per-phase score curve (data + curve primitive both
present; pure compute + one SVG). The "14 keywords" feature is LOW value (aggregator A's are flavor).

**LIFT VERDICT.** MED. The core (MVP/ACE + 0-100) is DONE. Only the timeline-cadence score
trajectory is worth lifting, and it is incremental. Legal: re-implementing a KDA/CS/gold
composite from your own Match-V5 data is fine; do NOT copy aggregator A's exact (beta, unpublished)
coefficients or keyword strings.

---

## 2. aggregator G - AI-Score

**WHAT.** aggregator G's headline feature is an "AI-Score" + AI tier prediction shown per match and
per player, marketed as an ML model over match data. (Source: aggregator G homepage via search.)
The EXACT component breakdown (how laning/teamfighting/objective/vision roll into the number)
is NOT published anywhere I could find - aggregator G does not document weights or sub-axes. A
commonly described adjacent pattern in this tool class is a 5-axis performance pentagon
(Combat / Growth-farming / Objectives / Vision / Survival) plus a laning-phase win ratio like
"4:6" - but that is the genre convention, not a confirmed aggregator G spec.

**HOW.** Proprietary ML scoring of post-game stats into a single 0-100-ish number + a tier
estimate. Unverifiable internals.

**RC ALREADY HAS IT.** YES, the consumer-facing equivalent. RC's hero 0-100 score
(`_setHeroScore`, `last_match.js:783-807`) is explicitly described in-code as "aggregator-G-style"
and the MVP card comments cite the aggregator G pattern (`last_match.js:849-853`). RC's number is a
transparent heuristic (documented in the row tooltip) rather than an opaque ML score - which
is a FEATURE for a single-user coaching tool, not a deficit.

**WHERE IT INTEGRATES.** Already integrated (hero block + roster). The only liftable IDEA is
the multi-axis DECOMPOSITION of the single score (show WHY the 78 is a 78: combat vs farm vs
vision vs objective sub-bars), which aggregator G/the pentagon convention implies. RC has every
input for that decomposition already (`core/carry_share.py`, `core/obj_participation.py`,
vision_score in the roster, the rubric `components` dict in
`core/post_game_rubric.py:461-475`).

**EFFORT+RISK.** LOW effort / LOW risk to surface the existing `components` dict from
`post_game_rubric` as a small per-axis breakdown bar under the hero grade (the data is already
computed and returned by `/api/post-game-rubric`, just not rendered as a breakdown).

**LIFT VERDICT.** HIGH (as a decomposition view, not as a new score). The single number exists;
exposing its already-computed sub-components is cheap and is the single most coaching-useful
aggregator-G-flavored addition. Legal: trivially, since the decomposition is RC's own rubric.

---

## 3. Aggregator C - Gamer Performance Index (GPI)

**WHAT.** GPI is an 8-category 0-100 radar built by ML over your gameplay TREND (not a single
match): Aggression, Consistency, Farming, Fighting, Survivability (Toughness), Teamplay,
Versatility, Vision. 0 ~ Bronze, 100 ~ Challenger. It updates roughly every 10 games (a single
bad game barely moves it). Each category has documented sub-components (e.g. Farming = general
income + farm efficiency + early/mid/late CS & gpm; Vision = placement + denial + efficiency +
impact). (Sources: aggregator C/gpi - fetched OK; aggregator C/gpi ML page via search.)

**HOW.** Longitudinal aggregation: per-category score is an ML rollup of many stats across a
recent window, normalized to a rank-cohort 0-100 scale, presented as a radar.

**RC ALREADY HAS IT.** YES. `core/player_gpi.py` is an explicit GPI-radar lift (its docstring
cites "competitor-lift #1 ... the Aggregator C GPI radar"). It computes the same 8 axes
(`_RELATIVE_AXES` aggression/farming/vision/... at `core/player_gpi.py:50-52`+) over the
operator's local `rewind_history.db`, with per-axis improvement tips
(`core/player_gpi.py:63-67`). DIFFERENCE: RC scores SELF-RELATIVE percentiles (50 = your own
typical game) because it has no rank-cohort distributions locally; Aggregator C scores vs a rank
cohort. RC's choice is honest given no Riot-API cohort data.

**WHERE IT INTEGRATES.** Already wired to `/api/player-profile` + a radar panel. For the PGR
specifically, the lift is to show THIS MATCH'S point against the GPI radar (a single-match dot
overlaid on the longitudinal radar) so the post-game tells you which axis this game pulled up
or down. The single-match per-axis values are already computable from the same columns
`player_gpi` reads.

**EFFORT+RISK.** LOW-MED effort / LOW risk. The radar + axis math exist; overlaying one match's
axis values on the existing radar is a render + one compute reuse.

**LIFT VERDICT.** MED. The longitudinal radar is DONE. The PGR-specific "this match vs your
radar" overlay is a genuine, cheap addition that ties the single-match review to the trend.
Legal: it is RC's own GPI module; the 8-axis taxonomy is an idea, not copyrightable.

---

## 4. Aggregator B - advanced post-match metrics

**WHAT.** Aggregator B's post-game adds metrics beyond the in-client stats screen: Damage Share,
Gold Differential @15, Vision Score per Hour, CS@15, and kill participation (kills+assists over
team kills), with players listed in role order. (Sources: Aggregator B FAQ + playleagueoflegends /
third-party review site Z9 writeups via search.)

**HOW.** Standard Match-V5 + timeline-derived ratios: @15 snapshots from the timeline, share/
participation as simple team-normalized fractions, vision normalized per hour.

**RC ALREADY HAS IT.** PARTIAL. RC has: gold_share + KP (`core/carry_share.py`), vision_score
(roster), damage share via the team-aggregate chart (`last_match.js:1025`), and gold@N/cs@N at
the 10-min frame in lane-compare (`pgr_lane_compare.js:16-21`, fed by
`dashboard/builders_lcu_enrich.py`). GAPS: (a) RC snapshots @10, Aggregator B standardizes on @15
(both are in the timeline; `csd_at_15`/`gd_at_15` keys already exist in
`core/match_metrics.py:247-248`, so the @15 frame is reachable); (b) RC has no DAMAGE-PER-GOLD
metric and no VISION-PER-MINUTE normalization in the PGR.

**WHERE IT INTEGRATES.** Stat-grid in the hero (`_setStatsGrid`, `last_match.js:924-959`) +
lane-compare. Add damage-per-gold = damage_to_champs / gold (both already in the roster row),
and vision-per-min = vision_score / minutes. @15 snapshot reuses the same timeline-frame
fetch the @10 path already does.

**EFFORT+RISK.** LOW effort / LOW risk. All inputs are already in the roster + timeline; these
are pure derived ratios + one extra frame lookup.

**LIFT VERDICT.** HIGH. Damage-per-gold + vision-per-min + an @15 column are small, additive,
and high signal (damage-per-gold is widely cited as the most honest carry metric because it
normalizes for gold lead - see league-of-graphs below). Legal: arithmetic over your own data.

---

## 5. league-of-graphs - normalized comparison metrics

**WHAT.** league-of-graphs frames performance as normalized ratios rather than raw totals.
Combat tab: SV ratio (survival weighted for game length), kill participation, damage share,
support score, damage per death. Income tab: damage-per-gold, early-game gold diff @15,
early-game minion diff, minions/min. It logs CS/min PER GAME (not just season average) so you
can spot recent regressions. (Source: agatasmurf.com league-of-graphs writeup + dignitas
"how to measure best stats" via search.)

**HOW.** Per-game derived ratios normalized for game length / gold, displayed as comparison
rows vs lobby or vs your own history.

**RC ALREADY HAS IT.** PARTIAL. KP, damage share, CS/min/game are present. GAPS: damage-per-gold
(see #4), damage-per-death, and a length-weighted survival ratio (RC tracks deaths + time-dead
in `match_metrics` `time_dead_summary`/`time_alive_pct` but does not surface an SV-style
normalized survival score in the PGR).

**WHERE IT INTEGRATES.** Hero stat-grid + the team-aggregate chart. damage-per-death =
damage_to_champs / max(deaths,1) (roster has both). SV ratio reuses time_alive_pct +
duration. These are the same "normalize for length/gold" family as #4.

**EFFORT+RISK.** LOW effort / LOW risk (derived ratios over existing roster + match_metrics
fields).

**LIFT VERDICT.** HIGH (as the same damage-per-gold / damage-per-death / SV-ratio bundle as #4;
treat #4 and #5 as one combined "normalized carry-metrics" lift). The "this game vs my last 10"
per-game CS/min regression callout is also a strong, cheap "what to improve" hook RC's
`my_chronic` column could consume. Legal: standard derived stats.

---

## 6. Overlay App E - post-game insights + "level up" callouts

**WHAT.** Overlay App E analyzes the match and surfaces "key insights to level up your game" + tracked
performance metrics; its strength is in-game/champ-select real-time overlays (timers, build
paths) more than a deep post-game grade. Public docs do NOT detail a per-role grade rubric or
a structured "what to improve" taxonomy. (Source: overlay app E/lol + comparison writeups via
search; specifics on post-game grading not publicly documented.)

**HOW.** Heuristic insight callouts over match stats, surfaced as short tips.

**RC ALREADY HAS IT.** YES, and arguably deeper. RC's `_compute_quick_review`
(`dashboard/builders_last_match.py:205`) already emits structured `{text, why}` callouts in 3
buckets (right / wrong_team / my_chronic), and `core/aftergame_summary.py` +
`core/precomputed_replay_narrative.py` produce narrative game-sense blurbs. RC's coach can also
generate per-match "what to improve" via Haiku.

**WHERE IT INTEGRATES.** Already integrated (Quick Review section + AI Analysis tab).

**EFFORT+RISK.** N/A - nothing distinct to lift. Overlay App E's edge is its live overlay, which is the
subject of `RC2_RESEARCH_in_match_overlay.md`, not this PGR doc.

**LIFT VERDICT.** LOW. RC's post-game insight surface already meets or exceeds Overlay App E's public
post-game behavior. The only takeaway is editorial: keep callouts short + actionable + tied to
a "why", which RC already does via the `why` tooltip field.

---

## 7. Cross-cutting patterns + the single-match deep layout

Observed layout conventions across all six tools, mapped to RC's state:

| Pattern | Genre convention | RC state |
|---|---|---|
| One headline 0-100/0-10 score | aggregator A OP Score, aggregator G AI-Score | DONE (`_setHeroScore`) |
| MVP/ACE(SVP) badge | aggregator A MVP/ACE | DONE (`_renderMvpCard`) |
| Per-role letter grade | Riot S-grade lineage | DONE (`post_game_rubric.py`) |
| Multi-axis radar/pentagon | Aggregator C GPI, aggregator G pentagon | DONE longitudinal (`player_gpi.py`); MISSING single-match overlay |
| @10/@15 lane snapshot | Aggregator B, league-of-graphs @15 | PARTIAL (@10 lane-compare; @15 not surfaced) |
| Normalized carry ratios (dmg/gold, dmg/death, SV) | league-of-graphs, Aggregator B | MISSING (highest-value gap) |
| Win-prob "where the game turned" | aggregator G/genre | DONE (`pgr_winprob.js` + WPA phases) |
| Structured "what to improve" | Overlay App E, Aggregator C tips | DONE (`_compute_quick_review` + GPI tips) |
| Team-aggregate vs bars | all | DONE (`_setChart`) |
| Per-min diff curves | all | DONE (`_setTimeline`) |

Single-match deep layout: every tool stacks (1) a hero with one big score + result, (2) a
roster with per-player scores + MVP, (3) a stat-comparison block, (4) a timeline/curve, (5)
text insights. RC's Last Match view already follows this exact stack. RC 2.0's PGR work is
therefore: close the two real gaps (normalized carry ratios; @15 + single-match radar overlay),
and surface the already-computed rubric `components` as a decomposition - not a re-layout.

---

## 8. Consolidated lift ranking (legal re-implementation only)

HIGH:
1. Normalized carry-metrics bundle (damage-per-gold + damage-per-death + vision-per-min + SV
   ratio) - all inputs already in the roster + `match_metrics`; LOW effort, high signal,
   directly fills the Aggregator B / league-of-graphs gap. (sections 4, 5)
2. Score DECOMPOSITION under the hero grade - render the already-returned
   `post_game_rubric.components` (+ carry_share / obj_participation) as per-axis sub-bars so the
   single number is explainable. Data already computed. (section 2)
3. @15 lane/stat snapshot column - extend the existing @10 timeline-frame path to @15 (keys
   `csd_at_15`/`gd_at_15` already defined in `match_metrics`). (section 4)

MED:
4. aggregator-A-style timeline OP-Score trajectory (per-phase 0-100 curve in the roster) - reuses
   `timeline_frames` + the existing `op_score.js` curve primitive. (section 1)
5. Single-match dot overlaid on the GPI radar - reuse `player_gpi` axis math for one match.
   (section 3)

LOW / no-op:
6. Overlay App E post-game (RC already meets/exceeds). (section 6)
7. aggregator A 14-keyword flavor + aggregator G opaque ML score (intentionally not copied; RC's
   transparent heuristic is preferable for a single-user coaching tool). (sections 1, 2)

Legal note: every HIGH/MED item above is arithmetic or a taxonomy over RC's OWN Match-V5 /
rewind data. No external coefficients, keyword strings, or proprietary ML weights are lifted -
aggregator A/aggregator G do not publish theirs in any case, and `post_game_rubric.py` already documents
that Riot's exact weights are non-public and RC uses source-cited emphasis ordering instead.

---

## Sources

- aggregator A Help Center, "OP Score explained": https://aggregator-a.invalid/help/articles/31088715328665-OP-Score-explained (403 on fetch; content via search snippet)
- aggregator A Help Center, "Understanding MVP and ACE criteria": https://aggregator-a.invalid/help/articles/31092293690649-Understanding-MVP-and-ACE-criteria (403 on fetch; content via search snippet)
- aggregator G homepage (AI-Score / tier prediction): https://aggregator-g.invalid/
- Aggregator C GPI overview: https://aggregator-c.invalid/gpi/
- Aggregator C GPI (machine learning) + support: https://aggregator-c.invalid/support/sections/115000496991-GPI
- Aggregator B FAQ: https://aggregator-b.invalid/faq
- "Understanding Your Summoner Profile Stats: What Aggregator A and Aggregator B Actually Show" (Wombo Combo): https://review-site-z9.invalid/blog/summoner-lookup/understanding-summoner-profile-stats
- "Aggregator H: LoL Stats, Ranks & Win Rates" (agatasmurf writeup): https://agatasmurf.com/league-of-graphs/
- Dignitas, "How to Measure the Best Stats for Performance in League of Legends": https://dignitas.gg/articles/how-to-measure-the-best-stats-for-performance-in-league-of-legends
- LeagueMath, "Kill participation by role": https://www.leaguemath.com/kill-participation-by-role/
- Overlay App E LoL: https://overlay-app-e.invalid/lol
- unrankedsmurfs, Riot S/S+ grade algorithm writeup (RC rubric calibration reference, cited in `core/post_game_rubric.py:3`): https://www.unrankedsmurfs.com/blog/what-is-riot-algorithm-for-determining-s-and-s+-ranks
