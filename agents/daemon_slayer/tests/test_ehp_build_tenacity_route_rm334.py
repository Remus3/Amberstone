"""RM-334: the ``apply_build_tenacity`` seam reaches ``/ehp``.

THE DEFECT
----------
``ehp.compute_ehp`` has shipped ``apply_build_tenacity: bool = False`` since item
236 (ehp.py:1389) and consumes it at ehp.py:2582, where it reads
``total_item_tenacity(item_ids)`` - the RESOLVED build the caller already sent.
``/ehp`` exposes ``compute_ehp`` directly and has carried the ``enemies``
transport that makes tenacity bite since ENGINE 1.39.0, yet it is the ONE route
in the family that never parsed the flag.

The three routes that DO parse it, source-mapped off the AST rather than
inherited from prose, are ``_route_rank_tank`` (server.py:968),
``_route_hybrid`` (:1255) and ``_route_rank_bruiser`` (:1397). ``_route_ehp``
was absent from that list, so the seam was live on the rankers and
arithmetically INERT on the primitive they are built out of.

THE RECORDED "INTENT" IS A NOTE WHOSE MECHANISM IS REFUTED
----------------------------------------------------------
RM-334 carried a REFUTED IF clause: the row would die if ``/ehp`` were
deliberately the raw single-build primitive with tenacity deferred to the
rankers AND that intent were recorded somewhere. A note DOES exist - it is not
in ``_route_ehp``'s docstring (the row checked there and correctly found
nothing), it is in the PYTHON CLIENT, at ``core/daemon_slayer_client.ehp_for``:

    ``apply_build_tenacity`` is deliberately absent - ``_route_ehp`` does
    not parse it (it needs a resolved build, which /ehp does not rank over).

The clause does not fire, because the note's stated MECHANISM is measurably
backwards and the check is one line long. Build tenacity needs a RESOLVED build,
and ``/ehp`` is precisely the route that scores ONE resolved build: it forwards
its ``items`` list to ``compute_ehp(item_ids=...)``, which is the only input
``total_item_tenacity`` reads. The RANKERS are the endpoints that do not have a
single resolved build - they iterate a candidate item over a base build - and
that is why ``rank_items_by_ehp`` carries the flag as a TRI-STATE
``Optional[bool] = None`` (ehp.py:3204) resolved per scoring mode at :3431,
while ``compute_ehp`` carries a plain ``bool = False``.

So the note describes the defect rather than a decision. It is pinned in
``ClientNoteTests`` below so that the correction cannot silently rot back, and
the parse SHAPE difference it half-noticed is pinned in ``OwnerShapeTests``.

TWO PROBE TRAPS, BOTH MEASURED - EITHER ONE MAKES A TEST PASS VACUOUSLY
-----------------------------------------------------------------------
1. THE SCORING-AXIS TRAP. Tenacity moves the ``cc_blended`` axis ONLY. On the
   RANKERS that means ``score_by`` must be set to ``"cc_blended"``, because it
   defaults to ``"blended"`` and the flag looks inert under the default - a
   control run that way cost the filing pass a false "inert everywhere"
   reading. On ``/ehp`` the resolution is different and is asserted, not
   assumed: ``/ehp`` does not parse ``score_by`` AT ALL (it is a ranker key),
   and ``cc_blended_ehp`` is an unconditional field of the response. So this
   file asserts on ``cc_blended_ehp`` directly and pins the absence of the gate
   in ``ScoringAxisTests``.

2. THE SATURATION TRAP, AND A CORRECTION TO THE ROW. The row states that "at 3
   or more hard-CC enemies ``cc_pressure_fraction`` clamps to 1.0 and the flag
   stops moving the number". MEASURED here, that threshold is WRONG in the
   direction that would have weakened the test: at 3 hard-CC enemies the flag
   STILL moves, because only the OFF arm saturates.

       enemies                                   OFF        ON         moves
       ['Leona']                            6199.4814  6890.2807   yes
       ['Leona','Morgana']                  4251.0729  5402.4052   yes
       ['Leona','Morgana','Sion']           4251.0729  4286.4985   yes
       ['Leona','Morgana','Sion',
        'Amumu','Sett']                     4251.0729  4251.0729   NO

   The real rule is that the flag goes inert only once the ON arm is ALSO
   clamped, since ``cc_pressure_fraction`` is a MIN against 1.0 and tenacity
   only pushes the value DOWN. Saturating the OFF arm alone is not enough. The
   acceptance body sits at 2 enemies where both arms are informative, and the
   genuinely inert 5-enemy case is kept as the negative control in
   ``SaturationTrapTests`` rather than being described in prose.

DEFAULT-OFF
-----------
``apply_build_tenacity`` defaults False on ``compute_ehp`` and the new route key
is optional, so a body omitting it is a byte-identical response. That is not
asserted by comparing the route to itself - which would hold even if the route
had been broken in the same way twice - but against sha256 digests of the
canonical wire form captured at HEAD BEFORE this slice, in
``PreChangeByteIdentityTests``.

This slice ships route EXPOSURE only. It flips no live default and bumps no
ENGINE_VERSION.

OFFLINE ONLY: no live :8860, no sockets. Direct handler + engine calls.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import pathlib
import unittest

from agents.daemon_slayer import server
from agents.daemon_slayer._item_tenacity import total_item_tenacity
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp

_SEAM = "apply_build_tenacity"

_SERVER_PY = pathlib.Path(server.__file__)
_SERVER_SRC = _SERVER_PY.read_text(encoding="utf-8")

# The acceptance body, straight off the filed row.
_CASTER = "Braum"
_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
# 3111 is Mercury's Treads - the tenacity source that makes the seam bite.
_MERC_TREADS = "3111"
_BUILD = ("3068", "3075", "3143", _MERC_TREADS)
_ENEMIES = ("Leona", "Morgana")

# Measured at HEAD, in-process, before this slice.
_ACCEPTANCE_OFF = 4251.072939411764
_ACCEPTANCE_ON = 5402.405193835784

# enemies -> (cc_blended_ehp OFF, cc_blended_ehp ON). The saturation sweep.
_SWEEP: dict[tuple[str, ...], tuple[float, float]] = {
    ("Leona",): (6199.481370, 6890.280723),
    ("Leona", "Morgana"): (4251.072939, 5402.405194),
    ("Leona", "Morgana", "Sion"): (4251.072939, 4286.498547),
}
# BOTH arms clamped -> the only genuinely inert comp in the sweep.
_SATURATED = ("Leona", "Morgana", "Sion", "Amumu", "Sett")

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _body(enemies=_ENEMIES, **extra) -> dict:
    body: dict = {
        "champion": _CASTER,
        "level": _LEVEL,
        "items": list(_BUILD),
        "mode": "SR",
        "enemy_ad_share": 0.5,
        "enemy_ap_share": 0.5,
    }
    if enemies:
        body["enemies"] = list(enemies)
    body.update(extra)
    return body


def _wire(payload: dict) -> str:
    """Canonical serialization - byte-identity is asserted on this, not on ==."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _digest(payload: dict) -> str:
    return hashlib.sha256(_wire(payload).encode("utf-8")).hexdigest()


