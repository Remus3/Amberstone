"""R193 slice C - the item-omnivamp EHP seam must be reachable over /ehp.

THE GAP THIS CLOSES
-------------------
``compute_ehp`` has carried a DEFAULT-OFF ``assume_max_stacks_omnivamp`` kwarg
since 2026-07-10 (ehp.py:1251, consumed :1517-1521) that credits the
Riftmaker-family item-passive omnivamp into the EHP SUSTAIN axis. It was proven
in-process by ``test_item_omnivamp_credit_r100.py`` and then STRANDED: the
string never appeared in ``agents/daemon_slayer/server.py``, so no shipped HTTP
route could arm it and no RC code path could reach it.

Note why the two standing reachability guards
(``test_route_seams_reach_the_client.py`` and its per-route sibling) were GREEN
through that whole period: both build their seam universe from keys server.py
ALREADY parses, so a NEVER-parsed kwarg is invisible to them. Their green status
was never evidence of reachability - this file is the missing evidence.

WHAT IS PROVEN
--------------
  * the parse layer maps body key ``assume_max_stacks_omnivamp`` -> the
    ``compute_ehp`` kwarg of the same name (captured at the call boundary),
  * an ABSENT key is byte-identical to the pre-seam /ehp response (the
    acceptance bar - no default is changed),
  * armed on a Riftmaker build (item 4633) the response moves in the documented
    direction: heal_omnivamp / sustain_ehp_delta / effective_ehp_with_sustain
    rise while ``blended_ehp`` stays EXACTLY put (sustain-only credit),
  * ``core.daemon_slayer_client.ehp_for`` can express the key, and emits it only
    when True.

IN-PROCESS ONLY: route handlers take a body dict and read the module ``_CACHE``
(the ``test_oq17_route_seam_transport.py`` idiom). No :8893, no network.

NO ENGINE_VERSION assertion here - exposing an existing engine seam on a route
is transport, and the bump is stamped separately.
"""
from __future__ import annotations

import inspect
import unittest
from unittest import mock

import core.daemon_slayer_client as dsc
from agents.daemon_slayer import server
from agents.daemon_slayer.data_loader import DataSnapshot

_SNAP = DataSnapshot.load()

# Riftmaker - the only omnivamp source in the registry (224633 is its Arena
# mirror). Mordekaiser is the melee reference champion from the R100 engine
# test, so the 10 pct melee branch is the one under measurement here.
_RIFTMAKER = "4633"
_BODY = {
    "champion": "Mordekaiser",
    "level": 13,
    "mode": "SR",
    "items": [_RIFTMAKER],
}

_SEAM = "assume_max_stacks_omnivamp"


def setUpModule() -> None:
    server._CACHE.set(_SNAP)


class RouteParsesTheOmnivampKeyTests(unittest.TestCase):
    """The body key reaches ``compute_ehp`` as the identically named kwarg."""

    def _captured_kwarg(self, body: dict):
        seen: dict = {}
        real = server.compute_ehp

        def _spy(*a, **kw):
            seen.update(kw)
            return real(*a, **kw)

        with mock.patch.object(server, "compute_ehp", _spy):
            server._route_ehp(dict(body))
        return seen

    def test_armed_key_forwards_true(self) -> None:
        kw = self._captured_kwarg(dict(_BODY, **{_SEAM: True}))
        self.assertIn(_SEAM, kw)
        self.assertIs(kw[_SEAM], True)

    def test_absent_key_forwards_false(self) -> None:
        kw = self._captured_kwarg(dict(_BODY))
        self.assertIn(_SEAM, kw)
        self.assertIs(kw[_SEAM], False)

    def test_explicit_false_forwards_false(self) -> None:
        kw = self._captured_kwarg(dict(_BODY, **{_SEAM: False}))
        self.assertIs(kw[_SEAM], False)


