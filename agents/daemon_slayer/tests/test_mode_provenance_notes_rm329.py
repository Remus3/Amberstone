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
from pathlib import Path

from agents.daemon_slayer._rank_mage import (
    rank_items_by_ability_dps as _rank_mage_impl,
)
from agents.daemon_slayer.ability_dps import rank_items_by_ability_dps
from agents.daemon_slayer.burst import rank_items_by_burst
from agents.daemon_slayer.data_loader import DataSnapshot, canonical_mode
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.hps import compute_hps, rank_items_by_hps
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.onhit_dps import rank_items_by_onhit
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


# ---------------------------------------------------------------------------
# Slice S6: the four routes S1 was fenced out of.
#
# Each is backed by its OWN module, and each one PROVABLY filters a candidate
# pool by mode - every one of them calls ``rank._filter_candidates(mode=mode)``
# -> ``rank._is_legal_in_mode``:
#
#   /rank-bruiser   hybrid.rank_items_by_hybrid          hybrid.py:1269
#   /rank-assassin  burst.rank_items_by_burst            burst.py:2118
#   /rank-mage      _rank_mage.rank_items_by_ability_dps _rank_mage.py:301
#   /rank-onhit     onhit_dps.rank_items_by_onhit        onhit_dps.py:456
#
# so all four earn the item-filter wording, not the weaker table wording
# ``compute_hps`` had to settle for.
#
# THE CASE FOLD IS NOT UNIFORM ACROSS THEM, and that is the whole subtlety.
# ``rank_items_by_burst`` folds ``mode = canonical_mode(mode)`` at burst.py:2032,
# so its ``result.mode`` is the resolved spelling. The other three fold NOWHERE
# (measured: ``canonical_mode`` does not appear in hybrid.py, _rank_mage.py or
# onhit_dps.py at all), so ``result.mode`` echoes the caller's RAW spelling
# while ``_is_legal_in_mode`` upper-cases and filters anyway. Reporting the raw
# spelling there would print the pre-RM-325 falsehood - "mode=aram not in
# MODE_MAP_ID" over a pool the map-12 filter had in fact been applied to. So
# the note is computed from ``canonical_mode(mode)``, which changes NO
# behaviour: it is read only to build the string.
#
# Adding the fold to the three unfolded rankers is deliberately NOT done here.
# That would move what ``compute_hybrid`` / ``compute_ability_dps`` /
# ``compute_onhit_dps`` are handed for a lowercase mode, which is a scoring
# change (RM-325's domain), and RM-329 is notes-only.
# ---------------------------------------------------------------------------

_UNFILTERED_LITERAL = "not in MODE_MAP_ID - no per-mode item filter applied"


class _PoolFilteringRankerNoteMixin:
    """Shared contract for a ranker that DOES filter its pool by mode.

    Subclasses set ``ROUTE``/``CHAMPION`` and implement ``_rank``. Every
    assertion here is about the item-legality verdict, which each of these
    routes provably reaches - see the module comment above.
    """

    ROUTE = ""
    CHAMPION = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()

    def _rank(self, mode: str):  # pragma: no cover - overridden
        raise NotImplementedError

    def _expected(self, mode: str) -> str:
        # The RESOLVED mode, never the raw one (RM-325).
        return mode_filter_note(canonical_mode(mode))

    def test_probe_actually_ranks_something(self) -> None:
        # Vacuity fence: a ranker returning an empty pool would make every
        # note assertion below true of nothing worth asserting.
        r = self._rank("SR")
        self.assertGreater(len(r.ranked), 0, self.CHAMPION)
        self.assertGreater(r.candidates_evaluated, 0, self.CHAMPION)

    def test_unknown_mode_meets_the_acceptance_predicate(self) -> None:
        r = self._rank(_UNKNOWN)
        self.assertTrue(
            _accepted(r.notes),
            f"{self.ROUTE}: no mode-provenance note in {list(r.notes)!r}",
        )

    def test_unknown_mode_names_the_mode_string(self) -> None:
        self.assertEqual(
            self._rank(_UNKNOWN).notes[0],
            f"mode={_UNKNOWN} {_UNFILTERED_LITERAL}",
        )

    def test_known_modes_name_the_resolved_map_id(self) -> None:
        for mode, map_id in MODE_MAP_ID.items():
            with self.subTest(mode=mode):
                notes = self._rank(mode).notes
                self.assertEqual(notes[0], f"mode={mode} -> maps id {map_id}")
                self.assertNotIn("not in MODE_MAP_ID", notes[0])

    def test_lowercase_mode_is_not_reported_as_unfiltered(self) -> None:
        # The RM-325 trap. ``_is_legal_in_mode`` upper-cases, so the map-12
        # filter HAS run at ``mode="aram"`` and the fallback line would be a
        # false provenance line. Pinned on the three unfolded rankers too,
        # where ``result.mode`` still echoes "aram".
        for spelling in ("aram", "Aram"):
            with self.subTest(spelling=spelling):
                notes = self._rank(spelling).notes
                self.assertEqual(
                    notes[0], f"mode=ARAM -> maps id {MODE_MAP_ID['ARAM']}"
                )
                self.assertNotIn("not in MODE_MAP_ID", notes[0])

    def test_lowercase_and_uppercase_aram_share_one_pool(self) -> None:
        # The claim the note above makes, checked against the pool itself
        # rather than inferred - if these ever diverged the note would be
        # naming a filter that did not run.
        lo, up = self._rank("aram"), self._rank("ARAM")
        self.assertEqual(
            [r.item_id for r in lo.ranked], [r.item_id for r in up.ranked]
        )

    def test_note_comes_from_the_shared_helper(self) -> None:
        # No route may paraphrase: the two sentences live in exactly one
        # place (``rank.mode_filter_note``) so they cannot drift apart.
        for mode in ("SR", "ARAM", "aram", _UNKNOWN):
            with self.subTest(mode=mode):
                self.assertEqual(self._rank(mode).notes[0], self._expected(mode))

    def test_exactly_one_mode_provenance_note(self) -> None:
        for mode in ("SR", "ARAM", _UNKNOWN):
            with self.subTest(mode=mode):
                hits = [
                    n for n in self._rank(mode).notes
                    if "MODE_MAP_ID" in n or "maps id" in n
                ]
                self.assertEqual(len(hits), 1, hits)

    def test_unknown_mode_really_does_widen_the_pool(self) -> None:
        # The severity the note exists to disclose, measured not assumed:
        # an unrecognised mode evaluates a strictly larger pool than SR
        # because ``_is_legal_in_mode`` allows everything through.
        self.assertGreater(
            self._rank(_UNKNOWN).candidates_evaluated,
            self._rank("SR").candidates_evaluated,
        )


