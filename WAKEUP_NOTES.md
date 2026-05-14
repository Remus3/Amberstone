# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 + s199 + s200 + s201 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

# s204 wrap — 2026-05-14 (Phase 5.9.17 block_index expansion — 8 entries / 2 new champs + 6 extensions + form_index seed)

**Operator instruction:** "continue DS" — direct continuation of s203 (now the **twentieth** consecutive override / proc-shape ship on the same template, **thirteenth** pure-data batch in the block_index family). This batch closes the s203 carry-forward "Riven form_index seed needed for form-conditional block_index entries" — Riven becomes the first new champion added to the form_index registry since s187 (Nidalee/Elise/Jayce/Hwei/LeeSin). Cumulative coverage 67% → 68% of the 171-champion roster.

## One new architectural pattern discovered s204

**Second NET-damage layering of block_index on form_index** (after s203 LeeSin Q). Riven is a particularly clean case: form 0 "Blade of the Exile" has ZERO damage blocks (pure buff/empower form), and form 1 "Wind Slash" carries the only damage. The form_index seed routes the parser to form 1; block_index = 1 then selects max-missing-HP execute within that form. No information loss from routing past form 0 since it's data-empty. Nidalee Q (Cougar Takedown) form 1 block 1 ships in the same batch — both are execute-amp layers, both compose orthogonally with their prior form_index entries.

## Sub-patterns reused

- **Multi-hit single-target totals (3 entries):** Evelynn Q (Hate Spike 7-missile rotation, 175% AP scaling), Gwen Q (max-stack 6-snip burst, 10.3× block 0 base), Syndra W (Force of Will Total Mixed sum, 1.12× — small additive but consistent under-count).
- **Fully-charged amp (1 entry):** KSante W (Path Maker full 2s charge Total Maximum Mixed, 1.8× block 0).
- **Champion-vs-minion amp (1 entry):** Seraphine Q (High Note Maximum Champion Damage 1.75×). Revives s198/s202 'enchanter-class' skip under archetype-mismatch framing — direct /ability-dps queries benefit even though Seraphine dispatches to ds.hps.
- **Execute amp layered on form_index (1 entry):** Nidalee Q (Cougar Takedown low-HP execute via s187 form_index=1). Second NET-damage layering after s203 LeeSin Q.
- **Target-state amp (1 entry):** Zoe E (Maximum Mixed on sleep-procced target, 2× block 0). First entry reviving the conditional target-state schema lift bucket under unconditional operator-commits framing — same as Khazix Q isolation s196 / Xerath W center-spot s201 / Vayne E wall-stun s202.
- **Form_index seed expansion (1 entry):** Riven R + new form_index Riven.R = 1 (Wind Slash max-missing-HP execute). Closes s203 carry-forward. First new champion added to form_index registry since s187.

## s204 ship — Phase 5.9.17 — 8 entries

Live A/B headlines on :8893 (/ability-dps lvl 11 vs 80 armor / 30 MR / 2000 HP) — TOTAL ability_dps deltas (per-spell preview deltas in parens):

| Champion | Key | Pattern | total adps off → on | Lift |
|----------|-----|---------|---------------------|------|
| Evelynn | Q | full Hate Spike (7× missile) | 19.78 → 86.98 | **+339.7%** (per-spell +667%) |
| Gwen | Q | max-stack Snip Snip (10× base) | 8.80 → 23.65 | **+168.7%** (per-spell +934%) |
| Nidalee | Q | cougar Takedown low-HP exec | 39.02 → 68.51 | **+75.6%** (per-spell +175%) |
| Seraphine | Q | Max Champion Damage | 11.11 → 17.02 | **+53.2%** |
| KSante | W | Path Maker full charge | 8.48 → 9.99 | **+17.8%** |
| Syndra | W | Total Mixed sum | 28.06 → 29.23 | **+4.2%** |
| Zoe | E | sleep-procced Max Mixed | 44.53 → 45.99 | **+3.3%** |
| Riven | R | Wind Slash form 1 exec | 57.80 → 59.43 | **+2.8%** (was 0.00 baseline) |

**Spell-share dilution** explains why Gwen Q's per-spell +934% translates to total +168.7% (Gwen R already contributes 6.79 dps so Q is one of 3 contributors). Riven R total lift +2.8% is small because Riven's Q (Broken Wings) dominates at 54.84 dps — but architecturally significant since R was contributing 0.00 pre-s204 due to form 0 having no damage blocks. Zoe E +3.3% similar — Zoe's Q dominates at 42.17 dps.

