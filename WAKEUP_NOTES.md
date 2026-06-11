# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

# 2026-06-10 - gemini loop cycle 4: false REGRESS audit refuted + gate edge pins [item 387]

Gemini-headless-upgrade executor cycle. Directive = FIX-FIRST regression: audit claimed the
item-386 `lc.get("champion")` gate shipped untested (conftest + gate tests "missing").
REFUTED by ground truth: c7922951 (merged via d446ea80, INSIDE the audited range
9ccc64fa..b5533f85) carries gate + tests/conftest.py + tests/test_hz_shadow_live_gate.py
(4 tests) in the SAME commit. Auditor diffed only tip commit b5533f85 (docs+data only).

- Verified fresh pre-edit: gate+wiring 12 passed at HEAD.
- Shipped `c5cf8b56`: +2 edge pins in test_hz_shadow_live_gate.py (champion="" loading-screen
  edge; non-dict lc isinstance guard). Test-only, no engine, no restart.
- Gates: RC 5789p/2sk/94st exit 0; ruff + hygiene clean; CI run 27315276398 green.
- LOOP IMPROVEMENT (FUTURE): loop auditor should diff prev-done-sha..new-sha, not the tip
  commit - tip-only diffing produced this false REGRESS.
- DON'T REDO: HZ shadow live-gate IS tested (6 tests); do not re-add gate tests.
- NOTE: RC pid drifted 14160 -> 3336 during cycle (supervisor bounce); alive+reload_ok true.

---

# 2026-06-10 - gemini loop: HZ-D4 charter sweep - shadow-pipeline root-cause fix + ARAM tables + agreement metric [item 386]

Gemini-headless-upgrade executor cycle. Directive = HZ-D4 (7-lever cost sweep + next HZ increment). Merges `d446ea80` + `b54d040e` (2 PARALLEL worktree agents, verifier-CONFIRMED). NO engine, no Share, no web/ touch; RC restarted pid 14160.

- 7-lever sweep: 7/7 CLEAN, no commit. Scout's lever-6 "orphan tasks" REFUTED by ground truth (all 3 flagged tasks point at on-disk scripts).
- ROOT CAUSE found verifying the table-expand premise: ALL 837 choice + 800 build shadow rows junk - enemy=null 100 percent (champ from PERSISTENT stale coach dict; enemy_team only in live liveclient -> idle ticks logged stale replays) + 290 Champ0 rows (pytest build_state runs appended to REAL data/ jsonls). Flip path could never accrue.
- FIX: live `lc.get("champion")` gate in both shadow_log_precomputed_* + autouse conftest SHADOW_PATH->tmp redirect (hz_choice/hz_build/det_coach); +4 gate tests; polluted jsonls rotated to _scratch/*.pre_item386.jsonl.
- ARAM tables full-roster 172 (every native capture is mode=aram): laning_aram 65.75MB LFS + build_orders_aram 688 + variants_aram 344 @16.12.1. GOTCHA: gen CLIs default to 10-champ seed; pass --champions <172-CSV from SR table scenarios keys>.
- hz_shadow_report v2 (item-369 tail): classify_verdict/record_agreement/summarize_agreement, per-mode agreement + uncovered_with_native; flip hint cites agreement rate; +22 tests.
- Gates: RC 5787p/2sk/94st exit 0; DS 7075p/1sk/1xf exit 0; ruff + ASCII clean.
- OPS: RC-Supervisor task was NOT running (restart_trigger sat unconsumed); schtasks /Run /TN RC-Supervisor restored; watch it next session.
- NEXT (gated): play real ARAM -> covered+native rows accrue -> hz_shadow_report agreement gate -> operator flip decision.
