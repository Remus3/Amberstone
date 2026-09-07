"""RM-200 - route exposure for the SCALING wielder-HSP lane.

THE DEFECT
----------
``_hsp_amp.sum_wielder_hsp_pct`` gained a keyword-only ``assume_scaling_hsp_grants``
at R197 (``_hsp_amp.py:26``). It folds in the ADDITIONAL Heal-and-Shield-Power an
item earns from a SCALING clause, which the curated ``enchanter_items.json``
``heal_shield_amp_pct`` field structurally cannot carry - that field stores only
the FLAT PRINTED stat. Dawncore prints 16% and its First Light clause
("2% heal and shield power for every additional 100% base mana regeneration")
earned zero without the flag.

The seam was EXECUTED but STRANDED. Both production call sites -
``ehp.py:1951`` and ``sustain.py:382`` - called the helper without the kwarg, so
neither ``compute_ehp`` nor ``compute_sustain`` could express it, no route parsed
it, and no client could set it. ``grep -c assume_scaling_hsp_grants server.py``
returned 0.

Same defect class as R197 (``assume_hsp_amp``) and R194(a)
(``assume_max_stacks_omnivamp``), and invisible to the DEPTH-0 stranded-seam
guard for a structural reason RM-202 recorded: the owner was one hop below the
route-facing entry points, so it sat in the depth-1 tier
(``test_stranded_hsp_seam_r197.STRANDED_DEPTH1``).

WHAT THIS SLICE SHIPS: route EXPOSURE, DEFAULT-OFF. Not a default flip. Every
existing caller stays byte-identical, and the live default-ON flip remains
unshipped and unclaimed.

THE THREE GATES (RM-118 durable)
--------------------------------
A seam is reachable only when all three hold, and flag-only wiring ships
something settable, guard-green and arithmetically INERT:

  1. FLAG ...... server.py parses the body key AND forwards it (both halves -
     R194 recorded a parse-side drop that made a live re-rank read as inert).
  2. TRANSPORT . the id that ARMS the seam must be able to reach the helper.
     Here that is the item list: Dawncore ``6621`` travels ``items`` ->
     ``_coerce_str_list`` -> ``item_ids`` -> ``sum_wielder_hsp_pct``. Both
     routes already carried it (``server.py:656`` for /ehp, ``server.py:2115``
     for /sustain), so no new transport was needed - CONFIRMED by measurement
     below, not assumed.
  3. OWNER ..... the engine function that actually reads it. Measured here by a
     package-wide ``inspect.signature`` sweep, never inherited from a docstring:
     a sibling slice's docstring was wrong twice in OPPOSITE directions in one
     run (it overstated the rune lanes' routes and understated the vamp lanes').

A FOURTH FACT, MEASURED RATHER THAN DESIGNED
--------------------------------------------
This seam is a MODIFIER of the flat item lane, not an independent switch. Both
call sites reach the helper only inside their ``assume_hsp_amp`` branch, so
arming this flag ALONE is byte-identical. That is asserted below rather than
left to be rediscovered, and it is why the pair is documented together.

CLIENT REACHABILITY IS DELIBERATELY NOT ASSERTED HERE. The existing per-route
equality guard
(``test_route_seams_reach_the_client_per_route.py``) already keys its ledger by
(route, seam) over every route, so forgetting the client wire turns THAT guard
red on its own - a stronger check than anything duplicated here, and it keeps
this file free of a ``core.*`` import that would make it host-dependent, i.e.
unable to run against the engine package without the host application present.

Offline only - no server start, no sockets. AST + inspect + direct handler calls.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import pkgutil
import textwrap
import unittest

from .. import server as S
from ..data_loader import DataSnapshot
from ..ehp import compute_ehp
from ..sustain import compute_sustain
from .._hsp_amp import sum_wielder_hsp_pct

SEAM = "assume_scaling_hsp_grants"

# Dawncore (SR). The ONLY armed magnitude on the SR line: First Light grants
# 0.02 on top of the 0.16 flat printed stat, so 0.16 OFF -> 0.18 ON.
DAWNCORE = "6621"
# Redemption carries 0.10 flat AND enough base mana regen to buy Dawncore a
# SECOND First Light step, which is why the pair moves 0.26 -> 0.30 and not
# 0.26 -> 0.28. Pinned below so a registry edit cannot silently change it.
REDEMPTION = "3107"
# Sterak's Gage - a wielder SELF-SHIELD with NO HSP stat of its own. Required
# for the /ehp proof: shield_amp_mult scales the ItemShield POOL, so without a
# self-shield item the pool is 0.0 and the amp moves the multiplier while
# moving no score (measured on the R197 pair, recorded there too).
STERAKS = "3053"

# The flat-lane partner. This seam is inert without it (see the module docstring).
FLAT = "assume_hsp_amp"


def _package_functions() -> dict[str, object]:
    """Every function defined in the daemon_slayer package, by qualified name.

    A package-wide sweep rather than a route-facing walk: the OWNER question is
    "who reads this kwarg", and answering it from the route side would inherit
    exactly the assumption this table exists to check.
    """
    import agents.daemon_slayer as pkg

    out: dict[str, object] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name == "tests" or info.name.startswith("test_"):
            continue
        try:
            mod = importlib.import_module(f"agents.daemon_slayer.{info.name}")
        except Exception:  # noqa: BLE001 - an unimportable module owns no seam
            continue
        for name, obj in vars(mod).items():
            if inspect.isfunction(obj) and obj.__module__ == mod.__name__:
                out[f"{info.name}.{name}"] = obj
    return out


def _owners(seam: str) -> set[str]:
    """Qualified names of package functions whose signature carries ``seam``."""
    found = set()
    for fq, fn in _package_functions().items():
        try:
            params = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            continue
        if seam in params:
            found.add(fq)
    return found


def _handler_tree(fn: object) -> ast.AST:
    return ast.parse(textwrap.dedent(inspect.getsource(fn)))


def _routes_parsing(seam: str) -> set[str]:
    """Routes whose handler reads ``seam`` out of the body via ``_opt_bool``."""
    out = set()
    for path, fn in S._POST_ROUTES.items():
        for n in ast.walk(_handler_tree(fn)):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_opt_bool"
                and len(n.args) >= 2
                and isinstance(n.args[1], ast.Constant)
                and n.args[1].value == seam
            ):
                out.add(path)
    return out


def _routes_passing(seam: str) -> set[str]:
    """Routes whose handler FORWARDS ``seam`` as a keyword on some call.

    The second half of gate 1. Parsing alone is not reachability.
    """
    out = set()
    for path, fn in S._POST_ROUTES.items():
        for n in ast.walk(_handler_tree(fn)):
            if isinstance(n, ast.Call) and any(kw.arg == seam for kw in n.keywords):
                out.add(path)
    return out


class SeamOwnerTable(unittest.TestCase):
    """GATE 3 - measured owners, never inherited from prose."""

    def test_owner_table_is_exactly_the_helper_and_its_two_entry_points(self):
        self.assertEqual(
            _owners(SEAM),
            {
                "_hsp_amp.sum_wielder_hsp_pct",
                "ehp.compute_ehp",
                "sustain.compute_sustain",
            },
            "owner table drifted - re-measure before editing any docstring that "
            "names the owners of this seam",
        )

    def test_sweep_is_not_vacuous(self):
        # A broken sweep would return an empty owner set and pass the negative
        # assertions below for the wrong reason.
        self.assertGreater(len(_package_functions()), 200)
        self.assertIn("ehp.compute_ehp", _package_functions())

    def test_both_entry_points_default_the_seam_off(self):
        for fn in (compute_ehp, compute_sustain):
            with self.subTest(fn=fn.__name__):
                p = inspect.signature(fn).parameters[SEAM]
                self.assertIs(p.default, False)

    def test_helper_keeps_the_seam_keyword_only(self):
        # Positional drift here would silently re-bind an existing caller's
        # ``patch`` argument.
        p = inspect.signature(sum_wielder_hsp_pct).parameters[SEAM]
        self.assertIs(p.kind, inspect.Parameter.KEYWORD_ONLY)


class SeamRouteTable(unittest.TestCase):
    """GATE 1 - the per-seam route table, parsed AND passed."""

    def test_parsed_on_exactly_the_two_owning_routes(self):
        self.assertEqual(_routes_parsing(SEAM), {"/ehp", "/sustain"})

    def test_passed_on_exactly_the_two_owning_routes(self):
        self.assertEqual(_routes_passing(SEAM), {"/ehp", "/sustain"})

    def test_no_other_route_leaks_the_seam(self):
        # The route table is an EQUALITY above; this states the negative half
        # explicitly because a leak onto a route whose scorer cannot read the
        # key is the reachable-and-dead illusion RM-115 exists to kill.
        others = set(S._POST_ROUTES) - {"/ehp", "/sustain"}
        self.assertTrue(others, "route dispatch collapsed")
        self.assertFalse(others & (_routes_parsing(SEAM) | _routes_passing(SEAM)))

    def test_both_routes_carry_the_item_transport(self):
        # GATE 2. Without an item list the flag is settable and arithmetically
        # inert - Dawncore could never reach the helper.
        for path in ("/ehp", "/sustain"):
            with self.subTest(route=path):
                src = inspect.getsource(S._POST_ROUTES[path])
                self.assertIn('_coerce_str_list(body.get("items"), "items")', src)


class HelperMagnitudes(unittest.TestCase):
    """Pin the curated + scaling magnitudes every measurement below rests on."""

    def test_dawncore_alone_moves_by_one_first_light_step(self):
        self.assertAlmostEqual(sum_wielder_hsp_pct([DAWNCORE]), 0.16, places=6)
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([DAWNCORE], assume_scaling_hsp_grants=True),
            0.18,
            places=6,
        )

    def test_redemption_buys_dawncore_a_second_step(self):
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([DAWNCORE, REDEMPTION]), 0.26, places=6
        )
        self.assertAlmostEqual(
            sum_wielder_hsp_pct(
                [DAWNCORE, REDEMPTION], assume_scaling_hsp_grants=True
            ),
            0.30,
            places=6,
        )

    def test_item_without_a_scaling_clause_is_unmoved(self):
        # The negative control for the helper: a flat-only HSP item must earn
        # nothing from this lane, or the flag is folding in the wrong quantity.
        self.assertAlmostEqual(
            sum_wielder_hsp_pct([REDEMPTION], assume_scaling_hsp_grants=True),
            0.10,
            places=6,
        )


class RouteDefaultOff(unittest.TestCase):
    """Omitting the key must be byte-identical on both routes."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        S._CACHE.set(cls.snap)

    def test_ehp_absent_key_equals_explicit_false(self):
        base = {
            "champion": "Aatrox",
            "level": 11,
            "items": [DAWNCORE, STERAKS],
            FLAT: True,
        }
        self.assertEqual(
            S._route_ehp(dict(base)),
            S._route_ehp({**base, SEAM: False}),
        )

    def test_sustain_absent_key_equals_explicit_false(self):
        base = {"champion": "DrMundo", "items": [DAWNCORE], FLAT: True}
        self.assertEqual(
            S._route_sustain(dict(base)),
            S._route_sustain({**base, SEAM: False}),
        )

    def test_armed_transport_with_flag_off_is_byte_identical(self):
        # THE TRANSPORT-REMOVAL TRIPWIRE. Dawncore is in the build on both
        # routes and the flag is OFF, so the response must equal the one from a
        # request that never names the seam. Paired with the movement proofs
        # below, this is what makes a future ``items`` removal fail loudly
        # instead of quietly collapsing ON onto OFF.
        ehp_body = {
            "champion": "Aatrox",
            "level": 11,
            "items": [DAWNCORE, STERAKS],
            FLAT: True,
        }
        self.assertEqual(
            S._route_ehp({**ehp_body, SEAM: False}),
            S._route_ehp(dict(ehp_body)),
        )
        sus_body = {"champion": "DrMundo", "items": [DAWNCORE], FLAT: True}
        self.assertEqual(
            S._route_sustain({**sus_body, SEAM: False}),
            S._route_sustain(dict(sus_body)),
        )

    def test_seam_alone_without_the_flat_lane_is_inert(self):
        # MEASURED, not designed: both call sites reach the helper only inside
        # their ``assume_hsp_amp`` branch, so this flag is a MODIFIER of the
        # flat item lane rather than an independent switch. Recorded so the
        # pairing is not rediscovered as a bug.
        ehp_body = {"champion": "Aatrox", "level": 11, "items": [DAWNCORE, STERAKS]}
        self.assertEqual(
            S._route_ehp({**ehp_body, SEAM: True}),
            S._route_ehp(dict(ehp_body)),
        )
        sus_body = {"champion": "DrMundo", "items": [DAWNCORE]}
        self.assertEqual(
            S._route_sustain({**sus_body, SEAM: True}),
            S._route_sustain(dict(sus_body)),
        )

    def test_flag_on_without_a_scaling_item_is_byte_identical(self):
        # No Dawncore in the build -> the lane has nothing to fold -> ON must
        # equal OFF. Proves the movement below comes from the SCALING clause
        # and not from the flag perturbing something else.
        ehp_body = {
            "champion": "Aatrox",
            "level": 11,
            "items": [REDEMPTION, STERAKS],
            FLAT: True,
        }
        self.assertEqual(
            S._route_ehp({**ehp_body, SEAM: True}),
            S._route_ehp(dict(ehp_body)),
        )
        sus_body = {"champion": "DrMundo", "items": [REDEMPTION], FLAT: True}
        self.assertEqual(
            S._route_sustain({**sus_body, SEAM: True}),
            S._route_sustain(dict(sus_body)),
        )


