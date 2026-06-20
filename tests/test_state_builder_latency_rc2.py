"""RC2 6.5 - state-pipeline latency reduction.

build_state() opens two independent localhost relay round-trips:
``lcu_summary()`` (champ-select / lobby, needed immediately) and
``liveclient_summary()`` (in-game fields, not needed until the overlay
merge well below). Historically they ran back-to-back, stacking two
~1s-timeout waits on the /api/state critical path. 6.5 overlaps the
liveclient round-trip with the lcu + coach-file work so its latency
leaves the serial path.

We mock at the relay boundary (``lcu_summary`` / ``liveclient_summary``)
plus ``read_json`` / ``get_team_context`` / ``validate_coaching_payload``
so the test never touches disk or the network. Both summaries sleep, and
``time.sleep`` releases the GIL, so overlapped execution is real (not an
artifact of mock cheapness).
"""
from __future__ import annotations

import time
import unittest
from unittest import mock

from dashboard import _state_builder


def _patches(self, *, lcu_delay=0.0, lc_delay=0.0,
             lcu_payload=None, lc_payload=None, health=None, coach=None):
    health = health if health is not None else {"mode": "client"}
    coach = coach if coach is not None else {"action": ""}

    def _read_json(p):
        if "health" in str(p):
            return health
        return coach

    def _lcu():
        if lcu_delay:
            time.sleep(lcu_delay)
        return lcu_payload or {}

    def _lc():
        if lc_delay:
            time.sleep(lc_delay)
        return lc_payload or {}

    patches = [
        mock.patch.object(_state_builder, "read_json", side_effect=_read_json),
        mock.patch.object(_state_builder, "lcu_summary", side_effect=_lcu),
        mock.patch.object(_state_builder, "liveclient_summary", side_effect=_lc),
        mock.patch.object(_state_builder, "get_team_context", return_value=None),
        mock.patch.object(_state_builder, "validate_coaching_payload",
                          lambda *_a, **_kw: None),
    ]
    for p in patches:
        p.start()
        self.addCleanup(p.stop)


class StatePipelineLatencyTests(unittest.TestCase):

    def test_liveclient_overlaps_lcu(self):
        """The two independent relay round-trips run concurrently, not
        serially. Proven by ordering, not total wall-clock: the liveclient
        call must START before the lcu call FINISHES. (Total build time is
        confounded by cold-import cost of the deterministic/cooldowns
        stages, so a wall-clock threshold is unreliable; the start/end
        ordering of the two relays is the clean signal.)"""
        ev: dict[str, float] = {}

        def _lcu():
            ev["lcu_start"] = time.monotonic()
            time.sleep(0.15)
            ev["lcu_end"] = time.monotonic()
            return {}

        def _lc():
            ev["lc_start"] = time.monotonic()
            time.sleep(0.15)
            ev["lc_end"] = time.monotonic()
            return {"champion": "Ahri"}

        def _read_json(p):
            return {"mode": "client"} if "health" in str(p) else {"action": ""}

        for p in (
            mock.patch.object(_state_builder, "read_json", side_effect=_read_json),
            mock.patch.object(_state_builder, "lcu_summary", side_effect=_lcu),
            mock.patch.object(_state_builder, "liveclient_summary", side_effect=_lc),
            mock.patch.object(_state_builder, "get_team_context", return_value=None),
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda *_a, **_kw: None),
        ):
            p.start()
            self.addCleanup(p.stop)

        _state_builder.build_state()
        self.assertEqual(set(ev), {"lcu_start", "lcu_end", "lc_start", "lc_end"})
        self.assertLess(
            ev["lc_start"], ev["lcu_end"],
            "liveclient_summary started only after lcu_summary finished - "
            "the two relay round-trips ran serially, not overlapped",
        )

    def test_overlap_preserves_liveclient_merge(self):
        """Overlapping must not change the result: liveclient fields still
        land in state['liveclient'] and overlay onto blank coach slots."""
        _patches(
            self,
            lc_payload={"champion": "Caitlyn", "game_time": "5:00", "level": 7},
            coach={"action": "", "game_time": "", "level": 0},
        )
        state = _state_builder.build_state()
        self.assertEqual(state["liveclient"]["champion"], "Caitlyn")
        # blank coach slots filled from the liveclient overlay
        self.assertEqual(state["coach"]["game_time"], "5:00")
        self.assertEqual(state["coach"]["level"], 7)

    def test_no_game_still_empty(self):
        """Both relays empty (no game) -> build still succeeds, liveclient
        is the empty dict, no overlay keys injected."""
        _patches(self, lcu_payload={}, lc_payload={})
        state = _state_builder.build_state()
        self.assertEqual(state["liveclient"], {})
        self.assertEqual(state["mode_key"], "client")


if __name__ == "__main__":
    unittest.main()
