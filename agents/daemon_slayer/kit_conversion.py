"""RM-86 L1 - per-champion kit-conversion vector (default-OFF sort-key seam).

RC-1 (``docs/specs/RM-86_scorer_kit_blindness_investigation.md`` section 3):
every scorer ranks candidates by the marginal change in ONE scalar objective,
and the champion enters that objective only through BASE STATS AND STAT
COEFFICIENTS. Nothing in the ranking path asks whether the kit can USE the stat
an item provides. So an item can raise the score through a stat the kit cannot
convert into output - BotRK raises Naafiri's modelled DPS through attack speed
she has no ratio for, and Liandry's raises Orianna's modelled ability damage
through 300 HP an ability-DPS objective cannot read at all.

This module supplies the conversion vector. It does NOT apply it; each ranker
scales its own SORT key and leaves every row field raw (transparency), exactly
as ``ap_ad_coherence`` does at ``onhit_dps.py:498-509``.

WHY A CURATED REGISTRY AND NOT A ``damage_blocks`` SCAN
------------------------------------------------------
Spec section 4 proposed deriving the vector from the champion's own
``damage_blocks`` ("does any block carry an AS term? a crit term? a DoT?").
Measured 2026-07-18 across all 1709 blocks / 171 champions of
``data/daemon_slayer/16.14.1/champion_abilities.json``: the complete block key
set is ``ap_pct, attribute, attribute_kind, base, bonus_ad_pct, bonus_armor_pct,
bonus_mr_pct, caster_armor_pct, caster_bonus_hp_pct, caster_bonus_mp_pct,
caster_bonus_ms_pct, caster_max_hp_pct, caster_max_mp_pct, raw_modifiers,
target_bonus_hp_pct, target_current_hp_pct, target_max_hp_pct,
target_missing_hp_pct, total_ad_pct, unparsed_modifiers``. There is NO
attack-speed, crit, on-hit or DoT key for any champion. Attack speed appears
only as ``attribute_kind="duration"`` (attack speed the ability GRANTS, never a
ratio it scales BY); crit appears in 6 ``attribute`` strings and on-hit in 11,
out of 570 distinct attribute values of which 439 are singletons.

The real signal is prose - 107 of 171 champions mention on-hit in
``effects_descriptions`` - but the loader DROPS that field (``AbilityForm``
declares 16 fields at ``abilities.py:220-235`` and ``from_dict`` at ``:237-263``
parses exactly those, ``effects_descriptions`` not among them).

So the vector is hand-seeded from verbatim prose, following the
``_passive_damage_overrides.py`` precedent ("Seeded 2026-05-31 against verbatim
effects_descriptions", ``:379``) and its continuous-fraction contract
(``conditional_probability: float = 1.0``, ``:375``). This is also FORCED by the
operator constraint that five kits (Pantheon, Rek'Sai, Rengar, Olaf, Riven) HAVE
the term and must still not be credited at face value: no data file carries
cadence, so a boolean has-an-AS-term gate is the wrong shape.

REACHABILITY (measured, main thread, live 16.14.1 deltas)
---------------------------------------------------------
The transform only ever LOWERS a positive score, so it can never push a good
item UP except as a side effect of everything above it falling. Reachable:
Naafiri's BotRK leaves #1 on both routes; Orianna's Liandry's leaves #1 while
Blackfire is NOT suppressed with it; Poppy's top-10 is preserved. NOT reachable
at any setting, and filed as L2 objective-coverage work: Olaf's Stridebreaker
rising (it and BotRK both carry ``PercentAttackSpeedMod: 0.25``, and
Stridebreaker's real justification is Halting Slash's engage slow, for which no
objective contains a term) and Pantheon's Heartsteel leaving #3 (pure HP, which
is ON-AXIS for the bruiser objective, so its exposure is zero on every channel).

Self-contained: no ``core`` import, so the engine package stays standalone
(the ``hybrid.py:69`` rule).
"""

from __future__ import annotations

from dataclasses import dataclass

from .effects import ITEM_EFFECTS

# --- the vector ------------------------------------------------------------


@dataclass(frozen=True)
class KitConversion:
    """Fraction of face value at which each channel converts into output.

    Every field is a continuous fraction in [0.0, 1.0]. 1.0 means full
    conversion, which is the pre-gate behaviour, so an all-1.0 entry is inert at
    any lever strength. Continuous rather than boolean because five seeded kits
    HAVE the term and must be credited BELOW face value; a boolean gate would
    score Pantheon's on-hit at either 0 or 1 and both are wrong.
    """

    attack_speed: float = 1.0
    crit: float = 1.0
    on_hit: float = 1.0
    off_axis_stat: float = 1.0
    note: str = ""


