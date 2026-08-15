"""RM-201: the ``apply_cc_floor`` CC-floor seam reaches ``/ehp``.

THE DEFECT
----------
``cc_pressure.compute_cc_pressure`` has shipped ``apply_cc_floor: bool = False``
since ENGINE 1.150.0 (cc_pressure.py:237). It has FIVE production callers and
NOT ONE forwards it:

  * ``ehp.compute_ehp``                              (ehp.py:2525)
  * ``core/cc_blended_ehp_context.py``               (:101)
  * ``core/cc_conditional_impact_context.py``        (:137)
  * ``core/enemy_cc_threat_context.py``              (:185)
  * ``dashboard/routes_cc_conditional_pressure.py``  (:207)

So the guaranteed-minimum CC band - the ``durations_floor_s`` half of the
conditional registry, seeded from Meraki for five champions - could not be armed
by any coach tick, any operator curl or any Python client. Same defect class
R197 fixed for ``assume_hsp_amp`` and RM-118 fixed for the survivability and
vamp lanes: engine complete, route wire simply never added.

This slice wires the ``compute_ehp`` caller only. The other four are coach-prompt
and dashboard consumers on their own routes and are out of scope.

STEP ZERO - REACHABILITY, PROVEN NOT ASSUMED
--------------------------------------------
The gap would be COSMETIC rather than live if ``ehp.py:2525`` were itself
unreachable from ``/ehp``. It is not, and the call path is opened in
``RouteReachabilityTests`` below rather than asserted in prose.

Two facts in the filed row are CORRECTED here, both measured:

  1. The ``/ehp`` body key for the enemy comp is ``enemies``, NOT
     ``enemy_champions``. ``_route_ehp`` reads ``enemies`` (server.py:661) and
     forwards it as ``enemy_champions=enemies`` (server.py:826). A body sent
     with the engine-side name is silently dropped.
  2. ``/ehp`` does not parse ``score_by`` AT ALL - that key belongs to
     ``/rank-tank`` and ``/rank-bruiser``. The ``ehp.py:2525`` call site runs on
     EVERY ``/ehp`` request carrying a non-empty ``enemies`` list; there is no
     ``score_by`` gate to satisfy. ``cc_blended_ehp`` is an unconditional field
     of the ``/ehp`` response, not a ranking mode.

THE THREE GATES (RM-118 durable)
--------------------------------
A seam has a FLAG, a TRANSPORT and an OWNER, and flag-only wiring ships
something settable, guard-green and arithmetically INERT. Here the transport is
TWO keys, not one:

  * ``enemies``            - without an enemy comp the whole cc block is skipped
                             and ``enemy_cc_pressure_s`` stays 0.0.
  * ``include_conditional`` - the floor lives on the CONDITIONAL registry, so
                             ``apply_cc_floor`` is arithmetically inert unless
                             the conditional axis is also on. Pinned by
                             ``test_floor_is_inert_without_the_conditional_axis``.

``_route_ehp`` already parsed both (server.py:661-662). The PYTHON CLIENT did
not: ``core/daemon_slayer_client.ehp_for`` carried ``enemies`` but had no
``include_conditional`` parameter anywhere in the module - measured, zero
occurrences of the name in the file before this slice. Adding ``apply_cc_floor``
to the client alone would therefore have shipped a client seam that is settable
and can never move a number, the exact reachable-and-dead failure mode RM-115
exists to kill. Both are added, and both halves are pinned below.

The reason that gap survived every existing guard is itself measured:
``test_route_seams_reach_the_client_per_route._SEAM_PREFIXES`` is
``("apply_", "assume_", "gate_", "exclude_")``, and ``include_conditional``
matches none of them, so the per-route client-reach guard never looked at it.

WHY ASHE AND NOT MAOKAI
-----------------------
The filed row proposed Maokai as the acceptance champion. MEASURED: Maokai does
NOT move, and cannot, so a Maokai-based acceptance would have "passed" by
asserting no change and shipped an inert wire.

Maokai R is a ``coexists_with_unconditional`` entry, so the consumer credits
MAX(unconditional, conditional) for the slot and never both. His unconditional R
tops out at 2.0s, while the conditional R (floor 0.75, max 2.25, p 0.4) is worth
0.9s OFF and 1.35s ON. Both are below 2.0, so the MAX rule picks the
unconditional value either way and the floor is dominated.

Ashe is the clean mover and the arithmetic is fully traceable because R is her
only registered CC slot:

    unconditional R (max rank)          1.5
    conditional R: floor 1.0, max 3.5, p 0.4, coexists=True
    OFF  cond = 3.5 * 0.4              = 1.4  -> MAX(1.5, 1.4) = 1.5
    ON   cond = 1.0 + 0.4 * (3.5-1.0)  = 2.0  -> MAX(1.5, 2.0) = 2.0

so ``total_cc_seconds`` moves 1.5 -> 2.0, a +0.5s / 33 percent move that
propagates to ``enemy_cc_pressure_s``, ``cc_pressure_fraction`` and
``cc_blended_ehp`` on the route response. All four floor movers are swept in
``FloorMovementTests`` so the choice of Ashe is not load-bearing.

DEFAULT-OFF
-----------
``apply_cc_floor`` defaults False on ``compute_cc_pressure`` AND on
``compute_ehp``, and the route key is optional, so a body omitting it is a
byte-identical response. This slice ships route EXPOSURE only; it flips no live
default and bumps no ENGINE_VERSION.

OFFLINE ONLY: no live :8860, no sockets. Direct handler + engine + client calls.
"""
from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path
from unittest import mock

