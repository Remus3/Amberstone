"""The three ASSUMED-INCOMING-SHARE seams, exposed end to end (engine + route).

THE DEFECT
----------
``compute_ehp`` arms three champion-blind assumption flags DEFAULT-ON:

  * ``assume_item_crit_dr``       (Randuin's 30 pct crit-damage reduction)
  * ``assume_item_aa_dr``         (Plated Steelcaps 10 pct basic-attack DR)
  * ``assume_item_enemy_as_slow`` (Frozen Heart 20 pct enemy attack-speed slow)

Each folds a MODULE CONSTANT share of incoming physical damage
(``_ASSUMED_INCOMING_CRIT_SHARE`` / ``_ASSUMED_INCOMING_AA_SHARE``, both 0.5)
into the physical EHP denominator. The share is the same 0.5 for every champion
in the game - there is no live crit-share or auto-attack-share feed - so it is a
global operator assumption, not a measurement.

Before this change ``rank_items_by_ehp`` did not expose ANY of the three, and
``_route_rank_tank`` parsed none of them, so no HTTP caller and no
``core/daemon_slayer_client`` caller could turn the assumption off. The three
were arm-only: a seam with no OFF switch above ``compute_ehp``.

WHY IT MATTERS (measured, Amumu L13, mode SR, prefix 3068 + 3047, shares
0.50/0.50):

  Randuin's 3143   dEHP 2419.95 armed -> 1616.30 forced off  (+49.7 pct)
  Frozen Heart 3110     1209.37       ->  774.11             (+56.2 pct)
  Warmog's 3083         2097.50       -> 2031.24             (+3.3 pct)

and the ranked head flips outright: 3143 leads the DEFAULT order and falls to
rank 6 with the three forced off. 28 champions currently share one
byte-identical shipped SR ``mixed`` order led by 3143.

WHAT THIS FILE GUARDS
---------------------
1. RED-1: the three names are in ``rank_items_by_ehp``'s signature.
2. RED-2: a ``/rank-tank``-shaped body carrying the three keys False produces a
   DIFFERENT head than the default body (the route no longer ignores them).
3. GREEN regression pin: OMITTING the keys is byte-identical to the shipped
   default - same ranked order, same row values, to the last float bit. This is
   the whole safety property of the change.
4. NAMED NEGATIVE CONTROL: Warmog's Armor 3083 is a PURE-HP item with no
   crit-DR, no basic-attack DR and no enemy AS-slow. Flipping the flags may move
   it only through the shared blended denominator - measured +3.3 pct. If it ever
   moves like Randuin's (+49.7 pct) the wiring landed on the wrong denominator,
   so the assertion is deliberately a tight 3.5 pct tripwire, not a loose bound.

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

_SEAMS = (
    "assume_item_crit_dr",
    "assume_item_aa_dr",
    "assume_item_enemy_as_slow",
)

# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
# Sunfire Aegis + Plated Steelcaps is a real early-tank prefix, and Steelcaps is
# itself an aa-DR carrier so the baseline build exercises the seam, not just the
# candidate rows.
_BUILD = ("3068", "3047")
_CHAMPION = "Amumu"
_LEVEL = 13

# Measured 2026-07-25 on ENGINE 1.249.0 at the params above. The FULL default
# top-8 order; 3143 leads.
_DEFAULT_TOP8 = ("3143", "3083", "3084", "6665", "2504", "3053", "4401", "663058")
# The same probe with all three seams forced OFF - Randuin's falls to rank 6.
_FORCED_OFF_TOP8 = ("3083", "3084", "2504", "6665", "3053", "3143", "4401", "663058")

# Exact shipped row values at the default (the byte-identical pin).
_DEFAULT_DELTA_EHP = {
    "3143": 2419.9494469814244,   # Randuin's Omen
    "3110": 1209.365929824562,    # Frozen Heart
    "3083": 2097.5006578947377,   # Warmog's Armor - the negative control
}

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
        # the ON/OFF row sets stop being comparable.
        top_n=None,
        **kwargs,
    )


def _order(result) -> tuple[str, ...]:
    return tuple(r.item_id for r in result.ranked)


def _deltas(result) -> dict[str, float]:
    return {r.item_id: r.delta_ehp for r in result.ranked}


def _rows(result) -> tuple[tuple, ...]:
    return tuple(
        (r.item_id, r.delta_ehp, r.new_ehp, r.ehp_per_1k_gold,
         r.cc_blended_ehp, r.delta_cc_blended_ehp, r.team_blended_ehp,
         r.delta_team_blended_ehp)
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
        "top": 8,
    }
    body.update(extra)
    return body


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class SignatureExposureTests(_Base):
    """RED-1: the engine entry point must name all three seams."""

    def test_rank_items_by_ehp_exposes_all_three_seams(self) -> None:
        params = inspect.signature(rank_items_by_ehp).parameters
        missing = [s for s in _SEAMS if s not in params]
        self.assertEqual(
            missing, [],
            "rank_items_by_ehp must expose the assumed-share seams; missing "
            f"{missing}",
        )

    def test_seams_default_to_true_so_shipped_behavior_is_unchanged(self) -> None:
        params = inspect.signature(rank_items_by_ehp).parameters
        for seam in _SEAMS:
            self.assertIs(
                params[seam].default, True,
                f"{seam} must default True - compute_ehp arms it, and a False "
                "default here would silently change every shipped tank build",
            )


class RouteExposureTests(_Base):
    """RED-2: the /rank-tank route must actually consume the three keys."""

    def test_route_forced_off_reorders_the_head(self) -> None:
        default = server._route_rank_tank(_route_body())
        forced_off = server._route_rank_tank(
            _route_body(**{s: False for s in _SEAMS})
        )
        d_order = tuple(r["item_id"] for r in default["ranked"])
        f_order = tuple(r["item_id"] for r in forced_off["ranked"])
        self.assertEqual(d_order, _DEFAULT_TOP8)
        self.assertEqual(f_order, _FORCED_OFF_TOP8)
        self.assertNotEqual(
            d_order[0], f_order[0],
            "the route ignored the assumed-share keys - head did not move",
        )

    def test_route_each_seam_is_independently_honored(self) -> None:
        default = server._route_rank_tank(_route_body())
        base = {r["item_id"]: r["delta_ehp"] for r in default["ranked"]}
        # Randuin's carries crit-DR; Steelcaps (in the PREFIX) carries aa-DR, so
        # turning either off must move 3143's delta. Frozen Heart is not in the
        # top-8 head, so assert on the two that are.
        for seam in ("assume_item_crit_dr", "assume_item_aa_dr"):
            out = server._route_rank_tank(_route_body(**{seam: False}))
            got = {r["item_id"]: r["delta_ehp"] for r in out["ranked"]}
            self.assertNotEqual(
                got.get("3143"), base.get("3143"),
                f"{seam}=False was parsed but never reached the engine",
            )

    def test_route_absent_keys_are_byte_identical_to_explicit_true(self) -> None:
        absent = server._route_rank_tank(_route_body())
        explicit = server._route_rank_tank(
            _route_body(**{s: True for s in _SEAMS})
        )
        self.assertEqual(absent, explicit)


class ByteIdenticalDefaultTests(_Base):
    """The regression pin - omitting the seams may not move one float."""

    def test_default_order_and_row_values_are_unchanged(self) -> None:
        result = _rank()
        self.assertEqual(_order(result)[:8], _DEFAULT_TOP8)
        deltas = _deltas(result)
        for item_id, expected in _DEFAULT_DELTA_EHP.items():
            self.assertEqual(
                deltas[item_id], expected,
                f"{item_id} delta_ehp drifted from the shipped default",
            )

    def test_explicit_true_equals_omitted(self) -> None:
        omitted = _rows(_rank())
        explicit = _rows(_rank(**{s: True for s in _SEAMS}))
        self.assertEqual(omitted, explicit)


class ForcedOffMagnitudeTests(_Base):
    """Direction + magnitude, incl. the named negative control."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.on = _deltas(_rank())
        cls.off = _deltas(_rank(**{s: False for s in _SEAMS}))

    def _pct(self, item_id: str) -> float:
        return (self.on[item_id] - self.off[item_id]) / self.off[item_id] * 100.0

    def test_randuins_is_heavily_inflated_by_the_assumption(self) -> None:
        self.assertGreater(self._pct("3143"), 40.0)

    def test_frozen_heart_is_heavily_inflated_by_the_assumption(self) -> None:
        self.assertGreater(self._pct("3110"), 40.0)

    def test_warmogs_pure_hp_negative_control_barely_moves(self) -> None:
        # Warmog's carries none of the three effects. Measured +3.3 pct - it
        # moves only via the shared blended denominator. A Randuin's-sized move
        # here means the seam landed on the wrong denominator.
        self.assertLess(
            self._pct("3083"), 3.5,
            "pure-HP Warmog's moved like a crit-DR item - the assumed-share "
            "multiplier hit the wrong denominator",
        )

    def test_forced_off_order_matches_the_measured_reorder(self) -> None:
        self.assertEqual(
            _order(_rank(**{s: False for s in _SEAMS}))[:8], _FORCED_OFF_TOP8
        )


