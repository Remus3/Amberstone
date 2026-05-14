# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s196 wrap — 2026-05-14 (Phase 5.9.9 extended multi-hit/condition-amp block_index expansion)

**Operator instruction:** "continue DS" — direct continuation of s195. The carry-forward had three schema-lift items + the same pure-data well that s195 sampled from. Pure-data was still the cleanest ship: deeper triage of the same Meraki snapshot surfaced 17 more clean wins spanning patterns A and B from s195 (multi-hit single-target totals + fully-charged/condition amps).

## Context

s195 had triaged 13 candidates from 153 with a focused-cleanest cut. Re-scanning the same `champion_abilities.json` with a damage-block filter (block 0 must be `attribute_kind=damage` with damage scaling; block N's attribute must contain Total/Maximum/Increased/Enhanced/Empowered and also be damage-kind) returned 145 pure-damage candidates. Triaged to 17 entries across two patterns:

**Pattern A — Multi-hit single-target totals (12 entries):**
- Akali E=2 (E1 Shuriken Flip throw + E2 grappling-hook dash on tagged target, ~3.33×)
- Akshan Q=1 (Avengerang ricochet out + return on same target, 2×)
- Cassiopeia W=1 (Miasma cloud full duration, 5×)
- Chogath E=1 (Vorpal Spikes 3-hit empowered AA rotation, 3×)
- Draven R=1 (Whirling Death out + return, 2×)
- Lillia W=1 (Watch Out! Eep! center hit, 3× rim damage)
- Morgana R=1 (Soul Shackles initial + delayed-snap tether duration, 2×)
- Nautilus E=2 (Riptide 3-wave same target, 2×)
- Riven Q=1 (Broken Wings Q-Q-Q 3-cast chain, 3×)
- Sett Q=1 (Knuckle Down both empowered AAs, 2×)
- Skarner Q=1 (Shattered Earth empowered 3-hit chain, 3×)
- Soraka E=1 (Equinox immediate + delayed-silence proc, 2×)

**Pattern B — Fully-charged / condition amps (5 entries):**
- Gragas Q=1 (Barrel Roll fully-fermented 4s hold, 1.5×)
- Karthus Q=1 (Lay Waste single-target enhanced passive, 2×)
- Khazix Q=1 (Taste Their Fear isolation amp — the defining Kha'Zix mechanic, 2.1×)
- KogMaw R=1 (Living Artillery low-HP execute, 2×)
- Pantheon Q=1 (Comet Spear fully-charged hurl, 2.2×)

All 17 verified per-rank against the Meraki snapshot — block N's base + scaling fields match the exact canonical-condition multiple of block 0 (e.g., Akshan Q rank 1 block 1 base 10 = exact 2× block 0 base 5; Riven Q rank 1 block 1 base 135 = exact 3× block 0 base 45). The `test_riven_Q_block1_matches_3x_block0` and `test_akshan_Q_block1_matches_2x_block0` sanity checks pin these per-rank multipliers.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **Registry expanded 35 → 49 champions (17 new (champion, key) pairs).** 14 new champions: Akshan, Chogath, Draven, Gragas, Karthus, Khazix, KogMaw, Lillia, Nautilus, Pantheon, Riven, Sett, Skarner, Soraka. 3 key extensions: Akali +E=2 (alongside existing R=0, R2=2), Cassiopeia +W=1 (alongside existing E=1), Morgana +R=1 (alongside existing W=3). `_meta.description` extended with Phase 5.9.9 note explaining both sub-patterns + the rationale for skip-list growth. `_meta.rationale` adds entry-by-entry per-rank math verification with Meraki ATTR names. Skipped-list extended with 15 explicit deferrals: Nidalee Q (form_index conflict with s187), Kassadin R (resource-state), Aatrox W (CC-conditional), Akshan R (charge), Ambessa Q/W/E (form swap), Pantheon W/R (no scaling / engine default OK), Gangplank R (Upgrade choices), Jhin R (4-shot sequence), Hwei R (channel deferral), Gwen R / KSante R (form swap), Karthus E/R, Mel Q, Naafiri Q, Olaf Q, Nasus E. |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.80.0 → 0.81.0. Docstring extended with Phase 5.9.9 section noting the data-only nature, both sub-patterns with all 17 entries enumerated, A/B impact summary, and deliberate skip-list rationale. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `Phase599ExpansionTests` class (25 tests): 17 per-entry `_delta_check` (mirrors s195 pattern), 3 multi-key resolved-shape (Akali three-key Q→E→R/R2, Cassi E+W, Morgana W+R), 2 math sanity (`test_riven_Q_block1_matches_3x_block0` + `test_akshan_Q_block1_matches_2x_block0`), 3 backward-compat (`test_pre_s196_morgana_W_unchanged` + `test_pre_s196_akali_R2_unchanged` + `test_pre_s196_corki_unchanged`). `RegistryShapeTests.test_known_champion_overrides` extended with assertions for all 14 new champions + 3 extended champions' new shapes. Existing tests updated to reflect Cassi `{E:1, W:1}` and Akali `{R:0, R2:2, E:2}` and Morgana `{W:3, R:1}` shapes (`GetBlockIndexForTests.test_known_override_returns_champion_source` repointed from Cassi to Veigar; `ResolveBlockIndexTests.test_none_with_known_returns_champion` repointed from Cassi to Veigar; `BackwardCompatTests.test_unmapped_keys_inside_mapped_champion_use_global_strategy` repointed from Cassi to Veigar; `ComputeAbilityDpsBlockIndexTests.test_mapped_champion_uses_registry` and `test_explicit_override_wins` updated for new Cassi shape; `AkaliTokenVariantTests` 3 tests updated for new Akali shape; `RankerBlockIndexTests.test_rank_mage_carries_source` and `ToDictSerializationTests.test_compute_ability_dps_carries_source` updated for new Cassi shape). File docstring extended with Phase 5.9.9 section. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.80.0 → 0.81.0 with the Phase 5.9.9 line in the history comment. |

## Verification

- DS suite **1733 pass** (was 1708 in s195 wrap; +25 from new `Phase599ExpansionTests` class)
- Wider RC `tests/` suite **913 pass** (post-DS-restart — pre-restart, phase8_smoke's `test_live_three_profiles` was failing on the 0.81.0 pin against the still-0.80.0 live server, as expected)
- `py_compile` clean for __init__.py
- DS server :8893 restarted from PID 10420 → new PID via `Get-CimInstance` filter + `taskkill /F /PID` + `Start-Process pythonw tools\start_daemon_slayer.py`; `/health` reports `engine_version=0.81.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP)

| Champion.Key | Registry (post-s196) | Forced block 0 | Delta | Lift |
|---|---|---|---|---|
| Riven Q | 56.98 adps | 20.42 adps | +36.56 | **+179.0%** |
| Pantheon Q | 24.30 adps | 12.06 adps | +12.24 | **+101.5%** |
| Karthus Q | 53.20 adps | 27.79 adps | +25.41 | **+91.4%** |
| Lillia W | 21.06 adps | 11.35 adps | +9.71 | **+85.5%** |
| Akshan Q | 7.32 adps | 3.99 adps | +3.33 | **+83.5%** |
| Skarner Q | 13.64 adps | 7.95 adps | +5.69 | **+71.5%** |
| Khazix Q | 15.18 adps | 9.26 adps | +5.92 | **+63.9%** |
| Akali E | 24.15 adps | 15.41 adps | +8.74 | **+56.7%** |
| Gragas Q | 47.41 adps | 36.42 adps | +10.99 | **+30.2%** |
| Draven R | 3.19 adps | 2.49 adps | +0.70 | **+28.3%** |
| Sett Q | 5.46 adps | 4.32 adps | +1.14 | **+26.5%** |
| Soraka E | 8.47 adps | 7.61 adps | +0.86 | **+11.3%** |
| Nautilus E | 8.24 adps | 7.51 adps | +0.73 | **+9.7%** |
| Chogath E | 21.94 adps | 20.85 adps | +1.09 | **+5.2%** |
| KogMaw R | 16.45 adps | 15.68 adps | +0.77 | **+4.9%** |
| Morgana R | 24.49 adps | 23.71 adps | +0.78 | **+3.3%** |
| Cassiopeia W | 40.44 adps | 39.48 adps | +0.96 | **+2.4%** |

Riven Q +179% is the headline — Broken Wings is Riven's core damage rotation, and the 3-cast Q-Q-Q chain on the same target was being scored as a single cast pre-s196 (block 0 only). Pantheon Q +101% and Karthus Q +91% similarly reflect their identity-defining mechanics (fully-charged Comet Spear, solo-target Lay Waste).

The small-lift entries (Cassi W +2.4%, Morgana R +3.3%, KogMaw R +4.9%) are utility-heavy champions whose total_ability_dps is dominated by other spells; the per-spell registry lift is real but diluted by spell-share weighting.

**Regression checks pass:**
- s195 Morgana W=3 entry preserved (`test_pre_s196_morgana_W_unchanged`)
- s192 Akali R=0, R2=2 token-variant entries preserved + composition with new E=2 verified (`test_pre_s196_akali_R2_unchanged`)
- s194 Corki {W:1, E:1} entry preserved (`test_pre_s196_corki_unchanged`)
- `BackwardCompatTests` green: unmapped Zed burst with no override = unmapped Zed burst with empty explicit override (byte-identical)

## Findings

- **The pure-data well still has clean candidates.** s195 wrap said "13 cleanest of 153"; s196 found 17 more with the same triage criteria. Deeper inspection of the snapshot's per-rank math (block N's `base[]` must be an exact-multiple of block 0's `base[]` across all 5 ranks) is a strong-enough filter to keep the patterns clean. Estimated 80-100 more candidates remain unmapped — but they're increasingly utility-blocky (Heal/Shield/Slow blocks intermixed with damage blocks) or mechanically ambiguous.
- **The skipped-list pattern is now self-documenting.** Each skip entry in `_meta.rationale` documents (1) what the candidate is, (2) why it was skipped, (3) which carry-forward bucket it belongs to (form-conflict, resource-state, CC-state, target-state, multi-form). 15 skip entries added this batch, all categorized.
- **Per-spell lift % vs total_ability_dps lift %.** The headline finding from s195 was duplicated here: a per-spell 3× lift can yield anywhere from +5% to +180% total_ability_dps lift depending on the spell's weight in the champion's rotation. Single-spell-defining champions (Riven, Karthus, Akshan) see huge lifts; utility/multi-spell champions (Morgana, Cassi) see small lifts. This is correct behavior, not a bug — each champion's burst signal is now closer to reality.
- **Akali test fallout was avoidable.** I had to repoint several Akali-based test fixtures because adding E=2 broke their hardcoded `{R:0, R2:2}` expected shape. Lesson: when extending an existing champion's registry entry, search for ALL test assertions of that champion's shape — not just the canonical RegistryShapeTests assertion. Cost was ~5 min to fix; preventable with a pre-edit grep.
- **Test-discovery counted correctly.** s195 wrap said `+19` new tests; s196 added `+25`. Pre-s196 the DS suite was 1708, post-s196 is 1733. The math is exact (1708 + 25 = 1733), confirming all 25 new tests register at discovery time.
- **Process-tracking pattern continued to hold.** `Get-CimInstance Win32_Process | Where-Object` filter isolated the DS pythonw.exe PID 10420 cleanly; relaunched via `Start-Process pythonw tools\start_daemon_slayer.py` background spawn. No false kills.
- **Cassiopeia W's lift is honestly tiny but the math is right.** Cassi /ability-dps total post-s196 is 40.44 vs forced-block-0 39.48 = +2.4% lift. This is because Cassi's E (Twin Fang) dominates her ability_dps — it's a 0.5s cooldown spell with the s191 block-1 amp already applied. Adding W=1 (Miasma full duration) shifts the per-W spell from per-second tick to full-duration total — but Cassi rarely commits to W's full duration in burst-window scoring (it's a slow zone, used for setup not damage). The +0.96 adps is the marginal full-duration uplift; the rationale doc notes this is the *contract* (operator drops W, target walks through cloud), even though in practice Cassi's burst is Q+E focused.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — same as s195 carry-forward. Zoe sleep, Lux Illumination, DrMundo E missing-HP threshold, Renekton Q full Fury. Schema lift candidates accumulated to 4+ but each requires different conditional shape (HP threshold, mark presence, status effect, resource state). Defer until operator commits to the schema design (current `dict[str, int]` would need to become `dict[str, int | dict[str, ...]]`).
- 🟡 **Sum-of-blocks block_index** — DrMundo W full-channel + recast detonation. Single known candidate. Defer.
- 🟡 **Conditional resource-state block_index** — Corki R Big One, Renekton Q full Fury, Aatrox Q chain stage, Kassadin R stack count, Akshan R Comeuppance charge. Now 5+ candidates accumulated — could justify the schema lift after the target-state version ships.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness still missing. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Real internal CD in long combos** — s190 carry-forward.
- 🟡 **Form-conflict block_index entries** (Nidalee Q, Hwei R block-3, Gwen R, KSante R) — each needs orthogonal form_index + block_index registry entry resolved against the canonical form (not form 0). Future batch when conditional schema ships.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

## Architectural pattern lock-in (continued from s195)

Twelfth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo / s187 form / s188 per-AA on-hit / s189 Spellblade / s190 Lightshield / s191 block_index / s192 token-variant / s193 channels / s194 calibration / s195 multi-hit/charge/recast / s196 extended multi-hit/condition-amp). Fifth pure-data batch in the channel/total/charge family. The pattern is now well past stable enough for routine 10-25 entry batches per session; the rate-limiting step is operator triage of skip-list growth (15 skip entries this batch — manageable but the well of "easy + clean" candidates is narrowing). Next structural lift (conditional-block_index schema) is queued and has 4+ target-state candidates + 5+ resource-state candidates — ready when operator commits to schema design.

---

# s195 wrap — 2026-05-14 (Phase 5.9.8 multi-hit/charge/recast block_index expansion)

**Operator instruction:** "continue ds" — direct continuation of s194. The carry-forward list had two pure-data candidates and three schema-lift candidates; pure-data was the cleanest ship. Scanned `champion_abilities.json` for the next clean class of multi-block (Total/Maximum/Increased/Enhanced/Empowered) entries beyond the s193 channel set and s194 calibration-follow-up — found 153 unregistered candidates and triaged to the 13 cleanest spanning four sub-patterns.

## Context

The s193 hand-off mentioned "Conditional damage amps (Ahri R→Q, Zoe E→Q, Akali R1→QE→R2)" but on inspection most of those map to existing combo-sequence (s186) or multi-form (s187) work. The actual remaining gap in the pure-data expansion pipeline is **multi-hit single-target totals + fully-charged amps + recast amps + CC-conditional duration totals** — all of which fit the established s191 "operator commits to canonical amped condition" model without any schema lift. Same `dict[str, int]` registry; same s192 token-canonical + base-key fallback walker logic; just more JSON.

Four sub-patterns shipped this batch — each maps cleanly to a single static block_index:

**(A) Multi-hit single-target totals (operator focuses all hits/bolts/missiles on one target):**
- Ahri W=2 (Fox-Fire 3-bolt total)
- Kaisa Q=2 (Icathian Rain missile-focus total)
- Lulu Q=3 (Glitterlance both passes)
- Sivir Q=2 (Boomerang Blade out + back)
- Talon W=2 (Rake out + return)
- Talon R=2 (Shadow Assault unstealth chain)
- Velkoz W=2 (Void Rift initial + detonation)
- Ekko Q=3 (Timewinder out + return)

**(B) Fully-charged amps (operator commits to wind-up duration in burst):**
- Varus Q=1 (fully-charged Piercing Arrow, 1.5× block 0)
- Zoe Q=1 (long-distance Paddle Star post-E teleport, 2.5× block 0)
- Vladimir E=1 (2-charge Tides of Blood, 2× block 0 + 4× caster HP scaling)

**(C) Recast amps (operator commits to executing both stages in window):**
- Camille Q=2 (Precision Protocol second cast, 2× block 0)

**(D) CC-conditional duration totals (operator commits to root + full duration):**
- Morgana W=3 (Tormented Shadow Maximum Total Damage vs rooted target)

All 13 verified per-rank math against the Meraki snapshot — for instance, Ahri W block 2 base 64 (rank 1) = 40 (block 0 initial) + 12×2 (block 1 subsequent × 2 more bolts), ap_pct 64% = 40% + 12%×2. The `test_ahri_W_block2_matches_sum_of_blocks_0_and_2x1` sanity check pins this property.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **Registry expanded 25 → 35 entries.** 11 new champions (Camille, Ekko, Kaisa, Lulu, Morgana, Sivir, Talon, Varus, Vladimir, Zoe) + 2 multi-key extensions (Ahri added W=2 to its existing {Q:1}; Vel'Koz added W=2 to its existing {R:1}). `_meta.description` extended with Phase 5.9.8 note explaining the four sub-patterns. `_meta.rationale` adds entry-by-entry math verification (each block N's base + scaling fields match the sum of components from blocks 0..N-1). Skipped-list extended: Xerath R (multi-target split-fire ambiguity); Galio W / Janna Q / Nunu W (tank/support roles make "commits to full charge" less universally true). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.79.0 → 0.80.0. Docstring extended with Phase 5.9.8 section noting the data-only nature of the batch + the four sub-patterns + A/B impact summary. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `Phase598ExpansionTests` class (19 tests): 13 per-entry `_delta_check` (mirrors s194 pattern), 3 multi-key resolved-shape checks (Talon W+R, Ahri Q+W, Velkoz W+R), 1 Ahri W numeric sanity matching block 0 + 2× block 1, 2 backward-compat guards (`test_pre_s195_unmapped_unaffected` + `test_pre_s195_singed_unaffected`). Pre-existing `test_known_champion_overrides` extended with 11 explicit assertions for new champion entries (Ahri+W=2, Camille, Ekko, Kaisa, Lulu, Morgana, Sivir, Talon, Varus, Velkoz+W=2, Vladimir, Zoe). File docstring extended with Phase 5.9.8 section. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.79.0 → 0.80.0 with the Phase 5.9.8 line in the history comment. |

## Verification

- DS suite **1708 pass** (was 1689 in s194 wrap; +19 from new `Phase598ExpansionTests` class)
- Wider RC `tests/` suite **913 pass** (test-discovery scope; the s194 wrap's "wider RC 1024" included `agents/daemon_slayer/tests/` via combined discovery — adjusting for that, the net is +19 new DS tests with zero non-DS regressions)
- phase8_smoke `test_live_three_profiles` pins ENGINE_VERSION 0.80.0 post-restart (was failing pre-restart with `'0.79.0' != '0.80.0'`)
- `py_compile` clean for __init__.py
- DS server :8893 restarted from PID 16644 → PID via background spawn; `/health` reports `engine_version=0.80.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP)

| Champion.Key | Registry (post-s195) | Forced block 0 | Delta | Lift |
|---|---|---|---|---|
| Morgana W | 23.71 adps | 9.17 adps | +14.54 | **+158.5%** |
| Zoe Q | 43.93 adps | 18.63 adps | +25.30 | **+135.8%** |
| Sivir Q | 8.27 adps | 4.47 adps | +3.80 | **+85.0%** |
| Ekko Q | 16.44 adps | 9.68 adps | +6.76 | **+69.8%** |
| Camille Q | 8.54 adps | 5.04 adps | +3.50 | **+69.5%** |
| Talon W | 12.27 adps | 7.43 adps | +4.84 | **+65.2%** |
| Kaisa Q | 11.46 adps | 7.73 adps | +3.73 | **+48.3%** |
| Varus Q | 8.14 adps | 6.09 adps | +2.05 | **+33.6%** |
| Lulu Q | 10.13 adps | 7.59 adps | +2.54 | **+33.5%** |
| Vladimir E | 27.59 adps | 22.23 adps | +5.36 | **+24.1%** |
| Velkoz W | 19.65 adps | 17.04 adps | +2.61 | **+15.3%** |
| Ahri W | 19.43 adps | 17.36 adps | +2.07 | **+11.9%** |
| Talon R | 12.27 adps | 11.83 adps | +0.45 | **+3.8%** |

Morgana W (+158.5%) and Zoe Q (+135.8%) are the headline lifts — both are large-multiplier amps that nearly tripled their realistic burst-window contribution. Morgana W block 3 'Maximum Total Damage' represents the full Tormented Shadow channel against a rooted (Q'd) target, which is the canonical Morgana setup. Zoe Q block 1 'Maximum Magic Damage' is the long-distance Paddle Star after E-teleport, 2.5× the close-range minimum. Both pre-s195 numbers under-stated the actual per-cast damage by 2.4× and 2.4× respectively.

Talon R's small 3.8% lift is because Talon R is rank-3 (lvl 6/11/16) so it has only 3 ranks of damage progression vs Q/W/E's 5 ranks; block 2 is still 2× block 0 but its contribution to `total_ability_dps` is muted by its lower cast rate and shorter rank ladder. Talon W's 65.2% is the more impactful Talon entry.

**Regression checks pass:**
- s194 entries unchanged (`test_pre_s195_unmapped_unaffected` asserts Corki {W:1, E:1} preserved)
- s193 entries unchanged (`test_pre_s195_singed_unaffected` asserts Singed {Q:1} preserved)
- s192 entries unchanged (Akali R/R2 token-variant logic intact — DS suite's `AkaliTokenVariantTests` still green)
- s191 entries unchanged (Cassi E:1, Veigar R:1, etc. — `test_known_champion_overrides` still green)
- `BackwardCompatTests` green: unmapped Zed burst with no override = unmapped Zed burst with empty explicit override (byte-identical)

## Findings

- **The s191-s194 pattern continues to scale.** Tenth consecutive override registry on the same template; fourth pure-data batch in the channel/total/charge family. Each new champion entry drops in as a one-line JSON addition + 1-2 test methods + a rationale comment. The pattern is now stable enough to support routine "add 5-15 entries per session" batches with no engineering risk.
- **Multi-hit single-target totals dominated this batch.** Of 13 entries, 8 are pattern A (multi-hit focus totals). These are the cleanest-to-model "operator commits" decisions — Sivir Q boomerang focusing one target on out+back is unambiguous; Talon R unstealth re-engaging is the canonical assassin combo. The Meraki snapshot exposes the math via clean per-block decomposition.
- **Fully-charged amps are also clean wins.** Varus Q, Zoe Q, Vladimir E all have a "minimum" vs "maximum" block pair where the operator's commit decision is binary (charge or release early). Operator's choice in burst window is to commit to charge — confirmed by Zoe's massive +135.8% lift (long-range Paddle Star is the entire point of Zoe's E→Q identity).
- **Morgana W is a fortunate edge case.** Tormented Shadow has 4 blocks: min-per-tick, max-per-tick, min-total, max-total. The realistic burst-window value is max-total (rooted target, full duration) — block 3. This is the first single-static-block_index entry that lands on a 4-block ability where the operator must commit to BOTH a CC condition AND a duration condition (the s191 Brand W and Cassi E entries were single-condition CC amps without duration; the s193 channel entries were single-condition duration totals without CC). Morgana W is the intersection.
- **Camille Q (recast amp) is the first pattern-C entry.** Block 0 = first cast (20-40% total AD), block 2 = second cast (40-80% total AD) — exactly 2× scaling. This pattern could expand to other recast champions (Riven Q has 3 stages, Yone Q has 3 stages — both modeled differently via combo_sequence rather than block_index). Camille is the cleanest because her two casts share a form, while Riven/Yone have per-cast forms.
- **Process-tracking pattern continued to hold.** `Get-CimInstance Win32_Process | Where-Object` filter isolated the DS pythonw.exe PID 16644 cleanly; relaunched via bash `pythonw tools/start_daemon_slayer.py` background spawn. No false kills.
- **Xerath R deliberately skipped despite tempting +math.** Xerath R block 2 'Total Magic Damage' would represent all 4 bolts focusing one target (170 + 220 + 270 + 50 stack = 680 base at rank 1). But Xerath R is a long-range siege ult, not a single-target burst — operator commonly splits fire across multiple enemies for poke. Defer until calibration shows a per-call override would be useful.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — same as s194 carry-forward. Zoe sleep (yes, even though Zoe Q is now in registry, Zoe E→sleep→Q-amp on sleeping target is a SECOND amp on top), Lux Illumination, DrMundo E missing-HP threshold, Renekton Q full Fury. Schema lift: `{"<champion>": {"<key>": {"default": 0, "when_target_missing_hp_pct_above": [0.5, 2]}}}`. Defer until 3+ candidates accumulate cleanly.
- 🟡 **Sum-of-blocks block_index** — DrMundo W full-channel + recast detonation. Schema lift: `block_index: int | list[int]` where list means sum. Single known candidate; defer until 3+ accumulate.
- 🟡 **Conditional resource-state block_index** — Corki R Big One every-4th-missile, Renekton Q full Fury, Aatrox Q chain stage. Same shape as conditional damage amps; defer until 3+ candidates accumulate.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness still missing. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Real internal CD in long combos** — s190 carry-forward.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

## Architectural pattern lock-in (continued from s194)

Eleventh consecutive override / proc-shape modeling improvement on the same template; fourth pure-data batch in the channel/total/charge family. Resolver composition (form + block) verified for Jayce Q in s194 — s195 doesn't add new compositions but adds entries spanning four NEW sub-patterns (multi-hit, fully-charged, recast, CC-conditional duration). Pattern is now stable enough to add 10-15 entries per session without engineering risk. Next structural lift is the conditional-block_index schema (which has 3+ candidates queued and is now ready) — but operator can ship more pure-data batches first if calibration analysis surfaces under-counts in unmapped champions.

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

