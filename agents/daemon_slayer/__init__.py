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

Stat-growth correctness fix (2026-05-19 - Riot quadratic per-level
scaling, ENGINE_VERSION 1.5.0):

* ``stats.py`` scaled champion per-level base stats LINEARLY
  (``base + perlevel * (level - 1)``); Riot's in-game growth is
  QUADRATIC: ``base + perlevel * growth_multiplier(level)`` where
  ``growth_multiplier(n) = (n - 1) * (0.7025 + 0.0175 * (n - 1))``.
  The two coincide ONLY at level 1 (multiplier 0) and level 18
  (multiplier exactly 17.0); for levels 2..17 the old code over-stated
  every per-level base stat (hp/mp/regen/armor/mr/ad). Real bug, not a
  modeling choice - cross-checked vs the canonical Riot/League-wiki
  formula and lolmath's growth() primitive.
* New ``stats.growth_multiplier(level)`` + ``stats.scaled(base,
  perlevel, level)``; the 8 ``CHAMPION_SCALING_RULES`` entries
  (hp/mp/hpregen/mpregen/armor/mr/ad/crit) repointed from the deleted
  ``linear`` to ``scaled``. Attack speed (``attack_speed_scaling``)
  was already correct Riot AS math and is untouched. Single
  application point (``engine._scale_champion_base``) - no double
  scaling. Per-level ability lambdas in ``_effects_data.py`` are
  intentionally linear ability scalings and are unaffected.
* Level-1 and level-18 numeric pins are stable (endpoint identity);
  mid-level DPS/EHP/burst/stats pins shift lower and were rebaselined
  to the corrected, hand-proven engine output.

Multi-source percent-pen / percent-reduction composition fix
(2026-05-19 - audit lane 1, ENGINE_VERSION 1.9.1):

* Prior ``effects.effective_target_armor`` /
  ``effective_target_mr`` summed ``armor_pen_pct`` /
  ``magic_pen_pct`` / ``armor_reduction_pct`` / ``mr_reduction_pct``
  directly across all items. League's documented rule is
  MULTIPLICATIVE composition: two 35% pen sources yield
  ``1 - 0.65 * 0.65 = 0.5775`` (57.75%) effective pen, NOT 0.70. The
  additive bug OVER-penetrated multi-pen builds (LDR + Serylda's,
  LDR + Mortal Reminder + Serylda's, Void Staff + Cryptbloom, Black
  Cleaver + Obsidian Cleaver). Single-pen-item builds are unaffected
  (composition of one factor is the factor); zero-pen builds are
  unaffected (empty product is 1.0).
* New private helper ``effects._composed_keep_factor(pcts)`` returns
  ``Pi (1 - p_i)``; the four % layers are now ``1 - keep_factor``.
  Pipeline order unchanged (flat-red -> %-red -> %-pen -> flat-pen).
  +8 audit tests in ``test_engine_math_correctness_pipeline_c.py``
  ``MultiplicativePenCompositionTests`` (RED-then-GREEN; 6 of 8
  failed pre-fix, all 8 pass post-fix; the 2 unchanged single-source
  / zero-source cases are explicit anti-regression guards).
* No existing DS test required rebaseline (the prior fixture builds
  carried at most one %-pen item per build path; the test_rank_assassin
  3-pen sentinel was a "raises" path, not a math assertion).

Lethality 1:1 conversion fix (2026-05-19 - audit lane 6,
ENGINE_VERSION 1.10.0):

* Prior ``effects.effective_target_armor`` folded lethality into the
  flat-pen sum at the pre-V14.1 scaling ``lethality * (0.6 + 0.4 *
  level / 18)`` (62.22% at L1 ramping to 100% at L18). Riot V14.1
  (2024-01) REMOVED that level scaling - lethality now grants its
  full value as flat armor pen at every caster level. The engine
  sits on patch 16.10.x (well past V14.1) so the 1:1 rule is the
  correct math. The pre-V14.1 formula UNDER-applied lethality at
  every level except 18, max 37.78 percentage points at L1; this
  systematically under-scored every lethality item in the engine
  rank/build for early-to-mid-game champion levels.
* ``effects.py`` lethality fold simplified: when ``level`` is
  supplied and ``lethality_total > 0``, the contribution is now
  ``pen_flat += lethality_total`` (1.0 factor at every level). The
  ``level`` parameter is retained on the signature for back-compat
  with the original Phase 4 batch 30 contract and for the
  "level=None means lethality contributes nothing" invariant on
  the non-DPS path.
* +1 RED-then-GREEN audit test
  (``ArmorPenPipelineOrderTests.test_lethality_is_one_to_one_flat_pen_post_v14_1``)
  pinning the 1:1 rule at L1/L6/L11/L18. 9 existing tests pinned
  to the pre-V14.1 formula were rebaselined to the 1:1 rule:
  4 in ``LethalityScalingTests``, 2 in ``LethalityEngineWireInTests``,
  1 in ``SpectralCutlassLethality``, 1 in
  ``Batch32LethAllyPromotionsTests``, 1 in ``Batch38ActiveItemTests``
  (renamed _scales_with_level -> _level_invariant_post_v14_1), 1 in
  ``LethalityLevelScaledDerivation`` wireable sim (renamed
  _scales_with_caster_level -> _one_to_one_post_v14_1). Source:
  League wiki Armor_penetration "Lethality now grants the full amount
  as flat armor penetration at all levels with no scaling. ... In
  V14.1 lethality was changed back to no longer scale by level."
