"""Hermetic tests for tools/det_coach_shadow_report.py.

The real data/det_coach_shadow.jsonl is gitignored (clean-checkout lesson: a
test reading it passes on dev and fails on CI), so every test builds mock
records in tmp_path. Assertions are on COMPUTED quantities (rates, counts), not
on brittle string equality of the human dump.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.det_coach_shadow_report as rpt


def _choice(key, label, source_tag):
    return {
        "key": key,
        "label": label,
        "expected_outcome": "",
        "confidence": "mid",
        "source_tag": source_tag,
        "trigger": "",
        "rebranch_when": "",
        "rebranch_to": "",
    }


def _rec(
    *,
    mode="sr",
    champ="Caitlyn",
    enemies=None,
    det=None,
    native=None,
    replaced=True,
    engine="1.149.0",
):
    return {
        "ts": "2026-06-23T00:00:00+00:00",
        "mode": mode,
        "my_champion": champ,
        "enemy_champions": enemies or ["Galio"],
        "game_time_s": 600.0,
        "level": 9,
        "item_count": 3,
        "engine_version": engine,
        "replaced": replaced,
        "det_choices": det or [],
        "callouts": [],
        "lead_projection": {},
        "native_choices": native or [],
    }


def _write(tmp_path: Path, records) -> Path:
    p = tmp_path / "det_coach_shadow.jsonl"
    with p.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return p


# Reusable choice fragments mirroring the live vocabulary.
_DET_TRADE_A = _choice("A", "Trade now", "ds-matchup")
_DET_FARM_A = _choice("A", "Farm safe", "ds-matchup")
_DET_BUILD_C = _choice("C", "Buy Bloodthirster", "ds-build")
_NAT_TRADE_A = _choice("A", "Trade now", "lane-state")
_NAT_FARM_A = _choice("A", "Farm safe", "lane-state")
_NAT_MACRO_A = _choice("A", "Push mid wave", "wave-tempo")
_NAT_BUILD_SPIKE = _choice("B", "Base now, buy Bloodthirster", "item-spike")


# --------------------------------------------------------------------------
# classify_domain unit cases
# --------------------------------------------------------------------------
def test_classify_domain_trade_tag():
    assert rpt.classify_domain("ds-matchup", "Trade now") == "trade"
    assert rpt.classify_domain("lane-state", "Trade now") == "trade"


def test_classify_domain_build_tag_and_item_substring():
    assert rpt.classify_domain("ds-build", "Buy X") == "build"
    assert rpt.classify_domain("item-spike", "Base now, buy X") == "build"
    assert rpt.classify_domain("item-timing", "rush X") == "build"


def test_classify_domain_macro_catchall():
    assert rpt.classify_domain("wave-tempo", "Push mid") == "macro"
    assert rpt.classify_domain("objective-call", "Take drake") == "macro"
    assert rpt.classify_domain("ward-timing", "Ward pit") == "macro"


def test_classify_domain_blank_is_none():
    assert rpt.classify_domain("", "") is None
    assert rpt.classify_domain(None, None) is None


def test_classify_domain_label_fallback_when_tag_blank():
    # source_tag missing -> small label-keyword fallback.
    assert rpt.classify_domain("", "Trade now") == "trade"
    assert rpt.classify_domain(None, "Buy Bloodthirster") == "build"
    assert rpt.classify_domain("", "Sip tea quietly") is None


# --------------------------------------------------------------------------
# classify_trade_verdict unit cases
# --------------------------------------------------------------------------
def test_classify_trade_verdict_basics():
    assert rpt.classify_trade_verdict("Trade now") == "trade"
    assert rpt.classify_trade_verdict("All in now") == "all_in"
    assert rpt.classify_trade_verdict("Back off") == "back_off"
    assert rpt.classify_trade_verdict("Farm safe") == "farm"
    assert rpt.classify_trade_verdict("Trade even") == "hold"


def test_classify_trade_verdict_unclassifiable_is_none():
    assert rpt.classify_trade_verdict("") is None
    assert rpt.classify_trade_verdict(None) is None
    assert rpt.classify_trade_verdict("ponder the void") is None


# --------------------------------------------------------------------------
# Aligned + agreeing trade-vs-trade row
# --------------------------------------------------------------------------
def test_trade_vs_trade_agrees(tmp_path):
    p = _write(tmp_path, [_rec(det=[_DET_TRADE_A], native=[_NAT_TRADE_A])])
    report = rpt.build_report(p)
    al = report["domain_alignment"]
    wt = report["within_trade"]
    assert al["both_present"] == 1
    assert al["aligned"] == 1
    assert al["alignment_rate"] == 1.0
    assert wt["comparable"] == 1
    assert wt["agree"] == 1
    assert wt["agreement_rate"] == 1.0
    assert wt["domain_divergence"] == 0


# --------------------------------------------------------------------------
# Aligned but DISAGREEING trade-vs-trade row
# --------------------------------------------------------------------------
def test_trade_vs_trade_disagrees(tmp_path):
    # det says Trade now (trade), native says Farm safe (farm) - same domain,
    # different verdict -> aligned but within-trade disagreement.
    p = _write(tmp_path, [_rec(det=[_DET_TRADE_A], native=[_NAT_FARM_A])])
    report = rpt.build_report(p)
    al = report["domain_alignment"]
    wt = report["within_trade"]
    assert al["aligned"] == 1  # still same domain
    assert wt["comparable"] == 1
    assert wt["agree"] == 0
    assert wt["agreement_rate"] == 0.0
    assert wt["domain_divergence"] == 0
    mism = [c for c in wt["confusion"] if not c["agree"]]
    assert any(c["det"] == "trade" and c["native"] == "farm" for c in mism)


# --------------------------------------------------------------------------
# Domain-divergent row - the de-bias guard
# --------------------------------------------------------------------------
def test_domain_divergent_row_is_not_a_within_trade_disagreement(tmp_path):
    # det A ds-matchup (trade) vs native A wave-tempo "Push mid wave" (macro).
    # This MUST count as domain_divergence and NOT drag down the within-trade
    # agreement denominator (cycle-53 false-0% de-bias).
    p = _write(tmp_path, [_rec(det=[_DET_TRADE_A], native=[_NAT_MACRO_A])])
    report = rpt.build_report(p)
    al = report["domain_alignment"]
    wt = report["within_trade"]
    assert al["both_present"] == 1
    assert al["aligned"] == 0  # trade != macro
    assert al["alignment_rate"] == 0.0
    assert al["native_domain_dist"].get("macro") == 1
    # The key assertion: excluded from within-trade, not a disagreement.
    assert wt["domain_divergence"] == 1
    assert wt["comparable"] == 0
    assert wt["agree"] == 0
    assert wt["agreement_rate"] == 0.0


def test_divergent_row_does_not_dilute_within_trade(tmp_path):
    # One agreeing trade pair + one domain-divergent row. Within-trade rate
    # must stay 1.0 (1/1), NOT 1/2 - the divergent row is excluded.
    p = _write(
        tmp_path,
        [
            _rec(det=[_DET_TRADE_A], native=[_NAT_TRADE_A]),
            _rec(det=[_DET_TRADE_A], native=[_NAT_MACRO_A]),
        ],
    )
    report = rpt.build_report(p)
    wt = report["within_trade"]
    al = report["domain_alignment"]
    assert wt["comparable"] == 1
    assert wt["agreement_rate"] == 1.0
    assert wt["domain_divergence"] == 1
    # domain alignment is over BOTH rows: 1 aligned of 2.
    assert al["both_present"] == 2
    assert al["aligned"] == 1
    assert al["alignment_rate"] == 0.5


# --------------------------------------------------------------------------
# Build-domain overlap row
# --------------------------------------------------------------------------
def test_build_overlap_counted(tmp_path):
    # det C "Buy Bloodthirster" vs native item-spike naming Bloodthirster.
    det = [_DET_TRADE_A, _DET_BUILD_C]
    native = [_NAT_MACRO_A, _NAT_BUILD_SPIKE]
    p = _write(tmp_path, [_rec(det=det, native=native)])
    report = rpt.build_report(p)
    bo = report["build_overlap"]
    assert bo["det_build_rows"] == 1
    assert bo["native_build_rows"] == 1
    assert bo["comparable"] == 1
    assert bo["overlap"] == 1
    assert bo["overlap_rate"] == 1.0


def test_build_no_overlap_when_items_differ(tmp_path):
    det = [_DET_TRADE_A, _DET_BUILD_C]  # Bloodthirster
    native = [
        _NAT_MACRO_A,
        _choice("B", "Base now, buy Kraken Slayer", "item-spike"),
    ]
    p = _write(tmp_path, [_rec(det=det, native=native)])
    report = rpt.build_report(p)
    bo = report["build_overlap"]
    assert bo["comparable"] == 1
    assert bo["overlap"] == 0
    assert bo["overlap_rate"] == 0.0


# --------------------------------------------------------------------------
# Coverage math
# --------------------------------------------------------------------------
def test_coverage_math(tmp_path):
    records = [
        _rec(mode="sr", det=[_DET_TRADE_A], native=[_NAT_TRADE_A]),
        _rec(mode="sr", det=[_DET_TRADE_A], native=[_NAT_MACRO_A]),
        _rec(mode="aram", det=[_DET_TRADE_A], native=[]),  # not both-present
        _rec(mode="aram", det=[], native=[_NAT_MACRO_A], replaced=False),
    ]
    p = _write(tmp_path, records)
    cov = rpt.build_report(p)["coverage"]
    assert cov["total"] == 4
    assert cov["replaced"] == 3  # three records have replaced=True
    assert cov["both_present"] == 2
    assert cov["by_mode"]["sr"] == {"total": 2, "both": 2}
    assert cov["by_mode"]["aram"] == {"total": 2, "both": 0}
    assert cov["by_champion_both_top15"].get("Caitlyn") == 2


def test_engine_version_distribution(tmp_path):
    records = [
        _rec(engine="1.149.0", det=[_DET_TRADE_A], native=[_NAT_TRADE_A]),
        _rec(engine="1.149.0", det=[_DET_TRADE_A], native=[_NAT_TRADE_A]),
        _rec(engine="1.151.0", det=[_DET_TRADE_A], native=[_NAT_TRADE_A]),
    ]
    p = _write(tmp_path, records)
    cov = rpt.build_report(p)["coverage"]
    assert cov["by_engine_version"] == {"1.149.0": 2, "1.151.0": 1}


# --------------------------------------------------------------------------
# Fail-soft
# --------------------------------------------------------------------------
def test_missing_file_zeroed_no_exception(tmp_path):
    missing = tmp_path / "does_not_exist.jsonl"
    report = rpt.build_report(missing)  # must not raise
    assert report["coverage"]["total"] == 0
    assert report["coverage"]["both_present"] == 0
    assert report["domain_alignment"]["both_present"] == 0
    assert report["domain_alignment"]["alignment_rate"] == 0.0
    assert report["within_trade"]["comparable"] == 0
    assert report["build_overlap"]["comparable"] == 0
    assert "HOLD" in report["flip_ready_hint"]


def test_malformed_line_skipped(tmp_path):
    p = tmp_path / "det_coach_shadow.jsonl"
    good = _rec(det=[_DET_TRADE_A], native=[_NAT_TRADE_A])
    with p.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(good) + "\n")
        fh.write("{ this is not valid json\n")  # skipped
        fh.write("\n")  # blank skipped
        fh.write("[1, 2, 3]\n")  # valid json but not a dict -> skipped
    records = rpt.load_jsonl(p)
    assert len(records) == 1
    report = rpt.build_report(p)
    assert report["coverage"]["total"] == 1


# --------------------------------------------------------------------------
# flip_ready_hint thresholds
# --------------------------------------------------------------------------
def test_flip_hint_holds_on_low_alignment(tmp_path):
    # All rows domain-divergent -> alignment 0% -> HOLD on alignment.
    records = [
        _rec(det=[_DET_TRADE_A], native=[_NAT_MACRO_A]) for _ in range(10)
    ]
    p = _write(tmp_path, records)
    hint = rpt.build_report(p)["flip_ready_hint"]
    assert hint.startswith("HOLD")
    assert "alignment" in hint


def test_flip_hint_holds_on_small_trade_sample(tmp_path):
    # Perfectly aligned + agreeing, but only a few trade rows -> HOLD on sample.
    records = [
        _rec(det=[_DET_TRADE_A], native=[_NAT_TRADE_A]) for _ in range(5)
    ]
    p = _write(tmp_path, records)
    report = rpt.build_report(p)
    assert report["domain_alignment"]["alignment_rate"] == 1.0
    hint = report["flip_ready_hint"]
    assert hint.startswith("HOLD")
    assert "sample too small" in hint


def test_main_runs_json_and_human(tmp_path, capsys):
    p = _write(tmp_path, [_rec(det=[_DET_TRADE_A], native=[_NAT_TRADE_A])])
    assert rpt.main(["--path", str(p), "--json"]) == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["schema"] == "det_coach_shadow_report/v1"
    assert rpt.main(["--path", str(p)]) == 0
    human = capsys.readouterr().out
    assert "[coverage]" in human
    assert "[domain-alignment]" in human


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
