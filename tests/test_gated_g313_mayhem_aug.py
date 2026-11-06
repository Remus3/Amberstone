"""tools/gated_g313_mayhem_aug.py - the G3-13 sampler and grader (s144 lane gated cycle 8).

Read-only plumbing for the next ARAM Mayhem game; nothing here ticks a row.
Source pins first (the keys the tool reads are the keys the shipped coach
writes and the shipped panel renders), then the sampler against a stub fetch,
the grade predicates, and the CLI. All data is synthetic: augment names are
placeholders and no Riot id appears anywhere.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from tools import gated_g313_mayhem_aug as g

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "gated_g313_mayhem_aug.py"
CHOICES = ["Card Alpha", "Card Beta", "Card Gamma"]


def _s(t: float, gt: float | None, *, mode="aram", lc=True, game_mode="KIWI", select=False,
       choices=(), reco=(), top=None, reco_mode="mayhem", stage=None, frame_age=1.0) -> dict:
    return {
        "t": t, "state_ok": True, "mode_key": mode, "liveclient": lc, "game_time_s": gt,
        "game_mode": game_mode, "coach_mayhem": game_mode == "KIWI",
        "augment_select": select, "augment_choices": list(choices),
        "aug_reco": list(reco), "aug_reco_top": top if top is not None else (reco[0] if reco else None),
        "aug_reco_mode": reco_mode if reco else None, "aug_reco_stage": stage,
        "frame_ts": None if frame_age is None else t - frame_age, "frame_age_s": frame_age,
    }


def _good_game() -> list[dict]:
    return [
        _s(100.0, None, lc=False, mode="client"),
        _s(104.0, 2.0),
        _s(108.0, 6.0, select=True, choices=CHOICES, reco=["Card Beta", "Card Alpha"], stage=1),
        _s(112.0, 10.0, select=True, choices=CHOICES, reco=["Card Beta", "Card Alpha"], stage=1),
        _s(140.0, 38.0, select=False, choices=CHOICES, reco=["Card Beta", "Card Alpha"], stage=1),
    ]


# -- source pins ---------------------------------------------------------------

def test_coach_still_stamps_the_keys_the_tool_reads():
    src = (ROOT / "coaches" / "aram_coach.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    keys = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(getattr(t, "id", "") == "_AUG_RECO_KEYS" for t in n.targets))
    for k in ("aug_reco", "aug_reco_top", "aug_reco_mode", "aug_reco_stage"):
        assert k in keys
    assert 'mode="mayhem"' in src and '"augment_select":  True' in src
    assert 'cur["augment_select"] = False' in src


def test_panel_still_renders_from_those_keys():
    js = (ROOT / "web" / "js" / "panels" / "augment_reco.js").read_text(encoding="utf-8")
    for needle in ("p.aug_reco", "p.augment_select === true", "p.aug_reco_top", "PICK NOW", "TOP PICK"):
        assert needle in js


def test_liveclient_summary_carries_game_mode(monkeypatch):
    # Behavioural (s144 L5 merger): this was a source-text pin on
    # `out["game_mode"] = gd.get("gameMode")`, which the s144 true-audit
    # hardening of dashboard/_liveclient.py rewrote as
    # `_str_or(gd.get("gameMode"), None)` (a non-str mode reads None). What the
    # G3-13 grader needs is the VALUE on /api/state's liveclient block, so the
    # real summary builder is driven with a KIWI frame and must carry it.
    import time

    from core import liveclient_cache
    from dashboard import _liveclient

    frame = {"activePlayer": {"summonerName": "Me", "level": 5, "currentGold": 100,
                              "championStats": {}},
             "allPlayers": [{"summonerName": "Me", "championName": "Lux", "team": "ORDER",
                             "items": [], "scores": {"kills": 0, "deaths": 0,
                                                     "assists": 0, "creepScore": 0}}],
             "events": {"Events": []},
             "gameData": {"gameTime": 12.5, "gameMode": "KIWI"}}
    snap = liveclient_cache.Snapshot(data=frame, ts=time.time())
    monkeypatch.setattr(liveclient_cache, "get", lambda: snap)
    assert _liveclient.liveclient_summary()["game_mode"] == "KIWI"


def test_norm_name_matches_the_resolver():
    from core.augment_external_source import _norm_name
    for name in ("Bread And Butter", "bread-and-butter", "BREAD AND BUTTER!"):
        assert g.norm_name(name) == _norm_name(name)


def test_mayhem_matches_the_shared_detector():
    from core.mayhem_detect import is_mayhem
    for gm in ("KIWI", "ARAM", "ARAM_MAYHEM", "", None, "CHERRY"):
        assert g.is_mayhem_mode(gm) == is_mayhem(str(gm or ""))


# -- sampler -------------------------------------------------------------------

def _fetch_factory(state, meta, seen):
    def fetch(url, token):
        seen.append((url, token))
        return meta if url.endswith("/latest-frame/meta") else state
    return fetch


def test_sample_reduces_state_and_sends_token_only_to_the_relay():
    state = {"mode_key": "aram",
             "liveclient": {"game_time_s": 12.5, "game_mode": "KIWI", "summoner": "Player#0000"},
             "coach": {"mayhem": True, "augment_select": True, "augment_choices": CHOICES,
                       "aug_reco": [{"id": 1, "name": "Card Beta"}, {"id": 2, "name": "Card Alpha"}],
                       "aug_reco_top": "Card Beta", "aug_reco_mode": "mayhem", "aug_reco_stage": 1}}
    seen: list = []
    s = g.sample(_fetch_factory(state, {"ts": 995.0}, seen), now=lambda: 1000.0, token="tok-x")
    assert s["game_time_s"] == 12.5 and s["game_mode"] == "KIWI" and s["coach_mayhem"] is True
    assert s["aug_reco"] == ["Card Beta", "Card Alpha"] and s["frame_age_s"] == 5.0
    assert s["augment_choices"] == CHOICES and s["aug_reco_stage"] == 1
    assert ("https://127.0.0.1:8888/api/state", None) in seen
    assert ("http://127.0.0.1:8889/latest-frame/meta", "tok-x") in seen
    blob = json.dumps(s)
    assert "tok-x" not in blob and "Player#0000" not in blob


def test_sample_is_fail_soft_on_dead_endpoints():
    s = g.sample(lambda url, tok: None, now=lambda: 50.0, token="")
    assert s["state_ok"] is False and s["liveclient"] is False and s["frame_age_s"] is None
    assert g.grade([s])["verdict"] == "NO_GAME"


def test_relay_base_is_plain_http():
    assert g.RELAY_BASE.startswith("http://") and g.DASH_BASE.startswith("https://")


# -- grade ---------------------------------------------------------------------

def test_good_game_passes_compute_half():
    r = g.grade(_good_game())
    assert r["verdict"] == "PASS"
    c = r["checks"]
    assert c["reco"]["state"] == "PASS" and c["reco"]["top"] == "Card Beta"
    assert c["clear"]["state"] == "PASS" and c["frame"]["state"] == "FRESH"
    assert c["stage"]["aug_reco_stage"] == 1


def test_no_game():
    r = g.grade([_s(1.0, None, mode="client", lc=False)])
    assert r["verdict"] == "NO_GAME"


def test_aram_mode_key_without_liveclient_is_not_in_game():
    assert g.grade([_s(1.0, 5.0, lc=False)])["verdict"] == "NO_GAME"


def test_plain_aram_is_not_mayhem_and_negative_control_holds():
    r = g.grade([_s(1.0, 5.0, game_mode="ARAM"), _s(5.0, 9.0, game_mode="ARAM")])
    assert r["verdict"] == "NOT_MAYHEM" and r["checks"]["negative"]["state"] == "PASS"


def test_plain_aram_with_a_reco_fails_negative_control():
    r = g.grade([_s(1.0, 5.0, game_mode="ARAM", select=True, choices=CHOICES, reco=["Card Beta"])])
    assert r["verdict"] == "FAIL" and r["checks"]["negative"]["state"] == "FAIL"


def test_coach_mayhem_flag_alone_does_not_vouch():
    s = _s(1.0, 5.0, game_mode="ARAM")
    s["coach_mayhem"] = True
    assert g.grade([s])["checks"]["mayhem"]["state"] == "NOT_MAYHEM"


def test_panel_never_seen_is_not_seen_and_names_the_dark_case():
    # An unresolved offer writes no augment_select / augment_choices at all
    # (aram_coach._handle_augment_select), so a dark panel reads NOT_SEEN.
    r = g.grade([_s(1.0, 5.0), _s(5.0, 9.0)])
    assert r["verdict"] == "NOT_SEEN" and r["checks"]["panel"]["state"] == "NOT_SEEN"
    assert "dark on screen" in r["checks"]["panel"]["note"]
    assert g.EXIT.get(r["verdict"], 1) == 1


def test_select_without_choices_is_not_an_open_panel():
    r = g.grade([_s(1.0, 5.0, select=True, choices=())])
    assert r["checks"]["panel"]["state"] == "NOT_SEEN"


def test_stale_open_flag_without_reco_is_dark_not_pass():
    # Only a stale augment_select left by an earlier panel produces this shape.
    r = g.grade([_s(1.0, 5.0, select=True, choices=CHOICES), _s(30.0, 34.0)])
    assert r["verdict"] == "INCOMPLETE" and r["checks"]["reco"]["state"] == "DARK"


def test_top_not_offered_fails():
    r = g.grade([_s(1.0, 5.0, select=True, choices=CHOICES, reco=["Card Omega"]), _s(30.0, 34.0)])
    assert r["verdict"] == "FAIL" and r["checks"]["reco"]["state"] == "FAIL"
    assert "not an offered card" in r["checks"]["reco"]["problems"][0]["why"]


def test_top_matches_after_normalisation():
    r = g.grade([_s(1.0, 5.0, select=True, choices=["CARD-BETA!"], reco=["Card Beta"]),
                 _s(30.0, 34.0)])
    assert r["checks"]["reco"]["state"] == "PASS"


def test_wrong_reco_mode_fails():
    r = g.grade([_s(1.0, 5.0, select=True, choices=CHOICES, reco=["Card Beta"], reco_mode="arena"),
                 _s(30.0, 34.0)])
    assert r["verdict"] == "FAIL" and "aug_reco_mode" in r["checks"]["reco"]["problems"][0]["why"]


def test_one_bad_sample_fails_even_after_a_good_one():
    rows = _good_game()
    rows.insert(4, _s(120.0, 18.0, select=True, choices=CHOICES, reco=["Card Omega"]))
    assert g.grade(rows)["verdict"] == "FAIL"


def test_reco_outside_open_panel_is_not_graded_as_reco():
    rows = [_s(1.0, 5.0, select=True, choices=CHOICES), _s(30.0, 34.0, reco=["Card Omega"])]
    assert g.grade(rows)["checks"]["reco"]["state"] == "DARK"


def test_stuck_augment_select_fails():
    rows = [_s(1.0, 5.0, select=True, choices=CHOICES, reco=["Card Beta"]),
            _s(60.0, 5.0 + g.STUCK_AFTER_S + 1, select=True, choices=CHOICES, reco=["Card Beta"])]
    r = g.grade(rows)
    assert r["checks"]["clear"]["state"] == "STUCK" and r["verdict"] == "FAIL"


def test_select_still_open_inside_the_window_is_incomplete():
    rows = [_s(1.0, 5.0, select=True, choices=CHOICES, reco=["Card Beta"]),
            _s(10.0, 14.0, select=True, choices=CHOICES, reco=["Card Beta"])]
    r = g.grade(rows)
    assert r["checks"]["clear"]["state"] == "INCOMPLETE" and r["verdict"] == "INCOMPLETE"


@pytest.mark.parametrize("age,state", [(None, "STALE"), (g.FRAME_FRESH_S + 0.5, "STALE"),
                                       (g.FRAME_FRESH_S, "FRESH"), (-3.0, "STALE")])
def test_frame_freshness(age, state):
    rows = [_s(1.0, 5.0, select=True, choices=CHOICES, reco=["Card Beta"], frame_age=age),
            _s(30.0, 34.0)]
    assert g.grade(rows)["checks"]["frame"]["state"] == state


def test_stale_frame_does_not_change_the_compute_verdict():
    rows = _good_game()
    for s in rows:
        s["frame_age_s"] = 500.0
    r = g.grade(rows)
    assert r["verdict"] == "PASS" and r["checks"]["frame"]["state"] == "STALE"


# -- CLI and hygiene -----------------------------------------------------------

def test_render_always_says_the_on_screen_half_is_owed():
    text = g.render(g.grade(_good_game()))
    assert text.startswith("G3-13 compute half: PASS") and "on-screen: OWED" in text


@pytest.mark.parametrize("rows,code", [(_good_game(), 0), ([_s(1.0, 5.0)], 1),
                                       ([_s(1.0, 5.0, select=True, choices=CHOICES,
                                            reco=["Card Omega"])], 2)])
def test_cli_grade_exit_codes(tmp_path, capsys, rows, code):
    f = tmp_path / "samples.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n\n", encoding="utf-8")
    assert g.main(["--grade", str(f), "--json"]) == code
    out = json.loads(capsys.readouterr().out)
    assert out["samples"] == len(rows)


def test_cli_missing_file(tmp_path):
    assert g.main(["--grade", str(tmp_path / "absent.jsonl")]) == 1


def test_cli_sampling_prints_jsonl_and_grade_to_stderr(monkeypatch, capsys):
    calls = iter(_good_game())
    monkeypatch.setattr(g, "sample", lambda: next(calls))
    monkeypatch.setattr(g.time, "sleep", lambda s: None)
    assert g.main(["--samples", "5", "--interval", "0"]) == 0
    cap = capsys.readouterr()
    lines = [json.loads(x) for x in cap.out.splitlines()]
    assert len(lines) == 5 and "G3-13 compute half: PASS" in cap.err


def test_tool_is_read_only_and_ascii():
    src = TOOL.read_bytes()
    assert src.isascii() and b"\r\n" not in src
    text = src.decode("ascii")
    for banned in ("write_text", "write_bytes", ".unlink(", "os.remove", "shutil",
                   " open(", "subprocess", "/lol-", 'method="POST"', "method='POST'"):
        assert banned not in text, banned
    assert not re.search(r"\b\d{10}\b", text)
