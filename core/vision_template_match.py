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

Default-OFF: this module is NOT wired into the live RC loop. Its importers are
offline: core/vision_atlas_precompute.py (atlas digest precompute, itself
reached only through core/vision_region_atlas.py), tools/vision_atlas_validate.py
(flip-readiness validator) and the tests. A real flip is a later, deliberate,
live-gated step.

Fail-soft, NEVER raises: cv2/numpy absent, unknown category, empty atlas,
unreadable icon, malformed crop, bad numerics -> (None, 0.0). Lazy cv2/numpy
import inside functions (opencv is treated as an optional dependency).

Bounds (s144 true-audit cycle 132): a crop edge over _MAX_CROP_EDGE is refused
(a whole frame is not an icon crop); the resized-template cache holds at most
_TPL_CACHE_MAX_BYTES and evicts oldest-first; an icon file over _MAX_ICON_BYTES
or a PNG whose header declares an edge over _MAX_ICON_EDGE is skipped
undecoded; a roster iterable is read for at most _MAX_ROSTER names.

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

import itertools
import logging
import math
import struct
import threading
from collections.abc import Mapping
from pathlib import Path

from core.failed_load_gate import FailedLoadGate

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

# RM-1626: the largest crop edge (either dimension) score_all accepts. HUD
# icon crops are tens of px; the offline validator's synthetic crop of the
# largest tracked item icon (512 px) is ~603 px. A crop past this is a frame,
# not an icon, and used to cost seconds of matchTemplate per category plus a
# full catalog of huge resized templates.
_MAX_CROP_EDGE = 1024

# RM-1627: byte budget of the resized-template cache. It used to grow one
# full catalog per distinct crop size for the process lifetime. Oldest entries
# are evicted first; a single template larger than the budget is not cached.
_TPL_CACHE_MAX_BYTES = 64 * 1024 * 1024

# RM-1630: icon decode guards. The tracked icons are at most a few hundred
# KB and 512 px, but the folders are refilled from an external feed by
# scripts/data_pipeline.py, so a file is skipped unread past _MAX_ICON_BYTES and
# a PNG is skipped undecoded when its IHDR declares an edge past _MAX_ICON_EDGE
# (a decompression bomb is small on disk and huge decoded).
_MAX_ICON_BYTES = 8 * 1024 * 1024
_MAX_ICON_EDGE = 2048
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# RM-1625: at most this many roster entries are read (an endless generator
# no longer hangs the match). Far above any real roster or catalog size.
_MAX_ROSTER = 512

# Lazy caches (test seam _reset_caches drops all three):
#   _ATLAS_CACHE: category -> {stem: full_res_template_rgb_uint8}
#   _INDEX_CACHE: category -> {normalized_name_key: stem}
#   _TPL_CACHE:   (category, stem, size) -> (resized_tpl_rgb, mask) uint8
_ATLAS_CACHE: dict = {}
_INDEX_CACHE: dict = {}
_TPL_CACHE: dict = {}
# Guards _TPL_CACHE's check-evict-insert so concurrent callers cannot push it
# past its budget.
_TPL_LOCK = threading.Lock()
# RM-443: per-category failure gates. A failed folder scan is NOT cached (it
# used to be, forever) - retried after the backoff, warned once per streak.
_ATLAS_GATES: dict = {}


def _reset_caches() -> None:
    """Test seam: drop the lazy caches (mirrors minimap_identity._reset_caches)."""
    _ATLAS_CACHE.clear()
    _INDEX_CACHE.clear()
    with _TPL_LOCK:
        _TPL_CACHE.clear()
    _ATLAS_GATES.clear()


