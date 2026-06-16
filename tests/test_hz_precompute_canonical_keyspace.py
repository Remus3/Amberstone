"""HZ precompute canonical-keyspace guard + renamed-champ resolution.

Root cause (this slice): the HZ-A laning table was canonicalized (item 388) but
the HZ-B1 build_orders + HZ-B2 build_order_variants tables were generated with
raw DISPLAY-name keys, and the precompute reader modules did NOT canonicalize
their champion lookup keys. The live shadow path (dashboard._deterministic_
coaching) passes the raw Live Client display name ("Wukong", "Aurelion Sol",
"Tahm Kench"), so every renamed / multi-word champion silently MISSED the
canonical-keyed laning table - as my_champion AND as an enemy. These tests pin
the canonical-everywhere invariant: every committed table is canonical-keyed and
the readers normalize any display-name input to its canonical DDragon id.
"""
import unittest

from core.archetype_picks import canonical_champion_id
from core.build_order_precompute import load_build_order_precompute
from core.build_order_variants import load_build_order_variants
from core.laning_scenario_precompute import load_laning_scenarios
from core import precomputed_build_coach as pbc
from core import precomputed_laning_coach as plc

_MODES = ("sr", "aram", "arena")


def _is_canonical(key: str) -> bool:
    return bool(key) and canonical_champion_id(key) == key


class CommittedTableKeyspaceTests(unittest.TestCase):
    """Every committed HZ precompute table is keyed by canonical DDragon ids."""

    def _assert_canonical_top_keys(self, payload, top, label):
        if not payload:
            self.skipTest(f"no committed {label} table for this patch")
        keys = list((payload.get(top) or {}).keys())
        self.assertTrue(keys, f"{label}: empty table")
        bad = [k for k in keys if not _is_canonical(k)]
        self.assertEqual(
            bad, [],
            f"{label}: {len(bad)} non-canonical (display-name) keys, e.g. "
            f"{bad[:5]} - regenerate with canonical ids",
        )

    def test_build_orders_tables_are_canonical_keyed(self):
        for mode in _MODES:
            self._assert_canonical_top_keys(
                load_build_order_precompute(mode), "build_orders",
                f"build_orders/{mode}")

    def test_build_order_variants_tables_are_canonical_keyed(self):
        for mode in _MODES:
            self._assert_canonical_top_keys(
                load_build_order_variants(mode), "build_orders",
                f"build_order_variants/{mode}")

    def test_laning_scenarios_tables_are_canonical_keyed(self):
        for mode in _MODES:
            self._assert_canonical_top_keys(
                load_laning_scenarios(mode), "scenarios",
                f"laning_scenarios/{mode}")


class ReaderCanonicalizesDisplayInputTests(unittest.TestCase):
    """The readers normalize a raw Live Client DISPLAY name to canonical so a
    renamed champ resolves against the canonical-keyed tables (the real bug).

    Uses synthetic canonical-keyed payloads so the assertion is deterministic
    and independent of the committed seed contents.
    """

    def test_laning_reader_canonicalizes_my_champion_and_enemy(self):
        band = plc.band_for_level(6)
        mana = plc.mana_state_for(None)
        cd = plc.cd_state_for(None)
        payload = {"scenarios": {"MonkeyKing": {"TahmKench": {
            band: {mana: {cd: {"verdict": "trade", "net_swing": 5}}}}}}}
        # display my_champion ("Wukong") AND display enemy ("Tahm Kench") must
        # canonicalize for the table lookup; resolve_enemy returns the covered
        # enemy verbatim (display form) so the A/B label + shadow log stay
        # human-readable.
        self.assertEqual(
            plc.resolve_enemy("Wukong", ["Tahm Kench"], "sr", payload=payload),
            "Tahm Kench",
            "display-name my_champion did not canonicalize in resolve_enemy",
        )
        cc = plc.precomputed_choices(
            "Wukong", "Tahm Kench", 6, mode="sr", payload=payload)
        self.assertTrue(
            cc, "display my_champion/enemy did not resolve a laning cell")

    def test_build_reader_canonicalizes_my_champion(self):
        payload = {"build_orders": {"MonkeyKing": {
            "anti_tank": {"variant": "anti_tank", "order": ["3047"],
                          "antitank": {}},
            "anti_squishy": {"variant": "anti_squishy", "order": ["3006"],
                             "antitank": {}}}}}
        # tank wall -> anti_tank lean; "Wukong" must canonicalize to MonkeyKing
        cc = pbc.build_choices(
            "Wukong", ["Malphite", "Ornn", "Sion"], "sr", payload=payload)
        self.assertEqual(
            len(cc), 2,
            "display my_champion did not resolve a build variant pair")

    def test_canonical_input_still_resolves(self):
        # idempotence: a canonical id passes through unchanged.
        payload = {"build_orders": {"MonkeyKing": {
            "anti_tank": {"variant": "anti_tank", "order": ["3047"],
                          "antitank": {}},
            "anti_squishy": {"variant": "anti_squishy", "order": ["3006"],
                             "antitank": {}}}}}
        cc = pbc.build_choices(
            "MonkeyKing", ["Malphite", "Ornn", "Sion"], "sr", payload=payload)
        self.assertEqual(len(cc), 2)


if __name__ == "__main__":
    unittest.main()
