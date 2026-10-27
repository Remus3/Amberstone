"""RM-959 - /v2/fight-report rejects an out-of-range level with 422.

Before the fix ``_route_fight_report`` passed any level straight into
``compute_fight_report``, which only normalises ``< 1 -> 1`` and is fail-soft
by contract. Level 19+ therefore answered HTTP 200 with a zeroed report
(bounded_dps 0.0, resource_type "Unknown", three "section failed" notes),
while every sibling engine route (/dps, /burst, /ehp, ...) answers 422 through
``stats.clamp_level``. Level -1 was silently computed as level 1.

Pinned here:
  * level 19 / 25 / -1 -> 422, and the sections never run;
  * level 0 -> the route-wide ``or 1`` idiom (computed as level 1, pinned by
    tests/test_server_display_consistency_p1l25.py), unchanged;
  * levels 1 and 18 are byte-identical to a direct ``compute_fight_report``.

ASCII only.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.fight_report import compute_fight_report
from agents.daemon_slayer.stats import LEVEL_MAX, LEVEL_MIN

_CHAMP = "Ahri"
_ITEMS = ["3089"]


def _body(level: object) -> dict:
    return {"champion": _CHAMP, "level": level, "items": list(_ITEMS)}


class FightReportLevelBoundTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)

    def _status(self, route, body: dict) -> int:
        try:
            route(body)
        except server._ApiError as e:
            return e.status
        return 200

    def test_above_level_max_is_422(self) -> None:
        for level in (LEVEL_MAX + 1, 25):
            with self.subTest(level=level):
                self.assertEqual(
                    self._status(server._route_fight_report, _body(level)), 422)

    def test_negative_level_is_422(self) -> None:
        self.assertEqual(
            self._status(server._route_fight_report, _body(LEVEL_MIN - 2)), 422)

    def test_matches_sibling_dps_route(self) -> None:
        # The reference behaviour the fix aligns with: /dps rejects the same
        # levels through stats.clamp_level.
        for level in (LEVEL_MAX + 1, 25, LEVEL_MIN - 2):
            with self.subTest(level=level):
                self.assertEqual(self._status(server._route_dps, _body(level)),
                                 self._status(server._route_fight_report,
                                              _body(level)))

    def test_rejected_before_sections_run(self) -> None:
        with mock.patch.object(server, "compute_fight_report") as fake:
            with self.assertRaises(server._ApiError):
                server._route_fight_report(_body(25))
        fake.assert_not_called()

    def test_level_zero_keeps_or_one_idiom(self) -> None:
        out = server._route_fight_report(_body(0))
        self.assertEqual(out["level"], 1)

    def test_in_range_byte_identical(self) -> None:
        for level in (LEVEL_MIN, LEVEL_MAX):
            with self.subTest(level=level):
                via_route = server._route_fight_report(_body(level))
                direct = compute_fight_report(
                    _CHAMP, level, item_ids=list(_ITEMS), runes=[],
                    mode="SR", snapshot=self.snap).to_dict()
                self.assertEqual(json.dumps(via_route, sort_keys=True),
                                 json.dumps(direct, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
