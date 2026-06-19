# arch: Anthropic vision/coach + Tesseract OCR handlers | section=vision | frozen=no
"""Inference handlers: Sonnet vision, Haiku coach, Tesseract OCR.

Split out of moon_vision_server.py during Phase 2.4. Combines the plan's
``sonnet_escalation.py`` (vision API calls) and ``tier_routes.py`` (OCR
endpoints) - both run inside HTTP request handlers and feed the same stats
ring + cost tracker, so keeping them adjacent avoids a needless boundary.

Owns:
- ``_VISION_PROMPT`` - TFT analysis system prompt (cached via ``cache_control:
  ephemeral`` on subsequent calls).
- ``_parse_json`` - best-effort fenced/raw/braces JSON extraction.
- ``_crop_to_primary`` - halves Sonnet input area on stitched dual-monitor
  frames (RC_VISION_NO_CROP=1 disables).
- ``_record_to_cost_tracker`` - best-effort hook into ``core.cost_tracker``.
- ``handle_vision`` / ``handle_coach`` - Anthropic Messages API.
- ``handle_ocr`` - Tesseract over base64 crops.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from io import BytesIO

from ._config import COACH_MODEL, VISION_MODEL, _get_client, log
from ._stats import _record

_VISION_PROMPT = """Analyze TFT screenshot. Return ONLY valid JSON:
{"traits_active":["N.O.V.A. 3"],"board_units":["Aatrox 2-star","Caitlyn"],
"bench_units":["Kindred","empty"],"shop_units":["Akali","Leona","unknown","Corki","empty"],
"items_equipped":{"Aatrox":["Warmog"]},"items_on_bench":[],"augments":["Crest"],
"gold":null,"hp":null,"level":null,"stage_round":null,
"is_augment_select":false,"augment_choices":[],"last_round_result":null,"round_damage":null}
RULES: Read TRAITS panel (left), SHOP names (bottom cards), BENCH, BOARD (your side only).
Never output trait names as unit names. Spectating -> board_units=["SPECTATING"]."""


def _parse_json(raw: str) -> dict | None:
    # AUDIT (2026-04-22): bare `except: pass` replaced with specific
    # JSONDecodeError catches so SystemExit/KeyboardInterrupt propagate.
    for t in [raw, raw.strip("`").strip()]:
        t2 = t[4:].strip() if t.startswith("json") else t
        try:
            return json.loads(t2)
        except json.JSONDecodeError:
            pass
    fb = raw.find("{")
    lb = raw.rfind("}")
    if fb != -1 and lb > fb:
        try:
            return json.loads(raw[fb:lb + 1])
        except json.JSONDecodeError:
            pass
    return None


def _crop_to_primary(img_b64: str) -> tuple[str, str]:
    """AUDIT 2026-04-29 (gap C): the Game-PC screen agent stitches both
    monitors into one frame (3840x1280 typical). League runs on monitor 0
    at 1920x1080; the right half of the stitched frame is the dashboard
    on the iPad-via-Duet display, which Sonnet wastes time analysing.

    Crop to the primary 1920x1080 region before /vision. Cuts Sonnet input
    by ~50% (image area) -> roughly halves latency and cost.

    Returns (cropped_b64, media_type). On any decode/encode failure, returns
    the original b64 + best-guess media type - the worst case is "we burned
    3.6 s instead of 1.8 s on this one call".

    Disable via env: RC_VISION_NO_CROP=1.
    """
    if os.environ.get("RC_VISION_NO_CROP") == "1":
        mt = "image/jpeg" if img_b64.startswith("/9j/") else "image/png"
        return img_b64, mt
    try:
        from PIL import Image
        import io as _io
        raw = base64.b64decode(img_b64)
        img = Image.open(_io.BytesIO(raw))
        w, h = img.size
        # Already small? Skip - this is a non-stitched frame from a
        # single-monitor capture (or a future cropped agent).
        if w <= 1920 and h <= 1080:
            mt = "image/jpeg" if img_b64.startswith("/9j/") else "image/png"
            return img_b64, mt
        cropped = img.crop((0, 0, min(1920, w), min(1080, h)))
        buf = _io.BytesIO()
        # JPEG quality 85 keeps text legible while being ~70% smaller than
        # PNG. Sonnet sees the same content either way.
        cropped.save(buf, format="JPEG", quality=85, optimize=True)
        out = base64.b64encode(buf.getvalue()).decode("ascii")
        log.debug("Vision crop: %dx%d -> %dx%d (%d -> %d KB)",
                  w, h, cropped.width, cropped.height,
                  len(raw) // 1024, len(buf.getvalue()) // 1024)
        return out, "image/jpeg"
    except Exception as exc:  # noqa: BLE001
        log.warning("Vision crop failed (%s) - sending original frame", exc)
        mt = "image/jpeg" if img_b64.startswith("/9j/") else "image/png"
        return img_b64, mt


def _record_to_cost_tracker(resp, *, model: str, purpose: str) -> None:
    """AUDIT 2026-04-29 (in-game audit gap B): the vision server holds the
    only Anthropic client that runs Sonnet for vision calls. Without this
    hook, cost_tracker stays at $0.00 forever even as vision burns real
    dollars. Best-effort: a telemetry hiccup must never break the coach
    loop, so failures are swallowed."""
    try:
        from core.cost_tracker import get_tracker as _gt
        u = getattr(resp, "usage", None)
        _gt().record_call(
            model=model,
            input_tokens=getattr(u, "input_tokens", 0) or 0 if u else 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0 if u else 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0 if u else 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0 if u else 0,
            purpose=purpose,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("cost_tracker record_call: %s", e)


def handle_vision(body: bytes) -> dict:
    d = json.loads(body)
    img = d.get("image_b64", "")
    model = d.get("model", VISION_MODEL)
    if not img:
        return {"error": "no image_b64"}
    # Spend-gate (belt-and-suspenders, separate process): refuse the Sonnet
    # vision call when the "vision" gate is disabled. Re-reads coach_settings
    # off disk each call, so a Settings toggle applies here too.
    try:
        from core.cost_tracker import get_tracker as _gt
        if _gt().gate_disabled("vision"):
            return {"error": "vision_disabled"}
    except Exception:  # noqa: BLE001
        pass
    # AUDIT 2026-04-29 (gap C): crop stitched dual-monitor frame to the
    # primary 1920x1080 region before sending. Halves Sonnet input area.
    img_send, media_type = _crop_to_primary(img)
    t0 = time.time()
    try:
        # AUDIT 2026-04-29 (gap E): _VISION_PROMPT is identical for every
        # vision call this session - promote to a cache_control:ephemeral
        # system block instead of repeating it in user content. Cuts the
        # text-portion input cost ~90% on subsequent calls.
        resp = _get_client().messages.create(
            model=model, max_tokens=1400,
            system=[{"type": "text", "text": _VISION_PROMPT,
                     "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64",
                                             "media_type": media_type,
                                             "data": img_send}}]}])
        ms = int((time.time() - t0) * 1000)
        raw = resp.content[0].text.strip()
        result = _parse_json(raw)
        tok = getattr(resp, 'usage', None)
        tokens = (tok.input_tokens + tok.output_tokens) if tok else 0
        # AUDIT 2026-04-29 (gap B): feed cost_tracker.
        _record_to_cost_tracker(resp, model=model, purpose="vision_relay")
        if result is None:
            _record("vision", ms, ok=False)
            return {"error": "parse_failed", "raw": raw[:200]}
        _record("vision", ms, ok=True, tokens=tokens)
        log.info("Vision OK %dms tok=%d", ms, tokens)
        return {"ok": True, "result": result, "latency_ms": ms}
    except Exception:
        ms = int((time.time() - t0) * 1000)
        _record("vision", ms, ok=False)
        raise


def handle_coach(body: bytes) -> dict:
    d = json.loads(body)
    p = d.get("prompt", "")
    model = d.get("model", COACH_MODEL)
    if not p:
        return {"error": "no prompt"}
    t0 = time.time()
    try:
        resp = _get_client().messages.create(
            model=model, max_tokens=600,
            messages=[{"role": "user", "content": p}])
        ms = int((time.time() - t0) * 1000)
        text = resp.content[0].text.strip()
        tok = getattr(resp, 'usage', None)
        tokens = (tok.input_tokens + tok.output_tokens) if tok else 0
        # AUDIT 2026-04-29 (gap B): feed cost_tracker.
        _record_to_cost_tracker(resp, model=model, purpose="coach_relay")
        _record("coach", ms, ok=True, tokens=tokens)
        log.info("Coach OK %dms tok=%d", ms, tokens)
        return {"ok": True, "text": text, "latency_ms": ms}
    except Exception:
        ms = int((time.time() - t0) * 1000)
        _record("coach", ms, ok=False)
        raise


_TESSERACT_DEFAULT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
# P2-W1-app-A subprocess hardening (sibling of the cycle-7 core.vision_tesseract
# fix this slice missed): pytesseract default timeout=0 waits unbounded, so a
# hung tesseract.exe blocks this HTTP handler thread forever. Cap every call.
_OCR_TIMEOUT_S = 10.0


def handle_ocr(body: bytes) -> dict:
    d = json.loads(body)
    crops = d.get("crops", {})
    if not crops:
        return {"error": "no crops"}
    try:
        import pytesseract
        from PIL import Image, ImageEnhance
    except ImportError:
        return {"error": "pytesseract/PIL missing"}
    # winget install does not add Tesseract to PATH on Windows; pin to default.
    import os.path as _osp
    if not pytesseract.pytesseract.tesseract_cmd or \
            not _osp.isfile(pytesseract.pytesseract.tesseract_cmd):
        if _osp.isfile(_TESSERACT_DEFAULT):
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_DEFAULT
    results: dict = {}
    t0 = time.time()

    def _pre(b64, scale=3):
        img = Image.open(BytesIO(base64.b64decode(b64))).convert("L")
        w, h = img.size
        img = img.resize((w * scale, h * scale), Image.LANCZOS)
        return ImageEnhance.Contrast(img).enhance(2.5)

    # AUDIT (2026-04-22): specific exception classes - pytesseract raises
    # pytesseract.TesseractError / EnvironmentError / OSError on tool
    # failures; PIL raises PIL.UnidentifiedImageError / OSError on crop
    # decode. Keep the silent-continue behaviour (OCR is best-effort) but
    # stop swallowing SystemExit/KeyboardInterrupt.
    _OCR_EXC = (RuntimeError, OSError, ValueError, AttributeError)
    if "stage_round" in crops:
        try:
            t = re.sub(r"[^0-9\-]", "",
                       pytesseract.image_to_string(
                           _pre(crops["stage_round"], 4),
                           config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789-",
                           timeout=_OCR_TIMEOUT_S).strip())
            m = re.match(r"^([1-7])-([1-7])$", t)
            if m:
                s, r2 = int(m.group(1)), int(m.group(2))
                if 1 <= s <= 7 and 1 <= r2 <= (4 if s == 1 else 7):
                    results["stage_round"] = f"{s}-{r2}"
        except _OCR_EXC:
            pass
    if "level" in crops:
        try:
            t = pytesseract.image_to_string(
                _pre(crops["level"]),
                config="--oem 3 --psm 7 -c tessedit_char_whitelist=Llv0123456789 ",
                timeout=_OCR_TIMEOUT_S).strip()
            m = re.search(r"\d+", t)
            if m and 1 <= int(m.group()) <= 10:
                results["level"] = int(m.group())
        except _OCR_EXC:
            pass
    if "gold" in crops:
        try:
            t = re.sub(r"[^0-9]", "",
                       pytesseract.image_to_string(
                           _pre(crops["gold"]),
                           config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789",
                           timeout=_OCR_TIMEOUT_S).strip())
            if t and 0 <= int(t) <= 999:
                results["gold"] = int(t)
        except _OCR_EXC:
            pass
    ms = int((time.time() - t0) * 1000)
    _record("ocr", ms, ok=True)
    log.info("OCR: %s %dms", results, ms)
    return {"ok": True, "result": results}
