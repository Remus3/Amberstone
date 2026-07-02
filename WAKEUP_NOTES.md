# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-02 (R58 LOOP - assume_ms_utility seam: MS utility valuation for bruiser/juggernaut; ENGINE 1.166.0 -> 1.167.0)

Loop directive R58 executed by this session (head e7e95653; merge `304c88dd`, slice `9b42acd8`, LEDGER 738). Premise verified FIRST: item MS resolves into stats["ms"] (engine.py:200) but the bruiser/juggernaut scorer consumed it at ZERO (only consumer ability_dps.py:285); DDragon 16.13.1 DMP 3742 + FoN 4401 both 4 pct MS.

- **Seam (hybrid.py ONLY):** DEFAULT-OFF END-appended `assume_ms_utility` on compute_hybrid + rank_items_by_hybrid (spec caught the routing fact: the ranker does NOT call compute_hybrid - both entry points need the flag). `_ms_utility_multiplier` = 1 + min(0.15 cap, bonus_ms_frac * 0.5) - melee attack-uptime model; DPS term only; shared multiplier cancels in the normalized pct; raw dps/delta_dps stay RAW (no Shipwrecker double-count). Worked pin: Darius + DMP + FoN -> 367.2 -> x1.04; zero-DPS FoN gains exactly +0.013 hybrid_delta_pct.
- **Orchestrated:** Plan spec agent (cites re-verified) -> 1 worktree build agent (TDD RED 16F/2P observed -> GREEN 18 tests) -> verifier CONFIRM 7/7 -> sole merger.
- **Ship:** ENGINE 1.167.0 (pins 107/94, 0 stray) + DS bounce (live 1.167.0) + Share --check green 393 files SAME commit; Share/CHANGELOG 1.167.0 prepend + backfilled the MISSING 1.165.0->1.166.0 OQ11 entry; DAEMON_SLAYER banner 1.167.0/7751. Fresh dual suite: DS 7751 / RC 10435, 0 failed.
- **Handoff:** stack-ramp conditional-MS registry (Shipwrecker +20 flat at 100 momentum / Steadfast +6 pct at max stacks) feeds the same seam later. Live default-ON flip -> LIVE_GAME_GATED_SYNC B41 (PRACTICE-SR) + flip-ledger entry.
- Frozen files untouched. CI green baseline held. Worktree note: C:/RC-CIWatchdog belongs to that scheduled task, untouched.

---

# 2026-07-02 (OQ15 - QA20 this-match dot overlay on GPI radar; backend + ui, NO ENGINE/DS/Share)

Loop directive OQ15 executed by this session (head 744e3e87; merges `b6f6220a` backend + `fd15a9fd` frontend, LEDGER 736). Premise verified first (radar geometry + OQ15 OPEN); Plan-agent spec citation-checked vs source before any build.

- **Backend (core/player_gpi.py):** `_this_match_block(games)` - newest game scored per relative axis as 100*midrank-percentile vs the full directional baseline; versatility/consistency null (no single-match analog); `this_match` {match_id, champion_id, game_creation_ts, axes x8} rides the existing payload + route TTL cache (route change = docstring only; match_id flip drives the frontend repaint).
- **Frontend (player_gpi.js/.css):** `_matchDotsSvg` by-KEY dots (r=2.4 amber --signal-warn, above polygon below labels, "" on absent/malformed this_match - old payloads byte-identical), `_matchLegend` "last game - <champ> - Nh ago", sig gains `|tm:` incl match_id. SVG user-units under the pre-existing documented exception.
- **Orchestrated:** 2 parallel worktree slices on disjoint files to a frozen contract -> verifier CONFIRM each (A fresh 89/89, B fresh 9/9) -> sole merger --no-ff. TDD RED-first both (A 10F red, B 2F red observed).
- **Proof:** full RC suite fresh on merged main 10435 passed / 2 skipped / 193 subtests (+20 over OQ14); RC restarted pid 18500 -> 16652 alive/reload_ok; LIVE /api/player-profile: this_match Vayne NA1_5592802194 aggression 93.9 / tempo 93.6 / survival 33.9, 6 non-null + 2 null. 5-phase audit PASS 0 MUST-FIX / 0 SHOULD-FIX; harness capture inspected (6 amber dots + legend).
- **OWED carry-forward:** Electron-companion capture of the champ-select GPI panel with the dot overlay during a real champ-select (panel not on the in-game overlay view; live state idle - OQ12/OQ13/OQ14 precedent).
- NICE FUTURE: legend age drift excluded from sig (coarse-by-design); stale "200-unit viewBox" comment player_gpi.css:142; _champName(null) cosmetic. NO DS path, NO ENGINE. Frozen files untouched.
- OPERATOR-QUEUE: OQ12/13/14/15 now DONE; OQ18 (drain-plan PREP live-input wiring) remains OPEN in ORCHESTRATION_PLAN - a natural next-cycle pick.

