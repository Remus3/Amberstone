"""
calibrate_vision.py - Pull latest frame, overlay current OCR regions, run OCR.

Outputs:
  data/debug_frame.jpg            - raw frame
  data/debug_frame_annotated.jpg  - frame + bbox overlay + field labels
  data/debug_crops/<field>.png    - per-field cropped region

Usage:
  python tools/calibrate_vision.py
"""
import base64
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont

TOKEN = "8e8f131e212b329438218eca27372dde"


def fetch_frame() -> bytes:
    req = urllib.request.Request(
        "http://127.0.0.1:8889/latest-frame", headers={"X-RC-Token": TOKEN}
    )
    data = json.loads(urllib.request.urlopen(req, timeout=5).read())
    age = time.time() - data.get("ts", 0)
    print(f"frame age={age:.1f}s {data['width']}x{data['height']} {data['format']}")
    return base64.b64decode(data["b64"])


def main() -> int:
    raw = fetch_frame()
    (ROOT / "data" / "debug_frame.jpg").write_bytes(raw)
    img = Image.open(io.BytesIO(raw)).convert("RGB")

    regions = json.loads((ROOT / "data" / "vision_regions.json").read_text(encoding="utf-8"))
    print(f"regions: {list(regions)}")

    # Annotated overlay
    ann = img.copy()
    d = ImageDraw.Draw(ann)
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except Exception:  # noqa: BLE001
        font = ImageFont.load_default()
    palette = ["#ff2244", "#44ff88", "#4a9eff", "#ffa84a",
               "#c77dff", "#ffdd00", "#3ddba8"]
    crops_dir = ROOT / "data" / "debug_crops"
    crops_dir.mkdir(exist_ok=True)
    for i, (name, bbox) in enumerate(regions.items()):
        color = palette[i % len(palette)]
        d.rectangle(bbox, outline=color, width=2)
        # Label above the box (or below if at top)
        ly = bbox[1] - 16 if bbox[1] >= 18 else bbox[3] + 2
        d.text((bbox[0], ly), name, fill=color, font=font)
        crop = img.crop(bbox)
        crop.save(crops_dir / f"{name}.png")

    out = ROOT / "data" / "debug_frame_annotated.jpg"
    ann.save(out, format="JPEG", quality=85)
    print(f"annotated -> {out}")
    print(f"crops -> {crops_dir}")

    # Run OCR via the dashboard endpoint (uses the same code path as live)
    try:
        import ssl as _ssl
        _ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
        _ctx.check_hostname = False
        _ctx.verify_mode = _ssl.CERT_NONE
        r = urllib.request.urlopen("https://127.0.0.1:8888/api/ocr", timeout=10, context=_ctx)
        print("OCR result:", r.read().decode())
    except Exception as e:  # noqa: BLE001
        print("OCR failed:", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
