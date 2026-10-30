"""tests for tools/gated_lx11_minimap_check.py (LX-11, RM-612 replay-scrubber minimap drain grader).

The plan half runs the SHIPPED web/js/panels/replay_minimap.js under node over a
hand-built match (synthetic ids only, RM-906). The grade half draws canvases with
PIL in the shapes dev.js _replayMapDraw draws (opaque art, a 3 px team-colour ring
at radius R, a 0.7-alpha cross at a death spot) and checks the verdicts, including
the mutants a broken renderer would produce. The DOM ids, tokens and drawing
constants the grader relies on are pinned against web/index.html and dev.js.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import math
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tools import gated_lx11_minimap_check as lx

ROOT = Path(__file__).resolve().parent.parent
DEV_JS = (ROOT / "web" / "js" / "panels" / "dev.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
SYNTH_ID = "XX1_9000000001"
ALLY = "#4aa3ff"
ENEMY = "#ff5a5a"
ALLY_RGB = (0x4A, 0xA3, 0xFF)
ENEMY_RGB = (0xFF, 0x5A, 0x5A)
W = H = 480
R = 16
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


# --- synthetic match --------------------------------------------------------------

# Spread-out positions (world units) so no two badges overlap on a 480 px canvas.
POS = {1: (2000, 12000), 2: (5000, 9000), 3: (8000, 6000), 4: (11000, 3000), 5: (3000, 3000),
       6: (12000, 12000), 7: (9000, 11000), 8: (6000, 12500), 9: (12500, 7000), 10: (7400, 7400)}
KILL_POS = (10000, 9000)


def _match(queue: int = 420) -> dict:
    parts = [{"participant_id": p, "team_id": 100 if p <= 5 else 200,
              "champion_id": 100 + p, "champion_name": f"Champ{p}"} for p in range(1, 11)]
    snaps = []
    for i in range(6):
        t = i * 60000
        entries = []
        for p in range(1, 11):
            pos = list(POS[p])
            if p == 6 and t == 180000:
                pos = list(KILL_POS)          # Riot keeps a dead champion's frame at its death spot
            entries.append({"participant_id": p, "level": 3, "pos": pos})
        snaps.append({"timestamp_ms": t, "minute": round(t / 60000.0, 1), "entries": entries})
    kills = [{"timestamp_ms": 175000, "killer_id": 1, "victim_id": 6, "pos": list(KILL_POS)}]
    return {"match_id": SYNTH_ID, "queue_id": queue, "participants": parts, "snapshots": snaps,
            "kills": kills, "tracked": {"champion_id": 101}}


def _w2c(pos):
    return [pos[0] / 14800 * W, H - pos[1] / 14800 * H]


# --- hand-built plan + PIL canvases -----------------------------------------------

def _plan() -> dict:
    badges = []
    for p in (1, 2, 3, 7, 8):
        badges.append({"pid": p, "role": "ally" if p <= 5 else "enemy", "xy": _w2c(POS[p]),
                       "revive": False, "src": "frame", "halo_units": 0, "obstructed": False})
    return {"tool": "gated_lx11_minimap_check", "match_sha": lx.match_sha(SYNTH_ID),
            "queue_id": 420, "kind": "sr", "canvas": {"w": W, "h": H, "r": R},
            "ally_team": 100, "slider_index": 3, "t_ms": 180000,
            "expect_frame_clock": "t = 3.0min", "expect_map_clock": "Map at 3:00",
            "frames_total": 6, "usable_by_rule": True, "badges": badges,
            "dead": [{"pid": 6, "role": "enemy", "cross_xy": _w2c(KILL_POS), "obstructed": False}],
            "unknown": []}


def _ring(d: ImageDraw.ImageDraw, xy, col):
    x, y = xy
    d.ellipse([x - R, y - R, x + R, y + R], fill=(30, 30, 30, 255))
    d.ellipse([x - R - 1.5, y - R - 1.5, x + R + 1.5, y + R + 1.5], outline=col + (255,), width=3)


def _cross(img: Image.Image, xy, col):
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    k = R * 0.5
    x, y = xy
    rgba = col + (int(0.7 * 255),)
    d.line([x - k, y - k, x + k, y + k], fill=rgba, width=3)
    d.line([x + k, y - k, x - k, y + k], fill=rgba, width=3)
    img.alpha_composite(over)


def _canvas(plan, art=True, victim_badge=False, swap=False, cross=True) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if art:
        # a dim gradient stands in for the desaturated map art (many colours, none near a ring)
        for y in range(H):
            for x in range(0, W, 8):
                img.paste((40 + x // 16, 60 + y // 16, 50 + (x + y) // 32, 255), (x, y, x + 8, y + 1))
    d = ImageDraw.Draw(img)
    cols = {"ally": ENEMY_RGB if swap else ALLY_RGB, "enemy": ALLY_RGB if swap else ENEMY_RGB}
    for dd in plan["dead"]:
        if cross:
            _cross(img, dd["cross_xy"], cols[dd["role"]])
        if victim_badge:
            _ring(d, dd["cross_xy"], cols[dd["role"]])
    for b in plan["badges"]:
        _ring(d, b["xy"], cols[b["role"]])
    return img


def _evidence(img: Image.Image, **over) -> dict:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    ev = {"tool": "gated_lx11_minimap_check", "captured_at": "2026-10-30T12:00:00Z",
          "href": "https://127.0.0.1:8888/#replay", "ui_mock": "", "view_hidden": False,
          "figure_hidden": False,
          "note_text": "Positions sampled every 60 s; the halo grows with time since the last sample",
          "note_visible": True, "map_clock_text": "Map at 3:00", "frame_clock_text": "t = 3.0min",
          "slider_value": "3", "meta_text": f"{SYNTH_ID} - Ranked Solo - 5:00 - patch 16.21 (W)",
          "flags_text": "", "ally_color": ALLY, "enemy_color": ENEMY, "text_color": "#e8e8e8",
          "canvas_w": W, "canvas_h": H,
          "canvas_png": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}
    ev.update(over)
    return ev


# --- grade ------------------------------------------------------------------------

def test_clean_canvas_passes():
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan)))
    assert res["verdict"] == "PASS", res
    assert res["checks"]["art"] == "ART_DRAWN"
    assert all(b["ring"] == "RING_OK" for b in res["checks"]["badges"])
    assert res["checks"]["dead"][0]["hidden"] == "HIDDEN"
    assert res["checks"]["dead"][0]["cross"] == "CROSS_SEEN"


def test_dead_champion_still_drawn_fails():
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan, victim_badge=True)))
    assert res["verdict"] == "FAIL"
    assert res["checks"]["dead"][0]["hidden"] == "BADGE_DRAWN"


def test_missing_art_fails():
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan, art=False)))
    assert res["verdict"] == "FAIL"
    assert res["checks"]["art"] == "ART_MISSING"


def test_swapped_ring_colours_fail():
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan, swap=True)))
    assert res["verdict"] == "FAIL"
    assert any(b["ring"] == "RING_ABSENT" for b in res["checks"]["badges"])


def test_hidden_victim_without_cross_is_inconclusive():
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan, cross=False)))
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["checks"]["dead"][0]["cross"] == "CROSS_UNCLEAR"


@pytest.mark.parametrize("over,verdict", [
    ({"ui_mock": "1"}, "INCONCLUSIVE"),
    ({"figure_hidden": "false"}, "INCONCLUSIVE"),
    ({"note_visible": "true"}, "INCONCLUSIVE"),
    ({"note_text": 5}, "INCONCLUSIVE"),
    ({"ally_color": "rgb(99999999999, 0, 0)"}, "INCONCLUSIVE"),
    ({"view_hidden": True}, "FAIL"),
    ({"view_hidden": None}, "INCONCLUSIVE"),
    ({"figure_hidden": True}, "FAIL"),
    ({"note_text": "Champion positions"}, "FAIL"),
    ({"note_visible": False}, "FAIL"),
    ({"map_clock_text": "Map at 4:00"}, "INCONCLUSIVE"),
    ({"frame_clock_text": "t = 4.0min"}, "INCONCLUSIVE"),
    ({"slider_value": "2"}, "INCONCLUSIVE"),
    ({"map_clock_text": 300}, "INCONCLUSIVE"),
    ({"frame_clock_text": None}, "INCONCLUSIVE"),
    ({"ui_mock": True}, "INCONCLUSIVE"),
    ({"meta_text": "XX1_9000000002 - Ranked Solo - 5:00 - patch 16.21"}, "INCONCLUSIVE"),
    ({"href": "http://127.0.0.1:8890/#replay"}, "INCONCLUSIVE"),
    ({"href": "file:///tmp/replay.html"}, "INCONCLUSIVE"),
    ({"ally_color": "", "enemy_color": "", "text_color": ""}, "INCONCLUSIVE"),
    ({"ally_color": "oklch(70% 0.1 250)"}, "INCONCLUSIVE"),
    ({"ally_color": "rgb(74 163 255)", "enemy_color": "rgb(255 90 90 / 1)"}, "PASS"),
    ({"enemy_color": ALLY}, "FAIL"),
])
def test_dom_and_provenance_rules(over, verdict):
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan), **over))
    assert res["verdict"] == verdict, (over, res["fails"], res["gaps"])


def test_flat_fill_is_not_map_art():
    plan = _plan()
    flat = Image.new("RGBA", (W, H), (60, 70, 80, 255))
    flat.alpha_composite(_canvas(plan, art=False))
    res = lx.grade(plan, _evidence(flat))
    assert res["checks"]["art"] == "ART_FLAT"
    assert res["verdict"] == "INCONCLUSIVE"


def test_empty_token_falls_back_to_text_colour_like_dev_js():
    assert lx.token_color("", (1, 2, 3)) == (1, 2, 3)
    assert lx.token_color("  ", (1, 2, 3)) == (1, 2, 3)
    assert lx.token_color("#000000", (1, 2, 3)) == (0, 0, 0)
    assert lx.token_color("oklch(70% 0.1 250)", (1, 2, 3)) is None
    assert 'const allyColor = _replayMapToken("--signal-info") || fg;' in DEV_JS


def test_wrong_evidence_never_fails_the_row():
    plan = _plan()
    broken = _canvas(plan, victim_badge=True, art=False)
    for over in ({"ui_mock": "1"}, {"href": "http://localhost:9000/"},
                 {"meta_text": "XX1_9000000002 - Ranked Solo"},
                 {"slider_value": "2", "map_clock_text": "Map at 2:00",
                  "frame_clock_text": "t = 2.0min"}):
        res = lx.grade(plan, _evidence(broken, **over))
        assert res["verdict"] == "INCONCLUSIVE" and res["provenance"], over
        assert res["fails"]          # the render findings are still reported


def test_ring_mostly_off_canvas_is_unclear_not_absent():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    assert lx.ring_fraction(img, [0, 0], R, ALLY_RGB) is None
    assert lx.ring_fraction(img, [240, 240], R, ALLY_RGB) == 0.0


def test_wrong_canvas_size_fails():
    plan = _plan()
    small = _canvas(plan).resize((300, 300))
    res = lx.grade(plan, _evidence(small))
    assert res["verdict"] == "FAIL"


def test_obstructed_rows_are_skipped_not_passed():
    plan = _plan()
    for b in plan["badges"]:
        b["obstructed"] = True
    plan["dead"][0]["obstructed"] = True
    res = lx.grade(plan, _evidence(_canvas(plan)))
    assert res["verdict"] == "INCONCLUSIVE"
    assert {b["ring"] for b in res["checks"]["badges"]} == {"SKIPPED"}


def test_grade_output_never_carries_the_match_id():
    plan = _plan()
    res = lx.grade(plan, _evidence(_canvas(plan)))
    assert SYNTH_ID not in json.dumps(res)
    assert SYNTH_ID not in json.dumps(plan)


def test_parse_color_forms():
    assert lx.parse_color("#4aa3ff") == ALLY_RGB
    assert lx.parse_color("#fff") == (255, 255, 255)
    assert lx.parse_color(" rgb(1, 2, 3) ") == (1, 2, 3)
    assert lx.parse_color("rgba(1,2,3,0.5)") == (1, 2, 3)
    assert lx.parse_color("rgb(1 2 3)") == (1, 2, 3)
    assert lx.parse_color("rgb(1 2 3 / 50%)") == (1, 2, 3)
    assert lx.parse_color("var(--x)") is None
    assert lx.parse_color(None) is None


def test_dur_str_and_radius_match_dev_js():
    assert lx.dur_str(180) == "3:00"
    assert lx.dur_str(3605) == "60:05"
    assert lx.badge_radius(480) == 16
    assert lx.badge_radius(495) == 17          # Math.round(16.5) = 17


# --- cli --------------------------------------------------------------------------

def test_cli_grade_exit_codes(tmp_path, capsys):
    plan = _plan()
    pp = tmp_path / "plan.json"
    pp.write_text(json.dumps(plan), encoding="utf-8")
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(_evidence(_canvas(plan))), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_evidence(_canvas(plan, victim_badge=True))), encoding="utf-8")
    junk = tmp_path / "junk.json"
    junk.write_text(json.dumps(_evidence(_canvas(plan), canvas_png="data:image/png;base64,AAAA")),
                    encoding="utf-8")
    assert lx.main(["grade", "--plan", str(pp), "--evidence", str(ok)]) == 0
    assert lx.main(["grade", "--plan", str(pp), "--evidence", str(bad)]) == 1
    assert lx.main(["grade", "--plan", str(pp), "--evidence", str(junk)]) == 2
    assert lx.main(["grade", "--plan", str(pp), "--evidence", str(tmp_path / "nope.json")]) == 2
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    arr = tmp_path / "arr.json"
    arr.write_text("[]", encoding="utf-8")
    assert lx.main(["grade", "--plan", str(empty), "--evidence", str(ok)]) == 2
    assert lx.main(["grade", "--plan", str(pp), "--evidence", str(arr)]) == 2
    assert lx.main(["plan", "--match-json", str(arr)]) == 2
    for mutate in (lambda p: p["badges"][0].__setitem__("xy", [float("inf"), 0]),
                   lambda p: p["canvas"].__setitem__("w", "480"),
                   lambda p: p["canvas"].__setitem__("r", float("inf")),
                   lambda p: p["dead"][0].__setitem__("role", "neutral"),
                   lambda p: p.__setitem__("badges", "x"),
                   lambda p: p["badges"][0].__setitem__("xy", [-1000, -1000]),
                   lambda p: p["canvas"].__setitem__("r", 4096),
                   lambda p: p.pop("slider_index"),
                   lambda p: p.__setitem__("slider_index", True)):
        bent = copy.deepcopy(plan)
        mutate(bent)
        bp = tmp_path / "bent.json"
        bp.write_text(json.dumps(bent), encoding="utf-8")
        assert lx.main(["grade", "--plan", str(bp), "--evidence", str(ok)]) == 2
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 100000 + "]" * 100000, encoding="utf-8")
    assert lx.main(["grade", "--plan", str(deep), "--evidence", str(ok)]) == 2
    out = capsys.readouterr().out
    assert SYNTH_ID not in out


def test_cli_snippet_prints_function():
    assert lx.main(["snippet"]) == 0


# --- plan (runs the shipped replay_minimap.js) ------------------------------------

@needs_node
def test_plan_picks_the_death_frame():
    plan = lx.build_plan(_match())
    assert plan["slider_index"] == 3 and plan["t_ms"] == 180000
    assert plan["expect_map_clock"] == "Map at 3:00"
    assert plan["expect_frame_clock"] == "t = 3.0min"
    assert plan["canvas"] == {"w": W, "h": H, "r": R}
    assert plan["ally_team"] == 100
    dead = {d["pid"]: d for d in plan["dead"]}
    assert set(dead) == {6}
    assert dead[6]["role"] == "enemy"
    assert dead[6]["cross_xy"] == pytest.approx(_w2c(KILL_POS))
    pids = {b["pid"]: b for b in plan["badges"]}
    assert set(pids) == set(range(1, 11)) - {6}
    assert pids[2]["xy"] == pytest.approx(_w2c(POS[2]))
    assert pids[1]["role"] == "ally" and pids[9]["role"] == "enemy"
    assert SYNTH_ID not in json.dumps(plan)
    assert plan["match_sha"] == lx.match_sha(SYNTH_ID)


@needs_node
def test_plan_ally_team_follows_tracked_champion():
    m = _match()
    m["tracked"] = {"champion_id": 107}
    plan = lx.build_plan(m)
    roles = {b["pid"]: b["role"] for b in plan["badges"]}
    assert roles[7] == "ally" and roles[1] == "enemy"


@needs_node
def test_plan_index_override_and_range():
    plan = lx.build_plan(_match(), index=1)
    assert plan["slider_index"] == 1 and plan["dead"] == []
    assert plan["usable_by_rule"] is False
    with pytest.raises(lx.InputError):
        lx.build_plan(_match(), index=99)


@needs_node
@pytest.mark.parametrize("queue", [1750, 1700, 2400])
def test_plan_refuses_hidden_map_queues(queue):
    with pytest.raises(lx.InputError):
        lx.build_plan(_match(queue))


@needs_node
def test_plan_refuses_match_without_positions():
    m = _match()
    for s in m["snapshots"]:
        for e in s["entries"]:
            e["pos"] = None
    with pytest.raises(lx.InputError):
        lx.build_plan(m)


@needs_node
def test_plan_marks_overlap_as_obstructed():
    m = _match()
    for s in m["snapshots"]:
        for e in s["entries"]:
            if e["participant_id"] == 2:
                e["pos"] = [POS[3][0] + 300, POS[3][1] + 300]
    plan = lx.build_plan(m, index=2)
    pids = {b["pid"]: b for b in plan["badges"]}
    assert pids[2]["obstructed"] and pids[3]["obstructed"]
    assert not pids[8]["obstructed"]


@needs_node
def test_plan_then_grade_end_to_end(tmp_path):
    plan = lx.build_plan(_match())
    assert lx.grade(plan, _evidence(_canvas(plan)))["verdict"] in ("PASS", "INCONCLUSIVE")
    clear = copy.deepcopy(plan)
    clear["badges"] = [b for b in clear["badges"] if not b["obstructed"]]
    assert lx.grade(clear, _evidence(_canvas(clear)))["verdict"] == "PASS"
    mj = tmp_path / "m.json"
    mj.write_text(json.dumps(_match(1750)), encoding="utf-8")
    assert lx.main(["plan", "--match-json", str(mj)]) == 2


# --- pins against the shipped page ------------------------------------------------

def test_snippet_ids_exist_in_index_html():
    for el_id in ("replay-map-canvas", "replay-map-figure", "replay-map-clock", "replay-clock",
                  "replay-slider", "replay-meta", "replay-map-flags", "view-replay"):
        assert f'"{el_id}"' in lx.SNIPPET
        assert f'id="{el_id}"' in INDEX, el_id
    assert 'class="replay-map-note"' in INDEX
    note = re.search(r'class="replay-map-note">([^<]*)<', INDEX).group(1)
    assert lx.NOTE_FRAGMENT in note


def test_canvas_size_read_from_index_html():
    assert lx.canvas_size() == (W, H)


def test_drawing_constants_pinned_to_dev_js():
    draw = DEV_JS[DEV_JS.index("function _replayMapDraw"):DEV_JS.index("function _replayViewWireOnce")]
    for token in ('"--signal-info"', '"--signal-bad"', '"--text"', '"--surface"'):
        assert token in draw
        assert token.strip('"') in lx.SNIPPET or token == '"--surface"'
    assert "const R = Math.round(W / 30);" in draw
    assert "const k = R * 0.5;" in draw
    assert "ctx.globalAlpha = 0.7;" in draw
    assert draw.count("ctx.lineWidth = 3;") == 2           # cross + badge ring
    assert "ctx.arc(x, y, R, 0, Math.PI * 2);" in draw
    assert "ctx.setLineDash([4, 3])" in draw               # revive ring is dashed
    assert '"Map at " + _replayDurStr(Math.floor(t / 1000))' in draw
    assert "`t = ${snap.minute.toFixed(1)}min`" in DEV_JS
    assert "m.textContent = `${d.match_id} - " in DEV_JS
    assert "_REPLAY_MAP.allyTeam = tracked ? tracked.team_id : 100;" in DEV_JS
    assert 'document.body.dataset.uiMock === "1"' in DEV_JS


def test_cross_control_point_is_off_the_cross():
    # The control pixel sits at the same distance on the horizontal axis; its distance
    # to either diagonal is d, which clears the 1.5 px half-width for every sampled d.
    k = R * 0.5
    assert min(f * k for f in (0.35, 0.5, 0.65, 0.8)) > 1.5 + 1.0
    assert math.isclose(math.hypot(k, k), k * math.sqrt(2.0))
