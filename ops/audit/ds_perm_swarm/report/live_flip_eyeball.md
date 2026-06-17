# Live-Flip Eyeball - DS seam OFF vs ON (top-6 re-rank diff)

Read-only in-process re-rank; the live :8893 stays seam-OFF. For each
champ + seam, ON should be SANER not RANDOM (charter 4b). A seam with no
move for a champ is a no-op there (expected for non-tabled champs).

champs: 5 | level 13 | top-6

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
- **DSP8_target_preset=tank**
    OFF: Wooglet's Witchcap, Essence Reaver, Trinity Force, Infinity Edge, Lich Bane, Rabadon's Deathcap
    ON : Wooglet's Witchcap, Void Staff, Lich Bane, Rabadon's Deathcap, Essence Reaver, Trinity Force
    +in : Void Staff
    -out: Infinity Edge
- **DSV3_assume_squishy_target**
    OFF: Wooglet's Witchcap, Essence Reaver, Trinity Force, Infinity Edge, Lich Bane, Rabadon's Deathcap
    ON : Wooglet's Witchcap, Lich Bane, Rabadon's Deathcap, Hextech Gunblade, Essence Reaver, Infinity Edge
    +in : Hextech Gunblade
    -out: Trinity Force

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
- **DSP8_target_preset=tank**
    OFF: Sundered Sky, Essence Reaver, Trinity Force, Infinity Edge, Bloodthirster, Kraken Slayer
    ON : Serylda's Grudge, Lord Dominik's Regards, Sundered Sky, Essence Reaver, Mortal Reminder, Trinity Force
    +in : Serylda's Grudge, Lord Dominik's Regards, Mortal Reminder
    -out: Infinity Edge, Bloodthirster, Kraken Slayer
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

## KSante (ARAM)
- **DSP8_target_preset=tank**
    OFF: Trinity Force, Essence Reaver, Iceborn Gauntlet, Sundered Sky, Runaan's Hurricane, Infinity Edge
    ON : Trinity Force, Lord Dominik's Regards, Essence Reaver, Serylda's Grudge, Mortal Reminder, Black Cleaver
    +in : Lord Dominik's Regards, Serylda's Grudge, Mortal Reminder, Black Cleaver
    -out: Iceborn Gauntlet, Sundered Sky, Runaan's Hurricane, Infinity Edge
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

## Rakan (ARAM)
- **DSP8_target_preset=tank**
    OFF: Wooglet's Witchcap, Trinity Force, Essence Reaver, Lich Bane, Rabadon's Deathcap, Iceborn Gauntlet
    ON : Wooglet's Witchcap, Void Staff, Lich Bane, Trinity Force, Rabadon's Deathcap, Cryptbloom
    +in : Void Staff, Cryptbloom
    -out: Essence Reaver, Iceborn Gauntlet
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

## Rell (ARAM)
- **DSP8_target_preset=tank**
    OFF: Wooglet's Witchcap, Lich Bane, Trinity Force, Essence Reaver, Rabadon's Deathcap, Dusk and Dawn
    ON : Wooglet's Witchcap, Void Staff, Lich Bane, Rabadon's Deathcap, Cryptbloom, Shadowflame
    +in : Void Staff, Cryptbloom, Shadowflame
    -out: Trinity Force, Essence Reaver, Dusk and Dawn
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
