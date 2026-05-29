# Competitor Lift Analysis - 2026-05-28

18 LoL data/coaching/tooling sites reviewed (4 parallel research agents) for features/data/UX
worth lifting into Riot Commander (RC), a LOCAL single-player live-coaching dashboard with the
Daemon Slayer DPS/EHP math engine. RC does NOT replicate crowd-sourced live win/pick/ban stats;
liftable = heuristics, math-presentation, and UX layers over engine math RC already owns.

## Ranked lift candidates

### HIGH
- **lolsolved.gg engine-knobs UX** - genetic-algorithm build theorycrafter (~400k plans/champ),
  models builds vs ENEMY STATS over a tunable combat window (1.5-4s, Burst/Sustain/Mage). Closest
  peer to DS. LIFT: expose tunable combat-window / gold-cap / boot-timing controls on the build
  chooser so the operator can re-rank DS builds for burst-vs-sustain or early-vs-full. Controls
  layer over math RC already has.
- **calc.gg action-queue combo builder** - ordered cast sequence (Q-AA-W-R, max 60 actions/60s)
  evaluated per-hit with mitigation; same Meraki source as DS. LIFT: a sequence-input + timeline UX
  for DS (per-hit mitigated combo vs current aggregate output).
- **calc.gg stat-sweep graphs** - plot damage/EHP across a swept variable (target armor/MR/level/
  item-count); 2-variable = 3D/heatmap surface. LIFT: parametric "how does this scale" graph over
  DS single-number outputs. Math is there; only the sweep loop + render is new.
- **Aggregator C power-spike timeline** - explicit lvl/item spike "now you can fight" markers. LIFT:
  render live spike markers against game_time in Active Match view from existing DS DPS/EHP curves.
- **Aggregator C matchup cooldown-watch cards** - "watch their hook, 16s" key-enemy-cooldown framing.
  LIFT: extend the CC-threat card to surface highest-threat enemy ability cooldowns, reusing
  `_PER_SPELL_CC_DURATIONS` / cc_conditional. (Directly relevant to this session's CC-card rewrite.)

### MEDIUM
- **statcheck.lol stat sandbox** - interactive add-item + set-level -> live full stat block. LIFT:
  a thin UI over already-exported DS functions; high single-player value ("what does this exact
  build give me at level N").
- **Aggregator P relative-performance bars** - "100% baseline" + "+X% vs next" framing. LIFT:
  marginal DPS/EHP-gain score bar per build-path/item in the DS chooser. Zero external dependency.
- **draftsense.net Standard/Aggressive/Defensive 3-way toggle** - cleaner than archetype-keyed rows
  for "go greedy or safe". Also: pin "suppress anti-heal when enemies do not heal" as an explicit
  build filter rule.
- **aggregator N beats/struggles-against split** - "champions to ban to raise win rate" as its own
  labeled category. LIFT: label local Match-V5 per-champ-vs-enemy win-rate (extends item-168
  `_query_struggle_ban`). Locally computable.
- **AlphaMeta matchup-framed damage delta** - "my-build vs their-build" side-by-side. Concept only
  (403, closed-source). Validates a matchup-framed DS presentation.
- **lolstats Carry Score** - rank-independent, opponent-relative 1-10 rating. Informs the pending
  post-game 0-100 score (ROADMAP-S3): normalize relative-to-this-lobby over absolute thresholds.
- **Guide Site Q effect-category item filtering** - group candidate items by family (lethality/crit/
  on-hit/tank/AP), reusing the unique-passive-family data RC tracks.

### LOW / NONE
- probuilds.net, aggregator S - crowd-sourced pro/meta builds RC deliberately does not scrape (LOW).
- aggregator J, lol.ps/datastudio - overlap RC's existing overlay+AI+multi-mode product; no
  distinctive calc surface (LOW). Phase-split (early/late) tier framing mildly interesting.
- hextech.tools - redundant stat browser (RC uses DDragon/CDragon/Meraki directly) (LOW).
- lolscript.com - validates RC's playstyle->build + comp-adjust design; net-new = per-item "job in
  the fight" rationale string (LOW-MED, closed-source).
- third-party review site Z9/blog - pure editorial, no data feed (NONE).
- github.com/FloPrm/lol_analytics - unlicensed README link-list, zero extractable code (NONE).
  Pointer only to Oracle's Elixir / Leaguepedia / lpl.qq (RC already tracks via rewind_history.db
  + the parked 101.qq.com item).

## Synthesis
Every HIGH/MEDIUM candidate is a presentation/controls layer over math RC already owns. None
require a crowd corpus. Strongest near-term: (1) the Aggregator C cooldown-watch framing feeds
directly into this session's CC-card rewrite; (2) the lolsolved/calc.gg stat-sweep + combo-queue +
Aggregator P relative-score-bar cluster is the natural next DS-UI arc; (3) lolstats Carry Score
normalization is the reference for the deferred post-game 0-100 score.
