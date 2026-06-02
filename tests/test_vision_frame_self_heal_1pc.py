"""1-PC self-heal for the vision-frame relay (vision_server/_frame.py).

Mirrors tests/test_liveclient_self_heal_1pc.py. After the Game-PC -> Legion
consolidation (ADR-011) the continuous DXGI screen-agent that pushed frames to
:8889/upload-frame is DISABLED (it is the permanent BSOD trigger), so nothing
feeds the global /latest-frame slot. get_latest_frame() grabs ONE frame
in-process (a single GDI BitBlt via PIL.ImageGrab - NOT a loop, NOT the
continuous DXGI surface) when the cache is stale + League is local. This makes
the RC-LiveClientRelay/screen-agent an optimization rather than a hard
dependency.

Contract:
  - a FRESH relayed upload short-circuits the self-grab (zero capture).
  - a STALE/missing cache + League local -> self-grab populates + serves.
  - a self-grab failure (PIL absent / headless / grab error) -> existing cache,
    no crash.
  - self-grabs are throttled so a no-game steady state never hammers GDI.
  - a ?source= (secondary UI-debug) request is NEVER self-grabbed.
  - a remote GAME_HOST (legacy 2-PC override) never self-grabs (the screen of
    a remote box is not capturable here; the relay agent stays primary).
"""
from __future__ import annotations

import base64
import time
import unittest

from vision_server import _frame

# A minimal valid 1x1 JPEG so magic-byte-checking consumers accept the payload.
_TINY_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB/8AACwgAAQABAQERAP/EABQAAQAA"
    "AAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAA/AKpgA//Z"
)


class VisionFrameSelfHealTests(unittest.TestCase):
    def setUp(self):
        _frame._reset_self_read_state()
        self._orig_fetch = _frame._fetch_frame_direct
        self._orig_host = _frame.GAME_HOST
        self.calls = []

    def tearDown(self):
        _frame._fetch_frame_direct = self._orig_fetch
        _frame.GAME_HOST = self._orig_host
        _frame._reset_self_read_state()

    def _stub_fetch(self, ret):
        def _f():
            self.calls.append(time.time())
            return ret
        _frame._fetch_frame_direct = _f

    def _grab_payload(self):
        return {
            "b64": _TINY_JPEG_B64,
            "size": len(_TINY_JPEG_B64),
            "width": 1, "height": 1, "format": "jpeg",
            "source": "self_grab",
        }

    def test_fresh_upload_short_circuits_self_grab(self):
        self._stub_fetch(self._grab_payload())
        _frame.handle_upload_frame(
            (f'{{"image_b64": "{_TINY_JPEG_B64}", "source": "league"}}').encode()
        )
        out = _frame.get_latest_frame()
        self.assertEqual(out.get("source"), "league")
        self.assertEqual(self.calls, [])  # fresh upload -> no in-process grab

    def test_stale_cache_self_grabs(self):
        self._stub_fetch(self._grab_payload())
        out = _frame.get_latest_frame()  # cache empty -> self-grab
        self.assertEqual(out.get("source"), "self_grab")
        self.assertEqual(out.get("b64"), _TINY_JPEG_B64)
        self.assertEqual(out.get("format"), "jpeg")
        self.assertEqual(len(self.calls), 1)

    def test_self_grab_failure_returns_empty(self):
        self._stub_fetch(None)  # PIL absent / headless / grab error
        out = _frame.get_latest_frame()
        self.assertIsNone(out.get("b64"))
        self.assertEqual(len(self.calls), 1)

    def test_self_grab_failure_empty_dict_returns_empty(self):
        # A grab that returns a dict with no b64 must NOT populate the cache.
        self._stub_fetch({"width": 0, "height": 0})
        out = _frame.get_latest_frame()
        self.assertIsNone(out.get("b64"))
        self.assertEqual(len(self.calls), 1)

    def test_self_grab_throttled(self):
        self._stub_fetch(None)
        _frame.get_latest_frame()
        _frame.get_latest_frame()  # within throttle window
        self.assertEqual(len(self.calls), 1)

    def test_source_request_never_self_grabs(self):
        # The secondary UI-debug channel must reflect exactly what it pushed;
        # a self-grab here would clobber its meaning. Empty -> empty dict.
        self._stub_fetch(self._grab_payload())
        out = _frame.get_latest_frame(source="ui_debug")
        self.assertIsNone(out.get("b64"))
        self.assertEqual(self.calls, [])

    def test_remote_host_no_self_grab(self):
        _frame.GAME_HOST = "10.1.2.3"
        self._stub_fetch(self._grab_payload())
        out = _frame.get_latest_frame()
        self.assertIsNone(out.get("b64"))
        self.assertEqual(self.calls, [])  # remote -> agent stays primary

    def test_self_grabbed_b64_is_valid_base64(self):
        self._stub_fetch(self._grab_payload())
        out = _frame.get_latest_frame()
        raw = base64.b64decode(out["b64"], validate=True)
        self.assertEqual(raw[:3], b"\xff\xd8\xff")  # JPEG magic bytes

    def test_no_banned_codepoints(self):
        # Hard-rule ban: em/en-dashes + smart quotes. Pre-existing U+2500
        # box-drawing dividers are operator-gated retro-sweep, not this slice.
        text = (
            __import__("pathlib").Path(_frame.__file__).read_text(encoding="utf-8")
        )
        banned = {
            0x2014: "em-dash", 0x2013: "en-dash",
            0x2018: "lsquo", 0x2019: "rsquo",
            0x201C: "ldquo", 0x201D: "rdquo",
        }
        hits = [name for cp, name in banned.items() if chr(cp) in text]
        self.assertFalse(hits, f"_frame.py has banned codepoints: {hits}")


if __name__ == "__main__":
    unittest.main()
