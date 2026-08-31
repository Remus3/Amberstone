# arch: lane 8 cycle 44 - non-finite float hardening for the callout DB | section=tests | frozen=no
"""Lane 8 cycle 44 regression tests for core/event_callouts.py.

THE DEFECT CLASS: every numeric coercion in the module was a bare
``float(...)`` guarded by ``except (TypeError, ValueError)``. That guard
catches a string and a None, and it does NOT catch NaN or +/-Infinity -
``float('nan')`` SUCCEEDS. So the two values the module cannot actually use
are exactly the two its fail-soft guard lets through.

Two distinct consequences, both proven red before the fix:

  1. ``next_callouts`` RAISED. A non-finite ``game_time_s`` reached
     ``int(elapsed_since_first // cadence_s)`` and raised
     ``ValueError: cannot convert float NaN to integer``. The function's own
     coercion block exists precisely so no bad ``game_time_s`` can raise, so
     the guard was defeated by the input it was written for. Both callers in
     ``dashboard/_deterministic_coaching.py`` (:929 inline, :959 background)
     swallow it with a bare ``except Exception`` and no log line, so the whole
     deterministic coaching result blanked silently and the warm path kept
     serving the last good value forever.

  2. A non-finite ``down_at_s`` on ONE event produced ``eta_s: nan`` in a
     returned row. ``dashboard/routes_state.py:226`` serializes the state with
     ``json.dumps(...)`` at the DEFAULT ``allow_nan=True``, which emits a bare
     ``NaN`` token. That token is not valid JSON (RFC 8259) and browser
     ``JSON.parse`` throws on it - measured on node v24:
     ``Unexpected token 'N', "{"eta_s":NaN}" is not valid JSON``. So one bad
     event field blanks the ENTIRE dashboard, not just the callout panel.
     This repo already treats that as a known class and defends against it
     with ``allow_nan=False`` in ``agents/_supervisor_http.py:190``,
     ``performance_tracker.py:55`` and three more modules; this module was
     MANUFACTURING the token those guards exist to reject.

REACHABILITY, scoped honestly. The chain is complete and unguarded at every
RC hop: ``core/liveclient_cache.py:201`` parses the Live Client body with
``json.loads`` at its default ``parse_constant``, which ACCEPTS the bare
``NaN`` / ``Infinity`` tokens, and ``dashboard/_liveclient.py:315`` admits the
result because ``isinstance(float('nan'), float)`` is True. What is NOT
claimed is that Riot emits such a token today - that is unmeasured. The
finding is that nothing in RC would stop it, and that the RAISE in (1) is a
contract violation regardless of any upstream.

MEASURED NEGATIVE, recorded so the next pass does not re-file it:
``core/district_fusion.py:178`` ``_within_window`` consumes the same
``down_at_s`` rows and is NaN-safe by accident - ``0.0 <= nan <= X`` is False,
so a non-finite event is skipped, which is the correct outcome. It is not a
sibling defect and needs no change.

Every test below whose name starts ``test_r`` was proven RED against the
pre-fix module. The ``test_c`` tests are characterization tests that pass
both before and after by design - they pin behaviour the fix must not move.
"""
from __future__ import annotations

import json
import math
import re
import unittest
from pathlib import Path

from core import event_callouts as ec
from core.event_callouts import (
    epic_buff_callouts,
    inhibitor_callouts,
    next_callouts,
)

NAN = float("nan")
INF = float("inf")
NEG_INF = float("-inf")

_MODULE_PATH = Path(ec.__file__)


def _nonfinite_etas(rows: object) -> list:
    """Tags of every row carrying a non-finite eta_s. Empty list = clean."""
    out = []
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return out
    for c in rows:
        if not isinstance(c, dict):
            continue
        eta = c.get("eta_s")
        if isinstance(eta, float) and not math.isfinite(eta):
            out.append(c.get("tag"))
    return out


