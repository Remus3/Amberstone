# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) + items 366-369 (2026-06-09 DS-patch-refresh prune) + item 371 (2026-06-09 BACKLOG-batch T1F3/T2F4 prune) + item 376 (2026-06-10 prune) + item 387 + round 2026-06-10-02 + item 394 + audit-cycles-1-5 + cycle-6/item-400 + cycle-8/item-402 + cycle-9/item-403 + cycle-13/item-407 + cycle-14/item-409 + cycle-17/item-412 + cycle-18/item-413 + item-414 + item 434 + cycle 47 (2026-06-11/13/14/16 prunes; full per-cycle records live in docs/LEDGER.md) archived. Only the last 3 sessions kept here.

---

# 2026-06-23 (R22 DIRECTOR REFILL) - det_coach_shadow agreement aggregator (Haiku-to-ZERO)

Re-probed live state (mode=client / liveclient null - no game), so both carry-forward live-gated
lanes (RC_COMP_HP_LEAN AP-mage-vs-2+-tank eyeball; live overlay eye-line + S0-pulse) were no-ops
this cycle -> headless lane. Interviewed the gemini director (gemini-3-pro-preview, ops/loop/
loop_controller.gemini() pattern); it picked a Haiku-to-ZERO agreement instrument. Commit 8470c3cc
(pushed). Tier-1 tooling (2 new files; no engine/DS/Share/ENGINE_VERSION; pre-commit hook skipped
Share sync, confirming Tier-1).

