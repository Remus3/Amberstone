# Live-Flip Eyeball - DS seam OFF vs ON (top-6 re-rank diff)

Read-only in-process re-rank; the live :8893 stays seam-OFF. For each
champ + seam, ON should be SANER not RANDOM (charter 4b). A seam with no
move for a champ is a no-op there (expected for non-tabled champs).

champs: 1 | level 13 | top-6

## Caitlyn (ARAM)
- **DSP8_target_preset=tank**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Lord Dominik's Regards, Serylda's Grudge, Trinity Force, Essence Reaver, Terminus, Mortal Reminder
    +in : Lord Dominik's Regards, Serylda's Grudge, Terminus, Mortal Reminder
    -out: Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
- **DSV3_assume_squishy_target**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Trinity Force, Essence Reaver, Lich Bane, Infinity Edge, Lord Dominik's Regards, Serylda's Grudge
    +in : Lich Bane, Lord Dominik's Regards, Serylda's Grudge
    -out: Sundered Sky, Bloodthirster, Kraken Slayer
- **DSV4_assume_ability_amp**
    OFF: Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Kraken Slayer
    ON : Trinity Force, Essence Reaver, Infinity Edge, Sundered Sky, Bloodthirster, Spear of Shojin
    +in : Spear of Shojin
    -out: Kraken Slayer
