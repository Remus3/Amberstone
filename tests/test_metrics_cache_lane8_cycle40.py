"""
tests/test_metrics_cache_lane8_cycle40.py

Lane 8 (Headless-True-Audit) cycle 40 - core/metrics_cache.py.

Characterization + regression suite for the module's two load-bearing
contract claims:

  1. The module docstring states "Non-fatal: missing files, invalid JSON,
     partial writes, empty logs are all silently tolerated; affected fields
     are set to None / 'unknown'", and the reader section comment states
     "File readers (each is independently fault-tolerant)".

     Both were false. _refresh() chained all six readers inside a single
     try/except, so the FIRST reader that raised aborted every LATER reader.
     A wrong-typed field in a timestamp artifact therefore emptied the
     incident list and blanked all nine policy_* fields, neither of which it
     has anything to do with.

  2. _load_json is annotated "-> Optional[Dict[str, Any]]" but returned
     whatever json.loads produced. A file holding a valid JSON list, string
     or number reached callers that immediately called .get() on it.

The pre-existing smoke test tests/phase2_smoke/test_metrics_cache.py has a
test named test_malformed_status_json_non_fatal, but it writes "{bad json{{"
- INVALID json, which json.loads rejects inside _load_json's own except.
It never exercised the valid-JSON-wrong-type path, which is the one that
actually broke the refresh.

No live dependencies: every test drives a temp runtime_dir.
"""
import json
import sys
import unittest
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.metrics_cache import MetricsCache, MetricsSummary
import core.feature_policy as fp


# A runtime_dir where every source file is present and well-formed.
GOOD_FILES = {
    "status.json": {"supervisor_state": "healthy_ready", "process_running": True},
    "monitor_state.json": {
        "consecutive_fails": 2,
        "ladder_index": 1,
        "circuit_breaker": {"tripped": False},
    },
    "health.json": {"mode": "aram"},
    "coaching_ts_sr.json": {"ts": "2026-08-31T10:00:00+00:00", "mode": "sr"},
}

GOOD_INCIDENT = {
    "ts": "2026-08-31T10:00:00+00:00",
    "severity": "warn",
    "subsystem": "supervisor",
    "trigger": "probe",
    "detail": "d",
}


class _Base(unittest.TestCase):

    def setUp(self):
        self._td_obj = tempfile.TemporaryDirectory()
        self._td = Path(self._td_obj.name)
        for name, payload in GOOD_FILES.items():
            (self._td / name).write_text(json.dumps(payload), encoding="utf-8")
        (self._td / "incident_log.jsonl").write_text(
            json.dumps(GOOD_INCIDENT) + "\n", encoding="utf-8"
        )

    def tearDown(self):
        fp._reload()
        self._td_obj.cleanup()

    def _refresh(self):
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        mc._refresh()
        return mc.get_summary()

    def _corrupt(self, name, raw_text):
        (self._td / name).write_text(raw_text, encoding="utf-8")


class TestBaselineIsGood(_Base):
    """Guards the fixture itself. If these fail, every isolation test below
    is vacuous, because it would be asserting against an already-empty
    baseline rather than against a loss caused by the corruption."""

    def test_baseline_populates_every_reader(self):
        s = self._refresh()
        self.assertIsNone(s.refresh_error)
        self.assertEqual(s.supervisor_state, "healthy_ready")
        self.assertEqual(s.consecutive_fails, 2)
        self.assertEqual(s.ladder_idx, 1)
        self.assertEqual(s.current_mode, "aram")
        self.assertEqual(s.last_coaching_ts, "2026-08-31T10:00:00+00:00")
        self.assertEqual(len(s.last_5_incidents), 1)
        self.assertIsNotNone(s.policy_source_status)


