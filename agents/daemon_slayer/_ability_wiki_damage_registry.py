# arch: hand-authored wiki ability-damage payloads for champions the Meraki bulk snapshot never shipped | section=agents/daemon_slayer | frozen=no
"""Hand-authored ability payloads for the two champions Meraki never shipped.

MEASURED DEFECT (2026-07-25). ``data/daemon_slayer/16.14.1/champions.json``
carries 173 champions; ``champion_abilities.json`` carries 171. The set
difference is exactly ``["Locke", "Zaahen"]``. Champions with zero
``attribute_kind == "damage"`` block: ZERO - i.e. every other champion is fed
by Meraki and only these two fall through entirely, and they fall through to a
DEGENERATE zero:

* ``compute_burst_damage`` returns ``total_burst_damage == 0.0`` with every
  cast noted ``"ability data unavailable"`` and ``form_index == -1``.
* ``rank_items(..., fight_length=...)`` reads that as ``baseline_burst 0.0``
  (``rank.py:1118-1131``), so every one of the 706 candidates scores
  ``delta_burst 0.0`` - the entire ranked table is degenerate.

Measured on a live ``:8860`` at ``items=["3142","6691","3814"], level=13,
target_armor=140, target_mr=90, target_hp=2800``: ``POST /rank-assassin``
Locke ``baseline_burst 0.0`` against Zed's ``807.3862433862435``; a
173-champion ``/burst`` sweep found exactly two degenerate rows (Locke 0.0,
Zaahen 0.0) with the lowest non-zero at Aphelios 259.5.

WHY A REGISTRY AND NOT A PIPELINE FIX. The upstream ``leveling`` payload is
not on disk anywhere:

* ``champion_abilities.json`` (Meraki bulk) has no Locke / Zaahen key at all.
* ``cdragon_ability_ratios.json`` and ``cdragon_spell_stats.json`` cover 9 and
  13 champions respectively - neither includes them.
* ``wiki_ability_stats.json`` (232815 B, 1046 abilities) carries NO ``leveling``
  key for ANY champion: ``tools/daemon_slayer_wiki_ability_extract.py`` fetches
  the page then keeps only geometry / cooldown / CC params and discards
  ``leveling``. Promoting it is a schema lift on that extractor plus a
  re-extract, which is a separate slice.

So the numbers have to be authored, in code, from the wiki - exactly the
``_ability_base_overrides`` (A-03 / RM-81) and ``_passive_damage_overrides``
(item 238 / GAP-2) precedent. Unlike those two this registry INJECTS a
champion rather than amending an existing form, which is why it hooks the
snapshot's ``data`` container rather than a per-form callback.

DEFAULT-ON, and why that is safe. Every other seam in ``abilities.py`` ships
DEFAULT-OFF because it MUTATES a form the engine already serves, so OFF is the
byte-identical contract. This one is different in kind: a champion the
snapshot does not contain has no prior behavior to preserve, so there is no
regression surface to protect. The injection is KEYS-NOT-PRESENT-ONLY - a
champion already in ``data`` is never touched, which the test file proves by
sweeping all 171 pre-existing champions OFF vs ON and requiring byte-identical
``total_burst_damage``. The kwarg
``AbilitiesSnapshot.load(apply_wiki_ability_damage=...)`` is appended at the
END of the signature and defaults True so the seam can still be disabled (to
reproduce pre-registry behavior in a test, or if a future Meraki re-extract
ships the champions for real - at which point the keys-not-present guard makes
this registry silently inert without any code change).

SOURCE. Every number below was transcribed from the LIVE wiki
``Template:Data <Champion>/<Ability>`` wikitext, fetched
2026-07-25 via ``https://wiki.leagueoflegends.com/en-us/api.php``
``action=query&prop=revisions&rvslots=main&rvprop=content`` - the same host and
endpoint ``tools/daemon_slayer_wiki_ability_extract.py`` uses
(``:108-110``). The raw ``|leveling`` line is quoted verbatim beside every
entry it produced. The key mapping was NOT guessed: the wiki's own ability
redirects give it, e.g. ``Template:Data Locke/Q -> Template:Data Locke/Ritual
Nails``, ``Template:Data Zaahen/R -> Template:Data Zaahen/Grim Deliverance``.

LINEAR EXPANSION IS AN ASSUMPTION. ``{{ap|X to Y}}`` names only the rank-1 and
rank-max endpoints; ``_ramp`` expands it linearly across the ability's rank
count (5 basic / 3 ult), which is the same reading
``_ability_base_overrides._ramp`` uses and which its own method note calls
"exactly what the wiki ``{{ap|X to Y}}`` macro means". It is KNOWN-WRONG for
some champions (a handful of Riot series are not evenly spaced). It is
independently corroborated here for every COOLDOWN series: each ``_ramp``ed
cooldown below reproduces ``champions.json`` ``lolmath.cooldowns`` for that
champion exactly, on all 8 abilities - e.g. Zaahen W ``{{ap|14 to 12}}`` ->
``(14, 13.5, 13, 12.5, 12)`` against lolmath ``[14, 13.5, 13, 12.5, 12]``.
That does not prove the damage series are linear, but it does prove the
expansion rule matches Riot's own data for these two champions.

CONVENTIONS, and the two places this deviates from Meraki.

1. BLOCK ORDER IS DAMAGE-FIRST. ``ability_dps._select_blocks`` reads
   ``damage_blocks[0]`` under the default ``block_strategy="first"`` and
   ``_evaluate_block`` does NOT filter on ``attribute_kind`` - a shield /
   modifier / heal block sitting at index 0 is evaluated as raw damage. 190 of
   the shipped Meraki forms have exactly that shape (a pre-existing quirk, out
   of scope here). Because these payloads are authored, damage blocks are
   ordered FIRST and non-damage blocks trail. Where an ability has NO damage
   at all (Locke W) NO block is emitted, so ``_select_blocks`` short-circuits
   to 0.0 rather than evaluating a grey-health cap as damage.

2. AGGREGATE / RESTATEMENT BLOCKS ARE KEPT. Meraki keeps "Total X Damage"
   rows as ``attribute_kind="damage"`` (208 of them across the roster), and
   these payloads do the same so Locke and Zaahen behave like their peers
   under every ``block_strategy``. They are inert under the default "first".

3. FORM-LEVEL ``damage_type`` FOLLOWS BLOCK 0, NOT THE PAGE HEADER, on the two
   pages whose ``|damagetype`` is a compound. ``burst`` applies ONE mitigation
   factor per form from ``form.damage_type``, and MIXED splits 50/50
   armor/MR (``ability_dps.py:371,384``). Locke R's page says "Magic True" but
   the TRUE half is the execute threshold, which is authored as a non-damage
   block; Zaahen E's page says "Physical Magic" but the magic half is the
   outer-edge percent-max-HP block at index 2. Labelling either form MIXED
   would mis-mitigate the pure block 0 that the default strategy actually
   reads, so both are labelled by their block 0. The compound header is
   recorded in each form's ``parse_notes``.

NOT AUTHORED - and never invented. The three passives (Locke's Silver Stake,
Zaahen's Cultivation of War, whose ``Determination`` page is a redirect to it)
carry NO ``|leveling`` param on the wiki at all. Their forms are emitted with
an EMPTY ``damage_blocks`` tuple and ``parse_status="no_damage"``, matching how
Meraki ships most passives. Locke's Silver Stake on-hit magic damage and
Zaahen's Determination bonus-AD are effects-text-only, i.e. exactly the shape
the DEFAULT-OFF ``_passive_damage_overrides`` seam exists for - a separate,
measured decision. The default combo sequence is ``("Q","W","E","AA","R","AA")``
(``burst.DEFAULT_COMBO_SEQUENCE``), so no P cast is scored either way.
"""
from __future__ import annotations

