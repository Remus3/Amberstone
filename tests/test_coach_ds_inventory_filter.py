"""The ARAM / Arena / Brawl coaches must hand the DS dispatcher an INVENTORY
list, not a raw slot list.

Root cause (third instance found this run; two prior slices fixed the dashboard
layer): trinkets and consumables are serialized inline with shop items by the
Live Client API, so a raw ``resolve_many`` over ``state["items"]`` reports a
phantom occupied slot. The SR coach (``coach_integration/_coach.py``) has used
the filtered ``resolve_inventory`` entry point since s156; these three coaches
were never brought across.

Two consumers share the same list, so the defect is not cosmetic:

  * ``dispatch_for_coach(item_ids=...)`` - the engine is asked to rank against a
    slot budget that a potion is occupying, and can refuse the call outright
    once the 6-slot budget is exhausted by non-items.
  * ``ds_calibration.log_ds_run(owned_items=...)`` - the same list is persisted,
    so every polluted tick also writes a permanently wrong calibration row.

Each test drives the real ``_run_coach`` with a hand-built state whose inventory
mixes genuine build items with a trinket, potions and an elixir, captures what
the dispatcher was actually handed, and asserts the build items survived while
every ``NON_INVENTORY_IDS`` member was dropped. Asserting BOTH directions is
what keeps the test from passing on an empty list.
"""

from __future__ import annotations

import unittest
from unittest import mock

from core.daemon_slayer_resolver import NON_INVENTORY_IDS

# Inventory the coaches are driven with. The first two are real build items and
# must survive; the rest are the non-inventory rows and must not. Chosen because
# each resolves to a NON_INVENTORY_IDS member under every resolver mode - the
# ARAM/Arena maps index re-points some ward names, so a name that filters under
# "sr" alone would make the Arena/Brawl assertions vacuous.
_BUILD_NAMES = ["Berserker's Greaves", "Kraken Slayer"]
_NON_INVENTORY_NAMES = [
    "Health Potion",
    "Refillable Potion",
    "Elixir of Wrath",
    "Farsight Alteration",
    "Control Ward",
]
_ITEMS = _BUILD_NAMES + _NON_INVENTORY_NAMES


class _StubClient:
    """Truthy so the ``if not self._client: return`` guard passes.

    The DS block runs before any model call, so failing the Haiku call after the
    capture is the cheapest way to stop the tick; ``@safe_coach_output`` absorbs
    it and the assertions run on what was already captured.
    """

    class messages:  # noqa: N801 - mirrors the anthropic client attribute name
        @staticmethod
        def create(*_a, **_k):
            raise RuntimeError("no model call in this test")


def _run_and_capture(coach, state):
    """Invoke ``_run_coach`` and return the item_ids the dispatcher was given."""
    seen: dict = {}

    def _fake_dispatch(**kwargs):
        seen["item_ids"] = list(kwargs.get("item_ids") or [])
        return None

    with mock.patch(
        "coach_integration.archetype_dispatch.dispatch_for_coach", _fake_dispatch
    ):
        coach._run_coach(state)

    assert "item_ids" in seen, (
        "the dispatcher was never reached - the test harness broke before the "
        "DS block, so a passing assertion below would be vacuous"
    )
    return seen["item_ids"]


class _FilterAssertions(unittest.TestCase):
    """Shared both-directions assertion for the three coaches."""

    def assert_filtered(self, item_ids):
        leaked = [i for i in item_ids if i in NON_INVENTORY_IDS]
        self.assertEqual(
            [], leaked,
            f"non-inventory ids reached the DS dispatcher: {leaked}",
        )
        self.assertGreaterEqual(
            len(item_ids), len(_BUILD_NAMES),
            f"the real build items were dropped too: {item_ids}",
        )


class ARAMCoachInventoryFilterTests(_FilterAssertions):
    def _coach(self):
        from coaches.aram_coach import Coach as ARAMCoach

        coach = object.__new__(ARAMCoach)
        coach._client = _StubClient()
        coach._vision_state = {}
        return coach

    def test_dispatcher_gets_inventory_only(self):
        state = {
            "champion": "Kalista",
            "game_mode": "ARAM",
            "level": 11,
            "items": _ITEMS,
            "enemy_comp": ["Ashe", "Annie", "Leona", "Malphite", "Sett"],
            "game_seconds": 900,
            "hp": 850,
            "hp_max": 1000,
        }
        self.assert_filtered(_run_and_capture(self._coach(), state))


class ArenaCoachInventoryFilterTests(_FilterAssertions):
    def _coach(self):
        from coaches.arena_coach import Coach as ArenaCoach

        coach = object.__new__(ArenaCoach)
        coach._client = _StubClient()
        coach._vision_state = {}
        coach._event_round_count = 4
        return coach

    def test_dispatcher_gets_inventory_only(self):
        state = {
            "champion": "Kalista",
            "level": 11,
            "items": _ITEMS,
            "enemy_comp": ["Ashe", "Annie"],
            "game_seconds": 600,
            "teams": [{"name": "You", "is_you": True, "hp_pct": 90}],
            "augments": [],
            "hp": 850,
            "hp_max": 1000,
        }
        self.assert_filtered(_run_and_capture(self._coach(), state))


class BrawlCoachInventoryFilterTests(_FilterAssertions):
    def _coach(self):
        from coaches.brawl_coach import Coach as BrawlCoach

        coach = object.__new__(BrawlCoach)
        coach._client = _StubClient()
        coach._vision_state = {}
        return coach

    def test_dispatcher_gets_inventory_only(self):
        state = {
            "champion": "Kalista",
            "game_mode": "BRAWL",
            "level": 11,
            "items": _ITEMS,
            "enemy_comp": ["Ashe", "Annie"],
            "game_seconds": 600,
            "hp": 850,
            "hp_max": 1000,
        }
        self.assert_filtered(_run_and_capture(self._coach(), state))


if __name__ == "__main__":
    unittest.main()