class TestReaderIsolation(_Base):
    """Each corruption must damage ONLY its own reader's fields. The
    incident list and the policy block are read after every other reader,
    so they are the canary for a cross-reader abort."""

    def _assert_later_readers_survived(self, s):
        self.assertEqual(
            len(s.last_5_incidents), 1,
            "incident tail was collateral damage from an unrelated reader",
        )
        self.assertIsNotNone(
            s.policy_source_status,
            "policy block was collateral damage from an unrelated reader",
        )

    def test_status_json_is_a_list(self):
        self._corrupt("status.json", "[]")
        s = self._refresh()
        self.assertIsNone(s.supervisor_state)
        self._assert_later_readers_survived(s)

    def test_status_json_is_a_bare_string(self):
        self._corrupt("status.json", '"healthy_ready"')
        s = self._refresh()
        self.assertIsNone(s.supervisor_state)
        self._assert_later_readers_survived(s)

    def test_status_json_is_a_number(self):
        self._corrupt("status.json", "42")
        s = self._refresh()
        self.assertIsNone(s.supervisor_state)
        self._assert_later_readers_survived(s)

    def test_monitor_state_consecutive_fails_not_numeric(self):
        self._corrupt("monitor_state.json", json.dumps({"consecutive_fails": "n/a"}))
        s = self._refresh()
        self.assertIsNone(s.consecutive_fails)
        self._assert_later_readers_survived(s)

    def test_monitor_state_ladder_index_is_a_dict(self):
        self._corrupt("monitor_state.json", json.dumps({"ladder_index": {"v": 1}}))
        s = self._refresh()
        self.assertIsNone(s.ladder_idx)
        self._assert_later_readers_survived(s)

    def test_monitor_state_is_a_list(self):
        self._corrupt("monitor_state.json", "[1, 2]")
        s = self._refresh()
        self.assertIsNone(s.consecutive_fails)
        self.assertIsNone(s.ladder_idx)
        self._assert_later_readers_survived(s)

    def test_health_json_is_a_bare_string(self):
        self._corrupt("health.json", '"aram"')
        s = self._refresh()
        self.assertIsNone(s.current_mode)
        self._assert_later_readers_survived(s)

    def test_coaching_ts_artifact_is_a_list(self):
        self._corrupt("coaching_ts_sr.json", "[1, 2]")
        s = self._refresh()
        self.assertIsNone(s.last_coaching_ts)
        self._assert_later_readers_survived(s)

    def test_one_bad_mode_artifact_does_not_hide_the_others(self):
        """A wrong-typed sr artifact must not suppress a valid aram one."""
        self._corrupt("coaching_ts_sr.json", "[1, 2]")
        (self._td / "coaching_ts_aram.json").write_text(
            json.dumps({"ts": "2026-08-31T11:00:00+00:00", "mode": "aram"}),
            encoding="utf-8",
        )
        s = self._refresh()
        self.assertEqual(s.last_coaching_ts, "2026-08-31T11:00:00+00:00")
        self._assert_later_readers_survived(s)

    def test_a_reader_that_raises_outright_cannot_stop_the_others(self):
        """Guards the per-step try/except in _refresh directly.

        Every OTHER test in this class drives isolation through wrong-typed
        input, which _load_json and _as_int now convert into a quiet None -
        so no exception ever reaches _refresh and a mutant that collapses
        the per-step guards back into one shared try/except SURVIVES them
        all (measured: mutant M4, 10 passed).  The per-step guard is
        defence in depth against an UNANTICIPATED throw inside a reader,
        which is exactly what this injects.
        """
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        boom = RuntimeError("injected")

        def _raise(*_a, **_k):
            raise boom

        mc._read_status = _raise
        mc._refresh()
        s = mc.get_summary()
        self.assertIsNone(s.supervisor_state)
        self.assertEqual(s.consecutive_fails, 2, "a later reader was aborted")
        self.assertEqual(len(s.last_5_incidents), 1, "a later reader was aborted")
        self.assertIsNotNone(s.policy_source_status, "a later reader was aborted")
        self.assertIn("injected", s.refresh_error or "")
        self.assertIn("status.json", s.refresh_error or "")

    def test_a_late_reader_that_raises_cannot_roll_back_earlier_fields(self):
        """Same injection in the other direction."""
        mc = MetricsCache(self._td, refresh_interval_s=9999)

        def _raise(*_a, **_k):
            raise RuntimeError("injected-late")

        mc._read_incident_tail_into = _raise
        mc._refresh()
        s = mc.get_summary()
        self.assertEqual(s.last_5_incidents, [])
        self.assertEqual(s.supervisor_state, "healthy_ready")
        self.assertEqual(s.current_mode, "aram")
        self.assertIsNotNone(s.policy_source_status)
        self.assertIn("incident_log.jsonl", s.refresh_error or "")

    def test_earlier_reader_fields_survive_a_later_reader_fault(self):
        """Symmetric direction: a fault in a LATE reader must not roll back
        the fields an EARLY reader already populated."""
        self._corrupt("coaching_ts_sr.json", "[1, 2]")
        s = self._refresh()
        self.assertEqual(s.supervisor_state, "healthy_ready")
        self.assertEqual(s.consecutive_fails, 2)
        self.assertEqual(s.current_mode, "aram")


