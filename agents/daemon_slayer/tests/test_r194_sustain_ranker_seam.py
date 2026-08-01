"""R194 slice A (RM-116 part a): the EHP SUSTAIN axis reaches the RANKER.

THE DEFECT
----------
``compute_ehp`` has carried ``assume_max_stacks_omnivamp`` since 2026-07-10
(ehp.py) and R193 slice C wired it onto ``POST /ehp`` and
``core/daemon_slayer_client.ehp_for``. That is the SCALAR lane only. The
RANKER lane - ``rank_items_by_ehp`` / ``POST /rank-tank`` /
``core/daemon_slayer_client.rank_tank_for`` - did not accept the kwarg at all,
and its ``score_by`` allowlist was ``("blended", "cc_blended", "team_blended")``
with no sustain member. So the one place the credit can change an OPERATOR
DECISION (which item to buy next) could not see it: the omnivamp heal lands on
``effective_ehp_with_sustain`` / ``sustain_ehp_delta`` and NEVER on
``blended_ehp``, which is the only quantity the ranker sorted on.

WHY score_by="sustain" IS A REAL SORT CRITERION AND NOT AN ALIAS
---------------------------------------------------------------
The RM-115 inert-seam trap is a UNIFORM MULTIPLIER on the EHP numerator: a
ratio sort key is invariant under it, so the seam measures non-zero per row and
still cannot reorder. This one is not that shape. ``_blend_with_heal`` adds the
vamp heal pool as an ADDEND to the numerator, and the addend is per-CANDIDATE
(only a candidate that carries omnivamp earns one), so it moves rows relative
to each other.

MEASURED 2026-07-26, ENGINE 1.256.0, Amumu L13, mode SR, prefix Sunfire Aegis
3068 + Plated Steelcaps 3047, shares 0.50/0.50, top_n=None (pool 138):

  assume_max_stacks_omnivamp=True
    Riftmaker 4633            blended rank 43  ->  sustain rank 35
    Rylai's Crystal Scepter 3116  blended rank 35  ->  sustain rank 36

  4633 delta_ehp          734.1252302631583  (UNMOVED by the credit)
  4633 delta_sustain_ehp  849.3574186147398  (the +115.2 omnivamp heal, amped
                                              through the same resist curve)
  3116 delta_ehp == delta_sustain_ehp == 839.0002631578955 (no omnivamp)

The 4633 / 3116 pair FLIPS: 3116 outranks 4633 on blended, 4633 outranks 3116
on sustain. That is the acceptance criterion for "a real, distinct sort
criterion".

DEFAULT-OFF
-----------
With the omnivamp credit OFF, ``effective_ehp_with_sustain == blended_ehp`` on
every current build (no shipped item resolves a spellvamp or omnivamp STAT), so
score_by="sustain" produces the byte-identical blended ORDER - measured below,
not assumed. The mode is therefore the ``cc_blended`` shape: an identity until
its feeding seam is armed, never a silent behavior change.

OFFLINE ONLY: no live :8860, no network.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import rank_items_by_ehp
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)

_SEAM = "assume_max_stacks_omnivamp"
_ROUTE = "/rank-tank"

# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
# Same champion + prefix as test_assumed_share_exposure.py so the two pins are
# directly comparable.
_CHAMPION = "Amumu"
_LEVEL = 13
_BUILD = ("3068", "3047")

_RIFTMAKER = "4633"      # the only pooled SR carrier of item-passive omnivamp
_RYLAI = "3116"          # the named neighbour it must overtake, omnivamp-free

# Measured at the params in the module docstring.
_RIFT_DELTA_EHP = 734.1252302631583
_RIFT_DELTA_SUSTAIN = 849.3574186147398
_RYLAI_DELTA_EHP = 839.0002631578955

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _rank(**kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=_CHAMPION,
        level=_LEVEL,
        current_item_ids=list(_BUILD),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        # No truncation (reference_ds_probe_depth_top40_truncation): top_n is
        # applied AFTER the sort, so a finite cut changes WHICH rows survive and
        # the two orders stop being comparable.
        top_n=None,
        **kwargs,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _legacy_rows(result) -> tuple[tuple, ...]:
    """Every row field that existed BEFORE this slice, in order.

    The byte-identical contract is about these values and their ordering. The
    two new fields are additive (the Term A ``team_blended_ehp`` precedent).
    """
    return tuple(
        (r.item_id, r.gold, r.delta_ehp, r.new_ehp, r.ehp_per_1k_gold,
         r.cc_blended_ehp, r.delta_cc_blended_ehp, r.survivability_score,
         r.team_blended_ehp, r.delta_team_blended_ehp,
         r.delta_armor, r.delta_mr)
        for r in result.ranked
    )


def _route_body(**extra) -> dict:
    body = {
        "champion": _CHAMPION,
        "level": _LEVEL,
        "items": list(_BUILD),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
        "top": 50,
    }
    body.update(extra)
    return body


def _rank_of(order: tuple[str, ...], item_id: str) -> int:
    return order.index(item_id)


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class EngineSeamExposureTests(_Base):
    """RED-1: the ranker entry point must name the seam and the new mode."""

    def test_rank_items_by_ehp_exposes_the_omnivamp_seam(self) -> None:
        params = inspect.signature(rank_items_by_ehp).parameters
        self.assertIn(
            _SEAM, params,
            "rank_items_by_ehp must forward assume_max_stacks_omnivamp - the "
            "scalar /ehp lane has carried it since R193 slice C",
        )
        self.assertIs(
            params[_SEAM].default, False,
            "the seam ships DEFAULT-OFF; a True default would silently move "
            "every shipped tank build",
        )

    def test_score_by_sustain_is_accepted(self) -> None:
        result = _rank(score_by="sustain")
        self.assertEqual(result.score_by, "sustain")

    def test_unknown_score_by_still_raises(self) -> None:
        with self.assertRaises(ValueError):
            _rank(score_by="omnivamp")


class SustainReordersTests(_Base):
    """The acceptance criterion: sustain is a DISTINCT sort criterion."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.blended_on = _order(_rank(**{_SEAM: True}))
        cls.sustain_on = _order(_rank(score_by="sustain", **{_SEAM: True}))

    def test_riftmaker_overtakes_rylai_only_under_sustain(self) -> None:
        self.assertGreater(
            _rank_of(self.blended_on, _RIFTMAKER),
            _rank_of(self.blended_on, _RYLAI),
            "blended must still rank Rylai's ABOVE Riftmaker - the omnivamp "
            "credit is sustain-only and may never touch blended_ehp",
        )
        self.assertLess(
            _rank_of(self.sustain_on, _RIFTMAKER),
            _rank_of(self.sustain_on, _RYLAI),
            "score_by=sustain did not reorder - the omnivamp heal never "
            "reached the sort key",
        )

    def test_measured_ranks_are_pinned(self) -> None:
        self.assertEqual(_rank_of(self.blended_on, _RIFTMAKER), 42)
        self.assertEqual(_rank_of(self.sustain_on, _RIFTMAKER), 34)
        self.assertEqual(_rank_of(self.blended_on, _RYLAI), 34)
        self.assertEqual(_rank_of(self.sustain_on, _RYLAI), 35)

    def test_row_values_carry_the_credit_on_the_sustain_field_only(self) -> None:
        rows = {r.item_id: r for r in _rank(score_by="sustain", **{_SEAM: True}).ranked}
        rift = rows[_RIFTMAKER]
        self.assertEqual(rift.delta_ehp, _RIFT_DELTA_EHP)
        self.assertEqual(rift.delta_sustain_ehp, _RIFT_DELTA_SUSTAIN)
        rylai = rows[_RYLAI]
        self.assertEqual(rylai.delta_ehp, _RYLAI_DELTA_EHP)
        self.assertEqual(
            rylai.delta_sustain_ehp, _RYLAI_DELTA_EHP,
            "an omnivamp-free candidate must sit at the sustain identity",
        )

    def test_efficiency_sort_also_tracks_the_sustain_delta(self) -> None:
        """The per-1k column is the second half of the sort key, not decor."""
        rows = {
            r.item_id: r
            for r in _rank(score_by="sustain", sort_by="efficiency",
                           **{_SEAM: True}).ranked
        }
        rift = rows[_RIFTMAKER]
        self.assertAlmostEqual(
            rift.ehp_per_1k_gold, _RIFT_DELTA_SUSTAIN / (rift.gold / 1000.0),
            places=9,
            msg="efficiency was priced off delta_ehp while the sort ranked on "
                "the sustain delta - the two halves of the key disagree",
        )


