# DS Cross-Eval: Kaisa

VERDICT: MISMATCH

Scorer: dps | Archetype: carry(primary)/mage(secondary) | Anchor: ARAM
Evidence: outcome_self (ARAM n=41 wr=56.1, SR n=18 wr=38.9)

---

## Axis 1 - archetype_ok: TRUE

DPS scorer is AD-axis, consistent with primary carry. Kit is AA-heavy with on-hit scaling.
No axis mismatch. The issue is pool coverage, not axis choice.

---

## Axis 2 - comp_ok: TRUE

Scorer = dps. Primary responsiveness axis = target_resist (correct for DPS).
- target_resist.comp_blind = false; max_positive_shift = +20 (Liandry's Torment +20 vs tanky, Lord Dominik's +8, Eclipse +6). Adequate signal.
- enemy_damage_type.comp_blind = true (max_positive_shift=0). This is EXPECTED for a pure DPS scorer; enemy damage type governs EHP/survival builds, not DPS item selection. No defect here.

---

## Axis 3 - outcome_ok: FALSE (MISMATCH)

Empirical baseline wr = 56.1 (n=41 self). Above-baseline items:
  Guinsoo's Rageblade  n=30  wr=60.0  -> NOT in scorer grid at all
  Statikk Shiv         n=19  wr=57.9  -> NOT in scorer grid at all
  Nashor's Tooth       n=16  wr=56.2  -> NOT in scorer grid at all
  BotRK                n=18  wr=55.6  -> scorer rank #1 (ad_squishy) - correct

Scorer top-8 (ad_squishy): BotRK(#1), Hurricane(#2), Kraken Slayer(#3), Void Immolation(#4),
Essence Reaver(#5), Stormrazor(#6), Yun Tal(#7), IE(#8).

Empirically losing items inside scorer top-8:
  Navori Flickerblade  scorer #10  empirical wr=20.0 (n=5)
  Yun Tal Wildarrows   scorer #7   empirical wr=20.0 (n=5)
  Infinity Edge        scorer #8   empirical wr=40.0 (n=5, below 56.1 baseline)

The three empirically-best staples (Guinsoo's, Statikk Shiv, Nashor's Tooth) are entirely
absent from the pool. Kaisa's AP-hybrid evolution path (Q evolves with AP, E evolves with AS/AP)
drives significant on-hit and AP-mixed builds that the pure AD DPS pool does not model.
Scorer also elevates pure-crit (IE, Yun Tal, Navori) items that empirically underperform.

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated Retune

Add Guinsoo's Rageblade, Statikk Shiv, and Nashor's Tooth to Kaisa's DS item pool.
These three items are Kaisa's top empirical performers (wr 57.9-60.0, n=16-30) and are
entirely absent from all five comp cells. Root cause is likely that Kaisa's hybrid AP/on-hit
build path is not represented in the current dps-scorer item candidate set.
Secondary: audit Navori, Yun Tal, IE rank inflation - pure-crit items over-indexed vs hybrid.