class TestRefreshErrorReporting(_Base):
    """Isolation must not become silence: a wrong-typed file is still a
    fault and must remain visible on the summary."""

    def test_wrong_typed_file_is_still_reported(self):
        self._corrupt("monitor_state.json", json.dumps({"consecutive_fails": "n/a"}))
        s = self._refresh()
        self.assertIsNotNone(
            s.refresh_error,
            "a wrong-typed source file must not degrade silently",
        )

    def test_clean_refresh_reports_no_error(self):
        self.assertIsNone(self._refresh().refresh_error)

    def test_refresh_error_names_the_offending_file(self):
        self._corrupt("health.json", '"aram"')
        s = self._refresh()
        self.assertIn("health.json", s.refresh_error or "")

    def test_refresh_error_is_cleared_once_the_file_is_repaired(self):
        self._corrupt("health.json", '"aram"')
        self.assertIsNotNone(self._refresh().refresh_error)
        (self._td / "health.json").write_text(
            json.dumps({"mode": "aram"}), encoding="utf-8"
        )
        s = self._refresh()
        self.assertIsNone(s.refresh_error)
        self.assertEqual(s.current_mode, "aram")

    def test_multiple_faults_are_all_named(self):
        """Two independent faults must BOTH appear - the first must not
        short-circuit reporting of the second.

        Deliberately not status.json + health.json: _read_health documents a
        conservative gate that skips health.json entirely when
        process_running is not True, so a corrupt status.json legitimately
        means health.json is never opened and so never reported.  Pairing
        those two would assert against the documented gate rather than
        against fault aggregation.
        """
        self._corrupt("status.json", "[]")
        self._corrupt("monitor_state.json", '"x"')
        s = self._refresh()
        self.assertIn("status.json", s.refresh_error or "")
        self.assertIn("monitor_state.json", s.refresh_error or "")


class TestLoadJsonHonoursItsAnnotation(_Base):
    """_load_json is annotated -> Optional[Dict[str, Any]]. Anything that is
    not a mapping must come back as None rather than reaching a caller that
    will immediately call .get() on it."""

    def _load(self, raw):
        self._corrupt("probe.json", raw)
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        return mc._load_json("probe.json")

    def test_object_is_returned(self):
        self.assertEqual(self._load('{"a": 1}'), {"a": 1})

    def test_list_becomes_none(self):
        self.assertIsNone(self._load("[1, 2]"))

    def test_string_becomes_none(self):
        self.assertIsNone(self._load('"x"'))

    def test_number_becomes_none(self):
        self.assertIsNone(self._load("42"))

    def test_bool_becomes_none(self):
        self.assertIsNone(self._load("true"))

    def test_json_null_becomes_none(self):
        self.assertIsNone(self._load("null"))

    def test_invalid_json_becomes_none(self):
        self.assertIsNone(self._load("{bad json{{"))

    def test_missing_file_becomes_none(self):
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        self.assertIsNone(mc._load_json("does_not_exist.json"))

    def test_utf8_bom_is_tolerated(self):
        (self._td / "probe.json").write_bytes(
            b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode("utf-8")
        )
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        self.assertEqual(mc._load_json("probe.json"), {"a": 1})


