# Competitor Lift - DEPTH Teardown - 2026-05-30

Depth follow-up to `docs/COMPETITOR_LIFT_2026-05-28.md` (breadth scan of 18 sites - read
that first; this doc does NOT re-tread it). Scope: turn the 5 HIGH-ranked lifts into
ready-to-gate RC integration SPECs the operator can pick from on wakeup. Each lift answers
all six depth-checklist points (WHAT / HOW / HAVE / WHERE / EFFORT+RISK / LIFT verdict) and
is classified IN-RUN (presentation-over-existing-DS-math, no new dep, no schema lift,
mock-verifiable) vs OPERATOR-GATE (new compute / new page / live-game-only / direction call).

Live teardown method: WebFetch + WebSearch against the public sites (lolsolved.gg /
calc.gg / aggregator C). calc.gg + aggregator C blog deep pages are SPA/403 to a markdown
fetch; their interaction specifics are corroborated from the 2026-05-28 doc (prior agent
captured them) + the homepage/search text quoted inline below.

RC grounding is grep-cited to live source at the time of writing (DS data patch 16.11.1,
engine surfaces on `:8888` dashboard + `:8893` DS engine).

---

## Lift 1 - lolsolved.gg engine-knobs UX (tunable combat-window / gold-cap / boot-timing)

**WHAT.** lolsolved exposes the optimizer's internal assumptions as user-adjustable controls,
so the operator can re-rank builds for a fight model instead of accepting one fixed ranking.
Confirmed control set + ranges (live homepage fetch):
- Combat-length overrides, THREE phase-split knobs: "Early Combat Length Override" (default
  0.5, poke), "Mid Game Combat Length Override" (default 1.5, burst), "Late Game Combat
  Length Override" (default 4.0, sustain), plus a global "Combat Length Override".
- Boot timing: "Tier 1 Boots" (max gold before boots), "Tier 2 Boots" (upgrade timing).
- Enemy defensive stat curves: "Enemy HP / Enemy Armor / Enemy Magic Resist" adjustable from
  minute 0 through minute 45.
- Gold: "Limit Gold" (build-cost cap), "Ultimate Build" (4x post-20 income + extra slots).
- Damage-profile knob: per-stat intensity selectors (e.g. "Ability Haste" = "Very High");
  "Extended Combat Value" 0.0-1.5 (DoT effectiveness); "Override Stat Ratios" (raw JSON).

**HOW.** Genetic-algorithm theorycrafter (~400k plans/champ) re-runs in-browser (0-60s, red->
yellow progress bar) and emits a recommended item-order list. The knobs are inputs to the
fitness function: combat length decides whether burst items or sustained-DPS items win; the
enemy resist curve decides armor-pen vs raw-AD weighting; gold cap bounds the search.

**HAVE.** RC owns every one of these inputs as PARAMETERS already, just not as UI controls:
- Combat-window / fight model: `agents/daemon_slayer/dps.py` `compute_dps()` already does a
  phase-weighted rotation (`phase` arg, auto-selected per level); the level-DPS curve sampler
  `compute_dps_curve()` (`dps.py:924`) exists. There is no operator-facing "fight length"
  slider that re-weights the ranking, though.
- Enemy target resists: `target_armor / target_mr / target_max_hp / target_bonus_hp` are
  first-class args on `compute_dps`, `rank_items` (`rank.py:346`), `plan_build_order`
  (`core/build_order.py:279`). `/api/ds-preview` (`dashboard/routes_state.py:408`) already
  resolves these from LIVE enemy items or a mode/level curve and threads them in.
- Gold cap: `rank_items(budget=...)` + `_filter_candidates` budget filter (`rank.py:339`)
  already exist. Boots: `plan_build_order(inject_boots=...)` + `_DEFAULT_BOOTS_BY_ARCHETYPE`
  (`core/build_order.py:111`) handle boot insertion.
- So RC has the math and the knobs as code args; what is missing is the CONTROL PANEL that
  exposes a fight-length / gold-cap / target-resist slider set bound to a re-fetch of
  `/api/ds-preview` + `/api/build-order`.

