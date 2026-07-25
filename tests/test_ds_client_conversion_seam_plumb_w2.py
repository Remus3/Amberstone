"""BUILD SLICE W2 - make the two champion-selective conversion seams
REACHABLE from the client dispatcher.

Measured defect (this session, on HEAD c01e8f80):

  * ``apply_crit_conversion`` (Ashe Frost Shot, registry
    ``agents/daemon_slayer/_crit_conversion_overrides.py``) is PARSED by the
    server (``agents/daemon_slayer/server.py:488``) and ACCEPTED by the engine
    (``agents/daemon_slayer/rank.py:921``).
  * ``kit_conversion_strength`` (RM-86 L1 lever, registry
    ``agents/daemon_slayer/kit_conversion.py:106``) is likewise parsed
    (``server.py:481``) and accepted (``rank.py:918``).
  * ``core/daemon_slayer_client.py`` had ZERO occurrences of either name, so
    neither ``rank_for`` nor ``rank_for_primary_archetype`` could emit the body
    key. Every live coach tick and every generated build table therefore ran
    both seams at the engine default, i.e. the Ashe + Quinn fixes shipped
    2026-07-25 were inert in every shipped artifact.

This is the same failure mode as memory ``reference_ds_kit_conversion_not_
route_exposed`` one layer further down the stack: the seam measures correct
in-process and is inert on the wire.

Verified against source BEFORE writing (file:line cited above plus):
  - Both keys live ONLY on POST /rank (the carry / ds.dps route). ``grep -n
    'apply_crit_conversion|kit_conversion_strength' agents/daemon_slayer/*.py``
    returns server.py 481/488/511/512 and rank.py 918/921/1112/1228/1304/1322
    and nothing on any /rank-<archetype> route.
  - ``core/daemon_slayer_client.py`` has exactly ONE ``rank_for(`` call site
    (line 1840, the carry + kit-less-fallback chokepoint of
    ``rank_for_primary_archetype``), so one forward covers the dispatcher.
  - Engine gate asymmetry (do NOT assume symmetry):
      ``apply_crit_conversion`` is a BOOL defaulting False (server.py:488
      ``_opt_bool(..., False)``), so omit == False.
      ``kit_conversion_strength`` is a FLOAT defaulting 0.0 (server.py:481
      ``_opt_float(..., 0.0)``) and rank.py:1303-1305 consults the registry
      ONLY when ``kit_conversion_strength > 0.0`` - so omit == 0.0 == any
      non-positive value, and the client emits the key only when > 0.0.
  - ``registry_champion_ids()`` (kit_conversion.py:269) and ``_CRIT_CONVERSION``
    (_crit_conversion_overrides.py:95) are read AT RUNTIME here so control
    champions can never silently decay into the registry (the premise-decay
    trap that killed a hardcoded Quinn negative control last session).
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

import core.daemon_slayer_client as dsc


# --- fixtures -------------------------------------------------------------

def _rank_payload() -> dict:
    """Minimal well-formed POST /rank response (see RankedItem.from_dict)."""
    return {
        "ranked": [
            {"item_id": "3031", "item_name": "Infinity Edge",
             "delta_dps": 120.0, "gold": 3300},
            {"item_id": "3153", "item_name": "Blade of the Ruined King",
             "delta_dps": 90.0, "gold": 3200},
        ]
    }


class _Spy:
    """Records every body dict reaching the request layer (_post_json)."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []
        self.paths: list[str] = []

    def __call__(self, path, body, timeout=None):  # noqa: D102 - stub
        self.paths.append(path)
        self.bodies.append(json.loads(json.dumps(body)))
        return _rank_payload()

    @property
    def last(self) -> dict:
        return self.bodies[-1]

    def seam(self, key: str):
        """ABSENT sentinel or the value actually sent - used by the report."""
        return self.last.get(key, "ABSENT")


_BASE = dict(
    level=16,
    item_ids=["3153", "3047"],
    mode="SR",
    target_armor=110.0,
    target_mr=52.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
    top=8,
)

_CRIT_KEY = "apply_crit_conversion"
_KIT_KEY = "kit_conversion_strength"


