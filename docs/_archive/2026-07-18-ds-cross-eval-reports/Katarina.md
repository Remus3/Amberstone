# DS Cross-Eval: Katarina

**VERDICT: MISMATCH**

Scorer: ability | Archetype: mage/assassin | Anchor: ARAM | Evidence: outcome_self (n=28, wr=46.4%)

---

## Axis 1 - archetype_ok: TRUE

Ability scorer = AP axis. Katarina kit is AP burst (Q/E/R all AP-scaling, Shunpo resets on kills).
Mage primary / assassin secondary is a defensible AP assignment.
HOWEVER: empirical ARAM self above-baseline winners are Heartsteel 56.2% (n=16) and Titanic Hydra
62.5% (n=16) - off-tank HP items, not AP. The scorer axis is kit-correct but diverges from what
actually wins in practice. Flagged as context for outcome axis; archetype assignment itself is OK.

## Axis 2 - comp_ok: TRUE

Ability scorer primary_axis = target_resist (comp_blind=false). Max shift = +3 vs tanky enemies.
Risers vs tanky: Bloodletter's Curse +3, Cryptbloom +2, Void Staff +1. This is correct behavior -
ability scorer should respond to target MR, and it does.

enemy_damage_type comp_blind = TRUE (max_positive_shift=0, no risers/fallers). For an ability/burst
scorer, enemy damage-type composition responsiveness is not required - the scorer's job is to
maximize AP damage output, not to track what the enemy team is dealing. comp_ok is true.

## Axis 3 - outcome_ok: FALSE (MISMATCH)

Using ARAM outcome_self (n=28 >= 8). Baseline wr = 46.4%.

Scorer top-8 (bal_squishy / ad_squishy identical):
  Rank 1 Liandry's Torment - not in empirical self list
  Rank 2 Wooglet's Witchcap - not in empirical self list
  Rank 3 Blackfire Torch - not in empirical self list
  Rank 4 Rabadon's Deathcap - empirical wr 16.7% (n=6) FAR below baseline
  Rank 5 Void Staff - not in empirical self list
  Rank 6 Shadowflame - empirical wr 33.3% (n=6) below baseline
  Rank 7 Cryptbloom - not in empirical self list
  Rank 8 Stormsurge - not in empirical self list (appears in outcome_all at 38.1%)

Empirical self above-baseline items (wr > 46.4%):
  Heartsteel 56.2% (n=16) - ABSENT from scorer pool
  Titanic Hydra 62.5% (n=16) - ABSENT from scorer pool
  Nashor's Tooth 66.7% (n=9) - ABSENT from scorer pool
  Mercury's Treads 71.4% (n=7) - footwear, low n, ABSENT from scorer pool
  Needlessly Large Rod 66.7% (n=6) - component, low n

Scorer top-4 AP items either absent from empirical self entirely or losing heavily when present
(Rabadon's 16.7%, Shadowflame 33.3%). The three dominant empirical winners (Heartsteel, Titanic
Hydra, Nashor's Tooth) are all absent from the ability scorer pool. The pool is empirically inverted.

## Axis 4 - rune_ok: N/A

rune_relevant = false.

---

## Nominated Retune

Investigate eligibility of Heartsteel, Titanic Hydra, and Nashor's Tooth for the Katarina ability
scorer item pool. Current AP-only pool excludes the ARAM-dominant off-tank build path entirely. The
winning pattern (HP-stacking + on-hit) may warrant either: (a) a pool expansion adding these items
with appropriate scoring factors, or (b) a secondary bruiser/assassin scorer blend for Katarina
specifically. Additionally, Rabadon's Deathcap at rank 4 with 16.7% empirical wr and Shadowflame at
rank 6 with 33.3% wr suggest overcounting amplifier multipliers relative to raw AP stats in low-n
ARAM contexts.
