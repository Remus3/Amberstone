"""s144 true-audit cycle 132: core/vision_template_match.py hardening.

One test group per finding (RM-1624..RM-1630), each written RED first against
the pre-fix module:

  RM-1624  cv2.imread cannot open a non-ASCII path on Windows, so a checkout
              under a folder name like "icones" with an accent loaded an EMPTY
              atlas (and printed a cv2 WARN per icon). Icons are now read as
              bytes and decoded with cv2.imdecode.
  RM-1625  a roster that was not a list / tuple / set (a frozenset, a dict
              view, a generator, a bare string, a mapping) silently widened
              the candidate set to the FULL catalog - the exact wrong-id risk
              the roster exists to remove. A set roster resolved in hash order,
              so a tie picked a different winner per process.
  RM-1626  an oversized crop (a whole frame passed as a crop) had no bound:
              a 1500 px crop over the 18 spells took seconds and cached 117 MB.
  RM-1627  the resized-template cache grew without bound, one full catalog
              per distinct crop size, for the process lifetime.
  RM-1628  match_icon decided on the UNROUNDED score but reported the
              rounded one, so a score of 0.59996 came back as (None, 0.6) at
              the default 0.6 threshold.
  RM-1629  a float crop holding NaN / inf was cast to uint8 (platform-
              defined garbage plus a RuntimeWarning) and scored as if real.
  RM-1630  an icon file was decoded whatever it claimed to be: a PNG header
              declaring a huge canvas (a decompression bomb from a refilled
              icon folder) and an oversized file are now skipped undecoded.

ASCII only (repo hard rule).
"""
from __future__ import annotations

import itertools
import shutil
import struct
import warnings
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import core.vision_template_match as vtm  # noqa: E402 - after importorskip

_REPO = Path(__file__).resolve().parent.parent
_SPELLS = _REPO / "data" / "icons" / "spells"
_FIX = Path(__file__).resolve().parent / "fixtures" / "vision_template"


@pytest.fixture(autouse=True)
def _fresh_caches():
    vtm._reset_caches()
    yield
    vtm._reset_caches()


def _first_spell() -> Path:
    pngs = sorted(_SPELLS.glob("*.png"))
    assert pngs, "the tracked spell icons are the fixture"
    return pngs[0]


def _rgb(path: Path):
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


# -- RM-1624: non-ASCII icon folder -----------------------------------------

def test_non_ascii_category_folder_still_loads(tmp_path, monkeypatch):
    folder = tmp_path / ("ic" + chr(0xF4) + "nes")  # source stays ASCII
    folder.mkdir()
    src = _first_spell()
    shutil.copyfile(src, folder / src.name)
    monkeypatch.setitem(vtm._CATEGORY_DIRS, "spells", folder)
    assert vtm.list_ids("spells") == [src.stem]
    assert vtm._atlas("spells")[src.stem].shape == _rgb(src).shape


def test_loaded_icon_is_rgb_not_bgr(tmp_path, monkeypatch):
    folder = tmp_path / "spells"
    folder.mkdir()
    src = _first_spell()
    shutil.copyfile(src, folder / src.name)
    monkeypatch.setitem(vtm._CATEGORY_DIRS, "spells", folder)
    assert np.array_equal(vtm._atlas("spells")[src.stem], _rgb(src))


# -- RM-1625: roster shapes -------------------------------------------------

@pytest.mark.parametrize("roster", [
    frozenset(["Ahri"]),
    {"Ahri": 1}.keys(),
    (name for name in ["Ahri"]),
    ["Ahri"],
    ("Ahri",),
    {"Ahri"},
], ids=["frozenset", "dict_keys", "generator", "list", "tuple", "set"])
def test_any_iterable_roster_restricts_the_candidates(roster):
    assert vtm._candidate_stems("champions", roster) == ["Ahri"]


@pytest.mark.parametrize("roster", [
    "Ahri", b"Ahri", {"Ahri": 1}, 5, 1.5, object(),
], ids=["str", "bytes", "mapping", "int", "float", "object"])
def test_an_unreadable_roster_fails_closed_not_to_the_full_catalog(roster):
    assert vtm._candidate_stems("champions", roster) == []
    crop = _rgb(_FIX / "champ_crop.png") if (_FIX / "champ_crop.png").is_file() else None
    if crop is not None:
        assert vtm.match_icon(crop, "champions", roster=roster) == (None, 0.0)


@pytest.mark.parametrize("roster", [None, [], (), frozenset(), set()],
                         ids=["none", "list", "tuple", "frozenset", "set"])
def test_absent_or_empty_roster_is_the_full_catalog(roster):
    assert vtm._candidate_stems("champions", roster) == vtm.list_ids("champions")


def test_unordered_roster_resolves_in_catalog_order():
    names = ["Zed", "Ahri", "Annie", "Jinx"]
    want = sorted(names)
    assert vtm._candidate_stems("champions", set(names)) == want
    assert vtm._candidate_stems("champions", frozenset(names)) == want
    # An ORDERED roster keeps the caller's order (the documented tie rule).
    assert vtm._candidate_stems("champions", names) == names


def test_unbounded_roster_iterable_is_capped():
    out = vtm._candidate_stems("champions", itertools.repeat("Ahri"))
    assert out == ["Ahri"]


# -- RM-1626: oversized crop ------------------------------------------------

def test_crop_edge_above_the_cap_is_refused():
    edge = vtm._MAX_CROP_EDGE
    assert 600 <= edge <= 2048, "the validator's synthetic 512 px item crops must fit"
    over = np.zeros((40, edge + 1, 3), np.uint8)
    assert vtm.score_all(over, "spells") == []
    assert vtm.match_icon(over, "spells") == (None, 0.0)
    assert vtm._TPL_CACHE == {}


