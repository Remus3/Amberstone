# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-05-25 (evening) - item 187 SHIPPED: parallel 7-slice drain - DD Defy heal-on-takedown ENGINE 1.57.0 + U+2500 candidate sweep + Calibrations audit + cc_conditional wave 20+ schema-lift recommendation + Cherry augment scaffold + Bridge Watcher audit + 101.qq.com capture scope (4 commits + 2 merges `74e1c7f` `31aac59` `77e6b41` `f60c91a` pushed origin/main `c138fe3..f60c91a`; ENGINE 1.56.0 -> 1.57.0; DS :8893 restarted pid 13880 -> serves 1.57.0; RC :8888 unchanged pid 10352 mode=client - DS engine + drift guard tests + docs only)

Operator "in parallel" 7 slices selected from operator-gated decision-owed lane. 39th consecutive run using orchestrator-merge pattern (items 134-187). 7 worktree/investigative agents dispatched concurrent. Pre-flight: 0 open PRs; 2 stale remote branches (worktree-agent-a9421dd8e35427f24 + worktree-agent-ad0f8ca358904c2a3) deleted via `git push origin --delete` (fully merged into main `c138fe3`); CI 10/10 green; HEAD = item 186 `c138fe3`; mode_key=client (between games).

**Slice A `31aac59` (merge `f60c91a` ort 0 conflicts 37 files +812 / -60) feat(ds) ENGINE 1.57.0 - Death's Dance Defy heal-on-takedown shipped:** Closes ENGINE 1.28.0 Phase 6 deliberate omission carried forward through items 129/153/156/157/158+ as "DD Defy heal STILL deferred". Schema lift ADDITIVE: NEW `ItemHeal.takedown_gated: bool = False` field at `agents/daemon_slayer/_effects_types.py:355` (convention-agnostic at dataclass layer; consumer-side gating in `_collect_heals`). NEW `_TAKEDOWN_RATE_PER_FIGHT = 0.5` operator-tunable module constant at `agents/daemon_slayer/ehp.py:246` (mirrors `_MISSING_HP_SHARE_FOR_HEALS = 0.5` Phase 6.5 + `_CC_EFFECTIVENESS_FACTOR = 0.5` ENGINE 1.33.0 precedent). `_collect_heals` gains `takedown_rate` kwarg, multiplies resolved magnitude by `max(0.0, takedown_rate)` for entries with `takedown_gated=True`. ItemEffect promotions (Meraki 16.10.1 verified): SR 6333 `ItemHeal(bonus_ad_scaling=0.75, takedown_gated=True)` per Meraki Defy "heals you for 75% bonus AD over 2 seconds" - **agent caught brief error: brief said 15% max HP, Meraki authoritative says 75% bonus AD**; Arena 226333 mode-mirror with identical schema; both promoted from `defensive_only=True` -> heal contributor. ENGINE_VERSION 1.56.0 -> 1.57.0 with full changelog block + bulk pin sync across 32 DS test files. **+40 tests** in NEW `agents/daemon_slayer/tests/test_dd_defy_heal_on_takedown.py` across 9 classes. test_ehp_heal_phase6.py::DeathsDanceDeferredTests flipped to post-ship state pins. test_effects_expansion.py EXPECTED defensive_only sets dropped 6333 + 226333. test_cc_conditional_wave19.py 5 historical 1.56.0 markers restored (bulk regex incorrectly bumped wave 19 anchors). Sample math (Aatrox L11, base_ad=68, bonus_ad=60, takedown_rate=0.5): per-trigger heal = 0.75 * 60 = 45 hp; takedown-gated * 0.5 = 22.5 hp -> blended_ehp gains ~22 hp via top-of-damage-stack absorption. Default 1.56.0 byte-identical EHP contract holds for every build without DD equipped.

**Slice B `74e1c7f` (merge `77e6b41` ort 0 conflicts 11 files +304 / -62) chore(housekeeping) item-187 U+2500 box-drawing sweep on 9 candidate files:** Top 20 files by U+2500 count classified as 19 INTENTIONAL (live source/test/tool section dividers) + 1 CANDIDATE; agent expanded beyond top 20 to find 8 more candidates (7x `_archive/2026-05-01-audit/` dead Tk code + web/legacy_index.html + ops/rc_config.json). 9 candidate files swept -2874 U+2500 -> 0: `_archive/2026-05-01-audit/tft/comp_control.py` 886 + `_archive/2026-05-01-audit/ui/client_panel.py` 576 + `_archive/2026-05-01-audit/modes/arena_overlay.py` 330 + `web/legacy_index.html` 349 + `ops/rc_config.json` 276 (visual padding in `_*` underscore-prefixed string values only; no consumer code parses these) + `_archive/2026-05-01-audit/ui/game_right_bot.py` 185 + `_archive/2026-05-01-audit/tft/tft_overlay.py` 116 + `_archive/2026-05-01-audit/core/tk_ai_bar_proxy.py` 97 + `_archive/2026-05-01-audit/ui/base.py` 59. NEW `tests/test_u2500_candidate_sweep.py` (~229 LOC / 13 tests across 12 functions). `tests/test_u2500_hygiene.py` `_ASSERTED_CLEAN` frozenset grew 2 -> 11. Repo-wide pre/post: 52,420 -> 49,546 U+2500 / 203 -> 194 files (-2,874 / -9 files exact). 10 INTENTIONAL files documented in test frozenset as durable skip list. 89 passed (6 + 13 + 70 phase8); ruff clean; json.load PASS on rc_config.json (27 keys); py_compile clean on swept `.py` files.

