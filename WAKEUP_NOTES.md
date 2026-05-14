# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s194 wrap — 2026-05-14 (Phase 5.9.7 calibration-follow-up block_index expansion)

**Operator instruction:** "continue DS" — direct continuation of s193's carry-forward list. The cleanest next ship is more registry entries closing the explicit "Corki E/W, Hecarim W, Jayce W, Rell R, DrMundo W same per-tick → total pattern (+5-20% adps each, lower-impact deferral)" callout from s193's open-items section. Same template as s193 (pure data, no code), but mechanically interesting: includes the first block_index entry that layers on a prior form_index override (Jayce Q + s187 Jayce.Q form_index=1 cannon-form).

## Context

s193's hand-off listed exactly 5 deferred candidates: Corki E/W (Gatling Gun channel, Valkyrie trail), Hecarim W (Spirit of Dread aura), Jayce W (Lightning Field hammer aura), Rell R (Magnet Storm channel), DrMundo W (Heart Zapper drain). Inspection of the Meraki abilities snapshot confirmed each follows the same "per-tick" block 0 + "Total/Maximum" block 1 pattern as the s193 entries. Three additional candidates surfaced during inspection that fit the same template:

- **Hecarim E (Devastating Charge)** — min→max charge variant (2× block 0); operator commits to full charge in burst window, same modeling intuition as s191's Belveth E full-channel Royal Maelstrom (block 2 = max-channel).
- **Jayce Q (Shock Blast through Acceleration Gate)** — Increased Damage variant (1.4× block 0); canonical Jayce combo (fires E gate first, then Q through it). This is the first block_index that **layers on a prior form_index override** — s187 already set Jayce.Q form_index=1 (cannon form), now s194 sets block_index=1 within that form. Two orthogonal resolvers compose: form_index selects cannon form 1; block_index then selects gate-amped block 1 within that form.
- **Corki R Big One** — block 1 "Big One Physical Damage" was inspected but deliberately SKIPPED. Big One is a charge-based mechanic (every 4th missile is a special amped shot, NOT a per-cast amp). Requires conditional resource-state modeling to apply correctly. Defer.

All 8 ship-candidates verified against Meraki ATTR names in the snapshot (one of "Total Magic Damage", "Total Physical Damage", "Maximum Physical Damage", "Increased Damage") — confirming clean per-tick → total or min → max amped variants. Pure data batch — no resolver/walker/server code changes.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **Registry expanded from 20 → 25 entries (8 new (champion, key) pairs).** New entries: Corki {W:1, E:1}, Hecarim {W:1, E:1}, Jayce {Q:1, W:1}, Rell {R:1}, DrMundo {W:1}. `_meta.description` extended with Phase 5.9.7 note explaining the calibration-follow-up class + the Jayce Q form/block layering. `_meta.rationale` adds entry-by-entry per-tick × duration math verification with the Meraki ATTR names. Skipped-list updated to document Corki R Big One (conditional resource-state, not per-cast amp). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.78.0 → 0.79.0. Docstring extended with Phase 5.9.7 section noting the data-only nature of the batch + the form+block resolver composition for Jayce Q + A/B impact summary. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `CalibrationFollowUpExpansionTests` class (13 tests): one per new (champion, key) entry asserting registry routes to expected block_index + delta-check that total_ability_dps exceeds forced-block-0 baseline (`_delta_check` helper mirrors s193); plus `test_corki_both_keys_in_resolved` + `test_hecarim_both_keys_in_resolved` + `test_jayce_both_keys_in_resolved` for multi-key champions; `test_jayce_Q_block_layers_on_s187_form_index` smoke test for the form+block composition; `test_pre_s194_unmapped_unaffected` backward-compat guard preserving s193's Singed entry. Pre-existing `test_known_champion_overrides` extended with explicit assertions for all 5 new champion entries. File docstring extended with Phase 5.9.5/5.9.6/5.9.7 section. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.78.0 → 0.79.0 with the Phase 5.9.7 line in the history comment. |

## Verification

