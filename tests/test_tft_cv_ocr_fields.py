"""TFT-04 (session 134): HUD region profile, layout classifier and OCR fields.

Spec: docs/TFT_PROGRAM.md section 3.2 stages 2-4 and the TFT-04 row of section 7
(ADR-018). Everything except the last block runs WITHOUT Tesseract: the OCR
engine is a seam (``engine.read(img, field=..., allowlist=..., psm=...)``) and a
fake engine answers per field name, so parsers, validators, layout gates and the
value envelopes are pinned on synthetic frames.

The real-pixel block composes sanitised crops from corpus 20261025-070350
(``tests/fixtures/tft_cv_ocr/``: text-only crops and flat layout-probe patches, no
player name, portrait, splash or icon art) back onto a black 1280x720 canvas.
Its layout test needs no Tesseract; its value test skips when Tesseract is not
installed. Measured corpus accuracy is reported by tools/tft_cv_accuracy.py
(``--extractor tft.cv.ocr_fields:extract``), not asserted here.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tft.cv import layout as lay
from tft.cv import ocr_fields as of
from tft.cv.profile import (
    BASE_RESOLUTION,
    load_profile,
    parse_profile,
    resolution_from_ini,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE_FILE = REPO_ROOT / "config" / "tft_regions" / "2560x1440.json"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "tft_cv_ocr"
SIZE = (1280, 720)


@pytest.fixture(scope="module")
def prof():
    p = load_profile()
    assert p is not None
    return p


@pytest.fixture(scope="module")
def vocab():
    return of.load_vocab(18)


class FakeEngine:
    """The OCR seam's stand-in: per-field answer queues (the last answer sticks)."""

    def __init__(self, answers: dict | None = None):
        self.answers = {k: list(v) for k, v in (answers or {}).items()}
        self.calls: list[str] = []
        self.lock = threading.Lock()

    def read(self, img, *, field, allowlist="", psm=7):
        with self.lock:
            self.calls.append(field)
            q = self.answers.get(field)
            if not q:
                return ""
            return q.pop(0) if len(q) > 1 else q[0]


def _rect(draw, box, fill):
    l, t, r, b = box
    draw.rectangle((l, t, r - 1, b - 1), fill=fill)


