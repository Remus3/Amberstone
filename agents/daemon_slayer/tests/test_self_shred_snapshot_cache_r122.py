"""Regression guard: self_shred reuses the process-wide cached abilities
snapshot instead of re-reading + re-parsing the ~3MB champion_abilities.json
on every call.

compute_self_shred_uplift runs once per /v2/fight-report request (via
fight_report.compute_fight_report, which passes snapshot=None). Every other
production abilities consumer (ability_dps, ability_hps, burst, server) reads
the snapshot through abilities.load_default() - the module-level singleton -
so a coach tick parses the file at most once. self_shred was the lone caller
of the uncached classmethod AbilitiesSnapshot.load(), re-parsing the whole
file each request. These tests pin the cached read (call-count) and prove the
change is output-identical (same resolved uplift across repeated calls).
"""
from __future__ import annotations

import unittest
from unittest import mock

from agents.daemon_slayer.abilities import AbilitiesSnapshot, reset_default_cache
from agents.daemon_slayer.self_shred import compute_self_shred_uplift


def _call() -> object:
    # Nasus E is a real armor pct shred, so this exercises the full resolve
    # path (snapshot load -> get_abilities -> shred selection), not just the
    # early-return no-shred branch.
    return compute_self_shred_uplift(
        "Nasus", 18, target_armor=100.0, target_mr=50.0,
        champion_physical_dps=200.0,
    )


class SnapshotCachedReadTests(unittest.TestCase):
    def setUp(self) -> None:
        # Deterministic cold cache so the first load_default() read is counted.
        reset_default_cache()

    def test_disk_snapshot_read_once_across_repeated_calls(self) -> None:
        with mock.patch.object(
            AbilitiesSnapshot, "load", wraps=AbilitiesSnapshot.load
        ) as spy:
            for _ in range(3):
                _call()
            # Cached path: the snapshot is parsed exactly once regardless of
            # how many fight-report requests resolve a self-shred. Pre-fix
            # (uncached AbilitiesSnapshot.load per call) this was 3.
            self.assertEqual(spy.call_count, 1)

    def test_repeated_calls_return_identical_result(self) -> None:
        results = [_call() for _ in range(3)]
        for r in results[1:]:
            self.assertEqual(r, results[0])
        # Sanity: the shred actually resolved (guards against silently
        # exercising the no-shred branch if Nasus data shifts).
        self.assertEqual(results[0].shred_source, "Nasus:E")


if __name__ == "__main__":
    unittest.main()
