"""RM-158 data half - SR-derived arena PRECOMPUTE must never go unflagged.

The shipped ``laning_scenarios_arena.json`` is a byte copy of the SR table on both
patches that ever shipped one, so the PRECOMPUTE column of every covered
``mode=arena`` row the HZ-C1 shadow logger wrote is SR content. The NATIVE half of
the same row is a genuine Arena observation, so the correction flags the
precompute rather than deleting the row. This module pins:

  1. the SIGNATURE is live and discriminating on BOTH economy axes - reading
     only ``next_spike`` under-detects, because it agrees at L6,
  2. the detector FIRES on a planted SR row and stays SILENT on a correct arena
     row, on both axes (non-vacuity in both directions),
  3. the flagger tags only proven rows, never touches a native-only row, is
     byte-preserving otherwise, and is idempotent,
  4. the WRITER is gated - a new arena tick written while the served table still
     carries SR's economy is stamped at write time, so the corpus cannot be
     re-contaminated behind the guard,
  5. the LIVE corpus carries no UNFLAGGED SR-derived arena row.

Note on (5): the live corpus is gitignored + machine-local, so it is SKIPPED
where the file is absent - which includes CI and every worktree. It is the only
assertion here that does not run everywhere; 1-4 do, and they are what keep this
guard from being green-by-vacuum.
"""
from __future__ import annotations

import json

import pytest

from core import hz_choice_shadow as hzs
from core import laning_scenario_precompute as gen
from core import lead_projection as lead
from tools import hz_shadow_arena_contamination as hzc


def _row(band, spike, recall_label, mode="arena", mana="full", tag=False):
    row = {
        "ts": "2026-07-08T23:25:14.487798+00:00",
        "mode": mode,
        "my_champion": "Kai'Sa",
        "enemy": "Amumu",
        "band": band,
        "mana_state": mana,
        "cd_state": "all_up",
        "covered": True,
        "level": 3,
        "item_count": 2,
        "choices": [
            {"key": "A", "label": "Trade Amumu",
             "expected_outcome": "net swing +0.11; you remove 20% of Amumu, "
                                 "they remove 8% of you"},
            {"key": "B", "label": recall_label,
             "expected_outcome": f"buy Runaan's Hurricane (2500g) toward {spike}"},
        ],
    }
    if tag:
        row[hzs.PRECOMPUTE_SOURCE_KEY] = hzs.SR_COPY_TAG
    return row


def _native_only_row(band="L16", mode="arena"):
    """A coverage-miss tick: ZERO precompute content, pure Arena observation."""
    return {
        "ts": "2026-07-05T00:11:21.173932+00:00",
        "mode": mode, "my_champion": "Tristana", "enemy": None, "band": band,
        "mana_state": "full", "cd_state": "all_up", "covered": False,
        "game_time_s": 1285.78, "level": 16, "item_count": 0,
        "engine_version": "1.179.0", "choices": [],
        "native_action": "SPECTATE ROUND", "native_choices": [],
    }


# ---------------------------------------------------------------- 1. signature

def test_income_rows_are_distinct():
    """The whole signature dies if ARENA ever falls back to the SR rate."""
    assert lead.gold_income_is_registered("ARENA") is True
    assert lead.gold_income_per_min("SR") == 450.0
    assert lead.gold_income_per_min("ARENA") == 600.0


@pytest.mark.parametrize("band, sr_spike, ar_spike, sr_recall, ar_recall", [
    ("L2", "component", "component", "back_soon", "hold"),
    ("L6", "two_item", "first_item", "recall_now", "hold"),
    ("L11", "three_item", "two_item", "back_soon", "back_soon"),
])
def test_economy_expectation_is_the_pinned_table(band, sr_spike, ar_spike,
                                                 sr_recall, ar_recall):
    """Pinned, not merely recomputed - silent drift here would make the detector
    stop firing while every assertion below still passed.

    RE-PINNED for the RM-158 residual (per-mode levelling curve). Both mode
    inputs now move: the income RATE (450 vs 600 g/min, RM-158) and the band
    MINUTE (SR level = 1 + 0.5*min; ARENA spawns at 3 and levels at 0.70/min,
    so it reaches every band far sooner and has banked LESS at it). The table
    below is what ``economy_cell`` computes today; the detector derives its own
    expectation live from that same function, so the discrimination is intact
    and only the axis attribution moved. Measured against the live corpus after
    the change: the SAME 644 rows are proven, arena_unflagged_sr = 0 and
    arena_undecided_with_precompute = 0, so no re-flag is owed.
    """
    exp = hzc.economy_expectation(band, "full")
    assert exp["sr"]["next_spike"] == sr_spike
    assert exp["arena"]["next_spike"] == ar_spike
    assert exp["sr"]["recall"] == sr_recall
    assert exp["arena"]["recall"] == ar_recall


