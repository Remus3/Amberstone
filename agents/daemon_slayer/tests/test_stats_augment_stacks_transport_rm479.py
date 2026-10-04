"""RM-479: POST /stats must transport ``augment_stacks`` to ``build_champion``.

ENGINE 1.282.0 gave ``build_champion`` an ``augment_stacks`` kwarg (Tap Dancer
on-hit move-speed stacks, default ``ASSUMED_TAP_DANCER_STACKS``). /stats
forwarded ``augments`` but dropped the stack count, so a caller always got the
default - recorded as named debt in ``tests/test_ds_parity_map.py``. This pins
the TRANSPORT (route body -> engine), not only that the engine accepts it.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.augments import ASSUMED_TAP_DANCER_STACKS
from agents.daemon_slayer.data_loader import DataSnapshot


def _stats(body: dict) -> dict:
    return server._POST_ROUTES["/stats"](dict(body))


class StatsAugmentStacksTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            server._CACHE.get()
        except RuntimeError:
            server._CACHE.set(DataSnapshot.load())

    _BASE = {"champion": "Vayne", "level": 18, "mode": "ARENA",
             "augments": ["TapDancer"]}

    def test_stack_count_reaches_the_engine(self) -> None:
        zero = _stats({**self._BASE, "augment_stacks": {"TapDancer": 0}})
        many = _stats({**self._BASE, "augment_stacks": {"TapDancer": 20}})
        self.assertGreater(many["stats"]["ms"], zero["stats"]["ms"])

    def test_omitted_is_byte_identical_to_the_documented_default(self) -> None:
        omitted = _stats(self._BASE)
        explicit = _stats({**self._BASE, "augment_stacks": {
            "TapDancer": ASSUMED_TAP_DANCER_STACKS}})
        self.assertEqual(omitted, explicit)

    def test_null_is_the_default(self) -> None:
        self.assertEqual(_stats({**self._BASE, "augment_stacks": None}),
                         _stats(self._BASE))

    def test_bad_shapes_are_a_400(self) -> None:
        for bad in ([1, 2], "TapDancer", 5, {"TapDancer": "lots"},
                    {"TapDancer": float("inf")}):
            with self.assertRaises(server._ApiError) as cm:
                _stats({**self._BASE, "augment_stacks": bad})
            self.assertEqual(cm.exception.status, 400, bad)


if __name__ == "__main__":
    unittest.main()