def _body_keys_of(handler: str) -> set[str]:
    """Every body key one ``_route_*`` handler reads, measured off the AST."""
    tree = ast.parse(_SERVER_SRC)
    fn = next(
        f for f in ast.walk(tree)
        if isinstance(f, ast.FunctionDef) and f.name == handler
    )
    keys: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name in ("_opt_bool", "_opt_float", "_opt_int", "_opt_str",
                        "_coerce_str_list", "_required_str", "get"):
                keys |= {
                    a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                }
    return keys


def _handlers_parsing(seam: str) -> set[str]:
    """Every ``_route_*`` handler in server.py that reads ``seam`` off the body.

    DERIVED, never listed. A hand-written roster is exactly how the filed row's
    own three-site map could have gone stale between the filing and this slice.
    """
    tree = ast.parse(_SERVER_SRC)
    found: set[str] = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("_route_"):
            continue
        if seam in _body_keys_of(fn.name):
            found.add(fn.name)
    return found


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class RouteReachabilityTests(_Base):
    """STEP ZERO. The call path is opened, not scanned.

    A scan is not a reachability probe (feedback_scan_is_not_a_reachability_probe).
    If these fail, the seam gap is cosmetic and nothing below should have shipped.
    """

    def test_enemies_transport_reaches_the_cc_block(self) -> None:
        armed = server._route_ehp(_body())
        bare = server._route_ehp(_body(enemies=()))
        self.assertGreater(
            armed["enemy_cc_pressure_s"], 0.0,
            "the /ehp cc block never ran - tenacity has nothing to shorten and "
            "this whole slice is moot",
        )
        self.assertEqual(bare["enemy_cc_pressure_s"], 0.0)

    def test_the_build_carries_a_real_tenacity_source(self) -> None:
        """Without Merc Treads the flag is a no-op and every arm below is vacuous."""
        self.assertGreater(
            total_item_tenacity(_BUILD), 0.0,
            "the acceptance build lost its tenacity item - the ON arm cannot "
            "differ from OFF and the acceptance passes by asserting nothing",
        )
        self.assertEqual(total_item_tenacity(tuple(
            i for i in _BUILD if i != _MERC_TREADS
        )), 0.0)

    def test_engine_owner_moves_the_number_for_this_body(self) -> None:
        """The engine half, proven independently of the route."""
        kw = dict(
            champion_id=_CASTER, level=_LEVEL, item_ids=list(_BUILD),
            mode="SR", enemy_champions=list(_ENEMIES),
        )
        off = compute_ehp(_snap(), **kw, apply_build_tenacity=False)
        on = compute_ehp(_snap(), **kw, apply_build_tenacity=True)
        self.assertAlmostEqual(off.cc_blended_ehp, _ACCEPTANCE_OFF, places=6)
        self.assertAlmostEqual(on.cc_blended_ehp, _ACCEPTANCE_ON, places=6)


