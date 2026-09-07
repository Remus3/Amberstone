"""BUILD SLICE W2 - make the two champion-selective conversion seams
REACHABLE from the client dispatcher.

Measured defect (this session, on HEAD 3ab8c741):

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
import time
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
        default, so no positional construction anywhere can shift.

        RE-EXPRESSED at RM-115 (ENGINE 1.254.0), deliberately NOT weakened.
        The original form asserted ``params[-2:] == [_KIT_KEY, _CRIT_KEY]``,
        i.e. that these two seams are the FINAL two parameters. That is a
        stricter statement than the convention it cites, and it is false for
        any correct future append: RM-115 appended ``apply_mode_modifiers``
        and ``exclude_off_axis_items`` to ``rank_for`` exactly as the
        convention requires, and the assertion broke even though nothing it
        was protecting against had happened.

        What the convention actually protects is that no EXISTING positional
        construction can shift. The checks below assert that property
        directly, and are strictly STRONGER than the original: the original
        said nothing about defaults at all, and said nothing about the other
        23 parameters. Concretely:

          * only the three genuine inputs may lack a default, so every seam
            ever appended is optional and no call site breaks;
          * both W2 seams are KEYWORD_ONLY, so neither can be reached
            positionally in the first place;
          * both sit after ``timeout`` - i.e. after the entire pre-seam
            surface - which is the "appended at the end" half, expressed so
            that a later append is allowed to also sit after them;
          * their relative order is preserved.
        """
        import inspect

        sig = inspect.signature(dsc.rank_for)
        params = list(sig.parameters)

        required = [n for n, v in sig.parameters.items()
                    if v.default is inspect.Parameter.empty]
        self.assertEqual(
            required, ["champion", "level", "item_ids"],
            "a parameter without a default appeared in rank_for - that is "
            "the actual way a positional construction shifts, and it is what "
            "the append-last convention exists to prevent",
        )

        for key in (_KIT_KEY, _CRIT_KEY):
            self.assertIs(sig.parameters[key].kind,
                          inspect.Parameter.KEYWORD_ONLY)
            self.assertIsNot(sig.parameters[key].default,
                             inspect.Parameter.empty)
            self.assertGreater(
                params.index(key), params.index("timeout"),
                f"{key} moved ahead of the pre-seam parameter surface",
            )

        self.assertLess(params.index(_KIT_KEY), params.index(_CRIT_KEY))


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
# LIVE gate - :8860. Controls are DERIVED from the registries at runtime.
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


class EngineTransportError(RuntimeError):
    """A live call returned NO BODY at all - a swallowed HTTP timeout.

    Raised instead of returning None so a transport failure can never be
    mistaken for a ranking change (see _PatientTransport below).
    """


# --------------------------------------------------------------------------- #
# xdist root cause (MEASURED 2026-07-26 against the live :8860 engine).
#
# ``_post_json`` (``core/daemon_slayer_client.py:95-112``) maps EVERY transport
# failure to ``None``, and every caller up the stack reads ``None`` as "the
# engine had nothing to say" rather than "the engine never answered". That is
# the correct PRODUCTION shape - a live coach tick must fail fast rather than
# stall a frame - so neither fix below belongs in ``core/``. It is wrong for a
# test harness, because a hole then gets compared against a real ranking.
#
# TWO independent transport faults were measured, not one:
#
#   1. DEADLINE. ``core/daemon_slayer_client.py:33`` sets
#      ``DEFAULT_TIMEOUT = 0.5`` s. Solo POST /rank is 22 - 37 ms, but at
#      8-way concurrency the tail reaches 513 ms and 3 of 24 calls returned
#      None. Fixed here by forcing ``_LIVE_TIMEOUT`` on the live calls.
#
#   2. LISTEN BACKLOG. ``agents/daemon_slayer/server.py:2630`` builds a stdlib
#      ``ThreadingHTTPServer`` and never raises ``request_queue_size``, so the
#      socketserver default of 5 applies. When more than 5 connects are pending
#      the OS refuses the connection outright: MEASURED 3 of 500 sequential
#      POSTs failing with ``ConnectionRefusedError [WinError 10061]`` while a
#      12-way load ran, at a 30 s deadline - so NO timeout can fix this one.
#      Fixed here by retrying the CONNECT, which is a pure transport retry.
#
# Both faults produced exactly the observed SUBFAILED champion='Caitlyn': the
# control's BASE call failed while its FLAGGED call succeeded, so
# ``assertEqual`` compared a hole against a ranking and reported "Caitlyn has
# no _CRIT_CONVERSION entry but moved".
#
# What is NOT retried: any assertion. A retry here happens only when the
# response is ``None``, i.e. when no verdict exists yet. The engine is a pure
# function of the request body against a fixed snapshot, so a re-connected call
# returns the same ranking - the comparison is evaluated exactly once, on real
# data. If every attempt fails, the teardown hook below fails the test LOUDLY
# rather than letting the hole reach an assertion.
#
# Route, body, engine and every assertion are untouched.
# --------------------------------------------------------------------------- #
_REAL_POST_JSON = dsc._post_json