| Commit | Summary |
|--------|---------|
| [`1003ed9`](https://github.com/Remus3/riot-commander/commit/1003ed9) | s204 feat — 8-entry Phase 5.9.17 block_index + Riven form_index seed + 2 NET-damage form_index×block_index layerings |

Registry: 115 → 117 champions. Entries: 173 → 181. Form_index registry: 5 → 6 champions, 9 → 10 entries (Riven R=1 new). ENGINE_VERSION: 0.88.0 → 0.89.0. DS suite: 1919 → 1939 (+20 net tests). Wider RC: 1023 + 1 expected phase8_smoke pass post-restart.

**Test-fixture maintenance:** 5 stale assertions in `test_known_champion_overrides` converted from full-shape `assertEqual` to either commented-out OR migrated to Phase599_17 block (Evelynn / Syndra / Riven / KSante / Zoe — all extended this batch). 1 stale `test_zoe_both_keys_in_resolved` in `Phase599_15ExpansionTests` converted from full-shape `assertEqual` to per-key `.get()` subset check (Zoe now has 3 keys after s204 added E=2). 1 `test_rank_assassin_carries_source` updated for new Evelynn shape `{R:1, Q:5}`.

## Tomorrow / future sessions

**All s203 carry-forwards remain unchanged except Riven (closed):**

- 🟡 **Token-variant for multi-stage Q chains** — Aatrox Q1/Q2/Q3 (combo_sequence-aware), Gwen R needlework recasts (already partially handled via block_index=4 for full burst).
- 🟡 **Form-swap block_index schema** — KSante R full per-form indexing, Kayn (Rhaast/Shadow Q), Hwei (Q/W/E forms 0/1/2/3), **Qiyana Q** (s203 + s204 deferred — needs form_index registry seed for elemental form, same pattern Riven shipped this batch).
- 🟡 **Sequence-state block_index** — Jhin R 4th-shot, Corki R Big One every-4th-missile, Akshan R Comeuppance charge.
- 🟡 **Conditional target-state block_index** — Zoe sleep amp now SHIPPED (s204) under operator-commits framing. Remaining: Lux Illumination, DrMundo E missing-HP threshold, Evelynn Q charm, Vayne E wall-stun, Kayle E missing-HP, Kindred E mark detonation. 6+ candidates still queued — schema lift becomes warranted if 3+ ship under operator-commits framing first.
- 🟡 **Sum-of-blocks schema** — STILL 8+ candidates: Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Camille W flat+max-HP (s202) + Katarina R bAD+AP, Malphite W first+subsequent, Malzahar E/R on-cast+DOT, Kalista E per-stack, Jinx R distance-scaled (s203). Lift continues to be warranted.
- 🟡 **Nested missing-HP parser** — Kindred E (s201 drop), Kayle E (s202 drop), Belveth R execute curve (s203 drop). Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.

## Hand-off notes

- **Tryndamere remains canonical unmapped fixture** (s201 rotation). No change s204.
- **Evelynn now has 2 keys** (R s191 + Q s204). Assassin archetype.
- **Gwen now has 2 keys** (R s203 + Q s204). Mage/bruiser hybrid.
- **KSante now has 2 keys** (R s202 + W s204). Tank/bruiser hybrid.
- **Riven now has 2 keys** (Q s196 + R s204) + form_index R=1 entry. Bruiser archetype.
- **Syndra now has 2 keys** (R s195 + W s204). Mage archetype.
- **Zoe now has 3 keys** (Q s195 + W s202 + E s204). Mage archetype.
- **Nidalee + Seraphine** are the 2 truly-new champions this batch.
- **DS server restart required** after ENGINE_VERSION bump. Via PowerShell `Stop-Process -Id <pid> -Force` then `Start-Process pythonw start_daemon_slayer.py -WindowStyle Hidden -WorkingDirectory "C:\Riot Commander"`. /health confirms 0.89.0.

## s204 architectural delta

Twentieth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority → s186 combo → s187 form → s188 per-AA on-hit → s189 Spellblade → s190 Lightshield → s191 block_index → s192 token-variant → s193 channels → s194 calibration → s195 multi-hit → s196 condition-amp → s197 assassin/fighter → s198 bruiser broadening → s199 standard sweep → s200 rescue → s201 framing revert → s202 wall-stun framing revert + broadening → s203 active-cast vs passive-zap split + empty-block-0 fix + form_index×block_index NET-damage layering → s204 form_index seed expansion + second NET-damage layering + target-state amp revival). Thirteenth pure-data batch in the channel/total/charge family. Second batch to expand form_index registry (s187 was the seed). **Cumulative coverage: 181 (champion, key) entries across 117 champions** (68% of the 171-champion roster touched). Pattern remains rock-solid; rate-limit is now (a) sum-of-blocks schema lift becoming necessary (8+ candidates queued), (b) Qiyana Q form_index seed needed before next form-conditional block_index batch.

