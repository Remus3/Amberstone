"""
DS3 in-game legibility variant preview + contrast measurement harness.

PREPARE-ONLY. This tool exists so an operator-present session can PICK an
overlay legibility variant in minutes. It renders the overlay HUD over
synthetic backdrop proxies and measures the ACTUAL rendered contrast of the
key overlay ink, but it never decides anything and never touches a production
file. The final pick is a rendered-pixel judgement over REAL gameplay, which a
headless agent may not self-adjudicate (ROADMAP RM-122 fence, CLAUDE.md R3).

WHAT IT DOES NOT DO
    There is no League client, no live game and no archive of real game frames
    on this machine, so nothing here renders over real game pixels. The three
    backdrops are SYNTHETIC PROXIES chosen to bracket the luminance / chroma
    extremes a real frame spans. They are a screening tool, not a verdict.

WHAT IT DOES
    1. Builds three deterministic backdrop proxies (see BACKDROPS):
       bright_rift  - high-luminance sand / river at noon. Worst case for a
                      see-through backing and for thin dark strokes.
       dark_pit     - low-luminance baron pit / fog of war. Worst case for a
                      heavy dark scrim, which reads as an opaque box that
                      blocks the game rather than floating over it.
       chroma_fight - high-chroma teamfight VFX. Worst case for the
                      color-coded tier channel (doctrine rule 4 pop-out,
                      rule 10 categories-as-color).
    2. Renders the matrix {baseline + each variant} x {each backdrop} through
       the same proven mechanics as tools/pseudo_screen_overlay.py.
    3. For every cell, resolves the effective foreground and background of the
       key overlay text through getComputedStyle + a canvas round-trip (NOT by
       parsing hex out of the CSS source: web/css/themes.css declares several
       tokens in oklch() as a second declaration overriding a hex sibling, so a
       source grep measures a value the browser is not using), then computes
       WCAG 2.x contrast on the resolved sRGB.
    4. Writes a JSON report plus one PNG per cell.

VARIANT CSS IS INJECTED AT RENDER TIME (page.add_style_tag), exactly as
pseudo_screen_overlay.py injects its backdrop. web/css/overlay.css is never
modified and no variant is ever wired on by default.

Usage:
    python tools/overlay_legibility_preview.py
    python tools/overlay_legibility_preview.py --variant v1_hairline_scrim
    python tools/overlay_legibility_preview.py --backdrop bright_rift --no-shots
    python tools/overlay_legibility_preview.py --mode aram

Requires a RUNNING local dashboard at https://127.0.0.1:8888 (RC supervisor).
It does NOT need League, LCU, or a live game - the frame comes from the
committed data/ui_mock/active_match_<mode>.json fixtures.

Out (all gitignored, DO NOT commit):
    tools/pseudo_screen_out/legib_<variant>_<backdrop>_<mode>_2560.png
    tools/pseudo_screen_out/_backdrop_<name>.png
    tools/pseudo_screen_out/legibility_report.json

Companion spec: docs/qa/OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md
"""
import argparse
import io
import json
import os
import random
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from playwright.sync_api import sync_playwright

BASE = os.environ.get("RC_PSEUDO_BASE", "https://127.0.0.1:8888")
OUT_DIR = Path(__file__).resolve().parent / "pseudo_screen_out"

# Same canvas + ovscale contract as pseudo_screen_overlay.py: 2560/1920 ==
# 1440/1080 == 1.3333, so the 1920x1080 design-px widget field maps 1:1.
CANVAS_W = 2560
CANVAS_H = 1440
OVSCALE = 1.333

# Same-origin path we intercept with page.route and fulfill with the generated
# backdrop bytes. A file:// URL would be blocked from the https origin and a
# multi-hundred-KB data: URI makes add_style_tag crawl, so route + fulfill is
# the clean seam.
BACKDROP_PATH = "/__rc_legib_backdrop.png"

BACKDROP_W = 1280
BACKDROP_H = 720


# ---------------------------------------------------------------------------
# Backdrop proxies (deterministic - a re-render is comparable to a prior one)
# ---------------------------------------------------------------------------

def _value_noise(size, cells, seed):
    """Deterministic smooth value noise: a small random grid, bicubic-upscaled.

    PIL's Image.effect_noise cannot be seeded, so a re-render would produce a
    different field and two runs would not be comparable. This is seeded.
    """
    cw, ch = cells
    rnd = random.Random(seed)
    small = Image.new("L", (cw, ch))
    small.putdata([rnd.randrange(256) for _ in range(cw * ch)])
    return small.resize(size, Image.BICUBIC)


def _fbm(size, seed):
    """Four-octave fractional-brownian field in mode L, mean near 128.

    Octaves are folded with Image.blend (a C-speed lerp) rather than per-pixel
    Python arithmetic, so a 1280x720 field costs milliseconds.
    """
    layers = ((5, 3, None), (13, 8, 0.36), (41, 24, 0.22), (137, 78, 0.12))
    acc = None
    for cw, ch, weight in layers:
        octave = _value_noise(size, (cw, ch), seed + cw)
        acc = octave if acc is None else Image.blend(acc, octave, weight)
    return acc


