"""LBAND1 - tools.live_benchmark_band_report tests.

Pins the fail-soft loader, the summary counts (checkpoint / metric / band /
per-champion), the degenerate top-band-skew flag, the zeroed empty case, and
the main() smoke (human + JSON) over a tmp path.
"""
from __future__ import annotations

import json

from tools import live_benchmark_band_report as rep


def _rec(champ, checkpoint, metric, band, native=None):
    return {
        "ts": "t", "mode": "sr", "champion": champ,
        "game_time_s": 600.0, "cs": 90, "level": 9, "engine_version": "1.x",
        "bands": [{
            "checkpoint": checkpoint, "metric": metric, "display": "CS",
            "value": 90.0, "band": band, "p50": 70.0, "line": "x",
            "source_tag": "live-bench",
        }],
        "native_action": native,
    }


def test_load_jsonl_missing_is_empty(tmp_path):
    assert rep.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_malformed(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"champion":"Annie","bands":[]}\nNOT JSON\n\n', encoding="utf-8")
    rows = rep.load_jsonl(p)
    assert len(rows) == 1
    assert rows[0]["champion"] == "Annie"


def test_summary_counts():
    records = [
        _rec("Tristana", "10", "cs_at_10", "above-p75", native="Farm"),
        _rec("Tristana", "10", "level_at_10", "p50-p75"),
        _rec("Ahri", "15", "cs_at_15", "below-p25"),
    ]
    s = rep.summarize(records)
    assert s["records"] == 3
    assert s["band_fires"] == 3
    assert s["with_native_action"] == 1
    assert s["by_checkpoint"] == {"10": 2, "15": 1}
    assert s["by_metric"] == {"cs_at_10": 1, "level_at_10": 1, "cs_at_15": 1}
    assert s["by_band"]["above-p75"] == 1
    assert s["by_band"]["below-p25"] == 1
    assert s["by_champion"] == {"Tristana": 2, "Ahri": 1}
    # canonical band order present even for zero-count bands
    assert list(s["by_band"])[:4] == list(rep._BAND_ORDER)


def test_empty_is_zeroed():
    s = rep.summarize([])
    assert s["records"] == 0
    assert s["band_fires"] == 0
    assert s["top_band_skew"] is None
    assert s["by_band"] == {k: 0 for k in rep._BAND_ORDER}


def test_degenerate_skew_flag():
    records = [_rec("Tristana", "10", "cs_at_10", "above-p75") for _ in range(5)]
    s = rep.summarize(records)
    assert s["top_band_skew"]["band"] == "above-p75"
    assert s["top_band_skew"]["pct"] == 100.0
    assert "DEGENERATE" in rep._human(s)


def test_main_smoke(tmp_path, capsys):
    p = tmp_path / "s.jsonl"
    p.write_text(json.dumps(_rec("Annie", "10", "cs_at_10", "p25-p50")) + "\n",
                 encoding="utf-8")
    assert rep.main(["--path", str(p), "--json"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["records"] == 1
    # human path
    assert rep.main(["--path", str(p)]) == 0
    assert "LBAND1" in capsys.readouterr().out