**WHERE.** Panel JS: `web/js/panels/champ_select.js` (build chooser + DS archetype preview
already call `/api/ds-preview` and `/api/build-order`). A control strip above the build
chooser sets `{combat_phase_weight | budget | target_armor | target_mr | target_max_hp}` and
re-POSTs those routes. Backend: the routes already accept `target_*` (and budget for the
ranker); only `combat_phase_weight` (a re-weight of the existing phase rotation in
`compute_dps`) would be a NEW engine arg - everything else is plumbing existing args to the UI.

**EFFORT + RISK.** MED. target-resist / gold-cap / boot-timing controls are pure plumbing
(args already exist) and are FULLY MOCK-TESTABLE (POST canned payloads, assert ranking
shifts). The fight-length-reweight knob is the only one that needs a small engine change
(a weight multiplier over the existing phase rotation) - still no new data, no Claude/Riot
dep, no schema lift. No live game required for visual proof (champ-select + mock fixtures
cover it). Risk: scope creep - lolsolved exposes ~12 knobs; RC should ship 3-4 (fight model,
target resists, gold cap) and resist the JSON-ratio-override surface.

**LIFT verdict. MED - OPERATOR-GATE.** New control panel + a re-fetch wiring arc + one engine
re-weight arg. It is product-direction (how many knobs, default fight model) and warrants a
framed scope question. Not a one-commit in-run change. Strongest of the "controls" cluster.

---

## Lift 2 - calc.gg action-queue combo builder (ordered cast sequence, per-hit mitigated)

