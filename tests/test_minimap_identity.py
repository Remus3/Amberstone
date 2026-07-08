"""Tests for core.minimap_identity (ZOI plan spec E-1) - minimap champion
identity via circle-masked icon template match, plus the RC_ZOI_IDENTITY gate
in core.minimap_blob_detect.current_minimap_dots.

API surfaces grep-confirmed before scaffolding:
  - core/minimap_blob_detect.py:269 current_minimap_dots(minimap_rect, ttl_s)
  - core/minimap_blob_detect.py:155 _dots_cache (test reset seam)
  - core/minimap_blob_detect.py:173 _scaled_size_bounds(crop_w)
  - core/liveclient_cache.py:224 get() -> Snapshot; :40-56 Snapshot(data=...)
  - core/vision_tracker.py:307 roster names = allPlayers[].championName
  - data/icons/champions/<DDragonId>.png (173 on disk, verified)

Synthetic fixtures only - live template-match quality is LIVE-GATED; these
tests prove the gated, fail-soft plumbing. ASCII only (repo hard rule).
"""
import builtins

import pytest

np = pytest.importorskip("numpy")

import core.liveclient_cache as lcc
import core.minimap_blob_detect as mbd
import core.minimap_identity as mi


def _has_cv2() -> bool:
    try:
        import cv2  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


needs_cv2 = pytest.mark.skipif(not _has_cv2(), reason="opencv-python not installed")

RECT = {"x": 1600, "y": 761, "w": 312, "h": 312}


def _synthetic_crop_with_icon(champ="Ashe", w=208, h=208, cx=60, cy=80):
    """Paste the module's own circle-masked template into a flat crop at a
    known spot. Returns (crop, dots) where the one dot sits on the icon."""
    size = mi._template_size(w)
    tm = mi._masked_template(champ, size)
    assert tm is not None, f"template for {champ} must load"
    tpl, mask = tm
    crop = np.full((h, w, 3), 30, dtype=np.uint8)
    half = size // 2
    top, left = cy - half, cx - half
    region = crop[top:top + size, left:left + size]
    m = mask.astype(bool)
    region[m] = tpl[m]
    dot = {"team": "red", "x_frac": cx / w, "y_frac": cy / h,
           "px": 40, "confidence": 0.8}
    return crop, [dot]


def _reset_dots_cache():
    mbd._dots_cache.update(wall=0.0, rect=None, dots=[])


# --- identify_dots: match quality on synthetic fixtures ----------------------

@needs_cv2
def test_synthetic_icon_matched_to_correct_champion():
    crop, dots = _synthetic_crop_with_icon("Ashe")
    orig = [dict(d) for d in dots]
    out = mi.identify_dots(crop, dots, ["Ashe", "Garen", "Ahri"])
    assert out is dots and len(out) == 1
    d = out[0]
    assert d["champion"] == "Ashe"
    assert d["identity_confidence"] >= mi._MATCH_THRESHOLD
    assert d["identity_confidence"] <= 1.0
    # additive only - every original field survives untouched
    for k, v in orig[0].items():
        assert d[k] == v


@needs_cv2
def test_non_roster_champion_never_returned():
    crop, dots = _synthetic_crop_with_icon("Ashe")
    out = mi.identify_dots(crop, dots, ["Garen"])
    for d in out:
        assert d.get("champion") in (None, "Garen")


@needs_cv2
def test_threshold_rejection(monkeypatch):
    """Below the confidence threshold -> no champion tag (deterministic via a
    threshold no score can reach)."""
    crop, dots = _synthetic_crop_with_icon("Ashe")
    monkeypatch.setattr(mi, "_MATCH_THRESHOLD", 1.01)
    out = mi.identify_dots(crop, dots, ["Ashe"])
    assert out is dots
    assert "champion" not in out[0]
    assert "identity_confidence" not in out[0]


@needs_cv2
def test_passthrough_dot_far_from_any_icon():
    """A dot over flat background must pass through unchanged (Pearson stage
    scores a flat window 0)."""
    crop, _ = _synthetic_crop_with_icon("Ashe", cx=60, cy=80)
    dot = {"team": "blue", "x_frac": 150 / 208, "y_frac": 150 / 208,
           "px": 20, "confidence": 0.5}
    out = mi.identify_dots(crop, [dot], ["Ashe"])
    assert out[0].get("champion") is None
    assert "identity_confidence" not in out[0]


