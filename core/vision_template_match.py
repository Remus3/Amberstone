"""Generic deterministic icon template-match foundation (Lane E CV atlas).

Purpose: given ONE small RGB crop, name the single best-matching icon from a
whole category catalog (champions / items / spells). This is the deterministic
substrate for the Haiku/Sonnet-to-ZERO Lane E CV atlas - specifically the
OBS_CV_MINIMAP_PLAN.md section 3 rows #8 (objective-icon read) and #10
(item-completion read), where a fixed on-disk icon set can be recognized
without paying a vision-model call.

HAVE-distinction from core/minimap_identity.py: that module is roster-scoped
minimap-DOT identity - it walks a list of blob-detected dots on a MINIMAP crop
and, for each dot, matches a tiny neighborhood against ONLY the ~10 live-roster
champions. This module is the generic inverse: a SINGLE crop matched against the
FULL category catalog (or an optional roster subset), returning one (id, conf)
pair. Different input (one crop vs many dots), different candidate scope (whole
catalog vs 10-champ roster), different output (one best id vs additive per-dot
tags). The two share only the proven fail-soft idiom and the two-stage numeric
match core, which are re-derived here rather than imported to keep this module
self-contained.

Default-OFF: this module is NOT imported or wired into any live/runtime path.
Nothing in the RC loop calls it; it is exercised only by its unit test. A real
flip is a later, deliberate, live-gated step.

Fail-soft, NEVER raises: cv2/numpy absent, unknown category, empty atlas,
unreadable icon, malformed crop, bad numerics -> (None, 0.0). Lazy cv2/numpy
import inside functions (opencv is treated as an optional dependency).

Matching design (two-stage, mirrors minimap_identity._match_score):
  1. cv2.matchTemplate TM_CCORR_NORMED slides the resized template over the
     crop in the fast C path and locates the best offset (tolerating small
     icon-vs-crop positional jitter).
  2. A masked zero-mean Pearson correlation at that single offset is the
     confidence in [0, 1]. CCORR_NORMED alone scores flat/noise windows
     deceptively high; Pearson is 0 on a flat window and ~1.0 on an exact
     paste, so the threshold is meaningful.

Color space: cv2.imread returns BGR; templates are converted BGR->RGB on load
and kept RGB internally. match_icon therefore expects an RGB crop (the RC
vision pipeline crops are RGB) - the caller must convert a fresh cv2.imread
result BGR->RGB before calling.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger("rc.vision_template_match")

_ICON_ROOT = Path(__file__).resolve().parent.parent / "data" / "icons"
_CATEGORY_DIRS = {
    "champions": _ICON_ROOT / "champions",
    "items": _ICON_ROOT / "items",
    "spells": _ICON_ROOT / "spells",
}

# Confidence threshold: masked zero-mean Pearson correlation of the crop patch
# vs the icon template, clamped to [0, 1]. An exact synthetic paste scores
# ~1.0; a flat / noise window scores ~0.0; two DIFFERENT icons land well under
# 0.5. Below the threshold match_icon returns (None, conf) - a missing id is
# always safer than a wrong one for any downstream consumer.
_MATCH_THRESHOLD = 0.6

# Template edge length as a fraction of the crop's min dimension: the template
# is deliberately SMALLER than the crop so cv2.matchTemplate can slide it over
# small icon offsets. Clamped to a floor and to the crop min dimension.
_TPL_FRAC = 0.85
_MIN_TPL = 8

# WHY default square: these are generic rectangular HUD icons (objective /
# item / spell), unlike the CIRCULAR minimap portraits. The circular-mask path
# is kept for a future minimap-style caller but is off by default.
_USE_CIRCLE_MASK = False

# Lazy caches (test seam _reset_caches drops all three):
#   _ATLAS_CACHE: category -> {stem: full_res_template_rgb_uint8}
#   _INDEX_CACHE: category -> {normalized_name_key: stem}
#   _TPL_CACHE:   (category, stem, size) -> (resized_tpl_rgb, mask) uint8
_ATLAS_CACHE: dict = {}
_INDEX_CACHE: dict = {}
_TPL_CACHE: dict = {}


def _reset_caches() -> None:
    """Test seam: drop the lazy caches (mirrors minimap_identity._reset_caches)."""
    _ATLAS_CACHE.clear()
    _INDEX_CACHE.clear()
    _TPL_CACHE.clear()


def _num(v):
    """Coerce to a finite float, or None (guard shared with minimap_identity)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _name_keys(raw):
    """All lookup keys for one id / display string: casefolded exact plus the
    apostrophe / space / dot / ampersand stripped variant (the
    minimap_identity._name_keys pattern). So "Miss Fortune" and the stem
    "MissFortune" both collapse to "missfortune"."""
    if not isinstance(raw, str):
        return
    base = raw.casefold().strip()
    if not base:
        return
    yield base
    stripped = base
    for ch in ("'", " ", ".", "&"):
        stripped = stripped.replace(ch, "")
    if stripped and stripped != base:
        yield stripped


