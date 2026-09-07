"""Pins ADR-014 / RM-175: the shipped ARAM laning tables are KNOWN-WRONG on
economy, by a closed-form factor, and are deliberately not regenerated.

This is the machine-checkable half of the decision. A prose note saying "the
ARAM tables are stale" rots the moment someone regenerates one, or the moment
the level curve moves again; these assertions go red instead.

Deliberately split so the teeth do NOT depend on git-LFS content:

1. CLOSED FORM (pure code, always runs). The shipped tables were generated when
   ``lead_projection.minutes_for_level`` was mode-blind. Both the SR and ARAM
   curves start at base level 1.0, so ``(level - base)`` cancels and the whole
   error is ``rate_SR / rate_ARAM`` at EVERY band. Derived from
   ``level_curve`` at runtime, never from a literal, so re-tuning either curve
   fails here rather than silently invalidating the ADR.
2. AXIS CENSUS (pure code, always runs). Which of the three persisted economy
   fields actually move. RM-175 as filed had this transposed; this is the
   assertion that catches that class of mistake.
3. DISK PIN (skips only on a missing file or an unfetched git-LFS pointer). The
   shipped bytes at 16.12.1 and 16.13.1 carry exactly the six known-wrong
   triples and none of the corrected values.
4. CONTRACT. ADR-014 is on disk, indexed, and states the ratio
   (feedback_contract_test_must_read_the_contract_from_disk).

MEASURED ONCE, 2026-08-06, recorded here as provenance for the disk half: a
full-file scan of both ARAM tables returns exactly 6 distinct
(gold_at_band, next_spike, recall) triples. 355008 economy leaves at 16.12.1 and
359148 at 16.13.1 are wrong on gold_at_band and next_spike; 137600 and 139092
respectively are wrong on recall.

ASCII only.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import laning_scenario_precompute as lsp  # noqa: E402
from core import lead_projection as lp  # noqa: E402

_ADR_PATH = _ROOT / "docs" / "adr" / "ADR-014-aram-laning-table-known-wrong-not-regenerated.md"
_TABLE_DIR = _ROOT / "data" / "daemon_slayer" / "laning_scenarios"

# Patches whose shipped ARAM table carries the mode-blind economy block.
_STALE_PATCHES = ("16.12.1", "16.13.1")

# The six (gold_at_band, next_spike, recall) triples a MODE-BLIND curve
# produces for ARAM. Reconstructed by driving economy_cell under the SR curve
# and then confirmed byte-for-byte against both shipped tables.
_KNOWN_WRONG_TRIPLES = {
    ("1200.0", "first_item", "hold"),
    ("1200.0", "first_item", "recall_now"),
    ("6000.0", "two_item", "back_soon"),
    ("6000.0", "two_item", "recall_now"),
    ("12000.0", "complete", "hold"),
    ("12000.0", "complete", "recall_now"),
}

# Leaves are emitted with sorted keys, so the economy triple is contiguous.
_ECONOMY_RE = re.compile(
    rb'"gold_at_band":([0-9.]+),"next_spike":"([a-z_]+)","recall":"([a-z_]+)"'
)

_MANA_COMBOS = (("full", False), ("full", True), ("low", False), ("low", True))


def _mode_blind_economy(band: str, mana_state: str, manaless: bool,
                        monkeypatch) -> dict:
    """``economy_cell`` for ARAM as it was generated PRE-FIX: the ARAM income
    row (which was always correct) over the SR levelling curve.

    Patching ``level_curve`` on the module reproduces the defect exactly -
    ``minutes_for_level`` resolves it through the module global - while leaving
    ``gold_income_per_min`` alone, which is right: the shipped ARAM headers
    carry ``income_per_min: 600.0``, so income was never the defect."""
    sr_curve = lp.level_curve("SR")
    monkeypatch.setattr(lp, "level_curve", lambda mode="SR": sr_curve)
    return lsp.economy_cell(band, mana_state, "ARAM", manaless)


# ------------------------------------------------------------------ 1. closed form
def test_aram_error_is_the_curve_rate_ratio_at_every_band(monkeypatch):
    """The corrected/shipped gold ratio is rate_SR / rate_ARAM, exactly, at
    every generated band - because both curves share base level 1.0 so the
    (level - base) factor cancels."""
    sr_base, sr_rate = lp.level_curve("SR")
    aram_base, aram_rate = lp.level_curve("ARAM")
    assert sr_base == aram_base, (
        "ADR-014's closed form assumes SR and ARAM share a base level; they no "
        f"longer do (SR {sr_base}, ARAM {aram_base}). The error is no longer "
        "band-independent - re-derive it and update ADR-014."
    )
    expected_ratio = sr_rate / aram_rate
    income = lp.gold_income_per_min("ARAM")

    for band in lsp.GEN_BANDS:
        level = lsp.level_for_band(band)
        # EXACT arm - the model before economy_cell's 4-decimal _round.
        shipped_raw = income * ((level - sr_base) / sr_rate)
        corrected_raw = income * lp.minutes_for_level(level, "ARAM")
        assert corrected_raw / shipped_raw == pytest.approx(
            expected_ratio, rel=1e-12), band

        # PERSISTED arm - what actually lands in the table. Only good to the
        # 4-decimal rounding economy_cell applies, hence rel=1e-6.
        shipped = _mode_blind_economy(band, "full", False, monkeypatch)
        monkeypatch.undo()
        corrected = lsp.economy_cell(band, "full", "ARAM", False)
        assert shipped["gold_at_band"] > 0.0, band
        ratio = corrected["gold_at_band"] / shipped["gold_at_band"]
        assert ratio == pytest.approx(expected_ratio, rel=1e-6), (
            f"{band}: shipped {shipped['gold_at_band']} -> corrected "
            f"{corrected['gold_at_band']} is ratio {ratio}, expected "
            f"{expected_ratio}"
        )


def test_aram_gold_error_is_minus_50_495_percent():
    """The headline figure, pinned to full precision on the UNROUNDED model.
    RM-175 filed it as -50.495 pct; the exact value is 0.5/1.01 - 1, i.e.
    -50.495049504950495 pct."""
    sr_base, sr_rate = lp.level_curve("SR")
    income = lp.gold_income_per_min("ARAM")
    for band in lsp.GEN_BANDS:
        level = lsp.level_for_band(band)
        shipped_raw = income * ((level - sr_base) / sr_rate)
        corrected_raw = income * lp.minutes_for_level(level, "ARAM")
        pct = (corrected_raw - shipped_raw) / shipped_raw * 100.0
        assert pct == pytest.approx(-50.495049504950495, abs=1e-9), (band, pct)


def test_sr_economy_is_unaffected_by_the_curve_fix():
    """SR owes nothing, for a reason worth pinning rather than assuming: the
    curve the pre-fix code fell through to IS the SR row, so SR economy is
    identically the mode-blind economy.

    Pinned two ways, because the identity alone would survive an SR re-base:
    the SR row must still BE the default row, and the SR golds must still be
    the values the shipped SR tables carry (900 / 4500 / 9000 - read off
    laning_scenarios_sr.json). Re-basing SR's 0.5 rate to its measured 0.5584
    (the operator-gated change flagged in core/lead_projection.py) fails here,
    which is correct: at that moment the SR tables join the debt and RM-175's
    scope was wrong."""
    assert lp.level_curve("SR") == lp._DEFAULT_LEVEL_CURVE, (
        "SR is no longer the curve an unregistered mode falls through to; the "
        "ADR-014 reasoning for SR being unaffected no longer holds"
    )
    shipped_sr_gold = {"L2": 900.0, "L6": 4500.0, "L11": 9000.0}
    for band in lsp.GEN_BANDS:
        assert lsp.economy_cell(band, "full", "SR", False)["gold_at_band"] == \
            pytest.approx(shipped_sr_gold[band]), band


# ------------------------------------------------------------------ 2. axis census
def test_which_economy_axes_move_per_band(monkeypatch):
    """RM-175 as filed said next_spike moves at L2/L11 and recall at L2/L6/L11.
    Measured, it is transposed: next_spike moves at all three bands (12 of 12
    mana/manaless combinations) and recall moves at L2 and L11 only (3 of 4 at
    each), never at L6."""
    moved: dict[str, set] = {"gold_at_band": set(), "next_spike": set(),
                             "recall": set()}
    recall_combo_hits = {band: 0 for band in lsp.GEN_BANDS}

    for band in lsp.GEN_BANDS:
        for mana_state, manaless in _MANA_COMBOS:
            shipped = _mode_blind_economy(band, mana_state, manaless, monkeypatch)
            monkeypatch.undo()
            corrected = lsp.economy_cell(band, mana_state, "ARAM", manaless)
            for field in moved:
                if shipped[field] != corrected[field]:
                    moved[field].add(band)
                    if field == "recall":
                        recall_combo_hits[band] += 1

    assert moved["gold_at_band"] == set(lsp.GEN_BANDS)
    assert moved["next_spike"] == set(lsp.GEN_BANDS), (
        "next_spike is expected to move at EVERY generated band; got "
        f"{sorted(moved['next_spike'])}"
    )
    assert moved["recall"] == {"L2", "L11"}, (
        "recall is expected to move at L2 and L11 only; got "
        f"{sorted(moved['recall'])}"
    )
    assert recall_combo_hits == {"L2": 3, "L6": 0, "L11": 3}, recall_combo_hits


def test_a_stale_hold_SUPPRESSES_the_recall_chip_rather_than_mislabelling_it():
    """The severity finding, and the one that makes the defect worse in KIND
    than "a wrong number".

    ``_RECALL_LABELS`` has no ``hold`` key, and the B chip at
    precomputed_laning_coach.py:441 is built only when the recall value IS a
    key. The shipped ARAM tables say ``hold`` at L2 and L11 where the corrected
    curve says ``back_soon``, so the stale table DELETES the recall option at
    two of three bands rather than mis-wording it.

    Adding a ``hold`` key changes that shape - the chip would be emitted with a
    wrong label instead of suppressed - which is an ADR-014 trigger, so this is
    pinned rather than assumed."""
    from core import precomputed_laning_coach as plc

    assert "hold" not in plc._RECALL_LABELS, (
        "_RECALL_LABELS gained a 'hold' key. The stale ARAM tables now EMIT a "
        "wrongly-labelled recall chip instead of suppressing it - re-read the "
        "trigger list in ADR-014."
    )
    assert set(plc._RECALL_LABELS) == {"recall_now", "back_soon"}, \
        sorted(plc._RECALL_LABELS)
    # The two shipped values at L2 / L11 vs what the corrected curve produces.
    assert "hold" not in plc._RECALL_LABELS      # suppressed today
    assert "back_soon" in plc._RECALL_LABELS     # would render post-regen


def test_the_recall_combo_that_does_not_move_is_the_mana_starved_one(monkeypatch):
    """(low mana, mana champion) is pinned to recall_now by rule 1 of
    _recall_verdict on both curves, which is why it is the 1-of-4 that holds."""
    for band in ("L2", "L11"):
        shipped = _mode_blind_economy(band, "low", False, monkeypatch)
        monkeypatch.undo()
        corrected = lsp.economy_cell(band, "low", "ARAM", False)
        assert shipped["recall"] == corrected["recall"] == "recall_now", band


# ------------------------------------------------------------------ 3. disk pin
def _table_bytes_or_skip(patch: str) -> Path:
    """The disk half runs only where the git-LFS objects are fetched.

    NO CI WORKFLOW FETCHES LFS - re-derived 2026-09-06, ci.yml, docs-guards.yml
    and patch-day-ddragon-sync.yml carry zero `lfs:` keys between them (the
    first two on actions/checkout@v6, the third on @v4; codspeed.yml was
    deleted) - so this half is PERMANENTLY skipped in CI and is a
    developer-machine tripwire only. Under the repo's
    default -q a skip renders as a bare `s`, which is not loud enough for a
    permanent condition, so the reason is also raised as a warning: the
    warnings summary shows under -q, the skip reason does not."""
    path = _TABLE_DIR / patch / "laning_scenarios_aram.json"
    reason = None
    if not path.is_file():
        reason = f"{path} absent (table not on disk)"
    else:
        head = path.open("rb").read(64)
        if head.startswith(b"version https://git-lfs"):
            reason = f"{path} is an unfetched git-LFS pointer; run git lfs pull"
    if reason:
        warnings.warn(
            f"ADR-014 disk pin NOT enforced for {patch}: {reason}. The "
            "closed-form and axis-census assertions still ran.",
            UserWarning, stacklevel=2,
        )
        pytest.skip(reason)
    return path


def _economy_triples(path: Path) -> set:
    """Every distinct economy triple in the file. Chunked so a 66 MB table does
    not land in memory twice; the 200-byte carry-over stops a triple that
    straddles a chunk boundary from being missed."""
    found = set()
    with path.open("rb") as fh:
        tail = b""
        while True:
            chunk = fh.read(1 << 22)
            if not chunk:
                break
            buf = tail + chunk
            for m in _ECONOMY_RE.finditer(buf):
                found.add(tuple(g.decode("ascii") for g in m.groups()))
            tail = buf[-200:]
    return found


@pytest.mark.parametrize("patch", _STALE_PATCHES)
def test_shipped_aram_table_carries_exactly_the_known_wrong_triples(patch):
    """Set EQUALITY, not containment: a subset assertion would stay green if a
    partial regen introduced corrected leaves alongside stale ones."""
    path = _table_bytes_or_skip(patch)
    found = _economy_triples(path)
    assert found == _KNOWN_WRONG_TRIPLES, (
        f"{path.name} @ {patch} no longer carries exactly the ADR-014 "
        f"known-wrong economy set. Found {sorted(found)}. If this table was "
        "regenerated, ADR-014's decision has been reversed - update it and "
        "RM-175 rather than relaxing this assertion."
    )


@pytest.mark.parametrize("patch", _STALE_PATCHES)
def test_shipped_aram_table_contains_no_corrected_gold_value(patch):
    """The corrected golds (594.0594 / 2970.297 / 5940.5941) must appear
    nowhere in the shipped bytes."""
    path = _table_bytes_or_skip(patch)
    golds = {t[0] for t in _economy_triples(path)}
    corrected = {
        str(lsp.economy_cell(band, "full", "ARAM", False)["gold_at_band"])
        for band in lsp.GEN_BANDS
    }
    assert not (golds & corrected), (
        f"{path.name} @ {patch} already carries corrected gold values "
        f"{sorted(golds & corrected)}"
    )


def test_16_12_1_aram_is_unreachable_without_an_explicit_pin():
    """Half the deferred regen is provably wasted work: no production caller can
    reach 16.12.1 while a 16.13.1 ARAM table exists."""
    if not (_TABLE_DIR / "16.13.1" / "laning_scenarios_aram.json").is_file():
        warnings.warn(
            "ADR-014 reachability pin NOT enforced: the 16.13.1 aram table is "
            "not on disk (the permanent CI state - no workflow fetches LFS).",
            UserWarning, stacklevel=2,
        )
        pytest.skip("16.13.1 aram table absent; reachability claim not testable")
    assert lsp._latest_available_patch("aram") == "16.13.1", (
        "the ARAM prior-patch fallback no longer resolves to 16.13.1; 16.12.1 "
        "may now be reachable, which is an ADR-014 regen trigger"
    )


# ------------------------------------------------------------------ 4. contract
def test_adr_014_is_on_disk_and_indexed():
    assert _ADR_PATH.exists(), f"ADR-014 missing at {_ADR_PATH}"
    index = (_ROOT / "docs" / "adr" / "README.md").read_text(encoding="utf-8")
    assert _ADR_PATH.name in index, "ADR-014 is not linked from docs/adr/README.md"


def test_adr_014_records_the_ratio_and_the_reachability_finding():
    text = _ADR_PATH.read_text(encoding="utf-8")
    for token in (
        "0.5 / 1.01",
        "-50.495049504950495",
        "_latest_available_patch",
        "laning_scenarios/v4",
        "hz_choice_shadow.jsonl",
        "_RECALL_LABELS",
        "Two gaps in the guarding",
    ):
        assert token in text, f"ADR-014 no longer states {token!r}"


def test_adr_014_carries_a_trigger_list_for_reopening():
    text = _ADR_PATH.read_text(encoding="utf-8")
    assert "What would make the regen NECESSARY" in text
    assert "RC_LANING_CV_SERVED" in text
    assert "test_laning_verdict_flip_retired.py" in text
