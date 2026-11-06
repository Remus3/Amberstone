"""Tests for tools/gated_g413_pulse_ration.py (G4-13 READY, read-only grader).

Synthetic recorder logs only; no game, no browser, no network. The pins read
the shipped JS so the grader's mirrored decision table cannot drift silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tools import gated_g413_pulse_ration as g

ROOT = Path(__file__).resolve().parent.parent
T0 = 1_800_000_000.0


def _state(phase="InProgress", mode="sr", lc=None):
    return {"mode_key": mode, "lcu": {"phase": phase},
            "liveclient": {"game_time_s": 812.0} if lc is None else lc}


def _stamp(t, cue, pulse=None, raw="Hold the wave", prev=None):
    if pulse is None:
        pulse = "1" if g.expected_pulse(prev or "none", cue) else "0"
    return {"k": "stamp", "t": T0 + t, "cue": cue, "tier": g.CUE_TIER[cue],
            "pulse": pulse, "raw": raw, "band": "action action-fight"}


def _glow(t, target=".am-pane-call", cls="ov-pulse"):
    return {"k": "glow", "t": T0 + t, "target": target, "cls": cls}


def _log(rows, shell="overlay", notify=True, ts=None):
    last = max((r["t"] for r in rows if isinstance(r, dict)
                and isinstance(r.get("t"), float)), default=T0)
    return {"ts": last + 1.0 if ts is None else ts, "shell": shell,
            "pulse_notify": notify, "armed_at": T0, "log": rows}


def _grade(rows, **kw):
    log = _log(rows, **{k: v for k, v in kw.items() if k in ("shell", "notify", "ts")})
    state = kw.get("state", _state())
    return g.grade(state, log, kw.get("state_ts", log["ts"]))


def test_rationed_when_lethal_cross_glows_and_reemit_is_suppressed():
    rows = [_stamp(0, "fight", "0"),
            _stamp(2, "fight", "0", raw="Trade on cooldowns"),
            _stamp(4, "lethal", "1", raw="Trade on cooldowns"),
            _glow(4.01),
            _stamp(6, "lethal", "0", raw="Back off now")]
    r = _grade(rows)
    assert r["verdict"] == "RATIONED"
    assert r["operator_eyeball_owed"] is True
    assert [a["cue"] for a in r["armed"]] == ["lethal"]
    assert r["armed"][0]["headline_changed"] is False
    classes = [s["class"] for s in r["suppressed"]]
    assert classes == ["reemit_same_cue", "sustained_emergency_new_text"]
    assert r["sustained_emergency_new_text"] == 1


def test_steady_tier_change_is_suppressed_not_armed():
    rows = [_stamp(0, "good", "0"), _stamp(2, "fight", "0", raw="Fight at drake"),
            _stamp(4, "spike", "1"), _glow(4.2, "#rn-callouts")]
    r = _grade(rows)
    assert r["verdict"] == "RATIONED"
    assert r["suppressed"][0]["class"] == "steady_tier"


def test_glow_missing_when_armed_without_ov_pulse():
    rows = [_stamp(0, "fight", "0"), _stamp(2, "urgent_headline", "1", raw="DIVE"),
            _glow(2.01, "#rn-action", "rn-pulse-bad")]
    r = _grade(rows)
    # The headline pulse is hidden on the overlay shell: it never counts.
    assert r["verdict"] == "GLOW_MISSING"
    assert r["armed"][0]["glows"] == ["#rn-action:rn-pulse-bad"]


def test_throttled_armed_stamp_is_not_missing():
    rows = [_stamp(0, "fight", "0"), _stamp(1.0, "lethal", "1"), _glow(1.01),
            _stamp(2.0, "urgent_headline", "1", raw="Flash away")]
    r = _grade(rows)
    assert r["verdict"] == "RATIONED"
    assert [x["cue"] for x in r["throttled"]] == ["urgent_headline"]


def test_only_a_recent_call_pane_glow_excuses_a_dark_armed_stamp():
    rows = [_stamp(0, "fight", "0"), _stamp(1.0, "spike", "1"), _glow(1.01, "#rn-callouts"),
            _stamp(2.0, "urgent_headline", "1", raw="Flash away")]
    r = _grade(rows)
    assert r["verdict"] == "GLOW_MISSING"
    assert [x["cue"] for x in r["problems"]] == ["urgent_headline"]


def test_all_throttled_armed_stamps_credit_no_glow():
    # The only glow precedes the first graded stamp (the baseline's): nothing
    # graded glowed on its own, so the Emergency half is still unanswered.
    rows = [_stamp(0, "lethal", "1"), _glow(0.01),
            _stamp(1.0, "urgent_headline", "1", raw="Flash away")]
    r = _grade(rows)
    assert r["verdict"] == "NO_ARMED"
    assert r["armed_but_throttled"] == 1


def test_glow_leak_when_latest_stamp_unarmed():
    rows = [_stamp(0, "fight", "0"), _stamp(2, "fight", "0"), _glow(2.5)]
    assert _grade(rows)["verdict"] == "GLOW_LEAK"


def test_decision_drift_on_pulse_mismatch_and_tier_mismatch():
    rows = [_stamp(0, "fight", "0"), _stamp(2, "good", "1")]
    r = _grade(rows)
    assert r["verdict"] == "DECISION_DRIFT"
    assert r["problems"][0]["expected_pulse"] == "0"
    bad_tier = dict(_stamp(2, "lethal", "1"), tier="urgent")
    assert _grade([_stamp(0, "fight", "0"), bad_tier])["verdict"] == "DECISION_DRIFT"


def test_sustained_cue_never_expects_a_pulse():
    assert g.expected_pulse("lethal", "lethal") is False
    assert g.expected_pulse("choices", "choices") is False
    assert g.expected_pulse("good", "choices") is True
    assert g.expected_pulse("good", "fight") is False
    assert g.expected_pulse("fight", "objective_steal") is True


def test_no_armed_when_only_quiet_stamps():
    rows = [_stamp(0, "fight", "0"), _stamp(2, "fight", "0")]
    assert _grade(rows)["verdict"] == "NO_ARMED"


@pytest.mark.parametrize("state", [_state(phase="ChampSelect"), _state(lc={}),
                                   _state(mode="tft"), _state(mode="client")])
def test_no_game(state):
    rows = [_stamp(0, "fight", "0"), _stamp(2, "lethal", "1"), _glow(2.01)]
    assert _grade(rows, state=state)["verdict"] == "NO_GAME"


def test_stale_log_not_overlay_muted_too_short():
    rows = [_stamp(0, "fight", "0"), _stamp(2, "lethal", "1"), _glow(2.01)]
    assert _grade(rows, state_ts=T0 + 3.0 + g.MAX_SKEW_S + 1)["verdict"] == "STALE_LOG"
    assert _grade(rows, shell="")["verdict"] == "NOT_OVERLAY"
    assert _grade(rows, notify=False)["verdict"] == "MUTED"
    assert _grade([_stamp(0, "lethal", "1")])["verdict"] == "TOO_SHORT"


def test_garbage_log_rows_are_ignored():
    rows = [{"k": "stamp", "t": "x"}, "junk", _stamp(0, "fight", "0"),
            _stamp(2, "fight", "0")]
    assert _grade(rows)["verdict"] == "NO_ARMED"


def test_cli_exit_codes_and_snippets(tmp_path, capsys):
    rows = [_stamp(0, "fight", "0"), _stamp(2, "lethal", "1"), _glow(2.01)]
    log = _log(rows)
    sp, lp = tmp_path / "state.json", tmp_path / "log.json"
    sp.write_text(json.dumps(_state()), encoding="utf-8")
    lp.write_text(json.dumps(log), encoding="utf-8")
    argv = ["grade", "--state", str(sp), "--log", str(lp), "--state-ts", str(log["ts"])]
    assert g.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "RATIONED"
    lp.write_text(json.dumps(_log([_stamp(0, "fight", "0"), _stamp(2, "good", "1")])),
                  encoding="utf-8")
    assert g.main(argv) == 3
    capsys.readouterr()
    lp.write_text("[]", encoding="utf-8")
    assert g.main(argv) == 2
    capsys.readouterr()
    assert g.main(["snippet"]) == 0
    snip = capsys.readouterr().out
    assert "data-s0-pulse" in snip and "%TARGETS%" not in snip
    for t in g.GLOW_TARGETS:
        assert json.dumps(t) in snip
    assert g.main(["dump"]) == 0
    assert "rc_overlay_settings" in capsys.readouterr().out


def test_tool_is_read_only_and_ascii():
    src = (ROOT / "tools" / "gated_g413_pulse_ration.py").read_text(encoding="utf-8")
    src.encode("ascii")
    for banned in ("write_text", "requests", "urllib", "subprocess", "open(", "unlink"):
        assert banned not in src, banned


# --- pins against the shipped JS --------------------------------------------

def _js(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_pin_cue_tier_table_matches_overlay_priority():
    src = _js("web/js/lib/overlay_priority.js")
    block = re.search(r"const _CUE_TIER = \{(.*?)\};", src, re.S)
    assert block, "_CUE_TIER block moved"
    pairs = dict(re.findall(r"(\w+):\s*'(\w+)'", block.group(1)))
    assert pairs == g.CUE_TIER
    should = re.search(r"function shouldPulse\(prevCue, sel\) \{(.*?)\n\}", src, re.S)
    assert should, "shouldPulse moved"
    body = should.group(1)
    assert "sel.cue === 'spike' || sel.cue === 'choices'" in body
    assert "sel.tier === 'emergency' || oneShot" in body
    assert "eligible && prevCue !== sel.cue" in body


def test_pin_overlay_pulse_targets_throttle_and_gate():
    src = _js("web/js/overlay_pulse.js")
    assert re.search(r"const THROTTLE_MS = (\d+);", src).group(1) == str(
        int(g.THROTTLE_S * 1000))
    assert 'rn.dataset.s0Pulse === "1"' in src
    assert 'const PULSE_CLASS = "ov-pulse";' in src
    targets = re.findall(r'\{ mount: "([\w-]+)",\s*container: ("[^"]+"|null) \}', src)
    want = {(".am-pane-call", "am-call-body"), (".am-pane-build", "am-build-body"),
            ("#rn-lead", "rn-lead"), ("#rn-choices", "rn-choices"),
            ("#rn-callouts", "rn-callouts")}
    got = {(c.strip('"') if c != "null" else "#" + m, m) for m, c in targets}
    assert got == want
    assert {sel for sel, _ in want} == set(g.GLOW_TARGETS)


def test_pin_right_now_stamps_and_headline_hidden_on_overlay():
    rn = _js("web/js/panels/right_now.js")
    for frag in ("RN.root.dataset.s0Cue = _sel.cue;",
                 "RN.root.dataset.s0Tier = _sel.tier;",
                 'RN.root.dataset.s0Pulse = _s0Pulse ? "1" : "0";',
                 "if (isFreshAction && _s0Pulse) {",
                 "RN.action.dataset.raw = rawAction;"):
        assert frag in rn, frag
    css = _js("web/css/overlay.css")
    assert ('body[data-shell="overlay"] #right-now .panel-body > '
            '*:not(#rn-lead):not(#rn-choices):not(#rn-callouts) {\n  display: none !important;'
            ) in css
