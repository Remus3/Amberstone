# arch: HUD color-layer consumption in OCR pipeline (R95) | section=vision-tests | frozen=no
"""R95 guard: core/vision_tesseract CONSUMES the core.hud_settings color layer.

read_hud_settings() surfaces two color-driven flags - ``colorblind`` (a non-zero
ColorPalette re-hues the HP/mana bars) and ``color_correction_needed`` (a
non-neutral ColorBrightness/Contrast/Gamma shifts the whole frame). Before R95 the
OCR pipeline hard-matched bar colors and never inverse-corrected the crop, so a
colorblind / gamma-shifted HUD silently mis-read. These tests pin:

  INV1 no-regression: settings=None (with the process-wide global cleared) is
       byte-identical to the pre-R95 neutral behavior.
  INV2 colorblind bar: a marginally-green bar that the strict thresholds miss is
       detected under the relaxed colorblind path (relaxed pct > strict pct).
  INV3 gamma preprocess: color_correction_needed + a non-neutral ColorGamma
       changes the binarized preprocess output.
  INV4 neutral dict == None: an all-neutral settings dict matches the None path.
  configure_hud_color: installs / clears the process-wide default.

CI-safe: no pytesseract - _bar_fill_pct / _preprocess are exercised directly on
tiny synthetic PIL images.
"""
from __future__ import annotations

import pytest
from PIL import Image

from core import vision_tesseract as vt


@pytest.fixture(autouse=True)
def _reset_hud_color():
    """Never leak the process-wide HUD color global across tests."""
    vt.configure_hud_color(None)
    yield
    vt.configure_hud_color(None)


def _marginal_green_bar(w=20, h=8, fill_frac=0.6):
    """A bar whose left ``fill_frac`` columns are only MARGINALLY green: g just
    over the relaxed floor (90) but well under the strict floor (110)."""
    img = Image.new("RGB", (w, h), (10, 10, 10))
    fill_cols = int(w * fill_frac)
    for x in range(fill_cols):
        for y in range(h):
            img.putpixel((x, y), (70, 95, 70))
    return img


def _clear_green_bar(w=20, h=8, fill_frac=0.5):
    """A clearly-green bar the strict path detects, filling the left half."""
    img = Image.new("RGB", (w, h), (10, 10, 10))
    fill_cols = int(w * fill_frac)
    for x in range(fill_cols):
        for y in range(h):
            img.putpixel((x, y), (20, 200, 20))
    return img


def _gray_gradient(w=20, h=8):
    """Distinct per-column gray levels spanning a wide range so a gamma LUT
    repositions pixels across the binarize threshold after autocontrast."""
    img = Image.new("RGB", (w, h))
    for x in range(w):
        v = min(20 + x * 11, 245)
        for y in range(h):
            img.putpixel((x, y), (v, v, v))
    return img


# INV1 -----------------------------------------------------------------------
def test_inv1_preprocess_none_matches_baseline():
    """Neutral path is stable + byte-identical between the default-arg (cleared
    global) and an explicit settings=None call."""
    vt.configure_hud_color(None)
    img = _gray_gradient()
    default_arg = vt._preprocess(img)
    explicit_none = vt._preprocess(img, settings=None)
    assert default_arg.tobytes() == explicit_none.tobytes()


def test_inv1_bar_fill_green_sensible_on_clear_bar():
    """A clearly-green bar returns a sensible >0 fill pct on the neutral path."""
    vt.configure_hud_color(None)
    pct = vt._bar_fill_pct(_clear_green_bar(), "green")
    assert pct is not None and pct > 0


# INV2 -----------------------------------------------------------------------
def test_inv2_colorblind_bar_adaptation():
    """Strict path misses a marginally-green bar; the colorblind-relaxed path
    detects it (relaxed pct strictly > strict pct)."""
    img = _marginal_green_bar()
    strict = vt._bar_fill_pct(img, "green")                      # global cleared -> strict
    strict_explicit = vt._bar_fill_pct(img, "green", settings=None)
    relaxed = vt._bar_fill_pct(img, "green", settings={"colorblind": True})
    assert strict == strict_explicit
    assert (strict or 0) == 0
    assert relaxed is not None and relaxed > (strict or 0)


# INV3 -----------------------------------------------------------------------
def test_inv3_gamma_preprocess_changes_output():
    """color_correction_needed + a non-neutral ColorGamma changes the binarized
    preprocess bytes versus the neutral path."""
    img = _gray_gradient()
    neutral = vt._preprocess(img, scale=1, settings=None)
    gamma = vt._preprocess(
        img, scale=1,
        settings={"color_correction_needed": True, "color": {"ColorGamma": "0.8"}},
    )
    assert neutral.tobytes() != gamma.tobytes()


# INV4 -----------------------------------------------------------------------
def test_inv4_neutral_dict_equals_none_path():
    """An all-neutral settings dict is indistinguishable from settings=None for
    both preprocess and bar detection."""
    neutral_dict = {"colorblind": False, "color_correction_needed": False, "color": {}}
    img = _gray_gradient()
    assert (vt._preprocess(img, settings=neutral_dict).tobytes()
            == vt._preprocess(img, settings=None).tobytes())
    bar = _marginal_green_bar()
    assert (vt._bar_fill_pct(bar, "green", settings=neutral_dict)
            == vt._bar_fill_pct(bar, "green", settings=None))


# configure_hud_color --------------------------------------------------------
def test_configure_hud_color_installs_and_clears_default():
    """A bare _bar_fill_pct (no settings arg) honors the installed default, and
    clearing reverts to the strict path."""
    img = _marginal_green_bar()
    vt.configure_hud_color(None)
    strict = vt._bar_fill_pct(img, "green") or 0
    vt.configure_hud_color({"colorblind": True})
    installed = vt._bar_fill_pct(img, "green")          # no settings arg -> uses global
    assert installed is not None and installed > strict
    vt.configure_hud_color(None)
    assert (vt._bar_fill_pct(img, "green") or 0) == strict


def test_configure_hud_color_gamma_default_affects_preprocess():
    """Installing a color_correction_needed default makes a bare _preprocess
    call adapt; clearing reverts it."""
    img = _gray_gradient()
    baseline = vt._preprocess(img, scale=1).tobytes()
    vt.configure_hud_color({"color_correction_needed": True, "color": {"ColorGamma": "0.8"}})
    installed = vt._preprocess(img, scale=1).tobytes()  # no settings arg -> uses global
    assert installed != baseline
    vt.configure_hud_color(None)
    assert vt._preprocess(img, scale=1).tobytes() == baseline