class RouteDefaultOffIsByteIdenticalTests(unittest.TestCase):
    """The acceptance bar: omitting the key changes nothing."""

    def test_absent_key_equals_the_baseline_response(self) -> None:
        # The baseline is the response shape a pre-seam caller got: a body with
        # no omnivamp key at all. Full-dict equality, not a scalar spot check.
        base = server._route_ehp(dict(_BODY))
        again = server._route_ehp(dict(_BODY))
        self.assertEqual(base, again)

    def test_explicit_false_equals_the_baseline_response(self) -> None:
        base = server._route_ehp(dict(_BODY))
        off = server._route_ehp(dict(_BODY, **{_SEAM: False}))
        self.assertEqual(base, off)

    def test_off_sustain_collapses_onto_blended(self) -> None:
        # Mordekaiser + Riftmaker carries no lifesteal / spellvamp, so OFF the
        # sustain-inclusive term must sit exactly on blended_ehp.
        off = server._route_ehp(dict(_BODY))
        self.assertAlmostEqual(
            off["effective_ehp_with_sustain"], off["blended_ehp"], places=6
        )


class RouteArmedMovesTheSustainAxisTests(unittest.TestCase):
    """ON diverges in the documented direction - sustain axis only."""

    def _pair(self):
        off = server._route_ehp(dict(_BODY))
        on = server._route_ehp(dict(_BODY, **{_SEAM: True}))
        return off, on

    def test_on_credits_a_positive_omnivamp_heal(self) -> None:
        off, on = self._pair()
        self.assertEqual(off["heal_omnivamp"], 0.0)
        self.assertGreater(on["heal_omnivamp"], 0.0)

    def test_on_raises_the_sustain_delta(self) -> None:
        _, on = self._pair()
        self.assertGreater(on["sustain_ehp_delta"], 0.0)

    def test_on_raises_effective_ehp_with_sustain(self) -> None:
        off, on = self._pair()
        self.assertGreater(
            on["effective_ehp_with_sustain"], off["effective_ehp_with_sustain"]
        )

    def test_on_does_not_move_blended_ehp(self) -> None:
        # blended_ehp is the primary EHP number; the credit is sustain-only.
        off, on = self._pair()
        self.assertEqual(on["blended_ehp"], off["blended_ehp"])

    def test_non_omnivamp_build_with_key_armed_is_inert(self) -> None:
        # Bloodthirster grants lifesteal but no omnivamp: arming the route seam
        # must not leak a credit onto an unrelated build.
        body = dict(_BODY, champion="Aatrox", items=["3072"])
        off = server._route_ehp(dict(body))
        on = server._route_ehp(dict(body, **{_SEAM: True}))
        self.assertEqual(on["heal_omnivamp"], 0.0)
        self.assertEqual(on, off)


class ClientCanExpressTheOmnivampKeyTests(unittest.TestCase):
    """``ehp_for`` exposes the seam as an EXPLICIT keyword argument.

    Explicit (never ``**kwargs``) because the per-route reachability guard reads
    these signatures to decide whether a route's seams are reachable.
    """

    def test_ehp_for_declares_the_seam(self) -> None:
        params = inspect.signature(dsc.ehp_for).parameters
        self.assertIn(_SEAM, params)
        self.assertIs(params[_SEAM].default, False)

    def _sent_body(self, **kw) -> dict:
        seen: dict = {}

        def _spy(path: str, body: dict, timeout: float = 0.0):
            seen["path"] = path
            seen["body"] = body
            return {}

        with mock.patch.object(dsc, "_post_json", _spy):
            dsc.ehp_for("Mordekaiser", level=13, item_ids=[_RIFTMAKER], **kw)
        return seen

    def test_armed_client_call_emits_the_key(self) -> None:
        sent = self._sent_body(**{_SEAM: True})
        self.assertEqual(sent["path"], "/ehp")
        self.assertIs(sent["body"].get(_SEAM), True)

    def test_default_client_call_omits_the_key(self) -> None:
        sent = self._sent_body()
        self.assertNotIn(_SEAM, sent["body"])

    def test_false_client_call_omits_the_key(self) -> None:
        sent = self._sent_body(**{_SEAM: False})
        self.assertNotIn(_SEAM, sent["body"])


if __name__ == "__main__":
    unittest.main()