class OwnerShapeTests(unittest.TestCase):
    """The route table and the PARSE SHAPE, MEASURED off inspect.signature.

    Never inherited from a docstring - a sibling slice's docstring was wrong
    twice in OPPOSITE directions in a single run
    (reference_ds_route_seam_transport_vs_flag).
    """

    def test_compute_ehp_accepts_a_plain_default_false_bool(self) -> None:
        p = inspect.signature(compute_ehp).parameters
        self.assertIn(_SEAM, p)
        self.assertIs(
            p[_SEAM].default, False,
            "a True default would move every shipped EHP number at once - this "
            "slice ships route EXPOSURE, not a default flip",
        )

    def test_ranker_owner_is_tri_state_and_that_is_why_the_shapes_differ(self) -> None:
        """Pins WHY _route_ehp must NOT copy the two tri-state ranker sites.

        ``rank_items_by_ehp`` resolves None per scoring mode (ehp.py:3431 - ON
        for cc_blended, OFF for blended), so its routes parse a tri-state.
        ``compute_ehp`` has no scoring mode to resolve against, so /ehp parses
        the plain default-False bool that _route_hybrid uses. Copying the
        tri-state here would hand a ``None`` to a ``bool``-annotated parameter.
        """
        self.assertIs(
            inspect.signature(rank_items_by_ehp).parameters[_SEAM].default, None
        )
        self.assertIsNot(
            inspect.signature(compute_ehp).parameters[_SEAM].default, None
        )