def _num(v):
    """Coerce to a finite float, or None (guard shared with minimap_identity)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if not math.isfinite(f):  # NaN / inf
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


def _png_edges(data):
    """(width, height) from a PNG's IHDR chunk, or None when `data` is not a
    PNG with a complete IHDR. Reads 24 header bytes; never decodes."""
    if len(data) < 24 or data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _read_icon(cv2, np, path):
    """One icon file -> RGB uint8 array, or None when it is skipped.

    RM-1624: reads BYTES and decodes with cv2.imdecode. cv2.imread cannot
    open a non-ASCII path on Windows (measured: it returns None and prints a
    findDecoder WARN), so a checkout under such a folder loaded an EMPTY
    atlas. RM-1630: a file over _MAX_ICON_BYTES is skipped unread and a PNG
    declaring an edge over _MAX_ICON_EDGE (or zero) is skipped undecoded.
    An OSError reading the file propagates; the caller skips that icon."""
    if path.stat().st_size > _MAX_ICON_BYTES:
        _log.debug("vision_template_match: icon %s skipped: over %d bytes",
                   path, _MAX_ICON_BYTES)
        return None
    data = path.read_bytes()
    if len(data) > _MAX_ICON_BYTES:
        return None
    edges = _png_edges(data)
    if edges is not None and not all(0 < e <= _MAX_ICON_EDGE for e in edges):
        _log.debug("vision_template_match: icon %s skipped: declared %dx%d",
                   path, edges[0], edges[1])
        return None
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _atlas(category):
    """category -> {stem: full_res_template_rgb_uint8}. Built once by scanning
    the category dir and loading each PNG BGR->RGB (through _read_icon). Empty
    dict on any failure (cv2 absent, unknown category, unreadable / missing /
    empty dir). A loaded atlas, cv2 absent and an unknown category are cached;
    a folder failure is not (RM-443, RM-450) and is retried after the gate's
    backoff."""
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
        import numpy as np
    except Exception:  # noqa: BLE001 - opencv optional
        _ATLAS_CACHE[category] = out
        return out
    gate = _ATLAS_GATES.setdefault(category, FailedLoadGate())
    if not gate.should_attempt():
        return {}
    try:
        # RM-450: a MISSING or EMPTY category folder is a failure, not a
        # design state. The three folders under data/icons are tracked in git
        # and refilled by scripts/data_pipeline.py (weekly task), which can
        # run while RC is up, so an empty atlas cached here would outlive the
        # folder appearing. Retried after the gate's backoff instead; the
        # retry costs one directory listing per window.
        if not d.is_dir():
            raise OSError(f"category folder missing: {d}")
        for p in sorted(d.glob("*.png")):
            try:
                rgb = _read_icon(cv2, np, p)
                if rgb is None:
                    continue
                out[p.stem] = rgb
            except Exception as exc:  # noqa: BLE001 - skip one bad icon
                _log.debug("vision_template_match: icon %s skipped: %s", p, exc)
        if not out:
            raise OSError(f"no loadable icons in {d}")
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        if gate.record_failure():
            _log.warning("vision_template_match: atlas scan %s failed: %s", category, exc)
        return {}
    gate.record_success()
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
        for stem in _atlas(category):
            for k in _name_keys(stem):
                out.setdefault(k, stem)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: index %s failed: %s", category, exc)
    # RM-443: memoise only a projection of a LOADED atlas; a failed scan is
    # not cached, so neither is the empty index built from it.
    if category in _ATLAS_CACHE:
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


def _entry_bytes(entry):
    """Bytes held by one (tpl, mask) cache entry."""
    return int(entry[0].nbytes) + int(entry[1].nbytes)


def _cache_template(key, entry):
    """Insert one (tpl, mask) entry under the _TPL_CACHE_MAX_BYTES budget
    (RM-1627). Oldest entries are evicted first; an entry larger than the
    whole budget is not cached. The total is re-summed under the lock, so an
    external _TPL_CACHE.clear() (the RM-443 test seam) cannot desync it."""
    nbytes = _entry_bytes(entry)
    budget = _TPL_CACHE_MAX_BYTES
    if nbytes > budget:
        return
    with _TPL_LOCK:
        if key in _TPL_CACHE:
            return
        total = sum(_entry_bytes(v) for v in _TPL_CACHE.values())
        while _TPL_CACHE and total + nbytes > budget:
            oldest = next(iter(_TPL_CACHE))
            total -= _entry_bytes(_TPL_CACHE.pop(oldest))
        _TPL_CACHE[key] = entry


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
        with _TPL_LOCK:
            cached = _TPL_CACHE.get(key)
        if cached is not None:
            return cached
        base = _atlas(category).get(stem)
        if base is None:
            return None
        tpl = cv2.resize(base, (s, s), interpolation=cv2.INTER_AREA)
        tpl = np.ascontiguousarray(tpl.astype(np.uint8))
        out = (tpl, _mask(np, s))
        _cache_template(key, out)
        return out
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: template %s/%s@%s failed: %s",
                   category, stem, size, exc)
        return None


def _roster_names(roster):
    """Read a roster argument (RM-1625). Returns None for "no restriction"
    (roster None, or an iterable yielding nothing - the documented empty
    roster), else the list of entries read (at most _MAX_ROSTER). A bare
    str / bytes, a mapping, a non-iterable or an iterable that raises is
    UNREADABLE and reads as [] - no candidate - never as the full catalog:
    widening a roster the caller meant to restrict is the wrong-id risk."""
    if roster is None:
        return None
    if isinstance(roster, (str, bytes, bytearray, memoryview, Mapping)):
        return []
    try:
        names = list(itertools.islice(iter(roster), _MAX_ROSTER))
    except Exception:  # noqa: BLE001 - a caller's iterable may raise anything
        return []
    return names or None


def _candidate_stems(category, roster):
    """Ordered candidate stem list. A non-empty roster iterable (list, tuple,
    set, frozenset, dict view, generator) is resolved to stems through the
    _name_keys index (display names -> stems), de-duplicated; an ORDERED
    roster keeps its order, a set / frozenset resolves in catalog (sorted)
    order so a tie never depends on string-hash order. No roster or an empty
    one is the FULL sorted category catalog; an unreadable roster (see
    _roster_names) is no candidate. Empty list when the atlas is empty or no
    roster entry resolves."""
    atlas = _atlas(category)
    if not atlas:
        return []
    names = _roster_names(roster)
    if names is None:
        return sorted(atlas.keys())
    idx = _index(category)
    out = []
    seen = set()
    for r in names:
        if not isinstance(r, str):
            continue
        for k in _name_keys(r):
            stem = idx.get(k)
            if stem is not None and stem not in seen:
                seen.add(stem)
                out.append(stem)
                break
    if isinstance(roster, (set, frozenset)):
        out.sort()
    return out


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
        if math.isnan(r):  # NaN
            return 0.0
        return max(0.0, min(1.0, r))
    except Exception:  # noqa: BLE001 - fail-soft contract
        return 0.0


def score_all(crop, category="champions", roster=None):
    """Raw (stem, confidence) for EVERY candidate in `category`.

    Returns a list of (stem, confidence_float) in CANDIDATE order (roster order
    when a non-empty roster is given, else the sorted catalog). confidence is
    the UNROUNDED masked zero-mean Pearson score in [0.0, 1.0]. A candidate
    whose template cannot be built is skipped (mirrors the match_icon loop).

    This is the substrate match_icon reduces via argmax + threshold. A caller
    that needs the full distribution rather than the single best - the offline
    flip-readiness validator (nearest-confuser margins, a threshold sweep) or a
    future confidence-weighted Live-Client/CV fusion layer - uses this directly
    so there is ONE scoring code path.

    Fully fail-soft: bad input, missing cv2/numpy, unknown category, empty
    atlas, or numeric trouble -> []. Never raises."""
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001 - opencv/numpy optional
        return []
    try:
        if category not in _CATEGORY_DIRS:
            return []
        arr = np.asarray(crop)
        if arr.ndim != 3 or arr.shape[2] < 3:
            return []
        # RM-1626: a frame is not an icon crop; refuse before any copy.
        if max(int(arr.shape[0]), int(arr.shape[1])) > _MAX_CROP_EDGE:
            return []
        arr = arr[:, :, :3]
        if arr.dtype != np.uint8:
            # RM-1629: only real numbers coerce; a NaN / inf pixel is a
            # corrupt crop, refused instead of cast to platform garbage.
            if arr.dtype.kind not in "iuf":
                return []
            if arr.dtype.kind == "f" and not bool(np.isfinite(arr).all()):
                return []
            arr = np.clip(arr, 0, 255).astype(np.uint8)
        crop_rgb = np.ascontiguousarray(arr)
        height, width = int(crop_rgb.shape[0]), int(crop_rgb.shape[1])
        size = _template_size(height, width)
        if size is None or height < size or width < size:
            return []
        candidates = _candidate_stems(category, roster)
        if not candidates:
            return []
        out = []
        for stem in candidates:
            tm = _resized_template(category, stem, size)
            if tm is None:
                continue
            score = _match_score(cv2, np, crop_rgb, tm[0], tm[1])
            out.append((stem, score))
        return out
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: score_all failed soft: %s", exc)
        return []


def match_icon(crop, category="champions", roster=None, threshold=None):
    """Best single icon match for one RGB crop against a category catalog.

    crop: an (H, W, 3) RGB uint8-coercible ndarray (the RC vision crops are
      RGB; convert a fresh cv2.imread BGR result before calling).
    category: one of available_categories() ("champions" / "items" / "spells").
    roster: optional iterable of ids or display names (list, tuple, set,
      frozenset, dict view, generator); when non-empty the candidate set is
      restricted to those (resolved to stems), else the FULL catalog. A bare
      string, bytes, a mapping or a non-iterable is unreadable: no candidate,
      so (None, 0.0) - never the full catalog.
    threshold: optional confidence floor; defaults to _MATCH_THRESHOLD (0.6).

    Returns (id_or_None, confidence_float). confidence is the best score seen,
    rounded to 3 places and always in [0.0, 1.0]; id is the winning stem when
    that REPORTED confidence >= threshold, else None (RM-1628: the decision
    used the unrounded score, so 0.59996 came back as (None, 0.6)). Fully
    fail-soft: any bad input, missing dependency, or numeric trouble ->
    (None, 0.0). Never raises.

    Thin argmax + threshold reducer over score_all (single scoring path). The
    argmax uses a strict > so ties keep the first candidate in candidate order
    (roster order for an ordered roster, else catalog order)."""
    try:
        thr = _MATCH_THRESHOLD if threshold is None else _num(threshold)
        if thr is None:
            thr = _MATCH_THRESHOLD
        scored = score_all(crop, category, roster)
        if not scored:
            return (None, 0.0)
        best_id = None
        best_conf = 0.0
        for stem, score in scored:
            if score > best_conf:
                best_conf = score
                best_id = stem
        conf = round(best_conf, 3)
        if best_id is not None and conf >= thr:
            return (best_id, conf)
        return (None, conf)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("vision_template_match: match_icon failed soft: %s", exc)
        return (None, 0.0)
