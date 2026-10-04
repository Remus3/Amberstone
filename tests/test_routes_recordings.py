# arch: RM-641 recording sidecar + video route tests (allow-list, links, Range) | section=tests | frozen=no
"""RM-641 (directive X-41, ADR-016 "Serving"): GET /api/recordings/<id> and
GET /api/recordings/<id>/video.

Binding design: a local recording is served from :8888 ONLY for a path that a
data/recordings/<id>.json sidecar names (the RM-637 recorder writes
``obs_output_path``), after os.path.realpath and a junction / symlink
rejection, behind the existing RC_DASH_TOKEN gate, with HTTP Range.

Everything here is synthetic: temp dirs, temp files, a fake handler. No real
recording, no real sidecar.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from dashboard import routes_recordings as rr

PAYLOAD = bytes(range(256)) * 40  # 10240 bytes, every offset distinguishable


class _FakeHandler:
    """The BaseHTTPRequestHandler surface the route uses."""

    def __init__(self, path: str, headers: dict | None = None):
        self.path = path
        self.headers = dict(headers or {})
        self.status: int | None = None
        self.out_headers: dict[str, str] = {}
        self.wfile = BytesIO()
        self.json_status: int | None = None
        self.json_body: dict | None = None

    # streaming surface
    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, k: str, v: str) -> None:
        self.out_headers[k] = v

    def end_headers(self) -> None:
        pass

    # JSON surface (the dashboard's own helper)
    def _send(self, code: int, body: bytes, ctype: str, cache_control=None) -> None:
        self.json_status = code
        self.json_body = json.loads(body) if ctype == "application/json" else None


def _route(path: str):
    for matcher, fn in rr.GET_ROUTES:
        if matcher(path):
            return fn
    return None


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="rc_rec_"))
        self.rec_dir = self.tmp / "recordings"
        self.rec_dir.mkdir()
        self.media = self.tmp / "media"
        self.media.mkdir()
        self.video = self.media / "game.mp4"
        self.video.write_bytes(PAYLOAD)
        p = patch.object(rr, "RECORDINGS_DIR", self.rec_dir)
        p.start()
        self.addCleanup(p.stop)
        env = patch.dict(os.environ, {"RC_DASH_TOKEN": ""})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sidecar(self, mid: str, out_path, **extra) -> None:
        body = {"schema": 1, "status": "final", "match_id": mid, "owner": "rc",
                "obs_output_path": None if out_path is None else str(out_path),
                "game_time_offset_s": 31.5, "death_count": 1,
                "bookmarks": [{"event_id": 1, "name": "ChampionKill",
                               "game_time": 300.0, "video_time": 331.5,
                               "provisional": False, "own_death": True}]}
        body.update(extra)
        (self.rec_dir / f"{mid}.json").write_text(json.dumps(body), encoding="ascii")

    def get(self, path: str, headers: dict | None = None) -> _FakeHandler:
        fn = _route(path)
        self.assertIsNotNone(fn, f"no route for {path}")
        h = _FakeHandler(path, headers)
        fn(h)
        return h


# ----------------------------------------------------------------------------
class ParseRangeTests(unittest.TestCase):
    def test_absent_or_ignored(self):
        self.assertIsNone(rr.parse_range(None, 100))
        self.assertIsNone(rr.parse_range("", 100))
        self.assertIsNone(rr.parse_range("items=0-5", 100))
        self.assertIsNone(rr.parse_range("bytes=abc", 100))
        self.assertIsNone(rr.parse_range("bytes=5-2", 100))      # invalid -> ignore
        self.assertIsNone(rr.parse_range("bytes=0-1,4-5", 100))  # multi -> full body

    def test_closed_open_and_suffix(self):
        self.assertEqual(rr.parse_range("bytes=0-0", 100), (0, 0))
        self.assertEqual(rr.parse_range("bytes=10-19", 100), (10, 19))
        self.assertEqual(rr.parse_range("bytes=90-", 100), (90, 99))
        self.assertEqual(rr.parse_range("bytes=-10", 100), (90, 99))
        self.assertEqual(rr.parse_range(" bytes = 1 - 2 ", 100), (1, 2))

    def test_clamps_end_and_long_suffix(self):
        self.assertEqual(rr.parse_range("bytes=95-500", 100), (95, 99))
        self.assertEqual(rr.parse_range("bytes=-500", 100), (0, 99))
        self.assertEqual(rr.parse_range("bytes=99-99", 100), (99, 99))

    def test_unsatisfiable(self):
        self.assertEqual(rr.parse_range("bytes=100-", 100), rr.UNSATISFIABLE)
        self.assertEqual(rr.parse_range("bytes=100-200", 100), rr.UNSATISFIABLE)
        self.assertEqual(rr.parse_range("bytes=-0", 100), rr.UNSATISFIABLE)
        self.assertEqual(rr.parse_range("bytes=0-", 0), rr.UNSATISFIABLE)


# ----------------------------------------------------------------------------
class VideoServeTests(_Base):
    def test_full_body_200_advertises_ranges(self):
        self.sidecar("123", self.video)
        h = self.get("/api/recordings/123/video")
        self.assertEqual(h.status, 200)
        self.assertEqual(h.out_headers["Accept-Ranges"], "bytes")
        self.assertEqual(h.out_headers["Content-Length"], str(len(PAYLOAD)))
        self.assertEqual(h.out_headers["Content-Type"], "video/mp4")
        self.assertEqual(h.wfile.getvalue(), PAYLOAD)

    def test_range_206_with_exact_content_range(self):
        self.sidecar("123", self.video)
        h = self.get("/api/recordings/123/video", {"Range": "bytes=100-199"})
        self.assertEqual(h.status, 206)
        self.assertEqual(h.out_headers["Content-Range"], f"bytes 100-199/{len(PAYLOAD)}")
        self.assertEqual(h.out_headers["Content-Length"], "100")
        self.assertEqual(h.wfile.getvalue(), PAYLOAD[100:200])

    def test_open_ended_and_suffix_ranges(self):
        self.sidecar("123", self.video)
        n = len(PAYLOAD)
        h = self.get("/api/recordings/123/video", {"Range": f"bytes={n - 5}-"})
        self.assertEqual(h.status, 206)
        self.assertEqual(h.out_headers["Content-Range"], f"bytes {n - 5}-{n - 1}/{n}")
        self.assertEqual(h.wfile.getvalue(), PAYLOAD[-5:])
        h = self.get("/api/recordings/123/video", {"Range": "bytes=-1"})
        self.assertEqual(h.wfile.getvalue(), PAYLOAD[-1:])
        self.assertEqual(h.out_headers["Content-Range"], f"bytes {n - 1}-{n - 1}/{n}")

    def test_range_spanning_the_read_chunk(self):
        self.sidecar("123", self.video)
        with patch.object(rr, "_CHUNK", 7):
            h = self.get("/api/recordings/123/video", {"Range": "bytes=3-4099"})
        self.assertEqual(h.wfile.getvalue(), PAYLOAD[3:4100])

    def test_unsatisfiable_416_names_the_size(self):
        self.sidecar("123", self.video)
        h = self.get("/api/recordings/123/video", {"Range": f"bytes={len(PAYLOAD)}-"})
        self.assertEqual(h.status, 416)
        self.assertEqual(h.out_headers["Content-Range"], f"bytes */{len(PAYLOAD)}")
        self.assertEqual(h.wfile.getvalue(), b"")

    def test_platform_prefixed_match_id_maps_to_the_game_id_sidecar(self):
        # Replay view ids are Match-V5 ("NA1_123"); the recorder names its
        # sidecar by the Live Client gameId ("123").
        self.sidecar("123", self.video)
        h = self.get("/api/recordings/NA1_123/video", {"Range": "bytes=0-0"})
        self.assertEqual(h.status, 206)


class AllowListTests(_Base):
    def assertRefused(self, h: _FakeHandler, code: int = 404):
        self.assertIsNone(h.status, "stream must not start")
        self.assertEqual(h.json_status, code)
        self.assertEqual(h.wfile.getvalue(), b"")

    def test_no_sidecar_is_404(self):
        self.assertRefused(self.get("/api/recordings/999/video"))

    def test_path_not_in_any_sidecar_is_unreachable(self):
        # A real file next to an allowed one; nothing names it, so no id
        # reaches it.
        other = self.media / "other.mp4"
        other.write_bytes(b"secret")
        self.sidecar("123", self.video)
        for p in ("/api/recordings/other/video",
                  "/api/recordings/..%2fmedia%2fother/video",
                  "/api/recordings/../media/other/video"):
            h = _FakeHandler(p)
            fn = _route(p)
            if fn is None:
                continue
            fn(h)
            self.assertNotEqual(h.status, 200, p)
            self.assertEqual(h.wfile.getvalue(), b"", p)

    def test_operator_owned_sidecar_has_no_video(self):
        self.sidecar("123", None, owner="operator")
        self.assertRefused(self.get("/api/recordings/123/video"))

    def test_relative_path_refused(self):
        # Relative to the process cwd it WOULD exist; it is still refused.
        here = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, here)
        self.sidecar("123", "media/game.mp4")
        self.assertRefused(self.get("/api/recordings/123/video"))

    def _junction(self) -> Path:
        target_dir = self.tmp / "elsewhere"
        target_dir.mkdir(exist_ok=True)
        (target_dir / "g.mp4").write_bytes(PAYLOAD)
        via = self.media / "via"
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(target_dir), str(via))
        else:
            os.symlink(target_dir, via, target_is_directory=True)
        return via / "g.mp4"

    def test_link_walk_stands_alone(self):
        # Each guard must hold without the other: blind realpath, and the
        # walk still refuses the junction.
        path = self._junction()
        with patch.object(rr.os.path, "realpath", lambda p: p):
            self.assertIsNone(rr.resolve_recording_path(str(path)))

    def test_realpath_compare_stands_alone(self):
        # A reparse point the link predicates cannot see (a mount point,
        # say) is still caught by the realpath comparison.
        path = self._junction()
        with patch.object(rr, "_is_link", lambda p: False):
            self.assertIsNone(rr.resolve_recording_path(str(path)))

    def test_non_video_extension_refused(self):
        txt = self.media / "notes.txt"
        txt.write_bytes(b"x")
        self.sidecar("123", txt)
        self.assertRefused(self.get("/api/recordings/123/video"))

    def test_missing_file_refused(self):
        self.sidecar("123", self.media / "gone.mp4")
        self.assertRefused(self.get("/api/recordings/123/video"))

    def test_symlinked_file_refused(self):
        link = self.media / "link.mp4"
        try:
            os.symlink(self.video, link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create a symlink here: {exc}")
        self.sidecar("123", link)
        self.assertRefused(self.get("/api/recordings/123/video"))

    def test_junction_or_dir_symlink_in_the_parent_chain_refused(self):
        target_dir = self.tmp / "elsewhere"
        target_dir.mkdir()
        (target_dir / "g.mp4").write_bytes(PAYLOAD)
        via = self.media / "via"
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(target_dir), str(via))
        else:
            os.symlink(target_dir, via, target_is_directory=True)
        self.sidecar("123", via / "g.mp4")
        self.assertRefused(self.get("/api/recordings/123/video"))
        # the same file by its real path is fine
        self.sidecar("124", target_dir / "g.mp4")
        self.assertEqual(self.get("/api/recordings/124/video").status, 200)

    def test_symlinked_sidecar_refused(self):
        real = self.tmp / "planted.json"
        real.write_text(json.dumps({"obs_output_path": str(self.video)}), encoding="ascii")
        try:
            os.symlink(real, self.rec_dir / "555.json")
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"cannot create a symlink here: {exc}")
        self.assertRefused(self.get("/api/recordings/555/video"))

    def test_malformed_sidecar_refused(self):
        (self.rec_dir / "123.json").write_text("{not json", encoding="ascii")
        self.assertRefused(self.get("/api/recordings/123/video"))


class AuthTests(_Base):
    def test_token_gate_when_configured(self):
        self.sidecar("123", self.video)
        with patch.dict(os.environ, {"RC_DASH_TOKEN": "s3cret"}):
            h = self.get("/api/recordings/123/video")
            self.assertEqual(h.json_status, 401)
            self.assertIsNone(h.status)
            h = self.get("/api/recordings/123/video", {"X-RC-Token": "wrong"})
            self.assertEqual(h.json_status, 401)
            h = self.get("/api/recordings/123", {})
            self.assertEqual(h.json_status, 401)
            h = self.get("/api/recordings/123/video", {"X-RC-Token": "s3cret"})
            self.assertEqual(h.status, 200)


class SidecarSummaryTests(_Base):
    def test_summary_never_leaks_the_path(self):
        self.sidecar("123", self.video)
        h = self.get("/api/recordings/NA1_123")
        self.assertEqual(h.json_status, 200)
        body = h.json_body
        self.assertTrue(body["has_video"])
        self.assertEqual(body["video_url"], "/api/recordings/123/video")
        self.assertEqual(body["game_time_offset_s"], 31.5)
        self.assertEqual(body["bookmarks"][0]["own_death"], True)
        blob = json.dumps(body)
        self.assertNotIn("obs_output_path", blob)
        self.assertNotIn(str(self.media.name), blob)

    def test_summary_without_servable_video(self):
        self.sidecar("123", None, owner="operator")
        h = self.get("/api/recordings/123")
        self.assertEqual(h.json_status, 200)
        self.assertFalse(h.json_body["has_video"])
        self.assertIsNone(h.json_body["video_url"])

    def test_summary_404_and_bad_id(self):
        self.assertEqual(self.get("/api/recordings/777").json_status, 404)
        self.assertEqual(self.get("/api/recordings/a%20b").json_status, 400)


class DispatchRegistrationTests(unittest.TestCase):
    def test_dashboard_dispatch_reaches_this_route(self):
        from dashboard import _dispatch
        hits = [fn for m, fn in _dispatch._gather_get()
                if m("/api/recordings/123/video")]
        self.assertTrue(hits, "route not registered in dashboard/_dispatch.py")
        self.assertIs(hits[0], rr._serve_recordings)


if __name__ == "__main__":
    unittest.main()
