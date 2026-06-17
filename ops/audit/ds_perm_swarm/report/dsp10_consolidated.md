# DS Permutation Swarm - Consolidated Mismatch Report (DSP10)

top_k=6 min_item_n=5 worst_n=40
consolidated (anchor-matched, scored) champ-modes: 162

Each row: DS-favored top-K (union across target-preset buckets, with live rewind n/wr) vs the above-baseline empirical winners DS buries. A per-champion fix should lift the buried winners; an empty buried list = DS already favors the winners (the negative lift is thin-sample / cost-axis noise).

## Zilean (ARAM) - hps/enchanter - n=125 base_wr=52.8 mean_lift=-32.8

DS top (rank: item [rewind n/wr]):
  1:Echoes of Helia[0/-], 2:Ardent Censer[0/-], 3:Staff of Flowing Water[0/-], 4:Locket of the Iron Solari[4/25.0], 5:Knight's Vow[0/-], 6:Redemption[5/20.0]

BURIED winners (item n/wr +lift):
  Shadowflame[29/65.5 +12.7], Needlessly Large Rod[23/65.2 +12.4], Refillable Potion[21/61.9 +9.1], Rabadon's Deathcap[34/61.8 +9.0], Luden's Echo[80/57.5 +4.7], Stormsurge[30/56.7 +3.9], Sorcerer's Shoes[64/53.1 +0.3]

## Shaco (ARAM) - burst/assassin - n=124 base_wr=52.4194 mean_lift=-29.2143

DS top (rank: item [rewind n/wr]):
  1:Wooglet's Witchcap[0/-], 2:Trinity Force[0/-], 2:Blade of The Ruined King[1/100.0], 3:Essence Reaver[6/16.6667], 5:Lich Bane[2/50.0], 6:Infinity Edge[13/38.4615], 6:Eclipse[0/-]

BURIED winners (item n/wr +lift):
  Blackfire Torch[43/65.1 +12.6806], Liandry's Torment[77/62.3 +9.8806], Sorcerer's Shoes[60/61.7 +9.2806], Luden's Echo[35/60.0 +7.5806], Shadowflame[46/56.5 +4.0806], Refillable Potion[29/55.2 +2.7806], Malignance[26/53.8 +1.3806]

## Pyke (ARAM) - burst/assassin - n=150 base_wr=52.0 mean_lift=-22.0

DS top (rank: item [rewind n/wr]):
  1:Sundered Sky[0/-], 1:Blade of The Ruined King[0/-], 2:Essence Reaver[0/-], 2:Serylda's Grudge[20/30.0], 4:Trinity Force[0/-], 4:Lord Dominik's Regards[0/-], 5:Infinity Edge[0/-], 6:Umbral Glaive[0/-], 6:Eclipse[1/0.0]

BURIED winners (item n/wr +lift):
  Long Sword[31/67.7 +15.7], Opportunity[31/58.1 +6.1], Youmuu's Ghostblade[45/57.8 +5.8], Axiom Arc[125/53.6 +1.6], Serrated Dirk[44/52.3 +0.3]

## Udyr (ARAM) - hybrid/bruiser - n=56 base_wr=42.8571 mean_lift=-21.6988

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Trinity Force[4/50.0], 2:Liandry's Torment[37/48.6486], 3:Heartsteel[7/14.2857], 4:Dusk and Dawn[0/-], 5:Essence Reaver[0/-], 6:Iceborn Gauntlet[0/-], 6:Blade of The Ruined King[4/25.0]

BURIED winners (item n/wr +lift):
  Spirit Visage[8/62.5 +19.6429], Jak'Sho, The Protean[10/60.0 +17.1429], Sorcerer's Shoes[7/57.1 +14.2429], Plated Steelcaps[7/57.1 +14.2429], Fimbulwinter[22/54.5 +11.6429], Thornmail[11/45.5 +2.6429], Mercury's Treads[30/43.3 +0.4429]