def test_next_spike_alone_under_detects_at_l2():
    """The reason the detector needs the recall axis at all."""
    exp = hzc.economy_expectation("L2", "full")
    assert exp["sr"]["next_spike"] == exp["arena"]["next_spike"]
    assert exp["sr"]["recall"] != exp["arena"]["recall"]


def test_recall_alone_under_detects_at_l11():
    """And the reason it needs the next_spike axis. Neither axis is sufficient
    alone; together they cover every generated band."""
    exp = hzc.economy_expectation("L11", "full")
    assert exp["sr"]["recall"] == exp["arena"]["recall"]
    assert exp["sr"]["next_spike"] != exp["arena"]["next_spike"]


@pytest.mark.parametrize("band", list(gen.GEN_BANDS))
@pytest.mark.parametrize("mana", ["full", "low"])
def test_every_generated_band_and_mana_is_decidable(band, mana):
    """The strong form, and it now holds everywhere.

    Under the mode-blind curve one band+mana cell collapsed on BOTH label axes
    and the detector had to fall back to ``gold_at_band``, which only decides
    when the row happened to render the no-next-item form. With the per-mode
    curve every generated cell is decidable on a LABEL axis, so the detector no
    longer depends on the render form anywhere. That is a strengthening, and it
    is asserted rather than asserted-away.
    """
    exp = hzc.economy_expectation(band, mana)
    assert (exp["sr"]["next_spike"] != exp["arena"]["next_spike"]
            or exp["sr"]["recall"] != exp["arena"]["recall"])


def test_gold_axis_still_decides_and_takes_precedence():
    """``gold_at_band`` remains the first-precedence axis where it is rendered,
    and it differs at every generated band."""
    for band in gen.GEN_BANDS:
        exp = hzc.economy_expectation(band, "full")
        assert exp["sr"]["gold_at_band"] != exp["arena"]["gold_at_band"], band
    row = _row("L11", "two_item", "Back soon")
    row["choices"][1]["expected_outcome"] = "9000g banked; next spike two_item"
    assert hzc.sr_derived_reason(row) == "gold_at_band"
    row["choices"][1]["expected_outcome"] = "6076g banked; next spike two_item"
    assert hzc.sr_derived_reason(row) is None


def test_l16_reads_the_l11_cell():
    """item-370 descend-only fallback (core/precomputed_laning_coach.py:511)."""
    assert hzc.effective_band("L16") == "L11"
    assert hzc.effective_band("L2") == "L2"
    assert hzc.effective_band("L99") is None


# ------------------------------------------------------------- 2. non-vacuity

@pytest.mark.parametrize("band, spike, label, axis", [
    ("L2", "component", "Back soon", "recall"),        # ONLY the recall axis
    ("L6", "two_item", "Recall now", "next_spike"),    # spike decides first
    ("L11", "three_item", "Back soon", "next_spike"),  # ONLY the spike axis
    ("L16", "three_item", "Back soon", "next_spike"),  # L16 reads the L11 cell
])
def test_detector_fires_on_planted_sr_row(band, spike, label, axis):
    assert hzc.sr_derived_reason(_row(band, spike, label)) == axis


@pytest.mark.parametrize("band, spike, label", [
    ("L2", "component", "Hold and farm this window"),
    ("L6", "first_item", "Hold and farm this window"),
    ("L11", "two_item", "Back soon"),
    ("L16", "two_item", "Back soon"),
])
def test_detector_silent_on_correct_arena_row(band, spike, label):
    assert hzc.sr_derived_reason(_row(band, spike, label)) is None