def _blocks(draw, box, n, thin=False):
    """``n`` bright glyph-like blocks inside ``box`` (thin = 1-shaped)."""
    l, t, r, b = box
    h = b - t
    gh = max(3, h // 2)
    gw = max(1, gh // 4) if thin else max(2, int(gh * 0.7))
    x = l + max(2, (r - l) // 6)
    for _ in range(n):
        draw.rectangle((x, t + (h - gh) // 2, x + gw - 1, t + (h - gh) // 2 + gh - 1),
                       fill=(240, 240, 240))
        x += gw + max(2, gw // 2)


def synthetic_frame(prof, size=SIZE, panels=("stage_bar", "hud_bar", "shop", "own_hp"),
                    score_digits=(2, 2, 2, 2, 2, 2, 2), trait_counts=(3, 2, 1),
                    active=(True, True, False), streak_rgb=(230, 120, 30)):
    img = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(img)
    for name in ("stage", "timer", "level", "xp", "gold", "streak"):
        _blocks(d, prof.box(name, size), 2)
    _blocks(d, prof.box("own_hp", size), 3)          # "100": three glyphs
    for slot in prof.group("odds", size):
        _blocks(d, slot["text"], 2)
    for slot in prof.group("shop", size):
        _blocks(d, slot["name"], 4)
        _blocks(d, slot["cost"], 1)
    for slot, n in zip(prof.group("scoreboard", size), score_digits):
        if n:
            _blocks(d, slot["hp"], n)
    for slot, count, act in zip(prof.group("traits", size), trait_counts, active):
        _blocks(d, slot["name"], 5)
        _blocks(d, slot["count"], 1, thin=(count == 1))
        _rect(d, slot["icon"], (200, 120, 40) if act else (70, 70, 70))
    _rect(d, prof.box("streak_icon", size), streak_rgb)
    for name in panels:
        for p in prof.panels[name].probes:
            _rect(d, prof.scale(p.box, *size), tuple(int(c) for c in p.rgb))
    return img


ANSWERS = {
    "stage": ["3-6"], "timer": ["7"], "gold": ["50"], "level": ["7"], "xp": ["2/56"],
    "streak": ["11"], "own_hp": ["100"], "odds": ["16%", "30%", "43%", "10%", "1%"],
    "shop_name": ["Rammus", "Mama Beak", "Scuttlecrab", "Fiddlesticks", "Smurfing"],
    "shop_cost": ["3", "3", "2", "3", "5"],
    "scoreboard_hp": ["85", "83", "67", "61", "58", "52", "40"],
    "trait_name": ["Blossom", "Lunar", "Executioner"], "trait_count": ["3", "2"],
}


# ---------------------------------------------------------------------------
# profile


def test_native_profile_is_exact_2560x1440(prof):
    assert (prof.base_w, prof.base_h) == BASE_RESOLUTION == (2560, 1440)
    assert prof.key == "2560x1440@ui1" and prof.exact and prof.conf_factor == 1.0


def test_boxes_scale_with_the_frame(prof):
    native = prof.box("gold", (2560, 1440))
    half = prof.box("gold", (1280, 720))
    three_q = prof.box("gold", (1920, 1080))
    assert native == tuple(int(v) for v in prof.boxes["gold"])
    assert half == tuple(int(v / 2) for v in prof.boxes["gold"])
    assert three_q == tuple(int(v * 0.75) for v in prof.boxes["gold"])


def test_same_aspect_client_uses_scaled_profile_with_lower_conf():
    p = load_profile((1920, 1080))
    assert p is not None and not p.exact and p.conf_factor < 1.0
    assert p.fits(1920, 1080) and p.fits(1280, 720)


def test_other_aspect_has_no_profile_and_reads_absent(prof):
    assert load_profile((2560, 1080)) is None
    assert not prof.fits(2560, 1080)
    fr = of.read_frame(Image.new("RGB", (2560, 1080)), profile=prof, engine=FakeEngine(ANSWERS))
    assert {fv.src for fv in fr.fields.values()} == {"absent"}
    assert {fv.reason for fv in fr.fields.values()} == {"no_profile"}


def test_ui_scale_mismatch_has_no_profile():
    assert load_profile((2560, 1440), ui_scale=1.25) is None


def test_resolution_from_client_ini():
    text = "[/Script/TFTSettings.TFTUserSettings]\nResolutionSizeX=2560\nResolutionSizeY=1440\n"
    assert resolution_from_ini(text) == (2560, 1440)
    assert resolution_from_ini("ResolutionSizeX=1920\n") is None
    assert resolution_from_ini("") is None


def _doc():
    return json.loads(PROFILE_FILE.read_text(encoding="ascii"))


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("base"),
    lambda d: d["fields"].pop("gold"),
    lambda d: d["fields"]["gold"].update(box=[10, 10, 5, 20]),
    lambda d: d["fields"]["gold"].update(panel="nope"),
    lambda d: d["fields"]["shop"]["group"].update(count=0),
    lambda d: d["panels"]["shop"].update(min_match=9),
])
def test_parse_profile_rejects_bad_documents(mutate):
    d = _doc()
    mutate(d)
    with pytest.raises(ValueError):
        parse_profile(d)


def test_bad_profile_file_is_skipped_not_raised(tmp_path):
    (tmp_path / "2560x1440.json").write_text("{not json", encoding="ascii")
    assert load_profile(config_dir=tmp_path) is None


def test_groups_expand(prof):
    assert len(prof.group("odds", SIZE)) == 5
    assert len(prof.group("shop", SIZE)) == 5
    assert len(prof.group("scoreboard", SIZE)) == 7
    assert len(prof.group("traits", SIZE)) == 9
    xs = [s["name"][0] for s in prof.group("shop", SIZE)]
    assert xs == sorted(xs) and len(set(xs)) == 5


def test_profile_file_is_ascii_lf_rectangles_only():
    raw = PROFILE_FILE.read_bytes()
    raw.decode("ascii")
    assert b"\r\n" not in raw
    d = _doc()
    for name, spec in d["fields"].items():
        assert set(spec) <= {"box", "group", "panel"}, name
    for name, spec in d["panels"].items():
        assert set(spec) <= {"probes", "min_match", "cover", "cover_min"}, name


# ---------------------------------------------------------------------------
# pure parsers / validators


@pytest.mark.parametrize("text,want", [
    ("3-6", (3, 6)), (" 2 - 2\n", (2, 2)), ("36", None), ("3-0", None), ("12-1", None), ("", None),
])
def test_parse_stage(text, want):
    assert of.parse_stage(text) == want


def test_parse_int_and_percent():
    assert of.parse_int("50", 0, 999) == 50
    assert of.parse_int("1000", 0, 999) is None
    assert of.parse_int("", 0, 9) is None
    assert of.parse_percent("43%") == 43
    assert of.parse_percent("101%") is None
    assert of.parse_percent("%") is None


def test_parse_xp_with_and_without_the_separator():
    assert of.parse_xp("2/56") == ((2, 56), False)
    assert of.parse_xp("3436") == ((34, 36), True)     # QA probe: "/" lost
    assert of.parse_xp("56/2") == (None, False)
    assert of.parse_xp("00") == (None, False)


def test_parse_signed_allows_overkill_hp():
    assert of.parse_signed("-18", -99, 200) == -18
    assert of.parse_signed("85", -99, 200) == 85
    assert of.parse_signed("8-5", -99, 200) is None


def test_match_name(vocab):
    assert of.match_name("MamaBeak", vocab.units)[0] == "Mama Beak"
    assert of.match_name("Scuttlecrah", vocab.units)[0] == "Scuttlecrab"
    assert of.match_name("Vi", vocab.units) == ("Vi", 1.0)
    assert of.match_name("Vx", vocab.units) is None
    assert of.match_name("zzzzzz", vocab.units) is None
    assert of.match_name("FlipFrenzy", vocab.items)[0] == "Flip Frenzy"


def test_solve_odds_uses_the_sum_check():
    vals, unique = of.solve_odds([[5, 55], [30], [18, 15], [0], [0]])
    assert vals == [55, 30, 15, 0, 0] and unique
    assert of.solve_odds([[5], [30], [18], [0], [0]]) == (None, False)
    # primaries sum to 110; swapping slot 0 or slot 1 both reach 100 -> a tie is refused
    assert of.solve_odds([[50, 40], [40, 30], [20], [0], [0]])[1] is False
    assert of.solve_odds([[], [30], [15], [0], [0]]) == (None, False)


def test_ordered_rows_drops_inversions_and_exempts_eliminated():
    assert of.ordered_rows([85, 83, 6, 61, 58, 52, 40]) == {0, 1, 3, 4, 5, 6}
    assert of.ordered_rows([12, 12, 0, -4, 0, -18, 0]) == set(range(7))
    assert of.ordered_rows([None, 50, None]) == {1}


def test_reconcile_digits_restores_dropped_ones():
    wide = (0, 0, 8, 12)
    one = (10, 0, 12, 12)
    assert of.reconcile_digits("6", [wide, one]) == "61"
    assert of.reconcile_digits("61", [wide, one]) == "61"
    assert of.reconcile_digits("6", [wide, wide]) is None          # refused, not guessed
    assert of.reconcile_digits("-18", [one, wide]) == "-18"
    assert of.reconcile_digits("", [wide]) is None


def test_streak_sign_from_icon_hue():
    assert of.streak_sign(Image.new("RGB", (20, 20), (230, 120, 30))) == 1
    assert of.streak_sign(Image.new("RGB", (20, 20), (40, 120, 230))) == -1
    assert of.streak_sign(Image.new("RGB", (20, 20), (90, 90, 90))) is None
    assert of.streak_sign(Image.new("RGB", (20, 20), (115, 60, 15))) == 1    # dimmed flame


def test_lone_one_shape_rule():
    bw = Image.new("L", (40, 40), 255)
    ImageDraw.Draw(bw).rectangle((18, 5, 21, 34), fill=0)
    assert of.is_lone_one(bw)
    ImageDraw.Draw(bw).rectangle((5, 5, 14, 34), fill=0)
    assert not of.is_lone_one(bw)


def test_has_text_signal_accepts_dimmed_text():
    dim = Image.new("RGB", (30, 12), (25, 25, 25))
    ImageDraw.Draw(dim).rectangle((5, 2, 20, 9), fill=(95, 95, 95))
    assert of.has_text_signal(dim)
    assert not of.has_text_signal(Image.new("RGB", (30, 12), (25, 25, 25)))


# ---------------------------------------------------------------------------
# layout classifier


def test_layout_all_probe_panels_visible(prof):
    got = lay.classify(synthetic_frame(prof), prof)
    assert got.panels == {"stage_bar": True, "hud_bar": True, "shop": True,
                          "own_hp": True, "scoreboard": True, "traits": True}


def test_layout_black_frame_hides_probe_panels(prof):
    got = lay.classify(Image.new("RGB", SIZE), prof)
    for panel in ("stage_bar", "hud_bar", "shop"):
        assert got.panels[panel] is False, panel


def test_inspect_panel_cover_hides_own_hp(prof):
    """The local HP box narrows with its digit count (100 vs 96), so its gate is
    the inspect panel's green health bar covering it, not the box frame."""
    img = synthetic_frame(prof)
    assert lay.classify(img, prof).panels["own_hp"] is True
    d = ImageDraw.Draw(img)
    for p in prof.panels["own_hp"].cover:
        _rect(d, prof.scale(p.box, *SIZE), tuple(int(c) for c in p.rgb))
    assert lay.classify(img, prof).panels["own_hp"] is False


def test_layout_cover_panel_hides_scoreboard(prof):
    img = synthetic_frame(prof)
    d = ImageDraw.Draw(img)
    for p in prof.panels["scoreboard"].cover:
        _rect(d, prof.scale(p.box, *SIZE), tuple(int(c) for c in p.rgb))
    assert lay.classify(img, prof).panels["scoreboard"] is False


# ---------------------------------------------------------------------------
# read_frame on synthetic frames (fake engine)


def test_read_frame_envelopes(prof, vocab):
    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=FakeEngine(ANSWERS),
                       vocab=vocab, workers=1)
    v = {k: fv.value for k, fv in fr.fields.items()}
    assert (v["label"], v["stage"], v["round"]) == ("3-6", 3, 6)
    assert (v["timer"], v["gold"], v["level"], v["xp_cur"], v["xp_max"]) == (7, 50, 7, 2, 56)
    assert v["streak"] == 11 and v["own_hp"] == 100
    assert v["odds"] == [16, 30, 43, 10, 1]
    shop = v["shop"]
    assert [o["name"] for o in shop] == ["Rammus", "Mama Beak", "Scuttlecrab",
                                         "Fiddlesticks", "Smurfing"]
    assert [o["kind"] for o in shop] == ["champion"] * 4 + ["special"]
    assert shop[0]["champion_api"].startswith("DA_18_") and shop[2]["cost"] == 2
    assert shop[4]["cost"] == 5
    assert [r["hp"] for r in v["scoreboard"]] == [85, 83, 67, 61, 58, 52, 40]
    traits = v["traits"]
    assert [(t["trait"], t["count"], t["active"]) for t in traits] == [
        ("Blossom", 3, True), ("Lunar", 2, True), ("Executioner", 1, False)]
    for name, fv in fr.fields.items():
        assert fv.src == "ocr", name
        assert 0.0 < fv.conf <= 1.0, name
    assert fr.extractor_version == of.EXTRACTOR_VERSION and fr.profile_key == "2560x1440@ui1"


def test_hidden_panels_read_absent_and_are_never_ocrd(prof, vocab):
    eng = FakeEngine(ANSWERS)
    img = synthetic_frame(prof, panels=("stage_bar",))
    d = ImageDraw.Draw(img)
    for p in prof.panels["own_hp"].cover:
        _rect(d, prof.scale(p.box, *SIZE), tuple(int(c) for c in p.rgb))
    fr = of.read_frame(img, profile=prof, engine=eng, vocab=vocab, workers=1)
    for name in ("gold", "level", "xp_cur", "xp_max", "streak", "odds", "shop", "own_hp"):
        assert fr.fields[name].src == "absent" and fr.fields[name].value is None, name
        assert fr.fields[name].reason == "panel_hidden", name
    assert not {"gold", "level", "xp", "streak", "odds", "shop_name", "own_hp"} & set(eng.calls)
    assert fr.fields["label"].value == "3-6"


def test_odds_failing_the_sum_runs_fallbacks_then_reads_absent(prof, vocab):
    answers = dict(ANSWERS, odds=["16%", "30%", "43%", "18%", "1%"])
    eng = FakeEngine(answers)
    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=eng, vocab=vocab,
                       fields=["odds"], workers=1)
    assert fr.fields["odds"].src == "absent" and fr.fields["odds"].reason == "odds_sum"
    assert eng.calls.count("odds") == 5 * len(of.PREP_ODDS)


def test_odds_recover_the_measured_5_8_confusion(prof, vocab):
    assert of.confusable_variants([18, 1]) == [15]
    assert of.confusable_variants([55]) == [85, 58]
    # level-8 strip 15/20/32/30/3 with "15%" read as "18%" by every recipe
    answers = dict(ANSWERS, odds=["18%", "20%", "32%", "30%", "3%"])
    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=FakeEngine(answers),
                       vocab=vocab, fields=["odds"], workers=1)
    assert fr.fields["odds"].value == [15, 20, 32, 30, 3]
    assert fr.fields["odds"].conf < of.FIELD_CONF["odds"]