## Nilah (ARAM) - dps/carry - n=83 base_wr=54.2169 mean_lift=-20.8836

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[9/33.3333], 2:Void Immolation[0/-], 3:Trinity Force[0/-], 3:Liandry's Torment[0/-], 4:Essence Reaver[1/100.0], 4:Eclipse[0/-], 5:Kraken Slayer[0/-], 6:Stormrazor[0/-]

BURIED winners (item n/wr +lift):
  Immortal Shieldbow[20/70.0 +15.7831], Lord Dominik's Regards[16/62.5 +8.2831], B. F. Sword[13/61.5 +7.2831], Mercury's Treads[37/59.5 +5.2831], Infinity Edge[54/55.6 +1.3831], Navori Flickerblade[44/54.5 +0.2831]

## Zaahen (SR) - hybrid/bruiser - n=7 base_wr=57.1429 mean_lift=-17.1429

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[0/-], 2:Heartsteel[0/-], 2:Liandry's Torment[0/-], 3:Kraken Slayer[0/-], 3:Eclipse[0/-], 4:Trinity Force[5/40.0], 5:Stormrazor[0/-], 6:Essence Reaver[0/-]

BURIED winners: (none - DS already favors the winning items)

## Kayle (ARAM) - ability/mage - n=143 base_wr=53.8462 mean_lift=-16.3462

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[0/-], 2:Blackfire Torch[0/-], 3:Wooglet's Witchcap[0/-], 4:Rabadon's Deathcap[16/37.5], 4:Void Staff[3/66.6667], 6:Shadowflame[3/33.3333], 6:Cryptbloom[0/-]

BURIED winners (item n/wr +lift):
  Blade of The Ruined King[69/62.3 +8.4538], Terminus[39/59.0 +5.1538], Riftmaker[33/57.6 +3.7538], Wit's End[53/56.6 +2.7538], Berserker's Greaves[116/55.2 +1.3538], Guinsoo's Rageblade[92/54.3 +0.4538]

## TwistedFate (ARAM) - ability/mage - n=147 base_wr=55.7823 mean_lift=-15.8688

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[11/36.3636], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[5/20.0], 4:Rabadon's Deathcap[37/43.2432], 4:Void Staff[11/54.5455], 5:Shadowflame[38/50.0], 6:Cryptbloom[0/-]

BURIED winners (item n/wr +lift):
  Refillable Potion[23/73.9 +18.1177], Needlessly Large Rod[27/70.4 +14.6177], Luden's Echo[102/55.9 +0.1177]

## Seraphine (ARAM) - hps/enchanter - n=136 base_wr=56.6176 mean_lift=-14.9509

DS top (rank: item [rewind n/wr]):
  1:Echoes of Helia[3/66.6667], 2:Ardent Censer[6/50.0], 3:Staff of Flowing Water[12/41.6667], 4:Knight's Vow[0/-], 5:Locket of the Iron Solari[0/-], 6:Redemption[9/33.3333]

BURIED winners (item n/wr +lift):
  Shadowflame[21/61.9 +5.2824], Amplifying Tome[20/60.0 +3.3824], Malignance[71/59.2 +2.5824], Ionian Boots of Lucidity[58/58.6 +1.9824]

## Rakan (ARAM) - hps/enchanter - n=61 base_wr=39.3443 mean_lift=-13.5548

DS top (rank: item [rewind n/wr]):
  1:Echoes of Helia[0/-], 2:Ardent Censer[2/0.0], 3:Staff of Flowing Water[1/0.0], 4:Locket of the Iron Solari[19/31.5789], 5:Knight's Vow[3/33.3333], 6:Redemption[5/20.0]

BURIED winners (item n/wr +lift):
  Guardian's Horn[11/54.5 +15.1557], Warmog's Armor[11/45.5 +6.1557], Mercury's Treads[36/44.4 +5.0557], Heartsteel[20/40.0 +0.6557], Fimbulwinter[33/39.4 +0.0557]

## Katarina (ARAM) - ability/mage - n=152 base_wr=50.6579 mean_lift=-13.0248

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[3/33.3333], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[0/-], 4:Rabadon's Deathcap[35/37.1429], 4:Void Staff[13/38.4615], 5:Cryptbloom[1/0.0], 6:Shadowflame[46/36.9565]

