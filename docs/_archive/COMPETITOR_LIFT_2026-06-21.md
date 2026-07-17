# Competitor Lift - Aggregator B (Section-7b heavyweight deep-dive)

Date: 2026-06-21. Session: R10 (gemini DIRECTOR REFILL). Target: **Aggregator B**
(aggregator B), a major League stats / build / tier-list site. This is a dedicated
single-target teardown, deeper than the 2026-06-18_R2 multi-tool survey (which
touched aggregator B only at the gold_share/carry-efficiency grade level).

Method: two heavyweight agents in parallel - an external Aggregator B teardown
(WHAT/HOW) and an RC capability map (HAVE/WHERE, cited file:line) - then
orchestrator verification of every HAVE claim against live code.

**Sourcing caveat (honest):** aggregator B is Cloudflare / anti-bot gated; a plain
WebFetch returns 403. Firsthand captures used a headless browser path (patch
26.12 / 16.12 era pages). Where a data shape could not be captured it is
labeled INFERRED, not fact. No exact XHR payloads are fabricated.

**Anchor fact (captured):** Aggregator B does not aggregate per request - the site
shell renders pre-aggregated static JSON from a CDN, versioned by
patch+region+rank+role. Its value is the *offline-precompute-then-render-flat*
pattern, which RC already owns (DS engine + the ~2800-match local SQLite). So
every finding below is weighted toward PRESENTATION over existing math/data.

---

## Findings (6-point depth checklist each)

### F1 - Tri-metric counters: full-game WR vs lane-phase GD@15 split
- **WHAT:** the champion counter page renders THREE independently-ranked lists
  for the same champ - "Best Picks" (by full-game win rate), "Worst Picks"
  (inverted WR), and "Best Lane Counters" sorted by **GD@15** (gold diff at 15
  min), an explicitly laning-phase metric decoupled from game outcome. A champ
  can top GD@15 (stomps lane) yet sit mid-pack on WR (throws the lead); Aggregator B
  shows both side by side. The page literally tells the reader to use WR AND
  GD@15 together.
- **HOW:** per-matchup aggregate keyed (champ, opponent, role, rank, patch) =
  {winrate, gd15, games} (richer matchup views add csd15 / kill-diff /
  first-tower per [INFERRED from search]); served as flat CDN JSON, not live.
- **HAVE:** PARTIAL/DIFFERENT-BASIS. RC has a 1v1 DS combat-sim verdict
  (all_in / trade / back_off / even + net_swing) via `agents/daemon_slayer/
  matchup.py` -> `/api/ds-matchup` -> `web/js/panels/ds_matchup.js`. That is a
  single selected matchup, sim-based - NOT a winrate/GD@15-ranked counter LIST.
  `data/rewind_history.db` carries per-game participant + timeline rows but has
  NO matchup aggregation table.
- **WHERE:** a new personal-corpus aggregator over `rewind_history.db` (mirror
  `core/duration_winrate.py`) keyed on the locked champ, ranking enemy laners by
  the operator's own GD@15 vs them; new route + a Build Insights tab.
- **EFFORT+RISK:** MED. New compute over a gitignored DB (needs fixtures; see
  the clean-checkout-probe risk), new route + panel. The lane-vs-game distinction
  is genuinely novel for RC.
- **LIFT VERDICT: HIGH value, but new compute path -> FUTURE / BACKLOG** (per
  the charter, a HIGH-lift that needs a new aggregation is not built blind
  in-run). Top FUTURE candidate.

### F2 - Per-item-slot win-rate ladder (each candidate carries metric + sample)
- **WHAT:** the build page frames itemization as a slot-by-slot decision table
  (Starting / Core / 4th / 5th / 6th / 7th), each slot listing 1-3 competing
  options, every option annotated with its own WR% + match count.
- **HOW:** per-slot array {itemId, winrate, matches}; the recommended build is
  the frequency-above-baseline pick (most-frequent build that beats the champ's
  baseline WR), not raw max-WR [INFERRED from FAQ].
- **HAVE:** YES (different metric). RC's DS computes per-item delta-DPS and
  ranks options (`daemon_slayer_picks` in `/api/state`; `/api/ds-relscore` ->
  `web/js/panels/ds_relscore.js`; `web/js/panels/item_build.js`). The relative
  -score bar (delta vs top) already shipped (plan row D1).
- **WHERE:** a re-layout of the already-audited `ds_relscore.js` / `item_build.js`.
- **EFFORT+RISK:** MED. Touches audited live panels; marginal gain over the
  shipped relative-score bar; RC's metric (causal delta-DPS) is already stronger
  than Aggregator B's correlational WR.