@needs_cv2
def test_never_removes_or_reorders_dots():
    crop, dots = _synthetic_crop_with_icon("Ashe")
    extra = {"team": "blue", "x_frac": 0.9, "y_frac": 0.9,
             "px": 12, "confidence": 0.3}
    dots.append(extra)
    out = mi.identify_dots(crop, dots, ["Ashe"])
    assert out is dots and len(out) == 2
    assert out[1] is extra


@needs_cv2
def test_display_name_variants_resolve():
    """Live roster carries Live Client championName display strings
    (core/vision_tracker.py:307) - all variants must find an icon file."""
    for name in ("Miss Fortune", "Kha'Zix", "Wukong", "ashe", "MonkeyKing"):
        assert mi._icon_path(name) is not None, name
    assert mi._icon_path("Notachamp9000") is None
    assert mi._icon_path(None) is None


@needs_cv2
def test_template_cache_reuse(monkeypatch):
    """Resized masked templates are cached keyed (champ icon, size) - the
    second call must not re-read the icon from disk."""
    import cv2
    mi._reset_caches()
    calls = {"n": 0}
    real = cv2.imread

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(cv2, "imread", counting)
    t1 = mi._masked_template("Ashe", 16)
    t2 = mi._masked_template("Ashe", 16)
    assert t1 is not None and t2 is not None
    assert calls["n"] == 1
    assert t1[0] is t2[0] and t1[1] is t2[1]
    # a different size is a different cache entry
    t3 = mi._masked_template("Ashe", 20)
    assert t3 is not None and calls["n"] == 2


# --- identify_dots: fail-soft contract ---------------------------------------

def test_cv2_absent_failsoft(monkeypatch):
    """cv2 import failure -> dots returned UNCHANGED (fail-soft)."""
    crop = np.zeros((60, 60, 3), dtype=np.uint8)
    dots = [{"team": "red", "x_frac": 0.5, "y_frac": 0.5,
             "px": 20, "confidence": 0.6}]
    snapshot = [dict(d) for d in dots]
    real_import = builtins.__import__

    def fake(name, *a, **k):
        if name == "cv2":
            raise ImportError("cv2 unavailable (test)")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    out = mi.identify_dots(crop, dots, ["Ashe"])
    assert out is dots and out == snapshot


def test_malformed_inputs_never_raise():
    dots = [{"team": "red", "x_frac": 0.5, "y_frac": 0.5,
             "px": 9, "confidence": 0.2}]
    assert mi.identify_dots(None, dots, ["Ashe"]) is dots
    assert mi.identify_dots("junk", dots, ["Ashe"]) is dots
    assert mi.identify_dots(np.zeros((60, 60, 3), dtype=np.uint8), dots, None) is dots
    assert mi.identify_dots(np.zeros((60, 60, 3), dtype=np.uint8), dots, []) is dots
    assert mi.identify_dots(np.zeros((60, 60, 3), dtype=np.uint8), None, ["Ashe"]) is None
    assert mi.identify_dots(np.zeros((4, 4, 3), dtype=np.uint8), dots, ["Ashe"]) is dots
    bad = [{"team": "red", "x_frac": "x", "y_frac": None}, "not-a-dict", None]
    out = mi.identify_dots(np.zeros((60, 60, 3), dtype=np.uint8), bad, ["Ashe"])
    assert out is bad and len(out) == 3


def test_unknown_roster_champion_ignored():
    crop = np.full((100, 100, 3), 30, dtype=np.uint8)
    dots = [{"team": "blue", "x_frac": 0.5, "y_frac": 0.5,
             "px": 20, "confidence": 0.5}]
    out = mi.identify_dots(crop, dots, ["Notachamp9000"])
    assert out is dots and "champion" not in out[0]


# --- RC_ZOI_IDENTITY gate in current_minimap_dots ----------------------------

def _fixture_crop():
    crop = np.zeros((60, 60, 3), dtype=np.uint8)
    crop[20:28, 30:38] = (200, 40, 40)  # one vivid red blob
    return crop


def test_identity_flag_parsing(monkeypatch):
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("RC_ZOI_IDENTITY", v)
        assert mbd._identity_enabled() is False, v
    for v in ("1", "true", "YES", "On"):
        monkeypatch.setenv("RC_ZOI_IDENTITY", v)
        assert mbd._identity_enabled() is True, v
    monkeypatch.delenv("RC_ZOI_IDENTITY")
    assert mbd._identity_enabled() is True  # default ON (2026-07-08)


