# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-29 (headless run 2026-06-29-02 + WP-C5: CI baseline fully restored + Lane A v4 + /api/build-plan route)

Headless cycle (skill headless-upgrade), then a WP-C5 follow-on after the operator archived an
accidental 2nd loop. Sole-writer across my commits (disjoint files; zero collisions with the loop).

- **670 WP-C5 /api/build-plan route (merge `cedb78c2`).** NEW `dashboard/routes_build_plan.py` composes
  ds-preview + build-order + `ReplanLoop.tick` -> the `{ok,live[],meta[],knobs,plan_meta}` contract; HTTP
  `seed_fn` boundary (no in-process engine - split-brain); registered in `_dispatch.py`; active_match.js
  Row1 wired. P1L4 guard WIDENED (situational is the on-demand planner brain, ZERO coach-tick callers) -
  fixes the nightly red WP-C3 introduced. Tier-2, no ENGINE bump. Verifier 9/9 CONFIRM; backend gate 9941 passed.
- **666-669 CI baseline RESTORE + Lane A v4.** 666 fixed the nightly COLLECTION crash (importorskip numpy +
  win32-only hotkey skips) - the full Linux suite had NEVER completed. That unmasked 668's 5 pre-existing
  failures (home-rank missing-DB / loop empty-CFG / overlay raw-hex) - all fixed. 667 = Lane A v4 (schema v4 +
  cooldown_window + spike_timing + item-state axis; charter 4b; shadow-only, slice E full-roster regen + F
  coach-flip GATED). 669 = a v4 test follow-up (test_laning_scenario_economy v3->v4, the import-sweep blind spot).
- **NEXT:** Section C continues (the master-plan Section J tracker is the live WP map) - WP-D series (D3 reuses
  replan.py for the per-item override store) + the B-series Row1 visual polish; Lane A slice E (full-roster v4
  regen, isolated) + slice F (gated flip, do-not-flip-blind). **OWED:** live in-game overlay visual capture for
  WP-C5 Row1 (not agent-reachable). Memory added: `feedback_schema_bump_grep_literal_value`.

---

# 2026-06-29 (Section C - WP-C4 owned-aware re-plan loop + sell/swap + hysteresis shipped; commit `51f3141d`)

Scoped build session (ultracode workflow). Fourth + last build-brain MODULE before the C5 route wires it live.

- **665 WP-C4 owned-aware re-plan (commit `51f3141d`).** NEW `core/build_planner/replan.py` - `ReplanLoop.tick()` keeps owned items as a FIXED prefix (never re-planned; C2 `plan_build` already drops owned from the pool), re-beams only the tail, and applies anti-flip-flop hysteresis. **Hysteresis:** stickiness margin (challenger flips only if single-item `score_build([id]).total > incumbent*1.10`), pure `schmitt()` pivot (add 1.20 / drop 0.90, inclusive, drop<add invariant), just-bought lock (game-clock seconds; off-build mid+ exempt; purchase = owned COUNT growth so a 3340->3363 trinket swap is not a false purchase; first tick = no phantom), sell rate-limit (<=1/stage, resets on stage change). **Sell/swap:** free trinket upgrade 3340->3363 (bypasses all gates), boots-sell at 6-item+surplus (boots = `Boots` tag OR from-closure to 1001), true swap ONLY on matchup-invalidated (antiheal vs heal_sources==0, %armor-pen vs squishy kill target; one swap/item). **Component-defer = real recipe membership:** `component_ids_of` transitive `from`-closure (owned 3036 -> defers planned 3035, live-verified). State IN-MEMORY: `accept()` logs, `end_match(path)` opt-in atomic save. replan.py added to planner-test `_SOURCES` (split-brain + family-literal guard).
- **Built via ultracode workflow:** 2-agent adversarial DESIGN CRITIQUE -> spec synthesis -> RED agent -> GREEN agent -> 4 adversarial verifiers (ground-truth + hysteresis + sell-gating + prefix/defer/purity). **The critique CAUGHT a real blocker** - the original spec's `_first_item_totals` beam-map gate would collapse at full depth (bw6 dp6 -> 1 distinct opener) and flip the incumbent every tick, DEFEATING no-whiplash; the impl correctly diverged to a single-item `score_build` gate with "viable == in pool AND unowned". All 4 verdicts CONFIRM/high, none fixture-shaped. **Orchestrator fresh ground-truth gate:** 49/0 (replan 30 + planner 19), py_compile + ruff + ASCII clean, zero banned literal, zero `agents.daemon_slayer` import.
- **Tier-1:** no ENGINE bump, not Share-mirrored, no DS restart, NOT live-wired. **NEXT Section C: WP-C5** (`/api/build-plan` data contract DS->module->panel; Tier-2 route + integration tests; deps C2/C3/C4 now ALL satisfied + B2 panel). D3 also reuses replan.py for the per-item override store.

---

# 2026-06-29 (Section C - WP-C3 live counter-build / situational_fit shipped; commit `64b7c634`)

Scoped build session (ultracode workflow). Filled the `situational_fit` 0.0 stub left by WP-C2.

- **664 WP-C3 situational counter-build (commit `64b7c634`).** NEW `core/build_planner/situational.py` (390 lines) - pure `situational_fit(build_ids, enemy_profile, ally_state, *, stage) -> [0,1)` over 7 criteria: C1 resist-vs-damage-split, C2 antiheal (ally de-dup), C3 fed-override (additive -> widens resist margin), C4 HP+resist vs pen, C5 pen TYPE from kill-target armor/MR not team avg, C6 tenacity vs CC, C7 `reanchor_plan` operator-deviation. `classify_item` patch-stable (flats + tags + curated NAME rosters on resolved name; both id keyspaces). `build_enemy_profile` is the ONLY impure helper, NEVER in the score_build path. `scoring.score_build` gains `enemy_profile=`/`ally_state=` (lazy import); `enemy_profile=None` stays 0.0 (stub-equivalent, existing test unchanged). Added to planner-test `_SOURCES` (split-brain ast guard + family-literal ban).
- **Built via ultracode workflow:** 3-agent divergent design panel -> synthesis-to-locked-spec -> RED agent -> GREEN agent -> 7 per-criterion adversarial verifiers + structural verifier (all CONFIRM, none fixture-shaped). **Orchestrator fresh ground-truth gate:** 54/0 (situational 35/0 + planner 19/0), py_compile + ruff + ASCII clean, zero banned literal, zero `agents.daemon_slayer` import.
- **Tier-1:** no ENGINE bump, not Share-mirrored, no DS restart, NOT live-wired (WP-C5 `/api/build-plan` consumes it later). **Section J bookkeeping:** also corrected the stale C2 row OPEN -> DONE (`4f1d4126`; the WAKEUP-flagged loop drift - code was already merged item 663).
- **NEXT Section C: WP-C4** (owned-aware re-plan loop + sell/swap + hysteresis; deps C2+C3 satisfied). Lane-A v4 remains a separate open spec (`docs/specs/LANE_A_SCENARIO_PRECOMPUTE_SPEC.md`).
