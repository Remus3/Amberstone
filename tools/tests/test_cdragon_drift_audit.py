# arch: offline tests for ds_cdragon_drift_audit | section=tools-tests | frozen=no
"""Offline unit tests for ``tools/ds_cdragon_drift_audit.py``.

No network, no disk I/O. All fixtures are inline dicts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import ds_cdragon_drift_audit as A  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(champion, slot, field, meraki, cdragon, kind="changed"):
    delta = None
    if meraki and cdragon:
        delta = round(cdragon[0] - meraki[0], 6)
    return {
        "champion": champion,
        "slot": slot,
        "field": field,
        "meraki": meraki,
        "cdragon": cdragon,
        "delta": delta,
        "kind": kind,
    }


# ---------------------------------------------------------------------------
# classify_row: one test per class
# ---------------------------------------------------------------------------


class TestExplosion:
    def test_ap_pct_huge_value(self):
        row = _row("Lux", "Q", "ap_pct", [0.6, 0.75, 0.9], [7600.0, 7600.0, 7600.0])
        assert A.classify_row(row) == "explosion"

    def test_base_huge_value(self):
        row = _row("Lux", "Q", "base", [200.0, 250.0], [6000.0, 6000.0])
        assert A.classify_row(row) == "explosion"

    def test_base_below_threshold_not_explosion(self):
        # base <= 5000 and not _pct should NOT be explosion
        row = _row("Lux", "Q", "base", [200.0, 250.0], [250.0, 300.0])
        assert A.classify_row(row) != "explosion"


class TestOffByOneResidue:
    # meraki [80,120,160,200,240], cdragon [40,80,120,160,200]
    # cdragon[i] == meraki[i-1] for i in 1..4 (4 out of 4 overlap positions)
    def test_classic_rank_shift(self):
        row = _row(
            "Ahri", "E", "ap_pct",
            [80.0, 120.0, 160.0, 200.0, 240.0],
            [40.0, 80.0, 120.0, 160.0, 200.0],
        )
        assert A.classify_row(row) == "off_by_one_residue"

    def test_no_shift_not_flagged(self):
        row = _row(
            "Ahri", "E", "ap_pct",
            [80.0, 120.0, 160.0, 200.0, 240.0],
            [80.0, 120.0, 160.0, 200.0, 240.0],
        )
        # identical arrays -> clean balance drift (delta 0 means no real change,
        # but the function still classifies; won't be off_by_one)
        assert A.classify_row(row) != "off_by_one_residue"


class TestLargeDivergence:
    # meraki [40,55,70], cdragon [120,165,210] -> ratio 3.0x -> large_divergence
    def test_3x_divergence(self):
        row = _row("Zed", "W", "total_ad_pct",
                   [40.0, 55.0, 70.0], [120.0, 165.0, 210.0])
        assert A.classify_row(row) == "large_divergence"

    def test_half_ratio_divergence(self):
        # cdragon is 0.33x of meraki -> <= 0.5x
        row = _row("Zed", "W", "total_ad_pct",
                   [120.0, 165.0, 210.0], [40.0, 55.0, 70.0])
        assert A.classify_row(row) == "large_divergence"

    def test_modest_ratio_not_large(self):
        # 1.15x - not a large divergence
        row = _row("Zed", "W", "total_ad_pct",
                   [65.0, 65.0, 65.0, 65.0, 65.0],
                   [75.0, 75.0, 75.0, 75.0, 75.0])
        assert A.classify_row(row) != "large_divergence"


class TestRankShapeMismatch:
    # meraki len3, cdragon len5, not benign (cdragon[:3] != meraki)
    def test_non_benign_length_difference(self):
        # meraki len3, cdragon len5, not a benign trailing-extra (prefix doesn't match),
        # and ratio 105/100 = 1.05x so large_divergence does NOT fire first
        row = _row("Darius", "Q", "base",
                   [100.0, 110.0, 120.0],
                   [105.0, 115.0, 125.0, 135.0, 145.0])
        assert A.classify_row(row) == "rank_shape_mismatch"

    def test_benign_trailing_extra_not_mismatch(self):
        # cdragon is meraki + 1 extra rank, prefix matches exactly
        row = _row("Darius", "Q", "base",
                   [80.0, 120.0, 160.0, 200.0, 240.0],
                   [80.0, 120.0, 160.0, 200.0, 240.0, 280.0])
        assert A.classify_row(row) == "clean_balance_drift"

    def test_benign_trailing_extra_by_2_not_mismatch(self):
        row = _row("Darius", "Q", "base",
                   [80.0, 120.0, 160.0],
                   [80.0, 120.0, 160.0, 200.0, 240.0])
        assert A.classify_row(row) == "clean_balance_drift"

    def test_ult_len6_vs_len3_trailing_extra_is_benign(self):
        # The ult case: CDragon resolves a length-6 array (len-7 live bin minus the
        # trimmed leading rank-0); a length-3 meraki ult block carries +3 unread
        # trailing ranks (ranks 4-6 do not exist). Prefix matches -> benign, NOT a
        # shape mismatch (no ability rank beyond 3 is ever read for an ult).
        row = _row("Lux", "R", "base",
                   [300.0, 400.0, 500.0],
                   [300.0, 400.0, 500.0, 600.0, 700.0, 800.0])
        assert A.classify_row(row) == "clean_balance_drift"


class TestCleanBalanceDrift:
    def test_simple_ratio_nudge(self):
        row = _row("Lux", "Q", "ap_pct",
                   [65.0, 65.0, 65.0, 65.0, 65.0],
                   [75.0, 75.0, 75.0, 75.0, 75.0])
        assert A.classify_row(row) == "clean_balance_drift"


# ---------------------------------------------------------------------------
# audit_drift: counts + suspects + JSON-serialisable
# ---------------------------------------------------------------------------


class TestAuditDrift:
    def _build_drift(self):
        return {
            "summary": {},
            "rows": [
                # explosion
                _row("Lux", "Q", "ap_pct",
                     [0.6], [7600.0], "changed"),
                # off_by_one_residue
                _row("Ahri", "E", "ap_pct",
                     [80.0, 120.0, 160.0, 200.0, 240.0],
                     [40.0, 80.0, 120.0, 160.0, 200.0], "changed"),
                # large_divergence
                _row("Zed", "W", "total_ad_pct",
                     [40.0, 55.0, 70.0], [120.0, 165.0, 210.0], "changed"),
                # rank_shape_mismatch - prefix ratio 1.05x so large_divergence won't fire
                _row("Darius", "Q", "base",
                     [100.0, 110.0, 120.0],
                     [105.0, 115.0, 125.0, 135.0, 145.0], "changed"),
                # clean_balance_drift
                _row("Lux", "Q", "ap_pct",
                     [65.0, 65.0, 65.0, 65.0, 65.0],
                     [75.0, 75.0, 75.0, 75.0, 75.0], "changed"),
                # only_cdragon - should be ignored for classification counts
                _row("NewChamp", "Q", "ap_pct", None, [0.5, 0.6], "only_cdragon"),
                # meraki_only - should be ignored
                _row("OldChamp", "R", "base", [100.0], None, "meraki_only"),
            ],
        }

    def test_counts(self):
        result = A.audit_drift(self._build_drift())
        s = result["summary"]
        assert s["n_changed"] == 5
        assert s["explosion"] == 1
        assert s["off_by_one_residue"] == 1
        assert s["large_divergence"] == 1
        assert s["rank_shape_mismatch"] == 1
        assert s["clean_balance_drift"] == 1
        assert s["n_suspect"] == 4

    def test_suspects_list(self):
        result = A.audit_drift(self._build_drift())
        suspects = result["suspects"]
        assert len(suspects) == 4
        classes = {s["class"] for s in suspects}
        assert "clean_balance_drift" not in classes
        assert "explosion" in classes

    def test_suspect_fields_present(self):
        result = A.audit_drift(self._build_drift())
        for s in result["suspects"]:
            for key in ("champion", "slot", "field", "class", "meraki", "cdragon", "delta"):
                assert key in s, f"missing key {key!r} in suspect"

    def test_json_serialisable_ascii(self):
        result = A.audit_drift(self._build_drift())
        encoded = json.dumps(result, ensure_ascii=True)
        # must not raise and must be ASCII
        assert isinstance(encoded, str)
        encoded.encode("ascii")  # raises if non-ASCII slipped through


# ---------------------------------------------------------------------------
# ASCII hygiene on the tool source itself
# ---------------------------------------------------------------------------


class TestAsciiHygiene:
    def test_no_em_or_en_dashes_in_source(self):
        src = Path(_TOOLS) / "ds_cdragon_drift_audit.py"
        text = src.read_text(encoding="utf-8")
        bad = [ch for ch in text if ord(ch) in (0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D)]
        assert not bad, f"non-ASCII punctuation found in source: {bad}"
