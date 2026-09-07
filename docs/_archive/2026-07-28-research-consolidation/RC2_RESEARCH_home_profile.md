# RC 2.0 Phase-1 Research (stage 1.2): HOME / Player-Profile Landing Surface

Grounded, cited survey of how League companion apps present the HOME /
player-profile landing surface - the first screen you see when the app
opens and no game is live. Covers what is shown at a glance, layout
patterns, dark-theme telemetry density, onboarding, and a 6-point LIFT
verdict for each pattern against RC's current home surface.

ASCII only - no em-dashes, en-dashes, or smart quotes (repo hard rule).
Cited from live repo greps + web sources (URLs at bottom).
Date: 2026-06-19. Author: research subagent.

Scope filter applied throughout: RC is a SOLO single-player coaching tool.
Social graph, friends feeds, "spectate streamer", ads, premium upsell, and
multi-account scouting are explicitly OUT - flagged as NOISE, not lifted.

---

## 1. RC's CURRENT home surface (ground truth)

The Home view is the default landing whenever no game is live:
`web/js/main.js:662` maps `mode === "client" | "lobby" | !live -> "home"`.
The render pipeline is `_homeRefresh -> /api/home/summary` (no-store)
`main.js:2940`, dispatching to seven sub-renderers `main.js:2950`-`2959`.

The backend payload is built by `dashboard/builders_home.py`
`_build_home_summary()` (`builders_home.py:63`), reading the live-captured
`data/match_history.db` (today's rows present; `rewind_history.db` is NOT
used here - it is stale until a manual backfill, `builders_home.py:67`).

### 1a. What RC's home already surfaces (each panel + cite)

| RC home panel | Data | Source |
|---|---|---|
| TODAY cluster | games count, grade tally, mode tally, total + avg KDA | `builders_home.py:130`, render `_homeRenderToday` `main.js:2950` |
| Hero chips + inline sparklines | CS/min, gold/min, KDA each with a 14-day SVG sparkline drawn INTO the chip | `_homeRenderTrends` `main.js:2967`-`3038`; series `_home_trends_14d` `builders_home.py:295` |
| RECENT 5 | last 5 non-TFT matches: champ, grade (S-F), KDA, duration, CS, CS/min, build items; row click deep-links to History | `builders_home.py:92`-`112`, render `main.js:1907` |
| THIS WEEK | top-5 most-played champs (7d): games, avg KDA, K/D/A, CS total, CS/min, best grade, modes | `builders_home.py:143`-`174` |
| TONIGHT'S PICK | top this_week champ by avg KDA, tie-broken by games; reason string + Good/Bad/Ugly one-liners | `_home_tonight_pick` `builders_home.py:231`, tips `_home_pick_tips` `builders_home.py:203`, render `_homeRenderCoach` `main.js:3043` |
| LAST BUILD | most-recent local-player row from `postgame_stats.db`: champ + 6 items + 2 spells | `_home_last_build` `builders_home.py:252` |
| STREAKS | consecutive play-days + consecutive S/A grade run | `_home_streaks` `builders_home.py:341` |
| SERVICES | RC pid+mode, Vision :8889 up/down | `builders_home.py:181`-`193` |
| Trend pill / hot-cold streaks | 30d WR arrow, recent-vs-baseline WR delta, hot/cold champ list | `main.js:1472`-`1593` (adapt panel, shared) |

### 1b. The one structural gap

RC has NO RANK / TIER / LP surface anywhere on home. There is no
ranked-ladder read. `_build_home_summary` surfaces GRADE (S-F, an RC
heuristic over match stats) explicitly BECAUSE win/loss is not stored on
rows (`builders_home.py:70`). Every competitor below leads with rank +
LP + win rate as the hero element; RC leads with today's grade + KDA
trend. This is the single biggest at-a-glance divergence and the anchor
for the HIGH-lift findings.

---

## 2. External patterns - what each app shows at a glance

