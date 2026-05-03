# SR Itemization Changes — Patch 26.8 → 26.9.1 (16.8 → 16.9.1)

**Compiled:** 2026-05-02
**Patch range covered:** 26.8 (prior baseline; matches RC's 2026-04-18 build data) → 26.9 / 26.9.1 (current live)
**Scope:** Summoner's Rift Ranked Solo/Duo item-level changes only. No champion balance, no rune changes, no Arena.
**Caveat:** Riot's official patch URLs use the `26-9` slug (calendar / season-2 numbering). The user-facing "16.9" / Season 16 framing is the same patch.

---

## Mythic system status

**Mythic items DO NOT exist as a category in 2026.**

Per [pcgamer / Dexerto coverage of patch 14.1 removal](https://www.pcgamer.com/league-of-legends-is-ditching-mythic-items-and-players-are-happy-to-see-them-go-the-only-sad-part-was-that-it-took-3-years-of-asking/) and the [Wiki Mythic item entry](https://leagueoflegends.fandom.com/wiki/Mythic_item) (fetched 2026-05-02): Riot removed the entire mythic classification in patch 14.1, converting every former mythic into a Legendary item and removing the one-mythic-per-build restriction. There is no "Mythic slot first" structure to enforce in 2026 — build paths should treat all Legendaries as freely combinable. RC's build data should NOT carry a mythic-first ordering hint.

Confirmed independently in [aussyelo's 2026 items guide](https://www.aussyelo.com/blog/lol-items-guide). The 2026 preseason (patch 26.1, 2026-01-08) was a further restructure that introduced role-quest boots upgrades but did NOT reintroduce a Mythic tier.

---

## Item additions (patch 26.9)

| Item | Role / class | When | Source |
|---|---|---|---|
| **Doran's Bow** | Starter — 6 AD, 12–15% AS, 1.5% omnivamp, 400g (limited 1). Aggressive AA-trade starter for Vayne / Kog'Maw / Kalista. | 26.9 | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09), [riftpatchnotes 26.9](https://www.riftpatchnotes.com/lol/patch/26-9) |
| **Doran's Helm** | Starter — 100–110 HP, 10 armor, 10 MR, 450g (limited 1). Unique passive *Helping Hand*: +5 on-hit physical vs minions. Tank/bruiser top starter. | 26.9 | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |
| **Gluttonous Greaves** | T2 boots — 45 MS, 4% omnivamp, 950g (Boots + 650). Unique *Slay*: +1% omnivamp per champ takedown, max 6%. (Limited 1 boots item — competes with Berserker's / Steelcaps / Mercs / Sorcs / Ionian.) | 26.9 | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09), [riftpatchnotes 26.9](https://www.riftpatchnotes.com/lol/patch/26-9) |
| **Immortal Path** | T3 boots upgrade from Gluttonous Greaves via mid-lane role quest. 45 MS, 4% omnivamp. Adds *Now and Forever*: above 50% HP deal +5% damage; below 50% HP gain +15% heal/shield/regen. | 26.9 | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |

**NOT an SR addition:** Shardblade and the new Bami's Cinder variant (with 12s CD, 1% bonus-HP scaling, immobilize-triggered fire nova) are **Arena-only** in 26.9 per [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) — Arena research already captured these. Do not add to SR build data.

---

## Item removals (patch 26.9)

| Item | Was used by | Replacement / what to migrate to | Source |
|---|---|---|---|
| **Opportunity** | Lethality assassins (Zed, Talon, Qiyana, Akali AD, Naafiri, Pyke, sometimes ADC bursts on Jhin/MF) | Hubris, Voltaic Cyclosword, Serylda's Grudge, Edge of Night, Youmuu's. No 1:1 replacement — the lethality/MS-burst niche folds into Voltaic Cyclosword (now energized-on-ability) and Hubris. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09), [riftpatchnotes 26.9](https://www.riftpatchnotes.com/lol/patch/26-9) |
| **Trailblazer** (a.k.a. "Trailblade" in some sources) | Jungle clear / smite item slot | Other jungle items remain; check live items_index.json for current jungle starter set. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |

**Action for RC:** scan `data/meta_build/sr_champion_builds.json` for `Opportunity` and `Trailblazer` (and the alt spelling `Trailblade`) and either drop those entries or remap the Opportunity slots to **Voltaic Cyclosword** (closest functional replacement — lethality + energized burst) or **Hubris** (lethality + snowball AD).

---

## Item reworks (patch 26.9)

| Item | Before (26.8) | After (26.9) | Affects | Source |
|---|---|---|---|---|
| **Statikk Shiv** | Recipe Scout's Slingshot + Rectrix + Pickaxe + 450g = 2700g. 45 AD / 30% AS / 4% MS. Waveclear-focused chain lightning. | Recipe Scout's Slingshot + Pickaxe + **Aether Wisp** + 625g = 3000g. 40 AD / **45 AP** / 30% AS / 4% MS. Reworked *Electrospark* — chain lightning bounces 4–8 targets by level AND **applies on-hit effects to secondary targets**. (Now an on-hit AP/AD hybrid scaling item, not pure waveclear.) | Kai'Sa, Varus on-hit, Twitch, Vayne, Kog'Maw, Yasuo crit-on-hit, Yone — anyone who used Shiv for waveclear OR wants on-hit chain. AP component opens it for hybrids (Kai'Sa especially). | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09), [riftpatchnotes 26.9](https://www.riftpatchnotes.com/lol/patch/26-9) |
| **Voltaic Cyclosword** | 3000g. 18 lethality. Energized-on-AA *Firmament* slow + bonus damage. | **2900g** (combine 963 → 863). **10 lethality**. New *Galvanize*: damaging enemy champs **with abilities** triggers Energized effects. Reworked *Firmament*: grants lethality + current-HP bonus damage (melee 15 leth / 9% HP, ranged 12 / 7%). | Lethality bruisers and assassins (Hecarim, Sett-AD, Pyke, Talon, Jax-lethality builds). Now triggers off ability damage, not just AAs — ability-heavy lethality kits gain. Lethality cut means it's a worse pure-lethality stick — supplement with Hubris/Serylda's. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |
| **Dusk and Dawn** | 350 HP, 70 AP, 25% AS. (No spellblade healing.) | **300 HP, 60 AP, 20% AS**. Adds Spellblade heal: 10% AP + 3% bonus HP per spellblade trigger. | Hybrid spellblade users in support/jungle slots that build it. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09), [riftpatchnotes 26.9](https://www.riftpatchnotes.com/lol/patch/26-9) |
| **Staff of Flowing Water** | 15 ability haste, *Rapids* gives MS + 45 AP. | **10 ability haste**. *Rapids* now gives **15 AH** + 40 AP (MS removed, AH re-added inline). | Enchanter supports (Soraka, Sona, Lulu, Karma, Janna, Yuumi). | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |
| **Hubris** | 60 AD, *Eminence* +15 base AD + 2 AD per stack. | **55 AD**, *Eminence* **+12 base AD + 3 AD per stack**. | Lethality snowballers (Talon, Zed, Kha'Zix, Qiyana, Naafiri). Better with stacks, worse on first buy — push for fed games. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |
| **Axiom Arc** | *Flux*: takedown refunds 15% (+0.15% per lethality) of ult CD. | *Flux*: takedown refunds **10% (+0.25% per lethality)** of ult CD. | Lethality ult-reset assassins (Talon, Kha'Zix, Pyke). High-lethality stacks scale better; low-lethality builds get less refund. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |
| **Endless Hunger** | *Famine*: 5 AH + 10% bonus AD ratio AH for all. | *Famine*: 5 AH + **13% bonus AD ratio for melee, 10% for ranged**. | Melee bruiser Jak'Sho-tier users — small buff. | [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) |

**No reworks this patch** for: Cosmic Drive, Decapitator, Essence Reaver, Flesheater on SR. Those reworks exist but are **Arena-only** in 26.9 per [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09). Do not propagate the Arena rework details to SR build data.

---

## Boots changes (patch 26.9)

Per [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09) and [riftpatchnotes 26.9](https://www.riftpatchnotes.com/lol/patch/26-9), no stat changes to **Berserker's Greaves, Plated Steelcaps, Mercury's Treads, Sorcerer's Shoes, Ionian Boots of Lucidity, Boots of Swiftness, Boots of Mobility, Synchronized Souls** in 26.9.

What did change:
- **Gluttonous Greaves** — new T2 boots option (see additions). Counts against the "limited 1 boots item" cap.
- **Immortal Path** — new T3 mid-lane role-quest upgrade (see additions).
- The patch 26.1 role-quest tier-3 boots system (per [aussyelo 2026 items guide](https://www.aussyelo.com/blog/lol-items-guide)) remains active. Each role unlocks a T3 boot via quest; this patch added Immortal Path as the mid-lane variant of Gluttonous Greaves.

---

## Anti-X reference (current state, fetched 2026-05-02)

> No anti-heal or anti-tank items received explicit changes in 26.9 per [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09). Costs/effects below carry forward from 26.8 baseline. **Spirit Visage carrying no anti-heal interaction** is consistent — Spirit Visage is a self-heal-amp item, not an anti-heal item, and has not been an anti-heal source in the modern patch system.

### Grievous Wounds — AD side
| Item | Cost | Notes |
|---|---|---|
| Executioner's Calling | ~800g | Component anti-heal, cheap rush |
| Bramble Vest | ~1100g | Anti-heal on incoming AAs (armor item) |
| Mortal Reminder | ~3000g | Full crit/AS Grievous Wounds for ADCs |
| Chempunk Chainsword | ~3000g | AD bruiser/fighter Grievous Wounds (HP + AD) |
| Thornmail | ~2700g | Tank Grievous Wounds (armor + HP, reflect) |

### Grievous Wounds — AP side
| Item | Cost | Notes |
|---|---|---|
| Oblivion Orb | ~800g | Component anti-heal |
| Morellonomicon | ~2200–2500g | Mage anti-heal completed item |

### % Armor Penetration
| Item | Cost | Notes |
|---|---|---|
| Lord Dominik's Regards | ~3000g | 35% armor pen + crit/AD (ADC anti-tank) |
| Black Cleaver | ~3000g | Stack-based armor shred (bruiser anti-tank) |
| Terminus | ~3000g | On-hit % pen ramp (on-hit ranged anti-tank) |
| Serylda's Grudge | ~3200g | % armor pen for lethality/AD casters |
| Botrk (Blade of the Ruined King) | ~3300g | % current-HP on-hit (ranged AA anti-tank) |

### Magic Penetration
| Item | Cost | Notes |
|---|---|---|
| Sorcerer's Shoes | ~1100g | Flat magic pen (boots) |
| Void Staff | ~3000g | % magic pen completion |
| Cryptbloom | ~2850g | % magic pen + healing aura mage utility |
| Liandry's Anguish (Torment) | ~3000g | %-HP burn vs tanks (mage anti-tank) |
| Demonic Embrace | ~2700g | %-HP burn (HP-stacking AP bruiser anti-tank) |
| Shadowflame | ~3000g | Magic pen + low-HP burst spike |

> Riftpatchnotes / Wiki V26.09 do NOT show modifications to the items above this patch. If RC's build data references costs differing from the table, prefer items_index.json as the live truth.

---

## Component changes (patch 26.9)

Per [Wiki V26.09](https://wiki.leagueoflegends.com/en-us/V26.09):

| Component | Change |
|---|---|
| **Aether Wisp** | Now builds into **Statikk Shiv** (it didn't before). Recipe path shift only — no stat change. |
| **Rectrix** | **No longer builds into Statikk Shiv**. Other recipes unchanged. |
| **Scout's Slingshot, Pickaxe, B.F. Sword, Long Sword, Recurve Bow, Cloak of Agility, Needlessly Large Rod, Lost Chapter** | No changes in 26.9. |

---

## Per-champion build implications (top 5 with shifts in 26.9)

1. **Lethality assassins as a class** (Talon, Zed, Qiyana, Naafiri, Pyke, Kha'Zix) — **Opportunity removed**. Replace first-item-Opportunity templates with Voltaic Cyclosword (now ability-triggered Energized — synergy way up for ability-heavy kits) or Hubris (better stack-scaling, weaker first-buy).
2. **Kai'Sa / Varus on-hit / Twitch** — **Statikk Shiv now hybrid AD/AP with on-hit chain** (40 AD + 45 AP + applies on-hits to secondary targets). For Kai'Sa specifically the AP scaling and on-hit chain make it a stronger second/third item slot than 26.8.
3. **Hecarim / Sett-AD / lethality bruisers** — **Voltaic Cyclosword reworked** to ability-trigger. Hecarim (Q-heavy) and Sett (W/E-heavy) get more reliable Energized procs than 26.8's AA-only model. Lethality cut (18→10) means pair with Serylda's/Hubris.
4. **Aggressive AA bot-laners** (Vayne, Kog'Maw, Kalista) — **Doran's Bow** is the new 400g aggressive starter (6 AD / ~12% AS / 1.5% omnivamp). Replace Doran's Blade entries in opening-buy templates for these picks per riftpatchnotes guidance.
5. **Mid-lane mages who quest into T3 boots** — new **Immortal Path** option (Gluttonous Greaves upgrade). Above-50%-HP +5% damage / below-50%-HP +15% heal-shield-regen. Strong on bruiser-mages (Akali, Sylas, Vladimir) and on Vlad/Cassio sustain mages. Worth adding to mid-lane T3 boots option set.

---

## Sources fetched

| URL | Fetched | Notes |
|---|---|---|
| https://wiki.leagueoflegends.com/en-us/V26.09 | 2026-05-02 | **Primary** — exhaustive item change list with before/after stats and recipes. |
| https://www.riftpatchnotes.com/lol/patch/26-9 | 2026-05-02 | Confirmed SR-specific changes; matched Wiki numbers. |
| https://wiki.leagueoflegends.com/en-us/V26.08 | 2026-05-02 | Baseline — only ARAM tweaks + 1 SoFW tooltip fix; confirms 26.9 carries all the SR item motion. |
| https://www.leagueoflegends.com/en-us/news/game-updates/league-of-legends-patch-26-9-notes/ | 2026-05-02 | Official Riot notes (URL slug is `26-9`, NOT `16-9`). |
| https://www.aussyelo.com/blog/lol-items-guide | 2026-05-02 | 2026 itemization overview; confirmed Mythic system absent and 26.1 role-quest T3 boots framework. |
| https://www.pcgamer.com/league-of-legends-is-ditching-mythic-items-and-players-are-happy-to-see-them-go-the-only-sad-part-was-that-it-took-3-years-of-asking/ | 2026-05-02 | Mythic removal confirmation (V14.1, historical). |
| https://leagueoflegends.fandom.com/wiki/Mythic_item | 2026-05-02 | Mythic page snapshot — confirms classification removed. |
| https://www.leagueoflegends.com/en-us/news/game-updates/patch-notes/lol-patch-16-9-notes/ | 2026-05-02 | **404 — wrong slug.** Use `/league-of-legends-patch-26-9-notes/` instead. |
| https://www.leagueoflegends.com/en-us/news/game-updates/patch-notes/lol-patch-16-8-notes/ | 2026-05-02 | **404 — wrong slug.** Riot uses `26-x` URL pattern. |
| https://escorenews.com/en/lol/article/77440-all-new-and-changed-items-from-season-2-patch-26-9-16-9-pbe-in-league-of-legends | 2026-05-02 | **403 blocked** — used WebSearch summary excerpt instead. |
| https://www.sportskeeda.com/esports/all-system-changes-league-legends-patch-26-9-notes-runes-items | 2026-05-02 | **405 blocked** — covered by Wiki + riftpatchnotes. |
