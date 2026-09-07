# RC2 research consolidation - group G2 (9 files)

Read-only extraction pass, 2026-07-28. Every source doc is dated 2026-06-19/06-20
(`git log -1 -- docs/research/RC2_RESEARCH_pgr.md` -> `fdfdee4d` 2026-06-20), so every
item below was re-QA'd against HEAD, not carried forward.

Cross-check surfaces used: `docs/RC2_QA_CONSOLIDATED.md` (a 2026-06-20 97-item
reconciliation of the SAME material - treated as a dated claim, re-probed, and
corrected where it has since drifted), `docs/RC2_PLAN.md`, `ROADMAP.md`,
`docs/LEDGER.md`, `docs/LIVE_GAME_GATED_SYNC.md`, plus live greps.

---

## docs/research/RC2_RESEARCH_pgr.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| P1 | Normalized carry-metrics bundle: damage-per-gold + damage-per-death + vision-per-min + SV survival ratio in the PGR hero stat-grid (doc section 8 HIGH #1) | STILL OPEN | Repo-wide `grep -i "damage_per_gold\|damagePerGold\|dmg_per_gold\|damage_per_death\|vision_per_min\|visionPerMin\|sv_ratio"` = **No matches found**. Narrow re-grep over `web/js/panels/last_match.js` + `dashboard/builders_last_match.py` + `core/post_game_rubric.py` for `per.?gold\|per.?death\|sv.?ratio` = **empty**. | M |
| P2 | Render the already-computed `post_game_rubric.components` as per-axis decomposition sub-bars under the hero grade (section 8 HIGH #2) | SHIPPED | `web/js/panels/last_match.js:907-951` - "LIFT 2a (2026-06-22): per-role score decomposition", `_AXES` (KDA/CS-min/OBJ/Vision/DPM) + `_pgrSaturation` sat = comp/(2*weight). The standalone 5-bar block was then de-duped into the player-snapshot card's 4 bars (INCOME/COMBAT/OBJECTIVES/VISION) - `last_match.js:926-938`. Note: `RC2_QA_CONSOLIDATED.md:193` item 16 still says OPEN; that row is stale by ~2 days. | - |
| P3 | @15 lane/stat snapshot column (extend the existing @10 timeline-frame path; `csd_at_15`/`gd_at_15` keys already defined) (section 8 HIGH #3) | STILL OPEN | `web/js/panels/pgr_lane_compare.js:140-157` exposes exactly ONE breakpoint (`gold_at_n`/`cs_at_n`/`at_n_minute`, defaulting to 10) - no second frame. Grep for `at_15\|gd_at_15\|csd_at_15` across `web/` returns only `right_now.js:334-335` (`st-csd-15`/`st-gd-15`, the LIVE in-game stat rows - a different surface) and `champ_benchmarks.js:39` (cohort benchmark). Nothing in the PGR path. | S |
| P4 | aggregator-A-style per-phase OP-Score TRAJECTORY on the PGR roster rows (section 8 MED #4) | STILL OPEN | `dashboard/routes_op_score.py:1-18` serves `GET /api/op-score-curve[?mode=][&champion=]` over the LOCAL rewind CORPUS, split win-vs-loss - **no `match_id` parameter**, no per-roster-row curve; `web/js/panels/op_score.js:63` calls it mode-scoped. `RC2_QA_CONSOLIDATED.md:210` item 33 marks this SHIPPED, which is a mis-file: it graded the panel's existence, not the PGR spec's ask (a per-match roster trajectory). | M |
| P5 | Overlay THIS match's 8 axis values as a distinct dot on the longitudinal GPI radar (section 8 MED #5) | SHIPPED | `web/js/panels/player_gpi.js:234` `_matchDotsSvg(axes, thisMatch)`, invoked at `:455` with `payload.this_match`, exported at `:563`. `RC2_QA_CONSOLIDATED.md:197` item 20 (OPEN) is stale. | - |
| P6 | Overlay App E post-game lift (section 6) | REFUTED | The doc's own verdict is "N/A - nothing distinct to lift"; RC's `_compute_quick_review` already exceeds Overlay App E's public post-game behavior. No action was ever proposed. | - |
| P7 | Enable the coded-but-DEFAULT-OFF `carry_efficiency` grade fold (section 0, "a gated grade re-baseline, not new code") | LIVE-GATED | `core/post_game_rubric.py:409` `carry_efficiency: bool = False` - still default-off; weight constant `_CARRY_EFFICIENCY_WEIGHT = 0.5` at `:335`. Flipping re-grades historic rows, so it needs a calibration sign-off (`RC2_QA_CONSOLIDATED.md:211` item 34 GATED-LIVE). | S (flip) |

---

## docs/research/RC2_RESEARCH_timeline.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| T1 | Pattern A - full-size, axis-labeled gold/XP-diff split-area chart in the PGR (reuse the `pgr_winprob.js` midline-split idiom) | STILL OPEN | `web/js/panels/last_match.js:1372-1389` renders three 100x40 `_tlSparkline` mini-charts (GOLD/XP/CS DIFF) - no axes, no labels, no split-area. Grep `gold.?diff\|golddiff` over `web/ dashboard/ core/` returns only `map_state.js:512-516`, an overlay bar whose own comment says "the dormant team_gold_diff bar can never be fed live". No PGR gold-diff panel exists in `web/js/panels/`. | M |
| T2 | Pattern B - objective/kill EVENT RIBBON as x-positioned SVG markers on the gold chart's shared time scale | STILL OPEN | `last_match.js:1391-1407` renders a TEXT `<li>` list (`lm-tl-ev` = clock + label + side), not markers positioned by `timestamp/duration`. `web/js/panels/dev.js:596,727` has a Replay-view ribbon that is likewise a filtered event LIST. The x-aligned marker row the spec asks for does not exist. (`RC2_QA_CONSOLIDATED.md:216` "ribbon ships" refers to this list.) | S-M |
| T3 | Pattern C - lane state at @10 AND @15 breakpoints | DUPLICATE-OF | Same item as **P3** above. | - |
| T4 | Pattern D - 0-14/14-25/25+ phase-band `<rect>`s behind the timeline + DS-fed power-spike ticks | STILL OPEN | Grep `phase.?band` across `web/` = **no matches**. `spike_curve.js` plots a live ally/enemy strength sparkline but nothing overlays post-game phase bands on the match timeline. | M |
| T5 | Pattern E - "Story" wiring: click a WPA phase card -> highlight that x on the timeline | STILL OPEN | Grep `addEventListener\|onclick\|click` in `web/js/panels/post_game_phases.js` = **no matches** (the cards render at `:91` from `payload.top_phases` but carry no handler); `pgr_winprob.js:154,232` dots the swings on its own curve independently. The two panels are not linked. | S |
| T6 | Pattern F - teamfight kill-clustering ribbon (cluster CHAMPION_KILL by ~20s proximity) | STILL OPEN | Grep `killClust\|kill_pos\|cluster` across `web/` = **no matches** (only `minimap_zoi.js:25`, an unrelated comment). No clustering code anywhere in the PGR path. | M |
| T7 | Pattern G - kill/death position heatmap over a Summoner's Rift map image | STILL OPEN | Same empty grep as T6 (`kill_pos`, `heatmap` -> no plotting code). The doc itself rates this LOW / "park it"; the map-image licensing nuance it flags is unchanged. | L |
| T8 | Adopt uPlot (or Chart.js / Chartist / d3) for dense interactive charts | REFUTED | The doc's own verdict is "OVERKILL ... note it as a FUTURE option, do not pull it in now". Re-verified today: `grep -rl "chart\.js\|d3\.min\|plotly\|uplot\|echarts\|highcharts" web/` = **no files**. RC still ships zero charting deps; the recommendation is "do not act", so there is no open item. | - |

---

## docs/research/RC2_COACHING_SPEC.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| C1 | WS1.3 - add a 5th `hold` verdict band + relabel the dominant `even` A-chip (the quantified 39% -> ~53% agreement win) | SHIPPED (shadow) | `core/precomputed_laning_coach.py:60-65` documents the exact relabel rationale, `:72` `"hold": ("Hold and farm this window", "Force a short trade on your cd")`, `:114` rank map includes `"hold": 1`, `:304` `return "hold"`. `docs/RC2_PLAN.md:94` E5 DONE `4da01fbe`. | - |
| C2 | WS1.6 - NEW `core/laning_cv_overrides.py` (enemy dead -> shove, enemy missing -> back off, low HP -> disengage) | SHIPPED | `core/laning_cv_overrides.py:123-136` implements the exact Layer-1/2/3 precedence; `tests/test_laning_cv_overrides.py` exists. `RC2_QA_CONSOLIDATED.md:226` item 49 cites `77ef5e2a`. | - |
| C3 | WS1.6 - NEW standalone `core/laning_band.py` module for the 5-band classifier + confidence gate | SUPERSEDED | `ls core/laning_band.py` -> **No such file or directory**. The spec's own alternative ("or extend `precomputed_laning_coach`") is what landed - the band logic lives in `core/precomputed_laning_coach.py:114,304`. Not a gap, a different placement. | - |
| C4 | WS1.6 Tier-2 - soften `agents/daemon_slayer/matchup.py::_classify` thresholds + re-sweep the LFS tables + re-measure agreement + flip | LIVE-GATED | `agents/daemon_slayer/matchup.py:34-36` still reads `_ALL_IN_KILL_THRESHOLD = 1.0`, `_TRADE_MARGIN = 0.10`, `_EVEN_BAND = 0.05` - byte-identical to the spec's 2026-06-19 baseline. `docs/LIVE_GAME_GATED_SYNC.md:1175` `[HOLD]` HZ-A choice-B even<->hold band flip, "operator-gated, not applied". Needs accrued real-game shadow rows. | L |
| C5 | WS1.6 flip - let the deterministic band drive the SERVED chips once `hz_shadow_report` agreement clears the gate | LIVE-GATED | `ROADMAP.md:47` (RM-03): "P5.2 served CV-flip env (`RC_LANING_CV_SERVED=1`, gated on `hz_shadow_report` agreement delta)" - still listed OPEN in the live RC 2.0 program line. | S (flip) |
| C6 | WS2.2 - append `trigger` / `rebranch_when` / `rebranch_to` to `CoachChoice` with defaults + sanitize in `parse_choices` | SHIPPED | `core/coach_choices.py:68-77` (the three fields, appended at END with `""` defaults per the Python Conventions rule), `:106` `_coerce_rebranch_to`, `:145-147` parse-time coercion with length caps. | - |
| C7 | WS2.5 - chip renderer shows the trigger as a sub-line + `rebranch_when` as a muted "-> switch to B if ..." hint | SHIPPED | `web/js/panels/coach_choices.js:72-74` reads `c.trigger` / `c.rebranch_when` / `c.rebranch_to`, `:81` "RC2 5.3: the trigger names the live condition the option assumes, shown ..."; `:35` folds all three into the render sig. | - |
| C8 | WS3.5 - NEW `core/objective_playbook.py` (objective x lead -> setup + fight rule, spliced as a `kind="playbook"` callout) + shadow log | SHIPPED | `core/objective_playbook.py` exists on disk; `tests/test_objective_playbook.py`, `tests/test_objective_playbook_shadow.py`, `tests/test_objective_playbook_shadow_report.py`, `tools/objective_playbook_shadow_report.py` all present. `RC2_QA_CONSOLIDATED.md:229` item 52 SHIPPED. | - |
| C9 | WS4.3 - emit `objective_events` from `dashboard/_liveclient.py::liveclient_summary` (same loop as `inhib_events`) | SHIPPED | `dashboard/_liveclient.py:337` `objective_events: list = []`, `:370` append, `:372` fail-soft `[]`, `:373` `out["objective_events"] = objective_events`. Guarded by `tests/test_liveclient_objective_events.py`. Consumed downstream by `web/js/panels/objective_chips.js`. | - |
| C10 | WS4.3 - NEW `core/macro_response.py` (lost-objective + stagnation responses) + shadow log | SHIPPED | `core/macro_response.py` exists; `tests/test_macro_response.py`, `tests/test_macro_response_shadow.py`, `tests/test_macro_response_shadow_report.py`, `tools/macro_response_shadow_report.py` present. `RC2_QA_CONSOLIDATED.md:230` item 53 SHIPPED. | - |

---

## docs/research/RC2_OVERLAY_CONDENSATION_SPEC.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| O1 | Section 4 handoff - NEW `web/js/lib/overlay_priority.js` with a pure `selectPrimary(state)` + the band->tier map | SHIPPED | `web/js/lib/overlay_priority.js` exists; `:48` `lethal: 100` priority ladder, `:62` `BAND_TIER`, `:183/:186` exports `selectPrimary, shouldPulse, signalFromState, BAND_TIER, PRIORITY`. Consumed at `web/js/panels/right_now.js:4`. Covered by `tests/test_overlay_priority_rc2.py`. | - |
| O2 | Section 5 - motion rationing: pulse only on an into-EMERGENCY edge or a one-shot URGENT promotion, never on a benign same-band re-emit | SHIPPED | `overlay_priority.js:115` `function shouldPulse(prevCue, sel)`, `:137` documents the edge-gate ("a sustained low-HP fight pulses" once); `right_now.js:8` keeps the prior-S0 shadow for it. `tests/test_overlay_pulse_flip_rc2.py` exists. | - |
| O3 | Section 2 CALLOUT CLAMP - clamp the OVERLAY subset to the 2 nearest-ETA callout rows (dashboard keeps 3) | STILL OPEN | `web/js/panels/callouts.js:78` `.slice(0, 3)` and `:148` `callouts.slice(0, 3)` - both still 3, with no overlay-conditional path. Grep `clamp\|slice(0, ?2)\|two.?row` across `callouts.js`, `overlay_priority.js` and `tests/test_dashboard_condense_rc2.py` = **no matches**. | S |
| O4 | Section 6 - bind the greenlit Hextech palette (base/panel/gold/cyan/good/caution/lethal) across the overlay | SHIPPED | `docs/RC2_PLAN.md:100` E11 "Hextech reskin across surfaces" = **DONE** (all 9 out-of-game surfaces; overlay HUD Hextech landed via the separate overlay-polish lane, R72 / LEDGER 760). | - |
| O5 | Q1 - minimap-anchored objective + camp ETA chips (needs screen-coordinate projection) | SUPERSEDED (objectives) / REFUTED (camps) | The objective half shipped in a DIFFERENT place: `web/js/panels/objective_chips.js:3-6` - "objective respawn-timer chips. A compact glance strip in the overlay CALL pane ... The 'biggest glance win' item" - explicitly NOT minimap-anchored (grep `minimap.?anchor\|projectToMinimap` across `web/` = **no matches**). The camp half is refuted by the same docstring, `:11-13`: "Live Client emits NO jungle-camp events, so camps are intentionally out of scope". | - |
| O6 | Q2 - define the explicit lethal-incoming (hp-at-fight) predicate for the priority-100 rung; "grep before wiring, no assumed surface" | SHIPPED | `overlay_priority.js:124-144` - the Q2 predicate `_isLethalAtFight` with `LETHAL_HP_PCT = 25`, conservative `0 < hp_pct <= LETHAL_HP_PCT`; wired at `:175` `lethal: s.lethal_incoming === true \|\| _isLethalAtFight(nband, s.hp_pct)`. The comment at `:129` records that no `lethal_incoming` producer exists, so the derived path is the live one. | - |
| O7 | Q3 - trinket/control-ward-ready one-shot AMBIENT glyph pulsing on the ready edge | REFUTED | The premise (a trinket cooldown feed) is false. The `w-trinket` ward-cue widget was BUILT and then REMOVED 2026-07-05 - `docs/LEDGER.md` item 783 (commit `d0ca9945`): "removed 3 broken/unneeded HUD widgets - ward cue (`w-trinket`; **Live Client exposes no cooldowns so it never turned off**)", with an explicit "Don't-redo: the 3 removed widgets are gone ... do NOT re-add". `web/js/lib/next_buy_model.js:30` confirms "w-trinket / Ward Cue widget was removed 2026-07-05". (The surviving `NB_TRINKET_*` rule at `:48-51` is a stage-gated BUY nudge, a different feature.) | - |

---

## docs/research/RC2_FOLDER_REORG.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| F1 | `docs io RC peer/` (space in dir name) - KEEP for now, "defer to an operator-gated pass" because renaming hits 10 `.gitignore` secret globs + frozen CLAUDE.md refs | REFUTED | The directory no longer exists: `ls -d "docs io RC peer"` -> **No such file or directory**, and `git ls-files \| grep -i "^docs.?io"` = **empty**. It went with the Peer cross-Claude bridge decommission (`git log -- "docs io RC peer"` -> `62be5e4c` "OQ2 finish the Peer cross-Claude bridge decommission sweep", then `f08ade78`). No CLAUDE.md / ARCHITECTURE.md reference survives (grep = empty). The rename question is moot. | - |
| F2 | Residual of F1 - the 10 `.gitignore` globs pinning the vanished directory | STILL OPEN | `.gitignore:225-229` (and the rest of the block) still carry `docs io RC peer/*ASKS*`, `*BUNDLE*`, `*POST_UPDATE*`, `*PARITY*`, `*SECRET*` ... for a path that no longer exists. Harmless but dead. Grep confirmed no live producer writes there. | S |
| F3 | EXECUTED - `git mv repo-audit.md` + `repo-audit-prompt.md` to `docs/_archive/2026-06-17-repo-audit/` | SHIPPED | `ls repo-audit.md` -> **GONE** from root. `docs/RC2_PLAN.md:186` stage 7.4 DONE `386d5e2c`. | - |
| F4 | All 10 "VERIFIED KEEP-AT-ROOT - do NOT re-litigate" rows | SHIPPED (still true) | Re-probed on disk today: `composition_advisor.py`, `item_advisor.py`, `performance_tracker.py`, `champion_profiles.py`, `role_profiles.py`, `start_claude.ps1`, `GEMINI.md` all PRESENT at root. The doc's conclusion ("the repo structure is already canonical") holds; nothing to carry forward except F2. | - |

---

## docs/research/RC2_ASCII_SWEEP_VERIFICATION.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| A1 | P7.1 enforcement tightening - remove the frozen-file skip from the tree-wide banned-set walk + add `test_frozen_files_clean_of_banned_glyphs` | SHIPPED | `tests/test_smart_quote_hygiene.py:41-47` - "this guard NO LONGER skips frozen files ... plus a new explicit regression lock `test_frozen_files_clean_of_banned_glyphs`". Independent spot-check today: scanned `web/js/panels/last_match.js` for the 8 banned codepoints -> **0 banned-set hits** (the 71 non-ASCII bytes present are U+2192 / U+00B7 render glyphs, exactly the "Retained by design" class the doc allowlists). | - |
| A2 | E10 - ASCII retro sweep across ALL files + git HISTORY rewrite + force-push (explicitly scoped OUT of P7.1, "a separate operator-played stage") | LIVE-GATED | `ROADMAP.md:47` RM-03: "**OPEN:** E10 ASCII+git-history rewrite (force-push, operator-gated)". `docs/LIVE_GAME_GATED_SYNC.md:1199` "E10 / QA96 ASCII git-history rewrite + force-push (release-gated) + pre-release name-scrub". Release-gated, force-push pre-authorized, still unexecuted. | L |

---

## docs/research/RC2_PORT_CPU_FOOTPRINT_VERIFICATION.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| V1 | The `RC_LCU_POOL` default-ON flip "remains operator-gated on a real-game socket observation" (section 5, the file's ONLY open line) | SHIPPED | `core/lcu_pool.py:19-20` "pool_enabled() reads RC_LCU_POOL (**default \"1\" since the E7 flip 2026-06-30** - validated over a live game)"; `:43` `os.environ.get("RC_LCU_POOL", "1")`. `docs/LIVE_GAME_GATED_SYNC.md:2052`: "E7 default-ON flip is DONE - **do NOT re-open this gate**." | - |
| V2 | Machine-lock the 13 Phase-6 footprint invariants in one consolidated guard | SHIPPED | `tests/test_port_cpu_footprint_rc2.py` exists on disk. `RC2_QA_CONSOLIDATED.md:241` item 64 SHIPPED `92ca2279`. Sections 1-4 of this doc are measurements already taken; no other actionable item. | - |

---

## docs/research/RC2_PORT_SAFETY_AUDIT.md

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| S1 | Section 6 follow-up **E7** - wire the FROZEN `lcu/lcu_client.py._request` onto `HttpsConnectionPool` (operator-approved frozen edit); the `poller.py` pilot is the reference impl | SHIPPED | `lcu/lcu_client.py:142-152` - "RC2 E7 / P6.4 (L6, **operator frozen-grant 2026-06-30**) ... `from core import lcu_pool` / `if lcu_pool.pool_enabled():`" with the per-call urlopen retained as the fall-through. `docs/LIVE_GAME_GATED_SYNC.md:2042` confirms the wire-up. | - |
| S2 | Section 6 follow-up E7 - ARAM bench-swap latency | SHIPPED | `docs/LIVE_GAME_GATED_SYNC.md:1676` E7a (`64591d5f`) tightens the RC-LCUAgent bench-swap queue-drain (fast 0.1s re-poll); `:2047` "Bench-swap state-render responsiveness (E7 TODO-1, commit `2ce53103`) shipped independently, NOT gated". | - |
| S2b | Residual live eyeball on the bench-swap drain | LIVE-GATED | `docs/LIVE_GAME_GATED_SYNC.md:596` **G3-01** (was A6) "E7a bench-swap queue-drain eyeball (`64591d5f`): click a bench champ in a real [champ-select]". Needs the operator in a live lobby. | S |
| S3 | Section 6 - live default-ON flip of `RC_LCU_POOL` | DUPLICATE-OF | Same item as **V1** above (already SHIPPED 2026-06-30). | - |

---

## docs/research/RC2_STALE_FILE_CENSUS.md

Every named path was re-probed on disk today, not inherited from the census.

| # | ITEM | VERDICT | EVIDENCE | EFFORT |
|---|---|---|---|---|
| N1 | The headline worklist - quarantine ~96 ARCHIVE-CANDIDATEs (sections A-E) into `_archive/` | SUPERSEDED | `docs/RC2_PLAN.md:185` stage 7.3 DONE `5f3391c8` **corrected this census**: the bulk archive-candidates were re-probed COUPLED (live regression tests / living docs / `routes_static._AGENT_ALLOWED` / immutable agent history) and RETAINED - "correcting the census labels"; only **8** provably-orphan one-shot tools were quarantined to `_archive/2026-06-20-rc2-p73/`. A further batch (4 shipped DS plans + 5 one-shots) archived later under LEDGER 822 Lane 6. Spot-check: `docs/DS_V2_PLAN.md` and `docs/API_SURFACE_AUDIT.md` are both **GONE** from `docs/`. The "~96" number is dead. | - |
| N2 | Section D - archive the 5 `tools/{done,headless-upgrade,ship-batch,sync-all-md,test-first-autopilot}.md` skill duplicates of `.claude/commands/*.md` | STILL OPEN | All five re-probed **PRESENT** on disk today (`ls tools/done.md tools/headless-upgrade.md tools/ship-batch.md tools/sync-all-md.md tools/test-first-autopilot.md` -> all found). `docs/RC2_PLAN.md:185` explicitly records "5 `tools/*.md` skill-dups **DEFERRED** (noisy substring refs)". The deferral reason (substring back-refs) is the actual work. | S |
| N3 | Section E caveat 4 - archive `ops/audit/{P0_INVENTORY,P0_WORKMAP,P1_INVENTORY}.md` once Phase 7 closes | STILL OPEN (hold expired) | `ops/audit/P0_INVENTORY.md` and `ops/audit/P1_INVENTORY.md` re-probed **PRESENT**. The hold condition is satisfied: `docs/RC2_PLAN.md` stages 7.1-7.5 are all DONE, so the "KEEP until Phase 7 closes, THEN flip to archive" trigger has fired and nothing acted on it. | S |
| N4 | Section E - archive the orphan `ops/phase3_file_audit_proposals.py` (the live `RC-Phase3-PeriodicAudit` task runs `-m ops.phase3_file_audit`, which does not import it) | STILL OPEN | File re-probed **PRESENT**. Orphan status re-confirmed today: `grep -rn "phase3_file_audit_proposals" --include=*.py --include=*.xml --include=*.ps1 .` excluding the file itself = **zero hits**. | S |
| N5 | The 7 "Open VERIFY flags for 7.3" (`tools/claude_send.ahk`, `legion_on.ps1`/`legion_off.ps1`, `install_headless_launcher_shortcut.ps1`, `daemon_slayer_build_orders_generate.py`, `champion_loadout_invariants.py`, `champion_loadout_validate_meta.py`, `wrap-gamepc.md`) | SUPERSEDED | 7.3 ran the verify and RETAINED them as coupled (`RC2_PLAN.md:185`). Spot-check today: `tools/claude_send.ahk` and `tools/legion_on.ps1` both **PRESENT**, i.e. the adjudication stands. Likewise the remaining `tools/hotfix_*_item{263,269,275,276,277}.py` were retained (only item167 + item273 were quarantined) - `ls tools/hotfix_*` confirms 6 survivors, `hotfix_*item167*` **GONE**. No open decision. | - |

---

## Roll-up

**Verdict counts across all 9 files (48 items):**

| Verdict | Count |
|---|---|
| SHIPPED | 19 |
| STILL OPEN | 14 |
| LIVE-GATED | 5 |
| SUPERSEDED | 4 |
| REFUTED | 4 |
| DUPLICATE-OF | 2 |

### STILL OPEN + LIVE-GATED, best-first

Ordered by coaching/UX value per unit of effort. Effort in brackets.

1. **T5 - "Story" click-to-highlight wiring** [S]. Link the existing `post_game_phases.js` WPA cards to `pgr_winprob.js`'s curve. Pure glue over two shipped panels, zero new model. Highest value-to-effort in the set.
2. **P1 - Normalized carry-metrics bundle** (dmg/gold, dmg/death, vision/min, SV ratio) [M]. All inputs already sit in the PGR roster row + `match_metrics`; it is arithmetic plus a stat-grid row. The single most-cited gap across both research docs.
3. **P3 / T3 - @15 lane + stat snapshot** [S]. `pgr_lane_compare.js` already has the one-breakpoint machinery; add a second frame lookup. Standard laning grade everywhere else in the genre.
4. **O3 - Callout 2-row clamp for the overlay subset** [S]. One-line-ish change in `callouts.js:78,148` gated on the overlay subset; closes acceptance bar A4 of a spec whose other five bars all shipped.
5. **T1 - Full-size gold/XP-diff split-area chart** [M]. Data and the render idiom both exist (`pgr_winprob.js` midline split); currently only 100x40 sparklines.
6. **T2 - Event ribbon on the chart's shared x-scale** [S-M]. Ships as a pair with T1 - it is what makes the gold line legible. The event LIST already renders; this is repositioning it.
7. **T4 - Phase bands + power-spike ticks** [M]. Bands are trivial `<rect>`s; the spike ticks need a DS hook. Ship bands first.
8. **P4 - Per-match OP-Score trajectory on roster rows** [M]. Needs a `match_id` path through `routes_op_score.py`; the curve primitive exists. Note this was previously mis-filed as SHIPPED.
9. **N2 - Archive the 5 `tools/*.md` skill dups** [S]. Deferred with a stated reason (substring back-refs); the reason is the work.
10. **N3 - Archive `ops/audit/P0_*/P1_INVENTORY.md`** [S]. The hold condition (Phase 7 closes) has fired.
11. **N4 - Archive orphan `ops/phase3_file_audit_proposals.py`** [S]. Zero importers re-confirmed today.
12. **F2 - Drop the dead `docs io RC peer/` `.gitignore` globs** [S]. The directory is gone; the globs are not.
13. **T6 - Teamfight kill-clustering ribbon** [M]. Nice once T2 exists; defer behind it (the doc says the same).
14. **T7 - Kill/death map heatmap** [L]. Doc-rated LOW; map-image licensing nuance unresolved. Park.

**LIVE-GATED (needs the operator in a real game / a release act):**

- **C5 - `RC_LANING_CV_SERVED=1` served CV flip** [S flip]. Gated on a `hz_shadow_report` agreement delta over accrued real games. This is the live gate that unblocks the whole Haiku-to-zero laning lane.
- **C4 - matchup `_classify` threshold softening + LFS re-sweep** [L]. Tier-2; `[HOLD]` in `LIVE_GAME_GATED_SYNC.md:1175`. Depends on C5's measurement.
- **P7 - `carry_efficiency` grade default-ON** [S flip]. Re-grades historic rows, so it needs a calibration sign-off, not just an eyeball.
- **S2b - Bench-swap queue-drain eyeball (G3-01)** [S]. One click in a real champ-select.
- **A2 - E10 ASCII git-history rewrite + force-push** [L]. Release-gated, force-push pre-authorized.

### Cross-file notes for the consolidator

- **Do not carry `docs/RC2_QA_CONSOLIDATED.md` forward verbatim.** It is a 2026-06-20 reconciliation of this same material and has drifted on at least three rows I re-probed: item 16 (score decomposition) shipped 2026-06-22, item 20 (GPI match dot) shipped, and item 33 (OP-Score trajectory) was graded SHIPPED against the wrong artifact. It is still the best index of the 97-item queue - just re-probe each row.
- **RC2_PORT_CPU_FOOTPRINT_VERIFICATION.md and RC2_PORT_SAFETY_AUDIT.md are fully drained.** Both files' only open lines (the `RC_LCU_POOL` flip and the E7 frozen-client wire-up) shipped 2026-06-30. Nothing survives consolidation except the S2b eyeball. Archive both as-is.
- **RC2_ASCII_SWEEP_VERIFICATION.md reduces to one line (E10).** Its P7.1 half is fully shipped and machine-locked.
- **RC2_FOLDER_REORG.md reduces to one line (F2).** Its central open question (`docs io RC peer/`) was answered by a decommission the doc could not have anticipated.
- **RC2_STALE_FILE_CENSUS.md's headline numbers are dead** - stage 7.3 refuted "~96 archive-candidates" down to 8 executed. Carry forward only the 3 named residues (N2/N3/N4), not the census methodology.
- **RC2_COACHING_SPEC.md is 7-of-10 shipped** and is the strongest "mostly done" doc in the set; only the two flips (C4/C5) survive.
