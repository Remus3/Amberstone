# Live-Flip Eyeball - DS seam OFF vs ON (top-6 re-rank diff)

Read-only in-process re-rank; the live :8893 stays seam-OFF. For each
champ + seam, ON should be SANER not RANDOM (charter 4b). A seam with no
move for a champ is a no-op there (expected for non-tabled champs).

champs: 20 | level 13 | top-6

## Briar (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Rabadon's Deathcap, Lich Bane, Hextech Gunblade, Essence Reaver, Trinity Force
    ON : Wooglet's Witchcap, Rabadon's Deathcap, Lich Bane, Shadowflame, Hextech Gunblade, Void Staff
    +in : Shadowflame, Void Staff
    -out: Essence Reaver, Trinity Force
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Rabadon's Deathcap, Lich Bane, Hextech Gunblade, Essence Reaver, Trinity Force
    ON : Wooglet's Witchcap, Rabadon's Deathcap, Lich Bane, Hextech Gunblade, Shadowflame, Banshee's Veil
    +in : Shadowflame, Banshee's Veil
    -out: Essence Reaver, Trinity Force
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Heartsteel, Essence Reaver, Runaan's Hurricane, Kraken Slayer
    ON : Sundered Sky, Sterak's Gage, Death's Dance, Void Immolation, Trinity Force, Heartsteel
    +in : Sundered Sky, Sterak's Gage, Death's Dance
    -out: Essence Reaver, Runaan's Hurricane, Kraken Slayer

## Corki (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Trinity Force, The Collector, Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster
    +in : The Collector
    -out: Endless Hunger
- **DSP11_kit_axis_dps**
    OFF: Kraken Slayer, Runaan's Hurricane, Stormrazor, Essence Reaver, Infinity Edge, Yun Tal Wildarrows
    ON : Trinity Force, The Collector, Kraken Slayer, Runaan's Hurricane, Stormrazor, Essence Reaver
    +in : Trinity Force, The Collector
    -out: Infinity Edge, Yun Tal Wildarrows
- **DSP2_exempt_offclass**
    OFF: Kraken Slayer, Runaan's Hurricane, Stormrazor, Essence Reaver, Infinity Edge, Yun Tal Wildarrows
    ON : Kraken Slayer, Runaan's Hurricane, Stormrazor, Essence Reaver, Trinity Force, Infinity Edge
    +in : Trinity Force
    -out: Yun Tal Wildarrows
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Wooglet's Witchcap, Infinity Edge, Bloodthirster, Essence Reaver, Umbral Glaive, Hextech Gunblade
    +in : Umbral Glaive, Hextech Gunblade
    -out: Trinity Force, Endless Hunger
- **DSV2_assume_takedown**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Hubris, Trinity Force
    +in : Hubris
    -out: Endless Hunger
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Wooglet's Witchcap, Infinity Edge, Bloodthirster, Essence Reaver, Hextech Gunblade, Lich Bane
    +in : Hextech Gunblade, Lich Bane
    -out: Trinity Force, Endless Hunger

## Darius (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Sundered Sky, Umbral Glaive
    +in : Umbral Glaive
    -out: Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Sundered Sky, Umbral Glaive
    +in : Umbral Glaive
    -out: Kraken Slayer
- **RF1_survivability_hybrid**
    OFF: Trinity Force, Void Immolation, Runaan's Hurricane, Essence Reaver, Heartsteel, Stormrazor
    ON : Sterak's Gage, Death's Dance, Stridebreaker, Force of Nature, Trinity Force, Void Immolation
    +in : Sterak's Gage, Death's Dance, Stridebreaker, Force of Nature
    -out: Runaan's Hurricane, Essence Reaver, Heartsteel, Stormrazor

## Ezreal (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Wooglet's Witchcap, Essence Reaver, Trinity Force, Infinity Edge, Lich Bane, Rabadon's Deathcap
    ON : Essence Reaver, Trinity Force, Wooglet's Witchcap, Infinity Edge, Lich Bane, Rabadon's Deathcap