class NonFiniteGameTimeTests(unittest.TestCase):
    """(1) next_callouts must not raise on a non-finite clock."""

    def test_r1_nan_game_time_does_not_raise(self):
        # RED pre-fix: ValueError: cannot convert float NaN to integer
        # (core/event_callouts.py:302).
        rows = next_callouts("sr", NAN, 6, 1)
        self.assertIsInstance(rows, list)

    def test_r2_positive_infinity_game_time_does_not_raise(self):
        # RED pre-fix. inf - inf is NaN, so +inf reached the same int() call.
        rows = next_callouts("sr", INF, 6, 1)
        self.assertIsInstance(rows, list)

    def test_c0_negative_infinity_game_time_already_did_not_raise(self):
        """CHARACTERIZATION, not a red test - stated because the first draft
        mislabelled it. ``-inf < spawn_s`` is True, so -inf took the
        ``eta = spawn_s - game_time_s`` branch and never reached the int()
        call that NaN and +inf died on. It did NOT escape clean: that branch
        returns ``eta_s = +inf``, which is the defect test_r5 catches.
        """
        rows = next_callouts("sr", NEG_INF, 6, 1)
        self.assertIsInstance(rows, list)

    def test_r4_nonfinite_clock_falls_back_to_the_documented_zero(self):
        """A non-finite clock behaves EXACTLY as clock 0.0.

        The pre-existing contract for an uncoercible game_time_s is gt = 0.0
        (the ``except (TypeError, ValueError)`` branch). The new non-finite
        branch joins that one rather than inventing a third behaviour - the
        defect was the raise, not the fallback value.

        ANCHORED ON THE LITERAL 0.0, not on the junk-string result, because
        mutation testing killed the first version of this test as vacuous:
        both NaN and "not-a-number" now route through _finite and take the
        SAME branch, so comparing them to each other could not observe the
        fallback VALUE at all - moving it to 60.0 left the test green. The
        real clock 0.0 is an independent anchor that a changed fallback
        cannot move with it.
        """
        at_zero = next_callouts("sr", 0.0, 6, 1, max_n=99)
        for label, bad in (("nan", NAN), ("inf", INF), ("-inf", NEG_INF),
                           ("junk-string", "not-a-number")):
            with self.subTest(clock=label):
                self.assertEqual(next_callouts("sr", bad, 6, 1, max_n=99),
                                 at_zero)

    def test_r16_infinite_level_does_not_raise_overflowerror(self):
        """RED pre-fix, and a SECOND handler class the first draft missed.

        ``int(float('inf'))`` raises OverflowError, which
        ``except (TypeError, ValueError)`` does NOT catch - so an infinite
        level or legendary_count escaped next_callouts entirely. NaN was
        caught here (int(nan) is a ValueError); only Infinity got through.
        Found by checking the int() sites after the float() ones, not by the
        original probe.
        """
        for field in ("level", "legendary_count"):
            for bad in (INF, NEG_INF):
                with self.subTest(field=field, bad=repr(bad)):
                    kwargs = {"level": 6, "legendary_count": 1}
                    kwargs[field] = bad
                    rows = next_callouts("sr", 600.0, **kwargs)
                    self.assertIsInstance(rows, list)

    def test_r17_nonfinite_level_falls_back_to_the_documented_default(self):
        """Level 1 / 0 legendaries - anchored on the LITERAL defaults.

        Same vacuity trap as test_r4: comparing the infinite-level result to
        the junk-string result cannot see the fallback value, because both
        take one branch. Anchored on real level 1 and real 0 legendaries
        instead - mutation-proven (M12, M13).
        """
        at_level_1 = next_callouts("sr", 600.0, 1, 1, max_n=99)
        at_zero_legs = next_callouts("sr", 600.0, 6, 0, max_n=99)
        for label, bad in (("inf", INF), ("-inf", NEG_INF), ("junk", "junk"),
                           ("nan", NAN)):
            with self.subTest(field="level", bad=label):
                self.assertEqual(
                    next_callouts("sr", 600.0, bad, 1, max_n=99), at_level_1)
            with self.subTest(field="legendary_count", bad=label):
                self.assertEqual(
                    next_callouts("sr", 600.0, 6, bad, max_n=99),
                    at_zero_legs)

    def test_r5_nonfinite_clock_emits_no_nonfinite_eta(self):
        for label, gt in (("nan", NAN), ("inf", INF), ("-inf", NEG_INF)):
            with self.subTest(clock=label):
                rows = next_callouts("sr", gt, 6, 1, max_n=99)
                self.assertEqual(_nonfinite_etas(rows), [])


