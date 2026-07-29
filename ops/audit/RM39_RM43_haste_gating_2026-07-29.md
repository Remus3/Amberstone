# RM-39/RM-43 ability-HASTE reachability - Aatrox/Ambessa

Date: 2026-07-29. READ-ONLY empirical, no engine edit, no commit.
DS patch: 16.14.1.

## Mechanism (file:line)

- rank_for_primary_archetype (core/daemon_slayer_client.py:2072) does NOT expose apply_ad_axis_ability_damage; its bruiser branch (:2252 rank_bruiser_for) never forwards it. The client is an HTTP wrapper to :8893, so compute_ability_dps is server-side and unpatchable from a probe process.
- Driven instead through the in-process scorer agents.daemon_slayer.hybrid.rank_items_by_hybrid (hybrid.py:970; flag param hybrid.py:1013) - the SAME function the server's _route_rank_bruiser calls (server.py:1117), with the SAME body the probe uses (tanky target probe_champion.py:44, item_ids=[], level=13, mode=SR, top=40).
- Amplify (B/D): wrap hybrid.compute_ability_dps (the live binding from hybrid.py:43 `from .ability_dps import compute_ability_dps`) - x1e6 every per_spell.dps and total_ability_dps. per_spell.dps is what _physical_ability_damage sums (hybrid.py:248-252).
- Haste-narrow (E): replace ability_dps._effective_ability_cd (ability_dps.py:530, applied at :1218-1220) with base_cd/1e6 so theoretical=1/cooldown (ability_dps.py:1289) would explode IF the measured<=0 branch (ability_dps.py:1288) is entered.

Enemy comp held constant across all cells: enemy_ad_share=0.85, enemy_ap_share=0.10.

## Verdicts

### Aatrox (ranked pool n=40)
- A vs C (flag OFF vs ON, no amp): CHANGED: 6662: #6->#5; 3742: #8->#6; 2510: #5->#7; 6692: #7->#8; 6610: #10->#9; 3097: #9->#10; 3143: #27->#11; 6673: #16->#12
- B vs A (flag OFF, compute x1e6): IDENTICAL (byte-exact ranked item_id+score list)
- D vs C (flag ON, compute x1e6): CHANGED: 3143: #11->#1; 3071: #15->#2; 3072: #19->#3; 3053: #24->#4; 6694: #25->#5; 663058: NEW->#6; 6673: #12->#7; 6333: #26->#8
- E vs C (flag ON, haste cooldown->0): IDENTICAL (byte-exact ranked item_id+score list)

### Ambessa (ranked pool n=40)
- A vs C (flag OFF vs ON, no amp): CHANGED: 6673: #11->#6; 3302: #9->#7; 3181: #10->#8; 3031: #6->#9; 6653: #7->#10; 3036: #12->#11; 3097: #8->#12; 3143: #27->#13
- B vs A (flag OFF, compute x1e6): IDENTICAL (byte-exact ranked item_id+score list)
- D vs C (flag ON, compute x1e6): CHANGED: 3143: #13->#1; 3071: #15->#2; 663058: NEW->#3; 3083: NEW->#4; 2502: NEW->#5; 3742: #19->#6; 3084: NEW->#7; 3110: NEW->#8
- E vs C (flag ON, haste cooldown->0): IDENTICAL (byte-exact ranked item_id+score list)

## CONCLUSION
- Aatrox: (a) default config - ability term unreachable (rank_for_primary_archetype cannot toggle the flag). (b) apply_ad_axis_ability_damage ON - first-order ability path REACHABLE (D vs C); ability-HASTE specifically unreachable (E vs C).
- Ambessa: (a) default config - ability term unreachable (rank_for_primary_archetype cannot toggle the flag). (b) apply_ad_axis_ability_damage ON - first-order ability path REACHABLE (D vs C); ability-HASTE specifically unreachable (E vs C).