- **LIFT VERDICT: MED -> defer.**

### F3 - Tier table: rate always paired with raw sample + inline counter column
- **WHAT:** the tier list shows the raw match count in every row next to the
  percentages (discount a 54% on 9k games vs 328k), plus an inline "Counter
  Picks" column.
- **HOW:** tier = algorithm over (win rate, pick rate, weighted ban rate)
  bucketed into S+/S/A/... pills [INFERRED from FAQ].
- **HAVE:** RC deliberately has NO redistributable global-meta tier/winrate
  (`dashboard/routes_item_wpa.py:36-38` - "NOT a global meta winrate"; personal
  -corpus only). The rate-always-with-sample discipline is ALREADY practiced:
  `web/js/panels/duration_winrate.js:56` renders `n=`; the WPA tables carry a
  confidence/sample bar (`build_insights.js:125-162`).
- **WHERE:** n/a.
- **EFFORT+RISK:** the global-meta tier itself conflicts with RC's deliberate
  no-redistributable-meta stance (ADR-006 / item-wpa framing); the sample-size
  discipline is done.
- **LIFT VERDICT: CLOSED** (sample discipline already shipped; global meta tier
  is a deliberate non-goal).

### F4 - "Highest win rate" vs "most popular" dichotomy
- **WHAT:** Aggregator B surfaces the gap between most-popular and highest-WR picks,
  contextualizing a low-sample high-WR item by its tiny pick rate.
- **HOW:** the same {winrate, pickrate, games} tuple sorted two ways.
- **HAVE:** the adjacent ground is shipped - the relative-score bar (D1) and
  personal-vs-cohort build promotion. RC's recommendation is DPS-causal, so the
  "popular but low-WR" trap matters less than on a correlational site.
- **WHERE:** n/a.
- **EFFORT+RISK:** LOW value for RC.
- **LIFT VERDICT: LOW -> CLOSED.**

### F5 - Skill-order leveling grid (ability-row x level-column pips)
- **WHAT:** a leveling grid (one row per Q/W/E/R, columns = levels 1-18, filled
  pips at the levels you point) plus a compact "Q>W>E" priority chip with WR.
- **HOW:** {ability -> [levels]} + {priority, winrate, games}.
- **HAVE:** RC has `/api/skill-wpa` (first-maxed-basic WR) in the Build Insights
  Skills tab (`build_insights.js:194-214`). A prescriptive full max-order ladder
  is NOT surfaced; `agents/daemon_slayer/rank.py` has ability data but no display.
- **WHERE:** new compute from `rank.py` -> closer to MISSING than PARTIAL.
- **EFFORT+RISK:** MED (new compute), LOW value (well-understood widget).
- **LIFT VERDICT: MED -> defer.**

### F6 - ARAM "ARAM Modifications" balance block
- **WHAT:** ARAM champ pages render the champ's mode-specific damage
  dealt/taken deltas (e.g. -5% dealt / +10% taken) and fold them into ARAM tiers.
- **HOW:** static per-champ ARAM-modifier table (Riot publishes these per patch),
  rendered as labeled signed-percent rows.
- **HAVE:** RC's DS engine already CONSUMES Meraki `aram_modifiers` internally
  for the build math (see `docs/DAEMON_SLAYER.md`), but it is not rendered as a
  per-champ balance block on any UI surface.
- **WHERE:** a small render over data DS already ingests; an ARAM coaching/champ
  surface.
- **EFFORT+RISK:** MED-LOW. The data is partly in-house (Meraki) but a clean
  per-champ render + per-patch upkeep is a small new surface.
- **LIFT VERDICT: MED -> FUTURE** (ARAM-relevant, render over partly-owned data).

### F7 - Duo / synergy delta score (pair WR minus solo baseline)
- **WHAT:** a Duo Tier List ranks bot+sup (and mid+jg) pairs by duo WR plus a
  "synergy" delta = pair WR minus the two champs' solo-WR expectation.
- **HOW:** {pairA, pairB, duo_winrate, games} + synergy delta, bucketed.
- **HAVE:** RC HAS the backend - `/api/duo-synergy` (`dashboard/routes_duo_
  synergy.py`, fed by `core/synergy_external_source.py` + `core/smoothed_rates_
  101qq.py`) serves joint winrate + smoothed pair rate + sample. BUT the
  champ-select PANEL was deliberately REMOVED (item 213) because the grid was
  "disconnected from the actual draft" - `web/js/panels/champ_select.js:3908-3914`
  documents the removal; the route + mock fixture remain unused.