class NonFiniteEventFieldTests(unittest.TestCase):
    """(2) a non-finite down_at_s must be skipped, never turned into eta_s."""

    def test_r6_nan_objective_down_at_s_emits_no_nan_eta(self):
        # RED pre-fix: the baron row carried eta_s = nan.
        rows = next_callouts(
            "sr", 1300.0, 6, 1, max_n=99,
            objective_events=[{"name": "baron", "killer_team": "ally",
                               "down_at_s": NAN}],
        )
        self.assertEqual(_nonfinite_etas(rows), [])

    def test_r7_nan_inhibitor_down_at_s_emits_no_nan_eta(self):
        # RED pre-fix: the inhib_lane row carried eta_s = nan.
        rows = inhibitor_callouts(
            [{"name": "Barracks_T1L1", "down_at_s": NAN}], 1300.0)
        self.assertEqual(_nonfinite_etas(rows), [])

    def test_r8_nan_epic_buff_down_at_s_emits_no_nan_eta(self):
        # RED pre-fix: the baron_buff_ally row carried eta_s = nan.
        rows = epic_buff_callouts(
            [{"name": "baron", "killer_team": "ally", "down_at_s": NAN}],
            1300.0)
        self.assertEqual(_nonfinite_etas(rows), [])

    def test_r9_every_public_entry_point_survives_a_nonfinite_event_field(self):
        """Sweep every exported entry point that consumes an event list.

        Structural rather than hand-enumerated: the cycle-43 lesson was that a
        hand count misses a site. Each case asserts no raise AND no non-finite
        eta_s for both NaN and +/-Infinity.
        """
        for bad in (NAN, INF, NEG_INF):
            obj = [{"name": "baron", "killer_team": "ally", "down_at_s": bad}]
            drake = [{"name": "dragon", "killer_team": "ally",
                      "down_at_s": bad, "dragon_type": "Fire"}]
            inhib = [{"name": "Barracks_T1L1", "down_at_s": bad}]
            turret = [{"name": "Turret_T2_L_03_A", "down_at_s": bad}]
            minions = [{"down_at_s": bad}]
            # Called eagerly rather than through lambdas: a deferred closure
            # over the loop variables is a late-binding trap (ruff B023) and
            # would make the sweep grade only the LAST value of bad.
            cases = (
                ("inhibitor_callouts", inhibitor_callouts(inhib, 900.0)),
                ("epic_buff_callouts", epic_buff_callouts(obj, 900.0)),
                ("structure_siege_callout",
                 ec.structure_siege_callout(turret, inhib, 900.0)),
                ("dragon_soul_callout", ec.dragon_soul_callout(drake)),
                ("wave_callout", ec.wave_callout(900.0, minions)),
                ("recall_callout", ec.recall_callout(bad, "Item", 3000)),
                ("next_callouts_all_event_lists", next_callouts(
                    "sr", 900.0, 6, 1, max_n=99, objective_events=obj,
                    inhib_events=inhib, turret_events=turret,
                    minion_events=minions, enable_wave=True)),
            )
            for name, rows in cases:
                with self.subTest(entry=name, bad=repr(bad)):
                    self.assertEqual(_nonfinite_etas(rows), [])