from typing import Any, Iterator

# --- wiki provenance ---------------------------------------------------------

_WIKI_HOST = "https://wiki.leagueoflegends.com"
_FETCHED = "2026-07-25"

# (champion_id, key) -> (Template:Data page title, fetch date).
# The mapping was read off the wiki's OWN ability redirects, not assumed:
#   Template:Data Locke/I  -> Template:Data Locke/Silver Stake
#   Template:Data Locke/Q  -> Template:Data Locke/Ritual Nails
#   Template:Data Locke/W  -> Template:Data Locke/Soul Ignition
#   Template:Data Locke/E  -> Template:Data Locke/Ashen Pursuit
#   Template:Data Locke/R  -> Template:Data Locke/Purgatory
#   Template:Data Zaahen/I -> Template:Data Zaahen/Cultivation of War
#   Template:Data Zaahen/Q -> Template:Data Zaahen/The Darkin Glaive
#   Template:Data Zaahen/W -> Template:Data Zaahen/Dreaded Return
#   Template:Data Zaahen/E -> Template:Data Zaahen/Aureate Rush
#   Template:Data Zaahen/R -> Template:Data Zaahen/Grim Deliverance
WIKI_SOURCES: dict[tuple[str, str], tuple[str, str]] = {
    ("Locke", "P"): ("Template:Data Locke/Silver Stake", _FETCHED),
    ("Locke", "Q"): ("Template:Data Locke/Ritual Nails", _FETCHED),
    ("Locke", "W"): ("Template:Data Locke/Soul Ignition", _FETCHED),
    ("Locke", "E"): ("Template:Data Locke/Ashen Pursuit", _FETCHED),
    ("Locke", "R"): ("Template:Data Locke/Purgatory", _FETCHED),
    ("Zaahen", "P"): ("Template:Data Zaahen/Cultivation of War", _FETCHED),
    ("Zaahen", "Q"): ("Template:Data Zaahen/The Darkin Glaive", _FETCHED),
    ("Zaahen", "W"): ("Template:Data Zaahen/Dreaded Return", _FETCHED),
    ("Zaahen", "E"): ("Template:Data Zaahen/Aureate Rush", _FETCHED),
    ("Zaahen", "R"): ("Template:Data Zaahen/Grim Deliverance", _FETCHED),
}


