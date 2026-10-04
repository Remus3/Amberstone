# DS audit against the external reference L 2026-10-03 corrections (RM-663 / RM-664 / RM-665)

Date: 2026-10-04. Tier-0, audit only. No engine, data, ROADMAP or BACKLOG edits.
Provenance: the item, rune and augment names below come from the changelog of
"external reference L". None of its numbers were used. Every magnitude here is
from local DDragon (`data/daemon_slayer/16.18.1/items.json`,
`data/meta_build/ddragon/16.18.1|16.19.1/runesReforged.json`), local
CommunityDragon (`data/daemon_slayer/16.18.1/arena_augments.json`,
`cherry_augments.json`), the vendored `items_meraki.json` (cited only as
in-repo context; its body is frozen at an older content patch per
`_effects_data.py:785-791`), or the League wiki item page (fetched 2026-10-04).

Verdicts: MATCH = code agrees with DDragon and the wiki. DEFECT = measured
disagreement, filed in the last section. BY-DESIGN = a documented
modelling choice; no row.

## L-03 (RM-663) items and runes

Skipped, per the directive:
- Legend: Haste. Ability haste is INERT (Settled).
- The gold interpolation fix. DS has no cost model.
- The 7 entries closed by the 2026-05-30 review. `docs/history_notes.md:29037`
  records "0 NOW / 0 FUTURE / 7 CLOSED" but does not name the 7. The newest
  entry that review saw was dated 2026-05-22 (`docs/history_notes.md:21848`),
  so none of them overlaps the 2026-10-03 list below.

All `_effects_data.py` paths below are `agents/daemon_slayer/_effects_data.py`.

