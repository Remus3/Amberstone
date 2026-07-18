# Thresh DS Scorer Cross-Eval

**VERDICT: MISMATCH**

Archetype: enchanter/tank | Scorer: hps | ARAM evidence: outcome_self (n=20, wr=70.0%)

---

## Axis 1 - archetype_ok: TRUE (with flag)

Thresh is labeled enchanter/tank; hps is the designated enchanter scorer. Axis assignment is internally consistent.

Flag: empirical ARAM self play (n=20, wr=70.0%) shows zero enchanter items in top-5. Actual winning builds are pure tank: Fimbulwinter (n=14, wr=64.3%), Unending Despair (n=14, wr=64.3%), Heartsteel (n=9, wr=77.8%). Thresh is played as a hook-tank in practice, not an enchanter buffing allies. archetype label is technically valid but the scorer-vs-playstyle gap is real.

## Axis 2 - comp_ok: TRUE

Scorer = hps (enchanter). Enchanter scorers are comp-invariant by design. comp_blind=true, max_positive_shift=0 on both enemy_damage_type and target_resist axes. This is expected and correct for an enchanter scorer. No defect.

## Axis 3 - outcome_ok: FALSE

Using outcome_self (n=20 >= 8). Baseline wr = 70.0%.

Scorer top-8 (all comp cells identical): Echoes of Helia (r1, score=26.5), Ardent Censer (r2, 15.0), Staff of Flowing Water (r3, 12.0), Locket of the Iron Solari (r4, 11.3), Knight's Vow (r5, 10.0), Redemption (r6, 8.0), Imperial Mandate (r7, 6.0), Mikael's Blessing (r8, 3.9).

Empirical self items (ARAM):
- Fimbulwinter n=14 wr=64.3%
- Unending Despair n=14 wr=64.3%
- Mercury's Treads n=11 wr=45.5%
- Heartsteel n=9 wr=77.8%  <- ABOVE baseline
- Guardian's Horn n=6 wr=50.0%

Overlap between scorer top-8 and empirical items: ZERO. Not a single scorer-recommended item appears in the empirical dataset. Heartsteel (wr=77.8%, above 70% baseline) is entirely absent from the scorer pool. Moonstone Renewer sits at rank 9 with score=0.0, suggesting the hps scorer is aware of tank-adjacent items at the margin but does not surface tank items at all.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Consider adding a secondary archetype path for Thresh that routes tank-item scoring (EHP/bruiser weight) when empirical builds trend full-tank. The hps scorer is appropriate for enchanter Thresh builds but the real winning builds (Heartsteel, Fimbulwinter, Unending Despair) are unscored. Option: add tank secondary scorer dispatch at the same weight as the enchanter scorer, or promote tank as primary given empirical evidence. At minimum, add Heartsteel/Fimbulwinter/Unending Despair to the hps scorer pool with partial credit so they do not score 0.