def _ramp(low: float, high: float, count: int) -> list[float]:
    """The wiki ``{{ap|X to Y}}`` series: a linear ramp over ``count`` ranks.

    ``_ramp(150, 300, 3) -> [150.0, 225.0, 300.0]``. Rounded to 6 places so the
    authored values stay stable + ASCII-clean - the same helper and rounding
    convention as ``_ability_base_overrides._ramp``.

    LINEAR EXPANSION IS AN ASSUMPTION (see the module docstring): the wiki
    macro names only the endpoints, and a handful of Riot series are not evenly
    spaced. Every cooldown series produced by this helper below is
    cross-checked against ``champions.json`` ``lolmath.cooldowns``.
    """
    if count < 2:
        return [float(low)]
    span = count - 1
    return [round(low + (high - low) * i / span, 6) for i in range(count)]


def _flat(value: float) -> list[float]:
    """A rank-invariant series. ``DamageBlock.value_at`` clamps a 1-element
    list to that value at every rank, which is how Meraki stores flat ratios."""
    return [float(value)]


def _dmg(attribute: str, **fields: Any) -> dict[str, Any]:
    return {"attribute": attribute, "attribute_kind": "damage", **fields}


def _block(attribute: str, kind: str, **fields: Any) -> dict[str, Any]:
    return {"attribute": attribute, "attribute_kind": kind, **fields}


# --- Locke (id 805, "the Ashen Exorcist", Assassin/Mage, Mana, AP) -----------
#
# Cooldown cross-check against champions.json lolmath.cooldowns for Locke:
#   Q [10, 9, 8, 7, 6]  W [18, 17, 16, 15, 14]  E [10]*5  R [120, 100, 80]
# Every _ramp below reproduces those exactly.