class RankBruiserModeProvenanceTests(
    _PoolFilteringRankerNoteMixin, unittest.TestCase
):
    """``/rank-bruiser`` (``hybrid.rank_items_by_hybrid``) - mode NOT folded."""

    ROUTE = "/rank-bruiser"
    CHAMPION = "Darius"

    def _rank(self, mode: str):
        return rank_items_by_hybrid(
            self.snap, self.CHAMPION, _LEVEL, mode=mode, top_n=5
        )

    def test_result_mode_is_the_raw_spelling_but_the_note_is_resolved(self) -> None:
        # Pins the asymmetry rather than leaving it to be rediscovered: this
        # ranker does NOT canonical_mode-fold, so ``result.mode`` echoes the
        # caller while the note reports what the filter actually did.
        r = self._rank("aram")
        self.assertEqual(r.mode, "aram")
        self.assertEqual(r.notes[0], f"mode=ARAM -> maps id {MODE_MAP_ID['ARAM']}")


class RankAssassinModeProvenanceTests(
    _PoolFilteringRankerNoteMixin, unittest.TestCase
):
    """``/rank-assassin`` (``burst.rank_items_by_burst``) - mode IS folded."""

    ROUTE = "/rank-assassin"
    CHAMPION = "Zed"

    def _rank(self, mode: str):
        return rank_items_by_burst(
            self.snap, self.CHAMPION, _LEVEL, mode=mode, top_n=5
        )

    def test_result_mode_is_already_folded_here(self) -> None:
        # The one route of the four that folds at its entry (burst.py:2032),
        # so the plain ``mode_filter_note(result.mode)`` form is also correct
        # for it. Pinned so a future fold removal is caught here.
        r = self._rank("aram")
        self.assertEqual(r.mode, "ARAM")
        self.assertEqual(r.notes[0], mode_filter_note(r.mode))


class RankMageModeProvenanceTests(
    _PoolFilteringRankerNoteMixin, unittest.TestCase
):
    """``/rank-mage`` (``_rank_mage.rank_items_by_ability_dps``).

    Imported through ``ability_dps`` - the route's public surface - even
    though the definition lives in ``_rank_mage``, so this pins the symbol
    the server actually calls.
    """

    ROUTE = "/rank-mage"
    CHAMPION = "Lux"

    def _rank(self, mode: str):
        return rank_items_by_ability_dps(
            self.snap, self.CHAMPION, _LEVEL, mode=mode, top_n=5
        )

    def test_route_symbol_is_the_rank_mage_definition(self) -> None:
        # ``ability_dps`` re-exports it; the note lives in ``_rank_mage``.
        self.assertIs(rank_items_by_ability_dps, _rank_mage_impl)


class RankOnhitModeProvenanceTests(
    _PoolFilteringRankerNoteMixin, unittest.TestCase
):
    """``/rank-onhit`` (``onhit_dps.rank_items_by_onhit``) - mode NOT folded."""

    ROUTE = "/rank-onhit"
    CHAMPION = "Gwen"

    def _rank(self, mode: str):
        return rank_items_by_onhit(
            self.snap, self.CHAMPION, _LEVEL, mode=mode, top_n=5
        )


class NoDuplicatedProvenanceLiteralTests(unittest.TestCase):
    """The two sentences exist in exactly ONE place in the engine.

    ``mode_filter_note`` was extracted so seven routes could not drift into
    seven paraphrases. A copy-pasted literal would pass every behavioural
    test above on the day it was written and rot silently afterwards, so
    the source itself is checked.
    """

    _ENGINE_DIR = Path(__file__).resolve().parent.parent

    def _owners(self, needle: str) -> list[str]:
        return sorted(
            p.name
            for p in self._ENGINE_DIR.glob("*.py")
            if needle in p.read_text(encoding="utf-8")
        )

    def test_only_rank_py_spells_out_the_fallback_sentence(self) -> None:
        owners = self._owners(_UNFILTERED_LITERAL)
        self.assertEqual(owners, ["rank.py"], owners)

    def test_only_rank_py_spells_out_the_maps_id_sentence(self) -> None:
        owners = self._owners(" -> maps id {")
        self.assertEqual(owners, ["rank.py"], owners)

    def test_the_engine_dir_is_the_one_being_scanned(self) -> None:
        # Vacuity fence: a wrong _ENGINE_DIR would make both sweeps above
        # pass by finding nothing at all.
        self.assertTrue((self._ENGINE_DIR / "rank.py").is_file(), self._ENGINE_DIR)
        self.assertTrue((self._ENGINE_DIR / "hybrid.py").is_file())


if __name__ == "__main__":
    unittest.main()
