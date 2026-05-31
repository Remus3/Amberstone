"""Per-item flat Ability Haste registry.

DDragon's structured ``items.json.data[id].stats`` block does NOT carry
``AbilityHaste`` as a stat key (only as a ``tags`` entry); the numeric
value lives inside the localized description text as
``<attention>N</attention> Ability Haste`` inside the leading
``<stats>...</stats>`` block. Meraki bulk strips per-item stats. So
this registry is the canonical source for engine-side AH lookup.

ENGINE 1.24.0 (2026-05-21): wired into ``ability_dps.compute_ability_dps``
via ``total_item_ability_haste(item_ids)`` -> ``_total_ability_haste(
base_ah=...)`` so per-spell cooldowns reflect the build's full item-AH.
Prior to this lane the engine passed ``base_ah=0.0`` (floor case);
SR builds with Cosmic Drive + Frozen Heart now correctly compress
spell cooldowns via the Riot canonical ``eff_cd = base / (1 + h/100)``
formula already shipped in ``_effective_ability_cd`` (1.23.0).

Regeneration: when DDragon ships a new patch, re-run::

    py tools/regen_item_ability_haste.py <patch> > _item_ability_haste_new.py

then diff + replace ``_ITEM_ABILITY_HASTE`` below. The generator parses
``<attention>N</attention> Ability Haste`` from the first ``<stats>``
block of each item description; subsequent matches (Mythic-passive AH
grants, proc-on-takedown AH) are intentionally ignored - the static
lane carries only the build-time base stat. Patch 16.10.1: 220 items.

The registry is keyed by string item_id to match the engine's
``resolved.item_ids`` tuple shape (strings throughout).
"""

from __future__ import annotations

from typing import Iterable


