"""RM-118 residual: the THREE stranded RUNE lanes reach their routes.

THE DEFECT
----------
``test_stranded_hsp_seam_r197.py::STRANDED_TODAY`` ledgered these three engine
seams as debt: the ENGINE half shipped complete - registry, consumer and all -
while no route in ``server.py`` parsed the flag, so no coach tick, no operator
curl and no Python client function could arm them.

  * ``apply_rune_offense_grants`` (ENGINE 1.223.0, extended R155 / R159) -
    ``_rune_offense_grants.rune_offense_grants`` resolves a rune-granted
    ``(bonus AD, AP, attack-speed fraction)`` triple into the DPS stat block.
  * ``apply_rune_self_heal`` (R142) - Second Wind 8444's 4-percent-of-missing-
    health heal, into the EHP numerator.
  * ``apply_rune_shield_grants`` (R142-S2) - Guardian 8465's SELF shield, into
    the EHP numerator. The ALLY half is excluded by design (that is hps.py's
    lane, not a wielder-EHP term).

Same defect class R197 fixed for ``assume_hsp_amp`` and the 1.266.0 slice fixed
for the four EHP survivability seams; this is the OTHER route family that slice
deferred.

TRANSPORT: ``rune_ids`` - AND /dps DID NOT HAVE IT
--------------------------------------------------
Every one of the three is keyed by Riot perk id, so the flag is inert without a
``rune_ids`` roster on the wire. Four of the five routes here have parsed
``rune_ids`` since R136 (/ehp, /rank-tank, /hybrid, /rank-bruiser). ``/dps`` did
NOT: ``compute_dps`` grew its own ``rune_ids`` parameter with the seam
(dps.py:758) and the route never carried either. Wiring the flag alone would
have shipped a key that parses and then does nothing - the RM-115
reachable-and-dead failure mode - so the transport is wired in the same slice
and pinned below.

ROUTE OWNERSHIP IS PER-SEAM, NOT PER-FAMILY (reference_ds_seam_reachability_per_route)
-------------------------------------------------------------------------------------
MEASURED off ``inspect.signature`` over every module in the package, never
assumed from the family name:

  ================================  ===========================================
  seam                              engine entry points -> routes
  ================================  ===========================================
  apply_rune_offense_grants         compute_dps            -> /dps
                                    compute_hybrid         -> /hybrid
                                    rank_items_by_hybrid   -> /rank-bruiser
  apply_rune_self_heal              compute_ehp            -> /ehp
                                    rank_items_by_ehp      -> /rank-tank
                                    compute_hybrid         -> /hybrid
                                    rank_items_by_hybrid   -> /rank-bruiser
  apply_rune_shield_grants          (identical to self_heal)
  ================================  ===========================================

The predecessor slice's write-up said these three reach ``compute_dps`` /
``compute_hybrid`` / ``rank_items_by_hybrid``. That is right for the offense
lane and INCOMPLETE for the other two: ``ehp.py`` names both of them on
``compute_ehp`` (ehp.py:1570-1571) and on ``rank_items_by_ehp``
(ehp.py:3161-3162), so /ehp and /rank-tank own them too and are wired here.
Corrected by measurement, not by trusting the prose.

The asymmetry is the thing the guards below protect: ``compute_ehp`` and
``rank_items_by_ehp`` do NOT name ``apply_rune_offense_grants`` (an EHP frame has
no damage axis to credit AD/AP/AS into), so ``/ehp`` and ``/rank-tank`` must NOT
grow that key. Emitting it there would manufacture reachability - asserted
against below rather than left to convention.

DEFAULT-OFF
-----------
All three default False on every engine entry point, and ``dps.py:1058`` /
``ehp.py:1763`` / ``ehp.py:1888`` consult their registry ONLY inside the
``if`` the flag opens. So an omitted body key is a byte-identical route
response, and - stronger - a body that carries a full ``rune_ids`` roster with
the flags OFF is byte-identical too. Both measured below.

OFFLINE ONLY: no live :8860, no network. Direct handler + engine + client calls.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest
from unittest import mock

import agents.daemon_slayer as ds_pkg
import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.dps import compute_dps
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)
from agents.daemon_slayer.tests.test_stranded_hsp_seam_r197 import (
    STRANDED_TODAY,
    stranded_seams,
)

_OFFENSE = "apply_rune_offense_grants"
_SELF_HEAL = "apply_rune_self_heal"
_SHIELD = "apply_rune_shield_grants"

_SEAMS = (_OFFENSE, _SELF_HEAL, _SHIELD)
_EHP_LANES = (_SELF_HEAL, _SHIELD)

# The MEASURED route table this slice wires. Keyed by seam so a later reader can
# see at a glance which routes may carry which key.
_ROUTES_BY_SEAM: dict[str, tuple[str, ...]] = {
    _OFFENSE: ("/dps", "/hybrid", "/rank-bruiser"),
    _SELF_HEAL: ("/ehp", "/rank-tank", "/hybrid", "/rank-bruiser"),
    _SHIELD: ("/ehp", "/rank-tank", "/hybrid", "/rank-bruiser"),
}
# The EHP-family routes that must NEVER carry the offense key.
_OFFENSE_FORBIDDEN = ("/ehp", "/rank-tank")

_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
_CARRY_ITEMS = ("3031", "3006", "3094")     # IE + boots + Rageblade
_TANK_ITEMS = ("3068", "3083")              # Sunfire + Warmog's
_RANDUINS = "3143"

# Registry members, by Riot perk id.
_CONQUEROR = "8010"          # offense: adaptive force per stack
_ABSOLUTE_FOCUS = "8233"     # offense: adaptive force above 70 percent health
_GATHERING_STORM = "8236"    # offense: adaptive force per 10 minutes
_SECOND_WIND = "8444"        # self-heal
_GUARDIAN = "8465"           # self-shield
# MEASURED movers for the offense lane at level 13 on the build above. Legend:
# Alacrity 9104 and Jack Of All Trades 8316 ARE in the registry but are
# conditional (an attack-speed-locked champion, and a distinct-item-stat census
# threshold), so they read as no change on this build and are deliberately not
# asserted as movers.
_OFFENSE_MOVERS = (_CONQUEROR, _ABSOLUTE_FOCUS, _GATHERING_STORM)
# A syntactically valid perk id in NO registry - the roster-side invariant control.
_OFF_REGISTRY_RUNE = "8000"

_CARRY = "Jinx"
_TANK = "Leona"

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _dps_body(**extra) -> dict:
    body = {
        "champion": _CARRY,
        "level": _LEVEL,
        "items": list(_CARRY_ITEMS),
        "mode": "SR",
        "target_armor": 100.0,
        "target_mr": 100.0,
    }
    body.update(extra)
    return body


def _ehp_body(champion: str = _TANK, **extra) -> dict:
    body = {
        "champion": champion,
        "level": _LEVEL,
        "items": list(_TANK_ITEMS),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


def _hybrid_body(**extra) -> dict:
    body = _dps_body()
    body["enemy_ad_share"] = 0.5
    body["enemy_ap_share"] = 0.5
    body.update(extra)
    return body


def _tank_rank_body(**extra) -> dict:
    # No truncation (reference_ds_probe_depth_top40_truncation).
    body = _ehp_body(top=200)
    body.update(extra)
    return body


def _bruiser_rank_body(**extra) -> dict:
    body = _hybrid_body(top=200)
    body.update(extra)
    return body


def _order(result_dict: dict) -> tuple[str, ...]:
    return tuple(r["item_id"] for r in result_dict["ranked"])


def _row_delta(result_dict: dict, item_id: str, field: str) -> float:
    for r in result_dict["ranked"]:
        if r["item_id"] == item_id:
            return r[field]
    raise AssertionError(f"{item_id} not in route ranked")


def _ehp_rank(**kwargs):
    return rank_items_by_ehp(
        _snap(),
        champion_id=_TANK,
        level=_LEVEL,
        current_item_ids=list(_TANK_ITEMS),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        top_n=None,
        **kwargs,
    )


def _hybrid_rank(**kwargs):
    return rank_items_by_hybrid(
        _snap(),
        champion_id=_CARRY,
        level=_LEVEL,
        current_item_ids=list(_CARRY_ITEMS),
        mode="SR",
        target_armor=100.0,
        target_mr=100.0,
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        top_n=None,
        **kwargs,
    )


def _ehp_rows(result) -> tuple[tuple, ...]:
    """Every pre-existing EHP row field - the byte-identical contract."""
    return tuple(
        (r.item_id, r.gold, r.delta_ehp, r.new_ehp, r.ehp_per_1k_gold,
         r.cc_blended_ehp, r.delta_cc_blended_ehp, r.survivability_score,
         r.team_blended_ehp, r.delta_team_blended_ehp,
         r.delta_sustain_ehp, r.delta_armor, r.delta_mr, r.delta_max_hp)
        for r in result.ranked
    )


def _hybrid_rows(result) -> tuple[tuple, ...]:
    """Every pre-existing hybrid row field - the byte-identical contract."""
    return tuple(
        (r.item_id, r.gold, r.delta_dps, r.delta_ehp, r.new_dps, r.new_ehp,
         r.hybrid_delta_pct, r.hybrid_score, r.hybrid_per_1k_gold,
         r.cc_blended_ehp, r.delta_cc_blended_ehp, r.survivability_score,
         r.ms_utility_mult)
        for r in result.ranked
    )


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class EngineSeamOwnershipTests(_Base):
    """Gate 1: the per-seam route table, MEASURED, not copied from prose."""

    def test_offense_lane_lives_on_the_dps_axis_only(self) -> None:
        for fn in (compute_dps, compute_hybrid, rank_items_by_hybrid):
            with self.subTest(engine=fn.__name__):
                params = inspect.signature(fn).parameters
                self.assertIn(_OFFENSE, params)
                self.assertIs(
                    params[_OFFENSE].default, False,
                    f"{_OFFENSE} must ship DEFAULT-OFF on {fn.__name__}",
                )

    def test_ehp_frames_do_not_name_the_offense_lane(self) -> None:
        """The scope pin the route guard exists to protect.

        An EHP frame has no damage axis to credit AD/AP/AS into, so if a later
        slice adds ``apply_rune_offense_grants`` to ``compute_ehp`` or
        ``rank_items_by_ehp``, THIS goes red and points at the two route wires
        that then need to grow with it - the alternative is a body key silently
        dropped before the engine call (the R194 parse-without-pass shape).
        """
        for fn in (compute_ehp, rank_items_by_ehp):
            with self.subTest(engine=fn.__name__):
                self.assertNotIn(_OFFENSE, inspect.signature(fn).parameters)

    def test_ehp_lanes_live_on_all_four_survivability_entry_points(self) -> None:
        for fn in (compute_ehp, rank_items_by_ehp,
                   compute_hybrid, rank_items_by_hybrid):
            for seam in _EHP_LANES:
                with self.subTest(engine=fn.__name__, seam=seam):
                    params = inspect.signature(fn).parameters
                    self.assertIn(seam, params)
                    self.assertIs(params[seam].default, False)

    def test_no_other_engine_entry_point_names_these_seams(self) -> None:
        """Sweep every module in the package so the table cannot silently grow.

        If a NEW engine function grows one of these parameters, it needs its own
        measured route decision - not an assumption that the existing wires cover
        it. The expected set is the exact table this slice wired, plus the two
        private registry helpers the seams are named after.
        """
        expected = {
            ("dps", "compute_dps"),
            ("ehp", "compute_ehp"),
            ("ehp", "rank_items_by_ehp"),
            ("hybrid", "compute_hybrid"),
            ("hybrid", "rank_items_by_hybrid"),
            ("_rune_shield_grants", "rune_shield_grants"),
        }
        found: set[tuple[str, str]] = set()
        for mod_info in pkgutil.iter_modules(ds_pkg.__path__):
            if mod_info.name == "tests":
                continue
            try:
                mod = importlib.import_module(
                    f"agents.daemon_slayer.{mod_info.name}"
                )
            except Exception:                                  # pragma: no cover
                continue
            for fn_name, fn in inspect.getmembers(mod, inspect.isfunction):
                if getattr(fn, "__module__", "") != mod.__name__:
                    continue
                try:
                    params = inspect.signature(fn).parameters
                except (TypeError, ValueError):                 # pragma: no cover
                    continue
                if any(seam in params for seam in _SEAMS):
                    found.add((mod_info.name, fn_name))
        self.assertEqual(
            found, expected,
            "the engine entry points naming a rune-lane seam changed - re-measure "
            "the route table in this file's docstring before wiring anything",
        )


class DpsRouteTests(_Base):
    """``/dps``: the route that also had to grow the ``rune_ids`` TRANSPORT."""

    def test_route_now_carries_the_transport(self) -> None:
        src = _server_source()
        self.assertIn('_coerce_str_list(body.get("rune_ids"), "rune_ids")', src)
        # Cheap structural proof the /dps handler itself reads it, not just a
        # sibling route: the handler's own source must name the key.
        handler_src = inspect.getsource(server._route_dps)
        self.assertIn("rune_ids", handler_src)
        self.assertIn(_OFFENSE, handler_src)

    def test_absent_key_equals_explicit_false(self) -> None:
        self.assertEqual(
            server._route_dps(_dps_body()),
            server._route_dps(_dps_body(**{_OFFENSE: False})),
        )

    def test_a_full_rune_roster_with_the_flag_off_is_byte_identical(self) -> None:
        """The stronger DEFAULT-OFF claim: the TRANSPORT alone must be inert.

        ``dps.py`` consults the registry only inside the ``if`` the flag opens,
        so a caller that sends its runes but never arms the seam gets exactly the
        pre-wire response. This is what makes the transport safe to add to a
        route that shipped without it.
        """
        loaded = _dps_body(rune_ids=[_CONQUEROR, _GATHERING_STORM, _SECOND_WIND])
        self.assertEqual(server._route_dps(_dps_body()),
                         server._route_dps(loaded))

    def test_every_measured_mover_raises_dps(self) -> None:
        off = server._route_dps(_dps_body())["weighted_dps"]
        for rune in _OFFENSE_MOVERS:
            with self.subTest(rune=rune):
                on = server._route_dps(
                    _dps_body(rune_ids=[rune], **{_OFFENSE: True})
                )["weighted_dps"]
                self.assertGreater(
                    on, off,
                    f"{_OFFENSE} was parsed but never reached compute_dps",
                )

    def test_conqueror_is_the_measured_pair(self) -> None:
        # Jinx, level 13, SR, IE + boots + Rageblade, target 100/100 resists.
        # Conqueror 8010 at 12 stacks is the largest single adaptive grant in the
        # registry at this level, so it is the clearest OFF/ON pair.
        off = server._route_dps(_dps_body())["weighted_dps"]
        on = server._route_dps(
            _dps_body(rune_ids=[_CONQUEROR], **{_OFFENSE: True})
        )["weighted_dps"]
        self.assertAlmostEqual(off, 53.21843541666665, places=6)
        self.assertAlmostEqual(on, 59.84518835784314, places=6)

    def test_off_registry_rune_is_inert_even_when_armed(self) -> None:
        self.assertEqual(
            server._route_dps(_dps_body()),
            server._route_dps(
                _dps_body(rune_ids=[_OFF_REGISTRY_RUNE], **{_OFFENSE: True})
            ),
            "the offense lane credited a perk id that is in no registry",
        )


class EhpRouteTests(_Base):
    """``/ehp``: the two SELF-side survivability lanes."""

    def _blended(self, **extra) -> float:
        return server._route_ehp(_ehp_body(**extra))["blended_ehp"]

    def test_absent_key_equals_explicit_false(self) -> None:
        for seam in _EHP_LANES:
            with self.subTest(seam=seam):
                self.assertEqual(
                    server._route_ehp(_ehp_body()),
                    server._route_ehp(_ehp_body(**{seam: False})),
                )

    def test_a_full_rune_roster_with_both_flags_off_is_byte_identical(self) -> None:
        self.assertEqual(
            server._route_ehp(_ehp_body()),
            server._route_ehp(_ehp_body(rune_ids=[_SECOND_WIND, _GUARDIAN])),
        )

    def test_second_wind_raises_blended_ehp(self) -> None:
        self.assertGreater(
            self._blended(rune_ids=[_SECOND_WIND], **{_SELF_HEAL: True}),
            self._blended(),
            f"{_SELF_HEAL} was parsed but never reached compute_ehp",
        )

    def test_guardian_raises_blended_ehp(self) -> None:
        self.assertGreater(
            self._blended(rune_ids=[_GUARDIAN], **{_SHIELD: True}),
            self._blended(),
            f"{_SHIELD} was parsed but never reached compute_ehp",
        )

    def test_the_two_lanes_are_additive_not_aliases(self) -> None:
        """Different registries, so arming both must beat arming either one."""
        base = self._blended()
        heal = self._blended(rune_ids=[_SECOND_WIND], **{_SELF_HEAL: True})
        shield = self._blended(rune_ids=[_GUARDIAN], **{_SHIELD: True})
        both = self._blended(
            rune_ids=[_SECOND_WIND, _GUARDIAN],
            **{_SELF_HEAL: True, _SHIELD: True},
        )
        self.assertGreater(heal, base)
        self.assertGreater(shield, base)
        self.assertGreater(both, heal)
        self.assertGreater(both, shield)

    def test_each_lane_is_inert_without_its_own_rune(self) -> None:
        # Guardian in the roster must not pay out the SELF-HEAL lane, and vice
        # versa - the two registries are disjoint.
        self.assertEqual(
            self._blended(rune_ids=[_GUARDIAN], **{_SELF_HEAL: True}),
            self._blended(),
            f"{_SELF_HEAL} credited a rune that belongs to the shield registry",
        )
        self.assertEqual(
            self._blended(rune_ids=[_SECOND_WIND], **{_SHIELD: True}),
            self._blended(),
            f"{_SHIELD} credited a rune that belongs to the self-heal registry",
        )


class HybridRouteTests(_Base):
    """``/hybrid``: the only route where ONE call can arm all three."""

    def test_absent_keys_equal_explicit_false(self) -> None:
        explicit = dict.fromkeys(_SEAMS, False)
        self.assertEqual(
            server._route_hybrid(_hybrid_body()),
            server._route_hybrid(_hybrid_body(**explicit)),
        )

    def test_offense_lane_moves_the_dps_axis_only(self) -> None:
        off = server._route_hybrid(_hybrid_body())
        on = server._route_hybrid(
            _hybrid_body(rune_ids=[_CONQUEROR], **{_OFFENSE: True})
        )
        self.assertGreater(on["dps"], off["dps"])
        self.assertEqual(on["ehp"], off["ehp"])
        self.assertGreater(on["hybrid_score"], off["hybrid_score"])

    def test_survivability_lanes_move_the_ehp_axis_only(self) -> None:
        off = server._route_hybrid(_hybrid_body())
        on = server._route_hybrid(_hybrid_body(
            rune_ids=[_SECOND_WIND, _GUARDIAN],
            **{_SELF_HEAL: True, _SHIELD: True},
        ))
        self.assertEqual(on["dps"], off["dps"])
        self.assertGreater(on["ehp"], off["ehp"])
        self.assertGreater(on["hybrid_score"], off["hybrid_score"])

    def test_all_three_together_beat_either_half(self) -> None:
        off = server._route_hybrid(_hybrid_body())["hybrid_score"]
        both = server._route_hybrid(_hybrid_body(
            rune_ids=[_CONQUEROR, _SECOND_WIND, _GUARDIAN],
            **{_OFFENSE: True, _SELF_HEAL: True, _SHIELD: True},
        ))["hybrid_score"]
        offense_only = server._route_hybrid(
            _hybrid_body(rune_ids=[_CONQUEROR], **{_OFFENSE: True})
        )["hybrid_score"]
        self.assertGreater(both, offense_only)
        self.assertGreater(offense_only, off)


class TankRankerRouteTests(_Base):
    """``/rank-tank``: where the two survivability lanes change a CHOICE."""

    def test_absent_keys_are_byte_identical(self) -> None:
        explicit = dict.fromkeys(_EHP_LANES, False)
        self.assertEqual(
            server._route_rank_tank(_tank_rank_body()),
            server._route_rank_tank(_tank_rank_body(**explicit)),
        )

    def test_route_forwards_both_lanes(self) -> None:
        off = server._route_rank_tank(_tank_rank_body())
        for seam, rune in ((_SELF_HEAL, _SECOND_WIND), (_SHIELD, _GUARDIAN)):
            with self.subTest(seam=seam):
                on = server._route_rank_tank(
                    _tank_rank_body(rune_ids=[rune], **{seam: True})
                )
                self.assertGreater(
                    _row_delta(on, _RANDUINS, "delta_ehp"),
                    _row_delta(off, _RANDUINS, "delta_ehp"),
                    f"{seam} was parsed but never reached rank_items_by_ehp",
                )

    def test_the_route_does_not_parse_the_offense_lane(self) -> None:
        self.assertNotIn(_OFFENSE, inspect.getsource(server._route_rank_tank))

    def test_engine_default_path_is_byte_identical(self) -> None:
        omitted = _ehp_rank()
        explicit = _ehp_rank(**dict.fromkeys(_EHP_LANES, False))
        self.assertEqual(_ehp_rows(omitted), _ehp_rows(explicit))

    def test_a_rune_roster_with_both_flags_off_is_byte_identical(self) -> None:
        self.assertEqual(
            _ehp_rows(_ehp_rank()),
            _ehp_rows(_ehp_rank(rune_ids=(_SECOND_WIND, _GUARDIAN))),
        )

    def test_the_order_actually_moves(self) -> None:
        # Leona, level 13, SR, Sunfire + Warmog's over the full 137-row pool.
        # Both lanes add to the EHP NUMERATOR, which lifts the rows that buy raw
        # health relatively more than the rows that buy pure resists, so WHICH
        # item ranks where changes - not merely a row value.
        off = server._route_rank_tank(_tank_rank_body())
        on = server._route_rank_tank(_tank_rank_body(
            rune_ids=[_SECOND_WIND, _GUARDIAN],
            **{_SELF_HEAL: True, _SHIELD: True},
        ))
        self.assertNotEqual(_order(off), _order(on))

    def test_off_registry_rune_is_wholly_invariant(self) -> None:
        armed = _ehp_rank(
            rune_ids=(_OFF_REGISTRY_RUNE,),
            **dict.fromkeys(_EHP_LANES, True),
        )
        self.assertEqual(_ehp_rows(_ehp_rank()), _ehp_rows(armed))


class BruiserRankerRouteTests(_Base):
    """``/rank-bruiser``: all three lanes, each able to change a CHOICE."""

    def test_absent_keys_are_byte_identical(self) -> None:
        explicit = dict.fromkeys(_SEAMS, False)
        self.assertEqual(
            server._route_rank_bruiser(_bruiser_rank_body()),
            server._route_rank_bruiser(_bruiser_rank_body(**explicit)),
        )

    def test_route_forwards_the_offense_lane(self) -> None:
        off = server._route_rank_bruiser(_bruiser_rank_body())
        on = server._route_rank_bruiser(
            _bruiser_rank_body(rune_ids=[_CONQUEROR], **{_OFFENSE: True})
        )
        self.assertGreater(
            _row_delta(on, _RANDUINS, "new_dps"),
            _row_delta(off, _RANDUINS, "new_dps"),
            f"{_OFFENSE} was parsed but never reached rank_items_by_hybrid",
        )

    def test_route_forwards_both_survivability_lanes(self) -> None:
        off = server._route_rank_bruiser(_bruiser_rank_body())
        for seam, rune in ((_SELF_HEAL, _SECOND_WIND), (_SHIELD, _GUARDIAN)):
            with self.subTest(seam=seam):
                on = server._route_rank_bruiser(
                    _bruiser_rank_body(rune_ids=[rune], **{seam: True})
                )
                self.assertGreater(
                    _row_delta(on, _RANDUINS, "new_ehp"),
                    _row_delta(off, _RANDUINS, "new_ehp"),
                    f"{seam} was parsed but never reached rank_items_by_hybrid",
                )

    def test_engine_default_path_is_byte_identical(self) -> None:
        omitted = _hybrid_rank()
        explicit = _hybrid_rank(**dict.fromkeys(_SEAMS, False))
        self.assertEqual(_hybrid_rows(omitted), _hybrid_rows(explicit))

    def test_a_rune_roster_with_every_flag_off_is_byte_identical(self) -> None:
        loaded = _hybrid_rank(
            rune_ids=(_CONQUEROR, _SECOND_WIND, _GUARDIAN)
        )
        self.assertEqual(_hybrid_rows(_hybrid_rank()), _hybrid_rows(loaded))

    def test_both_halves_move_the_order_independently(self) -> None:
        # Jinx, level 13, SR, IE + boots + Rageblade over the full 139-row pool.
        base = _order(server._route_rank_bruiser(_bruiser_rank_body()))
        offense = _order(server._route_rank_bruiser(
            _bruiser_rank_body(rune_ids=[_CONQUEROR], **{_OFFENSE: True})
        ))
        survivability = _order(server._route_rank_bruiser(_bruiser_rank_body(
            rune_ids=[_SECOND_WIND, _GUARDIAN],
            **{_SELF_HEAL: True, _SHIELD: True},
        )))
        self.assertNotEqual(base, offense)
        self.assertNotEqual(base, survivability)

    def test_off_registry_rune_is_wholly_invariant(self) -> None:
        armed = _hybrid_rank(
            rune_ids=(_OFF_REGISTRY_RUNE,), **dict.fromkeys(_SEAMS, True)
        )
        self.assertEqual(_hybrid_rows(_hybrid_rank()), _hybrid_rows(armed))


class ClientWiringTests(_Base):
    """Gate 3: the client functions must be able to express what they POST."""

    _FN_BY_ROUTE = {
        "/dps": "dps_for",
        "/ehp": "ehp_for",
        "/rank-tank": "rank_tank_for",
        "/hybrid": "hybrid_for",
        "/rank-bruiser": "rank_bruiser_for",
    }

    def test_every_owning_client_function_names_its_seams(self) -> None:
        for seam, routes in _ROUTES_BY_SEAM.items():
            for route in routes:
                fn_name = self._FN_BY_ROUTE[route]
                with self.subTest(seam=seam, fn=fn_name):
                    params = inspect.signature(
                        getattr(client_mod, fn_name)
                    ).parameters
                    self.assertIn(seam, params)
                    self.assertIs(params[seam].default, False)

    def test_no_ehp_family_client_can_express_the_offense_lane(self) -> None:
        for route in _OFFENSE_FORBIDDEN:
            fn_name = self._FN_BY_ROUTE[route]
            with self.subTest(fn=fn_name):
                self.assertNotIn(
                    _OFFENSE,
                    inspect.signature(getattr(client_mod, fn_name)).parameters,
                    f"{fn_name} can express {_OFFENSE}, which its route does not "
                    "parse - a key that dies on the wire",
                )

    def test_dps_for_can_express_the_rune_transport(self) -> None:
        params = inspect.signature(client_mod.dps_for).parameters
        self.assertIn("rune_ids", params)
        self.assertIsNone(params["rune_ids"].default)

    def _sent(self, fn_name: str, **kwargs) -> dict:
        seen: dict = {}

        def _fake(path, body, timeout=0.0):
            seen["path"] = path
            seen["body"] = body
            return {"ranked": []}

        with mock.patch.object(client_mod, "_post_json", _fake):
            getattr(client_mod, fn_name)(
                _CARRY, level=_LEVEL, item_ids=list(_CARRY_ITEMS), **kwargs
            )
        return seen

    def test_each_client_emits_only_when_armed(self) -> None:
        for seam, routes in _ROUTES_BY_SEAM.items():
            for route in routes:
                fn_name = self._FN_BY_ROUTE[route]
                with self.subTest(seam=seam, fn=fn_name):
                    bare = self._sent(fn_name)
                    self.assertEqual(bare["path"], route)
                    self.assertNotIn(seam, bare["body"])
                    armed = self._sent(fn_name, **{seam: True})
                    self.assertIs(armed["body"][seam], True)

    def test_dps_for_emits_the_transport_only_when_given(self) -> None:
        self.assertNotIn("rune_ids", self._sent("dps_for")["body"])
        armed = self._sent("dps_for", rune_ids=[_CONQUEROR])
        self.assertEqual(armed["body"]["rune_ids"], [_CONQUEROR])


class PerRouteStrandedSeamTests(_Base):
    """PER-(route, seam), never name-collapsed."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.parsed, _ = _route_table()
        cls.client = _client_by_route()

    def test_every_wired_pair_is_parsed_and_expressible(self) -> None:
        for seam, routes in _ROUTES_BY_SEAM.items():
            for route in routes:
                with self.subTest(seam=seam, route=route):
                    self.assertIn(seam, self.parsed[route])
                    self.assertIn(seam, self.client[route])

    def test_the_ehp_family_routes_do_not_parse_the_offense_lane(self) -> None:
        for route in _OFFENSE_FORBIDDEN:
            with self.subTest(route=route):
                self.assertNotIn(_OFFENSE, self.parsed[route])


class StrandedLedgerTests(_Base):
    """The debt ledger can only shrink - these three must have left it."""

    def test_the_three_are_no_longer_stranded(self) -> None:
        stranded = stranded_seams(_server_source())
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, stranded)
                self.assertNotIn(
                    seam, STRANDED_TODAY,
                    "the seam is wired - delete its STRANDED_TODAY entry so the "
                    "ledger keeps shrinking",
                )


def _server_source() -> str:
    import pathlib
    return pathlib.Path(server.__file__).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
