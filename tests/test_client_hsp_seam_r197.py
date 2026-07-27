# tests/test_client_hsp_seam_r197.py
"""R197 client half: the wielder-HSP seam must be settable from RC code.

WHAT THIS PINS
--------------
``agents/daemon_slayer/server.py`` began parsing ``assume_hsp_amp`` on BOTH
/ehp (server.py:636) and /sustain (server.py:1761) at R197. The engine had
accepted the kwarg since ENGINE 1.171.0 (R60) on ``compute_ehp`` and
``compute_sustain``, but no route parsed it, so no client could arm it. Wiring
the routes moved the gap one layer out rather than closing it: /ehp's client
function did not declare the keyword, and /sustain had no client function at
all. Both DS-side reachability guards went RED on exactly that pair.

This file is the RC-side regression pin for the client half. The DS-dir guards
answer the GENERAL question by AST introspection ("is any route seam
unreachable"); this one answers the SPECIFIC one behaviourally, by capturing
the request body an actual call produces.

THE PROPERTY THAT MATTERS MOST HERE IS THE NEGATIVE ONE
-------------------------------------------------------
Every assertion about the flag being SENT is paired with one about it being
ABSENT. A seam that ships DEFAULT-OFF is only safe if a caller who does not
name it produces the identical request it produced before the seam existed - so
the omitted-key cases below are pinned against a full literal body, not just a
``not in`` check, which would pass even if the wiring corrupted a sibling key.

OFFLINE ONLY: ``_post_json`` is monkeypatched, so no socket is opened and the
engine at :8893 is never contacted. Nothing here starts a server.
"""
from __future__ import annotations

import inspect
import unittest

import core.daemon_slayer_client as dsc


class _CapturedTransport:
    """Stand-in for ``_post_json`` that records (path, body, timeout)."""

    def __init__(self, reply=None):
        self.calls: list[tuple[str, dict, float]] = []
        self.reply = reply

    def __call__(self, path: str, body: dict, timeout: float = 0.0):
        self.calls.append((path, dict(body), timeout))
        return self.reply

    @property
    def last(self) -> tuple[str, dict, float]:
        return self.calls[-1]


class _TransportPatchCase(unittest.TestCase):
    """Base that swaps the module-level transport out and restores it."""

    reply: object = None

    def setUp(self) -> None:
        self._real_post_json = dsc._post_json
        self.transport = _CapturedTransport(reply=self.reply)
        dsc._post_json = self.transport

    def tearDown(self) -> None:
        dsc._post_json = self._real_post_json


_EHP_BASE = {
    "champion": "Soraka",
    "level": 13,
    "item_ids": ["3107", "3222"],
}

# What ``ehp_for`` puts on the wire for the base call above with no seam named.
# Pinned as a literal so a regression that ADDS or MUTATES any key - not just
# one that leaks assume_hsp_amp - fails here.
_EHP_BASE_BODY = {
    "champion": "Soraka",
    "level": 13,
    "items": ["3107", "3222"],
    "mode": "SR",
    "enemy_ad_share": 0.5,
    "enemy_ap_share": 0.5,
}