def available_categories():
    """Sorted list of supported category names. Never raises."""
    try:
        return sorted(_CATEGORY_DIRS.keys())
    except Exception:  # noqa: BLE001 - fail-soft contract
        return []


def _atlas(category):
    """category -> {stem: full_res_template_rgb_uint8}. Built once by scanning
    the category dir and loading each PNG BGR->RGB. Empty dict on any failure
    (cv2 absent, unknown category, unreadable dir). Cached."""
    cached = _ATLAS_CACHE.get(category)
    if cached is not None:
        return cached
    out: dict = {}
    d = _CATEGORY_DIRS.get(category)
    if d is None:
        _ATLAS_CACHE[category] = out
        return out
    try:
        import cv2
    except Exception:  # noqa: BLE001 - opencv optional
        _ATLAS_CACHE[category] = out
        return out
    try:
        for p in sorted(d.glob("*.png")):
            try:
                img = cv2.imread(str(p), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                out[p.stem] = rgb
            except Exception as exc:  # noqa: BLE001 - skip one bad icon
                _log.debug("vision_template_match: icon %s skipped: %s", p, exc)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.warning("vision_template_match: atlas scan %s failed: %s", category, exc)
    _ATLAS_CACHE[category] = out
    return out


def _index(category):
    """category -> {normalized_name_key: stem}, built from the atlas stems via
    _name_keys so roster display names resolve to stems. Cached."""
    cached = _INDEX_CACHE.get(category)
    if cached is not None:
        return cached
    out: dict = {}
    try:
        for stem in _atlas(category).keys():
            for k in _name_keys(stem):
                out.setdefault(k, stem)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: index %s failed: %s", category, exc)
    _INDEX_CACHE[category] = out
    return out


def list_ids(category):
    """Sorted list of id stems in `category` (empty list on any failure)."""
    try:
        if category not in _CATEGORY_DIRS:
            return []
        return sorted(_atlas(category).keys())
    except Exception:  # noqa: BLE001 - fail-soft contract
        return []


def _template_size(height, width):
    """Template edge length (px) for a crop of the given dimensions: round of
    _TPL_FRAC * min(H, W), floored at _MIN_TPL and capped at min(H, W). Returns
    None when the crop is smaller than the floor. Never raises."""
    try:
        m = min(int(height), int(width))
    except (TypeError, ValueError):
        return None
    if m < _MIN_TPL:
        return None
    s = int(round(_TPL_FRAC * m))
    return max(_MIN_TPL, min(m, s))


def _mask(np, size):
    """The (size, size) uint8 match mask. Full 255 square by default; an
    inscribed 255 circle when _USE_CIRCLE_MASK is set (kept for a future
    minimap-style caller). Never raises for a valid size."""
    if _USE_CIRCLE_MASK:
        yy, xx = np.ogrid[:size, :size]
        c = (size - 1) / 2.0
        m = ((xx - c) ** 2 + (yy - c) ** 2) <= (size / 2.0) ** 2
        return m.astype(np.uint8) * 255
    return np.full((size, size), 255, dtype=np.uint8)


def _resized_template(category, stem, size):
    """Cached (resized_tpl_rgb, mask) uint8 arrays for one atlas entry at
    `size` px, or None (cv2/numpy absent, unknown stem, bad size). Never
    raises. Cache key is (category, stem, size)."""
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001 - opencv/numpy optional
        return None
    try:
        s = int(size)
        if s < _MIN_TPL:
            return None
        key = (category, stem, s)
        cached = _TPL_CACHE.get(key)
        if cached is not None:
            return cached
        base = _atlas(category).get(stem)
        if base is None:
            return None
        tpl = cv2.resize(base, (s, s), interpolation=cv2.INTER_AREA)
        tpl = np.ascontiguousarray(tpl.astype(np.uint8))
        out = (tpl, _mask(np, s))
        _TPL_CACHE[key] = out
        return out
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: template %s/%s@%s failed: %s",
                   category, stem, size, exc)
        return None


