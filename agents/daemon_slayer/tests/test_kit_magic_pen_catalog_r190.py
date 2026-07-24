"""R190 slice B - CHAMPION-KIT-INTRINSIC magic-penetration catalog guard.

The item half of this axis is closed and already machine-guarded: R153
swept flat magic pen (``test_magic_pen_flat_catalog_r153.py``) and
R160/R161 swept percent pen on both axes
(``test_pen_pct_catalog_r160.py``), both now exemption-free under
doctrine B (an Arena mirror's OWN explicit DDragon stat line wins over
its SR twin's coefficient). This module guards the UNSWEPT half - the
magic penetration and magic-resist shred that champions carry in their
KITS rather than in an item.

WHY ``ITEM_EFFECTS`` IS THE SOLE ITEM CREDIT PATH (re-measured for R190
against the shipped 16.14.1 data, not carried forward from a doc):

  * ``stats.ITEM_STAT_KEY_MAP`` maps DDragon stat keys to canonical
    engine stats and carries NO penetration key of any kind, so a
    magnitude stated only in a ``stats`` block could never be read.
  * The vendored Meraki snapshot
    ``data/daemon_slayer/16.14.1/items_meraki.json`` DOES carry
    ``magicPenetration`` sub-blocks (921 penetration-family blocks
    across its 320 items, nested under ``passives[*].stats``), but
    every single one of those fields is 0.0 - including Void Staff
    (3135), whose 40% percent pen is real and shipped. Meraki's
    structured penetration fields are uniformly zeroed placeholders on
    this patch, which is exactly why ``ITEM_EFFECTS`` has to be the
    only item credit path. The Meraki test below pins that measurement
    so a future extract that starts populating the field is a loud
    event, not a silent one.

WHY THE KIT HALF IS A SEPARATE AXIS ENTIRELY:

  ``effects.effective_target_mr(target_mr, effects)`` accepts ONLY
  ``ItemEffect`` objects (effects.py:631). There is no champion-id
  parameter and no kit lane anywhere in that pipeline, so
  kit-intrinsic magic penetration NEVER enters the damage math. It is
  scored only on the standalone opt-in anti-tank axis,
  ``antitank._ANTITANK_REGISTRY``, whose ``SHRED`` / ``PERCENT_PEN``
  rows carry a 0..1 reliability magnitude rather than an MR number.
  That registry is SELECTIVE by design, not exhaustive - which is
  precisely the drift risk this module exists to catch.

WHAT THIS MODULE DOES:

  It re-derives the swept population from the shipped ability snapshot
  ``data/daemon_slayer/<patch>/champion_abilities.json`` on EVERY run,
  using a deliberately WIDE net: any champion spell or passive form
  whose ``effects_descriptions`` prose or whose structured
  ``damage_blocks`` attribute label so much as MENTIONS "magic resist"
  or "magic pen". Every mention is then pinned into exactly one of two
  buckets - a target-side grant, or a non-grant (a self/ally resist
  buff, a resist-scaling ratio, or an interaction note). A future
  champion authored the same way lands in neither bucket and fails RED
  here instead of silently reading 0.0 on the anti-tank axis.

R190 OUTCOME - NOT saturated. One real gap:

  Annie R "Summon: Tibbers" states "Passive: Annie gains magic
  penetration" and ships a STRUCTURED block - attribute "Magic
  Penetration", values [15, 17.5, 20], units all "%" - and Annie is
  absent from ``_ANTITANK_REGISTRY`` entirely (and from every other
  penetration lane in the engine; ``grep -rn "magic_pen"`` over
  ``agents/daemon_slayer/*.py`` reaches only ``ItemEffect`` fields,
  ``boot_utility``'s Sorcerer's-Shoes tag, and the ``ehp`` enemy-pen
  knobs). This module PINS that gap as a known-uncredited row rather
  than fixing it - crediting a registry row is an engine change and
  this slice is test-only. When a later slice adds the row, the pin
  below flips RED and forces the update, which is the intended
  behavior in both directions.

  The other 13 kit grants on this axis are all already credited.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from agents.daemon_slayer._effects_types import ItemEffect
from agents.daemon_slayer.antitank import _ANTITANK_REGISTRY, compute_antitank
from agents.daemon_slayer.effects import effective_target_mr
from agents.daemon_slayer.stats import ITEM_STAT_KEY_MAP

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PATCH_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

_SLOTS = ("P", "Q", "W", "E", "R")

# The wide net. Deliberately NOT a clever "is this a shred" regex - a
# bare mention is enough to enter the swept population, and the pinned
# buckets below do the classification. A narrower pattern would let a
# newly-authored phrasing slip through unclassified, which is the exact
# failure mode this guard is built to prevent (Mordekaiser R writes
# "magic resist", not "magic resistance", and every reduction-verb
# pattern tried during the R190 sweep missed it by word distance).
_MAGIC_SIDE_MENTION_RE = re.compile(r"(?i)magic resist|magic pen")

# Structured attribute labels that state a magic-side penetration or
# resist-reduction magnitude. "Resistances Reduction" covers both axes
# at once (Briar Q / Corki E / Kog'Maw Q), so it belongs to the magic
# side as well as the physical one.
_MAGIC_SIDE_ATTRIBUTE_RE = re.compile(
    r"(?i)magic penetration|magic resist(?:ance)? reduction"
    r"|mr reduction|resistances reduction"
)


# --------------------------------------------------------------------------
# The pinned population. Keys are (champion_id, slot); DDragon champion
# ids (MonkeyKing, KSante) exactly as the snapshot writes them.
# --------------------------------------------------------------------------

# Target-side grants: the form lowers an ENEMY's magic resist, or grants
# the champion magic penetration. Each value is the verbatim mechanic
# and its magnitude as the 16.14.1 snapshot states it.
_KIT_MAGIC_PEN_GRANTS: dict[tuple[str, str], str] = {
    ("Annie", "R"): "gains magic penetration - 15 / 17.5 / 20 percent",
    ("Briar", "Q"): "reduces their armor and magic resistance - 10..20 percent",
    ("Corki", "E"): "each stack reduces the target's armor and magic resistance"
                    " - 3..5 flat per stack, 12..20 total",
    ("Evelynn", "W"): "inflicts magic resistance reduction - 35..45 percent",
    ("Jayce", "R"): "reduce the target's armor and magic resistance"
                    " - 10 / 15 / 20 / 25 percent (based on level)",
    ("Karthus", "W"): "inflicted with 25 percent magic resistance reduction",
    ("Kayle", "Q"): "inflicted with 15 percent reduced armor and magic resistance",
    ("KogMaw", "Q"): "reduces their armor and magic resistance - 16..32 percent",
    ("Mordekaiser", "E"): "gains magic penetration - 5 / 7.5 / 10 / 12.5 / 15 percent",
    ("Mordekaiser", "R"): "reducing their ... armor, magic resist ... by 10 percent",
    ("Rell", "P"): "reduce the target's armor and magic resistance by 3 percent"
                   " for 5 seconds, stacking to 15 percent",
    ("Rumble", "E"): "inflicting them with magic resistance reduction"
                     " - 10..18 percent, 20..36 stacked, 30..54 enhanced",
    ("Trundle", "R"): "steals 40 percent of their current armor and magic resistance",
    ("Zoe", "E"): "inflicted with 30 percent magic resistance reduction",
}

# Every other mention. None of these lower an enemy's MR: they grant MR
# to self or an ally, scale damage OFF a resist stat, reduce the
# CASTER's own resists, or are pure interaction prose. Kept explicit so
# a re-authored tooltip that turns one of them into a shred cannot slip
# past by already being "known".
_NON_GRANT_MAGIC_SIDE_MENTIONS: dict[tuple[str, str], str] = {
    ("Anivia", "P"): "self bonus MR while in egg",
    ("Azir", "P"): "Sun Disc structure loses its own resists when Azir is away",
    ("Braum", "W"): "self and ally bonus MR",
    ("Briar", "R"): "self bonus MR from Hematomania",
    ("Camille", "P"): "shield sizing reads Camille's OWN current armor and MR",
    ("Galio", "P"): "damage scales off Galio's own bonus MR",
    ("Garen", "W"): "self bonus MR per Courage stack",
    ("Gwen", "W"): "self bonus MR inside the mist",
    ("Hecarim", "W"): "self bonus MR while Spirit of Dread is active",
    ("Illaoi", "E"): "the spawned Spirit copies the target's armor and MR",
    ("Jax", "R"): "self bonus MR per champion hit",
    ("KSante", "P"): "damage scales off K'Sante's own bonus MR",
    ("KSante", "R"): "K'Sante's OWN base resists are cut entering All Out;"
                     " the penetration he gains is bonus-ARMOR pen, not magic",
    ("Kennen", "R"): "self bonus MR during the storm",
    ("Kled", "P"): "self bonus MR while Dismounted",
    ("Leona", "W"): "self bonus MR and flat damage reduction",
    ("Nasus", "R"): "self bonus MR during Fury of the Sands",
    ("Olaf", "R"): "self bonus MR passive",
    ("Orianna", "E"): "the Ball grants bonus MR to the unit it is attached to",
    ("Ornn", "P"): "Ornn amplifies his OWN bonus MR by 10 percent",
    ("Pantheon", "E"): "self bonus MR after the recast",
    ("Poppy", "W"): "self total-MR multiplier",
    ("Rammus", "P"): "bonus AD scales off Rammus's own total MR",
    ("Rammus", "W"): "self bonus MR and a reflect that scales off total MR",
    ("Rell", "W"): "self bonus MR while Dismounted",
    ("Sejuani", "P"): "self bonus MR from Fury of the North",
    ("Shyvana", "P"): "self bonus MR per elemental drake",
    ("Singed", "R"): "self bonus MR from Insanity Potion",
}

# The one swept grant with no engine credit anywhere. See the module
# docstring - fixing it is an engine change, out of this slice's scope.
_KNOWN_UNCREDITED_GRANTS: dict[tuple[str, str], str] = {
    ("Annie", "R"): "Annie has no _ANTITANK_REGISTRY entry at all, so her"
                    " 15 / 17.5 / 20 percent kit magic pen reads 0.0 on the"
                    " anti-tank axis. R190 slice B records this as a FUTURE"
                    " engine finding; it does not credit it.",
}

# Registry kinds that represent lowering a target's resists.
_RESIST_LOWERING_KINDS = frozenset({"SHRED", "PERCENT_PEN"})

# ``_ANTITANK_REGISTRY`` rows carry NO axis field - SHRED / PERCENT_PEN
# are axis-agnostic, so a physical-side row is indistinguishable from a
# magic-side one by kind alone. These non-grant slots legitimately carry
# a resist-lowering row for a PHYSICAL-side reason and are therefore
# exempt from the "a non-grant must not be registered as a shred" rule.
# Pinned individually so the exemption cannot quietly widen.
_NON_GRANT_WITH_PHYSICAL_SIDE_ROW: dict[tuple[str, str], str] = {
    ("KSante", "R"): "All Out grants 50 percent bonus-ARMOR penetration."
                     " The registry PERCENT_PEN row is that physical-side"
                     " credit; K'Sante's magic-side mention is the cut to"
                     " his OWN base MR, which is not a target shred.",
}


# --------------------------------------------------------------------------
# Derivation helpers - re-run against the shipped snapshot every test run.
# --------------------------------------------------------------------------

def _current_patch() -> str:
    return (_PATCH_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _abilities() -> dict:
    path = _PATCH_ROOT / _current_patch() / "champion_abilities.json"
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def _form_prose(form: dict) -> str:
    return " | ".join(form.get("effects_descriptions") or [])


def _form_attribute_labels(form: dict) -> tuple[str, ...]:
    return tuple(
        (block.get("attribute") or "")
        for block in (form.get("damage_blocks") or [])
    )


def _swept_magic_side_mentions() -> dict[tuple[str, str], list[dict]]:
    """(champion, slot) -> the forms mentioning magic resist / magic pen."""
    found: dict[tuple[str, str], list[dict]] = {}
    for champion, slots in _abilities().items():
        for slot in _SLOTS:
            for form in slots.get(slot) or []:
                haystack = _form_prose(form) + " || " + " ; ".join(
                    _form_attribute_labels(form)
                )
                if _MAGIC_SIDE_MENTION_RE.search(haystack):
                    found.setdefault((champion, slot), []).append(form)
    return found


def _structured_magic_side_blocks() -> dict[tuple[str, str], list[dict]]:
    """(champion, slot) -> damage_blocks whose attribute states a magnitude."""
    found: dict[tuple[str, str], list[dict]] = {}
    for champion, slots in _abilities().items():
        for slot in _SLOTS:
            for form in slots.get(slot) or []:
                for block in form.get("damage_blocks") or []:
                    if _MAGIC_SIDE_ATTRIBUTE_RE.search(block.get("attribute") or ""):
                        found.setdefault((champion, slot), []).append(block)
    return found


def _registry_rows(champion: str, slot: str) -> tuple:
    return tuple(
        entry
        for entry in _ANTITANK_REGISTRY.get(champion, ())
        if entry.source == slot
    )


class R190KitMagicPenSweepTests(unittest.TestCase):
    """Durable guard - the swept set is re-derived from shipped data."""

    def setUp(self) -> None:
        self.swept = _swept_magic_side_mentions()

    def test_pinned_buckets_are_disjoint(self) -> None:
        overlap = set(_KIT_MAGIC_PEN_GRANTS) & set(_NON_GRANT_MAGIC_SIDE_MENTIONS)
        self.assertEqual(overlap, set())

    def test_known_uncredited_is_a_subset_of_the_grants(self) -> None:
        self.assertTrue(
            set(_KNOWN_UNCREDITED_GRANTS).issubset(set(_KIT_MAGIC_PEN_GRANTS))
        )

    def test_sweep_matches_the_pinned_population(self) -> None:
        # Drift in EITHER direction fails: a new champion form that
        # mentions magic resist lands here unclassified, and a form that
        # loses its mention (a rework, a patch removal) is just as loud.
        pinned = set(_KIT_MAGIC_PEN_GRANTS) | set(_NON_GRANT_MAGIC_SIDE_MENTIONS)
        derived = set(self.swept)
        self.assertEqual(
            sorted(derived - pinned),
            [],
            "unclassified magic-side kit mention(s) - classify as a grant"
            " or a non-grant in test_kit_magic_pen_catalog_r190.py",
        )
        self.assertEqual(
            sorted(pinned - derived),
            [],
            "pinned magic-side kit mention(s) no longer present in the"
            " shipped champion_abilities.json - retire the pin",
        )

    def test_every_pinned_grant_still_reads_as_a_magic_side_mention(self) -> None:
        for key in sorted(_KIT_MAGIC_PEN_GRANTS):
            with self.subTest(champion=key[0], slot=key[1]):
                self.assertIn(key, self.swept)

    def test_credited_grants_carry_a_resist_lowering_registry_row(self) -> None:
        # The whole point of the axis: a kit shred / pen that the
        # anti-tank registry does not carry scores zero. Every swept
        # grant except the pinned known gap must have a row.
        for key, mechanic in sorted(_KIT_MAGIC_PEN_GRANTS.items()):
            if key in _KNOWN_UNCREDITED_GRANTS:
                continue
            champion, slot = key
            with self.subTest(champion=champion, slot=slot):
                rows = _registry_rows(champion, slot)
                self.assertTrue(
                    rows,
                    f"{champion} {slot} states '{mechanic}' but has no"
                    " _ANTITANK_REGISTRY row on that slot",
                )
                kinds = {row.kind for row in rows}
                self.assertTrue(
                    kinds & _RESIST_LOWERING_KINDS,
                    f"{champion} {slot} is registered as {sorted(kinds)},"
                    " none of which lowers a target's resists",
                )
                for row in rows:
                    if row.kind in _RESIST_LOWERING_KINDS:
                        self.assertGreater(row.magnitude, 0.0)

    def test_credited_grants_flip_shreds_resist_on_the_scorer(self) -> None:
        # Assert on the computed result, not on the registry literal:
        # every credited grant champion must actually report
        # shreds_resist through compute_antitank.
        for key in sorted(_KIT_MAGIC_PEN_GRANTS):
            if key in _KNOWN_UNCREDITED_GRANTS:
                continue
            champion, slot = key
            with self.subTest(champion=champion, slot=slot):
                result = compute_antitank(champion)
                self.assertTrue(result.shreds_resist)
                self.assertGreater(result.antitank_score, 0.0)

    def test_non_grant_mentions_are_not_credited_as_magic_side_shred(self) -> None:
        # A self / ally MR buff or a resist-scaling ratio must never be
        # mistaken for a shred. Champions in this bucket may still carry
        # a resist-lowering row on a DIFFERENT slot (Rell P shreds while
        # Rell W is a self buff), so this asserts per-slot.
        for key, why in sorted(_NON_GRANT_MAGIC_SIDE_MENTIONS.items()):
            champion, slot = key
            if (champion, slot) in _KIT_MAGIC_PEN_GRANTS:
                continue
            if (champion, slot) in _NON_GRANT_WITH_PHYSICAL_SIDE_ROW:
                continue
            with self.subTest(champion=champion, slot=slot):
                for row in _registry_rows(champion, slot):
                    self.assertNotIn(
                        row.kind,
                        _RESIST_LOWERING_KINDS,
                        f"{champion} {slot} is a non-grant ({why}) but is"
                        f" registered as {row.kind}",
                    )

    def test_physical_side_exemptions_are_still_needed(self) -> None:
        # A dead exemption is drift too - if the physical-side row goes
        # away, the exemption must be retired rather than left standing.
        for key, why in sorted(_NON_GRANT_WITH_PHYSICAL_SIDE_ROW.items()):
            champion, slot = key
            with self.subTest(champion=champion, slot=slot):
                self.assertIn(key, _NON_GRANT_MAGIC_SIDE_MENTIONS)
                kinds = {row.kind for row in _registry_rows(champion, slot)}
                self.assertTrue(
                    kinds & _RESIST_LOWERING_KINDS,
                    f"{champion} {slot} exemption ({why}) is stale - no"
                    " resist-lowering row remains on that slot",
                )


class R190KnownUncreditedGapTests(unittest.TestCase):
    """Annie R - the one real gap R190 slice B measured."""

    def test_annie_r_states_structured_percent_magic_pen(self) -> None:
        blocks = _structured_magic_side_blocks().get(("Annie", "R"))
        self.assertTrue(blocks, "Annie R lost its structured magic-pen block")
        pen = [b for b in blocks if b.get("attribute") == "Magic Penetration"]
        self.assertEqual(len(pen), 1)
        modifiers = pen[0].get("raw_modifiers") or []
        self.assertEqual(len(modifiers), 1)
        values = modifiers[0].get("values") or []
        units = modifiers[0].get("units") or []
        self.assertEqual([float(v) for v in values], [15.0, 17.5, 20.0])
        self.assertEqual(set(units), {"%"})

    def test_annie_is_absent_from_the_antitank_registry(self) -> None:
        # Pinned as a KNOWN GAP. When a later slice credits Annie this
        # fails, which is the intended forcing function - update the pin
        # and move the row into the credited population above.
        self.assertNotIn("Annie", _ANTITANK_REGISTRY)
        self.assertEqual(_registry_rows("Annie", "R"), ())
        result = compute_antitank("Annie")
        self.assertFalse(result.shreds_resist)
        self.assertEqual(result.antitank_score, 0.0)

    def test_the_uncredited_magnitude_is_materially_large(self) -> None:
        # What the gap is worth, expressed through the ONE consumer that
        # can express it: an equivalent 20 percent ITEM percent-pen
        # source strips 20 MR off a 100-MR target. Annie's kit reaches
        # none of that, because effective_target_mr has no kit lane.
        equivalent = ItemEffect(
            item_id="R190-annie-r-equivalent",
            name="Annie R kit magic pen (rank 3, 20 percent)",
            magic_pen_pct=0.20,
        )
        self.assertAlmostEqual(
            effective_target_mr(100.0, [equivalent]), 80.0, places=3
        )


class R190KitAxisSeparationTests(unittest.TestCase):
    """Kit-intrinsic pen never reaches the damage math - pin the seam."""

    def test_effective_target_mr_is_a_no_op_without_item_effects(self) -> None:
        self.assertAlmostEqual(effective_target_mr(100.0, []), 100.0, places=3)

    def test_effective_target_mr_only_reads_item_effect_fields(self) -> None:
        # Passing anything without the ItemEffect magic-side fields is an
        # AttributeError, which is the structural proof that there is no
        # champion / kit lane into this function.
        with self.assertRaises(AttributeError):
            effective_target_mr(100.0, ["Mordekaiser"])

    def test_mordekaiser_kit_pen_scores_on_the_axis_but_not_on_mr(self) -> None:
        # Mordekaiser E is the canonical credited kit PERCENT_PEN row.
        # It moves the anti-tank score and nothing else: the MR pipeline
        # is untouched by his kit.
        result = compute_antitank("Mordekaiser")
        self.assertTrue(result.shreds_resist)
        self.assertGreater(result.antitank_score, 0.0)
        self.assertAlmostEqual(effective_target_mr(100.0, []), 100.0, places=3)

    def test_registry_magnitudes_are_reliability_not_mr_numbers(self) -> None:
        # Guards the unit confusion directly: a resist-lowering row's
        # magnitude is a 0..1 reliability weight. A future edit that
        # pastes a raw percent (e.g. 15 for Mordekaiser E) fails here.
        for champion, slot in sorted(_KIT_MAGIC_PEN_GRANTS):
            for row in _registry_rows(champion, slot):
                if row.kind not in _RESIST_LOWERING_KINDS:
                    continue
                with self.subTest(champion=champion, slot=slot):
                    self.assertGreater(row.magnitude, 0.0)
                    self.assertLessEqual(row.magnitude, 1.0)


class R190ItemPathIsTheOnlyItemCreditPathTests(unittest.TestCase):
    """Re-measured on every run - the reason ITEM_EFFECTS stands alone."""

    def test_item_stat_key_map_carries_no_magic_pen_key(self) -> None:
        for ddragon_key, (canonical, _kind) in ITEM_STAT_KEY_MAP.items():
            with self.subTest(ddragon_key=ddragon_key):
                self.assertNotIn("pen", canonical.lower())
                self.assertNotIn("penetration", ddragon_key.lower())

    def test_no_meraki_item_states_a_structured_magic_pen_stat(self) -> None:
        path = _PATCH_ROOT / _current_patch() / "items_meraki.json"
        items = json.loads(path.read_text(encoding="utf-8"))["items"]
        self.assertGreater(len(items), 0)

        blocks: list[tuple[str, dict]] = []

        def walk(node, item_id: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "magicPenetration" and isinstance(value, dict):
                        blocks.append((item_id, value))
                    walk(value, item_id)
            elif isinstance(node, list):
                for value in node:
                    walk(value, item_id)

        for item_id, item in items.items():
            walk(item, item_id)

        self.assertTrue(
            blocks,
            "Meraki snapshot no longer carries magicPenetration blocks -"
            " re-measure before trusting the ITEM_EFFECTS-only claim",
        )
        for item_id, block in blocks:
            with self.subTest(item_id=item_id):
                self.assertEqual(
                    [v for v in block.values() if v],
                    [],
                    f"{item_id} now states a structured magicPenetration"
                    " value - the ITEM_EFFECTS-only credit path assumption"
                    " needs re-deriving",
                )

    def test_void_staff_percent_pen_lives_only_in_item_effects(self) -> None:
        # The concrete case: Void Staff's 40 percent is real and shipped,
        # yet its Meraki structured field is zero. Prove the credit comes
        # from ITEM_EFFECTS by exercising the consumer.
        from agents.daemon_slayer._effects_data import ITEM_EFFECTS

        void_staff = ITEM_EFFECTS.get("3135")
        self.assertIsNotNone(void_staff)
        self.assertGreater(void_staff.magic_pen_pct, 0.0)
        self.assertLess(
            effective_target_mr(100.0, [void_staff]),
            100.0,
        )


if __name__ == "__main__":
    unittest.main()
