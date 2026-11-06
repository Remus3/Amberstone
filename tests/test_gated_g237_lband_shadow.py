"""Tests for tools/gated_g237_lband_shadow.py (G2-37 PREP, s144 lane gated c42).

Every input is hand-built (RM-906: no real game, match or player id). The tool
is a read-only grader; these tests pin its vocabulary against the production
modules, grade rows written by the production shadow writer itself, and pin the
"no surface" fact the row's READY block rests on.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core import live_benchmark_band as lbb
from core import live_benchmark_band_shadow as shadow
from tools import gated_g237_lband_shadow as g237

ROOT = Path(__file__).resolve().parent.parent
SINCE = "2026-01-02T18:00:00+00:00"


def _band(cp="10", metric="cs_at_10", band="p25-p50", value=70.0):
    return {"checkpoint": cp, "metric": metric, "display": "CS", "value": value,
            "band": band, "p50": 72.0, "line": "x", "source_tag": "live-bench"}


def _row(ts="2026-01-02T18:20:00+00:00", gt=600, cs=70, level=9, bands=None,
         champ="Caitlyn", mode="sr"):
    return {"ts": ts, "mode": mode, "champion": champ, "game_time_s": gt,
            "cs": cs, "level": level, "engine_version": "0.0.0",
            "bands": [_band()] if bands is None else bands, "native_action": None}


def _write(tmp_path, rows, raw=()):
    p = tmp_path / "lband.jsonl"
    lines = [json.dumps(r) for r in rows] + list(raw)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return p


def _grade(path, champion=None):
    return g237.grade(g237.read_lines(path), g237.parse_since(SINCE), champion)


def test_vocabulary_restates_production_constants():
    assert {lab: (c, m) for c, lab, m in lbb._CHECKPOINTS} == g237.CHECKPOINTS
    assert g237.TOLERANCE_S == lbb._TOLERANCE_S
    assert g237.SOURCE_TAG == lbb._SOURCE_TAG
    assert g237.MAX_CHAMPION_CHARS == shadow._MAX_CHAMPION_CHARS
    assert g237.MAX_CS == shadow._MAX_CS
    assert (g237.MIN_LEVEL, g237.MAX_LEVEL) == (shadow._MIN_LEVEL, shadow._MAX_LEVEL)


def test_band_vocab_is_rank_value_output():
    src = (ROOT / "core" / "benchmarks.py").read_text(encoding="utf-8")
    for band in g237.BAND_VOCAB:
        assert f'return "{band}"' in src


def test_sr_mode_keys_restate_production_map():
    from dashboard import _deterministic_coaching as dc
    assert {k for k, v in dc._MODE_KEY_TO_LOWER.items() if v == "sr"} == g237.SR_MODE_KEYS


def test_rows_from_the_production_writer_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, "_LAST_SIG", {})
    p = tmp_path / "lband.jsonl"
    for gt, cs in ((598, 70), (603, 71)):
        assert shadow.log_live_bands("sr", "Caitlyn", bands=[_band(value=float(cs))],
                                     game_time_s=gt, cs=cs, level=9, path=p,
                                     now_iso="2026-01-02T18:20:00+00:00") is not None
    out = _grade(p, champion="Caitlyn")
    assert out["verdict"] == "PASS", out
    assert out["rows"] == 2 and out["duplicates"] == 0


def test_writer_sig_matches_grader_sig(tmp_path, monkeypatch):
    # The writer refuses a write whose sig equals the last one, so two
    # consecutive rows the grader calls duplicates can only come from a writer
    # that lost its lock. Pin that the two sigs agree in both directions.
    monkeypatch.setattr(shadow, "_LAST_SIG", {})
    p = tmp_path / "lband.jsonl"
    kw = dict(bands=[_band()], level=9, path=p, now_iso="2026-01-02T18:20:00+00:00")
    assert shadow.log_live_bands("sr", "Caitlyn", game_time_s=600, cs=70, **kw) is not None
    # Same 5 s bucket, same values: the writer refuses.
    assert shadow.log_live_bands("sr", "Caitlyn", game_time_s=603, cs=70, **kw) is None
    # Next bucket: the writer appends, and the grader sees two distinct sigs.
    assert shadow.log_live_bands("sr", "Caitlyn", game_time_s=605, cs=70, **kw) is not None
    a, b = (json.loads(x) for x in p.read_text(encoding="utf-8").splitlines())
    assert g237.sig(a) != g237.sig(b)
    assert g237.sig(a) == g237.sig({**a, "game_time_s": 603})
    p.write_text("\n".join([json.dumps(a), json.dumps(a), json.dumps(b)]) + "\n",
                 encoding="utf-8", newline="\n")
    out = _grade(p)
    assert out["verdict"] == "FAIL" and out["duplicates"] == 1


def test_no_rows_since_is_no_result(tmp_path):
    p = _write(tmp_path, [_row(ts="2026-01-02T17:59:59+00:00")])
    assert _grade(p)["verdict"] == "NO_RESULT"


def test_since_compares_as_time_not_text(tmp_path):
    # 13:30-05:00 is 18:30Z, after SINCE; as text it sorts before it.
    p = _write(tmp_path, [_row(ts="2026-01-02T13:30:00-05:00")])
    assert _grade(p)["verdict"] == "PASS"


def test_naive_since_is_refused():
    with pytest.raises(ValueError):
        g237.parse_since("2026-01-02T18:00:00")


@pytest.mark.parametrize("row, needle", [
    (_row(gt=700), "outside the 10:00 window"),
    (_row(mode="aram"), "not SR-family"),
    (_row(level=0), "level 0"),
    (_row(cs=True), "cs True"),
    (_row(bands=[_band(band="top")]), "band 'top'"),
    (_row(bands=[_band(cp="15", metric="cs_at_10", value=1.0)], gt=900), "not at checkpoint 15"),
    (_row(bands=[]), "no bands"),
    (_row(champ=" Caitlyn"), "champion"),
])
def test_contract_breaks_fail(tmp_path, row, needle):
    out = _grade(_write(tmp_path, [row]))
    assert out["verdict"] == "FAIL"
    assert any(needle in r for r in out["reasons"]), out["reasons"]


def test_only_checkpoint_15_fails(tmp_path):
    p = _write(tmp_path, [_row(gt=900, bands=[_band(cp="15", metric="cs_at_15")])])
    out = _grade(p)
    assert out["verdict"] == "FAIL" and "no band at checkpoint 10" in out["reasons"]


def test_non_strict_json_row_fails(tmp_path):
    raw = '{"ts": "2026-01-02T18:21:00+00:00", "mode": "sr", "champion": "Caitlyn", ' \
          '"game_time_s": NaN, "cs": 70, "level": 9, "bands": []}'
    out = _grade(_write(tmp_path, [_row()], raw=[raw]))
    assert out["verdict"] == "FAIL"
    assert any("not strict JSON" in r for r in out["reasons"])


@pytest.mark.parametrize("raw", [
    '{"ts": "2026-01-02T18:21:00+00:00", "mode": "sr", "champ',  # torn append
    '[1, 2]',                                                    # not an object
    '{"mode": "sr", "champion": "Caitlyn"}',                     # no ts
])
def test_unparseable_line_in_window_fails(tmp_path, raw):
    out = _grade(_write(tmp_path, [_row()], raw=[raw]))
    assert out["verdict"] == "FAIL"
    assert any("unparseable" in r for r in out["reasons"]), out["reasons"]


def test_unparseable_line_before_window_is_not_charged(tmp_path):
    old = _row(ts="2026-01-02T17:00:00+00:00")
    p = tmp_path / "lband.jsonl"
    p.write_text("\n".join(["{torn", json.dumps(old), json.dumps(_row())]) + "\n",
                 encoding="utf-8", newline="\n")
    assert _grade(p)["verdict"] == "PASS"


def _lines(tmp_path, items):
    p = tmp_path / "lband.jsonl"
    p.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in items) + "\n",
                 encoding="utf-8", newline="\n")
    return p


def test_later_old_row_does_not_excuse_a_torn_line(tmp_path):
    old = _row(ts="2026-01-02T17:00:00+00:00")
    out = _grade(_lines(tmp_path, [_row(), "{torn", old]))
    assert out["verdict"] == "FAIL"
    assert any("unparseable" in r for r in out["reasons"]), out["reasons"]
    assert any("step back in time" in r for r in out["reasons"]), out["reasons"]


def test_ts_stepping_backward_in_window_fails(tmp_path):
    later = _row(ts="2026-01-02T18:30:00+00:00", gt=605, cs=71, bands=[_band(value=71.0)])
    out = _grade(_lines(tmp_path, [later, _row()]))
    assert out["verdict"] == "FAIL"
    assert any("step back in time" in r for r in out["reasons"]), out["reasons"]
    old = _row(ts="2026-01-02T17:00:00+00:00")
    assert _grade(_lines(tmp_path, [_row(), old]))["verdict"] == "FAIL"


def test_band_value_must_be_the_rows_own_cs(tmp_path):
    out = _grade(_write(tmp_path, [_row(cs=70, bands=[_band(value=71.0)])]))
    assert out["verdict"] == "FAIL"
    assert any("is not the row's 70" in r for r in out["reasons"]), out["reasons"]
    lv = _band(metric="level_at_10", value=9.0)
    assert _grade(_write(tmp_path, [_row(level=9, bands=[_band(value=70.0), lv])]))[
        "verdict"] == "PASS"


def test_foreign_champion_fails(tmp_path):
    out = _grade(_write(tmp_path, [_row(champ="Jinx")]), champion="Caitlyn")
    assert out["verdict"] == "FAIL"


def test_cli_exit_codes(tmp_path, capsys):
    good = _write(tmp_path, [_row()])
    assert g237.main(["shadow", str(good), "--since", SINCE]) == 0
    assert g237.main(["shadow", str(good), "--since", "2027-01-01T00:00:00+00:00"]) == 3
    assert g237.main(["shadow", str(tmp_path / "missing.jsonl"), "--since", SINCE]) == 2
    assert g237.main(["shadow", str(good), "--since", SINCE, "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["verdict"] == "PASS"


def test_no_surface_reads_a_band_yet():
    """The READY block's premise: nothing outside the shadow path renders a band.

    When a surface ships, this fails on purpose - the G2-37 eyeball half then
    becomes live-drainable and the READY block must be rewritten."""
    # The tracked UI surfaces: the dashboard (web/), the Electron overlay shell
    # (rc-shell/) and the legacy overlay.py. git ls-files keeps node_modules out.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    listed = subprocess.run(
        ["git", "ls-files", "--", "web", "rc-shell", "overlay.py"], cwd=ROOT,
        capture_output=True, text=True, check=True, creationflags=flags,
    ).stdout.split("\n")
    files = [ROOT / p for p in listed if p.strip()]
    # Positive control: an empty or partial universe would pass vacuously.
    rel = {f.relative_to(ROOT).as_posix() for f in files}
    assert "overlay.py" in rel
    assert any(p.startswith("web/js/") for p in rel)
    assert any(p.startswith("rc-shell/src/") for p in rel)
    hits = []
    for f in files:
        if f.suffix in {".js", ".mjs", ".cjs", ".html", ".css", ".py"} and f.is_file():
            text = f.read_text(encoding="utf-8", errors="replace")
            if "live-bench" in text or "live_benchmark_band" in text:
                hits.append(f.relative_to(ROOT).as_posix())
    assert hits == []
    users = []
    for base in ("dashboard", "coaches", "modes", "app", "core"):
        for f in (ROOT / base).rglob("*.py"):
            if "live_benchmark_band" in f.read_text(encoding="utf-8", errors="replace"):
                users.append(f.relative_to(ROOT).as_posix())
    # Every served-code file that names the bander is the shadow path.
    assert sorted(users) == [
        "core/live_benchmark_band_shadow.py",
        "dashboard/_deterministic_coaching.py",
        "dashboard/_state_builder.py",
    ]
