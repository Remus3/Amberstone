# Competitor Lift - Aggregator A (2026-06-22, session R15)

Section-7b heavyweight deep-dive. Target: Aggregator A (aggregator A) - a public League stats
site + a desktop companion app. First review of this tool (prior lifts: Aggregator P,
draft tool L, a target-vs-opponent stat advisor, simulator tool R, Aggregator H, Aggregator B).

Method: three parallel general-purpose research agents over DISJOINT Aggregator A surfaces
(builds/itemization, performance-grading/profile, live-game/pre-game/desktop-overlay),
each running the 6-point depth checklist (WHAT / HOW / HAVE-grep-RC-cite / WHERE /
EFFORT+RISK / LIFT) and grepping the RC repo for the HAVE citation. Lift LEGALLY:
re-implement in RC's own code, never vendor; keep the third-party name out of shipped
code (this research doc may name it).

NOW-eligibility gate (for an in-run ACT slice): presentation-only over EXISTING DS
math or existing local data (rewind_history.db / DS endpoints), NO new external
dependency, NO Riot/Claude live call, NO DS schema lift, NO live game required to
validate, and unit-testable with fixtures.

---

## SHIPPED THIS RUN

**Arc-shape readout on the OP Score panel** (Agent-2 F3, HIGH-lift / LOW-risk).
A deterministic classifier labels the SHAPE of each per-minute composite-score line
(the wins curve and the losses curve already plotted by the OP Score tab) with an
RC-native one-word tag + a plain-language read. This is the single Aggregator A profile
mechanic RC had no equivalent for, and it rides entirely on existing local compute.

- NEW `core/op_score_shape.py` - pure classifier (start level, end level, net trend,
  volatility -> one of Snowball / Ramping / Front-loaded / Commanding / Behind /
  Steady / Volatile, RC's own vocabulary, NOT Aggregator A's 14 keyword set).
- `core/op_score_curve.py` - `compute_op_score_curve` now attaches `out["arc"] =
  {win, loss}` derived from the minutes just computed (no extra DB read). The route
  serves it automatically; the cache copies it.
- `web/js/panels/op_score.js` + `web/css/panels/op_score.css` - renders two chips
  (Wins / Losses) between the legend and caption, win-green / loss-red borders, the
  read as a title tooltip; `--fs-xs` tokenized.
- `web/data/ui_mock/op_score.json` - `arc` field so the panel renders the chips in
  ui_mock mode.
- Tests: NEW `tests/test_op_score_shape.py` (15 cases over the 7 shapes + None/thin/
  non-numeric guards + summarize splits) + `tests/test_op_score_curve.py` (arc wired,
  empty -> {win:None,loss:None}) + `tests/test_op_score_panel_dom.py` (chip render +
  CSS token + fixture field). No DS engine change, no ENGINE_VERSION bump, no schema
  lift. 5-phase UI audit CLEAN; live ui_mock pixel capture confirmed (Wins Snowball /
  Losses Ramping, font 16px).

Why this over the other candidates: it is the only finding that clears every NOW gate
(no new dependency, no schema lift, no live game) AND fills a genuine RC gap. RC already
has a per-match grade (post_game_rubric) and a per-minute corpus curve (op_score_curve)
but never NAMED the curve's arc; this is a descriptive re-expression of a line the
dashboard already draws.

---

## Surface 1 - Builds / itemization

Aggregator A's build pages are empirical-frequency-driven (what winning players actually built,
in observed purchase order), partitioned by champ/role/patch/mode, with pick-rate +
win-rate + raw game count per slot. No enemy-comp adaptation.

- F1 Per-slot build sequence with paired win-rate + pick-rate + n. HAVE partial:
  `web/js/panels/build_insights.js` ships an Items/Skills/Runes/Spells table with
  WPA + win-rate columns over rewind_history.db, but FLAT per-item, not per-slot-position.
  WHERE: a route joining `core/build_order.py` slot output with per-slot frequency.
  LIFT MED - the table primitive exists, but a ~2846-match personal corpus is too thin
  at slot granularity (most cells n<5). FUTURE.