- **WHERE:** re-surfacing must NOT go back on champ-select (the removal is
  deliberate); a separate Build Insights / duo view would be the home.
- **EFFORT+RISK:** LOW effort (endpoint live) but PRODUCT/RE-LITIGATION risk
  (item 213). The fresh atom is only the synergy-delta-vs-solo presentation.
- **LIFT VERDICT: MED -> FUTURE** (placement is a product call; do not re-add to
  champ-select).

### F8 - Summoner / champion per-stat benchmark breakdown  [THE IN-RUN SHIP]
- **WHAT:** Aggregator B's champion-stats / summoner profile renders a dense per-stat
  breakdown (CS@10, gold@10/15, kill-participation, level@10, ...) with
  distribution context.
- **HOW:** per-stat aggregate distribution per (champ, role, patch).
- **HAVE:** **PARTIAL - computed but never surfaced.** RC computes exactly this
  in `core/benchmarks.py` over `data/coach_reference/champion_benchmarks.json`
  (186 champ|mode keys x 11 metrics x {p25,p50,p75,avg,n,weighted_n} + games),
  consumed ONLY by coach prose (`rank_value`) - NO route/panel reads it (grep
  confirmed). This is DISTINCT from the GPI radar (`core/player_gpi.py` ->
  `/api/player-profile`, which shows DERIVED composite axes, not raw per-stat
  numbers) and from the live per-tick band (`core/live_benchmark_band.py`, which
  is shadow-only and validation-gated -> EXCLUDED, not touched here).
- **WHERE:** a new Build Insights "Benchmarks" tab (mirror `duration_winrate.js`)
  + `GET /api/champ-benchmarks` (mirror `routes_duration_winrate.py`) + a small
  additive `core/benchmarks` accessor. Tab wiring: `web/index.html` #bi-tabs +
  a `bi-bench-mount` pane; `build_insights.js` `_renderActive()` dispatch;
  registrar `dashboard/_dispatch.py`.
- **EFFORT+RISK:** LOW. Presentation over EXISTING trusted local data, no schema
  lift, no new dependency, additive tab on an established pattern, not validation
  -gated, not re-litigation, testable.
- **LIFT VERDICT: HIGH-lift LOW-risk -> SHIP IN-RUN (this cycle's slice).**

### F9 - Live in-game overlay: matchup-aware auto-import + benchmark tips
- **WHAT:** a Windows overlay with one-click rune/build auto-import re-tailored
  to the locked opponent, objective timers, per-player scouting, post-game recap.
- **HAVE:** RC already has its own overlay (`?overlay=1`, `rc-shell/`,
  `web/js/panels/overlay_*`), live coaching, and auto rune-push (RuneWriter),
  reading the same Live Client / LCU surfaces.
- **LIFT VERDICT: CLOSED** (covered by RC's existing overlay + coach stack).

---

## Triage

| Finding | Verdict | Disposition |
|---|---|---|
| F8 per-stat benchmark breakdown | HIGH / LOW-risk | **NOW - shipped in-run (Benchmarks tab)** |
| F1 WR-counter vs GD@15 lane-counter split | HIGH / new-compute | FUTURE (BACKLOG) |
| F6 ARAM Modifications balance block | MED | FUTURE |
| F7 duo synergy-delta presentation | MED / re-litigation | FUTURE (non-champ-select home) |
| F2 per-item-slot WR ladder | MED | defer |
| F5 skill-order leveling grid | MED | defer |
| F3 tier table sample discipline | CLOSED | already shipped |
| F3 global-meta tier | CLOSED | deliberate non-goal (ADR-006) |
| F4 highest-WR vs most-popular | LOW | CLOSED |
| F9 live overlay auto-import | CLOSED | covered by RC overlay/RuneWriter |

## In-run action

Shipped F8 as a new **Benchmarks tab in Build Insights**: a per-champion own
-corpus stat distribution (CS@10 / Gold@10 / Gold@15 / KP% / Level@10, median
with p25-p75 range + a games trust column), surfacing `core/benchmarks` data RC
already computes but never rendered. Descriptive personal-corpus, not a meta
winrate; sample-gated; asset-hash auto-reload (ADR-008), no RC restart. Built
TDD-first as an isolated slice, verifier-gated + 5-phase UI-audited before merge.

Lift policy honored: re-implemented in RC's own code, no vendored third-party
code, third-party names kept out of repo source (this docs file only).