def _ramp(field, lo, hi):
    """Map an L field (0..255) into [lo, hi] and return an L band."""
    span = (hi - lo) / 255.0
    return field.point(lambda v: max(0, min(255, int(lo + v * span))))


def _radial_mask(size, falloff=1.0):
    """White-centre / black-edge radial alpha mask at the requested size."""
    base = Image.radial_gradient("L").point(lambda v: int(255 * ((1.0 - v / 255.0) ** falloff)))
    return base.resize(size, Image.BICUBIC)


def _build_bright_rift():
    """High-luminance sand / river field. The worst case for see-through ink.

    A 0.58-alpha dark backing over a bright frame composites UP toward the
    game, so every low-alpha ink tier loses its separation exactly here.
    """
    size = (BACKDROP_W, BACKDROP_H)
    field = _fbm(size, seed=1101)
    r = _ramp(field, 150, 244)
    g = _ramp(field, 136, 232)
    b = _ramp(field, 92, 186)
    img = Image.merge("RGB", (r, g, b))
    # Specular river highlights: a handful of near-white blurred streaks.
    d = ImageDraw.Draw(img)
    rnd = random.Random(4242)
    for _ in range(14):
        x = rnd.randrange(0, BACKDROP_W)
        y = rnd.randrange(0, BACKDROP_H)
        w = rnd.randrange(90, 320)
        h = rnd.randrange(8, 26)
        d.ellipse((x, y, x + w, y + h), fill=(248, 244, 226))
    return img.filter(ImageFilter.GaussianBlur(2.0))


def _build_dark_pit():
    """Low-luminance baron pit / fog-of-war field.

    The worst case for a HEAVY backing: a near-opaque dark plate that reads as
    a premium frame over sand reads as a black rectangle punched into the game
    here, which is the doctrine rule-8 cost the operator has to weigh.
    """
    size = (BACKDROP_W, BACKDROP_H)
    field = _fbm(size, seed=2202)
    r = _ramp(field, 5, 26)
    g = _ramp(field, 7, 30)
    b = _ramp(field, 12, 46)
    img = Image.merge("RGB", (r, g, b))
    # Two dim violet pit glows so it is not a flat swatch.
    for cx, cy, rad, col in ((360, 300, 260, (58, 30, 86)), (940, 470, 200, (24, 44, 70))):
        mask = _radial_mask((rad * 2, rad * 2), falloff=1.7)
        glow = Image.new("RGB", (rad * 2, rad * 2), col)
        img.paste(glow, (cx - rad, cy - rad), mask)
    return img.filter(ImageFilter.GaussianBlur(1.5))


def _build_chroma_fight():
    """High-chroma teamfight VFX field.

    Mid luminance but very high saturation and high spatial frequency. This is
    the field that attacks the CATEGORY channel (doctrine rule 10): a red band
    marker beside a red VFX blob stops being a category and becomes noise, and
    the single-pop-out guarantee of rule 4 is what is actually at risk.
    """
    size = (BACKDROP_W, BACKDROP_H)
    r = _ramp(_fbm(size, seed=3303), 30, 175)
    g = _ramp(_fbm(size, seed=5507), 26, 160)
    b = _ramp(_fbm(size, seed=7717), 34, 185)
    img = Image.merge("RGB", (r, g, b))
    blobs = (
        (250, 200, 230, (255, 42, 60)),
        (700, 150, 190, (25, 232, 255)),
        (1010, 430, 250, (255, 60, 224)),
        (430, 560, 210, (56, 255, 122)),
        (860, 610, 160, (255, 206, 96)),
        (120, 430, 150, (140, 80, 255)),
    )
    for cx, cy, rad, col in blobs:
        mask = _radial_mask((rad * 2, rad * 2), falloff=1.3)
        glow = Image.new("RGB", (rad * 2, rad * 2), col)
        img.paste(glow, (cx - rad, cy - rad), mask)
    return img.filter(ImageFilter.GaussianBlur(1.2))


BACKDROPS = {
    "bright_rift": {
        "label": "Bright rift (river / sand at noon)",
        "why": (
            "High-luminance worst case. A see-through backing composites UP "
            "toward the game here, collapsing every low-alpha ink tier."
        ),
        "build": _build_bright_rift,
    },
    "dark_pit": {
        "label": "Dark pit (baron pit / fog of war)",
        "why": (
            "Low-luminance worst case. Text contrast is easy here; what fails "
            "is the FRAME - a heavy scrim reads as an opaque box blocking the "
            "game, the doctrine rule-8 data-ink cost."
        ),
        "build": _build_dark_pit,
    },
    "chroma_fight": {
        "label": "High-chroma teamfight VFX",
        "why": (
            "Saturation / spatial-frequency worst case. Attacks the CATEGORY "
            "colour channel (doctrine rule 10) and the single-pop-out "
            "guarantee (rule 4), not the luminance channel."
        ),
        "build": _build_chroma_fight,
    },
}