class EhpForHspSeamTests(_TransportPatchCase):
    reply = {"ehp": 1.0}

    def test_seam_is_an_explicit_keyword_with_a_false_default(self) -> None:
        """Not ``**kwargs``: the DS reachability guards read this signature."""
        params = inspect.signature(dsc.ehp_for).parameters
        self.assertIn("assume_hsp_amp", params)
        param = params["assume_hsp_amp"]
        self.assertEqual(param.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(param.default, False)
        self.assertNotIn(
            inspect.Parameter.VAR_KEYWORD,
            [p.kind for p in params.values()],
            "ehp_for must not grow a **kwargs passthrough - it would make an "
            "unreachable seam look wired to the per-route guard",
        )

    def test_omitting_the_seam_sends_the_pre_r197_body_exactly(self) -> None:
        dsc.ehp_for(**_EHP_BASE)
        path, body, _timeout = self.transport.last
        self.assertEqual(path, "/ehp")
        self.assertEqual(body, _EHP_BASE_BODY)

    def test_explicit_false_still_omits_the_key(self) -> None:
        """DEFAULT-OFF is emit-when-True, so False must be indistinguishable."""
        dsc.ehp_for(**_EHP_BASE, assume_hsp_amp=False)
        _path, body, _timeout = self.transport.last
        self.assertEqual(body, _EHP_BASE_BODY)

    def test_true_sends_the_key(self) -> None:
        dsc.ehp_for(**_EHP_BASE, assume_hsp_amp=True)
        _path, body, _timeout = self.transport.last
        self.assertIs(body.get("assume_hsp_amp"), True)
        self.assertEqual(body, {**_EHP_BASE_BODY, "assume_hsp_amp": True})

    def test_the_seam_does_not_disturb_the_sibling_omnivamp_seam(self) -> None:
        """Both are DEFAULT-OFF sustain-adjacent bools - arming one must not
        arm the other, which a shared emit helper could silently do."""
        dsc.ehp_for(**_EHP_BASE, assume_hsp_amp=True)
        _path, hsp_only, _t = self.transport.last
        self.assertNotIn("assume_max_stacks_omnivamp", hsp_only)

        dsc.ehp_for(**_EHP_BASE, assume_max_stacks_omnivamp=True)
        _path, omni_only, _t = self.transport.last
        self.assertNotIn("assume_hsp_amp", omni_only)


class SustainForTests(_TransportPatchCase):
    reply = {"total_sustain_score": 1.0}

    def test_the_function_exists_and_posts_the_sustain_route(self) -> None:
        self.assertTrue(hasattr(dsc, "sustain_for"))
        dsc.sustain_for("Soraka")
        path, _body, _timeout = self.transport.last
        self.assertEqual(path, "/sustain")

    def test_signature_carries_the_seam_and_its_transport(self) -> None:
        """``assume_hsp_amp`` is inert without ``item_ids`` - the engine sums
        heal_shield_amp_pct over the inventory - so the pair ships together."""
        params = inspect.signature(dsc.sustain_for).parameters
        for name in ("item_ids", "assume_hsp_amp"):
            self.assertIn(name, params)
            self.assertEqual(params[name].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(params["assume_hsp_amp"].default, False)
        self.assertIsNone(params["item_ids"].default)

    def test_minimal_call_sends_only_champion_and_mode(self) -> None:
        dsc.sustain_for("Soraka")
        _path, body, _timeout = self.transport.last
        self.assertEqual(body, {"champion": "Soraka", "mode": "SR"})

    def test_explicit_false_and_empty_items_send_neither_key(self) -> None:
        dsc.sustain_for("Soraka", item_ids=[], assume_hsp_amp=False)
        _path, body, _timeout = self.transport.last
        self.assertEqual(body, {"champion": "Soraka", "mode": "SR"})

    def test_armed_call_sends_both_halves(self) -> None:
        dsc.sustain_for(
            "Soraka", mode="ARAM", item_ids=["3107", 3222], assume_hsp_amp=True,
        )
        _path, body, _timeout = self.transport.last
        self.assertEqual(body, {
            "champion": "Soraka",
            "mode": "ARAM",
            "items": ["3107", "3222"],
            "assume_hsp_amp": True,
        })

    def test_falsy_item_entries_are_dropped_like_every_sibling(self) -> None:
        dsc.sustain_for("Soraka", item_ids=["3107", "", None, "3222"])
        _path, body, _timeout = self.transport.last
        self.assertEqual(body["items"], ["3107", "3222"])

    def test_default_timeout_matches_the_module_contract(self) -> None:
        dsc.sustain_for("Soraka")
        _path, _body, timeout = self.transport.last
        self.assertEqual(timeout, dsc.DEFAULT_TIMEOUT)

    def test_engine_down_returns_none_rather_than_raising(self) -> None:
        """Same fail-soft contract as ehp_for - None means unreachable."""
        self.transport.reply = None
        self.assertIsNone(dsc.sustain_for("Soraka"))

    def test_result_dict_is_returned_raw(self) -> None:
        self.assertEqual(dsc.sustain_for("Soraka"), {"total_sustain_score": 1.0})


class SeamReachesBothParsingRoutesTests(unittest.TestCase):
    """The RC-side echo of the DS per-route guard, scoped to this one seam.

    Source-level rather than behavioural on purpose: it asserts that the two
    routes which PARSE ``assume_hsp_amp`` are each POSTed by a client function
    that can express it. The DS-dir guards prove this generally by AST; pinning
    it here means a revert of either half fails the RC suite too, which is the
    suite a non-DS session actually runs.
    """

    def test_both_parsing_routes_have_an_expressing_client_function(self) -> None:
        import agents.daemon_slayer.server as server_mod

        src = inspect.getsource(server_mod)
        self.assertIn('_opt_bool(body, "assume_hsp_amp"', src)

        for fn, path in ((dsc.ehp_for, "/ehp"), (dsc.sustain_for, "/sustain")):
            client_src = inspect.getsource(fn)
            self.assertIn(f'_post_json("{path}"', client_src)
            self.assertIn("assume_hsp_amp", inspect.signature(fn).parameters)
            self.assertIn('body["assume_hsp_amp"] = True', client_src)

    def test_the_engine_functions_behind_both_routes_accept_the_kwarg(self) -> None:
        """Guard against a wire with no engine on the far end."""
        from agents.daemon_slayer.ehp import compute_ehp
        from agents.daemon_slayer.sustain import compute_sustain

        for fn in (compute_ehp, compute_sustain):
            self.assertIn("assume_hsp_amp", inspect.signature(fn).parameters)


if __name__ == "__main__":
    unittest.main()