- **DSP11_kit_axis_dps**
    OFF: Runaan's Hurricane, Kraken Slayer, Essence Reaver, Stormrazor, Infinity Edge, Yun Tal Wildarrows
    ON : Essence Reaver, Trinity Force, Runaan's Hurricane, Kraken Slayer, Stormrazor, Infinity Edge
    +in : Trinity Force
    -out: Yun Tal Wildarrows
- **DSP2_exempt_offclass**
    OFF: Runaan's Hurricane, Kraken Slayer, Essence Reaver, Stormrazor, Infinity Edge, Yun Tal Wildarrows
    ON : Runaan's Hurricane, Kraken Slayer, Essence Reaver, Trinity Force, Stormrazor, Infinity Edge
    +in : Trinity Force
    -out: Yun Tal Wildarrows
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Essence Reaver, Trinity Force, Infinity Edge, Lich Bane, Rabadon's Deathcap
    ON : Wooglet's Witchcap, Lich Bane, Essence Reaver, Rabadon's Deathcap, Shadowflame, Trinity Force
    +in : Shadowflame
    -out: Infinity Edge
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Essence Reaver, Trinity Force, Infinity Edge, Lich Bane, Rabadon's Deathcap
    ON : Wooglet's Witchcap, Lich Bane, Rabadon's Deathcap, Hextech Gunblade, Essence Reaver, Infinity Edge
    +in : Hextech Gunblade
    -out: Trinity Force

## Gnar (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Rabadon's Deathcap, Infinity Edge
    ON : Wooglet's Witchcap, Lich Bane, Trinity Force, Essence Reaver, Rabadon's Deathcap, Lord Dominik's Regards
    +in : Lord Dominik's Regards
    -out: Infinity Edge
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Rabadon's Deathcap, Infinity Edge
    ON : Wooglet's Witchcap, Lich Bane, Rabadon's Deathcap, Trinity Force, Essence Reaver, Dusk and Dawn
    +in : Dusk and Dawn
    -out: Infinity Edge
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Heartsteel, Essence Reaver, Runaan's Hurricane, Stormrazor
    ON : Sterak's Gage, Black Cleaver, Randuin's Omen, Thornmail, Void Immolation, Trinity Force
    +in : Sterak's Gage, Black Cleaver, Randuin's Omen, Thornmail
    -out: Heartsteel, Essence Reaver, Runaan's Hurricane, Stormrazor

## JarvanIV (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Sundered Sky, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Wooglet's Witchcap, Umbral Glaive, Bloodthirster
    +in : Wooglet's Witchcap, Umbral Glaive
    -out: Sundered Sky, Kraken Slayer
- **DSV2_assume_takedown**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Sundered Sky, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Sundered Sky, Hubris
    +in : Hubris
    -out: Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Sundered Sky, Kraken Slayer
    ON : Wooglet's Witchcap, Essence Reaver, Trinity Force, Lich Bane, Infinity Edge, Umbral Glaive
    +in : Wooglet's Witchcap, Lich Bane, Umbral Glaive
    -out: Bloodthirster, Sundered Sky, Kraken Slayer
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Runaan's Hurricane, Kraken Slayer, Essence Reaver, Heartsteel
    ON : Sundered Sky, Death's Dance, Sterak's Gage, Void Immolation, Trinity Force, Runaan's Hurricane
    +in : Sundered Sky, Death's Dance, Sterak's Gage
    -out: Kraken Slayer, Essence Reaver, Heartsteel

## KSante (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Trinity Force, Essence Reaver, Iceborn Gauntlet, Sundered Sky, Runaan's Hurricane, Infinity Edge
    ON : Trinity Force, Essence Reaver, Iceborn Gauntlet, Lord Dominik's Regards, Lich Bane, Sundered Sky
    +in : Lord Dominik's Regards, Lich Bane
    -out: Runaan's Hurricane, Infinity Edge
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Iceborn Gauntlet, Sundered Sky, Runaan's Hurricane, Infinity Edge
    ON : Trinity Force, Essence Reaver, Lich Bane, Iceborn Gauntlet, Lord Dominik's Regards, Dusk and Dawn
    +in : Lich Bane, Lord Dominik's Regards, Dusk and Dawn
    -out: Sundered Sky, Runaan's Hurricane, Infinity Edge