_ITEM_ABILITY_HASTE: dict[str, float] = {
    "1111":  10.0,  # Jarvan I's
    "2020":  10.0,  # The Brutalizer
    "2022":   5.0,  # Glowing Mote
    "2049":  20.0,  # Guardian's Amulet
    "2050":  15.0,  # Guardian's Shroud
    "2065":  15.0,  # Shurelya's Battlesong
    "2502":  15.0,  # Unending Despair
    "2503":  20.0,  # Blackfire Torch
    "2510":  20.0,  # Dusk and Dawn
    "2520":  15.0,  # Bastionbreaker
    "2522":  10.0,  # Actualizer
    "2524":  15.0,  # Bandlepipes
    "2525":  20.0,  # Protoplasm Harness
    "3001":  20.0,  # Evenshroud
    "3003":  25.0,  # Archangel's Staff
    "3004":  15.0,  # Manamune
    "3011":  15.0,  # Chemtech Putrifier
    "3023":   5.0,  # Lifewell Pendant
    "3024":  10.0,  # Glacial Buckler
    "3039":  10.0,  # Atma's Reckoning
    "3040":  25.0,  # Seraph's Embrace
    "3042":  15.0,  # Muramana
    "3050":  10.0,  # Zeke's Convergence
    "3057":  10.0,  # Sheen
    "3065":  10.0,  # Spirit Visage
    "3067":  10.0,  # Kindlegem
    "3068":  10.0,  # Sunfire Aegis
    "3071":  20.0,  # Black Cleaver
    "3074":  15.0,  # Ravenous Hydra
    "3078":  15.0,  # Trinity Force
    "3100":  10.0,  # Lich Bane
    "3105":  10.0,  # Aegis of the Legion
    "3107":  15.0,  # Redemption
    "3108":  10.0,  # Fiendish Codex
    "3109":  10.0,  # Knight's Vow
    "3110":  20.0,  # Frozen Heart
    "3115":  15.0,  # Nashor's Tooth
    "3118":  15.0,  # Malignance
    "3119":  15.0,  # Winter's Approach
    "3121":  15.0,  # Fimbulwinter
    "3128":  10.0,  # Deathfire Grasp
    "3133":  10.0,  # Caulfield's Warhammer
    "3137":  20.0,  # Cryptbloom
    "3152":  20.0,  # Hextech Rocketbelt
    "3156":  15.0,  # Maw of Malmortius
    "3158":  10.0,  # Ionian Boots of Lucidity
    "3165":  15.0,  # Morellonomicon
    "3171":  20.0,  # Crimson Lucidity
    "3177":  15.0,  # Guardian's Blade
    "3179":  15.0,  # Umbral Glaive
    "3190":  10.0,  # Locket of the Iron Solari
    "3193":  15.0,  # Gargoyle Stoneplate
    "3222":  15.0,  # Mikael's Blessing
    "3430":  15.0,  # Rite Of Ruin
    "3508":  20.0,  # Essence Reaver
    "3802":  10.0,  # Lost Chapter
    "4005":  20.0,  # Imperial Mandate
    "4010":  15.0,  # Bloodletter's Curse
    "4011":  15.0,  # Sword of Blossoming Dawn
    "4016":  25.0,  # Wordless Promise
    "4402":  10.0,  # Innervating Locket
    "4403":  20.0,  # The Golden Spatula
    "4628":  25.0,  # Horizon Focus
    "4629":  25.0,  # Cosmic Drive
    "4633":  15.0,  # Riftmaker
    "4636":  25.0,  # Night Harvester
    "4638":  10.0,  # Watchful Wardstone
    "4642":  10.0,  # Bandleglass Mirror
    "4643":  20.0,  # Vigilant Wardstone
    "4644":  20.0,  # Crown of the Shattered Queen
    "6333":  15.0,  # Death's Dance
    "6609":  15.0,  # Chempunk Chainsword
    "6610":  10.0,  # Sundered Sky
    "6616":  10.0,  # Staff of Flowing Water
    "6617":  20.0,  # Moonstone Renewer
    "6620":  20.0,  # Echoes of Helia
    "6630":  20.0,  # Goredrinker
    "6632":  20.0,  # Divine Sunderer
    "6655":  10.0,  # Luden's Echo
    "6656":  20.0,  # Everfrost
    "6660":   5.0,  # Bami's Cinder
    "6662":  15.0,  # Iceborn Gauntlet
    "6664":  10.0,  # Hollow Radiance
    "6667":  10.0,  # Radiant Virtue
    "6691":  15.0,  # Duskblade of Draktharr
    "6692":  15.0,  # Eclipse
    "6693":  15.0,  # Prowler's Claw
    "6694":  15.0,  # Serylda's Grudge
    "6696":  20.0,  # Axiom Arc
    "6697":  10.0,  # Hubris
    "6698":  10.0,  # Profane Hydra
    "6699":  10.0,  # Voltaic Cyclosword
    "8001":  20.0,  # Anathema's Chains
    "8010":  15.0,  # Bloodletter's Curse
    "8020":  15.0,  # Abyssal Mask
    "123430":  10.0,  # Rite of Ruin
    "124011":  15.0,  # Sword of Blossoming Dawn
    "126697":  10.0,  # Hubris
    "222022":   5.0,  # Glowing Mote
    "222065":  15.0,  # Shurelya's Battlesong
    "222502":  10.0,  # Unending Despair
    "222503":  20.0,  # Blackfire Torch
    "222510":  20.0,  # Dusk and Dawn
    "222522":  10.0,  # Actualizer
    "222524":  10.0,  # Bandlepipes
    "222525":  15.0,  # Protoplasm Harness
    "223001":  20.0,  # Evenshroud
    "223003":  25.0,  # Archangel's Staff
    "223004":  15.0,  # Manamune
    "223011":  15.0,  # Chemtech Putrifier
    "223040":  25.0,  # Seraph's Embrace
    "223042":  15.0,  # Muramana
    "223050":  15.0,  # Zeke's Convergence
    "223057":  10.0,  # Sheen
    "223065":  10.0,  # Spirit Visage
    "223067":  10.0,  # Kindlegem
    "223068":  10.0,  # Sunfire Aegis
    "223069":  25.0,  # Void Immolation
    "223071":  20.0,  # Black Cleaver
    "223074":  15.0,  # Ravenous Hydra
    "223078":  20.0,  # Trinity Force
    "223100":  20.0,  # Lich Bane
    "223105":  10.0,  # Aegis of the Legion
    "223107":  15.0,  # Redemption
    "223109":  15.0,  # Knight's Vow
    "223110":  15.0,  # Frozen Heart
    "223112":  25.0,  # Guardian's Orb
    "223115":  10.0,  # Nashor's Tooth
    "223118":  20.0,  # Malignance
    "223119":  15.0,  # Winter's Approach
    "223121":  15.0,  # Fimbulwinter
    "223137":  15.0,  # Cryptbloom
    "223152":  20.0,  # Hextech Rocketbelt
    "223156":  15.0,  # Maw of Malmortius
    "223158":  40.0,  # Ionian Boots of Lucidity
    "223165":  15.0,  # Morellonomicon
    "223172":  30.0,  # Zephyr
    "223177":  15.0,  # Guardian's Blade
    "223185":  10.0,  # Guardian's Dirk
    "223190":  25.0,  # Locket of the Iron Solari
    "223193":  15.0,  # Gargoyle Stoneplate
    "223508":  20.0,  # Essence Reaver
    "224005":  35.0,  # Imperial Mandate
    "224403":  20.0,  # The Golden Spatula
    "224628":  25.0,  # Horizon Focus
    "224629":  35.0,  # Cosmic Drive
    "224633":  15.0,  # Riftmaker
    "224636":  25.0,  # Night Harvester
    "224644":  20.0,  # Crown of the Shattered Queen
    "226333":  10.0,  # Death's Dance
    "226609":  15.0,  # Chempunk Chainsword
    "226610":  10.0,  # Sundered Sky
    "226616":  15.0,  # Staff of Flowing Water
    "226617":  30.0,  # Moonstone Renewer
    "226620":  30.0,  # Echoes of Helia
    "226630":  20.0,  # Goredrinker
    "226632":  20.0,  # Divine Sunderer
    "226655":  25.0,  # Luden's Echo
    "226656":  20.0,  # Everfrost
    "226660":   5.0,  # Bami's Cinder
    "226662":  10.0,  # Iceborn Gauntlet
    "226664":  10.0,  # Hollow Radiance
    "226667":  10.0,  # Radiant Virtue
    "226691":  15.0,  # Duskblade of Draktharr
    "226692":  10.0,  # Eclipse
    "226693":  15.0,  # Prowler's Claw
    "226694":  10.0,  # Serylda's Grudge
    "226696":  20.0,  # Axiom Arc
    "226697":  10.0,  # Hubris
    "226698":  15.0,  # Profane Hydra
    "226699":  20.0,  # Voltaic Cyclosword
    "228001":  20.0,  # Anathema's Chains
    "228020":  15.0,  # Abyssal Mask
    "322065":  15.0,  # Shurelya's Battlesong
    "323003":  25.0,  # Archangel's Staff
    "323004":  15.0,  # Manamune
    "323040":  25.0,  # Seraph's Embrace
    "323042":  15.0,  # Muramana
    "323050":  10.0,  # Zeke's Convergence
    "323107":  15.0,  # Redemption
    "323109":  10.0,  # Knight's Vow
    "323110":  25.0,  # Frozen Heart
    "323119":  15.0,  # Winter's Approach
    "323121":  15.0,  # Fimbulwinter
    "323190":  10.0,  # Locket of the Iron Solari
    "323222":  15.0,  # Mikael's Blessing
    "324005":  20.0,  # Imperial Mandate
    "326616":  10.0,  # Staff of Flowing Water
    "326617":  20.0,  # Moonstone Renewer
    "326620":  20.0,  # Echoes of Helia
    "328020":  15.0,  # Abyssal Mask
    "443061":  30.0,  # Force Of Entropy
    "443062":  20.0,  # Sanguine Gift
    "443063":  25.0,  # Eleisa's Miracle
    "443193":  15.0,  # Gargoyle Stoneplate
    "444636":  25.0,  # Night Harvester
    "444644":  25.0,  # Crown of the Shattered Queen
    "446632":  20.0,  # Divine Sunderer
    "446656":  25.0,  # Everfrost
    "446691":  20.0,  # Duskblade of Draktharr
    "446693":  20.0,  # Prowler's Claw
    "447101":  40.0,  # Gambler's Blade
    "447103":  30.0,  # Hemomancer's Helm
    "447104":  20.0,  # Innervating Locket
    "447105":  30.0,  # Empyrean Promise
    "447108":  20.0,  # Runecarver
    "447112":  20.0,  # Flesheater
    "447113":  20.0,  # Detonation Orb
    "447116":  30.0,  # Kinkou Jitte
    "447118":  15.0,  # Pyromancer's Cloak
    "447119":  20.0,  # Lightning Rod
    "447122":  25.0,  # Black Hole Gauntlet
    "447123":  40.0,  # Puppeteer
    "663172":  25.0,  # Zephyr
    "663193":  10.0,  # Gargoyle Stoneplate
    "664011":  10.0,  # Sword of Blossoming Dawn
    "664403":  20.0,  # The Golden Spatula
    "664644":  15.0,  # Crown of the Shattered Queen
    "667101":  10.0,  # Gambler's Blade
    "994403":  20.0,  # Golden Spatula
}