**WHAT.** An "Action Queue" where the user types an ordered, SEQUENTIAL cast/attack list
(Q, AA, W, R, ...) and each action is evaluated in time order. Live homepage text:
`"Action Queue (Actions are all sequential, not simultaneous, max 60 actions, max 60
seconds)"`. calc.gg time-steps the sequence so health/mana regen, cooldowns, and time-based
passives resolve between actions; each hit is mitigated by the target's resists. Output is a
per-hit damage breakdown / running total over the sequence (vs RC's single aggregate DPS).

**HOW.** A duel-sim loop: maintain a clock, pop the next action, apply ability/AA damage
through the armor/MR/pen pipeline, advance the clock by the action's cast time / windup,
re-resolve cooldowns + regen, accumulate. The Meraki source data calc.gg uses is the SAME
bulk source RC's DS engine consumes (`cdn.merakianalytics.com/.../champions.json`).

**HAVE.** PARTIAL. RC computes the per-hit ingredients but has no ordered-sequence simulator:
- Ability damage per cast: `agents/daemon_slayer/ability_dps.py` (`compute_ability_dps`).
  Burst: `agents/daemon_slayer/burst.py` (`compute_burst_damage`). AA DPS + mitigation
  pipeline: `dps.py` `compute_dps`. Per-spell cast/cooldown data: `champion_abilities.json`
  carries per-rank `cooldown` lists (1270 cooldown entries in patch 16.11.1).
- What is MISSING: a function that takes an ORDERED `[Q, AA, W, R]` list and walks a clock
  applying each hit with between-action regen/cd resolution. RC's outputs are aggregate
  (weighted DPS, total burst) - no timeline, no per-hit row, no user-authored sequence.

**WHERE.** NEW engine module `agents/daemon_slayer/combo.py` (`compute_combo(champion, level,
items, sequence, target_*)` -> list of per-hit `{action, t, raw, mitigated, cumulative}`),
composing the existing `compute_ability_dps` + AA pipeline + the `cooldown` data. NEW route
`/api/ds-combo` (sibling of `/api/build-order` in `dashboard/routes_state.py`). NEW panel
(sequence input + per-hit timeline table) - a Champ Select or sandbox surface.

**EFFORT + RISK.** HIGH. This is a new simulator (clock + action loop), a new route, and a
new panel - the largest of the five. It is fully MOCK-TESTABLE (deterministic per-hit output
for a fixed sequence) and needs NO new external dependency and NO schema lift (cast/cooldown
data already in `champion_abilities.json`). Risk: the time-step fidelity (cast times, windup,
animation cancels) is the hard part - calc.gg itself flags "not all features implemented".
RC should scope a v1 = no animation-cancel modeling, fixed cast times.

**LIFT verdict. HIGH value, OPERATOR-GATE.** Net-new compute + page; single-player burst-trade
value is high but it is a multi-session arc, not in-run. File as its own issue.

---

## Lift 3 - calc.gg stat-sweep graphs (damage/EHP across a swept variable)

**WHAT.** Plot a DS output (damage / DPS / EHP) on Y against a SWEPT variable on X (target
armor, target MR, target level, item count). 2-variable mode = a heatmap / 3D surface. Turns
RC's single-number outputs into a "how does this scale" curve - e.g. "my DPS vs enemy armor
0->300" shows the armor breakpoint where LDR/anti-armor overtakes raw damage.

**HOW.** A loop over the swept variable: for each X value, call the scorer with that one input
varied and everything else fixed, collect (X, Y), render a line. 2-var = nested loop ->
matrix -> heatmap. Pure presentation over repeated scorer calls.

**HAVE.** STRONGEST overlap of the five - the sweep primitive already exists in one axis:
- `compute_dps_curve()` (`dps.py:924`) ALREADY sweeps LEVEL (default 1/6/11/16/18) and returns
  `DpsCurvePoint[]` (`level, weighted_dps, phase, stats`). That is exactly a level-swept DPS
  graph, unconsumed by any UI.
- `dashboard/routes_spike_curve.py` already does a per-minute sweep (level + item-count proxy)
  and renders it via `web/js/panels/spike_curve.js` - a working sparkline panel. So RC has a
  live sweep-loop-to-chart pipeline today, just not over the OTHER axes (target armor/MR).
- Sweeping target armor/MR/item-count is a trivial loop over `compute_dps`/`compute_ehp` with
  `target_armor`/`target_mr` varied - all first-class args already.

**WHERE.** Smallest of the graph lifts. Option A (in-run-able): a new "scaling" tab on the
existing DS preview that calls a NEW thin route `/api/ds-sweep?champion&axis=armor&...`
(loops `compute_dps` over the axis) and renders with the EXISTING `spike_curve.js` chart
component (or a sibling). Engine math: 100% present. Route: ~40 lines. Panel: reuse the
sparkline renderer.

**EFFORT + RISK.** LOW-MED. 1-variable sweep is a presentation layer over existing scorers
(`compute_dps_curve` is literally a level sweep already). NO new data, NO Claude/Riot dep, NO
schema lift, FULLY mock-testable (assert the curve is monotonic-decreasing in target armor),
NO live game needed. The 2-variable heatmap is a bigger render job (defer). Risk: minimal -
the loop is cheap and cached patterns exist in `routes_spike_curve.py`.

**LIFT verdict. MED - borderline IN-RUN for the 1-variable case.** A single-axis sweep
(target-armor-swept DPS) is genuinely low risk and mostly presentation. It edges to GATE only
because it needs a NEW route + a NEW chart-tab wiring (more than a pure-presentation tweak),
and the operator should pick which axis ships first. The 2-var heatmap is firmly GATE.

---

## Lift 4 - Aggregator C power-spike timeline (live "now you can fight" markers)

**WHAT.** Aggregator C surfaces champion power spikes as discrete markers: level spikes
(6 = ultimate, plus 9/11/13/16/18) and item spikes (BF Sword, mythic completion, Sheen, etc),
bucketed into early/mid/late phases with green/yellow/red strength badges. It is a STATIC
pre-game champion profile (editorial phase coloring + a spike list), NOT a live game-clock
overlay. Search-confirmed taxonomy: "level 6 power spike ... spikes at 9, 11, 13, 16 and 18"
+ "item spikes ... BF Sword ... +40 attack damage".

**HOW.** Aggregator C derives phase strength from crowd/meta data + curated spike lists per
champion. The RC-relevant LIFT is NOT the meta coloring (RC deliberately does not scrape
crowd stats) - it is rendering "when does THIS build come online" markers from RC's OWN DS
curves against the live game clock, which is a stronger single-player signal than a static
profile.

**HAVE.** RC is closer here than the doc implied - the spike PANEL already exists:
- `dashboard/routes_spike_curve.py` computes per-minute team-vs-team power curves (0-40) with
  `_peak_minute()` = first minute crossing 70% of max (the "come online" semantic), already
  rendered by `web/js/panels/spike_curve.js`.
- `web/js/panels/active_match.js` ALREADY mounts that panel (`am-spike-curve`, `active_match.js:31`)
  and is fed `ctx.liveclient` with `p.game_time` (`active_match.js:191`). The per-champ
  level/item curves come from `compute_dps_curve` / the archetype scorers.
- GAP: the existing panel is a CS-side team-vs-team sparkline keyed on a synthetic
  minute->level->item schedule. It is NOT keyed on the LIVE game clock, and it has no discrete
  "you hit your level-6 / 2-item spike NOW" markers tied to the operator's actual level + item
  count from `liveclient`.

**WHERE.** `web/js/panels/active_match.js` (panel already mounted + already has `game_time` +
`liveclient`). Backend: reuse `compute_dps_curve` / the archetype scorers; optionally a thin
`/api/spike-markers` that takes the operator's live level + owned items and returns the next
spike threshold. The marker overlay draws a "now" line at `game_time` and dots at the level/
item thresholds the operator has crossed or is about to cross.

**EFFORT + RISK.** MED. The curve math + panel both exist; the work is (a) a live-clock cursor
on the existing curve and (b) discrete spike-threshold markers (level 6/11/16, item 1/2/3
completion). Mostly presentation over existing DS curves, but it needs a LIVE game for true
visual proof (the live-clock cursor only renders mid-match), and `active_match.js` is the
operator's in-game surface. Mock-testable for the marker math; live-only for the final visual.

**LIFT verdict. MED - OPERATOR-GATE (live-game-gated).** Real value but the proof surface is
in-game-only and it touches the active-match panel. Not in-run. The team-power-curve half is
already shipped; this issue is specifically the live-clock cursor + spike markers.

---

## Lift 5 - Aggregator C matchup cooldown-watch cards (highest-threat enemy ability cooldowns)

**WHAT.** "Watch their hook - 16s" framing: surface the highest-threat enemy ability's
cooldown so the operator knows the window after the enemy whiffs a key spell. Aggregator C frames
this as matchup tips; the RC-relevant version is data-driven from the enemy roster's actual
ability cooldowns + CC threat.

**HOW.** Pick the enemy's highest-impact ability (longest hard CC / biggest burst), show its
base cooldown by rank, optionally net of the enemy's ability haste. It is a static per-ability
fact (cooldown) framed as actionable ("after they hook, you have ~16s").

**HAVE.** PARTIAL - the two halves exist but are not joined:
- CC THREAT (which ability is dangerous): `agents/daemon_slayer/cc_conditional.py` +
  `_PER_SPELL_CC_DURATIONS` already rank per-spell hard-CC durations. Two live dashboard
  consumers already exist: `/api/cc-conditional-pressure`
  (`dashboard/routes_cc_conditional_pressure.py`) and `/api/cc-blended-ehp-threat`
  (`dashboard/routes_cc_blended_ehp_threat.py`), surfaced as champ-select threat chips
  (`champ_select.js:1021` + `cc_conditional_pressure.js`).
- ABILITY COOLDOWNS (the "16s" number): `champion_abilities.json` carries per-rank `cooldown`
  lists for every Q/W/E/R (1270 entries, patch 16.11.1). This is the exact data the
  cooldown-watch card needs - already in RC's DS data dump, NO new fetch.
- IMPORTANT distinction: `dashboard/_state_cooldowns.py` + `core.summoner_cooldowns` already
  track SUMMONER + ULT cooldowns from Live Client and ship them as `summoner_cooldowns` on
  `/api/state` - but that is summoner spells + ult, NOT the per-ability (Q/W/E) base cooldowns
  from the abilities JSON. The matchup cooldown-watch card is the Q/W/E layer, which is
  currently unconsumed.

**WHERE.** Extend the EXISTING CC-threat card. Backend: the CC-threat routes already resolve
the enemy roster + rank per-spell CC; join each flagged spell to its `cooldown` from
`champion_abilities.json` (a dict lookup - no new compute). Panel: `web/js/panels/champ_select.js`
CC card render (and optionally the active-match threat surface). This is the lift the
2026-05-28 doc flagged as "directly relevant to the CC-card rewrite".

**EFFORT + RISK.** LOW-MED. The CC-threat plumbing (route + chip) exists; the only addition is
joining the already-loaded `cooldown` data to the already-ranked CC spell and rendering the
number. NO new data (cooldowns in the DS dump), NO Claude/Riot dep, NO schema lift, FULLY
mock-testable (fixed roster -> fixed "Blitz hook 16s"). No live game needed for the champ-
select card. Risk: low - cosmetic framing decision (base cd vs haste-adjusted; RC has no live
enemy haste, so base-cd-by-rank is the honest v1).

**LIFT verdict. LOW-MED - borderline IN-RUN.** The cleanest "join existing data to existing
card" lift. It edges to GATE only because it touches a card mid-rewrite and is a framing
decision (which spell counts as "the threat", base vs adjusted cd). If the operator's current
CC-card work is open, fold it in there.

---

## (a) Operator pick-list - ranked build-next order

Ranked by (value to a single-player live tool) / (effort + risk), IN-RUN first:

1. **Lift 5 - matchup cooldown-watch on the CC card** (LOW-MED, borderline IN-RUN). Both data
   halves already live in RC (CC ranking + ability `cooldown` dump); it is a join + render.
   Highest value-per-effort; folds into the CC-card work already in flight.
2. **Lift 3 (1-variable) - target-armor-swept DPS graph** (LOW-MED). `compute_dps_curve`
   already sweeps level; sweeping armor is the same loop; reuse the `spike_curve.js` chart.
   Cleanest pure-math-to-chart lift after #5.
3. **Aggregator P relative-score bar** (see cross-check below) - the orchestrator's in-run
   pick; lowest-risk presentation tweak but dependent on which score surface it binds to.
4. **Lift 4 - live power-spike markers on active-match** (MED, live-gated). Panel + curve
   already exist; needs a live-clock cursor + spike dots. Proof is in-game-only.
5. **Lift 1 - engine-knobs control panel** (MED). Args all exist; needs a control strip +
   re-fetch wiring + one engine re-weight arg. Product-direction (how many knobs).
6. **Lift 2 - action-queue combo simulator** (HIGH value, HIGH effort). Net-new simulator +
   route + panel. Biggest arc; file and schedule.

IN-RUN-able this run: the relative-score bar (#3, per cross-check) is the single safest. Lift 5
and Lift 3-1var are near-in-run but each adds a NEW route/join and should be a framed slice.

## (b) Ready-to-file GitHub issue bodies (OPERATOR-GATE lifts)

**Title:** DS engine-knobs control panel (fight-length / gold-cap / target-resist re-rank)
Body: Add a control strip above the champ-select build chooser exposing 3-4 DS optimizer
knobs (combat-fight-length model, gold cap, enemy target armor/MR) bound to a re-fetch of
`/api/ds-preview` + `/api/build-order`. All inputs except a fight-length re-weight already
exist as args on `rank_items`/`plan_build_order`/`compute_dps` (`rank.py`, `core/build_order.py`,
`dashboard/routes_state.py:408`). Lift from lolsolved.gg (Early/Mid/Late Combat Length
Override 0.5/1.5/4.0, Limit Gold, Tier1/Tier2 Boots, Enemy Armor/MR curves). Mock-testable;
no new data/dep/schema. Scope question: how many knobs ship in v1.

**Title:** DS action-queue combo simulator (ordered cast sequence, per-hit mitigated timeline)
Body: New `agents/daemon_slayer/combo.py` `compute_combo(champion, level, items, sequence,
target_*)` walking a clock over an ordered `[Q, AA, W, R]` list, applying each hit through the
existing ability/AA mitigation pipeline with between-action cooldown/regen resolution; per-hit
`{action, t, raw, mitigated, cumulative}` output. New `/api/ds-combo` route + sequence-input
panel. Composes existing `compute_ability_dps`/`burst`/`compute_dps` + the `cooldown` data in
`champion_abilities.json` (1270 entries) - no new dep, no schema lift. Lift from calc.gg Action
Queue (sequential, max 60 actions/60s). v1 scope: fixed cast times, no animation-cancel modeling.

**Title:** DS stat-sweep graph (damage/EHP across target armor/MR/level/item-count)
Body: New thin `/api/ds-sweep?champion&axis=armor&...` route looping `compute_dps`/`compute_ehp`
over one swept variable (extend the level sweep `compute_dps_curve` already does, `dps.py:924`)
and render with the existing `spike_curve.js` chart component as a "scaling" tab on the DS
preview. 1-variable first (target-armor-swept DPS, shows the anti-armor breakpoint);
2-variable heatmap deferred. Lift from calc.gg stat-sweep. Mock-testable (assert monotonic in
target armor); no new data/dep/schema.

**Title:** Live power-spike markers on Active Match (level/item "now you can fight" line)
Body: Add a live game-clock cursor + discrete spike-threshold markers (level 6/11/16, item
1/2/3 completion) to the already-mounted spike-curve panel in `web/js/panels/active_match.js`
(`am-spike-curve`, already fed `ctx.liveclient` + `p.game_time`). Reuse `compute_dps_curve` /
the archetype scorers; optional `/api/spike-markers` returning the operator's next spike
threshold from live level + owned items. Lift from Aggregator C power-spike framing (level
6/9/11/13/16/18 + item spikes). Marker math mock-testable; final visual is live-game-only.

**Title:** Matchup cooldown-watch on the CC-threat card (enemy ability base cooldown framing)
Body: Join the already-ranked enemy CC spell (`cc_conditional.py` / `_PER_SPELL_CC_DURATIONS`,
already surfaced by `/api/cc-conditional-pressure` + the champ-select chip) to its per-rank
`cooldown` from `champion_abilities.json` and render "watch their <spell> - <Ns>" on the CC
card (`web/js/panels/champ_select.js`). NB this is the Q/W/E ability layer; `summoner_cooldowns`
on `/api/state` (`_state_cooldowns.py`) already covers summoner+ult only. No new data/dep/
schema; mock-testable. Framing decision: base cd vs haste-adjusted (RC has no live enemy haste
-> base-cd-by-rank is the honest v1). Fold into the CC-card rewrite if open.

## (c) Relative-score-bar cross-check verdict

**CONFIRMED - the relative-performance bar is genuinely the lowest-risk of all candidates IN-RUN,
with ONE binding caveat about WHERE the score lives.**

RC's DS layer DOES expose per-item and per-path comparable scores, but in the DYNAMIC endpoints,
NOT in the static curated build list:
- `/api/ds-preview` (`dashboard/routes_state.py:408` -> `rank_for_primary_archetype`) returns a
  ranked list where every row carries `delta_dps` (rounded `_delta(r)`) + `gold` + `scorer`.
  Under the hood `rank.py` `RankedItem` carries `delta_dps`, `new_dps`, `dps_per_1k_gold` - so a
  "% of best" bar is `row.delta_dps / max(rows.delta_dps)` with ZERO new compute. THIS is the
  cleanest home for a per-ITEM relative bar (the build-chooser DS archetype preview already
  renders these rows).
- `/api/build-order` (`routes_state.py:731` -> `plan_build_order`) returns a sequence where each
  `BuildStep` carries `delta` (`core/build_order.py:180`, the scorer delta gained at that step) +
  `scorer` + `unit`. A per-STEP relative bar is `step.delta / max(steps.delta)`. Cheap.

CAVEAT (state it exactly): the STATIC curated build chooser - `coaches/loadout_resolver.py`
`list_variants()` (`:117`) and the `build_paths[]` rows it returns - carries NO score field. Those
rows are hand-curated item-name lists (`key, label, items, runes, summoners, _archetype`); there
is no `delta`/`score` on a build_path. So a relative-score bar CANNOT bind to the curated
build_paths as-is - it must bind to the `delta_dps` rows from `/api/ds-preview` (per-item) or the
`BuildStep.delta` from `/api/build-order` (per-step). Both already render in the champ-select
build surface, so the bar is a pure CSS/JS presentation tweak over data RC already sends down -
no new route, no new compute, no new dep, fully mock-testable. That is why it is the lowest-risk
in-run lift, and exactly why the score source must be the dynamic ranker output, not the curated
variant rows.
