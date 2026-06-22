"""Tests for the ARAM balance-grid accessor + /api/aram-balance route.

Two layers:

  - Accessor (``core.aram_balance_context.balance_grid_for`` /
    ``balance_grid_map``): the NEW all-7-field non-neutral grid reader,
    distinct from the SHIPPED dealt+taken coach-prompt path
    (``get_balance_mults`` / ``aram_balance_line``) which stays unchanged.

  - Route (``dashboard.routes_aram_balance._serve_aram_balance``): 200
    happy-path shape (ok / patch / champions) driven through a stub
    handler that captures ``_send`` (mirrors test_routes_damage_mix).

Ground truth (VERIFIED on disk, data/daemon_slayer/16.12.1/champions.json):
Aatrox carries aramDamageDealt=1.05 with all other fields neutral, so the
grid for Aatrox is exactly {"aramDamageDealt": 1.05}. We assert that known
value + structural invariants only; NO data-fragile cross-champ counts
(CLAUDE.md "Testing Discipline").
"""
from __future__ import annotations

import json
import unittest
from typing import Optional

from core import aram_balance_context as abc
from dashboard import routes_aram_balance


# ---------------------------------------------------------------------
# Stub request handler (mirrors test_routes_damage_mix.StubHandler)
# ---------------------------------------------------------------------

class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: Optional[int] = None
        self.last_body: Optional[bytes] = None
        self.last_ct: Optional[str] = None

    def _send(self, status, body, content_type):
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


# ---------------------------------------------------------------------
# Accessor tests
# ---------------------------------------------------------------------

class BalanceGridForTests(unittest.TestCase):
    def test_aatrox_dealt_only(self):
        # VERIFIED: Aatrox = {dealt:1.05, all others neutral}.
        grid = abc.balance_grid_for("Aatrox")
        self.assertEqual(grid, {"aramDamageDealt": 1.05})

    def test_aatrox_omits_neutral_fields(self):
        # Only the non-neutral field is present - no taken/healing/AH keys.
        grid = abc.balance_grid_for("Aatrox")
        for k in (
            "aramDamageTaken",
            "aramHealing",
            "aramShielding",
            "aramTenacity",
            "aramAbilityHaste",
            "aramAttackSpeed",
        ):
            self.assertNotIn(k, grid)

    def test_none_returns_empty(self):
        self.assertEqual(abc.balance_grid_for(None), {})

    def test_unknown_champ_returns_empty(self):
        self.assertEqual(abc.balance_grid_for("NotAChampionXyz"), {})

    def test_fully_neutral_champ_returns_empty(self):
        # Find a champ that is fully neutral (absent from the grid map) and
        # confirm the per-champ accessor returns {} for it. Data-driven so
        # it survives a patch bump without pinning a specific champ name.
        full = abc.balance_grid_map()
        all_ids = _all_champ_ids()
        neutral_ids = [c for c in all_ids if c not in full]
        self.assertTrue(
            neutral_ids,
            "expected at least one fully-neutral champ in the snapshot",
        )
        self.assertEqual(abc.balance_grid_for(neutral_ids[0]), {})

    def test_values_are_non_neutral(self):
        # Every value in any returned grid must be non-neutral by the
        # field's own rule (multiplier != 1.0, or AH != 0).
        for fields in abc.balance_grid_map().values():
            for key, val in fields.items():
                if key == "aramAbilityHaste":
                    self.assertNotEqual(val, 0)
                else:
                    self.assertNotEqual(val, 1.0)


class BalanceGridMapTests(unittest.TestCase):
    def test_map_includes_aatrox(self):
        m = abc.balance_grid_map()
        self.assertIn("Aatrox", m)
        self.assertEqual(m["Aatrox"], {"aramDamageDealt": 1.05})

    def test_map_omits_fully_neutral(self):
        # No entry in the map may be an empty dict (fully-neutral champs
        # are dropped, not stored as {}).
        for cid, fields in abc.balance_grid_map().items():
            self.assertTrue(fields, f"{cid} stored as empty grid")

    def test_map_keys_are_champ_id_strings(self):
        for cid in abc.balance_grid_map():
            self.assertIsInstance(cid, str)


class UnchangedSymbolsTests(unittest.TestCase):
    """Guard the SHIPPED coach-prompt API is still present + working."""

    def test_get_balance_mults_still_present(self):
        # Aatrox dealt 1.05, taken neutral 1.0.
        self.assertEqual(abc.get_balance_mults("Aatrox"), (1.05, 1.0))

    def test_aram_balance_line_still_present(self):
        line = abc.aram_balance_line("Aatrox", "ARAM")
        self.assertIn("deal +5%", line)


# ---------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------

class RouteTests(unittest.TestCase):
    def test_happy_path_shape(self):
        h = StubHandler("/api/aram-balance")
        routes_aram_balance._serve_aram_balance(h)
        self.assertEqual(h.last_status, 200)
        self.assertEqual(h.last_ct, "application/json")
        body = h.parsed()
        self.assertIs(body.get("ok"), True)
        self.assertIsInstance(body.get("patch"), str)
        self.assertTrue(body["patch"])
        champs = body.get("champions")
        self.assertIsInstance(champs, dict)
        self.assertIn("Aatrox", champs)
        self.assertEqual(champs["Aatrox"], {"aramDamageDealt": 1.05})

    def test_get_routes_registered(self):
        paths = [m.__doc__ for m, _ in routes_aram_balance.GET_ROUTES]
        # Structural: exactly one GET route + no POST routes.
        self.assertEqual(len(routes_aram_balance.GET_ROUTES), 1)
        self.assertEqual(routes_aram_balance.POST_ROUTES, [])


def _all_champ_ids() -> list:
    """Read every champ id from the live snapshot (test helper)."""
    import pathlib

    data_dir = pathlib.Path(abc.__file__).resolve().parent.parent / "data" / "daemon_slayer"
    patch = (data_dir / "current.txt").read_text(encoding="utf-8").strip()
    raw = json.loads((data_dir / patch / "champions.json").read_text(encoding="utf-8"))
    return list((raw.get("data") or {}).keys())


if __name__ == "__main__":
    unittest.main()
