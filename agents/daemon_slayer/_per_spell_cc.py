"""Per-spell crowd-control duration registry (relocated from ability_dps.py,
item 241 A2).

A forward-marker hand-seeded registry: ``compute_ability_dps`` does not branch on
it; it flows to an API field and the cc_pressure / EHP-vs-CC consumers. Kept here
(not in ability_dps.py) because it is ~700 lines of data with only two referenced
helpers and zero coupling to the DPS math. ``ability_dps`` re-exports every public
symbol so existing ``from .ability_dps import _PER_SPELL_CC_DURATIONS`` imports and
the ``cc_pressure`` monkeypatch seam keep working unchanged.
"""
from __future__ import annotations

from .ehp import effective_cc_duration

# ENGINE 1.30.0 (2026-05-21) - per-spell CC duration registry seeded.
# Closes the item 130 carry-forward (b): this is the 2nd consumer of the
# ``effective_cc_duration`` helper shipped 1.25.0 (item 122). The helper
# itself lives in ``ehp.py`` (free function imported above); this slice
# exposes the downstream-consumer surface at the per-spell AbilityDps
# layer so a future EHP-vs-CC blended scorer (or fight-sim) can read
# per-rank base CC durations + the matching post-tenacity values without
# re-resolving the champion.
#
# ENGINE 1.29.0 shipped the seam EMPTY (forward-marker pattern mirroring
# item 112's ``STAT_GRANT_CALC_KEYS``). ENGINE 1.30.0 seeded a starter set
# of high-impact CC abilities at patch 16.10.1 (30 entries / 24 champs).
# ENGINE 1.31.0 (2026-05-21) extends the seed with wave 2: 23 additional
# entries across 20 additional champions, same first-order CC scope.
# ENGINE 1.33.0 (2026-05-22) extends the seed with wave 3: 14 additional
# entries across 14 additional champions of first-order CC at patch
# 16.10.1, same selection rules.
# ENGINE 1.34.0 (2026-05-22) extends the seed with wave 4: 15 additional
# entries across 15 additional champions, same selection rules.
# ENGINE 1.35.0 (2026-05-22) extends the seed with wave 5: 8 additional
# entries across 7 additional champions, same selection rules.
# ENGINE 1.36.0 (2026-05-22) schema lift to dict.setdefault builder
# pattern + wave 6: 5 additional entries (3 multi-wave augmentations of
# existing champion spell maps + 2 new champions). Total: 95 entries
# across 82 champions.
# All values from official Riot tooltips for FIRST-ORDER CC (stuns /
# roots / suspensions / knock-ups / knock-backs / charms / suppressions
# / polymorphs / sleeps / fear / taunts). Slows are NOT encoded
# (different math). Conditional CC (3rd-stack stuns like Brand R, Bard Q
# wall-bounce variant, Tahm Kench Q 3rd-stack stun) are skipped where
# the base semantic is unclear without a fight-sim observer.
#
# Engine math consumption is STILL FUTURE: today the values flow through
# AbilitySpellDps.cc_duration_s + .cc_duration_post_tenacity for API
# inspection (to_dict serialization) + future composition by a downstream
# fight-sim or EHP-vs-CC blended scorer. compute_ability_dps does not
# branch on the values; production DPS math is byte-identical to 1.29.0
# for every population case.
#
# Schema:
#   _PER_SPELL_CC_DURATIONS[champion_id][spell_key] = (cc_s_r1, ..., cc_s_r5)
# where ``champion_id`` is the DDragon id (e.g. ``"Annie"``, ``"MonkeyKing"``
# for Wukong), ``spell_key`` is one of ``{"Q","W","E","R"}``, and the
# tuple is per-rank base CC duration in seconds. Per-rank tuples are
# length 5 for Q/W/E and length 3 for R; some abilities have a single
# value across all ranks (e.g. Annie R 1.5s all 3 ranks). Single-value
# tuples like (1.5,) are also accepted - the engine reads the rank slot
# defensively (consumer behavior pinned by tests).
#
# ENGINE 1.36.0 SCHEMA LIFT: the registry is now constructed via a
# module-level builder function ``_build_per_spell_cc_durations`` which
# uses ``dict.setdefault(champ, {})[spell] = tuple`` to allow multi-wave
# augmentation of a single champion's spell map without dict-literal
# collision. Prior to 1.36.0 the registry was a single dict literal
# which clobbered prior-wave entries when a later wave added a new
# spell to the same champion. This blocked Lulu R + Sejuani Q + Thresh
# E (all rejected from wave 5 due to clobber). The builder runs ONCE
# at module import and assigns the result to _PER_SPELL_CC_DURATIONS
# below; consumer code reads the dict transparently.
def _build_per_spell_cc_durations() -> dict[str, dict[str, tuple[float, ...]]]:
    """Build the per-spell CC duration registry via setdefault.

    Returns a fresh dict of champion_id -> spell_key -> per-rank tuple.

    Uses ``setdefault(champ, {})[spell] = tuple`` so multiple waves can
    contribute spells to the same champion without clobbering prior-wave
    entries. The builder pattern replaces the single dict literal used
    1.30.0 through 1.35.0; production behavior of all 90 pre-1.36.0
    entries is byte-identical (value pins preserved).
    """
    registry: dict[str, dict[str, tuple[float, ...]]] = {}
    # ----- ENGINE 1.30.0 wave 1 (2026-05-21) -----
    # Initial seed: 30 entries across 24 champions of first-order CC at
    # patch 16.10. All values from Riot wiki + cdragon tooltips.
    # Ahri E - Charm: charm 1.0/1.25/1.5/1.75/2.0
    registry.setdefault("Ahri", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Annie R - Summon: Tibbers: stun on summon 1.5s all ranks
    registry.setdefault("Annie", {})["R"] = (1.5, 1.5, 1.5)
    # Ashe R - Enchanted Crystal Arrow: stun 1.5-3.5s based on travel
    # distance; use 1.5s as the minimum guaranteed floor across all ranks
    registry.setdefault("Ashe", {})["R"] = (1.5, 1.5, 1.5)
    # Blitzcrank Q - Rocket Grab: pull then 1.0s stun on connect all ranks
    registry.setdefault("Blitzcrank", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Cassiopeia R - Petrifying Gaze: stun 2.0s if facing (slow otherwise)
    # all ranks
    registry.setdefault("Cassiopeia", {})["R"] = (2.0, 2.0, 2.0)
    # Galio W - Shield of Durand: taunt 1.0s base on cast all ranks
    registry.setdefault("Galio", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Galio E - Justice Punch: knock-up 0.5s
    registry.setdefault("Galio", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Galio R - Hero's Entrance: knock-up 0.75s on landing
    registry.setdefault("Galio", {})["R"] = (0.75, 0.75, 0.75)
    # Leona Q - Shield of Daybreak: stun 1.25s all ranks
    registry.setdefault("Leona", {})["Q"] = (1.25, 1.25, 1.25, 1.25, 1.25)
    # Leona E - Zenith Blade: root 0.5s on connect
    registry.setdefault("Leona", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Leona R - Solar Flare: stun 1.5s in center
    registry.setdefault("Leona", {})["R"] = (1.5, 1.5, 1.5)
    # Lissandra R - Frozen Tomb: stun 1.5s on enemy-target cast all ranks
    registry.setdefault("Lissandra", {})["R"] = (1.5, 1.5, 1.5)
    # Lulu W - Whimsy: polymorph 1.25/1.5/1.75/2.0/2.25
    registry.setdefault("Lulu", {})["W"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Malzahar R - Nether Grasp: suppression 2.5s all ranks
    registry.setdefault("Malzahar", {})["R"] = (2.5, 2.5, 2.5)
    # Maokai R - Nature's Grasp: root 1.2/1.6/2.0
    registry.setdefault("Maokai", {})["R"] = (1.2, 1.6, 2.0)
    # MonkeyKing (Wukong) R - Cyclone: knock-up 1.0s on first hit
    registry.setdefault("MonkeyKing", {})["R"] = (1.0, 1.0, 1.0)
    # Morgana Q - Dark Binding: root 2.0/2.25/2.5/2.75/3.0
    registry.setdefault("Morgana", {})["Q"] = (2.0, 2.25, 2.5, 2.75, 3.0)
    # Nautilus Q - Dredge Line: root+pull 1.0/1.15/1.3/1.45/1.6
    registry.setdefault("Nautilus", {})["Q"] = (1.0, 1.15, 1.3, 1.45, 1.6)
    # Nautilus R - Depth Charge: knock-up 1.0/1.5/2.0 on final target
    registry.setdefault("Nautilus", {})["R"] = (1.0, 1.5, 2.0)
    # Pantheon W - Shield Vault: stun 1.0s all ranks
    registry.setdefault("Pantheon", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Rakan W - Grand Entrance: knock-up 1.0s all ranks
    registry.setdefault("Rakan", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Renekton W - Ruthless Predator: stun 0.75s base all ranks
    registry.setdefault("Renekton", {})["W"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Sejuani R - Glacial Prison: stun on travel-line 1.0/1.5/2.0
    registry.setdefault("Sejuani", {})["R"] = (1.0, 1.5, 2.0)
    # Sona R - Crescendo: stun 1.5s all ranks
    registry.setdefault("Sona", {})["R"] = (1.5, 1.5, 1.5)
    # Thresh Q - Death Sentence: stun 1.5s on connect all ranks
    registry.setdefault("Thresh", {})["Q"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Veigar E - Event Horizon: stun on edge cross 1.5s all ranks
    registry.setdefault("Veigar", {})["E"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Vi Q - Vault Breaker: knock-up 0.75s all ranks
    registry.setdefault("Vi", {})["Q"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Vi R - Cease and Desist: knock-up 1.0s on initial target
    registry.setdefault("Vi", {})["R"] = (1.0, 1.0, 1.0)
    # Yasuo R - Last Breath: knock-up 1.0s on cast (then airborne held
    # until end - approximate base trigger as 1.0)
    registry.setdefault("Yasuo", {})["R"] = (1.0, 1.0, 1.0)
    # Zoe E - Sleepy Trouble Bubble: drowsy then 2.0s sleep on contact
    registry.setdefault("Zoe", {})["E"] = (2.0, 2.0, 2.0, 2.0, 2.0)
    # ----- ENGINE 1.31.0 wave 2 (2026-05-21) -----
    # +23 entries across 20 new champions of first-order CC at patch 16.10.
    # Selection rules unchanged from wave 1 (stuns / roots / suspensions
    # / knock-ups / knock-backs / charms / sleeps / fear / suppressions);
    # no slows; no conditional CC (e.g. Tahm Kench Q 3rd-stack, Bard Q
    # wall-bounce variant). Values sourced from Riot wiki + cdragon
    # champion JSONs for patch 16.10.
    # Alistar Q - Pulverize: knock-up 1.0s all ranks
    registry.setdefault("Alistar", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Alistar W - Headbutt: knock-back 0.5s on contact all ranks
    registry.setdefault("Alistar", {})["W"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Amumu Q - Bandage Toss: stun 1.0/1.1/1.2/1.3/1.4 on pull
    registry.setdefault("Amumu", {})["Q"] = (1.0, 1.1, 1.2, 1.3, 1.4)
    # Amumu R - Curse of the Sad Mummy: stun 1.5/1.75/2.0 AOE
    registry.setdefault("Amumu", {})["R"] = (1.5, 1.75, 2.0)
    # Anivia Q - Flash Frost: stun 1.25s on detonation all ranks
    registry.setdefault("Anivia", {})["Q"] = (1.25, 1.25, 1.25, 1.25, 1.25)
    # Braum R - Glacial Fissure: knock-up 1.0s at center line all ranks
    registry.setdefault("Braum", {})["R"] = (1.0, 1.0, 1.0)
    # Chogath Q - Rupture: knock-up 1.0s on detonation all ranks
    registry.setdefault("Chogath", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Fiddlesticks Q - Terrify: fear 1.25/1.5/1.75/2.0/2.25
    registry.setdefault("Fiddlesticks", {})["Q"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Gnar R - GNAR!: knock-back 0.75s base displacement all ranks
    registry.setdefault("Gnar", {})["R"] = (0.75, 0.75, 0.75)
    # Gragas E - Body Slam: stun 1.0s on contact all ranks
    registry.setdefault("Gragas", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Jhin W - Deadly Flourish: root 0.75/1.0/1.25/1.5/1.75 on marked
    registry.setdefault("Jhin", {})["W"] = (0.75, 1.0, 1.25, 1.5, 1.75)
    # Lux Q - Light Binding: root 2.0/2.25/2.5/2.75/3.0 first target
    registry.setdefault("Lux", {})["Q"] = (2.0, 2.25, 2.5, 2.75, 3.0)
    # Nami Q - Aqua Prison: stun 1.5s all ranks
    registry.setdefault("Nami", {})["Q"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Neeko E - Tangle-Barbs: root 0.75/1.0/1.25/1.5/1.75
    registry.setdefault("Neeko", {})["E"] = (0.75, 1.0, 1.25, 1.5, 1.75)
    # Neeko R - Pop Blossom: stun 1.25s on activation all ranks
    registry.setdefault("Neeko", {})["R"] = (1.25, 1.25, 1.25)
    # Orianna R - Command: Shockwave: knock-up 1.0s all ranks
    registry.setdefault("Orianna", {})["R"] = (1.0, 1.0, 1.0)
    # Poppy E - Heroic Charge: stun 0.5s base on contact (wall stun
    # 1.5s is conditional on terrain - base 0.5s always fires)
    registry.setdefault("Poppy", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Rell W (Ferromancy: Crash Down) intentionally NOT modeled here -
    # the W toggle has a non-standard rank progression (split mount /
    # dismount semantics; knock-up duration scales with dash distance).
    # Riven W - Ki Burst: stun 0.75s AOE all ranks
    registry.setdefault("Riven", {})["W"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Singed E - Fling: knock-back 1.0s displacement all ranks
    registry.setdefault("Singed", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Skarner R - Impale: suppression 1.75/2.0/2.25 on grabbed target
    registry.setdefault("Skarner", {})["R"] = (1.75, 2.0, 2.25)
    # Varus R - Chain of Corruption: root 2.0s on root spread all ranks
    registry.setdefault("Varus", {})["R"] = (2.0, 2.0, 2.0)
    # Xerath E - Shocking Orb: stun 1.0/1.25/1.5/1.75/2.0 at min range
    # (longer with distance; floor pin for closest-target hit)
    registry.setdefault("Xerath", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Zac E - Elastic Slingshot: knock-up 1.0s on landing all ranks
    registry.setdefault("Zac", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # ----- ENGINE 1.33.0 wave 3 (2026-05-22) -----
    # +14 entries across 14 additional champions of first-order CC at
    # patch 16.10. Selection rules unchanged from wave 1 + wave 2
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms
    # / sleeps / fear / suppressions / polymorphs / taunts); no slows;
    # no conditional CC (Brand R 3rd-hit / TF W Gold Card / Tahm Q
    # 3rd-stack / Lillia R dream-stack / Volibear Q terrain / Urgot R
    # fear / Rell W mount/dismount toggle / Warwick R channel-gated);
    # no self-CC. Values sourced from Riot wiki + cdragon champion
    # JSONs for patch 16.10. Canonical DDragon ids ("Chogath" /
    # "MonkeyKing" / "AurelionSol" / "XinZhao" - punctuation-stripped
    # per _portraitUrl convention).
    # AurelionSol R - The Skies Descend / Falling Star: knock-up on
    # impact + stun in center (the center stun is the canonical
    # first-order CC value; knockup on first contact is wider but
    # shorter); pin the center stun 1.25/1.5/1.75 at ranks 1/2/3.
    registry.setdefault("AurelionSol", {})["R"] = (1.25, 1.5, 1.75)
    # Caitlyn W - Yordle Snap Trap: root 1.5s all ranks on triggered
    # trap (single value across all 5 ranks; trap duration scales with
    # rank but root duration is constant per the 16.10 tooltip).
    registry.setdefault("Caitlyn", {})["W"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Camille E - Hookshot / Wall Dive: stun 0.75s on second-cast
    # wall-dive contact all ranks (single value across 5 ranks).
    registry.setdefault("Camille", {})["E"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Diana R - Moonfall: knock-up 0.75s on pull (single value all
    # 3 ranks; rank scales damage + cooldown, not the CC duration).
    registry.setdefault("Diana", {})["R"] = (0.75, 0.75, 0.75)
    # Elise E (human form) - Cocoon: stun 1.1/1.4/1.7/2.0/2.3 across
    # 5 ranks (one of the longest single-target stuns at min rank).
    registry.setdefault("Elise", {})["E"] = (1.1, 1.4, 1.7, 2.0, 2.3)
    # Heimerdinger E - CH-2 Electron Storm Grenade: stun 1.25s on
    # primary target all 4 ranks (E maxes at rank 4 not 5; engine
    # canonical 5-rank shape, pin rank-5 slot to rank-4 value).
    registry.setdefault("Heimerdinger", {})["E"] = (
        1.25, 1.25, 1.25, 1.25, 1.25,
    )
    # Ivern Q - Rootcaller: root 1.0/1.25/1.5/1.75/2.0 across 5 ranks
    # (ally dash after root not modeled - it is an ally interaction,
    # not enemy CC).
    registry.setdefault("Ivern", {})["Q"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Malphite R - Unstoppable Force: knock-up 1.5/1.75/2.0 across
    # 3 ranks (Malphite's signature ult CC value).
    registry.setdefault("Malphite", {})["R"] = (1.5, 1.75, 2.0)
    # Pyke Q - Bone Skewer: stun 1.25s on the pulled/skewered target
    # all 5 ranks (the ranged-Q-on-cast charge stuns; pin the
    # constant value).
    registry.setdefault("Pyke", {})["Q"] = (1.25, 1.25, 1.25, 1.25, 1.25)
    # Rell Q - Shattering Strike: root 1.0s on hit all 5 ranks
    # (single value; Rell W is intentionally NOT modeled per the
    # mount/dismount toggle skip rule).
    registry.setdefault("Rell", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Ryze W - Rune Prison: root 0.75/1.0/1.25/1.5/1.75 across
    # 5 ranks (Ryze's signature W root).
    registry.setdefault("Ryze", {})["W"] = (0.75, 1.0, 1.25, 1.5, 1.75)
    # Sion Q - Decimating Smash: stun 1.25/1.5/1.75/2.0/2.25 at full
    # charge across 5 ranks (the minimum charge stuns shorter but the
    # full-charge value is the canonical max-rank pin).
    registry.setdefault("Sion", {})["Q"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Tristana R - Buster Shot: knock-back 1.0s on hit all 3 ranks
    # (the displacement is brief; pin the constant value).
    registry.setdefault("Tristana", {})["R"] = (1.0, 1.0, 1.0)
    # XinZhao W - Wind Becomes Lightning: knock-up 1.0s on the
    # 3rd-strike attack at end of pull-line all 5 ranks (canonical
    # value; the pull setup scales damage not the CC duration).
    registry.setdefault("XinZhao", {})["W"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # ----- ENGINE 1.34.0 wave 4 (2026-05-22) -----
    # +15 entries across 15 additional champions of first-order CC at
    # patch 16.10. Selection rules unchanged from waves 1 + 2 + 3
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms
    # / sleeps / fear / suppressions / polymorphs / taunts); no slows;
    # no conditional CC (Bard Q wall-bounce / TF W Gold Card / Evelynn W
    # detonation-on-Eve-attack / Karma W channel-completion / Syndra E
    # via Dark Sphere / Swain E return-wave / Seraphine E slowed-target /
    # Zilean Q double-bomb / Hwei E compound-cast); no self-CC. Values
    # sourced from data/daemon_slayer/16.10.1/champion_abilities.json
    # for the explicit per-rank duration entries; the knock-up / knock-back
    # / direct-stun single-value entries follow the wave 1+2+3 convention
    # for displacements not encoded as duration blocks.
    # Draven E - Stand Aside: knock-back 0.5s on contact all 5 ranks
    # (brief displacement followed by slow; pin canonical knockback
    # value following the Singed E / Tristana R pattern from wave 2+3).
    registry.setdefault("Draven", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Ekko W - Parallel Convergence: stun 2.25s on enemies inside the
    # anomaly when it expires after delay (single value across 5 ranks;
    # rank scales shield strength, not CC duration). Universal-zone
    # pattern (enemies inside at expiry get the CC) mirrors Soraka E
    # Equinox + Anivia Q from wave 2.
    registry.setdefault("Ekko", {})["W"] = (2.25, 2.25, 2.25, 2.25, 2.25)
    # Janna Q - Howling Gale: knock-up 1.0s at full charge across all
    # 5 ranks (rank scales damage; knock-up duration scales with the
    # tornado's charge time NOT with rank; pin canonical full-charge
    # value per the wave-1 Vi Q / wave-3 Tristana R single-value
    # convention).
    registry.setdefault("Janna", {})["Q"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Jax E - Counter Strike: stun 1.0s AOE on dodge counterattack at
    # all 5 ranks (rank scales damage not CC duration).
    registry.setdefault("Jax", {})["E"] = (1.0, 1.0, 1.0, 1.0, 1.0)
    # Jinx E - Flame Chompers: root 1.5s on triggered chomper at all
    # 5 ranks (rank scales damage + cooldown, not CC duration).
    registry.setdefault("Jinx", {})["E"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Mel E - Solar Snare: root 1.25/1.5/1.75/2.0/2.25 on orb expiry
    # across 5 ranks (Orb Root Duration block from champion_abilities
    # data at 16.10.1).
    registry.setdefault("Mel", {})["E"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Nocturne E - Unspeakable Horror: fear 1.25/1.5/1.75/2.0/2.25
    # across 5 ranks (Disable Duration block from data; the channel
    # is the application timer not a conditional gate - the fear
    # applies as soon as the channel completes which is universal).
    registry.setdefault("Nocturne", {})["E"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Quinn E - Vault: knock-back 0.75s on dash hit at all 5 ranks
    # (brief displacement following Singed E / Tristana R pattern).
    registry.setdefault("Quinn", {})["E"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Rammus E - Frenzying Taunt: taunt 1.2/1.4/1.6/1.8/2.0 across
    # 5 ranks (Taunt Duration block from data).
    registry.setdefault("Rammus", {})["E"] = (1.2, 1.4, 1.6, 1.8, 2.0)
    # Senna W - Last Embrace: root 1.25/1.5/1.75/2.0/2.25 across 5
    # ranks (Root Duration block from data; delayed root after the
    # ~1s travel delay - the timer is universal not conditional,
    # mirrors the Nautilus Q / Caitlyn W expiry-root pattern).
    registry.setdefault("Senna", {})["W"] = (1.25, 1.5, 1.75, 2.0, 2.25)
    # Seraphine R - Encore: stun 1.25/1.5/1.75 across 3 ranks
    # (Disable Duration block from data; primary AOE wave stuns
    # enemies hit; bounce-back extension is universal).
    registry.setdefault("Seraphine", {})["R"] = (1.25, 1.5, 1.75)
    # Shaco W - Jack in the Box: fear 0.5/0.75/1.0/1.25/1.5 across
    # 5 ranks (Fear Duration block from data; box trigger fires the
    # fear on enemies in radius unconditionally).
    registry.setdefault("Shaco", {})["W"] = (0.5, 0.75, 1.0, 1.25, 1.5)
    # Shen E - Shadow Dash: taunt 1.5s on dash hit at all 5 ranks
    # (canonical post-rework value; rank scales damage + energy
    # restore, not CC duration; description "dashing in a direction,
    # taunting enemies in his path" from cdragon).
    registry.setdefault("Shen", {})["E"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Soraka E - Equinox: root 1.0/1.25/1.5/1.75/2.0 on enemies inside
    # at zone expiry across 5 ranks (Root Duration block from data;
    # universal-zone pattern mirroring Ekko W + Anivia Q).
    registry.setdefault("Soraka", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Zyra E - Grasping Roots: root 1.0/1.25/1.5/1.75/2.0 on line hit
    # across 5 ranks (Root Duration block from data).
    registry.setdefault("Zyra", {})["E"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # ----- ENGINE 1.35.0 wave 5 (2026-05-22) -----
    # +14 entries across 14 additional champions of first-order CC at
    # patch 16.10. Selection rules unchanged from waves 1+2+3+4
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls); no
    # slows; no conditional CC; no self-CC. champion_abilities.json
    # at 16.10.1 does not carry explicit Disable/Stun/Root/Fear/Taunt
    # duration blocks for these spells (only damage_blocks); values
    # sourced from Riot wiki + canonical patch 16.10.1 tooltips and
    # follow the single-value-all-ranks pattern established by waves
    # 1+2+3+4 (Sona R / Galio W / Yasuo R / Pantheon W / Vi Q / Singed
    # E / Tristana R / Caitlyn W / Camille E / Pyke Q / Rell Q / Jax E
    # etc.). REJECTED candidates with reason recorded (do NOT re-
    # research): Aurora R (conditional knock-up only on cast start),
    # Mordekaiser R Realm of Death (banishment conditional - items 137
    # REJECT list), Briar R Certain Death (charm+knockback compound -
    # charm piece conditional), Bard Q (wall-bounce conditional - items
    # 138 REJECT list), Sett W (direct-damage-only - items 137 REJECT),
    # Taliyah W (displacement-only not knock-up - items 137 REJECT),
    # Volibear Q (terrain conditional - items 135+ REJECT), JarvanIV
    # EQ combo (flag-throw conditional), Trundle R (slow+damage steal),
    # Kennen E (3rd Mark of the Storm stack conditional), KSante Q
    # (3rd stack conditional), Sett E Facebreaker (both-sides pull
    # conditional), Vayne E Condemn (wall-pin conditional), Sylas E2
    # Abscond/Abduct (second-cast conditional), Xayah E (3+ feathers
    # conditional), Aphelios Q variants (varies by chamber), Aurora E
    # Drawn In (slow+pull displacement), Briar Q (charge conditional),
    # Renata R (damage-applied conditional). Sejuani Q (Arctic Assault
    # stun) NOT included since Sejuani R was seeded wave 1 (would
    # combine into one Sejuani entry; deferred for sweep simplicity).
    # Shen E + Jax E + Jinx E NOT included - all 3 already seeded
    # wave 4. Thresh E (Flay knockback) NOT included - Thresh Q was
    # seeded wave 1; multi-spell Thresh extension deferred.
    # Hecarim E - Devastating Charge: knockback 0.75s on charge contact
    # all 5 ranks (brief displacement; rank scales damage + slow, not
    # CC duration); canonical knockback pattern following Singed E /
    # Tristana R from prior waves.
    registry.setdefault("Hecarim", {})["E"] = (0.75, 0.75, 0.75, 0.75, 0.75)
    # Hecarim R - Onslaught of Shadows: fear 1.0s on Hecarim phasing
    # through enemies all 3 ranks (canonical fear duration; rank scales
    # damage + travel range, not CC duration).
    registry.setdefault("Hecarim", {})["R"] = (1.0, 1.0, 1.0)
    # KSante R - All Out: knock-up 0.75s on first impact across all
    # 3 ranks (knock-aside displacement; rank scales damage + bonus
    # stats, not CC duration). Canonical first-impact-only CC piece;
    # the All Out form-change is a self-buff not first-order CC.
    registry.setdefault("KSante", {})["R"] = (0.75, 0.75, 0.75)
    # Mordekaiser E - Death's Grasp: pull 0.25s displacement at all 5
    # ranks (brief inward pull; canonical post-rework value following
    # the Singed E displacement family. Rank scales magic-pen + damage,
    # not CC duration).
    registry.setdefault("Mordekaiser", {})["E"] = (
        0.25, 0.25, 0.25, 0.25, 0.25,
    )
    # Urgot E - Disdain: knockback 0.5s on hit at all 5 ranks (brief
    # displacement; rank scales damage + executes low-HP targets, not
    # CC duration; canonical knockback value following the Draven E /
    # Singed E displacement family).
    registry.setdefault("Urgot", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Viego W - Spectral Maw: stun 1.5s at full charge all 5 ranks
    # (single value across 5 ranks; rank scales damage + dash range,
    # not CC duration; minimum-charge stuns shorter but full-charge
    # value is the canonical max pin following the Sion Q + Pantheon W
    # pattern).
    registry.setdefault("Viego", {})["W"] = (1.5, 1.5, 1.5, 1.5, 1.5)
    # Yone R - Fate Sealed: knock-up 0.75s on hit all 3 ranks (brief
    # lift; rank scales damage not CC duration; canonical knock-up
    # value matching Diana R / Gnar R / Tristana R pattern).
    registry.setdefault("Yone", {})["R"] = (0.75, 0.75, 0.75)
    # Ziggs W - Satchel Charge: knockback 0.5s on explosion all 5
    # ranks (brief displacement; rank scales damage, not CC duration;
    # canonical knockback value following Draven E pattern).
    registry.setdefault("Ziggs", {})["W"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Wave 5 deferrals (now unblocked via schema lift, addressed in
    # wave 6 below): Lulu R / Sejuani Q / Thresh E were rejected
    # from wave 5 due to dict-literal collision with prior-wave
    # entries (Lulu W wave 1 / Sejuani R wave 1 / Thresh Q wave 1).
    # The 1.36.0 schema lift to setdefault enables multi-wave
    # augmentation of the same champion's spell map.
    # Tahm Kench W - Devour ally: knock-up 0.0s NOT first-order CC
    # (allied target swallow; intentionally skipped, on items 137
    # REJECT list).
    # Briar W Blood Frenzy - SKIPPED (no CC, just damage steal).
    # Heimerdinger Q turret - NOT first-order champion CC (turret
    # piece; H-28G's stun-mine piece is conditional on enemy stepping
    # in trap and the duration is rank 5 only; Heimerdinger E already
    # seeded wave 3 covers his canonical CC).
    # ----- ENGINE 1.36.0 wave 6 (2026-05-22) -----
    # SCHEMA LIFT + 5 additional entries. The 1.36.0 schema lift to
    # the setdefault builder pattern (above) unblocks 3 wave-5
    # deferrals (multi-wave augmentation of existing champion spell
    # maps): Lulu R (Lulu W in wave 1), Sejuani Q (Sejuani R in
    # wave 1), Thresh E (Thresh Q in wave 1). 2 new champions also
    # ship: Bard R + Lillia R. Total wave 6 net: 5 spell entries
    # across 5 distinct champions (Lulu / Sejuani / Thresh / Bard /
    # Lillia; the first 3 augment existing entries, the last 2
    # introduce new champions).
    # Selection rules unchanged from waves 1-5: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms
    # / sleeps / fear / suppressions / polymorphs / taunts / pulls
    # / stasis); no slows; no conditional CC; no self-CC; canonical
    # DDragon ids. Stasis (Bard R Tempered Fate) added to the first-
    # order CC scope as a hard-disable type alongside stun / root /
    # suspension / suppression.
    # Lulu R - Wild Growth: knock-up 1.0s on ally landing all 3
    # ranks (allied target launched into air; the knock-up affects
    # enemies under the landing zone unconditionally; canonical
    # 16.10.1 value; rank scales bonus HP + radius + duration of
    # the giant-form, not the initial knock-up duration). Multi-
    # wave augmentation: Lulu W polymorph was seeded wave 1; the
    # setdefault builder allows Lulu R to coexist.
    registry.setdefault("Lulu", {})["R"] = (1.0, 1.0, 1.0)
    # Sejuani Q - Arctic Assault: stun 0.75/0.875/1.0/1.125/1.25 across
    # 5 ranks (canonical post-rework value at 16.10.1; brief knockup-
    # stun on first enemy hit by the dash). Multi-wave augmentation:
    # Sejuani R was seeded wave 1; the setdefault builder allows
    # Sejuani Q to coexist.
    registry.setdefault("Sejuani", {})["Q"] = (0.75, 0.875, 1.0, 1.125, 1.25)
    # Thresh E - Flay: knockback 0.4s displacement all 5 ranks
    # (brief swat displacement; rank scales damage + slow not CC
    # duration; canonical knockback value following Singed E /
    # Tristana R / Draven E pattern). Multi-wave augmentation:
    # Thresh Q death-sentence stun was seeded wave 1; the setdefault
    # builder allows Thresh E to coexist.
    registry.setdefault("Thresh", {})["E"] = (0.4, 0.4, 0.4, 0.4, 0.4)
    # Bard R - Tempered Fate: stasis 2.5s on enemies hit by the
    # tomb-wave all 3 ranks (canonical Bard R duration; rank scales
    # cooldown not CC duration; the area-of-effect stasis is a hard
    # disable on enemies hit). Stasis is first-order CC (target is
    # untargetable + cannot act); aligns with the existing scope.
    # Bard Q wall-bounce stun stays REJECTED (conditional on terrain).
    registry.setdefault("Bard", {})["R"] = (2.5, 2.5, 2.5)
    # Lillia R - Lilting Lullaby: sleep 2.0s on enemies marked with
    # Dream Dust when she puts them to sleep all 3 ranks (canonical
    # 16.10.1 base sleep duration on the application; rank scales
    # damage + cooldown not CC duration). The Dream Dust mark from
    # her other abilities is the activation pattern (mirrors Zoe E
    # drowsy-then-sleep pattern wave 1); the sleep itself is the
    # first-order CC.
    registry.setdefault("Lillia", {})["R"] = (2.0, 2.0, 2.0)
    # Wave 6 REJECTED candidates (with reason recorded so future
    # audits do NOT re-research):
    # * Rell R Magnet Storm: primarily a force-pull / drag mechanic
    #   while channeling (continuous slow pull of enemies inward);
    #   the 1.0s "initial pull" is a damage tick + slow not a hard
    #   first-order CC. The Magnet Storm field IS impactful but does
    #   not displace targets to a discrete pull-stun like Sion R or
    #   Skarner R. REJECT consistent with wave-5 deferral.
    # * Bard Q Cosmic Binding: wall-bounce conditional stun
    #   (REJECT carryover from waves 4+5).
    # * TF W Pick a Card Gold Card: card-selection conditional stun
    #   (REJECT carryover from waves 4+5).
    # * Lillia E Swirlseed: ranged slow (NOT a sleep; sleep is on R only).
    # * Tristana W Rocket Jump landing: knockback was REJECTED-by-
    #   tooltip-search at 16.10.1 (landing applies a small slow not
    #   a discrete knockback). Tristana R buster-shot knockback was
    #   already seeded wave 3.
    # * Akshan E Heroic Swing: no first-order CC (just dash + slow).
    # * Karthus Q Lay Waste: no first-order CC.
    # * Naafiri R The Hunt Calls: no first-order CC.
    # * Yuumi Q Prowling Projectile fully-charged root: REJECT due to
    #   conditional charge time semantics (operator-gated schema lift
    #   to a conditional axis would unblock).
    # * Brand Q / Tahm Q / Volibear Q / Mordekaiser R / Aurora R /
    #   Briar R / Sett W / Sett E / Taliyah W / Trundle R / Kennen E /
    #   KSante Q / Vayne E / Sylas E2 / Xayah E / Aphelios Q /
    #   Aurora E / Briar Q / Renata R / Viktor W / Warwick R / Bard Q /
    #   TF W: all conditional-CC carryovers from prior-wave REJECT
    #   lists (operator-gated schema lift for the conditional axis).
    # FINAL wave 6 net: 5 spell entries across 5 distinct champions
    # (Lulu R / Sejuani Q / Thresh E / Bard R / Lillia R).
    # ----- ENGINE 1.37.0 wave 7 (2026-05-22) -----
    # +8 entries across +7 new champions + 1 multi-wave augmentation
    # (Zac R; Zac E was wave 2) of first-order CC at patch 16.10.1.
    # Selection rules unchanged from waves 1-6: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls /
    # stasis); no slows; no conditional CC; no self-CC; canonical DDragon
    # ids. Values sourced from Riot wiki + canonical patch 16.10.1
    # tooltips (Meraki bulk + champion_abilities.json damage_blocks do
    # NOT carry per-spell CC duration data; same sourcing convention as
    # waves 1-6 for the wiki-tooltip lookups). Wave 7 picks broaden
    # remaining first-order-CC coverage across champions NOT yet seeded.
    # Irelia E - Flawless Duet: stun 0.75/0.85/0.95/1.05/1.15 across
    # 5 ranks (canonical post-rework value at 16.10.1; rank scales the
    # stun duration). The 2 daggers must connect for the stun to fire,
    # but the stun itself is unconditional once both connect.
    registry.setdefault("Irelia", {})["E"] = (0.75, 0.85, 0.95, 1.05, 1.15)
    # Kalista R - Fate's Call: knock-up 1.0s on enemies hit by the
    # ally-cannonball at all 3 ranks (rank scales bonus dash range +
    # damage, not CC duration; canonical value following the Sona R /
    # Diana R / Yone R single-value-all-ranks pattern from prior waves).
    registry.setdefault("Kalista", {})["R"] = (1.0, 1.0, 1.0)
    # Ornn R - Call of the Forge God: knock-up 0.5s on first-impact of
    # the elemental ram all 3 ranks (canonical primary first-hit knockup;
    # rank scales damage + ram range, not CC duration; the second-cast
    # knockup with Brittle is conditional on the target carrying a
    # Brittle stack from other Ornn abilities, intentionally skipped).
    registry.setdefault("Ornn", {})["R"] = (0.5, 0.5, 0.5)
    # Shyvana R - Dragon's Descent: knock-back 1.0s on dragon-form
    # contact with first enemy all 3 ranks (canonical post-rework
    # displacement; rank scales bonus stats + damage, not CC duration).
    registry.setdefault("Shyvana", {})["R"] = (1.0, 1.0, 1.0)
    # Smolder R - Mountain Breaker: knock-up 1.25s on enemies hit by
    # the dive landing all 3 ranks (canonical first-order knockup; rank
    # scales damage + slow piece, the slow is intentionally skipped as
    # a separate axis per the no-slows wave convention).
    registry.setdefault("Smolder", {})["R"] = (1.25, 1.25, 1.25)
    # Vayne E - Condemn: knock-back 0.5s on hit at all 5 ranks (the
    # universal knockback displacement; rank scales damage, not CC
    # duration; the wall-pin stun is conditional on terrain contact
    # and is intentionally REJECTED per the no-conditional-CC rule).
    # Canonical knockback following the Singed E / Tristana R / Draven E
    # / Thresh E displacement family.
    registry.setdefault("Vayne", {})["E"] = (0.5, 0.5, 0.5, 0.5, 0.5)
    # Volibear E - Sky Splitter: airborne 0.25s on enemies under the
    # landing zone at all 5 ranks (brief lift-up on the lightning strike
    # landing; rank scales damage + bonus MR shred, not CC duration;
    # this is the brief disable component, distinct from the conditional
    # Volibear Q terrain-stun which stays REJECTED).
    registry.setdefault("Volibear", {})["E"] = (0.25, 0.25, 0.25, 0.25, 0.25)
    # Zac R - Let's Bounce: knock-up 1.0s on enemies hit by Zac's bounce
    # contact all 3 ranks (canonical knockup; rank scales bounce count +
    # damage, not CC duration; the slow piece on bounces is intentionally
    # skipped per the no-slows wave convention).
    registry.setdefault("Zac", {})["R"] = (1.0, 1.0, 1.0)
    # Wave 7 REJECTED candidates (with reason recorded so future audits
    # do NOT re-research):
    # * Darius E Apprehend: pure pull + slow (no first-order stun).
    # * Draven E Stand Aside: already wave 4.
    # * Ekko W Parallel Convergence: already wave 4.
    # * Yorick R Eulogy of the Isles: no first-order CC (Mist Walker
    #   summons; Yorick W Dark Procession is a wall summon, not champ-CC).
    # * AurelionSol Q / Q': no CC (Breath of Light beam damage).
    # * Aurora W Across the Veil: no CC (dash + invisibility).
    # * Aurora E The Weirding: pull + slow conditional (REJECT - matches
    #   wave 6 Aurora E carryover).
    # * Ambessa Q / W / E / R: no first-order CC at 16.10.1 (cunning
    #   weave / dash / line damage / executes); all stays inert until
    #   a future audit surfaces a canonical CC value.
    # * Pyke E Phantom Undertow: damage on path-return only (no CC);
    #   Pyke Q stun was already wave 3.
    # * Veigar E Event Horizon: already wave 1.
    # * Fiora W Riposte: parry/stun on parry is conditional on enemy
    #   targeted-damage timing (REJECT - conditional axis).
    # * Vex E Looming Darkness: fear conditional on Vex E-passive mark
    #   (REJECT - conditional axis).
    # * Ornn Q Volcanic Rupture: knockup conditional on Brittle second-
    #   cast Q (REJECT - conditional axis).
    # * Renata R Hostile Takeover: berserk effect (forces enemies to
    #   attack each other) but no first-order CC duration in the wiki
    #   tooltip in the canonical-disable sense (REJECT - berserk is a
    #   different mechanic axis, queued for a future schema lift).
    # * Volibear Q Thundering Smash: terrain-conditional stun (REJECT
    #   carryover from waves 5+6).
    # * TahmKench R Devour: ally-target swallow (REJECT carryover).
    # * Aurora R Between Worlds: zone effect, no first-order CC.
    # FINAL wave 7 net: 8 spell entries across 8 distinct champions
    # (Irelia E / Kalista R / Ornn R / Shyvana R / Smolder R / Vayne E /
    # Volibear E / Zac R). 7 of the 8 are NEW champions; Zac R is a
    # multi-wave augmentation (Zac E was seeded wave 2). Total registry:
    # 103 entries across 89 champs.
    # ----- ENGINE 1.42.0 wave 8 (2026-05-22) -----
    # +3 entries / 0 new champions / 3 multi-wave augmentations. The
    # unconditional first-order CC at patch 16.10.1 is approaching
    # saturation - per item 145 don't-redo: "most remaining champions
    # either have no first-order CC OR carry conditional-only CC". The
    # wave 8 audit walked every champion+spell duration block in
    # data/daemon_slayer/16.10.1/champion_abilities.json + cross-checked
    # against the wave-1-through-7 entries + the cc_conditional 33-entry
    # registry. Net new unconditional candidates: 3 (all multi-wave
    # augmentations of champions already partially seeded).
    # Selection rules unchanged from waves 1-7: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls /
    # stasis); no slows; no conditional CC; no self-CC; canonical
    # DDragon ids.
    # Lissandra W - Ring of Frost: root 1.25/1.35/1.45/1.55/1.65 across
    # 5 ranks (canonical 16.10.1 Meraki value via Root Duration block in
    # champion_abilities.json). AOE-on-cast around Lissandra; enemies
    # in radius are rooted unconditionally. Multi-wave augmentation:
    # Lissandra R stun was seeded wave 1; the setdefault builder allows
    # Lissandra W to coexist on the same champion's spell map.
    registry.setdefault("Lissandra", {})["W"] = (1.25, 1.35, 1.45, 1.55, 1.65)
    # Maokai W - Twisted Advance: root 1.0/1.1/1.2/1.3/1.4 across 5
    # ranks (canonical 16.10.1 Meraki value via Root Duration block).
    # Targeted dash + root on enemy hit; the root applies on contact
    # unconditionally once W is cast. Multi-wave augmentation: Maokai R
    # Nature's Grasp was seeded wave 1; setdefault allows W to coexist.
    # NOTE: Maokai Q Bramble Smash terrain-stun is conditional (already
    # cc_conditional wave 2 entry) and stays REJECTED here per the
    # no-conditional-CC selection rule.
    registry.setdefault("Maokai", {})["W"] = (1.0, 1.1, 1.2, 1.3, 1.4)
    # Rakan R - The Quickness: charm 1.0/1.25/1.5 across 3 ranks
    # (canonical 16.10.1 Meraki value via Disable Duration block).
    # Rakan dashes around an area for up to 4s; enemies he touches
    # during the dash are charmed. The charm-on-touch is unconditional
    # once R is cast (the dash IS the cast). Multi-wave augmentation:
    # Rakan W Grand Entrance knock-up was seeded wave 1; setdefault
    # allows R to coexist.
    registry.setdefault("Rakan", {})["R"] = (1.0, 1.25, 1.5)
    # Wave 8 REJECTED candidates (with reason recorded so future audits
    # do NOT re-research):
    # * Bard Q Cosmic Binding: already in cc_conditional wave 1 entry
    #   (terrain-bounce double-stun conditional axis).
    # * Evelynn W Allure: charm/stun is detonation-on-Eve-attack
    #   conditional (target must be auto-attacked by Eve to apply the
    #   charm); REJECT - belongs in cc_conditional if added later.
    # * Karma W Focused Resolve: already in cc_conditional wave 1
    #   (channel-completion full-tether root).
    # * Morgana R Soul Shackles: stun fires on tether expiry which
    #   requires target staying in range for 3s OR dying mid-tether;
    #   channel-completion-conditional axis; REJECT - belongs in
    #   cc_conditional if added later (parallel to Karma W).
    # * Seraphine E Beat Drop: stun OR root duration is the same value
    #   but which CC fires is conditional on target state (still target
    #   gets root, moving/slowed target gets stun); REJECT per item 138
    #   conditional-CC rule (target state is a conditional axis).
    # * TwistedFate W Pick a Card: already in cc_conditional wave 1
    #   (gold-card selection conditional stun).
    # * Volibear R Stormbringer: 2/3/4s Turret Disable Duration - the
    #   disable is on STRUCTURES (turrets), not on champion CC; carryover
    #   from items 138 REJECT list.
    # * Zilean Q Time Bomb: already in cc_conditional wave 2 (double-
    #   bomb stack conditional stun).
    # * Senna W Last Embrace: ALREADY in wave 4 (item 145's REJECT-list
    #   note "Senna W (unconditional)" matched the existing wave-4 entry;
    #   verified via grep on ability_dps.py - line 1182 has Senna W
    #   root 1.25/1.5/1.75/2.0/2.25 seeded item 138 wave 4).
    # * Tristana W Rocket Jump landing: REJECT per item 140 wave 6 list
    #   (the landing applies a small slow not a discrete knockback at
    #   16.10.1; only the Tristana R buster-shot knockback is canonical
    #   and was seeded wave 3).
    # * Aatrox W Infernal Chains: already in cc_conditional wave 4
    #   (debuffed-target persistence pull-back root).
    # * Skarner Q Shattered Earth + Upheaval: already in cc_conditional
    #   wave 2 (nth-hit knockup).
    # FINAL wave 8 net: 3 spell entries / 0 NEW champions / 3 multi-
    # wave augmentations (Lissandra W + Maokai W + Rakan R). Total
    # registry: 106 entries across 89 champs (unchanged champ count
    # because all 3 augmentations are on existing champions).
    # ----- ENGINE wave 9 (2026-05-22) -----
    # +2 entries / 0 new champions / 2 multi-wave augmentations. Per
    # item 146 carry (j): "wave 9+ likely thin pool (saturation for
    # net-new champions). The unconditional first-order CC at 16.10.1
    # is genuinely saturated for net-new champions, future waves either
    # coexist on already-registered champs OR need new schema." Wave 9
    # delivers exactly that - all wave 9 candidates are multi-wave
    # coexistence on already-registered champions. The wave 9 audit
    # walked every UNREGISTERED spell of every already-registered
    # champion in data/daemon_slayer/16.10.1/champion_abilities.json
    # for explicit Stun/Root/Silence/Charm/Fear/Taunt/Sleep/Suppression/
    # Knockup/Knockback/Airborne/Stasis Duration blocks. Result: 6
    # candidates surfaced from the abilities-data grep, of which 2 are
    # genuine unconditional first-order CC (Chogath W silence + Malzahar
    # Q silence) and 4 are already-known conditional / out-of-scope
    # rejects (see REJECT block below).
    # Selection rules unchanged from waves 1-8: first-order CC only
    # (stuns / roots / suspensions / knock-ups / knock-backs / charms /
    # sleeps / fear / suppressions / polymorphs / taunts / pulls /
    # stasis / silence / banishment); no slows; no conditional CC; no
    # self-CC; canonical DDragon ids.
    # Chogath W - Feral Scream: silence 1.6/1.7/1.8/1.9/2.0 across 5
    # ranks (canonical 16.10.1 Meraki value via Silence Duration block
    # in champion_abilities.json). Cone-shaped magic damage + silence
    # on cast; enemies in the cone are silenced unconditionally once W
    # is cast. Multi-wave augmentation: Chogath Q Rupture knockup was
    # seeded wave 2; the setdefault builder allows Chogath W to coexist
    # on the same champion's spell map. Silence is first-order CC per
    # the wave 9 scope expansion (matches the Mordekaiser E pull family
    # admission from wave 5 - hard-disable types that fit cleanly
    # alongside stun / root / suspension / suppression).
    registry.setdefault("Chogath", {})["W"] = (1.6, 1.7, 1.8, 1.9, 2.0)
    # Malzahar Q - Call of the Void: silence 1.0/1.25/1.5/1.75/2.0
    # across 5 ranks (canonical 16.10.1 Meraki value via Silence
    # Duration block in champion_abilities.json). Two void zones AOE
    # location-cast; enemies caught in the path between zones are
    # silenced unconditionally on contact. Multi-wave augmentation:
    # Malzahar R Nether Grasp suppression was seeded wave 1; the
    # setdefault builder allows Malzahar Q to coexist on the same
    # champion's spell map. This is a SECOND silence-family entry in
    # wave 9 alongside Chogath W; both share the same silence CC kind
    # which is added to the first-order CC scope in this wave per the
    # same precedent as wave 6 stasis (Bard R Tempered Fate).
    registry.setdefault("Malzahar", {})["Q"] = (1.0, 1.25, 1.5, 1.75, 2.0)
    # Wave 9 REJECTED candidates (with reason recorded so future audits
    # do NOT re-research):
    # * Bard Q Cosmic Binding: already in cc_conditional wave 1 entry
    #   (terrain-bounce double-stun conditional axis); the unconditional
    #   first-stun-on-direct-hit piece is fired on every cast but the
    #   double-stun-on-bounce semantics are conditional. REJECT per
    #   carryover from waves 4-8 + cc_conditional schema-lift.
    # * Morgana R Soul Shackles: stun 1.5/1.75/2.0 across 3 ranks IS
    #   in the Stun Duration block - BUT the stun fires only on tether
    #   expiry which requires target staying in range for ~3s OR dying
    #   mid-tether. This is channel-completion-conditional and was
    #   explicitly REJECTED in item 146 wave 8 - belongs in
    #   cc_conditional if added later (parallel to Karma W).
    # * Seraphine E Beat Drop: stun OR root duration 1.1/1.2/1.3/1.4/1.5
    #   across 5 ranks. Already REJECTED in waves 4 + 8 - target state
    #   determines which CC fires (still target gets root, moving/slowed
    #   target gets stun). Conditional axis per item 138 rule.
    # * Volibear R Stormbringer: 2/3/4s Turret Disable Duration - the
    #   disable is on STRUCTURES (turrets), not on champion CC.
    #   Carryover REJECT from items 138 + 142 + 146.
    # * Janna R Monsoon: initial knockup on cast + heal channel; the
    #   initial knockup is the cast-portion CC but its duration is not
    #   exposed in the damage_blocks (only Heal Per Tick + Total Heal).
    #   The knockup duration is brief (~0.5s tooltip-stated) and the
    #   channel itself is a slow-pulse-with-heal not a hard CC. REJECT
    #   per the unwillingness to encode a value not present in the
    #   Meraki bulk - operator-tunable channel-knockup is best deferred
    #   to cc_conditional with a channel-completion gate.
    # * Lulu E Help, Pix!: shield/damage only, no CC.
    # * 226 other UNREGISTERED spells of the 89 registered champions:
    #   all have NO Stun/Root/Silence/Charm/Fear/Taunt/Sleep/Suppression/
    #   Knockup/Knockback/Airborne/Stasis Duration block in
    #   champion_abilities.json. The data lane is genuinely saturated.
    # FINAL wave 9 net: 2 spell entries / 0 NEW champions / 2 multi-
    # wave augmentations (Chogath W silence + Malzahar Q silence).
    # Total registry: 108 entries across 89 champs (unchanged champ
    # count because all augmentations are on existing champions). Per
    # item 146 carry (j) prediction, wave 9 surfaces only thin
    # multi-wave coexistence and the unconditional first-order CC pool
    # at 16.10.1 remains saturated for net-new champions.
    return registry


_PER_SPELL_CC_DURATIONS: dict[str, dict[str, tuple[float, ...]]] = (
    _build_per_spell_cc_durations()
)


def _per_spell_cc_for(champion_id: str, spell_key: str) -> tuple[float, ...]:
    """Read a champion+spell base CC duration tuple from the registry.

    Returns ``()`` when the champion is absent, the spell is absent, or
    the registry entry is empty. Forward-marker: the registry is empty
    at 1.29.0 by design so all calls return ``()``; tests inject a
    monkey-patched entry to exercise consumer math.
    """
    champ_entry = _PER_SPELL_CC_DURATIONS.get(champion_id, {})
    return tuple(champ_entry.get(spell_key, ()))


def _apply_tenacity_to_cc_tuple(
    base_cc: tuple[float, ...], tenacity_mult: float,
) -> tuple[float, ...]:
    """Apply ``effective_cc_duration`` element-wise to a base-CC tuple.

    Free-function wrapper around ``ehp.effective_cc_duration`` (the
    helper shipped 1.25.0). Routed through this module-local helper so
    the call site is grep-able and the engine layer stays read-only
    against ``ehp.py``. Returns an empty tuple when the input is empty.

    Floors at 0.0 per-element via the underlying helper. SR + non-ARAM
    modes with ``tenacity_mult == 1.0`` return identity values (the
    tuple is byte-equal to the input modulo float casting).
    """
    if not base_cc:
        return ()
    return tuple(
        effective_cc_duration(float(s), float(tenacity_mult)) for s in base_cc
    )


# ENGINE schema lift item 336 (2026-06-07): per-spell CC RANGE registry.
#
# A NEW sibling registry capturing distance- / travel-scaled CC durations
# as a ``(min_s, max_s)`` interval - a shape the flat per-rank
# ``_PER_SPELL_CC_DURATIONS`` tuple structurally CANNOT express. Several
# single-cast CC spells scale their duration continuously with projectile
# travel distance (NOT by spell rank); the flat registry can only pin one
# representative value per rank and discards the ceiling. This registry is
# the structural home for that (min, max) interval.
#
# FORWARD-MARKER / BYTE-IDENTICAL: nothing consumes _PER_SPELL_CC_RANGE at
# ship - it mirrors how _PER_SPELL_CC_DURATIONS itself shipped EMPTY at
# ENGINE 1.29.0 (item 130; item 112 STAT_GRANT_CALC_KEYS precedent).
# compute_cc_pressure / compute_ehp / cooldown_watch / cc_output read ONLY
# _PER_SPELL_CC_DURATIONS and never this sibling, so live DS output is
# byte-identical and ENGINE_VERSION does NOT bump. A future EHP-vs-CC /
# fight-sim consumer can read the worst-case (max-distance) ceiling without
# corrupting the rank semantics every flat-tuple test pins.
#
# Schema:
#   _PER_SPELL_CC_RANGE[champion_id][spell_key] = (min_s, max_s)
# where min_s is the instant- / short-throw CC duration and max_s the
# full-distance ceiling. All values from official Riot tooltips
# (effects_descriptions) at patch 16.10.1, verbatim
# "min : max (based on distance traveled)" literals.
#
# SCOPE: this slice seeds ONLY the 4 clean "distance traveled" cases. The
# channel-time variants (Sion Q 1.25:2.25, Galio W, KSante W, Viego W,
# etc.) share the interval SHAPE but a different scaling input (charge
# time, not projectile distance) and are a later row-expansion, not part
# of this lift.
def _build_per_spell_cc_range() -> dict[str, dict[str, tuple[float, float]]]:
    """Build the per-spell distance-scaled CC range registry.

    Returns a fresh dict of champion_id -> spell_key -> (min_s, max_s).

    Uses the same ``setdefault(champ, {})[spell] = (min, max)`` builder
    shape as ``_build_per_spell_cc_durations`` so future waves can add
    spells to an already-seeded champion without dict-literal clobber.
    """
    registry: dict[str, dict[str, tuple[float, float]]] = {}
    # ----- item 336 seed (2026-06-07): 4 distance-scaled CC intervals -----
    # Xerath E (Shocking Orb): "stuns them for 0.75 : 2.25 (based on orb
    # travel distance) seconds". The flat registry pins per-rank
    # (1.0..2.0) which cannot represent the distance ceiling.
    registry.setdefault("Xerath", {})["E"] = (0.75, 2.25)
    # Maokai R (Nature's Grasp): "roots them for 0.75 : 2.25 (based on
    # distance traveled) seconds". Flat registry R=(1.2, 1.6, 2.0).
    registry.setdefault("Maokai", {})["R"] = (0.75, 2.25)
    # Ashe R (Enchanted Crystal Arrow): "stunning them for 1 : 3.5 (based
    # on distance traveled) seconds". Flat registry R=(1.5, 1.5, 1.5).
    registry.setdefault("Ashe", {})["R"] = (1.0, 3.5)
    # Hecarim R (Onslaught of Shadows): "fears nearby enemies for 0.75 :
    # 1.5 (based on distance traveled) seconds". Flat registry
    # R=(1.0, 1.0, 1.0).
    registry.setdefault("Hecarim", {})["R"] = (0.75, 1.5)
    return registry


_PER_SPELL_CC_RANGE: dict[str, dict[str, tuple[float, float]]] = (
    _build_per_spell_cc_range()
)


def _per_spell_cc_range_for(
    champion_id: str, spell_key: str,
) -> tuple[float, float] | None:
    """Read a champion+spell distance-scaled CC ``(min_s, max_s)`` range.

    Returns ``None`` when the champion is absent, the spell is absent, or
    the registry carries no range entry for that slot. ``None`` (not an
    empty tuple) is the explicit "no distance-scaled range" sentinel so a
    consumer can distinguish "unknown" from a real interval. Forward-
    marker: nothing consumes this at ship, so a future fight-sim reads the
    ceiling via this accessor without re-resolving the champion.
    """
    champ_entry = _PER_SPELL_CC_RANGE.get(champion_id, {})
    rng = champ_entry.get(spell_key)
    return rng if rng is not None else None
