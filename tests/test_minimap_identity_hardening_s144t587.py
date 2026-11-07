"""Hardening tests for core.minimap_identity (lane true-audit, S144-T-587).

Each test pins one audited weakness of identify_dots / _icon_index /
_template_size / _num (core/minimap_identity.py):

  1. an int frac too large for a float raised OverflowError out of _num, so
     ONE bad dot voided the identity pass for every later dot;
  2. one roster champion could be tagged on two dots in the same frame (two
     nearby dots whose search windows both cover the one icon) - a wrong
     identity, which the module's own contract ranks worse than none;
  3. a DDragon mirror id was joined onto the icon dir with no containment, so
     an absolute or ".."-bearing id indexed a .png outside data/icons/champions;
  4. the roster cap ("NEVER the full 173-icon catalog") and the per-frame dot
     budget were unenforced;
  5. a float crop holding NaN was cast to uint8 through an undefined cast
     (RuntimeWarning; under warnings-as-errors the whole pass was lost);
  6. a numpy float32 frac was refused as "not a number";
  7. _template_size raised on an int too large for a float and returned the
     live size for inf / bool, against its "bad input -> _MIN_TPL" docstring.

Synthetic fixtures only (live template-match quality is LIVE-GATED).
ASCII only (repo hard rule).
"""
import json
import warnings

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

import core.minimap_identity as mi  # noqa: E402

W = H = 208


@pytest.fixture(autouse=True)
def _fresh_caches():
    mi._reset_caches()
    yield
    mi._reset_caches()


def _paste(crop, champ, cx, cy):
    size = mi._template_size(crop.shape[1])
    tm = mi._masked_template(champ, size)
    assert tm is not None, f"template for {champ} must load"
    tpl, mask = tm
    half = size // 2
    region = crop[cy - half:cy - half + size, cx - half:cx - half + size]
    m = mask.astype(bool)
    region[m] = tpl[m]


def _dot(cx, cy, team="red"):
    return {"team": team, "x_frac": cx / (W - 1), "y_frac": cy / (H - 1),
            "px": 40, "confidence": 0.8}


def _flat():
    return np.full((H, W, 3), 30, dtype=np.uint8)


# --- 1. one overflowing dot must not void the rest ---------------------------

def test_num_int_too_large_for_float_is_none():
    assert mi._num(10 ** 400) is None
    assert mi._num(-(10 ** 400)) is None


def test_overflowing_dot_does_not_void_later_dots():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    bad = {"team": "red", "x_frac": 10 ** 400, "y_frac": 0.5,
           "px": 40, "confidence": 0.9}
    good = _dot(60, 80)
    dots = [bad, good]
    out = mi.identify_dots(crop, dots, ["Ashe", "Garen"])
    assert out is dots and len(out) == 2
    assert "champion" not in bad
    assert good.get("champion") == "Ashe"


# --- 2. one champion, one dot (roster multiplicity is the quota) -------------

def test_one_icon_two_overlapping_dots_tags_one_dot_only():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    a = _dot(60, 80)
    b = _dot(65, 80)  # 5 px away: its +-19 px window still holds the icon
    dots = [a, b]
    mi.identify_dots(crop, dots, ["Ashe", "Garen"])
    tagged = [d for d in dots if d.get("champion") == "Ashe"]
    assert len(tagged) == 1
    untagged = [d for d in dots if "champion" not in d]
    assert len(untagged) == 1
    assert "identity_confidence" not in untagged[0]


def test_tie_goes_to_the_earlier_dot():
    """The two dots score the same best offset; input order (the detector's
    confidence order) breaks the tie, so the result is deterministic."""
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    a = _dot(60, 80)
    b = _dot(60, 80)
    mi.identify_dots(crop, [a, b], ["Ashe"])
    assert a.get("champion") == "Ashe"
    assert "champion" not in b


