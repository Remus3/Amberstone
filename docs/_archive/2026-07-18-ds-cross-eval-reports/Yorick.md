# DS Cross-Eval: Yorick

**VERDICT: MINOR**

Archetype hybrid (AD bruiser) is correct. Comp responsiveness is real. Two empirical staples fall outside the scorer top-8: Sundered Sky sits at rank 12 despite 64.5% wr (n=31 ARAM), and Spirit Visage is absent from all comp-grid cells entirely despite 63.2% wr (n=19 ARAM). Essence Reaver occupies rank 5 with zero empirical above-baseline support.

---

## Axis 1: archetype_ok = true

Scorer = hybrid (AD axis, bruiser archetype). Yorick kit is fully AD: ghouls, Maiden of the Mist, and all scaling are AD/physical. Empirical ARAM above-baseline (champ wr 52.9%): Iceborn Gauntlet 71.4% (n=21), Sundered Sky 64.5% (n=31), Spirit Visage 63.2% (n=19), Mercury's Treads 58.1% (n=31). These are AD/tank/sustain items. Hybrid AD scorer is the correct axis.

---

## Axis 2: comp_ok = true

Scorer = hybrid, primary_axis = enemy_damage_type, comp_blind = false (both axes). Wit's End rises +18 ranks when enemies are AP - the strongest single-item shift in the pool, showing the EHP layer responds to damage type. Dead Man's Plate falls -5 (armor less valuable vs AP). Target_resist axis also moves: Liandry's Torment +15 when targets are AP tanky. Both responsiveness blocks are comp_blind = false. No DEFECT.

Note: Liandry's rising +15 for Yorick (an AD champion) vs AP-tanky targets is worth a curiosity flag - it implies the hybrid scorer has some AP-item bleed at extreme armor conditions - but is not a blocking comp_blind issue since the primary AD items still dominate the squishy cells.

---

## Axis 3: outcome_ok = false

Using outcome_all (n=51 ARAM, evidence_tier ARAM = outcome_all). Baseline wr = 52.9%.

Above-baseline empirical items:
- Iceborn Gauntlet: 71.4% wr (n=21) - rank 7 ad_squishy, rank 8 bal_squishy - IN top-8, OK
- Sundered Sky: 64.5% wr (n=31) - rank 12 ad_squishy, rank 12 bal_squishy - NOT in top-8, FLAGGED
- Spirit Visage: 63.2% wr (n=19) - absent from all 5 comp-grid cells entirely, FLAGGED
- Mercury's Treads: 58.1% wr (n=31) - boots, excluded from comp-grid pool by design, acceptable

Scorer top-8 items with no above-baseline empirical signal (ARAM):
- Essence Reaver: rank 5 ad_squishy / rank 5 bal_squishy (d_dps=56.5, d_ehp=0.0) - 0 empirical ARAM rows
- Runaan's Hurricane: rank 6 ad_squishy / rank 6 bal_squishy - 0 empirical ARAM rows
- Void Immolation: rank 1 across all cells (6000g mythic) - 0 empirical rows; high gold cost means low sample rate, less actionable

Sundered Sky out of top-8 despite being a 64.5%-wr staple (n=31) is the primary finding. Spirit Visage entirely absent from the pool despite 63.2% wr / n=19 is the secondary finding; Yorick's W gravetending passive heals him and interacts with healing-amp, which Spirit Visage directly buffs.

---

## Axis 4: rune_ok = n/a

rune_relevant = false.

---

## Nominated Retune

Sundered Sky pool weight boost: it contributes both d_ehp (994-1042) and d_dps (28.6) at rank 12 in squishy cells; re-weighting or reducing a competing penalty should lift it into top-8 for squishy matchups.

Spirit Visage addition to item pool: currently entirely absent from comp-grid; add with healing-amp credit tied to Yorick W passive gravetending self-heal. Expected rank: moderate EHP-healing hybrid, likely top-10 once included.

Essence Reaver demotion review: rank 5 with 0 empirical ARAM presence and d_ehp=0; pure mana-CDR value is being overweighted for a champion who builds tank/bruiser in practice.
