# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-28 (overlay-build loop - WP-A6 remove CALL/FIGHT MODEL/MAP pane name headers; b089d130)

Headless overlay-build-continue cycle (docs/OVERLAY_BUILD_MASTER_PLAN.md Section J). Next OPEN W1 after A5: A6 (T1, deps A5 DONE). A1-A6 now ALL DONE - the A-section is complete.

- **WP-A6 (b089d130).** index.html ONLY (DOM removal, A4/A5 precedent - turned out no overlay.css edit, so no shared-file collision). Removed the CALL/FIGHT MODEL/MAP `<div class="am-pane-head">` title divs (pure titles, zero JS consumers). CDS: dropped only the `<span>CDS</span>` label, KEPT cd-ledger-head + cd-chev (cd_ledger.js wires the collapse click + chevron onto that head - removing it breaks collapse). BUILD untouched (its header holds am-draft-elo; -> WP-B1). Updated the existing DS-controls MountTests assertion (pinned FIGHT MODEL header present -> now asserts removed). RED-first tests/test_overlay_a6_pane_headers_removed.py 4->9 green. Tier-1, ADR-008 (no RC restart). LEDGER 658, Section J A6 -> DONE.
- **G.9 UI-audit PASSED (no MUST-FIX):** RC Web Static :8810 ?overlay=1#active-match: CALL/FIGHT MODEL/MAP hasHead=false, BUILD hasHead=true+am-draft-elo, CDS head+chev present + "CDS" text gone; imported cd_ledger.js + attachCooldownLedgerHandlers() + clicked head -> collapse round-trips (chev - <-> +, pane cd-collapsed toggles). Verifier CONFIRM (A6 9/0).
- **PRE-EXISTING (do-not-chase, NOT A6):** 4 [data-panelset] overlay.css drift failures + 1 AsciiHygiene collection error (task_72ca84ec) - PROVEN pre-existing by stash (web/index.html + the ds_controls test stashed -> the same 4+1 fail identically on HEAD; A6 edited NO overlay.css). Local sweep 110 passed.
- **NEXT (loop):** Section J next OPEN W1 = B1 (strip DS-ENGINE caption + "No Draft prior", T1, active_match.js - foundational for B2/B3; serialize ALL of Section B on active_match.js). Then C1 (kit-synergy, W2). E5 (docs sweep, T0) + F5-H02/F5-M01 (W0) still open.

---

# 2026-06-28 (overlay-build loop - WP-A5 enemy-spells drop name + full aligned champ names; 69a3929f)

Headless overlay-build-continue cycle (docs/OVERLAY_BUILD_MASTER_PLAN.md Section J). Next OPEN W1 after A4b: A5 (T1, deps none).

- **WP-A5 (69a3929f).** enemy_spells.js: removed _shortChamp (9-char slice) + the .es-head "ENEMY SPELLS" title; render full champion names. _buildRows computes maxLen over the roster and sets mount --es-champ-ch = maxLen+1 so every row's name column shares one width (chips align). overlay.css: dropped .es-head; max-width 230->360 (a CAP, content-driven so short-name rosters stay compact); .es-champ flex:0 0 58px+ellipsis -> flex:0 0 auto + min-width calc(var(--es-champ-ch)*1ch), no clip. .es-chip ellipsis unchanged (out of scope). RED-first tests/test_overlay_a5_enemy_spells_unname_widen.py 13->15 green. Tier-1, ADR-008 (no RC restart), no ENGINE/DS/Share. LEDGER 657, Section J A5 -> DONE.
- **G.9 UI-audit PASSED (no MUST-FIX):** RC Web Static :8810 + synthetic 5-enemy roster (incl "Nunu & Willump") + preview_inspect; names full + un-clipped, all five name columns 157px, first chips aligned same x, --es-champ-ch=15, no es-head. Verifier CONFIRM (A5 15/0, regression 33/0); local sweep incl overlay snapshot = 101 passed.
- **GOTCHA (do-not-redo):** the Claude_Preview browser CACHES ES modules across preview_start/stop cycles - the first A5 render served the STALE A4b-era enemy_spells.js (truncated names, es-head present). Fix = cache-bust the dynamic import: import('/js/panels/x.js?bust='+Date.now()). Captured in memory reference_claude_preview_live_8888.
- **NEXT (loop):** Section J next OPEN W1 = A6 (remove pane name headers, deps A5 now DONE -> READY; index.html + overlay.css, serialize overlay.css after A5), then B1 (strip DS-ENGINE caption, T1, active_match.js). C1 (kit-synergy, W2) + E5 (docs sweep, T0) + F5-H02/F5-M01 (W0) also open.

---

# 2026-06-28 (overlay-build loop - WP-A4b stats panel vertical "You vs benchmark" frontend; 14effd16)

Headless overlay-build-continue cycle (docs/OVERLAY_BUILD_MASTER_PLAN.md Section J). First OPEN W1 WP whose deps are DONE: A4b (T1, deps A4a DONE). The frontend half of WP-A4, consuming last cycle's /api/role-bracket-bench.

- **WP-A4b (14effd16).** Full rebuild of web/js/panels/stats_panel.js: dropped the panel name + HP/mana bars + 6-stat grid; new vertical "You vs Avg" table. Header = role <select> (top/jungle/mid/bot/support -> route role param) + auto-derived game-time bracket (lc.game_time_s; <1500s early / <2100s mid / else late, mirrors core.role_bracket_bench). 4 rows LVL/CS/TF/KDA. You = live lc.* (KDA=(k+a)/max(d,1) from the "k/d/a" string); Bench = /api/role-bracket-bench stats.<k>.avg, champ_benchmarks-style (role,bracket) cache+TTL+inflight, degraded "-" on error. overlay.css: max-width 190->220, bar/grid rules -> vertical table (You white-.96/bold vs Avg white-.62 = opacity compare signal, colorblind-safe). RED-first tests/test_overlay_a4b_stats_vertical.py 17->20 green. Tier-1, ADR-008 (no RC restart), no ENGINE/DS/Share. LEDGER 656, Section J A4b -> DONE.
- **DO-NOT-REDO / gaps:** (1) TF (kill-participation) has NO live producer (Live Client API, reference_liveclient_no_hud_data) -> You TF cell is an honest "-"; the benchmark column still shows historical KP. (2) renderStatsPanel(lc) consumes the DERIVED liveclient_summary shape (hp_max/game_time_s/kda/level/cs), NOT the raw envelope -> the active_match_sr.json ui_mock (raw shape) does NOT render the panel; live /api/state is its feed. (3) index.html:2206 #am-statspanel mount already correct - no edit. (4) the plan's web/js/test/*.test.js paths do NOT exist; overlay panels are tested by Python grep-contract tests in tests/ (no jsdom/node harness).
- **G.9 UI-audit PASSED (no MUST-FIX):** RC Web Static preview (:8810) + synthetic derived lc inject (no live game) + preview_inspect computed styles; bracket="early" from game_time_s=1320, You KDA=6.5 from "5/2/8", zero console errors. Verifier CONFIRM (A4b 20/0, regression 41/0); local sweep incl Playwright overlay snapshot = 87 passed.
- **NEXT (loop):** Section J next OPEN W1 = A5 (enemy-spells widen+unname, T1, deps none), then A6 (remove pane name headers, deps A5), B1 (strip DS-ENGINE caption, T1). C1 (kit-synergy, W2) + E5 (docs sweep, T0) also open. Serialize overlay.css edits A5->A6 (shared file; A4b already off overlay.css this cycle).

---

(older sessions relocated to `docs/history_notes.md` - 2026-06-28 WP-A6 /done prune)