class RouteOnPathMovement(unittest.TestCase):
    """The ON-path proof. Named champion, level and inventory - not prose."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()
        S._CACHE.set(cls.snap)

    def test_ehp_on_moves_the_multiplier_and_the_score(self):
        # Aatrox L11 SR, [Dawncore 6621, Sterak's 3053]. Sterak's supplies the
        # ItemShield pool the multiplier scales; Dawncore supplies the HSP.
        body = {
            "champion": "Aatrox",
            "level": 11,
            "items": [DAWNCORE, STERAKS],
            FLAT: True,
        }
        flat = S._route_ehp(dict(body))
        scaled = S._route_ehp({**body, SEAM: True})
        # 1.0 heal_amp_mult * (1 + 0.16) OFF -> * (1 + 0.18) ON.
        self.assertAlmostEqual(flat["shield_amp_mult"], 1.16, places=6)
        self.assertAlmostEqual(scaled["shield_amp_mult"], 1.18, places=6)
        self.assertGreater(scaled["blended_ehp"], flat["blended_ehp"])

    def test_ehp_movement_is_exactly_one_first_light_step(self):
        # The shield pool enters the blend linearly in shield_amp_mult, so the
        # ON delta must be 0.18/0.16 of the flat-lane delta. Asserting the
        # RATIO rather than a hardcoded EHP keeps this from going stale on an
        # unrelated Aatrox or Sterak's data change.
        body = {
            "champion": "Aatrox",
            "level": 11,
            "items": [DAWNCORE, STERAKS],
            FLAT: True,
        }
        base = S._route_ehp({**body, FLAT: False})["blended_ehp"]
        flat = S._route_ehp(dict(body))["blended_ehp"]
        scaled = S._route_ehp({**body, SEAM: True})["blended_ehp"]
        self.assertGreater(flat - base, 0.0)
        self.assertAlmostEqual((scaled - base) / (flat - base), 0.18 / 0.16, places=6)

    def test_sustain_on_moves_the_score(self):
        # DrMundo SR, [Dawncore 6621]. His REGEN sustain is the amped kind.
        body = {"champion": "DrMundo", "items": [DAWNCORE], FLAT: True}
        flat = S._route_sustain(dict(body))
        scaled = S._route_sustain({**body, SEAM: True})
        self.assertGreater(scaled["sustain_score"], flat["sustain_score"])
        self.assertGreater(
            scaled["total_sustain_score"], flat["total_sustain_score"]
        )

    def test_sustain_movement_is_exactly_one_first_light_step(self):
        # DELTA, not places=6, and the looseness is the TRANSPORT's not the
        # model's: SustainResult.to_dict rounds sustain_score to 4 decimals, so
        # a ratio rebuilt from three rounded scores carries ~1.1e-3 of rounding
        # error (measured 1.12605 against an exact 1.125). The unrounded proof
        # is asserted at places=6 on the dataclass in EngineLevelSeam below.
        # 0.005 still separates one step (1.125) from no movement (1.0) and
        # from two steps (1.25) by two orders of magnitude.
        body = {"champion": "DrMundo", "items": [DAWNCORE], FLAT: True}
        base = S._route_sustain({**body, FLAT: False})["sustain_score"]
        flat = S._route_sustain(dict(body))["sustain_score"]
        scaled = S._route_sustain({**body, SEAM: True})["sustain_score"]
        self.assertGreater(flat - base, 0.0)
        self.assertAlmostEqual(
            (scaled - base) / (flat - base), 0.18 / 0.16, delta=0.005
        )


class EngineLevelSeam(unittest.TestCase):
    """The engine half, called directly - the route tests above go through
    ``_opt_bool``, which would mask a kwarg that never reached the helper."""

    @classmethod
    def setUpClass(cls):
        cls.snap = DataSnapshot.load()

    def test_compute_ehp_forwards_the_kwarg(self):
        kw = dict(
            item_ids=[DAWNCORE, STERAKS], mode="SR", assume_hsp_amp=True
        )
        flat = compute_ehp(self.snap, "Aatrox", 11, **kw)
        scaled = compute_ehp(
            self.snap, "Aatrox", 11, **kw, assume_scaling_hsp_grants=True
        )
        self.assertAlmostEqual(flat.shield_amp_mult, 1.16, places=6)
        self.assertAlmostEqual(scaled.shield_amp_mult, 1.18, places=6)

    def test_compute_sustain_forwards_the_kwarg(self):
        flat = compute_sustain("DrMundo", item_ids=[DAWNCORE], assume_hsp_amp=True)
        scaled = compute_sustain(
            "DrMundo",
            item_ids=[DAWNCORE],
            assume_hsp_amp=True,
            assume_scaling_hsp_grants=True,
        )
        self.assertGreater(scaled.sustain_score, flat.sustain_score)

    def test_sustain_movement_ratio_is_exact_before_rounding(self):
        # The unrounded twin of the route-level delta assertion. On the
        # dataclass the REGEN component scales linearly in hsp_mult, so the
        # ratio is exactly 0.18/0.16 with no transport rounding in the way.
        kw = dict(item_ids=[DAWNCORE])
        base = compute_sustain("DrMundo", **kw, assume_hsp_amp=False).sustain_score
        flat = compute_sustain("DrMundo", **kw, assume_hsp_amp=True).sustain_score
        scaled = compute_sustain(
            "DrMundo", **kw, assume_hsp_amp=True, assume_scaling_hsp_grants=True
        ).sustain_score
        self.assertGreater(flat - base, 0.0)
        self.assertAlmostEqual((scaled - base) / (flat - base), 0.18 / 0.16, places=6)

    def test_compute_sustain_seam_is_inert_without_items(self):
        # The transport gate at the engine level: no inventory, nothing to fold.
        off = compute_sustain("DrMundo", assume_hsp_amp=True)
        on = compute_sustain(
            "DrMundo", assume_hsp_amp=True, assume_scaling_hsp_grants=True
        )
        self.assertEqual(on.to_dict(), off.to_dict())


if __name__ == "__main__":
    unittest.main()
