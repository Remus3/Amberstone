"""Offensive crowd-control OUTPUT (lockdown) scorer (ENGINE 1.106.0, item 294).

The mirror of the survivability CC axes (item 290 champion-innate CC-mitigation /
item 292 spell-shield), pointed the other way: those score how much enemy CC a
champion SURVIVES; this scores how much CC a champion APPLIES to enemies - her
lockdown contribution as a first-class offensive-utility metric, the seventh
scored axis alongside DPS / burst / EHP / ability-DPS / healing-throughput / the
six archetype scorers.

The per-spell CC DURATION substrate already exists (``_PER_SPELL_CC_DURATIONS``
in ``_per_spell_cc.py``, consumed defensively by ``cc_pressure``). Durations
alone do not encode lockdown VALUE - a 1.5s suppression and a 1.5s slow are not
worth the same to a team fight. This module adds the missing schema: a
hand-authored per-(champion, spell) CC-KIND registry plus a kind -> weight table
that converts weighted CC-seconds into a single ``lockdown_score``.

Purely ADDITIVE: a new standalone scorer and a new ``/cc-output`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Flipping it into a
live coach surface (the auto-pairing consumer that credits a champion's lockdown
into a team-fight verdict) is the separate Phase-D step.

Schema (mirrors the AbilitySpellDps / CcSpellEntry surface):
  * ``CcOutputEntry`` - one registry row: spell_key, cc_kind, max-rank duration,
    conditional flag. ``conditional=True`` means the CC fires only on a gate
    (terrain hit, nth stack, target-state, full charge, tether expiry) and is
    credited at the operator-tunable ``_CC_OUTPUT_CONDITIONAL_PROB`` midpoint.
  * ``CcOutputSpellEntry`` - one scored spell: duration, kind weight, weighted
    seconds (= duration * weight, times the conditional midpoint when gated).
  * ``CcOutputResult`` - the aggregate: ``lockdown_score`` (unconditional weighted
    seconds), ``conditional_lockdown_score`` (gated weighted seconds at the
    midpoint), ``total_lockdown_score`` (their sum), and ``total_cc_seconds`` (raw
    unweighted unconditional seconds, the cc_pressure-comparable quantity).

CC durations are sourced verbatim from ``_PER_SPELL_CC_DURATIONS`` wherever that
registry already carries the spell (no second source of truth); the kinds and any
durations that registry deliberately excluded (slows, conditional CC) are
hand-authored from the verbatim patch-16.11 ability prose by the item-294 roster
fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SPELL_ORDER = ("P", "Q", "W", "E", "R")

# CC-kind -> lockdown weight. Hand-authored, operator-tunable. Four tiers:
#   1.00 hard disable - target cannot act at all (move / attack / cast / blink)
#   0.60 action-restricting - target keeps SOME agency (root can still cast +
#        attack; silence can still move + attack; ground blocks only blinks)
#   0.50 displacement - a brief forced reposition (knock-up duration is the hard
#        AIRBORNE tier; a knock-aside / pull is shorter and partial)
#   0.20 soft - slows / blinds-of-sight that only degrade, never deny
_CC_KIND_WEIGHT: dict[str, float] = {
    "SUPPRESSION": 1.0,
    "STUN": 1.0,
    "AIRBORNE": 1.0,
    "CHARM": 1.0,
    "FEAR": 1.0,
    "TAUNT": 1.0,
    "SLEEP": 1.0,
    "STASIS": 1.0,
    "POLYMORPH": 1.0,
    "ROOT": 0.6,
    "SILENCE": 0.6,
    "GROUND": 0.6,
    "DISARM": 0.6,
    "BLIND": 0.6,
    "KNOCKBACK": 0.5,
    "PULL": 0.5,
    "SLOW": 0.2,
    "NEARSIGHT": 0.2,
    "CRIPPLE": 0.2,
}

# A gated (conditional) CC fires only some of the time - it is credited at this
# availability midpoint, the same shape as cc_conditional's probability weight.
_CC_OUTPUT_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class CcOutputEntry:
    """One registry row: a champion spell that applies CC to enemies.

    ``spell`` is one of ``{"P","Q","W","E","R"}``. ``cc_kind`` is a key of
    ``_CC_KIND_WEIGHT``. ``duration_s`` is the max-rank CC duration in seconds
    (reused verbatim from ``_PER_SPELL_CC_DURATIONS`` when that registry carries
    the spell, else hand-authored from the patch-16.11 prose). ``conditional``
    is True when the CC only fires on a gate.
    """

    spell: str
    cc_kind: str
    duration_s: float
    conditional: bool = False


def _build_cc_output_registry() -> dict[str, tuple[CcOutputEntry, ...]]:
    """Build champion_id -> tuple[CcOutputEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several CC spells without dict-literal collision (the same builder pattern
    the per-spell CC duration registry adopted at ENGINE 1.36.0). Runs ONCE at
    import; the result is assigned to ``_CC_OUTPUT_REGISTRY`` below.
    """
    raw: dict[str, list[CcOutputEntry]] = {}

    def add(
        champ: str, spell: str, kind: str, dur: float, cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            CcOutputEntry(spell, kind, float(dur), bool(cond))
        )

    # ===== INJECTED ENTRIES (item 294, 12-agent roster fan-out) =====
    # Aatrox
    add("Aatrox", "Q", "AIRBORNE", 0.25, True)
    add("Aatrox", "W", "PULL", 1.5, True)
    # Ahri
    add("Ahri", "E", "CHARM", 2.0)
    # Akali
    add("Akali", "Q", "SLOW", 0.5)
    # Alistar
    add("Alistar", "Q", "AIRBORNE", 1.0)
    add("Alistar", "W", "STUN", 0.5)
    add("Alistar", "E", "STUN", 1.0, True)
    # Ambessa
    add("Ambessa", "E", "SLOW", 1.0)
    add("Ambessa", "R", "SUPPRESSION", 0.75)
    # Amumu
    add("Amumu", "Q", "STUN", 1.4)
    add("Amumu", "R", "STUN", 2.0)
    # Anivia
    add("Anivia", "Q", "STUN", 1.25, True)
    add("Anivia", "W", "KNOCKBACK", 0.5)
    add("Anivia", "R", "SLOW", 1.5)
    # Annie
    add("Annie", "Q", "STUN", 1.75, True)
    add("Annie", "W", "STUN", 1.75, True)
    add("Annie", "R", "STUN", 1.5, True)
    # Aphelios
    add("Aphelios", "P", "SLOW", 2.5)
    add("Aphelios", "Q", "ROOT", 1.0, True)
    # Ashe
    add("Ashe", "P", "SLOW", 2.0)
    add("Ashe", "W", "SLOW", 2.0)
    add("Ashe", "R", "STUN", 1.5)
    # AurelionSol
    add("AurelionSol", "E", "PULL", 5.0)
    add("AurelionSol", "R", "STUN", 1.75)
    # Aurora
    add("Aurora", "E", "SLOW", 1.0)
    add("Aurora", "R", "SLOW", 2.0)
    # Azir
    add("Azir", "Q", "SLOW", 1.0)
    add("Azir", "R", "KNOCKBACK", 1.0)
    # Bard
    add("Bard", "P", "SLOW", 1.0, True)
    add("Bard", "Q", "STUN", 1.8, True)
    add("Bard", "R", "STASIS", 2.5)
    # Belveth
    add("Belveth", "W", "AIRBORNE", 0.75)
    # Blitzcrank
    add("Blitzcrank", "Q", "STUN", 1.0)
    add("Blitzcrank", "E", "AIRBORNE", 1.0)
    add("Blitzcrank", "R", "SILENCE", 0.5)
    # Brand
    add("Brand", "Q", "STUN", 1.5, True)
    add("Brand", "R", "SLOW", 0.25, True)
    # Braum
    add("Braum", "P", "STUN", 1.75)
    add("Braum", "Q", "SLOW", 2.0)
    add("Braum", "R", "AIRBORNE", 1.0)
    # Briar
    add("Briar", "Q", "STUN", 0.85)
    add("Briar", "E", "STUN", 1.5, True)
    add("Briar", "R", "FEAR", 1.5)
    # Caitlyn
    add("Caitlyn", "W", "ROOT", 1.5, True)
    add("Caitlyn", "E", "SLOW", 1.0)
    # Camille
    add("Camille", "W", "SLOW", 2.0)
    add("Camille", "E", "STUN", 0.75, True)
    add("Camille", "R", "KNOCKBACK", 0.5)
    # Cassiopeia
    add("Cassiopeia", "W", "GROUND", 5.0)
    add("Cassiopeia", "R", "STUN", 2.0, True)
    # Chogath
    add("Chogath", "Q", "AIRBORNE", 1.0)
    add("Chogath", "W", "SILENCE", 2.0)
    add("Chogath", "E", "SLOW", 1.5)
    # Darius
    add("Darius", "W", "SLOW", 1.0)
    add("Darius", "E", "AIRBORNE", 1.0)
    # Diana
    add("Diana", "R", "PULL", 0.75)
    # DrMundo
    add("DrMundo", "Q", "SLOW", 2.0)
    # Draven
    add("Draven", "E", "KNOCKBACK", 0.5)
    # Ekko
    add("Ekko", "Q", "SLOW", 1.75)
    add("Ekko", "W", "STUN", 2.25, True)
    # Elise
    add("Elise", "E", "STUN", 2.3)
    # Evelynn
    add("Evelynn", "W", "CHARM", 2.25, True)
    # Fiddlesticks
    add("Fiddlesticks", "Q", "FEAR", 2.25)
    # Fiora
    add("Fiora", "W", "STUN", 2.0, True)
    # Fizz
    add("Fizz", "E", "SLOW", 2.0)
    add("Fizz", "R", "AIRBORNE", 1.0, True)
    # Galio
    add("Galio", "W", "TAUNT", 1.0)
    add("Galio", "E", "AIRBORNE", 0.5)
    add("Galio", "R", "AIRBORNE", 0.75)
    # Gangplank
    add("Gangplank", "E", "SLOW", 2.0)
    add("Gangplank", "R", "SLOW", 0.5)
    # Garen
    add("Garen", "Q", "SILENCE", 1.5)
    # Gnar
    add("Gnar", "Q", "SLOW", 2.0)
    add("Gnar", "W", "STUN", 1.25)
    add("Gnar", "E", "SLOW", 0.5, True)
    add("Gnar", "R", "KNOCKBACK", 0.75)
    # Gragas
    add("Gragas", "Q", "SLOW", 2.0)
    add("Gragas", "E", "STUN", 1.0)
    add("Gragas", "R", "KNOCKBACK", 0.25)
    # Graves
    add("Graves", "W", "NEARSIGHT", 4.0)
    # Gwen
    add("Gwen", "R", "SLOW", 1.5)
    # Hecarim
    add("Hecarim", "E", "KNOCKBACK", 0.75)
    add("Hecarim", "R", "FEAR", 1.0)
    # Heimerdinger
    add("Heimerdinger", "E", "STUN", 1.25, True)
    # Hwei
    add("Hwei", "E", "AIRBORNE", 1.5)
    # Illaoi
    add("Illaoi", "E", "SLOW", 1.5, True)
    # Irelia
    add("Irelia", "E", "STUN", 1.15)
    add("Irelia", "R", "KNOCKBACK", 0.5)
    # Ivern
    add("Ivern", "Q", "ROOT", 2.0)
    add("Ivern", "E", "SLOW", 2.0)
    # Janna
    add("Janna", "Q", "AIRBORNE", 1.0)
    add("Janna", "W", "SLOW", 2.0)
    add("Janna", "R", "KNOCKBACK", 0.5)
    # JarvanIV
    add("JarvanIV", "Q", "AIRBORNE", 0.75, True)
    add("JarvanIV", "W", "SLOW", 2.0)
    add("JarvanIV", "R", "KNOCKBACK", 0.15)
    # Jax
    add("Jax", "E", "STUN", 1.0)
    # Jayce
    add("Jayce", "Q", "SLOW", 2.0)
    add("Jayce", "E", "KNOCKBACK", 0.5)
    # Jhin
    add("Jhin", "W", "ROOT", 1.75, True)
    add("Jhin", "E", "SLOW", 2.0)
    add("Jhin", "R", "SLOW", 0.5)
    # Jinx
    add("Jinx", "W", "SLOW", 2.0)
    add("Jinx", "E", "ROOT", 1.5)
    # KSante
    add("KSante", "Q", "STUN", 0.8, True)
    add("KSante", "W", "STUN", 1.75)
    add("KSante", "R", "KNOCKBACK", 0.75)
    # Kalista
    add("Kalista", "E", "SLOW", 2.0)
    add("Kalista", "R", "AIRBORNE", 1.0)
    # Karma
    add("Karma", "Q", "SLOW", 1.5)
    add("Karma", "W", "ROOT", 2.0, True)
    # Karthus
    add("Karthus", "W", "SLOW", 5.0)
    # Kassadin
    add("Kassadin", "E", "SLOW", 1.0)
    # Kayle
    add("Kayle", "Q", "SLOW", 2.0)
    # Kayn
    add("Kayn", "W", "AIRBORNE", 1.0, True)
    # Kennen
    add("Kennen", "P", "STUN", 1.25, True)
    # Khazix
    add("Khazix", "P", "SLOW", 2.0, True)
    add("Khazix", "W", "SLOW", 2.0, True)
    # Kindred
    add("Kindred", "E", "SLOW", 1.0)
    # Kled
    add("Kled", "Q", "PULL", 2.5, True)
    add("Kled", "R", "KNOCKBACK", 0.5)
    # KogMaw
    add("KogMaw", "E", "SLOW", 3.0)
    # Leblanc
    add("Leblanc", "E", "ROOT", 1.5, True)
    # LeeSin
    add("LeeSin", "E", "SLOW", 4.0, True)
    add("LeeSin", "R", "AIRBORNE", 1.0)
    # Leona
    add("Leona", "Q", "STUN", 1.25)
    add("Leona", "E", "ROOT", 0.5)
    add("Leona", "R", "STUN", 1.5)
    # Lillia
    add("Lillia", "E", "SLOW", 3.0)
    add("Lillia", "R", "SLEEP", 2.0, True)
    # Lissandra
    add("Lissandra", "Q", "SLOW", 1.5)
    add("Lissandra", "W", "ROOT", 1.65)
    add("Lissandra", "R", "STUN", 1.5)
    # Lulu
    add("Lulu", "Q", "SLOW", 2.0)
    add("Lulu", "W", "POLYMORPH", 2.25)
    add("Lulu", "R", "AIRBORNE", 1.0)
    # Lux
    add("Lux", "Q", "ROOT", 3.0)
    add("Lux", "E", "SLOW", 1.0)
    # Malphite
    add("Malphite", "Q", "SLOW", 3.0)
    add("Malphite", "E", "CRIPPLE", 3.0)
    add("Malphite", "R", "AIRBORNE", 2.0)
    # Malzahar
    add("Malzahar", "Q", "SILENCE", 2.0)
    add("Malzahar", "R", "SUPPRESSION", 2.5)
    # Maokai
    add("Maokai", "Q", "STUN", 0.5, True)
    add("Maokai", "W", "ROOT", 1.4)
    add("Maokai", "E", "SLOW", 2.0)
    add("Maokai", "R", "ROOT", 2.0)
    # Mel
    add("Mel", "E", "ROOT", 2.25)
    # Milio
    add("Milio", "Q", "STUN", 1.0)
    # MissFortune
    add("MissFortune", "E", "SLOW", 2.0)
    # MonkeyKing
    add("MonkeyKing", "R", "AIRBORNE", 1.0)
    # Mordekaiser
    add("Mordekaiser", "E", "PULL", 0.25)
    add("Mordekaiser", "R", "STASIS", 7.0)
    # Morgana
    add("Morgana", "Q", "ROOT", 3.0)
    add("Morgana", "R", "STUN", 2.0, True)
    # Naafiri
    add("Naafiri", "R", "SLOW", 0.25)
    # Nami
    add("Nami", "Q", "AIRBORNE", 1.5)
    add("Nami", "R", "AIRBORNE", 0.5)
    # Nasus
    add("Nasus", "W", "CRIPPLE", 5.0)
    # Nautilus
    add("Nautilus", "P", "ROOT", 1.5)
    add("Nautilus", "Q", "STUN", 1.6)
    add("Nautilus", "E", "SLOW", 1.5)
    add("Nautilus", "R", "AIRBORNE", 2.0)
    # Neeko
    add("Neeko", "E", "ROOT", 1.75)
    add("Neeko", "R", "STUN", 1.25)
    # Nilah
    add("Nilah", "R", "PULL", 3.0)
    # Nocturne
    add("Nocturne", "E", "FEAR", 2.25, True)
    add("Nocturne", "R", "NEARSIGHT", 6.0)
    # Nunu
    add("Nunu", "W", "AIRBORNE", 0.75, True)
    add("Nunu", "E", "ROOT", 1.5, True)
    add("Nunu", "R", "SLOW", 3.0)
    # Olaf
    add("Olaf", "Q", "SLOW", 2.5)
    # Orianna
    add("Orianna", "W", "SLOW", 2.0)
    add("Orianna", "R", "AIRBORNE", 1.0)
    # Ornn
    add("Ornn", "Q", "KNOCKBACK", 2.0)
    add("Ornn", "E", "STUN", 1.25, True)
    add("Ornn", "R", "AIRBORNE", 0.5)
    # Pantheon
    add("Pantheon", "W", "STUN", 1.0)
    add("Pantheon", "R", "SLOW", 2.0)
    # Poppy
    add("Poppy", "Q", "SLOW", 1.0)
    add("Poppy", "E", "STUN", 0.5, True)
    add("Poppy", "R", "AIRBORNE", 1.0)
    # Pyke
    add("Pyke", "Q", "PULL", 1.25)
    add("Pyke", "E", "STUN", 1.25)
    # Qiyana
    add("Qiyana", "Q", "ROOT", 0.5, True)
    add("Qiyana", "R", "KNOCKBACK", 1.0)
    # Quinn
    add("Quinn", "Q", "NEARSIGHT", 1.75)
    add("Quinn", "E", "KNOCKBACK", 0.75)
    # Rakan
    add("Rakan", "W", "AIRBORNE", 1.0)
    add("Rakan", "R", "CHARM", 1.5)
    # Rammus
    add("Rammus", "Q", "STUN", 0.4)
    add("Rammus", "E", "TAUNT", 2.0)
    add("Rammus", "R", "AIRBORNE", 0.75, True)
    # RekSai
    add("RekSai", "W", "AIRBORNE", 1.0)
    # Rell
    add("Rell", "Q", "STUN", 1.0)
    add("Rell", "W", "STUN", 0.8)
    add("Rell", "R", "PULL", 2.0)
    # Renata
    add("Renata", "Q", "ROOT", 1.0)
    add("Renata", "E", "SLOW", 2.0)
    add("Renata", "R", "CHARM", 2.25)
    # Renekton
    add("Renekton", "W", "STUN", 0.75)
    # Rengar
    add("Rengar", "E", "ROOT", 1.75, True)
    # Riven
    add("Riven", "Q", "KNOCKBACK", 0.5, True)
    add("Riven", "W", "STUN", 0.75)
    # Rumble
    add("Rumble", "E", "SLOW", 2.0)
    add("Rumble", "R", "SLOW", 4.5)
    # Ryze
    add("Ryze", "W", "ROOT", 1.75, True)
    # Sejuani
    add("Sejuani", "Q", "AIRBORNE", 1.25)
    add("Sejuani", "W", "SLOW", 0.25)
    add("Sejuani", "E", "STUN", 1.0, True)
    add("Sejuani", "R", "STUN", 2.0)
    # Senna
    add("Senna", "Q", "SLOW", 2.0)
    add("Senna", "W", "ROOT", 2.25)
    # Seraphine
    add("Seraphine", "E", "STUN", 1.5, True)
    add("Seraphine", "R", "CHARM", 1.75)
    # Sett
    add("Sett", "E", "STUN", 1.0, True)
    add("Sett", "R", "SUPPRESSION", 1.5)
    # Shaco
    add("Shaco", "W", "FEAR", 1.5)
    add("Shaco", "E", "SLOW", 3.0)
    # Shen
    add("Shen", "Q", "SLOW", 2.0, True)
    add("Shen", "E", "TAUNT", 1.5)
    # Shyvana
    add("Shyvana", "R", "KNOCKBACK", 1.0)
    # Singed
    add("Singed", "W", "GROUND", 3.0)
    add("Singed", "E", "KNOCKBACK", 1.0)
    # Sion
    add("Sion", "Q", "STUN", 2.25, True)
    add("Sion", "E", "SLOW", 2.5)
    add("Sion", "R", "STUN", 1.75, True)
    # Skarner
    add("Skarner", "Q", "SLOW", 1.0)
    add("Skarner", "W", "SLOW", 1.0)
    add("Skarner", "R", "SUPPRESSION", 2.25)
    # Smolder
    add("Smolder", "W", "SLOW", 1.5)
    add("Smolder", "R", "AIRBORNE", 1.25)
    # Sona
    add("Sona", "R", "STUN", 1.5)
    # Soraka
    add("Soraka", "Q", "SLOW", 1.5)
    add("Soraka", "E", "ROOT", 2.0)
    # Swain
    add("Swain", "W", "SLOW", 1.5)
    add("Swain", "E", "ROOT", 1.5)
    add("Swain", "R", "SLOW", 1.5)
    # Sylas
    add("Sylas", "Q", "SLOW", 1.5)
    add("Sylas", "E", "AIRBORNE", 0.5)
    # Syndra
    add("Syndra", "W", "SLOW", 1.5)
    add("Syndra", "E", "KNOCKBACK", 0.5)
    # TahmKench
    add("TahmKench", "Q", "STUN", 1.5, True)
    add("TahmKench", "R", "SUPPRESSION", 3.0, True)
    # Taliyah
    add("Taliyah", "Q", "SLOW", 1.5, True)
    add("Taliyah", "W", "AIRBORNE", 1.0)
    add("Taliyah", "E", "STUN", 0.75, True)
    add("Taliyah", "R", "KNOCKBACK", 0.5)
    # Talon
    add("Talon", "W", "SLOW", 1.0)
    # Taric
    add("Taric", "E", "STUN", 1.5)
    # Teemo
    add("Teemo", "Q", "BLIND", 3.0)
    add("Teemo", "R", "SLOW", 4.0)
    # Thresh
    add("Thresh", "Q", "STUN", 1.5)
    add("Thresh", "E", "KNOCKBACK", 0.4)
    add("Thresh", "R", "SLOW", 2.0)
    # Tristana
    add("Tristana", "W", "SLOW", 2.0)
    add("Tristana", "R", "KNOCKBACK", 1.0)
    # Trundle
    add("Trundle", "Q", "SLOW", 0.1)
    add("Trundle", "E", "KNOCKBACK", 0.5)
    # Tryndamere
    add("Tryndamere", "W", "SLOW", 4.0, True)
    # TwistedFate
    add("TwistedFate", "W", "STUN", 2.0, True)
    # Twitch
    add("Twitch", "W", "SLOW", 3.0)
    # Udyr
    add("Udyr", "E", "STUN", 0.75)
    add("Udyr", "R", "SLOW", 4.0)
    # Urgot
    add("Urgot", "Q", "SLOW", 1.25)
    add("Urgot", "E", "STUN", 0.5)
    add("Urgot", "R", "SUPPRESSION", 1.5, True)
    # Varus
    add("Varus", "E", "SLOW", 4.0)
    add("Varus", "R", "ROOT", 2.0)
    # Vayne
    add("Vayne", "E", "KNOCKBACK", 0.5)
    # Veigar
    add("Veigar", "E", "STUN", 1.5)
    # Velkoz
    add("Velkoz", "Q", "SLOW", 2.6)
    add("Velkoz", "E", "AIRBORNE", 0.75)
    add("Velkoz", "R", "SLOW", 1.0)
    # Vex
    add("Vex", "P", "FEAR", 1.5)
    add("Vex", "E", "SLOW", 2.0)
    # Vi
    add("Vi", "Q", "KNOCKBACK", 0.75)
    add("Vi", "R", "AIRBORNE", 1.0)
    # Viego
    add("Viego", "W", "STUN", 1.5, True)
    add("Viego", "R", "KNOCKBACK", 0.75)
    # Viktor
    add("Viktor", "W", "STUN", 1.5, True)
    # Vladimir
    add("Vladimir", "W", "SLOW", 2.0)
    # Volibear
    add("Volibear", "Q", "STUN", 1.0)
    add("Volibear", "E", "AIRBORNE", 0.25)
    add("Volibear", "R", "SLOW", 1.0)
    # Warwick
    add("Warwick", "E", "FEAR", 1.0, True)
    add("Warwick", "R", "SUPPRESSION", 1.5)
    # Xayah
    add("Xayah", "E", "ROOT", 1.25, True)
    # Xerath
    add("Xerath", "W", "SLOW", 2.5)
    add("Xerath", "E", "STUN", 2.0)
    # XinZhao
    add("XinZhao", "Q", "AIRBORNE", 0.75, True)
    add("XinZhao", "W", "AIRBORNE", 1.0)
    add("XinZhao", "E", "SLOW", 0.5)
    add("XinZhao", "R", "STUN", 0.75, True)
    # Yasuo
    add("Yasuo", "Q", "AIRBORNE", 0.75, True)
    add("Yasuo", "R", "AIRBORNE", 1.0)
    # Yone
    add("Yone", "Q", "AIRBORNE", 0.75, True)
    add("Yone", "R", "AIRBORNE", 0.75)
    # Yorick
    add("Yorick", "W", "KNOCKBACK", 0.25)
    add("Yorick", "E", "SLOW", 1.5)
    # Yunara
    add("Yunara", "W", "SLOW", 1.5)
    # Yuumi
    add("Yuumi", "Q", "SLOW", 2.0)
    add("Yuumi", "R", "SLOW", 1.25)
    # Zac
    add("Zac", "Q", "ROOT", 0.5, True)
    add("Zac", "E", "AIRBORNE", 1.0)
    add("Zac", "R", "KNOCKBACK", 1.0)
    # Zed
    add("Zed", "E", "SLOW", 1.5, True)
    # Zeri
    add("Zeri", "W", "SLOW", 2.0)
    # Ziggs
    add("Ziggs", "W", "KNOCKBACK", 0.5)
    add("Ziggs", "E", "SLOW", 1.5)
    # Zilean
    add("Zilean", "Q", "STUN", 1.5, True)
    add("Zilean", "E", "SLOW", 2.5)
    # Zoe
    add("Zoe", "E", "SLEEP", 2.0)
    # Zyra
    add("Zyra", "E", "ROOT", 2.0)
    add("Zyra", "R", "AIRBORNE", 1.0)
    # ===== END INJECTED ENTRIES =====

    return {champ: tuple(entries) for champ, entries in raw.items()}


_CC_OUTPUT_REGISTRY: dict[str, tuple[CcOutputEntry, ...]] = (
    _build_cc_output_registry()
)


@dataclass(frozen=True)
class CcOutputSpellEntry:
    """One scored CC spell for a champion.

    ``weighted_seconds`` = ``duration_s * kind_weight`` for an unconditional
    entry, times ``_CC_OUTPUT_CONDITIONAL_PROB`` when ``conditional`` is True.
    """

    spell_key: str
    cc_kind: str
    duration_s: float
    kind_weight: float
    conditional: bool
    weighted_seconds: float

    def to_dict(self) -> dict:
        return {
            "spell_key": self.spell_key,
            "cc_kind": self.cc_kind,
            "duration_s": round(self.duration_s, 4),
            "kind_weight": self.kind_weight,
            "conditional": self.conditional,
            "weighted_seconds": round(self.weighted_seconds, 4),
        }


@dataclass(frozen=True)
class CcOutputResult:
    """Aggregate offensive CC-output (lockdown) for one champion.

    ``lockdown_score`` sums ``weighted_seconds`` over the UNCONDITIONAL spells;
    ``conditional_lockdown_score`` sums them over the gated spells (already
    discounted by the availability midpoint); ``total_lockdown_score`` is their
    sum. ``total_cc_seconds`` is the raw unweighted unconditional duration sum,
    directly comparable to ``cc_pressure.CcPressureResult.total_cc_seconds``.
    Returns all-zero with an empty ``spells`` tuple for an unregistered or blank
    champion (never raises).
    """

    champion: str
    mode: str
    lockdown_score: float
    conditional_lockdown_score: float
    total_lockdown_score: float
    total_cc_seconds: float
    spells: tuple[CcOutputSpellEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "lockdown_score": round(self.lockdown_score, 4),
            "conditional_lockdown_score": round(
                self.conditional_lockdown_score, 4
            ),
            "total_lockdown_score": round(self.total_lockdown_score, 4),
            "total_cc_seconds": round(self.total_cc_seconds, 4),
            "spells": [s.to_dict() for s in self.spells],
        }


def _empty_result(champion: str, mode: str) -> CcOutputResult:
    return CcOutputResult(
        champion=champion,
        mode=mode,
        lockdown_score=0.0,
        conditional_lockdown_score=0.0,
        total_lockdown_score=0.0,
        total_cc_seconds=0.0,
        spells=(),
    )


def _spell_sort_key(entry: CcOutputEntry) -> tuple[int, str]:
    try:
        return (_SPELL_ORDER.index(entry.spell), entry.spell)
    except ValueError:
        return (len(_SPELL_ORDER), entry.spell)


def compute_cc_output(champion: str, mode: str = "SR") -> CcOutputResult:
    """Aggregate a champion's offensive CC output into a lockdown score.

    Reads ``_CC_OUTPUT_REGISTRY``. For each registered enemy-CC spell the
    per-kind weight (``_CC_KIND_WEIGHT``) converts the max-rank duration into
    weighted CC-seconds; conditional spells are discounted by
    ``_CC_OUTPUT_CONDITIONAL_PROB``. ``mode`` is carried on the result for
    parity with the other scorers but does not change output today (offensive
    output is target-independent; the enemy's tenacity is not known here).

    Returns an all-zero ``CcOutputResult`` (empty ``spells``) when the champion
    is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _CC_OUTPUT_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[CcOutputSpellEntry] = []
    lockdown = 0.0
    conditional_lockdown = 0.0
    raw_uncond_seconds = 0.0
    for entry in sorted(entries, key=_spell_sort_key):
        weight = _CC_KIND_WEIGHT.get(entry.cc_kind, 0.0)
        base_weighted = entry.duration_s * weight
        if entry.conditional:
            weighted = base_weighted * _CC_OUTPUT_CONDITIONAL_PROB
            conditional_lockdown += weighted
        else:
            weighted = base_weighted
            lockdown += weighted
            raw_uncond_seconds += entry.duration_s
        scored.append(
            CcOutputSpellEntry(
                spell_key=entry.spell,
                cc_kind=entry.cc_kind,
                duration_s=entry.duration_s,
                kind_weight=weight,
                conditional=entry.conditional,
                weighted_seconds=weighted,
            )
        )

    return CcOutputResult(
        champion=champion,
        mode=safe_mode,
        lockdown_score=lockdown,
        conditional_lockdown_score=conditional_lockdown,
        total_lockdown_score=lockdown + conditional_lockdown,
        total_cc_seconds=raw_uncond_seconds,
        spells=tuple(scored),
    )


__all__ = [
    "CcOutputEntry",
    "CcOutputResult",
    "CcOutputSpellEntry",
    "compute_cc_output",
    "_CC_KIND_WEIGHT",
    "_CC_OUTPUT_CONDITIONAL_PROB",
    "_CC_OUTPUT_REGISTRY",
]
