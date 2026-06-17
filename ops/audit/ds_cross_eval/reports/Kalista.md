# DS Cross-Eval: Kalista
**Verdict: MISMATCH**
Scorer: dps | Archetype: carry (AD) | Anchor: ARAM | Evidence: outcome_self (n=50, baseline wr=62.0)

---

## Axis 1 - archetype_ok: TRUE

dps scorer is AD-axis. Kalista is a physical ADC with on-hit/attack-speed kit.
Empirical top items all physical/on-hit: BotRK (n=45, wr=62.2), Runaan's (n=33, wr=63.6), Guinsoo's (n=33, wr=54.5).
AD-axis scorer aligns with both kit and empirical winner profile.

---

## Axis 2 - comp_ok: FALSE

**DEFECT: enemy_damage_type is fully comp-blind (max_positive_shift=0, top_risers_when_ap=[]).**

All five comp cells (ad_squishy, bal_squishy, ap_squishy, ad_tanky, ap_tanky) produce identical scores for
squishy targets (BotRK 138.36, Runaan's 93.10, Void Immolation 92.25 - all three unchanged across AD/BAL/AP
squishy). d_ehp and d_dps are 0.0 across every cell. The scorer cannot distinguish AP-heavy vs AD-heavy
enemy comps at all.

For a dps scorer on a physical ADC this matters: Wit's End (MR shred, good vs AP) should rise when enemy is
AP-heavy; it does not appear in scorer top-8 in any squishy comp. The armor-pen items (LDR, Serylda's) are
correctly suppressed vs squishy but the AP-responsive on-hit options are invisible to the scorer.

target_resist responsiveness is working (max_positive_shift=23; Liandry's +23, Serylda's +8, LDR +6 vs tanky
- correct behaviour for a physical dps scorer facing tanky enemies). But the squishy-cell comp-blindness is
a structural defect.

---

## Axis 3 - outcome_ok: FALSE

Baseline wr = 62.0 (outcome_self, n=50). Above-baseline empirical items:
- Berserker's Greaves (n=40, wr=62.5) - ABSENT from scorer entirely
- Runaan's Hurricane (n=33, wr=63.6) - scorer rank #2 in ad_squishy (OK)
- Wit's End (n=11, wr=63.6) - ABSENT from scorer top-8
- Phantom Dancer (n=8, wr=87.5) - ABSENT from scorer top-8
- Navori Flickerblade (n=6, wr=83.3) - scorer rank #10 (just outside top-8)

Critical: Berserker's Greaves is the most-worn item (n=40) with above-baseline wr and does not appear in the
scorer at all. It is not a combat-stat item (pure boots) so likely excluded from the item pool by design, but
empirically it is a strong signal item worn in 80% of games.

Phantom Dancer (wr=87.5, n=8) and Wit's End (wr=63.6, n=11) both beat baseline and are absent from top-8.
Scorer top-8 contains Kraken Slayer (#4, wr not in empirical top), Essence Reaver (#5, absent empirically),
Stormrazor (#6, absent empirically), Infinity Edge (#7, absent empirically), Yun Tal (#8, absent empirically)
- none of these appear in the empirical item list at all, meaning they are not commonly built or win with
Kalista in practice. The scorer is over-weighting crit/burst items relative to Kalista's actual on-hit
playstyle.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

1. Add Berserker's Greaves to scorer item pool (or confirm intentional boots exclusion and document).
2. Wire enemy damage type into dps scorer so Wit's End and other on-hit MR items rise vs AP-heavy comps.
3. Audit Phantom Dancer scoring - 87.5% wr empirically, absent top-8; likely attack-speed/dodge passive
   not captured in dps formula.
4. Demote crit-burst items (Essence Reaver, Stormrazor, Infinity Edge) that are empirically absent from
   Kalista builds; Kalista's kit does not scale as well with raw crit as standard marksmen.
