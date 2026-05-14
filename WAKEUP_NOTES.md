# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 + s198 archived to docs/history_notes.md. Only the last 3 sessions kept here.

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

# s201 wrap — 2026-05-14 (Phase 5.9.14 block_index expansion — 16 entries / 13 champs)

**Operator instruction:** "continue ds" — direct continuation of s200 (now the **seventeenth** consecutive override / proc-shape ship on the same template, **tenth** pure-data batch in the block_index family). The pure-data well still had clean candidates after nine prior batches. This batch reverts 4 prior-batch skip rationales by re-framing them under the established "operator commits to canonical-amped condition" model, and adds 4 cleanly-new entries plus 8 more under the standard multi-hit / fully-charged / channel patterns.

## Context

Re-scanning the abilities snapshot for unmapped champions surfaced 47 candidate (champion, key) tuples across 33 unmapped champions. Triaged to 17 entries → dropped Kindred E during implementation (engine cannot read nested missing-HP coefficient from `unparsed_modifiers`), shipping 16 entries final.

The framing-revert pattern emerged across 4 prior-batch skips:
- **Xerath W** (s198 'positional condition, defer to conditional schema lift') → aligned with Khazix Q isolation framing already shipped s196 — operator commits to center positioning is the same intuition as committing to isolation. Same unconditional override schema, no conditional schema needed.
- **Ziggs E** (s198 'unrealistic 5-mine focus') → operator commits to chokepoint setup with all 5 mines on entry path. Same model as Ashe Q 5-AA focus shipped s199 / Mel Q 6-projectile s197 / Skarner Q 3-hit s196.
- **Janna Q** (s198 'low ratio + support') → 1.55× amp is consistent under-count worth fixing; Janna's `/ability-dps` is valid even for support builds (Yuumi Q also support and shipped s198).
- **Yasuo E** (s198 'stacks decay 10s') → operator commits to E-stacking in burst setup, same resource-state framing as Twitch E 6-stack pre-burst rotation (s198) and Tristana E max-stack (s199).

## s201 ship — Phase 5.9.14 — 16 entries, four patterns

**Pattern A multi-hit single-target totals (7):** Graves Q=2 (buckshot + return 2.89×), Jhin Q=2 (Maximum Final Bounce 2.05×), Kennen R=1 filtered (Total Single-Target 7.5× per-bolt), Taliyah Q=2 (5-stone Worked Ground 2.6×), Teemo E=2 (Total Poison 4-tick DOT 2.67×), Xerath R=1 filtered (Total Magic all bullets 4-6×), Ziggs E=2 (5 mines focused 5×).

**Pattern B fully-charged amps (4):** Galio W=1 filtered (Shield of Durand 2s commit 3×), Janna Q=2 (Howling Gale 3s max-charge 1.55×), Jhin R=1 (Maximum max-distance 4×), Viego Q=3 (fully-charged Soul Steal AA 2×).

**Pattern C channel/duration totals (3):** Fizz R=2 (Gigalodon max-distance 2×), Garen E=1 (Increased per spin 1.25×), Teemo R=1 filtered (Total Magic 4-tick poison 4×).

**Pattern D resource/positional amps (2):** Xerath W=1 (Increased center-spot 1.67×), Yasuo E=3 (Total Combined max stacks 2×).

**Filtered-idx semantics (s199 lesson re-applied):** 4 entries have non-damage prefix blocks. Galio W raw block 0 'Magic Shield Strength' + 1-2 'Damage Reduction' → filtered idx 1 = raw 4. Kennen R raw block 0 'Bonus Resistances' → filtered idx 1 = raw 2. Teemo R raw blocks 0-2 non-damage → filtered idx 1 = raw 4. Xerath R raw block 0 'Number of Recasts' → filtered idx 1 = raw 2.

