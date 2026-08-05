"""RM-118 residual: the FIVE stranded per-item shield seams reach ``/ehp``.

THE DEFECT
----------
``test_stranded_hsp_seam_r197.py::STRANDED_TODAY`` ledgered these five engine
seams as debt. Each one's ENGINE half shipped complete - the ``ItemShield``
registry row, the ``_collect_shields`` arming branch and the EHP-numerator
consumer - while no route in ``server.py`` parsed the flag, so no coach tick,
no generated build table, no operator curl and no Python client function could
ever arm one.

  * ``assume_kaenic_shield``       - Kaenic Rookern 2504 / Arena 222504
    (Magebane, 15 percent max HP MAGIC shield).
  * ``assume_eclipse_shield``      - Eclipse 6692 / Arena 226692
    (Ever Rising Moon, 160 +40 percent bonus AD generic shield, 0.5x ranged).
  * ``assume_chainlaced_shield``   - Chainlaced Crushers 3173
    (Noxian Persistence, 100 at L1 -> 200 at L18 +8 percent bonus HP MAGIC).
  * ``assume_seraphs_shield``      - Seraph's Embrace 3040 / 223040 / 323040
    (Lifeline, 18 percent max mana generic shield).
  * ``assume_fimbulwinter_shield`` - Fimbulwinter 3121 / 223121 / 323121
    (Everlasting, 100 +4.5 percent max mana generic shield).

Same defect class R197 fixed for ``assume_hsp_amp``, 1.266.0 for the four EHP
survivability seams, 1.267.0 for the three rune lanes, 1.268.0 for the two vamp
lanes and 1.274.0 for the crit-chance override lane.

EXPOSURE IS NOT A DEFAULT FLIP
------------------------------
The ledger reason these five carried - "live flip operator-gated" - conflates
two separate questions, exactly as the crit-chance lane's "unmeasured live flip"
reason did before 1.274.0. This slice ships ROUTE EXPOSURE only: every seam stays
``bool = False`` on ``compute_ehp``, every body key is optional, and every client
argument is emitted only when armed. No default is flipped anywhere. The live
default flip remains unshipped, unclaimed and operator-gated.

ROUTE OWNERSHIP IS PER-SEAM, NOT PER-FAMILY (reference_ds_seam_reachability_per_route)
-------------------------------------------------------------------------------------
MEASURED off ``inspect.signature`` over every module in the package, never
inherited from a sibling slice's prose:

  ============================  ========================================
  seam                          engine entry points -> routes
  ============================  ========================================
  assume_kaenic_shield          compute_ehp -> /ehp   (and NOTHING else)
  assume_eclipse_shield         compute_ehp -> /ehp   (and NOTHING else)
  assume_chainlaced_shield      compute_ehp -> /ehp   (and NOTHING else)
  assume_seraphs_shield         compute_ehp -> /ehp   (and NOTHING else)
  assume_fimbulwinter_shield    compute_ehp -> /ehp   (and NOTHING else)
  ============================  ========================================

``rank_items_by_ehp`` does NOT name any of the five, nor do ``compute_hybrid`` /
``rank_items_by_hybrid`` / ``compute_dps``, so ``/rank-tank``, ``/hybrid``,
``/rank-bruiser`` and ``/dps`` must NOT grow any of these keys - a parsed key
its engine function cannot accept is the R194 parse-without-pass shape, dead
before the engine call. The only other function naming them is the private
helper ``ehp._collect_shields``, which is engine-internal by construction (the
R197 guard only walks functions ``server.py`` calls).

TRANSPORT: ``items`` FOR ALL FIVE, AND NOTHING ELSE
---------------------------------------------------
A flag that parses and then cannot change a number is the RM-115
reachable-and-dead failure mode, so each lane's transport was checked, not
assumed. ``_collect_shields`` arms per ITEM ID off the equipped inventory, and
the magnitudes resolve off ``level`` (Chainlaced lerp), the resolved
``max_hp`` / ``max_mana`` / ``bonus_ad`` stat block and ``is_ranged``. Every one
of those inputs is derived from ``champion`` + ``level`` + ``items``, all three
of which ``/ehp`` has parsed since Phase 1. No new transport is needed and none
is added. The ON-path movement is measured per seam below, so none of the five
ships settable-and-inert.

DEFAULT-OFF
-----------
``_collect_shields`` drops a ``default_off`` shield before resolving its
magnitude unless the caller arms THAT item's specific seam, so an omitted body
key is a byte-identical route response. Per-seam arming is also non-leaking: on
a build carrying two default-off shields, arming one credits exactly one. Both
measured below.

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
from agents.daemon_slayer.effects import ITEM_EFFECTS
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
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

_KAENIC = "assume_kaenic_shield"
_ECLIPSE = "assume_eclipse_shield"
_CHAINLACED = "assume_chainlaced_shield"
_SERAPHS = "assume_seraphs_shield"
_FIMBUL = "assume_fimbulwinter_shield"

_SEAMS = (_KAENIC, _ECLIPSE, _CHAINLACED, _SERAPHS, _FIMBUL)
# The MEASURED route table this slice wires. One route, all five seams.
_ROUTES_BY_SEAM: dict[str, tuple[str, ...]] = {seam: ("/ehp",) for seam in _SEAMS}
# Every OTHER EHP-family route. None of their engine functions names any of the
# five, so none of them may parse any of the keys.
_FORBIDDEN_ROUTES = ("/rank-tank", "/hybrid", "/rank-bruiser")

# The s232 target/caster-state entries that must SURVIVE this slice - the
# conditional-target-state arc is operator-CLOSED, so they are deliberately not
# client-facing and this ledger shrink must not take them along.
_S232_SURVIVORS = (
    "assume_ally_detonation",
    "assume_caster_lowhp",
    "assume_lifeline_shield",
    "assume_item_lowhp_magic_crit",
    "assume_passive_reflect",
)

_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
# One (champion, build) pair per seam, each carrying that seam's item plus two
# unrelated completed items so the resolved stat block is realistic.
_PROBES: dict[str, tuple[str, tuple[str, ...]]] = {
    # Magic-shield tank: Kaenic Rookern + Sunfire + Steelcaps.
    _KAENIC: ("Malphite", ("2504", "3068", "3047")),
    # Bonus-AD melee bruiser: Eclipse + Black Cleaver + Steelcaps.
    _ECLIPSE: ("Sett", ("6692", "3071", "3047")),
    # Level-lerped magic shield on a boots slot: Chainlaced + Sunfire + Wardens.
    _CHAINLACED: ("Sett", ("3173", "3068", "3075")),
    # Max-mana mage: Seraph's Embrace + Zhonya's + Sorcerer's Shoes.
    _SERAPHS: ("Ryze", ("3040", "3157", "3020")),
    # Max-mana tank: Fimbulwinter + Sunfire + Steelcaps.
    _FIMBUL: ("Sion", ("3121", "3068", "3047")),
}
# The MEASURED off/on ``blended_ehp`` pair per seam. These are the ON-path
# movement proofs: a wire that parsed a key and dropped it before the engine
# call would leave every ON value equal to its OFF twin.
_MEASURED: dict[str, tuple[float, float]] = {
    _KAENIC: (6560.949098552632, 7002.336717677632),
    _ECLIPSE: (4299.715930460527, 4670.6529041447375),
    _CHAINLACED: (5923.776993750001, 6113.777596691178),
    _SERAPHS: (3601.8210250000006, 4279.22489125),
    _FIMBUL: (5328.295964243422, 5729.085216995396),
}
# The full curated item set each seam arms, base id plus every mode mirror.
_ARMED_IDS: dict[str, tuple[str, ...]] = {
    _KAENIC: ("2504", "222504"),
    _ECLIPSE: ("6692", "226692"),
    _CHAINLACED: ("3173",),
    _SERAPHS: ("3040", "223040", "323040"),
    _FIMBUL: ("3121", "223121", "323121"),
}

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _body(champion: str, items: tuple[str, ...], **extra) -> dict:
    body = {
        "champion": champion,
        "level": _LEVEL,
        "items": list(items),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


def _probe_body(seam: str, **extra) -> dict:
    champion, items = _PROBES[seam]
    return _body(champion, items, **extra)


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

    def test_all_five_live_on_compute_ehp_default_off(self) -> None:
        params = inspect.signature(compute_ehp).parameters
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(seam, params)
                self.assertIs(
                    params[seam].default, False,
                    f"{seam} must ship DEFAULT-OFF on compute_ehp - this slice "
                    "exposes the seam, it does NOT flip a live default",
                )

    def test_no_other_route_facing_engine_function_names_them(self) -> None:
        """The scope pin the route guard exists to protect.

        ``rank_items_by_ehp`` / ``compute_hybrid`` / ``rank_items_by_hybrid`` /
        ``compute_dps`` do NOT name any of the five, which is exactly why
        /rank-tank, /hybrid, /rank-bruiser and /dps must not grow the keys. If a
        later slice extends a seam to one of those frames, THIS goes red and
        points at the route wire that then has to grow with it.
        """
        for fn in (rank_items_by_ehp, compute_hybrid, rank_items_by_hybrid,
                   compute_dps):
            params = inspect.signature(fn).parameters
            for seam in _SEAMS:
                with self.subTest(engine=fn.__name__, seam=seam):
                    self.assertNotIn(seam, params)

    def test_package_wide_sweep_pins_the_owning_functions(self) -> None:
        """Sweep every module so the table cannot silently grow.

        The expected set is the exact table this slice wired plus the private
        helper that does the per-item arming.
        """
        expected = {
            ("ehp", "compute_ehp"),
            ("ehp", "_collect_shields"),
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
            "the engine entry points naming a per-item shield seam changed - "
            "re-measure the route table in this file's docstring before wiring "
            "anything",
        )

    def test_every_armed_item_is_a_default_off_shield(self) -> None:
        for seam, ids in _ARMED_IDS.items():
            for iid in ids:
                with self.subTest(seam=seam, item=iid):
                    eff = ITEM_EFFECTS.get(iid)
                    self.assertIsNotNone(eff, f"{iid} has no item effect row")
                    self.assertIsNotNone(
                        eff.shield, f"{iid} carries no ItemShield"
                    )
                    self.assertTrue(
                        eff.shield.default_off,
                        f"{iid} is not default-off - arming it would double "
                        "credit the always-on pool",
                    )


class StrandedLedgerTests(_Base):
    """Gate 2a: the self-cleaning debt ledger shrank by exactly these five."""

    def test_no_seam_is_stranded_any_more(self) -> None:
        stranded = stranded_seams(SERVER_SRC)
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, stranded)

    def test_no_seam_is_still_ledgered_as_debt(self) -> None:
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(
                    seam, STRANDED_TODAY,
                    f"{seam} is wired but still in STRANDED_TODAY - the ledger "
                    "can only shrink",
                )

    def test_the_s232_entries_survive_this_shrink(self) -> None:
        """The conditional-target-state arc is operator-CLOSED, not debt."""
        for seam in _S232_SURVIVORS:
            with self.subTest(seam=seam):
                self.assertIn(
                    seam, STRANDED_TODAY,
                    f"{seam} left the ledger - the s232 target/caster-state "
                    "entries are deliberately not client-facing",
                )


class EhpRouteParseAndForwardTests(_Base):
    """Gate 2b: ``/ehp`` parses AND forwards all five."""

    def test_the_handler_reads_all_five_keys(self) -> None:
        src = inspect.getsource(server._route_ehp)
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(f'_opt_bool(body, "{seam}", False)', src)

    def test_absent_keys_equal_explicit_defaults(self) -> None:
        explicit = dict.fromkeys(_SEAMS, False)
        for seam in _SEAMS:
            with self.subTest(build=seam):
                self.assertEqual(
                    server._route_ehp(_probe_body(seam)),
                    server._route_ehp(_probe_body(seam, **explicit)),
                )

    def test_the_string_and_int_forms_follow_the_shared_opt_bool_contract(
        self,
    ) -> None:
        """``_opt_bool`` accepts curl-shaped truthies; garbage falls back OFF.

        Pinned so a later edit cannot make one of these five parse differently
        from every other boolean seam on the route. A garbage value collapsing
        to the default is what keeps a malformed body byte-identical rather than
        silently armed.
        """
        armed = server._route_ehp(_probe_body(_KAENIC, **{_KAENIC: True}))
        off = server._route_ehp(_probe_body(_KAENIC))
        for truthy in ("true", "TRUE", "yes", "on", "1", 1):
            with self.subTest(value=truthy):
                self.assertEqual(
                    server._route_ehp(_probe_body(_KAENIC, **{_KAENIC: truthy})),
                    armed,
                )
        for falsy in ("nope", "", 0, None, []):
            with self.subTest(value=falsy):
                self.assertEqual(
                    server._route_ehp(_probe_body(_KAENIC, **{_KAENIC: falsy})),
                    off,
                )


class MeasuredOnPathTests(_Base):
    """Gate 2c: EVERY seam MOVES the route number, with a pinned pair."""

    def _blended(self, seam: str, **extra) -> float:
        return server._route_ehp(_probe_body(seam, **extra))["blended_ehp"]

    def test_the_measured_off_on_pair_per_seam(self) -> None:
        for seam, (off, on) in _MEASURED.items():
            with self.subTest(seam=seam):
                self.assertAlmostEqual(self._blended(seam), off, places=6)
                self.assertAlmostEqual(
                    self._blended(seam, **{seam: True}), on, places=6
                )

    def test_arming_each_seam_raises_blended_ehp(self) -> None:
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertGreater(
                    self._blended(seam, **{seam: True}),
                    self._blended(seam),
                    f"{seam} was parsed but never reached compute_ehp",
                )

    def test_a_build_without_the_item_is_an_exact_no_op(self) -> None:
        """The flag is a per-ITEM opt-in, never a flat survivability lift."""
        neutral = ("3068", "3047", "3075")
        for seam in _SEAMS:
            champion, _ = _PROBES[seam]
            with self.subTest(seam=seam):
                self.assertEqual(
                    server._route_ehp(_body(champion, neutral)),
                    server._route_ehp(_body(champion, neutral, **{seam: True})),
                )

    def test_arming_one_seam_never_credits_another_items_shield(self) -> None:
        """Per-seam arming must not leak across the default-off pool.

        Sett carries BOTH Eclipse 6692 and Chainlaced Crushers 3173 here, so a
        wire that collapsed the five flags into one shared boolean - or an
        engine edit that widened an arming branch - shows up as the single-seam
        response matching the both-armed one.
        """
        champion = "Sett"
        both = ("6692", "3173", "3047")
        base = server._route_ehp(_body(champion, both))["blended_ehp"]
        only_eclipse = server._route_ehp(
            _body(champion, both, **{_ECLIPSE: True})
        )["blended_ehp"]
        only_chain = server._route_ehp(
            _body(champion, both, **{_CHAINLACED: True})
        )["blended_ehp"]
        armed_both = server._route_ehp(
            _body(champion, both, **{_ECLIPSE: True, _CHAINLACED: True})
        )["blended_ehp"]
        self.assertGreater(only_eclipse, base)
        self.assertGreater(only_chain, base)
        self.assertGreater(armed_both, only_eclipse)
        self.assertGreater(armed_both, only_chain)

    def test_the_route_matches_the_engine_call_it_claims_to_make(self) -> None:
        for seam in _SEAMS:
            champion, items = _PROBES[seam]
            with self.subTest(seam=seam):
                self.assertAlmostEqual(
                    self._blended(seam, **{seam: True}),
                    _engine(champion, items, **{seam: True}).blended_ehp,
                    places=9,
                )


class RouteScopeTests(_Base):
    """Gate 5: no OTHER route may carry any of the five keys."""

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

    def test_ehp_for_names_all_five_default_off(self) -> None:
        params = inspect.signature(client_mod.ehp_for).parameters
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertIn(seam, params)
                self.assertIs(params[seam].default, False)

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

        champion, items = _PROBES[_KAENIC]
        with mock.patch.object(client_mod, "_post_json", _fake):
            client_mod.ehp_for(
                champion,
                level=_LEVEL,
                item_ids=list(items),
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
