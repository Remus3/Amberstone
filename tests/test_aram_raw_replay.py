"""Pin tools/aram_raw_replay.py - the offline replay of recorded live-Haiku
ARAM responses through the REAL parser.

Why this exists: the Haiku-to-ZERO program compares a deterministic coach
column against the live Haiku column, and the live column has never been
replayable offline. The single blocker was that `coaches/aram_coach.py` wrote
only a truncated prefix of each raw response into the log, so a response whose
`Choices:` line fell past the cut looked identical to a response where the
model never emitted the field at all.

The load-bearing assertion in this file is exactly that distinction: a
truncation-limited record must be reported as TRUNCATED, never folded into the
"model did not emit it" bucket. Conflating the two is the error the replay tool
exists to prevent.

The fixture is authored here rather than read from `logs/` - the real logs
rotate, so a test bound to them would be flaky.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import aram_raw_replay as R  # noqa: E402


# The live logger writes one record per response, newlines flattened to " | ",
# and reports the TRUE character count in the header even when the body that
# follows was clipped. That gap is the truncation signal.
_PREFIX = "17:09:54.377 INFO     rc.coaches.aram      [aram_coach.py:1099] "


def _log_line(declared: int, body: str) -> str:
    flat = body.replace("\n", " | ")
    return f"{_PREFIX}ARAM Haiku raw ({declared} chars): {flat}"


_FULL_BODY = "\n".join([
    "Action: POKE PHASE",
    "Immediate: hold the wave at your tower and trade on cooldown",
    "Fight rule: Orianna ult down; never chase past T1",
    "Reset / item: No. Mortal Reminder 555g short",
    "Risk: Evelynn R one-shot from fog",
    "Item build: Yun Tal Wildarrows, Berserker's Greaves, Infinity Edge",
    "Item extra: omit",
    "Item reasons: Yun Tal=crit baseline; Berserker's=AS breakpoint",
    'Choices: [{"key":"A","label":"poke","confidence":"high"},'
    '{"key":"B","label":"all in","confidence":"low"}]',
])

# Same response, clipped mid-line exactly the way the pre-fix logger clipped
# it: the trailing Choices line never made it into the record, while the header
# still reports the response's true length.
_TRUNCATED_BODY = _FULL_BODY[:300]
_TRUNCATED_DECLARED = len(_FULL_BODY)

# The nastier clip: the Choices line IS in the record but the array was cut
# mid-payload, so it is the log that is malformed, not the model's output.
_CUT_MID_ARRAY_BODY = _FULL_BODY[:_FULL_BODY.index('"confidence":"high"')]

# Neither labeled nor positionally recoverable into anything meaningful.
_MALFORMED_BODY = "I cannot help with that request."

# A complete response that simply omits Choices - the genuine model-omission
# case that must NOT be confused with the truncated one.
_NO_CHOICES_BODY = "\n".join([
    "Action: FALL BACK",
    "Immediate: back off and reset",
    "Fight rule: wait for Briar engage",
    "Risk: Swain drain tank",
])


def _write_fixture(dirpath: Path) -> Path:
    p = dirpath / "fixture.log"
    p.write_text("\n".join([
        _PREFIX + "some unrelated line that must be ignored",
        _log_line(len(_FULL_BODY), _FULL_BODY),
        _log_line(_TRUNCATED_DECLARED, _TRUNCATED_BODY),
        _log_line(len(_FULL_BODY), _CUT_MID_ARRAY_BODY),
        _log_line(len(_MALFORMED_BODY), _MALFORMED_BODY),
        _log_line(len(_NO_CHOICES_BODY), _NO_CHOICES_BODY),
    ]) + "\n", encoding="utf-8")
    return p


class ExtractTests(unittest.TestCase):
    """Record extraction off a log file."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = _write_fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_extracts_only_raw_records(self):
        recs = list(R.iter_raw_records([self.log]))
        self.assertEqual(len(recs), 5)

    def test_unescapes_pipe_back_to_newlines(self):
        recs = list(R.iter_raw_records([self.log]))
        self.assertEqual(recs[0].body, _FULL_BODY)

    def test_declared_length_is_read_from_the_header(self):
        recs = list(R.iter_raw_records([self.log]))
        self.assertEqual(recs[0].declared_chars, len(_FULL_BODY))
        self.assertEqual(recs[1].declared_chars, _TRUNCATED_DECLARED)

    def test_truncation_flag(self):
        recs = list(R.iter_raw_records([self.log]))
        self.assertFalse(recs[0].truncated)
        self.assertTrue(recs[1].truncated)
        self.assertTrue(recs[2].truncated)
        self.assertFalse(recs[3].truncated)

    def test_rotated_log_files_are_discovered(self):
        d = Path(self._tmp.name)
        (d / "2026-08-02.log.3").write_text(
            _log_line(len(_FULL_BODY), _FULL_BODY) + "\n", encoding="utf-8")
        (d / "2026-08-02.log").write_text(
            _log_line(len(_FULL_BODY), _FULL_BODY) + "\n", encoding="utf-8")
        found = R.discover_logs(d)
        names = {p.name for p in found}
        self.assertIn("2026-08-02.log.3", names)
        self.assertIn("2026-08-02.log", names)