**Slice C audit-only no-commit (calibrations audit):** 4 surfaces audited. 13 condition tag midpoints (cc_conditional.py:286-300): all operator-decision-only; 3 forward-marker tags (COND_FRENZY_STATE / COND_RANGE_GATED / COND_TRAVERSE) seeded waves 7+17. 67 per-entry probability values: **10 entries flagged with >0.1 drift from tag midpoint** all carry operator rationales (Karma:W -0.1 tether persistence / Viktor:W -0.1 zone stun 3 stacks ~1.5s / Xayah:E -0.1 3+ feather threshold / Kennen:E -0.1 Mark of Storm combo / JarvanIV:E +0.2 EQ flag combo / Fiora:W -0.1 parry timing / Yuumi:Q -0.1 conservative / Evelynn:W -0.1 / Hwei:E -0.1 / Neeko:E -0.1 / Sylas:E -0.1). _MISSING_HP_SHARE_FOR_HEALS = 0.5 (ehp.py:209-220) anchor: Sundered Sky 6610 mid-fight HP convention; operator-tunable. _CC_EFFECTIVENESS_FACTOR = 0.5 (ehp.py:223-242) anchor: ENGINE 1.33.0 conservative discount for QSS/dodge/cleanse/gaps; operator-tunable. No data-driven delta proposals; existing per-entry override machinery (`data/cc_conditional_calibration.json` + `_PER_ENTRY_PROBABILITY_OVERRIDES`) ready for operator calibration from live-game data without schema change.

**Slice D research-only no-commit (cc_conditional wave 20+ Meraki schema field):** RECOMMENDED `notes` field per spell form at `tools/daemon_slayer_abilities_extract.py:453-560` _build_form function. Pure-additive parallel to cast_time (wave 14) + effects_descriptions (wave 9) + parent_resource (wave 19). Unblocks 3 candidates: Kindred E Mounting Dread (third-stack pounce stun COND_NTH_HIT), Diana P Moonsilver Blade (form-empowered moonstone passive COND_FRENZY_STATE), Vayne P Night Hunter (third-strike empowered stun COND_NTH_HIT + COND_FRENZY_STATE overlap). All 3 Meraki-verifiable via `notes` text; require breaking the per-form text into segments distinguishing unconditional status-grants from conditional empowered-attack CC. Operator-gated for next session.

**Slice E research-only no-commit (set_augment_intent Cherry scaffold):** Endpoint UNCERTAIN: PATCH `/lol-cherry-game-intra-event/v1/augment-select` (best-guess from LCU namespace convention + KebsCS pattern; requires live Arena capture to confirm). Agent handler scaffold ready at tools/gamepc_lcu_agent.py:1179-1194 (replace existing no-op stub). Dashboard wiring 90% DONE: `"set_augment_intent"` already in `_LCU_ALLOWED_CMDS` at dashboard/routes_loadout.py:57 (item 166 wiring). Live verification: operator in queue 1750 (CHERRY) champ-select + Chrome DevTools Network capture of session.actions[] containing augment-type action.

**Slice F audit-only no-commit (Bridge Watcher acceptance):** Ledger `ops/runtime/bridge_action_history.db` shows 2/50 samples (4% of acceptance threshold), both auto-ok lane from early Phase 4 tests 2026-05-03, 100% auto-ok rate. 0 samples since 2026-05-03. Watcher pid 6204 alive cadence=active queue=0/auto_ok=0/err=0/suppressed=0 since boot. ETA to 50 samples: indeterminate at current zero-cadence; needs live task volume OR integration test seeding to populate.

**Slice G research-only no-commit (101.qq.com CDN capture scope):** Primary target hero-rank-double duo-synergy JSON at `https://game.gtimg.cn/images/lol/act/.../hero-rank-double-*.json`. Capture method: operator at Game-PC + Chrome DevTools Network tab + save cURL command + JSON payload. Storage `data/capture_101qq_<YYYYMMDD>/{hero_rank_double_payload.json, network_requests.txt, CAPTURE_METADATA.json}`. Diff script template `tools/compare_101qq_vs_ddragon.py` (pseudocode pending URL capture). Blocker risk: geo-blocking from Legion/Tailscale; needs operator at Game-PC. Secondary: champions.json + items.json + augments.json exploratory if time permits.

**Docs sync:** `docs/DAEMON_SLAYER.md` L5+L32 ENGINE 1.56.0 -> 1.57.0 + 4671 -> 4712 tests. `README.md` L46 4,671 -> 4,712 tests. `BRIEF.md` L20 ENGINE_VERSION 1.56.0 -> 1.57.0 + L26 4,671 -> 4,712 tests. `docs/ARCHITECTURE.md` L161 ENGINE_VERSION 1.56.0 -> 1.57.0 + 4671 -> 4712. `ROADMAP.md` L165 Fleet status DS row ENGINE 1.56.0 -> 1.57.0 + 4671 -> 4712 tests.

