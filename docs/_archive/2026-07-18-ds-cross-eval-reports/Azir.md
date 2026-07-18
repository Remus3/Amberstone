# DS Cross-Eval: Azir

**VERDICT: MINOR**

Scorer: ability | Archetype: mage/carry | Evidence tier ARAM: outcome_all (n=82, wr=54.9%)

---

## Axis 1 - archetype_ok: PASS

Azir is a pure AP mage. His soldiers deal AP damage, all abilities scale AP. The ability scorer (AP axis) is correct. Empirical above-baseline items are all AP or AP-adjacent (Liandry's 58.5%, Shadowflame 57.6%, Rabadon's 69.6%, Zhonya's 84.6%). No axis mismatch.

## Axis 2 - comp_ok: PASS

Scorer: ability. Primary axis is target_resist (correct for AP damage dealer - pen items rise vs tanky).

enemy_damage_type: comp_blind=true (max_positive_shift=0, no risers/fallers). This is acceptable for a pure AP caster with no adaptive/hybrid component - the scorer does not adapt to enemy damage type, but that is not a defect for this kit.

target_resist: responsive. max_positive_shift=6. Bloodletter's Curse rises +6 (rank 8 ad_tanky vs absent in squishy), Void Staff +2, Cryptbloom +2 when targets are AP-tanky. Correct behavior.

## Axis 3 - outcome_ok: FAIL (pool gap)

Scorer top-8 (ad_squishy, identical across all squishy comps): Liandry's (#1, 28.5), Wooglet's (#2, 26.3), Blackfire Torch (#3, 19.1), Rabadon's (#4, 9.9), Shadowflame (#5, 8.6), Void Staff (#6, 8.4), Stormsurge (#7, 7.3), Cryptbloom (#8, 6.3).

Above-baseline empirical (wr > 54.9%, outcome_all n=82):
- Nashor's Tooth: n=75, wr=56.0% - NOT in scorer top-12 at all
- Liandry's Torment: n=53, wr=58.5% - scorer #1 (aligned)
- Shadowflame: n=33, wr=57.6% - scorer #5 (aligned)
- Rabadon's Deathcap: n=23, wr=69.6% - scorer #4 (aligned)
- Rylai's Crystal Scepter: n=15, wr=60.0% - NOT in scorer top-12
- Zhonya's Hourglass: n=13, wr=84.6% - scorer #10 (below top-8)
- Berserker's Greaves: n=9, wr=77.8% - NOT in scorer pool (attack speed, not AP)

Critical miss: Nashor's Tooth is the highest-frequency empirical item (n=75, 91% of games) with above-baseline wr (56.0%), yet it does not appear anywhere in the scorer's top-12. Azir's soldiers are auto-attack-based and Nashor's Tooth grants attack speed + on-hit AP damage + CDR - it is a core Azir item. Its complete absence from the scorer pool is a meaningful gap. Rylai's also absent despite 60.0% wr.

## Axis 4 - rune_ok: N/A

rune_relevant=false.

---

## Nominated Retune

Add Nashor's Tooth (id 3115) to ability scorer item pool for Azir; investigate why attack-speed AP hybrid items (Nashor's Tooth) are excluded. Audit Rylai's Crystal Scepter absence (id 3116, wr=60.0%, n=15). Zhonya's Hourglass (wr=84.6%) could be promoted above top-8 threshold but its n=13 is borderline.
