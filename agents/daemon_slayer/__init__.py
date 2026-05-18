"""Daemon Slayer - local item-build engine.

Phase 2 step 4 + Phase 3 + Phase 4: stat math + auto-attack DPS layered
with per-item conditional effects from ``effects.py``, single-slot item
ranking (``rank.py``), and full-build beam search (``beam.py``).

Effects coverage: IE / Kraken / Stormrazor / BT / Shieldbow (thin slice)
plus the energized family (Statikk Shiv, Rapid Firecannon, Voltaic),
scaling procs (Wit's End, Runaan's, Trinity Force, Sundered Sky,
Guinsoo's, Lich Bane, Nashor's Tooth), the armor pen / reduction layer
(LDR, Mortal Reminder, Black Cleaver), the symmetric magic pen layer
(Void Staff, Cryptbloom, Sorcerer's Shoes, Shadowflame - Phase 4
batch 4, 2026-05-04), the target-HP layer (BotRK Mist's Edge,
Eclipse Ever Rising Moon - Phase 4 batch 5, 2026-05-04), the
caster-HP layer (Titanic Hydra Cleave, Heartsteel Colossal
Consumption - Phase 4 batch 6, 2026-05-04), the multi-target rotation
layer (Ravenous Hydra Cleave - Phase 4 batch 7, 2026-05-04), the
multi-proc-per-item schema (Titanic Hydra cleave-to-others - Phase 4
batch 8, 2026-05-04), Immolate items (Sunfire Aegis, Hollow Radiance -
Phase 4 batch 9, 2026-05-04, reusing the caster-HP + multi-target
layers with no new schema), unique-passive enforcement (Phase 4
batch 10, 2026-05-04 - ItemEffect.unique_passive_key + dedup in
collect_effects; first user is "immolate" tagging Sunfire + Hollow
Radiance), spellblade unique-passive (Phase 4 batch 11, 2026-05-04 -
Trinity Force + Lich Bane share a "spellblade" key; Sundered Sky's
distinct "Lightshield Strike" and Essence Reaver's defensive_only
entry intentionally untagged), lifeline unique-passive (Phase 4
batch 12, 2026-05-04 - Immortal Shieldbow + Sterak's Gage + Maw of
Malmortius share a "lifeline" key; Phantom Dancer's distinct
"Spectral Waltz" Ghost effect intentionally untagged), Terminus
promoted from defensive_only (Phase 4 batch 13, 2026-05-04 - Shadow
on-hit 30 magic per basic + Juxtaposition Dark sustained 10% armor
pen + 10% magic pen), build-wide damage amplifier schema (Phase 4
batch 14, 2026-05-04 - ItemEffect.damage_amp_pct + multiplicative
stacking via total_damage_amp_multiplier; first user is Riftmaker's
8% Void Corruption at full ramp), HP→AP cross-derivation (Phase 4
batch 15, 2026-05-04 - ItemEffect.ap_per_bonus_hp_pct + additive
helper total_bonus_ap_from_hp; Riftmaker's Void Infusion 2% bonus
HP → AP wired so Lich Bane / Nashor's Tooth procs see the converted
total), Stridebreaker (6631) Cleave + Essence Reaver (3508) Spellblade
promoted via the new CallContext.crit_chance schema (Phase 4 batch 21,
2026-05-04 - Stridebreaker mirrors Ravenous Hydra's 40% AD cleave to
other enemies in 350 radius; ER fires 1.25 * base_ad + 50 * crit_chance
once per ~3s spellblade rotation, joins the Trinity Force / Lich Bane
unique-passive dedup family, with the rewritten Trinity Force batch-11
comment closing the order-dependence question), Hextech Gunblade (3146)
Lightning Bolt promoted from defensive_only as a long-CD periodic
proc (Phase 4 batch 22, 2026-05-04 - 175→253 by level + 30% AP magic
damage, 40s cooldown, modeled with ``every_n_seconds=40.0``; same shape
as Sundered Sky's 8s Lightshield Strike with a far longer cadence;
the 25%/1.5s slow stays utility-only, not modeled), Iceborn Gauntlet
(6662) added to ITEM_EFFECTS as a new entry (Phase 4 batch 23,
2026-05-04 - 150% base AD bonus physical Spellblade variant joining
the Trinity Force / Lich Bane / Essence Reaver dedup family at the
shared ~3s ability-cast cadence; frost-field slow stays utility-only),
Profane Hydra (6698) added to ITEM_EFFECTS as a new entry (Phase 4
batch 24, 2026-05-04 - 40% AD melee Cleave to other enemies in 350
radius via the existing targets_in_rotation gate; matches
Stridebreaker's coefficient choice from batch 21; Heretical Cleave
active stays not-modeled per the s77/s78 actives-without-cooldown-pin
rule; Tiamat-tree exclusivity vs the other hydras is build-legality,
not unique-passive), Serylda's Grudge (6694) added to ITEM_EFFECTS as
a new entry (Phase 4 batch 25, 2026-05-04 - 35% armor pen joins the
LDR / Mortal Reminder family at the same coefficient as LDR; Bitter
Cold ability slow stays utility-only per the slow-without-damage
rule), Yun Tal Wildarrows (3032) + Atma's Reckoning (3039) paired
promotion via the new ItemEffect crit_chance_bonus_flat /
crit_chance_bonus_max_pct + per_bonus_hp_cap fields (Phase 4 batch 26,
2026-05-04 - Yun Tal pinned at full Wildarrows stacks 25%, Atma's
Big Hands linear ramp 0-30% over 0-3000 caster bonus HP; summed and
clamped at 1.0 in compute_dps so both auto-attack crit and ER's
Spellblade scaling see the boosted total; Yun Tal's Flurry AS bonus
intentionally not modeled), Manamune (3004) + Muramana (3042) paired
promotion via the new CallContext.caster_max_mp field +
ItemEffect.bonus_ad_pct_max_mp Awe wiring (Phase 4 batch 27, 2026-05-04
- Awe converts 2% max mana into bonus AD via the same engine-resolved
stat layer pattern as Sterak's bonus_ad_pct_base_ad from batch 20;
Muramana additionally fires Shock - 1.2% max mana per-attack physical -
via a periodic proc; Manaflow stack-up + Muramana's ability damage
piece intentionally not modeled), Archangel's Staff (3003) + Seraph's
Embrace (3040) paired promotion via the new
ItemEffect.bonus_ap_pct_bonus_mp field (Phase 4 batch 28, 2026-05-04 -
AP-side Awe twin; Archangel +1% / Seraph's +2% BONUS mana as AP, keyed
off item-contributed mana only - distinct from the Manamune family's
max-mana keying; engine walks ap_flat the same way the Manamune walk
targets ad_flat; Seraph's Lifeline shield piece tagged unique_passive_key
"lifeline" - Awe walk in engine.py bypasses collect_effects so the AP
contribution survives lifeline dedup), Phase 4 batch 29 coverage batch
(2026-05-04 - 6 items: 4 defensive_only entries [Hubris, Spirit Visage,
Kaenic Rookern, Cosmic Drive] + 2 partial promotions reusing existing
schema [Liandry's Torment via damage_amp_pct=0.06 for Suffering's
sustained 6% amp, Stormsurge via magic_pen_flat=15 joining Sorcerer's
Shoes / Shadowflame in the magic pen layer]; Hubris's 18 Lethality
deferred to a future "lethality plumbing" batch - needs level-scaled
flat pen schema), Phase 4 batch 30 lethality plumbing (2026-05-04 -
new ItemEffect.lethality field + level-scaled fold into
effective_target_armor's flat-pen sum (lethality × (0.6 + 0.4 × level/18));
7 items unlock simultaneously: Hubris (18), Voltaic Cyclosword (10),
Edge of Night (15), Youmuu's Ghostblade (18), Opportunity (18) all
promoted from defensive_only-or-stats-only-prior, plus Axiom Arc (18)
+ Umbral Glaive (18) as new entries - all 7 current-patch lethality
items now carry the level-scaled flat pen contribution), Phase 4 batch
31 support/ramp coverage sweep (2026-05-04 - 21 items: Dead Man's Plate
(3742) Shipwrecker partial promotion via periodic proc every_n_attacks=4
~109 physical at full Momentum stacks; Spectral Cutlass (4004) ARAM-only
lethality=15 promotion joining the batch-30 family; 19 defensive_only
entries for support/enchanter/tank items [Knight's Vow, Mikael's Blessing,
Redemption, Locket, Ardent Censer, Staff of Flowing Water, Echoes of Helia,
Moonstone Renewer, Dawncore, Imperial Mandate, Rod of Ages, Winter's Approach,
Fimbulwinter, Force of Nature, Rylai's Crystal Scepter, Jak'Sho the Protean,
Hextech Rocketbelt, Experimental Hexplate, Abyssal Mask]), Phase 4 batch 32 AP amplification + lethality + new schema
(2026-05-04 - 15 items: Rabadon's Deathcap (3089) via new
``ap_amp_pct=0.30`` field + ``total_ap_amp_multiplier`` helper wired
into compute_dps so every AP-scaling proc (Lich Bane, Nashor's Tooth,
Void Staff pen) sees the ×1.30 effective AP; Dusk and Dawn (2510)
Spellblade 75% base AD + 10% AP magical every ~1.5s joining the
"spellblade" unique-passive dedup family; The Collector (667666) 10
lethality + Prowler's Claw (6693) 22 lethality + Bastionbreaker (2520)
22 lethality all via the batch-30 level-scaled flat pen schema; Overlord's
Bloodmail (2501) via new ``bonus_ad_pct_bonus_hp=0.025`` field + engine.py
stat-walk using item_totals[hp_flat] as bonus HP proxy; Demonic Embrace
(4637) Dark Pact 2% bonus HP as AP via existing ``ap_per_bonus_hp_pct``
schema (stacks additively with Riftmaker); 8 defensive_only entries
[Morellonomicon, Horizon Focus, Malignance, Blackfire Torch, Endless
Hunger, Chempunk Chainsword, Hexoptics C44, Bloodletter's Curse];
Azakana's Gaze + Shaped Charge + Hypershot/Hatefog/Baleful Blaze all
deferred pending ability-cast schema), and 48 defensive_only items
spanning the Tier-1 SR / Arena pool plus high-pickrate batch 2 + AP
batch 3 additions plus batch 31 support/ramp coverage plus batch 32.
Phase 4 batch 33 ability-burn promos + dual-pen + caster-HP burn
(2026-05-04 - 4 active promotions: Gambler's Blade (667101) 15 lethality
+ 15 magic pen flat dual-pen [DDragon Adaptive Force gap noted]; Unending
Despair (2502) Agony 3% caster bonus HP magic every 4s via existing
caster_bonus_hp schema; Blackfire Torch (2503) Baleful Blaze 6 + 6% AP
magic every 0.5s promoted from defensive_only [ranged Meraki value];
Demonic Embrace (4637) gains second proc Azakana's Gaze 1% target max
HP/s magic burn [ranged value]; plus 7 defensive_only entries: Night
Harvester, Fiendhunter Bolts, Sword of the Divine, Flesheater, Sword of
Blossoming Dawn, Actualizer, Cruelty). Phase 4 batch 34 magic-amp schema
(2026-05-04 - new ItemEffect.magic_amp_pct field +
total_magic_amp_multiplier helper + per-proc application in
_periodic_proc_dps; does NOT amplify physical auto-attack damage;
Abyssal Mask (8020) promoted from defensive_only with magic_amp_pct=0.12
[Unmake 12% more magic damage to nearby enemies]). Phase 4 batch 35
missed-lethality + dual-pen + spellblade + on-hit sweep (2026-05-04 -
5 active promotions: Duskblade of Draktharr (6691) lethality=18
[missed from batch-30 lethality sweep]; Perplexity (4015) 22% armor pen
+ 30% magic pen dual-pen; Divine Sunderer (6632) Spellblade 125% base AD
+ 6% target max HP physical every 3s [joins spellblade dedup family];
Navori Flickerblade (6672) Bring It Down every-3rd-attack 120→168
physical [ranged scaling]; Hellfire Hatchet (4017) lethality=12 [Char
proc deferred]; plus 6 defensive_only entries: Goredrinker, Galeforce,
Zeke's Convergence, Wordless Promise, Frozen Mallet, Lightning Braid).
Phase 4 batch 36 Arena item sweep + Rite of Ruin crit (2026-05-04 -
6 active promotions: Detonation Orb (447113) magic_pen_flat=12;
Reverberation (447114) Resonate 10+2% caster bonus HP magic on-hit;
Pyromancer's Cloak (447118) Spark 100→350 magic burn every 5s;
Lightning Rod (447119) Call Lightning 135→230+30% bonus AD+50% AP+10%
target max HP magic every 16s; Regicide (447115) lethality=15; Rite of
Ruin (3430) crit_chance_bonus_flat=0.20 [max Wrath+Ruin stacks]; plus 6
defensive_only: Runecarver, Kinkou Jitte, Diamond-Tipped Spear,
Twilight's Edge, Decapitator, Mirage Blade). Phase 4 batch 37 TRUE damage type + Arena item sweep
(2026-05-04 - new ``TRUE = "true"``
constant + ``_DAMAGE_TYPES`` update; ``_periodic_proc_dps`` handles
``damage_type == TRUE`` with ``resist=0.0`` bypassing both armor and
MR; 3 active promotions: Darksteel Talons (443054) Gash every-attack
10→20 true [ranged, level-scaled; bonus-armor component deferred],
Fulmination (443055) Dynamo every-100th-attack 13% target max HP magic
[upper-bound approx; Polarity Energized deferred], Reaper's Toll
(443090) Reap every-attack 0.7% target max HP true [pinned at 0 stacks];
plus 14 defensive_only entries completing the Arena 443xxx/447xxx pool:
Gambler's Blade (447101), Reality Fracture (447102), Hemomancer's Helm
(447103), Innervating Locket (447104), Empyrean Promise (447105),
Dragonheart (447106), Cruelty (447109), Moonflair Spellblade (447110),
Flesheater (447112), Black Hole Gauntlet (447122), Puppeteer (447123),
Demon King's Crown (443056), Sword of the Divine (443060), Hamstringer
(443069)). Phase 4 batch 38 Giant Slayer MAX HP diff schema + 228xxx/443xxx/SR
sweep (2026-05-04 - new ``ItemEffect.giant_slayer_pct_per_100hp`` +
``giant_slayer_max_pct`` fields + ``total_giant_slayer_multiplier`` helper wired
into ``compute_dps`` after caster_max_hp is derived from build; distinct from
LDR's bonus-HP-keyed ``target_bonus_hp_amp``; Perplexity (4015) updated with
giant_slayer_pct_per_100hp=0.006 / max=0.15 completing its Giant Slayer component;
3 active promotions: Wooglet's Witchcap (228002) ap_amp_pct=0.50, Deathblade (228003)
lethality=20 + crit_damage_bonus=0.45, Obsidian Cleaver (228005) armor_reduction_pct=0.35
[5 stacks × 7%]; 17 defensive_only entries completing the 228xxx + 443xxx + SR
pool sweep [Anathema's Chains SR (8001)/Arena (228001), Adaptive Helm (228004),
Sanguine Blade (228006), Runeglaive (228008), Shield of Molten Stone (443058),
Cloak of Starry Night (443059), Force of Entropy (443061), Sanguine Gift (443062),
Eleisa's Miracle (443063), Talisman of Ascension (443064), Turbo Chemtank (443079),
Twin Mask (443080), Hexbolt Companion (443081), Gargoyle Stoneplate (443193),
Protoplasm Harness (2525, lifeline unique-passive), Randuin's Omen (3143)]). Phase 4 batch 39 MR-reduction schema + Arena re-skin
sweep (2026-05-04 - new ``ItemEffect.mr_reduction_pct`` field wired into
``effective_target_mr`` before % pen step, mirroring the armor-side
``armor_reduction_pct`` layer; 5 active promotions: Bloodletter's Curse (4010)
mr_reduction_pct=0.30 [4×7.5% Vile Decay stacks], Divine Sunderer Arena (446632)
Spellblade 180% base AD + 2% target max HP [higher base-AD coefficient than SR
6632; unique_passive_key spellblade], Overlord's Bloodmail Arena (447111)
bonus_ad_pct_bonus_hp=0.03 [Tyranny 3% vs SR's 2.5%], Atma's Reckoning (663039)
crit_chance_bonus_max_pct=0.30 [same coefficients as SR 3039], Hextech Gunblade
(663146) Lightning Bolt same formula as SR 3146; 7 defensive_only: Night Harvester
(444636), Demonic Embrace Arena (444637), Duskblade Arena (446691), Radiant Virtue
(446667), Warmog's Armor Arena (443083), Demon King's Crown (663056), Sword of
Blossoming Dawn (4011)). Phase 4 batch 40 component items +
final SR/Arena sweep (2026-05-04 - 3 active promotions: Last Whisper
(3035) armor_pen_pct=0.18 [component of LDR/Mortal Reminder/Serylda's],
The Brutalizer (2020) lethality=5 [historical component item], Haunting
Guise (3147) damage_amp_pct=0.06 [Madness 2%/s × 3s, pinned at full
stacks, same coefficient as Liandry's Torment 3151]; 15 defensive_only
entries completing the final SR/Arena sweep: Crown of the Shattered Queen
Arena (444644), Everfrost Arena (446656), Galeforce Arena (446671),
Crown of the Shattered Queen SR (664644), Shield of Molten Stone SR
(663058), Cloak of Starry Night SR (663059), Zephyr SR (663172),
Gargoyle Stoneplate SR (663193), The Golden Spatula (664403), Thornmail
(3075), Mejai's Soulstealer (3041), Quicksilver Sash (3140), Hexdrinker
(3155, unique_passive_key lifeline), Verdant Barrier (4632), Plated
Steelcaps (3047)). Phase 4 batch 41 Arena 226xxx mirrors (2026-05-04
- fixes a batch-35 key collision where Navori Flickerblade was mistakenly
keyed to "6672" (Kraken Slayer's DDragon ID), silently overwriting it;
Navori moved to correct key "6675", old defensive_only "6675" stub
removed; covers all 28 missing 226xxx Arena pool items (DDragon IDs
226xxx = SR counterpart at 226xxx − 220000): 14 active promotions
sharing the same schema as their SR counterparts [Sundered Sky (226610)
Lightshield Strike, Stridebreaker (226631) Cleave, Liandry's Anguish
(226653) damage_amp_pct=0.06, Iceborn Gauntlet (226662) Spellblade
spellblade-key, Hollow Radiance (226664) Immolate immolate-key,
Navori Flickerblade (226672) Bring It Down 120→168, Eclipse (226692)
Ever Rising Moon 6% target HP, Prowler's Claw (226693) lethality=22,
Serylda's Grudge (226694) armor_pen_pct=0.35, Axiom Arc (226696)
lethality=18, Hubris (226697) lethality=18, Profane Hydra (226698)
Cleave, Voltaic Cyclosword (226699) Firmament+lethality=10, Opportunity
(226701) lethality=18]; 14 defensive_only mirrors [Death's Dance
(226333), Chempunk Chainsword (226609), Staff of Flowing Water (226616),
Moonstone Renewer (226617), Echoes of Helia (226620), Dawncore (226621),
Goredrinker (226630), Luden's Echo (226655), Rod of Ages (226657),
Jak'Sho (226665), Immortal Shieldbow (226673, lifeline-key), Navori
Flickerblades (226675), The Collector (226676), Serpent's Fang
(226695)]). Phase 4 batch 42 222xxx/224xxx Arena + 32xxxx ARAM mirrors
(2026-05-04 - 35 entries: 10 active [Unending Despair (222502), Blackfire
Torch (222503), Dusk and Dawn (222510) spellblade-key, Spectral Cutlass
(224004) lethality=15, Riftmaker (224633) damage_amp_pct=0.08, Shadowflame
(224645) magic_pen_flat=15, Stormsurge (224646) magic_pen_flat=15,
Archangel's ARAM (323003), Manamune ARAM (323004), Abyssal Mask ARAM
(328020) magic_amp_pct=0.12]; 25 defensive_only). Phase 4 batch 43
223xxx Arena mirrors (2026-05-04 - 58 entries: 33 active with same
schema as SR 3xxx counterparts [Archangel's (223003), Manamune (223004),
Sorcerer's Shoes (223020), IE (223031), Yun Tal (223032), Mortal Reminder
(223033), LDR (223036), Atma's (223039), Sterak's (223053) lifeline-key,
Sunfire Aegis (223068) immolate-key, Black Cleaver (223071), Ravenous
Hydra (223074), Trinity Force (223078) spellblade-key, Heartsteel
(223084), Runaan's (223085), Statikk Shiv (223087), Rabadon's (223089),
Wit's End (223091), RFC (223094), Lich Bane (223100) spellblade-key,
Nashor's (223115), Guinsoo's (223124), Void Staff (223135), Cryptbloom
(223137), Youmuu's (223142), Gunblade (223146), BotRK (223153),
Hullbreaker (223181), Terminus (223302) dual-pen, ER (223508)
spellblade-key, DMP (223742), Titanic Hydra (223748) dual-Cleave, Edge
of Night (223814)]; 25 defensive_only [223026/046/047/050/065/072/073/
075/102/107/109/110/116/118/119/139/143/152/156-lifeline/157/161/165/
190/222/504]). Phase 4 batch 44 DPS components + full items (2026-05-04
- 19 entries: 5 proc-bearing components [Sheen (3057) Spellblade 100%
base AD every 1.5s spellblade-key, Tiamat (3077) Cleave 50% AD to nearby
via targets_in_rotation gate (zero single-target), Hextech Alternator
(3145) Revved 75 magic every 5s, Bami's Cinder (6660) Immolate
12+0.5% max HP magic/s immolate-key, Rageknife (6677) Wrath 20 magic
on-hit]; 3 full items with DPS contribution [Sword of the Divine (3131)
18 lethality + Divine Judgment 75% AD guaranteed-crit bonus every 15s,
Shield of the Rakkor (6700) stats-only (Rakkor Strike armor pen
conditional on active - not modeled), Evenshroud (3001) damage_amp_pct=0.06
(Coruscation 6% more damage - legacy removed-item entry)]; 11 stats-only
items [Zeal (3086), Serrated Dirk (3134) lethality=10, Caulfield's
Warhammer (3133), Executioner's Calling (3123), Lost Chapter (3802),
Oblivion Orb (3916), Fiendish Codex (3108), Aether Wisp (3113),
Hearthbound Axe (3051), Phage (3044), Ironspike Whip (6029)]).
Phase 4 batch 45 defensive full items + components + boots (2026-05-04
- 21 entries: 1 active [Berserker's Greaves (3006) 25% AS contribution];
20 defensive_only [Everfrost (6656), Silvermere Dawn (6035), Radiant
Virtue (6667), Crown of the Shattered Queen (4644), Sin Eater (4012),
Innervating Locket (4402), Gargoyle Stoneplate (3193), Trailblazer
(3002), Kindlegem (3067), Tear of the Goddess (3070), Spectre's Cowl
(3211), Glacial Buckler (3024), Bramble Vest (3076), Warden's Mail
(3082), Aegis of the Legion (3105), Crystalline Bracer (3801), Catalyst
of Aeons (3803), Boots of Swiftness (3009), Mercury's Treads (3111),
Ionian Boots of Lucidity (3158)]).
CallContext + callable ``bonus_damage`` lets stat-scaling procs bind
to ``base_ad`` / ``bonus_ad`` / ``level`` / ``ap`` / ``target_max_hp`` /
``caster_max_hp`` / ``caster_bonus_hp`` / ``targets_in_rotation`` /
``crit_chance`` / ``caster_max_mp``.
Phase 4 batch 46 226xxx/228xxx/224xxx Arena mirrors + remaining SR
(2026-05-04 - 22 entries: 9 active [Divine Sunderer (226632) Spellblade
spellblade-key, Bami's Cinder (226660) Immolate immolate-key, Duskblade
(226691) lethality=18, Abyssal Mask (228020) magic_amp_pct=0.12, Demonic
Embrace (224637) ap_per_bonus_hp_pct=0.02 + Azakana's Gaze 1% target max
HP/s, Noonquiver (6670) stats-only, Rectrix (6690) stats-only, Lifeline
(4003) lethality=5, Blighting Jewel (4630) magic_pen_pct=0.13]; 13
defensive_only [Everfrost Arena (226656), Radiant Virtue Arena (226667),
Galeforce Arena (226671), Silvermere Dawn Arena (226035), Night Harvester
Arena (224636), CotSQ Arena (224644), Multitool (228009), Leeching Leer
(4635), Golden Spatula SR (4403), Watchful/Stirring/Vigilant Wardstones
(4638/4641/4642/4643), Bandleglass Mirror (4642)]). Phase 4 batch 47
Arena 22xxxx/32xxxx remaining pool + 221xxx components (2026-05-04 -
~42 entries: 8 active DPS procs [Evenshroud Arena (223001)
damage_amp_pct=0.06, Seraph's Embrace Arena (223040/323040)
bonus_ap_pct_bonus_mp=0.02 lifeline-key, Muramana Arena (223042/323042)
Shock 1.2% max mana physical on-hit + bonus_ad_pct_max_mp=0.02, Sheen
Arena (223057) Spellblade 100% base AD every 1.5s spellblade-key,
Stormrazor Arena (223095) Stormraider guaranteed-crit bonus every 30s,
Guardian's Dirk Arena (223185) lethality=11]; 7 221xxx Arena components
[221011/221026/221031/221043/221053/221057/221058 - stats-only]; 2
mini-consumables [222022/222141 - defensive_only]; 26 defensive_only
Arena mirrors [223002/067/069/105/111/112/121/158/172/177/184/193,
222051/065/524/526/530, 224403, 322065/526/530, 323002/070/121]).
Phase 4 batch 48 core 1xxx tier-1 components (2026-05-04 - 29 entries:
1 proc-bearing component [Recurve Bow (1043) Sting - 15 bonus physical
on every attack]; 14 stats-only active [Cloak of Agility (1018), Blasting
Wand (1026), Long Sword (1036), Pickaxe (1037), B. F. Sword (1038),
Dagger (1042), Amplifying Tome (1052), Vampiric Scepter (1053), Doran's
Blade (1055), Doran's Ring (1056), Needlessly Large Rod (1058), Dark Seal
(1082), Cull (1083), Doran's Bow (1086)]; 14 defensive_only [Boots (1001),
Faerie Charm (1004), Rejuvenation Bead (1006), Giant's Belt (1011),
Sapphire Crystal (1027), Ruby Crystal (1028), Cloth Armor (1029),
Chain Vest (1031), Null-Magic Mantle (1033), Emberknife (1035),
Hailblade (1039), Obsidian Edge (1040), Doran's Shield (1054),
Negatron Cloak (1057)]).
Phase 4 batch 49 remaining 3xxx/2xxx + final Arena pool (2026-05-04 -
~49 entries: 12 active [Spellslinger's Shoes (3175) magic_pen_flat=18 +
magic_pen_pct=0.08 - both pen layers; Gunmetal Greaves (3172) AS boots
stats-only; Guardian's Blade (3177) + Guardian's Hammer (3184) mixed-stat
components; Stormrazor (3095) legacy deprecated stats-only; Scout's
Slingshot (3144) stats-only; Fated Ashes (2508) 30 AP stats-only (Inflame
ability-cast deferred); Rite of Ruin (123430) crit_chance_bonus_flat=0.25;
Hubris (126697) lethality=18; Prowler's Claw Arena (446693) lethality=20;
B. F. Sword Arena (221038) stats-only; Berserker's Greaves Arena (223006)
AS boots stats-only]; 11 defensive_only boots [Ghostcrawlers (3005),
Gluttonous Greaves (3008), Symbiotic Soles (3010), Synchronized Souls
(3013), Mobility Boots (3117), Immortal Path (3168), Swiftmarch (3170),
Crimson Lucidity (3171), Chainlaced Crushers (3173), Armored Advance
(3174), Forever Forward (3176)]; 5 defensive_only components [Chalice of
Blessing (3012), Lifewell Pendant (3023), Winged Moonplate (3066),
Guardian's Orb (3112), Forbidden Idol (3114)]; 4 defensive_only 2xxx
[Shurelya's (2065), Bandlepipes (2524), Whispering Circlet (2526),
Diadem of Songs (2530)]; 5 defensive_only Arena [Sword of Blossoming
Dawn (124011), Ghostcrawlers Arena (223005), Gluttonous Greaves Arena
(223008), Boots of Swiftness Arena (223009), Chemtech Putrifier Arena
(223011)]).

Beam search (Phase 2 step 4) returns the top-N complete builds by final
weighted DPS, finding multi-item synergies the single-slot ranker
misses. Boots-uniqueness on by default; ``total_budget`` clamps total
build gold; ``current_item_ids`` pins the user's current build.

The local HTTP server (``server.py``) exposes ``/stats``, ``/dps``,
``/rank``, and ``/beam`` on :8893; the package stays importable for
direct use without spinning the engine.

Batch 64 (2026-05-05 - Stage 4: ult-cast schema, ENGINE_VERSION 0.60.0):
  Promoted Malignance (3118, 223118) via per-champion ult cast rate data from
  rewind_history.db (spell4_casts / game_duration_s → ult_cast_rates.json,
  172 champions). Hatefog formula: (180 + 15% AP) magic per ult zone hit.
  Schema addition: CallContext.ult_casts_per_sec (float, engine-derived from
  ult_rates.py; default 0.0 → safe no-op). PeriodicProc trick: every_n_seconds=1.0
  as normalization anchor; bonus_damage = (180+0.15*ap)*ult_casts_per_sec so
  rate is champion-aware without a per-champion ItemEffect split.
  Permanently deferred (3 items remain): Lightning Braid (no Meraki formula,
  DPS-negative), Kinkou Jitte (directional geometry), Mejai's Arena mirror
  (no Arena DDragon ID).

Phase 6 step 7 (2026-05-10 - per-level DPS curve helper, ENGINE_VERSION 0.61.0):
  Added ``compute_dps_curve()`` + ``DpsCurvePoint`` dataclass + ``DPS_CURVE_LEVELS``
  (1/6/11/16/18) to dps.py. Pure additive helper - calls ``compute_dps()`` at each
  level, returns a list of points with weighted DPS + phase + compact stat subset.
  No engine math change; no schema breakage. Unlocks coach hints like "Lulu peaks
  at lvl 6, falls off at 11". 12 new tests (35 total in test_dps).

Phase 0 (2026-05-12 - dead-unique candidate filter, ENGINE_VERSION 0.62.0):
  Added ``shares_dead_unique`` + ``dead_unique_key`` fields to ``RankedItem`` and
  the ``filter_shared_uniques: bool = True`` parameter to ``rank_items``. Filters
  candidates whose unique_passive_key collides with an item already in
  current_item_ids (Trinity→ER, Sterak's→Maw, Sunfire→Hollow Radiance families).
  6 new tests in test_rank's ``SharedUniqueFilterTests``.

Phase 1 (s174, 2026-05-12 - Tank EHP scorer, ENGINE_VERSION 0.63.0):
  New ``ehp.py`` sibling of ``dps.py`` with ``compute_ehp()`` + ``EhpResult`` +
  ``rank_items_by_ehp()`` + ``EhpRankedItem`` + ``EhpRankResult``. Closed-form
  League EHP math: ``physical_ehp = hp / armor_factor(armor)``, same for
  magical_ehp via mr, ``true_ehp = hp``. ``blended_ehp`` weighted by
  caller-supplied ``enemy_ad_share`` / ``enemy_ap_share`` (remainder is true).
  ARAM ``aramDamageTaken`` modifier folded into all EHP components (lower
  modifier → take less damage → higher EHP). New ``/rank-tank`` server route
  mirrors ``/rank`` shape. ``core/defensive_picks.py`` opt-in integration via
  ``use_ehp_ranker=True`` (Option B layer - the s171 curated catalog is passed
  as ``only_item_ids`` whitelist; math drives ordering within the vetted pool).
  Deliberate Phase 1 omissions deferred to Phase 1.5: shield throughput
  (Sterak's lifeline, Doran's Shield), healing throughput, enemy pen modeling.
  See ``NEXT_SESSION_PLAN_2026-05-12_ARCHETYPE_EXPANSION.md`` for the multi-
  session archetype-expansion plan this kicks off.

Phase 2 (s175, 2026-05-12 - Bruiser hybrid scorer, ENGINE_VERSION 0.64.0):
  New ``hybrid.py`` composing ``compute_dps`` + ``compute_ehp`` into a single
  archetype score for bruisers: ``hybrid_score = α·dps + β·ehp``.
  ``compute_hybrid()`` + ``HybridResult`` for the scorer; ``rank_items_by_hybrid()``
  + ``HybridRankedItem`` + ``HybridRankResult`` for the ranker. Per-champion
  (α, β) overrides live in ``archetype_weights.json`` - ships with 20
  bruisers (Jarvan IV, Darius, Garen, Camille, Renekton, Sett, Mordekaiser,
  Riven, Volibear, Nasus, Olaf, Skarner, Hecarim, Udyr, Vi, Xin Zhao,
  Lee Sin, MonkeyKing/Wukong, Warwick, Trundle); unlisted champions fall
  back to (0.50, 0.50). Ranker sort key is normalized percentage delta
  (``α · dps_delta/baseline_dps + β · ehp_delta/baseline_ehp``) so the
  weights stay intuitive across the ~10× magnitude gap between DPS and
  EHP. New ``/hybrid`` + ``/rank-bruiser`` server routes mirror existing
  ``/dps`` + ``/rank`` shapes (union of /dps and /ehp params + optional
  ``alpha`` / ``beta`` overrides). Deliberate omissions: per-champion
  weight calibration from rewind_history.db (Phase 2.5) and
  phase/level-aware weights (single weight pair is good enough for v1).

Phase 6 (s181, 2026-05-13 - Enchanter healing throughput scorer, ENGINE_VERSION 0.69.0):
  New ``hps.py`` sibling of ``ehp.py`` / ``burst.py`` with ``compute_hps()``
  + ``HpsResult`` + ``HpsItemContribution`` + ``rank_items_by_hps()`` +
  ``HpsRankedItem`` + ``HpsRankResult``. Per-item healing/shielding/buff
  throughput model backed by a new hand-curated ``data/daemon_slayer/<patch>/
  enchanter_items.json`` registry covering 9 enchanter items: Moonstone
  Renewer (6617, chain amp), Redemption (3107, active AoE heal), Mikael's
  Blessing (3222, single-target heal + cleanse), Echoes of Helia (6620,
  Soul Siphon damage→heal), Ardent Censer (3504, AS/on-hit ally buff),
  Staff of Flowing Water (6616, AP/AH ally buff), Locket of the Iron
  Solari (3190, active AoE shield), Imperial Mandate (4005, damage proc),
  Knight's Vow (3109, ally tank-share). Each item carries per-proc
  base/per-level/AP-scaling for healing and shielding, procs-per-second,
  targets-per-proc, heal/shield amp percent (Moonstone +30% chain;
  Redemption/Mikael/Ardent/Staff +10-12% H&S power), and an ally_buff_credit
  number calibrated against direct HPS (10 ≈ 10 HPS-equivalent) so pure-
  buff items rank next to direct-heal items. Total throughput = (healing_raw
  + shielding_raw) × product(1 + amp_pct) × mode_mult + sum(buff_credit).
  ARAM mode applies ``aramShieldsHealing`` modifier when present on the
  champion. Operator can pass ``targets_per_proc_override`` to retune the
  "average teammate" assumption (Arena 2v2 → override=1). New ``/hps`` +
  ``/rank-enchanter`` server routes mirror ``/ehp`` + ``/rank-tank`` shape
  but drop target_*-resist parameters (irrelevant for outgoing heals).
  ``core/daemon_slayer_client.py`` gains ``EnchanterRankedItem`` +
  ``rank_enchanter_for()`` + ``hps_for()`` client helpers; the
  ``rank_for_primary_archetype()`` dispatcher's enchanter branch now routes
  to ``ds.hps`` - first time the dispatcher has all 6 archetype branches
  wired with no fallbacks. Champion list covered: Lulu, Soraka, Janna,
  Karma, Sona, Yuumi, Nami, Seraphine, Renata Glasc, Senna (support
  variant). Deliberate Phase 6 omissions (Phase 6.5+): real ally-state
  plumbing (positions, HP, buff uptime), champion-spell healing
  throughput (Soraka W / Lulu E / Janna E - only ITEM throughput scored),
  heal/shield-power scaling on champion abilities (applies to items only),
  Chemtech Putrifier 3011 (anti-heal - intentionally excluded from
  positive-HPS contributions).

Phase 5 (s180, 2026-05-13 - Assassin burst-window scorer, ENGINE_VERSION 0.68.0):
  New ``burst.py`` sibling of ``ability_dps.py`` with ``compute_burst_damage()``
  + ``BurstResult`` + ``ComboCast`` + ``rank_items_by_burst()`` +
  ``BurstRankedItem`` + ``BurstRankResult``. Per-combo evaluator: walks a
  caller-supplied ``combo_sequence`` (default ``("Q","W","E","AA","R","AA")``;
  tokens ``AA`` / ``P`` / ``Q`` / ``W`` / ``E`` / ``R`` / ``Q2-R2`` for
  repeats), fires each spell once at its level-resolved rank, sums damage
  blocks, applies the ``compute_ability_dps`` amp pipeline (Rabadon's AP
  amp, Liandry's damage amp, Demonic Embrace HP→AP, Abyssal Mask magic
  amp on magic-typed spells, Riftmaker HP→AP, Mejai's stacked AP), and
  applies the standard mitigation pipeline (lethality + flat pen + % pen
  for PHYSICAL; flat + % magic pen for MAGIC; TRUE bypass). Auto-attack
  hits in the combo contribute the build's per-hit ``avg_attack_dmg`` from
  ``compute_dps`` (post-armor + mode, no on-hit periodic procs - Phase 5.5
  deferral). ``primary_scaling`` classifier inspects the un-evaluated
  damage blocks (AP / AD / HP / MIXED / TRUE) so it's stable across builds.
  New ``/burst`` + ``/rank-assassin`` server routes mirror ``/ability-dps``
  + ``/rank-mage`` shape - union of body parameters plus ``combo_sequence``
  (list / dash-string / comma-string forms accepted). Sort keys
  ``delta`` (absolute burst-damage gain) and ``efficiency`` (per-1k-gold).
  ``core/daemon_slayer_client.py`` gains ``AssassinRankedItem`` +
  ``rank_assassin_for()`` + ``burst_for()`` client helpers; the
  ``rank_for_primary_archetype()`` dispatcher's assassin branch now routes
  to ``ds.burst`` (was ``ds.dps`` with ``fell_back=True``). Enchanter still
  falls back to ds.dps pending Phase 6. Champion list unblocked: Zed,
  Talon, Akali, Kha'Zix, Rengar, Fizz, Diana, Kassadin, Katarina, LeBlanc,
  Qiyana, Pyke, Naafiri, Briar, Yone (all 14 present in the Phase 4a
  abilities snapshot). Deliberate omissions (Phase 5.5): real cooldown
  sequencing, mana economy, on-hit periodic AA procs, per-champion combo
  templates JSON (operator passes ``combo_sequence`` explicitly v1),
  conditional damage amps (Ahri R→Q, Zoe E→Q). Phase 6 (enchanter HPS) is
  the last remaining scorer in the archetype-expansion plan.

Phase 4c (s179, 2026-05-12 - Mage ability DPS ranker, ENGINE_VERSION 0.67.0):
  ``ability_dps.py`` gains ``rank_items_by_ability_dps()`` + ``AbilityDpsRankedItem``
  + ``AbilityDpsRankResult`` mirroring ``rank_items_by_hybrid`` / ``rank_items_by_ehp``
  shape - same candidate-filtering pipeline (purchasable + mode-legal +
  optional whitelist + budget + terminal-only + dead-unique dedup),
  same ``delta`` / ``efficiency`` sort keys, but each candidate is scored
  by total-ability-DPS gain over the baseline rather than auto-attack DPS
  or blended EHP. New ``/rank-mage`` server route mirrors ``/rank-tank`` +
  ``/rank-bruiser`` shape: union of ``/ability-dps`` and ``/rank`` body
  parameters, with shared ``max_priority`` / ``form_index`` decoders so
  both routes parse the operator's priority/form overrides identically.
  ``core/daemon_slayer_client.py`` gains ``MageRankedItem`` +
  ``rank_mage_for()`` + ``ability_dps_for()`` client helpers; the
  ``rank_for_primary_archetype()`` dispatcher's mage branch now routes
  to ``ds.ability`` (was ``ds.dps`` with ``fell_back=True``). Assassin
  + enchanter still fall back to ds.dps pending Phases 5-6.

Phase 4b (s178, 2026-05-12 - Mage ability DPS evaluator, ENGINE_VERSION 0.66.0):
  New ``ability_dps.py`` sibling of ``dps.py`` with ``compute_ability_dps()``
  + ``AbilityDpsResult`` + ``AbilitySpellDps`` + ``AbilityContext``. Per-spell
  evaluator that resolves Q/W/E/R damage at the rank a champion would have
  at the given level (canonical Q-first, W-second, E-third max-priority
  table; R unlocks 6/11/16), sums the first damage block's per-rank
  scaling (``base`` + total/bonus AD + AP + caster max/bonus HP + target
  max/missing/current/bonus HP + target armor + caster bonus armor/MR +
  caster max MP), then multiplies by measured casts/sec from
  ``cast_rates.get_spell_casts_per_sec`` (Phase 4b's new derivation from
  ``rewind_history.db.participants.spell[1-4]_casts``). Mode multiplier
  (``aramDamageDealt`` for ARAM) applied per-cast. Mitigation routes per
  damage type: PHYSICAL→target_armor curve, MAGIC→target_mr curve,
  TRUE→bypass, MIXED→half-half. AP cross-derivations from ``compute_dps``
  ported in for parity (Riftmaker HP→AP, Mejai's stacked AP, Rabadon's
  ap_amp, Demonic Embrace hp_ap_amp, build-wide damage_amp + giant_slayer
  + target_bonus_hp_amp + magic_amp on magic-typed spells). Single-block
  multi-form abilities use ``form_index=0`` by default; per-key
  ``form_index_overrides`` available for Aphelios/Jayce/Sylas. Coverage:
  170+ champions × 4 spells × 3 mode buckets via
  ``data/daemon_slayer/spell_cast_rates.json`` (172 champs, 669 buckets;
  generated by new ``scripts/build_spell_cast_rates.py`` from 2851
  matches in the rewind DB). ``ult_rates.py`` extended with the new
  ``get_spell_casts_per_sec(champion, key, mode)`` function; legacy
  ``get_ult_casts_per_sec`` preserved for Malignance Hatefog backward
  compat. New ``/ability-dps`` server route mirrors ``/dps`` shape.
  Deliberate Phase 4b omissions deferred to Phase 4c: per-spell ranker
  (``rank_items_by_ability_dps``) + ``/rank-mage`` route + per-champion
  max-priority overrides JSON + assassin-style combo-window scoring.

Phase 4a (s177, 2026-05-12 - Champion ability ingest, ENGINE_VERSION 0.65.0):
  New ``abilities.py`` loader + ``tools/daemon_slayer_abilities_extract.py``
  extractor consuming the Meraki bulk champions endpoint. Phase 4a is
  data-only - formula evaluation ships in Phase 4b's ``ability_dps.py``.
  Per-champion ability records expose ``P/Q/W/E/R → AbilityForm`` with
  per-rank ``cooldown`` / ``cost``, ``damage_type``, ``targeting``,
  ``is_aoe``, and a list of typed ``DamageBlock`` records. Each block
  carries per-rank scaling fields (``base``, ``total_ad_pct``,
  ``bonus_ad_pct``, ``ap_pct``, ``caster_max_hp_pct``,
  ``caster_bonus_hp_pct``, ``target_max_hp_pct``, ``target_missing_hp_pct``,
  ``target_current_hp_pct``, ``target_bonus_hp_pct``, ``target_armor_pct``,
  ``bonus_armor_pct``, ``bonus_mr_pct``, ``caster_max_mp_pct``) normalized
  from Meraki's ``leveling[].modifiers[].units[]`` strings. Multi-form
  abilities (Aphelios 6× Q/P, Jayce/Elise/Karma/LeeSin/Nidalee/Sylas 2×
  per affected key) preserved verbatim. Coverage: 171/172 champions (Meraki
  bulk lags Zaahen by one patch), 927 ability forms ingested. Status
  classifier reports 98.4% ok / 99.3% parsed (target 80%) - 4 unparsed
  niche aggregates (Illaoi spirit reflection, Ryze legacy R, Trundle ult
  HP-drain, MonkeyKing clone-output scalar). Snapshot lives at
  ``data/daemon_slayer/<patch>/champion_abilities.json``. The DS server
  does not call the abilities loader yet - Phase 4b wires
  ``compute_ability_dps()`` into ``/rank-mage``.

Phase 4d (s185, 2026-05-13 - per-champion max_priority overrides, ENGINE_VERSION 0.70.0):

* New ``agents/daemon_slayer/champion_max_priority.json`` registry (12 entries:
  Cassiopeia/Kayle/Akali/TwistedFate/Kassadin/Rumble/Leblanc/Heimerdinger/
  Karthus/Vladimir/Anivia/Lillia) - each champion mapped to a 3-key (Q,W,E)
  permutation reflecting their canonical max order. Loader + singleton cache
  + ``get_max_priority_for(champion_id)`` ship in ``ability_dps.py`` next to
  the existing rank-table code.
* ``compute_ability_dps`` + ``compute_burst_damage`` signatures relax their
  ``max_priority`` parameter from ``tuple[str,str,str] = ("Q","W","E")`` to
  ``Optional[Sequence[str]] = None`` - None routes through the per-champion
  override registry; explicit values still win. Both results gain a
  ``max_priority_source`` field tracking ``"override"`` / ``"champion"`` /
  ``"default"`` provenance.
* ``rank_items_by_ability_dps`` / ``rank_items_by_burst`` thread the override
  through the baseline + every candidate so the entire ranking uses the
  same priority. Result envelopes carry ``max_priority_source``.
* Server route ``_parse_max_priority`` returns ``Optional`` and passes None
  through when the operator doesn't specify, so the engine resolver kicks in.
  ``/ability-dps``, ``/rank-mage``, ``/burst``, ``/rank-assassin`` all
  surface ``max_priority_source`` in their JSON responses.

Phase 5.5 (s186, 2026-05-13 - per-champion combo_sequence overrides, ENGINE_VERSION 0.71.0):

* New ``agents/daemon_slayer/champion_combo_sequences.json`` registry (15
  entries - all 14 canonical assassins plus Briar). Zed → Q-W-E-R-Q2-AA
  (shadow Q double); Yone → Q-Q2-Q3-AA-E-W-R (chain knockup); Akali →
  Q-AA-E-R-Q2-AA-R2 (R recast within window); Leblanc → Q-W-E-R-Q2-AA
  (R mimic); the rest tighten the canonical openers. Default
  ``["Q","W","E","AA","R","AA"]`` fallback for the other 156 champions.
* Loader + singleton cache + ``get_combo_for(champion_id)`` +
  ``_resolve_combo_sequence(champion_id, explicit)`` ship in ``burst.py``
  next to ``DEFAULT_COMBO_SEQUENCE``.
* ``compute_burst_damage`` + ``rank_items_by_burst`` signatures relax
  ``combo_sequence`` from ``Sequence[str] = DEFAULT_COMBO_SEQUENCE`` to
  ``Optional[Sequence[str]] = None``; None routes through the per-champion
  override registry. ``BurstResult`` / ``BurstRankResult`` gain
  ``combo_sequence_source`` ("override" | "champion" | "default").
* Server route ``_parse_combo_sequence`` returns ``Optional`` and passes
  None through. ``/burst`` and ``/rank-assassin`` surface
  ``combo_sequence_source`` in their JSON responses.

Phase 4e (s187, 2026-05-13 - per-(champion, key) form_index overrides, ENGINE_VERSION 0.72.0):

* New ``agents/daemon_slayer/champion_form_index.json`` registry (5
  entries). Nidalee Q/W/E → 1 (cougar form has 5 damage blocks for
  Takedown vs human's 2 on Javelin Toss). Elise Q → 1 (spider Venomous
  Bite). Jayce Q → 1 (cannon Shock Blast - 2 blocks vs hammer leap's
  1). Hwei Q/W/E → first damage-bearing form (form 0 is a stance setup
  with zero damage blocks for each). LeeSin Q → 1 (Resonating Strike
  recast). Default empty dict (form 0 for all) for the other 167 champions.
* Loader + singleton cache + ``get_form_index_for(champion_id)`` +
  ``_resolve_form_index_overrides(champion_id, explicit)`` ship in
  ``ability_dps.py``. Caller-supplied dict merges with registry, with
  caller winning per-key - registry fills any keys the caller didn't
  override.
* ``compute_ability_dps`` / ``rank_items_by_ability_dps`` /
  ``compute_burst_damage`` / ``rank_items_by_burst`` all resolve
  form_index through the new helper. Results gain ``form_index_source``
  ("override" | "champion" | "default") + ``form_index_resolved`` (the
  merged dict actually used). Burst.py imports the resolver from
  ability_dps so the two scorers share resolution logic.
* No server route change - ``/ability-dps``, ``/rank-mage``, ``/burst``,
  ``/rank-assassin`` already accept ``form_index`` body field; the engine
  resolver kicks in when the field is absent and surfaces both new
  source/resolved fields in their JSON responses.

Phase 5.6 (s188, 2026-05-13 - per-attack on-hit proc damage, ENGINE_VERSION 0.73.0):

* New ``dps._per_attack_proc_damage()`` helper computes amortized per-AA
  on-hit damage (Wit's End +magic, BotRK Mist's Edge HP%, Statikk Shiv
  4-stack). Sister to ``_periodic_proc_dps``; only counts
  ``every_n_attacks`` procs (skips ``every_n_seconds``). Post-mit +
  post-mode + post-amps + magic-typed gets ``magic_amp``.
* ``DpsResult`` gains ``per_attack_on_hit_damage: float`` (default 0.0
  for empty builds; surfaced in ``to_dict()``); computed inline at the
  end of ``compute_dps`` using the same call_ctx / effects already
  resolved for the rotation pipeline.
* ``burst.compute_burst_damage`` now reads ``aa_probe.per_attack_on_hit_damage``
  and adds it to ``aa_base_per_hit`` so each AA token in the combo
  contributes the richer total. Notes line decomposes base + on-hit
  for explainability. Backward-compat preserved: builds without on-hit
  items see identical per-AA damage to pre-s188.
* **Spellblade NOT included** here (it's ``every_n_seconds``-based, not
  ``every_n_attacks``-based) - see Phase 5.7 below for the dedicated
  arm-by-spell-cast / consume-by-AA model that lands Spellblade
  contributions in burst combos.

Phase 5.9.15 (s202, 2026-05-14 - block_index expansion: Gangplank / Gnar / KSante / RekSai / Vayne / Yunara new + 12 key extensions on Zoe / Akshan / AurelionSol / Nasus / Poppy / Renekton / Rumble Q+R / Smolder Q+R / Viktor / Yuumi, ENGINE_VERSION 0.87.0):

* Pure data-only batch - no code changes. 18 new (champion, key)
  entries: 6 truly-new champions (Gangplank, Gnar, KSante, RekSai,
  Vayne, Yunara) + 12 key extensions on existing champions (Zoe W,
  Akshan R, AurelionSol Q, Nasus R, Poppy E, Renekton R, Rumble Q+R,
  Smolder Q+R, Viktor E, Yuumi R). Registry: 104 → 110 champions,
  143 → 161 entries.
* **Pattern A multi-hit single-target totals** (5 entries):
    - KSante R=2 (All Out dash + wall-strike 2×)
    - Vayne E=2 (Condemn dash + wall-slam 2.5×)
    - Yunara Q=2 filtered (Combined Passive + Active 2×)
    - Zoe W=1 filtered (3 empowered AAs from spell rotation 3×)
    - Viktor E=2 (Death Ray double-hit 1.29×)
* **Pattern B channel/duration totals** (7 entries):
    - Gangplank R=2 (Cannon Barrage 4-wave total 12× per-wave)
    - AurelionSol Q=2 (Breath of Light full 2.5s channel 26×)
    - Nasus R=1 filtered (Fury of the Sands full 15s target_max_hp_pct)
    - Renekton R=1 filtered (Dominus full 15s aura 30×)
    - Rumble R=2 (Equalizer max 4s channel 10×)
    - Yuumi R=2 filtered (Final Chapter 2 hits per target 2×)
    - Poppy E=1 filtered (Heroic Charge wall-slam total 2×)
* **Pattern C max-charge / max-distance amps** (3 entries):
    - Akshan R=1 filtered (Comeuppance max-charge bullet 3×)
    - Smolder R=1 filtered (Mouth of the Abyss max-distance 1.5×)
    - (Pattern shared with Pattern E channel for Rumble Q overheat)
* **Pattern D resource-state amps** (2 entries):
    - RekSai E=1 (Furious Bite max Fury → true damage 1.25×)
    - Smolder Q=1 (max-stack passive 1.75× - gear-INdependent)
* **Pattern E wall-stun terrain / charge condition amps** (3 entries):
    - Gnar R=1 filtered (GNAR! wall-stun amp 1.5×)
    - (Vayne E + Poppy E listed under Pattern A - both wall-stun)
    - Rumble Q=2 filtered (Total Enhanced damage during Danger Zone 1.5×)
* **Filtered-idx semantics** (9 of 18 entries have non-damage
  prefix blocks): Gnar R raw 0/2 'Movement Speed' + 'Disable
  Duration' stripped; Yunara Q raw 1 'Bonus Attack Speed' +
  raw 4-5 modifiers stripped; Zoe W raw 0-1 'Bonus Movement Speed'
  stripped; Akshan R raw 0-1 'Maximum Bullets' / 'Storing Interval'
  stripped; Nasus R raw 0-2 'Bonus Health' / 'Bonus Resistances' /
  'Increased Size' stripped; Poppy E raw 1 'Stun Duration' stripped;
  Renekton R raw 0-1 'Bonus Movement Speed' / 'Bonus Resistances'
  stripped; Rumble Q raw 1 'Increased Damage Per Second' (intermediate
  damage block at filtered idx 1; we pick filtered idx 2 = raw 4
  'Total Enhanced'); Smolder R raw 0 'Self Heal' stripped; Yuumi R
  raw 0-1 + 5-6 heal blocks stripped.
* **Reverts of 4 prior-batch skip rationales:** Gnar R (s198 'wall-
  stun terrain' → s202: operator-commits, same as Khazix Q isolation
  s196 / Xerath W center-spot s201), Vayne E (s198 'wall-stun
  terrain' → s202: same operator-commit framing), Poppy E (s199
  'wall-state target condition' → s202: same), Rumble Q (s199
  'Danger Zone heat decays mid-fight' → s202: operator commits to
  overheat Q burst).
* **6 deliberate skips documented inline:** Syndra W (block 2
  'Total Mixed' is just 1.12× block 0 - too marginal), Camille W
  (block 1 'Outer Cone Bonus' is target_max_hp_pct ONLY without
  flat - needs sum-of-blocks), Yunara W (block 0 'Initial' is
  HIGHER than block 2 'Total Expanded' - engine default correct),
  Smolder E (Meraki schema 'Minimum' label ambiguity carried from
  s198), Sona Q (block 1 is Power Chord bonus needing sum-of-
  blocks), Kayle E (Phase 4a target_missing_hp_pct plumbing - same
  pattern as s201 Kindred E drop).
* All 18 verified per-rank math against Meraki snapshot.
* Backward-compat preserved.
* Eighteenth consecutive override / proc-shape modeling improvement
  on the same template (s185-s202); eleventh pure-data batch in the
  block_index family. Cumulative coverage 161 (champion, key)
  entries across 110 champions (64% of the 171-champion roster).

Phase 5.9.14 (s201, 2026-05-14 - block_index expansion: Fizz / Galio / Garen / Graves / Janna / Jhin / Kennen / Taliyah / Teemo / Viego / Xerath / Yasuo / Ziggs, ENGINE_VERSION 0.86.0):

* Pure data-only batch - no code changes. 16 new (champion, key)
  entries across 13 new champions (3 multi-key: Jhin Q+R, Teemo E+R,
  Xerath W+R, plus single-key for Fizz/Galio/Garen/Graves/Janna/
  Kennen/Taliyah/Viego/Yasuo/Ziggs). Registry: 91 → 104 champions,
  127 → 143 entries.
* **Pattern A multi-hit single-target totals** (7 entries):
    - Graves Q=2 (End of the Line buckshot + return 2.89×)
    - Jhin Q=2 (Dancing Grenade Max Final Bounce after 3 minion
      deaths nearby, 2.05×)
    - Kennen R=1 filtered (Slicing Maelstrom all 6+ bolts on 1
      target, 7.5× per-bolt)
    - Taliyah Q=2 (Threaded Volley all 5 stones via Worked Ground,
      2.6×)
    - Teemo E=2 (Toxic Shot Total Poison 4-tick DoT, 2.67×)
    - Xerath R=1 filtered (Rite of the Arcane all 4-6 bullets on
      same target, 4-6×)
    - Ziggs E=2 (Hexplosive Minefield all 5 mines focused, 5×)
* **Pattern B fully-charged amps** (4 entries):
    - Galio W=1 filtered (Shield of Durand 2s commit, 3×)
    - Janna Q=2 (Howling Gale 3s max-charge, 1.55×)
    - Jhin R=1 (Curtain Call Maximum at max distance, 4×)
    - Viego Q=3 (Blade of the Ruined King fully-charged Soul Steal
      AA, 2×)
* **Pattern C channel/duration totals** (3 entries):
    - Fizz R=2 (Chum the Waters Gigalodon max-distance, 2×)
    - Garen E=1 (Judgment Increased per spin ramp on stationary
      target, 1.25×)
    - Teemo R=1 filtered (Noxious Trap full 4-tick poison, 4×)
* **Pattern D resource/positional amps** (2 entries):
    - Xerath W=1 (Eye of Destruction Increased center-spot, 1.67×)
    - Yasuo E=3 (Sweeping Blade Total Combined at max stacks, 2×)
* **Filtering notes** (filtered idx ≠ raw block idx; same lesson
  as s199 Shen Q / s200 Anivia R / Lillia Q / Poppy Q):
    - Galio.W raw block 0 'Magic Shield Strength' + blocks 1-2
      'Damage Reduction' (non-damage) → filtered idx 1 = raw block 4
      'Maximum Magic Damage'.
    - Kennen.R raw block 0 'Bonus Resistances' (non-damage) →
      filtered idx 1 = raw block 2 'Total Single-Target Damage'.
    - Teemo.R raw blocks 0-2 'Bounce Distance Cap' / 'Maximum
      Charges' / 'Slow' (non-damage) → filtered idx 1 = raw block 4
      'Total Magic Damage'.
    - Xerath.R raw block 0 'Number of Recasts' (non-damage) →
      filtered idx 1 = raw block 2 'Total Magic Damage'.
* **Reverts of prior skip rationale:** Xerath W (s198 'positional
  condition, defer to conditional schema lift' → s201: aligned with
  Khazix Q isolation framing shipped s196, same operator-commit
  semantics), Ziggs E (s198 'unrealistic 5-mine focus' → s201:
  operator commits to chokepoint setup, same as Ashe Q 5-AA focus
  in s199), Janna Q (s198 'low ratio 1.46× + support' → s201: 1.55×
  amp and support champions can route through /ability-dps for
  mage-builds), Yasuo E (s198 'stacks decay 10s' → s201: operator
  commits to E-stacking in burst setup, same as Twitch E 6-stack
  pre-burst rotation).
* **6 deliberate skips documented inline:** Seraphine Q (dispatcher
  routes to ds.hps), Taliyah E (1.04× ratio + misses initial impact
  block 0), Thresh E (per-soul scaling needs sum-of-blocks),
  Nidalee W (conflicts with s187 form_index=1 cougar), Shyvana E
  (Phase 4a parsing produces malformed interpolated base values),
  Kindred E (dropped during s201 implementation - Enhanced damage
  block has identical base + bAD to block 0; missing-HP amp lives
  entirely in unparsed_modifiers nested-format scaling that the
  Phase 4a parser cannot extract).
* All 16 verified per-rank math against Meraki snapshot.
* Backward-compat preserved: any unmapped champion or unchanged
  champion sees byte-identical output to pre-s201.
* Seventeenth consecutive override / proc-shape modeling improvement
  on the same template (s185-s201); tenth pure-data batch in the
  block_index family. Cumulative coverage 143 (champion, key)
  entries across 104 champions.

Phase 5.9.13 (s200, 2026-05-14 - rescue batch: Ambessa Drain + Anivia Empowered + Lillia + Nilah + Poppy + 7-entry block_index expansion, ENGINE_VERSION 0.85.0):

* Pure data-only batch - no code changes. 7 new (champion, key)
  entries (1 new champion Ambessa contributing 3 entries Q/W/E + 4
  key extensions on Anivia/Lillia/Nilah/Poppy). Registry: 90 → 91
  champions, 120 → 127 entries.
* **Rescues 4 previously-deferred mechanics:**
    - Ambessa Q/W (s196/s197/s198 deferred 'form swap') is actually a
      Drain-stack resource amp - operator commits, same model as
      Renekton Fury (s197).
    - Anivia R (s195 deferred 'channel ticks ambiguous') is the
      Empowered phase amp triggered after 1.5s+ channel commit, same
      model as Belveth E max-charge (s174).
    - Lillia Q (s199 'uncertain mechanic') is Q damage + Dream Dust
      AA bonus on Q-stacked target, same as Sett Q empowered-AA-
      followup (s196).
    - Nilah Q (s199 'uncertain 2-stack mechanic') is canonical max-
      stack-consumed empowered AA (2× Min per-AA), same as Twitch E
      Deadly Venom 6-stack (s198) and Tristana E full-stack (s199).
* **Pattern A multi-hit single-target totals** (3 entries):
    - Ambessa E=1 (Lacerate slash+thrust 2×)
    - Lillia Q=1 filtered (Q + Dream Dust AA 2×)
    - Poppy Q=1 filtered (Hammer Shock out + return 2×)
* **Pattern B resource-state amps** (3 entries):
    - Ambessa Q=1 (Cunning Sweep Drain Increased 2×)
    - Ambessa W=1 (Repudiation Drain Increased 1.5×)
    - Nilah Q=1 (Formless Blade Maximum empowered AA 2×)
* **Pattern C channel/duration commit** (1 entry):
    - Anivia R=1 filtered (Glacial Storm Empowered phase per-tick 3×)
* **Filtering notes** (filtered idx ≠ raw block idx):
    - Anivia.R raw block 1 'Slow' is non-damage → filtered idx 1 =
      raw block 2 'Empowered Damage per Tick'.
    - Lillia.Q raw blocks 0, 1 are Movement Speed (non-damage) →
      filtered idx 1 = raw block 3 'Total Mixed Damage'.
    - Poppy.Q raw blocks 1, 2, 3 are Slow / Minion-only → filtered
      idx 1 = raw block 4 'Total Physical Damage'.
* All 7 verified per-rank math against Meraki snapshot.
* Live-validated /ability-dps on :8893 lvl 11 vs 80/30/2000:
    - Anivia R baseline 19.80 → 21.88 (+10.5%)
    - Lillia Q 21.06 → 25.15 (+19.4%)
    - Poppy Q 11.51 → 20.22 (+75.7%)
    - Ambessa Q 5.76 → 8.49 (+47.4%)
    - Ambessa W 5.76 → 6.51 (+13.0%)
    - Ambessa E 5.76 → 6.61 (+14.7%)
    - Nilah Q 5.14 → 9.36 (+82.2%)
* Backward-compat preserved: any unmapped champion or unchanged
  champion sees byte-identical output to pre-s200.
* Sixteenth consecutive override / proc-shape modeling improvement
  on the same template (s185-s200); ninth pure-data batch in the
  block_index family. Intentionally smaller batch (7 entries vs
  s198's 20 / s199's 17) - focus is rescuing prior-batch skip-list
  entries against improved mechanic understanding, not net-new
  candidate scanning.

Phase 5.9.12 (s199, 2026-05-14 - Aatrox sweet-spot / Ashe Flurry / Karthus Defile / 17-entry block_index expansion, ENGINE_VERSION 0.84.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 17 new (champion, key)
  entries (6 new champions + 11 key extensions on existing). Registry:
  84 → 90 champions, 103 → 120 (champion, key) pairs.
* **Pattern A - Multi-hit single-target totals** (8 entries):
    - Ashe Q=2 (Ranger's Focus all 5 enhanced AAs, 5×)
    - Nunu E=1 (Snowball Barrage 3-snowball cap, 3×)
    - Samira W=1 (Blade Whirl 2-rotation total, 2×)
    - Shen Q=2 (Twilight Assault 3-AA empowered, 3×)
    - Swain Q=2 (Death's Hand all 5 bolts at point-blank, 2×)
    - Viktor Q=2 (Power Transfer ability + empowered AA, 1.7×)
    - Xayah Q=1 (Double Daggers out + return, 2×)
    - Zac Q=1 (Stretching Strikes both arms on target, 2×)
* **Pattern B - Positional/sweet-spot amps** (3 entries):
    - Aatrox Q=1 (Q1 Edge of the Blade sweet-spot, 1.7×)
    - Shaco E=2 (Two-Shiv Poison backstab, 1.5×)
    - Talon Q=1 (Noxian Diplomacy champion crit, 1.5×)
* **Pattern C - Resource-state amps** (2 entries):
    - Tristana E=4 (Explosive Charge max-stack, 2× block 1)
    - Udyr Q=1 (Wilding Claw Awakened 2-AA, 2×)
* **Pattern D - Channel total** (1 entry):
    - Karthus E=2 (Defile per-second tick, 4× per-tick)
* **Pattern E - Direct-hit primary target** (2 entries):
    - Sejuani R=1 (Glacial Prison direct stun, ~2×)
    - Nautilus R=2 (Depth Charge primary hit, ~2×)
* **Pattern F - Execute amp** (1 entry):
    - Fiddlesticks W=3 (Bountiful Harvest low-HP execute, 2× base + missing-HP)
* All 17 verified per-rank math against the Meraki snapshot. Math-level
  sanity tests pin three: Ashe Q block 2 = exact 5× block 1 (per-AA →
  flurry); Karthus E block 2 = exact 4× block 1 (per-tick → per-second);
  Tristana E block 4 = exact 2× block 1 (no-stack → full-stack).
* **Multi-key extensions:** Aatrox now {W:3, Q:1}, Karthus now
  {Q:1, E:2}, Nautilus now {E:2, R:2}, Nunu now {W:1, E:1}, Samira now
  {R:1, W:1}, Sejuani now {W:2, R:1}, Talon now {W:2, R:2, Q:1}, Udyr
  now {R:1, Q:1}, Viktor now {R:2, Q:2}, Zac now {R:2, Q:1},
  Fiddlesticks now {R:1, W:3}.
* **Deliberately skipped:** Diana R (multi-target pull, not single-burst),
  Gnar R (wall-stun terrain), Lillia Q (uncertain mechanic), Poppy E/Q
  (wall/duration target-state), Rumble Q (heat decay, defer to
  calibration), Teemo R (4-shroom focus unrealistic), Viktor E
  (Augmented system removed), Yasuo E (stacks decay), Yunara (new champ
  unverified), Yuumi R (5-wave model mismatch), Zoe W (stolen-spell
  resource), Nilah Q (uncertain 2-stack mechanic).
* Backward-compat preserved: any unmapped champion sees byte-identical
  output to pre-s199. Fifteenth consecutive override / proc-shape
  modeling improvement on the same template (s185-s199); eighth pure-
  data batch in the block_index family.

Phase 5.9.11 (s198, 2026-05-14 - bruiser/jungler/utility/marksman block_index expansion, ENGINE_VERSION 0.83.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 20 new (champion, key)
  entries (17 new champions + 2 key extensions on existing Sion and
  Vladimir; XinZhao contributes 2 entries Q+W). Registry: 67 → 84
  champions, 83 → 103 (champion, key) pairs.
* **Pattern A - Multi-hit single-target totals** (12 entries):
    - Sylas Q=3 (Chain Lash initial + delayed pulse, 3.33×)
    - XinZhao Q=1 (Three Talon Strike 3 empowered AAs, 3×)
    - XinZhao W=2 (Wind Becomes Lightning slash + thrust, 3.71×)
    - Zac R=2 (Let's Bounce all 4 bounces same target, 2.5×)
    - Maokai E=1 (Sapling Toss enhanced dual-hit, 2×)
    - Kayn Q=1 (Reaping Slash both passes, 2×)
    - Sejuani W=2 (Winter's Wrath swipe + thrust total, 2.89×)
    - Neeko Q=2 (Blooming Burst initial + 2 blooms, 2.04×)
    - Nasus E=2 (Spirit Fire initial + 5 full-duration ticks, 2×)
    - Nami E=1 (Tidecaller's Blessing 3 empowered AAs, 3×)
    - Ornn R=2 (Call of the Forge God initial + 2nd ram, 2×)
    - Twitch E=3 (Contaminate at 6 Deadly Venom stacks, 4.5×)
* **Pattern B - Fully-charged amps** (4 entries):
    - Vi Q=1 (Vault Breaker fully-charged 1.25s, 2.5×)
    - Sion R=1 (Unstoppable Onslaught max-speed, 2.67×)
    - Irelia W=1 (Defiant Dance fully-charged 2s, 3×)
    - Yuumi Q=1 (Prowling Projectile untargeted max-distance, 1.62×)
* **Pattern C - Resource-state amp** (1 entry):
    - Jax E=1 (Counter Strike at 2 dodge stacks, 2×)
* **Pattern D - Channel/duration totals** (3 entries):
    - Udyr R=1 (Wingborne Storm full 8 ticks, 8×)
    - Vladimir W=1 (Sanguine Pool full 4-second duration, 4×)
    - Viktor R=2 (Chaos Storm initial + 6 ticks full channel, 4.48×)
* All 20 verified per-rank math against the Meraki abilities snapshot
  (block N's base + scaling fields match the canonical-condition
  multiple of block 0's components). Math-level sanity tests pin two:
  Udyr R block 1 = exact 8× block 0 (all ranks); Vi Q block 1 = exact
  2.5× block 0 (all 5 ranks).
* **Deliberately skipped this batch** (documented in registry rationale):
  Evelynn Q (target-state charm condition - schema lift bucket),
  Vayne E (target-state wall-stun terrain condition), Vladimir Q
  (passive-empowered AA, on-hit not per-cast), Xerath W (positional
  target-state amp), Ziggs E (5-mine focus unrealistic), Janna Q (low
  ratio + utility ult), Seraphine Q (enchanter-class, dispatcher routes
  to ds.hps), Yasuo E (resource-state decay rate too fast for clean
  commit model), Heimerdinger Q/R (turret-based not per-cast),
  Sona R / Lux Q/E/R / Veigar Q (single-block, engine default correct),
  Smolder Q / Smolder E (max-stacks-with-gear / Meraki schema
  ambiguity).
* Backward-compat preserved: any unmapped champion (Zed, Yasuo, etc.)
  sees byte-identical output to pre-s198. Fourteenth consecutive
  override / proc-shape modeling improvement on the same template;
  seventh pure-data batch in the block_index family.

Phase 5.9.10 (s197, 2026-05-14 - assassin/fighter resource + utility block_index expansion, ENGINE_VERSION 0.82.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 20 new (champion, key)
  entries across 18 new champions (registry 49 → 67). Same walker
  logic; zero engine math change. Spans five sub-patterns: multi-hit/
  channel/mark totals, fully-charged amps, resource-state amps,
  execute/channel-duration amps, multi-charge/multi-fire totals.

Phase 5.9.9 (s196, 2026-05-14 - extended multi-hit/condition-amp block_index expansion, ENGINE_VERSION 0.81.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 17 new (champion, key)
  entries (14 new champions + 3 key extensions on Akali, Cassiopeia,
  Morgana). The s191/s192 walker logic (per-token-canonical lookup +
  base-key fallback) handles all new entries transparently. Registry:
  35 → 49 champions, 17 new (champion, key) pairs.
* **Pattern A - Multi-hit single-target totals** (12 entries):
    - Akali E=2 (E1 Shuriken Flip + E2 grappling-hook dash, ~3.33×)
    - Akshan Q=1 (Avengerang ricochet out + return, 2×)
    - Cassiopeia W=1 (Miasma full duration, 5×)
    - Chogath E=1 (Vorpal Spikes 3-hit total, 3×)
    - Draven R=1 (Whirling Death out + return, 2×)
    - Lillia W=1 (Watch Out! Eep! center hit, 3×)
    - Morgana R=1 (Soul Shackles tether full duration, 2×)
    - Nautilus E=2 (Riptide 3-wave same target, 2×)
    - Riven Q=1 (Broken Wings 3-cast Q-Q-Q combo total, 3×)
    - Sett Q=1 (Knuckle Down both empowered AAs, 2×)
    - Skarner Q=1 (Shattered Earth empowered 3-hit chain, 3×)
    - Soraka E=1 (Equinox immediate + delayed proc total, 2×)
* **Pattern B - Fully-charged / condition amps** (5 entries):
    - Gragas Q=1 (Barrel Roll max-fermented 4s hold, 1.5×)
    - Karthus Q=1 (Lay Waste single-target enhanced, 2×)
    - Khazix Q=1 (Taste Their Fear isolation amp, 2.1×)
    - KogMaw R=1 (Living Artillery low-HP execute, 2×)
    - Pantheon Q=1 (Comet Spear fully-charged hurl, 2.2×)
* All 17 verified per-rank math against the Meraki abilities snapshot -
  block N's base + scaling fields match the exact canonical-condition
  multiple of block 0's components (e.g., Akshan Q block 1 base 10/50/90/
  130/170 = exact 2× block 0's 5/25/45/65/85; Riven Q block 1 base 135/
  225/315/405/495 = exact 3× block 0's 45/75/105/135/165).
* **Deliberately skipped this batch** (documented in registry rationale):
  Nidalee Q (form_index=1 cougar override from s187 conflicts with block_
  index=1 human Javelin max-distance interpretation; needs conditional
  form-specific schema lift), Kassadin R (resource-state stack condition,
  belongs in carried-forward conditional-resource-state bucket), Aatrox
  W (CC-conditional pull-back trigger), Akshan R (Comeuppance bullet
  charge, resource-state), Ambessa Q/W/E (form swap mechanics need per-
  form analysis), Gangplank R (Upgrade choices need per-upgrade modeling),
  Jhin R (4-shot ult fits combo_sequence better than block_index), Hwei R
  (channel full-duration, lower-impact deferral), Gwen R / KSante R
  (multi-form / form-swap mechanics), Karthus E/R, Mel Q, Naafiri Q,
  Olaf Q, Nasus E.
* Backward-compat preserved: any unmapped champion (Zed, etc.) sees byte-
  identical output to pre-s196. Twelfth consecutive override / proc-shape
  modeling improvement on the same template; fifth pure-data batch in the
  channel/total/charge family (s191 seed, s193 channels, s194 calibration
  follow-up, s195 multi-hit/charge/recast, s196 extended multi-hit/
  condition-amp).

Phase 5.9.8 (s195, 2026-05-14 - multi-hit/charge/recast block_index expansion, ENGINE_VERSION 0.80.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 13 new (champion, key)
  entries across four established sub-patterns. The s191/s192 walker
  logic (per-token-canonical lookup + base-key fallback) handles all
  new entries transparently. Registry: 25 → 35 entries.
* **Multi-hit single-target totals** (operator commits to focus all
  hits/bolts/missiles on one target):
    - Ahri W=2 (Fox-Fire 3-bolt total)
    - Kaisa Q=2 (Icathian Rain missile-focus total)
    - Lulu Q=3 (Glitterlance both passes)
    - Sivir Q=2 (Boomerang out + back)
    - Talon W=2 (Rake out + return)
    - Talon R=2 (Shadow Assault unstealth chain)
    - Velkoz W=2 (Void Rift both halves)
    - Ekko Q=3 (Timewinder out + return)
* **Fully-charged amps** (operator commits to wind-up time in burst):
    - Varus Q=1 (fully-charged Piercing Arrow, 1.5× block 0)
    - Zoe Q=1 (long-distance Paddle Star post-E, 2.5× block 0)
    - Vladimir E=1 (2-charge Tides of Blood, 2× block 0 + 4× HP scaling)
* **Recast amps** (operator commits to both stages in window):
    - Camille Q=2 (Precision Protocol 2nd cast, 2× block 0)
* **CC-conditional duration totals** (operator commits root + duration):
    - Morgana W=3 (Tormented Shadow full duration vs rooted)
* All 13 verified per-rank math against Meraki snapshot (block N's
  base + scaling fields match the sum of components from blocks 0..N-1
  for the canonical-condition case - e.g., Ahri W block 2 base 64 = 40
  initial + 12×2 subsequent at rank 1, ap_pct 64% = 40% + 12%×2).
* Backward-compat preserved: any unmapped champion sees byte-identical
  output to pre-s195. Tenth consecutive pure-data expansion of the
  override registry pattern; fourth batch in the channel/total/charge
  family (s191 seed, s193 channels, s194 calibration follow-up, s195
  multi-hit / charge / recast).

Phase 5.9.7 (s194, 2026-05-14 - calibration-follow-up block_index expansion, ENGINE_VERSION 0.79.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 8 new (champion, key)
  entries closing the s193 carry-forward calibration list. Same
  "per-tick → total" or "min → max amped variant" pattern as s193;
  these are the lower-impact-but-still-meaningful entries deferred
  from s193 for triage. Now the channel/aura/charge family closes
  systematic under-counting for non-mage/non-assassin ability-based
  champions queried via /ability-dps + /burst direct routes:
    - Corki W (Valkyrie fire-trail full-duration total - 5× block 0)
    - Corki E (Gatling Gun 4-second full-channel total - 16× block 0)
    - Hecarim W (Spirit of Dread full-aura total - 5× block 0)
    - Hecarim E (Devastating Charge max-charge variant - 2× block 0)
    - Jayce Q (Shock Blast through Acceleration Gate - 1.4× block 0;
      layered on s187's Jayce Q form_index=1 cannon-form override,
      orthogonal: form_index selects cannon form 1 → block_index then
      selects the gate-amped block 1 within that form)
    - Jayce W (Lightning Field hammer-form full-aura total - 4× block 0)
    - Rell R (Magnet Storm full 4-second channel - 8× block 0)
    - DrMundo W (Heart Zapper full drain channel - 16× block 0; block 2
      recast detonation is a separate +25% one-time burst not summed in
      current single-block_index schema, minor under-count, acceptable)
* All entries verified against Meraki ATTR names ('Total Magic/Physical
  Damage', 'Maximum Physical Damage', 'Increased Damage') in
  champion_abilities.json - clean per-tick → total or min → max amped.
* Backend-impact A/B on /ability-dps at level 11 vs 80/30/2000:
    Singed-class channels (8-16× lift) for the Corki E + Hecarim W +
    Jayce W + Rell R + DrMundo W subset; Jayce Q + Corki W see 1.4×
    and 5× lifts respectively; Hecarim E 2× lift on max-charge.
* No engine code changed - the s191/s192 walker logic (per-token-canonical
  lookup + base-key fallback) handles all new entries transparently.
* Backward-compat preserved: any unmapped champion (Aatrox, Zed-without-
  Akali-style-R, etc.) sees byte-identical output to pre-s194.

Phase 5.9.6 (s193, 2026-05-14 - channeled-ability block_index expansion, ENGINE_VERSION 0.78.0):

* Pure data-only batch - no code changes, just expands the s191
  ``champion_block_index.json`` registry with 8 new champion entries
  plus extends Anivia's existing entry to add her Q.
* New entries cover the "per-tick → total" gap for channeled / duration
  abilities where the engine's default "first damage block" picked the
  per-tick value but the per-cast contribution is the full-channel total:
    - Alistar E (Trample channel)
    - AurelionSol E (Singularity duration)
    - Fiddlesticks R (Crowstorm full channel)
    - MissFortune E (Make It Rain duration)
    - Samira R (Inferno Trigger spray total)
    - Singed Q (Poison Trail full duration)
    - Velkoz R (Life Form Disintegration Ray full channel)
    - Syndra R (Maximum at 7+ Dark Sphere stacks)
* Anivia gets Q=2 added (Total Magic Damage = initial pass + detonation
  combined; her existing E=1 stays for chilled-target amp).
* Backend-impact A/B on /ability-dps at level 11 vs 80/30/2000:
    Singed Q       +182% (4.06 → 11.46 adps)
    Fiddlesticks R +125% (5.24 → 11.81 adps)
    Anivia Q+E     +105% (9.66 → 19.80 adps)
    AurelionSol E   +65% (1.99 →  3.29 adps)
    Velkoz R        +23% (13.84 → 17.04 adps)
    MissFortune E   +17% (9.97 → 11.64 adps)
    Syndra R        +10% (25.55 → 28.06 adps)
* The s191 + s192 walker logic (per-token-canonical lookup + fallback)
  remains unchanged - this batch only ships JSON entries.

Phase 5.9.5 (s192, 2026-05-14 - token-variant block_index for Akali R, ENGINE_VERSION 0.77.0):

* Closes s191 carry-forward (a). Akali R has 3 damage blocks in the
  Meraki snapshot - block0 "Magic Damage" with bonus-AD scaling (R1
  base cast), block1 "Minimum Magic Damage" (R2 vs full-HP target),
  block2 "Maximum Magic Damage" (R2 max-execute scaling via missing-HP
  curve). Pre-s192, the burst walker evaluated R and R2 tokens with
  the SAME block_index from the s191 per-(champion, key) registry -
  setting Akali R=2 globally would have double-counted R1's execute
  amp (R1 doesn't have it in-game).
* ``compute_burst_damage`` walker now does TOKEN-CANONICAL lookup first
  (``block_overrides.get(canonical)`` - e.g. ``"R2"``), falling back to
  BASE-KEY lookup (``block_overrides.get(ability_key)`` - e.g. ``"R"``).
  Operator's per-call dict still wins per-token; the registry fills
  any tokens the caller didn't override.
* ``champion_block_index.json`` registry gains Akali entry
  ``{"R": 0, "R2": 2}``. R1 → block 0 (220 raw at rank 1, retains bAD
  scaling); R2 → block 2 (420 raw at rank 1 + 90% AP - the missing-HP
  max-execute scaling).
* ``compute_ability_dps`` is unaffected - it iterates base spell keys
  (Q/W/E/R) and the resolver's R2-keyed entry is simply absent from
  its lookup. Token-variant entries only fire in the burst walker.
* Live verified: Akali burst 787.9 → 941.7 (+154, +20%) on the s186
  registry combo Q-AA-E-R-Q2-AA-R2. R1 row still raw=220 / final=169.2;
  R2 row jumps to raw=420 / final=323.1 (+154 from the now-doubled
  base + 60pp AP scaling delta).
* Schema is forward-compatible - future per-token entries (Yone Q1/Q2/Q3
  if Meraki ever ships per-stage blocks, Leblanc mimic-Q once ingested,
  etc.) drop in without code changes.

Phase 5.9 (s191, 2026-05-14 - per-(champion, key) damage block_index overrides, ENGINE_VERSION 0.76.0):

* A minority of champions have a later damage block in their canonical
  ability form that represents the realistic burst-window value: Cassi E
  block1 "Total Enhanced Damage" (vs poisoned), Anivia E block1
  "Enhanced Damage" (vs chilled), Diana W block2 "Total Magic Damage"
  (all 3 orbs), Veigar R block1 "Maximum Magic Damage" (executed target),
  Brand W block1 "Increased Damage" (vs CC'd), etc. Pre-s191, the
  ``"first"`` strategy locked all callers to block 0 - under-scoring
  these mages and assassins systematically.
* New ``ability_dps._select_blocks`` strategy ``"indexed"`` accepts a
  ``block_index`` parameter (default 0). New ``"indexed"`` is added to
  ``_BLOCK_STRATEGIES`` alongside ``"first"`` / ``"sum"`` / ``"max"``.
  Out-of-range indexes clamp to the last damage block (forward-compat
  for patches that add extra blocks).
* New ``ability_dps.{_BLOCK_INDEX_PATH, _load_block_index_table,
  reset_block_index_cache, get_block_index_for,
  _resolve_block_index_overrides}`` mirror the Phase 4e form_index
  registry (s187) - singleton-cached JSON loader + per-(champion, key)
  map. Caller's explicit dict still wins per-key; the registry fills
  any keys the caller didn't override.
* New ``agents/daemon_slayer/champion_block_index.json`` seed registry
  ships 12 entries across 11 champions:

    Ahri Q=1, Anivia E=1, Aurora Q=2, Belveth E=2,
    Brand W=1 + R=1, Cassiopeia E=1, Diana W=2, Evelynn R=1,
    Karma W=1, Veigar R=1, Vex R=2.

* ``compute_ability_dps`` and ``compute_burst_damage`` gain
  ``block_index_overrides: Optional[dict[str, int]]`` (default None →
  resolves via registry). Per-spell loop switches to ``"indexed"``
  strategy for keys present in the resolved map; keys without an entry
  honor the caller-supplied global ``block_strategy``.
* ``AbilityDpsResult`` + ``AbilityDpsRankResult`` + ``BurstResult`` +
  ``BurstRankResult`` all gain ``block_index_source: str`` ("override"
  | "champion" | "default") + ``block_index_resolved: dict[str, int]``
  (the merged map actually used). ``to_dict()`` carries both.
* Four server routes (``/ability-dps``, ``/rank-mage``, ``/burst``,
  ``/rank-assassin``) accept a new ``block_index`` JSON dict body field.
  Shared ``_parse_block_index`` decoder mirrors ``_parse_form_index``.

Phase 5.8 (s190, 2026-05-13 - Sundered Sky Lightshield Strike in burst, ENGINE_VERSION 0.75.0):

* Sundered Sky (6610 + Arena mirror 226610) carries a Lightshield Strike
  ``PeriodicProc`` (``name="Lightshield Strike"``, ``every_n_seconds=8.0``).
  The engine schema explicitly keeps Lightshield Strike OUT of the
  spellblade unique-passive family (distinct in-game label, longer CD,
  no dedup), so pre-s190 it was invisible in burst combos - same gap as
  Spellblade pre-s189.
* New ``dps._lightshield_strike_per_proc_damage()`` mirrors the
  Spellblade helper but filters by ``proc.name == "Lightshield Strike"``.
  Returns ``(per_proc_damage, item_name)`` with the standard
  mitigation / mode / amp pipeline. Empty builds yield ``(0.0, "")``.
* ``DpsResult`` gains ``lightshield_strike_per_proc_damage: float`` +
  ``lightshield_strike_item_name: str`` (default 0.0 / "").
  ``compute_dps`` populates after the existing Spellblade block.
* ``burst.compute_burst_damage`` extends the combo walker with a second
  arm-consume state machine: ``lightshield_armed`` set by any ability
  cast, ``lightshield_procs_fired`` capped at 1 per combo (Sundered
  Sky's 8s real CD doesn't permit re-arming within a 2-3s burst window).
  AA branch consumes both Spellblade AND Lightshield independently
  when armed - a build with Sundered Sky + Trinity Force lands BOTH
  procs on the AA following the first ability cast.
* ``BurstResult`` gains ``lightshield_strike_procs: int`` +
  ``lightshield_strike_damage: float`` + ``lightshield_strike_item_name: str``.
  Notes block reports per-combo fired count + total damage; surfaces an
  idle diagnostic when the build has Sundered Sky but the combo doesn't
  exercise it.

Phase 5.7 (s189, 2026-05-13 - Spellblade-in-burst, ENGINE_VERSION 0.74.0):

* Spellblade items (Trinity Force / Lich Bane / Essence Reaver / Iceborn
  Gauntlet / Dusk and Dawn / Divine Sunderer / Sheen / Bloodsong - plus
  Arena mirrors) all carry ``unique_passive_key="spellblade"`` and use
  ``PeriodicProc.every_n_seconds`` (3.0 or 1.5). Pre-s189, they were
  invisible to ``burst.py`` because s188's per-attack helper only counts
  ``every_n_attacks`` procs.
* New ``dps._spellblade_per_proc_damage()`` returns the build's
  Spellblade per-proc damage value (already mitigated + mode-mult'd +
  amp-applied). ``collect_effects`` dedups via ``unique_passive_key``
  first-seen-wins, so at most one Spellblade survives per build.
* ``DpsResult`` gains ``spellblade_per_proc_damage: float`` +
  ``spellblade_item_name: str`` (default 0.0 / ""); surfaced in
  ``to_dict()``. ``compute_dps`` populates both after the existing
  per-attack on-hit block.
* ``burst.compute_burst_damage`` walks the combo with a
  ``spellblade_armed: bool`` flag - any ability token (P/Q/W/E/R or
  repeat variant) sets armed=True; AA token consumes (armed → fire
  proc → armed=False; adds proc damage to that ComboCast's
  ``final_damage``). Tracks ``spellblade_procs_fired`` +
  ``spellblade_damage_total`` for surfacing on ``BurstResult``. Real
  1.5s internal CD is irrelevant in a single-combo window - the arming
  gate is the binding constraint (fresh spell-cast required to re-arm),
  same architectural pattern as s180's no-cooldown-sequencing decision.
* ``BurstResult`` gains ``spellblade_procs: int`` +
  ``spellblade_damage: float`` + ``spellblade_item_name: str``. Notes
  block reports per-combo fired count + total damage; surfaces an idle
  diagnostic when the build has Spellblade but the combo template
  doesn't exercise it (e.g. operator-supplied pure-AA combo).

Phase 4(d) (2026-05-18 - candidate unique_passive_key exposure, ENGINE_VERSION 1.4.0):

* All 6 ranker ``*RankedItem`` dataclasses gain ``unique_passive_key:
  str = ""`` (+ ``to_dict()``), populated unconditionally from the
  candidate's own ``cand_eff.unique_passive_key`` - not just on dead
  collision like ``dead_unique_key``. Surfaces the positive "this item
  locks the <family>" signal. Additive + backward-compatible (default
  "", existing consumers ignore the new key, no math touched).
* Mirrored in the 6 ``core/daemon_slayer_client.py`` client dataclasses
  (field + ``from_dict``) and the 6 ``rank_for_primary_archetype``
  envelope branches. ``core/build_order.BuildStep`` gains
  ``locked_family`` (consumes the new key) - the positive counterpart
  to its existing ``excluded_family``.
"""

ENGINE_VERSION = "1.4.0"