class StateSerializationContractTests(unittest.TestCase):
    """The /api/state contract: the result must be strict-JSON encodable."""

    def test_r10_result_encodes_under_allow_nan_false(self):
        """dashboard/routes_state.py:226 dumps at allow_nan=True, so a NaN
        becomes a bare NaN token the browser cannot parse. Asserting the
        STRICT encoder accepts the payload is the portable way to pin that a
        token can never be produced here."""
        for bad in (NAN, INF, NEG_INF):
            with self.subTest(bad=repr(bad)):
                rows = next_callouts(
                    "sr", 1300.0, 6, 1, max_n=99,
                    objective_events=[{"name": "baron", "killer_team": "ally",
                                       "down_at_s": bad}],
                    inhib_events=[{"name": "Barracks_T1L1",
                                   "down_at_s": bad}],
                )
                json.dumps(rows, allow_nan=False)

    def test_r11_nonfinite_clock_result_encodes_under_allow_nan_false(self):
        for bad in (NAN, INF, NEG_INF):
            with self.subTest(bad=repr(bad)):
                json.dumps(next_callouts("sr", bad, 6, 1, max_n=99),
                           allow_nan=False)


class SortKeyTests(unittest.TestCase):
    """_sort_key is exported and reused by dashboard/_deterministic_coaching."""

    def test_r12_nonfinite_eta_sorts_to_the_unknown_bucket(self):
        """RED pre-fix: returned (1, nan).

        A NaN comparison key makes list.sort() order-dependent and therefore
        non-deterministic, which contradicts the docstring's "Sorted
        active-first, then ascending ETA". A non-finite eta is an UNKNOWN eta,
        so it belongs in the same bucket None already uses.
        """
        none_bucket = ec._sort_key({"eta_s": None})[0]
        for bad in (NAN, INF, NEG_INF):
            with self.subTest(bad=repr(bad)):
                bucket, key = ec._sort_key({"eta_s": bad})
                self.assertEqual(bucket, none_bucket)
                self.assertTrue(math.isfinite(key))

    def test_r13_sorting_a_mixed_list_is_stable_and_total(self):
        rows = [
            {"tag": "a", "eta_s": 30.0},
            {"tag": "b", "eta_s": NAN},
            {"tag": "c", "eta_s": -5.0},
            {"tag": "d", "eta_s": None},
            {"tag": "e", "eta_s": 10.0},
        ]
        got = [c["tag"] for c in sorted(rows, key=ec._sort_key)]
        # active first, then ascending finite eta, then the unknown bucket in
        # stable input order (b before d).
        self.assertEqual(got, ["c", "e", "a", "b", "d"])


class StructuralGuardTests(unittest.TestCase):
    """Pin the root-cause fix shape, not just the symptoms.

    The cycle-43 precedent: a structural guard found a third defect site that
    a hand count had missed. A future edit that adds a bare ``float(`` back
    into this module reopens the exact class fixed here, and no behavioural
    test would necessarily catch it, so the guard reads the source.
    """

    def test_r14_no_bare_float_coercion_survives_in_the_module(self):
        src = _MODULE_PATH.read_text(encoding="utf-8")
        lines = src.splitlines()
        # The body of _finite itself is the ONE sanctioned coercion site.
        # Located structurally (def _finite -> next top-level def/class) so
        # the exemption cannot silently widen to the rest of the module.
        start = end = None
        for i, line in enumerate(lines):
            if line.startswith("def _finite("):
                start = i
            elif start is not None and end is None and re.match(
                    r"^(def |class )", line) and i > start:
                end = i
                break
        self.assertIsNotNone(start, "def _finite( not found - the guard is "
                                    "measuring nothing")
        if end is None:
            end = len(lines)
        exempt = range(start, end)

        offenders = []
        in_docstring = False
        for i, line in enumerate(lines):
            # Skip the module docstring block so prose about float() is not
            # graded as code (the module explains the defect in words).
            stripped = line.strip()
            if stripped.count('"""') == 1:
                in_docstring = not in_docstring
                continue
            if in_docstring or i in exempt:
                continue
            code = line.split("#", 1)[0]
            if not re.search(r"(?<![\w.])float\s*\(", code):
                continue
            offenders.append(f"{i + 1}: {stripped}")
        self.assertEqual(
            offenders, [],
            "every numeric coercion in core/event_callouts.py must route "
            "through _finite() so NaN/Infinity cannot pass a guard written "
            "for TypeError/ValueError. Offending lines:\n"
            + "\n".join(offenders))

    def test_r15_finite_helper_rejects_every_nonfinite_and_uncoercible_input(self):
        self.assertIsNone(ec._finite(NAN))
        self.assertIsNone(ec._finite(INF))
        self.assertIsNone(ec._finite(NEG_INF))
        self.assertIsNone(ec._finite(None))
        self.assertIsNone(ec._finite("abc"))
        self.assertIsNone(ec._finite({}))
        self.assertIsNone(ec._finite([1.0]))
        # OverflowError, the third handler class: float() of an int too large
        # to represent. Neither TypeError nor ValueError, so the original
        # handler tuple would have let it escape.
        self.assertIsNone(ec._finite(10 ** 400))
        # bool is rejected on purpose - float(True) is 1.0, which would let a
        # bool masquerade as a one-second clock.
        self.assertIsNone(ec._finite(True))
        self.assertIsNone(ec._finite(False))
        self.assertEqual(ec._finite(0.0), 0.0)
        self.assertEqual(ec._finite(-12.5), -12.5)
        self.assertEqual(ec._finite(7), 7.0)
        self.assertEqual(ec._finite("42.5"), 42.5)


