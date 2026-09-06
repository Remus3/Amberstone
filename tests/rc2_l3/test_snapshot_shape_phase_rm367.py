"""lcu/snapshot_shape.py - an empty gameflow body is not a phase (RM-367).

``shape_snapshot`` reads ``/lol-gameflow/v1/gameflow-phase`` and assigned
``state["phase"] = phase.strip('"')`` for ANY ``str`` body, so an empty,
quote-only or whitespace-only body landed in the payload as a phase string
that no arm matches - a value claiming to be a live read when nothing was
read. The ``bytes`` branch one line down had the identical hole.

THE DECISION THIS FILE PINS, and the two alternatives it rejects.

RM-367 offered three readings of an empty body: a falsy no-phase that joins
the existing null path, a distinguishable unreadable-body value, or a value
the shaper omits entirely. **This tree chose the falsy no-phase, emitted as
Python None**, on the consumer contract rather than on consistency - which is
the same basis RM-347 settled on, and RM-347's fence explicitly forbids
unifying the three in-tree conventions for their own sake:

  * ``web/js/main.js:629`` reads ``const phase = lcu && lcu.phase``, and the
    two arms that branch on a FALSY phase - the s209 sticky-guard inference at
    ``:711`` and the item-281 null-phase in-game promotion at ``:728`` - fire
    identically for ``""``, ``null`` and ``undefined``. None of the three is
    matched by any explicit ``phase === ...`` arm either. So None changes no
    view arm, and ``"Unknown"`` - the value the very next branch uses - would
    have silently DISARMED both, because it is truthy. That is the row's named
    trap and the reason this was a row rather than a one-line consistency fix.
  * ``dashboard/_cs_retention.py:114`` tests ``snap.get("phase") in
    _CLEAR_PHASES``. That frozenset holds the *string* ``"None"`` - a real LCU
    phase - and neither ``""`` nor Python None, so both fall into the
    "unknown, do not act on it" bucket. This is the exact consumer contract
    ``lcu/lcu_pregame.py:346-351`` cites as the reason RM-347 chose None.

Omitting the key entirely (the third option) was rejected on measurement, not
taste: ``shape_snapshot`` itself reads ``state["phase"]`` by BRACKET at
``:432``, ``:488``, ``:498``, ``:506`` and ``:543``, so omission raises
KeyError five lines later. Distinguishing the empty body (the second option)
needs either a truthy sentinel - the trap above - or a new payload key no
consumer asked for; choosing the falsy no-phase means deliberately NOT
distinguishing it, so ``cs_debug.raw_phase`` keeps following ``phase`` exactly
as it does today.

The predicate is NOT re-implemented here. ``lcu/lcu_pregame.py:96``
``_phase_or_none`` is RM-347's, already documents this exact rule ("An EMPTY
body is not a phase name"), and lives in the same package - a near-copy is the
``feedback_resolver_fix_is_not_a_consumer_fix`` failure class.

NOT in scope, recorded so a later pass does not read the omission as an
oversight: the unguarded ``phase.decode()`` on the bytes branch is already
filed as RM-293, and the ``else: "Unknown"`` branch is left exactly as it is -
its truthiness is measured and filed separately rather than changed here.

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dashboard.view_router_state import update_game_started  # noqa: E402
from lcu.snapshot_shape import (  # noqa: E402
    _reset_mastery_cache_for_tests,
    _reset_summoner_lookup_cache_for_tests,
    shape_snapshot,
)

_PHASE = "/lol-gameflow/v1/gameflow-phase"


def _fake_request(phase_body):
    """Agent transport contract: (method, path, body=None) -> (payload, err).

    Only the gameflow-phase route answers; every other path 404s exactly as
    LCU does for a resource that is not live in the current phase, which keeps
    each case to the one field under test.
    """
    def request(method, path, body=None):
        if path == _PHASE:
            return phase_body, None
        return None, "404"
    return request


def _phase_of(phase_body):
    return shape_snapshot(_fake_request(phase_body), {})["phase"]


class EmptyGameflowBodyIsNotAPhaseTest(unittest.TestCase):
    """An empty body must not be reported as a phase (RM-367)."""

    def setUp(self):
        _reset_mastery_cache_for_tests()
        _reset_summoner_lookup_cache_for_tests()

    def tearDown(self):
        _reset_mastery_cache_for_tests()
        _reset_summoner_lookup_cache_for_tests()

    # -- the defect: str bodies that name no phase ----------------------

    def test_empty_str_body_is_not_reported_as_a_phase(self):
        """Pre-fix this landed as "" - not a phase, reported as one."""
        self.assertIsNone(_phase_of(""))

    def test_quote_only_str_body_is_not_reported_as_a_phase(self):
        """The body arrives quoted, so '""' is the empty body on the wire."""
        self.assertIsNone(_phase_of('""'))

    def test_whitespace_only_str_body_is_not_reported_as_a_phase(self):
        """strip('"') alone leaves '   ' - truthy, and matched by no arm."""
        self.assertIsNone(_phase_of('"   "'))

    # -- the same hole one branch down (acceptance names it) ------------

    def test_empty_bytes_body_gets_identical_treatment(self):
        self.assertIsNone(_phase_of(b""))

    def test_quote_only_bytes_body_gets_identical_treatment(self):
        self.assertIsNone(_phase_of(b'""'))

    def test_whitespace_only_bytes_body_gets_identical_treatment(self):
        self.assertIsNone(_phase_of(b'"   "'))

    # -- the normal path must be untouched ------------------------------

    def test_real_phase_is_unchanged(self):
        self.assertEqual(_phase_of('"ChampSelect"'), "ChampSelect")

    def test_real_phase_unquoted_is_unchanged(self):
        """Some client versions answer unquoted; both must still work."""
        self.assertEqual(_phase_of("InProgress"), "InProgress")

    def test_real_phase_from_bytes_is_unchanged(self):
        self.assertEqual(_phase_of(b'"InProgress"'), "InProgress")

    def test_literal_None_phase_survives_as_the_string(self):
        """The LCU's idle phase IS the string "None" - a REAL phase.

        Collapsing it to Python None would make "the operator is sitting at
        the home screen" indistinguishable from "nothing could be read", which
        is precisely the confusion RM-347 was filed over. It is also an
        explicit member of ``dashboard/_cs_retention._CLEAR_PHASES``, so
        losing it would stop champ-select retention ever being cleared.
        """
        self.assertEqual(_phase_of('"None"'), "None")

    def test_unreadable_body_type_still_reports_Unknown(self):
        """The ``else`` branch is deliberately NOT changed by this row.

        A non-str/non-bytes body (a failed request answering None) keeps
        reporting "Unknown". Its truthiness is a separate question, measured
        and filed rather than folded into this fix.
        """
        self.assertEqual(_phase_of(None), "Unknown")

    # -- the breadcrumb follows the decision ----------------------------

    def test_cs_debug_raw_phase_follows_phase(self):
        """Choosing the falsy no-phase means NOT distinguishing the empty
        body, so the diagnostic breadcrumb tracks ``phase`` rather than
        preserving a value the payload has just declined to report.
        """
        snap = shape_snapshot(_fake_request('""'), {})
        self.assertIsNone(snap["cs_debug"]["raw_phase"])
        self.assertEqual(snap["cs_debug"]["raw_phase"], snap["phase"])


class ViewArmIndifferenceTest(unittest.TestCase):
    """None must fire the same view arm "" did - the row's second acceptance.

    Exercised through ``dashboard/view_router_state``, which is the sanctioned
    way to drive the transition table under pytest (its own header at ``:1-7``
    says the JS in ``main.js`` stays canonical). That makes this a test of the
    TRANSITION TABLE, not of the runtime consumer, and it is not claimed to be
    more: the JS half is proven by reading ``main.js:629`` - ``lcu &&
    lcu.phase`` - where ``""`` and ``null`` are both falsy and reach the arms
    at ``:711`` and ``:728`` identically. The mirror's own docstring at ``:86``
    already records that ``lcu.phase`` "reads null/empty" as ONE class.
    """

    def test_s209_sticky_guard_arm_is_indifferent(self):
        """ChampSelect ended, phase not stable, a game is live -> in-progress."""
        empty = update_game_started("", "champ-select", live=True)
        none_ = update_game_started(None, "champ-select", live=True)
        self.assertEqual(empty, "in-progress")
        self.assertEqual(empty, none_)

    def test_item_281_null_phase_promotion_arm_is_indifferent(self):
        empty = update_game_started("", None, live=True, mode="aram")
        none_ = update_game_started(None, None, live=True, mode="aram")
        self.assertEqual(empty, "in-progress")
        self.assertEqual(empty, none_)

    def test_live_gate_still_holds_for_both(self):
        """Without a live game neither value may PROMOTE the sticky.

        The arm holds ``prior`` rather than clearing it - a blip during champ
        select must leave the view where it was, which is the whole point of
        the ``live`` gate documented at ``view_router_state.py:86-95``. This
        assertion was written the other way round first and the test caught
        it; the contract is "does not advance", not "returns None".
        """
        self.assertEqual(
            update_game_started("", "champ-select", live=False), "champ-select")
        self.assertEqual(
            update_game_started(None, "champ-select", live=False), "champ-select")

    def test_Unknown_would_have_disarmed_both_arms(self):
        """The rejected alternative, pinned so the trap cannot be re-entered.

        "Unknown" is truthy and matches no explicit ``phase === ...`` arm, so
        it falls through to ``return prior`` - the sticky never advances. This
        asserts the BEHAVIOUR that made "Unknown" the wrong answer, so anyone
        later "unifying" the two conventions sees this go red.
        """
        self.assertIsNone(
            update_game_started("Unknown", None, live=True, mode="aram"))
        self.assertEqual(
            update_game_started("Unknown", "champ-select", live=True),
            "champ-select")


if __name__ == "__main__":
    unittest.main()