"""

ENGINE_VERSION = "1.44.0"
# 1.44.0 (cc_conditional wave 7 tag schema lift - COND_FRENZY_STATE +
# COND_RANGE_GATED forward-marker, 2026-05-22):
#
# Closes item 147 carry (l) "Briar frenzy + Sylas range REJECTs STILL
# need new condition tag constants (separate schema lift)". Ships the
# 2 long-deferred condition tag constants ``COND_FRENZY_STATE`` and
# ``COND_RANGE_GATED`` as a FORWARD-MARKER schema-lift seam. NO new
# registry entries this wave - the schema lift unblocks future entries
# without a separate engine bump.
#
# NEW condition tag constants:
#   * ``COND_FRENZY_STATE`` = "frenzy_state" - champion enters a self-
#     empowered state (Briar W Blood Frenzy, Renekton Fury threshold,
#     Volibear R passive form, Aatrox post-R passive) that gates an
#     empowered variant of another spell with first-order CC.
#   * ``COND_RANGE_GATED`` = "range_gated" - CC fires only when the
#     cast lands within a specific range band (close-range or max-
#     range). Distinct from COND_TERRAIN (positioning vs map geometry)
#     and COND_NTH_HIT (stack accumulation).
#
# Both tags registered in ``_DEFAULT_CONDITION_PROBABILITY`` with
# calibrated midpoint 0.4 (mid-low - the empowered-state / range-band
# prerequisite is operator-controlled but not guaranteed; calibration
# sits below COND_DUAL_ENEMY 0.6 + COND_NTH_HIT 0.7 midpoints but
# above COND_TERRAIN 0.3 floor). Both exported via ``__all__`` so
# external readers see them as public taxonomy. Operator-tunable via
# the per-tag override JSON loader.
#
# Registry total UNCHANGED at 36 entries / 32 champions. The item 147
# carry-forward named Briar frenzy + Sylas range as canonical REJECT
# candidates for these tags. A Meraki 16.10.1 re-verify during this
# run found: (1) Sylas E2 Abduct stuns on hook hit regardless of cast
# range (the item 142 REJECT note calling it range-conditional was
# incorrect); (2) Briar W has 2 forms (Blood Frenzy + Snack Attack)
# but the Meraki extract is parse-stripped to damage_blocks only - the
# leveling/effects detail needed to verify a frenzy-empowered Q or R
# CC mechanic is absent at parse-strip level. Future entries populate
# when a Meraki-verifiable mechanic surfaces (e.g. Renekton W
# empowered cast during Fury, Aatrox passive-empowered abilities,
# Volibear R passive form). The forward-marker schema lift is the
# deliverable.
#
# Mirrors the s112 ``STAT_GRANT_CALC_KEYS`` empty-registry pattern at
# ENGINE 1.22.0 + the pre-1.32.0 ``_PER_SPELL_CC_DURATIONS`` forward-
# marker pattern.
#
# +29 tests NEW ``agents/daemon_slayer/tests/test_cc_conditional_wave7_tags.py``
# across 7 classes: WaveSevenTagConstantsTests (6) /
# WaveSevenDefaultProbabilityTests (6) / WaveSevenPublicTaxonomyTests
# (3) / RegistryUnchangedTests (4) / ConditionalCcEntryAcceptsNewTagsTests
# (3) / WaveSevenOverrideLoaderCompatibilityTests (3) /
# EngineVersionCurrentTests (1) + AsciiHygieneTests (2). Consumer math
# BYTE-IDENTICAL to 1.43.0 for all 5 consumer surfaces (cc_pressure +
# compute_ehp + compute_hybrid + coach prompt + dashboard UI) since
# no registry entry consumes either new tag at ship time.
# ``test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES`` gained
# ``test_cc_conditional_wave7_tags.py``.
#
# Carry-forwards from item 147 unchanged: (a) loading_view.css orphan
# @import + build_order.css inverse orphan still operator-gated;
# (c) cc_conditional registry future wave 8+ expansion operator-gated;
# (d) DD Defy heal-on-takedown still deferred; (e) live ARAM/SR smoke
# still pending; (f) RC-PostmortemAnalyze first scheduled run
# 2026-05-24 04:15; (g)/(h) calibration midpoints operator-gated;
# (i) obj_participation widening operator-gated; (j) UI/UX live-game
# audit ritual; (k) _PER_SPELL_CC_DURATIONS unconditional registry
# 108/89 unchanged this wave (wave 10+ likely exhausted for net-new
# at 16.10.1).
#
# 1.43.0 (cc_conditional wave 6 + _PER_SPELL_CC_DURATIONS wave 9 +
# BACKLOG stale-sweep wave 11 + cost/latency CLEAN, 2026-05-22):
#
# Three commit-bearing parallel-slice additions + 1 read-only CLEAN
# sweep composing on item 146 carries-forward (b) cc_conditional
# wave 6 expansion + (j) _PER_SPELL_CC_DURATIONS wave 9 (multi-wave
# coexistence only - saturated for net-new champs). Item 147. 14th
# consecutive orchestrator-merge run (items 134-147).
#
# Slice A - cc_conditional wave 6 (35/32 -> 36/32; +1 entry / +0
# net-new champs - multi-wave coexistence on Brand) via setdefault
# builder pattern from items 140-146. NEW: Brand Q Sear (target_
# debuffed 0.5 stun 1.25s - stuns target carrying Blaze passive
# stack; coexists with Brand R wave 1 nth_hit stun on different
# spell slot - third multi-wave coexistence within cc_conditional
# after Aatrox Q+W, Briar Q+E, TahmKench R+Q; brings within-cc_
# conditional multi-wave coexistence count to 4 champs). Uses only
# the 10 existing condition tags. REGISTRY_TOTAL_CHAMPIONS=32
# unchanged / REGISTRY_TOTAL_ENTRIES=35 -> 36. REJECTED wave-6
# candidates documented: Lissandra E (no CC), Aurora R/E/Q/W
# (uncertain/no CC), Volibear R (turret-only), Renata R (no CC),
# Aphelios Q/R (no CC), Vex E (already shipped), Sett W (needs
# new tag), Vayne wall (schema lift), Trundle E (no tag fit),
# Renekton W / Camille E (asymmetry). +44 tests NEW
# tests/test_cc_conditional_wave6.py. 5 prior-wave test files
# relaxed Brand-pin assertions to assertGreaterEqual + entry-level
# pins because Brand now has Q+R in registry (pattern matches item
# 145 Slice B Aatrox wave 3 relax). EngineVersionCurrentTests uses
# assertGreaterEqual((1, 42, 0)) for forward-compat per item 146
# lesson. tests/test_cc_conditional_forward_marker.py _ALLOWED_
# TEST_FILES gained test_cc_conditional_wave6.py.
#
# Slice B - _PER_SPELL_CC_DURATIONS wave 9 (106/89 -> 108/89; +2
# entries / +0 net-new champs both multi-wave coexistence) confirms
# item 146 carry (j) saturation prediction. Audit walked all 226
# unregistered spells of all 89 registered champions; only 2 of 6
# candidates surfaced were genuine unconditional first-order CC.
# NEW: Chogath W Feral Scream silence 1.6/1.7/1.8/1.9/2.0s
# (coexists with Chogath Q wave 2 knockup); Malzahar Q Call of
# the Void silence 1.0/1.25/1.5/1.75/2.0s (coexists with Malzahar
# R wave 1 suppression). Silence joins first-order CC scope per
# same precedent as wave 6 stasis (Bard R) - hard-disable types
# fit cleanly alongside stun/root/suspension/suppression. Both
# values verified vs data/daemon_slayer/16.10.1/champion_
# abilities.json Meraki silence-duration blocks. Multi-wave
# coexistence count now proven at 9 unconditional champions: Lulu
# W+R (waves 1+6), Sejuani R+Q (waves 1+6), Thresh Q+E (waves 1+
# 6), Zac E+R (waves 2+7), Lissandra R+W (waves 1+8), Maokai R+W
# (waves 1+8), Rakan W+R (waves 1+8), Chogath Q+W (waves 2+9
# NEW), Malzahar R+Q (waves 1+9 NEW). Selection rules unchanged
# from waves 1-8: first-order CC only; no slows; no conditional
# CC; canonical DDragon ids. REJECTED wave-9 candidates: Bard Q
# (cc_conditional wave 1), Morgana R (channel-completion conditional),
# Seraphine E (target-state conditional), Volibear R (turret-only),
# Janna R (undocumented duration), Lulu E (no CC). Consumer math
# BYTE-IDENTICAL to 1.42.0 for default include_conditional=False
# callers. +37 tests NEW tests/test_per_spell_cc_registry_wave9.py
# across 7 classes. tests/test_per_spell_cc_registry_seed.py count
# pin 89/106 -> 89/108 (assertGreaterEqual floor). tests/test_per
# _spell_cc_registry_wave8.py 2 count pins assertEqual ->
# assertGreaterEqual relaxation.
#
# Slice C - BACKLOG.md L13 cc_conditional ecosystem subsection
# stale-sweep wave 11 per [[feedback_backlog_path_stale_check]]:
# stopping-at-item-145-state line ("items 141-145 / 4 wave
# expansions / 33 entries + JSON override loader") flipped to
# "items 141-146 / 5 wave expansions / 35 entries". ROADMAP sweep
# CLEAN (Fleet status DS row already current at ENGINE 1.42.0 per
# item 146 Slice D verified). Sweep cycle decay: wave 1=2 / 2=3 /
# 3=3 / 4=1 / 5=1 / 6=1 / 7=2 / 8=1 / 9=1 / 10=1 / **11=1**.
# Methodology stable across 11 sweep rounds. Note: BACKLOG L13
# now needs another touch by orchestrator commit to reflect the
# 36/108 state THIS RUN ships (Slice C ran on pre-A baseline).
#
# Slice D - cost/latency CLEAN no-commit (14th consecutive CLEAN
# sweep since item 134). All 7 levers surveyed: prompt-cache (19
# files carry cache_control marker across 8 active coach modules;
# 22 messages.create caller files), route TTL (11+6=17 cached
# routes; uncached are POST/action/file-read), polling cadences
# (1.5s bridge_pending / 2s state / 500ms applyStaleness UI-local /
# 1000ms map cooldown UI-local), log spam (8-entry suppression set;
# top non-suppressed /api/bridge at 0.197/sec well below 1/sec
# threshold), model tier (all real messages.create() use claude-
# haiku-4-5-20251001; 3 r._model="claude-sonnet-4-6" annotations
# are POST-call telemetry stamps per item 146 don't-redo), scheduled
# tasks (14 unique RC-* tasks matches item 146 catalog), bundle
# size (27 panel files vs 29 @import lines in dashboard.css = 28
# panel @imports including item 146 orphan loading_view.css NOT
# fixed this run + 1 inverse orphan NEW: build_order.css EXISTS
# in panels dir but is NOT @imported in dashboard.css). Verdict
# CLEAN on 7 levers + 2 MINOR PROPOSALS (operator-gated, deferred):
# 1. loading_view.css orphan @import at web/css/dashboard.css:27
# (carries from item 146); 2. build_order.css orphan FILE (inverse:
# either dead-code awaiting deletion OR missing @import; depends
# on whether build_order panel is in production - NEW this run).
#
# Stale ENGINE pin syncs across 30+ DS test files (1.42.0 -> 1.43.0)
# via orchestrator bulk-rewrite. Same s243/s246 facade-split
# precedent; value-pinned regression suite is the definitive
# behavior-equivalence proof.
#
# Orchestrator-merge pattern now 14 consecutive runs (items 134-147).
# Durable template for parallel headless-upgrade-style drains.
#
# 1.42.0 (cc_conditional wave 5 + _PER_SPELL_CC_DURATIONS wave 8 +
# BACKLOG stale-sweep wave 10 + cost/latency CLEAN, 2026-05-22):
#
# Three commit-bearing parallel-slice additions + 1 read-only CLEAN
# sweep composing on item 145 carries-forward (a) cc_conditional
# wave 5+ expansion + (i) _PER_SPELL_CC_DURATIONS wave 8. Item 146.
#
# Slice A - cc_conditional wave 5 (33/32 -> 35/32; +2 entries / +0
# net-new champs - both are multi-wave coexistence on existing keys)
# via setdefault builder pattern from items 140-145. NEW: Briar E
# Chilling Scream (channel_completion 0.5 fear 1.0s - full-charge
# cone fear; tap-cast damage only; coexists with Briar Q wave 4
# terrain stun via setdefault on different spell slot - SECOND multi-
# wave coexistence in cc_conditional after Aatrox Q+W); TahmKench Q
# Tongue Lash (nth_hit 0.7 stun 1.5s - 3rd-stack stun via passive;
# coexists with TahmKench R wave 1 devour suppression via setdefault).
# Uses only the 10 existing condition tags. REGISTRY_TOTAL_CHAMPIONS=
# 32 unchanged / REGISTRY_TOTAL_ENTRIES=33 -> 35. REJECTED wave-5
# candidates documented: Vayne wall-stun (schema lift needed), Mel E
# (needs Meraki reverify), Annie passive Pyromania (encoding
# ambiguous), Belveth W (slow only), Cho'Gath W (unconditional
# silence belongs in unconditional registry), Trundle E (no clean
# tag fit). Multi-wave coexistence count now 4: Aatrox Q3+W (waves
# 3+4), Briar Q+E (waves 4+5), TahmKench R+Q (waves 1+5), Pantheon
# W+Q (waves 1+4 already shipped). +52 tests NEW
# tests/test_cc_conditional_wave5.py across 9 classes.
# tests/test_cc_conditional_wave4.py 3 Briar aggregator assertions
# relaxed to entry-level pins because Briar now has Q+E in registry.
# tests/test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES set
# gained test_cc_conditional_wave5.py.
#
# Slice B - _PER_SPELL_CC_DURATIONS wave 8 (103/89 -> 106/89; +3
# entries / +0 net-new champs via multi-wave coexistence) extends
# the unconditional first-order CC registry. NEW: Lissandra W Ring
# of Frost root 1.25/1.35/1.45/1.55/1.65 across 5 ranks (coexists
# with wave 1 Lissandra R stun); Maokai W Twisted Advance root
# 1.0/1.1/1.2/1.3/1.4 (coexists with wave 1 Maokai R root); Rakan R
# The Quickness charm 1.0/1.25/1.5 all 3 ranks (coexists with wave
# 1 Rakan W knockup). All 3 values verified vs
# data/daemon_slayer/16.10.1/champion_abilities.json Meraki duration
# blocks. Multi-wave coexistence now proven at 7 champions: Lulu
# W+R (waves 1+6), Sejuani R+Q (waves 1+6), Thresh Q+E (waves 1+6),
# Zac E+R (waves 2+7), Lissandra R+W (waves 1+8 NEW), Maokai R+W
# (waves 1+8 NEW), Rakan W+R (waves 1+8 NEW). Selection rules
# unchanged from waves 1-7: first-order CC only; no slows; no
# conditional CC; canonical DDragon ids. REJECTED wave-8 candidates
# documented: Bard Q / Karma W / TwistedFate W / Zilean Q / Aatrox W
# / Skarner Q (all in cc_conditional), Evelynn W / Morgana R /
# Seraphine E (conditional axes), Volibear R (turret-only), Tristana
# W (slow), Senna W (already shipped wave 4 per item 138). Consumer
# math BYTE-IDENTICAL to 1.41.0 for default include_conditional=False
# callers. +38 tests NEW tests/test_per_spell_cc_registry_wave8.py
# across 7 classes. tests/test_per_spell_cc_registry_seed.py count
# pin 89/103 -> 89/106. tests/test_per_spell_cc_registry_wave7.py
# count pin assertEqual -> assertGreaterEqual relaxation.
#
# Slice C - BACKLOG.md L13 cc_conditional ecosystem subsection
# stale-sweep wave 10 per [[feedback_backlog_path_stale_check]]:
# stopping-at-item-144-state line ("items 141-144 / 3 wave
# expansions / 28 entries") flipped to "items 141-145 / 4 wave
# expansions / 33 entries + JSON override loader" annotation. ROADMAP
# sweep CLEAN (Fleet status DS row already current at ENGINE 1.41.0
# per item 145 Slice D verified). Sweep cycle decay: wave 1=2 / 2=3
# / 3=3 / 4=1 / 5=1 / 6=1 / 7=2 / 8=1 / 9=1 / **10=1**. Methodology
# stable across 10 sweep rounds.
#
# Slice D - cost/latency CLEAN no-commit (13th consecutive CLEAN
# sweep since item 134). All 7 levers surveyed: prompt-cache (8
# callers explicit-block w/ cache_control + replay_coach + experi-
# mental_builder verified), route TTL (17 routes cached), polling
# cadences (1.5s bridge_pending / 2s state matches item 145 baseline),
# log spam (/api/bridge at 0.26/sec well below 1/sec threshold,
# consistent with item 145's 0.021/sec window - both below threshold),
# model tier (21/21 messages.create() Haiku per reference_model_
# config.md; sonnet/opus annotations are POST-call telemetry stamps
# NOT API tier), scheduled tasks (7 install scripts: DDragon /
# Postmortem / Rewind / LegionBridge / Phase3 x2 / run_postmortem;
# cadences sane), bundle size (28 panel @imports vs 27 panel files -
# loading_view.css orphan @import flagged; operator-gated 1-line
# CSS fix deferred). Verdict CLEAN on 6 levers + 1 MINOR PROPOSAL
# (loading_view.css orphan @import in web/css/dashboard.css:27 -
# safe to ship but operator-gated; carries forward).
#
# Stale ENGINE pin syncs across 30 DS test files (1.41.0 -> 1.42.0)
# via orchestrator bulk-rewrite. Same s243/s246 facade-split
# precedent; value-pinned regression suite is the definitive
# behavior-equivalence proof.
#
# Orchestrator-merge pattern now 13 consecutive runs (items 134-146).
# Durable template for parallel headless-upgrade-style drains.
#
# 1.41.0 (cc_conditional wave 4 expansion + JSON override loader for
# operator personal calibration, 2026-05-22):
#
# Three parallel-slice additions composing on item 144 carries-forward
# (e) operator-tunable calibration midpoints + per-entry probability
# values AND (j) future cc_conditional wave 4+ expansion. Item 145.
#
# Slice A - cc_conditional JSON override loader mirrors item 131 Slice B
# `b892519` core/post_game_rubric.py pattern. NEW _OVERRIDES_PATH = Path
# ("data") / "cc_conditional_calibration.json" (gitignored personal
# calibration; mirror of data/post_game_rubric_weights.json). NEW
# _load_overrides() fail-soft (missing file -> {}, malformed JSON -> {},
# non-dict shape -> {}). NEW _apply_default_probability_overrides(
# defaults, overrides) -> dict (unknown tags silently dropped + bool
# defense LOAD-BEARING before int/float per item 131 + out-of-range
# [0.0, 1.0] DROPPED not clamped). NEW _apply_per_entry_overrides(
# overrides) -> dict[(champion, spell), float] (malformed colon-keys
# dropped + same bool defense + out-of-range drop). Module-load step:
# _DEFAULT_CONDITION_PROBABILITY = _apply_default_probability_overrides(
# _DEFAULT_CONDITION_PROBABILITY, _load_overrides()) +
# _PER_ENTRY_PROBABILITY_OVERRIDES = _apply_per_entry_overrides(
# _load_overrides()). _build_per_spell_cc_conditional() reads
# _PER_ENTRY_PROBABILITY_OVERRIDES.get((champion, spell), default) when
# constructing each ConditionalCcEntry via inline `_p()` helper. Schema:
# {"default_condition_probability": {<tag>: <float>},
#  "per_entry_probability": {<champion>:<spell>: <float>}}.
# Both top-level keys optional. +46 tests NEW
# tests/test_cc_conditional_overrides.py across 5 classes
# (LoadOverridesTests 10 + ApplyDefaultProbabilityOverridesTests 10 +
# ApplyPerEntryOverridesTests 10 + IntegrationTests 5 +
# NoOverrideFileDefaultPreservationTests 3 + AsciiHygieneTests 1).
# tests/test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES set
# gained test_cc_conditional_overrides.py.
#
# Slice B - cc_conditional wave 4 (28/28 -> 32/33; +4 net-new champs
# Nunu / Yuumi / Pantheon / Briar + 1 multi-wave coexistence Aatrox W
# on top of Aatrox Q wave 3) via setdefault builder pattern from items
# 140-144. NEW entries: Nunu R Absolute Zero (channel_completion 0.5
# knockup 0.5s - full 3s channel completion); Yuumi Q Prowling
# Projectile (channel_completion 0.4 root 1.75s - max-travel-distance
# root); Pantheon Q Comet Spear empowered (channel_completion 0.5 stun
# 1.0s - long-cast empowered version; coexists with Pantheon W wave 1
# unconditional stun via setdefault); Aatrox W Infernal Chains
# (debuffed_target 0.5 root 1.75s - chain debuff persistence pull-back;
# FIRST multi-wave coexistence with Aatrox Q wave 3 nth_hit knockup on
# different spell slot); Briar Q Head Rush (terrain 0.3 stun 1.0s -
# terrain-collision stun; the Briar Q+R frenzy-state-gated variants
# from item 144 carry-forward still require new condition tag schema
# lift NOT in this wave). REJECTED wave-4 candidates documented:
# Senna W (unconditional), Aurora E / Aurora R (mechanic-uncertain),
# Heimerdinger R-Q (no additional CC beyond E base), Galio Q (slow
# only), Galio R (already unconditional), Briar W (no first-order CC),
# Briar Q/R frenzy variants (needs new tag schema lift), Naafiri R /
# Akali R / Jhin R / Pyke R / Sett R (no CC), Sett W (needs new tag),
# Brand W (passive not first-order), Lillia E (no CC). REGISTRY_TOTAL_
# CHAMPIONS=32 / REGISTRY_TOTAL_ENTRIES=33. +63 tests NEW
# tests/test_cc_conditional_wave4.py across 9 classes.
# tests/test_cc_conditional_wave3.py 3 Aatrox aggregator assertions
# relaxed to entry-level pins because Aatrox now has Q+W in registry.
# tests/test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES set
# gained test_cc_conditional_wave4.py.
#
# Slice C - BACKLOG.md L13 cc_conditional ecosystem entry stale-sweep
# wave 9 flipped: stale "18 entries / 18 champions" + "future consumer
# wires" claim replaced with comprehensive 5-consumer ecosystem
# annotation (cc_pressure DIRECT + compute_ehp INDIRECT + compute_hybrid
# INDIRECT + coach prompt cc_conditional_impact_line + dashboard UI
# routes_cc_conditional_pressure). Sweep cycle: wave 1=2 / 2=3 / 3=3 /
# 4=1 / 5=1 / 6=1 / 7=2 / 8=1 / 9=1. Methodology decay continues.
#
# Slice D - cost/latency CLEAN no-commit (12th consecutive CLEAN sweep
# since item 134). All 7 levers surveyed: prompt-cache (8 callers
# explicit-block w/ cache_control), route TTL (16 routes cached),
# polling cadences (1.5s bridge_pending / 2s state matches s144),
# log spam (/api/bridge at 0.021/sec below threshold), model tier
# (21/21 messages.create() Haiku per reference_model_config.md),
# scheduled tasks (14 RC-* sane), bundle size (27 panel CSS = 27
# @import lines perfect parity). Verdict CLEAN; lever lane exhausted
# absent product-fidelity tradeoffs.
#
# Stale ENGINE pin syncs in 33 DS test files (1.40.0 -> 1.41.0) via
# orchestrator bulk-rewrite. Same s243/s246 facade-split precedent;
# value-pinned regression suite is the definitive behavior-equivalence
# proof.
#
# Wave-4 entries flow through Slice A's _p() helper (per-entry override
# threading); orchestrator-merge resolved at this commit. The 5 raw-
# probability literals in Slice B's diff were threaded post-merge so
# per-entry overrides apply uniformly to ALL 33 registry entries.
#
# Orchestrator-merge pattern now 12 consecutive runs (items 134-145).
# Durable template for parallel headless-upgrade-style drains.
#
# 1.40.0 (cc_conditional FOURTH + FIFTH consumer wires (coach prompt +
# dashboard UI) + wave 3 registry expansion, 2026-05-22):
#
# Three parallel-slice additions composing on item 143 carries-forward (a).
# The cc_conditional ecosystem is now COMPLETE across 5 consumer surfaces
# (engine math: cc_pressure / compute_ehp / compute_hybrid + coach prompt
# + dashboard UI).
#
# Slice A - cc_conditional FOURTH consumer (FIRST coach prompt) via NEW
# core/cc_conditional_impact_context.py cc_conditional_impact_line().
# Sibling of core/cc_blended_ehp_context.py item 138 Slice A `738c005`.
# Reads compute_cc_pressure(name, mode, include_conditional=True) and
# isolates the .conditional_cc_seconds contribution; aggregates across
# all enemies into one summary line. Defaults
# _FIGHT_WINDOW_S = 6.0 + _CC_EFFECTIVENESS_FACTOR = 0.5 match ehp.py
# constants exactly. ImportError fallback stub mirrors
# enemy_cc_threat_context.py pattern. Wired into all 4 active mode coach
# prompts (aram / arena / brawl 3 NB+URF+OFA / coach_integration sr)
# APPEND-only per cache-prefix preservation. +53 tests in NEW
# tests/test_cc_conditional_impact_context.py. NO ENGINE math change.
#
# Slice B - cc_conditional FIFTH consumer (FIRST dashboard UI) via NEW
# dashboard/routes_cc_conditional_pressure.py + frontend chip. Sibling
# of dashboard/routes_cc_blended_ehp_threat.py item 140 Slice A
# `3b6cc4b`. GET /api/cc-conditional-pressure?ally=&enemy=&mode= returns
# ally vs enemy conditional_cc_seconds averages + ratio + tier (good /
# warn / bad) via symmetric construction (ally side feeds ENEMY roster
# as enemy_champions to compute_cc_pressure(include_conditional=True),
# vice versa). Tier bands ratio >= 1.05 = good (enemy carries more
# conditional CC = follow-up window); 0.95-1.05 = warn; <0.95 = bad.
# 5-min TTL mode-aware in-process cache. NEW web/js/panels/
# cc_conditional_pressure.js + cc_conditional_pressure.css chip
# mounted between #csv-sugg-cc-blended-ehp-threat and
# #csv-sugg-pickorder, tier-tinted via data-cc-cond-tier attr. +42
# tests across NEW test_routes_cc_conditional_pressure.py + NEW
# test_cc_conditional_pressure_panel_dom.py. NO ENGINE math change.
#
# Slice C - cc_conditional wave 3 registry expansion (23 -> 28 entries
# / 23 -> 28 champions). Uses the _build_per_spell_cc_conditional
# setdefault builder pattern. 5 new entries / 5 new champions:
#   - Aatrox Q3 knockup 0.5s nth_hit 0.7 (3rd-cast within combo)
#   - Riven Q3 knockup 0.75s nth_hit 0.7 (3rd Broken Wings stage)
#   - Yasuo Q3 knockup 1.0s nth_hit 0.7 (Steel Tempest 3rd stack)
#   - Yone Q3 knockup 0.75s nth_hit 0.7 (mirror of Yasuo Q3)
#   - Leblanc E root 1.5s channel_completion 0.5 (Ethereal Chains
#     full-tether)
# Uses only the 10 EXISTING condition tags (no new tags).
# REGISTRY_TOTAL_CHAMPIONS=28 / REGISTRY_TOTAL_ENTRIES=28. All wave 1+2
# entries preserved byte-identical via setdefault. +59 tests in NEW
# test_cc_conditional_wave3.py + 2 wave2 assertEqual -> assertGreaterEqual
# count-pin relaxations + 1 forward-marker test allowlist update.
#
# Slice D - cost/latency CLEAN sweep (11th consecutive CLEAN run since
# item 134). 7 levers surveyed (prompt-cache / route TTL / polling
# cadences / log spam / model tier / scheduled tasks / bundle size); all
# CLEAN; product-fidelity lever-lane exhausted.
#
# Consumer math BYTE-IDENTICAL to 1.39.0 for all default
# include_conditional=False callers. The 5 wave-3 entries surface
# via include_conditional=True opt-in through the SHIPPED cc_pressure
# kwarg. The cc_conditional ecosystem is now fully consumer-wired.
#
# 1.39.0 (cc_conditional SECOND + THIRD consumer wires + wave 2 registry
# expansion, 2026-05-22):
#
# Three parallel-slice additions composing on item 142 carries-forward (h).
#
# Slice A - cc_conditional SECOND consumer wire in ehp.py.
#   compute_ehp gains `include_conditional: bool = False` kwarg AFTER
#   `enemy_champions`. When True, propagates to internal
#   compute_cc_pressure(enemy, mode, include_conditional=True) calls.
#   Default False preserves byte-identical behavior with item 137 EHP
#   contract; cc_blended_ehp now reflects conditional contribution when
#   opted in. INDIRECT wire - ehp.py has no direct dependency on the
#   conditional CC registry; the kwarg flow is
#   ehp -> cc_pressure -> conditional registry.
#   The forward-marker scan in test_cc_conditional_forward_marker.py
#   keeps `_ALLOWED_SOURCE_FILES = {"cc_pressure.py"}` (ehp.py is an
#   indirect kwarg-only consumer; not on the allowlist). +16 tests in
#   NEW test_cc_conditional_consumer_ehp.py.
#
# Slice B - cc_conditional THIRD consumer wire in hybrid.py.
#   compute_hybrid gains `include_conditional: bool = False` kwarg AFTER
#   `enemy_champions`. Threads through ALL 3 internal compute_ehp call
#   sites via `**_ehp_kwargs` gating (passes the kwarg ONLY when True).
#   HybridResult.cc_blended_ehp reflects conditional contribution
#   automatically through the ehp -> cc_pressure chain. Default False
#   preserves byte-identical behavior with item 139 hybrid contract.
#   INDIRECT wire - hybrid.py has no direct dependency on the
#   conditional CC registry.
#   +18 tests in NEW test_cc_conditional_consumer_hybrid.py.
#
# Slice C - cc_conditional wave 2 registry expansion (18/18 -> 23/23;
# +5 entries / +5 new champs). Uses the _build_per_spell_cc_conditional
# setdefault builder pattern. New entries:
#   - Maokai Q Bramble Smash (terrain 0.3, stun 1.0s) - coexists with
#     Maokai R unconditional via setdefault
#   - Pyke E Phantom Undertow (channel_completion 0.5, stun 1.25s) -
#     coexists with Pyke Q wave 3 unconditional
#   - Swain E Nevermove (channel_completion 0.5, root
#     1.5/1.625/1.75/1.875/2.0s across 5 ranks)
#   - Skarner Q Shattered Earth + Upheaval (nth_hit 0.7, knockup 0.75s)
#     - coexists with Skarner R wave 3 unconditional
#   - Zilean Q Time Bomb (nth_hit 0.7, stun 2.0s)
# Uses only the 10 EXISTING condition tags (no new tags). All wave 1
# entries preserved byte-identical via setdefault. +55 tests in NEW
# test_cc_conditional_wave2.py.
#
# Slice D - BACKLOG stale-sweep wave 8 + cost/latency CLEAN (10th
# consecutive CLEAN run since item 134). One BACKLOG entry flipped to
# reflect cc_pressure SHIPPED as FIRST consumer at ENGINE 1.38.0 + the
# 18/18 wave 1 registry; surface natural NEXT wires (compute_ehp +
# compute_hybrid) which this run ships.
#
# Consumer math BYTE-IDENTICAL to 1.38.0 for all default
# include_conditional=False callers (the existing 4+ consumers of
# compute_ehp / compute_hybrid). When opted-in, cc_blended_ehp absorbs
# the conditional contribution through the unified effective_cc_duration
# seam (ARAM tenacity flows through automatically).
#
# 1.38.0 (cc_conditional FIRST consumer wire + wave 1 registry expansion,
# 2026-05-22):
# Two parallel-slice additions composing on item 141 carries-forward (h).
#
# Slice A - cc_conditional FIRST consumer wire in cc_pressure.py.
# Closes item 141 carry (h): the conditional CC schema lift shipped at
# 1.37.0 as a FORWARD-MARKER seam with no consumer wires; this slice
# wires the FIRST authorized consumer. ``compute_cc_pressure(champion,
# mode, *, include_conditional=False)`` gains an opt-in kwarg. When
# False (the default), behavior is BYTE-IDENTICAL to 1.37.0 for the 4
# existing consumers (compute_ehp / enemy_cc_threat_line /
# compute_hybrid / routes_cc_blended_ehp_threat). When True, the
# function reads ``get_conditional_entries(champion)`` + computes a
# probability-weighted sum via ``get_total_conditional_cc_seconds``
# (apply_probability=True default), applies ARAM tenacity via
# ``effective_cc_duration(conditional_total, tenacity_mult)`` so the
# math seam stays unified, and folds the post-tenacity conditional
# total into ``total_cc_seconds`` while exposing the SEPARATE
# contribution on the NEW ``conditional_cc_seconds`` field. The NEW
# ``conditional_entries: tuple[ConditionalCcEntry, ...] = ()`` field
# surfaces the registered conditional entries for transparency.
# ``test_cc_conditional_forward_marker.py`` was updated in the same
# slice: ``_ALLOWED_SOURCE_FILES = {"cc_pressure.py"}`` allow-lists
# the FIRST consumer; every OTHER file under ``agents/daemon_slayer/``
# still triggers the no-consumer-wire guard.
#
# Slice B - cc_conditional wave 1 expansion (10 -> 18 entries).
# Extends the seed shipped at 1.37.0 with 8 additional canonical
# conditional CC entries across 8 new champions, all sourced from the
# wave 4/5/6/7 REJECT lists: Bard Q Cosmic Binding (terrain 0.3 -
# wall-bounce 1.5/1.75/2.0/2.25/2.5s); Karma W Focused Resolve
# (channel 0.4 - full-tether 1.5/1.625/1.75/1.875/2.0s); Taliyah W
# Seismic Shove (channel 0.5 - recast 0.75s knockup); Kennen E
# Lightning Rush (nth_hit 0.6 - Mark of the Storm 3-stack stun 1.25s);
# KSante Q Ntofo Strikes (nth_hit 0.7 - 3rd-cast root 0.75s; coexists
# with KSante R wave 5); Ornn Q Volcanic Rupture (debuffed 0.5 -
# post-Brittle knockup 1.5s; coexists with Ornn R wave 7); Xayah E
# Bladecaller (nth_hit 0.6 - 3+ feathers root 1.25s); Fiora W Riposte
# (debuffed 0.4 - parry-stun 1.5s). REGISTRY_TOTAL_CHAMPIONS goes
# 10 -> 18; REGISTRY_TOTAL_ENTRIES goes 10 -> 18. No new condition
# tags (uses only the 10 existing tags). 8 candidates REJECTED with
# reason: Aurora R (uncertain), Briar Q+R (frenzy-state-gated needs
# new tag), Sylas E2 (range-conditional needs new tag), Renata R +
# Aphelios Q (no first-order CC), Lissandra E (mis-described - direct
# skillshot), Volibear R (turret-only), Swain E (deferred).
#
# Consumer math: byte-identical to 1.37.0 for ALL existing callers via
# the default ``include_conditional=False`` contract; Slice B is
# data-lane only.
#
# 1.37.0 (per-spell CC registry wave 7 + conditional CC axis schema lift,
# 2026-05-22):
# Two parallel-slice additions composing on item 140 carries-forward.
#
# Slice A - _PER_SPELL_CC_DURATIONS wave 7 (data lane via setdefault
# builder). Extends the 95-entry / 82-champion registry shipped 1.36.0
# with 8 additional first-order CC entries across 7 new champions of
# patch 16.10.1. New champions seeded: Irelia E Flawless Duet stun
# 0.75/0.85/0.95/1.05/1.15 across 5 ranks; Kalista R Fate's Call
# knockup 1.0s all 3 ranks; Ornn R Call of the Forge God knockup 0.5s
# all 3 ranks; Shyvana R Dragon's Descent knockback 1.0s all 3 ranks;
# Smolder R Mountain Breaker knockup 1.25s all 3 ranks; Vayne E Condemn
# knockback 0.5s all 5 ranks; Zac R Let's Bounce knockup 1.0s all 3
# ranks; multi-wave augmentation Zac R (Zac E was wave 2; now coexists
# via setdefault). Volibear E Sky Splitter airborne 0.25s all 5 ranks
# adds the airborne CC kind. Selection rules unchanged from waves
# 1-6: first-order CC only; no slows; no conditional CC; canonical
# DDragon ids. 15+ REJECT candidates documented (Darius E pull+slow /
# Yorick R Mist Walkers / AurelionSol Q / Aurora W/E/R / Ambessa all
# spells / Pyke E damage / Fiora W parry / Vex E mark / Ornn Q Brittle /
# Renata R berserk-axis / Volibear Q terrain / Sett W/E / TahmKench R
# ally swallow). Registry total: 103 entries across 89 champions
# (+8 entries / +7 new champs / +1 multi-wave coexistence).
#
# Slice B - conditional CC axis schema lift via NEW
# agents/daemon_slayer/cc_conditional.py module. Forward-marker pattern
# mirroring s112 STAT_GRANT_CALC_KEYS empty seam shipped at 1.22.0 and
# _PER_SPELL_CC_DURATIONS pre-130 empty seam. Ships the schema +
# machinery + seed of 10 canonical conditional CC entries from the
# wave 4/5/6 REJECT lists (Brand R 3rd-stack stun / TwistedFate W
# Gold Card / JarvanIV E terrain knockup / TahmKench R Devour
# suppression / Volibear Q terrain knockback / Warwick R channel-
# completion suppression / Viktor W 3rd-charge stun / Mordekaiser R
# banishment / Sett E dual-enemy stun / Vex E debuffed fear). NEW
# ConditionalCcEntry frozen dataclass + condition tags enum
# (COND_NTH_HIT / COND_GOLD_CARD / COND_TERRAIN / COND_CHANNEL_COMPLETION
# / COND_DREAM_STACK / COND_DEVOUR_TARGET / COND_TARGET_HP_BELOW /
# COND_TARGET_DEBUFFED / COND_DUAL_ENEMY / COND_MODE_GATED) + NEW
# _DEFAULT_CONDITION_PROBABILITY map of 10 operator-tunable midpoints
# (e.g. nth_hit=0.7 / gold_card=0.4 / terrain=0.3 / channel=0.5 /
# devour=0.4 / mode_gated=1.0) + NEW _build_per_spell_cc_conditional()
# setdefault builder + NEW get_conditional_entries(champion) lookup +
# NEW get_total_conditional_cc_seconds(champion, apply_probability,
# rank_index) probability-weighted aggregator. REGISTRY_TOTAL_CHAMPIONS
# = 10 / REGISTRY_TOTAL_ENTRIES = 10. Forward-marker boundary pinned
# by NoConsumerWireTests (5 tests) verifying NO file in
# agents/daemon_slayer/ outside the new test files imports from
# cc_conditional. cc_pressure.py / ehp.py / ability_dps.py / engine.py
# all explicitly tested. DocstringStatesForwardMarkerTests (3 tests)
# verify module docstring declares FORWARD-MARKER + no-consumer-wires
# + references prior STAT_GRANT_CALC_KEYS empty seam. Future consumers
# populate via probability-weighted aggregation in compute_cc_pressure
# or a sibling fight-sim. Production behavior of every existing
# consumer is byte-identical to 1.36.0 (the new module is dead-code
# at the consumer layer).
#
# +59 tests across NEW test_cc_conditional.py (47 across 7 classes)
# + NEW test_cc_conditional_forward_marker.py (12 across 2 classes).
# +37 tests in NEW test_per_spell_cc_registry_wave7.py. Total DS
# suite delta from 1.36.0: +96.
#
# 1.36.0 (per-spell CC registry schema lift + wave 6, 2026-05-22):
# Closes item 139 carry (j): the future registry-merge pass owed to
# enable multi-wave augmentation of single-champion spell maps. Lifts
# the _PER_SPELL_CC_DURATIONS registry from a single dict literal (which
# clobbered prior-wave entries when a later wave added a new spell to
# the same champion) to a module-level builder function
# _build_per_spell_cc_durations() that uses
# ``registry.setdefault(champ, {})[spell] = tuple`` so multiple waves
# can contribute spells to the same champion without clobbering.
# Production behavior of all 90 pre-1.36.0 entries is byte-identical
# (value pins preserved); the schema lift only changes the construction
# shape.
#
# Wave 6 ships 5 NEW entries unblocked by the schema lift:
# * Lulu R Wild Growth knock-up 1.0s all 3 ranks (multi-wave: Lulu W
#   polymorph was seeded wave 1; now coexists).
# * Sejuani Q Arctic Assault stun 0.75/0.875/1.0/1.125/1.25 across 5
#   ranks (multi-wave: Sejuani R was seeded wave 1; now coexists).
# * Thresh E Flay knockback 0.4s all 5 ranks (multi-wave: Thresh Q
#   was seeded wave 1; now coexists).
# * Bard R Tempered Fate stasis 2.5s all 3 ranks (NEW champion;
#   stasis added to first-order CC scope).
# * Lillia R Lilting Lullaby sleep 2.0s all 3 ranks (NEW champion).
#
# Registry total: 95 entries across 82 champions. Consumer math
# byte-identical to 1.35.0 for all existing entries.
#
# 1.35.0 (compute_hybrid enemy_champions kwarg + cc_blended_ehp scoring
# + CC registry wave 5, 2026-05-22):
# Two feature additions shipped in the same parallel orchestrator drain
# composing on item 138 carries-forward.
#
# Slice A - compute_hybrid enemy_champions kwarg + cc_blended_ehp
# scoring. FIRST DS-engine SCORER consumer of cc_blended_ehp (the
# field shipped item 137 ENGINE 1.33.0). compute_hybrid() in
# agents/daemon_slayer/hybrid.py:178 gains a new
# ``enemy_champions: Iterable[str] = ()`` kwarg threaded through to
# all 3 internal compute_ehp(...) call sites (lines 238 / 547 / 584).
# When enemy_champions is non-empty, the hybrid_score uses
# ``ehp_result.cc_blended_ehp`` (POST-CC-erosion EHP) instead of the
# pre-CC ``blended_ehp`` for the scoring component. Default empty
# tuple preserves byte-identical hybrid_score with all pre-1.35.0
# callers via the item 137 compute_ehp identity contract
# (cc_blended_ehp == blended_ehp when enemy_champions=()).
# HybridResult dataclass gains 2 new fields for surface visibility:
# cc_blended_ehp: float = 0.0 + enemy_champions: tuple[str, ...] = ().
# The ehp field on HybridResult keeps blended_ehp semantics (PRE-CC)
# for transparency; cc_blended_ehp is the NEW surface alongside.
# +22 tests in test_hybrid_enemy_champions.py. Math verified live:
# Aatrox L11 SR + (Annie/Morgana/Malzahar) summed CC clamps fraction
# 1.0 -> cc_blended_ehp = blended * 0.5 -> hybrid_score delta = beta
# * (blended_ehp - cc_blended_ehp) matches expected to 4 decimal places.
#
# Slice B - _PER_SPELL_CC_DURATIONS wave 5 (data lane). Extends the
# 82-entry / 73-champion registry shipped 1.34.0 with 8 additional
# first-order CC entries across 7 new champions of patch 16.10.1
# (Hecarim brings 2 spell entries). Total registry now 90 entries
# across 80 champions. New champs: Hecarim (E+R), KSante (R),
# Mordekaiser (E), Urgot (E), Viego (W), Yone (R), Ziggs (W).
# Mid-implementation collision discovery REJECTED 9 candidates that
# clobbered prior-wave dict keys (Lulu R, Quinn E, Shen E, Jax E,
# Jinx E, Janna Q, Sejuani Q, Rell R, Thresh E - all prior-wave
# champion-spell dict keys). The dict-literal cannot represent
# multi-wave augmentation of a single champion spell map; a future
# registry-merge pass is owed to enable these without clobbering.
# Conditional CC candidates REJECTED with reason in commit body
# (Aurora R / Mordekaiser R / Briar R / Bard Q / Sett W / Taliyah W /
# Volibear Q / JarvanIV EQ / Trundle R / Kennen E / KSante Q / Sett E /
# Vayne E / Sylas E2 / Xayah E / Aphelios Q / Aurora E / Briar Q /
# Renata R - all operator-gated schema lift). Consumer math is
# BYTE-IDENTICAL to 1.34.0 (data lane only).
#
# 1.34.0 (per-spell CC duration registry wave 4, 2026-05-22):
# Closes the item 137 carry / data-side broadening: extends the
# 67-entry / 58-champion registry shipped 1.33.0 with 15 additional
# first-order CC entries across 15 new champions of patch 16.10.1.
# Total registry now 82 entries across 73 champions.
# New champions seeded (15): Draven (E knock-back), Ekko (W zone-expiry
# stun), Janna (Q knock-up), Jax (E counter-strike stun), Jinx (E
# Flame Chompers root), Mel (E Solar Snare orb root), Nocturne (E
# Unspeakable Horror fear), Quinn (E Vault knock-back), Rammus (E
# Frenzying Taunt), Senna (W Last Embrace root), Seraphine (R Encore
# stun), Shaco (W Jack in the Box fear), Shen (E Shadow Dash taunt),
# Soraka (E Equinox root), Zyra (E Grasping Roots root). Selection
# rules unchanged from waves 1+2+3: first-order CC only; no slows;
# no conditional CC (Bard Q wall-bounce / Evelynn W detonation-on-
# Eve-attack / Hwei E compound-cast / Karma W channel-completion /
# Seraphine E slowed-target / Swain E return-wave / Syndra E via
# Dark Sphere / TwistedFate W Gold Card / Zilean Q double-bomb -
# all REJECTED with reason recorded); canonical DDragon ids.
# Consumer math is BYTE-IDENTICAL to 1.33.0 for every (champion, item,
# mode) tuple - this is a pure data lane lift; the cc_pressure
# aggregator (item 136 Slice A) + AbilitySpellDps.cc_duration_s /
# cc_duration_post_tenacity fields read the 15 new entries transparently.
# The EHP-vs-CC blended scorer (item 137 Slice A) also reads through
# cc_pressure with no math change.
#
# 1.33.0 (EHP-vs-CC blended scorer + CC registry wave 3, 2026-05-22):
# Closes item 136 carry (a). Two engine consumers shipped in the same
# parallel orchestrator drain.
#
# Slice A - EHP-vs-CC blended scorer (compute_ehp). Second engine math
# consumer of compute_cc_pressure (after the coach-prompt-side consumer
# at 1.32.0 - core/enemy_cc_threat_context.py). compute_ehp() gains an
# optional enemy_champions kwarg defaulting to (). When non-empty, the
# scorer computes enemy CC pressure from the registry via
# compute_cc_pressure(enemy, mode) per entry, sums total_cc_seconds
# across enemies, derives cc_pressure_fraction = min(sum /
# _FIGHT_WINDOW_S, 1.0), and computes cc_blended_ehp = blended_ehp *
# (1.0 - cc_pressure_fraction * _CC_EFFECTIVENESS_FACTOR) where
# _CC_EFFECTIVENESS_FACTOR = 0.5 (conservative midpoint - 1s of summed
# enemy CC pressure erodes 0.5s of operator fight-time effectiveness;
# CC is not perfectly chained, QSS/Cleanse/Flash mitigate, etc.).
# EhpResult gains 3 new fields (enemy_cc_pressure_s, cc_pressure_fraction,
# cc_blended_ehp); to_dict + format_table + notes carry them. Default
# call (enemy_champions=()) leaves cc_blended_ehp == blended_ehp -
# back-compat for every existing call site across the engine + the
# dashboard. The blended_ehp / physical_ehp / magical_ehp / true_ehp
# fields are UNCHANGED when enemy_champions is provided - the discount
# lives ONLY in the new cc_blended_ehp field. ARAM tenacity flows
# through transparently via the existing compute_cc_pressure wiring.
#
# Slice B - _PER_SPELL_CC_DURATIONS wave 3 (data registry expansion).
# Extends the 53-entry / 44-champion seed (wave 1 + wave 2) with 14
# additional first-order CC entries across 14 new champions at patch
# 16.10.1. Total registry now 67 entries across 58 champions.
# New champions (14): AurelionSol R, Caitlyn W, Camille E, Diana R,
# Elise E, Heimerdinger E, Ivern Q, Malphite R, Pyke Q, Rell Q, Ryze W,
# Sion Q, Tristana R, XinZhao W. Selection rules unchanged from waves
# 1+2: first-order CC only; no slows; no conditional CC; canonical
# DDragon ids. Consumer math BYTE-IDENTICAL to 1.32.0 - data lane only;
# cc_pressure aggregator + AbilitySpellDps cc_duration_s fields read
# the registry transparently for the new entries.
#
# 1.32.0 (cc_pressure aggregator, 2026-05-22):
# First consumer of the _PER_SPELL_CC_DURATIONS registry seeded at
# ENGINE 1.30.0 + extended at 1.31.0. NEW module agents/daemon_slayer/
# cc_pressure.py exposes compute_cc_pressure(champion, mode) ->
# CcPressureResult aggregating max-rank CC durations across registered
# spells with per-mode aramTenacity applied through
# ehp.effective_cc_duration. Empty result for unknown champions; SR
# mode identity. The seam any future EHP-vs-CC blended scorer or
# coach-prompt renderer reads from. Engine math UNCHANGED from 1.31.0
# for every (champion, item, mode) tuple - this is a NEW aggregator
# module, not a math change to compute_dps / compute_ability_dps /
# compute_ehp / compute_hps. Existing per-spell cc_duration_s +
# cc_duration_post_tenacity fields on AbilitySpellDps unchanged.
#
# 1.31.0 (per-spell CC duration registry wave 2, 2026-05-21):
# Closes item 134 carry-forward (h) data-side: extends the
# ``_PER_SPELL_CC_DURATIONS`` registry shipped 1.30.0 with 23 additional
# first-order CC entries across 20 additional champions of patch 16.10.
# Total registry now 53 entries across 44 champions (was 30 / 24 at
# 1.30.0). Consumer math is BYTE-IDENTICAL to 1.30.0; this is a pure
# data lane lift - the values flow through AbilitySpellDps.cc_duration_s
# + cc_duration_post_tenacity for API inspection only.
# New champions seeded (20): Alistar (Q + W), Amumu (Q + R), Anivia (Q),
# Braum (R), Chogath (Q), Fiddlesticks (Q), Gnar (R), Gragas (E),
# Jhin (W), Lux (Q), Nami (Q), Neeko (E + R), Orianna (R), Poppy (E),
# Riven (W), Singed (E), Skarner (R), Varus (R), Xerath (E), Zac (E).
# Selection rules followed from 1.30.0: first-order CC only (stuns /
# roots / suspensions / knock-ups / knock-backs / charms / sleeps /
# fear / suppressions). No slows. No conditional CC (e.g. Bard Q
# wall-bounce, Tahm Kench Q 3rd-stack). Canonical DDragon ids
# (Chogath, Wukong=MonkeyKing pre-existing).
# The engine-side fight-sim consumer that reads the registry for math
# is STILL FUTURE work per the BACKLOG carry. This bump is a DATA seed
# only.
#
# 1.30.0 (per-spell CC duration registry seeded, 2026-05-21):
# Closes the item 130 carry-forward (b): the engine-side fight-sim
# consumer that reads ``_PER_SPELL_CC_DURATIONS`` for math is still
# FUTURE work, but this slice seeds the DATA so it is available on the
# wire (AbilitySpellDps.cc_duration_s + cc_duration_post_tenacity)
# for future composition + direct API inspection.
# Registry seeded with 30 starter entries across 24 champions (Q/W/E/R
# per-spell CC base durations from patch 16.10 tooltips). All entries
# are FIRST-ORDER CC (stuns / roots / suspensions / knock-ups / charms
# / suppressions / polymorphs / sleeps / taunts). Slows are NOT encoded
# (different math). Conditional CC (e.g. Brand R 3rd-stack, charged
# variants requiring fight-sim observer) is skipped where base semantic
# is unclear without a fight-sim.
# Champions seeded (24): Ahri, Annie, Ashe, Blitzcrank, Cassiopeia,
# Galio, Leona, Lissandra, Lulu, Malzahar, Maokai, MonkeyKing (Wukong),
# Morgana, Nautilus, Pantheon, Rakan, Renekton, Sejuani, Sona, Thresh,
# Veigar, Vi, Yasuo, Zoe.
# This bump is a DATA-LAYER seed, NOT a math change - the ``cooldown``,
# ``base_cooldown``, ``total_ability_haste``, ``raw_damage_per_cast``,
# ``post_mode_damage_per_cast``, ``post_mitigation_damage_per_cast``,
# ``dps``, and all other existing fields are byte-identical to 1.29.0
# output for every (champion, spell, mode) tuple. Only the 2 cc_*
# tuple fields now carry non-empty values for the 30 seeded entries.
# This is the 2nd consumer of ``effective_cc_duration`` helper shipped
# 1.25.0 (item 122). Engine-side math consumption (fight-sim) is still
# FUTURE work per the BACKLOG carry.
#
# 1.29.0 (per-spell CC duration extractor seam, 2026-05-21):
# Closes the item 129 carry-forward (a): 2nd consumer of the
# ``effective_cc_duration`` helper shipped 1.25.0 (item 122). The helper
# itself lives in ``ehp.py`` (free function); this slice exposes the
# downstream-consumer surface at the per-spell AbilityDps layer so a
# future EHP-vs-CC blended scorer (or fight-sim) can read per-rank base
# CC durations + the matching post-tenacity values without re-resolving
# the champion.
# NEW ``AbilitySpellDps.cc_duration_s: tuple[float, ...]`` field
# (defaults ``()`` empty tuple) - per-rank base CC duration in seconds.
# NEW ``AbilitySpellDps.cc_duration_post_tenacity: tuple[float, ...]``
# field - same shape after element-wise
# ``effective_cc_duration(base, aram_tenacity_mult)``; identity in SR
# + non-ARAM modes; lengthened in ARAM for the 15 champs with
# aramTenacity > 1.0.
# NEW ``_PER_SPELL_CC_DURATIONS: dict[str, dict[str, tuple[float, ...]]]``
# module-level registry seam (in ``ability_dps.py``). EMPTY at 1.29.0
# by design (mirror of item 112's ``STAT_GRANT_CALC_KEYS`` empty-seam
# pattern): production behavior is byte-identical to pre-slice because
# the registry returns ``()`` for every (champion, spell) lookup;
# ``_apply_tenacity_to_cc_tuple(())`` short-circuits to ``()``. Future
# patches populate per-champion + per-spell entries when a downstream
# consumer (fight-sim / coach-prompt / EHP-vs-CC) needs the data.
# NEW free helpers ``_per_spell_cc_for(champion_id, spell_key)`` +
# ``_apply_tenacity_to_cc_tuple(base, tenacity_mult)`` (the latter
# wraps ``ehp.effective_cc_duration`` element-wise). Imported via
# ``from .ehp import effective_cc_duration`` at the top of
# ``ability_dps.py`` - no circular (``ehp.py`` does not import
# ``ability_dps``).
# This bump is a forward-marker engine seam, NOT a math change - the
# ``cooldown``, ``base_cooldown``, ``total_ability_haste``,
# ``raw_damage_per_cast``, ``post_mode_damage_per_cast``,
# ``post_mitigation_damage_per_cast``, ``dps``, and all other existing
# fields are byte-identical to 1.28.0 output. The 2 new fields default
# to ``()`` so existing consumers (rank.py, coach prompts, /api/state)
# remain forward-compatible.
#
# 1.28.0 (Phase 6 EHP healing throughput, 2026-05-21):
# Closes the ehp.py:23 deliberate Phase-1 omission "Healing throughput
# (lifesteal, Spirit Visage amp) - fits Phase 6". Three contributions
# now feed an EHP heal pool:
#   (a) item-passive heals via NEW ``ItemHeal`` dataclass +
#       ``ItemEffect.heal`` field: Sundered Sky 6610 / Arena 226610
#       "Lightshield Strike" 100% base AD melee / 50% base AD ranged
#       per one-trigger-per-fight (10s CD per target > 6s fight window).
#   (b) lifesteal-derived heal: ``stats.lifesteal * stats.ad * stats.as
#       * _FIGHT_WINDOW_S (6.0)`` accumulated over the standard fight
#       window. Pre-mitigation approximation (consistent with EHP's
#       no-enemy-pen Phase-1 posture).
#   (c) multiplicative heal amp via NEW ``ItemEffect.heal_amp_pct``
#       field: Spirit Visage 3065 / Arena 223065 "Boundless Vitality"
#       +25%. Multiple amp items stack multiplicatively per the
#       buff-system doctrine (batch 14).
# Bloodthirster 3072 / Arena 223072 "Ichorshield" rides the Phase 1.5
# ItemShield pipeline (full-cap steady-state assumption: 165 L1 -> 315
# L18, ANY damage type; overheal builds the shield between fights at
# base/walking). NO ``unique_passive_key="lifeline"`` - BT's Ichorshield
# is a distinct unique passive and can stack with any single lifeline
# shield in real builds.
# EhpResult gains heal_item_total / heal_lifesteal / heal_amp_mult /
# heal_total / heal_sources fields; compute_ehp folds heal_total into
# physical_ehp / magical_ehp / true_ehp at the top of the damage stack
# (heals don't discriminate by damage type, so the heal pool acts like
# an ANY shield).
# Deliberate Phase-6 omissions (deferred to Phase 6.5+):
#   * Death's Dance Defy heal-on-takedown (75% bonus AD over 2s) - the
#     takedown-rate assumption is uncertain; stays defensive_only.
#   * Spirit Visage amp on Phase 1.5 SHIELDS - the engine ships
#     heal-pipeline amp only. Builds pairing Spirit Visage with a
#     lifeline item under-credit by ~15% on the shield piece.
#   * Sundered Sky 6% missing-HP additive - requires a current-HP-share
#     assumption distinct from the steady-state full-HP convention.
#
# 1.27.0 (Phase 1.5 EHP shield throughput, 2026-05-21):
# Closes the ehp.py:21 deliberate Phase-1 omission "Shield throughput
# (Sterak's lifeline, Doran's Shield, Bloodthirster) - needs uptime
# modeling". Ships the four LIFELINE-style shields (single trigger per
# fight, value-additive to the effective-HP pool at top of the damage
# stack):
#   * Sterak's Gage 3053 - any-damage, 60% bonus_hp
#   * Immortal Shieldbow 6673 - any-damage, 400 L1-L8 -> 700 L18,
#     ranged x0.80
#   * Maw of Malmortius 3156 - magical, 200 + 150% bonus_ad, ranged x0.75
#   * Hexdrinker 3155 - magical, 110 L1-L8 -> 280 L18, ranged x0.75
# NEW ``ItemShield`` dataclass in _effects_types.py + ``ItemEffect.shield``
# field. EhpResult gains shield_any / shield_phys / shield_mag /
# shield_true / shield_sources fields; compute_ehp folds the shield_hp
# into physical_ehp / magical_ehp / true_ehp at the top of the damage
# stack (shields share the same armor/MR factor as HP per League's
# damage model). 4 lifeline items share unique_passive_key="lifeline"
# so rank.py's shares_dead_unique filter picks at most one in any
# generated build (compute_ehp itself does NOT apply dedup - the data
# layer carries the values, the planner decides which to keep).
# Bloodthirster's ichor-shield is intentionally DEFERRED to Phase 6
# (with the lifesteal model) - it requires overheal accrual rather
# than a single-trigger threshold.
#
# 1.26.0 (Dead Man's Plate Momentum stacks-schema lift, 2026-05-21):
# Closes BACKLOG "Dead Man's Plate Momentum stacks-schema" queued from
# overnight 2026-05-20 iter 15-16 (where the item was flipped to
# defensive_only because the dual-track Meraki formula didn't fit any
# existing schema). NEW ``PeriodicProc.stack_ramp_seconds`` field
# (default 0.0; backward-compat) - the family extension for the
# stack-accumulation -> discharge pattern. When > 0 alongside
# every_n_attacks > 0, the sustained model in ``_periodic_proc_dps``
# fires the proc once per ``max(stack_ramp_seconds,
# every_n_attacks * attack_period_s)`` - typically the ramp dominates
# (3.57s > 1/AS for non-attack-speed-stacked builds). The burst path
# (``_per_attack_proc_damage``) skips stack-ramp-gated procs because
# the burst window (2-3s) is shorter than typical ramps and these are
# tank/utility items whose DPS contribution is sustained-only.
# Dead Man's Plate (3742 + Arena mirror 223742) re-encoded:
# ``Shipwrecker`` proc = lambda c: 40.0 + c.base_ad PHYSICAL,
# every_n_attacks=1, stack_ramp_seconds=3.57. Full-stack discharge
# matches Meraki 16.10.1 spec: ``0.4 * 100 (cap 40) + 1.0 * base_ad``.
# Verified: Aatrox L11 + 3742 vs no items vs 100 armor target = 20.15
# DPS delta = (40 + 103.875) / 3.57 * 0.5 exactly. Other items can
# adopt the same schema in future iterations (Sterak's Lifeline once
# the EHP-vs-CC sim lands; hypothetical future ramp-discharge items).
# Schema is mutually exclusive with every_n_seconds (no ramp semantics
# in time-based path; ramp is implicit in the period).
#
# 1.25.0 (aram_tenacity_mult consumer wired into EHP, 2026-05-21):
# Closes BACKLOG "Future EHP enemy-CC model for aram_tenacity_mult"
# carry from item 113 (the field was forward-marker-stored on
# AbilityDpsResult in 1.23.0 but had no EHP-side surfacer or consumer
# helper). EhpResult now surfaces ``aram_tenacity_mult`` (default 1.0)
# read from ``resolved.stats.get("aram_tenacity_mult", 1.0)``. NEW
# module-level helper ``effective_cc_duration(base_cc_s, tenacity_mult)``
# returns ``base_cc_s * max(0.0, tenacity_mult)`` - the seam any future
# fight-sim / coach-prompt / EHP-vs-CC consumer reads to convert a base
# CC duration into the post-tenacity value. 17 ARAM champs carry
# non-1.0 aramTenacity in 16.10.1 (assassin-shaped +20% / +10%
# lengthening + a handful of shorteners). EHP's blended_ehp math is
# UNCHANGED - CC duration vs HP pool is a separate axis; consumers
# must pair tenacity_mult with their own base-CC assumption. SR + every
# non-ARAM mode degenerate to identity (tenacity_mult = 1.0; helper
# returns base_cc_s unchanged). format_table renders the tenacity line
# only when non-1.0 (parallel to mode_multiplier).
#
# 1.24.0 (per-item flat AH wired into compute_ability_dps, 2026-05-21):
# Closes BACKLOG item "DS item-level ability_haste lane". DDragon
# items.json's structured ``stats`` block strips ``AbilityHaste`` (only
# carries it in ``tags``); the numeric value lives in the localized
# description as ``<attention>N</attention> Ability Haste`` inside the
# leading ``<stats>...</stats>`` block. Meraki bulk strips per-item
# stats. NEW ``agents/daemon_slayer/_item_ability_haste.py`` ships a
# static 220-entry registry parsed from items.json description text
# at patch 16.10.1, with ``total_item_ability_haste(item_ids)``
# summer. Wired into ``compute_ability_dps`` as ``base_ah`` -> threaded
# through the existing 1.23.0 ``_total_ability_haste`` +
# ``_effective_ability_cd`` haste-formula consumer. SR + ARAM both
# benefit (ARAM additionally folds ``aram_ability_haste`` on top).
# Example: SR Black Cleaver (20) + Cosmic Drive (25) + Sorc Shoes (0)
# + Lich Bane (10) + Rabadon (0) + Zhonya (0) = 55 AH -> 7s base CD ->
# 7 / 1.55 = 4.52s effective. Pre-1.24.0 the engine pinned base CDs
# regardless of build AH (floor case ``base_ah=0.0``).
#
# Regeneration on new patches: re-parse items.json description text;
# subsequent matches (Mythic-passive AH grants, on-takedown procs) are
# intentionally ignored - the static lane carries only the build-time
# base stat.
#
# 1.23.0 (aramAbilityHaste + aramTenacity engine consumption, 2026-05-20):
# Closes the half-shipped state from ENGINE 1.19.0 (`6bba097` exposed
# the two ARAM modifier keys via the resolved stats dict but no scorer
# read them). The cooldown lane in
# ``agents/daemon_slayer/ability_dps.py`` now CONSUMES the
# ``aram_ability_haste`` delta via Riot's canonical haste formula
# ``eff_cd = base_cd / (1 + total_AH / 100)`` (mirrors
# ``core/summoner_cooldowns.py`` shipped 2026-05-20 `58d1e87` for
# summoner spells). 22 champs carry non-zero aramAbilityHaste in
# 16.10.1 - the consumer is now real, not a TODO:
# * positive deltas shorten the rotation (Soraka +10, Katarina +10,
#   Azir +20, Aurora/Camille/Hecarim/Irelia/Lucian/Naafiri/Rakan +10,
#   Leblanc +20)
# * negative deltas lengthen it (Seraphine -20, Teemo -15, Ziggs -20,
#   Corki -20, Brand/Mel/Milio/Sion/Smolder/Zyra -10)
# New helpers in ``ability_dps.py``:
#   * ``_effective_ability_cd(base_cd, total_haste)`` - the haste formula
#     primitive (denominator floor 0.01 against extreme negative haste).
#   * ``_total_ability_haste(scaled_stats, mode, base_ah=0)`` - mode-gated
#     read of the engine-exposed aram_ability_haste delta. SR + every
#     non-ARAM mode return base_ah unchanged; ARAM folds in the delta.
#     ``base_ah`` is reserved for the future item-AH lane - currently 0.
# Schema lift on ``AbilitySpellDps``:
#   * ``base_cooldown`` - pre-haste rank cooldown (back-compat: identity
#     to old ``cooldown`` field in SR + zero-haste-ARAM cases).
#   * ``total_ability_haste`` - the haste sum used in the formula.
# Schema lift on ``AbilityDpsResult``:
#   * ``aram_ability_haste`` - the consumed haste delta (0.0 outside ARAM).
#   * ``aram_tenacity_mult`` - forwarded for a future EHP-side enemy-CC
#     consumer; NOT consumed in this slice (the consumption point is in
#     a future EHP scorer that ingests enemy CC durations applied
#     against the receiving champion). Marker is in place so when that
#     scorer ships, the data is already on the result.
# Existing ``cooldown`` field on ``AbilitySpellDps`` now stores the
# EFFECTIVE post-haste cooldown. SR mode + most ARAM champions (those
# with aramAbilityHaste=0) see identity - the field is backward
# compatible. Forty-two test files in the DS test suite assert on
# ``.cooldown`` values for SR-mode builds (e.g.
# ``test_cooldown_inheritance.py``); all preserved because total_ah=0
# at SR. +26 new value-pinned tests in
# ``test_aram_ability_haste_consumption.py`` covering haste formula
# math, mode-gated composition, live snapshot consumption (Soraka Q
# 6.0 -> 5.4545 at +10 AH, Azir E 22.0 -> 18.333 at +20 AH, Seraphine
# Q lengthened at -20 AH, Teemo Q lengthened at -15 AH, Veigar
# zero-haste identity), tenacity forwarding, to_dict round-trip,
# backward-compat on Riven R / Qiyana Q / Veigar W SR baselines.
#
# 1.22.0 (cdragon-arena calculations formula evaluator, 2026-05-20):
# Phase 6 step 3 of the cdragon-arena `dataValues + calculations`
# enrichment closes the half-shipped state (dataclass layer landed
# `8f7a71b` 2026-05-20). New module
# ``agents/daemon_slayer/augment_formula_eval.py`` interprets the 4 cdragon
# `mFormulaParts` typed-part shapes (NumberCalculationPart /
# NamedDataValueCalculationPart / StatByNamedDataValueCalculationPart /
# StatByCoefficientCalculationPart) with the optional `mMultiplier`
# wrapper, composing via sum-of-parts. The evaluator is pure-function
# and PRE-WIRED into ``compute_augment_stats``: when an augment ships
# non-empty `calculations` AND any calc key maps to a canonical stat
# grant via ``STAT_GRANT_CALC_KEYS``, the evaluator displaces the
# hand-maintained ``_AUGMENT_STAT_OVERLAYS`` entry for that augment;
# otherwise the registry remains the source of truth. At cdragon 16.10.1
# NO augment ships a stat-named calc key (every key is damage / heal /
# shield / conversion - Typhoon "Damage" = 0.2 * AD, UndyingGuard
# "TotalDamage" = BaseDamage + 1.0*bonus_AD + 1.1*bonus_HP, etc.), so the
# ``STAT_GRANT_CALC_KEYS`` map is empty and the live behavior is
# unchanged. The seam exists for the next-patch slice when Riot ships a
# stat-named calculation (e.g. Arena S2 Augment Level-Up patch 26.09).
# Out of scope for this slice (return zero-contribution today; future
# evaluator extensions): ByCharLevelInterpolationCalculationPart,
# ByCharLevelBreakpointsCalculationPart, BuffCounterByCoefficient,
# SumOfSubParts, ProductOfSubParts, AbilityResourceByCoefficient,
# GameCalculationModified, hash-name parts (e.g. ``{b22609db}``). None
# carry stat-grant semantics at the current patch.
# +N tests in ``test_augment_formula_eval.py`` covering each typed-part
# shape, mMultiplier wrapping, part-sum composition, real-augment value
# extraction (Typhoon Damage = 0.2*AD, ServeBeyondDeath {85d7d7f0} =
# 10 * 0.25 = 2.5, UndyingGuard TotalDamage at bonus_ad=100/bonus_hp=200,
# JeweledGauntlet CritGranted), and the overlay-registry fallback. The
# evaluator is non-load-bearing for production callsites today; the
# ENGINE bump is the architecture seam that future patches consume.
#
# 1.21.0 (UX-headless iter 4 / DS audit lane: AP-scaling on-hit family,
# 2026-05-20): Nashor's Tooth Icathian Bite AP coefficient corrected
# 20% -> 15% per Meraki bulk 16.10.1 ("Basic attacks deal 15 (+ 15% AP)
# bonus magic damage on-hit"). Both 3115 (SR) and 223115 (Arena mirror)
# corrected. New pinned test test_nashors_tooth_meraki_16_10_1_coef
# guards the value (closed-form: at ap=100 the proc damage is 30.0).
#
# Other AP-scaling on-hit family members verified clean:
#   Lich Bane Spellblade (1.20.0) = 75% base AD + 40% AP magic
#   Guinsoo's Wrath (1.14.0) = 30 flat magic on-hit
#   Terminus Shadow (existing) = 30 magic on-hit constant
#
# No production callsite affected outside the registry.

# 1.20.0 (UX-headless iter 3 / DS audit lane: Spellblade family,
# 2026-05-20): Lich Bane Spellblade AP coefficient corrected 50% -> 40%
# per Meraki bulk 16.10.1 (the engine had drifted; current League math
# is 75% base AD + 40% AP, not + 50% AP). 16.10.1 Meraki verifies:
# "deals 75% base AD (+ 40% AP) bonus magic damage". Both 3100 (SR) and
# 223100 (Arena mirror) corrected; spellblade unique-passive family
# membership unchanged (still shares the key with Trinity Force /
# Iceborn / Sheen / Essence Reaver).
#
# Other spellblade family members verified clean against Meraki:
#   Trinity Force 3078 = 200% base AD physical (correct)
#   Sheen 3057        = 100% base AD physical (correct)
#   Essence Reaver 3508 = 125% base AD + 0.5/crit% physical (correct)
#   Iceborn Gauntlet 6662 = 150% base AD physical (correct)
#
# Spot-check Lich Bane drift on Ahri lvl 11 lone-item: weighted_dps 56.33
# -> 52.996 (-5.9%; the AP term contributes less per proc); test pins
# rebaselined in test_effects_expansion.py + test_spellblade_burst.py +
# test_ability_item_proc_p1l22.py. No callsite outside the registry
# affected.

# 1.19.0 (UX-headless iter 2, 2026-05-20): aramAbilityHaste +
# aramTenacity exposure lane. Pre-fix the engine ignored both keys (a
# comment in _apply_mode_modifiers said they "belong in their respective
# consumers" but no scorer ever wired them). 22 champs carry non-zero
# aramAbilityHaste in 16.10.1 (Soraka +10, Katarina +10, Azir +20,
# Seraphine -20, Teemo -15, etc); 17 carry non-1.0 aramTenacity
# (assassin-shaped +20% / +10% on Akali/Belveth/Ekko/Elise/Evelynn/Fizz/
# Katarina/Kayn/Khazix/Lucian/Nunu/Pyke/Qiyana/Quinn/Rengar/Talon/Zed).
# Both values now surface in the resolved stats dict via
# ``scaled['aram_ability_haste']`` (flat delta, default 0) and
# ``scaled['aram_tenacity_mult']`` (multiplier, default 1.0). Mode notes
# carry the values when non-baseline. Exposure-only - no downstream
# scorer consumes them yet; the data lane is now visible for the next
# scorer iteration (a cooldown-cycle modifier in burst.py / ability_dps
# or an effective-CC-duration term in an EHP-side enemy comp model).
# Additive (no existing scorer math changes), 11 new tests pinning the
# multiplier paths + SR-mode strip + live snapshot probes (Soraka +10,
# Katarina +10/1.2, Seraphine -20).

# 1.18.0 (UX-headless iter 1, 2026-05-20): HPS split aramHealing /
# aramShielding into per-side multipliers. Pre-fix the engine read
# aramShieldsHealing with a fallback to aramHealing and applied that one
# value to BOTH the healing_hps and shielding_hps lanes. The 16.10.1
# Meraki bulk carries the two keys independently; 24 champions in the
# snapshot have split values (Camille 1.20/1.10, LeeSin 1.10/1.20,
# Milio 0.95/0.90, Nunu 1.10/1.20, Ahri 0.90/1.00, Alistar 0.80/1.00,
# Annie 1.00/0.90, Bard 1.20/1.00, Briar 1.15/1.00, DrMundo 0.90/1.00,
# Hecarim 1.20/1.00, Illaoi 0.80/1.00, Ivern 1.00/0.90, Janna 0.90/1.00,
# Kayn 0.80/1.00, Khazix 1.20/1.00, Lux 1.00/0.90, Nocturne 1.20/1.00,
# Rell 1.00/0.90, Renekton 1.10/1.00, Swain 0.80/1.00, Tryndamere
# 1.20/1.00, Vladimir 0.90/1.00, Zac 1.10/1.00). The collapsed single-
# value mis-modeled the shield half on all 24. HpsResult gains heal_mult
# and shield_mult fields; the prior single mode_multiplier is preserved
# as a backward-compat property aliasing heal_mult so the healing-ratio
# invariant test still holds. +9 deterministic tests pinning the 4
# illustrative champ pairs from BACKLOG (Camille/LeeSin/Milio/Nunu),
# the per-side application inside compute_hps, the SR/ARAM ratio match,
# the mode_multiplier alias, and the legacy aramShieldsHealing-only
# fallback for older snapshots. Source: Meraki bulk
# /champions.json[name]/lolmath/aram_modifiers/{aramHealing,
# aramShielding} 16.10.1 snapshot.

# 1.17.0 (Iter 16, 2026-05-20): Structural-drift resolution lane vs Meraki
# bulk items 16.10.1 - the 2 items flagged by iter 15 closed in two
# different ways. (a) Sundered Sky 6610 + Arena 226610 Lightshield
# Strike recalibrated from pre-rework "20 + 200% base_ad" to
# "70 + 80% (base_ad + bonus_ad)" - same long-CD periodic shape and
# 8s cadence, but constants tracked to the 16.10.1 spec
# "60-80 bonus damage + 80% total critical damage modifier on the
# next-AA empowered crit" (70 = midpoint of the 60-80 band; 0.8 *
# total_AD approximates the empowered-crit delta-vs-normal-AA when
# the 80% total-crit-modifier applies). Full re-encoding as a true
# crit-guarantee burst proc deferred (would touch burst.py +
# dps.py + CallContext crit-damage field). (b) Dead Man's Plate
# 3742 + Arena 223742 Shipwrecker flipped to defensive_only - the
# Meraki 16.10.1 dual-track formula "0.4 * stacks (cap 40) +
# stacks% (cap 100%) * base_ad" requires a Momentum stack
# accumulation model the engine's periodic-proc schema doesn't
# support yet. Principled deferral: Dead Man's is a TANK pick
# where DPS contribution is incidental; defensive_only flip is
# safer than carrying a stale flat-magnitude estimate. Test delta:
# 5 lightshield-burst-harness expected values rebaselined (140 ->
# 118, 70 -> 59 with armor); 5 DeadMansPlateShipwreckerTests rewritten
# from active-periodic shape assertions to defensive_only + no-DPS-lift
# assertions. defensive_only count crosses both thresholds upward
# (assertGreaterEqual passes both s-31 >=40 and s-34 >=53 gates).
# 1.16.0 (Iter 15, 2026-05-20): Damage-magnitude lane audit vs Meraki bulk
# items 16.10.1 - 16 hardcoded item proc constants cross-checked.
# Two clean magnitude drifts fixed: (a) Hextech Alternator (3145) Revved
# 75 -> 65 bonus magic (Meraki: "Damaging an enemy champion deals 65
# bonus magic damage"); (b) Voltaic Cyclosword Firmament (6699 + Arena
# 226699) "100 + 25% bonus_ad" -> flat 100 bonus physical (Meraki:
# "next basic attack deals 100 bonus physical damage on-hit"; the 25%
# bonus AD scaling clause was a pre-rework formula). Two structural
# drifts FLAGGED but NOT fixed in this lane: (i) Sundered Sky 6610
# Lightshield Strike now reads "60-80 critical damage + 80% total
# crit damage modifier" - structurally different from the engine's
# "20 + 200% base AD" pre-rework formula. (ii) Dead Man's Plate 3742
# Shipwrecker new spec is "0.4 phys per Momentum stack, cap 40" plus
# "+ 0-100% bonus MS modifier", dual-track vs engine's "100 + 45% * 20"
# pre-rework formula. Both flagged for a follow-up structural-drift
# iteration (next session). 12 items confirmed MATCH (Stormrazor 3097,
# Kraken 6672 ramp, Statikk 3087, Rapid Firecannon 3094, Wit's End
# 3091, Guinsoo 3124 Wrath, Rageknife 6677, Recurve Bow 1043, Fated
# Ashes 2508, Runaan 3085, Trinity 3078 Spellblade, Bami 6660 - all
# verified against Meraki bulk effects strings). Test delta: 2 tests
# updated (test_3145_hextech_alternator_revved_proc 75 -> 65; new
# direct flat-proc assertion in test_voltaic_cyclosword_flat_proc).
# 1.15.0 (Iter 14, 2026-05-20): Arena mirror audit - synced two arena variants
# to their already-fixed SR base entries. (a) 226676 The Collector promoted off
# defensive_only and given lethality=10.0 to mirror iter-10 SR 6676 fix. (b)
# 223124 Guinsoo's Rageblade gained the Wrath +30 magic on-hit every-AA proc to
# mirror iter-12 SR 3124 fix; Phantom Hit untouched. Audited 14 SR/Arena pairs
# total (sunfire 223068 / dead-mans 223742 / titanic 223748 / hollow-radiance
# 226664 / nashor 223115 / wits-end 223091 / opportunity 226701 / LDR 223036 /
# horizon 224628 / riftmaker 224633 / crown 224644 / statikk 223087) - parity
# held on all except the two SR-recently-fixed items above. Endless Hunger
# 222517 verified defensive_only with no DPS contribution.
# 1.14.0 (Iter 12, 2026-05-20): Energized + spellblade + on-hit + cleave +
# anti-tank family audit vs Meraki / DDragon 16.10.1. Cross-checked Statikk
# Shiv / Rapid Firecannon / Stormrazor / Voltaic Cyclosword / Trinity Force
# / Lich Bane / Essence Reaver / Sundered Sky / Iceborn Gauntlet / Wit's End
# / Nashor's Tooth / Kraken Slayer / Runaan's Hurricane / Guinsoo's Rageblade
# / Terminus / Blade of the Ruined King / Stridebreaker / Profane Hydra /
# Giant Slayer (LDR + Bork). One drift fixed: Guinsoo's Rageblade was
# missing its Wrath flat-magic on-hit (DDragon 16.10.1 entry 3124 SR: "Wrath:
# Attacks deal 30 bonus magic damage on-hit" - permanent, every AA, separate
# from Phantom Hit every-3rd proc). Added as a 2nd PeriodicProc entry on
# 3124. Voltaic Cyclosword (4s charge), Statikk Shiv (180 magic / 10s),
# Rapid Firecannon (40 magic / ~3s), Stormrazor (100 magic / 4s), Lich Bane
# (75% base AD + 50% AP magic), Trinity Force (200% base AD), Essence Reaver
# (125% base AD + crit lerp), Iceborn (150% base AD), Sundered Sky (20 + 200%
# base AD / 8s), Nashor's (15 + 20% AP magic on-hit), Kraken (Bring It Down
# 150->200 every 3rd AA, level-stepped), Runaan's (2x 55% total AD bolts),
# Terminus (30 magic on-hit + 10/10 pen), Bork (9% target HP on-hit melee),
# Wit's End (45 magic on-hit), Stridebreaker / Profane Hydra (40% AD cleave),
# Giant Slayer LDR (15% / 1500 bonus HP) all already on Meraki 16.10.1
# values. Old Tiamat (id 3077) is currently a stat-only assassin component,
# no DPS proc to model (the cleave moved to Tiamat upgrades like
# Stridebreaker / Titanic Hydra / Profane Hydra). Vampiric Scepter (1053)
# and Cull (1083) are early components, defensive-side only.
# 1.13.0 (Iter 11, 2026-05-20): Level-scaling-formula audit lane vs Meraki
# 16.10.1. Walked every "level"-keyed lambda in _effects_data.py and cross-
# checked Statikk Shiv / Rapid Firecannon / Stormrazor / Voltaic Cyclosword
# / Sundered Sky / Riftmaker / Demonic Embrace / Liandry's / Heartsteel /
# The Collector / Eclipse / BotRK against the Meraki bulk-items endpoint
# stored at data/daemon_slayer/16.10.1/items_meraki.json. ONE drift caught:
# Statikk Shiv (3087) and its Arena mirror (223087) carried
# bonus_damage=110 every_n_seconds=3 (~36.7 magic/s) - an iter-7 era stale
# magnitude. Meraki 16.10.1 "Electrospark" is 3 attacks x 60 bonus magic
# within 8s on a 25->10s cooldown ramp (pp|25 to 10 for 6; L6+ steady-
# state 10s). Engine now encodes payload-per-cycle: bonus_damage=180,
# every_n_seconds=10 = 18 magic/s steady-state (same encoding shape as
# Kraken/Stormrazor: per-cooldown-cycle, NOT per-attack). Proc renamed
# "Electroshock" -> "Electrospark" to match Meraki's actual name (the
# "Electroshock" passive is the takedown-CD-reset secondary, not the
# main 3-attack chain). +7 audit tests in
# StatikkShivElectrosparkMagnitudeTests pinning magnitude, cadence,
# proc name, magical damage type, and Aatrox-L11 net-positive sanity.
# Other 11 lerp/per-level/level-gated sites confirmed correct vs Meraki:
# Rapid Firecannon 40 flat magic on-hit, Stormrazor 100 flat magic on-hit,
# Voltaic Cyclosword 100 + 25% bonus_ad physical + 10 lethality, Sundered
# Sky's 20+200%-base-AD approximation kept (refactoring the
# critical-damage-by-level 60-80 + 80% bonus-crit-damage form would
# require a guaranteed-crit schema lift, out of scope for this drift
# pass), Riftmaker's 8% damage_amp at max stacks (not level-ramped),
# Liandry's 1% target_max_hp burn per tick (not level-ramped), Heartsteel
# 70 + 6% max_hp (not level-ramped per Meraki 16.10.1 text), Eclipse's
# 6% target_max_hp (not level-ramped), Demonic Embrace's ramp is
# health-missing-driven not level-driven, BotRK 9% target_max_hp pinned
# in iter-7. The Collector executes at 5% max HP (already correct;
# the task hint "15% missing HP, NOT level-scaled" was a misread - the
# actual Meraki spec is 5% max HP, also NOT level-scaled, engine right).
# Streak: iter-11 lane=level-scaling-formulas FOUND drift (Statikk
# Shiv); resets to 1/10.
# 1.12.0 (Iter 10, 2026-05-20): Lethality + flat-pen audit lane vs Community
# Dragon 16.10 ground truth. Probed the engine entries for all 21 items in
# the audit set (8 lethality legendaries, 5 components, 4 Last-Whisper-family
# %-armor-pen, 5 magic-pen items, Hextech Alternator component) plus the
# 2 Arena IDs (Deathblade 228003, Spectral Cutlass 4004) and pulled CD's
# 16.10 description blob for every one. 20 of 21 match exactly: Hubris,
# Youmuu's, Edge of Night, Voltaic Cyclosword (10 with Firmament active is
# correct), Axiom Arc, Umbral Glaive, Duskblade, Serrated Dirk all at
# 18/15/10/18/18/18/10 lethality; Long Sword 0; Last Whisper 18%, LDR /
# Serylda's 35%, Mortal Reminder 30% (NOT 35 - wiki recall was wrong, CD
# confirms 30); Sorc Shoes 12 flat MP, Void Staff 40% MP pen, Shadowflame
# 15 flat MP, Hextech Alternator 0 (component, no pen); Spectral Cutlass
# 15, Deathblade 20. ONE drift: The Collector (6676) carries 10 Lethality
# in the stat block but had defensive_only=True with lethality=0.0 - the
# original entry was tagged for the Death execute (correctly NOT a per-
# rotation DPS proc) but the lethality plumbing batch (30) never promoted
# Collector off defensive_only the way it did Hubris / Youmuu's. The
# execute stays zero-rotation-DPS; the 10 Lethality stat block contributes
# to the rest of the rotation. Fix: promote off defensive_only, pin
# lethality=10.0, expand the note. +1 test in test_effects_expansion.py
# (Batch29DefensiveOnlyCoverageTests). Streak update: iter-10 lane=lethality
# -and-flat-pen FOUND drift (not no-change), streak resets to 1/10.
# 1.11.0 (Iter 8, 2026-05-20): Immolate family + Titanic Hydra Cleave drift vs
# Meraki 16.10.1. Iter 7 BotRK fix triggered a wider audit of every
# percentage-of-stat hit (`* c.<stat>_(hp|ad|ap)`). Four more drifts caught:
# (1) Sunfire Aegis 3068 Immolate "12 + 1.5% bonus_hp" -> Meraki "20 + 1%
# bonus_hp"; (2) Hollow Radiance 6664 "12 + 1.5% bonus_hp" -> "15 + 1%
# bonus_hp"; (3) Bami's Cinder 6660 "12 + 1% bonus_hp" -> flat 15 (no HP
# scaling at component tier - upgrades carry the HP scaling); (4) Titanic
# Hydra 3748 Cleave "5 + 1.5% bonus_hp" primary + "40% total AD" cleave-
# to-nearby -> "1% max_hp" primary + "3% max_hp" to nearby (shape change:
# bonus_hp -> max_hp; AD-coefficient -> max_hp-coefficient). Engine pins
# the melee value, same convention as Iter 7 BotRK / Eclipse / Hullbreaker
# / Kraken. All four SR items + their four Arena mirrors (223068, 226664,
# 226660, 223748) patched in lockstep. Schemas unchanged - dedup keys
# (immolate, hydra_cleave), every_n_seconds/attacks, periodics arity all
# stay - only the lambda magnitudes shift. +15 new audit tests in
# test_meraki_formula_audit_pipeline_a.py and 12 existing tests
# rebaselined to the corrected values. py_compile + ruff clean.
# 1.10.2 (Iter 7, 2026-05-20): BotRK Mist's Edge magnitude vs Meraki 16.10.1
# - was 8% target_max_hp (stale comment claimed "melee value; ranged 5%"),
# Meraki actually carries 9% melee / 6% ranged. Pipeline-A audit on
# 2026-05-19 corrected 5 items vs Meraki but missed BotRK; this is the
# follow-up. Both SR 3153 and Arena mirror 223153 patched. Engine still
# pins to the melee value (convention shared with Eclipse, Kraken,
# Hullbreaker). target_max_hp steady-state approximation unchanged
# (deliberate, documented at proc site). Riot's 100 damage cap vs
# minions/monsters not modeled - champion DPS only.
# 1.10.1 (Iter 3, 2026-05-19): hydra_cleave unique-passive family. All 4
# SR Tiamat-tree items (Ravenous Hydra 3074, Titanic Hydra 3748,
# Stridebreaker 6631, Profane Hydra 6698) + their 4 Arena mirrors
# (223074 / 223748 / 226631 / 226698) now declare
# unique_passive_key="hydra_cleave" so collect_effects's first-seen-wins
# dedup and the ranker's shares_dead_unique filter handle both layers
# in one shot. Previously the comment on Profane Hydra claimed
# "Tiamat-tree exclusivity is enforced by the ranker's build legality
# checks", but rank._filter_candidates has no such check - the engine
# was double-counting the Cleave proc on any 2+ hydra build and the
# ranker happily recommended a second hydra. Live League marks Cleave
# as a "Unique" passive (only one procs per AA). +9 tests in
# test_hydra_cleave_unique_iter3.py covering schema, collect_effects
# dedup, DPS no-double-count, and ranker filter behavior; 1 stale
# negative-assertion test flipped (test_profane_hydra_not_tagged
# _unique_passive -> _tagged_hydra_cleave_iter3). Build-order planner
# docstring updated 3-family -> 7-family count for accuracy. No
# rebaselines outside the flipped test.
