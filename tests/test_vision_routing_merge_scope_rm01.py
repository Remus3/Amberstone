"""
tests/test_vision_routing_merge_scope_rm01.py - RM-01 upstream half.

`core.vision_routing.read_or_escalate` asks the Sonnet escalation for a
specific list of fields (`escalate_fn(img_b64, missing)`) and then merged
back EVERY key the model returned, including keys nobody asked for and
keys OCR had already resolved and validated. That unscoped merge is the
producer half of the RM-01 vision-fusion defect (the downstream
plausibility gate in core/vision_fusion.py shipped 2026-07-25).

These tests pin the new merge-scope seam:
  * default OFF - the served coach dict is byte-identical to today, so no
    live consumer can regress (measured: 104 of 233 real fusion-shadow
    records carry `is_augment_select`, which
    modes/shared_vision.GameVisionReader._postprocess aliases into the
    consumed `augment_select`; B-01b re-homed that key into the ARAM +
    Arena TIERED_FIELDS so strict no longer drops it);
  * RC_VISION_MERGE_STRICT=1 - the merge is filtered to the exact field
    list handed to escalate_fn;
  * the drop telemetry is written in both modes, to its own JSONL lane
    (data/vision_merge_shadow.jsonl) so it never pollutes the per-field
    ocr_shadow.jsonl schema that tools/ocr_shadow_report.py aggregates.

The tests stub core.vision_tesseract in sys.modules (same idiom as
tests/test_vision_ocr_shadow.py) so the real OCR module is never imported,
and redirect RC_VISION_MERGE_SHADOW_PATH into tmp_path so no test ever
writes the production log.
"""
from __future__ import annotations

import json
import sys
import types

from core import vision_routing


def _install_fake_tesseract(monkeypatch, ocr_values):
    """Inject a lightweight core.vision_tesseract stub into sys.modules."""
    mod = types.ModuleType("core.vision_tesseract")

    def read_fast_fields(img_b64, fields=None, parallel=False):
        return dict(ocr_values)

    mod.read_fast_fields = read_fast_fields
    monkeypatch.setitem(sys.modules, "core.vision_tesseract", mod)
    return mod


def _redirect_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(tmp_path / "ocr_shadow.jsonl"))
    monkeypatch.setenv(
        "RC_VISION_MERGE_SHADOW_PATH", str(tmp_path / "vision_merge_shadow.jsonl")
    )


def _read_rows(path):
    if not path.exists():
        return []
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


# -- strict mode: the actual RM-01 fix ---------------------------------------

def test_strict_merge_drops_unrequested_keys(monkeypatch, tmp_path):
    """The model answers with keys nobody asked for; strict mode drops them."""
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.setenv("RC_VISION_MERGE_STRICT", "1")
    _install_fake_tesseract(monkeypatch, {})

    def escalate_fn(img_b64, missing):
        # `gold` was asked for; the rest is the TFT-shaped payload the live
        # relay returns for every mode (reference_vision_relay_tft_prompt_all_modes).
        return {
            "gold": 913,
            "board_units": ["Aatrox 2-star"],
            "shop_units": ["Akali"],
            "traits_active": ["Bastion 2"],
            "is_augment_select": False,
            "stage_round": "3-2",
        }

    result = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )

    assert result == {"gold": 913}


def test_strict_merge_does_not_clobber_a_validated_ocr_field(monkeypatch, tmp_path):
    """OCR resolved `level`; it is not in `missing`, so Sonnet cannot overwrite it.

    modes/shared_vision.read_tiered documents exactly this contract:
    "OCR wins for numeric fields it validates; Sonnet fills the rest".
    """
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.setenv("RC_VISION_MERGE_STRICT", "1")
    _install_fake_tesseract(monkeypatch, {"level": 11})

    def escalate_fn(img_b64, missing):
        assert "level" not in missing
        return {"gold": 913, "level": 1}

    result = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold", "level"], escalate_fn=escalate_fn
    )

    assert result["level"] == 11
    assert result["gold"] == 913


def test_strict_merge_keeps_shadow_fields(monkeypatch, tmp_path):
    """Shadow fields are forced into `missing`, so strict mode must keep them."""
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.setenv("RC_VISION_MERGE_STRICT", "1")
    _install_fake_tesseract(monkeypatch, {"gold": 100})

    def escalate_fn(img_b64, missing):
        return {"gold": 200, "board_units": []}

    result = vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold"],
        escalate_fn=escalate_fn,
        shadow_fields=["gold"],
    )

    assert result == {"gold": 200}


# -- default OFF: served dicts stay byte-identical ---------------------------

def test_default_off_preserves_todays_unscoped_merge(monkeypatch, tmp_path):
    """No env flag set -> the returned dict is exactly what it was before."""
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.delenv("RC_VISION_MERGE_STRICT", raising=False)
    _install_fake_tesseract(monkeypatch, {})

    payload = {"gold": 913, "board_units": ["Aatrox"], "is_augment_select": True}

    def escalate_fn(img_b64, missing):
        return dict(payload)

    result = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )

    assert result == payload


