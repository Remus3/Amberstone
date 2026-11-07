"""Tests for tools/gated_g423_base_capture.py (G4-23 PREP, s144 lane gated c77).

Every input is hand-built (RM-906: no real game, match or player id). The tool is
a read-only watcher and grader; these tests pin its verdicts and the source facts
the doc row cites.
"""
from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path

import pytest

from core import vision_profiles as vp
from tools import gated_g423_base_capture as g423

ROOT = Path(__file__).resolve().parent.parent
CK = "2560x1440|GlobalScale=0.0000|MinimapScale=9.9900"
OLD_CK = "2560x1440|GlobalScale=0.0000|MinimapScale=1.6200"
T0 = 1_000_000.0


def _ref(sha: str = "aaaaaaaaaaaa", ts: float = 1.0, ck: str = OLD_CK,
         state: str = "base") -> dict:
    return {"sha12": sha, "ts": ts, "config_key": ck, "state": state,
            "w": 2560, "h": 1440}


def _old_refs() -> dict:
    return {f"{vp._safe(OLD_CK)}.jpg": _ref()}


def _s(t: float, game, fg: bool, refs: dict, ck: str = CK) -> dict:
    return g423.make_sample(T0 + t, game, g423.LEAGUE_EXE if fg else "explorer.exe",
                            ck, refs)


def _with_new(ts: float) -> dict:
    refs = _old_refs()
    refs[f"{vp._safe(CK)}.jpg"] = _ref("bbbbbbbbbbbb", T0 + ts, CK)
    return refs


def _pass_window() -> list:
    """Load in, alt-tab out 10 s (no write), come back, the still lands."""
    out = [_s(0, False, True, _old_refs())]
    out += [_s(t, True, False, _old_refs()) for t in (2, 4, 6, 8, 10, 12)]
    out.append(_s(14, True, True, _old_refs()))
    out.append(_s(16, True, True, _with_new(15.0)))
    out.append(_s(18, True, True, _with_new(15.0)))
    return out


# ---- source facts the row cites -------------------------------------------------

def test_auto_path_gates_are_has_game_foreground_then_once_per_config():
    src = inspect.getsource(vp.save_reference_image)
    i_game = src.index("_game_active()")
    i_fg = src.index("_league_is_foreground()")
    i_once = src.index("reference_path(ck, state).exists()")
    assert i_game < i_fg < i_once
    assert "if not force:" in src


def test_frame_self_grab_calls_the_auto_path_without_force():
    src = (ROOT / "vision_server" / "_frame.py").read_text(encoding="utf-8")
    assert "save_reference_image(img)" in src
    assert "force=True" not in src


def test_league_exe_constant_matches_the_gate():
    assert g423.LEAGUE_EXE == vp._LEAGUE_EXE


def test_safe_name_matches_reference_path():
    assert vp.reference_path(CK).name == f"{g423.safe_name(CK)}.jpg"


def test_base_still_whose_key_holds_a_double_underscore_is_not_a_named_state():
    # hud_settings writes "k=?" for a missing layout key; _safe turns "=?|"
    # into "___", so the file name alone cannot tell base from named state.
    qk = "2560x1440|GlobalScale=?|MinimapScale=9.9900"
    assert "__" in g423.safe_name(qk)
    refs = _old_refs()
    refs[f"{g423.safe_name(qk)}.jpg"] = _ref("bbbbbbbbbbbb", T0 + 15.0, qk)
    w = [_s(t, True, False, _old_refs(), ck=qk) for t in (0, 2, 4, 6, 8)]
    w += [_s(10, True, True, _old_refs(), ck=qk), _s(16, True, True, refs, ck=qk)]
    assert g423.grade(w)["verdict"] == "PASS_CANDIDATE"


def test_meta_ts_missing_or_outside_bracket_is_not_a_pass():
    for ts in (None, 1.0, 9999.0):
        w = _pass_window()
        for s in w[-2:]:
            s["refs"][f"{vp._safe(CK)}.jpg"]["ts"] = None if ts is None else T0 + ts
        r = g423.grade(w)
        assert r["verdict"] == "AMBIGUOUS" and r["bracket"]["meta_in_bracket"] is False


# ---- grade ----------------------------------------------------------------------

def test_pass_candidate_needs_arm_alt_tab_and_clean_bracket():
    r = g423.grade(_pass_window())
    assert r["verdict"] == "PASS_CANDIDATE"
    assert r["alt_tab"]["samples"] == 6 and r["alt_tab"]["span_s"] == 10.0
    assert r["bracket"]["meta_in_bracket"] is True
    assert "eyeball" in r["still_needs"]


def test_gate_c_masks_when_the_active_config_already_has_a_still():
    # The substitution: alt-tab on a calibrated config proves nothing.
    refs = _old_refs()
    w = [_s(t, True, t % 4 == 0, refs, ck=OLD_CK) for t in range(0, 40, 2)]
    assert g423.grade(w)["verdict"] == "GATE_C_MASKED"


def test_write_while_desktop_is_foreground_is_a_clobber():
    w = [_s(0, True, False, _old_refs()), _s(2, True, False, _with_new(1.0)),
         _s(4, True, False, _with_new(1.0))]
    assert g423.grade(w)["verdict"] == "FAIL_CLOBBER"


def test_write_with_no_game_fails():
    w = [_s(0, False, True, _old_refs()), _s(2, False, True, _with_new(1.0))]
    assert g423.grade(w)["verdict"] == "FAIL_NO_GAME"


def test_split_bracket_is_ambiguous():
    w = [_s(0, True, False, _old_refs()), _s(2, True, True, _with_new(1.0))]
    assert g423.grade(w)["verdict"] == "AMBIGUOUS"


