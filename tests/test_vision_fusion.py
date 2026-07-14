# arch: tests for core.vision_fusion confidence-weighted partial-read fusion | section=tests | frozen=no
"""Tests for core.vision_fusion - R126 Slice B partial-read fusion layer.

Spec: docs/NO_LLM_PRECOMPUTE_PLAN.md:159-163 (confidence-weighted fusion /
partial-read layer) - fuse Live Client API (high trust) + CV reads
(confidence-weighted) into one best-effort state; always emit something;
never raise. Precedent: core/district_fusion.py (API-ground-truth-over-CV,
fail-soft never-raises). CV reads carry no per-field score today
(core/vision_routing.read_or_escalate returns a plain {field: value} dict),
so CV confidence here is a heuristic default unless the caller passes
measured scores via cv_confidence.

BUILD-SUBSTRATE only (R126 Slice B): no coach wire, ENGINE-IMPACT NONE.
"""
import pathlib

import core.vision_fusion as vf
from core.vision_fusion import fuse_reads, fuse_with_atlas

_MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[1] / "core" / "vision_fusion.py"
)


def test_constants():
    assert vf.LIVECLIENT_CONF == 1.0
    assert vf.STALE_LIVECLIENT_CONF == 0.5
    assert vf.CV_DEFAULT_CONF == 0.7
    assert vf.CV_OVERRIDE_STALE_THRESHOLD == 0.6


def test_lc_exact_when_fresh_non_gap():
    res = fuse_reads({"gold": 3200}, {})
    entry = res["gold"]
    assert entry["source"] == "liveclient"
    assert entry["value"] == 3200
    assert entry["confidence"] == vf.LIVECLIENT_CONF
    assert "lc_exact:gold" in res["_notes"]


def test_gap_field_cv_authoritative():
    res = fuse_reads(
        {}, {"augment_choices": ["a", "b"]},
        api_gap_fields=frozenset({"augment_choices"}),
    )
    entry = res["augment_choices"]
    assert entry["source"] == "cv"
    assert entry["value"] == ["a", "b"]
    assert entry["confidence"] == vf.CV_DEFAULT_CONF  # 0.7 heuristic default
    assert "cv_gap:augment_choices" in res["_notes"]


def test_gap_field_ignores_liveclient_when_in_both():
    # A structural API gap: even a present LC value is ignored; CV wins.
    res = fuse_reads(
        {"augment_choices": "LC_JUNK"},
        {"augment_choices": "CV_TRUTH"},
        api_gap_fields=frozenset({"augment_choices"}),
    )
    entry = res["augment_choices"]
    assert entry["source"] == "cv"
    assert entry["value"] == "CV_TRUTH"
    assert "cv_gap:augment_choices" in res["_notes"]


def test_stale_lc_cv_override_at_default_conf():
    # Default CV conf 0.7 >= threshold 0.6 -> CV overrides the stale LC read.
    res = fuse_reads({"cs": 100}, {"cs": 142}, live_stale=True)
    entry = res["cs"]
    assert entry["source"] == "cv"
    assert entry["value"] == 142
    assert entry["confidence"] == vf.CV_DEFAULT_CONF
    assert "cv_override_stale:cs" in res["_notes"]


def test_stale_lc_no_cv_falls_to_stale_lc():
    res = fuse_reads({"cs": 100}, {}, live_stale=True)
    entry = res["cs"]
    assert entry["source"] == "liveclient"
    assert entry["value"] == 100
    assert entry["confidence"] == vf.STALE_LIVECLIENT_CONF
    assert "lc_stale:cs" in res["_notes"]


def test_cv_only_non_gap_fallback():
    res = fuse_reads({}, {"ward_count": 3})
    entry = res["ward_count"]
    assert entry["source"] == "cv"
    assert entry["value"] == 3
    assert entry["confidence"] == vf.CV_DEFAULT_CONF
    assert "cv_fallback:ward_count" in res["_notes"]


def test_cv_confidence_clamps_high_to_one():
    res = fuse_reads({}, {"hp": 850}, cv_confidence={"hp": 1.5})
    assert res["hp"]["confidence"] == 1.0
    assert res["hp"]["source"] == "cv"


def test_low_cv_confidence_keeps_stale_lc():
    # 0.4 < CV_OVERRIDE_STALE_THRESHOLD (0.6): the stale LC read must win.
    res = fuse_reads(
        {"gold": 500}, {"gold": 9999},
        live_stale=True, cv_confidence={"gold": 0.4},
    )
    entry = res["gold"]
    assert entry["source"] == "liveclient"
    assert entry["value"] == 500
    assert entry["confidence"] == vf.STALE_LIVECLIENT_CONF
    assert "lc_stale:gold" in res["_notes"]


def test_cv_confidence_clamps_negative_to_zero():
    res = fuse_reads({}, {"hp": 10}, cv_confidence={"hp": -3.0})
    assert res["hp"]["confidence"] == 0.0


def test_empty_inputs_returns_notes_dict():
    res = fuse_reads({}, {})
    assert isinstance(res, dict)
    assert res["_notes"] == []


def test_none_inputs_do_not_raise():
    # Malformed inputs must never raise (fail-soft contract).
    res = fuse_reads(None, None)
    assert isinstance(res, dict)
    assert "_notes" in res


def test_fuse_with_atlas_failsoft_no_atlas():
    # core.vision_region_atlas does not exist yet (Slice B stands alone): the
    # lazy import must fail-soft to frozenset() so a plain LC field reads
    # lc_exact rather than raising.
    res = fuse_with_atlas({"level": 6}, {})
    entry = res["level"]
    assert entry["source"] == "liveclient"
    assert entry["confidence"] == vf.LIVECLIENT_CONF
    assert "lc_exact:level" in res["_notes"]


def test_module_source_is_ascii():
    raw = _MODULE_PATH.read_bytes()
    assert all(b < 128 for b in raw), "non-ASCII byte in core/vision_fusion.py"
