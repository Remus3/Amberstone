# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-07 - loop cycle 3 (run 2026-06-06): E1 per-role rubric EMPIRICAL CALIBRATION SHIPPED [item 335]

Gemini-directed headless cycle; directive = ORCHESTRATION_PLAN session E1 (tune core/post_game_rubric.py weight vectors from public per-role data). Operator interrupted after this cycle -> STOP dropped, loop halted, /done. Non-engine, non-frozen; ENGINE stays 1.120.0 (DS untouched, no Share); RC restarted pid 27300 -> 9412 (route reload). Commits `42780b3d` code + `d7ebebbd` docs.

- **NOT a stale premise (breaks the D1/D2/B1 streak):** the rubric existed + was LIVE-wired (routes_post_game_rubric -> last_match.js hero grade chip + postmortem_analyze) but its weights were hand-estimated "STARTING" values. GROUND TRUTH over 5957 ranked-SR rows in data/rewind_history.db (map 11 CLASSIC >=15min, real obj): the median real game graded **D** (TOP/JG/MID/ADC) / **C** (SUP), scores 33-46 - violating the module's own documented "median 1.0-profile -> 50 (B)" invariant. dpm baselines ran 40-80% low (TOP 480 vs real 717), KDA high (TOP 2.50 vs 1.78), weight sums 3.70-4.60 (need 5.0 for the x10 to hit 50).
- **Fix (2 grounded axes):** `_ROLE_BASELINES` -> empirical real per-role medians; `_DEFAULT_WEIGHTS` -> public-source emphasis ordering (unrankedsmurfs confirms Riot publishes NO exact weights: CS-led TOP/MID, obj/KP-heaviest JG, vision + strict-KDA SUP, carry-damage ADC), every vector now sums to 5.0. Validated on the same corpus: median now grades **B** all roles (TOP 51.5 / JG 53.3 / MID 52.0 / ADC 53.5 / SUP 54.6) with a sane S+..D spread.
- **Tests:** +2 durable db-independent invariants (`CalibrationInvariantTests`: weight-sum==5.0 + baseline-profile==50/B). Blast radius 1 source + 4 test files (the obj dilution/compose tests pad ally objectives so the operator share stays below the now-realistic 2x-median obj clamp - high-share games correctly saturate). verifier CONFIRM from clean state; FULL RC **5257 passed / 1 skip / 0 fail**; ruff clean; CI green (hygiene + smoke + snapshot).
- **Don't-redo:** E1 DONE - do NOT revert to hand-estimates or re-pitch "tune the weights" (now source-ordered + sum-5.0 + invariant-locked; the override JSON loader stays for operator tuning). FUTURE: CC-score is a source-cited SUP signal with no rubric axis yet (schema lift); baselines are SR-only (event modes grade vs SR medians). NEXT OPEN = E2 (LCU data.json diff research).

---

# 2026-06-06 - loop cycle 3 (run 2026-06-06-02): A2b DS-Matchup card SHIPPED [item 327]

Gemini-directed headless cycle; directive = ORCHESTRATION_PLAN session A2b. Orchestrator-merge: 1 Claude sole-merger + 2 parallel disjoint worktree slices + read-only verifier gate. Merges `0a4b0dc0` backend + `3dd1cdcf` frontend + UI-fix `0a017dc4`. Non-engine, non-frozen; ENGINE stays 1.120.0 (DS untouched, NOT restarted); RC restarted pid 13060 -> 13948 for the route reload.