def test_rewritten_existing_still_is_a_regrab():
    changed = _old_refs()
    changed[f"{vp._safe(OLD_CK)}.jpg"] = _ref("cccccccccccc", 5.0)
    w = [_s(0, True, True, _old_refs()), _s(2, True, True, changed)]
    assert g423.grade(w)["verdict"] == "FAIL_REGRAB"


def test_clean_write_without_alt_tab_is_not_exercised():
    w = [_s(0, True, True, _old_refs()), _s(2, True, True, _with_new(1.0))]
    assert g423.grade(w)["verdict"] == "NOT_EXERCISED"


def test_armed_eligible_minute_without_write_is_a_fail_candidate():
    w = [_s(t, True, True, _old_refs()) for t in range(0, 64, 2)]
    assert g423.grade(w)["verdict"] == "NO_WRITE_WHILE_ELIGIBLE"


def test_named_state_still_or_vanished_still_voids():
    named = _old_refs()
    named[f"{vp._safe(CK)}__self_dead.jpg"] = _ref("dddddddddddd", T0, CK, "self_dead")
    assert g423.grade([_s(0, True, True, _old_refs()),
                       _s(2, True, True, named)])["verdict"] == "VOID"
    assert g423.grade([_s(0, True, True, _old_refs()),
                       _s(2, True, True, {})])["verdict"] == "VOID"


def test_new_still_rewritten_after_its_write_is_a_regrab():
    w = _pass_window()
    later = _with_new(15.0)
    later[f"{vp._safe(CK)}.jpg"].update(sha12="eeeeeeeeeeee", ts=T0 + 19.0)
    w.append(_s(20, True, False, later))
    assert g423.grade(w)["verdict"] == "FAIL_REGRAB"


def test_new_still_vanishing_after_its_write_voids():
    w = _pass_window() + [_s(20, True, True, _old_refs())]
    assert g423.grade(w)["verdict"] == "VOID"


def test_meta_json_landing_after_the_jpg_still_grades():
    w = _pass_window()
    w[-2]["refs"][f"{vp._safe(CK)}.jpg"]["ts"] = None
    assert g423.grade(w)["verdict"] == "PASS_CANDIDATE"


def test_alt_tab_on_another_config_does_not_exercise_the_written_one():
    other = "2560x1440|GlobalScale=0.0000|MinimapScale=8.8800"
    w = [_s(0, False, True, _old_refs())]
    w += [_s(t, True, False, _old_refs(), ck=other) for t in (2, 4, 6, 8, 10, 12)]
    w += [_s(14, True, True, _old_refs()), _s(16, True, True, _with_new(15.0))]
    assert g423.grade(w)["verdict"] == "NOT_EXERCISED"


def test_refs_never_reports_unknown_key_as_armed(tmp_path, capsys):
    args = argparse.Namespace(cmd="refs", root=str(tmp_path))
    assert g423.run(args, sampler=lambda: _s(0, False, True, _old_refs(), ck="unknown")) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["armed"] is False and rep["config_key_known"] is False


def test_unknown_config_key_is_ambiguous_not_an_arm():
    w = [_s(t, True, False, _old_refs(), ck="unknown") for t in (0, 2, 4, 6)]
    r = g423.grade(w)
    assert r["verdict"] == "AMBIGUOUS" and "unknown" in r["reason"]


def test_no_samples_is_no_evidence():
    assert g423.grade([])["verdict"] == "NO_EVIDENCE"


# ---- readers and run --------------------------------------------------------------

def test_snapshot_refs_reads_meta_and_hashes(tmp_path):
    d = tmp_path / "ref"
    d.mkdir()
    (d / "a.jpg").write_bytes(b"jpeg-bytes")
    (d / "a.json").write_text(json.dumps({"config_key": CK, "ts": 12.5,
                                          "width": 2560, "height": 1440}))
    (d / "b__self_dead.jpg").write_bytes(b"x")
    snap = g423.snapshot_refs(d)
    assert snap["a.jpg"]["ts"] == 12.5 and snap["a.jpg"]["state"] == "base"
    assert len(snap["a.jpg"]["sha12"]) == 12
    assert snap["b__self_dead.jpg"]["ts"] is None
    assert g423.snapshot_refs(tmp_path / "missing") == {}


def test_read_has_game(tmp_path):
    p = tmp_path / "h.json"
    p.write_text(json.dumps({"has_game": True}))
    assert g423.read_has_game(p) is True
    assert g423.read_has_game(tmp_path / "none.json") is None


def test_run_watch_exit_codes_and_refs(tmp_path, capsys):
    window = iter(_pass_window())
    args = argparse.Namespace(cmd="watch", samples=10, interval=0.0, json=True,
                              root=str(tmp_path))
    assert g423.run(args, sampler=lambda: next(window), sleep=lambda s: None) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["verdict"] == "PASS_CANDIDATE" and len(out["timeline"]) == 10
    args = argparse.Namespace(cmd="refs", root=str(tmp_path))
    assert g423.run(args, sampler=lambda: _s(0, False, True, _old_refs())) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["armed"] is True and rep["stills"][0]["config_key"] == OLD_CK


def test_run_rejects_bad_sample_count(tmp_path):
    args = argparse.Namespace(cmd="watch", samples=0, interval=1.0, json=False,
                              root=str(tmp_path))
    assert g423.main(["watch", "--samples", "0", "--root", str(tmp_path)]) == 2
    with pytest.raises(ValueError):
        g423.run(args, sampler=dict)
