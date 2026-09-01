# arch: RM-325 DS scorer mode-case parity | section=daemon_slayer | frozen=no
"""Scorer-side mode-string case parity (RM-325).

Root cause: item 244 made the rank-layer mode FILTER case-insensitive
(``MODE_MAP_ID.get(mode.upper())`` in ``_is_legal_in_mode`` /
``strip_arena_trinkets``) and left every SCORER case-SENSITIVE. Each
scorer gates its ARAM balance multiplier on a bare ``mode == "ARAM"``,
so a lowercase ``mode="aram"`` request got an ARAM-legal item pool
scored through a NON-ARAM multiplier path.

Two distinct wrong answers came out of that split, both measured on
Ziggs L13 build ("3020", "6653") at 16.17.1:

* ``apply_mode_modifiers=False`` (the DEFAULT, and the live-coach
  path's default): ``mode="aram"`` scored with ``mode_multiplier=1.0``
  instead of the champion's ``aramDamageDealt``.
* ``apply_mode_modifiers=True``: ``mode="aram"`` fell through the
  ``mode == "ARAM"`` gate into the ``elif apply_mode_modifiers`` wiki
  sidecar branch and scored 0.92 - the exact branch whose own comment
  at ``dps.py`` says "do NOT route ARAM through the wiki sidecar
  (avoids double-count)". The authoritative lolmath value is 0.87.

Why the item-244 test stayed green through this: its end-to-end case
``test_lowercase_aram_ranked_ids_match_uppercase`` compares ITEM IDS
ONLY. ``aramDamageDealt`` is a uniform scalar over every candidate, so
the ordering is preserved and the id list matches while every
``delta_dps`` differs. This module adds the missing consumer-side
assertions: multiplier parity per scorer, and per-index ``delta_dps``
parity through ``rank_items``.

Per the item-244 docstring the live coach dispatches UPPERCASE mode
strings, so this is internal-consistency hardening, not a live
coaching regression.

Discipline: every expected multiplier is READ FROM THE SNAPSHOT inside
the test (``lolmath.aram_modifiers`` / ``DataSnapshot.mode_modifier``),
never hardcoded. Each test that discriminates two source values first
asserts those two values actually DIFFER, so the probe cannot quietly
go vacuous when the patch data changes.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.ability_dps import compute_ability_dps
from agents.daemon_slayer.ability_hps import compute_ability_hps
from agents.daemon_slayer.beam import beam_search_build
from agents.daemon_slayer.burst import compute_burst_damage
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import compute_ehp
from agents.daemon_slayer.hps import compute_hps
from agents.daemon_slayer.rank import MODE_MAP_ID, rank_items

# The build the RM-325 finding was reproduced on against the live
# :8860 engine. Ziggs carries a non-1.0 aramDamageDealt AND a wiki
# sidecar dmg_dealt that DISAGREES with it, which is what makes the
# lowercase fall-through observable rather than coincidentally equal.
_CHAMP = "Ziggs"
_LEVEL = 13
_ITEMS = ("3020", "6653")

# Enchanter with non-1.0 aramHealing AND non-1.0 aramShielding, so the
# heal and shield halves are independently discriminating.
_HEAL_CHAMP = "Seraphine"


def _lolmath_aram(snap: DataSnapshot, champion_id: str) -> dict:
    """Authoritative per-champion ARAM balance block from the snapshot."""
    champ = snap.champion(champion_id)
    return ((champ.get("lolmath") or {}).get("aram_modifiers") or {})


class DpsModeCaseParityTests(unittest.TestCase):
    """``compute_dps`` must resolve the same ARAM multiplier for any case."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _dps(self, mode: str, apply_mode_modifiers: bool):
        return compute_dps(
            self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode=mode,
            target_armor=80.0, target_mr=50.0,
            apply_mode_modifiers=apply_mode_modifiers,
        )

    def test_source_values_differ_so_the_probe_is_not_vacuous(self) -> None:
        # Precondition, not a behaviour assertion: if lolmath and the wiki
        # sidecar ever agree for this champion, every assertion below would
        # pass no matter which branch ran. Fail loudly instead.
        lol = float(_lolmath_aram(self.snap, _CHAMP)["aramDamageDealt"])
        side = (self.snap.mode_modifier(_CHAMP, "aram") or {}).get("dmg_dealt")
        self.assertIsNotNone(
            side, f"{_CHAMP} has no wiki sidecar dmg_dealt - pick another probe"
        )
        self.assertNotEqual(
            lol, float(side),
            f"{_CHAMP} lolmath aramDamageDealt == sidecar dmg_dealt "
            f"({lol}); this probe can no longer tell the branches apart",
        )

    def test_lowercase_aram_multiplier_matches_uppercase_default_flags(self) -> None:
        lo = self._dps("aram", False)
        up = self._dps("ARAM", False)
        expected = float(_lolmath_aram(self.snap, _CHAMP)["aramDamageDealt"])
        self.assertEqual(
            lo.mode_multiplier, up.mode_multiplier,
            "mode='aram' scored with a different multiplier than 'ARAM'",
        )
        # Equality alone is not enough: both spellings collapsing onto the
        # WRONG branch would also be "equal". Pin the shared value to the
        # authoritative lolmath number.
        self.assertEqual(up.mode_multiplier, expected)
        self.assertEqual(lo.mode_multiplier, expected)

    def test_lowercase_aram_multiplier_matches_uppercase_sidecar_on(self) -> None:
        # The exact live repro: apply_mode_modifiers=True is where the
        # lowercase request reached the wiki sidecar branch.
        lo = self._dps("aram", True)
        up = self._dps("ARAM", True)
        expected = float(_lolmath_aram(self.snap, _CHAMP)["aramDamageDealt"])
        sidecar = float(self.snap.mode_modifier(_CHAMP, "aram")["dmg_dealt"])
        self.assertEqual(lo.mode_multiplier, up.mode_multiplier)
        self.assertEqual(lo.mode_multiplier, expected)
        self.assertNotEqual(
            lo.mode_multiplier, sidecar,
            "lowercase ARAM routed through the wiki sidecar - the branch "
            "dps.py's own comment forbids for ARAM (double-count)",
        )

    def test_mixed_case_aram_multiplier_matches_uppercase(self) -> None:
        mixed = self._dps("Aram", True)
        up = self._dps("ARAM", True)
        self.assertEqual(mixed.mode_multiplier, up.mode_multiplier)

    def test_lowercase_aram_weighted_dps_matches_uppercase(self) -> None:
        # The multiplier is the mechanism; weighted_dps is the artifact a
        # consumer actually reads. Assert the downstream number moved too.
        lo = self._dps("aram", False)
        up = self._dps("ARAM", False)
        self.assertAlmostEqual(lo.weighted_dps, up.weighted_dps, places=6)


