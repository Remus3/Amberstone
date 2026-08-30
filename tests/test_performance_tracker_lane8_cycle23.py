"""Lane 8 Headless-True-Audit cycle 23 - performance_tracker.py.

Target picked on criterion 2 (secret-adjacent: it reads API-Key-Claude.txt at
:406 and passes the value into experimental_builder.record_result at :418) and
criterion 4 (load-bearing with no dedicated test module of its own).

Two defect classes are pinned here.

W1 - the private atomic writer was NOT hardened against the Windows
PermissionError that the repo's own canonical helper exists to absorb.
``performance_tracker._atomic_write_json`` ended in a BARE ``os.replace``.
``core/polled_json.py:30-35`` records that os.replace transiently raises
PermissionError (WinError 5) on Windows whenever a concurrent reader holds the
destination open, that these files are polled by design so the contention is
routine, and that the same retry was already applied to
ops/rc_supervisor.atomic_write_json back on 2026-05-02. performance_tracker
held a PRIVATE COPY that missed that fix - the resolver-vs-consumer split.

The reader is real and cross-process: agents/supervisor.py:794-805 imports
performance_tracker._latest_rating_file and read_text()s the winning file, and
ops/phase3_install.ps1:57 launches that supervisor as its own process.

The failure was triple-masked, which is why it could sit here:
  1. the write raise is caught at :361 and only WARNED,
  2. control falls THROUGH, so the MatchDB row at :386 is still written and
     app/_game_lifecycle.py:236 then logs "Performance rating saved",
  3. the stale file keeps its stale mtime, so _latest_rating_file still picks
     it and the post-game summary silently enriches from a PRIOR game.

W2 - every numeric field was read with ``.get(key, default)``, which supplies
the default only for a MISSING key and passes a present-but-null value straight
through. Six fields then crash save_rating with a TypeError. The callers at
app/_game_lifecycle.py:201 and :230 wrap the call in ``except Exception``, so a
single null from the upstream feed silently costs the user BOTH the rating file
and the match_history.db row. app/_game_lifecycle.py is a FROZEN file, so the
coercion belongs here at the boundary, which is the correct place regardless.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import performance_tracker as pt  # noqa: E402
from core.polled_json import _REPLACE_RETRY_DELAYS_S as _DELAYS  # noqa: E402
from tests._replace_faults import replace_fails  # noqa: E402


def _seed(target: Path, marker: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"marker": marker}), encoding="utf-8")


class TestAtomicWriteUnderConcurrentReader(unittest.TestCase):
    """W1: the polled rating file has a cross-process reader."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp(prefix="rc_l8c23_")
        self.target = Path(self._tmpdir) / "last_sr.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_write_survives_a_transient_concurrent_reader(self):
        """The routine case: a poller holds the file open, then releases.

        This is the discriminator between the bare os.replace and the
        retry-backed one. Measured on Python 3.14 / win32 when this guard was
        written: the bare writer raised PermissionError [WinError 5] in under a
        millisecond, while the retry-backed writer rode out an 80 ms reader and
        landed its content.

        LANE 8 CYCLE 26 - the fault is now INJECTED at the os.replace boundary
        instead of BORROWED from the operating system. The original shape held
        the destination open on a background thread and relied on the Windows
        share lock to manufacture the PermissionError. POSIX renames straight
        through an open read handle, so on Linux no fault ever occurred and
        this test asserted a success that needed no retry at all: vacuously
        green on the one platform where the retry loop had never run. Two
        failures then a success drives the real backoff on every platform.
        """
        _seed(self.target, "OLD")
        with replace_fails(self.target, times=2) as rec:
            pt._atomic_write_json(self.target, {"marker": "NEW"})

        self.assertEqual(rec.failures, 2)
        self.assertEqual(rec.attempts, 3,
                         "the writer did not re-attempt after a transient "
                         "PermissionError; the retry loop was not exercised")
        on_disk = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(
            on_disk.get("marker"), "NEW",
            "the rating write was lost to a routine concurrent reader; the "
            "file still holds the previous game's content",
        )
        self.assertEqual(list(self.target.parent.glob("*.tmp")), [],
                         "a retried write must not leave a scratch file")

    def test_no_orphaned_tmp_when_the_write_cannot_land(self):
        """Under PERMANENT contention the write must still fail loudly, but it
        must not litter a .tmp beside the target.

        Deliberately NOT asserting success here - the retry buys the transient
        window only, exactly as core/polled_json.py:30-35 claims, and pinning a
        stronger promise than the mechanism makes would be a false guard.

        LANE 8 CYCLE 26 - the fault is now INJECTED rather than borrowed from
        the OS. Held open, this test was RED on Linux ("PermissionError not
        raised") because POSIX lets the rename through, which is also why the
        exhaustion branch of _replace_with_retry had never executed there.
        """
        _seed(self.target, "OLD")
        with replace_fails(self.target) as rec:
            with self.assertRaises(PermissionError):
                pt._atomic_write_json(self.target, {"marker": "NEW"})

        self.assertEqual(
            rec.attempts, len(_DELAYS) + 1,
            "a permanently failing replace must be attempted once per entry "
            "in core/polled_json._REPLACE_RETRY_DELAYS_S, plus the initial "
            "attempt, before the re-raise. Derived rather than hardcoded so a "
            "deliberate change to the backoff table does not present as a "
            "regression here.",
        )
        strays = list(self.target.parent.glob("*.tmp"))
        self.assertEqual(
            strays, [],
            f"orphaned tmp left behind after an exhausted retry: {strays}",
        )
        on_disk = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(on_disk.get("marker"), "OLD",
                         "a failed write must leave the prior file intact")

    @unittest.skipUnless(
        sys.platform == "win32",
        "POSIX rename ignores an open read handle; there is no OS fault to "
        "observe here, which is exactly why the tests above inject their own")
    def test_a_held_read_handle_really_blocks_replace_on_this_os(self):
        """The narrow question the portable tests can no longer answer.

        They simulate the share lock, so something has to prove the simulated
        condition is REAL on the platform RC actually ships on. This asserts
        the OS property alone - no writer, no retry loop - so it stays true
        whatever core/polled_json does next. If it ever goes red on win32, the
        premise of the whole retry loop is gone and the injected-fault tests
        above are testing a fiction.
        """
        _seed(self.target, "OLD")
        scratch = self.target.with_name("os_probe.scratch")
        scratch.write_text("NEW", encoding="utf-8")
        with open(self.target, encoding="utf-8"):
            with self.assertRaises(PermissionError):
                os.replace(scratch, self.target)
        scratch.unlink()

    def test_rejects_non_finite_values_before_touching_disk(self):
        """Pre-existing contract (P2-W4 hw2 slice H) - keep it pinned.

        allow_nan=False must raise BEFORE the tmp file is written, so a
        degenerate upstream cs_per_min drops the one bad rating instead of
        serializing bare Infinity/NaN tokens that the dashboard rejects.
        """
        _seed(self.target, "OLD")
        with self.assertRaises(ValueError):
            pt._atomic_write_json(self.target, {"cs_per_min": float("inf")})
        self.assertEqual(list(self.target.parent.glob("*.tmp")), [],
                         "a rejected payload must not leave a tmp behind")
        on_disk = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(on_disk.get("marker"), "OLD")


