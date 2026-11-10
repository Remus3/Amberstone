"""s144 true-audit cycle 174 - tools/det_coach_shadow_report.py hardening.

The B1 flip-readiness gate reads data/det_coach_shadow.jsonl, which a live
writer appends to (110 MB / 60721 rows measured read-only 2026-11-06). Four
weaknesses, one test group each (S144-T-01 .. S144-T-04 in the cycle report):

  1. FAIL-SOFT CONTRACT: the docstring promises "a missing / empty / malformed
     log yields zeroed sections, never an exception", but one non-UTF-8 byte
     anywhere in the file raised UnicodeDecodeError out of build_report and
     main (read_text decoded the WHOLE file at once); a UTF-8 BOM silently
     dropped the first row.
  2. MEMORY: the whole file was held as one str, then as a splitlines copy,
     then as full parsed rows (callouts, lead_projection, enemy lists the
     report never reads) - 669 MB peak working set on the live 110 MB log.
  3. VALIDATION: a truthy NON-LIST det_choices / native_choices ("x", a dict)
     counted as both-present and sat in every denominator as an incomparable
     row, dragging the headline alignment rate down.
  4. KEYWORD MATCHING: label keywords matched as raw substrings, so "brush"
     read as a build ("rush"), "seven" as a hold ("even"), "rebuild" as a
     build. Keywords now match at a WORD START (plurals such as "trades" and
     "items" still match).

Hermetic: every test builds rows in tmp_path (the real log is gitignored).
"""
from __future__ import annotations

import json
import tracemalloc
from typing import TYPE_CHECKING

import tools.det_coach_shadow_report as rpt

if TYPE_CHECKING:
    from pathlib import Path


def _choice(key, label, source_tag):
    return {"key": key, "label": label, "source_tag": source_tag}


def _rec(det, native, **extra):
    rec = {
        "ts": "2026-06-23T00:00:00+00:00",
        "mode": "sr",
        "my_champion": "Caitlyn",
        "enemy_champions": ["Galio"],
        "engine_version": "1.149.0",
        "replaced": True,
        "det_choices": det,
        "callouts": [],
        "lead_projection": {},
        "native_choices": native,
    }
    rec.update(extra)
    return rec


_DET_TRADE = [_choice("A", "Trade now", "ds-matchup")]
_NAT_TRADE = [_choice("A", "Trade now", "lane-state")]


def _write_bytes(tmp_path: Path, chunks: list[bytes]) -> Path:
    p = tmp_path / "det_coach_shadow.jsonl"
    p.write_bytes(b"".join(chunks))
    return p


def _line(rec) -> bytes:
    return (json.dumps(rec) + "\n").encode("ascii")


# --------------------------------------------------------------------------
# 1. fail-soft decode
# --------------------------------------------------------------------------

def test_non_utf8_line_is_skipped_not_raised(tmp_path):
    good = _line(_rec(_DET_TRADE, _NAT_TRADE))
    bad = b'{"mode": "sr", "my_champion": "\xff\xfe"}\n'
    p = _write_bytes(tmp_path, [good, bad, good])
    report = rpt.build_report(p)
    assert report["coverage"]["total"] == 2
    assert report["domain_alignment"]["aligned"] == 2


