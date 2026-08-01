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


@dataclass(frozen=True)
class AbilityBaseOverride:
    """One corrected per-rank ``base`` series for one named damage block.

    ``attribute`` selects the block by its ``DamageBlock.attribute`` string
    (never by position - a Meraki re-extract can reorder blocks). ``stale`` is
    the series currently on disk and acts as the apply-guard; ``corrected`` is
    the wiki-true series. ``source`` MUST cite the ``DS_ABILITY_SHAPING_NOTES``
    line the numbers came from.
    """

    attribute: str
    stale: tuple[float, ...]
    corrected: tuple[float, ...]
    source: str
    note: str


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
}


def _matches(base: tuple[float, ...] | None, want: tuple[float, ...]) -> bool:
    """True when ``base``'s leading series equals ``want`` within ``_TOL``."""
    if base is None or len(base) < len(want):
        return False
    return all(abs(base[i] - want[i]) <= _TOL for i in range(len(want)))


def apply_base_overrides(cid: str, key: str, form):
    """Return ``form`` with its registered stale ``base`` heads corrected.

    Returns the SAME object when ``(cid, key, form.form_index)`` is not
    registered, when the named block is absent, or when the block no longer
    matches the entry's ``stale`` series (the anti-double-correction guard -
    logged at WARNING, because it means either the extract or the CDragon
    sidecar has moved and the entry needs re-verifying against the wiki).

    Only the leading ``len(corrected)`` elements are replaced; any trailing
    elements (the concatenated per-level tail three of the six carry) are kept
    verbatim, so the array length is invariant.
    """
    entries = _ABILITY_BASE_OVERRIDES.get((cid, key, form.form_index))
    if not entries:
        return form
    blocks = list(form.damage_blocks)
    changed = False
    for entry in entries:
        for i, block in enumerate(blocks):
            if block.attribute != entry.attribute:
                continue
            if not _matches(block.base, entry.stale):
                _LOG.warning(
                    "RM-81 base override for %s %s %r no longer matches the "
                    "extract (on disk %r, expected stale %r) - SKIPPED. "
                    "Re-verify the entry against %s.",
                    cid,
                    key,
                    entry.attribute,
                    None if block.base is None else block.base[: len(entry.stale)],
                    entry.stale,
                    entry.source,
                )
                break
            assert block.base is not None  # guaranteed by _matches
            new_base = entry.corrected + tuple(block.base[len(entry.corrected):])
            blocks[i] = replace(block, base=new_base)
            changed = True
            break
    if not changed:
        return form
    return replace(form, damage_blocks=tuple(blocks))