- **Shipped:** NEW `GET /api/ds-matchup` (`dashboard/routes_ds_matchup.py` + `_dispatch.py`) - thin read-only adapter over the EXISTING `core/daemon_slayer_client.matchup()` (POST `/v2/matchup`, item-265 compute_matchup engine) + a champ-select card (`web/js/panels/ds_matchup.js` + `.css` + `web/data/ui_mock/ds_matchup.json`). DISTINCT pairwise surface, NOT a ds-profile axis. Purely additive; mirrors routes_ds_profile (5-min cache, numeric-key->slug, fail-soft 400/503/200-no_matchup). Payload adds swing_pct (0-100, 50=even) + favored (A/B/even) over the raw MatchupResult.
- **Card:** champ_a=cs.my_champion vs champ_b=first committed enemy; verdict chip (all_in/trade green, back_off red, even info) over a centered swing bar + per-side pct-removed + casts notes.
- **Verify:** both slices verifier-CONFIRM (21/0 + 8/0); FULL RC suite **5185 passed / 1 skip / 0 fail**; ruff + node --check clean; ASCII-clean. 5-phase UI audit **1 MUST-FIX FIXED** (`setDsMatchupScheduler` was never wired in champ_select.js -> card rendered 1 tick late on cold cache; + regression test) **+ 1 SHOULD FIXED** (`.dsm-head-sub` min-width:0/overflow-wrap guard). Live: Vayne vs Caitlyn L1 back_off favored B -0.148; L6 -0.303; numeric 67/51 resolves; missing param 400.
- **VISUAL CAPTURE OWED** (carry-forward): Game-PC `:8892` MCP down (SessionStart /health None) + Claude_Preview can't reach HTTPS self-signed `:8888` (same A1/A2 blocker). Code-side audit + live probe + DOM tests stand in.
- **Don't-redo:** A2b DONE - thin adapter over `/v2/matchup` (do NOT reimplement compute_matchup or load a DataSnapshot in the web process); champ_b defaults to the first committed enemy (selectable-enemy dropdown = FUTURE). FUTURE audit nits: `_signature` omits combo-flags/notes; `.dsm-swing-end` nowrap; `_notesHtml` "full combo" doubled phrase.

---

# 2026-06-06 - loop cycle 5 (run 2026-06-06-01): A1 DS-Profile panel SHIPPED [item 325]

Gemini-directed headless cycle; directive = ORCHESTRATION_PLAN session A1. Orchestrator-merge: 1 Claude sole-merger + 2 parallel disjoint worktree slices + read-only verifier gate. Commit `8e376858`. Non-engine, non-frozen; ENGINE stays 1.120.0 (DS untouched, NOT restarted); RC restarted pid 24164 for the new route.

- **Shipped:** NEW `GET /api/ds-profile` (`dashboard/routes_ds_profile.py` + `_dispatch.py`) aggregating the 4 EXISTING pure scorers (compute_mobility/sustain/scaling/waveclear) into a locked-champ 4-bar champ-select panel (`web/js/panels/ds_profile.js` + `.css` + `web/data/ui_mock/ds_profile.json`). Purely additive; mirrors the ds_sweep competitor-lift pattern (5-min cache, numeric-key->slug, fail-soft 400/200-no_profile/503).
- **Per-axis bar:** leaguewide-max-% (cached once) + LOW/MED/HIGH tier; scaling -> UP/EVEN/DOWN slope chip; waveclear -> top_kind + ranged_shove. Live Vayne: mob9/sus0/scal41-UP/wave1.
- **Wiring (orchestrator-owned shared files):** index.html mount `#csv-sugg-ds-profile`, champ_select.js import+scheduler+`dsp:` signature, dashboard.css @import.
- **Verify:** both slices verifier-CONFIRM; FULL RC suite **5153 passed / 1 skip / 0 fail**; ruff clean; ASCII-clean. 5-phase UI audit **PASS 0 MUST-FIX / 0 SHOULD-FIX / 1 NICE** (`.dsp-detail` overflow guard - cosmetic, ancestor-clipped).
- **VISUAL CAPTURE OWED** (carry-forward): Claude_Preview can't reach HTTPS self-signed `:8888` + Game-PC `:8892` MCP down (`project_gamepc_mcp_boot_gap`). Code-side audit + live probe + DOM tests stand in.
- **Don't-redo:** A1 DONE - reads the 4 existing scorers, no engine math; ASCII trajectory words not arrows. **NEXT (A2):** add threat-range/zone-control/objective-damage/extended-duel/matchup axes to the SAME `/api/ds-profile` surface (fns exist: threatrange/zonecontrol/objdamage/extendedduel.py) + re-audit.