def backdrop_asset(name):
    """Return (png_bytes, mean_rgb) for a backdrop, caching the PNG on disk."""
    spec = BACKDROPS[name]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"_backdrop_{name}.png"
    img = spec["build"]()
    img.save(path, "PNG")
    small = img.resize((64, 36), Image.BILINEAR)
    px = list(small.getdata())
    n = float(len(px))
    mean = [
        round(sum(p[0] for p in px) / n, 2),
        round(sum(p[1] for p in px) / n, 2),
        round(sum(p[2] for p in px) / n, 2),
    ]
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), mean, path


# ---------------------------------------------------------------------------
# Variants. Each is a COMPLETE, self-contained overlay-scoped block, injected
# at render time. Nothing here edits web/css/overlay.css.
# ---------------------------------------------------------------------------

# Shared carve-out note: w-trinket (overlay.css:608) and w-mmrect
# (overlay.css:627) deliberately strip the widget frame and their selectors
# carry a higher specificity than the generic .ovx-widget rule, so they keep
# their transparent treatment under every variant below. That is intended - a
# glyph cue and a minimap outline must not grow a plate.
#
# SHARED PREREQUISITE, measured 2026-09-01 and true of the SHIPPED overlay:
#   web/css/panels/active_match.css:92-100
#     #view-active-match .am-pane { background: var(--surface-head); }   (1,1,0)
#   beats
#   web/css/overlay.css:217-224
#     body[data-shell="overlay"] .ovx-widget.am-pane { background: transparent; }
#                                                                      (0,3,1)
# because an id outranks any number of classes. So the three .am-pane widgets
# (w-call, w-build, w-ovds) paint an OPAQUE off-palette dashboard purple -
# getComputedStyle reports oklch(0.27 0.06 302) - while every other widget
# paints the intended Hextech rgba(22,32,46,0.58). Each variant below therefore
# repeats its backing rule at the higher `#view-active-match .am-pane.ovx-widget`
# specificity, otherwise the variant would not reach the PRIMARY widget at all.

V1_CSS = """
/* V1 HAIRLINE + SCRIM. Keep the doctrine hairline and the small radius; make
 * the BACKING backdrop-independent (0.58 -> 0.90) and add an outer dark scrim
 * ring in the existing box-shadow stack so the frame separates from any game
 * pixel WITHOUT growing the widget box. Then lift the two sub-AA faint ink
 * tiers (0.55 alpha today) off the floor. */
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget {
  background: rgba(var(--ovx-bg), 0.90);
  border: 1px solid rgba(var(--ovx-gold), 0.78);
  border-radius: 7px;
  box-shadow: inset 0 1px 0 rgba(var(--ovx-gold), 0.45),
              0 0 0 1px rgba(var(--ovx-bg-nested), 1),
              0 0 0 5px rgba(4, 6, 9, 0.38),
              0 6px 18px rgba(0, 0, 0, 0.62);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"],
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget[data-ovx-id="w-call"] {
  background: rgba(var(--ovx-bg), 0.95);
  border-color: rgba(var(--ovx-gold), 0.95);
  box-shadow: inset 0 4px 16px -4px rgba(var(--ovx-cyan), 0.45),
              inset 0 1px 0 rgba(var(--ovx-gold), 0.50),
              0 0 0 1px rgba(var(--ovx-bg-nested), 1),
              0 0 0 5px rgba(4, 6, 9, 0.42),
              0 6px 20px rgba(0, 0, 0, 0.66);
}
body[data-shell="overlay"] .ovx-widget .cd-chip,
body[data-shell="overlay"] .ovx-widget .rc-chip,
body[data-shell="overlay"] .ovx-widget .rc-co-row,
body[data-shell="overlay"] #rn-lead {
  background: rgba(var(--ovx-bg-nested), 0.96);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] #am-call-body
  > div[data-call-line="objective"] > span:last-child {
  color: rgba(var(--ovx-text), 0.80) !important;
}
body[data-shell="overlay"] #rn-lead .rc-lead-tag {
  color: rgba(var(--ovx-text), 0.80);
}
body[data-shell="overlay"] .rc-co-eta {
  color: rgba(var(--ovx-gold), 0.98);
}
"""