# Generous on purpose: the engine is contended by up to 8 xdist workers, and an
# over-long deadline only costs wall clock on a run that was going to fail.
_LIVE_TIMEOUT = 30.0
# 5 attempts x a backoff longer than the measured 1.9 s worst-case service time
# clears a transient backlog overflow; a genuinely dead engine still fails.
_TRANSPORT_ATTEMPTS = 5
_TRANSPORT_BACKOFF = 0.4


class _PatientTransport:
    """Force ``_LIVE_TIMEOUT`` on every live call and re-connect on a None.

    Records the requests that stayed None after every attempt so teardown can
    tell a transport artefact apart from engine behaviour.
    """

    def __init__(self) -> None:
        self.failures: list[tuple[str, dict]] = []
        self.reconnects = 0

    def __call__(self, path, body, timeout=None):
        for attempt in range(_TRANSPORT_ATTEMPTS):
            out = _REAL_POST_JSON(path, body, timeout=_LIVE_TIMEOUT)
            if out is not None:
                self.reconnects += attempt
                return out
            time.sleep(_TRANSPORT_BACKOFF * (attempt + 1))
        self.failures.append((path, dict(body)))
        return None


def _signature(champion: str, **kw):
    res = dsc.rank_for_primary_archetype(champion, "carry", **{**_LIVE_ARGS, **kw})
    if res is None:
        # NEVER return None here. A None signature silently satisfies
        # assertNotEqual and silently breaks assertEqual, so a dead socket
        # would be reported as a ranking change. Fail loudly instead.
        raise EngineTransportError(
            f"live POST /rank returned NO BODY for champion={champion!r} "
            f"kw={kw!r} (args={_LIVE_ARGS!r}) - this is a TRANSPORT failure at "
            f"core/daemon_slayer_client.py:107, not a ranking change"
        )
    return [(r["item_id"], round(float(r["delta"]), 6)) for r in res["ranked"]]


def _engine_is_up() -> bool:
    """Engine-up gate, retried for the SAME backlog-overflow reason as above.

    A single refused connect here would silently SKIP this whole class, which
    is worse than a failure: the seam evidence disappears with no signal. The
    load spike is real at collection time, when every xdist worker imports
    every test module at once.
    """
    for attempt in range(_TRANSPORT_ATTEMPTS):
        if dsc.is_engine_up(timeout=5.0):
            return True
        time.sleep(_TRANSPORT_BACKOFF * (attempt + 1))
    return False


class LiveConversionSeamReachabilityTests(unittest.TestCase):
    """Falsifiable acceptance criterion, measured through the CLIENT path."""

    @classmethod
    def setUpClass(cls) -> None:
        # RM-119 B2 (2026-08-06). Was `@unittest.skipUnless(_engine_is_up(),
        # ...)`, which had two problems: a decorator can only skip - it can
        # never fail, so RC_REQUIRE_DS_ENGINE could not reach it - and it ran
        # the retry loop at IMPORT time, which is precisely the collection-time
        # moment `_engine_is_up` documents as the load spike. Both fixed by
        # moving the probe into setUpClass and delegating the verdict.
        from tests.test_ds_live_route_gate import require_live_engine
        require_live_engine("the live conversion-seam reachability class",
                            up=_engine_is_up())

    def setUp(self) -> None:
        # Install the patient transport for the whole test (see the block
        # above). ``_post_json`` is resolved as a module global at call time by
        # every client entry point, so rebinding it here reaches the entire
        # nested call chain - the same seam
        # ``core/build_order_precompute.py:604-638`` uses in production.
        self.transport = _PatientTransport()
        patcher = mock.patch.object(dsc, "_post_json", self.transport)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._assert_no_swallowed_transport_failure)

        self.seeded = _registry_champions()
        self.controls = [c for c in _CONTROL_POOL if c not in self.seeded]
        self.assertGreaterEqual(
            len(self.controls), 3,
            "control pool decayed into the registries - repair the premise",
        )

    def _assert_no_swallowed_transport_failure(self) -> None:
        """A None body reaching any assertion in this class is a defect in the
        MEASUREMENT, not in the engine - surface it rather than let it colour a
        ranking comparison."""
        self.assertEqual(
            self.transport.failures, [],
            f"{len(self.transport.failures)} live engine call(s) returned no "
            f"body at a {_LIVE_TIMEOUT}s deadline - the verdict above is a "
            f"transport artefact, not engine behaviour",
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