---

# s203 wrap — 2026-05-14 (Phase 5.9.16 block_index expansion — 12 entries / 5 new champs + 5 extensions)

**Operator instruction:** "continue DS" — direct continuation of s202 (now the **nineteenth** consecutive override / proc-shape ship on the same template, **twelfth** pure-data batch in the block_index family). This batch closes the assassin/bruiser-heavy candidate well: 5 brand-new champions (Blitzcrank, Gwen, Kled, LeeSin, Thresh) + 5 key extensions on existing champions (Diana R, Jax R, Kennen W, Smolder E, Vladimir Q). Cumulative coverage 64% → 67% of the 171-champion roster.

## Two new architectural patterns discovered s203

1. **Empty-block-0 fix** — Thresh E. Engine default `block_strategy="first"` selects `damage_blocks[0]` after filtering. Thresh E filtered idx 0 = raw block 0 has only unparsed `1.7 per Soul collected` (no base, no AP, no tAD) and `_evaluate_block` returns 0 for it. Pre-s203, Thresh E ability_dps was literally 0. Setting block_index=2 routes to the canonical 75-255 + 70% AP magic damage component. First instance of this fix pattern; DrMundo Q has similar shape but rejected because its block 0 has actual scaling (target_current_hp_pct 20-30% × target HP).

2. **NET-damage layering of block_index on form_index** — LeeSin Q. s187 already set LeeSin Q form_index=1 (Resonating Strike form). s203 adds block_index=1 within form 1 (max-missing-HP variant, 2× block 0 bAD). Two orthogonal resolvers compose at runtime: form_index selects Resonating Strike form 1 → block_index then selects max-missing-HP block 1 within that form. First time block_index extension adds NET damage on top of a form_index entry — Jayce Q s194 was the smaller-magnitude precedent.

## Sub-patterns reused

- **Multi-hit single-target totals (5 entries):** Diana R full Moonfall channel, Gwen R 9-needle 3-cast, Kled Q 3-stage Beartrap reel, Kled E 2-strike Jousting, Vladimir Q Crimson Rush full-stack.
- **Active-cast vs passive-zap split (3 entries):** Blitzcrank R / Kennen W / Jax R — engine default block 0 was scoring the passive (per-zap / per-4th-AA mark / passive 3rd-AA) as the R/W cast value, which is per-AA scaling not per-cast.
- **Resource-state amp (1 net new):** Smolder E max-stack (reverts s198/s202 'Meraki Minimum label ambiguity' skip — same operator-commit framing as Smolder Q s202 successful reintroduction).
- **Max-charge condition amp (1 entry):** Kled R fully-charged Skaarl-remount.

## s203 ship — Phase 5.9.16 — 12 entries

Live A/B headlines on :8893 (/ability-dps lvl 11 vs 80 armor / 30 MR / 2000 HP):

| Champion | Key | Pattern | adps off → on | Lift |
|----------|-----|---------|---------------|------|
| Gwen | R | 9× full burst | 2.76 → 8.80 | **+218.4%** |
| Kled | all 3 | combined Q+E+R registry | 7.36 → 17.26 | **+134.4%** |
| Vladimir | Q | Crimson Rush full-stack | 28.09 → 43.19 | **+53.8%** |
| LeeSin | Q | form 1 max-missing-HP | 9.99 → 14.62 | **+46.4%** |
| Blitzcrank | R | active vs passive zap | 4.60 → 5.96 | **+29.4%** |
| Thresh | E | empty-block-0 fix | 6.45 → 7.21 | **+11.8%** |
| Kennen | W | active vs passive 4th-AA | 18.74 → 20.18 | **+7.6%** |
| Smolder | E | max-stack Achooo! | 20.76 → 22.16 | **+6.7%** |
| Diana | R | Moonfall full channel | 16.91 → 17.80 | **+5.3%** |
| Jax | R | active 3-AA total | 15.65 → 15.82 | **+1.1%** |

