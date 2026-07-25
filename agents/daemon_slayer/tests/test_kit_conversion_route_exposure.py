"""RM-86 L1 prerequisite - expose ``kit_conversion_strength`` on the CARRY route.

PART 7 of docs/OPEN_ITEMS_REVIEW_2026-07-25.md measured the cross-cutting blocker:
``agents/daemon_slayer/server.py`` carried ZERO ``kit_conversion`` /
``conversion_strength`` references, so the RM-86 L1 lever was Python-API-only.
``tools/daemon_slayer_build_orders_generate.py`` drives the shipped build tables
through ``:8893``, so no kit-conversion fix could reach a shipped artifact.

Confirmed API surface before scaffolding:
  * ``rank_items(..., kit_conversion_strength: float = 0.0)`` - rank.py:918.
  * the gate is consulted ONLY when > 0.0 - rank.py:1294-1297.
  * ``server._route_rank`` builds the ``rank_items`` call - server.py:421-501.
  * ``server._CACHE.set(DataSnapshot)`` seeds the route snapshot holder
    - test_rank_route_seam_passthrough.py:42 precedent.
  * Naafiri separates 116-of-134 rows at strength 0.0 -> 1.0 (PART 7 measurement).

DEFAULT-OFF contract: a body that omits the key is byte-identical to one that
passes 0.0, and to today's response.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def setUpModule() -> None:
    server._CACHE.set(_SNAP)


def _names(result: dict) -> list[str]:
    return [row["item_name"] for row in result["ranked"]]


class KitConversionRouteExposureTests(unittest.TestCase):
    """POST /rank accepts kit_conversion_strength and threads it to rank_items."""

    BODY = {
        "champion": "Naafiri",
        "level": 13,
        "mode": "SR",
        "items": ["3142"],
        "target_armor": 100.0,
        "target_mr": 60.0,
        "target_max_hp": 2400.0,
        "target_bonus_hp": 1200.0,
        "top": 40,
    }

    def test_omitted_is_byte_identical_to_explicit_zero(self):
        omitted = server._route_rank(dict(self.BODY))
        explicit = server._route_rank(dict(self.BODY, kit_conversion_strength=0.0))
        self.assertEqual(omitted, explicit)

    def test_strength_one_diverges_for_a_registry_champion(self):
        off = server._route_rank(dict(self.BODY))
        on = server._route_rank(dict(self.BODY, kit_conversion_strength=1.0))
        self.assertNotEqual(_names(off), _names(on))

    def test_row_fields_stay_raw(self):
        """L1 scales the SORT key only - the emitted deltas are untouched."""
        off = server._route_rank(dict(self.BODY))
        on = server._route_rank(dict(self.BODY, kit_conversion_strength=1.0))
        off_by_id = {r["item_id"]: r["delta_dps"] for r in off["ranked"]}
        for row in on["ranked"]:
            if row["item_id"] in off_by_id:
                self.assertAlmostEqual(
                    row["delta_dps"], off_by_id[row["item_id"]], places=6
                )

    def test_off_registry_champion_is_inert(self):
        """A champion absent from _KIT_CONVERSION gets _IDENTITY - exactly inert.

        This originally used Quinn, which was true when written and is no longer:
        the A-20 / RM-89 slice SEEDED Quinn into the registry in this same batch,
        which is the whole point of that row. Jinx and Caitlyn are the controls
        A-20 itself pinned as byte-identical at full strength.
        """
        from agents.daemon_slayer.kit_conversion import registry_champion_ids

        registry = registry_champion_ids()
        for champ in ("Jinx", "Caitlyn"):
            with self.subTest(champion=champ):
                self.assertNotIn(champ, registry)
                body = dict(self.BODY, champion=champ)
                off = server._route_rank(dict(body))
                on = server._route_rank(dict(body, kit_conversion_strength=1.0))
                self.assertEqual(_names(off), _names(on))


if __name__ == "__main__":
    unittest.main()
