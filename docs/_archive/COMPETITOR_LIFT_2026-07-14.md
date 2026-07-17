# Competitor Lift Teardown - Overlay App F + Overlay App E PC in-game overlays (2026-07-14, R120)

Date: 2026-07-14 - Section 7b deep-dive - gemini-loop DIRECTOR REFILL cycle 18.
Method: two heavyweight adversarial research subagents (one per target, each
armed with the prior teardown as a don't-redo set + RC's hard data-source
constraints), plus an orchestrator grep-verify pass against the live RC repo.
6-point depth checklist (WHAT / HOW / HAVE-grep-cite / WHERE / EFFORT+RISK /
LIFT) applied per surviving candidate.

## Verdict up front

CLEAN no-ship. Both targets' PC in-game overlays are ALREADY fully torn down and
are DRAINED for RC:

- Overlay App F - R100 (docs/COMPETITOR_LIFT_2026-07-10_OVERLAY_APP_F.md, 2026-07-10),
  verdict ~90 percent duplicate, live-overlay competitor category flagged DRAINED.
- Overlay App E - R117 as "Target C" (docs/COMPETITOR_LIFT_2026-07-13_TargetC.md,
  2026-07-13), desktop-companion + ~12-overlay family inventoried, F1 team
  item-value differential shipped in-run, remainder already-have or gated.

The three angles the directive named (jungle timers / power-spike tags / synergy
metrics) each FAIL the net-new test on live ground truth. Two genuinely-new
residuals surfaced this cycle; BOTH are hard-CLOSED (no Live Client signal, no
in-scope axis). No presentation-only + no-new-dep + no-schema + testable AND
net-new candidate survives -> no in-run ship, no BACKLOG-FUTURE add. This is the
R44 / R100 / R112 research-only precedent.

## The architectural wall (unchanged, decisive)

Overlay App F and Overlay App E are both Overlay Platform M apps. Overlay App F consumes the Overlay Platform M
Game Events Provider (GEP), which exposes signals RC's pipeline cannot see -
notably `jungle_camps` (per-camp alive / vision / icon_status). RC is Live Client
`:2999`-only per ADR-006, and `:2999` for the player's OWN game emits NO
jungle-camp events, NO relic-pickup events, NO enemy cooldowns / buffs / wards /
gold / positions. It exposes `allPlayers[].items` (public scoreboard), scores,
levels, and game_time. Adopting Overlay Platform M/GEP = a new blind external dependency +
an architecture change against RC's deterministic-precompute philosophy = a CLOSED
anchor, not a lift. GEP also does NOT expose enemy/team gold, so even the
competitors' "gold gap" readouts are estimates over the same public inputs RC
already holds.

## The three named angles

### Jungle timers  ->  COVERED (objective layer) + CLOSED (per-camp layer)

1. WHAT - live respawn countdowns. Objective half = dragon / baron / herald /
   grubs / inhibitors. Camp half = blue / red / scuttle / Gromp / Wolves / Krugs /
   Raptors per-camp alive+vision.
2. HOW - objective respawns are fixed-cadence arithmetic off `:2999` epic-monster
   events; per-camp respawn needs a camp-clear event, which only Overlay Platform M GEP
   `jungle_camps` provides.
3. HAVE - objective layer YES: `core/event_callouts.py` (48 jungle/dragon/baron/
   objective refs) + `web/js/panels/objective_gauges.js` + `objective_chips.js`.
   Per-camp layer NO, and confirmed absent by design: grep of
   `core/event_callouts.py` for raptor|krug|gromp|wolves|blue_buff|red_buff|
   scuttle|small.camp|camp_respawn = 0 matches (epic-objective-only).
4. WHERE - would be an SR-only overlay panel; but there is no feeding event.
5. EFFORT+RISK - CLOSED: the sole source is Overlay Platform M GEP; a `:2999` fallback can
   only show fixed initial-spawn cadence (low fidelity), and jungle camps are
   off RC's ARAM/Arena live axis. Overlay App E's "clear-route/clear-speed" = jungle
   PATHING = the R117 F4 CLOSED verdict verbatim.
6. LIFT - CLOSED (blocked by data-source + off-axis; reaffirms R117 F4).

### Power-spike tags  ->  COVERED / not-a-Overlay App E-feature

1. WHAT - a champion power-spike / breakpoint readout.
2. HOW - level/item breakpoint math.
3. HAVE - YES: Daemon Slayer is deterministic DPS math (706 items / 173 champs)
   and R81 `/api/spike-curve` already emits phase stoplights -
   `dashboard/routes_spike_curve.py` + `web/js/panels/spike_curve.js` +
   `agents/daemon_slayer/spike_markers.py`. RC's version is DEEPER than the
   competitors' precomputed reference tiles.
