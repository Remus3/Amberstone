"""A-21 / RM-90 Slice S1 - plumb ``score_by`` through the build-order layer.

The Term A ally-granted-EHP seam (``score_by="team_blended"``) shipped at ENGINE
1.220.0 and is parsed by ``POST /rank-tank`` (server.py:639-643) and forwarded by
``core.daemon_slayer_client.rank_for_primary_archetype`` (:1458, :1540). But
``core/build_order.py`` and ``core/build_order_precompute.py`` carried ZERO
``score_by`` occurrences, so neither shipped build-order table could ever emit
the seam - the plumb is purely client-side, no server change.

DEFAULT-OFF discipline. ``score_by`` defaults to ``"blended"`` (today's value) at
every new seam, and a default call must not even PUT the key in the ranker
kwargs - the negative controls below assert absence, not just equality, because
an injected ``rank_fn`` without ``**kwargs`` would otherwise start raising.

ASCII only.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import core.build_order_precompute as bop  # noqa: E402
from core.build_order import plan_build_order  # noqa: E402


class _RecordingRanker:
    """Deterministic stand-in for the DS dispatcher that records every call."""

    def __init__(self, pool=None):
        self.calls: list[dict] = []
        self._pool = pool or [
            ("3143", "Randuin's Omen", 1600.0),
            ("3083", "Warmog's Armor", 1400.0),
            ("3190", "Locket of the Iron Solari", 1200.0),
            ("3065", "Spirit Visage", 1100.0),
            ("6665", "Jak'Sho, The Protean", 1000.0),
            ("3075", "Thornmail", 900.0),
            ("3110", "Frozen Heart", 800.0),
        ]

    def __call__(self, champion, archetype, **kwargs):
        self.calls.append(dict(kwargs))
        owned = {str(i) for i in kwargs.get("item_ids") or ()}
        return {
            "ok": True,
            "scorer": "ehp",
            "archetype": archetype,
            "ranked": [
                {
                    "item_id": iid,
                    "item_name": name,
                    "delta": delta,
                    "gold": 2900,
                    "shares_dead_unique": False,
                    "dead_unique_key": "",
                    "unique_passive_key": "",
                }
                for iid, name, delta in self._pool
                if iid not in owned
            ],
            "fell_back": False,
        }


_BASE = dict(
    level=11,
    owned_item_ids=[],
    mode="SR",
    target_armor=80.0,
    target_mr=60.0,
    target_max_hp=2000.0,
    target_bonus_hp=600.0,
    slots=6,
)


class TestPlanBuildOrderScoreBy(unittest.TestCase):
    """core.build_order.plan_build_order gains a first-class ``score_by``."""

    def test_default_omits_score_by_entirely(self):
        """NEGATIVE CONTROL: an unchanged caller must be byte-identical.

        Not merely ``score_by == "blended"`` - the key must be ABSENT from the
        ranker kwargs, so a fake / older ``rank_fn`` sees the exact same call.
        """
        rk = _RecordingRanker()
        plan_build_order("Thresh", "tank", rank_fn=rk, **_BASE)
        self.assertTrue(rk.calls, "planner made no engine call")
        for call in rk.calls:
            self.assertNotIn("score_by", call)

    def test_explicit_team_blended_reaches_the_ranker_on_every_call(self):
        rk = _RecordingRanker()
        plan_build_order(
            "Thresh", "tank", rank_fn=rk, score_by="team_blended", **_BASE
        )
        self.assertTrue(rk.calls)
        for call in rk.calls:
            self.assertEqual(call.get("score_by"), "team_blended")

    def test_explicit_blended_is_still_omitted(self):
        """Passing the default value explicitly stays byte-identical."""
        rk = _RecordingRanker()
        plan_build_order("Thresh", "tank", rank_fn=rk, score_by="blended", **_BASE)
        for call in rk.calls:
            self.assertNotIn("score_by", call)

    def test_rank_kwargs_backdoor_still_works(self):
        """Pre-existing callers threading it via rank_kwargs are unaffected."""
        rk = _RecordingRanker()
        plan_build_order(
            "Thresh", "tank", rank_fn=rk,
            rank_kwargs={"score_by": "team_blended"}, **_BASE
        )
        self.assertTrue(rk.calls)
        for call in rk.calls:
            self.assertEqual(call.get("score_by"), "team_blended")

    def test_explicit_param_wins_over_rank_kwargs(self):
        """The named parameter is the authority when both are supplied."""
        rk = _RecordingRanker()
        plan_build_order(
            "Thresh", "tank", rank_fn=rk, score_by="team_blended",
            rank_kwargs={"score_by": "cc_blended"}, **_BASE
        )
        for call in rk.calls:
            self.assertEqual(call.get("score_by"), "team_blended")

    def test_order_itself_is_unchanged_by_the_plumb_under_the_fake(self):
        """The plumb forwards a knob; it must not reorder anything by itself."""
        a = plan_build_order("Thresh", "tank", rank_fn=_RecordingRanker(), **_BASE)
        b = plan_build_order(
            "Thresh", "tank", rank_fn=_RecordingRanker(),
            score_by="team_blended", **_BASE
        )
        self.assertEqual(
            [s.item_id for s in a.order], [s.item_id for s in b.order]
        )


class TestPrecomputeScoreBy(unittest.TestCase):
    """core.build_order_precompute forwards ``score_by`` down the sweep."""

    def test_compute_cell_default_omits_score_by(self):
        rk = _RecordingRanker()
        bop.compute_cell("Thresh", "mixed", archetype="tank", rank_fn=rk)
        self.assertTrue(rk.calls)
        for call in rk.calls:
            self.assertNotIn("score_by", call)

    def test_compute_cell_forwards_score_by(self):
        rk = _RecordingRanker()
        bop.compute_cell(
            "Thresh", "mixed", archetype="tank", rank_fn=rk,
            score_by="team_blended",
        )
        self.assertTrue(rk.calls)
        for call in rk.calls:
            self.assertEqual(call.get("score_by"), "team_blended")

    def test_build_orders_for_champion_forwards_score_by(self):
        rk = _RecordingRanker()
        bop.build_orders_for_champion("Thresh", rank_fn=rk, score_by="team_blended")
        self.assertTrue(rk.calls)
        for call in rk.calls:
            self.assertEqual(call.get("score_by"), "team_blended")

    def test_generate_table_forwards_score_by(self):
        rk = _RecordingRanker()
        bop.generate_table(["Thresh"], rank_fn=rk, score_by="team_blended")
        self.assertTrue(rk.calls)
        for call in rk.calls:
            self.assertEqual(call.get("score_by"), "team_blended")

    def test_generate_table_default_payload_has_no_score_by_key(self):
        """NEGATIVE CONTROL: a default regen writes a byte-identical payload."""
        payload = bop.generate_table(["Thresh"], rank_fn=_RecordingRanker())
        self.assertNotIn("score_by", payload["dimensions"])

    def test_generate_table_stamps_score_by_when_non_default(self):
        """A non-default regen is self-describing (provenance in the table)."""
        payload = bop.generate_table(
            ["Thresh"], rank_fn=_RecordingRanker(), score_by="team_blended"
        )
        self.assertEqual(payload["dimensions"].get("score_by"), "team_blended")

    def test_cli_exposes_score_by_flag(self):
        """The regen the main thread runs must be able to turn the seam on."""
        parser = bop._build_arg_parser()
        self.assertEqual(parser.parse_args([]).score_by, "blended")
        self.assertEqual(
            parser.parse_args(["--score-by", "team_blended"]).score_by,
            "team_blended",
        )

    def test_cli_rejects_an_unknown_score_by(self):
        parser = bop._build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--score-by", "drop table items"])


if __name__ == "__main__":
    unittest.main()
