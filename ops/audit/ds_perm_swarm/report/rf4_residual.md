# RF4 Residual Re-run - Loop-Until-Dry Verification

loop-until-dry: SATISFIED (0 new survivability cluster(s), 1 pass)
RF1-RF3 tabled champs resolved: 11/12 - residual: Rell
worst-N rows classified: 40

## RF1-RF3 seam-ON resolution (in-process re-rank, OFF vs ON)

- [rf1] Briar (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3084', '3508', '3085', '6672'] -> ON['6610', '3053', '6333', '223069', '3078', '3084']; floated=['6610', '3053', '6333']
- [rf1] Darius (hybrid/ARAM) RESOLVED: OFF['3078', '223069', '3085', '3508', '3084', '3097'] -> ON['3053', '6333', '6631', '4401', '3078', '223069']; floated=['3053', '6333', '6631', '4401']
- [rf1] Gnar (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3084', '3508', '3085', '3097'] -> ON['3053', '3071', '3143', '3075', '223069', '3078']; floated=['3053', '3071', '3143', '3075']
- [rf1] JarvanIV (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3085', '6672', '3508', '3084'] -> ON['6610', '6333', '3053', '223069', '3078', '3085']; floated=['6610', '6333', '3053']
- [rf1] RekSai (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3084', '3085', '3508', '6672'] -> ON['6610', '3065', '223069', '3078', '3084', '3085']; floated=['6610', '3065']
- [rf1] Tryndamere (hybrid/ARAM) RESOLVED: OFF['223069', '3085', '3078', '6672', '3508', '3084'] -> ON['3748', '223069', '3085', '3078', '6672', '3508']; floated=['3748']
- [rf1] Udyr (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3084', '3508', '2510', '6662'] -> ON['6665', '3065', '3075', '223069', '3078', '3084']; floated=['6665', '3065', '3075']
- [rf1] Urgot (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3084', '3508', '3085', '6662'] -> ON['3748', '2501', '3071', '6665', '3075', '223069']; floated=['3748', '2501', '3071', '6665', '3075']
- [rf1] Yasuo (hybrid/ARAM) RESOLVED: OFF['223069', '3078', '3084', '3508', '3085', '3097'] -> ON['3091', '6665', '223069', '3078', '3084', '3508']; floated=['3091', '6665']
- [rf2] Rakan (hps/ARAM) RESOLVED: OFF['6620', '3504', '6616', '3190', '3109', '3107'] -> ON['2051', '3083', '3084', '6620', '3504', '6616']; floated=['2051', '3083', '3084']
- [rf3] KSante (ehp/ARAM) RESOLVED: OFF['223069', '3083', '6665', '2504', '3084', '3143'] -> ON['6662', '3075', '223069', '3083', '6665', '2504']; floated=['6662', '3075']
- [rf3] Rell (ehp/ARAM) NOT-RESOLVED: OFF['223069', '3083', '6665', '2504', '3084', '3143'] -> ON['223069', '3083', '6665', '2504', '3084', '3143']; injected=[]

## Worst-N classification

- ability_mage_lane (14): Anivia, Ekko, Elise, Evelynn, Fizz, Heimerdinger, Katarina, KogMaw, Lillia, Malzahar, TwistedFate, Vex, Xerath, Zoe
- cluster_a_deferred (4): Kayle, Seraphine, Shaco, Zilean
- covered_dsp11 (6): Corki, Naafiri, Nilah, Pyke, Quinn, Senna
- covered_rf1 (9): Briar, Darius, Gnar, JarvanIV, RekSai, Tryndamere, Udyr, Urgot, Yasuo
- covered_rf2 (1): Rakan
- covered_rf3 (2): KSante, Rell
- dps_burst_lane (2): Caitlyn, Yunara
- no_buried (1): Zaahen
- thin_or_noise (1): MasterYi

## Resolution residuals (existing RF table, float-seam no-op - QUEUED)
- [rf3] Rell (ehp): tabled ['3121'] NOT pooled by the scorer -> the float-only seam cannot surface it (needs an INJECT mode, RF2's shape). NOT a new cluster; queued (RF6).

## NEW survivability clusters: NONE - the swarm is DRY. The remaining divergent tail is Cluster A (operator-gated AP-in-ARAM), the dps/burst lane (DSP2/DSP11, its own closed loop), the ability/mage lane (deferred DSV1 AP-DoT valuation), no-buried, and thin-sample / cost-axis noise. RF4 loop-until-dry satisfied (1 no-new-cluster pass).