def test_higher_scoring_dot_wins_the_champion(monkeypatch):
    """The champion goes to the dot that matches it BEST, not to the first dot
    scanned: scores are fed in scan order (first dot 0.70, second 0.90)."""
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    scores = iter([0.70, 0.90])
    monkeypatch.setattr(mi, "_match_score",
                        lambda *_a, **_k: next(scores))
    first = _dot(60, 80)
    second = _dot(60, 80)
    mi.identify_dots(crop, [first, second], ["Ashe"])
    assert "champion" not in first and "identity_confidence" not in first
    assert second.get("champion") == "Ashe"
    assert second.get("identity_confidence") == 0.9


def test_repeated_roster_entry_allows_repeated_tags():
    """One For All: the same champion fills several seats, so the quota is the
    roster multiplicity, not one."""
    crop = _flat()
    _paste(crop, "Ashe", 50, 50)
    _paste(crop, "Ashe", 150, 150)
    a = _dot(50, 50)
    b = _dot(150, 150)
    mi.identify_dots(crop, [a, b], ["Ashe", "Ashe"])
    assert a.get("champion") == "Ashe" and b.get("champion") == "Ashe"


def test_single_roster_entry_two_icons_tags_one():
    crop = _flat()
    _paste(crop, "Ashe", 50, 50)
    _paste(crop, "Ashe", 150, 150)
    a = _dot(50, 50)
    b = _dot(150, 150)
    mi.identify_dots(crop, [a, b], ["Ashe"])
    assert [a.get("champion"), b.get("champion")].count("Ashe") == 1


def test_display_variants_share_one_quota():
    """'Wukong' and 'MonkeyKing' are one champion (one icon stem): listing both
    spellings once each is a multiplicity of two, not two champions."""
    crop = _flat()
    _paste(crop, "Wukong", 50, 50)
    _paste(crop, "Wukong", 150, 150)
    a = _dot(50, 50)
    b = _dot(150, 150)
    mi.identify_dots(crop, [a, b], ["Wukong"])
    assert [a.get("champion"), b.get("champion")].count("Wukong") == 1
    a.pop("champion", None)
    b.pop("champion", None)
    mi.identify_dots(crop, [a, b], ["Wukong", "MonkeyKing"])
    assert a.get("champion") == "Wukong" and b.get("champion") == "Wukong"


# --- 3. DDragon id containment -----------------------------------------------

def _mirror(tmp_path, monkeypatch, entries):
    icon_dir = tmp_path / "icons" / "champions"
    icon_dir.mkdir(parents=True)
    (icon_dir / "Ashe.png").write_bytes(b"x")
    champs = tmp_path / "ddragon_champions.json"
    champs.write_text(json.dumps({"data": entries}), encoding="utf-8")
    monkeypatch.setattr(mi, "_ICON_DIR", icon_dir)
    monkeypatch.setattr(mi, "_CHAMPS_PATH", champs)
    mi._reset_caches()
    return icon_dir


def test_dotdot_ddragon_id_is_not_indexed(tmp_path, monkeypatch):
    (tmp_path / "icons" / "evil.png").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "icons" / "evil.png").write_bytes(b"x")
    _mirror(tmp_path, monkeypatch, {
        "Evil": {"id": "../evil", "name": "Evil"},
        "Ashe": {"id": "Ashe", "name": "Ashe"},
    })
    assert mi._icon_path("Evil") is None
    assert mi._icon_path("Ashe") is not None


def test_absolute_ddragon_id_is_not_indexed(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "abs.png").write_bytes(b"x")
    _mirror(tmp_path, monkeypatch, {
        "Abs": {"id": str(outside / "abs"), "name": "Abs"},
    })
    assert mi._icon_path("Abs") is None


def test_bad_id_falls_back_to_a_clean_key(tmp_path, monkeypatch):
    icon_dir = _mirror(tmp_path, monkeypatch, {
        "Ashe": {"id": "../Ashe", "name": "Frost Archer Alias"},
    })
    p = mi._icon_path("Frost Archer Alias")
    assert p is not None and p.parent == icon_dir


# --- 4. roster cap and dot budget --------------------------------------------