import core.daemon_slayer_client as client_mod
from agents.daemon_slayer import server
from agents.daemon_slayer.cc_conditional import get_conditional_entries
from agents.daemon_slayer.cc_pressure import compute_cc_pressure
from agents.daemon_slayer.data_loader import DataSnapshot
from agents.daemon_slayer.ehp import compute_ehp, rank_items_by_ehp
from agents.daemon_slayer.tests.test_stranded_hsp_seam_r197 import (
    STRANDED_DEPTH1,
    _parsed_keys,
    _passed_kwargs,
    stranded_seams_depth1,
)

_SEAM = "apply_cc_floor"
_AXIS = "include_conditional"

_LEVEL = 13
# Probe hygiene (reference_ds_probe_empty_build_artifact): never an empty build.
_SUNFIRE, _WARMOGS = "3068", "3083"
_BUILD = (_SUNFIRE, _WARMOGS)
_CASTER = "Leona"

# The five champions whose conditional entries carry a durations_floor_s band.
_FLOOR_CHAMPS = ("Maokai", "Hecarim", "Ashe", "KSante", "Sion")
# Measured total_cc_seconds at include_conditional=True, mode SR: (OFF, ON).
_FLOOR_TOTALS = {
    "Ashe": (1.5, 2.0),
    "KSante": (1.775, 2.025),
    "Sion": (2.75, 2.875),
    "Hecarim": (1.75, 1.8),
}
# Dominated by the coexistence MAX rule - see the module docstring.
_DOMINATED = "Maokai"
_MOVER = "Ashe"
# Carries no conditional entry at all, so it is the off-registry control.
_OFF_REGISTRY = "Sett"

_SERVER_PY = Path(server.__file__)
_SERVER_SRC = _SERVER_PY.read_text(encoding="utf-8")

_SNAP = None


def _snap() -> DataSnapshot:
    global _SNAP
    if _SNAP is None:
        _SNAP = DataSnapshot.load()
    return _SNAP