**Merge order:** Slice B (U+2500 sweep, no engine) merged into main FIRST as `77e6b41`; Slice A (DD Defy ENGINE 1.57.0) merged into main SECOND as `f60c91a`. 0 merge conflicts (disjoint files). Slice C+D+E+F+G produced no commits (audit/research only). Docs sync edits included in the merge graph via the agents themselves (Slice A bulk-updated 32 DS test files including its own ENGINE pin).

**DS restart:** `taskkill /F /PID 13880` (DS server listener pid via netstat -ano -p TCP | grep 8893) + `schtasks /Run /TN RC-DaemonSlayer` per [[reference_ds_server_not_supervisor_watched]] -> `/health` engine_version=1.57.0 patch=16.10.1 champions=172 items=705. RC :8888 unchanged (no route module edits; pid 10352 alive=True last_reload_ok=True mode_key=client).

**Don't-redo:**
- DD Defy heal-on-takedown ADDITIVE schema lift via `ItemHeal.takedown_gated: bool = False` is the canonical pattern for future "post-takedown" / "post-kill" / "post-assist" item effects (e.g. Hullbreaker stacks-on-takedown if Riot ever ships one). The `_TAKEDOWN_RATE_PER_FIGHT = 0.5` constant is the operator-tunable consumer-side gate; mirrors `_MISSING_HP_SHARE_FOR_HEALS` + `_CC_EFFECTIVENESS_FACTOR` precedent.
- Meraki authoritative source-of-truth: DD Defy heals 75% bonus AD over 2s (NOT 15% max HP). Future item-effect work MUST verify the brief's mechanic claims against live Meraki bulk endpoint before coding.
- `tests/test_u2500_hygiene.py` `_ASSERTED_CLEAN` frozenset is now 11 entries (was 2); extend it when sweeping a new file; do NOT remove entries (each removal opens a regression vector).
- `ops/rc_config.json` U+2500 sweep was safe because all swept values are `_*` underscore-prefixed visual separator string values (no consumer code parses them). Future config-file U+2500 sweeps require the same pattern verification.
- The 7-slice parallel headless drain produced 1 commit-bearing engine slice (Slice A DD Defy) + 1 commit-bearing housekeeping slice (Slice B U+2500) + 5 audit/research no-commit slices. The orchestrator-merge pattern at 39 consecutive runs is durable; mixing commit-bearing + audit-only slices in one drain is standard.
- The cc_conditional wave 20+ recommendation is `notes` field schema lift unblocks 3 candidates (Kindred E + Diana P + Vayne P); operator-gated for next session.
- Cherry augment endpoint discovery requires live Arena queue 1750 session - cannot scaffold without operator.

**Carries forward:**
(a) Item 186 carries ALL unchanged EXCEPT (c) DD Defy heal-on-takedown NO LONGER deferred (DONE this session); (l) U+2500 candidate sweep proposal NO LONGER open (DONE this session).
(b) NEW: `_TAKEDOWN_RATE_PER_FIGHT = 0.5` calibration value operator-gated for live-game adjustment.
(c) NEW: cc_conditional wave 20 `notes` Meraki schema lift recommended by Slice D research; operator-gated for next session (unblocks Kindred E + Diana P + Vayne P).
(d) Live UI captures STILL OWED for page #3 Replay + pages #11/12/13 Active Match SR/ARAM/Arena (live-gated).
(e) Bridge Watcher acceptance STILL time-gated (2/50 samples, 0 since 2026-05-03).
(f) Cherry augment endpoint live-Arena-gated for final wire (scaffold ready).
(g) 101.qq.com CDN capture STILL operator-at-Game-PC-gated (scope doc ready).
(h) Calibrations STILL operator-gated; existing override JSON machinery ready.
(i) Legion 1-PC consolidation STILL operator-gated.
(j) Auto-ops verb expansion STILL Phase-3 95%-gated.
(k) Frozen-file grant NOT used this session.
(l) DS engine cumulative test count now 4712 / cumulative subtests 1774.

---

# 2026-05-25 (late afternoon) - item 186 SHIPPED: dead-endpoint cleanup (11 routes) + dedup duplicate-fetch cache + housekeeping wave 27 CLEAN + Slice E U+2500 stale-carry confirmed + Slice G cc_conditional wave 20 saturation (2 merges + 1 RC restart pushed origin/main `9aea56a..077ee64`; non-engine; non-frozen; no DS engine bump; no DS restart; RC :8888 restarted via restart_trigger.txt pid 12612 -> 10352 for route module reload)

Operator-triggered parallel headless drain on operator-gated decision-owed lane: dead-endpoint cleanup vet + implement / dedup duplicate-fetch cache / U+2500 audit / cc_conditional wave 20 REJECT re-audit / housekeeping triple / 101.qq.com Game-PC capture / set_augment_intent Cherry discovery / Bridge Watcher acceptance / Auto-ops verb expansion + lanes. 38th consecutive run using orchestrator-merge pattern (items 134-186). 5 worktree/investigative agents dispatched concurrent (Slice C dead-endpoint + Slice D dedup + Slice E U+2500 + Slice G cc_conditional + Slice J housekeeping). Pre-flight: 0 open PRs; 0 stale remote branches; CI 5/5 green; HEAD = item 185 `9aea56a`; mode_key=client.

