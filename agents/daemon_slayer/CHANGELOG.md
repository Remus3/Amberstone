# Daemon Slayer engine - changelog

Relocated verbatim from `agents/daemon_slayer/__init__.py` (item 241,
2026-06-01). The engine revision is `ENGINE_VERSION` in `__init__.py`;
this file is the full per-version history. New ENGINE bumps PREPEND one
entry to the changelog section (newest-first); never extend a prior line.

## Module overview (former __init__ docstring)

Daemon Slayer - local item-build engine.

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

## ENGINE version changelog (former __init__ comment block)

1.177.0 (R70, 2026-07-03 - Hollow Radiance Desolate champion-takedown eruption
on the DSV2 seam). Meraki 16.13.1 item 6664 passive "Desolate": "Scoring a
takedown against an enemy champion within 3 seconds of damaging them causes a
larger eruption that deals [hollow_ibase*4 = 60] (+ [hollow_ihp*4 = 4]% bonus
health) magic damage ... within 500 units" (= 400% of Immolate, base 15 + 1%
bonus HP). Small schema lift on the EXISTING default-OFF assume_takedown seam
(Hubris/Collector precedent): two END-appended ItemEffect fields
takedown_eruption_base / takedown_eruption_bonus_hp_ratio, pure helper
effects.total_takedown_eruption_damage, and a compute_burst_damage fold that
credits the eruption ONCE as MAGIC damage (MR-mitigated x mode_mult x
magic_amp - the exact DSV6 assume_magic_burst routing) sourced from
ctx.caster_bonus_hp; new BurstResult field takedown_eruption_damage + note
line. Pins: 6664 (SR) + Arena mirror 226664 (60.0 / 0.04; 226664 has no own
Meraki entry - mirror convention); no ARAM 326664 in the 16.13.1 pool
(guarded absent, R69 323152 precedent). The 200% NON-champion kill eruption
stays unmodeled (farm math, not fight math - registry notes document it).
R59 doctrine holds: burst-only, compute_dps untouched (the Immolate
PeriodicProc keeps the sustained aura tick - no double-count). Sunfire 3068 +
Hubris/Collector guarded zero-field. Flag OFF byte-identical. TDD RED-first
(test_item_takedown_eruption_r70.py, 24 tests RED 17F -> GREEN). 1.176.0 ->
1.177.0.

1.176.0 (R69, 2026-07-03 - Rocketbelt/Everfrost item-ACTIVE magic burst on the
DSV6 seam). Meraki 16.13.1 item 3152 Hextech Rocketbelt active "Supersonic":
dash + rocket arc dealing "100 (+ 10% AP) magic damage ... once per cast";
item 446656 Everfrost (Arena DISTRIBUTED) active "Glaciate": cone dealing
"300 (+ 85% AP) magic damage" + 70% slow / center root (CC not in this damage
lane). Pure DATA pin - no schema lift, no new seam: the one-cast active
magnitude is exactly the DSV6 single-proc burst-window shape, so 3152 + Arena
mirror 223152 (100 / 0.10) and 446656 (300 / 0.85) ride the EXISTING
magic_burst_base/magic_burst_ap_ratio fields read by total_magic_burst_damage
-> compute_burst_damage ONLY under the default-OFF assume_magic_burst flag
(MR-mitigated x mode_mult x magic_amp). DPS side intentionally unmodeled (long
cooldown actives, no PeriodicProc - no double-count; defensive_only stays True,
verified a doc-only flag with zero engine consumers). Variant guards: no ARAM
323152 in the 16.13.1 pool; legacy Everfrost 6656/226656 present but all map
flags False + absent from Meraki - unpinned, test-guarded. Flag OFF
byte-identical; live default-ON flip stays operator-gated
(docs/LIVE_GAME_GATED_SYNC.md B13 extended). TDD RED-first
(test_item_active_magic_burst_r69.py, 21 tests RED 10F -> GREEN). 1.175.0 ->
1.176.0.

1.175.0 (R68, 2026-07-03 - Thornmail/Bramble ITEM Thorns reflect on the R49 seam).
Meraki 16.13.1 item 3075 Thornmail passive "Thorns": "When struck by a basic
attack [[on-hit]], deal 20 (+ 10% bonus armor) magic damage to the attacker";
item 3076 Bramble Vest: flat 10 magic damage, same trigger. Both also inflict
Grievous Wounds (3s vs champions) - NOT modeled (healing debuff, outside this
damage lane; documented in the registry notes). New ITEM-keyed registry
_ITEM_REFLECT_OVERRIDES in _passive_reflect_overrides.py (id-string keyed, the
_target_vulnerability_overrides convention) + PassiveReflectEntry gains an
END-appended caster_bonus_armor_pct field + reflect_per_proc gains an
END-appended caster_bonus_armor kwarg (the Thornmail bonus-armor axis).
item_reflect_entry(item_ids, caster_bonus_armor) dedupes the Thorns UNIQUE
passive (Bramble is Thornmail's component): a build owning several thorn items
is credited ONCE - the strongest per-proc at the given stats. Registered ids:
3075 + pool mirrors 223075 (Arena map-30) / 323075 + 3076; Bramble mirrors
223076/323076 are NOT in the 16.13.1 DS pool and are NOT registered. Consumers:
dps.compute_dps + burst.compute_burst_damage fold the item reflect AFTER the
champion stream inside the EXISTING default-OFF assume_passive_reflect seam
(independent streams - Rammus W + item Thorns stack in game), MAGIC-mitigated
by the duel target's effective MR x magic_amp, amortized 1/reflect_cadence_s
(DPS) / window-scaled over _ASSUMED_REFLECT_BURST_WINDOW_S (burst), NOT added
to the per-attack on-hit display (incoming-triggered stream). Flag OFF the item
registry is never read - byte-identical. No new flag; live default-ON flip
stays operator-gated (docs/LIVE_GAME_GATED_SYNC.md B17 extended). TDD RED-first
(test_item_reflect_thornmail_r68.py, 31 tests RED->GREEN). 1.174.0 -> 1.175.0.

1.174.0 (R67, 2026-07-03 - Terminus "Juxtaposition" Dark 3-stack pen correction).
Meraki 16.13.1 item 3302: Dark hits grant 10% armor penetration and magic
penetration per stack, "stacks up to 3 times" = "30% resistances penetration at
maximum stacks". The registry had encoded a single Dark stack (0.10/0.10); per
the full-stack sustained-DPS convention (Black Cleaver 3071 5-stack 0.30 shred,
Guinsoo 3124 4-stack 0.32 cond-AS) SR 3302 + Arena mirror 223302 both move to
armor_pen_pct=0.30 + magic_pen_pct=0.30. Shadow (constant 30 magic on-hit,
every attack) untouched on both entries. Light hits (6-8 caster bonus armor+MR
per stack, level pp 1;11;14) stay OUT of item-schema scope - no item-keyed
resist-grant path exists (_passive_resist_overrides.py is champion-keyed only);
logged FUTURE, no schema field added. New hermetic Meraki-truth characterization
regexes the Dark per-stack pct + stack cap + the 30%-at-max-stacks prose out of
the vendored snapshot so a future patch changing any of them fails the suite
instead of silently drifting; property-style pen fold asserts 0.30 pen leaves
200-resist targets at exactly 140 effective on both axes and strictly beats
0.10 via _armor_factor monotonicity (test_terminus_juxtaposition_r67.py,
14 tests RED->GREEN). 1.173.0 -> 1.174.0.

1.173.0 (R66, 2026-07-03 - Guinsoo's Rageblade "Seething Strike" conditional AS).
Meraki 16.13.1 item 3124: basic attacks grant 8% bonus AS for 3s, stacking to 4
(32% total). Modeled on the EXISTING ungated R42 conditional-AS lane
(bonus_as_conditional, the field Yun Tal Flurry carries at 0.08 with no flag),
pinned at the full-stack steady state per repo convention (Black Cleaver 5-stack
shred, Mejai's full-stack AP): SR 3124 + Arena mirror 223124 both = 0.32. Gemini
director approved UNGATED (no new seam / flag). Wrath + Phantom Hit periodics
untouched. The fold is the existing base_as-scaled cond_as fold in compute_dps
(2.5 AS hard-cap re-clamp applies). New hermetic Meraki-truth characterization
regexes the per-stack pct + stack cap out of the vendored snapshot text so a
future patch changing either fails the suite instead of silently drifting
(test_guinsoo_seething_strike_r66.py, 9 tests RED->GREEN). 1.172.0 -> 1.173.0.

1.172.0 (ranged-only melee build-pool purchasability gate, 2026-07-02 - live-drain bug fix,
NOT a seam). DS /rank recommended the RANGED-ONLY Runaan's Hurricane (3085) for MELEE champions
(reproduced live on Irelia #5 SR and Viego #8 ARAM) - an item the in-game shop blocks on melee.
NEW RANGED_ONLY_ITEM_IDS = {"3085", "223085"} (Runaan's canonical + the Arena map-30 alias ONLY;
Rapid Firecannon 3094 and Statikk Shiv 3087 verified NOT range-restricted at 16.13.1 and stay
melee-buildable) is excluded from the candidate pool in the shared rank._filter_candidates builder
before the inject force-admit, gated by a champion_is_melee flag threaded through all 7 ranker
lanes (rank / ehp / hybrid / burst / hps / beam / _rank_mage). Melee = base attackrange <= 250
(mirrors ehp._is_ranged; Graves 425 and Kindred 500 classify ranged and keep Runaan's).
_champion_is_melee fails CLOSED to ranged so a missing/malformed champ record never over-filters a
real ranged carry. Purchasability correctness fix, independent of the B1 apply_melee_aa_gate DPS
seam (which only zeroes Runaan's bolt DPS and is default-OFF). Melee build-order tables change
(Runaan's removed) - NOT stamp-only. 15 RED->GREEN regression tests
(test_rank_ranged_only_purchasability.py). No backfill needed (/rank is ephemeral live compute).
1.171.0 -> 1.172.0.

1.171.0 (R60, 2026-07-02 - wielder Heal/Shield Power (HSP) amp seam. Distinct from
R59 (which scored the TARGET-side Lifeline shield): R60 scores the WIELDER's own
heal_shield_amp_pct (Redemption / Mikael / Ardent / Moonstone / Staff of Flowing
Water). NEW agents/daemon_slayer/_hsp_amp.sum_wielder_hsp_pct sums the caster's HSP
additively across the build (reusing the enchanter_items.json field hps.py reads).
DEFAULT-OFF assume_hsp_amp seam on ehp.compute_ehp (folds 1 + hsp_pct into the sibling
shield_amp_mult, amplifying the wielder's own item self-shields - Sterak's / Shieldbow
/ Maw - alongside Spirit Visage) and sustain.compute_sustain (amplifies REGEN-kind kit
self-heal only; vamp - LIFESTEAL / OMNIVAMP / SPELLVAMP / DRAIN - is NOT HSP-affected,
so a vamp-only champion is byte-identical even ON). hsp_pct 0.0 when OFF ->
BYTE-IDENTICAL to 1.170.0. HZ-B build-order tables re-stamped 1.170.0 -> 1.171.0
(content byte-identical - default rank math unchanged). Live default-ON flip
operator-gated (LIVE_GAME_GATED_SYNC B43).)

1.170.0 (R59, 2026-07-02 - target-side Lifeline shield seam in the OFFENSE scorers.
Where ehp.py already values the WIELDER's own Lifeline shield (Phase 1.5, ENGINE
1.27.0), this closes the symmetric omission: a modeled TARGET holding a Lifeline item
(Sterak's 3053 / Maw 3156 / Shieldbow 6673) absorbs part of the incoming burst. NEW
_lifeline_target_shield.target_lifeline_shield REUSES ItemShield.resolve_magnitude.
DEFAULT-OFF assume_lifeline_shield on compute_burst_damage (subtracts the shield from
total_burst_damage) + compute_dps (surfaces the magnitude, rate untouched). Byte-
identical OFF. Live flip operator-gated (LIVE_GAME_GATED_SYNC B42).)

1.169.0 (OQ18, 2026-07-02 - live-input wiring across the DS HTTP boundary (item-638
pattern). No math change: threads the producer-only-orphan live inputs across the
HTTP routes so each live-gated eyeball (LIVE_GAME_GATED_SYNC B31-B33, B4, B12) becomes
a pure flag flip, byte-identical when the body omits the input. server.py only (plus
the version stamp): ``_route_antitank`` gains ``level`` (R17/R39 ramp seam, B12 - scales
a ramp-seeded row's %max-HP / %current-HP magnitude toward its early endpoint; level=18
/ omitted is byte-identical) + ``item_ids`` / ``augments`` (P3.2 ``compute_antitank_live``
live build, B4 - resolves the champion's live AP/AD so a seeded ratio scales; empty /
omitted stays on the static path). Three NEW routes expose the dsp_live_consumers
producers: ``/summoner-fight-adj`` -> summoner_fight_adjustments (DSP5, B31, self+enemy
summoner sets -> EHP/tenacity/MS/DR/antiheal), ``/enemy-rune-threat`` -> enemy_rune_threat
(DSP6, B32, PtA amp / Conqueror ramp / Grasp poke-sustain / antiheal + ehp_divisor),
``/ally-protected-ehp`` -> ally_protected_ehp (DSP7, B33, an ally's EHP with its live
teammates' enchanter shield/heal/resist grants folded in). Every input DEFAULT-OFF/empty
-> byte-identical; the live default-ON plumb (feeding the real live-client summoner/rune/
ally set + eyeballing the adjusted readout) stays operator-gated. No engine-math file
changed (both antitank functions already accepted the args); additive read-only routes.)

1.168.0 (OQ17, 2026-07-02 - /rank* HTTP-boundary seam transport (item-638 pattern).
No math change: threads the existing ENGINE-ONLY default-OFF seams across the HTTP
routes so each live eyeball is a pure flag flip, byte-identical when the body omits
the flag. server.py only (plus the version stamp): ``_route_burst`` gains ``runes``
parsing + the six compute-direct seams assume_takedown (DSV2) / assume_ability_amp
(DSV4) / score_completion_runes (DSP4) / gate_target_hp_amp (R51) / gate_caster_hp_amp
+ caster_current_hp_pct (R53) - all /burst-scoped like R30 assume_magic_burst because
a flat keystone amp washes out of a candidate-baseline delta, so they read the
single-build burst NUMBER not the ranker delta. ``_route_rank_assassin`` gains the four
enemy-comp / kill-state ranking seams the burst ranker already forwards -
assume_takedown (DSV2) / assume_squishy_target (DSV3) / assume_ability_amp (DSV4) /
target_preset (DSP8). ``_route_dps`` gains apply_melee_aa_gate (B1), /dps-scoped like
R7/R12. Every seam DEFAULT-OFF/None -> byte-identical; the live default-ON flips stay
EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md rows B2/B3/B6/B18/B19/B34). EXCLUDED from OQ17:
R50 apply_all_out_bonus is a load-time AbilitiesSnapshot flag (not a per-call compute
param), so it is not a pure flag-flip and needs per-request snapshot construction -
logged as a separate follow-up. Client-helper emit (core/daemon_slayer_client.py) is a
follow-up: the raw HTTP boundary is already a pure flag-flip; the typed Python helpers
emit the new keys only once their named params are added.)

1.167.0 (R58, 2026-07-02 - assume_ms_utility seam: Movement Speed utility valuation
for the BRUISER/juggernaut (hybrid) scorer. New DEFAULT-OFF END-appended kwarg on
``compute_hybrid`` + ``rank_items_by_hybrid`` in ``hybrid.py``; all engine edits in
that one module. Pure helper ``_ms_utility_multiplier(resolved_ms, base_ms)`` credits
bonus MS over the champion's base MS as effective bruiser DPS: each 1 pct bonus MS
~= ``_MS_UTILITY_DPS_FRACTION`` (0.5, conservative operator-tunable uptime/stickiness
midpoint) pct effective DPS, total credit capped at ``_MS_UTILITY_DPS_CAP`` (0.15,
guards stacked pct-MS blowup); fail-soft identity on zero/missing base MS or
at-or-below-base resolved MS (slows never penalize). The multiplier rescales ONLY the
DPS term of ``hybrid_score`` / ``hybrid_delta_pct`` (baseline AND candidate, so a
shared multiplier cancels in the normalized pct); the raw ``dps`` / ``delta_dps`` /
``new_dps`` / ``delta_ehp`` surfaces keep RAW weighted_dps semantics - no double
counting with stat-derived DPS procs (Dead Man's Plate Shipwrecker pinned in tests).
New END-appended defaulted ``ms_utility_mult`` field rides HybridResult +
HybridRankedItem + both to_dict()s (key appended LAST); a "ms utility ON" note
surfaces the applied multiplier. Default False is BYTE-IDENTICAL: the OFF paths bind
the same raw values with the same op order (no new float ops), pinned by
omitted-vs-explicit-False full-dict equality tests. Worked pin: Darius (base MS 340,
alpha 0.65) + DMP 3742 + FoN 4401 (additive 0.04 + 0.04 pct MS -> 367.2) -> x1.04 on
the DPS axis; a zero-DPS MS item (FoN) gains exactly alpha * 0.5 * bonus_frac in
hybrid_delta_pct on a naked baseline. OUT OF SCOPE - handoff: the non-DDragon-stat MS
registry (Dead Man's Plate 3742 Shipwrecker +20 flat MS at 100 momentum stacks,
Force of Nature 4401 Steadfast +6 pct MS at max stacks) is NOT folded into resolved MS yet;
a follow-up registry would feed those into the same seam. Live default-ON flip
operator-gated as with every DS seam.)

1.166.0 (OQ11 / QA69 - static-CD ability-haste consumer. The item-233 name-keyed
``ability_static_cd`` wiki-sidecar accessor gets its behavioral consumer: the
per-spell DPS path bridges the priced FORM's name (Meraki names match the wiki
Template:Data page titles) to the accessor and, when the ability is genuinely
haste-immune, keeps the engine's own base cooldown instead of dividing by total
ability haste. HONEST COVERAGE - gated iff ALL THREE hold: the raw ``static``
value parses as a single plain positive number ("True" toggles + wiki formula
strings do not); the ability carries NO wiki recharge_ranks (Amumu Q "Bandage
Toss" static "3" + recharge 16..12 is the canonical charge-ability trap - its
real cadence is the haste-affected recharge timer); the parsed value agrees with
the engine's own base cooldown at the priced rank (Heimerdinger R "UPGRADE!!!"
static "3" vs cd 100..70 disagrees -> stays on the haste path). The gate sits on
the APPLICATION after the haste sum, so total_ability_haste keeps the honest
build-wide sum; a new END-appended defaulted ``static_cd`` marker rides
AbilitySpellDps + to_dict. Gated live at ship: Samira R "Inferno Trigger" (5s
flat, e.g. 45 item AH no longer shows 3.45s) and Swain R form-1 "Demonflare"
(8s, form-override only). Absent sidecar -> byte-identical haste path.)

1.165.0 (R55 - archetype-aware DEFAULT for the target_current_hp_pct seam. The seam
(item 374) scales ONLY the three genuine %-current-HP procs (BotRK 3153 / Hellfire 4017
/ Fulmination 443055). Before R55 it reached only the mage + assassin scorers; R55 plumbs
target_current_hp_pct into the CARRY (rank_items) and BRUISER (rank_items_by_hybrid)
scorers -> compute_dps too, and the server /rank + /rank-bruiser handlers now forward it.
A new caller-side resolver core.ds_archetype_hp_pct.archetype_target_current_hp_pct maps
an archetype to a conservative DEFAULT fraction (SUSTAINED / juggernaut -> 0.5, target
ground down over the fight; BURST + non-damage / unknown -> 1.0). The dispatcher
core.daemon_slayer_client.rank_for_primary_archetype opts in via a DEFAULT-OFF
assume_archetype_hp_pct flag - byte-identical when off (carry / bruiser get no override;
mage / assassin get the caller's value). The resolver lives in core, NOT the engine
package, so the :8893 HTTP client never imports agents.daemon_slayer in-process
(split-brain guard). The 0.5 value is a conservative DESIGN midpoint - lolmath.com is
parked/unreachable so it is not a measured constant. Live default-ON flip + exact-%
calibration EXCLUDED / operator-gated -> docs/LIVE_GAME_GATED_SYNC.md.)

1.164.0 (R53 - caster_hp gate seam for Last Stand 8299. Last Stand's amp scales with
the CASTER's health (DDragon 16.13.1 runesReforged.json longDesc verbatim: "Deal 5% -
11% increased damage to champions while you are below 60% health. Max damage gained at
30% health."). Item 232 already modeled that ramp in keystone_amp via _last_stand_amp
(1.0 at/above 0.60 caster HP -> 1.11 at/below 0.30) - unchanged and already correct for
16.13.1. The burst scorer, though, always fed Last Stand caster_hp_pct (live default
1.0 -> full HP -> NO amp), so Last Stand contributed NOTHING to the default burst
total. R53 adds a DEFAULT-OFF caster_hp gate seam: keystone_amp(..., gate_caster_hp=
False) (byte-identical parity plumbing - the 8299 ramp is single-sourced on
caster_hp_pct) + compute_burst_damage(..., gate_caster_hp_amp=False,
caster_current_hp_pct=1.0). When flipped ON, Last Stand's amp reads caster_current_hp_pct
instead of the shared caster_hp_pct, so Absolute Focus 8233 (gates on HIGH caster HP)
and Last Stand (gates on LOW caster HP) no longer conflict over one HP value. At the
DEFAULT gate_caster_hp_amp=False Last Stand reads caster_hp_pct exactly as pre-R53 ->
BYTE-IDENTICAL (all live/internal burst callers pass caster_hp_pct=1.0; no consumer
passes the flag). TDD RED-first test_rune_caster_hp_gate_r53.py (10). ENGINE 1.163.0 ->
1.164.0. Live default-ON flip EXCLUDED (do-not-flip-blind ->
docs/LIVE_GAME_GATED_SYNC.md).)

1.163.0 (R51 - target_hp gate seam for Cut Down 8017 / Coup de Grace 8014. The two
Precision slot-4 stacking_amp runes previously applied their flat 8% amp
UNCONDITIONALLY in keystone_amp (the burst-window approximation: a burst spans the
target HP range, so both gates - Cut Down >60%, Coup de Grace <40% - are met
somewhere inside the window). R51 adds a DEFAULT-OFF gate_target_hp seam:
keystone_amp(..., gate_target_hp=False) + compute_burst_damage(..., gate_target_hp_amp
=False). When flipped ON, keystone_amp honestly gates each amp on target_hp_pct per
the live DDragon 16.13.1 longDesc - Cut Down amps only when target_hp_pct is strictly
ABOVE 0.60, Coup de Grace only when strictly BELOW 0.40; magnitude 1.08 unchanged. At
the DEFAULT gate_target_hp=False the gate block is skipped entirely -> BYTE-IDENTICAL
to the pre-R51 unconditional approximation (no live consumer passes the flag). The
gate touches ONLY the two target_hp_above / target_hp_below runes; every other amp
rune ignores the flag. TDD RED-first test_rune_target_hp_gate_r51.py (15). ENGINE
1.162.0 -> 1.163.0. Live default-ON flip EXCLUDED (do-not-flip-blind ->
docs/LIVE_GAME_GATED_SYNC.md).)

1.162.0 (R50 - K'Sante P "All Out Bonus" bilinear caster-resist seam. The item-255
K'Sante entry seeds the base Dauntless Instinct mark consume (12 + 1% : 2% by level
of target max HP); its All Out Bonus - active only while K'Sante is in the
R-empowered All Out state - was the documented OMIT in _passive_damage_overrides
(the item-513 reject note: a bilinear caster_bonus_resist * target_max_hp PRODUCT
gated on All Out). R50 seeds it in a SEPARATE registry _ALL_OUT_BONUS_OVERRIDES
(NOT merged into _PASSIVE_DAMAGE_OVERRIDES, so the base entry stays byte-identical
and its prior-entry invariants are untouched). Verbatim 16.13.1
effects_descriptions: "1% (+ 1% per 100 bonus armor) (+ 1% per 100 bonus magic
resistance) of the target's maximum health" -> target_max_hp_pct 1.0 + two bilinear
terms (_per_100(1.0, caster_bonus_armor, target_max_hp) + the caster_bonus_mr
sibling), each 0 at the default no-build ctx, gated by conditional_probability 0.5
(documented amortized All-Out-uptime firing midpoint, operator-tunable - the
Brand / Sejuani convention). A NEW default-OFF load flag apply_all_out_bonus on
AbilitiesSnapshot.load appends a SECOND synthetic damage block onto K'Sante's P
form via _apply_all_out_bonus_overrides; independent of apply_passive_damage (both
flags ON coexist: base mark consume + All Out bonus). DEFAULT-OFF byte-identical
(flag False -> the new registry is never read; no live consumer passes it, so no
ranking changes). Live default-ON flip EXCLUDED (a WRONG precompute is worse than
none until validated in a real All Out fight) -> docs/LIVE_GAME_GATED_SYNC.md. TDD
RED-first test_passive_damage_all_out_bonus_r50.py (14). ENGINE 1.161.0 -> 1.162.0.)

1.161.0 (R49 - on-being-hit reflect damage seam + full-MR scaling target. Rammus W
Defensive Ball Curl reflects magic damage to basic attackers - a REACTIVE
(incoming-triggered) TOTAL-resist form that was a documented NOT-seeded case in
_passive_damage_overrides (item 513: "no caster total-MR _SCALING_TARGETS field AND
wrong cadence for that empowered-AA seam"). New module
agents/daemon_slayer/_passive_reflect_overrides.py (PassiveReflectEntry +
reflect_entry + reflect_per_proc + _ASSUMED_REFLECT_BURST_WINDOW_S), seeded 1 vs
verbatim 16.13.1 Meraki truth (data/daemon_slayer/16.13.1/champion_abilities.json
Rammus W: "dealt 15 (+ 10% total armor) (+ 10% total magic resistance) magic
damage", parse_status no_damage). The blocker is resolved by a symmetric schema lift:
AbilityContext gains a FULL-MR caster_mr attribute (the MR sibling of the existing
full-armor caster_armor) and _registries._SCALING_TARGETS gains the
("caster_mr_pct","caster_mr") mapping - byte-identical (value_at returns 0.0 for the
missing DamageBlock field on every existing block). compute_dps gains an END-appended
assume_passive_reflect=False flag; when True the reflect per-incoming-attack magnitude
(flat + % of the caster's resolved TOTAL armor + % of TOTAL MR) is MR-mitigated by the
duel target's effective MR (same curve the AA uses) + mode_mult + magic_amp + build
amp, amortized into DPS by the assumed incoming-attack rate (1 / reflect_cadence_s),
and folded into total + per-phase DPS (a separate incoming stream - NOT added to the
per-hit AA display). compute_burst_damage gains the same END-appended flag; when True
the reflect is credited over the assumed burst exposure window
(_ASSUMED_REFLECT_BURST_WINDOW_S / reflect_cadence_s procs) into total_burst, mirroring
the assume_magic_burst / assume_ally_detonation burst seams (the AA-probe compute_dps
call leaves the seam OFF -> no double-count). The % terms scale on the build's resolved
resists which do NOT include W's own active self-buff resists (the _passive_resist
EHP seam) - a documented modeling lower bound. DEFAULT-OFF byte-identical: both flags
default False -> the registry is never read -> identical to 1.160.0; no live :8893
default scorer flips them on. TDD RED-first test_passive_reflect_overrides_r49.py (16
cases). Live default-ON flip EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md. No new
dependency. Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced ->
1.161.0.)

1.160.0 (R46 - stacking permanent max-HP passive registry. A NEW survivability axis
and the SECOND EHP-NUMERATOR term (after the revive multiplier): champion passives
that grant PERMANENT bonus maximum health PER STACK and accumulate (effectively)
without bound over a game - not in the resolved stat block (not base-per-level, not
an item), so neither EHP scorer saw them. New module
agents/daemon_slayer/_passive_health_overrides.py (passive_health_stack_hp +
_PASSIVE_HEALTH_OVERRIDES), seeded 3 vs verbatim 16.13.1 Meraki truth
(data/daemon_slayer/16.13.1/champion_abilities.json): Sion W Soul Furnace (+4 health
per kill, the +15 large/champ upside omitted conservative; infinitely farm-stacking),
Cho'Gath R Feast (per-stack health from the parsed 'Bonus Health Per Stack'
damage_block [80,120,160] by R rank, level-gated at the level-6 ult), Swain P
Ravenous Flock (+15 per collected Soul Fragment). The per-stack HP is EXACT Meraki;
the assumed STACK COUNT by level is an operator-tunable CONSERVATIVE midpoint (the
live stack feed we lack), the analog of _REVIVE_PROB / _ASSUMED_FLAT_DR_INSTANCES.
compute_ehp gains an END-appended assume_passive_health_stacks=False flag; when True
the per-champ bonus max-HP is added RAW to every per-type EHP numerator (physical /
magical / true) exactly like ext_flat_hp / flat_mit_*, riding the same armor/MR curve
and lifting every damage-type EHP uniformly. DEFAULT-OFF byte-identical: the flag
defaults False -> passive_health_stack_hp returns 0.0 -> identical to 1.159.0; no live
:8893 default scorer flips it on. TDD RED-first test_passive_health_overrides_r46.py
(18 cases). Live default-ON flip EXCLUDED (no live stack feed) ->
docs/LIVE_GAME_GATED_SYNC.md. No new dependency. Credits Riot Data Dragon /
CommunityDragon / Meraki. DS :8893 bounced -> 1.160.0.)

1.159.0 (R45 - Poppy W low-HP doubled percent-of-resist tier. The item-268 percent-of-resist
survivability mode seeded Poppy W "Stubborn to a Fault" at +12% of TOTAL armor + MR but OMITTED
the "doubled to 24% while below 40% maximum health" conditional (verified vs
data/daemon_slayer/16.13.1/champion_abilities.json). R45 models that tier. PassiveResistEntry gains
three END-appended fields (low_hp_pct_armor, low_hp_pct_mr, low_hp_threshold, default 0.0 -> dormant);
resist_grants gains a keyword-only caster_current_hp_pct=1.0 (END) and, INSIDE the existing percent
block, adds an INCREMENTAL (low_hp_pct/100)*resist*prob when caster_current_hp_pct < low_hp_threshold
(base 12% + incremental 12% = 24% below 40% HP). compute_ehp + compute_hybrid thread
caster_current_hp_pct (END-appended default 1.0, forwarding only). Poppy seeded 12.0/12.0/0.40; Rell W
(15% of BONUS, already correct) UNCHANGED. DEFAULT-OFF byte-identical on two axes: apply_passive_resist
False short-circuits, and apply_passive_resist True at the default full-HP fraction (1.0 not < 0.40)
leaves the low-HP branch dormant -> identical to 1.158.0. TDD RED-first
test_passive_resist_low_hp_tier_r45.py (RED 15-fail proof). The directive's "Poppy 10%/20%, Rell 10%"
numbers were WRONG vs Meraki 16.13.1; the shipped 12%/24%@40% + Rell 15%-bonus are correct. No new
dependency. Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.159.0.)

1.158.0 (R43 - Imperial Mandate target-vulnerability mark, executing R41's handoff.
DDragon 16.13.1 item.json 4005 reworked to "Command: On Immobilizing an enemy champion, mark them as 7%
Vulnerable for 4 seconds" - a +7% increased-damage-from-ALL-SOURCES mark, the shape _target_vulnerability_
overrides models. Seeded 4005 (SR) / 224005 (Arena) / 324005 (ARAM) at amp 0.07 into _ITEM_VULN_OVERRIDES
(the same multi-mirror doctrine as Evenshroud 3001/223001). The 16.13.1 official rework SUPERSEDES the stale
Meraki mirror (items_meraki.json content_patch None, which still shows the old "Coordinated Fire" current-HP
detonation) - an official Riot rework overrides a null-provenance community mirror (do-not-flip-blind). 4005
removed from both non-fit handoff registries (_NONFIT_VULN_CANDIDATES here + _NONFIT_DETONATION_CANDIDATES in
_ally_detonation_overrides, now both empty). Consumed only under apply_target_vuln=True (default-OFF,
byte-identical); a build holding Imperial Mandate is amplified x1.07. TDD RED-first
test_target_vulnerability_overrides_r43.py; the R12 + R41 non-fit assertions flipped. No new dependency or
schema. Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.158.0.)

1.157.0 (R42 - Yun Tal conditional-AS (Flurry) unit-mismatch fix. compute_dps folded cond_as - a
bonus-AS FRACTION from total_conditional_as (uptime-weighted ~0.08) - directly onto the FINAL rotation
AS, but stats["as"] is attacks/sec (the engine resolves it as base_as * (1 + bonus_pct)), so the raw add
over-credited AS by a factor of 1/base_as. Corrected to scale the fraction by the champion's innate base
AS before adding (base_as * cond_as), mirroring the R7 passive_as fold directly below it, with the same
2.5 League hard-cap re-clamp; the explain note now reads "+X% bonus AS ... folded onto base AS".
raw_attack_dps is unchanged (it reads the un-folded eff_as). TDD RED-first
test_conditional_as_base_fold_r42.py. No new data, dependency, or schema.)

1.156.0 (R41 - ally mark-detonation magic-damage seam, default-OFF, byte-identical.
A handful of champions lay a MARK an ALLY consumes for bonus damage - the mark-enabler's contribution to
TEAM damage, distinct from the self-amp (_ability_amp_overrides) and all-source-vulnerability
(_target_vulnerability_overrides) mark registries. R12 explicitly handed this seam off. New PURE module
_ally_detonation_overrides.py (no engine imports) returns the pre-mitigation raw detonation magic; both
compute_dps and compute_burst_damage gain an assume_ally_detonation flag (END-appended, default False ->
byte-identical) that credits it: per-event magic for burst, per-event/cadence for the DPS rate, each
MR-mitigated (magic routing) + mode_mult + magic_amp + the _ASSUMED_ALLY_DETONATION_PROB=0.5 assumed ally
proc rate. Seeded Leona P Sunlight (FLAT_MAGIC 32:151 based on level, 2.5s mark cadence), VERIFIED vs
champion_abilities.json 16.13.1. Imperial Mandate 4005 - the directive's named 10% current-HP detonation -
is a documented NON-FIT: DDragon 16.13.1 shows it reworked to a 7% Vulnerable all-source amp (Control /
Command passives); the old Coordinated Fire detonation is gone (only the stale Meraki mirror, content_patch
None, still carries it), so seeding it would be a WRONG precompute - it now belongs in
_target_vulnerability_overrides. An unmarked champion contributes 0 even with the flag on. The live
default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md). Offline Meraki-grounded characterization
tests (test_ally_detonation_r41.py, 19 cases). Credits Riot Data Dragon / CommunityDragon / Meraki. DS
:8893 bounced -> 1.156.0.)

1.155.0 (R39 - anti-tank current-HP level-ramp endpoints, default-OFF, byte-identical.
The CURRENT_HP-kind sibling of R17 (1.151.0). A real subset of the antitank %current-HP rows deal a
percentage that scales with the CASTER's champion level - Senna P Absolution "1% : 10% (based on level) of
target's current health". AntiTankEntry gains optional current_hp_ramp_lo / current_hp_ramp_hi endpoints
(default 0.0, END-appended so every positional / P3.2 / R17 construction survives), and a parallel
_current_hp_level_ramp_factor shares R17's lerp through an extracted _ramp_lerp_factor helper.
_effective_magnitude multiplies BOTH ramp factors; a row carries at most one ramp pair (max-HP OR current-HP,
never both), so the other factor is always 1.0 and every existing row is byte-identical. With level=None (the
/anti-tank route default) and at level 18 the score equals the item-308/315/R17 value; below 18 a seeded row
discounts toward its current_hp_ramp_lo endpoint. Seeded set = the 1 CURRENT_HP champion-level ramp in
antitank_registry_notes.json (patch 16.12.1): Senna P 1:10. The live default-ON flip (a survivability / draft
consumer calling with the live champion level) is operator-gated (docs/LIVE_GAME_GATED_SYNC.md). Offline
Meraki-grounded characterization tests (test_antitank_ramp_current_hp_r39.py, 28 cases). Credits Riot Data
Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.155.0.)

1.154.0 (item 638 - live-flip seam flags wired across the /rank HTTP boundary + R5 self-HP, default-OFF, byte-identical.
The seam flags (off-class WIN exemption, kit-axis WIN credit, survivability-by-win, magic-burst, passive-as-stacks,
target-vulnerability, cost ceiling, and the caster missing-HP heal amplification) previously existed only on the
in-process scorers; the /rank route family neither accepted nor forwarded them, so the served build ranking always
ran every scorer at its DEFAULT. server.py /rank + /rank-tank + /rank-bruiser + /rank-assassin + /rank-enchanter now
read the applicable flags from the request body and thread them into the archetype scorer; passive-as-stacks +
target-vulnerability exposed on /dps, magic-burst on /burst. hps.py compute_hps + rank_items_by_hps gain
assume_missing_hp_heal_amp + caster_missing_hp_pct (END-appended), forwarded into compute_ability_hps. Every flag
defaults OFF / null / 0.0; a request omitting a flag is byte-identical to the prior version, and the default-ON
activation of any flag is a separate gated decision. (Backfilled 2026-06-30 under R39 - the engine changelog entry
was omitted when 1.154.0 shipped 2026-06-27; sourced verbatim from the Share/CHANGELOG.md 1.153.0 -> 1.154.0 entry.)
Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.154.0.)

1.153.0 (R35 - survivability percent-DR LIVE consumer, default-OFF, byte-identical.
R19 shipped the forward-marker accessor DataSnapshot.spell_damage_reduction_pct(champ, slot) (per-rank PERCENT
damage reduction from champion_abilities.json defensive modifier blocks, pure-% filter) with NO consumer. R35 wires
it into _passive_mitigation_overrides.mitigation_multipliers via a new trailing snapshot=None param: when a snapshot
is passed AND apply_passive_mitigation is True, each (champ, slot) percent-DR block folds into the matching EHP
DENOMINATOR multiplier (mit_phys / mit_mag / mit_true) exactly like a hand-authored PassiveMitigationEntry active -
read at _ASSUMED_ABILITY_RANK=4 (index 3, clamped to the per-rank tuple bounds), amortized by _ACTIVE_DR_PROB=0.3
(these are cooldown-gated self-buffs), and classified to an axis by case-insensitive substring (a "physical" token ->
PHYS, a "magic" token -> MAG, else ANY). The substring classify follows the LIVE 16.13.1 labels, which the directive's
literal 3-key map missed: "Damage Reduction", Braum's lowercased "Damage reduction", "Magic Damage Reduction",
"Physical Damage Reduction", MasterYi's "Modified Damage Reduction". 8 champs land in the snapshot map (Alistar R,
Belveth E, Braum E, Galio W split phys+mag, Garen W, Gragas W, MasterYi W, Warwick E); a forward-safe
_HAND_AUTHORED_DR_CHAMPS guard skips the snapshot fold for any champ already in the curated registry so a future
overlap is never double-counted (disjoint today). compute_ehp passes its existing snapshot through to the consumer.
DEFAULT-OFF (apply_passive_mitigation=False) short-circuits to (1,1,1) before the snapshot is consulted, and the
legacy 3-arg call (snapshot defaults None) is unchanged, so live DS output is byte-identical. Two item-261 / item-262
characterization tests that used Garen as a "no-DR" baseline were repointed to Ashe / Caitlyn (Garen now carries a
folded snapshot DR block). The live default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md). Offline
champion_abilities.json-grounded characterization tests (test_passive_mitigation_snapshot_r35.py, 13 cases).
Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.153.0.)

1.152.0 (R30 / DSV6 - on-cast magic-burst valuation seam, default-OFF, byte-identical.
The per-cast burst combo loop (compute_burst_damage) sums only ability casts + AA hits, so item on-cast magic
procs (Luden's Echo 6655 75+5%AP, Stormsurge Squall 4646 125+10%AP, Malignance Hatefog 3118 180+15%AP) were never
credited in a burst window - AP/magic builds scored too low on the offense-burst axis. ItemEffect gains two
END-appended fields magic_burst_base / magic_burst_ap_ratio (default 0.0, the one-shot burst-window magnitude;
every positional construction survives), plus effects.total_magic_burst_damage(effects, caster_ap). Both consumers
gain assume_magic_burst (default False). compute_burst_damage folds sum(base + ap_ratio*ap) MR-mitigated (MAGIC
routing) x mode_mult x magic_amp into total_burst - the same mitigation + amp shape the periodic layer applies to
these exact procs in compute_dps. compute_ability_dps takes the param for caller API symmetry but is DELIBERATELY
INERT (byte-identical ON or OFF): a one-shot magnitude has no dimensionally-sound place in a per-second metric, and
compute_dps already values these at their PeriodicProc rate (ability_dot_only=False), so folding them in the
ability-DPS scorer would be wrong-units AND a partial double-count. DEFAULT-OFF leaves every existing item + caller
byte-identical. The live default-ON flip (a scorer/rank call with assume_magic_burst=True) is operator-gated
(docs/LIVE_GAME_GATED_SYNC.md). Offline Meraki-grounded characterization tests (test_magic_burst_valuation_dsv5.py).
Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.152.0.)

1.151.0 (R17 - anti-tank level-ramp %max-HP endpoints, default-OFF, byte-identical.
A real subset of the antitank %max-HP rows deal a percentage that scales with the CASTER's champion level
(Aatrox P "4% : 8% (based on level)", Brand P "8% : 12%", Skarner P "5% : 9%", ...). AntiTankEntry gains optional
ramp_lo / ramp_hi endpoints (default 0.0, END-appended so every positional/P3.2 construction survives), and
compute_antitank / _mechanism_value / _effective_magnitude take an optional level. The hand-tuned magnitude encodes
the LATE-game (max-ramp) reliability; when a level is injected a ramp-seeded row's effective magnitude scales by the
new _level_ramp_factor = lerp(ramp_lo, ramp_hi, (level-1)/17) / ramp_hi, so level=18 AND level=None (the /anti-tank
route default) are byte-identical to item 308/315 and early levels discount toward ramp_lo. Seeded 10 verified MAX_HP
champion-level ramps from the patch-16.12.1 registry source_quotes: Aatrox P 4:8, Brand P 8:12, KSante P 1:2,
Mordekaiser P 1:5, Ornn P 10:18, Renata P 1:2, Skarner P 5:9, Urgot P 2:6, Zed P 6:10, Zeri P 1:11. Every un-ramped
row is byte-identical at any level (the additive contract, mirrors P3.2). Offline characterization tests RED-first
(test_antitank_ramp_r17.py). The live default-ON flip (a consumer calling with the live champion level) is
operator-gated (docs/LIVE_GAME_GATED_SYNC.md). Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893
bounced -> 1.151.0.)

1.150.0 (R14 - cc_conditional durations_floor_s guaranteed-minimum CC floor band, default-OFF, byte-identical.
A distance / channel-scaled conditional CC entry encodes its MAX payoff in durations_s (Maokai R 2.25, Hecarim R
1.5, Ashe R 3.5, KSante W 1.0, Sion R 1.0); the new optional ConditionalCcEntry.durations_floor_s field records
the GUARANTEED close-range / min-channel minimum the CC always lands (Maokai 0.75, Hecarim 0.75, Ashe 1.0,
KSante 0.5, Sion 0.25 per Meraki 16.12.1 effects_descriptions). NEW default-OFF apply_cc_floor seam on
cc_pressure.compute_cc_pressure: when ON a floor-tagged entry is credited floor + probability * (max - floor)
instead of max * probability, in BOTH the standalone and the coexistence MAX-rule paths (_conditional_credit_seconds).
Seeded 5 - 4 existing entries gain a floor + a NEW Ashe R entry (coexists_with_unconditional=True, range_gated,
mirrors Maokai/Hecarim R; Ashe R also in the unconditional _PER_SPELL_CC_DURATIONS at 1.5). Loader reads the field
via .get (backward-compat; the ~60 untouched records stay floor=None). Default OFF byte-identical; the live
default-ON flip + ehp/hybrid propagation are operator-gated (docs/LIVE_GAME_GATED_SYNC.md). Offline
characterization tests RED-first. Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.150.0.)

1.149.0 (R12 - all-source TARGET-VULNERABILITY mark registry, default-OFF, byte-identical. The cross-source
sibling of the per-spell self-amp _ability_amp_overrides registry: a vulnerability MARK makes the marked TARGET
take +X% damage FROM ALL SOURCES (the wielder's autos, abilities, item procs, and allies), the all-source half a
per-spell self-amp can never express. NEW _target_vulnerability_overrides.py with two registries by source kind -
_CHAMPION_VULN_OVERRIDES keyed by champion_id (an ABILITY that marks) and _ITEM_VULN_OVERRIDES keyed by item-id
string (an ITEM passive that marks) - plus TargetVulnEntry (amp, source_key, kind, note) and
target_vuln_multiplier(champion_id, item_ids) composing the product of (1+amp) over every mark the wielder owns
(multiplicative per independent amp source, de-duped per unique item id). SEEDED 2 ACTIVE (ground truth 16.12.1):
Vladimir R Hemoplague (DDragon Vladimir.json tooltip 'take {{e2}}% increased damage from all sources',
effect[2]=[10,10,10] -> 0.10 rank-flat); Evenshroud 3001 + Arena 22-mirror 223001 (items.json 'Coruscation: ...
take 7% increased damage for 5 seconds' -> 0.07). NON-FIT (recorded in _NONFIT_VULN_CANDIDATES, NOT seeded):
Imperial Mandate 4005 - patch 16.12.1 'Coordinated Fire' is a current-HP mark-DETONATION (allies consume for 10%
current-HP bonus magic damage, 9s/target CD), NOT a +X% all-source multiplier, so it is honestly excluded rather
than modeled as a fictional 6% amp (a WRONG precompute is worse than none; it belongs in an ally-detonation seam).
compute_dps gains apply_target_vuln: bool=False (appended at END); when ON, weighted_dps + every phase_dps is
multiplied by target_vuln_multiplier(resolved.champion_id, resolved.item_ids), scaling the wielder's whole DPS
output (AAs + procs + the routed on_hit passive). The seam models the fully-marked target at full magnitude (the
assume_takedown / assume_ability_amp developed-fight doctrine); uptime gating is a live-consumer concern. Default
OFF byte-identical; the live default-ON flip + ability_dps/burst consumer broadening are operator-gated
(docs/LIVE_GAME_GATED_SYNC.md). Credits Riot Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.149.0.)

1.148.0 (R9 - per-instance FLAT-AMOUNT damage-reduction EHP registry, default-OFF, byte-identical.
The MISSING SIBLING of the percent _passive_mitigation_overrides registry, which deliberately EXCLUDED
(its docstring) the survivability class that reduces a FLAT NUMBER per damage instance, naming Fizz P,
Amumu E, Leona W. R9 adds exactly that excluded class as a NEW sibling registry
_passive_flat_mitigation_overrides.py (it does NOT modify the percent registry). WHY A SEPARATE
REGISTRY + a DIFFERENT EHP seam: a flat per-instance reduction is hit-count / instance-size dependent,
not a clean steady-state multiplier on the damage axis - it prevents instances * flat * prob of damage
over a fight window, behaving like bonus effective-HP, so it folds into the EHP NUMERATOR exactly like
ext_flat_hp (the enchanter ally flat-HP grant), NOT the denominator (the percent registry divides
mit_phys/mag/true). NEW PassiveFlatMitigationEntry (terms tuple of (flat_or_per_rank_tuple, type),
cap_frac=0.5, conditional_probability, rank_scaled) keyed (champion_id, key, form_index).
flat_mitigation_hp(cid, level, assume_passive_flat_mitigation) -> (phys, mag, true) prevented HP; OFF
(default) -> (0.0, 0.0, 0.0) -> byte-identical. _ASSUMED_FLAT_DR_INSTANCES=6.0 is the operator-tunable
conservative per-instance count (the live per-instance feed we lack, the analog of the percent
registry's _ACTIVE_DR_PROB). SEEDED 3 (ground truth champion_abilities.json 16.12.1, effects_descriptions
+ the parsed damage_blocks flat modifier): Fizz P 'reduces every instance of incoming damage by 4 (+ 1%
AP), up to a maximum of 50% reduction' -> flat 4 ANY innate prob 1.0 (+AP omitted); Amumu E 'reduces
every instance of pre-mitigation physical damage taken, capped at 50% of the damage instance' -> flat
per-rank [5,7,9,11,13] PHYS passive prob 1.0 from the 'Physical Damage Reduction' modifier (+3%
bonus-armor/MR omitted, rank_scaled); Leona W 'gaining flat damage reduction of up to 50% of the damage
instance' -> flat per-rank [8,12,16,20,24] ANY active amortized at 0.3 from the 'Flat Damage Reduction'
modifier (bonus-armor/MR is a resist-grant axis, not a flat-DR term; rank_scaled). DATA-DRIVEN
PER-RANK note: the source assumption was a per-LEVEL amount, but the 16.12.1 data shows Amumu E + Leona
W carry a per-RANK flat block (5 ability ranks) read at _ASSUMED_ABILITY_RANK=4, not an 18-level curve.
The cap_frac (0.5) is recorded for provenance but NON-BINDING at representative instance sizes (a flat
4-50 is far below 50% of a 100-300 final-damage instance) so it is not applied in the prevented-HP
arithmetic. compute_ehp + rank_items_by_ehp gain assume_passive_flat_mitigation: bool=False; the
prevented HP adds RAW to each per-type EHP numerator (main math + the _blend_with_heal sustain
recompute) and rides the SAME armor/MR curve, so blended_ehp + cc_blended_ehp inherit it; the pre-vs-
post-mitigation simplification (Amumu reduces pre-mitigation) is a documented bounded over-credit.
EhpResult gains passive_flat_mit_phys/mag/true (default 0.0, appended at END). Default OFF
byte-identical; the live default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md). Credits Riot
Data Dragon / CommunityDragon / Meraki. DS :8893 bounced -> 1.148.0.)

1.147.0 (R7 - per-stack champion self-Attack-Speed passive seam on the AA DPS scorer, default-OFF,
byte-identical. A class of champion INNATE passives grant the champion a per-stack bonus ATTACK SPEED
that ramps to a documented ceiling at max stacks; the stat pipeline (engine.build_champion) has no
signal for these innate stacking self-AS buffs, so compute_dps under-credited a champ at full stacks.
NEW _passive_as_overrides.py registry (PassiveAsEntry per champion_id: per_stack_low/high bonus-AS
FRACTION by level + max_stacks + ap_per_stack_per_100) - the ATTACK-SPEED sibling of the item-effect
total_conditional_as (Yun Tal) lane. compute_dps gains assume_passive_as_stacks: bool=False; when ON,
passive_as_bonus(cid, level, ap, stack_fraction=_ASSUMED_PASSIVE_AS_STACK_FRACTION=1.0) =
per_stack_at(level, ap) * max_stacks * fraction folds into the rotation AS with the SAME 2.5 League
hard-cap re-clamp as the Yun Tal conditional-AS path (raw_attack_dps left at the no-conditional
baseline, matching cond_as). per_stack * max_stacks == the documented max by construction, so the
full-stack assumption is self-clamping. SEEDED 4 (ground truth champion_abilities.json 16.12.1, Meraki
content patch 25.15, effects_descriptions): Irelia Ionian Fervor 10%:25% by level/stack max 4 ->
40%:100%; Jax Relentless Assault 5%:12.5% by level/stack max 8 -> 40%:100%; Ezreal Rising Spell Force
10% flat/stack max 5 -> 50%; Volibear The Relentless Storm (5% + 4% per 100 AP)/stack max 5 -> 25% +
20% per 100 AP (the one AP-scaled passive, reads the resolved post-amp AP). A champion with no
registered passive is byte-identical even with the flag on. Default OFF byte-identical; the live
default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md; CLAUDE-Settled "per-stack
assumed_stacks"). DS :8893 bounced -> 1.147.0.)

1.146.0 (item 515 - missing-HP heal-AMPLIFICATION seam on the ability-HPS scorer, default-OFF,
byte-identical. A heal-AMP MULTIPLIER class distinct from the heal-MAGNITUDE units: several abilities
scale their OWN heal output UP as the caster's health drops ("healing increased by 0% : X% based on
missing health") - the class the item-253 _passive_heal_overrides header explicitly EXCLUDED from the
heal-magnitude registry (a comeback multiplier on the heal already computed, not a heal amount scaling
on a stat). NEW _MISSING_HP_HEAL_AMP[champion_id][spell_key] = max_bonus registry in ability_hps.py
(co-located with _AOE_HEAL_TARGETS) + _missing_hp_heal_amp_factor(champ, spell, missing_pct) = 1 +
max_bonus * clamp(missing_pct, 0, 1). compute_ability_hps gains assume_missing_hp_heal_amp: bool=False;
when ON, a registered (champ, spell) heal_per_cast is multiplied by the factor using the existing
caster_missing_hp_pct param (HEAL-only - every seeded entry amps healing, not shielding). SEEDED 4
(ground truth champion_abilities.json 16.12.1 effects_descriptions): Master Yi W Meditate, Lissandra R
Frozen Tomb, Sylas W Kingslayer all "0% : 100% (based on missing health)" -> 1.0; Briar P Crimson Curse
"increases healing from all sources by 0% : 40% (based on missing health)" -> 0.40 (its + per-100-bonus-
health sub-term omitted = conservative lower bound). Nidalee E (Primal Surge, a directive example) was
probed and carries NO missing-HP amp text -> NOT seeded (never fabricate). Default OFF + full-HP (0
missing) are both byte-identical; the live default-ON flip is operator-gated (docs/LIVE_GAME_GATED_SYNC.md).
DS :8893 bounced -> 1.146.0.)

1.145.0 (item 513 - passive_damage caster-defensive-stat scaling schema lift, default-OFF. Some
empowered-AA passives deal bonus damage scaling on the CASTER's bonus armor / bonus magic resistance
(the resist-tank "I hit harder the tankier I am" form). The DamageBlock.bonus_armor_pct / bonus_mr_pct
fields + their _SCALING_TARGETS mappings (-> caster_bonus_armor / caster_bonus_mr) + the AbilityContext
attributes already existed; this lift carries the two %-fields THROUGH the passive_damage registry -
PassiveDamageEntry + PerStackTerm gain bonus_armor_pct / bonus_mr_pct, and to_damage_block copies them
into the synthetic block so ability_dps._evaluate_block applies them with ZERO new evaluator math. SEEDED
2 entries from verbatim 16.11.1 effects_descriptions, both default-OFF byte-identical: Taric P Bravado
(25 : 93 based on level + 15% bonus armor) + Galio P Colossal Smash (15 : 115 based on level + 100% AD +
45% AP + 60% bonus MR; crit interaction omitted -> AA-crit seam). Both stay metadata-only / NOT on the
_AA_ROUTED_ON_HIT_KEYS allowlist (Taric post-spell-2-hit + Galio periodic gates, not every-AA). EXHAUSTED
172-champ sweep found ONLY these two clean linear cases; K'Sante P (bilinear caster-resist * target-HP,
All Out gated) + Rammus W (total-resist reflect) documented NOT-seeded. +18 characterization subtests.)

1.141.0 (B1 melee-applicability gate - DS Tier-2 cross-eval nomination B, default-OFF. dps.py /
hybrid.py carried NO attack-range gate, so Runaan's Hurricane's two extra bolts - a RANGED-basic-only
on-hit - were credited on melee autos (mis-valuing Runaan's on Briar / XinZhao / Nilah, who win on
bruiser items not the Runaan's / crit-AS template; evidence ops/audit/ds_cross_eval/TIER2_REPORT.md).
NEW PeriodicProc.ranged_only flag (set on Runaan's 3085 + Arena 223085 Wind's Fury) + CallContext.is_melee
(engine-derived in compute_dps from the champion record attackrange < new MELEE_RANGE_CEILING=350) +
apply_melee_aa_gate kwarg threaded compute_dps -> _phase_weighted_dps -> _rotation_attack_dps ->
_periodic_proc_dps, plus _per_attack_proc_damage (burst) and compute_hybrid. When the gate is ON and the
wielder is melee, a ranged_only proc contributes 0; default-OFF is byte-identical (the flag is never read,
is_melee is set but unused). Ranged champions are unaffected even with the seam on. +9 difference-of-
differences tests. Live rank.py / server.py flip stays validation-gated -> docs/LIVE_GAME_GATED_SYNC.md.
The B2 kit-agnostic AD-axis residual (Ezreal Muramana / TF caster-ADC) is a SEPARATE future slice.)

1.140.0 (DSP5/6/7 live-context CONSUMERS - the three DSP substrate seams shipped registries
(summoners.py 1.131.0 / enemy_runes.py 1.132.0 / the ally-grant overrides 1.133.0) but NO scorer
consumed them, so a flag-flip did nothing. NEW dsp_live_consumers.py adds the consumer layer: three
thin, pure, fail-soft functions a live surface (fight_report / matchup / coach / peel readout) calls
with the real live-client context. DSP5 summoner_fight_adjustments folds the player's + enemy's
summoner set (Heal/Barrier EHP, Cleanse tenacity, Ghost/Heal MS, self-Exhaust incoming-DR, enemy
Ignite antiheal). DSP6 enemy_rune_threat folds the enemy's rune set (Press the Attack incoming-amp ->
ehp_divisor 1+amp, Conqueror damage-ramp, Grasp+Second Wind poke-sustain, antiheal). DSP7
ally_protected_ehp folds an ally's enchanter flat-HP grant (DSP7) AND resist grant (the item-321
ally-resist producer surface: Orianna E / Braum W / Taric W) into compute_ehp via external_flat_hp /
external_resist_armor / external_resist_mr. Each is byte-identical to the pre-DSP engine on an EMPTY
context (no spells / no runes / no allies), so importing + wiring changes nothing until a live caller
supplies data. The live default-ON wire (feeding the real summoner/rune/ally set from the live client
+ eyeballing the adjusted readout) stays operator-gated -> docs/LIVE_GAME_GATED_SYNC.md (do-not-flip
-blind). +10 tests test_dsp_live_consumers.py (empty no-op + correct-direction per consumer + version
pin). DEFAULT-OFF, 2026-06-17.)

1.139.0 (RF6 tank-template survivability INJECT seam - extends the RF3 ehp/tank float to the
tabled winners the candidate pool DROPS. RF4 found RF3's float is a no-op for Rell: its sole tabled
winner Fimbulwinter 3121 is the non-purchasable mana-line transform of Winter's Approach
(gold.purchasable=False), so _filter_candidates excludes it from the pool and the RF3 float has
nothing to lift (RF4 verified in_pool=False). RF3's "the EHP scorer ALREADY pools these resist/HP
items" premise holds for KSante (Thornmail 3075 / Iceborn 6662 pooled+floated) but is FALSE for Rell.
DEFAULT-OFF, 2026-06-17. ROOT-CAUSE: purchasable=False is the gate (the marksman deny-set is
marksman-only; Rell is a tank). NEW inject_ids force-admit param on rank._filter_candidates - an id
in the set bypasses the only_ids whitelist + exclude_names deny + _is_purchasable gate (still respects
current / non-coachable / mode-legality / terminal / budget); None default -> byte-identical for every
pre-RF6 caller. rank_items_by_ehp passes inject_ids=surv_ids only when the RF3 seam is ON, so the
tabled set enters the pool before the existing float prefix lifts it; OFF the pool + sort are unchanged.
The RF2 hps only_ids|=surv_ids union could NOT surface a non-purchasable transform either - RF6's
force-admit clears the gate it could not (Rakan 3121 sibling gap logged FUTURE in ORCHESTRATION_PLAN).
Per-champ test test_survivability_item_credit_rf6.py (12): Rell Fimbulwinter injects+floats ON +
NOT-pooled OFF (injected not floated), KSante float unbroken, Malphite no-op, _filter_candidates
inject-unit + mode-legality + None byte-identical. Live default-ON flip EXCLUDED ->
docs/LIVE_GAME_GATED_SYNC.md.)

1.138.0 (RF3 tank-template survivability item-credit seam - the ehp/tank scorer
rank_items_by_ehp pools EVERY purchasable mode-legal terminal item and sorts PURELY by delta_ehp
(or ehp_per_1k_gold in efficiency mode), blind to win-rate. The WIN-correlated mid-tier resist/HP
items the player base wins ARAM on (KSante: Thornmail / Iceborn Gauntlet; Rell: Fimbulwinter - the
DSP10 ehp-lane buried winners) ARE in the pool and DO earn a positive EHP delta, but the maximal
raw-EHP stackers add more absolute EHP, so the win items sink below them. DEFAULT-OFF, 2026-06-17.
NEW agents/daemon_slayer/survivability_item_credit_tank.json table (KSante: Iceborn Gauntlet /
Thornmail; Rell: Fimbulwinter; built by ops/audit/ds_perm_swarm/build_survivability_item_credit_tank.py
from the DSP10 report's ehp lane) + a survivability_item_ids_tank() loader added to
survivability_credit.py (shared _parse_table, separate file + cache - the RF1 hybrid and RF2 enchanter
tables stay byte-unaffected). rank_items_by_ehp gains prefer_survivability_by_win (default False ->
byte-identical, new survivability_score field on EhpRankedItem stays 0.0): when ON and the champ is
tabled, the tabled ids are FLOATED above the max-EHP ordering by WIN-table MEMBERSHIP (model order
preserved within each tier via a (survivability_score,) + base_key sort prefix). ROOT-CAUSE distinction:
RF3 mirrors RF1's FLOAT (the EHP scorer already pools these items, like the bruiser scorer) - it does
NOT inject like RF2 (whose enchanter_only pool EXCLUDES them); and it is orthogonal to DSP6/DSP8, which
alter the ENEMY damage profile (every item's EHP magnitude shifts under the same context, the relative
SELF order is unchanged - the win items stay buried under any preset). Components (Giant's Belt /
Negatron Cloak) + boots (Plated Steelcaps) + Cluster A deliberately NOT tabled. The live default-ON flip
is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.)

1.137.0 (RF2 enchanter-template survivability item-credit seam - the hps/enchanter scorer
rank_items_by_hps defaults enchanter_only=True, restricting the candidate pool to the curated
enchanter-throughput registry (Echoes of Helia / Ardent Censer / Staff of Flowing Water / Locket /
Knight's Vow / Redemption). For an enchanter played front-to-back as a tank-support, the HP/tank
survivability items the player base wins ARAM on are EXCLUDED from the pool entirely (zero HPS
throughput, not in the registry), so the generic enchanter template tops the list and the
WIN-correlated tank items never appear (the DSP10 hps-lane buried winners). DEFAULT-OFF, 2026-06-17.
NEW agents/daemon_slayer/survivability_item_credit_enchanter.json table (Rakan: Guardian's Horn /
Warmog's Armor / Heartsteel / Fimbulwinter; built by
ops/audit/ds_perm_swarm/build_survivability_item_credit_enchanter.py from the DSP10 report's hps lane)
+ a survivability_item_ids_enchanter() loader added to survivability_credit.py (shared _parse_table,
separate cache). rank_items_by_hps gains prefer_survivability_by_win (default False -> byte-identical,
new survivability_score field on HpsRankedItem stays 0.0): when ON and the champ is tabled, the tabled
ids are INJECTED into the enchanter_only pool then floated above the generic template by WIN-table
MEMBERSHIP (model order preserved within each tier via a (survivability_score,) + base_key sort prefix).
ROOT-CAUSE distinction from RF1: the hybrid/bruiser scorer ALREADY pools survivability items and merely
buries them (RF1 only floats); the enchanter scorer EXCLUDES them via enchanter_only, so RF2 must INJECT
first. Mercury's Treads (boots) + Cluster A (Zilean/Seraphine, both AP buried winners on the hps lane)
deliberately NOT tabled. The live default-ON flip is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not
flip blind.)

1.136.0 (RF1 generic-bruiser-template survivability item-credit seam - the hybrid/bruiser scorer
rank_items_by_hybrid ranked a near-fixed generic AD-DPS template (Void Immolation / Blade of The
Ruined King / Trinity Force / Heartsteel / Essence Reaver / Runaan's Hurricane) for every bruiser
because its sort key hybrid_delta_pct = alpha*dps_pct + beta*ehp_pct is alpha-weighted toward damage
and the default mixed-damage target preset under-credits the pure resist/sustain axis, so the
WIN-correlated survivability items the player base wins ARAM on sank below it (the DSP10 consolidated
buried winners). DEFAULT-OFF, 2026-06-17. NEW agents/daemon_slayer/survivability_credit.py loader over a
WIN-anchored survivability_item_credit.json table (9 bruiser champs / 28 terminal items: Darius, Yasuo,
Urgot, JarvanIV, Gnar, Udyr, Tryndamere, RekSai, Briar - items Spirit Visage / Jak'Sho / Sterak's Gage /
Death's Dance / Black Cleaver / Force of Nature / Randuin's Omen / Thornmail / Titanic Hydra /
Fimbulwinter / Sundered Sky / Stridebreaker / Iceborn Gauntlet / Overlord's Bloodmail / Wit's End; built
by ops/audit/ds_perm_swarm/build_survivability_item_credit.py from the DSP10 buried-winner report
hybrid/bruiser lane). rank_items_by_hybrid gains prefer_survivability_by_win (default False ->
byte-identical, new survivability_score field stays 0.0): when ON and the champ is tabled, every tabled
survivability item is floated above the generic template (model order preserved within each tier via a
(survivability_score,) + base_key sort prefix). ROOT-CAUSE distinction from the DSP11 seam: DSP11 floats
DPS/burst kit-axis items GATED ON delta_dps > 0; survivability items add EHP not DPS so their hybrid
delta is ~0 and a delta gate would never surface them - RF1 floats by WIN-table MEMBERSHIP, the signal
the damage-biased sort is blind to. MasterYi is NOT tabled (his buried winners are pure DPS - a
DSP11/within-axis matter). Champs absent from the table are a no-op. Cluster A
(Zilean/Shaco/Kayle/Seraphine AP-in-ARAM) is a SEPARATE operator-gated decision, deliberately NOT
tabled. The live default-ON flip is EXCLUDED (docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.)

1.135.0 (DSP11 Cluster-B2 kit-axis item-credit seam - the dps/burst scorers ranked a near-fixed
generic AD template (BotRK / Kraken / Stormrazor / Trinity / Essence Reaver for carry; Sundered Sky /
IE / Trinity for assassin) for every AD carry/assassin because compute_dps / compute_burst_damage
model a generic rotation that cannot encode a kit's win-axis (Pyke R executes scale with lethality,
Nilah doubles crit, Ezreal Q + Manamune ramp), so the engine buried the items the player base WINS on
(the DSP10 consolidated buried winners). DEFAULT-OFF, 2026-06-17. NEW agents/daemon_slayer/
kit_axis_credit.py loader over a WIN-anchored kit_axis_item_credit.json table (7 champs / 21 terminal
items, built by ops/audit/ds_perm_swarm/build_kit_axis_item_credit.py from the DSP10 buried-winner
report + rewind_history.db). rank_items (dps) + rank_items_by_burst (burst) gain
prefer_kit_axis_by_win (default False -> byte-identical, new kit_axis_score field stays 0.0): when ON
and the champ is tabled, (1) the dps ranker un-strips the champ's kit-axis items from the
ranged-marksman off-class deny set so a caster-ADC's hard-excluded Trinity Force becomes a candidate,
and (2) both rankers float every positive-delta kit-axis item above the generic template (model order
preserved within each tier via a (kit_axis_score,) + base_key sort prefix). A non-positive-delta item
is a regression and is NOT floated. Champs absent from the table are a no-op. Cluster A
(Zilean/Shaco/Kayle/Seraphine AP-in-ARAM archetype divergence) is a SEPARATE operator-gated routing
decision, deliberately NOT in this table. The live default-ON flip is EXCLUDED
(docs/LIVE_GAME_GATED_SYNC.md) - do not flip blind.)

1.134.0 (DSP8 enemy-comp target-preset seam - generalizes the DSV3 assume_squishy_target binary
armor assumption into four named enemy-comp target presets, DEFAULT-OFF, 2026-06-17.
rank_items_by_burst gains target_preset (default None -> byte-identical): "squishy" / "bruiser" /
"tank" / "high_cc", each a representative (armor, MR) defensive profile substituted for an absent /
zero target so item valuation reflects the comp being burst - lethality / flat pen bites a tank's
armor (50 base + 13/lvl -> 180 @ L11), magic pen bites a high-CC enchanter's MR (35 base + 3.5/lvl
-> 70 @ L11). NEW agents/daemon_slayer/burst.py _TARGET_PRESETS table + _assumed_target_resists(
preset, level) -> (armor, MR) curve (base + per_level * (level - 1)) + _resolve_target_preset(
target_preset, assume_squishy_target). The squishy preset REUSES the DSV3 _SQUISHY_TARGET_BASE_ARMOR
/ _PER_LEVEL constants so target_preset="squishy" and assume_squishy_target=True agree on armor (22 +
4.5/lvl -> 67 @ L11); the preset adds the representative MR (30 base + 0.5/lvl) the binary seam
omitted. BACK-COMPAT: assume_squishy_target is UNCHANGED - it still substitutes ARMOR only (the MR
substitution requires an explicit target_preset), so the DSV3 ranking + its 7 tests stay byte-
identical; an explicit positive target_armor / target_mr always wins. preset profiles at L11:
squishy (67/35), bruiser (90/55), tank (180/110), high_cc (75/70) - tank tankiest + squishy
squishiest on both axes. The result's existing target_armor / target_mr fields carry the substituted
resists; a new note surfaces the active preset. compute_burst_damage is untouched (it takes explicit
resists). DEFAULT-OFF: no live scorer passes target_preset, so /rank-assassin + compute_burst are
byte-identical. The live default consumer flip (wire a burst / target-preset scorer to the live
enemy comp) is operator-gated in docs/LIVE_GAME_GATED_SYNC.md. +16 hermetic tests. ENGINE 1.133.0 ->
1.134.0.)

1.133.0 (DSP7 ally aura/enchanter seam - ally SHIELD/HEAL flat-HP EHP-grant, DEFAULT-OFF,
2026-06-17. The THIRD ally-grant survivability EHP mode and the SHIELD/HEAL bucket the item-289
ally-grant registry deliberately EXCLUDED ("ally shields/heals are ability_hps THROUGHPUT, not a
resist-denominator add nor a revive-numerator multiplier - a different axis"). Here the SAME
shield/heal HP is modeled on the SURVIVABILITY side as the flat EHP an enchanter CONFERS on a
PROTECTED ally - distinct from the granter-side ability_hps throughput (it is the ally analog of
base HP: a flat shield/heal rides the protected ally's armor/MR curve, so +H raw HP scales every
per-type EHP exactly like +H max HP). NEW separate registry _ALLY_FLAT_HP_GRANT_OVERRIDES in
_passive_ally_grant_overrides.py (kept apart from the item-289 _PASSIVE_ALLY_GRANT_OVERRIDES so its
4-clean-entry shape + exclusion test stay byte-identical) seeds 7 canonical enchanter grants -
Janna E / Lulu E / Karma E / Yuumi E / Seraphine W shields + Soraka W / Nami W heals - with the
verbatim per-rank BASE values from data/daemon_slayer/16.12.1/champion_abilities.json (the source
ability_hps.py reads; AP ratio omitted - the granter's AP is a live Phase-D input), amortized by
_ALLY_SHIELD_HEAL_PROB 0.5. New AllyGrantEntry.shield_hp/heal_hp fields (the 4 resist/revive entries
leave both 0.0). Public surface: ally_flat_hp_grant(champion_id, level, apply_ally_grant) fail-soft
-> 0.0. CONSUMER seam (GENERIC): compute_ehp gains external_flat_hp (default 0.0 -> byte-identical),
a raw add to every per-type EHP numerator + _blend_with_heal; new EhpResult.ally_grant_flat_hp
field + to_dict. DEFAULT-OFF: apply_ally_grant=False -> 0.0 AND no live caller passes
external_flat_hp, so /rank + compute_ehp + compute_dps + compute_burst are byte-identical. allyamp.py
(the OUTWARD scorer) is saturated for the shield/heal buckets under its one-mechanism-per-(champ,
source) schema, so it gains only a docstring cross-reference to this PROTECTED-ALLY seam (no
registry/score change). The live default-ON consumer flip (an EHP/peel-target consumer reading the
live ally's granter set) is operator-gated in docs/LIVE_GAME_GATED_SYNC.md. +24 hermetic tests.
ENGINE 1.132.0 -> 1.133.0.)

1.132.0 (DSP6 enemy-rune threat seam - NEW agents/daemon_slayer/enemy_runes.py, DEFAULT-OFF,
2026-06-17. Net-new additive substrate: RC modeled the player's OWN runes (rune_procs.py,
core/rune_wpa.py) but had ZERO model of the ENEMY's runes as a threat modulating the player's
EHP preset or the enemy's target preset. The enemy-side mirror of summoners.py - a self-contained
registry modeling 4 enemy runes on the preset each threatens: Press the Attack 8005 (incoming_amp:
the enemy's 8% damage-dealt amp lands as an 8% incoming amp on the player, an EHP-numerator divisor
1/1.08), Conqueror 8010 (damage_ramp: max-stack bonus Adaptive Force 21.6-48.0 by level = 12 *
1.8-4.0/stack, the legacy true-dmg-ramp lens; lifesteal 8% melee / 5% ranged carried for the
enemy-sustain target lens), Grasp of the Undying 8437 (poke_sustain: 1.3% max-HP heal + 3.5%
max-HP magic + 5 perm HP per proc, ranged 40% effective), Second Wind 8444 (poke_sustain: 4% of
missing HP over 10s). The 4th DSP6 bucket, ANTIHEAL, is NOT a rune (no rune grants Grievous
Wounds - it comes from items + Ignite, already in summoners.py id 14), so it is carried as a
non-rune constant GRIEVOUS_WOUNDS_PCT 0.40 + the enemy_antiheal_pct(present) flag helper and is
NOT in ENEMY_RUNE_SEAM_IDS. Every coefficient is verbatim from DDragon runesReforged.json 16.12.1
longDesc (authoritative; never aggregator D / aggregator A), cited per rune in the formula string.
DEFAULT-OFF: ENEMY_RUNE_SEAM_IDS marks the modeled ids but NO live scorer consumes them, so /rank +
compute_dps + compute_ehp + compute_burst are byte-identical to the pre-DSP6 engine. Public
surface: compute_enemy_rune_value + enemy_incoming_amp_pct / enemy_damage_ramp / enemy_poke_
sustain_pct / enemy_poke_sustain_hp / enemy_grasp_magic_proc / enemy_antiheal_pct, all fail-soft
(unknown id / empty / bad input -> 0.0). The live default-ON consumer flip (an EHP/target-preset
consumer reading the enemy's live rune set) is operator-gated in docs/LIVE_GAME_GATED_SYNC.md.
+29 hermetic tests. ENGINE 1.131.0 -> 1.132.0.)

1.131.0 (DSP5 summoner-spell seam - NEW agents/daemon_slayer/summoners.py, DEFAULT-OFF,
2026-06-17. Net-new additive substrate: RC had ZERO summoner-spell layer. A self-contained
registry in the rune_procs.RUNE_PROCS style modeling the 6 combat summoner spells on their
scoring axis - Ignite 14 (antiheal_true: 70-525 true DoT by level + 40% Grievous Wounds),
Exhaust 3 (incoming_dr: 35% damage-dealt cut on the exhausted enemy), Heal 7 (ehp_heal: 80-346
flat heal by level + 30% MS), Barrier 21 (ehp_shield: 100-502.35 flat shield by level), Cleanse
1 (cc_discount: 75% tenacity; the QSS item analog feeds the same lane), Ghost 6 (move_speed:
24-50.82% MS by level). DDragon + CDragon 16.12.1 ZERO summoner magnitudes (prose-only
descriptions, like stripped item passive formulas), so every coefficient is the LoL wiki value
(reference_lol_wiki_access, fetched 2026-06-17), cited verbatim per spell in the formula string;
the wiki reflects the live patch which post-dates 16.12.1, so the live default-ON flip re-anchors
to the then-current patch. DEFAULT-OFF: SUMMONER_SEAM_IDS marks the modeled ids but NO live
scorer consumes them, so /rank + compute_dps + compute_ehp are byte-identical to the pre-DSP5
engine. Public surface: compute_summoner_value + summoner_antiheal_pct / summoner_incoming_dr_pct
/ summoner_cc_discount_pct + compute_summoner_ms_pct + compute_summoner_ehp_bonus, all fail-soft
(unknown id -> 0.0). The live default-ON consumer flip (fight_report / matchup / coach) is
operator-gated in docs/LIVE_GAME_GATED_SYNC.md. +24 hermetic tests. ENGINE 1.130.0 -> 1.131.0.)

1.130.0 (DSP4 self-rune completion seam - DEFAULT-OFF, 2026-06-17. Completes the self-rune
combat-proc coverage in agents/daemon_slayer/rune_procs.py by adding the ONE remaining LIVE,
pickable rune that deals direct champion proc damage and was unmodeled: Shield Bash 8401
(Resolve). DDragon 16.12.1 runesReforged.json longDesc verbatim: "your next basic attack
against a champion deals 5 - 30 (+2.5% Bonus Health) (+15.0% New Shield Amount) bonus adaptive
damage" on gaining a shield. "adaptive" is the damage TYPE not a stat coefficient (scales on
bonus health + shield amount, NO AD/AP), so compute = 5-30 by level + 0.025*bonus_hp +
0.15*shield_amount (proc_type on_proc_burst, condition shield_gated, cooldown_s 0.0 - gated by
shield-gain events). The registry grows 19 -> 20. DEFAULT-OFF seam: Shield Bash joins the new
COMPLETION_RUNE_IDS frozenset; compute_burst_damage + compute_combo gain score_completion_runes
(default False) and SKIP completion runes unless ON, so every existing rune set stays
byte-identical to the pre-DSP4 engine (do-not-flip-blind; the live default-ON flip is
operator-gated in docs/LIVE_GAME_GATED_SYNC.md section B + the ledger). The burst scorer has no
live shield signal so it scores the shield-independent 5-30 + 2.5% bonus-HP floor (best-case-
shielded approximation); shield_amount is forward-compat for a live caster-stat producer. The
42 other unmodeled catalog runes are honest exclusions: stat-grants (Waterwalking 8232, Jack
Of All Trades 8316), ult-only amp (Axiom Arcanist 8224), legacy/non-pickable (Deathfire Touch
8992), and non-damage (move-speed / mana / heal / shield / armor / tenacity / gold / wards).
core/rune_wpa.py cross-links the empirical WPA lens with the mechanical proc model: each WPA
row now carries proc_modeled (fail-soft import of RUNE_PROCS keys, additive field). TDD: 27
new subtests (Shield Bash math + COMPLETION_RUNE_IDS + burst/combo default-OFF byte-identical +
ON contributes + proc_modeled annotation); 2 registry-shape pins updated 19 -> 20. Sources:
Riot Data Dragon 16.12.1.)

1.129.0 (DSP2 Cluster-B off-class WIN-exemption seam - DEFAULT-OFF, 2026-06-17. The DS
permutation swarm DSP1 WIN-anchor (ops/audit/ds_perm_swarm) found Ezreal SR -39 the single
worst outcome-divergent champ-mode: the item-213 ranged-marksman off-class deny-set
(rank.OFFCLASS_MARKSMAN_ITEM_NAMES) hard-strips Sheen-line / on-hit items from EVERY ranged
marksman, but Trinity Force is Ezreal's most-built item (rewind ARAM n=219) and Spear of Shojin
+ Black Cleaver are real Ezreal/Corki/Smolder/Senna builds. There is no kit-data axis for
"wants Sheen" (lolmath.damage_distribution is AD/AP only), so the exemption is WIN+usage
anchored: ops/audit/ds_perm_swarm/build_marksman_offclass_exempt.py distills the cross-eval
empirical block (rewind WIN data) into agents/daemon_slayer/marksman_offclass_exempt.json
(an off-class item is exempted for a champ at n>=30 AND wr>=mode_baseline-3). NEW DEFAULT-OFF
seam rank_items(exempt_offclass_by_win=True): when ON + the champ is a ranged marksman, the
exempt items are subtracted from the deny-set so they re-enter the candidate pool. Byte-identical
when off (the DSV1-4 precedent); pure crit ADCs (Caitlyn/Jinx/Sivir - absent from the table) are
untouched ON or OFF. The live default-ON flip is EXCLUDED -> docs/LIVE_GAME_GATED_SYNC.md.
4 caster-marksmen exempted (Corki/Ezreal/Senna/Smolder). +12 hermetic tests
(test_rank_offclass_win_exempt.py). DS :8893 bounced -> 1.129.0.)

1.128.0 (Aphelios dps zero-output fix - degenerate basic=0 scenario fallback, 2026-06-16.
Found in the comprehensive per-champion DS scorer cross-eval (ops/audit/ds_cross_eval/
SYSTEMIC_FINDINGS.md Cluster C). compute_dps reads settings.scenario.{early,mid,late}
rotations and scores ONLY the basic-attack portion; the upstream lolmath scenario for
Aphelios (weapon-swap kit) encodes basic=0 in every rotation, so weighted_dps collapsed to
0.0 - every item delta became 0 and the carry ranker degenerated to an all-Doran's, all-zero
ranking (the coach surfaced useless recommendations). FIX: when ALL phases have zero
basic-attack DPS AND mode_mult>0 AND raw_attack_dps>0, fall back weighted_dps =
raw_attack_dps*mode_mult (AD*AS*crit*mode, fully item-responsive) + an auditable note. The
mode_mult>0 gate preserves the ARAM-disabled contract (aramDamageDealt=0 -> mode_mult=0 ->
weighted stays 0, e.g. Yunara pre-16.11.1). Byte-identical for every champion with real
basic-attack rotations. +4 regression tests (test_dps_aphelios_degenerate_scenario.py).
DS :8893 bounced -> 1.128.0.)

1.127.0 (DSV4 - Spear of Shojin Focused Will ability-amp valuation, 2026-06-16. P6-G5
residual / G2-residual bucket-B. The ability scorers had NO seam for Spear of Shojin
3161 Focused Will, a stacking ability/passive damage amp (Meraki 16.12.1: 3% per stack,
max 4 stacks = 12%); the item carried defensive_only=True with the note "ability damage
not DPS-modeled", so an ability-reliant build that bought Shojin saw zero damage value
from it - only its raw AD/AH stats. Focused Will amps ABILITIES and PASSIVES only, never
basic attacks (the generic damage_amp_pct was deliberately left off Shojin since it would
amp AAs too). FIX: NEW ItemEffect.ability_damage_amp_per_stack / ability_damage_amp_max_stacks
(0.0 / 0 default = byte-identical) + effects.total_ability_damage_amp helper +
dps._ASSUMED_ABILITY_AMP_STACKS=4 (a developed fight at max stacks). A default-OFF
assume_ability_amp seam on compute_ability_dps (multiplies the spell ability sum; the item
DoT procs are NOT amped - conservative), compute_burst_damage (multiplies ONLY ability_total,
never aa_total), and rank_items_by_burst (threads into both compute_burst_damage call sites).
Data: Shojin 3161 + Arena 223161 pinned to 0.03 / 4. Ships DEFAULT-OFF (byte-identical when
off); the live rank scorers do NOT pass assume_ability_amp=True yet - the flip is a separate
real-game-validation-gated step (DS Phase-D class). +14 Meraki-anchored tests. DS :8893
bounced -> 1.127.0.)

1.126.0 (DSV3 - lethality-vs-sustained-AD burst-ranker valuation, 2026-06-16. P6-G5
residual 3. rank_items_by_burst defaulted target_armor=0.0; against zero armor
effective_target_armor floors its penetration tail at zero, so lethality (flat armor
pen, Riot V14.1 1:1) contributed NOTHING to a ranked item's delta and an equal-cost
raw-AD item out-ranked a lethality item - the exact lethality-vs-sustained tradeoff a
burst assassin's squishy target inverts. Adds a DEFAULT-OFF assume_squishy_target seam,
byte-identical when off: burst.py gains _assumed_squishy_target_armor(level) (a
representative squishy-carry curve, 22 base + 4.5 per level above 1 -> 67 at level 11)
and rank_items_by_burst gains assume_squishy_target. When True AND the caller did not
pin a positive target_armor, the ranker substitutes the assumed squishy armor for BOTH
the baseline and every candidate compute_burst_damage call, so lethality flows through
effective_target_armor and out-values raw AD; an explicit target_armor>0 is respected
(the seam only fills a zero/absent target). The lethality math itself is unchanged
(effects.effective_target_armor, ENGINE 1.5.1 V14.1 1:1) - only the ranker's target
assumption is refined. The seam ships DEFAULT-OFF; the live rank scorers do not pass
assume_squishy_target=True yet (a validation-gated flip). DS :8893 bounced -> 1.126.0.
Sources: Riot Data Dragon / CommunityDragon / Meraki Analytics.)

1.125.0 (DSV2 - takedown / kill-state item-passive valuation, 2026-06-15. P6-G5
residual 2. The burst + auto scorers had no seam for the on-takedown item passives, so
Hubris (Eminence bonus AD) + The Collector (5% execute) were under-ranked among lethality
items. Adds a DEFAULT-OFF kill-state OFFENSE seam, byte-identical when off: ItemEffect
gains takedown_bonus_ad_base / takedown_bonus_ad_per_stack (Hubris Eminence "15 (+2 per
stack)" bonus AD on takedown, Meraki 16.12.1) + execute_max_hp_pct (The Collector Death
execute below 5% target max HP), all default 0.0. effects.py gains total_takedown_bonus_ad
+ total_execute_max_hp_pct. dps.py gains _ASSUMED_TAKEDOWN_STACKS=1 + an assume_takedown
kwarg on compute_dps (folds Hubris bonus AD 15 + 2*1 = 17 into the rotation AD + bonus_ad
ctx; the Collector execute is NOT credited - a one-shot finisher is not sustained DPS).
burst.py gains assume_takedown on compute_burst_damage + rank_items_by_burst (threads into
the AA probe + the ability ctx so Hubris raises BOTH ability and AA, and credits the
Collector execute as a 5% target-max-HP TRUE finisher execute_finisher_damage folded into
total_burst_damage). Death's Dance carries NEITHER offense field: its takedown payoff is
the Defy heal, already valued on the survivability axis (ehp.py takedown_gated, ENGINE
1.57.0) - crediting offense would double-count phantom damage. Data: Hubris 6697 / 226697 /
126697 + The Collector 6676 / 667666 / 226676 wired. The seam ships DEFAULT-OFF; the live
rank scorers do not pass assume_takedown=True yet (a validation-gated flip). DS :8893
bounced -> 1.125.0. Sources: Riot Data Dragon / CommunityDragon / Meraki Analytics.)

1.124.0 (DSV1 - AP damage-over-time burn valuation, 2026-06-15. P6-G5 residual 1.
compute_ability_dps (the AP / ability scorer) mirrored compute_dps's item amp + pen
handling but never folded item PERIODIC procs, so ability-triggered AP burn DoTs were
invisible to the mage item ranking even though the auto scorer has valued them since
Phase 4 - P6-G5's "AP DoT burn vs single-rotation ability model" gap. Completed the
mirror: PeriodicProc gains an ability_dot flag (default False = byte-identical);
_periodic_proc_dps gains ability_dot_only (default False = compute_dps byte-identical);
compute_ability_dps folds _periodic_proc_dps(ability_dot_only=True) into
total_ability_dps. Data: ADDED Liandry's Torment burn (6653 + Arena 226653) - 2% target
max HP/s magic (16.12.1 Meraki 6% over 3s, the Azakana's Gaze sibling); FIXED Blackfire
Baleful Blaze (2503 + Arena 222503) to the Meraki total 60 (+6% AP) over 3s / 6 ticks =
10 (+1% AP) per 0.5s tick (the prior 6+6%/tick mis-read the wiki {{ap|60/6}} tick-count
as a melee/ranged split); TAGGED Demonic Azakana (4637 + Arena 224637) ability_dot for
sibling completeness. Only the 3 named/sibling burn families lift - tank Immolate auras,
physical spellblades, and on-cast nukes (all every_n_seconds procs too) stay out of the
AP scorer via the curated ability_dot tag. Live: Veigar L11 SR mage ranking now Liandry
#1 at target_max_hp=2500 (was buried ~#23), Blackfire #1 at tmh=0; no pollution. DS :8893
bounced -> 1.124.0. Sources: Riot Data Dragon / CommunityDragon / Meraki Analytics.)

1.123.0 (P6 lolmath build-engine parity G4, 2026-06-15 - boots-pool refresh to the
16.12.1 tier-3 boots. DDragon 16.12.1 added Summoner's-Rift-only tier-3 upgraded boots
(Spellslinger's Shoes / Gunmetal Greaves / Armored Advance / Chainlaced Crushers /
Crimson Lucidity / Swiftmarch / Immortal Path) and pulled Mobility Boots + Symbiotic Soles
from the store; the DS build planner still emitted only legacy tier-2 boots (Mercury's
Treads / Berserker's Greaves), diverging from the lolmath oracle. core/build_order now
upgrades the selected tier-2 family to its tier-3 form on SR (map 11) via _BOOTS_SR_UPGRADE
- ARAM (map 12) and Arena (map 30) have NO tier-3 form and keep tier-2 - and the assassin
default moves off the out-of-store Mobility Boots to Ionian -> Crimson Lucidity. No engine
MATH change: the ranker is byte-identical and never imports core/build_order; this re-selects
the synthetic boots slot, so all build_orders tables (flat + HZ-B1 + HZ-B2 variants,
sr / aram / arena) were regenerated. DS :8893 bounced -> 1.123.0. Deferred: Arena should use
the 22xxxx boots mirror (3xxx are map30=False) - logged for a follow-up slice.)

1.122.0 (P6 lolmath build-engine parity G1, 2026-06-15 - kit-damage-axis archetype
correction. DDragon class tags encode ROLE, not the AD-vs-AP axis a kit scales on, so
core/archetype_picks resolved AP-scaling kits to an AD scorer (Fighter -> bruiser on Gwen
0.70 magical; Marksman -> carry on Teemo 0.81 magical) and an AD assassin to the AP
enchanter scorer (Pyke 0.76 physical) - the build engine then built the WRONG damage axis.
The DEFAULT archetype is now re-based against champions.json lolmath.damage_distribution
(the ground-truth axis), below any operator pick. 18 default-source champions re-base
(11 named by the lolmath-vs-DS sweep + 7 AP assassins it missed - Akali / Ekko / Evelynn /
Fizz / Kassadin / Katarina / Leblanc - plus Pyke AP->AD). Tank kits (axis-neutral) and the
lolmath-only quirks where the kit axis already agrees with DS (XinZhao AD, Taric AP) are
deliberately NOT flipped. No engine MATH change: the scorer code is byte-identical; this
re-selects WHICH scorer a tag default reads, so all build_orders tables (flat + HZ-B1 +
HZ-B2 variants, sr / aram / arena) were regenerated. DS :8893 bounced -> 1.122.0.)

1.121.0 (item 414, 2026-06-14 - SUSTAIN contract-gap closure. Closes the
test_wireable_sims_p1l3 strict-xfail: lifesteal/spellvamp/omnivamp resolve as wireable
stats but had no explicitly-named effective-EHP sustain output. The EHP scorer already
folds the lifesteal heal pool into blended_ehp (ENGINE 1.28.0); this slice NAMES the
sustain-inclusive quantity via a SIBLING layer (the cc_blended_ehp pattern - blended_ehp /
physical_ehp / magical_ehp / true_ehp stay byte-identical) and consumes the previously-
unconsumed spellvamp / omnivamp stats. New EhpResult fields: effective_ehp_with_sustain
(blended EHP incl the full vamp pool), ehp_without_sustain (vamp heal stripped = raw EHP),
sustain_ehp_delta, heal_spellvamp / heal_omnivamp, + a "sustain" to_dict block + a
format_table row. The vamp heals reuse the lifesteal AA-throughput proxy (_vamp_heal_pool
generalises _lifesteal_heal); spellvamp / omnivamp resolve to 0 on every current build (no
SR item grants them - VampStatResolutionEdge), so effective_ehp_with_sustain == blended_ehp
today and diverges only when such an item lands. Additive / byte-identical at default; DS
:8893 bounced -> 1.121.0.)

1.120.0 (item 321, 2026-06-06 - survivability seam default-ON cutover. compute_ehp's
``apply_egg_resist`` flag (item 316, Anivia Rebirth EGG-STATE resist seam) flips
default False -> True: the death-triggered self-revive EXTRA now reshapes per damage
type through the resurrection egg's MODIFIED resists (-40 at L1 ramping to +20 at L18)
by default. Pass ``apply_egg_resist=False`` to recover the prior item-288 scalar path.
Blast radius is nil for live scoring - no scorer passes ``apply_passive_revive=True``
today, and the egg deltas are 0.0 for every non-Anivia / non-revive champ (ratio 1.0,
byte-identical). The COMPANION Orianna E ally-resist seam (item 316 regression lock of
item-289 ``ally_resist_grant`` -> ``external_resist_armor/mr``) needs NO default flip:
it is consumer-driven (the granter value is supplied explicitly by the caller and the
``/ehp`` server route already accepts it), so it is already active wherever a caller
wires it. Wiring both seams into a live survivability scorer + per-champion validation
is logged FUTURE. No DS restart-coupled balance change; one seam test re-pointed to the
new default. DS :8893 must be bounced -> 1.120.0.)

1.119.0 (prefer_cdragon_ratios default-ON cutover - the ability damage RATIOS are
now re-sourced from the LIVE CommunityDragon 16.11 character bins in preference to
the frozen Meraki champion_abilities.json dump. The item-319 semantic block-matcher
(_apply_cdragon_ratio_preference: stat-FAMILY-signature bijection with whole-form
Meraki fall-back on any ambiguous multi-block structure) made the flip structurally
safe - flip-ON failures fell from 70 (item 311, positional zip) to 0 structural.
NEW resolver float-snap (tools/daemon_slayer_cdragon_ratio_extract._snap, round-4):
CDragon bins store ratios as float32 so a clean authored 0.55 arrived as
0.550000011920929 -> 55.000001, mis-comparing byte-for-byte against Meraki 55.0; the
snap collapses float32 noise while preserving every genuine authored ratio. Sidecar
regenerated live: 171 champs / 838 mechanical / 577 fallback / 0 errors. GENUINE
balance re-pins validated per-champion vs wiki + live bin: Lux Q 65 -> 75% AP, Ezreal
Q 15 -> 40% AP (both Meraki-stale, CDragon authoritative); Veigar Q float-noise only
(snaps back to Meraki 50/55/60/65/70). Seam tests re-pointed for the new default
(explicit prefer_cdragon_ratios=False is the legacy Meraki-only path). DS :8893
restarted -> 1.119.0; RC NOT restarted - DS engine + sidecar + tests + Share + docs.)

1.118.0 (Extended-dueling / 1v1 sustained-fight scorer - item 309, the SEVENTEENTH
scored axis, built by a 10-channel roster fan-out + 10 completeness critics. NEW
agents/daemon_slayer/extendedduel.py: a per-(champion, source, kind) duel-mechanism
registry plus a kind -> weight table (_EXTENDEDDUEL_KIND_WEIGHT: RAMP 1.0 / RESET 0.85 /
DUELHEAL 0.75 / ENDURE 0.6) and a cadence -> mult table (_EXTENDEDDUEL_CADENCE_MULT:
SUSTAINED 1.0 / PERIODIC 0.8 / BURST 0.65). compute_extendedduel folds every mechanism into a
single duel_score = sum(kind_weight * cadence_mult * magnitude), gated mechanisms credited at
the 0.5 conditional midpoint; top_kind labels the strongest duel tool and ramps flags any RAMP
mechanism (the champion gets STRONGER the longer the fight runs - do not commit to a long 1v1
against her). It scores how well a champion's OWN KIT wins a PROLONGED 1v1 duel past the burst
window - the RAMP / RESET / DUELHEAL / ENDURE attrition tools it brings - the extended-duel
dimension the prior sixteen axes never measured (the burst scorer measures front-loaded damage
and the DPS scorer measures raw output against a fixed dummy; neither answers whether the kit
WINS the long duel). SELECTIVE but broad axis (most fighters / skirmishers carry an attrition
tool): 283 entries / 111 champions / 81 conditional / 63 ramping; kinds RAMP 81 / ENDURE 76 /
DUELHEAL 75 / RESET 51; cadence SUSTAINED 97 / PERIODIC 95 / BURST 91. NEW POST+GET
/extended-duel route (additive - every existing route byte-identical). Live tank-melters by
duel power: MasterYi 2.74 / Tryndamere 2.38 / Jax 2.12 / Aatrox 2.11 / Yone 1.66 / Fiora 1.65
/ Nasus 1.60 / Renekton 1.57 / Warwick 1.55 / Vladimir 1.52 vs LeBlanc / Veigar / Lux / Xerath
/ Janna / Ziggs / Zoe / Sona / Milio 0.0 (burst / artillery / utility floor). + reusable
tools/ds_extendedduel_build.py validate/inject generator + extendedduel_registry_notes.json
provenance sidecar (Share-excluded). Purely additive: reads no existing scorer, read by none.)

1.117.0 (Anti-tank / %HP-damage + resist-shred scorer - item 308, the SIXTEENTH
scored axis, built by an 8-channel roster fan-out + 4 completeness critics. NEW
agents/daemon_slayer/antitank.py: a per-(champion, source, kind) anti-tank-mechanism
registry plus a kind -> weight table (_ANTITANK_KIND_WEIGHT: MAX_HP 1.0 / SHRED 0.85 /
CURRENT_HP 0.75 / PERCENT_PEN 0.65) and a cadence -> mult table (_ANTITANK_CADENCE_MULT:
SUSTAINED 1.0 / PERIODIC 0.8 / BURST 0.65). compute_antitank folds every mechanism into a
single antitank_score = sum(kind_weight * cadence_mult * magnitude), gated mechanisms
credited at the 0.5 conditional midpoint; top_kind labels the strongest anti-tank tool and
shreds_resist flags any SHRED or PERCENT_PEN mechanism (the champion lowers the tank's
resists for the whole team, not just herself). It scores how well a champion's OWN KIT melts
a high-HP / high-resist target - the %max-HP / %current-HP damage and the armor/MR shred /
%pen it brings - the anti-tank dimension the prior fifteen axes never measured (the DPS /
burst scorers measure raw damage against a fixed dummy; none asks whether the kit cares how
much health and armor the enemy stacked). Every kind gets stronger the tankier the target;
pure %-missing-health executes are EXCLUDED as finishers (they do nothing to a full tank). A
single ability may carry two kinds (Trundle R = %max-HP drain + resist steal; Vi W / Yorick
E / Sion E = %max-HP + armor shred), so a champion may hold two rows on one slot. NEW
/anti-tank route (POST+GET). Purely ADDITIVE - reads no existing scorer and is read by none,
so every existing route is byte-identical. SELECTIVE (only champions whose damage scales
with enemy health or resists appear; a flat-damage champion scores 0.0), the sustain /
zone-control / ally-amplification shape. 171-champion fan-out (8 classify + 4 completeness
critics) -> 102 entries / 78 champs / 38 conditional / kinds MAX_HP 63 SHRED 25 CURRENT_HP 9
PERCENT_PEN 5 / cadence SUSTAINED 40 PERIODIC 46 BURST 16. Live: Rumble 1.42 (top) / K'Sante
1.24 / Sion 1.21 / Rell 1.14 / Vi 1.11 / Mordekaiser 1.02 / Trundle 0.99 / Vayne 0.95 /
Kog'Maw 0.93 (top tank-melters) vs MasterYi / Annie / Talon / Katarina / Lux / Soraka 0.0
(flat-damage floor); 29 shreds_resist champs, 5 kit-intrinsic PERCENT_PEN. +
tools/ds_antitank_build.py (marker-splice generator) + antitank_registry_notes.json
provenance sidecar (Share-excluded). Phase D - an auto-pairing consumer crediting anti-tank
into a live draft / teamfight / itemization verdict - remains. The anti-tank / %HP-damage
axis is EXHAUSTED across the roster.)

1.116.0 (Ally-amplification / buff-throughput scorer - item 304, the FIFTEENTH
scored axis, built by a 10-channel roster fan-out. NEW agents/daemon_slayer/allyamp.py:
a per-(champion, source) ally-buff-mechanism registry plus a kind -> weight table
(_ALLYAMP_KIND_WEIGHT: PROTECT 1.0 / SHIELD 0.85 / HEAL 0.75 / STEROID 0.6 /
HASTE 0.45) and a scope -> mult table (_ALLYAMP_SCOPE_MULT: TEAM 1.0 / DUO 0.8 /
SINGLE 0.65). compute_allyamp folds every mechanism into a single allyamp_score =
sum(kind_weight * scope_mult * magnitude), gated mechanisms credited at the 0.5
conditional midpoint; top_kind labels the strongest ally-buff and saves_ally flags
any PROTECT mechanism (a hard save - invuln / revive / untargetable / damage-immune
placed on an ally). It scores how much COMBAT VALUE a champion grants to her ALLIES -
the shields, heals, steroids, hard-saves, and haste she pumps OUTWARD into her team -
the buff-throughput dimension the prior fourteen axes never measured (every prior axis
scores what a champion does to an enemy, to a piece of ground, or to her OWN body; this
is the mirror of the self-sustain axis pointed at teammates). NEW /ally-amp route
(POST+GET). Purely ADDITIVE - reads no existing scorer and is read by none, so every
existing route is byte-identical. Deliberately SPARSE (only champions who grant value
to allies appear; a selfish carry / assassin scores 0.0), the sustain / zone-control
shape. 171-champion ten-channel fan-out (10 classify + 10 completeness critics) -> 74
entries / 43 champs / 30 conditional / kinds SHIELD 19 HEAL 18 HASTE 15 STEROID 14
PROTECT 8 / scope TEAM 37 SINGLE 31 DUO 6. Live: Taric 1.20 (top, PROTECT invuln) /
Milio 1.14 / Nami 0.82 / Janna 0.82 / Senna 0.81 / Lulu 0.71 (top ally-buffers) vs
MasterYi / Zed / Vayne / Darius 0.0 (selfish floor); the 8 saves_ally champs = Taric /
Kayle / Zilean / Kindred / TahmKench / Shen / Bard / Akshan. + tools/ds_allyamp_build.py
(marker-splice generator) + allyamp_registry_notes.json provenance sidecar
(Share-excluded). Phase D - an auto-pairing consumer crediting ally amplification into a
live teamfight / draft / peel-target verdict - remains. The ally-amplification /
buff-throughput axis is EXHAUSTED across the roster.)

1.115.0 (Objective / structure-damage scorer - item 303, the FOURTEENTH scored
axis, built by a 10-channel roster fan-out. NEW agents/daemon_slayer/objdamage.py:
a per-(champion, source) objective-mechanism registry plus a kind -> weight table
(_OBJDAMAGE_KIND_WEIGHT: STRUCTURE_BONUS 1.0 / MONSTER_BONUS 0.9 / SUSTAINED_DPS
0.7 / SUMMON_DPS 0.55 / BURST_SECURE 0.45) and a scope -> mult table
(_OBJDAMAGE_SCOPE_MULT: BOTH 1.0 / MONSTER 0.85 / STRUCTURE 0.85). compute_objdamage
folds every mechanism into a single objdamage_score = sum(kind_weight * scope_mult
* magnitude), gated mechanisms credited at the 0.5 conditional midpoint; top_kind
labels the strongest objective tool and pressures_structures flags any mechanism
that hits towers (scope BOTH or STRUCTURE). It scores how much pressure a champion
puts on the map's OBJECTIVES - turrets / structures and epic monsters (drake /
baron / herald / grubs) - the macro / siege dimension the prior thirteen axes never
measured (they score combat against a champion or a piece of ground; this scores
throughput against the objects that win the game). NEW /objective-damage route
(POST+GET). Purely ADDITIVE - reads no existing scorer and is read by none, so every
existing route is byte-identical. It scores the FULL roster (every champion carries
at least one row), the threat-range / wave-clear shape. 171-champion ten-channel
fan-out (10 classify + 10 completeness critics) -> 285 entries / 171 champs / 66
conditional / kinds SUSTAINED_DPS 219 BURST_SECURE 28 SUMMON_DPS 18 MONSTER_BONUS 16
STRUCTURE_BONUS 4 / scope BOTH 258 MONSTER 21 STRUCTURE 6. Live: KogMaw 1.27 /
Belveth 1.21 / Kindred 1.15 / Volibear 1.15 / Vayne 1.09 (top objective threats) vs
Soraka / Yuumi / Janna / Braum 0.11 (enchanter floor - general AA DPS only); Ziggs
top_kind STRUCTURE_BONUS (Short Fuse tower bonus). + tools/ds_objdamage_build.py
(marker-splice generator) + objdamage_registry_notes.json provenance sidecar
(Share-excluded). Phase D - an auto-pairing consumer crediting objective damage into
a live macro / split-push / objective-setup verdict - remains. The objective /
structure-damage axis is EXHAUSTED across the roster.)

1.114.0 (Zone-control / area-denial scorer - item 302, the THIRTEENTH scored
axis, built by a 10-channel roster fan-out. NEW agents/daemon_slayer/zonecontrol.py:
a per-(champion, source) area-denial-mechanism registry plus a kind -> weight
table (_ZONECONTROL_KIND_WEIGHT: TERRAIN 1.0 / FIELD 0.85 / TRAP 0.7 / SUMMON 0.6
/ DISPLACE 0.45) and a persistence -> mult table (_ZONECONTROL_PERSISTENCE_MULT:
SUSTAINED 1.0 / TIMED 0.8 / BRIEF 0.55). compute_zonecontrol folds every mechanism
into a single zonecontrol_score = sum(kind_weight * persistence_mult * magnitude),
gated mechanisms credited at the 0.5 conditional midpoint; top_kind labels the
strongest area-control and controls_terrain flags any TERRAIN mechanism. It scores
how much a champion can make a piece of GROUND dangerous, impassable, or contested
for a duration - the spatial area-denial dimension the prior twelve axes never
measured (they score what a champion does to a target; this scores how it denies
and reshapes space). NEW /zone-control route (POST+GET). Purely ADDITIVE - reads
no existing scorer and is read by none, so every existing route is byte-identical.
The axis is deliberately SPARSE (only champions with real area-denial appear),
unlike the full-roster threat-range / wave-clear axes. 171-champion ten-channel
fan-out (10 classify + 10 completeness critics; the critics pruned 25 spurious
single-target-CC entries) -> 98 entries / 83 champs / 45 conditional / kinds
TERRAIN 11 FIELD 55 SUMMON 12 TRAP 10 DISPLACE 10 / persistence TIMED 59 SUSTAINED
26 BRIEF 13. Live: Anivia 1.32 / Illaoi 0.96 / Viktor 0.95 / Karthus 0.86 /
Taliyah 0.80 (top zoners) vs MasterYi / Zed / Talon / Tryndamere 0.0 (no
area-denial - the correct sparse answer). + tools/ds_zonecontrol_build.py
(marker-splice generator) + zonecontrol_registry_notes.json provenance sidecar
(Share-excluded). Phase D - an auto-pairing consumer crediting zone-control into a
live teamfight / objective / draft-zoning verdict - remains. The zone-control /
area-denial axis is EXHAUSTED across the roster.)

1.113.0 (Effective threat-range scorer - item 301, the TWELFTH scored axis,
built by a 10-channel roster fan-out. NEW agents/daemon_slayer/threatrange.py: a
per-(champion, source) threatening-mechanism registry plus a band -> weight table
(_THREATRANGE_BAND_WEIGHT: GLOBAL 1.1 / ARTILLERY 1.0 / LONG 0.75 / MEDIUM 0.5 /
SHORT 0.3 / MELEE 0.15) and a kind -> mult table (_THREATRANGE_KIND_MULT: BURST
1.0 / CC 1.0 / SUSTAINED 0.9 / POKE 0.7). compute_threatrange folds every
mechanism into a single threatrange_score = sum(band_weight * kind_mult *
magnitude), gated mechanisms credited at the 0.5 conditional midpoint; top_band
labels the longest real threat and is_artillery flags any ARTILLERY/GLOBAL reach.
It scores how FAR OUT a champion threatens damage or CC - the poke / siege /
safe-DPS-distance dimension the prior eleven axes never measured (they score what
a champion does in a fight; this scores from how far away it can do it). NEW
/threat-range route (POST+GET). Purely ADDITIVE - reads no existing scorer and is
read by none, so every existing route is byte-identical. EXHAUSTIVE 171-champion
ten-channel fan-out -> 725 entries / 171 champs (full roster) / 185 conditional /
bands ARTILLERY 71 GLOBAL 33 LONG 191 MEDIUM 159 SHORT 133 MELEE 138 / kinds CC
261 BURST 191 SUSTAINED 183 POKE 90. Live: Xerath 2.28 / Caitlyn 1.94 / Lux 1.84
/ Ziggs 1.81 / Velkoz 1.71 (top artillery) vs Garen 0.33 / Udyr 0.51 / MasterYi
0.60 (melee-only). + tools/ds_threatrange_build.py (marker-splice generator) +
threatrange_registry_notes.json provenance sidecar (Share-excluded). Phase D - an
auto-pairing consumer crediting threat-range into a live poke / siege / draft
verdict - remains. The effective-threat-range axis is EXHAUSTED across the
roster.)

1.112.0 (Wave-clear / AoE-shove scorer - item 300, the ELEVENTH scored axis,
built by a 10-channel roster fan-out. NEW agents/daemon_slayer/waveclear.py: a
per-(champion, source) wave-clear-mechanism registry plus a kind -> weight table
(FULL_AOE 1.0 / AOE_DOT 0.85 / MULTI_HIT 0.6 / CLEAVE_AA 0.5 / SINGLE_TARGET
0.25) and a range_band -> multiplier table (GLOBAL 1.1 / RANGED 1.0 / MELEE 0.7 -
a wave cleared from a safe distance shoves more tempo than one needing a walk
into the minions). Each mechanism carries a 0..1 magnitude (share of the wave it
removes) and a conditional flag (needs the ult up / a stack / an AoE item);
compute_waveclear() folds every mechanism into a single waveclear_score = sum of
kind_weight * range_mult * magnitude (conditional credited at the 0.5 midpoint),
plus a top_kind label and a ranged_shove safe-shove flag. This axis owns the
lane-priority / roam-window / objective-setup TEMPO dimension - every prior axis
scores combat against a champion target; this one scores throughput against a
wave of minions. NEW /waveclear route (POST+GET). PURELY ADDITIVE: reads no
scorer, read by none - every existing route is byte-identical. EXHAUSTIVE
171-champ Workflow fan-out (10 classify + 10 completeness critics, Sonnet,
schema-validated) -> 376 entries / 171 champs (full roster) / 27 conditional /
kinds MULTI_HIT 173 / SINGLE_TARGET 94 / FULL_AOE 62 / AOE_DOT 31 / CLEAVE_AA 16
/ bands RANGED 196 / MELEE 176 / GLOBAL 4; engine + tests hand-written from the
structured output. + tools/ds_waveclear_build.py (reusable validate / inject
generator) + waveclear_registry_notes.json provenance sidecar (Share-excluded).
Live score: Zyra 2.12 / Ziggs 1.82 / AurelionSol 1.80 / Heimerdinger 1.77 /
Brand 1.41 (top shovers) vs Vayne 0.03 / Warwick 0.03 / Yuumi 0.05 (no AoE,
last-hit only); empty / unknown = 0. The wave-clear / AoE-shove axis is EXHAUSTED
across the roster.)

1.111.0 (Scaling / power-curve scorer - item 299, the TENTH scored axis, built
by a 10-channel roster fan-out. NEW agents/daemon_slayer/scaling.py: a
per-(champion, source) scaling-mechanism registry plus a kind -> weight table
(INFINITE_STACK 1.0 / FORM_SPIKE 0.8 / RATIO_HYPERSCALE 0.8 / ITEM_RELIANT 0.5 /
EARLY_FRONTLOAD 0.4). Each mechanism tags the online_stage it keys on (EARLY /
MID / LATE - nothing contributes before its stage) and a 0..1 magnitude;
compute_scaling() folds every online mechanism into an early / mid / late power
triple using a per-kind ramp (_SCALING_STAGE_RAMP: a stack / ratio / item kind
RAMPS UP to 1.0 late, a FORM_SPIKE is flat once unlocked, an EARLY_FRONTLOAD
DECAYS), conditional mechanisms credited at the 0.5 midpoint. scaling_score =
late_power (higher = stronger end-state); scaling_slope = late_power -
early_power (signed trajectory: positive scales up, negative falls off). This is
the only axis that owns the TIME dimension - every other scored axis is a static
snapshot. NEW /scaling route (POST+GET). PURELY ADDITIVE: reads no scorer, read
by none - every existing route is byte-identical. EXHAUSTIVE 171-champ Workflow
fan-out (10 classify + 10 completeness critics, Sonnet, schema-validated) -> 258
entries / 171 champs (full roster) / 42 conditional / kinds EARLY_FRONTLOAD 68 /
FORM_SPIKE 62 / RATIO_HYPERSCALE 62 / ITEM_RELIANT 50 / INFINITE_STACK 16; engine
+ tests hand-written from the structured output. + tools/ds_scaling_build.py
(reusable validate / inject generator) + scaling_registry_notes.json provenance
sidecar (Share-excluded). Live slope: Vladimir +1.84 / Zac +1.41 / Karthus +1.40
/ Nasus +1.305 / Kayle +1.01 (scale up) vs Draven -0.29 / Renekton / Pantheon /
LeeSin / Elise -0.27 (fall off); empty / unknown = 0. The scaling / power-curve
axis is EXHAUSTED across the roster.)

1.110.0 (Sustain / vamp-throughput scorer - item 298, the NINTH scored axis,
built by a 10-channel roster fan-out. NEW agents/daemon_slayer/sustain.py: a
per-(champion, spell) damage-conversion + regen sustain registry (lifesteal /
omnivamp / spellvamp / channelled drains / HP-regen steroids) plus a kind ->
weight table (OMNIVAMP 1.0 / LIFESTEAL 0.8 / DRAIN 0.8 / SPELLVAMP 0.6 /
REGEN 0.4), normalised to effective-HP units where 1.0 unit = _SUSTAIN_HP_UNIT
(300) HP recovered over a fight. A vamp kind returns vamp_pct * _REF_FIGHT_DAMAGE
(2000) HP; a REGEN steroid returns pct_max_hp * _REF_MAX_HP (2200) + flat_hp.
compute_sustain() -> SustainResult with sustain_score (unconditional weighted
units), conditional_sustain_score (gated sources credited at the 0.5 availability
midpoint), total_sustain_score, and raw_sustain_units (unweighted unconditional).
Distinct from the healing-throughput axis (ability_hps + _passive_heal_overrides,
which owns flat / ratio ABILITY heals); this axis owns the damage-conversion +
self-regen attrition the heal axis never measured. NEW /sustain route (POST+GET).
PURELY ADDITIVE: reads no scorer, read by none - every existing route is
byte-identical. EXHAUSTIVE 171-champ Workflow fan-out (10 classify + 10
completeness critics, Sonnet, schema-validated) -> 56 entries / 45 champs / 25
REGEN / 37 conditional; engine + tests hand-written from the structured output;
curated out 2 unbuildable rows (Senna P crit-gated, Pyke P grey-health) + 1
LeeSin W dup + capped Swain R 1.29 -> 0.6. + tools/ds_sustain_build.py (reusable
validate / inject generator) + sustain_registry_notes.json provenance sidecar
(Share-excluded). Live: Warwick 11.67 (top) / Aatrox 6.99 / Nasus 1.28 /
Karthus 0. The sustain / vamp-throughput axis is EXHAUSTED across the roster.)

1.109.0 (Mobility / gap-close / kiting scorer - item 297, the EIGHTH scored axis,
built by a 10-channel roster fan-out. NEW agents/daemon_slayer/mobility.py: a
per-(champion, spell) self-mobility registry (dashes / blinks / leaps / MS
steroids / brief untargetable hops) plus a kind -> weight table (BLINK 1.0 /
DASH 0.8 / LEAP 0.8 / UNTARGET_REPOSITION 0.7 / MS_STEROID 0.5), normalised to
Flash-units where 1.0 unit = one Flash (_FLASH_UNITS = 400 units of instant
displacement). compute_mobility() -> MobilityResult with mobility_score
(unconditional weighted units), conditional_mobility_score (gated moves credited
at the 0.5 availability midpoint), total_mobility_score, and raw_mobility_units
(unweighted unconditional). Normalisation rules: a single displacement is capped
at _MAX_DASH_UNITS (1500, ~one screen) so a global teleport (TwistedFate R /
Shen R / Pantheon R, 25000-unit literals) does not dwarf the axis; a sustained /
toggle MS buff with no fixed window (Quinn R / MissFortune Strut / Warwick W) is
credited over _MS_SUSTAINED_WINDOW_S (3.0s); a multi-charge dash multiplies by
its cast count. 254 entries / 150 champions (105 MS steroids, 130 conditional).
NEW /mobility route (POST + GET) in server.py. PURELY ADDITIVE - reads no
existing scorer and is read by none, so every existing route is byte-identical;
the new endpoint is the opt-in. + tools/ds_mobility_build.py (reusable validate /
inject generator + provenance sidecar). +22 tests. NEXT (Phase D): an
auto-pairing consumer crediting mobility into a live disengage / kite / draft
verdict; per-target tenacity-aware kiting; tune weights + the cap / window
midpoints after a live re-rank.)

1.108.0 (Meraki content-freshness guard - DS source-adoption WIN 2, 2026-06-03.
The Meraki `latest` champions endpoint is mutable but its CONTENT is frozen at a
past game patch; the snapshot `fetched_at` reflects the FETCH wall-clock and lies
about data age. tools/daemon_slayer_abilities_extract.py now surfaces the honest
signal: _meraki_content_patch() takes the newest per-record `patchLastChanged`
(YY.MM, numeric-sorted so 25.15 > 25.9) and stamps it as `meraki_content_patch`
on champion_abilities.json; a pinned _EXPECTED_MERAKI_CONTENT_PATCH = "25.15"
trips a loud WARNING to re-pin + re-validate ability ratios + gold/golden tests
when Meraki finally refreshes. tools/daemon_slayer_extract.py propagates that
content patch into manifest.json meraki_items.content_patch (best-effort read of
the sibling champion_abilities.json). Regenerated 16.11.1/champion_abilities.json:
content patch 25.15, DATA + COVERAGE byte-identical to HEAD (171 champs / 927
forms) - the `latest` content is genuinely frozen, so zero ability-ratio change
and zero engine-behavior risk; ONLY the provenance field was added. The gold/
golden DS tests were already patch-pinned (test_gold_efficiency_p1l13 pins the
vendored 16.10.1 snapshot + derives expected at runtime; test_golden_e2e_p1l24
hand-derives from first principles vs the loaded snapshot), so WIN 2's gold-pin
bullet was a verified no-op. +12 freshness/manifest tests. Also fixed a WIN 1
completion gap caught by the fuller test run: tests/test_routes_ds_combo.py
test_totals_block hardcoded a flat-windup combo duration of 2.0 for Lux that the
WIN 1 AA-windup offset tier (1.107.0) shifted to 1.984 (Lux AA windup 0.25 ->
0.234); replaced the literal with the structural clock-end identity
(duration_s == last action t + its cast_time) so it is robust to windup drift.
Long-term re-source of ability ratios from DDragon/CDragon remains future work.
Plan: docs/DS_SOURCE_ADOPTION_PLAN.md.)

1.107.0 (AA-windup offset tier - DS source-adoption WIN 1, 2026-06-03. The
wiki_stats sidecar left 110 champions on the flat 0.25s AA-windup default; 109
are now recovered from the wiki's published attack_delay_offset via the validated
formula windup_fraction = 0.300 + attack_delay_offset, stored as seconds at base
AS: (0.300 + offset) / as_base (combo.py is a FIXED-windup model, no AS curve).
Fraction validated 4/4 EXACT vs the wiki's own Windup% (Caitlyn/Ashe/Vayne/Jinx).
``tools/daemon_slayer_wiki_stats_extract.py`` now parses attack_delay_offset +
as_base from the SAME ChampionData raw block (zero extra network; signed parse -
the unsigned _scalar_in_block dropped the leading minus most offsets carry) and
adds a ``wiki_offset`` provenance tier in _merge_fill BETWEEN cdragon and the flat
default. wiki_stats.json regenerated: _offset_cast_fills 109, _default_cast_fills
1 (only Alistar has neither an explicit cast time nor an offset), _with_cast_measured
61 -> 170. Consumers byte-identical: combo.py:317 / data_loader.py:188 already
prefer any positive sidecar attack_cast_time, so the 109 new per-champ windups flow
through with no engine-code change. +6 offset-tier tests (extract + overlay).
Plan: docs/DS_SOURCE_ADOPTION_PLAN.md. Source choice deviates from the plan's
literal cdragon mAttackDelayCastOffsetPercent to the wiki raw fields, matching the
validator ds_windup_offset_compare.py ground truth where both offset AND as_base
are co-located.)

1.106.0 (Offensive CC-OUTPUT / lockdown scorer, item 294 - the SEVENTH SCORED axis
and the MIRROR of the survivability CC axes (item 290 champion CC-mitigation / item
292 spell-shield): those score how much enemy CC a champion SURVIVES, this scores
how much CC she APPLIES to enemies - her lockdown contribution as a first-class
offensive-utility metric. The per-spell CC DURATION substrate already existed
(``_PER_SPELL_CC_DURATIONS``, consumed defensively by ``cc_pressure``); durations
alone do not encode lockdown VALUE (a 1.5s suppression and a 1.5s slow are not
equal), so this lift adds the missing schema: a NEW hand-authored per-(champion,
spell) CC-KIND registry plus a kind -> weight table. NEW
``agents/daemon_slayer/cc_output.py`` (``CcOutputEntry`` registry + ``_CC_KIND_WEIGHT``
4-tier table [1.0 hard-disable stun/airborne/charm/fear/taunt/sleep/stasis/polymorph/
suppression; 0.6 action-restricting root/silence/ground/disarm/blind; 0.5 displacement
knockback/pull; 0.2 soft slow/nearsight/cripple] + ``_CC_OUTPUT_CONDITIONAL_PROB=0.5``
availability midpoint + ``compute_cc_output`` -> ``CcOutputResult`` [lockdown_score /
conditional_lockdown_score / total_lockdown_score / total_cc_seconds]). NEW
``/cc-output`` route. PURELY ADDITIVE - the new scorer reads no existing scorer and is
read by none, so every existing route is BYTE-IDENTICAL (the opt-in is the new
endpoint itself, the section-5 "default inert" contract for a brand-new surface). CC
durations are reused VERBATIM from ``_PER_SPELL_CC_DURATIONS`` wherever that registry
carries the spell (108 durations reconciled, single source of truth); slows +
conditional CC the duration registry deliberately excluded are hand-authored from the
verbatim patch-16.11 prose. EXHAUSTIVE 171-champ fan-out (12 parallel classify agents +
12 completeness critics) -> 315 entries / 161 champions / 71 conditional across 18 CC
kinds. + ``tools/ds_cc_output_build.py`` (reusable validate/reconcile/inject generator)
+ ``cc_output_registry_notes.json`` provenance sidecar (Share-excluded like CHANGELOG /
CC_CONDITIONAL_NOTES). +21 tests. NEXT (Phase D, live-gated): the auto-pairing consumer
that credits a champion's lockdown into a team-fight / draft verdict; a
per-target-tenacity output discount; tune the kind weights + conditional midpoint after
a live re-rank.)

1.105.0 (GAP-2 effects-text GUARANTEED-SURVIVAL WINDOW registry, item 293 - the
NINTH survivability axis and the SECOND EHP-NUMERATOR term, after the item-288
revive. A SELF window during which the champion cannot be damaged or killed
(untargetable / stasis / invulnerable) voids ALL incoming damage for its
duration, so it adds the avoided ``window_s / _FIGHT_WINDOW_S`` damage FRACTION to
the EHP numerator - the operator-chosen BOUNDED additive model (the revive shape),
not a divergent uptime model or a consumer-less catalog. This closes the
"guaranteed-survival window (option 2)" that items 288 / 290 / 292 repeatedly
flagged as the remaining unmodeled seam ("a cannot-be-hit / cannot-die window =
infinite EHP for its duration"); the additive fraction keeps it FINITE. NEW
``agents/daemon_slayer/_passive_survival_window_overrides.py`` (``SurvivalWindowEntry``
+ ``survival_window_multiplier`` + 2 operator-tunable availability midpoints
``_SURVIVAL_WINDOW_ULT_PROB=0.35`` / ``_SURVIVAL_WINDOW_BASIC_PROB=0.5``). NEW
``compute_ehp(apply_survival_window=False)`` (default-off byte-identical) folds the
multiplier into the same numerator step as the revive (``combined_revive *=
survival_window_mult``) + ``EhpResult.survival_window_mult`` echo field + to_dict;
threaded through ``rank_items_by_ehp`` / ``compute_hybrid`` / ``rank_items_by_hybrid``
+ the ``/ehp`` ``/rank-tank`` ``/hybrid`` ``/rank-bruiser`` routes. A window voids
every damage type uniformly, so it is a uniform numerator multiplier (re-ranks
nothing, like the revive). EXHAUSTIVE 171-champ scan -> 10 self windows: 6 ults
(Tryndamere R 5s / Kindred R 4s / Taric R 2.5s self / Kayle R 2.5s self / Lissandra
R 2.5s self / Xayah R 1.5s) + 4 basics (Vladimir W 2s / Elise E Rappel 1.95s / Fizz
E 0.75s / Mel W 0.75s). Exclusions: cast-bound OFFENSIVE dashes (Zed R / Camille R /
Master Yi Q / Maokai W / Evelynn R / Galio R / Sion R / Briar R), pets/clones
(Shaco / Wukong / Azir / Elise W / Caitlyn / Aphelios / Illaoi / Lulu / Kayn W /
Neeko), post-death frenzy (Sion P / Karthus P / Kog'Maw P - item 288 class),
revive-domain (Zac P / Zilean R / Kayn P), ally/target/enemy-applied (Kalista R /
TahmKench R / Urgot R / Poppy R / Bard R), conditional/positional invuln (Xin Zhao R
/ Pantheon E / Gwen W - resist half already in _passive_resist_overrides), sustained
attach-state (Yuumi W), windup-only stasis before an escape (Ekko R / Ryze R / Yone
E). The clean SELF survivability schema-lift lane (heal/shield/DR/resist/revive +
ally + CC-mitigation + spell-shield + survival-window) is now EXHAUSTED across both
EHP scorers. NEXT (Phase D, live-gated): flip ``apply_survival_window`` default-on
after a saner-not-different re-rank; feed a live cooldown clock.)

1.104.0 (GAP-2 effects-text SPELL-SHIELD / block-one CC registry, item 292 - the
EIGHTH survivability axis and the SECOND that feeds the cc_blended discount rather
than an EHP numerator/denominator term. Item 290 (1.103.0, the SEVENTH axis)
modeled a SELF tenacity / CC-immunity ABILITY as a multiplicative DURATION scale on
every eaten CC and explicitly deferred this sibling sub-axis: a SPELL-SHIELD blocks
ONE incoming CC INSTANCE entirely (availability-gated by cooldown), it does not
scale every CC's duration. NEW _champion_spell_shield_overrides.py (SpellShieldEntry
+ champion_spell_shield_fraction) seeds the 4 clean SELF spell-shields (Sivir E /
Nocturne W reactive 1.5s spell shields, Fiora W 0.75s parry, Morgana E SELF-cast 5s
CC-immunity shield) amortized at three documented block-AVAILABILITY midpoints
(_SPELL_SHIELD_REACTIVE_PROB 0.2 / _SPELL_SHIELD_DURATION_PROB 0.25 /
_SPELL_SHIELD_PARRY_PROB 0.12). The seam stays SEPARATE from item 290's tenacity:
the block fraction is applied as its OWN multiplicative discount on the
POST-tenacity pressure (cc_total *= 1 - frac), NOT on the effective_cc_duration
tenacity seam, under its OWN compute_ehp(apply_spell_shield=False) flag +
EhpResult.spell_shield_frac echo field. Default-off byte-identical; threaded through
rank_items_by_ehp / compute_hybrid / rank_items_by_hybrid + the /ehp /rank-tank
/hybrid /rank-bruiser routes. EXHAUSTIVE 171-champ scan -> exactly these 4 self
entries; EXCLUSIONS: champion-innate tenacity/immunity (item 290 Garen/Olaf/Malzahar
P), cast-bound engage immunity (Galio R), area/projectile walls (Yasuo W / Shen W),
untargetable/invuln/stasis windows (the guaranteed-survival seam, option 2), and the
Morgana E ALLY cast (ally-grant domain item 289). +18 tests. The default-on flip is
the Phase D job (a live re-rank). The clean SELF CC-survival lane - tenacity (290) +
spell-shield (292) - is now EXHAUSTED; the damage-immunity half stays a different
unmodeled seam.)

1.103.0 (GAP-2 effects-text CHAMPION-INNATE CC-MITIGATION registry, item 290 - the
SEVENTH survivability axis and the FIRST that is NOT an EHP term at all. The six
prior axes (heal/shield throughput, a flat-% DR denominator mult 1.91.0, a
resist-stat denominator add 1.93.0-1.99.0, a revive numerator mult 1.101.0, all
SELF, plus the ally resist+revive grants 1.102.0) all move Effective HP. THIS axis
feeds the OTHER survivability lever the engine already models: cc_blended_ehp
discounts EHP by the enemy CC the caster eats. A champion with an INNATE tenacity /
CC-IMMUNITY ability eats LESS of that pressure, so her CC-adjusted EHP is discounted
LESS. The clean CC-survival HALF of the "guaranteed-survival" family the ally-grant
(item 289) + DR registries flagged as excluded: a tenacity fraction is a finite
DURATION scale, unlike the damage-immunity half (invuln/stasis = infinite EHP),
which stays a different unmodeled seam. NEW _champion_cc_mitigation_overrides.py
(CcMitigationEntry + champion_cc_tenacity_fraction) is the CHAMPION-ability sibling
of the two tenacity sources cc_blended already credits (_item_tenacity item 236 +
the ARAM _TENACITY_MAP); combined MULTIPLICATIVELY with the item source on the same
ehp.effective_cc_duration seam (League tenacity stacks multiplicatively).
compute_ehp(apply_champion_tenacity=False) seam + EhpResult.champion_tenacity_frac;
default-off byte-identical, threaded through rank_items_by_ehp / compute_hybrid /
rank_items_by_hybrid + the /ehp /rank-tank /hybrid /rank-bruiser routes.
EXHAUSTIVE 171-champ scan -> exactly 3 self entries: Garen W (60% tenacity 0.75s,
brief-window midpoint), Olaf R (100% CC immunity 3s active, active-ult midpoint),
Malzahar P (100% CC immunity passive, passive midpoint). Documented exclusions:
cast-bound dash/channel immunity (Sion R/Warwick R/Pantheon R/Kled R+P/Galio
R/Briar R - an offensive engage window, not a defensive uptime), spell-shields
(Fiora W/Morgana E - a binary block-one, the separate spell-shield sub-axis),
ally-targeted (Milio R - the ally-grant domain), one-time cleanse (Kled P/Alistar R
- removes current CC once, not a duration tenacity; Alistar R's 45/55/65% DR is the
_passive_mitigation axis), and the Bard R false positive (epic monsters/turrets are
the immune TARGETS). +15 tests test_champion_cc_mitigation_item290.py. Live /ehp:
Olaf vs a heavy-CC comp cc_blended_ehp rises with the flag on; flag-off byte-
identical. Default-on flip = Phase D, a live re-rank validation.)

1.102.0 (GAP-2 effects-text ALLY-TARGETED survivability grant registry, item 289 -
the SIXTH survivability axis and the FIRST that scores a DIFFERENT champion than the
caster. The five SELF axes (heal/shield throughput, DR denominator mult, resist-stat
denominator add, revive numerator mult) all raise the CASTER's EHP; an ALLY-TARGETED
grant rides a TEAMMATE - the value the granter confers is added to the PROTECTED
ALLY's EHP. This is the "the grant rides an ally, not the caster - the Orianna-E
ball-attached class" the item-264..272 resist registry + the item-288 revive registry
both flagged. NEW _passive_ally_grant_overrides.py (AllyGrantEntry + ally_resist_grant
+ ally_revive_multiplier + _ALLY_REVIVE_PROB) seeds 4: Orianna E (6/12/18/24/30 ally
armor+MR by E rank), Braum W (20-40 ally base by W rank), Taric W (6-10% of GRANTER
total armor, armor only, percent-of-granter mode), Renata W (ally revived to 100% max
health -> numerator mult). GENERIC consumer seam: compute_ehp(external_resist_armor=,
external_resist_mr=, external_revive_multiplier=) default 0.0/0.0/1.0 = byte-identical,
route-reachable on /ehp. EhpResult += ally_grant_armor / _mr / _revive_mult. Exclusions:
ally shields/heals (=ability_hps), ally invuln/untargetable windows (Taric R/Kindred
R/Kayle R/Tahm Kench R/etc. - a guaranteed-survival window, NOT a finite EHP mult),
flat-heal ally revives needing ally max HP (Zilean R/Akshan W deferred to Phase D),
Ornn P false positive. +28 tests. Auto-pairing (which live ally <- which granter) is
the Phase D consumer job; this ships the granter-side values + the seam.)

1.101.0 (GAP-2 effects-text REVIVE / second-life registry, item 288 - the FIFTH
survivability axis and the FIRST EHP-NUMERATOR term. Heals/shields are
throughput, a flat-% DR divides the EHP denominator (1.91.0), a resist-stat grant
raises the armor/MR denominator (1.93.0-1.99.0); a REVIVE is a different shape - a
death-triggered SECOND HP POOL. A champion who can come back is worth
(1 + revived_fraction) of her single-life EHP when the passive is up. This is the
"DIFFERENT non-EHP-denominator seam" item 272 flagged for Anivia P (its -40:20 egg
armor/MR stays the item-272 resist-axis EXCLUSION; this models the REVIVE, not the
egg resist). NEW _passive_revive_overrides.py (PassiveReviveEntry +
revive_multiplier) + compute_ehp(apply_passive_revive=False) seam that multiplies
the per-type EHP NUMERATOR by 1 + revived_hp_fraction(level) * _REVIVE_PROB,
applied BEFORE blended_ehp so the blend + cc_blended inherit it. Default-off
byte-identical. The revived FRACTION is EXACT from the ability text; only the
availability+survival midpoint (_REVIVE_PROB 0.4 - long cooldown + must-survive-
the-resurrection-window) is the assumption (Phase D feeds the live passive-CD +
egg survival). EXHAUSTIVE roster scan (death-triggered self-revive restoring a
sustained HP pool): exactly Anivia P Rebirth (restores ALL health, 240s CD ->
revived_fraction 1.0 -> x1.40) + Zac P Cell Division (10:50% by level, 300s CD,
bloblet-gated -> level_scaled -> x1.04 L1 to x1.20 L18). DOCUMENTED EXCLUSIONS:
post-death decaying frenzy w/ no sustained pool (Sion P / Karthus P / KogMaw P),
ally-targeted revive (Zilean R / Renata W / Akshan W), GA item revive (item-side).
NUMERATOR multiplier (build-independent, uniform scale) so it does NOT re-rank an
item-ranker - it makes the per-row EHP scalars accurate. Threaded through both
EHP-bearing scorers (rank_items_by_ehp + rank_items_by_hybrid) + compute_hybrid +
the /ehp /rank-tank /hybrid /rank-bruiser routes. Hand pin: Anivia L11 blended
2011.42 off -> 2815.98 on (x1.40); Zac L11 x1.1341; Caitlyn off==on byte-identical.
+25 tests test_passive_revive_overrides_item288.py. ENGINE 1.100.0 -> 1.101.0. DS
:8893 restarted -> 1.101.0; RC NOT restarted - DS engine + tests + Share + docs.)

1.100.0 (Passive-damage cadence routing - the compute_dps on_hit -> AA cadence
consumer, 04_GAPS_AND_ROADMAP section 2 "the gated piece". The passive-damage
registry tagged every entry with a cadence string that was metadata-only: the
injected P-form synthetic block is inert in every scorer (compute_ability_dps
skips the P slot, and compute_dps never read the registry), so
apply_passive_damage changed no ranking anywhere. NEW: compute_dps gains an
OPT-IN apply_passive_damage flag (default False = byte-identical) that routes an
allowlisted every-AA on_hit passive's per-hit bonus onto the auto-attack cadence
- evaluated through the canonical to_damage_block + _evaluate_block +
AbilityContext.from_build path, mitigated by the entry's damage type (the shared
resistance curve the AA already uses, plus the magic-debuff amp for MAGIC),
folded into per_attack_on_hit_damage AND the steady DPS (per_hit * eff_as) across
every phase. NEW _AA_ROUTED_ON_HIT_KEYS allowlist + aa_routed_on_hit_entry helper
in _passive_damage_overrides.py. v1 routes ONLY the verified every-AA entries
(Warwick Eternal Hunger, Orianna Clockwork Winding) where the per-hit attribution
is exact; the mark-consume (Lux Illumination), internal-CD (Ziggs Short Fuse),
and empowered-first-hit (Akali / Kha'Zix) on_hit entries are NOT routed - their
amortization needs the structured cadence + a live re-rank check and they carry
forward inert. /dps route gains the apply_passive_damage body param. The
default-on FLIP stays gated (live "saner not just different" validation). Hand
pin: Warwick Eternal Hunger 12:46 at L11 = 32.0 magic per hit, +32.0*eff_as DPS.
+19 tests test_passive_damage_aa_cadence.py. ENGINE 1.99.0 -> 1.100.0. DS :8893
restarted -> 1.100.0; RC NOT restarted - DS engine + tests + Share + docs only.)

1.99.0 (GAP-2 RESIST-STAT grant PER-STACK UNBOUNDED lift, item 272 - the last
cleanly headless-buildable resist-grant exclusion class. A self bonus-armor grant
that scales LINEARLY with a slow game-long accumulator (Thresh souls) with NO
cap, so unlike the BOUNDED per-stack cases (Garen W cap 30/30, Graves E cap 8
stacks, Wukong P cap 5 - all seeded "at the cap" as the steady state) it cannot
be capped; it needs an assumed steady-state count. NEW per-stack seam on
PassiveResistEntry: per_stack_armor / per_stack_mr * assumed_stacks
(_ASSUMED_SOUL_COUNT 25, the item-249 assumed_stacks convention carried to the
EHP seam) summed alongside the flat-add (264/267) + percent (268) halves in
resist_grants; default 0.0 -> flat/percent/bounded-at-cap entries unchanged. NO
new EHP threading (compute_ehp already calls resist_grants). SEEDED 1 (default-OFF
byte-identical to 1.98.0): Thresh P Damnation (1 bonus armor per soul, ARMOR ONLY
- the +1 AP per soul is offensive, not a resist; no MR; UNBOUNDED accumulator
seeded at the assumed steady-state soul count 25 -> 25 bonus armor at the
midpoint; permanent prob 1.0; Thresh's innate "armor does not increase through
growth (per level)" makes souls his ONLY armor scaling, so the grant is load-
bearing for his EHP). EXHAUSTIVE roster scan (per-stack + armor/MR co-occurrence):
Thresh P is the SOLE per-stack-UNBOUNDED self-resist grant - every other per-stack
resist is BOUNDED (Garen W / Graves E / Wukong P combat stacks / Jax R on-hit,
already seeded or omitted). The clean headless effects-text RESIST-grant lane is
now FULLY EXHAUSTED across all 6 source modes (flat 264 + rank-scaled-block 267 +
percent-of-resist 268 + unlabeled-multi-stat-block 270 + form-occupancy 271 +
per-stack-unbounded 272); the 2 remaining resist exclusions each need a DIFFERENT
seam and stay documented NEGATIVES: Anivia P resurrection non-combat state,
Orianna E ball-attached (rides an ally not the caster). Default
apply_passive_resist=False byte-identical. +19 tests
test_passive_resist_per_stack_item272.py.)

1.98.0 (GAP-2 RESIST-STAT grant FORM-OCCUPANCY-gated lift, item 271 - the last
clean headless resist-grant exclusion class. A self bonus armor / MR grant that
exists ONLY in one stance of a 2-form toggle; the other stance carries ZERO of
it, so unlike K'Sante All Out / Kayn R the base cannot be seeded gate-
independently. Amortized by the form-occupancy midpoint (_FORM_OCCUPANCY_PROB
0.5 = a roughly even Cannon/Hammer split), reusing the existing
conditional_probability field - NO new schema field (the item-270 hand-authoring
convention). SEEDED 1 (default-OFF byte-identical to 1.97.0): Jayce R Transform
Mercury Hammer (5/15/25/35 (based on level) armor == MR via _step_per_level even-
quarters, Hammer-stance only; +7.5% bonus AD sub-term omitted - no bonus-AD ctx
on the EHP seam, the item-270 Jax-R / item-264 omission boundary; Cannon-stance R
form 0 only shreds the TARGET, never a self-grant). EXHAUSTIVE roster scan: Jayce
R Hammer is the SOLE form-gated self flat-resist grant (Kled forms are HP not
resist; Elise/Nidalee/Gnar/Shyvana/Swain forms grant no flat resist). The clean
headless effects-text RESIST-grant lane is now FULLY EXHAUSTED across all 5
source modes (flat 264 + rank-scaled-block 267 + percent-of-resist 268 +
unlabeled-multi-stat-block 270 + form-occupancy 271); the 3 remaining resist
exclusions each need a DIFFERENT seam and stay documented NEGATIVES: Anivia P
resurrection non-combat state, Thresh P per-stack-unbounded soul accumulator,
Orianna E ball-attached (rides an ally not the caster). Default
apply_passive_resist=False byte-identical. +24 tests
test_passive_resist_form_gated_item271.py.)

1.97.0 (GAP-2 RESIST-STAT grant UNLABELED MULTI-STAT / MULTI-SERIES block lift,
item 270 - the last seedable resist-grant EXCLUSION class from items 264/267/268,
now seeded. These forms carry a parsed Meraki block that bundles several stats or
two value series with no per-stat label, so item 264 deferred them as "value
cannot be confidently attributed". NO new schema field - the existing flat-add
rank_scaled machinery (item 267) handles all four; HAND attribution resolves the
per-series ambiguity the item-264 note imagined needing a generic parser for.
SEEDED 4 (all default-OFF byte-identical to 1.96.0, rank_scaled flat-add): Singed
R Insanity Potion (ONE shared series [25,60,95] = AP == armor == MR, 25s active
amortized), Braum W Stand Behind Me (self base [20,25,30,35,40] by W rank,
series[1] +36%-of-ALLY-bonus omitted, active amortized), Leona W Eclipse (base
[20,27.5,35,42.5,50] by W rank, series[1] +20% + the per-instance flat damage
reduction omitted, 3s active amortized), Jax R Grandmaster-at-Arms (armor
[25,50,75] + MR [15,30,45] by R rank, series[1] +40%/24%-bonus-AD + per-champ-hit
extra omitted, on-hit active amortized). The rank-varying series[0] is the flat
base; the rank-constant series[1] is a percent coefficient omitted per its
(different) base (cross-champion / uncertain / bonus-AD - the item-264 omission
boundary). resist_grants / compute_ehp / EhpResult unchanged. EXHAUSTIVE roster
re-scan confirmed these 4 are the only non-seeded SELF resist-grant blocks; the 6
other armor/MR blocks are target-SHRED (Evelynn W / JarvanIV Q / Renekton E /
Rengar R / Rumble E / Yorick E). The clean headless effects-text RESIST-grant
lane is now EXHAUSTED (flat + rank-scaled-block + percent-of-resist + unlabeled-
multi-stat-block all seeded); remaining exclusions each need a DIFFERENT seam:
Jayce R form-gated gate-dependent, Anivia P resurrection-state, Thresh P
per-stack-unbounded, Orianna E ball-attached. apply_passive_resist defaults False
-> byte-identical; flag-on CAN re-rank the item-rankers (non-linear _armor_factor,
the item-264 finding) - validate live before flipping default-on (Phase D).)

1.96.0 (GAP-2 RESIST-STAT grant PERCENT-OF-RESIST mode, item 268 - the
candidate-B base-vs-bonus split named in items 264/267 as the documented
percent-mode EXCLUSION, now modeled. A percent-of-resist grant is bonus armor /
MR equal to a PERCENT of the champion's OWN resist STAT (not a flat add): the
flat-add seam (items 264/267) could not express it. NEW PassiveResistEntry
fields armor_pct / mr_pct (percent, flat or per-rank / per-level tuple, resolved
the same way as armor / mr) + pct_base ("total" = base + build, or "bonus" =
build delta total - base). resist_grants gains keyword-only total_armor /
total_mr / base_armor / base_mr (0.0 defaults = a legacy positional call returns
the flat-add half unchanged + any percent entry contributes 0); compute_ehp
threads the RESOLVED build resists in. The percent multiplies the resolved build
resist (excludes these passive grants -> no self-feedback) BEFORE _armor_factor;
flat + percent halves on one entry SUM (Rammus). SEEDED 5 (default-OFF
byte-identical to 1.95.0; rides the item-264 apply_passive_resist flag through
compute_ehp / compute_hybrid / rank_items_by_ehp / rank_items_by_hybrid / /ehp /
/rank-tank / /hybrid / /rank-bruiser, NO new wiring): Malphite W 10/15/20/25/30%
of TOTAL armor by W rank ARMOR-ONLY permanent (Granite-Shield Increased tier
omitted) / Taric W 6/7/8/9/10% of TOTAL armor by W rank ARMOR-ONLY permanent
(ally copy omitted) / Poppy W flat 12% of TOTAL armor + MR permanent (doubled-
24%-below-40%-HP omitted) / Rell W form 1 flat 15% of BONUS armor + MR Dismounted
steady-state (0 itemless) / Rammus W 30/37.5/45/52.5/60% of TOTAL armor + MR by W
rank extending the item-267 flat half on the SAME entry, 7s active amortized at
_ACTIVE_RESIST_PROB. RE-RANK note unchanged from item 264: a resist add goes
through the NON-LINEAR _armor_factor so rank_items_by_ehp / _by_hybrid CAN
re-rank flag-on (a CORRECT re-rank); default flag-OFF stays byte-identical. The
percent-of-resist class is now EXHAUSTED at 16.11.1 - the remaining resist-grant
exclusions are unlabeled-multi-stat-block (Singed R / Braum W / Leona W / Jax R),
form-gated-gate-dependent (Jayce R), resurrection-state (Anivia P), per-stack-
unbounded (Thresh P), ball-attached (Orianna E). +28 tests
test_passive_resist_percent_item268.py.)

1.95.0 (GAP-2 RESIST-STAT grant "read the parsed block" lift, item 267 - the
fifth survivability axis continued. Extends the item-264
_passive_resist_overrides.py registry with grants whose VALUE is NOT in the
effects_descriptions prose ("gains bonus armor and bonus magic resistance" with
no inline number) but lives in a parsed Meraki [other] block indexed by ABILITY
RANK. NEW PassiveResistEntry.rank_scaled flag (mutually exclusive with
level_scaled): armor/mr is a per-ability-rank tuple resolved via
ability_dps.rank_at_level(key, level) - deterministic for ults (R 6/11/16),
engine-default Q>W>E priority for basics; an unlearned ability grants 0.0
(function-level import dodges the ability_dps<->ehp cycle). _value_at_level gains
keyword-only key/rank_scaled (back-compat: existing positional flat/level_scaled
calls unchanged). SEEDED 6 (default-OFF byte-identical to 1.94.0; flows through
the existing item-264 resist_grants -> compute_ehp / compute_hybrid wiring, NO
new EHP threading): Olaf R [10/15/20] PERMANENT (prob 1.0); Nasus R [40/55/70],
Kennen R [20/40/60], Hecarim W [5/10/15/20/25], Rammus W FLAT [27/32/37/42/47]
(%-of-total-resist half OMITTED = percent mode) - all cooldown-gated actives
amortized at _ACTIVE_RESIST_PROB 0.3; Graves E [32/56/80/104/128] ARMOR-ONLY at
the 8-stack cap (prob 1.0, Garen-W-at-cap convention). EXCLUDED (documented):
percent-of-own-resist mode (Malphite W, Taric W, Rammus W %-half, Poppy W, Rell
W); unlabeled multi-stat/multi-tier blocks where the armor/MR value cannot be
confidently attributed (Singed R 3 unlabeled series, Braum W self+ally
base/enhanced, Leona W base/hit-enhanced + %, Jax R flat+%AD stacks); ball-
attached (Orianna E); form-gated (Jayce R Hammer); resurrection (Anivia P). The
re-rank caveat from item 264 still holds: a flat resist add goes through the
non-linear _armor_factor so rank_items_by_ehp / _hybrid CAN re-rank flag-ON
(correct, not a bug); DEFAULT flag-OFF stays byte-identical.)

1.94.0 (Lane A - 1v1 head-to-head matchup engine + /v2/matchup route. NEW module
matchup.py with compute_matchup(snapshot, champ_a_id, champ_b_id, level_a, level_b,
item_ids_a, item_ids_b, mode, hp_a_pct, hp_b_pct, sequence_a, sequence_b) ->
MatchupResult (frozen dataclass + to_dict). The deterministic substitute for an
LLM's "who wins this trade" laning judgment, so live coaching can migrate the
trade question off Claude Haiku. Pure + deterministic - composes ONLY the existing
pure scorers (no LLM, no network, purely additive: a new module + a new route,
changing no existing scorer's output). Composition: (1) resolve each champion's
defensive stats (armor / MR / max HP / bonus HP) via build_champion the SAME way
compute_ehp does, bonus_hp = max(0, hp - base_hp); (2) fire each side's burst combo
into the other's resolved defences - compute_burst_damage already mitigates against
target_armor / target_mr so total_burst_damage IS post-mitigation into the target,
no re-applied armor; (3) effective HP = max HP * the current-HP-pct assumption;
(4) pct_*_removed = capped fraction of the target's effective HP removed by one
combo; (5) net_swing = pct_b_removed - pct_a_removed, the who-wins scalar in
[-1, 1] (positive = A favored); (6) mana gate each side's full combo via
compute_mana_bounded_combo over the EXACT sequence the burst scored (manaless /
energy champs never gate); (7) verdict from operator-tunable module constants
_ALL_IN_KILL_THRESHOLD=1.0 / _TRADE_MARGIN=0.10 / _EVEN_BAND=0.05 -> one of all_in
(A kills B with a full combo + survives) / back_off (A is the one who dies, or
swing firmly negative) / trade (swing firmly positive) / even. NEW /v2/matchup POST
route (mirrors /v2/fight-report; champ_a / champ_b required, level_a / level_b /
item_ids_a / item_ids_b / mode / hp_a_pct / hp_b_pct optional). Property invariants:
mirror -> net_swing 0 + even; symmetry -> swap(A,B) negates net_swing exactly;
level + item advantage -> net_swing > 0; net_swing monotone non-decreasing in
level_a. +tests test_matchup_lane_a.py.)

1.93.0 (item 264 - GAP-2 effects-text RESIST-STAT grant registry + 6 seeded,
default-OFF byte-identical. The FOURTH survivability axis, sibling of the
effects-text HEAL (items 250-254) + SHIELD (item 260) + DAMAGE-REDUCTION (items
261-262) registries. A resist grant is bonus armor / magic resistance a champion
gains from an ability or innate passive that is NOT in the resolved stat block
(not base per-level, not an item), so compute_ehp never carried it. Item 261
documented resist-stat grants as a DELIBERATE EXCLUSION from the DR registry ("a
DIFFERENT axis than a damage multiplier"); this is that axis. NEW module
_passive_resist_overrides.py: PassiveResistEntry (armor + mr terms, flat or
per-level tuple, + conditional_probability + level_scaled) + resist_grants(champ,
level, apply) -> (bonus_armor, bonus_mr). compute_ehp(apply_passive_resist=False)
adds the grants to armor/mr BEFORE _armor_factor (eff_armor = armor + bonus_armor;
a positive grant lowers the resist curve's damage-taken multiplier = larger EHP =
the correct direction). +2 EhpResult fields (passive_resist_armor / _mr, default
0.0) at END + to_dict + note. Threaded rank_items_by_ehp + /ehp + /rank-tank +
compute_hybrid + rank_items_by_hybrid + /hybrid + /rank-bruiser (the full EHP-
bearing scorer pair). SEEDED 6 (4 permanent + 2 active; exact from verbatim
16.11.1 effects_descriptions): Garen W Courage (30 armor + 30 MR cap, permanent),
Wukong P Stone Skin (6:10 by level bonus armor, armor-only, permanent), Shyvana P
(5 armor + 5 MR base, permanent; per-drake +5 omitted), Sejuani P Frost Armor (10
armor + 10 MR in-combat, permanent; +75% bonus-resist sub-terms omitted), Gwen W
Hallowed Mist (22 armor + 22 MR active mist, amortized 0.3; +7% AP omitted),
Pantheon E Aegis Assault (5:30 by level armor + MR, 4s active, amortized 0.3,
level_scaled; +2.5% bonus HP omitted). EXCLUDED (documented NEGATIVES): value-not-
in-effects-text (Olaf R / Rammus W / Kennen R / Nasus R / Hecarim W / Malphite W /
Singed R / Taric W / Graves E - value in a parsed block, not the prose), percent-
of-resist multiplier (Poppy W +12% total / Rell W 15% bonus - needs a base-vs-
bonus resist split), form-gated gate-dependent magnitude (Jayce R Hammer - Cannon
has zero), resurrection-state (Anivia P), per-stack unbounded (Thresh P souls),
ball-attached (Orianna E). KEY FINDING (honest, DIFFERS from the DR registry): a
flat resist add goes through the NON-LINEAR _armor_factor, so unlike item 261's
DR (a uniform multiplicative EHP scale that is rank-INVARIANT) a resist grant is
NOT a uniform scale -> rank_items_by_ehp / rank_items_by_hybrid CAN re-rank flag-
on (an armor item is worth marginally less EHP to a champ that already carries +30
innate armor). DEFAULT apply_passive_resist=False = both grants 0.0 = byte-
identical to 1.92.0. +N tests test_passive_resist_overrides_item264.py.)

1.92.0 (item 262 - thread apply_passive_mitigation into the BRUISER EHP scorer,
default-OFF byte-identical. Symmetric completion of item 261: that wired the
item-261 effects-text DAMAGE-REDUCTION layer into the TANK scorer (compute_ehp +
rank_items_by_ehp + /ehp + /rank-tank); this mirrors it for the bruiser path
(compute_hybrid + rank_items_by_hybrid + /hybrid + /rank-bruiser). apply_passive_mitigation
flows to every compute_ehp call so a champion with a registered mitigation passive
(Kassadin / KSante / Briar / Irelia / Nilah) gets a DR-boosted ehp + cc_blended_ehp
-> a larger hybrid_score scalar. Default False = all three DR multipliers 1.0 =
BYTE-IDENTICAL to 1.91.0. The mitigation is a CHAMPION passive (build-independent),
so it scales the EHP denominator uniformly across the baseline AND every candidate;
the ratio-based hybrid_delta_pct sort key (delta_ehp / baseline_ehp) is INVARIANT
under that uniform scale -> enabling it does NOT re-rank, it makes the per-row
hybrid_score + cc_blended_ehp scalars accurate (mirrors item 261's tank
rank_items_by_ehp - a champ passive cannot differentiate one candidate from another
the way the build-dependent tenacity term does). This completes the EHP-bearing
scorer pair: tank ds.ehp + bruiser ds.hybrid are both mitigation-aware; the other 4
scorers (carry/mage/assassin/enchanter) score on DPS/burst/HPS not EHP so a DR
denominator does not apply. +14 tests test_bruiser_mitigation_item262.py. NO engine
math change beyond the additive flag threading - no new EhpResult/HybridResult fields,
no registry change.)

1.91.0 (item 261 / GAP 2 - effects-text-only DAMAGE-REDUCTION (mitigation)
registry, default-OFF byte-identical. The survivability-triad SIBLING of the
effects-text HEAL (items 250-254) + SHIELD (item 260) registries, but for the
THIRD survivability axis: a flat-% damage-reduction multiplier. Heals + shields
are survivability THROUGHPUT (feed compute_ability_hps); damage reduction is the
survivability DENOMINATOR - a "% less damage taken" is strictly multiplicative on
Effective HP, so it folds into compute_ehp's physical/magical/true EHP
denominators. NEW _passive_mitigation_overrides.py: PassiveMitigationEntry (terms
of (pct, damage_type) + conditional_probability + level_scaled) +
_PASSIVE_MITIGATION_OVERRIDES + mitigation_multipliers(champ, level, apply) ->
(mit_phys, mit_mag, mit_true). NO synthetic block (DR is not an ability
attribute_kind; compute_ehp reads only armor/MR - even the DR percents Meraki
parses into a "modifier" block are uncovered by the EHP consumer). compute_ehp
gains apply_passive_mitigation=False; when True the three multipliers divide the
matching denominator (mult < 1.0 = smaller divisor = larger EHP = the correct DR
direction). Threaded through rank_items_by_ehp + /ehp + /rank-tank (all default-OFF
byte-identical). +3 EhpResult fields (passive_mitigation_phys/mag/true, default
1.0). SEEDED 5 (exhaustive of the clean flat-% multiplicative DR set at 16.11.1):
Kassadin P Void Stone (10% magic, PERMANENT prob 1.0) / Nilah W Jubilant Veil (25%
magic, active) / KSante W Path Maker (30% all, active; All Out 75% R-form-gated
omitted) / Briar E Chilling Scream (35% all, active) / Irelia W Defiant Dance
(physical 40:70 + magic 20:35 based-on-level, active; +AP sub-terms omitted;
level_scaled). The 4 actives are cooldown-gated bursts amortized by the
operator-tunable conditional_probability midpoint _ACTIVE_DR_PROB=0.3 (the
expected fraction of a fight the active is up); the exact percent is shipped, only
the firing midpoint is the assumption (item-255 convention). EXCLUDED (documented):
per-instance flat-amount DR (Fizz P / Amumu E / Leona W - hit-count dependent, the
vamp-class boundary), DR-percent-not-in-effects-text (Alistar R / Gragas W /
Warwick E / BelVeth E - value only in a modifier block), resist-stat grants (Garen
W Courage armor/MR), AoE-only (Jax E), immunity-until-hit (Malzahar P Void Shift
90%), partial-window+modified-value (Master Yi W 70% first 0.5s), dodge/untargetable
(Zed R / Yone E / Vladimir W), grey-health/Grit (DrMundo W / Sett W / Morde W /
Rengar W / TahmKench E), offensive damage-falloff (Ezreal R / Xayah Q / Qiyana Q),
vamp/heal lines. +37 tests test_passive_mitigation_overrides_item261.py. ENGINE
1.90.0 -> 1.91.0. DS :8893 restarted -> 1.91.0; RC NOT restarted - DS engine +
tests + Share + docs only.)

1.90.0 (item 260 / GAP 2 - effects-text-only SHIELD registry, default-OFF
byte-identical. New _passive_shield_overrides.py (sibling of the heal/damage
registries): a synthetic attribute_kind="shield" block for the self-shields whose
magnitude lives only in stripped effects_descriptions (no shield block parsed).
The consumer was already complete - ability_hps._eval_heal_shield_block is kind-
agnostic and compute_ability_hps already sums _select_kind_blocks(form,"shield")
into total_shield_per_sec (the 56 snapshot shields were scored); this registry
adds only the missing effects-text half. Injected by AbilitiesSnapshot.load(
apply_passive_shield=True) when the form has NO existing shield block. SEEDED 10
(exhaustive of the clean self-shield set at 16.11.1): Malphite P Granite Shield
(10% max HP) / Camille P Adaptive Defenses (20% max HP) / Vi P Blast Shield (12%
max HP) / Rakan P Fey Feathers (30:225 + 95% AP) / Shen P Ki Barrier (47:120 +
13% bonus HP) / Yasuo P Way of the Wanderer (125:600 Flow-shield) / Blitzcrank P
Mana Barrier (35% max MANA) / Skarner W Seismic Bastion (8% max HP) / Volibear E
Sky Splitter (14% max HP + 75% AP) / Viktor Q Siphon Power (40:115 + 18% AP,
level_scaled). One additive unit "% maximum mana" -> caster_max_mp in
ability_hps._HEAL_UNIT_TO_CTX (the ctx attr already existed; no snapshot block
uses a mana unit -> default path byte-identical). No bilinear / per-charge term
needed. Conditional gates (Blitzcrank 30% HP / Camille+Vi periodic / Volibear
within-strike / Yasuo full-Flow) NOT modeled - the magnitude is gate-independent
(Evelynn-P/Kayn-form precedent). EXCLUDED (documented): spell shields (Nocturne
W / Sivir E), damage-stored barriers (Sett W Grit / Mordekaiser W / TahmKench E),
shield re-grants (Galio R / Yuumi R), shield-strips (Blitzcrank R / Rell Q),
shield-verb-but-no-grant (weapon-flavor / damage-reduction / amp / vamp). +31 tests
test_passive_shield_overrides_item260.py. ENGINE 1.89.0 -> 1.90.0. DS :8893
restarted -> 1.90.0; RC NOT restarted - DS engine + tests + Share + docs only.)

1.89.0 (item 258 / gap-plan Phase D - authored the C2 AA-empower amortized values
in _ability_amp_overrides.py, default-OFF byte-identical. The 5 base="aa" AmpEntry
champs (Caitlyn W / Fiora E / Jayce W f1 / Sivir W / Nidalee Q f1) carried
placeholder amp_per_rank=(0.0,) since item 247 wired the dps.compute_dps consumer
(_aa_amp_multiplier scales ONLY the base-AA single-target damage component
base_dps - NOT item proc DPS, NOT attack speed, NOT extra-target bounces). Of the
5, ONLY Fiora E fits that seam and is AUTHORED; the other 4 stay INERT with
documented non-fit reasons. AUTHORED: Fiora E Bladework - the 2nd empowered AA is
a GUARANTEED CRIT at modified crit damage 160%:200% by E rank (damage_block
"Critical damage"), a real (m-1) per-AA uplift on Fiora's typical no-crit bruiser
build (the 1st empowered AA cannot crit -> modeled neutral). AMORTIZED over the E
cooldown (11/10/9/8/7s) at AS=1.0 baseline: addend=(m-1)/cd -> amp_per_rank
(0.0545,0.0700,0.0889,0.1125,0.1429), always_on (the addend is the already-
amortized expected per-AA uplift; a probability gate would double-discount).
ASSUMPTION (operator-tunable, same convention as item-249 assumed_stacks /
item-255 conditional_probability): AS=1.0 sustained window + 1st-AA crit-loss
modeled neutral + no-crit build (a crit build folds crit into base_dps so this
would over-credit). INERT (4, documented non-fit): Caitlyn W = Headshot bonus is
a trap-spring-gated separate passive not a base-AA multiplier (would over-credit
every AA); Jayce W f1 = per-AA modifier 70:110% AD is mostly < 1.0*AD, spell value
is the +360% bonus AS the consumer cannot model (would read as a base-AA nerf);
Sivir W = extra-target bounce (40:50% AD to others) + AS, single-target AA damage
unchanged; Nidalee Q f1 = Takedown CONVERTS the AA to a magic missing-HP formula
(not a physical base-AA multiplier) gated behind a Cougar-form Q recast. NEW
source-rank guard in _aa_amp_multiplier: an entry whose spell is UNLEVELED
(rank < 0) contributes factor 1.0 (mirrors the item-257 cross-spell src_rank >= 0
guard; a low-level Fiora with E not yet leveled under the canonical 1-point
distribution stays byte-identical to the no-amp baseline). LIVE (compute_dps
weighted_dps, itemless): Fiora apply_ability_amps=False L4 37.2852 / L11 31.0544 /
L18 42.3214 -> True 39.3172 (x1.0545 E rank0) / 32.7469 / 48.3691 (x1.1429 E
rank4); Fiora L1-3 (E rank -1) byte-identical; Caitlyn / Jayce / Sivir / Nidalee
flag-on byte-identical (4 inert); Lux control byte-identical; default
apply_ability_amps=False byte-identical for all champions. +18 tests
test_aa_empower_authored_item258.py. ENGINE 1.88.0 -> 1.89.0. DS :8893 restarted
-> 1.89.0; RC NOT restarted - DS engine + tests + Share + docs only.)

1.88.0 (item 257 / gap-plan C2x - AurelionSol W CROSS-SPELL self-state amp seam,
default-OFF byte-identical. Resolves the last _STAGED_AMP_CANDIDATES entry that
the per-form AmpEntry key could not express: AurelionSol W (Astral Flight)
carries a "Breath of Light Flat Damage Modifier" [108,109,110,111,112]% that
amplifies the Q beam WHILE W flight is active; W f0 itself has no damage block.
NEW CrossSpellAmpEntry (source_key + amp_per_rank + condition) + NEW
_CROSS_SPELL_AMP_OVERRIDES keyed by the TARGET spell (AurelionSol Q f0,
source_key=W, amp_per_rank 0.08..0.12, condition w_flight) + NEW _cross_spell_amp_for
resolver + NEW _COND_W_FLIGHT condition (0.4 midpoint, the magnitude the staged
entry always documented). compute_ability_dps consults it ONLY under
apply_ability_amps=True: resolves the SOURCE (W) rank via rank_at_level at the
current level + gates on the W-flight midpoint, multiplying the target Q's
per-cast amp factor; skipped when W is unleveled (rank < 0 -> no buff). NO
double-count (W f0 has no damage block; Q has no _ABILITY_AMP_OVERRIDES entry).
_STAGED_AMP_CANDIDATES is now EMPTY (Sion Q + Hwei Q f2 resolved item 246 via
block-index routing; AurelionSol W resolved here). _amp_multiplier type widened
to AmpEntry | CrossSpellAmpEntry (both carry amp_per_rank/always_on/condition).
LIVE: AurelionSol Q apply_ability_amps=True lvl1 byte-identical 146.25 (W rank -1
skipped) / lvl11 292.5 -> 304.2 (x1.04 = 1 + 0.4*0.10 W rank 2) / lvl16 292.5 ->
306.54 (x1.048 = 1 + 0.4*0.12 W rank 4); default apply_ability_amps=False
byte-identical for all champions; Caitlyn control flag-on byte-identical (no
cross-spell entry). +20 tests test_cross_spell_amp_item257.py. ENGINE 1.87.0 ->
1.88.0. DS :8893 restarted -> 1.88.0; RC NOT restarted - DS engine + tests +
Share + docs only.)

1.87.0 (item 255 / gap-plan - GAP-2 CONDITIONAL-GATE effects-text DAMAGE schema
lift + 5 SEEDED, default-OFF byte-identical. The class items 248/249 STAGED
(Brand P ring explosion + Ekko W sub-30% passive) + 3 siblings the exhaustion
scan surfaced (Jhin P 4th shot, K'Sante P mark consume, Sejuani P frozen
detonation). TWO new PassiveDamageEntry fields (+ the same on PerStackTerm for
the fold): (a) target_missing_hp_pct = % of the target's MISSING health (the
sibling of target_max_hp_pct; rides the EXISTING evaluator -
target_missing_hp_pct -> target_missing_hp is already in _SCALING_TARGETS - so
ZERO new evaluator math; resolves to 0 at the default full-HP ctx = byte-
identical lower-bound, like the missing-HP HEAL seeds, surfacing only under a
sub-threshold target_current_hp_pct). (b) conditional_probability (default 1.0
= no-op for the 23 prior entries) - to_damage_block MULTIPLIES every coefficient
(base + each scaling field + each bilinear factor) by it so the injected block
is the amortized expected magnitude; the documented operator-tunable firing
midpoint for a gate NOT expressible via the target-HP ctx (per_stack
assumed_stacks + cc_conditional probability precedent). SEEDED (5, verbatim
16.11.1): Brand P Blaze ring explosion (8%:12% (based on level) + 2%/100 AP
MAX HP, MAGIC, per_fight, conditional_probability 0.5 = 3-stack+2s detonation
firing midpoint; base Ablaze DoT not modeled) / Ekko W Parallel Convergence
passive (3% + 3%/100 AP MISSING HP, MAGIC, on_hit, conditional_probability 1.0 -
the sub-30%-HP gate is ctx-ENCODED so a second probability would double-discount;
0 at full HP) / Jhin P Whisper 4th shot (15/20/25% (based on level) MISSING HP,
PHYSICAL, on_hit, conditional_probability 0.25 = EXACT every-4th-shot frequency;
always-crit + AD steroid omitted; 0 at full HP) / K'Sante P Dauntless Instinct
mark consume (12 + 1%:2% (based on level) MAX HP, PHYSICAL, on_hit, prob 1.0;
All Out Bonus bonus-armor/MR %max-HP omitted - no ctx, Caitlyn-crit precedent) /
Sejuani P Icebreaker frozen detonation (10% MAX HP, MAGIC, per_fight,
conditional_probability 0.5 = CC-detonation firing midpoint). REJECTS
(documented): Kai'Sa P 5th-stack consume (the (Kaisa,P,0) key holds the
UNCONDITIONAL Caustic Wounds per-stack ramp; a per-entry conditional_probability
would wrongly gate it - needs per-TERM gating / a multi-entry registry) / Zed P
below-50% (already shipped item 247, full magnitude gate-not-modeled, not
re-gated) / Zeri P full-charge shot (AA-replacement semantics, the additive
passive seam mis-models it) / Samira P blade bonus (the missing-HP clause is a
MULTIPLIER on a flat+AD on-hit, not an additive %-HP term) / the missing-HP
HEALS (Karma W f1 / Viego P - in the heal registry, not damage). +20 tests
test_passive_damage_conditional_gate_item255.py. LIVE in-process block-eval:
Brand P apply_passive_damage=True 0.5*lerp(8,12)@L11*2500 = 129.41 no-AP /
293.41 at AP 656; Ekko W 0 at full HP / 425.25 at 25% HP (AP 656); Jhin P 0 at
full HP / 93.75 at 25% HP (= 0.25*20%*1875 EXACT, no AP); K'Sante P 51.71
(12 + 1.59%*2500); Sejuani P 125.0 (= 0.5*10%*2500); all default-OFF
byte-identical. DS suite 5866 -> 5886 (+20). ENGINE 1.86.0 -> 1.87.0. DS :8893
restarted -> 1.87.0; RC NOT restarted - DS engine + tests + Share + docs only.)

1.86.0 (item 254 / gap-plan - GAP-2 LINEAR effects-text HEAL registry RE-OPEN
(the item-251 sibling slice) + 4 SEEDED, default-OFF byte-identical. NO schema
change - the 4 new entries use the EXISTING item-251 linear machinery (same
_PASSIVE_HEAL_OVERRIDES dict, same to_heal_block, same _eval_heal_shield_block);
a linear entry just carries no bilinear_terms / no per_charge. The item-253
AS-aware roster pass logged Mordekaiser R "heal 10% of their maximum health" as
a clean target-max-HP linear heal the original item-251 84-candidate scan
overlooked; this slice re-runs the exhaustive scan (all 171 champs, no-heal-block
forms whose effects_descriptions carry a heal/restore verb AND a self/target HP
quantity) and recovers 4 misses. SEEDED 4: Mordekaiser R Realm of Death (10%
TARGET max HP on the soul-consume, flat across all 3 R ranks - target-relative,
0 at rest, surfaces under resolve_target_relative + target_max_hp, cadence
per_cast); Illaoi P Prophet of an Elder God (5% caster MISSING HP per Tentacle
that hits a champion - missing-HP, 0 at rest, surfaces under
resolve_target_relative + caster_missing_hp_pct, per-Tentacle lower bound);
Zac P Cell Division Goo (4% : 8% by level caster MAX HP per chunk consumed -
resolves at the default like Maokai/Swain, per-chunk lower bound, the
resurrection 50% revive omitted); Dr. Mundo P Goes Where He Pleases (4% caster
MAX HP on the immobilize-resist canister consume - resolves at the default like
Gragas; the per-5s max-HP regen tick omitted as a regen-rate steroid). EXHAUSTED:
the re-scan confirmed the remaining heal-verb+HP hits are %-of-HP DAMAGE lines
(Aatrox/Brand/Gwen/Sejuani/Smolder - the heal-verb match was spurious), the
documented vamp / revive / grey-health classes (Darius Q bespoke, Pyke P / Sion P
/ TahmKench E, Warwick W is a sub-50%-HP HUNT trigger not a heal), a PET heal
(Zyra R restores her PLANTS' current HP), or a remount / mount-HP restore (Kled P
- Skaarl restores 40-70% of the MOUNT's max HP on a 100-Courage remount, the
revive-adjacent class). The LINEAR effects-text heal class is now EXHAUSTED at
patch 16.11.1. Default apply_passive_heal=False (load_default) byte-identical
(the seam injects only under the flag, gated on no existing heal block - all 4
forms have empty damage_blocks). +20 tests test_passive_heal_overrides_linear_
reopen_item254.py. DS :8893 restarted -> 1.86.0; RC NOT restarted - DS engine +
tests + Share + docs only.)

1.85.0 (item 253 / gap-plan - GAP-2 AS-AWARE effects-text HEAL seam + the LAST
named clean headless heal lift, default-OFF byte-identical. The bilinear HEAL
registry (items 250-252) could not express a heal scaling on bonus ATTACK SPEED
because the heal block carried no AS stat - so Viego P's "+5% per 100% bonus
attack speed of the target's maximum health" sub-term was deliberately OMITTED
in item 250 and carried forward. This slice closes it: compute_ability_hps now
feeds a "bonus_as" entry into the bilinear_ctx = bonus attack speed in PERCENTAGE
POINTS (total AS minus the champion's INNATE base AS over the innate base, the
"% per 100% bonus AS" convention - it credits BOTH the per-level AND item AS
bonus; the innate base is the champion record's flat "attackspeed" stat, e.g.
Viego 0.658, NOT resolved.base_stats["as"] which folds per-level AS growth into
"base"). The AS term is then a plain _per_100(5.0, "bonus_as", "target_max_hp")
bilinear product - ZERO new eval math (the item-248 bilinear evaluator already
sums factor * ctx[a] * ctx[b]); only the new caster-stat key. bonus_as is a pure
caster stat (always resolved); the Viego term gates on its target_max_hp half so
a build with no AS bonus and the default resolve_target_relative=False are both
byte-identical (the bilinear product is 0). SEEDED 1 (the sole AS-scaled heal in
the EXHAUSTED roster scan): Viego P gains the 4th term (was 3: flat 2% + 2.5%/100
bonus AD + 2%/100 AP target max HP; now + 5% per 100% bonus AS target max HP).
EXHAUSTED: the all-171-champ scan for a heal OR shield magnitude scaling on the
caster's own bonus attack speed found Viego P and nothing else - every other
"attack speed" + heal line is an AS buff, a vamp/life-steal clause (excluded
class), a stat-steal on the TARGET (Mordekaiser R reduces the target's AS), or a
heal-amp multiplier (Trundle W / Nilah P). +16 tests test_passive_heal_overrides_
as_aware_item253.py (+ 2 item-250 Viego pins rescoped for the 3rd bilinear term).
DS suite 5818 -> 5834. DS :8893 restarted -> 1.85.0; RC NOT
restarted - DS engine + tests + Share + docs only. NOTE: Mordekaiser R "heal 10%
of target max HP" surfaced in the scan as a LINEAR target-max-HP heal that the
item-251 linear registry missed - NOT AS-scaled, out of scope here; logged for a
future linear-registry re-open.)

1.84.0 (item 252 / gap-plan - GAP-2 PER-CHARGE effects-text HEAL seam + 1
SEEDED, default-OFF byte-identical. The heal sibling of the item-249 per-stack
DAMAGE fold: PassiveHealEntry gains per_charge (a tuple of (value, unit) linear
terms read "per charge", same shape + unit maps as linear_terms) + assumed_
charges (the operator-tunable steady-state stock); to_heal_block FOLDS each
per_charge term * assumed_charges into raw_modifiers at BUILD time, so the
existing ability_hps._eval_heal_shield_block needs ZERO new math (the per-charge
contribution collapses into ordinary raw_modifiers once the count is fixed - no
abilities.py / ability_hps.py change). SEEDED 1 (the sole per-charge heal in the
EXHAUSTED scan): Taric Q Starlight's Touch - 25 (+ 15% AP) (+ 1% of caster max
HP) per charge; the 3 per-charge terms fold * assumed_charges 3.0 (typical mid-
fight stock; the per-charge COEFFICIENTS are exact, only the count is the
assumption; true cap = Q rank, max 5 at rank 5). NO existing heal block on Taric
Q (only a "Maximum Charges" attribute_kind="other" block), so the seam's no-
existing-heal-block gate admits it. All terms flat / caster-stat -> resolve NON-
zero at the default resolve_target_relative=False (no HP assumption needed, like
the item-251 linear caster-stat seeds); the apply_passive_heal=False DEFAULT
(load_default) stays byte-identical. EXHAUSTED: Taric Q is the only per-charge
HEAL (the only other charge mechanic, Zeri P, is a DAMAGE charge); Taric Q moved
out of the in-module BESPOKE exclusion. +18 tests test_passive_heal_overrides_
per_charge_item252.py. DS suite 5800 -> 5818. DS :8893 restarted -> 1.84.0; RC
NOT restarted - DS engine + tests + Share + docs only.)

1.83.0 (item 251 / gap-plan - GAP-2 LINEAR effects-text-only HEAL registry +
16 SEEDED, default-OFF byte-identical. The sibling slice to item 250's 3
BILINEAR heals: the same _passive_heal_overrides module + apply_passive_heal
seam + compute_ability_hps consumer now also carry LINEAR effects-text self-
heals (flat "35 : 100 based on level", caster-stat-scaled "+ 20% AP" / "5.5% of
max HP", per-level-pct-of-HP) found in the EXHAUSTED 84-candidate scan (forms
with NO attribute_kind=="heal" block whose effects_descriptions carry a heal
verb). SEEDED 16: 14 P-slot - Ahri P (35:95 + 20% AP, 9-stack consume) /
Alistar P (5% max HP, 7-stack) / Aurora P (3:20 + 2% AP per Spirit/sec) /
Cho'Gath P (18:52 on-kill) / Evelynn P (15:150/sec below-threshold, gate not
modeled) / Fiora P (35:100 Vital) / Gragas P (5.5% max HP) / Lillia P (6:90 +
30% AP vs champ) / Maokai P (4%:12.8% max HP empowered AA) / Rek'Sai P (10%:20%
max HP Fury consume) / Swain P (3%:6% max HP soul fragment) / Trundle P (1.8%:
5.5% TARGET max HP on death - resolves under resolve_target_relative) / Xin Zhao
P (3/3.5/4% max HP + 65% AP on-hit) / Yuumi P (20:110 + 25% AP periodic) - plus
2 SPELL-slot Rakan Q (40:210 + 55% AP) / Talon Q (9:55 on-kill). SCHEMA LIFT
(the one novel piece beyond item 250): NEW level_scaled flag (PassiveHealEntry
+ DamageBlock + a level param threaded through ability_hps._select_kind_blocks /
_eval_heal_shield_block) so a SPELL-slot heal scaling "based on level" reads its
18-element per-level tuple at the champion LEVEL (level-1), not the spell rank -
Rakan Q / Talon Q (a Q-rank index would mis-read a level-scaled heal). UNLIKE
the 3 bilinear seeds (all target/missing-HP scaled -> 0 at resolve-off), most
linear seeds have a FLAT / caster-stat term that resolves NON-zero at the
default resolve_target_relative=False - so apply_passive_heal=True surfaces them
without an HP assumption; the apply_passive_heal=False DEFAULT (load_default)
stays byte-identical. EXCLUSIONS documented in-module (vamp / resource-restore /
revive / grey-health / bespoke-product/charge/crit/form-gate). +22 tests
test_passive_heal_overrides_linear_item251.py; item-250 test rescoped 3->19
registry. DS suite 5778 -> 5800. DS :8893 restarted -> 1.83.0; RC NOT
restarted.)

1.82.0 (item 250 / gap-plan - GAP-2 effects-text-only HEAL registry (bilinear
AP/AD-on-HP) + 3 SEEDED, default-OFF byte-identical. The HEAL sibling of the
items 247-249 effects-text-only passive DAMAGE registry. A class of P/W/R forms
parse to NO attribute_kind=="heal" block (the heal lives only in stripped
effects_descriptions text) yet carry a self-heal whose dominant term is a
BILINEAR (base% + per100% * stat) * HP product - an AP / bonus-AD scaled
%-of-HP heal that no single linear heal unit expresses. Because heals feed
ability_hps (compute_ability_hps reads heal blocks from raw_modifiers, not the
typed fields the damage evaluator uses), this is a NEW module
(_passive_heal_overrides.py) + a NEW opt-in flag (AbilitiesSnapshot.load(
apply_passive_heal=True) + _apply_passive_heal_overrides) + a NEW consumer path
(ability_hps._eval_heal_shield_block evaluates a synthetic heal block's
bilinear_terms against a bilinear_ctx dict). to_heal_block builds a synthetic
DamageBlock(attribute_kind="heal", raw_modifiers=(...linear %-of-HP...),
bilinear_terms=(...products...)); the linear terms resolve through the EXISTING
v2 resolve_target_relative / extra_units machinery and the bilinear products
through the new bilinear_ctx. SEEDED from verbatim 16.11.1 effects_descriptions,
all default-OFF: Viego P Sovereign's Domination (heal 2% (+ 2.5% per 100 bonus
AD) (+ 2% per 100 AP) of target max HP on Mist-Wraith consume; the +5% per 100%
bonus-AS term is OMITTED - no AS ctx on a heal block, same boundary as the
damage registry's omitted crit terms; takedown-gated per_fight cadence) + Karma
W f1 Renewal (heal 17% (+ 1% per 100 AP) of caster missing HP on the Mantra-
empowered W; the 2nd on-tether-complete heal omitted; form 1, so a consumer
routes W->1 via form_index_overrides) + Kayn R Umbral Trespass Darkin (heal
11.25% (+ 7.5% per 100 bonus AD) of target max HP; Rhaast-form-only, the form
gate not modeled - magnitude gate-independent, Zed-P precedent). STRONGER
default-OFF story than the damage registry: every seeded heal scales on a
target / caster-MISSING HP quantity that compute_ability_hps resolves to 0
unless the caller opts into resolve_target_relative + an HP assumption, so even
with apply_passive_heal=True the DEFAULT compute_ability_hps call
(resolve_target_relative=False) is byte-identical - the seeded heals contribute
0 (unresolved lower bound) and the spell row is skipped. EXHAUSTED scan (171
champs, forms with no heal block whose effects_descriptions carry heal +
"per 100 X" + max/missing health): the bilinear self-heal set is exactly these
3. Documented EXCLUSIONS (scanned, not seeded): Fiora P (heal is FLAT 35:100,
the bilinear term is its DAMAGE) -> a future LINEAR effects-text-heal registry;
Vladimir Q (already has a snapshot heal block; the bilinear missing-HP term is a
conditional Crimson-Rush-empowered BONUS - the no-existing-heal-block gate
correctly skips it). +23 tests test_passive_heal_overrides_item250.py (registry
shape / to_heal_block raw+bilinear shape / _per_100 factor reuse / exact eval
math for the 3 / lower-bound unresolved without extra_units / bilinear_ctx=None
no-op / load seam gate skips when a heal block exists / flag-on resolve-off
byte-identical to flag-off / inject-on verbatim L13 per-cast values for the 3 /
AP raises Viego's per-cast). DEFAULT byte-identical: the full DS suite is
unchanged with apply_passive_heal at its False default.)

1.81.0 (item 249 / gap-plan - GAP-2 PER-STACK passive damage schema lift + 3
SEEDED + 1 UPGRADE, default-OFF byte-identical. Some passives deal damage that
scales LINEARLY with the number of stacks on the target; the per-stack
COEFFICIENTS are exact and only the stack MULTIPLIER is a steady-state
``assumed_stacks`` (documented per entry, operator-tunable, externalized so a
future live consumer can feed the real count - mirrors item 236's tenacity
externalization). The lift adds the ``PerStackTerm`` dataclass +
``PassiveDamageEntry.per_stack`` / ``assumed_stacks`` fields;
``_passive_damage_overrides.to_damage_block`` FOLDS ``field + per_stack.field *
assumed_stacks`` element-wise into the synthetic DamageBlock, so
``ability_dps._evaluate_block`` needs ZERO new math (no abilities.py /
ability_dps.py change - the per-stack contribution collapses into the ordinary
base/scaling fields once the assumed count is fixed). SEEDED from verbatim
16.11.1 effects_descriptions, all default-OFF (the seam injects only under
apply_passive_damage=True): Kai'Sa P Caustic Wounds (4:24 by level + 12% AP, +
(1:6 by level + 3% AP) per Plasma stack; the "12%:24% based on stacks" AP ratio
is linear = 12% + 3%/stack; assumed_stacks 2.0 = the 0..4 ramp-cycle-average -
the canonical case STAGED through item 248) + Darius P Hemorrhage ((13:30 by
level + 30% bonus AD) per stack bleed, dot, cap 5, assumed 3.0) + Twitch P
Deadly Venom ((6/12/18/24/30 by level + 18% AP) per stack true poison, dot,
cap 6, assumed 3.0) + an UPGRADE to the already-seeded Orianna P (adds the
2:10 by level + 3% AP per-stack ramp it was missing; assumed 1.0). EXHAUSTED
scan: of the 15 no_damage P-forms with "per stack"+"damage" language only
these 4 are per-stack TARGET damage; the other 11 are stat STEROIDS
(Belveth/Garen/Irelia/Kayle/Samira/Senna/Sona/Volibear/Wukong gain
AS/MS/armor per stack) or stack-gain/damage-store mechanics (Mel/Smolder) -
documented inline, not seeded. The Kai'Sa 5th-stack-consume sub-term (15% + 6%
per 100 AP of MISSING health) is OMITTED: conditional (fires on the 5th stack)
AND inert at the default full-HP ctx (same precedent as Ekko W staged in 248).
STAYED STAGED (neither bilinear nor per-stack covers them): Brand P / Ekko W
(conditional + missing-HP) + Karma W f1 / Viego P (HEALS, not damage). +17
tests test_passive_damage_per_stack_item249.py (PerStackTerm fold math /
assumed_stacks=0 inert / registry shape / steroid forms not seeded /
default-OFF byte-identical / inject-on verbatim L11 values for the 4 / Orianna
upgrade differs from base-only). DEFAULT byte-identical: the full DS suite is
unchanged with apply_passive_damage at its False default.)

1.80.0 (item 248 / gap-plan - GAP-2 bilinear AP-on-HP passive schema lift +
4 SEEDED passives, default-OFF byte-identical. The AP-scaled %-of-HP passive
form ("X% (+ Y% per 100 AP) of the target's HP") is a PRODUCT of two ctx stats
(ctx[ap] * ctx[target_hp]) that no single linear _SCALING_TARGETS field
expresses - each field is one pct * one ctx attr. The lift adds
DamageBlock.bilinear_terms (a flat tuple of (factor, ctx_attr_a, ctx_attr_b)
summed as factor * ctx[a] * ctx[b] in ability_dps._evaluate_block, AFTER the
per-rank linear terms; default () = every existing block byte-identical) +
has_damage_scaling now True for a bilinear-only block + the
_passive_damage_overrides._per_100(pct, per_attr, of_attr) authoring helper
(factor = pct / 10000: /100 to turn pct into a fraction, /100 for the "per 100"
denominator). SEEDED from verbatim 16.11.1 effects_descriptions, all default-OFF
(the seam injects only under apply_passive_damage=True): Gwen P A Thousand Cuts
(1% + 0.55% per 100 AP target max HP, on-hit - the canonical case the lift was
built for, STAGED through item 247) + Aurora P Spirit Abjuration (2.5% + 2% per
100 AP max HP, 3rd-stack consume) + Lillia P Dream-Laden Bough (5% + 1.25% per
100 AP max HP dot) + Renata P Leverage (1%:2% level + 2% per 100 AP max HP,
first-hit per_fight). All four scale on target MAX HP (non-zero at the default
full-HP ctx, so not inert). STAYED STAGED (the bilinear lift does NOT cover
them): Kai'Sa P (the dominant per-application term is a Plasma-stack-count ramp;
its 5th-stack-consume bilinear sub-term is only part of the passive + fires
conditionally) + Brand P / Ekko W (bilinear term is conditional - ring
detonation / sub-30%-HP gate, and Ekko's is missing-HP-scaled = ~0 at full-HP
ctx) + Karma W f1 / Viego P (the bilinear term is a HEAL, not damage). +22 tests
test_passive_damage_bilinear_item248.py (per_100 conversion / bilinear-only
DamageBlock evaluation / has_damage_scaling / registry shape / default-OFF
byte-identical / inject-on verbatim values for the 4) + item-247 StagedAbsent
test split (Gwen now seeded, Kai'Sa stays staged). DEFAULT byte-identical: the
full DS suite is unchanged with apply_passive_damage at its False default.)

1.79.0 (item 247 / gap-plan Phase C2 - AA-empowerment amp seam in compute_dps.
The 5 base="aa" AmpEntry champs (Caitlyn W / Fiora E / Jayce W f1 / Sivir W /
Nidalee Q), registered item 239 but with NO consumer, are now wired into the
AA scorer: compute_dps gains apply_ability_amps (default False / byte-identical)
and, when True, _aa_amp_multiplier scales ONLY the base-AA component (item proc
DPS stays unamped) by the champ's amortized empowerment factor. Threaded
compute_dps -> _phase_weighted_dps -> _rotation_attack_dps (aa_empower_amp) + the
per-hit display values (avg_attack_dmg / raw_attack_dps); route-reachable via the
/dps server route (apply_ability_amps body param). rank_at_level is imported
function-level to avoid the dps <-> ability_dps cycle. FORWARD-MARKER: the 5
entries carry placeholder amp_per_rank=(0.0,) (and are conditional-with-no-
condition, so prob 0), so the seam is INERT today - it is wired + route-reachable
+ byte-identical, and Phase D authors the amortized per-champ value + flips
always_on / a condition per champ live. +8 tests test_aa_empower_seam_item247.py
(default byte-identical / forward-marker factor==1.0 / monkeypatched always_on
amp scales base-AA fully + AA-only scope vs a proc build / route wiring pin).)

1.78.0 (item 247 / gap-plan Phase C3 - GAP-2 exotic passive registry: 6 of 8
authored default-OFF in _passive_damage_overrides.py from verbatim 16.11.1
effects_descriptions. NEW additive schema: _step_per_level (3-tier even-thirds
level step for slash-notation "X / Y / Z based on level"); the PassiveDamageEntry
scaling fields widen to float | tuple (a per-level tuple rides target_max_hp_pct
/ total_ad_pct for a level-scaled coefficient); to_damage_block coerces either +
wires target_current_hp_pct. SEEDED: Aatrox P (4%:8% target max HP lerp), Jarvan
IV P (8% target current HP flat; min-20/cap-400 inert in champ band), Zed P
(6/8/10% target max HP step; below-50%-HP fire gate not modeled - magnitude is
gate-independent; breakpoints even-thirds estimate), Caitlyn P (60/90/120% AD
step; +crit-chance AD multiplier omitted = AA-crit seam), Ekko P (30:140 + 90% AP
lerp; every-3rd-stack cadence metadata-only), Gangplank P (50:250 + 100% bonus AD
TRUE over 2.5s dot; +2-per-1%-crit term omitted = crit seam). STAGED (own slice):
Gwen P (bilinear AP-on-HP needs a core evaluator term), Kai'Sa P (per-Plasma-stack
ramp needs a stack-count runtime decision). DEFAULT BYTE-IDENTICAL: the seam only
injects under apply_passive_damage=True; the 6 new P forms stay no_damage with the
flag OFF. +31 tests test_passive_damage_exotic_item247.py.)

1.77.0 (item 246 / gap-plan Phase C1 - staged-amp block-index routing for
Hwei Q f2, gated under apply_ability_amps; default byte-identical. The two
STAGED damage_amp_self candidates whose "Maximum ..." block already models the
charged / isolated ceiling are reconciled by ROUTING the block-index (never an
amp, which would double-count the value the block holds): (a) Sion Q was already
resolved before this seam - champion_block_index.json {Q:2} selects its "Maximum
Physical Damage" block by default (the s191 routing predates the Gap-1 amp
analysis), so its STAGED entry was removed and flag on/off is byte-identical;
(b) Hwei Q form2 Severing Bolt is now wired via the new _STAGED_AMP_BLOCK_ROUTES
in _ability_amp_overrides.py - under apply_ability_amps the block-index routes
to damage-block 1 "Maximum Damage" (the isolated / immobilized + max-missing-HP
ceiling, which Meraki pre-bakes flat == block0 * the "Maximum Damage Increase"
%, so NO separate Gap-2 missing-HP coefficient is needed - the route IS the
ceiling). compute_ability_dps consults _staged_amp_block_route_for ONLY when
apply_ability_amps=True, taking precedence over block_index_overrides for that
(champion, key, form) only; the default path is untouched. AurelionSol W stays
STAGED (cross-spell self-state seam, deferred to its own session). +16 tests
test_staged_amp_block_route_item246; existing test_ability_amp_overrides green.)

1.76.0 (item 243 - non-coachable joke/anvil item deny-set in the rank pool.
rank.py _NON_COACHABLE_ITEM_IDS = {994403 Golden Spatula, 663064 Veigar's
Talisman of Ascension} skipped unconditionally in _filter_candidates, so they
are excluded from every mode + every scorer's candidate pool. Root cause:
DDragon mis-flags Golden Spatula maps['12']=True (ARAM) with a full all-stats
block, so the DPS scorer ranked it #2 in a live ARAM Varus build; item 213
stripped it from the curated champion_loadouts.json but the live rank pool
reads the DDragon maps flag directly. +7 tests test_non_coachable_deny_item243;
test_rank_mode_legality_p1l23's source-derived expected set now subtracts the
deny-set. Default behaviour unchanged for every build that does not contain
those two ids.)

1.75.0 (GAP findings - 3 opt-in / correction engine extensions; default path
byte-identical except the (a) correction):
(a) phantom-damage residual: _ability_overrides.NON_DAMAGE_BLOCKS +2 entries
    (DrMundo E / Twitch R). block[0] is a self-AD grant / steroid the Meraki
    extractor mislabeled attribute_kind="damage" (the name contains "Damage");
    flipped to "other" so no damage consumer sums it (DrMundo E falls to the
    real block[1]/[2]; Twitch R is an AA-empower so its cast damage is 0).
    Mel R left to its block-index route (block[0] is not default-selected).
    A correction (changes those 2 forms' DPS), not an opt-in flag.
(b) ability self-damage-amp registry (_ability_amp_overrides.py): opt-in
    compute_ability_dps(apply_ability_amps=False) seam (ability_dps.py post_amps
    line); ACTIVE Mordekaiser Q (isolation, verified) + Illaoi Q (always_on
    reference, live-inert) + 5 AA-empowerment entries (base="aa", inert here);
    AurelionSol W / Sion Q / Hwei Q f2 STAGED (cross-spell target / a "Maximum"
    block already models the ceiling). Default False -> byte-identical.
(c) effects-text-only passive-damage registry (_passive_damage_overrides.py):
    opt-in AbilitiesSnapshot.load(apply_passive_damage=False) load-time synthetic
    -DamageBlock inject; 10 P-slot on-hit passives hand-authored from verbatim
    effects_descriptions (Ziggs/Lux/Orianna/Warwick/Akali/Khazix/Qiyana/Vex/
    Sona/Velkoz). Default False -> no block appended -> byte-identical. The
    on_hit -> AA-cadence default-flip is live-validation-gated (STAGED).
1.74.0 (item 238 - null-damage-type ability correction registry,
_ability_overrides.py: DAMAGE_TYPE_OVERRIDES 7 + NON_DAMAGE_BLOCKS 7, applied
at abilities.AbilitiesSnapshot.load via _apply_ability_overrides; corrects 27
null-damage-type forms' mitigation routing + flips 7 phantom self-buff/shield
blocks to "other"; single load-time hook -> all consumers see corrected forms).
1.73.0 (item 237 - bruiser cc_blended ranking + build-tenacity, the symmetric
completion of item 236. Item 236 made the TANK ranker (rank_items_by_ehp)
tenacity-aware under score_by="cc_blended", but the BRUISER scorer
(compute_hybrid + rank_items_by_hybrid) stayed tenacity-blind: it consumed
cc_blended_ehp for the displayed hybrid_score yet SORTED on PRE-cc blended_ehp,
so a tenacity item could not rise vs a CC comp (a real asymmetry). Fix:
compute_hybrid gains `apply_build_tenacity: bool = False` (threaded to its
compute_ehp call - makes the hybrid_score scalar tenacity-accurate);
rank_items_by_hybrid gains `score_by: str = "blended"` (default, byte-id) |
"cc_blended" (the delta_pct SORT key now divides the cc_blended-ehp delta by
the cc_blended baseline) + `apply_build_tenacity: Optional[bool] = None`
(tri-state: None -> ON for cc_blended / OFF for blended, mirroring item 236).
HybridRankedItem +cc_blended_ehp/+delta_cc_blended_ehp; HybridRankResult
+score_by. /rank-bruiser exposes score_by/apply_build_tenacity (400 on bad
score_by); /hybrid keeps the plain-bool apply_build_tenacity scalar (no sort).
DEFAULT score_by="blended" + tenacity OFF = BYTE-IDENTICAL to 1.72.0 (full DS
suite unchanged; proven Sett vs ["Ashe"] Wit's End blended #24 -> cc_blended
#21, Sterak's #20 -> #19). Same honest nuance as item 236: tenacity re-ranks
ONLY vs a non-saturating CC comp (the 6s fraction cap). +11 tests
test_bruiser_cc_blended_item237.py. With this the cc_blended/tenacity arc is
COMPLETE - both the tank + bruiser cc_blended scorers are tenacity-aware.)
1.72.0 (item 236 - opt-in CC-adjusted (cc_blended) EHP ranking mode + the
item-tenacity layer that makes it real. The item-235 enemies/include_conditional
wire surfaced the cc_blended_ehp DISCOUNT on /ehp+/hybrid+/rank-bruiser, but the
discount is a per-enemy-comp UNIFORM scale (it credits no caster build attribute),
so a cc_blended SORT would be ORDER-INERT - it cannot re-rank items. Fix: a NEW
item-tenacity layer makes the discount build-DEPENDENT. `rank_items_by_ehp` gains
`score_by: str = "blended"` (default, byte-identical PRE-cc delta) | "cc_blended"
(ranks on the enemy-CC-lockdown-adjusted delta) + `enemy_champions` +
`include_conditional` (re-added here as a LIVE consumer, unlike item 235 which
reverted them as inert on the blended ranker) + `apply_build_tenacity:
Optional[bool]=None` (tri-state: None -> ON for cc_blended / OFF for blended;
explicit bool overrides). `EhpRankedItem` gains `cc_blended_ehp` +
`delta_cc_blended_ehp` fields; `EhpRankResult` gains `score_by`. NEW
`_item_tenacity.py` per-item tenacity registry (17 items, description-parsed -
DDragon stats strip tenacity exactly like ability haste; Anathema's enemy-debuff
+ Silvermere active + Elixir consumable EXCLUDED) + `total_item_tenacity` (League
MULTIPLICATIVE stacking 1-prod(1-t)). `compute_ehp` gains `apply_build_tenacity:
bool=False`: when True it scales the enemy CC the caster eats by (1 - build
tenacity) via the existing `effective_cc_duration` seam BEFORE the 6s-cap
fraction, so a tenacity item (Sterak's/Mercury's) shrinks its own lockdown ->
larger cc_blended_ehp -> rises under cc_blended scoring (VS a non-saturating CC
comp; an ultra-heavy comp still saturates the 6s cap so no tenacity helps -
correct). /rank-tank route exposes score_by/enemies/include_conditional/
apply_build_tenacity (400 on bad score_by). DEFAULT score_by="blended" +
apply_build_tenacity OFF = BYTE-IDENTICAL to 1.71.0 (full DS suite unchanged;
proven Malphite vs ["Ashe"] Sterak's blended #5 -> cc_blended #2). +14 tests
test_cc_blended_ranking_item236.py.)
1.71.0 (item 235 - self-audit wiring + parameterize pass. The 6 opt-in scoring
flags shipped across items 231-234 (apply_mode_modifiers / gate_ammo /
apply_ability_haste / aoe_targets_hit) + the cc_blended-EHP enemy context
(enemy_champions / include_conditional) reached ZERO :8893 route, so no live
caller could exercise them. This pass threads them end-to-end - leaf compute_*
fns already accepted them; the rank_* wrappers + the routes now do too - all
OPT-IN, DEFAULT byte-identical to 1.70.0 (proven: full DS suite unchanged at
the defaults). Specifically: `apply_mode_modifiers` -> rank_items / +/dps,
rank_items_by_ehp / +/rank-tank, compute_hybrid + rank_items_by_hybrid /
+/hybrid +/rank-bruiser, beam_search_build / +/beam, compute_dps_curve,
compute_fight_report (phys-dps section); `aoe_targets_hit` -> rank_items_by_burst
/ +/rank-assassin +/burst; `gate_ammo` + `apply_ability_haste` ->
compute_fight_report / +/v2/fight-report -> mana_sim; `enemy_champions` (NEW
route arg `enemies`) + `include_conditional` -> /ehp +/hybrid +/rank-bruiser
so the item-137/143 cc_blended_ehp discount is finally reachable from a route.
include_conditional was REVERTED from rank_items_by_ehp / +/rank-tank - the EHP
ranker deltas on blended_ehp (PRE-cc) + EhpRankedItem has no cc field, so it was
inert there (kept honest, not shipped as a no-op param). DRY: NEW shared
`_item_ability_haste.effective_cooldown(base_cd, ah)` (Riot base/(1+AH/100) with
the 0.01 denom floor) - the canonical single-source for the haste-CDR formula;
`ability_dps._effective_ability_cd` + `mana_sim` now delegate to it (was
re-implemented inline in each). `total_item_ability_haste` now delegates per-item
to `item_ability_haste` (wired the previously no-consumer single-item accessor).
NEW behavior-neutral GET /modifier-summary diagnostic route surfaces
`modifier_blocks.summarize_modifiers` over the live AbilitiesSnapshot (the
deliberate additive substrate's intended coach surface) - reads only, touches no
DPS/EHP number. +23 wiring tests (test_flag_wiring_item235.py).)
1.70.0 (DS V2 - item 234 mana_sim opt-in ability-haste / CDR model + static-CD
honest no-consumer verdict. Gives the bounded rotation CDR-awareness +
resolves the item-233 static-CD blocker honestly. `compute_mana_bounded_combo`
NEW `apply_ability_haste: bool = False` (END of sig). False (DEFAULT) = raw
rank cooldowns, BYTE-IDENTICAL to 1.69.0. True = the build's item ability
haste (`_item_ability_haste.total_item_ability_haste` over the resolved item
list - the SAME hand-curated 16.x registry the live ability scorer uses)
reduces every cooldown-bearing slot in the WAIT-TO-READY clock via Riot's
canonical `base_cd / (1 + ability_haste / 100)`, applied UNIFORMLY to BOTH the
bounded + unbounded reference passes so the shared wall-clock denominator
stays consistent (bounded_dps <= unbounded_dps holds). A faster rotation
accrues less regen between casts so haste can also bind the mana gate earlier.
Haste only BINDS on a cooldown-REPEATING sequence (a single-cast Q-AA-W-E-R
combo is cast-time-bound, not cooldown-bound, so haste is moot there); on a
repeating sequence (e.g. Lux Q-AA-Q-AA-Q at 35 AH) cooldowns x 0.741 ->
duration 18.25 -> 13.58s -> bounded_dps 56.02 -> 75.27. A no-haste build
(ability_haste==0) is byte-identical with the flag on. STATIC-CD HONEST
VERDICT: the item-233 staged `ability_static_cd` bucket is NOT used to exempt
haste-immune slots - its QWER active-slot coverage is only 3 abilities (Amumu
Q / Heimerdinger R / Samira R) with a clear mislabel (Amumu Bandage Toss
scales with haste in-game), too unreliable to gate CDR, and a burst rotation's
spells all scale with haste regardless. Haste is applied UNIFORMLY. Every
default path byte-identical to 1.69.0.)
1.69.0 (DS V2 - item 233 missile travel-time bucket + rune target_hp tags +
burst role + static-CD accessor. Continues item 225's owed-bucket wiring; all
OPT-IN / additive / byte-identical at default. (A) MISSILE -> NEW missile.py
(spell_travel_time = distance / missile_speed; speed bands gate the MIX:
<400 dash/melee/on-hit artifact -> None, >=5000 instant/global -> 0.0, else a
real projectile; _distance_from_geometry rejects the cone_distance=100.0 /
0.0 CDragon placeholder sentinels + a <200 cast_radius floor, falling to
_DEFAULT_DISTANCE=1000 so the travel-time is never the 100-sentinel garbage -
most slots resolve at the default reference, real cast_radius like Lux E 295
gives an exact value). Consumed by fight_report's NEW 7th MISSILE section
(per-projectile-slot travel-time; APPROXIMATE - default-distance-dominated).
spell_missile_speed accessor added to data_loader (item 233 foundation).
(B) RUNE target_hp tags -> rune_procs.py Cut Down 8017 (target_hp_above) +
Coup de Grace 8014 (target_hp_below) condition tags as METADATA; keystone_amp
keeps the 1.08 amp UNCONDITIONAL (the burst-window approximation - a burst
spans >60% open to <40% execute so both gates are met within the window; a
single target_hp_pct snapshot would be LESS accurate for a burst). target_hp_pct
kwarg added to keystone_amp + compute_rune_proc_damage for forward-compat
parity. Byte-identical (registry 19). (C) BURST role -> burst.py derives caster
role from champion attackrange (>350 = ranged) + threads role + target_hp_pct
into the rune calls (Lethal Tempo 8008 ranged 6-24 vs melee 9-30 now correct);
only changes an explicit runes=[8008] call on a ranged champ - the live /rank
passes no runes so it is unaffected. (D) STATIC-CD -> data_loader
ability_static_cd accessor (wiki static, name-keyed); DATA-STAGED honest
no-consumer - the live cooldown model has no ability-haste layer to gate
against + the wiki static is a MIX of numbers/toggles/formulas. (E) DEFAULT-ON
FLIP assessment (gate_ammo / apply_mode_modifiers / aoe_targets_hit): all THREE
stay default-OFF - each re-ranks live output (mana_bounded_dps / Arena base
stats + urf-mode mults / AoE-shaped burst) and needs live-game validation
before a flip; operator-gated, not flipped this run. Every default path
byte-identical to 1.68.0.)
1.68.0 (DS V2 - item 232 4-bucket sidecar consume + rune proc-signature lift.
Wires 3 of item 225's remaining owed sidecar buckets + lifts the rune model,
all OPT-IN / BYTE-IDENTICAL at default (mirrors the gate_ammo/runes=None
precedent). Foundation: DataSnapshot loads wiki_ability_stats.json + 3 new
accessors spell_geometry / ability_recharge / mode_modifier (pure reads).
(A) GEOMETRY -> NEW geometry.py (classify_spell_shape / is_aoe_shape /
aoe_multiplier / spell_aoe_multiplier; _AOE_TARGET_CAP=5). burst.py gains
aoe_targets_hit: int = 1 (END of sig); an AoE-shaped ability (line/cone/
circle per the cdragon geometry bucket) hitting N targets scales x min(N, cap)
- default targets_hit=1 -> x1 -> byte-identical (the guard skips the call).
(B) RECHARGE -> NEW recharge_ledger.py (compute_recharge_ledger: time-step
charge-availability over a fight window; cdragon ammo recharge primary,
wiki ability_recharge supplementary fallback). Consumed by fight_report's
NEW recharge section (6th substrate section; charge-availability per slot
over a fight window). (C) MODE_MODIFIERS -> dps.py + ehp.py +
engine.py opt-in apply_mode_modifiers: bool = False (END of compute_dps /
compute_ehp sig). True applies the wiki mode_modifiers - dmg_dealt/dmg_taken
MULTIPLIERS for urf/ofa/usb/nb (dps/ehp; ARAM keeps its legacy lolmath path,
no double-count) + the ar(Arena)/swift hp_lvl/dam_lvl/arm_lvl/as_lvl/hp_base/
arm_base ADDEND stat-growth overrides (engine._scale_champion_base via
_resolve_mode_addends + _ADDEND_AXIS_MAP; build_champion threads the flag).
Arena re-ranks ONLY when the flag is True (operator-gated flip). ms_mod /
total_as axes intentionally unmapped (no clean growth-rule target). (D) RUNE
PROC-SIGNATURE LIFT -> rune_procs.py: RuneProc gains condition: str =
"unconditional"; compute_rune_proc_damage + keystone_amp gain caster_hp_pct=
1.0 / game_time_s=0.0 / role="melee" / bonus_as=0.0 kwargs (byte-identical
defaults). Ships the 3 item-231 honest-exclusion gated runes EXPRESSIBLY:
Last Stand 8299 (stacking_amp caster_hp_below; amp 1.0 at full HP -> byte-
identical, ramps 1.05->1.11 as caster hp 0.60->0.30), Absolute Focus 8233 +
Gathering Storm 8236 (adaptive stat grants, EXCLUDED from burst total like
Conqueror -> byte-identical burst, expressible via fight_report). Lethal
Tempo 8008 gains role (melee 9-30 default byte-identical; ranged 6-24) +
bonus_as amp. Registry 16 -> 19. burst.py + fight_report.py thread
caster_hp_pct + game_time_s into the rune calls (default full-HP/time-0 ->
byte-identical; fight_report reports the context-gated amp). 8139 (heal) +
8446 (tower) remain honest exclusions. Every default path byte-identical to
1.67.0.)
1.67.0 (DS V2 - 2 disjoint slices + rune-expansion verdict. (A) wire item
225's `ammo` charge sidecar bucket (data/daemon_slayer/<patch>/
cdragon_spell_stats.json) into mana_sim behind an OPTIONAL gate_ammo flag -
BYTE-IDENTICAL when omitted (gate_ammo=False, the default, tracks no charges
at all; mirrors the runes=None opt-in precedent). When gate_ammo=True the
bounded rotation layers a per-slot charge ledger over the bounded pass only:
a cast of a charge-bearing slot consumes 1 charge, charges recharge over the
clock at recharge[rank] s/charge capped at max[rank], a 0-charge cast is gated
status="no_ammo" (same skip shape as "oom" - zero damage / no spend / no clock
advance / cooldown not consumed). The unbounded reference pass is never ammo-
gated so the bounded_dps denominator stays the full V1-parity rotation. Slots
with ammo==null + manaless/energy champs are completely unaffected. New
DataSnapshot.cdragon_spell_stats field + spell_ammo(champ, slot) accessor
(absent file -> {} -> byte-identical). Closes 1 of item 225's 6 owed sidecar
buckets. (B) rune_procs - resolve the "expand per_attack if DDragon exposes
them" NEXT honestly: the DDragon 16.11.1 well is DRY (16 runes modeled + Fleet
Footwork excluded; every remaining damage/amp rune is caster-state-gated /
game-time-gated / sustain / utility / stat-stack / tower-only). Last Stand
8299 documented as an HONEST EXCLUSION (caster-hp<60% amp; modeling it
unconditionally best-case 1.11x would inflate every burst for a caster-state
the burst-MAX scorer almost never represents, unlike the target-hp-gated Cut
Down 8017 / Coup de Grace 8014 siblings a burst window routinely meets) +
Absolute Focus 8233 / Gathering Storm 8236 (stat grants, not proc damage) +
Taste of Blood 8139 / Demolish 8446. 0 net-new runes; registry unchanged.
Additive: every default path is byte-identical to 1.66.0.)
1.66.0 (DS V2 - 3 disjoint slices. (A) rune_procs 14 -> 16: add the two
per_attack damage runes Hail of Blades 9923 (TRUE 4-20 by level + 0.08 bonus
AD + 0.06 AP, additive, CD 10s) and Lethal Tempo 8008 (flat adaptive 9-30 by
level, melee 100%-effective at max stacks; ranged 6-24 and the +1%-per-1%-
bonus-AS amp NOT modeled - no role flag / no bonus-AS in the proc signature,
mirrors the Grasp melee-modeled precedent). Fleet Footwork 8021 is an HONEST
EXCLUSION (heal + move-speed sustain only, no damage; modeling it as a damage
rune would invent numbers) - documented alongside the Aery-shield / Grasp-heal
exclusions. All DDragon 16.11.1 runesReforged.json longDesc verbatim.
(B) scenario_matrix: 2 new metrics mana_bounded_dps (-> mana_sim
compute_mana_bounded_combo.bounded_dps) and rune_burst (-> burst
compute_burst_damage(runes=...).total_burst_damage); still a HARNESS over
existing scorers, no new math; the existing dps/burst/combo metrics are
byte-identical (new sequence/runes params default None). (C) wire an OPTIONAL
runes param into rank_items_by_burst + the live /rank-assassin route -
BYTE-IDENTICAL when omitted (runes=None threads None into both
compute_burst_damage calls); the live assassin ranking only re-ranks when a
caller passes runes in the request body. Additive: every default path is
byte-identical to 1.65.0.)
1.65.0 (DS V2 S2/S3/S4 - wire the rune_procs proc/amp layer into the burst +
combo scorers behind an OPTIONAL runes param. BYTE-IDENTICAL when omitted
(rune_proc_damage=0.0, total_burst_damage unchanged); when a runes list is
passed, on_proc_burst/per_attack/stacking_amp procs add to the total and a
stacking-amp keystone (Press the Attack 1.08, First Strike 1.07) multiplies
the ability+AA base. Conqueror (adaptive stat-stack) is EXCLUDED from the
damage total by design. Expand rune_procs 8 -> 14 (Summon Aery 8214 / Grasp
8437 / Aftershock 8439 / First Strike 8369 / Coup de Grace 8014 / Cut Down
8017 - all DDragon 16.11.1 verbatim; the brief crossed 8014/8299 ids, DDragon
won). NEW fight_report.py unified V2 report composing mana_sim + rune_procs +
self_shred + ability_hps + scenario_matrix, served at POST /v2/fight-report.
Additive: every existing scorer is byte-identical without runes.)
1.64.0 (DS V2 - wire ability_hps v2 into the live enchanter HPS scorer:
compute_hps now folds champion-spell heal/shield throughput
(total_ability_hps) into total_throughput, re-ranking enchanter builds.
Byte-identical for champions with no ability heal/shield blocks. Mana
uptime gates the ability cast cadence (real finite-mana usage). Additive
substrate (mana_sim/rune_procs/self_shred/scenario_matrix) stays unwired.)
1.62.0 (item 213 - ranged-marksman off-class item pollution filter.
The DPS scorer (rank.rank_items) ranked every purchasable mode-legal
item by raw DPS delta, surfacing melee-bruiser / tank / skirmisher
items (Trinity Force, Heartsteel, Bastionbreaker, Umbral Glaive,
Sundered Sky, Black Cleaver, ...) high for ranged ADCs because they add
big raw AD / AS / Health - items the operator never plays on a Caitlyn /
Jinx / Ezreal class champion. NEW consumer-side filter: when the champion
is a ranged marksman (Marksman tag + attackrange >= 500) the DPS candidate
pool drops the OFFCLASS_MARKSMAN_ITEM_NAMES deny-set (by NAME - alias-proof
vs the Arena 22/32/44/66-prefixed mirror ids, patch-stable). Gate fires
ONLY through the DPS scorer (carry / dps / adc archetypes) so mages
(mage scorer) and melee fighters / tanks (not ranged marksmen) are
untouched - no over-filter regression. Data-driven, NOT per-champion:
the gate is the snapshot's own champion record. Default ranking math
for every non-ranged-marksman champion is BYTE-IDENTICAL to 1.61.0.)

1.61.0 (cc_conditional wave 23 - Hecarim R Onslaught of Shadows
distance-gated fear SHIPPED via the wave 18 coexists_with_unconditional
same-slot-coexistence schema (Maokai R precedent). SECOND consumer of
the wave 7 forward-marker COND_RANGE_GATED tag.

Re-audit of operator-gated REJECT carries from items 178-201 against
the FULL ENGINE 1.60.0 schema (cast_time + effects_descriptions +
parent_resource + notes + damage_blocks). The audit subagent surfaced
Hecarim R as the canonical range-gated fear payload that prior waves
had not matched against the COND_RANGE_GATED tag. The
effects_descriptions[1] "fears nearby enemies for 0.75 : 1.5 (based
on distance traveled) seconds" is the textbook range-gated CC payload
pattern; Maokai R wave 18 was the FIRST consumer (range-gated root),
Hecarim R wave 23 is the SECOND (range-gated fear).

REGISTRY ADDS: +1 primary entry / +1 net-new champion (Hecarim).
Registry: 71 entries / 56 champs -> 72 entries / 57 champs (62
primary + 8 sidecar -> 63 primary + 8 sidecar). Tag count unchanged
at 13. COND_RANGE_GATED consumer count: 1 -> 2.

Hecarim R mechanism:
  * Active: Hecarim dashes with displacement immunity to target
    location, summoning 5 spectral riders in an arrow formation
    that charge alongside him.
  * Upon arrival: AoE magic damage + range-gated fear + range-
    gated slow on nearby enemies. Per Meraki effects_descriptions[1]:
    "Upon arrival, he fears nearby enemies for 0.75 : 1.5 (based on
    distance traveled) seconds and slows them by 0% : 99% (based on
    distance from Hecarim)."
  * Distance-traveled values:
    - Short-range dash (close to original position): 0.75s fear
    - Mid-range dash: ~1.0s fear (the unconditional baseline value)
    - Long-range dash (max ride): 1.5s fear (the cc_conditional value)

Encoding choice:
  * cc_kind=fear (the 0.75-1.5s fear is the primary CC payload;
    the 0-99% slow is a separate utility payload not registered
    here per the slow-without-damage rule).
  * durations_s=(1.5, 1.5, 1.5) - 1.5s flat per R rank at the
    max-distance band; R rank only scales the dash range + the
    spectral rider damage, NOT the fear cap.
  * condition=COND_RANGE_GATED - SECOND consumer of the wave 7
    forward-marker tag (Maokai R wave 18 was the FIRST). The
    range-gated payload pattern (duration scales on distance
    traveled) is the canonical match for this tag.
  * probability=0.4 (tag midpoint matching Maokai R precedent;
    mid-low reflecting that the operator must commit to a long-
    distance ride to reach the 1.5s far band).
  * coexists_with_unconditional=True - declares same-slot
    coexistence with the unconditional `_PER_SPELL_CC_DURATIONS
    ["Hecarim"]["R"] = (1.0, 1.0, 1.0)` baseline entry. Consumer
    math: include_conditional=True the MAX rule credits the
    larger of unconditional 1.0s or conditional 1.5 * 0.4 = 0.6s
    default; default calibration keeps unconditional 1.0s as the
    credited value. Operator tunes Hecarim:R above 0.667 to flip.

Math preservation: default
compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL
to ENGINE 1.60.0 for ALL champions (the wave 23 path skips when
the flag is False; unconditional 1.0s R fear unchanged for
Hecarim). include_conditional=True at default 0.4 probability
keeps the unconditional 1.0s winning via MAX-rule; only operator
override above 0.667 flips the conditional above the
unconditional.

REJECT verdicts wave 23 (audit subagent full report; cross-
checked against `data/daemon_slayer/16.10.1/champion_abilities.json`):
  * Jhin W Deadly Flourish "roots them for a duration" - duration
    lacks explicit numeric value. REJECT (cannot pin durations_s
    without verified cast-time or per-rank spec).
  * Anivia Q recast shatter stun "stun them for a duration" -
    duration lacks explicit numeric value. REJECT.
  * Heimerdinger E center-of-impact 1.5s stun - center-of-impact
    spatial differentiation is NOT a tactical condition (no nth_hit
    marker, no mark application, no terrain requirement). REJECT
    for conditional registry; if first-order, belongs in
    `_PER_SPELL_CC_DURATIONS`.
  * Lillia R Dream Mist 1.5s drowsy on Dream Dust mark - the
    COND_DREAM_STACK forward-marker tag remains empty-registry;
    Lillia passive multi-mark mechanics are parse-stripped in
    damage_blocks-only format; cannot verify multi-stack payoff
    explicitly. REJECT pending Meraki schema lift for Dream Stack
    interactions.
  * Lissandra W root + R stun "stunned for 1.5 seconds" - both
    are UNCONDITIONAL first-order CC (no gating condition). Belong
    in `_PER_SPELL_CC_DURATIONS`. REJECT for conditional registry.
  * Leona R epicenter stun - epicenter is spatial (impact zone),
    NOT a tactical condition. REJECT.
  * Jinx E knockdown + root - UNCONDITIONAL knockdown/root on
    champion contact. Belongs in `_PER_SPELL_CC_DURATIONS`. REJECT
    for conditional registry.

1.60.0 (cc_conditional wave 22 - Rell W form 1 Ferromancy: Mount Up
empowered-AA stun SHIPPED via the wave 14 cast_time + wave 20 notes
schema lifts. Operator-granted authority item 199 Slice B (full
allow + commit + push + recommended-option-always).

Re-audit of operator-gated REJECT carries from items 178-198 against
the FULL ENGINE 1.59.0 schema (cast_time + effects_descriptions +
parent_resource + notes + damage_blocks). The candidate was the
explicit item 198 carry (i) "Rell W form 1 cc_conditional candidate
STILL operator-decision-gated" - the wave 15 REJECT carry pending
operator clarification on form-transition empowered-AA semantics.

Fleet-wide audit verified saturation on the parse-strip CC-attribute
damage_blocks lane: all 28 candidate spells with explicit Stun /
Root / Fear / Silence / Taunt / Charm / Knockup / Snare / Disable
Duration damage_blocks (Ahri E / Anivia Q / Braum R / Chogath QW /
Elise E / Fiddlesticks Q / Gnar R / Ivern Q / Jhin W / Lissandra
RW / Lulu RW / Malzahar QR / Maokai RW / Mel E / Morgana Q /
Nautilus QR / Nocturne E / Poppy E / Rakan RW / Rammus E / Senna W /
Seraphine R / Shaco W / Soraka E / Tristana R / Veigar E / Volibear
E / Zyra E) are ALREADY in `_PER_SPELL_CC_DURATIONS` unconditional
registry; this lane is fully saturated and the cc_conditional
growth requires sidecar / form-explicit / state-tracking entries.

REGISTRY ADDS: +1 sidecar entry / 0 net-new champions. Rell W form
1 lands in the sidecar registry alongside the wave 15 Rell W form 0
entry on the same (Rell, W) slot via the form_index discriminator.
This is the FOURTH same-spell-slot multi-form-coexistence in the
sidecar registry after Karma W form 0+1 (wave 1+10), Hwei E form
0+1+2 (wave 9+10), Sylas E form 0+1 (wave 12). Registry: 70
entries / 56 champs -> 71 entries / 56 champs (62 primary + 7
sidecar -> 62 primary + 8 sidecar). Tag count unchanged at 13.

Rell W form 1 Mount Up empowered-AA mechanism:
  * Form 0 cast (wave 15 entry) -> Mounted -> Dismounted transform
    + leap + arrival stun 0.8s.
  * Form 1 RECAST within 3.5s of form 0 -> Dismounted -> Mounted
    transform + empowers next basic attack within 3.5s with 0.2s
    cast_time + 100 bonus AA range + 40% bonus AS.
  * Empowered AA charge-arrival or collision -> stuns target 0.6s
    flat + flings 150 units over Rell over 0.4s.
  * Per Meraki effects_descriptions[0] for form_index=1: "Upon
    arrival or collision, she deals bonus magic damage, stuns the
    target for 0.6 seconds, and flings them 150 units over
    herself, though not through terrain, over 0.4 seconds."
  * Cast_time pinned by Meraki schema lift: form 1 = 0.25s cast
    for the W recast itself; empowered AA charge = 0.2s cast.

Encoding choice:
  * cc_kind=stun (0.6s primary CC payload; 0.4s fling is a
    separate displacement not registered, mirroring form 0's
    exclusion of its own 0.4s knockup).
  * durations_s=(0.6,) single-element tuple - 0.6s flat across
    all 5 W ranks (the stun does NOT scale with W rank; only
    the cast cooldown + Mount Up shield-conversion scale).
  * condition=COND_CHANNEL_COMPLETION - the 2-cast cycle (form
    0 -> form 1 within 3.5s) + empowered-AA charge-delivery
    sequence is functionally a multi-step channel. The stun
    fires ONLY on charge-arrival completion. Pattern parallel to
    Sylas E form 1 Abduct (2-cast cycle, wave 12) + Hwei E form
    1 Grim Visage (2-cast cycle, wave 9).
  * probability=0.4 (mid-low, mirroring Sylas E + Hwei E form 1
    - 2-input setup is reliable in Rell combo cadence but the
    charged AA is dodgeable; the 3.5s form 1 + 3.5s AA window
    is generous but operator-gated since the empowered AA can
    be denied by knockup / dash / hard CC on Rell mid-charge).
  * form_index=1 (sidecar registry slot).

Math preservation: default
compute_cc_pressure(include_conditional=False) is BYTE-IDENTICAL
to ENGINE 1.59.0 for ALL champions (the wave 22 path skips when
the flag is False). include_conditional=True callers receive
+0.24s (0.6 * 0.4) NEW conditional pressure on top of the wave
15 form 0 0.4s (0.8 * 0.5) = total Rell W conditional 0.64s.

Schema preservation: pure-additive on the cc_conditional sidecar
registry. No new condition tag introduced. The wave 14 cast_time
schema lift + wave 20 notes field schema lift are both used
(cast_time confirms 0.25s form 1 + 0.2s charge AA; notes field
adds the "ranged version" + "instant melee version" interaction
clauses; effects_descriptions field carries the 0.6s stun value
verbatim).

REJECT verdicts wave 22 (cross-checked against full schema):
  - Renekton W Fury (REJECT-confirmed: already shipped wave 9
    primary registry COND_FRENZY_STATE 1.5s).
  - Karma W form 1 Mantra (REJECT-confirmed: already shipped
    wave 10 sidecar registry COND_FRENZY_STATE).
  - Hwei E form 1 Grim Visage (REJECT-confirmed: already shipped
    wave 9 primary registry COND_CHANNEL_COMPLETION).
  - Hwei E form 2 Gaze of the Abyss (REJECT-confirmed: already
    shipped wave 10 sidecar registry COND_CHANNEL_COMPLETION).
  - Neeko E Empowered Root (REJECT-confirmed: the Empowered Root
    Duration block IS in the Meraki damage_blocks for form 0
    alongside base Root Duration, but Neeko E primary entry wave
    1 already covers the base root path; the empowered root is
    gated on Neeko's W-form-stack mechanic that requires a
    separate state-tracking schema lift not authorized this
    wave. CARRY).
  - Aatrox R post-passive (REJECT-confirmed: minion-only fear
    per items 150/153/156/177 schema-lift verification; not
    champion CC).
  - Volibear R Stormbringer (REJECT-confirmed: only Turret
    Disable Duration parsed in damage_blocks; turret-only NOT
    champion CC per items 150/153/156/177).
  - Briar W frenzy-empowered (REJECT-confirmed: only Bonus AS +
    Bonus MS parsed in damage_blocks; self-buff frenzy NOT
    champion CC per items 150/153/156/177).

Carries forward (wave 23+ operator-gated, all require state-
tracking schema lift beyond cast_time + effects_descriptions +
parent_resource + notes + damage_blocks):
  * Neeko E Empowered W-stack root (W-form-disguise stack
    mechanic state-tracking).
  * Renekton W base stun unconditional (could move to
    _PER_SPELL_CC_DURATIONS coexists pattern but operator-gated).
  * 28 unconditional CC carries flagged in audit (the 28-spell
    unconditional-CC saturation list above is operator-gated for
    a separate _PER_SPELL_CC_DURATIONS-expansion wave).
  * Cherry / Arena augment-empowered champion-CC entries
    (Arena-mode-gated; needs COND_MODE_GATED + per-augment
    state-tracking schema lift), 2026-05-25):

1.59.0 (cc_conditional wave 21 - Xin Zhao Q + R re-audit closures
via the wave 20 `notes` field schema lift. The wave 21 re-audit
applied the orchestrator-brief "re-audit ALL prior-wave REJECT
carries against the new `notes` field" methodology. Full-fleet
scan: 916 forms with non-null notes (98.8% coverage from 1.58.0);
CC-verb + condition-gate regex over post-boilerplate-stripped
notes text yielded 190 matches; registry-membership filter
against `_PER_SPELL_CC_DURATIONS` + cc_conditional primary +
sidecar registries reduced to 113 candidates; triage of the top
40 against full effects_descriptions + notes content yielded
TWO valid ship candidates - both on Xin Zhao, neither of which
the wave 0-20 registry covered.

REGISTRY ADDS: +2 primary entries / +1 net-new champion. Xin
Zhao becomes the 56th cc_conditional champion + enters with
BOTH Q and R simultaneously (rare 2-slot entry in a single wave,
parallel to wave 13 Aphelios Q form 3 + wave 18 Briar R single-
wave entries). Registry: 68 entries / 55 champs -> 70 entries /
56 champs (60 primary + 7 sidecar -> 62 primary + 7 sidecar).
Tag count unchanged at 13.

(1) Xin Zhao Q Three Talon Strike 3rd-hit knockup 0.75s flat
    across all 5 Q ranks. COND_NTH_HIT (prob 0.7 tag midpoint).
    The COND_NTH_HIT tag's own docstring in cc_conditional.py
    (line 190) EXPLICITLY named "Xin Zhao Q 3rd-attack knockup"
    as the canonical motivating example for the tag, yet through
    waves 0-20 the entry was never added. Wave 21 closes the
    gap.

(2) Xin Zhao R Crescent Sweep target-NOT-Challenged stun 0.75s
    flat across all 3 R ranks. COND_TARGET_DEBUFFED (prob 0.5
    tag midpoint) with INVERSE semantic - stun fires ONLY on
    targets that are NOT currently marked Challenged. SECOND
    INVERSE-gated COND_TARGET_DEBUFFED entry after Briar R wave
    18 (non-marked-enemy fear). CORRECTS a wave 15 REJECT carry
    where the audit caught the knockback displacement and
    dismissed the entry as 'not in cc_conditional CC kind
    schema' - that was a misread (knockback IS in the schema
    AND the same gate fires a stun alongside). The wave 20
    schema-lifted notes field confirms the stun is a distinct
    CC payload via 'Displacement immunity will also resist the
    application of the stun' (the notes field is the canonical
    home for spell-shield + displ-imm interaction clauses on
    real CC payloads).

REJECT verdicts wave 21 (after triaging top 40 candidates from
the 113-after-registry-filter pool; full audit report in
`agents/daemon_slayer/docs/WAVE_21_AUDIT_NOTES.md`):
  - Blitzcrank E, Darius E, Poppy W, Poppy R, Rammus Q,
    Sett R, Skarner E, Trundle E, Vel'Koz E, Viego R, Yorick W:
    UNCONDITIONAL CC payloads belonging in
    `_PER_SPELL_CC_DURATIONS` not cc_conditional. CARRY to a
    future _PER_SPELL_CC_DURATIONS expansion wave; operator-
    gated since the unconditional registry already covers ~89
    champs and adding 11+ more is a separate scope decision.
  - LeeSin R: UNCONDITIONAL knockback + airborne primary + 1s
    knockup secondary. wave 13/14/15/16 REJECT carry. REJECT.
  - Akshan E, Aphelios Q form 2, Aurora R, Bard E, Bel'Veth E,
    Briar W form 1, Caitlyn E, Camille R, Kha'Zix Q, Olaf R,
    Pyke R, Rek'Sai E form 1, Rumble E, Samira P, Sylas R,
    Taliyah R, Tryndamere E, TwistedFate R, Twitch W, Urgot W,
    Vex R: notes wording mentions CC verbs in non-CC context
    (cast-cancel clauses, self-CC during ability, interaction
    clauses, damage modifiers on debuffed targets). REJECT
    (false-positive on regex filter).
  - Rell W form 1: empowered-AA dash+stun gated on dismounted-
    state. CARRY to wave 22+ as operator-decision-gated entry
    (wave 15 docstring explicitly REJECT-noted "form-transition
    empowered-AA registration" semantic distinct from rage-
    meter / mantra-charge patterns).

Math preservation: default
compute_cc_pressure(include_conditional=False) is BYTE-
IDENTICAL to ENGINE 1.58.0 for ALL champions (the wave 21
path skips when the flag is False). include_conditional=True
callers receive +0.525s (Q 0.75 * 0.7) and +0.375s (R 0.75 *
0.5) = +0.9s expected conditional pressure for Xin Zhao on top
of the existing 1.0s unconditional W knockup.

Schema preservation: pure-additive on the cc_conditional
registry. The notes-field schema lift from ENGINE 1.58.0 was
the unblocking artifact (the notes field IS used as authoritative
evidence for "the stun" being a real CC payload on Xin Zhao R).
No new condition tag introduced. No sidecar entries added.
The 7 sidecar entries (Aphelios Q form 3, Gnar W form 1, Hwei
E form 2, Jayce E form 0, Karma W form 1, Rell W form 0,
Sylas E form 1) are unchanged, 2026-05-25):

1.58.0 (cc_conditional wave 20 - Meraki extractor `notes` field
schema lift + Vayne E Condemn terrain-collision stun SHIPPED.
Operator-gated decision from item 187 Slice D research note:
"RECOMMENDED `notes` field per spell form at
tools/daemon_slayer_abilities_extract.py:453-560. Pure-additive
parallel to cast_time/effects_descriptions/parent_resource.
Unblocks Kindred E + Diana P + Vayne P." Re-audit against fresh
Meraki bulk found the brief premise stale: Kindred E carries
only slow + damage (no hard CC); Diana P is pure AS bonus
(no CC at all); Vayne P is pure MS bonus (no CC at all).
All 3 REJECT under the lift. Vayne E Condemn surfaced as a
4th candidate during the audit: terrain-collision stun 1.5s
(flat across all 5 E ranks per Meraki effects_descriptions
"If the target collides with terrain, they take bonus
physical damage and become stunned for 1.5 seconds"). The
`notes` field adds nuance ("Condemn's stun duration starts
when Vayne's target collides with a wall (they can be
immobilized for up to 2 seconds depending on displacement
duration based on distance traveled)") confirming the 1.5s
is a fixed value with displacement-distance-scaled padding.
Vayne E gets `coexists_with_unconditional=True` because the
slot ALSO has the unconditional 0.5s knockback entry in
`_PER_SPELL_CC_DURATIONS` (the no-terrain miss path);
consumer MAX rule selects the larger of unconditional
post-tenacity (0.5s) or conditional post-tenacity
(1.5 * 0.3 = 0.45s default). Tag = COND_TERRAIN (prob 0.3)
- SECOND consumer of the wave 7 forward-marker tag after
Ornn E wave 15. Vayne becomes a NEW cc_conditional
champion. Registry growth: 67 entries / 54 champs ->
68 entries / 55 champs. Tag count UNCHANGED at 13. The
notes schema lift is FORWARD-MARKER infrastructure for
future consumers that need richer per-spell mechanical
caveats (spell-shield interactions, cast-cancel clauses,
untargetable-during-X notes). Default
`compute_cc_pressure(include_conditional=False)`
BYTE-IDENTICAL to 1.57.0 for ALL champions, 2026-05-25):

SCHEMA LIFT: tools/daemon_slayer_abilities_extract.py
NEW `_normalize_notes(raw) -> str | None` helper +
`notes: str | None = None` per-form record field threaded
through `_build_form(...)`. Pure-additive: damage-block
pipeline + effects_descriptions + cast_time +
parent_resource UNCHANGED. Re-extracted
data/daemon_slayer/16.10.1/champion_abilities.json at
1.58.0 schema (171 champs / 927 forms / 99.0% ok_rate;
916 / 927 forms with non-null notes = 98.8% coverage).
Byte-identical coverage shape vs 1.57.0; the new field
surfaces for first time without altering existing schema.

REGISTRY ADD: agents/daemon_slayer/cc_conditional.py
+1 primary entry registry.setdefault("Vayne", {})["E"] =
ConditionalCcEntry(... cc_kind="stun", durations_s=(1.5,) * 5,
condition=COND_TERRAIN, probability=_p("Vayne", "E", 0.3),
coexists_with_unconditional=True).
+0 sidecar entries. REGISTRY_TOTAL_ENTRIES bumps 67 -> 68,
REGISTRY_TOTAL_CHAMPIONS bumps 54 -> 55. Vayne joins
Ornn as a multi-slot cc_conditional champion eventually
(Ornn has Q wave 4 + E wave 15; Vayne starts with only
E wave 20). FIRST Vayne first-order CC registration
anywhere.

REJECT verdicts wave 20 (3 brief-named carries):
Kindred E Mounting Dread - effects: slow 30% for 1s,
3-stack pounce damage with missing-HP crit threshold.
NO hard CC. The 3rd stack is target-tag-stacking damage
only. REJECT.
Diana P Moonsilver Blade - effects: +15-35% bonus AS
scaling to 3x after ability cast. NO CC mechanic at all.
REJECT.
Vayne P Night Hunter - effects: +30 bonus MS while
facing a visible enemy champion. NO CC mechanic at all.
REJECT.

Brief deviation pattern matches item 187 + item 177
precedents (first-attempt-success + agent-self-correction).
The brief's 3 named candidates were all REJECT-verified at
the parse-strip + notes-lift level. Vayne E is the 4th
candidate that the audit surfaced as a genuine winner.
Future wave 21+ ship-candidates should re-audit prior
REJECT carries against the `notes` field for richer
mechanical caveats not in effects_descriptions
(operator-gated).

1.57.0 (Death's Dance Defy heal-on-takedown - SHIPPED via NEW
ItemHeal.takedown_gated schema field + _TAKEDOWN_RATE_PER_FIGHT
operator-tunable module constant. Closes the Phase 6 deliberate
omission "Death's Dance Defy heal (75% bonus AD on takedown over
2s) is DEFERRED to Phase 6.5: the takedown-rate assumption is
uncertain enough that a Phase 6 first-pass would over- or
under-credit it" pending since ENGINE 1.28.0 (2026-05-21,
Phase 6 heal pipeline). +2 ItemEffect promotions (SR 6333 +
Arena 226333) flipped from defensive_only -> heal contributors.
Default 1.56.0 byte-identical-EHP contract holds for every build
WITHOUT Death's Dance equipped. ENGINE 1.56.0 sites (CC pressure,
parent_resource lift) are byte-identical, 2026-05-25):

SCHEMA LIFT: agents/daemon_slayer/_effects_types.py
``ItemHeal`` gains optional ``takedown_gated: bool = False`` field.
When True, the consumer (``ehp._collect_heals``) multiplies the
resolved per-trigger magnitude by ``_TAKEDOWN_RATE_PER_FIGHT``
(operator-tunable module constant in ``ehp.py``, default 0.5)
before contributing to the heal pool. Backward-compat: all wave
1.28.0/1.29.0 ItemHeal entries omit the field and default to False;
their consumer semantics are byte-identical to ENGINE 1.56.0.
The math change is OPT-IN per item via the new flag.

CONSUMER WIRE: agents/daemon_slayer/ehp.py
``_collect_heals`` gains ``takedown_rate: float =
_TAKEDOWN_RATE_PER_FIGHT`` kwarg; when an ItemHeal's takedown_gated
is True, the resolved magnitude is multiplied by
``max(0.0, takedown_rate)`` before contributing to the totals.
Items without the flag (the 99% default case including Sundered
Sky) flow through unchanged. The constant lives in ``ehp.py``
(not in the dataclass) to mirror the Phase 6.5
``_MISSING_HP_SHARE_FOR_HEALS = 0.5`` precedent and the ENGINE
1.33.0 ``_CC_EFFECTIVENESS_FACTOR = 0.5`` precedent: operator-
tunable midpoint as a single module constant; do NOT vary
per-champion or per-mode (the calibration surface area beyond
what live data supports is a long-tail risk).

CONSTANT: agents/daemon_slayer/ehp.py
``_TAKEDOWN_RATE_PER_FIGHT = 0.5`` - "carry nets one takedown
every other fight on average". Calibration note: this is a
conservative midpoint that does NOT over-credit DD in passive
sidelane play and does NOT under-credit it in active teamfights.
Future per-role calibration via rewind_history.db role-by-role
analysis is operator-gated.

+2 ITEMEFFECT PROMOTIONS this engine bump:

(1) SR 6333 Death's Dance (Legendary, 3300g, 60 AD + 50 armor +
    15 ability haste). ItemHeal(bonus_ad_scaling=0.75,
    takedown_gated=True). Per Meraki 16.10.1 passive Defy: "If
    an enemy champion dies within 3 seconds of you damaging them,
    removes Ignore Pain's remaining stored damage and heals you
    for 75% bonus AD over 2 seconds". The Ignore Pain damage-
    storing piece is NOT modeled at the EHP layer (it shifts
    damage from instant -> 3s spread - a timing transform, not a
    magnitude reduction; the EHP scorer is a magnitude model;
    timing-shift damage smoothing is a separate axis intentionally
    out of scope here). Promoted from defensive_only -> heal
    contributor; the Meraki-verified 75% bonus AD coefficient is
    the authoritative source.

(2) Arena 226333 Death's Dance - mode mirror of SR 6333 with
    identical Defy schema. Arena fights are shorter (multi-round
    cycles) but the constant is mode-agnostic by design; mode-
    specific calibration can layer on top via a future per-mode
    override. Promoted from defensive_only -> heal contributor.

SAMPLE MATH (Aatrox L11 with 6333 only, base_ad=68, bonus_ad=60,
takedown_rate=0.5): per-trigger heal = 0.75 * 60 = 45 hp;
takedown-gated * 0.5 = 22.5 hp. The heal pool gains 22.5 hp;
blended_ehp gains ~22 hp via the top-of-damage-stack absorption.
At takedown_rate=1.0 (every-fight takedown), heal contribution
doubles to 45 hp; at takedown_rate=0.0 (never), heal contribution
is 0 (DD is back to defensive_only-equivalent on the EHP lane).

DOWNSTREAM CONSUMERS: rank.py rank_items_by_ehp surfaces DD as a
real EHP contributor for the first time. The heal magnitude is
small relative to DD's stat block (60 AD + 50 armor + 15 AH),
but the EHP delta now reflects the takedown-conditional heal
pool addition rather than ignoring it entirely. Live coaching
layers (champ_select_coach, sr_coach archetype recommenders)
pick up the change automatically via the EHP scorer.

Test count grew by 26 (4672 -> 4698) - exactly the new
test_dd_defy_heal_on_takedown.py file.

1.56.0 (cc_conditional wave 19 STATE-TRACKING EXTRACTOR SCHEMA
LIFT - NEW parent_resource field per-form record in
tools/daemon_slayer_abilities_extract.py output. The field
captures the champion-level Meraki resource string (FURY /
BLOOD_WELL / FRENZY / RAGE / HEAT / ENERGY / GRIT / MANA / ...)
threaded to every form so consumers can query state-tracking
eligibility WITHOUT parsing description text. The per-form
resource field encoded what the SPELL costs (Briar Q costs
CURRENT_HEALTH because it self-damages); the new
parent_resource field encodes what the CHAMPION uses as its
resource bar (Briar's bar is FRENZY). For Aatrox / Renekton /
Gnar / Rumble the per-form resource was null because the spells
don't cost a resource; the new field surfaces their empowered-
state resource (BLOOD_WELL / FURY / RAGE / HEAT) for the first
time. 0 new cc_conditional entries (all 6 wave-7 carries were
already shipped in prior waves 9/10/18 or REJECT-verified per
item 176 finding); the lift is FORWARD-MARKER infrastructure
for any future cc_conditional candidate consuming the
COND_FRENZY_STATE tag - the entry author SHOULD verify the
champion's parent_resource is in the empowered-state family
{FURY, BLOOD_WELL, FRENZY, RAGE, HEAT} before pitching. 6
cc_conditional champs (Aatrox / Briar / Gnar / Kennen /
Renekton / Sett) carry empowered-state resources today; the
remaining 48 are MANA/ENERGY/no-state. The 1.55.0 byte-
identical-default contract holds: include_conditional=False
math is unchanged for ALL champions; the lift is purely additive
on the extracted-data side, 2026-05-24):

SCHEMA LIFT: tools/daemon_slayer_abilities_extract.py
``_build_champion`` now reads ``payload["resource"]`` from the
Meraki champion-level record and threads it to every form via
the new ``_build_form(..., parent_resource=...)`` kwarg.
``_build_form`` adds ``"parent_resource": parent_resource`` to
the returned per-form dict positioned next to the existing
``"resource"`` field. Snapshot at
``data/daemon_slayer/16.10.1/champion_abilities.json``
regenerated; coverage 99.0% ok_rate / 927 forms / 171 champions
byte-identical to ENGINE 1.55.0 baseline. The new field is on
every form (drift guard test).

RE-AUDIT OUTCOME (carry-forward 176 (a)): all 6 wave-7 carries
closed without registry growth this wave.
  * Renekton W - ALREADY SHIPPED PRIMARY wave 9 item 153
    (COND_FRENZY_STATE 1.5s).
  * Karma W form_index=1 - ALREADY SHIPPED SIDECAR wave 10
    item 154 (COND_FRENZY_STATE 2.35-2.75s).
  * Hwei E form_index=2 - ALREADY SHIPPED SIDECAR wave 10
    item 154 (COND_CHANNEL_COMPLETION 1.2-2.0s); form_index=1
    Grim Visage was item 153 REJECT (description text says
    "DISABLE not CHANNEL") and Sylas E form 1 took the channel
    slot at wave 12.
  * Neeko E Empowered Root - ALREADY SHIPPED PRIMARY wave 1
    (COND_DUAL_ENEMY 1.8-3.0s, the dual-enemy gate is the
    same trigger surface as the W-disguise-stack empowered
    root).
  * Aatrox post-R passive - REJECT-VERIFIED item 153: the post-
    R passive surface change is minion-only fear, NOT champion
    CC; Aatrox first-order CC is Q wave 3 (nth_hit 0.5s) +
    W wave 4 (debuffed_target 1.75s).
  * Volibear R passive - REJECT-VERIFIED items 150/153/156:
    Stormbringer Turret Disable Duration is TURRET-only NOT
    champion CC.
  * Briar W frenzy - REJECT-VERIFIED items 150/153/156: Blood
    Frenzy is self-buff only (Bonus AS + Bonus MS) with no
    champion CC payload; Briar first-order CC is Q wave 4
    (terrain 1.0s) + E wave 5 (channel 1.0s) + R wave 18
    (debuffed_target 1.5s).

Future cc_conditional wave 19+ candidates targeting the
COND_FRENZY_STATE tag SHOULD use the parent_resource field as a
structural pre-filter: the entry author runs
``champ_rec[\"Q\"][0][\"parent_resource\"]`` and confirms the
result is in the empowered-state family before pitching the
entry. This replaces the prior practice of parsing description
text for "empowered" / "frenzied" / "berserk" / "rage" keywords
which had false positives (description text mentioned the state
but the CC fired on a different trigger).

ALSO 1.55.0 (cc_conditional wave 18 FULL schema lift - NEW
coexists_with_unconditional boolean field on ConditionalCcEntry
+ consumer-side MAX rule in compute_cc_pressure() so a
conditional entry CAN now coexist on the same (champion, spell)
slot as an unconditional entry in _PER_SPELL_CC_DURATIONS
without double-counting. +2 primary entries / 0 net-new
champions (Maokai already in registry via Q wave 2; Briar
already in registry via Q wave 4 + E wave 5). Closes items
170-175 carry forward (Maokai R distance-gated needs same-
spell-slot coexistence schema lift) and is the FIRST consumer
of the wave 7 forward-marker tag COND_RANGE_GATED, 2026-05-24):

SCHEMA LIFT: ConditionalCcEntry gains optional
``coexists_with_unconditional: bool = False`` field. When True,
the entry declares that the same (champion, spell) slot ALSO
holds an unconditional entry in `_PER_SPELL_CC_DURATIONS`. The
consumer-side ``compute_cc_pressure(include_conditional=True)``
math credits MAX(unconditional_post_tenacity,
conditional_post_probability_post_tenacity) per slot - never the
sum. Backward-compat: all wave 0-17 entries omit the field and
default to False; their consumer semantics are byte-identical
to ENGINE 1.54.0. The math change is OPT-IN per entry via the
new flag.

+2 PRIMARY ENTRIES this wave:

(1) Maokai R Nature's Grasp distance-gated max-root: encodes the
    FAR-DISTANCE 2.25s payoff (Meraki effects_descriptions:
    "roots them for 0.75 : 2.25 (based on distance traveled)
    seconds") gated on Maokai landing brambles at max travel.
    Maps to COND_RANGE_GATED - FIRST CONSUMER of the wave 7
    (ENGINE 1.44.0) forward-marker tag, closing the empty-
    registry contract pending since item 148. Probability tag
    midpoint 0.4. coexists_with_unconditional=True because the
    unconditional `_PER_SPELL_CC_DURATIONS["Maokai"]["R"] =
    (1.2, 1.6, 2.0)` entry encodes per-rank mid-distance
    estimates on the same slot. At default calibration the
    unconditional 2.0s (rank 3 post-tenacity) BEATS the
    conditional 2.25 * 0.4 = 0.9s post-probability - so the
    consumer credits the unconditional 2.0s. Operator can tune
    via per_entry_probability `Maokai:R = 0.9` (or higher) to
    lift the conditional above the unconditional. Maokai is NEW
    to cc_conditional in R slot (already had Q wave 2 terrain-
    stun); Maokai now has 2 cc_conditional entries (Q + R).

(2) Briar R Certain Death Hematomania impact non-marked fear:
    1.5s flat fear on all non-marked enemies in the Hematomania
    impact explosion radius (Meraki effects_descriptions: "fears
    all non-marked targets for 1.5 seconds"). Maps to
    COND_TARGET_DEBUFFED with the inverse mark-state semantic
    (fires on NON-debuffed AoE targets when the marked-debuff
    was applied to a DIFFERENT enemy). Probability midpoint 0.5.
    NO coexistence flag - Briar has no unconditional R entry in
    `_PER_SPELL_CC_DURATIONS`. Briar becomes the SECOND 3-slot
    cc_conditional champion (Q wave 4 + E wave 5 + R wave 18)
    after TahmKench (Q + W + R - shipped wave 13). FIRST Briar
    R first-order CC registration anywhere. Discovered during
    wave 18 re-audit of Briar description text alongside Briar
    W self-buff verification.

RE-AUDIT VERDICTS (orchestrator-flagged spec candidates):

* Renekton W Reign-of-Anger empowered stun 1.5s: ALREADY SHIPPED
  wave 9 (ENGINE 1.46.0, item 153) as FIRST COND_FRENZY_STATE
  consumer. Spec carry obsolete. NO state-tracking tag
  COND_FURY_50 added (would duplicate COND_FRENZY_STATE
  semantic).
* Karma W form 1 Renewal: ALREADY SHIPPED wave 10 sidecar
  (ENGINE 1.47.0, item 154) as SECOND COND_FRENZY_STATE
  consumer.
* Hwei E form 1 Grim Visage fear: ALREADY SHIPPED wave 9 primary
  (ENGINE 1.46.0, item 153).
* Hwei E form 2 Gaze of the Abyss root: ALREADY SHIPPED wave 10
  sidecar (ENGINE 1.47.0, item 154).
* Neeko E Empowered Root: ALREADY SHIPPED wave 9 primary
  (ENGINE 1.46.0, item 153) with COND_DUAL_ENEMY tag.
* Aatrox R post-passive empowered Q/W: REJECT re-verified.
  effects_descriptions confirms "fearing nearby enemy MINIONS
  AND MONSTERS for 3 seconds" - minion/monster ONLY, not
  champions. The post-R "passive Q-sweetspot empowerment"
  notion in items 150-152 audit was speculative; schema-lifted
  description does NOT empower Q or W during R.
* Volibear R Stormbringer passive form: REJECT re-verified.
  effects_descriptions confirms only turret-disable + 50% slow
  (1s decaying). No champion-facing first-order CC.
* Briar W Blood Frenzy empowered Q/E/R: REJECT re-verified.
  effects_descriptions for Briar W confirms self-buff frenzy
  state (ghosting + AS + MS + AoE-around-target AA
  empowerment) with NO CC granted to Q/E/R while in frenzy.

NO NEW CONDITION TAGS added this wave (the spec's proposed
COND_FURY_50 / COND_POSTR_PASSIVE / COND_TRANSFORMED /
COND_FRENZY_ACTIVE are redundant with existing
COND_FRENZY_STATE which already covers all observed state-
tracking-gated CC mechanics; tag total remains 13). The
COND_RANGE_GATED forward-marker tag is now ACTIVE (1 consumer
= Maokai R), closing the wave 7 schema-lift empty-registry
contract.

Registry growth: 65 entries / 54 champions (ENGINE 1.54.0) ->
67 entries / 54 champions (ENGINE 1.55.0) (Maokai already in
registry via Q wave 2; Briar already in registry via Q wave 4
+ E wave 5; both are multi-wave coexistence adds on existing
champions). Per-tag consumer counts post-wave-18:
COND_RANGE_GATED +1 (FIRST consumer); COND_TARGET_DEBUFFED +1.

Math preservation: default include_conditional=False
compute_cc_pressure is BYTE-IDENTICAL to 1.54.0 for all
touched champions. include_conditional=True callers receive:
  * Maokai R: MAX rule selects existing unconditional 2.0s
    by default (conditional 0.9s default falls below) - so
    the visible total_cc_seconds is UNCHANGED vs 1.54.0 at
    default calibration. Operator-tunable via
    per_entry_probability override.
  * Briar R: +0.75s conditional contribution (1.5 * 0.5) on
    top of existing Briar Q + E conditional contributions.

Closes items 170 / 172 / 173 / 174 / 175 carry forward "Maokai
R distance-gated NEEDS same-spell-slot coexistence schema
lift" via the new coexists_with_unconditional flag + consumer
MAX rule. Closes wave 7 (ENGINE 1.44.0) COND_RANGE_GATED
forward-marker tag empty-registry contract via Maokai R FIRST
consumer.

1.54.0 (cc_conditional wave 17 - COND_TRAVERSE tag schema lift
+1 new condition tag constant + Taliyah E first-order CC entry
closing item 174 carry (i), 2026-05-24):

Wave 17 lifts a NEW condition tag constant COND_TRAVERSE
("traverse") at calibrated midpoint 0.3 (mid-low: champions
typically AVOID telegraphed traverse-zones unless forced through
by displacement or pathing constraint). The new tag captures the
"enemy displacement-over-placed-object" CC mechanic semantic that
does NOT fit the 12 pre-existing tags (COND_TERRAIN is map-
geometry collision NOT spell-placed object; COND_NTH_HIT is
stack accumulation; COND_TARGET_DEBUFFED is pre-applied mark).

FIRST consumer is Taliyah E Unraveled Earth dash-detonation
stun 0.75s (champion-facing duration per Meraki
effects_descriptions; the 2.0s monster value is encoded as
monster-only in the description so the registry stores the
champion-facing value only). The mechanic is canonical:
Taliyah scatters 22 stones across the ground; enemies who DASH
OR ARE KNOCKED OVER a stone detonate it + are stunned 0.75s
(champion) / 2.0s (monster); the stun fires once per cast per
target ("Unraveled Earth can affect targets only once per
cast"). Standalone enemy who walks AROUND the field = damage
+ 20% slow only (no first-order CC). Schema-lift-verified via
the ENGINE 1.46.0 Meraki effects_descriptions schema lift.

Multi-wave coexistence: Taliyah W (wave 1 channel-completion
knockup) + Taliyah E (wave 17 traverse-conditional stun) is
the latest multi-entry-within-cc_conditional champion (joining
Aatrox Q+W / Brand Q+R / Briar Q+E / TahmKench R+Q / KSante
Q+W / etc).

Registry growth: 64 -> 65 entries / 54 -> 54 champions
(Taliyah already in registry via W wave 1; this is multi-wave
coexistence on the SAME champion via setdefault on a different
spell slot). Condition tag total: 12 -> 13.

Per-tag consumer counts post-wave-17: COND_TRAVERSE = 1
(Taliyah E, FIRST consumer); all other tag counts unchanged
from wave 16 baseline.

Math preservation: default include_conditional=False
compute_cc_pressure is BYTE-IDENTICAL to 1.53.0 for Taliyah
(base = 0.0 unchanged; Taliyah has no unconditional
_PER_SPELL_CC_DURATIONS entry). include_conditional=True
callers receive new probability-weighted contribution Taliyah
+0.225s (0.75 * 0.3) stacked on top of the wave 1 W
contribution (0.75 * 0.5 = 0.375), giving Taliyah a total
conditional contribution of 0.6s post-wave-17.

Closes item 174 carry (i) "Taliyah E NEEDS new COND_TRAVERSE
tag (operator-gated)". The remaining item 174 carries for
cc_conditional wave 18+ are Maokai R same-spell-slot
coexistence (NEEDS registry schema lift) + 6 wave-7
schema-lift carries (Renekton W Fury / Aatrox post-R passive
/ Volibear R passive / Briar W frenzy / multi-form
Karma+Hwei+Neeko) STILL operator-gated.

1.53.0 (cc_conditional wave 16 - +4 primary entries / +3 net-new
champions via effects_descriptions re-audit of the ENGINE 1.52.0
Meraki schema-lifted data file extending the wave 15 audit to all
171 champions regardless of cast_time, 2026-05-24):

Wave 16 ships +4 primary entries / +3 net-new champions (Garen +
Syndra + Udyr; KSante already in registry with Q wave 1 nth_hit
root) using ONLY the existing 12 condition tags. NO new tag
constants. The registry total grows 60 entries / 51 champions ->
64 entries / 54 champions (53 -> 57 primary + 7
sidecar unchanged = 64 total entries). The sweep extended the wave
15 cast_time-gated audit to scan ALL 171 champions for uncovered
slots with explicit CC duration text in effects_descriptions; 11
candidates surfaced. 4 SHIP cleanly with no schema lift + no tag
expansion + no slot collision; the other 7 REJECTED.

NEW cc_conditional entries (all primary registry):

  * Garen Q Decisive Strike empowered-AA silence (primary
    registry, NEW champion) - COND_NTH_HIT 0.7
    - durations_s=(1.5,) flat across all 5 Q ranks per
      effects_descriptions ("silence them for 1.5 seconds").
    - mechanic: Garen Q cleanses slows + bonus MS + empowers
      NEXT basic attack within 4.5s to lunge + silence target
      1.5s on hit. Standalone Q with no follow-up AA = MS
      buff cleanse only (no silence). FIRST Garen first-order
      CC registration in the engine.

  * Syndra E Scatter the Weak Dark-Sphere knockback stun
    (primary registry, NEW champion) - COND_TARGET_DEBUFFED 0.5
    - durations_s=(1.25,) flat across all 5 E ranks per
      effects_descriptions ("stunned for 1.25 seconds").
    - mechanic: Syndra E knockback cone; if a Dark Sphere
      (Q residue) sits in path, sphere ALSO flies + stuns
      targets 1.25s. Standalone E without sphere = damage +
      knockback only. Maps to COND_TARGET_DEBUFFED - the
      'debuff' is sphere overlap at moment of cast. Distinct
      from Transcendent 80-Splinter slow REJECTED wave 15.
      FIRST Syndra first-order CC registration.

  * Udyr E Blazing Stampede empowered-AA pounce stun (primary
    registry, NEW champion) - COND_NTH_HIT 0.7
    - durations_s=(0.75,) flat across all 5 E ranks per
      effects_descriptions ("stun them for 0.75 seconds").
    - mechanic: Udyr E enters Stampede Stance + NEXT basic
      attack pounces + stuns 0.75s. Once-per-target ICD that
      does NOT affect first-cast probability. Standalone
      Stance entry with no AA = MS buff + ghosting only.
      Parallel to Garen Q wave 16 (single-hit AA-empower).
      FIRST Udyr first-order CC registration.

  * KSante W Path Maker recast channel-completion stun
    (primary registry, NEW champion-slot) - COND_CHANNEL_COMPLETION 0.5
    - durations_s=(1.0,) representative midpoint of the
      0.5-1.75s range (channel-time-scaled per
      effects_descriptions). Operator can tune via
      per_entry_probability override.
    - mechanic: KSante W charges 0.4-1.0s + recast dashes +
      carries enemies + stuns 0.5-1.75s based on channel
      time. Canonical channel-completion pattern parallel to
      Warwick R + Karma W + Pantheon Q + Sion R + Renata Q +
      Rell W form 0. All Out (R-active) form REMOVES this
      stun (replaces with true damage); entry encodes BASE
      form payload only. Coexists with KSante Q wave 1
      cc_conditional entry on a different spell slot. FIRST
      KSante W first-order CC registration.

Wave 16 REJECT verdicts (effects_descriptions schema-verified
this run; CARRY-FORWARD only if new evidence surfaces):

  * Ahri W - priority targeting on Charmed targets is W's
    mechanic but W itself applies no CC; the charm is applied
    by Ahri's E. REJECT.
  * Aphelios R Moonlight Vigil - already shipped as
    Aphelios:Q:3 sidecar wave 13; R has no first-order CC
    payload. REJECT.
  * Darius E Apprehend - 1.0s airborne is UNCONDITIONAL
    pull-displacement; belongs in `_PER_SPELL_CC_DURATIONS`
    not cc_conditional. REJECT (matches wave 15 Darius E
    REJECT carry).
  * Irelia R perimeter knockaway - displacement only (per
    effects_descriptions "knocking all enemy units away from
    them, though not rendering them airborne"); 1.5s slow is
    NOT CC. REJECT.
  * LeeSin R - item 171 wave 13 REJECT carries (UNCONDITIONAL
    primary-target root + knockback) + item 172 wave 14
    REJECT carry.
  * Milio R - cleanse + tenacity buff only; no CC payload.
    REJECT.
  * Taliyah E dash-detonation stun 0.75s - wave 15 REJECT
    verdict binding (would need new COND_TRAVERSE tag for
    clean fit; tag schema lift operator-gated).

Carry-forward (still operator-gated; NOT addressed wave 16):

  * Maokai R distance-gated root - STILL would double-count
    with unconditional Maokai R entry in `_PER_SPELL_CC_DURATIONS`
    (NEEDS same-spell-slot conditional-vs-unconditional
    coexistence schema lift parallel to
    `_PER_SPELL_CC_CONDITIONAL_FORMS` but for unconditional/
    conditional pairs; operator-gated).
  * 6 wave-7 schema-lift carries: Renekton W Fury / Aatrox
    post-R passive / Volibear R passive / Briar W frenzy /
    multi-form Karma+Hwei+Neeko - STILL state-tracking
    schema-blocked (need extractor lift beyond cast_time +
    effects_descriptions to track Fury / passive-flag /
    form-empowered-state).

Registry growth: 60 -> 64 entries / 51 -> 54 champions
(53 -> 57 primary + 7 sidecar unchanged). 3 of the 4 new entries
are net-new champions (Garen + Syndra + Udyr); KSante W is a
multi-wave coexistence with KSante Q wave 1.
Per-tag consumer counts: COND_NTH_HIT +2 (Garen Q + Udyr E);
COND_TARGET_DEBUFFED +1 (Syndra E); COND_CHANNEL_COMPLETION
+1 (KSante W). COND_TERRAIN / COND_FRENZY_STATE / COND_RANGE_GATED
unchanged.

Math preservation: default include_conditional=False
compute_cc_pressure BYTE-IDENTICAL to 1.52.0 (the conditional
path skips when the flag is False). include_conditional=True
callers receive new probability-weighted contributions for
Garen (+1.05s = 1.5 * 0.7), Syndra (+0.625s = 1.25 * 0.5),
Udyr (+0.525s = 0.75 * 0.7), KSante (+0.5s = 1.0 * 0.5).

Schema lift evidence (no new lift this wave - relies on the
1.46.0 effects_descriptions schema lift + 1.51.0 cast_time
schema lift already in the extracted data):

  * Effects-description text for all 4 shipped entries
    verified against `data/daemon_slayer/16.10.1/champion_abilities.json`
    via direct probe of `effects_descriptions[]` field.
  * No collisions detected vs `_PER_SPELL_CC_DURATIONS` or
    `_PER_SPELL_CC_CONDITIONAL` or `_PER_SPELL_CC_CONDITIONAL_FORMS`
    for any of Garen:Q / Syndra:E / Udyr:E / KSante:W.

1.52.0 (cc_conditional wave 15 - +3 entries / +2 net-new champions
via cast_time + effects_descriptions cross-reference audit of the
ENGINE 1.51.0 Meraki schema-lifted data file, 2026-05-24):

Wave 15 ships +3 entries (+2 primary + 1 sidecar) across +2 net-new
champions (Zac + Rell; Ornn already in registry with Q wave 4
debuffed_target knockup) using ONLY the existing 12 condition tags.
NO new tag constants. The registry total grows 57 entries / 49
champions -> 60 entries / 51 champions (51 -> 53 primary + 6 -> 7
sidecar = 60 total entries). The sweep audited all 110 forms across 171 champs
where cast_time>0 + a CC-keyword appears in effects_descriptions;
57 collide with unconditional `_PER_SPELL_CC_DURATIONS` (BLOCKED),
28 are already covered as cc_conditional entries (no dup), 25
unsorted candidates evaluated. 3 ship cleanly with no schema lift
+ no tag expansion + no slot collision; the other 22 REJECTED.

NEW cc_conditional entries:

  * Zac Q Stretching Strikes 2-hit cross-target root (primary
    registry, NEW champion) - COND_NTH_HIT 0.7
    - durations_s=(0.5,) flat across all 5 Q ranks per
      effects_descriptions ("both are rooted for 0.5 seconds").
    - mechanic: first Q strike applies tether + slow; the
      empowered second strike (replaces next AA within 2s
      tether window) lands on a DIFFERENT target = both rooted
      0.5s. Same-target double-strike = damage + slow only (no
      root). FIRST Zac Q first-order CC registration in the
      engine. Coexists with unconditional Zac E + R entries in
      `_PER_SPELL_CC_DURATIONS` on different spell slots.

  * Ornn E Searing Charge terrain-collision stun (primary
    registry, NEW champion) - COND_TERRAIN 0.3
    - durations_s=(1.25,) flat across all 5 E ranks per
      effects_descriptions ("stuns nearby enemies for 1.25
      seconds").
    - mechanic: Ornn charges + deals damage; terrain collision
      mid-charge creates a shockwave knockup + stun 1.25s.
      Standalone E with no terrain hit = damage only. FIRST
      consumer of COND_TERRAIN tag (forward-marker since wave 7
      schema lift). Coexists with the wave 4 cc_conditional
      Ornn Q debuffed-target knockup entry on a different
      spell slot.

  * Rell W form_index=0 Ferromancy: Crash Down channel-completion
    stun (sidecar registry, NEW champion) - COND_CHANNEL_COMPLETION
    0.5
    - durations_s=(0.8,) flat across all 5 W ranks per
      effects_descriptions ("stuns them for 0.8 seconds").
    - mechanic: Rell's Mounted-state W leaps over 0.625s
      cast_time; on arrival stuns + knocks up + slides. Mid-cast
      hard CC cancels the arrival payload. Form 1 (Mount Up
      Dismounted-state empowered-AA) is REJECTED this wave
      pending operator clarification on form-transition
      empowered-AA registration. FIRST Rell W first-order CC
      registration in the engine. Coexists with unconditional
      Rell Q stun entry in `_PER_SPELL_CC_DURATIONS` on a
      different spell slot.
    - Sidecar pattern parallel to Hwei E form 1+2 + Sylas E
      form 1 + Karma W form 1 + Gnar W form 1 + Aphelios Q
      form 3 + Jayce E form 0.
    - Form-explicit override key shape: Rell:W:0.

Wave 15 REJECT verdicts (cast_time + effects_descriptions schema-
verified this run; CARRY-FORWARD only if new evidence surfaces):

  * Aatrox R / Darius R / Sion E / Nunu Q - minion-only fear or
    stun payloads (NOT champion CC). REJECT.
  * Ambessa R / Blitzcrank R / Darius E / Quinn R / Velkoz E -
    UNCONDITIONAL CC on primary champion target; belong in
    `_PER_SPELL_CC_DURATIONS` not cc_conditional. REJECT.
  * Fiddlesticks E center silence / Irelia R perimeter -
    positional sub-zone gating not encoded by schema. REJECT.
  * Khazix Q - "fear" appears in spell name only; no actual
    fear CC. REJECT.
  * LeeSin R - item 171 wave 13 REJECT carries (UNCONDITIONAL
    primary-target CC).
  * Aphelios R - the Gravitum root is already shipped as
    Aphelios:Q:3 sidecar (wave 13). R has no first-order CC.
    REJECT.
  * Rell W form 1 Mount Up empowered AA - form-transition
    empowered-AA semantics not cleanly cast-time conditional.
    REJECT pending operator clarification.
  * Syndra E Transcendent - 80-Splinter passive accumulation
    state-tracking not encoded by schema. REJECT.
  * Taliyah Q no CC; Taliyah E dash-detonation - no clean tag
    fit (would need new COND_TRAVERSE tag). REJECT.
  * Urgot R Mercy recast - target HP-threshold state-tracking
    not encoded; would need first COND_TARGET_HP_BELOW consumer
    registration. REJECT.
  * XinZhao R knockback - knockback not in cc_conditional CC
    kind schema. REJECT.
  * Zyra R - UNCONDITIONAL zone knockup. REJECT.
  * Maokai R distance-gated root - STILL would double-count
    with unconditional Maokai R entry (item 170 wave 12 + item
    171 wave 13 + item 172 wave 14 carry-forward).
  * Multi-form same-spell-slot Renekton W Fury / Aatrox post-R
    passive / Volibear R passive / Briar W frenzy / multi-form
    Karma+Hwei+Neeko - STILL self-buff or minion-only or turret-
    only per item 153 wave 9 schema-lift verification. REJECT.

Registry growth: 57 -> 60 entries / 49 -> 51 champions
(51 -> 53 primary + 6 -> 7 sidecar). Ornn already in primary
registry with wave 4 Q debuffed_target knockup so Ornn E
adds an entry but not a net-new champion.
Per-tag consumer counts: COND_NTH_HIT +1 (Zac Q);
COND_TERRAIN +1 (Ornn E, FIRST consumer); COND_CHANNEL_COMPLETION
+1 (Rell W form 0); others unchanged.

Math preservation: default include_conditional=False
compute_cc_pressure BYTE-IDENTICAL to 1.51.0 (the conditional
path skips when the flag is False). include_conditional=True
callers receive new probability-weighted contributions for
Zac (+0.35s = 0.5 * 0.7), Ornn (+0.375s = 1.25 * 0.3), Rell
(+0.4s = 0.8 * 0.5).

Schema lift evidence (carry from 1.51.0 - no new lift this wave):

  * `tools/daemon_slayer_abilities_extract.py` ``_normalize_cast_time``
    helper + per-form ``cast_time: float | None`` field from 1.51.0.
  * The 110-form audit walked the extracted data programmatically;
    the 3 shipped entries were verified against
    ``effects_descriptions[]`` + cross-checked against
    ``_PER_SPELL_CC_DURATIONS`` + ``_PER_SPELL_CC_CONDITIONAL``
    + ``_PER_SPELL_CC_CONDITIONAL_FORMS`` for collisions.

1.51.0 (cc_conditional wave 14 - +1 sidecar entry / +1 net-new
champion via cast_time Meraki extractor schema lift, 2026-05-24):

Wave 14 closes the long-deferred Jayce E cast-time root carry
(item 170 wave 12 + item 171 wave 13) by schema-lifting
``tools/daemon_slayer_abilities_extract.py`` to capture the Meraki
``castTime`` field per form. The extracted JSON now exposes
``cast_time`` (float seconds or None for instant casts) on every
ability form. ENGINE 1.51.0 re-extracts patch 16.10.1 with the new
schema; pure-additive (damage_blocks + effects_descriptions +
parse_status math byte-identical to 1.50.0).

NEW cc_conditional entry:

  * Jayce E form_index=0 Thundering Blow cast-time root
    (sidecar registry, NEW champion) - COND_CHANNEL_COMPLETION 0.5
    - durations_s=(0.25,) flat across all 5 E ranks per
      Meraki castTime field for form 0 (Hammer-form Thundering
      Blow). The CC duration equals the cast lockout window.
    - mechanic: roots the target enemy over the cast time, then
      swings the hammer to deal damage + knock target back 600
      units. Form 1 (Cannon Acceleration Gate) is instant-cast
      (cast_time=None) and has NO first-order CC. FIRST Jayce
      first-order CC registration in the engine.
    - Sidecar pattern parallel to Hwei E form 1+2 + Sylas E form 1
      + Karma W form 1 + Gnar W form 1 + Aphelios Q form 3 -
      form_index distinguishes the CC-payload form (Hammer) from
      the utility-only form (Cannon).
    - Form-explicit override key shape: Jayce:E:0.

Wave 14 REJECT verdicts:

  * Maokai R distance-gated root 0.75-2.25s - STILL would double-
    count with the unconditional Maokai R registry entry in
    `_PER_SPELL_CC_DURATIONS` for ranks 1/2/3. REJECT (carry from
    item 170 wave 12; would need that registry entry deleted
    first or a 3-registry coexistence schema lift).
  * LeeSin R cast-time root 0.25s - LeeSin R is UNCONDITIONAL on
    the primary target ("rooting the target enemy champion over
    the cast time") - belongs in `_PER_SPELL_CC_DURATIONS` not
    cc_conditional. The cast_time schema lift this wave makes
    LeeSin R a viable candidate for the unconditional registry
    but is OUT OF SCOPE for cc_conditional wave 14 (item 171
    wave 13 REJECT verdict carries).
  * KSante R cast-time gating - the description says K'Sante
    gains DISPLACEMENT IMMUNITY over the cast time AND the
    target is rooted for an explicit 0.5s during the cast
    (the 0.5s is the unconditional root - cast_time is the
    self-buff window, not the CC duration). REJECT.
  * Multi-form same-spell-slot Renekton W Fury / Aatrox post-R
    passive / Volibear R passive / Briar W frenzy - STILL self-
    buff or minion-only or turret-only per item 153 wave 9
    schema-lift verification. REJECT (no new evidence).

Registry growth: 56 -> 57 entries / 48 -> 49 champions
(51 primary unchanged + 5 -> 6 sidecar).
Per-tag consumer counts: COND_CHANNEL_COMPLETION +1; others
unchanged.

Math preservation: default include_conditional=False
compute_cc_pressure BYTE-IDENTICAL to 1.50.0 (the conditional
path skips when the flag is False). include_conditional=True
callers receive the new Jayce E sidecar entry's
probability-weighted contribution.

Schema lift evidence:

  * `tools/daemon_slayer_abilities_extract.py` now exports
    ``_normalize_cast_time(raw)`` helper handling None /
    "none" / float / numeric-string Meraki castTime values.
  * Per-form record now carries ``cast_time: float | None``.
  * Re-extracted patch 16.10.1 verified Jayce E form 0
    cast_time=0.25, form 1 cast_time=None (instant cast).
  * Same schema lift unlocks LeeSin R / KSante R / Maokai R
    cast-time data for FUTURE registry additions (NOT this
    wave per REJECT verdicts above).

1.50.0 (cc_conditional wave 13 - +7 entries / +5 net-new champions
via all-champ effects_descriptions scan against ENGINE 1.46.0 Meraki
schema-lifted data file, 2026-05-24):

Wave 13 ships +7 entries (+6 primary + 1 sidecar) across +5 net-new
champions using ONLY the existing 12 condition tags. NO new tag
constants. The registry total grows 49 entries / 43 champions ->
56 entries / 48 champions (45 -> 51 primary + 4 -> 5 sidecar = 56
total entries).

NEW cc_conditional entries:

  * Sejuani E Permafrost (primary registry, NEW champion) -
    COND_NTH_HIT 0.7
    - durations_s=(1.0,) flat across all 5 E ranks per
      effects_descriptions ("stuns them for 1 second").
    - mechanic: E can ONLY be cast against an enemy already
      carrying 4 Frost stacks (accumulated via Sejuani W +
      allied melee basic attacks within a 5s window). The cast
      itself is gated on 4 stacks - the canonical nth-hit
      conditional. Coexists with Sejuani Q + R unconditional
      stuns in `_PER_SPELL_CC_DURATIONS` on different spell
      slots.

  * Renata Q Handshake recast bystander stun (primary registry,
    NEW champion) - COND_CHANNEL_COMPLETION 0.5
    - durations_s=(0.5,) flat across all 5 Q ranks per
      effects_descriptions ("all secondary targets hit are
      stunned for 0.5 seconds").
    - mechanic: first cast roots primary target 1.0s
      (unconditional, NOT registered here yet); RECAST within
      tether throws the target, SECONDARY enemies in the throw
      line are stunned 0.5s. FIRST Renata first-order CC
      registration in the engine.

  * Shaco R Hallucinate clone-death box fear (primary registry,
    NEW champion) - COND_CHANNEL_COMPLETION 0.5
    - durations_s=(1.0,) flat across all 3 R ranks per
      effects_descriptions ("fearing nearby enemies for 1
      second").
    - mechanic: R summons a clone that lasts up to 18s; on
      clone death/expiration, 3 mini-boxes deploy + fear
      nearby enemies 1.0s. Standalone R cast = damage +
      control only. Coexists with unconditional Shaco W
      0.5-1.5s fear in `_PER_SPELL_CC_DURATIONS` on a
      different spell slot.

  * Fizz R Chum the Waters lure-on-champion knockup (primary
    registry, NEW champion) - COND_TARGET_DEBUFFED 0.5
    - durations_s=(1.0,) flat across all 3 R ranks per
      effects_descriptions ("knocked up for 1 second instead
      of knocked back").
    - mechanic: base eruption knocks back 0.25s; lure
      attached to a champion (debuffing them with slow +
      reveal) makes the eruption knock UP 1.0s instead.
      FIRST Fizz first-order CC registration in the engine.

  * Warwick E Primal Howl recast fear (primary registry,
    existing champion - coexists with wave 0 Warwick R
    suppression on a different spell slot) -
    COND_CHANNEL_COMPLETION 0.5
    - durations_s=(1.0,) flat across all 5 E ranks per
      effects_descriptions ("fearing nearby enemies for 1
      second").
    - mechanic: E grants 2.5s damage reduction; recast
      (manual after 1s or auto on buff expiration) fears
      nearby enemies 1.0s. Standalone E without recast =
      self-buff only.

  * TahmKench W Abyssal Dive emerge stun (primary registry,
    existing champion - coexists with wave 0 TahmKench R
    devour suppression + wave 5 TahmKench Q nth_hit stun on
    different spell slots) - COND_CHANNEL_COMPLETION 0.5
    - durations_s=(1.0,) flat across all 5 W ranks per
      effects_descriptions ("knock up and stun them for 1
      second").
    - mechanic: 1.35s channel + 0.15s blink + 0.65s recovery;
      on completion Tahm Kench emerges to knock up + stun
      nearby enemies 1.0s. Interrupted channel = no payload.

  * Aphelios Q form_index=3 Gravitum Binding Eclipse expunge
    root (sidecar registry, NEW champion) -
    COND_TARGET_DEBUFFED 0.5
    - durations_s=(1.0,) flat across all Q ranks per
      effects_descriptions ("rooting them for 1 second").
    - mechanic: when Gravitum is active main weapon (form 3),
      Q expunges enemies carrying Gravitum's slow debuff for
      1.0s root. Other weapon-forms (Calibrum/Severum/
      Infernum/Crescendum) have NO root payload. FIRST
      Aphelios first-order CC registration in the engine.
      Sidecar pattern parallel to Hwei E form 1+2 + Sylas E
      form 1 + Karma W form 1 + Gnar W form 1.

Wave 13 REJECT verdicts (effects_descriptions schema-lift-verified
this run; CARRY-FORWARD only if new evidence surfaces):

  * LeeSin R Dragon's Rage primary-target airborne 1.0s - the
    description "rendering them airborne for 1 second" is
    UNCONDITIONAL CC on the primary target; belongs in
    `_PER_SPELL_CC_DURATIONS` not cc_conditional. The bystander
    collision knockup IS conditional but adding it without the
    primary unconditional entry under-credits the spell.
    REJECT - defer to a future `_PER_SPELL_CC_DURATIONS`
    LeeSin R addition.
  * Poppy R Keeper's Verdict 1.0s base knockup - the 1.0s
    knockup is the BASE non-charged recast; the charged
    knockback is the empowered variant. Knockup-on-base-recast
    is UNCONDITIONAL; belongs in `_PER_SPELL_CC_DURATIONS` not
    cc_conditional. REJECT.
  * RekSai W form 1 Unburrow knockup 1.0s - unconditional 1.0s
    knockup on Unburrow form transition; belongs in
    `_PER_SPELL_CC_DURATIONS` not cc_conditional. REJECT.
  * Jayce E cast-time root - STILL schema-blocked (item 170
    wave 12 carry; cast_time field absent from
    effects_descriptions and damage_blocks).
  * Maokai R distance-gated root - STILL double-count with
    unconditional Maokai R entry (item 170 wave 12 carry;
    would need that registry deleted first).

Multi-wave coexistence count: Warwick (wave 0 R + wave 13 E)
joins as the NINTH multi-entry-WITHIN-cc_conditional champion.
TahmKench (wave 0 R + wave 5 Q + wave 13 W) extends to TRIPLE
cc_conditional coverage - FIRST 3-slot cc_conditional champion
in the registry. Sejuani (Q+R uncond + E wave 13 cond) +
Shaco (W uncond + R wave 13 cond) join as the NINTH/TENTH
unconditional/conditional-cross champions. Renata + Fizz +
Aphelios are FIRST CC registrations (no prior cc_conditional
or unconditional entries).

COND_FRENZY_STATE tag total consumers: 3 - unchanged.
COND_RANGE_GATED tag total consumers: 0 - still forward-marker.
COND_NTH_HIT total consumers: grew by 1 (Sejuani E wave 13
joins Alistar E / Brand R / Kennen E / KSante Q / Riven Q /
Viktor W / Xayah E / Yasuo Q / Yone Q / Zilean Q / Skarner Q /
Aatrox Q / TahmKench Q).
COND_TARGET_DEBUFFED total consumers: grew by 2 (Fizz R + Aphelios
Q form 3 wave 13).
COND_CHANNEL_COMPLETION total consumers: grew by 4 (Renata Q +
Shaco R + Warwick E + TahmKench W wave 13).

1.49.0 (cc_conditional wave 12 - +3 entries / +3 net-new champions
closing 3 schema-lift-verified candidates: Singed E Mega-Adhesive
overlap root + Alistar E Trample 5-stack stun + Sylas E form 1
Abduct 2-cast-completion stun, 2026-05-24):

Wave 12 ships +3 entries across +3 net-new champions using ONLY the
existing 12 condition tags. NO new tag constants. The registry total
grows 46 entries / 40 champions -> 49 entries / 43 champions (46 ->
48 primary + 3 -> 4 sidecar = 49 total entries).

NEW cc_conditional entries:

  * Singed E Fling Mega-Adhesive overlap root (primary registry) -
    COND_TARGET_DEBUFFED
    - durations_s=(1.0, 1.25, 1.5, 1.75, 2.0) per Meraki 16.10.1
      Root Duration block (schema-lifted damage_blocks expose the
      per-rank values explicitly).
    - probability=0.5 tag midpoint
    - mechanic: target must land inside Singed's pre-placed W Mega
      Adhesive zone for the root to fire; standalone E with no W
      overlap is damage + displacement only. Coexists with the
      unconditional Singed E knockback 1.0s in
      `_PER_SPELL_CC_DURATIONS` on the same spell slot via the
      separate-registry pattern. Closes item 156 wave 11 deferred
      carry (the wave 11 audit dismissed the root as "for a
      duration" without explicit value, but the actual Meraki
      damage_blocks DOES expose the per-rank Root Duration block).

  * Alistar E Trample 5-stack stun (primary registry) - COND_NTH_HIT
    - durations_s=(1.0,) flat across all 5 E ranks per
      effects_descriptions ("Alistar's next basic attack on-hit
      against a champion ... stun the target for 1 second").
    - probability=0.7 tag midpoint
    - mechanic: E channels 5s, ticks every 0.5s, generates a stack
      per champion damaged up to 5 stacks. At 5 stacks the next
      basic attack stuns. Standalone E with fewer than 5 stacks =
      damage + ghosting only. Coexists with Alistar Q + W
      unconditional entries on different spell slots. Closes item
      170 wave-12-audit candidate (named in ability_dps.py
      comment as known conditional-CC carryover).

  * Sylas E form_index=1 Abduct (sidecar registry, 2-cast-
    completion stun) - COND_CHANNEL_COMPLETION
    - durations_s=(0.5,) flat across all 5 E ranks per
      effects_descriptions ("stun them for 0.5 seconds" + "knocks
      them up for 0.5 seconds upon arrival").
    - probability=0.4 mid-low matching Hwei E parallel.
    - mechanic: Sylas E is a 2-cast cycle. Form 0 (Abscond) is a
      dash with no CC. Form 1 (Abduct, recast within 3.5s) whips
      chains that stun the first enemy + knocks them up on Sylas's
      arrival. Sidecar pattern parallel to Hwei E form 1+2.
      FIRST Sylas first-order CC registration anywhere in the
      engine. Closes item 170 wave-12-audit candidate +
      ability_dps.py:1225-1228 carry-forward + item 148 wave 7
      schema-lift docstring REJECT note (the wave 7 reject was
      correct that range is NOT the conditional axis; channel-
      completion of the 2-cast cycle IS).

Wave 12 REJECT verdicts (effects_descriptions schema-lift-verified
this run; CARRY-FORWARD to future waves only if new evidence
surfaces):

  * Jayce E Thundering Blow cast-time root - effects_descriptions
    includes "Jayce roots the target enemy over the cast time"
    and "Jayce is unable to cast To the Skies! or Shock Blast
    for 0.4 seconds after Thundering Blow's cast time". The 0.4s
    value refers to Jayce's Q/Q1 LOCKOUT period AFTER the cast,
    NOT the cast-time root duration itself. The actual cast-
    time duration is not in effects_descriptions or damage_blocks.
    CARRY-FORWARD wave 13+ if patch data adds explicit cast_time
    field.
  * Maokai R Sapling Showcase distance-gated root 0.75-2.25s -
    the unconditional Maokai R registry entry in
    `_PER_SPELL_CC_DURATIONS` already encodes a mid-distance root
    (1.2, 1.6, 2.0) seconds across 3 R ranks. Adding a
    cc_conditional COND_RANGE_GATED entry would double-count
    with the unconditional encoding under
    include_conditional=True. REJECT.

Multi-wave coexistence count: Singed (E wave 0 unconditional + E
wave 12 cc_conditional via separate-registry pattern on same spell
slot) joins as the SEVENTH unconditional/conditional-cross champion.
Alistar joins as the EIGHTH (Q+W unconditional, E wave 12
conditional, on different spell slots). Sylas (E form 1 wave 12
sidecar) is a FIRST CC registration (no prior cc_conditional or
unconditional entries).

COND_FRENZY_STATE tag total consumers: 3 (Renekton W wave 9 + Karma
W form 1 wave 10 + Gnar W form 1 wave 11) - unchanged.
COND_RANGE_GATED tag total consumers: 0 (still forward-marker per
wave 7 schema lift) - unchanged.
COND_NTH_HIT total consumers: grew by 1 (Alistar E wave 12 joins
Brand R / Kennen E / KSante Q / Riven Q / Viktor W / Xayah E /
Yasuo Q / Yone Q / Zilean Q / Skarner Q / Aatrox Q / TahmKench Q).
COND_TARGET_DEBUFFED total consumers: grew by 1 (Singed E wave 12
joins Vex E / Ornn Q / Aatrox W / Brand Q / Fiora W / Seraphine E).
COND_CHANNEL_COMPLETION total consumers: grew by 1 (Sylas E form 1
wave 12 joins Karma W / Warwick R / Pyke E / Swain E / Taliyah W /
Leblanc E / Nunu R / Yuumi Q / Pantheon Q / Briar E / Morgana R /
Evelynn W / Hwei E + Hwei E form 2 sidecar + Sion R).

Wave 12 closes the wave 11 + 12 audit-loop for now; future waves
would need either Meraki cast_time schema lift (unblocks Jayce E)
or 2-spell-overlap target-debuffed encoding schema lift (would
unblock additional patterns like Ahri R-then-W charm chain).

1.48.0 (cc_conditional wave 11 - +2 entries / +2 net-new champions
closing 2 schema-lift-verified candidates: Sion R channel-time-
gated stun + Gnar W form 1 Wallop Mega-form-gated stun via
effects_descriptions consumption, 2026-05-23):

Wave 11 ships +2 entries across +2 net-new champions using ONLY the
existing 12 condition tags. NO new tag constants. The registry total
grows 44 entries / 38 champions -> 46 entries / 40 champions.

NEW cc_conditional entries:

  * Sion R Unstoppable Onslaught (primary registry) - COND_CHANNEL_COMPLETION
    - durations_s=(1.0,) representative midpoint of channel-time
      range 0.25-1.75s explicit in effects_descriptions ("Enemies
      in a smaller radius are also pulled towards Sion over 0.5
      seconds and become stunned after a brief delay for 0.25 :
      1.75 (based on channel time) seconds")
    - probability=0.5 tag midpoint
    - mechanic: stun fires only on full-charge slam-impact; channel-
      cancel via partial charge or hard CC on Sion mid-charge
      nullifies. Closes item 150 + 151 wave-8/9 REJECT carries
      implicitly (Sion R was not previously pitched explicitly but
      falls under "channel-completion conditional channel-time-
      gated stun" pattern). Coexists with the wave 0 unconditional
      Sion Q (Decimating Smash stun 1.25-2.25s) on a different
      spell slot via setdefault.

  * Gnar W form_index=1 Wallop (sidecar registry, Mega-rage-
    transformation-form-gated stun) - COND_FRENZY_STATE
    - durations_s=(1.25,) flat across all 5 W ranks per
      effects_descriptions ("Gnar slams his arm down in the
      target direction, dealing physical damage to all enemies
      struck within the area and stunning them for 1.25 seconds")
    - probability=0.4 COND_FRENZY_STATE tag midpoint
    - mechanic: Gnar W in Mini form (form_index=0, Hyper) is a
      passive on-hit stack with no first-order CC. Gnar W in Mega
      form (form_index=1, Wallop) is the Mega-form-gated active
      stun. Maps to COND_FRENZY_STATE - Gnar must be in the
      rage-meter-driven Mega transform state to cast Wallop.
      Parallel to Renekton W Fury wave 9 + Karma W form 1 wave
      10 (THIRD consumer of the COND_FRENZY_STATE tag). The Gnar
      R unconditional terrain-collision stun 0.75s stays in
      `_PER_SPELL_CC_DURATIONS` on a different spell slot
      unchanged.

Wave 11 REJECT verdicts (effects_descriptions schema-lift-verified
this run; CARRY-FORWARD to future waves only if new evidence
surfaces):

  * Aatrox R World Ender - the 3s fear in description
    "fearing nearby enemy minions and monsters for 3 seconds"
    is explicitly minion+monster-only. NO champion-facing CC.
    CONFIRMED-REJECT.
  * Volibear R Stormbringer - description "Volibear also
    disables enemy turrets in an area" + "slowing nearby enemies
    by 50% decaying over 1 second" confirms turret-disable +
    champion slow only. Slow is NOT first-order CC. CONFIRMED-
    REJECT.
  * Briar W Blood Frenzy - description confirms self-buff state
    (ghosting + bonus attack speed + bonus movement speed +
    basic-attack empowerment). No CC granted to other spells
    while in frenzy. Briar W form_index=1 Snack Attack adds bonus
    damage + 50 bonus range + life-steal on next AA - no CC.
    CONFIRMED-REJECT.
  * Sion E Roar of the Slayer - stun 0.75s explicit but mechanic
    "If the target is a minion or non-epic monster, they are
    also stunned" is minion-only. NO champion-facing stun.
    CONFIRMED-REJECT.
  * Twisted Fate W Pick a Card Gold - ALREADY in primary registry
    as wave 0 COND_GOLD_CARD stun 1.5s. NOT a wave 11 candidate.
  * Lillia W Watch Out! Eep! - effects_descriptions shows
    damage + center-bonus only, no CC. CONFIRMED-REJECT.
  * Lillia R Lilting Lullaby - drowsy 1.5s + 2.0s sleep ALREADY
    in `_PER_SPELL_CC_DURATIONS` unconditional. NOT a wave 11
    candidate.
  * Ekko W ALREADY in `_PER_SPELL_CC_DURATIONS` unconditional.
    Ekko R Chronobreak description shows damage + self-heal +
    stasis (Ekko's own stasis, not target CC). NO champion-
    facing CC. CONFIRMED-REJECT.
  * Smolder R MMOOOMMMM! - description "exhales a wave of fire"
    + Smolder-heal + damage; no CC mention. CONFIRMED-REJECT.
  * Karma E Inspire/Defiance - both forms shield + MS only, no
    CC. CONFIRMED-REJECT.
  * Vladimir R Hemoplague - description "increasing the damage
    they take from all sources by 10%" + delayed burst damage +
    Vlad heal. NO CC. CONFIRMED-REJECT.
  * Singed E Fling - description includes conditional Mega-
    Adhesive root ("If the target lands on Mega Adhesive's area
    of effect after the displacement, they are rooted for a
    duration") but Singed E primary CC (knockup 1.0s) is ALREADY
    in `_PER_SPELL_CC_DURATIONS` unconditional. The Mega-Adhesive
    follow-up root has no explicit duration in effects_descriptions
    (just "for a duration") and requires both spells cast in
    sequence - NOT verifiable from current schema at wave 11.
    SKIP for now; would need W-overlap target-debuffed encoding.
  * Sion R adjacent: the slow 3s "and slowed by 3 seconds" is
    slow only, NOT first-order CC. The wave 11 entry captures
    only the inner-radius stun.
  * Nidalee / Elise / Jayce / Kayle - no schema-lift-verifiable
    champion-CC mechanics surface in their effects_descriptions
    blocks beyond what's already encoded (Elise E human-form
    cocoon stun ALREADY in `_PER_SPELL_CC_DURATIONS`; Jayce E
    Thundering Blow root "over the cast time" lacks explicit
    duration value; Kayle E + R have NO CC; Nidalee R is a
    transform, no CC).
  * Jayce E Thundering Blow - the description "Jayce roots the
    target enemy over the cast time, then swings his hammer at
    them to deal magic damage, capped against monsters, and
    knock them back 600 units" includes a brief root over the
    cast time. The cast time is ~0.4s per Riot wiki (NOT in
    effects_descriptions). SKIP for wave 11 since the exact
    duration value is not in the parse-strip; would need patch
    wiki cross-reference. CARRY-FORWARD for wave 12+.
  * Akshan Q + R - description shows damage + AA-AS-buff + life-
    steal + execute, no first-order CC. CONFIRMED-REJECT.
  * Tristana E Explosive Charge - description shows damage
    stacking + detonation; the Buster Shot follow-up delays the
    detonation but no CC component. CONFIRMED-REJECT.

Multi-wave coexistence count: Sion (Q wave 0 unconditional + R wave
11 cc_conditional) joins as the FIFTH multi-entry-within-cc_conditional/
unconditional-cross champion. Gnar (R wave 0 unconditional + W form 1
wave 11 sidecar cc_conditional) joins as the SIXTH. Both via the
separate-registry coexistence pattern (unconditional =
`_PER_SPELL_CC_DURATIONS`; conditional primary =
`_PER_SPELL_CC_CONDITIONAL`; conditional form-explicit =
`_PER_SPELL_CC_CONDITIONAL_FORMS`).

COND_FRENZY_STATE tag total consumers: 3 (Renekton W wave 9 +
Karma W form 1 wave 10 + Gnar W form 1 wave 11).
COND_RANGE_GATED tag total consumers: 0 (still forward-marker per
wave 7 schema lift).

1.47.0 (cc_conditional wave 10 - same-spell-slot registry schema
lift closing the (a)-class REJECT carry from wave 9 + Hwei E form 2
EW root via effects_descriptions consumption, 2026-05-23):

Ships the same-spell-slot registry schema lift (item 153 carry (a)
"Karma W form 1 R-empowered Renewal Total Root slot-collides with
wave 1 W entry; registry schema needs same-spell-slot lift") via a
parallel SIDECAR registry pattern that preserves backward
compatibility with the ~244 test access lines pinning the
``_PER_SPELL_CC_CONDITIONAL["Champion"]["Slot"]`` lookup shape.

Schema design:

  * The PRIMARY ``_PER_SPELL_CC_CONDITIONAL`` registry stays
    ``Dict[str, Dict[str, ConditionalCcEntry]]`` (unchanged shape;
    all wave 0-9 entries land here with form_index=None default).
  * The PARALLEL ``_PER_SPELL_CC_CONDITIONAL_FORMS`` sidecar
    registry is ``Dict[str, Dict[Tuple[str, int], ConditionalCcEntry]]``
    keyed by ``(spell, form_index)`` for explicit-form entries.
  * ``ConditionalCcEntry`` gains optional ``form_index:
    Optional[int] = None`` field. None = default form (wave 0-9
    legacy); int = explicit Meraki form_index (wave 10+
    schema-lift entries).
  * ``get_conditional_entries(champion)`` merges entries from
    both registries, returning a flat Q/W/E/R-ordered tuple with
    multi-form entries on the same slot ordered by form_index
    ASC (default form first, then form-explicit by ASC index).
  * ``REGISTRY_TOTAL_ENTRIES`` sums entries across both
    registries. ``REGISTRY_TOTAL_CHAMPIONS`` counts unique
    champions across both.
  * New ``_apply_per_form_entry_overrides()`` helper extends the
    wave 1 per-entry override JSON shape with a 3-segment
    ``<champion>:<spell>:<form_index>`` key for form-explicit
    calibration. The 2-segment ``<champion>:<spell>`` key from
    wave 1+ still feeds the primary registry.

NEW cc_conditional entries (both in sidecar registry; 0 net-new
champions since Karma + Hwei already had wave 0-9 entries;
registry 42/38 -> 44/38):

  * Karma W form_index=1 Renewal (Mantra-empowered Focused Resolve)
    - COND_FRENZY_STATE (SECOND consumer after Renekton W wave 9)
    - durations_s = (2.35, 2.45, 2.55, 2.65, 2.75) seconds at mid
      Mantra rank 2 (+0.75 bonus); operator can tune via
      per_entry_probability key ``Karma:W:1`` if max-Mantra
      calibration is preferred (would land at (2.85, 2.95, 3.05,
      3.15, 3.25)).
    - Mechanic schema-lift-verified: effects_descriptions[0]
      "Mantra Bonus: Focused Resolve's root duration is increased
      ... Renewal scales with Mantra's rank".
    - Coexists with primary registry wave 1 Karma W default-form
      entry (Focused Resolve channel-completion root); the
      sidecar entry encodes the Mantra-bonus extension that the
      wave 1 entry could not capture under the old single-entry-
      per-slot registry.

  * Hwei E form_index=2 Gaze of the Abyss (EW form root)
    - COND_CHANNEL_COMPLETION (third consumer after wave 1 Karma W
      + wave 4 Pyke E + wave 9 Hwei E form 1)
    - durations_s = (1.2, 1.4, 1.6, 1.8, 2.0) seconds across 5 E
      ranks (Meraki 16.10.1 Root Duration block; the duration
      values are in the parse-strip damage_blocks for form
      index=2 but were absent from the primary registry under the
      old single-entry-per-slot schema).
    - Mechanic schema-lift-verified: effects_descriptions[0]
      "Active - EW: Hwei tosses an eyeball ... root them for a
      duration".
    - Coexists with primary registry wave 9 Hwei E default-form
      entry (Grim Visage EQ channel-completion fear); both forms
      fire on the same 2-cast cycle gating but the operator
      picks EQ vs EW vs EE mid-cycle.

NO new condition tag constants this wave. The 2 entries use
COND_FRENZY_STATE (existing wave 7 tag, second consumer; closing
the "only Renekton W" single-consumer state) + COND_CHANNEL_COMPLETION
(existing wave 0 tag, third consumer; Hwei form 2 root mirrors
Hwei form 1 fear which is in the primary registry).

Consumer math BYTE-IDENTICAL to 1.46.0 for default
include_conditional=False callers across all 5 consumer surfaces
(cc_pressure + compute_ehp + compute_hybrid + coach prompt +
dashboard UI). The 2 new sidecar entries contribute to
compute_cc_pressure for Karma + Hwei when callers opt in via
include_conditional=True (Karma now has 2 conditional CC
contributions per cast; Hwei similarly).

Multi-form coexistence: the wave 10 sidecar contains 2 entries
both on champions that ALREADY have wave 0-9 entries in the
primary registry. The merge in ``get_conditional_entries()``
returns the primary entry FIRST (legacy ordering) followed by
form-explicit entries in form_index ASC order. This deterministic
iteration order matches the ``compute_cc_pressure`` Q/W/E/R
convention plus the wave 10 sub-form ordering.

+N tests NEW
``agents/daemon_slayer/tests/test_cc_conditional_wave10.py``
mirrors wave 9 test structure with per-form entry pins +
multi-form same-slot coexistence assertions + form_index
override key shape pins.
``test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES``
gained ``test_cc_conditional_wave10.py``.

Carry-forwards from item 153 mostly unchanged: (a) Karma W form 1
CLOSED this wave (sidecar registry entry); (b) RC-PostmortemAnalyze
first scheduled run 2026-05-24 04:15 still pending; (c) DD Defy
still deferred; (d) live ARAM/SR smoke still pending; (e)
Aatrox R / Volibear R / Briar W from item 153 wave 9 REJECTs are
schema-lift-verified NEGATIVES (do NOT re-pitch).

1.46.0 (cc_conditional wave 9 + Meraki extractor schema lift -
+3 entries / +3 net-new champions closing 3 of 7 schema-lift-
blocked candidates from prior wave REJECT carries, 2026-05-23):

Ships the long-deferred Meraki extractor schema lift (item 147
carry (l) / item 150 wave 7 / items 151+152 carry) by adding
``effects_descriptions: list[str]`` to each form record in
``data/daemon_slayer/16.10.1/champion_abilities.json`` via
``tools/daemon_slayer_abilities_extract.py``. The lift is PURELY
ADDITIVE: damage_blocks pipeline + parse_status math + downstream
consumers see byte-identical structured fields. Captures
empowered / form-gated CC mechanics that lived in description
text but were absent from the structured leveling[] blocks
(Renekton W Reign-of-Anger empowered stun 1.5s, Volibear R turret-
only confirmation, Aatrox R minion-only fear confirmation, Briar
W frenzy self-buff-only confirmation).

NEW cc_conditional entries (all via setdefault builder, +3 net-new
champions; registry 39/35 -> 42/38):

  * Hwei E form 1 Grim Visage (channel 0.4 fear 1.0/1.125/1.25/
    1.375/1.5s across 5 ranks). Hwei E is a 2-cast cycle (E mood
    selector -> Q/W/E form lock). Form 1 EQ fires fear on completion.
    Maps to COND_CHANNEL_COMPLETION on the 2-cast sequence.

  * Neeko E Tangle-Barbs EMPOWERED variant (dual_enemy 0.5 root
    1.8/2.1/2.4/2.7/3.0s across 5 ranks). Spiral grows on first-
    enemy hit, subsequent enemies hit by the grown spiral are
    rooted for the empowered duration. Maps to COND_DUAL_ENEMY
    (2+ enemies in spiral path). Coexists with unconditional Neeko
    E base root (0.7-1.5s in _PER_SPELL_CC_DURATIONS) via the
    separate-registry pattern.

  * Renekton W Reign-of-Anger empowered stun (frenzy_state 0.4
    stun 1.5s flat across 5 ranks). The Fury-empowered cast extends
    the base W stun (0.75s in unconditional) to 1.5s. Mechanic
    value captured EXCLUSIVELY in effects_descriptions[2] "Reign
    of Anger Bonus: ... increasing the stun duration to 1.5
    seconds" - the schema lift is necessary to verify this. Maps
    to COND_FRENZY_STATE - FIRST consumer of the wave 7 forward-
    marker tag, closing the empty-registry contract.

NO new condition tag constants this wave. All 3 use existing
COND_CHANNEL_COMPLETION (1 entry) + COND_DUAL_ENEMY (1 entry) +
COND_FRENZY_STATE (1 entry; first consumer of the wave 7 forward-
marker tag). The Renekton W entry closes the COND_FRENZY_STATE
empty-registry pattern (parallel to s112 STAT_GRANT_CALC_KEYS
closure precedent + s134 _PER_SPELL_CC_DURATIONS seed precedent).

REJECT verdicts (4 candidates from item 152 mission spec) after
schema-lift verification:

  (a) Karma W form 1 Renewal - same (Karma, W) slot already in
      cc_conditional wave 1 (Focused Resolve channel-completion
      root). Registry keyed (champion, spell); form 1 R-empowered
      variant cannot coexist on the same slot. Wave 1 entry
      captures the core mechanic; R-empowered extension is a
      calibration tuning, not new mechanic.
  (b) Aatrox R World Ender - schema-lifted description confirms
      3s fear targets minions/monsters ONLY, NOT champions. No
      champion-facing CC. The item 150 audit speculation about
      "post-R passive empowered Q-sweetspot/W-pull" is not
      supported by Riot 16.10.1 description text.
  (c) Volibear R Stormbringer - schema-lifted description confirms
      only turret-disable + 50% slow (1s decaying). Slow is NOT
      first-order CC; turret-only disable is not champion CC.
  (d) Briar W Blood Frenzy - schema-lifted description confirms
      Blood Frenzy is purely self-buff (ghosting + AS + MS +
      AoE-around-target AA empowerment). No CC granted to other
      spells while in frenzy state.

Consumer math BYTE-IDENTICAL to 1.45.0 for default
include_conditional=False callers across all 5 consumer surfaces
(cc_pressure + compute_ehp + compute_hybrid + coach prompt +
dashboard UI). The 3 new entries surface in compute_cc_pressure
for their champions when callers opt in via
include_conditional=True.

Extractor lift verified: re-extracted patch 16.10.1 with --force
(operator authorized via mission spec - current.txt unchanged at
16.10.1). New JSON is 2,260,764 bytes (was 1,702,349 bytes;
+33% growth from descriptions). Coverage section UNCHANGED
(927 forms / 571 ok / 3 partial / 3 unparsed / 350 no_damage /
99.0% ok_rate / 99.5% parsed_rate) - the lift is structurally a
strict superset.

+N tests NEW
``agents/daemon_slayer/tests/test_cc_conditional_wave9.py`` mirrors
wave 8 test structure. Plus extractor schema lift tests in
``agents/daemon_slayer/tests/test_abilities_extract_descriptions.py``
pinning the effects_descriptions field shape + presence on the
7 candidate forms.
``test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES``
gained ``test_cc_conditional_wave9.py``.

Carry-forwards from item 152 mostly unchanged: (a) operator
calibrations still tunable via JSON loader; (b) RC-PostmortemAnalyze
first scheduled run 2026-05-24 04:15 still pending; (c) DD Defy
still deferred; (d) live ARAM/SR smoke still pending. The Meraki
extractor schema lift (cited as "operator-gated" in items 150 + 151
carry-forwards) is now SHIPPED at ENGINE 1.46.0 - that lever is
closed; future wave 10+ growth must source NEW mechanics or
operator-tune existing calibrations.

1.45.0 (cc_conditional wave 8 - +3 entries / +3 net-new champions
closing prior-wave REJECT carries that DO NOT need the Meraki
extractor schema lift, 2026-05-22):

Closes item 150 carry-forward "16 consecutive saturation runs" by
correctly identifying 3 explicitly-authorized cc_conditional
candidates that:
  (a) cleanly fit the 12 existing condition tags (no new tag);
  (b) are visible at parse-strip Meraki 16.10.1 level (the Disable
      Duration / Stun Duration blocks ARE in the dump's
      damage_blocks);
  (c) were FLAGGED by prior wave REJECT notes as belonging in
      cc_conditional (NOT new pitches).

NEW entries (all via setdefault builder, +3 net-new champions):

  * Morgana R Soul Shackles (channel 0.5 stun 1.5/1.75/2.0s across
    3 ranks). Wave 8 unconditional REJECT (item 146 `4ab11ba`) said
    "REJECT - belongs in cc_conditional (parallel to Karma W)".
    Wave 9 REJECT (item 147 `3c73c3b`) said "channel-completion-
    conditional; belongs in cc_conditional parallel to Karma W".
    Mechanic identical to Karma W: tethers + stuns on full-channel
    completion. The wave 8 + wave 9 REJECT notes were definitive
    operator-acknowledged guidance; this wave executes.

  * Seraphine E Beat Drop (debuffed_target 0.5 stun 1.1/1.2/1.3/
    1.4/1.5s across 5 ranks). Wave 4 REJECT (item 138 `6718445`)
    said "conditional on existing slow"; wave 8 REJECT (item 146)
    said "target-state-conditional"; wave 9 REJECT (item 147) said
    "target-state conditional". CC tier escalates by target state -
    fresh = damage+slow only / slowed = stun / stunned = root. The
    conditional stun variant is the registry shape; same Disable
    Duration block in Meraki for all CC tiers.

  * Evelynn W Allure (channel 0.4 charm 1.25/1.5/1.75/2.0/2.25s
    across 5 ranks). Wave 4 REJECT (item 138) + wave 8 REJECT (item
    146) both said "detonation-on-Eve-attack conditional charm".
    The mark+detonation sequence is channel-completion of Evelynn's
    own kit-sequence (mark application + follow-up attack within
    ~2.5s mark window). Maps to COND_CHANNEL_COMPLETION.

NO new condition tag constants. All 3 use existing
COND_CHANNEL_COMPLETION (2 entries) + COND_TARGET_DEBUFFED (1
entry). Registry: 36 entries / 32 champions -> 39 entries / 35
champions. Multi-wave coexistence count within cc_conditional
unchanged at 4 champs (Morgana/Seraphine/Evelynn are all net-new).

This wave does NOT use the Meraki extractor schema lift - the
duration values are in the parse-strip damage_blocks (verified
via shape probe: Morgana R = "Stun Duration", Seraphine E =
"Disable Duration", Evelynn W = "Disable Duration"). The mechanic
descriptions (channel-completion / target-state-escalation /
mark-detonation) live in Riot wiki + in-game tooltip + standard
League knowledge - NO `effects`/`leveling` extractor schema lift
needed.

The Meraki parse-strip is STILL the standing constraint for
OTHER candidates (Renekton W Fury / Aatrox post-R passive /
Volibear R passive / Briar W frenzy form-empowered Q+R / Karma
W form_index=1 / Hwei E form_index=1 / Neeko E Empowered Root) -
wave 8 does NOT close that constraint.

Consumer math BYTE-IDENTICAL to 1.44.0 for default
include_conditional=False callers across the 5 consumer surfaces
(cc_pressure + compute_ehp + compute_hybrid + coach prompt +
dashboard UI). The 3 new entries surface in compute_cc_pressure
for their champions when callers opt in via
include_conditional=True.

+29 tests NEW
``agents/daemon_slayer/tests/test_cc_conditional_wave8.py`` across
7 classes (WaveEightNewEntryShapeTests / WaveEightValuePinsTests /
WaveEightNewChampionsTests / RegistryGrowthTests /
ExistingSeedPreservedTests / EngineVersionCurrentTests /
AsciiHygieneTests). EngineVersionCurrentTests uses
``assertGreaterEqual(parts, (1, 45, 0))`` for forward-
compatibility per item 146 lesson.
``test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES``
gained ``test_cc_conditional_wave8.py``.

Carry-forwards from item 150 mostly unchanged: (a) Meraki extractor
schema lift for form-empowered spells still operator-gated for the
OTHER candidates above; (c) RC-PostmortemAnalyze 2026-05-24 04:15;
(d) DD Defy still deferred; (e) live ARAM/SR smoke still pending;
(f) calibrations operator-gated; (g) obj_participation kills ->
takedowns flip operator-gated.

1.44.0 (cc_conditional wave 7 tag schema lift - COND_FRENZY_STATE +
COND_RANGE_GATED forward-marker, 2026-05-22):

Closes item 147 carry (l) "Briar frenzy + Sylas range REJECTs STILL
need new condition tag constants (separate schema lift)". Ships the
2 long-deferred condition tag constants ``COND_FRENZY_STATE`` and
``COND_RANGE_GATED`` as a FORWARD-MARKER schema-lift seam. NO new
registry entries this wave - the schema lift unblocks future entries
without a separate engine bump.

NEW condition tag constants:
  * ``COND_FRENZY_STATE`` = "frenzy_state" - champion enters a self-
    empowered state (Briar W Blood Frenzy, Renekton Fury threshold,
    Volibear R passive form, Aatrox post-R passive) that gates an
    empowered variant of another spell with first-order CC.
  * ``COND_RANGE_GATED`` = "range_gated" - CC fires only when the
    cast lands within a specific range band (close-range or max-
    range). Distinct from COND_TERRAIN (positioning vs map geometry)
    and COND_NTH_HIT (stack accumulation).

Both tags registered in ``_DEFAULT_CONDITION_PROBABILITY`` with
calibrated midpoint 0.4 (mid-low - the empowered-state / range-band
prerequisite is operator-controlled but not guaranteed; calibration
sits below COND_DUAL_ENEMY 0.6 + COND_NTH_HIT 0.7 midpoints but
above COND_TERRAIN 0.3 floor). Both exported via ``__all__`` so
external readers see them as public taxonomy. Operator-tunable via
the per-tag override JSON loader.

Registry total UNCHANGED at 36 entries / 32 champions. The item 147
carry-forward named Briar frenzy + Sylas range as canonical REJECT
candidates for these tags. A Meraki 16.10.1 re-verify during this
run found: (1) Sylas E2 Abduct stuns on hook hit regardless of cast
range (the item 142 REJECT note calling it range-conditional was
incorrect); (2) Briar W has 2 forms (Blood Frenzy + Snack Attack)
but the Meraki extract is parse-stripped to damage_blocks only - the
leveling/effects detail needed to verify a frenzy-empowered Q or R
CC mechanic is absent at parse-strip level. Future entries populate
when a Meraki-verifiable mechanic surfaces (e.g. Renekton W
empowered cast during Fury, Aatrox passive-empowered abilities,
Volibear R passive form). The forward-marker schema lift is the
deliverable.

Mirrors the s112 ``STAT_GRANT_CALC_KEYS`` empty-registry pattern at
ENGINE 1.22.0 + the pre-1.32.0 ``_PER_SPELL_CC_DURATIONS`` forward-
marker pattern.

+29 tests NEW ``agents/daemon_slayer/tests/test_cc_conditional_wave7_tags.py``
across 7 classes: WaveSevenTagConstantsTests (6) /
WaveSevenDefaultProbabilityTests (6) / WaveSevenPublicTaxonomyTests
(3) / RegistryUnchangedTests (4) / ConditionalCcEntryAcceptsNewTagsTests
(3) / WaveSevenOverrideLoaderCompatibilityTests (3) /
EngineVersionCurrentTests (1) + AsciiHygieneTests (2). Consumer math
BYTE-IDENTICAL to 1.43.0 for all 5 consumer surfaces (cc_pressure +
compute_ehp + compute_hybrid + coach prompt + dashboard UI) since
no registry entry consumes either new tag at ship time.
``test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES`` gained
``test_cc_conditional_wave7_tags.py``.

Carry-forwards from item 147 unchanged: (a) loading_view.css orphan
@import + build_order.css inverse orphan still operator-gated;
(c) cc_conditional registry future wave 8+ expansion operator-gated;
(d) DD Defy heal-on-takedown still deferred; (e) live ARAM/SR smoke
still pending; (f) RC-PostmortemAnalyze first scheduled run
2026-05-24 04:15; (g)/(h) calibration midpoints operator-gated;
(i) obj_participation widening operator-gated; (j) UI/UX live-game
audit ritual; (k) _PER_SPELL_CC_DURATIONS unconditional registry
108/89 unchanged this wave (wave 10+ likely exhausted for net-new
at 16.10.1).

1.43.0 (cc_conditional wave 6 + _PER_SPELL_CC_DURATIONS wave 9 +
BACKLOG stale-sweep wave 11 + cost/latency CLEAN, 2026-05-22):

Three commit-bearing parallel-slice additions + 1 read-only CLEAN
sweep composing on item 146 carries-forward (b) cc_conditional
wave 6 expansion + (j) _PER_SPELL_CC_DURATIONS wave 9 (multi-wave
coexistence only - saturated for net-new champs). Item 147. 14th
consecutive orchestrator-merge run (items 134-147).

Slice A - cc_conditional wave 6 (35/32 -> 36/32; +1 entry / +0
net-new champs - multi-wave coexistence on Brand) via setdefault
builder pattern from items 140-146. NEW: Brand Q Sear (target_
debuffed 0.5 stun 1.25s - stuns target carrying Blaze passive
stack; coexists with Brand R wave 1 nth_hit stun on different
spell slot - third multi-wave coexistence within cc_conditional
after Aatrox Q+W, Briar Q+E, TahmKench R+Q; brings within-cc_
conditional multi-wave coexistence count to 4 champs). Uses only
the 10 existing condition tags. REGISTRY_TOTAL_CHAMPIONS=32
unchanged / REGISTRY_TOTAL_ENTRIES=35 -> 36. REJECTED wave-6
candidates documented: Lissandra E (no CC), Aurora R/E/Q/W
(uncertain/no CC), Volibear R (turret-only), Renata R (no CC),
Aphelios Q/R (no CC), Vex E (already shipped), Sett W (needs
new tag), Vayne wall (schema lift), Trundle E (no tag fit),
Renekton W / Camille E (asymmetry). +44 tests NEW
tests/test_cc_conditional_wave6.py. 5 prior-wave test files
relaxed Brand-pin assertions to assertGreaterEqual + entry-level
pins because Brand now has Q+R in registry (pattern matches item
145 Slice B Aatrox wave 3 relax). EngineVersionCurrentTests uses
assertGreaterEqual((1, 42, 0)) for forward-compat per item 146
lesson. tests/test_cc_conditional_forward_marker.py _ALLOWED_
TEST_FILES gained test_cc_conditional_wave6.py.

Slice B - _PER_SPELL_CC_DURATIONS wave 9 (106/89 -> 108/89; +2
entries / +0 net-new champs both multi-wave coexistence) confirms
item 146 carry (j) saturation prediction. Audit walked all 226
unregistered spells of all 89 registered champions; only 2 of 6
candidates surfaced were genuine unconditional first-order CC.
NEW: Chogath W Feral Scream silence 1.6/1.7/1.8/1.9/2.0s
(coexists with Chogath Q wave 2 knockup); Malzahar Q Call of
the Void silence 1.0/1.25/1.5/1.75/2.0s (coexists with Malzahar
R wave 1 suppression). Silence joins first-order CC scope per
same precedent as wave 6 stasis (Bard R) - hard-disable types
fit cleanly alongside stun/root/suspension/suppression. Both
values verified vs data/daemon_slayer/16.10.1/champion_
abilities.json Meraki silence-duration blocks. Multi-wave
coexistence count now proven at 9 unconditional champions: Lulu
W+R (waves 1+6), Sejuani R+Q (waves 1+6), Thresh Q+E (waves 1+
6), Zac E+R (waves 2+7), Lissandra R+W (waves 1+8), Maokai R+W
(waves 1+8), Rakan W+R (waves 1+8), Chogath Q+W (waves 2+9
NEW), Malzahar R+Q (waves 1+9 NEW). Selection rules unchanged
from waves 1-8: first-order CC only; no slows; no conditional
CC; canonical DDragon ids. REJECTED wave-9 candidates: Bard Q
(cc_conditional wave 1), Morgana R (channel-completion conditional),
Seraphine E (target-state conditional), Volibear R (turret-only),
Janna R (undocumented duration), Lulu E (no CC). Consumer math
BYTE-IDENTICAL to 1.42.0 for default include_conditional=False
callers. +37 tests NEW tests/test_per_spell_cc_registry_wave9.py
across 7 classes. tests/test_per_spell_cc_registry_seed.py count
pin 89/106 -> 89/108 (assertGreaterEqual floor). tests/test_per
_spell_cc_registry_wave8.py 2 count pins assertEqual ->
assertGreaterEqual relaxation.

Slice C - BACKLOG.md L13 cc_conditional ecosystem subsection
stale-sweep wave 11 per [[feedback_backlog_path_stale_check]]:
stopping-at-item-145-state line ("items 141-145 / 4 wave
expansions / 33 entries + JSON override loader") flipped to
"items 141-146 / 5 wave expansions / 35 entries". ROADMAP sweep
CLEAN (Fleet status DS row already current at ENGINE 1.42.0 per
item 146 Slice D verified). Sweep cycle decay: wave 1=2 / 2=3 /
3=3 / 4=1 / 5=1 / 6=1 / 7=2 / 8=1 / 9=1 / 10=1 / **11=1**.
Methodology stable across 11 sweep rounds. Note: BACKLOG L13
now needs another touch by orchestrator commit to reflect the
36/108 state THIS RUN ships (Slice C ran on pre-A baseline).

Slice D - cost/latency CLEAN no-commit (14th consecutive CLEAN
sweep since item 134). All 7 levers surveyed: prompt-cache (19
files carry cache_control marker across 8 active coach modules;
22 messages.create caller files), route TTL (11+6=17 cached
routes; uncached are POST/action/file-read), polling cadences
(1.5s bridge_pending / 2s state / 500ms applyStaleness UI-local /
1000ms map cooldown UI-local), log spam (8-entry suppression set;
top non-suppressed /api/bridge at 0.197/sec well below 1/sec
threshold), model tier (all real messages.create() use claude-
haiku-4-5-20251001; 3 r._model="claude-sonnet-4-6" annotations
are POST-call telemetry stamps per item 146 don't-redo), scheduled
tasks (14 unique RC-* tasks matches item 146 catalog), bundle
size (27 panel files vs 29 @import lines in dashboard.css = 28
panel @imports including item 146 orphan loading_view.css NOT
fixed this run + 1 inverse orphan NEW: build_order.css EXISTS
in panels dir but is NOT @imported in dashboard.css). Verdict
CLEAN on 7 levers + 2 MINOR PROPOSALS (operator-gated, deferred):
1. loading_view.css orphan @import at web/css/dashboard.css:27
(carries from item 146); 2. build_order.css orphan FILE (inverse:
either dead-code awaiting deletion OR missing @import; depends
on whether build_order panel is in production - NEW this run).

Stale ENGINE pin syncs across 30+ DS test files (1.42.0 -> 1.43.0)
via orchestrator bulk-rewrite. Same s243/s246 facade-split
precedent; value-pinned regression suite is the definitive
behavior-equivalence proof.

Orchestrator-merge pattern now 14 consecutive runs (items 134-147).
Durable template for parallel headless-upgrade-style drains.

1.42.0 (cc_conditional wave 5 + _PER_SPELL_CC_DURATIONS wave 8 +
BACKLOG stale-sweep wave 10 + cost/latency CLEAN, 2026-05-22):

Three commit-bearing parallel-slice additions + 1 read-only CLEAN
sweep composing on item 145 carries-forward (a) cc_conditional
wave 5+ expansion + (i) _PER_SPELL_CC_DURATIONS wave 8. Item 146.

Slice A - cc_conditional wave 5 (33/32 -> 35/32; +2 entries / +0
net-new champs - both are multi-wave coexistence on existing keys)
via setdefault builder pattern from items 140-145. NEW: Briar E
Chilling Scream (channel_completion 0.5 fear 1.0s - full-charge
cone fear; tap-cast damage only; coexists with Briar Q wave 4
terrain stun via setdefault on different spell slot - SECOND multi-
wave coexistence in cc_conditional after Aatrox Q+W); TahmKench Q
Tongue Lash (nth_hit 0.7 stun 1.5s - 3rd-stack stun via passive;
coexists with TahmKench R wave 1 devour suppression via setdefault).
Uses only the 10 existing condition tags. REGISTRY_TOTAL_CHAMPIONS=
32 unchanged / REGISTRY_TOTAL_ENTRIES=33 -> 35. REJECTED wave-5
candidates documented: Vayne wall-stun (schema lift needed), Mel E
(needs Meraki reverify), Annie passive Pyromania (encoding
ambiguous), Belveth W (slow only), Cho'Gath W (unconditional
silence belongs in unconditional registry), Trundle E (no clean
tag fit). Multi-wave coexistence count now 4: Aatrox Q3+W (waves
3+4), Briar Q+E (waves 4+5), TahmKench R+Q (waves 1+5), Pantheon
W+Q (waves 1+4 already shipped). +52 tests NEW
tests/test_cc_conditional_wave5.py across 9 classes.
tests/test_cc_conditional_wave4.py 3 Briar aggregator assertions
relaxed to entry-level pins because Briar now has Q+E in registry.
tests/test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES set
gained test_cc_conditional_wave5.py.

Slice B - _PER_SPELL_CC_DURATIONS wave 8 (103/89 -> 106/89; +3
entries / +0 net-new champs via multi-wave coexistence) extends
the unconditional first-order CC registry. NEW: Lissandra W Ring
of Frost root 1.25/1.35/1.45/1.55/1.65 across 5 ranks (coexists
with wave 1 Lissandra R stun); Maokai W Twisted Advance root
1.0/1.1/1.2/1.3/1.4 (coexists with wave 1 Maokai R root); Rakan R
The Quickness charm 1.0/1.25/1.5 all 3 ranks (coexists with wave
1 Rakan W knockup). All 3 values verified vs
data/daemon_slayer/16.10.1/champion_abilities.json Meraki duration
blocks. Multi-wave coexistence now proven at 7 champions: Lulu
W+R (waves 1+6), Sejuani R+Q (waves 1+6), Thresh Q+E (waves 1+6),
Zac E+R (waves 2+7), Lissandra R+W (waves 1+8 NEW), Maokai R+W
(waves 1+8 NEW), Rakan W+R (waves 1+8 NEW). Selection rules
unchanged from waves 1-7: first-order CC only; no slows; no
conditional CC; canonical DDragon ids. REJECTED wave-8 candidates
documented: Bard Q / Karma W / TwistedFate W / Zilean Q / Aatrox W
/ Skarner Q (all in cc_conditional), Evelynn W / Morgana R /
Seraphine E (conditional axes), Volibear R (turret-only), Tristana
W (slow), Senna W (already shipped wave 4 per item 138). Consumer
math BYTE-IDENTICAL to 1.41.0 for default include_conditional=False
callers. +38 tests NEW tests/test_per_spell_cc_registry_wave8.py
across 7 classes. tests/test_per_spell_cc_registry_seed.py count
pin 89/103 -> 89/106. tests/test_per_spell_cc_registry_wave7.py
count pin assertEqual -> assertGreaterEqual relaxation.

Slice C - BACKLOG.md L13 cc_conditional ecosystem subsection
stale-sweep wave 10 per [[feedback_backlog_path_stale_check]]:
stopping-at-item-144-state line ("items 141-144 / 3 wave
expansions / 28 entries") flipped to "items 141-145 / 4 wave
expansions / 33 entries + JSON override loader" annotation. ROADMAP
sweep CLEAN (Fleet status DS row already current at ENGINE 1.41.0
per item 145 Slice D verified). Sweep cycle decay: wave 1=2 / 2=3
/ 3=3 / 4=1 / 5=1 / 6=1 / 7=2 / 8=1 / 9=1 / **10=1**. Methodology
stable across 10 sweep rounds.

Slice D - cost/latency CLEAN no-commit (13th consecutive CLEAN
sweep since item 134). All 7 levers surveyed: prompt-cache (8
callers explicit-block w/ cache_control + replay_coach + experi-
mental_builder verified), route TTL (17 routes cached), polling
cadences (1.5s bridge_pending / 2s state matches item 145 baseline),
log spam (/api/bridge at 0.26/sec well below 1/sec threshold,
consistent with item 145's 0.021/sec window - both below threshold),
model tier (21/21 messages.create() Haiku per reference_model_
config.md; sonnet/opus annotations are POST-call telemetry stamps
NOT API tier), scheduled tasks (7 install scripts: DDragon /
Postmortem / Rewind / LegionBridge / Phase3 x2 / run_postmortem;
cadences sane), bundle size (28 panel @imports vs 27 panel files -
loading_view.css orphan @import flagged; operator-gated 1-line
CSS fix deferred). Verdict CLEAN on 6 levers + 1 MINOR PROPOSAL
(loading_view.css orphan @import in web/css/dashboard.css:27 -
safe to ship but operator-gated; carries forward).

Stale ENGINE pin syncs across 30 DS test files (1.41.0 -> 1.42.0)
via orchestrator bulk-rewrite. Same s243/s246 facade-split
precedent; value-pinned regression suite is the definitive
behavior-equivalence proof.

Orchestrator-merge pattern now 13 consecutive runs (items 134-146).
Durable template for parallel headless-upgrade-style drains.

1.41.0 (cc_conditional wave 4 expansion + JSON override loader for
operator personal calibration, 2026-05-22):

Three parallel-slice additions composing on item 144 carries-forward
(e) operator-tunable calibration midpoints + per-entry probability
values AND (j) future cc_conditional wave 4+ expansion. Item 145.

Slice A - cc_conditional JSON override loader mirrors item 131 Slice B
`b892519` core/post_game_rubric.py pattern. NEW _OVERRIDES_PATH = Path
("data") / "cc_conditional_calibration.json" (gitignored personal
calibration; mirror of data/post_game_rubric_weights.json). NEW
_load_overrides() fail-soft (missing file -> {}, malformed JSON -> {},
non-dict shape -> {}). NEW _apply_default_probability_overrides(
defaults, overrides) -> dict (unknown tags silently dropped + bool
defense LOAD-BEARING before int/float per item 131 + out-of-range
[0.0, 1.0] DROPPED not clamped). NEW _apply_per_entry_overrides(
overrides) -> dict[(champion, spell), float] (malformed colon-keys
dropped + same bool defense + out-of-range drop). Module-load step:
_DEFAULT_CONDITION_PROBABILITY = _apply_default_probability_overrides(
_DEFAULT_CONDITION_PROBABILITY, _load_overrides()) +
_PER_ENTRY_PROBABILITY_OVERRIDES = _apply_per_entry_overrides(
_load_overrides()). _build_per_spell_cc_conditional() reads
_PER_ENTRY_PROBABILITY_OVERRIDES.get((champion, spell), default) when
constructing each ConditionalCcEntry via inline `_p()` helper. Schema:
{"default_condition_probability": {<tag>: <float>},
 "per_entry_probability": {<champion>:<spell>: <float>}}.
Both top-level keys optional. +46 tests NEW
tests/test_cc_conditional_overrides.py across 5 classes
(LoadOverridesTests 10 + ApplyDefaultProbabilityOverridesTests 10 +
ApplyPerEntryOverridesTests 10 + IntegrationTests 5 +
NoOverrideFileDefaultPreservationTests 3 + AsciiHygieneTests 1).
tests/test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES set
gained test_cc_conditional_overrides.py.

Slice B - cc_conditional wave 4 (28/28 -> 32/33; +4 net-new champs
Nunu / Yuumi / Pantheon / Briar + 1 multi-wave coexistence Aatrox W
on top of Aatrox Q wave 3) via setdefault builder pattern from items
140-144. NEW entries: Nunu R Absolute Zero (channel_completion 0.5
knockup 0.5s - full 3s channel completion); Yuumi Q Prowling
Projectile (channel_completion 0.4 root 1.75s - max-travel-distance
root); Pantheon Q Comet Spear empowered (channel_completion 0.5 stun
1.0s - long-cast empowered version; coexists with Pantheon W wave 1
unconditional stun via setdefault); Aatrox W Infernal Chains
(debuffed_target 0.5 root 1.75s - chain debuff persistence pull-back;
FIRST multi-wave coexistence with Aatrox Q wave 3 nth_hit knockup on
different spell slot); Briar Q Head Rush (terrain 0.3 stun 1.0s -
terrain-collision stun; the Briar Q+R frenzy-state-gated variants
from item 144 carry-forward still require new condition tag schema
lift NOT in this wave). REJECTED wave-4 candidates documented:
Senna W (unconditional), Aurora E / Aurora R (mechanic-uncertain),
Heimerdinger R-Q (no additional CC beyond E base), Galio Q (slow
only), Galio R (already unconditional), Briar W (no first-order CC),
Briar Q/R frenzy variants (needs new tag schema lift), Naafiri R /
Akali R / Jhin R / Pyke R / Sett R (no CC), Sett W (needs new tag),
Brand W (passive not first-order), Lillia E (no CC). REGISTRY_TOTAL_
CHAMPIONS=32 / REGISTRY_TOTAL_ENTRIES=33. +63 tests NEW
tests/test_cc_conditional_wave4.py across 9 classes.
tests/test_cc_conditional_wave3.py 3 Aatrox aggregator assertions
relaxed to entry-level pins because Aatrox now has Q+W in registry.
tests/test_cc_conditional_forward_marker.py _ALLOWED_TEST_FILES set
gained test_cc_conditional_wave4.py.

Slice C - BACKLOG.md L13 cc_conditional ecosystem entry stale-sweep
wave 9 flipped: stale "18 entries / 18 champions" + "future consumer
wires" claim replaced with comprehensive 5-consumer ecosystem
annotation (cc_pressure DIRECT + compute_ehp INDIRECT + compute_hybrid
INDIRECT + coach prompt cc_conditional_impact_line + dashboard UI
routes_cc_conditional_pressure). Sweep cycle: wave 1=2 / 2=3 / 3=3 /
4=1 / 5=1 / 6=1 / 7=2 / 8=1 / 9=1. Methodology decay continues.

Slice D - cost/latency CLEAN no-commit (12th consecutive CLEAN sweep
since item 134). All 7 levers surveyed: prompt-cache (8 callers
explicit-block w/ cache_control), route TTL (16 routes cached),
polling cadences (1.5s bridge_pending / 2s state matches s144),
log spam (/api/bridge at 0.021/sec below threshold), model tier
(21/21 messages.create() Haiku per reference_model_config.md),
scheduled tasks (14 RC-* sane), bundle size (27 panel CSS = 27
@import lines perfect parity). Verdict CLEAN; lever lane exhausted
absent product-fidelity tradeoffs.

Stale ENGINE pin syncs in 33 DS test files (1.40.0 -> 1.41.0) via
orchestrator bulk-rewrite. Same s243/s246 facade-split precedent;
value-pinned regression suite is the definitive behavior-equivalence
proof.

Wave-4 entries flow through Slice A's _p() helper (per-entry override
threading); orchestrator-merge resolved at this commit. The 5 raw-
probability literals in Slice B's diff were threaded post-merge so
per-entry overrides apply uniformly to ALL 33 registry entries.

Orchestrator-merge pattern now 12 consecutive runs (items 134-145).
Durable template for parallel headless-upgrade-style drains.

1.40.0 (cc_conditional FOURTH + FIFTH consumer wires (coach prompt +
dashboard UI) + wave 3 registry expansion, 2026-05-22):

Three parallel-slice additions composing on item 143 carries-forward (a).
The cc_conditional ecosystem is now COMPLETE across 5 consumer surfaces
(engine math: cc_pressure / compute_ehp / compute_hybrid + coach prompt
+ dashboard UI).

Slice A - cc_conditional FOURTH consumer (FIRST coach prompt) via NEW
core/cc_conditional_impact_context.py cc_conditional_impact_line().
Sibling of core/cc_blended_ehp_context.py item 138 Slice A `738c005`.
Reads compute_cc_pressure(name, mode, include_conditional=True) and
isolates the .conditional_cc_seconds contribution; aggregates across
all enemies into one summary line. Defaults
_FIGHT_WINDOW_S = 6.0 + _CC_EFFECTIVENESS_FACTOR = 0.5 match ehp.py
constants exactly. ImportError fallback stub mirrors
enemy_cc_threat_context.py pattern. Wired into all 4 active mode coach
prompts (aram / arena / brawl 3 NB+URF+OFA / coach_integration sr)
APPEND-only per cache-prefix preservation. +53 tests in NEW
tests/test_cc_conditional_impact_context.py. NO ENGINE math change.

Slice B - cc_conditional FIFTH consumer (FIRST dashboard UI) via NEW
dashboard/routes_cc_conditional_pressure.py + frontend chip. Sibling
of dashboard/routes_cc_blended_ehp_threat.py item 140 Slice A
`3b6cc4b`. GET /api/cc-conditional-pressure?ally=&enemy=&mode= returns
ally vs enemy conditional_cc_seconds averages + ratio + tier (good /
warn / bad) via symmetric construction (ally side feeds ENEMY roster
as enemy_champions to compute_cc_pressure(include_conditional=True),
vice versa). Tier bands ratio >= 1.05 = good (enemy carries more
conditional CC = follow-up window); 0.95-1.05 = warn; <0.95 = bad.
5-min TTL mode-aware in-process cache. NEW web/js/panels/
cc_conditional_pressure.js + cc_conditional_pressure.css chip
mounted between #csv-sugg-cc-blended-ehp-threat and
#csv-sugg-pickorder, tier-tinted via data-cc-cond-tier attr. +42
tests across NEW test_routes_cc_conditional_pressure.py + NEW
test_cc_conditional_pressure_panel_dom.py. NO ENGINE math change.

Slice C - cc_conditional wave 3 registry expansion (23 -> 28 entries
/ 23 -> 28 champions). Uses the _build_per_spell_cc_conditional
setdefault builder pattern. 5 new entries / 5 new champions:
  - Aatrox Q3 knockup 0.5s nth_hit 0.7 (3rd-cast within combo)
  - Riven Q3 knockup 0.75s nth_hit 0.7 (3rd Broken Wings stage)
  - Yasuo Q3 knockup 1.0s nth_hit 0.7 (Steel Tempest 3rd stack)
  - Yone Q3 knockup 0.75s nth_hit 0.7 (mirror of Yasuo Q3)
  - Leblanc E root 1.5s channel_completion 0.5 (Ethereal Chains
    full-tether)
Uses only the 10 EXISTING condition tags (no new tags).
REGISTRY_TOTAL_CHAMPIONS=28 / REGISTRY_TOTAL_ENTRIES=28. All wave 1+2
entries preserved byte-identical via setdefault. +59 tests in NEW
test_cc_conditional_wave3.py + 2 wave2 assertEqual -> assertGreaterEqual
count-pin relaxations + 1 forward-marker test allowlist update.

Slice D - cost/latency CLEAN sweep (11th consecutive CLEAN run since
item 134). 7 levers surveyed (prompt-cache / route TTL / polling
cadences / log spam / model tier / scheduled tasks / bundle size); all
CLEAN; product-fidelity lever-lane exhausted.

Consumer math BYTE-IDENTICAL to 1.39.0 for all default
include_conditional=False callers. The 5 wave-3 entries surface
via include_conditional=True opt-in through the SHIPPED cc_pressure
kwarg. The cc_conditional ecosystem is now fully consumer-wired.

1.39.0 (cc_conditional SECOND + THIRD consumer wires + wave 2 registry
expansion, 2026-05-22):

Three parallel-slice additions composing on item 142 carries-forward (h).

Slice A - cc_conditional SECOND consumer wire in ehp.py.
  compute_ehp gains `include_conditional: bool = False` kwarg AFTER
  `enemy_champions`. When True, propagates to internal
  compute_cc_pressure(enemy, mode, include_conditional=True) calls.
  Default False preserves byte-identical behavior with item 137 EHP
  contract; cc_blended_ehp now reflects conditional contribution when
  opted in. INDIRECT wire - ehp.py has no direct dependency on the
  conditional CC registry; the kwarg flow is
  ehp -> cc_pressure -> conditional registry.
  The forward-marker scan in test_cc_conditional_forward_marker.py
  keeps `_ALLOWED_SOURCE_FILES = {"cc_pressure.py"}` (ehp.py is an
  indirect kwarg-only consumer; not on the allowlist). +16 tests in
  NEW test_cc_conditional_consumer_ehp.py.

Slice B - cc_conditional THIRD consumer wire in hybrid.py.
  compute_hybrid gains `include_conditional: bool = False` kwarg AFTER
  `enemy_champions`. Threads through ALL 3 internal compute_ehp call
  sites via `**_ehp_kwargs` gating (passes the kwarg ONLY when True).
  HybridResult.cc_blended_ehp reflects conditional contribution
  automatically through the ehp -> cc_pressure chain. Default False
  preserves byte-identical behavior with item 139 hybrid contract.
  INDIRECT wire - hybrid.py has no direct dependency on the
  conditional CC registry.
  +18 tests in NEW test_cc_conditional_consumer_hybrid.py.

Slice C - cc_conditional wave 2 registry expansion (18/18 -> 23/23;
+5 entries / +5 new champs). Uses the _build_per_spell_cc_conditional
setdefault builder pattern. New entries:
  - Maokai Q Bramble Smash (terrain 0.3, stun 1.0s) - coexists with
    Maokai R unconditional via setdefault
  - Pyke E Phantom Undertow (channel_completion 0.5, stun 1.25s) -
    coexists with Pyke Q wave 3 unconditional
  - Swain E Nevermove (channel_completion 0.5, root
    1.5/1.625/1.75/1.875/2.0s across 5 ranks)
  - Skarner Q Shattered Earth + Upheaval (nth_hit 0.7, knockup 0.75s)
    - coexists with Skarner R wave 3 unconditional
  - Zilean Q Time Bomb (nth_hit 0.7, stun 2.0s)
Uses only the 10 EXISTING condition tags (no new tags). All wave 1
entries preserved byte-identical via setdefault. +55 tests in NEW
test_cc_conditional_wave2.py.

Slice D - BACKLOG stale-sweep wave 8 + cost/latency CLEAN (10th
consecutive CLEAN run since item 134). One BACKLOG entry flipped to
reflect cc_pressure SHIPPED as FIRST consumer at ENGINE 1.38.0 + the
18/18 wave 1 registry; surface natural NEXT wires (compute_ehp +
compute_hybrid) which this run ships.

Consumer math BYTE-IDENTICAL to 1.38.0 for all default
include_conditional=False callers (the existing 4+ consumers of
compute_ehp / compute_hybrid). When opted-in, cc_blended_ehp absorbs
the conditional contribution through the unified effective_cc_duration
seam (ARAM tenacity flows through automatically).

1.38.0 (cc_conditional FIRST consumer wire + wave 1 registry expansion,
2026-05-22):
Two parallel-slice additions composing on item 141 carries-forward (h).

Slice A - cc_conditional FIRST consumer wire in cc_pressure.py.
Closes item 141 carry (h): the conditional CC schema lift shipped at
1.37.0 as a FORWARD-MARKER seam with no consumer wires; this slice
wires the FIRST authorized consumer. ``compute_cc_pressure(champion,
mode, *, include_conditional=False)`` gains an opt-in kwarg. When
False (the default), behavior is BYTE-IDENTICAL to 1.37.0 for the 4
existing consumers (compute_ehp / enemy_cc_threat_line /
compute_hybrid / routes_cc_blended_ehp_threat). When True, the
function reads ``get_conditional_entries(champion)`` + computes a
probability-weighted sum via ``get_total_conditional_cc_seconds``
(apply_probability=True default), applies ARAM tenacity via
``effective_cc_duration(conditional_total, tenacity_mult)`` so the
math seam stays unified, and folds the post-tenacity conditional
total into ``total_cc_seconds`` while exposing the SEPARATE
contribution on the NEW ``conditional_cc_seconds`` field. The NEW
``conditional_entries: tuple[ConditionalCcEntry, ...] = ()`` field
surfaces the registered conditional entries for transparency.
``test_cc_conditional_forward_marker.py`` was updated in the same
slice: ``_ALLOWED_SOURCE_FILES = {"cc_pressure.py"}`` allow-lists
the FIRST consumer; every OTHER file under ``agents/daemon_slayer/``
still triggers the no-consumer-wire guard.

Slice B - cc_conditional wave 1 expansion (10 -> 18 entries).
Extends the seed shipped at 1.37.0 with 8 additional canonical
conditional CC entries across 8 new champions, all sourced from the
wave 4/5/6/7 REJECT lists: Bard Q Cosmic Binding (terrain 0.3 -
wall-bounce 1.5/1.75/2.0/2.25/2.5s); Karma W Focused Resolve
(channel 0.4 - full-tether 1.5/1.625/1.75/1.875/2.0s); Taliyah W
Seismic Shove (channel 0.5 - recast 0.75s knockup); Kennen E
Lightning Rush (nth_hit 0.6 - Mark of the Storm 3-stack stun 1.25s);
KSante Q Ntofo Strikes (nth_hit 0.7 - 3rd-cast root 0.75s; coexists
with KSante R wave 5); Ornn Q Volcanic Rupture (debuffed 0.5 -
post-Brittle knockup 1.5s; coexists with Ornn R wave 7); Xayah E
Bladecaller (nth_hit 0.6 - 3+ feathers root 1.25s); Fiora W Riposte
(debuffed 0.4 - parry-stun 1.5s). REGISTRY_TOTAL_CHAMPIONS goes
10 -> 18; REGISTRY_TOTAL_ENTRIES goes 10 -> 18. No new condition
tags (uses only the 10 existing tags). 8 candidates REJECTED with
reason: Aurora R (uncertain), Briar Q+R (frenzy-state-gated needs
new tag), Sylas E2 (range-conditional needs new tag), Renata R +
Aphelios Q (no first-order CC), Lissandra E (mis-described - direct
skillshot), Volibear R (turret-only), Swain E (deferred).

Consumer math: byte-identical to 1.37.0 for ALL existing callers via
the default ``include_conditional=False`` contract; Slice B is
data-lane only.

1.37.0 (per-spell CC registry wave 7 + conditional CC axis schema lift,
2026-05-22):
Two parallel-slice additions composing on item 140 carries-forward.

Slice A - _PER_SPELL_CC_DURATIONS wave 7 (data lane via setdefault
builder). Extends the 95-entry / 82-champion registry shipped 1.36.0
with 8 additional first-order CC entries across 7 new champions of
patch 16.10.1. New champions seeded: Irelia E Flawless Duet stun
0.75/0.85/0.95/1.05/1.15 across 5 ranks; Kalista R Fate's Call
knockup 1.0s all 3 ranks; Ornn R Call of the Forge God knockup 0.5s
all 3 ranks; Shyvana R Dragon's Descent knockback 1.0s all 3 ranks;
Smolder R Mountain Breaker knockup 1.25s all 3 ranks; Vayne E Condemn
knockback 0.5s all 5 ranks; Zac R Let's Bounce knockup 1.0s all 3
ranks; multi-wave augmentation Zac R (Zac E was wave 2; now coexists
via setdefault). Volibear E Sky Splitter airborne 0.25s all 5 ranks
adds the airborne CC kind. Selection rules unchanged from waves
1-6: first-order CC only; no slows; no conditional CC; canonical
DDragon ids. 15+ REJECT candidates documented (Darius E pull+slow /
Yorick R Mist Walkers / AurelionSol Q / Aurora W/E/R / Ambessa all
spells / Pyke E damage / Fiora W parry / Vex E mark / Ornn Q Brittle /
Renata R berserk-axis / Volibear Q terrain / Sett W/E / TahmKench R
ally swallow). Registry total: 103 entries across 89 champions
(+8 entries / +7 new champs / +1 multi-wave coexistence).

Slice B - conditional CC axis schema lift via NEW
agents/daemon_slayer/cc_conditional.py module. Forward-marker pattern
mirroring s112 STAT_GRANT_CALC_KEYS empty seam shipped at 1.22.0 and
_PER_SPELL_CC_DURATIONS pre-130 empty seam. Ships the schema +
machinery + seed of 10 canonical conditional CC entries from the
wave 4/5/6 REJECT lists (Brand R 3rd-stack stun / TwistedFate W
Gold Card / JarvanIV E terrain knockup / TahmKench R Devour
suppression / Volibear Q terrain knockback / Warwick R channel-
completion suppression / Viktor W 3rd-charge stun / Mordekaiser R
banishment / Sett E dual-enemy stun / Vex E debuffed fear). NEW
ConditionalCcEntry frozen dataclass + condition tags enum
(COND_NTH_HIT / COND_GOLD_CARD / COND_TERRAIN / COND_CHANNEL_COMPLETION
/ COND_DREAM_STACK / COND_DEVOUR_TARGET / COND_TARGET_HP_BELOW /
COND_TARGET_DEBUFFED / COND_DUAL_ENEMY / COND_MODE_GATED) + NEW
_DEFAULT_CONDITION_PROBABILITY map of 10 operator-tunable midpoints
(e.g. nth_hit=0.7 / gold_card=0.4 / terrain=0.3 / channel=0.5 /
devour=0.4 / mode_gated=1.0) + NEW _build_per_spell_cc_conditional()
setdefault builder + NEW get_conditional_entries(champion) lookup +
NEW get_total_conditional_cc_seconds(champion, apply_probability,
rank_index) probability-weighted aggregator. REGISTRY_TOTAL_CHAMPIONS
= 10 / REGISTRY_TOTAL_ENTRIES = 10. Forward-marker boundary pinned
by NoConsumerWireTests (5 tests) verifying NO file in
agents/daemon_slayer/ outside the new test files imports from
cc_conditional. cc_pressure.py / ehp.py / ability_dps.py / engine.py
all explicitly tested. DocstringStatesForwardMarkerTests (3 tests)
verify module docstring declares FORWARD-MARKER + no-consumer-wires
+ references prior STAT_GRANT_CALC_KEYS empty seam. Future consumers
populate via probability-weighted aggregation in compute_cc_pressure
or a sibling fight-sim. Production behavior of every existing
consumer is byte-identical to 1.36.0 (the new module is dead-code
at the consumer layer).

+59 tests across NEW test_cc_conditional.py (47 across 7 classes)
+ NEW test_cc_conditional_forward_marker.py (12 across 2 classes).
+37 tests in NEW test_per_spell_cc_registry_wave7.py. Total DS
suite delta from 1.36.0: +96.

1.36.0 (per-spell CC registry schema lift + wave 6, 2026-05-22):
Closes item 139 carry (j): the future registry-merge pass owed to
enable multi-wave augmentation of single-champion spell maps. Lifts
the _PER_SPELL_CC_DURATIONS registry from a single dict literal (which
clobbered prior-wave entries when a later wave added a new spell to
the same champion) to a module-level builder function
_build_per_spell_cc_durations() that uses
``registry.setdefault(champ, {})[spell] = tuple`` so multiple waves
can contribute spells to the same champion without clobbering.
Production behavior of all 90 pre-1.36.0 entries is byte-identical
(value pins preserved); the schema lift only changes the construction
shape.

Wave 6 ships 5 NEW entries unblocked by the schema lift:
* Lulu R Wild Growth knock-up 1.0s all 3 ranks (multi-wave: Lulu W
  polymorph was seeded wave 1; now coexists).
* Sejuani Q Arctic Assault stun 0.75/0.875/1.0/1.125/1.25 across 5
  ranks (multi-wave: Sejuani R was seeded wave 1; now coexists).
* Thresh E Flay knockback 0.4s all 5 ranks (multi-wave: Thresh Q
  was seeded wave 1; now coexists).
* Bard R Tempered Fate stasis 2.5s all 3 ranks (NEW champion;
  stasis added to first-order CC scope).
* Lillia R Lilting Lullaby sleep 2.0s all 3 ranks (NEW champion).

Registry total: 95 entries across 82 champions. Consumer math
byte-identical to 1.35.0 for all existing entries.

1.35.0 (compute_hybrid enemy_champions kwarg + cc_blended_ehp scoring
+ CC registry wave 5, 2026-05-22):
Two feature additions shipped in the same parallel orchestrator drain
composing on item 138 carries-forward.

Slice A - compute_hybrid enemy_champions kwarg + cc_blended_ehp
scoring. FIRST DS-engine SCORER consumer of cc_blended_ehp (the
field shipped item 137 ENGINE 1.33.0). compute_hybrid() in
agents/daemon_slayer/hybrid.py:178 gains a new
``enemy_champions: Iterable[str] = ()`` kwarg threaded through to
all 3 internal compute_ehp(...) call sites (lines 238 / 547 / 584).
When enemy_champions is non-empty, the hybrid_score uses
``ehp_result.cc_blended_ehp`` (POST-CC-erosion EHP) instead of the
pre-CC ``blended_ehp`` for the scoring component. Default empty
tuple preserves byte-identical hybrid_score with all pre-1.35.0
callers via the item 137 compute_ehp identity contract
(cc_blended_ehp == blended_ehp when enemy_champions=()).
HybridResult dataclass gains 2 new fields for surface visibility:
cc_blended_ehp: float = 0.0 + enemy_champions: tuple[str, ...] = ().
The ehp field on HybridResult keeps blended_ehp semantics (PRE-CC)
for transparency; cc_blended_ehp is the NEW surface alongside.
+22 tests in test_hybrid_enemy_champions.py. Math verified live:
Aatrox L11 SR + (Annie/Morgana/Malzahar) summed CC clamps fraction
1.0 -> cc_blended_ehp = blended * 0.5 -> hybrid_score delta = beta
* (blended_ehp - cc_blended_ehp) matches expected to 4 decimal places.

Slice B - _PER_SPELL_CC_DURATIONS wave 5 (data lane). Extends the
82-entry / 73-champion registry shipped 1.34.0 with 8 additional
first-order CC entries across 7 new champions of patch 16.10.1
(Hecarim brings 2 spell entries). Total registry now 90 entries
across 80 champions. New champs: Hecarim (E+R), KSante (R),
Mordekaiser (E), Urgot (E), Viego (W), Yone (R), Ziggs (W).
Mid-implementation collision discovery REJECTED 9 candidates that
clobbered prior-wave dict keys (Lulu R, Quinn E, Shen E, Jax E,
Jinx E, Janna Q, Sejuani Q, Rell R, Thresh E - all prior-wave
champion-spell dict keys). The dict-literal cannot represent
multi-wave augmentation of a single champion spell map; a future
registry-merge pass is owed to enable these without clobbering.
Conditional CC candidates REJECTED with reason in commit body
(Aurora R / Mordekaiser R / Briar R / Bard Q / Sett W / Taliyah W /
Volibear Q / JarvanIV EQ / Trundle R / Kennen E / KSante Q / Sett E /
Vayne E / Sylas E2 / Xayah E / Aphelios Q / Aurora E / Briar Q /
Renata R - all operator-gated schema lift). Consumer math is
BYTE-IDENTICAL to 1.34.0 (data lane only).

1.34.0 (per-spell CC duration registry wave 4, 2026-05-22):
Closes the item 137 carry / data-side broadening: extends the
67-entry / 58-champion registry shipped 1.33.0 with 15 additional
first-order CC entries across 15 new champions of patch 16.10.1.
Total registry now 82 entries across 73 champions.
New champions seeded (15): Draven (E knock-back), Ekko (W zone-expiry
stun), Janna (Q knock-up), Jax (E counter-strike stun), Jinx (E
Flame Chompers root), Mel (E Solar Snare orb root), Nocturne (E
Unspeakable Horror fear), Quinn (E Vault knock-back), Rammus (E
Frenzying Taunt), Senna (W Last Embrace root), Seraphine (R Encore
stun), Shaco (W Jack in the Box fear), Shen (E Shadow Dash taunt),
Soraka (E Equinox root), Zyra (E Grasping Roots root). Selection
rules unchanged from waves 1+2+3: first-order CC only; no slows;
no conditional CC (Bard Q wall-bounce / Evelynn W detonation-on-
Eve-attack / Hwei E compound-cast / Karma W channel-completion /
Seraphine E slowed-target / Swain E return-wave / Syndra E via
Dark Sphere / TwistedFate W Gold Card / Zilean Q double-bomb -
all REJECTED with reason recorded); canonical DDragon ids.
Consumer math is BYTE-IDENTICAL to 1.33.0 for every (champion, item,
mode) tuple - this is a pure data lane lift; the cc_pressure
aggregator (item 136 Slice A) + AbilitySpellDps.cc_duration_s /
cc_duration_post_tenacity fields read the 15 new entries transparently.
The EHP-vs-CC blended scorer (item 137 Slice A) also reads through
cc_pressure with no math change.

1.33.0 (EHP-vs-CC blended scorer + CC registry wave 3, 2026-05-22):
Closes item 136 carry (a). Two engine consumers shipped in the same
parallel orchestrator drain.

Slice A - EHP-vs-CC blended scorer (compute_ehp). Second engine math
consumer of compute_cc_pressure (after the coach-prompt-side consumer
at 1.32.0 - core/enemy_cc_threat_context.py). compute_ehp() gains an
optional enemy_champions kwarg defaulting to (). When non-empty, the
scorer computes enemy CC pressure from the registry via
compute_cc_pressure(enemy, mode) per entry, sums total_cc_seconds
across enemies, derives cc_pressure_fraction = min(sum /
_FIGHT_WINDOW_S, 1.0), and computes cc_blended_ehp = blended_ehp *
(1.0 - cc_pressure_fraction * _CC_EFFECTIVENESS_FACTOR) where
_CC_EFFECTIVENESS_FACTOR = 0.5 (conservative midpoint - 1s of summed
enemy CC pressure erodes 0.5s of operator fight-time effectiveness;
CC is not perfectly chained, QSS/Cleanse/Flash mitigate, etc.).
EhpResult gains 3 new fields (enemy_cc_pressure_s, cc_pressure_fraction,
cc_blended_ehp); to_dict + format_table + notes carry them. Default
call (enemy_champions=()) leaves cc_blended_ehp == blended_ehp -
back-compat for every existing call site across the engine + the
dashboard. The blended_ehp / physical_ehp / magical_ehp / true_ehp
fields are UNCHANGED when enemy_champions is provided - the discount
lives ONLY in the new cc_blended_ehp field. ARAM tenacity flows
through transparently via the existing compute_cc_pressure wiring.

Slice B - _PER_SPELL_CC_DURATIONS wave 3 (data registry expansion).
Extends the 53-entry / 44-champion seed (wave 1 + wave 2) with 14
additional first-order CC entries across 14 new champions at patch
16.10.1. Total registry now 67 entries across 58 champions.
New champions (14): AurelionSol R, Caitlyn W, Camille E, Diana R,
Elise E, Heimerdinger E, Ivern Q, Malphite R, Pyke Q, Rell Q, Ryze W,
Sion Q, Tristana R, XinZhao W. Selection rules unchanged from waves
1+2: first-order CC only; no slows; no conditional CC; canonical
DDragon ids. Consumer math BYTE-IDENTICAL to 1.32.0 - data lane only;
cc_pressure aggregator + AbilitySpellDps cc_duration_s fields read
the registry transparently for the new entries.

1.32.0 (cc_pressure aggregator, 2026-05-22):
First consumer of the _PER_SPELL_CC_DURATIONS registry seeded at
ENGINE 1.30.0 + extended at 1.31.0. NEW module agents/daemon_slayer/
cc_pressure.py exposes compute_cc_pressure(champion, mode) ->
CcPressureResult aggregating max-rank CC durations across registered
spells with per-mode aramTenacity applied through
ehp.effective_cc_duration. Empty result for unknown champions; SR
mode identity. The seam any future EHP-vs-CC blended scorer or
coach-prompt renderer reads from. Engine math UNCHANGED from 1.31.0
for every (champion, item, mode) tuple - this is a NEW aggregator
module, not a math change to compute_dps / compute_ability_dps /
compute_ehp / compute_hps. Existing per-spell cc_duration_s +
cc_duration_post_tenacity fields on AbilitySpellDps unchanged.

1.31.0 (per-spell CC duration registry wave 2, 2026-05-21):
Closes item 134 carry-forward (h) data-side: extends the
``_PER_SPELL_CC_DURATIONS`` registry shipped 1.30.0 with 23 additional
first-order CC entries across 20 additional champions of patch 16.10.
Total registry now 53 entries across 44 champions (was 30 / 24 at
1.30.0). Consumer math is BYTE-IDENTICAL to 1.30.0; this is a pure
data lane lift - the values flow through AbilitySpellDps.cc_duration_s
+ cc_duration_post_tenacity for API inspection only.
New champions seeded (20): Alistar (Q + W), Amumu (Q + R), Anivia (Q),
Braum (R), Chogath (Q), Fiddlesticks (Q), Gnar (R), Gragas (E),
Jhin (W), Lux (Q), Nami (Q), Neeko (E + R), Orianna (R), Poppy (E),
Riven (W), Singed (E), Skarner (R), Varus (R), Xerath (E), Zac (E).
Selection rules followed from 1.30.0: first-order CC only (stuns /
roots / suspensions / knock-ups / knock-backs / charms / sleeps /
fear / suppressions). No slows. No conditional CC (e.g. Bard Q
wall-bounce, Tahm Kench Q 3rd-stack). Canonical DDragon ids
(Chogath, Wukong=MonkeyKing pre-existing).
The engine-side fight-sim consumer that reads the registry for math
is STILL FUTURE work per the BACKLOG carry. This bump is a DATA seed
only.

1.30.0 (per-spell CC duration registry seeded, 2026-05-21):
Closes the item 130 carry-forward (b): the engine-side fight-sim
consumer that reads ``_PER_SPELL_CC_DURATIONS`` for math is still
FUTURE work, but this slice seeds the DATA so it is available on the
wire (AbilitySpellDps.cc_duration_s + cc_duration_post_tenacity)
for future composition + direct API inspection.
Registry seeded with 30 starter entries across 24 champions (Q/W/E/R
per-spell CC base durations from patch 16.10 tooltips). All entries
are FIRST-ORDER CC (stuns / roots / suspensions / knock-ups / charms
/ suppressions / polymorphs / sleeps / taunts). Slows are NOT encoded
(different math). Conditional CC (e.g. Brand R 3rd-stack, charged
variants requiring fight-sim observer) is skipped where base semantic
is unclear without a fight-sim.
Champions seeded (24): Ahri, Annie, Ashe, Blitzcrank, Cassiopeia,
Galio, Leona, Lissandra, Lulu, Malzahar, Maokai, MonkeyKing (Wukong),
Morgana, Nautilus, Pantheon, Rakan, Renekton, Sejuani, Sona, Thresh,
Veigar, Vi, Yasuo, Zoe.
This bump is a DATA-LAYER seed, NOT a math change - the ``cooldown``,
``base_cooldown``, ``total_ability_haste``, ``raw_damage_per_cast``,
``post_mode_damage_per_cast``, ``post_mitigation_damage_per_cast``,
``dps``, and all other existing fields are byte-identical to 1.29.0
output for every (champion, spell, mode) tuple. Only the 2 cc_*
tuple fields now carry non-empty values for the 30 seeded entries.
This is the 2nd consumer of ``effective_cc_duration`` helper shipped
1.25.0 (item 122). Engine-side math consumption (fight-sim) is still
FUTURE work per the BACKLOG carry.

1.29.0 (per-spell CC duration extractor seam, 2026-05-21):
Closes the item 129 carry-forward (a): 2nd consumer of the
``effective_cc_duration`` helper shipped 1.25.0 (item 122). The helper
itself lives in ``ehp.py`` (free function); this slice exposes the
downstream-consumer surface at the per-spell AbilityDps layer so a
future EHP-vs-CC blended scorer (or fight-sim) can read per-rank base
CC durations + the matching post-tenacity values without re-resolving
the champion.
NEW ``AbilitySpellDps.cc_duration_s: tuple[float, ...]`` field
(defaults ``()`` empty tuple) - per-rank base CC duration in seconds.
NEW ``AbilitySpellDps.cc_duration_post_tenacity: tuple[float, ...]``
field - same shape after element-wise
``effective_cc_duration(base, aram_tenacity_mult)``; identity in SR
+ non-ARAM modes; lengthened in ARAM for the 15 champs with
aramTenacity > 1.0.
NEW ``_PER_SPELL_CC_DURATIONS: dict[str, dict[str, tuple[float, ...]]]``
module-level registry seam (in ``ability_dps.py``). EMPTY at 1.29.0
by design (mirror of item 112's ``STAT_GRANT_CALC_KEYS`` empty-seam
pattern): production behavior is byte-identical to pre-slice because
the registry returns ``()`` for every (champion, spell) lookup;
``_apply_tenacity_to_cc_tuple(())`` short-circuits to ``()``. Future
patches populate per-champion + per-spell entries when a downstream
consumer (fight-sim / coach-prompt / EHP-vs-CC) needs the data.
NEW free helpers ``_per_spell_cc_for(champion_id, spell_key)`` +
``_apply_tenacity_to_cc_tuple(base, tenacity_mult)`` (the latter
wraps ``ehp.effective_cc_duration`` element-wise). Imported via
``from .ehp import effective_cc_duration`` at the top of
``ability_dps.py`` - no circular (``ehp.py`` does not import
``ability_dps``).
This bump is a forward-marker engine seam, NOT a math change - the
``cooldown``, ``base_cooldown``, ``total_ability_haste``,
``raw_damage_per_cast``, ``post_mode_damage_per_cast``,
``post_mitigation_damage_per_cast``, ``dps``, and all other existing
fields are byte-identical to 1.28.0 output. The 2 new fields default
to ``()`` so existing consumers (rank.py, coach prompts, /api/state)
remain forward-compatible.

1.28.0 (Phase 6 EHP healing throughput, 2026-05-21):
Closes the ehp.py:23 deliberate Phase-1 omission "Healing throughput
(lifesteal, Spirit Visage amp) - fits Phase 6". Three contributions
now feed an EHP heal pool:
  (a) item-passive heals via NEW ``ItemHeal`` dataclass +
      ``ItemEffect.heal`` field: Sundered Sky 6610 / Arena 226610
      "Lightshield Strike" 100% base AD melee / 50% base AD ranged
      per one-trigger-per-fight (10s CD per target > 6s fight window).
  (b) lifesteal-derived heal: ``stats.lifesteal * stats.ad * stats.as
      * _FIGHT_WINDOW_S (6.0)`` accumulated over the standard fight
      window. Pre-mitigation approximation (consistent with EHP's
      no-enemy-pen Phase-1 posture).
  (c) multiplicative heal amp via NEW ``ItemEffect.heal_amp_pct``
      field: Spirit Visage 3065 / Arena 223065 "Boundless Vitality"
      +25%. Multiple amp items stack multiplicatively per the
      buff-system doctrine (batch 14).
Bloodthirster 3072 / Arena 223072 "Ichorshield" rides the Phase 1.5
ItemShield pipeline (full-cap steady-state assumption: 165 L1 -> 315
L18, ANY damage type; overheal builds the shield between fights at
base/walking). NO ``unique_passive_key="lifeline"`` - BT's Ichorshield
is a distinct unique passive and can stack with any single lifeline
shield in real builds.
EhpResult gains heal_item_total / heal_lifesteal / heal_amp_mult /
heal_total / heal_sources fields; compute_ehp folds heal_total into
physical_ehp / magical_ehp / true_ehp at the top of the damage stack
(heals don't discriminate by damage type, so the heal pool acts like
an ANY shield).
Deliberate Phase-6 omissions (deferred to Phase 6.5+):
  * Death's Dance Defy heal-on-takedown (75% bonus AD over 2s) - the
    takedown-rate assumption is uncertain; stays defensive_only.
  * Spirit Visage amp on Phase 1.5 SHIELDS - the engine ships
    heal-pipeline amp only. Builds pairing Spirit Visage with a
    lifeline item under-credit by ~15% on the shield piece.
  * Sundered Sky 6% missing-HP additive - requires a current-HP-share
    assumption distinct from the steady-state full-HP convention.

1.27.0 (Phase 1.5 EHP shield throughput, 2026-05-21):
Closes the ehp.py:21 deliberate Phase-1 omission "Shield throughput
(Sterak's lifeline, Doran's Shield, Bloodthirster) - needs uptime
modeling". Ships the four LIFELINE-style shields (single trigger per
fight, value-additive to the effective-HP pool at top of the damage
stack):
  * Sterak's Gage 3053 - any-damage, 60% bonus_hp
  * Immortal Shieldbow 6673 - any-damage, 400 L1-L8 -> 700 L18,
    ranged x0.80
  * Maw of Malmortius 3156 - magical, 200 + 150% bonus_ad, ranged x0.75
  * Hexdrinker 3155 - magical, 110 L1-L8 -> 280 L18, ranged x0.75
NEW ``ItemShield`` dataclass in _effects_types.py + ``ItemEffect.shield``
field. EhpResult gains shield_any / shield_phys / shield_mag /
shield_true / shield_sources fields; compute_ehp folds the shield_hp
into physical_ehp / magical_ehp / true_ehp at the top of the damage
stack (shields share the same armor/MR factor as HP per League's
damage model). 4 lifeline items share unique_passive_key="lifeline"
so rank.py's shares_dead_unique filter picks at most one in any
generated build (compute_ehp itself does NOT apply dedup - the data
layer carries the values, the planner decides which to keep).
Bloodthirster's ichor-shield is intentionally DEFERRED to Phase 6
(with the lifesteal model) - it requires overheal accrual rather
than a single-trigger threshold.

1.26.0 (Dead Man's Plate Momentum stacks-schema lift, 2026-05-21):
Closes BACKLOG "Dead Man's Plate Momentum stacks-schema" queued from
overnight 2026-05-20 iter 15-16 (where the item was flipped to
defensive_only because the dual-track Meraki formula didn't fit any
existing schema). NEW ``PeriodicProc.stack_ramp_seconds`` field
(default 0.0; backward-compat) - the family extension for the
stack-accumulation -> discharge pattern. When > 0 alongside
every_n_attacks > 0, the sustained model in ``_periodic_proc_dps``
fires the proc once per ``max(stack_ramp_seconds,
every_n_attacks * attack_period_s)`` - typically the ramp dominates
(3.57s > 1/AS for non-attack-speed-stacked builds). The burst path
(``_per_attack_proc_damage``) skips stack-ramp-gated procs because
the burst window (2-3s) is shorter than typical ramps and these are
tank/utility items whose DPS contribution is sustained-only.
Dead Man's Plate (3742 + Arena mirror 223742) re-encoded:
``Shipwrecker`` proc = lambda c: 40.0 + c.base_ad PHYSICAL,
every_n_attacks=1, stack_ramp_seconds=3.57. Full-stack discharge
matches Meraki 16.10.1 spec: ``0.4 * 100 (cap 40) + 1.0 * base_ad``.
Verified: Aatrox L11 + 3742 vs no items vs 100 armor target = 20.15
DPS delta = (40 + 103.875) / 3.57 * 0.5 exactly. Other items can
adopt the same schema in future iterations (Sterak's Lifeline once
the EHP-vs-CC sim lands; hypothetical future ramp-discharge items).
Schema is mutually exclusive with every_n_seconds (no ramp semantics
in time-based path; ramp is implicit in the period).

1.25.0 (aram_tenacity_mult consumer wired into EHP, 2026-05-21):
Closes BACKLOG "Future EHP enemy-CC model for aram_tenacity_mult"
carry from item 113 (the field was forward-marker-stored on
AbilityDpsResult in 1.23.0 but had no EHP-side surfacer or consumer
helper). EhpResult now surfaces ``aram_tenacity_mult`` (default 1.0)
read from ``resolved.stats.get("aram_tenacity_mult", 1.0)``. NEW
module-level helper ``effective_cc_duration(base_cc_s, tenacity_mult)``
returns ``base_cc_s * max(0.0, tenacity_mult)`` - the seam any future
fight-sim / coach-prompt / EHP-vs-CC consumer reads to convert a base
CC duration into the post-tenacity value. 17 ARAM champs carry
non-1.0 aramTenacity in 16.10.1 (assassin-shaped +20% / +10%
lengthening + a handful of shorteners). EHP's blended_ehp math is
UNCHANGED - CC duration vs HP pool is a separate axis; consumers
must pair tenacity_mult with their own base-CC assumption. SR + every
non-ARAM mode degenerate to identity (tenacity_mult = 1.0; helper
returns base_cc_s unchanged). format_table renders the tenacity line
only when non-1.0 (parallel to mode_multiplier).

1.24.0 (per-item flat AH wired into compute_ability_dps, 2026-05-21):
Closes BACKLOG item "DS item-level ability_haste lane". DDragon
items.json's structured ``stats`` block strips ``AbilityHaste`` (only
carries it in ``tags``); the numeric value lives in the localized
description as ``<attention>N</attention> Ability Haste`` inside the
leading ``<stats>...</stats>`` block. Meraki bulk strips per-item
stats. NEW ``agents/daemon_slayer/_item_ability_haste.py`` ships a
static 220-entry registry parsed from items.json description text
at patch 16.10.1, with ``total_item_ability_haste(item_ids)``
summer. Wired into ``compute_ability_dps`` as ``base_ah`` -> threaded
through the existing 1.23.0 ``_total_ability_haste`` +
``_effective_ability_cd`` haste-formula consumer. SR + ARAM both
benefit (ARAM additionally folds ``aram_ability_haste`` on top).
Example: SR Black Cleaver (20) + Cosmic Drive (25) + Sorc Shoes (0)
+ Lich Bane (10) + Rabadon (0) + Zhonya (0) = 55 AH -> 7s base CD ->
7 / 1.55 = 4.52s effective. Pre-1.24.0 the engine pinned base CDs
regardless of build AH (floor case ``base_ah=0.0``).

Regeneration on new patches: re-parse items.json description text;
subsequent matches (Mythic-passive AH grants, on-takedown procs) are
intentionally ignored - the static lane carries only the build-time
base stat.

1.23.0 (aramAbilityHaste + aramTenacity engine consumption, 2026-05-20):
Closes the half-shipped state from ENGINE 1.19.0 (`6bba097` exposed
the two ARAM modifier keys via the resolved stats dict but no scorer
read them). The cooldown lane in
``agents/daemon_slayer/ability_dps.py`` now CONSUMES the
``aram_ability_haste`` delta via Riot's canonical haste formula
``eff_cd = base_cd / (1 + total_AH / 100)`` (mirrors
``core/summoner_cooldowns.py`` shipped 2026-05-20 `58d1e87` for
summoner spells). 22 champs carry non-zero aramAbilityHaste in
16.10.1 - the consumer is now real, not a TODO:
* positive deltas shorten the rotation (Soraka +10, Katarina +10,
  Azir +20, Aurora/Camille/Hecarim/Irelia/Lucian/Naafiri/Rakan +10,
  Leblanc +20)
* negative deltas lengthen it (Seraphine -20, Teemo -15, Ziggs -20,
  Corki -20, Brand/Mel/Milio/Sion/Smolder/Zyra -10)
New helpers in ``ability_dps.py``:
  * ``_effective_ability_cd(base_cd, total_haste)`` - the haste formula
    primitive (denominator floor 0.01 against extreme negative haste).
  * ``_total_ability_haste(scaled_stats, mode, base_ah=0)`` - mode-gated
    read of the engine-exposed aram_ability_haste delta. SR + every
    non-ARAM mode return base_ah unchanged; ARAM folds in the delta.
    ``base_ah`` is reserved for the future item-AH lane - currently 0.
Schema lift on ``AbilitySpellDps``:
  * ``base_cooldown`` - pre-haste rank cooldown (back-compat: identity
    to old ``cooldown`` field in SR + zero-haste-ARAM cases).
  * ``total_ability_haste`` - the haste sum used in the formula.
Schema lift on ``AbilityDpsResult``:
  * ``aram_ability_haste`` - the consumed haste delta (0.0 outside ARAM).
  * ``aram_tenacity_mult`` - forwarded for a future EHP-side enemy-CC
    consumer; NOT consumed in this slice (the consumption point is in
    a future EHP scorer that ingests enemy CC durations applied
    against the receiving champion). Marker is in place so when that
    scorer ships, the data is already on the result.
Existing ``cooldown`` field on ``AbilitySpellDps`` now stores the
EFFECTIVE post-haste cooldown. SR mode + most ARAM champions (those
with aramAbilityHaste=0) see identity - the field is backward
compatible. Forty-two test files in the DS test suite assert on
``.cooldown`` values for SR-mode builds (e.g.
``test_cooldown_inheritance.py``); all preserved because total_ah=0
at SR. +26 new value-pinned tests in
``test_aram_ability_haste_consumption.py`` covering haste formula
math, mode-gated composition, live snapshot consumption (Soraka Q
6.0 -> 5.4545 at +10 AH, Azir E 22.0 -> 18.333 at +20 AH, Seraphine
Q lengthened at -20 AH, Teemo Q lengthened at -15 AH, Veigar
zero-haste identity), tenacity forwarding, to_dict round-trip,
backward-compat on Riven R / Qiyana Q / Veigar W SR baselines.

1.22.0 (cdragon-arena calculations formula evaluator, 2026-05-20):
Phase 6 step 3 of the cdragon-arena `dataValues + calculations`
enrichment closes the half-shipped state (dataclass layer landed
`8f7a71b` 2026-05-20). New module
``agents/daemon_slayer/augment_formula_eval.py`` interprets the 4 cdragon
`mFormulaParts` typed-part shapes (NumberCalculationPart /
NamedDataValueCalculationPart / StatByNamedDataValueCalculationPart /
StatByCoefficientCalculationPart) with the optional `mMultiplier`
wrapper, composing via sum-of-parts. The evaluator is pure-function
and PRE-WIRED into ``compute_augment_stats``: when an augment ships
non-empty `calculations` AND any calc key maps to a canonical stat
grant via ``STAT_GRANT_CALC_KEYS``, the evaluator displaces the
hand-maintained ``_AUGMENT_STAT_OVERLAYS`` entry for that augment;
otherwise the registry remains the source of truth. At cdragon 16.10.1
NO augment ships a stat-named calc key (every key is damage / heal /
shield / conversion - Typhoon "Damage" = 0.2 * AD, UndyingGuard
"TotalDamage" = BaseDamage + 1.0*bonus_AD + 1.1*bonus_HP, etc.), so the
``STAT_GRANT_CALC_KEYS`` map is empty and the live behavior is
unchanged. The seam exists for the next-patch slice when Riot ships a
stat-named calculation (e.g. Arena S2 Augment Level-Up patch 26.09).
Out of scope for this slice (return zero-contribution today; future
evaluator extensions): ByCharLevelInterpolationCalculationPart,
ByCharLevelBreakpointsCalculationPart, BuffCounterByCoefficient,
SumOfSubParts, ProductOfSubParts, AbilityResourceByCoefficient,
GameCalculationModified, hash-name parts (e.g. ``{b22609db}``). None
carry stat-grant semantics at the current patch.
+N tests in ``test_augment_formula_eval.py`` covering each typed-part
shape, mMultiplier wrapping, part-sum composition, real-augment value
extraction (Typhoon Damage = 0.2*AD, ServeBeyondDeath {85d7d7f0} =
10 * 0.25 = 2.5, UndyingGuard TotalDamage at bonus_ad=100/bonus_hp=200,
JeweledGauntlet CritGranted), and the overlay-registry fallback. The
evaluator is non-load-bearing for production callsites today; the
ENGINE bump is the architecture seam that future patches consume.

1.21.0 (UX-headless iter 4 / DS audit lane: AP-scaling on-hit family,
2026-05-20): Nashor's Tooth Icathian Bite AP coefficient corrected
20% -> 15% per Meraki bulk 16.10.1 ("Basic attacks deal 15 (+ 15% AP)
bonus magic damage on-hit"). Both 3115 (SR) and 223115 (Arena mirror)
corrected. New pinned test test_nashors_tooth_meraki_16_10_1_coef
guards the value (closed-form: at ap=100 the proc damage is 30.0).

Other AP-scaling on-hit family members verified clean:
  Lich Bane Spellblade (1.20.0) = 75% base AD + 40% AP magic
  Guinsoo's Wrath (1.14.0) = 30 flat magic on-hit
  Terminus Shadow (existing) = 30 magic on-hit constant

No production callsite affected outside the registry.

1.20.0 (UX-headless iter 3 / DS audit lane: Spellblade family,
2026-05-20): Lich Bane Spellblade AP coefficient corrected 50% -> 40%
per Meraki bulk 16.10.1 (the engine had drifted; current League math
is 75% base AD + 40% AP, not + 50% AP). 16.10.1 Meraki verifies:
"deals 75% base AD (+ 40% AP) bonus magic damage". Both 3100 (SR) and
223100 (Arena mirror) corrected; spellblade unique-passive family
membership unchanged (still shares the key with Trinity Force /
Iceborn / Sheen / Essence Reaver).

Other spellblade family members verified clean against Meraki:
  Trinity Force 3078 = 200% base AD physical (correct)
  Sheen 3057        = 100% base AD physical (correct)
  Essence Reaver 3508 = 125% base AD + 0.5/crit% physical (correct)
  Iceborn Gauntlet 6662 = 150% base AD physical (correct)

Spot-check Lich Bane drift on Ahri lvl 11 lone-item: weighted_dps 56.33
-> 52.996 (-5.9%; the AP term contributes less per proc); test pins
rebaselined in test_effects_expansion.py + test_spellblade_burst.py +
test_ability_item_proc_p1l22.py. No callsite outside the registry
affected.

1.19.0 (UX-headless iter 2, 2026-05-20): aramAbilityHaste +
aramTenacity exposure lane. Pre-fix the engine ignored both keys (a
comment in _apply_mode_modifiers said they "belong in their respective
consumers" but no scorer ever wired them). 22 champs carry non-zero
aramAbilityHaste in 16.10.1 (Soraka +10, Katarina +10, Azir +20,
Seraphine -20, Teemo -15, etc); 17 carry non-1.0 aramTenacity
(assassin-shaped +20% / +10% on Akali/Belveth/Ekko/Elise/Evelynn/Fizz/
Katarina/Kayn/Khazix/Lucian/Nunu/Pyke/Qiyana/Quinn/Rengar/Talon/Zed).
Both values now surface in the resolved stats dict via
``scaled['aram_ability_haste']`` (flat delta, default 0) and
``scaled['aram_tenacity_mult']`` (multiplier, default 1.0). Mode notes
carry the values when non-baseline. Exposure-only - no downstream
scorer consumes them yet; the data lane is now visible for the next
scorer iteration (a cooldown-cycle modifier in burst.py / ability_dps
or an effective-CC-duration term in an EHP-side enemy comp model).
Additive (no existing scorer math changes), 11 new tests pinning the
multiplier paths + SR-mode strip + live snapshot probes (Soraka +10,
Katarina +10/1.2, Seraphine -20).

1.18.0 (UX-headless iter 1, 2026-05-20): HPS split aramHealing /
aramShielding into per-side multipliers. Pre-fix the engine read
aramShieldsHealing with a fallback to aramHealing and applied that one
value to BOTH the healing_hps and shielding_hps lanes. The 16.10.1
Meraki bulk carries the two keys independently; 24 champions in the
snapshot have split values (Camille 1.20/1.10, LeeSin 1.10/1.20,
Milio 0.95/0.90, Nunu 1.10/1.20, Ahri 0.90/1.00, Alistar 0.80/1.00,
Annie 1.00/0.90, Bard 1.20/1.00, Briar 1.15/1.00, DrMundo 0.90/1.00,
Hecarim 1.20/1.00, Illaoi 0.80/1.00, Ivern 1.00/0.90, Janna 0.90/1.00,
Kayn 0.80/1.00, Khazix 1.20/1.00, Lux 1.00/0.90, Nocturne 1.20/1.00,
Rell 1.00/0.90, Renekton 1.10/1.00, Swain 0.80/1.00, Tryndamere
1.20/1.00, Vladimir 0.90/1.00, Zac 1.10/1.00). The collapsed single-
value mis-modeled the shield half on all 24. HpsResult gains heal_mult
and shield_mult fields; the prior single mode_multiplier is preserved
as a backward-compat property aliasing heal_mult so the healing-ratio
invariant test still holds. +9 deterministic tests pinning the 4
illustrative champ pairs from BACKLOG (Camille/LeeSin/Milio/Nunu),
the per-side application inside compute_hps, the SR/ARAM ratio match,
the mode_multiplier alias, and the legacy aramShieldsHealing-only
fallback for older snapshots. Source: Meraki bulk
/champions.json[name]/lolmath/aram_modifiers/{aramHealing,
aramShielding} 16.10.1 snapshot.

1.17.0 (Iter 16, 2026-05-20): Structural-drift resolution lane vs Meraki
bulk items 16.10.1 - the 2 items flagged by iter 15 closed in two
different ways. (a) Sundered Sky 6610 + Arena 226610 Lightshield
Strike recalibrated from pre-rework "20 + 200% base_ad" to
"70 + 80% (base_ad + bonus_ad)" - same long-CD periodic shape and
8s cadence, but constants tracked to the 16.10.1 spec
"60-80 bonus damage + 80% total critical damage modifier on the
next-AA empowered crit" (70 = midpoint of the 60-80 band; 0.8 *
total_AD approximates the empowered-crit delta-vs-normal-AA when
the 80% total-crit-modifier applies). Full re-encoding as a true
crit-guarantee burst proc deferred (would touch burst.py +
dps.py + CallContext crit-damage field). (b) Dead Man's Plate
3742 + Arena 223742 Shipwrecker flipped to defensive_only - the
Meraki 16.10.1 dual-track formula "0.4 * stacks (cap 40) +
stacks% (cap 100%) * base_ad" requires a Momentum stack
accumulation model the engine's periodic-proc schema doesn't
support yet. Principled deferral: Dead Man's is a TANK pick
where DPS contribution is incidental; defensive_only flip is
safer than carrying a stale flat-magnitude estimate. Test delta:
5 lightshield-burst-harness expected values rebaselined (140 ->
118, 70 -> 59 with armor); 5 DeadMansPlateShipwreckerTests rewritten
from active-periodic shape assertions to defensive_only + no-DPS-lift
assertions. defensive_only count crosses both thresholds upward
(assertGreaterEqual passes both s-31 >=40 and s-34 >=53 gates).
1.16.0 (Iter 15, 2026-05-20): Damage-magnitude lane audit vs Meraki bulk
items 16.10.1 - 16 hardcoded item proc constants cross-checked.
Two clean magnitude drifts fixed: (a) Hextech Alternator (3145) Revved
75 -> 65 bonus magic (Meraki: "Damaging an enemy champion deals 65
bonus magic damage"); (b) Voltaic Cyclosword Firmament (6699 + Arena
226699) "100 + 25% bonus_ad" -> flat 100 bonus physical (Meraki:
"next basic attack deals 100 bonus physical damage on-hit"; the 25%
bonus AD scaling clause was a pre-rework formula). Two structural
drifts FLAGGED but NOT fixed in this lane: (i) Sundered Sky 6610
Lightshield Strike now reads "60-80 critical damage + 80% total
crit damage modifier" - structurally different from the engine's
"20 + 200% base AD" pre-rework formula. (ii) Dead Man's Plate 3742
Shipwrecker new spec is "0.4 phys per Momentum stack, cap 40" plus
"+ 0-100% bonus MS modifier", dual-track vs engine's "100 + 45% * 20"
pre-rework formula. Both flagged for a follow-up structural-drift
iteration (next session). 12 items confirmed MATCH (Stormrazor 3097,
Kraken 6672 ramp, Statikk 3087, Rapid Firecannon 3094, Wit's End
3091, Guinsoo 3124 Wrath, Rageknife 6677, Recurve Bow 1043, Fated
Ashes 2508, Runaan 3085, Trinity 3078 Spellblade, Bami 6660 - all
verified against Meraki bulk effects strings). Test delta: 2 tests
updated (test_3145_hextech_alternator_revved_proc 75 -> 65; new
direct flat-proc assertion in test_voltaic_cyclosword_flat_proc).
1.15.0 (Iter 14, 2026-05-20): Arena mirror audit - synced two arena variants
to their already-fixed SR base entries. (a) 226676 The Collector promoted off
defensive_only and given lethality=10.0 to mirror iter-10 SR 6676 fix. (b)
223124 Guinsoo's Rageblade gained the Wrath +30 magic on-hit every-AA proc to
mirror iter-12 SR 3124 fix; Phantom Hit untouched. Audited 14 SR/Arena pairs
total (sunfire 223068 / dead-mans 223742 / titanic 223748 / hollow-radiance
226664 / nashor 223115 / wits-end 223091 / opportunity 226701 / LDR 223036 /
horizon 224628 / riftmaker 224633 / crown 224644 / statikk 223087) - parity
held on all except the two SR-recently-fixed items above. Endless Hunger
222517 verified defensive_only with no DPS contribution.
1.14.0 (Iter 12, 2026-05-20): Energized + spellblade + on-hit + cleave +
anti-tank family audit vs Meraki / DDragon 16.10.1. Cross-checked Statikk
Shiv / Rapid Firecannon / Stormrazor / Voltaic Cyclosword / Trinity Force
/ Lich Bane / Essence Reaver / Sundered Sky / Iceborn Gauntlet / Wit's End
/ Nashor's Tooth / Kraken Slayer / Runaan's Hurricane / Guinsoo's Rageblade
/ Terminus / Blade of the Ruined King / Stridebreaker / Profane Hydra /
Giant Slayer (LDR + Bork). One drift fixed: Guinsoo's Rageblade was
missing its Wrath flat-magic on-hit (DDragon 16.10.1 entry 3124 SR: "Wrath:
Attacks deal 30 bonus magic damage on-hit" - permanent, every AA, separate
from Phantom Hit every-3rd proc). Added as a 2nd PeriodicProc entry on
3124. Voltaic Cyclosword (4s charge), Statikk Shiv (180 magic / 10s),
Rapid Firecannon (40 magic / ~3s), Stormrazor (100 magic / 4s), Lich Bane
(75% base AD + 50% AP magic), Trinity Force (200% base AD), Essence Reaver
(125% base AD + crit lerp), Iceborn (150% base AD), Sundered Sky (20 + 200%
base AD / 8s), Nashor's (15 + 20% AP magic on-hit), Kraken (Bring It Down
150->200 every 3rd AA, level-stepped), Runaan's (2x 55% total AD bolts),
Terminus (30 magic on-hit + 10/10 pen), Bork (9% target HP on-hit melee),
Wit's End (45 magic on-hit), Stridebreaker / Profane Hydra (40% AD cleave),
Giant Slayer LDR (15% / 1500 bonus HP) all already on Meraki 16.10.1
values. Old Tiamat (id 3077) is currently a stat-only assassin component,
no DPS proc to model (the cleave moved to Tiamat upgrades like
Stridebreaker / Titanic Hydra / Profane Hydra). Vampiric Scepter (1053)
and Cull (1083) are early components, defensive-side only.
1.13.0 (Iter 11, 2026-05-20): Level-scaling-formula audit lane vs Meraki
16.10.1. Walked every "level"-keyed lambda in _effects_data.py and cross-
checked Statikk Shiv / Rapid Firecannon / Stormrazor / Voltaic Cyclosword
/ Sundered Sky / Riftmaker / Demonic Embrace / Liandry's / Heartsteel /
The Collector / Eclipse / BotRK against the Meraki bulk-items endpoint
stored at data/daemon_slayer/16.10.1/items_meraki.json. ONE drift caught:
Statikk Shiv (3087) and its Arena mirror (223087) carried
bonus_damage=110 every_n_seconds=3 (~36.7 magic/s) - an iter-7 era stale
magnitude. Meraki 16.10.1 "Electrospark" is 3 attacks x 60 bonus magic
within 8s on a 25->10s cooldown ramp (pp|25 to 10 for 6; L6+ steady-
state 10s). Engine now encodes payload-per-cycle: bonus_damage=180,
every_n_seconds=10 = 18 magic/s steady-state (same encoding shape as
Kraken/Stormrazor: per-cooldown-cycle, NOT per-attack). Proc renamed
"Electroshock" -> "Electrospark" to match Meraki's actual name (the
"Electroshock" passive is the takedown-CD-reset secondary, not the
main 3-attack chain). +7 audit tests in
StatikkShivElectrosparkMagnitudeTests pinning magnitude, cadence,
proc name, magical damage type, and Aatrox-L11 net-positive sanity.
Other 11 lerp/per-level/level-gated sites confirmed correct vs Meraki:
Rapid Firecannon 40 flat magic on-hit, Stormrazor 100 flat magic on-hit,
Voltaic Cyclosword 100 + 25% bonus_ad physical + 10 lethality, Sundered
Sky's 20+200%-base-AD approximation kept (refactoring the
critical-damage-by-level 60-80 + 80% bonus-crit-damage form would
require a guaranteed-crit schema lift, out of scope for this drift
pass), Riftmaker's 8% damage_amp at max stacks (not level-ramped),
Liandry's 1% target_max_hp burn per tick (not level-ramped), Heartsteel
70 + 6% max_hp (not level-ramped per Meraki 16.10.1 text), Eclipse's
6% target_max_hp (not level-ramped), Demonic Embrace's ramp is
health-missing-driven not level-driven, BotRK 9% target_max_hp pinned
in iter-7. The Collector executes at 5% max HP (already correct;
the task hint "15% missing HP, NOT level-scaled" was a misread - the
actual Meraki spec is 5% max HP, also NOT level-scaled, engine right).
Streak: iter-11 lane=level-scaling-formulas FOUND drift (Statikk
Shiv); resets to 1/10.
1.12.0 (Iter 10, 2026-05-20): Lethality + flat-pen audit lane vs Community
Dragon 16.10 ground truth. Probed the engine entries for all 21 items in
the audit set (8 lethality legendaries, 5 components, 4 Last-Whisper-family
%-armor-pen, 5 magic-pen items, Hextech Alternator component) plus the
2 Arena IDs (Deathblade 228003, Spectral Cutlass 4004) and pulled CD's
16.10 description blob for every one. 20 of 21 match exactly: Hubris,
Youmuu's, Edge of Night, Voltaic Cyclosword (10 with Firmament active is
correct), Axiom Arc, Umbral Glaive, Duskblade, Serrated Dirk all at
18/15/10/18/18/18/10 lethality; Long Sword 0; Last Whisper 18%, LDR /
Serylda's 35%, Mortal Reminder 30% (NOT 35 - wiki recall was wrong, CD
confirms 30); Sorc Shoes 12 flat MP, Void Staff 40% MP pen, Shadowflame
15 flat MP, Hextech Alternator 0 (component, no pen); Spectral Cutlass
15, Deathblade 20. ONE drift: The Collector (6676) carries 10 Lethality
in the stat block but had defensive_only=True with lethality=0.0 - the
original entry was tagged for the Death execute (correctly NOT a per-
rotation DPS proc) but the lethality plumbing batch (30) never promoted
Collector off defensive_only the way it did Hubris / Youmuu's. The
execute stays zero-rotation-DPS; the 10 Lethality stat block contributes
to the rest of the rotation. Fix: promote off defensive_only, pin
lethality=10.0, expand the note. +1 test in test_effects_expansion.py
(Batch29DefensiveOnlyCoverageTests). Streak update: iter-10 lane=lethality
-and-flat-pen FOUND drift (not no-change), streak resets to 1/10.
1.11.0 (Iter 8, 2026-05-20): Immolate family + Titanic Hydra Cleave drift vs
Meraki 16.10.1. Iter 7 BotRK fix triggered a wider audit of every
percentage-of-stat hit (`* c.<stat>_(hp|ad|ap)`). Four more drifts caught:
(1) Sunfire Aegis 3068 Immolate "12 + 1.5% bonus_hp" -> Meraki "20 + 1%
bonus_hp"; (2) Hollow Radiance 6664 "12 + 1.5% bonus_hp" -> "15 + 1%
bonus_hp"; (3) Bami's Cinder 6660 "12 + 1% bonus_hp" -> flat 15 (no HP
scaling at component tier - upgrades carry the HP scaling); (4) Titanic
Hydra 3748 Cleave "5 + 1.5% bonus_hp" primary + "40% total AD" cleave-
to-nearby -> "1% max_hp" primary + "3% max_hp" to nearby (shape change:
bonus_hp -> max_hp; AD-coefficient -> max_hp-coefficient). Engine pins
the melee value, same convention as Iter 7 BotRK / Eclipse / Hullbreaker
/ Kraken. All four SR items + their four Arena mirrors (223068, 226664,
226660, 223748) patched in lockstep. Schemas unchanged - dedup keys
(immolate, hydra_cleave), every_n_seconds/attacks, periodics arity all
stay - only the lambda magnitudes shift. +15 new audit tests in
test_meraki_formula_audit_pipeline_a.py and 12 existing tests
rebaselined to the corrected values. py_compile + ruff clean.
1.10.2 (Iter 7, 2026-05-20): BotRK Mist's Edge magnitude vs Meraki 16.10.1
- was 8% target_max_hp (stale comment claimed "melee value; ranged 5%"),
Meraki actually carries 9% melee / 6% ranged. Pipeline-A audit on
2026-05-19 corrected 5 items vs Meraki but missed BotRK; this is the
follow-up. Both SR 3153 and Arena mirror 223153 patched. Engine still
pins to the melee value (convention shared with Eclipse, Kraken,
Hullbreaker). target_max_hp steady-state approximation unchanged
(deliberate, documented at proc site). Riot's 100 damage cap vs
minions/monsters not modeled - champion DPS only.
1.10.1 (Iter 3, 2026-05-19): hydra_cleave unique-passive family. All 4
SR Tiamat-tree items (Ravenous Hydra 3074, Titanic Hydra 3748,
Stridebreaker 6631, Profane Hydra 6698) + their 4 Arena mirrors
(223074 / 223748 / 226631 / 226698) now declare
unique_passive_key="hydra_cleave" so collect_effects's first-seen-wins
dedup and the ranker's shares_dead_unique filter handle both layers
in one shot. Previously the comment on Profane Hydra claimed
"Tiamat-tree exclusivity is enforced by the ranker's build legality
checks", but rank._filter_candidates has no such check - the engine
was double-counting the Cleave proc on any 2+ hydra build and the
ranker happily recommended a second hydra. Live League marks Cleave
as a "Unique" passive (only one procs per AA). +9 tests in
test_hydra_cleave_unique_iter3.py covering schema, collect_effects
dedup, DPS no-double-count, and ranker filter behavior; 1 stale
negative-assertion test flipped (test_profane_hydra_not_tagged
_unique_passive -> _tagged_hydra_cleave_iter3). Build-order planner
docstring updated 3-family -> 7-family count for accuracy. No
rebaselines outside the flipped test.
