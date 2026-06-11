# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 (2026-06-11 prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-11 - DEEP-AUDIT cycle 1: P0 BASELINE re-derived + verified [item 395]

Charter cycle (docs/DEEP_AUDIT_CHARTER.md). Gemini's prior "P0 done" synopsis was unstamped + wrong (42209 files / 7451 tests claimed; live = 30398 files / 15167 tests) -> ruled STALE, re-derived everything from live probes.

- Baseline shipped to ops/audit/: P0_INVENTORY.md (30398 files / 4350.5 MB; tracked 2896 / 409.3 MB), p0_pytest_baseline.txt, p0_dashboard_reference.jpeg, P0_WORKMAP.md (P1-P8 seeds, cited).
- Model: claude-fable-5[1m] probe ACCEPTED headless -> set in .claude/settings.json (untracked).
- truth_gate LIVE CATCH: default `py -m pytest` hit the pytest-less pythoncore-3.14-64 interpreter -> suite zeroed -> blanket REFUSE. Fixed (canonical Programs/Python314 pin + sys.executable fallback, RED->GREEN regression test, 19/19). Gate re-run PROCEED 15168p/0f exit 0 + CI success.
- INTERPRETER DUALITY is now a P2 seed: sweep every bare-`py` suite invocation (hooks, skills, docs, scheduled tasks); decide fleet pin (py.ini vs absolute).
- RC-VisionServer schtask exits 1 but vision serves in-process fine -> vestigial task, P2 reconcile seed.
- Desktop synopsis rewritten ASCII/BOM-free, handoff log now sha-stamped (was BOM'd + unstamped).
- NEXT CYCLE: P1 STRUCTURE per synopsis (relocations, _scratch/.bak scrap triage, web/ PNG mirror + logs retention + python-embed consumer eval, CLAUDE.md context-budget trim).

---

# 2026-06-10 - insights fold-in + drainer hardening [item 394]

Operator fed the /insights report suggestion-by-suggestion; dedup-first per pattern (2 of 4 = already shipped).

- Suggestion 1 (re-verify greens): DUPLICATE of CLAUDE.md Verification Discipline - no-op.
- Suggestion 2 (API-surface grounding): NEW -> CLAUDE.md Testing Discipline rule `b8c0695b`.
- Suggestion 3 (truth-gate): NEW `tools/truth_gate.py` + 17 tests `d657c1f6`; live demo PROCEED 15147p/0f/7s CI-green 4/4 CONFIRM; wired verifier.md + both headless skills.
- Suggestion 4 (drainer): manifest/resume/headless_run.ps1 ALREADY SHIPPED (dedup); NEW = hard pre-commit gates in both skills (UI-audit + drift-guards + truth_gate exit 0 block the push; .claude local). Drain triage: only headless-actionable item was item-211 `--trust-lcu CHAMP` + `--match-id` (RED->GREEN 9 tests); rest of ROADMAP = operator/live-gated; item-210 unify = FROZEN lcu_client.py, deferred.
- LW block relocated LEDGER-top -> history_notes above item 278 (`160de74e`); LEDGER header append rule fixed.
- OPERATOR DECISION OWED: item-211 7 residual rows - run --trust-lcu per-row (needs lcu_champ list) or clear-as-junk.
- Truth-gate EARNED ITS KEEP same session: round 2 REFUSED on the LW relocation breaking `test_constraint_single_source` (1f/15155p) - guard re-pinned to LW-in-history; round 2b PROCEED 15157p/0f. Gate claims now utf-8-sig (PS BOM).
- precommit_gate was DEAD on this fleet (Bash-only matcher vs CLAUDE_CODE_USE_POWERSHELL_TOOL=1) + wrong-tree root on `git -C` + no py_compile: all fixed, PowerShell matcher added, 25 tests, live exit-2 proofs (glyph + syntax). First real PowerShell-tool commit after this note = harness firing proof.
- Patch-update SWARM directive encoded in memory reference_patch_refresh_workflow (all upstreams incl lolmath/101.qq/aggregator B + cohorts + merge-arbiter + coverage report).
- Gotchas: PS5.1 here-string commit messages with embedded double quotes break native arg quoting (`error: unknown option '-'`) - keep messages quote-free; PS5.1 pipes to native exes prepend a UTF-8 BOM (broke truth_gate claims AND precommit_gate stdin).
- OVERNIGHT HANDOFF: operator directive captured VERBATIM-intent in `docs/DEEP_AUDIT_CHARTER.md` - the standing deep-audit program (P0-P8: full-tree audit/refactor, frozen+history+gist+md-rewrite AUTHORIZED, vanguard/2pc prune, BOM retro-sweep, HZ-to-ZERO completion, Electron overlay to full replace web dashboard, gemini answers scope questions NOT operator). Loop armed: config max_cycles 100, gemini rail 200, directive_suffix -> charter; Desktop RC_DEEP_AUDIT_SYNOPSIS.md seeded; effortLevel xhigh set. NEXT SESSION = audit cycle 1 (P0 baseline). League client + dashboard left OPEN on screen per operator for UI/UX phases.

---

# 2026-06-10 - operator headless-upgrade round 2026-06-10-02: items 388-393 (6 slices, 9 pushes) + 2 live operator interrupts fixed same-session

Operator: "start any open for live game gating + other items parallel orchestrated to the end". 4 worktree agents + verifier gates on every merge; 2 mid-run operator reports root-caused + shipped while they played.

- item 388: drift probe NONE (16.12.1/25.15 all == sentinel; calc-site chunks unchanged); ARENA HZ tables full-roster `fb66722f` (HZ shadow armed sr+aram+arena; gen CLIs need CANONICAL ids - display names skip 6783 pairs); item-211 orphans 12 -> 7 (chain class, 5 MOVEs + 3 re-stamps; FUTURE --trust-lcu).
- item 389: summoner-spell WPA = 4th build_insights tab `6585b77a` - WPA lane COMPLETE; UI audit 5/5 PASS; proof _scratch/spells_tab_proof.jpeg.
- item 390: item-208 carry CLOSED `2784db8f` - range-gate at the REAL chokepoint core/daemon_slayer_client.py:1147 (ROADMAP fn was phantom) + 89-row backfill + guard.
- item 391 (OPERATOR INTERRUPT "champ select slow"): 3 commits ff4d59d1/69cb9dde/9e90c28d - :8889 single-thread -> ThreadingHTTPServer; stage WARN pinned deterministic=692ms inline matchup per 5s bucket; warm-path async single-flight fix. LIVE PROOF /api/state 3-30ms during a running game (was 700ms). Instrumentation permanent.
- item 392 (OPERATOR INTERRUPT "active match devoid/wrong/map dead/cds unneeded"): `138d4740` - map text layers render w/o coords (Live Client position = ROLE STRING, never coords - live-proven on :2999); DS rerank got items=null ALL GAME (items_display only) -> _amOwnedItemIds itemID path + gold>=2000 completed-count + canonical id bridges x3 routes; cds rail visual-only hide (wiring + overlay threat re-show kept). Proof _scratch/active_match_reflow_proof.jpeg.
- item 393 (OPERATOR DIRECTIVE 6-axis sweep): `91b6b847` - 1385 rows, 901 refilled / 42 trimmed / 15 stripped, SR 364x7 / ARAM 512x6 / Arena 509x6 zero exceptions (verifier independent probes), regen invariants + 1549-case guard; 16 ambiguous rows REPORT-ONLY for operator review.
- ROADMAP stale fixes: item-212 minors STALE-SHIPPED; DS-6-bucket medium entry was drift (wired 231-234); item-208 closed; item-211 residual recorded.
- OWED live: map roster ticking / DS pill+pips / minimap-crop self-grab fallback on a real game; Electron packaging + in-match overlay capture (carry).
- DON'T REDO: Live Client position is a role string (no coord dots from :2999 ever); pre-06-10 shadow rows junk; WPA lane closed; 16 ambiguous loadout rows need operator, not a strip.
- PRACTICE-TOOL note: coach.action/immediate empty in PRACTICETOOL while choices/callouts/lead populate (prose coach dark there; deterministic surfaces carry the page) - characterize-or-accept next session.

---