4. WHERE - already built.
5. EFFORT+RISK - none; duplicate.
6. LIFT - COVERED. Note: the "power-spike notification" overlay is a Aggregator C
   feature (torn down R89 2026-07-10), NOT a Overlay App E overlay; Overlay App F's is a
   shallow static damage-breakdown reference. Nothing net-new from either target.

### Synergy metrics  ->  COVERED / not-an-in-game-feature

1. WHAT - champion-pairing / team-comp synergy.
2. HOW - pairing win-rate aggregates (pre-game), not a live in-game mechanic.
3. HAVE - YES: `dashboard/routes_duo_synergy.py` + `core/smoothed_rates_101qq.py`
   + `core/synergy_external_source.py` (101.qq duo-synergy, item 277, live-wired)
   + `core/build_planner/kit_synergy.py` + FU02 team-context fan-out. Both apps'
   synergy lives in champ-select/pre-game only; neither offers live in-game
   team-comp analysis (the live team-comp spike comparison is again a Aggregator C
   addition, not in either target's overlay).
4. WHERE - already built.
5. EFFORT+RISK - none; duplicate.
6. LIFT - COVERED.

## Other net-new overlay candidates found (both CLOSED)

- Overlay App F per-small-camp live jungle tracking (Overlay Platform M GEP `jungle_camps`).
  The one genuinely-richer mechanic. CLOSED: sole source is GEP; `:2999` has no
  camp event; SR-only, off RC's ARAM/Arena axis; adopting Overlay Platform M violates
  ADR-006 + the precompute philosophy. Recorded here so a future cycle does not
  re-chase it.
- Overlay App E support-item (World Atlas) tier-upgrade timer. CLOSED: the PREDICTIVE
  countdown needs live quest-gold progress, a field `:2999` does not expose (RC
  can only DETECT the upgrade post-hoc after the item id changes, which is not the
  feature); support-only + SR-only, off RC's ARAM/Arena axis.
- Real-time team gold gap (Overlay App F). NOT net-new: it is an ESTIMATE (CS + kills
  + item value) over the same public inputs RC already holds, and RC already
  ships the honest economy-ahead lens - the team item-value differential
  (`web/js/lib/item_value.js` `teamItemValueDiff` + `web/js/panels/map_state.js`
  `renderItemValueDiff` + the relabeled `web/index.html` bar), shipped R117 F1. A
  gold-gap estimate chip would be a lower-fidelity duplicate of the same lens.

Everything else in both overlays maps 1:1 onto the R100 + R117 don't-redo sets
(benchmark tiles, ult/summ timers, skill order, ARAM/Arena augments, rune/build
import, trinket reminder, loading-screen scouting, per-player WR/KDA/mains cards,
post-match analysis). The Overlay App F manual click-to-track enemy summ/ult CD
overlay remains the sole logged BACKLOG-FUTURE residual (R100 F1, MED-lift,
do-not-build-blind) - GEP has no enemy cooldowns, so even the competitors cannot
automate it, which validates F1's manual scoping. Not re-nominated.

## Final triage

- NOW: none. No presentation-only lift over existing RC data survives refutation.
- FUTURE: none net-new (R100 F1 enemy-CD tracker already logged; do not re-add).
- CLOSED: per-small-camp jungle respawn (no `:2999` camp event; Overlay Platform M-only;
  off-axis - reaffirms R117 F4); support-item upgrade timer (no quest-gold field;
  support/SR-only, off-axis); gold-gap estimate (lower-fidelity duplicate of the
  R117-shipped item-value differential).

## Loop-health note (for the director)

The competitor-lift lane is DRAINED across every family RC has a product-shape
overlap with. This is the THIRD explicit drain flag: the live-scout/overlay
family (R100, 2026-07-10), the stat-site family (R112, 2026-07-13), and now both
PC in-game overlays (R120). The desktop-companion family (R117) was already
"substantially torn down." The remaining meatier open lanes are the Haiku-to-ZERO
Lane A/E precompute programs (charter 4b PRIMARY north star) and the UI-audit
rotation. If a competitor pick is issued again, it should target a DIFFERENT
category with no prior RC teardown (draft theory, replay/VOD analysis,
economy/wave tooling) - not another overlay/companion/stat-site whose value chain
is a production-key warehouse or an Overlay Platform M GEP signal RC's `:2999`-only pipeline
architecturally cannot see. A PART C durable steer to this effect was written to
`ops/loop/control/gemini_ask.txt`.

ENGINE-IMPACT: NONE (docs-only; repo + live DS both ENGINE 1.211.0, no bump, no
Share, no DS restart, no route/schema change). Third-party names are retained in
THIS research artifact only; RC repo code carries none (name-scrub policy). Plain
ASCII throughout.
