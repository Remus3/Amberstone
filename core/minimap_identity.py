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
    display strings from Live Client allPlayers, as ``VisionTracker._compute_enemies`` in core/vision_tracker.py reads them)
    are ever considered - NEVER the full 173-icon catalog. A roster longer
    than _MAX_ROSTER (16, the Arena lobby) is refused whole: the dots come
    back unchanged.
  - one champion, one dot: a champion names at most as many dots per frame
    as it holds roster seats (once in SR / ARAM, several in One For All);
    spellings of one champion ("Wukong" / "MonkeyKing") share its seats. A
    dot whose best match is a champion already claimed by a better-scoring
    dot gets NO tag, never its second-best guess.
  - per-frame budget: only the first _MAX_DOTS entries are examined; the
    rest pass through untouched.
  - fail-soft, NEVER raises: cv2/numpy absent, corrupt icon, malformed dots,
    bad numerics -> the input dots come back unchanged. Tags are written only
    after every dot is scored, so a failure mid-pass leaves no dot tagged.
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
``_name_keys`` in core/champion_movespeed.py.

Live template-match quality is LIVE-GATED (a real game verifies before any
flip); the synthetic tests prove correct, gated, fail-soft plumbing.

ASCII only (repo hard rule). No em-dashes.
"""
from __future__ import annotations

import json
import logging
import math
import numbers
import re
from pathlib import Path

from core.failed_load_gate import FailedLoadGate

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
_MATCH_THRESHOLD = 0.55  # live-tuned 2026-07-08: 568px native grab catches real matches at ~0.57

# Champion minimap icon size in FIXED screen pixels. Minimap icons are drawn at
# a constant size independent of the minimap scale / crop resolution (unlike the
# crop itself, which scales with the native render size and minimap zoom). Tuned
# at the 416px native grab (2560x1440, MinimapScale=1.62): champion icons are
# ~27px across. Using a FRACTION of crop width (the old _ICON_FRAC=0.065) was
# wrong: a 2560 render produces a 568px crop and the fraction would request a
# 37px template, overshooting the real 27px icon and breaking the match.
_ICON_PX = 27           # fixed template edge length in px
_MIN_TPL = 8            # below this the portrait carries no signal
_MAX_TPL = 48
_SEARCH_PAD = 6         # px searched around the dot centroid (blob-centroid
                        # vs icon-center jitter); keeps the window tiny.

# Budget caps (S144-T-587). The live roster is <= 10 names (Arena seats 16);
# the live detector emits <= 2 * _MAX_PER_TEAM = 10 dots. A longer roster is a
# caller bug that would turn the per-frame pass into a catalog scan, so it is
# refused whole rather than silently truncated; dots past the budget are
# passed through unexamined.
_MAX_ROSTER = 16
_MAX_DOTS = 64

# A DDragon champion id is one plain token ("MonkeyKing", "KSante"); measured
# 173/173 ids in data/meta/ddragon_champions.json match. Anything else (a
# separator, "..", a drive) would join onto _ICON_DIR as a path OUTSIDE it.
_DDRAGON_ID_RE = re.compile(r"[A-Za-z0-9_]{1,64}")

# Lazy caches. _ICON_INDEX: normalized champion key -> icon Path (None ==
# not built yet). _TPL_CACHE: (icon stem, size) -> (tpl_rgb, mask) uint8.
_ICON_INDEX: dict | None = None
_TPL_CACHE: dict = {}
# RM-443: an index built while either source failed is served but NOT cached -
# retried after the gate's backoff, warned once per failure streak
# (core/failed_load_gate.py). A clean build is cached as before.
_ICON_INDEX_GATE = FailedLoadGate()
# The partial index a failed build produced, served during its backoff.
_PARTIAL_ICON_INDEX: dict = {}
# RM-450: per-icon-file gates for _masked_template. An icon is only rewritten
# by the icon pipeline, so a 60 s window (not the gate's 5 s file default)
# keeps a corrupt PNG to one decode per minute on the per-frame path while a
# refreshed icon still heals without a restart.
_ICON_RETRY_AFTER_S = 60.0
_TPL_GATES: dict = {}


def _reset_caches() -> None:
    """Test seam: drop the lazy caches (mirrors ``_reset_caches`` in core/champion_movespeed.py)."""
    global _ICON_INDEX, _PARTIAL_ICON_INDEX
    _ICON_INDEX = None
    _PARTIAL_ICON_INDEX = {}
    _TPL_CACHE.clear()
    _ICON_INDEX_GATE.reset()
    _TPL_GATES.clear()


def _num(v):
    """Coerce to a finite float, or None (same guard as core/zoi_influence.py).
    Any real number is accepted (numpy float32 included); bool, numpy bool,
    non-numbers, NaN / inf and an int too large for a float are None."""
    if isinstance(v, bool) or not isinstance(v, numbers.Real):
        return None
    try:
        f = float(v)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(f):  # NaN / inf
        return None
    return f


def _ddragon_id(*candidates):
    """The first candidate that is a plain DDragon id token, or None."""
    for c in candidates:
        if isinstance(c, str) and _DDRAGON_ID_RE.fullmatch(c):
            return c
    return None


def _name_keys(raw: str):
    """All lookup keys for one champion string: casefolded exact plus
    apostrophe / space / dot / ampersand stripped variants (the
    ``_name_keys`` pattern of core/champion_movespeed.py)."""
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
    global _ICON_INDEX, _PARTIAL_ICON_INDEX
    if _ICON_INDEX is not None:
        return _ICON_INDEX
    if not _ICON_INDEX_GATE.should_attempt():
        # Inside the backoff after a failed build: serve the partial index
        # that build produced (dir-scan keys) without touching the disk.
        return _PARTIAL_ICON_INDEX
    out: dict = {}
    failures: list[str] = []
    try:
        for p in sorted(_ICON_DIR.glob("*.png")):
            for k in _name_keys(p.stem):
                out.setdefault(k, p)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        failures.append(f"icon dir scan failed: {exc}")
    try:
        raw = json.loads(_CHAMPS_PATH.read_text(encoding="utf-8"))
        data = raw.get("data", raw)
        if isinstance(data, dict):
            for key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                # Contained: only a plain id token is joined onto _ICON_DIR
                # (an absolute or ".." id used to index any .png on disk).
                ddid = _ddragon_id(entry.get("id"), key)
                if ddid is None:
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
        failures.append(f"ddragon name index unavailable: {exc}")
    if failures:
        if _ICON_INDEX_GATE.record_failure():
            _log.warning("minimap_identity: %s", "; ".join(failures))
        _PARTIAL_ICON_INDEX = out
        return out
    _ICON_INDEX_GATE.record_success()
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
    to [_MIN_TPL, _MAX_TPL]. Returns the FIXED _ICON_PX (2026-07-08: champion
    minimap icons are constant size, not proportional to the crop). Bad input
    (bool, non-number, NaN / inf, <= 0, an int too large for a float) ->
    _MIN_TPL."""
    if isinstance(crop_w, bool):
        return _MIN_TPL
    try:
        w = float(crop_w)
    except (OverflowError, TypeError, ValueError):
        return _MIN_TPL
    if not math.isfinite(w) or w <= 0:
        return _MIN_TPL
    return max(_MIN_TPL, min(_MAX_TPL, _ICON_PX))


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
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        _log.debug("minimap_identity: template %r@%r failed: %s", champion, size, exc)
        return None
    # RM-450: an unreadable icon used to be re-read (and re-decoded) on every
    # call - per dot, per frame. One gate per icon file, shared by every size.
    gate = _TPL_GATES.setdefault(str(path), FailedLoadGate(_ICON_RETRY_AFTER_S))
    if not gate.should_attempt():
        return None
    try:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise OSError(f"unreadable icon {path}")
        tpl = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)  # crops are RGB
        tpl = cv2.resize(tpl, (s, s), interpolation=cv2.INTER_AREA)
        yy, xx = np.ogrid[:s, :s]
        c = (s - 1) / 2.0
        mask = (((xx - c) ** 2 + (yy - c) ** 2) <= (s / 2.0) ** 2)
        mask = mask.astype(np.uint8) * 255
        out = (np.ascontiguousarray(tpl), mask)
    except Exception as exc:  # noqa: BLE001 - fail-soft contract
        if gate.record_failure():
            _log.warning("minimap_identity: template %r@%r failed: %s", champion, size, exc)
        return None
    gate.record_success()
    _TPL_CACHE[key] = out
    return out


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
        if math.isnan(r):  # NaN
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
    dot passes through unchanged. A champion tags at most as many dots as it
    holds roster seats (the best-scoring dots win; ties go to the earlier
    dot). The same list object is returned, order preserved. Never raises -
    any failure returns `dots` unchanged, with no dot tagged."""
    if not isinstance(dots, list) or not dots:
        return dots
    if not isinstance(roster, (list, tuple, set, frozenset)) or not roster:
        return dots
    if len(roster) > _MAX_ROSTER:
        _log.debug("minimap_identity: roster of %d exceeds %d, identity skipped",
                   len(roster), _MAX_ROSTER)
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
        crop = crop[:, :, :3]
        if crop.dtype != np.uint8:
            if crop.dtype.kind not in "biuf":
                return dots
            # NaN / inf have no uint8 value (the bare cast is undefined and
            # warns): map them to black / white before the clip.
            crop = np.nan_to_num(crop.astype(np.float64), nan=0.0,
                                 posinf=255.0, neginf=0.0)
            crop = np.clip(crop, 0, 255).astype(np.uint8)
        crop = np.ascontiguousarray(crop)
        H, W = int(crop.shape[0]), int(crop.shape[1])
        size = _template_size(W)
        if size > H or size > W:
            return dots
        # One entry per CHAMPION (icon stem), whatever spelling the roster
        # used; its seat count is the per-frame tag quota.
        templates: dict = {}
        for champ in roster:
            if not isinstance(champ, str) or not champ.strip():
                continue
            name = champ.strip()
            path = _icon_path(name)
            if path is None:
                continue
            entry = templates.get(path.stem)
            if entry is not None:
                entry[3] += 1
                continue
            tm = _masked_template(name, size)
            if tm is not None:
                templates[path.stem] = [name, tm[0], tm[1], 1]
        if not templates:
            return dots
        half = size // 2 + _SEARCH_PAD
        candidates = []  # (score, dot index, stem)
        for i, d in enumerate(dots[:_MAX_DOTS]):
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
            best_stem = None
            best_score = 0.0
            for stem, (_name, tpl, mask, _seats) in templates.items():
                score = _match_score(cv2, np, win, tpl, mask)
                if score > best_score:
                    best_score = score
                    best_stem = stem
            if best_stem is not None and best_score >= _MATCH_THRESHOLD:
                candidates.append((best_score, i, best_stem))
        # Best-scoring dots claim their champion first; a dot whose best
        # champion has no seat left stays untagged (never its second guess).
        candidates.sort(key=lambda c: (-c[0], c[1]))
        claimed: dict = {}
        tags = []
        for score, i, stem in candidates:
            used = claimed.get(stem, 0)
            if used >= templates[stem][3]:
                continue
            claimed[stem] = used + 1
            tags.append((i, templates[stem][0], round(score, 3)))
        for i, name, conf in tags:
            dots[i]["champion"] = name
            dots[i]["identity_confidence"] = conf
        return dots
    except Exception as exc:  # noqa: BLE001 - identity NEVER breaks presence
        _log.debug("minimap_identity: identify_dots failed soft: %s", exc)
        return dots