def test_roster_over_cap_passes_through_unchanged():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    dots = [_dot(60, 80)]
    roster = ["Ashe"] + ["Garen"] * mi._MAX_ROSTER
    assert len(roster) > mi._MAX_ROSTER
    out = mi.identify_dots(crop, dots, roster)
    assert out is dots and "champion" not in dots[0]


def test_roster_at_cap_still_identifies():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    dots = [_dot(60, 80)]
    roster = ["Ashe"] + ["Garen"] * (mi._MAX_ROSTER - 1)
    mi.identify_dots(crop, dots, roster)
    assert dots[0].get("champion") == "Ashe"


def test_dots_beyond_budget_pass_through_untouched():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    filler = [_dot(180, 180) for _ in range(mi._MAX_DOTS)]
    target = _dot(60, 80)
    dots = filler + [target]
    out = mi.identify_dots(crop, dots, ["Ashe"])
    assert out is dots and len(out) == mi._MAX_DOTS + 1
    assert "champion" not in target


def test_dot_inside_budget_is_identified():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    filler = [_dot(180, 180) for _ in range(mi._MAX_DOTS - 1)]
    target = _dot(60, 80)
    mi.identify_dots(crop, filler + [target], ["Ashe"])
    assert target.get("champion") == "Ashe"


# --- 5. NaN float crop --------------------------------------------------------

def test_nan_float_crop_identifies_without_an_invalid_cast():
    crop = _flat().astype(np.float64)
    _paste(crop, "Ashe", 60, 80)
    crop[0:5, 0:5, :] = np.nan
    crop[200:205, 200:205, :] = np.inf
    dots = [_dot(60, 80)]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        mi.identify_dots(crop, dots, ["Ashe"])
    assert dots[0].get("champion") == "Ashe"


def test_non_numeric_crop_dtype_passes_through():
    crop = np.full((H, W, 3), "a", dtype=object)
    dots = [_dot(60, 80)]
    assert mi.identify_dots(crop, dots, ["Ashe"]) is dots
    assert "champion" not in dots[0]


def test_complex_crop_is_refused_not_silently_truncated():
    """A complex crop is not an image: the dtype gate refuses it instead of
    casting away the imaginary part (a ComplexWarning) and matching on it."""
    real = _flat()
    _paste(real, "Ashe", 60, 80)
    crop = real.astype(np.complex128)
    dots = [_dot(60, 80)]
    # warnings stay at the default filter: an "error" filter would turn the
    # ComplexWarning into an exception the fail-soft except swallows, and the
    # test could not tell the gate from the swallow.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        out = mi.identify_dots(crop, dots, ["Ashe"])
    assert out is dots and "champion" not in dots[0]
    # positive control: the same pixels as uint8 DO identify
    ctl = [_dot(60, 80)]
    mi.identify_dots(real, ctl, ["Ashe"])
    assert ctl[0].get("champion") == "Ashe"


# --- 6. numpy scalar fracs ----------------------------------------------------

def test_numpy_float32_frac_is_accepted():
    crop = _flat()
    _paste(crop, "Ashe", 60, 80)
    d = _dot(60, 80)
    d["x_frac"] = np.float32(d["x_frac"])
    d["y_frac"] = np.float32(d["y_frac"])
    mi.identify_dots(crop, [d], ["Ashe"])
    assert d.get("champion") == "Ashe"


def test_numpy_bool_frac_is_refused():
    assert mi._num(np.bool_(True)) is None
    assert mi._num(True) is None


# --- 7. _template_size bad input ---------------------------------------------

@pytest.mark.parametrize("bad", [10 ** 400, float("inf"), float("-inf"),
                                 float("nan"), True, False, -5, 0, "x", None],
                         ids=["huge_int", "inf", "-inf", "nan", "True",
                              "False", "neg", "zero", "str", "None"])
def test_template_size_bad_input_is_min(bad):
    assert mi._template_size(bad) == mi._MIN_TPL


def test_template_size_good_input_is_fixed_icon_px():
    assert mi._template_size(208) == mi._ICON_PX
    assert mi._template_size(568.0) == mi._ICON_PX
