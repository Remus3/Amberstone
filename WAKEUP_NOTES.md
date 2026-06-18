# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

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

---

# 2026-06-18 (PM2) - headless deep-research+lift: R2 competitor fan-out + Game Flow tab

Operator-direct /headless-upgrade run (deep-research+lift focus). Code commit `b17531e1`.

- **R2 competitor fan-out** (aggregator B / aggregator A / Aggregator Z1 / aggregator G, 4 parallel deep-dive agents).
  RC supersedes/has nearly the whole surface. **Verify-gate caught a wrong agent HAVE:** the
  aggregator G "win-prob match-flow curve" NOW pick is ALREADY shipped (`web/js/panels/pgr_winprob.js`,
  PGR S3) - the agent read only post_game_phases.js and missed the graph. Reclassified CLOSED.
- **SHIPPED F-DPM per-minute performance curve** (the one genuine own-data gap = Aggregator Z1's
  signature graph): `core/perf_curve.py` -> `/api/perf-curve?mode=&metric=&champion=` -> Build
  Insights "Game Flow" tab (inline-SVG dual win/loss line, gold/cs toggle). Avg cumulative
  gold/CS per game minute over the own rewind corpus, win-vs-loss split. Pure aggregation over
  timeline_frames, no global/Riot/Claude dep, no DS schema. TDD +42 (11 module + 18 route + 13
  DOM). Live aram/gold n=2004 (wins pull ahead by min5), sr/cs n=618. RC pid 22672. Tier-1.
- **Section-3b UI audit 5/5 CLEAN, 0 MUST-FIX.** **VISUAL CAPTURE OWED** (Game-PC :8892 down +
  Claude_Preview MCP not connected this session). Carry-forward.
- **FUTURE -> BACKLOG** (`docs/COMPETITOR_LIFT_2026-06-18_R2.md`): aggregator B carry-efficiency grade
  axes (gold_share verified 0 hits, Tier-2 grade re-baseline = product call); aggregator A OP-Score
  per-interval performance curve (new scoring model); DPM damage-per-min (cumulative-all-units
  trap, needs a to-champs frame field); aggregator G lane-vs-full WPA totals (marginal).
- **NEXT:** F-UGG1 carry-efficiency as a DISPLAY-only stat (LOW-risk, no grade change).
- **Still open from earlier today:** ops/loop/config.json + director_prompt.md modified
  (operator pre-run loop tuning) - NOT committed; review/commit/discard next session.

---

# 2026-06-18 (PM) - headless: nightly CI green (deps + Linux-portability) + section-4b flip-gate evidence

Direct /headless-upgrade run (the gemini loop I launched this AM self-stopped NO_WORK x2, so
operator-direct, not a director cycle). Commits `e33892c3` + `ee9c6b1c`.

- **P0 RED nightly-full-suite FIXED end-to-end.** The schedule-only nightly ran the whole tree
  on the pure-Python `check` job's minimal deps -> 7 collection ImportErrors (websockets /
  portalocker / PIL / json5). `e33892c3`: nightly `pip install -r requirements.txt` + declared
  the 2 undeclared prod deps (websockets==16.0, json5==0.14.0) + `workflow_dispatch`. Dispatch
  -> 15642 pass / 4 fail / 10 err (collection fixed). `ee9c6b1c` cleared the 14 Linux-portability
  residual: loop_controller config-load guard (CFG={} when the hardcoded C:\ path is absent; 10
  errors), ddragon _safe_basename + ntpath (1), prune junction skipif win32 (1), 2 DS concurrency
  _post transient-reset retries (2). **Nightly re-dispatch run 27769336101 (HEAD ee9c6b1c) =
  SUCCESS: 15655 passed / 50 skipped / 0 failed / 0 errors.**
- **P1 section-4b flip-gate evidence (offline, rewind_history.db replay):** ran all 3 replay
  flip-gates; NONE flip-ready -> Haiku stays the floor on all. Lane A laning ~50% (engine
  52-53%, table loses it); Lane B build-order +3.3% [-2.3,+9.0] (anti_tank carriers ~+9%, MOST
  PROMISING); pickban ~46-49% (no signal). NEXT lever = Lane B build-order anti_tank ordering.
  Artifacts ops/runtime/{laning_verdict,pickban}_validation.json.
- **P2 cost sweep CLEAN:** no sub-500ms net poll; cache_control present on all 14 coach callers.
- **Left for operator:** ops/loop/config.json + director_prompt.md modified (your pre-run loop
  tuning) - NOT committed; review/commit/discard next session.

---

# 2026-06-18 - Aggregator H R1 lift: win-rate-by-game-length Build Insights tab

Gemini DIRECTOR REFILL cycle (round-2 RF queue drained -> director synthesized R1: a
Section-7b heavyweight competitor deep-dive). Target = Aggregator H (not-yet-reviewed).
RC supersedes most of it; the one genuine gap shipped in-run.

- **SHIPPED F1 win-rate-by-game-length** (commit `e9f70e7d`): `core/duration_winrate.py`
  -> `/api/duration-winrate` -> Build Insights "Game Length" tab. Win % bucketed by match
  duration over the operator's OWN rewind corpus (no global / Riot / Claude dep, no DS
  schema change). Tier-1, no engine/DS/frozen. TDD +8; full RC suite 8349 passed exit 0;
  RC restarted pid 11712 (endpoint live; bogus mode -> 400).
- **VERIFY-GATE catch:** `matches.game_duration_s` has 4 ms-encoded/corrupt rows
  (MAX=1988073, clean 3600-100000s zero gap); MAX_DURATION_S=7200 + MIN_DURATION_S=300
  drop them. Live: ARAM n=2044 downward slope 56.2/51.1/49.4/48.2 (snowball tendency),
  SR n=683 peak 30-35m 60.2.
- **OWED (carry-forward):** live visual capture of the Game Length tab (Game-PC :8892 down +
  Claude_Preview cannot attach to RC-owned :8888 headless). Code-side 5-phase UI audit PASS,
  no MUST-FIX (1 SHOULD-FIX deferred: shared Min-buys control inert on the chart tab). Drive
  `?ui_mock=1#build-insights` -> Game Length tab when a visual path is available.
- Triage: F2 global win/pick/ban + F6 lobby-player-tags + F7 global objective/tier = FUTURE
  (new external dep; F6 already BACKLOG as Overlay App F 3.1); F3/F4/F5 CLOSED (RC at-parity or
  superior). Doc `docs/COMPETITOR_LIFT_2026-06-18.md`.
