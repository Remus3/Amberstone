"""Regression: plan_build_order must never emit >=2 items from the same
MaxGroupOwnable:1 percent-penetration family (found 2026-07-12).

Two in-game exclusivity groups carry a percent-pen effect the DS engine used
to double-count because the ITEM_EFFECTS entries had an empty
``unique_passive_key`` - the engine's ONLY no-double hook (rank_items
``filter_shared_uniques`` + collect_effects dedup, both keyed on
``unique_passive_key``):

* LastWhisper (armor %pen)  -> Lord Dominik's 3036 / Mortal Reminder 3033 /
  Serylda's 6694 (+ Arena mirrors 223036 / 223033 / 226694). REPORTED: Jhin
  (and ~9 other AD carries) got LDR + Mortal Reminder + Serylda's vs tanks.
* VoidPen (magic %pen)      -> Void Staff 3135 / Cryptbloom 3137 (+ Arena
  mirrors 223135 / 223137). SIBLING found in the same sweep: a mage vs a
  high-MR target got Void Staff + Cryptbloom.

plan_build_order does NO dedup of its own - it delegates to the engine via
``filter_shared_uniques=True``. This test drives it through an in-process
adapter that mirrors ``rank_for_primary_archetype`` (same routing + envelope)
so the genuine engine math is exercised with no live :8860 server. The pen
only matters at resist>0, so both cases pass a non-zero enemy resist.
"""
from __future__ import annotations

import unittest

from agents.daemon_slayer.ability_dps import rank_items_by_ability_dps
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.rank import rank_items
from core.build_order import plan_build_order

# Completed members of each MaxGroupOwnable:1 pen family (components 3035 /
# 4630 are intentionally excluded - keying them would block the legitimate
# component -> completed upgrade recommendation, and the bug is completed-item
# doubles).
LAST_WHISPER = {"3036", "3033", "6694", "223036", "223033", "226694"}
VOID_PEN = {"3135", "3137", "223135", "223137"}


def _make_adapter(snapshot: DataSnapshot):
    """rank_fn mirroring rank_for_primary_archetype (carry->dps, mage->ability).

    Unlike the p1l5 adapter this threads the enemy resist block into BOTH
    branches - the armor/magic pen the bug hinges on is worthless at resist 0.
    """

    def adapter(champion, archetype, **kw):
        arch = (archetype or "").strip().lower()
        common = dict(
            level=kw["level"],
            current_item_ids=kw.get("item_ids") or [],
            mode=kw.get("mode", "SR"),
            top_n=kw.get("top", 8),
            sort_by=kw.get("sort_by", "delta"),
            filter_shared_uniques=kw.get("filter_shared_uniques", True),
            target_armor=kw.get("target_armor", 0.0),
            target_mr=kw.get("target_mr", 0.0),
            target_max_hp=kw.get("target_max_hp", 0.0),
            target_bonus_hp=kw.get("target_bonus_hp", 0.0),
        )
        if arch == "mage":
            r = rank_items_by_ability_dps(snapshot, champion, **common)
            scorer = "ability"
            delta = lambda x: x.delta_ability_dps  # noqa: E731
        else:
            r = rank_items(snapshot, champion, **common)
            scorer = "dps"
            delta = lambda x: x.delta_dps  # noqa: E731
        return {
            "ok": True,
            "scorer": scorer,
            "archetype": arch,
            "fell_back": False,
            "ranked": [
                {
                    "item_id": x.item_id,
                    "item_name": x.item_name,
                    "delta": delta(x),
                    "gold": x.gold,
                    "shares_dead_unique": x.shares_dead_unique,
                    "dead_unique_key": x.dead_unique_key,
                    "unique_passive_key": x.unique_passive_key,
                }
                for x in r.ranked
            ],
        }

    return adapter


class DoublePenMutexTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        cls.adapter = staticmethod(_make_adapter(cls.snap))

    def _order_ids(self, champion, archetype, **kw):
        res = plan_build_order(
            champion, archetype, owned_item_ids=[], slots=6,
            rank_fn=self.__class__.adapter, **kw,
        )
        self.assertIsNotNone(res, f"plan_build_order returned None for {champion}")
        return [str(s.item_id) for s in res.order]

    def test_jhin_never_double_last_whisper(self):
        ids = self._order_ids("Jhin", "carry", level=18, mode="SR", target_armor=150.0)
        hits = [i for i in ids if i in LAST_WHISPER]
        self.assertLessEqual(
            len(hits), 1,
            f"Jhin build vs armor emitted >=2 LastWhisper-family items: {hits} in {ids}",
        )

    def test_syndra_never_double_void_pen(self):
        ids = self._order_ids("Syndra", "mage", level=18, mode="SR", target_mr=150.0)
        hits = [i for i in ids if i in VOID_PEN]
        self.assertLessEqual(
            len(hits), 1,
            f"Syndra build vs MR emitted >=2 VoidPen-family items: {hits} in {ids}",
        )

    def test_no_order_shares_a_unique_passive_key(self):
        """General invariant across a spread of champs/archetypes: no two items
        in a planned order share a non-empty unique_passive_key."""
        cases = [
            ("Jhin", "carry", dict(target_armor=150.0)),
            ("Rengar", "assassin", dict(target_armor=150.0)),
            ("Graves", "carry", dict(target_armor=120.0)),
            ("Syndra", "mage", dict(target_mr=150.0)),
            ("Lux", "mage", dict(target_mr=120.0)),
        ]
        for champ, arch, ctx in cases:
            with self.subTest(champ=champ):
                ids = self._order_ids(champ, arch, level=18, mode="SR", **ctx)
                seen: dict[str, str] = {}
                for iid in ids:
                    eff = ITEM_EFFECTS.get(iid)
                    key = getattr(eff, "unique_passive_key", "") if eff else ""
                    if key:
                        self.assertNotIn(
                            key, seen,
                            f"{champ}: items {seen.get(key)} and {iid} share "
                            f"unique_passive_key={key!r} in order {ids}",
                        )
                        seen[key] = iid


if __name__ == "__main__":
    unittest.main()