def test_shop_strip_without_a_roster_name_is_not_a_shop(prof, vocab):
    answers = dict(ANSWERS, shop_name=["qwxz"])
    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=FakeEngine(answers),
                       vocab=vocab, fields=["shop"], workers=1)
    assert fr.fields["shop"].src == "absent" and fr.fields["shop"].reason == "no_roster_match"


def test_scoreboard_inversion_is_reread_and_overkill_kept(prof, vocab):
    # row 3 first reads "9": one digit for two glyphs is refused, and the fallback
    # recipe's 61 fits between its neighbours; row 7 is an eliminated player's -4
    answers = dict(ANSWERS, scoreboard_hp=["85", "83", "67", "9", "58", "52", "-4", "61"])
    fr = of.read_frame(synthetic_frame(prof, score_digits=(2, 2, 2, 2, 2, 2, 1)),
                       profile=prof, engine=FakeEngine(answers), vocab=vocab,
                       fields=["scoreboard"], workers=1)
    rows = fr.fields["scoreboard"].value
    assert [r["hp"] for r in rows] == [85, 83, 67, 61, 58, 52, -4]
    assert rows[6]["alive"] is False and rows[0]["alive"] is True
    assert rows[3]["conf"] < rows[0]["conf"]


def test_unread_field_is_absent_never_zero(prof, vocab):
    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=FakeEngine({}),
                       vocab=vocab, workers=1)
    for name, fv in fr.fields.items():
        assert fv.value is None and fv.src == "absent", name


