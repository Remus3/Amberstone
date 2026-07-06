# arch: P2 deep-audit cycle 7 W1 slice E regression pins | section=tests | frozen=no
"""Deep-audit cycle 7 (P2-W1 slice E) regression tests.

Pins for the two FIX-NOW classes found in the core archetype/vision slice:

1. Subprocess hardening (charter standing class): every pytesseract
   ``image_to_string`` call in ``core.vision_tesseract`` must pass a
   positive ``timeout=`` so a hung tesseract.exe cannot block a thread-pool
   worker forever (pytesseract default timeout=0 waits unbounded; with
   ``read_fast_fields`` running every coach tick, hung processes would
   accumulate threads). pytesseract >= 0.3 kills the child and raises
   RuntimeError on expiry, which the existing per-field except paths
   already absorb (field omitted for that tick).

2. Non-atomic write of a polled/shared JSON file: the first-run defaults
   write of ``data/vision_regions.json`` in ``_regions()`` used a bare
   ``write_text`` (a reader could observe a partial file). It must go
   through the canonical ``core.polled_json.atomic_write_json`` tmp+replace
   idiom.

pytesseract/PIL are NOT installed in CI - tests inject fakes via
sys.modules (the module imports both lazily inside functions; mirrors
tests/test_vision_tesseract_env_config.py).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from core import vision_tesseract as vt

_MODULE_SRC = Path(vt.__file__).read_text(encoding="utf-8")


# -- 1. pytesseract timeout hardening ------------------------------------


class _FakeImg:
    """Minimal stand-in for a PIL image through _preprocess()."""

    width = 10
    height = 10

    def convert(self, _mode):
        return self

    def resize(self, _size, _resample=None):
        return self

    def point(self, _fn):
        return self

    def split(self):
        return (self, self, self)


def _fake_pil():
    mod = types.ModuleType("PIL")
    mod.Image = types.SimpleNamespace(LANCZOS=1)
    image_mod = types.ModuleType("PIL.Image")
    image_mod.LANCZOS = 1
    mod.Image = image_mod
    return mod, image_mod


def _fake_pytesseract(return_text: str, calls: list):
    mod = types.ModuleType("pytesseract")

    def image_to_string(img, lang=None, config="", nice=0,
                        output_type="string", timeout=0):
        calls.append({"config": config, "timeout": timeout})
        return return_text

    mod.image_to_string = image_to_string
    mod.pytesseract = types.SimpleNamespace(tesseract_cmd="tesseract")
    return mod


def test_tess_timeout_constant_exists_and_positive():
    assert hasattr(vt, "_TESS_TIMEOUT_S"), (
        "vision_tesseract must define _TESS_TIMEOUT_S (subprocess hardening)"
    )
    assert vt._TESS_TIMEOUT_S > 0


def test_every_image_to_string_call_passes_timeout():
    """Source guard: no pytesseract call site may omit timeout=.

    Counts call sites (excluding the fake-def line in this test file) and
    requires each to carry the shared timeout constant.
    """
    call_sites = _MODULE_SRC.count("image_to_string(")
    timed = _MODULE_SRC.count("timeout=_TESS_TIMEOUT_S")
    assert call_sites >= 8, f"expected >=8 OCR call sites, found {call_sites}"
    assert timed == call_sites, (
        f"{call_sites - timed} image_to_string call(s) missing "
        "timeout=_TESS_TIMEOUT_S"
    )


def test_ocr_int_passes_timeout_to_pytesseract(monkeypatch):
    calls: list = []
    pil_mod, pil_image_mod = _fake_pil()
    monkeypatch.setitem(sys.modules, "PIL", pil_mod)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image_mod)
    monkeypatch.setitem(
        sys.modules, "pytesseract", _fake_pytesseract("42", calls)
    )
    assert vt._ocr_int(_FakeImg()) == 42
    assert calls, "fake pytesseract was never invoked"
    assert calls[0]["timeout"] == vt._TESS_TIMEOUT_S
    assert calls[0]["timeout"] > 0


def test_ocr_timer_passes_timeout_to_pytesseract(monkeypatch):
    calls: list = []
    pil_mod, pil_image_mod = _fake_pil()
    monkeypatch.setitem(sys.modules, "PIL", pil_mod)
    monkeypatch.setitem(sys.modules, "PIL.Image", pil_image_mod)
    monkeypatch.setitem(
        sys.modules, "pytesseract", _fake_pytesseract("14:38", calls)
    )
    assert vt._ocr_timer(_FakeImg()) == "14:38"
    assert calls and calls[0]["timeout"] == vt._TESS_TIMEOUT_S


# -- 2. atomic defaults write of vision_regions.json ----------------------


def test_regions_default_write_uses_atomic_helper():
    """Source guard: the first-run defaults write must use the canonical
    tmp+replace helper, never a bare write_text on the live path."""
    assert "atomic_write_json" in _MODULE_SRC, (
        "_regions() defaults write must go through "
        "core.polled_json.atomic_write_json"
    )
    assert "_REGIONS_FILE.write_text" not in _MODULE_SRC, (
        "bare non-atomic write_text on _REGIONS_FILE is banned"
    )


def test_regions_default_write_creates_valid_file(monkeypatch, tmp_path):
    """First-run behavior: missing regions file -> defaults written,
    parseable JSON, no tmp residue, defaults returned."""
    target = tmp_path / "vision_regions.json"
    monkeypatch.setattr(vt, "_REGIONS_FILE", target)
    # neutralize the profile layer that now sits in front of the legacy path so
    # this characterizes the legacy vision_regions.json fallback in isolation
    import core.vision_profiles as _vp
    monkeypatch.setattr(_vp, "load_profile", lambda config_key=None: {
        "config_key": "unknown", "base": [1920, 1080], "regions": {}, "source": "legacy_seed"})
    vt.reload_regions()
    try:
        regions = vt._regions()
        assert regions == vt._DEFAULT_REGIONS
        assert target.exists()
        on_disk = json.loads(target.read_text(encoding="utf-8"))
        assert on_disk == vt._DEFAULT_REGIONS
        assert list(tmp_path.glob("*.tmp")) == []
    finally:
        vt.reload_regions()  # do not leak the tmp_path cache to other tests


def test_regions_reads_existing_file_with_base(monkeypatch, tmp_path):
    """Characterization: _base metadata is honored and stripped."""
    target = tmp_path / "vision_regions.json"
    target.write_text(
        json.dumps({"_base": [2560, 1440], "gold": [1, 2, 3, 4]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(vt, "_REGIONS_FILE", target)
    # neutralize the profile layer so this characterizes the legacy _base path
    import core.vision_profiles as _vp
    monkeypatch.setattr(_vp, "load_profile", lambda config_key=None: {
        "config_key": "unknown", "base": [1920, 1080], "regions": {}, "source": "legacy_seed"})
    vt.reload_regions()
    try:
        regions = vt._regions()
        assert regions == {"gold": [1, 2, 3, 4]}
        assert vt._BASE_CACHE == (2560, 1440)
        # bbox scales 2x when the frame is double the calibration base
        assert vt._scale_bbox([10, 10, 20, 20], 5120, 2880) == (20, 20, 40, 40)
    finally:
        vt.reload_regions()