BURIED winners (item n/wr +lift):
  Titanic Hydra[62/62.9 +12.2421], Heartsteel[71/60.6 +9.9421], Mercury's Treads[38/55.3 +4.6421], Blade of The Ruined King[69/53.6 +2.9421], Nashor's Tooth[29/51.7 +1.0421]

## Briar (ARAM) - hybrid/bruiser - n=38 base_wr=52.6316 mean_lift=-11.6594

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Blade of The Ruined King[8/37.5], 3:Trinity Force[0/-], 4:Heartsteel[9/44.4444], 4:Liandry's Torment[0/-], 5:Essence Reaver[0/-], 6:Runaan's Hurricane[0/-]

BURIED winners (item n/wr +lift):
  Ruby Crystal[5/80.0 +27.3684], Sterak's Gage[11/63.6 +10.9684], Sundered Sky[31/54.8 +2.1684], Mercury's Treads[26/53.8 +1.1684], Death's Dance[17/52.9 +0.2684]

## Caitlyn (ARAM) - dps/carry - n=262 base_wr=50.3817 mean_lift=-10.9272

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[11/36.3636], 2:Runaan's Hurricane[3/33.3333], 2:Void Immolation[0/-], 4:Essence Reaver[0/-], 4:Eclipse[0/-], 5:Kraken Slayer[15/46.6667], 6:Stormrazor[0/-], 6:Liandry's Torment[0/-]

BURIED winners (item n/wr +lift):
  Lord Dominik's Regards[80/53.8 +3.4183], B. F. Sword[32/53.1 +2.7183], The Collector[164/51.2 +0.8183], Rapid Firecannon[131/50.4 +0.0183]

## Yasuo (ARAM) - hybrid/bruiser - n=143 base_wr=41.958 mean_lift=-10.5172

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Blade of The Ruined King[91/40.6593], 3:Trinity Force[0/-], 4:Heartsteel[9/22.2222], 4:Liandry's Torment[0/-], 5:Essence Reaver[0/-], 6:Runaan's Hurricane[0/-]

BURIED winners (item n/wr +lift):
  Jak'Sho, The Protean[20/65.0 +23.042], Wit's End[20/55.0 +13.042], Statikk Shiv[19/52.6 +10.642], Pickaxe[18/50.0 +8.042]

## Anivia (ARAM) - ability/mage - n=147 base_wr=55.102 mean_lift=-9.6493

DS top (rank: item [rewind n/wr]):
  1:Wooglet's Witchcap[0/-], 1:Liandry's Torment[101/55.4455], 3:Blackfire Torch[10/40.0], 4:Rabadon's Deathcap[30/63.3333], 4:Void Staff[6/33.3333], 5:Cryptbloom[6/33.3333], 6:Shadowflame[22/36.3636]

BURIED winners (item n/wr +lift):
  Refillable Potion[25/64.0 +8.898], Rod of Ages[104/60.6 +5.498], Seraph's Embrace[113/56.6 +1.498], Sorcerer's Shoes[114/55.3 +0.198]

## Gnar (ARAM) - hybrid/bruiser - n=69 base_wr=56.5217 mean_lift=-9.6328

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Blade of The Ruined King[4/75.0], 3:Trinity Force[45/57.7778], 4:Heartsteel[25/36.0], 4:Liandry's Torment[0/-], 5:Essence Reaver[0/-], 6:Iceborn Gauntlet[1/100.0], 6:Runaan's Hurricane[0/-]

BURIED winners (item n/wr +lift):
  Randuin's Omen[12/75.0 +18.4783], Black Cleaver[23/65.2 +8.6783], Ruby Crystal[13/61.5 +4.9783], Thornmail[13/61.5 +4.9783], Sterak's Gage[17/58.8 +2.2783], Plated Steelcaps[24/58.3 +1.7783], Mercury's Treads[43/58.1 +1.5783]

