# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-08 - HZ-A1 Lane A laning-scenario precompute (Haiku-to-ZERO) [item 352]

gemini-headless-upgrade loop, directive HZ-A1 (first HZ-* fanout off the 2026-06-08 ORCHESTRATION_PLAN reseed). Commit 85b13b7c. BUILD + PERSIST + READ only, NO live coach flip (charter 4b do-not-flip-blind).

- **NEW `core/laning_scenario_precompute.py`** precomputes laning `trade`/`all_in`/`back_off`/`even` verdicts over (my_champ x enemy x level-band x mana-state x cd-state) from the SHIPPED `compute_matchup` engine. Generator (`compute_cell`/`generate_table`) + fail-soft mtime-cached reader (`load_laning_scenarios` + `lookup`) + CLI; atomic versioned JSON -> `data/daemon_slayer/laning_scenarios/<patch>/laning_scenarios_<mode>.json`. Dims: 4 bands (L2/L6/L11/L16) x mana full/low x cd all_up/no_ult. mana low = affordable combo prefix from `mana_sim` per-cast cost ledger (manaless -> low==full); cd no_ult drops R.
- **Model fix (the de-risk probe caught it):** enemy modelled at FULL resources (`sequence_b` = full rotation) so a same-level mirror is symmetric (even); the first cut left the enemy on the engine default (AA, no E) and skewed even the mirror to back_off -0.10.
- SR seed = 10-champ archetype-diverse SAMPLE (not a tier list), itemless, 1600 cells / 667KB; dist even 793 / back_off 696 / trade 111 / all_in 0 (0 all_in is HONEST for itemless equal-level - needs full HP removal; surfaces with an item axis, HZ-A2). +16 characterization tests (cell == compute_matchup). verifier CONFIRM 16/16.
- Fixed a PRE-EXISTING red (NOT my slice): ROADMAP.md 82898 > 81920 doc-budget -> relocated shipped item 344 verbatim to ROADMAP_HISTORY (-> 79228). Full RC 5316 passed / 1 skip / 0 fail. ENGINE 1.120.0 untouched, no DS / Share / RC restart, no web -> no UI-audit.
- **NEXT OPEN = HZ-A2** (recall/back-timing + power-spike-ETA). The table is read by a FUTURE consumer (HZ-C1); validate on a real/replayed game BEFORE any coach flip.

---

# 2026-06-08 - vision :8889 false-alarm probe fix + cdragon hard-tail CLOSED [item 351]

"start the next open items in parallel" -> 2 parallel tracks (vision anomaly + cdragon NEXT-UP #1), both resolved. Commits 7f49499d (fix) + d2ecf125 (docs); CI green both.

- **Vision :8889 = FALSE ALARM.** Session-start "vision server :8889 not listening" was a probe artifact: server UP (PID 2108 moon_vision_server.py, 0.0.0.0:8889, /health 200). rc_facts `_port_listening` used ONE 0.4s TCP connect; a busy single-threaded accept races it (probed 3 OK / 2 timeout ~405ms). Fix `7f49499d`: retry timeouts (3x1.0s), refused=down-fast; +5 tests test_rc_facts_port_probe.py. Spawned chip task_a647378a = thread the :8889 server (the accept-stall root cause; gated on confirming handlers make no blocking inline model calls).
- **cdragon hard-tail (NEXT-UP #1) = CLOSED (item 351, `d2ecf125`; scope + drift-check, NO engine change).** 577 fallback blocks: 292 emission-guard (stay fallback) + ~174 live-state (buff-counter/conditional/unknown-stat/resource) = CLOSED-as-Meraki (item-232 class) + 111 by-level. by-level drift-checked = ALIGNED not stale (cdragon champ-level 1..18 vs Meraki spell-rank 1..5 = different axes; auxiliary blocks; primary-damage pairs agree <=~7%) -> DEFERRED to BACKLOG. Operator chose drift-check-first.
- **Don't-redo:** do NOT re-pitch a calc-graph resolver for the cdragon tail (only remaining cdragon growth needs a NEW extractor key). by-level lift parked in BACKLOG (only if a champ-level-indexed ratio axis is ever needed). Vision server is HEALTHY - rc_facts probe was the bug, not the server (a future :8889 "not listening" anomaly is likely the same race - re-probe /health). NEXT: remaining open work all operator/live-gated (P3.2 Phase-D, 6 UNIVERSAL_FILES, brief/flag flips, visual captures); no blind-shippable autonomous engine item (forward-marker EXHAUSTED item 348).

---

# 2026-06-07 - parallel next-items + loop-control half + gemini-audit fix [items 348-350]

"start next open items in parallel" -> 3 parallel tracks; then "continue" x2 -> 2 more items. All pushed (6f904bc7, d4e0cd04, dc78d5a3); CI green through d4e0cd04 (350 = ps1+docs).

- **Item 348 (`6f904bc7`):** orchestration E2/E3/F1 CLOSED + DS forward-marker scout EXHAUSTED. E2 (LCU richer-endpoint diff): top-3 = mastery-by-puuid full-team / match game-timelines / career-stats. E3 (lift sweep): NO new NOW candidate; 5 FUTURE (N1-N5); 3 stale-shipped flagged (anti-heal / inhibitor / per-item-WPA). F1 = stale-premise (both halves pre-shipped). DS scout: the un-taken LIFT_FOUND queue all REJECTED; `wiki_ability_stats` `*_raw` is unparsed wiki markup -> needs a NEW extractor key (memory `reference_ds_forward_marker_exhausted`). Fanout A1-F1 now FULLY CLOSED.
- **Item 349 (`d4e0cd04`):** loop-status CONTROL half (NEXT-UP #3 tail). NEW `POST /api/loop-control` (stop / resume / set_directive / clear) over `ops/loop/control/*`, atomic + capped + 400-guarded; `loop_controller.py` `consume_directive_override()` one-shot hook + precedence override>FIXED>director + import-safe CFG; `dev.js`/`header.css` Settings control card. +19 tests; full 5296 / 0. 5-phase UI audit ALL PASS (1 ASCII MUST-FIX fixed). RC pid 3340->7144; live curl all 4 actions + 400 OK, control dir restored.
- **Item 350 (`dc78d5a3`):** RC-GeminiAudit fix (`tools/gemini_audit.ps1`). Bug: `Write-Error` under EAP=Stop masked exit-1-no-log. Fixed: `Fail()` helper (logs + correct exit) + model fallback (gemini-3-pro-preview -> gemini-2.5-flash). External root cause verified: **429** (key VALID - models.list 50 - quota/RPM, Antigravity-shared); self-recovers on reset, NOT code-fixable. Memory `project_gemini_auditor` updated.

Don't-redo: DS forward-marker cadence EXHAUSTED (needs a new extractor key, not another scout fanout). NEXT-UP #3 FULLY SHIPPED (monitor 346 + control 349). RC-GeminiAudit 429 is EXTERNAL - read `logs/gemini_audit.log` FAIL line first. NEXT: remaining open work is all operator-gated (cdragon hard tail = needs calc-graph resolver / 6 UNIVERSAL_FILES / P3.2 Phase-D) or live/product-gated (E2/E3 candidates) - no blind-shippable autonomous item left.
