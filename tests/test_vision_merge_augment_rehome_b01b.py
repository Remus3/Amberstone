"""tests/test_vision_merge_augment_rehome_b01b.py - item B-01b.

`is_augment_select` used to live NOWHERE in any coach's TIERED_FIELDS even
though it has a live consumer: `modes.shared_vision.GameVisionReader.
_postprocess` aliases it into the consumed `augment_select` AFTER
`core.vision_routing.read_or_escalate` returns. That single unrequested-key
dependency was the SOLE reason RC_VISION_MERGE_STRICT shipped DEFAULT-OFF.

B-01b re-homes the field into the two coaches whose modes actually have
augments (ARAM Mayhem, Arena) and MEASURES what a strict merge does to the
`cv_reads` payload that `modes.shared_vision._log_fusion_shadow` records.

Three groups:
  1. registration - who declares the field and who deliberately does not;
  2. end-to-end - strict mode no longer breaks the augment-select alias, and
     the OFF path is untouched;
  3. the shadow-corpus measurement - which keys strict removes from the
     fusion-shadow payload, and the invariant that nothing analytically
     load-bearing (the liveclient-comparable numerics, the disagreement
     observations) is ever among them.

No Anthropic key, network call, or screen capture: the coach constants are
introspected at class level and the router is driven with a stubbed
core.vision_tesseract (same idiom as tests/test_vision_routing_merge_scope_rm01.py).
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from coaches.aram_coach import Coach as ARAMCoach
from coaches.arena_coach import ArenaVisionReader
from coaches.brawl_coach import BrawlVisionReader
from core import vision_routing
from modes.shared_vision import GameVisionReader

FIELD = "is_augment_select"

# The live relay answers EVERY mode with the TFT prompt
# (vision_server/_inference.py:31-38), so an ARAM/Arena tick gets this shape.
_RELAY_PAYLOAD = {
    "traits_active": ["N.O.V.A. 3"],
    "board_units": ["Aatrox 2-star"],
    "bench_units": ["Kindred"],
    "shop_units": ["Akali"],
    "items_equipped": {"Aatrox": ["Warmog"]},
    "items_on_bench": [],
    "augments": ["Crest"],
    "augment_choices": ["Crest", "Pandoras", "Portable Forge"],
    "gold": 913,
    "hp": 64,
    "level": 11,
    "stage_round": "3-2",
    FIELD: True,
    "last_round_result": "win",
    "round_damage": 12,
}

# Everything in the relay payload that no ARAM/Arena code path reads. These are
# the keys a strict merge removes from the fusion-shadow cv_reads payload.
_TFT_ONLY = {
    "traits_active", "board_units", "bench_units", "shop_units",
    "items_equipped", "items_on_bench", "stage_round", "hp",
    "last_round_result", "round_damage",
}


def _install_fake_tesseract(monkeypatch, ocr_values=None):
    mod = types.ModuleType("core.vision_tesseract")

    def read_fast_fields(img_b64, fields=None, parallel=False):
        return dict(ocr_values or {})

    mod.read_fast_fields = read_fast_fields
    monkeypatch.setitem(sys.modules, "core.vision_tesseract", mod)


def _redirect_logs(monkeypatch, tmp_path):
    monkeypatch.setenv("RC_OCR_SHADOW_PATH", str(tmp_path / "ocr_shadow.jsonl"))
    monkeypatch.setenv(
        "RC_VISION_MERGE_SHADOW_PATH", str(tmp_path / "vision_merge_shadow.jsonl")
    )


def _read_through(monkeypatch, tmp_path, fields, strict):
    """Drive the real router + the real _postprocess for one tick."""
    _redirect_logs(monkeypatch, tmp_path)
    _install_fake_tesseract(monkeypatch)
    if strict:
        monkeypatch.setenv("RC_VISION_MERGE_STRICT", "1")
    else:
        monkeypatch.delenv("RC_VISION_MERGE_STRICT", raising=False)

    def escalate_fn(_img, _missing):
        return dict(_RELAY_PAYLOAD)

    raw = vision_routing.read_or_escalate(
        "dummyb64", fields=list(fields), escalate_fn=escalate_fn
    )
    reader = GameVisionReader.__new__(GameVisionReader)
    return reader._postprocess(raw)


# -- 1. registration ---------------------------------------------------------

def test_aram_declares_is_augment_select():
    assert FIELD in ARAMCoach._ARAM_TIERED_FIELDS


def test_arena_declares_is_augment_select():
    assert FIELD in ArenaVisionReader.TIERED_FIELDS


def test_declaring_coaches_carry_a_validator():
    assert FIELD in ARAMCoach._ARAM_TIERED_VALIDATORS
    assert FIELD in ArenaVisionReader.TIERED_VALIDATORS
    for validator in (ARAMCoach._ARAM_TIERED_VALIDATORS[FIELD],
                      ArenaVisionReader.TIERED_VALIDATORS[FIELD]):
        assert validator(True)
        assert validator(False)
        assert not validator("yes")
        assert not validator(None)


def test_brawl_deliberately_does_not_declare_it():
    """Nexus Blitz / URF have no augments and no augment consumer.

    coaches/brawl_coach.py contains zero occurrences of "augment": neither
    _NB_PROMPT nor _URF_PROMPT asks for one and no brawl code path reads
    `augment_select`. Declaring the field there would request a key the mode
    can never use.
    """
    assert FIELD not in BrawlVisionReader._NB_TIERED_FIELDS
    assert FIELD not in BrawlVisionReader._URF_TIERED_FIELDS
    src = (Path(__file__).resolve().parent.parent
           / "coaches" / "brawl_coach.py").read_text(encoding="utf-8")
    assert "augment" not in src


def test_declaring_it_does_not_force_a_new_escalation():
    """No cost regression: both declaring coaches already always escalate.

    SHADOW_FIELDS entries are force-added to `missing` by read_or_escalate, so
    `missing` was already non-empty on every tick for ARAM and Arena. Adding
    an OCR-impossible field cannot turn a full-OCR-hit tick into a Sonnet call
    because there are no full-OCR-hit ticks on these two modes.
    """
    assert ARAMCoach._ARAM_SHADOW_FIELDS
    assert ArenaVisionReader.SHADOW_FIELDS
    assert set(ARAMCoach._ARAM_SHADOW_FIELDS) <= set(ARAMCoach._ARAM_TIERED_FIELDS)
    assert set(ArenaVisionReader.SHADOW_FIELDS) <= set(ArenaVisionReader.TIERED_FIELDS)


# -- 2. end-to-end: the alias survives strict mode ---------------------------

@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(ARAMCoach._ARAM_TIERED_FIELDS, id="aram"),
        pytest.param(ArenaVisionReader.TIERED_FIELDS, id="arena"),
    ],
)
def test_strict_merge_keeps_the_augment_select_alias(monkeypatch, tmp_path, fields):
    out = _read_through(monkeypatch, tmp_path, fields, strict=True)
    assert out[FIELD] is True
    assert out["augment_select"] is True


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param(ARAMCoach._ARAM_TIERED_FIELDS, id="aram"),
        pytest.param(ArenaVisionReader.TIERED_FIELDS, id="arena"),
    ],
)
def test_off_path_still_produces_the_alias(monkeypatch, tmp_path, fields):
    """Keep the OFF-path assertion intact - the default is unchanged."""
    out = _read_through(monkeypatch, tmp_path, fields, strict=False)
    assert out[FIELD] is True
    assert out["augment_select"] is True


def test_pre_rehome_shape_would_have_lost_the_alias(monkeypatch, tmp_path):
    """Regression fence: this is what strict did BEFORE B-01b.

    Simulating the pre-fix TIERED_FIELDS (the same list minus the re-homed
    field) reproduces the loss the flag was held back for, so the test proves
    the re-home is what fixes it and not some incidental router change.
    """
    pre = [f for f in ARAMCoach._ARAM_TIERED_FIELDS if f != FIELD]
    out = _read_through(monkeypatch, tmp_path, pre, strict=True)
    assert FIELD not in out
    assert "augment_select" not in out


# -- 3. the measured shadow-corpus delta -------------------------------------

def test_strict_narrows_the_fusion_shadow_payload_by_exactly_the_tft_keys(
        monkeypatch, tmp_path):
    """MEASURED answer: yes, strict narrows the cv_reads payload.

    `modes.shared_vision.read_tiered` hands its post-_postprocess dict to
    `_log_fusion_shadow`, which records it verbatim as `cv_reads`. A strict
    merge therefore shrinks that payload by exactly the keys the coach never
    requested. On the ARAM field list against the live relay payload that is
    the 10 TFT-only keys - and nothing else.
    """
    lenient = _read_through(
        monkeypatch, tmp_path, ARAMCoach._ARAM_TIERED_FIELDS, strict=False)
    strict = _read_through(
        monkeypatch, tmp_path, ARAMCoach._ARAM_TIERED_FIELDS, strict=True)

    dropped = set(lenient) - set(strict)
    assert dropped == _TFT_ONLY
    assert len(dropped) == 10
    # Every key the ARAM coach actually reads survives.
    for consumed in ("my_tower_hp", "enemy_tower_hp", "wave_pct", "hp_packs",
                     "augments", "augment_select", "augment_choices"):
        assert consumed not in dropped


def test_strict_never_drops_a_liveclient_comparable_numeric(monkeypatch, tmp_path):
    """The analytic core of the fusion shadow lane is untouched.

    `_log_fusion_shadow` only ever compares gold / level / cs / kda (the four
    fields `modes.shared_vision._liveclient_flat_fields` emits), and all four
    are in both declaring coaches' TIERED_FIELDS AND SHADOW_FIELDS, so they are
    force-added to `missing` and can never be filtered out. Strict mode
    therefore cannot cost the corpus a single disagreement observation.
    """
    comparable = {"gold", "level", "cs", "kda"}
    for fields in (ARAMCoach._ARAM_TIERED_FIELDS, ArenaVisionReader.TIERED_FIELDS):
        assert comparable <= set(fields)
        strict = _read_through(monkeypatch, tmp_path, fields, strict=True)
        # The stub payload carries gold + level; both must survive.
        assert strict["gold"] == 913
        assert strict["level"] == 11


def test_real_fusion_shadow_corpus_invariants():
    """Replay the production corpus: no load-bearing field is ever narrowed.

    Skips when data/fusion_shadow.jsonl is absent (clean checkout / CI). The
    assertions are invariants, not counts, so a growing log cannot make this
    brittle. Counts measured 2026-07-25 on 233 records: 104 records (44.6%)
    are narrowed, 700 of 1428 cv_reads keys (49.0%) drop, and 0 of the 138
    liveclient-comparable keys and 0 disagreement observations are lost.
    """
    path = (Path(__file__).resolve().parent.parent
            / "data" / "fusion_shadow.jsonl")
    if not path.exists():
        pytest.skip("data/fusion_shadow.jsonl not present")
    # RM-155: mere EXISTENCE is not enough. The invariants below need a real
    # corpus - `narrowed > 0` cannot hold on a handful of records, and a tiny
    # corpus is the signature of pollution (a test that wrote the production
    # path) rather than of production traffic. Skip honestly instead of
    # failing, so the suite stays idempotent in a fresh tree.
    _MIN_CORPUS_RECORDS = 50
    if sum(1 for ln in path.read_text(encoding="utf-8", errors="replace")
           .splitlines() if ln.strip()) < _MIN_CORPUS_RECORDS:
        pytest.skip(
            f"data/fusion_shadow.jsonl has fewer than {_MIN_CORPUS_RECORDS} "
            "records - too small to assert corpus invariants"
        )

    tiered = [
        set(ARAMCoach._ARAM_TIERED_FIELDS),
        set(ArenaVisionReader.TIERED_FIELDS),
        set(BrawlVisionReader._NB_TIERED_FIELDS),
        set(BrawlVisionReader._URF_TIERED_FIELDS),
    ]
    comparable = {"gold", "level", "cs", "kda"}
    records = narrowed = comparable_lost = disagree_lost = augsel_lost = 0

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        cv = rec.get("cv_reads")
        if not isinstance(cv, dict) or not cv:
            continue
        records += 1
        best = max(tiered, key=lambda s: len(set(cv) & s))
        keep = {k for k in cv if k in best}
        # _postprocess re-adds augment_select iff is_augment_select survived.
        if (FIELD in cv and cv.get("augment_select") == cv.get(FIELD)):
            keep.discard("augment_select")
            if FIELD in keep:
                keep.add("augment_select")
        dropped = set(cv) - keep
        if dropped:
            narrowed += 1
        comparable_lost += len(dropped & comparable)
        if "augment_select" in cv and "augment_select" in dropped:
            augsel_lost += 1
        for f in rec.get("disagree_fields") or []:
            if f in dropped:
                disagree_lost += 1

    assert records > 0
    # The measured answer: strict DOES narrow the corpus...
    assert narrowed > 0
    # ...but only telemetry-grade keys. Never the analytic core, and - post
    # re-home - never the augment-select flag the whole flag hold was about.
    assert comparable_lost == 0
    assert disagree_lost == 0
    assert augsel_lost == 0