- **RF36_survivability_ehp**
    OFF: Void Immolation, Warmog's Armor, Jak'Sho, The Protean, Kaenic Rookern, Heartsteel, Randuin's Omen
    ON : Iceborn Gauntlet, Thornmail, Void Immolation, Warmog's Armor, Jak'Sho, The Protean, Kaenic Rookern
    +in : Iceborn Gauntlet, Thornmail
    -out: Heartsteel, Randuin's Omen

## Naafiri (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Infinity Edge, Essence Reaver, Bloodthirster, Sundered Sky, Kraken Slayer, Trinity Force
    ON : The Collector, Hubris, Infinity Edge, Essence Reaver, Bloodthirster, Sundered Sky
    +in : The Collector, Hubris
    -out: Kraken Slayer, Trinity Force
- **DSP11_kit_axis_dps**
    OFF: Trinity Force, Essence Reaver, Kraken Slayer, Stormrazor, Heartsteel, Runaan's Hurricane
    ON : The Collector, Hubris, Trinity Force, Essence Reaver, Kraken Slayer, Stormrazor
    +in : The Collector, Hubris
    -out: Heartsteel, Runaan's Hurricane
- **DSP8_target_preset=squishy**
    OFF: Infinity Edge, Essence Reaver, Bloodthirster, Sundered Sky, Kraken Slayer, Trinity Force
    ON : Infinity Edge, Essence Reaver, Umbral Glaive, Bloodthirster, Sundered Sky, Axiom Arc
    +in : Umbral Glaive, Axiom Arc
    -out: Kraken Slayer, Trinity Force
- **DSV2_assume_takedown**
    OFF: Infinity Edge, Essence Reaver, Bloodthirster, Sundered Sky, Kraken Slayer, Trinity Force
    ON : Infinity Edge, Essence Reaver, Bloodthirster, Sundered Sky, Kraken Slayer, Hubris
    +in : Hubris
    -out: Trinity Force
- **DSV3_assume_squishy_target**
    OFF: Infinity Edge, Essence Reaver, Bloodthirster, Sundered Sky, Kraken Slayer, Trinity Force
    ON : Infinity Edge, Essence Reaver, Umbral Glaive, Bloodthirster, Sundered Sky, Axiom Arc
    +in : Umbral Glaive, Axiom Arc
    -out: Kraken Slayer, Trinity Force

## Nilah (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Infinity Edge, Immortal Shieldbow, Lord Dominik's Regards, Navori Flickerblade, Essence Reaver, Trinity Force
    +in : Immortal Shieldbow, Lord Dominik's Regards, Navori Flickerblade
    -out: Sundered Sky, Bloodthirster, Kraken Slayer
- **DSP11_kit_axis_dps**
    OFF: Trinity Force, Essence Reaver, Kraken Slayer, Stormrazor, Heartsteel, Runaan's Hurricane
    ON : Infinity Edge, Navori Flickerblade, Immortal Shieldbow, Lord Dominik's Regards, Trinity Force, Essence Reaver
    +in : Infinity Edge, Navori Flickerblade, Immortal Shieldbow, Lord Dominik's Regards
    -out: Kraken Slayer, Stormrazor, Heartsteel, Runaan's Hurricane
- **DSP8_target_preset=squishy**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Umbral Glaive
    +in : Umbral Glaive
    -out: Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Umbral Glaive
    +in : Umbral Glaive
    -out: Kraken Slayer

## Pyke (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Kraken Slayer
    ON : Axiom Arc, Youmuu's Ghostblade, Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge
    +in : Axiom Arc, Youmuu's Ghostblade
    -out: Bloodthirster, Kraken Slayer
- **DSP11_kit_axis_dps**
    OFF: Trinity Force, Kraken Slayer, Essence Reaver, Runaan's Hurricane, Stormrazor, Heartsteel
    ON : Axiom Arc, Youmuu's Ghostblade, Trinity Force, Kraken Slayer, Essence Reaver, Runaan's Hurricane
    +in : Axiom Arc, Youmuu's Ghostblade
    -out: Stormrazor, Heartsteel
