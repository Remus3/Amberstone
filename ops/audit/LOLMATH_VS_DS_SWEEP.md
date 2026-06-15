# lolmath vs Daemon Slayer - all-champion build sweep

lolmath patch label **26.12** (= DDragon **16.12.1**, same live patch). DS SR build_orders ENGINE **1.120.0**, patch **16.12.1**. Covered 172/172 champs; lolmath-no-data: none.

## Methodology

- **lolmath**, headless render, no live game -> lolmath's **constant default enemy comp = Jayce / Sejuani / Annie / Lucian / Thresh** (4 squishy + 1 tank). Two lolmath builds captured per champ:

  - **normal** = `Primary BUILD ORDER` (gold/cost-efficient purchase path).

  - **ULTIMATE** = `ULTIMATE BUILD (GLOBAL OPTIMIZATION)` on the RESULTS tab - lolmath's cost-IGNORING best-six-item set (global pass that re-tests replacing every item for hidden synergies). **This is the fairest analog to DS's 6-item recommendation** and is the primary lolmath column below.

- **DS** = static `build_orders_sr.json` `mixed` variant (synthetic neutral target: armor 80 / 2400 HP / 50-50 AD-AP). DS also ships `poke`/`burst_heavy`/`frontline_heavy` variants; DS does NOT take lolmath's 5-champ comp (see G6/G7).

- **kit** = champ intrinsic type (lolmath magical vs physical dmg share). **lm/ds** = each side's *item* skew.


## lolmath 'Not Yet Implemented' (verbatim from site)

> Not Yet Implemented: Infernal Cinder (map objective), Dragon Soul buffs on Summoner's Rift, Dynamic Levels for Self and Enemy Items, Dynamic Grievous Wounds, Dynamic Tenacity Proficiency, Accurate Tower Damage Scenarios.

Gaps lolmath itself declares - a shared-frontier checklist. DS already models some (Grievous Wounds, ARAM/Arena tenacity contexts); neither models Dragon Soul buffs or Infernal Cinder.


## Systematic gaps (DS work items)

- **G1 Build-philosophy mismatch AP-vs-AD** (20): Amumu, Blitzcrank, Diana, Elise, Galio, Gragas, Gwen, KogMaw, Lillia, Lulu, Mordekaiser, Nidalee, Nunu, Pyke, Rumble, Singed, TahmKench, Taric, Teemo, XinZhao. One tool builds >=2 of a damage type, the other builds **zero**. Where DS is AD on an AP-scaling kit (Gwen, Teemo, Rumble, ...), that is a DS archetype/scorer correctness bug (AP champ in an AD pool). Per-row flag `DS_AD_vs_LM_AP` / `DS_AP_vs_LM_AD`. **Highest priority.**

- **G2 Low overlap** (59 more champs, dmg-axis agrees but <=1 shared item): driven by G3-G6, not noise.

- **G3 Runes**: lolmath emits a full rune page per champ+comp; DS models **none**.

- **G4 Boots pool drift**: lolmath uses current 16.x upgraded boots; DS uses legacy boots. lolmath boots: Spellslinger's Shoes(22), Gluttonous Greaves(14), Boots of Swiftness(4), Sorcerer's Shoes(2). DS boots: Mercury's Treads(140), Berserker's Greaves(30).