### 2.1 Aggregator A (the de-facto standard)
At-a-glance, top to bottom: current ranked tier badge + LP + solo/duo win
rate for the current split (updates within minutes of game end); then a
rank-history LP graph; then a recent-20 match list with color-coded KDA,
CS/min, vision score, damage; each row expands to full build / skill order
/ gold timeline. Champion-stats table below (per-champ WR, games, KDA).
The "OP Score" is a per-game 0-10 performance number with a timeline graph
and ~14 shape-derived keyword tags (e.g. "Unstoppable", "Indomitable
Will") plus MVP/ACE badges. Philosophy is a clean, compact, raw-data view
([happysmurf](https://review-site-z11.invalid/blog/what-is-aggregator-a/),
[help.aggregator A OP Score](https://aggregator-a.invalid/help/articles/31088715328665-OP-Score-explained)).

### 2.2 Aggregator B
Same skeleton as Aggregator A (rank, LP-per-game, recent matches, champ stats)
but differentiates on PERCENTILE BENCHMARKING: it shows your stat vs other
players at the same rank on the same champion, plus early-game phase deltas
(gold diff @15, XP diff @10, first-blood rate). It always shows game COUNT
next to a win rate so you can weigh significance. Most granular filter set
(game type / role / rank / region / patch)
([third-party review site Z9 summoner-stats](https://review-site-z9.invalid/blog/summoner-lookup/understanding-summoner-profile-stats)).

### 2.3 Aggregator C
The most "coaching"-shaped landing. The Summoner Profile frames you three
ways: game-to-game performance, year progression, and IDENTITY (champ pool
+ build styles). Core element is the GPI (Gamer Performance Index) radar -
skills like Fighting, Farming, Aggression scored on one graph with
specific written improvement advice per weak axis. Recent-games snapshot =
last-20 WR + champs played + matchups faced + performance on your top-2
champs, with a "this matchup has been giving you trouble" callout. Single
unified surface (champions, profile, live companion in one place)
([aggregator C profile feature](https://aggregator-c.invalid/blog/how-to-use-the-aggregator-c-summoner-profile-feature/),
[aggregator-a-vs-aggregator-c](https://aggregator-c.invalid/aggregator-a-vs-aggregator-c/)).

### 2.4 Overlay App E (desktop app, closest analog to RC)
Personal PERFORMANCE DASHBOARD that aggregates post-game grades into trend
lines per category, auto-identifies your strongest + weakest areas, and
generates WEEKLY SUMMARIES. Post-game grades land within ~2 minutes across
behavioral dimensions (CS efficiency, kill participation, objective
involvement, death quality) benchmarked against similar-rank play. Coaching
text "explains the specific pattern behind the grade" (e.g. missed CS in a
named time window) rather than showing a bare number. Pro tier adds champ-
pool comparison: "which champions in your pool most reward fighting-heavy
play" - a data-driven roster recommendation
([overlay app E/lol](https://overlay-app-e.invalid/lol),
[third-party review site Z9 overlay app E review](https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review)).

### 2.5 AGGREGATOR G.GG
Leads with AI-SCORE (per-game 0-100) and TIER PREDICTION (an ML-estimated
MMR/tier, distinct from the displayed rank). AI-driven insights surface
match flow, win rates, builds, counters. RC's own Post Game Review reframe
is explicitly modeled on aggregator G's single-match richer layout (CLAUDE.md
"aggregator-G-style Post Game Review", s220)
([aggregator G](https://m.aggregator-g.invalid/)).

### 2.6 Aggregator H
Stat-density leader. Pulls Riot API for champ WR, rank history, KDA, CS/min,
damage share, and notably PERCENTILE-RANKED stat bars on the profile (your
value plotted against the population). Also a champ-select live checker that
loads all 10 players. Running since 2013, the reference for "how much
telemetry fits on one page"
([aggregator H](https://aggregator-h.invalid/),
[agatasmurf LoG](https://agatasmurf.com/league-of-graphs/)).

### 2.7 Overlay App F (Overlay Platform M desktop app)
Profile tab = account status + recent games + season stats. Strength is
LANE-HABIT / playstyle profiling and champion-mastery emphasis ("master
your mains"). Match-history overview is explicitly framed around spotting
WEAK GAME PHASES (early/mid/late) and which champs yield best results -
a growth/trend lens rather than a raw dump
([overlay app F overlay platform M](https://overlay-platform-m.invalid/app/overlay-app-f),
[wecoach overlay app F guide](https://review-site-z12.invalid/blog/article/all-you-need-to-know-about-overlay-app-f-a-complete-guide)).

### 2.8 Cross-cutting layout + dark-theme density observations
- Universal vertical order: IDENTITY HEADER (rank/LP/WR + avatar) ->
  RECENT-FORM STRIP (last 20, color-coded W/L) -> CHAMP-POOL TABLE ->
  deep-dive panels. The header is always the densest, highest-contrast
  band.
- Recent form is universally a horizontal color-coded row (green win /
  red loss) for instant streak read - the single most copied element.
- Per-game composite SCORE (OP Score 0-10 / AI-Score 0-100 / Overlay App E grade)
  is now table stakes; all of them also attach a short WORD tag or
  pattern sentence, not just a number.
- Dark theme is universal; density is managed by (a) muted secondary text
  for labels, bright text for values, (b) small inline sparklines/bars
  rather than separate chart panels, (c) percentile bars to encode "good
  vs bad" as color without extra text. RC already does (a) and (b) on the
  hero chips (`main.js:2967`).
- Onboarding everywhere = "type Riot ID + tagline, get a page" - zero
  config. RC has no search box because it is single-account (the operator
  is SamplePlayer#Trist); RC's "onboarding" is implicit. This is a genuine
  simplification, not a gap.

---

## 3. LIFT checklist (6-point) per pattern

Legend: HAVE = RC already has it. EFFORT S/M/L. LIFT = recommendation
(HIGH / MED / LOW). Legal re-implementation only (all stats are
Riot-API-derived or RC-computed; no scraping of competitor UIs).

### P-A. Rank / tier / LP identity header
- WHAT: hero band with current ranked tier badge, LP, and split win rate.
- HOW: read `/lol-ranked/v1/current-ranked-stats` (or Riot League-V4) and
  paint a tier crest + LP + WR at top of home.
- HAVE: NO. No rank read anywhere on home (`builders_home.py` surfaces
  grade instead, by design `:70`). LCU ranked endpoint is not wired into
  the home payload.
- WHERE: new field on `_build_home_summary` out dict
  (`builders_home.py:74`) + a hero header element in the home view.
- EFFORT+RISK: M. LCU ranked read is straightforward; risk is RC plays
  mostly ARAM/Arena/event modes where solo-queue rank is stale or absent -
  header could read empty most nights.
- LIFT: HIGH (with a caveat) - this is THE universal element RC lacks, but
  pair it with a graceful "Unranked / no recent solo-queue" state because
  the operator is not a ladder grinder. See finding #1.

### P-B. Recent-form color-coded W/L strip
- WHAT: horizontal row of last-N games as green-win / red-loss pills for a
  one-glance streak read.
- HOW: map each recent match to a W/L color chip.
- HAVE: PARTIAL. RC has a Recent-5 list with grade glyphs
  (`main.js:1907`, `home-recent-grade`) but NOT win/loss - because W/L is
  not stored on match rows (`builders_home.py:70`). The grade (S-F) is the
  proxy.
- WHERE: `_homeRenderRecent` (`main.js:2951`) - swap/augment grade glyph
  with a W/L color border.
- EFFORT+RISK: M. Requires capturing win/loss at end-of-game ingest (an
  existing TODO, `builders_home.py:91` "would need an end-of-game ingest
  hook"). Risk: event modes (ARAM Mayhem) have weak Match-V5 (CLAUDE.md
  settled item).
- LIFT: HIGH - cheap, universal, high glance-value, and unblocks P-A's WR.
  See finding #2.

### P-C. Per-game composite score + word tag (OP Score / AI-Score style)
- WHAT: single 0-100 (or 0-10) performance number per game + a short
  pattern sentence.
- HOW: RC already HAS the engine - the grade (S-F) is exactly this, and
  the s220 PGR 0-100 score is the planned richer version.
- HAVE: YES (grade) / PLANNED (0-100). Grade computed live
  (`builders_home.py` reads `grade` col); the 0-100 PGR score is an
  RC heuristic with NO Claude/Riot dependency, staged S2-S5
  (CLAUDE.md "aggregator-G-style Post Game Review", `docs/research` PGR work).
- WHERE: already on Recent-5 + Tonight's Pick; extend with the PGR score
  when it ships.
- EFFORT+RISK: S (display) - the score work is separately scoped.
- LIFT: LOW (already covered / already planned) - do NOT re-pitch; note
  alignment only.

### P-D. GPI-style skill radar with per-axis advice (Aggregator C)
- WHAT: radar of skill axes (farming/fighting/aggression/vision...) each
  scored, with written "improve this" advice on weak axes.
- HOW: aggregate per-axis percentiles from match stats; attach a
  deterministic advice string per low axis.
- HAVE: PARTIAL primitives. RC has `_home_pick_tips` Good/Bad/Ugly
  one-liners (`builders_home.py:203`) and 14d CS/gold/KDA trends
  (`builders_home.py:295`) - the raw axes exist, but no radar and no
  population percentile.
- WHERE: new builder reading `match_history.db` + a radar SVG in home.
- EFFORT+RISK: L. Needs a percentile baseline (RC has no population corpus
  on home; `rewind_history.db` could seed a personal baseline but not a
  rank-cohort one). High build cost; the "advice" overlaps RC's existing
  coach output.
- LIFT: MED - conceptually the best fit for a coaching tool, but expensive
  and partly redundant with RC's deterministic tips + live coach. Defer
  behind P-A/P-B. The cheap slice (Good/Bad/Ugly already shipped) captures
  most of the value.

### P-E. Champion-pool table with per-champ trend (Overlay App F / Aggregator B)
- WHAT: your champ pool ranked, each with games / WR-or-grade / KDA / a
  hot-cold trend arrow and "best results" highlight.
- HAVE: MOSTLY YES. THIS WEEK panel is exactly this minus WR + percentile
  (`builders_home.py:143`-`174`, top-5 by games with KDA/CS/grade/modes);
  hot/cold champ list also exists (`main.js:1472`).
- WHERE: extend `this_week` rows (`builders_home.py:166`) with a per-champ
  trend arrow (recent vs baseline KDA, the logic already exists at
  `main.js:1540`).
- EFFORT+RISK: S. Pure additive aggregation on data already loaded.
- LIFT: MED - small polish on an existing panel; arrow + "best results"
  badge would close most of the Overlay App F gap cheaply.

### P-F. "What to play tonight" champ recommendation (Overlay App E pro / RC)
- WHAT: a single suggested champ for this session with a reason.
- HAVE: YES - Tonight's Pick is exactly this and is arguably AHEAD of
  Overlay App E's gated equivalent (`builders_home.py:231`, with Good/Bad/Ugly
  tips + click-to-History). RC computes it free, no Claude/Riot.
- LIFT: LOW (already shipped, competitive-leading) - do NOT re-pitch;
  potential micro-improvement is to weight by RC's DS build-confidence,
  separately scoped.

### P-G. Weekly summary digest (Overlay App E)
- WHAT: a periodic consolidated "this week you..." card with category
  trend lines + strongest/weakest callout.
- HAVE: PARTIAL. THIS WEEK panel + 14d sparklines cover the data; there is
  no narrative "weekly digest" card with an explicit best/worst callout.
- WHERE: a new home card synthesizing `this_week` + `trends` +
  `_home_pick_tips` logic (`builders_home.py:203`, `:295`).
- EFFORT+RISK: S-M. All inputs already in the payload; deterministic
  string assembly, no new data source. Aligns with the existing
  `/repo-insights`-style grounded-narrative pattern.
- LIFT: MED - good ROI, fully local, reinforces the coaching identity.

### P-H. MMR / tier-prediction (aggregator G AI-Score tier)
- WHAT: an estimated MMR/tier separate from displayed rank.
- HAVE: NO. RC has no MMR model and no population corpus.
- EFFORT+RISK: L. Needs an ML/statistical model + a rank-cohort dataset RC
  does not hold; event-mode focus makes solo MMR low-signal.
- LIFT: LOW - high cost, low fit for a solo event-mode player; out of scope
  (mirrors CLAUDE.md "ML win-predictors CLOSED").

---

## 4. NOISE (surveyed, deliberately NOT lifted for a solo tool)
- Riot-ID/tagline SEARCH BOX + multi-account scouting (single-account tool;
  onboarding is implicit).
- Friends / social feed / "spectate streamer" / Story page (aggregator G) -
  no social graph.
- Ads, premium upsell, Pro-gating (Overlay App E/Aggregator C) - irrelevant.
- Ladder leaderboards / regional cut-offs - not a ranked grind tool.
- Population percentile bars are USEFUL telemetry but require a cohort
  corpus RC lacks; a PERSONAL baseline (from `rewind_history.db`) is the
  legal cheap substitute and is the form RC should prefer if it ever adds
  percentile bars.

---

## 5. Sources
- Aggregator A: https://review-site-z11.invalid/blog/what-is-aggregator-a/ ;
  https://aggregator-a.invalid/help/articles/31088715328665-OP-Score-explained ;
  https://aggregator-a.invalid/
- Aggregator B / Aggregator A stats: https://review-site-z9.invalid/blog/summoner-lookup/understanding-summoner-profile-stats ;
  https://review-site-z9.invalid/blog/summoner-lookup/aggregator-a-vs-ugg-comparison
- Aggregator C: https://aggregator-c.invalid/blog/how-to-use-the-aggregator-c-summoner-profile-feature/ ;
  https://aggregator-c.invalid/aggregator-a-vs-aggregator-c/
- Overlay App E: https://overlay-app-e.invalid/lol ;
  https://review-site-z9.invalid/blog/game-analytics/overlay-app-e-gg-overlay-review
- AGGREGATOR G.GG: https://m.aggregator-g.invalid/
- Aggregator H: https://aggregator-h.invalid/ ;
  https://agatasmurf.com/league-of-graphs/
- Overlay App F: https://overlay-platform-m.invalid/app/overlay-app-f ;
  https://review-site-z12.invalid/blog/article/all-you-need-to-know-about-overlay-app-f-a-complete-guide
