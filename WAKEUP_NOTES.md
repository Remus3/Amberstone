# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 + s197 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

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

---

# s198 wrap — 2026-05-14 (Phase 5.9.11 bruiser/jungler/utility/marksman block_index expansion)

**Operator instruction:** "continue ds" — direct continuation of s197 (now the fifteenth consecutive override / proc-shape ship on the same template). The pure-data well still has clean candidates after seven batches, and the s197 carry-forwards (token-variant for multi-stage chains, form-swap, sequence-state) all need schema lifts. Pure-data was the cleanest ship again.

## Context

s197 reasoned the resource-state framing ("operator commits to canonical resource state") fit cleanly under the unconditional s191 model — Renekton Q full-Fury, Kassadin R max-stack landed there. Re-scanning the same `champion_abilities.json` snapshot for unmapped (champion, key) candidates with promising amp ratios surfaced 75 candidates beyond the s191/s193/s194/s195/s196/s197 set. Triaged to 20 entries spanning four sub-patterns across bruiser/jungler/utility/marksman class — explicitly broadening coverage beyond the assassin/fighter focus of s197.

Four sub-patterns shipped this batch — same `dict[str, int]` registry; same s192 token-canonical + base-key fallback walker; just more JSON:

**(A) Multi-hit single-target totals (12 entries):**
- Sylas Q=3 (Chain Lash initial + delayed pulse on chained target, 3.33×)
- XinZhao Q=1 (Three Talon Strike 3 empowered AAs total, 3×)
- XinZhao W=2 (Wind Becomes Lightning slash + thrust both on same target, 3.71× base + 4× tAD)
- Zac R=2 (Let's Bounce all 4 bounces same target, 2.5×)
- Maokai E=1 (Sapling Toss enhanced dual-hit, 2×)
- Kayn Q=1 (Reaping Slash both passes through target, 2×)
- Sejuani W=2 (Winter's Wrath swipe + thrust total, 2.89× base + 4× AP)
- Neeko Q=2 (Blooming Burst initial + 2 blooms same target, 2.04× base + 1.83× AP)
- Nasus E=2 (Spirit Fire initial impact + 5 full-duration ticks, 2×)
- Nami E=1 (Tidecaller's Blessing 3 empowered AAs all landing on target, 3×)
- Ornn R=2 (Call of the Forge God initial ram + 2nd ram pass, 2×)
- Twitch E=3 (Contaminate at 6 Deadly Venom stacks, 4.5× base + 6× per-stack scaling)

**(B) Fully-charged amps (4 entries):**
- Vi Q=1 (Vault Breaker fully-charged 1.25s wind-up, 2.5×)
- Sion R=1 (Unstoppable Onslaught max-speed after full acceleration, 2.67× base)
- Irelia W=1 (Defiant Dance fully-charged 2s, 3×)
- Yuumi Q=1 (Prowling Projectile untargeted at max-distance, 1.62×)

**(C) Resource-state amp (1 entry):**
- Jax E=1 (Counter Strike at 2 dodge stacks max, 2×)

**(D) Channel/duration totals (3 entries):**
- Udyr R=1 (Wingborne Storm full 8 ticks, exact 8× block 0)
- Vladimir W=1 (Sanguine Pool full 4-second duration, exact 4×)
- Viktor R=2 (Chaos Storm initial + 6 ticks full channel, 4.48× base + 5.20× AP)

All 20 verified per-rank against the Meraki snapshot. `test_udyr_R_block1_matches_8x_block0` + `test_vi_Q_block1_matches_2_5x_block0` are the math-sanity pins.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **Registry expanded 67 → 84 champions (20 new (champion, key) pairs).** 17 new champions: Sylas, XinZhao (Q+W), Zac, Maokai, Kayn, Sejuani, Neeko, Nasus, Nami, Ornn, Vi, Irelia, Yuumi, Twitch, Jax, Udyr, Viktor. 2 key extensions on existing champions: Sion +R=1 (alongside s197's Q=2), Vladimir +W=1 (alongside s195's E=1). `_meta.description` extended with Phase 5.9.11 section covering all four sub-patterns. `_meta.rationale` adds entry-by-entry per-rank math verification with Meraki ATTR names. Skipped-list extended with 14 deliberate deferrals (Evelynn Q target-state, Vayne E wall-stun, Vladimir Q passive-AA, Xerath W positional, Ziggs E unrealistic focus, Janna Q utility, Seraphine Q enchanter-class, Yasuo E decay rate, Heimerdinger Q/R turret, Sona R / Lux Q/E/R / Veigar Q single-block, Smolder Q/E gear-conditional or schema-ambiguous). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.82.0 → 0.83.0. Docstring extended with Phase 5.9.11 section noting the data-only nature, all four sub-patterns with 20 entries enumerated, A/B impact summary, deliberate skip-list rationale. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `Phase599_11ExpansionTests` class (29 tests): 20 per-entry `_delta_check` covering all four sub-patterns + 3 multi-key resolved-shape (XinZhao Q+W, Sion Q+R, Vladimir E+W) + 2 math sanity (Udyr R 8×, Vi Q 2.5×) + 4 backward-compat regression guards (Morgana s195+s196, Aatrox s197 W=3, Camille s195, Singed s193 preserved). `RegistryShapeTests.test_known_champion_overrides` extended with 17 explicit assertions for new champions + 2 updated for Sion {Q:2, R:1} and Vladimir {E:1, W:1}. File docstring extended with Phase 5.9.11 section. |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.82.0 → 0.83.0 with the Phase 5.9.11 line in the history comment (covers both `test_engine_version_history` and `test_batch64_version`). |

## Verification

- DS suite **1794 pass** (was 1765 in s197 wrap; +29 from new `Phase599_11ExpansionTests` class — 20 per-entry + 3 multi-key + 2 math sanity + 4 backward-compat)
- Wider RC `tests/` suite **938 pass** (post-DS-restart; pre-restart phase8_smoke's `test_live_three_profiles` was failing on the 0.83.0 pin against still-0.82.0 live server, as expected)
- DS server :8893 restarted from PID 3724 → new PID via `Get-CimInstance` filter + PowerShell `taskkill /F /PID` + `Start-Process pythonw tools\start_daemon_slayer.py`; `/health` reports `engine_version=0.83.0` patch=16.10.1 172 champions 705 items
- phase8_smoke 75 pass post-DS-restart

## Live A/B on :8893 (/ability-dps at lvl 11 vs 80 armor / 30 MR / 2000 HP)

| Champion.Key | Registry block | Forced block 0 | Lift |
|---|---|---|---|
| Twitch E | 1.17 adps | 0.32 adps | **+263.0%** |
| XinZhao Q+W | 15.49 adps | 7.05 adps | **+119.7%** (combined) |
| Sylas Q | 15.95 adps | 7.29 adps | **+118.8%** |
| Udyr R | 15.42 adps | 7.95 adps | **+94.1%** |
| Viktor R | 19.75 adps | 10.47 adps | **+88.6%** |
| Kayn Q | 25.50 adps | 15.22 adps | **+67.5%** |
| Vi Q | 15.50 adps | 9.49 adps | **+63.4%** |
| Neeko Q | 24.63 adps | 15.58 adps | **+58.0%** |
| Yuumi Q | 10.79 adps | 6.90 adps | **+56.4%** |
| XinZhao W | 15.49 adps | 11.83 adps | **+31.0%** |
| Jax E | 15.65 adps | 12.75 adps | **+22.7%** |
| Sejuani W | 10.43 adps | 9.06 adps | **+15.0%** |
| Nasus E | 9.73 adps | 8.55 adps | **+13.9%** |
| Nami E | 11.46 adps | 10.11 adps | **+13.4%** |
| Maokai E | 10.68 adps | 9.54 adps | **+12.0%** |
| Zac R | 12.04 adps | 10.95 adps | **+9.9%** |
| Ornn R | 16.18 adps | 15.00 adps | **+7.9%** |
| Irelia W | 15.97 adps | 15.07 adps | **+6.0%** |
| Sion R | 32.59 adps | 31.11 adps | **+4.8%** |
| Vladimir W | 28.09 adps | 27.59 adps | **+1.8%** |

Twitch E +263% is the headline — Contaminate at 6 Deadly Venom stacks is Twitch's entire late-game burst identity, and the engine was scoring it at the 1-stack minimum pre-s198. Sylas Q +119%, Udyr R +94%, and Viktor R +88% similarly reflect their identity-defining ability values that were being systematically under-counted at the per-tick or initial-block default.

The small-lift entries (Vladimir W +1.8%, Sion R +4.8%, Irelia W +6%) are utility-heavy or multi-spell champions where the new entry is correct but diluted by other spells' dominant share of total_ability_dps. Vladimir Q + E dominate his ability output; the W contribution is now correct (4× per-tick) but adds only 0.50 adps to total. This is per-spell-correct, total-share-correct behavior.

**Regression checks pass:**
- s195+s196 Morgana entry preserved (`test_pre_s198_morgana_unchanged` asserts `{W:3, R:1}`)
- s197 Aatrox W=3 preserved in burst path (`test_pre_s198_aatrox_unchanged` asserts `{W:3}`)
- s195 Camille Q=2 preserved (`test_pre_s198_camille_unchanged`)
- s193 Singed Q=1 preserved (`test_pre_s198_singed_unchanged`)
- `BackwardCompatTests` green: unmapped Zed burst with no override = empty explicit override (byte-identical)
- Live regression checks: Cassi 40.44 (s191+s196 baseline {E:1, W:1}), Singed 11.46 (s193 {Q:1}), Veigar 25.91 ({R:1}), Akali burst resolved {R:0, R2:2, E:2} preserved

## Findings

- **Pure-data well still has clean candidates after 7 batches.** s191 → s197 shipped 67 entries; s198 adds 20 more without any change in code shape. Each new entry drops in as one JSON line + 1 test method + a rationale comment. Estimated ~50 more candidates remain unmapped, but they're increasingly diluted by other spells (s198's Vladimir W +1.8% lift is the dilution headwind) OR need schema lifts (form-swap, sequence-state, conditional target-state).
- **Bruiser/jungler/utility broadening.** s191-s197 was assassin/mage/marksman-heavy; s198 deliberately broadened to bruiser (Vi, Irelia, Sion, Sejuani, Jax, Maokai, Kayn, Ornn, Sylas), jungler (XinZhao, Udyr, Zac), and utility (Nami, Yuumi, Viktor, Nasus, Neeko, Vladimir, Twitch). Coverage is now more balanced across class archetypes — important for the dispatcher's `ds.ability` mage scorer and `ds.burst` assassin scorer both having representative champions tested.
- **Resource-state framing continues to extend.** Jax E (2 dodge stacks) joins s197's Renekton/Kassadin and Twitch E (6 Deadly Venom stacks) as resource-state amps that fit the unconditional s191 model with "operator commits to having the resource" framing. The conditional-resource-state schema lift bucket is now down to: Jhin R 4-shot sequence (per-cast within ult), Corki R Big One (every-4th-missile per recast), Aatrox Q chain stage (per-cast in rotation) — all genuinely needing per-cast conditional schema, not "operator commits at burst window" framing.
- **Twitch E was an obvious gap pre-s198.** 6 Deadly Venom stacks is Twitch's *entire* burst identity — Q stealth approach → AA stack to 6 → E for max damage. Scoring his E at 1 stack (block 0 default) is essentially scoring naked-Twitch, not real-Twitch. +263% lift confirms the per-stack scaling was fully present in the Meraki snapshot all along; the engine just needed the override registry to point at the right block.
- **Two-key extensions on existing champions work cleanly.** Sion (s197 Q=2) + R=1 from s198, and Vladimir (s195 E=1) + W=1 from s198. The walker resolves both via dict-update under the single canonical resolver call — verified live and by `test_sion_both_keys_in_resolved` + `test_vladimir_both_keys_in_resolved` assertions. No regression to s195/s197 entries.
- **XinZhao Q+W combined +119.7% is a strong validation of multi-key per-champion entries.** Single champion contributing 2 new entries; both route to expected blocks; total_ability_dps shifts by the sum of per-spell lifts. Mirrors the s197 pattern for Renekton (Q+W) and Naafiri (Q+E).
- **Process-tracking pattern continues to hold.** `Get-CimInstance Win32_Process` filter isolated DS PID 3724 cleanly; relaunched via `Start-Process pythonw` background spawn. No false kills. `taskkill /F /PID` ran via PowerShell (Bash variant prepended `cd` and failed).

## Open items carried forward

- 🟡 **Token-variant for multi-stage Q chains** — Aatrox Q (Q1/Q2/Q3 distinct), Gwen R needlework chain. Same shape as Akali R/R2 (s192). 2+ candidates accumulated.
- 🟡 **Form-swap block_index** — Ambessa Q/W/E (form swap), KSante R (All Out form), Kayn Q (could refine — Rhaast/Shadow Assassin differ post-form), Hwei Q form 0/1/2/3. Schema lift: `{champ: {key: {form_idx: block_idx, ...}}}`.
- 🟡 **Sequence-state block_index** — Jhin R 4th-shot, Corki R Big One every-4th-missile, Aphelios stance rotation. Defer to combo_sequence-style modeling, not block_index.
- 🟡 **Conditional block_index based on target state** — Zoe sleep, Lux Illumination, DrMundo E missing-HP, Evelynn Q charm (NEW from s198 skip list), Vayne E wall-stun (NEW). Schema lift candidates: 5+. Defer until operator commits to schema design.
- 🟡 **Sum-of-blocks block_index** — DrMundo W full-channel + recast detonation. Single candidate, defer.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness still missing. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Real internal CD in long combos** — s190 carry-forward.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

## Architectural pattern lock-in (continued from s197)

Fourteenth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo / s187 form / s188 per-AA on-hit / s189 Spellblade / s190 Lightshield / s191 block_index / s192 token-variant / s193 channels / s194 calibration / s195 multi-hit/charge/recast / s196 extended multi-hit/condition-amp / s197 assassin/fighter resource + utility / s198 bruiser/jungler/utility/marksman broadening). Seventh pure-data batch in the channel/total/charge family. Pattern remains rock-solid for 10-25 entry batches; the rate-limiting step continues to be operator triage of skip-list growth (14 skips this batch — manageable). Next genuinely-blocking lifts are token-variant for multi-stage Q chains (Aatrox Q1/Q2/Q3) and form-swap (Hwei per-form, KSante All Out, Ambessa) — both have 2+ candidates accumulated and warrant schema design. Conditional target-state schema lift now has 5+ candidates queued (Zoe sleep, Lux Illumination, DrMundo E missing-HP, Evelynn Q charm, Vayne E wall-stun) — ready when operator commits.
