"""RM-158 data half - guard against SR-derived mode=arena rows in the HZ-C1 corpus.

The shipped ``laning_scenarios_arena.json`` is a byte copy of the SR table on both
patches that ever shipped one, so every ``mode=arena`` row the HZ-C1 shadow logger
wrote carries an SR precompute answer. This module pins:

  1. the SIGNATURE is live and discriminating (the SR / ARENA income rows are
     distinct and the spike labels they produce differ at L2 and L11),
  2. the detector actually FIRES on a planted contaminated row and does NOT fire
     on a correctly-generated arena row (non-vacuity, both directions),
  3. the purge is byte-preserving + drops exactly the arena bucket,
  4. the LIVE corpus carries no SR-derived arena row - and no arena row at all.

Note on (4): the live corpus is gitignored + machine-local, so that assertion is
skipped where the file is absent (CI). It is the WEAKEST of the four on purpose;
1-3 run everywhere and are what keep this guard from being green-by-vacuum.
"""
from __future__ import annotations

import json

import pytest

from core import lead_projection as lead
from tools import hz_shadow_arena_contamination as hzc


def _row(band, spike, mode="arena"):
    return {
        "ts": "2026-07-08T23:25:14.487798+00:00",
        "mode": mode,
        "my_champion": "Kai'Sa",
        "enemy": "Amumu",
        "band": band,
        "mana_state": "full",
        "cd_state": "all_up",
        "covered": True,
        "level": 3,
        "item_count": 2,
        "choices": [
            {"key": "A", "label": "Trade Amumu",
             "expected_outcome": "net swing +0.11; you remove 20% of Amumu, "
                                 "they remove 8% of you"},
            {"key": "B", "label": "Back soon",
             "expected_outcome": f"buy Runaan's Hurricane (2500g) toward {spike}"},
        ],
    }


# ---------------------------------------------------------------- 1. signature

def test_income_rows_are_distinct():
    """The whole signature dies if ARENA ever falls back to the SR rate."""
    assert lead.gold_income_is_registered("ARENA") is True
    assert lead.gold_income_per_min("SR") == 450.0
    assert lead.gold_income_per_min("ARENA") == 600.0


def test_discriminating_bands_are_the_pinned_pair():
    """Pinned, not merely recomputed - a silent drift here would make the
    detector stop firing while every assertion below still passed."""
    assert hzc.discriminating_bands() == {
        "L2": ("component", "first_item"),
        "L11": ("three_item", "complete"),
    }


def test_l6_is_not_decidable():
    """L6 agrees under both income rows; the detector must not claim it."""
    assert hzc.spike_label_for("L6", "SR") == hzc.spike_label_for("L6", "ARENA")
    assert "L6" not in hzc.discriminating_bands()


def test_l16_reads_the_l11_cell():
    """item-370 descend-only fallback (core/precomputed_laning_coach.py:511)."""
    assert hzc.effective_band("L16") == "L11"
    assert hzc.effective_band("L2") == "L2"
    assert hzc.effective_band("L99") is None


# ------------------------------------------------------------- 2. non-vacuity

@pytest.mark.parametrize("band, spike", [
    ("L2", "component"),      # SR label at L2; ARENA would say first_item
    ("L11", "three_item"),    # SR label at L11; ARENA would say complete
    ("L16", "three_item"),    # L16 reads the L11 cell
])
def test_detector_fires_on_planted_sr_row(band, spike):
    assert hzc.is_sr_derived_arena_row(_row(band, spike)) is True


@pytest.mark.parametrize("band, spike", [
    ("L2", "first_item"),
    ("L11", "complete"),
    ("L16", "complete"),
])
def test_detector_silent_on_correct_arena_row(band, spike):
    assert hzc.is_sr_derived_arena_row(_row(band, spike)) is False