class MaxNGuardTests(unittest.TestCase):
    """max_n was the ONE numeric parameter of next_callouts with no guard.

    Found by the independent audit pass, not by the original probe. The
    module's own ``test_bad_numeric_inputs_do_not_raise`` names the promise
    this broke - it coerces game_time_s, level and legendary_count and stops
    short of max_n.
    """

    def test_r18_uncoercible_max_n_does_not_raise(self):
        """RED pre-fix: TypeError: '>=' not supported between 'str' and 'int'
        escaping a function whose entire contract is fail-soft."""
        for bad in ("3", [], {}, object(), 1.5, NAN):
            with self.subTest(max_n=repr(bad)):
                rows = next_callouts("sr", 600.0, 6, 1, max_n=bad)
                self.assertIsInstance(rows, list)

    def test_r19_uncoercible_max_n_falls_back_to_no_cap(self):
        """An uncoercible cap joins None and -1, which ALREADY mean no cap.

        Chosen over "fall back to the default 3" because None and -1 are both
        pinned to the full list by the pre-existing suite
        (test_negative_max_n_returns_full_list), so this is the fallback that
        adds no third behaviour.
        """
        uncapped = next_callouts("sr", 600.0, 6, 1, max_n=None)
        self.assertGreater(len(uncapped), 3)
        for bad in ("3", [], 1.5, NAN, True):
            with self.subTest(max_n=repr(bad)):
                self.assertEqual(next_callouts("sr", 600.0, 6, 1, max_n=bad),
                                 uncapped)

    def test_c5_every_valid_max_n_is_unchanged(self):
        """CHARACTERIZATION. The pre-existing pins must not move."""
        self.assertEqual(next_callouts("sr", 0.0, 1, 0, max_n=0), [])
        self.assertGreater(len(next_callouts("sr", 0.0, 1, 0, max_n=-1)), 3)
        self.assertEqual(len(next_callouts("sr", 600.0, 6, 1, max_n=2)), 2)
        self.assertGreater(
            len(next_callouts("sr", 600.0, 6, 1, max_n=None)), 3)


