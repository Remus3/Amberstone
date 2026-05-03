# Arena (2v2v2v2 / Cherry) Meta Research — Patch 26.9

**Compiled:** 2026-05-02
**Authoritative patch:** League of Legends **26.9** (also written as `16.9` on aggregator D; both refer to the same client patch, season 16 / 2026 Split 2)
**Mode internal name:** `CHERRY` (display name: Arena)
**Coverage:** ~140k Arena matches sampled across aggregator C + aggregator J + aggregator B as of fetch time

> Substrate note for RC: the existing `data/meta_build/aram_champion_builds.json` is **not** valid as an arena source. Arena builds are dictated by anvil RNG (Stat Anvil, Prismatic Anvil, Component Anvil), augment level/tier, and round-by-round HP carry. The "full_build" / "core_items" / "vs_*" schema fits SR/ARAM but mis-models arena. This document captures the inputs RC needs to model arena builds correctly.

---

## Arena meta overview

- **Patch 26.9 launched Arena Season 2** (a soft relaunch; mode reintroduced from rotated-status in patch 25.13 and now committed for 12+ months). The patch is the largest single arena update of 2026.
- **Augment-level system is new (26.9):** every augment now has 1–3 levels with keystone effects unlocked at max level. Crafting rounds let you remove augments or gain extra slots. New "Augment Level" item exists. This means a Silver augment can scale into a Gold-equivalent payoff if you keep it through 3 upgrades.
- **Reroll system overhauled (26.9):** moved from a shared pool of 4 to **1 reroll per selection screen**. Players also pick a **gameplay plan** once per game.
- **Shopkeeper's Special:** legendary rounds now feature a guaranteed prismatic offering. "Calculated Risk" augment grants a Prismatic if it's your first or second augment, otherwise it grants Gold.
- **15 new augments** added in 26.9: Chroma Flux, Demonic Clasp, Grievous Venom, Magical Girl, Mercy, Rice and Chicken/Fish/Pork, Scavenger, Silver Spoon, Spellcraft, Transmute: Silver, Trash To Treasure, Unstable Transmutation, Wild Fire. Removed: Snowball Fight, Juice Press, Twin Mask.
- **Pacing slowed slightly (26.9):** augment selection 37 → 42s, item rounds 42 → 47s. Energized stacking nerfed 200% → 150%. Attack speed cap is now 4.0 (breakable via augments). Hats no longer lost on death.
- **Map rotation:** Petricite Grove (new — Demacian outskirts with rolling-bomb hazard), Ancestral Woods (added Power Flowers + Bulwark Blossom — last-hitter gets shield/heal), Koipond (lily-pad trigger radius reduced).
- **Dominant archetype:** **stack-check bruisers** (Cho'Gath, Zaahen, Sett, Vi, Pantheon, Briar, Ambessa). HP-stacking + omnivamp + mid-range engage is the strongest profile because of the small map + augment-driven snowball. Pure ADCs are largely **B/C tier** outside of Xin Zhao who is functionally a bruiser. AP burst (Brand, Ahri, Veigar) is the secondary archetype. Pure squishies and complex enchanters underperform.
- **Recently released champion Zaahen** is the patch standout — 63.7% top-4 rate at 76% ban rate, considered "ticks every box for arena."

---

## Top picks (15)

For each champ: tier, fetched winrate (1st-place WR unless stated), core build path, boots, top augment per tier, situational notes. **All builds reflect highest-WR sample shown by aggregator J on 2026-05-02 for patch 26.9.** Arena builds are anvil-RNG-dependent; treat these as "if items were freely chosen" reference, not strict acquisition order.

### 1. Cho'Gath — S tier (17.7% 1st WR, 30% top-2)
- **Core (highest WR):** Gargoyle Stoneplate → Riftmaker → Heartsteel
- **Situational:** Spirit Visage, Sunfire Aegis, Unending Despair (vs heavy AP / multi-instance burst)
- **Boots:** Mercury's Treads (default; tenacity matters because R is the win-condition)
- **Augments:** Prismatic = **Goliath** (15% HP + 10% adaptive); Gold = **Tank Engine** (size + HP per takedown — synergizes with R stacks); Silver = **Stackosaurus Rex** (75% more permanent stacks)
- **Pairs with:** Galio (40% WR together), Ashe, Xin Zhao
- **Notes:** Banned 39.5% — keep as fallback pick logic. R execute is the load-bearing identity; HP stacking augments compound with feast stacks.

### 2. Zaahen — S tier (top WR overall, 63.7% top-4 at 76% ban)
- **Core (highest WR):** Overlord's Bloodmail → Hemomancer's Helm → Divine Sunderer (20% WR / 2.5 avg)
- **Alt cores:** Divine Sunderer + Sundered Sky (more sustain), Overlord's Bloodmail + Dragonheart (tankier)
- **Boots:** Mercury's Treads
- **Augments:** Prismatic = **Mystic Punch** (on-hit ability CDR); Gold = **Undying Guard** (revive damage + KB); Silver = **The Brutalizer** (AD + haste + lethality)
- **Pairs with:** Yuumi (33% WR), Sion, Brand
- **Notes:** Hemomancer's Helm (arena-only prismatic, omnivamp + AD + haste) is the "want it on every build" anvil pull. If the augment offers AS scaling, swap Sundered Sky → BotRK.

### 3. Shyvana — S tier (50% WR on optimal core / 2.3 avg)
- **Core:** Overlord's Bloodmail → Dragonheart → Riftmaker
- **Situational:** Dusk and Dawn, Heartsteel, Titanic Hydra, Jak'Sho
- **Boots:** Mercury's Treads
- **Augments:** Prismatic = **Goliath**; Gold = **Marksmage** (AP→physical conversion — fits her hybrid scaling); Silver = **Big Dragon Energy** (Shyvana-exclusive, 26.6 patch — full Dragon Fury at combat start + bonus Emberstrike damage)
- **Pairs with:** Veigar (42.9% WR), Smolder, Aurelion Sol
- **Notes:** "Gain a Prismatic Stat Anvil" is selected in 29.3% of her games — this is the universal "skip aggressive item, take stats" pick across most champs but especially impactful on hybrid scalers.

### 4. Vi — S tier (16.9% 1st WR, 31.6% top-2)
- **Core:** Duskblade of Draktharr → Voltaic Cyclosword → The Collector (33.3% WR)
- **Boots:** Plated Steelcaps
- **Augments:** Prismatic = **Jeweled Gauntlet** (her only S-tier augment — ability crit); Silver = **The Brutalizer**; "Gain Prismatic Stat Anvil" 28.6% pick
- **Pairs with:** Yasuo (21.4% WR / 3.0 avg — best duo), Ahri (37.5%), Sett (30.8%)
- **Notes:** Lethality-first build is unusual for Vi but optimal in arena because of the small map + R-as-execute; Duskblade procs are easier in 2v2.

### 5. Sett — S tier (16.9% 1st WR, highest pick rate top-tier at 22.3%)
- **Core (60% WR / 1.4 avg):** Overlord's Bloodmail → Warmog's Armor → Stridebreaker
- **Alt:** Overlord's Bloodmail → Dragonheart → Demon King's Crown; or Black Hole Gauntlet → Overlord's Bloodmail → Dragonheart
- **Situational:** Death's Dance, Goredrinker, Heartsteel
- **Boots:** Mercury's Treads
- **Augments:** Prismatic = **Goliath**; Gold = **Tank Engine**; "Prismatic Stat Anvil" 29.9%
- **Pairs with:** Shyvana, Xin Zhao, Zaahen (brawl synergy)
- **Notes:** Banned 52.9% — top 3 ban target. R is round-deciding when paired with engage partner.

### 6. Olaf — A tier (15.4% 1st WR, 57.9% top-4)
- **Core:** Hamstringer → Blade of The Ruined King → Ravenous Hydra (33.3% WR)
- **Boots:** Gluttonous Greaves (omnivamp boots — strong pickup on perma-uptime champs)
- **Augments:** Prismatic = **Tap Dancer**; Gold = **Lightning Strikes**; "Prismatic Stat Anvil" 30.9%
- **Pairs with:** Ryze (41.7% WR), Fizz, Veigar
- **Notes:** Hamstringer (arena anvil) replaces Stridebreaker in his SR build — slow + AS scaling on a single item.

### 7. Pantheon — A tier (14.7% 1st WR, 27.3% top-2)
- **Core:** Flesheater → Duskblade of Draktharr → Eclipse (33.3% WR)
- **Boots:** Plated Steelcaps
- **Augments:** Prismatic = dash-amplifier (Dashing or Blade Waltz); "Prismatic Stat Anvil" 26.8%
- **Pairs with:** Xin Zhao, Singed (28.6%), Briar
- **Notes:** Flesheater (arena) was buffed in 26.9 to steal multiple stats per kill — synergizes with Pantheon's reliable kill-secure via Q.

### 8. Ambessa — A tier (15.4% 1st WR, 53.5% top-4)
- **Core:** Divine Sunderer → Voltaic Cyclosword → Eclipse (18.2% WR)
- **Alt (28.6% WR):** Regicide → Hemomancer's Helm → Voltaic Cyclosword
- **Boots:** Ionian Boots of Lucidity (primary) / Gluttonous Greaves (alt build)
- **Augments:** Prismatic = **Earthwake** (15.5% pick); Gold = **Outlaw's Grit** (22.4% pick); "Prismatic Stat Anvil" 28.6%
- **Pairs with:** Zaahen (33.3%) — duo of patch
- **Notes:** Banned 25.8%. Hemomancer's Helm appears again — universal AD-bruiser anvil pull.

### 9. Amumu — A tier (15.1% 1st WR, 50.9% top-4)
- **Core:** Pyromancer's Cloak → Liandry's Anguish → Malignance (50% WR)
- **Boots:** Mercury's Treads
- **Augments:** Prismatic = **Dreadbringer**; Gold = **Tank Engine**; "Prismatic Stat Anvil" 26.6%
- **Pairs with:** **Aurelion Sol (73.3% WR / 1.7 avg — strongest duo in dataset)**, Ahri, Shyvana
- **Notes:** Pyromancer's Cloak (arena) is now a near-mandatory AP-bruiser anvil — burn item + utility, drives the entire build.

### 10. Briar — S tier (16.3% 1st WR, 57.2% top-4)
- **Core:** Hemomancer's Helm → Death's Dance → Blade of The Ruined King (22.2% WR / 3.3 avg)
- **Boots:** Mercury's Treads
- **Augments:** Prismatic = **Mystic Punch** (on-hit CDR — premium for her ability spam); Gold = "Symphony of War" / "Augment Slot"; "Prismatic Stat Anvil" 29.0%
- **Pairs with:** Shyvana (29.4%), Sion, Mordekaiser
- **Notes:** 7.5/7.2/5.8 avg KDA — she trades aggressively. Death's Dance + Hemomancer compounds the omnivamp profile.

### 11. Xin Zhao — S tier (19.6% 1st WR — highest single-champion 1st rate among non-Zaahen)
- **Core:** Moonflair Spellblade → Blade of The Ruined King → Guinsoo's Rageblade
  - aggregator D shows alternate hyperbuild: **Dusk and Dawn + Nashor's Tooth + Guinsoo's Rageblade** with 88.7% 1st rate when paired with a Prismatic item
- **Boots:** Gluttonous Greaves
- **Augments:** Prismatic = **Dual Wield** (12% pick — fires secondary bolts that apply on-hit); Gold = "Twice Thrice" / "Lightning Strikes"; "Prismatic Stat Anvil" 26.1%
- **Best Prismatic items for him:** Reverberation (82.92% WR), Moonflair Spellblade (78.72% WR)
- **Pairs with:** Mordekaiser (31.6% WR / 2.6 avg, +12% over solo)
- **Notes:** Functions as bruiser-AS hybrid. Moonflair (CC + AP + ability haste) is unusual on him but the data is overwhelming — it's the `must-pick` Prismatic for him.

### 12. Tryndamere — C tier despite top-list pick rate (12.8% 1st WR)
- **Core:** Reaper's Toll → Blade of The Ruined King → Bloodthirster (16.7% WR / 3.0 avg)
- **Boots:** Berserker's Greaves
- **Augments:** Prismatic = **Dual Wield**; Gold = **Aim for the Head** (excess crit → damage); S-tier specific = **Compulsion For Power**; "Prismatic Stat Anvil" 28.2%
- **Pairs with:** Morgana (33.3%)
- **Notes:** Mediocre solo (4.3 avg) but has the highest ceiling with the right augment combo. Reaper's Toll (arena prismatic) is his namesake item — % max-HP stacking damage that fits R-tank scaling perfectly.

### 13. Ahri — C tier (13.5% 1st WR despite 11% pick rate)
- **Core:** Pyromancer's Cloak → Runecarver → Liandry's Anguish
- **Boots:** Gluttonous Greaves (omnivamp on a burst mage is unusual but data-supported)
- **Augments:** Prismatic = **Jeweled Gauntlet**; Gold = **Phenomenal Evil** (stacking AP); "Prismatic Stat Anvil" 28.1%
- **Pairs with:** Jax (15.4% WR / 2.5 avg — top), Amumu (41.7%)
- **Notes:** Burn-mage build, not the SR Luden's path. Runecarver (arena) is the anti-shield AP item that makes her R + E lethal vs tanks.

### 14. Yasuo — D tier despite 16.4% pick rate (10.5% 1st WR)
- **Core:** Hamstringer → Sword of the Divine → Blade of The Ruined King (33.3% WR)
- **Boots:** Berserker's Greaves
- **Augments:** Prismatic = **Dual Wield**; "Prismatic Stat Anvil" 27.4%
- **Pairs with:** Vi (21.4% WR / 3.0 avg, +10.9% over solo)
- **Notes:** Skewed by player base (he's first-timed often). Sword of the Divine (component anvil item) replaces IE in arena because crit takes too long to assemble from scratch.

### 15. Brand — A tier (15.5% 1st WR, 30.4% top-2)
- **Core:** Pyromancer's Cloak → Dragonheart → Liandry's Anguish (60% WR / 2.2 avg — one of the highest-WR cores in the dataset)
- **Boots:** Sorcerer's Shoes
- **Augments:** Prismatic = **Infernal Conduit**; Gold = **Magic Missile**; "Prismatic Stat Anvil" 27.7%
- **Pairs with:** Xin Zhao (28.6%), Tahm Kench (28.6%), Nautilus (22.2%)
- **Notes:** Banned 24.5%. Dragonheart on a mage is the arena-specific tweak — makes him the "frontline-mage" archetype that's hard to focus.

### Honourable mentions (from aggregator B / aggregator C top-20)
- **Malphite** B tier (13.7% 1st WR) — Black Hole Gauntlet → Shield of Molten Stone → Heartsteel; Plated Steelcaps; Prismatic = Goliath; Gold = Tank Engine
- **Yorick** D tier (10.5% 1st) — Minionmancer (S-augment) is build-defining; pair with Ashe/Malzahar/Yone
- **Yone** D tier (11.0% 1st) — Hamstringer → Kraken Slayer → Blade of The Ruined King; Berserker's Greaves
- **Sylas** D tier (10.9% 1st) — Runecarver → Rod of Ages → Riftmaker; Sorcerer's Shoes; Prismatic = Dashing
- **Zyra / Amumu / Yorick clusters** — mage/summoner archetypes that hard-scale with one specific augment (Minionmancer for Yorick, Dreadbringer for Amumu, Infernal Conduit for Brand).

---

## Arena-specific items reference

Arena items only appear via **anvils** (Component, Stat, Prismatic). They cannot be bought from the shop directly. Coaches must treat anvil-pull as *which option do I pick* rather than *what do I save gold for*.

### Confirmed Prismatic items currently in pool (patch 26.9, partial — wiki shows ~50 total)
| Item | Stat profile | Best users |
|---|---|---|
| **Hemomancer's Helm** | 60 AD / 30 haste / 10% omnivamp | AD bruisers (Zaahen, Briar, Ambessa) — universal pickup |
| **Reaper's Toll** | 40 adaptive / 50% AS / 10% MS, % max-HP stacking damage | AS bruisers / juggernauts (Tryndamere, Olaf) |
| **Pyromancer's Cloak** | AP + burn passive | AP bruisers / mages (Amumu, Brand, Ahri) — universal AP pickup |
| **Overlord's Bloodmail** | HP + AD + sustain | Tank-bruisers (Sett, Shyvana, Zaahen) — universal HP pickup |
| **Dragonheart** | HP + resists + sustain | Frontline (Sett, Brand, Shyvana, Ambessa) |
| **Moonflair Spellblade** | AP + CC haste + spellblade | Hybrids w/ AS scaling (Xin Zhao top user) |
| **Reverberation** | AOE-trigger Prismatic | AS carries (Xin Zhao 82.9% WR with it) |
| **Black Hole Gauntlet** | Tank + AP + pull active | Engage tanks (Malphite, Sett alt) |
| **Crown of the Shattered Queen** | Damage-reduction shield (buffed 26.7) | Squishy mages |
| **Dusk and Dawn** | AS + AP scaling | AS hybrids (Xin Zhao alt build) |
| **Decapitator** | AD + ult haste (baseline ult-haste added 26.9) | Ult-reset champs |
| **Demon King's Crown** | Tank + soul mechanic | Sett alt, frontline |
| **Diamond-Tipped Spear** | AD + range | ADCs that need range |
| **Divine Sunderer** | AD + spellblade + sustain (spellblade ratios buffed 26.9) | Ambessa, Zaahen |
| **Demonic Embrace** | AP + HP burn | AP bruisers |
| **Cruelty / Cloak of Starry Night / Darksteel Talons** | Variable | Niche builds |

### Confirmed Component / Stat anvil items
| Item | Notes |
|---|---|
| **Hamstringer** | AD + AS + slow on hit. Replaces Stridebreaker for Olaf/Yasuo/Yone. |
| **Flesheater** | AD + sustain; **patch 26.9 buffed to steal multiple stats per kill** (was single-stat) |
| **Shardblade** | NEW 26.9 — lets you obtain multiple Stat Shards simultaneously |
| **Bami's Cinder** | NEW 26.9 — HP + haste + immolate; granted by new "Upgrade Immolate" augment |
| **Hexblot Companion** | New/reworked 26.9 — pet that scales |
| **Kinkou Jutte** | New/reworked 26.9 — Akali-flavoured AS+AP |
| **Sword of the Divine** | Component anvil; replaces IE-line for crit champs (Yasuo) |
| **Runecarver** | AP + anti-shield (Sylas, Ahri vs tanks) |
| **Sundered Sky** | Crit-strike sustain (Zaahen alt build) |
| **Shield of Molten Stone** | HP + immolate (Malphite) |

### Anvil RNG model for the coach
- **Component anvil:** 3 random component items (build pieces); appears every couple rounds.
- **Stat anvil:** 3 random stat-shard offerings (AD, AP, HP, etc).
- **Prismatic anvil (Shopkeeper's Special):** 4000g, randomized choice from full Prismatic pool, guaranteed in legendary rounds in 26.9.
- The build "core 3" listed for each champ above is *aspirational* — actual round-by-round acquisition is what's offered. The coach should rank-order items by champion-fit, not enforce SR-style item completion order.

---

## Universal anti-X reference

### AD anti-heal (Grievous Wounds 40% reduction, scaling to 60% under conditions)
| Item | Cost | Stats | Trigger |
|---|---|---|---|
| **Executioner's Calling** | 800g | 15 AD | GW on any physical damage |
| **Mortal Reminder** | 3300g | 40 AD / 25% crit / 35% armor pen | GW; **scales to 60% when target heals while afflicted** |
| **Chempunk Chainsword** | 3100g | 45 AD / 450 HP / 15 haste | **60% GW below 50% target HP** (the late-fight threshold) |

### AP anti-heal
| Item | Cost | Stats | Trigger |
|---|---|---|---|
| **Oblivion Orb** | 800g | 30 AP | GW on any magic damage |
| **Morellonomicon** | 2950g | 90 AP / 15 haste / 200 HP | **80% GW when target heals 60% max-HP under debuff** (the Soraka/Vlad late-stack threshold) |

### Tank anti-heal
| Item | Cost | Stats | Trigger |
|---|---|---|---|
| **Bramble Vest** | 800g | 30 armor | GW on basic-attacks-received |
| **Thornmail** | 2900g | 80 armor / 250 HP | GW on basic-attacks-received + on-CC-applied (immobilization trigger) |

### Anti-tank %max-HP (AD)
- **Reaper's Toll** (arena prismatic) — stacking %max-HP damage on Reap proc
- **Blade of The Ruined King** — on-hit %current-HP, the standard pick across all top AD bruisers in this dataset
- **Ravenous Hydra** / **Titanic Hydra** — flat HP-scaling cleave; appear on Olaf, Cho'Gath
- **Liandry's Anguish** — counted as anti-tank because of %max-HP burn (used by Brand, Ahri, Amumu builds in this dataset)

### Magic pen (AP)
- **Sorcerer's Shoes** (Brand, Sylas)
- **Malignance** (Amumu) — magic pen + ult-haste
- **Liandry's Anguish** — magic pen + burn (the universal "vs anything" AP pickup)
- **Cryptbloom** — flat magic pen, healing-on-takedown

### Notes for arena specifically
- Spirit Visage **does not carry GW reduction** in 2026. The "Spirit Visage counters anti-heal" mythos is from older patches. (Per dodge.gg 2026 anti-heal guide.)
- Arena's omnivamp meta means GW is more impactful than in SR — every top-10 AD champion above runs an omnivamp item (Hemomancer's Helm, Ravenous Hydra, BotRK, Bloodthirster, Death's Dance, Gluttonous Greaves). Coach should rate GW-anvils much higher in arena than in SR.

---

## Augment-build interaction notes

These are the augments that **fundamentally change which items to pick** when offered. Coach should detect these on augment-pick frame and re-route the item recommendation logic.

1. **Dual Wield** (Prismatic) — fires secondary bolts that apply on-hit. Pushes any non-on-hit champ toward Kraken Slayer / Wit's End / BotRK / Guinsoo's. Top users: Xin Zhao, Yasuo, Yone, Tryndamere.

2. **Mystic Punch** (Prismatic) — on-hit ability cooldown reduction. Pushes ability-spam bruisers (Briar, Zaahen) toward Nashor's Tooth / Guinsoo's / BotRK. Useless without an AS source.

3. **ADAPt** (Prismatic) — convert all bonus AD into AP at 2.22 ratio. **Total build inversion** — AD champ should now buy AP items (Rabadon's, Riftmaker, Liandry's). Caster doesn't usually take it but it's a known "go AP Yone/Sett" enabler.

4. **Marksmage** (Gold) — converts AP into physical damage at 75% AP ratio. Inverse of ADAPt. Pushes AP champs (Sylas-mentioned alt; Shyvana) into AP items but with the damage hitting as physical (so Last Whisper / armor pen scales).

5. **Jeweled Gauntlet** (Prismatic) — abilities can crit. Top pick for AP carries (Ahri, Veigar, LeBlanc). Pushes toward IE-equivalent crit items (Storm Surge / Shadowflame for crit-damage stacking) instead of normal AP items.

6. **Goliath** (Prismatic) — 15% HP + 10% adaptive force. Doesn't change item path but **stacks multiplicatively with HP items** (Heartsteel, Warmog's, Overlord's Bloodmail). Always bias toward more HP items when this is taken. Top pick for Cho'Gath, Sett, Shyvana, Malphite.

7. **Tank Engine** (Gold) — bonus size + HP per takedown. Same family as Goliath — bias HP items, plus enables W/Q-engage range increases on certain champs (Cho'Gath silence, Malphite ult). Top pick for tanks.

8. **Big Dragon Energy** (Gold, Shyvana-only, added 26.06) — full Dragon Fury at combat start + enhanced Emberstrike. Build-defining for Shyvana — pushes her from hybrid into AP-burn build (Demonic Embrace, Liandry's, Riftmaker).

9. **Minionmancer** (S-tier, Yorick-defining) — 35% increased size/HP/damage on summons. Pushes Yorick toward HP/AD items that buff Maiden too (Trinity Force, Sundered Sky, Stridebreaker). Without this Yorick is C/D tier; with it he's S-tier.

10. **Aim for the Head** (Gold, Tryndamere/crit-defining) — converts excess crit-chance over 100% into bonus crit damage. Pushes hard into stacking crit items (IE → PD → Mortal Reminder → Bloodthirster). Caps the "100% crit then stop" SR rule.

11. **Dashing** (Prismatic) — 200–350 ability haste on dash/blink abilities. Pushes dash-heavy champs (Sylas, LeBlanc, Pantheon — alt) toward haste items (Cosmic Drive, Black Cleaver) over raw damage.

12. **Earthwake** (Prismatic, Ambessa-favoured) — terrain-based AOE on movement abilities. Pushes Ambessa toward mobility items (Phantom Dancer/Trinity Force/Stridebreaker) to maximize triggers.

13. **Calculated Risk** (NEW 26.9 utility augment) — first/second pick gives Prismatic, otherwise Gold. **Coach should detect pick order and surface this as a "snake-pick early" reminder** — taking it round 4+ is a trap.

14. **Spellcraft** (NEW 26.9) — multi-tier upgrade-on-cast augment. Combos with Chroma Flux which auto-casts Essence Flux on stacks. AP combo pattern.

15. **Demonic Clasp** (NEW 26.9) — replaces Flee with multi-claw pull (1–5 based on level). Engage augment — pushes any squishy ranged champ into bruiser-pivot itemization (Hemomancer's, Riftmaker, Hexdrinker).

---

## Sources (URLs fetched 2026-05-02)

| Source | URL | Status |
|---|---|---|
| Aggregator C tier list (top 20 + duos) | https://aggregator-c.invalid/lol/tier-list/arena-champions | OK |
| aggregator B arena tier list (header / patch only) | https://aggregator-b.invalid/lol/arena-tier-list | partial — header only |
| Riot 26.9 patch notes (arena section) | https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-9-notes/ | OK |
| LoL Wiki Arena patch history | https://wiki.leagueoflegends.com/en-us/Arena/Patch_history | OK |
| LoL Wiki Arena Augments | https://wiki.leagueoflegends.com/en-us/Arena/Augments | OK |
| LoL Wiki Prismatic Item index | https://wiki.leagueoflegends.com/en-us/Prismatic_Item | partial — list only, no descriptions |
| esports.net 2026 arena guide | https://www.esports.net/wiki/guides/lol-arena-tier-list/ | OK |
| dodge.gg 2026 anti-heal guide | https://www.dodge.gg/en-US/lol/news/anti-heal-items-2026 | OK |
| aggregator J per-champ (Cho'Gath, Zaahen, Shyvana, Vi, Sett, Xin Zhao, Olaf, Pantheon, Ambessa, Amumu, Briar, Tryndamere, Ahri, Yasuo, Brand, Malphite, Yorick, Yone, Sylas) | https://aggregator-j.invalid/en/league/champion/{Champ}/arena | OK for all 19 |
| aggregator A arena landing (Xin Zhao Prismatic-item win-rates) | https://aggregator-a.invalid/lol/modes/arena | OK |
| altchar 26.9 arena summary | https://www.altchar.com/game-news/league-of-legends-patch-26.9-updates-arena-with-new-augments-map-and-faster-pacing-aujkk9t1VF9M | OK |

### Sources that failed / blocked
| Source | URL | Failure |
|---|---|---|
| aggregator N tier list | https://aggregator-n.invalid/lol/arena/tier-list | HTTP 402 (paywalled fetch) |
| aggregator N augment tier list | https://aggregator-n.invalid/lol/arena/tier-list/augments | HTTP 402 |
| aggregator D arena tier list | https://aggregator-d.invalid/lol/tierlist/arena/ | HTTP 403 |
| overlay app E arena augments | https://overlay-app-e.invalid/lol/arena-augments | HTTP 403 |
| Fandom wiki Arena root + Augments | https://leagueoflegends.fandom.com/wiki/Arena_(League_of_Legends) | HTTP 403 |

(LoG was not attempted per project memo — confirmed-403-on-automated.)

---

## Substrate recommendations for RC wire-in (informational, not action)

If RC's arena coach wants a JSON schema that matches arena reality, the per-champion record needs at minimum:
- `tier` (S+/S/A/B/C/D from aggregator C or aggregator J)
- `wr_first` (1st-place WR), `wr_top4`, `pickrate`, `banrate`
- `ideal_core` (3 items, ranked) — for "if I see this in component anvil, take it" logic
- `prismatic_priority` (ordered list, with named exceptions like Xin Zhao→Reverberation/Moonflair)
- `boots` (default + alt with condition)
- `top_augment_per_tier` (Prismatic / Gold / Silver)
- `build_changing_augments` (list of names from §5 above) — when picked, swap recommendation logic
- `best_duos` (top 3 with WR delta)
- `kit_notes` (one line — e.g. "R execute is win-condition, prioritize haste")

The current `aram_champion_builds.json` `full_build` / `vs_tanks` / `vs_healing` / `vs_burst` schema can be **partially reused** but the `_against_` slots map poorly — arena's enemies rotate every 1–2 rounds across 3–6 different teams, so "vs healing" should become "vs healing-anvil-pull-priority" (which GW item to favour from a stat anvil). Treat it as item-priority weights, not a fixed alternate build.
