# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-17 - live-session prep batch (operator-directed; eyeball harness + DSP5/6/7 consumers + anti-tank P3.2 producer)

Operator asked to bundle-plan the live-game-gated open items for the next session, then (AskUserQuestion) to build all 4 prep items. Shipped 5 commits (`c0c46410` `b09c100d` `0357defb` `ce33870a` + LEDGER 488); ENGINE 1.139.0 -> 1.140.0.

- **Eyeball harness** `ops/audit/ds_perm_swarm/live_flip_eyeball.py`: OFF-vs-ON top-6 dump for the 9 flag-ready seams (DSV2/3/4, DSP2, DSP8, DSP11 dps+burst, RF1, RF2, RF3+RF6) - one diff/champ, no mid-game `:8893` restarts. Smoke matched every documented intent.
- **DSP5/6/7 consumers** `agents/daemon_slayer/dsp_live_consumers.py` (ENGINE 1.140.0): the substrate seams had NO consumer; now `summoner_fight_adjustments` / `enemy_rune_threat` / `ally_protected_ehp` exist (byte-identical on empty context). DS :8893 restarted 1.140.0; Share 365.
- **Anti-tank P3.2 producer** `antitank.compute_antitank_live` (Tier-1, no bump): resolves live AP/AD via `build_champion` -> `compute_antitank(stats=)`. ehp ally-resist half folded into DSP7.
- **Plan** `docs/LIVE_GAME_GATED_SYNC.md` "Next-session play order": 34 gated boxes -> 3-game min (SR/ARAM/Arena).

GATE: DS 7334 / RC 8333 / Share --check green; +15 TDD; ruff+ASCII clean. (7 RC reds on the first 12min run were a Share-sync/DS-restart SEQUENCING artifact - all green on fresh re-run; the RF2/RF6 LiveFresh lesson.)

NEXT (live session, all still DEFAULT-OFF, do-not-flip-blind): run the eyeball harness + tick the seams; DSP5/6/7 + anti-tank now need only live-input plumb + eyeball (NOT consumer-building); HZ Lane-A/B + st-* + brief-flip need a corpus (>1 game). Do NOT rebuild the consumers - they shipped. DAEMON_SLAYER.md changelog had drifted to 1.129.0 (loop skipped it); bumped to 1.140.0 + a gap-bridge pointer (1.130-1.139 canonical entries are in Share/CHANGELOG + LEDGER 464-487) - do NOT backfill those 10 versions.

---

# 2026-06-17 - RF6 ds-engine: ehp/tank survivability INJECT seam (headless gemini-loop cycle 6, round-2 refill)

**Commit `700fa6a8`** (ENGINE 1.138.0 -> 1.139.0, DEFAULT-OFF). ORCHESTRATION_PLAN RF6, the last OPEN round-2 row.

