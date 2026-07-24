"""RM-04 A-01 - carry candidate-pool widen seam (DEFAULT-OFF).

PREMISE (measured 2026-07-24 against ENGINE 1.241.0 / patch 16.14.1, live
:8893 and in-process ``rank._filter_candidates``):

  * The SR carry candidate pool is 108 items (NOT the 111 the filing quotes)
    and is SET-IDENTICAL across Caitlyn / Jinx / Ashe / Sivir / Senna /
    Smolder / Ezreal.
  * Black Cleaver (3071), Spear of Shojin (3161), Stridebreaker (6631) and
    Sterak's Gage (3053) are excluded by the item-213 ranged-marksman
    off-class NAME deny-set ``rank.OFFCLASS_MARKSMAN_ITEM_NAMES``
    (rank.py:83-127), applied via ``_filter_candidates(exclude_names=...)``
    at rank.py:1044 / rank.py:711-712.
  * Bloodsong (3877) is excluded by a DIFFERENT mechanism -
    ``rank._SR_EXCLUDED_ITEM_IDS`` (rank.py:170-188), the RM-93 support-quest
    deny. That deny is deliberate and MEASURED (admitting it put Bloodsong at
    #2 for Vel'Koz / #3 for Jinx - an RM-92 non-output mispricing), so the
    widen seam does NOT resurrect it. Pinned below.
  * Eclipse (6692) IS admitted at the default - it is not in either deny.

The seam ``rank_items(widen_carry_pool=True)`` un-strips
``rank.CARRY_POOL_WIDEN_ITEM_NAMES`` from the off-class deny for EVERY ranged
marksman. It is broader than the pre-existing DSP2 per-champion
``exempt_offclass_by_win`` table (4 tabled champions, and no Stridebreaker /
Sterak's Gage entry anywhere in it).

Assertions are difference-of-behavior (ON vs OFF) and id-level reachability -
never fragile cross-item magnitude equality. Ids are asserted BY ID, since the
Arena mirror aliases (223071 / 223161 / 226631 / 223053) share the display
name and are map-filtered off SR.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import rank as rank_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items

_SNAP = DataSnapshot.load()

# Canonical SR ids for the filing's named items (verified by id against the
# DDragon snapshot: purchasable=True, maps["11"]=True, terminal).
BLACK_CLEAVER_ID = "3071"
SHOJIN_ID = "3161"
STRIDEBREAKER_ID = "6631"
STERAKS_ID = "3053"
BLOODSONG_ID = "3877"
ECLIPSE_ID = "6692"

WIDEN_IDS = (BLACK_CLEAVER_ID, SHOJIN_ID, STRIDEBREAKER_ID, STERAKS_ID)

# The seven marksmen the filing claims share one byte-identical pool.
COHORT = ("Caitlyn", "Jinx", "Ashe", "Sivir", "Senna", "Smolder", "Ezreal")

# Sweep-standard tanky target (a zero-HP target nullifies every %max-HP term).
TARGET = dict(
    target_armor=100.0,
    target_mr=60.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
)


def _rank(champ: str, **kw):
    return rank_items(
        _SNAP,
        champ,
        level=16,
        current_item_ids=[],
        mode="SR",
        top_n=None,
        **TARGET,
        **kw,
    )


def _ids(res) -> tuple[str, ...]:
    return tuple(r.item_id for r in res.ranked)


def _rows(res) -> tuple[tuple, ...]:
    """Full row fingerprint - proves byte-identity, not just ordering."""
    return tuple(
        (r.item_id, r.item_name, r.delta_dps, r.dps_per_1k_gold,
         r.effective_score, r.gold)
        for r in res.ranked
    )


class WidenSetShapeTests(unittest.TestCase):
    def test_widen_set_is_ascii_frozenset(self) -> None:
        s = rank_mod.CARRY_POOL_WIDEN_ITEM_NAMES
        self.assertIsInstance(s, frozenset)
        self.assertTrue(s)
        for n in s:
            self.assertTrue(n.isascii(), n)

    def test_widen_set_is_a_subset_of_the_deny_set(self) -> None:
        # Un-stripping a name the deny-set never stripped would be a no-op.
        self.assertTrue(
            rank_mod.CARRY_POOL_WIDEN_ITEM_NAMES
            <= rank_mod.OFFCLASS_MARKSMAN_ITEM_NAMES
        )

    def test_widen_set_carries_the_four_filed_offclass_names(self) -> None:
        for name in ("Black Cleaver", "Spear of Shojin", "Stridebreaker",
                     "Sterak's Gage"):
            self.assertIn(name, rank_mod.CARRY_POOL_WIDEN_ITEM_NAMES, name)


class PremiseTests(unittest.TestCase):
    """The filing's own claims, re-measured by id."""

    def test_pool_is_identical_across_the_seven_marksmen(self) -> None:
        pools = {c: frozenset(_ids(_rank(c))) for c in COHORT}
        base = pools[COHORT[0]]
        for champ in COHORT[1:]:
            self.assertEqual(pools[champ], base, champ)

    def test_named_items_are_excluded_at_default_by_id(self) -> None:
        base = frozenset(_ids(_rank("Senna")))
        for iid in (*WIDEN_IDS, BLOODSONG_ID):
            self.assertNotIn(iid, base, iid)

    def test_eclipse_is_admitted_at_default_by_id(self) -> None:
        self.assertIn(ECLIPSE_ID, frozenset(_ids(_rank("Senna"))))