def test_scaled_profile_lowers_conf(vocab):
    scaled = load_profile((1920, 1080))
    img = synthetic_frame(scaled, size=(1920, 1080))
    fr = of.read_frame(img, profile=scaled, engine=FakeEngine(ANSWERS), vocab=vocab,
                       fields=["gold"], workers=1)
    assert fr.fields["gold"].value == 50
    assert fr.fields["gold"].conf == pytest.approx(of.FIELD_CONF["gold"] * scaled.conf_factor)


def test_worker_threads_are_capped_at_two(prof, vocab):
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    class SlowEngine(FakeEngine):
        def read(self, img, **kw):
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            time.sleep(0.01)
            with lock:
                live["now"] -= 1
            return super().read(img, **kw)

    of.read_frame(synthetic_frame(prof), profile=prof, engine=SlowEngine(ANSWERS),
                  vocab=vocab, workers=8)
    assert of.MAX_WORKERS == 2 and 1 <= live["peak"] <= 2


def test_a_raising_field_is_absent_and_never_raises(prof, vocab):
    class BoomEngine(FakeEngine):
        def read(self, img, **kw):
            if kw.get("field") == "gold":
                raise RuntimeError("tesseract exploded")
            return super().read(img, **kw)

    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=BoomEngine(ANSWERS),
                       vocab=vocab, workers=2)
    assert fr.fields["gold"].src == "absent" and fr.fields["gold"].reason == "error"
    assert fr.fields["label"].value == "3-6" and fr.fields["level"].value == 7


