# Competitor lift teardown - 2026-07-28 (R220, Section 7b deep-dive)

**Category: LANE / WAVE-MANAGEMENT / MINION-ECONOMY tooling.**
Method: one heavyweight external research agent (web teardown) plus one read-only
RC ground-truth agent (the HAVE column), synthesized and re-verified by the
orchestrator. Every RC claim below was re-read from source by the merger before
it was written down.

---

## 0. Why this is not the target the directive named

The R220 directive named "Overlay App F or Aggregator B live-game overlay". Both are a
recorded do-not-redo, and the repo says so in three places:

- `ROADMAP.md` RM-01, verbatim: "COMPETITOR-LIFT ROTATION RETIRED: the
  competitor-lift/overlay/companion/stat-site research category is DRAINED 4x
  (R100 Overlay App F / R112 aggregator D+aggregator C / R120 Overlay App F+Overlay App E /
  R125 Aggregator C Desktop) - the director should NOT re-pick it; rotate DS-sweep,
  Haiku-to-ZERO (Lane A/E), or a genuinely un-torn-down category instead."
- `docs/_archive/2026-07-28-research-consolidation/COMPETITOR_LIFT_INDEX.md`, the
  R100 block: "the live-scouting / live-overlay competitor CATEGORY is now
  DRAINED"; the 2026-07-16 block: "DRAINED 5x ... the next competitor pick
  rotates category or accepts the well is dry".
- Overlay App F already has two full teardowns on disk
  (`docs/_archive/COMPETITOR_LIFT_2026-07-10_OVERLAY_APP_F.md`,
  `docs/_archive/COMPETITOR_LIFT_2026-06-16.md`); Aggregator B was covered 2026-06-21 and
  the live-overlay category again at R81 (2026-07-05).

So the directive's INTENT (run a Section 7b lift this cycle) is honored and its
TARGET is rotated, exactly as the drain notes instruct. The rotation was picked by
measurement, not taste: zero keyword hits for `wave manage` / `wave simulator` /
`cs trainer` / `minion wave` / `freeze` / `slow push` across every prior
`COMPETITOR_LIFT_*.md`. This category has never been torn down.

## 1. Three premise corrections - read these before acting on anything below

**PC1. The laning `hold` band ALREADY SHIPPED.** The standing description of the
Lane A blocker ("the verdict vocabulary lacks a hold/farm band") is STALE.
`core/precomputed_laning_coach.py:68-74` carries five labels including
`"hold": ("Hold and farm this window", ...)`, and `laning_band()` at `:271-309`
implements the 5-band precedence off `_HOLD_LOW = 0.05` / `_BACK_OFF = 0.18` /
`_TRADE = 0.10` (`:79-81`). Only the raw DS engine is still 4-band
(`agents/daemon_slayer/matchup.py:184-206`; `VALID_VERDICTS` at
`core/laning_scenario_precompute.py:173-175`). The open work is the FLIP and the
re-measure, not the band. Do not re-build it.

**PC2. The Live Client DOES emit a minion event, and RC has never read it.**
`dashboard/_state_cooldowns.py:18` names `MinionsSpawning` as an event that
actually shows up in the top-level `events` block, and then `:20-21` passes an
empty event list downstream. Repo-wide grep for `MinionsSpawning` returns exactly
one hit: that comment. This is the single most useful fact in the teardown.

**PC3. The stored corpus is 2966 matches, not 3005**, with 693200
`timeline_frames` rows carrying `minions_killed` / `pos_x` / `pos_y`.
`timeline_events` has zero minion event types.

## 2. Targets

| target | shape | license | why picked |
|---|---|---|---|
| statup.gg | Overlay Platform M in-game companion | proprietary, do not vendor | the only product in the category claiming wave-state coaching |
| kdenhartog/MinionCalculator | max-CS calculator | GPL-2.0, do NOT vendor | the only target exposing its CS formula in readable source |
| MOBA Trainer | macro-pattern drill product | proprietary | 51 named macro patterns, the taxonomy end of the category |