**Slice C `4cfd0be` (merge `077ee64` ort 0 conflicts 7 files +229 / -547) chore(dashboard) item-186 dead-endpoint cleanup - 11 routes removed + 11 keepers + drift guard:**
- Item 184 Phase 6 carry (h). 15 dead-endpoint candidates surfaced; 11 truly-dead deleted; 4 had real callers and were kept (sr-draft/apply + post-game-rubric + post-game-wpa + decisions/respond_active kept after caller-verification per item 184 risk-control note).
- Routes removed (11): /api/aram-analyze + /api/experimental/adapt + /api/experimental/get + /api/experimental/mark + /api/logs + /api/recommend-champ + /api/replay-coach (routes_coach.py); /api/ocr-crop + /api/reload-regions + /api/validate-ocr (routes_diag.py); /api/sr-draft/profile (routes_sr_draft.py).
- Keepers verified by real-caller grep (11): /api/bridge/cadence (operator /sleep+/wake slash commands) / /api/bridge/messages (peer_bridge_daemon + bridge_watcher) / /api/bridge/status (bridge_mcp_server) / /api/decisions/respond_active (gamepc_keybind_listener) / /api/health/peer (supervisor + bridge_watcher_health_publisher + main.js) / /api/last-match/ingest (gamepc_lcu_agent) / /api/ocr (calibrate_vision) / /api/replay/match (dev.js + index.html) / /api/sr-draft/apply (phase8 test + live LCU push) / /api/team-context (dispatch + tests + LCU agent) / /api/bridge/pending (bridge_pending panel).
- Risk-control vetting per item 184 carry (h): aram_analyze (0 callers, DELETED safely); sr-draft/profile (0 callers, DELETED); sr-draft/apply + post-game-rubric + post-game-wpa (real callers, KEPT). Risk-check grep against ROADMAP.md + BACKLOG.md OPEN items: 0 references to the 11 deleted routes.
- NEW `tests/test_dead_endpoint_cleanup_item186.py` (~214 LOC / 4 drift guard tests) pins via AST walk: deleted routes cannot reappear in GET_ROUTES/POST_ROUTES tables + deleted handler symbols cannot be re-defined / re-imported. Failures CI-blocking.
- Phase 8 smoke tests dropped 5 (test_sr_draft_profile_stub.py::TestRouteHandler (3) + test_sr_user_builds.py::TestRouteMergeInvariant (2) - their routes are gone); +4 new drift guard tests = net +4 unique passing test cases. Pre-existing test failures (16 in ban_suggest + draft_elo + target_state_caller, all sqlite or live-HTTP unrelated) unchanged baseline.
- RC restart REQUIRED for route table reload (immutable module-level GET/POST_ROUTES); restart_trigger.txt -> pid 12612 -> 10352 alive=True reload_ok=True mode_key=client.
- Live HTTP probe verification: 6/6 deleted routes confirmed HTTP 404 (correct); 3/3 kept routes confirmed handler-hit (POST /api/sr-draft/apply = 400 bad body + POST /api/last-match/ingest = 400 bad body + POST /api/decisions/respond_active = 404 "no pending decision" handler response).

**Slice D `d570aa4` (merge `7f17625` ort 0 conflicts 6 files +293 / -5) feat(web) item-186 dedup duplicate-fetch cache - /api/loadout/list + /api/decisions ~50-150ms saved per consolidated fetch:**
- Item 184 Phase 6 carry (j) LOW priority. /api/loadout/list + /api/decisions each hit by 2 panel modules independently per page load.
- NEW `web/js/lib/dedup_fetch.js` (~93 LOC) module-level Map<urlKey, inflightPromise> dedup primitive with 100ms grace TTL + response.clone() for multi-consumer body reads + immediate evict-on-reject (matches item 171 trailing-space precedent for query-string-aware cache keys).
- Wired 4 call sites: web/js/panels/bridge_pending.js (+5/-1) + web/js/panels/trigger_pill.js (+4/-1) for /api/decisions; web/js/panels/champ_select.js (+5/-1) + web/js/panels/item_build.js (+9/-2) for /api/loadout/list (2 sites in item_build).
- NEW `tests/test_loadout_list_dedup.py` (~170 LOC / 13 tests across 4 classes): DedupFetchLibTests + WiredSitesGrepTests + NoRawFetchRegressionTests + AsciiHygieneTests.
- Expected savings: /api/decisions trigger_pill 500ms cadence vs bridge_pending 20s cadence = ~1 saved roundtrip per coincident tick (~50-100ms server-side per dedup; 500ms grace window covers typical 0-100ms overlap). /api/loadout/list 2 panels both fire on central-pane render; at item 184 baseline 0.684/s pre-suppression, render-storm bursts (panel mount + state tick within same frame) coalesce into 1 request via 100ms TTL.
- ADR-008 asset-hash auto-serves new JS; no RC restart needed for the dedup work itself (Slice C restart covered both).