class ParseSiteTests(unittest.TestCase):
    """THE RED ASSERTION. Derived from the AST, never from a written roster."""

    def test_ehp_route_parses_the_seam(self) -> None:
        self.assertIn(
            _SEAM, _body_keys_of("_route_ehp"),
            "/ehp exposes compute_ehp directly and carries the enemies "
            "transport, but drops the flag - the seam is inert on the "
            "primitive while live on the three rankers built out of it",
        )

    def test_every_route_whose_owner_accepts_the_seam_now_parses_it(self) -> None:
        """The row's per-route acceptance, stated as the general property.

        RM-118's STRANDED_DEPTH1 guard asks only whether a seam is wired on SOME
        route, never whether it is wired on EVERY route whose compute owner
        accepts it. That is why this gap stayed invisible while the ledger read
        clean. This assertion asks the stronger question for this seam.
        """
        parsing = _handlers_parsing(_SEAM)
        self.assertTrue(
            parsing, "the derived parse-site set is EMPTY - the AST walk broke "
            "and every assertion keyed off it is vacuous"
        )
        expected = {
            "_route_ehp", "_route_rank_tank", "_route_hybrid",
            "_route_rank_bruiser",
        }
        self.assertEqual(
            parsing, expected,
            "the apply_build_tenacity route family moved. Every route whose "
            "compute owner accepts the seam must parse it, or be listed here "
            "with a written reason",
        )

    def test_seam_is_forwarded_not_merely_parsed(self) -> None:
        """Gate 2 of 3. A parsed-but-dropped key is a live seam that reads inert."""
        tree = ast.parse(_SERVER_SRC)
        fn = next(
            f for f in ast.walk(tree)
            if isinstance(f, ast.FunctionDef) and f.name == "_route_ehp"
        )
        forwarded = {
            kw.arg for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            for kw in node.keywords if kw.arg
        }
        self.assertIn(_SEAM, forwarded)


class ScoringAxisTests(_Base):
    """PROBE TRAP 1. /ehp has no score_by gate, so cc_blended_ehp is direct."""

    def test_route_has_no_score_by_gate(self) -> None:
        self.assertNotIn("score_by", _body_keys_of("_route_ehp"))
        self.assertEqual(
            _wire(server._route_ehp(_body(score_by="cc_blended"))),
            _wire(server._route_ehp(_body())),
            "/ehp grew a score_by gate - every assertion in this file reads "
            "cc_blended_ehp unconditionally and must be re-derived against it",
        )

    def test_the_blended_axis_is_untouched_by_the_seam(self) -> None:
        """Tenacity moves cc_blended ONLY. If plain blended_ehp moved too, the
        seam has leaked onto an axis it does not own."""
        off = server._route_ehp(_body(**{_SEAM: False}))
        on = server._route_ehp(_body(**{_SEAM: True}))
        self.assertEqual(off["blended_ehp"], on["blended_ehp"])
        self.assertNotEqual(off["cc_blended_ehp"], on["cc_blended_ehp"])


class AcceptanceTests(_Base):
    """THE ROW'S ACCEPTANCE, verbatim: a DIFFERENT cc_blended_ehp true vs false."""

    def test_acceptance_body_moves_cc_blended_ehp(self) -> None:
        off = server._route_ehp(_body(**{_SEAM: False}))
        on = server._route_ehp(_body(**{_SEAM: True}))
        self.assertNotEqual(off["cc_blended_ehp"], on["cc_blended_ehp"])
        self.assertAlmostEqual(off["cc_blended_ehp"], _ACCEPTANCE_OFF, places=6)
        self.assertAlmostEqual(on["cc_blended_ehp"], _ACCEPTANCE_ON, places=6)

    def test_route_now_matches_its_own_compute_owner(self) -> None:
        """The defect stated as an equality: the route must not lose the flag."""
        kw = dict(
            champion_id=_CASTER, level=_LEVEL, item_ids=list(_BUILD),
            mode="SR", enemy_champions=list(_ENEMIES),
        )
        for arm in (False, True):
            with self.subTest(apply_build_tenacity=arm):
                self.assertAlmostEqual(
                    server._route_ehp(_body(**{_SEAM: arm}))["cc_blended_ehp"],
                    compute_ehp(_snap(), **kw, apply_build_tenacity=arm)
                    .cc_blended_ehp,
                    places=9,
                )

    def test_tenacity_raises_ehp_and_lowers_pressure(self) -> None:
        """Direction, not just difference. Tenacity shortens the CC eaten."""
        off = server._route_ehp(_body(**{_SEAM: False}))
        on = server._route_ehp(_body(**{_SEAM: True}))
        self.assertGreater(on["cc_blended_ehp"], off["cc_blended_ehp"])
        self.assertLess(on["cc_pressure_fraction"], off["cc_pressure_fraction"])