**Honest negative up front: there is no standalone wave-simulator product.** Six
distinct search angles returned SEO guide articles, unrelated combat simulators,
and two calculators. The category is thin. Its value to RC is F1 and F2 plus the
F4/F5 negatives, not volume.

---

## 3. Findings

### F1 - Deterministic wave / cannon clock from `gameTime` + the `MinionsSpawning` anchor. HIGH, NOW.

**WHAT.** Every tool in this category that says anything time-bound about waves is
running one pure function: `gameTime -> (wave index, is cannon wave, seconds to
next wave, seconds to next cannon)`. Nobody derives it from observation, because
nobody can (F4). It is arithmetic over four constants: first-wave time, wave
interval, cannon cadence, and the two breakpoints where each changes.

Extracted constant set (wiki.leagueoflegends.com/en-us/Minion): wave interval 30s
until 14:00, 25s to 30:00, 20s after; siege first at 1:30 then every 3rd wave
until 14:00, every 2nd to 25:00, every wave after; 3 melee + 3 caster per wave
with documented reductions; 0.792s intra-wave spawn stagger; stat upgrade tick
every 90s. Wave gold roughly 147g standard and 207g with cannon.

**HOW.** Structurally identical to `core/decision_detector.py:158-176`
`_next_objective_spawn(events, game_time, name, first_at, respawn, kill_event)`:
scan `events` for the anchor, take max `EventTime`, add a cadence, return an
absolute game time. A wave clock is that function with `first_at` supplied by the
live `MinionsSpawning` event instead of a constant, and a piecewise cadence
instead of a scalar respawn. No new algorithm.

**HAVE. No.** `core/event_callouts.py:106` `_SR_OBJECTIVES` is the timed-callout
registry and holds dragon / herald / baron / plates / elder only; constants at
`:72-78`. No wave row, no minion row. `dashboard/_liveclient.py` extracts three
event classes into the slim envelope - `inhib_events` (`:302-313`),
`turret_events` (`:314-329`), `objective_events` (`:337-372`) - and no minion
extract. RC has the transport and has never carried this event class.

**WHERE.** (a) `dashboard/_liveclient.py`, a 4th event extract beside `:302-313`
emitting `minion_events`. Respect the in-file trap documented at `:298-302`:
`events` is a TOP-LEVEL key of `allgamedata`, NOT nested under `gameData`;
reading `gd.get("events")` silently yields an empty list. (b) `core/event_callouts.py`,
a new pure `wave_callout()` beside `recall_callout` at `:414`, with a `_WAVE_KIND`
joining the kind union at `:807` and a mode gate mirroring `_RECALL_MODES` at
`:148`. (c) Nothing else: `dashboard/_deterministic_coaching.py:50-51` already
imports `next_callouts` + `_sort_key`, so a new callout kind reaches `/api/state`
with no route change and renders on `web/js/panels/objective_chips.js`.
Layer: dashboard route plus a pure `core/` module. NOT a DS engine change, so no
ENGINE_VERSION bump.

**EFFORT + RISK.** No new data source, no Riot key, no Claude, no schema lift
(additive envelope key plus additive callout kind). Tier-1. Test beds exist
(`tests/test_event_callouts.py`, `tests/test_event_callouts_recall_item269.py`).
**The one real risk is a constant conflict and it must not be papered over:**
three sources disagree on first-wave time (0:30 vs 1:05 vs 1:30) and on the
cannon-cadence breakpoint (14:00 vs 15:00), and a 2025 change moved first-cannon
arrival 2:05 -> 2:35. Anchor the clock on the live `MinionsSpawning` EventTime,
never on a hardcoded spawn time, and validate the cadence table against one real
game before any flip.