**Slice E read-only no-commit (U+2500 residue audit beyond rc_supervisor + rc_self_monitor):**
- Carry-forward statement in items 178-185 ("542 residual U+2500 chars STILL operator-gated separate sweep, NOT trivial - intentional docstring tree-drawing in rc_supervisor 58 + rc_self_monitor 484") is STALE.
- Live grep: ops/rc_supervisor.py = 0 U+2500; ops/rc_self_monitor.py = 0 U+2500. Both files already swept by item 176 (`8611ff3` 2026-05-24 frozen-file grant `tools/strip_u2500.py --allow-frozen`).
- Repo-wide audit: 51,287 U+2500 across 197 files (excluding .git/ _archive/ logs/ .venv/ node_modules/ data/daemon_slayer/). Top 20 = 16,886 chars = 33% of total. Classification: 10 INTENTIONAL (test/tool docstring section divider art - safe to retain) + 10 candidate (data payloads, JS generated content, archived code, policy definitions - candidates if operator wants sweep).
- **Verdict: STALE-CARRY CONFIRMED.** Orchestrator drops the "542 residual" line from next ledger entry. No code commit needed.

**Slice G read-only no-commit (cc_conditional wave 20 REJECT re-audit at current schema):**
- Per item 184 carry (g): wave 20+ SCHEMA-BLOCKED unless re-audit REJECT carries from waves 11-19 against current Meraki + parent_resource (item 177 forward-marker) + cast_time (item 172) + coexists_with_unconditional (item 176) schemas.
- Cross-referenced ~50 REJECT carries from waves 11-19 against `data/daemon_slayer/16.10.1/champion_abilities.json` + `agents/daemon_slayer/cc_conditional.py` _PER_SPELL_CC_CONDITIONAL + _PER_SPELL_CC_CONDITIONAL_FORMS.
- Verdict per carry: ALL initially-REJECT carries remain REJECT-confirmed (unconditional / minion-only / self-buff / turret-only / out-of-schema / state-tracking / damage-only) OR already-shipped (Renekton W wave 9 / Karma W form 1 wave 10 / Hwei E form 2 wave 10 / Neeko E wave 1 / Aphelios Q form 3 wave 13) OR overridden by later waves' schema lifts (Jayce E cast_time -> shipped wave 14 / Maokai R coexists -> shipped wave 18 / Taliyah E -> shipped wave 17 COND_TRAVERSE).
- 0 NEW ship-candidates surfaced from broader Meraki effects_descriptions + cast_time + parent_resource scan.
- **Verdict: SATURATION DEEPENS no-commit.** Registry stays at 67 entries / 54 champions / 13 condition tags. Future wave 20+ growth needs NEW Meraki schema field OR re-audit of older waves' REJECT pile at a later schema lift.