**Live A/B headlines on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP):** Taliyah Q **+138.2%** (5-stone Worked Ground), Graves Q **+104.5%** (4-shell ricochet), Xerath R **+77.0%** (4-6 bullets focused), Teemo R **+62.5%** (4-tick shroom), Viego Q **+52.9%** (fully-charged AA), Jhin Q **+36.0%** (Max Final Bounce), Janna Q **+32.4%** (3s max-charge), Jhin R **+23.2%** (Max distance), Yasuo E **+21.5%** (Total Combined max stacks), Kennen R **+11.7%**, Ziggs E **+9.7%**, Fizz R **+8.0%**, Galio W **+7.9%**, Xerath W **+6.0%**, Garen E **+3.5%**, Teemo E **+1.5%**. Viego /burst +88.22 burst damage (Q=3 propagates through burst walker too).

**6 deliberate skips documented inline:** Seraphine Q (Maximum Champion HP threshold; Seraphine routes to ds.hps), Taliyah E (1.04× marginal ratio + misses initial impact), Thresh E (per-soul scaling needs sum-of-blocks framework), Nidalee W (conflicts with s187 form_index=1 cougar Pounce), Shyvana E (Phase 4a parsing produces malformed interpolated base values), **Kindred E** (was in initial draft; dropped during implementation because Phase 4a parser cannot extract nested per-mark missing-HP coefficient from `unparsed_modifiers` — both blocks have identical base + bAD, registry entry would be a no-op).

## Ships this session

| Commit | Theme |
|---|---|
| [`9365f5c`](https://github.com/Remus3/riot-commander/commit/9365f5c) | s201 feat — 16-entry block_index + 4 prior-skip reverts |

Registry: 91 → 104 champions. Entries: 127 → 143. ENGINE_VERSION: 0.85.0 → 0.86.0. DS suite: 1842 → 1866 (+24 net tests). Wider RC: 913 green post-DS-restart. **Test fixture rotation:** Yasuo → Tryndamere in 7 places where 'stable unmapped champion' was needed (Yasuo landed in registry s201; Tryndamere is now the canonical fixture — Q/E single-block, W/R no damage blocks, will never enter registry).

## Carry-forward for tomorrow

**All s198/s199/s200 carry-forwards remain unchanged:**
- 🟡 **Token-variant for multi-stage Q chains** — Aatrox Q1/Q2/Q3 with combo_sequence + token-variant block_index, Gwen R needlework chain. 2+ candidates accumulated.
- 🟡 **Form-swap block_index schema** — KSante (All Out R), Kayn (Rhaast/Shadow Q), Hwei (Q/W/E forms 0/1/2/3). Schema lift: `{champ: {key: {form_idx: block_idx, ...}}}`.
- 🟡 **Sequence-state schema** — Jhin R 4th-shot recast, Corki R Big One every-4th-missile within ult, Aphelios stance rotation.
- 🟡 **Conditional target-state schema lift** — 5+ candidates queued: Zoe sleep (E→Q on sleeping), Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Vayne E wall-stun.
- 🟡 **Sum-of-blocks schema** — Thresh E souls + active magic, Taliyah E impact + detonations. Single candidates each.
- 🟡 **Nested missing-HP parser** — Kindred E (s201 dropped). Phase 4a `unparsed_modifiers` extractor needs upgrade to handle "X% (+ Y% per Mark) of target's missing health" format.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

**Don't redo:**
- Kindred E was dropped intentionally during s201 implementation — don't re-add to registry until Phase 4a parser improves. Skip-list rationale shipped in registry `_meta.description`.
- Xerath W / Ziggs E / Janna Q / Yasuo E now in registry — don't re-defer them based on stale s198 rationale. The skip rationale was reverted with operator-commit framing aligned to existing patterns (Khazix Q isolation, Ashe Q 5-AA, Yuumi Q support, Twitch E pre-burst stack).
- Yasuo is now in the registry → use **Tryndamere** as the stable unmapped fixture for tests (already updated in 7 places).

**Next session candidate:** Either (a) schema lift for conditional target-state to unlock 5+ queued entries, OR (b) Aatrox Q token-variant + combo_sequence (Aatrox added to s186 combo_sequence registry + Q2/Q3 token-variant block_index entries), OR (c) more pure-data sweep — ~50 candidates remain unmapped though increasingly diluted by other spells or needing schema lifts. Operator pick.

## Architectural pattern lock-in

Seventeenth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo / s187 form / s188 per-AA on-hit / s189 Spellblade / s190 Lightshield / s191 block_index / s192 token-variant / s193 channels / s194 calibration / s195 multi-hit / s196 condition-amp / s197 assassin/fighter / s198 bruiser broadening / s199 standard sweep / s200 rescue batch / s201 framing revert). Tenth pure-data batch in the channel/total/charge family. **Cumulative coverage: 143 (champion, key) entries across 104 champions** (61% of the 171-champion roster touched). Pattern remains rock-solid; the rate-limit continues to be operator triage of skip-list growth (6 skips this batch — manageable) and clean candidate availability. Genuinely-blocking lifts remain token-variant for multi-stage chains, form-swap, sequence-state, conditional target-state, sum-of-blocks, and nested missing-HP parsing.

