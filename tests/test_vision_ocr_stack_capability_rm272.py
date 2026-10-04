"""RM-272: a box that loses pytesseract must not degrade OCR SILENTLY.

Acceptance (BACKLOG RM-272): losing the OCR stack produces exactly ONE
WARNING and a false ``ocr_stack_ok`` on /stats; the per-call error counters
and the rings are unchanged (a static machine fact is not a per-call event);
and the OCR hardening tests still SKIP, not pass, on a stack-less box.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import logging
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vision_server import _inference as inf  # noqa: E402
from vision_server import _stats as st  # noqa: E402


@pytest.fixture
def no_ocr_stack(monkeypatch):
    """Make `import pytesseract` raise ImportError; reset the latch."""
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    monkeypatch.setattr(st, "_ocr_stack_error", "")
    yield
    st._ocr_stack_error = ""


def _body() -> bytes:
    return json.dumps({"crops": {"gold": "aGVsbG8="}}).encode()


def _ocr_counters():
    with st._stats_lock:
        return dict(st._stats["ocr"]), len(st._log_ring), len(st._latency_ring)


def test_missing_stack_warns_once_and_flags_capability(no_ocr_stack, caplog):
    before = _ocr_counters()
    with caplog.at_level(logging.WARNING, logger="moon_vision"):
        for _ in range(3):
            assert inf.handle_ocr(_body()) == {"error": "pytesseract/PIL missing"}
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING and "OCR stack" in r.getMessage()]
    assert len(warnings) == 1
    assert st.get_stats()["ocr_stack_ok"] is False
    # Per-call counters and both rings untouched by a static condition.
    assert _ocr_counters() == before


def test_stats_reports_capability_true_when_stack_importable(monkeypatch):
    monkeypatch.setattr(st, "_ocr_stack_error", "")
    present = all(importlib.util.find_spec(m) is not None
                  for m in ("pytesseract", "PIL"))
    assert st.get_stats()["ocr_stack_ok"] is present


def test_hardening_suite_still_skips_on_a_stack_less_box(no_ocr_stack):
    """The naive fix (a _record on the ImportError path) would make the OCR
    error-count assertions pass for the wrong reason; the skip predicate is
    what fences them, so assert it still reports the stack as missing."""
    import tests.test_vision_server_inference_hardening as hard
    assert hard._ocr_stack_missing() == "pytesseract"


def test_success_path_is_unaffected_when_stack_present(monkeypatch):
    if importlib.util.find_spec("pytesseract") is None:
        pytest.skip("CAPABILITY GAP: pytesseract not installed on this runner")
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format="PNG")
    body = json.dumps({"crops": {"g": base64.b64encode(buf.getvalue()).decode()}})
    monkeypatch.setattr(st, "_ocr_stack_error", "")
    out = inf.handle_ocr(body.encode())
    assert out.get("error") != "pytesseract/PIL missing"
    assert st.get_stats()["ocr_stack_ok"] is True