## Tryndamere (ARAM) - hybrid/bruiser - n=55 base_wr=49.0909 mean_lift=-9.4481

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 1:Blade of The Ruined King[28/39.2857], 3:Runaan's Hurricane[0/-], 4:Trinity Force[0/-], 5:Kraken Slayer[5/40.0], 5:Eclipse[0/-], 6:Essence Reaver[0/-]

BURIED winners (item n/wr +lift):
  Vampiric Scepter[6/83.3 +34.2091], Titanic Hydra[11/63.6 +14.5091], Berserker's Greaves[18/61.1 +12.0091], Navori Flickerblade[17/58.8 +9.7091], Mercury's Treads[26/53.8 +4.7091], Infinity Edge[16/50.0 +0.9091], Phantom Dancer[10/50.0 +0.9091]

## RekSai (ARAM) - hybrid/bruiser - n=29 base_wr=48.2759 mean_lift=-9.4188

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Blade of The Ruined King[0/-], 3:Trinity Force[0/-], 4:Heartsteel[14/28.5714], 4:Liandry's Torment[1/0.0], 5:Runaan's Hurricane[0/-], 5:Eclipse[5/80.0], 6:Essence Reaver[0/-]

BURIED winners (item n/wr +lift):
  Sundered Sky[13/61.5 +13.2241], Mercury's Treads[18/55.6 +7.3241], Spirit Visage[10/50.0 +1.7241]

## Senna (ARAM) - dps/carry - n=207 base_wr=51.6908 mean_lift=-9.4097

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[34/41.1765], 2:Void Immolation[0/-], 3:Kraken Slayer[25/44.0], 3:Eclipse[12/41.6667], 4:Stormrazor[0/-], 4:Liandry's Torment[1/100.0], 5:Essence Reaver[4/75.0]

BURIED winners (item n/wr +lift):
  Black Cleaver[38/63.2 +11.5092], Berserker's Greaves[61/54.1 +2.4092], Muramana[92/53.3 +1.6092]

## Rell (ARAM) - ehp/tank - n=53 base_wr=39.6226 mean_lift=-8.9635

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Randuin's Omen[1/100.0], 2:Warmog's Armor[13/23.0769], 2:Kaenic Rookern[12/25.0], 3:Jak'Sho, The Protean[14/21.4286], 3:Force of Nature[4/75.0], 4:Unending Despair[20/40.0], 4:Spirit Visage[1/100.0], 5:Dead Man's Plate[0/-], 5:Heartsteel[27/51.8519]

BURIED winners (item n/wr +lift):
  Giant's Belt[9/66.7 +27.0774], Fimbulwinter[22/40.9 +1.2774]

## Vex (ARAM) - ability/mage - n=105 base_wr=41.9048 mean_lift=-8.422

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[14/35.7143], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[9/33.3333], 4:Rabadon's Deathcap[39/38.4615], 4:Void Staff[14/28.5714], 5:Cryptbloom[5/20.0], 6:Shadowflame[72/38.8889]

BURIED winners (item n/wr +lift):
  Refillable Potion[20/45.0 +3.0952]

## Quinn (ARAM) - dps/carry - n=174 base_wr=49.4253 mean_lift=-8.0372

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[31/38.7097], 2:Runaan's Hurricane[5/40.0], 2:Void Immolation[0/-], 3:Kraken Slayer[22/45.4545], 3:Eclipse[0/-], 5:Essence Reaver[0/-], 6:Stormrazor[0/-]

BURIED winners (item n/wr +lift):
  Cloak of Agility[27/63.0 +13.5747], Long Sword[24/62.5 +13.0747], Lord Dominik's Regards[38/57.9 +8.4747], Infinity Edge[102/55.9 +6.4747], Statikk Shiv[68/54.4 +4.9747], The Collector[130/50.0 +0.5747], Mortal Reminder[24/50.0 +0.5747]

## Yunara (ARAM) - dps/carry - n=17 base_wr=52.9412 mean_lift=-6.9412

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[5/40.0], 2:Void Immolation[0/-], 3:Kraken Slayer[4/75.0], 3:Liandry's Torment[0/-], 4:Stormrazor[0/-], 5:Essence Reaver[0/-], 5:Eclipse[0/-], 6:Yun Tal Wildarrows[10/60.0]