- DS suite **1689 pass** (was 1676 in s193 wrap; +13 from new `CalibrationFollowUpExpansionTests` class)
- Wider RC suite **1024 pass** (was 1013 in s193; +11: 13 new DS tests carry into wider suite via discovery, minus 2 that get absorbed by setUpClass aggregation; verified by phase8_smoke's `test_live_three_profiles` pinning ENGINE_VERSION 0.79.0 post-restart)
- `py_compile` clean for __init__.py
- DS server :8893 restarted from PID 16176 → new PID; `/health` reports `engine_version=0.79.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP)

| Champion.Key | Registry (post-s194) | Forced block 0 | Delta | Lift |
|---|---|---|---|---|
| Corki W | 17.733 adps | 14.202 adps | +3.531 | **+24.9%** |
| Corki E | 17.733 adps | 16.465 adps | +1.268 | **+7.7%** |
| Hecarim W | 27.648 adps | 22.442 adps | +5.206 | **+23.2%** |
| Hecarim E | 27.648 adps | 27.121 adps | +0.527 | **+1.9%** |
| Jayce Q | 29.103 adps | 25.040 adps | +4.063 | **+16.2%** |
| Jayce W | 29.103 adps | 22.065 adps | +7.038 | **+31.9%** |
| Rell R | 10.975 adps | 10.476 adps | +0.499 | **+4.8%** |
| DrMundo W | 30.459 adps | 25.791 adps | +4.667 | **+18.1%** |

Lifts are smaller than s193's headline channels (Singed +182%, Fiddle R +125%) because these champions all have multi-spell ability damage contributions — Hecarim's E adds only +1.9% to his total because his Q and W already dominate, while his W alone (+23.2%) mirrors the s193 channel pattern. Jayce W +31.9% is the biggest single-spell lift, reflecting how much the hammer-aura full duration outweighs the per-tick value the engine was using pre-s194.

**Per-spell row-level checks** (extract from /ability-dps raw_damage_per_cast):
- Corki W block 1 vs 0: per-tick 40-100 (block 0) → full-duration 200-500 (block 1) at rank 5 ≈ 5×
- Corki E block 1 vs 0: per-shot 5-17.5 (block 0) → full-channel 80-280 (block 1) ≈ 16×
- Hecarim W block 1 vs 0: per-tick 20-60 → full-aura 100-300 ≈ 5×
- Hecarim E block 1 vs 0: min-charge 30-90 → max-charge 60-180 ≈ 2×
- Jayce Q block 1 (cannon form 1) vs 0: regular Shock Blast 60-260 → gate-amped 84-364 ≈ 1.4×
- Jayce W block 1 vs 0: per-tick 35-95 → full-aura 140-380 ≈ 4×
- Rell R block 1 vs 0: per-tick 15-35 → full-channel 120-280 ≈ 8×
- DrMundo W block 1 vs 0: per-tick 5-20 → full-drain 80-320 ≈ 16× (block 2 recast detonation +25% one-time burst still missed — minor known under-count, documented in rationale)

**Regression checks pass:**
- Singed Q registry-resolved block 1 unchanged (s193 entry preserved; `test_pre_s194_unmapped_unaffected` asserts exact `{"Q": 1}` shape)
- Cassi /ability-dps total: **39.48** — unchanged from s191/s192/s193
- Akali /burst total: **941.71** — unchanged from s192 (R=0, R2=2 token-variant logic preserved)
- Zed (unmapped) burst with no override equals burst with explicit empty override — `BackwardCompatTests` green

## Findings

- **The s191/s192/s193 pattern still scales.** Tenth consecutive override registry on the same template; s194 is the third pure-data batch in the series (s191 seed, s193 channels, s194 calibration follow-up). Each new champion entry drops in as a one-line JSON addition + 1-2 test methods + a rationale comment.
- **Form/block resolvers compose cleanly.** Jayce Q is the first block_index entry that layers on a prior form_index entry (s187 set Jayce.Q form_index=1 cannon-form; s194 sets block_index=1 within that form). The resolvers compose at runtime without any new code: form_index resolves form selection → block_index resolves block selection within the resolved form. `test_jayce_Q_block_layers_on_s187_form_index` is a smoke test for the composition; full behavior asserted by the A/B delta on Jayce.Q (+16.2%).
- **DrMundo W's block 2 detonation is the only known under-count.** Heart Zapper has 3 damage blocks: block 0 per-tick (5-20), block 1 full-channel total (80-320), block 2 recast detonation (20-80). The single-block_index schema can pick only one — block 1 (the full channel) captures the larger share (~80% of realistic damage). Block 2's +25% one-time burst is missed. Acceptable under-count documented in rationale. Future schema lift could be `block_index: int | list[int]` to sum two blocks — defer until 3+ candidates need it.
- **Multi-spell champions show diluted lifts.** Hecarim E only adds +1.9% to total despite block 1 being 2× block 0 because his Q (rank 5, 60% bAD) and W (full aura, 5× block 0 base + 100% AP) dominate his total_ability_dps. The W +23.2% is the bigger signal. Pattern: per-spell lift × spell's share of total_ability_dps = total lift.
- **Corki R Big One was the cleanest skip.** Inspection showed block 0 "Physical Damage" (regular missile) + block 1 "Big One Physical Damage" (2× block 0). Looks like a per-tick → amped pattern at first glance, but Big One is mechanically a charge-stack proc (1 per ~12s real, every 4th missile), NOT a per-cast amp. Applying block_index=1 would over-count the regular cast by 2×. Documented as deferred in skipped-list with explicit "requires conditional resource-state modeling" rationale.
- **Process-tracking pattern continues to hold.** Used `Get-CimInstance Win32_Process | Where-Object` filter to isolate the DS pythonw.exe PID 16176; `Stop-Process -Id 16176 -Force` cleanly; relaunched via bash `pythonw tools/start_daemon_slayer.py` background spawn. No false kills.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — same as s193 carry-forward. Zoe sleep, Lux Illumination, DrMundo E missing-HP threshold, Renekton Q full Fury. Schema lift: `{"<champion>": {"<key>": {"default": 0, "when_target_missing_hp_pct_above": [0.5, 2]}}}`. Defer until 3+ candidates accumulate cleanly.
- 🟡 **Sum-of-blocks block_index** — DrMundo W full-channel + recast detonation. Schema lift: `block_index: int | list[int]` where list means sum. Single known candidate; defer until 3+ accumulate.
- 🟡 **Conditional resource-state block_index** — Corki R Big One every-4th-missile, Renekton Q full Fury, Aatrox Q chain stage. Same shape as conditional damage amps; defer until 3+ candidates accumulate.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness still missing. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Real internal CD in long combos** — s190 carry-forward.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

## Architectural pattern lock-in (continued from s193)

Tenth consecutive override registry on the same template. Three pure-data batches in the series now (s191 seed, s193 channels, s194 calibration follow-up). Resolver composition (form + block) verified live for Jayce Q — future per-champion entries can compose any combination of max_priority / combo_sequence / form_index / block_index without coupling. The registry pattern is stable enough that a future operator-driven "add 5-10 entries when calibration data warrants" batch can ship in one session with no engineering risk.

---

# s193 wrap — 2026-05-14 (Phase 5.9.6 channeled-ability block_index expansion)

**Operator instruction:** "continue" — straight from the s192 carry-forward. The cleanest next ship is more registry entries, focusing on a different pattern from s191 (single-block conditional amps) and s192 (per-token variants): the "per-tick → total" gap for channeled or duration-based abilities.

## Context

Scanning the 248 multi-block (champion, key, form) tuples in `champion_abilities.json` for "Total" / "Maximum" / "Increased" attribute names surfaced ~30 candidates beyond the s191 + s192 set. The biggest signal class: channeled abilities (Crowstorm, Disintegration Ray, Inferno Trigger, Trample, etc.) where Meraki ships block 0 = "per-tick" and block 1 = "Total" (the cumulative for the full channel duration). For both `/ability-dps` (cast-rate × per-cast damage) and `/burst` (single-combo per-cast damage), the realistic per-cast contribution is the FULL CHANNEL total — operator commits to the channel, sums up the ticks. The engine's default `block_strategy="first"` picked block 0 (per-tick) for every channel, systematically under-counting their item-ranking signal by 20-180% (per the A/B inspection below).

Pure data batch — no resolver/walker/server code changes. The s191 + s192 token-canonical lookup logic remains unchanged; just more JSON entries on the same template.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **Registry expanded from 12 → 20 entries.** 8 new champion entries (Alistar E=1 Trample total, AurelionSol E=1 Singularity total, Fiddlesticks R=1 Crowstorm total, MissFortune E=1 Make It Rain total, Samira R=1 Inferno Trigger spray total, Singed Q=1 Poison Trail total, Velkoz R=1 Disintegration Ray max, Syndra R=2 max sphere stacks) + Anivia entry extended from `{"E": 1}` to `{"Q": 2, "E": 1}` (Q now uses block 2 "Total Magic Damage" = initial pass + detonation combined). `_meta.description` extended with Phase 5.9.6 note explaining the per-tick → total pattern. `_meta.rationale` adds entry-by-entry rank-N math verification. Skipped-list expanded to document Corki E / Hecarim W / Jayce W / Rell R / DrMundo W (same pattern, deferred to a calibration follow-up batch since they're lower-impact in current rankings) + Renekton R + Kennen R + AurelionSol Q + Rumble R (modeling caveats per inline rationale). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.77.0 → 0.78.0. Docstring extended with Phase 5.9.6 section noting the data-only nature of the batch + A/B impact table. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `ChanneledAbilityExpansionTests` class (11 tests) — one per new entry asserting (a) registry routes the key to the expected block_index, (b) total_ability_dps with registry exceeds forced-block-0 baseline. Plus `test_anivia_E_still_routes_to_block_1` regression guard, `test_singed_Q_total_block_matches_per_cast_math` numeric sanity check. `test_known_champion_overrides` extended with explicit assertions for all 9 new/extended entries. Pre-existing `test_rank_mage_carries_source` in `ToDictSerializationTests` updated for Anivia's new `{"Q": 2, "E": 1}` shape. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.77.0 → 0.78.0 with the Phase 5.9.6 line in the history comment. |

## Verification

- DS suite **1676 pass** (was 1665 in s192 wrap; +11 from new `ChanneledAbilityExpansionTests` class)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for __init__.py
- DS server :8893 restarted from PID 12368 → new PID; `/health` reports `engine_version=0.78.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP)

