# DS Cross-Eval: Rakan

**Verdict: MINOR**
Scorer: hps | Archetype: enchanter/mage | Anchor: ARAM | Evidence: outcome_all (n=61 ARAM, n=35 SR)

---

## Axis 1 - archetype_ok: TRUE

Primary=enchanter, secondary=mage. hps scorer is the correct AP-axis scorer for enchanters.
Rakan kit (W heal, E shield/charm) maps cleanly to hps. No axis mismatch.

ARAM empirical note: above-baseline items (Mercury's Treads 44.4%, Warmog's Armor 45.5%,
Guardian's Horn 54.5%) are tank/HP items, not enchanter items. This reflects Rakan's ARAM
playstyle diverging from enchanter archetype - but the archetype assignment itself is correct.

---

## Axis 2 - comp_ok: TRUE

Scorer = hps/enchanter. comp_invariance is EXPECTED for enchanters. comp_blind=true across
all 5 cells (identical rankings, all d_ehp=0.0, all d_dps=0.0). This is correct behavior.
No defect.

---

## Axis 3 - outcome_ok: FALSE (pool gap)

ARAM baseline wr = 39.3% (outcome_all, n=61).

Above-baseline empirical ARAM items:
- Guardian's Horn (id 2051): n=11, wr=54.5% -- absent from scorer pool
- Warmog's Armor (id 3083): n=11, wr=45.5% -- absent from scorer pool
- Mercury's Treads (id 3111): n=36, wr=44.4% -- absent from scorer pool
- Heartsteel (id 3084): n=20, wr=40.0% -- absent from scorer pool

Scorer top-8: Echoes of Helia (#1), Ardent Censer (#2), Staff of Flowing Water (#3),
Locket (#4), Knight's Vow (#5), Redemption (#6), Imperial Mandate (#7), Mikael's (#8).

Overlap with above-baseline ARAM items: ZERO.

Locket (scorer rank 4) does appear in ARAM empirical but at wr=31.6% -- BELOW baseline.
That is a losing item in this dataset.

SR baseline wr = 57.1% (outcome_all, n=35). Above-baseline SR:
- Solstice Sleigh (id 3876): n=9, wr=77.8% -- absent from scorer pool
- Knight's Vow (id 3109): n=7, wr=85.7% -- scorer rank 5 (MATCH)
- Kindlegem (id 3067): n=12, wr=58.3% -- absent from scorer pool
- Ionian Boots (id 3158): n=18, wr=66.7% -- absent from scorer pool
- Locket (id 3190): n=21, wr=61.9% -- scorer rank 4 (MATCH)

SR is partially aligned (2 scorer items in above-baseline set). ARAM is the anchor mode and
shows zero overlap.

Pool gap: hps scorer recommends classic enchanter items (Echoes, Ardent, Staff) that do not
appear in empirical ARAM winners. Rakan plays as a tanky initiator in ARAM, not a traditional
enchanter, and the tank/HP items that win are invisible to the hps scorer pool.

---

## Axis 4 - rune_ok: N/A

rune_relevant=false. No rune judgment possible.

---

## Nominated Retune

Consider adding a tank/HP item path to Rakan's scorer pool as a secondary signal, or flagging
Rakan as a tank-divergent enchanter (similar to a secondary archetype weighting). Specifically:
Guardian's Horn (2051), Warmog's Armor (3083), Fimbulwinter (3121, wr=39.4% near baseline)
are high-frequency ARAM items the scorer currently ignores. A blended enchanter+tank pool
or a playstyle-branch for Rakan ARAM would reduce the gap.

Nominated retune: add Guardian's Horn + Warmog's Armor to Rakan hps scorer ARAM item pool;
investigate whether Rakan ARAM warrants a secondary tank-archetype branch.
