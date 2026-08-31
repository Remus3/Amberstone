# RC 2.0 - Operator Q/A Consolidation (Stage 8.3)

> RC 2.0 Phase 8.3 deliverable (`docs/RC2_PLAN.md`). Authored 2026-06-20.
> ASCII only - no em-dashes, en-dashes, or smart quotes (repo hard rule).
>
> PURPOSE: collapse the 97-item raw decision queue in `docs/_archive/RC2_TODO_QA.md`
> (authored 2026-06-19) into the GENUINE RESIDUE. Since the raw queue was
> written, the TOP-10 were all decided (-> E-batch E1-E12) and phases 3-7 +
> E1/E3/E4/E5/E6/E8/E9 shipped. This doc reconciles every item against HEAD so
> the operator decides only what is still live, instead of re-reading 744 lines.
>
> METHOD: 6 read-only agents reconciled all 97 items against the shipped-ledger
> (RC2_PLAN stage table + E-batch + LIVE_GAME_GATED_SYNC). Every SHIPPED/CLOSED
> verdict carries a git/file:line citation; a sample (6 shas, 9 new files, 6
> grep claims) was independently re-verified before this doc was written.

---

## SUMMARY (97 items reconciled vs HEAD 2026-06-20)

| Verdict | Count | Meaning |
|---|---|---|
| SHIPPED | 33 | code landed + git-verified; no operator action |
| GATED-LIVE | 13 | code shipped DEFAULT-OFF or eyeball owed -> `docs/LIVE_GAME_GATED_SYNC.md` (operator-played) |
| GATED | 18 | needs a dataset, producer wiring, or a product judgment call (not just a live eyeball) |
| OPEN | 31 | genuine residual build-decisions; most are headless-buildable now |
| CLOSED | 2 | do-not-pitch (operator-CLOSED / dead-end) |

The old TOP-10 are fully spent (all became E1-E12 or shipped). The new decision
surface is the 31 OPEN + the GATED-LIVE bundle that rides the next live session.

---

## A. RESIDUAL OPEN - headless-buildable now (31)

These need no live game and no new dataset; the loop can build them. Grouped by
surface, highest-glanceability-value first within group.

### Overlay / in-game (Section 1)
- **1** Trinket/control-ward-ready single-pulse glyph cue (no competitor covers it). [S]
- **4** Minimap-anchored objective + camp timer chips on the map pane (biggest glance win). [M]
- **6** Fullscreen-detect "switch to Borderless" one-line hint (read League HWND, AC-safe). [S]
- **9** Auto-declutter `body.fight` combat mode (needs a conservative fight trigger). [M]
- **11** Segmented peripheral-timer meter + conic-gradient ring gauges. [M]
- **12** Restructure overlay into always-on-core + phase-contextual bands (bundles 9/11). [L]
- **13** Elevation-parity (UIPI) detect-and-hint (low value; neither process elevated today). [S]
- **14** Harden display-pick-by-resolution (currently generic enum; 1-PC primary==game holds). [S]

### Home / lobby / champ-select / PGR (Section 2A-2D)
- **15** Last-20 W/L pip strip + true season WR% on home (season_stats exists; pips/WR do not). [S]
- **16** Render post-game-rubric `components` as per-axis sub-bars (only composite grade ships). [S]
- **17** Standalone weekly "this week you... + Good/Bad/Ugly" digest card (primitives exist). [M]
- **20** Overlay this-match's 8 axis values as a distinct dot on the longitudinal GPI radar. [S]
- **21** Last-session recap + tilt nudge at lobby/pre-queue (only today-hero streak ships). [M]
- **23** Re-fire `/api/duo-synergy` at lobby on party>=2 (currently champ-select-only). [S]
- **24** Party/Top8 recent-form tag chips (only Top8 hue-highlight ships). [M]
- **26** Ban-specific reason labels + SR ally AD/AP damage-profile read (pick reasons ship). [M]
- **31** PGR normalized carry-metrics bundle (dmg-per-gold/per-death/vision-per-min/SV/@15). [M]