class ClientPayloadTests(unittest.TestCase):
    """Gate 3 - ``rank_tank_for`` must be able to SEND the keys, and must omit
    them entirely when left at the ``None`` inherit default.

    No network: ``_post_json`` is stubbed and the emitted body is inspected.
    """

    def _body(self, **kwargs) -> dict:
        captured: dict = {}

        def _fake_post(path, body, timeout=None):
            captured["path"] = path
            captured["body"] = body
            return {"ranked": []}

        with mock.patch.object(client_mod, "_post_json", _fake_post):
            client_mod.rank_tank_for(
                "Amumu", level=_LEVEL, item_ids=list(_BUILD), **kwargs
            )
        self.assertEqual(captured["path"], "/rank-tank")
        return captured["body"]

    def test_flagless_call_omits_every_new_key(self) -> None:
        body = self._body()
        for key in _SEAMS + ("apply_resist_damage_coupling",
                             "resist_coupling_strength"):
            self.assertNotIn(
                key, body,
                f"{key} leaked into a flagless payload - the wire is no longer "
                "byte-identical",
            )

    def test_explicit_false_is_emitted(self) -> None:
        body = self._body(**{s: False for s in _SEAMS})
        for seam in _SEAMS:
            self.assertIs(body[seam], False)

    def test_resist_coupling_pair_is_emitted(self) -> None:
        body = self._body(
            apply_resist_damage_coupling=True, resist_coupling_strength=3.0
        )
        self.assertIs(body["apply_resist_damage_coupling"], True)
        self.assertEqual(body["resist_coupling_strength"], 3.0)


if __name__ == "__main__":
    unittest.main()