class TestSaveRatingSurvivesNullFields(unittest.TestCase):
    """W2: a present-but-null field must not cost the user the whole save."""

    BASE = {
        "game_mode": "CLASSIC", "game_seconds": 1200, "cs_per_min": 6.0,
        "deaths": 3, "kills": 5, "assists": 7, "gold": 12000, "kda": "5/3/7",
    }

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp(prefix="rc_l8c23_sr_")
        # _get_db caches globally; keep the audit off the real match DB.
        self._saved_db = pt._match_db
        pt._match_db = None

    def tearDown(self):
        import shutil
        pt._match_db = self._saved_db
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _call(self, field, akt=10):
        gs = dict(self.BASE)
        if field == "ally_kills_total":
            akt = None
        else:
            gs[field] = None
        return pt.save_rating(self._tmpdir, "Ahri", gs, akt)

    def test_null_numeric_fields_do_not_raise(self):
        """All six measured crashers. Each was a TypeError that the frozen
        caller swallowed, silently costing the rating file AND the DB row."""
        for field in ("ally_kills_total", "cs_per_min", "gold",
                      "game_seconds", "deaths", "kills"):
            with self.subTest(field=field):
                try:
                    grade, notes = self._call(field)
                except TypeError as exc:
                    self.fail(
                        f"a null '{field}' crashed save_rating ({exc}); the "
                        "caller's except Exception then drops the rating and "
                        "the match row with no user-visible signal"
                    )
                self.assertIsInstance(grade, str)
                self.assertIsInstance(notes, list)

    def test_a_null_field_still_produces_a_real_grade(self):
        """Not merely 'does not raise' - a null in one metric must still yield
        a graded, persisted rating rather than the ('', []) early-out that
        means 'this match was not rateable'."""
        grade, _notes = self._call("cs_per_min")
        self.assertIn(grade, ("S", "A", "B", "C", "D", "F"))
        written = Path(self._tmpdir) / "data" / "ratings" / "last_sr.json"
        self.assertTrue(written.exists(),
                        "the rating file was not written for a null field")
        payload = json.loads(written.read_text(encoding="utf-8"))
        self.assertEqual(payload["rating"], grade)
        self.assertEqual(payload["stats"]["cs_per_min"], 0,
                         "a null metric should read as 0, matching the value "
                         "a MISSING key already produces via .get(k, 0)")

    def test_null_and_missing_agree(self):
        """The whole point: .get(k, default) already handles the missing case.
        A null value must land on the same grade, or the two spellings of
        'no data' disagree."""
        missing = dict(self.BASE)
        del missing["cs_per_min"]
        g_missing, _ = pt.save_rating(self._tmpdir, "Ahri", missing, 10)
        g_null, _ = self._call("cs_per_min")
        self.assertEqual(g_missing, g_null)