| Name | Code (file:line) | Reference | Verdict |
|---|---|---|---|
| Lethal Tempo (8008) | `rune_procs.py:270-281`: 9-30 melee / 6-24 ranged, linear L1-L18, x(1+bonus AS). Its attack-speed grant is recorded as ROLE-BLOCKED at `_rune_offense_grants.py:923` | DDragon 16.18.1 and 16.19.1 longDesc: 6% melee / 4% ranged per stack, 9-30 / 6-24. The wiki disagrees: 4.8% ranged per stack (its V14.21 note), 9-32.47 melee, 6-21.66 ranged | MATCH to DDragon. The wiki/DDragon conflict is HELD, not filed. Settle it from the CommunityDragon perk bin before any change. |
| Spellblade, Sheen (3057) | `_effects_data.py:4884`: 1.00 x base AD, every 1.5s | wiki: 100% base AD, 1.5s CD | MATCH. Sheen uses 1.5s; the rest of the family uses 3.0s. That makes Sheen alone equal to Trinity Force's DPS, but the item is a component. Noted, not filed. |
| Spellblade, Trinity Force (3078) | `_effects_data.py:211`: 2.0 x base AD, every 3s, key `spellblade` | wiki and in-repo Meraki: 200% base AD, 1.5s CD | MATCH (the 3s cadence is a BY-DESIGN rotation assumption) |
| Spellblade, Iceborn Gauntlet (6662) | `_effects_data.py:959`: 1.50 x base AD | wiki: 150% base AD | MATCH |
| Spellblade, Essence Reaver (3508) | `_effects_data.py:750`: 1.25 x base AD + 50 x crit_chance | wiki: 125% base AD (+0-50 by crit chance) | MATCH |
| Spellblade, Lich Bane (3100) | `_effects_data.py:933`: 0.75 x base AD + **0.40** x AP. The Arena mirror `:4439` inherits it | wiki: 75% base AD (+ **45%** AP), with the V26.10 note "AP ratio increased to 45% AP from 40% AP". In-repo Meraki (frozen) reads 40% | **DEFECT** (D1) |
| Force of Nature (4401) | `_item_resist_grants.py:218`: +70 MR at 8 stacks. The effect-row note `_effects_data.py:1784-1786` reads "+6 MR each ... Resistor 30 bonus MR" | DDragon 16.18.1: "Gain 70 Magic Resist ... 8 times". wiki: 70 MR / 6% MS at 8 stacks | MATCH on magnitude. The note is stale (D5, cosmetic). 6% MS is unmodelled (BY-DESIGN, no MS axis in EHP). |
| Cloak of Starry Night (663059 / 443059) | `_item_resist_grants.py:265` +10% total MR (663059); `:257` +20% (443059) | DDragon 16.18.1: 663059 "by 10%", cap 25%; 443059 "by 20%", cap 50%. The wiki shows the Arena row (100 MR / 300 HP / 20% / 50%) | MATCH. The MR-scaled non-attack damage reduction is uncredited (BY-DESIGN, `_item_resist_grants.py:253-256`). |
| Kraken Slayer (6672) | `_effects_data.py:93`: `150 + 5*(min(L,11)-1)`, i.e. a ramp over L2-L11. Arena mirror 226672 at `:3599` is the same | in-repo Meraki 6672: `150 + (200-150)/10*(x-1) for 13 ... levels=1;9 to 20`, i.e. a 13-value table at L1 then L9..L20 (150 through L8, 155 at L9, 200 at L18, 210 at L20). wiki: "Melee 150 - 210 (based on level)". The same file already reads the "1;9 to N" convention as a hold-then-ramp from L9 (Bloodthirster `:44-56` reads the identical "(315-165)/10*(x-1) for 1;9 to 20" shape as an L1 hold then L9-L18 ramp; Immortal Shieldbow `:115-123`) | **DEFECT** (D2). Over-credits L2-L17. Worst case is L11: 200 vs 165. L1 and L18 agree. The 0-75% missing-HP amp is unmodelled (BY-DESIGN, target-state). Ranged 0.8x is melee-pinned (BY-DESIGN). |
| Blade of the Ruined King (3153) | `_effects_data.py:603`: 0.09 x target max HP x `target_current_hp_pct` | wiki: 9% melee / 6% ranged current HP (V25.14) | MATCH. Melee pin is BY-DESIGN. The `target_current_hp_pct` seam is operator-gated (BACKLOG.md:304), so no flip is proposed. The Arena mirror 223153 at `:4525` does NOT multiply by the seam (D3). |
| Titanic Hydra (3748) | `_effects_data.py:1115` 1% caster max HP primary; `:1128` 3% x (targets-1) cleave | wiki and in-repo Meraki: 1% / 3% max HP melee; Titanic Crescent 4% / 9% max HP, 10s CD | MATCH on Cleave. Titanic Crescent is unmodelled. That is the do-not-touch-blindly %max-HP row: BY-DESIGN HOLD, no row from this audit. |
| Muramana (3042) | `_effects_data.py:1340` Awe 2% max mana; `:1343` Shock 1.2% max mana on-hit | wiki (V14.19, V26.01): Awe 2%, on-hit 1.2%, abilities 4% / 3% max mana, no AD ratio. DDragon: 1000 mana | MATCH. The ability piece is unmodelled (BY-DESIGN, ability-bound rule, `:1333-1334`). |
| Heartsteel (3084) | `_effects_data.py:797`: 70 + 6% caster max HP, every 30s. `_item_health_stack.py:91`: 10% permanent HP (default-OFF seam) | DDragon: "70 plus 6% of your max Health ... 10%". wiki: 70 / 6% / 10%, 30s per target. The wiki's alternate form "7 (+0.6% max health)" is the same quantity: 10% of (70 + 6%) | MATCH |
| Kaenic Rookern (2504) | `_effects_data.py:1469`: magic shield 0.15 x max HP, default-OFF | wiki: 15% max HP, 15s refresh (V14.19) | MATCH |
| Shadowflame (4645) | `_effects_data.py:1091`: 15 flat magic pen. `_item_lowhp_magic_crit.py:74`: +20% below 40% | DDragon 16.18.1 description: "15 Magic Penetration ... below 40% Health, dealing 20% increased damage". DDragon `stats` carries no pen key, so the pen magnitude is DDragon-description-only (not Meraki). wiki: 15 pen, 120% | MATCH. The Arena mirror 224645 (10 pen / 15%) also matches its own DDragon line. |
| Lich Bane | see the Spellblade row | | DEFECT (D1) |
| Bramble Vest (3076) | `_passive_reflect_overrides.py:186,203`: 10 magic per incoming basic. The effect-row note `_effects_data.py:5157` says "50 Armor" | DDragon 16.18.1: 30 Armor, Thorns. wiki: 10 magic, 40% Wounds (V14.19) | MATCH on Thorns. Armor comes from DDragon `stats`, so the "50 Armor" note is stale only (D6, cosmetic). Wounds are unmodelled (BY-DESIGN, healing debuff). |
| Actualizer (2522) | `_effects_data.py:2178-2186`: `defensive_only`. The note describes an "ally within 1000 range" damage amp. The Arena mirror `:3976-3981` is likewise empty | DDragon 16.18.1: active "Mana Made Real", 8s, +100% costs, increased ability damage / heal / shield, basic CDs 30% faster. wiki: 15% (+0.5% per 100 bonus mana) amp, 60s CD | **DEFECT** (D4). The note names a mechanic the item does not have. The 8s/60s ability amp is unmodelled; any modelling is a separate Tier-2 row. |
| Guardian's Horn (2051) | `_effects_data.py:6072`: `defensive_only`. Undaunted is named only as an exclusion at `_item_spell_shield_overrides.py:60` | DDragon: 150 HP, 20 HP per 5s, blocks 15 per champion hit (25% vs DoT). wiki: same, ARAM/Arena | MATCH on stats (DDragon aggregate). The flat-15 per-hit block has no EHP lane: BY-DESIGN gap, recorded rather than filed. |