- **Problem:** RF4 found RF3's ehp/tank survivability FLOAT is a no-op for Rell - its sole tabled winner Fimbulwinter 3121 is NOT in Rell's candidate pool, so there is nothing to float.
- **Root-cause (probe-confirmed, NOT the directive's assumed "mana-item gate"):** 3121 is dropped by `_is_purchasable` - `gold.purchasable=False` because it is the non-purchasable mana-line TRANSFORM of Winter's Approach 3119 (terminal+ARAM-legal; the off-class marksman deny is marksman-only, Rell is a tank). Probe: 3121 NOT in Rell pool OFF (124 items); RF3 float ON surfaced `[]`.
- **Deviation logged (feedback_audit_proposals_are_intent):** the directive's literal "mirror RF2's `only_ids |= surv_ids`" is INSUFFICIENT - RF2's hps inject ALSO silently drops 3121 for Rakan (the union still runs through `_is_purchasable`). Implemented the INTENT via a NEW `inject_ids` force-admit param on `rank._filter_candidates` (bypasses only_ids/exclude_names/`_is_purchasable`; still honors current/non-coachable/mode-legality/terminal/budget; `None` default byte-identical for all 7 callers). `ehp.rank_items_by_ehp` passes `inject_ids=surv_ids` only when the RF3 seam is ON.
- **Scope:** ehp lane only; hps (RF2, DONE) left byte-identical. FUTURE: the same purchasable-gate gap exists for Rakan's hps 3121 - the `inject_ids` mechanism now exists to fix it (logged LIVE_GAME_GATED_SYNC.md RF6 ledger).
- **Verify:** DS :8893 bounced (PID 14148 -> /health 1.139.0); ds_share_sync 362 --check in sync; DS+Share CHANGELOG. +12 TDD (`test_survivability_item_credit_rf6.py`). DS 7324 / RC 8333, ruff+py_compile clean, no frozen files.
- **NEXT:** round-2 refill queue (RF1-RF6) DRAINED -> expect director NO_WORK or new refill.

---

# 2026-06-17 - RF5 test-hygiene: hermeticity sibling sweep (headless gemini-loop cycle 5, round-2 refill)

- Executor cycle 5 of the round-2-refill swarm (`ops/loop`, gemini director). Directive = RF5 (test-hermeticity sibling sweep). Tier-1 test-hygiene work commit `e0f3da12` + this docs closeout; NO ENGINE bump / DS restart / Share sync / frozen / RC restart / backfill.
- GROUND-TRUTH SWEEP: a before/after snapshot of 18 prod write-target artifacts (controller.log + 5 shadow jsonls + coach_trace + ds_calibration + decisions_* + lessons_*/bridge_monitor + post_game configs) across the FULL RC (8329) + DS (7312) suites = NO DELTA - the suite has NO active polluter. The authors already stub `coach_trace.append`, monkeypatch `decision_detector._HEARTBEAT_PATH` to tmp, and pass explicit `path=` to the shadow + DS writers.
- DIRECT vector clean: 0 repo-root-anchored (`parent.parent`/`PROJECT_ROOT`/`__file__`) writes in either test dir; the 3 prod-token direct candidates all tmp-rooted (test_metrics_cache TemporaryDirectory / test_p2w4_hw2_a _seed(tmp_path) / test_loop_status_route CONTROLLER_LOG monkeypatched).
- INDIRECT vector = the only gap: `coach_trace.append()` + `ds_calibration.log_ds_run()` HARDCODE a module-global prod path with NO `path` param, so a caller has no tmp seam = latent polluters.
- SHIPPED (mirror SHADOW_PATH net / item 386 + OPEN2 CTL redirect): conftest autouse `redirect_prod_write_paths_to_tmp` -> `_TRACE_FILE` + `_LOG_PATH` redirected to an ISOLATED `tmp_path_factory.mktemp` dir (NOT the test's tmp_path - an initial `tmp_path/"prodwrite"` subdir leaked into the cache-prune tests' `iterdir()` and broke test_ddragon_mirror_prune x2 + test_meta_build_cache_retention; the full-suite gate caught it -> fixed via tmp_path_factory) + the directive-mandated session-scoped `assert_prod_artifacts_unchanged` regression guard (12 coaching/loop/game-only artifacts; health.json/logs/lessons_*/bridge_monitor excluded so it cannot flake on the live daemon). ds_coach_shadow left alone (already hermetic via explicit path=; redirecting would break test_shadow_path_default).
- TDD +4 `tests/test_hermeticity_prod_writes.py` (RED-first: both globals under prod data/ = 2 failed -> GREEN: off-prod + no-path writers land in tmp, prod byte-unchanged). GATE: RC `tests/ --ignore=tests/daemon_slayer` 8333 passed / 2 skip / 109 subtests exit 0 (+4 vs 8329 RF4 baseline, 0 regress); DS-dir untouched (separate conftest scope, 7312 stands); ruff clean; py_compile OK; ASCII clean; doc hygiene 14 passed; ROADMAP 80556B under budget. INLINE sole orchestrator (R9 + clean-sweep clause); verifier SKIPPED per R7 (the before/after NO-DELTA snapshot + RED->GREEN IS the verify). No frozen files. ORCHESTRATION_PLAN RF5 OPEN->DONE; LEDGER 486; ROADMAP swarm sync.
- NEXT: RF6 (RF4-surfaced ehp INJECT seam for Rell Fimbulwinter, not-pooled) - last OPEN row. Tracker `docs/ORCHESTRATION_PLAN.md`.
