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


# -- RM-01 Lane E B-01: CV plausibility gate on the stale-override branch -----
# Triaged from data/fusion_shadow.jsonl (230 real-game records, 2026-07-18 ->
# 2026-07-24): ALL 41 cv_override_stale decisions the fusion layer ever made
# were the field `gold` with a CV value of literally 1, beating a known-good
# Live Client gold of 87 / 913 / 6423 / 8703 / 12761 / 30410. The override
# fired purely because live_stale was True and the UNCONDITIONAL heuristic
# CV_DEFAULT_CONF (0.7) clears CV_OVERRIDE_STALE_THRESHOLD (0.6) - there was
# no plausibility check anywhere in fuse_reads. Doctrine: a wrong precompute
# is worse than a Haiku call, so an implausible CV read must never win.


def test_plausibility_constants():
    assert vf.CV_ORDER_OF_MAGNITUDE_FACTOR == 10.0
    assert vf.CV_DIVERGENCE_ABS_FLOOR == 50.0
    # gold is deliberately NOT monotonic - currentGold drops on every purchase.
    assert "gold" not in vf.MONOTONIC_NONDECREASING_FIELDS
    assert "level" in vf.MONOTONIC_NONDECREASING_FIELDS
    assert "cs" in vf.MONOTONIC_NONDECREASING_FIELDS
    assert vf.PLAUSIBLE_RANGES["level"] == (1, 18)


def test_shadow_ledger_repro_gold_1_never_beats_stale_liveclient():
    # Verbatim shape of data/fusion_shadow.jsonl record 0 and record 229.
    res = fuse_reads(
        {"gold": 8703, "level": 7, "cs": 40, "kda": "14/0/0"},
        {"gold": 1},
        live_stale=True,
    )
    entry = res["gold"]
    assert entry["source"] == "liveclient"
    assert entry["value"] == 8703
    assert entry["confidence"] == vf.STALE_LIVECLIENT_CONF
    assert "cv_implausible:gold" in res["_notes"]
    assert "cv_override_stale:gold" not in res["_notes"]


def test_order_of_magnitude_divergence_blocks_cv_override():
    for lc_gold in (87, 913, 6423, 12761, 30410):
        res = fuse_reads({"gold": lc_gold}, {"gold": 1}, live_stale=True)
        assert res["gold"]["value"] == lc_gold, lc_gold
        assert res["gold"]["source"] == "liveclient", lc_gold


def test_monotonic_field_cv_below_liveclient_blocked():
    # Level only ever increases in a game; a CV level below the LC anchor is
    # a mis-read. 3 vs 12 is inside the order-of-magnitude factor, so ONLY the
    # monotonic rule can catch it.
    res = fuse_reads({"level": 12}, {"level": 3}, live_stale=True)
    assert res["level"]["source"] == "liveclient"
    assert res["level"]["value"] == 12
    assert "cv_implausible:level" in res["_notes"]


def test_out_of_range_cv_blocked():
    # 47 is inside the divergence factor of 12 and is monotonic-increasing,
    # so ONLY the hard-range rule (level 1..18) can catch it.
    res = fuse_reads({"level": 12}, {"level": 47}, live_stale=True)
    assert res["level"]["source"] == "liveclient"
    assert res["level"]["value"] == 12
    assert "cv_implausible:level" in res["_notes"]


def test_type_mismatch_cv_blocked():
    # A numeric LC anchor with a non-numeric CV read is a parse miss, not a
    # state change (the ledger carries one cv gold read of the string '250').
    res = fuse_reads({"gold": 500}, {"gold": "500"}, live_stale=True)
    assert res["gold"]["source"] == "liveclient"
    assert res["gold"]["value"] == 500
    assert "cv_implausible:gold" in res["_notes"]


def test_plausible_cv_still_overrides_stale_lc():
    # The gate must not be over-broad: a believable CV read still wins.
    res = fuse_reads({"cs": 100}, {"cs": 142}, live_stale=True)
    assert res["cs"]["source"] == "cv"
    assert res["cs"]["value"] == 142
    assert "cv_override_stale:cs" in res["_notes"]
    assert "cv_implausible:cs" not in res["_notes"]


def test_small_absolute_values_do_not_trip_divergence():
    # Below CV_DIVERGENCE_ABS_FLOOR the ratio is meaningless noise: an early
    # game gold of 3 -> 40 is a real state change, not a mis-read.
    res = fuse_reads({"gold": 3}, {"gold": 40}, live_stale=True)
    assert res["gold"]["source"] == "cv"
    assert res["gold"]["value"] == 40


def test_gate_only_touches_the_contested_stale_branch():
    # Fresh LC, api_gap and cv-only fallback paths are untouched by the gate:
    # an implausible CV value still flows exactly as it did before.
    fresh = fuse_reads({"gold": 8703}, {"gold": 1})
    assert fresh["gold"]["source"] == "liveclient"
    assert "lc_exact:gold" in fresh["_notes"]

    gap = fuse_reads(
        {"gold": 8703}, {"gold": 1}, api_gap_fields=frozenset({"gold"}),
    )
    assert gap["gold"]["source"] == "cv"
    assert gap["gold"]["value"] == 1
    assert "cv_gap:gold" in gap["_notes"]

    only_cv = fuse_reads({}, {"gold": 1}, live_stale=True)
    assert only_cv["gold"]["source"] == "cv"
    assert only_cv["gold"]["value"] == 1
    assert "cv_fallback:gold" in only_cv["_notes"]


def test_is_plausible_cv_never_raises_and_defaults_open():
    # Fail-soft: anything the gate cannot judge is treated as plausible so it
    # can never silently swallow a field.
    assert vf.is_plausible_cv("gold", 500, 480) is True
    assert vf.is_plausible_cv("unknown_field", object(), object()) is True
    assert vf.is_plausible_cv("gold", None, None) is True
    assert vf.is_plausible_cv("kda", "5/2/9", "4/2/9") is True
    assert vf.is_plausible_cv("gold", 100, None) is True


def test_bools_are_not_treated_as_numerics():
    # bool is a subclass of int: augment_select True/False must not be run
    # through the numeric divergence rules.
    res = fuse_reads(
        {"augment_select": False}, {"augment_select": True}, live_stale=True,
    )
    assert res["augment_select"]["source"] == "cv"
    assert res["augment_select"]["value"] is True


def test_gate_failure_does_not_break_never_raises_contract(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(vf, "is_plausible_cv", boom)
    res = fuse_reads({"gold": 500}, {"gold": 1}, live_stale=True)
    assert isinstance(res, dict)
    assert "_notes" in res
