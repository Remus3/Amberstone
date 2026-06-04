"""Mobility / gap-close / kiting scorer (ENGINE 1.109.0, item 297).

The eighth scored axis alongside DPS / burst / EHP / ability-DPS /
healing-throughput / offensive CC-output (item 294) / the six archetype
scorers. It quantifies how much a champion can REPOSITION her own body -
the dashes, blinks, leaps, movement-speed steroids and brief untargetable
hops that decide gap-close, kiting and disengage - into a single
``mobility_score``.

There is no existing self-mobility metric (``geometry.py`` is ability hitbox
math, ``missile.py`` is projectile travel-time); this module adds the missing
schema: a hand-authored per-(champion, spell) mobility registry plus a kind ->
weight table, normalised to a common unit where ``1.0`` mobility-unit is one
Flash (``_FLASH_UNITS`` = 400 units of instant repositioning).

Purely ADDITIVE: a new standalone scorer and a new ``/mobility`` route. It reads
no existing scorer and is read by none, so every existing route is byte-identical
(the opt-in is the new endpoint itself - inert until a caller invokes it, the
section-5 "default inert" contract for a brand-new surface). Wiring it into a
live draft / disengage / kite-threat coach surface is the separate Phase-D step.

Normalisation (everything reduces to Flash-units of repositioning):
  * displacement kinds (BLINK / DASH / LEAP / UNTARGET_REPOSITION) -
    ``mobility_units = (range_units / _FLASH_UNITS) * charges``; a 400-unit dash
    is 1.0, a multi-charge dash multiplies by its cast count.
  * MS_STEROID - ``mobility_units = ms_pct * _BASE_MS * duration_s / _FLASH_UNITS``
    (the extra distance covered during the speed buff, Flash-normalised); a
    sustained / toggle buff with no fixed window (``duration_s`` left at 0) is
    credited over ``_MS_SUSTAINED_WINDOW_S``.

Schema (mirrors the CcOutput surface):
  * ``MobilityEntry`` - one registry row: spell_key, kind, the raw magnitude
    (``range_units`` for displacement kinds, ``ms_pct`` + ``duration_s`` for a
    speed steroid), ``charges``, and a ``conditional`` flag. ``conditional=True``
    means the move only fires on a gate (needs an enemy/minion to dash to,
    terrain-only, reset-on-takedown, full-charge, tether) and is credited at the
    operator-tunable ``_MOBILITY_CONDITIONAL_PROB`` midpoint.
  * ``MobilitySpellEntry`` - one scored spell: normalised units, kind weight,
    weighted units (= units * weight, times the conditional midpoint when gated).
  * ``MobilityResult`` - the aggregate: ``mobility_score`` (unconditional
    weighted units), ``conditional_mobility_score`` (gated weighted units at the
    midpoint), ``total_mobility_score`` (their sum), and ``raw_mobility_units``
    (unweighted unconditional units, the kind-agnostic comparable quantity).

Magnitudes and kinds are hand-authored from the verbatim patch-16.11 ability
prose by the item-297 ten-channel roster fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_SPELL_ORDER = ("P", "Q", "W", "E", "R")

# Mobility-kind -> weight. Hand-authored, operator-tunable. Five tiers by
# reliability of the repositioning:
#   1.00 BLINK   - instant, no travel time, crosses any terrain (highest)
#   0.80 DASH    - fast fixed-path ground dash, interruptible, many cross walls
#   0.80 LEAP    - target/terrain-anchored jump (same reliability as a dash)
#   0.70 UNTARGET_REPOSITION - brief untargetable hop, repositions AND dodges
#   0.50 MS_STEROID - a speed buff: great chase/kite, telegraphed, no wall-cross
_MOBILITY_KIND_WEIGHT: dict[str, float] = {
    "BLINK": 1.0,
    "DASH": 0.8,
    "LEAP": 0.8,
    "UNTARGET_REPOSITION": 0.7,
    "MS_STEROID": 0.5,
}

# 1.0 mobility-unit = one Flash (400 units of instant displacement).
_FLASH_UNITS = 400.0
# Per-displacement saturation: range beyond ~one screen is strategic map
# mobility (global teleports - TwistedFate R, Shen R, Pantheon R), not fight
# gap-close / kiting, so a single dash/blink/leap is capped here before
# normalisation. Keeps a 25000-unit global from dwarfing the whole axis.
_MAX_DASH_UNITS = 1500.0
# Reference base movement speed for the MS_STEROID -> distance conversion.
_BASE_MS = 330.0
# A sustained / toggle MS buff (Quinn R, MissFortune Strut, Warwick W) carries
# no fixed decay window; it is credited over this representative gap-close /
# kite window when the registry row leaves ``duration_s`` at 0.
_MS_SUSTAINED_WINDOW_S = 3.0
# A gated (conditional) mobility move fires only some of the time - it is
# credited at this availability midpoint, the cc_output / cc_conditional shape.
_MOBILITY_CONDITIONAL_PROB = 0.5


@dataclass(frozen=True)
class MobilityEntry:
    """One registry row: a champion spell that repositions the caster.

    ``spell`` is one of ``{"P","Q","W","E","R"}``. ``kind`` is a key of
    ``_MOBILITY_KIND_WEIGHT``. For a displacement kind ``range_units`` is the
    max-rank travel distance in game units and ``charges`` the number of casts
    available in a short window (default 1); for ``MS_STEROID`` ``ms_pct`` is
    the max-rank decimal speed fraction (0.30 = +30%) and ``duration_s`` its
    seconds. ``conditional`` is True when the move only fires on a gate.
    """

    spell: str
    kind: str
    range_units: float = 0.0
    ms_pct: float = 0.0
    duration_s: float = 0.0
    charges: int = 1
    conditional: bool = False


def _normalized_units(entry: MobilityEntry) -> float:
    """Reduce a registry row to Flash-normalised mobility units.

    A speed steroid becomes the extra distance covered during the buff
    (``ms_pct * _BASE_MS * duration_s``); a displacement becomes its travel
    distance times its charge count. Both divided by ``_FLASH_UNITS``.
    """
    if entry.kind == "MS_STEROID":
        dur = entry.duration_s if entry.duration_s > 0 else _MS_SUSTAINED_WINDOW_S
        return (entry.ms_pct * _BASE_MS * dur) / _FLASH_UNITS
    charges = entry.charges if entry.charges and entry.charges > 0 else 1
    capped = min(entry.range_units, _MAX_DASH_UNITS)
    return (capped / _FLASH_UNITS) * charges


def _build_mobility_registry() -> dict[str, tuple[MobilityEntry, ...]]:
    """Build champion_id -> tuple[MobilityEntry] via an append builder.

    Uses ``raw.setdefault(champ, []).append(...)`` so a champion can carry
    several mobility spells without dict-literal collision (the cc_output /
    per-spell-CC builder pattern). Runs ONCE at import.
    """
    raw: dict[str, list[MobilityEntry]] = {}

    def add(
        champ: str,
        spell: str,
        kind: str,
        *,
        range_units: float = 0.0,
        ms_pct: float = 0.0,
        duration_s: float = 0.0,
        charges: int = 1,
        cond: bool = False,
    ) -> None:
        raw.setdefault(champ, []).append(
            MobilityEntry(
                spell=spell,
                kind=kind,
                range_units=float(range_units),
                ms_pct=float(ms_pct),
                duration_s=float(duration_s),
                charges=int(charges),
                conditional=bool(cond),
            )
        )

    # ===== INJECTED ENTRIES (item 297, 10-channel roster fan-out) =====
    # Aatrox
    add("Aatrox", "E", "DASH", range_units=300.0)
    add("Aatrox", "R", "MS_STEROID", ms_pct=0.6, duration_s=10.0)
    # Ahri
    add("Ahri", "W", "MS_STEROID", ms_pct=0.4, duration_s=2.0)
    add("Ahri", "R", "DASH", range_units=450.0, charges=3)
    # Akali
    add("Akali", "P", "MS_STEROID", ms_pct=0.6, duration_s=2.0, cond=True)
    add("Akali", "W", "MS_STEROID", ms_pct=0.5, duration_s=2.0)
    add("Akali", "E", "DASH", range_units=825.0, cond=True)
    add("Akali", "R", "DASH", range_units=750.0, cond=True)
    # Akshan
    add("Akshan", "W", "MS_STEROID", ms_pct=0.37, duration_s=0.0, cond=True)
    add("Akshan", "E", "LEAP", range_units=725.0, cond=True)
    # Alistar
    add("Alistar", "W", "DASH", range_units=650.0, cond=True)
    # Ambessa
    add("Ambessa", "P", "DASH", range_units=350.0, cond=True)
    add("Ambessa", "R", "BLINK", range_units=1250.0, cond=True)
    # Amumu
    add("Amumu", "Q", "DASH", range_units=1100.0, charges=2, cond=True)
    # Annie
    add("Annie", "E", "MS_STEROID", ms_pct=0.5, duration_s=1.5)
    # Aphelios
    add("Aphelios", "Q", "MS_STEROID", ms_pct=0.25, duration_s=1.75)
    # AurelionSol
    add("AurelionSol", "W", "DASH", range_units=1500.0)
    # Aurora
    add("Aurora", "W", "MS_STEROID", ms_pct=0.4, duration_s=4.0)
    add("Aurora", "E", "DASH", range_units=250.0)
    add("Aurora", "R", "LEAP", range_units=650.0)
    # Azir
    add("Azir", "E", "DASH", range_units=1000.0, cond=True)
    # Bard
    add("Bard", "E", "DASH", range_units=800.0, cond=True)
    # Belveth
    add("Belveth", "Q", "DASH", range_units=400.0)
    add("Belveth", "R", "DASH", range_units=500.0, cond=True)
    # Blitzcrank
    add("Blitzcrank", "W", "MS_STEROID", ms_pct=0.9, duration_s=4.0)
    # Braum
    add("Braum", "W", "LEAP", range_units=650.0, cond=True)
    add("Braum", "E", "MS_STEROID", ms_pct=0.1, duration_s=4.0, cond=True)
    # Briar
    add("Briar", "Q", "LEAP", range_units=600.0, cond=True)
    add("Briar", "W", "MS_STEROID", ms_pct=0.6, duration_s=5.0, cond=True)
    add("Briar", "R", "MS_STEROID", ms_pct=0.9, duration_s=0.0, cond=True)
    # Caitlyn
    add("Caitlyn", "E", "DASH", range_units=390.0)
    # Camille
    add("Camille", "E", "DASH", range_units=800.0, cond=True)
    add("Camille", "R", "LEAP", range_units=475.0, cond=True)
    # Cassiopeia
    add("Cassiopeia", "Q", "MS_STEROID", ms_pct=0.5, duration_s=3.0, cond=True)
    # Corki
    add("Corki", "W", "DASH", range_units=1800.0)
    # Darius
    add("Darius", "R", "LEAP", range_units=460.0, cond=True)
    # Diana
    add("Diana", "E", "DASH", range_units=825.0, cond=True)
    # DrMundo
    add("DrMundo", "R", "MS_STEROID", ms_pct=0.35, duration_s=10.0)
    # Draven
    add("Draven", "W", "MS_STEROID", ms_pct=0.7, duration_s=1.5)
    # Ekko
    add("Ekko", "P", "MS_STEROID", ms_pct=0.8, duration_s=3.0, cond=True)
    add("Ekko", "E", "DASH", range_units=325.0)
    add("Ekko", "R", "DASH", range_units=2000.0)
    # Elise
    add("Elise", "Q", "DASH", range_units=475.0, cond=True)
    add("Elise", "E", "UNTARGET_REPOSITION", range_units=825.0, cond=True)
    # Evelynn
    add("Evelynn", "E", "MS_STEROID", ms_pct=0.3, duration_s=2.0)
    add("Evelynn", "R", "BLINK", range_units=700.0)
    # Ezreal
    add("Ezreal", "E", "BLINK", range_units=475.0)
    # Fiddlesticks
    add("Fiddlesticks", "R", "BLINK", range_units=800.0)
    # Fiora
    add("Fiora", "P", "MS_STEROID", ms_pct=0.4, duration_s=1.85, cond=True)
    add("Fiora", "Q", "DASH", range_units=400.0)
    add("Fiora", "R", "MS_STEROID", ms_pct=0.5, duration_s=1.85, cond=True)
    # Fizz
    add("Fizz", "Q", "DASH", range_units=550.0, cond=True)
    add("Fizz", "E", "UNTARGET_REPOSITION", range_units=400.0, charges=2)
    # Galio
    add("Galio", "E", "DASH", range_units=650.0)
    add("Galio", "R", "LEAP", range_units=4200.0, cond=True)
    # Gangplank
    add("Gangplank", "P", "MS_STEROID", ms_pct=0.3, duration_s=2.0, cond=True)
    # Garen
    add("Garen", "Q", "MS_STEROID", ms_pct=0.35, duration_s=3.6)
    # Gnar
    add("Gnar", "W", "MS_STEROID", ms_pct=0.8, duration_s=3.0, cond=True)
    add("Gnar", "E", "LEAP", range_units=475.0)
    # Gragas
    add("Gragas", "E", "DASH", range_units=600.0)
    # Graves
    add("Graves", "E", "DASH", range_units=425.0)
    # Gwen
    add("Gwen", "E", "DASH", range_units=350.0)
    # Hecarim
    add("Hecarim", "E", "MS_STEROID", ms_pct=0.65, duration_s=4.0)
    add("Hecarim", "R", "DASH", range_units=1000.0)
    # Heimerdinger
    add("Heimerdinger", "P", "MS_STEROID", ms_pct=0.2, duration_s=0.0, cond=True)
    # Hwei
    add("Hwei", "W", "MS_STEROID", ms_pct=0.15, duration_s=3.0, cond=True)
    # Irelia
    add("Irelia", "Q", "DASH", range_units=600.0, cond=True)
    # Ivern
    add("Ivern", "Q", "DASH", range_units=1200.0, cond=True)
    # Janna
    add("Janna", "W", "MS_STEROID", ms_pct=0.1, duration_s=0.0)
    # JarvanIV
    add("JarvanIV", "Q", "LEAP", range_units=770.0, cond=True)
    add("JarvanIV", "R", "LEAP", range_units=650.0, cond=True)
    # Jax
    add("Jax", "Q", "LEAP", range_units=700.0, cond=True)
    # Jayce
    add("Jayce", "P", "MS_STEROID", ms_pct=0.12, duration_s=0.75)
    add("Jayce", "Q", "LEAP", range_units=600.0, cond=True)
    add("Jayce", "E", "MS_STEROID", ms_pct=0.3, duration_s=3.0, cond=True)
    # Jhin
    add("Jhin", "P", "MS_STEROID", ms_pct=0.14, duration_s=2.0, cond=True)
    # Jinx
    add("Jinx", "P", "MS_STEROID", ms_pct=1.75, duration_s=6.0, cond=True)
    # KSante
    add("KSante", "W", "DASH", range_units=450.0, cond=True)
    add("KSante", "E", "DASH", range_units=250.0)
    add("KSante", "R", "BLINK", range_units=175.0, cond=True)
    # Kaisa
    add("Kaisa", "E", "MS_STEROID", ms_pct=0.4, duration_s=1.2)
    add("Kaisa", "R", "DASH", range_units=1500.0, cond=True)
    # Kalista
    add("Kalista", "P", "DASH", range_units=300.0)
    # Karma
    add("Karma", "E", "MS_STEROID", ms_pct=0.4, duration_s=2.0)
    # Kassadin
    add("Kassadin", "R", "BLINK", range_units=500.0)
    # Katarina
    add("Katarina", "E", "BLINK", range_units=700.0, cond=True)
    # Kayle
    add("Kayle", "P", "MS_STEROID", ms_pct=0.1, duration_s=5.0, cond=True)
    add("Kayle", "W", "MS_STEROID", ms_pct=0.4, duration_s=2.0)
    # Kayn
    add("Kayn", "Q", "DASH", range_units=325.0)
    add("Kayn", "E", "MS_STEROID", ms_pct=0.7, duration_s=1.5, cond=True)
    add("Kayn", "R", "DASH", range_units=500.0, cond=True)
    # Kennen
    add("Kennen", "E", "MS_STEROID", ms_pct=1.0, duration_s=2.0)
    # Khazix
    add("Khazix", "E", "LEAP", range_units=700.0)
    add("Khazix", "R", "MS_STEROID", ms_pct=0.4, duration_s=1.25)
    # Kindred
    add("Kindred", "Q", "LEAP", range_units=325.0)
    # Kled
    add("Kled", "P", "MS_STEROID", ms_pct=0.49, duration_s=1.5, cond=True)
    add("Kled", "Q", "DASH", range_units=300.0, charges=2, cond=True)
    add("Kled", "E", "DASH", range_units=700.0, charges=2, cond=True)
    add("Kled", "R", "MS_STEROID", ms_pct=1.5, duration_s=3.0)
    # KogMaw
    add("KogMaw", "P", "MS_STEROID", ms_pct=0.5, duration_s=4.0, cond=True)
    # Leblanc
    add("Leblanc", "W", "BLINK", range_units=600.0, cond=True)
    # LeeSin
    add("LeeSin", "Q", "DASH", range_units=1100.0, cond=True)
    add("LeeSin", "W", "DASH", range_units=700.0, cond=True)
    # Leona
    add("Leona", "E", "DASH", range_units=225.0, cond=True)
    # Lillia
    add("Lillia", "Q", "MS_STEROID", ms_pct=0.28, duration_s=6.5)
    add("Lillia", "W", "DASH", range_units=500.0)
    # Lissandra
    add("Lissandra", "E", "BLINK", range_units=900.0)
    # Lucian
    add("Lucian", "E", "DASH", range_units=425.0)
    # Lulu
    add("Lulu", "W", "MS_STEROID", ms_pct=0.25, duration_s=4.0, cond=True)
    # Malphite
    add("Malphite", "Q", "MS_STEROID", ms_pct=0.4, duration_s=3.0, cond=True)
    add("Malphite", "R", "DASH", range_units=1000.0)
    # Maokai
    add("Maokai", "W", "UNTARGET_REPOSITION", range_units=650.0, cond=True)
    add("Maokai", "R", "MS_STEROID", ms_pct=0.6, duration_s=2.0, cond=True)
    # MasterYi
    add("MasterYi", "Q", "UNTARGET_REPOSITION", range_units=600.0, cond=True)
    add("MasterYi", "R", "MS_STEROID", ms_pct=0.35, duration_s=7.0)
    # Mel
    add("Mel", "W", "MS_STEROID", ms_pct=0.3, duration_s=0.75)
    add("Mel", "E", "DASH", range_units=300.0)
    # Milio
    add("Milio", "E", "MS_STEROID", ms_pct=0.2, duration_s=2.5)
    # MissFortune
    add("MissFortune", "W", "MS_STEROID", ms_pct=0.31, duration_s=0.0, cond=True)
    # MonkeyKing
    add("MonkeyKing", "W", "DASH", range_units=300.0)
    add("MonkeyKing", "E", "DASH", range_units=625.0, cond=True)
    add("MonkeyKing", "R", "MS_STEROID", ms_pct=0.2, duration_s=4.0)
    # Mordekaiser
    add("Mordekaiser", "P", "MS_STEROID", ms_pct=0.09, duration_s=4.0, cond=True)
    # Naafiri
    add("Naafiri", "W", "MS_STEROID", ms_pct=0.3, duration_s=5.0)
    add("Naafiri", "E", "DASH", range_units=600.0)
    add("Naafiri", "R", "DASH", range_units=900.0, cond=True)
    # Nami
    add("Nami", "P", "MS_STEROID", ms_pct=0.3, duration_s=1.5, cond=True)
    # Nautilus
    add("Nautilus", "Q", "DASH", range_units=1150.0, cond=True)
    # Neeko
    add("Neeko", "W", "MS_STEROID", ms_pct=0.25, duration_s=2.0)
    # Nidalee
    add("Nidalee", "P", "MS_STEROID", ms_pct=0.3, duration_s=4.0, cond=True)
    add("Nidalee", "W", "LEAP", range_units=375.0)
    # Nilah
    add("Nilah", "W", "MS_STEROID", ms_pct=0.25, duration_s=2.25)
    add("Nilah", "E", "DASH", range_units=325.0, charges=2, cond=True)
    # Nocturne
    add("Nocturne", "Q", "MS_STEROID", ms_pct=0.35, duration_s=5.0, cond=True)
    add("Nocturne", "R", "DASH", range_units=4000.0, cond=True)
    # Nunu
    add("Nunu", "P", "MS_STEROID", ms_pct=0.1, duration_s=4.0, cond=True)
    add("Nunu", "W", "MS_STEROID", ms_pct=0.6, duration_s=10.0)
    # Olaf
    add("Olaf", "R", "MS_STEROID", ms_pct=0.7, duration_s=1.0, cond=True)
    # Ornn
    add("Ornn", "W", "DASH", range_units=200.0)
    add("Ornn", "E", "DASH", range_units=450.0)
    add("Ornn", "R", "DASH", range_units=700.0, cond=True)
    # Pantheon
    add("Pantheon", "W", "LEAP", range_units=600.0, cond=True)
    add("Pantheon", "E", "MS_STEROID", ms_pct=0.6, duration_s=1.5, cond=True)
    add("Pantheon", "R", "LEAP", range_units=25000.0)
    # Poppy
    add("Poppy", "W", "MS_STEROID", ms_pct=0.4, duration_s=2.0)
    add("Poppy", "E", "DASH", range_units=475.0, cond=True)
    # Pyke
    add("Pyke", "W", "MS_STEROID", ms_pct=0.45, duration_s=5.0)
    add("Pyke", "E", "DASH", range_units=400.0)
    add("Pyke", "R", "BLINK", range_units=600.0, cond=True)
    # Qiyana
    add("Qiyana", "W", "DASH", range_units=300.0, cond=True)
    add("Qiyana", "E", "DASH", range_units=750.0, cond=True)
    # Quinn
    add("Quinn", "E", "DASH", range_units=700.0, cond=True)
    add("Quinn", "R", "MS_STEROID", ms_pct=1.3, duration_s=0.0)
    # Rakan
    add("Rakan", "W", "DASH", range_units=600.0)
    add("Rakan", "E", "DASH", range_units=700.0, charges=2, cond=True)
    add("Rakan", "R", "MS_STEROID", ms_pct=0.75, duration_s=4.0)
    # Rammus
    add("Rammus", "Q", "MS_STEROID", ms_pct=2.35, duration_s=6.0)
    add("Rammus", "R", "LEAP", range_units=800.0)
    # RekSai
    add("RekSai", "W", "MS_STEROID", ms_pct=0.1, duration_s=0.0)
    add("RekSai", "E", "BLINK", range_units=2500.0, cond=True)
    add("RekSai", "R", "DASH", range_units=1500.0, cond=True)
    # Rell
    add("Rell", "Q", "DASH", range_units=100.0)
    add("Rell", "W", "MS_STEROID", ms_pct=0.3, duration_s=2.0, cond=True)
    add("Rell", "E", "MS_STEROID", ms_pct=0.25, duration_s=3.0)
    # Renata
    add("Renata", "W", "MS_STEROID", ms_pct=0.4, duration_s=5.0, cond=True)
    # Renekton
    add("Renekton", "E", "DASH", range_units=450.0, charges=2)
    # Rengar
    add("Rengar", "P", "LEAP", range_units=600.0, cond=True)
    add("Rengar", "R", "MS_STEROID", ms_pct=0.4, duration_s=12.0)
    # Riven
    add("Riven", "Q", "DASH", range_units=325.0, charges=3)
    add("Riven", "E", "DASH", range_units=325.0)
    # Rumble
    add("Rumble", "W", "MS_STEROID", ms_pct=0.3, duration_s=1.3)
    # Ryze
    add("Ryze", "Q", "MS_STEROID", ms_pct=0.25, duration_s=2.0, cond=True)
    add("Ryze", "R", "BLINK", range_units=3000.0)
    # Samira
    add("Samira", "P", "DASH", range_units=1000.0, cond=True)
    add("Samira", "E", "DASH", range_units=600.0)
    # Sejuani
    add("Sejuani", "Q", "DASH", range_units=650.0)
    # Seraphine
    add("Seraphine", "W", "MS_STEROID", ms_pct=0.2, duration_s=2.5)
    # Sett
    add("Sett", "Q", "MS_STEROID", ms_pct=0.3, duration_s=1.5, cond=True)
    add("Sett", "R", "LEAP", range_units=1250.0, cond=True)
    # Shaco
    add("Shaco", "Q", "BLINK", range_units=400.0)
    add("Shaco", "R", "BLINK", range_units=300.0)
    # Shen
    add("Shen", "E", "DASH", range_units=600.0)
    add("Shen", "R", "BLINK", range_units=25000.0, cond=True)
    # Shyvana
    add("Shyvana", "W", "MS_STEROID", ms_pct=0.3, duration_s=3.0)
    add("Shyvana", "R", "LEAP", range_units=1000.0)
    # Singed
    add("Singed", "P", "MS_STEROID", ms_pct=0.3, duration_s=2.0, cond=True)
    add("Singed", "R", "MS_STEROID", ms_pct=0.28, duration_s=25.0)
    # Sion
    add("Sion", "P", "MS_STEROID", ms_pct=0.67, duration_s=2.376, cond=True)
    add("Sion", "R", "DASH", range_units=7000.0)
    # Sivir
    add("Sivir", "P", "MS_STEROID", ms_pct=0.2, duration_s=1.5, cond=True)
    add("Sivir", "E", "MS_STEROID", ms_pct=0.3, duration_s=1.5, cond=True)
    add("Sivir", "R", "MS_STEROID", ms_pct=0.6, duration_s=4.0)
    # Skarner
    add("Skarner", "E", "DASH", range_units=1700.0)
    add("Skarner", "R", "MS_STEROID", ms_pct=0.4, duration_s=1.5, cond=True)
    # Smolder
    add("Smolder", "W", "MS_STEROID", ms_pct=0.75, duration_s=1.25)
    add("Smolder", "E", "DASH", range_units=250.0)
    # Sona
    add("Sona", "E", "MS_STEROID", ms_pct=0.2, duration_s=7.0)
    # Soraka
    add("Soraka", "P", "MS_STEROID", ms_pct=0.9, duration_s=0.0, cond=True)
    add("Soraka", "Q", "MS_STEROID", ms_pct=0.3, duration_s=2.5, cond=True)
    # Sylas
    add("Sylas", "W", "DASH", range_units=800.0, cond=True)
    add("Sylas", "E", "DASH", range_units=950.0, cond=True)
    # TahmKench
    add("TahmKench", "W", "BLINK", range_units=900.0)
    add("TahmKench", "R", "MS_STEROID", ms_pct=0.4, duration_s=3.0, cond=True)
    # Taliyah
    add("Taliyah", "P", "MS_STEROID", ms_pct=0.4, duration_s=0.0, cond=True)
    add("Taliyah", "R", "LEAP", range_units=3000.0, cond=True)
    # Talon
    add("Talon", "Q", "DASH", range_units=550.0, cond=True)
    add("Talon", "E", "DASH", range_units=725.0, cond=True)
    add("Talon", "R", "MS_STEROID", ms_pct=0.4, duration_s=2.5)
    # Teemo
    add("Teemo", "W", "MS_STEROID", ms_pct=0.35, duration_s=3.0)
    # Thresh
    add("Thresh", "Q", "DASH", range_units=1100.0, cond=True)
    # Tristana
    add("Tristana", "W", "LEAP", range_units=900.0)
    # Trundle
    add("Trundle", "W", "MS_STEROID", ms_pct=0.52, duration_s=8.0, cond=True)
    # Tryndamere
    add("Tryndamere", "E", "DASH", range_units=650.0)
    # TwistedFate
    add("TwistedFate", "R", "BLINK", range_units=5500.0)
    # Twitch
    add("Twitch", "Q", "MS_STEROID", ms_pct=0.3, duration_s=6.0, cond=True)
    # Udyr
    add("Udyr", "E", "MS_STEROID", ms_pct=0.4, duration_s=4.0)
    # Urgot
    add("Urgot", "E", "DASH", range_units=450.0)
    # Vayne
    add("Vayne", "P", "MS_STEROID", ms_pct=0.09, duration_s=2.0, cond=True)
    add("Vayne", "Q", "DASH", range_units=300.0)
    # Vex
    add("Vex", "R", "DASH", range_units=25000.0, cond=True)
    # Vi
    add("Vi", "Q", "DASH", range_units=700.0)
    add("Vi", "R", "DASH", range_units=800.0, cond=True)
    # Viego
    add("Viego", "W", "DASH", range_units=400.0)
    add("Viego", "E", "MS_STEROID", ms_pct=0.3, duration_s=8.0, cond=True)
    add("Viego", "R", "BLINK", range_units=500.0, cond=True)
    # Viktor
    add("Viktor", "Q", "MS_STEROID", ms_pct=0.3, duration_s=2.5, cond=True)
    # Vladimir
    add("Vladimir", "Q", "MS_STEROID", ms_pct=0.4, duration_s=0.5, cond=True)
    add("Vladimir", "W", "UNTARGET_REPOSITION", range_units=150.0)
    # Volibear
    add("Volibear", "Q", "MS_STEROID", ms_pct=0.26, duration_s=4.0)
    add("Volibear", "R", "LEAP", range_units=700.0)
    # Warwick
    add("Warwick", "Q", "DASH", range_units=365.0, cond=True)
    add("Warwick", "W", "MS_STEROID", ms_pct=0.65, duration_s=0.0, cond=True)
    add("Warwick", "R", "LEAP", range_units=838.0)
    # Xayah
    add("Xayah", "W", "MS_STEROID", ms_pct=0.3, duration_s=1.5, cond=True)
    add("Xayah", "R", "UNTARGET_REPOSITION", range_units=150.0)
    # XinZhao
    add("XinZhao", "E", "DASH", range_units=650.0)
    # Yasuo
    add("Yasuo", "E", "DASH", range_units=475.0, cond=True)
    add("Yasuo", "R", "BLINK", range_units=1100.0, cond=True)
    # Yone
    add("Yone", "Q", "DASH", range_units=450.0, cond=True)
    add("Yone", "E", "DASH", range_units=550.0)
    add("Yone", "R", "BLINK", range_units=1000.0, cond=True)
    # Yunara
    add("Yunara", "E", "DASH", range_units=600.0)
    # Yuumi
    add("Yuumi", "W", "DASH", range_units=1100.0, cond=True)
    # Zac
    add("Zac", "E", "LEAP", range_units=1800.0, cond=True)
    add("Zac", "R", "MS_STEROID", ms_pct=0.5, duration_s=3.0)
    # Zed
    add("Zed", "W", "BLINK", range_units=650.0, cond=True)
    add("Zed", "R", "BLINK", range_units=625.0, charges=2, cond=True)
    # Zeri
    add("Zeri", "P", "MS_STEROID", ms_pct=0.1, duration_s=3.0, cond=True)
    add("Zeri", "E", "DASH", range_units=300.0)
    add("Zeri", "R", "MS_STEROID", ms_pct=0.2, duration_s=8.0)
    # Ziggs
    add("Ziggs", "W", "DASH", range_units=825.0, cond=True)
    # Zilean
    add("Zilean", "E", "MS_STEROID", ms_pct=0.99, duration_s=2.5)
    # Zoe
    add("Zoe", "W", "MS_STEROID", ms_pct=0.7, duration_s=3.0)
    add("Zoe", "R", "BLINK", range_units=300.0)
    # ===== END INJECTED ENTRIES =====

    return {champ: tuple(entries) for champ, entries in raw.items()}


_MOBILITY_REGISTRY: dict[str, tuple[MobilityEntry, ...]] = (
    _build_mobility_registry()
)


@dataclass(frozen=True)
class MobilitySpellEntry:
    """One scored mobility spell for a champion.

    ``mobility_units`` is the Flash-normalised magnitude (pre-weight);
    ``weighted_units`` = ``mobility_units * kind_weight`` for an unconditional
    entry, times ``_MOBILITY_CONDITIONAL_PROB`` when ``conditional`` is True.
    """

    spell_key: str
    kind: str
    mobility_units: float
    kind_weight: float
    conditional: bool
    weighted_units: float

    def to_dict(self) -> dict:
        return {
            "spell_key": self.spell_key,
            "kind": self.kind,
            "mobility_units": round(self.mobility_units, 4),
            "kind_weight": self.kind_weight,
            "conditional": self.conditional,
            "weighted_units": round(self.weighted_units, 4),
        }


@dataclass(frozen=True)
class MobilityResult:
    """Aggregate self-mobility (gap-close / kiting) for one champion.

    ``mobility_score`` sums ``weighted_units`` over the UNCONDITIONAL spells;
    ``conditional_mobility_score`` sums them over the gated spells (already
    discounted by the availability midpoint); ``total_mobility_score`` is their
    sum. ``raw_mobility_units`` is the unweighted unconditional unit sum (the
    kind-agnostic comparable quantity). Returns all-zero with an empty
    ``spells`` tuple for an unregistered or blank champion (never raises).
    """

    champion: str
    mode: str
    mobility_score: float
    conditional_mobility_score: float
    total_mobility_score: float
    raw_mobility_units: float
    spells: tuple[MobilitySpellEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "champion": self.champion,
            "mode": self.mode,
            "mobility_score": round(self.mobility_score, 4),
            "conditional_mobility_score": round(
                self.conditional_mobility_score, 4
            ),
            "total_mobility_score": round(self.total_mobility_score, 4),
            "raw_mobility_units": round(self.raw_mobility_units, 4),
            "spells": [s.to_dict() for s in self.spells],
        }


def _empty_result(champion: str, mode: str) -> MobilityResult:
    return MobilityResult(
        champion=champion,
        mode=mode,
        mobility_score=0.0,
        conditional_mobility_score=0.0,
        total_mobility_score=0.0,
        raw_mobility_units=0.0,
        spells=(),
    )


def _spell_sort_key(entry: MobilityEntry) -> tuple[int, str]:
    try:
        return (_SPELL_ORDER.index(entry.spell), entry.spell)
    except ValueError:
        return (len(_SPELL_ORDER), entry.spell)


def compute_mobility(champion: str, mode: str = "SR") -> MobilityResult:
    """Aggregate a champion's self-mobility into a gap-close / kiting score.

    Reads ``_MOBILITY_REGISTRY``. Each registered mobility spell is reduced to
    Flash-normalised units (``_normalized_units``) and scaled by the per-kind
    weight (``_MOBILITY_KIND_WEIGHT``); conditional spells are discounted by
    ``_MOBILITY_CONDITIONAL_PROB``. ``mode`` is carried on the result for parity
    with the other scorers but does not change output today (self-mobility is
    target-independent).

    Returns an all-zero ``MobilityResult`` (empty ``spells``) when the champion
    is blank / None or absent from the registry; never raises.
    """
    safe_mode = mode if mode else "SR"
    if not champion:
        return _empty_result("", safe_mode)
    entries = _MOBILITY_REGISTRY.get(champion)
    if not entries:
        return _empty_result(champion, safe_mode)

    scored: list[MobilitySpellEntry] = []
    mobility = 0.0
    conditional_mobility = 0.0
    raw_uncond_units = 0.0
    for entry in sorted(entries, key=_spell_sort_key):
        weight = _MOBILITY_KIND_WEIGHT.get(entry.kind, 0.0)
        units = _normalized_units(entry)
        base_weighted = units * weight
        if entry.conditional:
            weighted = base_weighted * _MOBILITY_CONDITIONAL_PROB
            conditional_mobility += weighted
        else:
            weighted = base_weighted
            mobility += weighted
            raw_uncond_units += units
        scored.append(
            MobilitySpellEntry(
                spell_key=entry.spell,
                kind=entry.kind,
                mobility_units=units,
                kind_weight=weight,
                conditional=entry.conditional,
                weighted_units=weighted,
            )
        )

    return MobilityResult(
        champion=champion,
        mode=safe_mode,
        mobility_score=mobility,
        conditional_mobility_score=conditional_mobility,
        total_mobility_score=mobility + conditional_mobility,
        raw_mobility_units=raw_uncond_units,
        spells=tuple(scored),
    )


__all__ = [
    "MobilityEntry",
    "MobilityResult",
    "MobilitySpellEntry",
    "compute_mobility",
    "_MOBILITY_KIND_WEIGHT",
    "_MOBILITY_CONDITIONAL_PROB",
    "_MOBILITY_REGISTRY",
    "_FLASH_UNITS",
    "_BASE_MS",
    "_MS_SUSTAINED_WINDOW_S",
    "_MAX_DASH_UNITS",
]
