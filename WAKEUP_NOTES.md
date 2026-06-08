# WAKEUP_NOTES - RC hand-off ledger

> Sessions s27-s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 + s203 + s204 + s214 + s215 + s225 + s226 + 2026-05-19/20 mid-run summary + 2026-05-20 housekeeping batch + 2026-05-21 items 121-130 + 2026-05-22 items 133-139 + 2026-05-22 items 140-149 + item 181 + item 187 + item 188 + item 189 + item 190 + item 191 + item 192 + item 193 + item 194 + item 195 + item 196 + item 197 + item 198 + item 199 + item 200 + item 204 + item 215 + item 216 + item 227 + item 228 + item 241 + item 242 + item 245 + item 246 + item 247 + item 248 + item 249 + item 250 + 2026-06-01 Share-docs-reconcile (1.86.0) + item 255 + item 256 + item 257 + item 258+259 + item 261 + item 263 + item 264 + items 271-287 (2026-06-03 prune) + 2026-06-03 RC-wide multi-agent (item 299 prune) + item 300 (2026-06-04 wave-clear prune) + item 301 (2026-06-04 threat-range prune) archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# 2026-06-08 - LIFT1 competitor-lift review: RC supersedes both targets [item 354]

gemini-headless-upgrade loop, directive LIFT1 (cycle off the 2026-06-08 ORCHESTRATION_PLAN, ahead of HZ-B). Commit 4b15b031. RESEARCH + TRIAGE only, NO code slice (docs-only).

- **2 heavyweight general-purpose research agents** (depth-per-target, 6-point checklist WHAT/HOW/HAVE-grep-cite/WHERE/EFFORT+RISK/LIFT); every HAVE/WHERE premise re-verified live before publishing. Output `docs/COMPETITOR_LIFT_2026-06-08.md`.
- **Tool 1 (seb16120 target-vs-opponent "what stat to buy")** = a 100%-client-side manual-entry DEFENSIVE EHP calc (no champ/item data, no network calls). RC SUPERSEDES automatically: `agents/daemon_slayer/ehp.py` (per-type/blended EHP + shields/heals/ARAM/CC/revive layers the competitor lacks) + `core/defensive_picks.py` threat-weighted defensive-ITEM picks + the live `cc_blended_ehp_threat` panel.
- **Tool 2 (simulator tool R.com + r/simulator tool R)** = a JS combat sim (combo / 1v1 / DPS-TTK / EHP / build-sort / sandbox). RC parity-or-better on EVERY axis via the prior 2026-05-30 calc.gg lift (`combo.py`/`matchup.py`/`dps.py`/`fight_report.py` + `ds_combo.js`/`ds_matchup.js`); the 172-champ engine beats the twins' hand-coded-champ ceiling.
- **ACT:** NO HIGH-lift+LOW-risk finding -> per the ACT gate (MED/LOW always defer) NO in-run code. **2 FUTURE gaps -> BACKLOG (Coaching depth):** T1-F3 enemy-pen-aware effective resists (`ehp.py compute_ehp` documented Phase-1 omission, enemy pen plumbed via `defensive_picks.py` but feeds only THREAT scores; MED engine schema lift, operator-gated) + T2-F4 rune/keystone in the combo SURFACE (`routes_ds_combo.py` threads no `runes=` param, grep=0; MED route+panel wire-up + Sec-3b UI ritual). Minor deferred: T2-F3 TTK headline, T1-F4 per-stat EHP/gold.
- Docs-only: DS-dir 7024 passed / RC tests/ 5352 passed, 0 regressions. ENGINE 1.120.0 untouched, no DS/RC restart, no Share, no UI-audit. Competitor tools read-only, no code vendored. ROADMAP 81707/81920 (TIGHT - the NEXT cycle needs a ROADMAP_HISTORY relocation before it can add a shipped line).
- **NEXT OPEN = the operator UI/UX + bug batch** (LOBBY1 / PGR1 / REPLAY1 / HIST1+HIST2 / CS1-CS3), then HZ-B.

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
