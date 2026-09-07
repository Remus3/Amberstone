"""RM-118: the wielder HSP ITEM-amp reaches the HYBRID (bruiser) RANKER.

THE DEFECT
----------
``assume_hsp_amp`` shipped in ENGINE 1.171.0 (R60) on the SCALAR lanes
(``compute_ehp`` / ``compute_sustain``). On 2026-07-29 the EHP-ranker half was
wired (commit 1a2f92e7): ``rank_items_by_ehp`` -> ``POST /rank-tank`` ->
``core/daemon_slayer_client.rank_tank_for``. The HYBRID (bruiser) ranker -
``rank_items_by_hybrid`` -> ``POST /rank-bruiser`` -> ``rank_bruiser_for`` - is
the SEPARATE module that decides a bruiser item CHOICE, and it never accepted
the kwarg. So the wielder Heal-and-Shield-Power item amp (Redemption 3107,
Mikael's Blessing 3222, additive per ``_hsp_amp.sum_wielder_hsp_pct``) could not
move a single bruiser build decision. That is the remaining OPEN half RM-118
recorded after 1a2f92e7.

Same defect class + same three-gate remedy as the EHP-ranker half and R194
slice A: engine ranker -> route -> client, each asserted separately so a
name-collapsed guard cannot read this wire as done because a SIBLING route
(``/rank-tank`` / ``/ehp`` / ``/sustain``) already carries the seam.

WHY THE CREDIT IS CONDITIONAL, NOT A UNIFORM MULTIPLIER (the RM-115 inert trap)
------------------------------------------------------------------------------
``compute_ehp``'s ``shield_amp_mult`` multiplies the wielder's ItemShield POOL.
On the HSP pair ALONE that pool is empty, so arming the seam moves NO score.
It becomes a REAL, per-candidate sort input the moment a self-shield item enters
the build: a candidate that carries its own ItemShield (Sterak's Gage 3053,
Immortal Shieldbow 6673) earns an amped shield -> a higher ``new_ehp`` ->
``delta_ehp`` while a candidate with no self-shield (Randuin's Omen 3143) does
not. The hybrid ranker feeds ``delta_ehp`` into its beta-weighted score, so the
amp moves rows relative to each other - the R194 per-candidate shape, not the
RM-115 uniform-ratio shape.

DEFAULT-OFF
-----------
``rank_items_by_hybrid`` defaults ``assume_hsp_amp=False``. An omitted key is a
byte-identical response - measured below, not assumed.

OFFLINE ONLY: no live :8860, no network. Direct handler + engine + client calls.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import rank_items_by_hybrid
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)

_SEAM = "assume_hsp_amp"
_ROUTE = "/rank-bruiser"

# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
_CHAMPION = "Sett"
_LEVEL = 13
# HSP pair in the CURRENT build -> wielder HSP pct 0.22, but no self-shield in
# the prefix so the BASELINE ItemShield pool is empty and the amp lands only on
# a self-shield CANDIDATE's own pool.
_REDEMPTION, _MIKAELS = "3107", "3222"
_BUILD = (_REDEMPTION, _MIKAELS)

_STERAKS = "3053"     # self-shield candidate - amped pool -> delta moves ON
_SHIELDBOW = "6673"   # self-shield candidate
_RANDUINS = "3143"    # tank candidate, NO ItemShield pool -> invariant control

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _rank(**kwargs):
    return rank_items_by_hybrid(
        _snap(),
        champion_id=_CHAMPION,
        level=_LEVEL,
        current_item_ids=list(_BUILD),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        # No truncation (reference_ds_probe_depth_top40_truncation).
        top_n=None,
        **kwargs,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _legacy_rows(result) -> tuple[tuple, ...]:
    """Every pre-existing row field, in order - the byte-identical contract."""
    return tuple(
        (r.item_id, r.gold, r.delta_dps, r.delta_ehp, r.new_dps, r.new_ehp,
         r.hybrid_delta_pct, r.hybrid_score, r.hybrid_per_1k_gold,
         r.cc_blended_ehp, r.delta_cc_blended_ehp, r.survivability_score)
        for r in result.ranked
    )


def _row(result, item_id: str):
    for r in result.ranked:
        if r.item_id == item_id:
            return r
    raise AssertionError(f"{item_id} not in pool")


def _route_body(**extra) -> dict:
    body = {
        "champion": _CHAMPION,
        "level": _LEVEL,
        "items": list(_BUILD),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
        "top": 200,
    }
    body.update(extra)
    return body


def _route_delta(result_dict, item_id: str) -> float:
    for r in result_dict["ranked"]:
        if r["item_id"] == item_id:
            return r["delta_ehp"]
    raise AssertionError(f"{item_id} not in route pool")


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class EngineSeamExposureTests(_Base):
    """Gate 1: the ranker entry point must name the seam, DEFAULT-OFF."""

    def test_rank_items_by_hybrid_exposes_the_hsp_seam(self) -> None:
        params = inspect.signature(rank_items_by_hybrid).parameters
        self.assertIn(
            _SEAM, params,
            "rank_items_by_hybrid must forward assume_hsp_amp - the scalar /ehp "
            "lane and the /rank-tank ranker carry it while the bruiser ranker "
            "could not see it",
        )
        self.assertIs(
            params[_SEAM].default, False,
            "the seam ships DEFAULT-OFF; a True default would silently move "
            "every shipped bruiser build that owns a self-shield item",
        )


class HspReordersTests(_Base):
    """The acceptance criterion: the amp is a real per-candidate sort input."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.off = _rank()
        cls.on = _rank(**{_SEAM: True})

    def test_self_shield_candidate_delta_increases_on(self) -> None:
        for iid in (_STERAKS, _SHIELDBOW):
            with self.subTest(item=iid):
                self.assertGreater(
                    _row(self.on, iid).delta_ehp,
                    _row(self.off, iid).delta_ehp,
                    "assume_hsp_amp did not reach the hybrid ranker - a "
                    "self-shield candidate's amped ItemShield pool must raise "
                    "its delta_ehp",
                )

    def test_no_shield_candidate_is_invariant(self) -> None:
        self.assertEqual(
            _row(self.on, _RANDUINS).delta_ehp,
            _row(self.off, _RANDUINS).delta_ehp,
            "a candidate with no ItemShield pool must be untouched by the amp",
        )

    def test_the_order_actually_moves(self) -> None:
        self.assertNotEqual(
            _order(self.off), _order(self.on),
            "the amp raised a self-shield delta but reordered nothing - it must "
            "be able to change WHICH item ranks where, not just a row value",
        )