**Slice J no-commit (housekeeping triple wave 27):**
- Cost/latency lever sweep: 29th consecutive CLEAN since item 134. 7 levers all green. L1 prompt-cache 13 cache_control hits / 8 blocks (matches item 185 baseline); L2 route TTL 14 routes with `_CACHE` (within 12-16 fluctuation); L3 polling tightest NETWORK 2000ms (pollIfStale + pollLcu); L4 log spam `_SUPPRESS_LOG_PATHS` 10 entries unchanged; top non-suppressed /api/bridge 0.132/sec (matches item 184/185 baseline; /api/ward-heat absent because operator out-of-game); L5 model tier all coaches haiku-4-5-20251001 + agent7 DEFAULT_MODEL = haiku (Sonnet only as POST-call telemetry; Opus only agent6_auditor); L6 14 RC-* scheduled tasks; L7 27=27 panel CSS = dashboard.css @imports parity guard 4/4 PASS.
- BACKLOG/ROADMAP stale-sweep wave 27: 0 actionable flips. 8 OPEN file:line anchors grep-verified live within +/- 3 tolerance (dev.js:362 verdict.team_won within +1 tolerance from cited :361 / gamepc_lcu_agent.py:1192 augment_intent_unsupported EXACT / gamepc_lcu_agent.py:245 ARAM Mayhem 2400 within -1 tolerance from cited :246 / gamepc_lcu_agent.py:536 _arena_teams EXACT / archetype_dispatch.py:52 _UNIT_SUFFIX EXACT / rc_supervisor.py:210 CircuitBreaker EXACT / item_build.js:328 _ibBuilds within +1 tolerance / supervisor.py:667 champ_select_states (ROADMAP L61 cites :597 = SHIPPED FU01 historical anchor; intentionally FROZEN per [[feedback_no_history_rewrite]]).
- **Sweep cycle decay:** 17=0 / 18=1 / 19=0 / 20=0 / 21=0 / 22=0 / 23=0 / 24=0 / 25=0 / 26=0 / **27=0** = 10 consecutive zero-flip waves = saturation plateau deepens.
- Living docs sync verify: ENGINE_VERSION=1.56.0 / cc_conditional=67/54 / tags=13 / DS health endpoint serves engine_version=1.56.0 patch=16.10.1 champs=172 items=705 / BRIEF.md L20 + DAEMON_SLAYER.md L5/L32 (4671 tests) + ARCHITECTURE.md L161 + BACKLOG.md L13 + ROADMAP.md L165 ALL current at 1.56.0 / 4671 / 67/54 / waves 0-19 / 13 tags. Item 185 anchors verified live: primitives.css:249 min-height: 360px + replay_events.css:71 max-height: 320px. No drift; no commit needed.

**Slices skipped this session (operator-gated lane items 1-3 + 4-7 explicitly listed but not actionable):**
- set_augment_intent Cherry endpoint discovery: requires live Arena lobby + LCU swagger probe at mid-Arena phase; mode_key=client (no Arena session); deferred to next live Arena window.
- Live UI captures (page #3 Replay + pages #11/12/13 Active Match + ARAM Mayhem smoke): operator out-of-game; deferred.
- DD Defy heal-on-takedown: scope unclear without spec; deferred.
- Calibrations (13 cond-prob midpoints + 67 entry probs + _MISSING_HP_SHARE_FOR_HEALS=0.5 + _CC_EFFECTIVENESS_FACTOR=0.5): operator-gated; no live game outcome data without rewind_history.db backfill; deferred.
- 101.qq.com duo-synergy one-off Game-PC capture: needs operator at Game-PC browser; bridge dispatch to Game-PC Claude possible but capture itself needs operator auth/navigation; deferred.
- Bridge Watcher acceptance (50+ samples): time-gated on real traffic.
- Auto-ops verb expansion + GamePC/Peer auto-action lanes: gated on Phase 3 95% success rate (not yet measured at threshold).

**Verified post-commit:**
- `py -m pytest tests/phase8_smoke/ tests/test_dead_endpoint_cleanup_item186.py tests/test_loadout_list_dedup.py -q` = **87 passed / 4 subtests in 3.73s**. Phase 8 smoke 75 -> 70 (5 dropped because their routes are gone) + 13 dedup tests + 4 drift guard tests = 87 net.
- `py -m ruff check .` ALL CHECKS PASSED.
- DS suite untouched (no engine change; DS :8893 serves 1.56.0 from item 177; not restarted).
- RC :8888 restarted via restart_trigger.txt for route table reload: pid 12612 -> 10352 alive=True last_reload_ok=True mode_key=client throughout post-restart.
- Live HTTP probes: 6/6 deleted routes 404 (correct); 3/3 kept routes handler-hit (correct).
- Pushed `9aea56a..077ee64` origin/main.

**Don't-redo:**
- `_SUPPRESS_LOG_PATHS` 10-entry needle tuple is calibrated; trailing-space needle bug (item 171 root cause) is regressed-protected by `test_constant_contains_high_frequency_paths` + 2 positive tests asserting bare-path-prefix + query-string variants both suppressed.
- The 11 deleted routes are now CI-blocked from re-introduction by `tests/test_dead_endpoint_cleanup_item186.py` AST-walk drift guard. Re-introducing /api/aram-analyze (etc.) requires deleting the corresponding drift guard pin first.
- `web/js/lib/dedup_fetch.js` is the canonical dedup primitive for ALL future panel-level fetch wiring on multi-consumer endpoints. Wire pattern: import dedupFetch from "/js/lib/dedup_fetch.js"; await dedupFetch(url, opts). 100ms grace TTL is appropriate for the typical panel-mount + state-tick coincidence window; longer TTLs need explicit per-call override.
- The "542 residual U+2500" carry-forward is permanently dropped from future ledger entries. rc_supervisor.py + rc_self_monitor.py were swept item 176; the residual count was a stale ledger artifact (item 178+ carry inherited an out-of-date snapshot).
- cc_conditional wave 20+ STILL SCHEMA-BLOCKED at current Meraki + parent_resource + cast_time + coexists_with_unconditional schemas. Future ship-candidates require a NEW field lift in `tools/daemon_slayer_abilities_extract.py` to surface mechanics absent from the current parse-strip (state-tracking thresholds, form-transition gates, recast preconditions).
- 30+ days of orchestrator-merge pattern (items 134-186) demonstrates the 3-5-parallel-slice + sequential-merge + Slice D worktree or direct main + tests gate + restart-if-route-table-changed + docs sync + push template is durable. 38 consecutive runs is the streak.
- Slice C agent self-corrected on caller-verification mid-run: initially flagged 22 routes for deletion, narrowed to 11 truly-dead after grepping tools/ + web/js/ + tests/ + ROADMAP.md + BACKLOG.md for callers. Per [[feedback_verify_generated_reports]]: subagent measurement claims MUST be grep-verified before action.

**Carries forward:**
- Item 185 carries ALL unchanged EXCEPT: (a) item 184 dead-endpoint cleanup (15 candidates) NOW CLOSED via Slice C; (b) item 184 dedup duplicate-fetch cache NOW CLOSED via Slice D; (c) 542 residual U+2500 carry-forward DROPPED as stale (rc_supervisor + rc_self_monitor swept item 176).
- Live UI capture STILL OWED for page #3 Replay (rewind_history.db populated + match selected) + pages #11/12/13 Active Match SR/ARAM/Arena (in-game window).
- DD Defy heal-on-takedown STILL deferred (operator-gated, scope unclear).
- Calibrations STILL operator-gated.
- Legion 1-PC consolidation STILL operator-gated (s169 option B).
- cc_conditional wave 20+ STILL SCHEMA-BLOCKED (this session's Slice G audit confirms saturation; needs NEW Meraki schema lift to unblock).
- set_augment_intent Cherry endpoint discovery STILL live-gated.
- Bridge Watcher acceptance criteria (50+ real samples) STILL time-gated.
- Auto-ops verb expansion + GamePC/Peer auto-action lanes STILL gated on Phase 3 95% success rate.
- 101.qq.com duo-synergy one-off Game-PC capture STILL operator-at-Game-PC-gated.
- Frozen-file grant NOT used this session.
- The 51,287 U+2500 chars across 197 non-frozen files: classified intentional (test/tool divider art) vs candidate (data payloads, archived code) - 10/10 split in top 20. Operator-gated separate sweep if desired; not a blocker.

---

# 2026-05-25 (afternoon) - item 185 SHIPPED: page #3 Replay flex-allocation re-tune + housekeeping triple wave 26 CLEAN (1 commit `e9bc504` pushed origin/main `636804d..e9bc504`; non-engine; non-frozen; no DS engine bump; no DS restart; no RC restart - ADR-008 asset-hash auto-serves CSS on next dashboard load)

Operator "start the next item" - 37th consecutive run using orchestrator-merge pattern (items 134-185). CAVEMAN ULTRA session default. 3 audit slices dispatched concurrent + 1 inline code slice. Pre-flight: 0 open PRs; 0 stale remote branches; CI 5/5 green; HEAD = item 184 `636804d`. Operator mode_key=client (between games) so non-game UI work UNBLOCKED.

**Slice A `e9bc504` (direct main) fix(ui) page #3 Replay flex-allocation re-tune (3 files / +103 / -1):**
- Item 184 carry (b) / item 162 carry (c). 10-row participant table collapsed to ~0 visible rows when 15-event timeline saturated `.replay-events-list { max-height: 480px }`. Edge surfaced after v2.1 typography migration (items 159 + 182) bumped row heights +44% (champ-icon 28 -> 38 / item-icon 22 -> 30 / row min-height -> --hit-min 42px).
- `web/css/panels/primitives.css` `.replay-grid-wrap` gains `min-height: 360px` so participant grid always shows ~6-7 rows visible even when timeline saturates. flex: 1 still grows the grid when timeline is short.
- `web/css/panels/replay_events.css` `.replay-events-list max-height: 480px -> 320px` so timeline does not crowd out the grid in the ~780px `.replay-main-pane` viewport. overflow-y: auto keeps long event tails scrollable.
- NEW `tests/test_replay_view_flex_allocation.py` (~108 LOC, 6 grep-based pin tests across 3 classes): ReplayGridWrapMinHeightTests 2 + ReplayEventsListMaxHeightTests 2 + AsciiHygieneTests 2. Pins .replay-grid-wrap min-height 360 + .replay-events-list max-height 320 + flex: 1 + overflow-y: auto + ASCII hygiene on edited blocks.

**Slice B CLEAN no-commit (BACKLOG/ROADMAP stale-sweep wave 26):**
- 0 actionable flips. Explore subagent flagged 1 semantic drift at `agents/supervisor.py:597` claiming "minimap-locate rewire" reference in ROADMAP L61 is now UIApplyError. Direct verification: ROADMAP L61 is the `✅ FU01 - minimap-locate` SHIPPED entry from s168 (2026-05-11); shipped-entry historical anchors are intentionally frozen per [[feedback_no_history_rewrite]]. False positive on shipped-entry historical citation.
- All 11 canonical OPEN file:line refs grep-verified live within +/- 3 tolerance: `dev.js:361` verdict.team_won / `main.js:3081/3092/4281` LCU 3 sites / `gamepc_lcu_agent.py:246` ARAM Mayhem qid=2400 / `gamepc_lcu_agent.py:536` _arena_teams / `gamepc_lcu_agent.py:1192` augment_intent_unsupported / `rc_supervisor.py:210` CircuitBreaker / `archetype_dispatch.py:52` _UNIT_SUFFIX / `item_build.js:328` _ibBuilds / `core/draft_elo.py:141` cross_pairs (BACKLOG L13 cc_conditional ecosystem cross-ref).
- **Sweep cycle decay:** 17=0 / 18=1 / 19=0 / 20=0 / 21=0 / 22=0 / 23=0 / 24=0 / 25=0 / **26=0** = 9 consecutive zero-flip waves = sustained saturation plateau.

**Slice C CLEAN no-commit (cost/latency wave 28 audit + measurement-error verification):**
- 28th consecutive CLEAN since item 134. Initial Explore subagent report flagged 4 false-positive drift claims; live verification against source authoritative:
  - Lever 1 prompt-cache: agent counted 21 raw cache_control mentions; live `grep cache_control coaches/*.py coach_integration/*.py | wc -l` = 13 hits across 8 cache blocks (matches item 184 baseline of "8 sites" = cache-control marker BLOCKS not raw grep counts). CLEAN.
  - Lever 3 polling: agent flagged 8 sub-500ms NETWORK timers; live grep `setInterval` in `web/js/main.js` shows tightest NETWORK polls = `pollIfStale` 2000ms (L6179) + `pollLcu` 2000ms (L6247); 500ms is `applyStaleness` (L1284) UI-local timer per item 184 baseline. CLEAN.
  - Lever 4 log spam: agent counted 15 _SUPPRESS_LOG_PATHS entries claiming spam at 0.98/sec; live `dashboard/_handler.py:74-85` = 10 entries unchanged from item 184; top non-suppressed `/api/ward-heat` 0.148/sec per item 184 baseline well below 1/sec. The 0.98/sec was LCU lockfile INFO log, not an HTTP route handler log - different category. CLEAN.
  - Lever 6 scheduled tasks: agent reported 0 RC-* tasks; live `schtasks /Query /TN \RC-* /FO LIST | grep -c TaskName` = 13 (matches session-start rc_facts probe of 14 within tolerance for subfolder differences). CLEAN.
  - Lever 5 model tier: agent claimed sonnet-4-6 in aram_coach.py call-time; per item 184 don't-redo + memory `feedback_verify_generated_reports`: Sonnet only appears as `r._model = "claude-sonnet-4-6"` POST-call telemetry stamps (not call-time selection). CLEAN.
- Lever 2 route TTL: 16 routes_*.py with `_CACHE` (within 12-16 loose drift). Lever 7 bundle parity: `ls web/css/panels/*.css | wc -l` = 27 = `grep -c "@import.*panels/" web/css/dashboard.css` = 27. CLEAN.
- **Verdict: 28th consecutive CLEAN no-commit.** Per [[feedback_verify_generated_reports]] agent measurement errors recorded for prompt refinement; do NOT relay subagent audit outputs as-is.

**Slice D CLEAN no-commit (cc_conditional wave 20 audit):**
- SCHEMA-BLOCKED as expected per item 184 don't-redo. 5 wave 19 REJECT carries re-audited against current Meraki schema (parent_resource + coexists_with_unconditional + cast_time):
  - Jayce E cast-time root: REJECT-CONFIRMED (root duration missing from Meraki at parse-strip level despite cast_time=0.25 captured).
  - Maokai R distance-gated: ALREADY SHIPPED wave 18 ENGINE 1.55.0.
  - Taliyah E Unraveled Earth: ALREADY SHIPPED wave 17 ENGINE 1.54.0 COND_TRAVERSE.
  - Rell W form 1: REJECT-CONFIRMED (form-transition semantics not gate-encodable under current schema).
  - Urgot R recast suppression: REJECT-CONFIRMED (no COND_RECAST_THRESHOLD tag exists; HP-threshold gate is recast precondition not CC condition).
- 0 new candidates surfaced from broader Meraki effects_descriptions + cast_time + parent_resource scan.
- **Verdict: SCHEMA-BLOCKED no-commit.** Wave 20+ growth needs (1) new COND_RECAST_THRESHOLD + COND_FORM_TRANSITION tags, (2) Meraki encode of missing root durations, or (3) multi-form orchestration schema. Operator-gated.

**Verified post-commit:**
- `py -m pytest tests/test_replay_view_flex_allocation.py tests/test_replay_events_panel_dom.py tests/phase8_smoke/ -q` = **110 passed in 2.44s** (6 new + 29 replay_events_panel_dom + 75 phase8_smoke).
- `py -m ruff check .` ALL CHECKS PASSED.
- DS suite untouched (no engine change; DS :8893 serves 1.56.0 from item 177; not restarted).
- RC :8888 unchanged pid 7612 alive=True reload_ok=True mode_key=client throughout (ADR-008 auto-serves CSS on next dashboard load).

**Don't-redo:**
- `.replay-grid-wrap min-height: 360px` is canonical floor for the participant grid; do NOT remove without rebalancing against `.replay-events-list` max-height. `.replay-events-list max-height: 320px` is the corresponding cap; future re-tunes should change BOTH in lockstep so the ~780px pane allocation stays balanced (~115px misc + 360 grid + 320 timeline = 795 close to pane height with slight overflow tolerance via overflow:auto on both).
- Slice B + C agent reports caught false positives this session - per [[feedback_verify_generated_reports]] subagent audit numbers MUST be verified vs live source before action. The "1 drift flip" on supervisor.py:597 was a shipped-entry historical anchor; the "5 measurement errors" on cost/latency levers were prompt-misread artifacts. Future audit slice prompts should include explicit "before claiming X, grep against current source" guards.
- 28 consecutive CLEAN cost/latency waves + 9 consecutive zero-flip BACKLOG sweeps confirm saturation; future sweep + audit slices should expect CLEAN no-commit verdicts as baseline.
- Orchestrator-merge pattern now 37 consecutive runs (items 134-185).

**Carry-forward:**
- Item 184 carries ALL unchanged EXCEPT (b) page #3 Replay flex-allocation re-tune NOW CLOSED.
- Live UI capture OWED for page #3 Replay at next operator-driven match-list-populated session (requires `rewind_history.db` populated + a selected match for the 10-row table to render).
- Live UI capture OWED for pages #11/12/13 Active Match SR/ARAM/Arena at next in-game window.
- DD Defy heal-on-takedown STILL deferred.
- Calibrations STILL operator-gated.
- Legion 1-PC consolidation STILL operator-gated.
- cc_conditional wave 20+ STILL SCHEMA-BLOCKED (this session's audit confirms).
- 542 residual U+2500 box-drawing chars STILL operator-gated separate sweep.
- Item 184 dead-endpoint cleanup proposal (15 candidates) STILL operator-gated.
- Item 184 dedup duplicate-fetch cache STILL deferred LOW-priority.
- Frozen-file grant NOT used this session.