# The identity. Returned for every champion absent from the registry below.
#
# The default is the identity for three independent reasons, and all three must
# hold:
#   1. Blast-radius containment. 171 champions are in the snapshot and the seed
#      set is 8. A default below 1.0 would silently move the ranking for 163
#      champions on the first default-ON flip.
#   2. Sign correctness. At 1.0 every per-channel term is (1 - strength * exposure
#      * 0.0) == 1.0 exactly, so the product is an identity ON THE FLOAT, not an
#      approximation.
#   3. Evidence asymmetry. A fraction below 1.0 is a positive claim requiring
#      prose. Absence of evidence is not evidence of non-conversion. The identity
#      encodes "we have not looked at this champion", which is the truth for 163.
_IDENTITY = KitConversion()


# champion_id -> KitConversion. Every number is justified by the verbatim
# effects_descriptions fragment carried in its own ``note``.
_KIT_CONVERSION: dict[str, KitConversion] = {
    "Naafiri": KitConversion(
        attack_speed=0.00, crit=0.30, on_hit=0.10, off_axis_stat=0.00,
        note=(
            "A regex for attack speed / on-hit / critical / per second / per tick "
            "over all five slots returns ZERO matches, while the same regex matches "
            "Olaf, Pantheon, Orianna, Poppy, RekSai, Rengar and Riven. Every damage "
            "block she owns scales bonus_ad_pct only (Q Darkin Daggers 20-240 pct "
            "bonus AD, E Eviscerate 40-120, R Hounds' Pursuit 120). Her only "
            "self-buff is W: 'Naafiri gains 20% AD bonus attack damage'. attack_speed "
            "is 0.00 because there is no AS ratio, no AS prose and no attack-timer "
            "reset anywhere in the kit; crit and on_hit are low but nonzero because "
            "her ordinary basic attacks still crit and still apply on-hit."
        ),
    ),
    "Olaf": KitConversion(
        attack_speed=0.25, crit=0.55, on_hit=0.35, off_axis_stat=1.00,
        note=(
            "P Berserker Rage: 'Olaf gains bonus attack speed and life steal based "
            "on his missing health, up to 50% : 100% (based on level) bonus attack "
            "speed'. W Tough It Out grants a further [40,50,60,70,80] pct for 5s on "
            "a [16,15,14,13,12]s cooldown. A purchased 25 pct entering a 60-100 pct "
            "self-supplied pool delivers roughly 25/(25+75) of its zero-baseline "
            "value. off_axis_stat is 1.00 because the bruiser objective already "
            "scores HP and resists - nothing is off-axis for him except AP."
        ),
    ),
    "Pantheon": KitConversion(
        attack_speed=0.20, crit=0.20, on_hit=0.20, off_axis_stat=1.00,
        note=(
            "P Mortal Will: 'Pantheon generates a stack of Mortal Will whenever he "
            "lands a basic attack on-hit or casts an ability, stacking up to 5 times. "
            "At 5 stacks, Pantheon's next basic ability consumes the stacks to become "
            "empowered'. W empowered: 'Each hit is affected by critical strike "
            "modifiers and applies on-hit effects.' The 1-in-5 duty cycle is literal "
            "in the prose, so all three offensive channels take 0.20 from the same "
            "sentence."
        ),
    ),
    "Orianna": KitConversion(
        attack_speed=0.00, crit=0.00, on_hit=0.10, off_axis_stat=0.00,
        note=(
            "P Clockwork Windup: 'Orianna's basic attacks are empowered to deal "
            "10 : 50 (based on level) (+ 15% AP) bonus magic damage on-hit'. on_hit "
            "is 0.10 rather than 0.00 precisely because that passive exists, but she "
            "is a ranged control mage whose fight output is her ball rotation, not "
            "her auto cadence. attack_speed and crit are 0.00 - no AS or crit "
            "language in any of her five slots. off_axis_stat 0.00 is verifiable "
            "structurally: no Orianna damage block carries caster_max_hp_pct, "
            "caster_bonus_hp_pct, bonus_armor_pct or bonus_mr_pct; every one carries "
            "ap_pct only, so health converts to ability DPS at exactly zero."
        ),
    ),
    "Poppy": KitConversion(
        attack_speed=0.35, crit=0.35, on_hit=0.35, off_axis_stat=1.00,
        note=(
            "P Iron Ambassador: 'Periodically, Poppy's next basic attack is empowered "
            "to throw her buckler'. The word is 'Periodically', not 'every N attacks' "
            "- the proc is cooldown-gated, so purchased attack speed does not raise "
            "its rate. Her other blocks are bonus_ad_pct / ap_pct / target_max_hp_pct "
            "with zero crit or on-hit language. off_axis_stat 1.00 on the tank route: "
            "she IS the EHP objective."
        ),
    ),
    "Quinn": KitConversion(
        attack_speed=0.20, crit=0.55, on_hit=0.15, off_axis_stat=1.00,
        note=(
            "P Harrier: 'Quinn's basic attacks against Vulnerable targets are "
            "empowered to consume the mark to deal 10 : 95 (based on level) "
            "(+ 16% : 50% (based on level) AD) bonus physical damage', and the "
            "16.14.1 record carries cooldown [8.0, 8.0, 8.0] with damage_blocks "
            "EMPTY (parse_status no_damage). attack_speed 0.20: the mark sits on "
            "a STATIC cooldown, so purchased attack speed cannot raise the proc "
            "rate at all, and W Heightened Senses already self-supplies "
            "[28,41,54,67,80] pct bonus attack speed on every Vulnerable "
            "consume - twice diluted; nonzero only because her ordinary autos "
            "still swing faster. on_hit 0.15: same static-cooldown argument, and "
            "her real builds are ~0 pct on-hit (DS_SWEEP_TRACKER batch19), so "
            "only her plain autos carry an on-hit proc. crit 0.55 is "
            "deliberately the HIGHEST of the three and is NOT a 'she does not "
            "crit' claim: the Harrier proc itself does not crit, but crit chance "
            "scales its cooldown (5s down to 1.83s), a term no objective models, "
            "so the two errors partly cancel and her late build genuinely runs "
            "Lord Dominik's / Infinity Edge 5th-6th. off_axis_stat stays 1.00 on "
            "purpose - see the over-fire note below."
        ),
    ),
    # OVER-FIRE GUARD for the Quinn entry, the Blackfire shape from the Orianna
    # seed. It is TRUE that health converts to zero carry-route DPS for her - but
    # that is true of every AD carry, so it is a class-wide statement, not Quinn
    # kit signal, and the channel is a 300g-of-off-axis-stat presence test that
    # fires on Edge of Night (3814, 350 HP). Edge of Night IS a real Quinn core
    # item (Profane Hydra or Hubris -> boots -> Collector -> Edge of Night ->
    # Lord Dominik's -> Infinity Edge). A fraction below 1.0 would demote her own
    # build alongside the leads this seed exists to suppress, so the channel is
    # left at face value and the whole correction rides on the three offensive
    # channels.
    "RekSai": KitConversion(
        attack_speed=0.45, crit=0.40, on_hit=0.45,
        note=(
            "Q Queen's Wrath: 'Rek'Sai gains 35% bonus attack speed for 3 seconds. "
            "Her next basic attack within the duration will have an uncancellable "
            "windup and deal bonus physical damage... Queen's Wrath's damage to the "
            "primary target is affected by critical strike modifiers.' Cooldown "
            "[4,3.5,3,2.5,2], so a self-supplied 35 pct with 3s uptime is near "
            "permanent at rank 5 and dilutes purchased AS. crit 0.40 because crit is "
            "stated to modify the Q hit ONLY, one attack per cast. NOTE the spec's "
            "'3 autos per Fury cycle' is NOT in 16.14.1 prose - it reads 'Her next "
            "basic attack', singular. Seeded from the prose."
        ),
    ),
    "Rengar": KitConversion(
        attack_speed=0.30, crit=0.35, on_hit=0.45,
        note=(
            "Q Savagery empowers 'his next two basic attacks within 3 seconds to gain "
            "40% bonus attack speed'; Ferocity Q grants '50% : 101% (based on level) "
            "bonus attack speed for 5 seconds' on a [6,5.5,5,4.5,4]s cooldown, so "
            "purchased AS is heavily diluted. crit 0.35 because Q's crit is an "
            "explicit FORMULA on crit chance - 'critically strike for ((31.25% + 30%) "
            "critical strike chance + 40%) AD' - not an ordinary crit roll, so "
            "purchased crit enters through a flatter coefficient. That formula is "
            "exactly why a boolean has-a-crit-term gate is the wrong shape."
        ),
    ),
    "Riven": KitConversion(
        attack_speed=0.30, crit=0.35, on_hit=0.55,
        note=(
            "P Runic Blade: 'Riven's ability casts generate a stack of Charge... "
            "stacking up to 3 times. Riven's basic attacks are empowered to each "
            "consume a stack to deal bonus physical damage equal to 30% : 50% (based "
            "on level) AD' and 'The bonus damage is affected by critical strike "
            "modifiers and applies life steal at 100% effectiveness.' Charge "
            "GENERATION is ability-cast-bound, so purchased attack speed only spends "
            "at most 3 charges faster and is wasted beyond the generation rate. "
            "UNVERIFIED: the 16.14.1 prose says Runic Blade applies LIFE STEAL at "
            "100% effectiveness; it does NOT say it applies on-hit effects. on_hit "
            "0.55 is seeded on her ordinary autos only."
        ),
    ),
}