VERIFY-THE-PREMISE payoff (audit-proposals-are-intent): the directive's premise ("no aggregator
exists") was GLOBALLY false - hz_shadow_report.py + hz_mismatch_diagnose.py + live_benchmark_band_
report.py already aggregate other shadow logs. But it held for the SPECIFIC target: an inventory
(ls data/*shadow*.jsonl + grep readers) found det_coach_shadow.jsonl (22,344 rows, the LARGEST
shadow log, the B1 deterministic-coach flip substrate) had a WRITER (core/det_coach_shadow.py) and
NO reader. Re-derived the real metric: det A-choice is always ds-matchup (laning trade) but native
(Haiku) A-choice is overwhelmingly macro/objective (wave-tempo/objective-*), so a naive label-match
would false-0% (the cycle-53/item-574 category error). New tools/det_coach_shadow_report.py
classifies each side's DOMAIN off source_tag (trade/build/macro) -> domain ALIGNMENT rate (headline
do-not-flip signal: 2% live - Haiku is mostly macro at these ticks), within-trade verdict agreement
(cross-domain EXCLUDED as domain_divergence, never diluting the denominator; 0/159, Haiku plays
safer "Farm safe"), build-item overlap (3.1%), coverage. Default flip-hint HOLD. Mirrors
hz_shadow_report.py conventions. RED-first hermetic test (mock jsonl in tmp; real file gitignored)
20/20; verifier-gated CONFIRM (9/9 checks).

NEXT: overlay-polish lane stays DRAINED + RC2 tail exhausted; next unit is another gemini-directed
NON-DS-scorer refill. SAME-LANE off-lane refills ready: macro_response_shadow.jsonl (18,192) +
objective_playbook_shadow.jsonl (18,858) are the next un-aggregated shadow logs (same domain-aware
pattern). Carry-forward live-gated lanes still OWED (need the RIGHT live game): RC_COMP_HP_LEAN
default-ON eyeball (AP mage vs 2+ tanks) + live overlay eye-line + S0-pulse capture. The DS
scorer-valuation track stays CLOSED (do NOT re-pitch kill-state/carry_share or AP-DoT).

---

# 2026-06-22 (R21 DIRECTOR REFILL) - ARAM balance-grid UI audit + visual OWED cleared

Bootstrapped, re-probed live state (a live SR practice game was up: mode_key=sr, coach.champion=
Jinx - an ADC). Interviewed the gemini director (gemini-3-pro-preview, ops/loop/loop_controller.
gemini() pattern) for the next NON-DS-scorer unit -> it picked Rotation-3 UI audit + populated
capture of the R20-shipped ARAM balance-adjustment grid panel (the VISUAL OWED). Live game was an
ADC so both carry-forward live-gated lanes were no-ops this cycle (the RC_COMP_HP_LEAN eyeball needs
an AP mage vs 2+ tanks; the overlay band-channel was already captured in the prior Caitlyn game) -
the headless UI unit was the right pick. Ledger 594, commit bd961b39 (pushed). Tier-1 frontend (no
engine / DS / Share / ENGINE_VERSION change; asset-hash hot-reload per ADR-008).

VERIFY-THE-PREMISE payoff (audit-proposals-are-intent): the directive tagged it Tier-2; corrected to
Tier-1 (JS/CSS presentation). The probe found the STRUCTURAL reason the capture had been OWED:
renderAramBalance was dispatched in the LIVE-state render branch ONLY (web/js/main.js ~L1431); the
ui_mock active-match branch (L1392-1411) wired every sibling panel (ward/spike/minimap/objective
chips) but NOT renderAramBalance, so the documented ?ui_mock=1&mode=aram#active-match audit/capture
path (the sanctioned headless path per test_active_match_view.py) could never render it. ROOT-CAUSE
FIX: wired it into the ui_mock branch too (mode + roster from the active_match_aram.json fixture,
which already carries a 10-champ roster). The documented audit path now renders it; on the live :8888
dashboard the real /api/aram-balance 134-champ map populates it.

5-phase fixture audit (read-only subagent, UI Fixture Ritual) = CLEAN (typography all >= floor on
--fs-xs 16 / --fs-sm 18; read-only panel so HIT-TARGETS N/A; ASCII clean; self gold-edge reads
first; ally-blue vs enemy-red-bg distinct; buff/nerf by BOTH color AND the +/- sign, WCAG 1.4.1).
Applied its one SHOULD-FIX in-slice: .ab-chip off-grid 2px vertical pad -> --space-1 4px (8px-grid).

VERIFY: RED-first tests/snapshot_panels/test_aram_balance_view.py - static wiring guard (both
branches; RED at 1 call site) + Playwright populated capture (stubs /api/aram-balance, asserts the
self gold row + >=4 enemy + >=9 total + both buff/nerf chips) -> screenshots/aram-balance_aram.png
(649x429, all 10 rows). GREEN 3/3 after the fix. Full tests/snapshot_panels/ + test_aram_balance_grid
= 204 passed (the main.js render-path edit is regression-clean); active-match view 8/8. Diff adds 0
non-ASCII bytes (main.js's pre-existing 4374 = un-swept smart quotes, a separate operator-gated pass).

NEXT: the overlay-polish lane stays DRAINED + the RC2 feature-lift tail is exhausted; the next unit
is another gemini-directed NON-DS-scorer refill (UI-audit / competitor-lift / haiku-zero / cost
rotation). Carry-forward live-gated lanes still OWED (need the RIGHT live game): the RC_COMP_HP_LEAN
default-ON eyeball (an AP mage vs 2+ tanks) + the live in-game overlay eye-line + S0-pulse capture.
The DS scorer-valuation track stays CLOSED (do NOT re-pitch kill-state/carry_share or a new AP-DoT).

---

# 2026-06-22 (DSV5 follow-on) - no-comp-info guard (RC_COMP_HP_LEAN flip prerequisite)

Continued the program with a LIVE SR practice game up (mode_key=sr; Jinx vs Lucian/Sion/Wukong/
Pantheon/Soraka = tanky_count 3, the qualifying 2+-tank comp). Interviewed the gemini director
(gemini-3-pro-preview via the `ops/loop/loop_controller.gemini()` pattern) for the next NON-DS-scorer
unit; it BLESSED the unit below (PART A/B/C) AFTER I verified the premise. Ledger 593, commit
e2de5043 (pushed). Tier-1 (`coach_integration/enemy_stats.py`, NOT frozen; NO engine / DS / Share /
ENGINE_VERSION change - the pre-commit hook SKIPPED Share sync, confirming Tier-1).

VERIFY-THE-PREMISE PAYOFF (again): a ground-truth probe (`ops/audit/ds_perm_swarm/dsv5_lean_probe.py`)
against the live comp exposed a real defect in the JUST-shipped DSV5 seam (item 592). `_comp_hp_scale`
computes `scale = 1 + 0.10*(tanky_count - 1)`, so with `RC_COMP_HP_LEAN` ON and NO enemy_champions
(tanky_count=0) it returned 0.90, NOT 1.0 - conflating "no comp data" with "all-squishy comp" and
contradicting its own docstring. The smoking gun: `test_no_comp_info_on_is_neutral` was NAMED for
neutral (1.0) + commented "-> scale 1.0" but its assertion had been bent to 0.9 to match the bug
(`feedback_subagent_fixture_shaped_to_bug`). The champ-select / preview routes (`routes_state`
ds-preview Path 3, ds-knobs, ds-relscore, ds-statcheck) ALL call `compute_enemy_stats(mode, level)`
with no comp, so a global default-ON flip would have silently de-rated every preview ranking by 10%.
The live in-game SR coach (`_coach.py:308-313`) DOES pass enemy_champions, so the intended tilt (live
comp OFF->ON max_hp 2210 -> 2652, x1.20) is correct + unchanged.

SHIPPED: `_comp_hp_scale` short-circuits to (1.0, 0) when there is no classifiable comp (None / [] /
all-blank); a REAL all-squishy comp (>=1 classifiable champ, 0 tanky) still earns the intended 0.90
discount, a tank comp still earns the uplift. RED-first: corrected the bug-shaped assertion to 1.0 +
3 new tests (blank-comp -> 1.0; no-info-vs-known-squishy contrast; env-ON-no-comp byte-identical); 4
RED confirmed (1989.0 != 2210.0), then 43/43 enemy-stats green; 68/68 ds-preview/knobs/relscore/
statcheck route-logic green (the lone teardown hermeticity error = the live RC pid 12264 appending
its own gitignored shadow logs mid-suite - all 5 paths git check-ignore'd, conftest redirects in-test
writes to tmp, so the external live process is the only possible writer). Ruff clean.

NEXT / OWED: gemini PART C ruled HOLD the `RC_COMP_HP_LEAN` default-ON flip for a separate operator-run
- this unit RESOLVES the preview-route safety blocker (documented in `docs/LIVE_GAME_GATED_SYNC.md`,
newest live-flip ledger entry). The DS scorer-valuation track stays CLOSED (do NOT re-pitch a
kill-state/carry_share or a new AP-DoT scorer). WAKEUP tail (UI feature-lift entry) is ripe for the
next weekly-hygiene relocate-trim (4 same-day entries now).
