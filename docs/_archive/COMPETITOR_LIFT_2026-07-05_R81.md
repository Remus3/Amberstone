# Competitor Lift - Live-Game Overlay Assistant (Section-7b deep-dive: matchup + power-spike presentation)

Date: 2026-07-05 (R81). Target category: a **prominent commercial live-game
LoL desktop OVERLAY assistant** - the "live companion" class that runs DURING a
match and overlays real-time reads (matchup difficulty, power-spike timing, live
build steps, objective timers). Third-party names are scrubbed per repo policy;
this teardown is framed by technical substance only (Section-7b). A second widely
used desktop overlay (the build-import + timer class) was researched as a NEGATIVE
CONTROL and is referenced only as "the timer-class overlay."

Single-category teardown in the established Aggregator B/Aggregator H format: WHAT / HOW
/ HAVE (grep RC + cite file) / WHERE / EFFORT+RISK / LIFT per finding, then a NOW
/ FUTURE / CLOSED triage. Distinct from LIFT1 (a damage simulator + a
target-vs-opponent stat advisor) and the pre/post-game stat-site family already
lifted (Aggregator B R10, Aggregator N, Aggregator D R34, Guide Site Q R44, Aggregator S R54,
Aggregator H R71).

## Sourcing + honest caveats

- The live-companion overlay's own model is a STATIC per-champ heuristic ("base
  stats + scaling ratios + ability design + cooldown rhythm", described by the
  vendor as "guidelines, not laws"), surfaced as pre-baked per-phase color cells
  and hotkey panels. No live-telemetry model is exposed for these reads.
- The timer-class overlay (negative control) ships NO dedicated power-spike model
  at all - jungle/ult/summ timers + build/rune import only; even its own docs
  attribute "power-spike timers" to the live-companion tool, not itself. So the
  depth below is on the live-companion overlay; the timer-class one confirms the
  power-spike phase read is the differentiated feature worth studying.
- Anchor fact: the single most-cited feature of the live-companion overlay is the
  three-phase early/mid/late GREEN/YELLOW/RED strength read (per champ AND per
  team). It converts a hard-to-parse scaling story into a one-glance stoplight.
  RC already computes the underlying continuous per-minute team-power curve; the
  liftable value is the phase-bucketed COLOR PRESENTATION, not the model.

---

## Findings (6-point depth checklist each)

