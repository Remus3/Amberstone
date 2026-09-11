"""RM-312 - the in-process L3 degrade to the :8889 relay must not be SILENT.

``dashboard/_lcu_inprocess.lcu_summary_inprocess`` wraps the whole
``shape_snapshot`` assembly in ``try: ... except Exception: return None``
(``dashboard/_lcu_inprocess.py:182-191`` as filed 2026-08-31; the same three
lines are :255-257 after the RM-312 fix). Returning ``None`` IS the contract -
``dashboard/_state_builder._read_lcu_snapshot`` (:80-100) falls back to the
relay ``lcu_summary()`` on it - but before RM-312
that path emitted nothing, so a real shaping fault was indistinguishable from
the ordinary, expected "League is not running" case. RC would pay the relay
hop that lever L3 exists to REMOVE, forever, with nothing in ``logs/`` saying
why.

This guard pins the SIGNAL without touching the contract:

  * a raising ``shape_snapshot`` still returns ``None`` (fail-soft intact);
  * exactly one WARNING is emitted, naming the exception TYPE and the
    innermost raising frame (never the payload - an LCU snapshot carries
    PUUIDs);
  * the ordinary not-connected path (``client._port`` falsy) logs NOTHING on
    ``rc.web_dashboard``, which is the assertion that matters most: a line on
    the expected path is worse than no line at all. Scoped to that logger on
    purpose - the frozen ``lcu/lcu_client.py:110`` already emits its own
    first-miss INFO on ``rc.lcu`` when the lockfile is absent, and that is
    pre-existing, deliberate and not RM-312's to change;
  * the throttle holds - ``build_state()`` runs on a 1 Hz SSE/TTL cadence
    (``dashboard/routes_state.py:210-230`` + :378-390), so a persistent fault
    must not write ~3600 WARNING lines an hour.

ANTI-VACUITY (CLAUDE.md "Testing Discipline"): an empty or no-op run would
PASS a bare ``assertNoLogs``, so the not-connected arm carries a POSITIVE
CONTROL - the same capture context, same logger, is shown to catch a record
when the fault path IS driven. The frame-attribution arm raises from a
uniquely named module-level helper and asserts that name reaches the log
line, so a hardcoded or constant message cannot pass.

Spies here are RECORDING, never raising: an ``AssertionError`` IS an
``Exception`` and would be swallowed by the very ``except`` under test
(``reference_raise_based_spy_is_vacuous_under_fail_soft``).

API surface, RE-DERIVED after the RM-312 edit landed - the fix moved every
offset in this module, so the pre-edit numbers this block first carried were
all stale (``feedback_your_own_edit_staled_the_citation``):
  * ``lcu_summary_inprocess``        dashboard/_lcu_inprocess.py:232
  * ``_log_degrade``                 dashboard/_lcu_inprocess.py:127
  * ``_get_client``                  dashboard/_lcu_inprocess.py:158
  * ``shape_snapshot`` (module ref)  dashboard/_lcu_inprocess.py:76
  * ``_read_relay_snapshot``         dashboard/_lcu_inprocess.py:190
  * ``_reset_client_for_tests``      dashboard/_lcu_inprocess.py:260
  * ``_expire_degrade_log_for_tests`` dashboard/_lcu_inprocess.py:290
  * ``client._port`` read            dashboard/_lcu_inprocess.py:173, :249, :252
  * logger name "rc.web_dashboard"   dashboard/_lcu_inprocess.py:78,
                                     dashboard/_state_builder.py:41

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dashboard._lcu_inprocess as inp  # noqa: E402

_LOGGER_NAME = "rc.web_dashboard"
_THIS_FILE = os.path.basename(__file__)


def _raise_from_named_helper(*_args, **_kwargs):
    """Raise from a uniquely named frame so the log line can be anchored."""
    raise RuntimeError("shape blew up")


class _StubClient:
    """Stand-in LcuClient exposing only what the reader touches.

    Mirrors tests/rc2_l3/test_lcu_inprocess_l3.py:37. These are ordinary
    instance methods, not class-accessed stubs, so no @staticmethod wrapping
    applies here.
    """

    def __init__(self, port):
        self._port = port
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        return bool(self._port)

    def _refresh_conn_if_changed(self):
        pass

    def _request(self, method, endpoint, data=None, _retry=True):
        return None


class TestDegradeIsNotSilent(unittest.TestCase):
    """RM-312: the except-and-return-None path must leave a trace."""

    def setUp(self):
        inp._reset_client_for_tests()

    def tearDown(self):
        inp._reset_client_for_tests()

    def _drive_fault(self, side_effect):
        """Run lcu_summary_inprocess with a connected client and a raising
        shape_snapshot. The relay read is stubbed so the suite never touches
        the live :8889."""
        client = _StubClient(port=1234)
        with mock.patch.object(inp, "_get_client", return_value=client), \
                mock.patch.object(inp, "_read_relay_snapshot",
                                  return_value={}), \
                mock.patch.object(inp, "shape_snapshot",
                                  side_effect=side_effect):
            return inp.lcu_summary_inprocess()

    # --- contract preserved -------------------------------------------------

    def test_raising_shape_snapshot_still_returns_none(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING"):
            out = self._drive_fault(_raise_from_named_helper)
        self.assertIsNone(out)

    # --- the signal ---------------------------------------------------------

    def test_fault_emits_exactly_one_warning_naming_the_exception_type(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_from_named_helper)
        self.assertEqual(len(cap.records), 1, cap.output)
        rec = cap.records[0]
        self.assertEqual(rec.levelname, "WARNING")
        self.assertIn("RuntimeError", rec.getMessage())

    def test_warning_names_the_innermost_raising_frame(self):
        # Anchors the message to REAL traceback data: a constant string or a
        # message built only from the except-clause frame cannot contain the
        # helper's name or this file's basename.
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_from_named_helper)
        msg = cap.records[0].getMessage()
        self.assertIn("_raise_from_named_helper", msg)
        self.assertIn(_THIS_FILE, msg)

    def test_warning_does_not_leak_the_exception_payload_text(self):
        # An LCU payload carries PUUIDs, so the line is built from the
        # exception TYPE plus frame coordinates only - never str(exc).
        def _raise_with_secret(*_a, **_k):
            raise RuntimeError("puuid=SECRET-PUUID-VALUE")

        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_with_secret)
        self.assertNotIn("SECRET-PUUID-VALUE", cap.records[0].getMessage())

    # --- the assertion that matters most ------------------------------------

    def test_ordinary_not_connected_path_logs_nothing(self):
        client = _StubClient(port=None)
        spy = mock.Mock(name="shape_snapshot_must_not_run")
        with self.assertNoLogs(_LOGGER_NAME, level="DEBUG"):
            with mock.patch.object(inp, "_get_client", return_value=client), \
                    mock.patch.object(inp, "shape_snapshot", spy):
                out = inp.lcu_summary_inprocess()
        # Anchors: the code path really ran and really short-circuited.
        self.assertIsNone(out)
        self.assertFalse(spy.called, "not-connected must not reach the shape")

        # POSITIVE CONTROL - the same logger and the same capture style DO
        # catch a record when the fault path is driven, so the assertNoLogs
        # above is a real negative, not a vacuous one.
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_from_named_helper)
        self.assertEqual(len(cap.records), 1, cap.output)

    # --- the throttle (1 Hz build_state cadence) ----------------------------

    def test_identical_repeated_fault_logs_once_not_per_call(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            for _ in range(5):
                self.assertIsNone(self._drive_fault(_raise_from_named_helper))
        self.assertEqual(len(cap.records), 1, cap.output)

    def test_a_different_fault_signature_logs_again(self):
        def _raise_value_error(*_a, **_k):
            raise ValueError("different fault")

        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_from_named_helper)
            self._drive_fault(_raise_value_error)
        self.assertEqual(len(cap.records), 2, cap.output)
        joined = " ".join(r.getMessage() for r in cap.records)
        self.assertIn("RuntimeError", joined)
        self.assertIn("ValueError", joined)

    def test_throttle_expiry_re_logs_the_same_fault(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_from_named_helper)
            inp._expire_degrade_log_for_tests()
            self._drive_fault(_raise_from_named_helper)
        self.assertEqual(len(cap.records), 2, cap.output)

    def test_reset_helper_clears_the_degrade_log_state(self):
        # _reset_client_for_tests must also forget the throttle, or an
        # earlier test in the same process would suppress a later one.
        self._drive_fault(_raise_from_named_helper)
        inp._reset_client_for_tests()
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_raise_from_named_helper)
        self.assertEqual(len(cap.records), 1, cap.output)


if __name__ == "__main__":
    unittest.main()