V2_CSS = """
/* V2 SOLID PLATE. Maximum legibility, minimum ambiguity: an effectively
 * opaque nested-dark plate, a 2px full-alpha gold border, a tighter 4px
 * radius, and a hard black keyline. Every contrast pair becomes
 * backdrop-INDEPENDENT because the plate no longer admits game pixels. */
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget {
  background: rgba(var(--ovx-bg-nested), 0.97);
  border: 2px solid rgba(var(--ovx-gold), 1);
  border-radius: 4px;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.95),
              0 8px 22px rgba(0, 0, 0, 0.75);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"],
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget[data-ovx-id="w-call"] {
  background: rgb(var(--ovx-bg-nested));
  border-color: rgba(var(--ovx-cyan), 1);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.95),
              0 0 14px -2px rgba(var(--ovx-cyan), 0.55),
              0 8px 22px rgba(0, 0, 0, 0.8);
}
body[data-shell="overlay"] .ovx-widget .cd-chip,
body[data-shell="overlay"] .ovx-widget .rc-chip,
body[data-shell="overlay"] .ovx-widget .rc-co-row,
body[data-shell="overlay"] #rn-lead {
  background: rgba(var(--ovx-bg), 0.96);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] #am-call-body
  > div[data-call-line="objective"] > span:last-child {
  color: rgba(var(--ovx-text), 0.85) !important;
}
body[data-shell="overlay"] #rn-lead .rc-lead-tag {
  color: rgba(var(--ovx-text), 0.85);
}
"""

V3_CSS = """
/* V3 OUTLINE + HALO. The opposite pole: no backing at all on the ambient
 * widgets, legibility carried by a hard dark text halo (the broadcast-subtitle
 * technique). Maximum data-ink (doctrine rule 8), minimum occlusion. The
 * PRIMARY (w-call) keeps a light 0.55 plate because it is the one element that
 * must never be ambiguous. Faint tiers cannot survive with no backing, so they
 * are promoted to near-full ink. */
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget {
  background: transparent;
  border: 1px solid rgba(var(--ovx-gold), 0.55);
  border-radius: 7px;
  box-shadow: none;
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"],
body[data-shell="overlay"] #view-active-match .am-pane.ovx-widget[data-ovx-id="w-call"] {
  background: rgba(var(--ovx-bg-nested), 0.55);
  border-color: rgba(var(--ovx-gold), 0.95);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.90);
}
body[data-shell="overlay"] .ovx-widget .cd-chip,
body[data-shell="overlay"] .ovx-widget .rc-chip,
body[data-shell="overlay"] .ovx-widget .rc-co-row,
body[data-shell="overlay"] #rn-lead {
  background: rgba(var(--ovx-bg-nested), 0.42);
}
body[data-shell="overlay"] .ovx-widget,
body[data-shell="overlay"] .ovx-widget * {
  text-shadow: 0 0 2px rgba(0, 0, 0, 0.95),
               0 0 5px rgba(0, 0, 0, 0.85),
               1px 0 0 rgba(0, 0, 0, 0.92),
               -1px 0 0 rgba(0, 0, 0, 0.92),
               0 1px 0 rgba(0, 0, 0, 0.92),
               0 -1px 0 rgba(0, 0, 0, 0.92);
}
body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] #am-call-body
  > div[data-call-line="objective"] > span:last-child {
  color: rgba(var(--ovx-text), 0.92) !important;
}
body[data-shell="overlay"] #rn-lead .rc-lead-tag {
  color: rgba(var(--ovx-text), 0.92);
}
body[data-shell="overlay"] .rc-co-eta {
  color: rgb(var(--ovx-gold));
}
"""

VARIANTS = {
    "baseline": {
        "label": "Baseline (web/css/overlay.css as shipped)",
        "optimizes": "doctrine rule 8 (data-ink) - the reference, not a proposal",
        "trades": "n/a",
        "css": "",
    },
    "v1_hairline_scrim": {
        "label": "V1 hairline + scrim",
        "optimizes": (
            "rule 1 (one-glance) and rule 8 jointly - the box does not grow, "
            "only its backing alpha and an outer scrim ring change"
        ),
        "trades": (
            "occlusion: 0.90 backing admits far less game than 0.58, so the "
            "HUD is closer to a solid panel over the dark pit"
        ),
        "css": V1_CSS,
    },
    "v2_solid_plate": {
        "label": "V2 solid plate",
        "optimizes": (
            "rule 1 absolutely - every pair is backdrop-independent, nothing "
            "can wash out at any game brightness"
        ),
        "trades": (
            "rule 8 outright, and the doctrine section-0 premise that the "
            "overlay is see-through. Reads as a dev-tool plate over dark pixels"
        ),
        "css": V2_CSS,
    },
    "v3_outline_halo": {
        "label": "V3 outline + halo",
        "optimizes": (
            "rule 8 hardest - near-zero occlusion, the game is visible through "
            "every ambient widget"
        ),
        "trades": (
            "guaranteed contrast. Computed contrast is text-vs-GAME, so it is "
            "backdrop-dependent by construction; the halo is a rendered-pixel "
            "effect that no getComputedStyle number can score"
        ),
        "css": V3_CSS,
    },
}


