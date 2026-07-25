"""A-12 / RM-46 - plumb ``apply_crit_conversion`` through rank_items and the CARRY route.

The A-12 build slice landed the seam in ``dps.compute_dps`` only, so the crit
conversion was Python-API-only: ``rank.py`` held no parameter and
``tools/daemon_slayer_build_orders_generate.py`` drives the shipped build tables
through ``:8893``. That is the same blocker PART 7 named for RM-86
(docs/OPEN_ITEMS_REVIEW_2026-07-25.md:451-457), and the A-12 agent's own ordering
measurement had to monkeypatch ``rank.compute_dps`` to work around it.

Confirmed API surface before scaffolding:
  * ``compute_dps(..., apply_crit_conversion: bool = False)`` - dps.py:747, gate at :890.
  * ``rank_items`` calls ``compute_dps`` at rank.py:1091 (baseline) and :1206 (candidate).
    BOTH must receive the flag or the delta is computed against a mismatched baseline.
  * ``server._route_rank`` builds the ``rank_items`` call - server.py:421.
  * Registry holds exactly one champion, Ashe - _crit_conversion_overrides.py.

Gate params are the ones A-12 reproduced byte-for-byte against the PART 7 filing:
level 16, current build ["3006"], armor 110 / MR 52 / 2500 max HP / 1200 bonus HP.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items

_SNAP = DataSnapshot.load()


def setUpModule() -> None:
    server._CACHE.set(_SNAP)


_GATE = {
    "level": 16,
    "mode": "SR",
    "target_armor": 110.0,
    "target_mr": 52.0,
    "target_max_hp": 2500.0,
    "target_bonus_hp": 1200.0,
    "top": 40,
}


def _rank(champion: str, **kw) -> list[str]:
    result = rank_items(
        _SNAP,
        champion_id=champion,
        level=_GATE["level"],
        current_item_ids=["3006"],
        mode=_GATE["mode"],
        target_armor=_GATE["target_armor"],
        target_mr=_GATE["target_mr"],
        target_max_hp=_GATE["target_max_hp"],
        target_bonus_hp=_GATE["target_bonus_hp"],
        top_n=_GATE["top"],
        **kw,
    )
    return [row.item_name for row in result.ranked]


def _route(champion: str, **kw) -> dict:
    body = dict(_GATE, champion=champion, items=["3006"], **kw)
    return server._route_rank(body)


def _names(result: dict) -> list[str]:
    return [row["item_name"] for row in result["ranked"]]


class RankItemsCritConversionPlumbTests(unittest.TestCase):
    """rank_items accepts the flag and threads it to BOTH compute_dps calls."""

    def test_default_off_is_byte_identical(self):
        omitted = _rank("Ashe")
        explicit = _rank("Ashe", apply_crit_conversion=False)
        self.assertEqual(omitted, explicit)

    def test_ashe_diverges_when_on(self):
        off = _rank("Ashe")
        on = _rank("Ashe", apply_crit_conversion=True)
        self.assertNotEqual(off, on)

    def test_infinity_edge_demotes_relative_to_crit_chance_items(self):
        """The A-12 direction: IE falls, pure crit-chance items rise.

        Rank positions are asserted as a RELATION, not as filed absolute
        numbers - PART 7's simulated #8 -> #9 measured #8 -> #10 in the built
        seam, and the relation is what the row's thesis actually claims.
        """
        off = _rank("Ashe")
        on = _rank("Ashe", apply_crit_conversion=True)
        ie_off, ie_on = off.index("Infinity Edge"), on.index("Infinity Edge")
        self.assertGreater(ie_on, ie_off)

    def test_aphelios_negative_control_identical(self):
        """Only Ashe is in the registry, so every other champion is inert."""
        for champ in ("Aphelios", "Jinx", "Caitlyn"):
            with self.subTest(champion=champ):
                self.assertEqual(_rank(champ), _rank(champ, apply_crit_conversion=True))


class RouteCritConversionPlumbTests(unittest.TestCase):
    """POST /rank accepts apply_crit_conversion and stays DEFAULT-OFF."""

    def test_omitted_is_byte_identical_to_explicit_false(self):
        omitted = _route("Ashe")
        explicit = _route("Ashe", apply_crit_conversion=False)
        self.assertEqual(omitted, explicit)

    def test_route_on_matches_the_direct_call(self):
        route_on = _names(_route("Ashe", apply_crit_conversion=True))
        direct_on = _rank("Ashe", apply_crit_conversion=True)
        self.assertEqual(route_on, direct_on)

    def test_route_negative_control_identical(self):
        off = _names(_route("Aphelios"))
        on = _names(_route("Aphelios", apply_crit_conversion=True))
        self.assertEqual(off, on)


if __name__ == "__main__":
    unittest.main()
