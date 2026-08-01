"""Guard the port registry against the drift that made it necessary.

The registry is only worth having if it is CHECKED. Before this file existed,
answering "which ports does RC use" meant grepping bind sites and hand-filtering
vendored noise - which is exactly how 8901 nearly got handed to Daemon Slayer
while Sibling-A was already serving on it.

So the tests here do two distinct jobs:

1. Pin each constant against the LIVE definition site, by importing the module
   that actually binds and comparing. A test that only re-asserted the literal
   (`assert ports.DASHBOARD == 8888`) would pass forever while the real server
   moved, which is the failure mode this whole module exists to prevent.
2. Assert the block reservations stay disjoint and keep containing the ports
   assigned to them.
"""
from __future__ import annotations

import unittest

from core import ports


class LiveDefinitionSitesAgreeTests(unittest.TestCase):
    """Each constant must equal the value the binding module actually uses.

    Import failures are skips rather than errors: several of these modules pull
    optional runtime deps, and a missing dep should not turn a port-registry
    guard red. The skip is loud enough to notice, and the modules that matter
    most (dashboard, DS engine, Mission Control) import cleanly in CI.
    """

    def _live(self, module_path: str, attr: str) -> int:
        import importlib
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:  # noqa: BLE001 - optional runtime deps
            self.skipTest(f"{module_path} not importable here: {exc}")
        self.assertTrue(
            hasattr(mod, attr),
            f"{module_path} no longer defines {attr} - the registry's citation "
            f"is stale, fix core/ports.py rather than deleting this assertion",
        )
        return getattr(mod, attr)

    def test_dashboard_port_matches_server(self):
        self.assertEqual(ports.DASHBOARD, self._live("dashboard.server", "PORT"))

    def test_vision_port_matches_config(self):
        self.assertEqual(ports.VISION, self._live("vision_server._config", "PORT"))

    def test_agents_ports_match_supervisor_common(self):
        self.assertEqual(
            ports.AGENTS_SUPERVISOR, self._live("agents._supervisor_common", "WEB_PORT")
        )
        self.assertEqual(
            ports.AGENTS_WS, self._live("agents._supervisor_common", "WS_PORT")
        )

    def test_mission_control_port_matches_server(self):
        self.assertEqual(ports.MISSION_CONTROL, self._live("mc.server", "PORT"))

    def test_ds_engine_port_matches_both_ends(self):
        """Server and client must agree, or the client silently talks to nothing."""
        server = self._live("agents.daemon_slayer.server", "DEFAULT_PORT")
        client = self._live("core.daemon_slayer_client", "DEFAULT_PORT")
        self.assertEqual(ports.DS_ENGINE, server)
        self.assertEqual(
            server, client, "DS server and client disagree on the engine port"
        )


class BlockReservationTests(unittest.TestCase):

    def test_blocks_are_pairwise_disjoint(self):
        names = sorted(ports.BLOCKS)
        checked = 0
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                overlap = set(ports.BLOCKS[a]) & set(ports.BLOCKS[b])
                self.assertEqual(
                    overlap, set(), f"blocks {a} and {b} overlap on {sorted(overlap)}"
                )
                checked += 1
        self.assertEqual(checked, 6, "expected 6 pairs across 4 blocks")

    def test_rc_ports_fall_inside_the_rc_block(self):
        for port in (
            ports.DASHBOARD, ports.VISION, ports.AGENTS_SUPERVISOR,
            ports.AGENTS_WS, ports.MISSION_CONTROL,
        ):
            self.assertEqual(ports.block_for(port), "rc", f"port {port} left the RC block")

    def test_ds_ports_are_knowingly_still_in_the_rc_block(self):
        """The DS block is RESERVED, not yet occupied.

        This asserts the migration's CURRENT state rather than its target, so
        the suite stays honest about where the ports really are. When the move
        happens, this test flips to expect "ds" and the docstring in
        core/ports.py loses its MIGRATION note in the same commit.
        """
        self.assertEqual(ports.block_for(ports.DS_ENGINE), "rc")
        self.assertEqual(ports.block_for(ports.DS_MATCH_DB_MCP), "rc")
        self.assertTrue(
            set(ports.DS_BLOCK).isdisjoint(ports.ALL),
            "the reserved DS block is occupied - if the migration happened, "
            "update this test and the MIGRATION note together",
        )

    def test_live_client_is_not_claimed_by_any_block(self):
        """Riot owns 2999; a block that swallowed it would be a real collision."""
        self.assertIsNone(ports.block_for(ports.LIVE_CLIENT))
        self.assertNotIn(ports.LIVE_CLIENT, ports.ALL)

    def test_all_is_complete(self):
        """ALL must list every RC-bound port, so callers can trust it for scans."""
        named = {
            ports.DASHBOARD, ports.VISION, ports.AGENTS_SUPERVISOR, ports.AGENTS_WS,
            ports.MISSION_CONTROL, ports.DS_ENGINE, ports.DS_MATCH_DB_MCP,
        }
        self.assertEqual(ports.ALL, named)

    def test_block_for_returns_none_off_block(self):
        self.assertIsNone(ports.block_for(80))
        self.assertIsNone(ports.block_for(8896))


if __name__ == "__main__":
    unittest.main()