class EhpModeCaseParityTests(unittest.TestCase):
    """``compute_ehp`` mode multiplier is ``aramDamageTaken``, not 1.0."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lowercase_aram_matches_uppercase(self) -> None:
        expected = float(_lolmath_aram(self.snap, _CHAMP)["aramDamageTaken"])
        self.assertNotEqual(
            expected, 1.0,
            f"{_CHAMP} aramDamageTaken is 1.0 - probe cannot discriminate",
        )
        lo = compute_ehp(self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode="aram")
        up = compute_ehp(self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode="ARAM")
        self.assertEqual(lo.mode_multiplier, up.mode_multiplier)
        self.assertEqual(lo.mode_multiplier, expected)


class BurstModeCaseParityTests(unittest.TestCase):
    """``compute_burst_damage`` mode multiplier is ``aramDamageDealt``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lowercase_aram_matches_uppercase(self) -> None:
        expected = float(_lolmath_aram(self.snap, _CHAMP)["aramDamageDealt"])
        self.assertNotEqual(expected, 1.0)
        lo = compute_burst_damage(
            self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode="aram",
            target_armor=80.0, target_mr=50.0,
        )
        up = compute_burst_damage(
            self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode="ARAM",
            target_armor=80.0, target_mr=50.0,
        )
        self.assertEqual(lo.mode_multiplier, up.mode_multiplier)
        self.assertEqual(lo.mode_multiplier, expected)


class AbilityDpsModeCaseParityTests(unittest.TestCase):
    """``compute_ability_dps`` mode multiplier is ``aramDamageDealt``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lowercase_aram_matches_uppercase(self) -> None:
        expected = float(_lolmath_aram(self.snap, _CHAMP)["aramDamageDealt"])
        self.assertNotEqual(expected, 1.0)
        lo = compute_ability_dps(
            self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode="aram",
            target_armor=80.0, target_mr=50.0,
        )
        up = compute_ability_dps(
            self.snap, _CHAMP, _LEVEL, item_ids=list(_ITEMS), mode="ARAM",
            target_armor=80.0, target_mr=50.0,
        )
        self.assertEqual(lo.mode_multiplier, up.mode_multiplier)
        self.assertEqual(lo.mode_multiplier, expected)


class HpsModeCaseParityTests(unittest.TestCase):
    """``compute_hps`` heal/shield multipliers are ARAM-gated per side."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lowercase_aram_matches_uppercase(self) -> None:
        aram = _lolmath_aram(self.snap, _HEAL_CHAMP)
        exp_heal = float(aram["aramHealing"])
        exp_shield = float(aram["aramShielding"])
        self.assertNotEqual((exp_heal, exp_shield), (1.0, 1.0))
        lo = compute_hps(self.snap, _HEAL_CHAMP, _LEVEL, mode="aram")
        up = compute_hps(self.snap, _HEAL_CHAMP, _LEVEL, mode="ARAM")
        self.assertEqual((lo.heal_mult, lo.shield_mult),
                         (up.heal_mult, up.shield_mult))
        self.assertEqual((lo.heal_mult, lo.shield_mult), (exp_heal, exp_shield))