def test_detector_ignores_other_modes_native_rows_and_junk():
    assert hzc.sr_derived_reason(
        _row("L2", "component", "Back soon", mode="sr")) is None
    assert hzc.sr_derived_reason(_native_only_row()) is None
    assert hzc.sr_derived_reason({"mode": "arena", "band": "L2"}) is None
    assert hzc.sr_derived_reason("not a row") is None
    assert hzc.sr_derived_reason(None) is None


# ----------------------------------------------------------------- 3. flagger

def test_flag_tags_only_proven_rows_and_preserves_every_other_byte(tmp_path):
    src = tmp_path / "src.jsonl"
    dst = tmp_path / "dst.jsonl"
    keep_sr = json.dumps(_row("L2", "component", "Back soon", mode="sr"))
    native = json.dumps(_native_only_row())
    # Under the per-mode curve L2 is decided by the recall axis and L6 by the
    # next_spike axis (see the pinned table above). The fixture keeps one row
    # per axis so the by-axis census below stays non-vacuous either way.
    hit_recall = json.dumps(_row("L2", "component", "Back soon"))
    hit_spike = json.dumps(_row("L6", "two_item", "Recall now"))
    clean = json.dumps(_row("L6", "first_item", "Hold and farm this window"))
    torn = "\x00\x00\x00"
    raw = "\r\n".join([keep_sr, native, hit_spike, torn, hit_recall, clean]) + "\r\n"
    src.write_bytes(raw.encode("utf-8"))

    result = hzc.flag_rows(src, dst)
    assert result["tagged"] == 2
    assert result["untouched"] == 4

    out = dst.read_bytes().split(b"\r\n")
    assert out[0] == keep_sr.encode()          # other mode: untouched
    assert out[1] == native.encode()           # native-only: untouched
    assert out[3] == torn.encode()             # torn append: untouched
    assert out[5] == clean.encode()            # correct arena row: untouched
    for idx in (2, 4):
        row = json.loads(out[idx])
        assert row[hzs.PRECOMPUTE_SOURCE_KEY] == hzs.SR_COPY_TAG
        row.pop(hzs.PRECOMPUTE_SOURCE_KEY)
        assert row == json.loads([hit_spike, None, hit_recall][idx - 2 if idx == 2 else 2])

    stats = hzc.scan(dst)
    assert stats["arena_rows"] == 4
    assert stats["arena_native_only"] == 1
    assert stats["arena_flagged"] == 2
    assert stats["arena_unflagged_sr"] == 0
    assert stats["arena_proven_by_axis"] == {"next_spike": 1, "recall": 1}


def test_flag_is_idempotent(tmp_path):
    src = tmp_path / "src.jsonl"
    dst = tmp_path / "dst.jsonl"
    src.write_bytes((json.dumps(_row("L2", "component", "Back soon")) + "\n").encode())
    hzc.flag_rows(src, dst)
    once = dst.read_bytes()
    second = tmp_path / "dst2.jsonl"
    hzc.flag_rows(dst, second)
    assert second.read_bytes() == once


def test_flag_never_drops_a_line(tmp_path):
    """The 2026-08-06 regression: a purge deleted 504 uncovered arena rows that
    had no precompute column to correct. Nothing here may remove a line."""
    src = tmp_path / "src.jsonl"
    dst = tmp_path / "dst.jsonl"
    rows = [_native_only_row(), _row("L2", "component", "Back soon"),
            _native_only_row("L2"), _row("L6", "two_item", "Recall now")]
    src.write_bytes(("\n".join(json.dumps(r) for r in rows) + "\n").encode())
    hzc.flag_rows(src, dst)
    assert len(dst.read_bytes().splitlines()) == len(rows)
    stats = hzc.scan(dst)
    assert stats["arena_rows"] == 4
    assert stats["arena_native_only"] == 2


# ------------------------------------------------------------- 4. writer gate

def _serve(monkeypatch, income):
    payload = {"dimensions": {"economy": {"income_per_min": income}}}
    monkeypatch.setattr(gen, "load_laning_scenarios",
                        lambda mode="sr", patch=None: payload)


def test_writer_tag_fires_while_the_served_arena_table_is_an_sr_copy(monkeypatch):
    _serve(monkeypatch, 450.0)
    assert hzs.precompute_source_tag("arena") == hzs.SR_COPY_TAG