| Champion | Pre-s193 (block 0 only) | Post-s193 (registry) | Delta |
|---|---|---|---|
| Singed Q | 4.06 adps | **11.46 adps** | **+182.4%** |
| Fiddlesticks R | 5.24 adps | **11.81 adps** | **+125.4%** |
| Anivia Q+E | 9.66 adps | **19.80 adps** | **+105.0%** |
| AurelionSol E | 1.99 adps | **3.29 adps** | **+64.9%** |
| Velkoz R | 13.84 adps | **17.04 adps** | **+23.1%** |
| MissFortune E | 9.97 adps | **11.64 adps** | **+16.7%** |
| Syndra R | 25.55 adps | **28.06 adps** | **+9.8%** |

Channel-class abilities (Crowstorm, Disintegration Ray, Poison Trail, Singularity, Make It Rain, Trample, Inferno Trigger) were systematically under-counted by 20-180% pre-s193. After the registry update, /rank-mage and /rank-assassin on these champions correctly weight their ultimate's contribution to the per-cast damage budget.

**Singed /rank-mage top 5** (baseline 11.46, was 4.06 pre-s193):
- 1. Rabadon's Deathcap +11.77 / 2. Shadowflame +10.16 / 3. Mejai's +10.10 / 4. Stormsurge +8.58 / 5. Void Staff +8.46
- AP items dominate as expected — Poison Trail's 85% AP scaling (block 1 total) makes Rabadon's huge

