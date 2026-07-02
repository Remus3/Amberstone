# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) + 2026-06-29 WP-D1 session (full in LEDGER 670) + R47 UI-audit cycle 16 (2026-06-30, full in LEDGER 702) archived. Only the last 3 sessions kept here.

---

# 2026-07-01 late night 3 (live-gated-sync full resync + operator decision queue + drain tooling; docs/meta, NO ENGINE/DS/Share)

Operator-directed: refresh docs/LIVE_GAME_GATED_SYNC.md (consolidated headless-impossible checklist) + build reusable drain tooling + answer a local-AI question. Fable-5 orchestrated 46-agent Workflow (11 doc readers + repo grep sweep + git-evidence + seam-flag ground-truth + adversarial done-verify + verifier gate PASS). LEDGER 734.

- **Resync (`26aba81f`):** removed 4 confirmed-done (overlay 598, boots PM7, vision self-heal 685/688/711, packaging), added 78 -> 108 open (86 one-shot + 14 accrual + 8 parked). Every open row env-tagged. Drain: S1 practice SR / S2 real SR / S3 ARAM Mayhem / S4 Arena. ARENA NEEDED: YES (8 items). Est 4 sessions. Ledger section preserved + 1 SYNC entry.
- **SEAM GROUND TRUTH (code-verified):** ZERO seams wired-on-live. DSP2/DSP11/F2/RF1-3 transport-plumbed, callers omit; DSV/DSP4/DSP8/B1/R50-53/Phase-D engine-only; DSP5/6/7+P3.2 producer/test-only; RC_COMP_HP_LEAN + RC_LANING_CV_SERVED cold.
- **Decision queue (`df75d18c`):** docs/OPERATOR_DECISION_QUEUE_2026-07-01.md - 12 decide-now + 7 review-first, pro/con/rec each. Top-3 (DSV5 flip ON, DSP11+RF1 flips, doc housekeeping) clear ~35 rows with NO game.
- **Tooling (LOCAL, gitignored .claude/):** /live-gated-drain command (fable-limit -> opus-4.8 max/ultracode fallback; worktree merge/prune + /done + next-session prompt) + live-gated-resync saved workflow (verifier JSON schema-forced - the live re-gate output was unparseable).
- **Local-AI analysis (chat + BACKLOG line):** Gemini used in 3 roles - ask+audit already on flash (near-free), ONLY the headless-loop director uses premium gemini-3-pro-preview. Context is CURATED not full-repo (audit ~17K tok deterministic + agentic self-reads bounded by .geminiignore; director ~30-40K tok capped). Swap plan (RC_LLM_BACKEND switch, free-tier ask+audit first, ensemble on advisory roles) logged to BACKLOG.
- Do NOT redo: the resync is fresh as of 2026-07-01. Next = operator works the decision queue (start DSV5 flip ON).

---

# 2026-07-01 late night 2 (OQ13 - QA17 mode-factored weekly Good/Bad/Ugly digest; backend + ui, NO ENGINE/DS/Share)

Loop directive OQ13 executed by this session (merges `4d2955f4` + `22cc3e80` + audit-fix `acf54c4d`, LEDGER 733). Premise live-verified BEFORE build (ARAM 7d 11.7 deaths/game + 2.0 CS/min vs SR 8.8 + 6.6 - mode-blind tips mis-grade ARAM). 2 parallel worktree agents on disjoint files to a frozen weekly_digest contract -> verifier CONFIRM each (A 24 / B 17 fresh) -> sole merger --no-ff.

- **Backend (`c84d51af`):** _MODE_BENCH (SR strict 3.0/6.0/6.0; ARAM lenient 2.5/12.0/None, CS never judged; ARENA/BRAWL lenient; default) + pure _home_weekly_digest(rows); rows collected in the EXISTING week-cutoff loop (0 new SQL); games<=2 R30-style suppression; "" = suppressed line. KEYSTONE test: identical stats -> ARAM bad=="" / SR "10.0 deaths per game (bench 6 for SR)".
- **Frontend (`128635c4`):** #home-weekly-digest card sibling AFTER #home-combo (combo.hidden is pick+trends-coupled - nesting would suppress); createElement/textContent only; dataset.sig idempotent; tokens-only CSS.
- **Proof:** full RC suite fresh on merged main 10399 passed / 2 skipped / 193 subtests (+35 = new 18+17); RC restarted pid 15840 alive/reload_ok; LIVE /api/home/summary: ARAM 23g lenient (bad suppressed, good "2.6 KDA over 23 games") vs SR 10g strict (bad "8.8 deaths per game (bench 6 for SR)").
- **5-phase audit PASS 0 MUST-FIX.** Both SHOULD-FIXes fixed in-slice (`acf54c4d`): head deduped to THIS WEEK BY MODE + ui_mock weekly_digest block (fixture flapped live-then-hide). NICE FUTURE: pre-existing U+2192 home.css:545 (next drift sweep).
- **OPERATOR MID-RUN CORRECTION:** "why is the chrome dashboard being used?" - audit agent had been told to render :8888 in Chromium (old OQ8/OQ12 fixture precedent). Redirected mid-flight: sanctioned = rc-shell Electron capture or ?overlay=1. Result: rc-shell NOT running + ?overlay=1 hides #home-overlay BY DESIGN (overlay.css:80) -> code-side phases complete, **Electron-companion capture OWED**. Rule reinforced: NO Chrome :8888 renders as visual proof, ever.
- Remaining OPEN queue: OQ14 (Item Shaper knobs), OQ15 (GPI radar dot).

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
