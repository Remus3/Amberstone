# Competitor Lift - Live Companion Teardown - 2026-06-03

Deep-dive teardown of the leading League COMPANION / OVERLAY tools (Overlay App E, Aggregator C,
Overlay App F, aggregator A desktop, Aggregator B live companion, Aggregator G) for in-game + pre/post-game value
RC can re-implement. RC = LOCAL single-user live-coaching dashboard, Daemon Slayer (DS)
deterministic build/DPS engine, champ-select coaching, post-game review, ARAM/Arena/SR
coaches, Electron overlay (Phase 1).

This doc deliberately DOES NOT re-tread the two prior reports:
- `docs/COMPETITOR_LIFT_2026-05-28.md` (breadth, 18 sites) - theorycraft/calc cluster.
- `docs/COMPETITOR_LIFT_2026-05-30.md` (depth) - lolsolved knobs, calc.gg combo + stat-sweep,
  Aggregator C power-spike + cooldown-watch, relative-score bar. Those 5 lifts are SPEC'd there;
  read it before re-deriving them.

This report's angle is the LIVE OVERLAY + post-game-SCORE surfaces of the big companion apps
(not the calc sandboxes), which the prior two only skimmed. Every finding is grep-cited to
live RC source at patch 16.11.1.

---

## THE LOAD-BEARING CONSTRAINT (read first - it gates half the findings)

Three independent sources confirm the single most important fact for this teardown:

1. **The League Live Client API (`:2999`) does NOT emit ability-cast, summoner-spell-cast, or
   item-purchase events.** The only `eventdata` events are kills/objectives/structures
   (ChampionKill, DragonKill, BaronKill, TurretKilled, InhibKilled, Multikill, Ace, FirstBlood,
   GameStart, MinionsSpawning). Verified against the SkinSpotlights LiveEventsDocumentation
   (the authoritative community doc) AND RC's own `dashboard/_state_cooldowns.py:12-23` which
   already bakes this in: "The Live Client API does NOT emit SUMMONER_SPELL_USED or
   ULTIMATE_USED events ... We pass an empty event list ... every summoner + ult renders as
   READY."

2. **Overlay App E states it does NOT read game memory** - it "presents information that the game
   already does." The competitor enemy-ult-cooldown timers that start "when you see Zed cast
   Death Mark" are driven by Overlay Platform M's GEP (a manual/observational layer) or screen-reading,
   NOT the Live Client API.

3. **Riot has publicly stated that tracking enemy ult cooldowns "crosses the line in providing
   information that's not available in game."** So the enemy-cooldown-countdown feature is both
   un-replicable from RC's :2999-only data path AND on thin policy ice.

CONSEQUENCE: Any competitor feature framed as "live countdown of what the enemy just cast"
(enemy ult timer, enemy flash timer, "they used flash 4:40 ago") is a HARD NO for RC unless RC
adds a NEW data dependency (vision OCR of the scoreboard, or a manual operator click). RC's
honest analog is the EXISTING all-READY `summoner_cooldowns` ledger (who-has-what + haste-aware
effective CD) which is already on `/api/state`. This single constraint reframes the whole
"why doesn't RC have cooldown timers like Overlay App E" question: it is a deliberate, correct,
policy-clean limitation, not a missing feature.

---

## TARGET 1 - Overlay App E (in-game overlay + post-game grades)

### 1a. Live damage calculator on item-hover

1. **WHAT.** Hovering an item in the in-game SHOP shows how much your abilities will deal AFTER
   buying it, accounting for your current level, ability ranks, and the specific enemy you are
   laning against. It is the single most-cited "wow" feature of the Overlay App E overlay.
2. **HOW.** Overlay App E reads your live champion state (level, ability ranks, current items) from the
   client API, adds the hovered item's stats to a local stat block, runs its damage formula
   against the lane opponent's resists, and renders a delta. No memory read; it is a stat-block
   recompute on hover.
