# arch: RM-329 EHP-family mode-provenance notes | section=daemon_slayer | frozen=no
"""Mode-provenance notes on the EHP-family scorers (RM-329).

``/rank`` has always answered the question "which map did you filter
against?" in its own ``notes``::

    mode=ARAM -> maps id 12
    mode=ARAMM not in MODE_MAP_ID - no per-mode item filter applied

and ``/ehp`` inherits ``engine.py``'s ``mode=X - modifier table not
plugged in for this mode`` through ``build_champion``. The EHP-family
scorers carried NEITHER. A typo'd mode (``ARAMM``) therefore returned a
pool built with NO per-mode legality filter - map-illegal items leaking
into a mode-legal answer - and nothing in the payload said so.

Nothing pinned it because
``test_rank_mode_legality_p1l23.py::test_rank_items_garbage_mode_returns_result_with_note``
covers exactly ONE of the eight scorers despite its name promising the
contract (``reference_guard_domain_narrower_than_its_name``).

SCOPE OF THIS MODULE (slice S1): the three routes whose scorers live in
``ehp.py`` / ``hps.py`` -

  * ``/rank-tank``      -> ``ehp.rank_items_by_ehp``
  * ``/rank-enchanter`` -> ``hps.rank_items_by_hps``
  * ``/hps``            -> ``hps.compute_hps``

The other four routes named in RM-329 (``/rank-bruiser``,
``/rank-assassin``, ``/rank-mage``, ``/rank-onhit``) are backed by ``hybrid.py`` /
``burst.py`` / ``ability_dps.py`` / ``onhit_dps.py``, which this slice
does not own. ``rank.mode_filter_note`` is the shared helper they each
need a one-line call to.

WHAT THE NOTES ARE ALLOWED TO SAY. ``test_mode_case_scorer_parity_rm325.py``
``ModeNoteProvenanceTests`` argues, correctly, that "a false provenance
line is worse than none" - the pre-RM-325 note claimed no filter had been
applied when item 244's case-insensitive filter had in fact applied it.
So each note here is pinned to a thing its own module provably does:

  * the two RANKERS call ``rank._filter_candidates`` -> ``_is_legal_in_mode``,
    so they may report the map-id verdict, and must report the RESOLVED
    one (``mode="aram"`` names map 12, it does NOT say "not in MODE_MAP_ID").
  * ``compute_hps`` filters NO pool - it scores a supplied build - so it
    says nothing about item legality. It reports only that its own
    heal/shield modifier table (``_aram_heal_shield_modifiers``, ARAM-only,
    SR being the unmodified baseline) has no row for the mode.

The notes are ADDITIVE: no pool, ordering or numeric value moves.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.hps import compute_hps, rank_items_by_hps
from agents.daemon_slayer.rank import MODE_MAP_ID, mode_filter_note, rank_items

# The RM-329 probe champions. Leona is a tank (the /rank-tank subject in
# the filed row); Soraka is the enchanter both /hps routes are built for.
_TANK = "Leona"
_ENCHANTER = "Soraka"
_LEVEL = 11
# A build with real enchanter formulas behind it, so compute_hps returns a
# non-zero throughput and the note is not riding on an empty result.
_ENCHANTER_BUILD = ("3504", "6617", "3107")
# The typo from the filed row. An unrecognised mode, NOT a rejected one -
# RM-329 is a provenance addition and deliberately does not introduce
# mode-string rejection.
_UNKNOWN = "NOT_A_REAL_MODE"

# The acceptance predicate from the BACKLOG row, verbatim.
_ACCEPT = ("not in MODE_MAP_ID", "modifier table not plugged in")


def _accepted(notes) -> bool:
    return any(frag in n for n in notes for frag in _ACCEPT)


class ModeFilterNoteHelperTests(unittest.TestCase):
    """``rank.mode_filter_note`` is the single source of the two strings.

    It was extracted from ``rank_items`` so the EHP-family scorers emit
    the SAME sentence rather than a paraphrase that drifts. The literals
    are pinned here because the acceptance predicate greps them.
    """

    def test_known_mode_names_the_resolved_map_id(self) -> None:
        for mode, map_id in MODE_MAP_ID.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    mode_filter_note(mode), f"mode={mode} -> maps id {map_id}"
                )

    def test_unknown_mode_names_the_allow_all_fallback(self) -> None:
        self.assertEqual(
            mode_filter_note(_UNKNOWN),
            f"mode={_UNKNOWN} not in MODE_MAP_ID - no per-mode item filter applied",
        )

    def test_rank_items_still_emits_the_helper_string_unchanged(self) -> None:
        # The extraction must be byte-identical at the original call site -
        # ModeNoteProvenanceTests reads rank_items().notes[0].
        snap = DataSnapshot.load()
        for mode in ("ARAM", "aram", _UNKNOWN):
            with self.subTest(mode=mode):
                r = rank_items(
                    snap, _TANK, _LEVEL, mode=mode, target_armor=80.0, top_n=3
                )
                self.assertEqual(r.notes[0], mode_filter_note(r.mode))

    def test_probe_mode_is_genuinely_unrecognised(self) -> None:
        # Vacuity fence: every assertion below is worthless if the probe
        # mode ever becomes a real MODE_MAP_ID key.
        self.assertNotIn(_UNKNOWN, MODE_MAP_ID)
        self.assertNotIn(_UNKNOWN.upper(), MODE_MAP_ID)


class RankTankModeProvenanceTests(unittest.TestCase):
    """``/rank-tank`` (``ehp.rank_items_by_ehp``)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, mode: str):
        return rank_items_by_ehp(self.snap, _TANK, _LEVEL, mode=mode, top_n=5)

    def test_unknown_mode_meets_the_acceptance_predicate(self) -> None:
        r = self._rank(_UNKNOWN)
        self.assertTrue(
            _accepted(r.notes),
            f"no mode-provenance note in {list(r.notes)!r}",
        )

    def test_unknown_mode_names_the_mode_string(self) -> None:
        self.assertIn(
            f"mode={_UNKNOWN} not in MODE_MAP_ID", self._rank(_UNKNOWN).notes[0]
        )

    def test_known_modes_name_the_resolved_map_id(self) -> None:
        for mode, map_id in MODE_MAP_ID.items():
            with self.subTest(mode=mode):
                notes = self._rank(mode).notes
                self.assertIn(f"maps id {map_id}", notes[0])
                self.assertNotIn("not in MODE_MAP_ID", notes[0])

    def test_lowercase_mode_is_not_reported_as_unfiltered(self) -> None:
        # The RM-325 trap: the filter IS case-insensitive, so claiming the
        # fallback here would be a FALSE provenance line.
        notes = self._rank("aram").notes
        self.assertIn(f"maps id {MODE_MAP_ID['ARAM']}", notes[0])
        self.assertNotIn("not in MODE_MAP_ID", notes[0])

    def test_exactly_one_mode_provenance_note(self) -> None:
        for mode in ("SR", "ARAM", _UNKNOWN):
            with self.subTest(mode=mode):
                hits = [n for n in self._rank(mode).notes if n.startswith("mode=")]
                self.assertEqual(len(hits), 1, hits)


