# DS Cross-Eval: Draven

**Verdict: MISMATCH**
Scorer top pool (BotRK, Runaan's, Void Immolation) diverges sharply from empirical high-wr staples (Collector 60.0%, Bloodthirster 73.3%, LDR 71.4%, RFC 85.7%).

---

## Axis 1 - archetype_ok: TRUE

Draven is a pure AD carry (spinning-axe AA-based physical kit). Scorer axis = dps (AD).
Empirical ARAM self (n=39, baseline 56.4%) above-baseline items are all AD:
- The Collector n=35 wr=60.0%
- Infinity Edge n=28 wr=57.1%
- Bloodthirster n=15 wr=73.3%
- Lord Dominik's Regards n=14 wr=71.4%
- Rapid Firecannon n=7 wr=85.7%
- BotRK n=7 wr=57.1%

AD carry axis is correct.

---

## Axis 2 - comp_ok: TRUE

Scorer = dps. Primary axis is target_resist (not enemy_damage_type), which is correct for a
physical DPS caster scoring against target armor/MR.

target_resist moves as expected: max_positive_shift=18, Liandry's Torment +18, LDR +6,
Eclipse +5. The scorer adjusts recommendations when enemies are tanky.

enemy_damage_type comp_blind=TRUE with max_positive_shift=0. This is NOT a defect for a
dps scorer - enemy damage type does not affect which AD items Draven should build. The
top-level responsiveness.comp_blind=false confirms the scorer is not globally blind.

No defect here.

---

## Axis 3 - outcome_ok: FALSE (MISMATCH)

Using outcome_self (n=39 >= 8 threshold). Baseline wr=56.4%.

Empirical items above baseline:
- The Collector n=35 wr=60.0% - high-n flagship
- Bloodthirster n=15 wr=73.3%
- Lord Dominik's Regards n=14 wr=71.4%
- Rapid Firecannon n=7 wr=85.7%
- BotRK n=7 wr=57.1%

Scorer top-8 (ad_squishy): BotRK(1), Runaan's Hurricane(2), Void Immolation(3),
Essence Reaver(4), Kraken Slayer(5), Stormrazor(6), Infinity Edge(7), Yun Tal Wildarrows(8).

Mismatches:
- The Collector (n=35, wr=60%) - completely absent from scorer top-8
- Bloodthirster (wr=73.3%) - absent from scorer top-8
- Lord Dominik's (wr=71.4%) - absent from scorer squishy top-8 (only rank 11 in tanky cell)
- Rapid Firecannon (wr=85.7%) - absent from scorer pool entirely
- Runaan's Hurricane (rank 2 scorer) - absent from empirical top-10 entirely
- Void Immolation rank 3 scorer at 6000g - absent from empirical
- Kraken Slayer rank 5 scorer - absent from empirical

BotRK is scorer rank 1 but only n=7 wr=57.1% empirically (barely above baseline, low n).
The pool is dominated by on-hit / attack-speed items while the empirical signal points to
crit + execute (Collector, IE, BT, LDR, RFC).

---

## Axis 4 - rune_ok: n/a

rune_relevant=false.

---

## Nominated Retune

Boost crit+execute item scores: The Collector, Bloodthirster, Lord Dominik's Regards,
Rapid Firecannon should all score higher for Draven's dps profile. Demote or cap
Runaan's Hurricane (no empirical support) and Void Immolation (prohibitively expensive,
zero empirical presence). Verify that Draven's stack-axe mechanic is correctly modeled
as crit-amplified physical DPS rather than flat on-hit.