- F2 "Strong/Weak against" ranked counter board. HAVE no - RC has a 1v1 trade engine
  (`agents/daemon_slayer/matchup.py`, `/api/ds-matchup`), no ranked counter list. A
  MECHANICAL board (loop matchup.py vs the live enemy team) is liftable over existing
  engine math; the EMPIRICAL win-rate board is the closed "live stats API" direction.
  LIFT MED, but live-game-gated to populate (needs the live enemy roster) -> FUTURE.
- F3 Popular vs highest-win-rate distinction. HAVE partial - build_insights already
  shows both a sample column and a win-rate column with client-side column sort.
  CLOSED (effectively shipped).
- F4 Skill max order with its own win-rate. HAVE partial - a Skill WPA first-max tab
  exists; a full 15-step prescribed order has no DS source (DS does not model level-up).
  LIFT MED, needs new data. FUTURE.
- F5 Item recommendation logic. RC is ARCHITECTURALLY AHEAD: `core/build_order.py` does
  iterative forward selection re-ranked against the REAL enemy resist context per slot
  + the no-double-unique rule; `agents/daemon_slayer/antitank.py` adds a vs-tank shred
  axis Aggregator A lacks. CLOSED (do not lift backward).
- F6 ARAM/Arena dedicated pages. HAVE yes - DS build orders are per-mode (sr/aram/arena),
  `/api/ds-relscore` + `/api/ds-sweep` take a mode param. CLOSED.
- F7 Anti-tank / vs-comp adaptation. RC EXCEEDS (antitank axis + per-slot enemy_stats);
  Aggregator A has none. CLOSED (RC differentiator).

## Surface 2 - Performance grading / profile

Aggregator A's signature is "OP Score" - a per-match 0-10 rating + MVP/ACE badges + a per-minute
timeline graph + 14 plain-language "shape" keywords describing the curve's arc.

- F1 OP Score 0-10 + MVP/ACE. HAVE yes-equivalent - RC has both a role-aware 0-100 static
  grade (`core/post_game_rubric.py`, S+/S/A...) AND a lobby-relative 0-100 blend driving
  MVP/SVP badges (`web/js/panels/last_match.js` `_rosterScores`/`_renderMvpCard`). RC uses
  MVP/SVP vs Aggregator A's MVP/ACE. CLOSED (operator-Settled heuristic).
- F2 Per-minute OP Score timeline (single match). HAVE partial - `core/op_score_curve.py`
  builds the per-minute composite but CORPUS-aggregated (win vs loss split), not single-match.
  The single-match timeline tab plots raw gold/xp/cs diffs, not a composite. A single-match
  composite line reuses the existing formula + SVG renderer + timeline_frames join. LIFT MED.
  FUTURE (a clean follow-on; would pair with the shipped arc classifier).
- **F3 Timeline shape keywords. HAVE no -> SHIPPED THIS RUN (see top).** Aggregator A assigns 1 of
  14 labels from the curve geometry (Late bloomer / Rollercoaster / Resilience / Decline /
  ...). RC now classifies its own win/loss corpus arcs with a 7-label RC vocabulary.
- F4 Lane head-to-head OP Score compare. HAVE yes (final-stats form): `pgr_lane_compare.js`
  does operator-vs-lane-opponent on final stats. The per-minute overlay rides on F2. FUTURE.
- F5 Profile match list / stat bars / champ-stats / "recently played with". HAVE broadly -
  `last_match.js` + `historical_pgr.js` + `player_gpi.js` + `core/personal_build_wr.py` +
  `core/duration_winrate.py` cover list/bars/champ-tab (shipped off prior reviews). A
  "recently played with" duo-frequency panel over existing participant rows is a modest
  LOW-lift FUTURE. CLOSED for the rest.
- F6 Ranked LP trend graph. HAVE no - rewind_history.db records no per-game LP delta; needs
  a Riot/LCU capture + schema column. CLOSED (fails NOW gate).

## Surface 3 - Live-game / pre-game / desktop overlay

