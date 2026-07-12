"""RED-first TDD for the Lane E CV atlas flip-readiness harness.

Two units under test, one feature slice:

  1. core.vision_template_match.score_all - a NEW public helper returning the
     raw (stem, confidence) score for EVERY candidate in a category (the
     substrate match_icon already computes internally). match_icon is refactored
     to a thin argmax+threshold wrapper over it; the r96 suite pins that
     match_icon behavior is unchanged.

  2. tools.vision_atlas_validate - the offline harness that runs score_all over
     a category's own pristine icons (a synthetic crop per icon) and reports
     self-match accuracy, the nearest-confuser margins, and a threshold sweep.
     This is the PRISTINE-ICON CEILING, not live in-game accuracy (live frames
     are operator/live-gated); the report says so.

Hermetic: the harness unit test runs "spells" only (18 icons -> 324 matches,
fast); champions/items are exercised via the CLI, not the suite. cv2 required.

ASCII only (repo hard rule). No em-dashes.
"""
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

import core.vision_template_match as vtm
import tools.vision_atlas_validate as vav

_FIX = Path(__file__).resolve().parent / "fixtures" / "vision_template"


@pytest.fixture(autouse=True)
def _fresh_caches():
    vtm._reset_caches()
    yield
    vtm._reset_caches()


def _load(name):
    img = cv2.imread(str(_FIX / name), cv2.IMREAD_COLOR)
    assert img is not None, "missing fixture: " + name
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


# --- score_all (core) -------------------------------------------------------

def test_score_all_covers_full_catalog():
    crop = _load("champ_crop.png")
    scored = vtm.score_all(crop, "champions")
    assert isinstance(scored, list)
    assert len(scored) == 173
    stems = [s for s, _c in scored]
    assert "Aatrox" in stems
    for _stem, conf in scored:
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0


def test_score_all_argmax_matches_match_icon():
    crop = _load("champ_crop.png")
    scored = vtm.score_all(crop, "champions")
    top_id = max(scored, key=lambda sc: sc[1])[0]
    assert top_id == "Aatrox"
    # match_icon must agree with score_all's argmax (single code path).
    icon_id, _conf = vtm.match_icon(crop, "champions")
    assert icon_id == "Aatrox"


def test_score_all_roster_scope_and_fail_soft():
    crop = _load("champ_crop.png")
    only = vtm.score_all(crop, "champions", roster=["Ahri", "Zed"])
    assert sorted(s for s, _c in only) == ["Ahri", "Zed"]
    assert vtm.score_all(None, "champions") == []
    assert vtm.score_all(crop, "does_not_exist") == []


# --- harness (tools) --------------------------------------------------------

def test_synth_crop_pads_and_is_rgb_uint8():
    tpl = vtm._atlas("spells")[vtm.list_ids("spells")[0]]
    crop = vav.synth_crop(tpl)
    assert crop.dtype == np.uint8
    assert crop.ndim == 3 and crop.shape[2] == 3
    # A dark border is added, so the crop is strictly larger than the icon.
    assert crop.shape[0] > tpl.shape[0]
    assert crop.shape[1] > tpl.shape[1]


def test_validate_category_spells_shape_and_ceiling():
    res = vav.validate_category("spells", worst_n=100)
    assert res["category"] == "spells"
    assert res["n"] == 18
    assert res["self_match"]["total"] == 18
    # Pristine-icon ceiling: every icon self-recognizes at ~1.0.
    assert all(c["self_conf"] >= 0.99 for c in res["confusions"])
    # The raw rate dips below 100% ONLY because DDragon ships pixel-identical
    # mode-variant duplicates (Arena Flash, ARAM Snowball). Every self-match
    # miss is one of those identical twins, never a genuine confusion, so the
    # effective rate (crediting twins) is perfect.
    assert res["identical_twins"], "expected the Arena/ARAM duplicate spell icons"
    for w in res["wrong"]:
        assert w in res["identical_twins"]
    assert res["effective_rate"] == 1.0
    # Distinct icons stay well separated: the smallest NON-zero margin is not
    # marginal (only the identical twins sit at margin 0.0).
    nonzero = sorted(c["margin"] for c in res["confusions"] if c["margin"] > 1e-6)
    assert nonzero and nonzero[0] >= 0.2
    # threshold_sweep is keyed by each configured threshold and partitions n.
    assert set(res["threshold_sweep"].keys()) == set(vav.THRESHOLDS)
    for _thr, cell in res["threshold_sweep"].items():
        assert cell["confident_correct"] + cell["confident_wrong"] + cell["abstain"] == 18
    # confusions carry a nearest-confuser margin, smallest first.
    margins = [c["margin"] for c in res["confusions"]]
    assert margins == sorted(margins)


def test_render_report_is_honest_markdown():
    res = vav.validate_category("spells")
    md = vav.render_report({"spells": res})
    assert isinstance(md, str)
    assert "spells" in md
    # The report must flag that this is the pristine ceiling, not live accuracy.
    assert "ceiling" in md.lower()
