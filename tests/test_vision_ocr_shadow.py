"""
tests/test_vision_ocr_shadow.py - R101-A shadow OCR routing.

Covers the shadow_fields telemetry mode on
core.vision_routing.read_or_escalate: named fields ALWAYS escalate to
Sonnet (even when their OCR value validates), Sonnet's value wins in the
returned dict (non-consuming - the OCR value is logged only), and one
OCR-vs-Sonnet comparison row per shadow field is appended to
data/ocr_shadow.jsonl (path overridable via RC_OCR_SHADOW_PATH). Logging
is fail-soft: it never raises into the live vision path.

The tests stub core.vision_tesseract in sys.modules so the real (heavy)
OCR module is never imported, and redirect RC_OCR_SHADOW_PATH into
tmp_path so no test ever writes the production shadow log.
"""
from __future__ import annotations

import json
import sys
import types

from core import vision_routing


def _install_fake_tesseract(monkeypatch, ocr_values):
    """Inject a lightweight core.vision_tesseract stub into sys.modules.

    read_or_escalate resolves read_fast_fields via an in-function
    `from core.vision_tesseract import read_fast_fields`, so a sys.modules
    entry is picked up at call time without importing the real module.
    """
    mod = types.ModuleType("core.vision_tesseract")

    def read_fast_fields(img_b64, fields=None, parallel=False):
        return dict(ocr_values)

    mod.read_fast_fields = read_fast_fields
    monkeypatch.setitem(sys.modules, "core.vision_tesseract", mod)
    return mod


def test_shadow_field_forces_escalation_even_when_ocr_validates(monkeypatch, tmp_path):
    # gold OCR value 100 validates cleanly, yet as a shadow field it must
    # still be handed to escalate_fn; level validates and is not shadowed,
    # so it must NOT escalate.
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(tmp_path / "ocr_shadow.jsonl"))
    _install_fake_tesseract(monkeypatch, {"gold": 100, "level": 5})

    captured = {}

    def escalate_fn(img_b64, missing):
        captured["missing"] = list(missing)
        return {"gold": 200}

    result = vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold", "level"],
        escalate_fn=escalate_fn,
        shadow_fields=["gold"],
    )

    assert "gold" in captured["missing"]
    assert "level" not in captured["missing"]
    assert result["level"] == 5


def test_shadow_sonnet_value_wins_in_result(monkeypatch, tmp_path):
    # Non-consuming telemetry: OCR says 100, Sonnet says 200 -> Sonnet wins.
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(tmp_path / "ocr_shadow.jsonl"))
    _install_fake_tesseract(monkeypatch, {"gold": 100})

    def escalate_fn(img_b64, missing):
        return {"gold": 200}

    result = vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold"],
        escalate_fn=escalate_fn,
        shadow_fields=["gold"],
    )

    assert result == {"gold": 200}


def test_shadow_log_writes_jsonl_rows(monkeypatch, tmp_path):
    shadow_path = tmp_path / "ocr_shadow.jsonl"
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(shadow_path))
    # gold: OCR == Sonnet (match True); level: OCR != Sonnet (match False);
    # hp: OCR absent -> ocr_val None (match False).
    _install_fake_tesseract(monkeypatch, {"gold": 100, "level": 5})

    def escalate_fn(img_b64, missing):
        return {"gold": 100, "level": 7, "hp": 500}

    vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold", "level", "hp"],
        escalate_fn=escalate_fn,
        shadow_fields=["gold", "level", "hp"],
    )

    assert shadow_path.exists()
    rows = {}
    for ln in shadow_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        obj = json.loads(ln)
        assert set(obj.keys()) == {"ts", "field", "ocr_val", "sonnet_val", "match"}
        rows[obj["field"]] = obj

    assert len(rows) == 3
    assert rows["gold"]["ocr_val"] == 100
    assert rows["gold"]["sonnet_val"] == 100
    assert rows["gold"]["match"] is True
    assert rows["level"]["ocr_val"] == 5
    assert rows["level"]["sonnet_val"] == 7
    assert rows["level"]["match"] is False
    assert rows["hp"]["ocr_val"] is None
    assert rows["hp"]["sonnet_val"] == 500
    assert rows["hp"]["match"] is False


def test_shadow_logging_is_fail_soft(monkeypatch, tmp_path):
    # Parent path is a regular file, so mkdir/open inside _log_ocr_shadow
    # raises; read_or_escalate must swallow it and still return the merged
    # dict.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(blocker / "ocr_shadow.jsonl"))
    _install_fake_tesseract(monkeypatch, {"gold": 100})

    def escalate_fn(img_b64, missing):
        return {"gold": 200}

    result = vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold"],
        escalate_fn=escalate_fn,
        shadow_fields=["gold"],
    )

    assert result == {"gold": 200}


def test_log_ocr_shadow_direct_never_raises(monkeypatch, tmp_path):
    # Direct-call fail-soft guard on the helper itself.
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(blocker / "ocr_shadow.jsonl"))
    assert vision_routing._log_ocr_shadow({"gold": 1}, {"gold": 2}, {"gold"}) is None


def test_non_shadow_behavior_unchanged(monkeypatch):
    # With no shadow_fields, an OCR-validated field returns from OCR and
    # escalate_fn is never called - byte-compatible with prior behavior.
    _install_fake_tesseract(monkeypatch, {"gold": 100, "level": 5})

    calls = {"n": 0}

    def escalate_fn(img_b64, missing):
        calls["n"] += 1
        return {}

    result = vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold", "level"],
        escalate_fn=escalate_fn,
    )

    assert calls["n"] == 0
    assert result == {"gold": 100, "level": 5}


def test_reader_shadow_fields_default_is_empty():
    from modes.shared_vision import GameVisionReader
    assert GameVisionReader.SHADOW_FIELDS == []


def test_read_tiered_passes_shadow_fields_through(monkeypatch):
    import core.vision_routing as vr
    import modes.shared_vision as sv

    captured = {}

    def fake_read_or_escalate(img_b64, fields, *, escalate_fn=None,
                              validators=None, shadow_fields=None):
        captured["shadow_fields"] = shadow_fields
        captured["fields"] = list(fields)
        return {"gold": 1}

    monkeypatch.setattr(vr, "read_or_escalate", fake_read_or_escalate)
    monkeypatch.setattr(sv, "_capture_screen", lambda: "dummyb64")

    reader = sv.GameVisionReader.__new__(sv.GameVisionReader)
    reader.TIERED_FIELDS = ["gold", "level"]
    reader.SHADOW_FIELDS = ["gold"]

    out = reader.read_tiered()

    assert captured["shadow_fields"] == ["gold"]
    assert captured["fields"] == ["gold", "level"]
    assert out == {"gold": 1}