def _body(enemies=(_MOVER,), **extra) -> dict:
    body = {
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


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        server._CACHE.set(_snap())


class RouteReachabilityTests(_Base):
    """STEP ZERO. The call path is opened, not scanned.

    A scan is not a reachability probe (feedback_scan_is_not_a_reachability_probe).
    If these fail, the seam gap is cosmetic and nothing below should have shipped.
    """

    def test_enemies_key_reaches_the_cc_pressure_call_site(self) -> None:
        armed = server._route_ehp(_body())
        bare = server._route_ehp(_body(enemies=()))
        self.assertGreater(
            armed["enemy_cc_pressure_s"], 0.0,
            "ehp.py:2525 did not run - the /ehp cc block is unreachable and this "
            "whole slice is moot",
        )
        self.assertEqual(bare["enemy_cc_pressure_s"], 0.0)
        self.assertLess(armed["cc_blended_ehp"], bare["cc_blended_ehp"])

    def test_route_reads_enemies_not_enemy_champions(self) -> None:
        """Row correction 1 - the engine-side name is silently dropped."""
        engine_name = server._route_ehp(
            _body(enemies=(), enemy_champions=[_MOVER])
        )
        self.assertEqual(
            engine_name["enemy_cc_pressure_s"], 0.0,
            "'enemy_champions' became a live /ehp key - the transport name in "
            "this file's tests needs re-deriving",
        )

    def test_route_has_no_score_by_gate(self) -> None:
        """Row correction 2 - score_by is a ranker key, inert on /ehp."""
        self.assertNotIn("score_by", _seam_keys_of("_route_ehp"))
        self.assertEqual(
            _wire(server._route_ehp(_body(score_by="cc_blended"))),
            _wire(server._route_ehp(_body())),
            "/ehp grew a score_by gate - the reachability claim above needs "
            "re-deriving against it",
        )


def _seam_keys_of(handler: str) -> set[str]:
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


class RouteTableTests(unittest.TestCase):
    """The per-seam route table, MEASURED off inspect.signature.

    Never inherited from a docstring - a sibling slice's docstring was wrong
    twice in OPPOSITE directions in a single run
    (reference_ds_route_seam_transport_vs_flag).
    """

    def test_measured_owner_set_is_exactly_compute_ehp(self) -> None:
        owners = {
            fn.__name__
            for fn in (compute_ehp, rank_items_by_ehp)
            if _SEAM in inspect.signature(fn).parameters
        }
        self.assertEqual(
            owners, {"compute_ehp"},
            "the EHP-family owner set for apply_cc_floor moved. /ehp is the "
            "whole route table for this seam; if rank_items_by_ehp grew it, "
            "_route_rank_tank must grow the key in the SAME slice",
        )

    def test_ranker_route_must_not_grow_the_key(self) -> None:
        """The scope pin. A key no handler forwards dies on the wire."""
        self.assertNotIn(_SEAM, _seam_keys_of("_route_rank_tank"))
        self.assertNotIn(_SEAM, _seam_keys_of("_route_rank_bruiser"))
        self.assertNotIn(_SEAM, _seam_keys_of("_route_hybrid"))

    def test_ehp_route_owns_it(self) -> None:
        self.assertIn(_SEAM, _seam_keys_of("_route_ehp"))
        self.assertIn(_AXIS, _seam_keys_of("_route_ehp"))


class EngineSeamTests(unittest.TestCase):
    """Gate 1 - the engine half ships DEFAULT-OFF on every entry point."""

    def test_default_off_on_both_owners(self) -> None:
        for fn in (compute_cc_pressure, compute_ehp):
            with self.subTest(fn=fn.__name__):
                p = inspect.signature(fn).parameters
                self.assertIn(_SEAM, p)
                self.assertIs(
                    p[_SEAM].default, False,
                    "a True default would move every shipped EHP number at once "
                    "- this slice ships route EXPOSURE, not a default flip",
                )

    def test_seam_is_keyword_only_on_compute_ehp(self) -> None:
        """Appended at END, keyword-only - a positional slot would break every
        existing call site (the Python-conventions rule in CLAUDE.md)."""
        p = inspect.signature(compute_ehp).parameters[_SEAM]
        self.assertIs(p.kind, inspect.Parameter.KEYWORD_ONLY)


class ByteIdentityTests(_Base):
    """Gate 2 - DEFAULT-OFF means an omitted key changes nothing."""

    def test_omitted_key_is_byte_identical(self) -> None:
        with_off = server._route_ehp(_body(**{_AXIS: True, _SEAM: False}))
        omitted = server._route_ehp(_body(**{_AXIS: True}))
        self.assertEqual(_wire(with_off), _wire(omitted))

    def test_armed_transport_flag_off_is_byte_identical(self) -> None:
        """ARMED-TRANSPORT / FLAG-OFF. Fails loudly if a transport is removed.

        The transport is asserted to be genuinely ARMED first, so this cannot
        pass vacuously on a body whose cc block never ran - which is exactly
        what makes a future removal of the ``enemies`` or ``include_conditional``
        parse fail here rather than silently.
        """
        armed = _body(**{_AXIS: True})
        baseline = server._route_ehp(dict(armed))
        self.assertGreater(
            baseline["enemy_cc_pressure_s"], 0.0,
            "transport is not armed - this byte-identity assertion would be "
            "vacuous, so the ON-path proof below is unguarded",
        )
        self.assertEqual(
            _wire(server._route_ehp(dict(armed, **{_SEAM: False}))),
            _wire(baseline),
        )

    def test_floor_is_inert_without_the_conditional_axis(self) -> None:
        """The AND-gate. The floor lives on the CONDITIONAL registry only."""
        for champ in _FLOOR_CHAMPS:
            with self.subTest(champ=champ):
                self.assertEqual(
                    _wire(server._route_ehp(_body(enemies=(champ,), **{_SEAM: True}))),
                    _wire(server._route_ehp(_body(enemies=(champ,)))),
                    "apply_cc_floor moved a number with include_conditional OFF "
                    "- the seam leaked onto the unconditional axis",
                )

    def test_off_registry_champion_is_invariant(self) -> None:
        """Negative control - a champion with no floor band cannot move."""
        armed = _body(enemies=(_OFF_REGISTRY,), **{_AXIS: True})
        self.assertEqual(
            _wire(server._route_ehp(dict(armed, **{_SEAM: True}))),
            _wire(server._route_ehp(dict(armed))),
        )


class FloorMovementTests(_Base):
    """Gate 3 - ON actually MOVES A NUMBER. The row's own acceptance."""

    def test_engine_totals_match_the_measured_table(self) -> None:
        for champ, (off, on) in _FLOOR_TOTALS.items():
            with self.subTest(champ=champ):
                got_off = compute_cc_pressure(
                    champ, "SR", include_conditional=True, apply_cc_floor=False
                ).total_cc_seconds
                got_on = compute_cc_pressure(
                    champ, "SR", include_conditional=True, apply_cc_floor=True
                ).total_cc_seconds
                self.assertAlmostEqual(got_off, off, places=6)
                self.assertAlmostEqual(got_on, on, places=6)
                self.assertGreater(got_on, got_off)

    def test_route_moves_total_cc_seconds_for_the_mover(self) -> None:
        """THE acceptance: POST /ehp with the seam ON moves the CC number."""
        armed = _body(enemies=(_MOVER,), **{_AXIS: True})
        off = server._route_ehp(dict(armed))
        on = server._route_ehp(dict(armed, **{_SEAM: True}))
        self.assertAlmostEqual(off["enemy_cc_pressure_s"], 1.5, places=6)
        self.assertAlmostEqual(on["enemy_cc_pressure_s"], 2.0, places=6)
        # and the discount it drives propagates to the EHP number
        self.assertGreater(on["cc_pressure_fraction"], off["cc_pressure_fraction"])
        self.assertLess(on["cc_blended_ehp"], off["cc_blended_ehp"])

    def test_every_floor_mover_moves_through_the_route(self) -> None:
        """The choice of Ashe is not load-bearing."""
        for champ in _FLOOR_TOTALS:
            with self.subTest(champ=champ):
                armed = _body(enemies=(champ,), **{_AXIS: True})
                off = server._route_ehp(dict(armed))
                on = server._route_ehp(dict(armed, **{_SEAM: True}))
                self.assertGreater(
                    on["enemy_cc_pressure_s"], off["enemy_cc_pressure_s"]
                )

    def test_maokai_is_dominated_by_the_coexistence_max_rule(self) -> None:
        """Pins WHY the filed row's proposed champion was rejected.

        Not a curiosity - a Maokai-based acceptance would assert no change and
        pass over a completely unwired seam.
        """
        entry = next(
            e for e in get_conditional_entries(_DOMINATED) if e.spell == "R"
        )
        self.assertIsNotNone(entry.durations_floor_s)
        self.assertTrue(entry.coexists_with_unconditional)
        cond_on = entry.durations_floor_s + entry.probability * (
            entry.durations_s[-1] - entry.durations_floor_s
        )
        from agents.daemon_slayer.ability_dps import _PER_SPELL_CC_DURATIONS
        uncond = _PER_SPELL_CC_DURATIONS[_DOMINATED]["R"][-1]
        self.assertGreater(
            uncond, cond_on,
            "Maokai's unconditional R no longer dominates his floored "
            "conditional R - he may now be a valid acceptance champion",
        )
        armed = _body(enemies=(_DOMINATED,), **{_AXIS: True})
        self.assertEqual(
            _wire(server._route_ehp(dict(armed, **{_SEAM: True}))),
            _wire(server._route_ehp(dict(armed))),
        )


class ClientReachTests(unittest.TestCase):
    """Gate 3 on the client - BOTH halves, or the seam is reachable-and-dead."""

    def _sent(self, **kwargs) -> dict:
        with mock.patch.object(client_mod, "_post_json", return_value={}) as p:
            client_mod.ehp_for(
                _CASTER, level=_LEVEL, item_ids=list(_BUILD), **kwargs
            )
        self.assertTrue(p.called)
        return p.call_args[0][1]

    def test_client_can_express_both_the_flag_and_its_axis(self) -> None:
        params = inspect.signature(client_mod.ehp_for).parameters
        for name in (_SEAM, _AXIS, "enemies"):
            with self.subTest(param=name):
                self.assertIn(
                    name, params,
                    "ehp_for cannot express this - arming apply_cc_floor without "
                    "include_conditional is a settable seam that can never move "
                    "a number (RM-115 reachable-and-dead)",
                )

    def test_both_are_emit_when_true(self) -> None:
        body = self._sent(enemies=[_MOVER], **{_AXIS: True, _SEAM: True})
        self.assertIs(body[_SEAM], True)
        self.assertIs(body[_AXIS], True)
        self.assertEqual(body["enemies"], [_MOVER])

    def test_omitted_client_call_is_byte_identical_on_the_wire(self) -> None:
        self.assertEqual(
            _wire(self._sent()),
            _wire(self._sent(**{_AXIS: False, _SEAM: False})),
        )
        self.assertNotIn(_SEAM, self._sent())
        self.assertNotIn(_AXIS, self._sent())

    def test_client_body_survives_the_route(self) -> None:
        """End to end: the body the client builds is one the route honours."""
        server._CACHE.set(_snap())
        armed = self._sent(enemies=[_MOVER], **{_AXIS: True, _SEAM: True})
        plain = self._sent(enemies=[_MOVER], **{_AXIS: True})
        self.assertGreater(
            server._route_ehp(armed)["enemy_cc_pressure_s"],
            server._route_ehp(plain)["enemy_cc_pressure_s"],
        )


class StrandedLedgerTests(unittest.TestCase):
    """The depth-1 guard's ledger shrinks by exactly this one name."""

    def test_seam_is_parsed_and_passed_by_server(self) -> None:
        self.assertIn(_SEAM, _parsed_keys(_SERVER_SRC))
        self.assertIn(
            _SEAM, _passed_kwargs(_SERVER_SRC),
            "parsed but never forwarded - R194 recorded exactly this PARSE-side "
            "drop, which makes a live seam read as inert",
        )

    def test_seam_left_the_depth1_debt_ledger(self) -> None:
        self.assertNotIn(_SEAM, STRANDED_DEPTH1)
        self.assertNotIn(_SEAM, stranded_seams_depth1(_SERVER_SRC))

    def test_the_sibling_row_is_untouched(self) -> None:
        """RM-200 owns assume_scaling_hsp_grants - this slice must not move it."""
        self.assertIn("assume_scaling_hsp_grants", STRANDED_DEPTH1)


if __name__ == "__main__":
    unittest.main()
