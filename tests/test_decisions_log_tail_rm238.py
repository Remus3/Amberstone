"""RM-238: /api/decisions/log must not read the whole append-only JSONL.

The log is never rotated, so a whole-file read grows without bound. The route
now tails the file backwards in chunks; these tests pin that the bytes READ
are bounded by what the response needs, not by the file size.
"""
from __future__ import annotations

import builtins
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashboard.routes_diag as rd  # noqa: E402


class _H:
    def __init__(self, path):
        self.path = path
        self.sent = None

    def _send(self, status, payload, ctype):
        self.sent = (status, payload, ctype)


class _CountingFile:
    def __init__(self, fh, counter):
        self._fh = fh
        self._counter = counter

    def read(self, n=-1):
        data = self._fh.read(n)
        self._counter[0] += len(data)
        return data

    def __getattr__(self, name):
        return getattr(self._fh, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self._fh.close()


class DecisionsLogTailRM238(unittest.TestCase):
    def _serve(self, path, limit=20):
        counter = [0]
        real_open = builtins.open

        def counting_open(p, mode="r", *a, **kw):
            fh = real_open(p, mode, *a, **kw)
            if Path(p) == path:
                return _CountingFile(fh, counter)
            return fh

        h = _H(f"/api/decisions/log?limit={limit}")
        with mock.patch.object(rd, "_LOG_PATH", path), \
                mock.patch.object(Path, "read_text",
                                  side_effect=AssertionError("whole-file read")), \
                mock.patch("builtins.open", counting_open):
            rd._serve_decisions_log(h)
        return h, counter[0]

    def test_large_log_read_is_bounded(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decisions_log.jsonl"
            row = json.dumps({"id": "x", "pad": "p" * 600})
            with open(p, "w", encoding="utf-8") as f:
                for i in range(20000):  # ~12 MB
                    f.write(row.replace('"x"', f'"d{i}"') + "\n")
            size = p.stat().st_size
            h, read = self._serve(p, limit=50)
            self.assertEqual(h.sent[0], 200)
            body = json.loads(h.sent[1])
            self.assertEqual(len(body["entries"]), 50)
            self.assertEqual(body["entries"][0]["id"], "d19999")
            self.assertEqual(body["entries"][-1]["id"], "d19950")
            self.assertLess(read, 256 * 1024,
                            f"read {read} of {size} bytes for 50 entries")

    def test_all_junk_tail_is_capped_by_budget(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decisions_log.jsonl"
            with open(p, "w", encoding="utf-8") as f:
                f.write(json.dumps({"id": "old"}) + "\n")
                for _ in range(200000):  # ~6 MB of torn lines
                    f.write("{not json at all..\n")
            h, read = self._serve(p)
            self.assertEqual(h.sent[0], 200)
            self.assertLessEqual(read, rd._TAIL_MAX_BYTES)

    def test_small_log_without_trailing_newline(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "decisions_log.jsonl"
            p.write_bytes(b'{"id":"a"}\n{"id":"b"}\n{"id":"c"}')
            h, _ = self._serve(p)
            ids = [e["id"] for e in json.loads(h.sent[1])["entries"]]
            self.assertEqual(ids, ["c", "b", "a"])

    def test_line_spanning_chunk_boundary_is_whole(self):
        lines = [json.dumps({"id": f"e{i}", "pad": "z" * 37}) for i in range(40)]
        data = ("\n".join(lines) + "\n").encode()
        import io
        out = list(rd._iter_lines_newest_first(io.BytesIO(data), chunk=7))
        got = [x for x in out if x]
        self.assertEqual(got, list(reversed(lines)))


if __name__ == "__main__":
    unittest.main()