def test_crop_edge_at_the_cap_is_scored():
    at = np.zeros((40, vtm._MAX_CROP_EDGE, 3), np.uint8)
    assert len(vtm.score_all(at, "spells")) == len(vtm.list_ids("spells"))


# -- RM-1627: template cache budget -----------------------------------------

def _cache_bytes() -> int:
    return sum(t.nbytes + m.nbytes for t, m in vtm._TPL_CACHE.values())


def test_template_cache_stays_within_its_byte_budget(monkeypatch):
    assert 0 < vtm._TPL_CACHE_MAX_BYTES <= 256 * 1024 * 1024
    monkeypatch.setattr(vtm, "_TPL_CACHE_MAX_BYTES", 60_000)
    rng = np.random.default_rng(7)
    for edge in (20, 24, 28, 32, 36, 40, 44, 48):
        crop = rng.integers(0, 255, (edge, edge, 3), dtype=np.uint8)
        scored = vtm.score_all(crop, "spells")
        assert len(scored) == len(vtm.list_ids("spells"))
        assert _cache_bytes() <= 60_000


def test_eviction_does_not_change_scores(monkeypatch):
    crop = np.random.default_rng(3).integers(0, 255, (40, 40, 3), dtype=np.uint8)
    full = vtm.score_all(crop, "spells")
    vtm._reset_caches()
    monkeypatch.setattr(vtm, "_TPL_CACHE_MAX_BYTES", 5_000)
    assert vtm.score_all(crop, "spells") == full


def test_a_template_larger_than_the_budget_is_not_cached(monkeypatch):
    monkeypatch.setattr(vtm, "_TPL_CACHE_MAX_BYTES", 10)
    stem = vtm.list_ids("spells")[0]
    tm = vtm._resized_template("spells", stem, 32)
    assert tm is not None and tm[0].shape == (32, 32, 3)
    assert vtm._TPL_CACHE == {}


# -- RM-1628: threshold decided on the reported number ----------------------

@pytest.mark.parametrize("score, thr, want", [
    (0.59996, None, ("A", 0.6)),
    (0.5994, None, (None, 0.599)),
    (0.74996, 0.75, ("A", 0.75)),
    (0.7494, 0.75, (None, 0.749)),
])
def test_threshold_is_decided_on_the_reported_confidence(monkeypatch, score, thr, want):
    monkeypatch.setattr(vtm, "score_all", lambda *a, **k: [("A", score)])
    got = vtm.match_icon(np.zeros((40, 40, 3), np.uint8), "spells", threshold=thr)
    assert got == want
    icon_id, conf = got
    assert (icon_id is not None) == (conf >= (0.6 if thr is None else thr))


# -- RM-1629: non-finite float crop -----------------------------------------

@pytest.mark.parametrize("fill", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "inf", "-inf"])
def test_non_finite_float_crop_is_refused(fill):
    crop = np.zeros((40, 40, 3), np.float64)
    crop[5, 5, 1] = fill
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert vtm.score_all(crop, "spells") == []
        assert vtm.match_icon(crop, "spells") == (None, 0.0)
    assert [w for w in caught if issubclass(w.category, RuntimeWarning)] == []


def test_finite_float_crop_matches_like_its_uint8_twin():
    src = _first_spell()
    icon = _rgb(src)
    canvas = np.full((76, 76, 3), 20, np.uint8)
    canvas[6:70, 6:70] = icon
    want = vtm.match_icon(canvas, "spells")
    assert want[0] == src.stem
    assert vtm.match_icon(canvas.astype(np.float64), "spells") == want


# -- RM-1630: icon decode guards --------------------------------------------

def _png_header(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr
            + b"\x00\x00\x00\x00")


def _counting_imdecode(monkeypatch) -> list:
    calls = []
    real = cv2.imdecode

    def counting(buf, flag):
        calls.append(len(buf))
        return real(buf, flag)

    monkeypatch.setattr(cv2, "imdecode", counting)
    return calls


def test_png_declaring_a_huge_canvas_is_skipped_undecoded(tmp_path, monkeypatch):
    folder = tmp_path / "spells"
    folder.mkdir()
    src = _first_spell()
    shutil.copyfile(src, folder / src.name)
    (folder / "Bomb.png").write_bytes(_png_header(40000, 40000))
    monkeypatch.setitem(vtm._CATEGORY_DIRS, "spells", folder)
    calls = _counting_imdecode(monkeypatch)
    assert vtm.list_ids("spells") == [src.stem]
    assert len(calls) == 1, "only the real icon is decoded"


def test_oversized_icon_file_is_skipped_unread(tmp_path, monkeypatch):
    folder = tmp_path / "spells"
    folder.mkdir()
    src = _first_spell()
    shutil.copyfile(src, folder / src.name)
    big = folder / "Big.png"
    big.write_bytes(src.read_bytes() + b"\x00" * 64)
    monkeypatch.setattr(vtm, "_MAX_ICON_BYTES", src.stat().st_size)
    monkeypatch.setitem(vtm._CATEGORY_DIRS, "spells", folder)
    calls = _counting_imdecode(monkeypatch)
    read = []
    real_read = Path.read_bytes

    def counting_read(self):
        read.append(self.name)
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", counting_read)
    assert vtm.list_ids("spells") == [src.stem]
    assert len(calls) == 1
    assert "Big.png" not in read, "an oversized icon is never read into memory"


def test_icon_guards_have_sane_defaults():
    assert 1024 * 1024 <= vtm._MAX_ICON_BYTES <= 64 * 1024 * 1024
    assert 512 <= vtm._MAX_ICON_EDGE <= 4096