BURIED winners (item n/wr +lift):
  Infinity Edge[12/75.0 +22.0588], Runaan's Hurricane[13/61.5 +8.5588], Berserker's Greaves[10/60.0 +7.0588]

## Darius (ARAM) - hybrid/bruiser - n=135 base_wr=56.2963 mean_lift=-6.7311

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Blade of The Ruined King[0/-], 3:Trinity Force[46/56.5217], 4:Runaan's Hurricane[0/-], 5:Essence Reaver[0/-], 6:Heartsteel[9/33.3333], 6:Liandry's Torment[0/-]

BURIED winners (item n/wr +lift):
  Force of Nature[24/75.0 +18.7037], Sterak's Gage[48/70.8 +14.5037], Death's Dance[37/64.9 +8.6037], Plated Steelcaps[37/59.5 +3.2037], Stridebreaker[47/57.4 +1.1037]

## Xerath (ARAM) - ability/mage - n=169 base_wr=48.5207 mean_lift=-6.6022

DS top (rank: item [rewind n/wr]):
  1:Wooglet's Witchcap[0/-], 2:Liandry's Torment[46/45.6522], 3:Blackfire Torch[22/36.3636], 3:Void Staff[35/42.8571], 4:Rabadon's Deathcap[51/41.1765], 6:Shadowflame[75/44.0], 6:Cryptbloom[7/42.8571]

BURIED winners (item n/wr +lift):
  Refillable Potion[46/60.9 +12.3793], Needlessly Large Rod[48/58.3 +9.7793], Luden's Echo[128/50.8 +2.2793]

## KSante (ARAM) - ehp/tank - n=57 base_wr=45.614 mean_lift=-6.5558

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Randuin's Omen[3/33.3333], 2:Warmog's Armor[7/14.2857], 2:Kaenic Rookern[10/50.0], 3:Jak'Sho, The Protean[23/56.5217], 3:Force of Nature[6/33.3333], 4:Unending Despair[19/57.8947], 4:Spirit Visage[6/66.6667], 5:Dead Man's Plate[0/-], 5:Heartsteel[16/31.25]

BURIED winners (item n/wr +lift):
  Thornmail[14/57.1 +11.486], Negatron Cloak[11/54.5 +8.886], Plated Steelcaps[12/50.0 +4.386], Iceborn Gauntlet[40/47.5 +1.886]

## Corki (ARAM) - dps/carry - n=130 base_wr=43.8462 mean_lift=-6.3462

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[3/33.3333], 2:Kraken Slayer[1/0.0], 2:Void Immolation[0/-], 3:Runaan's Hurricane[2/50.0], 3:Eclipse[8/37.5], 5:Stormrazor[0/-], 6:Essence Reaver[2/50.0]

BURIED winners (item n/wr +lift):
  Bloodthirster[21/52.4 +8.5538], Long Sword[16/50.0 +6.1538], The Collector[62/46.8 +2.9538], Trinity Force[80/46.2 +2.3538], Muramana[99/45.5 +1.6538]

## Heimerdinger (ARAM) - ability/mage - n=122 base_wr=44.2623 mean_lift=-6.3315

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[107/42.9907], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[76/46.0526], 4:Rabadon's Deathcap[24/41.6667], 4:Void Staff[9/22.2222], 5:Shadowflame[14/35.7143], 6:Cryptbloom[2/50.0]

BURIED winners (item n/wr +lift):
  Zhonya's Hourglass[21/47.6 +3.3377], Refillable Potion[19/47.4 +3.1377], Sorcerer's Shoes[96/46.9 +2.6377], Malignance[26/46.2 +1.9377], Rylai's Crystal Scepter[74/44.6 +0.3377], Needlessly Large Rod[27/44.4 +0.1377]

## Lillia (ARAM) - ability/mage - n=100 base_wr=41.0 mean_lift=-6.2273

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[88/44.3182], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[55/41.8182], 4:Rabadon's Deathcap[11/18.1818], 4:Void Staff[3/100.0], 5:Shadowflame[2/50.0], 6:Cryptbloom[0/-]

