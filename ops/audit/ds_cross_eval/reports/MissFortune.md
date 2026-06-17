# DS Cross-Eval Verdict: MissFortune

**Severity: MISMATCH**
Scorer top-8 (squishy cells) dominated by AP item (Wooglet's rank 1, Lich Bane rank 5) and items absent from empirical play; high-wr AD crit staples Bloodthirster/Yun Tal/Mortal Reminder missing from scorer pool.

---

## Axis 1: archetype_ok - FALSE

Archetype is assassin(primary)/mage(secondary), scorer is burst.
Burst scorer is AD-axis; MF kit is physical AD (Q double-hit, R bullet rain, all physical damage).
Mage secondary is not supported by her kit; she has no AP scaling of consequence.
However the deeper problem is visible in the comp_grid: Wooglet's Witchcap (AP item, id 228002)
ranks #1 in every cell with score 502, nearly double BotRK at 277. This is an AP-heavy item
scoring first on an AD marksman. Lich Bane (AP) ranks #5 in squishy cells. The mage secondary
archetype tag is pulling AP burst items into the top of the pool where they do not belong.
Empirical data shows zero Wooglet's, zero Lich Bane, zero BotRK appearances. The assassin tag
is also wrong; MF is a marksman/ADC, not a dive-gap-closer.

---

## Axis 2: comp_ok - FALSE (partial defect)

Scorer is burst. responsiveness.comp_blind = false at top level, so overall comp-responsiveness
is present. But enemy_damage_type sub-block: comp_blind = true, max_positive_shift = 0, no
risers. For a burst/AD scorer, enemy AP vs AD mix has no effect on item selection. This means
if the enemy team is all AP, no defensive AD items adjust - the scorer treats all comps
identically from a damage-type lens. This is a real gap though less severe than an EHP scorer
being fully comp-blind. The target_resist axis does work correctly: Black Cleaver +20,
Serylda's +11, Mortal Reminder +11, LDR +10 all rise vs tanky enemies, which is correct
armor-pen response for AD burst.

---

## Axis 3: outcome_ok - FALSE

Using outcome_self (n=46 >= 8). Self baseline wr = 43.5%.

Items above baseline from outcome_self:
- Yun Tal Wildarrows (3032): wr 50.0%, n=8 - NOT in scorer top-8 any cell
- Bloodthirster (3072): wr 57.1%, n=7 - NOT in scorer top-8 squishy cells
- Mortal Reminder (3033): wr 57.1%, n=7 - only appears in ad_tanky rank 12, absent squishy top-8
- Serylda's Grudge (6694): wr 50.0%, n=6 - ad_tanky rank 9 only

Items in scorer top-8 (ad_squishy/bal_squishy) checked against empirical:
- Wooglet's Witchcap (228002) rank 1, score 502: zero empirical appearances
- BotRK (3153) rank 2, score 278: zero empirical appearances
- Essence Reaver (3508) rank 3: zero empirical appearances (though good in SR all)
- Trinity Force (3078) rank 4: zero empirical appearances
- Lich Bane (3100) rank 5: zero empirical appearances
- Infinity Edge (3031) rank 6: wr 42.9%, BELOW self baseline 43.5%
- Sundered Sky (6610) rank 7: zero empirical appearances
- Eclipse (6692) rank 8: zero empirical appearances

8 of 8 scorer top items are either below baseline or absent from empirical data entirely.
The actual high-wr empirical build (Collector + IE + Bloodthirster crit path) is absent from
or underscored in the squishy cells. This is a clear pool mismatch.

---

## Axis 4: rune_ok - TRUE

rune_relevant = true. MF burst (Double Up / Bullet Time synergy) is rune-sensitive (Lethal
Tempo, Fleet Footwork, Conqueror all materially affect output). Flag is correctly set.

---

## Nominated Retune

burst scorer: strip mage secondary or gate AP item inclusion behind ap_scaling > threshold;
Wooglet's at rank 1 for MF indicates AP item scoring path is not gated by kit AP ratio.
Archetype should be marksman (carry) not assassin; re-tag to carry scorer or retain burst but
add kit-gating so AP items (Wooglet's, Lich Bane) cannot outrank AD crit items for a physical
damage kit with <0.1 AP ratio on primary damage source.
