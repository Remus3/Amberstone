"""Drift-check manifest endpoint - /agent/_watcher_manifest.json.

Verifies the shape + freshness gate of the manifest the peer-side
tools/bridge_watcher_update_check.ps1 consumes. Exercises the handler
via a stub Request handler (same pattern as test_routes_archetype.py).
"""
from __future__ import annotations

import hashlib
import json
import time
import unittest
from pathlib import Path
from unittest import mock

from dashboard import routes_static


class StubHandler:
    def __init__(self, path: str = ""):
        self.path = path
        self.last_status: int | None = None
        self.last_body: bytes | None = None
        self.last_ct: str | None = None

    def _send(self, status, body, content_type):
        self.last_status = status
        self.last_body = body
        self.last_ct = content_type

    def parsed(self) -> dict:
        return json.loads(self.last_body.decode("utf-8")) if self.last_body else {}


class WatcherManifestTests(unittest.TestCase):
    def setUp(self):
        # Bust the 2 s cache between cases so each test sees a fresh
        # compute path.
        routes_static._WATCHER_MANIFEST_CACHE["body"] = b""
        routes_static._WATCHER_MANIFEST_CACHE["mtime"] = 0.0

    def test_returns_200_json_with_files_map(self):
        h = StubHandler("/agent/_watcher_manifest.json")
        routes_static._serve_watcher_manifest(h)
        self.assertEqual(h.last_status, 200)
        self.assertIn("application/json", h.last_ct)
        body = h.parsed()
        self.assertEqual(body["schema_version"], 1)
        self.assertIn("files", body)
        self.assertIn("generated_at", body)
        self.assertIsInstance(body["generated_at"], int)

    def test_includes_full_runtime_fileset(self):
        h = StubHandler("/agent/_watcher_manifest.json")
        routes_static._serve_watcher_manifest(h)
        files = h.parsed()["files"]
        for name in routes_static._WATCHER_RUNTIME_FILES:
            self.assertIn(name, files, f"manifest missing runtime file: {name}")

    def test_sha256_matches_disk(self):
        h = StubHandler("/agent/_watcher_manifest.json")
        routes_static._serve_watcher_manifest(h)
        files = h.parsed()["files"]
        for name, entry in files.items():
            if "error" in entry:
                continue
            disk = (routes_static.APP_DIR / "tools" / name).read_bytes()
            expected = hashlib.sha256(disk).hexdigest()
            self.assertEqual(entry["sha256"], expected, f"hash mismatch for {name}")
            self.assertEqual(entry["size"], len(disk), f"size mismatch for {name}")

    def test_cache_short_circuits_repeat_calls(self):
        h1 = StubHandler("/agent/_watcher_manifest.json")
        routes_static._serve_watcher_manifest(h1)
        first_body = h1.last_body
        # Mutate the cache mtime so we know the cached path is taken.
        cached_marker = routes_static._WATCHER_MANIFEST_CACHE["mtime"]
        # Patch read_bytes to fail loudly if the second call re-reads.
        with mock.patch.object(Path, "read_bytes", side_effect=AssertionError(
                "second call should hit the 2s cache, not re-read disk")):
            h2 = StubHandler("/agent/_watcher_manifest.json")
            routes_static._serve_watcher_manifest(h2)
        self.assertEqual(h2.last_status, 200)
        self.assertEqual(h2.last_body, first_body)
        # Cache mtime unchanged on a cache hit.
        self.assertEqual(routes_static._WATCHER_MANIFEST_CACHE["mtime"], cached_marker)

    def test_cache_expires_after_2s(self):
        h1 = StubHandler("/agent/_watcher_manifest.json")
        routes_static._serve_watcher_manifest(h1)
        # Backdate the cache to force re-compute on the next call.
        routes_static._WATCHER_MANIFEST_CACHE["mtime"] = time.time() - 10.0
        h2 = StubHandler("/agent/_watcher_manifest.json")
        routes_static._serve_watcher_manifest(h2)
        self.assertEqual(h2.last_status, 200)
        # New mtime must be recent.
        self.assertGreater(routes_static._WATCHER_MANIFEST_CACHE["mtime"], time.time() - 1.0)

    def test_missing_runtime_file_reports_error_not_500(self):
        # Force one file to be unreadable; the endpoint must still 200
        # with a per-file error entry rather than crashing the route.
        real_read_bytes = Path.read_bytes

        def fake_read_bytes(self):
            if self.name == "bridge_watcher_classify.py":
                raise FileNotFoundError(2, "stub missing", str(self))
            return real_read_bytes(self)

        with mock.patch.object(Path, "read_bytes", fake_read_bytes):
            h = StubHandler("/agent/_watcher_manifest.json")
            routes_static._serve_watcher_manifest(h)
        self.assertEqual(h.last_status, 200)
        files = h.parsed()["files"]
        self.assertIn("error", files["bridge_watcher_classify.py"])
        # Other files unaffected.
        self.assertIn("sha256", files["bridge_watcher.py"])


class WatcherUpdateCheckAllowlistTests(unittest.TestCase):
    def test_update_check_ps1_is_in_agent_allowlist(self):
        # Peers fetch the script via iex (iwr /agent/<name>).Content so
        # it MUST be present in the agent allowlist or the iwr 404s
        # before the update check can even start.
        self.assertIn("bridge_watcher_update_check.ps1", routes_static._AGENT_ALLOWED)


if __name__ == "__main__":
    unittest.main()