def test_unknown_field_name_is_rejected(prof):
    with pytest.raises(ValueError):
        of.read_frame(Image.new("RGB", SIZE), profile=prof, engine=FakeEngine(), fields=["hp"])


def test_label_schema_adapter(prof, vocab):
    fr = of.read_frame(synthetic_frame(prof), profile=prof, engine=FakeEngine(ANSWERS),
                       vocab=vocab, workers=1)
    out = of.to_label_fields(fr)
    assert out["stage"]["value"] == "3-6" and out["hp_local"]["value"] == 100
    rows = out["scoreboard"]["value"]
    assert rows[0] == {"hp": 100, "local": True} and len(rows) == 8
    assert out["shop"]["value"][4] == {"name": "Smurfing", "cost": 5, "kind": "special"}
    assert out["shop_open"] is True
    assert [t["name"] for t in out["traits"]["value"]] == ["Blossom", "Lunar", "Executioner"]


def test_tesseract_engine_without_binary_returns_empty():
    eng = of.TesseractEngine(cmd="")
    assert not eng.available()
    assert eng.read(Image.new("L", (10, 10), 255), field="gold") == ""


# ---------------------------------------------------------------------------
# real pixels: sanitised corpus crops on a black canvas


def _manifest():
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="ascii"))


def _composite(frame: dict, size=SIZE) -> Image.Image:
    sheet = Image.open(FIXTURES / frame["sheet"]).convert("RGB")
    canvas = Image.new("RGB", SIZE, (0, 0, 0))
    for c in frame["crops"]:
        canvas.paste(sheet.crop(tuple(c["sheet"])), tuple(c["box"][:2]))
    # the flame icon is art and is not in the fixture: paint a flat warm patch
    ImageDraw.Draw(canvas).rectangle(
        tuple(load_profile().box("streak_icon", SIZE)), fill=(230, 120, 30))
    return canvas if size == SIZE else canvas.resize(size, Image.LANCZOS)