class RankEnchanterModeProvenanceTests(unittest.TestCase):
    """``/rank-enchanter`` (``hps.rank_items_by_hps``)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, mode: str):
        return rank_items_by_hps(
            self.snap, _ENCHANTER, _LEVEL, mode=mode, top_n=5
        )

    def test_unknown_mode_meets_the_acceptance_predicate(self) -> None:
        r = self._rank(_UNKNOWN)
        self.assertTrue(
            _accepted(r.notes),
            f"no mode-provenance note in {list(r.notes)!r}",
        )

    def test_unknown_mode_names_the_mode_string(self) -> None:
        self.assertIn(
            f"mode={_UNKNOWN} not in MODE_MAP_ID", self._rank(_UNKNOWN).notes[0]
        )

    def test_known_modes_name_the_resolved_map_id(self) -> None:
        for mode, map_id in MODE_MAP_ID.items():
            with self.subTest(mode=mode):
                notes = self._rank(mode).notes
                self.assertIn(f"maps id {map_id}", notes[0])
                self.assertNotIn("not in MODE_MAP_ID", notes[0])

    def test_lowercase_mode_is_not_reported_as_unfiltered(self) -> None:
        notes = self._rank("aram").notes
        self.assertIn(f"maps id {MODE_MAP_ID['ARAM']}", notes[0])
        self.assertNotIn("not in MODE_MAP_ID", notes[0])


class ComputeHpsModeProvenanceTests(unittest.TestCase):
    """``/hps`` (``hps.compute_hps``) - the no-pool member of the family.

    It ranks nothing, so it must NOT borrow the item-filter sentence. The
    only mode fact it owns is its heal/shield modifier table.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _hps(self, mode: str):
        return compute_hps(
            self.snap,
            _ENCHANTER,
            _LEVEL,
            item_ids=list(_ENCHANTER_BUILD),
            mode=mode,
        )

    def test_unknown_mode_meets_the_acceptance_predicate(self) -> None:
        r = self._hps(_UNKNOWN)
        self.assertTrue(
            _accepted(r.notes),
            f"no mode-provenance note in {list(r.notes)!r}",
        )

    def test_unknown_mode_note_names_the_mode_and_the_table(self) -> None:
        hits = [n for n in self._hps(_UNKNOWN).notes if n.startswith("mode=")]
        self.assertEqual(len(hits), 1, hits)
        self.assertIn(f"mode={_UNKNOWN}", hits[0])
        self.assertIn("heal/shield modifier table not plugged in", hits[0])

    def test_probe_build_actually_scores(self) -> None:
        # Vacuity fence: a zero-throughput result would make the note the
        # only thing the probe exercises.
        self.assertGreater(self._hps("SR").total_throughput, 0.0)

    def test_modelled_modes_claim_nothing(self) -> None:
        # SR is the unmodified baseline and ARAM is the one mode the table
        # covers, so a "not plugged in" line would be FALSE for both.
        for mode in ("SR", "ARAM", "sr", "aram"):
            with self.subTest(mode=mode):
                notes = self._hps(mode).notes
                self.assertFalse(
                    any("not plugged in" in n for n in notes), list(notes)
                )

    def test_arena_and_brawl_are_reported_unmodelled(self) -> None:
        # Both are real, MODE_MAP_ID-legal modes whose heal/shield balance
        # table this engine does not carry - the note is about the TABLE,
        # not about whether the mode string was recognised.
        for mode in ("ARENA", "BRAWL"):
            with self.subTest(mode=mode):
                self.assertTrue(
                    any("not plugged in" in n for n in self._hps(mode).notes)
                )

    def test_no_item_filter_claim_on_a_route_that_filters_nothing(self) -> None:
        for mode in ("SR", "ARAM", _UNKNOWN):
            with self.subTest(mode=mode):
                notes = self._hps(mode).notes
                self.assertFalse(
                    any("item filter" in n or "maps id" in n for n in notes),
                    list(notes),
                )


if __name__ == "__main__":
    unittest.main()