**Reverts 1 prior skip rationale:** Smolder E (s198/s202 'Meraki Minimum schema label ambiguity' → s203: re-framed under operator-commits-to-max-stacks). All 12 verified per-rank against Meraki snapshot. 4 of 12 entries have non-damage prefix blocks stripped pre-index (filtered idx ≠ raw idx): Diana R (raw 0 'Slow'), Kled Q (raw 1 'modifier' + raw 4 'slow'), Kled R (raw 0-1 'shield'), Vladimir Q (raw 1 'Heal').

| Commit | Summary |
|--------|---------|
| (pending) | s203 feat — 12-entry Phase 5.9.16 block_index expansion + Smolder E revert + first empty-block-0 fix + first NET-damage block_index×form_index layering |

Registry: 110 → 115 champions. Entries: 161 → 173. ENGINE_VERSION: 0.87.0 → 0.88.0. DS suite: 1894 → 1919 (+25 net tests). Wider RC: 1024 green post-DS-restart.

**Test-fixture maintenance:** 2 stale assertions in earlier `Phase599_11ExpansionTests.test_vladimir_both_keys_in_resolved` + `Phase599_15ExpansionTests.test_smolder_all_three_keys_in_resolved` converted from `assertEqual(resolved, exact_dict)` to per-key `.get()` subset checks, since s203 added keys without removing the s197/s198/s202 entries.

## Tomorrow / future sessions

**All s199/s200/s201/s202 carry-forwards remain unchanged:**

- 🟡 **Token-variant for multi-stage Q chains** — Aatrox Q1/Q2/Q3 (combo_sequence-aware), Gwen R needlework recasts (already partially handled via block_index=4 for full burst).
- 🟡 **Form-swap block_index schema** — KSante R full per-form indexing, Kayn (Rhaast/Shadow Q), Hwei (Q/W/E forms 0/1/2/3), Riven R form 1 (s203 deferred — needs form_index registry seed for Riven), Qiyana Q (s203 deferred — needs form_index registry seed for elemental form).
- 🟡 **Sequence-state block_index** — Jhin R 4th-shot, Corki R Big One every-4th-missile, Akshan R Comeuppance charge.
- 🟡 **Conditional target-state block_index** — Zoe E sleep amp, Lux Illumination, DrMundo E missing-HP threshold, Evelynn Q charm, Vayne E wall-stun, Kayle E missing-HP, Kindred E mark detonation. 7+ candidates queued.
- 🟡 **Sum-of-blocks schema** — NOW 8+ candidates: Thresh E souls+magic, Taliyah E impact+detonations, Sona Q spell+Power Chord, Camille W flat+max-HP (s202) + Katarina R bAD+AP, Malphite W first-AA+subsequent, Malzahar E/R on-cast+DOT, Kalista E per-stack accumulation, Jinx R distance-scaled (s203). Lift is increasingly warranted.
- 🟡 **Nested missing-HP parser** — Kindred E (s201 drop), Kayle E (s202 drop), Belveth R execute curve (s203 drop). Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.

## Hand-off notes

- **Tryndamere remains canonical unmapped fixture** (s201 rotation). No change s203.
- **Kled is the first 3-key new-champion entry in a single batch** since s202's Rumble. Bruiser broadening continues from s198.
- **Vladimir now has 3 keys** (E s195 + W s198 + Q s203). Mage archetype.
- **Smolder now has 4 keys** (W s197 + Q s202 + R s202 + E s203). Carry archetype.
- **DS server restart required** after ENGINE_VERSION bump. Via PowerShell `Stop-Process -Id <pid> -Force` then `Start-Process pythonw start_daemon_slayer.py -WindowStyle Hidden -WorkingDirectory "C:\Riot Commander"`. /health confirms 0.88.0.

## s203 architectural delta

Nineteenth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority → s186 combo → s187 form → s188 per-AA on-hit → s189 Spellblade → s190 Lightshield → s191 block_index → s192 token-variant → s193 channels → s194 calibration → s195 multi-hit → s196 condition-amp → s197 assassin/fighter → s198 bruiser broadening → s199 standard sweep → s200 rescue → s201 framing revert → s202 wall-stun framing revert + broadening → s203 active-cast vs passive-zap split + empty-block-0 fix + form_index×block_index NET-damage layering). Twelfth pure-data batch in the channel/total/charge family. **Cumulative coverage: 173 (champion, key) entries across 115 champions** (67% of the 171-champion roster touched). Pattern remains rock-solid; rate-limit is now (a) sum-of-blocks schema lift becoming necessary (8+ candidates queued), (b) form_index registry seed expansion for Riven/Qiyana before next form-conditional block_index batch.

