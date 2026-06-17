# DS Cross-Eval: Tristana

**VERDICT: MINOR**

Scorer: dps | Archetype: carry (AD) | Anchor: ARAM | Evidence: outcome_self (n=61 ARAM, n=78 SR)

---

## Axis 1 - archetype_ok: PASS

Tristana is an AD marksman. carry+dps is the correct axis (AD carry = dps scorer). Empirical
ARAM self items confirm AD crit/AS builds win: Navori Flickerblade 74.5% (n=51), Infinity Edge
74.5% (n=47), Yun Tal Wildarrows 75.8% (n=33), The Collector 78.3% (n=23). All AD items, no
off-axis AP or tank items in the above-baseline cluster. Scorer axis matches kit and empirical.

## Axis 2 - comp_ok: PASS

Primary axis is target_resist. dps scorer does not depend on enemy damage type (it measures your
own output vs target resistances only), so enemy_damage_type comp_blind=true is expected and not
a defect for this scorer type. The relevant axis (target_resist) is NOT comp-blind: max positive
shift = +22 rank positions when facing tanky enemies. Top risers vs tanky: Liandry's Torment +22,
Serylda's Grudge +9, Lord Dominik's Regards +7, Mortal Reminder +6, Eclipse +6. The scorer
correctly re-ranks anti-tank options when target armor/MR increases. comp_ok = pass.

## Axis 3 - outcome_ok: MINOR FLAG

Baseline wr ARAM self: 72.1%. Above-baseline items (wr > 72.1%, n >= 8):
- Navori Flickerblade: 74.5% wr, n=51
- Infinity Edge: 74.5% wr, n=47
- Yun Tal Wildarrows: 75.8% wr, n=33
- The Collector: 78.3% wr, n=23

Scorer ad_squishy top-8: #1 BotRK, #2 Runaan's Hurricane, #3 Kraken Slayer, #4 Essence Reaver,
#5 Stormrazor, #6 Void Immolation, #7 Infinity Edge, #8 Yun Tal Wildarrows.

IE and Yun Tal appear in top-8 (ranks 7, 8). Navori Flickerblade lands at rank 10 - just outside
top-8, minor gap. The Collector (78.3% wr, n=23, highest above-baseline item) is completely absent
from scorer top-8 in both squishy cells. It is also absent from tanky cells' top-8. This is a
meaningful pool gap: the empirically best-performing item is not surfaced by the scorer in any
comp context. The target_resist faller list confirms the scorer sees The Collector as -6 shift
vs tanky, which depresses its rank when tanky is the test cell - but in squishy cells the penalty
should be absent and the item still fails to crack top-8.

BotRK is the scorer's #1 pick (score 123.3) but ranks 7th in empirical ARAM self by frequency
(n=13, wr=61.5%) - below the 72.1% baseline. BotRK overranked relative to empirical signal.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Investigate why The Collector scores below rank 8 in squishy cells. It has no armor-pen
interaction that would harm it vs squishies, and the empirical signal (78.3% wr, n=23) is
clear. Likely cause: the scorer does not model The Collector's execute passive (bonus damage
vs low-HP targets) or its AD+crit efficiency vs squishy targets. Also check BotRK overrank -
its %HP damage model may over-credit vs squishy (no %HP tank to drain), inflating its raw DPS
number vs calibrated empirical results.

Suggested action: add The Collector execute passive to DS item effects if not already modeled;
re-validate BotRK squishy scaling to ensure %HP component does not double-count vs low-HP targets.