def test_writer_tag_clears_itself_once_a_correct_table_ships(monkeypatch):
    _serve(monkeypatch, 600.0)
    assert hzs.precompute_source_tag("arena") is None


def test_writer_tag_never_fires_for_sr_itself(monkeypatch):
    _serve(monkeypatch, 450.0)
    assert hzs.precompute_source_tag("sr") is None
    assert hzs.precompute_source_tag("nonsense") is None


def test_writer_tag_is_fail_soft(monkeypatch):
    monkeypatch.setattr(gen, "load_laning_scenarios",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert hzs.precompute_source_tag("arena") is None
    _serve(monkeypatch, None)
    assert hzs.precompute_source_tag("arena") is None


def test_written_arena_record_is_stamped(tmp_path, monkeypatch):
    _serve(monkeypatch, 450.0)
    p = tmp_path / "shadow.jsonl"
    rec = hzs.log_precomputed_choices(
        "arena", "Kai'Sa", "Amumu",
        choices=[{"key": "A", "label": "Trade Amumu"}],
        band="L2", mana_state="full", cd_state="all_up", covered=True,
        level=3, item_count=2, game_time_s=61.0, path=p,
    )
    assert rec[hzs.PRECOMPUTE_SOURCE_KEY] == hzs.SR_COPY_TAG
    on_disk = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert on_disk[hzs.PRECOMPUTE_SOURCE_KEY] == hzs.SR_COPY_TAG


def test_written_coverage_miss_is_not_stamped(tmp_path, monkeypatch):
    """A coverage miss has no precompute column, so there is nothing to
    disown - stamping it would falsely mark a clean observation."""
    _serve(monkeypatch, 450.0)
    p = tmp_path / "shadow.jsonl"
    rec = hzs.log_precomputed_choices(
        "arena", "Tristana", None, choices=[], band="L16", mana_state="full",
        cd_state="all_up", covered=False, level=16, game_time_s=1285.7, path=p,
    )
    assert hzs.PRECOMPUTE_SOURCE_KEY not in rec


def test_written_record_is_clean_once_the_table_is_fixed(tmp_path, monkeypatch):
    _serve(monkeypatch, 600.0)
    p = tmp_path / "shadow.jsonl"
    rec = hzs.log_precomputed_choices(
        "arena", "Kai'Sa", "Amumu", choices=[{"key": "A", "label": "Trade"}],
        band="L2", mana_state="full", cd_state="all_up", covered=True,
        level=3, game_time_s=61.0, path=p,
    )
    assert hzs.PRECOMPUTE_SOURCE_KEY not in rec


# ------------------------------------------------------------- 5. live corpus

def test_corpus_path_is_immune_to_the_conftest_shadow_redirect(monkeypatch):
    """conftest autouse-patches SHADOW_PATH to a tmp dir for EVERY test, which
    silently self-skipped the corpus guard below until this was pinned."""
    monkeypatch.delenv(hzc.CORPUS_ENV, raising=False)
    resolved = hzc.live_corpus_path()
    assert resolved.parts[-2:] == hzc.CORPUS_RELPATH
    assert resolved != hzs.SHADOW_PATH        # the patched constant, not ours
    monkeypatch.setenv(hzc.CORPUS_ENV, "X:/elsewhere/corpus.jsonl")
    assert str(hzc.live_corpus_path()).replace("\\", "/") == "X:/elsewhere/corpus.jsonl"


def test_live_corpus_has_no_unflagged_sr_derived_arena_row():
    corpus = hzc.live_corpus_path()
    if not corpus.exists():
        pytest.skip(
            f"machine-local gitignored corpus absent: {corpus}. EXPECTED in a "
            f"worktree and in CI - the file lives only in the main checkout, so "
            f"this assertion is NOT a CI gate. Point {hzc.CORPUS_ENV} at it to run."
        )
    stats = hzc.scan(corpus)
    assert stats["arena_unflagged_sr"] == 0, (
        f"{stats['arena_unflagged_sr']} arena rows carry UNFLAGGED SR-derived "
        f"precompute in {corpus} (per axis: {stats['arena_proven_by_axis']}, per "
        f"band: {stats['arena_proven_by_band']}). Re-run "
        f"tools/hz_shadow_arena_contamination.py --flag. Do NOT delete the rows: "
        f"their native half is a genuine Arena observation."
    )