- **DSP8_target_preset=squishy**
    OFF: Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Kraken Slayer
    ON : Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Umbral Glaive, Serylda's Grudge
    +in : Umbral Glaive, Serylda's Grudge
    -out: Bloodthirster, Kraken Slayer
- **DSV2_assume_takedown**
    OFF: Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Kraken Slayer
    ON : Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Hubris
    +in : Hubris
    -out: Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Kraken Slayer
    ON : Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Umbral Glaive, Serylda's Grudge
    +in : Umbral Glaive, Serylda's Grudge
    -out: Bloodthirster, Kraken Slayer

## Quinn (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Kraken Slayer, Iceborn Gauntlet
    ON : Infinity Edge, The Collector, Statikk Shiv, Mortal Reminder, Lord Dominik's Regards, Trinity Force
    +in : The Collector, Statikk Shiv, Mortal Reminder, Lord Dominik's Regards
    -out: Essence Reaver, Sundered Sky, Kraken Slayer, Iceborn Gauntlet
- **DSP11_kit_axis_dps**
    OFF: Runaan's Hurricane, Kraken Slayer, Essence Reaver, Stormrazor, Infinity Edge, Yun Tal Wildarrows
    ON : Infinity Edge, Statikk Shiv, The Collector, Mortal Reminder, Lord Dominik's Regards, Runaan's Hurricane
    +in : Statikk Shiv, The Collector, Mortal Reminder, Lord Dominik's Regards
    -out: Kraken Slayer, Essence Reaver, Stormrazor, Yun Tal Wildarrows
- **DSP8_target_preset=squishy**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Kraken Slayer, Iceborn Gauntlet
    ON : Trinity Force, Essence Reaver, Infinity Edge, Lich Bane, Sundered Sky, Kraken Slayer
    +in : Lich Bane
    -out: Iceborn Gauntlet
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Kraken Slayer, Iceborn Gauntlet
    ON : Trinity Force, Essence Reaver, Lich Bane, Infinity Edge, Sundered Sky, Dusk and Dawn
    +in : Lich Bane, Dusk and Dawn
    -out: Kraken Slayer, Iceborn Gauntlet

## Rakan (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Rabadon's Deathcap, Iceborn Gauntlet
    ON : Wooglet's Witchcap, Lich Bane, Trinity Force, Rabadon's Deathcap, Shadowflame, Essence Reaver
    +in : Shadowflame
    -out: Iceborn Gauntlet
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Rabadon's Deathcap, Iceborn Gauntlet
    ON : Wooglet's Witchcap, Lich Bane, Rabadon's Deathcap, Dusk and Dawn, Trinity Force, Essence Reaver
    +in : Dusk and Dawn
    -out: Iceborn Gauntlet
- **RF2_survivability_hps**
    OFF: Echoes of Helia, Ardent Censer, Staff of Flowing Water, Locket of the Iron Solari, Knight's Vow, Redemption
    ON : Guardian's Horn, Warmog's Armor, Heartsteel, Echoes of Helia, Ardent Censer, Staff of Flowing Water
    +in : Guardian's Horn, Warmog's Armor, Heartsteel
    -out: Locket of the Iron Solari, Knight's Vow, Redemption

## RekSai (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Umbral Glaive, Bloodthirster
    +in : Umbral Glaive
    -out: Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Trinity Force, Essence Reaver, Infinity Edge, Lich Bane, Sundered Sky, Umbral Glaive
    +in : Lich Bane, Umbral Glaive
    -out: Bloodthirster, Kraken Slayer
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Heartsteel, Runaan's Hurricane, Essence Reaver, Kraken Slayer
    ON : Sundered Sky, Spirit Visage, Void Immolation, Trinity Force, Heartsteel, Runaan's Hurricane
    +in : Sundered Sky, Spirit Visage
    -out: Essence Reaver, Kraken Slayer

