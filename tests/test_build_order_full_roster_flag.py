"""Tests for the ``--champions all`` full-roster expansion (R77 ergonomic fix).

Both build-order generators (``core.build_order_precompute`` HZ-B1 and
``core.build_order_variants`` HZ-B2) default their sweep to the 10-champ
``SEED_CHAMPIONS`` sample. Omitting ``--champions`` on a regen silently uses
that seed - the "static seed footgun" that has staled the committed HZ-B tables
before. This module characterizes the fix: a single ``--champions all`` flag
that expands the sweep to the FULL canonical roster, while every other path
(explicit CSV, empty default) is byte-for-byte unchanged.

Hermetic: the roster resolver reads the committed DS champion registry
(``data/daemon_slayer/<patch>/champions.json``) off disk - no :8860, no network,
no table generation. The resolver is imported + called directly.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.build_order_precompute as bop  # noqa: E402
import core.build_order_variants as bov  # noqa: E402


class FullRosterResolverTests(unittest.TestCase):
    """``full_roster()`` yields the whole canonical roster, not the seed."""

    def test_full_roster_is_the_full_canonical_roster(self):
        roster = bop.full_roster()
        # ~173 champions on a live patch; guard well above the 10-champ seed.
        self.assertGreaterEqual(len(roster), 170)
        # Canonical DDragon ids, incl. an id whose display name differs
        # (Bel'Veth -> "Belveth") to prove the id form is sourced.
        self.assertIn("Annie", roster)
        self.assertIn("Belveth", roster)

    def test_full_roster_is_a_superset_of_the_seed(self):
        # The seed sample is a subset of the full roster (the seed champs are
        # all id-form display names), so expanding never DROPS a seed champ.
        roster = set(bop.full_roster())
        self.assertTrue(set(bop.SEED_CHAMPIONS) <= roster)

    def test_full_roster_is_sorted_and_deduped(self):
        roster = bop.full_roster()
        self.assertEqual(roster, sorted(roster))
        self.assertEqual(len(roster), len(set(roster)))


class ResolveChampionsTests(unittest.TestCase):
    """``resolve_champions()`` maps the CLI value: all / csv / empty->seed."""

    def test_all_token_yields_full_roster(self):
        resolved = bop.resolve_champions("all")
        self.assertEqual(resolved, bop.full_roster())
        self.assertGreaterEqual(len(resolved), 170)
        self.assertIn("Annie", resolved)
        self.assertIn("Belveth", resolved)

    def test_all_token_is_not_the_seed(self):
        resolved = bop.resolve_champions("all")
        self.assertNotEqual(len(resolved), len(bop.SEED_CHAMPIONS))
        self.assertNotEqual(set(resolved), set(bop.SEED_CHAMPIONS))

    def test_all_token_is_case_insensitive(self):
        full = len(bop.full_roster())
        for token in ("ALL", "All", " all ", "aLL"):
            self.assertEqual(
                len(bop.resolve_champions(token)), full, f"token={token!r}"
            )

    def test_empty_yields_seed_backward_compat(self):
        # The CRITICAL backward-compat guard: an EMPTY --champions must still
        # default to SEED_CHAMPIONS (unchanged), never the full roster.
        self.assertEqual(
            tuple(bop.resolve_champions("")), tuple(bop.SEED_CHAMPIONS)
        )

    def test_whitespace_only_yields_seed(self):
        self.assertEqual(
            tuple(bop.resolve_champions("   ")), tuple(bop.SEED_CHAMPIONS)
        )

    def test_explicit_csv_parses_verbatim(self):
        # An explicit CSV is parsed as today - NOT expanded to the roster.
        self.assertEqual(bop.resolve_champions("Ahri, Zed"), ["Ahri", "Zed"])
        self.assertEqual(bop.resolve_champions("Lux"), ["Lux"])


class VariantsMirrorTests(unittest.TestCase):
    """HZ-B2 reuses the SAME shared resolver (DRY - one source of truth)."""

    def test_variants_reuses_shared_resolver(self):
        self.assertIs(bov.resolve_champions, bop.resolve_champions)

    def test_variants_all_token_yields_full_roster(self):
        self.assertEqual(bov.resolve_champions("all"), bop.full_roster())

    def test_variants_empty_yields_seed(self):
        self.assertEqual(
            tuple(bov.resolve_champions("")), tuple(bop.SEED_CHAMPIONS)
        )


if __name__ == "__main__":
    unittest.main()
