# arch: tests for the R126 fuse_reads shadow-first wiring in the vision tick | section=tests | frozen=no
"""tests/test_fusion_shadow_wiring.py - Lane E S6 fusion shadow wiring.

Covers the SHADOW-FIRST wiring of core.vision_fusion.fuse_reads into
GameVisionReader.read_tiered (modes/shared_vision.py) - the ARAM/Arena
coach vision tick chokepoint (aram_coach._run_vision -> read_tiered;
arena_coach the same). Contract under test:

- When BOTH sources exist (liveclient cache snapshot + CV reads), one
  fusion record (inputs + fused result with confidences + disagreement
  flag) is appended to data/fusion_shadow.jsonl (RC_FUSION_SHADOW_PATH
  override), sibling of the R101 data/ocr_shadow.jsonl lane.
- The coach-visible dict returned by read_tiered is IDENTICAL with the
  shadow wiring active - fusion is log-only, never served.
- The hook is fail-soft: a raise anywhere inside (fusion, writer path)
  is swallowed; the coach path is unaffected.
- The liveclient snapshot is read passively (no cache auto-start): no
  new thread, no new poll from the shadow lane.

No live game needed: _capture_screen and read_or_escalate are stubbed,
and the liveclient cache module snapshot is monkeypatched directly.
"""
from __future__ import annotations

import json
import time

import core.liveclient_cache as lcc
import core.vision_fusion
import core.vision_routing as vr
import modes.shared_vision as sv


def _lc_allgamedata(gold=3200.4, level=9, kills=1, deaths=2, assists=3,
                    cs=42):
    """Minimal /allgamedata shape: activePlayer + matching allPlayers row
    (summonerName match path, scores per the Live Client API)."""
    return {
        "activePlayer": {
            "summonerName": "Moon#NA1",
            "championName": "Lux",
            "currentGold": gold,
            "level": level,
        },
        "allPlayers": [
            {
                "summonerName": "Moon#NA1",
                "championName": "Lux",
                "team": "ORDER",
                "scores": {"kills": kills, "deaths": deaths,
                           "assists": assists, "creepScore": cs,
                           "wardScore": 0.0},
            },
        ],
    }


def _set_lc_snapshot(monkeypatch, data, age_s=0.0):
    """Pin the liveclient cache module snapshot (passive read target)."""
    ts = (time.time() - age_s) if data is not None else 0.0
    snap = lcc.Snapshot(data=data, ts=ts, fetched_at=time.time())
    monkeypatch.setattr(lcc, "_snapshot", snap)


def _mk_reader(monkeypatch, cv_result):
    """Reader wired like aram_coach._run_vision (no Anthropic key needed):
    capture + tiered routing stubbed to return a fixed CV dict."""
    monkeypatch.setattr(sv, "_capture_screen", lambda: "dummyb64")

    def fake_read_or_escalate(img_b64, fields, *, escalate_fn=None,
                              validators=None, shadow_fields=None):
        return dict(cv_result)

    monkeypatch.setattr(vr, "read_or_escalate", fake_read_or_escalate)
    reader = sv.GameVisionReader.__new__(sv.GameVisionReader)
    reader.TIERED_FIELDS = list(cv_result)
    reader.SHADOW_FIELDS = []
    reader.TIERED_VALIDATORS = {}
    return reader


def _read_records(path):
    return [json.loads(ln) for ln in
            path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_agree_record_written_lc_wins_fresh(monkeypatch, tmp_path):
    # Healthy LC + CV agree: record written, fresh LC wins every shared
    # field at confidence 1.0, disagreement False.
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata())
    cv = {"gold": 3200, "level": 9, "cs": 42, "kda": "1/2/3"}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
    recs = _read_records(shadow)
    assert len(recs) == 1
    rec = recs[0]
    assert set(rec) == {"ts", "live_stale", "live_client", "cv_reads",
                        "fused", "disagree_fields", "disagreement"}
    assert rec["live_stale"] is False
    assert rec["live_client"] == {"gold": 3200, "level": 9, "cs": 42,
                                  "kda": "1/2/3"}
    assert rec["cv_reads"] == cv
    assert rec["fused"]["gold"] == {"value": 3200, "source": "liveclient",
                                    "confidence": 1.0}
    assert "lc_exact:gold" in rec["fused"]["_notes"]
    assert rec["disagree_fields"] == []
    assert rec["disagreement"] is False