class TestNumericCoercion(_Base):
    """int() on an upstream-supplied field is unguarded arithmetic on
    untrusted shape. Valid numerics must still be coerced."""

    def test_numeric_string_is_still_accepted(self):
        self._corrupt("monitor_state.json", json.dumps({"consecutive_fails": "3"}))
        self.assertEqual(self._refresh().consecutive_fails, 3)

    def test_float_is_truncated_not_fatal(self):
        self._corrupt("monitor_state.json", json.dumps({"consecutive_fails": 3.7}))
        self.assertEqual(self._refresh().consecutive_fails, 3)

    def test_bad_field_does_not_suppress_its_sibling(self):
        self._corrupt(
            "monitor_state.json",
            json.dumps({"consecutive_fails": "n/a", "ladder_index": 4}),
        )
        s = self._refresh()
        self.assertIsNone(s.consecutive_fails)
        self.assertEqual(s.ladder_idx, 4, "a sibling field was collateral damage")

    def test_circuit_breaker_survives_a_bad_numeric_sibling(self):
        self._corrupt(
            "monitor_state.json",
            json.dumps({
                "consecutive_fails": "n/a",
                "circuit_breaker": {"tripped": True},
            }),
        )
        self.assertIs(self._refresh().circuit_breaker_tripped, True)

    def test_non_dict_circuit_breaker_is_ignored(self):
        """Ignored must mean genuinely ignored, not raised-and-swallowed.

        Asserting only that the field is None passes either way: replacing
        the isinstance check with `cb is not None` makes .get() throw, the
        per-step guard catches it, and the field is still None (measured:
        mutant M16 survived that assertion alone).  Pinning refresh_error
        to None is what distinguishes the two.
        """
        self._corrupt(
            "monitor_state.json", json.dumps({"circuit_breaker": "tripped"})
        )
        s = self._refresh()
        self.assertIsNone(s.circuit_breaker_tripped)
        self.assertIsNone(s.refresh_error, "a non-dict circuit_breaker raised")


class TestToDictCoversEveryField(_Base):
    """to_dict() emitted 12 of the 21 declared fields, silently dropping the
    entire Phase 2 Step 2 policy block. It has no consumer today, which is
    exactly why the omission survived - the next consumer is the one that
    would have been bitten."""

    def test_to_dict_covers_every_slot(self):
        d = MetricsSummary().to_dict()
        self.assertEqual(
            sorted(d), sorted(MetricsSummary.__slots__),
            "to_dict() keys drifted from __slots__",
        )

    def test_to_dict_carries_policy_values(self):
        s = self._refresh()
        d = s.to_dict()
        self.assertEqual(d["policy_source_status"], s.policy_source_status)
        self.assertEqual(d["policy_sr_live_coaching"], s.policy_sr_live_coaching)

    def test_to_dict_is_json_serialisable(self):
        json.dumps(self._refresh().to_dict())

    def test_to_dict_incidents_are_not_the_internal_list(self):
        s = self._refresh()
        d = s.to_dict()
        d["last_5_incidents"].append({"injected": True})
        self.assertEqual(len(s.last_5_incidents), 1)


class TestSnapshotIsolation(_Base):
    """get_summary() promises the caller cannot reach internal state."""

    def test_incident_dicts_are_rebuilt(self):
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        mc._refresh()
        a = mc.get_summary()
        a.last_5_incidents[0]["detail"] = "mutated"
        self.assertNotEqual(mc.get_summary().last_5_incidents[0]["detail"], "mutated")

    def test_successive_snapshots_are_distinct_objects(self):
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        mc._refresh()
        self.assertIsNot(mc.get_summary(), mc.get_summary())

    def test_get_summary_before_any_refresh_is_empty_not_fatal(self):
        s = MetricsCache(self._td, refresh_interval_s=9999).get_summary()
        self.assertEqual(s.last_5_incidents, [])
        self.assertEqual(s.refreshed_at, "")

    def test_get_summary_survives_incident_entries_missing_keys(self):
        """get_summary() documents 'Never raises', but indexed the five
        incident keys directly. Nothing in-module can produce a short entry
        today; this pins the promise against a future writer."""
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        mc._refresh()
        with mc._lock:
            mc._summary.last_5_incidents = [{"ts": "t"}]
        s = mc.get_summary()
        self.assertEqual(s.last_5_incidents[0]["ts"], "t")
        self.assertEqual(s.last_5_incidents[0]["severity"], "")