**LIFT: HIGH.** The only finding in the category that is a genuine RC capability
gap, needs zero new dependency, is fully deterministic (squarely on the
Haiku-to-ZERO charter), and unblocks F2 and F3.

### F2 - CS efficiency as actual-over-theoretical-max, replacing the flat 8.0 bar. MED-HIGH, NOW-next.

**WHAT / HOW.** The competitor calculator turns the wave cadence into a
theoretical max-CS-at-time curve and reports actual/max as a percentage.
**Its formula was read from source and is WRONG past 14:00** - it assumes a 30s
cadence and every-3rd cannon forever, so it overstates max CS in exactly the
window where the interval tightens to 25s and 20s. Re-implement from the F1
cadence table; do not port the competitor's arithmetic.

**HAVE. Partially, and worse.** `core/lead_projection.py:57`
`_CS_PER_MIN_BENCHMARK_SR = 8.0` is a single flat scalar for the whole game, and
the module's own honesty note at `:17-27` states RC does not carry the enemy
laner's exact CS at live request time. `dashboard/_adaptation_latch.py:160-177`
latches `cs_at_10` and `csd_at_15` and emits only those two. So RC benchmarks CS
against a constant, not against what was actually available.

**WHERE.** `core/lead_projection.py` (the benchmark axis) plus the F1 cadence
table as its input. **EFFORT + RISK:** LOW-MED, no new data, but it is a live
coaching number so it is do-not-flip-blind. **LIFT: MED-HIGH**, gated behind F1.

### F3 - Wave-conditioned recall. MED, FUTURE (pair with F1).

`core/event_callouts.py:414-444` `recall_callout` takes three purely economic
arguments and has no time or wave term, so it can advise a back into a crashing
cannon wave. The wave clock is the missing input. Deferred only because it
changes an EXISTING served verdict, which is a flip, not an addition.

### F4 - A live wave STATE machine (freeze / slow-push / fast-push). CLOSED, data-blocked.

Verified three independent ways: `:2999` exposes no minion entities of any kind;
the full Overlay Platform M GEP field list gives `minionKills` counts only, no positions or
minion data; the stored timeline has no minion events
(`scripts/rewind_scraper.py:311-341` DDL - no minion column, no minion event
type). Same wall class as the CLOSED ward heatmap. **Do not re-pitch a live wave
state machine from any API.** Only a CV route could see wave position, which puts
it behind Lane E, not here.

### F5 - "Wave state called out" as a category claim. REFUTED.

An Overlay Platform M app's ceiling is the GEP contract, so a competitor's advertised
"wave state" is necessarily a clock, a CS-rate inference, or LLM prose - it is
not observed wave state, because nothing in that stack can observe it. Recorded
as a competitive-position finding: RC can honestly compute the deterministic
subset (F1) that the category only claims.

### F6 - Named macro-pattern taxonomy + graded puzzles. LOW, CLOSED.
Author/content dependency, same verdict as the Guide Site Q F4 prose finding.

### F7 - CS / last-hit trainers as a product tier. CLOSED.
A different product category (a drill trainer, not a live coach).

---

## 4. The RC-side finding the outside research surfaced: a dead wave render surface

This is not a competitor lift. It is what the HAVE sweep found while answering the
HAVE column, and it is the most actionable RC-internal result of the cycle.
**RC renders a complete wave-state UI that nothing has ever fed.**

- `web/js/panels/next.js:16-83` implements a full 3-lane wave readout with a
  documented band table (<=30 FREEZE, 30-65 TRADE, 65-80 CRASH, >=80 DISENGAGE),
  per-lane colouring, and the player's own lane marked. It reads `p.wave_top` /
  `p.wave_mid` / `p.wave_bot`. **The only writers of those three keys in the repo
  are test fixtures** (`scripts/rebuild_sim_fixtures.py:166,191,229`). In a live
  game all three lines render the "-" no-data sentinel, forever.
