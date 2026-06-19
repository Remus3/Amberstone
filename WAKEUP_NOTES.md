# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-18 (PM5) - F2 cost-aware-top gate (DS Tier-2 nom F2, DEFAULT-OFF; ENGINE 1.142.0)

Operator "continue open items from last run". Shipped the second bounded DS Tier-2
ship-or-close nomination from PM3's `TIER2_REPORT.md`. Commit `<hash>`, CI GREEN.

- **PREFLIGHT:** DS :8893 was DOWN (no proc) -> relaunched detached, healthy ENGINE 1.141.0 ->
  (post-bump) 1.142.0. RC-DaemonSlayer result=1 / RC-GeminiAudit result=3 / RC-WeeklyHygiene
  result=1 = same external/stale anomalies as PM3/PM4 (gemini loop DOWN, not locally fixable).
- **F2 cost-aware-top (item 497, ENGINE 1.141.0 -> 1.142.0; DS :8893 restarted; Share 367).**
  `rank.py` `sort_by="delta"` scales with cost -> 6000g ARAM/Arena Void Immolation `223069` ranks #1
  on hybrid/bruiser + ehp/tank across ~66 champs (artifact, NO WIN gate). NEW DEFAULT-OFF
  `cost_ceiling` param on the shared `_filter_candidates` (drop `gold.total` STRICTLY > ceiling)
  threaded through `rank_items`/`rank_items_by_ehp`/`rank_items_by_hybrid`; other 4 callers unchanged
  -> byte-identical OFF. +12 TDD (difference-of-differences). Reproduced live (Garen bruiser ARAM
  rank-1 = 223069). PM4 id/mode subtlety RESOLVED: 223069 is a genuine base id (maps 12+30 ARAM+Arena),
  NOT the `22`-alias quirk; report "ARAM-exclusive" imprecise. DS-dir 7360 / RC tests/ 8439 green;
  87 ENGINE pins / 79 files; Share --check in sync.
- **B2 found largely ALREADY SHIPPED** (DSP11 `prefer_kit_axis_by_win` + DSP2 `exempt_offclass_by_win`)
  - only per-champion live re-rank validation remains. A ARAM-override stays default-OFF. B1+F2
  bounded Tier-2 nominations now DONE; lane tail is live-validation-gated -> `LIVE_GAME_GATED_SYNC.md`.
- **Doc-budget:** pre-existing `test_roadmap_md_under_budget` RED (82556 > 80KB; CI runs no pytest so
  PM4 missed it) cleared by relocating the shipped item-320 `prefer_cdragon_ratios` block verbatim to
  `ROADMAP_HISTORY.md` (now 81269 < 81920).
- `ops/loop/{config.json,director_prompt.md}` STILL uncommitted (operator pre-run loop tuning,
  untouched PM2-PM5; gemini loop DOWN).

---

# 2026-06-18 (PM4) - B1 melee-applicability gate (DS Tier-2 nom B, DEFAULT-OFF)

Operator "continue open items from last run". Shipped the single named highest-value DS
Tier-2 follow-on from PM3's `TIER2_REPORT.md`. Commit `b2953489`, CI run 27796044261 GREEN.

- **B1 melee-gate (item 496, ENGINE 1.140.0 -> 1.141.0; DS :8893 restarted pid 25116; Share 366).**
  `dps.py`/`hybrid.py` had no attack-range gate -> Runaan's bolts (ranged-basic-only) credited on
  melee autos. NEW `PeriodicProc.ranged_only` (on `3085`+`223085`) + `CallContext.is_melee`
  (attackrange < new `dps.MELEE_RANGE_CEILING`=350) + `apply_melee_aa_gate` threaded compute_dps ->
  _phase_weighted_dps -> _rotation_attack_dps -> _periodic_proc_dps + _per_attack_proc_damage +
  compute_hybrid. ON+melee -> bolts contribute 0; OFF byte-identical; ranged unaffected. +9 TDD
  (diff-of-differences). DS-dir 7348 / RC tests/ 8432 green. Hybrid RANKER call sites deliberately
  NOT threaded (out of compute_hybrid scope; caught a NameError + reverted).