BURIED winners (item n/wr +lift):
  Sorcerer's Shoes[55/47.3 +6.3], Fiendish Codex[13/46.2 +5.2], Ionian Boots of Lucidity[18/44.4 +3.4], Cosmic Drive[34/44.1 +3.1]

## Malzahar (ARAM) - ability/mage - n=172 base_wr=52.3256 mean_lift=-6.0522

DS top (rank: item [rewind n/wr]):
  1:Wooglet's Witchcap[0/-], 1:Liandry's Torment[155/52.9032], 3:Blackfire Torch[113/53.0973], 4:Rabadon's Deathcap[30/36.6667], 4:Void Staff[16/37.5], 5:Shadowflame[50/52.0], 6:Cryptbloom[6/50.0]

BURIED winners (item n/wr +lift):
  Sorcerer's Shoes[140/53.6 +1.2744], Rylai's Crystal Scepter[88/53.4 +1.0744]

## Ekko (ARAM) - ability/mage - n=125 base_wr=44.8 mean_lift=-5.9968

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[1/0.0], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[0/-], 4:Rabadon's Deathcap[37/54.0541], 4:Void Staff[9/22.2222], 5:Shadowflame[41/41.4634], 6:Cryptbloom[0/-]

BURIED winners (item n/wr +lift):
  Hextech Rocketbelt[50/54.0 +9.2], Stormsurge[41/53.7 +8.9], Lich Bane[86/50.0 +5.2], Needlessly Large Rod[26/50.0 +5.2], Sorcerer's Shoes[79/48.1 +3.3], Zhonya's Hourglass[26/46.2 +1.4], Mercury's Treads[20/45.0 +0.2]

## Zoe (ARAM) - ability/mage - n=161 base_wr=42.8571 mean_lift=-5.8108

DS top (rank: item [rewind n/wr]):
  1:Wooglet's Witchcap[0/-], 2:Liandry's Torment[2/0.0], 3:Rabadon's Deathcap[59/47.4576], 3:Void Staff[29/31.0345], 4:Blackfire Torch[8/25.0], 5:Shadowflame[86/44.186], 6:Cryptbloom[11/45.4545]

BURIED winners (item n/wr +lift):
  Luden's Echo[143/44.8 +1.9429], Stormsurge[73/43.8 +0.9429], Needlessly Large Rod[35/42.9 +0.0429], Refillable Potion[28/42.9 +0.0429]

## Fizz (ARAM) - ability/mage - n=107 base_wr=46.729 mean_lift=-5.7428

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[3/66.6667], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[0/-], 4:Rabadon's Deathcap[19/42.1053], 4:Void Staff[9/33.3333], 5:Shadowflame[37/54.0541], 6:Cryptbloom[1/0.0]

BURIED winners (item n/wr +lift):
  Luden's Echo[36/58.3 +11.571], Needlessly Large Rod[24/58.3 +11.571], Sorcerer's Shoes[53/47.2 +0.471], Lich Bane[62/46.8 +0.071]

## MasterYi (ARAM) - hybrid/bruiser - n=105 base_wr=55.2381 mean_lift=-5.7188

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 1:Blade of The Ruined King[71/56.338], 3:Runaan's Hurricane[0/-], 4:Trinity Force[1/0.0], 4:Eclipse[1/100.0], 5:Kraken Slayer[18/38.8889], 6:Heartsteel[7/57.1429]

BURIED winners (item n/wr +lift):
  Infinity Edge[20/65.0 +9.7619], Guinsoo's Rageblade[30/63.3 +8.0619], Berserker's Greaves[72/55.6 +0.3619]

## KogMaw (ARAM) - ability/mage - n=148 base_wr=42.5676 mean_lift=-5.6747

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[35/37.1429], 2:Wooglet's Witchcap[0/-], 3:Blackfire Torch[5/20.0], 4:Rabadon's Deathcap[8/62.5], 4:Void Staff[7/28.5714], 5:Shadowflame[14/35.7143], 6:Cryptbloom[0/-]

