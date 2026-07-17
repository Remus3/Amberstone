# Competitor Lift - Aggregator D (Section-7b heavyweight deep-dive)

Date: 2026-06-27. Session: R34 (gemini DIRECTOR REFILL, loop cycle 5). Target:
**Aggregator D** (aggregator D), a major League stats / build / tier-list site.
Dedicated single-target teardown, distinct from the already-CLOSED Aggregator A / Aggregator B
/ Aggregator H / Aggregator N lifts (R10/R15/R20 + the 2026-06-18 surveys).

Method: two heavyweight agents in parallel - an external Aggregator D teardown
(WHAT/HOW) and an RC capability map (HAVE/WHERE, cited file:line, hunting the
"computed-but-never-rendered" pattern that R10's F8 ship used) - then
orchestrator verification of every HAVE claim against live code.

**Sourcing caveat (honest):** aggregator D is Cloudflare / anti-bot gated; a
plain WebFetch may 403. Firsthand reads used a headless-browser path on the live
build page (patch ~16.13 / 26.13 era). Where a data shape could not be captured
it is labeled **[INFERRED]**, not fact. No exact XHR payloads are fabricated.

**Anchor fact:** Aggregator D, like its peers, serves pre-aggregated patch-keyed
rollups, not per-request compute - the value to lift is PRESENTATION, which RC
weights for, since RC already owns the math (DS engine + the ~2800-match local
SQLite). Aggregator D's true signature is the **delta-vs-baseline framing on every
recommendation row** + the **popular-vs-winrate dichotomy** (it shows what
players BUILD next to what players WIN with, and teaches the survivorship-bias
gap between them).

---

## Findings (6-point depth checklist each)

### F1 - Popular build vs win-rate build, side by side  [THE IN-RUN SHIP]
- **WHAT:** the build page renders TWO item philosophies at once - a popularity
  -sorted "most built" set AND a win-rate-sorted set, and explicitly captions
  the survivorship trap (a low-sample high-WR item like a snowball Mejai's is
  flagged, not recommended). The user sees the gap between "what I build" and
  "what actually wins."
- **HOW:** two aggregation grains over the same games - frequency of completion
  vs WR per item/subset - each with games + WR; the WR list min-sample-gated
  [INFERRED].
- **HAVE:** **PARTIAL - computed AND served, but the popular half was dropped at
  render.** `core/personal_build_wr.py:227-245` already computes BOTH the
  win-rate ranking (`items` sorted by confidence-weighted `lift` vs the player's
  own baseline) AND `most_common_build` (the modal completed build). The route
  `/api/personal-build` (`dashboard/routes_personal_build.py`) serves both. But
  `web/js/panels/personal_build.js` rendered ONLY the win-rate rows and silently
  threw `most_common_build` away (it appeared in the documented contract comment
  but no render path read it). Exactly the R10 F8 "computed-but-never-surfaced"
  shape, but one field deep instead of a whole module.
- **WHERE:** `web/js/panels/personal_build.js` render + `web/css/panels/
  personal_build.css` - pure presentation over the already-served payload.
- **EFFORT+RISK:** LOW. No new compute, no new route, no new dependency, no
  schema lift, not validation-gated, not re-litigation; testable headless via the
  existing champ-select snapshot fixture (which already carries
  `most_common_build`).
- **LIFT VERDICT: HIGH-lift LOW-risk -> SHIP IN-RUN (this cycle's slice).**

### F2 - Delta-vs-baseline column on every recommendation row
- **WHAT:** every item / rune / skill row shows not just WR but a Delta = how
  much that choice beats the champ's own baseline WR (matchup pages add
  Delta1/Delta2 vs role-average expectations). Positive = a real edge beyond
  what averages predict.
- **HOW:** `row_WR - baseline` per aggregation bucket; matchup deltas use two
  published normalization formulas [INFERRED].
- **HAVE:** YES (the strongest case already shipped). `core/personal_build_wr.py
  :224` emits per-item `lift = est - baseline` and `web/js/panels/
  personal_build.js` renders it as the signed `+pp/-pp` column with a colored
  bar; the champ `baseline_win_rate` is in the header. The WPA tabs
  (`build_insights.js` Items/Runes/Skills) show a WR residual, conceptually the
  same delta.
- **WHERE:** the per-item delta is done. A clean "delta vs your average" column
  on the WPA tabs (replacing the residual label) would be a marginal MED lift.
- **EFFORT+RISK:** MED, touches the audited WPA tabs (don't-redo); marginal gain
  over the shipped per-item lift.
- **LIFT VERDICT: MED -> defer** (the headline form is shipped; F1 is the
  unshipped half of the same idea).

### F3 - Matchup ("vs") delta stats per opponent (gold/CS/kill diffs)
- **WHAT:** per-opponent pages show head-to-head WR + Delta + a difficulty class
  AND the stat diffs (gold/CS/kill @ a marker) and build adjustments specific to
  that matchup.
- **HOW:** aggregation key (champ, role, opponent, patch) with build
  sub-aggregation filtered to matchup games [INFERRED]; sample-expensive.
- **HAVE:** PARTIAL/UNSURFACED. The raw inputs are RECORDED -
  `core/match_metrics.py:246` `csd_at_15`, `:321` `team_gold_diff_trend`, `:311`
  `matchup_history` - and `core/draft_elo_db.py:167` `matchup_winrate` gives
  head-to-head WR. But `/api/personal-vs` (`dashboard/routes_personal_vs.py`)
  returns ONLY W/L record + threat band per enemy; NO module aggregates "vs
  champ X over my corpus: avg gold/CS/kill diff" and no panel renders it.
  `csd_at_15` surfaces only as a single live in-game value (`dashboard/
  _adaptation_latch.py:177` -> `web/js/panels/right_now.js:334`).
- **WHERE:** a new per-opponent aggregator over `rewind_history.db` /
  match_metrics + a new route + a Build Insights tab.
- **EFFORT+RISK:** MED. New aggregation over a gitignored DB (needs fixtures;
  clean-checkout-probe risk), new route + panel. Same profile as Aggregator B's F1, which
  was deferred FUTURE per the charter "a HIGH-lift that needs a new aggregation
  is not built blind in-run."
- **LIFT VERDICT: HIGH value, new compute path -> FUTURE / BACKLOG.** Top FUTURE
  candidate.

### F4 - Strict current-patch-only default with patch toggle
- **WHAT:** default sample is the LIVE patch only (header reads the patch
  number); a toggle switches to last-patch / 7 / 14 / 30-day / combined; the
  first ~48h is flagged preliminary.
- **HOW:** aggregation key includes patch_version; the toggle re-queries a
  different precomputed (patch, window) rollup [INFERRED].
- **HAVE:** RC's corpus is the operator's OWN games (small-n, personal); a
  global-meta patch-window toggle is N/A to a personal corpus, and RC
  deliberately has no redistributable global meta (`dashboard/
  routes_item_wpa.py` framing, ADR-006). The DS engine itself is already pinned
  to the live patch (`data/daemon_slayer/current.txt`).
- **WHERE:** n/a (personal-corpus, not meta).
- **LIFT VERDICT: CLOSED** (the patch-window toggle is a global-meta affordance;
  RC is deliberately personal-corpus only).

### F5 - Skill Priority (lvl 10) vs Skill Order (lvl 15) split
- **WHAT:** two skill panels - Priority sampled at level 10 (larger sample,
  early intent), Order at level 15 (smaller sample, realized order; higher WR
  from level-lead selection bias) - with the bias named inline.
- **HOW:** timeline-frame skill-allocation snapshots at two fixed levels,
  aggregated to sequences with WR/pick%/games [INFERRED].
- **HAVE:** PARTIAL/DIFFERENT. RC has `/api/skill-wpa` (first-maxed-basic WR
  residual) in the Build Insights Skills tab (`build_insights.js:203`). The two
  -level split + the selection-bias caption is not present; it needs per-level
  timeline sampling = new compute.
- **WHERE:** new compute from timeline frames -> closer to MISSING.
- **EFFORT+RISK:** MED (new compute), LOW-MED value (the WPA residual already
  covers the core question).
- **LIFT VERDICT: MED -> defer.**

### F6 - Rune ladder: per-slot WR alongside whole-page WR
- **WHAT:** beyond the recommended page, every individual rune in every slot
  gets its own WR/pick%/games row, separate from whole-keystone-page WR, so you
  can swap one minor rune on evidence.
- **HOW:** two grains - full rune-page combos + marginal per-slot selection
  [INFERRED].
- **HAVE:** PARTIAL. `core/rune_wpa.py:192` -> `/api/rune-wpa` ->
  `build_insights.js:238` already ranks per-rune WR residual + n. Pick% is NOT
  computed (no per-rune pick-rate column).
- **WHERE:** a pick% column on the already-shipped rune-WPA tab.
- **EFFORT+RISK:** MED, touches don't-redo rune-WPA; needs a new pick-rate count.
- **LIFT VERDICT: MED -> defer.**

### F7 - Win-rate-by-game-length curve
- **WHAT:** WR across game-duration buckets, exposing scaling shape
  (early-snowball vs late-monster), shown per-build on the champ page.
- **HOW:** games bucketed by duration (5-min bins), WR per bin [INFERRED].
- **HAVE:** YES. `core/duration_winrate.py:74` `compute_duration_winrate` ->
  `/api/duration-winrate` -> `web/js/panels/duration_winrate.js` (personal
  -corpus). RC's is per-champion personal; Aggregator D's is corpus-wide-per-build,
  a different lens but the same widget.
- **LIFT VERDICT: CLOSED** (shipped; the lens difference is a global-meta gap).

### F8 - Early/mid/late + snowball/comeback ratings bar
- **WHAT:** per-champ 4-tier strength bars (early/mid/late game power, snowball
  vs comeback tendency).
- **HOW:** phase-bucketed WR + lead/comeback aggregates [INFERRED].
- **HAVE:** PARTIAL/SURFACED-AS-PILL. `core/lead_projection.py:160` `_phase`
  (early/mid/late), `:231` `project_lead` (incl. `comeback_odds`) are computed
  and surface as a SINGLE live pill (`web/js/panels/callouts.js:114`,
  `right_now.js` `st-comeback`). A dedicated per-champ rating BAR over the corpus
  does not exist as its own panel; building it needs a new corpus aggregation.
- **EFFORT+RISK:** MED (new corpus aggregation over the phase classifier).
- **LIFT VERDICT: MED -> FUTURE** (second-best FUTURE candidate after F3).

### F9 - One-Trick (OTP) tier list + per-champ elite-player strip
- **WHAT:** a tier list filtered to 60%+-on-champ mains, distinct from the
  general tier list; each champ page shows top players + the champ's rank among
  experts ("good in average hands" vs "good when mastered").
- **HOW:** filter corpus by per-player champion-concentration; separate
  elite-only aggregation [INFERRED].
- **HAVE:** NO (and out of scope). RC is a single-operator tool - there is no
  multi-player corpus to compute an OTP tier list or an elite leaderboard from.
- **LIFT VERDICT: CLOSED** (needs a multi-player corpus RC does not have; ADR-006
  no-redistributable-meta posture).

### F10 - Composite tier ranking with PBI + significance flagging
- **WHAT:** tier = f(WR, pick%, PBI contestedness) with statistical-significance
  flagging, not raw WR.
- **HAVE:** N/A - RC deliberately has no redistributable global-meta tier
  (`dashboard/routes_item_wpa.py`, ADR-006); the sample-size discipline (n shown
  everywhere, shrink toward baseline via `core/smoothed_rates`) is already
  practiced.
- **LIFT VERDICT: CLOSED** (deliberate non-goal; sample discipline already
  shipped).

### F11 - Head-to-head champ comparison + duo/pairwise synergy grid
- **WHAT:** a 2-champ side-by-side tool + a Duos section of pairwise WR.
- **HAVE:** the duo half is HAVE - `/api/duo-synergy` (`core/
  synergy_external_source.py` + `core/smoothed_rates_101qq.py`, item 277) serves
  joint WR + smoothed pair rate; `core/draft_elo_db.py:122` `pair_winrate` adds
  a corpus pair WR. The champ-select panel was deliberately removed (item 213);
  a separate home would be needed.
- **LIFT VERDICT: MED -> FUTURE** (placement is a product call; do not re-add to
  champ-select).

### F12 - Live in-game overlay
- **WHAT:** an overlay with build/rune auto-import, objective timers, scouting.
- **HAVE:** RC already has its own overlay (`?overlay=1`, `rc-shell/`,
  `web/js/panels/overlay_*`), live coaching, and auto rune-push (RuneWriter).
- **LIFT VERDICT: CLOSED** (covered by RC's existing overlay + coach stack).

---

## Triage

| Finding | Verdict | Disposition |
|---|---|---|
| F1 popular-vs-winrate dual build + survivorship caption | HIGH / LOW-risk | **NOW - shipped in-run (personal_build panel)** |
| F3 per-opponent matchup delta-stats table | HIGH / new-compute | FUTURE (BACKLOG) |
| F8 early/mid/late + snowball/comeback rating bar | MED / new-compute | FUTURE |
| F11 duo synergy-delta presentation | MED / re-litigation | FUTURE (non-champ-select home) |
| F2 delta column on WPA tabs | MED | defer (headline form shipped) |
| F5 skill priority(10) vs order(15) split | MED | defer |
| F6 rune per-slot pick% column | MED | defer |
| F4 current-patch-only toggle | CLOSED | global-meta affordance (ADR-006) |
| F7 win-rate-by-game-length curve | CLOSED | already shipped |
| F9 OTP tier list / elite strip | CLOSED | needs multi-player corpus |
| F10 composite tier + PBI | CLOSED | deliberate non-goal (ADR-006) |
| F12 live overlay | CLOSED | covered by RC overlay/RuneWriter |

## In-run action

Shipped **F1** as a presentation enrichment of the existing personal best-build
champ-select card: the panel now renders the operator's most-FREQUENT completed
build (`most_common_build`, previously served-but-dropped) on a "Usual" line,
marks each win-rate-ranked row that belongs to the usual build with a per-row
pip, and renders a conditional survivorship-insight callout naming the gap -
an UNDERUSED WINNER (positive lift, not in the usual build) and/or an OVERUSED
LOSER (negative lift, in the usual build). All data comes from the already
-served `/api/personal-build` payload: zero new compute, no new route, no new
dependency. Built TDD-first (RED guards in `tests/test_personal_build_panel_dom.
py` + render/branch assertions in the champ-select snapshot test), verifier-gated
(24/24), and 5-phase UI-audited (PASS, no MUST-FIX) before commit. CSS+JS only ->
asset-hash auto-reload (ADR-008), no RC restart, no ENGINE/Share.

Lift policy honored: re-implemented in RC's own code, no vendored third-party
code, third-party names kept out of repo source (this docs file only).

## FUTURE candidates routed to BACKLOG

- **F3 per-opponent matchup delta-stats table** (top FUTURE): a new aggregator
  over `core/match_metrics.py` `csd_at_15` / `team_gold_diff_trend` /
  `matchup_history` + `rewind_history.db`, surfacing "vs champ X: avg gold/CS/
  kill diff @15" - the inputs are recorded, only the aggregation + route + panel
  are missing. Needs DB fixtures (clean-checkout-probe risk). Same class as Aggregator B
  F1 (deferred).
- **F8 early/mid/late + snowball/comeback rating bar**: a per-champ corpus
  aggregation over the already-computed `core/lead_projection.py` phase
  classifier + comeback odds.