---

# s202 wrap — 2026-05-14 (Phase 5.9.15 block_index expansion — 18 entries / 6 new champs + 12 extensions)

**Operator instruction:** "continue ds" — direct continuation of s201 (now the **eighteenth** consecutive override / proc-shape ship on the same template, **eleventh** pure-data batch in the block_index family). This batch broadens coverage further to 64% of the 171-champion roster (was 61% pre-s202).

## Context

Re-scanning unmapped champs found 30 candidates across 20 unmapped champions plus 27 candidate extensions on already-mapped champions. Triaged to 18 entries:
- 6 truly-new champions: Gangplank, Gnar, KSante, RekSai, Vayne, Yunara
- 12 key extensions on existing: Zoe W, Akshan R, AurelionSol Q, Nasus R, Poppy E, Renekton R, Rumble Q+R, Smolder Q+R, Viktor E, Yuumi R

The framing-revert pattern emerged again across 4 prior-batch skips — all wall-stun / heat-decay conditional skips re-framed under operator-commit:
- **Gnar R** (s198 'wall-stun terrain target-state') → same operator-commits framing as Khazix Q isolation s196 / Xerath W center-spot s201
- **Vayne E** (s198 'wall-stun terrain') → same wall-stun framing
- **Poppy E** (s199 'wall-state target condition') → same
- **Rumble Q** (s199 'Danger Zone heat decays mid-fight') → operator commits to overheat Q burst window

## s202 ship — Phase 5.9.15 — 18 entries, five patterns

**Pattern A multi-hit single-target totals (5):** KSante R=2 (All Out dash+wall-strike 2×), Vayne E=2 (Condemn wall-slam total 2.5×), Yunara Q=2 filtered (Combined Passive+Active 2×), Zoe W=1 filtered (3 empowered AAs 3×), Viktor E=2 (Death Ray double-hit 1.29×).

**Pattern B channel/duration totals (7):** Gangplank R=2 (4-wave Cannon Barrage 12× per-wave), AurelionSol Q=2 (Breath of Light full channel 26×), Nasus R=1 filtered (Dominus full 15s target_max_hp 30×), Renekton R=1 filtered (Dominus full duration 30×), Rumble R=2 (Equalizer max channel 10×), Yuumi R=2 filtered (Final Chapter 2 hits per target 2×), Poppy E=1 filtered (Heroic Charge wall-slam 2×).

**Pattern C max-charge/distance amps (2):** Akshan R=1 filtered (Comeuppance max-charge 3×), Smolder R=1 filtered (Mouth of the Abyss max-distance 1.5×).

**Pattern D resource-state amps (2):** RekSai E=1 (Furious Bite max Fury true damage 1.25×), Smolder Q=1 (max-stack passive 1.75× — gear-INdependent, not the Infinity Edge variant which is gear-conditional).

**Pattern E wall-stun / charge condition amps (2):** Gnar R=1 filtered (GNAR! wall-stun 1.5×), Rumble Q=2 filtered (Danger Zone overheat Total Enhanced 1.5×).

**Filtered-idx semantics (s199 lesson re-applied):** 9 of 18 entries have non-damage prefix blocks. Most notable: Nasus R raw 0-2 'Bonus Health' / 'Bonus Resistances' / 'Increased Size' → filtered idx 1 = raw 4. Yuumi R raw 0-1 + 5-6 heal blocks → filtered idx 2 = raw 4. Yunara Q raw 1 duration + 4-5 modifiers → filtered idx 2 = raw 3.

**Live A/B headlines on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP):** AurelionSol Q **+351.6%** (3.29 → 14.85 — Breath of Light full channel is dominant), Renekton R **+68.8%** (11.43 → 19.29 — Dominus full duration aura), Smolder Q **+51.6%** (13.70 → 20.76 — max-stack passive scaling), Nasus R **+48.4%** (9.73 → 14.44), Rumble Q **+18.4%**, Gangplank R **+17.1%**, Rumble R **+9.0%**, RekSai E **+7.1%**, Vayne E **+5.9%**, KSante R **+5.7%**, Yunara Q **+4.0%**, Yuumi R **+3.8%**, Viktor E **+3.1%**, Gnar R **+2.3%**, Smolder R **+2.0%**, Poppy E **+1.8%**, Zoe W **+1.4%**, Akshan R **+0.9%**. Smaller percentages reflect spell-share dilution where the new key is correct but the champion's other spells already dominate total ability_dps.