BURIED winners (item n/wr +lift):
  Terminus[33/51.5 +8.9324], Wit's End[35/51.4 +8.8324], Berserker's Greaves[91/46.2 +3.6324], Blade of The Ruined King[86/44.2 +1.6324], Runaan's Hurricane[56/42.9 +0.3324], Seraph's Embrace[35/42.9 +0.3324]

## Urgot (ARAM) - hybrid/bruiser - n=74 base_wr=45.9459 mean_lift=-5.2052

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 2:Blade of The Ruined King[0/-], 3:Trinity Force[0/-], 4:Heartsteel[54/40.7407], 4:Liandry's Torment[0/-], 5:Essence Reaver[0/-], 6:Runaan's Hurricane[0/-]

BURIED winners (item n/wr +lift):
  Jak'Sho, The Protean[11/63.6 +17.6541], Overlord's Bloodmail[10/50.0 +4.0541], Titanic Hydra[49/49.0 +3.0541], Black Cleaver[27/48.1 +2.1541], Mercury's Treads[48/47.9 +1.9541], Thornmail[21/47.6 +1.6541]

## Elise (ARAM) - ability/mage - n=57 base_wr=57.8947 mean_lift=-4.9559

DS top (rank: item [rewind n/wr]):
  1:Liandry's Torment[26/50.0], 2:Blackfire Torch[8/62.5], 3:Wooglet's Witchcap[0/-], 4:Void Staff[10/40.0], 5:Shadowflame[29/62.069], 5:Cryptbloom[4/50.0], 6:Rabadon's Deathcap[21/57.1429], 6:Bloodletter's Curse[0/-]

BURIED winners (item n/wr +lift):
  Sorcerer's Shoes[48/58.3 +0.4053]

## JarvanIV (ARAM) - hybrid/bruiser - n=127 base_wr=38.5827 mean_lift=-4.6844

DS top (rank: item [rewind n/wr]):
  1:Void Immolation[0/-], 1:Blade of The Ruined King[2/0.0], 3:Trinity Force[0/-], 4:Runaan's Hurricane[0/-], 5:Kraken Slayer[0/-], 5:Eclipse[59/33.8983], 6:Essence Reaver[0/-], 6:Liandry's Torment[0/-]

BURIED winners (item n/wr +lift):
  Caulfield's Warhammer[16/50.0 +11.4173], Sundered Sky[80/42.5 +3.9173], Sterak's Gage[31/41.9 +3.3173], Mercury's Treads[68/41.2 +2.6173], Death's Dance[42/40.5 +1.9173], Spear of Shojin[20/40.0 +1.4173]

## Evelynn (ARAM) - ability/mage - n=36 base_wr=52.7778 mean_lift=-4.5238

DS top (rank: item [rewind n/wr]):
  1:Wooglet's Witchcap[0/-], 2:Liandry's Torment[0/-], 3:Rabadon's Deathcap[16/50.0], 3:Void Staff[7/42.8571], 4:Blackfire Torch[0/-], 5:Shadowflame[18/55.5556], 6:Cryptbloom[0/-]

BURIED winners (item n/wr +lift):
  Tear of the Goddess[7/71.4 +18.6222], Luden's Echo[8/62.5 +9.7222], Stormsurge[17/58.8 +6.0222], Lich Bane[14/57.1 +4.3222]

## Naafiri (ARAM) - burst/assassin - n=54 base_wr=42.5926 mean_lift=-4.4845

DS top (rank: item [rewind n/wr]):
  1:Blade of The Ruined King[0/-], 2:Infinity Edge[0/-], 2:Eclipse[37/35.1351], 3:Umbral Glaive[0/-], 3:Serylda's Grudge[20/50.0], 4:Essence Reaver[0/-], 4:Lord Dominik's Regards[0/-], 6:Bloodthirster[0/-], 6:Mortal Reminder[0/-]

BURIED winners (item n/wr +lift):
  Long Sword[10/50.0 +7.4074], The Collector[24/45.8 +3.2074], Hubris[28/42.9 +0.3074]