def test_detector_ignores_other_modes_and_shapes():
    assert hzc.is_sr_derived_arena_row(_row("L2", "component", mode="sr")) is False
    assert hzc.is_sr_derived_arena_row({"mode": "arena", "band": "L2"}) is False
    assert hzc.is_sr_derived_arena_row({"mode": "arena", "band": "L6",
                                        "choices": []}) is False
    assert hzc.is_sr_derived_arena_row("not a row") is False
    assert hzc.is_sr_derived_arena_row(None) is False


# ------------------------------------------------------------------- 3. purge

def test_purge_drops_only_arena_and_preserves_bytes(tmp_path):
    corpus = tmp_path / "shadow.jsonl"
    keep_sr = json.dumps(_row("L2", "component", mode="sr"))
    keep_aram = json.dumps(_row("L6", "two_item", mode="aram"))
    drop_a = json.dumps(_row("L2", "component"))
    drop_b = json.dumps(_row("L6", "two_item"))  # undecidable, dropped anyway
    torn = "\x00\x00\x00"                        # a torn append must survive
    raw = "\r\n".join([keep_sr, drop_a, torn, keep_aram, drop_b]) + "\r\n"
    corpus.write_bytes(raw.encode("utf-8"))

    backup = tmp_path / "backup.jsonl"
    result = hzc.purge(corpus, backup)

    assert result["dropped"] == 2
    assert result["kept"] == 3
    assert backup.read_bytes() == raw.encode("utf-8")
    out = corpus.read_bytes()
    assert out == ("\r\n".join([keep_sr, torn, keep_aram]) + "\r\n").encode("utf-8")
    assert b"\r\n" in out                       # CRLF preserved, not normalised


def test_scan_counts_the_arena_bucket(tmp_path):
    corpus = tmp_path / "shadow.jsonl"
    lines = [json.dumps(_row("L2", "component")),
             json.dumps(_row("L6", "two_item")),
             json.dumps(_row("L2", "component", mode="sr"))]
    corpus.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    stats = hzc.scan(corpus)
    assert stats["arena_rows"] == 2
    assert stats["arena_proven_sr"] == 1
    assert stats["arena_undecidable"] == 1
    assert stats["by_mode"]["sr"] == 1


# ------------------------------------------------------------- 4. live corpus

def test_corpus_path_is_immune_to_the_conftest_shadow_redirect(monkeypatch):
    """conftest autouse-patches SHADOW_PATH to a tmp dir for EVERY test, which
    silently self-skipped the corpus guard below until this was pinned."""
    from core import hz_choice_shadow as hzs
    monkeypatch.delenv(hzc.CORPUS_ENV, raising=False)
    resolved = hzc.live_corpus_path()
    assert resolved.parts[-2:] == hzc.CORPUS_RELPATH
    assert resolved != hzs.SHADOW_PATH        # the patched constant, not ours
    monkeypatch.setenv(hzc.CORPUS_ENV, "X:/elsewhere/corpus.jsonl")
    assert str(hzc.live_corpus_path()).replace("\\", "/") == "X:/elsewhere/corpus.jsonl"


def test_live_corpus_has_no_sr_derived_arena_row():
    corpus = hzc.live_corpus_path()
    if not corpus.exists():
        pytest.skip(
            f"machine-local gitignored corpus absent: {corpus}. This is EXPECTED "
            f"in a worktree and in CI - the file lives only in the main checkout. "
            f"Point {hzc.CORPUS_ENV} at it to make this guard run."
        )
    stats = hzc.scan(corpus)
    assert stats["arena_proven_sr"] == 0, (
        f"{stats['arena_proven_sr']} SR-derived arena rows are back in "
        f"{corpus} (per band: {stats['arena_proven_by_band']}). Re-run "
        "tools/hz_shadow_arena_contamination.py --purge; and if a CORRECT "
        "arena laning table has since shipped, retire this guard deliberately "
        "rather than loosening it."
    )
    assert stats["arena_rows"] == 0, (
        f"{stats['arena_rows']} mode=arena rows are present in {corpus}. Until a "
        "non-SR-copy arena laning table ships, no arena row in this corpus is a "
        "valid arena measurement (RM-158)."
    )