**Fiddlesticks /rank-mage top 5** (baseline 11.81, was 5.24 pre-s193):
- 1. Rabadon's Deathcap +6.53 / 2. Shadowflame +6.35 / 3. Mejai's +5.60 / 4. Stormsurge +5.47 / 5. Void Staff +5.25
- Crowstorm's 250% AP scaling at rank 3 (block 1 total) dominates Fiddle's late-game burst signal

**Regression checks:**
- Cassi /ability-dps total: **39.48** — unchanged from s191/s192 (E:1 entry preserved through s193 expansion)
- Akali /burst total: **941.71** — unchanged from s192 (R=0, R2=2 token-variant logic preserved)
- 1013/1013 wider RC tests pass — no fallout from the additive JSON-only change

## Findings

- **The s191/s192 pattern scales cleanly.** Pure JSON expansion with zero code changes ships 9 entries spanning a 20-180% impact range. The Phase 4e form_index / s185 max_priority / s186 combo / s187 form_index / s191 block_index / s192 token-variant pattern is now confirmed extensible: future per-champion modeling entries drop into the same `{"<champion>": {"<key>": <int>}}` slot with no friction.
- **Per-tick → total is the largest single class of mis-pricing in the engine.** Channels like Singed Q / Fiddle R have been valued at 1/8 to 1/20 of their realistic per-cast damage since the engine's first ability_dps ship in s178. The Meraki schema has been correct all along; the engine just needed to know which block represents the realistic per-cast value. s193 corrects this for 8 of the worst offenders.
- **Cast-rate sanity holds.** `spell_cast_rates.json` measures one cast per channel (not per tick), so multiplying `total_per_cast` by `casts_per_sec` gives the right time-averaged DPS contribution. No double-counting concern from the per-tick → total swap.
- **Anivia Q is doubly amped now.** s191 added E=1 (chilled-target Enhanced); s193 adds Q=2 (Flash Frost both passes total). Anivia's full Q-W-E rotation in /rank-mage now scores correctly for the canonical Q-E-burst combo that defines her mid laner identity.
- **Skipped-list grew with deferral rationale.** Corki E / Hecarim W / Jayce W / Rell R / DrMundo W all share the per-tick → total pattern but were skipped this batch because their /rank-* impact is smaller (lower cast frequency in rewind data, smaller absolute total damage). They're tracked as a calibration follow-up batch — if rewind volume increases, expand the registry.
- **Process-tracking refinement from s192 worked.** Used `Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' ... }` to filter to the actual DS process (not the powershell.exe parent). No false kills this batch.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — same as s192 carry-forward. Zoe sleep, Lux Illumination, DrMundo E missing-HP threshold, Renekton Q full Fury. Schema lift: `{"<champion>": {"<key>": {"default": 0, "when_target_missing_hp_pct_above": [0.5, 2]}}}`. Defer until 3+ candidates accumulate cleanly.
- 🟡 **Calibration follow-up entries** — Corki E/W, Hecarim W, Jayce W, Rell R, DrMundo W. Same per-tick → total pattern as s193 entries; deferred this batch as lower-priority. Estimate +5-20% adps per champion. One-line additions to the registry when prioritized.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness still missing. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Real internal CD in long combos** — s190 carry-forward.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

