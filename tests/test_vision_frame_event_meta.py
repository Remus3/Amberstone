"""Drift guard for vision_server/_frame.py event_meta extension.

Item 207: /upload-frame route accepts optional event_meta dict for the
LCU phase-watcher (tools/gamepc_phase_watcher.py). Backward-compatible:
polling agent uploads omit the field and still succeed.
"""
from __future__ import annotations

import base64
import json
import unittest

import vision_server._frame as frame_mod


def _b64_jpeg() -> str:
    # Minimal 1x1 JPEG so magic-byte validation passes.
    raw = bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605"
        "08070707090908090a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c2024"
        "2e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffdb00"
        "4301090909121111122412131224321b1c1b32323232323232323232323232"
        "323232323232323232323232323232323232323232323232323232323232"
        "32323232323232323232ffc00011080001000103012200021101031101ffc4"
        "001f0000010501010101010100000000000000000102030405060708090a0b"
        "ffc400b5100002010303020403050504040000017d01020300041105122131"
        "410613516107227114328191a1082342b1c11552d1f02433627282090a1617"
        "18191a25262728292a3435363738393a434445464748494a53545556575859"
        "5a636465666768696a737475767778797a838485868788898a9293949596"
        "9798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9ca"
        "d2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4"
        "001f0100030101010101010101010000000000000102030405060708090a0b"
        "ffc400b51100020102040403040705040400010277000102031104052131061"
        "2415107617113223281081442911a1b1c109233352f0156272d10a162434e1"
        "25f11718191a262728292a35363738393a434445464748494a535455565758"
        "595a636465666768696a737475767778797a82838485868788898a92939495"
        "969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9"
        "cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda00"
        "0c03010002110311003f00fbd0a00ffd9"
    )
    return base64.b64encode(raw).decode("ascii")


class UploadFrameAcceptsEventMetaTests(unittest.TestCase):
    """Posting event_meta lands the field in the cache slot, and the
    response reports event_tagged=True. Polling uploads without the
    field continue to work (event_tagged=False).
    """

    def test_polling_upload_no_event_meta_is_ok(self):
        body = json.dumps({
            "image_b64": _b64_jpeg(),
            "source": "game-pc",
            "width": 1920,
            "height": 1080,
            "format": "jpeg",
            "primary": True,
        }).encode()
        out = frame_mod.handle_upload_frame(body)
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("event_tagged", True))
        cached = frame_mod.get_latest_frame()
        self.assertEqual(cached.get("event_meta"), None)

    def test_event_meta_dict_is_persisted(self):
        meta = {
            "topic": "/lol-gameflow/v1/gameflow-phase",
            "sub_phase": "ChampSelect",
            "queue_id": 420,
            "captured_at": "2026-05-27T21:15:00Z",
            "monitor": "game",
        }
        body = json.dumps({
            "image_b64": _b64_jpeg(),
            "source": "game-pc-event-game",
            "width": 1920,
            "height": 1080,
            "format": "jpeg",
            "primary": False,
            "event_meta": meta,
        }).encode()
        out = frame_mod.handle_upload_frame(body)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("event_tagged"))
        cached = frame_mod.get_latest_frame(source="game-pc-event-game")
        self.assertEqual(cached.get("event_meta"), meta)

    def test_event_meta_non_dict_is_coerced_to_none(self):
        body = json.dumps({
            "image_b64": _b64_jpeg(),
            "source": "game-pc-malformed",
            "width": 1920,
            "height": 1080,
            "format": "jpeg",
            "primary": False,
            "event_meta": ["not", "a", "dict"],
        }).encode()
        out = frame_mod.handle_upload_frame(body)
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("event_tagged"))
        cached = frame_mod.get_latest_frame(source="game-pc-malformed")
        self.assertEqual(cached.get("event_meta"), None)


if __name__ == "__main__":
    unittest.main()
