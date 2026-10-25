"""Lane 8 true-audit (s134 cycle 2): tft/tft_vision_reader.py.

The reader feeds the live TFT coach (tft/tft_live_analysis.py _run_cycle).
Findings pinned here:

1. Crop regions were authored for 1600x900, but the vision relay serves
   1280x720 frames (vision_server/_frame.py _SELF_GRAB_MAX_WIDTH). PIL pads an
   out-of-frame crop with black instead of raising, so on every live frame the
   bench + shop strip was 92 percent black and the HP column 80 percent black,
   and the "board" box covered the shop instead of the board.
2. _validate_units turned the SPECTATING sentinel into an empty board whenever
   the traits panel was readable, which disabled the consumer's SPECTATING
   skip and coached someone else's game as an empty board.
3. The model's JSON is untrusted: a non-dict reply raised out of read(), a
   string level raised TypeError, and a string "false" for is_augment_select
   was truthy.
4. The moon_proxy failure was swallowed with no log line.
5. The dark-frame check sampled only the top rows of the traits crop.
6. The reply parser assumed the first content block was text.
"""

import base64
import io
import logging
from unittest.mock import patch

import pytest
from PIL import Image

from tft import tft_vision_reader as tvr
from tft.tft_vision_reader import TftVisionReader


def _reader():
    return TftVisionReader("sk-ant-test")