class ByteIdenticalDefaultTests(_Base):
    """The regression pin - the default path may not move one float."""

    def test_explicit_defaults_equal_omitted(self) -> None:
        omitted = _rank()
        explicit = _rank(score_by="blended", **{_SEAM: False})
        self.assertEqual(_order(omitted), _order(explicit))
        self.assertEqual(_legacy_rows(omitted), _legacy_rows(explicit))

    def test_new_row_fields_sit_at_the_blended_identity_by_default(self) -> None:
        for r in _rank().ranked:
            self.assertEqual(r.delta_sustain_ehp, r.delta_ehp, r.item_id)
            self.assertEqual(r.sustain_ehp, r.new_ehp, r.item_id)

    def test_omnivamp_on_does_not_move_the_blended_order(self) -> None:
        """The credit is sustain-only - arming it may not touch blended_ehp."""
        off = _rank()
        on = _rank(**{_SEAM: True})
        self.assertEqual(_order(off), _order(on))
        self.assertEqual(_legacy_rows(off), _legacy_rows(on))

    def test_sustain_without_the_credit_is_the_blended_order(self) -> None:
        """MEASURED, not assumed: no shipped item resolves a vamp STAT, so the
        sustain metric collapses onto blended until the seam is armed."""
        self.assertEqual(_order(_rank()), _order(_rank(score_by="sustain")))

    def test_default_to_dict_keeps_every_legacy_key(self) -> None:
        row = _rank().ranked[0].to_dict()
        legacy = {
            "item_id", "item_name", "gold", "delta_ehp", "new_ehp",
            "ehp_per_1k_gold", "is_terminal", "tags", "shares_dead_unique",
            "dead_unique_key", "unique_passive_key", "cc_blended_ehp",
            "delta_cc_blended_ehp", "survivability_score", "team_blended_ehp",
            "delta_team_blended_ehp", "delta_armor", "delta_mr",
        }
        self.assertEqual(legacy - set(row), set())
        self.assertEqual(row["delta_sustain_ehp"], row["delta_ehp"])


