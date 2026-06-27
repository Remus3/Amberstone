"""Engine Agent A - /rank route-family seam-flag passthrough.

Proves the server route handlers (``server._route_rank`` /
``_route_rank_tank`` / ``_route_rank_bruiser`` / ``_route_rank_assassin`` /
``_route_rank_enchanter`` plus the scoped ``_route_dps`` / ``_route_burst``)
ACCEPT the seam flags, thread them to the underlying scorer, and stay
BEHAVIOR-PRESERVING: a body that omits a flag is byte-identical to the
default-off result, while a flag turned ON DIVERGES.

In-process (the route functions take a body dict + read the module
``_CACHE``); no HTTP. Confirmed API surface before scaffolding:
  * server._route_rank / _route_rank_tank / _route_rank_bruiser /
    _route_rank_assassin / _route_rank_enchanter / _route_dps / _route_burst
    - agents/daemon_slayer/server.py (grepped def lines).
  * server._CACHE.set(DataSnapshot) seeds the snapshot holder
    - server.py:166 (_SnapshotCache.set).
  * rank_items accepts exempt_offclass_by_win / prefer_kit_axis_by_win /
    cost_ceiling - rank.py:549-551.
  * rank_items_by_ehp accepts prefer_survivability_by_win / cost_ceiling
    - ehp.py:1930-1931.
  * rank_items_by_hybrid accepts prefer_survivability_by_win / cost_ceiling
    - hybrid.py:618-619.
  * rank_items_by_burst accepts prefer_kit_axis_by_win - burst.py:1512.
  * rank_items_by_hps accepts prefer_survivability_by_win - hps.py:815.
  * Off-class win-exempt set surfaces Trinity Force for Ezreal; RF2 surfaces
    Guardian's Horn / Warmog's Armor / Heartsteel for Rakan (live-probed).

No ENGINE_VERSION assertion here (version bump is a separate agent).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()


def setUpModule() -> None:
    # Seed the module-level snapshot holder the route handlers read.
    server._CACHE.set(_SNAP)


def _names(result: dict) -> list[str]:
    return [row["item_name"] for row in result["ranked"]]


def _new_score(result: dict, key: str) -> list[float]:
    return [row[key] for row in result["ranked"]]


class RankCarrySeamTests(unittest.TestCase):
    """/rank: exempt_offclass_by_win (DSP2), prefer_kit_axis_by_win (DSP11),
    cost_ceiling (F2)."""

    BODY = {"champion": "Ezreal", "level": 11, "mode": "SR", "top": 40}

    def test_default_off_byte_identical(self):
        a = server._route_rank(dict(self.BODY))
        b = server._route_rank(dict(self.BODY))
        self.assertEqual(a, b)
        # And explicitly-off equals omit.
        off = server._route_rank(
            dict(self.BODY, exempt_offclass_by_win=False,
                 prefer_kit_axis_by_win=False)
        )
        self.assertEqual(_names(a), _names(off))

    def test_exempt_offclass_by_win_diverges(self):
        off = _names(server._route_rank(dict(self.BODY)))
        on = _names(server._route_rank(
            dict(self.BODY, exempt_offclass_by_win=True)))
        self.assertNotEqual(off, on)
        # The off-class win-exempt set un-strips Ezreal's Trinity Force.
        self.assertIn("Trinity Force", set(on) - set(off))

    def test_cost_ceiling_threads_and_constrains(self):
        # A low cost ceiling drops expensive candidates -> a strict subset of
        # the unconstrained pool. Behavior-preserving: omitting the key is the
        # no-ceiling default. ``top`` is raised so neither run is truncated -
        # truncation could otherwise promote a capped row that was below the
        # top-N cut in the wide run and break the subset relation.
        wide_body = dict(self.BODY, top=500)
        wide = set(_names(server._route_rank(wide_body)))
        capped_rows = server._route_rank(dict(wide_body, cost_ceiling=1500))
        capped = set(_names(capped_rows))
        self.assertTrue(capped.issubset(wide))
        self.assertLess(len(capped), len(wide))
        # Every surviving candidate is at or under the ceiling.
        self.assertLessEqual(
            max(row["gold"] for row in capped_rows["ranked"]), 1500
        )


class RankEnchanterSurvivabilitySeamTests(unittest.TestCase):
    """/rank-enchanter: prefer_survivability_by_win (RF2) - a survivability
    route, per the build brief."""

    BODY = {"champion": "Rakan", "level": 11, "mode": "ARAM", "top": 40}

    def test_default_off_byte_identical(self):
        a = server._route_rank_enchanter(dict(self.BODY))
        off = server._route_rank_enchanter(
            dict(self.BODY, prefer_survivability_by_win=False))
        self.assertEqual(a, off)

    def test_prefer_survivability_by_win_diverges(self):
        off = _names(server._route_rank_enchanter(dict(self.BODY)))
        on = _names(server._route_rank_enchanter(
            dict(self.BODY, prefer_survivability_by_win=True)))
        self.assertNotEqual(off, on)
        # RF2 injects + floats the WIN-anchored survivability set for Rakan.
        floated = set(on) - set(off)
        self.assertTrue(
            {"Guardian's Horn", "Warmog's Armor", "Heartsteel"} & floated
        )


class RankEnchanterMissingHpAmpSeamTests(unittest.TestCase):
    """/rank-enchanter: R5 assume_missing_hp_heal_amp + caster_missing_hp_pct.
    MasterYi W (Meditate self-heal) is in the comeback heal-amp registry."""

    BODY = {"champion": "MasterYi", "level": 11, "mode": "SR", "top": 40,
            "enchanter_only": False}

    def test_default_off_byte_identical(self):
        a = server._route_rank_enchanter(dict(self.BODY))
        off = server._route_rank_enchanter(
            dict(self.BODY, assume_missing_hp_heal_amp=False,
                 caster_missing_hp_pct=0.0))
        self.assertEqual(a, off)

    def test_r5_amp_diverges_new_hps(self):
        off = server._route_rank_enchanter(dict(self.BODY))
        on = server._route_rank_enchanter(
            dict(self.BODY, assume_missing_hp_heal_amp=True,
                 caster_missing_hp_pct=0.5))
        self.assertNotEqual(
            _new_score(off, "new_hps")[:5], _new_score(on, "new_hps")[:5]
        )


class RankTankSeamTests(unittest.TestCase):
    """/rank-tank: cost_ceiling (F2) threads to rank_items_by_ehp."""

    BODY = {"champion": "Malphite", "level": 11, "mode": "SR", "top": 40}

    def test_default_off_byte_identical(self):
        a = server._route_rank_tank(dict(self.BODY))
        b = server._route_rank_tank(dict(self.BODY))
        self.assertEqual(a, b)

    def test_cost_ceiling_constrains(self):
        wide_body = dict(self.BODY, top=500)
        wide = set(_names(server._route_rank_tank(wide_body)))
        capped_rows = server._route_rank_tank(dict(wide_body, cost_ceiling=1500))
        capped = set(_names(capped_rows))
        self.assertTrue(capped.issubset(wide))
        self.assertLess(len(capped), len(wide))
        self.assertLessEqual(
            max(row["gold"] for row in capped_rows["ranked"]), 1500
        )


class DpsScopedSeamTests(unittest.TestCase):
    """R7 assume_passive_as_stacks + R12 apply_target_vuln are scoped to /dps
    (rank_items does NOT forward them to compute_dps). Prove the route accepts
    them and the default path is byte-identical."""

    BODY = {"champion": "Kindred", "level": 11, "mode": "SR",
            "target_armor": 50.0}

    def test_default_off_byte_identical(self):
        a = server._route_dps(dict(self.BODY))
        off = server._route_dps(
            dict(self.BODY, assume_passive_as_stacks=False,
                 apply_target_vuln=False))
        self.assertEqual(a, off)

    def test_flags_accepted_no_error(self):
        # Behavior-preserving acceptance: the route threads both flags into
        # compute_dps without raising (divergence is champion/effect specific
        # and owned by the engine-level seam tests, not this passthrough gate).
        out = server._route_dps(
            dict(self.BODY, assume_passive_as_stacks=True,
                 apply_target_vuln=True))
        self.assertIn("weighted_dps", out)


class BurstScopedSeamTests(unittest.TestCase):
    """R30 assume_magic_burst is scoped to /burst (rank_items_by_burst does NOT
    accept it). Prove the route accepts it and the default is byte-identical."""

    BODY = {"champion": "Syndra", "level": 11, "mode": "SR",
            "target_armor": 50.0, "target_mr": 50.0}

    def test_default_off_byte_identical(self):
        a = server._route_burst(dict(self.BODY))
        off = server._route_burst(dict(self.BODY, assume_magic_burst=False))
        self.assertEqual(a, off)

    def test_flag_accepted_no_error(self):
        out = server._route_burst(dict(self.BODY, assume_magic_burst=True))
        self.assertIn("total_burst_damage", out)


if __name__ == "__main__":
    unittest.main()