# ---------------------------------------------------------------------------
# In-page contrast measurement
# ---------------------------------------------------------------------------

# The ink that actually has to be read in a fight. Selectors are the live ones
# from web/css/overlay.css - see the spec doc for the file:line of each rule.
TARGETS = [
    {
        "key": "w-call ACTION verb",
        "sel": ('body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] '
                '#am-call-body > div[data-call-line="action"] > span:last-child'),
        "rule": "overlay.css:339-344 (rgb(--ovx-text), --fs-ov-call 14px/700)",
    },
    {
        "key": "w-call ACTION verb (table path)",
        "sel": ('body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] '
                "#am-call-body .am-call-thead"),
        "rule": "overlay.css:417-422 (the second ACTION render path)",
    },
    {
        "key": "w-call RIGHT-NOW",
        "sel": ('body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] '
                '#am-call-body > div[data-call-line="right-now"] > span:last-child'),
        "rule": "overlay.css:331-337 (rgb(--ovx-cyan), --fs-ov-chip 13px/600)",
    },
    {
        "key": "w-call OBJECTIVE footer",
        "sel": ('body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-call"] '
                '#am-call-body > div[data-call-line="objective"] > span:last-child'),
        "rule": "overlay.css:387-396 (rgba(--ovx-text, 0.55), --fs-ov-sigil 12px)",
    },
    {
        # w-call carries NO .am-pane-head in the shipped markup (measured: the
        # pane is .obj-chips + #am-call-body only), so the gold uppercase head
        # is sampled on w-build, which does have one.
        "key": "w-build pane head",
        "sel": ('body[data-shell="overlay"] .ovx-widget[data-ovx-id="w-build"] '
                ".am-pane-head"),
        "rule": "overlay.css:206-216 (rgba(--ovx-gold, 0.90), --fs-ov-head 11px)",
    },
    {
        "key": "w-lead value line",
        "sel": 'body[data-shell="overlay"] #rn-lead .rc-lead-line',
        "rule": "overlay.css:259-261 (--fs-sm; colour inherited from callouts.css)",
    },
    {
        "key": "w-lead tag",
        "sel": 'body[data-shell="overlay"] #rn-lead .rc-lead-tag',
        "rule": "overlay.css:262-264 (rgba(--ovx-text, 0.55))",
    },
    {
        "key": "w-callouts row line",
        "sel": 'body[data-shell="overlay"] #rn-callouts .rc-co-row .rc-co-line',
        "rule": "callouts.css base ink inside the .ovx-widget frame",
    },
    {
        "key": "w-callouts ETA chip",
        "sel": 'body[data-shell="overlay"] #rn-callouts .rc-co-eta',
        "rule": "overlay.css:274-276 (rgba(--ovx-gold, 0.85))",
    },
    {
        "key": "w-callouts ETA chip NOW",
        "sel": 'body[data-shell="overlay"] #rn-callouts .rc-co-eta.rc-co-now',
        "rule": "overlay.css:277-281 (rgb(--ovx-cyan) on rgba(--ovx-cyan, 0.18))",
    },
]