_LOCKE: dict[str, list[dict[str, Any]]] = {
    # Template:Data Locke/Silver Stake (skill = I), fetched 2026-07-25.
    # The page has NO |leveling param. Its damage lives only in |description:
    #   "|description  = {{sbc|Innate:}} '''Locke's''' {{tip|basic attacks}}
    #    deal {{pplevel|5 to 40|color=magic damage}} {{as|(+ 10% AP)}}
    #    {{as|'''bonus''' magic damage}} {{tip|on-hit}}, increased by ...
    #    up to {{pplevel|5*2 to 40*2|color=magic damage}} {{as|(+ 20% AP)}}."
    # ``pplevel`` is per CHAMPION LEVEL, on-hit, and conditional on target
    # missing health - the effects-text-only shape the DEFAULT-OFF
    # ``_passive_damage_overrides`` seam owns. NOT authored here: emitting it
    # as a P damage block would credit an on-hit passive as a spell cast.
    "P": [
        {
            "key": "P",
            "name": "Silver Stake",
            "form_index": 0,
            "icon": None,
            "cooldown": None,
            "cost": None,
            "damage_type": "MAGIC",
            "targeting": "Passive",
            "affects": "Enemies",
            "resource": None,
            "is_aoe": False,
            "damage_blocks": [],
            "raw_effects_count": 1,
            "raw_leveling_count": 0,
            "parse_status": "no_damage",
            "parse_notes": [
                "wiki page carries no |leveling param",
                "on-hit pplevel 5 to 40 (+10% AP) magic damage is effects-text only",
            ],
        }
    ],
    # Template:Data Locke/Ritual Nails (skill = Q), fetched 2026-07-25.
    # Page vardefines: b1=50, b2=82, ap=20, s1=18, s2=50, sap1=25, sap2=35.
    #   "|leveling     = {{st|Magic Damage per Nail|{{ap|{{#var:b1}} to
    #    {{#var:b2}}}} {{as|(+ {{#var:ap}}% AP)}}
    #    |Maximum Nail Damage|{{ap|{{#var:b1}}*3 to {{#var:b2}}*3}}
    #    {{as|(+ {{ap|{{#var:ap}}*3}}% AP)}}}}"
    #   "|leveling3    = {{st|One Stack Bonus Damage|{{ap|{{#var:s1}} to
    #    {{#var:s2}}}} {{as|(+ {{ap|{{#var:sap1}} to {{#var:sap2}}}}% AP)}}
    #    |Two Stacks Bonus Damage|{{ap|{{#var:s1}}*2*1.2 to {{#var:s2}}*2*1.2}}
    #    {{as|(+ {{ap|{{#var:sap1}}*2*1.2 to {{#var:sap2}}*2*1.2}}% AP)}}
    #    |Three Stacks Bonus Damage|{{ap|{{#var:s1}}*3*1.4 to
    #    {{#var:s2}}*3*1.4}} {{as|(+ {{ap|{{#var:sap1}}*3*1.4 to
    #    {{#var:sap2}}*3*1.4}}% AP)}}}}
    #    {{st|Maximum Total Magic Damage|{{ap|({{#var:b1}}+{{#var:s1}}*1.4)*3
    #    to ({{#var:b2}}+{{#var:s2}}*1.4)*3}} {{as|(+
    #    {{ap|({{#var:ap}}+{{#var:sap1}}*1.4)*3 to
    #    ({{#var:ap}}+{{#var:sap2}}*1.4)*3}}% AP)}}}}"
    #   "|cooldown = {{ap|10 to 6}}   |cost = 70   |damagetype = Magic"
    "Q": [
        {
            "key": "Q",
            "name": "Ritual Nails",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(10, 6, 5),
            "cost": _flat(70),
            "damage_type": "MAGIC",
            "targeting": "Direction",
            "affects": "Enemies",
            "resource": "MANA",
            # notes: "Applies area damage for the nail missile".
            "is_aoe": True,
            "damage_blocks": [
                # 50 to 82 (+ 20% AP)
                _dmg("Magic Damage per Nail",
                     base=_ramp(50, 82, 5), ap_pct=_flat(20)),
                # 50*3 to 82*3 = 150 to 246 (+ 20*3 = 60% AP)
                _dmg("Maximum Nail Damage",
                     base=_ramp(150, 246, 5), ap_pct=_flat(60)),
                # Soul Nails stack consumption (leveling3): 18 to 50 (+ 25 to 35% AP)
                _dmg("One Stack Bonus Damage",
                     base=_ramp(18, 50, 5), ap_pct=_ramp(25, 35, 5)),
                # 18*2*1.2 = 43.2 to 50*2*1.2 = 120 (+ 25*2*1.2 = 60 to 35*2*1.2 = 84% AP)
                _dmg("Two Stacks Bonus Damage",
                     base=_ramp(43.2, 120, 5), ap_pct=_ramp(60, 84, 5)),
                # 18*3*1.4 = 75.6 to 50*3*1.4 = 210 (+ 25*3*1.4 = 105 to 35*3*1.4 = 147% AP)
                _dmg("Three Stacks Bonus Damage",
                     base=_ramp(75.6, 210, 5), ap_pct=_ramp(105, 147, 5)),
                # (50+18*1.4)*3 = 225.6 to (82+50*1.4)*3 = 456
                # (+ (20+25*1.4)*3 = 165 to (20+35*1.4)*3 = 207% AP)
                _dmg("Maximum Total Magic Damage",
                     base=_ramp(225.6, 456, 5), ap_pct=_ramp(165, 207, 5)),
            ],
            "raw_effects_count": 3,
            "raw_leveling_count": 6,
            "parse_status": "ok",
            "parse_notes": ["hand-authored from Template:Data Locke/Ritual Nails"],
        }
    ],
    # Template:Data Locke/Soul Ignition (skill = W), fetched 2026-07-25.
    #   "|leveling     = {{st|Movement speed|{{ap|40 to 60}}%
    #    {{as|(+ 2% per 100 AP)}}}}
    #    {{st|Damage taken grey health cap|{{ap|40 to 160}}
    #    {{as|(+ 120% AP)}}}}"
    #   "|cooldown = {{ap|18 to 14}}   |cost = {{ap|50 to 70}}"
    #   The page carries NO |damagetype param - Soul Ignition deals no damage.
    # Both leveling rows are non-damage (a movement-speed modifier and a
    # grey-health / shield cap). Emitting either as block 0 would have
    # ``_select_blocks`` evaluate it as raw damage under the default "first"
    # strategy, so NO block is emitted and the form contributes 0.0 - which is
    # the truthful answer for a damageless self-buff.
    "W": [
        {
            "key": "W",
            "name": "Soul Ignition",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(18, 14, 5),
            "cost": _ramp(50, 70, 5),
            "damage_type": None,
            "targeting": "Auto",
            "affects": "Self",
            "resource": "MANA",
            "is_aoe": False,
            "damage_blocks": [],
            "raw_effects_count": 4,
            "raw_leveling_count": 2,
            "parse_status": "no_damage",
            "parse_notes": [
                "leveling rows are non-damage: movement speed 40 to 60 pct, "
                "grey-health cap 40 to 160 (+120% AP)",
                "omitted so block 0 is never evaluated as damage",
            ],
        }
    ],
    # Template:Data Locke/Ashen Pursuit (skill = E), fetched 2026-07-25.
    #   "|leveling     = {{st|Blink Magic Damage|{{ap|40 to 80}}
    #    {{as|(+ 40% AP)}}}}"
    #   "|leveling2    = {{st|Dash Magic Damage|{{ap|40 to 120}}
    #    {{as|(+ 40% AP)}}}}
    #    {{st|Total Magic Damage|{{ap|40+40 to 80+120}}
    #    {{as|(+ {{ap|40+40}}% AP)}}}}"
    #   "|cooldown = 10   |cost = {{ap|30 to 70}}   |damagetype = Magic"
    "E": [
        {
            "key": "E",
            "name": "Ashen Pursuit",
            "form_index": 0,
            "icon": None,
            "cooldown": _flat(10),
            "cost": _ramp(30, 70, 5),
            "damage_type": "MAGIC",
            "targeting": "Location",
            "affects": "Self, Enemies",
            "resource": "MANA",
            # notes: "The blink deals area damage."
            "is_aoe": True,
            "damage_blocks": [
                _dmg("Blink Magic Damage",
                     base=_ramp(40, 80, 5), ap_pct=_flat(40)),
                _dmg("Dash Magic Damage",
                     base=_ramp(40, 120, 5), ap_pct=_flat(40)),
                # 40+40 = 80 to 80+120 = 200 (+ 40+40 = 80% AP)
                _dmg("Total Magic Damage",
                     base=_ramp(80, 200, 5), ap_pct=_flat(80)),
            ],
            "raw_effects_count": 4,
            "raw_leveling_count": 3,
            "parse_status": "ok",
            "parse_notes": ["hand-authored from Template:Data Locke/Ashen Pursuit"],
        }
    ],
    # Template:Data Locke/Purgatory (skill = R), fetched 2026-07-25.
    #   "|leveling     = {{st|Magic Damage|{{ap|150 to 300}}
    #    {{as|(+ 60% AP)}}}}
    #    {{st|Execute Threshold|{{as|{{ap|10 to 12}}%|hp}}
    #    {{as|(+ {{fd|0.5}}% per Sealed Champion stack)|buzzword}}
    #    {{as|of the target's '''maximum''' health}}}}"
    #   "|cooldown = {{ap|120 to 80}}   |cost = 100
    #    |damagetype   = Magic True"
    # damage_type: the page header is the compound "Magic True", but the TRUE
    # half is the EXECUTE, authored below as a non-damage block (a threshold is
    # not a damage quantity, and its per-stack term is unbounded state the
    # engine has no input for). Block 0 is pure magic, so MAGIC is the correct
    # single mitigation label - MIXED would 50/50 split it against armor.
    "R": [
        {
            "key": "R",
            "name": "Purgatory",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(120, 80, 3),
            "cost": _flat(100),
            "damage_type": "MAGIC",
            "targeting": "Location",
            "affects": "Enemies, Self",
            "resource": "MANA",
            # notes: "Applies area damage with the nail".
            "is_aoe": True,
            "damage_blocks": [
                _dmg("Magic Damage", base=_ramp(150, 300, 3), ap_pct=_flat(60)),
                _block("Execute Threshold", "other",
                       target_max_hp_pct=_ramp(10, 12, 3)),
            ],
            "raw_effects_count": 2,
            "raw_leveling_count": 2,
            "parse_status": "ok",
            "parse_notes": [
                "page |damagetype is the compound 'Magic True'",
                "the TRUE half is the execute, kept as a non-damage block",
            ],
        }
    ],
}