def test_non_utf8_line_main_exits_zero(tmp_path, capsys):
    p = _write_bytes(tmp_path, [b"\x93not json\x94\n", _line(_rec(_DET_TRADE, _NAT_TRADE))])
    assert rpt.main(["--path", str(p), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["coverage"]["total"] == 1


def test_load_jsonl_skips_undecodable_line(tmp_path):
    p = _write_bytes(tmp_path, [b'{"a": "\xc3"}\n', b'{"b": 1}\n'])
    assert rpt.load_jsonl(p) == [{"b": 1}]


def test_utf8_bom_first_row_is_kept(tmp_path):
    p = _write_bytes(
        tmp_path,
        [b"\xef\xbb\xbf" + _line(_rec(_DET_TRADE, _NAT_TRADE)),
         _line(_rec(_DET_TRADE, _NAT_TRADE))],
    )
    assert len(rpt.load_jsonl(p)) == 2
    assert rpt.build_report(p)["coverage"]["total"] == 2


def test_deeply_nested_line_is_skipped_not_raised(tmp_path):
    # json.loads raises RecursionError (not ValueError) on deep nesting.
    p = _write_bytes(tmp_path, [b"[" * 200_000 + b"\n", _line(_rec(_DET_TRADE, _NAT_TRADE))])
    assert rpt.build_report(p)["coverage"]["total"] == 1


def test_nul_in_path_is_zeroed(tmp_path):
    # open() raises ValueError (not OSError) on an embedded NUL.
    assert rpt.build_report(tmp_path / "a\x00b.jsonl")["coverage"]["total"] == 0


def test_human_summary_survives_unencodable_names(tmp_path, capsys):
    # A valid JSON row may carry a lone surrogate or a non-ASCII name; the
    # human summary must neither raise nor emit a non-ASCII byte.
    rows = [
        _rec(_DET_TRADE, _NAT_TRADE, my_champion="\ud800"),
        _rec(_DET_TRADE, _NAT_TRADE, my_champion="Kai" + chr(0x2019) + "Sa", mode=chr(0xE9)),
    ]
    p = tmp_path / "det_coach_shadow.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="ascii")
    assert rpt.main(["--path", str(p)]) == 0
    out = capsys.readouterr().out
    assert out.isascii()
    assert "\\ud800" in out
    assert "Kai\\u2019Sa" in out


def test_crlf_and_torn_last_line(tmp_path):
    rec = json.dumps(_rec(_DET_TRADE, _NAT_TRADE)).encode("ascii")
    p = _write_bytes(tmp_path, [rec + b"\r\n", rec + b"\r\n", rec[: len(rec) // 2]])
    assert rpt.build_report(p)["coverage"]["total"] == 2


def test_directory_path_is_zeroed(tmp_path):
    report = rpt.build_report(tmp_path)
    assert report["coverage"]["total"] == 0
    assert report["flip_ready_hint"].startswith("HOLD")


# --------------------------------------------------------------------------
# 2. bounded memory: the report never holds the unread payload
# --------------------------------------------------------------------------

def test_build_report_peak_memory_below_file_size(tmp_path):
    # 600 rows, each with ~16 KB of callouts the report never reads.
    filler = ["x" * 400] * 40
    rows = [
        _line(_rec(_DET_TRADE, _NAT_TRADE, callouts=filler,
                   lead_projection={"curve": filler}))
        for _ in range(600)
    ]
    p = _write_bytes(tmp_path, rows)
    size = p.stat().st_size
    assert size > 8_000_000
    tracemalloc.start()
    try:
        report = rpt.build_report(p)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert report["coverage"]["total"] == 600
    assert report["domain_alignment"]["aligned"] == 600
    # Old path: whole-file str + splitlines copy + full rows, about 3x size.
    assert peak < size // 4, (peak, size)


def test_build_report_equals_full_row_aggregation(tmp_path):
    # The projected stream must give the same report as the summarize_*
    # functions run over the full rows.
    det = _DET_TRADE + [_choice("C", "Buy Bloodthirster", "ds-build")]
    nat = [_choice("A", "Push mid wave", "wave-tempo"),
           _choice("B", "Base now, buy Bloodthirster", "item-spike")]
    rows = [
        _rec(det, nat, mode="aram", my_champion="Jinx", engine_version="1.2.0"),
        _rec(_DET_TRADE, _NAT_TRADE, replaced=False),
        _rec([], _NAT_TRADE),
        _rec(det, [7, _choice("A", "Farm safe", "lane-state")]),
        # No "A" key and a non-dict lead: the A-choice is None, so the slim
        # row must keep the position (dropping the 7 would promote the dict).
        _rec(det, [7, _choice("B", "Trade now", "lane-state")]),
    ]
    p = _write_bytes(tmp_path, [_line(r) for r in rows])
    full = rpt.load_jsonl(p)
    report = rpt.build_report(p)
    assert report["coverage"] == rpt._coverage_block(full)
    assert report["domain_alignment"] == rpt.summarize_domain_alignment(full)
    assert report["within_trade"] == rpt.summarize_within_trade(full)
    assert report["build_overlap"] == rpt.summarize_build_overlap(full)


# --------------------------------------------------------------------------
# 3. both-present means two comparable choice LISTS
# --------------------------------------------------------------------------

def test_non_list_choices_are_not_both_present(tmp_path):
    rows = [
        _rec(_DET_TRADE, _NAT_TRADE),
        _rec("garbage", _NAT_TRADE),
        _rec(_DET_TRADE, {"key": "A", "label": "Trade now"}),
        _rec(_DET_TRADE, ["Trade now"]),
    ]
    p = _write_bytes(tmp_path, [_line(r) for r in rows])
    report = rpt.build_report(p)
    assert report["coverage"]["total"] == 4
    assert report["coverage"]["both_present"] == 1
    assert report["domain_alignment"]["both_present"] == 1
    assert report["domain_alignment"]["alignment_rate"] == 1.0
    assert report["within_trade"]["domain_divergence"] == 0
    assert report["build_overlap"]["det_build_rows"] == 0


def test_replaced_counts_only_true(tmp_path):
    rows = [
        _rec(_DET_TRADE, _NAT_TRADE, replaced=True),
        _rec(_DET_TRADE, _NAT_TRADE, replaced="false"),
        _rec(_DET_TRADE, _NAT_TRADE, replaced=False),
        _rec(_DET_TRADE, _NAT_TRADE, replaced=1),
    ]
    p = _write_bytes(tmp_path, [_line(r) for r in rows])
    assert rpt.build_report(p)["coverage"]["replaced"] == 1


# --------------------------------------------------------------------------
# 4. keywords match at a word start, never mid-word
# --------------------------------------------------------------------------

def test_brush_is_not_a_build_keyword():
    assert rpt.classify_domain("", "Ward the brush") is None
    assert rpt.classify_domain(None, "Hide in brush then trade") == "trade"


def test_rebuild_is_not_a_build_keyword():
    assert rpt.classify_domain("", "Rebuild the wave") is None


def test_build_keywords_still_match_at_word_start():
    assert rpt.classify_domain("", "Buy Bloodthirster") == "build"
    assert rpt.classify_domain("", "Rush Zhonyas") == "build"
    assert rpt.classify_domain("", "Two items done") == "build"


def test_seven_is_not_an_even_hold():
    assert rpt.classify_trade_verdict("Seven stacks - poke now") == "trade"


def test_threshold_and_tactics_are_not_keywords():
    assert rpt.classify_trade_verdict("Threshold reached") is None
    assert rpt.classify_trade_verdict("Tactics") is None


def test_det_vocabulary_unchanged():
    assert rpt.classify_trade_verdict("Trade now") == "trade"
    assert rpt.classify_trade_verdict("Trade even") == "hold"
    assert rpt.classify_trade_verdict("All in now") == "all_in"
    assert rpt.classify_trade_verdict("Back off") == "back_off"
    assert rpt.classify_trade_verdict("Short trades") == "trade"
    assert rpt.classify_trade_verdict("Last-hit CS under tower") == "farm"
    assert rpt.classify_trade_verdict("ALL-IN!") == "all_in"