class TestSaveTftRatingSurvivesNullFields(unittest.TestCase):
    """W2 SIBLING - the same root cause in save_tft_rating.

    Found by grepping the module for other feed-supplied numeric reads after
    the save_rating fix, which is the step item 208/213 records skipping: a
    first fix that is too narrow. TFT is the highest-volume mode in the store
    (8041 of 8395 match_history.db rows on the live box), so the sibling is
    the bigger exposure of the two, not an afterthought.

    The `stage` case carries its own trap. It is reachable ONLY when
    `stage_round` fails to parse, because a parsed stage_round leaves `sn`
    truthy and the tft_coaching fallback never runs. Probing with a
    well-formed stage_round reports OK and hides the crash.
    """

    LIVE = {"last_round_result": "", "stage_round": "4-2", "level": 8,
            "traits_active": [], "board_units": [], "augments": []}
    COACH = {"variant": "standard", "alive_others": 3, "stage": 4,
             "game_time_s": 1800, "level": 8}

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.mkdtemp(prefix="rc_l8c23_tft_")
        self._saved_db = pt._match_db
        pt._match_db = None

    def tearDown(self):
        import shutil
        pt._match_db = self._saved_db
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_null_alive_others_does_not_raise(self):
        coach = dict(self.COACH, alive_others=None)
        try:
            grade, notes = pt.save_tft_rating(
                self._tmpdir, dict(self.LIVE), coach)
        except TypeError as exc:
            self.fail(f"a null alive_others crashed save_tft_rating ({exc})")
        self.assertIsInstance(grade, str)
        self.assertIsInstance(notes, list)

    def test_null_stage_does_not_raise_on_the_fallback_path(self):
        """Empty stage_round forces the tft_coaching['stage'] fallback."""
        live = dict(self.LIVE, stage_round="")
        coach = dict(self.COACH, stage=None)
        try:
            grade, notes = pt.save_tft_rating(self._tmpdir, live, coach)
        except TypeError as exc:
            self.fail(f"a null stage crashed save_tft_rating ({exc})")
        self.assertIsInstance(grade, str)
        self.assertIsInstance(notes, list)

    def test_other_null_coaching_fields_stay_safe(self):
        """Regression fence for the fields that were ALREADY null-safe, so a
        later refactor cannot quietly remove the `or 0` / falsy guards that
        make them so."""
        for field in ("game_time_s", "level", "variant"):
            with self.subTest(field=field):
                coach = dict(self.COACH)
                coach[field] = None
                grade, _notes = pt.save_tft_rating(
                    self._tmpdir, dict(self.LIVE), coach)
                self.assertIsInstance(grade, str)


