"""P2 cycle-15 half-wave-2 slice-F regression tests - tft/ deep.

Each test pins a defect the slice-F audit found and fixed. No live OCR,
no tesseract subprocess, no network - pure parse/aggregate/error-path helpers
exercised with fakes and tiny fixtures.

API surface verified before writing (cited file:line):
  1. raw-API-error-leak (HARD RULE):
     - TftPbeCoachEngine.__init__(data_file, debug=) -> tft/tft_pbe_engine.py:336
     - _run_safe(state) acquires self._lock, calls self._run, on Exception
       calls self._write_status(<msg>) -> tft/tft_pbe_engine.py:403-413
     - _write_status writes {"mode":"tft_pbe","action":"ERROR","risk":msg}
       atomically to self._data_file -> tft/tft_pbe_engine.py:496-505
     - the risk field is rendered user-facing by the pbe coach
       (coaches/tft_pbe_coach.py:166 carries "risk"; _tft_data_file ->
       data/tft_pbe_coaching_data.json at coaches/tft_pbe_coach.py:62)
     Pre-fix: _write_status(f"Coach error: {str(exc)[:60]}") leaked the raw
     exception body (which can carry a credit/balance/400/rate-limit string)
     into the panel. Sibling tft_coach_engine._run_safe was already fixed
     (tft/tft_coach_engine.py:684 -> "Coaching paused - retrying").

  2. OCR no-timeout (friction-class-3, stuck-tesseract hang):
     - _OCR_TIMEOUT module constant -> tft/tft_ocr_reader.py
     - _ocr_digits(img, tess) calls tess.image_to_string(processed, config=,
       timeout=_OCR_TIMEOUT) -> tft/tft_ocr_reader.py
     - _ocr_stage_round / _ocr_level likewise.
     Pre-fix: no timeout kwarg - a wedged tesseract.exe blocks the background
     OCR thread (tft/tft_state_reader.py:74 _ocr_loop) for that field forever.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image  # noqa: E402  (third-party, used by the OCR helpers)

from tft import tft_ocr_reader  # noqa: E402
from tft.tft_pbe_engine import TftPbeCoachEngine  # noqa: E402


# A fake raw API-error body that must NEVER reach the user-facing risk field.
_RAW_API_ERROR = (
    "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
    "'message': 'credit balance is too low to access the Anthropic API'}}"
)


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
# 1. raw-API-error-leak (HARD RULE) - tft_pbe_engine._run_safe
# ---------------------------------------------------------------------------

def test_pbe_run_safe_does_not_leak_raw_error_to_risk(tmp_path: Path) -> None:
    data_file = tmp_path / "tft_pbe_coaching_data.json"
    engine = TftPbeCoachEngine(data_file)

    # Force the inner run to raise with a raw API-error body.
    def _boom(_state: dict) -> None:
        raise RuntimeError(_RAW_API_ERROR)

    engine._run = _boom  # type: ignore[assignment]
    engine._run_safe({"stage": 4, "round": 2})

    written = json.loads(data_file.read_text(encoding="utf-8"))
    risk = written.get("risk", "")
    # The friendly degraded message is shown ...
    assert risk == "Coaching paused - retrying"
    # ... and NONE of the raw error body leaks into any user-facing field.
    blob = json.dumps(written).lower()
    assert "credit balance" not in blob
    assert "400" not in blob
    assert "invalid_request_error" not in blob


def test_pbe_run_safe_releases_lock_after_error(tmp_path: Path) -> None:
    # The error path must still release the lock so the next tick can run.
    engine = TftPbeCoachEngine(tmp_path / "tft_pbe_coaching_data.json")

    def _boom(_state: dict) -> None:
        raise RuntimeError(_RAW_API_ERROR)

    engine._run = _boom  # type: ignore[assignment]
    engine._run_safe({"stage": 2, "round": 1})
    # Lock is free -> acquirable without blocking.
    assert engine._lock.acquire(blocking=False) is True
    engine._lock.release()


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
