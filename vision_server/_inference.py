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


# AUDIT 2026-08-30 (lane 8 cycle 20): the model id is caller-controlled on
# both /vision and /coach. A membership allowlist was REJECTED as the guard -
# `modes/shared_vision.py:273` legitimately sends SONNET_MODEL for escalation
# and `tft/` sends its own, so pinning to VISION_MODEL/COACH_MODEL would break
# the escalation path this server exists to serve. Validate SHAPE instead:
# printable, bounded, no control characters, no path separators.
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _body_object(body: bytes) -> tuple[dict | None, dict | None]:
    """Decode a request body that must be a JSON object.

    AUDIT 2026-08-30 (lane 8 cycle 20): all three handlers went straight to
    ``json.loads(body)`` then ``d.get(...)``. A top-level array or scalar -
    merely WRONG input, not hostile - raised AttributeError out of the
    handler, which ``do_POST`` turned into a bare HTTP 500 "internal error"
    with no stats record. Returns ``(obj, None)`` or ``(None, error_dict)``.
    """
    try:
        d = json.loads(body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None, {"error": "bad_json"}
    if not isinstance(d, dict):
        return None, {"error": "bad_body"}
    return d, None


def _resolve_model(d: dict, default: str) -> tuple[str | None, dict | None]:
    """Pick and shape-validate the model id. See ``_MODEL_RE``."""
    m = d.get("model")
    if m is None or m == "":
        m = default
    if not isinstance(m, str) or not _MODEL_RE.match(m):
        return None, {"error": "bad_model"}
    return m, None


def _first_text(resp) -> str | None:
    """First content block carrying str ``.text``, else None.

    AUDIT 2026-08-30 (lane 8 cycle 20): both handlers read
    ``resp.content[0].text``, which assumes a non-empty content list whose
    FIRST block is a text block. Measured: an empty list raises IndexError and
    a leading thinking block raises AttributeError - the thinking-block class
    CLAUDE.md names explicitly. Scan for the first text block instead.
    """
    for blk in (getattr(resp, "content", None) or []):
        t = getattr(blk, "text", None)
        if isinstance(t, str):
            return t
    return None


def _parse_json(raw: str) -> dict | None:
    # AUDIT (2026-04-22): bare `except: pass` replaced with specific
    # JSONDecodeError catches so SystemExit/KeyboardInterrupt propagate.
    # AUDIT 2026-08-30 (lane 8 cycle 20): the annotation has always said
    # `dict | None`, but a model answering `[1,2,3]` / `123` / `"x"` / `true`
    # returned that value straight through, and handle_vision then counted it
    # ok=True. Both live consumers isinstance-gate the result
    # (modes/shared_vision.py:383, dashboard/_screen_read.py:134), so the
    # value was discarded downstream while the stats ring called it a
    # success. Enforce the documented contract here.
    # A non-dict parse falls THROUGH to the next candidate rather than
    # returning: a model answering with a JSON string that quotes an object
    # still has its object salvaged by the brace fallback below.
    for t in [raw, raw.strip("`").strip()]:
        t2 = t[4:].strip() if t.startswith("json") else t
        try:
            v = json.loads(t2)
        except json.JSONDecodeError:
            continue
        if isinstance(v, dict):
            return v
    fb = raw.find("{")
    lb = raw.rfind("}")
    if fb != -1 and lb > fb:
        try:
            v = json.loads(raw[fb:lb + 1])
        except json.JSONDecodeError:
            return None
        if isinstance(v, dict):
            return v
    return None


def _crop_to_primary(img_b64: str) -> tuple[str, str]:
    """AUDIT 2026-04-29 (gap C): a multi-monitor screen agent could stitch
    both monitors into one frame (3840x1280 typical). League runs on monitor 0
    at 1920x1080; the right half of a stitched frame is the dashboard
    on a secondary display, which Sonnet wastes time analysing.

    Crop to the primary 1920x1080 region before /vision. Cuts Sonnet input
    by ~50% (image area) -> roughly halves latency and cost.

    Returns (cropped_b64, media_type). On any decode/encode failure, returns
    the original b64 + best-guess media type - the worst case is "we burned
    3.6 s instead of 1.8 s on this one call".

    Disable via env: RC_VISION_NO_CROP=1.
    """
    # AUDIT 2026-08-30 (lane 8 cycle 20): every `startswith` below assumed a
    # str. On a wrong-typed `image_b64` the b64decode inside the try raised,
    # and then the EXCEPT handler raised too - AttributeError on the same
    # non-string - so the recovery path was itself a crash. Guard once here.
    if not isinstance(img_b64, str):
        return img_b64, "image/png"
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
    # AUDIT 2026-08-30 (lane 8 cycle 20): validate the body shape, the image
    # field type and the model id BEFORE any work. Each rejection is recorded
    # ok=False so malformed traffic is visible in /stats - pre-fix these paths
    # raised before `t0` was ever set, so not one of them reached the ring.
    d, err = _body_object(body)
    if err is not None:
        _record("vision", 0, ok=False)
        return err
    img = d.get("image_b64", "")
    if not img or not isinstance(img, str):
        _record("vision", 0, ok=False)
        return {"error": "no image_b64"}
    model, err = _resolve_model(d, VISION_MODEL)
    if err is not None:
        _record("vision", 0, ok=False)
        return err
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
        # AUDIT 2026-08-30 (lane 8 cycle 20): was resp.content[0].text.
        _raw_txt = _first_text(resp)
        raw = _raw_txt.strip() if _raw_txt is not None else ""
        result = _parse_json(raw) if raw else None
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
    # AUDIT 2026-08-30 (lane 8 cycle 20): same three gates as handle_vision.
    d, err = _body_object(body)
    if err is not None:
        _record("coach", 0, ok=False)
        return err
    p = d.get("prompt", "")
    if not p or not isinstance(p, str):
        _record("coach", 0, ok=False)
        return {"error": "no prompt"}
    model, err = _resolve_model(d, COACH_MODEL)
    if err is not None:
        _record("coach", 0, ok=False)
        return err
    t0 = time.time()
    try:
        resp = _get_client().messages.create(
            model=model, max_tokens=600,
            messages=[{"role": "user", "content": p}])
        ms = int((time.time() - t0) * 1000)
        # AUDIT 2026-08-30 (lane 8 cycle 20): was resp.content[0].text.
        text = _first_text(resp)
        if text is None:
            _record("coach", ms, ok=False)
            return {"error": "empty_response"}
        text = text.strip()
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
# AUDIT 2026-08-30 (lane 8 cycle 20): `_pre` upscales every crop 3-4x LINEAR,
# i.e. 9-16x in pixels, with no bound on the decoded input. MEASURED on the
# pre-fix file: a 5 KB 1000x1000 PNG became a 16 MB resident "L" buffer at
# scale=4 - a ~3000x wire-to-memory amplification, under a do_POST body cap of
# 10 MiB. A 9000x9000 crop sits just under PIL's 89 MP bomb threshold and
# reaches ~1.3 GB after the 4x upscale, on a ThreadingHTTPServer worker.
# Cap the decoded dimensions and the crop count.
_OCR_MAX_CROP_PX = 4096
_OCR_MAX_CROPS = 12


def handle_ocr(body: bytes) -> dict:
    # AUDIT 2026-08-30 (lane 8 cycle 20): `crops` was used with `in` and then
    # `[]`. Both succeed on a str/list for `in` and raise TypeError on the
    # index, so a wrong-typed field became an HTTP 500. Validate the shape
    # BEFORE importing the OCR stack, so bad input costs nothing.
    d, err = _body_object(body)
    if err is not None:
        _record("ocr", 0, ok=False)
        return err
    crops = d.get("crops", {})
    if not isinstance(crops, dict):
        _record("ocr", 0, ok=False)
        return {"error": "bad_crops"}
    if not crops:
        return {"error": "no crops"}
    if len(crops) > _OCR_MAX_CROPS:
        _record("ocr", 0, ok=False)
        return {"error": "too_many_crops"}
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
        """Decode + upscale one crop. Raises ValueError on anything unusable.

        AUDIT 2026-08-30 (lane 8 cycle 20): the type check and the dimension
        cap are the guard against the amplification measured above. The size
        is read BEFORE `convert`/`resize`, so an oversized crop is refused
        without ever allocating the upscaled buffer.
        """
        if not isinstance(b64, str):
            raise ValueError("crop is not a string")
        img = Image.open(BytesIO(base64.b64decode(b64)))
        w, h = img.size
        if not (0 < w <= _OCR_MAX_CROP_PX and 0 < h <= _OCR_MAX_CROP_PX):
            raise ValueError(
                f"crop {w}x{h} outside 1..{_OCR_MAX_CROP_PX}")
        img = img.convert("L").resize((w * scale, h * scale), Image.LANCZOS)
        return ImageEnhance.Contrast(img).enhance(2.5)

    # AUDIT (2026-04-22): specific exception classes - pytesseract raises
    # pytesseract.TesseractError / EnvironmentError / OSError on tool
    # failures; PIL raises PIL.UnidentifiedImageError / OSError on crop
    # decode. Keep the silent-continue behaviour (OCR is best-effort) but
    # stop swallowing SystemExit/KeyboardInterrupt.
    # AUDIT 2026-08-30 (lane 8 cycle 20): TypeError (wrong-typed crop value),
    # MemoryError (the amplification above) and PIL's DecompressionBombError
    # (a direct Exception subclass, so NOT covered by any entry below) all
    # escaped this tuple and became an HTTP 500. A bad crop must degrade to a
    # skipped field, never to a 5xx.
    # DecompressionBombError is resolved defensively: `tests/test_p2w1_app_a.py`
    # substitutes a SimpleNamespace for the PIL Image module, which has no such
    # attribute, and a hard reference raises AttributeError at tuple-build time.
    # Under a stub there is no real PIL to raise it either, so nothing is lost;
    # against real PIL the class is always present and stays pinned by
    # OcrResourceTests::test_decompression_bomb_is_skipped_not_raised.
    _bomb = getattr(Image, "DecompressionBombError", None)
    _OCR_EXC = (RuntimeError, OSError, ValueError, AttributeError,
                TypeError, MemoryError)
    if isinstance(_bomb, type) and issubclass(_bomb, BaseException):
        _OCR_EXC = _OCR_EXC + (_bomb,)
    # Track attempt/failure so a call where EVERY crop threw is not recorded
    # as a clean read - see the _record call at the end of this function.
    attempts = 0
    fails = 0
    if "stage_round" in crops:
        attempts += 1
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
        except _OCR_EXC as _oe:
            fails += 1
            log.debug("OCR crop skipped: %s", _oe)
    if "level" in crops:
        attempts += 1
        try:
            t = pytesseract.image_to_string(
                _pre(crops["level"]),
                config="--oem 3 --psm 7 -c tessedit_char_whitelist=Llv0123456789 ",
                timeout=_OCR_TIMEOUT_S).strip()
            m = re.search(r"\d+", t)
            if m and 1 <= int(m.group()) <= 10:
                results["level"] = int(m.group())
        except _OCR_EXC as _oe:
            fails += 1
            log.debug("OCR crop skipped: %s", _oe)
    if "gold" in crops:
        attempts += 1
        try:
            t = re.sub(r"[^0-9]", "",
                       pytesseract.image_to_string(
                           _pre(crops["gold"]),
                           config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789",
                           timeout=_OCR_TIMEOUT_S).strip())
            if t and 0 <= int(t) <= 999:
                results["gold"] = int(t)
        except _OCR_EXC as _oe:
            fails += 1
            log.debug("OCR crop skipped: %s", _oe)
    ms = int((time.time() - t0) * 1000)
    # AUDIT 2026-08-30 (lane 8 cycle 20): this was an unconditional ok=True,
    # so a call in which EVERY crop threw was indistinguishable in /stats from
    # a clean read. A call that simply found no legible text is still a
    # success (attempts>0, fails<attempts); only an all-failed call is not.
    _record("ocr", ms, ok=not (attempts > 0 and fails == attempts))
    log.info("OCR: %s %dms (%d/%d crops failed)", results, ms, fails, attempts)
    return {"ok": True, "result": results}