class TestNumCoercion(unittest.TestCase):
    """Direct unit cover for _num.

    Added because the bool branch SURVIVED mutation M8: replacing
    ``if isinstance(value, bool)`` with ``if False`` left every other test
    green. That is not an equivalent mutant - it changes _num(True) from the
    default to True, which then arithmetics as 1 - so the guard needed a test
    rather than the benefit of the doubt.
    """

    def test_passes_real_numbers_through_unchanged(self):
        self.assertEqual(pt._num(7), 7)
        self.assertEqual(pt._num(6.5), 6.5)
        self.assertEqual(pt._num(0), 0)
        self.assertEqual(pt._num(-3), -3)

    def test_null_yields_the_supplied_default(self):
        self.assertEqual(pt._num(None), 0)
        self.assertEqual(pt._num(None, 1), 1)

    def test_bool_is_rejected_rather_than_arithmetic_as_one(self):
        """A bool where a metric was expected is wrong input. Python would
        otherwise silently treat True as 1 and False as 0."""
        self.assertEqual(pt._num(True), 0)
        self.assertEqual(pt._num(True, 1), 1)
        self.assertEqual(pt._num(False), 0)

    def test_numeric_strings_are_accepted(self):
        """The upstream feed is JSON RC does not author; a quoted number is a
        shape it has produced before."""
        self.assertEqual(pt._num("12000"), 12000.0)
        self.assertEqual(pt._num("6.5"), 6.5)

    def test_garbage_falls_back_to_the_default(self):
        for junk in ("", "n/a", [], {}, object()):
            with self.subTest(junk=repr(junk)):
                self.assertEqual(pt._num(junk, 4), 4)


class TestSecretIsNeverLogged(unittest.TestCase):
    """4b: the API key read at :406 must not reach a log record.

    The outer handler at :419-420 logs the exception from record_result. If
    that exception text can carry the key, the key lands in logs/.
    """

    def test_a_raising_record_result_cannot_put_the_key_in_the_log(self):
        import logging
        fake_key = "sk-ant-FAKE-TESTKEY-lane8-cycle23"
        import tempfile
        tmpdir = tempfile.mkdtemp(prefix="rc_l8c23_key_")
        try:
            (Path(tmpdir) / "API-Key-Claude.txt").write_text(
                fake_key, encoding="utf-8")

            records = []

            class _Capture(logging.Handler):
                def emit(self, record):
                    records.append(record.getMessage())
                    try:
                        records.append(str(record.exc_info))
                    except Exception:  # noqa: BLE001
                        pass

            handler = _Capture()
            logger = logging.getLogger("rc.tracker")
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)

            import coaches.experimental_builder as eb
            saved_consume = eb.consume_active
            saved_record = eb.record_result

            def _fake_consume():
                return {"champion": "Ahri"}

            def _boom(champion, grade, gs, api_key):
                # The realistic leak shape: a client that echoes the
                # credential it was handed into the error text.
                raise RuntimeError(f"401 unauthorized for key={api_key}")

            eb.consume_active = _fake_consume
            eb.record_result = _boom
            saved_db = pt._match_db
            pt._match_db = None
            try:
                pt.save_rating(tmpdir, "Ahri", {
                    "game_mode": "CLASSIC", "game_seconds": 1200,
                    "cs_per_min": 6.0, "deaths": 3, "kills": 5,
                    "assists": 7, "gold": 12000, "kda": "5/3/7",
                }, 10)
            finally:
                pt._match_db = saved_db
                eb.consume_active = saved_consume
                eb.record_result = saved_record
                logger.removeHandler(handler)

            joined = " ".join(records)
            self.assertNotIn(
                fake_key, joined,
                "the API key reached a log record via the exception text",
            )
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