def _candidate_stems(category, roster):
    """Ordered candidate stem list. A non-empty list/tuple/set roster is
    resolved to stems through the _name_keys index (display names -> stems),
    de-duplicated, order preserved; otherwise the FULL sorted category catalog.
    Empty list when the atlas is empty or no roster entry resolves."""
    atlas = _atlas(category)
    if not atlas:
        return []
    if isinstance(roster, (list, tuple, set)) and roster:
        idx = _index(category)
        out = []
        seen = set()
        for r in roster:
            if not isinstance(r, str):
                continue
            for k in _name_keys(r):
                stem = idx.get(k)
                if stem is not None and stem not in seen:
                    seen.add(stem)
                    out.append(stem)
                    break
        return out
    return sorted(atlas.keys())


def _match_score(cv2, np, crop, tpl, mask):
    """Two-stage masked match score in [0, 1] for one (crop, template) pair.
    Stage 1 (fast C): TM_CCORR_NORMED with the mask slides the template over
    the crop and locates the best offset. Stage 2: masked zero-mean Pearson
    correlation at that single offset is the confidence (0 on a flat window,
    ~1.0 on an exact paste). Returns 0.0 on any numerical trouble."""
    try:
        res = cv2.matchTemplate(crop, tpl, cv2.TM_CCORR_NORMED, mask=mask)
        finite = np.isfinite(res)
        if not bool(finite.any()):
            return 0.0
        res = np.where(finite, res, -1.0)
        idx = int(np.argmax(res))
        py, px = divmod(idx, res.shape[1])
        s = tpl.shape[0]
        patch = crop[py:py + s, px:px + s]
        m = mask.astype(bool)
        a = patch[m].astype(np.float64).ravel()
        b = tpl[m].astype(np.float64).ravel()
        a = a - a.mean()
        b = b - b.mean()
        denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
        if denom <= 1e-9:
            return 0.0
        r = float((a * b).sum() / denom)
        if r != r:  # NaN
            return 0.0
        return max(0.0, min(1.0, r))
    except Exception:  # noqa: BLE001 - fail-soft contract
        return 0.0


def match_icon(crop, category="champions", roster=None, threshold=None):
    """Best single icon match for one RGB crop against a category catalog.

    crop: an (H, W, 3) RGB uint8-coercible ndarray (the RC vision crops are
      RGB; convert a fresh cv2.imread BGR result before calling).
    category: one of available_categories() ("champions" / "items" / "spells").
    roster: optional list/tuple/set of ids or display names; when non-empty the
      candidate set is restricted to those (resolved to stems), else the FULL
      catalog.
    threshold: optional confidence floor; defaults to _MATCH_THRESHOLD (0.6).

    Returns (id_or_None, confidence_float). id is the winning stem when the best
    confidence >= threshold, else None; confidence is the best score seen,
    rounded to 3 places and always in [0.0, 1.0]. Fully fail-soft: any bad
    input, missing dependency, or numeric trouble -> (None, 0.0). Never raises."""
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001 - opencv/numpy optional
        return (None, 0.0)
    try:
        if category not in _CATEGORY_DIRS:
            return (None, 0.0)
        thr = _MATCH_THRESHOLD if threshold is None else _num(threshold)
        if thr is None:
            thr = _MATCH_THRESHOLD
        arr = np.asarray(crop)
        if arr.ndim != 3 or arr.shape[2] < 3:
            return (None, 0.0)
        if arr.dtype != np.uint8:
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        crop_rgb = np.ascontiguousarray(arr[:, :, :3])
        height, width = int(crop_rgb.shape[0]), int(crop_rgb.shape[1])
        size = _template_size(height, width)
        if size is None or height < size or width < size:
            return (None, 0.0)
        candidates = _candidate_stems(category, roster)
        if not candidates:
            return (None, 0.0)
        best_id = None
        best_conf = 0.0
        for stem in candidates:
            tm = _resized_template(category, stem, size)
            if tm is None:
                continue
            score = _match_score(cv2, np, crop_rgb, tm[0], tm[1])
            if score > best_conf:
                best_conf = score
                best_id = stem
        if best_id is not None and best_conf >= thr:
            return (best_id, round(best_conf, 3))
        return (None, round(best_conf, 3))
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: match_icon failed soft: %s", exc)
        return (None, 0.0)