class SaturationTrapTests(_Base):
    """PROBE TRAP 2, and the correction to the row's stated threshold."""

    def test_sweep_matches_the_measured_table(self) -> None:
        for enemies, (want_off, want_on) in _SWEEP.items():
            with self.subTest(enemies=enemies):
                off = server._route_ehp(_body(enemies=enemies, **{_SEAM: False}))
                on = server._route_ehp(_body(enemies=enemies, **{_SEAM: True}))
                self.assertAlmostEqual(off["cc_blended_ehp"], want_off, places=4)
                self.assertAlmostEqual(on["cc_blended_ehp"], want_on, places=4)
                self.assertGreater(on["cc_blended_ehp"], off["cc_blended_ehp"])

    def test_three_cc_enemies_still_move_the_number(self) -> None:
        """The row said 3+ is inert. It is not - only the OFF arm clamps there."""
        enemies = ("Leona", "Morgana", "Sion")
        off = server._route_ehp(_body(enemies=enemies, **{_SEAM: False}))
        on = server._route_ehp(_body(enemies=enemies, **{_SEAM: True}))
        self.assertEqual(off["cc_pressure_fraction"], 1.0)
        self.assertLess(on["cc_pressure_fraction"], 1.0)
        self.assertNotEqual(off["cc_blended_ehp"], on["cc_blended_ehp"])

    def test_both_arms_clamped_is_the_real_inert_case(self) -> None:
        """The negative control, and the MECHANISM of the inertness.

        MEASURED: the flag is inert on ``cc_blended_ehp`` here, but it is NOT
        inert on the response - ``enemy_cc_pressure_s`` still falls 11.90 ->
        8.33, because tenacity really does shorten the CC and it is
        ``cc_pressure_fraction``'s MIN-against-1.0 clamp that swallows the
        difference downstream. Asserting whole-response equality here would be
        WRONG, and asserting only cc_blended_ehp equality without the seconds
        would leave the clamp unproven - so both halves are pinned.
        """
        off = server._route_ehp(_body(enemies=_SATURATED, **{_SEAM: False}))
        on = server._route_ehp(_body(enemies=_SATURATED, **{_SEAM: True}))
        self.assertEqual(off["cc_pressure_fraction"], 1.0)
        self.assertEqual(
            on["cc_pressure_fraction"], 1.0,
            "the ON arm left saturation - this comp is no longer the inert "
            "control and the trap threshold needs re-deriving",
        )
        self.assertEqual(off["cc_blended_ehp"], on["cc_blended_ehp"])
        self.assertLess(
            on["enemy_cc_pressure_s"], off["enemy_cc_pressure_s"],
            "the raw CC seconds did NOT move, so this comp proves nothing "
            "about the clamp - the flag may simply be unwired",
        )