FRAMES = sorted(_manifest()["frames"])


def test_fixture_is_sanitised():
    m = _manifest()
    raw = (FIXTURES / "manifest.json").read_bytes()
    raw.decode("ascii")
    low = raw.decode("ascii").lower()
    for word in ("puuid", "summoner", "riotid", "gamename", "tagline"):
        assert word not in low
    for frame in m["frames"].values():
        assert (FIXTURES / frame["sheet"]).stat().st_size < 64_000
        for c in frame["crops"]:
            if c["name"].startswith("score"):
                # scoreboard names end left of x=1205 (1280 frame); only HP boxes ship
                assert c["box"][0] >= 1210, c
            assert c["name"] != "streak_icon"


@pytest.mark.parametrize("key", FRAMES)
def test_real_pixel_layout(prof, key):
    got = lay.classify(_composite(_manifest()["frames"][key]), prof)
    for panel in ("stage_bar", "hud_bar", "shop", "own_hp", "scoreboard"):
        assert got.panels[panel] is True, panel


def test_own_hp_needs_both_recipes_to_agree(prof, vocab):
    fr = of.read_frame(synthetic_frame(prof), profile=prof, vocab=vocab, fields=["own_hp"],
                       engine=FakeEngine({"own_hp": ["100", "10"]}), workers=1)
    assert fr.fields["own_hp"].src == "absent"
    assert fr.fields["own_hp"].reason in ("recipes_disagree", "unparsed")


