"""Daemon Slayer — local item-build engine.

Phase 2 step 4 + Phase 3 + Phase 4: stat math + auto-attack DPS layered
with per-item conditional effects from ``effects.py``, single-slot item
ranking (``rank.py``), and full-build beam search (``beam.py``).

Effects coverage: IE / Kraken / Stormrazor / BT / Shieldbow (thin slice)
plus the energized family (Statikk Shiv, Rapid Firecannon, Voltaic),
scaling procs (Wit's End, Runaan's, Trinity Force, Sundered Sky,
Guinsoo's, Lich Bane, Nashor's Tooth), the armor pen / reduction layer
(LDR, Mortal Reminder, Black Cleaver), the symmetric magic pen layer
(Void Staff, Cryptbloom, Sorcerer's Shoes, Shadowflame — Phase 4
batch 4, 2026-05-04), the target-HP layer (BotRK Mist's Edge,
Eclipse Ever Rising Moon — Phase 4 batch 5, 2026-05-04), the
caster-HP layer (Titanic Hydra Cleave, Heartsteel Colossal
Consumption — Phase 4 batch 6, 2026-05-04), the multi-target rotation
layer (Ravenous Hydra Cleave — Phase 4 batch 7, 2026-05-04), the
multi-proc-per-item schema (Titanic Hydra cleave-to-others — Phase 4
batch 8, 2026-05-04), Immolate items (Sunfire Aegis, Hollow Radiance —
Phase 4 batch 9, 2026-05-04, reusing the caster-HP + multi-target
layers with no new schema), unique-passive enforcement (Phase 4
batch 10, 2026-05-04 — ItemEffect.unique_passive_key + dedup in
collect_effects; first user is "immolate" tagging Sunfire + Hollow
Radiance), spellblade unique-passive (Phase 4 batch 11, 2026-05-04 —
Trinity Force + Lich Bane share a "spellblade" key; Sundered Sky's
distinct "Lightshield Strike" and Essence Reaver's defensive_only
entry intentionally untagged), lifeline unique-passive (Phase 4
batch 12, 2026-05-04 — Immortal Shieldbow + Sterak's Gage + Maw of
Malmortius share a "lifeline" key; Phantom Dancer's distinct
"Spectral Waltz" Ghost effect intentionally untagged), Terminus
promoted from defensive_only (Phase 4 batch 13, 2026-05-04 — Shadow
on-hit 30 magic per basic + Juxtaposition Dark sustained 10% armor
pen + 10% magic pen), build-wide damage amplifier schema (Phase 4
batch 14, 2026-05-04 — ItemEffect.damage_amp_pct + multiplicative
stacking via total_damage_amp_multiplier; first user is Riftmaker's
8% Void Corruption at full ramp), HP→AP cross-derivation (Phase 4
batch 15, 2026-05-04 — ItemEffect.ap_per_bonus_hp_pct + additive
helper total_bonus_ap_from_hp; Riftmaker's Void Infusion 2% bonus
HP → AP wired so Lich Bane / Nashor's Tooth procs see the converted
total), Stridebreaker (6631) Cleave + Essence Reaver (3508) Spellblade
promoted via the new CallContext.crit_chance schema (Phase 4 batch 21,
2026-05-04 — Stridebreaker mirrors Ravenous Hydra's 40% AD cleave to
other enemies in 350 radius; ER fires 1.25 * base_ad + 50 * crit_chance
once per ~3s spellblade rotation, joins the Trinity Force / Lich Bane
unique-passive dedup family, with the rewritten Trinity Force batch-11
comment closing the order-dependence question), Hextech Gunblade (3146)
Lightning Bolt promoted from defensive_only as a long-CD periodic
proc (Phase 4 batch 22, 2026-05-04 — 175→253 by level + 30% AP magic
damage, 40s cooldown, modeled with ``every_n_seconds=40.0``; same shape
as Sundered Sky's 8s Lightshield Strike with a far longer cadence;
the 25%/1.5s slow stays utility-only, not modeled), Iceborn Gauntlet
(6662) added to ITEM_EFFECTS as a new entry (Phase 4 batch 23,
2026-05-04 — 150% base AD bonus physical Spellblade variant joining
the Trinity Force / Lich Bane / Essence Reaver dedup family at the
shared ~3s ability-cast cadence; frost-field slow stays utility-only),
Profane Hydra (6698) added to ITEM_EFFECTS as a new entry (Phase 4
batch 24, 2026-05-04 — 40% AD melee Cleave to other enemies in 350
radius via the existing targets_in_rotation gate; matches
Stridebreaker's coefficient choice from batch 21; Heretical Cleave
active stays not-modeled per the s77/s78 actives-without-cooldown-pin
rule; Tiamat-tree exclusivity vs the other hydras is build-legality,
not unique-passive), Serylda's Grudge (6694) added to ITEM_EFFECTS as
a new entry (Phase 4 batch 25, 2026-05-04 — 35% armor pen joins the
LDR / Mortal Reminder family at the same coefficient as LDR; Bitter
Cold ability slow stays utility-only per the slow-without-damage
rule), Yun Tal Wildarrows (3032) + Atma's Reckoning (3039) paired
promotion via the new ItemEffect crit_chance_bonus_flat /
crit_chance_bonus_max_pct + per_bonus_hp_cap fields (Phase 4 batch 26,
2026-05-04 — Yun Tal pinned at full Wildarrows stacks 25%, Atma's
Big Hands linear ramp 0–30% over 0–3000 caster bonus HP; summed and
clamped at 1.0 in compute_dps so both auto-attack crit and ER's
Spellblade scaling see the boosted total; Yun Tal's Flurry AS bonus
intentionally not modeled), Manamune (3004) + Muramana (3042) paired
promotion via the new CallContext.caster_max_mp field +
ItemEffect.bonus_ad_pct_max_mp Awe wiring (Phase 4 batch 27, 2026-05-04
— Awe converts 2% max mana into bonus AD via the same engine-resolved
stat layer pattern as Sterak's bonus_ad_pct_base_ad from batch 20;
Muramana additionally fires Shock — 1.2% max mana per-attack physical —
via a periodic proc; Manaflow stack-up + Muramana's ability damage
piece intentionally not modeled), Archangel's Staff (3003) + Seraph's
Embrace (3040) paired promotion via the new
ItemEffect.bonus_ap_pct_bonus_mp field (Phase 4 batch 28, 2026-05-04 —
AP-side Awe twin; Archangel +1% / Seraph's +2% BONUS mana as AP, keyed
off item-contributed mana only — distinct from the Manamune family's
max-mana keying; engine walks ap_flat the same way the Manamune walk
targets ad_flat; Seraph's Lifeline shield piece tagged unique_passive_key
"lifeline" — Awe walk in engine.py bypasses collect_effects so the AP
contribution survives lifeline dedup), Phase 4 batch 29 coverage batch
(2026-05-04 — 6 items: 4 defensive_only entries [Hubris, Spirit Visage,
Kaenic Rookern, Cosmic Drive] + 2 partial promotions reusing existing
schema [Liandry's Torment via damage_amp_pct=0.06 for Suffering's
sustained 6% amp, Stormsurge via magic_pen_flat=15 joining Sorcerer's
Shoes / Shadowflame in the magic pen layer]; Hubris's 18 Lethality
deferred to a future "lethality plumbing" batch — needs level-scaled
flat pen schema), Phase 4 batch 30 lethality plumbing (2026-05-04 —
new ItemEffect.lethality field + level-scaled fold into
effective_target_armor's flat-pen sum (lethality × (0.6 + 0.4 × level/18));
7 items unlock simultaneously: Hubris (18), Voltaic Cyclosword (10),
Edge of Night (15), Youmuu's Ghostblade (18), Opportunity (18) all
promoted from defensive_only-or-stats-only-prior, plus Axiom Arc (18)
+ Umbral Glaive (18) as new entries — all 7 current-patch lethality
items now carry the level-scaled flat pen contribution), Phase 4 batch
31 support/ramp coverage sweep (2026-05-04 — 21 items: Dead Man's Plate
(3742) Shipwrecker partial promotion via periodic proc every_n_attacks=4
~109 physical at full Momentum stacks; Spectral Cutlass (4004) ARAM-only
lethality=15 promotion joining the batch-30 family; 19 defensive_only
entries for support/enchanter/tank items [Knight's Vow, Mikael's Blessing,
Redemption, Locket, Ardent Censer, Staff of Flowing Water, Echoes of Helia,
Moonstone Renewer, Dawncore, Imperial Mandate, Rod of Ages, Winter's Approach,
Fimbulwinter, Force of Nature, Rylai's Crystal Scepter, Jak'Sho the Protean,
Hextech Rocketbelt, Experimental Hexplate, Abyssal Mask]), Phase 4 batch 32 AP amplification + lethality + new schema
(2026-05-04 — 15 items: Rabadon's Deathcap (3089) via new
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
(2026-05-04 — 4 active promotions: Gambler's Blade (667101) 15 lethality
+ 15 magic pen flat dual-pen [DDragon Adaptive Force gap noted]; Unending
Despair (2502) Agony 3% caster bonus HP magic every 4s via existing
caster_bonus_hp schema; Blackfire Torch (2503) Baleful Blaze 6 + 6% AP
magic every 0.5s promoted from defensive_only [ranged Meraki value];
Demonic Embrace (4637) gains second proc Azakana's Gaze 1% target max
HP/s magic burn [ranged value]; plus 7 defensive_only entries: Night
Harvester, Fiendhunter Bolts, Sword of the Divine, Flesheater, Sword of
Blossoming Dawn, Actualizer, Cruelty). Phase 4 batch 34 magic-amp schema
(2026-05-04 — new ItemEffect.magic_amp_pct field +
total_magic_amp_multiplier helper + per-proc application in
_periodic_proc_dps; does NOT amplify physical auto-attack damage;
Abyssal Mask (8020) promoted from defensive_only with magic_amp_pct=0.12
[Unmake 12% more magic damage to nearby enemies]). Phase 4 batch 35
missed-lethality + dual-pen + spellblade + on-hit sweep (2026-05-04 —
5 active promotions: Duskblade of Draktharr (6691) lethality=18
[missed from batch-30 lethality sweep]; Perplexity (4015) 22% armor pen
+ 30% magic pen dual-pen; Divine Sunderer (6632) Spellblade 125% base AD
+ 6% target max HP physical every 3s [joins spellblade dedup family];
Navori Flickerblade (6672) Bring It Down every-3rd-attack 120→168
physical [ranged scaling]; Hellfire Hatchet (4017) lethality=12 [Char
proc deferred]; plus 6 defensive_only entries: Goredrinker, Galeforce,
Zeke's Convergence, Wordless Promise, Frozen Mallet, Lightning Braid).
Phase 4 batch 36 Arena item sweep + Rite of Ruin crit (2026-05-04 —
6 active promotions: Detonation Orb (447113) magic_pen_flat=12;
Reverberation (447114) Resonate 10+2% caster bonus HP magic on-hit;
Pyromancer's Cloak (447118) Spark 100→350 magic burn every 5s;
Lightning Rod (447119) Call Lightning 135→230+30% bonus AD+50% AP+10%
target max HP magic every 16s; Regicide (447115) lethality=15; Rite of
Ruin (3430) crit_chance_bonus_flat=0.20 [max Wrath+Ruin stacks]; plus 6
defensive_only: Runecarver, Kinkou Jitte, Diamond-Tipped Spear,
Twilight's Edge, Decapitator, Mirage Blade). Phase 4 batch 37 TRUE damage type + Arena item sweep
(2026-05-04 — new ``TRUE = "true"``
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
sweep (2026-05-04 — new ``ItemEffect.giant_slayer_pct_per_100hp`` +
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
sweep (2026-05-04 — new ``ItemEffect.mr_reduction_pct`` field wired into
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
final SR/Arena sweep (2026-05-04 — 3 active promotions: Last Whisper
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
— fixes a batch-35 key collision where Navori Flickerblade was mistakenly
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
(2026-05-04 — 35 entries: 10 active [Unending Despair (222502), Blackfire
Torch (222503), Dusk and Dawn (222510) spellblade-key, Spectral Cutlass
(224004) lethality=15, Riftmaker (224633) damage_amp_pct=0.08, Shadowflame
(224645) magic_pen_flat=15, Stormsurge (224646) magic_pen_flat=15,
Archangel's ARAM (323003), Manamune ARAM (323004), Abyssal Mask ARAM
(328020) magic_amp_pct=0.12]; 25 defensive_only). Phase 4 batch 43
223xxx Arena mirrors (2026-05-04 — 58 entries: 33 active with same
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
— 19 entries: 5 proc-bearing components [Sheen (3057) Spellblade 100%
base AD every 1.5s spellblade-key, Tiamat (3077) Cleave 50% AD to nearby
via targets_in_rotation gate (zero single-target), Hextech Alternator
(3145) Revved 75 magic every 5s, Bami's Cinder (6660) Immolate
12+0.5% max HP magic/s immolate-key, Rageknife (6677) Wrath 20 magic
on-hit]; 3 full items with DPS contribution [Sword of the Divine (3131)
18 lethality + Divine Judgment 75% AD guaranteed-crit bonus every 15s,
Shield of the Rakkor (6700) stats-only (Rakkor Strike armor pen
conditional on active — not modeled), Evenshroud (3001) damage_amp_pct=0.06
(Coruscation 6% more damage — legacy removed-item entry)]; 11 stats-only
items [Zeal (3086), Serrated Dirk (3134) lethality=10, Caulfield's
Warhammer (3133), Executioner's Calling (3123), Lost Chapter (3802),
Oblivion Orb (3916), Fiendish Codex (3108), Aether Wisp (3113),
Hearthbound Axe (3051), Phage (3044), Ironspike Whip (6029)]).
Phase 4 batch 45 defensive full items + components + boots (2026-05-04
— 21 entries: 1 active [Berserker's Greaves (3006) 25% AS contribution];
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
(2026-05-04 — 22 entries: 9 active [Divine Sunderer (226632) Spellblade
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
Arena 22xxxx/32xxxx remaining pool + 221xxx components (2026-05-04 —
~42 entries: 8 active DPS procs [Evenshroud Arena (223001)
damage_amp_pct=0.06, Seraph's Embrace Arena (223040/323040)
bonus_ap_pct_bonus_mp=0.02 lifeline-key, Muramana Arena (223042/323042)
Shock 1.2% max mana physical on-hit + bonus_ad_pct_max_mp=0.02, Sheen
Arena (223057) Spellblade 100% base AD every 1.5s spellblade-key,
Stormrazor Arena (223095) Stormraider guaranteed-crit bonus every 30s,
Guardian's Dirk Arena (223185) lethality=11]; 7 221xxx Arena components
[221011/221026/221031/221043/221053/221057/221058 — stats-only]; 2
mini-consumables [222022/222141 — defensive_only]; 26 defensive_only
Arena mirrors [223002/067/069/105/111/112/121/158/172/177/184/193,
222051/065/524/526/530, 224403, 322065/526/530, 323002/070/121]).
Phase 4 batch 48 core 1xxx tier-1 components (2026-05-04 — 29 entries:
1 proc-bearing component [Recurve Bow (1043) Sting — 15 bonus physical
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
Phase 4 batch 49 remaining 3xxx/2xxx + final Arena pool (2026-05-04 —
~49 entries: 12 active [Spellslinger's Shoes (3175) magic_pen_flat=18 +
magic_pen_pct=0.08 — both pen layers; Gunmetal Greaves (3172) AS boots
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

Batch 64 (2026-05-05 — Stage 4: ult-cast schema, ENGINE_VERSION 0.60.0):
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

Phase 6 step 7 (2026-05-10 — per-level DPS curve helper, ENGINE_VERSION 0.61.0):
  Added ``compute_dps_curve()`` + ``DpsCurvePoint`` dataclass + ``DPS_CURVE_LEVELS``
  (1/6/11/16/18) to dps.py. Pure additive helper — calls ``compute_dps()`` at each
  level, returns a list of points with weighted DPS + phase + compact stat subset.
  No engine math change; no schema breakage. Unlocks coach hints like "Lulu peaks
  at lvl 6, falls off at 11". 12 new tests (35 total in test_dps).
"""

ENGINE_VERSION = "0.62.0"
