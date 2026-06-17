# DSP10 Pass 2 - Loop-Until-Dry Verification

verdict: DRY (0 new B2 defect(s))
tabled champs resolved: 7/7
worst-N rows classified: 40

## DSP11 seam-ON resolution (in-process re-rank, OFF vs ON)

- Corki (dps/ARAM) RESOLVED: OFF['6672', '3085', '3097', '3508', '3031', '3032'] -> ON['3078', '6676', '6672', '3085', '3097', '3508']; floated=['3078', '6676']
- Ezreal (dps/ARAM) RESOLVED: OFF['3085', '6672', '3508', '3097', '3031', '3032'] -> ON['3508', '3078', '3085', '6672', '3097', '3031']; floated=['3078']
- Naafiri (burst/ARAM) RESOLVED: OFF['3031', '3508', '3072', '6610', '6672', '3078'] -> ON['6676', '126697', '3031', '3508', '3072', '6610']; floated=['6676', '126697']
- Nilah (dps/ARAM) RESOLVED: OFF['3078', '3508', '6672', '3097', '3084', '3085'] -> ON['3031', '6675', '6673', '3036', '3078', '3508']; floated=['3031', '6675', '6673', '3036']
- Pyke (burst/ARAM) RESOLVED: OFF['6610', '3508', '3078', '3031', '3072', '6672'] -> ON['6696', '3142', '6610', '3508', '3078', '3031']; floated=['6696', '3142']
- Quinn (dps/ARAM) RESOLVED: OFF['3085', '6672', '3508', '3097', '3031', '3032'] -> ON['3031', '3087', '6676', '3033', '3036', '3085']; floated=['3087', '6676', '3033', '3036']
- Senna (dps/ARAM) RESOLVED: OFF['6672', '3097', '3508', '3031', '223069', '6699'] -> ON['3071', '6672', '3097', '3508', '3031', '223069']; floated=['3071']

## Worst-N classification

- cluster_a_deferred (5): Kayle, Seraphine, Shaco, Udyr, Zilean
- covered_dsp11 (6): Corki, Naafiri, Nilah, Pyke, Quinn, Senna
- no_buried (1): Zaahen
- other_scorer (26): Anivia, Briar, Darius, Ekko, Elise, Evelynn, Fizz, Gnar, Heimerdinger, JarvanIV, KSante, Katarina, KogMaw, Lillia, Malzahar, MasterYi, Rakan, RekSai, Rell, Tryndamere, TwistedFate, Urgot, Vex, Xerath, Yasuo, Zoe
- within_axis_noise (2): Caitlyn, Yunara

## NEW B2 defects: NONE - the swarm is DRY. The only divergent tail is Cluster A (operator-gated), other-scorer AP/bruiser lanes, no-buried, and within-axis cost noise. DSP10 loop-until-dry satisfied.
