"""R96 TDD regression: core.vision_template_match generic icon atlas match.

Proves the client-side CV template-match foundation: exact champion / item
recognition on an offset paste, negative rejection of noise, roster scoping,
full-catalog argmax, fail-soft on bad input, and a non-empty cached atlas.
Default-OFF module - this test is its ONLY importer.

Fixtures (tests/fixtures/vision_template/*.png) are real icon pastes on a dark
canvas plus one seeded-noise crop; they are loaded with cv2.imread and
converted BGR->RGB before every call, because match_icon expects an RGB crop.

ASCII only (repo hard rule). No em-dashes.
"""
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import core.vision_template_match as vtm

_FIX = Path(__file__).resolve().parent / "fixtures" / "vision_template"


@pytest.fixture(autouse=True)
def _fresh_caches():
    """Drop the lazy atlas / index / template caches around each test."""
    vtm._reset_caches()
    yield
    vtm._reset_caches()


def _load(name):
    """Load a fixture PNG and convert BGR->RGB (match_icon expects RGB)."""
    img = cv2.imread(str(_FIX / name), cv2.IMREAD_COLOR)
    assert img is not None, "missing fixture: " + name
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def test_exact_champion_match():
    crop = _load("champ_crop.png")
    icon_id, conf = vtm.match_icon(crop, "champions")
    assert icon_id == "Aatrox"
    assert conf >= 0.85


def test_exact_item_match():
    crop = _load("item_crop.png")
    icon_id, conf = vtm.match_icon(crop, "items")
    assert icon_id == "bloodthirster"
    assert conf >= 0.80


def test_negative_noise_is_rejected():
    crop = _load("noise_crop.png")
    icon_id, _conf = vtm.match_icon(crop, "champions")
    assert icon_id is None


def test_roster_restriction():
    crop = _load("champ_crop.png")
    icon_id, _conf = vtm.match_icon(crop, "champions", roster=["Ahri"])
    # Candidate set restricted to the roster -> Aatrox can never win.
    assert icon_id != "Aatrox"


def test_argmax_correct_over_full_catalog():
    crop = _load("champ_crop.png")
    icon_id, _conf = vtm.match_icon(crop, "champions")
    assert icon_id == "Aatrox"


def test_fail_soft():
    champ = _load("champ_crop.png")
    assert vtm.match_icon(None, "champions") == (None, 0.0)
    assert vtm.match_icon(np.zeros((2, 2, 3), np.uint8), "champions") == (None, 0.0)
    assert vtm.match_icon(champ, "does_not_exist") == (None, 0.0)


def test_atlas_nonempty_and_cached():
    assert len(vtm.list_ids("champions")) == 173
    assert len(vtm.list_ids("items")) >= 30
    vtm._reset_caches()
    # Still works after a cache drop (lazy rebuild).
    assert len(vtm.list_ids("champions")) == 173


def test_confidence_bounds():
    champ = _load("champ_crop.png")
    item = _load("item_crop.png")
    noise = _load("noise_crop.png")
    results = [
        vtm.match_icon(champ, "champions"),
        vtm.match_icon(item, "items"),
        vtm.match_icon(noise, "champions"),
        vtm.match_icon(champ, "champions", roster=["Ahri"]),
    ]
    for _icon_id, conf in results:
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0
