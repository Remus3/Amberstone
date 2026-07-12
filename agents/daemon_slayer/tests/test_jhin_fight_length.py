"""RED-first: Jhin lethality-crit burst via the per-champ fight_length blend.

Engine-side half (core-free: imports ONLY agents.daemon_slayer so the Share
mirror copy runs standalone). Two things are proven here:

  1. VALUE: rank_items(fight_length=0.5) for Jhin surfaces his real meta
     lethality-crit core (Hubris / The Collector / Youmuu's / Serylda's, with
     Infinity Edge the retained crit core) that the SUSTAINED default buries,
     re-verified on the AS-lock baseline (ENGINE 1.204.0 -> 1.205.0).
  2. SERVER PLUMBING: POST /rank (_route_rank) parses + forwards a body
     ``fight_length`` so the live coach / backfill path can engage the blend;
     a body that OMITS it is byte-identical to the default ranking.

The client-side allow-map wiring (Jhin -> 0.5, controls byte-identical) lives in
tests/test_jhin_fight_length_wiring.py (that half needs core imports).
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.rank import rank_items

# Jhin's real-meta lethality-crit core (spec-grounded) + the retained crit core.
_LETHALITY = ("Hubris", "The Collector", "Youmuu's Ghostblade", "Serylda's Grudge")
# The PURE-lethality trio: no crit, so the SUSTAINED default really buries them
# (The Collector is excluded here - its crit component keeps it ~#12 even in the
# sustained default, so it is not a clean discriminator for the "buried" claim).
_PURE_LETHALITY = ("Hubris", "Youmuu's Ghostblade", "Serylda's Grudge")
_CRIT_CORE = "Infinity Edge"
_JHIN_FL = 0.5  # allow-map value, re-verified post-AS-lock (see core.ds_champion_fight_length)

_LEVEL = 13
_ARMOR = 80.0


def _dedup_names(result) -> list[str]:
    """Ranked item NAMES, dedup by name (alias item ids duplicate a name)."""
    seen: set[str] = set()
    out: list[str] = []
    for r in result.ranked:
        if r.item_name not in seen:
            seen.add(r.item_name)
            out.append(r.item_name)
    return out


def _pos(names: list[str], item: str):
    return (names.index(item) + 1) if item in names else None


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snap = DataSnapshot.load()
        server._CACHE.set(cls.snap)

    def _jhin_names(self, fight_length):
        res = rank_items(
            self.snap, champion_id="Jhin", level=_LEVEL, current_item_ids=[],
            mode="SR", target_armor=_ARMOR, top_n=60, fight_length=fight_length,
        )
        return _dedup_names(res)


class RankItemsValueTests(_Base):
    def test_fl_surfaces_lethality_crit_core(self) -> None:
        names = self._jhin_names(_JHIN_FL)
        # Infinity Edge (crit core) retained near the top.
        ie = _pos(names, _CRIT_CORE)
        self.assertIsNotNone(ie, f"{_CRIT_CORE} missing entirely")
        self.assertLessEqual(ie, 8, f"{_CRIT_CORE} at {ie}, expected top 8")
        # The full lethality core surfaces into the top of the list.
        for item in _LETHALITY:
            p = _pos(names, item)
            self.assertIsNotNone(p, f"{item} missing entirely at fl={_JHIN_FL}")
            self.assertLessEqual(
                p, 13, f"{item} at position {p}, expected top 13 at fl={_JHIN_FL}",
            )

    def test_sustained_default_buries_pure_lethality(self) -> None:
        # fl=None (the byte-identical default) leaves the PURE-lethality trio deep
        # in the list - proving the knob (not luck) does the surfacing work.
        names = self._jhin_names(None)
        for item in _PURE_LETHALITY:
            p = _pos(names, item)
            self.assertTrue(
                p is None or p > 15,
                f"{item} at {p} in the SUSTAINED default (expected >15 / absent)",
            )

    def test_fl_lifts_each_lethality_item_vs_default(self) -> None:
        # The knob strictly improves EVERY lethality item's position vs the
        # sustained default (the robust, data-tolerant form of the claim).
        blended = self._jhin_names(_JHIN_FL)
        default = self._jhin_names(None)
        big = 10_000

        def rank(names, item):
            return _pos(names, item) or big

        for item in _LETHALITY:
            self.assertLess(
                rank(blended, item), rank(default, item),
                f"{item}: fl={_JHIN_FL} pos {rank(blended, item)} not better than "
                f"default pos {rank(default, item)}",
            )

    def test_fl_reorders_top8_vs_default(self) -> None:
        # The knob must actually change the ranking (not a no-op).
        self.assertNotEqual(
            self._jhin_names(_JHIN_FL)[:8], self._jhin_names(None)[:8],
        )


class RouteRankPlumbingTests(_Base):
    def _route_names(self, body) -> list[str]:
        out = server._route_rank(body)
        seen: set[str] = set()
        names: list[str] = []
        for r in out["ranked"]:
            nm = r.get("item_name", "")
            if nm not in seen:
                seen.add(nm)
                names.append(nm)
        return names

    def test_route_rank_forwards_fight_length(self) -> None:
        # A body carrying fight_length engages the blend -> lethality surfaces.
        names = self._route_names({
            "champion": "Jhin", "level": _LEVEL, "target_armor": _ARMOR,
            "top": 60, "fight_length": _JHIN_FL,
        })
        for item in _LETHALITY:
            p = _pos(names, item)
            self.assertIsNotNone(p, f"{item} missing via _route_rank fight_length")
            self.assertLessEqual(p, 13, f"{item} at {p} via _route_rank")

    def test_route_rank_omitting_fight_length_is_default(self) -> None:
        # No fight_length in the body -> byte-identical to the rank_items default.
        route = self._route_names({
            "champion": "Jhin", "level": _LEVEL, "target_armor": _ARMOR, "top": 60,
        })
        direct = self._jhin_names(None)
        self.assertEqual(route, direct)


if __name__ == "__main__":
    unittest.main()