class RouteExposureTests(_Base):
    """Gate 2: POST /rank-tank must parse BOTH transports and forward them."""

    def test_route_accepts_and_honors_score_by_sustain(self) -> None:
        blended = server._route_rank_tank(_route_body(**{_SEAM: True}))
        sustain = server._route_rank_tank(
            _route_body(score_by="sustain", **{_SEAM: True})
        )
        b = tuple(r["item_id"] for r in blended["ranked"])
        s = tuple(r["item_id"] for r in sustain["ranked"])
        self.assertNotEqual(
            b, s, "the route parsed score_by=sustain but never forwarded it"
        )
        self.assertEqual(sustain["score_by"], "sustain")

    def test_route_rejects_an_unknown_score_by(self) -> None:
        with self.assertRaises(server._ApiError) as ctx:
            server._route_rank_tank(_route_body(score_by="omnivamp"))
        self.assertEqual(ctx.exception.status, 400)

    def test_route_forwards_the_omnivamp_seam(self) -> None:
        off = server._route_rank_tank(_route_body(score_by="sustain"))
        on = server._route_rank_tank(
            _route_body(score_by="sustain", **{_SEAM: True})
        )
        self.assertNotEqual(
            tuple(r["item_id"] for r in off["ranked"]),
            tuple(r["item_id"] for r in on["ranked"]),
            f"{_SEAM} was parsed but never reached rank_items_by_ehp",
        )

    def test_route_absent_keys_are_byte_identical(self) -> None:
        absent = server._route_rank_tank(_route_body())
        explicit = server._route_rank_tank(
            _route_body(score_by="blended", **{_SEAM: False})
        )
        self.assertEqual(absent, explicit)


