# DS Cross-Eval: Smolder

**Verdict: MINOR**
Scorer (dps / carry-AD) axis is correct. Target-resist responsiveness is present. Pool has real gaps: BotRK ranks #1 scorer with zero empirical footprint; Rapid Firecannon (n=61, wr=52.5%) absent from scorer top-12; Liandry's (n=25, wr=68.0%) underweighted vs squishies.

---

## Evidence basis

- Evidence tier ARAM: outcome_all (n=154, baseline wr=48.7%)
- Evidence tier SR: outcome_all (n=48, baseline wr=47.9%)
- Self n=7 ARAM (too small); using all throughout.

---

## Axis 1 - archetype_ok: PASS

Scorer = dps. Primary archetype = carry (AD). Smolder is an AD ability-scaling marksman whose damage scales off AD/crit/ability. dps scorer on AD carry is the correct axis. Empirical above-baseline items (ARAM all, wr > 48.7%): Rapid Firecannon 52.5%, Liandry's 68.0%, Bloodthirster 60.0%, Ionian Boots 50.5%. All are AD-adjacent or hybrid. No AP mage items dominate empirically to challenge the archetype call.

---

## Axis 2 - comp_ok: PASS

Scorer = dps. dps scorers must respond to target_resist (tanky vs squishy), which this one does: max_positive_shift = +21 ranks (Liandry's Torment rises +21 vs tanky). target_resist.comp_blind = false. Enemy damage_type.comp_blind = true (max_positive_shift = 0), but damage-type responsiveness is an ehp/hybrid concern, not a dps concern. No defect.

---

## Axis 3 - outcome_ok: MINOR FLAG

Scorer top-8 in ad_squishy (reference comp):
1. Blade of The Ruined King (75.4)
2. Void Immolation (51.0)
3. Kraken Slayer (46.4)
4. Essence Reaver (45.4)
5. Runaan's Hurricane (44.6)
6. Stormrazor (42.8)
7. Infinity Edge (38.5)
8. Eclipse (37.7)

Empirical ARAM all - items above baseline wr 48.7%:
- Rapid Firecannon: n=61, wr=52.5% -- ABSENT from scorer top-12 in all comp cells
- Liandry's Torment: n=25, wr=68.0% -- top-5 only in *tanky* cells (rank 5); absent from squishy cells top-8
- Bloodthirster: n=20, wr=60.0% -- absent from all scorer cells shown
- Ionian Boots: n=111, wr=50.5% -- boots, not in item pool (expected)
- Spear of Shojin: n=85, wr=48.2% -- below baseline, not flagged
- Muramana: n=79, wr=44.3% -- below baseline

BotRK is scorer rank 1 with zero empirical entries in the top-10 list (not present at all in ARAM or SR empirical data). This inversion (scorer #1, empirically absent) is the primary pool-quality signal.

---

## Axis 4 - rune_ok: n/a

rune_relevant = false.

---

## Nominated retune

Investigate why BotRK scores 75.4 with no empirical footprint - likely an AA-frequency or on-hit damage modeling gap vs Smolder's actual ability-cast-heavy pattern. Elevate Rapid Firecannon and Bloodthirster in the dps scorer pool for Smolder; both show above-baseline wr with meaningful sample sizes (n=61 and n=20 respectively).