# --- Zaahen (id 904, "The Unsundered", Fighter/Assassin, Mana, AD) -----------
#
# Cooldown cross-check against champions.json lolmath.cooldowns for Zaahen:
#   Q [10, 9, 8, 7, 6]  W [14, 13.5, 13, 12.5, 12]  E [10, 9.5, 9, 8.5, 8]
#   R [110, 95, 80]
# Every _ramp below reproduces those exactly.

_ZAAHEN: dict[str, list[dict[str, Any]]] = {
    # Template:Data Zaahen/Cultivation of War (skill = I), fetched 2026-07-25.
    # ``Template:Data Zaahen/Determination`` is a REDIRECT to this page - the
    # two are one ability, not two.
    # The page has NO |leveling param. Determination's bonus AD lives only in
    # |description2 as a per-level {{pp|...}} percent-of-AD buff, plus the
    # max-stack resurrection. Both are effects-text-only self-buffs and belong
    # to the DEFAULT-OFF ``_passive_damage_overrides`` /
    # ``_passive_revive_overrides`` seams, not here. NOT authored.
    "P": [
        {
            "key": "P",
            "name": "Cultivation of War",
            "form_index": 0,
            "icon": None,
            "cooldown": None,
            "cost": None,
            "damage_type": None,
            "targeting": "Passive",
            "affects": "Self",
            "resource": None,
            "is_aoe": False,
            "damage_blocks": [],
            "raw_effects_count": 2,
            "raw_leveling_count": 0,
            "parse_status": "no_damage",
            "parse_notes": [
                "wiki page carries no |leveling param",
                "Determination bonus AD + max-stack revive are effects-text only",
                "Template:Data Zaahen/Determination redirects to this page",
            ],
        }
    ],
    # Template:Data Zaahen/The Darkin Glaive (skill = Q), fetched 2026-07-25.
    # Page vardefines: q_bad1=20, q_bad5=40 (bonus-AD ratio percent, both casts).
    #   "|leveling     = {{st|Total Physical Damage|{{ap|15 to 75}}
    #    {{as|(+ 100% AD)}} {{as|(+ {{ap|{{#var:q_bad1}} to
    #    {{#var:q_bad5}}}}% '''bonus''' AD)}}|Physical Damage per Hit|
    #    {{ap|15/2 to 75/2}} {{as|(+ {{ap|100/2}}% AD)}}
    #    {{as|(+ {{ap|{{#var:q_bad1}}/2 to {{#var:q_bad5}}/2}}%
    #    '''bonus''' AD)}}}}
    #    {{st|Champion Healing|{{as|{{ap|5 to 9}}% of his '''maximum''' health}}
    #    |Non-Champion Healing|{{as|{{ap|5*0.5 to 9*0.5}}% of his
    #    '''maximum''' health}}}}"
    #   "|leveling3    = {{st|Bonus Physical Damage|{{ap|25 to 125}}
    #    {{as|(+ {{ap|{{#var:q_bad1}} to {{#var:q_bad5}}}}%
    #    '''bonus''' AD)}}}}"
    #   "|cooldown = {{ap|10 to 6}}   |cost = 25   |damagetype = Physical"
    # leveling3 is the RECAST (icon3 "The Darkin Glaive 2", itself a redirect
    # back to this page) - flattened onto form_index 0 AFTER the first-cast
    # blocks, so the default "first" strategy still reads the headline Q.
    "Q": [
        {
            "key": "Q",
            "name": "The Darkin Glaive",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(10, 6, 5),
            "cost": _flat(25),
            "damage_type": "PHYSICAL",
            "targeting": "Auto",
            "affects": "Self, Enemies",
            "resource": "MANA",
            "is_aoe": False,
            "damage_blocks": [
                # 15 to 75 (+ 100% AD) (+ 20 to 40% bonus AD)
                # AD-FAMILY SPLIT: this is the only ability in either kit whose
                # wiki row carries BOTH a total-AD and a bonus-AD ratio, and the
                # repo enforces a machine guard that no single damage block may
                # hold two fields of one stat family (``_AD_FIELDS`` in
                # tests/test_cdragon_ratio_matcher.py:33 +
                # tests/test_cdragon_surplus_ad_a29.py:83 - both sweep the WHOLE
                # snapshot, not just the sidecar merge). The two ratios are
                # therefore authored as adjacent blocks rather than folded:
                # folding bonus AD into total AD would apply it to base AD too
                # (an overstatement), and the reverse would understate badly.
                # Consequence: under the default block_strategy="first" only the
                # total-AD half is read, so Zaahen Q is CONSERVATIVE by its
                # 20-40 percent bonus-AD term. Never inflated.
                _dmg("Total Physical Damage",
                     base=_ramp(15, 75, 5),
                     total_ad_pct=_flat(100)),
                _dmg("Total Physical Damage Bonus AD Component",
                     bonus_ad_pct=_ramp(20, 40, 5)),
                # 15/2 = 7.5 to 75/2 = 37.5 (+ 100/2 = 50% AD)
                # (+ 20/2 = 10 to 40/2 = 20% bonus AD) - same split.
                _dmg("Physical Damage per Hit",
                     base=_ramp(7.5, 37.5, 5),
                     total_ad_pct=_flat(50)),
                _dmg("Physical Damage per Hit Bonus AD Component",
                     bonus_ad_pct=_ramp(10, 20, 5)),
                # Recast (leveling3): 25 to 125 (+ 20 to 40% bonus AD)
                _dmg("Bonus Physical Damage",
                     base=_ramp(25, 125, 5),
                     bonus_ad_pct=_ramp(20, 40, 5)),
                # Non-damage rows trail (see module docstring, convention 1).
                _block("Champion Healing", "heal",
                       caster_max_hp_pct=_ramp(5, 9, 5)),
                # 5*0.5 = 2.5 to 9*0.5 = 4.5
                _block("Non-Champion Healing", "heal",
                       caster_max_hp_pct=_ramp(2.5, 4.5, 5)),
            ],
            "raw_effects_count": 5,
            "raw_leveling_count": 5,
            "parse_status": "ok",
            "parse_notes": [
                "hand-authored from Template:Data Zaahen/The Darkin Glaive",
                "recast leveling3 flattened onto form 0 after the first-cast blocks",
                "total-AD and bonus-AD ratios split across adjacent blocks "
                "(no block may carry two AD-family fields)",
            ],
        }
    ],
    # Template:Data Zaahen/Dreaded Return (skill = W), fetched 2026-07-25.
    #   "|leveling     = {{st|Initial Physical Damage|{{ap|40 to 120}}
    #    {{as|(+ 50% '''bonus''' AD)}}}}
    #    {{st|Subsequent Physical Damage|{{ap|30 to 110}}
    #    {{as|(+ 30% '''bonus''' AD)}}}}
    #    {{st|Total Physical Damage|{{ap|40+30 to 120+110}}
    #    {{as|(+ {{ap|50+30}}% '''bonus''' AD)}}}}"
    #   "|cooldown = {{ap|14 to 12}}   |cost = 50   |damagetype = Physical"
    "W": [
        {
            "key": "W",
            "name": "Dreaded Return",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(14, 12, 5),
            "cost": _flat(50),
            "damage_type": "PHYSICAL",
            "targeting": "Direction",
            "affects": "Enemies",
            "resource": "MANA",
            # |spelleffects = spellaoe
            "is_aoe": True,
            "damage_blocks": [
                _dmg("Initial Physical Damage",
                     base=_ramp(40, 120, 5), bonus_ad_pct=_flat(50)),
                _dmg("Subsequent Physical Damage",
                     base=_ramp(30, 110, 5), bonus_ad_pct=_flat(30)),
                # 40+30 = 70 to 120+110 = 230 (+ 50+30 = 80% bonus AD)
                _dmg("Total Physical Damage",
                     base=_ramp(70, 230, 5), bonus_ad_pct=_flat(80)),
            ],
            "raw_effects_count": 1,
            "raw_leveling_count": 3,
            "parse_status": "ok",
            "parse_notes": ["hand-authored from Template:Data Zaahen/Dreaded Return"],
        }
    ],
    # Template:Data Zaahen/Aureate Rush (skill = E), fetched 2026-07-25.
    #   "|leveling     = {{st|Physical Damage|{{ap|40 to 120}}
    #    {{as|(+ 50% '''bonus''' AD)}}}}"
    #   "|leveling2    = {{st|Increased Physical Damage|{{ap|60 to 180}}
    #    {{as|(+ 75% '''bonus''' AD)}}}}
    #    {{st|Bonus Magic Damage|{{as|{{ap|4 to 6}}% of the target's
    #    '''maximum''' health}}}}"
    #   "|cooldown = {{ap|10 to 8}}   |cost = 40
    #    |damagetype   = Physical Magic"
    # damage_type: the page header is the compound "Physical Magic", but the
    # magic half is the OUTER-EDGE percent-max-HP block at index 2. Block 0 is
    # pure physical, so PHYSICAL is the correct single mitigation label -
    # MIXED would 50/50 split the physical block against MR.
    "E": [
        {
            "key": "E",
            "name": "Aureate Rush",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(10, 8, 5),
            "cost": _flat(40),
            "damage_type": "PHYSICAL",
            "targeting": "Location",
            "affects": "Self, Enemies",
            "resource": "MANA",
            # |spelleffects = spellaoe
            "is_aoe": True,
            "damage_blocks": [
                _dmg("Physical Damage",
                     base=_ramp(40, 120, 5), bonus_ad_pct=_flat(50)),
                _dmg("Increased Physical Damage",
                     base=_ramp(60, 180, 5), bonus_ad_pct=_flat(75)),
                _dmg("Bonus Magic Damage",
                     target_max_hp_pct=_ramp(4, 6, 5)),
            ],
            "raw_effects_count": 3,
            "raw_leveling_count": 3,
            "parse_status": "ok",
            "parse_notes": [
                "page |damagetype is the compound 'Physical Magic'",
                "the MAGIC half is the outer-edge percent-max-HP block",
            ],
        }
    ],
    # Template:Data Zaahen/Grim Deliverance (skill = R), fetched 2026-07-25.
    #   "|leveling     = {{st|Armor Penetration|{{ap|10 to 30}}%}}"
    #     (this row belongs to the R's PASSIVE half - the page's first
    #      |description is "{{sbc|Passive:}} '''Zaahen''' gains armor
    #      penetration", with |icon = false)
    #   "|leveling2    = {{st|Physical Damage|{{ap|250 to 550}}
    #    {{as|(+ 200% '''bonus''' AD)}}}}
    #    {{st|Healing per Champion hit|{{ap|250*0.33 to 550*0.33}}
    #    {{as|(+ {{ap|200*0.33}}% '''bonus''' AD)}}}}"
    #   "|cooldown = {{ap|110 to 80}}   |cost = 100
    #    |damagetype = Physical"
    # BLOCK ORDER: the damage block is authored FIRST even though the armor-pen
    # row precedes it on the page. ``_select_blocks`` reads index 0 without
    # checking attribute_kind, so an "Armor Penetration" row at index 0 would
    # be evaluated as 10-30 flat damage. See module docstring, convention 1.
    "R": [
        {
            "key": "R",
            "name": "Grim Deliverance",
            "form_index": 0,
            "icon": None,
            "cooldown": _ramp(110, 80, 3),
            "cost": _flat(100),
            "damage_type": "PHYSICAL",
            "targeting": "Location",
            "affects": "Self, Enemies",
            "resource": "MANA",
            # |spelleffects = spellaoe
            "is_aoe": True,
            "damage_blocks": [
                _dmg("Physical Damage",
                     base=_ramp(250, 550, 3), bonus_ad_pct=_flat(200)),
                # 250*0.33 = 82.5 to 550*0.33 = 181.5 (+ 200*0.33 = 66% bonus AD)
                _block("Healing per Champion hit", "heal",
                       base=_ramp(82.5, 181.5, 3), bonus_ad_pct=_flat(66)),
                _block("Armor Penetration", "modifier", base=_ramp(10, 30, 3)),
            ],
            "raw_effects_count": 3,
            "raw_leveling_count": 3,
            "parse_status": "ok",
            "parse_notes": [
                "hand-authored from Template:Data Zaahen/Grim Deliverance",
                "R passive armor-pen row moved behind the active damage block",
            ],
        }
    ],
}


