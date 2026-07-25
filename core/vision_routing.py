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

# Distinct dropped-key signatures already surfaced at WARNING (RM-01 merge
# scope). Process-lifetime dedupe only - the JSONL shadow row is unconditional.
_WARNED_DROP_SIGS: set = set()

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

    RM-01 (upstream half) merge scope: the escalation answer is scored
    against `missing` - the exact list handed to `escalate_fn` - NOT against
    `targets`. `missing` is chosen deliberately:
      * it is literally what was asked for, so anything else is an
        unrequested key (the live relay answers every mode with the TFT
        prompt, so board_units / shop_units / traits_active / stage_round
        ride along on ARAM ticks);
      * fields OCR already resolved AND validated are excluded from
        `missing`, so scoping to it also stops Sonnet clobbering a good OCR
        read - which is exactly the contract
        `modes/shared_vision.read_tiered` already documents ("OCR wins for
        numeric fields it validates; Sonnet fills the rest").
      * shadow fields are force-added to `missing`, so the shadow contract
        above (Sonnet's value wins) is unaffected.
    The filter is DEFAULT-OFF behind RC_VISION_MERGE_STRICT - see
    `_merge_strict_enabled` for the measured reason. The dropped-key set is
    logged unconditionally (WARNING + data/vision_merge_shadow.jsonl).
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

    # -- RM-01 upstream half: scope the escalation merge -------------------
    # Pre-fix this line was an unconditional
    #   out.update({k: v for k, v in sonnet.items() if v is not None})
    # which accepted EVERY key the model returned - keys nobody asked for
    # AND keys OCR had already resolved and validated.
    accepted = {k: v for k, v in sonnet.items() if v is not None}
    strict = _merge_strict_enabled()
    dropped = {k: v for k, v in accepted.items() if k not in set(missing)}
    if dropped:
        # WARNING once per distinct dropped-key signature, DEBUG thereafter.
        # The live vision tick fires every ~8-12s and (measured on
        # data/fusion_shadow.jsonl) 44.8% of reads over-answer with the same
        # TFT-shaped key set, so an unconditional WARNING would be ~180
        # identical lines per game. Every distinct key still gets its WARNING,
        # and the JSONL row below is written on EVERY occurrence, so no
        # observation is lost.
        sig = tuple(sorted(dropped))
        _emit = _log.debug if sig in _WARNED_DROP_SIGS else _log.warning
        _WARNED_DROP_SIGS.add(sig)
        _emit(
            "vision_routing: escalation returned %d key(s) outside the "
            "requested set %s: %s (strict=%s)",
            len(dropped), sorted(missing), list(sig), strict,
        )
        _log_merge_drops(missing, accepted, dropped, strict)
    if strict:
        accepted = {k: v for k, v in accepted.items() if k in set(missing)}

    out.update(accepted)
    return out or None


def _merge_strict_enabled() -> bool:
    """DEFAULT-OFF gate for the scoped escalation merge (RM-01 upstream).

    Set ``RC_VISION_MERGE_STRICT=1`` to filter the Sonnet merge down to the
    fields actually requested. OFF by default because the filter provably
    changes served coach dicts:

    ``modes/shared_vision.GameVisionReader._postprocess`` (shared_vision.py
    :416-418) aliases the relay's ``is_augment_select`` into the consumed
    ``augment_select`` AFTER read_or_escalate returns, and
    ``is_augment_select`` is in NO coach's TIERED_FIELDS - so it is an
    unrequested key with a live consumer. Replaying the 232 real records in
    data/fusion_shadow.jsonl: 104 of them (44.8%) carry ``is_augment_select``,
    and in all 104 the consumed ``augment_select`` equals it (i.e. it exists
    only because of the alias). Filtering by default would silently regress
    the 2026-07-12 ARAM Mayhem augment-select fix. The drop set is logged
    unconditionally so the flip stays a measured decision, not a guess.
    """
    import os
    raw = (os.getenv("RC_VISION_MERGE_STRICT") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _merge_shadow_path():
    """Resolve the merge-drop shadow-log path. Honors RC_VISION_MERGE_SHADOW_PATH
    (tests + ops override), else data/vision_merge_shadow.jsonl at the repo root.

    Deliberately its OWN lane rather than data/ocr_shadow.jsonl: that log has a
    fixed per-field schema {ts, field, ocr_val, sonnet_val, match} which
    tools/ocr_shadow_report.py aggregates by field, and a per-call drop record
    would corrupt those match rates.
    """
    import os
    from pathlib import Path
    override = os.getenv("RC_VISION_MERGE_SHADOW_PATH")
    if override:
        return Path(override)
    return (Path(__file__).resolve().parent.parent
            / "data" / "vision_merge_shadow.jsonl")


def _log_merge_drops(requested, returned: dict, dropped: dict,
                     strict: bool) -> None:
    """Append one merge-scope shadow row per escalation that over-answered.

    The row records what was asked for, what came back, and what the scoped
    merge did (strict=True) or would have (strict=False) discarded - the
    shadow-compare corpus for flipping RC_VISION_MERGE_STRICT on. Fail-soft:
    never raises into the live vision path.
    """
    try:
        import json
        import time
        row = json.dumps({
            "ts": time.time(),
            "strict": bool(strict),
            "requested": sorted(requested),
            "returned": sorted(returned),
            "dropped": {k: dropped[k] for k in sorted(dropped)},
        }, ensure_ascii=True, default=str)
        path = _merge_shadow_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(row + "\n")
    except Exception as exc:  # noqa: BLE001
        _log.debug("vision_routing: merge-drop log failed: %s", exc)


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
