"""RM-35 clause (2) - off-axis exclusion on the CARRY (ds.dps) fight_length path.

``rank_items``' ``fight_length`` blend scores each candidate as
``burst_gain + delta_dps * fight_length``. The burst half credits a PURE-AP item
on an AD marksman even when its sustained ``delta_dps`` is exactly zero, so
every champion in the shipped ``core.ds_champion_fight_length`` allow-map can be
sold dead AP gold. MEASURED on this snapshot at level 13 against the tanky
target, each champion at its own shipped SR build depth:

* Twitch (FL 0.5, IN the shipped allow-map, so this is LIVE today) ranks
  Lich Bane 3100 at #7 - ``delta_dps`` 22.86 against ``effective_score`` 251.00.
* Miss Fortune (the RM-35 GAP champion, counterfactual FL 0.5) ranks Lich Bane
  #6 and Rabadon's Deathcap 3089 #14 on ``delta_dps`` 0.000 - the entire
  176.21 score is burst term.

RM-41 already built the symmetric gate for ``ds.burst``
(``agents/daemon_slayer/_burst_off_axis.py``); this seam is its carry-route
consumer. The gate is DATA-DRIVEN both ways - champion axis from the snapshot's
own ``lolmath.damage_distribution``, item axis from its own DDragon offensive
stat line - so it is NOT a curated list and the controls below are structural,
not hand-picked exemptions.

Contract pinned here:

* DEFAULT-OFF is byte-identical: omitting the flag equals passing False, on
  every RankedItem field, both with and without ``fight_length``.
* ON strips pure-AP offense from an AD marksman's pool and lifts the crit core.
* CONTROL: a champion with no decisive damage split (Shaco) is a no-op flag-ON.
* CONTROL: hybrid items survive by construction (Hextech Gunblade 80 AP+40 AD).
* The delta comes from the NEW path - proven by a call counter on
  ``is_off_axis_candidate``, not inferred from the reordering.
* MUTATION: neutralising the axis resolver collapses ON back onto OFF, so the
  pins cannot pass for an unrelated reason.
"""
from __future__ import annotations

import unittest
from unittest import mock

from agents.daemon_slayer import rank as rank_mod
from agents.daemon_slayer._burst_off_axis import champion_burst_axis
from agents.daemon_slayer.abilities import reset_default_cache
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items

_LEVEL = 13
_FL = 0.5
# Live-shaped tanky mode-curve target. Never probe at the route defaults: they
# are all 0.0 and a zero-HP target nullifies every percent-max-HP effect
# (memory reference_ds_probe_zero_target_defaults).
_TARGET = dict(
    target_armor=105.0, target_mr=60.0,
    target_max_hp=3260.0, target_bonus_hp=1200.0,
)
# Two items from the champion's own shipped SR order - never an empty build
# (memory reference_ds_probe_empty_build_artifact).
_DEPTH = ["3153", "3006"]  # Blade of The Ruined King + Berserker's Greaves

# AD marksmen: MissFortune is the RM-35 GAP champion (unmapped, counterfactual
# FL); Twitch is IN core.ds_champion_fight_length at FL 0.5, so his pollution
# ships live.
_GAP = "MissFortune"
_MAPPED_LIVE = "Twitch"
# No decisive damage split (0.521 magical / 0.347 physical) -> axis None.
_CONTROL_NO_AXIS = "Shaco"

_LICH_BANE = "3100"      # 100% AP offense
_RABADON = "3089"        # 100% AP offense, delta_dps 0.000 for an AD marksman
_GUNBLADE = "3146"       # 80 AP + 40 AD -> hybrid, must survive on both axes
_PURE_AP_IDS = {_LICH_BANE, _RABADON, "3041", "4645", "3135", "3137"}
_CRIT_CORE = {"3031", "6676", "6697", "3036", "6694"}  # IE/Collector/Hubris/LDR/Serylda


def _snap() -> DataSnapshot:
    reset_default_cache()
    return DataSnapshot.load()


def _rows(snap, champion: str, *, exclude: bool, fight_length=_FL):
    return rank_items(
        snap, champion, _LEVEL, current_item_ids=_DEPTH, mode="SR",
        top_n=200, fight_length=fight_length,
        exclude_off_axis_items=exclude, **_TARGET,
    ).ranked


def _ids(rows) -> list[str]:
    return [r.item_id for r in rows]