def _png_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _decode(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")


def _capture(frame):
    with patch("modes.shared_vision._capture_screen", return_value=_png_b64(frame)):
        return _reader()._capture_game()


# -- 1. crop regions scale to the frame -------------------------------------

def test_regions_are_authored_inside_the_base_size():
    base_w, base_h = tvr._BASE_SIZE
    assert (base_w, base_h) == (1280, 720)
    for left, top, right, bottom in TftVisionReader._CROP_REGIONS:
        assert 0 <= left < right <= base_w
        assert 0 <= top < bottom <= base_h


def test_relay_frame_crops_carry_no_black_padding():
    """A uniform grey 1280x720 relay frame: every strip of the composite is
    grey across its own width. The 1600x900 boxes padded black here."""
    composite = _decode(_capture(Image.new("RGB", (1280, 720), (128, 128, 128))))
    y = 0
    for bbox in TftVisionReader._CROP_REGIONS:
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        strip = composite.crop((0, y, w, y + h))
        assert strip.getextrema() == ((128, 128), (128, 128), (128, 128)), bbox
        y += h
    assert y == composite.size[1]


def test_native_frame_scales_to_the_same_hud_boxes():
    small = _decode(_capture(Image.new("RGB", (1280, 720), (90, 90, 90))))
    big = _decode(_capture(Image.new("RGB", (2560, 1440), (90, 90, 90))))
    assert big.size == (small.size[0] * 2, small.size[1] * 2)
    assert tvr._scaled_bbox((0, 150, 200, 540), (2560, 1440)) == (0, 300, 400, 1080)


def test_non_16_9_frame_is_refused():
    assert _capture(Image.new("RGB", (1280, 1024), (128, 128, 128))) is None


def test_scaled_bbox_refuses_unusable_frames():
    assert tvr._scaled_bbox((0, 0, 10, 10), (0, 0)) is None
    assert tvr._scaled_bbox((0, 0, 1300, 10), (1280, 720)) is None


def test_dark_check_reads_the_whole_traits_crop():
    """Black frame with a bright band only in the first rows of the traits
    box: the old check sampled exactly those rows and passed it."""
    frame = Image.new("RGB", (1280, 720), (0, 0, 0))
    left, top, right, _bottom = TftVisionReader._CROP_REGIONS[0]
    frame.paste((255, 255, 255), (left, top, right, top + 12))
    assert _capture(frame) is None


def test_lit_frame_is_accepted():
    assert _capture(Image.new("RGB", (1280, 720), (60, 60, 60))) is not None


def test_prompt_does_not_claim_a_full_1600x900_screenshot():
    assert "1600x900" not in tvr._EXTRACT_PROMPT
    assert "1600x900" not in (tvr.__doc__ or "")


# -- 2 / 3. state normalisation and the SPECTATING sentinel -----------------

def _read_with(state):
    r = _reader()
    with patch.object(r, "_capture_game", return_value="aGVsbG8="), \
            patch.object(r, "_extract", return_value=state):
        return r.read()


def test_non_dict_reply_returns_none_without_raising():
    assert _read_with(["Aatrox", "Caitlyn"]) is None
    assert _read_with("Aatrox") is None


def test_spectating_sentinel_survives_a_readable_traits_panel():
    out = _read_with({"traits_active": ["Bastion 2"], "board_units": ["SPECTATING"]})
    assert out["board_units"] == ["SPECTATING"]


def test_spectating_sentinel_is_case_normalised():
    out = _read_with({"traits_active": ["Bastion 2"], "board_units": ["spectating"]})
    assert out["board_units"] == ["SPECTATING"]


def test_string_level_does_not_raise_and_is_coerced():
    out = _read_with({"traits_active": ["Bastion 2"], "board_units": ["Aatrox"] * 6,
                      "level": "3"})
    assert out["level"] == 3
    assert out["_unit_warning"] == "Got 6 units at level 3"


@pytest.mark.parametrize("bad", ["high", True, -1, 11, 3.5, None])
def test_implausible_level_becomes_none(bad):
    out = _read_with({"traits_active": ["Bastion 2"], "board_units": ["Aatrox"] * 6,
                      "level": bad})
    assert out["level"] is None
    assert "_unit_warning" not in out


def test_unit_warning_fires_on_an_int_level():
    out = _read_with({"traits_active": ["Bastion 2"], "board_units": ["Aatrox"] * 6,
                      "level": 3})
    assert out["_unit_warning"] == "Got 6 units at level 3"


def test_string_false_augment_select_is_false():
    assert _read_with({"is_augment_select": "false"})["is_augment_select"] is False
    assert _read_with({"is_augment_select": True})["is_augment_select"] is True


def test_wrong_typed_list_fields_become_empty_lists():
    out = _read_with({"board_units": "Aatrox", "augments": {"a": 1},
                      "shop_units": None, "items_equipped": ["x"]})
    assert out["board_units"] == []
    assert out["augments"] == []
    assert out["shop_units"] == []
    assert out["items_equipped"] == {}


def test_list_entries_keep_strings_and_choice_dicts_only():
    out = _read_with({"augments": ["Rogue Crest", None, 5, " "],
                      "augment_choices": [{"name": "A B", "description": "d"}, 7, "C D"]})
    assert out["augments"] == ["Rogue Crest"]
    assert out["augment_choices"] == [{"name": "A B", "description": "d"}, "C D"]


def test_hp_and_gold_out_of_range_become_none():
    out = _read_with({"hp": 250, "gold": "lots"})
    assert out["hp"] is None and out["gold"] is None
    out = _read_with({"hp": 64, "gold": "38"})
    assert out["hp"] == 64 and out["gold"] == 38


def test_absent_keys_stay_absent():
    out = _read_with({"board_units": ["Aatrox"]})
    assert set(out) == {"board_units"}


# -- 4. moon_proxy failure is logged ----------------------------------------

def test_moon_proxy_failure_is_logged_and_falls_back(caplog):
    r = _reader()
    with patch("core.moon_proxy.moon_proxy.extract_vision",
               side_effect=RuntimeError("relay down")), \
            patch.object(r, "_extract_local", return_value={"board_units": []}) as local, \
            caplog.at_level(logging.DEBUG, logger="rc.tft.vision"):
        assert r._extract("aGVsbG8=") == {"board_units": []}
    local.assert_called_once()
    assert any("moon_proxy" in rec.getMessage() for rec in caplog.records)


# -- 6. reply parsing --------------------------------------------------------

class _Block:
    def __init__(self, type_, text=None):
        self.type = type_
        if text is not None:
            self.text = text


class _Resp:
    def __init__(self, blocks):
        self.content = blocks
        self.usage = None


class _Client:
    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc
        self.messages = self

    def create(self, **_kw):
        if self._exc:
            raise self._exc
        return self._resp


def _local(resp=None, exc=None):
    r = _reader()
    r._client = _Client(resp, exc)
    return r._extract_local("aGVsbG8=")


def test_reply_parser_skips_a_leading_non_text_block():
    resp = _Resp([_Block("thinking"), _Block("text", '{"board_units": ["Aatrox"]}')])
    assert _local(resp) == {"board_units": ["Aatrox"]}


def test_reply_parser_strips_markdown_fences():
    resp = _Resp([_Block("text", '```json\n{"augments": []}\n```')])
    assert _local(resp) == {"augments": []}


def test_reply_parser_finds_braces_in_prose():
    resp = _Resp([_Block("text", 'Here you go: {"level": null} done')])
    assert _local(resp) == {"level": None}


def test_reply_with_no_text_returns_none():
    assert _local(_Resp([])) is None
    assert _local(_Resp([_Block("text", "   ")])) is None


def test_api_error_returns_none_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="rc.tft.vision"):
        assert _local(exc=RuntimeError("credit balance too low")) is None
    assert any("Vision extract failed" in rec.getMessage() for rec in caplog.records)