# Resolve colours through a canvas round-trip. Chromium's getComputedStyle
# preserves the authored colour space, so an oklch() token (themes.css declares
# several, often as a second declaration shadowing a hex sibling one line above)
# serialises back as "oklch(...)" and a regex would mis-read it. Painting the
# computed string onto a 1x1 canvas and reading the pixel back gives resolved,
# non-premultiplied sRGB plus the alpha, whatever syntax was authored.
MEASURE_JS = r"""(args) => {
  const backdrop = args.backdrop;   // [r,g,b] opaque, the game-pixel proxy
  const cv = document.createElement('canvas');
  cv.width = 1; cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });

  function toRGBA(str) {
    if (!str) return [0, 0, 0, 0];
    cx.clearRect(0, 0, 1, 1);
    cx.fillStyle = 'rgba(0,0,0,0)';
    cx.fillStyle = str;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  }

  function over(fg, bg) {           // fg rgba, bg opaque rgb
    const a = fg[3];
    return [
      fg[0] * a + bg[0] * (1 - a),
      fg[1] * a + bg[1] * (1 - a),
      fg[2] * a + bg[2] * (1 - a)
    ];
  }

  function lin(c) {
    c = c / 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }
  function relLum(rgb) {
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2]);
  }
  function ratio(a, b) {
    const la = relLum(a), lb = relLum(b);
    const hi = Math.max(la, lb), lo = Math.min(la, lb);
    return (hi + 0.05) / (lo + 0.05);
  }
  function label(el) {
    if (!el) return 'backdrop';
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const c = (el.getAttribute('class') || '').trim().split(/\s+/)[0];
    if (c) s += '.' + c;
    const ov = el.dataset && el.dataset.ovxId;
    if (ov) s += '[' + ov + ']';
    return s;
  }

  const out = [];
  for (const t of args.targets) {
    const el = document.querySelector(t.sel);
    if (!el) {
      out.push({ key: t.key, rule: t.rule, found: false, reason: 'no such element' });
      continue;
    }
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    // Measure even when the element is not currently PAINTED (the SR fixture
    // sheds the OBJECTIVE row, and the NOW chip only exists at eta 0). The
    // colour pair is still the real authored pair; `painted` records the
    // difference so the report never implies the pixel was on screen.
    const painted = r.width >= 1 && r.height >= 1 &&
                    cs.visibility !== 'hidden' && cs.display !== 'none';

    // Collect the background-color layer stack from the element up to <html>.
    const layers = [];
    let node = el;
    while (node) {
      const bg = toRGBA(getComputedStyle(node).backgroundColor);
      if (bg[3] > 0.001) layers.push({ el: label(node), rgba: bg });
      node = node.parentElement;
    }
    // Paint order is bottom-up: the game proxy, then <html>, ... then el.
    let effBg = backdrop.slice();
    const chain = ['backdrop(' + backdrop.map(v => Math.round(v)).join(',') + ')'];
    for (let i = layers.length - 1; i >= 0; i--) {
      effBg = over(layers[i].rgba, effBg);
      chain.push(layers[i].el + ' @a=' + layers[i].rgba[3].toFixed(2));
    }

    const fgRaw = toRGBA(cs.color);
    const effFg = over(fgRaw, effBg);
    out.push({
      key: t.key,
      rule: t.rule,
      found: true,
      painted: painted,
      computed_color: cs.color,
      fg_rgba: fgRaw.map((v, i) => i === 3 ? Number(v.toFixed(3)) : Math.round(v)),
      eff_fg: effFg.map(v => Math.round(v)),
      eff_bg: effBg.map(v => Math.round(v)),
      surface_chain: chain,
      opaque_surface: layers.length > 0 && layers[layers.length - 1].rgba[3] > 0.995,
      font_px: cs.fontSize,
      font_weight: cs.fontWeight,
      text_shadow: cs.textShadow === 'none' ? '' : cs.textShadow,
      ratio: Number(ratio(effFg, effBg).toFixed(2)),
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]
    });
  }

  // Diagnostics: the RESOLVED backing of every widget, so the report itself
  // records the active_match.css / overlay.css specificity split rather than
  // asserting it from a source read.
  const backings = {};
  document.querySelectorAll('.ovx-widget').forEach((el) => {
    const bg = getComputedStyle(el).backgroundColor;
    backings[(el.dataset && el.dataset.ovxId) || label(el)] = {
      authored: bg,
      resolved_rgba: toRGBA(bg)
    };
  });
  const rootCs = getComputedStyle(document.documentElement);
  const tokens = {};
  for (const t of ['--surface-head', '--surface', '--surface-alt', '--text',
                   '--text-faint', '--ovx-bg', '--ovx-bg-nested']) {
    tokens[t] = rootCs.getPropertyValue(t).trim();
  }

  const call = document.querySelector('.ovx-widget[data-ovx-id="w-call"]');
  const callRect = call ? call.getBoundingClientRect() : null;
  return {
    targets: out,
    widget_count: document.querySelectorAll('.ovx-widget').length,
    widget_backings: backings,
    root_tokens: tokens,
    call_rect: callRect
      ? [Math.round(callRect.x), Math.round(callRect.y),
         Math.round(callRect.width), Math.round(callRect.height)]
      : null
  };
}"""

BACKDROP_CSS_TMPL = (
    "html,body{{background:transparent!important;}}"
    "#rc-legib-backdrop{{position:fixed;inset:0;z-index:-1;pointer-events:none;"
    "background-image:url('{url}');background-size:cover;"
    "background-position:center;}}"
)

BACKDROP_JS = (
    "() => {"
    "  if (!document.getElementById('rc-legib-backdrop')) {"
    "    const d = document.createElement('div');"
    "    d.id = 'rc-legib-backdrop';"
    "    document.body.insertBefore(d, document.body.firstChild);"
    "  }"
    "}"
)


# Every committed ui_mock fixture (sr / aram / mayhem / complete, measured
# 2026-09-01) stamps body[data-fight="1"], so the section-6 combat shed hides
# the w-call OBJECTIVE footer and every .am-pane-head. getComputedStyle still
# resolves their colours (the contrast pairs below are real), but they are not
# in the captured PNG (overlay.css:735 sheds the OBJECTIVE row in a fight).
# --show-shed un-hides them for the visual pass only; it
# does not change any colour, only whether the pixel is on screen.
UNSHED_CSS = """
body[data-shell="overlay"][data-fight="1"] .ovx-widget[data-ovx-id="w-call"]
  #am-call-body > div[data-call-line="objective"] {
  display: flex !important;
}
body[data-shell="overlay"][data-fight="1"] .ovx-widget .am-pane-head {
  display: block !important;
}
"""


