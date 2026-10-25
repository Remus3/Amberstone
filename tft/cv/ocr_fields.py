"""Deterministic OCR reads of the TFT HUD (TFT program section 3.2 stage 4, slice TFT-04).

LLM-free. Every field comes back as a value envelope (section 1.1):
``FieldValue(value, conf, src)`` with ``src`` ``ocr`` (a Tesseract read that
passed its field's validation) or ``absent`` (value None - the panel is hidden,
the region holds no text, or the read failed validation; never 0). Validation
refuses rather than guesses: odds must sum to 100 +- 1, scoreboard rows must keep
the standings order, digit reads must match the crop's glyph count, the local
HP needs two recipes to agree, names must match a closed vocabulary.

Accuracy on the recorded corpus is measured by the TFT-06 harness:
``python tools/tft_cv_accuracy.py --corpus <match dir> --extractor
tft.cv.ocr_fields:extract``.

Fields (``FIELDS``): label / stage / round, timer, gold, level, xp_cur / xp_max,
streak, odds (five shop-odds percents), shop (five offers), own_hp, scoreboard
(the seven opponent HP rows) and traits (the trait panel rows).

Tesseract sits behind the ``OcrEngine`` seam (``engine.read(img, field=...,
allowlist=..., psm=...) -> str``), so unit tests drive every parser, validator and
layout gate with a fake engine and no Tesseract install. ``TesseractEngine`` runs
``tesseract.exe stdin stdout`` per crop with CREATE_NO_WINDOW and
BELOW_NORMAL_PRIORITY_CLASS, one OpenMP thread, a hard timeout, and at most
``MAX_WORKERS`` (2) concurrent calls - OCR is CPU-heavy and the operator is
playing on the same box.

Closed vocabularies: shop names match the set roster and trait names the set's
trait list (``tft/tft_set.py`` ``load_cdragon``) by edit distance; an offer whose
name is not a roster unit is a ``special`` card (Set 18 sells one-off effect cards
in the shop). Player names on the scoreboard are never read.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from itertools import product
from typing import Any, Callable, Iterable, Protocol

from tft.cv import EXTRACTOR_VERSION
from tft.cv.layout import Layout, classify
from tft.cv.profile import Profile, load_profile

_log = logging.getLogger("rc.tft.cv.ocr")

SRC_OCR = "ocr"
SRC_ABSENT = "absent"

MAX_WORKERS = 2
TESS_TIMEOUT_S = 10.0
_CREATE_NO_WINDOW = 0x08000000
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000

FIELDS = ("stage", "timer", "gold", "level", "xp", "streak", "odds", "shop",
          "own_hp", "scoreboard", "traits")

# Base confidence per field (section 3.4: "calibrated per field from the
# accuracy harness"). Seeded from the TFT-04 tuning run on the EVEN frames of
# corpus 20261025-070350 (accuracy of answered reads, capped at 0.98); the
# TFT-06 harness (tools/tft_cv_accuracy.py) re-calibrates them per match.
FIELD_CONF = {
    "stage": 0.97, "timer": 0.98, "gold": 0.97, "level": 0.98, "xp": 0.98,
    "streak": 0.98, "odds": 0.98, "shop": 0.98, "own_hp": 0.98,
    "scoreboard": 0.9, "traits": 0.98,
}

DIGITS = "0123456789"
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'"

# A crop whose brightest text-channel percentile stays under this has no glyphs:
# skip the Tesseract call and report absent (empty trait rows, hidden digits).
TEXT_SIGNAL_MIN = 120
DIM_TEXT_MIN = 60
DIM_TEXT_CONTRAST = 40
# The Prep recipes were tuned on 1280x720 relay frames; their upscale factors are
# normalised to this width so a 1920x1080 or 2560x1440 crop is not over-upscaled.
TUNED_FRAME_W = 1280


# ---------------------------------------------------------------------------
# Value envelope


@dataclass(frozen=True)
class FieldValue:
    value: Any = None
    conf: float = 0.0
    src: str = SRC_ABSENT
    reason: str = ""

    @property
    def present(self) -> bool:
        return self.src != SRC_ABSENT

    def envelope(self) -> dict:
        out = {"value": self.value, "conf": round(self.conf, 3), "src": self.src}
        if self.reason:
            out["reason"] = self.reason
        return out


def absent(reason: str) -> FieldValue:
    return FieldValue(None, 0.0, SRC_ABSENT, reason)


def _ocr_value(value, conf: float, src: str = SRC_OCR) -> FieldValue:
    return FieldValue(value, max(0.0, min(1.0, conf)), src)


# ---------------------------------------------------------------------------
# OCR engine seam


class OcrEngine(Protocol):
    def read(self, img, *, field: str, allowlist: str = "", psm: int = 7) -> str: ...


def _tesseract_cmd() -> str | None:
    try:
        from core.vision_tesseract import _tesseract_candidates
        cands = list(_tesseract_candidates())
    except Exception:  # noqa: BLE001 - optional shared resolver
        cands = [os.environ.get("RC_TESSERACT_CMD") or "",
                 r"C:\Program Files\Tesseract-OCR\tesseract.exe"]
    for cand in cands:
        if cand and os.path.isfile(cand):
            return cand
    return shutil.which("tesseract")


class TesseractEngine:
    """Tesseract CLI per crop: PNG on stdin, text on stdout; never raises."""

    def __init__(self, cmd: str | None = None, timeout_s: float = TESS_TIMEOUT_S):
        self.cmd = cmd if cmd is not None else _tesseract_cmd()
        self.timeout_s = timeout_s
        self._warned = False
        self._lock = threading.Lock()

    def available(self) -> bool:
        return bool(self.cmd) and os.path.isfile(self.cmd)

    def _warn_once(self, msg: str, *args) -> None:
        with self._lock:
            if self._warned:
                return
            self._warned = True
        _log.warning(msg, *args)

    def read(self, img, *, field: str, allowlist: str = "", psm: int = 7) -> str:
        if not self.available():
            self._warn_once("TFT OCR: tesseract not found; fields read absent")
            return ""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        args = [self.cmd, "stdin", "stdout", "--psm", str(int(psm))]
        if allowlist:
            args += ["-c", f"tessedit_char_whitelist={allowlist}"]
        env = dict(os.environ)
        env["OMP_THREAD_LIMIT"] = "1"
        flags = 0
        if os.name == "nt":
            flags = _CREATE_NO_WINDOW | _BELOW_NORMAL_PRIORITY_CLASS
        try:
            res = subprocess.run(args, input=buf.getvalue(), capture_output=True,
                                 timeout=self.timeout_s, env=env, creationflags=flags,
                                 check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            self._warn_once("TFT OCR: tesseract call failed (%s): %s", field, exc)
            return ""
        if res.returncode != 0:
            self._warn_once("TFT OCR: tesseract exit %s on %s", res.returncode, field)
            return ""
        return res.stdout.decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Preprocessing (pure PIL)


def _channel(img, mode: str):
    """Greyscale view that makes the field's text brightest.

    ``gray`` luminance; ``max`` brightest channel (coloured text: the odds strip);
    ``min`` darkest channel (white text on a coloured plate: shop names)."""
    from PIL import ImageChops

    rgb = img.convert("RGB")
    if mode == "gray":
        return rgb.convert("L")
    r, g, b = rgb.split()
    if mode == "max":
        return ImageChops.lighter(ImageChops.lighter(r, g), b)
    if mode == "min":
        return ImageChops.darker(ImageChops.darker(r, g), b)
    raise ValueError(f"unknown channel mode {mode!r}")


def percentile(gray, q: float) -> int:
    hist = gray.histogram()[:256]
    total = sum(hist)
    if total <= 0:
        return 0
    want = q * total
    run = 0
    for level, count in enumerate(hist):
        run += count
        if run >= want:
            return level
    return 255


def otsu_threshold(gray) -> int:
    hist = gray.histogram()[:256]
    total = sum(hist)
    if total <= 0:
        return 128
    sum_all = sum(i * h for i, h in enumerate(hist))
    w_b = 0
    sum_b = 0.0
    best_t, best_var = 128, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def has_text_signal(crop, channel: str = "gray", minimum: int = TEXT_SIGNAL_MIN) -> bool:
    """Cheap pre-check before a Tesseract call: bright glyphs, or (under a dimming
    overlay such as settings / team planner / augment choice, measured p98 80-110
    over a ~25 backdrop) glyphs that still stand 40+ levels above the median."""
    g = _channel(crop, channel)
    p98 = percentile(g, 0.98)
    if p98 >= minimum:
        return True
    return p98 >= DIM_TEXT_MIN and p98 - percentile(g, 0.5) >= DIM_TEXT_CONTRAST


def clear_border(bw, edges: str = "ltrb"):
    """Whiten every black component touching the named crop edges (box frames, the
    neighbouring slot's icon) so only free-standing glyphs reach Tesseract.

    ``edges`` picks the sides (l, t, r, b); trait names skip the bottom so that a
    descender cut by the box keeps its glyph."""
    from PIL import ImageDraw

    w, h = bw.size
    px = bw.load()
    edge: list = []
    if "t" in edges:
        edge += [(x, 0) for x in range(w)]
    if "b" in edges:
        edge += [(x, h - 1) for x in range(w)]
    if "l" in edges:
        edge += [(0, y) for y in range(h)]
    if "r" in edges:
        edge += [(w - 1, y) for y in range(h)]
    for xy in edge:
        if px[xy] == 0:
            ImageDraw.floodfill(bw, xy, 255)
    return bw


@dataclass(frozen=True)
class Prep:
    """One preprocessing recipe (tuned per field on the corpus EVEN frames).

    ``k`` raises the Otsu threshold toward white (thinner strokes for the tiny
    scoreboard digits); ``height`` rescales the ink bounding box to that many
    pixels (Tesseract reads short tokens better at a fixed glyph height);
    ``blur`` is a Gaussian radius applied after a bicubic upscale; ``channel`` is
    the ``_channel`` view; ``edges`` the sides ``clear_border`` cleans;
    ``adaptive`` = (box radius, offset) switches Otsu for a local threshold
    (glyph brighter than its neighbourhood mean by more than ``offset``);
    ``trim`` drops edge-glued bright column runs first (``trim_edge_runs``)."""

    scale: int = 4
    k: float = 0.0
    height: int | None = None
    blur: float = 0.0
    psm: int = 7
    channel: str = "gray"
    edges: str = "ltrb"
    adaptive: tuple | None = None
    trim: bool = False


PREP_DEFAULT = Prep()
PREP_ODDS = (Prep(scale=8, blur=2.0, height=40, trim=True), Prep(trim=True),
             Prep(height=40, trim=True))
PREP_SCORE = (Prep(k=0.3, height=96, psm=13), Prep(k=0.3, height=64, psm=13),
              Prep(k=0.3, height=40))
PREP_OWN_HP = (PREP_DEFAULT, Prep(k=0.3, height=64, psm=13))
PREP_TRAIT_COUNT = Prep(k=0.3, height=40, psm=13)
TRAIT_ONE_ADAPTIVE = (10, 20)
# Trait names sit on a translucent plate whose backdrop (sky, arena floor) is
# often brighter than an inactive trait's grey text: a global threshold loses
# those rows, a local one keeps them (corpus even frames: 0.74 -> 0.92 rows).
PREP_TRAIT_NAME = Prep(edges="ltr", adaptive=(10, 20))


def _scaled(size: tuple, scale: float) -> tuple[int, int]:
    return (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))


def binarize(crop, *, channel: str = "gray", scale: float = 4, threshold: int | None = None,
             k: float = 0.0, blur: float = 0.0, edges: str = "ltrb",
             adaptive: tuple | None = None):
    """Upscaled black-glyphs-on-white image (no padding), the polarity Tesseract prefers.

    Otsu picks the threshold unless one is given. Text is assumed to be the
    minority class: when more than half the crop lands on the bright side, the
    glyphs are the dark class (grey text over a bright backdrop) and polarity
    flips. ``adaptive`` = (radius, offset) uses a local-mean threshold instead.
    Components touching the crop edge on the ``edges`` sides are cleared."""
    from PIL import Image, ImageChops, ImageFilter, ImageOps

    if adaptive:
        radius, offset = adaptive
        g = _channel(crop, channel)
        g = g.resize(_scaled(g.size, scale), Image.LANCZOS)
        diff = ImageChops.subtract(g, g.filter(ImageFilter.BoxBlur(radius)))
        bw = diff.point(lambda p: 0 if p > offset else 255)
        return clear_border(bw, edges) if edges else bw
    g = _channel(crop, channel)
    g = ImageOps.autocontrast(g, cutoff=1)
    size = _scaled(g.size, scale)
    g = g.resize(size, Image.BICUBIC if blur else Image.LANCZOS)
    if blur:
        g = g.filter(ImageFilter.GaussianBlur(blur))
    t = otsu_threshold(g) if threshold is None else threshold
    hist = g.histogram()[:256]
    text_is_bright = sum(hist[t + 1:]) <= sum(hist) / 2
    if text_is_bright:
        t = min(254, int(t + k * (255 - t)))
        bw = g.point(lambda p: 0 if p > t else 255)
    else:
        t = max(1, int(t - k * t))
        bw = g.point(lambda p: 255 if p > t else 0)
    if edges:
        bw = clear_border(bw, edges)
    return bw


def trim_edge_runs(crop, channel: str = "gray"):
    """Drop the bright column run touching the left / right edge of a crop.

    The odds slots straddle the cost-tier icons (their x shifts with the percent
    widths): the icon fragment is a bright run glued to the crop edge, and the
    percent text starts after a dark gap. Trimming at column level, before any
    threshold, keeps a bright icon from skewing Otsu against dim (magenta) text."""
    g = _channel(crop, channel)
    w, h = g.size
    if w < 4:
        return crop
    level = (percentile(g, 0.5) + percentile(g, 0.98)) / 2
    px = g.load()
    col = [max(px[x, y] for y in range(h)) for x in range(w)]
    span = max(2, min(w // 2, int(0.9 * h)))   # an icon fragment is at most ~a glyph wide
    left, right = 0, w
    if col[0] > level:
        while left < w and col[left] > level:
            left += 1
        if left > span:
            # the icon run merged into the text (JPEG blur kept the gap lit):
            # cut at the darkest column of the leading window instead
            left = min(range(1, span), key=lambda x: (col[x], x)) + 1
    if col[-1] > level:
        while right > left and col[right - 1] > level:
            right -= 1
        if w - right > span:
            right = min(range(w - span, w - 1), key=lambda x: (col[x], -x))
    if right - left < 3:
        return crop
    return crop.crop((left, 0, right, h))


def preprocess(crop, *, channel: str = "gray", scale: float = 4, threshold: int | None = None,
               pad: int = 8, edges: str = "ltrb", k: float = 0.0, height: int | None = None,
               blur: float = 0.0, adaptive: tuple | None = None, trim: bool = False):
    """``binarize`` + optional ink-box height normalisation + white padding."""
    from PIL import Image, ImageOps

    if trim:
        crop = trim_edge_runs(crop, channel)
    bw = binarize(crop, channel=channel, scale=scale, threshold=threshold, k=k, blur=blur,
                  edges=edges, adaptive=adaptive)
    if trim:
        bw = drop_flat_fragments(bw)
    if height:
        box = ImageOps.invert(bw).getbbox()
        if box:
            bw = bw.crop(box)
            r = height / max(1, bw.height)
            bw = bw.resize((max(1, int(bw.width * r)), height), Image.LANCZOS)
            bw = bw.point(lambda p: 0 if p < 128 else 255)
            pad = max(pad, 12)
    return ImageOps.expand(bw, border=pad, fill=255)


def ink_components(bw) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of the black 8-connected components of a binarised image."""
    return [box for box, _seed in _components(bw)]


def _components(bw) -> list[tuple[tuple[int, int, int, int], tuple[int, int]]]:
    """(bounding box, one pixel inside) per black 8-connected component."""
    w, h = bw.size
    px = bw.load()
    seen = bytearray(w * h)
    boxes = []
    for y in range(h):
        for x in range(w):
            if px[x, y] != 0 or seen[y * w + x]:
                continue
            stack = [(x, y)]
            seen[y * w + x] = 1
            x0 = x1 = x
            y0 = y1 = y
            while stack:
                cx, cy = stack.pop()
                x0, x1, y0, y1 = min(x0, cx), max(x1, cx), min(y0, cy), max(y1, cy)
                for nx in (cx - 1, cx, cx + 1):
                    for ny in (cy - 1, cy, cy + 1):
                        if 0 <= nx < w and 0 <= ny < h and not seen[ny * w + nx] \
                                and px[nx, ny] == 0:
                            seen[ny * w + nx] = 1
                            stack.append((nx, ny))
            boxes.append(((x0, y0, x1 + 1, y1 + 1), (x, y)))
    return boxes


def glyph_boxes(bw, min_height_frac: float = 0.5) -> list[tuple[int, int, int, int]]:
    """Left-to-right boxes of the full-height glyphs (minus signs and specks excluded)."""
    boxes = ink_components(bw)
    if not boxes:
        return []
    tallest = max(b[3] - b[1] for b in boxes)
    return sorted((b for b in boxes if (b[3] - b[1]) >= min_height_frac * tallest),
                  key=lambda b: b[0])


def _thin(box) -> bool:
    return (box[2] - box[0]) / max(1, box[3] - box[1]) < 0.45


def reconcile_digits(text: str, glyphs: list) -> str | None:
    """Check a digit read against the glyph count of the crop.

    Tesseract drops a thin ``1`` in this small HUD font ("61" read as "6"). When
    the read is short by exactly the number of thin, 1-shaped glyphs, the 1s are
    put back at their positions; any other count mismatch is refused (None)
    rather than returned as a wrong number. No glyph count (no ink) passes the
    read through unchanged."""
    s = re.sub(r"[^0-9-]", "", text or "")
    sign = "-" if s.startswith("-") else ""
    digits = s.lstrip("-")
    if not glyphs:
        return s or None
    if not digits:
        return None
    n = len(glyphs)
    if len(digits) == n:
        return sign + digits
    ones = [i for i, g in enumerate(glyphs) if _thin(g)]
    if ones and len(digits) == n - len(ones):
        it = iter(digits)
        return sign + "".join("1" if i in ones else next(it) for i in range(n))
    return None


def drop_flat_fragments(bw):
    """Whiten flat slivers (wider than tall, under a third of the tallest glyph):
    the bottom edge of a cost-tier icon left after trimming, never a digit."""
    from PIL import ImageDraw

    comps = _components(bw)
    if not comps:
        return bw
    tallest = max(b[3] - b[1] for b, _ in comps)
    for (x0, y0, x1, y1), seed in comps:
        if (y1 - y0) < tallest / 3 and (x1 - x0) > (y1 - y0):
            ImageDraw.floodfill(bw, seed, 255)
    return bw


def is_lone_one(bw, min_height_frac: float = 0.4) -> bool:
    """A single tall, thin glyph: the digit 1, which Tesseract drops when it
    stands alone (trait counts). Shape rule only - no glyph template."""
    boxes = [b for b in ink_components(bw) if (b[3] - b[1]) >= min_height_frac * bw.height]
    if len(boxes) != 1:
        return False
    x0, y0, x1, y1 = boxes[0]
    return (x1 - x0) / max(1, y1 - y0) < 0.45


# ---------------------------------------------------------------------------
# Pure parsers / validators


_STAGE = re.compile(r"^(\d)\s*-\s*(\d)$")


def parse_stage(text: str) -> tuple[int, int] | None:
    s = re.sub(r"[^0-9-]", "", text or "")
    m = _STAGE.match(s)
    if not m:
        return None
    stage, rnd = int(m.group(1)), int(m.group(2))
    if not (1 <= stage <= 9 and 1 <= rnd <= 9):
        return None
    return stage, rnd


def parse_int(text: str, lo: int, hi: int) -> int | None:
    digits = re.sub(r"[^0-9]", "", text or "")
    if not digits or len(digits) > len(str(hi)):
        return None
    v = int(digits)
    return v if lo <= v <= hi else None


def parse_percent(text: str) -> int | None:
    s = (text or "").strip()
    m = re.match(r"^(\d{1,3})\s*%?", s)
    if not m:
        return None
    v = int(m.group(1))
    return v if 0 <= v <= 100 else None


# XP-bar maxima measured on the Set 18 HUD (QA_REPORT section 5, corpus
# 20261025-070350): L4 10, L5 20, L6 36, L7 56, L8 / L9 68. Used ONLY to split
# an XP read whose separator glyph was lost; a read with the glyph never needs it.
XP_MAX_KNOWN = (2, 6, 10, 20, 36, 56, 68, 80, 84)


def parse_xp(text: str) -> tuple[tuple[int, int] | None, bool]:
    """(xp_cur, xp_max), and whether the split was recovered without the glyph."""
    s = re.sub(r"[^0-9/]", "", text or "")
    if s.count("/") == 1:
        a, b = s.split("/")
        if a and b and len(a) <= 3 and len(b) <= 3:
            cur, mx = int(a), int(b)
            if 0 <= cur < mx <= 200:
                return (cur, mx), False
        return None, False
    if "/" in s or not s:
        return None, False
    splits = []
    for i in range(1, len(s)):
        a, b = s[:i], s[i:]
        if len(b) > 1 and b.startswith("0"):
            continue
        cur, mx = int(a), int(b)
        if mx in XP_MAX_KNOWN and 0 <= cur < mx:
            splits.append((cur, mx))
    if len(splits) == 1:
        return splits[0], True
    return None, False


def _norm(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def match_name(text: str, lexicon: Iterable[str], min_score: float = 0.6
               ) -> tuple[str, float] | None:
    """Closest lexicon entry by normalised edit distance, or None.

    score = 1 - distance / max(len); a tie between different names is refused."""
    t = _norm(text)
    if len(t) < 2:
        return None
    if len(t) == 2:
        # two-letter names (Vi) only match exactly: one edit is half the word
        exact = [n for n in lexicon if _norm(n) == t]
        return (exact[0], 1.0) if len(exact) == 1 else None
    best: list[tuple[float, str]] = []
    for name in lexicon:
        n = _norm(name)
        if not n:
            continue
        score = 1.0 - levenshtein(t, n) / max(len(t), len(n))
        best.append((score, name))
    if not best:
        return None
    best.sort(key=lambda x: -x[0])
    top_score, top = best[0]
    if top_score < min_score:
        return None
    if len(best) > 1 and best[1][0] == top_score and _norm(best[1][1]) != _norm(top):
        return None
    return top, top_score


# ---------------------------------------------------------------------------
# Set vocabularies


@dataclass(frozen=True)
class Vocab:
    units: dict = field(default_factory=dict)    # display name -> (apiName, cost)
    traits: dict = field(default_factory=dict)   # display name -> apiName
    items: tuple = ()                            # item / shop-card display names


_VOCAB_CACHE: dict = {}
_VOCAB_LOCK = threading.Lock()


def _base_name(name: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", name).strip()


def load_vocab(set_number: int | None = None) -> Vocab:
    """Roster + trait lexicon of a set from the tracked CDragon extract (cached)."""
    from tft import tft_set

    n = set_number if set_number is not None else tft_set.resolve_set()
    with _VOCAB_LOCK:
        if n in _VOCAB_CACHE:
            return _VOCAB_CACHE[n]
    cd = tft_set.load_cdragon(n)
    units: dict = {}
    for u in cd.get("units") or ():
        if not isinstance(u, dict):
            continue
        name, api, cost = u.get("name"), u.get("apiName"), u.get("cost")
        if isinstance(name, str) and isinstance(api, str) and isinstance(cost, int):
            units.setdefault(_base_name(name), (api, cost))
    traits: dict = {}
    for t in cd.get("traits") or ():
        if isinstance(t, dict) and isinstance(t.get("name"), str):
            traits[t["name"]] = t.get("apiName") or t["name"]
    if not traits:
        traits = {name: name for name in tft_set.trait_names(n)}
    # Set 18 sells one-off effect cards in the shop (Smurfing, Flip Frenzy, ...);
    # their names live in the extract's item list, the special-offer lexicon.
    items = tuple(sorted({i["name"] for i in cd.get("items") or ()
                          if isinstance(i, dict) and isinstance(i.get("name"), str)}))
    vocab = Vocab(units=units, traits=traits, items=items)
    with _VOCAB_LOCK:
        _VOCAB_CACHE[n] = vocab
    return vocab


# ---------------------------------------------------------------------------
# Field readers (each one crop -> engine -> parser -> envelope)


@dataclass
class _Ctx:
    img: Any
    prof: Profile
    engine: OcrEngine
    vocab: Vocab
    factor: float

    @property
    def size(self) -> tuple[int, int]:
        return (self.img.width, self.img.height)

    def crop(self, box):
        return self.img.crop(box)

    def s(self, base: float = 4) -> float:
        """Upscale factor normalised to the tuning frame width, so glyphs reach
        Tesseract at the tuned pixel size whatever the frame resolution."""
        return base * TUNED_FRAME_W / max(1, self.img.width)

    def ocr(self, crop, field_name: str, allowlist: str, prep: Prep = PREP_DEFAULT) -> str:
        pre = preprocess(crop, channel=prep.channel, scale=self.s(prep.scale), k=prep.k,
                         height=prep.height, blur=prep.blur, edges=prep.edges,
                         adaptive=prep.adaptive, trim=prep.trim)
        return self.engine.read(pre, field=field_name, allowlist=allowlist,
                                psm=prep.psm) or ""


def _read_int(ctx: _Ctx, name: str, box_name: str, lo: int, hi: int) -> FieldValue:
    crop = ctx.crop(ctx.prof.box(box_name, ctx.size))
    if not has_text_signal(crop):
        return absent("no_text")
    v = parse_int(ctx.ocr(crop, name, DIGITS), lo, hi)
    if v is None:
        return absent("unparsed")
    return _ocr_value(v, FIELD_CONF[name] * ctx.factor)


def read_own_hp(ctx: _Ctx) -> FieldValue:
    """The local player's HP box. Its layout gate is a cover probe only (the box
    narrows with the digit count), so the read must also agree with the box's
    glyph count - a stray name-plate digit cannot pass as HP."""
    crop = ctx.crop(ctx.prof.box("own_hp", ctx.size))
    if not has_text_signal(crop):
        return absent("no_text")
    glyphs = glyph_boxes(binarize(crop, scale=ctx.s()))
    reads = []
    for prep in PREP_OWN_HP:
        text = reconcile_digits(ctx.ocr(crop, "own_hp", DIGITS, prep), glyphs)
        reads.append(None if text is None else parse_int(text, 0, 200))
    if None in reads or len(set(reads)) != 1:
        # both recipes must read the same number (measured on match 3: "96" read
        # as "9" by one recipe while its glyph count also lost the 6) - refuse
        # rather than pick one
        return absent("unparsed" if set(reads) == {None} else "recipes_disagree")
    return _ocr_value(reads[0], FIELD_CONF["own_hp"] * ctx.factor)


def read_stage(ctx: _Ctx) -> FieldValue:
    crop = ctx.crop(ctx.prof.box("stage", ctx.size))
    if not has_text_signal(crop):
        return absent("no_text")
    sr = parse_stage(ctx.ocr(crop, "stage", DIGITS + "-"))
    if sr is None:
        return absent("unparsed")
    return _ocr_value(sr, FIELD_CONF["stage"] * ctx.factor)


def read_xp(ctx: _Ctx) -> FieldValue:
    crop = ctx.crop(ctx.prof.box("xp", ctx.size))
    if not has_text_signal(crop):
        return absent("no_text")
    xp, recovered = parse_xp(ctx.ocr(crop, "xp", DIGITS + "/"))
    if xp is None:
        # the thin separator survives a thinner, height-normalised binarisation more often
        xp, recovered = parse_xp(ctx.ocr(crop, "xp", DIGITS + "/", Prep(k=0.3, height=40)))
    if xp is None:
        return absent("unparsed")
    conf = FIELD_CONF["xp"] * ctx.factor * (0.7 if recovered else 1.0)
    return _ocr_value(xp, conf)


def streak_sign(icon) -> int | None:
    """+1 for the warm flame (win streak), -1 for a cold icon (loss streak), None
    when neither hue dominates the icon box."""
    from PIL import ImageChops

    rgb = icon.convert("RGB")
    r, _g, b = rgb.split()

    def count(hi, lo) -> int:
        # relative hue test so a dimming overlay (settings, planner) keeps the sign
        bright = hi.point(lambda p: 255 if p >= 80 else 0)
        ahead = ImageChops.subtract(hi, lo).point(lambda p: 255 if p >= 40 else 0)
        return ImageChops.multiply(bright, ahead).histogram()[255]

    warm, cold = count(r, b), count(b, r)
    total = max(1, rgb.width * rgb.height)
    if warm / total >= 0.04 and warm > 2 * cold:
        return 1
    if cold / total >= 0.04 and cold > 2 * warm:
        return -1
    return None


def read_streak(ctx: _Ctx) -> FieldValue:
    crop = ctx.crop(ctx.prof.box("streak", ctx.size))
    if not has_text_signal(crop):
        return absent("no_text")
    n = parse_int(ctx.ocr(crop, "streak", DIGITS), 0, 99)
    if n is None:
        return absent("unparsed")
    sign = streak_sign(ctx.crop(ctx.prof.box("streak_icon", ctx.size)))
    if sign is None:
        return absent("streak_icon_unknown")
    # the loss-streak icon colour is unverified on a real frame (no loss in the corpus)
    conf = FIELD_CONF["streak"] * ctx.factor * (1.0 if sign > 0 else 0.6)
    return _ocr_value(sign * n, conf)


def solve_odds(cands: list) -> tuple[list | None, bool]:
    """Pick one value per slot so the five sum to 100 +- 1 (section 3.3 check).

    ``cands[i]`` lists slot i's candidate reads, primary recipe first. Returns
    (values, unique): the combination with the most primary picks; None when no
    combination passes or two different ones tie."""
    if len(cands) != 5 or any(not c for c in cands):
        return None, False
    best: list = []
    best_score = -1
    for combo in product(*[list(enumerate(c)) for c in cands]):
        vals = [v for _, v in combo]
        if not 99 <= sum(vals) <= 101:
            continue
        score = sum(1 for rank, _ in combo if rank == 0)
        if score > best_score:
            best, best_score = [vals], score
        elif score == best_score and vals not in best:
            best.append(vals)
    if not best:
        return None, False
    return best[0], len(best) == 1


def read_odds(ctx: _Ctx, boxes: list) -> FieldValue:
    """Five shop-odds percents. Primary recipe first; only when the five fail the
    sum check do the fallback recipes run, and the sum then picks among reads."""
    crops = [ctx.crop(b) for b in boxes]
    if len(crops) != 5:
        return absent("unparsed")
    if not any(has_text_signal(c) for c in crops):
        return absent("no_text")
    cands: list = [[] for _ in crops]

    def run(prep: Prep) -> None:
        for i, c in enumerate(crops):
            v = parse_percent(ctx.ocr(c, "odds", DIGITS + "%", prep))
            if v is not None and v not in cands[i]:
                cands[i].append(v)

    run(PREP_ODDS[0])
    first = [c[0] if c else None for c in cands]
    if None not in first and 99 <= sum(first) <= 101:
        return _ocr_value(first, FIELD_CONF["odds"] * ctx.factor)
    for prep in PREP_ODDS[1:]:
        run(prep)
    vals, unique = solve_odds(cands)
    if vals is None:
        # last resort: the measured 5 <-> 8 confusion of this font ("15%" read as
        # "18%"), as lowest-ranked candidates; the sum and the tie rule still decide
        vals, unique = solve_odds([c + confusable_variants(c) for c in cands])
    if vals is None or not unique:
        return absent("odds_sum")
    return _ocr_value(vals, FIELD_CONF["odds"] * ctx.factor * 0.85)


_CONFUSABLE = {"5": "8", "8": "5"}


def confusable_variants(values: list) -> list:
    """Single-digit 5 <-> 8 swaps of each read, new values only, in read order."""
    out: list = []
    for v in values:
        s = str(v)
        for i, ch in enumerate(s):
            if ch in _CONFUSABLE:
                alt = int(s[:i] + _CONFUSABLE[ch] + s[i + 1:])
                if 0 <= alt <= 100 and alt not in values and alt not in out:
                    out.append(alt)
    return out


def read_shop_card(ctx: _Ctx, slot: int, boxes: dict) -> dict:
    """One shop offer: kind champion / special / empty (section 1.5 shop_offer)."""
    from PIL import ImageStat

    offer = {"slot": slot, "kind": "empty", "champion_api": None, "name": None,
             "name_text": "", "cost": None, "cost_ocr": None, "conf": 0.0}
    name_crop = ctx.crop(boxes["name"])
    art_mean = ImageStat.Stat(ctx.crop(boxes["art"]).convert("L")).mean[0]
    if not has_text_signal(name_crop, "gray", 150) and art_mean < 45:
        offer["conf"] = FIELD_CONF["shop"] * ctx.factor
        return offer
    text = ctx.ocr(name_crop, "shop_name", LETTERS)
    offer["name_text"] = text
    cost_crop = ctx.crop(boxes["cost"])
    cost = None
    if has_text_signal(cost_crop):
        cost = parse_int(ctx.ocr(cost_crop, "shop_cost", DIGITS), 0, 9)
    offer["cost_ocr"] = cost
    hit = match_name(text, ctx.vocab.units)
    if hit is not None:
        name, score = hit
        api, unit_cost = ctx.vocab.units[name]
        conf = FIELD_CONF["shop"] * ctx.factor * min(1.0, 0.4 + score * 0.6)
        if cost is not None and cost != unit_cost:
            conf *= 0.6
        offer.update(kind="champion", champion_api=api, name=name, cost=unit_cost,
                     conf=round(conf, 3))
        return offer
    card = match_name(text, ctx.vocab.items, min_score=0.75)
    if card is not None:
        offer.update(kind="special", name=card[0], cost=cost,
                     conf=round(FIELD_CONF["shop"] * ctx.factor * 0.8 * card[1], 3))
        return offer
    if len(_norm(text)) >= 3:
        offer.update(kind="special", name=text.strip(), cost=cost,
                     conf=round(FIELD_CONF["shop"] * ctx.factor * 0.4, 3))
        return offer
    offer.update(kind="unknown", conf=0.0)
    return offer


def finish_shop(offers: list) -> FieldValue:
    """Five offers -> one envelope. The shop counts as read only when at least one
    card matched a roster champion (or all five slots are empty): a strip of
    unmatched text is another overlay sitting where the shop would be (measured:
    the augment-choice screen), not a shop."""
    if not offers:
        return absent("unparsed")
    kinds = [o["kind"] for o in offers]
    if "champion" not in kinds and any(k != "empty" for k in kinds):
        return absent("no_roster_match")
    conf = min(o["conf"] for o in offers)
    return _ocr_value(offers, conf)


_SIGNED = re.compile(r"^(-?)(\d{1,3})$")


def parse_signed(text: str, lo: int, hi: int) -> int | None:
    """Signed integer (eliminated players' HP boxes print overkill as e.g. -18)."""
    m = _SIGNED.match(re.sub(r"[^0-9-]", "", text or ""))
    if not m:
        return None
    v = int(m.group(2)) * (-1 if m.group(1) else 1)
    return v if lo <= v <= hi else None


def _hp_key(hp: int) -> int:
    # eliminated players (0 or negative overkill) sort below the living in any order
    return max(hp, 0)


def ordered_rows(values: list) -> set:
    """Indices of the longest non-increasing run (by ``_hp_key``) of the read rows:
    the scoreboard is the standings, so a row breaking the order is a misread."""
    idx = [i for i, v in enumerate(values) if v is not None]
    if not idx:
        return set()
    best: dict = {}
    prev: dict = {}
    for a, i in enumerate(idx):
        best[i], prev[i] = 1, None
        for j in idx[:a]:
            if _hp_key(values[j]) >= _hp_key(values[i]) and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    end = max(idx, key=lambda i: (best[i], -i))
    keep = set()
    while end is not None:
        keep.add(end)
        end = prev[end]
    return keep


def read_scoreboard(ctx: _Ctx, boxes: list) -> FieldValue:
    """The seven opponent HP rows, top to bottom (row 1 = first row under the local box).

    Primary recipe on every row; a row that is unread or breaks the standings
    order is re-read with the fallback recipes and kept only if a candidate fits
    between its accepted neighbours."""
    crops = [ctx.crop(b) for b in boxes]
    signal = [has_text_signal(c) for c in crops]
    if not any(signal):
        return absent("no_text")
    wl = DIGITS + "-"
    glyphs = [glyph_boxes(binarize(c, scale=ctx.s(), k=PREP_SCORE[0].k)) if s else []
              for c, s in zip(crops, signal)]

    def attempt(i: int, prep: Prep) -> int | None:
        text = reconcile_digits(ctx.ocr(crops[i], "scoreboard_hp", wl, prep), glyphs[i])
        return None if text is None else parse_signed(text, -99, 200)

    vals = [attempt(i, PREP_SCORE[0]) if s else None for i, s in enumerate(signal)]
    keep = ordered_rows(vals)
    base = FIELD_CONF["scoreboard"] * ctx.factor
    confs = [base if i in keep else 0.0 for i in range(len(vals))]
    final = [v if i in keep else None for i, v in enumerate(vals)]
    for i, c in enumerate(crops):
        if final[i] is not None or not signal[i]:
            continue
        above = [final[j] for j in range(i) if final[j] is not None]
        below = [final[j] for j in range(i + 1, len(final)) if final[j] is not None]
        hi = _hp_key(above[-1]) if above else 10 ** 6
        lo = _hp_key(below[0]) if below else -(10 ** 6)
        for prep in PREP_SCORE[1:]:
            v = attempt(i, prep)
            if v is not None and lo <= _hp_key(v) <= hi:
                final[i], confs[i] = v, base * 0.85
                break
    rows = [{"row": i + 1, "hp": v, "alive": None if v is None else v > 0,
             "conf": round(confs[i], 3)} for i, v in enumerate(final)]
    read = [r for r in rows if r["hp"] is not None]
    if not read:
        return absent("unparsed")
    return _ocr_value(rows, min(r["conf"] for r in read))


def _icon_saturation(icon) -> float:
    from PIL import ImageStat

    hsv = icon.convert("RGB").convert("HSV")
    return ImageStat.Stat(hsv).mean[1]


# An active trait's hex icon is tinted (bronze / silver / gold / prismatic); an
# inactive one is a desaturated grey. Calibrated on the corpus (even frames).
TRAIT_ACTIVE_SAT = 70.0


def read_trait_count(ctx: _Ctx, crop) -> int | None:
    if not has_text_signal(crop, "gray", 100):
        return None
    # a lone 1 shows up under either threshold depending on the backdrop
    if is_lone_one(binarize(crop, scale=ctx.s(), k=PREP_TRAIT_COUNT.k)) or \
            is_lone_one(binarize(crop, scale=ctx.s(), adaptive=TRAIT_ONE_ADAPTIVE)):
        return 1
    return parse_int(ctx.ocr(crop, "trait_count", DIGITS, PREP_TRAIT_COUNT), 1, 30)


def read_trait_row(ctx: _Ctx, row: int, boxes: dict) -> dict | None:
    name_crop = ctx.crop(boxes["name"])
    if not has_text_signal(name_crop, "gray", 100):
        return None
    text = ctx.ocr(name_crop, "trait_name", LETTERS, PREP_TRAIT_NAME)
    hit = match_name(text, ctx.vocab.traits)
    if hit is None:
        return None
    name, score = hit
    count = read_trait_count(ctx, ctx.crop(boxes["count"]))
    active = _icon_saturation(ctx.crop(boxes["icon"])) >= TRAIT_ACTIVE_SAT
    conf = FIELD_CONF["traits"] * ctx.factor * min(1.0, 0.4 + score * 0.6)
    if count is None:
        conf *= 0.5
    return {"row": row, "trait": name, "trait_api": ctx.vocab.traits[name],
            "count": count, "active": active, "conf": round(conf, 3)}


def finish_traits(rows: list) -> FieldValue:
    got = [r for r in rows if r is not None]
    if not got:
        return absent("unparsed")
    return _ocr_value(got, min(r["conf"] for r in got))


# ---------------------------------------------------------------------------
# Entry points


@dataclass(frozen=True)
class FrameRead:
    fields: dict
    layout: Layout
    profile_key: str
    frame_size: tuple
    extractor_version: str = EXTRACTOR_VERSION

    def value(self, name: str):
        fv = self.fields.get(name)
        return None if fv is None else fv.value

    def envelopes(self) -> dict:
        return {k: v.envelope() for k, v in self.fields.items()}


def _all_absent(reason: str) -> dict:
    out = {}
    for name in _OUTPUT_KEYS:
        out[name] = absent(reason)
    return out


_OUTPUT_KEYS = ("label", "stage", "round", "timer", "gold", "level", "xp_cur", "xp_max",
                "streak", "odds", "shop", "own_hp", "scoreboard", "traits")
_FAILED = object()   # sentinel: a field task raised


def read_frame(img, *, profile: Profile | None = None, engine: OcrEngine | None = None,
               layout: Layout | None = None, fields: Iterable[str] | None = None,
               vocab: Vocab | None = None, set_number: int | None = None,
               workers: int = MAX_WORKERS) -> FrameRead:
    """Read the requested HUD fields from one frame (PIL image, any 16:9 size)."""
    want = tuple(fields) if fields is not None else FIELDS
    bad = [f for f in want if f not in FIELDS]
    if bad:
        raise ValueError(f"unknown TFT OCR fields: {bad}")
    if img.mode != "RGB":
        img = img.convert("RGB")
    size = (img.width, img.height)
    prof = profile if profile is not None else load_profile()
    if prof is None or not prof.fits(*size):
        return FrameRead(_all_absent("no_profile"), Layout(), "", size)
    lay = layout if layout is not None else classify(img, prof)
    ctx = _Ctx(img=img, prof=prof, engine=engine if engine is not None else TesseractEngine(),
               vocab=vocab if vocab is not None else load_vocab(set_number),
               factor=prof.conf_factor)

    def hidden(fname: str) -> bool:
        return not lay.visible(prof.panel_of(fname))

    tasks: list[tuple[str, int, Callable[[], Any]]] = []

    def add(key: str, idx: int, fn: Callable[[], Any]) -> None:
        tasks.append((key, idx, fn))

    if "stage" in want and not hidden("stage"):
        add("stage", 0, lambda: read_stage(ctx))
    if "timer" in want and not hidden("timer"):
        add("timer", 0, lambda: _read_int(ctx, "timer", "timer", 0, 99))
    if "gold" in want and not hidden("gold"):
        add("gold", 0, lambda: _read_int(ctx, "gold", "gold", 0, 999))
    if "level" in want and not hidden("level"):
        add("level", 0, lambda: _read_int(ctx, "level", "level", 1, 10))
    if "xp" in want and not hidden("xp"):
        add("xp", 0, lambda: read_xp(ctx))
    if "streak" in want and not hidden("streak"):
        add("streak", 0, lambda: read_streak(ctx))
    if "own_hp" in want and not hidden("own_hp"):
        add("own_hp", 0, lambda: read_own_hp(ctx))
    if "odds" in want and not hidden("odds"):
        add("odds", 0, lambda: read_odds(ctx, [s["text"] for s in prof.group("odds", size)]))
    if "shop" in want and not hidden("shop"):
        for i, slot in enumerate(prof.group("shop", size)):
            add("shop", i, lambda i=i, b=slot: read_shop_card(ctx, i, b))
    if "scoreboard" in want and not hidden("scoreboard"):
        add("scoreboard", 0, lambda: read_scoreboard(
            ctx, [s["hp"] for s in prof.group("scoreboard", size)]))
    if "traits" in want and not hidden("traits"):
        for i, slot in enumerate(prof.group("traits", size)):
            add("traits", i, lambda i=i, b=slot: read_trait_row(ctx, i, b))

    def safe(key: str, fn: Callable[[], Any]):
        # fail-soft: one bad crop makes its field absent, never raises into the
        # caller's poll loop (the TftStateReader OCR thread, the TFT-07 worker)
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            _log.debug("TFT OCR field %s failed: %s", key, exc)
            return _FAILED

    results: dict = {}
    n = max(1, min(int(workers), MAX_WORKERS))
    if n == 1 or len(tasks) <= 1:
        for key, idx, fn in tasks:
            results[(key, idx)] = safe(key, fn)
    else:
        with ThreadPoolExecutor(max_workers=n, thread_name_prefix="tft-ocr") as ex:
            futs = {(key, idx): ex.submit(safe, key, fn) for key, idx, fn in tasks}
            for k, fut in futs.items():
                results[k] = fut.result()
    failed = {key for (key, _idx), res in results.items() if res is _FAILED}

    out: dict = {}

    def gate(fname: str) -> FieldValue | None:
        if fname not in want:
            return absent("not_requested")
        if hidden(fname):
            return absent("panel_hidden")
        if fname in failed:
            return absent("error")
        return None

    g = gate("stage")
    if g is not None:
        for k in ("label", "stage", "round"):
            out[k] = g
    else:
        st = results[("stage", 0)]
        if st.present:
            s, r = st.value
            out["label"] = FieldValue(f"{s}-{r}", st.conf, st.src)
            out["stage"] = FieldValue(s, st.conf, st.src)
            out["round"] = FieldValue(r, st.conf, st.src)
        else:
            for k in ("label", "stage", "round"):
                out[k] = st
    for single in ("timer", "gold", "level", "streak", "own_hp"):
        g = gate(single)
        out[single] = g if g is not None else results[(single, 0)]
    g = gate("xp")
    if g is not None:
        out["xp_cur"] = out["xp_max"] = g
    else:
        xp = results[("xp", 0)]
        if xp.present:
            cur, mx = xp.value
            out["xp_cur"] = FieldValue(cur, xp.conf, xp.src)
            out["xp_max"] = FieldValue(mx, xp.conf, xp.src)
        else:
            out["xp_cur"] = out["xp_max"] = xp
    for multi in ("odds", "scoreboard"):
        g = gate(multi)
        out[multi] = g if g is not None else results[(multi, 0)]
    g = gate("shop")
    out["shop"] = g if g is not None else finish_shop(
        [results[("shop", i)] for i in range(len(prof.group("shop", size)))])
    g = gate("traits")
    out["traits"] = g if g is not None else finish_traits(
        [results[("traits", i)] for i in range(len(prof.group("traits", size)))])
    return FrameRead(out, lay, prof.key, size)


def read_fields(img, **kwargs) -> dict:
    """``read_frame(...).fields``: field name -> FieldValue."""
    return read_frame(img, **kwargs).fields


# ---------------------------------------------------------------------------
# Accuracy-harness adapter (tools/tft_cv_accuracy.py --extractor tft.cv.ocr_fields:extract)

_EXTRACT_LOCK = threading.Lock()
_EXTRACT_STATE: dict = {}


def _env(fv: FieldValue, value=None):
    if not fv.present:
        return None
    return {"value": fv.value if value is None else value, "conf": round(fv.conf, 3)}


def to_label_fields(fr: FrameRead) -> dict:
    """A FrameRead in the TFT-06 label schema (``tft_cv_labels/1`` field names).

    Fields this slice does not read (screen, occluders, buy / reroll cost, hud
    counter, scoreboard level badges, augment / item offers) are left out."""
    f = fr.fields
    out: dict = {"shop_open": fr.layout.visible("shop") if fr.layout.panels else None}
    out["stage"] = _env(f["label"])
    for key in ("timer", "level", "xp_cur", "xp_max", "gold", "streak", "odds"):
        out[key] = _env(f[key])
    out["hp_local"] = _env(f["own_hp"])
    shop = f["shop"]
    if shop.present:
        slots = []
        for o in shop.value:
            if o["kind"] == "empty":
                slots.append(None)
            elif o["kind"] in ("champion", "special"):
                slots.append({"name": o["name"], "cost": o["cost"], "kind": o["kind"]})
            else:
                slots.append({"name": o["name_text"] or "?", "cost": o["cost_ocr"]})
        out["shop"] = _env(shop, slots)
    else:
        out["shop"] = None
    sb = f["scoreboard"]
    if sb.present:
        own = f["own_hp"].value if f["own_hp"].present else None
        rows = [{"hp": own, "local": True}] + [{"hp": r["hp"]} for r in sb.value]
        out["scoreboard"] = _env(sb, rows)
    else:
        out["scoreboard"] = None
    tr = f["traits"]
    # a row whose count did not read is left out: "name:None" can never be right
    rows = [{"name": t["trait"], "count": t["count"], "active": t["active"]}
            for t in (tr.value if tr.present else ()) if t["count"] is not None]
    out["traits"] = _env(tr, rows) if rows else None
    return out


def extract(frame_path) -> dict:
    """Harness entry point: one frame file -> label-schema fields (envelopes)."""
    from PIL import Image

    with _EXTRACT_LOCK:
        if "engine" not in _EXTRACT_STATE:
            _EXTRACT_STATE["engine"] = TesseractEngine()
            _EXTRACT_STATE["profile"] = load_profile()
    with Image.open(frame_path) as im:
        img = im.convert("RGB")
    fr = read_frame(img, profile=_EXTRACT_STATE["profile"], engine=_EXTRACT_STATE["engine"])
    return to_label_fields(fr)