3. **HAVE - YES, the math; NO, the live-shop hover surface.** RC's DS engine IS this calculator
   and is strictly more rigorous: `agents/daemon_slayer/dps.py compute_dps()` +
   `ability_dps.py compute_ability_dps()` + `burst.py compute_burst_damage()` take
   `level`, item list, and `target_armor/target_mr/target_max_hp/target_bonus_hp` and return
   mitigated damage. `/api/ds-preview` already resolves live enemy resists from their actual
   items. The 2026-05-30 doc's Lift 1 (engine-knobs panel) and Lift 3 (stat-sweep) both cover
   the "what does this item do for me" presentation. What is genuinely absent is a per-item
   "buying THIS adds +X burst vs your lane opponent NOW" delta keyed to the operator's LIVE
   level/items mid-game (RC's surface is champ-select-centric).
4. **WHERE.** Engine: present (`compute_burst_damage` with live `liveclient` level/items + enemy
   resists). Route: a thin `/api/live-item-delta?item=<id>` that recomputes burst with vs
   without the candidate item, reading the operator's live state from `liveclient`. Panel:
   `web/js/panels/active_match.js` (already fed `ctx.liveclient` + `p.game_time` + owned items).
   This is the in-game twin of the prior doc's relative-score bar.
5. **EFFORT+RISK.** MED. The math + live enemy-resist resolution exist; the new work is a live
   in-game item-delta route + an active-match render, and the proof surface is in-game-only
   (live `liveclient` level/items). No new external dep, no Claude/Riot dep, no schema lift.
   Mock-testable for the delta math; live-only for the final visual. Overlaps heavily with the
   already-spec'd Lift 1/Lift 3 - this is their in-game (not champ-select) instantiation.
6. **LIFT. MED - needs new route + live-game-gated active-match render (defer to BACKLOG,
   fold into the Lift-1/Lift-3 DS-UI arc).** Not in-run (in-game proof only).

### 1b. Enemy + ally ultimate / summoner cooldown timers

1. **WHAT.** Enemy ult cooldowns shown on portraits; ally ult availability on portraits; timers
   start when the spell is observed cast.
2. **HOW.** Overlay Platform M GEP / observational layer (see THE LOAD-BEARING CONSTRAINT). NOT the Live
   Client API.
3. **HAVE - PARTIAL by deliberate design.** `core/summoner_cooldowns.py compute_cooldowns()` +
   `dashboard/_state_cooldowns.py compute_state_cooldowns()` already build a per-player
   summoner + ult ledger with full Ionian/Cosmic/Hextech-drake haste math
   (`eff_cd = base / (1 + haste/100)`) and ship it as `summoner_cooldowns` on `/api/state`
   (`_state_builder.py:285`). Because :2999 emits no cast events, every entry renders READY -
   so RC ALREADY shows "who has Flash vs Ignite, who has Cleanse vs Heal" and the haste-aware
   effective CD, just not a live countdown.
4. **WHERE.** The backend + `/api/state` key exist; what is missing is the PANEL JS (the module
   docstring literally says "The panel JS that consumes this is a separate follow-up").
5. **EFFORT+RISK.** LOW for the who-has-what panel (data already on `/api/state`); the live
   countdown is a HARD NO (no event source + Riot policy). The honest deliverable is a
   "summoner loadout + effective-CD" sidebar, NOT a countdown.
6. **LIFT. LOW (presentation over existing `/api/state` data) for the who-has-what +
   effective-CD ledger panel - in-run implementable. The live-countdown half is REJECTED
   (data + policy).** This is the cleanest pure-presentation win in the whole report: the
   payload is already shipping; only a panel renderer is missing.

### 1c. Post-game grades (CS / kill-participation / objective / death-quality vs rank cohort)

1. **WHAT.** Per-game letter grades across CS efficiency, kill participation, objective
   involvement, and "death quality," compared against a database of similar-rank games.
2. **HOW.** Pull post-game stats from Riot Match-V5, normalize each axis against the
   rank-cohort distribution, assign a grade.
3. **HAVE - YES, strongly.** RC has TWO substrates: `core/post_game_rubric.py` reproduces
   Riot's documented per-role S/A/B/C/D weight vectors (ADC 2.1 KDA + 0.50 obj + 0.85 CS/min,
   SUP 2.5 KDA + 1.5 vision + 0 CS/min, etc., tunable via
   `data/post_game_rubric_weights.json`), and `core/match_metrics.py` /
   `data/coach_reference/champion_benchmarks.json` carry per-champion benchmark distributions.
   RC's grading is per-role-weighted, which Overlay App E's flat axis grades are not.