def test_disagreement_flagged_and_listed(monkeypatch, tmp_path):
    # CV and LC disagree on gold: flag set, field listed, fresh LC still
    # wins in the fused result (served dict untouched either way).
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata(gold=3200.4))
    cv = {"gold": 9999, "level": 9, "cs": 42, "kda": "1/2/3"}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
    rec = _read_records(shadow)[0]
    assert rec["disagreement"] is True
    assert rec["disagree_fields"] == ["gold"]
    assert rec["fused"]["gold"]["source"] == "liveclient"
    assert rec["fused"]["gold"]["value"] == 3200


def test_stale_lc_cv_override_recorded(monkeypatch, tmp_path):
    # LC snapshot aged past the coach's 12s bound: live_stale True and the
    # default-confidence CV read (0.7 >= 0.6) overrides the stale LC value.
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata(gold=3200.4), age_s=30.0)
    cv = {"gold": 3450, "level": 9, "cs": 42, "kda": "1/2/3"}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
    rec = _read_records(shadow)[0]
    assert rec["live_stale"] is True
    assert rec["fused"]["gold"] == {
        "value": 3450, "source": "cv",
        "confidence": core.vision_fusion.CV_DEFAULT_CONF,
    }
    assert "cv_override_stale:gold" in rec["fused"]["_notes"]


def test_cv_only_fields_recorded_as_cv_fallback(monkeypatch, tmp_path):
    # Fields LC structurally lacks (fight_state) flow through as cv
    # fallback entries in the fused record.
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata())
    cv = {"gold": 3200, "fight_state": "poke"}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
    rec = _read_records(shadow)[0]
    assert rec["fused"]["fight_state"]["source"] == "cv"
    assert "cv_fallback:fight_state" in rec["fused"]["_notes"]


def test_served_output_identical_with_fusion_shadow_active(monkeypatch,
                                                           tmp_path):
    # THE served-output proof: with the shadow lane fully active (LC
    # present, disagreement recorded), the coach-visible dict is exactly
    # the postprocessed CV dict - byte-identical serve, log-only fusion.
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata())
    cv = {"gold": 1111, "level": 3, "cs": 7, "kda": "0/0/0",
          "is_augment_select": True}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    # Expected = CV dict + the pre-existing _postprocess augment alias
    # (served behavior that predates the fusion wiring).
    expected = dict(cv)
    expected["augment_select"] = True
    assert out == expected
    assert len(_read_records(shadow)) == 1


def test_fusion_raise_inside_hook_never_breaks_coach_path(monkeypatch,
                                                          tmp_path):
    # fuse_reads never raises by contract; force a raise anyway and prove
    # the hook swallows it - served dict unchanged, no partial record.
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata())

    def boom(*a, **kw):
        raise RuntimeError("fusion exploded")

    monkeypatch.setattr(core.vision_fusion, "fuse_reads", boom)
    cv = {"gold": 3200, "level": 9}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
    assert not shadow.exists()


def test_no_liveclient_data_writes_no_record(monkeypatch, tmp_path):
    # Both sources must exist: empty cache snapshot -> no record, serve
    # unchanged.
    shadow = tmp_path / "fusion_shadow.jsonl"
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH", str(shadow))
    _set_lc_snapshot(monkeypatch, None)
    cv = {"gold": 3200, "level": 9}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
    assert not shadow.exists()


def test_writer_failsoft_bad_path_output_unchanged(monkeypatch, tmp_path):
    # Parent path is a regular file so mkdir/open raises inside the
    # writer; the hook must swallow it (R101 writer fail-soft precedent).
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("RC_FUSION_SHADOW_PATH",
                       str(blocker / "fusion_shadow.jsonl"))
    _set_lc_snapshot(monkeypatch, _lc_allgamedata())
    cv = {"gold": 3200, "level": 9}
    out = _mk_reader(monkeypatch, cv).read_tiered()

    assert out == cv
