# DS Cross-Eval Report: Irelia

**Verdict: MINOR**
Scorer axis and top-item alignment are correct; two pool-composition issues degrade recommendation quality.

---

## Axis 1 - archetype_ok: TRUE

- archetype primary=bruiser, secondary=assassin, scorer=hybrid (ehp+dps blend).
- Hybrid is the correct scorer for an AD melee fighter that must survive to stack and sustain.
- Empirical ARAM self (n=30, baseline wr=46.7%): above-baseline items are Blade of the Ruined King
  (wr=51.9%, n=27), Mercury's Treads (wr=50.0%, n=14), Plated Steelcaps (wr=50.0%, n=6). All AD/bruiser.
  No AP item outperforms baseline. Archetype and scorer axis are aligned.

---

## Axis 2 - comp_ok: TRUE

- Scorer=hybrid: primary_axis=enemy_damage_type, comp_blind=false. Pass.
- EHP moves across comp cells: Void Immolation d_ehp = 4482.9 (ad_squishy) -> 3786.9 (ap_squishy),
  a -696 shift. BotRK d_ehp 157.0 -> 134.1. Not comp-blind.
- enemy_damage_type max_positive_shift=14 (Wit's End rises 14 ranks vs AP-heavy comp).
- target_resist max_positive_shift=12 (Lord Dominik's +12, Black Cleaver +11 vs tanky AP). Responsive.

---

## Axis 3 - outcome_ok: FALSE (MINOR pool gaps)

Evidence: ARAM outcome_self (n=30 >= 8, baseline wr=46.7%).

**Good alignment:**
- Blade of the Ruined King rank-2 scorer (ad_squishy, score=1.1709) and top empirical item
  (wr=51.9%, n=27). Strong overlap.

**Gap 1 - Sundered Sky absent from scorer top-8:**
- Empirical: Sundered Sky (id=6610) n=23, wr=47.8% (above 46.7 baseline). Third most-built item.
- Scorer: Sundered Sky does not appear in the ad_squishy or bal_squishy top-8.
  A frequently-built, above-baseline staple is missing from scorer recommendations.

**Gap 2 - Runaan's Hurricane rank-3 scorer, zero empirical presence:**
- Scorer: Runaan's Hurricane rank-3 in all squishy cells (d_dps=93.8, score=0.8546).
- Empirical: Runaan's Hurricane does not appear in ARAM self or all item lists.
  This is a marksman multi-hit item; the scorer inflates it via DPS math Irelia cannot
  realistically leverage (she is a melee auto-reset fighter, not a marksman).

**Other scorer top-8 items with no empirical presence:** Trinity Force (rank-4), Kraken Slayer (rank-5),
Essence Reaver (rank-6). Only BotRK from the top-8 appears above-baseline empirically.
The pool overrepresents crit/attack-speed items built on ranged champions.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Two targeted fixes:

1. **Runaan's Hurricane eligibility gate:** Runaan's generates high multi-hit DPS math but Irelia
   (melee, no inherent AoE auto, bruiser archetype) does not build it in practice. Investigate whether
   the DPS model for Runaan's assumes a range-agnostic multi-hit path; if so, gate the item's
   eligibility by champion archetype (marksman/ranged-carry only) or add a melee penalty
   to its DPS contribution.

2. **Sundered Sky pool inclusion:** Sundered Sky is Irelia's third most common item (n=23, wr=47.8%)
   and does not appear in scorer top-8 despite above-baseline win rate. Audit why it scores below
   rank-8 - likely missing a crit-on-full-HP or healing-on-crit passive valuation in the hybrid scorer.
   Consider adding an ability-haste or healing interaction entry for id=6610.