class OutputContractTests(unittest.TestCase):
    """The next_callouts docstring under-declared its own emitted kind set."""

    def test_r20_docstring_declares_every_kind_the_function_can_emit(self):
        """RED pre-fix: the docstring listed six kinds and the function emits
        eight. ``inhibitor`` and ``siege`` were both missing, and
        ``web/js/panels/callouts.js`` stamps ``data-kind`` into the DOM for
        CSS, so a style map built from the docstring silently unstyles two of
        eight row types. The CODE is the correct half here; the docstring is
        the wrong one.

        Derived from real output rather than a hand list, so a new kind added
        later without a docstring update fails here.
        """
        emitted = set()
        for gt in (0.0, 305.0, 900.0, 1300.0, 2200.0):
            rows = next_callouts(
                "sr", gt, 6, 1, max_n=99, gold=99999,
                next_item_name="Item", next_item_cost=100,
                objective_events=[
                    {"name": "baron", "killer_team": "ally",
                     "down_at_s": max(gt - 30.0, 0.0)},
                    {"name": "dragon", "killer_team": "ally",
                     "down_at_s": max(gt - 40.0, 0.0),
                     "dragon_type": "Fire"}],
                inhib_events=[{"name": "Barracks_T1L1",
                               "down_at_s": max(gt - 10.0, 0.0)}],
                turret_events=[{"name": "Turret_T2_L_03_A",
                                "down_at_s": max(gt - 5.0, 0.0)}],
                minion_events=[{"at_s": 65.0}],
                enable_wave=True,
            )
            emitted.update(c["kind"] for c in rows)
        self.assertTrue(emitted, "probe emitted nothing - the test is vacuous")

        # Parse the DECLARED set out of the "kind in {...}" clause rather
        # than substring-matching the whole docstring. Mutation testing
        # killed the first version: deleting "siege" from the kind list left
        # the test green because the word still appeared in the Args prose.
        doc = next_callouts.__doc__ or ""
        m = re.search(r"kind in \{([^}]*)\}", doc, re.S)
        self.assertIsNotNone(
            m, "next_callouts docstring no longer declares a 'kind in {...}' "
               "set - the guard is measuring nothing")
        declared = {t.strip() for t in m.group(1).replace("\n", " ").split(",")
                    if t.strip()}
        missing = sorted(emitted - declared)
        self.assertEqual(
            missing, [],
            "next_callouts emits these kinds but its docstring's 'kind in "
            f"{{...}}' clause does not list them: {missing}. Emitted "
            f"{sorted(emitted)}; declared {sorted(declared)}.")

    def test_r21_docstring_documents_every_event_parameter(self):
        """The Args block omitted turret_events, minion_events and
        enable_wave - all three passed live by
        dashboard/_deterministic_coaching.py."""
        import inspect
        doc = next_callouts.__doc__ or ""
        params = inspect.signature(next_callouts).parameters
        missing = sorted(p for p in params if p not in doc)
        self.assertEqual(
            missing, [],
            f"next_callouts parameters absent from its docstring: {missing}")


class CharacterizationTests(unittest.TestCase):
    """Green BOTH before and after. These pin what the fix must NOT move."""

    def test_c1_finite_objective_take_still_drives_the_respawn_eta(self):
        rows = next_callouts(
            "sr", 1300.0, 6, 1, max_n=99,
            objective_events=[{"name": "baron", "killer_team": "ally",
                               "down_at_s": 1250.0}],
        )
        baron = next((c for c in rows if c.get("tag") == "baron"), None)
        self.assertIsNotNone(baron)
        # last kill 1250 + 360s respawn = 1610; at gt 1300 that is 310s out.
        self.assertAlmostEqual(baron["eta_s"], 310.0, places=1)

    def test_c2_finite_inhibitor_still_yields_its_respawn_row(self):
        rows = inhibitor_callouts(
            [{"name": "Barracks_T1L1", "down_at_s": 1000.0}], 1100.0)
        self.assertTrue(rows)
        self.assertAlmostEqual(rows[0]["eta_s"], 200.0, places=1)

    def test_c3_a_bad_string_down_at_s_is_still_skipped_silently(self):
        self.assertEqual(
            inhibitor_callouts(
                [{"name": "Barracks_T1L1", "down_at_s": "soon"}], 1100.0),
            [])

    def test_c4_normal_early_game_shape_is_unchanged(self):
        rows = next_callouts("sr", 240.0, 5, 0, max_n=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(_nonfinite_etas(rows), [])
        dragon = next((c for c in rows if c.get("tag") == "dragon"), None)
        self.assertIsNotNone(dragon)
        self.assertAlmostEqual(dragon["eta_s"], 60.0, places=1)


if __name__ == "__main__":
    unittest.main()
