"""
core/vision_routing.py - cheap-first vision routing helper.

AUDIT 2026-04-28 (proposal 5.2): coaches that need numeric HUD fields
(gold/level/HP/round/stage) should call Tesseract first and only escalate
to Sonnet when the local OCR returns out-of-range or empty.

`read_or_escalate(img_b64, fields, escalate_fn=None)`:
  1. Run `core.vision_tesseract.read_fast_fields` on the requested fields.
  2. Validate against the provided `validators` dict (or built-in
     defaults). Any field that fails validation is "missing".
  3. If all required fields validated, return the dict - no API call.
  4. Otherwise call `escalate_fn(img_b64, missing_fields)`. The caller
     supplies the Sonnet path; this module stays free-of dependency on
     anthropic SDK and per-coach prompts.

Wire-up: LIVE via `modes/shared_vision.py` - the shared vision reader's
`read_tiered()` routes TIERED_FIELDS through read_or_escalate (Sonnet as
escalate_fn, DEFAULT_VALIDATORS merged with per-mode overrides). The
original "unused until TFT vision is restored" note is obsolete - this
module is on the hot vision path for all mode coaches.
(Doc refreshed deep-audit P2-W1-E, 2026-06-11.)
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, Iterable, Optional

_log = logging.getLogger("rc.vision_routing")

# Default validators: each takes the field's parsed value and returns
# True if the value is plausible. None always fails.
DEFAULT_VALIDATORS: Dict[str, Callable[[object], bool]] = {
    "gold":   lambda v: isinstance(v, int) and 0 <= v <= 99999,
    "level":  lambda v: isinstance(v, int) and 1 <= v <= 18,
    "hp":     lambda v: isinstance(v, int) and 0 <= v <= 99999,
    "mana":   lambda v: isinstance(v, int) and 0 <= v <= 99999,
    "timer":  lambda v: isinstance(v, str) and ":" in v,
    "kda":    lambda v: isinstance(v, str) and v.count("/") == 2,
    # TFT-specific:
    "stage":  lambda v: isinstance(v, str) and "-" in v,
    "round":  lambda v: isinstance(v, int) and 1 <= v <= 7,
}


def read_or_escalate(
    img_b64: str,
    fields: Iterable[str],
    *,
    escalate_fn: Optional[Callable[[str, list], Optional[dict]]] = None,
    validators: Optional[Dict[str, Callable[[object], bool]]] = None,
    shadow_fields: Optional[Iterable[str]] = None,
) -> Optional[dict]:
    """Route the requested fields through Tesseract first; escalate the
    misses to Sonnet via `escalate_fn(img_b64, missing_fields_list)`.

    Returns a merged dict {field: value} or None if both passes failed.
    Fields with no validator are accepted as-is (truthy = good).

    `shadow_fields` (subset of `fields`): OCR-vs-Sonnet telemetry mode. Each
    shadow field is ALWAYS escalated to Sonnet regardless of its OCR result,
    and one comparison row (ts, field, ocr_val, sonnet_val, match) is appended
    to data/ocr_shadow.jsonl per shadow field. The OCR value is logged only -
    Sonnet's value wins in the returned dict. This is the confidence dataset
    the Lane E OCR migration needs before any field flips to OCR-only.
    """
    validators = validators or DEFAULT_VALIDATORS
    targets = list(fields)
    shadow = set(shadow_fields or ())
    if not targets:
        return {}

    try:
        from core.vision_tesseract import read_fast_fields
        ocr = read_fast_fields(img_b64, fields=targets, parallel=True) or {}
    except Exception as exc:  # noqa: BLE001
        _log.debug("vision_routing: Tesseract pass failed: %s", exc)
        ocr = {}

    out: dict = {}
    missing = []
    for f in targets:
        # Shadow fields always escalate: we want Sonnet's value to compare
        # against OCR and log the pair. The OCR value is not committed here.
        if f in shadow:
            missing.append(f)
            continue
        v = ocr.get(f)
        ok = False
        if v is not None:
            check = validators.get(f)
            ok = check(v) if check else True
        if ok:
            out[f] = v
        else:
            missing.append(f)

    if not missing:
        _log.debug("vision_routing: full Tesseract hit (%d fields)", len(out))
        return out

    if escalate_fn is None:
        # Caller hasn't wired Sonnet escalation; return what we have.
        if out:
            _log.debug("vision_routing: partial OCR, no escalate_fn (%d/%d)",
                       len(out), len(targets))
        return out or None

    try:
        sonnet = escalate_fn(img_b64, missing) or {}
    except Exception as exc:  # noqa: BLE001
        _log.warning("vision_routing: escalate_fn raised: %s", exc)
        sonnet = {}

    if shadow:
        _log_ocr_shadow(ocr, sonnet, shadow)

    out.update({k: v for k, v in sonnet.items() if v is not None})
    return out or None


def _ocr_shadow_path():
    """Resolve the OCR shadow-log path. Honors RC_OCR_SHADOW_PATH (tests +
    ops override), else data/ocr_shadow.jsonl at the repo root."""
    import os
    from pathlib import Path
    override = os.getenv("RC_OCR_SHADOW_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "data" / "ocr_shadow.jsonl"


def _log_ocr_shadow(ocr: dict, sonnet: dict, shadow: set) -> None:
    """Append one OCR-vs-Sonnet comparison row per shadow field to the shadow
    log (JSONL). Fail-soft - never raises into the live vision path."""
    try:
        import json
        import time
        ts = time.time()
        path = _ocr_shadow_path()
        rows = []
        for f in sorted(shadow):
            ov = ocr.get(f)
            sv = sonnet.get(f)
            rows.append(json.dumps({
                "ts": ts,
                "field": f,
                "ocr_val": ov,
                "sonnet_val": sv,
                "match": ov is not None and ov == sv,
            }, ensure_ascii=True))
        if rows:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
    except Exception as exc:  # noqa: BLE001
        _log.debug("vision_routing: shadow log failed: %s", exc)
