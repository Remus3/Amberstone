"""Minimap champion IDENTITY via icon template match (ZOI plan spec E-1).

The blob detector (core/minimap_blob_detect.py) is presence-not-identity: it
says "a red dot is here" but not WHICH champion. This module annotates those
dots with {"champion", "identity_confidence"} by matching a small neighborhood
around each dot centroid against circle-masked champion icons - minimap icons
are CIRCULAR crops of the square DDragon portrait at minimap scale.

Contract (identify_dots):
  - ADDITIVE ONLY: never removes, reorders, or restructures dots; unmatched
    dots pass through unchanged; the SAME list object is returned.
  - roster-scoped: only the champions passed in (live: the 10 championName
    display strings from Live Client allPlayers, core/vision_tracker.py:307)
    are ever considered - NEVER the full 173-icon catalog.
  - fail-soft, NEVER raises: cv2/numpy absent, corrupt icon, malformed dots,
    bad numerics -> the input dots come back unchanged.
  - lazy cv2 import inside functions (opencv is an optional dependency).

Matching design (two-stage, per dot x roster - budget stays tiny):
  1. cv2.matchTemplate TM_CCORR_NORMED with the circular mask over a SMALL
     window around the dot centroid (never the whole crop) locates the best
     offset in the fast C path.
  2. A masked zero-mean Pearson correlation at that single offset is the
     confidence. CCORR_NORMED alone scores flat/foggy windows deceptively
     high (mean/rms of the template); Pearson is 0 on flat windows and 1.0
     on an exact paste, so the threshold is meaningful.

Templates come from data/icons/champions/<DDragonId>.png (173 on disk) and
are cached resized + circle-masked, keyed (icon stem, size). Display-name
variants ("Miss Fortune", "Kha'Zix", "Wukong") resolve through the DDragon
mirror (data/meta/ddragon_champions.json) - same multi-key index pattern as
core/champion_movespeed.py:81-92.

Live template-match quality is LIVE-GATED (a real game verifies before any
flip); the synthetic tests prove correct, gated, fail-soft plumbing.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

_log = logging.getLogger("rc.minimap_identity")

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_ICON_DIR = _DATA_DIR / "icons" / "champions"
_CHAMPS_PATH = _DATA_DIR / "meta" / "ddragon_champions.json"

# Confidence threshold (CONSERVATIVE, documented): masked zero-mean Pearson
# correlation of the circle patch vs the icon template, clamped to [0,1].
# An exact synthetic paste scores ~1.0; a flat/fog window scores 0.0; two
# DIFFERENT champion icons typically land well under 0.5. Below the threshold
# the dot gets NO champion tag - a missing identity is always safer than a
# wrong one (the MIA ring origin consumer would anchor on it).
_MATCH_THRESHOLD = 0.65

# Icon diameter as a fraction of the crop width. At the native 416px grab a
# minimap champion icon is ~27px across; at the legacy 208px coaching-frame
# crop ~14px. LIVE-GATED estimate - verified in a real game before any flip.
_ICON_FRAC = 0.065
_MIN_TPL = 8            # below this the portrait carries no signal
_MAX_TPL = 48
_SEARCH_PAD = 6         # px searched around the dot centroid (blob-centroid
                        # vs icon-center jitter); keeps the window tiny.

# Lazy caches. _ICON_INDEX: normalized champion key -> icon Path (None ==
# not built yet). _TPL_CACHE: (icon stem, size) -> (tpl_rgb, mask) uint8.
_ICON_INDEX: dict | None = None
_TPL_CACHE: dict = {}


def _reset_caches() -> None:
    """Test seam: drop the lazy caches (mirrors core/champion_movespeed.py:61)."""
    global _ICON_INDEX
    _ICON_INDEX = None
    _TPL_CACHE.clear()


def _num(v):
    """Coerce to a finite float, or None (same guard as core/zoi_influence.py)."""
    if isinstance(v, bool):
        return None
    if not isinstance(v, (int, float)):
        return None
    f = float(v)
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _name_keys(raw: str):
    """All lookup keys for one champion string: casefolded exact plus
    apostrophe / space / dot / ampersand stripped variants (the
    core/champion_movespeed.py:81-92 pattern)."""
    base = raw.casefold().strip()
    if not base:
        return
    yield base
    stripped = base
    for ch in ("'", " ", ".", "&"):
        stripped = stripped.replace(ch, "")
    if stripped and stripped != base:
        yield stripped


def _icon_index() -> dict:
    """normalized champion key -> icon Path. Built from (a) the icon dir scan
    (stem variants: "MissFortune" -> "missfortune") and (b) the DDragon mirror
    (display names: "Wukong" -> MonkeyKing.png). Empty dict on total failure;
    a missing DDragon mirror degrades to dir-scan keys only."""
    global _ICON_INDEX
    if _ICON_INDEX is not None:
        return _ICON_INDEX
    out: dict = {}
    try:
        for p in sorted(_ICON_DIR.glob("*.png")):
            for k in _name_keys(p.stem):
                out.setdefault(k, p)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.warning("minimap_identity: icon dir scan failed: %s", exc)
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        if isinstance(data, dict):
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                ddid = entry.get("id")
                if not isinstance(ddid, str) or not ddid:
                    ddid = key if isinstance(key, str) else None
                if not ddid:
                    continue
                p = _ICON_DIR / (ddid + ".png")
                if not p.is_file():
                    continue
                for form in (key, entry.get("id"), entry.get("name")):
                    if not isinstance(form, str):
                        continue
                    for k in _name_keys(form):
                        out.setdefault(k, p)
    except Exception as exc:  # noqa: BLE001 - dir-scan keys still serve
        _log.debug("minimap_identity: ddragon name index unavailable: %s", exc)
    _ICON_INDEX = out
    return out


def _icon_path(champion):
    """Icon Path for a champion name/id in any supported form, or None.
    Never raises."""
    try:
        if not isinstance(champion, str):
            return None
        idx = _icon_index()
        for k in _name_keys(champion):
            p = idx.get(k)
            if p is not None:
                return p
        return None
    except Exception:  # noqa: BLE001 - fail-soft contract
        return None


def _template_size(crop_w) -> int:
    """Icon template edge length (px) for a crop of width `crop_w`, clamped
    to [_MIN_TPL, _MAX_TPL]. Bad input -> _MIN_TPL."""
    try:
        w = float(crop_w)
    except (TypeError, ValueError):
        return _MIN_TPL
    if w != w or w <= 0:
        return _MIN_TPL
    return max(_MIN_TPL, min(_MAX_TPL, int(round(w * _ICON_FRAC))))


def _masked_template(champion, size):
    """Cached (tpl_rgb, circle_mask) uint8 arrays for `champion` at `size` px,
    or None (cv2 absent, unknown champion, unreadable icon, bad size).
    Cache key is (icon stem, size) so display-name variants share one entry.
    Never raises."""
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001 - opencv is optional
        return None
    try:
        s = int(size)
        if s < _MIN_TPL or s > _MAX_TPL:
            return None
        path = _icon_path(champion)
        if path is None:
            return None
        key = (path.stem, s)
        cached = _TPL_CACHE.get(key)
        if cached is not None:
            return cached
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            return None
        tpl = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)  # crops are RGB
        tpl = cv2.resize(tpl, (s, s), interpolation=cv2.INTER_AREA)
        yy, xx = np.ogrid[:s, :s]
        c = (s - 1) / 2.0
        mask = (((xx - c) ** 2 + (yy - c) ** 2) <= (s / 2.0) ** 2)
        mask = mask.astype(np.uint8) * 255
        out = (np.ascontiguousarray(tpl), mask)
        _TPL_CACHE[key] = out
        return out
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("minimap_identity: template %r@%r failed: %s", champion, size, exc)
        return None


def _match_score(cv2, np, win, tpl, mask) -> float:
    """Two-stage masked match score in [0,1] for one (window, template) pair.
    Stage 1 (fast C): TM_CCORR_NORMED with the circular mask locates the best
    offset inside the window. Stage 2: masked zero-mean Pearson correlation at
    that single offset is the confidence (0 on flat windows, 1.0 on an exact
    paste). Returns 0.0 on any numerical trouble."""
    try:
        res = cv2.matchTemplate(win, tpl, cv2.TM_CCORR_NORMED, mask=mask)
        finite = np.isfinite(res)
        if not bool(finite.any()):
            return 0.0
        res = np.where(finite, res, -1.0)
        idx = int(np.argmax(res))
        py, px = divmod(idx, res.shape[1])
        s = tpl.shape[0]
        patch = win[py:py + s, px:px + s]
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


def identify_dots(crop_rgb, dots, roster):
    """Annotate blob-detected minimap dots with champion identity.

    `crop_rgb` is the (H, W, 3) RGB minimap crop the dots were detected on;
    `dots` is the detect_team_dots output (each {"team", "x_frac", "y_frac",
    "px", "confidence"}); `roster` is the list of champion names/ids to
    consider (live: the 10 from Live Client allPlayers - never all 173).

    Where a CONSERVATIVE match succeeds a dot gains ADDITIVE keys
    {"champion": <roster name>, "identity_confidence": <0..1>}; every other
    dot passes through unchanged. The same list object is returned, order
    preserved. Never raises - any failure returns `dots` unchanged."""
    if not isinstance(dots, list) or not dots:
        return dots
    if not isinstance(roster, (list, tuple, set)) or not roster:
        return dots
    try:
        import cv2
        import numpy as np
    except Exception:  # noqa: BLE001 - opencv/numpy optional -> pass through
        return dots
    try:
        crop = np.asarray(crop_rgb)
        if crop.ndim != 3 or crop.shape[2] < 3:
            return dots
        if crop.dtype != np.uint8:
            crop = np.clip(crop, 0, 255).astype(np.uint8)
        crop = np.ascontiguousarray(crop[:, :, :3])
        H, W = int(crop.shape[0]), int(crop.shape[1])
        size = _template_size(W)
        if H < size or W < size:
            return dots
        templates = []
        for champ in roster:
            if not isinstance(champ, str) or not champ.strip():
                continue
            tm = _masked_template(champ.strip(), size)
            if tm is not None:
                templates.append((champ.strip(), tm[0], tm[1]))
        if not templates:
            return dots
        half = size // 2 + _SEARCH_PAD
        for d in dots:
            if not isinstance(d, dict):
                continue
            x = _num(d.get("x_frac"))
            y = _num(d.get("y_frac"))
            if x is None or y is None or not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
                continue
            cx = int(round(x * (W - 1)))
            cy = int(round(y * (H - 1)))
            top = max(0, cy - half)
            left = max(0, cx - half)
            bot = min(H, cy + half + 1)
            right = min(W, cx + half + 1)
            win = crop[top:bot, left:right]
            if win.shape[0] < size or win.shape[1] < size:
                continue
            best_name = None
            best_score = 0.0
            for name, tpl, mask in templates:
                score = _match_score(cv2, np, win, tpl, mask)
                if score > best_score:
                    best_score = score
                    best_name = name
            if best_name is not None and best_score >= _MATCH_THRESHOLD:
                d["champion"] = best_name
                d["identity_confidence"] = round(best_score, 3)
        return dots
    except Exception as exc:  # noqa: BLE001 - identity NEVER breaks presence
        _log.debug("minimap_identity: identify_dots failed soft: %s", exc)
        return dots