## Architectural pattern lock-in (continued from s191/s192)

Ninth consecutive override registry on the same template. s193 is the second pure-data batch in the series (after s191's seed entries themselves were data-driven once the resolver shipped). The pattern is now stable enough to support routine "calibration-driven" expansion batches — operator can add 5-10 entries per session without engineering risk. Future conditional-block_index (the carry-forward) is the only remaining structural lift.

---

# s192 wrap — 2026-05-14 (Phase 5.9.5 token-variant block_index for Akali R)

**Operator instruction:** "continue" — directly continuing the s191 carry-forward list. Top item (a): per-token-variant block_index for Akali R. R1 (block 0 base) and R2 (block 2 max-execute) need different blocks within the same combo, but the s191 per-(champion, key) registry only had a single per-key entry. Single commit ship.

## Context

s191's hand-off explicitly deferred Akali R because setting `{"Akali": {"R": 2}}` globally would over-count R1: R1 in-game is the initial dash with bonus-AD scaling (block 0), R2 is the recast with missing-HP execute scaling (block 2). The Meraki snapshot already exposes both blocks; the engine just needed to distinguish R from R2 tokens in the combo walker.

Two design decisions for this batch:
1. **Extend keys, not values** — `block_index_overrides` stays `dict[str, int]` (no `dict[str, int | list[int]]` complexity). Repeat-variant tokens (Q2/W2/E2/R2) become valid keys alongside base keys (Q/W/E/R). Forward-compatible: any future "Q3 differs from Q1/Q2" entry drops in without code changes.
2. **Token-canonical first, base-key fallback** — the burst walker checks `block_overrides.get(canonical)` before `block_overrides.get(ability_key)`. So `{"R": 0, "R2": 2}` routes R1 → block 0 (the same s191 default would, just explicit) and R2 → block 2 (the missing-HP execute scaling). `compute_ability_dps` is unaffected — it iterates Q/W/E/R only, so the R2 entry is invisible to the mage scorer.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | Added `"Akali": {"R": 0, "R2": 2}` entry. `_meta.description` extended with Phase 5.9.5 lookup precedence note (token-canonical first, base-key fallback). `_meta.rationale` adds Akali R/R2 entry explaining R1's bonus-AD scaling vs R2's missing-HP execute curve. Skipped-list updated: Yone Q1/Q2/Q3 (single-block per form, knockup is utility), Zed Q vs Q2-shadow (block 0 is correct for both), Leblanc Q vs Q2-mimic (mimic-Q has its own damage formula not in Meraki). |
| [agents/daemon_slayer/burst.py](agents/daemon_slayer/burst.py) | Combo walker's per-cast block-index resolution: `if canonical in block_overrides:` checked FIRST (token-canonical lookup — e.g. "R2"), then `elif ability_key in block_overrides:` (base-key fallback — e.g. "R"), then falls through to global `block_strategy`. Comment block expanded to document the two-tier lookup. compute_ability_dps unchanged. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.76.0 → 0.77.0. Docstring extended with Phase 5.9.5 section. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `AkaliTokenVariantTests` class (7 tests): registry shape, R1 row block 0 raw=220, R2 row block 2 raw=420, total burst with registry > forced R+R2:0, explicit R2 override wins over registry, R-only override falls through to R2 token (documents the "double-count" scenario when operator omits R2), `compute_ability_dps` ignores R2 entry. Pre-existing `RegistryShapeTests` `test_every_key_is_valid_token` extended valid-key set to include Q2/W2/E2/R2 (was Q/W/E/R only). `test_known_champion_overrides` adds Akali assertion. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.76.0 → 0.77.0 with the Phase 5.9.5 line in the history comment. |

## Verification

- DS suite **1665 pass** (was 1658 in s191 wrap; +7 from new `AkaliTokenVariantTests` class)
- Wider RC suite **1013 pass** (no regression)
- `py_compile` clean for burst.py + __init__.py
- DS server :8893 restarted from PID 15664 (was the s191 0.76.0 pid still running) → PID via background spawn; `/health` reports `engine_version=0.77.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893

**Akali /burst (s186 combo Q-AA-E-R-Q2-AA-R2 vs 80 armor / 30 MR / 2000 HP):**

| Scenario | Total | R row | R2 row |
|---|---|---|---|
| Registry-applied (R=0, R2=2) | **941.7** | raw=220.0 final=169.2 | raw=420.0 final=323.1 |
| Forced R+R2:0 (pre-s192 model) | 787.9 | raw=220.0 final=169.2 | raw=220.0 final=169.2 |
| Naive R:2 only (pre-s192 mistake) | 1095.6 | raw=420.0 final=323.1 | raw=420.0 final=323.1 |

Registry is exactly halfway between "ignore the R2 amp" (787.9) and "naively double-count R1" (1095.6), confirming the token-variant model captures the realistic mid-point: **+153.8 burst (+19.5%)** over the pre-s192 baseline.

**Akali /rank-assassin top 5 (registry baseline 941.7):**
- 1. Lich Bane +396.54 / 2. Shadowflame +370.19 / 3. Rabadon's Deathcap +354.90 / 4. Stormsurge +322.72 / 5. Essence Reaver +312.37
- Lich Bane #1 — Spellblade procs each ability cast and the now-doubled R2 base × 90% AP makes Lich Bane's AP scaling extra valuable

**Cassi /ability-dps (regression check):** 39.48 adps — unchanged from s191 (E:1 → block 1 Total Enhanced still applies). No s191 entry was affected by the token-variant extension.

## Findings

- **Token-canonical lookup is a 3-line change.** The burst walker already had `canonical, ability_key, is_ability = _normalize_combo_token(token)` at the top of each iteration — just needed `if canonical in block_overrides` before the existing `elif ability_key in block_overrides`. The API surface stays the same (`dict[str, int]`); the semantics extend naturally.
- **compute_ability_dps untouched.** The mage scorer iterates `SPELL_KEYS = ("Q", "W", "E", "R")` and does `overrides.get(key, 0)` — the Akali R2 entry in the dict is simply absent from this lookup. No special-case logic needed; the API extends cleanly. `compute_ability_dps` for Akali returns R with block 0 (same as pre-s192).
- **The +153.8 delta is exactly the R2 block 2 - block 0 swap.** At rank 1 (R lvl 11), block 0 base = 220 + 30% AP + 50% bonus AD; block 2 base = 420 + 90% AP. With 0 AP / 0 bAD (naked build), the delta is exactly 420 - 220 = 200 raw → 153.8 after mitigation (×0.769 from 30 MR). Confirms the model is consuming Meraki's blocks correctly with no extra amp drift.
- **Naive R:2 over-count is +307.6 vs registry.** Without token-variant lookup, an operator (or future engine maintainer) would have to either tolerate the pre-s192 under-count (+0 from R2 amp) or eat the over-count from doubling R1 (+153.8 spurious). The token-variant pattern eliminates this dichotomy.
- **Process-tracking gotcha.** First DS restart killed the wrong PID (PowerShell taskkill targeted the parent shell, not the python.exe server). Had to inspect `Get-CimInstance` for both py.exe + python.exe entries, kill the actual server (PID 15664) directly, then relaunch. Same shape as the s190 PowerShell `$pid` reserved-name issue — both stem from PowerShell process semantics being subtly different from POSIX.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — Zoe sleep amp, Lux Illumination mark, DrMundo E missing-HP threshold, Renekton Q Fury condition. Each wants block_index N when a target-state condition is met (target asleep, target marked, target missing >X% HP, caster has >Y resource). Schema extension: `{"<champion>": {"<key>": {"default": 0, "when_target_missing_hp_pct_above": [0.5, 2]}}}`. Substantial design lift; defer until 3+ candidates accumulate cleanly.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q follow-up amp)** — inter-spell awareness still missing for damage *multipliers* on subsequent spells (vs the per-block selection s191/s192 ships). Carried since s180.
- 🟡 **Generalized arm-consume framework via `is_ability_triggered_aa_proc` schema flag** — still two specific helpers (Spellblade s189 + Lightshield s190). Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — same upstream/plumbing/UI blockers as s187/s188/s189/s190/s191.
- 🟡 **Real internal CD in long combos** — s190 carry-forward (a); 8-token combos lasting >3s could in theory permit a second Lightshield Strike proc.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** all remain unchanged: live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune blocked on real-game fired nudges; `nudge_history` calibration additive.

## Architectural pattern lock-in (continued from s191)

Eighth consecutive override / proc-shape modeling improvement on the same template, and the first one to *extend* a prior registry rather than ship a new one (s191's registry gained the Akali entry; the schema stayed `dict[str, int]` but the valid-key set extended from `{Q,W,E,R}` to `{Q,W,E,R,Q2,W2,E2,R2}`). The pattern is now proven extensible across both rows (more entries) and columns (more granular keys per entry). Future conditional-block_index extensions can layer values from `int` → `dict[str, Any]` without disturbing the per-batch resolver contract.