### F1 - Three-phase early/mid/late GREEN/YELLOW/RED strength verdict  [NOW - SHIPPED in-run]
- **WHAT:** each champ (and each TEAM) is bucketed into 3 phases - early (0-15m),
  mid (15-30m), late (30m+) - and each phase gets one stoplight color (green =
  strong this phase, yellow = average, red = weak). The team version rolls up both
  comps into the same 3 buckets ("green early = lane bullies + gank potential;
  green late = hypercarries + teamfight"). One glance answers "when is my team
  strong."
- **HOW:** a static per-champ 3-cell color table + a combined team roll-up; no
  live data. Rendered as a 3-segment colored bar per side.
- **HAVE - PARTIAL.** RC computes the CONTINUOUS per-minute team-power curve for
  both teams already: `dashboard/routes_spike_curve.py` `_team_curve` (:333) sums
  normalized per-champ archetype-scored power over minutes 0-40; `_peak_minute`
  (:362) even names the "aggregator C power-spike semantic" (first minute the curve
  crosses 70% of its own max). But RC had NO phase bucketing and NO strong/avg/weak
  verdict - a repo-wide grep for `early_game|mid_game|late_game|phase_strength|
  phase_verdict|"phases"` returned ZERO RC-owned hits before this cycle.
  `web/js/panels/spike_curve.js` `renderSpikeCurve` (:146) drew the sparkline +
  peak triangles but no phase labels/colors.
- **WHERE:** backend `dashboard/routes_spike_curve.py` (additive `phases` block off
  the already-computed `ally`/`enemy` arrays); frontend `web/js/panels/
  spike_curve.js` (a strip beneath the sparkline) which already mounts on the LIVE
  active-match surface via `active_match.js:1584 _renderSpikeCurveFromCtx` - so it
  goes in-game for free (the live-overlay parity).
- **EFFORT + RISK - LOW.** Pure post-process over arrays already in the
  `/api/spike-curve` payload. No new data source, no Claude/Riot dependency, no DS
  engine-math change, no ENGINE_VERSION bump, no schema lift. Fully
  headless-testable.
- **LIFT: HIGH** - highest value, lowest risk. Turns an existing hard-to-read
  sparkline into the instantly legible stoplight read that is THE signature
  live-overlay feature.
- **RC-SPECIFIC CORRECTION (why RC does not copy the "vs own mean" recipe):** RC's
  team curve is monotonic non-decreasing and per-champ-fraction-normalized, so
  every full 5-champ team tops out near the same ~5.0 and a self-relative
  "phase vs own average" coloring would degenerate to early=red / late=green for
  EVERY team (useless). RC ships the HONEST comparative form instead: color each
  team's phase by its phase-mean power vs the OTHER team's phase-mean, 5% relative
  margin. Early/mid differentiate tempo (who wins those fights); late reads parity
  (yellow) when both comps are equally online at full build - a true statement, not
  a bug. This is the "who to fight when" read the operator actually wants.

### F2 - Team collective power spike (not just individual champ)  [NOW - byproduct of F1]
- **WHAT:** a team-comp spike row (sum of the 5 champ phase strengths per side).
- **HOW:** per-side phase sum, re-bucketed.
- **HAVE - YES (continuous form).** `routes_spike_curve.py:333` already sums the
  5-champ team curve for BOTH sides and returns `peaks.ally`/`peaks.enemy`. The
  team dimension exists; only the phase-color roll-up (F1) was missing.
- **WHERE:** same as F1 - falls out of the F1 team-array bucketing for free.
- **EFFORT + RISK - LOW** (subsumed by F1).
- **LIFT: MED** - real, delivered as a byproduct of F1 (the F1 strip is per-team).

### F5 - Matchup card reads the ROLE-MATCHED lane opponent, not "first enemy"  [FUTURE]
- **WHAT:** the overlay maps YOUR lane vs YOUR direct role opponent, not an
  arbitrary enemy.
- **HOW:** role-pair blue-side vs red-side by position, then run the matchup.
- **HAVE - PARTIAL (wrong opponent selection).** RC's matchup engine
  (`agents/daemon_slayer/matchup.py:209 compute_matchup`, route `/api/ds-matchup`,
  `core/laning_verdicts.py`) produces a rich all-in/trade/back-off verdict, but
  `web/js/panels/ds_matchup.js:247` selects `enemyIds[0]` (the FIRST enemy champ),
  not the role-matched laner. RC has role data (Live Client `position` = ROLE).
- **WHERE:** `web/js/panels/ds_matchup.js` opponent-selection logic (pure JS).
- **EFFORT + RISK - LOW-MED.** Presentation/selection fix over an existing engine +
  existing role data; no new dependency. Slight risk: role-data reliability differs
  champ-select vs live. Own slice + UI audit.
- **LIFT: MED** - a correctness upgrade to an existing card; smaller payoff than
  F1. -> BACKLOG (FUTURE).

### F4 - Live in-game matchup panel mount (verdict half only)  [FUTURE]
- **WHAT:** a held-key overlay panel showing per-champ ability cooldowns + specific
  matchup advice DURING the match.
- **HOW:** static per-champ CD tables + pre-written matchup tips on a hotkey.
- **HAVE - PARTIAL / champ-select-only.** RC's matchup verdict
  (`ds_matchup.js:239 renderDsMatchupForChampSelect`) mounts ONLY in champ-select
  (`active_match.js:982`), not the live in-game surface. Live ability cooldowns are
  NOT available (Live Client exposes no cooldowns - CLAUDE.md live-input note).
- **WHERE:** mount `ds_matchup.js` into the active-match live surface reading
  `liveclient` champ ids. The CD-table half is data-blocked (no live CD feed).
- **EFFORT + RISK - MED.** The verdict half is presentation-only but needs live
  enemy-champ resolution + a live mount + its own audit; the CD half is a no-go.
- **LIFT: MED** - overlaps F5 (the cleaner scoped "matchup in-game"). -> BACKLOG
  (FUTURE), paired with F5.

### F3 - Self power-spike transition TOAST  [FUTURE]
- **WHAT:** an in-game toast when a big level (lvl 6) or item-completion spike
  crosses, feeding a history feed.
- **HOW:** watch live level + completed-item events, emit a transient notification.
- **HAVE - MOSTLY.** `web/js/panels/spike_markers.js` computes crossed/next/future
  for the OPERATOR's own level spikes (6/11/16) + item-completion spikes (1/2/3
  legendaries), live-wired via `active_match.js:1603`. Gap: it is a static strip,
  not a toast-on-transition; and it is self-only.