# champion_id -> {ability key: [form payload, ...]}, in exactly the shape of
# ``champion_abilities.json``'s ``data[<champion>]`` container, so
# ``AbilitiesSnapshot.load`` builds these through the SAME
# ``AbilityForm.from_dict`` path (and the same override / CDragon hooks) as
# every Meraki champion. Nothing bypasses the loader.
WIKI_ABILITY_DAMAGE_CHAMPIONS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "Locke": _LOCKE,
    "Zaahen": _ZAAHEN,
}


def iter_injectable_champions() -> Iterator[tuple[str, dict[str, list[dict[str, Any]]]]]:
    """Yield ``(champion_id, keymap)`` for every hand-authored champion.

    The caller (``AbilitiesSnapshot.load``) is responsible for the
    keys-not-present-only rule - see ``inject_missing_champions``.
    """
    yield from WIKI_ABILITY_DAMAGE_CHAMPIONS.items()


def inject_missing_champions(data_block: dict[str, Any]) -> tuple[str, ...]:
    """Add every registry champion ABSENT from ``data_block``, in place.

    KEYS-NOT-PRESENT-ONLY: a champion already in ``data_block`` is never
    touched, so a future Meraki re-extract that ships Locke / Zaahen makes this
    registry silently inert with no code change, and the 171 champions the
    snapshot already carries are provably byte-identical (see
    ``tests/test_ability_wiki_damage_locke_zaahen.py``).

    Returns the tuple of champion ids actually injected (sorted) so the caller
    can log / assert on it.
    """
    added: list[str] = []
    for cid, keymap in iter_injectable_champions():
        if cid in data_block:
            continue
        data_block[cid] = {key: list(forms) for key, forms in keymap.items()}
        added.append(cid)
    return tuple(sorted(added))