# ===========================================================================
# Request-layer plumbing - core.daemon_slayer_client.rank_for
# ===========================================================================
class RankForConversionSeamBodyTests(unittest.TestCase):

    def _call(self, **kw) -> _Spy:
        spy = _Spy()
        with mock.patch.object(dsc, "_post_json", spy):
            rows = dsc.rank_for("Ashe", **{**_BASE, **kw})
        self.assertIsNotNone(rows)
        self.assertEqual(spy.paths, ["/rank"])
        return spy

    def test_default_body_is_byte_identical_and_carries_neither_key(self):
        """NO-OP PIN: the pre-plumb request payload, exactly."""
        spy = self._call()
        self.assertEqual(spy.last, {
            "champion": "Ashe",
            "level": 16,
            "items": ["3153", "3047"],
            "mode": "SR",
            "target_armor": 110.0,
            "target_mr": 52.0,
            "target_max_hp": 2500.0,
            "target_bonus_hp": 1200.0,
            "top": 8,
            "sort": "delta",
            "filter_shared_uniques": True,
        })

    def test_apply_crit_conversion_true_emits_the_body_key(self):
        spy = self._call(apply_crit_conversion=True)
        self.assertIs(spy.last.get(_CRIT_KEY), True)

    def test_apply_crit_conversion_false_omits_the_body_key(self):
        """False IS the engine default, so it must stay ABSENT - a client
        echoing its whole state back may not change the request."""
        spy = self._call(apply_crit_conversion=False)
        self.assertNotIn(_CRIT_KEY, spy.last)

    def test_kit_conversion_strength_positive_emits_a_float(self):
        spy = self._call(kit_conversion_strength=1.0)
        self.assertEqual(spy.last.get(_KIT_KEY), 1.0)
        self.assertIsInstance(spy.last.get(_KIT_KEY), float)

    def test_kit_conversion_strength_non_positive_omits_the_body_key(self):
        """rank.py:1303-1305 gates on ``> 0.0``; 0.0 and negatives are inert
        server-side, so the client must not send them at all."""
        for value in (0.0, -0.5):
            with self.subTest(value=value):
                spy = self._call(kit_conversion_strength=value)
                self.assertNotIn(_KIT_KEY, spy.last)

    def test_both_seams_together_round_trip(self):
        spy = self._call(apply_crit_conversion=True, kit_conversion_strength=0.6)
        self.assertIs(spy.last.get(_CRIT_KEY), True)
        self.assertEqual(spy.last.get(_KIT_KEY), 0.6)

    def test_seam_kwargs_are_keyword_only_and_appended_last(self):
        """Repo Python convention: a new param is appended at the END with a
        default, so no positional construction anywhere can shift."""
        import inspect

        params = list(inspect.signature(dsc.rank_for).parameters)
        self.assertEqual(params[-2:], [_KIT_KEY, _CRIT_KEY])
        sig = inspect.signature(dsc.rank_for)
        for key in (_KIT_KEY, _CRIT_KEY):
            self.assertIs(sig.parameters[key].kind,
                          inspect.Parameter.KEYWORD_ONLY)


# ===========================================================================
# Dispatcher plumbing - rank_for_primary_archetype (the SHIPPED client path)
# ===========================================================================
class DispatcherConversionSeamForwardingTests(unittest.TestCase):

    def _dispatch(self, champion="Ashe", archetype="carry", **kw) -> _Spy:
        spy = _Spy()
        with mock.patch.object(dsc, "_post_json", spy):
            res = dsc.rank_for_primary_archetype(
                champion, archetype, **{**_BASE, **kw})
        self.assertIsNotNone(res)
        return spy

    def test_dispatcher_forwards_apply_crit_conversion_to_the_carry_route(self):
        """THE DEFECT: before this slice no dispatcher argument could put
        this key on the wire, so the Ashe fix was unreachable live."""
        spy = self._dispatch(apply_crit_conversion=True)
        self.assertEqual(spy.paths[-1], "/rank")
        self.assertIs(spy.last.get(_CRIT_KEY), True)

    def test_dispatcher_forwards_kit_conversion_strength_to_the_carry_route(self):
        spy = self._dispatch(champion="Quinn", kit_conversion_strength=1.0)
        self.assertEqual(spy.paths[-1], "/rank")
        self.assertEqual(spy.last.get(_KIT_KEY), 1.0)

    def test_dispatcher_default_call_is_byte_identical_to_explicit_defaults(self):
        """NO-OP PIN at the dispatcher: omitting the kwargs and passing them
        at their engine defaults must serialize to the SAME bytes."""
        omitted = self._dispatch()
        explicit = self._dispatch(
            apply_crit_conversion=False, kit_conversion_strength=0.0)
        self.assertEqual(
            json.dumps(omitted.last, sort_keys=True),
            json.dumps(explicit.last, sort_keys=True),
        )
        self.assertNotIn(_CRIT_KEY, omitted.last)
        self.assertNotIn(_KIT_KEY, omitted.last)

    def test_non_carry_archetype_never_receives_the_carry_only_seams(self):
        """Both keys exist ONLY on POST /rank. A tank dispatch must not leak
        them onto /rank-tank (which would 400 or silently mislead)."""
        spy = _Spy()
        with mock.patch.object(dsc, "_post_json", spy):
            dsc.rank_for_primary_archetype(
                "Malphite", "tank",
                **{**_BASE, "apply_crit_conversion": True,
                   "kit_conversion_strength": 1.0})
        for body in spy.bodies:
            self.assertNotIn(_CRIT_KEY, body)
            self.assertNotIn(_KIT_KEY, body)


