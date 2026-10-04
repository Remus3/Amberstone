"""RM-247: oversized / bomb-class frames are REFUSED, never forwarded.

Before: `_crop_to_primary` had no dimension cap and its `except Exception`
recovery returned the ORIGINAL b64, so a frame that tripped PIL's
DecompressionBombError was forwarded to the API at full size; and
`handle_upload_frame` capped bytes on the wire but not the decoded canvas.

Frames are hand-built PNG headers (IHDR + IEND, no pixel data): PIL reads
the size from the header without decoding, which is exactly the path the
caps rely on - and no test allocates a giant buffer.
"""
from __future__ import annotations

import base64
import io
import json
import struct
import sys
import zlib
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from vision_server import _frame, _inference  # noqa: E402


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + kind + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def _png_header(w: int, h: int) -> str:
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(b"")) + _chunk(b"IEND", b""))
    return base64.b64encode(raw).decode("ascii")


def _real_png(w: int, h: int) -> str:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


@pytest.mark.parametrize("w,h", [(9000, 100), (100, 5000), (30000, 30000)])
def test_crop_refuses_oversized_and_bomb_frames(w, h):
    with pytest.raises(_inference.FrameRefused):
        _inference._crop_to_primary(_png_header(w, h))


def test_handle_vision_refuses_and_never_calls_the_api():
    body = json.dumps({"image_b64": _png_header(30000, 30000)}).encode()
    client = mock.MagicMock()
    with mock.patch.object(_inference, "_get_client", return_value=client), \
            mock.patch.object(_inference, "_record") as rec:
        out = _inference.handle_vision(body)
    assert out == {"error": "frame_refused"}
    client.messages.create.assert_not_called()
    assert any(c.kwargs.get("ok") is False for c in rec.call_args_list)


@pytest.mark.parametrize("w,h", [(1920, 1080), (3840, 1080), (3840, 1280)])
def test_real_capture_sizes_still_pass_the_crop(w, h):
    out, mt = _inference._crop_to_primary(_real_png(w, h))
    assert mt in ("image/png", "image/jpeg")
    assert out


@pytest.mark.parametrize("w,h", [(9000, 100), (30000, 30000)])
def test_upload_refuses_out_of_range_canvas(w, h):
    with mock.patch.object(_frame, "_record") as rec:
        out = _frame.handle_upload_frame(
            json.dumps({"image_b64": _png_header(w, h), "source": "t"}).encode())
    assert out["error"] == "frame_dimensions_out_of_range"
    assert rec.call_args.kwargs.get("ok") is False


@pytest.mark.parametrize("w,h", [(1920, 1080), (3840, 1080)])
def test_upload_accepts_real_capture_sizes(w, h):
    with mock.patch.object(_frame, "_record"), \
            mock.patch.object(_frame, "_latest_frame", {}), \
            mock.patch.object(_frame, "_frames_by_source", {}):
        out = _frame.handle_upload_frame(
            json.dumps({"image_b64": _real_png(w, h), "source": "t",
                        "primary": False}).encode())
    assert out.get("ok") is True, out
