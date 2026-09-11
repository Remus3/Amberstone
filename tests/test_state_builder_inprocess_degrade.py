"""RM-405 - the CALLER seam of the in-process L3 read must not degrade SILENTLY.

RM-312 made a fault raised INSIDE ``dashboard/_lcu_inprocess`` visible: that
module's own ``except`` now WARNs through a throttled ``_log_degrade`` before
returning ``None``. But ``dashboard/_state_builder._read_lcu_snapshot`` wraps
the whole call in a SECOND ``try/except`` one layer up::

    if os.environ.get("RC_LCU_INPROCESS") == "1":
        try:
            from dashboard._lcu_inprocess import lcu_summary_inprocess
            snap = lcu_summary_inprocess()
        except Exception:
            snap = None
        ...
    return lcu_summary()

Anything that ESCAPES ``_lcu_inprocess`` lands there and was swallowed with no
trace at all. Two concrete classes RM-312 provably cannot cover:

  * the LAZY IMPORT on the ``from dashboard._lcu_inprocess import ...`` line.
    If that raises (ImportError from a broken/renamed module, a circular
    import, a failure inside ``lcu.snapshot_shape`` at module load), the
    module never loads, so RM-312's ``_log_degrade`` does not exist to run;
  * a fault RE-RAISED past ``lcu_summary_inprocess``'s own guard - it catches
    with ``except Exception`` at ``dashboard/_lcu_inprocess.py:260``, so
    anything that escapes that clause (including a fault raised from inside
    the except body itself) surfaces one frame up, here.

SCOPE, stated so this file does not overstate its own coverage: BOTH layers
catch ``except Exception``, never ``BaseException``. A true ``BaseException``
(``KeyboardInterrupt``, ``SystemExit``) is NOT caught at either seam and
propagates straight out of ``_read_lcu_snapshot`` - it is deliberately out of
scope, not covered. The ``exc: BaseException`` annotation on
``_log_inprocess_caller_degrade`` is a widening of the PARAMETER type only; it
does not widen what the ``except`` clause admits.

Either way RC pays the :8889 relay hop that lever L3 exists to REMOVE, forever,
with nothing in ``logs/`` saying why - the exact failure RM-312 closed, one
frame higher.

This guard pins the caller-seam signal without touching the contract:

  * the fault path still yields ``lcu_summary()`` (fail-soft intact, asserted
    by identity against a sentinel);
  * exactly ONE WARNING per distinct fault signature, then at most one per
    ``_CALLER_DEGRADE_LOG_THROTTLE_S``. ``build_state()`` runs at
    ``RC_STATE_CADENCE_SEC``, default 0.5 s with a 0.1 floor
    (``dashboard/routes_state.py:167-178``), i.e. about 2 Hz, so an
    unthrottled persistent fault is on the order of 7000 lines an hour. The
    count arm drives 200 identical faults and asserts exactly 1 record;
  * the line NEVER carries ``str(exc)``. An LCU payload carries PUUIDs and
    this repo is PUBLIC, so the leak arm raises through a distinctive marker
    and asserts it is absent from ``getMessage()``, ``repr(record.args)``,
    ``repr(record.__dict__)`` AND a full ``logging.Formatter`` render - the
    four places a message can actually reach a handler;
  * the message is DISTINGUISHABLE from RM-312's, so a log reader can tell
    the caller seam from the module seam.

ANTI-VACUITY (CLAUDE.md "Testing Discipline"): a bare "nothing was logged"
assertion passes against a dead code path, so the flag-unset negative control
carries a POSITIVE CONTROL in the same test - the same logger, same capture
style, is shown to catch a record when the fault path IS driven. The
frame-attribution arm anchors on a uniquely named module-level helper plus this
file's basename, so a constant or hardcoded message cannot pass. This file was
additionally re-run with the ``log.warning`` call stubbed to a no-op and the
signal arms confirmed RED.

Spies here are RECORDING, never raising: an ``AssertionError`` IS an
``Exception`` and would be swallowed by the very ``except`` under test.

API surface, RE-DERIVED from disk AFTER this slice's own edit landed. RM-405
inserted 83 lines near the top of ``dashboard/_state_builder.py``, so every
number this block first carried was staled by the very change it documents
(``feedback_your_own_edit_staled_the_citation``):
  * ``_log_inprocess_caller_degrade``     dashboard/_state_builder.py:108
  * ``_read_lcu_snapshot``                dashboard/_state_builder.py:155
  * the ``RC_LCU_INPROCESS`` gate         dashboard/_state_builder.py:173
  * the lazy import line                  dashboard/_state_builder.py:175
  * the caller-seam ``except``            dashboard/_state_builder.py:177
  * ``lcu_summary`` (module ref)          dashboard/_state_builder.py:37
  * logger name "rc.web_dashboard"        dashboard/_state_builder.py:42,
                                          dashboard/_lcu_inprocess.py:78

All authored content here is 7-bit ASCII.
"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import dashboard._state_builder as sb  # noqa: E402

_LOGGER_NAME = "rc.web_dashboard"
_THIS_FILE = os.path.basename(__file__)
_INPROCESS_MOD = "dashboard._lcu_inprocess"

# Identity sentinel: the relay fallback must be returned verbatim.
_RELAY_SENTINEL = {"__relay__": "sentinel"}


def _escape_from_named_helper(*_args, **_kwargs):
    """Raise past lcu_summary_inprocess from a uniquely named frame."""
    raise RuntimeError("escaped the module guard")


class _RaisingModuleStub:
    """A ``sys.modules`` entry whose attribute access always fails.

    ``from dashboard._lcu_inprocess import lcu_summary_inprocess`` resolves
    the name off this object, gets ``AttributeError``, and the IMPORT_FROM
    opcode converts that into ``ImportError`` - which is exactly the real
    broken-module shape, raised on the import LINE inside
    ``_read_lcu_snapshot``. RM-312's ``_log_degrade`` cannot possibly run
    here: its module never loaded.
    """

    __name__ = _INPROCESS_MOD

    def __getattr__(self, name):
        raise AttributeError(name)


class _StateBuilderDegradeBase(unittest.TestCase):

    def setUp(self):
        sb._reset_caller_degrade_log_for_tests()

    def tearDown(self):
        sb._reset_caller_degrade_log_for_tests()

    def _drive_fault(self, side_effect):
        """Flag ON, ``lcu_summary_inprocess`` raising, relay stubbed."""
        with mock.patch.dict(os.environ, {"RC_LCU_INPROCESS": "1"}), \
                mock.patch.object(sb, "lcu_summary",
                                  return_value=_RELAY_SENTINEL), \
                mock.patch(_INPROCESS_MOD + ".lcu_summary_inprocess",
                           side_effect=side_effect):
            return sb._read_lcu_snapshot()

    def _drive_import_fault(self):
        """Flag ON, the LAZY IMPORT itself failing, relay stubbed."""
        with mock.patch.dict(os.environ, {"RC_LCU_INPROCESS": "1"}), \
                mock.patch.dict(sys.modules,
                                {_INPROCESS_MOD: _RaisingModuleStub()}), \
                mock.patch.object(sb, "lcu_summary",
                                  return_value=_RELAY_SENTINEL):
            return sb._read_lcu_snapshot()


class TestCallerSeamContract(_StateBuilderDegradeBase):
    """The fix must not change what _read_lcu_snapshot RETURNS."""

    def test_escaped_fault_still_returns_the_relay_result(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING"):
            out = self._drive_fault(_escape_from_named_helper)
        self.assertIs(out, _RELAY_SENTINEL)

    def test_import_failure_still_returns_the_relay_result(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING"):
            out = self._drive_import_fault()
        self.assertIs(out, _RELAY_SENTINEL)

    def test_success_path_returns_the_inprocess_snapshot_unlogged(self):
        good = {"lcu_port": "1234"}
        with self.assertNoLogs(_LOGGER_NAME, level="DEBUG"):
            with mock.patch.dict(os.environ, {"RC_LCU_INPROCESS": "1"}), \
                    mock.patch.object(sb, "lcu_summary",
                                      return_value=_RELAY_SENTINEL), \
                    mock.patch(_INPROCESS_MOD + ".lcu_summary_inprocess",
                               return_value=good):
                out = sb._read_lcu_snapshot()
        self.assertIs(out, good)

    def test_inprocess_returning_none_is_silent_here(self):
        # The ordinary "League is not running" case. RM-312 owns the decision
        # to stay quiet there; the caller seam must not add a line of its own.
        with self.assertNoLogs(_LOGGER_NAME, level="DEBUG"):
            with mock.patch.dict(os.environ, {"RC_LCU_INPROCESS": "1"}), \
                    mock.patch.object(sb, "lcu_summary",
                                      return_value=_RELAY_SENTINEL), \
                    mock.patch(_INPROCESS_MOD + ".lcu_summary_inprocess",
                               return_value=None):
                out = sb._read_lcu_snapshot()
        self.assertIs(out, _RELAY_SENTINEL)


class TestCallerSeamSignal(_StateBuilderDegradeBase):
    """The escaped fault must leave exactly one, attributable trace."""

    def test_escaped_fault_emits_one_warning_naming_the_exception_type(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_escape_from_named_helper)
        self.assertEqual(len(cap.records), 1, cap.output)
        rec = cap.records[0]
        self.assertEqual(rec.levelname, "WARNING")
        self.assertIn("RuntimeError", rec.getMessage())

    def test_warning_names_the_innermost_raising_frame(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_escape_from_named_helper)
        msg = cap.records[0].getMessage()
        self.assertIn("_escape_from_named_helper", msg)
        self.assertIn(_THIS_FILE, msg)

    def test_message_is_distinguishable_from_the_rm312_module_seam(self):
        # A log reader must be able to tell WHICH layer faulted. RM-312's line
        # reads "in-process LCU read failed"; this one must not be identical.
        import dashboard._lcu_inprocess as inp

        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_escape_from_named_helper)
        caller_msg = cap.records[0].getMessage()

        def _module_fault(*_a, **_k):
            raise RuntimeError("module seam")

        class _StubClient:
            _port = 1234

            def connect(self):
                return True

            def _refresh_conn_if_changed(self):
                pass

            def _request(self, method, endpoint, data=None, _retry=True):
                return None

        inp._reset_client_for_tests()
        try:
            with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap2:
                with mock.patch.object(inp, "_get_client",
                                       return_value=_StubClient()), \
                        mock.patch.object(inp, "_read_relay_snapshot",
                                          return_value={}), \
                        mock.patch.object(inp, "shape_snapshot",
                                          side_effect=_module_fault):
                    inp.lcu_summary_inprocess()
            module_msg = cap2.records[0].getMessage()
        finally:
            inp._reset_client_for_tests()

        self.assertNotEqual(caller_msg, module_msg)
        # Not merely different by frame coordinates: the prose must differ too.
        self.assertNotEqual(caller_msg.split(":")[0], module_msg.split(":")[0])


class TestCallerSeamNoPayloadLeak(_StateBuilderDegradeBase):
    """This repo is PUBLIC and LCU payloads carry PUUIDs - never str(exc)."""

    MARKER = "PUUID-LEAK-MARKER-7f3a"

    def _leaky(self, *_a, **_k):
        raise RuntimeError("puuid=" + self.MARKER)

    def _assert_marker_absent(self, rec):
        self.assertNotIn(self.MARKER, rec.getMessage())
        self.assertNotIn(self.MARKER, repr(rec.args))
        self.assertNotIn(self.MARKER, repr(rec.__dict__))
        rendered = logging.Formatter("%(message)s").format(rec)
        self.assertNotIn(self.MARKER, rendered)

    def test_escaped_fault_does_not_leak_the_exception_text(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(self._leaky)
        self.assertEqual(len(cap.records), 1, cap.output)
        self._assert_marker_absent(cap.records[0])

    def test_marker_control_proves_the_assertion_can_fail(self):
        # Anti-vacuity for the leak arm: the SAME four probes DO see a marker
        # when one is genuinely present, so a clean record is real evidence.
        rec = logging.LogRecord(
            _LOGGER_NAME, logging.WARNING, __file__, 1,
            "leaked %s", (self.MARKER,), None)
        self.assertIn(self.MARKER, rec.getMessage())
        self.assertIn(self.MARKER, repr(rec.args))
        self.assertIn(self.MARKER, repr(rec.__dict__))
        self.assertIn(self.MARKER,
                      logging.Formatter("%(message)s").format(rec))


class TestCallerSeamImportArm(_StateBuilderDegradeBase):
    """RM-312 provably cannot cover a failure of the LAZY IMPORT itself."""

    def test_import_error_is_logged_at_the_caller_seam(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_import_fault()
        self.assertEqual(len(cap.records), 1, cap.output)
        msg = cap.records[0].getMessage()
        self.assertIn("ImportError", msg)
        # The raising frame is the import line in _state_builder itself.
        self.assertIn("_state_builder.py", msg)
        self.assertIn("_read_lcu_snapshot", msg)

    def test_import_error_arm_does_not_touch_rm312_module_state(self):
        # Proof the two seams are independent: the module never loaded, so
        # RM-312's throttle state is untouched by this fault.
        import dashboard._lcu_inprocess as inp

        inp._reset_degrade_log_for_tests()
        with self.assertLogs(_LOGGER_NAME, level="WARNING"):
            self._drive_import_fault()
        self.assertIsNone(inp._degrade_log_state["sig"])


class TestCallerSeamThrottle(_StateBuilderDegradeBase):
    """A persistent fault at ~2 Hz must not flood logs/."""

    def test_two_hundred_identical_faults_emit_exactly_one_warning(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            for _ in range(200):
                out = self._drive_fault(_escape_from_named_helper)
                self.assertIs(out, _RELAY_SENTINEL)
        self.assertEqual(len(cap.records), 1, cap.output)

    def test_a_different_signature_emits_exactly_one_more(self):
        def _other(*_a, **_k):
            raise ValueError("a different fault")

        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            for _ in range(50):
                self._drive_fault(_escape_from_named_helper)
            for _ in range(50):
                self._drive_fault(_other)
        self.assertEqual(len(cap.records), 2, cap.output)
        joined = " ".join(r.getMessage() for r in cap.records)
        self.assertIn("RuntimeError", joined)
        self.assertIn("ValueError", joined)

    def test_throttle_expiry_re_logs_the_same_signature(self):
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_escape_from_named_helper)
            sb._expire_caller_degrade_log_for_tests()
            self._drive_fault(_escape_from_named_helper)
        self.assertEqual(len(cap.records), 2, cap.output)

    def test_reset_helper_clears_the_caller_degrade_state(self):
        self._drive_fault(_escape_from_named_helper)
        sb._reset_caller_degrade_log_for_tests()
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_escape_from_named_helper)
        self.assertEqual(len(cap.records), 1, cap.output)


class TestFlagOffNegativeControl(_StateBuilderDegradeBase):
    """With RC_LCU_INPROCESS unset the seam is DARK - and provably so."""

    def test_flag_unset_logs_nothing_and_returns_the_relay(self):
        env = dict(os.environ)
        env.pop("RC_LCU_INPROCESS", None)
        spy = mock.Mock(name="inprocess_must_not_run")
        with self.assertNoLogs(_LOGGER_NAME, level="DEBUG"):
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(sb, "lcu_summary",
                                      return_value=_RELAY_SENTINEL), \
                    mock.patch(_INPROCESS_MOD + ".lcu_summary_inprocess", spy):
                out = sb._read_lcu_snapshot()
        self.assertIs(out, _RELAY_SENTINEL)
        self.assertFalse(spy.called,
                         "flag unset must not reach the in-process path")

        # POSITIVE CONTROL - same logger, same capture style, DOES catch a
        # record when the fault path is driven, so the assertNoLogs above is a
        # real negative rather than a vacuous one.
        with self.assertLogs(_LOGGER_NAME, level="WARNING") as cap:
            self._drive_fault(_escape_from_named_helper)
        self.assertEqual(len(cap.records), 1, cap.output)

    def test_flag_set_to_other_value_is_also_dark(self):
        spy = mock.Mock(name="inprocess_must_not_run")
        with self.assertNoLogs(_LOGGER_NAME, level="DEBUG"):
            with mock.patch.dict(os.environ, {"RC_LCU_INPROCESS": "0"}), \
                    mock.patch.object(sb, "lcu_summary",
                                      return_value=_RELAY_SENTINEL), \
                    mock.patch(_INPROCESS_MOD + ".lcu_summary_inprocess", spy):
                out = sb._read_lcu_snapshot()
        self.assertIs(out, _RELAY_SENTINEL)
        self.assertFalse(spy.called)


class TestLoggerHelperNeverRaises(_StateBuilderDegradeBase):
    """It runs inside an except clause on a fail-soft path."""

    def test_a_broken_logger_does_not_escape_the_degrade(self):
        def _boom(*_a, **_k):
            raise RuntimeError("logging itself is broken")

        with mock.patch.object(sb.log, "warning", side_effect=_boom):
            out = self._drive_fault(_escape_from_named_helper)
        self.assertIs(out, _RELAY_SENTINEL)

    def test_a_traceback_free_exception_is_tolerated(self):
        # Defensive: _log_... walks exc.__traceback__, which can be None.
        sb._log_inprocess_caller_degrade(RuntimeError("no traceback"))


if __name__ == "__main__":
    unittest.main()