### History / timeline / dashboard-wide design (Section 2E-2G)
- **36** History champion/queue/result filters (copy the Loadouts filter widget). [S]
- **37** Per-session W-L header rollup in `_agg_session` (cheap once item-35 win loads). [S]
- **38** Richer history row (items/CS/grade) + in-place expand accordion. [M]
- **39** Gold/XP-diff split-area chart + "Story" WPA click-highlight (event ribbon ships). [M]
- **40** Lane @10/@15 dual breakpoints + 0-14/14-25/25+ phase-band rects. [M]
- **41** Teamfight kill-clustering ribbon + death heatmap (clustering heuristic + map asset). [L]
- **45** Quiet-by-default motion sweep - trim ~9 `infinite` CSS loops to one-shots. [S]
- **46** Two-tier design tokens (primitive ramp -> semantic alias; `--signal-*` still literal). [M]
- **47** Labeled grid sections + tonal-elevation surfaces + text-tier tokens. [M]
- **48** Dark-values grep-and-lock audit artifact (palette near-compliant already). [S]

### Responsiveness / engine (Section 4-5)
- **59** Cache the CS gameMode (L2) - RuneWriter still live-reads `/lol-lobby/v2/lobby` per tick. [S]
- **62** Single CS reader on 1-PC (L3) - research-only today; consolidate or leave the relay hop. [M]
- **69** Static-CD ability-haste consumer (a1) - the ONLY genuinely new engine code; needs a new
  schema seam + wiki CD is unreliable. Operator call: build, or formally defer-permanent. [L]

### Program
- **97** Phase 9 (Iteration 2) - runs once after the build phases drain, then the RC 2.0 banner.

## B. GATED-LIVE - rides the next live session (13)

Code is shipped DEFAULT-OFF or an eyeball is owed; all route through
`docs/LIVE_GAME_GATED_SYNC.md` and flip when the operator plays. The minimum
clearing set is 3 games (SR + ARAM + Arena).

- **7** Spike-crossed "do now" cue: arbitration shipped, producer feed unwired + over-fire eyeball.
- **32** aggregator-G-style PGR reframe S3/S4/S5 (needs a live SR window + per-page UI audit).
- **34** carry-efficiency grade default-ON (re-grades historic rows; calibration sign-off).
- **54** ARAM/Arena state-debounce default-ON (`RC_*_STATE_DEBOUNCE`).
- **61** LCU pooling default-ON (`RC_LCU_POOL=1`) + E7 frozen `lcu_client.py` grant.
- **65** 11 flag-ready re-rank seam flips = **E2** 3-game eyeball (DSP11/RF1/B1 already FLIP-READY).
- **67** Anivia revive flip (egg-survive feedback) + Orianna E ally-resist live-input wire.
- **70** Phase-D flips (apply_passive_damage + 4 on_hit + assumed_stacks).
- **71** cost_ceiling flip (behavioral, flippable now) + URF/OFA mode mults (gated on playing them).
- **75** ~88 st-* adaptation-row live producers (needs a live corpus, not one eyeball).
- **78** LBAND1 live benchmark-band wire + validate + flip.
- **79** `set_augment_intent` endpoint probe (next Arena 1750 augment phase).
- **96** Pre-release name-scrub + git-history rewrite = **E10** (release-gated, force-push pre-authorized).

## C. GATED - needs data / wiring / product judgment (18)

Not headless-buildable yet and not just a live eyeball; each blocks on something.

