"""RM-118 residual: the FOUR genuinely wireable stranded seams reach their routes.

THE DEFECT
----------
``test_stranded_hsp_seam_r197.py::STRANDED_TODAY`` ledgered 14 engine seams as
debt. Ten of those fourteen are DECLINED BY DESIGN, not debt: the five
target/caster-STATE seams belong to the conditional-target-state arc that is
operator-CLOSED (s232), and the five per-item shield opt-ins each carry an
operator-gated live flip that is still pending. This slice wires the other four,
which are debt in the strict sense - the ENGINE half shipped complete, and no
route in ``server.py`` parsed the flag, so no coach tick, no operator curl and
no Python client function could arm them:

  * ``apply_crit_chance_overrides`` (R212, ENGINE 1.253.0) -
    ``_crit_chance_overrides.resolve_crit`` / ``overflow_bonus_ad`` apply the
    per-champion crit-chance multiplier, the overflow-AD conversion, the Senna
    overflow life steal and Jhin's 0.86 crit-damage penalty. Four registered
    rows (Yasuo / Yone / Senna / Jhin) out of 173.
  * ``apply_ability_hsp_amp`` (ENGINE 1.202.0) - amps the CHAMPION-ABILITY
    heal/shield fold by the wielder's own item Heal/Shield-Power factor, the
    lane the item-throughput half had since R60.
  * ``apply_cast_rate_propensity_prior`` (RM-98) - the propensity PRIOR half of
    the cast-rate work; RM-98 adjudicated the TIME BASE and shipped it, and the
    prior was never route-exposed.
  * ``assume_ms_utility`` (R58, ENGINE 1.167.0) - the bonus-movement-speed
    utility multiplier on the hybrid axis.

Same defect class R197 fixed for ``assume_hsp_amp``, 1.266.0 for the four EHP
survivability seams, and 1.267.0 / 1.268.0 for the rune and vamp lanes.

ROUTE OWNERSHIP IS PER-SEAM, MEASURED OFF ``inspect.signature``
---------------------------------------------------------------
Never inherited from a sibling slice's docstring - that prose was wrong in BOTH
directions on 2026-07-30 (the rune slice found MORE routes than stated, the vamp
slice FEWER). Swept over every module in the package:

  ================================  ===========================================
  seam                              engine entry points -> routes
  ================================  ===========================================
  apply_crit_chance_overrides       compute_dps            -> /dps
  apply_ability_hsp_amp             compute_hps            -> /hps
  apply_cast_rate_propensity_prior  compute_hybrid         -> /hybrid
                                    rank_items_by_hybrid   -> /rank-bruiser
  assume_ms_utility                 compute_hybrid         -> /hybrid
                                    rank_items_by_hybrid   -> /rank-bruiser
  ================================  ===========================================

The asymmetries are the thing the guards below protect, and each is asserted
rather than left to convention:

  * ``rank_items_by_hps`` does NOT name ``apply_ability_hsp_amp`` (hps.py:863),
    so ``/rank-enchanter`` must not grow that key.
  * ``rank_items()`` - the CARRY ranker behind ``/rank`` - does NOT name
    ``apply_crit_chance_overrides``, so ``/rank`` must not grow it. ``/dps`` is
    the sole owner, exactly as R7 / R12 / the melee-AA gate are /dps-scoped.
  * ``compute_dps`` names neither hybrid seam, so ``/dps`` must not grow
    ``apply_cast_rate_propensity_prior`` or ``assume_ms_utility``.

TRANSPORT: ALL FOUR ARE PURE BOOLEANS
-------------------------------------
Checked explicitly, because a flag-only wire on a seam that needs a data
transport ships something settable, guard-green and arithmetically INERT (the
RM-115 failure mode; ``/dps`` had no ``rune_ids`` and ``/ehp`` no
``targets_in_rotation``). None of these four needs one:

  * the crit registry is keyed by ``champion_id``, already required by /dps;
  * the HSP amp factor is derived from ``item_ids``, already parsed by /hps;
  * the propensity prior rides ``result.per_spell``, computed in-engine;
  * the MS multiplier reads ``dps_result.stats["ms"]`` and the champion's base
    movespeed out of the snapshot.

So the flag alone is sufficient, and the ON-path arithmetic movement measured
below is the proof - not the absence of a transport-shaped parameter.

DEFAULT-OFF
-----------
All four default False on every engine entry point and each consumer sits
inside the ``if`` its flag opens (dps.py:1124, hps.py:685, hybrid.py:193 / 332 /
792 / 1363). An omitted body key is therefore a byte-identical route response,
measured below against an explicit ``False``.

OFFLINE ONLY: no live :8860, no network. Direct handler + engine + client calls.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest

import agents.daemon_slayer as ds_pkg
import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.hybrid import compute_hybrid, rank_items_by_hybrid
from agents.daemon_slayer.tests.test_route_seams_reach_the_client_per_route import (
    _client_by_route,
    _route_table,
)
from agents.daemon_slayer.tests.test_stranded_hsp_seam_r197 import (
    STRANDED_TODAY,
    stranded_seams,
)

_CRIT = "apply_crit_chance_overrides"
_ABILITY_HSP = "apply_ability_hsp_amp"
_PRIOR = "apply_cast_rate_propensity_prior"
_MS = "assume_ms_utility"

_SEAMS = (_CRIT, _ABILITY_HSP, _PRIOR, _MS)

# The MEASURED route table this slice wires.
_ROUTES_BY_SEAM: dict[str, tuple[str, ...]] = {
    _CRIT: ("/dps",),
    _ABILITY_HSP: ("/hps",),
    _PRIOR: ("/hybrid", "/rank-bruiser"),
    _MS: ("/hybrid", "/rank-bruiser"),
}
# route -> seams that route must NOT carry. Manufacturing reachability on a
# route whose engine entry point cannot read the flag is the reachable-and-dead
# illusion RM-115 exists to kill.
_FORBIDDEN_BY_ROUTE: dict[str, tuple[str, ...]] = {
    "/rank-enchanter": (_ABILITY_HSP,),
    "/rank": (_CRIT,),
    "/dps": (_PRIOR, _MS),
    "/hps": (_CRIT, _PRIOR, _MS),
}

_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
_CRIT_ITEMS = ("3031", "3006", "3094")      # IE + boots + Rageblade
_HSP_ITEMS = ("3504", "3107", "3222")       # Ardent + Redemption + Mikael's
_AP_ITEMS = ("3020", "6653", "3089")        # Sorcs + Liandry's + Deathcap
_AP_PARTIAL = ("3020", "6653")

# MEASURED movers (this file's probe, ENGINE 1.271.0). Yasuo / Yone carry the
# crit-chance doubling + overflow AD; Jhin carries the 0.86 crit-damage penalty,
# so his DPS moves DOWN. Senna is registered but her lane is overflow LIFE STEAL,
# which this DPS build does not surface - deliberately not asserted as a mover.
_CRIT_MOVERS = ("Yasuo", "Yone", "Jhin")
_HSP_CHAMP = "Soraka"
_HYBRID_CHAMP = "Ahri"

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _dps_body(champion: str = "Yasuo", **extra) -> dict:
    body = {
        "champion": champion,
        "level": _LEVEL,
        "items": list(_CRIT_ITEMS),
        "mode": "SR",
        "target_armor": 100.0,
        "target_mr": 100.0,
    }
    body.update(extra)
    return body


def _hps_body(**extra) -> dict:
    body = {
        "champion": _HSP_CHAMP,
        "level": _LEVEL,
        "items": list(_HSP_ITEMS),
        "mode": "SR",
    }
    body.update(extra)
    return body


def _hybrid_body(**extra) -> dict:
    body = {
        "champion": _HYBRID_CHAMP,
        "level": _LEVEL,
        "items": list(_AP_ITEMS),
        "mode": "SR",
        "target_armor": 100.0,
        "target_mr": 100.0,
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    body.update(extra)
    return body


def _bruiser_rank_body(**extra) -> dict:
    # No truncation (reference_ds_probe_depth_top40_truncation).
    body = _hybrid_body(items=list(_AP_PARTIAL), top=200)
    body.update(extra)
    return body


def _order(result_dict: dict) -> tuple[str, ...]:
    return tuple(r["item_id"] for r in result_dict["ranked"])


def _hybrid_rank(**kwargs):
    return rank_items_by_hybrid(
        _snap(),
        champion_id=_HYBRID_CHAMP,
        level=_LEVEL,
        current_item_ids=list(_AP_PARTIAL),
        mode="SR",
        target_armor=100.0,
        target_mr=100.0,
        enemy_ad_share=0.5,
        enemy_ap_share=0.5,
        top_n=None,
        **kwargs,
    )


def _engine_owners(seam: str) -> set[str]:
    """Every package function whose signature names ``seam``. No prose."""
    owners: set[str] = set()
    for mod_info in pkgutil.iter_modules(ds_pkg.__path__):
        if mod_info.ispkg:
            continue
        try:
            mod = importlib.import_module(f"{ds_pkg.__name__}.{mod_info.name}")
        except Exception:
            continue
        for fname, fn in vars(mod).items():
            if not inspect.isfunction(fn):
                continue
            if getattr(fn, "__module__", None) != mod.__name__:
                continue
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                continue
            if seam in params:
                owners.add(f"{mod_info.name}.{fname}")
    return owners


class RouteOwnershipIsMeasured(unittest.TestCase):
    """The table in the docstring is re-derived here, never trusted."""

    def test_public_entry_points_match_the_wired_route_table(self):
        expected_entry_points = {
            _CRIT: {"dps.compute_dps"},
            _ABILITY_HSP: {"hps.compute_hps"},
            _PRIOR: {"hybrid.compute_hybrid", "hybrid.rank_items_by_hybrid"},
            _MS: {"hybrid.compute_hybrid", "hybrid.rank_items_by_hybrid"},
        }
        for seam, expected in expected_entry_points.items():
            with self.subTest(seam=seam):
                public = {
                    o for o in _engine_owners(seam)
                    if not o.split(".", 1)[1].startswith("_")
                }
                self.assertEqual(
                    public, expected,
                    "engine route-ownership moved - re-measure the route table "
                    "before changing server.py",
                )

    def test_every_seam_defaults_off_on_every_owner(self):
        for seam in _SEAMS:
            for owner in _engine_owners(seam):
                mod_name, fn_name = owner.split(".", 1)
                mod = importlib.import_module(f"{ds_pkg.__name__}.{mod_name}")
                param = inspect.signature(getattr(mod, fn_name)).parameters[seam]
                with self.subTest(seam=seam, owner=owner):
                    self.assertIs(
                        param.default, False,
                        "a seam that does not default False cannot be wired "
                        "byte-identically",
                    )

    def test_all_four_are_pure_booleans_no_transport_needed(self):
        """No non-boolean companion parameter shipped with any of the four."""
        for seam in _SEAMS:
            for owner in _engine_owners(seam):
                mod_name, fn_name = owner.split(".", 1)
                mod = importlib.import_module(f"{ds_pkg.__name__}.{mod_name}")
                ann = inspect.signature(getattr(mod, fn_name)).parameters[seam].annotation
                with self.subTest(seam=seam, owner=owner):
                    self.assertIn(
                        ann, (bool, "bool"),
                        "seam is not a plain bool - it may need a transport",
                    )


class SeamsAreNoLongerStranded(unittest.TestCase):
    """The R197 reachability checker, run against the shipped server source."""

    def test_none_of_the_four_is_stranded_any_more(self):
        stranded = stranded_seams(server_src())
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(seam, stranded)

    def test_none_of_the_four_remains_in_the_debt_ledger(self):
        for seam in _SEAMS:
            with self.subTest(seam=seam):
                self.assertNotIn(
                    seam, STRANDED_TODAY,
                    "wired seams must be deleted from STRANDED_TODAY, not left "
                    "with a reason",
                )

    def test_the_ten_declined_seams_are_untouched(self):
        """This slice drains 4 of 14 and must not silently drain the other 10."""
        self.assertEqual(
            len(STRANDED_TODAY), 10,
            "the remaining ledger is the 5 operator-CLOSED target/caster-state "
            "seams plus the 5 operator-gated per-item shield opt-ins",
        )


def server_src() -> str:
    import pathlib
    return pathlib.Path(server.__file__).read_text(encoding="utf-8")


class RoutesCarryTheKey(unittest.TestCase):
    """Parsed AND passed - parsing alone is the third stranded shape (R194)."""

    def setUp(self):
        self.parsed, self.handler_of = _route_table()

    def _handler_src(self, route: str) -> str:
        return inspect.getsource(getattr(server, self.handler_of[route]))

    def test_each_owning_route_parses_and_forwards_its_seams(self):
        for seam, routes in _ROUTES_BY_SEAM.items():
            for route in routes:
                handler_src = self._handler_src(route)
                with self.subTest(seam=seam, route=route):
                    self.assertIn(
                        seam, self.parsed[route],
                        "route does not parse the seam out of the body",
                    )
                    self.assertIn(
                        f"{seam}={seam}", handler_src,
                        "route parses the seam and then drops it before the "
                        "engine call",
                    )

    def test_non_owning_routes_do_not_manufacture_reachability(self):
        for route, seams in _FORBIDDEN_BY_ROUTE.items():
            for seam in seams:
                with self.subTest(route=route, seam=seam):
                    self.assertNotIn(
                        seam, self.parsed.get(route, frozenset()),
                        "route emits a key its engine entry point cannot read",
                    )


class SeamsReachThePythonClient(unittest.TestCase):
    """A route key no client function can express is only half-reachable."""

    def test_each_route_client_function_can_express_its_seams(self):
        by_route = _client_by_route()
        for seam, routes in _ROUTES_BY_SEAM.items():
            for route in routes:
                with self.subTest(seam=seam, route=route):
                    self.assertIn(route, by_route, "route has no client function")
                    self.assertIn(
                        seam, by_route[route],
                        "client function POSTing this route cannot express the "
                        "seam",
                    )


class _RouteBase(unittest.TestCase):
    """Route handlers read the module-level snapshot cache, not a parameter."""

    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class OmittedKeyIsByteIdentical(_RouteBase):
    """DEFAULT-OFF contract, measured on the route, not asserted from prose."""

    def test_dps_omitted_matches_explicit_false(self):
        self.assertEqual(
            server._route_dps(_dps_body()),
            server._route_dps(_dps_body(**{_CRIT: False})),
        )

    def test_hps_omitted_matches_explicit_false(self):
        self.assertEqual(
            server._route_hps(_hps_body()),
            server._route_hps(_hps_body(**{_ABILITY_HSP: False})),
        )

    def test_hybrid_omitted_matches_explicit_false(self):
        self.assertEqual(
            server._route_hybrid(_hybrid_body()),
            server._route_hybrid(_hybrid_body(**{_PRIOR: False, _MS: False})),
        )

    def test_rank_bruiser_omitted_matches_explicit_false(self):
        self.assertEqual(
            server._route_rank_bruiser(_bruiser_rank_body()),
            server._route_rank_bruiser(
                _bruiser_rank_body(**{_PRIOR: False, _MS: False})
            ),
        )


class OnPathMovesArithmetic(_RouteBase):
    """Reachable-and-DEAD is the failure mode; each ON path must move a number."""

    def test_crit_overrides_move_dps_for_every_registered_mover(self):
        for champ in _CRIT_MOVERS:
            off = server._route_dps(_dps_body(champ))
            on = server._route_dps(_dps_body(champ, **{_CRIT: True}))
            with self.subTest(champion=champ):
                self.assertNotEqual(
                    off["weighted_dps"], on["weighted_dps"],
                    "registered crit-override row did not move over the route",
                )

    def test_crit_overrides_are_identity_for_an_unregistered_champion(self):
        # 169 of 173 champions have no registry row - byte-identical even ON.
        off = server._route_dps(_dps_body("Ashe"))
        on = server._route_dps(_dps_body("Ashe", **{_CRIT: True}))
        self.assertEqual(off, on)

    def test_ability_hsp_amp_moves_total_throughput(self):
        off = server._route_hps(_hps_body())
        on = server._route_hps(_hps_body(**{_ABILITY_HSP: True}))
        self.assertGreater(on["total_throughput"], off["total_throughput"])

    def test_ability_hsp_amp_is_identity_without_an_hsp_item(self):
        # amp_factor == 1.0 -> byte-identical even ON.
        plain = _hps_body(items=["3020", "3089"])
        self.assertEqual(
            server._route_hps(plain),
            server._route_hps(dict(plain, **{_ABILITY_HSP: True})),
        )

    def test_propensity_prior_moves_the_hybrid_score(self):
        off = server._route_hybrid(_hybrid_body())
        on = server._route_hybrid(_hybrid_body(**{_PRIOR: True}))
        self.assertNotEqual(off["hybrid_score"], on["hybrid_score"])

    def test_ms_utility_moves_the_hybrid_score(self):
        off = server._route_hybrid(_hybrid_body())
        on = server._route_hybrid(_hybrid_body(**{_MS: True}))
        self.assertNotEqual(off["hybrid_score"], on["hybrid_score"])

    def test_both_hybrid_seams_move_the_bruiser_item_ORDER(self):
        """Stronger than a moved number: the item CHOICE changes."""
        base = _order(server._route_rank_bruiser(_bruiser_rank_body()))
        for seam in (_PRIOR, _MS):
            with self.subTest(seam=seam):
                moved = _order(
                    server._route_rank_bruiser(_bruiser_rank_body(**{seam: True}))
                )
                self.assertEqual(len(base), len(moved))
                self.assertNotEqual(
                    base, moved,
                    "seam reaches the ranker but cannot change an item choice",
                )

    def test_route_on_path_matches_the_engine_on_path(self):
        """The route is not quietly computing something else."""
        engine = compute_hybrid(
            _snap(),
            champion_id=_HYBRID_CHAMP,
            level=_LEVEL,
            item_ids=list(_AP_ITEMS),
            mode="SR",
            target_armor=100.0,
            target_mr=100.0,
            enemy_ad_share=0.5,
            enemy_ap_share=0.5,
            **{_PRIOR: True, _MS: True},
        )
        route = server._route_hybrid(_hybrid_body(**{_PRIOR: True, _MS: True}))
        self.assertEqual(route["hybrid_score"], engine.hybrid_score)

    def test_ranker_on_path_matches_the_engine_on_path(self):
        engine = _hybrid_rank(**{_PRIOR: True, _MS: True})
        route = server._route_rank_bruiser(
            _bruiser_rank_body(**{_PRIOR: True, _MS: True})
        )
        self.assertEqual(
            _order(route), tuple(r.item_id for r in engine.ranked),
        )


class NegativeControls(unittest.TestCase):
    """Proof the guards above are not vacuously green."""

    def test_stranded_checker_reports_a_seam_removed_from_the_source(self):
        src = server_src()
        for seam in _SEAMS:
            stripped = "\n".join(
                ln for ln in src.splitlines() if seam not in ln
            )
            with self.subTest(seam=seam):
                self.assertEqual(stripped.count(seam), 0)
                self.assertIn(
                    seam, stranded_seams(stripped),
                    "checker stayed green on a source with the seam removed",
                )

    def test_client_reachability_checker_sees_a_missing_name(self):
        self.assertNotIn(
            "apply_crit_chance_overrides_TYPO", _client_by_route()["/dps"],
            "the client name collector accepts names that are not there",
        )

    def test_client_module_is_the_one_under_test(self):
        self.assertTrue(client_mod.__file__.endswith("daemon_slayer_client.py"))


if __name__ == "__main__":
    unittest.main()