def item_ability_haste(item_id: str | int) -> float:
    """Return the flat AH grant for a single item id, or 0.0 if unknown."""
    return _ITEM_ABILITY_HASTE.get(str(item_id), 0.0)


def total_item_ability_haste(item_ids: Iterable[str | int]) -> float:
    """Sum flat AH across the build's item ids.

    Items not in the registry contribute 0 (no warning - many DDragon
    item ids are boots/consumables/wards with no AH). Duplicate item ids
    contribute multiplicatively per occurrence per League's stat-stack
    rules (the engine's build planner enforces inventory cap and the
    s81/s82 unique-passive doctrine separately).

    Delegates per-item to ``item_ability_haste`` so the single-item
    accessor and the sum share one lookup path (no duplicate dict-get).
    """
    return sum(item_ability_haste(iid) for iid in item_ids)


def effective_cooldown(base_cd: float, ability_haste: float) -> float:
    """Riot canonical post-haste cooldown ``eff_cd = base_cd / (1 + AH/100)``.

    Single source for the haste-CDR formula shared by the ability-DPS
    scorer (``ability_dps._effective_ability_cd``) and the bounded-mana
    rotation walker (``mana_sim``). Before this helper each re-implemented
    the same arithmetic inline (ENGINE 1.23.0 ability side; item 234 mana
    side).

      * ``base_cd <= 0`` -> 0.0 (locked / pre-rank spells).
      * ``ability_haste == 0`` -> identity (eff_cd == base_cd).
      * ``ability_haste > 0`` -> shorter eff_cd.
      * ``ability_haste < 0`` (event-mode penalties) -> longer eff_cd.

    The denominator is floored at 0.01 so a hypothetical
    ``ability_haste <= -100`` stays finite + monotone-increasing rather
    than dividing by zero / inverting. Real engine values never approach
    that edge; the floor keeps the helper robust to test extremes.
    """
    if base_cd <= 0:
        return 0.0
    denom = 1.0 + float(ability_haste) / 100.0
    if denom < 0.01:
        denom = 0.01
    return float(base_cd) / denom