def test_flag_off_byte_identical_and_identity_never_called(monkeypatch):
    monkeypatch.setenv("RC_ZOI_IDENTITY", "0")  # explicit OFF for this test
    crop = _fixture_crop()
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda rect: crop)
    monkeypatch.setattr(mbd, "_grab_frame_minimap", lambda rect: None)

    def boom(*a, **k):
        raise AssertionError("identity path must not run when flag is off")

    monkeypatch.setattr(mi, "identify_dots", boom)
    monkeypatch.setattr(mbd, "_live_roster", boom)
    _reset_dots_cache()
    got = mbd.current_minimap_dots(RECT)
    minpx, maxpx = mbd._scaled_size_bounds(crop.shape[1])
    expected = mbd.detect_team_dots(crop, min_px=minpx, max_px=maxpx)
    assert expected, "fixture must produce at least one dot"
    assert got == expected


def test_flag_on_explicit_roster_passes_through_identity(monkeypatch):
    monkeypatch.setenv("RC_ZOI_IDENTITY", "1")
    crop = _fixture_crop()
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda rect: crop)
    seen = {}

    def fake_identify(c, dots, roster):
        seen["crop_is_fixture"] = c is crop
        seen["roster"] = list(roster)
        for d in dots:
            d["champion"] = "Ashe"
            d["identity_confidence"] = 0.99
        return dots

    monkeypatch.setattr(mi, "identify_dots", fake_identify)
    _reset_dots_cache()
    got = mbd.current_minimap_dots(RECT, roster=["Ashe", "Garen"])
    assert seen["roster"] == ["Ashe", "Garen"]
    assert seen["crop_is_fixture"] is True
    assert got and all(d.get("champion") == "Ashe" for d in got)


def test_flag_on_pulls_liveclient_roster(monkeypatch):
    monkeypatch.setenv("RC_ZOI_IDENTITY", "1")
    crop = _fixture_crop()
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda rect: crop)
    monkeypatch.setattr(mbd, "_live_roster", lambda: ["Ahri"])
    seen = {}

    def fake_identify(c, dots, roster):
        seen["roster"] = list(roster)
        return dots

    monkeypatch.setattr(mi, "identify_dots", fake_identify)
    _reset_dots_cache()
    mbd.current_minimap_dots(RECT)
    assert seen["roster"] == ["Ahri"]


def test_flag_on_empty_roster_skips_identity(monkeypatch):
    monkeypatch.setenv("RC_ZOI_IDENTITY", "1")
    crop = _fixture_crop()
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda rect: crop)
    monkeypatch.setattr(mbd, "_live_roster", lambda: [])

    def boom(*a, **k):
        raise AssertionError("identity must not run on an empty roster")

    monkeypatch.setattr(mi, "identify_dots", boom)
    _reset_dots_cache()
    got = mbd.current_minimap_dots(RECT)
    minpx, maxpx = mbd._scaled_size_bounds(crop.shape[1])
    assert got == mbd.detect_team_dots(crop, min_px=minpx, max_px=maxpx)


def test_flag_on_identity_error_never_breaks_presence(monkeypatch):
    """A broken identity pass degrades to plain presence dots, never []."""
    monkeypatch.setenv("RC_ZOI_IDENTITY", "1")
    crop = _fixture_crop()
    monkeypatch.setattr(mbd, "_grab_native_minimap", lambda rect: crop)
    monkeypatch.setattr(mbd, "_live_roster", lambda: ["Ashe"])

    def boom(*a, **k):
        raise RuntimeError("identity exploded (test)")

    monkeypatch.setattr(mi, "identify_dots", boom)
    _reset_dots_cache()
    got = mbd.current_minimap_dots(RECT)
    minpx, maxpx = mbd._scaled_size_bounds(crop.shape[1])
    assert got == mbd.detect_team_dots(crop, min_px=minpx, max_px=maxpx)


# --- _live_roster fail-soft accessor ------------------------------------------

def test_live_roster_reads_allplayers(monkeypatch):
    snap = lcc.Snapshot(data={"allPlayers": [
        {"championName": "Ashe", "team": "ORDER"},
        {"championName": "Kha'Zix", "team": "CHAOS"},
        {"championName": "", "team": "CHAOS"},
        {"noname": True},
        "not-a-dict",
    ]}, ts=1.0, fetched_at=1.0)
    monkeypatch.setattr(lcc, "get", lambda: snap)
    assert mbd._live_roster() == ["Ashe", "Kha'Zix"]


def test_live_roster_failsoft(monkeypatch):
    def boom():
        raise RuntimeError("relay down (test)")

    monkeypatch.setattr(lcc, "get", boom)
    assert mbd._live_roster() == []
    snap = lcc.Snapshot(data=None, ts=0.0, fetched_at=1.0)
    monkeypatch.setattr(lcc, "get", lambda: snap)
    assert mbd._live_roster() == []
