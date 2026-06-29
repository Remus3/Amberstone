# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-29 (Section C - WP-C3 live counter-build / situational_fit shipped; commit `64b7c634`)

Scoped build session (ultracode workflow). Filled the `situational_fit` 0.0 stub left by WP-C2.

- **664 WP-C3 situational counter-build (commit `64b7c634`).** NEW `core/build_planner/situational.py` (390 lines) - pure `situational_fit(build_ids, enemy_profile, ally_state, *, stage) -> [0,1)` over 7 criteria: C1 resist-vs-damage-split, C2 antiheal (ally de-dup), C3 fed-override (additive -> widens resist margin), C4 HP+resist vs pen, C5 pen TYPE from kill-target armor/MR not team avg, C6 tenacity vs CC, C7 `reanchor_plan` operator-deviation. `classify_item` patch-stable (flats + tags + curated NAME rosters on resolved name; both id keyspaces). `build_enemy_profile` is the ONLY impure helper, NEVER in the score_build path. `scoring.score_build` gains `enemy_profile=`/`ally_state=` (lazy import); `enemy_profile=None` stays 0.0 (stub-equivalent, existing test unchanged). Added to planner-test `_SOURCES` (split-brain ast guard + family-literal ban).
- **Built via ultracode workflow:** 3-agent divergent design panel -> synthesis-to-locked-spec -> RED agent -> GREEN agent -> 7 per-criterion adversarial verifiers + structural verifier (all CONFIRM, none fixture-shaped). **Orchestrator fresh ground-truth gate:** 54/0 (situational 35/0 + planner 19/0), py_compile + ruff + ASCII clean, zero banned literal, zero `agents.daemon_slayer` import.
- **Tier-1:** no ENGINE bump, not Share-mirrored, no DS restart, NOT live-wired (WP-C5 `/api/build-plan` consumes it later). **Section J bookkeeping:** also corrected the stale C2 row OPEN -> DONE (`4f1d4126`; the WAKEUP-flagged loop drift - code was already merged item 663).
- **NEXT Section C: WP-C4** (owned-aware re-plan loop + sell/swap + hysteresis; deps C2+C3 satisfied). Lane-A v4 remains a separate open spec (`docs/specs/LANE_A_SCENARIO_PRECOMPUTE_SPEC.md`).

---

# 2026-06-29 (headless run 2026-06-29-01: shipped overlay-flash fix + WP-C2 build planner; Lane A reframed)

Autonomous headless cycle (skill headless-upgrade). 2 verified code slices merged to main + CI-green, cost-sweep CLEAN, 1 forward spec. NO live-game work (gated - see below).

- **662 overlay match-launch flash fix (merge `f99de71b`).** main.js show-before-ready -> `once("ready-to-show")` gate + pure `shouldShowOverlayNow` + a `.ovx-ready` renderer load-gate (distinct from `.ovx-hidden`). rc-shell 306/0 (+7, RED-first). Verifier CONFIRM. OWED: Electron redeploy (Ctrl+Shift+B) + live no-flash pixel capture (gated).
- **663 WP-C2 build planner (merge `4f1d4126`).** NEW core/build_planner/{scoring,planner}.py - pure score_build (DPS READ from ds-preview seed = no split-brain, cohesion via C1 synergy_score) + beam search (width 5-8, depth 6) mirroring beam.py without importing it. 19/0, split-brain ast-guarded, no family literal, NOT live-wired. NEXT Section C: WP-C3 (the situational_fit 0.0 stub).
- **cost-sweep CLEAN** - all 7 levers tight (caches/TTL/polls/log-suppress/haiku-floor/tasks/bundle-parity), no commit.
- **Lane A REFRAMED (spec docs/specs/LANE_A_SCENARIO_PRECOMPUTE_SPEC.md):** the laning-verdict precompute is ALREADY SHIPPED (core/laning_scenario_precompute.py + patch-keyed artifacts + precomputed_laning_coach.py shadow reader) - NOT greenfield. Remaining = a bounded v4 EXTENSION: add cooldown-window + spike-timing verdicts (substrate exists - cooldown_watch/recharge_ledger/spike_markers, unwired) + an item-state axis. The coach-FLIP is GATED (shadow data-starved per LEDGER cycle 55, 0/0 comparable agreement; + no Live Client cooldown producer, ult_up hardcoded None at _deterministic_coaching.py:1019). NEXT cycle builds v4 from the spec.
- **ORCHESTRATION LESSON:** session ran from a STALE worktree (016b3228, pre-C1); a non-isolated Plan agent specced vs old code. FF'd the worktree to main mid-run. Always confirm a non-isolated subagent's checkout == main.
- **STILL OPERATOR-GATED:** the loopback regression (memory project_liveclient_loopback_regression) blocks E2 + ALL live-game verification; it is a Windows-level fix (WFP/Vanguard), NOT RC code.

---

# 2026-06-29 (live-ops session: E2 attempt blown by a SYSTEM loopback regression + overlay-flash + GPU-crash diagnoses; ZERO code shipped)

Operator played practice + ARAM Mayhem; ran the E2 live-flip pass + landed item 661 (below). Three diagnoses, no code change (all system-level or gated on a live game):

- **E2 (3-game live pass) BLOWN.** RC-LiveFlipWatcher (now Running, durable logon trigger) never fired - its gate needs `liveclient.allPlayers`, empty during all 3 games. ROOT = a SYSTEM loopback regression (memory `project_liveclient_loopback_regression`): a connect to ANY closed loopback port refuses in ~2000ms instead of instant, so RC's 1s `:2999` self-read times out -> empty liveclient -> blind 10-player roster + dead watcher. **Survives a reboot.** Ruled out token / `:8889` threading / RC-restart / winsock-LSP (all clean); :2999 + :8889 serve allPlayers=10 in <20ms when hit directly with the token. NOT RC code - needs WFP-filter / Vanguard investigation, operator-gated (do NOT blind-reset networking headless). Core coach (game_reader path) unaffected.
- **GPU DEVICE_HUNG crash (game 1, 21:57)** = a TDR storm (22 nvlddmkm events that evening). Prime cause = the **Parsec Virtual Display Adapter** (operator uninstalled it); driver 610.62 on the RTX 5070. Crash class gone after removal (0 severe 4101 since).
- **Overlay "flash to max size at match launch"** diagnosed, not fixed: `rc-shell/src/main.js:980` shows `overlayWindow` via `showInactive()` on FIRST-match lazy-create BEFORE `ready-to-show`/first paint + no renderer visibility gate until `overlay_layout._applyPos` runs. Fix = `once("ready-to-show")` show-gate + a `.ovx-ready` CSS gate. Verification needs a live game (gated on the loopback fix).

NEXT: (1) resolve the loopback regression (Windows/operator-level) then retry E2 + verify the overlay-flash fix; (2) headless RC CODE work (Section C WP-C2 + ROADMAP) proceeds independently - loopback does not block code.
