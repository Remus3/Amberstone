# arch: s144 true-audit regressions for the recording route (Range digits, mid-stream errors, stalled writer, strict JSON) | section=tests | frozen=no
"""s144 true-audit of dashboard/routes_recordings.py.

One regression per finding, each mutation-tested against the production line
it guards:

  F1  a Range header whose digit run passes CPython's int-from-str limit
      (4300 digits) raised ValueError out of parse_range, and the route
      answered 500 instead of 206 / 416 / the full body. Non-ASCII decimal
      digits and non-ASCII whitespace were also accepted by the str-pattern
      ``\\d`` / ``\\s``.
  F2  an error AFTER the 200/206 headers went out fell through to the route's
      catch-all, which wrote a SECOND HTTP response (a JSON 500) into the
      video body the client was still counting bytes of.
  F3  a client that stopped reading (a paused <video>, a dead tab) blocked
      the handler thread in wfile.write forever, holding the recording open;
      the copy now arms a bounded per-write socket timeout and restores the
      prior one.
  F4  a non-finite number in a sidecar (json.loads accepts NaN / Infinity)
      was re-emitted verbatim, so the summary reply was not strict JSON and
      the browser's JSON.parse rejected the whole payload.
  F5  the catch-all logged only the exception CLASS name, so a real failure
      left nothing to diagnose; it now logs the traceback (logs only - the
      reply still carries no path and no message).

Synthetic throughout: temp dirs, temp files, a fake handler. Non-ASCII code
points are built with chr() so this source stays 7-bit ASCII.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_recordings as rr

PAYLOAD = bytes(range(256)) * 40  # 10240 bytes

ARABIC_INDIC_ONE = chr(0x0661)  # a Unicode decimal digit (category Nd)
NBSP = chr(0x00A0)  # latin-1 no-break space: str \s matches it
NEL = chr(0x0085)  # latin-1 next-line: str \s matches it


def _strict_loads(raw: bytes):
    def _refuse(tok):
        raise ValueError(f"non-strict JSON constant {tok}")
    return json.loads(raw, parse_constant=_refuse)


class _Conn:
    """A socket stand-in that records every settimeout call."""

    def __init__(self, prior=None):
        self.timeout = prior
        self.calls: list = []

    def gettimeout(self):
        return self.timeout

    def settimeout(self, v):
        self.calls.append(v)
        self.timeout = v


class _Handler:
    def __init__(self, path: str, headers: dict | None = None, conn=None, wfile=None):
        self.path = path
        self.headers = dict(headers or {})
        self.status: int | None = None
        self.out_headers: dict[str, str] = {}
        self.wfile = wfile if wfile is not None else BytesIO()
        self.close_connection = False
        self.json_calls: list = []
        if conn is not None:
            self.connection = conn

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, k: str, v: str) -> None:
        self.out_headers[k] = v

    def end_headers(self) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str, cache_control=None) -> None:
        self.json_calls.append((code, body))


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_rec_s144_"))
        self.rec_dir = self.tmp / "recordings"
        self.rec_dir.mkdir()
        self.video = self.tmp / "game.mp4"
        self.video.write_bytes(PAYLOAD)
        p = patch.object(rr, "RECORDINGS_DIR", self.rec_dir)
        p.start()
        self.addCleanup(p.stop)
        env = patch.dict(os.environ, {"RC_DASH_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sidecar_text(self, mid: str, text: str) -> None:
        (self.rec_dir / f"{mid}.json").write_bytes(text.encode("ascii"))

    def sidecar(self, mid: str, **extra) -> None:
        body = {"status": "final", "owner": "rc", "obs_output_path": str(self.video),
                "game_time_offset_s": 31.5, "death_count": 0, "bookmarks": []}
        body.update(extra)
        self.sidecar_text(mid, json.dumps(body))

    def serve(self, h: _Handler) -> _Handler:
        rr._serve_recordings(h)
        return h


# ---------------------------------------------------------------- F1
class RangeDigitLimitTests(unittest.TestCase):
    BIG = 5000  # past CPython's 4300-digit int-from-str limit

    def test_leading_zero_run_is_still_zero(self):
        self.assertEqual(rr.parse_range("bytes=" + "0" * self.BIG + "-", 100), (0, 99))
        self.assertEqual(rr.parse_range("bytes=" + "0" * self.BIG + "7-8", 100), (7, 8))

    def test_huge_end_clamps_to_the_file(self):
        self.assertEqual(rr.parse_range("bytes=10-" + "9" * self.BIG, 100), (10, 99))

    def test_huge_suffix_is_the_whole_file(self):
        self.assertEqual(rr.parse_range("bytes=-" + "9" * self.BIG, 100), (0, 99))

    def test_huge_start_is_unsatisfiable(self):
        self.assertEqual(rr.parse_range("bytes=" + "9" * self.BIG + "-", 100),
                         rr.UNSATISFIABLE)
        self.assertEqual(rr.parse_range("bytes=" + "1" + "0" * 30 + "-", 100),
                         rr.UNSATISFIABLE)

    def test_end_before_start_compares_real_magnitudes(self):
        # Both beyond any file size, end smaller than start -> invalid ->
        # ignored (full body), not a 416 from comparing two capped values.
        self.assertIsNone(rr.parse_range("bytes=" + "9" * 40 + "-" + "9" * 30, 100))
        # Leading zeros do not make an end larger than its start.
        self.assertIsNone(rr.parse_range("bytes=50-" + "0" * 30 + "49", 100))
        self.assertEqual(rr.parse_range("bytes=50-" + "0" * 30 + "50", 100), (50, 50))

    def test_non_ascii_decimal_digits_are_not_digits(self):
        # U+0661 ARABIC-INDIC DIGIT ONE matches a str-pattern \d and int()
        # accepts it; a Range header is ASCII by grammar.
        self.assertIsNone(rr.parse_range("bytes=" + ARABIC_INDIC_ONE + "-", 100))
        self.assertIsNone(rr.parse_range("bytes=-" + ARABIC_INDIC_ONE, 100))

    def test_non_ascii_whitespace_is_not_ows(self):
        # http.client decodes headers as latin-1, so U+00A0 / U+0085 can
        # arrive; the Range grammar's whitespace is SP / HTAB only.
        self.assertIsNone(rr.parse_range("bytes" + NBSP + "=0-5", 100))
        self.assertIsNone(rr.parse_range(NEL + "bytes=0-5", 100))
        self.assertIsNone(rr.parse_range("bytes=0" + NBSP + "-5", 100))
        self.assertEqual(rr.parse_range("bytes =\t0 - 5", 100), (0, 5))


class RangeDigitLimitRouteTests(_Base):
    def test_route_answers_206_not_500(self):
        self.sidecar("123")
        h = self.serve(_Handler("/api/recordings/123/video",
                                {"Range": "bytes=" + "0" * 5000 + "-3"}))
        self.assertEqual(h.json_calls, [])
        self.assertEqual(h.status, 206)
        self.assertEqual(h.wfile.getvalue(), PAYLOAD[:4])

    def test_route_answers_416_for_a_huge_start(self):
        self.sidecar("123")
        h = self.serve(_Handler("/api/recordings/123/video",
                                {"Range": "bytes=" + "9" * 5000 + "-"}))
        self.assertEqual(h.json_calls, [])
        self.assertEqual(h.status, 416)


# ---------------------------------------------------------------- F2
class _FailingReader(io.RawIOBase):
    """Wraps a real binary file; read() raises after ``ok_reads`` calls."""

    def __init__(self, real, ok_reads: int):
        self._real = real
        self._left = ok_reads

    def fileno(self):
        return self._real.fileno()

    def seek(self, *a):
        return self._real.seek(*a)

    def read(self, n=-1):
        if self._left <= 0:
            raise OSError(5, "simulated read failure")
        self._left -= 1
        return self._real.read(n)

    def close(self):
        self._real.close()
        super().close()


class MidStreamFailureTests(_Base):
    def _open_failing(self, ok_reads: int):
        real_open = open

        def fake_open(path, mode="r", *a, **k):
            return _FailingReader(real_open(path, mode, *a, **k), ok_reads)
        return patch.object(rr, "open", fake_open, create=True)

    def test_read_error_after_headers_writes_no_second_response(self):
        self.sidecar("123")
        with patch.object(rr, "_CHUNK", 1000), self._open_failing(1), \
                self.assertLogs("rc.web_dashboard", level="WARNING"):
            h = self.serve(_Handler("/api/recordings/123/video"))
        self.assertEqual(h.status, 200)
        self.assertEqual(h.json_calls, [], "a JSON 500 was written into the video body")
        self.assertEqual(h.wfile.getvalue(), PAYLOAD[:1000])
        self.assertTrue(h.close_connection)

    def test_file_shorter_than_its_fstat_closes_the_connection(self):
        self.sidecar("123")
        real_fstat = os.fstat

        class _Big:
            def __init__(self, st):
                self.st_size = st.st_size + 500

        with patch.object(rr.os, "fstat", lambda fd: _Big(real_fstat(fd))):
            h = self.serve(_Handler("/api/recordings/123/video"))
        self.assertEqual(h.status, 200)
        self.assertEqual(h.wfile.getvalue(), PAYLOAD)
        self.assertTrue(h.close_connection)

    def test_complete_body_leaves_the_connection_alone(self):
        self.sidecar("123")
        h = self.serve(_Handler("/api/recordings/123/video"))
        self.assertEqual(h.wfile.getvalue(), PAYLOAD)
        self.assertFalse(h.close_connection)


# ---------------------------------------------------------------- F3
class _StalledWriter:
    def __init__(self):
        self.writes = 0

    def write(self, b):
        self.writes += 1
        raise TimeoutError("timed out")


class StalledClientTests(_Base):
    def test_write_is_bounded_and_prior_timeout_restored(self):
        self.sidecar("123")
        conn = _Conn(prior=None)
        w = _StalledWriter()
        with patch.object(rr, "_CHUNK", 1000):
            h = self.serve(_Handler("/api/recordings/123/video", conn=conn, wfile=w))
        self.assertEqual(h.status, 200)
        self.assertEqual(w.writes, 1, "kept writing to a timed-out socket")
        self.assertTrue(h.close_connection)
        self.assertEqual(h.json_calls, [])
        armed = [c for c in conn.calls if c is not None]
        self.assertTrue(armed, "no write timeout was armed")
        self.assertTrue(all(0 < c <= 300 for c in armed), conn.calls)
        self.assertIsNone(conn.timeout, "prior (blocking) timeout not restored")

    def test_successful_stream_restores_a_prior_finite_timeout(self):
        self.sidecar("123")
        conn = _Conn(prior=7.5)
        h = self.serve(_Handler("/api/recordings/123/video", conn=conn))
        self.assertEqual(h.wfile.getvalue(), PAYLOAD)
        self.assertEqual(conn.calls[0], rr._WRITE_STALL_S)
        self.assertEqual(conn.timeout, 7.5)

    def test_no_connection_attribute_still_streams(self):
        self.sidecar("123")
        h = self.serve(_Handler("/api/recordings/123/video"))
        self.assertEqual(h.wfile.getvalue(), PAYLOAD)


# ---------------------------------------------------------------- F4
class StrictJsonSummaryTests(_Base):
    def test_non_finite_sidecar_numbers_become_null(self):
        self.sidecar_text("123", (
            '{"status": "final", "owner": "rc", "obs_output_path": null,'
            ' "game_time_offset_s": NaN, "start_game_time_s": Infinity,'
            ' "death_count": -Infinity,'
            ' "bookmarks": [{"event_id": 1, "game_time": NaN, "video_time": 3.5,'
            ' "name": {"deep": [Infinity, 1]}}]}'))
        h = self.serve(_Handler("/api/recordings/123"))
        self.assertEqual(len(h.json_calls), 1)
        code, raw = h.json_calls[0]
        self.assertEqual(code, 200)
        body = _strict_loads(raw)
        self.assertIsNone(body["game_time_offset_s"])
        self.assertIsNone(body["start_game_time_s"])
        self.assertIsNone(body["death_count"])
        bm = body["bookmarks"][0]
        self.assertIsNone(bm["game_time"])
        self.assertEqual(bm["video_time"], 3.5)
        self.assertEqual(bm["name"], {"deep": [None, 1]})

    def test_finite_values_pass_through_unchanged(self):
        self.sidecar("123", game_time_offset_s=12.25, death_count=3)
        h = self.serve(_Handler("/api/recordings/123"))
        body = _strict_loads(h.json_calls[0][1])
        self.assertEqual(body["game_time_offset_s"], 12.25)
        self.assertEqual(body["death_count"], 3)
        self.assertTrue(body["has_video"])

    def test_a_value_the_scrubber_misses_fails_loudly_not_as_bad_json(self):
        # Backstop: allow_nan=False turns a missed case into a ValueError (the
        # route's generic 500), never a NaN token on the wire.
        h = _Handler("/api/recordings/123")
        with self.assertRaises(ValueError):
            rr._json(h, 200, {"t": (float("nan"),)})
        self.assertEqual(h.json_calls, [])


# ---------------------------------------------------------------- F5
class CatchAllLoggingTests(_Base):
    def test_unexpected_error_logs_a_traceback_but_replies_generically(self):
        secret = os.path.join(str(self.tmp), "private", "x.mp4")

        def boom(_raw):
            raise RuntimeError(f"cannot read {secret}")

        with patch.object(rr, "load_sidecar", boom), \
                self.assertLogs("rc.web_dashboard", level="WARNING") as cm:
            h = self.serve(_Handler("/api/recordings/123"))
        code, raw = h.json_calls[0]
        self.assertEqual(code, 500)
        self.assertNotIn(b"cannot read", raw)
        self.assertNotIn(b"private", raw)
        self.assertTrue(any(r.exc_info for r in cm.records),
                        "the catch-all logged no traceback")


if __name__ == "__main__":
    unittest.main()