_CHANNELS = ("attack_speed", "crit", "on_hit", "off_axis_stat")


def kit_conversion(champion_id: str, champ_rec: dict | None = None) -> KitConversion:
    """Return the conversion vector for ``champion_id``, or the identity.

    Resolves by champion id first, then by the display ``name`` on ``champ_rec``
    when supplied, matching the id-then-name pattern the sibling credit
    registries use. An unknown champion always resolves to the identity.
    """
    entry = _KIT_CONVERSION.get(str(champion_id))
    if entry is not None:
        return entry
    if champ_rec:
        name = str(champ_rec.get("name") or "")
        entry = _KIT_CONVERSION.get(name)
        if entry is not None:
            return entry
    return _IDENTITY


def registry_champion_ids() -> frozenset[str]:
    """Every champion id carrying a seeded (non-identity) conversion vector."""
    return frozenset(_KIT_CONVERSION)


# --- item exposure ---------------------------------------------------------

# Per-stat gold prices derived from the 16.14.1 component items themselves, not
# from memory: Amplifying Tome 400g/20 AP, Long Sword 350g/10 AD, Ruby Crystal
# 400g/150 HP, Sapphire Crystal 300g/300 mana, Cloth Armor 300g/15 armor,
# Null-Magic Mantle 400g/20 MR, Dagger 250g/0.10 AS, Cloak of Agility 600g/0.15
# crit. FlatHPPoolMod matches ehp.py:2194 _GOLD_PER_HP exactly. NOTE ehp.py:2193
# uses _GOLD_PER_MR = 18.0 where the 16.14.1 component tree derives 20.0; that
# divergence is left alone rather than "fixed" here.
_GOLD_PER = {
    "FlatMagicDamageMod": 20.0,
    "FlatPhysicalDamageMod": 35.0,
    "FlatHPPoolMod": 400.0 / 150.0,
    "FlatMPPoolMod": 1.0,
    "FlatArmorMod": 20.0,
    "FlatSpellBlockMod": 20.0,
}
_GOLD_PER_AS = 2500.0    # per 1.00 PercentAttackSpeedMod
_GOLD_PER_CRIT = 4000.0  # per 1.00 FlatCritChanceMod

