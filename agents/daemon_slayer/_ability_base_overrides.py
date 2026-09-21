"""A-03 / RM-81 - hand-authored corrections for STALE ability base damage.

Context. The 2026-07-18 RM-81 characterization
(``docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:445-621``) measured 75 stale
champions / 123 findings against the live wiki, then asked the only question
that matters for a build engine: how many of them CHANGE A RANKED ITEM ORDER.
The answer is six, tabulated verbatim at
``docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:562-571``. This registry carries
exactly those six and nothing else.

Why a REGISTRY and not a re-extract. Every automated route reproduces the stale
numbers:

* ``tools/daemon_slayer_abilities_extract.py`` is ``--force`` / ``--patch``
  only and all-or-nothing, and it pins
  ``_EXPECTED_MERAKI_CONTENT_PATCH = "25.15"`` at ``:128``. Re-running it
  re-writes the SAME values.
* Running it with ``--force`` is a standing repo hazard (the Meraki ``latest``
  endpoint is mutable), confirmed at three independent sites.
* The wiki extractor writes a GEOMETRY sidecar - it carries no base damage.
* The CDragon mechanical sidecar
  (``data/daemon_slayer/<patch>/cdragon_ability_ratios.json``) reaches only one
  of the six: it resolves Heimerdinger W ``Damage`` base
  ``[50, 75, 100, 125, 150, 175]`` (an INDEPENDENT confirmation of the wiki
  value seeded below), but the form's 3 mechanical blocks against Meraki's 2
  damage blocks is a cardinality mismatch, so
  ``abilities._apply_cdragon_ratio_preference`` falls the whole form back to
  Meraki by design. For the other five the sidecar resolves ``base = None``.

So the correction has to be authored, in code, keyed off the extract - exactly
the ``_passive_damage_overrides`` precedent (item 238 / GAP-2), and applied at
load time behind an opt-in flag.

METHOD - what "corrected" means. The notes' method section
(``DS_ABILITY_SHAPING_NOTES.md:528-532``) states the harness replaced each
drifted base with "the live wiki endpoints (linear ramp across the same rank
count - exactly what the wiki ``{{ap|X to Y}}`` macro means)". Each entry below
therefore stores the ramp ``_ramp(low, high, rank_count)``, with ``rank_count``
taken from the ability's own rank count (5 for a basic, 3 for an ult), and the
notes' ``stored -> wiki`` endpoint pair reproduced in the entry's comment.

SHAPE - why only the HEAD of the base array is replaced. Three of the six store
an 18-element base: a 5-entry rank series CONCATENATED with a 13-entry
per-level tail (the checker defect written up at
``DS_ABILITY_SHAPING_NOTES.md:592-617``; Mordekaiser Q is the worked example at
``:600-602``). Only the leading ``len(corrected)`` elements are the real rank
series, and only those are replaced - the tail is carried through untouched, so
the stored array keeps its length and nothing downstream of it changes. This is
also why the committed ``ability_staleness.json`` baseline mis-reports
Mordekaiser Q at 389 pct against a true ~5 pct: it predates the shape fix.

ANTI-DOUBLE-CORRECTION. Each entry carries the ``stale`` series currently on
disk. ``apply_base_overrides`` applies the correction ONLY when the loaded block
still matches ``stale`` (tolerance ``_TOL`` 1e-2, the same tolerance the RM-81
checker uses). If a future re-extract - or a future CDragon block - already
fixes the number, the entry silently stops applying and logs at WARNING that it
is stale-as-in-obsolete. A registry that blindly overwrote would double-correct
the day the upstream source is repaired.

DEFAULT-OFF. Mirrors the ``apply_passive_damage`` seam exactly: the hook in
``abilities.AbilitiesSnapshot.load`` runs only under
``apply_ability_base_overrides=True``. With the flag OFF (the default) NOT ONE
form is touched and the whole snapshot is byte-identical, so no shipped build
table, no ``:8860`` response and no existing test moves. Flipping it default-on
is a separate, measured decision - the notes' own bottom line is that all six
are ADJACENT-PAIR reorders inside an already-recommended core
(``DS_ABILITY_SHAPING_NOTES.md:577-588``), i.e. worth correcting for
truthfulness, not an emergency.

NOT SEEDED. The other 69 stale champions are deliberately absent: 43 route to a
scorer that never reads ability data on their axis (unreachable by
construction) and 26 are reachable but move no order
(``DS_ABILITY_SHAPING_NOTES.md:466-471``). Adding them would be authored risk
with zero measured output effect.

RM-480 RATIO LIFT (ENGINE 1.283.0). The 16.18.1 ratio-aware re-sweep of the
RM-81 detector surfaced drift that lives in the RATIO terms (Poppy Q's 100 ->
75 pct bonus AD moves no base at all), so an entry now names the ``field`` it
corrects: ``base`` (the default, so the six rows above are unchanged) or any
ratio key the detector measures (``_ALLOWED_FIELDS``). Seven champions were
added from ``data/daemon_slayer/16.18.1/ability_staleness.json`` - their
interior ranks are wiki-MEASURED, not ramp-inferred (see the block comment on
those entries). Guarding became all-or-nothing per form. Still DEFAULT-OFF.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace

_LOG = logging.getLogger(__name__)

# Same tolerance the RM-81 staleness checker uses - it already eats float
# representation noise, and the notes measured ZERO findings in the <=2 pct
# bucket, so nothing real hides under it.
_TOL: float = 1e-2


def _ramp(low: float, high: float, count: int) -> tuple[float, ...]:
    """The wiki ``{{ap|X to Y}}`` series: a linear ramp over ``count`` ranks.

    ``_ramp(150, 300, 3) -> (150.0, 225.0, 300.0)``. Rounded to 6 places so the
    authored values stay stable + ASCII-clean (same convention as
    ``_passive_damage_overrides._lerp_per_level``).
    """
    if count < 2:
        return (float(low),)
    span = count - 1
    return tuple(round(low + (high - low) * i / span, 6) for i in range(count))


# RM-480: the per-rank fields an entry may override. ``base`` plus every ratio
# key the RM-81 staleness detector can measure
# (``tools/ds_wiki_staleness_check._RATIO_KEYS``; a DS test pins the two sets
# equal, and pins each name to a real ``DamageBlock`` field). Anything else is
# refused at construction, i.e. at import of this module.
_ALLOWED_FIELDS: tuple[str, ...] = (
    "base",
    "ap_pct",
    "total_ad_pct",
    "bonus_ad_pct",
    "target_max_hp_pct",
    "target_missing_hp_pct",
    "target_current_hp_pct",
    "target_bonus_hp_pct",
    "caster_max_hp_pct",
    "caster_bonus_hp_pct",
    "bonus_armor_pct",
    "bonus_mr_pct",
    "caster_max_mp_pct",
    "caster_bonus_mp_pct",
)


@dataclass(frozen=True)
class AbilityBaseOverride:
    """One corrected per-rank series for one field of one named damage block.

    ``attribute`` selects the block by its ``DamageBlock.attribute`` string
    (never by position - a Meraki re-extract can reorder blocks; with a
    duplicated attribute the FIRST block wins, the same rule the staleness
    detector uses). ``field`` names the ``DamageBlock`` field corrected -
    ``base`` (the original A-03 shape) or, since RM-480, a per-rank ratio key.
    ``stale`` is the series currently on disk and acts as the apply-guard;
    ``corrected`` is the wiki-true series. ``source`` MUST cite where the
    numbers came from (the ``DS_ABILITY_SHAPING_NOTES`` line for the A-03 six,
    ``ability_staleness.json`` for the RM-480 seven).
    """

    attribute: str
    stale: tuple[float, ...]
    corrected: tuple[float, ...]
    source: str
    note: str
    field: str = "base"

    def __post_init__(self) -> None:
        if self.field not in _ALLOWED_FIELDS:
            raise ValueError(
                f"AbilityBaseOverride field {self.field!r} is not one of "
                f"{_ALLOWED_FIELDS}"
            )
        if not self.stale or len(self.stale) != len(self.corrected):
            raise ValueError(
                f"AbilityBaseOverride {self.attribute!r}.{self.field}: stale and "
                "corrected must be non-empty and the same length"
            )


_RM480_SRC = "data/daemon_slayer/16.18.1/ability_staleness.json"

# (champion_id, key, form_index) -> the block overrides for that form.
#
# A tuple of entries per key so a future champion needing TWO blocks corrected
# on one form does not need a schema change. All six seeded rows correct one
# block each, and every one of them is the form's FIRST damage block - which is
# what ``ability_dps`` reads under its default ``block_strategy="first"``, and
# is why these six (and not the other 69) move a ranked order.
_ABILITY_BASE_OVERRIDES: dict[tuple[str, str, int], tuple[AbilityBaseOverride, ...]] = {
    # Mordekaiser Q Obliterate. notes:566 - "Q base Magic Damage
    # [80, 230.6] -> [80, 220]", true drift 4.6 pct, first divergence at ranked
    # item 2 (top-5: Void Staff <-> Rabadon's swap, notes:580). The stored array
    # is the 18-element concatenated shape (notes:600-602) - only the 5-rank
    # head is replaced.
    ("Mordekaiser", "Q", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(80.0, 117.647059, 155.294118, 192.941176, 230.588235),
            corrected=_ramp(80.0, 220.0, 5),
            source="docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:566",
            note="Obliterate: base 80 : 230.6 -> 80 : 220 (5 ranks); 4.6 pct drift, moves ranked item 2",
        ),
    ),
    # Naafiri R The Call of the Pack. notes:567 - "R base Physical Damage
    # [150, 350] -> [150, 300]", true drift 14.3 pct, first divergence at ranked
    # item 3 (top-5: Serylda's <-> Bloodthirster swap, notes:582). Rank 0 is 150
    # in BOTH series - the correction is a slope fix, not a rescale.
    ("Naafiri", "R", 0): (
        AbilityBaseOverride(
            attribute="Physical Damage",
            stale=(150.0, 250.0, 350.0),
            corrected=_ramp(150.0, 300.0, 3),
            source="docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:567",
            note="The Call of the Pack: base 150 : 350 -> 150 : 300 (3 ranks); 14.3 pct drift, moves ranked item 3",
        ),
    ),
    # Heimerdinger W Hextech Micro-Rockets. notes:568 - "W base Initial Rocket
    # [40, 140] -> [50, 150]", 25.0 pct drift, first divergence at ranked item 8.
    # INDEPENDENTLY CONFIRMED by the CDragon sidecar, whose W ``Damage`` block
    # resolves base [50, 75, 100, 125, 150, 175] - the identical head - but which
    # the bijection rule declines (3 mechanical blocks vs 2 Meraki damage
    # blocks). form_index 0 is the base form; form 1 is the R-upgraded rocket
    # set and is NOT part of this row.
    ("Heimerdinger", "W", 0): (
        AbilityBaseOverride(
            attribute="Initial Rocket Magic Damage",
            stale=(40.0, 65.0, 90.0, 115.0, 140.0),
            corrected=_ramp(50.0, 150.0, 5),
            source="docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:568",
            note="Hextech Micro-Rockets initial: base 40 : 140 -> 50 : 150 (5 ranks); 25.0 pct drift, moves ranked item 8; matches the CDragon W Damage block head",
        ),
    ),
    # Azir W Arise!. notes:569 - "W base Magic Damage [50, 120.6] -> [50, 110]",
    # 8.8 pct drift, first divergence at ranked item 19. 18-element concatenated
    # shape (it is one of the checker's five shape false positives, notes:610) -
    # only the 5-rank head is replaced.
    ("Azir", "W", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(50.0, 67.647059, 85.294118, 102.941176, 120.588235),
            corrected=_ramp(50.0, 110.0, 5),
            source="docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:569",
            note="Arise!: base 50 : 120.6 -> 50 : 110 (5 ranks); 8.8 pct drift, moves ranked item 19",
        ),
    ),
    # Malzahar W Void Swarm. notes:570 - "W base Magic Damage [17, 39] ->
    # [12, 20]", 48.7 pct drift, first divergence at ranked item 25. Also an
    # 18-element concatenated shape (notes:612 lists it among the five shape
    # rows, reported 69 pct / TRUE 49 pct) - only the 5-rank head is replaced.
    ("Malzahar", "W", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(17.0, 22.5, 28.0, 33.5, 39.0),
            corrected=_ramp(12.0, 20.0, 5),
            source="docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:570",
            note="Void Swarm: base 17 : 39 -> 12 : 20 (5 ranks); 48.7 pct drift, moves ranked item 25",
        ),
    ),
    # Ahri R Spirit Rush. notes:571 - "R base Magic Damage [60, 120] ->
    # [75, 175]", 45.8 pct drift, first divergence at ranked item 37. Re-verified
    # still stale in data/daemon_slayer/16.14.1/champion_abilities.json
    # (OPEN_ITEMS_REVIEW_2026-07-25.md:463-464).
    ("Ahri", "R", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(60.0, 90.0, 120.0),
            corrected=_ramp(75.0, 175.0, 3),
            source="docs/_archive/2026-07-28-research-consolidation/DS_ABILITY_SHAPING_NOTES.md:571",
            note="Spirit Rush: base 60 : 120 -> 75 : 175 (3 ranks); 45.8 pct drift, moves ranked item 37",
        ),
    ),
    # ---------------------------------------------------------------- RM-480
    # The seven HIGH rows of the 16.18.1 ratio-aware RM-81 sweep. ``stale`` is
    # ``data/daemon_slayer/16.18.1/champion_abilities.json`` verbatim; the
    # endpoints of ``corrected`` are the ``wiki`` column of
    # ``ability_staleness.json``, and EVERY interior rank is WIKI-MEASURED: the
    # per-rank lists below are the ones wiki.leagueoflegends.com rendered on
    # 2026-09-21 (read-only fetch), not a ramp computed here. They do equal the
    # ``{{ap|X to Y}}`` linear ramp of the cached wikitext in
    # ``wiki_ability_stats.json``, which is corroboration, not the source.
    ("Poppy", "Q", 0): (
        AbilityBaseOverride(
            attribute="Physical Damage",
            field="bonus_ad_pct",
            stale=(100.0,) * 5,
            corrected=(75.0,) * 5,
            source=_RM480_SRC + " (ratio:Physical Damage:bonus_ad_pct)",
            note="Hammer Shock: 100 -> 75 pct bonus AD, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Physical Damage",
            field="target_max_hp_pct",
            stale=(9.0,) * 5,
            corrected=(7.0, 7.5, 8.0, 8.5, 9.0),
            source=_RM480_SRC + " (ratio:Physical Damage:target_max_hp_pct)",
            note="Hammer Shock: flat 9 -> 7/7.5/8/8.5/9 pct max HP, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Total Physical Damage",
            field="bonus_ad_pct",
            stale=(200.0,) * 5,
            corrected=(150.0,) * 5,
            source=_RM480_SRC + " (ratio:Total Physical Damage:bonus_ad_pct)",
            note="Hammer Shock total (two hits): 200 -> 150 pct bonus AD, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Total Physical Damage",
            field="target_max_hp_pct",
            stale=(18.0,) * 5,
            corrected=(14.0, 15.0, 16.0, 17.0, 18.0),
            source=_RM480_SRC + " (ratio:Total Physical Damage:target_max_hp_pct)",
            note="Hammer Shock total: flat 18 -> 14/15/16/17/18 pct max HP, wiki-measured",
        ),
    ),
    # Form 0 (Edge of Ixtal) only. Form 1 (Elemental Wrath) carries the same
    # stale Physical/Reduced blocks plus Increased/Subsequent blocks the report
    # has no row for - deliberately left for a follow-up, not guessed at here.
    ("Qiyana", "Q", 0): (
        AbilityBaseOverride(
            attribute="Physical Damage",
            stale=(60.0, 90.0, 120.0, 150.0, 180.0),
            corrected=(80.0, 110.0, 140.0, 170.0, 200.0),
            source=_RM480_SRC + " (base:Physical Damage)",
            note="Edge of Ixtal: base 60 : 180 -> 80 : 200, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Reduced Damage",
            stale=(45.0, 67.5, 90.0, 112.5, 135.0),
            corrected=(60.0, 82.5, 105.0, 127.5, 150.0),
            source=_RM480_SRC + " (base:Reduced Damage)",
            note="Edge of Ixtal reduced: base 45 : 135 -> 60 : 150, wiki-measured",
        ),
    ),
    ("Thresh", "E", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(75.0, 120.0, 165.0, 210.0, 255.0),
            corrected=(65.0, 110.0, 155.0, 200.0, 245.0),
            source=_RM480_SRC + " (base:Magic Damage)",
            note="Flay: base 75 : 255 -> 65 : 245 (V26.17), wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Magic Damage",
            field="ap_pct",
            stale=(70.0,) * 5,
            corrected=(60.0,) * 5,
            source=_RM480_SRC + " (ratio:Magic Damage:ap_pct)",
            note="Flay: 70 -> 60 pct AP (V26.17), wiki-measured",
        ),
    ),
    # The report's Kennen R cooldown row ([120, 120]) is out of scope here.
    ("Kennen", "R", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage Per Bolt",
            stale=(40.0, 75.0, 110.0),
            corrected=(40.0, 80.0, 120.0),
            source=_RM480_SRC + " (base:Magic Damage Per Bolt)",
            note="Slicing Maelstrom bolt: base 40 : 110 -> 40 : 120, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Magic Damage Per Bolt",
            field="ap_pct",
            stale=(22.5,) * 3,
            corrected=(25.0,) * 3,
            source=_RM480_SRC + " (ratio:Magic Damage Per Bolt:ap_pct)",
            note="Slicing Maelstrom bolt: 22.5 -> 25 pct AP, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Total Single-Target Damage",
            stale=(300.0, 562.5, 825.0),
            corrected=(300.0, 600.0, 900.0),
            source=_RM480_SRC + " (base:Total Single-Target Damage)",
            note="Slicing Maelstrom total (7.5 bolts): base 300 : 825 -> 300 : 900, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Total Single-Target Damage",
            field="ap_pct",
            stale=(168.75,) * 3,
            corrected=(187.5,) * 3,
            source=_RM480_SRC + " (ratio:Total Single-Target Damage:ap_pct)",
            note="Slicing Maelstrom total: 168.75 -> 187.5 pct AP, wiki-measured",
        ),
    ),
    ("Chogath", "E", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(20.0, 40.0, 60.0, 80.0, 100.0),
            corrected=(30.0, 50.0, 70.0, 90.0, 110.0),
            source=_RM480_SRC + " (base:Magic Damage)",
            note="Vorpal Spikes: base 20 : 100 -> 30 : 110, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Total Magic Damage",
            stale=(60.0, 120.0, 180.0, 240.0, 300.0),
            corrected=(90.0, 150.0, 210.0, 270.0, 330.0),
            source=_RM480_SRC + " (base:Total Magic Damage)",
            note="Vorpal Spikes total: base 60 : 300 -> 90 : 330, wiki-measured",
        ),
    ),
    # Bonus Magic Damage block only. The report's Total Enhanced Damage row
    # carries the BONUS series as its wiki column (a detector label collision),
    # so it is NOT a trustworthy target and that block is left alone.
    ("Cassiopeia", "E", 0): (
        AbilityBaseOverride(
            attribute="Bonus Magic Damage",
            stale=(20.0, 40.0, 60.0, 80.0, 100.0),
            corrected=(20.0, 45.0, 70.0, 95.0, 120.0),
            source=_RM480_SRC + " (base:Bonus Magic Damage)",
            note="Twin Fang bonus: base 20 : 100 -> 20 : 120, wiki-measured",
        ),
        AbilityBaseOverride(
            attribute="Bonus Magic Damage",
            field="ap_pct",
            stale=(55.0,) * 5,
            corrected=(45.0,) * 5,
            source=_RM480_SRC + " (ratio:Bonus Magic Damage:ap_pct)",
            note="Twin Fang bonus: 55 -> 45 pct AP, wiki-measured",
        ),
    ),
    # Mimic: Distortion is damage block index 3. The default
    # ``block_strategy="first"`` reads block 0 (Orb Magic Damage), so this entry
    # does NOT move default scoring. The report's other five LeBlanc R base rows
    # (Orb / Mark / Total / Application / Fracture) are out of scope here.
    ("Leblanc", "R", 0): (
        AbilityBaseOverride(
            attribute="Magic Damage",
            stale=(150.0, 300.0, 450.0),
            corrected=(150.0, 315.0, 480.0),
            source=_RM480_SRC + " (base:Magic Damage)",
            note="Mimic: Distortion: base 150 : 450 -> 150 : 480, wiki-measured; block 3, not read by default scoring",
        ),
        AbilityBaseOverride(
            attribute="Magic Damage",
            field="ap_pct",
            stale=(75.0,) * 3,
            corrected=(90.0,) * 3,
            source=_RM480_SRC + " (ratio:Magic Damage:ap_pct)",
            note="Mimic: Distortion: 75 -> 90 pct AP, wiki-measured; block 3, not read by default scoring",
        ),
    ),
}


def _validate_registry() -> None:
    """Refuse an ambiguous registry at import: one (attribute, field) per form."""
    for ident, entries in _ABILITY_BASE_OVERRIDES.items():
        seen: set[tuple[str, str]] = set()
        for entry in entries:
            pair = (entry.attribute, entry.field)
            if pair in seen:
                raise ValueError(f"duplicate override {pair} for {ident}")
            seen.add(pair)


_validate_registry()


def _matches(base: tuple[float, ...] | None, want: tuple[float, ...]) -> bool:
    """True when ``base``'s leading series equals ``want`` within ``_TOL``."""
    if base is None or len(base) < len(want):
        return False
    return all(abs(base[i] - want[i]) <= _TOL for i in range(len(want)))


