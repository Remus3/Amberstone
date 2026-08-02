"""RM-131: the 101.qq duo-synergy source gets a drift/staleness probe.

`core/synergy_external_source.py` fails SILENT: on any HTTP error or envelope
shape change `_validate_rows` rejects the payload and the consumer drops back to
the frozen May-25 static seed in `core/smoothed_rates_101qq.py`. Nothing logs,
nothing alarms, and `/api/duo-synergy` keeps serving. Before this row the daily
`RC-UpstreamDriftCheck` task tracked three signals and none of them was qq.

The probe is a SHAPE fingerprint (row-count bucket + first-row key-set hash),
not a value fingerprint. Win rates move every day; a value-sensitive signal
would report drift on every run, which is indistinguishable from reporting
nothing. What must move the signal is the envelope changing or the endpoint
going away - and an unreachable endpoint surfaces as ERR, which is the alarm
this row was filed to get.

Acceptance from the row, in order: (a) None fail-soft on HTTP error without
raising, (b) a changed fingerprint reports changed, (c) an errored probe is
never changed.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import upstream_drift_check as udc  # noqa: E402

# Key set of a real getRankDouble row (core/synergy_external_source.py:17-21).
GOOD_ROW = {
    "championid1": 51, "championid2": 412, "doublewinrate": 0.53,
    "iwinrate1": 0.51, "iwinrate2": 0.50, "itemp1": 1, "irank": 3,
    "lane1": "bottom", "lane2": "support",
}


def _rows(n=200, row=None):
    return [dict(row or GOOD_ROW) for _ in range(n)]


class ProbeRegistrationTests(unittest.TestCase):
    def test_qq_is_a_tracked_signal(self):
        self.assertIn("qq_synergy_shape", udc.FIELD_NAMES)

    def test_baseline_sentinel_carries_the_new_key(self):
        self.assertIn("qq_synergy_shape", udc._null_sentinel())

    def test_queue_catalog_is_also_tracked(self):
        """RM-128 rides the same family; a merge that drops one is caught here."""
        self.assertIn("cdragon_queue_catalog", udc.FIELD_NAMES)


class QqProbeTests(unittest.TestCase):
    def setUp(self):
        udc._LAST_ERRORS["qq_synergy_shape"] = None

    def test_a_http_error_is_fail_soft_none_and_records_the_error(self):
        from core import synergy_external_source as ses

        with mock.patch.object(ses, "fetch_rows",
                               side_effect=ses.SynergyError("HTTP 503")):
            got = udc.probe_qq_synergy_shape()   # must not raise
        self.assertIsNone(got)
        self.assertIn("HTTP 503", udc._LAST_ERRORS["qq_synergy_shape"] or "")

    def test_a_silent_fallback_to_the_seed_is_an_error_not_a_signal(self):
        """fetch_rows returns None on the exact failure this row is about."""
        from core import synergy_external_source as ses

        with mock.patch.object(ses, "fetch_rows", return_value=None):
            got = udc.probe_qq_synergy_shape()
        self.assertIsNone(got)
        self.assertIsNotNone(udc._LAST_ERRORS["qq_synergy_shape"])

    def test_fingerprint_is_stable_across_value_churn(self):
        """Daily win-rate movement must NOT read as drift."""
        from core import synergy_external_source as ses

        day1 = _rows(200)
        day2 = _rows(200, {**GOOD_ROW, "doublewinrate": 0.61, "irank": 9})
        with mock.patch.object(ses, "fetch_rows", return_value=day1):
            fp1 = udc.probe_qq_synergy_shape()
        with mock.patch.object(ses, "fetch_rows", return_value=day2):
            fp2 = udc.probe_qq_synergy_shape()
        self.assertIsNotNone(fp1)
        self.assertEqual(fp1, fp2)

    def test_b_an_envelope_shape_change_reports_changed(self):
        from core import synergy_external_source as ses

        renamed = {**GOOD_ROW}
        renamed["winrate_double"] = renamed.pop("doublewinrate")
        with mock.patch.object(ses, "fetch_rows", return_value=_rows(200)):
            before = udc.probe_qq_synergy_shape()
        with mock.patch.object(ses, "fetch_rows",
                               return_value=_rows(200, renamed)):
            after = udc.probe_qq_synergy_shape()
        self.assertNotEqual(before, after)

        fields = udc.compute_fields(
            {"qq_synergy_shape": before}, {"qq_synergy_shape": after},
            {"qq_synergy_shape": None})
        f = next(x for x in fields if x.name == "qq_synergy_shape")
        self.assertTrue(f.changed)
        self.assertTrue(udc.any_drift(fields))

    def test_a_row_count_collapse_reports_changed(self):
        from core import synergy_external_source as ses

        with mock.patch.object(ses, "fetch_rows", return_value=_rows(200)):
            full = udc.probe_qq_synergy_shape()
        with mock.patch.object(ses, "fetch_rows", return_value=_rows(3)):
            collapsed = udc.probe_qq_synergy_shape()
        self.assertNotEqual(full, collapsed)

    def test_c_an_errored_probe_is_never_changed(self):
        fields = udc.compute_fields(
            {"qq_synergy_shape": "n200+deadbeefdeadbeef"},
            {"qq_synergy_shape": None},
            {"qq_synergy_shape": "SynergyError: HTTP 503"})
        f = next(x for x in fields if x.name == "qq_synergy_shape")
        self.assertFalse(f.changed)
        self.assertFalse(udc.any_drift(fields))

    def test_c_an_errored_probe_carries_the_previous_value_forward(self):
        """Exercises advance_sentinel itself.

        An earlier draft of this test re-implemented the carry-forward
        expression in the test body, so it asserted a thing against itself and
        would have stayed green if upstream_drift_check.py dropped the line.
        Write the real sentinel to a tmp path and read back what production put
        there.
        """
        import tempfile

        previous = {"qq_synergy_shape": "n200+deadbeefdeadbeef",
                    "ddragon_version": "16.15.1"}
        current = {"qq_synergy_shape": None, "ddragon_version": "16.15.1"}
        errors = {"qq_synergy_shape": "SynergyError: HTTP 503"}
        fields = udc.compute_fields(previous, current, errors)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "upstream_drift.json"
            with mock.patch.object(udc, "SENTINEL_PATH", path):
                out = udc.advance_sentinel(previous, current, fields, drift=False)
                on_disk = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(out["qq_synergy_shape"], "n200+deadbeefdeadbeef")
        self.assertEqual(on_disk["qq_synergy_shape"], "n200+deadbeefdeadbeef",
                         "an errored probe erased the sentinel instead of "
                         "carrying the previous value forward")

    def test_a_successful_probe_overwrites_the_sentinel_value(self):
        """Negative control for the test above - carry-forward must not be
        unconditional, or the signal could never advance."""
        import tempfile

        previous = {"qq_synergy_shape": "n200+deadbeefdeadbeef"}
        current = {"qq_synergy_shape": "n200+0123456789abcdef"}
        fields = udc.compute_fields(previous, current, {})
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "upstream_drift.json"
            with mock.patch.object(udc, "SENTINEL_PATH", path):
                out = udc.advance_sentinel(previous, current, fields, drift=True)
        self.assertEqual(out["qq_synergy_shape"], "n200+0123456789abcdef")

    def test_first_run_is_baseline_seeding_not_drift(self):
        fields = udc.compute_fields(
            {"qq_synergy_shape": None}, {"qq_synergy_shape": "n200+abc"},
            {"qq_synergy_shape": None})
        f = next(x for x in fields if x.name == "qq_synergy_shape")
        self.assertFalse(f.changed)


if __name__ == "__main__":
    unittest.main()
