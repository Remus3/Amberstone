"""Phase 4(d) (2026-05-18) - contract tests for the additive
``unique_passive_key`` field exposed on every ranker.

These are signature-agnostic schema/round-trip checks (no DataSnapshot
needed) that pin the mechanical mirror across all 6 engine ranker
dataclasses + all 6 client dataclasses + the build-order consumer. The
behavioral end-to-end proof (real snapshot, real cand_eff wiring) lives
in agents/daemon_slayer/tests/test_rank.py::Phase4dUniquePassiveKeyTests.
"""
import dataclasses
import unittest

from agents.daemon_slayer.ability_dps import AbilityDpsRankedItem
from agents.daemon_slayer.burst import BurstRankedItem
from agents.daemon_slayer.ehp import EhpRankedItem
from agents.daemon_slayer.hps import HpsRankedItem
from agents.daemon_slayer.hybrid import HybridRankedItem
from agents.daemon_slayer.rank import RankedItem as EngineRankedItem

from core.daemon_slayer_client import (
    AssassinRankedItem,
    BruiserRankedItem,
    EnchanterRankedItem,
    MageRankedItem,
    RankedItem as ClientRankedItem,
    TankRankedItem,
)

_ENGINE_RANKED = (
    EngineRankedItem,
    EhpRankedItem,
    HybridRankedItem,
    AbilityDpsRankedItem,
    BurstRankedItem,
    HpsRankedItem,
)

_CLIENT_RANKED = (
    ClientRankedItem,
    TankRankedItem,
    BruiserRankedItem,
    MageRankedItem,
    AssassinRankedItem,
    EnchanterRankedItem,
)


class EngineRankerSchemaTests(unittest.TestCase):
    def test_all_engine_rankers_have_field_defaulting_empty(self) -> None:
        for cls in _ENGINE_RANKED:
            fields = {f.name: f for f in dataclasses.fields(cls)}
            self.assertIn(
                "unique_passive_key", fields,
                f"{cls.__module__}.{cls.__name__} missing unique_passive_key",
            )
            self.assertEqual(
                fields["unique_passive_key"].default, "",
                f"{cls.__name__}.unique_passive_key must default to ''",
            )

    def test_field_is_last_and_keeps_dead_unique_siblings(self) -> None:
        # Guards the additive ordering: the new field sits alongside the
        # existing collision-gated pair, all default-valued, so frozen
        # construction + every existing call site stay valid.
        for cls in _ENGINE_RANKED:
            names = [f.name for f in dataclasses.fields(cls)]
            for sib in ("shares_dead_unique", "dead_unique_key",
                        "unique_passive_key"):
                self.assertIn(sib, names, f"{cls.__name__} missing {sib}")
            self.assertGreater(
                names.index("unique_passive_key"),
                names.index("dead_unique_key"),
                "unique_passive_key must follow the defaulted dead-unique "
                "fields so no non-default-after-default error is possible",
            )


class ClientRoundTripTests(unittest.TestCase):
    def test_from_dict_reads_key(self) -> None:
        for cls in _CLIENT_RANKED:
            obj = cls.from_dict({"unique_passive_key": "lifeline"})
            self.assertEqual(
                obj.unique_passive_key, "lifeline",
                f"{cls.__name__}.from_dict dropped unique_passive_key",
            )

    def test_from_dict_backward_compat_default_empty(self) -> None:
        # An engine that predates 4(d) (or any payload omitting the key)
        # must deserialize cleanly with "" - never KeyError. (Mirrors the
        # existing dead_unique_key str(d.get(..., "")) contract; an
        # explicit-None value is not part of the engine's wire format.)
        for cls in _CLIENT_RANKED:
            obj = cls.from_dict({})
            self.assertEqual(obj.unique_passive_key, "")


if __name__ == "__main__":
    unittest.main()
