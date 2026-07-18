# Soraka - DS Scorer Cross-Eval Report

VERDICT: MINOR

Scorer: hps | Archetype: enchanter/mage | Anchor: ARAM outcome_all (n=117, wr=52.1%)

## Axis 1 - archetype_ok: TRUE

enchanter primary with hps scorer matches kit (heal/shield support). AP heal/shield axis is correct. No mismatch.

## Axis 2 - comp_ok: TRUE

comp_blind=true across all comp cells. hps/enchanter scorer invariance is EXPECTED per program rubric - comp signals ally value, no scorer surface. Not a defect.

## Axis 3 - outcome_ok: MINOR (pool gap)

Scorer top-8: Echoes of Helia(r1,score=29.2), Ardent Censer(r2,18.4), Staff of Flowing Water(r3,14.6), Locket(r4,11.3), Imperial Mandate(r5,10.9), Redemption(r6,10.3), Knight's Vow(r7,10.0), Mikael's Blessing(r8,3.9).

Empirical ARAM above-baseline (baseline wr=52.1%):
- Warmog's Armor: wr=59.0% (n=83) - NOT in scorer pool at all
- Fimbulwinter: wr=60.0% (n=30) - NOT in scorer pool at all
- Redemption: wr=62.1% (n=58) - r6 in scorer, OK
- Echoes of Helia: wr=80.0% (n=5, small) - r1 in scorer, OK
- Moonstone Renewer: wr=54.6% (n=108) - r9 in scorer (just outside top-8)

Warmog's (59% wr, n=83) and Fimbulwinter (60% wr, n=30) are high-sample ARAM winners absent from scorer pool. This is a known ARAM HP-stack meta nuance for hps scorers (HP-stack provides EHP + passive sustain that the hps axis does not model). Moonstone Renewer ranks r9 despite 54.6% wr - minor ordering gap. Noted as pool gaps, not wrong-axis. Severity: MINOR.

## Axis 4 - rune_ok: N/A

rune_relevant=false. Not applicable.

## Nominated retune

Add Warmog's Armor and Fimbulwinter to hps scorer item pool with moderate weight to surface ARAM HP-stack synergy. Moonstone Renewer weight lift from r9 to top-5 range. Label: pool-expansion, not axis change.