# Which stats the objective CANNOT convert into its own output. Mana is absent
# from the "ap" set deliberately: it is mage-convertible, and that single fact is
# what separates Blackfire Torch (600 mana, untouched) from Liandry's Torment
# (300 HP = 800g off-axis, penalised) for Orianna.
_OFF_AXIS_KEYS = {
    "ad": {"FlatHPPoolMod", "FlatArmorMod", "FlatSpellBlockMod", "FlatMagicDamageMod"},
    "ap": {"FlatHPPoolMod", "FlatArmorMod", "FlatSpellBlockMod",
           "FlatPhysicalDamageMod", "PercentLifeStealMod"},
    "ehp": {"FlatPhysicalDamageMod", "FlatMagicDamageMod", "PercentLifeStealMod"},
    # RM-115 p4: the BLENDED objective. ds.hybrid scores alpha*dps + beta*ehp,
    # so a stat is off-axis for it only when it is off-axis for BOTH terms -
    # i.e. the INTERSECTION of the damage set and the "ehp" set above, not
    # either one alone. Health, armor and magic resist are therefore ON-axis
    # here even though the damage sets penalise them: for a bruiser they ARE
    # the beta term. Reproduces the Olaf note at :128-129 ("nothing is off-axis
    # for him except AP") exactly.
    #
    # Passing a bare "ad"/"ap" here instead would be inert for the four bruiser
    # entries (their off_axis_stat is 1.00, so the shortfall is 0 and the set is
    # never consulted) but would OVER-FIRE for the two entries with
    # off_axis_stat 0.00 - Naafiri and Orianna - which /rank-bruiser will
    # happily accept. `_off_axis_intersection_rm115` guards the derivation.
    "hybrid_ad": {"FlatMagicDamageMod"},
    "hybrid_ap": {"FlatPhysicalDamageMod", "PercentLifeStealMod"},
}