## L-04 (RM-664) Arena / Mayhem augment census

Data vintage. `tools/ds_feed_index.py:74` has `KNOWN_STAMP_LAG = {}`. Per its
comment at `:63-73`, cherry_augments.json was refetched for 16.18.1 on
2026-09-20. On disk, `cherry_augments.json` reads `rc_patch 16.18.1`,
`fetched_at 2026-09-21T04:02Z`, 552 rows, and `arena_augments.json` reads
`patch 16.18.1`, 225 rows. Neither is stale against its own dir. Both are one
patch behind DDragon latest (16.19.1), and both predate the Sep-Oct changelog
window. Refresh with the 16.19.1 DS batch (RM-661 / L-01) before any
magnitude grading. The structural limit matters more: `cherry_augments.json`
carries only name / rarity / icon (no magnitudes), and the only in-repo
magnitude feed (`arena_augments.json`) has no Mayhem ("Kiwi" icon) rows. The
former Mayhem stats file was dropped and is now a local-only cache
(`tools/ds_feed_index.py:75-82`), so it is not a grading source.

Grep method: every apiName, display name and numeric id below was searched
across `agents/daemon_slayer`, `core`, `app`, `coaches`, `tools` and
`scripts`. The only code hits are the ones cited. `scaling_registry_notes.json:2056`
"Phenomenal Evil" is Veigar's passive, not the augment.

| Augment | ids (cherry / arena) | In-repo magnitude | DS status | Note |
|---|---|---|---|---|
| Accelerating Sorcery | 1 / 1 (Prismatic) | arena dataValues: HastePerCast 8 | data-only | Ability-haste-only, and AH is INERT (Settled). Same skip class as Dashing (`augments.py:118-119`). Not filed. |
| Mystic Punch | 58, 1058 / 58 | CooldownRefund 1.25s on-hit, MinCDR 0.5 | data-only | A cooldown-refund mechanic. DS has no cooldown-reduction lane (AH inert). Not filed. |
| Hand of Baron | 1389 / absent | none in repo. wiki Mayhem augments page: "25% increased adaptive force" + minion buff | missing | Mayhem-only, Prismatic. File as a stat row (adaptive %-amp). Its magnitude needs a CommunityDragon source before build. |
| Phenomenal Evil | 65, 1390 / 65 (Gold) | APPerProc 1, BonusAPForLatePick 40 after round 4 | data-only | Uptime-conditional stacking AP, like the MasterofDuality exclusion (`augment_formula_eval.py:302-309`). File as a stat row with an explicit stack assumption. |
| Warlock Juicebox | 2132 / absent | none (wiki page 404) | missing | Mayhem-only, Gold. File as a source-acquisition row first. No magnitude means no model. |
| Purist Caster ("Purist - Caster") | 2018 / absent | none (wiki page 404) | missing | Mayhem-only, Silver. Same as Warlock Juicebox. |
| Don't Blink | 26, 1026 / 26 (Silver) | BonusDamagePerMSDifference 0.001 (1% per 10 MS). wiki agrees | data-only | A damage amp keyed on caster-minus-target MS. Needs a target-MS input. File as a stat-amp row. |
| Slap Around | 136, 1136 / 136 (Silver) | AdaptiveForce 15 per immobilize, per round | data-only | Skipped by design at `augments.py:121-123` (adaptive and conditional). File only with a CC-count assumption. |
| Tap Dancer | 81, 1081 / 81 (Prismatic) | MSPerHit 6, MSToASConversion 0.001 | modelled | `augments.py:211-218` (constant `TAP_DANCER`), wired at `engine.py:466`. Magnitudes match arena dataValues. |
| (control) Aim for the Head | 336 / 336 | ceiling 0.5, ratio 0.4, +25% / +25% | modelled | `augments.py:129,205-210`; `dps.py:999,1204`. |
| (control) Dashing | 19, 1019 / 19 | Haste 75 | data-only | Skipped by design, `augments.py:118-119`. |

