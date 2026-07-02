# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-01 late night (OQ12 - QA31 PGR normalized carry-metrics bundle; ui + backend, NO ENGINE/DS/Share)

Loop directive OQ12 executed by this session (merges `12958b47` + `94c8224c`, LEDGER 732). Full orchestrator pattern: Explore recon -> Plan spec (citations spot-verified + live rewind DB schema probe) -> 2 parallel worktree agents on disjoint files coding a frozen payload contract -> verifier CONFIRM each -> sole merger. Operator interrupted mid-run ("complete + summarize open items") - slice finished per protocol, then wrap.

- **Backend (`5e27b452`):** dmg_share_pct producer; scripts/build_carry_benchmarks.py (rewind DB read-only -> COMMITTED data/coach_reference/carry_benchmarks.json, 44 groups role-or-mode x short/mid/long/all, min_n=50); core/carry_benchmarks.py reader (fallback chain + band fences); builders_last_match.py appends dmg_share_pct + carry_normalized END-of-payload, fail-soft.
- **Frontend (`2782e87e`):** 5 hidden bench sub-line spans (3 live grid + 2 hpgr), _setBenchSub "HIGH - p50 26" on --signal-good/bad, idempotent + old-payload-silent; tooltip " vs <bench_key> (n=N)" from stashed ttBase.
- **Proof:** full RC suite fresh on merged main 10364 passed / 2 skipped / 193 subtests; RC restarted pid 18564 alive/reload_ok; LIVE /api/last-match (real Vayne SR): BOTTOM|mid, kp 67.0 vs p50 48.4 HIGH, gold 29.8 vs 21.5 HIGH, dmg 36.1 vs 22.2 HIGH.
- **5-phase audit MUST-FIX NONE.** SHOULD-FIX FUTURE: stat-row baseline misalignment when subs unhide (reserve sub slot or top-align, last_match.css:388). NICE: tooltip n = kp n on all cells; hpgr helper duplicated. **Electron-overlay pixel capture OWED** (no live game).
- **Corpus caveat:** benchmark percentiles reflect the rewind DB rows at build time - regenerate carry_benchmarks.json after rewind catchup runs.
- Remaining OPEN queue: OQ13-OQ15.

---

# 2026-07-01 night (R56 gemini-loop DIRECTOR REFILL - coach_decisions + trigger_pill 5-phase fixture audit; ui, NO ENGINE/DS/Share)

Loop directive R56 executed by this session (`2f259dcb`, LEDGER 731). Inline (2 small panels, directive-sanctioned) with RED-first grep-contract lock.

- **MUST-FIXes:** 9 sub-floor hardcoded font-sizes tokenized in coach_decisions.css (11-17px -> var(--fs-md/sm/xs)); map_state.css .trigger-pill 17px -> var(--fs-sm); .coach-decision-btn ~30px -> min-height var(--hit-min, 42px) + var(--radius-sm).
- **STRUCTURE find:** #recent-coach-calls markup left index.html at s162 lobby v2 (832704a7) - module polled /api/decisions/log every 30s into a null render forever. Poll now gated on section presence; wiring preserved. Restoring a /coach-calls page = operator-gated FUTURE.
- **Adjacent latent red:** OQ16 objective_gauges.css header comment carried a 0-leading hex breaching the OQ6 dark-values ratchet (ceiling 0). Ratchet runs ONLY in the nightly full suite (push CI = light check job) - tonight's nightly would have gone red. Hex dropped from the comment in-slice.
- **Proof:** RC suite fresh 10309 passed / 2 skipped / 193 subtests; computed-style proof (title 22 / sub 18 / btn 18 + 42px / pill 18) via the :8810 static-preview synthetic-DOM path (item 656); live :8888 curl-verified serving tokenized CSS (ADR-008, no restart).
- **FUTURE:** ds-pill/augments-pill 21px hardcoded (siblings, out of scope); dead body[data-view="coach-calls"] rules in header.css.

---

# 2026-07-01 evening (loop false-NO_WORK fix 2 + GEMINI CREDITS DEPLETED; direct-executor continuation)

Operator re-invoked /gemini-headless-upgrade pointing at ops/loop/control/directive.md. Directive was STALE (OQ3, already shipped e14eedbd + docs 7f1dccee) - NOT re-executed. The 17:45 relaunch had STOPPED again on "NO_WORK / empty" with OQ11-OQ15 OPEN. Full detail LEDGER 728.

- **ROOT CAUSE (reproduced, stderr captured): Gemini API prepay credits DEPLETED** - 429 RESOURCE_EXHAUSTED "Your prepayment credits are depleted", gemini CLI exit 1, stdout 0B. **OPERATOR: top up at https://ai.studio/projects, then relaunch via PART A.** The loop CANNOT run until then.
- **LOOP FIX 2 (LEDGER 728):** gemini() no longer masks errors as NO_WORK - stderr captured to control/_gemini_err.txt + head logged on empty tries; empty output -> None sentinel -> director ADVANCES (same-sha guard still ends persistent outages); stop only on literal NO_WORK. TDD RED 2 -> GREEN, loop suites 34 passed.
- Credits TOPPED UP mid-session (operator message); gemini liveness re-probed PONG. Loop relaunch after the in-flight slices merged.
- **OQ11 DONE (`aa9c7d90`, LEDGER 729): ENGINE 1.166.0** - static-CD haste gate (first ability_static_cd consumer; plain-number-static only; Amumu Q/Heimer R pinned ungated, Samira R 3.4483 -> 5.0). Dual suite fresh on main: DS 7733 / RC 10274, 0 failed. DS :8893 bounced -> 1.166.0. Share ingest bundle rebuilt (full ds_share_sync).
- **Operator picked OQ3 variant A** -> OQ16 built live same session (`a5d2719a`, LEDGER 730): objective_gauges overlay widget at (1690,320), SR-live-only, schedule mirror-pinned vs event_callouts. **Live in-game overlay capture OWED** (no game was running).
- Remaining OPEN queue: OQ12-OQ15.