- Four more labelled STATS rows have zero producers:
  `wave_state_now` / `wave_control` / `wave_freezes` (`core/match_metrics.py:248,253,256`,
  rendered `web/js/panels/right_now.js:336,340,343`) and `cannon_cs_summary`
  (`core/match_metrics.py:244`, rendered `right_now.js:322`). RC has a labelled
  "Cannon CS" row and nothing computes it.
- `gd_at_15` is the same shape: a UI row (`right_now.js:335`) with no live
  producer - the latch emits `cs_at_10` and `csd_at_15` only.
- The ARAM `wave_pct` tier-shift rule (`core/aram_action_rule.py:36-39`) is dead
  in production: the live call site passes `wave_pct=None` explicitly
  (`dashboard/_deterministic_coaching.py:1097`) and there is no producer in
  `vision_server/`, `modes/`, or `game_reader/`.

F1 is the cheapest thing that could ever light any of this up, and the
`cannon_cs_summary` row is F1's natural first consumer.

**Second RC-side finding: the most under-used live field in the repo.**
`dashboard/_liveclient.py:232-241` already puts `creep_score` and `position` for
**all ten players** into the backend envelope every tick. Its only consumer is the
`csd_at_15` latch, once, at the 15:00 mark. (Note `_lean_roster` at `:95-99`
drops `creepScore`, carrying only kills/deaths/assists - the per-player CS reaches
the backend via `players[]`, not via `allPlayers[]`.) A rolling per-player CS-rate
differential is pure arithmetic over data RC already has.

---

## 5. Triage

| id | finding | lift | verdict | reason |
|---|---|---|---|---|
| F1 | wave/cannon clock off `MinionsSpawning` | HIGH | **NOW (filed)** | genuine gap, zero new dependency, deterministic, unblocks F2/F3 |
| F2 | CS efficiency vs theoretical max | MED-HIGH | NOW-next | replaces a flat 8.0 scalar; gated behind F1 |
| RC-1 | dead wave render surface + 6 producer-less keys | - | NOW (filed) | RC-internal defect surfaced by the HAVE sweep |
| RC-2 | all-10 `creep_score` used once per game | MED | FUTURE | pure arithmetic over existing data; needs a live verify |
| F3 | wave-conditioned recall | MED | FUTURE | changes a served verdict, so it is a flip not an add |
| F4 | live wave state machine | - | **CLOSED** | data-blocked 3 ways; CV-only, belongs to Lane E |
| F5 | competitor "wave state" claim | - | **REFUTED** | unobservable within the GEP contract |
| F6 | named-pattern taxonomy | LOW | CLOSED | author/content dependency |
| F7 | CS trainers | - | CLOSED | different product category |

**In-run ship: NONE.** The R220 directive says verbatim "Do not implement code
changes this cycle to maintain strict file disjointness", so F1 is FILED, not
built, despite clearing the Section 7b HIGH-lift + low-risk gate. It is the
strongest NOW candidate this category has produced and should be the next slice.

## 6. Negatives worth keeping

- No standalone wave-simulator product exists. Six search angles, no target.
- The competitor max-CS formula is wrong past 14:00. If RC ever ports one, port
  the cadence table, not the arithmetic.
- Match-V5 carries no minion events at all
  (`scripts/rewind_scraper.py:311-341`), so no wave metric is backfillable from
  the 2966-match corpus. Anything wave-shaped is live-only.
- `tools/hz_shadow_report.py:196-201` `_NON_LANING_ACTION_MARKERS` actively
  EXCLUDES crash / freeze / push / split / roam actions from the laning agreement
  sample. RC's own gate treats wave management as out of scope for the laning
  verdict - so a wave feature will not move the Lane A agreement number, and
  nobody should expect it to.

Upstream data credit: Riot Data Dragon, CommunityDragon, Meraki Analytics,
wiki.leagueoflegends.com (CC-BY-SA 3.0). No competitor code was copied; every
mechanic above is described for clean re-implementation in RC's own code.
