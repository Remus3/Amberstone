# DS Cross-Eval: Urgot

**Verdict: MINOR**

Scorer: hybrid | Archetype: bruiser/tank | Anchor: ARAM | Evidence tier (ARAM): outcome_all

---

## Axis 1 - archetype_ok: PASS

Urgot is bruiser/tank. Hybrid scorer = AD axis. Bruiser is AD-aligned (carry/bruiser/assassin=AD). Kit is AD (W empowered physical shots, R AD scaling, no AP ratios). Empirical above-baseline winners from outcome_all (baseline 45.9%, n=74): Jak'Sho 63.6% (n=11), Overlord's Bloodmail 50.0% (n=10), Titanic Hydra 49.0% (n=49) - all AD-bruiser/tank items. Axis correct.

## Axis 2 - comp_ok: PASS

Scorer = hybrid (has EHP component). comp_blind=false confirmed. enemy_damage_type: Wit's End rises +17 ranks when AP-heavy; Dead Man's Plate falls -7. target_resist: Liandry's rises +15 vs tanky; Eclipse +8. Both axes respond meaningfully to comp. EHP component reacts to incoming damage type as expected. No comp-blind defect.

## Axis 3 - outcome_ok: FAIL

Using outcome_all (n=74, self n=6 < 8). Baseline ARAM wr=45.9%.

Above-baseline empirical items:
- Jak'Sho, The Protean: 63.6% wr (n=11) - ABSENT from scorer top-8 in all comp cells
- Overlord's Bloodmail: 50.0% wr (n=10) - ABSENT from scorer top-12 entirely
- Titanic Hydra: 49.0% wr (n=49) - not in scorer top-8 (ranks vary; rises only +1 in responsiveness)

Scorer top-8 (ad_squishy): Void Immolation, BotRK, Trinity Force, Heartsteel, Essence Reaver, Runaan's Hurricane, Iceborn Gauntlet, Dusk and Dawn.

Problems:
- Essence Reaver rank 5 (d_dps=55.1, d_ehp=0): crit/mana item with zero EHP contribution; Urgot does not crit-build effectively; below baseline in practice.
- Runaan's Hurricane rank 6 (d_dps=52.7, d_ehp=0): attack-speed spread item; not a real Urgot staple; below baseline in practice.
- Heartsteel rank 4 (n=54, wr=40.7%): in scorer top-8 but empirically BELOW baseline - actively a losing build path.
- Jak'Sho and Overlord's Bloodmail, the two clearest above-baseline winners, are entirely absent from scorer top-8.

The scorer over-weights pure DPS items (Essence Reaver, Runaan's) and misses the tanky HP items (Jak'Sho, Overlord's Bloodmail) that actually win games on Urgot.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Adjust hybrid scorer EHP/DPS balance for Urgot: reduce weight on pure-DPS no-EHP items (Essence Reaver, Runaan's Hurricane rank <8), boost relative rank of Jak'Sho, Titanic Hydra, and Overlord's Bloodmail. Consider a champion-specific EHP weight nudge or a tank-item bonus path in the bruiser hybrid scorer so HP-stacking items surface above crit/AS items for this champion.