4. **WHERE.** Present. The gap vs Overlay App E is the COHORT-RELATIVE normalization ("vs similar games
   at your rank") - RC grades against role baselines, not a live rank-percentile. RC's local
   `rewind_history.db` (~2900 matches) is the cohort substrate if the operator wants
   percentile framing (see the deferred ROADMAP-S3 0-100 score + lolstats Carry Score note in
   the 2026-05-28 doc).
5. **EFFORT+RISK.** LOW-MED to add a percentile/lobby-relative framing over the existing rubric;
   no new external dep (cohort = local match DB).
6. **LIFT. LOW-MED - mostly presentation over existing rubric + local match DB; the cohort
   normalization is the only new compute (feeds the already-planned ROADMAP-S3 score, defer
   there).** Not a net-new capability.

---

## TARGET 2 - Overlay App F (live lobby scouting - the distinctive surface)

Overlay App F's signature is NOT calc or builds (aggregator A/Aggregator B do those); it is LIVE LOBBY PLAYER
SCOUTING - turning each of the 10 players' match history into actionable tags before/during
the game. This is the most instructive Overlay App F mechanic and the one RC has the least of.

### 2a. Player Tags (per-player playstyle / threat labels)

1. **WHAT.** Each player in the lobby gets quick labels: "Aggressive laner", "Good vision",
   "Great with Brand", "On a win streak", "Roam heavy", "OTP / champion spam", plus rank, main
   role, and per-champion win rate / KDA / games-played. Used to adjust your plan ("ward
   earlier vs aggressive junglers", "respect strong laners").
2. **HOW.** Overlay App F pulls each player's recent ranked/normal 5v5 games from the last 30 days
   via Riot Match-V5, runs heuristics over the per-player stat distribution (early-game
   aggression proxy = early solo kills / early deaths; vision proxy = vision score percentile;
   champ-mastery = games + win rate on the current champ; streak = consecutive W/L in recent
   history; role = most-probable role from global champion-usage priors + the player's history).
   It is rule-based tagging over aggregated Match-V5 rows, not ML.
3. **HAVE - LARGELY NO (this is RC's biggest genuine gap).** RC scouts the OPERATOR deeply but
   barely scouts the OTHER 9 players. RC has the ingredients but not the per-lobby-player tag
   surface: `core/riot_api.py` + `core/riot_api_cache.py` can fetch any player's Match-V5;
   `core/draft_elo_db.py` + `dashboard/routes_team_context.py` + `routes_personal_vs.py` do
   SOME team-context enrichment; `coaches/adaptation_hint*.py` derive playstyle tags but FOR
   THE OPERATOR ONLY (from the operator's own history). There is no "tag each enemy/ally from
   their last 20 games" pipeline rendered in champ-select.
4. **WHERE.** Engine/data: extend `core/riot_api.py` to batch-fetch the 9 other players'
   recent Match-V5 (champ-select gives PUUIDs via LCU), reuse the `adaptation_hint` heuristics
   (which already compute aggression/vision/streak axes) applied to OTHER players' rows. Route:
   extend `dashboard/routes_team_context.py`. Panel: champ-select scouting card
   (`web/js/panels/champ_select.js`).
5. **EFFORT+RISK.** HIGH. This is a NEW data-fetch pipeline (9x Match-V5 fan-out per
   champ-select, rate-limit-bounded on the personal Riot key), a NEW per-player tag engine
   (though it reuses adaptation_hint axes), and a NEW card. It also re-opens a deliberate RC
   design boundary: RC has historically NOT scraped crowd/other-player stats. NB the Riot
   personal key + champ-select timing make a 9-player fan-out tight but feasible (cache per
   PUUID, fetch only on lock-in). Match-V5 403s on event modes (ARAM Mayhem/Arena) are EXPECTED
   per the settled list - this works on SR/draft only.
6. **LIFT. HIGH value, MED-HIGH effort, NEEDS NEW data-fetch pipeline + product call (defer to
   BACKLOG).** This is the clearest "thing the big tools do that RC does not." It is a genuine
   product-direction decision (does a single-player tool want lobby scouting?), so it warrants
   a framed scope question, not a blind build. Flagged as the top NEW-capability candidate.

### 2b. Live team gold-diff + @10/@20 stat deltas (CS/gold/wards)

1. **WHAT.** Real-time gold gap between teams; gold earned @10/@20, minions @10/@20, wards
   @10/@20 with trend graphs.
2. **HOW.** @N deltas are Match-V5 timeline frames post-game; the LIVE gold gap is summed from
   the live scoreboard / client API team totals.
3. **HAVE - PARTIAL.** RC's live macro signal is `core/lead_projection.py project_lead()`,
   which produces a deterministic ahead/even/behind + slight/clear/large verdict from
   per-minute benchmark deltas (CS/gold/level/KDA vs `_CS_PER_MIN_BENCHMARK` etc.) - a COARSE
   3-state verdict, not a continuous team gold-diff number. The @10/@20 deltas exist only
   POST-game in `core/match_metrics.py` (gd_at_15, csd_at_15, etc.) and feed the ADAPTATION
   stats view, which per ROADMAP item 281 has NO live producer (renders "-" in-game). The Live
   Client API gives the operator's own gold but NOT a clean enemy-team gold sum.
4. **WHERE.** `lead_projection` already on `/api/state` as `lead_projection`. A live team
   gold-diff would need summing per-player current gold (Live Client `allPlayers` does NOT
   expose other players' gold - only the active player's), so a true gold-gap is BLOCKED on the
   same data gap as cooldown timers.
5. **EFFORT+RISK.** The lead_projection verdict is DONE; a precise live gold number is BLOCKED
   (Live Client does not expose enemy gold). Vision OCR of the scoreboard would be a new dep.
6. **LIFT. LOW (verdict already shipped); a precise live gold-diff number is REJECTED (no data
   path without OCR).** RC's benchmark-delta verdict is the honest single-player version.

### 2c. Role inference from champion-usage priors

1. **WHAT.** Assign each player to a lane/role pre-game when the client does not declare it
   (auto-fill, ARAM, blind).
2. **HOW.** Bayesian-ish: combine global champion->role usage priors with the player's own
   role history; pick the most-probable role assignment across the 5 players.
3. **HAVE - PARTIAL.** RC resolves the OPERATOR's role/archetype
   (`dashboard/routes_archetype.py`, the item-244 F1 champ-select archetype resolver) but does
   not run a 5-player role-assignment solver. This is a sub-component of 2a (Player Tags need
   role) and not independently worth much.
6. **LIFT. LOW standalone (folds into 2a if that ships).**

---

## TARGET 3 - aggregator A desktop overlay (the in-game timer / tracker cluster)

aggregator A's overlay is the richest pure-overlay timer/tracker set. Several map directly onto RC
gaps. Feature list confirmed from the live aggregator A overlays page.

### 3a. Healing-item / grievous-wounds tracker

1. **WHAT.** "Healing Item Tracker - identifies enemy team healing items AND allied
   healing-reduction items." Tells you, live, that the enemy is stacking sustain and your team
   lacks anti-heal.
2. **HOW.** Scan both teams' live items (client API item lists) against a known set of
   healing-source items and a known set of grievous-wounds items; surface a "enemy heals,
   you have no anti-heal" flag.
3. **HAVE - NO as a live tracker; YES as build data.** RC's DS layer knows which items are
   anti-heal (build scorers reason about it) and `core/damage_mix.py` reasons about damage
   profiles, but there is no LIVE panel that scans the enemy's actual items for sustain and
   warns "buy Oblivion Orb." RC's enemy item resolution already exists (`/api/ds-preview`
   reads live enemy items for resist curves), so the item-scan substrate is present.
4. **WHERE.** Engine: a small static set {healing-source item ids} + {grievous item ids}
   (derivable from `data/daemon_slayer/16.11.1/items.json`). Route: extend the existing live
   enemy-item resolution in `dashboard/routes_state.py` / `_state_builder.py` to emit a
   `heal_threat` flag. Panel: a one-line "RIGHT NOW" chip (`web/js/panels/right_now.js`) or an
   active-match badge.
5. **EFFORT+RISK.** LOW-MED. Data is local (items.json item tags), the live enemy-item read
   already exists, and the output is a single boolean+item-suggestion. No new external dep, no
   Claude/Riot dep. Live enemy items DO arrive via the relay/`liveclient` (RC already uses them
   for resist curves), so this is implementable and live-testable. Mock-testable for the
   item-set logic.
6. **LIFT. LOW-MED - presentation + a static item-set over already-resolved live enemy items
   (in-run implementable for the logic; live-game-gated for final visual).** Strong
   value-per-effort; a concrete single-player coaching nudge RC currently lacks.

### 3b. Jungle / Scuttle / inhibitor / ARAM-relic respawn timers

1. **WHAT.** Minimap respawn timers for jungle camps, Scuttle, inhibitors (ally + enemy), ARAM
   health relics; jungle-path overlay.
2. **HOW.** aggregator A's camp timers are event/observation-driven (camp cleared -> start timer);
   inhibitor timers key off the InhibKilled event; ARAM relic timers off a fixed cadence.
3. **HAVE - PARTIAL.** RC's `core/event_callouts.py _objective_callouts()` models dragon/
   herald/baron/elder via a FIXED-CADENCE schedule (spawn_s + cadence from `game_time_s`), and
   ships them as `callouts` on `/api/state`. Inhibitor respawn IS event-derivable (InhibKilled
   is one of the few real Live Client events). Per-CAMP jungle timers are NOT (no camp-clear
   event) - they would need vision/observation. ARAM relics are a fixed cadence (easy).
4. **WHERE.** `core/event_callouts.py` (already the callout home) + the `callouts` key. Add
   InhibKilled-driven inhibitor timers (real event) + ARAM relic cadence; jungle-camp timers
   stay BLOCKED (no event).
5. **EFFORT+RISK.** LOW for inhibitor (real event) + ARAM relic (cadence); jungle-camp timers
   REJECTED (no data). The dragon/baron cadence callouts already exist.
6. **LIFT. LOW for inhibitor + ARAM-relic timers (extends the existing callouts engine,
   in-run implementable); jungle-camp timers REJECTED (no event source).** Incremental.

### 3c. Live "real-time stats" skill-comparison + team item/gold standing

1. **WHAT.** "Real-time Stats - compares player skill using key metrics by lane + average
   tier"; "Gold & Item Comparison - total items + gold diff between teams."
2. **HOW.** Pre-game pull of both teams' rank/recent-form, plus live team item-count + gold
   sums.
3. **HAVE - PARTIAL / BLOCKED.** The skill-comparison overlaps Overlay App F 2a (needs the
   9-player fetch). The team gold/item standing is BLOCKED on the same Live-Client-no-enemy-gold
   gap as 2b.
6. **LIFT. Folds into 2a (player scouting) and inherits 2b's data block.** No independent lift.

---

## TARGET 4 - Aggregator B live companion (dynamic skill order)

Aggregator B's overlay is build/rune/skill focused (aggregator-A-class). The one mechanic worth isolating:

### 4a. Dynamic / situational skill-leveling order

1. **WHAT.** "In-game dynamic skill order recommendations for all situations" - the skill-up
   order ADAPTS to the matchup, not a single static R>Q>W>E string.
2. **HOW.** Aggregator B mines the most-successful skill-order SEQUENCES from high-elo games for the
   champ (and sometimes matchup), and surfaces the next skill to level based on the current
   level. Crowd-sourced sequences.
3. **HAVE - PARTIAL.** RC's `core/build_order.py plan_build_order()` orders ITEMS by DS scorer
   delta; the curated `coaches/loadout_resolver.py` variants carry summoners/runes/items but
   skill order is NOT a first-class DS output (DS reasons about ability damage per rank but
   does not emit a recommended max order). RC could DERIVE a skill-max order from its own
   ability-DPS-per-rank math (max the highest-DPS-per-rank ability first) - a deterministic,
   crowd-free version that fits RC's no-scrape stance.
4. **WHERE.** Engine: a new `compute_skill_order(champion, matchup?)` over
   `agents/daemon_slayer/ability_dps.py` per-rank deltas (which ability gains the most per
   point). Route/panel: champ-select build chooser.
5. **EFFORT+RISK.** MED. It is net-new engine logic (rank-delta argmax across Q/W/E), though it
   reuses the existing per-rank ability data. No external dep (RC derives it, not scrapes it).
   The fidelity question (DPS-max order vs real situational order, e.g. max W for safety) is the
   risk - a pure-DPS argmax can disagree with meta skill orders for utility reasons.
6. **LIFT. MED - net-new engine derivation over existing ability data; no new dep but a
   modeling call (DPS-max vs situational). Defer to BACKLOG.** Lower priority than the scouting
   + heal-tracker lifts.

---

## TARGET 5 - Aggregator G + Aggregator C (AI / GPI per-game scoring)

Aggregator G ("AI Score" + "Tier Prediction") and Aggregator C ("GPI", 8 axes 0-100) are the
post-game-SCORE leaders. Their public methodology + a Aggregator C/Aggregator G-class patent
(US11478716 "deep-learning skill estimation") reveal the shared algorithm.

### 5a. The per-game AI / skill score (sequence-model "deviation from rank baseline")

1. **WHAT.** A single per-game (and aggregate) score rating how well you played, decomposed
   into axes - Aggregator C GPI: Fighting, Farming, Vision, Objectives, Aggression, Survivability,
   Versatility, Teamplay (0-100 each, role-weighted into an overall). Aggregator G: an "AI Score"
   + a predicted tier. Both claim to be opponent/context-relative, not flat thresholds.
2. **HOW (from the patent + public docs).** Extract a TEMPORAL SEQUENCE of per-minute features
   (gold, XP, CS, K/D/A, objective control, vision, position) per player, feed it to a deep
   sequence model (LSTM-class) trained to predict match outcome / rank, and read out (a) a
   continuous skill estimate and (b) per-axis sub-scores = how far the player DEVIATES from the
   learned "what good play looks like at this rank" baseline. The key idea: the score is a
   learned deviation-from-cohort-baseline, computed per-timestep then aggregated, NOT a static
   weighted sum.
3. **HAVE - YES the substrate, NO the ML model (and RC explicitly does not want it).** RC has
   TWO relevant pieces: `core/post_game_score.py` is a logistic-regression WPA (win
   probability added) model with per-event state updates - a real per-timestep contribution
   model (`compute_match_wpa`, `WpaModel`, `data/post_game_wpa_model.json`), and
   `core/post_game_rubric.py` is the role-weighted S/A/B grade. So RC already computes BOTH a
   per-event win-prob delta AND a role-weighted grade - it is closer to the GPI/AI-Score idea
   than any other tool in these reports. The settled list confirms an ML win-predictor is a
   CLOSED negative for RC and the ROADMAP-S3 0-100 score is deliberately a heuristic over
   enriched stats with NO ML dependency.
4. **WHERE.** Both modules exist. The lift is PRESENTATION: decompose the existing rubric +
   WPA into a GPI-style multi-axis 0-100 card (Fighting from KDA+damage, Farming from CS/min vs
   benchmark, Vision from vision score, Objectives from `core/obj_participation.py`, etc. - all
   axes RC already computes) and frame it lobby-relative using the local `rewind_history.db`
   cohort. This IS the deferred ROADMAP-S3 aggregator-G-style Post Game Review reframe.
5. **EFFORT+RISK.** MED, but it is ALREADY the planned ROADMAP-S3 work (operator-gated, needs a
   live standard-queue game + the per-page UI-audit ritual). The axes all map to existing RC
   computations; the cohort-relative normalization uses the local match DB (no external dep, no
   ML). The risk is purely product scope (how many axes, how to normalize) - explicitly NOT an
   ML build (that is a settled CLOSED negative).
6. **LIFT. MED - presentation over existing rubric + WPA + obj-participation, cohort-normalized
   on the local match DB; this is the already-planned ROADMAP-S3 PGR reframe (operator-gated,
   live-game-gated). NOT a new ML dependency (CLOSED).** RC should explicitly reframe S3 as
   "the GPI/AI-Score axis card, built from RC's own deterministic axes + local cohort," which
   is a defensible no-scrape, no-ML version of the leaders' headline feature.

### 5b. Aggregator C "ability cooldowns and details" + per-role power spikes in the overlay

1. **WHAT.** The Aggregator C overlay surfaces enemy ability cooldowns + per-role early/mid/late
   power spikes as matchup context.
2. **HOW + HAVE + LIFT.** This is the SAME pair already spec'd in the 2026-05-30 doc as Lift 4
   (live power-spike markers, MED, live-gated) and Lift 5 (matchup cooldown-watch card on the
   CC card, LOW-MED, the cleanest join). RC already SHIPPED the cooldown-watch route
   (`dashboard/routes_cooldown_watch.py`, `/api/cooldown-watch`, base-CD-by-rank Q/W/E layer)
   per item-context. NOT re-derived here - see the prior doc.

---

## PRIORITY TABLE

Ranked by (single-player live-tool value) / (effort + risk). "Risk class" per the task spec:
PRES = low-risk presentation over existing DS/RC math (in-run implementable);
DEP = needs new dependency / schema lift / product call (defer to BACKLOG).

| # | Target | Mechanic | RC integration point | Effort | Lift | Risk class |
|---|--------|----------|----------------------|--------|------|------------|
| 1 | Overlay App E 1b | Who-has-what + effective-CD summoner/ult ledger PANEL (NOT countdown) | Panel JS over EXISTING `summoner_cooldowns` on `/api/state`; data already shipping (`_state_cooldowns.py`) | LOW | LOW | **PRES (in-run)** |
| 2 | aggregator A 3a | Healing-item / grievous-wounds live threat chip | static item-set over already-resolved live enemy items; `_state_builder.py` -> `right_now.js` chip | LOW-MED | LOW-MED | **PRES (logic in-run; visual live-gated)** |
| 3 | Aggregator G/Aggregator C 5a | GPI/AI-Score multi-axis 0-100 post-game card, cohort-normalized | decompose EXISTING `post_game_rubric.py` + `post_game_score.py` WPA + `obj_participation.py`; cohort = local `rewind_history.db` | MED | MED | **PRES over existing math = ROADMAP-S3 (operator+live-gated)** |
| 4 | Overlay App F 2a | Per-lobby-player Player Tags (aggression/vision/streak/mastery) | NEW 9x Match-V5 fan-out (`core/riot_api.py`) + reuse `adaptation_hint` axes on OTHER players; `routes_team_context.py` -> champ-select card | MED-HIGH | HIGH (value) | **DEP (new fetch pipeline + product call -> BACKLOG)** |
| 5 | Overlay App E 1a | Live in-game item-delta ("+X burst vs lane NOW") on item-hover | `compute_burst_damage` with live `liveclient` level/items + enemy resists; `/api/live-item-delta` -> `active_match.js` | MED | MED | **DEP (new route + live-gated; folds into Lift-1/3 arc) -> BACKLOG** |
| 6 | Aggregator B 4a | Deterministic DPS-max skill-leveling order | NEW `compute_skill_order` over `ability_dps.py` per-rank deltas; champ-select build chooser | MED | MED | **DEP (net-new engine derivation + modeling call) -> BACKLOG** |
| 7 | aggregator A 3b | InhibKilled-driven inhibitor + ARAM-relic respawn timers | extend `core/event_callouts.py` (real InhibKilled event + relic cadence); `callouts` key | LOW | LOW | **PRES (extends callouts engine, in-run)** |
| 8 | Overlay App E 1c | Cohort-relative post-game letter grade framing | percentile over EXISTING `post_game_rubric.py` using local match DB | LOW-MED | LOW-MED | **PRES (feeds #3 / ROADMAP-S3)** |
| - | Overlay App E 1b / Overlay App F 2b / aggregator A 3c | Enemy ult/flash live COUNTDOWN; precise live enemy team gold-diff | n/a | - | **REJECTED** | no Live Client event/enemy-gold data path + Riot policy (enemy-CD); needs vision OCR new dep |

### Top in-run (PRES) wins, build-next order
1. **#1 summoner/ult ledger panel** - payload already on `/api/state`; only a renderer is
   missing. Single safest win in the report.
2. **#7 inhibitor + ARAM-relic timers** - extends the existing `callouts` engine with the one
   real respawn event (InhibKilled) + a cadence; no new data.
3. **#2 heal-threat chip** - static item-set over the live enemy items RC already reads for
   resist curves; one concrete coaching nudge RC currently lacks.

### Top NEW-capability (DEP) candidate
**#4 Overlay App F-style per-lobby Player Tags** is the single biggest "thing the leaders do that
RC does not." It is a genuine product-direction call (does a single-player tool want to scout
the other 9 players?) + a new 9x Match-V5 fan-out pipeline, so it warrants a framed scope
question, not a blind build. Everything else is presentation over math/data RC already owns or
a CLOSED/blocked negative.

### The one-line strategic read
RC already owns the HARD parts the leaders charge for (a rigorous mitigated-damage engine, a
per-event WPA model, a role-weighted Riot-rubric grader, a haste-aware cooldown ledger, an
objective-cadence callout engine). The gaps are almost entirely PRESENTATION (panels that
consume payloads already on `/api/state`) plus exactly ONE missing capability of substance -
live lobby player-scouting (Overlay App F) - which is gated on a new Match-V5 fan-out and a
product decision, not on any engine work.

---

## ORCHESTRATOR VERIFICATION (2026-06-03 headless, post-report)

Verified the report's in-run picks against live source before acting (the premise-check
discipline). Corrections:

- **#1 summoner/ult ledger panel = ALREADY BUILT, not "renderer missing".** `web/js/panels/
  cd_ledger.js` (dated 2026-05-20) already renders the per-player summoner + ult ledger from
  `/api/state.summoner_cooldowns`, mounted at `#cd-ledger-body` in the active_match view, fed by
  `core/summoner_cooldowns.py` + `dashboard/_state_cooldowns.py`. HAVE. No build needed; the
  report's "single safest win" was stale. (A duplicate panel was NOT created.)
- **#7 inhibitor + ARAM-relic respawn callouts = genuine gap, scoped.** `core/event_callouts.py`
  has the SR objective schedule + level/item spikes + recall affordability but NO inhibitor
  respawn (the rock-solid 300s constant) and no ARAM relic cadence. It IS correct-by-construction
  and Haiku-elim-aligned. Wiring cost: the InhibKilled events must be surfaced through
  `liveclient_summary` -> `_deterministic_coaching._build_game_state` -> `next_callouts` (the lc
  summary does not currently carry raw events). Medium integration surface; logged for a focused
  slice. The ARAM relic cadence constant needs canonical-source verification before seeding
  (do not hardcode a guessed cadence).
- **#2 heal-threat / grievous chip, #5/#4 player-tags, #6 PGR/AI-score** stand as written
  (#4 player-tags BACKLOG + product call; #6 = the planned ROADMAP-S3 PGR reframe).

Net: the report's headline in-run win was already shipped; the real remaining engine-adjacent
work matches the standing ROADMAP (callouts extension + the operator-gated PGR reframe).