- **G5 Item pools**: lolmath freely uses lethality (Hubris, Serylda's, Umbral, Collector), AP on-hit (Nashor's, Riftmaker, Guinsoo's), and current mythic-less items; audit DS's per-archetype pool for missing entries.

- **G6 Gold-efficiency mode**: lolmath has an `IGNORE ITEM COST` toggle + the ULTIMATE BUILD (cost-ignoring global opt). For **161/172** champs the cost-ignoring ultimate differs from the gold-aware normal build by >=1 item (usually dropping boots or a gold-efficient item for a pricier raw-stat / power-spike item) - so gold-efficiency actively shapes lolmath's normal recommendation. DS has **no cost model at all**: its order is a fixed list, neither gold-aware nor a cost-ignoring optimum. Full per-champ normal-vs-ultimate diff in the appendix below.

- **G7 Comp-aware exact-match harness (research)**: feed DS the SAME 5-champ comp via `/api/ds-preview` (POST, resolves live enemy stats) instead of static `mixed`, to compare like-for-like. This sweep used static DS builds.


## Per-champion table (lolmath ULTIMATE vs DS mixed)

`(g)` = lolmath ultimate differs from its gold-aware normal build (gold-efficiency mattered).

| Champ | kit | lm | ds | lolmath ULTIMATE | DS mixed | overlap | flag |
|---|---|---|---|---|---|---|---|
| Aatrox (g) | AD | AD | AD | Hubris, Endless Hunger, LDR, Spear of Shojin, Profane Hydra, Death Dance | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, Runaan | - | ok |
| Ahri (g) | AP | AP | AP | Stormsurge, Spellslinger Shoes, Liandry Torment, Shadowflame, Rabadon Deathcap, Hextech Gunblade | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Akali | AP | AP | AP | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Lich Bane, Shadowflame, Rabadon Deathcap | Void Staff, Mercury Treads, Rabadon Deathcap, Lich Bane, Shadowflame, Stormsurge | Lich Bane; Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Akshan (g) | AD | AD | AD | BORK, PD, Hubris, IE, LDR, The Collector | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards | ok |
| Alistar (g) | AP | - | AD | Celestial Opposition, Heartsteel, Titanic Hydra, Liandry Torment, Hollow Radiance, Warmog Armor | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Ambessa (g) | AD | AD | AD | Hubris, Death Dance, Endless Hunger, The Collector, BORK, LDR | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, LDR | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Amumu **!!** | AP | AP | AD | Liandry Torment, Warmog Armor, Zhonya Hourglass, Dead Man Plate, Cosmic Drive, Kaenic Rookern | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Kaenic Rookern; Warmog's Armor | DS_AD_vs_LM_AP |
| Anivia (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Hextech Gunblade, Cryptbloom, Blackfire Torch, Shadowflame | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame | ok |
| Annie | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Stormsurge, Hextech Gunblade, Blackfire Torch, Shadowflame | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge | ok |
| Aphelios (g) | AD | AD | AD | Hubris, Runaan, LDR, IE, PD, Gluttonous Greaves | Doran Shield, Berserker Greaves, Doran Blade, Doran Ring, Cull, Doran Bow | - | ok |
| Ashe (g) | AD | AD | AD | Hubris, PD, LDR, IE, Gluttonous Greaves, Yun Tal Wildarrows | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Infinity Edge; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| AurelionSol (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Shadowflame, Cryptbloom, Blackfire Torch, Cosmic Drive | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame | ok |
| Aurora (g) | AP | AP | AP | Cosmic Drive, Rabadon Deathcap, Actualizer, Archangel Staff, Cryptbloom, Shadowflame | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| Azir (g) | AP | AP | AP | Nashor Tooth, Spellslinger Shoes, Shadowflame, Cryptbloom, Rabadon Deathcap, Cosmic Drive | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| Bard (g) | AP | AP | AP | Solstice Sleigh, Cryptbloom, Locket of the Iron Solari, Liandry Torment, Shadowflame, Stormsurge | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Belveth (g) | AD | AD | AD | BORK, Bloodthirster, PD, LDR, Yun Tal Wildarrows, IE | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, Overlord Bloodmail | Blade of The Ruined King | ok |
| Blitzcrank **!!** | AP | AP | AD | Bloodsong, Cosmic Drive, Locket of the Iron Solari, Liandry Torment, Dead Man Plate, Warmog Armor | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | DS_AD_vs_LM_AP |
| Brand (g) | AP | AP | AP | Solstice Sleigh, Shadowflame, Liandry Torment, Locket of the Iron Solari, Stormsurge, Void Staff | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge; Void Staff | ok |
| Braum (g) | AP | AP | AD | Celestial Opposition, Dead Man Plate, Locket of the Iron Solari, Protoplasm Harness, Liandry Torment, Warmog Armor | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Briar (g) | AD | AD | AD | Hubris, The Collector, Death Dance, Endless Hunger, LDR, IE | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, Trinity Force | - | ok |
| Caitlyn (g) | AD | AD | AD | Hubris, PD, LDR, Yun Tal Wildarrows, IE, BORK | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Camille (g) | AD | AD | AD | Trinity Force, Hubris, Profane Hydra, Bastionbreaker, Death Dance, LDR | BORK, Mercury Treads, Trinity Force, Runaan, LDR, Bloodthirster | Lord Dominik's Regards; Trinity Force | ok |
| Cassiopeia | AP | AP | AP | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Shadowflame, Liandry Torment, Rabadon Deathcap | Rabadon Deathcap, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer, Riftmaker | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Chogath (g) | AP | - | AD | Cosmic Drive, Heartsteel, Warmog Armor, Dead Man Plate, Kaenic Rookern, Sterak Gage | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Kaenic Rookern; Sterak's Gage; Warmog's Armor | ok |
| Corki (g) | AD | AD | AD | Hubris, Gluttonous Greaves, Axiom Arc, Umbral Glaive, LDR, The Collector | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Lord Dominik's Regards | ok |
| Darius (g) | AD | AD | AD | LDR, Guardian Angel, Spirit Visage, Endless Hunger, Death Dance, The Collector | BORK, Mercury Treads, Runaan, LDR, Trinity Force, Bloodthirster | Lord Dominik's Regards | ok |
| Diana **!!** | AP | AP | AD | Stormsurge, Cryptbloom, Shadowflame, Cosmic Drive, Lich Bane, Rabadon Deathcap | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, LDR | - | DS_AD_vs_LM_AP |
| DrMundo (g) | AP | - | AD | Spirit Visage, Sunfire Aegis, Heartsteel, Warmog Armor, Protoplasm Harness, Dead Man Plate | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Spirit Visage; Warmog's Armor | ok |
| Draven (g) | AD | AD | AD | Hubris, LDR, BORK, Yun Tal Wildarrows, The Collector, IE | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Ekko (g) | AP | AP | AP | Stormsurge, Void Staff, Lich Bane, Shadowflame, Rabadon Deathcap, Nashor Tooth | Rabadon Deathcap, Mercury Treads, Lich Bane, Void Staff, Shadowflame, Stormsurge | Lich Bane; Rabadon's Deathcap; Shadowflame; Stormsurge; Void Staff | ok |
| Elise **!!** | AP | AP | AD | Stormsurge, Rabadon Deathcap, Cryptbloom, Lich Bane, Shadowflame, Hextech Gunblade | BORK, Mercury Treads, LDR, Essence Reaver, Runaan, IE | - | DS_AD_vs_LM_AP |
| Evelynn (g) | AP | AP | AP | Stormsurge, Riftmaker, Lich Bane, Rabadon Deathcap, Shadowflame, Cosmic Drive | Void Staff, Mercury Treads, Rabadon Deathcap, Lich Bane, Shadowflame, Stormsurge | Lich Bane; Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Ezreal (g) | AD | AD | AD | Hubris, Boots of Swiftness, Manamune, LDR, Umbral Glaive, Trinity Force | BORK, Berserker Greaves, Runaan, LDR, IE, Yun Tal Wildarrows | Lord Dominik's Regards | ok |
| Fiddlesticks (g) | AP | AP | AP | Stormsurge, Rabadon Deathcap, Shadowflame, Cosmic Drive, Zhonya Hourglass, Cryptbloom | Void Staff, Mercury Treads, Shadowflame, Rabadon Deathcap, Stormsurge, Riftmaker | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Fiora (g) | AD | AD | AD | Hubris, Endless Hunger, Ravenous Hydra, Manamune, Serylda Grudge, Death Dance | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, Sunfire Aegis | - | ok |
| Fizz (g) | AP | AP | AP | Stormsurge, Spellslinger Shoes, Lich Bane, Shadowflame, Rabadon Deathcap, Zhonya Hourglass | Rabadon Deathcap, Mercury Treads, Lich Bane, Void Staff, Shadowflame, Stormsurge | Lich Bane; Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Galio **!!** | AP | AP | AD | Cosmic Drive, Rabadon Deathcap, Winter Approach, Archangel Staff, Warmog Armor, Riftmaker | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Kaenic Rookern, Spirit Visage | Warmog's Armor | DS_AD_vs_LM_AP |
| Gangplank (g) | AD | AD | AD | Hubris, Endless Hunger, Profane Hydra, The Collector, LDR, IE | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, Runaan | - | ok |
| Garen (g) | AD | AD | AD | Hubris, Endless Hunger, LDR, PD, Death Dance, Trinity Force | Trinity Force, Mercury Treads, Heartsteel, Sterak Gage, Sunfire Aegis, Dead Man Plate | Trinity Force | ok |
| Gnar (g) | AD | AD | AD | Hubris, Sterak Gage, LDR, Dead Man Plate, The Collector, Bastionbreaker | BORK, Mercury Treads, Heartsteel, Sterak Gage, Trinity Force, Runaan | Sterak's Gage | ok |
| Gragas **!!** | AP | AP | AD | Archangel Staff, Shadowflame, Rabadon Deathcap, Cosmic Drive, Lich Bane, Cryptbloom | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, Runaan | - | DS_AD_vs_LM_AP |
| Graves (g) | AD | AD | AD | Hubris, Endless Hunger, LDR, Umbral Glaive, Bloodthirster, The Collector | BORK, Berserker Greaves, Runaan, LDR, IE, Bastionbreaker | Lord Dominik's Regards | ok |
| Gwen **!!** | AP | AP | AD | BORK, Rabadon Deathcap, Dusk and Dawn, Guinsoo Rageblade, Nashor Tooth, Riftmaker | BORK, Mercury Treads, Runaan, Trinity Force, Bloodthirster, LDR | Blade of The Ruined King | DS_AD_vs_LM_AP |
| Hecarim (g) | AD | AD | AD | Trinity Force, Hubris, Umbral Glaive, Profane Hydra, LDR, Death Dance | BORK, Mercury Treads, Trinity Force, Runaan, LDR, Bloodthirster | Lord Dominik's Regards; Trinity Force | ok |
| Heimerdinger (g) | AP | AP | AP | Stormsurge, Riftmaker, Shadowflame, Rabadon Deathcap, Void Staff, Zhonya Hourglass | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge; Void Staff | ok |
| Hwei (g) | AP | AP | AP | Liandry Torment, Shadowflame, Stormsurge, Cryptbloom, Archangel Staff, Rabadon Deathcap | Void Staff, Mercury Treads, Rabadon Deathcap, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Illaoi (g) | AD | AD | AD | Dead Man Plate, Black Cleaver, Warmog Armor, Overlord Bloodmail, Sterak Gage, Kaenic Rookern | Trinity Force, Mercury Treads, Heartsteel, Sunfire Aegis, Sterak Gage, Dead Man Plate | Dead Man's Plate; Sterak's Gage | ok |
| Irelia (g) | AD | AD | AD | BORK, Bloodthirster, PD, Yun Tal Wildarrows, IE, LDR | BORK, Mercury Treads, Runaan, Bloodthirster, LDR, Yun Tal Wildarrows | Blade of The Ruined King; Bloodthirster; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Ivern (g) | AP | AP | AP | Cosmic Drive, Riftmaker, Warmog Armor, Rabadon Deathcap, Kaenic Rookern, Zhonya Hourglass | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Janna (g) | AP | AP | AP | Dream Maker, Rabadon Deathcap, Actualizer, Blackfire Torch, Cryptbloom, Archangel Staff | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| JarvanIV (g) | AD | AD | AD | Hubris, Experimental Hexplate, Death Dance, BORK, LDR, Ravenous Hydra | BORK, Mercury Treads, Runaan, Trinity Force, LDR, Bloodthirster | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Jax (g) | AD | AD | AD | BORK, Hubris, Bloodthirster, IE, LDR, PD | BORK, Mercury Treads, Runaan, Heartsteel, Sterak Gage, LDR | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Jayce (g) | AD | AD | AD | Umbral Glaive, Hubris, Voltaic Cyclosword, LDR, Bastionbreaker, The Collector | Trinity Force, Mercury Treads, Heartsteel, Sterak Gage, Sunfire Aegis, Dead Man Plate | - | ok |
| Jhin (g) | AD | AD | AD | Hubris, PD, LDR, The Collector, Yun Tal Wildarrows, Gluttonous Greaves | BORK, Berserker Greaves, LDR, Runaan, IE, Essence Reaver | Lord Dominik's Regards | ok |
| Jinx | AD | AD | AD | Hubris, LDR, Gluttonous Greaves, PD, The Collector, IE | BORK, Berserker Greaves, Essence Reaver, LDR, Runaan, IE | Infinity Edge; Lord Dominik's Regards | ok |
| KSante (g) | AD | AP | AD | Heartsteel, Dead Man Plate, Warmog Armor, Hollow Radiance, Liandry Torment, Unending Despair | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Kaisa (g) | AD | AD | AD | BORK, Hubris, PD, LDR, Yun Tal Wildarrows, Gluttonous Greaves | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Kalista (g) | AD | AD | AD | Hubris, Gluttonous Greaves, LDR, Yun Tal Wildarrows, IE, BORK | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Karma (g) | AP | AP | AP | Dream Maker, Shadowflame, Liandry Torment, Rabadon Deathcap, Stormsurge, Cryptbloom | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Karthus (g) | AP | AP | AP | Liandry Torment, Sorcerer Shoes, Stormsurge, Shadowflame, Blackfire Torch, Void Staff | Void Staff, Mercury Treads, Rabadon Deathcap, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge; Void Staff | ok |
| Kassadin | AP | AP | AP | Stormsurge, Spellslinger Shoes, Lich Bane, Archangel Staff, Shadowflame, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Lich Bane, Stormsurge | Lich Bane; Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Katarina (g) | AP | AP | AP | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Rabadon Deathcap, Shadowflame, Lich Bane | Rabadon Deathcap, Mercury Treads, Lich Bane, Void Staff, Shadowflame, Stormsurge | Lich Bane; Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Kayle (g) | AP | AP | AP | Hextech Gunblade, Rabadon Deathcap, Nashor Tooth, Lich Bane, Shadowflame, Cryptbloom | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| Kayn (g) | AD | AD | AD | Endless Hunger, Hubris, Serylda Grudge, Spear of Shojin, Bastionbreaker, Death Dance | BORK, Mercury Treads, Heartsteel, Sterak Gage, Trinity Force, LDR | - | ok |
| Kennen (g) | AP | AP | AP | Liandry Torment, Zhonya Hourglass, Stormsurge, Shadowflame, Rabadon Deathcap, Void Staff | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge; Void Staff | ok |
| Khazix (g) | AD | AD | AD | Profane Hydra, Hubris, Umbral Glaive, Axiom Arc, LDR, Bastionbreaker | BORK, Mercury Treads, LDR, Bastionbreaker, Umbral Glaive, Runaan | Bastionbreaker; Lord Dominik's Regards; Umbral Glaive | ok |
| Kindred (g) | AD | AD | AD | Hubris, PD, LDR, The Collector, BORK, IE | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards | ok |
| Kled (g) | AD | AD | AD | Hubris, Death Dance, LDR, Ravenous Hydra, The Collector, BORK | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, Overlord Bloodmail | Blade of The Ruined King | ok |
| KogMaw **!!** | AP | AP | AD | Lich Bane, Boots of Swiftness, Nashor Tooth, Stormsurge, Shadowflame, Cryptbloom | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | - | DS_AD_vs_LM_AP |
| Leblanc (g) | AP | AP | AP | Stormsurge, Spellslinger Shoes, Blackfire Torch, Shadowflame, Rabadon Deathcap, Archangel Staff | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Lich Bane | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| LeeSin (g) | AD | AD | AD | Hubris, Profane Hydra, The Collector, LDR, Guardian Angel, Death Dance | BORK, Mercury Treads, Runaan, LDR, Bloodthirster, IE | Lord Dominik's Regards | ok |
| Leona (g) | AP | AP | AD | Bloodsong, Warmog Armor, Dead Man Plate, Liandry Torment, Heartsteel, Hollow Radiance | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Lillia **!!** | AP | AP | AD | Riftmaker, Cosmic Drive, Blackfire Torch, Archangel Staff, Cryptbloom, Rabadon Deathcap | Heartsteel, Mercury Treads, Trinity Force, Sunfire Aegis, Sterak Gage, Warmog Armor | - | DS_AD_vs_LM_AP |
| Lissandra (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Blackfire Torch, Shadowflame, Cryptbloom, Cosmic Drive | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame | ok |
| Lucian (g) | AD | AD | AD | Hubris, Yun Tal Wildarrows, BORK, LDR, The Collector, Gluttonous Greaves | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Lulu **!!** | AP | AP | AD | Dream Maker, Cryptbloom, Rabadon Deathcap, Stormsurge, Lich Bane, Shadowflame | BORK, Berserker Greaves, Runaan, LDR, IE, Yun Tal Wildarrows | - | DS_AD_vs_LM_AP |
| Lux (g) | AP | AP | AP | Solstice Sleigh, Shadowflame, Liandry Torment, Stormsurge, Blackfire Torch, Cryptbloom | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge | ok |
| Malphite (g) | AP | - | AD | Dead Man Plate, Liandry Torment, Warmog Armor, Hollow Radiance, Titanic Hydra, Kaenic Rookern | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Kaenic Rookern; Warmog's Armor | ok |
| Malzahar (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Blackfire Torch, Shadowflame, Cryptbloom, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| Maokai (g) | AP | AP | AD | Bloodsong, Heartsteel, Locket of the Iron Solari, Liandry Torment, Warmog Armor, Hollow Radiance | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| MasterYi (g) | AD | AD | AD | BORK, Guinsoo Rageblade, IE, LDR, Yun Tal Wildarrows, Ravenous Hydra | BORK, Mercury Treads, Runaan, Bloodthirster, Yun Tal Wildarrows, LDR | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Mel (g) | AP | AP | AP | Blackfire Torch, Rabadon Deathcap, Shadowflame, Archangel Staff, Cryptbloom, Cosmic Drive | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| Milio | AP | AP | AP | Dream Maker, Ardent Censer, Dawncore, Rabadon Deathcap, Zhonya Hourglass, Banshee Veil | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | Ardent Censer | ok |
| MissFortune (g) | AD | AD | AD | Hubris, PD, LDR, BORK, The Collector, Gluttonous Greaves | BORK, Mercury Treads, LDR, Essence Reaver, IE, Runaan | Blade of The Ruined King; Lord Dominik's Regards | ok |
| MonkeyKing (g) | AD | AD | AD | Hubris, Titanic Hydra, Warmog Armor, Hollow Radiance, Sterak Gage, LDR | BORK, Mercury Treads, Heartsteel, Trinity Force, LDR, Runaan | Lord Dominik's Regards | ok |
| Mordekaiser **!!** | AP | AP | AD | Liandry Torment, Dead Man Plate, Riftmaker, Force of Nature, Unending Despair, Warmog Armor | Trinity Force, Mercury Treads, Heartsteel, Sterak Gage, Sunfire Aegis, Warmog Armor | Warmog's Armor | DS_AD_vs_LM_AP |
| Morgana (g) | AP | AP | AP | Dream Maker, Shadowflame, Liandry Torment, Stormsurge, Blackfire Torch, Void Staff | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Naafiri (g) | AD | AD | AD | Hubris, Bastionbreaker, Profane Hydra, Umbral Glaive, LDR, Youmuu Ghostblade | BORK, Mercury Treads, LDR, Bastionbreaker, Umbral Glaive, Runaan | Bastionbreaker; Lord Dominik's Regards; Umbral Glaive | ok |
| Nami (g) | AP | AP | AP | Solstice Sleigh, Shadowflame, Lich Bane, Stormsurge, Void Staff, Rabadon Deathcap | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Nasus (g) | AD | AD | AD | Essence Reaver, Ravenous Hydra, Endless Hunger, Death Dance, Bastionbreaker, Serylda Grudge | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, LDR | - | ok |
| Nautilus (g) | AP | AP | AD | Bloodsong, Warmog Armor, Locket of the Iron Solari, Liandry Torment, Heartsteel, Hollow Radiance | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Neeko (g) | AP | AP | AP | Solstice Sleigh, Lich Bane, Rabadon Deathcap, Stormsurge, Void Staff, Shadowflame | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge; Void Staff | ok |
| Nidalee **!!** | AP | AP | AD | Stormsurge, Cosmic Drive, Shadowflame, Lich Bane, Rabadon Deathcap, Cryptbloom | BORK, Mercury Treads, LDR, Essence Reaver, IE, Runaan | - | DS_AD_vs_LM_AP |
| Nilah (g) | AD | AD | AD | Hubris, PD, The Collector, LDR, Profane Hydra, IE | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Infinity Edge; Lord Dominik's Regards | ok |
| Nocturne (g) | AD | AD | AD | Hubris, PD, The Collector, LDR, BORK, IE | BORK, Mercury Treads, Heartsteel, Runaan, Sterak Gage, LDR | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Nunu **!!** | AP | AP | AD | Cosmic Drive, Riftmaker, Warmog Armor, Unending Despair, Liandry Torment, Hollow Radiance | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | DS_AD_vs_LM_AP |
| Olaf (g) | AD | AD | AD | Ravenous Hydra, The Collector, BORK, Yun Tal Wildarrows, LDR, IE | BORK, Mercury Treads, Runaan, LDR, Yun Tal Wildarrows, Bloodthirster | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Orianna (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Cryptbloom, Blackfire Torch, Shadowflame, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| Ornn (g) | AP | AD | AD | Heartsteel, Titanic Hydra, Hollow Radiance, Warmog Armor, Dead Man Plate, Unending Despair | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Pantheon (g) | AD | AD | AD | Solstice Sleigh, Death Dance, Hubris, Voltaic Cyclosword, Umbral Glaive, Serylda Grudge | BORK, Mercury Treads, Heartsteel, Sterak Gage, Trinity Force, LDR | - | ok |
| Poppy (g) | AD | - | AD | Bloodsong, Titanic Hydra, Dead Man Plate, Hollow Radiance, Liandry Torment, Warmog Armor | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Pyke **!!** | AD | AD | AP | Bloodsong, LDR, Profane Hydra, Umbral Glaive, Voltaic Cyclosword, Bastionbreaker | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | DS_AP_vs_LM_AD |
| Qiyana (g) | AD | AD | AD | Umbral Glaive, Hubris, Voltaic Cyclosword, LDR, Profane Hydra, Youmuu Ghostblade | LDR, Mercury Treads, Bastionbreaker, Umbral Glaive, Sundered Sky, Axiom Arc | Lord Dominik's Regards; Umbral Glaive | ok |
| Quinn (g) | AD | AD | AD | Hubris, IE, LDR, The Collector, PD, BORK | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards | ok |
| Rakan (g) | AP | AP | AP | Dream Maker, Hextech Gunblade, Liandry Torment, Locket of the Iron Solari, Rabadon Deathcap, Lich Bane | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Rammus (g) | AP | AD | AD | Hollow Radiance, Dead Man Plate, Warmog Armor, Heartsteel, Sterak Gage, Titanic Hydra | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Sterak's Gage; Warmog's Armor | ok |
| RekSai (g) | AD | AD | AD | Titanic Hydra, Dead Man Plate, Warmog Armor, Hollow Radiance, Overlord Bloodmail, Liandry Torment | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, LDR | - | ok |
| Rell (g) | AP | AP | AD | Bloodsong, Dead Man Plate, Locket of the Iron Solari, Liandry Torment, Warmog Armor, Hollow Radiance | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | ok |
| Renata (g) | AP | AP | AP | Solstice Sleigh, Rabadon Deathcap, Liandry Torment, Stormsurge, Void Staff, Shadowflame | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Renekton (g) | AD | AD | AD | Hubris, Dead Man Plate, Warmog Armor, Titanic Hydra, Sterak Gage, LDR | BORK, Mercury Treads, Runaan, LDR, Trinity Force, Bloodthirster | Lord Dominik's Regards | ok |
| Rengar (g) | AD | AD | AD | Ravenous Hydra, Hubris, Bloodthirster, The Collector, LDR, IE | BORK, Mercury Treads, LDR, Runaan, IE, Bastionbreaker | Infinity Edge; Lord Dominik's Regards | ok |
| Riven (g) | AD | AD | AD | Umbral Glaive, Hubris, Profane Hydra, Axiom Arc, LDR, Bastionbreaker | BORK, Mercury Treads, Runaan, LDR, IE, Bloodthirster | Lord Dominik's Regards | ok |
| Rumble **!!** | AP | AP | AD | Liandry Torment, Sorcerer Shoes, Stormsurge, Blackfire Torch, Shadowflame, Hextech Gunblade | BORK, Mercury Treads, Heartsteel, Sterak Gage, Sunfire Aegis, Warmog Armor | - | DS_AD_vs_LM_AP |
| Ryze (g) | AP | AP | AP | Blackfire Torch, Void Staff, Shadowflame, Archangel Staff, Stormsurge, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge; Void Staff | ok |
| Samira | AD | AD | AD | Hubris, The Collector, LDR, Axiom Arc, Gluttonous Greaves, IE | BORK, Berserker Greaves, Runaan, LDR, IE, Yun Tal Wildarrows | Infinity Edge; Lord Dominik's Regards | ok |
| Sejuani (g) | AD | - | AD | Heartsteel, Warmog Armor, Liandry Torment, Dead Man Plate, Hollow Radiance, Sterak Gage | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Sterak's Gage; Warmog's Armor | ok |
| Senna (g) | AD | AD | AD | Solstice Sleigh, Bastionbreaker, Hubris, LDR, Umbral Glaive, Axiom Arc | BORK, Berserker Greaves, LDR, Runaan, IE, Yun Tal Wildarrows | Lord Dominik's Regards | ok |
| Seraphine (g) | AP | AP | AP | Dream Maker, Rabadon Deathcap, Cryptbloom, Cosmic Drive, Lich Bane, Archangel Staff | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Sett (g) | AD | AD | AD | Hubris, Warmog Armor, Overlord Bloodmail, Endless Hunger, Death Dance, Spear of Shojin | Trinity Force, Mercury Treads, Heartsteel, Sunfire Aegis, Sterak Gage, Flesheater | - | ok |
| Shaco (g) | AP | AD | AD | Hubris, PD, The Collector, IE, LDR, BORK | BORK, Mercury Treads, LDR, Essence Reaver, IE, Runaan | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards | ok |
| Shen (g) | AD | - | AD | Sunfire Aegis, Warmog Armor, Heartsteel, Titanic Hydra, Kaenic Rookern, Riftmaker | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Kaenic Rookern; Warmog's Armor | ok |
| Shyvana (g) | AP | AD | AD | BORK, IE, Endless Hunger, Bloodthirster, Death Dance, LDR | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, LDR | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Singed **!!** | AP | AP | AD | Liandry Torment, Shadowflame, Cosmic Drive, Warmog Armor, Blackfire Torch, Dead Man Plate | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | DS_AD_vs_LM_AP |
| Sion | AD | - | AD | Dead Man Plate, Hollow Radiance, Warmog Armor, Heartsteel, Liandry Torment, Sterak Gage | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Sterak's Gage; Warmog's Armor | ok |
| Sivir (g) | AD | AD | AD | Hubris, PD, LDR, IE, Yun Tal Wildarrows, BORK | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Skarner (g) | AD | AD | AD | Heartsteel, Warmog Armor, Sterak Gage, Dead Man Plate, Hollow Radiance, Overlord Bloodmail | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Sterak's Gage; Warmog's Armor | ok |
| Smolder (g) | AD | AD | AD | Hubris, Gluttonous Greaves, The Collector, LDR, IE, Death Dance | BORK, Berserker Greaves, Runaan, LDR, IE, Yun Tal Wildarrows | Infinity Edge; Lord Dominik's Regards | ok |
| Sona (g) | AP | AP | AP | Dream Maker, Rabadon Deathcap, Stormsurge, Shadowflame, Cryptbloom, Lich Bane | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Soraka (g) | AP | AP | AP | Dream Maker, Archangel Staff, Ardent Censer, Redemption, Dawncore, Rabadon Deathcap | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | Ardent Censer; Redemption | ok |
| Swain (g) | AP | AP | AP | Solstice Sleigh, Zhonya Hourglass, Liandry Torment, Locket of the Iron Solari, Cryptbloom, Shadowflame | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame | ok |
| Sylas (g) | AP | AP | AP | Lich Bane, Spellslinger Shoes, Hextech Gunblade, Shadowflame, Stormsurge, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Syndra (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Cryptbloom, Rabadon Deathcap, Shadowflame, Lich Bane | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame | ok |
| TahmKench **!!** | AP | AP | AD | Bloodsong, Riftmaker, Locket of the Iron Solari, Cosmic Drive, Heartsteel, Warmog Armor | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Warmog's Armor | DS_AD_vs_LM_AP |
| Taliyah (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Cryptbloom, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Talon (g) | AD | AD | AD | Profane Hydra, Hubris, Umbral Glaive, Serylda Grudge, Bastionbreaker, Youmuu Ghostblade | BORK, Mercury Treads, LDR, Bastionbreaker, Umbral Glaive, The Collector | Bastionbreaker; Umbral Glaive | ok |
| Taric **!!** | AP | AD | AP | Celestial Opposition, Titanic Hydra, Locket of the Iron Solari, Sunfire Aegis, Warmog Armor, Heartsteel | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | DS_AP_vs_LM_AD |
| Teemo **!!** | AP | AP | AD | Rabadon Deathcap, Stormsurge, Liandry Torment, Shadowflame, Void Staff, Lich Bane | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | - | DS_AD_vs_LM_AP |
| Thresh (g) | AP | AP | AP | Solstice Sleigh, Kaenic Rookern, Locket of the Iron Solari, Warmog Armor, Liandry Torment, Dead Man Plate | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Tristana (g) | AD | AD | AD | Hubris, PD, LDR, The Collector, BORK, IE | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards | ok |
| Trundle (g) | AD | AD | AD | Hubris, Ravenous Hydra, The Collector, LDR, Death Dance, BORK | BORK, Mercury Treads, Runaan, Trinity Force, LDR, Bloodthirster | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Tryndamere (g) | AD | AD | AD | Hubris, PD, Bloodthirster, LDR, Ravenous Hydra, BORK | BORK, Mercury Treads, Runaan, Bloodthirster, LDR, Yun Tal Wildarrows | Blade of The Ruined King; Bloodthirster; Lord Dominik's Regards | ok |
| TwistedFate | AP | AP | AP | Stormsurge, Spellslinger Shoes, Liandry Torment, Hextech Gunblade, Lich Bane, Shadowflame | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge | ok |
| Twitch (g) | AD | AD | AD | Hubris, Runaan, BORK, LDR, Yun Tal Wildarrows, IE | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Infinity Edge; Lord Dominik's Regards; Runaan's Hurricane; Yun Tal Wildarrows | ok |
| Udyr (g) | AP | AD | AD | Hubris, Yun Tal Wildarrows, Endless Hunger, IE, LDR, Death Dance | Trinity Force, Mercury Treads, Heartsteel, Sunfire Aegis, Sterak Gage, Flesheater | - | ok |
| Urgot (g) | AD | AD | AD | Hubris, Warmog Armor, Dead Man Plate, LDR, Sterak Gage, Overlord Bloodmail | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, LDR | Lord Dominik's Regards; Sterak's Gage | ok |
| Varus (g) | AD | AD | AD | Boots of Swiftness, Hubris, PD, LDR, Yun Tal Wildarrows, BORK | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Vayne (g) | AD | AD | AD | Hubris, PD, BORK, Gluttonous Greaves, Yun Tal Wildarrows, LDR | BORK, Berserker Greaves, Runaan, Yun Tal Wildarrows, LDR, IE | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Veigar (g) | AP | AP | AP | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Shadowflame, Rabadon Deathcap, Liandry Torment | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Velkoz (g) | AP | AP | AP | Solstice Sleigh, Shadowflame, Liandry Torment, Stormsurge, Void Staff, Blackfire Torch | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge; Void Staff | ok |
| Vex (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Rabadon Deathcap | Void Staff, Mercury Treads, Rabadon Deathcap, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Vi (g) | AD | AD | AD | Hubris, Ravenous Hydra, The Collector, Bloodthirster, LDR, IE | BORK, Mercury Treads, Runaan, LDR, Bloodthirster, Yun Tal Wildarrows | Bloodthirster; Lord Dominik's Regards | ok |
| Viego (g) | AD | AD | AD | Hubris, PD, Ravenous Hydra, LDR, BORK, IE | BORK, Mercury Treads, Manamune, Runaan, Manamune, Bloodthirster | Blade of The Ruined King | ok |
| Viktor (g) | AP | AP | AP | Stormsurge, Void Staff, Liandry Torment, Shadowflame, Zhonya Hourglass, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge; Void Staff | ok |
| Vladimir (g) | AP | AP | AP | Cosmic Drive, Zhonya Hourglass, Riftmaker, Rabadon Deathcap, Spirit Visage, Cryptbloom | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap | ok |
| Volibear (g) | AD | AD | AD | Titanic Hydra, Hollow Radiance, Warmog Armor, Heartsteel, Overlord Bloodmail, Black Cleaver | BORK, Mercury Treads, Runaan, Trinity Force, LDR, Bloodthirster | - | ok |
| Warwick (g) | AD | AD | AD | Hubris, Ravenous Hydra, Death Dance, Spirit Visage, BORK, LDR | BORK, Mercury Treads, Runaan, Trinity Force, LDR, Bloodthirster | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Xayah (g) | AD | AD | AD | Hubris, PD, LDR, Yun Tal Wildarrows, IE, Gluttonous Greaves | BORK, Berserker Greaves, Runaan, LDR, Yun Tal Wildarrows, IE | Infinity Edge; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Xerath (g) | AP | AP | AP | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Rabadon Deathcap | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| XinZhao **!!** | AD | AP | AD | Dusk and Dawn, Rabadon Deathcap, Spirit Visage, Nashor Tooth, Zhonya Hourglass, Guinsoo Rageblade | BORK, Mercury Treads, Runaan, LDR, Yun Tal Wildarrows, Bloodthirster | - | DS_AD_vs_LM_AP |
| Yasuo (g) | AD | AD | AD | BORK, Hubris, IE, LDR, Ravenous Hydra, Death Dance | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, LDR | Blade of The Ruined King; Lord Dominik's Regards | ok |
| Yone (g) | AD | AD | AD | Hubris, Mercurial Scimitar, BORK, IE, LDR, Ravenous Hydra | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, Runaan | Blade of The Ruined King | ok |
| Yorick (g) | AD | AD | AD | Titanic Hydra, Warmog Armor, Dead Man Plate, Hollow Radiance, Heartsteel, Overlord Bloodmail | BORK, Mercury Treads, Heartsteel, Trinity Force, Sterak Gage, Runaan | Heartsteel | ok |
| Yunara (g) | AD | AD | AD | Hubris, PD, BORK, LDR, The Collector, Yun Tal Wildarrows | BORK, Berserker Greaves, Runaan, Yun Tal Wildarrows, LDR, IE | Blade of The Ruined King; Lord Dominik's Regards; Yun Tal Wildarrows | ok |
| Yuumi (g) | AP | AP | AP | Dream Maker, Shadowflame, Blackfire Torch, Liandry Torment, Cryptbloom, Rabadon Deathcap | Echoes of Helia, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer, Locket of the Iron Solari | - | ok |
| Zaahen (g) | AD | AD | AD | Hubris, LDR, Endless Hunger, BORK, Death Dance, Trinity Force | BORK, Mercury Treads, Heartsteel, Sterak Gage, Runaan, Overlord Bloodmail | Blade of The Ruined King | ok |
| Zac (g) | AP | AP | AD | Warmog Armor, Hollow Radiance, Spirit Visage, Dead Man Plate, Liandry Torment, Heartsteel | Warmog Armor, Mercury Treads, Sterak Gage, Jak'Sho, The Protean, Spirit Visage, Kaenic Rookern | Spirit Visage; Warmog's Armor | ok |
| Zed (g) | AD | AD | AD | Umbral Glaive, Hubris, Youmuu Ghostblade, LDR, Profane Hydra, Bastionbreaker | LDR, Mercury Treads, Bastionbreaker, Umbral Glaive, Sundered Sky, Axiom Arc | Bastionbreaker; Lord Dominik's Regards; Umbral Glaive | ok |
| Zeri (g) | AD | AD | AD | The Collector, PD, LDR, Gluttonous Greaves, Hubris, IE | BORK, Berserker Greaves, Bloodsong, LDR, Voltaic Cyclosword, Runaan | Lord Dominik's Regards | ok |
| Ziggs | AP | AP | AP | Liandry Torment, Boots of Swiftness, Stormsurge, Shadowflame, Void Staff, Lich Bane | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge; Void Staff | ok |
| Zilean (g) | AP | AP | AP | Solstice Sleigh, Cryptbloom, Liandry Torment, Hextech Gunblade, Blackfire Torch, Shadowflame | Echoes of Helia, Mercury Treads, Ardent Censer, Staff of Flowing Water, Redemption, Moonstone Renewer | - | ok |
| Zoe (g) | AP | AP | AP | Stormsurge, Spellslinger Shoes, Liandry Torment, Rabadon Deathcap, Shadowflame, Lich Bane | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Rabadon's Deathcap; Shadowflame; Stormsurge | ok |
| Zyra (g) | AP | AP | AP | Solstice Sleigh, Shadowflame, Liandry Torment, Cosmic Drive, Void Staff, Stormsurge | Rabadon Deathcap, Mercury Treads, Void Staff, Shadowflame, Stormsurge, Mejai Soulstealer | Shadowflame; Stormsurge; Void Staff | ok |

## Appendix: lolmath normal (gold-aware) where it differs from ultimate

| Champ | normal (gold-aware) | ULTIMATE (cost-ignore) |
|---|---|---|
| Aatrox | Hubris, Gluttonous Greaves, Serylda Grudge, Umbral Glaive, Profane Hydra, Death Dance | Hubris, Endless Hunger, LDR, Spear of Shojin, Profane Hydra, Death Dance |
| Ahri | Stormsurge, Spellslinger Shoes, Liandry Torment, Shadowflame, Blackfire Torch, Hextech Gunblade | Stormsurge, Spellslinger Shoes, Liandry Torment, Shadowflame, Rabadon Deathcap, Hextech Gunblade |
| Akshan | BORK, Gunmetal Greaves, Guinsoo Rageblade, Kraken Slayer, LDR, The Collector | BORK, PD, Hubris, IE, LDR, The Collector |
| Alistar | Celestial Opposition, Ionian Boots of Lucidity, Locket of the Iron Solari, Liandry Torment, Hollow Radiance, Warmog Armor | Celestial Opposition, Heartsteel, Titanic Hydra, Liandry Torment, Hollow Radiance, Warmog Armor |
| Ambessa | Hubris, Gluttonous Greaves, Umbral Glaive, The Collector, Profane Hydra, LDR | Hubris, Death Dance, Endless Hunger, The Collector, BORK, LDR |
| Amumu | Liandry Torment, Gluttonous Greaves, Dead Man Plate, Abyssal Mask, Warmog Armor | Liandry Torment, Warmog Armor, Zhonya Hourglass, Dead Man Plate, Cosmic Drive, Kaenic Rookern |
| Anivia | Liandry Torment, Spellslinger Shoes, Winter Approach, Stormsurge, Blackfire Torch, Shadowflame | Liandry Torment, Spellslinger Shoes, Hextech Gunblade, Cryptbloom, Blackfire Torch, Shadowflame |
| Aphelios | BORK, Runaan, LDR, PD, The Collector, Gluttonous Greaves, Experimental Hexplate | Hubris, Runaan, LDR, IE, PD, Gluttonous Greaves |
| Ashe | Hubris, PD, LDR, The Collector, Gluttonous Greaves, Hexoptics C44, Bloodthirster | Hubris, PD, LDR, IE, Gluttonous Greaves, Yun Tal Wildarrows |
| AurelionSol | Liandry Torment, Spellslinger Shoes, Stormsurge, Cryptbloom, Winter Approach | Liandry Torment, Spellslinger Shoes, Shadowflame, Cryptbloom, Blackfire Torch, Cosmic Drive |
| Aurora | Blackfire Torch, Spellslinger Shoes, Actualizer, Archangel Staff, Cryptbloom, Shadowflame | Cosmic Drive, Rabadon Deathcap, Actualizer, Archangel Staff, Cryptbloom, Shadowflame |
| Azir | Nashor Tooth, Spellslinger Shoes, Shadowflame, Stormsurge, Rabadon Deathcap, PD | Nashor Tooth, Spellslinger Shoes, Shadowflame, Cryptbloom, Rabadon Deathcap, Cosmic Drive |
| Bard | Bloodsong, Ionian Boots of Lucidity, Locket of the Iron Solari, Liandry Torment, Winter Approach, Archangel Staff | Solstice Sleigh, Cryptbloom, Locket of the Iron Solari, Liandry Torment, Shadowflame, Stormsurge |
| Belveth | BORK, Gluttonous Greaves, The Collector, LDR, Immortal Shieldbow, PD | BORK, Bloodthirster, PD, LDR, Yun Tal Wildarrows, IE |
| Blitzcrank | Bloodsong, Ionian Boots of Lucidity, Locket of the Iron Solari, Liandry Torment, Winter Approach, Archangel Staff | Bloodsong, Cosmic Drive, Locket of the Iron Solari, Liandry Torment, Dead Man Plate, Warmog Armor |
| Brand | Bloodsong, Sorcerer Shoes, Liandry Torment, Locket of the Iron Solari, Stormsurge, Void Staff | Solstice Sleigh, Shadowflame, Liandry Torment, Locket of the Iron Solari, Stormsurge, Void Staff |
| Braum | Celestial Opposition, Ionian Boots of Lucidity, Locket of the Iron Solari, Protoplasm Harness, Liandry Torment, Warmog Armor | Celestial Opposition, Dead Man Plate, Locket of the Iron Solari, Protoplasm Harness, Liandry Torment, Warmog Armor |
| Briar | Hubris, The Collector, PD, LDR, Umbral Glaive | Hubris, The Collector, Death Dance, Endless Hunger, LDR, IE |
| Caitlyn | Hubris, PD, LDR, The Collector, IE, BORK, Gluttonous Greaves | Hubris, PD, LDR, Yun Tal Wildarrows, IE, BORK |
| Camille | Trinity Force, Boots of Swiftness, Profane Hydra, Manamune, Winter Approach, LDR | Trinity Force, Hubris, Profane Hydra, Bastionbreaker, Death Dance, LDR |
| Chogath | Plated Steelcaps, Heartsteel, Warmog Armor, Dead Man Plate, Kaenic Rookern, Liandry Torment | Cosmic Drive, Heartsteel, Warmog Armor, Dead Man Plate, Kaenic Rookern, Sterak Gage |
| Corki | Hubris, Gluttonous Greaves, Axiom Arc, Umbral Glaive, LDR, Fiendhunter Bolts, Bastionbreaker | Hubris, Gluttonous Greaves, Axiom Arc, Umbral Glaive, LDR, The Collector |
| Darius | Black Cleaver, Gluttonous Greaves, Spirit Visage, Endless Hunger, Death Dance, The Collector | LDR, Guardian Angel, Spirit Visage, Endless Hunger, Death Dance, The Collector |
| Diana | Stormsurge, Sorcerer Shoes, Shadowflame, Liandry Torment, Lich Bane | Stormsurge, Cryptbloom, Shadowflame, Cosmic Drive, Lich Bane, Rabadon Deathcap |
| DrMundo | Spirit Visage, Ionian Boots of Lucidity, Heartsteel, Warmog Armor, Frozen Heart, Dead Man Plate | Spirit Visage, Sunfire Aegis, Heartsteel, Warmog Armor, Protoplasm Harness, Dead Man Plate |
| Draven | Hubris, LDR, BORK, PD, The Collector, Rapid Firecannon, Gluttonous Greaves | Hubris, LDR, BORK, Yun Tal Wildarrows, The Collector, IE |
| Ekko | Stormsurge, Sorcerer Shoes, Lich Bane, Shadowflame, Rabadon Deathcap, Nashor Tooth | Stormsurge, Void Staff, Lich Bane, Shadowflame, Rabadon Deathcap, Nashor Tooth |
| Elise | Stormsurge, Sorcerer Shoes, Liandry Torment, Lich Bane, Shadowflame | Stormsurge, Rabadon Deathcap, Cryptbloom, Lich Bane, Shadowflame, Hextech Gunblade |
| Evelynn | Stormsurge, Sorcerer Shoes, Lich Bane, Rabadon Deathcap, Shadowflame, Cosmic Drive | Stormsurge, Riftmaker, Lich Bane, Rabadon Deathcap, Shadowflame, Cosmic Drive |
| Ezreal | Hubris, Boots of Swiftness, Manamune, LDR, Umbral Glaive, The Collector | Hubris, Boots of Swiftness, Manamune, LDR, Umbral Glaive, Trinity Force |
| Fiddlesticks | Stormsurge, Sorcerer Shoes, Shadowflame, Cosmic Drive, Liandry Torment | Stormsurge, Rabadon Deathcap, Shadowflame, Cosmic Drive, Zhonya Hourglass, Cryptbloom |
| Fiora | Hubris, Boots of Swiftness, Profane Hydra, Umbral Glaive, Serylda Grudge, Death Dance | Hubris, Endless Hunger, Ravenous Hydra, Manamune, Serylda Grudge, Death Dance |
| Fizz | Stormsurge, Spellslinger Shoes, Lich Bane, Shadowflame, Rabadon Deathcap, Hextech Gunblade | Stormsurge, Spellslinger Shoes, Lich Bane, Shadowflame, Rabadon Deathcap, Zhonya Hourglass |
| Galio | Cosmic Drive, Spellslinger Shoes, Winter Approach, Archangel Staff, Blackfire Torch | Cosmic Drive, Rabadon Deathcap, Winter Approach, Archangel Staff, Warmog Armor, Riftmaker |
| Gangplank | Essence Reaver, Gluttonous Greaves, Profane Hydra, The Collector, LDR, Voltaic Cyclosword | Hubris, Endless Hunger, Profane Hydra, The Collector, LDR, IE |
| Garen | Trinity Force, Gluttonous Greaves, Black Cleaver, PD, Death Dance, Endless Hunger | Hubris, Endless Hunger, LDR, PD, Death Dance, Trinity Force |
| Gnar | Hubris, Gluttonous Greaves, LDR, Umbral Glaive, The Collector, Bastionbreaker | Hubris, Sterak Gage, LDR, Dead Man Plate, The Collector, Bastionbreaker |
| Gragas | Hextech Rocketbelt, Sorcerer Shoes, Liandry Torment, Winter Approach, Stormsurge, Cryptbloom | Archangel Staff, Shadowflame, Rabadon Deathcap, Cosmic Drive, Lich Bane, Cryptbloom |
| Graves | Hubris, Gluttonous Greaves, LDR, Umbral Glaive, Axiom Arc, The Collector | Hubris, Endless Hunger, LDR, Umbral Glaive, Bloodthirster, The Collector |
| Gwen | BORK, PD, The Collector, LDR, Kraken Slayer | BORK, Rabadon Deathcap, Dusk and Dawn, Guinsoo Rageblade, Nashor Tooth, Riftmaker |
| Hecarim | Umbral Glaive, Boots of Swiftness, Profane Hydra, Voltaic Cyclosword, LDR | Trinity Force, Hubris, Umbral Glaive, Profane Hydra, LDR, Death Dance |
| Heimerdinger | Stormsurge, Gluttonous Greaves, Shadowflame, Rabadon Deathcap, Void Staff, Liandry Torment | Stormsurge, Riftmaker, Shadowflame, Rabadon Deathcap, Void Staff, Zhonya Hourglass |
| Hwei | Liandry Torment, Spellslinger Shoes, Stormsurge, Cryptbloom, Archangel Staff | Liandry Torment, Shadowflame, Stormsurge, Cryptbloom, Archangel Staff, Rabadon Deathcap |
| Illaoi | Dead Man Plate, Gluttonous Greaves, Warmog Armor, Overlord Bloodmail, Sterak Gage | Dead Man Plate, Black Cleaver, Warmog Armor, Overlord Bloodmail, Sterak Gage, Kaenic Rookern |
| Irelia | BORK, Gluttonous Greaves, The Collector, PD, Guardian Angel | BORK, Bloodthirster, PD, Yun Tal Wildarrows, IE, LDR |
| Ivern | Cosmic Drive, Plated Steelcaps, Locket of the Iron Solari, Archangel Staff, Winter Approach | Cosmic Drive, Riftmaker, Warmog Armor, Rabadon Deathcap, Kaenic Rookern, Zhonya Hourglass |
| Janna | Dream Maker, Ionian Boots of Lucidity, Staff of Flowing Water, Blackfire Torch, Ardent Censer, Archangel Staff | Dream Maker, Rabadon Deathcap, Actualizer, Blackfire Torch, Cryptbloom, Archangel Staff |
| JarvanIV | BORK, Experimental Hexplate, Gluttonous Greaves, The Collector, LDR | Hubris, Experimental Hexplate, Death Dance, BORK, LDR, Ravenous Hydra |
| Jax | BORK, Boots of Swiftness, Winter Approach, Manamune, Archangel Staff | BORK, Hubris, Bloodthirster, IE, LDR, PD |
| Jayce | Umbral Glaive, Boots of Swiftness, Voltaic Cyclosword, LDR, Youmuu Ghostblade, The Collector | Umbral Glaive, Hubris, Voltaic Cyclosword, LDR, Bastionbreaker, The Collector |
| Jhin | Hubris, PD, LDR, The Collector, Fiendhunter Bolts, Gluttonous Greaves, Axiom Arc | Hubris, PD, LDR, The Collector, Yun Tal Wildarrows, Gluttonous Greaves |
| KSante | Heartsteel, Boots of Swiftness, Warmog Armor, Sunfire Aegis, Winter Approach, Unending Despair | Heartsteel, Dead Man Plate, Warmog Armor, Hollow Radiance, Liandry Torment, Unending Despair |
| Kaisa | BORK, Hubris, PD, LDR, The Collector | BORK, Hubris, PD, LDR, Yun Tal Wildarrows, Gluttonous Greaves |
| Kalista | Hubris, Gluttonous Greaves, LDR, Guinsoo Rageblade, PD, BORK, Runaan | Hubris, Gluttonous Greaves, LDR, Yun Tal Wildarrows, IE, BORK |
| Karma | Dream Maker, Sorcerer Shoes, Liandry Torment, Ardent Censer, Stormsurge, Cryptbloom | Dream Maker, Shadowflame, Liandry Torment, Rabadon Deathcap, Stormsurge, Cryptbloom |
| Karthus | Liandry Torment, Sorcerer Shoes, Stormsurge, Shadowflame, Blackfire Torch, Cryptbloom | Liandry Torment, Sorcerer Shoes, Stormsurge, Shadowflame, Blackfire Torch, Void Staff |
| Katarina | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Liandry Torment, Shadowflame, Lich Bane | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Rabadon Deathcap, Shadowflame, Lich Bane |
| Kayle | Lich Bane, Nashor Tooth, Gluttonous Greaves, Liandry Torment, Cryptbloom | Hextech Gunblade, Rabadon Deathcap, Nashor Tooth, Lich Bane, Shadowflame, Cryptbloom |
| Kayn | Sundered Sky, Hubris, Serylda Grudge, Umbral Glaive, Axiom Arc, Gluttonous Greaves | Endless Hunger, Hubris, Serylda Grudge, Spear of Shojin, Bastionbreaker, Death Dance |
| Kennen | Liandry Torment, Sorcerer Shoes, Stormsurge, Shadowflame, Blackfire Torch, Cryptbloom | Liandry Torment, Zhonya Hourglass, Stormsurge, Shadowflame, Rabadon Deathcap, Void Staff |
| Khazix | Profane Hydra, Gluttonous Greaves, Umbral Glaive, Axiom Arc, Serylda Grudge, Youmuu Ghostblade | Profane Hydra, Hubris, Umbral Glaive, Axiom Arc, LDR, Bastionbreaker |
| Kindred | Hubris, PD, LDR, The Collector, Gluttonous Greaves, Rapid Firecannon | Hubris, PD, LDR, The Collector, BORK, IE |
| Kled | Hubris, Gluttonous Greaves, LDR, Profane Hydra, The Collector, BORK | Hubris, Death Dance, LDR, Ravenous Hydra, The Collector, BORK |
| KogMaw | Guinsoo Rageblade, PD, BORK, Boots of Swiftness, Nashor Tooth | Lich Bane, Boots of Swiftness, Nashor Tooth, Stormsurge, Shadowflame, Cryptbloom |
| Leblanc | Stormsurge, Spellslinger Shoes, Blackfire Torch, Shadowflame, Liandry Torment, Archangel Staff | Stormsurge, Spellslinger Shoes, Blackfire Torch, Shadowflame, Rabadon Deathcap, Archangel Staff |
| LeeSin | Hubris, Profane Hydra, The Collector, LDR, Umbral Glaive, Gluttonous Greaves | Hubris, Profane Hydra, The Collector, LDR, Guardian Angel, Death Dance |
| Leona | Bloodsong, Boots of Swiftness, Locket of the Iron Solari, Liandry Torment, Protoplasm Harness, Sunfire Aegis | Bloodsong, Warmog Armor, Dead Man Plate, Liandry Torment, Heartsteel, Hollow Radiance |
| Lillia | Riftmaker, Ionian Boots of Lucidity, Blackfire Torch, Archangel Staff, Winter Approach, Rabadon Deathcap | Riftmaker, Cosmic Drive, Blackfire Torch, Archangel Staff, Cryptbloom, Rabadon Deathcap |
| Lissandra | Liandry Torment, Spellslinger Shoes, Blackfire Torch, Stormsurge, Cryptbloom, Archangel Staff | Liandry Torment, Spellslinger Shoes, Blackfire Torch, Shadowflame, Cryptbloom, Cosmic Drive |
| Lucian | Hubris, PD, BORK, LDR, The Collector, Gluttonous Greaves, IE | Hubris, Yun Tal Wildarrows, BORK, LDR, The Collector, Gluttonous Greaves |
| Lulu | Bloodsong, Ionian Boots of Lucidity, Ardent Censer, Liandry Torment, Locket of the Iron Solari, Shurelya Battlesong | Dream Maker, Cryptbloom, Rabadon Deathcap, Stormsurge, Lich Bane, Shadowflame |
| Lux | Bloodsong, Sorcerer Shoes, Liandry Torment, Shurelya Battlesong, Blackfire Torch, Cryptbloom | Solstice Sleigh, Shadowflame, Liandry Torment, Stormsurge, Blackfire Torch, Cryptbloom |
| Malphite | Liandry Torment, Gluttonous Greaves, Dead Man Plate, Hollow Radiance, Locket of the Iron Solari | Dead Man Plate, Liandry Torment, Warmog Armor, Hollow Radiance, Titanic Hydra, Kaenic Rookern |
| Malzahar | Liandry Torment, Spellslinger Shoes, Blackfire Torch, Stormsurge, Cryptbloom, Luden Echo | Liandry Torment, Spellslinger Shoes, Blackfire Torch, Shadowflame, Cryptbloom, Rabadon Deathcap |
| Maokai | Bloodsong, Ionian Boots of Lucidity, Locket of the Iron Solari, Liandry Torment, Warmog Armor, Hollow Radiance | Bloodsong, Heartsteel, Locket of the Iron Solari, Liandry Torment, Warmog Armor, Hollow Radiance |
| MasterYi | BORK, Guinsoo Rageblade, Yun Tal Wildarrows, LDR, Profane Hydra | BORK, Guinsoo Rageblade, IE, LDR, Yun Tal Wildarrows, Ravenous Hydra |
| Mel | Blackfire Torch, Spellslinger Shoes, Shadowflame, Archangel Staff, Cryptbloom, Actualizer | Blackfire Torch, Rabadon Deathcap, Shadowflame, Archangel Staff, Cryptbloom, Cosmic Drive |
| MissFortune | Hubris, The Collector, LDR, Axiom Arc, PD, Gluttonous Greaves, IE | Hubris, PD, LDR, BORK, The Collector, Gluttonous Greaves |
| MonkeyKing | Sundered Sky, Titanic Hydra, Warmog Armor, Hollow Radiance, Plated Steelcaps, Overlord Bloodmail | Hubris, Titanic Hydra, Warmog Armor, Hollow Radiance, Sterak Gage, LDR |
| Mordekaiser | Liandry Torment, Sorcerer Shoes, Zeke Convergence, Protoplasm Harness, Unending Despair | Liandry Torment, Dead Man Plate, Riftmaker, Force of Nature, Unending Despair, Warmog Armor |
| Morgana | Bloodsong, Sorcerer Shoes, Liandry Torment, Locket of the Iron Solari, Blackfire Torch, Cryptbloom | Dream Maker, Shadowflame, Liandry Torment, Stormsurge, Blackfire Torch, Void Staff |
| Naafiri | Hubris, Gluttonous Greaves, Profane Hydra, Umbral Glaive, Serylda Grudge, Voltaic Cyclosword | Hubris, Bastionbreaker, Profane Hydra, Umbral Glaive, LDR, Youmuu Ghostblade |
| Nami | Bloodsong, Sorcerer Shoes, Liandry Torment, Stormsurge, Void Staff, Rabadon Deathcap | Solstice Sleigh, Shadowflame, Lich Bane, Stormsurge, Void Staff, Rabadon Deathcap |
| Nasus | Essence Reaver, Ravenous Hydra, Endless Hunger, Death Dance, Bastionbreaker, LDR | Essence Reaver, Ravenous Hydra, Endless Hunger, Death Dance, Bastionbreaker, Serylda Grudge |
| Nautilus | Bloodsong, Ionian Boots of Lucidity, Locket of the Iron Solari, Liandry Torment, Protoplasm Harness, Sunfire Aegis | Bloodsong, Warmog Armor, Locket of the Iron Solari, Liandry Torment, Heartsteel, Hollow Radiance |
| Neeko | Bloodsong, Sorcerer Shoes, Liandry Torment, Stormsurge, Cryptbloom, Shadowflame | Solstice Sleigh, Lich Bane, Rabadon Deathcap, Stormsurge, Void Staff, Shadowflame |
| Nidalee | Stormsurge, Sorcerer Shoes, Shadowflame, Lich Bane, Rabadon Deathcap | Stormsurge, Cosmic Drive, Shadowflame, Lich Bane, Rabadon Deathcap, Cryptbloom |
| Nilah | Hubris, PD, The Collector, LDR, IE, BORK | Hubris, PD, The Collector, LDR, Profane Hydra, IE |
| Nocturne | BORK, PD, The Collector, LDR, Profane Hydra, Gluttonous Greaves | Hubris, PD, The Collector, LDR, BORK, IE |
| Nunu | Cosmic Drive, Riftmaker, Warmog Armor, Blackfire Torch, Winter Approach, Plated Steelcaps | Cosmic Drive, Riftmaker, Warmog Armor, Unending Despair, Liandry Torment, Hollow Radiance |
| Olaf | Profane Hydra, Gluttonous Greaves, BORK, The Collector, LDR, Death Dance | Ravenous Hydra, The Collector, BORK, Yun Tal Wildarrows, LDR, IE |
| Orianna | Liandry Torment, Spellslinger Shoes, Stormsurge, Blackfire Torch, Shadowflame, Archangel Staff | Liandry Torment, Spellslinger Shoes, Cryptbloom, Blackfire Torch, Shadowflame, Rabadon Deathcap |
| Ornn | Dead Man Plate, Warmog Armor, Hollow Radiance, Heartsteel, Mercury Treads, Unending Despair | Heartsteel, Titanic Hydra, Hollow Radiance, Warmog Armor, Dead Man Plate, Unending Despair |
| Pantheon | Bloodsong, Gluttonous Greaves, Umbral Glaive, Locket of the Iron Solari, Voltaic Cyclosword, Serylda Grudge | Solstice Sleigh, Death Dance, Hubris, Voltaic Cyclosword, Umbral Glaive, Serylda Grudge |
| Poppy | Bloodsong, Boots of Swiftness, Locket of the Iron Solari, Sunfire Aegis, Liandry Torment, Warmog Armor | Bloodsong, Titanic Hydra, Dead Man Plate, Hollow Radiance, Liandry Torment, Warmog Armor |
| Pyke | Bloodsong, Ionian Boots of Lucidity, Profane Hydra, Umbral Glaive, Voltaic Cyclosword, Axiom Arc | Bloodsong, LDR, Profane Hydra, Umbral Glaive, Voltaic Cyclosword, Bastionbreaker |
| Qiyana | Umbral Glaive, Swiftmarch, Voltaic Cyclosword, Serylda Grudge, Profane Hydra, Youmuu Ghostblade | Umbral Glaive, Hubris, Voltaic Cyclosword, LDR, Profane Hydra, Youmuu Ghostblade |
| Quinn | Hubris, Gluttonous Greaves, LDR, The Collector, PD, BORK | Hubris, IE, LDR, The Collector, PD, BORK |
| Rakan | Bloodsong, Gluttonous Greaves, Liandry Torment, Locket of the Iron Solari, Shurelya Battlesong, Hextech Rocketbelt | Dream Maker, Hextech Gunblade, Liandry Torment, Locket of the Iron Solari, Rabadon Deathcap, Lich Bane |
| Rammus | Hollow Radiance, Dead Man Plate, Protoplasm Harness, Mercury Treads, Thornmail | Hollow Radiance, Dead Man Plate, Warmog Armor, Heartsteel, Sterak Gage, Titanic Hydra |
| RekSai | Heartsteel, Warmog Armor, Overlord Bloodmail, Dead Man Plate, Hollow Radiance | Titanic Hydra, Dead Man Plate, Warmog Armor, Hollow Radiance, Overlord Bloodmail, Liandry Torment |
| Rell | Bloodsong, Plated Steelcaps, Locket of the Iron Solari, Liandry Torment, Protoplasm Harness, Hollow Radiance | Bloodsong, Dead Man Plate, Locket of the Iron Solari, Liandry Torment, Warmog Armor, Hollow Radiance |
| Renata | Bloodsong, Sorcerer Shoes, Liandry Torment, Locket of the Iron Solari, Void Staff, Shadowflame | Solstice Sleigh, Rabadon Deathcap, Liandry Torment, Stormsurge, Void Staff, Shadowflame |
| Renekton | BORK, Mercury Treads, Dead Man Plate, Sterak Gage, Warmog Armor | Hubris, Dead Man Plate, Warmog Armor, Titanic Hydra, Sterak Gage, LDR |
| Rengar | Profane Hydra, Gluttonous Greaves, Umbral Glaive, The Collector, LDR, Voltaic Cyclosword | Ravenous Hydra, Hubris, Bloodthirster, The Collector, LDR, IE |
| Riven | Hubris, Profane Hydra, Serylda Grudge, Umbral Glaive, Gluttonous Greaves | Umbral Glaive, Hubris, Profane Hydra, Axiom Arc, LDR, Bastionbreaker |
| Ryze | Blackfire Torch, Spellslinger Shoes, Shadowflame, Archangel Staff, Stormsurge | Blackfire Torch, Void Staff, Shadowflame, Archangel Staff, Stormsurge, Rabadon Deathcap |
| Sejuani | Protoplasm Harness, Warmog Armor, Mercury Treads, Dead Man Plate, Hollow Radiance | Heartsteel, Warmog Armor, Liandry Torment, Dead Man Plate, Hollow Radiance, Sterak Gage |
| Senna | Bloodsong, Boots of Swiftness, Hubris, LDR, Umbral Glaive, Axiom Arc | Solstice Sleigh, Bastionbreaker, Hubris, LDR, Umbral Glaive, Axiom Arc |
| Seraphine | Solstice Sleigh, Ionian Boots of Lucidity, Locket of the Iron Solari, Shurelya Battlesong, Redemption, Archangel Staff | Dream Maker, Rabadon Deathcap, Cryptbloom, Cosmic Drive, Lich Bane, Archangel Staff |
| Sett | Heartsteel, Warmog Armor, Overlord Bloodmail, Boots of Swiftness, Sterak Gage | Hubris, Warmog Armor, Overlord Bloodmail, Endless Hunger, Death Dance, Spear of Shojin |
| Shaco | BORK, PD, The Collector, IE, LDR, Gluttonous Greaves | Hubris, PD, The Collector, IE, LDR, BORK |
| Shen | Sunfire Aegis, Warmog Armor, Heartsteel, Titanic Hydra, Kaenic Rookern, Unending Despair | Sunfire Aegis, Warmog Armor, Heartsteel, Titanic Hydra, Kaenic Rookern, Riftmaker |
| Shyvana | BORK, Gluttonous Greaves, Protoplasm Harness, Spirit Visage, Death Dance | BORK, IE, Endless Hunger, Bloodthirster, Death Dance, LDR |
| Singed | Liandry Torment, Boots of Swiftness, Protoplasm Harness, Locket of the Iron Solari, Blackfire Torch | Liandry Torment, Shadowflame, Cosmic Drive, Warmog Armor, Blackfire Torch, Dead Man Plate |
| Sivir | Hubris, PD, LDR, The Collector, Navori Flickerblade, BORK, Gluttonous Greaves | Hubris, PD, LDR, IE, Yun Tal Wildarrows, BORK |
| Skarner | Heartsteel, Warmog Armor, Boots of Swiftness, Dead Man Plate, Hollow Radiance | Heartsteel, Warmog Armor, Sterak Gage, Dead Man Plate, Hollow Radiance, Overlord Bloodmail |
| Smolder | Hubris, Gluttonous Greaves, The Collector, LDR, Youmuu Ghostblade | Hubris, Gluttonous Greaves, The Collector, LDR, IE, Death Dance |
| Sona | Dream Maker, Ionian Boots of Lucidity, Ardent Censer, Liandry Torment, Locket of the Iron Solari, Lich Bane | Dream Maker, Rabadon Deathcap, Stormsurge, Shadowflame, Cryptbloom, Lich Bane |
| Soraka | Dream Maker, Ionian Boots of Lucidity, Ardent Censer, Redemption, Dawncore, Staff of Flowing Water | Dream Maker, Archangel Staff, Ardent Censer, Redemption, Dawncore, Rabadon Deathcap |
| Swain | Solstice Sleigh, Sorcerer Shoes, Liandry Torment, Locket of the Iron Solari, Void Staff, Shadowflame | Solstice Sleigh, Zhonya Hourglass, Liandry Torment, Locket of the Iron Solari, Cryptbloom, Shadowflame |
| Sylas | Stormsurge, Spellslinger Shoes, Actualizer, Archangel Staff, Shadowflame | Lich Bane, Spellslinger Shoes, Hextech Gunblade, Shadowflame, Stormsurge, Rabadon Deathcap |
| Syndra | Liandry Torment, Spellslinger Shoes, Stormsurge, Blackfire Torch, Shadowflame, Lich Bane | Liandry Torment, Spellslinger Shoes, Cryptbloom, Rabadon Deathcap, Shadowflame, Lich Bane |
| TahmKench | Bloodsong, Sorcerer Shoes, Locket of the Iron Solari, Liandry Torment, Heartsteel, Warmog Armor | Bloodsong, Riftmaker, Locket of the Iron Solari, Cosmic Drive, Heartsteel, Warmog Armor |
| Taliyah | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Archangel Staff | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Cryptbloom, Rabadon Deathcap |
| Talon | Profane Hydra, Gluttonous Greaves, Umbral Glaive, Serylda Grudge, Voltaic Cyclosword, Youmuu Ghostblade | Profane Hydra, Hubris, Umbral Glaive, Serylda Grudge, Bastionbreaker, Youmuu Ghostblade |
| Taric | Celestial Opposition, Boots of Swiftness, Locket of the Iron Solari, Sunfire Aegis, Warmog Armor, Heartsteel | Celestial Opposition, Titanic Hydra, Locket of the Iron Solari, Sunfire Aegis, Warmog Armor, Heartsteel |
| Teemo | Luden Echo, Sorcerer Shoes, Liandry Torment, Shadowflame, Void Staff, Lich Bane | Rabadon Deathcap, Stormsurge, Liandry Torment, Shadowflame, Void Staff, Lich Bane |
| Thresh | Solstice Sleigh, Sorcerer Shoes, Locket of the Iron Solari, Protoplasm Harness, Liandry Torment, Dead Man Plate | Solstice Sleigh, Kaenic Rookern, Locket of the Iron Solari, Warmog Armor, Liandry Torment, Dead Man Plate |
| Tristana | Hubris, PD, LDR, The Collector, BORK, Rapid Firecannon, Gluttonous Greaves | Hubris, PD, LDR, The Collector, BORK, IE |
| Trundle | BORK, Gluttonous Greaves, The Collector, LDR, Death Dance | Hubris, Ravenous Hydra, The Collector, LDR, Death Dance, BORK |
| Tryndamere | BORK, PD, Gluttonous Greaves, LDR, Umbral Glaive | Hubris, PD, Bloodthirster, LDR, Ravenous Hydra, BORK |
| Twitch | Hextech Gunblade, Runaan, BORK, LDR, PD, The Collector, Gluttonous Greaves | Hubris, Runaan, BORK, LDR, Yun Tal Wildarrows, IE |
| Udyr | Trinity Force, Ionian Boots of Lucidity, Black Cleaver, Immortal Shieldbow, PD | Hubris, Yun Tal Wildarrows, Endless Hunger, IE, LDR, Death Dance |
| Urgot | Hubris, Gluttonous Greaves, Umbral Glaive, LDR, Youmuu Ghostblade, Guardian Angel | Hubris, Warmog Armor, Dead Man Plate, LDR, Sterak Gage, Overlord Bloodmail |
| Varus | Boots of Swiftness, Hubris, PD, LDR, The Collector, BORK, Rapid Firecannon | Boots of Swiftness, Hubris, PD, LDR, Yun Tal Wildarrows, BORK |
| Vayne | BORK, PD, Guinsoo Rageblade, Gluttonous Greaves, Wit End, LDR | Hubris, PD, BORK, Gluttonous Greaves, Yun Tal Wildarrows, LDR |
| Veigar | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Shadowflame, Rabadon Deathcap, Actualizer | Stormsurge, Spellslinger Shoes, Hextech Gunblade, Shadowflame, Rabadon Deathcap, Liandry Torment |
| Velkoz | Solstice Sleigh, Sorcerer Shoes, Liandry Torment, Stormsurge, Void Staff, Blackfire Torch | Solstice Sleigh, Shadowflame, Liandry Torment, Stormsurge, Void Staff, Blackfire Torch |
| Vex | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Luden Echo | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Rabadon Deathcap |
| Vi | BORK, Gluttonous Greaves, Profane Hydra, The Collector, LDR | Hubris, Ravenous Hydra, The Collector, Bloodthirster, LDR, IE |
| Viego | BORK, PD, Profane Hydra, LDR, The Collector, Gluttonous Greaves | Hubris, PD, Ravenous Hydra, LDR, BORK, IE |
| Viktor | Stormsurge, Spellslinger Shoes, Liandry Torment, Shadowflame, Lich Bane, Rabadon Deathcap | Stormsurge, Void Staff, Liandry Torment, Shadowflame, Zhonya Hourglass, Rabadon Deathcap |
| Vladimir | Cosmic Drive, Immortal Path, Riftmaker, Rabadon Deathcap, Spirit Visage, Cryptbloom | Cosmic Drive, Zhonya Hourglass, Riftmaker, Rabadon Deathcap, Spirit Visage, Cryptbloom |
| Volibear | Titanic Hydra, Hollow Radiance, Warmog Armor, Heartsteel, Plated Steelcaps | Titanic Hydra, Hollow Radiance, Warmog Armor, Heartsteel, Overlord Bloodmail, Black Cleaver |
| Warwick | BORK, Gluttonous Greaves, Titanic Hydra, Hollow Radiance, Death Dance | Hubris, Ravenous Hydra, Death Dance, Spirit Visage, BORK, LDR |
| Xayah | Hubris, PD, LDR, The Collector, IE, Gluttonous Greaves, BORK | Hubris, PD, LDR, Yun Tal Wildarrows, IE, Gluttonous Greaves |
| Xerath | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Luden Echo | Liandry Torment, Spellslinger Shoes, Stormsurge, Shadowflame, Blackfire Torch, Rabadon Deathcap |
| XinZhao | Hextech Gunblade, Rabadon Deathcap, Spirit Visage, Nashor Tooth, Zhonya Hourglass, Guinsoo Rageblade | Dusk and Dawn, Rabadon Deathcap, Spirit Visage, Nashor Tooth, Zhonya Hourglass, Guinsoo Rageblade |
| Yasuo | BORK, Immortal Path, The Collector, LDR, Profane Hydra, Guardian Angel | BORK, Hubris, IE, LDR, Ravenous Hydra, Death Dance |
| Yone | BORK, Immortal Path, The Collector, IE, LDR, Ravenous Hydra | Hubris, Mercurial Scimitar, BORK, IE, LDR, Ravenous Hydra |
| Yorick | Titanic Hydra, Plated Steelcaps, Hollow Radiance, Warmog Armor, Heartsteel | Titanic Hydra, Warmog Armor, Dead Man Plate, Hollow Radiance, Heartsteel, Overlord Bloodmail |
| Yunara | Kraken Slayer, PD, BORK, LDR, The Collector, Rapid Firecannon, Gluttonous Greaves | Hubris, PD, BORK, LDR, The Collector, Yun Tal Wildarrows |
| Yuumi | Dream Maker, Luden Echo, Blackfire Torch, Liandry Torment, Cryptbloom, Rabadon Deathcap | Dream Maker, Shadowflame, Blackfire Torch, Liandry Torment, Cryptbloom, Rabadon Deathcap |
| Zaahen | Trinity Force, Ionian Boots of Lucidity, Winter Approach, Manamune, Frozen Heart, Spirit Visage | Hubris, LDR, Endless Hunger, BORK, Death Dance, Trinity Force |
| Zac | Warmog Armor, Sunfire Aegis, Spirit Visage, Gluttonous Greaves, Liandry Torment, Protoplasm Harness | Warmog Armor, Hollow Radiance, Spirit Visage, Dead Man Plate, Liandry Torment, Heartsteel |
| Zed | Umbral Glaive, Swiftmarch, Voltaic Cyclosword, Serylda Grudge, Profane Hydra, Bastionbreaker | Umbral Glaive, Hubris, Youmuu Ghostblade, LDR, Profane Hydra, Bastionbreaker |
| Zeri | The Collector, PD, LDR, IE, Gluttonous Greaves, Umbral Glaive | The Collector, PD, LDR, Gluttonous Greaves, Hubris, IE |
| Zilean | Bloodsong, Sorcerer Shoes, Liandry Torment, Hextech Gunblade, Blackfire Torch, Shadowflame | Solstice Sleigh, Cryptbloom, Liandry Torment, Hextech Gunblade, Blackfire Torch, Shadowflame |
| Zoe | Stormsurge, Spellslinger Shoes, Liandry Torment, Luden Echo, Shadowflame, Lich Bane | Stormsurge, Spellslinger Shoes, Liandry Torment, Rabadon Deathcap, Shadowflame, Lich Bane |
| Zyra | Bloodsong, Sorcerer Shoes, Liandry Torment, Locket of the Iron Solari, Void Staff, Stormsurge | Solstice Sleigh, Shadowflame, Liandry Torment, Cosmic Drive, Void Staff, Stormsurge |
