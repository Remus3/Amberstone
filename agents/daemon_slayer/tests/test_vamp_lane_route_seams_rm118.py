"""RM-118 residual: the TWO stranded VAMP lanes reach their route.

THE DEFECT
----------
``test_stranded_hsp_seam_r197.py::STRANDED_TODAY`` ledgered these two engine
seams as debt: the ENGINE half shipped complete - registry, consumer, curated
item set and all - while no route in ``server.py`` parsed the flag, so no coach
tick, no generated build table, no operator curl and no Python client function
could arm them.

  * ``assume_crit_weighted_vamp`` (R193 slice B) - ``_vamp_heal_pool`` prices
    vamp off the UNCRIT ``AD * AS * window`` throughput, but an auto-attack
    lands ``AD * (1 + crit * crit_damage_bonus)`` and lifesteal heals off THAT
    hit, so a crit carry's sustain is under-credited by the whole crit factor.
  * ``assume_cleave_lifesteal`` (R194 slice C, RM-116c) - Ravenous Hydra's
    Cleave rider and its Ravenous Crescent active are the two damage sources
    Meraki 16.14.1 explicitly labels lifesteal-eligible at 100 percent, and
    neither is auto-attack damage, so neither reaches the pool.

Same defect class R197 fixed for ``assume_hsp_amp``, the 1.266.0 slice fixed for
the four EHP survivability seams, and 1.267.0 fixed for the three rune lanes.

ROUTE OWNERSHIP IS PER-SEAM, NOT PER-FAMILY (reference_ds_seam_reachability_per_route)
-------------------------------------------------------------------------------------
MEASURED off ``inspect.signature`` over every module in the package, never
inherited from prose:

  ===========================  =========================================
  seam                         engine entry points -> routes
  ===========================  =========================================
  assume_crit_weighted_vamp    compute_ehp  -> /ehp        (and NOTHING else)
  assume_cleave_lifesteal      compute_ehp  -> /ehp        (and NOTHING else)
  ===========================  =========================================

``test_ehp_survivability_route_seams_rm118.py``'s write-up placed both in the
``compute_dps`` / ``compute_hybrid`` / ``rank_items_by_hybrid`` family. That is
WRONG for both: neither name appears on ``compute_dps``, ``compute_hybrid``,
``rank_items_by_hybrid`` OR ``rank_items_by_ehp``. ``compute_ehp`` is the sole
owner (ehp.py, appended at END of the signature), so ``/ehp`` is the entire
route table and every other route must NOT grow either key. Corrected by
measurement, not by trusting the prose - the same correction the 1.267.0 rune
slice had to make in the opposite direction.

TRANSPORT: ``items`` FOR BOTH, PLUS ``targets_in_rotation`` FOR THE CLEAVE LANE
------------------------------------------------------------------------------
A flag that parses and then cannot change a number is the RM-115
reachable-and-dead failure mode, so each lane's transport was checked, not
assumed:

  * ``assume_crit_weighted_vamp`` reads ``stats["crit"]`` and
    ``stats["lifesteal"]`` off the RESOLVED build plus the item-effect
    crit-chance lane. Its whole transport is ``items``, which ``/ehp`` has
    parsed since Phase 1. Nothing new was needed - and a zero-crit build is an
    exact no-op, pinned below so the flag is never mistaken for a constant lift.
  * ``assume_cleave_lifesteal`` reads ``items`` (only Ravenous Hydra 3074 and
    its Arena mirror 223074 carry the Meraki clause) AND ``targets_in_rotation``,
    the enemy count its Cleave lands on. ``/ehp`` did NOT parse that float, and
    no client function sent one. The flag alone is not inert - the Crescent term
    pays out at a single target - but the target-count half of the seam was
    unreachable, so the transport is wired in THIS slice and pinned below.

DEFAULT-OFF
-----------
``_crit_weighted_vamp_multiplier`` returns the identity 1.0 and
``_cleave_vamp_damage`` returns 0.0 before reading anything when their flag is
False. So an omitted body key is a byte-identical route response, and - stronger
- a body carrying a full ``targets_in_rotation`` count with the flags OFF is
byte-identical too. Both measured below.

OFFLINE ONLY: no live :8893, no network. Direct handler + engine + client calls.
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
from agents.daemon_slayer.ehp import (
    VAMP_ELIGIBLE_CLEAVE_ITEM_IDS,
    compute_ehp,
    rank_items_by_ehp,
)
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)
from agents.daemon_slayer.tests.test_stranded_hsp_seam_r197 import (
    SERVER_SRC,
    STRANDED_TODAY,
    stranded_seams,
)

_CRIT_VAMP = "assume_crit_weighted_vamp"
_CLEAVE = "assume_cleave_lifesteal"
_TRANSPORT = "targets_in_rotation"

_SEAMS = (_CRIT_VAMP, _CLEAVE)
# The MEASURED route table this slice wires. One route, both seams.
_ROUTES_BY_SEAM: dict[str, tuple[str, ...]] = {
    _CRIT_VAMP: ("/ehp",),
    _CLEAVE: ("/ehp",),
}
# Every OTHER EHP-family route. None of their engine functions names either
# seam, so none of them may parse either key.
_FORBIDDEN_ROUTES = ("/rank-tank", "/hybrid", "/rank-bruiser")

_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
# CRIT carry - Infinity Edge + Bloodthirster + Rageblade + Zeal resolves
# crit 0.75 / lifesteal 0.15, so BOTH factors of the crit-weight are live.
_CRIT_CHAMP = "Jinx"
_CRIT_ITEMS = ("3031", "3072", "3094", "3036")
# CLEAVE bruiser - Ravenous Hydra 3074 (the ONLY base id carrying the Meraki
# lifesteal clause) + Bloodthirster + Plated Steelcaps -> lifesteal 0.27, crit 0.
_CLEAVE_CHAMP = "Sett"
_CLEAVE_ITEMS = ("3074", "3072", "3047")
# Same shape, lifesteal-silent hydra sibling (Titanic 3748) - the item-set pin.
_TITANIC_ITEMS = ("3748", "3072", "3047")

_RAVENOUS_HYDRA = "3074"

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _crit_body(**extra) -> dict:
    body = {
        "champion": _CRIT_CHAMP,
        "level": _LEVEL,
        "items": list(_CRIT_ITEMS),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


def _cleave_body(items: tuple[str, ...] = _CLEAVE_ITEMS, **extra) -> dict:
    body = {
        "champion": _CLEAVE_CHAMP,
        "level": _LEVEL,
        "items": list(items),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


def _engine(champion: str, items: tuple[str, ...], **kwargs):
    return compute_ehp(
        _snap(),
        champion_id=champion,
        level=_LEVEL,
        item_ids=list(items),
        mode="SR",
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        **kwargs,
    )


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class EngineSeamOwnershipTests(_Base):
    """Gate 1: the per-seam route table, MEASURED, not copied from prose."""

    def test_both_lanes_live_on_compute_ehp_default_off(self) -> None:
        params = inspect.signature(compute_ehp).parameters
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(seam, params)
                self.assertIs(
                    params[seam].default, False,
                    f"{seam} must ship DEFAULT-OFF on compute_ehp",
                )

    def test_the_transport_defaults_to_the_single_target_identity(self) -> None:
        params = inspect.signature(compute_ehp).parameters
        self.assertIn(_TRANSPORT, params)
        self.assertEqual(params[_TRANSPORT].default, 1.0)

    def test_no_other_route_facing_engine_function_names_them(self) -> None:
        """The scope pin the route guard exists to protect.

        ``rank_items_by_ehp`` / ``compute_hybrid`` / ``rank_items_by_hybrid`` /
        ``compute_dps`` do NOT name either seam, which is exactly why /rank-tank,
        /hybrid, /rank-bruiser and /dps must not grow the keys. If a later slice
        extends the seam to one of those frames, THIS goes red and points at the
        route wire that then has to grow with it - the alternative is a body key
        silently dropped before the engine call (the R194 parse-without-pass
        shape).
        """
        for fn in (rank_items_by_ehp, compute_hybrid, rank_items_by_hybrid,
                   compute_dps):
            params = inspect.signature(fn).parameters
            for seam in _SEAMS:
                with self.subTest(engine=fn.__name__, seam=seam):
                    self.assertNotIn(seam, params)

    def test_package_wide_sweep_pins_the_owning_functions(self) -> None:
        """Sweep every module so the table cannot silently grow.

        The expected set is the exact table this slice wired plus the two
        private helpers the seams are named after.
        """
        expected = {
            ("ehp", "compute_ehp"),
            ("ehp", "_crit_weighted_vamp_multiplier"),
            ("ehp", "_cleave_vamp_damage"),
        }
        found: set[tuple[str, str]] = set()
        for mod_info in pkgutil.iter_modules(ds_pkg.__path__):
            if mod_info.name == "tests":
                continue
            try:
                mod = importlib.import_module(
                    f"agents.daemon_slayer.{mod_info.name}"
                )
            except Exception:                                   # pragma: no cover
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
            "the engine entry points naming a vamp-lane seam changed - re-measure "
            "the route table in this file's docstring before wiring anything",
        )

    def test_the_curated_cleave_item_set_is_the_r194_pair(self) -> None:
        # Ravenous Hydra plus its Arena mirror, resolved by ID SUFFIX. The four
        # structurally identical hydra siblings carry no Meraki lifesteal clause.
        self.assertEqual(
            sorted(VAMP_ELIGIBLE_CLEAVE_ITEM_IDS), ["223074", "3074"]
        )


class StrandedLedgerTests(_Base):
    """Gate 2a: the self-cleaning debt ledger shrank by exactly these two."""

    def test_neither_seam_is_stranded_any_more(self) -> None:
        stranded = stranded_seams(SERVER_SRC)
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, stranded)

    def test_neither_seam_is_still_ledgered_as_debt(self) -> None:
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(
                    seam, STRANDED_TODAY,
                    f"{seam} is wired but still in STRANDED_TODAY - the ledger "
                    "can only shrink",
                )


class EhpRouteParseAndForwardTests(_Base):
    """Gate 2b: ``/ehp`` parses AND forwards both seams plus the transport."""

    def test_the_handler_reads_all_three_keys(self) -> None:
        src = inspect.getsource(server._route_ehp)
        for key in (*_SEAMS, _TRANSPORT):
            with self.subTest(key=key):
                self.assertIn(key, src)
        self.assertIn(
            '_opt_float(body, "targets_in_rotation", 1.0)', src,
            "the cleave lane's transport must parse as a float on the engine's "
            "own single-target default",
        )

    def test_absent_keys_equal_explicit_defaults(self) -> None:
        explicit = dict.fromkeys(_SEAMS, False)
        explicit[_TRANSPORT] = 1.0
        for body_fn in (_crit_body, _cleave_body):
            with self.subTest(body=body_fn.__name__):
                self.assertEqual(
                    server._route_ehp(body_fn()),
                    server._route_ehp(body_fn(**explicit)),
                )

    def test_the_transport_alone_is_byte_identical(self) -> None:
        """The stronger DEFAULT-OFF claim: an armed transport must be inert.

        ``_cleave_vamp_damage`` returns 0.0 before reading ``targets_in_rotation``
        when the flag is False, so a caller that sends its enemy count but never
        arms the seam gets exactly the pre-wire response. This is what makes the
        float safe to add to a route that shipped without it.
        """
        for count in (0.0, 1.0, 3.0, 5.0):
            with self.subTest(targets_in_rotation=count):
                self.assertEqual(
                    server._route_ehp(_cleave_body()),
                    server._route_ehp(_cleave_body(**{_TRANSPORT: count})),
                )

    def test_a_non_finite_transport_is_rejected_not_silently_coerced(self) -> None:
        with self.assertRaises(server._ApiError):
            server._route_ehp(_cleave_body(**{_TRANSPORT: float("inf")}))


class CritWeightedVampMeasuredTests(_Base):
    """Gate 2c: the crit lane MOVES the route number, and only where it should."""

    def _blended(self, **extra) -> float:
        return server._route_ehp(_crit_body(**extra))["blended_ehp"]

    def test_the_measured_off_on_pair(self) -> None:
        # Jinx, level 13, SR, IE + Bloodthirster + Rageblade + Zeal, 50/50
        # enemy shares. Resolved crit 0.75, lifesteal 0.15.
        self.assertAlmostEqual(self._blended(), 3552.368806877279, places=6)
        self.assertAlmostEqual(
            self._blended(**{_CRIT_VAMP: True}), 3845.3720653400114, places=6
        )

    def test_arming_it_raises_blended_ehp(self) -> None:
        self.assertGreater(
            self._blended(**{_CRIT_VAMP: True}),
            self._blended(),
            f"{_CRIT_VAMP} was parsed but never reached compute_ehp",
        )

    def test_a_zero_crit_build_is_an_exact_no_op(self) -> None:
        # Sett with Ravenous Hydra + Bloodthirster + Steelcaps resolves crit 0.0,
        # so ``1 + crit * crit_damage_bonus`` collapses to the identity. The flag
        # is a crit WEIGHT, not a flat sustain lift - pinned so a future edit
        # cannot quietly turn it into one.
        self.assertEqual(
            server._route_ehp(_cleave_body()),
            server._route_ehp(_cleave_body(**{_CRIT_VAMP: True})),
        )

    def test_the_transport_does_not_touch_this_lane(self) -> None:
        # ``targets_in_rotation`` belongs to the cleave lane alone. Arming the
        # crit lane with a target count must read the same as without one.
        self.assertEqual(
            server._route_ehp(_crit_body(**{_CRIT_VAMP: True})),
            server._route_ehp(
                _crit_body(**{_CRIT_VAMP: True, _TRANSPORT: 4.0})
            ),
        )


class CleaveLifestealMeasuredTests(_Base):
    """Gate 2d: the cleave lane MOVES, and scales with its transport."""

    def _blended(self, items: tuple[str, ...] = _CLEAVE_ITEMS, **extra) -> float:
        return server._route_ehp(_cleave_body(items, **extra))["blended_ehp"]

    def test_the_measured_off_on_pair(self) -> None:
        # Sett, level 13, SR, Ravenous Hydra + Bloodthirster + Plated Steelcaps.
        # Lifesteal 0.27. OFF, then armed at the single-target default (Crescent
        # only), then at three targets (Crescent + two Cleave splashes).
        self.assertAlmostEqual(self._blended(), 4552.839179173092, places=6)
        self.assertAlmostEqual(
            self._blended(**{_CLEAVE: True}), 4652.511427749934, places=6
        )
        self.assertAlmostEqual(
            self._blended(**{_CLEAVE: True, _TRANSPORT: 3.0}),
            5104.774255667356,
            places=6,
        )

    def test_arming_it_raises_blended_ehp_at_a_single_target(self) -> None:
        # The Crescent active pays out even in a duel, which is exactly why the
        # FLAG - not the target count - is what guarantees byte-identity.
        self.assertGreater(
            self._blended(**{_CLEAVE: True}),
            self._blended(),
            f"{_CLEAVE} was parsed but never reached compute_ehp",
        )

    def test_the_credit_grows_monotonically_with_the_target_count(self) -> None:
        """The transport check with teeth: the float must reach the engine.

        A wire that parsed ``targets_in_rotation`` and then dropped it would
        still pass every OFF/ON assertion above, because the Crescent term is
        target-count-blind. Only this one fails.
        """
        seen = [
            self._blended(**{_CLEAVE: True, _TRANSPORT: n})
            for n in (1.0, 2.0, 3.0, 5.0)
        ]
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(seen[-1], seen[0])

    def test_a_lifesteal_silent_hydra_sibling_is_inert(self) -> None:
        # Titanic Hydra 3748 procs the same Cleave shape with NO Meraki lifesteal
        # clause, so the narrow curated set must credit it nothing even armed.
        self.assertNotIn("3748", VAMP_ELIGIBLE_CLEAVE_ITEM_IDS)
        self.assertEqual(
            server._route_ehp(_cleave_body(_TITANIC_ITEMS)),
            server._route_ehp(
                _cleave_body(_TITANIC_ITEMS, **{_CLEAVE: True, _TRANSPORT: 5.0})
            ),
            "the cleave lane credited a hydra sibling with no lifesteal clause",
        )

    def test_a_build_with_no_hydra_at_all_is_inert(self) -> None:
        self.assertNotIn(_RAVENOUS_HYDRA, _CRIT_ITEMS)
        self.assertEqual(
            server._route_ehp(_crit_body()),
            server._route_ehp(_crit_body(**{_CLEAVE: True, _TRANSPORT: 5.0})),
        )

    def test_the_two_lanes_are_independent_not_aliases(self) -> None:
        # Different consumers, so on a build that has BOTH crit and a Ravenous
        # Hydra, arming both must beat arming either alone.
        both_items = ("3074", "3072", "3031")
        base = _engine(_CLEAVE_CHAMP, both_items).blended_ehp
        crit = _engine(
            _CLEAVE_CHAMP, both_items, **{_CRIT_VAMP: True}
        ).blended_ehp
        cleave = _engine(
            _CLEAVE_CHAMP, both_items, **{_CLEAVE: True}
        ).blended_ehp
        both = _engine(
            _CLEAVE_CHAMP, both_items, **{_CRIT_VAMP: True, _CLEAVE: True}
        ).blended_ehp
        self.assertGreater(crit, base)
        self.assertGreater(cleave, base)
        self.assertGreater(both, crit)
        self.assertGreater(both, cleave)


class RouteScopeTests(_Base):
    """Gate 5: no OTHER route may carry either key."""

    def test_the_sibling_ehp_family_routes_do_not_parse_them(self) -> None:
        handlers = {
            "/rank-tank": server._route_rank_tank,
            "/hybrid": server._route_hybrid,
            "/rank-bruiser": server._route_rank_bruiser,
        }
        for route in _FORBIDDEN_ROUTES:
            src = inspect.getsource(handlers[route])
            for seam in _SEAMS:
                with self.subTest(route=route, seam=seam):
                    self.assertNotIn(
                        seam, src,
                        f"{route} parses {seam}, which its engine function does "
                        "not accept - a key that dies before the engine call",
                    )

    def test_the_parsed_route_table_matches_the_measured_one(self) -> None:
        parsed, _ = _route_table()
        for seam, routes in _ROUTES_BY_SEAM.items():
            for route in routes:
                with self.subTest(seam=seam, route=route):
                    self.assertIn(seam, parsed[route])
            for route, keys in parsed.items():
                if route in routes:
                    continue
                with self.subTest(seam=seam, forbidden_route=route):
                    self.assertNotIn(seam, keys)


class ClientWiringTests(_Base):
    """Gate 3: the client function must be able to express what it POSTs."""

    def test_ehp_for_names_both_seams_default_off(self) -> None:
        params = inspect.signature(client_mod.ehp_for).parameters
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(seam, params)
                self.assertIs(params[seam].default, False)

    def test_ehp_for_can_express_the_cleave_transport(self) -> None:
        params = inspect.signature(client_mod.ehp_for).parameters
        self.assertIn(_TRANSPORT, params)
        self.assertIsNone(params[_TRANSPORT].default)

    def test_no_other_client_function_can_express_them(self) -> None:
        # Folding these into ``_emit_ehp_family_seams`` would leak the keys onto
        # /rank-tank, /hybrid and /rank-bruiser, none of which parses them.
        for fn_name in ("rank_tank_for", "hybrid_for", "rank_bruiser_for",
                        "dps_for", "sustain_for"):
            params = inspect.signature(getattr(client_mod, fn_name)).parameters
            for seam in _SEAMS:
                with self.subTest(fn=fn_name, seam=seam):
                    self.assertNotIn(
                        seam, params,
                        f"{fn_name} can express {seam}, which its route does "
                        "not parse - a key that dies on the wire",
                    )

    def _sent(self, **kwargs) -> dict:
        seen: dict = {}

        def _fake(path, body, timeout=0.0):
            seen["path"] = path
            seen["body"] = body
            return {}

        with mock.patch.object(client_mod, "_post_json", _fake):
            client_mod.ehp_for(
                _CLEAVE_CHAMP,
                level=_LEVEL,
                item_ids=list(_CLEAVE_ITEMS),
                **kwargs,
            )
        return seen

    def test_each_seam_is_emitted_only_when_armed(self) -> None:
        bare = self._sent()
        self.assertEqual(bare["path"], "/ehp")
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, bare["body"])
                self.assertIs(self._sent(**{seam: True})["body"][seam], True)

    def test_the_transport_is_emitted_only_when_given(self) -> None:
        self.assertNotIn(_TRANSPORT, self._sent()["body"])
        self.assertEqual(self._sent(**{_TRANSPORT: 3})["body"][_TRANSPORT], 3.0)

    def test_the_bare_body_is_the_pre_wire_shape(self) -> None:
        self.assertEqual(
            set(self._sent()["body"]),
            {"champion", "level", "items", "mode",
             "enemy_ad_share", "enemy_ap_share"},
        )


class PerRouteReachabilityTests(_Base):
    """Gate 4: PER-(route, seam), never name-collapsed."""

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


if __name__ == "__main__":                                      # pragma: no cover
    unittest.main()