class PreChangeByteIdentityTests(_Base):
    """DEFAULT-OFF proven against HEAD, not against the route itself.

    Comparing the post-change route to the post-change route with the flag
    explicitly False would hold even if the slice had broken the default path
    in both arms at once. These digests were captured at HEAD BEFORE the route
    learned the key, so they cannot move with it.
    """

    _PRE_CHANGE = {
        "plain_no_enemies":
            "5b8f09999b0197459e7a845ae355e2e699698ef5c8c8bc1dc332beea7f9b6603",
        "acceptance_two_cc_enemies":
            "47918eff8eb891c29034745f408100becde2f1274566390563a426e2b52b1633",
        "seams_armed_aram":
            "78c95a77ea276502b4842f0eeb492fa7cb7659ea7606fc6c520006cebd94c1a4",
    }

    @staticmethod
    def _bodies() -> dict[str, dict]:
        return {
            "plain_no_enemies": _body(enemies=()),
            "acceptance_two_cc_enemies": _body(),
            "seams_armed_aram": {
                "champion": "Sion", "level": 16,
                "items": ["3068", "3083", "3143", "3075", "3047"],
                "mode": "ARAM", "enemy_ad_share": 0.6, "enemy_ap_share": 0.4,
                "enemies": ["Amumu"], "include_conditional": True,
                "rune_ids": ["8437"], "apply_mode_modifiers": True,
                "apply_champion_tenacity": True,
                "apply_passive_mitigation": True,
            },
        }

    def test_absent_key_reproduces_the_pre_change_bytes(self) -> None:
        for name, body in self._bodies().items():
            with self.subTest(body=name):
                self.assertEqual(
                    _digest(server._route_ehp(dict(body))),
                    self._PRE_CHANGE[name],
                    "the default /ehp path moved. RM-334 changes arithmetic "
                    "ONLY when apply_build_tenacity is sent true",
                )

    def test_explicit_false_equals_the_absent_key(self) -> None:
        for name, body in self._bodies().items():
            with self.subTest(body=name):
                self.assertEqual(
                    _digest(server._route_ehp(dict(body, **{_SEAM: False}))),
                    self._PRE_CHANGE[name],
                )

    def test_the_digests_are_not_all_the_same_string(self) -> None:
        """Non-vacuity: three identical digests would mean the bodies collapsed."""
        self.assertEqual(len(set(self._PRE_CHANGE.values())), 3)


class ClientNoteTests(unittest.TestCase):
    """The refuted note must not silently rot back into the client docstring."""

    @staticmethod
    def _ehp_for_doc() -> str:
        import core.daemon_slayer_client as client_mod
        tree = ast.parse(
            pathlib.Path(client_mod.__file__).read_text(encoding="utf-8")
        )
        fn = next(
            f for f in ast.walk(tree)
            if isinstance(f, ast.FunctionDef) and f.name == "ehp_for"
        )
        return ast.get_docstring(fn) or ""

    def test_the_refuted_note_carries_its_correction(self) -> None:
        """Pinned POSITIVELY, on the corrective anchor.

        The first draft of this guard banned the substring "deliberately
        absent" - which the corrected docstring necessarily QUOTES in order to
        say what it is correcting, so the guard failed against the very fix it
        was written to require. A ban on the false claim's words cannot tell
        "asserted" from "quoted and refuted"; the presence of the one-line
        refutation can.
        """
        doc = self._ehp_for_doc()
        self.assertTrue(doc, "ehp_for lost its docstring - this guard is vacuous")
        self.assertIn(_SEAM, doc)
        self.assertIn(
            "total_item_tenacity(item_ids)", doc,
            "ehp_for's docstring no longer carries the one-line refutation of "
            "the old 'no resolved build' claim. That claim is what kept the "
            "seam off /ehp; without the correction it can be re-derived and "
            "the wire removed again",
        )

    def test_client_can_express_the_seam_on_ehp(self) -> None:
        """Otherwise the seam is settable by curl and dead to every RC caller."""
        import core.daemon_slayer_client as client_mod
        self.assertIn(
            _SEAM, inspect.signature(client_mod.ehp_for).parameters,
            "ehp_for cannot express apply_build_tenacity - wiring the route "
            "alone ships the reachable-and-dead illusion RM-115 exists to kill",
        )


if __name__ == "__main__":
    unittest.main()