def test_default_off_still_lets_sonnet_win_over_ocr(monkeypatch, tmp_path):
    """Characterization: the pre-fix clobber survives while the flag is OFF."""
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.delenv("RC_VISION_MERGE_STRICT", raising=False)
    _install_fake_tesseract(monkeypatch, {"level": 11})

    def escalate_fn(img_b64, missing):
        return {"gold": 913, "level": 1}

    result = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold", "level"], escalate_fn=escalate_fn
    )

    assert result["level"] == 1


def test_is_augment_select_only_survives_strict_when_requested(monkeypatch, tmp_path):
    """B-01b: the OLD invariant was "is_augment_select is in NO TIERED_FIELDS".

    That was the bug, not the contract. `is_augment_select` has a live consumer
    (modes/shared_vision.GameVisionReader._postprocess aliases it into the
    consumed `augment_select` AFTER read_or_escalate returns), so it has been
    re-homed into the ARAM + Arena TIERED_FIELDS. The generic router rule is
    unchanged and is what this test now pins: strict mode keeps the key when it
    is in the requested field list and drops it when it is not. The
    coach-registration half is pinned in
    tests/test_vision_merge_augment_rehome_b01b.py.
    """
    _redirect_logs(monkeypatch, tmp_path)
    _install_fake_tesseract(monkeypatch, {})

    def escalate_fn(img_b64, missing):
        return {"gold": 913, "is_augment_select": True}

    # OFF path unchanged: everything the model answers with is merged.
    monkeypatch.delenv("RC_VISION_MERGE_STRICT", raising=False)
    lenient = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )
    assert lenient.get("is_augment_select") is True

    monkeypatch.setenv("RC_VISION_MERGE_STRICT", "1")
    # Not requested -> still dropped (the router rule itself did not change).
    strict_unrequested = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )
    assert "is_augment_select" not in strict_unrequested

    # Requested (what the re-homed coaches now do) -> kept.
    strict_requested = vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold", "is_augment_select"],
        escalate_fn=escalate_fn,
    )
    assert strict_requested.get("is_augment_select") is True


# -- drop telemetry ----------------------------------------------------------

def test_drop_shadow_row_written_when_flag_off(monkeypatch, tmp_path):
    """Shadow-compare: the drop set is logged even though nothing is dropped."""
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.delenv("RC_VISION_MERGE_STRICT", raising=False)
    _install_fake_tesseract(monkeypatch, {})

    def escalate_fn(img_b64, missing):
        return {"gold": 913, "board_units": [], "stage_round": "3-2"}

    vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )

    rows = _read_rows(tmp_path / "vision_merge_shadow.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"ts", "strict", "requested", "returned", "dropped"}
    assert row["strict"] is False
    assert row["requested"] == ["gold"]
    assert sorted(row["dropped"]) == ["board_units", "stage_round"]


def test_drop_shadow_row_written_when_flag_on(monkeypatch, tmp_path):
    _redirect_logs(monkeypatch, tmp_path)
    monkeypatch.setenv("RC_VISION_MERGE_STRICT", "1")
    _install_fake_tesseract(monkeypatch, {})

    def escalate_fn(img_b64, missing):
        return {"gold": 913, "board_units": []}

    vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )

    rows = _read_rows(tmp_path / "vision_merge_shadow.jsonl")
    assert len(rows) == 1
    assert rows[0]["strict"] is True
    assert sorted(rows[0]["dropped"]) == ["board_units"]


def test_no_drop_row_when_model_answers_exactly(monkeypatch, tmp_path):
    _redirect_logs(monkeypatch, tmp_path)
    _install_fake_tesseract(monkeypatch, {})

    def escalate_fn(img_b64, missing):
        return {"gold": 913}

    vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )

    assert _read_rows(tmp_path / "vision_merge_shadow.jsonl") == []


def test_drop_logging_is_fail_soft(monkeypatch, tmp_path):
    """A broken drop-log path must not raise into the live vision path."""
    _redirect_logs(monkeypatch, tmp_path)
    _install_fake_tesseract(monkeypatch, {})

    def boom(*_a, **_kw):
        raise OSError("disk on fire")

    monkeypatch.setattr(vision_routing, "_merge_shadow_path", boom)

    def escalate_fn(img_b64, missing):
        return {"gold": 913, "board_units": []}

    result = vision_routing.read_or_escalate(
        "dummyb64", fields=["gold"], escalate_fn=escalate_fn
    )

    assert result["gold"] == 913


def test_ocr_shadow_log_is_not_polluted_by_drop_rows(monkeypatch, tmp_path):
    """The drop lane must stay out of ocr_shadow.jsonl (report tool schema)."""
    ocr_path = tmp_path / "ocr_shadow.jsonl"
    _redirect_logs(monkeypatch, tmp_path)
    _install_fake_tesseract(monkeypatch, {"gold": 100})

    def escalate_fn(img_b64, missing):
        return {"gold": 200, "board_units": []}

    vision_routing.read_or_escalate(
        "dummyb64",
        fields=["gold"],
        escalate_fn=escalate_fn,
        shadow_fields=["gold"],
    )

    for obj in _read_rows(ocr_path):
        assert set(obj) == {"ts", "field", "ocr_val", "sonnet_val", "match"}