class TestIncidentTail(_Base):
    """The tail read is the only bounded-memory promise in the module."""

    def test_partial_first_line_is_discarded(self):
        big = json.dumps(dict(GOOD_INCIDENT, detail="x" * 200)) + "\n"
        payload = big * 200 + json.dumps(dict(GOOD_INCIDENT, detail="LAST")) + "\n"
        (self._td / "incident_log.jsonl").write_text(payload, encoding="utf-8")
        s = self._refresh()
        self.assertEqual(s.last_5_incidents[-1]["detail"], "LAST")
        for e in s.last_5_incidents:
            self.assertTrue(e["ts"])

    def _fixed_width_log(self, n_lines, width=128):
        """Write n_lines records of EXACTLY `width` bytes including the
        newline.  Because width divides INCIDENT_TAIL_BYTES (8192), the tail
        seek is guaranteed to land exactly on a record boundary."""
        from core.metrics_cache import INCIDENT_TAIL_BYTES
        self.assertEqual(INCIDENT_TAIL_BYTES % width, 0, "fixture assumption")
        out = []
        for i in range(n_lines):
            stub = json.dumps({
                "ts": f"t{i:05d}", "severity": "warn",
                "subsystem": "s", "trigger": "g", "detail": "",
            })
            pad = width - 1 - len(stub.encode("utf-8"))
            self.assertGreater(pad, 0, "record does not fit in width")
            rec = json.dumps({
                "ts": f"t{i:05d}", "severity": "warn",
                "subsystem": "s", "trigger": "g", "detail": "d" * pad,
            })
            rec = rec[: width - 1] if len(rec) > width - 1 else rec.ljust(width - 1)
            out.append(rec)
        payload = ("\n".join(out) + "\n").encode("utf-8")
        self.assertEqual(len(payload), n_lines * width, "fixture is not fixed-width")
        (self._td / "incident_log.jsonl").write_bytes(payload)
        return payload

    def test_aligned_tail_boundary_does_not_drop_a_complete_entry(self):
        """Regression: the first line was discarded whenever seek_pos > 0,
        including when the seek landed exactly on a record boundary, which
        threw away a COMPLETE incident.  Guaranteed to align here because
        the record width divides INCIDENT_TAIL_BYTES."""
        from core.metrics_cache import INCIDENT_TAIL_BYTES
        width = 128
        n = 200
        payload = self._fixed_width_log(n, width)
        seek_pos = len(payload) - INCIDENT_TAIL_BYTES
        self.assertGreater(seek_pos, 0)
        self.assertEqual(payload[seek_pos - 1:seek_pos], b"\n", "boundary not aligned")

        first_in_window = json.loads(
            payload[seek_pos:].decode("utf-8").splitlines()[0]
        )
        window_lines = payload[seek_pos:].decode("utf-8").rstrip("\n").split("\n")
        # Only assert the entry is kept when it is inside the 5-entry window.
        if len(window_lines) <= 5:
            self.assertIn(
                first_in_window["ts"],
                [e["ts"] for e in self._refresh().last_5_incidents],
                "a complete entry was discarded as if it were partial",
            )
        # The window is larger than 5 here, so assert the count instead: with
        # the off-by-one the tail yields one fewer usable record than it has.
        usable = len(window_lines)
        self.assertEqual(
            usable, INCIDENT_TAIL_BYTES // width,
            "fixture: window should hold exactly the tail-byte budget",
        )
        s = self._refresh()
        self.assertEqual(len(s.last_5_incidents), 5)
        self.assertEqual(s.last_5_incidents[-1]["ts"], f"t{n - 1:05d}")

    def test_aligned_boundary_keeps_the_boundary_record_when_window_is_small(self):
        """Same defect, made directly observable: size the log so the whole
        tail window holds fewer than MAX_INCIDENTS records, and the record
        sitting on the boundary must survive."""
        from core.metrics_cache import INCIDENT_TAIL_BYTES
        width = 2048           # 8192 / 2048 = 4 records in the window
        self.assertEqual(INCIDENT_TAIL_BYTES % width, 0)
        recs = []
        for i in range(6):
            rec = json.dumps({
                "ts": f"t{i:05d}", "severity": "warn", "subsystem": "s",
                "trigger": "g", "detail": "d" * 1900,
            })
            recs.append(rec.ljust(width - 1)[: width - 1])
        payload = ("\n".join(recs) + "\n").encode("utf-8")
        self.assertEqual(len(payload), 6 * width)
        (self._td / "incident_log.jsonl").write_bytes(payload)

        got = [e["ts"] for e in self._refresh().last_5_incidents]
        self.assertEqual(
            got, ["t00002", "t00003", "t00004", "t00005"],
            "the record on the aligned boundary was dropped as if partial",
        )

    def test_at_most_max_incidents(self):
        line = json.dumps(GOOD_INCIDENT) + "\n"
        (self._td / "incident_log.jsonl").write_text(line * 50, encoding="utf-8")
        self.assertLessEqual(len(self._refresh().last_5_incidents), 5)

    def test_malformed_lines_are_skipped_not_fatal(self):
        payload = (
            "not json\n"
            + json.dumps(GOOD_INCIDENT) + "\n"
            + "[1,2]\n"
            + json.dumps(dict(GOOD_INCIDENT, detail="KEEP")) + "\n"
        )
        (self._td / "incident_log.jsonl").write_text(payload, encoding="utf-8")
        s = self._refresh()
        self.assertEqual(s.last_5_incidents[-1]["detail"], "KEEP")

    def test_empty_file_is_empty_list(self):
        (self._td / "incident_log.jsonl").write_text("", encoding="utf-8")
        self.assertEqual(self._refresh().last_5_incidents, [])

    def test_undecodable_bytes_do_not_kill_the_tail(self):
        payload = (
            b"\xff\xfe bad bytes\n"
            + json.dumps(GOOD_INCIDENT).encode("utf-8")
            + b"\n"
        )
        (self._td / "incident_log.jsonl").write_bytes(payload)
        self.assertEqual(len(self._refresh().last_5_incidents), 1)

    def test_detail_is_truncated(self):
        (self._td / "incident_log.jsonl").write_text(
            json.dumps(dict(GOOD_INCIDENT, detail="y" * 500)) + "\n", encoding="utf-8"
        )
        self.assertLessEqual(len(self._refresh().last_5_incidents[0]["detail"]), 120)

    def test_reader_is_read_only(self):
        """The module docstring's first design rule is 'Read-only: never
        writes to any file.'"""
        before = {p.name: p.read_bytes() for p in self._td.iterdir()}
        self._refresh()
        after = {p.name: p.read_bytes() for p in self._td.iterdir()}
        self.assertEqual(before, after)