- **50** Laning hold-band Tier-2 recalibration (engine threshold-soften + LFS regen; E5 shipped shadow only).
- **55** Champ-select brief Haiku-elim flip (shadow-log review over real champ-selects first).
- **56** Replay-narrative surface flip (substrate+shadow ship; served path dormant - wire decision).
- **66** Plumb DSP4/5/6/7 + anti-tank live producers into real call sites.
- **68** Cross-eval clusters A/B Tier-2 re-tune (per-champion rewind-WIN validation).
- **72** Live calibration + HZ build/laning gates (accrual-gated: 50+ games / corpus growth).
- **73** HZ-B build-order provenance ENGINE-bump regen (data already current; Tier-2 172-champ gate).
- **76** `/api/ward-heat` producer (no WARD_PLACED source; vision/post-game heuristic).
- **80** CDragon lol-game-data catalog adoption (no concrete PGR/CD-ledger trigger yet).
- **84** Full 362-file Share mirror de-dup (its own session; gist + CI --check coupling).
- **85** `gamepc_*.py` archival (dedicated re-verify slice; prior pass found NOT-safe).
- **88** FUTURE set: scouting/augment-tiers/draft-WR were since SHIPPED; remainder (MMR-predict,
  teamfight-heatmap, GPI deep-dive) stays FUTURE unless promoted.
- **90** Interactive Item Shaper UI (primitive + 22 tests ship; UI blocked on DS live-flip = E2).
- **91** G6 cost-aware build mode (conflicts with DS empirical-WIN anchor; do-not-blind-build).
- **92** DS current-HP% lever flip to a fight-average (owes ENGINE bump + product call).
- **93** Arena S2 augment `level` axis (DEP: patch 26.09 PBE schema not landed).
- **94** Denser Draft-Elo pairwise WR corpus (D2 shipped; tail needs more champ-pair data).
- **95** Arm CI watchdog (built + 19 tests, NOT armed; dry-run a red main first).

## D. SHIPPED - collapsed (33)

No action. Verified against git. Items: 2,3,5,8,10 (overlay), 18,19,22,25,27,28,
29,30,33 (home/lobby/CS/PGR), 35,42,43,44,49,51,52,53,57 (history/design/coaching),
58,60,63,64 (responsiveness), 77,81,82,83,86 (data/hygiene), 87 (the NOW block).
Provenance: RC2_PLAN stage table (P3.x/P4.x/P5.x/P6.x/P7.x) + E1/E3/E4/E5/E6/E8/E9.

## E. CLOSED - do not re-pitch (2)

- **74** cdragon/wiki data tails - needs a NEW extractor key, not the current schema (CLAUDE Settled).
- **89** CLOSED research set - LCU augment dead-end, .rofl packet-parse out-of-scope, ML/CV-minimap/
  voice, effects.py re-merge, forward-marker queue dry (CLAUDE.md Settled + BACKLOG CLOSED).

---

## TOP RESIDUAL DECISIONS (replaces the spent TOP-10)

The highest value-per-effort calls now in front of the operator:

1. **Minimap-anchored objective/camp timer chips (item 4)** - the single biggest in-game
   glanceability win; coord projection already exists.
2. **PGR carry-metrics bundle + score-decomposition sub-bars (items 31, 16)** - turns the
   post-game grade from a black-box letter into a coachable breakdown.
3. **History upgrade trio (items 36, 37, 38)** - filters + per-session W-L + richer rows;
   cheap, compounding, all headless.
4. **Two-tier design tokens + motion sweep + labeled grid (items 46, 45, 47)** - the
   design-system foundation the **E11 Hextech reskin** should sit on; do these before E11.
5. **Home identity polish (items 15, 21)** - W/L pip strip + last-session recap close the
   "how am I doing lately" gap the rank header (E9) opened.
6. **Run the 3-game live session (E2 + the GATED-LIVE bundle)** - one SR + ARAM + Arena
   clears 13 default-OFF seams at once; this is the operator's highest-leverage single act.
7. **Decide item 69 (static-CD ability-haste) and item 91 (cost-aware build)** - the two
   "build new engine code vs defer-permanent" calls; everything else DS is flip-or-accrual.

## OPEN E-STAGES + PHASE 9 (program-level residue)