class DefaultOffIsByteIdenticalTests(unittest.TestCase):
    """The seam pays nothing and changes nothing until it is switched on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def _full(self, rows) -> list[tuple]:
        return [
            (r.item_id, r.delta_dps, r.new_dps, r.dps_per_1k_gold,
             r.effective_score, r.is_terminal, r.shares_dead_unique,
             r.unique_passive_key)
            for r in rows
        ]

    def test_omitting_the_flag_equals_passing_false(self) -> None:
        for fl in (None, _FL):
            with self.subTest(fight_length=fl):
                explicit = rank_items(
                    self.snap, _GAP, _LEVEL, current_item_ids=_DEPTH, mode="SR",
                    top_n=200, fight_length=fl, exclude_off_axis_items=False,
                    **_TARGET,
                ).ranked
                default = rank_items(
                    self.snap, _GAP, _LEVEL, current_item_ids=_DEPTH, mode="SR",
                    top_n=200, fight_length=fl, **_TARGET,
                ).ranked
                self.assertTrue(default, "empty ranking - assertion would be vacuous")
                self.assertEqual(self._full(default), self._full(explicit))

    def test_off_path_never_calls_the_gate(self) -> None:
        with mock.patch.object(
            rank_mod, "is_off_axis_candidate",
            side_effect=rank_mod.is_off_axis_candidate,
        ) as spy:
            rank_items(
                self.snap, _GAP, _LEVEL, current_item_ids=_DEPTH, mode="SR",
                top_n=200, fight_length=_FL, **_TARGET,
            )
        self.assertEqual(spy.call_count, 0)


class OffAxisStripMovesTheGapChampionTests(unittest.TestCase):
    """ON removes dead AP gold and lifts the lethality-crit core."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()
        cls.off = {c: _rows(cls.snap, c, exclude=False)
                   for c in (_GAP, _MAPPED_LIVE)}
        cls.on = {c: _rows(cls.snap, c, exclude=True)
                  for c in (_GAP, _MAPPED_LIVE)}

    def test_both_ad_marksmen_resolve_the_ad_axis(self) -> None:
        for champ in (_GAP, _MAPPED_LIVE):
            with self.subTest(champ=champ):
                self.assertEqual(
                    champion_burst_axis(self.snap.champions.get(champ)), "ad")

    def test_pollution_is_present_when_off(self) -> None:
        """Non-vacuous baseline: the rows the ON pins remove really are there."""
        for champ in (_GAP, _MAPPED_LIVE):
            with self.subTest(champ=champ):
                ids = _ids(self.off[champ])
                self.assertIn(_LICH_BANE, ids)
                self.assertLessEqual(
                    ids.index(_LICH_BANE) + 1, 8,
                    "Lich Bane should sit in the polluted top-8 baseline")

    def test_zero_dps_ap_item_scores_entirely_off_the_burst_term(self) -> None:
        """The mechanism behind the defect, asserted as a computed quantity."""
        row = next(r for r in self.off[_GAP] if r.item_id == _RABADON)
        self.assertEqual(row.delta_dps, 0.0)
        self.assertGreater(row.effective_score, 0.0)

    def test_on_strips_every_pure_ap_candidate(self) -> None:
        for champ in (_GAP, _MAPPED_LIVE):
            with self.subTest(champ=champ):
                self.assertEqual(set(_ids(self.on[champ])) & _PURE_AP_IDS, set())

    def test_on_spares_the_hybrid_item(self) -> None:
        """Not a blanket AP strip: 80 AP + 40 AD carries on-axis offense."""
        for champ in (_GAP, _MAPPED_LIVE):
            with self.subTest(champ=champ):
                self.assertIn(_GUNBLADE, _ids(self.on[champ]))

    def test_on_does_not_disturb_the_surviving_relative_order(self) -> None:
        """A pool strip only removes rows; it must not reorder the survivors."""
        for champ in (_GAP, _MAPPED_LIVE):
            with self.subTest(champ=champ):
                on_ids = _ids(self.on[champ])
                kept = [i for i in _ids(self.off[champ]) if i in set(on_ids)]
                self.assertEqual(on_ids, kept)

    def test_on_lifts_the_crit_core_into_the_top_eight(self) -> None:
        for champ in (_GAP, _MAPPED_LIVE):
            with self.subTest(champ=champ):
                before = len(_CRIT_CORE & set(_ids(self.off[champ])[:8]))
                after = len(_CRIT_CORE & set(_ids(self.on[champ])[:8]))
                self.assertGreater(after, before)

    def test_new_path_executed(self) -> None:
        """The delta came through the new gate - counted, not inferred."""
        with mock.patch.object(
            rank_mod, "is_off_axis_candidate",
            side_effect=rank_mod.is_off_axis_candidate,
        ) as spy:
            _rows(self.snap, _GAP, exclude=True)
        self.assertGreater(spy.call_count, 0)
        self.assertTrue(any(call.args[1] == "ad" for call in spy.call_args_list))


class ControlsAndMutationTests(unittest.TestCase):
    """The separation is structural: an indecisive kit is untouched."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = _snap()

    def test_control_champion_has_no_decisive_axis(self) -> None:
        self.assertIsNone(
            champion_burst_axis(self.snap.champions.get(_CONTROL_NO_AXIS)))

    def test_control_champion_is_byte_identical_flag_on(self) -> None:
        off = _rows(self.snap, _CONTROL_NO_AXIS, exclude=False)
        on = _rows(self.snap, _CONTROL_NO_AXIS, exclude=True)
        self.assertTrue(off, "empty ranking - assertion would be vacuous")
        self.assertEqual(
            [(r.item_id, r.delta_dps, r.effective_score) for r in on],
            [(r.item_id, r.delta_dps, r.effective_score) for r in off],
        )

    def test_control_baseline_carries_ap_items_to_strip(self) -> None:
        """Non-vacuous control: the no-op is the AXIS gate, not an empty pool."""
        ids = set(_ids(_rows(self.snap, _CONTROL_NO_AXIS, exclude=False)))
        self.assertTrue(ids & _PURE_AP_IDS)

    def test_mutation_neutralised_axis_collapses_on_onto_off(self) -> None:
        """Forcing the resolver to None must undo the ENTIRE flag-ON delta."""
        off = _ids(_rows(self.snap, _GAP, exclude=False))
        on = _ids(_rows(self.snap, _GAP, exclude=True))
        self.assertNotEqual(on, off, "flag-ON must differ, else the pin is vacuous")
        with mock.patch.object(rank_mod, "champion_burst_axis", return_value=None):
            mutated = _ids(_rows(self.snap, _GAP, exclude=True))
        self.assertEqual(mutated, off)

    def test_mutation_inverted_axis_strips_the_other_side(self) -> None:
        """Symmetry check: forcing "ap" strips the AD items instead."""
        with mock.patch.object(rank_mod, "champion_burst_axis", return_value="ap"):
            inverted = set(_ids(_rows(self.snap, _GAP, exclude=True)))
        self.assertIn(_LICH_BANE, inverted)
        self.assertNotIn("3031", inverted)  # Infinity Edge - pure AD offense
        self.assertIn(_GUNBLADE, inverted)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