class ReplayTests(unittest.TestCase):
    """The replay runs the REAL parser and buckets the outcomes."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = _write_fixture(Path(self._tmp.name))
        self.report = R.replay(R.iter_raw_records([self.log]))

    def tearDown(self):
        self._tmp.cleanup()

    def test_uses_the_real_parser_not_a_reimplementation(self):
        from coaches._base_coach import parse_fields
        from core.coach_output import CoachOutput
        self.assertIs(R.parse_fields, parse_fields)
        self.assertIs(R.CoachOutput, CoachOutput)

    def test_totals(self):
        self.assertEqual(self.report.total, 5)
        self.assertEqual(self.report.truncated, 2)

    def test_full_response_yields_decodable_choices(self):
        self.assertEqual(self.report.choices_decoded, 1)

    def test_choices_survive_the_structured_field_limit(self):
        recs = list(R.iter_raw_records([self.log]))
        out = R.replay_one(recs[0])
        self.assertEqual([c["key"] for c in out.choices], ["A", "B"])

    def test_truncated_record_is_reported_as_truncated_not_as_a_miss(self):
        # The whole point of the slice: "we clipped the evidence" and "the
        # model never emitted it" are different findings.
        self.assertEqual(self.report.choices_missing_truncated, 1)
        self.assertNotIn(
            "truncated", [r.source_kind for r in self.report.clean_misses])

    def test_choices_cut_mid_array_is_blamed_on_the_log_not_the_model(self):
        # Measured on the real 2026-08-02 logs: every recorded response that
        # DID carry a Choices line had its array clipped mid-payload. Counting
        # those as bad model output would be the same conflation one level in.
        self.assertEqual(self.report.choices_undecodable_truncated, 1)
        self.assertEqual(self.report.choices_undecodable_complete, 0)

    def test_genuine_omission_is_counted_separately(self):
        self.assertEqual(self.report.choices_missing_clean, 2)

    def test_malformed_record_does_not_crash_and_is_counted(self):
        self.assertGreaterEqual(self.report.no_fields, 1)

    def test_per_field_yield_is_reported(self):
        self.assertEqual(self.report.field_yield["action"], 4)
        self.assertEqual(self.report.field_yield["choices"], 2)


class CliTests(unittest.TestCase):
    """The tool is runnable and read-only."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = _write_fixture(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_main_returns_zero_and_prints_a_report(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = R.main([str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("truncated", buf.getvalue().lower())

    def test_json_mode_emits_parseable_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            R.main([str(self.log), "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["total"], 5)
        self.assertEqual(payload["choices_missing_truncated"], 1)

    def test_main_leaves_the_input_tree_untouched(self):
        before = {p.name: p.read_bytes()
                  for p in Path(self._tmp.name).iterdir()}
        with redirect_stdout(io.StringIO()):
            R.main([str(self.log)])
        after = {p.name: p.read_bytes()
                 for p in Path(self._tmp.name).iterdir()}
        self.assertEqual(before, after)

    def test_source_opens_nothing_for_writing(self):
        # A replay that mutates runtime data is not a replay. Cheap structural
        # guard so a later edit cannot quietly add a writer.
        src = (ROOT / "tools" / "aram_raw_replay.py").read_text(
            encoding="utf-8")
        for bad in ('"w"', "'w'", '"a"', "'a'", "write_text",
                    "write_bytes", "os.replace"):
            self.assertNotIn(bad, src)


class LoggerCaptureBoundTests(unittest.TestCase):
    """The producing side must record enough of the response to replay it."""

    def test_aram_coach_capture_covers_a_full_haiku_response(self):
        src = (ROOT / "coaches" / "aram_coach.py").read_text(encoding="utf-8")
        self.assertIn("ARAM Haiku raw", src)
        self.assertNotIn('[:600]', src)
        self.assertIn("_RAW_LOG_CHARS", src)
        import coaches.aram_coach as ac
        self.assertGreaterEqual(ac._RAW_LOG_CHARS, 3600)
        # Bounded: an unbounded log line is how a prior sweep found a log-spam
        # problem, so the capture stays a slice, just a sufficient one.
        self.assertLessEqual(ac._RAW_LOG_CHARS, 8000)


if __name__ == "__main__":
    unittest.main()
