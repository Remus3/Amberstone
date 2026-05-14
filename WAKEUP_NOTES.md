# WAKEUP_NOTES — RC hand-off ledger

> Sessions s27–s137 + s166 + s173.5 + s173.1 + s175 + s176 + s177 + s178 + s179 + s180 + s181 + s193 + s194 + s195 archived to docs/history_notes.md. Only the last 3 sessions kept here.

---

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

---

# s197 wrap — 2026-05-14 (Phase 5.9.10 assassin/fighter resource + utility block_index expansion)

**Operator instruction:** "continue DS" — direct continuation of s196 (now the fourteenth consecutive override / proc-shape ship on the same template). The pure-data well still has clean candidates, and s196's carry-forward list documented both schema-lift candidates (4+ target-state, 5+ resource-state) and several skipped per-(champion, key) opportunities that fit the unconditional-amp model with the right framing. Pure-data was the cleanest ship again.

## Context

s196 had explicitly skipped Kassadin R (resource-state), Aatrox W (CC-conditional), Akshan R (charge-state), Jhin R (sequence-state), Hwei R (channel deferral) on the grounds that they needed schema lifts or other modeling. On re-inspection: **Kassadin R block 3 (max-stack)** and **Aatrox W block 3 (chains + pullback)** both fit cleanly under the established "operator commits to canonical-amped condition" framing — same as Cassi's poisoned-target E or Renekton's full-Fury Q (which were also waiting candidates). Same-target focus totals from un-mapped champions (Naafiri Q 3-dagger same-target, Mel Q 6-projectile, Wukong R Cyclone full duration, LeBlanc Q+E combo amps, Lucian R channel total, etc.) round out a strong 20-entry batch across 18 new champions, with verified Meraki per-rank math for each.

Five sub-patterns shipped this batch — each maps cleanly to a single static block_index:

**(A) Multi-hit / channel / mark totals (12 entries):**
- Aatrox W=3 (Infernal Chains landed + pull-back, 2× block 0)
- Hwei R=3 (Spiraling Despair Maximum Total = full channel + detonation)
- LeBlanc Q=1 (Sigil of Malice + detonation via W/E follow-up, 2×)
- LeBlanc E=1 (Ethereal Chains root + return-tether, 2.12×)
- Lucian R=1 (Culling full-channel, exact 5× block 0)
- Mel Q=3 (Radiant Volley 6-projectile total on same target, ~10×)
- Mel R=2 (Golden Eclipse initial + mark detonation, ~10×)
- MonkeyKing R=1 (Wukong Cyclone full 4s spin, 8× per-tick)
- Naafiri Q=2 (Darkin Daggers 3 daggers same target, 4× bAD)
- Naafiri E=1 (Eviscerate dash multi-strike, 2.91×)
- MasterYi Q=2 (Alpha Strike same-target focus, exact 1.75×)
- Smolder W=2 (Achooo! 3-hit AoE on same target, 2.1×)

**(B) Fully-charged amps (3 entries):**
- Nunu W=1 (Biggest Snowball Ever! max-charge, exact 5×)
- Sion Q=2 (Decimating Smash fully-charged 2s wind-up, 2.92×)
- Briar E=4 (Chilling Scream max-charge + headbutt, 2.4× block 2)

**(C) Resource-state amps (3 entries):**
- Renekton Q=1 (Cull the Meek Empowered at 50+ Fury, 1.5× + 1.4× bAD)
- Renekton W=2 (Ruthless Predator Empowered at 50+ Fury, exact 1.5×)
- Kassadin R=3 (Riftwalk Maximum Bonus at max 4 stacks, ~3× + ~1.56× AP)

**(D) Execute / channel-duration amps (2 entries):**
- Darius R=2 (Noxian Guillotine execute on bleeding target, exact 2×)
- Nilah R=1 (Apotheosis full-duration whirlwind, 4× base + 4× bAD)