## Rell (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Lich Bane, Trinity Force, Essence Reaver, Rabadon's Deathcap, Dusk and Dawn
    ON : Wooglet's Witchcap, Lich Bane, Rabadon's Deathcap, Shadowflame, Trinity Force, Void Staff
    +in : Shadowflame, Void Staff
    -out: Essence Reaver, Dusk and Dawn
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Lich Bane, Trinity Force, Essence Reaver, Rabadon's Deathcap, Dusk and Dawn
    ON : Wooglet's Witchcap, Lich Bane, Rabadon's Deathcap, Dusk and Dawn, Shadowflame, Riftmaker
    +in : Shadowflame, Riftmaker
    -out: Trinity Force, Essence Reaver
- **RF36_survivability_ehp**
    OFF: Void Immolation, Warmog's Armor, Jak'Sho, The Protean, Kaenic Rookern, Heartsteel, Randuin's Omen
    ON : Fimbulwinter, Void Immolation, Warmog's Armor, Jak'Sho, The Protean, Kaenic Rookern, Heartsteel
    +in : Fimbulwinter
    -out: Randuin's Omen

## Senna (ARAM)
- **DSP11_kit_axis_burst**
    OFF: Essence Reaver, Infinity Edge, Trinity Force, Bloodthirster, Sundered Sky, Kraken Slayer
    ON : Black Cleaver, Essence Reaver, Infinity Edge, Trinity Force, Bloodthirster, Sundered Sky
    +in : Black Cleaver
    -out: Kraken Slayer
- **DSP11_kit_axis_dps**
    OFF: Kraken Slayer, Stormrazor, Essence Reaver, Infinity Edge, Void Immolation, Voltaic Cyclosword
    ON : Black Cleaver, Kraken Slayer, Stormrazor, Essence Reaver, Infinity Edge, Void Immolation
    +in : Black Cleaver
    -out: Voltaic Cyclosword
- **DSP8_target_preset=squishy**
    OFF: Essence Reaver, Infinity Edge, Trinity Force, Bloodthirster, Sundered Sky, Kraken Slayer
    ON : Essence Reaver, Infinity Edge, Umbral Glaive, Serylda's Grudge, Lord Dominik's Regards, Axiom Arc
    +in : Umbral Glaive, Serylda's Grudge, Lord Dominik's Regards, Axiom Arc
    -out: Trinity Force, Bloodthirster, Sundered Sky, Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Essence Reaver, Infinity Edge, Trinity Force, Bloodthirster, Sundered Sky, Kraken Slayer
    ON : Essence Reaver, Infinity Edge, Umbral Glaive, Serylda's Grudge, Lord Dominik's Regards, Axiom Arc
    +in : Umbral Glaive, Serylda's Grudge, Lord Dominik's Regards, Axiom Arc
    -out: Trinity Force, Bloodthirster, Sundered Sky, Kraken Slayer

## Smolder (ARAM)
- **DSP2_exempt_offclass**
    OFF: Kraken Slayer, Essence Reaver, Runaan's Hurricane, Stormrazor, Infinity Edge, Yun Tal Wildarrows
    ON : Kraken Slayer, Trinity Force, Essence Reaver, Runaan's Hurricane, Stormrazor, Infinity Edge
    +in : Trinity Force
    -out: Yun Tal Wildarrows
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Wooglet's Witchcap, Infinity Edge, Umbral Glaive, Essence Reaver, Bloodthirster, Serylda's Grudge
    +in : Umbral Glaive, Serylda's Grudge
    -out: Trinity Force, Endless Hunger
- **DSV2_assume_takedown**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Hubris
    +in : Hubris
    -out: Endless Hunger
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Infinity Edge, Essence Reaver, Bloodthirster, Trinity Force, Endless Hunger
    ON : Wooglet's Witchcap, Infinity Edge, Umbral Glaive, Essence Reaver, Bloodthirster, Serylda's Grudge
    +in : Umbral Glaive, Serylda's Grudge
    -out: Trinity Force, Endless Hunger

