# DS Cross-Eval: Briar

**Verdict: MISMATCH**
Scorer top-2 items (BotRK 37.5% wr, Heartsteel 44.4% wr) both lose empirically; highest-wr staples (Sterak's Gage 63.6%, Sundered Sky 54.8%, Death's Dance 52.9%) all absent from scorer top 8.

---

## Evidence tier

- ARAM: outcome_all (n=38, baseline wr=52.6%)
- SR: outcome_all (n=28, baseline wr=39.3%; small sample, low signal)

Primary evidence: ARAM outcome_all.

---

## Axis 1 - archetype_ok: TRUE

Briar is bruiser (primary) / assassin (secondary). Scorer is "hybrid" (EHP+DPS blend) on the AD axis. Kit is AD melee bruiser: bleed DOT, life-drain healing, dive/reset mechanic. Hybrid AD scorer is the correct axis assignment. Empirical above-baseline items (Sundered Sky, Sterak's Gage, Death's Dance) are all AD bruiser items, confirming the AD-axis call is right. No axis mismatch.

---

## Axis 2 - comp_ok: TRUE

Scorer is "hybrid" (EHP+DPS blend). comp_blind=false. Primary responsiveness axis = enemy_damage_type (max_positive_shift=7: Wit's End rises 7 ranks when enemy is AP-heavy). Target resist also moves (max +12: Liandry rises 12 when tanky, Mortal Reminder/Eclipse/LDR all shift significantly).

EHP component of the hybrid scorer is expected to respond to enemy_damage_type, and it does. DPS component responds to target_resist composition. Neither axis is frozen. comp_ok=true: the scorer is responsive, not comp-blind.

---

## Axis 3 - outcome_ok: FALSE

Using ARAM outcome_all (n=38, baseline wr=52.6%).

Above-baseline empirical items (wr > 52.6%):
- Sterak's Gage: 63.6% wr, n=11 - ABSENT from scorer top 8 (not ranked at all in ad_squishy top 8)
- Sundered Sky: 54.8% wr, n=31 (largest sample) - rank 12 in ad_squishy, rank 11 in bal_squishy; NOT in top 8
- Mercury's Treads: 53.8% wr, n=26 - boots (not in item pool)
- Death's Dance: 52.9% wr, n=17 - absent from ad_squishy top 8 entirely

Scorer top-8 items that empirically lose (wr below 52.6% baseline):
- BotRK: rank 2 (score 1.3053), empirical wr=37.5% (n=8) - 15 points below baseline, clearly losing
- Heartsteel: rank 4 (score 1.0649), empirical wr=44.4% (n=9) - 8 points below baseline

Summary: two of the top-4 scorer picks lose games. The three strongest empirical signals (Sterak's Gage, Sundered Sky, Death's Dance) are all outside the scorer top 8. This is a real outcome misalignment.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated retune

bruiser_hybrid_briar: reduce pure DPS weighting for Briar's hybrid scorer; BotRK's high d_dps (67.7) is inflating its rank despite poor empirical outcomes. Sterak's Gage and Death's Dance carry significant EHP (shield, DR) value not captured by d_ehp raw stat - add shield/DR EHP-multiplier recognition for bruiser archetype. Heartsteel rank 4 (d_ehp=1637 but wr=44.4%) suggests over-weighting passive EHP on a kit that needs active survivability (Sterak's Gage active shield, Death's Dance damage-to-heal). Consider a bruiser-specific penalty for items with zero d_ehp contribution in a hybrid scorer (Essence Reaver, Runaan's Hurricane, Stormrazor all rank 5-8 with d_ehp=0 and are unlikely bruiser purchases).