| E/Phase | Item | Where it lands in this consolidation |
|---|---|---|
| E2 | DS 3-game live-flip eyeball | GATED-LIVE bundle (item 65 + the 11 seams) |
| E7 | ARAM bench-swap + LCU pool default-ON | GATED-LIVE item 61 + bench tightening |
| E10 | ASCII git-history rewrite + force-push | GATED-LIVE item 96 (release-gated) |
| E11 | Hextech reskin (P3/P4 visual cutover) | sequence AFTER OPEN items 46/45/47 (token foundation) |
| E12 | Responsiveness levers L1/L2/L4 | L4 shipped (P6.3); L1/L2 via P6.2; residual = OPEN items 59/62 |
| P9 | Iteration 2 (delta research + design re-synth) | OPEN item 97; runs once all build stages drain |

Full per-item audit trail with evidence citations: **Appendix** below.

---

## APPENDIX - full per-item audit table

| # | item | tag | VERDICT | evidence |
|---|---|---|---|---|
| 1 | Trinket/vision-ready single-pulse cue | NEW | OPEN | no ward-ready cue; overlay_pulse.js glow only |
| 2 | Dashboard stays w/ overlay active | P3.4 | SHIPPED | 183f1969; overlay_settings.js keepCompanion |
| 3 | Ration motion/pulse to urgent | NEW | SHIPPED | overlay_priority.js:113 shouldPulse |
| 4 | Minimap-anchored objective/camp timers | NEW | OPEN | am-pane-map glow only; no timer chips |
| 5 | DPI/scaleFactor overlay sizing | P4.1 | SHIPPED | 4d5d54f0; overlay_state.js:306 normScaleFactor |
| 6 | Fullscreen "go Borderless" hint | NEW | OPEN | comment only; no HWND/WS_POPUP read |
| 7 | Tiered spike-crossed "do now" cue | NEW | GATED-LIVE | arbitration shipped; producer unwired |
| 8 | Settings without hotkeys | P3.5/4.4 | SHIPPED | overlay_settings.js sendOverlayAction |
| 9 | Fight-mode declutter (body.fight) | NEW | OPEN | no fight-state class |
| 10 | Opacity/scale/per-element sliders | NEW | SHIPPED | overlay_settings.js + 85d6b29e |
| 11 | Segmented meter + ring gauges | NEW | OPEN | none in web/js or overlay css |
| 12 | Core+contextual overlay bands | NEW | OPEN | depends on item 9 |
| 13 | Elevation parity guard (UIPI) | NEW | OPEN | crash reason string only |
| 14 | Pick display by resolution | NEW | OPEN | getAllDisplays generic enum only |
| 15 | W/L pip strip + season WR | NEW | OPEN | season_stats exists; no pips/WR% |
| 16 | Score decomposition sub-bars | NEW | OPEN | composite grade chip only |
| 17 | Weekly summary digest card | NEW | OPEN | digest icon != 7-day synthesis card |
| 18 | Rank/tier/LP identity header | GATED | SHIPPED | E9 lcu_ranked.py + main.js:2963 |
| 19 | Champ-pool per-champ trend arrow | NEW | SHIPPED | main.js:1600 recent-vs-baseline arrow |
| 20 | GPI single-match dot on radar | NEW | OPEN | longitudinal polygon only |
| 21 | Last-session recap on lobby | NEW | OPEN | today-hero streak only |
| 22 | Finish ready-check auto-accept | NEW | SHIPPED | E6 main.js:5344 _syncAutoAccept |
| 23 | Duo synergy at the lobby | NEW | OPEN | champ-select-only today |
| 24 | Party/Top8 recent-form chips | NEW | OPEN | Top8 hue-highlight only |
| 25 | Counter-picks vs live enemy comp | NEW | SHIPPED | E4 routes_pickban.py:1231 `_serve_counter_picks` |
| 26 | Ban reason labels + ally AD/AP | NEW | OPEN | pick reasons ship; ban/profile do not |
| 27 | Enemy/ally scouting table | GATED | SHIPPED | E9 routes_scouting.py:1 |
| 28 | Arena augment tier ratings | GATED | SHIPPED | augment_recommender.py (live OCR still gated) |
| 29 | Live per-pick draft win-% | GATED | SHIPPED | draft_elo.py + routes_draft_elo.py |
| 30 | RuneWriter game-2 fix + auto-toggle | NEW | SHIPPED | lcu_rune_writer.py:581 re-arm |
| 31 | Normalized carry-metrics bundle | NEW | OPEN | raw team-sum bars only |
| 32 | aggregator-G-style PGR reframe (s220) | GATED | GATED-LIVE | LIVE_GAME_GATED_SYNC PGR S3/4/5 |
| 33 | Timeline OP-Score trajectory | NEW | SHIPPED | op_score.js GET /api/op-score-curve |
| 34 | carry-efficiency grade default-ON | FLIP | GATED-LIVE | re-grades historic rows |
| 35 | Result-first win-colored history row | NEW | SHIPPED | main.js:1930 + ad4c9906 |
| 36 | History champ/queue/result filters | NEW | OPEN | scope tabs only |
| 37 | Per-session W-L header | NEW | OPEN | _agg_session emits no W-L |
| 38 | Richer row + expand accordion | NEW | OPEN | routes to PGR, no accordion |
| 39 | Gold-diff chart + event ribbon + story | NEW | OPEN | ribbon ships; chart/story absent |
| 40 | Lane @10/@15 breakpoints + bands | NEW | OPEN | single @N row only |
| 41 | Kill-clustering ribbon + death heatmap | NEW | OPEN | no kill_pos plot |
| 42 | prefers-reduced-motion replacement | NEW | SHIPPED | tokens.css:169 (E8 19f8116f) |
| 43 | Redundant status glyphs | NEW | SHIPPED | tokens.css:152 triangle glyphs (E8) |
| 44 | Threshold status helper statusFor() | NEW | SHIPPED | status.js:43 (E8) |
| 45 | Quiet-by-default motion sweep | NEW | OPEN | ~9 infinite loops live |
| 46 | Two-tier design tokens | NEW | OPEN | --signal-good still literal |
| 47 | Labeled grid + tonal elevation | NEW | OPEN | no surface/text-tier tokens |
| 48 | Dark-values audit + lock | NEW | OPEN | near-compliant; no lock artifact |
| 49 | Haiku-free laning coach (CV) | P5.1 | SHIPPED | 77ef5e2a laning_cv_overrides.py |
| 50 | Laning hold-band recalibration | GATED | GATED | E5 shadow only; engine threshold undone |
| 51 | ABC specificity + condition branching | P5.3/5.4 | SHIPPED | trigger field + rebranch |
| 52 | Mid/late/objective playbook | P5.5/5.6 | SHIPPED | objective_playbook.py |
| 53 | Lost-objective/stagnation playbook | P5.7 | SHIPPED | macro_response.py |
| 54 | State-debounce default-ON flip | FLIP | GATED-LIVE | RC_*_STATE_DEBOUNCE OFF |
| 55 | Champ-select brief flip | GATED | GATED | shadow-log review first |
| 56 | Replay-narrative flip | GATED | GATED | served path dormant |
| 57 | Antiheal callout membership review | NEW | SHIPPED | heal_threat.py:187 (product residual) |
| 58 | RuneWriter poll 2.0s->1.0s | P6.2 | SHIPPED | POLL_INTERVAL <=1.0s |
| 59 | Cache CS gameMode (L2) | NEW | OPEN | live-reads lobby per tick |
| 60 | SSE tick + build TTL ->0.5s (L4) | P6.3 | SHIPPED | e9b1a5d0 _STATE_CADENCE_S |
| 61 | Pooled keep-alive LCU conn (L6) | GATED | GATED-LIVE | lcu_pool.py OFF; E7 |
| 62 | Single CS reader on 1-PC (L3) | NEW | OPEN | research-only docs/_archive/2026-07-28-research-consolidation/RC2_RESEARCH_io_timing_map.md:174 |
| 63 | Min-interval guard + 1.5s :2999 floor | NEW | SHIPPED | lcu_pool.py:143 MinIntervalGuard |
| 64 | Port/CPU regression verify | P6.4/6.6 | SHIPPED | 92ca2279 footprint guard |
| 65 | 11 flag-ready re-rank seams flip | FLIP | GATED-LIVE | =E2; live_flip_eyeball.py |
| 66 | Wire DSP4-7 + antitank producers | GATED | GATED | live call-site wiring |
| 67 | Anivia revive + Orianna E flip | FLIP/GATED | GATED-LIVE | revive OFF; Orianna live-wire |
| 68 | Cross-eval clusters A+B re-tune | GATED | GATED | per-champ rewind-WIN |
| 69 | Static-CD ability-haste consumer (a1) | GATED | OPEN | only new engine code; build-vs-defer |
| 70 | Phase-D default-ON flips | FLIP | GATED-LIVE | passive_damage + on_hit + stacks |
| 71 | URF/OFA mults + F2 cost_ceiling flip | FLIP | GATED-LIVE | cost_ceiling flippable now |
| 72 | Live calib + HZ corpus gates | GATED | GATED | accrual (50+ games) |
| 73 | HZ-B build-order provenance regen | GATED | GATED | Tier-2 regen; data current |
| 74 | cdragon/wiki data tails (b1/b2) | CLOSED-ish | CLOSED | needs NEW extractor key |
| 75 | live producers ~88 st-* rows | GATED | GATED-LIVE | live corpus |
| 76 | /api/ward-heat producer | GATED | GATED | no WARD_PLACED source |
| 77 | win on end-of-game ingest | NEW | SHIPPED | ad4c9906; test_history_win_capture.py |
| 78 | LBAND1 benchmark-band wire-in | GATED | GATED-LIVE | real/replayed game |
| 79 | set_augment_intent endpoint discovery | GATED | GATED-LIVE | live Arena 1750 |
| 80 | CDragon game-data catalog adoption | GATED | GATED | no CD-ledger trigger |
| 81 | ASCII full sweep + warning | P7.1 | SHIPPED | dbbd7a8d |
| 82 | stale-file census >1 week | P7.2 | SHIPPED | 29fa1750 |
| 83 | dead-code removal + reorg | P7.3/7.4 | SHIPPED | 5f3391c8 + 386d5e2c |
| 84 | full 362-file mirror de-dup | GATED | GATED | own session; gist/CI coupling |
| 85 | gamepc_*.py archival | GATED | GATED | prior pass NOT-safe |
| 86 | verify dual suite green | P7.5 | SHIPPED | afa07330 17151/0 |
| 87 | NOW block (cross-listed set) | NOW | SHIPPED | P3-P7 + E1/E3-E9 |
| 88 | FUTURE gated set | FUTURE | GATED | dataset/live/product call |
| 89 | CLOSED research set | CLOSED | CLOSED | CLAUDE Settled + BACKLOG |
| 90 | Interactive Item Shaper UI | aspirational | GATED | UI blocked on DS live-flip (E2) |
| 91 | G6 cost-aware build mode | aspirational | GATED | conflicts DS WIN-anchor |
| 92 | DS current-HP% lever flip | aspirational | GATED | ENGINE bump + product call |
| 93 | Arena S2 augment level axis | aspirational | GATED | 26.09 PBE schema not landed |
| 94 | Draft-Elo pairwise WR (denser) | aspirational | GATED | denser champ-pair corpus |
| 95 | CI watchdog arming | aspirational | GATED | 19 tests built; not armed |
| 96 | Pre-release name-scrub + history rewrite | aspirational | GATED-LIVE | =E10; release-gated |
| 97 | Phase 9 - Iteration 2 | P9 | OPEN | runs once build phases drain |
