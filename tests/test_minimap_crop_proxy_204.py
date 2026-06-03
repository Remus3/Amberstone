"""item 281: the :8888 -> :8890 supervisor proxy must collapse a failed
``/api/minimap-crop`` fetch to 204 No Content.

A missing minimap frame is a NORMAL condition (vision producer idle/down -
e.g. 1-PC with no Game-PC screen agent). The supervisor answers non-2xx,
which the proxy forwarded verbatim, so the browser logged a 502 console
error on every ~2s poll - both in an idle lobby AND during a live game with
no frame source. 204 hides the panel quietly with zero console noise.

Other proxied paths keep their real upstream status so genuine
supervisor-down conditions still surface.
"""
from __future__ import annotations

import unittest

from dashboard._handler import proxy_error_status


class ProxyErrorStatusTests(unittest.TestCase):
    def test_minimap_crop_error_collapses_to_204(self):
        self.assertEqual(proxy_error_status("/api/minimap-crop?mode=sr", 502), 204)
        self.assertEqual(proxy_error_status("/api/minimap-crop?mode=aram", 404), 204)
        # Supervisor unreachable (no upstream code) also collapses to 204.
        self.assertEqual(proxy_error_status("/api/minimap-crop", None), 204)

    def test_other_paths_forward_upstream_code(self):
        self.assertEqual(proxy_error_status("/api/activity", 404), 404)
        self.assertEqual(proxy_error_status("/api/digest", 503), 503)

    def test_other_paths_unreachable_is_502(self):
        self.assertEqual(proxy_error_status("/api/activity", None), 502)
        self.assertEqual(proxy_error_status("/api/locked-champion", None), 502)


if __name__ == "__main__":
    unittest.main()