# s200 wrap — 2026-05-14 (Phase 5.9.12 s199 + Phase 5.9.13 s200 block_index expansion — two batches one session)

**Operator instruction:** "continue ds" (twice) — direct continuation of s198 (now the sixteenth + seventeenth consecutive override / proc-shape ship on the same template). Two pure-data batches shipped in the same Claude session: **s199** is the standard 17-entry sweep (similar size to s197/s198); **s200** is a smaller 7-entry rescue batch focused on resurrecting previously-deferred mechanics after improved understanding.

## Context

Eight prior batches (s191 seed → s193 channels → s194 calibration → s195 multi-hit → s196 condition-amp → s197 assassin/fighter → s198 bruiser/utility) ran the candidate well dry on net-new entries. The carry-forward bucket (token-variant for multi-stage chains, form-swap, sequence-state, conditional target-state) still needs schema lifts. **s199 + s200 together close the pure-data well further while two important discoveries land:** (1) **filtered-index semantics** — the engine's `_select_blocks` filters `attribute_kind != "damage"` blocks BEFORE indexing, so the registry value is the FILTERED damage-block index, not the raw block index; (2) **rescue framing** — several earlier deferrals were too conservative (Ambessa "form swap" was actually Drain-stack resource amp; Anivia R "ambiguous channel" was Empowered phase amp; Lillia/Nilah Q "uncertain" mapped cleanly to existing patterns).

## s199 ship — Phase 5.9.12 — 17 entries, six patterns