# One component's worth of off-axis stat. Liandry's clears it at 800g and
# Blackfire sits at 0, so the Orianna anchor has wide margin; Mejai's Soulstealer
# (100 HP = 267g) is the nearest item below the line.
_OFF_AXIS_MIN_GOLD = 300.0


def damage_objective(snapshot, champion_id: str) -> str:
    """Return ``"ap"`` for a magic-primary champion, else ``"ad"``.

    Same DDragon ``info.attack`` / ``info.magic`` split ``hybrid._damage_axis``
    uses (``hybrid.py:73-79``), reimplemented locally rather than imported so
    this module stays leaf-level and cannot create an import cycle with the
    rankers that consume it.
    """
    rec = snapshot.champions.get(str(champion_id)) or {}
    info = rec.get("info") or {}
    return "ap" if int(info.get("magic", 0) or 0) > int(info.get("attack", 0) or 0) else "ad"


def _has_per_attack_proc(item_id: str) -> bool:
    eff = ITEM_EFFECTS.get(str(item_id))
    if eff is None:
        return False
    return any(
        (getattr(p, "every_n_attacks", 0) or 0) > 0
        for p in (getattr(eff, "periodics", ()) or ())
    )


def item_exposures(item_id: str, rec: dict, objective: str) -> dict[str, float]:
    """How much of a candidate rides on each channel, each in [0, 1].

    Two channels use GOLD SHARE and two use PRESENCE. The asymmetry is forced by
    measurement, not taste:

    * Gold share fails for on-hit. BotRK is 3200g and prices out at 40 AD (1400)
      + 25 pct AS (625) + 10 pct lifesteal (1286) = 3311g, i.e. residual gold
      ZERO, even though Mist's Edge is the entire item. A residual-gold proxy
      scores its on-hit exposure at zero, which is exactly backwards.
    * Presence fails for attack speed. It crushes Stridebreaker, whose AS is only
      19 pct of its gold, and drops it far BELOW its ungated rank.
    * Presence is the house precedent for axis channels: ``_coherence_key`` tests
      ``"SpellDamage" in tags``, a bare presence test (``onhit_dps.py:505``).

    The on-hit CONJUNCTION is load-bearing. The DDragon ``OnHit`` tag alone is not
    a marker of auto-attack-cadence value: Black Cleaver, Trinity Force, Essence
    Reaver, Lich Bane and Iceborn Gauntlet all carry it while proccing on a
    spellblade clock rather than per attack. Conversely Stridebreaker has a
    per-attack proc and NO ``OnHit`` tag. Requiring both is the same
    two-independent-sources shape as ``_onhit_ap_axis`` (``onhit_dps.py:316-329``).
    """
    stats = rec.get("stats") or {}
    tags = set(rec.get("tags") or ())
    gold = float((rec.get("gold") or {}).get("total", 0) or 0) or 1.0
    off_axis_gold = sum(
        _GOLD_PER[k] * v
        for k, v in stats.items()
        if k in _GOLD_PER and k in _OFF_AXIS_KEYS.get(objective, ())
    )
    return {
        "attack_speed": min(
            1.0, float(stats.get("PercentAttackSpeedMod", 0.0) or 0.0) * _GOLD_PER_AS / gold
        ),
        "crit": min(
            1.0, float(stats.get("FlatCritChanceMod", 0.0) or 0.0) * _GOLD_PER_CRIT / gold
        ),
        "on_hit": 1.0 if ("OnHit" in tags and _has_per_attack_proc(item_id)) else 0.0,
        "off_axis_stat": 1.0 if off_axis_gold >= _OFF_AXIS_MIN_GOLD else 0.0,
    }


def conversion_factor(
    conv: KitConversion, item_id: str, rec: dict, strength: float, objective: str
) -> float:
    """Multiplier in [0, 1] for a candidate's SORT score. Never above 1.0."""
    factor = 1.0
    exposures = item_exposures(item_id, rec, objective)
    for channel in _CHANNELS:
        exposure = exposures[channel]
        if exposure <= 0.0:
            continue
        shortfall = 1.0 - getattr(conv, channel)
        if shortfall <= 0.0:
            continue
        factor *= 1.0 - strength * exposure * shortfall
    return factor if factor > 0.0 else 0.0