Mayhem "augment numbers and ability upgrades" (the 2026-10-03 fix). There is
no Mayhem magnitude feed in the repo, and "ability upgrades" (per-ability
rank / effect changes granted by an augment) has no DS seam of any kind. This
is a POSTULATE that needs its own spec, covering the source feed, the id
space (cherry 1xxx / 2xxx Kiwi rows) and the consumer, before any row can be
graded. It is not filed as a defect.

## L-05 (RM-665) Arena stat overrides and rune-less enemies

Question 1: does the Arena scorer path apply the `ar` addends?
Measured: NO on every default path, YES only on explicit opt-in.
- `data_loader.py:23-38`: `_WIKI_MODE_ALIASES` maps arena / cherry to `ar`.
  `data_loader.py:563-579` `mode_modifier()` returns the `ar` addend dict.
- `engine.py:101-108` `_ADDEND_AXIS_MAP` covers hp_base / hp_lvl / arm_base /
  arm_lvl / dam_lvl / as_lvl. `engine.py:110` `_resolve_mode_addends` is
  called only under `apply_mode_modifiers` (`engine.py:345-348`), which feeds
  `_scale_champion_base` (`:350`). All 45 champions carrying an `ar` block in
  16.18.1 `wiki_stats.json` use only mapped axes (hp_lvl 36, dam_lvl 16,
  as_lvl 5, hp_base 4, arm_lvl 2), so the lane is complete when enabled.
- `apply_mode_modifiers` defaults False at every server route
  (`server.py:468,494,597,752,1030,1346,1494,1821,1908,1978`) and every scorer
  signature (`dps.py:781`, `burst.py:541`, `ehp.py:1389`, `rank.py:990`). The
  client sends it only when True (`core/daemon_slayer_client.py:306-307`), and
  no non-test caller passes True. The Arena build-order generator calls
  `plan_build_order(mode="ARENA")` without it
  (`tools/daemon_slayer_build_orders_generate.py:236-250`), so
  `build_orders_arena.json` is computed WITHOUT the `ar` addends.
- Verdict: this is the known operator-gated RM-172 lane (LEDGER 1217 / 1225),
  not a new defect. The flag reorders Arena output (Quinn: 34 of 148 rows,
  `core/daemon_slayer_client.py:298-305`). Defaulting it on is out of scope
  per the directive.

Question 2: does `enemy_runes.py` credit runes in Arena / Mayhem?
- `enemy_runes.py` takes no mode argument anywhere (`:247`, `:263`, `:280`,
  `:294`, `:314`, `:342`, `:360`). It credits whatever ids the caller passes.
  Its only consumer is `dsp_live_consumers.enemy_rune_threat`
  (`dsp_live_consumers.py:118-148`), exposed as POST `/enemy-rune-threat`
  (`server.py:2512-2533`, registered `:3016`), which is also mode-blind.
- No caller outside `agents/daemon_slayer` (core, app, coaches, web) hits
  that route or function. The coach-side keystones in `coaches/aram_coach.py`
  (around 1032, 1386) are prompt text, not DS math.