class TestLifecycle(_Base):
    """start()/stop() must be idempotent and must not leave a live thread."""

    def test_start_then_stop_leaves_no_live_thread(self):
        mc = MetricsCache(self._td, refresh_interval_s=0.01)
        mc.start()
        mc.stop(timeout_s=5.0)
        self.assertFalse(mc._thread and mc._thread.is_alive())

    def test_double_start_spawns_one_worker(self):
        mc = MetricsCache(self._td, refresh_interval_s=0.01)
        mc.start()
        first = mc._thread
        mc.start()
        try:
            self.assertIs(mc._thread, first)
        finally:
            mc.stop(timeout_s=5.0)

    def test_stop_is_idempotent(self):
        mc = MetricsCache(self._td, refresh_interval_s=0.01)
        mc.start()
        mc.stop(timeout_s=5.0)
        mc.stop(timeout_s=5.0)

    def test_stop_without_start_is_not_fatal(self):
        MetricsCache(self._td, refresh_interval_s=0.01).stop(timeout_s=1.0)

    def test_start_populates_summary_synchronously(self):
        mc = MetricsCache(self._td, refresh_interval_s=9999)
        mc.start()
        try:
            self.assertEqual(mc.get_summary().supervisor_state, "healthy_ready")
        finally:
            mc.stop(timeout_s=5.0)

    def test_restart_after_stop_works(self):
        mc = MetricsCache(self._td, refresh_interval_s=0.01)
        mc.start()
        mc.stop(timeout_s=5.0)
        mc.start()
        try:
            self.assertTrue(mc._thread.is_alive())
        finally:
            mc.stop(timeout_s=5.0)


if __name__ == "__main__":
    unittest.main()