class ByteIdenticalDefaultTests(_Base):
    """The regression pin - the default path may not move one float."""

    def test_explicit_default_equals_omitted(self) -> None:
        omitted = _rank()
        explicit = _rank(**{_SEAM: False})
        self.assertEqual(_order(omitted), _order(explicit))
        self.assertEqual(_legacy_rows(omitted), _legacy_rows(explicit))


class RouteExposureTests(_Base):
    """Gate 2: POST /rank-bruiser must parse the key and forward it."""

    def test_route_absent_key_is_byte_identical(self) -> None:
        absent = server._route_rank_bruiser(_route_body())
        explicit = server._route_rank_bruiser(_route_body(**{_SEAM: False}))
        self.assertEqual(absent, explicit)

    def test_route_forwards_the_hsp_seam(self) -> None:
        off = server._route_rank_bruiser(_route_body())
        on = server._route_rank_bruiser(_route_body(**{_SEAM: True}))
        self.assertGreater(
            _route_delta(on, _STERAKS), _route_delta(off, _STERAKS),
            f"{_SEAM} was parsed but never reached rank_items_by_hybrid",
        )


class ClientWiringTests(_Base):
    """Gate 3: core/daemon_slayer_client.rank_bruiser_for must express the seam."""

    def test_signature_names_the_seam_default_off(self) -> None:
        params = inspect.signature(client_mod.rank_bruiser_for).parameters
        self.assertIn(_SEAM, params)
        self.assertIs(params[_SEAM].default, False)

    def _body(self, **kwargs) -> dict:
        seen: dict = {}

        def _fake(path, body, timeout=0.0):
            seen["path"] = path
            seen["body"] = body
            return {"ranked": []}

        with mock.patch.object(client_mod, "_post_json", _fake):
            client_mod.rank_bruiser_for(
                _CHAMPION, level=_LEVEL, item_ids=list(_BUILD), **kwargs
            )
        self.assertEqual(seen["path"], _ROUTE)
        return seen["body"]

    def test_seam_is_emitted_only_when_armed(self) -> None:
        self.assertNotIn(_SEAM, self._body())
        self.assertIs(self._body(**{_SEAM: True})[_SEAM], True)


class PerRouteStrandedSeamTests(_Base):
    """PER-(route, seam), never name-collapsed.

    ``assume_hsp_amp`` is already reachable on ``/ehp`` / ``/sustain`` /
    ``/rank-tank``, so the NAME-collapsed sibling guard would read this ranker
    wire as done the moment those landed. This asserts the PAIR
    ('/rank-bruiser', 'assume_hsp_amp').
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


if __name__ == "__main__":
    unittest.main()