needs_tesseract = pytest.mark.skipif(not of.TesseractEngine().available(),
                                     reason="Tesseract not installed")


def _check_values(fr, exp):
    v = {k: fv.value for k, fv in fr.fields.items()}
    for key in ("label", "timer", "level", "xp_cur", "xp_max", "gold", "streak", "own_hp"):
        assert v[key] == exp[key], key
    assert v["odds"] in (None, exp["odds"])           # sum-gated: absent or right
    assert [None if o["kind"] == "empty" else o["name"] for o in v["shop"]] == exp["shop"]
    got_sb = [r["hp"] for r in v["scoreboard"]]
    assert all(g in (None, e) for g, e in zip(got_sb, exp["scoreboard"]))
    assert sum(g is not None for g in got_sb) >= 5
    traits = {t["trait"]: t["count"] for t in v["traits"]}
    for name, count in exp["traits"]:
        assert traits.get(name) == count, name


@needs_tesseract
@pytest.mark.parametrize("key", FRAMES)
def test_real_pixel_values(prof, vocab, key):
    frame = _manifest()["frames"][key]
    fr = of.read_frame(_composite(frame), profile=prof, vocab=vocab)
    _check_values(fr, frame["expect"])


@needs_tesseract
def test_real_pixel_values_at_1920x1080(vocab):
    """Resolution-relative regions: the same HUD upscaled to a 1920x1080 frame."""
    frame = _manifest()["frames"][FRAMES[-1]]
    fr = of.read_frame(_composite(frame, size=(1920, 1080)), profile=load_profile((1920, 1080)),
                       vocab=vocab)
    _check_values(fr, frame["expect"])


# ---------------------------------------------------------------------------
# live path (match-3 QA N7): TftOcrReader reads through the cv regions


def test_live_reader_maps_cv_fields(prof):
    from tft.tft_ocr_reader import TftOcrReader

    reader = TftOcrReader(engine=FakeEngine(ANSWERS), profile=prof)
    got = reader.read_frame_fields(synthetic_frame(prof))
    assert got == {"stage_round": "3-6", "level": 7, "gold": 50, "hp": 100}
    # the 1600x900 absolute boxes are no longer what the live read crops
    assert reader.read_frame_fields(Image.new("RGB", SIZE)) == {}


def test_live_reader_read_uses_the_relay_frame(prof, monkeypatch):
    from tft import tft_ocr_reader as tor

    monkeypatch.setattr(tor.TftOcrReader, "available", property(lambda self: True))
    monkeypatch.setattr(tor, "_capture_full_frame", lambda: synthetic_frame(prof))
    reader = tor.TftOcrReader(engine=FakeEngine(ANSWERS), profile=prof)
    assert reader.read(force=True)["stage_round"] == "3-6"
    assert reader.read_stage_round_only() == "3-6"
    monkeypatch.setattr(tor, "_capture_full_frame", lambda: None)
    assert reader.read(force=True) == {}


