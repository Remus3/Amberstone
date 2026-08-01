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

    def test_ds_ports_live_in_the_ds_block(self):
        """Flipped 2026-08-01 (RM-129) when the migration actually landed.

        Until then this asserted "rc" on purpose, so the suite stayed honest
        about where the ports really were rather than about where they were
        going. It is kept pointing at CURRENT state for the same reason: if
        anything drags DS back inside the RC block, this fails loudly.
        """
        self.assertEqual(ports.block_for(ports.DS_ENGINE), "ds")
        self.assertEqual(ports.block_for(ports.DS_MATCH_DB_MCP), "ds")
        self.assertTrue(
            set(ports.RC_BLOCK).isdisjoint({ports.DS_ENGINE, ports.DS_MATCH_DB_MCP}),
            "a DS port is back inside the RC block - RM-129 moved them out",
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


class NextFreeTests(unittest.TestCase):
    """`next_free` must never invent a number RC has no standing to assign."""

    def test_next_free_rc_skips_every_allocated_port(self):
        got = ports.next_free("rc")
        self.assertIn(got, ports.RC_BLOCK)
        self.assertNotIn(got, ports.ALL)
        self.assertEqual(got, min(set(ports.RC_BLOCK) - ports.ALL))

    def test_next_free_ds_skips_the_two_migrated_ports(self):
        """Post-RM-129 the DS block floor is taken, so the answer moves up.

        Asserted against the allocation rather than the literal 8862: if a
        third DS service is added, this keeps telling the truth instead of
        pinning a number that quietly went stale.
        """
        got = ports.next_free("ds")
        self.assertIn(got, ports.DS_BLOCK)
        self.assertNotIn(got, ports.ALL)
        self.assertEqual(got, min(set(ports.DS_BLOCK) - ports.ALL))

    def test_sibling_blocks_refuse_to_answer_without_their_allocations(self):
        """RC does not know what LW and RM have allocated and must not guess.

        This is the whole point of the guard: a confident wrong number here
        would be handed to a sibling as "your next free port" and collide.
        """
        for block in ("lw", "rm"):
            with self.assertRaises(ValueError):
                ports.next_free(block)

    def test_sibling_blocks_answer_when_told_what_is_taken(self):
        """Lowest free in the BLOCK - which is not the same as lowest free
        next to the neighbours, and the difference bit on the first run.

        RM's five named ports are 8777 8778 8779 8780 8783 and RM described
        8781/8782 as "the free ones". Mechanically the lowest free port in
        8770-8789 is 8770, because the block floor is empty. Both statements
        are true about different questions, and a number handed to a sibling
        has to be the one THAT SIBLING would agree with - so RC states the
        arithmetic here and lets RM pick, rather than quietly redefining it.
        """
        taken = {8777, 8778, 8779, 8780, 8783}
        self.assertEqual(ports.next_free("rm", taken=taken), 8770)
        self.assertEqual(ports.next_free("rm", taken=taken | set(range(8770, 8777))), 8781)

    def test_unknown_block_raises(self):
        with self.assertRaises(KeyError):
            ports.next_free("nope")


if __name__ == "__main__":
    unittest.main()