# ===========================================================================
# LIVE gate - :8893. Controls are DERIVED from the registries at runtime.
# ===========================================================================
def _registry_champions() -> set[str]:
    from agents.daemon_slayer._crit_conversion_overrides import _CRIT_CONVERSION
    from agents.daemon_slayer.kit_conversion import registry_champion_ids
    return set(_CRIT_CONVERSION) | set(registry_champion_ids())


_CONTROL_POOL = ("Jinx", "Caitlyn", "Ezreal", "Vayne", "Tristana", "Kaisa")

_LIVE_ARGS = dict(
    level=16,
    item_ids=["3153", "3047"],
    mode="SR",
    target_armor=110.0,
    target_mr=52.0,
    target_max_hp=2500.0,
    target_bonus_hp=1200.0,
    top=40,
)


def _signature(champion: str, **kw):
    res = dsc.rank_for_primary_archetype(champion, "carry", **{**_LIVE_ARGS, **kw})
    if res is None:
        return None
    return [(r["item_id"], round(float(r["delta"]), 6)) for r in res["ranked"]]


@unittest.skipUnless(dsc.is_engine_up(timeout=1.5), "DS engine :8893 is down")
class LiveConversionSeamReachabilityTests(unittest.TestCase):
    """Falsifiable acceptance criterion, measured through the CLIENT path."""

    def setUp(self) -> None:
        self.seeded = _registry_champions()
        self.controls = [c for c in _CONTROL_POOL if c not in self.seeded]
        self.assertGreaterEqual(
            len(self.controls), 3,
            "control pool decayed into the registries - repair the premise",
        )

    def test_crit_conversion_moves_ashe_and_no_control(self):
        base = _signature("Ashe")
        flagged = _signature("Ashe", apply_crit_conversion=True)
        self.assertIsNotNone(base)
        self.assertNotEqual(base, flagged, "Ashe unchanged - seam unreachable")
        for champ in self.controls[:3]:
            with self.subTest(champion=champ):
                self.assertEqual(
                    _signature(champ),
                    _signature(champ, apply_crit_conversion=True),
                    f"{champ} has no _CRIT_CONVERSION entry but moved",
                )

    def test_kit_conversion_strength_moves_quinn_and_no_control(self):
        seeded_carry = "Quinn"
        self.assertIn(seeded_carry, self.seeded)
        base = _signature(seeded_carry)
        flagged = _signature(seeded_carry, kit_conversion_strength=1.0)
        self.assertIsNotNone(base)
        self.assertNotEqual(base, flagged, "Quinn unchanged - seam unreachable")
        for champ in self.controls[:3]:
            with self.subTest(champion=champ):
                self.assertEqual(
                    _signature(champ),
                    _signature(champ, kit_conversion_strength=1.0),
                    f"{champ} has no _KIT_CONVERSION entry but moved",
                )

    def test_both_omitted_is_identical_to_explicit_engine_defaults(self):
        for champ in ["Ashe", "Quinn", *self.controls[:2]]:
            with self.subTest(champion=champ):
                self.assertEqual(
                    _signature(champ),
                    _signature(champ, apply_crit_conversion=False,
                               kit_conversion_strength=0.0),
                )


if __name__ == "__main__":
    unittest.main()