class DefaultOffByteIdentityTests(unittest.TestCase):
    def test_omitted_equals_explicit_false_for_the_cohort(self) -> None:
        for champ in COHORT:
            self.assertEqual(
                _rows(_rank(champ)),
                _rows(_rank(champ, widen_carry_pool=False)),
                champ,
            )

    def test_default_off_leaves_the_widen_ids_unreachable(self) -> None:
        for champ in COHORT:
            pool = frozenset(_ids(_rank(champ, widen_carry_pool=False)))
            for iid in WIDEN_IDS:
                self.assertNotIn(iid, pool, f"{champ}/{iid}")


class WidenOnTests(unittest.TestCase):
    def test_all_four_ids_are_reachable_when_on(self) -> None:
        for champ in COHORT:
            pool = frozenset(_ids(_rank(champ, widen_carry_pool=True)))
            for iid in WIDEN_IDS:
                self.assertIn(iid, pool, f"{champ}/{iid}")

    def test_pool_grows_by_exactly_four(self) -> None:
        for champ in COHORT:
            off = frozenset(_ids(_rank(champ)))
            on = frozenset(_ids(_rank(champ, widen_carry_pool=True)))
            self.assertEqual(on - off, frozenset(WIDEN_IDS), champ)
            self.assertEqual(off - on, frozenset(), champ)

    def test_arena_mirror_aliases_do_not_leak_onto_sr(self) -> None:
        # Alias-proof: the 22xxxx / 226xxx mirrors are maps["11"]=False.
        on = frozenset(_ids(_rank("Senna", widen_carry_pool=True)))
        for alias in ("223071", "223161", "226631", "223053"):
            self.assertNotIn(alias, on, alias)

    def test_bloodsong_stays_denied_when_on(self) -> None:
        # RM-93 deny is a different mechanism (_SR_EXCLUDED_ITEM_IDS) and is
        # deliberately NOT widened - a 400g mutually-exclusive quest-progression
        # upgrade ranked against 3000g legendaries is a category error.
        for champ in ("Senna", "Smolder"):
            on = frozenset(_ids(_rank(champ, widen_carry_pool=True)))
            self.assertNotIn(BLOODSONG_ID, on, champ)

    def test_melee_champion_is_unaffected(self) -> None:
        # The gate only fires for ranged marksmen, so a melee bruiser is a
        # byte-identical no-op with the seam ON.
        self.assertEqual(
            _rows(_rank("Irelia")),
            _rows(_rank("Irelia", widen_carry_pool=True)),
        )

    def test_composes_with_the_dsp2_exempt_table(self) -> None:
        # Senna's DSP2 exemption is Black Cleaver only; the widen adds the
        # other three on top without dropping it.
        both = frozenset(_ids(_rank(
            "Senna", widen_carry_pool=True, exempt_offclass_by_win=True)))
        for iid in WIDEN_IDS:
            self.assertIn(iid, both, iid)


class RouteSurfaceTests(unittest.TestCase):
    """/rank accepts the flag and threads it to rank_items."""

    BODY = {
        "champion": "Senna", "level": 16, "mode": "SR", "top": 200,
        "target_armor": 100, "target_mr": 60,
        "target_max_hp": 2500, "target_bonus_hp": 1200,
    }

    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_SNAP)

    def test_omitted_equals_explicit_false(self) -> None:
        a = server._route_rank(dict(self.BODY))
        b = server._route_rank(dict(self.BODY, widen_carry_pool=False))
        self.assertEqual(a, b)

    def test_route_on_reaches_the_four_ids(self) -> None:
        on = server._route_rank(dict(self.BODY, widen_carry_pool=True))
        got = {row["item_id"] for row in on["ranked"]}
        for iid in WIDEN_IDS:
            self.assertIn(iid, got, iid)


if __name__ == "__main__":
    unittest.main()