## Tryndamere (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Trinity Force, Essence Reaver, Wooglet's Witchcap, Iceborn Gauntlet, Sundered Sky, Lich Bane
    ON : Trinity Force, Essence Reaver, Lich Bane, Wooglet's Witchcap, Iceborn Gauntlet, Sundered Sky
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Wooglet's Witchcap, Iceborn Gauntlet, Sundered Sky, Lich Bane
    ON : Trinity Force, Lich Bane, Essence Reaver, Wooglet's Witchcap, Dusk and Dawn, Iceborn Gauntlet
    +in : Dusk and Dawn
    -out: Sundered Sky
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Runaan's Hurricane, Trinity Force, Kraken Slayer, Essence Reaver, Heartsteel
    ON : Titanic Hydra, Void Immolation, Runaan's Hurricane, Trinity Force, Kraken Slayer, Essence Reaver
    +in : Titanic Hydra
    -out: Heartsteel

## Udyr (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Iceborn Gauntlet, Sundered Sky
    ON : Wooglet's Witchcap, Trinity Force, Lich Bane, Essence Reaver, Dusk and Dawn, Iceborn Gauntlet
    +in : Dusk and Dawn
    -out: Sundered Sky
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Iceborn Gauntlet, Sundered Sky
    ON : Wooglet's Witchcap, Lich Bane, Trinity Force, Dusk and Dawn, Essence Reaver, Rabadon's Deathcap
    +in : Dusk and Dawn, Rabadon's Deathcap
    -out: Iceborn Gauntlet, Sundered Sky
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Heartsteel, Essence Reaver, Dusk and Dawn, Iceborn Gauntlet
    ON : Jak'Sho, The Protean, Spirit Visage, Thornmail, Void Immolation, Trinity Force, Heartsteel
    +in : Jak'Sho, The Protean, Spirit Visage, Thornmail
    -out: Essence Reaver, Dusk and Dawn, Iceborn Gauntlet

## Urgot (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Trinity Force, Essence Reaver, Infinity Edge, Lord Dominik's Regards, Umbral Glaive, Sundered Sky
    +in : Lord Dominik's Regards, Umbral Glaive
    -out: Bloodthirster, Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Trinity Force, Essence Reaver, Infinity Edge, Lich Bane, Lord Dominik's Regards, Umbral Glaive
    +in : Lich Bane, Lord Dominik's Regards, Umbral Glaive
    -out: Sundered Sky, Bloodthirster, Kraken Slayer
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Heartsteel, Essence Reaver, Runaan's Hurricane, Iceborn Gauntlet
    ON : Titanic Hydra, Overlord's Bloodmail, Black Cleaver, Jak'Sho, The Protean, Thornmail, Void Immolation
    +in : Titanic Hydra, Overlord's Bloodmail, Black Cleaver, Jak'Sho, The Protean, Thornmail
    -out: Trinity Force, Heartsteel, Essence Reaver, Runaan's Hurricane, Iceborn Gauntlet

## Yasuo (ARAM)
- **DSP8_target_preset=squishy**
    OFF: Essence Reaver, Trinity Force, Wooglet's Witchcap, Infinity Edge, Sundered Sky, Bloodthirster
    ON : Wooglet's Witchcap, Essence Reaver, Trinity Force, Infinity Edge, Lich Bane, Umbral Glaive
    +in : Lich Bane, Umbral Glaive
    -out: Sundered Sky, Bloodthirster
- **DSV3_assume_squishy_target**
    OFF: Essence Reaver, Trinity Force, Wooglet's Witchcap, Infinity Edge, Sundered Sky, Bloodthirster
    ON : Wooglet's Witchcap, Lich Bane, Essence Reaver, Trinity Force, Infinity Edge, Umbral Glaive
    +in : Lich Bane, Umbral Glaive
    -out: Sundered Sky, Bloodthirster
- **RF1_survivability_hybrid**
    OFF: Void Immolation, Trinity Force, Heartsteel, Essence Reaver, Runaan's Hurricane, Stormrazor
    ON : Wit's End, Jak'Sho, The Protean, Void Immolation, Trinity Force, Heartsteel, Essence Reaver
    +in : Wit's End, Jak'Sho, The Protean
    -out: Runaan's Hurricane, Stormrazor