def apply_base_overrides(cid: str, key: str, form):
    """Return ``form`` with its registered stale per-rank fields corrected.

    Each entry corrects ``entry.field`` (``base`` or, since RM-480, a ratio
    key) on the first block whose ``attribute`` matches.

    ALL-OR-NOTHING per form. Every entry is guarded first; if ANY entry's block
    is absent or no longer matches its ``stale`` series (the
    anti-double-correction guard), the WHOLE form is returned untouched and a
    WARNING is logged - a half-applied correction (say a new ratio on an old
    base) would be a number neither source ever published. For the A-03
    single-entry rows this is exactly the old behaviour.

    Returns the SAME object when nothing applies. Only the leading
    ``len(corrected)`` elements are replaced; any trailing elements (the
    concatenated per-level tail three of the six carry) are kept verbatim, so
    the array length is invariant.
    """
    entries = _ABILITY_BASE_OVERRIDES.get((cid, key, form.form_index))
    if not entries:
        return form
    blocks = list(form.damage_blocks)
    plan: list[tuple[int, AbilityBaseOverride]] = []
    for entry in entries:
        idx = next(
            (i for i, b in enumerate(blocks) if b.attribute == entry.attribute),
            None,
        )
        current = None if idx is None else getattr(blocks[idx], entry.field)
        if idx is None or not _matches(current, entry.stale):
            _LOG.warning(
                "RM-81 override for %s %s %r.%s no longer matches the extract "
                "(on disk %r, expected stale %r) - whole form SKIPPED. "
                "Re-verify the entry against %s.",
                cid,
                key,
                entry.attribute,
                entry.field,
                None if current is None else tuple(current[: len(entry.stale)]),
                entry.stale,
                entry.source,
            )
            return form
        plan.append((idx, entry))
    for idx, entry in plan:
        block = blocks[idx]
        current = getattr(block, entry.field)
        new_vals = entry.corrected + tuple(current[len(entry.corrected):])
        blocks[idx] = replace(block, **{entry.field: new_vals})
    return replace(form, damage_blocks=tuple(blocks))