- **WHERE:** `spike_markers.js` (add prev-state diff + a toast slot). Enemy-side is
  a no-go (no live enemy level/item feed - `core/lead_projection.py:20`).
- **EFFORT + RISK - LOW-MED** (self toast); the valuable enemy half is data-blocked.
- **LIFT: LOW** - marginal over the existing strip. -> BACKLOG (FUTURE, low).

### F6 - Gold-lead-per-lane match-state overview  [CLOSED - data-blocked]
- **WHAT:** per-lane gold-lead overview + a spike history feed.
- **HAVE - NO, data-blocked.** RC cannot see enemy (or ally) per-player gold live;
  `core/lead_projection.py:20` explicitly infers macro state from your-side-vs-
  benchmark deltas only. No live per-player gold path exists from any API RC can
  read. **LIFT: CLOSED.**

### F7 - Ally ultimate / summoner timers on portraits  [CLOSED - data-blocked]
- **WHAT:** teammate ult + summ availability tracked on portraits.
- **HAVE - NO, data-blocked.** Live Client exposes no live cooldowns/buffs for any
  player (CLAUDE.md). Cast-event tracking has no RC source. **LIFT: CLOSED.**
- Adjacent note: EPIC-OBJECTIVE timers (the timer-class overlay's headline) RC
  ALREADY owns via `core/event_callouts.py` + `web/js/panels/objective_gauges.js`
  (OQ16 live ring gauges). CLOSED as already-owned.

---

## Triage

| # | Finding | Verdict | Reason |
|---|---------|---------|--------|
| F1 | Early/mid/late green/yellow/red phase-strength strip | **NOW - SHIPPED** | HIGH-lift, LOW-risk, pure post-process over existing `/api/spike-curve` arrays; live-overlay parity for free |
| F2 | Team collective phase spike | **NOW - SHIPPED** | Free byproduct of F1 (F1 strip is already per-team) |
| F5 | Matchup card reads role-matched lane opponent | **FUTURE** | LOW-MED presentation fix; own slice + audit; smaller payoff |
| F4 | Live in-game matchup panel mount (verdict half) | **FUTURE** | Verdict-part liftable; needs live mount + audit; CD half data-blocked; pair with F5 |
| F3 | Self power-spike transition toast | **FUTURE (low)** | Marginal over existing strip; enemy half data-blocked |
| F6 | Gold-lead-per-lane overview | **CLOSED** | No live per-player gold from any API RC can read |
| F7 | Ally ult / summ portrait timers | **CLOSED** | No live cooldown feed; objective timers already owned (OQ16) |

## In-run ship decision

**F1 shipped in-run this cycle (R81 F1)** as a Tier-1 slice: a purely additive
`phases` block on `GET /api/spike-curve` (`dashboard/routes_spike_curve.py`) + a
compact stoplight strip beneath the active-match sparkline
(`web/js/panels/spike_curve.js` + CSS), threaded through the existing live mount.
No DS engine-math change, no ENGINE_VERSION bump, no new data source, no new
dependency. See the R81 LEDGER entry + ORCHESTRATION_PLAN row for the commit.

FUTURE items (F5 / F4 / F3) filed to BACKLOG under "Research / inspiration ->
Competitor lift teardown - 2026-07-05 (live-game overlay, R81)". F6 / F7 CLOSED
(data-blocked - no live per-player gold or cooldown feed; do not re-pitch).