**Pattern A multi-hit single-target totals (8):** Ashe Q=2 (Ranger's Focus 5× per-AA), Nunu E=1 (3-snowball cap), Samira W=1 (Blade Whirl 2-rotation), Shen Q=1 filtered (3-AA Twilight Assault), Swain Q=2 (5-bolt point-blank), Viktor Q=2 (Q + empowered AA), Xayah Q=1 (out+return), Zac Q=1 (2-arm pull). **Pattern B positional/sweet-spot amps (3):** Aatrox Q=1 (Q1 Edge sweet-spot), Shaco E=2 (backstab), Talon Q=1 (champion crit). **Pattern C resource-state amps (2):** Tristana E=4 (max-stack), Udyr Q=1 (Awakened 2-AA). **Pattern D channel total (1):** Karthus E=2 (Defile per-second). **Pattern E direct-hit primary (2):** Sejuani R=1, Nautilus R=2. **Pattern F execute amp (1):** Fiddlesticks W=3 (low-HP).

**Filtering note discovery:** When verifying empirically, Shen Q at indexed=2 produced the WRONG block (raw block 3 'Increased Bonus' instead of raw block 2 'Total Magic Damage'). Root cause: `_select_blocks` filters out blocks with `attribute_kind != "damage"` (Shen Q raw block 0 is 'Slow') BEFORE indexing. The registry value is the FILTERED idx, not the raw idx. Shen.Q was corrected from 2 → 1. Four other entries (Ashe Q=2, Karthus E=2, Shaco E=2, Nautilus R=2) accidentally landed on the right filtered idx via `clamp out-of-range to last` semantics. Documented in registry `_meta` description.

**Live A/B headlines:** Shen Q **+113.9%**, Swain Q **+63.0%**, Xayah Q **+62.5%**, Aatrox Q **+56.1%**, Udyr Q **+44.6%**, Viktor Q **+41.9%**, Tristana E **+31.7%**.

## s200 ship — Phase 5.9.13 — 7 entries, rescue batch

**Rescued 4 deferred mechanics:** Ambessa Q/W (s196/s197/s198 'form swap' deferral dissolved — actually Drain-stack resource amp like Renekton Fury); Anivia R (s195 'channel ambiguous' — actually Empowered phase amp like Belveth E max-charge); Lillia Q (s199 'uncertain' — Q + Dream Dust AA combo like Sett Q); Nilah Q (s199 'uncertain 2-stack' — max-stack empowered AA like Twitch E / Tristana E). Plus 2 net-new: Ambessa E (Lacerate slash+thrust 2×), Poppy Q (Hammer Shock out+return 2×).

**Three sub-patterns:** Pattern A multi-hit totals (Ambessa E, Lillia Q, Poppy Q); Pattern B resource-state amps (Ambessa Q, Ambessa W, Nilah Q); Pattern C channel commit (Anivia R Empowered).

**Live A/B headlines:** Nilah Q **+82.0%**, Poppy Q **+75.7%**, Ambessa Q **+37.1%**, Lillia Q **+19.4%**, Anivia R **+10.5%**.

## Ships this session

| Commit | Theme |
|---|---|
| [`4ee733c`](https://github.com/Remus3/riot-commander/commit/4ee733c) | s199 feat — 17-entry block_index + filtering-note discovery |
| [`80ccb31`](https://github.com/Remus3/riot-commander/commit/80ccb31) | s199 docs — CLAUDE.md item #57 |
| [`8f837c0`](https://github.com/Remus3/riot-commander/commit/8f837c0) | s200 feat — 7-entry rescue batch |
| [`81d2b50`](https://github.com/Remus3/riot-commander/commit/81d2b50) | s200 docs — CLAUDE.md item #58 |

Registry: 84 → 90 → 91 champions. Entries: 103 → 120 → 127. ENGINE_VERSION: 0.83.0 → 0.84.0 → 0.85.0. DS suite: 1794 → 1825 → 1842 (+48 net tests). Wider RC: 913 green both restarts.

## Carry-forward for tomorrow

**All s198 carry-forwards remain unchanged** (token-variant for multi-stage Q chains — Aatrox Q1/Q2/Q3 with combo_sequence, Gwen R; form-swap schema — Ambessa/KSante/Kayn/Hwei; sequence-state — Jhin R 4th-shot, Corki R Big One; conditional target-state schema lift — 5+ candidates queued: Zoe sleep, Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Vayne E wall-stun).

**Don't redo:** Shen Q filtered-idx discovery + fix already shipped in 4ee733c — don't re-investigate the "wrong block" path. Ambessa was NOT a form-swap mechanic (despite s196/s197/s198 saying so) — Drain-stack is the correct model and Q/W/E are all 1 in the registry. Anivia R Empowered amp shipped — don't defer it back as "channel ambiguous".

**Next session candidate:** Either (a) schema lift for conditional target-state to unlock 5+ queued entries, OR (b) Aatrox Q token-variant + combo_sequence (Aatrox added to s186 combo_sequence registry + Q2/Q3 token-variant block_index entries for Q1/Q2/Q3 sweet-spot lookup). Both are architectural rather than pure-data. Operator pick.
