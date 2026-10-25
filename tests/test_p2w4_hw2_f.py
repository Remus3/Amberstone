"""P2 cycle-15 half-wave-2 slice-F regression tests - tft/ deep.

Each test pins a defect the slice-F audit found and fixed. No live OCR,
no tesseract subprocess, no network - pure parse/aggregate/error-path helpers
exercised with fakes and tiny fixtures.

API surface verified before writing (cited file:line):
  1. retired: the raw-API-error-leak pins on tft/tft_pbe_engine.py
     `_run_safe` went with that engine (RM-292 (b), PBE coach subsystem
     deleted - unreachable; tests/test_rm292b_pbe_coach_retired.py). The
     live twin's degraded message is tft/tft_coach_engine.py `_run_safe`.

  2. OCR no-timeout (friction-class-3, stuck-tesseract hang):
     - _OCR_TIMEOUT module constant -> tft/tft_ocr_reader.py
     - _ocr_digits(img, tess) calls tess.image_to_string(processed, config=,
       timeout=_OCR_TIMEOUT) -> tft/tft_ocr_reader.py
     - _ocr_stage_round / _ocr_level likewise.
     Pre-fix: no timeout kwarg - a wedged tesseract.exe blocks the background
     OCR thread (tft/tft_state_reader.py:74 _ocr_loop) for that field forever.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image  # noqa: E402  (third-party, used by the OCR helpers)

from tft import tft_ocr_reader  # noqa: E402


class _FakeTess:
    """Captures image_to_string kwargs without running tesseract."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def image_to_string(self, image, config="", **kwargs):  # noqa: ANN001
        self.calls.append({"config": config, **kwargs})
        return "42"


def _tiny_img() -> Image.Image:
    """A 6x4 black RGB image - small but real so _preprocess() succeeds."""
    return Image.new("RGB", (6, 4))


# ---------------------------------------------------------------------------
# 2. OCR subprocess timeout - tft_ocr_reader
# ---------------------------------------------------------------------------

def test_ocr_timeout_constant_is_finite_positive() -> None:
    assert isinstance(tft_ocr_reader._OCR_TIMEOUT, (int, float))
    assert tft_ocr_reader._OCR_TIMEOUT > 0


def test_ocr_digits_passes_timeout() -> None:
    tess = _FakeTess()
    tft_ocr_reader._ocr_digits(_tiny_img(), tess)
    assert tess.calls, "image_to_string was not called"
    assert tess.calls[0].get("timeout") == tft_ocr_reader._OCR_TIMEOUT


def test_ocr_stage_round_passes_timeout() -> None:
    tess = _FakeTess()
    # FakeTess returns "42" -> normalises to no valid X-Y; return value is
    # irrelevant, we only assert the timeout kwarg threaded through.
    tft_ocr_reader._ocr_stage_round(_tiny_img(), tess)
    assert tess.calls
    assert tess.calls[0].get("timeout") == tft_ocr_reader._OCR_TIMEOUT


def test_ocr_level_passes_timeout() -> None:
    tess = _FakeTess()
    tft_ocr_reader._ocr_level(_tiny_img(), tess)
    assert tess.calls
    assert tess.calls[0].get("timeout") == tft_ocr_reader._OCR_TIMEOUT