- F1 Live-game both-teams readout (enemy rank/champ-WR/form/tilt/smurf). HAVE partial -
  RC enriches the enemy roster with the operator's own record vs each enemy champ
  (`champ_select.js` `/api/personal-vs`) but not each enemy's own champ WR/form. Needs
  live Riot per-opponent fan-out + a live game. FUTURE (live-gated).
- F2 OP Score in-game number/model. HAVE partial - RC has a post-game WPA logistic model
  (`core/post_game_score.py`) + GPI; a 0-10 rollup over existing WPA+benchmarks is NOW-eligible
  but belongs in the staged Post-Game-Review UI work, not a live slice. FUTURE.
- F3 Overlay "you vs tier/role average" live delta. HAVE yes (data) - `core/benchmarks.py`
  + `dashboard/routes_champ_benchmarks.py` + live `:2999` read exist; only a render binding
  is missing, but validating the live delta needs a game. FUTURE (live-gated).
- F4 Live team-gold-gap / win readout. HAVE partial - `core/lead_projection.py` emits
  ahead/even/behind live; a live gold-gap BAR is unrendered; an aggregate "win chance %"
  is the operator-CLOSED ML direction. FUTURE for the bar; CLOSED for the model.
- F5 Auto rune + item-set import. HAVE fully - `lcu/lcu_rune_writer.py` auto-pushes runes +
  corrects spells + pushes build variants to the in-game shop. CLOSED.
- F6 Jungle camp/path timers + ARAM relic timers. HAVE partial - RC has spike markers +
  objective callouts (`core/event_callouts.py`, drake/herald/baron) but no per-camp respawn
  or jungle-path line. Camp timers are live-game-gated. FUTURE.
- F7 Enemy heal-item / grievous-wounds tracker. HAVE yes (engine) - `core/defensive_picks.py`
  + heal-threat modeling exist; live mid-game item-buy detection is constrained (Live Client
  items is null) + live-gated. FUTURE.
- F8 Multisearch (premade-lobby scout). HAVE no - out of RC's single-player scope. CLOSED.
- F9 Overlay injection mechanism. HAVE yes - `rc-shell/` is the same Vanguard-safe DWM /
  borderless / no-DXGI Electron model Aggregator A Desktop uses. CLOSED (validation only).

---

## Triage

- NOW (shipped): Agent-2 F3 arc-shape readout (this run).
- FUTURE (presentation, no live game, candidates for a later UI cycle):
  - Agent-2 F2 single-match per-minute composite OP-Score line (reuses op_score_curve
    formula + SVG renderer); the arc classifier shipped this run extends naturally to it.
  - Agent-2 F5 "recently played with" duo-frequency panel over rewind_history.db participants.
  - Agent-3 F2 a 0-10 performance rollup in the staged Post-Game-Review surface over the
    existing WPA model + benchmarks.
- FUTURE (live-game-gated; need a real game and/or live Riot fan-out): Agent-1 F2 live
  matchup board; Agent-3 F1 enemy-WR/form, F3 live benchmark delta, F4 live gold-gap bar,
  F6 jungle-camp/relic timers, F7 live enemy heal-buy trigger.
- FUTURE (new dependency / schema lift): Agent-1 F1 per-slot frequency sequence (thin-n),
  F4 prescribed skill order; Agent-2 F6 ranked LP trend (new capture + schema).
- CLOSED (RC already has it / ahead, or operator-Settled, or out of scope): Agent-1 F3/F5/F6/F7;
  Agent-2 F1; Agent-3 F5/F8/F9; any live ML win-prediction model; empirical live-stats-API
  build/counter tables.

## Sources
- OP Score explained - help.aggregator A/hc/en-us/articles/31088715328665-OP-Score-explained
- Timeline OP Score keywords - help.aggregator A/hc/en-us/articles/38185639004569
- Aggregator A live-game spectate - help.aggregator A/hc/en-us/articles/30992541874969
- Aggregator A Desktop overlays - aggregator A/desktop/en/overlays
