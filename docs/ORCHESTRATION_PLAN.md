# Orchestration Plan - Gemini-Directed Fanout Run

LIVING DOC. The gemini director reads this each cycle and picks the next OPEN
session (top-to-bottom, phase order A -> F). The executor cycle updates it:
flip the picked session OPEN -> WIP -> DONE, fill the Commit sha, and append any
newly discovered work to the Findings log at the bottom. When no session is OPEN,
the director emits NO_WORK and the loop self-terminates.

Per-cycle contract (enforced by ops/loop/director_prompt.md):
orchestrator multi-agent fanout (disjoint-file worktree subagents, sole merger,
verifier-gate each slice before merge) -> TDD (failing test first) -> py_compile
before any restart -> full pytest suite green -> UI sessions also pass the 5-phase
fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY) + a
Claude_Preview visual check vs /api/state -> commit with a descriptive message ->
push to origin/main -> /done ritual (append docs/LEDGER.md, sync ROADMAP + this
file) -> "C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe" ops/loop/done_sentinel.py. No AskUserQuestion; auto-pick safest option.

ASCII only. No em-dashes, en-dashes, or smart quotes.

## Sessions

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| A1 | DS-surface | DS Profile panel (design + axes batch 1: mobility, sustain, scaling, waveclear). New dashboard/routes_ds_profile.py + web/js/panels/ds_profile.js + CSS + web/data/ui_mock fixtures. Mirror dashboard/routes_ds_sweep.py + web/js/panels/ds_sweep.js. 5-phase UI audit + visual check. | DONE | 8e376858 |
| A2 | DS-surface | DS Profile axes batch 2: added threat-range, zone-control, objective-damage, extended-duel to the A1 /api/ds-profile surface (4 -> 8 axes) + dsp-flag markers. matchup split to A2b (pairwise, not a single-champ axis). 5-phase audit ship-ready. | DONE | 3f23e18c |
| A2b | DS-surface | DS Profile matchup readout: surface agents/daemon_slayer/matchup.compute_matchup (already wired at /v2/matchup) as a pairwise lane-matchup card keyed on a selected enemy + levels + items - a DISTINCT surface from the single-champ radar, NOT a 0-100 profile axis. | DONE | 0a017dc4 |
| A3 | DS-coach | Wire the 2 highest-value axes into coach context: anti-tank build hint (vs high-HP enemies) + scaling power-curve, into modes/* prompts. Shadow-log first, then surface. | DONE | 52f76059 |
| B1 | coach-wire | Wire core/laning_verdicts.py + core/event_callouts.py + core/lead_projection.py (pure generators, zero live-coach consumer) into the live coach dict + callouts.js / right_now.js / next.js. Shadow-log validation first. | DONE | 48411bfc |
| C1 | ui-audit | Champ-Select ARAM + Champ-Select Arena: 5-phase fixture audit + Claude_Preview visual validation vs /api/state. Per docs/UI_SCALE_SPEC_V2.md. | DONE | b4bfa05a |
| C2 | ui-audit | Active Match SR + ARAM + Arena: 5-phase audit + visual validation. | DONE | e81495e0 |
| C3 | ui-audit | Post Game Review SR + ARAM + Arena: 5-phase audit + visual validation. | DONE | aa0a5a7e |
| D1 | lift | DS relative-score bar (Aggregator P lift, BACKLOG.md:21): per-row score_pct fill (delta_dps/top_delta*100). Codeable with fixtures; render-gated on locked champ. | DONE | ab176543 |
| D2 | lift | draft tool L (the community fork) Elo log-odds draft aggregator (BACKLOG.md:78): clean algorithm reimplement (NO vendor) over pairwise WR from rewind_history.db. | DONE | 21bf98ef |
| E1 | research | Per-role grading rubric calibration (BACKLOG.md:100): tune core/post_game_rubric.py weight vectors from public per-role reference data. | DONE | 42780b3d |
| E2 | research | LCU data.json diff vs the reference catalog (BACKLOG.md:19) for richer endpoints. Log findings only; no live capture. | DONE | item 348 |
| E3 | research | Competitor-tool lift secondary sweep, framed by technical substance only (keep third-party names out of repo). Output new NOW/FUTURE/CLOSED candidates into the Findings log. | DONE | item 348 |
| F1 | monitoring | Phone monitoring loop-status panel reading ops/loop/control/{cycle.txt,controller.log,claude.done} + last commit (Tailscale-viewable) + daily upstream content-drift poll (tools/upstream_drift_check.py + scheduled task). | DONE | 5bc8f02f+d3fcc070 |
| HZ-A1 | haiku-zero | Lane A laning-scenario precompute (charter 4b PRIMARY). Build core/laning_scenario_precompute.py: for (champ x matchup x level-band x mana-state x cooldown-state) emit trade/all-in/back-off verdicts via agents/daemon_slayer/{scenario_matrix,combo,mana_sim,fight_report}.py + core/laning_verdicts.py. Persist versioned JSON to data/daemon_slayer/laning_scenarios/. Characterization tests vs DS math. BUILD + PERSIST ONLY - the live coach flip is EXCLUDED (needs real-game validation). | DONE | 85b13b7c |
| HZ-A2 | haiku-zero | Lane A extension: add recall/back-timing + power-spike-ETA verdicts (gold-income + item-completion driven, reuse core/lead_projection.py) to the HZ-A1 lookup tables. Characterization tests. BUILD + PERSIST ONLY. | DONE | dc5e6293 |
| LIFT1 | lift | OPERATOR-QUEUED 2026-06-08 (review NEXT, ahead of HZ-B): deep-dive competitor-lift review per headless-upgrade Section 7b (heavyweight general-purpose agent + browser/Firecrawl MCP; 6-point depth checklist per finding WHAT / HOW / HAVE (grep RC + cite file) / WHERE (RC integration point) / EFFORT+RISK / LIFT verdict HIGH-MED-LOW) of 3 tools: (1) https://seb16120.github.io/LoL-Target-Vs-Opponent-What-stat-to-buy/ - target-vs-opponent "what stat to buy" advisor (overlaps DS anti-tank axis A3 core/ds_antitank_hint.py + armor/MR pen build hints + core/damage_mix.py + the HZ-B build-order precompute); (2) https://simulator-tool-r.invalid/ - LoL damage/combat simulator (overlaps the DS engine compute_dps / compute_matchup / fight_report; check for a DS-validation or sim-surface lift); (3) https://www.reddit.com/r/simulator-tool-r/ - community context for #2. Output docs/COMPETITOR_LIFT_<date>.md. ACT: a HIGH-lift that is LOW-risk (presentation over EXISTING DS math, no new dependency/schema lift, testable) ships IN-RUN as its own slice (+Section 3b UI proof if frontend); a HIGH-lift with a new dependency / schema lift / product-direction call -> BACKLOG + issue (FUTURE); MED/LOW always defer. Lift LEGALLY (re-implement in RC's own code, never vendor). Research + triage NOW/FUTURE/CLOSED, do NOT auto-build everything. | DONE | 4b15b031 |
| LOBBY1 | ui-bug | OPERATOR-REPORTED 2026-06-08 (pre-game lobby): "Invite from my top 8 does not work" - inviting a friend from the operator's top-8 list fails. Investigate ROOT CAUSE first (the lobby invite flow: LCU `/lol-lobby/v2/lobby/invitations` + how the dashboard top-8 / friends surface builds the invite payload - summonerId vs puuid form); fix + regression test. LIVE-GATED: final verification needs a real lobby (do code-side + mark live-verification owed if no lobby). | DONE | 1f4f4118 |
| PGR1 | ui-ux | OPERATOR-REPORTED 2026-06-08 (Post Game Review): advance the s220 aggregator-G-style PGR reframe - "what's next" stage. Read the staged s220 plan (S2-S5, the single-match richer layout + 0-100 RC heuristic score over enriched stats, NO Claude/Riot dep - CLAUDE.md Settled) + docs/ROADMAP_HISTORY, pick the next UNSHIPPED stage, ship ONE stage + Section-3b per-page UI-audit + Claude_Preview visual vs /api/state. | DONE | c162e5bd |
| REPLAY1 | ui-bug | OPERATOR-REPORTED 2026-06-08 (Replay page): match ingestion is not up to date after each game. Investigate the post-game ingest chain (the 90s post-gameEnd Match-V5 fetch + INSERT in `core` rewind live writer [reference_rewind_live_writer] -> rewind_history.db -> the replay/replay-page data source + its cache/refresh); root-cause the staleness (timer not firing? cache TTL? page not re-fetching?). Fix + test. LIVE-GATED final verify. | DONE | 647b455e |
| HIST1 | ui-bug | OPERATOR-REPORTED 2026-06-08 (Session + History pages): clicking a populated match row does NOTHING. Wire the row click. Investigate the session/history panel JS (web/js/panels) - the match rows render but have no click handler (or it no-ops); should open that match's detail (-> HIST2 detached PGR). Fix + DOM test + Section-3b audit. | DONE | ac404c13 |
| HIST2 | ui-ux | OPERATOR-REPORTED 2026-06-08 (Session + History pages): a clicked match should populate + switch to a DETACHED historical PGR frame showing the PGR info "as if the match had just ended", SEPARATE from the live in-use last-match PGR (with a back action to return). Reuse the PGR/last-match render against a historical match-id source; MUST NOT mutate or clobber the live last-match PGR state. Tests + Section-3b UI-audit + visual. Pairs with HIST1. | DONE | ac404c13 |
| CS1 | ui-feature | OPERATOR-REPORTED 2026-06-08 (Champ Select): missing the CC-conditional pairing UI elements. Surface the DS cc_conditional pairing data on champ select (the engine has a saturated cc_conditional ecosystem - agents/daemon_slayer cc_conditional registry/accessors). Investigate the existing cc surface + the champ-select panel (web/js/panels/champ_select.js), add the pairing UI + route if needed + test + Section-3b audit + visual. | DONE | 541cd9d3 |
| CS2 | ui-bug | OPERATOR-REPORTED 2026-06-08 (Champ Select): operator must MANUALLY fix summoner spells - on first champ-select load the client defaults to Flash+Heal or Flash+Teleport at random instead of the intended set (Flash+Teleport). Investigate whether RC can push the correct summoner spells via LCU on champ-select enter (mirror lcu/lcu_rune_writer's auto-push pattern; `/lol-champ-select/v1/session/my-selection` spell1Id/spell2Id) - either ADD a spell auto-push (per-champ/per-mode default) or, if RC already pushes and is wrong, fix the source; if purely client-side + unreachable, document as client-only + close. LIVE-GATED. | DONE | 29cd2788 |
| CS3 | ui-ux | OPERATOR-REPORTED 2026-06-08 (Champ Select): the combo timeline / dps scaling / fight model / relative item power panels do NOT need to be seen during champ select -> MOVE them OFF the champ-select page to a more appropriate surface (e.g. an Active-Match / DS / Build view). Relocate placement only - KEEP all data wiring intact (feedback_field_remove_visual_only: this is a move, not a teardown). Tests + Section-3b audit on BOTH the source (champ-select, panels gone) and destination pages. | DONE | d68cddd3 |
| HZ-B1 | haiku-zero | Lane B build-order precompute. Build core/build_order_precompute.py: optimal build orders per (champ x mode x enemy-comp-archetype) from Meraki aram_modifiers + agents/daemon_slayer/rank.py + core/build_order.py + curated loadouts. Persist to data/daemon_slayer/build_orders/. Characterization tests. BUILD + PERSIST ONLY. | DONE | 3a129071 |
| HZ-B2 | haiku-zero | Lane B enemy-comp branch: anti-tank (high-HP comp) vs anti-squishy build-order variants layered on HZ-B1, using the DS anti-tank axis (A3). Characterization tests. BUILD + PERSIST ONLY. | DONE | 8d8bc311 |
| HZ-C1 | haiku-zero | Lane C deterministic choice-coach generator: read the HZ-A / HZ-B tables and emit core/coach_output.py A/B choices (#rn-immediate chips) for laning trade decisions. SHADOW-LOG alongside the live Haiku coach (log both, do NOT replace). Tests. No live flip. | DONE | 3581afed |
| HZ-D1 | haiku-zero | Lane D Electron overlay: advance rc-shell/ per docs/ELECTRON_OVERLAY.md - read it, pick the next UNSHIPPED code-side phase (Phase 2+), Vanguard-safe (DWM window, NO DXGI capture, Borderless). Ship the headless-safe slice; leave live-visual-only work WIP with a note. Tests where applicable. | DONE | 33dc9b3a |
| HZ-D2 | haiku-zero | OPERATOR RUN FOCUS 2026-06-10 MINIMUM FIRST DELIVERABLE: make the rc-shell companion sidecar window user-movable/draggable (frameless window has NO drag region today). Add a drag region (-webkit-app-region: drag header strip or equivalent) + persist the user-moved position across restarts; keep click-through/interactive zones working. Tests where applicable (rc-shell test harness). | DONE | 0b2eea62 |
| HZ-D3 | haiku-zero | Electron overlay continuation per docs/ELECTRON_OVERLAY.md: advance Phase 4 interactive controls (next unshipped control surface) and any remaining Phase 5 stabilization tail on the ?overlay=1 dashboard surface + rc-shell. Vanguard-safe constraints hold (DWM window, NO DXGI capture, Borderless). Headless-safe slices only; leave live-visual-only verification WIP with a note. | DONE | 33dc9b3a |
| HZ-D4 | haiku-zero | Headless-upgrade charter sweep: one pass of the cost/latency 7-lever sweep (prompt-cache coverage, route TTL, polling cadences, log spam, model tier, task catalog, bundle parity) + the next HZ Haiku-to-ZERO lane increment per ROADMAP (validate-before-flip rule holds; haiku stays interim floor until a precompute is validated vs a real game). Ship only net-positive fixes with green tests, else record CLEAN no-commit with evidence in the Findings log. | DONE | d446ea80+b54d040e |
| P6-G1 | ds-engine | P6 LOLMATH BUILD-ENGINE PARITY G1 (correctness, HIGHEST): DS built the WRONG damage axis - core/archetype_picks resolved the scorer archetype from the DDragon CLASS tag (role), ignoring the kit's lolmath.damage_distribution, so AP kits (Gwen/Teemo/Rumble/Diana) built crit/AD and AD assassin Pyke built AP enchanter. Fix re-bases the DEFAULT archetype onto the kit axis (below operator picks); tank axis-neutral. 18 default-source champs re-based (11 sweep-named + 7 AP assassins the sweep missed: Akali/Ekko/Evelynn/Fizz/Kassadin/Katarina/LeBlanc + Pyke AP->AD). All 9 build_orders tables regenerated (flat+HZ-B1+HZ-B2, sr/aram/arena) at ENGINE 1.121.0 -> 1.122.0; DS :8893 restarted; Share re-synced. Per-champ tests (29) + table-axis parity (18); DS 7095 + RC suites green. NOT flipped (kit axis sides with DS or axis-neutral): XinZhao/Taric + 6 tank-archetype AP kits (-> BACKLOG role call). archetype_mismatch.py was a red herring (UI nudge). | DONE | 1d7da921 |
| P6-G4 | core/build_order | P6 LOLMATH BUILD-ENGINE PARITY G4 (boots-pool refresh, low-risk): DS emitted only legacy tier-2 boots (Mercury's x140 / Berserker's x30 in the sweep) while lolmath uses the 16.12.1 SR-only tier-3 upgrades. core/build_order._select_boots now upgrades the resolved tier-2 family to its tier-3 form on SR (map 11) via the new _BOOTS_SR_UPGRADE map (each DDragon into verified map11-only); ARAM (12) + Arena (30) keep tier-2 (no tier-3 there); assassin default moved off the out-of-store Mobility Boots (3117) to Ionian -> Crimson Lucidity. No engine MATH change (ranker byte-identical, never imports core/build_order; the AH/tenacity registries + items.json already carried the tier-3 ids). All 9 build_orders tables regenerated at ENGINE 1.122.0 -> 1.123.0; DS :8893 restarted; Share re-synced (336). 9/9 tables verified (SR tier-3, ARAM/Arena tier-2, 0 Mobility); boots test 29; DS-dir 7095 + RC 7943 green. Deferred: Arena should use the 22xxxx boots mirror (3xxx are map30=False). | DONE | a58a1f10 |
| P6-G5 | ds-engine | P6 LOLMATH PARITY G5 (item-pool gaps) - CLOSED as NO pool gap, premise falsified (Tier-0 diagnosis; NO ENGINE bump / regen / DS restart / Share sync). DS has no per-archetype pool whitelist - rank.py::_filter_candidates iterates ALL 706 items.json (purchasable + terminal + map-legal + budget + 2-item deny). Of 48 lolmath-favored items, REAL SR pool gaps = 0; every one resolves to a canonical map11 id and ranks just below top-6 live @ ENGINE 1.123.0 (Talon Umbral #7 / Hubris #13 / Profane #33; Lux Liandry's #23; Jhin Collector #12). DS recommends ~60 distinct items / 172 champs - the breadth gap is SCORER VALUATION (item passives needing kill-state, AP DoT burn vs single-rotation ability model, lethality-vs-sustained in burst), NOT pool membership (lethality pen modeled, effects.py:326). Durable probes ops/audit/lolmath_ds_sweep/g5_{pool,live_rank}_probe.py. Re-routed to the G3/G6 Gemini-consult track. | CLOSED | (docs) |
| OVL1 | Electron-Phase4 | Electron Phase 4 interactive tail (headless-safe): add overlay-settings controls (pulse-notification toggle + ACTIVE auto-revert timer) to the ?overlay=1 surface (web/js/panels/overlay_ds_controls.js) and persist them in the rc-shell config (rc-shell/ main-process config.json). Tests in the rc-shell harness + a dashboard fixture render. Live-visual capture OWED (Game-PC MCP :8892 down). | DONE | 4d09f8ac |
| OVL2 | Electron-Phase6 | Electron Phase 6 Pengu Surface C code-only stub: scaffold a pengu/ plugin skeleton that fetches RC_ORIGIN/api/state + renders a panel with tokens.css, and add a client-origin-gated Access-Control-Allow-Origin header in dashboard/_handler.py (non-frozen). No live client needed; live validation OWED. Tests for the CORS-header origin gating. | DONE | aab53e37 |
| DSV1 | DS-Valuation | DS P6-G5 residual 1 (AP DoT/burn valuation): extend the DS damage model (agents/daemon_slayer/dps.py compute_dps + effects.py) to value AP damage-over-time burn (Liandry's / Blackfire Torch) beyond the single-rotation ability model. Root-cause-first, offline characterization tests vs Meraki, ENGINE_VERSION bump + DS restart + Share re-sync. | DONE | 597ffc95 |
| DSV2 | DS-Valuation | DS P6-G5 residual 2 (kill-state item passives): add a takedown/kill-state assumption seam to agents/daemon_slayer/burst.py + dps.py so on-takedown passives (Hubris / Collector / Death's Dance) are valued. Default-OFF byte-identical seam first, offline tests vs Meraki, ENGINE_VERSION bump + DS restart + Share re-sync. | DONE | f1075c38 |
| DSV3 | DS-Valuation | DS P6-G5 residual 3 (lethality vs sustained AD): refine the lethality-vs-sustained tradeoff in agents/daemon_slayer/burst.py so lethality pen out-values raw sustained AD for burst archetypes. Offline characterization tests vs Meraki, ENGINE_VERSION bump + DS restart + Share re-sync. | DONE | 27873cc1 |
| UIX1 | UI-Audit | Champ-Select SR 5-phase fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY per docs/UI_SCALE_SPEC_V2.md) on web/js/panels/champ_select.js + its CSS; Claude_Preview visual validation vs /api/state on :8888 (?ui_mock=1). Fix every MUST-FIX in-slice. Live capture OWED. | DONE | 3c123060 |
| UIX2 | UI-Audit | Home + Settings views 5-phase fixture audit on the Home render (web/js/main.js Home / Tonight-Pick path + builders_home.py surface) and the Settings panel (web/js/panels/dev.js); Claude_Preview visual validation vs /api/state on :8888. Fix every MUST-FIX in-slice. | DONE | 4b1804da |
| UIX3 | UI-Audit | Session / History + detached PGR 5-phase fixture audit on web/js/panels/historical_pgr.js + last_match.js + post_game_phases.js + CSS (the HIST1/HIST2 detached-PGR surface); Claude_Preview visual validation vs /api/state on :8888. Fix every MUST-FIX in-slice. | DONE | 7417a7a8 |
| DSV4 | DS-Valuation | DIRECTOR-REFILL continuation (the A1-UIX3 set drained; operator directive "continue open items headlessly"). The SAME DSV P6-G5 / G2-residual scorer-valuation lane: value Spear of Shojin 3161 Focused Will, a stacking ability/passive damage amp (Meraki 3%/stack x 4 = 12%) that was defensive_only "ability damage not DPS-modeled". Default-OFF assume_ability_amp seam on compute_ability_dps + compute_burst_damage (ability-only, never AA) + rank_items_by_burst; NEW ItemEffect ability_damage_amp_* fields + effects helper + dps._ASSUMED_ABILITY_AMP_STACKS=4. Offline Meraki-anchored tests, ENGINE bump + DS restart + Share re-sync. Ships DEFAULT-OFF (live flip validation-gated, EXCLUDED). | DONE | c5fe019d |

| RN1 | UI-Audit | DIRECTOR-REFILL cycle 43 (A1-UIX3+DSV1-4 drained; operator "continue open items headlessly - multi-agent fanout"). 5-phase fixture audit of the un-audited active-match RIGHT NOW + NEXT coaching panels (right_now.css + next.css). Fix MUST-FIX in-slice. | DONE | ed9c709c |
| DIAG1 | UI-Audit | DIRECTOR-REFILL cycle 43. 5-phase fixture audit of the un-audited Diagnostics developer view (dev.js diag section + header.css .diag-*). Fix MUST-FIX in-slice. | DONE | ed9c709c |
| HZ-T1 | haiku-zero | DIRECTOR-REFILL cycle 43. Hermetic per-mode (sr/aram/arena) fail-soft path-routing coverage for the HZ precompute SOURCE-module tests (load_*(mode) was tested only for sr; aram/arena tables items 386/388 untested on that path). | DONE | 9da9358a |
| LBAND1 | haiku-zero | DIRECTOR-REFILL cycle 45 (bounded queue drained, Gemini down 429; operator "continue open items headlessly - multi-agent fanout"). Section-7b competitor deep-dive (L1) + post-baseline robustness/coverage scout (L2: NOW=0/CLEAN=20). NEW core/live_benchmark_band.py - bands live cs+level vs the player's OWN per-champion percentile (core.benchmarks) at the ~10/~15min checkpoint; the LIVE half of the personal-benchmark data RC only used post-game (aftergame_summary). SR-only, gold excluded (on-hand-vs-total), >=5-games gate. Pure generator, no live consumer yet (wire-in FUTURE, do-not-flip-blind). +10 hermetic tests. | DONE | a8158629 |

## Sessions - OPERATOR REFILL 2026-06-17 (DS permutation swarm + drive ALL open items)

Operator directive: drive ALL open ROADMAP items to completion across many cycles; centerpiece =
the DS permutation swarm (maximize DS logic across self runes + summoner spells + ally team + ally
runes/auras + enemy team + enemy runes), adapt to lolmath at minimum, implement findings to the
smallest benefit. Each DSP row: READ `docs/DS_PERMUTATION_SWARM_PLAN.md` for the full contract +
the seam pattern (default-OFF, Meraki + rewind WIN anchored, ENGINE bump + DS restart + Share sync,
live flip EXCLUDED -> append to `docs/LIVE_GAME_GATED_SYNC.md`). Operator-gated forks -> Gemini PART C,
pick the recommended path, NEVER block. Director picks ONE top-down.

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| DSP1 | ds-swarm | Build the permutation validation harness + WIN anchor under ops/audit/ds_perm_swarm/: score DS top-N vs data/rewind_history.db WIN-rate per (champ x context bucket), consume ops/audit/ds_cross_eval/data/<Champ>.json. BUILD only, no engine change. Hermetic tests. See plan "DSP1". | DONE | 19f66829 |
| DSP2 | ds-engine | Cross-eval Cluster B fix: generic-marksman-template leaking onto non-marksman AD scorers (named systemic bug). Root-cause-first, per-champ tests, ENGINE bump + DS restart + Share sync. See plan "DSP2". | DONE | 6f7a5756 |
| DSP3 | ds-engine | Cross-eval Cluster A fix: archetype-vs-ARAM-win divergence (weights / core/archetype_picks resolution). WIN-anchored. ENGINE bump if math changes. See plan "DSP3". | DONE | 97920f56 |
| DSP4 | ds-engine | Self-rune completion seam: score keystones+minors not yet modeled; extend rune_procs + core/rune_wpa.py. Default-OFF. ENGINE bump + Share sync. See plan "DSP4". | DONE | 1f7dbe62 |
| DSP5 | ds-engine | Summoner-spell seam (NEW agents/daemon_slayer/summoners.py): Ignite antiheal+true, Exhaust incoming-DR, Heal/Barrier EHP, Cleanse/QSS CC-discount, Ghost MS. Default-OFF. See plan "DSP5". | DONE | 790b0236 |
| DSP6 | ds-engine | Enemy-rune threat seam (NEW): enemy Conqueror/PtA/Grasp+SecondWind/antiheal modulate target + EHP presets. Default-OFF. See plan "DSP6". | DONE | f3563120 |
| DSP7 | ds-engine | Ally aura/enchanter seam: extend allyamp.py + _passive_ally_grant_overrides.py to enchanter/shield/heal buckets. Default-OFF. See plan "DSP7". | DONE | 69f9085d |
| DSP8 | ds-engine | Enemy-comp target-preset seam: extend DSV3 assume_squishy_target into tank-heavy/squishy/bruiser/high-CC presets. Default-OFF. See plan "DSP8". | DONE | f03dfc25 |
| DSP9 | ds-lolmath | lolmath parity fold (P6 G3 runes + G7 comp-harness): re-run ops/audit/lolmath_ds_sweep with DSP4-8 seams ON in-harness, close residuals to >= lolmath parity. G6 cost-model = Gemini-consult, not blind build. See plan "DSP9". | DONE | 20d9f395 |
| DSP10 | ds-swarm | Full permutation cross-eval re-run: per-champion worktree swarm over the bucket matrix, all seams harness-ON, WIN-anchored; consolidated mismatch report + per-champ implement-to-smallest-benefit fixes. Loop-until-dry (2 no-new-fix passes). See plan "DSP10". | DONE | `7b96328f` (p1) + `e1c996d0` (p2-DRY) |
| DSP11 | ds-engine | Cluster B2 kit-axis item-crediting fix (Gemini PART C verdict 2026-06-17, from the DSP10 dsp10_consolidated report): the dps/burst scorers give caster-ADC / lethality-assassin / crit-melee kits a generic crit-marksman template instead of their WIN-axis - Pyke wins lethality (Opportunity/Youmuu's), Nilah wins crit (Immortal Shieldbow/IE/Navori), Ezreal wins Manamune/Trinity. Root-cause-first (WHY the template - candidate applicability vs DPS credit model), default-OFF seam, WIN-anchored vs report/dsp10_consolidated.md + rewind. ENGINE bump + DS restart + Share sync. Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM) stays a deferred operator policy decision (do-NOT-auto-flip). See plan "DSP10" + report/dsp10_consolidated.md. | DONE | `0c2b88e5` |
| HZU1 | haiku-zero | HZ uplift (cycle 52 NEXT): item-level build-order Haiku-flip gate - deepen tools/replay_build_order_validate.py to per-item bought-vs-win granularity, mine the 4627 ambiguous rows for which items carry signal. Then prep the laning-agreement read (live-gated -> LIVE_GAME_GATED_SYNC.md). | DONE | `a30cbba4` (code+mine, item 457) + docs this cycle |
| LGS1 | live-sync | Audit ROADMAP open-tails + this plan's EXCLUDED + every default-OFF seam in rank.py; verify docs/LIVE_GAME_GATED_SYNC.md is COMPLETE and each row names its flip location. Pure docs. Keeps the operator's live-game sync list authoritative. | DONE | `ba3d3ea1` |
| OPEN1 | hygiene | Unify the 4 divergent RC page-name templates to a single "RC: " prefix (dashboard/routes_loadout.py:120 + lcu/lcu_client.py:401 [FROZEN - route around or skip] + loadout_resolver.py:351 + agent default; ROADMAP item 210). Tests. | DONE | 5445502e |
| OPEN2 | test-hygiene | tests/test_p2w4_hw2_b.py git() error-path tests call the real loop_controller.git() and pollute the production ops/loop/control/controller.log (monkeypatch subprocess.run but not control_dir). Redirect control_dir to tmp_path in those tests (conftest SHADOW_PATH precedent, item 386). | DONE | b96f17e1 |

## Sessions - OPERATOR REFILL 2026-06-17 ROUND 2 (post-NO_WORK refill; DS cross-eval residual clusters + test hermeticity)

Authored on operator "refill" after the round-1 queue drained to NO_WORK (controller.log
11:37:27). Source = ops/audit/ds_perm_swarm/report/dsp10_consolidated.md (162 anchor-matched
champ-modes; DSP10-DRY + DSP11 closed Cluster B2 caster-ADC/crit, left Cluster A AP-in-ARAM
deferred). These rows target the systematic clusters the report STILL exposes that are
headless-safe: the hybrid/bruiser + enchanter-survivability + tank scorer lanes ranking a generic
template on top and burying WIN-correlated items. SAME contract as the DSP rows: READ
docs/DS_PERMUTATION_SWARM_PLAN.md; root-cause-first (verify-before-redo vs DSP2/DSP11 so this is
not a re-fix); default-OFF seam; Meraki + data/rewind_history.db WIN anchored vs the report;
ENGINE bump + DS :8893 restart + Share sync in the SAME commit; the live default-ON flip is
EXCLUDED -> append to docs/LIVE_GAME_GATED_SYNC.md. EXCLUDE the deferred Cluster A AP-in-ARAM set
(Zilean/Shaco/Kayle/Seraphine - operator policy, do-NOT-auto-flip). A session may record a
"no-change with reasoning" CLEAN if root-cause shows the buried lift is thin-sample / cost-axis
noise (DS audit loop allows it). Director picks ONE top-down.

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| RF1 | ds-engine | Generic-bruiser-template cluster (HIGHEST, largest residual). The hybrid/bruiser scorer ranks a generic AD-DPS template on top (Void Immolation / Blade of The Ruined King / Trinity Force / Heartsteel / Essence Reaver / Runaan's) and BURIES the WIN-correlated survivability/sustain items that win ARAM: Spirit Visage, Jak'Sho The Protean, Sterak's Gage, Death's Dance, Black Cleaver, Force of Nature, Randuin's Omen, Thornmail, Titanic Hydra, Fimbulwinter. Affected (n>=5 buried, ARAM hybrid/bruiser per dsp10_consolidated.md): Darius (Force of Nature 24/75.0 +18.7), Yasuo (Jak'Sho 20/65.0 +23.0), Urgot, JarvanIV, Gnar, Udyr, Tryndamere, RekSai, Briar, MasterYi. Root-cause WHY the bruiser scorer under-weights the survivability axis (analogous to DSP2 generic-marksman + DSP11 generic-crit but a DISTINCT scorer lane - verify-before-redo it is not already covered). Default-OFF WIN-anchored seam vs report/dsp10_consolidated.md + rewind. Per-champ tests. NOT the deferred Cluster A set. | DONE | `faeaeb4a` |
| RF2 | ds-engine | Enchanter-scorer survivability residual. The hps/enchanter scorer tops the generic enchanter template (Echoes of Helia / Ardent Censer / Staff of Flowing Water / Locket / Knight's Vow / Redemption) and buries the HP/tank items that win on enchanters played front-to-back as tank-support - Rakan: Guardian's Horn (11/54.5 +15.2), Warmog's, Fimbulwinter, Heartsteel, Mercury's Treads. Sibling-sweep the other enchanters in the report + grep the archetype scorers for the same template. EXCLUDE Zilean + Seraphine (deferred Cluster A AP-in-ARAM, do-NOT-touch). Root-cause-first, default-OFF WIN-anchored seam, per-champ tests. | DONE | `ee826cdc` |
| RF3 | ds-engine | Tank-scorer itemization-order residual. The ehp/tank scorer ordering diverges from WIN-anchored tank itemization, burying core resist/HP items - Rell: Giant's Belt (9/66.7 +27.1); KSante: Thornmail (14/57.1 +11.5), Negatron Cloak, Plated Steelcaps, Iceborn Gauntlet. Root-cause WHY the resist/HP-vs-mythic-tank ordering diverges from win-rate; default-OFF WIN-anchored seam vs the report; per-champ tests. Verify-before-redo vs the DSP6/DSP8 ENEMY-preset seams (this is the SELF tank-scorer, distinct). | DONE | `869656a0` |
| RF4 | ds-swarm | Residual re-run / loop-until-dry consolidation AFTER RF1-RF3 land. Re-run ops/audit/ds_perm_swarm with the new seams harness-ON, regenerate report/dsp10_consolidated, confirm the RF1-RF3 target clusters lifted (buried winners now ranked, or thin-sample-justified), append any NEW residual cluster to the Findings log. Loop-until-dry (1 no-new-cluster pass). BUILD/AUDIT only unless a clean per-champ fix surfaces. | DONE | `a63c0d47` |
| RF5 | test-hygiene | Hermeticity sibling sweep (insurance, non-DS). OPEN2 found tests/test_p2w4_hw2_b.py wrote the PROD ops/loop/control/controller.log via the real loop_controller.git() except-path. Systematically grep tests/ + agents/daemon_slayer/tests/ for OTHER fixtures that touch a PROD path (ops/runtime/, data/, logs/, ops/loop/control/) instead of tmp_path / a monkeypatched module global; redirect each to tmp (mirror conftest SHADOW_PATH + item-386 precedent). Pure test-hygiene, headless-safe; +regression assert the prod artifact is unchanged across the suite. Record CLEAN if none found. | DONE | `e0f3da12` |
| RF6 | ds-engine | RF4-surfaced residual (report/rf4_residual.md): the RF3 ehp/tank survivability seam is FLOAT-only, but Rell's sole tabled buried winner Fimbulwinter (3121) is NOT in Rell's ehp candidate pool (RF4 verified in_pool=False; a Winter's-Approach mana-line item the EHP _filter_candidates excludes), so the float seam (reorders POOLED items by win-table membership) is a no-op for Rell - RF3's "the EHP scorer ALREADY pools these resist/HP items" premise holds for KSante (3075/6662 pooled+floated) but is FALSE for Rell. Add an ehp-lane INJECT mode mirroring RF2's hps inject (only_ids |= surv_ids BEFORE the float prefix) so tabled-but-not-pooled survivability ids surface. Root-cause-first (confirm WHY Fimbulwinter is filtered for Rell - the mana-item gate); default-OFF WIN-anchored seam vs report/dsp10_consolidated.md + the survivability_item_credit_tank table; per-champ test (Rell Fimbulwinter floats ON, byte-identical OFF). ENGINE bump + DS :8893 restart + Share sync. Live default-ON flip EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. | DONE | `700fa6a8` |

## Sessions - DIRECTOR REFILL 2026-06-18

Authored by the gemini director on REFILL after the round-2 queue (RF1-RF6) drained.
Self-directed work unit: a Section-7b heavyweight competitor deep-dive lift. Output
docs/COMPETITOR_LIFT_2026-06-18.md. A HIGH-lift LOW-risk presentation-only finding
(over EXISTING DS math / existing local data, no new dependency or schema lift, testable)
ships IN-RUN as its own slice (+Section-3b UI proof if frontend); otherwise research +
triage NOW/FUTURE/CLOSED only. Director picks ONE top-down.

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| R1 | lift | Section-7b heavyweight deep-dive competitor lift of one major tool NOT yet reviewed (Aggregator H), 6-point depth checklist (WHAT / HOW / HAVE-grep-RC-cite / WHERE / EFFORT+RISK / LIFT verdict HIGH-MED-LOW). Output docs/COMPETITOR_LIFT_2026-06-18.md (third-party names out of core repo code). ACT: a HIGH-lift LOW-risk presentation finding over EXISTING DS math / existing local data (no new dependency / schema lift, testable) ships IN-RUN as its own slice (+Section-3b UI proof if frontend); a HIGH-lift with a new dependency / schema lift -> BACKLOG (FUTURE); MED/LOW defer. Orchestrator multi-agent for any ship-ready item (disjoint slices, sole merger, verifier-gate). TDD, py_compile, full suite. | DONE | `e9f70e7d` |

## Sessions - DIRECTOR REFILL 2026-06-19

Authored by the gemini director on REFILL after R1 (Aggregator H lift) drained.
Self-directed work unit: a Section-3b 5-phase UI audit of the newly expanded Build
Insights surface + its recent tabs + the GPI drilldown selector. Director picks ONE.

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| R2 | ui-audit | 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of the Build Insights view + recent tabs (web/js/panels/build_insights.js, duration_winrate.js, op_score.js [directive said op_score_curve.js; real file is op_score.js], GPI drilldown player_gpi.js) + their CSS, vs docs/UI_SCALE_SPEC_V2.md. Fix MUST-FIX in-slice. Visual proof via the Playwright snapshot harness (Claude_Preview cannot attach to RC-owned :8888, per R1). | DONE | `9b55615d` |
| R3 | ds-sweep | DIRECTOR REFILL: DS schema lift - passive_damage caster-defensive-stat scaling. Extend the passive_damage registry and to_damage_block to support caster bonus armor and bonus MR scaling (e.g., Taric P +15% bonus armor, Galio P +60% bonus MR). Default-OFF seam, byte-identical when off. Offline characterization tests vs Meraki. ENGINE_VERSION bump + DS :8893 restart + Share sync in the SAME commit. | DONE | `ab23c32c` |
| R4 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of un-audited core coaching panels - web/js/panels/team_context.js, coach_choices.js, item_build.js + their CSS - vs docs/UI_SCALE_SPEC_V2.md. Tokenize sub-floor (<--fs-xs 16px) hardcoded font-sizes; cross-panel .kv/#nx-wave/.minimap-grid blocks in item_build.css are OUT of scope (style already-audited Right Now/Next/Active-Match surfaces). Fix every MUST-FIX in-slice. Visual proof via the Playwright snapshot harness + Claude_Preview attempt (RC-owned :8888 self-signed blocker per R1/R2). | DONE | `9e56d23d` |
| R6 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of un-audited dashboard panels web/js/panels/cooldown_watch.js + cc_conditional_pressure.js + their CSS vs docs/UI_SCALE_SPEC_V2.md. Tokenize sub-floor hardcoded font-sizes. Fix every MUST-FIX in-slice. | DONE | `139ef216` |
| R5 | ds-sweep | DIRECTOR REFILL: DS schema lift - passive_heal missing_hp_heal_amp. Default-OFF `assume_missing_hp_heal_amp` seam on `ability_hps.py compute_ability_hps` + NEW `_MISSING_HP_HEAL_AMP` registry: a registered (champ, spell) heal_per_cast multiplied by `1 + max_bonus * caster_missing_hp_pct` (the heal-AMP multiplier class _passive_heal_overrides.py:27 deliberately excluded from the heal-MAGNITUDE registry). Seeded 4 from champion_abilities.json 16.12.1: Master Yi W / Lissandra R / Sylas W (0%:100% -> 1.0), Briar P (0%:40% -> 0.40); Nidalee E probed, no amp text, NOT seeded. Offline characterization tests vs Meraki ground truth. ENGINE 1.145.0 -> 1.146.0 + DS :8893 restart + Share sync SAME commit. Live flip EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. | DONE | `dc2eb0c3` |
| R7 | ds-sweep | DIRECTOR REFILL: DS schema lift - per-stack self-Attack-Speed passives. NEW `agents/daemon_slayer/_passive_as_overrides.py` registry (PassiveAsEntry: per-stack bonus-AS FRACTION low/high by level + max_stacks + ap_per_stack_per_100) + default-OFF `assume_passive_as_stacks` seam on `dps.py compute_dps` crediting the champ's innate per-stack bonus AS at `_ASSUMED_PASSIVE_AS_STACK_FRACTION`=1.0 (full stacks) into the AA rotation (same 2.5 hard-cap re-clamp as the Yun Tal cond_as path; raw_attack_dps left at the no-conditional baseline). Seeded 4 from champion_abilities.json 16.12.1 effects_descriptions: Irelia Ionian Fervor (10%:25% by lvl/stack, max 4), Jax Relentless Assault (5%:12.5% by lvl/stack, max 8), Ezreal Rising Spell Force (10% flat/stack, max 5), Volibear The Relentless Storm ((5% + 4% per 100 AP)/stack, max 5 - the AP-scaled one, reads resolved post-amp AP). per_stack*max_stacks == documented max (self-clamping). Offline characterization tests (RED-first, 19/19). ENGINE 1.146.0 -> 1.147.0 + DS :8893 restart + Share sync SAME commit. Live flip EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. | DONE | `7c22e3bb` |
| R8 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of the Electron overlay surface (web/css/overlay.css, web/js/panels/overlay_ds_controls.js, web/js/overlay_pulse.js) vs docs/UI_SCALE_SPEC_V2.md. Address the R6 residual: tokenize the 12/13px hardcoded sub-floor sizes in overlay.css (overlay-scoped tokens - global tokens.css keeps its >=16px floor). Fix every MUST-FIX in-slice. | DONE | `4916d8e4` |
| R9 | ds-sweep | DIRECTOR REFILL: DS schema lift - survivability per-instance FLAT damage reduction (flat DR). NEW `agents/daemon_slayer/_passive_flat_mitigation_overrides.py` modeling the per-instance flat-amount DR class the percent `_passive_mitigation_overrides.py` (docstring lines 64-69) deliberately EXCLUDED: Fizz P (flat 4, ANY, +1% AP omitted), Amumu E (per-rank [5,7,9,11,13], PHYS), Leona W (per-rank [8,12,16,20,24], ANY, active prob 0.3); all cap_frac 0.5. Default-OFF `assume_passive_flat_mitigation` seam on compute_ehp + rank_items_by_ehp folds prevented damage (`_ASSUMED_FLAT_DR_INSTANCES`=6 x flat x prob) into the EHP NUMERATOR (mirrors ext_flat_hp); byte-identical when OFF; `_ASSUMED_ABILITY_RANK`=4 reads the per-rank seeds. Offline characterization tests vs champion_abilities.json 16.12.1. ENGINE 1.147.0 -> 1.148.0 + DS :8893 restart + Share sync SAME commit. Live flip EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. | DONE | `d52c984e` |
| R10 | lift | DIRECTOR REFILL: Section-7b heavyweight deep-dive competitor lift of Aggregator B. Output docs/COMPETITOR_LIFT_2026-06-21.md. Act on HIGH-lift LOW-risk presentation finding IN-RUN. | DONE | `edd76db3` |
| R12 | ds-sweep | DIRECTOR REFILL: DS schema lift - cross-spell all-source TARGET-VULNERABILITY mark. NEW agents/daemon_slayer/_target_vulnerability_overrides.py (TargetVulnEntry + _CHAMPION_VULN_OVERRIDES champion_id->ability + _ITEM_VULN_OVERRIDES item-id->item + target_vuln_multiplier) modeling a debuff the wielder lays on the TARGET that makes it take +X% damage FROM ALL SOURCES (the all-source half the per-spell self-amp _ability_amp_overrides cannot express). Default-OFF apply_target_vuln seam on dps.compute_dps (weighted_dps + phase_dps scaled by the composed mark multiplier, multiplicative per source, de-duped per item; byte-identical OFF). SEEDED 2 ACTIVE vs 16.12.1 ground truth: Vladimir R Hemoplague 10% (DDragon Vladimir.json effect[2]=[10,10,10]) + Evenshroud 3001/Arena 223001 Coruscation 7% (items.json). NON-FIT (documented in _NONFIT_VULN_CANDIDATES, NOT seeded): Imperial Mandate 4005 - director suggested 6% but 16.12.1 Coordinated Fire is a current-HP mark-detonation, not a +X% all-source amp (no ground-truth value for a flat amp -> honestly excluded, a wrong precompute is worse than none). Offline characterization tests (23, RED-first). Verifier-gated CONFIRM. ENGINE 1.148.0 -> 1.149.0 + DS :8893 restart + Share sync SAME commit. Live flip + ability_dps/burst consumer broadening EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. | DONE | `cad49029` |
| R13 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of the un-audited Active Match threat + CD panels (web/js/panels/cd_ledger.js, cc_blended_ehp_threat.js, threat_donut.js) + their CSS vs docs/UI_SCALE_SPEC_V2.md. Tokenize sub-floor hardcoded font-sizes. Fix every MUST-FIX in-slice. Visual proof via the Playwright snapshot harness. | DONE | `0fb91841` |
| R14 | ds-sweep | DIRECTOR REFILL: DS schema lift - cc_conditional durations_floor_s (guaranteed-minimum CC floor band for distance/channel-scaled CC). NEW optional ConditionalCcEntry.durations_floor_s field (None default; loader .get backward-compat) + default-OFF apply_cc_floor seam on cc_pressure.compute_cc_pressure crediting floor + prob*(max-floor) instead of max*prob when ON (byte-identical OFF; standalone + coexistence MAX-rule paths both floor-aware). Seeded 5 vs 16.12.1 Meraki minimums: Maokai R 0.75 / KSante W 0.5 / Sion R 0.25 / Hecarim R 0.75 (4 existing entries) + NEW Ashe R 1.0 entry (coexists_with_unconditional=True, range_gated, durations_s 3.5, mirrors Maokai/Hecarim R; Ashe R also in unconditional _PER_SPELL_CC_DURATIONS 1.5). Offline characterization tests (RED-first). Verifier-gated. ENGINE 1.149.0 -> 1.150.0 + DS :8893 restart + Share sync SAME commit. Live default-ON flip + ehp/hybrid propagation EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. | DONE | `66abc012` |

## Sessions - DIRECTOR REFILL 2026-06-22

Authored by the gemini director on REFILL after R14 drained. Self-directed work
unit: a Section-7b heavyweight competitor deep-dive lift of Aggregator A (first review of
that tool; prior lifts covered Aggregator P / draft tool L / target-vs-opponent /
simulator tool R / Aggregator H / Aggregator B). Output docs/COMPETITOR_LIFT_2026-06-22.md
(third-party names out of core repo code). A HIGH-lift LOW-risk presentation-only
finding over EXISTING DS math / existing local data (no new dependency or schema
lift, testable) ships IN-RUN as its own slice (+Section-3b UI proof if frontend);
a new dependency / schema lift -> BACKLOG (FUTURE); MED/LOW defer.

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| R15 | lift | Section-7b heavyweight deep-dive competitor lift of Aggregator A, 6-point depth checklist (WHAT / HOW / HAVE-grep-RC-cite / WHERE / EFFORT+RISK / LIFT verdict HIGH-MED-LOW). Output docs/COMPETITOR_LIFT_2026-06-22.md. ACT: a HIGH-lift LOW-risk presentation finding over EXISTING DS math / existing local data (no new dependency / schema lift, testable) ships IN-RUN as its own slice (+Section-3b UI proof if frontend); HIGH-lift with new dependency / schema lift -> BACKLOG (FUTURE); MED/LOW defer. Orchestrator multi-agent for any ship-ready item (disjoint slices, sole merger, verifier-gate). TDD, py_compile, full suite. | DONE | `b49ef1a7` |
| R16 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of the un-audited Game Flow + Spike Curve panels (web/js/panels/perf_curve.js, spike_curve.js, spike_markers.js) + their CSS vs docs/UI_SCALE_SPEC_V2.md. Fix MUST-FIX in-slice. Visual proof via the Playwright snapshot harness + Claude_Preview visual vs /api/state. | DONE | `7ecb5b18` |
| R17 | ds-sweep | DIRECTOR REFILL: DS schema lift - antitank ramp_lo/ramp_hi level-ramp %HP. Extend the antitank registry to support ramp_lo and ramp_hi endpoints for champion abilities dealing percentage max HP damage scaling with level (e.g., Aatrox 4%:8%, Brand 8%:12%, Skarner 5%:9%). Generalizes to ~16 rows. Default-OFF seam, byte-identical when off. Offline characterization tests vs Meraki. ENGINE_VERSION bump + DS :8893 restart + Share sync in the SAME commit. Live flip EXCLUDED. | DONE | `5f308036` |
| R18 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) of un-audited panels build_order.js, augment_reco.js, archetype_nudge_chip.js, and map_state.js + their CSS vs docs/UI_SCALE_SPEC_V2.md. Tokenize sub-floor hardcoded font-sizes. Fix every MUST-FIX in-slice. | DONE | `0999d3eb` |
| R19 | ds-sweep | DIRECTOR REFILL: DS schema lift - survivability spell_damage_reduction_pct. NEW forward-marker accessor DataSnapshot.spell_damage_reduction_pct(champ_id, slot) in agents/daemon_slayer/data_loader.py - per-rank PERCENT damage reduction from champion_abilities.json defensive modifier blocks (pure-% units filter) as a first-class magnitude; lazy + frozen-safe; 8 champs at 16.12.1. Default-OFF, byte-identical (no consumer). Offline characterization tests vs Meraki. ENGINE_VERSION HELD at 1.151.0 (NOT bumped - gemini director ruling B: byte-identical forward-marker per the item 339/343 no-bump convention) + DS :8893 restart + Share sync. Live flip EXCLUDED. | DONE | `ee673c1d` |
| R20 | lift | DIRECTOR REFILL: Section-7b heavyweight deep-dive competitor lift of Aggregator N, 6-point depth checklist (WHAT / HOW / HAVE-grep-RC-cite / WHERE / EFFORT+RISK / LIFT verdict HIGH-MED-LOW). Output docs/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md (third-party names out of core repo code). ACT: a HIGH-lift LOW-risk presentation finding over EXISTING DS math / existing local data (no new dependency / schema lift, testable) ships IN-RUN as its own slice (+Section-3b UI proof if frontend); HIGH-lift with new dependency / schema lift -> BACKLOG (FUTURE); MED/LOW defer. Orchestrator multi-agent for any ship-ready item (disjoint slices, sole merger, verifier-gate). TDD, py_compile, full suite. Closed-negative respected: Aggregator N Arena augment WINRATE is Riot-policy-forbidden (BACKLOG line 122; pick-rate only). SHIPPED F1: ARAM per-champion balance-adjustment grid panel (the 7-field aramDamageDealt/Taken/Healing/Shielding/Tenacity/AbilityHaste/AttackSpeed grid RC loads but never displayed) - new /api/aram-balance route + web/js/panels/aram_balance.js, presentation-only over existing local champions.json, no engine bump. Lift doc docs/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md (F1-F7). | DONE | `e0f0ffac` |
| R21 | ui-audit | DIRECTOR REFILL: 5-phase fixture audit (STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY) + populated capture of the R20-shipped ARAM balance grid panel (web/js/panels/aram_balance.js), clearing its VISUAL OWED. VERIFY-THE-PREMISE found the root cause: renderAramBalance was wired into the live-state render branch ONLY, never the ui_mock active-match branch, so the documented ?ui_mock=1&mode=aram#active-match audit path could not drive it. Fix wires it into the ui_mock branch (mirrors the sibling panels). Audit CLEAN; applied its one SHOULD-FIX (.ab-chip off-grid 2px -> --space-1 4px). RED-first test_aram_balance_view.py (wiring guard + Playwright populated capture). Tier-1 frontend, no engine/Share/ENGINE_VERSION. | DONE | `bd961b39` |

## Sessions - DIRECTOR REFILL 2026-06-25

Authored by the gemini director on REFILL (loop restart, head cf2ea80c). The
director re-proposed the LEDGER-618 housekeeping TAIL, but a verify-the-premise
pass (CLAUDE.md verify-before-declare-broken) found ALL of it already shipped
EARLIER THE SAME DAY (items 618/619/620). This is a stale-LEDGER read by the
director (loop idle 06-22 -> 06-25; items 618-624 landed in that gap), NOT open
work. Recorded CLEAN no-op + escalated via PART C so the next directive picks
genuinely-open ROADMAP/BACKLOG work.

| ID | Theme | Scope | Status | Commit |
|----|-------|-------|--------|--------|
| R28 | housekeeping | DIRECTOR REFILL: re-proposed ledger-618 tail (SwapsInto extractor fix + snapshot_panels flake + ARCHITECTURE.md:172 drift). VERIFY-THE-PREMISE -> ALL already shipped: SLICE 1 = item 619 (`95972f57`, Riot 16.13 `...ImmobilizingCCAbility` taxonomy fix - extractor canonicalizes the suffix to the legacy stem, 16.13.1 cdragon carries 5 SwapsInto correct, spell_cc_tags 31/31 green; inert-data so NO ENGINE bump per the 339/343 convention - the directive's "MUST bump ENGINE_VERSION" was itself wrong); SLICE 2a snapshot flake = item 620 (`0fe7e3bf`, Windows-scoped keep-alive, CI green - 620 ground-truth-corrected the directive's "keep HTTP/1.1 keep-alive" premise: the keep-alive ITSELF is the Linux culprit); SLICE 2b doc-drift = FALSE premise (line 172 already reads ENGINE 1.151.0 / 7511 tests / patch 16.13.1, NOT the hallucinated 1.144.0/7361). No code change warranted - a redundant ENGINE re-bump or flake re-attempt would REGRESS shipped work. CLEAN no-op, evidence-logged. | CLEAN | (docs) |
| R32 | haiku-zero | LOOP cycle 3 (DIRECTOR REFILL): Lane A precompute-vs-Haiku agreement RE-MEASUREMENT via `tools/hz_shadow_report.py` on the item-614 corrected laning tables. Offline measurement only, ENGINE-IMPACT NONE (no math/network/write). Bucketed the 24,289 choice shadow records pre/post the item-614 fix boundary (commit `7383e712`, 2026-06-25T00:45:07 UTC), reusing the tool's own `record_agreement`/`classify_verdict` (whole-log result reconciles exactly to the live tool aggregate 1733/3717 0.4662). FINDING: the targeted `back_off->trade` model-error pocket is ELIMINATED (138 pre -> 0 post); post-fix aggregate dip (0.4863 -> 0.2468) is a 2-game small-sample artifact (Renekton-vs-Gragas 235/235 disagree + Nasus-vs-Gragas 77/77 agree), NOT a fix regression; a NEW pocket surfaced (`all_in->hold`, all Renekton-vs-Gragas) logged FUTURE for the next HZ_MISMATCH_DIAGNOSE. Flip readiness STILL NOT MET - do-not-flip-blind operator gate HOLDS, live coach NOT flipped. Findings doc `ops/audit/HZ_REMEASUREMENT_2026-06-27.md`. Docs+audit only (no code change -> no TDD target per the CSS-only-audit precedent item 435; full suite stays green, zero delta). | DONE | `760ff386` |

## EXCLUDED (live-game / operator-gated; the director MUST NOT pick these)

- DS Phase-D default-ON flag flips (apply_passive_damage, non-every-AA on_hit, per-stack assumed_stacks) - need real-game re-ranking validation.
- Live caster-stat producer for /anti-tank P3.2 activation + live survivability scorer (egg-resist / Orianna E) - need a live AbilitiesSnapshot / game.
- Champ-select brief Haiku -> deterministic flip - needs live shadow-log accrual + operator OK.
- Game-PC :8892 visual screenshot captures (MCP down post-1PC). C-phase visual validation uses the Claude_Preview MCP against :8888 instead.
- Anything in the CLAUDE.md "Settled - do not re-litigate" set.
- Haiku-to-ZERO LIVE coach flips: removing/replacing a live Haiku call with the HZ-* precompute tables. Per charter 4b "do not flip blind" - needs real/replayed-game validation + operator OK. The HZ-* sessions BUILD + PERSIST + SHADOW-LOG only; Haiku stays the interim floor until validated.
- DSP/DSV default-OFF seam live default-ON flips in rank.py/burst.py + every row in docs/LIVE_GAME_GATED_SYNC.md - need a real game. The DSP* sessions ship the seam DEFAULT-OFF + offline-validate it; the executor APPENDS each new seam's live flip to docs/LIVE_GAME_GATED_SYNC.md and NEVER flips blind.

## Findings log (executor appends; newest first)

- 2026-06-27 R32 (LOOP cycle 3, DIRECTOR REFILL, head 34f58257) DONE (docs+audit
  only, offline measurement, ENGINE-IMPACT NONE). Lane A precompute-vs-Haiku
  agreement re-measurement on the item-614 corrected laning tables via
  `tools/hz_shadow_report.py`. Bucketed 24,289 choice shadow records at the
  item-614 fix boundary (commit `7383e712`, 2026-06-25T00:45:07 UTC), reusing the
  tool's own classifiers (whole-log reconciles exactly to the live aggregate
  1733/3717 = 0.4662). HEADLINE: the targeted `back_off->trade` model-error pocket
  is ELIMINATED - 138 pre-fix -> 0 post-fix (all 138 are <= 06-18..06-20 records;
  none recurred in post-fix games). The post-fix aggregate dip (0.4863 -> 0.2468)
  is NOT a fix regression: the entire post-fix comparable-covered sample is TWO
  games from one day (Renekton-vs-Gragas 235 ticks all_in->hold 0 agree +
  Nasus-vs-Gragas 77 ticks all agree), so 77/312 is mechanically "one game agreed,
  one disagreed"; the fix only touches `no_ult` cells and cannot have caused the
  Renekton all_in lean. A NEW pocket surfaced - `all_in->hold` driven entirely by
  Renekton-vs-Gragas - logged FUTURE for the next HZ_MISMATCH_DIAGNOSE (single
  matchup, too thin to act on). Build axis unmeasurable post-fix (0 covered+native
  build records in the 2 games). Flip readiness STILL NOT MET (~47% aggregate,
  post window dominated by one un-diagnosed pocket) - do-not-flip-blind operator
  gate HOLDS, live coach NOT flipped (directive-mandated). Findings doc
  `ops/audit/HZ_REMEASUREMENT_2026-06-27.md`. No code touched -> no TDD target (the
  CSS-only-audit precedent item 435); full suite stays green, zero delta; no ENGINE
  bump (stays 1.152.0); no DS/Share change. regressions=0.
- 2026-06-27 R31 (LOOP cycle 2, FIX-FIRST directive, head 34f58257) CLEAN no-op
  (docs-only) - FALSE-POSITIVE REGRESS verdict. The cycle-1 auditor flagged the
  DSV6 assume_magic_burst seam (burst.py / ability_dps.py / effects.py) as shipped
  with "No tests added" and demanded tests for the assume_magic_burst=True path. A
  verify-the-premise pass (CLAUDE.md verify-before-declare-broken /
  audit-proposals-are-intent) found the premise FALSE: the test file
  agents/daemon_slayer/tests/test_magic_burst_valuation_dsv6.py was committed in the
  SAME commit as the seam (42f0111c, not a later one) and already covers ALL THREE
  demanded targets - effects.total_magic_burst_damage (MagicBurstHelper, 4 tests),
  compute_burst_damage(assume_magic_burst=True) (ComputeBurstSeam, 3 tests incl MR
  routing + no-field byte-identical), and compute_ability_dps(assume_magic_burst=True)
  (ComputeAbilityDpsInertSeam, the documented-inert ON==OFF==base proof), plus schema
  defaults / Meraki-pin / periodic-bonus drift guard / ENGINE_VERSION pin. The 13
  tests pass and the full DS suite is 7524 passed / 1 skipped / 1943 subtests green.
  The auditor diffed a stale digest that did not see the test file. No new tests
  fabricated (redundant duplicate coverage is churn, not value); no engine math
  touched; no ENGINE bump (stays 1.152.0). regressions=0 reported to done_sentinel.
- 2026-06-27 R30 (DIRECTOR REFILL cycle, head a24e7e39) dsv6-magic-burst DONE ->
  NAMING DEVIATION (audit-proposals-are-intent): the directive theme was
  "dsv5-magic-burst", but a ground-truth grep found DSV5 already taken (the
  comp_hp_lean AP-DoT-vs-burst EHP-gating arc, test_comp_hp_lean_dsv5.py); DSV1-5
  are all in use, so this work ships as DSV6 (next free arc label) to keep the
  arc labels unambiguous. The burst scorer (compute_burst_damage) under-valued AP
  on-cast magic procs because the per-cast combo loop sums only ability casts +
  AA hits, never the item on-cast magic burst (Luden's Echo 75+5%AP/6655,
  Stormsurge Squall 125+10%AP/4646, Malignance Hatefog 180+15%AP/3118).
  PREMISE-CHECK vs ground truth: all 3 ARE already modeled as PeriodicProcs so
  compute_dps values them at their periodic RATE (ability_dot_only=False), while
  compute_ability_dps (ability_dot_only=True) and compute_burst_damage do NOT -
  so both the ability-DPS and burst scorers under-credit AP burst builds. DSV6
  seam: 2 new ItemEffect fields (magic_burst_base / magic_burst_ap_ratio, the
  one-shot burst-window magnitude) appended at END + effects.total_magic_burst_damage
  helper + assume_magic_burst=False param on BOTH consumers. compute_burst_damage
  folds the MR-mitigated + mode + magic-amp magic burst into total_burst (the
  real fix - a one-shot magnitude belongs in a burst window). compute_ability_dps
  takes the param for API symmetry but is a DOCUMENTED-INERT seam (byte-identical
  ON or OFF): a one-shot magnitude has no dimensionally-sound place in a
  per-second metric, and these procs are already sustained-valued in compute_dps,
  so folding them here would be both wrong-units and a partial double-count.
  DEFAULT-OFF -> every existing item + caller byte-identical. ENGINE_VERSION bump + DS :8893 restart
  + Share sync in the same commit. Orchestration: single ~30-line tightly
  coupled (schema-first) seam implemented inline by the sole merger on the
  ground-truth-verified spec; mandatory read-only verifier gate before commit
  (worktree fanout reserved for large disjoint workloads, not a 30-line seam).
- 2026-06-27 R29 (DIRECTOR REFILL cycle, head 32a14490) SUPERSEDED - the L4
  capability-gap TAIL (zone_control via ZoneControlResult.controls_terrain boolean
  min 2; objective_damage via ObjDamageResult.objdamage_score >= 0.5 min 2 - score
  not boolean because pressures_structures is True for nearly every champ; + the
  active-match chip twin reusing /api/ds-preview) was scoped + thresholds grounded
  live 2026-06-27, ready to dispatch as 2 disjoint worktree slices - but an OPERATOR
  INTERRUPT redirected this session to live in-game overlay fixes (Ctrl+Shift+A
  ACTIVE rebind, keepCompanion default OFF = overlay-only in-game, console-flash
  suppression), the wenyan output-dialect default (caveman + gemini director/auditor
  + revived tools/caveman_default.py hook), and a loop-improvement deep-research
  report (docs/LOOP_IMPROVEMENTS_2026-06-27.md, NOW 12 / FUTURE 8 / CLOSED 16). The
  gemini loop was STOP'd (operator took manual control). The capability-gap tail
  remains OPEN for a future cycle (grounded thresholds + fixtures in this transcript).
  UPDATE (same-day autonomous continuation, operator-delegated "continue prior
  requests; use Gemini for answers"): the capability-gap tail was COMPLETED as ledger
  item 634 - slice 1 `992dd455` (zone_control + objective_damage detectors, 28 pytest)
  + slice 2 `eda8870d` (active-match chip twin, 6 node tests) + reconcile `4ea6de03`,
  2 disjoint worktree slices merged + verifier-gated, broader capgap sweep 88 passed
  (0 real failures; lone teardown error = the live in-game vision daemon, not code).
  No ENGINE bump. Only live SR validation with RC_CAPGAP_SURFACE=1 still owed.
- 2026-06-25 R28 (DIRECTOR REFILL cycle, loop restart head cf2ea80c) CLEAN no-op
  (docs-only) - the director re-proposed the ledger-618 housekeeping TAIL, but a
  verify-the-premise pass (CLAUDE.md verify-before-declare-broken /
  audit-proposals-are-intent) found ALL THREE pieces already shipped EARLIER THE
  SAME DAY. SLICE 1 (SwapsInto extractor) = item 619 (`95972f57`): root cause was a
  Riot 16.13 TAXONOMY change (added `...ImmobilizingCCAbility` twin beside legacy
  `...ImmobilizingCCSpell`, 7 of 12 swap spells reclassified to direct-immob); the
  extractor canonicalizes the suffix back to the legacy stem, so 16.13.1
  cdragon_spell_stats carries 5 SwapsInto (correct - Aphelios Q / Gnar W / Leblanc R
  / RekSai W / Rengar E) + the 7 direct as the umbrella stem; spell_cc_tags 31/31
  green; inert-data so NO ENGINE bump (339/343), which makes the directive's "MUST
  bump ENGINE_VERSION" itself wrong. SLICE 2a (snapshot flake) = item 620
  (`0fe7e3bf`): 620 GROUND-TRUTH-CORRECTED the directive's "keep HTTP/1.1 keep-alive"
  instruction - the keep-alive ITSELF is the Linux CI break (404 on the gitignored
  ddragon mirror -> BrokenPipe wedges the persistent pool), so the fix is
  Windows-platform-scoped, not "keep keep-alive". SLICE 2b (ARCHITECTURE.md:172
  doc-drift) = FALSE premise: line 172 already reads ENGINE 1.151.0 / 7511 tests /
  patch 16.13.1 (real collected DS ~7512, grep-method noise); the claimed "stale
  1.144.0/7361 vs live 1.151.0/7497" is a director hallucination, not on disk.
  Redoing any slice would be HARMFUL. Recorded CLEAN; escalated to the director
  (PART C gemini_ask.txt) to pick genuinely-open work next cycle. ROOT CAUSE of the
  stale directive: loop idle 06-22 -> 06-25; items 618-624 landed in the gap; the
  director keyed off LEDGER 618's "housekeeping tail" phrasing without reading items
  619/620 directly above it.
- 2026-06-23 R27 (DIRECTOR REFILL cycle, operator-driven) DONE (`29c48b21` ->
  rebased `bf2ff10d`; ledger 600) - the R26 follow-on broader SHIPPED-PANEL
  render-gate audit. 3 parallel read-only agents swept all ~56 dashboard+overlay
  panel renderers for 4 failure modes ([hidden]-attr-vs-style.display /
  positional-vs-id index / stale gate accessor / unwired renderer). NEGATIVE
  result: the ds_statcheck dead-panel bug is ISOLATED - no other panel is dead
  (the lone [hidden]+style.display overlap #am-spike-markers renders fine,
  spike_markers.js:147 sets .hidden=false). DO NOT re-run this sweep. The trace
  DID surface a real systemic idempotency edge: the 3 ctx-driven active-match
  panels (spike_markers/spike_curve/draft_elo) dedup by content sig while the
  outer active_match.js hide paths clobber mount.innerHTML="" behind them, so a
  re-show with identical data after a transient liveclient dropout left a
  visible-but-empty panel; fix = dedup guard also requires innerHTML!=="".
  RED-first tests/snapshot_panels/test_render_dedup_reshow.py 4/4. Tier-1
  frontend (no engine/Share/ENGINE_VERSION). Carry-forward OWED (both need a
  live game / operator action): E.1 ACTIVE knob (operator-physical), RC_COMP_HP_LEAN
  flip (operator-gated).
- 2026-06-22 R21 (DIRECTOR REFILL cycle) DONE (`bd961b39`) - Section-3b 5-phase
  fixture audit + populated capture of the R20 ARAM balance-grid panel, clearing the
  VISUAL OWED. VERIFY-THE-PREMISE payoff: renderAramBalance was dispatched in the
  live-state render branch ONLY (web/js/main.js ~L1431); the ui_mock active-match
  branch (L1392-1411) wired every sibling panel (ward/spike/minimap/objective chips)
  but NOT this one, so the documented ?ui_mock=1&mode=aram#active-match audit path
  could not render it - the structural reason the populated capture was OWED.
  Root-cause fix: dispatch it in the ui_mock branch too (mode + roster from the mock
  fixture; the panel self-gates on ARAM). 5-phase audit CLEAN; applied its one
  SHOULD-FIX (.ab-chip off-grid 2px vertical pad -> --space-1 4px, UI_SCALE_SPEC_V2
  8px-grid). RED-first tests/snapshot_panels/test_aram_balance_view.py: static wiring
  guard (renderAramBalance in both branches) + Playwright populated capture over the
  active_match_aram.json roster (Senna self + 4 ally + 5 enemy; stubs /api/aram-balance)
  asserting the self gold row + ally/enemy rows + buff/nerf chips, writing
  screenshots/aram-balance_aram.png. Tier-1 frontend (asset-hash hot-reload; no
  engine/DS/Share/ENGINE_VERSION). 204 snapshot+contract tests green; active-match 8/8.
- 2026-06-22 R20 (DIRECTOR REFILL cycle) DONE (`e0f0ffac`) - Section-7b competitor
  deep-dive lift of Aggregator N (docs/COMPETITOR_LIFT_2026-06-22_AGGREGATOR_N.md, F1-F7). F1
  SHIPPED IN-RUN: ARAM per-champion balance-adjustment grid panel. RC loads Riot's
  full 7-field ARAM modifier grid into champions.json but consumed only dealt+taken
  as a coach-prompt line - no web panel rendered it. New balance_grid_for /
  balance_grid_map accessors (core/aram_balance_context.py, existing prompt symbols
  byte-identical) + GET /api/aram-balance (dashboard/routes_aram_balance.py, 134
  non-neutral champs) + mode-gated web/js/panels/aram_balance.js grid (self from
  coach.champion; ally/enemy from liveclient.allPlayers; signed green/red deltas; AH
  additive). Presentation-only over existing local data, no dependency / schema lift
  / ENGINE bump. RED-first tests/test_aram_balance_grid.py (13). 1 worktree build
  agent + verifier CONFIRM. VISUAL OWED (mode-gated panel; headless cycle cannot
  drive ui_mock). F2 per-slot item win-rate ladder over rewind_history.db = the only
  non-trivial FUTURE candidate (MED-HIGH, weak solo sample) -> BACKLOG. F3/F5
  already-have, F4 forbidden external winrate source, F7 new TFT domain - all defer.
- 2026-06-22 R19 (DIRECTOR REFILL cycle) DONE (`ee673c1d`) - DS schema lift: NEW
  forward-marker accessor DataSnapshot.spell_damage_reduction_pct(champ_id, slot)
  surfacing the per-rank PERCENT damage-reduction magnitude from
  champion_abilities.json defensive modifier blocks (the modifier_blocks taxonomy
  already classified them defensive_self but no accessor exposed the numeric %).
  Lazy + frozen-safe (object.__setattr__ cache), parses the same snapshot via
  AbilitiesSnapshot. Pure-% filter (units all == "%") excludes flat reductions
  (Amumu E empty-units, Leona W "Flat Damage Reduction") + per-stat scaling
  sub-modifiers ("% per 100 AP"). 8 champs at 16.12.1: Alistar R 55/65/75, Galio
  W magic 25..45 + physical 12.5..22.5, Garen W 25..41, Gragas W 10..18, MasterYi
  W 45..55, Belveth/Braum/Warwick E 35..55.
  KEY DECISION (gemini director ruling B, synchronous gemini_ask). The directive
  said "ENGINE_VERSION bump" but ALSO "Default-OFF, byte-identical when
  unconsumed. Live flip EXCLUDED" - internally inconsistent. With no consumer the
  engine output is byte-identical, and the established item-339/343 forward-marker
  convention (spell_sub_missile_speed / spell_cc_tags) EXPLICITLY does NOT bump;
  ~70 version-contract tests pin 1.151.0. Director picked B: HOLD 1.151.0, no pin
  churn. Share mirror still re-synced (data_loader.py edit drifts Share/src) + DS
  :8893 restarted (loads the new code, /health stays 1.151.0).
  TDD RED-first test_spell_damage_reduction_pct.py (14 cases: 8 champ maps + Galio
  dual-label + Amumu/Leona/Ashe/unknown None negatives + 0<pct<=100 float-tuple
  invariant + ASCII). 1 worktree build agent on the disjoint data_loader + test
  slice; orchestrator independently re-ran the new test + the full DS suite in main
  before commit; ruff clean. DS suite 7511 passed / 1 skip / 1943 subtests; RC
  suite 9378 passed (the 12 fails ALL pre-existing - 3 CoachWire ARAM-template + 7
  ds_pick_consumption_p1l11 ARAM subfails + overlay.css sub-floor + spell_autopush
  on the dirty data/spell_prefs.json - 0 R19 regressions). ds_share_sync --check
  green (373 files). A survivability/EHP consumer reading the % (folding it into
  the EHP numerator like the flat-DR R9 path) is the FUTURE lift, not wired blind.

- 2026-06-22 R18 (DIRECTOR REFILL cycle) DONE (`0999d3eb`) - Section-3b 5-phase fixture
  audit of the 4 un-audited panels build_order / augment_reco / archetype_nudge_chip /
  map_state vs docs/UI_SCALE_SPEC_V2.md (v2.1 16px --fs-xs floor). GROUND-TRUTH DEVIATION
  from the directive's "4 disjoint CSS files" premise: archetype_nudge_chip.js has NO
  dedicated CSS - its styles live in map_state.css (251-284, shared with the map_state
  slice) + a view-scoped hide rule in header.css; and map_state.css is a shared grab-bag
  (header pills / panel chrome / STATS / GAME SENSE / WHAT-WENT). So the slices are NOT
  file-disjoint and parallel worktrees would collide - executed inline as orchestrator
  (directive "a trivial item may use a single agent"); per UI_SCALE_SPEC_V2 "each page
  audit sweeps its own panels only", swept the cleanly panel-owned files, NOT the grab-bag.
  Result = 16 sub-floor MUST-FIX tokenizations, 2 panels otherwise compliant:
  * build_order.css: 8 .bo-* literals (12-14px) -> var(--fs-xs); .bo-name/.bo-delta kept
    15px as DOCUMENTED operator-exceptions (dense bo-slot chip primary content; the operator
    explicitly tuned "15px readable floor", below the 16px token floor by design - inline
    rationale added so a maintainer cannot bump blind). .bo-pushbtn already var(--hit-min).
  * augment_reco.css: 8 .ar-* literals (12-15px) -> var(--fs-xs); .ar-top-name 23px headline
    above-floor, left as-is.
  * archetype_nudge_chip (in map_state.css): audited CLEAN - already floor-clear (17px chip /
    19px X). The X dismiss button is a density-constrained header-inline control (42px hit
    target would break the header row) - documented exception, NOT forced (logged FUTURE: a
    ::before hover-pad inflation that holds header height).
  * map_state.js: 2 minimap canvas labels (11px D/B/H, 13px YOU) are 2D-canvas spatial
    annotations that cannot consume a CSS --fs-* token - inline operator-exception rationale
    added (sized to fit dot glyphs; the 16px floor overflows the marker).
  TDD: tests/test_r18_panels_typography_v21_floor.py (RED-first, mirrors the R4 guard), 9
  cases green; 91 panel DOM + token-parity guards green; ruff clean. Asset-hash auto-reload
  (ADR-008), no RC restart. Full RC suite 9378 passed / 2 skip / 103 subtests; the 12 fails
  are ALL PRE-EXISTING + unrelated (3x CoachWire ARAM-template + 7 ds_pick_consumption ARAM-
  template subtests, overlay.css sub-floor [scans overlay.css only], spell_autopush on the
  dirty data/spell_prefs.json runtime drift) - NONE reference the R18 files. VISUAL CAPTURE
  OWED: Claude_Preview cannot attach to the RC-owned self-signed :8888 (port held by live
  pythonw; freeing it kills the runtime) + the panels are in-game/champ-select-only and do
  not render populated without a live game -> code-side audit + test harness are the in-slice
  proof; live populated-state capture carried to WAKEUP_NOTES.

- 2026-06-22 R17 (DIRECTOR REFILL cycle) DONE (`5f308036`) - DS schema lift: antitank
  level-ramp %max-HP endpoints. AntiTankEntry gains optional ramp_lo/ramp_hi (END-appended,
  default 0.0); compute_antitank gains optional level. The hand-tuned magnitude encodes
  late-game (max-ramp) reliability; a ramp-seeded row scales by
  lerp(ramp_lo,ramp_hi,(level-1)/17)/ramp_hi when a level is injected. DEFAULT-OFF / byte
  -identical: level=None (the /anti-tank route default) AND level=18 are exactly item-308/315;
  every un-ramped row is byte-identical at any level (mirrors the P3.2 ap/ad seam). Seeded 10
  verified MAX_HP champion-level ramps from the patch-16.12.1 registry source_quotes (Aatrox 4:8,
  Brand 8:12, KSante 1:2, Mordekaiser 1:5, Ornn 10:18, Renata 1:2, Skarner 5:9, Urgot 2:6,
  Zed 6:10, Zeri 1:11). DEVIATION FROM DIRECTIVE: the director estimated "~16 rows" but ground
  truth is 10 - the rest of the %HP roster is rank-scaled (per-ability-rank) or flat, NOT
  champion-level ramps; Senna P (CURRENT_HP 1:10) is a real level ramp but the directive scope
  was %max-HP, logged as a deferred sibling. A wrong seed is worse than a missing one (charter
  do-not-flip-blind), so 10 verified rows shipped, not 16 padded. ENGINE 1.150.0 -> 1.151.0
  (pin sweep 85 files / 96 pins, 0 residual), CHANGELOG prepend, DS :8893 restarted, Share
  re-synced (--check green) SAME commit. Offline characterization tests RED-first
  (test_antitank_ramp_r17.py, 25 cases). DS suite 7497 passed / 1 skip / 1943 subtests; full RC
  suite 9367 passed (the 6 remaining RC failures are PRE-EXISTING - reproduced on base sha
  b00c4dc7: 3x CoachWire ARAM-template, doc_size_budget ROADMAP-over-budget, overlay.css
  sub-floor px, spell_autopush on the dirty data/spell_prefs.json runtime drift - NONE are R17).
  Verifier-gated CONFIRM (byte-identical contract independently reproduced). Live default-ON flip
  EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.

- 2026-06-22 R16 (DIRECTOR REFILL cycle) DONE (`7ecb5b18`) - Section-3b 5-phase fixture audit
  of the 3 un-audited Game Flow + Spike Curve panels (perf_curve.js / spike_curve.js /
  spike_markers.js + their CSS) vs docs/UI_SCALE_SPEC_V2.md. Result = 1 MUST-FIX, all 3 panels
  otherwise v2.1-compliant (buttons hit --hit-min 42px, type on --fs-sm/--fs-xs tokens, ASCII-
  clean, spike cells display-only so not hit-targets). MUST-FIX (in-slice): perf_curve.css
  .pf-ylab/.pf-xlab font-size:13px is a legitimate scaled-viewBox SVG chart-glyph user-unit but
  carried its rationale only in the file header, not INLINE at the declaration like its audit-
  sibling spike_curve.css - added the inline operator-exception comment (zero pixel delta) + a
  NEW TDD guard CssSubFloorFontExceptionTests (RED->GREEN) that fails any sub-16px hardcoded
  font-size lacking an inline operator-exception within 6 lines. Deferred FUTURE: spike_markers
  raw off-grid spacing (1/2/3/6px, radius 4px) = pre-existing, not a NEW value. 136 slice + 13
  hygiene tests green; ruff clean; CSS served live on :8888 (asset-hash reload); verifier CONFIRM
  (6/6). Live Claude_Preview shot OWED (RC-owned :8888 preview blocker + active_match panels
  live-game-gated, mode_key=client) - same carry-forward as R4/R8/R13.
- 2026-06-22 R15 (DIRECTOR REFILL cycle) DONE (`b49ef1a7`) - Section-7b heavyweight competitor
  deep-dive lift of Aggregator A (first review; prior lifts covered Aggregator P / draft tool L /
  target-vs-opponent / simulator tool R / Aggregator H / Aggregator B). 3 disjoint parallel research agents
  (builds / OP-Score+profile / live+overlay), 6-point checklist -> docs/COMPETITOR_LIFT_2026-06-22.md.
  RC matches-or-exceeds most Aggregator A surfaces; the one HIGH-lift LOW-risk presentation gap (Aggregator A's
  per-line curve "shape keyword") SHIPPED as an OP-Score arc-shape readout: NEW core/op_score_shape.py
  pure classifier (Snowball / Ramping / Front-loaded / Commanding / Behind / Steady / Volatile from
  start/end/trend/volatility, RC's own vocabulary) + compute_op_score_curve out["arc"]={win,loss} +
  2 chips in the OP Score panel. No new dependency / Riot / Claude / DB schema / DS / ENGINE change.
  49 slice tests + 5-phase UI audit CLEAN + live ui_mock pixel capture + verifier CONFIRM. Full RC
  suite = 9369 passed / 12 PRE-EXISTING failures (item-578 aram_balance template cluster incl. 7
  test_ds_pick_consumption ARAM subfails + overlay.css px + spell_prefs.json drift) - all independent
  of this slice, 0 regressions. NEWLY DISCOVERED / triaged (FUTURE, not built): single-match
  per-minute OP-Score line + duo "recently played with" panel + a 0-10 post-game rollup (presentation,
  deferrable); live matchup board / enemy-WR-form / live benchmark delta / jungle-camp timers
  (live-game-gated); per-slot frequency sequence + ranked LP trend (new dependency / schema lift).

- 2026-06-22 REGRESS-FIX (continue 16, post-R14 doc reconciliation) DONE - the Gemini auditor
  returned VERDICT REGRESS naming 2 defects in the continue-15 docs sync (`c2161654`); both were
  re-verified vs ground truth before acting (audit-proposals-are-intent / verify-before-broken).
  (1) ROADMAP.md REAL: the continue-15 prepend concatenated the continue-14 sub-bullet onto the
  END of the continue-15 line - FIXED byte-precise, CRLF restored before "  - **SHIPPED ...
  continue 14" (+2 bytes; the 3 touched docs are CRLF). (2) docs/DAEMON_SLAYER.md 1.150.0 = STALE
  PREMISE: the status banner already read 1.150.0 / patch 16.12.1 on HEAD and the drift guard
  tests/test_docs_daemon_slayer_drift.py passed 3/3 BEFORE any edit - NO-OP, no fabricated change
  made on a correct file. Tier-0 doc fix; tiered verification (R5) = drift guard 3/3 + ASCII-
  hygiene, not the 14k full suite. No engine / DS / Share / ENGINE_VERSION / overlay / flip change.

- 2026-06-22 R14 (DIRECTOR REFILL cycle) DONE (`66abc012`) - DS schema lift: optional
  ConditionalCcEntry.durations_floor_s guaranteed-minimum CC floor band + a default-OFF
  apply_cc_floor seam on cc_pressure.compute_cc_pressure (credits floor + prob*(max-floor)
  when ON; byte-identical OFF; both the standalone and coexistence MAX-rule paths). Seeded 5
  vs Meraki 16.12.1 minimums (Maokai R 0.75 / KSante W 0.5 / Sion R 0.25 / Hecarim R 0.75 + a
  NEW Ashe R 1.0 coexisting entry mirroring Maokai/Hecarim R). Registry regenerated via the
  canonical generator (durations_floor_s now on every record); externalization guard count
  64->65 + need-set += durations_floor_s. ENGINE 1.149.0 -> 1.150.0, DS :8893 bounced, Share
  re-synced in the same commit. DS-dir suite 7472 passed; new floor test 13 passed. Coherent
  single-thread unit (linearly-coupled schema->seed->seam->test; R9 no-worktree-under-3-files);
  fresh first-hand re-verification gate (the verifier subagent hit a transient 529; R7 exempts
  single-thread edits from the subagent gate). NEWLY DISCOVERED (pre-existing on clean HEAD
  38326ed3, NOT caused by R14, FUTURE / out of scope): 3 ARAM CoachWire tests fail with
  KeyError 'aram_balance' (test_cc_blended_ehp_context / test_cc_conditional_impact_context /
  test_enemy_cc_threat_context :: test_aram_user_template_format_with_field) - item 578's
  aram_balance field is not threaded into those template fixtures; + test_overlay_css_typography_tokens
  fails on overlay.css bare px literals (overlay-polish lane open work). CI runs no pytest so
  these slipped onto main.

- 2026-06-22 R13 (DIRECTOR REFILL cycle) DONE (`0fb91841`) - Section-3b 5-phase
  fixture audit of the 3 Active Match panels cd_ledger.js / cc_blended_ehp_threat.js
  / threat_donut.js + CSS vs docs/UI_SCALE_SPEC_V2.md. Result = 1 MUST-FIX, 2 panels
  already clean. threat_donut.js: the SVG "?" / "." placeholder hardcoded font-size
  12 inside the fixed 28x28 donut (the 16px --fs-xs floor would overflow the tile) -
  documented as an inline operator-exception (cannot tokenize: no token < 16px by
  design; mirrors the cd_ledger.css density exceptions). cd_ledger.css CLEAN (item 184
  v2.1 already documented its 11/10/9px exceptions); cc_blended_ehp_threat.css CLEAN
  (fully tokenized, no interactive elements). FUTURE (logged, not in-slice): the
  .am-pane-head collapse toggle is ~41px tall, 1px under --hit-min 42px - shared
  selector across all am-panes, out of the 3-panel scope. Orchestrator note: the
  mandated worktree fan-out collapsed to an inline 4-line comment edit (R9: no
  worktrees under ~3 files; the audit found a single 1-file fix); verifier-gated
  CONFIRM (47/0/0) before commit. Visual proof: test_active_match_view.py Playwright
  snapshot renders the AM view hosting all 3 panels (47 passed). No engine / DS /
  Share / ENGINE_VERSION / overlay-render / flip change.

- 2026-06-21 R12 (DIRECTOR REFILL cycle) DONE (`cad49029`) - DS schema lift:
  cross-spell all-source TARGET-VULNERABILITY mark registry. NEW
  agents/daemon_slayer/_target_vulnerability_overrides.py: a vulnerability MARK
  makes the marked TARGET take +X% damage FROM ALL SOURCES - the all-source half
  the per-spell self-amp _ability_amp_overrides can never express. Two registries
  by source kind (_CHAMPION_VULN_OVERRIDES champion_id->ability,
  _ITEM_VULN_OVERRIDES item-id->item) + target_vuln_multiplier composing (1+amp)
  multiplicatively, de-duped per item. Default-OFF apply_target_vuln seam on
  dps.compute_dps scales weighted_dps + every phase_dps; byte-identical OFF
  (verifier CONFIRM). SEEDED 2 ACTIVE vs 16.12.1 ground truth: Vladimir R 10%
  (DDragon Vladimir.json effect[2]=[10,10,10]) + Evenshroud 3001/Arena 223001 7%
  (items.json Coruscation). GROUND-TRUTH DEVIATION (logged, not silent): the
  director named Imperial Mandate 4005 at 6%, but patch 16.12.1 items_meraki
  Coordinated Fire is a current-HP mark-DETONATION (10% current HP bonus magic
  damage on ally consume, 9s/target CD), NOT a +X% all-source amp. No all-source
  value exists to characterize against Meraki ground truth, so 4005 is recorded in
  _NONFIT_VULN_CANDIDATES (documented, NOT seeded) instead of modeled as a fiction
  - a WRONG precompute is worse than none; it belongs in an ally-detonation seam.
  ENGINE 1.148.0 -> 1.149.0 + DS :8893 restarted -> 1.149.0 live + Share --check
  green SAME commit. 23 R12 tests RED-first then green; DS suite 7459 passed / 1
  skipped / 1942 subtests. Live flip + ability_dps/burst broadening EXCLUDED ->
  docs/LIVE_GAME_GATED_SYNC.md. [[feedback_verify_before_declare_broken]] /
  [[feedback_audit_proposals_are_intent]] / [[reference_item_ah_registry_drift]].

- 2026-06-21 R11 fix-first (director directive) - retracts + supersedes the
  post-R10 REGRESS-recheck that previously sat here. WHAT HAPPENED: the gemini
  auditor flagged R10 for "text corruption / accidental path expansion" of the
  Aggregator B benchmark shorthand; the post-R10 recheck correctly found the FEATURE
  clean but then quoted the auditor's alleged corruption VERBATIM into this log +
  LEDGER 562 - planting long at-symbol-repo-path artifact strings (and the raw
  at-10 / at-15 / css-import benchmark tokens) into two living docs. Those planted
  strings read as live corruption and re-tripped the auditor each cycle (the loop
  the director caught). CORRECTION (this cycle): TRUE POSITIVE = the planted
  artifact strings were a real doc-hygiene defect; FIXED = removed / abstracted
  every at-symbol-repo-path and raw benchmark-token literal from this entry +
  LEDGER 562, so the recheck record no longer carries a corruption signature for
  the auditor to re-flag. Retracts the prior "pure no-op false positive" framing -
  there WAS a defect to fix. FEATURE re-verified clean this cycle and NOT changed:
  R10 slice 7c820bfd ships the correct labels (CS / Gold / Lvl at the 10-minute
  mark + Gold at 15) and a legitimate stylesheet import of champ_benchmarks.css;
  docs/COMPETITOR_LIFT_2026-06-21.md + BACKLOG.md (F1) + WAKEUP_NOTES.md all
  verify clean - no feature text was reverted because none was corrupted. Tier-0
  doc-only (no code / engine / DS / Share); doc-hygiene trio re-run green;
  done_sentinel --regressions 0. [[feedback_verify_before_declare_broken]] /
  [[feedback_audit_proposals_are_intent]] / [[feedback_verify_generated_reports]].

- 2026-06-21 R10 (DIRECTOR REFILL cycle) DONE (`edd76db3`, slice `7c820bfd` +
  default-mode fix `2376b4e8`) - Section-7b heavyweight competitor lift of Aggregator B.
  Two parallel research agents (external Aggregator B teardown WHAT/HOW + RC HAVE/WHERE
  map); every HAVE claim re-verified live. Output docs/COMPETITOR_LIFT_2026-06-21
  .md (9 findings, full 6-point checklist each). **IN-RUN SHIP (F8):** NEW Build
  Insights "Benchmarks" tab surfacing core/benchmarks (champion_benchmarks.json:
  186 champ|mode keys x 11 metrics x p25/p50/p75/avg/n) - computed for coach
  prose today, NEVER rendered in the UI (the clean computed-but-not-surfaced
  PARTIAL). NEW dashboard/routes_champ_benchmarks.py (GET /api/champ-benchmarks,
  mirrors routes_duration_winrate 5min cache + 400/500-safe) + web/js/panels/
  champ_benchmarks.{js,css} + web/data/ui_mock fixture + additive
  core/benchmarks.rows_for_mode accessor + tab wire (index.html bench tab/pane +
  build_insights.js dispatch + _dispatch.py registrar + dashboard.css @import).
  Per-champion own-corpus stat distribution (CS@10 / Gold@10 / Gold@15 / KP% /
  Lvl@10; median headline + p25-p75 spread + a Games trust column - Aggregator B's
  always-pair-a-stat-with-its-sample discipline); DESCRIPTIVE personal-corpus,
  NOT a meta winrate; sample-gated (>=3 games). Default mode sr (the only suffix
  the benchmark builder emits; aram/arena render an honest "No X benchmark data
  yet" empty state - not a games-played claim). Presentation over EXISTING local
  data: no schema lift, no new dependency, not validation-gated (distinct from
  the shadow-only EXCLUDED core/live_benchmark_band.py live per-tick band), not
  re-litigation; asset-hash auto-reload (ADR-008), no RC restart. TDD; 51 new
  tests (23 route + 28 panel-DOM) GREEN; verifier subagent CONFIRM + 5-phase
  UI-audit SHIP (0 MUST-FIX) before merge. Triage: F1 (GD@15 lane-counter vs
  win-rate-counter split, needs new rewind_history.db aggregation) + F6 (ARAM
  Modifications balance block) + F7 (duo synergy-delta, non-champ-select home -
  item-213 removed the champ-select grid deliberately) -> BACKLOG; F3 sample
  discipline + global-meta tier / F4 popular-vs-WR / F9 live overlay -> CLOSED.
  NICE-TO-HAVE deferred (visual owed): promote .cb-p50 to --fs-stat 26px. Live
  frame capture OWED (no live game; Claude_Preview cannot attach RC-owned :8888
  per R1/R2). [[feedback_audit_proposals_are_intent]] /
  [[feedback_verify_before_declare_broken]] / [[feedback_phase3_fixture_ritual]].

- 2026-06-21 R9 (DIRECTOR REFILL cycle) DONE (`d52c984e`, merge `6767fd18`) - DS
  schema lift: per-instance FLAT damage-reduction survivability registry. NEW
  `agents/daemon_slayer/_passive_flat_mitigation_overrides.py` models the
  flat-amount-per-instance DR class the percent `_passive_mitigation_overrides.py`
  docstring (lines 64-69) explicitly EXCLUDED. Seeded 3 from champion_abilities.json
  16.12.1 verbatim: Fizz P (flat 4, ANY, prob 1.0, +1% AP omitted), Amumu E (per-rank
  [5,7,9,11,13], PHYS, prob 1.0), Leona W (per-rank [8,12,16,20,24], ANY, active prob
  0.3); all cap_frac 0.5. Default-OFF `assume_passive_flat_mitigation` seam on
  compute_ehp + rank_items_by_ehp folds prevented damage (`_ASSUMED_FLAT_DR_INSTANCES`
  =6 x per-instance-flat x prob) into the EHP NUMERATOR (mirrors ext_flat_hp -
  prevented post-mitigation damage = bonus max-HP equiv); `_ASSUMED_ABILITY_RANK`=4
  reads the per-rank blocks. Byte-identical OFF (proven: Amumu blended 2401.33==2401.33;
  flat_mitigation_hp off=(0,0,0) on=(66,0,0) phys; unregistered champ identical on/off).
  DEVIATION from the directive's per-LEVEL assumption: Amumu/Leona carry per-RANK flat
  blocks in 16.12.1, modeled rank_scaled (followed the data). EhpResult gained
  passive_flat_mit_phys/mag/true (default 0.0, appended at end). ENGINE 1.147.0 ->
  1.148.0; DS :8893 restarted -> 1.148.0 live; Share synced (--check in-sync, 368 files).
  TDD test_passive_flat_mitigation_overrides_r9.py. Suites GREEN: DS 7436 passed (+1942
  subtests), RC 9132 passed (1 known live-daemon version-pin failure, resolved by the
  restart). Verifier-gated CONFIRM before merge. Live flat-DR flip EXCLUDED ->
  docs/LIVE_GAME_GATED_SYNC.md.
- 2026-06-21 R8 (DIRECTOR REFILL cycle) DONE (`4916d8e4`) - Section-3b 5-phase UI
  audit of the Electron overlay surface (overlay.css + overlay_ds_controls.js +
  overlay_pulse.js) vs UI_SCALE_SPEC_V2 v2.1; addressed the R6 residual.
  **TYPOGRAPHY (the fix):** overlay.css carried 4 hardcoded sub-floor font-size
  literals (.rc-src 13px; threat .cd-chip 13px; .cd-chip-sigil 12px; .cd-row-initial
  13px) - deliberate item-184 operator-exception game-distance values (read on the
  ~460px right-dock, lifted up from the 9-11px dashboard cd_ledger densities; 16px
  overflows the dense threat ledger). TOKENIZED, not bumped: NEW overlay-scoped
  --fs-ov-chip(13px)/--fs-ov-sigil(12px) on body[data-shell="overlay"] (sec 1b), NOT
  tokens.css :root (the global scale keeps its >=16px floor invariant); the 4 consumers
  now var()-reference them. Pure rename = ZERO pixel delta. **AUDIT (independent
  subagent):** VERDICT SHIP - STRUCTURE (no dead selectors; every overlay.css id/class
  maps to a JS-emitted mount), HIT-TARGETS (every overlay clickable meets --hit-min 42px
  via overlay_ds_controls.css padded-label rows), ASCII (0 bytes >0x7F all 3 files),
  HIERARCHY (CALL pane out-weights peers, sec 3b) all PASS; 0 MUST-FIX beyond the
  tokenization. **TDD red->green:** tests/test_overlay_css_typography_tokens.py 4 tests
  RED first (4 failed) -> GREEN (no bare px literal + tokens defined + referenced +
  overlay-scoped & global-floor invariant). **VISUAL (Playwright snapshot harness,
  directive step 4):** NEW test_overlay_view.py::test_overlay_subfloor_tokens_resolve_
  to_game_distance_px proves in a real browser --fs-ov-chip->13px, --fs-ov-sigil->12px,
  .rc-src computes 13px; full overlay snapshot suite 21 passed. **VERIFY:** verifier
  subagent CONFIRM all 6 claims (0 bare px, 4 consumers tokenized, overlay-scoped not
  :root, global floor intact, 4 passed fresh, 0 non-ASCII). Full RC suite
  tests/ --ignore=tests/daemon_slayer 9137 passed / 2 skip / 110 subtests; the 1 fail
  + 1 error are ENVIRONMENTAL live-game pollution, NOT this slice (no overlay code
  path): test_spell_autopush_e6 reads data/spell_prefs.json which the LIVE Caitlyn SR
  game wrote by_champ.SR.Caitlyn=[4,21] (Flash+Ignite) - modified in the working tree
  BEFORE this session per the session-start git status (HEAD by_champ is empty) - so
  the role-fallback assumption breaks; test_zaahen_loadout_item277 test_tool_is_ascii
  ERROR is the session-scoped assert_prod_artifacts_unchanged teardown (conftest.py:145)
  catching the live RC + vision daemon writing data/*.jsonl mid-run, re-attaching to the
  last test. Both reproduce in isolation, both predate + are independent of this slice;
  left untouched (live runtime state). ruff clean; py_compile OK. **ORCHESTRATION
  (auto-pick, logged):** sole orchestrator, INLINE per R9 (1 CSS file + 2 test files,
  below the worktree-slice threshold; the directive's parallel-worktree mechanism applied
  inline, intent over mechanism [[feedback_audit_proposals_are_intent]]); the directive's
  verifier gate was RUN (read-only verifier subagent CONFIRM before commit, directive
  step 2). Tier-1 CSS+test: no ENGINE bump / 0 frozen / no DS restart / no Share mirror /
  ADR-008 asset-hash auto-reload (no RC restart). Pre-existing working-tree edits NOT
  staged (left for operator/next cycle): ROADMAP.md (operator overlay-run cadence note),
  data/spell_prefs.json (live-game pollution). Source: gemini director directive
  ops/loop/control/directive.md (R8). [[feedback_phase3_fixture_ritual]] / [[feedback_verify_before_declare_broken]] / [[feedback_execution_efficiency_rules]].

- 2026-06-19 R7-regress-fix (DIRECTOR REFILL cycle, REGRESS-fix) DONE - the gemini
  auditor flagged a correctness regression in the R7 per-stack self-AS seam
  (agents/daemon_slayer/dps.py). UNIT MISMATCH: `passive_as_bonus()` returns a bonus-AS
  FRACTION (Irelia full stacks L18 = 1.0 = +100%; Jax L11 ~0.75), but the seam added it
  DIRECTLY to `stats_for_rotation["as"]`, which is FINAL attacks/sec (engine.py:195 resolves
  it as `base_as * (1 + bonus_pct)`, 2.5-capped). Adding the raw fraction over-credited AS by
  a factor of 1/base_as (~1.5x for Jax). FIX (dps.py): fold the fraction onto the champion's
  INNATE base AS - `innate_base_as = (champ["stats"]["attackspeed"]); + innate_base_as *
  passive_as`; the `min(2.5, ...)` hard-cap clamp preserved; note reworded to "+X% bonus AS
  ... folded onto base AS". TDD RED-first: NEW test `SeamAddsBaseAsScaledFraction` pins the
  corrected math by colinearity - `weighted_dps` is exactly affine in rotation AS
  (`total_attacks = basic + basic_time*as`; duration AS-independent), so off / pure-AS-Dagger
  calibration / on builds are colinear; the ON gain must equal `c1*(base_as*pa)`, NOT `c1*pa`.
  Confirmed RED on the buggy code (135.24 vs predicted_correct 118.75), GREEN after the fix.
  NO ENGINE_VERSION bump: the seam is DEFAULT-OFF (`test_default_off_byte_identical` proves
  byte-identical) + operator-gated (`assume_passive_as_stacks` not live), so the buggy math
  never reached a live consumer - no output-provenance delta, and the directive scoped "do not
  advance to a new item". SIBLING (FUTURE, NOT fixed this cycle - out of directive scope,
  pre-existing + separately pinned): the Yun Tal `cond_as` path (dps.py batch 54) adds
  `bonus_as_conditional=0.08` (a 30%-AS-at-27%-uptime FRACTION) to final AS the same way -
  same unit-mismatch class but tiny + long-shipped; a future cycle should base_as-scale it too.
  GATE (fresh this run): R7 file 20 passed; DS dir 7414 passed / 1 skip / 1942 subtests / 0
  failed; RC tests/ 8644 passed / 2 skip / 110 subtests (the lone failure was the expected
  Share-drift guard, GREEN after `ds_share_sync` re-mirror: `test_ds_share_sync_determinism`
  5 passed, --check in sync, 366 files, engine 1.147.0); ruff All checks passed; py_compile OK.
  Share/src + MANIFEST re-synced in the SAME commit (a source edit under agents/daemon_slayer/**
  drifts the mirror). verifier subagent re-check (directive-mandated): VERDICT CONFIRM on all
  6 claims (the lone determinism teardown ERROR is the live vision daemon mutating
  data/vision_state.json mid-run - environmental, not the fix; the 5 determinism tests passed).
  INLINE sole orchestrator (R9 - one-file math fix + its test, no disjoint slices). Tier-2
  (engine math). No frozen files. Source: gemini director directive
  ops/loop/control/directive.md (R7 regression fix). R7 itself stays DONE (`7c22e3bb`).

- 2026-06-19 R7 (DIRECTOR REFILL cycle) DONE (`7c22e3bb`) - DS schema lift: per-stack
  champion self-Attack-Speed passive seam on the AA DPS scorer (ENGINE 1.146.0 ->
  1.147.0). NEW `agents/daemon_slayer/_passive_as_overrides.py` registry - the
  ATTACK-SPEED sibling of the item-effect `total_conditional_as` (Yun Tal) lane, keyed
  on the CHAMPION's innate per-stack passive. `compute_dps` gains a default-OFF
  `assume_passive_as_stacks` seam: when ON, `passive_as_bonus(cid, level, ap,
  stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION=1.0)` folds the champ's per-stack
  bonus AS at full stacks into the rotation AS with the SAME 2.5 hard-cap re-clamp as
  cond_as (raw_attack_dps left at the no-conditional baseline, matching cond_as). **GROUND
  TRUTH (file-cited, [[feedback_verify_before_declare_broken]]):** seeded 4 from
  `data/daemon_slayer/16.12.1/champion_abilities.json` (Meraki content patch 25.15)
  effects_descriptions - Irelia Ionian Fervor 10%:25% by level/stack max 4 -> 40%:100%;
  Jax Relentless Assault 5%:12.5% by level/stack max 8 -> 40%:100%; Ezreal Rising Spell
  Force 10% flat/stack max 5 -> 50%; Volibear The Relentless Storm (5% + 4% per 100 AP)/
  stack max 5 -> 25% + 20% per 100 AP (the one AP-scaled passive, reads the resolved
  post-amp `ap`). per_stack * max_stacks == the documented max by construction, so the
  full-stack assumption is self-clamping (no separate ceiling). The on-hit / Lightning
  Claws / Unsteady mechanics on these passives are SEPARATE, not the AS buff - deliberately
  not modeled here. **TDD red->green:** `test_passive_as_overrides_r7.py` RED first
  (ImportError, seam absent) -> implemented -> GREEN (19/19): registry pins vs Meraki +
  full-stack-max-matches-documented (both level endpoints) + level-interp midpoint +
  Volibear AP scaling + stack-fraction clamp + compute_dps OFF byte-identical (4 champs,
  weighted+phase+raw) + ON raises DPS + note + unregistered-champ byte-identical-even-ON.
  **VERIFY (Tier-2 dual suite, [[reference_ds_bump_run_tests_dir]]):** DS-dir 7413 passed
  / 1 skip / 1942 subtests (exit 0); RC `tests/ --ignore=tests/daemon_slayer` 8645 passed
  / 2 skip / 110 subtests (exit 0) - NO mid-suite transients this cycle because the Share
  sync + DS :8893 restart were sequenced BEFORE the RC suite (vs R3/R5 which ran through
  the restart window). DS `/health` confirmed live 1.147.0 ([[reference_ds_server_not_supervisor_watched]]
  taskkill /F + `schtasks /Run /TN RC-DaemonSlayer`). ruff clean; Share `--check` green
  (366 files + doc anchors + lolmath_ingest). ENGINE bump = quoted-literal pins only
  ([[feedback_engine_bump_quoted_literal_only]]): byte-level replace of the assertion/
  assignment `"1.146.0"` patterns across 80 DS test .py (89 subs) + `__init__.py`; CHANGELOG
  bare-version prose untouched; CHANGELOG + Share/CHANGELOG dated entries prepended. **ORCHESTRATION
  (auto-pick, logged):** sole orchestrator, INLINE per R9 (registry + seam + consumer + test
  interlock - a single tightly-coupled engine change, not disjoint slices; the directive's
  parallel-worktree mechanism applied inline, intent over mechanism
  [[feedback_audit_proposals_are_intent]]); verifier SKIPPED per R7 (own single-thread; the
  fresh dual suite + the live :8893 re-verify + the file-cited Meraki ground-truth grep ARE
  the independent verify); no blocking AskUserQuestion (operator away). Live default-ON flip
  operator-gated -> appended `docs/LIVE_GAME_GATED_SYNC.md` live-flip ledger (R7 row); EXCLUDED
  L156 already names "per-stack assumed_stacks" as a gated flip class, so this seam slots into
  the existing live-sync plan. **NEW residual (FUTURE, not built):** the registry is the seed
  of an innate-per-stack-self-AS class - a per-patch re-scan of champion_abilities.json for
  new "X% : Y% per stack ... bonus attack speed" passive lines (+ any other AP-scaled AS
  passive beyond Volibear) joins the per-patch re-anchor; the live default-ON flip wires the
  dps/hybrid scorer-dispatch (the same site the B1 melee gate flips) to pass the flag for the
  4 tabled champs. Source: gemini director directive (R7). [[feedback_verify_before_declare_broken]]
  / [[feedback_engine_bump_quoted_literal_only]] / [[reference_ds_bump_run_tests_dir]] /
  [[reference_ds_server_not_supervisor_watched]] / [[feedback_execution_efficiency_rules]].
- 2026-06-19 R6 (DIRECTOR REFILL cycle) DONE (`139ef216`) - Section-3b 5-phase UI
  audit of two un-audited dashboard panels (cooldown_watch + cc_conditional_pressure,
  JS+CSS) vs UI_SCALE_SPEC_V2 v2.1. **TYPOGRAPHY = verified no-op:** both CSS files were
  ALREADY fully tokenized (every font-size resolves through `var(--fs-*)`, all >= --fs-xs
  16px; grep `font-size:\d+px` = 0 hits) - the directive's "tokenize sub-floor hardcoded
  font-sizes" had nothing to do (R4 typography-floor sweep / original ship already
  compliant; do-not-fabricate, [[feedback_verify_before_declare_broken]]). **MUST-FIX
  (genuine dead CSS):** cc_conditional_pressure.css carried `.cc-conditional-pressure-ratio`
  + `-ratio-value` (3 rules, ~24 lines) ORPHANED since item 213 (2026-05-28) replaced the
  ratio summary render with the plain-language verdict line - `renderCcConditionalPressure`
  never emits those classes. Grep across web/ + tests/ proved ZERO consumers -> removed.
  ZERO pixel delta (selectors never matched a DOM). cooldown_watch CSS classes all match
  JS-emitted (no dead CSS). **HIT-TARGETS N/A** (both are display-only chips, no clickable
  surface). **ASCII** 0 non-ASCII bytes (all 4 files; existing AsciiHygieneTests already
  guard JS+CSS). **STRUCTURE / HIERARCHY** PASS (small chips in the Suggestions / My-Pick
  cards, readable at 1920x1080). **TDD red->green:** `test_no_orphan_ratio_selectors` RED
  (dead CSS present) -> removed -> GREEN; +2 `test_font_sizes_are_tokenized` characterization
  guards (one per panel test file) lock token compliance against future sub-floor regress.
  **VERIFY:** verifier subagent CONFIRM all 4 claims (44 panel tests fresh; selector gone;
  tokenized; ASCII clean); full RC suite `tests/ --ignore=tests/daemon_slayer` 8645 passed
  / 2 skip / 110 subtests / exit 0 (8642 + 3 new). DS suite N/A (CSS+test cannot affect
  engine math, Tier-1 not Tier-2 tax per R5/R6). ruff clean. **VISUAL:** dead-CSS removal
  = zero rendered delta; the champ_select_view snapshot harness (in the RC suite) covers
  the panel render; Claude_Preview :8888 + Game-PC :8892 per documented env constraints.
  **ORCHESTRATION (auto-pick, logged):** sole orchestrator, INLINE per R9 (1 CSS file + 2
  test files, far below the worktree-slice threshold; the directive's parallel-worktree
  mechanism applied inline, intent over mechanism [[feedback_audit_proposals_are_intent]]);
  verifier subagent run on the slice claim BEFORE commit (directive step 3). Tier-1 CSS+test:
  no ENGINE bump / 0 frozen / no DS restart / no Share mirror / ADR-008 asset-hash
  auto-reload (no RC restart). **NEW residuals (FUTURE, not built - disjoint scope):**
  (1) overlay.css 12/13px hardcoded sub-floor sizes (Electron overlay surface, separate
  audit pass); (2) next.css:10 font-size 21px hardcoded (above floor, not in named scope);
  (3) `.cc-conditional-pressure-verdict` renders the actionable coaching sentence at --fs-xs
  (16px) - clears the floor but is the smallest tier for primary actionable text; a tier
  bump is a subjective readability call -> logged FUTURE, not shipped blind. Source: gemini
  director directive (R6). [[feedback_phase3_fixture_ritual]] / [[feedback_verify_before_declare_broken]] / [[feedback_audit_proposals_are_intent]] / [[feedback_execution_efficiency_rules]].
- 2026-06-19 R5 (DIRECTOR REFILL cycle) DONE (`dc2eb0c3`) - DS schema lift:
  missing-HP heal-AMPLIFICATION seam on the ability-HPS scorer (ENGINE 1.145.0 ->
  1.146.0). The heal-AMP MULTIPLIER class `_passive_heal_overrides.py:27` (item-253
  header) explicitly EXCLUDED from the heal-MAGNITUDE registry. NEW
  `_MISSING_HP_HEAL_AMP[champ][spell] = max_bonus` registry + `_missing_hp_heal_amp_
  factor` in `ability_hps.py` (co-located with `_AOE_HEAL_TARGETS`); `compute_ability_
  hps` gains `assume_missing_hp_heal_amp` (default OFF byte-identical, full-HP also
  identity), `heal_per_cast *= 1 + max_bonus * caster_missing_hp_pct` (HEAL-only,
  reuses the existing missing-HP param). Seeded 4 (champion_abilities.json 16.12.1
  effects_descriptions, file:line probed): Master Yi W Meditate / Lissandra R Frozen
  Tomb / Sylas W Kingslayer 0%:100% -> 1.0, Briar P Crimson Curse 0%:40% -> 0.40
  (+per-100-bonus-health sub-term omitted, lower bound). Nidalee E (a directive e.g.)
  probed, NO amp text -> NOT seeded (3/4 examples verified, 1 corrected, +Briar bonus).
  TDD test_missing_hp_heal_amp_item515.py RED-first. DS 7394 / RC 8642 green (8 mid-
  suite restart/sync-window transients re-verified fresh = 40 passed); ruff + Share
  --check clean. Inline sole orchestrator (R9; one coupled file + test, registry+seam+
  consumer interlock = no disjoint slices; verifier skip R7, fresh dual suite + live
  :8893 1.146.0 + file:line grep = the independent verify). Live default-ON flip ->
  docs/LIVE_GAME_GATED_SYNC.md (operator-gated). NEW residual (FUTURE, not built):
  the `_MISSING_HP_HEAL_AMP` registry is the seed of a heal-amp class - a patch
  re-scan for new "0%:X% based on missing health" heal lines + a possible heal-amp
  sibling for the SHIELD path (none found 16.12.1) join the per-patch re-anchor.
  [[feedback_engine_bump_quoted_literal_only]] / [[reference_ds_bump_run_tests_dir]] /
  [[reference_ds_server_not_supervisor_watched]] / [[feedback_verify_before_declare_broken]].
- 2026-06-19 R4 (DIRECTOR REFILL cycle) DONE (`9e56d23d`) - Section-3b 5-phase
  typography-floor UI audit of three un-audited core coaching panels
  (team_context / coach_choices / item_build, JS+CSS) vs UI_SCALE_SPEC_V2 v2.1.
  Tier-1 CSS-only, NO ENGINE / 0 frozen / no DS / no Share / ADR-008 asset-hash
  auto-reload (no RC restart). TYPOGRAPHY: 14 in-scope sub-floor (< --fs-xs 16px)
  hardcoded font-sizes tokenized (team_context 7x -> --fs-xs + .tc-slot radius ->
  --panel-radius-sm; coach_choices .rc-src 10 -> --fs-xs + stale 18px fallbacks ->
  22; item_build ds-chip/em + build-label + item-cost + ib-builds-status +
  cs-build-label -> --fs-xs, build-value 19 -> --fs-md). 2 documented operator-
  exceptions kept sub-floor with inline rationale (.item-name 14px = 70px tile +
  2-line clamp; .cs-build-runes 10px = dense narrow ITEM BUILD column).
  STRUCTURE/HIT-TARGETS/ASCII/HIERARCHY PASS (independent 5-phase audit subagent =
  SHIP, 0 MUST-FIX; .rc-chip keeps --hit-min 42). SCOPE: the cross-panel
  .kv/#nx-wave/.minimap-grid blocks in item_build.css (style already-audited Right
  Now/Next/Active-Match, C2) were EXCLUDED. DISCOVERY: Claude_Preview DOES attach
  to https://localhost:8888/ (prior cycles' "cannot attach to :8888" was the
  legion-rc hostname cert mismatch); a computed-style probe on the live stylesheet
  proved every in-scope selector resolves >=16px + the 2 exceptions hold. TDD
  drift-guard tests/test_core_panels_typography_v21_floor.py (7 tests). RC suite
  8642 passed / 0 fail. Inline sole orchestrator (R9; 3 tiny disjoint CSS slices;
  verifier role = the independent audit subagent + the live computed-style probe).
- FUTURE (R4 NICE, deferred): .ib-builds-block .cs-build-row is clickable
  (item_build.js click handler) but its tap target is not explicitly pinned to
  --hit-min (renders ~42px incidentally); pre-existing, out of the typography
  slice.
- 2026-06-19 R3 (DIRECTOR REFILL cycle) DONE (`ab23c32c`) - DS passive_damage
  caster-defensive-stat scaling schema lift (ENGINE 1.144.0 -> 1.145.0). The
  DamageBlock.bonus_armor_pct / bonus_mr_pct fields + _SCALING_TARGETS mappings
  (-> caster_bonus_armor / caster_bonus_mr) + AbilityContext attrs ALREADY existed;
  the gap was the hand-authored registry not carrying them. Added bonus_armor_pct /
  bonus_mr_pct to PassiveDamageEntry + PerStackTerm; to_damage_block copies them
  (ZERO new evaluator math). Seeded Taric P (25:93 + 15% bonus armor) + Galio P
  (15:115 + 100% AD + 45% AP + 60% bonus MR), both default-OFF byte-identical, both
  metadata-only (not AA-routed). EXHAUSTED 172-champ sweep: ONLY these 2 clean linear
  cases. NEW residual (FUTURE, not built blind): K'Sante P "All Out Bonus" = bilinear
  (caster bonus armor / MR x target max HP) + gated on the R-empowered All Out state -
  needs a bilinear term keyed on caster_bonus_armor + a conditional_probability for the
  All Out gate; Rammus W Defensive Ball Curl = 15 + 10% TOTAL armor + 10% TOTAL MR
  on-being-hit reflect - needs a caster-total-MR _SCALING_TARGETS field (only
  caster_armor total exists, no caster_mr) + a reflect cadence, wrong seam for the
  empowered-AA registry. +18 characterization subtests; DS 7379 / RC 8634 green
  (live-engine integration re-verified post-restart at 1.145.0). Share synced same
  commit (--check green). Inline sole orchestrator (single-file schema lift < worktree
  threshold per R9; verifier skip R7 - own single-thread, fresh dual suite + live curl
  ARE the independent verify). [[reference_ds_bump_run_tests_dir]] /
  [[feedback_engine_bump_quoted_literal_only]] / [[reference_ds_server_not_supervisor_watched]].

- 2026-06-19 R2 (DIRECTOR REFILL cycle) DONE (`9b55615d`) - Section-3b 5-phase UI
  audit of the Build Insights surface + recent tabs + the item-511 GPI drilldown.
  PREMISE CORRECTION ([[feedback_verify_before_declare_broken]]): the directive named
  op_score_curve.js; the real file is web/js/panels/op_score.js (op_score_curve is the
  BACKEND core module). Audited the 4 real panels JS+CSS (build_insights /
  duration_winrate / op_score / player_gpi) vs docs/UI_SCALE_SPEC_V2.md. STRUCTURE PASS
  (mounts/tabs/wiring test-locked); TYPOGRAPHY PASS (all DOM type on v2.1 --fs-* tokens;
  the only sub-16px values are SVG <text> user-units in scaled viewBoxes - op-ylab/op-xlab
  13px, gpi-axis 8/8.5px - each with an inline rationale = documented exceptions); ASCII
  PASS (py byte-scan 0 bytes >0x7F across all 8); HIERARCHY PASS (max-width caps +
  min-width:0 radar + ellipsis select, no h-scroll at 1920). HIT-TARGETS: 1 MUST-FIX ->
  .bi-table th.bi-sortable set min-height for --hit-min, a no-op on a display:table-cell
  box, so the 42px sortable-header target was never applied; fixed to height (honored as a
  cell minimum). Deferred NICE-TO-HAVE: gpi-tip --radius-sm vs --panel-radius-sm (would
  churn the gpi snapshot PNG); Min-buys control inert on chart/curve tabs (already
  R1-logged). VISUAL PROOF: Claude_Preview cannot attach to RC-owned :8888 (per R1) -> the
  Playwright snapshot harness tests/snapshot_panels/test_player_gpi_view.py 5/5 PASSED incl.
  test_player_gpi_champion_drilldown (item-511 selector) + regenerated player-gpi_radar.png
  (byte-identical; GPI panel unchanged). VERIFY: full RC suite tests/
  --ignore=tests/daemon_slayer 8634 passed / 1 failed / 2 skip - the lone failure was
  PRE-EXISTING (test_doc_size_budget::test_roadmap_md_under_budget; ROADMAP.md 82355 > 81920
  after the item-510/511 commits; CI runs no pytest so it slipped). Fixed red-first by
  relocating the 2026-06-01 DS Phase A/B/C + champ-select shipped epic (items 241-259) to
  docs/ROADMAP_HISTORY.md (breadcrumb keeps the Phase-D + #7/#8 residual); ROADMAP 76587
  bytes, doc-size 2 passed, 47 ROADMAP-ref tests re-verified. CSS-only -> asset-hash
  auto-reload (ADR-008), no RC restart. NO DS / Share / frozen / ENGINE / backfill. INLINE
  sole orchestrator (edit footprint 1 CSS line, below the worktree-slice threshold, so the
  directive's worktree mechanism was applied inline - intent over mechanism,
  [[feedback_audit_proposals_are_intent]]); verifier SKIPPED per R7 (own single-thread; the
  full suite + the Playwright render + the targeted re-verify ARE the independent verify).
  Source: gemini director directive ops/loop/control/directive.md (R2).

- 2026-06-18 HEADLESS-DIRECT (direct /headless-upgrade run; gemini loop self-stopped
  NO_WORK x2 this AM, so this is operator-direct not director-driven) DONE. Three slices.
  (P0) CI fix `e33892c3`: the schedule-only nightly-full-suite job ran the whole tree
  (pytest tests/ agents/daemon_slayer/tests/) but copy-pasted the pure-Python `check` job's
  minimal-deps install, so collection ImportError'd - websockets x3, portalocker x2, PIL x1,
  json5 x1 (exit 2, run 27750548487 @09:37 UTC schedule). Fix: nightly now
  `pip install -r requirements.txt` + test runner (Legion collect-only = 15705 tests / 0 err
  with deps present, proving deps were the only gap); declared the 2 real-but-undeclared prod
  deps (websockets==16.0 = agents/agent2_backend/ws_server.py + core/obs_publisher.py;
  json5==0.14.0 = tools/daemon_slayer_extract.py); added workflow_dispatch for on-demand
  verify. push `check` 27767581918 GREEN; nightly dispatch 27767592953 verifying.
  (P1) Section-4b Haiku-elimination flip-gate snapshot - offline vs data/rewind_history.db
  replay ground truth (400-651 matches); ran all 3 existing replay flip-gates to measure
  whether any HZ-* precompute is ready to retire its live Haiku call:
    - Lane A laning-verdict (replay_laning_verdict_validate, patch 16.12.1, 1998 pairs,
      coverage 3978/3996): ~50% agreement every level + both proxies (Wilson straddles 50) =
      NO signal. Engine fn compute_matchup tops ~52-53% solo-kill / ~55-56% TOP-role; the
      SHIPPED table loses even that (table-build/baseline-cell degradation). HOLD on Haiku.
    - Lane B build-order lean (replay_build_order_validate): followed-vs-not diff +3.3%
      [-2.3,+9.0], flip_ready=False but DIRECTIONALLY positive - anti_tank carriers (Void
      Staff / Black Cleaver / Lord Dominik's) ~+9% each, anti_squishy followed 58.2% vs not
      48.3%. MOST PROMISING lever; HOLD (CI includes 0), rank as next Lane B target.
    - Pickban (replay_pickban_validate, 651 matches): gold 46.1% [41.5,50.7] / trade 49.3%
      [42.4,56.1], clears_coinflip=False = NO signal. Keep secondary hint; HOLD champ-select.
    DECISION: no surface flip-ready -> Haiku stays interim floor on ALL three (validate-
    before-flip, charter 4b; reinforces the EXCLUDED-list HZ rule above). NEXT lever ranked =
    Lane B build-order anti_tank carrier ordering (strongest signal); Lane A blocked on the
    engine-model ceiling (TOP lane ~55-56% is closest). Artifacts:
    ops/runtime/{laning_verdict_validation,pickban_validation}.json.
  (P2) Section-4 cost/latency 7-lever sweep CLEAN (no commit): no sub-500ms network poll
  (only UI-local setInterval(applyStaleness,500)); cache_control present across all 14 coach
  messages.create callers; haiku held as interim floor per P1; no net-positive fix surfaced.

- 2026-06-18 R1-regress-fix (cycle 2, REGRESS-fix) DONE - the auditor flagged R1 as
  REGRESS: dashboard/routes_duration_winrate.py shipped with NO route test (only
  core/duration_winrate.py was covered by tests/test_duration_winrate.py). Added
  tests/test_routes_duration_winrate.py +14 covering the ROUTE layer: query parsing
  (default mode=aram, valid-mode passthrough, bad mode -> 400 with compute-not-called,
  champion int passthrough + non-int -> 400, omitted -> null, mode checked before
  champion), the (mode, champion) 5min in-process response cache (second same-key call
  cached with NO recompute via compute call-count, key separates by champion AND by
  mode, _reset_caches forces recompute), the cached/elapsed_ms envelope fields, the 500
  no-raw-leak path (compute raises -> body == "internal error - see logs", secret text
  absent), and the _dispatch GET registration. compute_duration_winrate is patched to a
  deterministic stub so the test touches NO real rewind_history.db (clean-checkout / CI
  safe; mirrors the test_routes_player_profile harness). Characterization, not RED-first
  - the route was already correct; the regression was absent coverage, not broken
  behavior (the tests fail if the route's status/cache/leak contract regresses). Tier-1
  test-only (NO engine / ENGINE_VERSION / DS / Share / frozen / RC restart / backfill).
  GATE (fresh this run): the new file 14 passed / 0.24s; ruff All checks passed;
  py_compile OK; ASCII + LF clean; full RC suite tests/ --ignore=tests/daemon_slayer
  8363 passed / 2 skip / 109 subtests exit 0 (8349 R1 baseline +14; a trailing
  logging-on-closed-file warning from the background TFT-OCR daemon thread at
  interpreter teardown is benign, not a test failure). INLINE sole orchestrator (R9 +
  the director's "trivial one-file item may use a single agent" clause - one test file,
  no disjoint slices); verifier SKIPPED per R7 (own single-thread, no untrusted slice -
  the characterization + ruff + the full RC suite ARE the independent verify). No frozen
  files. Source: gemini director directive ops/loop/control/directive.md (R1 regression
  fix). R1 itself stays DONE.
- 2026-06-18 R1 (DIRECTOR REFILL cycle) DONE (e9f70e7d) - Section-7b heavyweight
  competitor deep-dive of Aggregator H (a not-yet-reviewed target) + shipped the
  lone HIGH-lift LOW-risk presentation finding IN-RUN. Tier-1 (new core module +
  route + panel; NO engine / ENGINE_VERSION / DS / Share / frozen / backfill).
  BOTTOM LINE: RC supersedes most of Aggregator H (DS build/dps/ehp, the
  player_gpi radar, the build-insights WPA lane, live_benchmark_band); the one
  genuine gap = the signature win-rate-by-game-length curve, a pure aggregation over
  game_duration_s + tracked_win that RC already reads from rewind_history.db.
  SHIPPED F1: core/duration_winrate.py (mode via player_gpi.MODE_MAPS map_id;
  MIN_DURATION_S=300 remake gate + MAX_DURATION_S=7200 outlier drop - the VERIFY
  GATE caught 4 ms-encoded/corrupt duration rows the agent's spec missed, MAX
  game_duration_s=1988073 with a clean 3600-100000s zero gap; MIN_BUCKET_N=5 trust
  gate; conn= test seam, clean-checkout safe) -> dashboard/routes_duration_winrate.py
  GET /api/duration-winrate (mirrors routes_player_profile, 5min TTL, never leaks a
  raw error) registered in _dispatch.py -> Build Insights "Game Length" tab
  (web/js/panels/duration_winrate.js+css, self-contained chart panel, dispatched from
  build_insights.js::_renderActive, table engine untouched) + ui_mock fixture. TDD +8
  (RED-first: bucket tally, MIN_BUCKET_N gate, lo-incl/hi-excl boundaries,
  remake+outlier drop, map_id mode filter, champion filter, empty fail-soft,
  invalid-mode fallback). LIVE-VALIDATED over the real corpus: ARAM n=2044 downward
  slope 56.2/51.1/49.4/48.2 (snowball tendency), SR n=683 peak 30-35m 60.2. GATE
  (fresh this run): full RC suite tests/ --ignore=tests/daemon_slayer 8349 passed / 2
  skip / 109 subtests exit 0; ruff + py_compile + node --check clean; ASCII byte-scan
  clean for my additions (index.html pre-existing nav glyphs untouched). RC restarted
  pid 11712, /api/duration-winrate live (aram/sr correct; bogus mode -> 400 with the
  friendly error). 5-PHASE UI AUDIT code-side PASS, no MUST-FIX (1 SHOULD-FIX
  deferred: the shared Min-buys control is inert on the chart tab; hiding it needs the
  table engine, low value). LIVE VISUAL CAPTURE OWED (Game-PC :8892 down +
  Claude_Preview cannot attach to RC-owned :8888 headless - carry-forward in WAKEUP +
  synopsis). TRIAGE: F2 global win/pick/ban + F6 lobby-player-tags + F7 global
  objective/tier/leaderboard = FUTURE (each needs a new external dependency; F6 is
  already on BACKLOG as Overlay App F 3.1); F3 builds/WPA/matchup/synergy + F4 GPI
  Power-Circle + F5 percentile = CLOSED (RC at-parity or superior). No new BACKLOG
  item required. INLINE sole orchestrator (R9 coupled-seam: core -> route -> panel
  dependency-ordered, not disjoint files; the RF1-RF6 inline precedent); verifier
  SKIPPED per R7 (own single-thread, no untrusted slice - the RED->GREEN TDD + the
  full-suite + the live endpoint probe ARE the independent verify). No frozen files.
  Doc: docs/COMPETITOR_LIFT_2026-06-18.md. Source: gemini director directive
  ops/loop/control/directive.md (R1 DIRECTOR REFILL).
- 2026-06-17 RF6 (cycle 6, round-2 refill) DONE (700fa6a8) - ehp/tank survivability
  INJECT seam, ENGINE 1.138.0 -> 1.139.0, DEFAULT-OFF. ROOT-CAUSE (probe-confirmed,
  not the directive's assumed "mana-item gate" phrasing): Rell's Fimbulwinter 3121
  is dropped by `_is_purchasable` - gold.purchasable=False because 3121 is the
  non-purchasable mana-line TRANSFORM of Winter's Approach 3119 (terminal=True,
  ARAM-legal=True; the off-class marksman deny-set does NOT apply - it fires only
  for ranged marksmen and Rell is a tank). Live probe: 3121 NOT in Rell's ehp pool
  OFF (124 items); RF3 float ON surfaced [] (confirms RF4 in_pool=False, the RED).
  KEY DEVIATION FROM THE DIRECTIVE (feedback_audit_proposals_are_intent): the
  literal "mirror RF2's only_ids |= surv_ids" is INSUFFICIENT - probed RF2's own hps
  inject and it ALSO silently drops 3121 for Rakan (surfaces only purchasable
  2051/3083/3084), because the only_ids UNION still runs through _is_purchasable. So
  the union mechanism cannot surface a non-purchasable transform at all. Implemented
  the INTENT ("tabled-but-not-pooled ids surface" / "Rell Fimbulwinter floats ON")
  via a NEW `inject_ids` force-admit param on `rank._filter_candidates`: an id in
  the set bypasses the only_ids whitelist + exclude_names deny + _is_purchasable gate
  while still honoring already-equipped / non-coachable / mode-legality / terminal /
  budget; None default = byte-identical for all 7 callers. `ehp.rank_items_by_ehp`
  passes inject_ids=surv_ids ONLY when the RF3 prefer_survivability_by_win seam is ON
  (the SAME flag, no new param), so the tabled set enters the pool before the existing
  RF3 float prefix lifts it; OFF the pool + sort are unchanged. SCOPE: ehp lane only
  per the directive; the hps lane (RF2, DONE) left byte-identical (no risk to a DONE
  seam). DISCOVERED WORK (FUTURE, do-not-flip-blind): RF2's hps lane has the SAME
  purchasable-gate gap for Rakan's tabled 3121 - the inject_ids mechanism now EXISTS
  to fix it cheaply if a future RF wires the hps lane through it (logged in
  docs/LIVE_GAME_GATED_SYNC.md RF6 ledger). ENGINE bump 174 quoted pins / 157 .py
  (byte-replace, quoted-literal-only per feedback_engine_bump_quoted_literal_only,
  EOL-preserved via read_bytes/write_bytes); DS :8893 bounced (taskkill PID 14148 +
  schtasks /Run) -> /health 1.139.0 / patch 16.12.1 / 172 champs; ds_share_sync 362
  files --check "in sync"; DS + Share CHANGELOG prepended. TDD +12
  (test_survivability_item_credit_rf6.py): Rell Fimbulwinter injects+floats ON + NOT
  pooled OFF (the defining RF6-vs-RF3 injected-not-floated property), KSante
  already-pooled float unbroken, Malphite no-op, _filter_candidates inject-unit +
  mode-legality (3121 still excluded in ARENA map30=False) + None byte-identical,
  ENGINE pin 1.139.0. GATE (fresh this run): DS-dir agents/daemon_slayer/tests/ 7324
  passed / 1 skip / 1942 subtests exit 0 (+12 vs the 7312 RF5 baseline); RC tests/
  --ignore=tests/daemon_slayer 8333 passed / 2 skip / 109 subtests exit 0 (= RF5
  baseline, RF6 adds no RC test) - run AFTER the DS restart + Share sync (RF2
  sequencing lesson, no LiveFresh anchor flake); ruff clean (touched); py_compile OK;
  ASCII clean. INLINE sole orchestrator (R9 + coupled-seam clause - one cohesive lane:
  shared _filter_candidates param -> ehp ranker + shared ENGINE pin + Share mirror,
  dependency-ordered NOT disjoint files; the RF1-RF3 inline precedent); verifier
  SKIPPED per R7 (own single-thread, no untrusted slice - the RED probe + the dual
  full-suite + live :8893 /health + ds_share_sync --check ARE the independent verify).
  No frozen files. No blocking AskUserQuestion. NEXT: round-2 refill queue (RF1-RF6)
  DRAINED -> expect director NO_WORK or a new refill. Source: gemini director directive
  ops/loop/control/directive.md (RF6).
- 2026-06-17 RF5 (cycle 5, round-2 refill) DONE (e0f3da12) - test-hermeticity
  sibling sweep, Tier-1 test-hygiene (NO ENGINE bump / DS restart / Share sync /
  frozen / RC restart / backfill). GROUND-TRUTH SWEEP: a before/after snapshot of
  18 prod write-target artifacts across the FULL RC (8329) + DS (7312) suites =
  NO DELTA - the suite has NO active polluter (the authors already stub
  coach_trace.append, monkeypatch decision_detector _HEARTBEAT_PATH/etc to tmp,
  and pass explicit path= to the shadow + DS writers). DIRECT vector clean: 0
  repo-root-anchored (parent.parent / PROJECT_ROOT / __file__) writes in either
  test dir; the 3 prod-token direct candidates all tmp-rooted (test_metrics_cache
  TemporaryDirectory, test_p2w4_hw2_a _seed(tmp_path), test_loop_status_route
  CONTROLLER_LOG monkeypatched to tmp). INDIRECT vector = the real gap:
  coach_trace.append() + ds_calibration.log_ds_run() hardcode a module-global
  prod path (data/coach_trace.jsonl / data/ds_calibration.jsonl) with NO path
  parameter, so a caller has no tmp seam at all = latent polluters (vs the shadow
  writers, already netted by the conftest SHADOW_PATH fixture, and ds_coach_shadow
  / decision_detector / loop_controller, every caller of which already drives an
  explicit path= or its own monkeypatch). SHIPPED a preventive net (mirror the
  SHADOW_PATH precedent / item 386 + the OPEN2 CTL redirect): conftest autouse
  redirect_prod_write_paths_to_tmp redirects core.coach_trace._TRACE_FILE +
  core.ds_calibration._LOG_PATH to an ISOLATED tmp_path_factory dir (NOT the
  test's own tmp_path - an initial tmp_path subdir leaked a stray "prodwrite"
  entry into the cache-prune tests' tmp_path.iterdir(), caught by the full-suite
  gate -> fixed via tmp_path_factory.mktemp); + the directive-mandated suite-wide
  regression assert assert_prod_artifacts_unchanged (session-scoped, snapshots 12
  coaching/loop/game-only prod artifacts at session start, asserts size-unchanged
  at teardown; scoped OFF the live-daemon-touched set - health.json/logs/
  lessons_*/bridge_monitor excluded so it cannot flake on the live supervisor +
  bridge). ds_coach_shadow LEFT ALONE (already hermetic via explicit path=;
  redirecting its SHADOW_PATH would break test_shadow_path_default's data/-default
  assertion). TDD: +4 tests/test_hermeticity_prod_writes.py (RED-first: both
  globals resolve under prod data/ -> 2 failed; GREEN after the net: globals
  off-prod + the no-path writers land in tmp with prod byte-unchanged). GATE
  (fresh this run): RC tests/ --ignore=tests/daemon_slayer 8333 passed / 2 skip /
  109 subtests exit 0 (+4 vs the 8329 RF4 baseline, 0 regressions); DS-dir
  untouched (tests/conftest.py is a separate conftest scope, trust the 7312);
  ruff clean (touched); py_compile OK; ASCII clean. NO active offender found =
  CLEAN sweep + preventive net + the regression guard. INLINE sole orchestrator
  (R9 + the directive's "clean sweep may use a single agent" clause - 2 cohesive
  files); verifier SKIPPED per R7 (own single-thread; the before/after full-suite
  NO-DELTA snapshot + the RED->GREEN TDD ARE the independent verify); no blocking
  AskUserQuestion. No frozen files. NEXT: RF6 (RF4-surfaced ehp INJECT seam for
  Rell Fimbulwinter, not-pooled). Source: gemini director directive
  ops/loop/control/directive.md (RF5).
- 2026-06-17 RF4 (cycle 4, round-2 refill) DONE (a63c0d47) - residual re-run /
  loop-until-dry consolidation, AUDIT-only (no engine change; no ENGINE bump / DS
  restart / Share sync - new files live under ops/audit/ + tests/, NOT
  agents/daemon_slayer/). Regenerated report/dsp10_consolidated.{json,md} via
  run_consolidate.py = BYTE-IDENTICAL to the committed report (cross-eval data/ is
  static, the live :8893 is seam-OFF, and rewind_history.db is unchanged since the
  RF1-3 builds), and all 3 build_survivability_item_credit*.py --check stay green (the
  report-anchored tables did NOT drift - the regen is a safe no-op). NEW
  ops/audit/ds_perm_swarm/rf4_verify.py (mirror dsp10_pass2_verify) +
  tests/test_rf4_verify.py (+14 hermetic) + report/rf4_residual.{json,md}. CONFIRM
  RF1-3 LIFTED: in-process re-rank OFF vs ON (prefer_survivability_by_win=True per
  lane, level 13, anchor mode) = 11/12 RF-tabled champs RESOLVED - every RF1 hybrid
  champ (Briar/Darius/Gnar/JarvanIV/RekSai/Tryndamere/Udyr/Urgot/Yasuo) + RF2 Rakan +
  RF3 KSante float their buried survivability winners into the top-K under the
  survivability_score partition invariant. worst-N (40) classification: covered_rf1 9
  / covered_rf2 1 / covered_rf3 2 / cluster_a_deferred 4 (Zilean/Shaco/Kayle/Seraphine)
  / covered_dsp11 6 (Corki/Naafiri/Nilah/Pyke/Quinn/Senna) / ability_mage_lane 14
  (deferred DSV1 AP-DoT - Anivia/Ekko/Elise/Evelynn/Fizz/Heimerdinger/Katarina/KogMaw/
  Lillia/Malzahar/TwistedFate/Vex/Xerath/Zoe) / dps_burst_lane 2 (Caitlyn/Yunara,
  DSP2/DSP11's closed loop) / no_buried 1 (Zaahen) / thin_or_noise 1 (MasterYi).
  LOOP-UNTIL-DRY SATISFIED: 0 NEW survivability clusters in 1 pass. RESIDUAL (queued
  RF6): Rell ehp NOT-RESOLVED - its sole tabled id 3121 Fimbulwinter is NOT in Rell's
  ehp candidate pool (verified in_pool=False; a Winter's-Approach mana-line item the
  EHP _filter_candidates excludes), so RF3's FLOAT-only seam (reorders POOLED items by
  membership) is a no-op for it. RF3's "the EHP scorer ALREADY pools these resist/HP
  items" premise holds for KSante (3075 Thornmail / 6662 Iceborn both pooled+floated)
  but is FALSE for Rell+Fimbulwinter. The proper fix = an ehp-lane INJECT mode (RF2's
  hps shape: only_ids |= surv_ids before floating) = an engine seam change (ENGINE
  bump + DS restart + Share sync) - NOT a clean per-champ fix, so AUDIT-only this cycle
  + queued as RF6 (do-not-ship-engine-blind; a wrong float is worse than none). INLINE
  sole orchestrator (R9 - one cohesive audit module + its test, no disjoint slices);
  verifier SKIPPED per R7 (own single-thread, no untrusted slice - the live engine
  re-rank + the byte-identical regen + the 3 build --check ARE the independent verify).
  GATE (fresh this run): DS-dir agents/daemon_slayer/tests/ 7312 passed / 1 skip / 1942
  subtests exit 0 (unchanged - no DS edit); RC tests/ --ignore=tests/daemon_slayer 8329
  passed / 2 skip / 109 subtests exit 0 (+14 vs the 8315 RF3 baseline); ruff clean
  (touched); py_compile OK; ASCII clean. No frozen files. NEXT: RF5
  (test-hermeticity sweep) or RF6 (ehp inject seam). Source: gemini director directive
  ops/loop/control/directive.md (RF4).
- 2026-06-17 RF3 (cycle 3, round-2 refill) DONE (869656a0) - tank-template
  survivability item-credit seam, ENGINE 1.137.0 -> 1.138.0, DEFAULT-OFF.
  ROOT-CAUSE (verify-before-redo, distinct from RF1/RF2 AND from DSP6/DSP8): the
  ehp/tank scorer `rank_items_by_ehp` pools EVERY purchasable mode-legal terminal
  item (`_filter_candidates`, same pipeline as rank.py) and sorts PURELY by
  `delta_ehp` (or `ehp_per_1k_gold`) - blind to win-rate (ehp.py:2024-2027). The
  WIN-correlated mid-tier resist/HP items ARE pooled and DO earn a positive EHP
  delta, but the maximal raw-EHP stackers add MORE absolute EHP, so the win items
  sink below them. So RF3 is the SAME bury defect as RF1's hybrid lane (pooled +
  buried) -> a FLOAT, NOT RF2's inject (the enchanter_only pool EXCLUDES; the EHP
  scorer never excludes resist/HP). Verified distinct from DSP6 (enemy-runes) /
  DSP8 (burst-target): those alter the ENEMY damage-profile inputs feeding
  compute_ehp, shifting every item's EHP magnitude under the SAME context - the
  relative SELF order of mid-tier-resist vs max-EHP is unchanged, the win items
  stay buried under any enemy preset. RF3 is the SELF ranking-order float,
  orthogonal. DATA: the dsp10 ehp lane has exactly 2 champ rows - Rell + KSante.
  After the terminal + non-boot + survivability-name filter: Rell {Fimbulwinter
  3121}; KSante {Thornmail 3075, Iceborn Gauntlet 6662}. Giant's Belt 1011 +
  Negatron Cloak 1057 are COMPONENTS (build INTO terminals) -> dropped; Plated
  Steelcaps 3047 is BOOTS -> dropped (matches the operator's "burying core
  resist/HP items" framing - the actionable terminal set is the 3 above).
  SHIPPED: NEW `survivability_item_ids_tank()` loader in `survivability_credit.py`
  (separate file + cache; RF1 hybrid + RF2 enchanter tables byte-unaffected) +
  NEW `survivability_item_credit_tank.json` (builder
  `ops/audit/ds_perm_swarm/build_survivability_item_credit_tank.py`, scorer lane
  "ehp", shared survivability-name allowlist) + `EhpRankedItem.survivability_score`
  field + a DEFAULT-OFF `prefer_survivability_by_win` on `rank_items_by_ehp` that
  prefixes the sort key with the marker (`(survivability_score,) + base_key`,
  model order preserved within each tier) - byte-identical when OFF. TEST
  `test_survivability_item_credit_rf3.py` (10 tests incl the RF3-vs-RF2 defining
  assertion `test_floated_items_were_pooled_when_off`: surfaced ids ARE in the OFF
  ranking, proving float-not-inject). VERIFY: DS-dir 7312 passed / 1 skip / 1942
  subtests exit 0 (+10 vs RF2's 7302). RC tests/ 8307 passed after the DS :8893
  restart (1.137->1.138) cleared the phase8 live-engine pin + ds_share_sync cleared
  6 Share-anchor drifts; the pre-existing ROADMAP doc-size red was trimmed in the
  docs closeout. No frozen files. NEXT: RF4 (residual re-run / loop-until-dry
  consolidation after RF1-RF3) or RF5 (test-hermeticity sweep). Source: gemini
  director directive ops/loop/control/directive.md (RF3).
- 2026-06-17 RF2 (cycle 2, round-2 refill) DONE (ee826cdc) - enchanter-template
  survivability item-credit seam, ENGINE 1.136.0 -> 1.137.0, DEFAULT-OFF.
  ROOT-CAUSE (verify-before-redo, distinct from RF1): the hps/enchanter scorer
  `rank_items_by_hps` defaults `enchanter_only=True` -> the candidate pool is the curated
  enchanter-throughput registry (Helia / Ardent / Staff / Locket / Knight's Vow /
  Redemption). The HP/tank survivability items a tank-support enchanter wins on add ZERO
  HPS throughput, so they are not in the registry and are EXCLUDED from the pool entirely -
  not merely buried (RF1's hybrid scorer POOLS + buries; this one OMITS). So the RF2 seam
  must INJECT the tabled ids into the pool BEFORE floating them - the defining structural
  difference from RF1's float-only seam. SIBLING SWEEP: the dsp10 `worst[]` hps lane has
  exactly 3 champs - Zilean + Seraphine (both AP/mage buried winners = Cluster-A, EXCLUDED
  per directive) + Rakan (HP/tank). After excluding Cluster A + boots (Mercury's Treads),
  RAKAN IS THE ONLY enchanter-lane survivability defect in the report (no new cluster).
  SHIPPED: NEW `agents/daemon_slayer/survivability_item_credit_enchanter.json` (Rakan:
  Guardian's Horn 2051 / Warmog's 3083 / Heartsteel 3084 / Fimbulwinter 3121) + builder
  `ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py` (hps lane);
  `survivability_item_ids_enchanter()` added to `survivability_credit.py` (shared
  `_parse_table`, separate cache - RF1's hybrid table byte-unaffected); NEW
  `prefer_survivability_by_win` on `rank_items_by_hps` + `survivability_score` field on
  HpsRankedItem; pool-injection (`only_ids |= surv_ids`) + float prefix
  `(survivability_score,) + base_key` (byte-identical when off). SEAM-FIRST: live default-ON
  flip EXCLUDED -> `docs/LIVE_GAME_GATED_SYNC.md` section B + ledger (wires
  `server.py _route_rank_enchanter` / `core/daemon_slayer_client.rank_enchanter_for`); NOT
  flipped (do-not-flip-blind). ENGINE bump 88 quoted pins / 76 .py; DS :8893 bounced
  (taskkill PID 20148 + schtasks /Run) -> /health 1.137.0; ds_share_sync 359 --check "in
  sync"; DS + Share CHANGELOG prepended. TDD +9 (`test_survivability_item_credit_rf2.py`,
  RED-first: loader ids + RF1-table-unaffected + unknown empty; off byte-identical w/ score
  0.0; ON injects Heartsteel/Warmog's that OFF EXCLUDES; partition + membership +
  membership-not-throughput proof; untabled Soraka no-op; ENGINE pin 1.137.0). GATE (fresh
  this run): DS-dir 7302 passed / 1 skip / 1942 subtests exit 0 (+9 vs the 7293 RF1
  baseline); RC `tests/ --ignore=tests/daemon_slayer` green (the 8 LiveFresh anchor tests
  that transiently failed = a SEQUENCING artifact - the RC suite was launched BEFORE
  ds_share_sync + the DS restart finished, so `__init__.py`=1.137.0 but the Share ingest
  bundle/doc anchors + live /health still read 1.136.0 mid-window; re-run post-sync = 17
  passed exit 0). ruff + py_compile clean; build --check in sync. VERIFIER subagent =
  CONFIRM (all 7 claims: ENGINE pin, 3-file existence, loader fn, hps param/field, RF2 9
  passed, builder --check in sync, json content Rakan-only / no Cluster-A / no boots).
  INLINE sole orchestrator (R9 + coupled-seam: data -> loader -> hps ranker + shared ENGINE
  pin + Share mirror are dependency-ordered, NOT disjoint files; the DSP2-11/RF1 inline
  precedent) - BUT the verifier gate WAS run this cycle (instruction-5 explicit, operator
  away). No frozen files. NEXT: RF3 (tank-scorer itemization-order residual). Source: gemini
  director directive ops/loop/control/directive.md (RF2).
- 2026-06-17 RF1 (cycle 1, round-2 refill) DONE (faeaeb4a) - generic-bruiser-template
  survivability item-credit seam, ENGINE 1.135.0 -> 1.136.0, DEFAULT-OFF.
  ROOT-CAUSE (verify-before-redo CONFIRMED distinct from DSP2/DSP11): the 10
  directive-named champs all route the `hybrid` scorer (`rank_items_by_hybrid`),
  NOT the dps/burst rankers DSP2/DSP11 patched. Its sort key
  `hybrid_delta_pct = alpha*dps_pct + beta*ehp_pct` is alpha-weighted toward damage
  and the default mixed-damage target preset under-credits the pure resist/sustain
  axis, so the generic AD-DPS template (Void Immolation / BotRK / Trinity /
  Heartsteel / ER / Runaan's) tops it and the WIN-correlated survivability items
  sink. KEY DISTINCTION: DSP11's `prefer_kit_axis_by_win` floats kit-axis items
  GATED ON `delta_dps > 0`; survivability items add EHP not DPS so their hybrid
  delta is ~0 and a delta gate would NEVER surface them - so RF1 floats by
  WIN-TABLE MEMBERSHIP, the signal the damage-biased sort is blind to. DSP2 is
  ranged-marksman-only off-class (bruisers are not marksmen) -> never fired here.
  SHIPPED: NEW `agents/daemon_slayer/survivability_credit.py` loader +
  `survivability_item_credit.json` (built by
  `ops/audit/ds_perm_swarm/build_survivability_item_credit.py` from the report's
  hybrid lane); NEW `prefer_survivability_by_win` on `rank_items_by_hybrid` +
  `survivability_score` field on HybridRankedItem; float prefix
  `(survivability_score,) + base_key` (byte-identical when off). TABLE = 9 champs /
  28 items (Darius/Yasuo/Urgot/JarvanIV/Gnar/Udyr/Tryndamere/RekSai/Briar). The
  directive's 10th champ MasterYi is DELIBERATELY NOT tabled - the principled
  survivability-only filter found his buried winners are pure DPS (Infinity Edge,
  Guinsoo's Rageblade), a DSP11/within-axis matter, NOT a survivability burial
  (documented; a WRONG float is worse than none). Tryndamere reduces to 1 item
  (Titanic Hydra) for the same reason. SEAM-FIRST: live default-ON flip EXCLUDED ->
  appended to docs/LIVE_GAME_GATED_SYNC.md section B + ledger (wires
  `server.py _route_hybrid` / `daemon_slayer_client.hybrid_for` to pass the flag);
  NOT flipped (do-not-flip-blind). Cluster A (Zilean/Shaco/Kayle/Seraphine) NOT
  touched. ENGINE bump: 83 quoted pins / 75 .py; DS :8893 bounced (taskkill PID
  18816 + schtasks /Run) -> /health 1.136.0 confirmed; ds_share_sync 357 files
  --check "in sync"; DS + Share CHANGELOG prepended. TDD: +10 tests
  (test_survivability_item_credit_rf1.py, RED-first on the missing param/field/
  loader/ENGINE pin -> green: loader ids + MasterYi-absent + unknown empty; off
  byte-identical w/ survivability_score 0.0; on partitioned + FoN 4401 buried-off /
  floated-on; the membership-not-delta proof a floated item has lower
  hybrid_delta_pct than the off #1; untabled Garen no-op; ENGINE pin 1.136.0).
  GATE (fresh this run): DS-dir agents/daemon_slayer/tests/ 7293 passed / 1 skip /
  1942 subtests exit 0 (+10 vs the 7283 DSP11 baseline); full RC tests/
  --ignore=tests/daemon_slayer exit 0 (green; RF1 adds no RC test); ruff clean
  (touched); py_compile OK; build --check in sync; ASCII clean. INLINE sole
  orchestrator (R9 + coupled-seam clause - one cohesive lane: loader -> hybrid
  ranker + shared ENGINE pin + Share mirror, NOT disjoint files; the DSP2-11 inline
  precedent); verifier SKIPPED per R7 (own single-thread, no untrusted slice - the
  fresh dual full-suite + live :8893 probe + build --check IS the independent
  verify). No frozen files. NEXT: RF2 (enchanter-scorer survivability residual) or
  RF3 (tank-scorer). Source: gemini director directive
  ops/loop/control/directive.md (RF1).
- 2026-06-17 OPEN2 (cycle 19) DONE (b96f17e1) - hermetic loop_controller tests.
  test_p2w4_hw2_b.py git()/head() error-path tests monkeypatched subprocess.run
  to raise but NOT the module-global CTL, so loop_controller.git() except ->
  log() appended to the PROD ops/loop/control/controller.log every suite run
  (3 lines/run: "git rev-parse failed: Command 'git' timed out after 30 seconds"
  x2 + "...: git binary missing"; 684 accrued since 2026-06-13, 42 dated today).
  FIX: the lc fixture monkeypatches mod.CTL -> tmp_path/control after reload
  (mirror conftest SHADOW_PATH redirect, item 386). +2 hermeticity regression
  tests (CTL off-prod; prod controller.log size unchanged across error-path
  git()). Sibling sweep: done_sentinel/claude_stub head() degrade to "" with NO
  log() call - never polluters; the 5 other loop-touching test files pass
  explicit tmp paths. RC suite 8315 passed / 2 skip / 0 fail; full re-run added
  0 new prod-log lines (today count held at 42).
  NEW WORK (FUTURE, operator-gated): the historic ~684-line git-fail residue in
  controller.log is left intact (CLAUDE.md *.log-immutable bucket;
  feedback_no_history_rewrite). A surgical recovery (strip the 2 exact
  test-signature lines, preserve every real loop event) needs operator OK before
  rewriting a protected operational log.
- 2026-06-17 OPEN1 (cycle 18) DONE (5445502e) - unify RC LCU page-name prefix.
  VERIFY-BEFORE-REDO: the directive's "4 divergent templates" premise is STALE.
  All 3 NON-frozen producers already emit the canonical "RC: " prefix -
  loadout_resolver.py:360/373 (item 178), routes_loadout.py:189/201 (item 213
  removed "RC Experimental - "), routes_sr_draft.py:59/75 (born "RC: "), the
  agent default gamepc_lcu_agent.py:1000/1158 "RC: Auto", and
  lcu_rune_writer.RuneWriter.PAGE_PREFIX "RC: ". The ONLY remaining divergence
  is the FROZEN lcu/lcu_client.py:405 _RC_PAGE_PREFIX = "RC - " - SKIPPED per
  directive (frozen, self-contained internal constant, no non-frozen seam to
  route around) and FUNCTIONALLY HARMLESS: the gamepc_lcu_agent delete filter
  (L1183, ("RC ","RC:","RC-")) still reclaims an "RC - " page (name[:3]=="RC ").
  Root of the stale premise = the Item-210 comment block at
  gamepc_lcu_agent.py:1164 which still claimed routes_loadout.py emits
  "RC Experimental - " (removed item 213). SHIPPED: (1) NEW
  tests/test_rc_page_name_prefix_unified.py (+6) - pins the previously-UNPINNED
  cross-producer contract ("RC: " on every non-frozen producer +
  RuneWriter.PAGE_PREFIX; legacy "RC Experimental"/"RC - " absent from the 3
  producers; the 3-prefix wipe filter never narrowed back to "RC: " only =
  item-210 max-owned-pages incident guard; frozen lcu_client.py holdout
  documented); (2) corrected the stale comment to the now-unified reality.
  Tier-1 (test) + Tier-0 (comment); no engine/schema/ENGINE/web -> NO DS
  restart / Share sync / UI ritual / full dual suite (R5). GATE (fresh this
  run): page-name blast radius (the new guard + test_apply_runes_page_filter +
  test_sr_draft_apply + test_champ_select_item213 + test_loadout_user_builds_
  merge + test_csv_rune_push_on_selection_change) 78 passed exit 0; new guard
  alone 6 passed; ASCII hygiene (smart-quote/mojibake/u2500) 12 passed; ruff
  clean (touched files); py_compile OK. INLINE sole orchestrator (R9 - 1 new
  test + 1 comment edit = 2 cohesive files; parallel worktrees add only
  overhead + merge contention; the DSP/LGS inline precedent); verifier SKIPPED
  per R7 (own single-thread, no untrusted slice - the cross-producer grep +
  fresh blast-radius run IS the independent verify). No frozen files edited
  (lcu_client.py skipped). No new OPEN work surfaced. NEXT: OPEN2 (test
  control_dir leak). Source: gemini director directive
  ops/loop/control/directive.md (OPEN1).

- 2026-06-17 LGS1 (cycle 17) DONE - live-sync audit, pure docs (Tier-0, ZERO .py edits -> no ENGINE bump
  / DS restart / Share sync / py_compile). Audited the three sources the directive names. (1) rank.py
  default-OFF seams = exactly TWO: `exempt_offclass_by_win` (DSP2, L522) + `prefer_kit_axis_by_win` (DSP11,
  L523); both already had an accurately-located docs/LIVE_GAME_GATED_SYNC.md section-B row. The DSV2/3/4 +
  DSP8 seams the docs colloquially called "rank.py flips" actually live in `agents/daemon_slayer/burst.py`
  (`rank_items_by_burst` / `compute_burst_damage`), DSP4 `score_completion_runes` in `burst.py`+`combo.py`
  (grep-verified) -> FIXED the sync-doc DSV row + the EXCLUDED meta-bullet to name the burst scorer. (2)
  EXCLUDED section: every bullet maps to a sync-doc row EXCEPT "live caster-stat producer for /anti-tank
  P3.2 + live survivability scorer (egg-resist/Orianna E)" -> ADDED a section-B row naming
  `antitank.py effective_magnitude` (P3.2 ap/ad_ratio caster-stat scaling, needs a live AbilitiesSnapshot
  producer) + `ehp.py compute_ehp(external_resist_*)` (Orianna-E/Braum-W/Taric-W ally-resist producer;
  egg-resist already default-ON item 321). (3) ROADMAP open-tails: the live-gated tails (Phase-D flag flips,
  champ-select Haiku flip, vision self-heal, st-* adaptation producers, augment OCR) are all already in the
  sync doc; no missing row. NET: 2 doc fixes (DSV location + new anti-tank row) + a live-flip ledger entry;
  the sync list is now COMPLETE with every row naming an accurate flip location. No new OPEN work
  (OPEN1/OPEN2 remain). INLINE sole orchestrator (R9 - a docs audit + 4 .md edits, no disjoint code slices,
  so parallel worktrees add only overhead); verifier SKIPPED per R7 (own single-thread, no untrusted slice;
  the grep cross-checks ARE the independent verify). No frozen files. GATE: doc-hygiene suite (smart-quote /
  mojibake / u2500) + ASCII clean; full dual suite skipped per R5 (Tier-0 docs, zero .py). NEXT: OPEN1
  (page-name unify) or OPEN2 (test control_dir leak). Source: gemini director directive
  ops/loop/control/directive.md (LGS1).

- 2026-06-17 HZU1 (cycle 16) DONE - CODE was item 457, this cycle is the MINE-VERIFY + laning/flip
  doc-prep + status closeout. The directive's first two clauses (deepen
  `tools/replay_build_order_validate.py` to per-item bought-vs-win granularity + mine the 4627
  lean-ambiguous rows for which items carry signal) were ALREADY SHIPPED at `a30cbba4` (item 457,
  2026-06-16, ancestor of HEAD): `item_outcomes` + `_per_item_report` + the `per_item` accumulator +
  `_PER_ITEM_MIN_N=50` carrier rail + the per-ITEM print block, with +7 tests. Per CLAUDE.md
  verify-before-redo / do-not-re-litigate, this cycle did NOT re-implement; it RE-RAN the gate fresh on
  the live `data/rewind_history.db` (`--mode sr --limit 0`) as independent ground truth and reproduced
  item 457 byte-for-byte: 651 SR matches / 6510 rows, decisive=1832 / ambiguous=4627 (the named 4627) /
  uncovered_champ=51. HEADLINE (lean level): FOLLOWED 56.4% (n=766) vs NOT 54.1% (n=1066) = +2.3pp,
  95%=[-2.3,+6.9], flip_ready=False (a coin flip, dilution-consistent). COMPLETION-TIMING also flat
  (fast<=20.82min 56.1% vs slow 56.7%). ITEM-GRANULARITY mining of the 4627 ambiguous rows = 1/51 clean
  carriers: Infinity Edge anti_squishy +12.6pp (95%=[+0.7,+24.4], n=90 bought); Serylda's Grudge
  +11.3pp just misses (lo=-0.9). VERDICT: HOLD - the lean recommendation carries no flippable
  whole-build signal at this corpus and one IE carrier is too thin; the build coach stays on Haiku
  (interim floor) until a larger replay corpus clears the rail and the chip is eyeballed live. DOC-PREP
  (the 3rd clause): appended both HZ flip rows to `docs/LIVE_GAME_GATED_SYNC.md` section C - the Lane-A
  laning-agreement read (`tools/hz_shadow_report.py`, confirmed present; item 456) and the Lane-B
  build-order item-level flip (the gate as its rail, current HOLD numbers, re-run-as-corpus-grows
  instruction) - plus a live-flip ledger entry; they are the cycle-52 HZ precompute->Haiku flip PAIR,
  both HOLD. Tier-0 (only `.md` touched - LIVE_GAME_GATED_SYNC + this plan + LEDGER; ZERO `.py` edits ->
  no ENGINE bump / DS restart / Share sync / py_compile). GATE: the relevant-module suite
  `tests/test_replay_build_order_validate.py` + `_robustness` 65 passed exit 0 (the shipped tool still
  green) + the live gate re-run as the ground-truth check; full dual suite skipped per R5 (Tier-0 docs).
  INLINE sole orchestrator (R9 - docs + a re-run, no disjoint files); verifier SKIPPED per R7 (own
  single-thread, no untrusted slice - the gate re-run IS the independent verify). No frozen files. NEXT:
  LGS1 (live-sync audit) or OPEN1/OPEN2. Source: gemini director directive
  ops/loop/control/directive.md (HZU1).

- 2026-06-17 DSP10 PASS 2 (`e1c996d0`) DONE - SWARM DRY. Loop-until-dry pass 2:
  re-ran the cross-eval harness at live ENGINE 1.135.0 (run_all 172/172 OK,
  byte-identical to pass 1 -> DSP11 did NOT regress the default-path rankings;
  run_consolidate report stable) then verified the DSP11 prefer_kit_axis_by_win
  seam. NEW ops/audit/ds_perm_swarm/dsp10_pass2_verify.py (audit-only; nothing
  under agents/daemon_slayer touched -> NO ENGINE bump / DS restart / Share sync,
  the DSP10-pass1 audit-only precedent). (1) verify_resolved re-ranks each
  DSP11-tabled champ seam OFF vs ON IN-PROCESS (the live :8893 server is
  seam-OFF, so the cross-eval data/ files are the default-path snapshot and the
  seam-ON ranking must be exercised by calling rank_items / rank_items_by_burst
  directly, the DSP11 test path): 7/7 RESOLVED - Pyke->Axiom/Youmuu's,
  Naafiri->Collector/Hubris, Nilah->IE/Navori/Shieldbow/LDR, Quinn->IE/Statikk/
  Collector/MR/LDR, Senna->Black Cleaver, Corki->Trinity/Collector,
  Ezreal->ER + Trinity un-stripped; each floats its buried kit-axis winners into
  the top-K (partition invariant holds). (2) classify_worst (pure, hermetic)
  buckets the consolidated worst-40: a NEW B2 defect requires an untabled,
  non-Cluster-A dps/burst champ burying a COHERENT kit-axis set (>=2 axis items
  AND the strongest buried winner's lift >= 5.0, the magnitude floor of the real
  DSP11-tabled defects: Pyke Opportunity +6.1, Nilah Immortal Shieldbow +15.8,
  Senna Black Cleaver +11.5, Quinn IE +6.5). RESULT: 0 new B2 defects -> DRY.
  The divergent tail is entirely: 6 covered_dsp11 + 5 cluster_a_deferred
  (Zilean/Shaco/Kayle/Seraphine/Udyr - operator-gated, do-NOT-auto-flip) + 26
  other_scorer (AP-mage / bruiser / tank lanes - the DSV1 AP-DoT + archetype
  routing work, not B2) + 1 no_buried (Zaahen) + 2 within_axis_noise
  (Caitlyn/Yunara - pure ranged crit marksmen whose model already targets crit
  and only differ on WHICH crit item by a marginal +3.4/thin-n lift = the
  DSP9-falsified G6 cost-axis residual, the DSP11 "pure crit ADCs untouched"
  rationale). report/dsp10_pass2.{json,md} written. The min_axis_hits=2 count
  alone first false-flagged Caitlyn (Collector is a cross-axis generic item +
  RFC at ~baseline); the +5.0 strongest-lift floor (TDD'd) cleanly separates a
  true off-axis burial from within-axis cost noise. TDD: tests/test_dsp10_pass2.py
  +9 (RED-first on the missing module -> green: covered / cluster-A / no-buried /
  other-scorer gating, single-hit + marginal-2-hit noise, strong-coherent-set
  flagged not-dry on dps + burst, dry-when-only-benign). GATE (fresh this run):
  DS-dir agents/daemon_slayer/tests/ 7283 passed / 1 skip / 1942 subtests exit 0
  (unchanged vs DSP11 = no DS regression, no DS source touched); full RC tests/
  --ignore=tests/daemon_slayer 8307 passed / 2 skip / 109 subtests exit 0 (+9 =
  the new pass-2 hermetic tests, 0 regressions); ruff All checks passed
  (repo-wide); py_compile OK; ds_share_sync --check "in sync" (no DS drift);
  ASCII/LF clean. INLINE sole orchestrator (R9 - one cohesive audit module + its
  test; a dependency chain (probe re-run -> in-process seam re-rank -> classify ->
  report), not disjoint files, so parallel worktrees add only overhead; the
  DSP1-11 inline precedent + the directive's "trivial one-file audit item may use
  a single agent" clause); verifier subagent SKIPPED per R7 (own single-thread
  edit, no untrusted slice) - fresh in-thread dual full-suite + live in-process
  seam re-rank substituted. No frozen files touched. DSP10 loop-until-dry
  contract SATISFIED (pass 1 surfaced DSP11; pass 2 dry). NEXT: HZU1 (item-level
  build-order Haiku-flip gate) or LGS1/OPEN1/OPEN2. Source: gemini director
  directive ops/loop/control/directive.md (DSP10 pass 2).

- 2026-06-17 DSP11 (`0c2b88e5`) DONE. Cluster-B2 kit-axis item-credit seam (ENGINE
  1.134.0 -> 1.135.0, DEFAULT-OFF). ROOT-CAUSE (the directive's candidate-vs-credit
  question, confirmed live): TWO failure modes, BOTH leaving caster-ADC /
  lethality-assassin / crit-melee kits on a generic AD template. (1) CREDIT MODEL
  (dominant): compute_dps / compute_burst_damage model a generic AA / single-combo
  rotation that cannot encode a kit's win-axis (Pyke R executes scale with
  lethality, Nilah doubles crit, Ezreal Q + Manamune ramp), so the items the player
  base WINS on rank far below the generic on-hit/sheen template even vs a squishy
  target (live probe @ squishy preset: Pyke Youmuu's #8 / Opportunity absent; Nilah
  IE #12 / Navori #16 / Shieldbow #26; Ezreal Manamune #27) - the DSV3/DSP8
  squishy/target-preset seams do NOT fix this (the ad_squishy cross-eval bucket still
  buries them). (2) CANDIDATE APPLICABILITY (Ezreal only): Trinity Force is
  hard-stripped by the item-213 ranged-marksman off-class deny set (DSP2's
  exempt_offclass_by_win addressed it but is default-OFF + not the float). FIX: NEW
  default-OFF prefer_kit_axis_by_win on rank_items (dps) + rank_items_by_burst
  (burst), driven by a WIN-anchored kit_axis_item_credit.json table (7 champs / 21
  terminal items: Pyke/Naafiri/Senna lethality, Nilah/Quinn crit, Ezreal/Corki
  manamune) built by ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py from the
  DSP10 buried-winner report + rewind (Ezreal seeded direct - he fell outside the
  worst-40 anchor window). When ON for a tabled champ: (a) the dps ranker un-strips
  the champ's kit-axis items from the off-class deny set (Ezreal Trinity becomes a
  candidate), and (b) both rankers float every POSITIVE-delta kit-axis item above the
  generic template via a (kit_axis_score,) + base_key sort prefix (model order
  preserved within tiers; a regression item is NOT floated). NEW kit_axis_credit.py
  loader + kit_axis_score field on RankedItem/BurstRankedItem. LIVE-VERIFIED (seam
  ON): Pyke -> Axiom/Youmuu's #1-2, Nilah -> IE/Navori/Shieldbow/LDR #1-4, Ezreal ->
  ER/Trinity #1-2; untabled Caitlyn byte-identical. SEAM-FIRST (EXCLUDED): the live
  default-ON flip (wire the scorer-dispatch to pass the flag) is appended to
  docs/LIVE_GAME_GATED_SYNC.md section B + ledger; NOT flipped (do-not-flip-blind).
  Cluster A (Zilean/Shaco/Kayle/Seraphine AP-in-ARAM) is a SEPARATE operator-gated
  routing decision, deliberately NOT in this table (per the DSP10 Gemini PART C
  verdict). ENGINE bump: 82 quoted pins / 74 .py; DS :8893 bounced (taskkill PID
  19964 + schtasks /Run) -> /health 1.135.0 confirmed; ds_share_sync 354 files
  --check "in sync"; DS + Share CHANGELOG prepended. TDD: test_kit_axis_item_credit_
  dsp11.py +11 (RED-first on the missing params/loader/ENGINE pin -> green: loader
  ids/names + unknown/blank empty; dps + burst off byte-identical w/ kit_axis_score
  0.0; on partitions surfaced-above-rest; Nilah IE buried-off / floated-on; untabled
  Caitlyn no-op; Ezreal Trinity un-stripped; ENGINE pin 1.135.0). GATE (fresh this
  run): DS-dir agents/daemon_slayer/tests/ 7283 passed / 1 skip / 1942 subtests exit
  0 (+11 vs the 7272 DSP10 baseline); full RC tests/ --ignore=tests/daemon_slayer
  8297 passed / 2 skip / 109 subtests + 1 transient (test_live_three_profiles hit
  :8893 mid-DS-bounce -> 2 profiles not 3; GREEN on a fresh re-run once :8893 settled
  at 1.135.0, 0 real regressions = the default-OFF byte-identical proof); ruff All
  checks passed; py_compile OK; ASCII/LF clean.
  No web/* touched -> no UI ritual (R5/R11). INLINE sole orchestrator (R9 + the
  directive's coupled-seam clause - ONE cohesive seam: a shared kit_axis_credit.py
  loader imported by BOTH rank.py + burst.py, a shared kit_axis_score field pattern,
  and the shared ENGINE pin + Share mirror; the candidate slices are NOT disjoint
  (loader -> both scorers dependency + shared __init__ ENGINE pin + Share would
  merge-contend), so parallel worktrees add only overhead - the DSP2-10 precedent);
  verifier subagent SKIPPED per R7 (own single-thread edit, no untrusted slice) -
  fresh in-thread dual full-suite + live :8893 probe + Share --check substituted. No
  frozen files touched. NEXT: DSP10 loop-until-dry pass 2 (re-run the cross-eval with
  DSP11 ON, confirm no new B2-class defect) or HZU1. Source: gemini director
  directive ops/loop/control/directive.md (DSP11).

- 2026-06-17 DSP10 (475, 7b96328f) WIP - pass 1 DONE. Full permutation
  cross-eval re-run + the smallest-benefit harness-validity fix + the
  consolidated mismatch report. Audit tooling only - NO agents/daemon_slayer
  touched -> NO ENGINE bump / DS restart / Share sync / new
  LIVE_GAME_GATED_SYNC flip. RE-RUN: regenerated all 172
  ops/audit/ds_cross_eval/data/<Champ>.json at live ENGINE 1.134.0 via
  tools/ds_cross_eval/run_all.py (172 OK 0 FAIL 22.3s); 171/172 byte-identical
  (the data was already current across the DSP2-8 bumps) - ONLY Aphelios.json
  drifted, which both proves DSP2-8 did NOT regress the cross-eval rankings and
  catches the lone drift. SMALLEST-BENEFIT FIX (the one ship-this-cycle find):
  the DSP1 WIN-anchor harness scored each champ's ARAM-anchored comp_grid
  against BOTH ARAM and SR win-data, but 171/172 champs anchor ARAM (only
  Zaahen anchors SR), so the whole SR column was apples-to-oranges (an
  ARAM-built ranking judged on SR outcomes) - the worst divergent row Ezreal SR
  -39.13 (mean_wr 0.0) was pure cross-mode artifact. perm_score.build_report
  gains anchor_match_only (default True): only the anchor-matched mode scores.
  Scored champ-modes 295 -> 162; mean_lift_weighted +0.1651 (mixed, polluted)
  -> -0.2825 (the honest ARAM-only signal). DELIVERABLE: NEW
  ops/audit/ds_perm_swarm/consolidate.py + run_consolidate.py -> the DSP10
  consolidated mismatch report (report/dsp10_consolidated.{json,md}) joining
  DS-favored top-K (union across the target-preset buckets, with live rewind
  n/wr) vs the above-baseline empirical winners DS buries, for the worst-40
  anchor-matched champ-modes. TRIAGE of the now-VALID divergent tail: (A)
  Cluster A operator-gated ARAM off-meta archetype - Zilean -32.8 (enchanter
  routed, wins AP-mage Shadowflame/Rabadon's/Luden's), Shaco -29.2 (assassin,
  wins AP Blackfire/Liandry), Kayle -16.3 (mage, wins on-hit BotRK/Terminus),
  Seraphine -15.0, Udyr -21.7 (bruiser, wins tank Spirit Visage/Jak'Sho) -
  SYSTEMIC_FINDINGS says do-NOT-auto-flip (the cs_archetype_picks override
  mechanism exists but WHICH off-meta builds to chase is an operator call); (B)
  Cluster B2 kit-axis item-crediting - Pyke -22.0 (wins lethality
  Opportunity/Youmuu's), Nilah -20.9 (wins crit Immortal Shieldbow 70%/IE/
  Navori), Ezreal (wins Manamune/Trinity) - a REAL engine defect needing a
  dedicated root-cause pass; (C) NOT-defects - TwistedFate/Katarina (AP axis
  CORRECT, the negative lift is component + cost noise), Rakan (the known ARAM
  HP-stack-on-enchanter not-defect), Zaahen n=7 thin; (D) cost-axis = the
  DSP9-falsified G6 residual (Gemini-verdicted BACKLOG). NO ship-blind-safe
  per-champ ENGINE fix this cycle (Cluster A is do-not-auto-flip; Cluster B2
  needs root-cause-first - both would violate do-not-flip-blind if crammed in
  blind). GEMINI PART C (synchronous gemini_ask,
  gemini_io/answer_20260617-070708.md): verdict (a) - dedicate DSP11 to the
  Cluster B2 kit-axis fix; Cluster A stays a deferred operator policy decision.
  NEW DSP11 OPEN row seeded. GATE (fresh this run): DS-dir
  agents/daemon_slayer/tests/ 7272 passed / 1 skip / 1942 subtests exit 0
  (unchanged - no DS source touched); full RC tests/ --ignore=tests/daemon_slayer
  8297 passed / 2 skip / 109 subtests (+4 = the anchor-match + consolidate
  hermetic tests; the lone failure was the pre-existing ROADMAP.md 82540 > 81920
  size budget, FIXED by relocating 3 shipped prior-run cycle entries to
  docs/ROADMAP_HISTORY.md -> 78351); ruff All checks passed; py_compile OK;
  ASCII/LF clean. INLINE sole orchestrator (R9 - 4 cohesive audit-tooling files
  + 2 tests; no disjoint multi-file engine work this cycle, so the per-champ
  worktree swarm is deferred to DSP11 where it applies; the DSP1-9 inline
  precedent); verifier SKIPPED per R7 (own single-thread edit, no untrusted
  slice) - fresh dual-suite substituted. loop-until-dry: pass 1 surfaced DSP11
  (NOT a dry pass). NEXT (DSP11): Cluster B2 kit-axis fix, root-cause-first.
  Source: gemini director directive ops/loop/control/directive.md (DSP10).

- 2026-06-17 DSP9 (474, 20d9f395) DONE. lolmath parity fold - G7 comp-aware
  harness built; CLEAN no-engine-change finding (NO ENGINE bump, NO Share sync,
  NO DS restart - nothing under agents/daemon_slayer/** touched; the DSP4-8 seams
  already exist, this is offline AUDIT tooling). DELIVERABLE
  ops/audit/lolmath_ds_sweep/g7_comp_harness.py: pure helpers (LOLMATH_COMP /
  classify_comp / resolve_comp_target [blends the DSP8 _TARGET_PRESETS per comp
  member] / score_overlap, +13 hermetic tests tests/test_lolmath_g7_comp_harness.py)
  + a standalone probe (g2/g5 precedent, NOT in pytest) writing g7_comp_parity.json.
  THE G7 ASK ("feed DS the SAME 5-champ comp to compare like-for-like instead of
  static mixed"): lolmath's fixed comp = Jayce/Sejuani/Annie/Lucian/Thresh =
  4 squishy + 1 tank -> classify_comp -> burst_heavy. The probe scores the
  lolmath-vs-DS item overlap against ALL FOUR DS comp-archetype variants (so the
  conclusion is not hostage to one classification). RESULT @ ENGINE 1.123.0
  build_orders (the live default-OFF static tables; live engine 1.134.0), 172
  covered champs - mean item-overlap of lolmath-ULTIMATE vs each DS variant:
  frontline_heavy 2.00 (BEST) / poke 1.86 / mixed 1.84 (the gen_md baseline) /
  burst_heavy 1.49 (the comp-match). So comp-matching to burst_heavy tracks
  lolmath-ULTIMATE WORST (-0.349 vs the mixed baseline); the variant that best
  tracks it is the anti-tank frontline_heavy. ROOT: lolmath-ULTIMATE is the
  cost-IGNORING global-optimum raw-stat pile, which aligns with the pricier-item /
  penetration-heavy variants regardless of the enemy comp's squishiness - so the
  residual is the G6 COST-MODEL axis, NOT comp-awareness (and NOT runes). This
  FALSIFIES the G7 "comp-matching closes the gap" hypothesis with data and
  REINFORCES the G6 finding. G6 GEMINI-CONSULT (PART C synchronous,
  gemini_io/answer_20260617-062844.md): verdict (c) leave FUTURE/BACKLOG - "a raw
  gold cost model conflicts with DS's empirical-WIN-data anchoring + violates the
  do-not-blind-build directive"; logged to BACKLOG, NOT built. G3 (runes) stale
  text in gen_md.py corrected: DS now SCORES self-rune procs via the DSP4
  rune_procs/core/rune_wpa.py completion-rune seam (DEFAULT-OFF); only the full
  rune-PAGE EMITTER (a champ-select surface) remains FUTURE/live - NOT a
  build-order parity item. gen_md.py G3/G6/G7 work-item text updated to reflect
  DSP4-8 + this finding. NO new default-OFF engine seam shipped (audit-only) ->
  NO new docs/LIVE_GAME_GATED_SYNC.md FLIP row; a ledger note records the CLEAN
  outcome + that the existing DSP8 target_preset live flip will NOT improve
  lolmath-ULTIMATE parity (it is a comp axis; the residual is the cost axis).
  GATE (fresh this run): DS-dir agents/daemon_slayer/tests/ 7272 passed / 1 skip /
  1942 subtests exit 0 (unchanged vs the DSP8 baseline = no DS regression, as
  expected with no DS source touched); full RC tests/ --ignore=tests/daemon_slayer
  8294 passed / 2 skip / 109 subtests exit 0 (+13 = the new G7 hermetic tests, 0
  regressions); ruff All checks passed (repo-wide); py_compile OK; ds_share_sync
  --check "in sync" (no DS drift); ASCII/LF clean. INLINE sole orchestrator (R9 -
  2 core files g7_comp_harness.py + its test + gen_md.py edit + docs; an audit
  harness is one cohesive slice, parallel worktrees would only add merge overhead;
  the DSP1-8 inline precedent + the directive's "trivial one-file items may use a
  single agent" clause); verifier subagent SKIPPED per R7 (own single-thread edit,
  no untrusted slice) - fresh in-thread dual full-suite substituted. No frozen
  files touched. NEXT (DSP10): full permutation cross-eval re-run, all seams
  harness-ON, WIN-anchored, loop-until-dry. Source: gemini director directive
  ops/loop/control/directive.md (DSP9).

- 2026-06-17 DSP8 REGRESS-recheck (director directive) -> FALSE POSITIVE, no-op,
  no fix. The gemini auditor's VERDICT: REGRESS claimed a clipboard paste artifact
  ("67 @agents\agent2_backend\reports\20260428-223511-apply-p-audit4-m03-task-log-
  redact.md @ L11") at agents/daemon_slayer/tests/test_burst_target_preset_dsp8.py
  line 50. Ground-truth re-verify (CLAUDE.md Verify-before-declaring-broken, same
  class as the 466 + 469 auditor false positives this run): the artifact is ABSENT
  on 5 independent checks - (1) the full 192-line test file reads clean, L50 = the
  bruiser preset dict row '"bruiser": (90.0, 55.0),'; (2) the Share/src mirror grep
  for the artifact is empty; (3) git show HEAD:...test_burst_target_preset_dsp8.py
  has no artifact (committed clean at f03dfc25, its only commit); (4) git status
  working tree clean; (5) a signature sweep (".md @ L" / "@agents\" / "reports\2026"
  / "task-log-redact") over BOTH agents/daemon_slayer/tests + Share/src/.../tests
  returns 0 hits. The "task-log-redact" string lives ONLY in its legitimate
  2026-04-28 agent6/agent2 report .md files, never pasted into a test - the auditor
  conflated that real report's repo presence with a test-file paste. No file edit,
  no Share resync (no DS source touched), no ENGINE change. DS suite re-run GREEN:
  7272 passed / 1 skipped / 1942 subtests, exit 0 (test_burst_target_preset_dsp8.py
  among them). ROADMAP line 12 already records DSP8 DONE @ f03dfc25 NEXT DSP9 - no
  ROADMAP/LEDGER state change. Session status UNCHANGED (per directive). NEXT
  director: DSP8 is verified shipped-clean - do NOT re-issue this REGRESS; advance
  to the next OPEN item (DSP9 lolmath parity fold).

- 2026-06-17 DSP8 (473, f03dfc25) DONE. Enemy-comp target-preset seam (ENGINE
  1.133.0 -> 1.134.0). Generalizes the DSV3 assume_squishy_target binary armor
  assumption into four named enemy-comp target presets on rank_items_by_burst,
  DEFAULT-OFF. ROOT (plan DSP8 + the enemy-team permutation bucket): DSV3 added a
  single binary squishy-carry armor curve (assume_squishy_target -> 22 + 4.5/lvl,
  armor-only); the enemy comp's actual defensive shape - a tank's stacked
  armor+MR, a high-CC enchanter's MR, a bruiser's mixed resists - was an unmodeled
  permutation, so the assassin item ranking valued lethality vs raw AD vs magic
  pen against only one (squishy) target. FIX (burst.py, the DSV1-4 opt-in-seam
  precedent): NEW _TARGET_PRESETS table (squishy / bruiser / tank / high_cc ->
  (armor_base, armor_per_level, mr_base, mr_per_level)) + _assumed_target_resists(
  preset, level) -> (armor, MR) on the base + per_level*(level-1) curve +
  _resolve_target_preset. rank_items_by_burst gains target_preset (default None):
  when a preset is active and the caller did not pin a positive resist, the
  preset's (armor, MR) is substituted for BOTH the baseline and every candidate,
  so lethality / flat pen bites a tank's armor and magic pen bites a high-CC
  enchanter's MR; the result's existing target_armor/target_mr fields carry the
  substituted resists + a new note surfaces the active preset. profiles at L11:
  squishy 67/35, bruiser 90/55, tank 180/110, high_cc 75/70 - tank tankiest +
  squishy squishiest on both axes; the squishy preset REUSES the DSV3
  _SQUISHY_TARGET_BASE_ARMOR / _PER_LEVEL constants so target_preset="squishy" and
  assume_squishy_target=True agree on armor (the preset adds the representative MR
  30 + 0.5/lvl the binary seam omitted). MAGNITUDE: representative role-norm
  resist curves (NOT a Meraki per-champion lookup - the target is an ABSTRACT comp
  archetype, not a named champion); the values model a typical mid-game comp and
  re-anchor to the live patch at the operator flip. BACK-COMPAT: assume_squishy_
  target is UNCHANGED - still ARMOR-only (the MR substitution requires an explicit
  target_preset), so the DSV3 ranking + its 7 tests stay byte-identical; an
  explicit positive target_armor / target_mr always wins; compute_burst_damage is
  untouched (it takes explicit resists). DEFAULT-OFF: no live scorer passes
  target_preset, so /rank-assassin + compute_burst are byte-identical to pre-DSP8.
  SEAM-FIRST (EXCLUDED, do-not-flip-blind): the live default flip (wire the burst /
  /rank-assassin scorer to a target_preset derived from the live enemy comp)
  replaces the generic DSP8 placeholder with a specific DSP8 row in
  docs/LIVE_GAME_GATED_SYNC.md section B, NOT wired live. ENGINE bump (directive-
  mandated; burst.py under agents/daemon_slayer/** forces a Share sync): 1.133.0 ->
  1.134.0, 81 quoted-literal pins byte-replaced across 73 .py (__init__.py + 72 DS
  test files; UNQUOTED docstring/changelog refs untouched per
  feedback_engine_bump_quoted_literal_only); DS :8893 bounced (taskkill PID 19232 +
  schtasks /Run /TN RC-DaemonSlayer) -> /health engine_version 1.134.0 confirmed;
  ds_share_sync.py -> 351 files, --check "Share/src + doc anchors + lolmath_ingest
  in sync"; DS + Share CHANGELOG entries prepended (the authored semantic half the
  auto-rewrite cannot do; a burst.py seam is a CHANGELOG-only record like DSV1-4 -
  it extends an existing module, so NO new Share/docs/02 subsection, UNLIKE the
  DSP5/DSP6 new-module seams). TDD: agents/daemon_slayer/tests/
  test_burst_target_preset_dsp8.py +16 tests, RED-first (ImportError on
  _TARGET_PRESETS / _assumed_target_resists) -> green (4 presets registered;
  squishy armor matches the DSV3 curve at L1/11/18; the four L11 anchor profiles;
  monotonic-in-level both axes; tank tankiest + squishy squishiest; unknown preset
  + out-of-range level raise; ranker default-off zero-target; assume_squishy_target
  back-compat MR stays 0.0; each preset substitutes its profile; explicit targets
  not overridden; tank mitigates Zed's physical burst more than squishy = a
  computed-quantity assertion; ENGINE pin 1.134.0). GATE (fresh this run): DS-dir
  agents/daemon_slayer/tests/ 7272 passed / 1 skip / 1942 subtests exit 0 (91.02s;
  +16 vs the 7256 DSP7 baseline); full RC tests/ --ignore=tests/daemon_slayer 8281
  passed / 2 skip / 109 subtests (the 6 Share doc-anchor + ingest-sync tests RED on
  the first run = expected post-bump pre-sync drift, all green re-run after
  ds_share_sync; 0 regressions = the byte-identical proof); ruff All checks passed;
  py_compile OK; ASCII/LF clean (0 introduced non-ASCII). No web/* touched -> no UI
  ritual / snapshot (R5/R11). INLINE sole orchestrator (R9 + the directive's
  "tightly coupled engine seam -> execute inline" clause - one cohesive seam in
  burst.py + 1 test file + the mechanical 73-file ENGINE-pin bump + Share mirror +
  docs; parallel worktree slices would only contend on the shared ENGINE pins +
  Share; the DSP1-7 precedent); verifier subagent SKIPPED per R7 (own single-thread
  edit, no untrusted slice) - fresh in-thread dual full-suite + live :8893 probe +
  Share --check substituted. No frozen files touched. NEXT (DSP9): lolmath parity
  fold - re-run ops/audit/lolmath_ds_sweep with the DSP4-8 seams ON in-harness,
  close residuals to >= lolmath parity (G6 cost-model = Gemini-consult, not blind
  build). Source: gemini director directive ops/loop/control/directive.md (DSP8).

- 2026-06-17 DSP7 (472, 69f9085d) DONE. Ally aura/enchanter seam - ally enchanter
  SHIELD/HEAL flat-HP EHP-grant (ENGINE 1.132.0 -> 1.133.0). ROOT (plan DSP7 + the
  ally-team permutation bucket): RC modeled two ally-grant EHP modes - resist
  (denominator add) + revive (numerator multiplier) in
  _passive_ally_grant_overrides.py (item 289) - but item 289 DELIBERATELY EXCLUDED
  ally shields/heals ("ability_hps THROUGHPUT, not a resist/revive term - a
  different axis"), so the survivability an enchanter's shield/heal CONFERS on a
  protected ally was an unmodeled permutation. FIX (the THIRD EHP-grant mode, a
  flat NUMERATOR ADD): a flat shield/heal rides the protected ally's armor/MR curve
  exactly like base HP, so +H raw HP scales every per-type EHP like +H max HP. NEW
  SEPARATE registry _ALLY_FLAT_HP_GRANT_OVERRIDES (kept apart from the item-289
  _PASSIVE_ALLY_GRANT_OVERRIDES so its 4-clean-entry shape + the exclusion test
  test_ally_shields_heals_not_in_registry stay byte-identical) seeds 7 canonical
  enchanter grants - Janna E / Lulu E / Karma E / Yuumi E shields + Seraphine W
  shield + Soraka W / Nami W heals - with the verbatim per-rank BASE values probed
  from data/daemon_slayer/16.12.1/champion_abilities.json (the source ability_hps.py
  reads; AP ratio OMITTED - the granter's AP is a live Phase-D input, the
  resist-registry "omit the cross-champion bonus half" precedent), amortized by NEW
  _ALLY_SHIELD_HEAL_PROB 0.5 (the uptime midpoint between Braum-W 0.3 short-active
  and a 1.0 permanent tether). NEW AllyGrantEntry.shield_hp/heal_hp fields (the 4
  resist/revive entries leave both 0.0). Public: ally_flat_hp_grant(champion_id,
  level, apply_ally_grant) fail-soft -> 0.0. CONSUMER seam (GENERIC, mirroring the
  external_resist_* pattern): compute_ehp gains external_flat_hp (default 0.0 ->
  byte-identical), a raw add to every per-type EHP numerator + _blend_with_heal; NEW
  EhpResult.ally_grant_flat_hp + to_dict; negative clamped. DEFAULT-OFF: no live
  scorer passes external_flat_hp -> /rank + compute_ehp + compute_dps + compute_burst
  byte-identical (the DSP5/DSP6 seam-first precedent). allyamp.py (the OUTWARD
  scorer) is SATURATED for the shield/heal buckets under its one-mechanism-per-(champ,
  source) invariant (test_one_entry_per_champion_source + the 74-entry roster pin), so
  it gains only a docstring cross-reference to this PROTECTED-ALLY seam (no
  registry/score change) - the genuine gap was the EHP-grant view, implemented in the
  correct home (feedback_audit_proposals_are_intent: implement the INTENT, confirm the
  deviation). SEAM-FIRST (EXCLUDED): the live default-ON flip = wire a peel/EHP
  consumer reading the live ally team's granter set; appended to
  docs/LIVE_GAME_GATED_SYNC.md section B (a specific DSP7 row) + the live-flip ledger.
  ENGINE bump (directive-mandated + the DS-package schema change forces a Share sync):
  72 quoted pins / 72 .py; DS :8893 bounced (taskkill PID 17548 + schtasks /Run /TN
  RC-DaemonSlayer) -> /health engine_version 1.133.0 confirmed; ds_share_sync 350 files
  --check "Share/src + doc anchors + lolmath_ingest in sync"; DS + Share CHANGELOG
  prepended. TDD: test_ally_flat_hp_grant_dsp7.py +24 (ImportError red-first -> green;
  entry-field defaults, the 7-champ registry shape + probed base tuples, the separate
  registry leaves item-289 at 4, flag-off 0.0, _value_at_level-anchored curve match
  (no hardcoded rank), non-entry/blank 0.0, monotonic-by-level, compute_ehp default
  byte-identical, positive raises every axis, +H scales like +H max HP, negative
  clamped, to_dict carries it, end-to-end Janna grant -> ally EHP, ENGINE pin). GATE
  (fresh this run): DS-dir 7256 passed / 1 skip / 1942 subtests exit 0 (+ vs the 7235
  DSP6 baseline); RC tests/ 8281 passed / 2 skip / 109 subtests exit 0 (post-restart +
  sync, 0 regressions = byte-identical confirmed); ruff All checks passed; py_compile
  OK; ASCII/LF clean (0 introduced non-ASCII; the pre-existing DS-CHANGELOG history
  bytes untouched). No web/* touched -> no UI ritual / snapshot (R5/R11). INLINE sole
  orchestrator (R9 - one cohesive seam across ehp.py + _passive_ally_grant_overrides.py
  + allyamp.py + the ENGINE-pin bump + Share mirror; parallel worktree slices would
  conflict on the shared ENGINE pins + Share; the DSP1-6 precedent); verifier skipped
  per R7 (single-thread) - fresh in-thread dual-suite + live :8893 probe + Share --check
  substituted. No frozen files touched. NEXT: DSP8 (enemy-comp target-preset seam -
  extend DSV3 assume_squishy_target into tank-heavy/squishy/bruiser/high-CC presets).
  Source: gemini director directive ops/loop/control/directive.md (DSP7).

- 2026-06-17 DSP6 (471, f3563120) DONE. Enemy-rune threat seam (ENGINE 1.131.0
  -> 1.132.0). NEW agents/daemon_slayer/enemy_runes.py - the enemy-side mirror of
  summoners.py (DSP5). ROOT (plan DSP6 + the permutation-bucket matrix): RC
  modeled the player's OWN runes (rune_procs.py + core/rune_wpa.py) but had ZERO
  model of the ENEMY's runes as a threat modulating the player's EHP preset
  (survivability) or the enemy's target preset (tankiness) - the enemy-rune-
  threat dimension was an unmodeled permutation. FIX (NEW self-contained
  substrate, the summoners.py birth precedent): a frozen EnemyRuneThreat dataclass
  + ENEMY_RUNE_THREATS registry keyed by Riot rune id, one pure formula closure
  per rune on its threatened preset: Press the Attack 8005 incoming_amp (0.08 amp
  on the player; the enemy's 8% damage-dealt amp = a 1/1.08 EHP-numerator
  divisor), Conqueror 8010 damage_ramp (max-stack Adaptive Force 21.6-48.0 by
  level = 12 * 1.8-4.0/stack, the legacy true-dmg-ramp lens; lifesteal 0.08 melee
  / 0.05 ranged carried for the enemy-sustain target lens), Grasp 8437
  poke_sustain (1.3% max-HP heal + 3.5% max-HP magic + 5 perm HP/proc, ranged
  0.40), Second Wind 8444 poke_sustain (4% of missing HP over 10s). MAGNITUDES:
  every coefficient is verbatim from DDragon runesReforged.json 16.12.1 longDesc
  (authoritative; never aggregator D/aggregator A), cited per rune in the formula string -
  unlike summoner spells, DDragon does NOT zero rune longDescs, so no wiki
  fallback was needed (wiki cross-check only). ANTIHEAL (the 4th DSP6 bucket) is
  NOT a rune - no rune grants Grievous Wounds (it comes from items + Ignite,
  already in summoners.py id 14) - so it is carried as the non-rune constant
  GRIEVOUS_WOUNDS_PCT 0.40 + the enemy_antiheal_pct(present) flag helper and is
  EXCLUDED from ENEMY_RUNE_SEAM_IDS (documented inline). Public surface:
  compute_enemy_rune_value + enemy_incoming_amp_pct / enemy_damage_ramp /
  enemy_poke_sustain_pct / enemy_poke_sustain_hp / enemy_grasp_magic_proc /
  enemy_antiheal_pct, all fail-soft (unknown id / empty / None / bad input ->
  0.0). DEFAULT-OFF: ENEMY_RUNE_SEAM_IDS marks the ids but NO live scorer consumes
  the module -> /rank + compute_dps + compute_ehp + compute_burst byte-identical
  to pre-DSP6 (summoners-at-birth + DSV1-4 precedent). SEAM-FIRST (EXCLUDED): the
  live flip = wire an EHP/target-preset consumer reading the enemy's live rune
  set; appended to LIVE_GAME_GATED_SYNC.md section B (a specific DSP6 row +
  dropping DSP6 from the generic placeholder) + the live-flip ledger. ENGINE bump
  (directive-mandated + a new agents/daemon_slayer module needs Share sync): 79
  quoted pins / 71 .py; DS :8893 bounced -> 1.132.0 live; ds_share_sync 349 files
  --check in sync; DS + Share CHANGELOG prepended + Share/docs/02 function-ref
  subsection added. TDD +29 (28 logic green pre-bump, the ENGINE pin red-first ->
  green). Gate: DS-dir 7235 passed / 1 skip / 1942 subtests; RC tests/ 8281 passed
  / 2 skip / 109 subtests (post-restart + sync); ruff + py_compile + ASCII/LF
  clean (the 590 non-ASCII bytes in the DS CHANGELOG are pre-existing history,
  0 introduced). INLINE sole orchestrator (R9 - one cohesive new module + its
  ENGINE-pin bump across 71 files + Share mirror; parallel worktree slices would
  conflict on the shared ENGINE_VERSION pins + Share; the DSP1-5 reading of plan
  line 60); verifier skipped per R7 (single-thread) - fresh dual-suite + live
  :8893 probe + Share --check substituted. NEXT: DSP7 (ally aura/enchanter seam,
  extend allyamp.py + _passive_ally_grant_overrides.py). Source: gemini director
  directive ops/loop/control/directive.md (DSP6).

- 2026-06-17 DSP5 (470, 790b0236) DONE. Summoner-spell seam (ENGINE 1.130.0 ->
  1.131.0). NEW agents/daemon_slayer/summoners.py - a self-contained substrate
  (the rune_procs.RUNE_PROCS birth precedent) registering the 6 combat summoner
  spells on their scoring axis: Ignite 14 antiheal_true (70-525 true DoT by level
  + 0.40 Grievous Wounds), Exhaust 3 incoming_dr (0.35, level-independent), Heal 7
  ehp_heal (80-346 flat heal by level + 0.30 MS), Barrier 21 ehp_shield (100-
  502.35 by level), Cleanse 1 cc_discount (0.75 tenacity; QSS item analog), Ghost
  6 move_speed (0.24-0.5082 by level). Public surface (compute_summoner_value + 3
  flat-fraction getters + compute_summoner_ms_pct + compute_summoner_ehp_bonus)
  all fail-soft (unknown id / bad level -> 0.0). MAGNITUDES: DDragon + CDragon
  16.12.1 ZERO summoner magnitudes (prose-only descriptions, like stripped item
  passives - verified by fetching both), so every coefficient is the LoL wiki
  value (reference_lol_wiki_access), cited per spell in the formula string; the
  wiki is the live patch (post-16.12.1) so the flip re-anchors the magnitudes at
  flip. DEFAULT-OFF: SUMMONER_SEAM_IDS marks the ids but NO live scorer consumes
  the module -> /rank byte-identical (rune_procs-at-birth + DSV1-4 precedent).
  SEAM-FIRST (EXCLUDED): the live flip = wire a fight_report/matchup/coach
  consumer; appended to LIVE_GAME_GATED_SYNC.md section B (a specific DSP5 row
  replacing the generic DSP5-8 placeholder) + the live-flip ledger. ENGINE bump
  (directive-mandated + a new agents/daemon_slayer module needs Share sync): 78
  quoted pins / 70 .py; DS :8893 bounced -> 1.131.0; ds_share_sync 347 files
  --check in sync; DS + Share CHANGELOG prepended + Share/docs/02 function-ref
  subsection added. TDD +24 red-first -> green. Gate: DS-dir 7206 passed / 1 skip
  / 1942 subtests; RC tests/ 8281 passed / 2 skip / 109 subtests (post-restart +
  sync); 3 hygiene gates 12 passed; ruff + py_compile + ASCII/LF clean. INLINE
  sole orchestrator (R9); verifier skipped per R7 (single-thread) - fresh dual-
  suite + live :8893 probe + Share --check. External wiki fetch is a S7b data-
  anchor (not S4 runtime budget). NEXT: DSP6 (enemy-rune threat seam). Source:
  gemini director directive ops/loop/control/directive.md (DSP5).

- 2026-06-17 DSP4 cycle REGRESS directive: 1 of 2 items REAL, 1 FALSE POSITIVE.
  No ENGINE bump (notes-string only; no scorer/schema/math change). VERIFIED both
  premises against ground truth before coding (S7 + feedback_audit_proposals_are
  _intent). (1) REAL - burst.py notes byte-identical break: the DSP4 notes block
  gated on `if _scored_runes:` (post-completion-filter), so a supplied
  runes=[8401] default-OFF swallowed the rune-procs note entirely, whereas the
  pre-DSP4 engine fired "rune procs +0.0 (0 known rune(s))" for any supplied rune
  set (8401 was then an unknown id, _n=0). Violates burst.py docstring "byte-
  identical to the pre-DSP4 engine for any supplied rune set". FIX: gate on
  `if runes:` (supplied?), keep _n over _scored_runes so 8401 reads 0 known ->
  exact pre-DSP4 string; SCORING stays gated on _scored_runes (rune_proc_damage
  still 0.0, total unchanged). TDD: 2 new subtests in
  test_burst_shield_bash_seam_dsp4.py (notes byte-identical for runes=[8401];
  runes=None emits no note) - red before / green after. Sibling sweep: combo.py
  gates its rune note on `if rune_proc > 0.0:` (damage value, not runes
  truthiness) -> already byte-identical, no change. (2) FALSE POSITIVE -
  rune_procs.py `COMPLETION_RUNE_IDS: frozenset[int]` "import crash on Python
  <3.9": REFUTED. Line 42 `from __future__ import annotations` makes the
  annotation a lazy string (never evaluated); RC runs Python 3.14 (PEP 585 valid
  anyway); `typing.Dict` import is cosmetic. Proven: `import rune_procs` ->
  `IMPORT_OK [8401] frozenset 20`. NO change made (cargo-cult downgrade avoided).
  Suites: DS 7182 passed / 1942 subtests; RC 8281 passed. R7 verifier skipped
  (own single-thread edit); R9 inline (1 code line + 1 test file + docs, < 3
  files - directive's worktree-fanout boilerplate does not fit a 1-line revert).
  Share/ re-synced (--check green). Source: gemini director REGRESS directive
  ops/loop/control/directive.md.

- 2026-06-17 DSP4 (468, 1f7dbe62) DONE. Self-rune completion seam (ENGINE
  1.129.0 -> 1.130.0). ROOT (catalog sweep of DDragon 16.12.1 runesReforged.json
  vs RUNE_PROCS): of 62 catalog runes, 19 were modeled (8 item-226 + 6 S4 + 2
  per_attack + 3 item-232 gated) and 42 unmodeled. A scan for unmodeled runes
  with a damage component found exactly ONE LIVE, pickable, direct-champion-
  damage proc still missing: Shield Bash 8401 (Resolve). FIX: add 8401 to
  RUNE_PROCS (proc_type on_proc_burst, condition shield_gated, cooldown_s 0.0):
  compute = (5-30 by level) + 0.025*bonus_hp + 0.15*shield_amount, verbatim from
  the longDesc "5 - 30 (+2.5% Bonus Health) (+15.0% New Shield Amount) bonus
  adaptive damage". "adaptive" is the damage TYPE not a coefficient (no AD/AP
  scaling). Registry 19 -> 20. SEAM (DEFAULT-OFF, DSV1-4 precedent): new
  COMPLETION_RUNE_IDS frozenset + score_completion_runes kwarg on
  compute_burst_damage + compute_combo (default False -> completion runes
  SKIPPED -> byte-identical to pre-DSP4 for every rune set). The burst scorer
  has no live shield signal so it scores the shield-independent 5-30 + 2.5%
  bonus-HP floor (best-case-shielded); shield_amount forward-compat for a live
  producer. core/rune_wpa.py cross-links the empirical WPA lens with the proc
  model: each row gains proc_modeled (fail-soft RUNE_PROCS-keys import). The 42
  other unmodeled runes are honest exclusions: stat-grants (Waterwalking 8232,
  Jack 8316), ult-only amp (Axiom Arcanist 8224), legacy (Deathfire Touch 8992),
  non-damage utility. SEAM-FIRST (EXCLUDED): live flip score_completion_runes=
  True appended to docs/LIVE_GAME_GATED_SYNC.md section B + ledger. ENGINE bump +
  DS :8893 restart (1.130.0 live) + Share sync (--check green, 345 files) in the
  SAME commit. TDD +27 red-first->green (Shield Bash math floor/hp/shield/no-AD-
  AP/failsoft; COMPLETION set; burst+combo OFF byte-identical, ON contributes;
  proc_modeled annotation); 2 registry-shape pins 19->20; 77 ENGINE_VERSION test
  pins bumped. Gate: DS-dir 7177 passed / 1 skip / 1942 subtests exit 0; RC tests/
  8281 passed (post-bump share/anchor/live-engine set re-ran green after DS
  restart); ruff + py_compile + ASCII/LF clean. INLINE sole orchestrator (R9 -
  one tightly-coupled rune-proc seam across rune_procs/burst/combo/rune_wpa;
  parallel worktree slices would conflict on the shared scorer files - the
  DSP4-as-single-seam reading of plan line 60); verifier skipped per R7 (single-
  thread) - fresh in-thread dual full-suite re-verify. NEW FINDING (queued, NOT
  this cycle): the adaptive stat-grant runes (Waterwalking/Jack/Eyeball-class)
  are burst-neutral (proc_type adaptive is skipped by the burst consumer) so
  modeling them is fight_report-cosmetic only - a LOW-value DSP-tail, not worth
  an ENGINE bump unless a fight_report surfacing need appears. NEXT: DSP5
  (summoner-spell seam, NEW summoners.py). Source: gemini director directive
  ops/loop/control/directive.md (DSP4).

- 2026-06-17 DSP3 (467, 97920f56) DONE. Cluster-A archetype-vs-ARAM-win
  divergence. ROOT (cross-eval SYSTEMIC_FINDINGS Cluster A + the 8
  archetype_ok=false verdicts): get_archetype_for routes each champ to its KIT
  archetype (correct by DDragon tag / lolmath axis, P6-G1) but rewind ARAM win
  data favors a DIFFERENT axis for a cluster, so the kit-default scorer's whole
  pool misses the winning ARAM build. FIX (RC-side resolver seam, the DSP2
  pattern): NEW builder ops/audit/ds_perm_swarm/build_aram_archetype_override.py
  distills the cross-eval empirical (rewind WIN+usage) block into
  core/aram_archetype_override.json - selection mechanical (verdict
  archetype_ok=false AND archetype source=default; user_cs Lulu/MissFortune
  skipped) + WIN-anchored (>=1 above-baseline ARAM item on the override axis,
  n>=8 wr within 3pp baseline). 6 overrides: Zilean/Shaco/Shyvana->mage,
  Taric->tank, KogMaw/Kayle->carry. SEAM (DEFAULT-OFF, byte-identical):
  get_archetype_for(prefer_aram_win_axis=False); ON re-bases the kit default
  (operator picks NEVER touched), source=aram_win (resolver-only, not in
  VALID_SOURCES). SEAM-FIRST (EXCLUDED): live flip appended to
  docs/LIVE_GAME_GATED_SYNC.md section C. NO ENGINE bump / DS restart / Share
  sync - RC-side only, no engine math (the override changes WHICH scorer runs,
  never the scorer math); the DSP1/Tier-1 precedent. TDD +13 red-first->green
  (builder select/skip/win-gate/unmapped-raise hermetic; shipped-table 6
  overrides + Lulu/MissFortune absent; seam OFF byte-identical, ON Kayle->carry,
  non-override unchanged, operator-pick untouched, loader fail-soft). Gate: full
  RC tests/ 8278 passed / 2 skip / 109 subtests exit 0; ruff + py_compile +
  ASCII/LF clean. INLINE sole orchestrator (R9); verifier skipped per R7
  (single-thread) - fresh in-thread full-suite re-verify. NEW FINDING (NOT this
  cycle, queued): the Cluster-A OUTCOME-mismatch champs that are archetype_ok=TRUE
  (Bard/Morgana/Seraphine/Thresh hps, Malphite/Nunu tank) are item-POOL gaps not
  archetype swaps -> a separate pool-nomination lane, not DSP3. NEXT: DSP4
  (self-rune completion seam). Source: gemini director directive
  ops/loop/control/directive.md (DSP3).

- 2026-06-17 cycle 3 audit REGRESS -> AUDITOR FALSE POSITIVE (docs only, no code
  change). The gemini auditor flagged "Behavior change in agents/daemon_slayer/
  rank.py (exempt_offclass_by_win seam) has no accompanying test." PROOF it is
  false: the seam's 12 hermetic tests shipped in the SAME commit as the seam
  (6f7a5756, item 465) at agents/daemon_slayer/tests/test_rank_offclass_win_
  exempt.py; re-run fresh THIS cycle = 12 passed in 0.28s. The directive's exact
  ask ("a test verifying the un-stripping logic when the seam is enabled") is
  covered by THREE tests: test_seam_on_unstrips_ezreal_winning_items (L128-133:
  Trinity Force + Spear of Shojin re-enter Ezreal's pool SR+ARAM when
  exempt_offclass_by_win=True), test_seam_on_unstrips_corki_and_smolder
  (L135-138: Corki/Smolder +Trinity, Senna +Black Cleaver when ON),
  test_seam_on_adds_only_exempt_items_for_ezreal (L149-157: ON differs from OFF
  ONLY by the exempt items over the full candidate pool). Seam-OFF control
  test_default_off_preserves_item213 (L120-126) + no-collateral
  test_crit_adc_unchanged_when_seam_on (L140-147) also covered. Branch map of the
  seam (rank.py L656-667): 2a OFF = full deny-set (tested); 2b ON + non-empty
  exempt = deny-set minus exempt (tested x3); 2c ON + empty exempt = unchanged
  full deny-set (tested via Caitlyn). The only structurally-uncovered branch
  (non-marksman + ON = no-op) is gated behind _is_ranged_marksman and unreachable
  without a data-fragile scorer-routing assertion (Testing-Discipline banned), so
  it was deliberately NOT added. RESOLUTION per the directive's explicit "if this
  is an auditor false positive, document the proof" clause: documented here + in
  LEDGER 466; NO redundant test fabricated (the comprehensive coverage already
  exists; the seam was shipped TDD red-first per item 465). Full DS-dir suite
  re-run green THIS cycle (LEDGER 466). NEXT remains DSP3 (Cluster A
  archetype-vs-ARAM-win). Source: gemini director directive (cycle 3 REGRESS).

- 2026-06-17 DSP2 (465, 6f7a5756) DONE. Cluster-B off-class WIN-exemption seam,
  Tier-2 ENGINE 1.128.0 -> 1.129.0, DS :8893 bounced -> 1.129.0, Share re-synced
  (343, --check in sync) in the SAME commit. ROOT CAUSE (consumed the DSP1
  divergent tail, Ezreal SR -39 the worst champ-mode): the item-213 ranged-
  marksman off-class deny-set (rank.OFFCLASS_MARKSMAN_ITEM_NAMES) hard-strips
  Sheen-line / on-hit items (Trinity Force, Spear of Shojin, Black Cleaver) from
  EVERY ranged marksman - right for a crit ADC (Caitlyn/Jinx/Sivir) but WRONG for
  a Sheen/ability caster-marksman: Trinity Force is Ezreal's most-built item
  (rewind ARAM n=219, his BIS) yet excluded from the candidate pool; Spear of
  Shojin / Black Cleaver are real Corki/Smolder/Senna builds. No kit-data axis
  exists for "wants Sheen" (lolmath.damage_distribution is AD/AP only - cannot
  separate Ezreal's ability-physical from Caitlyn's auto-physical), so the
  exemption is WIN+usage anchored: NEW builder ops/audit/ds_perm_swarm/
  build_marksman_offclass_exempt.py distills the cross-eval empirical block
  (rewind WIN data) into agents/daemon_slayer/marksman_offclass_exempt.json
  (exempt at n>=30 AND wr>=mode_baseline-3). FIX (DEFAULT-OFF seam, byte-identical
  off, the DSV1-4 precedent): NEW rank_items(exempt_offclass_by_win=True) +
  fail-soft cached table loader (_load_offclass_exemptions / _offclass_win_
  exemptions); when ON + the champ is a ranged marksman, the exempt names are
  subtracted from the deny-set so they re-enter the pool. 4 caster-marksmen
  exempted (Corki/Ezreal/Senna/Smolder); pure crit ADCs (Caitlyn/Jinx/Sivir,
  absent from the table) are byte-identical ON or OFF (verified). SEAM-FIRST
  (EXCLUDED): rank.py does not pass exempt_offclass_by_win=True live yet; the flip
  is appended to docs/LIVE_GAME_GATED_SYNC.md (do-not-flip-blind). TDD: 12 hermetic
  tests red-first (ImportError) -> green (table shape, every exempt name in the
  deny-set, crit-ADC empty, helper id/name resolution, loader fail-soft, OFF
  preserves item-213, ON un-strips Ezreal/Corki/Smolder/Senna, ON adds ONLY the
  exempt items over the full pool, crit-ADC byte-identical). Offline validation:
  the seam re-includes exactly each champ's empirically-built off-class items with
  their n/wr; crit ADCs identical. Gate: DS-dir 7156 passed / 1 skip / 1942
  subtests; RC tests/ 8265 passed / 2 skip / 109 subtests (run after DS restart +
  ds_share_sync so live-:8893 + Share anchors green); ruff + py_compile + ASCII/LF
  clean; 155 ENGINE quoted pins bumped across 77 .py (0 historical refs in .py).
  ORCHESTRATION (auto-pick, logged): INLINE sole orchestrator (R9 - one cohesive
  engine seam, ~4 authored files, the DSP1 inline precedent); verifier subagent
  SKIPPED per R7 (single-thread, no untrusted slice) - fresh in-thread dual-suite
  + live :8893 probe + Share --check substituted. No frozen files touched. NEW
  FINDING (NOT this cycle): Pyke ARAM -22 is a DISTINCT mechanism - Pyke is melee
  (not Marksman-tagged) so he never hits the off-class filter; his burst scorer
  ranks raw-AD/crit/AS/heal items (Sundered Sky/Essence Reaver/BORK/Triforce/IE)
  ABOVE the lethality items he actually builds + wins on (Youmuu/Hubris/Axiom/
  Opportunity). That is a burst-valuation gap (DSV-class), not a marksman-template
  leak -> queue a DSP3-or-DSV row. NEXT: DSP3 (Cluster A archetype-vs-ARAM-win).

- 2026-06-17 DSP1 (464, 19f66829) DONE. Built the permutation WIN-anchor harness
  ops/audit/ds_perm_swarm/ (BUILD-only, no engine change). Scores DS top-N (cross-eval
  comp_grid) vs per-item rewind_history.db WIN-rate per (champ x mode) via difference-of-
  differences: lift = mean(WR of DS-top-K items, n>=min_item_n) - baseline_wr. 4 modules
  (cross_eval_loader / win_anchor [sqlite-conn injected, hermetic] / perm_score build_report
  / run_harness CLI) + 9 hermetic tests (in-memory sqlite + cross-eval fixtures; the 1.8GB
  rewind db is never opened - clean-checkout safe). LIVE RUN (report/perm_anchor_report.
  {json,md}): 294 champ-modes scored (160 ARAM + 134 SR), 54.4% positive lift,
  mean_lift_weighted +0.17 -> DS rankings weakly outcome-aligned. DIVERGENT TAIL
  (DSP2/DSP3 targets, lowest lift): Ezreal SR -39 / Zilean ARAM -33 / Shaco ARAM -29 /
  Pyke ARAM -22 - Ezreal+Pyke corroborate the Cluster-B generic-marksman-template
  hypothesis; the harness IS the DSP2/3 consume-and-validate tool. INLINE sole orchestrator
  (R9, coupled new package); verifier-gate = fresh in-thread exit-0 re-verify (R7, no
  untrusted slice). Gate: new 9/9; full RC tests/ 8265 passed / 2 skip / 109 subtests exit
  0; ruff + py_compile + ASCII/LF clean. NO DS paths -> no ENGINE bump / DS restart / Share
  sync. NEXT: DSP2 (Cluster-B marksman-template fix), consuming this report's divergent tail.

- 2026-06-16 LBAND1 (443, a8158629) DONE. Cycle 45 director-refill (bounded queue
  drained, Gemini down 429). 2-agent fanout: L2 robustness/coverage scout over
  post-2026-06-03-baseline NEW modules (items 285-442) = NOW=0 FUTURE=0 CLEAN=20
  (clean-baseline holds). L1 Section-7b competitor deep-dive (Aggregator C/Overlay App E/
  Overlay App F, docs/COMPETITOR_LIFT_2026-06-16.md): 1 HIGH flag (overlay app E live-
  benchmarking) VERIFY-FIRST-overturned to PARTIAL-supersede - lead_projection
  bands live metrics vs a FLAT heuristic; benchmarks.rank_value has per-champion
  personal percentiles but POST-GAME only. SHIPPED the net-new half: NEW
  core/live_benchmark_band.py bands live cs+level vs the player's own champion
  percentile at the ~10/~15 checkpoint (SR-only, gold excluded, >=5-games gate),
  pure generator + 10 hermetic tests, no live consumer yet (wire-in FUTURE, do-
  not-flip-blind). 5 competitor findings -> BACKLOG (Aggregator C skill radar,
  Overlay App F lobby-tags + ward-heatmap, Overlay App E enemy ult-CD + LCU rune-write).
  NEXT: bounded headless-safe queue drained again; remaining live/operator/Gemini-gated.

- 2026-06-16 RN1+DIAG1 (440, ed9c709c) + HZ-T1 (441, 9da9358a) DONE. Director-refill
  cycle 43 (A1-UIX3+DSV1-4 drained, Gemini down 429). 4 read-only scouts: DS-engine-lift
  CLOSED (DSV1-4 done, 174/174 tier-3 items, P6 design-level); Electron-overlay CLOSED
  (Phases 1-6 code-side shipped, rest live-gated/packaging); HZ + UI = NOW. 3 Section-3b UI-audits:
  ds_profile/ds_matchup CLOSED (tokenized); ds_sweep/ds_combo CLOSED (spacing-px only, NOT
  the font-floor/hit-target bar - no churn); right_now/next + diagnostics NOW. RN1:
  .rn-sr-btn hit-target (~26px -> 42px) + sub-floor compliance; DIAG1: rogue inline 10px
  dropped + dense-surface operator-exception. HZ-T1: per-mode fail-soft routing (scout's
  reader-test parametrize REJECTED on verify-first - mode bypassed by payload=). NEXT:
  bounded headless-safe queue DRAINED again; remaining = live/operator/Gemini-gated. Visual
  capture OWED (Game-PC :8892 down).

- 2026-06-16 DSV4 DONE (commit c5fe019d, item 437). DIRECTOR-REFILL continuation:
  the A1-UIX3 plan set was DONE, so under the operator directive "continue open
  items headlessly - multi-agent fanout orchestrated" the next bounded ship-or-
  close slice was drawn from the SAME DSV P6-G5 / G2-residual scorer-valuation
  lane the operator seeded DSV1/2/3 against (the P6-G2 work-map bucket B names
  Spear of Shojin explicitly). Tier-2 ENGINE 1.126.0 -> 1.127.0, DS :8893
  restarted -> 1.127.0, Share re-synced (340) in the SAME commit. ROOT CAUSE:
  the ability scorers had no seam for Spear of Shojin 3161 Focused Will, a
  stacking ability/passive damage amp (Meraki 16.12.1: 3%/stack, max 4 = 12%);
  the item was defensive_only "ability damage not DPS-modeled", so an ability-
  reliant build that bought Shojin saw zero damage value from it. Focused Will
  amps abilities/passives only, never basic attacks. FIX (DEFAULT-OFF
  assume_ability_amp seam, byte-identical off; INLINE sole orchestrator per R9 +
  the DSV1/2/3 precedent): NEW ItemEffect.ability_damage_amp_per_stack /
  ability_damage_amp_max_stacks (0.0/0 default) + effects.total_ability_damage_amp
  helper + dps._ASSUMED_ABILITY_AMP_STACKS=4; compute_ability_dps multiplies the
  spell ability sum (DoT procs NOT amped - conservative), compute_burst_damage
  multiplies ONLY ability_total (never aa_total), rank_items_by_burst threads
  both call sites; compute_dps (AA scorer) untouched. Shojin 3161 + Arena 223161
  pinned 0.03/4. SEAM-FIRST (EXCLUDED): ships DEFAULT-OFF, rank.py does not pass
  assume_ability_amp=True yet (the validation-gated flip is the DS Phase-D class).
  TDD: 14 Meraki-anchored tests red-first (ImportError) -> green (schema defaults,
  data pins, helper cap/linear math, compute_ability_dps + burst OFF byte-identical
  / ON exactly *1.12 ability-only / AA untouched / non-Shojin unchanged, rank
  byte-identical). Gate: DS-dir 7140 passed / 1 skip / 1942 subtests; RC tests/
  7982 passed / 2 skip / 109 subtests (run after DS restart + ds_share_sync so the
  live-:8893 + Share anchors are green, no pre-fix failures); ruff + py_compile +
  ASCII clean; ds_share_sync --check in sync (340, engine 1.127.0); 76 ENGINE pins
  bumped across 67 files (3 DSV3 historical changelog refs kept). Verifier subagent
  SKIPPED per R7 (single-thread inline) - fresh THIS-run re-verify instead. No
  frozen files touched. NEXT: the named bucket-B/C scorer-valuation residual is now
  covered (DSV1 AP DoT-burn + DSV2 kill-state + DSV3 lethality + DSV4 Shojin ability-
  amp); the P6 design tail (G3 runes / G6 cost-model / G7 comp-harness) is Gemini-
  consult-first per ops/audit/P6_LOLMATH_PARITY.md - NO bounded ship-or-close slice
  remains. The plan stays drained pending an operator/Gemini refill.

- 2026-06-16 UIX3 DONE (commit 7417a7a8, item 436). Session / History detached
  historical-PGR (HIST2) 5-phase fixture audit (STRUCTURE / TYPOGRAPHY / HIT-
  TARGETS / ASCII / HIERARCHY per docs/UI_SCALE_SPEC_V2.md v2.1) on
  historical_pgr.js + last_match.js + post_game_phases.js + CSS + the
  #view-historical-pgr DOM. Tier-1 frontend, NO ENGINE bump, NO DS/Share, NO RC
  restart (ADR-008 asset-hash). SCOPE TRUTH: the reused lm-* / lm-wpa-* surface
  (last_match.css) was already fully v2.1-swept in item 182 (every font-size a
  token or a documented inline OPERATOR EXCEPTION) -> 0 MUST-FIX there;
  historical_pgr.js + post_game_phases.js 0 non-ASCII; the DOM reuses globally-
  swept lm-* / view-section-* classes. The ONLY never-audited chrome = the
  bespoke .hpgr-back (Back button) + .hpgr-tag (ARCHIVE pill) in home.css
  (HIST2 item ac404c13). AUDIT: read-only general-purpose audit subagent ran all
  5 phases vs the v2.1 tokens (verified live tokens.css: --fs-xs 16 / --fs-sm 18
  / --hit-min 42); the orchestrator ground-truth re-verified EVERY claim against
  the files before acting - no merge on the agent's word. ORCHESTRATION (auto-
  pick, logged): INLINE sole orchestrator + ONE read-only audit subagent (2 CSS
  files in the merge set, R9 - the UIX1/UIX2/DSV/OVL inline precedent). 3 MUST-FIX
  SHIPPED (all home.css, ASCII-only, HEAD/work non-ASCII byte delta 0 = 612==612):
  (1) .hpgr-back font-size 13px -> var(--fs-xs) (bare sub-16, no rationale; the
  rule bar is >= --fs-xs); (2) .hpgr-back + min-height var(--hit-min) 42 hit-floor
  + display:inline-flex label centering (~21px clickable, NOT a full-width
  display:block exception -> the floor applies; the reused lm-tab / lm-rank-select
  / lm-section-head-btn already carry it); (3) .hpgr-tag font-size 11px ->
  var(--fs-xs) (7-char ARCHIVE pill, not the 3-char badge-density case the
  sanctioned lm-tc-score-badge 14px exceptions cite - tokenize to floor rather
  than claim a NEW operator-exception without approval). NICE-deferred (FUTURE):
  .hpgr-tag 999px pill radius + 1px/7px off-grid padding (pre-existing decorative;
  spec bans only NEW off-grid). TDD: a CSS-only audit has no failing-test-first
  target; gate = snapshot + render suite green. Gate (Tier-1 per R5): RC tests/
  7982 passed / 2 skip / 109 subtests, exit 0 (ZERO delta vs cycles 37/38, CSS
  cannot touch Python logic); ASCII delta 0. VISUAL: Claude_Preview OWED (preview
  MCP refuses to attach to the live external pythonw :8888 PID 2104; a 2nd main.py
  conflicts on :8889/LCU singletons; Game-PC :8892 down post-1PC) - render deltas
  proven deterministically (token == tokens.css value). No frozen files touched.
  NEXT: the A1-UIX3 plan set is now FULLY DONE -> the director should refill the
  plan with a new operator-scoped batch or emit NO_WORK.

- 2026-06-16 UIX2 DONE (commit 4b1804da, item 435). Home + Settings 5-phase
  fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY per
  docs/UI_SCALE_SPEC_V2.md v2.1) on the Home view (.home-* home.css + main.js
  _homeRender*/renderHomePanel 2614-3325 + builders_home.py data) and the
  Settings page (.settings-*/.spend-gate-*/.loop-*/.view-section-head h2 in
  header.css + index.html #view-settings + dev.js). Tier-1 frontend, NO ENGINE
  bump, NO DS/Share, NO RC restart (ADR-008 asset-hash auto-reload). AUDIT: a
  read-only general-purpose audit agent ran all 5 phases vs the v2.1 tokens ->
  0 MUST-FIX + 0 SHOULD-FIX (both surfaces already v2.1-migrated: Home .home-*
  2026-05-23, Settings the worked-example page), every in-scope font-size
  already a token + every clickable already min-height var(--hit-min); the
  orchestrator ground-truth re-verified the full rule set + the index.html view
  structure + tokens.css values before acting. SCOPE: Diagnostics (.diag-* incl
  the inline 10px) is a SEPARATE view (confirmed via index.html - Settings cards
  = VOICE/CHAMP-SELECT/DISPLAY/SPEND-GATES/DATA/HEADLESS-LOOP/PGR/LOBBY; Diag +
  Replay are their own #view-*), EXCLUDED; .view-section-sub (12px) does not
  render on the SETTINGS head (h2 only) = shared chrome, EXCLUDED. ORCHESTRATION
  (auto-pick, logged): INLINE sole orchestrator + ONE read-only audit subagent
  (2 CSS files in the merge set, R9 - the UIX1/DSV inline precedent). SHIPPED (8
  byte-identical token subs so the audited panels are fully token-driven; every
  sub token==literal vs tokens.css, zero render change): home.css
  .home-recent-main padding-left 4px -> var(--space-1), .home-recent-items gap
  4px -> var(--space-1), .home-coach-pick-body gap 28px ->
  var(--panel-padding-loose), .home-pick-section-1 gap 14px -> var(--panel-gap),
  .home-pick-section-2 gap 4px -> var(--space-1), .home-pick-tip-row gap 16px ->
  var(--space-4), .home-pick-section-3 column-gap 16px / row-gap 14px ->
  var(--space-4) / var(--panel-gap); header.css .loop-btn min-height 42px ->
  var(--hit-min). The spec's "spacing literals NOT auto-swept" line means these
  were optional consistency (byte-identical), not defects. LEFT: 4px radii (no
  4px radius token) + 6px kda gap = decorative, NICE-deferred. TDD: a CSS-only
  audit has no failing-test-first target; gate = snapshot + render suite green.
  Gate (Tier-1 per R5): RC tests/ 7982 passed / 2 skip / 109 subtests, exit 0
  (ZERO delta vs cycle 37, CSS cannot touch Python logic); ASCII hygiene green
  in-suite (added only ASCII var() tokens). VISUAL: Claude_Preview OWED - the
  preview MCP refuses to attach to the live external pythonw :8888 (PID 2104,
  "not a preview server"; it only manages servers it starts) + spawning a 2nd
  main.py on autoPort would conflict on :8889/LCU singletons; render deltas
  proven deterministically (8x byte-identical token==literal + snapshot_panels
  green). No frozen files touched. NEXT (plan order): UIX3 (Session + detached-
  PGR 5-phase audit).

- 2026-06-16 UIX1 DONE (commit 3c123060, item 434). Champ-Select SR 5-phase
  fixture audit (STRUCTURE / TYPOGRAPHY / HIT-TARGETS / ASCII / HIERARCHY per
  docs/UI_SCALE_SPEC_V2.md v2.1) on web/js/panels/champ_select.js +
  champ_select_view.css. Tier-1 frontend, NO ENGINE bump, NO DS/Share change, NO
  RC restart (ADR-008 asset-hash auto-reload). AUDIT: a read-only general-purpose
  audit agent ran all 5 phases against the v2.1 tokens; returned 0 MUST-FIX + 4
  SHOULD-FIX, EVERY claim ground-truth re-verified by the orchestrator (grep
  hardcoded-px / non-ASCII + targeted reads + the JS click-wiring) before acting -
  no merge on the agent's word. ORCHESTRATION (auto-pick, logged): INLINE sole
  orchestrator + ONE read-only audit subagent for the ritual - 2 files (js + css),
  so per R9 a worktree fan-out was unwarranted; the audit subagent IS the
  UI-fixture-ritual independent perspective, the orchestrator implements +
  ground-truth-gates. ASCII PASS (0 non-ASCII both files, re-confirmed post-edit).
  FIXES (all CSS, zero/low render risk): (1+2) .csv-pr-champ-name +
  .csv-pr-champ-wr 18px -> var(--fs-sm) - the SR foregrounded YOUR RECORD headline;
  --fs-sm == 18px (tokens.css:50) so byte-identical render, pure tokenization. (3)
  .csv-lock-btn 32px min-height documented inline as a SANCTIONED hit-floor
  exception (full-width display:block button on a mouse-driven 1920x1080 desktop =
  the horizontal target is the whole card width; the short vertical height is the
  operator's deliberate de-emphasis) - converts an undocumented sub-42 flag into a
  rationale'd exception, NO render change (the reduced height is preserved, not
  re-grown). (4) .csv-build-row + min-height: var(--hit-min) (42px, tokens.css:91)
  - hit-target parity with the compliant sibling .csv-build-path-row (2298);
  collapsed SR-primary rows carry the base class but stack multiple 42px path-rows
  so the floor is a no-op there (JS 3180/3187), a real fix on the non-collapsed SR
  experimental / ARAM / Arena variant click row. NOT-FINDINGS (verified): below-floor
  10px (2209) + 11px (2219) = decorative ::after / empty-cell pseudo-glyph markers
  on 20px spell icons (not a text tier); 11px (2520) = .csv-duo-cell-tag with a
  DOCUMENTED operator exception inline (item 178 ledger s234) AND Arena-scoped (out
  of SR scope); .csv-pr-chip 14px operator-directed exception + the body-zoom popup
  workaround (spec 200-204 OUT OF SCOPE) per the don't-flag set. NICE-TO-HAVE
  (logged FUTURE): tokenize the display:none dead rules (.csv-sugg-pickorder-cell
  16px, .csv-pb-mood-* 14/16px) + decorative-glyph normalization - non-rendering /
  decorative, deferred. TDD note: a CSS-only fixture audit has no failing-test-first
  target (no Python logic changed); the gate is the snapshot + render suite staying
  green. Gate (Tier-1 frontend per R5): RC tests/ 7982 passed / 2 skip / 109
  subtests, exit 0 (ZERO delta vs cycle 35/36 - a CSS edit cannot touch the Python
  logic suite); ASCII grep clean post-edit; no DS suite / Share / restart. VISUAL:
  Claude_Preview capture OWED - the preview MCP refuses to attach to the live
  pythonw :8888 (PID 2104) and freeing / duplicating the port would destabilize the
  running RC + this loop, so the visual is a carry-forward (per the directive's
  "live capture is OWED" + the EXCLUDED Game-PC :8892 note); render deltas proven
  deterministically instead (--fs-sm=18px byte-identical, --hit-min=42px floor). No
  frozen files touched. NEXT (plan order): UIX2 (Home + Settings 5-phase audit),
  then UIX3 (Session + detached-PGR).

- 2026-06-16 DSV3 DONE (commit 27873cc1, item 433). Lethality-vs-sustained-AD
  burst-ranker valuation - P6-G5 residual 3, Tier-2 ENGINE 1.125.0 -> 1.126.0, DS
  :8893 restarted -> 1.126.0, Share re-synced (339, --check in sync) in the SAME
  commit. ROOT CAUSE: rank_items_by_burst defaulted target_armor=0.0, and against
  zero armor effective_target_armor floors its penetration tail at zero - so
  lethality (flat armor pen, Riot V14.1 1:1) contributed NOTHING to a ranked item's
  delta and an equal-cost raw-AD item out-ranked a lethality item. A burst assassin's
  real target is a squishy carry WITH armor. FIX (DEFAULT-OFF assume_squishy_target
  seam, byte-identical off; INLINE sole orchestrator per directive + R9, verifier
  GATE PASS 7/7): burst.py NEW _assumed_squishy_target_armor(level) (22 base + 4.5
  per level -> 67 at L11) + assume_squishy_target on rank_items_by_burst; when ON and
  the caller did not pin a positive target_armor, the assumed squishy armor is
  substituted for the baseline AND every candidate so lethality flows through
  effective_target_armor and out-values raw AD; an explicit target_armor>0 is
  respected. Lethality math itself unchanged (effects.effective_target_armor) - only
  the ranker target assumption is refined. Ships DEFAULT-OFF; live rank scorers do not
  pass assume_squishy_target=True yet (validation-gated flip). TDD: new 7-case
  characterization test (difference-of-differences, not fragile cross-item). Gate:
  DS-dir 7126 passed / 1 skip / 1942 subtests; tests/ green after DS restart +
  ds_share_sync (the 7 pre-fix failures = 1 live-:8893 stale-version + 6 Share
  doc/ingest anchors, all 18 green re-run); 75 quoted pins bumped across 67 files;
  CHANGELOG prepended. No frozen files touched. NEXT (plan order): UIX1/2/3 (5-phase
  UI audits).

- 2026-06-15 DSV2 DONE (commit f1075c38, item 432). Takedown / kill-state item
  passive valuation - P6-G5 residual 2, Tier-2 ENGINE 1.124.0 -> 1.125.0, DS
  :8893 restarted, Share re-synced (338, --check in sync) in the SAME commit.
  GAP (P6-G5 ledger 424): the burst + auto scorers had NO seam for the on-takedown
  item passives, so Hubris (Eminence bonus AD) + The Collector (5% execute) were
  under-ranked among lethality items (Hubris ~#13, Collector ~#12 live). FIX adds a
  DEFAULT-OFF kill-state OFFENSE seam, byte-identical when off: NEW ItemEffect
  fields takedown_bonus_ad_base / takedown_bonus_ad_per_stack (Hubris Eminence
  15 + 2/stack, Meraki 16.12.1) + execute_max_hp_pct (Collector Death <5% target
  max HP); NEW effects helpers total_takedown_bonus_ad(stacks) +
  total_execute_max_hp_pct; dps._ASSUMED_TAKEDOWN_STACKS=1 + an assume_takedown
  kwarg on compute_dps (folds Hubris bonus AD into rotation AD + bonus_ad ctx ->
  higher AA DPS; Collector execute deliberately NOT credited - a one-shot finisher
  is not sustained DPS) and on compute_burst_damage + rank_items_by_burst (threads
  into the internal AA probe + the ability ctx so Hubris AD raises BOTH ability and
  AA, and credits the Collector execute as a 5% target-max-HP TRUE finisher
  execute_finisher_damage folded into total_burst_damage). NEW BurstResult fields
  mirror the rune_proc_damage convention (0.0 default = byte-identical). DESIGN
  GUARD (root-cause-honest): Death's Dance carries NEITHER offense field - its
  takedown payoff is the Defy HEAL, already valued on the survivability axis
  (ehp.py ItemHeal.takedown_gated, ENGINE 1.57.0); crediting it offense here would
  double-count phantom damage, so the seam is a deliberate no-op for DD (test pins
  this). Data wired: Hubris 6697/226697/126697 + Collector 6676/667666/226676.
  ORCHESTRATION (auto-pick, logged): INLINE sole orchestrator (the seam is one
  coupled contract across 6 engine files - schema + 2 scorers share assume_takedown;
  R9 + the DSV1/OVL2 precedent); verifier subagent SKIPPED per R7 (single-thread
  inline edit, no stale pipe) - fresh re-verify done instead (DS suite + RC suite +
  the 7 expected post-restart/sync failures re-run green). TDD: 16 Meraki-anchored
  tests red-first (ImportError on _ASSUMED_TAKEDOWN_STACKS) -> green: schema
  defaults, data pins, helper math, OFF byte-identical (dps + burst + rank), Hubris
  DPS/burst raise, Collector execute = 100 vs 2000 max HP folded into total, DD
  offense byte-identical (no phantom). Gate: DS-dir 7119 passed / 1 skip / 1942
  subtests; RC tests/ 7982 passed / 2 skip / 109 subtests (the 7 pre-fix failures =
  1 live-:8893 stale-version integration + 6 Share doc/ingest anchors, all green
  after the DS restart + ds_share_sync, re-run confirmed); ruff + py_compile clean;
  ds_share_sync --check in sync. ENGINE bump touched 75 assertion pins; 2 historical
  DSV1 (1.124.0) changelog refs deliberately kept (engine_bump_quoted_literal_only).
  SEAM-FIRST scope (per directive + EXCLUDED): the seam ships DEFAULT-OFF; the live
  rank scorers (rank.py) do NOT pass assume_takedown=True yet - flipping it ON is a
  separate real-game-validation-gated step (DS Phase-D default-ON flag-flip class).
  NEXT (plan order): DSV3 (lethality-vs-sustained AD in burst.py), then UIX1/2/3.

- 2026-06-15 DSV1 DONE (commit 597ffc95, item 431). AP damage-over-time burn
  valuation - P6-G5 residual 1, Tier-2 ENGINE 1.123.0 -> 1.124.0, DS :8893
  restarted, Share re-synced (337) in the SAME commit. ROOT CAUSE:
  compute_ability_dps (the AP/mage item scorer) mirrors compute_dps's item amp +
  pen handling but never folded the item PERIODIC procs, so ability-triggered AP
  burn DoTs (Liandry Torment, Blackfire Baleful Blaze, Demonic Azakana) were
  invisible to the mage ranking even though the auto scorer has valued them via
  _periodic_proc_dps since Phase 4 - the exact P6-G5 "AP DoT burn vs single-
  rotation ability model" gap (Veigar/Lux Liandry buried ~#23). FIX completed the
  mirror: PeriodicProc gains an ability_dot flag (default False = byte-identical);
  _periodic_proc_dps gains ability_dot_only (default False = compute_dps byte-
  identical); compute_ability_dps folds ability_dot proc DPS into
  total_ability_dps. Data: ADD Liandry Torment (6653 + Arena 226653) 2% target max
  HP/s magic (Meraki 6% over 3s, the Azakana sibling); FIX Blackfire Baleful
  (2503 + Arena 222503) to the Meraki total 60+6%AP/3s = 10+1%AP per 0.5s tick
  (prior 6+6%AP mis-read the wiki {{ap|60/6}} tick-count as a melee/ranged split);
  TAG Demonic Azakana (4637 + Arena 224637) ability_dot. DESIGN GUARD: the first
  cut folded ALL time-based procs -> polluted the mage ranking with tank Immolate
  auras (Sunfire), physical spellblades (Iceborn/Trinity Force), on-cast nukes;
  narrowed via the curated ability_dot tag (the _AA_ROUTED_ON_HIT_KEYS allowlist
  precedent) so only the 3 named/sibling burn families lift. LIVE-PROVEN: Veigar
  L11 SR mage ranking now Liandry #1 (delta 45.5) at target_max_hp=2500, Blackfire
  #1 at tmh=0; no pollution. ORCHESTRATION (auto-pick, logged): INLINE sole
  orchestrator (4 coupled engine files share one proc contract; R9 + OVL1/OVL2
  precedent); verifier subagent SKIPPED per R7 (single-thread inline edit, no stale
  pipe) - fresh re-verify done instead. TDD: 8 Meraki-anchored tests red-first ->
  green. Churn fixed: 2 Blackfire data pins + 1 LiandrysSuffering pin re-pinned to
  Meraki; 3 rank_mage ranking pins resolved by the ability_dot narrowing (no test
  edit). Gate: DS-dir 7103 passed / 1 skip / 1942 subtests; RC tests/ 7981 passed /
  2 skip / 109 subtests (lone failure = pre-restart live-:8893 version assertion,
  green post-restart); ruff + py_compile clean; ds_share_sync --check in sync.
  FUTURE (untagged, deliberate scope line): Luden's / Malignance / Stormsurge /
  Night Harvester (magic on-cast/ult-zone, not sustained DoTs) + Pyromancer's Cloak
  (Arena flat burn). NEXT (plan order): DSV2 (kill-state passives, burst.py seam),
  then DSV3, then UIX1/2/3.

- 2026-06-15 OVL2 DONE (commit aab53e37, item 430). Electron Phase 6 Pengu
  Surface-C code-only stub + client-origin-gated CORS. NEW pengu/ Pengu Loader
  plugin skeleton (ESM index.js + panel.css + README): runs in the League client
  UX (not served by :8888), fetches RC_ORIGIN/api/state every 2s (RC_ORIGIN default
  https://127.0.0.1:8888, localStorage rc_origin override), injects the dashboard
  tokens (tokens.css from RC_ORIGIN) + a sibling panel.css via import.meta.url,
  renders a mode/champion/coach card, fail-soft "RC offline" with NO raw API error
  surfaced. dashboard/_handler.py (non-frozen): NEW _cors_allowed_origin gate +
  _send echoes Access-Control-Allow-Origin + Vary:Origin ONLY for an allowed
  cross-origin client (loopback 127.0.0.1/localhost/::1, or an exact
  RC_CORS_ALLOW_ORIGINS env allowlist), NEVER wildcard (distinct from the
  vision_server :8889 "*"). Cross-origin POSTs still blocked by _csrf_ok; ACAO only
  governs READING GET responses -> echoing a same-machine loopback origin is a
  controlled LAN-only widening. ORCHESTRATION (auto-pick, logged): INLINE sole
  orchestrator (2 coupled disjoint slices, ~6 files sharing the CORS-origin
  contract; R9 + the OVL1/HZ-A2 precedent) + the read-only verifier subagent as the
  pre-commit ground-truth gate (ALL 6 CONFIRM: 13 new tests fresh, gate present +
  grep-proven no "*", ASCII clean, full suite green). TDD (CORS test red on the
  missing _cors_allowed_origin import -> green). +13 tests (test_handler_cors 7 +
  test_pengu_plugin_skeleton 6). 5-phase pengu UI audit CODE-SIDE (panel not served
  by :8888 -> no Claude_Preview capture): MUST-FIX 0; 2 SHOULD-FIX applied in-slice
  (panel.css border-radius 8px -> var(--panel-radius, 18px), resolves live from the
  injected tokens.css; + a precise comment that the surface vars
  --fg/--panel-bg/--panel-border/--font-ui are fallback-only since the primitives
  layer is not injected in-client). Gate (Tier-1 frontend + route): RC suite 7982
  passed / 2 skipped / 109 subtests, exit 0; ruff + py_compile clean; RC restarted
  pid 2104 last_reload_ok (handler re-import). No engine/DS/Share change
  (ds_share_sync N/A - 0 DS file touched). OWED: the live in-client visual (League
  client + Pengu Loader; no client in the headless run). NEXT (plan order): DSV1
  (P6-G5 AP DoT/burn valuation), then DSV2/DSV3, then UIX1/2/3.

- 2026-06-15 OVL1 DONE (commit 4d09f8ac, item 429). Electron Phase-4 overlay
  settings: a change-pulse toggle + an ACTIVE auto-revert-seconds control on the
  ?overlay=1 surface, persisted in-page (web/js/lib/overlay_settings.js,
  localStorage) and mirrored to the rc-shell config over a NEW preload
  window.rcShell IPC bridge. Both settings got REAL consumers (not inert):
  pulseNotify gates the existing web/js/overlay_pulse.js change-glow; activeRevertSec
  replaces the hardcoded 20s in the rc-shell main-process auto-revert. rc-shell
  was Phase-1 for renderer<->main (empty preload) - this added the first IPC
  bridge. Implemented INLINE (sole orchestrator) rather than fanned worktree
  slices: the two file sets (web vs rc-shell) share a tight IPC contract and
  rc-shell node_modules is gitignored (a worktree could not run npm test), so a
  single coherent implementation + a fresh full-suite gate was the safer call
  (R9). Gate: rc-shell 163 node tests (+13 settings cases +IPC wiring pins), RC
  7969 + new DOM-contract test + a Playwright pulse-suppression gate test; 5-phase
  UI audit PASS (0 MUST-FIX, rendered proof from the overlay snapshot). OWED:
  in-game visual over a real match (Game-PC MCP :8892 down post-1PC).

- 2026-06-15 PLAN REFILL (operator-directed, loop relaunch). The A1-F1 + HZ + LIFT/LOBBY/CS +
  P6-G1/G4/G5 set was fully DONE/CLOSED, so the director emitted NO_WORK and the loop stopped.
  Operator scope: Electron overlay + DS improvements + UI/UX uplift/research/expansion/audits.
  8 new OPEN sessions seeded (Gemini gemini-3-pro-preview planning pass, gemini_io/answer_20260615-204352.md,
  paths operator-verified live): OVL1 Electron Phase-4 overlay-settings, OVL2 Pengu Surface-C code-stub +
  CORS, DSV1/2/3 the P6-G5 scorer-valuation residual (AP DoT-burn / kill-state passives / lethality-vs-sustained,
  each a bounded ENGINE-bump slice), UIX1/2/3 5-phase audits (champ-select SR / Home+Settings / Session+detached-PGR).
  All headless-safe; live-visual capture marked OWED, no EXCLUDED/Settled item proposed.

- 2026-06-15 P6-G5 CLOSED as NO POOL GAP (cycle 27, item 424, Tier-0 diagnosis - docs/probes only,
  no ENGINE bump / regen / DS restart / Share sync). The sweep's G5 hypothesis ("DS per-archetype
  pool is missing lethality / AP-on-hit / mythic-less items vs item.json") is FALSE. Root-caused via
  durable probes (ops/audit/lolmath_ds_sweep/g5_pool_probe.py + g5_live_rank_probe.py), verified LIVE
  at ENGINE 1.123.0: (1) DS has NO per-archetype pool whitelist - the candidate set is
  rank.py::_filter_candidates over ALL 706 items.json (purchasable + terminal `into`-empty +
  map-legal + budget + a 2-item deny-set). (2) Of 48 lolmath-favored items, REAL SR pool gaps = 0 -
  all resolve to a canonical map11 id and are live candidates (probe v1 false-flagged 42 via the
  6-digit 22../12.. Arena ALIAS ids map11=False; v2 collects ALL ids/name -> canonical short id is
  in-pool; memory reference_items_index_alias_ids). (3) Every "missing" item is IN the live ranking
  just below top-6 (Talon: Umbral #7 / Hubris #13 / Profane #33; Lux: Liandry's #23; Jhin:
  Collector #12). DS recommends only ~60 distinct items / 172 champs x 4 comps - the breadth gap is
  SCORER VALUATION (item passives needing kill/takedown state: Hubris/Collector/Death's Dance; AP
  damage-over-time burn vs the single-rotation `ability` model: Liandry's/Blackfire; lethality-vs-
  sustained tradeoff in `burst`), NOT pool membership; lethality pen itself is modeled (V14.1 1:1,
  effects.py:326). Decision: do NOT add items to a pool (none missing; a forced fix = churn +
  regression risk). Residual scorer-valuation work is design-level (G3/G6 class) -> Gemini-consult.
  NEXT P6 = G2 re-measure (after G1/G4); G3 runes / G6 cost-model / G7 harness + G5 residual =
  Gemini-consult first (G6 likely by-design CLOSED).

- 2026-06-15 P6-G1 REGRESS FIXED (cycle 2, commit `e6ab8db3`): gemini's cycle-1 audit correctly
  caught (and I ground-truth-verified) that item 421's ENGINE bump used a blind byte-replace of
  the BARE string "1.121.0" -> "1.122.0", corrupting 10 HISTORICAL "shipped in ENGINE 1.121.0"
  refs (the 2026-06-14 SUSTAIN contract-gap closure) in ehp.py (x4) + test_ehp_sustain_contract.py
  (x1) + test_wireable_sims_p1l3.py (x5). Reverted those 10 lines to 1.121.0 in the SOURCE files
  (Share re-synced); the 27 live assertEqual(ENGINE_VERSION,"1.122.0") pins + __init__ constant +
  the EngineVersionCurrentTests doc-pin (line 35, tracks the LIVE version) correctly KEEP 1.122.0.
  Swept ALL 38 non-assertEqual 1.122.0 lines (not just the 2 gemini named); post-fix 0 historical
  1.122.0 remain. DS suite 7095 passed, 17 Share tests passed, --check in sync. LESSON: an ENGINE
  bump must target the QUOTED assertion literal / ENGINE_VERSION-symbol lines, never the bare
  version string (historical changelog comments share the literal).
- 2026-06-15 P6-G1 NEW WORK SURFACED (FUTURE, -> BACKLOG): 6 champions are AP-dominant
  kits (Amumu 0.77 / Galio 0.93 / Nunu 0.88 / Singed 0.91 / TahmKench 0.75 / Blitzcrank
  0.61 magical) but resolve to the axis-neutral `tank` archetype, so G1's axis correction
  left them as tanks (tank kits want durability, not a glass-AP pivot). The lolmath sweep
  flagged them as "DS != AP" but converting a tank to a mage is a ROLE reassignment / split
  (jungle-tank vs AP-mid Amumu), a product-direction call - NOT an axis-correctness bug.
  Deferred: needs an operator decision on whether RC should offer a per-champ AP-mode for
  these (a secondary-archetype surface), not a blind default flip. Also confirmed: G1's rule
  is data-driven (champions.json), so future champs/patches self-correct - no champ list to
  maintain.
- 2026-06-10 CYCLE-4 REGRESS AUDIT REFUTED by ground truth + gate edge pins added.
  The cycle-3 audit claimed dashboard/_deterministic_coaching.py changed with no
  accompanying test and that tests/conftest.py + the gate tests were missing from
  the commit. FALSE: commit c7922951 (merged via d446ea80, inside the audited
  range 9ccc64fa..b5533f85) carries the lc.get("champion") gate AND
  tests/conftest.py (+36) AND tests/test_hz_shadow_live_gate.py (4 tests) in the
  SAME commit. Root cause of the false REGRESS: the auditor diffed only the tip
  commit b5533f85 (docs+data only), not the full cycle sha range with merges.
  Action: re-ran gate+wiring tests fresh (12 passed), then strengthened the gate
  with 2 edge pins (champion="" loading-screen edge; non-dict lc isinstance
  guard). RC suite 5789 passed / 2 skipped / 94 subtests, exit 0. No engine, no
  restart (test-only). LOOP IMPROVEMENT (FUTURE): the auditor should diff the
  full cycle range (prev done sha..new sha), not the tip commit.
- 2026-06-10 HZ-D4 DONE (item 386; merges d446ea80 + b54d040e, 2 PARALLEL worktree
  agents both verifier-CONFIRMED pre-merge). 7-LEVER SWEEP: 7/7 CLEAN, no net-positive
  cost fix exists. Levers 1-5+7 scout-verified (all messages.create callers carry
  cache_control; /api/ds-knobs cached 300s + 350ms client debounce; no sub-500ms network
  polls; log suppression healthy; all coaching Haiku, vision Sonnet charter-exempt; 44
  panel CSS == 44 dashboard.css @imports, overlay.css deliberately standalone via
  index.html link). Lever 6 scout flagged "orphan tasks" - REFUTED by ground truth
  (verify-before-declare-broken): RC-PatchRefresh -> scripts/data_pipeline.py all,
  RC-HotkeyListener -> tools/gamepc_hotkey_listener.py, RC-DS-MatchDB-MCP ->
  tools/start_ds_matchdb_mcp.py, all targets present on disk; installer-not-in-ops/ is
  not an orphan. HZ INCREMENT root-caused AWAY from the planned table-expand-only: a
  census of the HZ shadow logs found 100 PERCENT junk rows - 837 choice + 800 build,
  enemy=null on EVERY row, all idle-tick replays of STALE coach payloads (champ comes
  from the persistent coach dict; enemy_team only ever exists in a live liveclient), plus
  290 my_champion=Champ0 rows = every pytest build_state run was appending to the REAL
  data/ jsonls. The gated flip path (accrue shadow -> agreement -> flip) could NEVER
  accrue as wired. FIX slice A: live gate lc.get("champion") in BOTH
  shadow_log_precomputed_* + autouse tests/conftest.py fixture redirecting SHADOW_PATH
  (hz_choice/hz_build/det_coach) to tmp for every test; +4 gate tests; 3 wiring fixtures
  updated to live-shaped lc. BACKFILL (Data Fixes rule): both polluted jsonls rotated to
  _scratch/ (gitignored), accrual restarts clean. Slice B (item-369 tail): hz_shadow_report
  v2 agreement metric - classify_verdict 5-class keyword matcher + record_agreement +
  summarize_agreement (per-mode, uncovered_with_native, flip hint cites agreement rate);
  stale "no native capture yet" docstring fixed; 22 tests. ARAM TABLES (every native
  capture to date is mode=aram - ARAM is the binding constraint, not dead weight):
  full-roster 172 laning_scenarios_aram.json 65.75MB LFS + build_orders_aram 688 +
  build_order_variants_aram 344 at 16.12.1; read-path smoke Kaisa vs Viktor L6 ->
  back_off + economy block. GOTCHA: the gen CLIs default to the 10-champ SEED - the first
  run silently produced seed-only tables; full roster needs --champions <172-CSV> (pulled
  from the SR table's scenarios keys). RC suite 5787/2sk/0f + DS 7075/1sk/1xf both exit 0;
  RC restarted pid 14160. OPS FINDING: RC-Supervisor task was NOT running - restart_trigger
  sat unconsumed; schtasks /Run /TN RC-Supervisor restored it (the trigger file is the
  supervisor's input, not RC's). Flip path now unblocked: play ARAM -> covered=true accrues
  WITH native capture -> hz_shadow_report agreement gate -> operator flip decision.
- 2026-06-10 HZ-D3 STALE PREMISE - no unshipped Phase 4 control surface and no
  Phase 5 tail remain; flipped DONE with NO new code (loop run 2026-06-10,
  verify-premise-first, the HZ-D2 precedent one row up). Phase 4 spec checklist
  vs shipped code: ACTIVE toggle + 20s auto-revert (item 269/378) + ACTIVE
  edge-glow indicator (slice 2, active_indicator.js); change-pulse notifications
  = web/js/overlay_pulse.js wired at main.js:6217 (initOverlayPulse) + .ov-pulse
  keyframe overlay.css:269-279 (item 378); DS weight tweak + build reorder =
  slice 3 #am-pane-ovds 4 knobs + top-5 re-rank over /api/ds-knobs (live-proven
  armor-300 re-rank); A+B coach = #rn-choices mounts in overlay base + coach
  panelsets (overlay.css:154, suppressed only in threat:211), coach_choices.js
  renderer unchanged. Phase 5 list fully closed by slices 3+4 (smoke drift-guard
  + updater/channels + crash isolation, items 382/383). Ground truth THIS cycle:
  rc-shell suite fresh 145/145; tests/test_overlay_route_smoke.py fresh 19
  passed / 9 subtests. Remaining Electron work is all operator/live-gated (NOT
  headless-safe, NOT HZ-D3 scope): packaging + first GitHub Release + packaged
  update check, in-match overlay capture (shell relaunch picks up slices 1-4),
  Phase 6 Pengu (optional, plan EXCLUDED). No regressions, docs-only commit.
- 2026-06-10 HZ-D2 STALE PREMISE - scope already shipped inside HZ-D1; flipped DONE with
  NO new code (loop run 2026-06-10, verify-premise-first). The row's "frameless window has
  NO drag region today" predates HZ-D1 slices 1+2: companion drag strip = drag_region.js
  injected on every did-finish-load (main.js mainWindow handler; merge 0b2eea62 + 95-line
  test), user-moved position persisted move/resize/close via persistWindowState(+Now) and
  restored clamped-on-screen at createWindow (Phase 1 + D1), overlay drag-when-ACTIVE +
  position/panelSet persistence via ov.mergeOverlayPatch (merge 8116c6c2), click-through
  intact (setIgnoreMouseEvents forward:true + applyClickThrough + ACTIVE glow). rc-shell
  suite re-run this cycle: 145/145 green. No regressions, docs-only commit.
- 2026-06-10 HZ-D1 slice 4 = Phase 5 stabilization tail SHIPPED, HZ-D1 flipped DONE
  (loop run 2026-06-10-01 cycle 4, merges 96cf5241 + 544cff59 + integration 33dc9b3a;
  slice commits c1fde16e + da5c0f9a, 2 PARALLEL worktree agents, both verifier-CONFIRMED
  pre-merge). Update channels: NEW rc-shell/src/update_channel.js (resolveChannel env
  RC_SHELL_CHANNEL > saved > stable; channelConfig dev=allowPrerelease; mergeChannelPatch;
  checkPlan not-packaged/updater-missing/15s-initial+4h-interval) + electron-updater ^6.3.9
  lazy-required in main.js (bare-checkout + unpackaged = gracefully disabled, console-only
  events, autoInstallOnAppQuit - NEVER mid-session restart), Shell-menu channel radios +
  Check-now, electron-builder.yml (nsis, publish github Remus3/riot-commander,
  generateUpdatesFilesForAllChannels). Crash isolation: NEW rc-shell/src/crash_guard.js
  (RESTART_REASONS crashed/oom/abnormal-exit/launch-failed/integrity-failure; killed +
  clean-exit NEVER resurrect; makeCrashGuard per-key rolling budget 3/60s -> give-up hides
  instead of strobing a half-dead HUD) wired by the merger: attachCrashGuard on BOTH
  windows (render-process-gone -> reload | hide; unresponsive logs only). package.json
  0.4.0; node suite 109 -> 145/0 (TDD red-first both slices); npm install restored deps
  (electron-updater resolvable; bare node require throws inside the getter by design -
  the try/catch path is load-bearing). RC 5769p/2sk + DS 7075p/1sk/1xf both exit 0.
  Phases 1-5 are now ALL shipped code-side. REMAINING (not HZ-D1-blocking): Phase 6 Pengu
  (optional, operator-gated dependency); OWED live: packaging + first GitHub Release +
  packaged-app update check (operator), in-match overlay capture (shell relaunch picks up
  slices 1-4).

- 2026-06-10 HZ-D1 slice 3 (loop run 2026-06-10-01 cycle 3, merges 85c54ba3 + 141c1333 +
  audit-fix bc8c94d3): Phase 4 in-overlay DS controls SHIPPED - #am-pane-ovds FIGHT MODEL
  pane (overlay-only; base+build panelsets) over GET /api/ds-knobs, 4 knobs + top-5
  re-ranked rows = build reorder; proof live on :8888 (armor 300 re-ranks). Two real bugs
  fixed in-slice: item-NAME vs id 503 (bridge via items_index._resolveItemId) + cascade
  leak (two-id display:none). Phase 5 starter shipped: tests/test_overlay_route_smoke.py
  shell<->web PANEL_SETS drift guard. REMAINING in HZ-D1: Phase 5 stabilization tail
  (electron-updater + stable/dev channels, crash isolation); OWED live: in-match capture
  (shell relaunch picks up slices 1-3).

- 2026-06-10 HZ-D1 slice 2 (loop run 2026-06-10-01 cycle 2, merge 8116c6c2): overlay
  position/panelset persistence + Phase 4 ACTIVE indicator. NEW pure helpers in
  overlay_state.js (overlayStateFrom / resolveOverlayBounds / mergeOverlayPatch -
  rc-shell-state.json gains an "overlay" sub-object, companion keys preserved) +
  NEW active_indicator.js (shell-injected edge-glow, pointer-events:none,
  html.rc-shell-active class) toggled inside applyClickThrough so the operator can
  SEE ACTIVE vs PASSIVE incl. the 20s auto-revert. main.js: overlay docks from
  saved coords (clamped) else right-edge default; 400ms-debounced move persist;
  panelSet restored at boot + persisted on Alt+Shift+C. node 85 -> 109/0 (TDD 16
  red first). REMAINING in HZ-D1: Phase 4 in-overlay DS controls (weight tweak /
  build reorder - needs a dashboard-side web/ slice + UI audit), Phase 5
  stabilization; OWED live: glow + drag-restore capture in a real match (running
  shell instance predates slices 1+2; relaunch picks both up).
- 2026-06-10 HZ-D1 slice 1 (loop run 2026-06-10-01, merge 0b2eea62): the
  frameless companion was never draggable - Phase 1 deferred the drag region to
  "CSS in the page" and the dashboard never got one. Shipped shell-side instead:
  NEW pure module rc-shell/src/drag_region.js (CSS + idempotent mount JS),
  injected by main.js on did-finish-load via webContents.insertCSS +
  executeJavaScript - no dashboard change, preload stays empty (sandbox:true
  preloads cannot require local modules, so the preload route is a dead-end).
  Overlay gets the same injection: inert while click-through, grabbable when
  ACTIVE = the overlay is now user-movable (a Phase 4 interactive control).
  Overlay position is NOT persisted yet (companion position is) - candidate for
  the next D1 slice. Live drag-feel capture OWED (headless run). node 77 -> 85.

- 2026-06-09 HZ-C1 STALE-PREMISE -> plan flipped DONE (commit 3581afed, LEDGER
  item 366). The director flagged it (3581afed may have shipped); VERIFIED true
  (the D1/D2/B1 stale-shipped trap). HZ-C1's full scope shipped 2026-06-09 01:56
  in a separate /gemini-headless-upgrade run (run 2026-06-09-01): NEW
  core/precomputed_laning_coach.py (one HZ-A laning cell -> two grounded A/B
  CoachChoice, pure static read, no Haiku / no :8893) + core/hz_choice_shadow.py
  (shadow-log alongside live Haiku, seed-coverage hits/misses) wired into
  dashboard/_state_builder.py via
  _deterministic_coaching.shadow_log_precomputed_choices (additive, fail-soft, NO
  live output change); +48 tests. GROUND TRUTH this cycle: all 6 deliverable files
  present on disk; the 3 HZ-C1 test files (test_precomputed_laning_coach.py /
  test_hz_choice_shadow.py / test_hz_c1_wiring.py) 50/50 PASS fresh; LEDGER item
  366 + ROADMAP line 20 + WAKEUP already synced for the whole HZ-C arc (commits
  72e5bf0d + 41750fa1) - ONLY this plan's HZ-C1 row (OPEN) + findings were never
  flipped. NO code change (re-implementing would clobber the live item-366 module
  + 48 tests). NO new LEDGER item (a stale-premise doc flip is not an item
  completion - the A2b/HZ-A1 false-alarm precedent below). The rest of the HZ-C
  arc was DISCOVERED + shipped the same run (NOT plan rows, so the director cannot
  re-pick them; all ledgered): HZ-C2 build A/B over HZ-B2 (item 367, 5627053b),
  hz_shadow_report flip-readiness gate (item 368, 1d116194), native coach-signal
  capture (item 369, 1f702711), full 171-champ SR seed expansion + slim/compact v3
  schema (item 370, 4202760c; laning JSON now LFS-tracked,
  reference_git_lfs_laning_artifact). BUILD + PERSIST + SHADOW only; the live coach
  flip stays EXCLUDED (charter 4b do-not-flip-blind). NEXT OPEN = HZ-D1 (Electron
  overlay Phase 2+); the gated post-HZ-D path is real-game shadow accrual ->
  precompute-vs-Haiku agreement (item-369 native capture) -> the coach flip.
- 2026-06-08 HZ-B2 DONE (commit 8d8bc311) + draft-elo clean-checkout test fix
  (d9347d62, item 363). HZ-B2: anti_tank vs anti_squishy build-order VARIANTS layered
  on HZ-B1 via the DS anti-tank axis (A3, core/ds_antitank_hint). Single coupled engine
  slice (1 worktree agent + merger ground-truth verify). DISTINCT from HZ-B1's fixed
  comp-shape biases: the two durability EXTREMES as a champion-decision pair, each
  modulated per champ by the A3 anti-tank score (a kit that already shreds -> softer
  synthetic wall). SIBLING module core/build_order_variants.py (keeps HZ-B1's schema +
  23 tests byte-identical) -> data/daemon_slayer/build_orders/<patch>/
  build_order_variants_<mode>.json (10-champ SR seed x 2 = 20 cells). +28 tests. BUILD +
  PERSIST only. MERGER independently re-probed the agent's "1 pre-existing failure"
  claim: test_target_state_caller_p1l4.py::test_live_items_path_only_wired_to_ds_preview
  is a WORKTREE-PATH artifact (the test skips any path containing .claude, so a checkout
  under .claude/worktrees/ skips the whole tree); it PASSES on main (full tests/ 5529
  passed / 0 fail). Earlier this turn (operator-flagged) the draft-elo + ban-suggest
  tests (16 fail + 6 err on a clean checkout) were fixed root-cause (item 363): they
  depended on the gitignored live rewind_history.db; open_ro now honors an RC_REWIND_DB
  env override + a self-contained tests/_draft_elo_fixture.py. Memory
  feedback_clean_checkout_probe written (I had wrongly dismissed the same cluster as a
  worktree artifact at item 362; the operator was right - reproduce the clean condition
  before dismissing a fresh-env failure). **NEXT OPEN = HZ-C1** (deterministic A/B
  choice-coach over HZ-A/HZ-B, shadow-log, no flip), then HZ-D1.
- 2026-06-08 HZ-B1 DONE (commit 3a129071; + cc_pairing guard fix 76691def).
  Lane B build-order precompute per (champ x mode x enemy-comp-archetype). Single
  coupled engine slice (1 worktree agent + merger ground-truth verify, the HZ-A2
  precedent). CONFIRMED-NEW-AXIS: the shipped build_orders_{sr,aram,arena}.json
  (item 265/266) key on a DAMAGE-PROFILE axis (ad/ap/balanced over a CONSTANT enemy
  stat block), NOT enemy-comp-archetype - HZ-B1 varies the enemy stat SHAPE.
  TAXONOMY (4 classes re-parameterizing plan_build_order levers): frontline_heavy /
  burst_heavy / poke / mixed. NEW core/build_order_precompute.py (generator + reader +
  CLI, HZ-A1 idioms) -> data/daemon_slayer/build_orders/<patch>/ (NEW subdir, the
  item-265/266 table untouched); 10-champ SR seed x 4 = 40 cells. +23 characterization
  tests. BUILD + PERSIST only (live coach flip EXCLUDED, charter 4b; read by HZ-C1).
  MERGER CAUGHT a REAL CS1 regression the subagent dismissed as "pre-existing":
  agents/daemon_slayer/tests/test_cc_conditional_forward_marker.py::NoConsumerWireTests
  failed on main - cc_pairing.py (item 359) wired a new cc_conditional consumer without
  updating the operator-gated forward-marker allowlist. CI MISSED it (CI = py_compile +
  ruff + Share-check only, NO pytest; the CS1 gate ran tests/ but not the DS-dir suite).
  Fixed (76691def, cc_pairing -> _ALLOWED_SOURCE_FILES, the operator CS1 request is the
  gate-crossing) + Share re-synced. The subagent's "tests/ 16 failed + 6 errors" was a
  worktree-missing-gitignored-data artifact, DISPROVEN: merged-main tests/ 5501 passed /
  0 fail, DS-dir 7043 / 0, ds_share_sync --check green, ENGINE 1.120.0. PROCESS NOTE: CI
  does NOT run pytest - the local gate MUST run BOTH tests/ AND agents/daemon_slayer/tests/
  before declaring green. **NEXT OPEN = HZ-B2** (anti-tank/anti-squishy variants), then
  HZ-C1 / HZ-D1.
- 2026-06-08 CS3 DONE (commit d68cddd3). Moved the 4 DS analysis panels OFF
  champ-select to the Active Match view (operator-chosen destination via one framed
  AskUserQuestion). Single coupled UI slice (1 worktree agent + merger verify). MAPPED
  by rendered title: combo timeline = csv-sugg-ds-combo, dps scaling = csv-sugg-ds-sweep,
  fight model = csv-sugg-ds-matchup (the 1v1 verdict, the only fight panel), relative
  item power = csv-ds-relscore. LEFT on champ-select: ds-profile / ds-knobs / ds-statcheck
  + the CS1 cc-pairing. RELOCATE not teardown - mounts moved index.html (same ids, routes
  + render fns UNCHANGED), invocations moved champ_select.js -> active_match.js fed a
  synthetic champ-select state from the LIVE coach payload (my_champion via the canonical
  _resolveChampId/CHAMPS.byId, matchup enemy = first liveclient enemy, relscore = owned
  items), fail-soft hidden with no live data. The merge full-suite gate caught the slice's
  lone red - a BRITTLE test (test_spike_curve.py::test_active_match_uses_champs_for_id_lookup
  exact-substring `import { ITEMS, CHAMPS }` broke when CS3 appended _resolveChampId to that
  destructure); robustified to a regex, intent preserved (CHAMPS.byId guard untouched). Full
  RC tests/ 5478 passed / 2 skip / 0 fail; ruff + node --check clean; 5-phase audit PASS on
  BOTH pages. OWED (live-gated): in-game visual capture of the 4 panels populated at once.
  The operator UI/UX batch (LOBBY1..CS3) is now FULLY SHIPPED. **NEXT OPEN = HZ-B1** (Lane B
  build-order precompute), then HZ-B2 / HZ-C1 / HZ-D1.
- 2026-06-08 HIST1+HIST2 + CS1 + CS2 DONE (3 parallel disjoint-file worktree
  slices, merged + full-suite-verified; commits ac404c13 / 541cd9d3 / 29cd2788).
  Operator "continue next open items in parallel". The merger cherry-picked the 3
  worktree branches onto main (web/index.html auto-merged clean - HIST added a new
  #view-historical-pgr section, CS1 added a champ-select mount div, non-overlapping
  hunks), then re-ran on the MERGED tree: 99 new+engine tests green + full RC tests/
  5455 passed / 2 skip / 0 fail (the lone red was the PRE-EXISTING ROADMAP doc-size
  budget red, untouched by the merge, cleared this commit by trimming the line-22
  batch entry); ruff + node --check + py_compile clean on every changed file; RC
  restarted pid 16308 reload_ok. All 3 had REAL premises (NOT the D1/D2/B1 stale-
  shipped trap). **HIST1+HIST2** (item 358): the Session/History match rows were
  inert (no click handler) + the PGR builder was latest-only; added match_ts to
  _build_last_match + ?match_ts= to /api/last-match + a NEW detached
  #view-historical-pgr (own hpgr- state, the live last-match PGR provably
  unclobbered). **CS1** (item 359): cc_conditional was saturated but only surfaced
  as scalars; NEW agents/daemon_slayer/cc_pairing.compute_cc_pairing join + GET
  /api/cc-pairing + a champ-select pairing panel (which ally enables the picked
  champ's conditional CC). **CS2** (item 360): the LCU summoner-spell push was gated
  behind a SUCCESSFUL rune-page write (skipped on the 3-page-cap failure, item 210);
  made it self-correcting + rune-independent in RuneWriter._poll() (Flash+TP SR /
  Flash+Snowball ARAM, PATCH only on a live mismatch). OWED (live-gated): CS1
  champ-select visual capture + CS2 real-champ-select end-to-end Flash+TP correction.
  CS3 was DEFERRED from this parallel batch (it edits champ_select.js + index.html,
  the same files CS1 touches -> guaranteed worktree merge conflict; sequence it AFTER
  CS1 landed). **NEXT OPEN = CS3** (move combo/dps/fight-model/item-power panels OFF
  champ-select, relocate-only), then HZ-B1.
- 2026-06-08 LIFT1 DONE (commit 4b15b031, docs/COMPETITOR_LIFT_2026-06-08.md).
  Deep-dive lift review (2 heavyweight agents, 6-point checklist, every HAVE/WHERE
  premise re-verified live) of the seb16120 target-vs-opponent stat advisor +
  simulator tool R.com (+ r/simulator tool R). VERDICT: RC SUPERSEDES both - simulator tool R's
  full surface (combo / 1v1 / DPS-TTK / EHP / build-sort / sandbox) already shipped
  via the 2026-05-30 calc.gg lift (combo.py / matchup.py / dps.py / fight_report.py +
  ds_combo.js / ds_matchup.js); the stat advisor is a manual-entry defensive-EHP calc
  RC beats automatically (ehp.py + core/defensive_picks.py + the live
  cc_blended_ehp_threat panel). NO HIGH-lift+LOW-risk finding -> per the ACT gate
  (MED/LOW always defer) NO in-run code slice. 2 FUTURE gaps -> BACKLOG: T1-F3
  enemy-pen-aware effective resists (ehp.py compute_ehp documented Phase-1 omission;
  MED engine schema lift, operator-gated) + T2-F4 rune/keystone in the combo SURFACE
  (routes_ds_combo.py threads no runes= param; MED route+panel wire-up + Sec-3b UI
  ritual). Minor deferred: T2-F3 TTK headline, T1-F4 per-stat EHP/gold. Docs-only:
  DS 7024 / RC 5352 passed, 0 regressions. NEXT OPEN = the operator UI/UX + bug
  batch (LOBBY1..CS3), then HZ-B.

- 2026-06-08 OPERATOR UI/UX + BUG BATCH queued (mid-loop interrupt, post-HZ-A2).
  The operator supplied a batch of page-specific issues to work NEXT; added as OPEN
  sessions (placed ahead of HZ-B so the loop picks them in upcoming cycles, after
  LIFT1): LOBBY1 (top-8 invite broken), PGR1 (s220 PGR reframe next stage), REPLAY1
  (match ingestion stale after each game), HIST1 (session/history match-row click is
  a no-op), HIST2 (detached historical PGR frame, separate from the live PGR), CS1
  (missing CC-conditional pairing UI on champ select), CS2 (summoner-spell defaults
  wrong on first champ-select load - investigate an LCU auto-push), CS3 (move combo
  timeline / dps scaling / fight model / relative item power OFF champ select). The
  "Continue ELECTRON_OVERLAY.md roadmap" item = the EXISTING HZ-D1 session (not
  duplicated). Several are LIVE-GATED (LOBBY1 / REPLAY1 / CS2 need a real lobby /
  game) + several touch a page (Section-3b UI-audit + visual required). Each row is
  framed INVESTIGATE-ROOT-CAUSE-FIRST; the executor verifies the premise live before
  fixing (some may be stale-premise, the D1/D2/B1 pattern). Operator can reorder via
  the loop control panel.
- 2026-06-08 REPLAY1 DONE (commit 647b455e). Replay / rewind ingest froze at
  2026-05-23 while the operator kept playing. ROOT CAUSE (verified live):
  scripts/rewind_catchup.py::resolve_current_puuid derived the account from the
  DB MAJORITY puuid - after the operator switched Riot ID (SamplePlayer#Vayne ->
  #Trist) the DB stayed dominated by ~2900 old-account rows, so resolution kept
  re-locking the OLD account + never discovered the new one (the new account has
  0 rows yet = chicken-and-egg). lib/rewind_live_writer.py read the stale puuid
  from rewind_catchup.state.json + only saw already-ingested old matches -> every
  90s post-gameEnd write was a silent already_present no-op. Probed: state puuid
  -> old Vayne (old URF matches, all in DB); current Trist account had 37
  un-ingested matches; get_account_by_riot_id("SamplePlayer","Trist") -> the right
  puuid with recent games. FIX: a persisted `riot_id` in the state sentinel is an
  authoritative sticky override - resolve_current_puuid resolves it via Account-V1
  BEFORE the DB-majority fallback (new priority step 3); main() persists
  args.riot_id. DATA RECOVERY (same fix): ran catchup --riot-id "SamplePlayer#Trist"
  -> state.json corrected (puuid+riot_id), 37 matches backfilled, rewind DB newest
  2026-05-23 -> 2026-06-08; live writer now resolves the current account
  (verified _resolve_latest_puuid). TDD tests/test_rewind_catchup_puuid.py (7)
  pins the priority order. RC suite 5376 / 2 skip / 0 fail; ruff clean. Backend +
  data only (no UI - replay page reads the now-fresh DB unchanged); state.json +
  rewind_history.db are gitignored (not committed). LIVE end-to-end (next-game
  auto-ingest) OWED. FUTURE (robustness): the live writer still reads puuid from
  state.json - a future account switch needs one catchup --riot-id run (or wiring
  the live LCU current-summoner Riot ID into the writer) before auto-ingest
  resumes; logged not built.
- 2026-06-08 PGR1 DONE (commit c162e5bd). s220 PGR reframe: shipped the last
  deferred S5 piece - per-player gold@10 / cs@10 in the lane-comparison card.
  DISCOVERY: S2/S3/S4 + the S5 Arena-augment loadout variant (pgr_loadout.js)
  were ALREADY shipped + wired (the PGR_REFRAME_S2.md staging doc was just not
  synced); the genuine gap was the @N lane head-to-head S4 punted as "no
  per-participant timeline". GROUND TRUTH: rewind_history.db.timeline_frames
  (664752 rows) AND the Match-V5 timeline both carry per-participant frames
  (total_gold + minions_killed + jungle_minions) - the team-aggregate series was
  a reducer choice, not a data gap. FIX: _enrich_match_timeline emits an `at_n`
  per-participant snapshot (frame nearest 10 min; sub-10-min -> last frame);
  _fold_at_n_into_roster copies gold_at_n/cs_at_n/at_n_minute onto each roster
  row (called from _attach_match_timeline); pgr_lane_compare.js leads with
  gold@N / cs@N head-to-head rows (reuses _rowHtml grid), degrades to final-only
  when absent. TDD +6 timeline tests + DOM/fixture flip of the stale "deferred"
  guard. RC suite 5369 / 2 skip / 0 fail; ruff + node --check clean; 5-phase UI
  audit PASS (0 MUST-FIX); verifier CONFIRM (the lone REFUTE was a mis-worded
  ruff claim on my side - .py ruff clean, not a code defect). Backend Python
  module -> RC restarted (pid 3292, last_reload_ok). VISUAL CAPTURE OWED
  (carry-forward): Game-PC :8892 MCP down (project_gamepc_mcp_boot_gap) +
  Claude_Preview can't attach the self-signed HTTPS :8888 - capture the @N row
  via ?ui_mock=1#last-match next time a visual path is up. S5 residual (FUTURE,
  minor): responsive polish; ARAM/Arena lane-compare stays hidden by design.
- 2026-06-08 LOBBY1 DONE (commit 1f4f4118). Top 8 / friends invites silently
  failed ("could not resolve summoner: <rid>"). ROOT CAUSE: lobby.invite_player
  (tools/gamepc_lcu_agent.py, non-frozen) resolved Name#TAG -> summonerId ONLY via
  /lol-summoner/v1/summoners/by-name/<name>, which Riot removed in the Riot ID
  migration (404s on current clients); the Top 8 add-flow (main.js:5003) only
  captures Name#TAG (no summonerId/puuid) so the dead path was the SOLE route ->
  100% failure. FIX: new _resolve_invitee_summoner_id layers resolution most-
  reliable-first - explicit summonerId -> puuid (/summoners-by-puuid-cached) ->
  scan /lol-chat/v1/friends (invite targets ARE friends; that resource carries
  gameName/gameTag/summonerId) -> legacy by-name LAST for ancient builds. Handler
  also accepts puuid + reports resolved_via. TDD: tests/test_lobby_invite_resolution.py
  (10 pass / 1 live-skip) reproduces the failure + pins resolution order, body
  shape {[{"toSummonerId":..}]}, and the dashboard allowlist. RC suite 5362 passed /
  2 skip / 0 fail. ORCHESTRATION CALL (auto-pick under no-AskUserQuestion): one
  tightly-coupled backend slice (agent + its test), so ran inline as sole
  orchestrator with the read-only verifier subagent as the pre-commit ground-truth
  gate (CONFIRM all 6 claims; siblings 46/0/0) rather than degenerate a 2-file
  coupled fix into worktree fan-out. BACKEND-ONLY (LCU agent) - NO web/route/asset
  delta, so NO 5-phase UI audit + NO RC restart (and no live lobby to capture).
  OWED (FUTURE): (1) LIVE end-to-end invite verification needs a real lobby +
  online friend (RC_LIVE_LOBBY=1 RC_LIVE_INVITE_RID=...); (2) inviting a NON-friend
  by Riot ID still depends on the dead by-name fallback - a modern alias-lookup
  (gameName/tagLine -> puuid) is owed but unverifiable offline, so not shipped
  blind; (3) RC-LCUAgent must reload to pick up the new code for live effect.
- 2026-06-08 HZ-A2 DONE (item 353, commit dc5e6293). Lane A extension: a
  gold-income + item-completion driven economy block layered onto the HZ-A1
  laning-scenario cells. NEW pure primitives in core/lead_projection.py (the
  shared macro-economy authority, project_lead untouched): minutes_for_level (the
  band<->minute bridge off the existing level benchmark), gold_income_per_min +
  expected_gold_earned (gross-income benchmark, ARAM 600 > SR 450), a
  cumulative-gold spike ladder (component 1100 / first_item 3000 / two_item 6200 /
  three_item 9400 + SPIKE_COMPLETE), next_spike, spike_threshold,
  spike_eta_seconds. core/laning_scenario_precompute.py: economy_cell +
  _recall_verdict compose those into a per-cell {recall, next_spike, spike_eta_s,
  gold_at_band} block threaded into every leaf via _cell_from_result; schema
  laning_scenarios/v1 -> v2 + an economy dimensions stanza. DESIGN CALL (auto-pick
  under no-AskUserQuestion): recall is gold/spike + mana driven, NOT trade-verdict
  driven - the combat verdict is a fight read, not an economy one; the cell-level
  economy input is the mana state. Rules: low-mana mana champ (manaless excluded)
  -> recall_now; unspent completed-item gold + no imminent spike -> recall_now;
  next spike within 60s -> back_soon; core build complete -> hold. ORCHESTRATION
  CALL: HZ-A2 is a hard LINEAR A->B dependency (the precompute imports the
  lead_projection primitives) over ~120 coupled LOC, so "true-concurrency"
  worktree fan-out degenerates to sequential + a guaranteed-red B slice; per the
  framework's own "engine slice first, then dependents" + auto-pick-safest, ran it
  as the sole orchestrator with TDD (31 red -> green) and the read-only verifier
  subagent as the pre-commit ground-truth gate (the integrity-critical part of the
  pattern). Regenerated SR seed table (1600 cells, v2, 1001402 bytes): recall_now
  940 / back_soon 440 / hold 220; next_spike component/two_item/three_item/complete
  across L2/L6/L11/L16 (verifier loaded the JSON + walked all 1600 leaves: 0
  missing economy). +35 tests (tests/test_lead_projection_economy.py 19,
  tests/test_laning_scenario_economy.py 16); HZ-A1 schema assertion bumped v1->v2.
  verifier CONFIRM all 6 claims (76/0 on the 4 module files; full RC suite 5352
  passed / 1 skip / 85 subtests / 0 fail; ruff clean). BUILD + PERSIST only - the
  live coach flip stays EXCLUDED (charter 4b do-not-flip-blind). NO engine touch
  (ENGINE 1.120.0, no DS bounce; ds_share_sync --check green - laning_scenarios is
  NOT part of the Share package, HZ-A1 precedent); no web/route/asset -> no
  UI-audit, no RC restart (table read by FUTURE consumer HZ-C1). The directive's
  "clear false-alarm blockers in ROADMAP/BACKLOG" was a no-op: the HZ-A1 false
  alarm was resolved last cycle (HEAD 0f32dd81) and never entered ROADMAP/BACKLOG
  as a blocker (grep clean). NEXT OPEN = HZ-B1 (Lane B build-order precompute).
- 2026-06-08 REGRESSION FALSE ALARM (gemini director, /gemini-headless-upgrade cycle).
  Director claimed the WAKEUP "+16 characterization tests" for
  core/laning_scenario_precompute.py were never committed ("no test files in the commit
  diff") and ordered them re-authored. GROUND TRUTH (checked 4 ways - Glob, git show
  --stat 85b13b7c, full file read, fresh pytest): tests/test_laning_scenario_precompute.py
  EXISTS (186 lines, 16 tests), was committed IN the feature commit 85b13b7c
  ("tests/test_laning_scenario_precompute.py | 186 +"), and is 16/16 GREEN this run (use
  Programs\Python\Python314\python.exe - the `py` launcher resolves to a pythoncore with no
  pytest). Read-only verifier subagent independently re-CONFIRMED (file-exists YES,
  in-commit-85b13b7c YES, 16/16 pass, engine-characterization test
  test_cell_verdict_matches_compute_matchup at line 111 pins cell["verdict"] ==
  compute_matchup). ROOT CAUSE: HEAD is the trailing docs-sync commit 49da557a (LEDGER 352
  + ROADMAP/WAKEUP, NO test files); the director diffed THAT instead of the feature commit
  one below it (85b13b7c). RESOLUTION: NO code change - declined to author duplicate tests
  (would collide with the shipped file). HZ-A1 + its 16 tests stay DONE (LEDGER item 352);
  no LEDGER entry added (a false-alarm rebuttal is not an item completion). NEXT OPEN
  unchanged = HZ-A2 (recall/back-timing + power-spike-ETA).
- 2026-06-08 HZ-A1 DONE (commit 85b13b7c). NEW core/laning_scenario_precompute.py:
  an offline deterministic sweep of the SHIPPED matchup engine
  (agents.daemon_slayer.matchup.compute_matchup) over (my_champ x enemy x
  level-band x mana-state x cooldown-state) -> trade / all_in / back_off / even
  verdicts; generator + fail-soft reader (load_laning_scenarios + lookup, mtime
  cache) + CLI; atomic versioned JSON ->
  data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_<mode>.json.
  Dimensions: 4 level-bands (L2/L6/L11/L16) x mana full/low x cd all_up/no_ult.
  mana-state low = the affordable combo prefix from mana_sim's per-cast cost
  ledger (manaless -> low==full, flagged); cd no_ult drops R. KEY MODEL FIX
  caught in build: the enemy is modelled at FULL resources (sequence_b = full
  rotation) so a same-level full-state mirror is symmetric (even) - the first cut
  left the enemy on the engine default (with AA, no E) and skewed even the mirror
  to back_off -0.10. Committed SR seed = 10-champ archetype-diverse SAMPLE (not a
  tier list), itemless v1, 1600 leaf cells / 667KB; verdict dist even 793 /
  back_off 696 / trade 111 / all_in 0 (0 all_in is HONEST for itemless - all_in
  needs full HP removal; it surfaces once an item axis lands, HZ-A2 /
  build-order precompute). 16 characterization tests pin cells == compute_matchup;
  verifier CONFIRM on the slice (16/16, 3 files present, ruff + py_compile clean).
  Full RC suite 5316 passed / 1 skip (the lone "fail" the verifier flagged was the
  PRE-EXISTING ROADMAP doc-size budget red, FIXED in the same commit by relocating
  shipped item 344 -> docs/ROADMAP_HISTORY.md: ROADMAP 82898 -> 79228 < 81920). NO
  engine touch -> ENGINE 1.120.0, no DS bounce, no Share sync; no web/ -> no
  UI-audit; RC not restarted (no route/asset delta - the table is read by a FUTURE
  consumer, HZ-C1). BUILD + PERSIST + READ only; live coach flip EXCLUDED (charter
  4b do-not-flip-blind). DISCOVERED/deferred: ARAM + Arena mode tables are a
  --mode away (the generator does all 3) but the laning-trade framing is SR;
  full-roster coverage is a --champions/--enemies expand (172^2 pairs) deferred
  offline for cost. NEXT OPEN = HZ-A2 (recall/back-timing + power-spike-ETA).
- 2026-06-08 RESEED (operator-directed, /gemini-headless-upgrade relaunch). A1-F1 were
  FULLY CLOSED -> director correctly emitted NO_WORK and self-terminated. Operator chose
  to refill with the charter 4b PRIMARY north star (drive live Haiku usage to ZERO).
  Seeded HZ-A1/A2 (Lane A laning-scenario precompute), HZ-B1/B2 (Lane B build-order
  precompute), HZ-C1 (Lane C deterministic choice-coach, shadow-log), HZ-D1 (Lane D
  Electron overlay). All scoped BUILD + PERSIST + SHADOW-LOG only; live coach flips stay
  EXCLUDED (charter "do not flip blind", needs real-game validation). Substrate paths
  verified present (scenario_matrix/combo/mana_sim/fight_report/rank/build_order/
  laning_verdicts/lead_projection/coach_output, rc-shell, ELECTRON_OVERLAY.md).
- 2026-06-07 E2 + E3 + F1 DONE + DS scout EXHAUSTED (item 348; parallel "next open
  items" dispatch). **Fanout A1-F1 now FULLY CLOSED -> NO_WORK; loop self-terminates.**
  No code shipped (research / reconcile only); RC not restarted; ENGINE 1.120.0.
  - **E2** (LCU richer-endpoint diff, research): RC's live `/lol-` surface vs the
    KebsCS reference catalog (reference-only, NOT vendored). Top-3 actionable richer
    endpoints, none blocked: (1) mastery-by-puuid FULL-TEAM
    `/lol-champion-mastery/v1/player/{puuid}/champion-mastery` (RC reads only SELF
    today, tools/gamepc_lcu_agent.py:454) -> champ-select "ally one-trick / off-role"
    signal into existing pickban / team-context panels (H); (2) match `game-timelines`
    + fuller `/games/{gameId}` parse (coaches/lcu_postgame_collector.py:764,
    dashboard/builders_lcu_enrich.py:17) -> per-frame gold/xp + ITEM_PURCHASED /
    SKILL_LEVEL_UP for the BACKLOG:24 spell-WPA / skill-order extension + s220 PGR
    curves (H); (3) career-stats per-champ aggregates for ally comfort (M).
    BLOCKED / dead-end (do NOT re-pick): augment LCU API (`/lol-cherry/*` absent,
    ADR-settled); any Arena / Cherry / Mayhem lobby-create payload (zero in corpus,
    needs live capture).
  - **E3** (technical-substance lift sweep, no vendor names): NO new NOW-bucket
    candidate exists (headless-safe lift lane exhausted). 5 new FUTURE candidates
    (all live / product / min-N gated): per-summspell+keystone WPA residual;
    recall-affordability / back-timing advisor; live enemy damage-type-split
    armor/MR chip; objective-tempo x level/recall cross-ref; forward spike-ETA from
    gold-income. Biggest un-shipped (logged, unbuilt): per-lobby-player threat tags
    (9x Match-V5 fan-out + product call). 3 STALE-SHIPPED premises to skip (the
    D1/D2/B1 trap): anti-heal callout (core/heal_threat.py item 285), inhibitor
    callout (core/event_callouts.py:329), per-item WPA tierlist (item 273) - their
    "open" verdicts live in DATED COMPETITOR_LIFT docs, left UNEDITED per the
    dated-artifact rule.
  - **F1** (monitor panel + drift poll): stale-premise - BOTH halves already shipped
    (monitor = item 346, 5bc8f02f panel + 3b3ea2e1 reconcile; drift poll = d3fcc070
    tools/upstream_drift_check.py + RC-UpstreamDriftCheck 03:45). DONE. The control
    half (Tailscale STOP / directive page) is a separate deferred item, not F1 scope.
  - **DS forward-marker scout** (item 348, worktree): EXHAUSTED. Entire un-taken
    LIFT_FOUND queue from items 344/345 REJECTED vs live loaders (cc_conditional
    get_max_conditional_cc_seconds = already-surfaced + registry-fn; cross-spell-amp
    / passive_heal / passive_damage candidates = registries NOT loaded into
    DataSnapshot or engine literals; survivability = off-channel; bilinear =
    synthetic-only DamageBlock-arg). The 2 mined sidecars (wiki_stats /
    cdragon_spell_stats) are FULLY mined; the unmined wiki_ability_stats carries no
    clean scalar (every `*_raw` is unparsed wiki markup `{{fd|0.25}}` /
    `{{ap|20 to 12}}` / `Varied` / `none`). Confirms items 344/345: further DS
    magnitude growth needs a NEW extractor key (patch-refresh schema change), NOT
    another scan. Worktree clean, ENGINE 1.120.0 untouched. Memory
    `reference_ds_forward_marker_exhausted` written.
- 2026-06-07 E1 DONE (item 335, commit 42780b3d). NOT a stale premise
  (unlike D1/D2/B1): core/post_game_rubric.py existed + was LIVE-wired
  (dashboard/routes_post_game_rubric.py -> web/js/panels/last_match.js hero
  grade chip) but its weights were hand-estimated "STARTING" values never
  calibrated against data. GROUND TRUTH: over 5957 ranked-SR participant
  rows in data/rewind_history.db (map 11 CLASSIC >=15min, real obj via
  core.obj_participation), the CURRENT rubric scored the MEDIAN game a D for
  TOP/JG/MID/ADC and C for SUP (scores 33-46) - violating the module's own
  documented "median 1.0-profile -> ~50 (B)" invariant. Root cause: dpm
  baselines ran 40-80% low (TOP 480 vs real 717), KDA baselines ran high
  (TOP 2.50 vs real 1.78), and weight sums (3.70-4.60) fell below the 5.0
  the x10 multiplier needs for a 50 median. PUBLIC SOURCE (unrankedsmurfs)
  confirms Riot publishes NO exact weights - only per-role EMPHASIS ordering
  (CS-led TOP/MID, obj/KP-heaviest JG, vision + strict-KDA + CC SUP,
  carry-damage ADC). FIX (two grounded axes): (1) _ROLE_BASELINES re-anchored
  to the empirical real per-role medians; (2) _DEFAULT_WEIGHTS re-ordered to
  the source emphasis with every role's vector summing to 5.0 (median ->
  50.0 = B floor). VALIDATED on the same corpus: median now grades B for all
  5 roles (TOP 51.5 / JG 53.3 / MID 52.0 / ADC 53.5 / SUP 54.6) with a sane
  S+..D spread. New durable db-independent invariants
  (CalibrationInvariantTests): per-role weight sum == 5.0 + baseline-profile
  grades exactly B at 50.0. Blast radius: 1 source + 4 test files; the obj
  dilution/compose tests (route + postmortem) needed ally-objective padding
  so the operator share stays below the 2x-median obj clamp (high-share
  games correctly saturate now that obj baselines are the real ~0.13-0.375
  medians). verifier CONFIRM from clean state (6 files 197/0; full RC 5257
  passed / 1 skip / 0 fail; ruff clean; 5 weight sums all 5.0). No engine
  touch -> ENGINE 1.120.0, no DS bounce, no Share sync; RC restarted (route
  reload). FUTURE: CC-score is a source-cited SUP signal with no rubric axis
  yet (documented gap); obj baselines are SR-only (event modes still 0).
  NEXT OPEN = E2 (LCU data.json diff research).
- 2026-06-06 D2 DONE (item 334, ship commit 21bf98ef). STALE-PREMISE
  (verify-premise, the D1 + B1 precedent): the draft tool L (the community fork) Elo log-odds draft
  aggregator was ALREADY SHIPPED 2026-05-20. core/draft_elo.py (pure math:
  winrate_to_rating = -400*log10(1/wr-1), rating_to_winrate = 1/(1+10^(-d/400)),
  team_score = sum(ally champ+pair+matchup) - sum(enemy champ+pair), +
  top_contributions hover decomposition) + core/draft_elo_db.py
  (rewind_history.db sqlite priors solo/pair/matchup, read-only mode=ro conn,
  Laplace-smoothed via core.smoothed_rates per CLAUDE.md #90, NO aggregator D) +
  dashboard/routes_draft_elo.py (GET /api/draft-elo, 5min TTL) +
  web/js/panels/draft_elo.js (champ-select chip + n= density + hover-only
  contribution strip). Ship chain 21bf98ef aggregator + a148f779 frontend chip
  + daa5a098 / 97ab12e9 per-row contribution hover + 87efa337 ESC. The directive
  read BACKLOG.md:78 FUTURE entry but missed the (SHIPPED 2026-05-20 ab3f553 +
  00051f3) reconciliation marker just below it; re-implementing would clobber a
  live 42-test module, so NO source change. GROUND TRUTH this cycle: live
  /api/draft-elo (ally 22,67,64,89,412 vs enemy 51,141,238,555,235) -> ok=true
  with real rewind-db ratings (solo_counts e.g. [33,64] / [35,72]; computed
  champ/pair/matchup ratings). Coverage already complete - tests/test_draft_elo.py
  (28) + tests/test_draft_elo_panel_dom.py (14 hover contract) +
  tests/snapshot_panels/test_draft_elo_panel.py = 42 passed; UNLIKE D1 there is
  NO owed clause (the snapshot view test already exists). Full RC suite 5255
  passed / 1 skip / 0 fail / 85 subtests (observed this run, unchanged - zero
  test delta). No source change -> no asset-hash reload, no RC restart; ENGINE
  1.120.0, no DS bounce, no Share sync. NEXT OPEN = E1 (per-role grading rubric
  calibration).
- 2026-06-06 D1 DONE (item 333, commit ab176543): DS relative-score bar.
  STALE-PREMISE (verify-premise, cycle-3/4 precedent): the feature was ALREADY
  SHIPPED as item 220 (2026-05-30) - dashboard/routes_ds_relscore.py (GET
  /api/ds-relscore, score_pct = round(delta_dps/top_delta*100,1), row0=100.0,
  READ-ONLY auto-resolved target, render-gated) + web/js/panels/ds_relscore.js
  (#csv-ds-relscore champ-select bar) + a backend route test
  (test_routes_ds_relscore.py) + a panel-smoke test
  (test_ds_relscore_panel_dom.py), wired in _dispatch.py + index.html +
  champ_select.js, LIVE-verified this cycle (Caitlyn SR: 12 rows, Runaan's
  100.0 -> 62.1). Re-implementing would duplicate item 220, so NO source change.
  The one open clause = item 220's "LIVE VISUAL CAPTURE owed" (Game-PC :8892
  down; Claude_Preview cannot attach the self-signed :8888). DISCHARGED
  CI-durably (the C1/C2/C3 pattern): NEW tests/snapshot_panels/
  test_ds_relscore_view.py renders the real renderDsRelscore bar into the live
  #csv-ds-relscore mount (the champ_select fixtures do not lock my_champion, so
  it drives the panel directly with a synthetic locked champ + a stubbed
  /api/ds-relscore payload), asserts the .dsr-bar-fill widths track score_pct
  (row0=100%, non-increasing) + the pct labels, and screenshots the panel.
  Test-only. 2 new tests, ruff + ASCII clean, verifier CONFIRM + full suite
  5255/0. Full RC suite 5255 passed / 1 skip / 0 fail / 85 subtests (+2). No
  source change -> no asset-hash reload, no RC restart; ENGINE 1.120.0, no DS
  bounce. NEXT OPEN = D2 (draft tool L (the community fork) Elo log-odds draft aggregator).
- 2026-06-06 C3 DONE (item 332, commit aa0a5a7e + docs sync): Post Game Review
  (last-match) SR + ARAM + Arena 5-phase fixture audit + reproducible visual
  validation. AUDIT: 3 parallel read-only mode-lens subagents (SR #14 / ARAM #15
  / Arena #16) ran STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY against
  last_match.css (~1290) + last_match.js (~1347, incl inline px) + the
  last_match_<m> fixtures + index.html #view-last-match vs UI_SCALE_SPEC_V2.
  Typography already on v2.1 tokens (every font-size a --fs-* token except ~5
  sub-floor labels carrying inline documented operator-exception rationale); 0
  in-scope MUST-FIX. Sole-merger call: the ARAM/Arena agents flagged the U+00B7
  meta separator + a "Review ->" tab arrow as ASCII MUST-FIX, but these are
  PRE-EXISTING (U+00B7 is a convention across 11 panels; last_match.css carries
  ~972 comment-art non-ASCII bytes) and OUTSIDE the actively-enforced em/en-dash
  + smart-quote set (all 3 agents verified ZERO U+2013/2014/2018/2019/201C/201D),
  and CI does not gate them (the C2 suite was green with U+2500 present) ->
  deferred to the operator-gated repo-wide ASCII sweep (FUTURE), not churned
  piecemeal. VISUAL: NEW tests/snapshot_panels/test_last_match_view.py renders
  the full #view-last-match for all 3 modes via the headless mock-server +
  Playwright at 1920x1080 (drive /?ui_mock=1&mode=<m>#last-match -> _lmMockUrl ->
  renderLastMatch; wait on #lm-mode-tag != "-"). Asserts per mode: view mounts,
  hero champion + grade render, mode tag (Ranked Solo / ARAM / ARENA) matches,
  Arena neutral ARENA pill vs SR VICTORY, no JS errors; screenshots each. NEW
  web/data/ui_mock/last_match_sr.json (SR Ranked Solo fixture) + an sr branch in
  _lmMockUrl give PGR-SR the same CI coverage as ARAM/Arena. 6 new tests, ruff +
  node --check + ASCII clean, verifier CONFIRM 6/0 + full suite 5253/0. Full RC
  suite 5253 passed / 1 skip / 0 fail / 85 subtests (+6). web/js asset-hash
  reload (ADR-008), no RC restart; no engine touch -> ENGINE 1.120.0, no DS
  bounce, no Share sync.
- FUTURE (C3 audit SHOULD/NICE + deferred ASCII debt): (1) repo-wide
  operator-gated ASCII sweep of last_match.css/js (~972 + 213 pre-existing
  non-ASCII: box-drawing/arrow comment art + the U+00B7 meta separator shared by
  11 panels - main.js/right_now.js/next.js/team_context.js/...). (2)
  .lm-hero-champ (champion-name role=button deep-link) lacks min-height --hit-min
  42px (~41px today); add min-height + inline-flex centering (shared hero element
  -> lands on all 3 PGR modes). (3) Arena _setHero hard-codes the "ARENA" result
  pill + ignores enriched.subteam_placement - surface the real placement (e.g.
  "2nd / 6"). (4) Arena _setTeamComp groups all 5 non-operator subteams into one
  ENEMY block - a subteam-grouped roster reads truer.
- 2026-06-06 C2 DONE (item 331, commit e81495e0 + docs sync): Active Match
  SR + ARAM + Arena 5-phase fixture audit + reproducible visual validation.
  AUDIT: 3 parallel read-only mode-lens subagents (SR #11 / ARAM #12 /
  Arena #13) each ran STRUCTURE/TYPOGRAPHY/HIT-TARGETS/ASCII/HIERARCHY
  against active_match.css + active_match.js (incl. its inline-style px) +
  the active_match_<m> fixtures + index.html #view-active-match vs
  UI_SCALE_SPEC_V2. SPLIT verdict: SR NEEDS-FIX (3 MUST-FIX); ARAM + Arena
  SHIP-READY. Sole-merger resolution: the SR auditor was right - the
  active_match.js inline styles carry NO inline rationale (unlike the
  cd_ledger.css precedent) and the CALL pane is the dominant in-game
  content. FIXED in-slice: (a) active_match.css 2 non-ASCII U+00D7 (x)
  signs in comments -> ASCII; (b) active_match.js 3 sub-floor inline
  font-size px on readable DOM text -> v2.1 tokens (_line value 13 ->
  --fs-md, _line label 10 -> --fs-xs, _dsIcon delta 11 -> --fs-xs).
  VISUAL: NEW tests/snapshot_panels/test_active_match_view.py renders the
  full #view-active-match for all 3 modes through the headless mock-server
  + Playwright harness at 1920x1080 (drive /?ui_mock=1&mode=<m>#active-match
  -> _amMockLoad -> renderActiveMatch; wait on #am-sub "phase InProgress").
  Asserts per mode: view mounts, CALL pane live coach line renders, map
  mounts with alt "<mode> map", draft-elo chip enabled SR/ARAM + hidden
  Arena (the 5v5 gate), no JS errors; screenshots each. 7 new tests, ruff
  + node --check + ASCII clean, verifier CONFIRM 7/0 + full suite 5247/0.
  Full RC suite 5247 passed / 1 skip / 0 fail / 85 subtests (+7). web/css|js
  asset-hash reload (ADR-008), no RC restart; no engine touch -> ENGINE
  1.120.0, no DS bounce, no Share sync. Also relocated the shipped cdragon
  ROADMAP item 1 -> docs/ROADMAP_HISTORY.md to bring ROADMAP.md back under
  its 80KB doc-size budget (was 81993 > 81920; pre-existing red latent
  since the C1 docs-only commit).
- FUTURE (C2 audit SHOULD/NICE, deferred - do NOT auto-flip): the density-
  constrained sub-floor micro-labels NOT bumped (kept at px): active_match.js
  map status 11px + gank band 12px (absolutely-positioned HUD overlays on
  the map image), _dsIcon/_defIcon OWNED 9px stamps + _defIcon caption 10px
  + _dsIconFallback 9px tile (inside 44-62px icon cells where >=16px
  overflows), MIA canvas badge 10px (canvas-rasterized, CSS tokens cannot
  apply). Document each with an inline operator-exception rationale
  (cd_ledger.css precedent) or bump on a future dense-overlay pass. Off-grid
  spacing (am-grid gap 14, pane padding 10/14) is pre-existing, deferred.
- 2026-06-06 C1 DONE (item 330, commit b4bfa05a): Champ-Select ARAM + Arena
  5-phase fixture audit + reproducible visual validation. AUDIT: 2 parallel
  read-only subagents (ARAM + Arena), each ran STRUCTURE/TYPOGRAPHY/HIT-TARGETS/
  ASCII/HIERARCHY against champ_select_view.css (mode blocks ~1659-1995 ARAM /
  ~2482-2804 Arena + shared base) + champ_select.js + the ui_mock fixtures vs
  docs/UI_SCALE_SPEC_V2.md. BOTH returned SHIP-READY, 0 MUST-FIX - the CSS was
  already swept onto v2.1 tokens by prior rounds (s164/s212/s214/s234/s239,
  items 178/181/202); the sub-floor px that remain (.csv-bench-empty 13,
  .csv-duo-cell-tag 11, .csv-arena-cell-name 13, .csv-pr-chip 14) all carry the
  inline "documented operator exception" rationale the spec permits. VISUAL: the
  C-phase Claude_Preview check A1/A2/A2b kept OWING is now discharged in a
  CI-durable form - NEW tests/snapshot_panels/test_champ_select_view.py renders
  the full-page #view-champ-select for both modes through the existing headless
  mock-server + Playwright harness at the 1920x1080 design baseline (drive path
  /?ui_mock=1&mode=<m>#champ-select -> _csMockLoad fetches
  /data/ui_mock/champ_select_<m>.json -> data-cs-mode stamp). Asserts per mode:
  view mounts, mode-specific structure renders (ARAM 10-cell bench / Arena duo
  row + augment slots), SR-only Pick & Ban hidden, no JS errors; screenshots the
  view. Operator-eyeballed both captures: ARAM (Jinx HOVERING + LOCK IN + COMP
  VERDICT swap->Ashe w/ green bench swap-ring + summspell D/F strip + enemies)
  and Arena (duo me+Lulu+waiting / Silver-Gold-Prismatic augment slots / 5
  stacked enemy sub-teams) both read clean at baseline, no horizontal scroll.
  5 new tests, ruff + py_compile + ASCII clean, verifier subagent CONFIRM 5/0.
  Full RC suite 5240 passed / 1 skip / 0 fail / 85 subtests (+5). No web/ source
  delta (audit found nothing to fix) -> no asset-hash reload, no RC restart; no
  engine touch -> ENGINE 1.120.0, no DS restart, no Share sync.
- FUTURE (C1 audit SHOULD/NICE, deferred - operator-tuned, do NOT auto-flip):
  (1) champ_select_view.css:264 .csv-lock-btn min-height 32px < --hit-min 42px -
  carries an explicit operator prominence-reduction rationale ("round 3"), so a
  bump would re-litigate that decision; formalize the comment or bump only on
  operator OK. (2) .csv-bench-cell has no min-width floor (bench cells clear 42px
  at the 1920 baseline but could dip below it on a narrower-than-baseline window;
  spec targets 1920 only). (3) Arena enemy .csv-arena-cell 3rd cell is a
  forward-flex scaffold (live Arena is 2/team) rendering one empty dashed cell
  per team; drop to a 2-col row only if the 3-cell scaffold is confirmed dead.
- 2026-06-06 B1 DONE (item 329; commits b8e7647a slice / 21f6aaf9 merge /
  48411bfc fix). STALE-PREMISE: the B1 row's "zero live-coach consumer" was
  wrong - all 3 generators were ALREADY wired live into /api/state by commit
  679c8928 (Haiku-elim W3A): dashboard/_deterministic_coaching.py
  (compute_deterministic + resolve_choices, TTL-cached, fail-soft) +
  _state_builder.py:312-347 ship coach.choices / state.callouts /
  state.lead_projection, and the panels (callouts.js #rn-lead + #rn-callouts,
  coach_choices.js #rn-choices) already render them. Verified live: /api/state
  carried callouts + lead_projection + 3 choices; 153 generator/wire/panel
  tests green. The one UNSHIPPED B1 clause was "shadow-log validation first":
  resolve_choices BLIND-FLIPS native -> deterministic choices live (sec-4b
  do-not-flip-blind) and the DISCARDED native choices were unrecorded, so the
  flip could not be validated. Shipped NEW core/det_coach_shadow.py (fail-soft
  jsonl, per-path dedup, mirrors A3 core/ds_coach_shadow) +
  dashboard._deterministic_coaching.shadow_log_det that records det
  choices/callouts/lead AND the discarded native choices side-by-side to
  data/det_coach_shadow.jsonl (gitignored), zero live-output change. 1 worktree
  slice (verifier CONFIRM 41/0) + 1 LIVE-CAUGHT fix: the first cut logged native
  AFTER resolve_choices overwrote coach["choices"] (native == det garbage, found
  via the live jsonl - NOT the worktree gate); reordered shadow_log_det before
  the overwrite + added a native!=det regression test. Full RC suite 5235 passed
  / 1 skip / 0 fail (+8). No web/ delta (panels pre-wired) -> no UI-audit. No
  engine touch -> ENGINE 1.120.0, no DS restart, no Share sync; RC restarted
  (route reload) pid 27300. NEXT: the jsonl now accrues det-vs-native validation
  data - a future cycle can analyze it to confirm/tune the live flip before
  declaring the laning-Haiku surface validated.
- 2026-06-06 A3 DONE (item 328, commit 52f76059): DS-coach SHADOW-LOG substrate
  shipped (NOT yet surfaced). 3 disjoint verifier-CONFIRMED worktree slices
  (verifier 13/0 + 17/0 + 6/0) + 1 base-coach integration: NEW pure generators
  core/ds_antitank_hint.build_antitank_hint (anti-tank build hint vs high-HP
  enemy comps over compute_antitank + core.archetype_picks tank/bruiser count)
  and core/ds_scaling_hint.build_scaling_hint (early/mid/late power-curve +
  outscale/falloff/even verdict over compute_scaling), a fail-soft jsonl writer
  core/ds_coach_shadow.log_coach_hints (DI-testable, lazy import, never raises),
  and a fire-and-forget hook BaseCoach._shadow_log_hints in _maybe_coach that
  canonicalizes champ name-forms and records both hints to
  data/ds_coach_hints_shadow.jsonl (gitignored) alongside live coaching WITHOUT
  touching the Haiku prompt / UI / coach output. Full RC suite 5227 passed / 1
  skip / 0 fail (+41); ruff + py_compile clean; ASCII-only. NO engine file
  touched -> ENGINE stays 1.120.0, no DS restart, no Share sync. SURFACING into
  coach context is the deliberate FUTURE step (gated on shadow-log accrual +
  validation; section-4b do-not-flip-blind, the champ-select Haiku-elim pattern).
  Calibration note: slice 1 set ANTITANK_STRONG=0.8 (Vayne 0.95 / Fiora 0.90
  clear lean-in; flat-damage mages at 0.0 -> recommend items) since no champ
  reaches the spec's 1.2 on a single mechanism.
- 2026-06-06 cycle-5 REGRESS on A2b = FALSE POSITIVE (3rd consecutive; cycles
  3/4/5 each flagged the same non-bug). This-run ground truth: `git grep` for the
  corruption marker across every tracked code file (*.css *.js *.py) returns ZERO
  matches; web/css/dashboard.css line 42 and tests/snapshot_panels/
  test_ds_matchup_panel.py line 47 both hold the correct CSS import directive;
  docs/ORCHESTRATION_PLAN.md lines below read correctly. Tests this run: 13
  implicated (parity guard + ds_matchup snapshot) passed; FULL RC suite 5186
  passed / 1 skip / 0 fail / 85 subtests. ROOT CAUSE of the loop: the auditor
  re-detects the bug-DESCRIPTION quoted verbatim inside the loop's own control
  files (ops/loop/control/directive.md + _gemini_in.txt) and the prior FP
  entries - it is documentation OF a non-bug, never source corruption. NO source
  change made (none warranted). A2b stays DONE. Escalated to the DIRECTOR via
  gemini_ask.txt: advance to A3, stop re-issuing this verdict.
- 2026-06-06 REGRESS verdict on A2b = FALSE POSITIVE (verify-only cycle, no
  source fix; ground truth HEAD 8188baf3). The auditor flagged a botched
  find/replace that would have turned the leading @import token into a stray
  test_dashboard_css_panel_imports_parity.py filename fragment in
  tests/snapshot_panels/test_ds_matchup_panel.py + docs/LEDGER.md +
  WAKEUP_NOTES.md. GROUND TRUTH: that string exists ONLY in the loop's own
  control files (ops/loop/control/directive.md + _gemini_in.txt, which quote the
  bug verbatim) and in untracked _verify_*.txt scratch logs - NEVER in source.
  test_ds_matchup_panel.py line 47 + web/css/dashboard.css line 42 both carry the
  correct @import './panels/ds_matchup.css'; the LEDGER / WAKEUP _imports_parity
  hits are legit prose references to the real bundle-parity guard test, not
  corruption. Verified live: snapshot_panels + the parity guard 92 passed; FULL
  RC suite 5186 passed / 1 skip / 0 fail; git diff empty (working tree == HEAD).
  A2b stands DONE. Director: advance to A3 - there is no regression to fix.
- 2026-06-06 A2b DONE (commit 0a017dc4): NEW GET /api/ds-matchup +
  champ-select ds_matchup card. Surfaces the EXISTING compute_matchup engine
  via the existing /v2/matchup client wire (core/daemon_slayer_client.matchup);
  thin read-only dashboard route (dashboard/routes_ds_matchup.py mirrors
  routes_ds_profile: 5-min TTL cache, numeric->slug resolver, fail-soft
  503/400/no_matchup) + a presentational card (web/js/panels/ds_matchup.js +
  ds_matchup.css) keyed champ_a=cs.my_champion vs champ_b=first committed enemy.
  Payload adds swing_pct (0-100, 50=even) + favored (A/B/even) over the raw
  MatchupResult. Shipped as 2 disjoint verifier-CONFIRMED worktree slices
  (backend 21/0, frontend 8/0) + 1 UI-audit fix. Full RC suite 5185 passed / 0
  fail; ruff + node --check clean. Live route probed green (Vayne vs Caitlyn:
  back_off, favored B, net_swing -0.148; L6 -0.303; numeric 67/51 resolves;
  missing param 400). 5-phase UI audit: 1 MUST-FIX FIXED (scheduler wiring was
  dead - card rendered one tick late vs siblings; + regression test), 1
  SHOULD-FIX FIXED (header overflow guard). VISUAL CAPTURE OWED (carry-forward):
  Game-PC :8892 MCP down (SessionStart re-confirmed /health None) +
  Claude_Preview cannot attach self-signed HTTPS :8888 (same A1/A2 blocker).
- FUTURE (A2b UI audit SHOULD/NICE, deferred): (1) ds_matchup.js _signature
  omits a_can_full_combo / b_can_full_combo / notes - a payload changing ONLY a
  combo flag or note text skips the sig-dedup rebuild (stale notes; low odds).
  (2) NICE: .dsm-swing-end labels lack white-space:nowrap (could wrap at extreme
  narrow width). (3) NICE: _notesHtml renders the .dsm-cast "full combo" tag
  immediately before "...lands full combo" (doubled phrase; cosmetic).

- 2026-06-06 A2 DONE (commit 3f23e18c): /api/ds-profile + the panel grew 4 -> 8
  axes (added threatrange/zonecontrol/objdamage/extendedduel from the existing
  pure scorers; headlines threatrange_score/zonecontrol_score/objdamage_score/
  duel_score; per-axis bool flag + dsp-flag marker: is_artillery->artillery,
  controls_terrain->terrain, pressures_structures->towers, ramps->ramps). Shipped
  as 2 disjoint verified worktree slices (route + panel), each independently
  re-run before merge. 5-phase UI audit SHIP-READY (0 MUST-FIX, 0 SHOULD-FIX).
  RC suite 5156 passed / 0 fail; DS suite 6705 passed / 0 fail; ruff clean. Live
  route probed green (Vayne: objdamage HIGH pressures_structures, extendedduel
  ramp, threatrange medium, zonecontrol sparse 0). VISUAL CAPTURE OWED
  (carry-forward): Game-PC :8892 MCP down + Claude_Preview cannot attach the
  self-signed HTTPS :8888 (same A1 blocker).
- 2026-06-06 A2b SPLIT: matchup was NOT made a profile axis. compute_matchup is
  a pairwise 1v1 (needs champ_a + champ_b + per-side level + items + a
  DataSnapshot) and already has its own surface (/v2/matchup); a single fixed
  "axis" value for the locked champ would be arbitrary/misleading. Logged as new
  OPEN session A2b - a dedicated matchup card keyed on a selected enemy.
- FUTURE (NICE, from A2 5-phase audit): ds_profile.css .dsp-label has no
  white-space:nowrap guard (9-char "OBJECTIVE" fits 5.5em today, parity with
  "WAVECLEAR"); .dsp-detail flex has no min-width:0 / flex-wrap (overlaps the A1
  .dsp-detail overflow NICE); 8 stacked rows is a denser card than 4 - revisit
  only if the live Suggestions stack reads tall. All cosmetic; deferred.
- 2026-06-06 A1 DONE: GET /api/ds-profile + champ-select DS-Profile panel (4 axes
  mobility/sustain/scaling/waveclear) shipped as 2 disjoint verified slices.
  5-phase UI audit PASS (0 MUST-FIX, 0 SHOULD-FIX). Live route probed green; full
  RC suite 5153 passed. VISUAL CAPTURE OWED (carry-forward): Claude_Preview cannot
  attach to the HTTPS self-signed live :8888, and Game-PC :8892 MCP is down
  (project_gamepc_mcp_boot_gap). Capture the locked-champ Suggestions card next
  time a visual path is available.
- FUTURE (NICE): web/css/panels/ds_profile.css .dsp-detail has no
  overflow/text-overflow/min-width:0 guard (clipped by ancestor overflow:hidden
  today - cosmetic only).
- A2 NEXT: add threat-range / zone-control / objective-damage / extended-duel /
  matchup axes to the same /api/ds-profile surface (engine fns already exist:
  threatrange.py / zonecontrol.py / objdamage.py / extendedduel.py).
