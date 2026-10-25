"""Lane 8 (true-audit) s134 cycle 1 - tft/tft_ocr_reader.py.

MEASURED before this slice (2026-10-25, the s134 tft_qa recorder's 80 live
game frames, real Tesseract 5 through the unmodified reader): 0 of 80 frames
yielded ANY field - stage_round, level, gold and hp were all absent on every
frame. Root cause: the regions were hard-coded for a 1600x900 screen, but the
vision relay serves 1280-wide frames (vision_server/_frame.py
_SELF_GRAB_MAX_WIDTH; the recorder's game frames are 1280x720). PIL crops a
box that lies outside the frame WITHOUT raising - it pads with black - so the
level / gold / hp boxes (y 853+ / x 1448+) cropped pure black and the stage
box missed the current HUD's "4-5" text. The subsystem was inert while every
status line said "OCR subsystem started".

Each test below pins one finding. No live capture, no network; the real-OCR
test renders its own text and skips where Tesseract or the font is absent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image  # noqa: E402

from tft import tft_ocr_reader as m  # noqa: E402
from tests._module_view import bind_which  # noqa: E402


class _FakeTess:
    """Returns a scripted string per call; records the configs it saw."""

    def __init__(self, text: str = "42") -> None:
        self.text = text
        self.calls: list[str] = []

    def image_to_string(self, image, config="", **kwargs):  # noqa: ANN001
        self.calls.append(config)
        return self.text


class _FieldEngine:
    """The tft.cv OCR seam (``read(img, field=...)``) answering per field
    name and recording every call. ocr_fields still glyph-checks each digit
    answer against the crop the reader actually took."""

    def __init__(self, answers: dict | None = None) -> None:
        self.answers = dict(answers or {})
        self.calls: list[str] = []

    def available(self) -> bool:
        return True

    def read(self, img, *, field, allowlist="", psm=7):  # noqa: ANN001
        self.calls.append(field)
        return self.answers.get(field, "")


# Real HUD pixels: the TFT-04 sanitised corpus crops (text-only crops and
# flat layout-probe patches, tests/fixtures/tft_cv_ocr) recomposed at their
# recorded boxes on a black 1280x720 relay-size canvas. The recorded boxes
# are ground truth independent of both region tables under test.
_FIX = _REPO_ROOT / "tests" / "fixtures" / "tft_cv_ocr"
_FRAMES_DOC = json.loads((_FIX / "manifest.json").read_text(encoding="ascii"))["frames"]
_FRAMES = sorted(_FRAMES_DOC)


def _real_pixel_frame(key: str) -> Image.Image:
    frame = _FRAMES_DOC[key]
    sheet = Image.open(_FIX / frame["sheet"]).convert("RGB")
    canvas = Image.new("RGB", (1280, 720))
    for c in frame["crops"]:
        canvas.paste(sheet.crop(tuple(c["sheet"])), tuple(c["box"][:2]))
    return canvas


def _live_expect(key: str) -> dict:
    exp = _FRAMES_DOC[key]["expect"]
    return {"stage_round": exp["label"], "level": exp["level"], "gold": exp["gold"],
            "hp": exp["own_hp"]}


def _cv_tesseract_or_skip() -> None:
    from tft.cv.ocr_fields import TesseractEngine
    if not TesseractEngine().available():
        pytest.skip("Tesseract not installed")


# -- F1: regions must land inside the frame the relay actually serves -------

@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080), (2560, 1440)])
def test_every_region_scales_inside_a_16x9_frame(size) -> None:
    for field, bbox in m._REGIONS.items():
        box = m._scaled_bbox(bbox, size)
        assert box is not None, field
        left, top, right, bottom = box
        assert 0 <= left < right <= size[0], (field, box)
        assert 0 <= top < bottom <= size[1], (field, box)


def test_grab_region_scales_a_baseline_box_to_the_frame() -> None:
    bbox = m._REGIONS["stage_round"]
    small = m._grab_region(bbox, Image.new("RGB", m._BASE_SIZE))
    big = m._grab_region(bbox, Image.new("RGB", (m._BASE_SIZE[0] * 2,
                                                 m._BASE_SIZE[1] * 2)))
    assert small is not None and big is not None
    assert big.size == (small.size[0] * 2, small.size[1] * 2)


def test_grab_region_refuses_a_box_outside_the_frame() -> None:
    # The pre-fix level box: PIL would have padded it with black.
    frame = Image.new("RGB", (1280, 720))
    assert m._grab_region((8, 853, 98, 890), frame) is None


def test_non_16x9_frame_is_refused_not_misread() -> None:
    # A stitched two-monitor grab: proportional scaling would put every
    # box on the wrong monitor.
    assert m._scaled_bbox(m._REGIONS["level"], (3840, 1080)) is None
    assert m._grab_region(m._REGIONS["level"],
                          Image.new("RGB", (3840, 1080))) is None


# -- F2: level parse must not take the "1" that "Lvl" OCRs into ------------

def test_level_takes_the_last_number_not_the_first() -> None:
    assert m._ocr_level(Image.new("RGB", (65, 21)), _FakeTess("Lv1.8")) == 8
    assert m._ocr_level(Image.new("RGB", (65, 21)), _FakeTess("Lvl.10")) == 10
    assert m._ocr_level(Image.new("RGB", (65, 21)), _FakeTess("Lvl.")) is None
    assert m._ocr_level(Image.new("RGB", (65, 21)), _FakeTess("Lvl.42")) is None


# -- F3: the legacy boxes carry no gold / hp locator -----------------------
# Pre-fix: _ocr_hp fell back to "the first valid number in the panel" - the
# TOP-ranked player's HP, not yours - and the gold box read 52 as 520. Since
# TFT-04 (merged s135) the live read() goes through tft.cv.ocr_fields and its
# own validated regions (tests/test_tft_cv_ocr_fields.py pins that mapping);
# these pins keep the legacy helpers honest.

@pytest.mark.parametrize("key", _FRAMES)
def test_hp_and_gold_come_only_from_their_own_validated_boxes(key) -> None:
    # The legacy table holds no gold / hp box at all ...
    assert set(m._REGIONS) == {"stage_round", "level"}
    assert not hasattr(m, "_ocr_hp")
    # ... and the live read takes hp / gold from the cv profile's own boxes.
    # On real HUD pixels every digit answer is glyph-checked against the crop
    # the reader took: a box that drifts onto black reads absent, and one on
    # the top scoreboard row (2-digit HP in f0031) refuses the 3-digit own HP,
    # so a wrong box loses its field here. A wrong box over a neighbour with
    # the SAME glyph count passes this fake; the real-Tesseract test below
    # catches that one.
    from tft.cv.profile import load_profile
    want = _live_expect(key)
    eng = _FieldEngine({"stage": want["stage_round"], "level": str(want["level"]),
                        "gold": str(want["gold"]), "own_hp": str(want["hp"])})
    reader = m.TftOcrReader(engine=eng, profile=load_profile())
    assert reader.read_frame_fields(_real_pixel_frame(key)) == want


@pytest.mark.parametrize("key", _FRAMES)
def test_live_read_real_tesseract_reads_own_hp_and_gold_on_real_pixels(key) -> None:
    # The pre-fix misreads were the top-ranked player's HP and gold 52 as
    # 520; real OCR over the recorded HUD must give the local player's values.
    _cv_tesseract_or_skip()
    from tft.cv.profile import load_profile
    got = m.TftOcrReader(profile=load_profile()).read_frame_fields(_real_pixel_frame(key))
    assert got == _live_expect(key)


def test_legacy_helpers_read_stage_and_level_on_a_scaled_frame() -> None:
    # Ink fills exactly the two baseline boxes of a 1280x720 page and PIL, not
    # _scaled_bbox, scales the page to 2560x1440. The fake answers only when it
    # is handed exactly that box at x2 (then x _SCALE plus the 10 px margin,
    # all ink inside): a crop that is shifted, mis-scaled or taken from the
    # other box reads nothing. These helpers are no longer on the live path
    # (read() goes through tft.cv.ocr_fields; only save_debug_crops uses
    # them), so a LIVE misread cannot pass through them - the two tests above
    # pin the live read.
    base = Image.new("RGB", m._BASE_SIZE)
    for box in m._REGIONS.values():
        base.paste((235, 235, 235), box)
    frame = base.resize((2560, 1440), Image.NEAREST)

    class _InkBox(_FakeTess):
        def image_to_string(self, image, config="", **kwargs):  # noqa: ANN001
            self.calls.append(config)
            stage = "-" in config.split("whitelist=")[-1]
            left, top, right, bottom = m._REGIONS["stage_round" if stage else "level"]
            want = ((right - left) * 2 * m._SCALE + 20, (bottom - top) * 2 * m._SCALE + 20)
            inner = image.crop((10, 10, image.width - 10, image.height - 10))
            if image.size != want or inner.getextrema() != (0, 0):
                return ""
            return "3-6" if stage else "Lvl.7"

    tess = _InkBox()
    stage = m._grab_region(m._REGIONS["stage_round"], frame)
    level = m._grab_region(m._REGIONS["level"], frame)
    assert stage is not None and level is not None
    assert m._ocr_stage_round(stage, tess) == "3-6"
    assert m._ocr_level(level, tess) == 7
    assert m._ocr_level(stage, tess) is None          # the other box reads nothing
    assert len(tess.calls) == 3


@pytest.mark.parametrize("key", _FRAMES)
def test_legacy_helpers_read_real_hud_pixels_at_relay_size(key) -> None:
    # A recalibration drift of _REGIONS (a box off the HUD text) or a parse
    # regression reads the wrong value or nothing here. 1280x720 only: the
    # relay serves that size; measured s135, the legacy stage helper reads
    # f0031's "3-6" as "5-6" on a LANCZOS x2 upscale of this canvas.
    tess = m._init_tesseract()
    if tess is None:
        pytest.skip("tesseract not installed")
    exp = _FRAMES_DOC[key]["expect"]
    img = _real_pixel_frame(key)
    assert m._ocr_stage_round(m._grab_region(m._REGIONS["stage_round"], img), tess) == exp["label"]
    assert m._ocr_level(m._grab_region(m._REGIONS["level"], img), tess) == exp["level"]


def test_live_read_on_a_stitched_frame_is_refused_for_no_profile(monkeypatch) -> None:
    # A stitched two-monitor grab fits no region profile: the reader returns
    # {} because read_frame REFUSED the frame (every field absent, reason
    # no_profile) and the engine was never asked - not because a black frame
    # read empty, which a 16:9 frame also does (the contrast below).
    from tft.cv import ocr_fields
    from tft.cv.profile import load_profile
    prof = load_profile()
    assert prof is not None and prof.fits(1280, 720) and not prof.fits(3840, 1080)
    seen = []
    real = ocr_fields.read_frame

    def spy(img, **kwargs):  # noqa: ANN001
        fr = real(img, **kwargs)
        seen.append(fr)
        return fr

    monkeypatch.setattr(ocr_fields, "read_frame", spy)
    eng = _FieldEngine({"stage": "3-6", "level": "7", "gold": "50", "own_hp": "100"})
    reader = m.TftOcrReader(engine=eng, profile=prof)
    assert reader.read_frame_fields(Image.new("RGB", (3840, 1080))) == {}
    assert len(seen) == 1 and seen[0].profile_key == ""
    assert {fv.reason for fv in seen[0].fields.values()} == {"no_profile"}
    assert eng.calls == []
    # contrast: a 16:9 black frame also reads {}, but NOT for no_profile
    assert reader.read_frame_fields(Image.new("RGB", (1280, 720))) == {}
    assert seen[1].profile_key == prof.key
    assert "no_profile" not in {fv.reason for fv in seen[1].fields.values()}


# -- F4: a missing tesseract binary means unavailable, not silently inert ---

def test_missing_binary_is_unavailable(monkeypatch) -> None:
    pytest.importorskip("pytesseract")
    monkeypatch.setattr(m, "_TESS_CMD", str(_REPO_ROOT / "no-such-tesseract.exe"))
    bind_which(monkeypatch, m, lambda name: None)
    assert m._init_tesseract() is None


def test_binary_on_path_is_used_when_default_is_absent(monkeypatch) -> None:
    pytesseract = pytest.importorskip("pytesseract")
    monkeypatch.setattr(m, "_TESS_CMD", str(_REPO_ROOT / "no-such-tesseract.exe"))
    bind_which(monkeypatch, m, lambda name: "found-tesseract")
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd",
                        pytesseract.pytesseract.tesseract_cmd)
    assert m._init_tesseract() is pytesseract
    assert pytesseract.pytesseract.tesseract_cmd == "found-tesseract"


# -- F5: calibrate() validates its input -----------------------------------

@pytest.mark.parametrize("field,bbox", [
    ("level", (10, 10, 5, 30)),        # right < left
    ("level", (10, 30, 50, 30)),       # zero height
    ("level", (-1, 0, 5, 5)),          # negative
    ("level", (1, 2, 3)),              # wrong arity
    ("level", (1.5, 2, 30, 40)),       # not ints
    ("level", (0, 0, 2000, 40)),       # beyond the baseline frame
    ("nonsense", (1, 2, 30, 40)),      # unknown field
])
def test_calibrate_rejects_bad_input(field, bbox) -> None:
    r = m.TftOcrReader.__new__(m.TftOcrReader)
    r._region_overrides = {}
    with pytest.raises(ValueError):
        r.calibrate(field, bbox)
    assert r._region_overrides == {}


# -- characterization: the stage-round parser (unchanged) ------------------

@pytest.mark.parametrize("raw,want", [
    ("3-6", "3-6"), ("36", "3-6"), ("1-4", "1-4"), ("1-5", None),
    ("5-14", None), ("-6", None), ("", None), ("8-1", None),
])
def test_stage_round_parser(raw, want) -> None:
    assert m._ocr_stage_round(Image.new("RGB", (43, 20)), _FakeTess(raw)) == want


# -- F6: preprocessing hands Tesseract dark text on a light page -----------

def test_preprocess_makes_light_text_dark_on_light() -> None:
    img = Image.new("RGB", (40, 20), (20, 30, 35))
    for x in range(10, 30):
        for y in range(5, 15):
            img.putpixel((x, y), (240, 240, 235))
    out = m._preprocess(img)
    assert out.mode == "L"
    hist = out.histogram()
    assert hist[255] > hist[0] > 0          # page light, text dark
    assert out.getpixel((0, 0)) == 255


# -- real OCR, end to end on rendered text (skips without the toolchain) ---

def test_real_tesseract_reads_rendered_stage_and_level() -> None:
    tess = m._init_tesseract()
    if tess is None:
        pytest.skip("tesseract not installed")
    from PIL import ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("arialbd.ttf", 15)
    except OSError:
        pytest.skip("arialbd.ttf not available")
    frame = Image.new("RGB", m._BASE_SIZE, (18, 30, 36))
    draw = ImageDraw.Draw(frame)
    sl, st = m._REGIONS["stage_round"][:2]
    draw.text((sl + 4, st + 2), "4-5", font=font, fill=(235, 225, 200))
    ll, lt = m._REGIONS["level"][:2]
    draw.text((ll + 4, lt + 3), "Lvl. 8", font=font, fill=(240, 240, 240))
    big = frame.resize((2560, 1440), Image.LANCZOS)
    for f in (frame, big):
        assert m._ocr_stage_round(m._grab_region(m._REGIONS["stage_round"], f),
                                  tess) == "4-5"
        assert m._ocr_level(m._grab_region(m._REGIONS["level"], f), tess) == 8