def _wait_for_ready(page, timeout_s=12.0):
    """Poll for body.ovx-ready (overlay_layout marks it after first place).

    Deliberately NOT wait_until="networkidle": the dashboard polls
    continuously, so networkidle never fires and the goto times out at 45s.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if page.evaluate("() => document.body.classList.contains('ovx-ready')"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.25)
    return False


def _luma_stats(img, rect):
    """Rendered-pixel luminance stats over a crop of the FINAL 2560x1440 PNG.

    This is a real measurement of the shipped pixels and is the only number
    here that sees V3's text halo at all (a halo is invisible to
    getComputedStyle). It is a spread statistic, not a contrast ratio.
    """
    if not rect:
        return None
    x, y, w, h = rect
    x = max(0, min(img.width - 1, x))
    y = max(0, min(img.height - 1, y))
    w = max(1, min(img.width - x, w))
    h = max(1, min(img.height - y, h))
    crop = img.crop((x, y, x + w, y + h)).convert("L")
    px = list(crop.getdata())
    n = float(len(px))
    mean = sum(px) / n
    var = sum((p - mean) ** 2 for p in px) / n
    return {
        "box": [x, y, w, h],
        "min": min(px),
        "max": max(px),
        "mean": round(mean, 2),
        "stdev": round(var ** 0.5, 2),
    }


def render_cell(browser, variant, backdrop, mode, shots=True, show_shed=False):
    """Render + measure one {variant} x {backdrop} cell."""
    bd_bytes, bd_mean, bd_path = backdrop_asset(backdrop)
    ctx = browser.new_context(
        ignore_https_errors=True,
        viewport={"width": CANVAS_W, "height": CANVAS_H},
        device_scale_factor=2,
    )
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route(
        f"**{BACKDROP_PATH}",
        lambda route: route.fulfill(status=200, body=bd_bytes, content_type="image/png"),
    )
    page.add_init_script("try { localStorage.setItem('rc-ui-mock', '1'); } catch (e) {}")

    url = f"{BASE}/?overlay=1&ui_mock=1&mode={mode}&ovscale={OVSCALE}#active-match"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25_000)
    except Exception as e:  # noqa: BLE001
        ctx.close()
        return {"variant": variant, "backdrop": backdrop, "error": f"goto: {e}"}

    ok_ready = _wait_for_ready(page)
    time.sleep(2.0)

    try:
        page.add_style_tag(content=BACKDROP_CSS_TMPL.format(url=BACKDROP_PATH))
        page.evaluate(BACKDROP_JS)
    except Exception as e:  # noqa: BLE001
        errors.append(f"backdrop: {e}")

    variant_css = VARIANTS[variant]["css"]
    if variant_css.strip():
        try:
            page.add_style_tag(content=variant_css)
        except Exception as e:  # noqa: BLE001
            errors.append(f"variant css: {e}")
    if show_shed:
        try:
            page.add_style_tag(content=UNSHED_CSS)
        except Exception as e:  # noqa: BLE001
            errors.append(f"unshed css: {e}")
    time.sleep(0.6)

    try:
        measured = page.evaluate(MEASURE_JS, {"backdrop": bd_mean, "targets": TARGETS})
    except Exception as e:  # noqa: BLE001
        measured = {"measure_error": str(e), "targets": []}

    out_path = None
    px_stats = None
    if shots:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        shed = "_shed" if show_shed else ""
        out_path = OUT_DIR / f"legib_{variant}_{backdrop}_{mode}{shed}_2560.png"
        try:
            raw = page.screenshot(type="png")
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            if img.size != (CANVAS_W, CANVAS_H):
                img = img.resize((CANVAS_W, CANVAS_H), Image.LANCZOS)
            img.save(out_path, "PNG")
            px_stats = _luma_stats(img, measured.get("call_rect"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"screenshot: {e}")
            out_path = None

    ctx.close()
    return {
        "variant": variant,
        "variant_label": VARIANTS[variant]["label"],
        "backdrop": backdrop,
        "backdrop_label": BACKDROPS[backdrop]["label"],
        "backdrop_mean_rgb": bd_mean,
        "backdrop_png": str(bd_path),
        "mode": mode,
        "show_shed": show_shed,
        "url": url,
        "ovx_ready": ok_ready,
        "out": str(out_path) if out_path else None,
        "out_bytes": out_path.stat().st_size if out_path and out_path.exists() else 0,
        "widget_count": measured.get("widget_count"),
        "widget_backings": measured.get("widget_backings"),
        "root_tokens": measured.get("root_tokens"),
        "w_call_box_luma": px_stats,
        "targets": measured.get("targets", []),
        "errors": errors[:5],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="DS3 overlay legibility variant preview")
    ap.add_argument("--variant", action="append", choices=sorted(VARIANTS),
                    help="restrict to one variant (repeatable); default = all")
    ap.add_argument("--backdrop", action="append", choices=sorted(BACKDROPS),
                    help="restrict to one backdrop (repeatable); default = all")
    ap.add_argument("--mode", default="sr", help="ui_mock fixture mode (default sr)")
    ap.add_argument("--no-shots", action="store_true",
                    help="measure contrast only, skip the PNG writes")
    ap.add_argument("--show-shed", action="store_true",
                    help="un-hide the combat-shed OBJECTIVE footer + pane heads "
                         "so they appear in the PNG (colours are unchanged)")
    args = ap.parse_args(argv)

    variants = args.variant or list(VARIANTS)
    backdrops = args.backdrop or list(BACKDROPS)

    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--ignore-certificate-errors"],
        )
        for v in variants:
            for b in backdrops:
                results.append(render_cell(browser, v, b, args.mode,
                                           shots=not args.no_shots,
                                           show_shed=args.show_shed))
        browser.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report = OUT_DIR / "legibility_report.json"
    report.write_text(json.dumps({
        "generated_for": "docs/qa/OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md",
        "caveat": (
            "SYNTHETIC backdrops only. No League client, no live game and no "
            "archive of real game frames exist on this machine, so no figure "
            "here is a measurement over real game pixels."
        ),
        "mode": args.mode,
        "show_shed": args.show_shed,
        "canvas": [CANVAS_W, CANVAS_H],
        "ovscale": OVSCALE,
        "cells": results,
    }, indent=2), encoding="utf-8")

    print("=" * 78)
    print("MANIFEST")
    print("=" * 78)
    ok_cells = 0
    for r in results:
        if r.get("error"):
            print(f"  FAIL {r['variant']} x {r['backdrop']}: {r['error']}")
            continue
        ok_cells += 1
        print(f"  {r['variant']:>18} x {r['backdrop']:<13} "
              f"widgets={r.get('widget_count')} ready={r.get('ovx_ready')} "
              f"png={r.get('out')} ({r.get('out_bytes')} bytes)")
    sources = ", ".join(str(OUT_DIR / f"_backdrop_{b}.png") for b in backdrops)
    print(f"  backdrop sources: {sources}")
    print(f"  report: {report}")

    base = next((r for r in results
                 if r.get("variant") == "baseline" and r.get("widget_backings")), None)
    if base:
        print()
        print("=" * 78)
        print("SHIPPED-OVERLAY DIAGNOSTIC (baseline widget backings, as resolved)")
        print("=" * 78)
        for wid, info in sorted(base["widget_backings"].items()):
            print(f"  {wid:<14} {info['authored']}")
        print("  root --surface-head = "
              f"{(base.get('root_tokens') or {}).get('--surface-head', '?')}")
        print("  NOTE: w-call / w-build / w-ovds are .am-pane widgets, so")
        print("        active_match.css:92-100 (1,1,0) outranks overlay.css:217-223")
        print("        (0,3,1) and they paint the OPAQUE dashboard --surface-head,")
        print("        not the Hextech rgba(22,32,46,0.58) every other widget uses.")

    print()
    print("=" * 78)
    print("CONTRAST (every ratio names its PAIR: resolved ink vs the exact surface)")
    print("=" * 78)
    for r in results:
        if r.get("error"):
            continue
        print(f"\n-- {r['variant']} x {r['backdrop']} "
              f"(backdrop mean rgb {r['backdrop_mean_rgb']})")
        for t in r.get("targets", []):
            if not t.get("found"):
                print(f"     {t['key']:<32} ABSENT ({t.get('reason', 'absent')})")
                continue
            flag = "AA " if t["ratio"] >= 4.5 else ("aa*" if t["ratio"] >= 3.0 else "FAIL")
            surf = "OPAQUE" if t.get("opaque_surface") else "SEE-THRU"
            seen = "" if t.get("painted") else "  (not painted in this fixture)"
            print(f"     {t['key']:<32} {t['ratio']:>6.2f}:1  {flag}  "
                  f"ink rgb{tuple(t['eff_fg'])} vs surface rgb{tuple(t['eff_bg'])} "
                  f"[{surf}]{seen}")
        if r.get("w_call_box_luma"):
            s = r["w_call_box_luma"]
            print(f"     w-call rendered-pixel luma: mean {s['mean']} "
                  f"stdev {s['stdev']} range {s['min']}..{s['max']}")

    print()
    print("AA  = >= 4.5:1 (WCAG AA normal text). aa* = >= 3.0:1 (large-text only;")
    print("      the overlay authors 11-14px, so 3.0 is NOT a pass here).")
    print("NOTE: no figure above was measured over real game pixels. See")
    print("      docs/qa/OVERLAY_LEGIBILITY_VARIANTS_2026-09-01.md.")
    return 0 if ok_cells else 1


if __name__ == "__main__":
    sys.exit(main())