- Verdict: mode-blind by construction, but there is no live consumer, so the
  MEASURED gap is zero today and no defect is filed. If the route is ever
  wired to a live game, it needs a mode gate for ARENA. The claim that ARAM
  Mayhem clears enemy runes comes from external reference L only. It is
  unverified here and live-gated (confirm from a real Mayhem Live Client rune
  payload).

## Defects to file

One line each: title | file:line | evidence | suggested failing test.

- D1 Lich Bane Spellblade AP ratio stale (0.40 vs 0.45) | `agents/daemon_slayer/_effects_data.py:933` (+ Arena mirror `:4439`) | wiki Lich Bane V26.10 "Spellblade AP ratio increased to 45% AP from 40% AP"; current tooltip "75% base AD (+ 45% AP)" | `ITEM_EFFECTS["3100"]` proc at base_ad=0, ap=100 must equal 45.0 (today 40.0). Tier-2 (ENGINE bump).
- D2 Kraken Slayer Bring It Down level ramp mapped to L2-L11 instead of hold-to-L8 then L9-L18 | `agents/daemon_slayer/_effects_data.py:93` (+ Arena mirror `:3599`) | in-repo Meraki 6672 `... for 13 ... levels=1;9 to 20`; wiki 150-210; same-file precedent Bloodthirster `:44-56` (identical "/10*(x-1) for 1;9 to 20" shape, `level_lerp_low=9`) | proc at L5 == 150, L9 == 155, L11 == 165, L18 == 200 (today L9 == 190, L11 == 200). Confirm against the CommunityDragon item bin first. Tier-2.
- D3 Arena BotRK 223153 ignores the target_current_hp_pct seam | `agents/daemon_slayer/_effects_data.py:4525` vs SR `:603` | SR row multiplies by `c.target_current_hp_pct`; the Arena mirror does not, so the operator-gated lever is silently inert on map 30 | with target_current_hp_pct=0.5, the 223153 proc must be half its value at 1.0 (today unchanged). Byte-identical at the default 1.0. Tier-2. Fence check: this restores parity between a mirror and the seam that is already wired (BACKLOG.md:304). It is not new target-state plumbing, so it does not re-open the Settled conditional-target-state arc. If the merger disagrees, hold it.
- D4 Actualizer effect row describes a nonexistent mechanic | `agents/daemon_slayer/_effects_data.py:2183` (+ `:3980`) | DDragon 16.18.1 2522 is the active "Mana Made Real" (8s ability amp, 60s CD per wiki), not an ally-proximity amp | a registry test that the 2522 / 222522 notes name "Mana Made Real". Tier-0 note fix. Modelling the amp is a separate Tier-2 row.
- D5 Force of Nature effect note stale ("+6 MR each ... Resistor 30") | `agents/daemon_slayer/_effects_data.py:1784-1786` | DDragon 16.18.1 4401 "Gain 70 Magic Resist ... 8 times"; the credited value at `_item_resist_grants.py:218` is already 70 | note-text test that 4401 cites 70 MR. Tier-0 cosmetic.
- D6 Bramble Vest effect note says 50 Armor | `agents/daemon_slayer/_effects_data.py:5157` | DDragon 16.18.1 3076 stats FlatArmorMod 30 | note-vs-DDragon armor test for 3076. Tier-0 cosmetic.

Coverage rows to file (L-04 missing or data-only stat augments; not defects):
- Hand of Baron (cherry 1389): adaptive %-amp. Needs a CommunityDragon magnitude source.
- Phenomenal Evil (arena 65 / cherry 1390): stacking AP. Needs a stated stack assumption.
- Don't Blink (arena 26): MS-difference damage amp. Needs a target-MS input.
- Slap Around (arena 136): per-CC adaptive force. Needs a CC-count assumption.
- Warlock Juicebox (cherry 2132) and Purist - Caster (cherry 2018): source acquisition first (no in-repo or wiki magnitude found).
- Mayhem "ability upgrades": a postulate spec, not a row.

Held, not filed:
- Lethal Tempo: DDragon/wiki conflict (ranged 4% vs 4.8% per stack; melee max 30 vs 32.47).
- Titanic Crescent: do-not-touch-blindly.
- Guardian's Horn flat block: no EHP lane.
- Arena `ar` default-on: operator-gated RM-172.