**(E) Multi-charge / multi-fire totals (2 entries):**
- Poppy R=1 (Keeper's Verdict fully-charged channel, 2× + 2× bAD)
- Rumble E=1 (Electro Harpoon 2-charge dual-fire, exact 2× base + 2× AP)

All 20 verified per-rank against the Meraki snapshot. `test_lucian_R_block1_matches_5x_block0` + `test_renekton_Q_block1_matches_1_5x_block0` are the math-sanity pins.

## Ships

| File | Change |
|---|---|
| [agents/daemon_slayer/champion_block_index.json](agents/daemon_slayer/champion_block_index.json) | **Registry expanded 49 → 67 champion entries (20 new (champion, key) pairs across 18 new champions).** 18 new champions: Aatrox, Briar, Darius, Hwei, Kassadin, Leblanc (Q+E), Lucian, MasterYi, Mel (Q+R), MonkeyKing, Naafiri (Q+E), Nilah, Nunu, Poppy, Renekton (Q+W), Rumble, Sion, Smolder. `_meta.description` extended with the Phase 5.9.10 section covering all five sub-patterns. `_meta.rationale` adds entry-by-entry per-rank math verification for each new entry. Skipped-list extended with 15 explicit deferrals: Aatrox Q chain (token-variant + combo_sequence), Akshan R / Kennen R / Jhin R / Kled W (resource/sequence/form), Ambessa Q/W/E / Gwen R / KSante R (form swap), Blitzcrank R / Fizz W/R / Galio W / Graves Q / Malphite W (complex semantics), LeBlanc R (Mimic data gap), Mel E / Renekton E form 1 (form conflict / long-zone). |
| [agents/daemon_slayer/__init__.py](agents/daemon_slayer/__init__.py) | ENGINE_VERSION 0.81.0 → 0.82.0. |
| [agents/daemon_slayer/tests/test_block_index_overrides.py](agents/daemon_slayer/tests/test_block_index_overrides.py) | New `Phase599_10ExpansionTests` class (32 tests): 20 per-entry `_delta_check` covering all five sub-patterns + 4 multi-key resolved-shape (LeBlanc Q+E, Mel Q+R, Naafiri Q+E, Renekton Q+W) + 2 math sanity (Lucian R 5×, Renekton Q 1.5×) + 4 backward-compat regression guards (Morgana s195+s196, Akali s192+s196, Corki s194, Singed s193 preserved). `RegistryShapeTests.test_known_champion_overrides` extended with 18 explicit assertions for the new champion entries. `ServerRouteSourceTests.test_ability_dps_default_source` repointed from Aatrox to Caitlyn (Aatrox now in registry). Six "unmapped fixture champion" tests repointed Aatrox → Yasuo (`GetBlockIndexForTests.test_unknown_falls_back_to_default`, `ResolveBlockIndexTests` 3 cases, `ComputeAbilityDpsBlockIndexTests.test_unmapped_champion_uses_default`, `ComputeBurstBlockIndexTests.test_unmapped_champion_uses_default`, `RankerBlockIndexTests.test_rank_unmapped_champion_default`, `ToDictSerializationTests.test_unmapped_champion_to_dict_is_empty_dict`). Two `ServerRouteSourceTests` Cassi assertions corrected to `{E:1, W:1}` shape (s196 had added W=1 but missed updating these tests against a then-down DS server). |
| [agents/daemon_slayer/tests/test_effects_expansion.py](agents/daemon_slayer/tests/test_effects_expansion.py) | Version-pin tests bumped 0.81.0 → 0.82.0 with the Phase 5.9.10 line in the history comment. |

## Verification

- DS suite **1765 pass** (was 1733 in s196 wrap; +32 from new `Phase599_10ExpansionTests` class)
- Wider RC `tests/` suite **913 pass** (post-DS-restart — pre-restart, phase8_smoke's `test_live_three_profiles` was failing on the 0.82.0 pin against the still-0.81.0 live server, as expected)
- `py_compile` clean for __init__.py + both test files
- DS server :8893 restarted (was PID 14972 → new PID via `taskkill /F /PID` + `Start-Process pythonw tools\start_daemon_slayer.py`); `/health` reports `engine_version=0.82.0` patch=16.10.1 172 champions 705 items

## Live A/B on :8893 (post-DS-restart)

| Champion.Key | Route | Registry | Forced block 0 | Delta | Lift |
|---|---|---|---|---|---|
| Naafiri Q | /ability-dps | 8.66 | 4.90 | +3.76 | **+76.8%** |
| Kassadin R | /ability-dps | 29.60 | 17.18 | +12.42 | **+72.3%** |
| Sion Q | /ability-dps | 31.11 | 20.39 | +10.72 | **+52.6%** |
| Darius R | /burst | 841.44 | 591.44 | +250.00 | **+42.3%** |
| Leblanc Q | /ability-dps | 18.32 | 13.56 | +4.76 | **+35.1%** |
| MonkeyKing R | /ability-dps | 7.83 | 6.02 | +1.81 | **+30.0%** |
| Renekton Q | /ability-dps | 11.43 | 9.30 | +2.13 | **+22.9%** |
| Aatrox W | /burst | 345.94 | 293.72 | +52.22 | **+17.8%** |
| Renekton W | /ability-dps | 11.43 | 10.22 | +1.21 | **+11.8%** |
| Lucian R | /ability-dps | 8.38 | 7.65 | +0.73 | **+9.5%** |
| Hwei R | /ability-dps | 20.90 | 19.20 | +1.70 | **+8.9%** |
| Nilah R | /ability-dps | 5.14 | 4.97 | +0.17 | **+3.4%** |

Headlines: Naafiri Q +76.8% (canonical 3-dagger same-target commit), Kassadin R +72.3% (max-stack Riftwalk = his identity), Sion Q +52.6% (fully-charged Smash is his core engage), Darius R +42.3% burst (Noxian Guillotine execute scoring).

`/rank-mage` Hwei top 5: Rabadon's +10.35 / Shadowflame +9.40 / Mejai's +8.88 / Stormsurge +8.01 / Void Staff +7.80 — AP items dominate because R block 3 has 95% AP scaling. `/rank-assassin` Kassadin top 5: Rabadon's +367.90 / Shadowflame +342.05 / Mejai's +315.65 / Lich Bane +312.69 / Stormsurge +292.84 — Lich Bane climbs to #4 from Spellblade amp on now-doubled R block 3 AP scaling (78% AP); canonical Kassadin AP-burst build emerges.

**Regression checks pass:**
- s196 Morgana entry preserved (`test_pre_s197_morgana_unchanged` asserts `{W:3, R:1}`)
- s192+s196 Akali entry preserved (`test_pre_s197_akali_unchanged` asserts `{R:0, R2:2, E:2}`)
- s194 Corki entry preserved (`test_pre_s197_corki_unchanged` asserts `{W:1, E:1}`)
- s193 Singed entry preserved (`test_pre_s197_singed_unchanged` asserts `{Q:1}`)
- `BackwardCompatTests` green: unmapped Zed burst with no override = empty explicit override (byte-identical)

## Findings

- **Resource-state amps cleanly fit the unconditional model** with the right framing. Renekton Q full-Fury and Kassadin R max-stack are both "operator commits to having the resource ready before burst" — same intuition as Cassi committing to poison or Brand committing to CC. The conditional-schema lift (which s196 had flagged as "ready when operator commits") turns out to be unnecessary for resource-state — the unconditional "commit to the canonical-amped condition" framing covers it. Resource-state schema lift now needed only for sequence-state cases (Jhin R 4th-shot, Corki R Big One every-4th-missile) where the resource state is per-cast within the same ability invocation.
- **The pure-data well still has clean candidates after 6 batches.** s191 → s196 shipped 49 entries; s197 adds 20 more without any change in code shape. Each new entry drops in as one JSON line + 1-2 test methods + a rationale comment. Estimated 50-80 more candidates remain unmapped, but they're increasingly utility-blocky or mechanically ambiguous (CC-conditional + duration-conditional + form-conditional combinations that need schema lifts).
- **Aatrox W is a clean fit but Aatrox Q is the harder one.** Aatrox W block 3 is the "chains landed + pull-back" total (2× block 0) — operator commits to landing the chain CC, same model as Brand W and Morgana R. But Aatrox Q has a 6-block multi-stage rotation (Q1/Q2/Q3 + knockup variants per stage) — needs token-variant entries (Q/Q2/Q3 distinct) combined with combo_sequence modeling. Defer to a follow-up batch dedicated to per-stage chains.
- **Test-fixture rotation cost was avoidable.** I had to switch 6 "unmapped champion fixture" tests from Aatrox to Yasuo because s197 added Aatrox.W=3. Could have predicted this from `test_unknown_falls_back_to_default` etc. before editing the JSON — pre-edit grep for "Aatrox" in the test file would have surfaced 9 dependencies, not just the 1 obvious one. Cost was ~5 min to fix; preventable with a pre-edit grep next time.
- **Two `ServerRouteSourceTests` were already broken from s196.** `test_ability_dps_champion_source` was asserting Cassi `{E:1}` but s196 had added W=1 — the test was wrong from s196's commit but only surfaced now because the s196 docs sync's wider-RC run was post-restart (the new live registry returned `{E:1, W:1}`). Fixed both Cassi assertions to `{E:1, W:1}`. The lesson: when extending an existing champion's registry entry, search for ALL test assertions of that champion's shape (RegistryShapeTests + ServerRouteSourceTests + any per-method explicit override tests), not just the canonical assertion.
- **Live `/rank-mage` and `/rank-assassin` rankings shift as expected.** Hwei's new R block 3 (95% AP scaling) makes Rabadon's #1 in his /rank-mage. Kassadin's new R block 3 (78% AP scaling at max stacks) surfaces Lich Bane at #4 (Spellblade amp on now-doubled R AP). Canonical AP-burst builds emerge naturally — confirming the registry choices produce correct downstream rankings, not just correct per-spell numbers.
- **Process-tracking pattern continued to hold.** `Get-CimInstance Win32_Process | Where-Object` filter isolated the DS pythonw.exe PID 14972 cleanly; relaunched via `Start-Process pythonw tools\start_daemon_slayer.py` background spawn. No false kills.

## Open items carried forward

- 🟡 **Conditional block_index based on target state** — same as s196 carry-forward. Zoe sleep (E→Q on sleeping target, SECOND amp on top of s195's distance amp), Lux Illumination, DrMundo E missing-HP threshold, Aatrox W block-3 chain-landed (now-shipped as unconditional but could refine). Schema lift candidates accumulated to 4+. Defer until operator commits to the schema design (current `dict[str, int]` would need to become `dict[str, int | dict[str, ...]]`).
- 🟡 **Sum-of-blocks block_index** — DrMundo W full-channel + recast detonation (single candidate; defer until 3+).
- 🟡 **Sequence-state block_index** — Jhin R 4th-shot, Corki R Big One every-4th-missile, Aphelios stance rotation. Defer to combo_sequence-style modeling, not block_index.
- 🟡 **Token-variant block_index for multi-stage abilities** — Aatrox Q chain (Q/Q2/Q3 distinct), Gwen R needlework chain. Same shape as Akali R/R2 (s192). Defer until 2+ candidates accumulate.
- 🟡 **Form-swap block_index** — Ambessa Q/W/E (form swap), KSante R (All Out form), Kayn Q (Rhaast/Shadow Assassin), Hwei Q form 0/1/2/3 (block_index per form). Schema lift: `{champ: {key: {form_idx: block_idx, ...}}}`.
- 🟡 **Conditional damage amps (Ahri R→Q, Zoe E→Q)** — inter-spell awareness still missing. Carried since s180.
- 🟡 **Generalized arm-consume framework** via `is_ability_triggered_aa_proc` schema flag. Carried since s190.
- 🟡 **Aphelios + Karma mantra + Khazix evolved** — upstream/plumbing/UI blockers.
- 🟡 **Real internal CD in long combos** — s190 carry-forward.
- 🟡 **Pre-existing carry-forwards from s184/s183/s182** — live-game chip lifecycle validation; `_TOP_N_THRESHOLD` retune; `nudge_history` calibration analysis.

## Architectural pattern lock-in (continued from s196)

Thirteenth consecutive override / proc-shape modeling improvement on the same template (s185 max_priority / s186 combo / s187 form / s188 per-AA on-hit / s189 Spellblade / s190 Lightshield / s191 block_index / s192 token-variant / s193 channels / s194 calibration / s195 multi-hit/charge/recast / s196 extended multi-hit/condition-amp / s197 assassin/fighter resource + utility totals). Sixth pure-data batch in the channel/total/charge family. Pattern remains rock-solid for 10-25 entry batches; resource-state framing turned out simpler than the schema-lift s196 anticipated (cf. Renekton, Kassadin). Next genuinely-blocking lifts are token-variant for multi-stage Q chains (Aatrox Q1/Q2/Q3) and form-swap (Hwei per-form, KSante All Out, Ambessa) — both have 2+ candidates accumulated and warrant schema design.
