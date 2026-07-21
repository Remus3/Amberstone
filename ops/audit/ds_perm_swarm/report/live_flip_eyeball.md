# Live-Flip Eyeball - DS seam OFF vs ON (top-6 re-rank diff)

Read-only in-process re-rank; the live :8893 stays seam-OFF. For each
champ + seam, ON should be SANER not RANDOM (charter 4b). A seam with no
move for a champ is a no-op there (expected for non-tabled champs).

champs: 4 | level 13 | top-6

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

## Briar (ARAM)
- **DSP8_target_preset=tank**
    OFF: Wooglet's Witchcap, Rabadon's Deathcap, Lich Bane, Hextech Gunblade, Essence Reaver, Trinity Force
    ON : Wooglet's Witchcap, Rabadon's Deathcap, Void Staff, Lich Bane, Hextech Gunblade, Shadowflame
    +in : Void Staff, Shadowflame
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
- **DSP8_target_preset=tank**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Serylda's Grudge, Lord Dominik's Regards, Infinity Edge, Mortal Reminder
    +in : Serylda's Grudge, Lord Dominik's Regards, Mortal Reminder
    -out: Sundered Sky, Bloodthirster, Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Essence Reaver, Trinity Force, Infinity Edge, Sundered Sky, Bloodthirster, Umbral Glaive
    +in : Umbral Glaive
    -out: Kraken Slayer
