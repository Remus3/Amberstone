# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch archived to docs/history_notes.md. Only the last 3 sessions kept here.

---
# 2026-05-21 - EHP Phase 6 healing throughput SHIPPED (1 commit `5018e9f`; ENGINE 1.27.0 -> 1.28.0)

Operator AskUserQuestion-picked "EHP Phase 6 healing throughput" from a 4-option fork (Phase 6 / per-spell CC / postmortem pre-flight / housekeeping). The natural follow-up per item 128 carry-forward (a). RC not restarted (DS engine slice, RC consumes over HTTP); DS :8893 restarted once for engine bump. Pushed + CI green; no frozen-file edits.

**Commit `5018e9f` feat(ds):** Closes `ehp.py:23` deliberate Phase-1 omission "Healing throughput (lifesteal, Spirit Visage amp) - fits Phase 6". Three contributions feed an EHP heal pool: (a) item-passive heals via NEW `ItemHeal` dataclass + `ItemEffect.heal` field - Sundered Sky 6610 / Arena 226610 Lightshield Strike (100% base AD melee / 50% ranged, one-trigger-per-fight under 10s/target CD); (b) lifesteal-derived heal `stats.lifesteal * stats.ad * stats.as * _FIGHT_WINDOW_S (6.0)` over standard fight window (pre-mitigation approximation matching EHP's no-enemy-pen Phase-1 posture); (c) multiplicative heal amp via NEW `ItemEffect.heal_amp_pct` field - Spirit Visage 3065 / Arena 223065 Boundless Vitality +25% (stacks multiplicatively per buff-system doctrine). Bloodthirster 3072 / Arena 223072 Ichorshield ships in the Phase 1.5 ItemShield pipeline (full-cap steady-state: 165 L1 -> 315 L18, ANY damage type). NO `unique_passive_key="lifeline"` - BT's Ichorshield is a distinct unique passive and stacks with any single lifeline shield.

**EhpResult new fields:** heal_item_total / heal_lifesteal / heal_amp_mult / heal_total / heal_sources. compute_ehp folds heal_total into physical_ehp / magical_ehp / true_ehp at top of damage stack (heals don't discriminate by damage type, so heal pool acts like an ANY shield).

**Deliberate Phase 6 omissions (deferred to Phase 6.5+):**
- Death's Dance Defy heal-on-takedown (75% bonus AD over 2s) - takedown-rate uncertain; 6333 + 226333 stay defensive_only.
- Spirit Visage amp on Phase 1.5 SHIELDS - engine ships heal-pipeline amp only; SV + lifeline-item under-credits the shield piece by ~15% (60% bonus_hp shield * 0.25 amp lost on a Sterak example).
- Sundered Sky 6% missing-HP additive - needs current-HP-share assumption distinct from full-HP convention.

**Tests:** +56 in NEW `tests/test_ehp_heal_phase6.py` across 11 classes: ItemHealSchemaTests (9: construction + scaling composition + ranged modifier + edge cases), CollectHealsTests (5), TotalHealAmpTests (6), LifestealHealTests (7), BTIchorshieldTests (8: level lerp + non-lifeline unique + EHP lift), SunderedSkyHealTests (4: melee/ranged + Arena mirror + periodic preserved), SpiritVisageAmpTests (5: amp pool only, NOT Phase 1.5 shields), EhpResultHealFieldsTests (4: to_dict + format_table + notes), DeathsDanceDeferredTests (3), BTPlusLifelineStacksTests (2: both shields aggregate at engine layer), EngineVersionCurrentTests (1). +15 stale ENGINE pin syncs across 14 DS test files (1.27.0 -> 1.28.0).

**Verified:** DS suite 2906 -> 2962 / 1 skipped / 1 xfailed / 1663 subtests. Wider RC 2780/0 (phase8_smoke flipped pass post-DS-restart). py_compile + ruff + ASCII clean on all 5 touched source files (0 non-ASCII added). DS :8893 restarted via taskkill PID 8564 + schtasks /Run RC-DaemonSlayer ritual; /health returns engine_version=1.28.0 patch=16.10.1.

**Math verified end-to-end:** Aatrox L11 + Sundered Sky + Spirit Visage = base AD 103.875 * 1.25 amp = 129.84 heal_total exactly. Aatrox L11 + BT alone: shield_any=198.33 (165 + 2/9 * 150 at L11) + heal_lifesteal=134.67 (0.15 * 183.88 AD * 0.8137 AS * 6).

**Don't-redo:** BT shield does NOT share `unique_passive_key="lifeline"` (distinct Ichorshield unique - stacks alongside Sterak/Shieldbow/Maw/Hexdrinker at the engine layer; rank.py upstream dedup is separate). Spirit Visage amp applies to HEAL pool ONLY in this engine (deliberate Phase 6 boundary; SpiritVisageAmpTests.test_spirit_visage_does_not_amp_phase15_shields pins). Lifesteal heal uses PRE-mitigation AD (EHP scorer is enemy-state-agnostic; over-credits by ~30-40% vs 60-90 armor - consistent with the no-enemy-pen Phase 1 omission still in force). Sundered Sky preserves its existing PeriodicProc damage proc - heal field is ADDED, not replacing. The `_FIGHT_WINDOW_S = 6.0` constant matches existing sustained/burst boundary in the DPS layer. DD 6333 stays defensive_only - the Defy heal-on-takedown rate is genuinely uncertain; do NOT pre-wire with a constant takedown probability.

**Next session:** (a) Per-spell CC duration extractor as 2nd consumer of `effective_cc_duration` helper (engine-side; ABILITY_RESULT.cc_duration_s field; would compose with the Phase 6 heal model into a future EHP-vs-CC blended scorer). (b) Phase 6.5 work queued: Death's Dance Defy heal (needs takedown-rate model), Spirit Visage amp on Phase 1.5 shields, Sundered Sky 6% missing-HP additive. (c) Live ARAM/SR smoke STILL pending - operator must play modified-tenacity champ + verify Phase 6 healing reflects in EHP rankings live. (d) RC-PostmortemAnalyze first cron 2026-05-24 04:15 - verify LastTaskResult=0 next session.

---
# 2026-05-21 - DS 3-slice drain SHIPPED (3 commits `c36446b` `13eb869` `d854951`; ENGINE 1.26.0 -> 1.27.0)

Operator: "continue ds" -> 3 scoped slices, each AskUserQuestion-framed. RC restarted 2x (coach prompt edits); DS :8893 restarted once for engine bump. All 3 pushed + CI green; no frozen-file edits.

**Slice 126 `c36446b` feat(coach):** EHP enemy-CC coach consumer (ARAM tenacity). First live consumer of `effective_cc_duration` helper (shipped 1.25.0 with zero consumers). NEW `core/aram_tenacity_context.py` loads `data/daemon_slayer/<patch>/champions.json` once at module-import -> `_TENACITY_MAP` of 17 non-1.0 champs (15 at 1.20x + 2 at 1.10x). `aram_tenacity_line(champion, mode) -> str` renders the prompt line. Wired into `coaches/aram_coach.py` `_USER_TMPL` between `Enemy keystones` and `DS top items`. Cached `_SYSTEM` unchanged (cache-prefix preservation). `tests/test_ds_pick_consumption_p1l11.py` fixture +1 line. +29 tests. RC 2733 -> 2762.

**Slice 127 `13eb869` feat(coach):** Per-enemy ARAM tenacity wire. Symmetric extension of 126 - aramTenacity is the multiplier on ANY CC on that champion (operator's CC on enemy lasts longer too). NEW `enemy_aram_tenacity_line(enemies, mode) -> str` renders `"Enemy ARAM tenacity (your CC on them lasts longer): Talon 1.20x, Zed 1.20x"`, sorted desc-mult then alpha. Wired next to `{aram_tenacity}`. +18 tests. RC 2762 -> 2780.

**Slice 128 `d854951` feat(ds):** EHP Phase 1.5 shield throughput. Closes `ehp.py:21` deliberate Phase-1 omission. 4 LIFELINE-style shields (Sterak 3053 60% bonus_hp ANY; Shieldbow 6673 400->700 ANY ranged x0.80; Maw 3156 200+150% bonus_ad MAGICAL ranged x0.75; Hexdrinker 3155 110->280 MAGICAL ranged x0.75). NEW `ItemShield` dataclass in `_effects_types.py` + `ItemEffect.shield` field + `ANY` constant + `_SHIELD_TYPES`. EhpResult gains shield_any/phys/mag/true/sources fields; `compute_ehp` folds totals at top of damage stack (shields share armor/MR factor with HP per League's damage model). NEW `_is_ranged` (threshold 250) + `_collect_shields` aggregator. Bloodthirster ichor-shield + Doran's Shield block-per-source DEFERRED to Phase 6. ENGINE 1.26.0 -> 1.27.0; +15 stale ENGINE pin syncs across 14 test files. +46 tests. DS 2860 -> 2906; RC 2780 unchanged. DS server taskkill + schtasks /Run RC-DaemonSlayer -> /health 1.27.0 live.

**Don't-redo:** all 4 lifeline items use EXISTING `unique_passive_key="lifeline"` (Phase 4 batch 12). Shields share SAME armor/MR factor as HP (NOT un-resisted). `compute_ehp` does NOT apply unique_passive dedup itself - rank.py's `shares_dead_unique` is upstream. The 17-champ tenacity map is patch-data-driven via `champions.json` -> `lolmath.aram_modifiers.aramTenacity`; do NOT hardcode. Per-call injection via `_USER_TMPL` (cache-prefix preservation); do NOT migrate to system-prompt suffix. Only ARAM coach is wired; Brawl/Arena/SR coaches do NOT have aramTenacity in their modes.

**Next session:** (a) Phase 6 healing throughput (lifesteal + Spirit Visage + Death's Dance + Bloodthirster ichor-shield) - natural follow-up. (b) Per-spell CC duration extractor as a 2nd consumer of the tenacity wire (engine-side). (c) live ARAM smoke still pending - operator must play modified-tenacity champ or face them. (d) RC-PostmortemAnalyze first cron 2026-05-24 04:15 - verify LastTaskResult=0 next session.

---
# 2026-05-21 - postmortem follow-up 4-slice drain SHIPPED (4 commits `50c83ac` `6d22e2e` `3cfea90` + 2 merges)

Operator: "continue what is next to do". Per item 124 carry-forward sweep + AskUserQuestion (4 options, operator picked "all 4 in parallel"). 4 slices shipped end-to-end; 2 via parallel worktree agents + 2 inline. RC restarted clean pid 5972 -> 2640; cadence task LIVE NextRun 2026-05-24T04:15.

**Slice B `50c83ac` feat(coach):** 2 new death patterns. `small_skirmish` (assists in {1,2}; fills gap between caught_4plus assists>=3 and solo_1v1_loss assists==0; assist-band elif chain) + `midgame_collapse` (game_time 8:00-15:00; independent if-block following early_pre_3min/late_throw time-band convention). PATTERN_META + classify_death + 10 NewPatternThresholdsTests (assist-band + time-window edge cases). Live regen on 28236 deaths: NEW top-3 = solo_pickoff (59%) / small_skirmish (49%) / caught_4plus (44%) - small_skirmish DISPLACED rapid_repeat from top-3. midgame_collapse fires on 36% of deaths (10275). Assist-band mutual-exclusion intact (small_skirmish + caught_4plus + solo_1v1_loss sum to 100%).

**Slice C `6d22e2e` feat(dash):** /api/personal-context route + frontend panel. NEW `dashboard/routes_personal_context.py` (60s mtime-keyed cache; returns ok=false reason=no_data on missing file with HTTP 200 not 404 so panel renders empty state). NEW `web/js/panels/personal_context.js` + `web/css/panels/personal_context.css` (3-card vertical stack inside Right Now panel body: label + count chip + rate% chip + truncated description; data-kind border tints by pattern key). Loader `core/death_patterns_loader.py` extended `top_patterns()` with rate/confidence + NEW `report_summary()` so the route reads via the loader (single source-of-truth). Wired in `_homeWireStartup` next to existing home poller. +31 tests (12 route + 19 DOM). Live curl `/api/personal-context` returns ok=True with the post-slice-B top-3.

**Slice A `3cfea90` feat(ops):** cadence task. NEW `ops/install_RC_PostmortemAnalyze.ps1` registers `RC-PostmortemAnalyze` weekly Sundays 04:15 (15 min after RC-RewindCatchup at 04:00 so new matches land first). NEW `ops/run_postmortem_with_restart.ps1` wrapper - runs analyzer, logs stdout/stderr to `logs/postmortem_analyze.YYYY-MM-DD.log`, writes `restart_trigger.txt` ONLY on clean exit so coach prompts reload PERSONAL CONTEXT at module import. Pattern mirrors `install_RC_RewindCatchup.ps1` + `install_RC_DDragonMirror.ps1` (PowerShell 5.1 `MultipleInstances=IgnoreNew` property-after-construction workaround). Task registered LIVE in this session: NextRun=2026-05-24T04:15:15 LastTaskResult=267011 (=0x41303 "task not yet run", expected on fresh register).

**Slice D `3cfea90` docs:** ROADMAP.md line 70 PGR aggregator-G-style reframe flipped 🟡 -> ✅. All S2-S5 shipped per CLAUDE.md items 115-118 (S2 `23e36d3` / S3 `92c6a0f` / S4 `d199f30` / S5 `7870124` + S5 follow-up). Compact summary replaces the 800+ char carry-forward prose; full per-stage detail stays in the CLAUDE.md ledger. Other open ROADMAP/BACKLOG entries verified current (BACKLOG line 15 SR records "blocked on new records" still TRUE - 0 SR records in `data/ds_calibration.jsonl`).

**Tests:** full RC suite 2692 -> **2733 passed / 0 failed** (+41: 10 slice B + 31 slice C). Slice A is .ps1-only (no pytest coverage; PowerShell parse-clean verified via `[System.Management.Automation.Language.Parser]::ParseFile`).

**Don't-redo:**
- `small_skirmish` is assist-band elif (mutually exclusive with caught_4plus + solo_1v1_loss); `midgame_collapse` is independent if-block (co-exists with assist-band tags; mirrors early/late convention). The agent's precedence call to use independent-if for midgame matches the existing classifier shape - do NOT collapse to a single elif chain.
- `/api/personal-context` returns HTTP 200 with `ok=false, reason="no_data"` on missing JSON (NOT 404). The panel needs to render an empty state, not a fetch error.
- Cache key on the route is FILE MTIME (not wall-clock TTL); 60s window. The loader stays single-source-of-truth - the route does NOT duplicate file-reading logic.
- Personal-context panel mounts INSIDE Right Now panel body (after SCREEN READ block); supplementary to live coach output. Do NOT move to its own sibling panel without operator approval.
- RC-PostmortemAnalyze is LIVE NextRun 2026-05-24T04:15. Wrapper writes `restart_trigger.txt` only on clean exit (analyzer exit 0). Log to `logs/postmortem_analyze.YYYY-MM-DD.log`. The 15-min offset after RC-RewindCatchup is load-bearing - rewind must complete first or the analyzer reads stale matches.
- ROADMAP line 70 is now ✅ SHIPPED; CLAUDE.md items 115-118 hold the per-stage detail. Do NOT re-pitch a new PGR stage - the full S2-S5 chain is closed.

**Carries forward:**
- ADR-007 phase 3 (prose-coach deprecation) STILL gated on operator playing 20+ SR games per the ADR. Unchanged from item 124.
- Live ARAM/SR smoke STILL pending (need a real game to confirm coach output references the new patterns when situationally relevant).
- 2026-05-24 04:15 first scheduled run is the live test of the cadence wire - check `logs/postmortem_analyze.2026-05-24.log` + `Get-ScheduledTaskInfo -TaskName RC-PostmortemAnalyze` for LastTaskResult=0.
- BACKLOG line 15 (rewind_history.db SR records with game_id) still blocked on zero SR records in `data/ds_calibration.jsonl` (1251 total lines, 0 SR).
- Item 124 + 123 + 122 carries unchanged.

---
# 2026-05-21 - ADR-007 phase 2 postmortem-analyze SHIPPED (1 commit `b3cd60b`)

Operator: "continue what is next to work on". Work-surface check: engine 1.26.0 ceiling per item 123, cost/latency exhausted, UI/UX live-game-gated. Path-stale-checked BACKLOG NOW lane via DB probe (28k CHAMPION_KILL events vs operator PUUIDs) -> ADR-007 phase 2 genuinely unbuilt + deferred since s169 (10 days). Operator AskUserQuestion-picked it from a 4-option fork. Full vertical slice shipped.

**Commit `b3cd60b` feat(coach):** 4 NEW files (`scripts/postmortem_analyze.py` + `core/death_patterns_loader.py` + 2 tests) + 6 prompts in 4 coach modules + `.gitignore` add + ROADMAP/CLAUDE sync. +875 -7 LOC.

**(a) `scripts/postmortem_analyze.py`** mines `data/rewind_history.db` for tracked PUUIDs (auto-resolves current + stale from `rewind_catchup.state.json`). 6 patterns: `caught_4plus` (assists>=3) / `solo_1v1_loss` (assists==0; mutually exclusive with caught) / `early_pre_3min` / `solo_pickoff` (no ally death in 8s window; team-filtered via participants.team_id) / `late_throw` (>=25min) / `rapid_repeat` (<=60s after prior self-death; per-match tracking). Laplace-smoothed rates via `core/smoothed_rates.py`. Atomic tmp+replace write to `data/coaching/death_patterns.json` (gitignored - personal data + PUUIDs).

**Live run:** 28,236 deaths / 2,838 matches / 0.04s. **Top-3: solo_pickoff (16595, 59%) / caught_4plus (12345, 44%) / rapid_repeat (6165, 22%).** Genuinely actionable.

**(b) `core/death_patterns_loader.py`** fail-soft reader + `personal_context_block()` formatter. Empty string when no top-3.

**(c) 6 coach prompts wired:** appended after the closing triple-quote of each (NEVER mid-block - cache-prefix preservation per [[reference_coach_choices_native_emit]]). aram_coach `_SYSTEM` / arena_coach `_SYSTEM_PROMPT` / brawl_coach 3 prompts (NB/URF/OFA) / coach_integration._sr_prompt `SR_SYSTEM_PROMPT`. `ARAM_SYSTEM_PROMPT` inside `_sr_prompt.py` DELIBERATELY left untouched (legacy, test-pinned not-modified).

**Tests:** RC 2662 -> 2692 (+30: 24 analyzer + 6 loader). 87 existing coach-choices-emit still green. py_compile + ruff + ASCII clean on all 8 touched files. CI green.

**Don't-redo:**
- 6 pattern thresholds operator-tuned away from noise (caught_4plus at >=3 NOT >=1 which fired on 92% of all deaths; solo_1v1_loss at ==0 mutually exclusive via elif)
- personal_context_block APPENDED after closing `"""` - do NOT refactor to f-string substitution or inline insertion (cache-prefix preservation)
- ARAM_SYSTEM_PROMPT in `_sr_prompt.py` is legacy + test-pinned not-modified; active ARAM owns its own prompt under `coaches/aram_coach.py`
- solo_pickoff filters ally deaths by participants.team_id (NOT all prior CHAMPION_KILLs); do NOT regress to team-blind
- data/coaching/death_patterns.json is gitignored (personal data + PUUIDs); do NOT commit
- Module-load caching is intentional; regenerate via `py scripts/postmortem_analyze.py && echo restart > restart_trigger.txt`

**Carries forward:**
- Cadence: analyzer is MANUAL. Optional weekly cron alongside RC-RewindCatchup (Sundays 04:00) is operator-gated.
- Live ARAM/SR smoke: prompts carry PERSONAL CONTEXT but Live Client games needed to verify coach output references patterns when situationally relevant.
- ADR-007 phase 3 (prose-coach deprecation) is the next logical follow-up but DELIBERATELY out-of-scope per the ADR's explicit "defer until phase-1 detectors prove out in real games" gate.
- All item 123/122/121 carries unchanged.

---
# 2026-05-21 - headless-upgrade run: ASCII drift catch (1 commit `b56f156`)

Short autonomous /headless-upgrade run; work surface EXHAUSTED at engine 1.26.0 ceiling.

**Phase 0:** baseline gathered (DS 2860 / RC 2662 / CI 6/6 green / ENGINE 1.26.0 / DDragon cron 03:30:30 LastResult=0 = item 110 retry-with-backoff fix proven live).

**Phase 1 (only shipped phase):** `b56f156` chore(ascii): strip UTF-8 BOM from 4 non-frozen `.py` (ops/rc_self_monitor.py + ops/rc_state_validator.py + scripts/team_planner_sync.py + tft/tft_coach_engine.py) + close 2 Python SyntaxWarnings (tools/build_installer.py:136 `\;` -> `\\;` runtime byte-identical; tools/extract_panels.py:1-4 docstring -> r-string + U+2192 arrow -> ASCII `->`). py_compile + ruff + ASCII clean. No behavior change. No test changes. No frozen edits. CI green (1m26s).

**Phases 2/3 skipped (honest verdict):** DS audit halted at 1.26.0 streak 13 per item 122; cost/latency lever surface exhausted (prompt-cache fully covered item 120; log spam 8 endpoints item 121; polling sane); UI/UX live-game-gated.

**ops/rc_supervisor.py BOM left alone:** frozen file + retroactive non-ASCII sweep is operator-gated per CLAUDE.md. Don't auto-action.

**New memory:** `feedback_backlog_path_stale_check.md` - before recommending "next NOW-lane item", grep proposed paths against live codebase; generalizes [[feedback_verify_generated_reports]] from API output to source state. Catches the same way item 122 caught 4 stale BACKLOG entries.

**Don't-redo:**
- engine 1.26.0 Meraki-coherent ceiling; no DS audit work without Meraki-confirmed drift
- ops/rc_supervisor.py BOM is operator-gated retroactive (not a current-run frozen-edit candidate)
- ASCII drift now clean across non-frozen .py; the recheck (`py -c "import ast,pathlib;..."`) is the durable detector
- aram_tenacity_mult end-consumer is intentionally a forward-marker per BACKLOG; do NOT speculatively wire

**Carries forward:** all item 122 / 121 / 119 carries unchanged. None new.

---
# 2026-05-21 - BACKLOG drain: aram_tenacity_mult EHP wire + Dead Man's Plate stacks-schema lift + ROADMAP/BACKLOG sweep (ENGINE 1.24.0 -> 1.26.0)

Operator asked "what is next" - identified item-AH lane + ward-heat frontend as ALREADY SHIPPED (paths-stale BACKLOG entries; verified via git log: f273acb f4938af). Pivoted to 3 genuine NOW items, all 3 shipped.

**Commits (3 + 2 from start-of-day pass-3+4 earlier):**
- `e9bf6b3` docs(roadmap+backlog): sweep stale SHIPPED from open-high (3 headless-upgrade entries) + coaching-depth (2 SHIPPED notes + item-AH queued + ward-heat queued).
- `ce563c4` feat(ds): aram_tenacity_mult EHP wire + Dead Man's Plate stacks-schema lift (ENGINE 1.24.0 -> 1.26.0).

**(1) ENGINE 1.25.0 - aram_tenacity_mult EHP wire:** EhpResult gains `aram_tenacity_mult` field; NEW `effective_cc_duration(base_cc_s, tenacity_mult)` helper in `ehp.py` returns `base_cc_s * max(0.0, tenacity_mult)`. 17 ARAM champs carry non-1.0 tenacity (Akali/Belveth/Ekko/Elise/Evelynn/Fizz/Katarina/Kayn/Khazix/Lucian/Nunu/Pyke/Qiyana/Quinn/Rengar/Talon/Zed; mostly 1.20, Elise/Fizz 1.10). The helper is the seam any future fight-sim / coach-prompt / EHP-vs-CC consumer reads. Blended EHP math UNCHANGED - CC duration vs HP pool is a separate axis. SR + non-ARAM modes degenerate to identity. +19 tests in test_ehp.py.

**(2) ENGINE 1.26.0 - Dead Man's Plate Momentum stacks-schema lift:** NEW `PeriodicProc.stack_ramp_seconds` field is the family extension for the stack-accumulation -> discharge pattern. Default 0.0 (backward-compat). Consumer in `_periodic_proc_dps` fires at `max(stack_ramp_seconds, every_n_attacks * attack_period_s)`. Burst path (`_per_attack_proc_damage`) skips ramp-gated procs. Dead Man's 3742 + Arena 223742 re-encoded: Shipwrecker = lambda c: 40 + c.base_ad PHYSICAL, every_n_attacks=1, stack_ramp_seconds=3.57. Math verified exact: Aatrox L11 vs 100-armor target delta = (40 + 103.875)/3.57 * 0.5 = 20.15 DPS. +18 stacks-schema tests in NEW test_stack_ramp_schema_126.py; 5 existing DeadMansPlate tests rewritten for post-lift state. Other items can adopt the same schema in future iterations.

**Stale entries swept:** ROADMAP "Open items - High priority" shed 3 headless-upgrade entries (items 119/120/121 - paths-stale duplicates of CLAUDE.md ledger). BACKLOG "Coaching depth" shed 4 entries: aramAbilityHaste SHIPPED note (4e5d818) + augment formula evaluator SHIPPED note (21657eb) + item-AH "queued" entry (actually shipped f273acb) + ward-heat frontend "queued" entry (actually shipped f4938af).

**Verified:** DS suite 2823 -> 2860 / 1 xfailed (+37); RC suite 2661 -> 2662 / 0 failed (+1); ruff + py_compile + ASCII-clean on additions. DS :8893 restarted TWICE via taskkill + schtasks /Run RC-DaemonSlayer; live /health serves 1.26.0. RC :8888 not restarted (engine wire is DS-side; RC consumes over HTTP).

**Don't-redo:**
- DS item-AH lane is SHIPPED (`f273acb` feat(ds): per-item flat AH wired) - the registry path was chosen over the originally-proposed `ItemEffect.ability_haste_flat` field but the OUTCOME is equivalent; do NOT re-pitch the field+extractor approach.
- Ward-Coverage Heat Strip frontend is SHIPPED (`f4938af`) - `core/ward_producer.py:install_liveclient_listener` wired in `main.py:149`; do NOT re-pitch a frontend-wire follow-up.
- `aram_tenacity_mult` on EhpResult is FORWARD-MARKER for fight-sim consumers; the EHP blended_ehp math is intentionally unchanged. Use `effective_cc_duration(base_s, tenacity_mult)` as the seam; the helper is the ONLY downstream contract.
- `PeriodicProc.stack_ramp_seconds` is mutually exclusive with `every_n_seconds` (the seconds-based path has no ramp semantics - ramp is implicit). __post_init__ enforces; tests pin.
- The burst path intentionally skips stack-ramp-gated procs - tank items with sustained-only DPS. Do NOT special-case Dead Man's in burst (a 3.57s ramp doesn't fit a 2-3s burst window).
- 5 DeadMansPlateShipwreckerTests in test_effects_expansion.py were rewritten for the post-lift state; do NOT re-add `defensive_only=True` assertions.

**Carries forward:**
- (a) Dead Man's stack-ramp schema is the canonical example for future stack-discharge items. Sterak's Lifeline + hypothetical future ramp items can adopt the same field. No items queued today.
- (b) `effective_cc_duration` has no live consumer yet - the fight-sim / coach-prompt consumer is still future. The seam is in place.
- (c) Standing operator-gated items unchanged: 101.qq.com one-off capture (ROADMAP med); Arena S2 patch 26.09 reconnaissance + CSS anchor-positioning lift; per-page UI audit ritual after a live game.

---
# 2026-05-21 - HEADLESS UPGRADE PASS 3 + PASS 4: design tokens sweep + log spam extension + ALL 4 coaches native choices emit

Operator re-extended scope: each /headless-upgrade re-run strips done items + folds in more DS work. No user gating.

**Pass-3 (3 commits):**
- `385f5e8` extend log spam suppression 3 -> 8 endpoints. Pass-2 covered the 2Hz pollers (~81% of log volume). Pass-3 adds asset-stamp + ui-version + activity + env + locked-champion (5-15s cadence each but cumulative ~1400 lines/hr extra). Total suppression now ~95% of log_message volume.
- `5cefe30` design tokens consumption sweep on item_build.css + team_context.css + bridge_pending.css. 9 hex swaps to var(--signal-*). 4 outliers intentionally preserved with rationale (wave-state thresholds, Riot tier colors, team tints, salmon brand).
- `6b92382` ARAM coach native choices emit (worktree H). Appended `Choices: <OPTIONAL...>` to OUTPUT FORMAT block at aram_coach.py:257 + JSON passthrough at lines 817-833 + `cur["choices"] = _choices_list` at line 842. +16 tests.

**Pass-4 (2 commits):**
- `14737a7` Arena coach native choices emit (worktree I). Mirrors ARAM at arena_coach.py:86 + _OUTPUT_KEYS gains "choices" at 123-126 + passthrough at 606-623 + cur.update key at 634. +23 tests.
- `58b7d20` Brawl + SR coaches native choices emit (worktree J in ONE commit). Brawl has 3 prompts (NB/URF/OFA) each gain Choices + 3 _OUTPUT_KEYS lists + shared passthrough. SR has split structure: coach_integration/_sr_prompt.py SR_SYSTEM_PROMPT gains Choices after Risk + coach_integration/_coach.py `_parse_response field_map` gains "choices":"choices" entry + passthrough mutates `fields["choices"]` from string to list BEFORE `current.update(fields)` (structural deviation pinned by tests). ARAM_SYSTEM_PROMPT in _sr_prompt.py intentionally untouched (ARAM owns its own prompt in coaches/aram_coach.py). +49 tests.

**ALL 4 per-mode coaches now emit native A/B/C choices arrays:** ARAM + Arena + Brawl (NB/URF/OFA) + SR. The dashboard's `_state_builder.py` prefers `core.coach_choices.parse_choices(coach)` (native) and falls back to `synthesize_simple_choices(coach)` (pure-Python A/B from action prose) when native is absent. Synthesizer stays as bootstrap + safety net.

**Cost contract:** zero extra LLM calls. Native emit rides existing per-tick coach call (LLM returns prose + choices in ONE response). Cache prefix preserved (Choices APPENDED to OUTPUT FORMAT, never mid-block).

**Schema (mirrors core.coach_choices.CoachChoice):** `{key:"A|B|C", label:"<3-5 word>", expected_outcome:"<one sentence>", confidence:"low|mid|high", source_tag:"<3-10 char>"}`. Max 3 entries. Per-mode source_tag suggestions in each coach prompt: ARAM (fight-trade/pack-grab/scaling/siege-call/augment-pivot), Arena (augment-pick/round-trade/duo-rotate), Brawl (fight-trade/respawn-window/objective-pace), SR (lane-state/rotate-ward/team-fight).

**+88 tests total across passes 3+4** (16 ARAM + 23 Arena + 28 Brawl + 21 SR). All emit-test files share the pattern: PromptShapeTests (prompt contains Choices + schema + key letters + confidence enum) + ParserPassthroughTests (valid passthrough + missing -> empty + malformed -> empty no crash) + CachePreservedTests (Choices APPENDED to end of OUTPUT FORMAT) + JsonDecodeBehaviorTests.

**Memory saved:** `reference_coach_choices_native_emit.md` - per-mode pattern + SR deviation + source_tag suggestions + don't-redo.

**Verified:** py_compile + ruff + ASCII clean on all touched files; CI green on all 4 commits (`385f5e8` + `5cefe30` + `6b92382` + `14737a7` + `58b7d20`); RC :8888 restarted once after pass-2 handler edit + pass-3 handler extension hot-reloaded on next request; coach prompt changes pick up on next coaching tick (no RC restart needed).

**DS audit cycle status:** HALTED at streak 13 from pass-2 (Black Cleaver 3071 + Voltaic 6699 + Eclipse 6692 all NO-CHANGE). Engine 1.24.0 formally Meraki-coherent.

**Don't-redo:**
- ALL 4 per-mode coaches now natively emit; do NOT pitch a 5th pass for the same task.
- The Choices line is APPENDED to OUTPUT FORMAT block, never mid-block (cache prefix preservation; CachePreservedTests in each emit-test pin this).
- Do NOT remove the synthesizer fallback in `_state_builder.py` - it's the bootstrap path AND the safety net.
- The SR coach's split-module structure + passthrough that mutates `fields["choices"]` from string to list BEFORE update is the only structural deviation - pinned by test_sr_coach_choices_emit.py.
- Log spam set (8 paths in `dashboard/_handler.py:_SUPPRESS_LOG_PATHS`) is calibrated to dashboard pollers; do NOT add without confirming > 1 log-line/sec steady-state.
- 4 panel-CSS outliers (wave-state thresholds / Riot brand tiers / team tints / salmon brand) intentionally preserved - they're domain-specific palette not semantic; do NOT swap to var().

**Carries forward:**
- (a) per-page UI audit ritual after operator plays a live game (the choices field will surface real LLM-generated A/B selections instead of the synthesizer heuristic; operator can review tutoring quality + tighten coach prompts if needed).
- (b) Arena S2 patch 26.09 reconnaissance + CSS anchor-positioning lift remain operator-gated.
- (c) any future game mode that adds a coach should follow the same Choices-emit pattern.
- (d) all item 120 carries unchanged.

No frozen edits this pass either. The pass-1 rewind-wire frozen edit remains the only frozen edit of the full headless-upgrade run.

---
# 2026-05-21 - HEADLESS UPGRADE PASS 2: DS audit HALT (streak 13) + close prompt-cache carries + log spam lever

Operator-extended scope: each /headless-upgrade re-run strips items already shipped + folds in more DS work and DS expansion under the same guidelines; no user gating; best-recommended choice + audit + test + iterate.

**Single commit `bb30e92`:** close prompt-cache carries (experimental_builder + replay_coach) + suppress high-frequency HTTP-request log spam. Pushed; CI green.

**Wave-2 (4 worktree agents parallel in 1 message):**
- DS-A Black Cleaver 3071 Carve - NO-CHANGE (Meraki 16.10.1 confirms 6%/stack = 30% max; engine correct). **Streak 10 -> 11 = HALT criterion reached per stop rule.**
- DS-B Voltaic Cyclosword 6699 Firmament - NO-CHANGE (100 flat phys + 10 lethality matches Meraki; no AD scaling - that was pre-rework formula).
- DS-C Eclipse 6692 Ever Rising Moon - NO-CHANGE (6% target max HP matches Meraki melee value).
- COACH+LOG combined slice - SHIPPED.

**Combined slice details:**
1. `coaches/experimental_builder.py:209` + `coaches/replay_coach.py:194` flipped from uncached `system=_SYSTEM_PROMPT` string-form to explicit-block list with `cache_control={"type":"ephemeral"}`. Closes pass-1 carry-forward (d). Marker pattern now CONSISTENT across all 8 messages.create() coach callers (aram_coach + arena_coach + brawl_coach + sr/coach_integration + champ_select_coach + aram_team_analyzer + experimental_builder + replay_coach).
2. `dashboard/_handler.py` NEW `_SUPPRESS_LOG_PATHS` tuple + rewrite `Handler.log_message` to skip 3 high-frequency 2Hz-poll endpoints (`GET /api/decisions ` + `GET /api/decisions/heartbeat ` + `GET /api/vision-state `). Sample log volume was ~7100 lines/hour (~90% of today's log file); suppression preserves error/info logging via separate log.warning/log.info calls (log_message is BaseHTTPRequestHandler's request-trace hook only; not a general logging filter).

**+17 tests across 3 NEW files:**
- tests/test_experimental_builder_cache.py (4): explicit-block + cache_control marker + text-carried + block-before-messages ordering
- tests/test_replay_coach_cache.py (4): same shape, system constant is _PROMPT
- tests/test_handler_log_spam_suppress.py (9): exact constant pinned + each of 3 paths suppressed + /api/state logged + POST /api/bridge/inbox logged + error-path call sites still present + log.warning bypasses suppression

**DS audit HALT milestone:** streak 13 consecutive no-changes (iter 20-32). Engine 1.24.0 declared formally Meraki-coherent at patch 16.10.1. Future DS work goes ONLY on Meraki-confirmed drift (no rumor-driven bumps; no exhaustive sweep churn).

**Verified:** py_compile + ruff + ASCII clean; CI green on `bb30e92` (1m20s). RC :8888 restarted via restart_trigger.txt -> pid 5844 alive=True last_reload_ok=True. Log spam suppression live; the 3 high-frequency endpoints stop emitting DEBUG lines immediately.

**Don't-redo:**
- DS audit cycle has HALTED at engine 1.24.0; do NOT pre-launch another exhaustive sweep absent Meraki-confirmed drift signal.
- Prompt-cache marker pattern is now CONSISTENT across all 8 messages.create() coach callers; the only callers WITHOUT a marker are the ones that don't pass a static system prompt at all.
- The 3-substring suppression set in `_handler.py:_SUPPRESS_LOG_PATHS` is calibrated to the 2Hz pollers - do NOT add to it without confirming the new path has > 1 log-line/sec steady-state.
- The log_message override is BaseHTTPRequestHandler's request-trace hook ONLY; error paths emit via log.warning/log.info elsewhere and are unaffected.

**Carries forward:**
- (a) coach prompt per-mode tuning to emit native `choices` arrays (queued; prompt engineering across aram/arena/brawl/sr coaches; zero LLM cost).
- (b) Arena S2 patch 26.09 reconnaissance + CSS anchor-positioning lift remain operator-gated.
- (c) all item 119 carries unchanged.

No frozen edits this pass. The pass-1 rewind-wire frozen edit was already merged.

---
# 2026-05-20/21 - HEADLESS UPGRADE RUN (6h, 23:22 CST -> 05:22 CST): /headless-upgrade skill collapse + A/B tutoring coach + rewind DB live writer + design tokens + champ_select prompt-cache + dict cache + UI polish sweep + 3-no-change DS audit pass

Operator-authorized 6-hour autonomous run with full authority + no user gating (20-day 100% acceptance pattern). Frozen-file edits permitted this run only.

**Scope reorientation:** collapse /done /clear /continue /compact /memory /audit /test /iterate /new-tech into one /headless-upgrade. Skill removes specific lever names + reorients to find cost+latency wins without product degradation. Up to 24 parallel worktree agents per task; orchestrator (this Claude) merges + resolves conflicts.

**8 commits, all pushed, all green CI:**
- `642d43b` chore(headless): /headless-upgrade skill rewrite + dict cache + alert poll
- `045d5fc` feat(coach): A/B tutoring choice block (chip buttons + read-only journal)
- `3d39ae7` Merge worktree D (design tokens)
- `0dbe5c9` Merge worktree B (rewind live writer)
- `a5efe11` fix(tests): ruff B017 - assertRaises(Exception) -> AttributeError
- `4064f87` perf(coach): apply prompt cache markers on champ_select_coach.py
- merge worktree F (UI polish: tabular-nums + text-wrap balance + .action pulse + draft_elo ESC)
- final docs sync commit (this commit)

**1. /headless-upgrade skill** (`tools/headless-upgrade.md` + `.claude/commands/headless-upgrade.md` mirror): 16 sections, full authority no-gating, max 24 parallel agents. Orchestrator pattern; design tokens; cost+latency lever sweep; UI/UX deep dive checklist (8px grid + 4-tier fs + semantic colors + widget unification + overlay design); A/B tutoring section; DS audit rule (11-no-change halt); rewind DB live wire; interrupt protocol; ASCII hygiene; anti-patterns; final-banner format.

**2. A/B tutoring coach choice block.** Reframes coach output from prose-only to optional A/B/C micro-decisions per tick. Each choice = key letter, label, expected outcome, confidence band (low/mid/high), source tag.
 - `core/coach_choices.py`: CoachChoice frozen dataclass; parse_choices forgiving parser; synthesize_simple_choices pure-Python fallback (Contest/Concede, Engage/Disengage, Push/Freeze, Recall/Stay, Ward/Skip, Rotate/Hold, Siege/Disengage).
 - `dashboard/_state_builder.py`: stamps coach.choices (parse > synth > []) on every /api/state envelope.
 - `dashboard/routes_coach_choice.py` POST /api/coach-choice -> `DecisionStore.record_coach_choice` in `core/decision_detector.py` -> appends type="coach_choice" to data/decisions_log.jsonl.
 - `web/js/panels/coach_choices.js` + `web/css/panels/coach_choices.css` + `<div id="rn-choices" hidden>` mount between #rn-immediate and Watch row in RIGHT NOW. Chips dedup via signature; click sets selected-class + POSTs.
 - Cost gate: native-emit rides existing per-tick coach call; synthesizer is zero-LLM bootstrap fallback. Read-only-first (no input wire, no auto-apply).
 - Live curl: POST /api/coach-choice 200 + entry in decisions_log.jsonl confirms end-to-end.
 - +51 tests across 3 files (parser safety + synth + serialization + ASCII + DOM mount + route validation + dispatch inclusion + 500 path).

**3. Rewind DB live writer (worktree B).** Streams new matches into rewind_history.db post-gameEnd (90s delay) instead of waiting for Sunday cron.
 - NEW `lib/rewind_live_writer.py` (347 LOC): schedule_live_insert(app) -> threading.Timer(90.0, daemon=True). Reuses scripts/rewind_scraper:insert_rows + scripts/rewind_catchup:write_match.
 - Hook = `app/_game_lifecycle.py::on_game_end()` (frozen file, +10 LOC under run grant) - isolated try/except after the existing postgame collector trigger. Fire-and-forget.
 - Failure modes silent: 404 (event mode), 403 (Personal-key), PUUID rotated, DC, gameDuration < 180s. 1 retry after 60s; abandons.
 - Idempotency: matches.match_id PRIMARY KEY + INSERT OR IGNORE. Pre-write probe skips Match-V5 round-trip.
 - +29 tests (Scheduler / PuuidResolver / Idempotency / FailureModes / WireSeam).
 - Weekly RC-RewindCatchup cron STAYS as resume sentinel.

**4. Design tokens (worktree D).** NEW `web/css/tokens.css` declares semantic palette + 4-tier font scale + 8px spacing grid + coach pulse keyframes.
 - `--signal-good/warn/bad/dim/info/gold` + `--*-soft` variants (rgba 0.18).
 - `--fs-xs/sm/md/lg/xl` (11/13/15/20/27px) - reserved for future consumption.
 - `--space-1..6` (4/8/12/16/24/32px) - reserved.
 - `@keyframes coach-pulse-good/warn/bad` (0.8s ease box-shadow glow).
 - `.tabular-nums` utility class.
 - dashboard.css `@import './tokens.css'` first.
 - 3-panel sweep: draft_elo / ban_suggest_toggle / right_now CSS swap hardcoded hex -> var(). Additive only.
 - +22 contract tests pinning shape.

**5. Champ-select prompt cache (worktree E).** `coaches/champ_select_coach.py:118` was string-form `system=_SYSTEM_PROMPT` (uncached). Flipped to explicit-block list with `cache_control={"type":"ephemeral"}` mirroring aram_coach.py:743-750. Real cost win on cache_read amortization. +5 pinning tests.

**6. Dictionary cache.** `dashboard/_handler.py:_send` gains optional cache_control kwarg (default "no-store" preserves all existing routes). `dashboard/routes_dictionary.py` opts the 4 dictionary endpoints (items/runes/champion-tags/augments) into `public, max-age=86400, immutable`. The docstring already promised this; implementation was missing. +3 CacheControlTests.

**7. Home alert poll downshift.** `web/js/main.js:2718` home alerts mirror 2000ms -> 5000ms (60% poll-cost drop on idle home view; data updates on user-trigger cadence, not real-time).

**8. UI polish sweep (worktree F).**
 - tabular-nums across 8 panels (right_now / next / item_build / team_context / augment_reco / spike_curve / ward_heat / draft_elo already).
 - text-wrap: balance on `.action` + `.action-mid` + `.lm-tc-mvp-name` + `.replay-events-chip-text`.
 - Coach prompt pulse-glow on .action when text changes between ticks: urgent->bad / fight->warn / good->good, 800ms keyframe dismissal, empty band silent.
 - draft_elo overlay ESC dismiss (document-level keydown; preserves HoverOnlyContractTests guard - no click handler, no pinned class).
 - +19 grep-style contract tests (test_ui_polish_2026_05_20.py).

**9. DS audit iter 27/28/29 NO-CHANGE (worktree C).** Statikk Shiv 3087, Rageknife 6677, Trinity Force 3078 Spellblade all verified against live Meraki bulk; engine values match. Streak now 10 consecutive (iter 20-29); 1 short of 11-iter halt rule. ENGINE 1.24.0 unchanged.

**Verified:** all touched files py_compile + ruff + ASCII clean; full RC suite 2533 passed; DS suite 2822 passed (+1 xfailed); CI green across the run (1 ruff B017 fix mid-run); RC :8888 restarted once (route + state builder edits) pid=14824 last_reload_ok=True.

**Memories saved (3 new):**
- `reference_ab_tutoring_coach.md` - chip wire + cost contract + don't-redo
- `reference_rewind_live_writer.md` - 90s delay + failure modes + idempotency
- `reference_design_tokens_css.md` - token palette + opt-in pattern

**Don't-redo (durable):**
- A/B coach `choices` field is expected on every /api/state envelope (empty list when no synthesizer match); do NOT remove the synthesizer fallback.
- Rewind live-writer hook is fire-and-forget Timer (daemon=True); do NOT block on_game_end on it.
- Dict-cache `public, max-age=86400, immutable` is calibrated to patch-refresh cadence.
- Statikk Shiv no-change was based on live Meraki bulk; do NOT pre-ship rumored buffs - only Meraki-confirmed drift.
- Design tokens 4-tier font scale + 8px spacing are RESERVED for future consumption; do NOT bump existing selectors without operator approval.
- HoverOnlyContractTests guards draft_elo against click-to-pin; the ESC handler is the only addition allowed - do NOT add click handler.
- The orchestrator-merge pattern (worktree agents -> Claude merges sequentially) is the durable template for future headless-upgrade runs.

**Carries forward:**
- (a) Coach prompt per-mode tuning to emit native `choices` arrays (no LLM cost; prompt engineering across aram/arena/brawl/sr coaches).
- (b) DS audit streak is at 10 - 1 more no-change halts the cycle (operator-gated whether to do 11th confirmation pass or declare halt).
- (c) Arena S2 patch 26.09 reconnaissance + CSS anchor-positioning lift remain operator-gated.
- (d) Prompt-cache marker pattern from worktree E should be 1-grep'd against any OTHER coach not already using it.
- (e) All item 118 / 117 / 116 / 115 carries forward unchanged.

Frozen-file grant used minimally (1 line in app/_game_lifecycle.py); grant does NOT carry forward.

---
# 2026-05-20 - s220 PGR S5 follow-ups: participant-name join + lm-build-pending dead-id cleanup (1 commit pending, will push; non-engine; no frozen edits; RC restarted once for route module edit)

Closes the two carries-forward from item 117 / s220 S5 per the NEXT_SESSION_QUEUE the prior session left in this file. Operator-authorized scope: non-frozen-files only; commits + pushes allowed; RC restart for route-module edits.

**(1) Participant-name join in /api/replay/events.** Backend `dashboard/routes_replay_events.py`:
- NEW `_participant_meta(conn, match_id) -> dict[int, (summoner_name, champion_name)]` helper joins the `participants` table, blank strings normalized to None for null-parity.
- Each event dict gains 6 fields: `actor_name`, `actor_champion`, `victim_name`, `victim_champion`, `assists_names: list[str|None]`, `assists_champs: list[str|None]`. Empty strings normalize to None (audit refinement).
- Cache key gains `_CACHE_SCHEMA = "v2-participant-join"` sentinel so stale pre-join entries evict on first hit (audit refinement) - not on TTL expiry.
- Module docstring updated with new event shape.

Frontend `web/js/panels/replay_events.js`:
- NEW `_portraitUrl(champ)` mirrors `cd_ledger.js:74-79` alphanum-strip pattern (load-bearing for Kai'Sa/Cho'Gath punctuation). CHAMPS import from items_index.js for version.
- `_actorText`/`_victimText` REFACTORED to `_actorChip`/`_victimChip` returning HTML with DDragon portrait `<img>` + name text. NEW `_chipHtml(pid, champ, name, prefix)` builds the 3-tier fallback chain: champion portrait + champ text -> summoner_name only -> P<id> (kept as ultimate fallback for event-mode esoterica with null champion).
- `<img onerror="this.style.display='none'">` collapses cleanly on a 404.

CSS `web/css/panels/replay_events.css`:
- Row grid widened `52px 1fr 60px 80px` -> `52px 1fr 110px 130px` to fit champion names.
- NEW `.replay-events-portrait` (18px square, flex-shrink:0, object-fit:cover).
- NEW `.replay-events-chip-text` (white-space:nowrap, ellipsis overflow, min-width:0).
- `.replay-events-victim` text-align:right -> `justify-content: flex-end` to honor new flex container.

**(2) `lm-build-pending` dead-id cleanup.** Single-line edit at `web/js/panels/last_match.js:1132`: forEach array in `_setEmptyState` no longer carries the dead id. Was a no-op `getElementById` return null fall-through; only `lm-tc-pending` + `lm-chart-pending` + `lm-tl-pending` exist in index.html. The 2 guarded `if (pending) ...` references in `_setEnrichedBuild` are LEFT ALONE - safe dead code per operator's "single-line cleanup" scope.

**Parallel audit (S5 pattern continued):** general-purpose subagent dispatched in BACKGROUND with the design intent + just-edited code. 5 findings returned during the test cycle, 3 actionable refinements applied in the SAME commit: (a) null-parity for assists_names/champs (was: empty strings), (b) DDragon portrait icon via `cd_ledger.js:74-79` pattern, (e) cache schema sentinel for stale-eviction. Findings (c) GPL cleanroom + (d) payload size verified safe - no action needed.

**+12 tests across 3 files:**
- `tests/test_routes_replay_events.py` +5: test_champion_kill_carries_participant_names_and_champs / test_assist_names_use_null_parity_for_unknown_pid / test_non_actor_event_has_null_names / test_cache_key_carries_schema_sentinel.
- `tests/test_replay_events_panel_dom.py` +6: ParticipantJoinConsumptionTests (5: CHAMPS import + alphanum-strip portrait URL + new-field consumption + chip helpers + P-id fallback) + CssGridWidenedForNamesTests (1).
- `tests/test_last_match_tabs_reframe_dom.py` +1: test_set_empty_state_does_not_reference_dead_id.

**Verified:** py_compile + ruff + ASCII clean across all 7 touched files; full RC suite **2401 passed / 67 subtests / 0 failed** (+12 over post-S5 2389). RC :8888 restarted (restart_trigger.txt because route module edited): pid=13016 alive=True last_reload_ok=True. Live curl proof on NA1_4683461559 (older match with summoner_name populated): CHAMPION_KILL t=140 actor=Sona/Forniami -> Lucian/Eisstrahl assists_names=['shaodw'] - the join works end-to-end. Live curl NA1_5560540832 (operator's recent match, summoner_name blank in DB): event=Jax actor_name=None - the null fallback handles cleanly, portrait + champion-text renders. Cache hit on second curl returned cached=True count=82. ADR-008 asset-hash auto-bumps cover JS/CSS; no DS restart; no ENGINE bump; no frozen-file edits.

**Don't-redo:**
- Participant join is FORWARD-COMPATIBLE - summoner_name is blank for newer matches in rewind_history.db; the chip's 3-tier fallback handles cleanly. Do NOT pretend the field is always populated.
- `_portraitUrl` alphanum-strip is LOAD-BEARING for Kai'Sa/Cho'Gath display-name punctuation - do NOT remove.
- `_CACHE_SCHEMA = "v2-participant-join"` sentinel is the durable mechanism for breaking-shape cache evictions - bump the sentinel string in the SAME commit as any future event-dict shape change.
- The 3-tier chip fallback (champ-portrait+text -> name only -> P<id>) is intentional.
- CSS grid widening 60/80 -> 110/130 is pinned by `CssGridWidenedForNamesTests::test_css_actor_victim_columns_widened` - do NOT shrink back.
- `_setEnrichedBuild`'s 2 `if (pending)` lm-build-pending guards are LEFT ALONE per operator's single-line scope; they no-op safely. Do NOT fold them into a wider sweep without operator approval.

**Carries forward:**
- S5 OBS video overlay remains operator-deferred (its own ADR + dependency decision per ADR-009 "Watch for").
- Future polish: (a) portrait-only chips for ultra-compact ribbon (currently portrait + name text); (b) hover-tooltip click-to-deep-link to participant detail view in a future PGR drilldown.
- All item 117/116/115 carries-forward unchanged.
- Frozen-file grant NOT used; does not carry forward.

---
# 2026-05-20 - s220 PGR S5 Replay scaffold + Match-V5 timeline events ribbon (1 commit 7870124, pushed; non-engine; no frozen edits; RC restarted once for new route module)

**FINAL S2-S5 stage of the s220 aggregator-G-style Post Game Review reframe.** Operator: "start next: s5 (Replay page scaffold + Match-V5 timeline + league_record GPLv3 cleanroom reference)". s220 chain is now COMPLETE end-to-end.

The existing Replay view (per-frame scrubber over `rewind_history.db.timeline_frames`) gains a sidecar **Match-V5 timeline event ribbon** under the scrubber. Default ribbon (~80-160 events for a 35-min SR match) shows CHAMPION_KILL + BUILDING_KILL + ELITE_MONSTER_KILL + TURRET_PLATE_DESTROYED; `[items][skills][wards]` checkboxes opt-in for ITEM_PURCHASED / SKILL_LEVEL_UP / LEVEL_UP / WARD_PLACED / WARD_KILL.

**Backend NEW `dashboard/routes_replay_events.py`:** GET `/api/replay/events?match_id=<id>[&include=items,skills,wards,all]`. Server-side event_type filter keeps payloads 5-15 KB. 5min TTL cache keyed on `(match_id, include_set)`. Fail-soft 400/404/503. BUILDING_KILL.team_id stores OWNER that LOST the building - the route FLIPS to destroyer-side so the ribbon paints by actor.

**Frontend NEW `web/js/panels/replay_events.js` + CSS:** vertical scrolling list mounted under `#replay-events-section` inside `view-replay` `<main class="replay-main-pane">`. Team-tinted left borders (ally=green / enemy=red) + kind-tinted labels (kill=red, structure=warn, objective=gold, ward=ok, item=accent). Filter checkboxes persist via `localStorage[rc-replay-events-include]`.

**PGR Review button routing FIX (pre-S5 broken):** pre-S5 wire routed to `#review` (not in VIEW_IDS) which silently fell back to Home. S5 routes to `#replay` + renames sessionStorage key `rc-review-focus-match` -> `rc-replay-focus-match`. `_replayViewRefresh` consumes+clears the focus id; `_replayLoadMatch` auto-fires on the focused row.

**Pre-existing CSS bug fix exposed by S5:** `header.css:613` had `body[data-view="replay"] main { display: none }` intended to hide the top-level dashboard `<main>`. The selector unintentionally also hid the nested `<main class="replay-main-pane">` - so the entire Replay scrubber + grid + events ribbon were invisible. Pre-S5 nobody clicked deep enough to notice. Surgical un-hide: `body[data-view="replay"] main.replay-main-pane { display: flex }` (class-targeted specificity wins).

**NEW `docs/adr/ADR-009-replay-events-cleanroom.md`** captures the league_record (GPLv3) cleanroom boundary: methodology reference for future OBS video overlay; do NOT vendor source (GPL incompatible). `.rofl` parsing dead-end (2026-05-17 fraxiinus/roflxd confirmation) - do not re-pitch.

**Parallel-audit pattern (operator's "edits and audits in parallel" instruction):** architecture-review subagent dispatched in BACKGROUND with design intent + repo state while the route was being written. Audit returned 4 refinements that landed in this commit: keep #replay not #review + rename sessionStorage key; server-side filter; ADR not just comment; no pre-split of routes_coach.py.

NEW `tests/test_routes_replay_events.py` (17 tests across 5 classes) + `tests/test_replay_events_panel_dom.py` (22 tests across 6 classes). Pins default strong-set + clock order + actor/victim/pos + BUILDING destroyer-flip + include widening + fail-soft + cache + ADR + #replay routing + sessionStorage key + cleanroom + ASCII.

**Verified:** py_compile + ruff + ASCII clean across all 12 touched files; full RC suite **2389 passed / 67 subtests / 0 failed** (+39 over post-S4 2350 baseline); live curl `/api/replay/events?match_id=NA1_5439050124` ok=true count=100 elapsed_ms=1 cached=false / cached=true on rehit; live Playwright @ /#replay on operator's most recent match NA1_5560540832 (Kai'Sa, May 14, 44:47 Normal Draft, Loss) showed 211 events strong-only with chronological order (3:50 Kill / 4:49 Plate TOP / 8:43 Grubs HORDE / 9:28 Dragon HEXTECH_DRAGON / 9:47 Kill / ...).

ADR-008 asset-hash auto-bumps cover JS/CSS; dashboard restarted ONCE to register the new route module. No DS restart. No ENGINE bump. No frozen-file edits.

**Don't-redo:** Match-V5 timeline events from `timeline_events` is the CANONICAL event source - do NOT re-pitch `.rofl` parsing. `league_record` (GPLv3) is methodology-only - do NOT vendor source; tests + ADR guard. BUILDING_KILL.team_id is FLIPPED to destroyer-side server-side. PGR Review button routes to `#replay` not `#review`. The `body[data-view="replay"] main.replay-main-pane { display: flex }` un-hide is LOAD-BEARING - do NOT remove without refactoring the broader selector. Server-side filter default (strong-only) is deliberate - WARD_PLACED (284k) + ITEM_PURCHASED (528k) would drown signal. Cache key is `(match_id, include_set)` not match_id alone. Audit-in-parallel pattern is durable.

**Carries forward:** S2-S5 of the s220 aggregator G PGR reframe are now ALL SHIPPED end-to-end. Future operator-gated slices: (a) OBS video overlay keyed to LCU game-lifecycle (its own ADR + dependency); (b) participant join for real summoner names in events (currently P1..P10 chips); (c) pre-existing `lm-build-pending` dead-id in `_setEmptyState` (S4 audit flagged, still out of scope). Item 116 + 115 carries unchanged. Frozen-file grant NOT used this session.

---
# 2026-05-20 - s220 PGR S4 tabs reframe 4 -> 3 (1 commit d199f30, pushed; non-engine; no frozen edits; no RC restart needed)

Stage S4 of the s220 aggregator-G-style Post Game Review reframe. Operator: "for the PGR page start next: S4 (tabs reframe)" + "do these edits and audits in parallel when possible".

Tab strip flipped 4 -> 3 per the aggregator G pattern:
- **Build** = was Comp (rosters with full per-player items + MVP/SVP card from S3)
- **Graph** = was Chart (team bars) MERGED with Timeline visuals (sparklines + objective ribbon)
- **AI Analysis** = was Insights (Quick Review 3-col) MERGED with Timeline heuristics (WPA Phases)
- **Review** nav button stays (routes to deep-review page).

Legacy localStorage migration via NEW `_migrateLegacyTab(saved)` in `wireLastMatchOnce`: `comp -> build` / `chart -> graph` / `timeline -> graph` (visuals home) / `insights -> ai-analysis`. Migrated value writes back in a one-shot so subsequent loads see new id verbatim. NEW `_VALID_TABS = ["build", "graph", "ai-analysis"]` allowlist gates `_activateTab`. Inner element IDs unchanged - CSS attr-selectors stay agnostic, JS doesn't have to rewire.

**Parallel audit win:** UI-audit subagent dispatched in BACKGROUND with the design intent + just-edited code while implementation was in-flight. Audit returned during the test/verify cycle. Findings: 1 real minor (stray "Timeline unavailable" banner in merged Graph) + 2 doc nits + (caught visually) 1 pre-existing CSS gap (`.lm-wpa-wrap` had `display: flex` but no `[hidden]` rule, so the Phases head bled through). All 3 fixed in the SAME commit, not a separate slice. Matches operator's "edits and audits in parallel" instruction directly.

NEW `tests/test_last_match_tabs_reframe_dom.py` +15 grep-based DOM-contract tests across 5 classes: TabStrip (4) + PanelMount (4) + LegacyMigration (5) + CssNoLegacySelectors (1) + AsciiHygiene (1). Pins 3 canonical tab ids + Build-default-active + legacy-id absence + Review-nav-button kept + Build/Graph/AI-Analysis mount locations + WPA-above-Quick-Review ordering + each legacy-id mapping case + writeback gate + legacy-array absence + CSS legacy selectors absence.

**Verified:** py_compile + ruff + ASCII clean across all 5 touched files (`web/index.html` + `web/js/panels/last_match.js` + `web/js/panels/post_game_phases.js` + `web/css/panels/last_match.css` + `tests/test_last_match_tabs_reframe_dom.py`); full RC suite **2350 passed / 67 subtests / 0 failed** (+15 over post-S3 2335 baseline); live Playwright @ `https://127.0.0.1:8888/#last-match` on operator's ARAM Vel'Koz 4/9/25 across all 3 tabs - Build = MVP cards + rosters (hero 48 BAD + SVP bliv 64 OK + MVP GenieInTheLamp 77 GOOD persisting); Graph = team-aggregate bars NO stray banner; AI Analysis = Quick Review 3-col with WPA hidden cleanly when no Match-V5 timeline.

ADR-008 asset-hash auto-bumps cover JS/CSS; index.html picks up on next page nav. No RC restart. No DS restart. No ENGINE bump. No frozen-file edits.

**Don't-redo:** the 3-tab reframe is final - do NOT re-add Comp/Chart/Timeline/Insights (`TabStripTests::test_legacy_tab_ids_removed` guards). `_migrateLegacyTab` writeback is INTENTIONAL one-shot - do NOT remove. `_VALID_TABS` allowlist gates `_activateTab` against malformed values - do NOT relax. WPA is ABOVE Quick Review in AI Analysis (heuristic-insights ordering) - `PanelMountTests::test_ai_analysis_hosts_wpa_then_quick_review` pins. `.lm-wpa-wrap[hidden] { display: none }` is LOAD-BEARING - the `display: flex` declaration on the base rule would otherwise re-leak the head. Single shared Graph placeholder replaces 2 pre-S4 placeholders; `_setTimeline`'s `lm-tl-pending` lookup no-ops cleanly when the element is absent. The audit-in-parallel pattern (dispatch UI-audit subagent in background while implementation in-flight) is durable - matches operator's "edits and audits in parallel" instruction.

**Carries forward:** S5 (Replay page scaffold + Match-V5 timeline + league_record GPLv3 cleanroom reference) still operator-gated; the s220 reframe chain continues stage-by-stage with the per-page UI-audit ritual between sessions. Pre-existing `lm-build-pending` dead-id in `_setEmptyState` (s107-era) flagged by audit but NOT touched here (out of scope, no-op `getElementById` already returns null). Item 115 carries unchanged. Frozen-file grant NOT used this session.

---
# 2026-05-20 - s220 PGR S3 aggregator G score+MVP polish (1 commit 92c6a0f, pushed; non-engine; no frozen edits; no RC restart needed)

Stage S3 of the s220 aggregator-G-style Post Game Review reframe. Operator picked "S3 aggregator G score+MVP polish (Recommended)" from a 4-option fork (over UI-audit-first / S4 tabs reframe / S5 Replay scaffold). Three aggregator-G-pattern affordances added to the Last Match view, all sourcing from the existing `_rosterScores` 100-point heuristic in `web/js/panels/last_match.js` so the three numbers stay mutually consistent. No new backend, no schema change, no ENGINE bump.

**(1) Hero match-score block** - NEW `#lm-hero-score` mounted as the 6th column of `.lm-hero-identity` carrying a big numeric 0-100 + tier label (Bad/OK/Good/Excellent). NEW `_setHeroScore(m, enriched)` + `_scoreTier(score)` helpers; tier-tinted via `data-tier` attribute. Hidden until LCU enrichment lands. Thresholds 80/65/50 calibrated against the existing 100-point scale.

**(2) Per-side MVP/SVP cards** - NEW `#lm-tc-ally-mvp` + `#lm-tc-enemy-mvp` empty divs in each `.lm-tc-group` between the head and the list. Body painted by NEW `_renderMvpCard(cardId, top, sm)`: portrait + inline crown SVG (path `M2 14 L4 4 L8 9 L12 2 L16 9 L20 4 L22 14 Z`, NOT emoji per ASCII hard rule) + name + numeric score + tier label. `data-kind="mvp"` (winning-side top) = gold-tinted purple bg + gold left-border; `data-kind="svp"` (losing-side top) = accent-tinted. `rankSide` closure inside `_setTeamComp` extended to return `{meta, top}` so the card can pull the top-scoring row.

**(3) Per-row score chip** - the existing `.lm-tc-score` cell becomes a flex-column `<div>` stacking the MVP/SVP/#rank badge text over the integer 0-100 numeric score (was tooltip-only). Row grid columns 46 -> 56 (SR + augment-mode templates both bumped so ally/enemy align). Decimal + factors stay in the hover tooltip.

NEW `tests/test_last_match_score_card_dom.py` +26 grep-based DOM-contract tests mirror `test_draft_elo_panel_dom.py` pattern. Five classes: HeroScoreBlockTests (8) + MvpCardTests (8) + PerRowScoreChipTests (5) + EmptyStateResetTests (2) + AsciiHygieneTests (3). Tests catch divergent-scorer drift, missing data-tier variants, crown-SVG-vs-emoji choice, ASCII glyph regressions, and grid-template-columns shrink-back.

**Verified:** py_compile + ruff + ASCII clean across all 4 touched files (`web/index.html` + `web/js/panels/last_match.js` + `web/css/panels/last_match.css` + `tests/test_last_match_score_card_dom.py`); full RC suite **2335 passed / 67 subtests / 0 failed** (+26 over s113 2309 baseline); live-verified via Playwright @ `https://127.0.0.1:8888/#last-match` on operator's ARAM Vel'Koz 4/9/25 last match = hero **48 BAD** (red), ally SVP **bliv 64 OK** (accent), enemy MVP **GenieInTheLamp 77 GOOD** (green), all 10 per-row chips populated with correct badge+numeric stack.

ADR-008 asset-hash auto-bumps cover the JS/CSS edits; index.html picks up on the next page nav (no asset-hash needed for the parent HTML). No DS restart. No RC restart. No frozen-file edits.

**Don't-redo:** all three S3 affordances source from the SAME `_rosterScores` heuristic - do NOT introduce a divergent scorer; `MvpCardTests::test_js_mvp_card_uses_roster_scores` guards that drift. Crown is INLINE SVG NOT an emoji - the ASCII hard rule forbids Unicode glyphs (no U+1F451, no unicode stars); `MvpCardTests::test_js_mvp_card_emits_crown_svg` guards. Tier thresholds 80/65/50 are pinned in `HeroScoreBlockTests::test_js_score_tier_buckets` - if `_rosterScores` weights ever change, retune both alongside. Row grid 46 -> 56 also covers the 3-digit edge case (score=100); both `PerRowScoreChipTests::test_css_grid_row_widens_score_column` + `test_css_grid_aug_row_widens_score_column` pin the width. `rankSide` now returns `{meta, top}` (was just `meta`) - the closure stays local to `_setTeamComp`; downstream callers use `.meta` / `.top`. AsciiHygieneTests BAD dict is built via chr() so the test file stays ASCII-clean against its own scan - do NOT inline the bad glyphs as string literals.

**Carries forward:** S4 (tabs reframe Comp/Chart/Timeline/Insights -> AI Analysis/Graph/Build) + S5 (Replay page scaffold + Match-V5 timeline + league_record GPLv3 cleanroom reference) still operator-gated; the s220 reframe chain continues stage-by-stage with the per-page UI-audit ritual between sessions. Item 114 + 113 carries unchanged. Frozen-file grant NOT used this session.

---
# 2026-05-20 - fleet OAuth Max migration finished + Legion ON/OFF desktop shortcuts (1 commit cc9401b, pushed; no ENGINE bump; non-engine; no frozen edits)

User-driven scoped session. Closes the 2026-05-20 fleet OAuth migration that item 100 LANDED ASPIRATIONALLY but only Legion actually flipped. Identified Peer as the $ fluctuation source on api.anthropic.com via console User-ID fingerprint `182f0ecf...` matching Peer's machine; dispatched 2 parallel bridge tasks (one to Peer, one to Game-PC) for full 6-step OAuth migrations. Both peers reported back successfully. Peer: was process-scope sk-ant-api03, no OAuth credentials, no oauthAccount; operator ran `claude /login` mid-session, daemon patched env.pop, accountUuid 4eb3a75e matches Legion. Game-PC: TWO leak vectors found that s100 missed - HKLM Machine registry ANTHROPIC_API_KEY + `C:/RC-Agent/.claude/settings.local.json` env block; both removed, daemon patched, old pid 4792 -> 16416. Legion bridge daemons (`tools/legion_bridge_daemon.py` + `tools/gamepc_bridge_daemon.py`) were ALSO missing env.pop (item 100 only patched `bridge_watcher_actions.py`); patched both as defense-in-depth. NEW `tools/legion_on.ps1` + `tools/legion_off.ps1` + Desktop shortcuts "Legion ON.lnk"/"Legion OFF.lnk" replacing the old "Claude RC.lnk" (backed up at "Claude RC.lnk.bak"). Both scripts idempotent: ScheduledTask IgnoreNew refusal + DS port-listen guard + Claude Desktop singleton via shell:AppsFolder. NEW memory `feedback_oauth_flip_injection_vectors.md` documents all 3 non-obvious vectors for future OAuth flips. Wider RC suite not re-run (non-engine + non-route-module touch). py_compile + ruff + ASCII clean on both daemon patches.

**Don't-redo:** OAuth migration is DONE on all 3 nodes (Legion always was OAuth; Peer + Game-PC flipped this session). The 2026-05-21+ `mcp__anthropic-usage__query_usage` should drop to near-$0 once Max plan absorbs all 3 nodes for a full day. Item 100's claim "fleet-wide OAuth" was only 33% true; this session retroactively makes it 100% true. Do NOT re-investigate Peer or Game-PC OAuth status. The 4 files now carrying env.pop fleet-wide are: `tools/bridge_watcher.py` + `tools/bridge_watcher_actions.py` (item 100, Legion) + `tools/legion_bridge_daemon.py` + `tools/gamepc_bridge_daemon.py` (this session). Peer-side `C:\Peer-Bridge\peer_bridge_daemon.py` (sha256 63c5bbce post-patch) + Game-PC's `C:/RC-Agent/gamepc_bridge_daemon.py` (sha256 9ff5d8fd) also patched but those live OUTSIDE this repo - patching Legion's `tools/gamepc_bridge_daemon.py` is what keeps `RC ON` re-downloads from clobbering Game-PC's local patch on next boot. Legion's RC-BridgeDaemon (running pid 472) still holds pre-patch code in memory; next Legion OFF + ON cycle picks up the patch. Peer recommendation for self-PID-lock on legion_bridge_daemon deferred (Legion daemon already has `_lock_held`/`_set_lock` pattern at lines 188-194 - functionally equivalent).

**Carries forward:** (a) Operator pending on Peer: `schtasks /End /TN "\Peer-BridgeDaemon"; schtasks /Run /TN "\Peer-BridgeDaemon"` so the patched env.pop takes effect (currently running daemon holds pre-patch code). Optional: `taskkill /F /PID 19824 /T` cleans the :8899 web_dashboard orphans on Peer (vestigial from 2026-05-05 manual launch, zero Anthropic calls so no billing impact). (b) Next session is **s220 aggregator-G-style Post Game Review reframe** - operator-decided scope: single-match richer layout, the 0-100 score is an RC heuristic over enriched stats with NO Claude/Riot dependency; staged S2-S5, each its own session plus the per-page UI-audit ritual. (c) All item 113 carries unchanged (DS item-AH lane, aram_tenacity_mult consumer, STAT_GRANT_CALC_KEYS seam pending Arena S2 26.09, post-game-phases live-game smoke, ruff/type-hint pass). (d) Peer bridge_watcher zombie still pending (separate from daemon; daemon covers task autofire so non-blocking).

---
# 2026-05-20 - 3-agent parallel BACKLOG NOW drain wave 2 (6 commits + 3 merges; ENGINE 1.22.0 -> 1.23.0; no frozen edits; DS + RC restarted)

Operator "start what is left in backlog and roadmap in parallel". 3 worktree agents concurrent on disjoint NOW-lane items from item 109 carry-forwards + the aramAH/Tenacity consumption gap.

**Agent A `4e5d818` feat(ds) - aramAbilityHaste + aramTenacity engine CONSUMPTION (ENGINE 1.22.0 -> 1.23.0).** NEW `_effective_ability_cd(base_cd, total_haste) = base_cd / (1 + total_haste/100)` + `_total_ability_haste(scaled_stats, mode, base_ah=0.0)` helpers in `agents/daemon_slayer/ability_dps.py:800-861`. Applied per-spell loop line 1336. `AbilitySpellDps` gains `base_cooldown` + `total_ability_haste`; `AbilityDpsResult` gains `aram_ability_haste` + `aram_tenacity_mult` (forward-marker for future EHP enemy-CC). `cooldown` field shifted to POST-haste effective (SR + zero-aramAH ARAM identity preserves 42 existing tests). +26 tests + 13 ENGINE pin syncs. `base_ah` parameter is a seam for future item-AH lane (currently 0; awaits `_effects_types.ItemEffect.ability_haste_flat` field).

**Agent B `e0eabb7` feat(champ-select) - HURTS-THEM/HELPS-US ban-suggest frontend toggle.** Closes item 109 carry-forward (a). NEW `web/js/panels/ban_suggest_toggle.js` (240 LOC) + CSS (187 LOC) + 25 snapshot DOM tests. Wires to `dashboard/routes_ban_suggest.py` (item 109 `6e7b7e5` backend). Mode persists `localStorage[rc-cs-bansugg-mode]` default `"hurts_them"`; `data-bs-active` attr-driven CSS flip (red HURTS / green HELPS); per-row active-mode rating + other-mode muted + `n=solo/pair` sample-density chip. Reuses cached `/api/champ-select/ban-suggestions` for portrait metadata. Integration via `_csvRenderBanSuggestToggle()` in `champ_select.js`.

**Agent C `ea9b88f` feat(draft-elo) - per-row contribution hover strip.** Closes item 109 carry-forward (b). NEW `Contribution` dataclass + `top_contributions()` sibling aggregator in `core/draft_elo.py:141-238` (NOT inside `team_score` - pure sibling). Route gained `?breakdown=1` adding `top_contributions: [{kind, a, b, delta, n}, ...]` (max 3); cache stores full + strips at serve. Frontend uses PURE CSS `:hover` (zero JS handlers, zero click-to-pin, `pointer-events: none` on overlay). `HoverOnlyContractTests` guard fails if future code adds `addEventListener('click'`, `.onclick`, or `pinned` class. +31 tests. Live `GET /api/draft-elo?ally=22,64,55,89,12&enemy=42,67,69,33,99&breakdown=1` returned top-3: enemy-pair (42,99) +240.82 n=3 / matchup (22,67) +240.82 n=3 / ally-pair (22,89) +190.85 n=2.

**Merges `14c14ef` / `4d50e92` / `89e645e`:** no conflicts (3 agents touched disjoint files). DS **2803 passed** (+26); RC **2309 passed** (+56 over 2253). py_compile + ruff clean; ASCII drift only on PRE-EXISTING carryover (arrows/multiplication/ellipsis/box-drawing in `agents/daemon_slayer/__init__.py` / `ability_dps.py` / `web/js/panels/champ_select.js` / `web/index.html`); new files clean. DS :8893 restarted (pid 4800 -> new); `test_live_three_profiles` flipped pass post-restart. RC :8888 restarted (Agent C edited `dashboard/routes_draft_elo.py` route module); pid=7692 last_reload_ok=True. Worktrees + 4 merged branches cleaned up.

**Don't-redo:** all 3 wave 2 items SHIPPED + live-verified; `cooldown` field semantics now POST-haste effective cd (back-compat via identity at total_haste=0); `aram_tenacity_mult` is FORWARD-MARKER only (do NOT pretend it's consumed today); `base_ah` parameter is a SEAM (currently 0 - awaits item-AH lane); ban-suggest toggle persists locally per-machine via localStorage (NOT server-side); per-row hover is PURE CSS - do NOT relax `HoverOnlyContractTests` without operator approval; `top_contributions` cache strip-at-serve is deliberate (cache hit rate unchanged).

**Carries forward:** (a) DS item-level ability_haste lane queued (touches `_effects_types.py` + `_effects_data.py` + extractor pass). (b) `aram_tenacity_mult` consumer (future EHP enemy-CC model in `agents/daemon_slayer/ehp.py` or successor). (c) `STAT_GRANT_CALC_KEYS` displacement seam STILL EMPTY (Arena S2 26.09 trigger - item 112 unchanged). (d) post-game-phases live-game smoke pending (item 112 unchanged). (e) item 110 Peer bridge_watcher zombie + Game-PC vision triad SKIPPED + RC-DDragonMirrorRefresh 5/21 03:30 cron unchanged. (f) Arena S2 patch 26.09 schema break ahead. (g) ruff/type-hint pass STILL operator-gated. (h) frozen-file grant NOT used this run - 3 agents routed entirely around frozen list.

---
# 2026-05-20 - 3-agent parallel BACKLOG NOW lane drain (4 commits; ENGINE 1.21.0 -> 1.22.0; no frozen edits; DS restart)

Operator-driven "start what is next on backlog in parallel". 3 worktree agents dispatched concurrent on 3 independent NOW-lane items, merged + pushed + DS restarted.

**Agent A `c965167` + `583a3bc` feat(ds) - cdragon mFormulaParts typed-part formula evaluator (ENGINE 1.21.0 -> 1.22.0).** NEW `agents/daemon_slayer/augment_formula_eval.py` interprets the 4 typed cdragon formula parts (`NamedDataValueCalculationPart` / `StatByNamedDataValueCalculationPart` / `StatByCoefficientCalculationPart` / `NumberCalculationPart`) wrapped by optional `mMultiplier`, composes via sum-of-parts. Out-of-scope shapes (`ByCharLevelInterpolation` etc.) return 0.0 via unknown-shape sentinel - never raise. Wired into `agents/daemon_slayer/augments.py:compute_augment_stats` as PREFERRED path with `_AUGMENT_STAT_OVERLAYS` registry fallback. `STAT_GRANT_CALC_KEYS` displacement seam is INTENTIONALLY EMPTY at cdragon 16.10.1 (all 82 unique calc keys are damage/heal/shield/conversion, none are stat grants) - production behavior byte-identical today. +47 tests; +13 ENGINE pin syncs.

**Agent B `a250416` feat(pgr) - WPA phases-that-mattered for Post Game Review S2.** NEW `core/post_game_score.py` pure-Python LR via batch gradient descent (no sklearn/numpy dep) + `data/post_game_wpa_model.json` trained checkpoint (200 most-recent SR matches, 800 samples, weights gold_diff +1.32 / xp_diff +0.65) + NEW `dashboard/routes_post_game_wpa.py` GET `/api/post-game-wpa?match_id=<id>` + NEW `web/js/panels/post_game_phases.js` stacked card list mounted in last-match view + dispatch registration. +68 tests. Live `GET /api/post-game-wpa?match_id=NA1_5439050124` -> ok=true event_count=86 elapsed_ms=2 top-3 CHAMPION_KILL phases t=60/65/73s WPA +2.3% each.

**Agent C `e0eec7e` feat(cooldowns) - wire Hextech Drake count from Live Client events.** Extended `dashboard/_state_cooldowns.py` with NEW `_hextech_drakes_by_team()` helper that watches `gameData.events.Events` for `EventName="DragonKill"` + `DragonType="Hextech"`, maps `KillerName` to team via `allPlayers[].summonerName -> .team` lookup, tallies per team. Per-participant `hextech_drakes` field wired into the participant build loop - feeds the s110 `58d1e87` haste-formula compute (`HEXTECH_DRAKE_AH_PER_STACK=5`). +10 tests. Closes the s110 carry-forward (c).

**Merge `21657eb`:** no conflicts (3 agents touched disjoint files). DS suite 2777 passed (+47); wider RC 2253 passed (+86). DS :8893 restarted (taskkill + relaunch start_daemon_slayer.py per `reference_ds_server_not_supervisor_watched`); `/health` -> engine_version=1.22.0.

**Don't-redo:** all 3 BACKLOG NOW items SHIPPED; cdragon formula evaluator's empty seam INTENTIONAL; pure-Python LR (no numpy dep) on purpose; the new `summs.summoner_haste` / `ult.ability_haste` / `hextech_drakes` keys are forward-compatible additions. **Carries forward:** seam populates when Arena S2 patch 26.09 schema break lands; aramAH/Tenacity engine consumption still queued for DS cooldown math (NOT PGR); WPA model retraining cadence operator-gated; post-game-phases live-game smoke pending; bridge/vision/DDragon items 110 carryforward unchanged. Frozen-file grant NOT used - 3 agents routed entirely around the frozen list.

---
# 2026-05-20 - fleet bridge daemon symmetry + autonomous cadence verified (3 commits; non-engine; 1 frozen edit operator-approved)

User-driven scoped session. **3 commits `f40e8fb`..`0e7cb8e`**, all pushed. No ENGINE bump; no DS restart needed.

**`f40e8fb` fix(gamepc) - shortcut Claude Desktop, not CLI.** `tools/gamepc_boot.ps1` section 6a was resolving `AppData\Roaming\Claude\claude-code\<ver>\claude.exe` which IS the Claude Code CLI native installer (the comment claiming "Desktop app" was wrong). Repointed to Squirrel-installed Claude Desktop at `AppData\Local\AnthropicClaude\claude.exe` (Product=Claude v1.8089.1). Squirrel auto-resolves newest app-<ver>\ subdir at launch time. CLI fallback (sec 6c) removed entirely per operator decision. Also unset User-level + **Machine-level** `ANTHROPIC_API_KEY` on Game-PC (was at Machine scope) - bridge_watcher subprocess already env.pop's per fleet item 100 so OAuth path unaffected. Mirrors Legion item 110 (Claude RC.lnk repointed to chat app).

**`cb74e00` feat(bridge) - legion_bridge_daemon + frozen push-notif fix + honest bridge gauge naming.** Closes fleet daemon symmetry gap: gamepc + peer had `gamepc_bridge_daemon.py` + `peer_bridge_daemon.py` for months, Legion had NEITHER. Without it, kind=task envelopes targeted at legion that didn't match the narrow `auto_read_patterns` / `auto_ops_verbs` whitelist (e.g. RC-VerifyBridgeRoundtrip-Once's "Reply with hostname/pid/ts" prompt) classified as escalate. Then push-notif path tried `claude` bare which subprocess.run can't resolve to `claude.cmd` (npm shim) on Windows -> WinError 2 silently. Tasks sat unhandled. **NEW** `tools/legion_bridge_daemon.py` mirrors gamepc/peer pattern (TARGET=legion, 30s idle poll / 10s post-work poll, lock+health under `ops/runtime/`, log under `logs/`). **NEW** `ops/install_RC_LegionBridgeDaemon.ps1` registers `RC-BridgeDaemon` (AtLogOn Highest, restart 3/1min, ETL=0). **Frozen edit** (operator-approved): `tools/bridge_watcher.py:256` push-notif spawn now uses `_actions._resolve_claude_executable()` instead of bare `"claude"` - fixes fleet-wide push-notif spawn failure. **Bridge field split** `dashboard/routes_state.py`: `bridge.age_s` -> `bridge.gamepc_result_age_s` (honest naming - the gauge ONLY tracked kind=result + source=gamepc, never generic bridge); ADDED `bridge.legion_daemon` sub-block exposing the new daemon's health (status, pid, invocations_since_boot, last_check_age_s); `web/js/main.js:6229,6232` consumer renamed.

**`0e7cb8e` fix(bridge-daemons) - CREATE_NO_WINDOW on claude --print spawn.** Operator surfaced conhost console window flashing at each cadence interval on Peer (and same on Game-PC). Root cause: pythonw.exe parent + `.cmd` npm shim child -> Windows must spawn cmd.exe to host batch script, conhost window appears. STARTUPINFO alone can't suppress for `.cmd`. Fix: pass `creationflags=subprocess.CREATE_NO_WINDOW` on win32 to all 3 daemon's `subprocess.run` call. Applied to all 3 daemons for fleet symmetry. Legion daemon restarted in place; gamepc refreshed via gamepc MCP (curl `/agent/gamepc_bridge_daemon.py` + taskkill + Start-ScheduledTask); Peer refreshed by operator via the one-liner re-pull.

**Peer bridge daemon was NEVER INSTALLED on Peer.** Diagnostic surfaced this: `peer_bridge_daemon.py` not in any directory on Peer C: drive. The rc_facts startup line "peer bridge daemon: watcher=alive queue=0 age=5s" was just based on bridge_watcher heartbeat publisher, NOT a real daemon process. Operator pulled from Legion's `/agent/` allowlist (already in `_AGENT_ALLOWED`) to `C:\Peer-Bridge\peer_bridge_daemon.py`; registered scheduled task `Peer-BridgeDaemon` (AtLogOn user=$env:USERNAME, Highest, restart 3/1min, ETL=0). Live-verified: pid 24772 -> 29720 (after CREATE_NO_WINDOW pull). Peer is a separate machine (not RC repo); the daemon lives outside any repo clone.

**End-to-end verification:** 4 autonomous test rounds total:
- Round 1 (pre-daemon): RC-VerifyBridgeRoundtrip-Once exited 0xC000013A; task sat unhandled; I /process-bridge-tasks'd manually.
- Round 2 (post-daemon): RC-VerifyBridgeRoundtrip-Once LastResult=0x00000000, PASS latency 44.35s, legion daemon picked up + invoked claude --print autonomously.
- Round 3 (autonomous-only worded): gamepc replied in 2m26s; Peer did NOT reply (daemon dead).
- Round 4 (post-install): both gamepc + peer replied autonomously. Hash-verify round: gamepc sha256=18196dfbecff1539, peer sha256=f075f314dd6a7e0c, both MATCH Legion repo source of truth. Full fleet symmetry proven.

**Don't-redo:** (1) gamepc shortcut points at Squirrel Claude Desktop directly - do NOT repoint to `claude-code\<ver>\claude.exe` (that's the CLI). (2) Legion now has its own bridge daemon - do NOT pitch the `/loop /process-bridge-tasks` pattern. (3) `bridge.age_s` field is GONE from `/api/health/all`; consumers MUST use `bridge.gamepc_result_age_s`. (4) Peer daemon installed at `C:\Peer-Bridge\peer_bridge_daemon.py` (no repo clone on Peer); when patching the daemon source on Legion, Peer needs `/agent/` re-pull (the one-liner pattern is durable). (5) `bridge_watcher.py:256` frozen edit is SHIPPED (uses `_actions._resolve_claude_executable()`); do NOT revert to bare "claude". (6) ANTHROPIC_API_KEY env var is unset at Machine scope on Game-PC; CLI subprocess invocations now use OAuth solely there.

**Carries forward:** (a) **Peer bridge_watcher zombie** - separate from the daemon. The watcher process (pid 11832, `bridge_watcher.py --node peer`) is "alive" but its internal `last_poll_at` is frozen at 2026-05-06 (14 days stale). Heartbeat publisher is fresh (received_at 9s ago) but it's publishing a stale snapshot of the watcher's own state. Daemon covers task autofire so this is non-blocking, but the watcher poll-loop hang is worth a separate look on Peer when convenient. (b) Game-PC vision screen-agent triad still SKIPPED per gamepc_boot.ps1 sec 4 isolation test 2026-05-16 (Vanguard BSOD investigation) - ingame OCR/Sonnet escalation paths inert; revert pending. (c) RC-DDragonMirrorRefresh next 5/21 03:30 cron is the live test of the `943d2e0` retry-with-backoff fix from earlier today (item 110); pre-this-session it had LastResult=2.
