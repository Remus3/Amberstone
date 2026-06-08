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
file) -> py ops/loop/done_sentinel.py. No AskUserQuestion; auto-pick safest option.

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
| HZ-A2 | haiku-zero | Lane A extension: add recall/back-timing + power-spike-ETA verdicts (gold-income + item-completion driven, reuse core/lead_projection.py) to the HZ-A1 lookup tables. Characterization tests. BUILD + PERSIST ONLY. | OPEN | - |
| HZ-B1 | haiku-zero | Lane B build-order precompute. Build core/build_order_precompute.py: optimal build orders per (champ x mode x enemy-comp-archetype) from Meraki aram_modifiers + agents/daemon_slayer/rank.py + core/build_order.py + curated loadouts. Persist to data/daemon_slayer/build_orders/. Characterization tests. BUILD + PERSIST ONLY. | OPEN | - |
| HZ-B2 | haiku-zero | Lane B enemy-comp branch: anti-tank (high-HP comp) vs anti-squishy build-order variants layered on HZ-B1, using the DS anti-tank axis (A3). Characterization tests. BUILD + PERSIST ONLY. | OPEN | - |
| HZ-C1 | haiku-zero | Lane C deterministic choice-coach generator: read the HZ-A / HZ-B tables and emit core/coach_output.py A/B choices (#rn-immediate chips) for laning trade decisions. SHADOW-LOG alongside the live Haiku coach (log both, do NOT replace). Tests. No live flip. | OPEN | - |
| HZ-D1 | haiku-zero | Lane D Electron overlay: advance rc-shell/ per docs/ELECTRON_OVERLAY.md - read it, pick the next UNSHIPPED code-side phase (Phase 2+), Vanguard-safe (DWM window, NO DXGI capture, Borderless). Ship the headless-safe slice; leave live-visual-only work WIP with a note. Tests where applicable. | OPEN | - |

## EXCLUDED (live-game / operator-gated; the director MUST NOT pick these)

- DS Phase-D default-ON flag flips (apply_passive_damage, non-every-AA on_hit, per-stack assumed_stacks) - need real-game re-ranking validation.
- Live caster-stat producer for /anti-tank P3.2 activation + live survivability scorer (egg-resist / Orianna E) - need a live AbilitiesSnapshot / game.
- Champ-select brief Haiku -> deterministic flip - needs live shadow-log accrual + operator OK.
- Game-PC :8892 visual screenshot captures (MCP down post-1PC). C-phase visual validation uses the Claude_Preview MCP against :8888 instead.
- Anything in the CLAUDE.md "Settled - do not re-litigate" set.
- Haiku-to-ZERO LIVE coach flips: removing/replacing a live Haiku call with the HZ-* precompute tables. Per charter 4b "do not flip blind" - needs real/replayed-game validation + operator OK. The HZ-* sessions BUILD + PERSIST + SHADOW-LOG only; Haiku stays the interim floor until validated.

## Findings log (executor appends; newest first)

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