class ClientWiringTests(_Base):
    """Gate 3: core/daemon_slayer_client.rank_tank_for must express both."""

    def test_signature_names_the_seam_default_off(self) -> None:
        params = inspect.signature(client_mod.rank_tank_for).parameters
        self.assertIn(_SEAM, params)
        self.assertIs(params[_SEAM].default, False)

    def _body(self, **kwargs) -> dict:
        seen: dict = {}

        def _fake(path, body, timeout=0.0):
            seen["path"] = path
            seen["body"] = body
            return {"ranked": []}

        with mock.patch.object(client_mod, "_post_json", _fake):
            client_mod.rank_tank_for(
                _CHAMPION, level=_LEVEL, item_ids=list(_BUILD), **kwargs
            )
        self.assertEqual(seen["path"], _ROUTE)
        return seen["body"]

    def test_seam_is_emitted_only_when_armed(self) -> None:
        self.assertNotIn(_SEAM, self._body())
        self.assertIs(self._body(**{_SEAM: True})[_SEAM], True)

    def test_score_by_sustain_is_emitted(self) -> None:
        self.assertNotIn("score_by", self._body())
        self.assertEqual(self._body(score_by="sustain")["score_by"], "sustain")

    def test_row_parser_surfaces_the_active_sustain_delta(self) -> None:
        """Dropping the ACTIVE field is how a live re-rank reads as inert."""
        row = client_mod.TankRankedItem.from_dict(
            {"item_id": _RIFTMAKER, "delta_ehp": _RIFT_DELTA_EHP,
             "delta_sustain_ehp": _RIFT_DELTA_SUSTAIN}
        )
        self.assertEqual(row.delta_sustain_ehp, _RIFT_DELTA_SUSTAIN)
        fallback = client_mod.TankRankedItem.from_dict(
            {"item_id": _RIFTMAKER, "delta_ehp": _RIFT_DELTA_EHP}
        )
        self.assertEqual(fallback.delta_sustain_ehp, _RIFT_DELTA_EHP)


class PerRouteStrandedSeamTests(_Base):
    """PER-(route, seam), never name-collapsed.

    ``assume_max_stacks_omnivamp`` is already reachable on ``/ehp``, so the
    NAME-collapsed sibling guard would read the ranker wire as done the moment
    R193 slice C landed - the exact collapse that let ``/rank-assassin`` stay
    stranded while the guard was green. This asserts the PAIR.
    """

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.parsed, _ = _route_table()
        cls.client = _client_by_route()

    def test_the_pair_is_parsed_by_the_route(self) -> None:
        self.assertIn(_SEAM, self.parsed[_ROUTE])

    def test_the_pair_is_expressible_by_the_client_function(self) -> None:
        self.assertIn(_SEAM, self.client[_ROUTE])

    def test_the_non_prefixed_score_by_transport_agrees_end_to_end(self) -> None:
        """``score_by`` carries no seam prefix, so the AST guards are BLIND to
        it. It has been stranded before, and a sustain mode the route rejects
        would be reachable-and-dead."""
        self.assertIn("score_by", self.parsed[_ROUTE] | self.client[_ROUTE],
                      "score_by is not even seam-shaped - assert it directly")
        # engine side accepts it
        self.assertEqual(_rank(score_by="sustain").score_by, "sustain")
        # route side accepts it
        out = server._route_rank_tank(_route_body(score_by="sustain"))
        self.assertEqual(out["score_by"], "sustain")
        # client side emits it
        params = inspect.signature(client_mod.rank_tank_for).parameters
        self.assertIn("score_by", params)


if __name__ == "__main__":
    unittest.main()