- **NOT taken (logged ROADMAP + LIVE_GATED as next bounded Tier-2 slices):** B2 kit-agnostic AD-axis
  (Ezreal Muramana/TF; Xayah/Nilah crit-not-on-hit) + F2 gold-aware top (223069 is Arena-prefixed
  yet report says ARAM-exclusive -> id/mode subtlety, [[reference_items_index_alias_ids]]; mutates the
  live ranking surface so do-not-flip-blind). Stopped at B1 to avoid stacking a subtler change.
- **A (ARAM override) stays default-OFF** - only Shaco a clean CONFIRM (+26.9pp); operator off-meta call.
- `ops/loop/{config.json,director_prompt.md}` STILL uncommitted (operator pre-run loop tuning, untouched
  PM2/PM3/PM4; gemini loop DOWN - RC-GeminiAudit result=3 external blip, not locally fixable).

---

# 2026-06-18 (PM3) - interactive headless: anomaly triage + 5-slice batch

Operator dispatched the full open-items list interactively, chose "launch headless loop"
(Claude-directed; the gemini loop is DOWN). Run 2026-06-18-02, HEAD af46008c -> 917cbb89.

ANOMALIES (preflight, all handled):
- DS :8893 was DOWN (no proc) -> restarted detached, healthy ENGINE 1.140.0 / 16.12.1 / 172 champs.
- RC-GeminiAudit result=3 = EXTERNAL Gemini blip: gemini-3-pro-preview AND gemini-2.5-flash both
  time out (exit 124); clean nightly thru 06/17, broke 06/18 03:04. Not locally fixable; gates the
  2 "Gemini-consult-first" items. Needs a quota/billing check or self-resolves. RC-WeeklyHygiene
  result=1 stale (06/14, next 06/21).

SHIPPED (5 slices, all on main):
- 8ccbaa9c test(D9): control-endpoint auth 200/401 unit test (handler shipped; was untested).
- 307273f8 lift(R2): aggregator G lane-vs-full WPA totals on /api/post-game-wpa (was FUTURE in PM2).
- 391191be feat(ci): CI Watchdog item 204 BUILT (auto-merge / cancel-on-newest-HEAD /
  core.bridge.send escalation; 19 tests). NOT live-armed (an unattended auto-merger must not race
  the run building it). ARM step in docs/CI_WATCHDOG_PLAN.md; operator's 3 Qs answered + pinned.
- ae47d0eb docs(ds): Tier-2 report-first (ops/audit/ds_cross_eval/TIER2_REPORT.md). Shaco the only
  clean ARAM-override CONFIRM (+26.9pp); B kit-aware-DPS strongest + actionable (B1 melee-gate
  structurally confirmed - no range gate in dps.py/hybrid.py); F2 confirmed across 66 champs. No
  engine change (gated on verifier + operator).
- 917cbb89 feat(hz-b): engine-less --static build-order regen (precompute + variants); in-process
  via server _POST_ROUTES, byte-identical to live (diff-verified). Patch regen no longer needs :8893.

DEFERRED / NEXT:
- S4 D11 assert->if-raise sweep: judgment-heavy (validation-vs-sanity across 405 asserts; DS asserts
  Tier-2). Do fresh, not under headless context pressure.
- Parked for live aram/sr games: HZ coach FLIP, DS default-ON flag-flips, Electron capture, DS
  calibration, Cherry Arena-1750 verify.
- Gemini-gated: P6 G3/G6/G7, per-champion full cross-eval (~170 agents).
- B1 melee-gate = highest-value DS Tier-2 follow-on (gated on verifier + per-champion re-rank).
- ops/loop/config.json + director_prompt.md STILL uncommitted (operator pre-run loop tuning; left
  untouched PM2 + PM3).