---

# 2026-07-02 (OQ14 - Interactive Item Shaper 3-knob strip; overlay-ui + backend route, NO ENGINE/DS/Share)

Loop directive OQ14 executed by this session (executor cycle 6, head c89a3e5b; feature `639e2789` + docs `d8396df0`, LEDGER 735). PREMISE-CHECK first (did NOT scaffold on the directive's "pure UI" label): grep proved core/shaper.apply_shaper had ZERO prod callers, rank_items (rank.py:527) takes NO weight-dict arg, and the archetype blend is a 2-axis [alpha,beta] per-champ table - so a full nudge->re-ranked-item-list wire is an ENGINE SEAM the directive mislabeled. Took the SAFEST-REVERSIBLE scope (PART C + operator no-questions): an HONEST emphasis preview, logging the full re-rank as a BACKLOG FUTURE.

- **Backend (`routes_ds_shape.py`):** NEW read-only GET /api/ds-shape (mirrors routes_ds_knobs) -> per-champ [alpha,beta] from the REAL archetype_weights.json -> baseline {damage:alpha, survivability:beta, utility:0.0} -> apply_shaper(ShaperState) -> baseline/shaped fractions + *_pct + archetype_source. Knobs int-clamped [-2,2]; 400 blank champion; graceful 500 (no raw traceback).
- **Frontend (`ds_shaper.js` + `.css`):** 3-knob strip Row4 SHAPER (after FIGHT MODEL in active_match.js). Non-persisting module var (NO localStorage), snaps to 0 on champion change + resetShaper() for match end; debounced dedupFetch; escHtml; renders "LABEL base -> shaped". CSS tokens-only (--hit-min 42 buttons, --fs-xs/sm >=16, --signal-info operator tone).
- **Orchestrated:** 2 parallel worktree slices on DISJOINT NEW files to a frozen route contract -> read-only verifier CONFIRM each (A 16 / B 6 node DOM passed fresh; cross-slice contract keys baseline_pct/shaped_pct + path + query MATCH) -> sole-merger wiring of the 3 shared files (_dispatch.py + dashboard.css + active_match.js). TDD RED-first both slices.
- **Proof:** full RC suite fresh on merged main 10415 passed / 2 skipped / 193 subtests; RC restarted pid 15840 -> 18500 (alive/reload_ok); LIVE ROUTE PROBE end-to-end green Darius dmg+1/surv-1 -> 65/35/0 baseline -> 72/27/0 shaped (both push to damage, sums 1.0, 4ms). 5-phase UI audit PASS 0 MUST-FIX / 0 SHOULD-FIX. In-game overlay pixel capture OWED (no live game - the strip renders only in-game).
- NO DS path -> no DS bounce, no Share sync, NO ENGINE (precommit confirmed no mirrored source staged). Did NOT stage the pre-existing data/spell_prefs.json drift. Frozen files untouched.
- Remaining OPEN queue: OQ15 (GPI radar this-match dot). FUTURE (BACKLOG): Item Shaper full re-rank engine seam (3-axis weight surface + ranker threading; do NOT build blind).