**6 deliberate skips documented inline:** Syndra W (1.12× too marginal), Camille W (Outer Cone Bonus is target_max_hp_pct ONLY without flat damage; needs sum-of-blocks), Yunara W (block 0 'Initial' is HIGHER than block 2 'Total Expanded' — engine default correct), Smolder E (Meraki 'Minimum' label ambiguity carried from s198), Sona Q (Power Chord bonus needs sum-of-blocks), Kayle E (Phase 4a parser limit — same family as s201 Kindred E drop).

## Ships this session

| Commit | Theme |
|---|---|
| [`723fb1c`](https://github.com/Remus3/riot-commander/commit/723fb1c) | s202 feat — 18-entry block_index + 4 prior-skip wall-stun reverts |

Registry: 104 → 110 champions. Entries: 143 → 161. ENGINE_VERSION: 0.86.0 → 0.87.0. DS suite: 1866 → 1894 (+28 net tests). Wider RC unchanged.

**Test-fixture maintenance:** 7 stale assertions in `test_known_champion_overrides` for champions extended this batch (AurelionSol/Akshan/Zoe/Poppy/Renekton/Rumble/Smolder/Nasus/Viktor/Yuumi) commented out in favor of the new s202-block assertions. 3 multi-key resolved-shape sanity tests updated in earlier Phase599 expansion classes (Renekton/Viktor/Poppy now include new R/E keys).

## Carry-forward for tomorrow

**All s199/s200/s201 carry-forwards remain unchanged:**
- 🟡 **Token-variant for multi-stage Q chains** — Aatrox Q1/Q2/Q3 with combo_sequence, Gwen R needlework. 2+ candidates accumulated.
- 🟡 **Form-swap block_index schema** — KSante R full per-form indexing (current s202 ships R=2 which works for All Out form; per-form schema needed for Q/W/E during All Out which have different blocks), Kayn (Rhaast/Shadow Q), Hwei (Q/W/E forms 0/1/2/3).
- 🟡 **Sequence-state schema** — Jhin R 4th-shot recast, Corki R Big One every-4th-missile within ult, Aphelios stance rotation.
- 🟡 **Conditional target-state schema lift** — 5+ candidates queued: Zoe sleep (E→Q), Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Vayne W silver bolts.
- 🟡 **Sum-of-blocks schema** — NOW 4+ candidates: Thresh E souls+magic (s201), Taliyah E impact+detonations (s201), Sona Q spell+Power Chord (s202), Camille W flat+max-HP (s202). Lift is warranted soon.
- 🟡 **Nested missing-HP parser** — Kindred E (s201 drop), Kayle E (s202 drop). Phase 4a `unparsed_modifiers` extractor needs upgrade.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness. Carried since s180.
- 🟡 **Generalized arm-consume framework** — Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

**Don't redo:**
- Sum-of-blocks bucket now has 4+ candidates (Thresh/Taliyah/Sona/Camille) — appropriate to schema-lift next architectural session.
- Nested missing-HP parser bucket has 2 candidates (Kindred/Kayle) — Phase 4a extractor upgrade.
- Yasuo → Tryndamere fixture rotation already done in s201.
- Don't re-defer the 4 wall-stun reverts (Gnar R / Vayne E / Poppy E / Rumble Q) — operator-commit framing is now well-established.

**Next session candidate:** Either (a) sum-of-blocks schema lift (4+ candidates ready, value-additive), (b) form-swap block_index schema (KSante R All Out per-form + Kayn/Hwei forms), or (c) more pure-data — well thinning but still has multi-form (Aphelios stances), Annie tier of remaining unmapped, and a few extensions I deliberately skipped (Camille W with sum, Sona Q with sum, Yunara W reconsideration). Operator pick.

## Architectural pattern lock-in

Eighteenth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority → s186 combo → s187 form → s188 per-AA on-hit → s189 Spellblade → s190 Lightshield → s191 block_index → s192 token-variant → s193 channels → s194 calibration → s195 multi-hit → s196 condition-amp → s197 assassin/fighter → s198 bruiser broadening → s199 standard sweep → s200 rescue → s201 framing revert → s202 wall-stun framing revert + broadening). Eleventh pure-data batch in the channel/total/charge family. **Cumulative coverage: 161 (champion, key) entries across 110 champions** (64% of the 171-champion roster touched). Pattern remains rock-solid; rate-limit now appears to be sum-of-blocks schema lift becoming necessary (4+ candidates queued) before further pure-data expansion can capture the remaining ~50 candidates that need block-sum semantics.