def test_live_reader_without_profile_reads_nothing(prof):
    from tft.tft_ocr_reader import TftOcrReader

    reader = TftOcrReader(engine=FakeEngine(ANSWERS), profile=prof)
    reader._profile = None          # e.g. a 21:9 client: no profile -> absent, not a guess
    assert reader.read_frame_fields(synthetic_frame(prof)) == {}


@needs_tesseract
def test_live_reader_real_pixels_1280x720(prof):
    from tft.tft_ocr_reader import TftOcrReader

    frame = _manifest()["frames"][FRAMES[-1]]
    exp = frame["expect"]
    got = TftOcrReader(profile=prof).read_frame_fields(_composite(frame))
    assert got == {"stage_round": exp["label"], "level": exp["level"], "gold": exp["gold"],
                   "hp": exp["own_hp"]}


# Match 3 (20261025-085349) round starts in game seconds, from the client TFT.log
# phase lines (QA_REPORT round table). Game data, no identity.
MATCH3_ROUND_STARTS = (
    ("1-1", 0), ("1-2", 34), ("1-3", 65), ("1-4", 103), ("2-1", 140), ("2-2", 226),
    ("2-3", 302), ("2-4", 378), ("2-5", 415), ("2-6", 490), ("2-7", 566), ("3-1", 615),
    ("3-2", 690), ("3-3", 790), ("3-4", 864), ("3-5", 902), ("3-6", 978), ("3-7", 1056),
    ("4-1", 1107), ("4-2", 1188), ("4-3", 1280), ("4-4", 1352), ("4-5", 1389), ("4-6", 1464),
    ("4-7", 1536), ("5-1", 1587), ("5-2", 1658), ("5-3", 1734), ("5-4", 1810), ("5-5", 1841),
    ("5-6", 1912), ("5-7", 1974), ("6-1", 2021),
)
# The QA recorder dir is gitignored and lives in the main checkout; a worktree
# (or CI) points at it with RC_TFT_QA_ROOT, else the test skips.
MATCH3_DIR = Path(os.environ.get("RC_TFT_QA_ROOT")
                  or REPO_ROOT / "ops" / "runtime" / "tft_qa") / "20261025-085349" / "frames"


def _match3_truth(gt: float):
    starts = [s for _, s in MATCH3_ROUND_STARTS]
    idx = max(i for i, s in enumerate(starts) if s <= gt)
    nxt = starts[idx + 1] if idx + 1 < len(starts) else None
    if gt - starts[idx] < 3 or (nxt is not None and nxt - gt < 3):
        return None                    # within 3 s of a round change: not graded
    return MATCH3_ROUND_STARTS[idx][0]


@needs_tesseract
@pytest.mark.skipif(not MATCH3_DIR.is_dir(), reason="local match-3 corpus absent (gitignored)")
def test_live_reader_stage_on_real_match3_relay_frames(prof):
    """N7 regression on the real 1280x720 relay frames of match 3: the old boxes read
    0 of 12 stages right; the cv regions must read every graded stage right (absent is
    allowed, wrong is not) and cover at least 85 percent of them."""
    from tft.tft_ocr_reader import TftOcrReader

    reader = TftOcrReader(profile=prof)
    right = wrong = graded = 0
    for path in sorted(MATCH3_DIR.glob("vision_*_gt*.jpg")):
        truth = _match3_truth(float(path.stem.split("_gt")[1]))
        if truth is None:
            continue
        with Image.open(path) as im:
            assert im.size == SIZE
            got = reader.read_frame_fields(im.convert("RGB"), ("stage",)).get("stage_round")
        graded += 1
        if got is not None:
            right += got == truth
            wrong += got != truth
    assert graded >= 50
    assert wrong == 0
    assert right / graded >= 0.85
