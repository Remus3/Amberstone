# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-08 - HZ-A2 Lane A economy block: recall/back-timing + power-spike-ETA (Haiku-to-ZERO) [item 353]

gemini-headless-upgrade loop, directive HZ-A2 (cycle 2 off the 2026-06-08 ORCHESTRATION_PLAN). Commit dc5e6293. BUILD + PERSIST only, NO live coach flip (charter 4b do-not-flip-blind).

- **`core/lead_projection.py` new pure primitives** (shared macro-economy authority; `project_lead` untouched): `minutes_for_level` (band<->minute bridge off the existing level benchmark), `gold_income_per_min` + `expected_gold_earned` (GROSS-earned benchmark, ARAM 600 > SR 450, distinct from on-hand `_GOLD_PER_MIN_BENCHMARK`), cumulative-gold `_SPIKE_LADDER` (component 1100 / first_item 3000 / two_item 6200 / three_item 9400) + `SPIKE_COMPLETE`, `next_spike` / `spike_threshold` / `spike_eta_seconds`.
- **`core/laning_scenario_precompute.py`:** `economy_cell` + `_recall_verdict` compose those into a per-cell `{recall, next_spike, spike_eta_s, gold_at_band}` block on every leaf; schema v1 -> **v2** + economy dimensions stanza.
- **Design call:** recall is gold/spike + mana driven, NOT trade-verdict driven (a combat read is not an economy one). low-mana mana champ -> recall_now; unspent completed-item gold + no imminent spike -> recall_now; spike within 60s -> back_soon; core complete -> hold.
- **Orchestration call:** HZ-A2 is a hard LINEAR A->B dep (~120 coupled LOC) so "true-concurrency" worktrees degenerate to sequential + a RED B slice -> ran as sole orchestrator with TDD (31 RED -> green) + the read-only verifier subagent as the pre-commit gate. verifier CONFIRM all 6 claims (76/0 module files; 0 of 1600 leaves missing economy; ruff clean).
- Regenerated SR seed (1600 cells, v2): recall_now 940 / back_soon 440 / hold 220. +35 tests (lead_projection_economy 19 + laning_scenario_economy 16). Full RC 5352 passed / 1 skip / 85 subtests / 0 fail. ENGINE 1.120.0 untouched, ds_share_sync --check green (laning_scenarios NOT in Share), no DS/RC restart, no web -> no UI-audit. Directive's "clear false-alarm blockers" = no-op (none existed; grep clean).
- **NEXT OPEN = HZ-B1** (Lane B build-order precompute per champ x mode x enemy-comp). The table is read by a FUTURE consumer (HZ-C1); validate recall-timing on a real/replayed game BEFORE any coach flip.

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