class AbilityHpsModeCaseParityTests(unittest.TestCase):
    """``compute_ability_hps`` heal/shield multipliers are ARAM-gated."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_lowercase_aram_matches_uppercase(self) -> None:
        aram = _lolmath_aram(self.snap, _HEAL_CHAMP)
        exp_heal = float(aram["aramHealing"])
        exp_shield = float(aram["aramShielding"])
        self.assertNotEqual((exp_heal, exp_shield), (1.0, 1.0))
        lo = compute_ability_hps(self.snap, _HEAL_CHAMP, _LEVEL, mode="aram")
        up = compute_ability_hps(self.snap, _HEAL_CHAMP, _LEVEL, mode="ARAM")
        self.assertEqual((lo.heal_mult, lo.shield_mult),
                         (up.heal_mult, up.shield_mult))
        self.assertEqual((lo.heal_mult, lo.shield_mult), (exp_heal, exp_shield))


class RankDeltaDpsCaseParityTests(unittest.TestCase):
    """Per-index ``delta_dps`` parity - the assertion item 244 was missing.

    ``test_rank_mode_case_insensitive_item244`` compares item IDS only.
    A uniform scalar multiplier preserves ordering, so that test passes
    even while every delta is scaled by the wrong factor.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, mode: str):
        return rank_items(
            self.snap, _CHAMP, _LEVEL, current_item_ids=list(_ITEMS),
            mode=mode, target_armor=80.0, target_mr=50.0, top_n=20,
        )

    def test_lowercase_aram_delta_dps_matches_uppercase_per_index(self) -> None:
        lo = self._rank("aram")
        up = self._rank("ARAM")
        self.assertGreater(len(up.ranked), 0)
        self.assertEqual(
            [r.item_id for r in lo.ranked], [r.item_id for r in up.ranked],
            "id ordering diverged - the item-244 filter parity regressed",
        )
        for i, (a, b) in enumerate(zip(lo.ranked, up.ranked)):
            self.assertAlmostEqual(
                a.delta_dps, b.delta_dps, places=6,
                msg=(
                    f"rank index {i} ({b.item_id} {b.item_name}): "
                    f"lowercase delta_dps {a.delta_dps:.4f} != uppercase "
                    f"{b.delta_dps:.4f} - the pool is ARAM-legal but the "
                    f"score is not ARAM-scored"
                ),
            )

    def test_lowercase_aram_baseline_dps_matches_uppercase(self) -> None:
        self.assertAlmostEqual(
            self._rank("aram").baseline_dps,
            self._rank("ARAM").baseline_dps,
            places=6,
        )


class ModeNoteProvenanceTests(unittest.TestCase):
    """The lowercase-mode note must name the map id that was applied.

    Pre-RM-325 ``rank_items(mode="aram").notes[0]`` read "mode=aram not
    in MODE_MAP_ID - no per-mode item filter applied", which item 244
    made untrue - the filter IS applied at lowercase. A false
    provenance line is worse than none.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def test_rank_lowercase_note_names_the_resolved_map_id(self) -> None:
        r = rank_items(
            self.snap, _CHAMP, _LEVEL, mode="aram",
            target_armor=80.0, top_n=5,
        )
        self.assertIn(f"maps id {MODE_MAP_ID['ARAM']}", r.notes[0])
        self.assertNotIn("not in MODE_MAP_ID", r.notes[0])

    def test_rank_mixed_case_note_names_the_resolved_map_id(self) -> None:
        r = rank_items(
            self.snap, _CHAMP, _LEVEL, mode="Aram",
            target_armor=80.0, top_n=5,
        )
        self.assertIn(f"maps id {MODE_MAP_ID['ARAM']}", r.notes[0])

    def test_rank_unknown_mode_still_notes_the_no_filter_fallback(self) -> None:
        # Scope fence: RM-325 does NOT introduce mode-string rejection.
        # An unrecognised mode keeps its documented allow-all contract and
        # keeps saying so.
        r = rank_items(
            self.snap, _CHAMP, _LEVEL, mode="NOT_A_REAL_MODE",
            target_armor=80.0, top_n=5,
        )
        self.assertIn("not in MODE_MAP_ID", r.notes[0])

    def test_beam_lowercase_note_names_the_resolved_map_id(self) -> None:
        r = beam_search_build(
            self.snap, _CHAMP, _LEVEL, current_item_ids=list(_ITEMS),
            mode="aram", target_armor=80.0, slot_count=3,
            beam_width=2, top_n=2,
        )
        self.assertIn(f"maps id {MODE_MAP_ID['ARAM']}", r.notes[0])
        self.assertNotIn("not in MODE_MAP_ID", r.notes[0])


if __name__ == "__main__":
    unittest.main()
