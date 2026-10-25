"""TFT-06: labelled frame set + the CV accuracy harness (docs/TFT_PROGRAM.md 3.4).

Covers ``tools/tft_cv_accuracy.py`` on a synthetic mini corpus (built in
tmp_path, no Riot art, no real frame) and the committed scrubbed label set
``tests/fixtures/tft_cv/labels_20261025-070350.json``. The real corpus frames
are gitignored (they show other players' names); the one test that needs them
skips when they are absent.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

import tools.tft_cv_accuracy as acc

REPO = Path(__file__).resolve().parents[1]
LABELS_FIXTURE = REPO / "tests" / "fixtures" / "tft_cv" / "labels_20261025-070350.json"
REAL_CORPUS = REPO / "ops" / "runtime" / "tft_qa" / "20261025-070350"


# ---------------------------------------------------------------------------
# synthetic mini corpus
# ---------------------------------------------------------------------------

def _f1():
    return {
        "screen": "board", "shop_open": True, "occluders": [],
        "stage": "2-2", "timer": 0, "level": 4, "xp_cur": 2, "xp_max": 10,
        "gold": 12, "streak": 2, "odds": [55, 30, 15, 0, 0],
        "buy_xp_cost": 4, "reroll_cost": 2, "hud_counter": 6,
        "shop": [{"name": "Akali", "cost": 1, "kind": "champion"}, None, None,
                 {"name": "Teemo", "cost": 2, "kind": "champion"},
                 {"name": "Shen", "cost": 2, "kind": "champion"}],
        "hp_local": 100,
        "scoreboard": [{"hp": 100, "level": 4, "local": True},
                       {"hp": 96, "level": 3}, {"hp": 91, "level": 3}],
        "traits": [{"name": "Blossom", "count": 3, "active": True},
                   {"name": "Juggernaut", "count": 2, "active": True},
                   {"name": "Primal", "count": 1, "active": False}],
        "traits_more": 0, "augment_offers": None, "item_offers": None,
    }


def _f2():
    d = _f1()
    d.update({"stage": "3-1", "timer": 1, "level": 6, "xp_cur": 2, "xp_max": 36,
              "gold": 36, "streak": 7, "odds": [30, 40, 25, 5, 0]})
    return d


def _f3():  # carousel: bottom HUD hidden
    d = _f1()
    d.update({"screen": "carousel", "shop_open": False, "stage": "2-4", "timer": 19,
              "level": None, "xp_cur": None, "xp_max": None, "gold": None,
              "streak": None, "odds": None, "buy_xp_cost": None,
              "reroll_cost": None, "hud_counter": None, "shop": None})
    return d


def _f4():  # augment choice
    d = _f3()
    d.update({"screen": "augment_choice", "stage": "3-2", "timer": 37,
              "augment_offers": ["Bronze For Life I", "Cognitive Overload",
                                 "Healing Orbs II"]})
    return d


FRAMES = ["game_0001_el0100.jpg", "game_0002_el0160.jpg",
          "game_0003_el0220.jpg", "game_0004_el0280.jpg"]


def _gt():
    return dict(zip(FRAMES, (_f1(), _f2(), _f3(), _f4())))


def _noisy():
    """Predictions with known, hand-countable errors."""
    p1 = _f1()
    p1["gold"] = 72                                    # wrong: 12 -> 72
    p1["shop"] = [dict(s) if s else None for s in p1["shop"]]
    p1["shop"][3]["name"] = "Teeno"                    # one slot name wrong
    p1["traits"] = [{"name": "Blossom", "count": 3, "active": True},
                    {"name": "Juggernaut", "count": 2, "active": True},
                    {"name": "Solar", "count": 1, "active": False}]  # Primal -> Solar
    p2 = _f2()
    p2["gold"] = {"value": 36, "conf": 0.6}            # envelope, right answer
    p3 = _f3()
    p3["gold"] = 5                                     # hallucinated: panel hidden
    p3.pop("stage")                                    # missed
    p4 = _f4()                                         # gold None = absent, correct
    return dict(zip(FRAMES, (p1, p2, p3, p4)))


def _labels_doc(frames_dir: Path | None = None) -> dict:
    frames = []
    for name, fields in _gt().items():
        row = {"frame": name, "el": int(name.split("_el")[1][:4]), "labels": fields}
        if frames_dir is not None:
            row["sha256"] = hashlib.sha256((frames_dir / name).read_bytes()).hexdigest()
        frames.append(row)
    return {
        "schema": acc.SCHEMA, "match": "synthetic-mini", "set": 18,
        "frame_size": [1280, 720], "source_size": [2560, 1440],
        "privacy": "synthetic", "semantics": "synthetic",
        "verification": {"method": "synthetic", "author": "test-a", "verifier": "test-b",
                         "frames_compared": 4, "values_compared": 1,
                         "disagreements": 0, "adjudicated": 0},
        "frames": frames,
    }


@pytest.fixture
def mini_corpus(tmp_path):
    frames_dir = tmp_path / "corpus" / "frames"
    frames_dir.mkdir(parents=True)
    for i, name in enumerate(FRAMES):
        (frames_dir / name).write_bytes(b"synthetic-frame-%d" % i)
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(_labels_doc(frames_dir)), encoding="utf-8")
    return tmp_path / "corpus", labels


# ---------------------------------------------------------------------------
# grading semantics
# ---------------------------------------------------------------------------

def test_oracle_predictions_score_perfect():
    rep = acc.grade(_gt(), _gt())
    rows = rep["fields"]
    for fam in ("stage", "gold", "level", "odds", "odds.slot", "shop.name", "shop.cost",
                "scoreboard.hp", "scoreboard.level", "traits", "augment_offers"):
        row = rows[fam]
        assert row["present"] > 0, fam
        assert row["accuracy"] == 1.0, fam
        assert row["coverage"] == 1.0, fam
        assert row["false_present"] == 0, fam
    assert rows["gold"]["absent"] == 2 and rows["gold"]["absent_ok"] == 2
    assert rows["augment_offers"]["present"] == 1
    assert rows["augment_offers"]["absent_ok"] == 3
    assert rows["stage"]["verdict"] == "show"


def test_noisy_predictions_hand_counted():
    rep = acc.grade(_gt(), _noisy())
    gold = rep["fields"]["gold"]
    assert (gold["present"], gold["answered"], gold["correct"], gold["wrong"],
            gold["missed"]) == (2, 2, 1, 1, 0)
    assert gold["accuracy"] == 0.5 and gold["coverage"] == 1.0
    assert (gold["absent"], gold["absent_ok"], gold["false_present"]) == (2, 1, 1)
    assert ["12", "72", 1] in gold["confusion"]
    assert ["<absent>", "5", 1] in gold["confusion"]
    assert gold["verdict"] == "mark"

    stage = rep["fields"]["stage"]
    assert (stage["present"], stage["answered"], stage["correct"], stage["missed"]) == (4, 3, 3, 1)
    assert stage["coverage"] == 0.75 and stage["accuracy"] == 1.0
    assert ["2-4", "<absent>", 1] in stage["confusion"]

    name = rep["fields"]["shop.name"]  # 2 frames x 5 slots, empty slots included
    assert (name["present"], name["correct"], name["wrong"]) == (10, 9, 1)
    assert ["teemo", "teeno", 1] in name["confusion"]
    assert rep["fields"]["shop"]["correct"] == 1  # whole-row exact: F1 wrong, F2 right

    traits = rep["fields"]["traits"]
    assert (traits["present"], traits["correct"], traits["wrong"]) == (4, 3, 1)
    assert (traits["tp"], traits["fp"], traits["fn"]) == (11, 1, 1)
    assert traits["precision"] == pytest.approx(11 / 12)
    assert traits["recall"] == pytest.approx(11 / 12)


def test_confidence_gate_and_calibration():
    rep = acc.grade(_gt(), _noisy(), gate=0.7)
    gold = rep["fields"]["gold"]
    # F2's gold carried conf 0.6 < gate 0.7 -> treated as absent -> a miss.
    assert (gold["answered"], gold["correct"], gold["missed"]) == (1, 0, 1)
    assert gold["coverage"] == 0.5
    low = acc.grade(_gt(), _noisy(), gate=0.0)["fields"]["gold"]["calibration"]
    by_bin = {b["bin"]: b for b in low}
    assert by_bin["0.50-0.80"]["answered"] == 1 and by_bin["0.50-0.80"]["correct"] == 1
    assert by_bin["0.95-1.00"]["answered"] == 1 and by_bin["0.95-1.00"]["correct"] == 0


def test_hide_verdict_when_coverage_low():
    preds = {k: {"stage": v["stage"]} if k == FRAMES[0] else {} for k, v in _gt().items()}
    row = acc.grade(_gt(), preds)["fields"]["stage"]
    assert row["coverage"] == 0.25
    assert row["verdict"] == "hide"


def test_value_normalisation_is_case_and_space_insensitive_only():
    gt = {"f": {"stage": "2-2", "augment_offers": ["Healing Orbs II"]}}
    ok = acc.grade(gt, {"f": {"stage": " 2-2 ", "augment_offers": ["healing  orbs ii"]}})
    assert ok["fields"]["augment_offers"]["correct"] == 1
    bad = acc.grade(gt, {"f": {"stage": "2-3", "augment_offers": ["Healing Orbs I"]}})
    assert bad["fields"]["stage"]["correct"] == 0
    assert bad["fields"]["augment_offers"]["correct"] == 0


def test_accuracy_rows_match_the_store_table_columns():
    rep = acc.grade(_gt(), _noisy())
    rows = acc.accuracy_rows(rep, match_id="m1", extractor_version="x1",
                             computed_at=1700000000.0)
    assert rows
    # docs/TFT_PROGRAM.md 1.5: accuracy(match_id, field, n, correct, coverage,
    # extractor_version, computed_at)
    assert all(list(r) == ["match_id", "field", "n", "correct", "coverage",
                           "extractor_version", "computed_at"] for r in rows)
    gold = next(r for r in rows if r["field"] == "gold")
    assert (gold["n"], gold["correct"], gold["coverage"]) == (2, 1, 1.0)


# ---------------------------------------------------------------------------
# CLI on the mini corpus
# ---------------------------------------------------------------------------

def _write_extractor(tmp_path, monkeypatch, name="rc_tft06_fake_extractor"):
    preds = {k: v for k, v in _noisy().items()}
    mod = tmp_path / f"{name}.py"
    mod.write_text(textwrap.dedent(f"""
        import json
        from pathlib import Path
        PREDS = json.loads({json.dumps(json.dumps(preds))})
        def extract(frame_path):
            return PREDS.get(Path(frame_path).name, {{}})
    """), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    return f"{name}:extract"


def test_cli_skips_cleanly_without_corpus(tmp_path, capsys):
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps(_labels_doc()), encoding="utf-8")
    rc = acc.main(["--corpus", str(tmp_path / "no-such-corpus"), "--labels", str(labels)])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.startswith("SKIP:")


def test_cli_prints_per_field_table_and_json(mini_corpus, tmp_path, monkeypatch, capsys):
    corpus, labels = mini_corpus
    spec = _write_extractor(tmp_path, monkeypatch)
    out_json = tmp_path / "report.json"
    rc = acc.main(["--corpus", str(corpus), "--labels", str(labels), "--extractor", spec,
                   "--json-out", str(out_json), "--match-id", "synthetic-mini",
                   "--extractor-version", "fake-1"])
    out = capsys.readouterr().out
    assert rc == 0, out
    lines = out.splitlines()
    header = next(ln for ln in lines if ln.startswith("field"))
    for col in ("acc", "cov", "verdict"):
        assert col in header
    gold = next(ln for ln in lines if ln.split()[:1] == ["gold"])
    assert "0.500" in gold and "1.000" in gold and "mark" in gold
    rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert rep["schema"] == acc.REPORT_SCHEMA
    assert rep["frames_graded"] == 4 and rep["extractor_errors"] == 0
    assert {r["field"] for r in rep["accuracy_rows"]} >= {"gold", "stage", "shop.name"}
    assert all(r["match_id"] == "synthetic-mini" for r in rep["accuracy_rows"])


def test_cli_predictions_file_needs_no_extractor(mini_corpus, tmp_path, capsys):
    corpus, labels = mini_corpus
    preds = tmp_path / "preds.json"
    preds.write_text(json.dumps({"frames": [{"frame": k, "fields": v}
                                            for k, v in _gt().items()]}), encoding="utf-8")
    rc = acc.main(["--corpus", str(corpus), "--labels", str(labels),
                   "--predictions", str(preds)])
    out = capsys.readouterr().out
    assert rc == 0
    stage = next(ln for ln in out.splitlines() if ln.split()[:1] == ["stage"])
    assert "1.000" in stage and "show" in stage


def test_cli_labels_only_inventory_and_sha_check(mini_corpus, capsys):
    corpus, labels = mini_corpus
    assert acc.main(["--corpus", str(corpus), "--labels", str(labels)]) == 0
    out = capsys.readouterr().out
    assert "4 labelled frames" in out and "frames ok 4/4" in out
    # A frame changed on disk is reported, and --strict turns it into a failure.
    (corpus / "frames" / FRAMES[0]).write_bytes(b"tampered")
    assert acc.main(["--corpus", str(corpus), "--labels", str(labels), "--strict"]) == 1
    assert "sha256 mismatch" in capsys.readouterr().out


def test_extractor_exception_counts_as_absent_not_crash(mini_corpus, tmp_path, monkeypatch):
    corpus, labels = mini_corpus
    mod = tmp_path / "rc_tft06_boom.py"
    mod.write_text("def extract(frame_path):\n    raise RuntimeError('boom')\n",
                   encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("rc_tft06_boom", None)
    fn = acc.load_extractor("rc_tft06_boom:extract")
    preds, errors = acc.run_extractor(fn, corpus / "frames", FRAMES)
    assert errors == 4 and all(v == {} for v in preds.values())
    row = acc.grade(_gt(), preds)["fields"]["stage"]
    assert (row["answered"], row["missed"]) == (0, 4)


def test_bad_label_docs_are_rejected():
    doc = _labels_doc()
    assert acc.validate_labels(doc) == []
    bad = json.loads(json.dumps(doc))
    bad["frames"][0]["labels"]["odds"] = [50, 30, 15, 0, 0]          # sums to 95
    bad["frames"][1]["labels"]["scoreboard"][1]["local"] = True      # two local rows
    bad["frames"][2]["labels"]["mystery_field"] = 3                  # unknown field
    bad["frames"][3]["labels"]["stage"] = "two-two"                  # bad stage
    problems = " | ".join(acc.validate_labels(bad))
    for needle in ("odds", "local", "mystery_field", "stage"):
        assert needle in problems, needle
    assert acc.validate_labels({"schema": "nope", "frames": []})


# ---------------------------------------------------------------------------
# board ground truth: per-round TFTEoGStats.json and the LCU post-match document
# ---------------------------------------------------------------------------

SYNTH_NAME = "SynthPlayerName"
SYNTH_UUID = "00000000-1111-2222-3333-444444444444"


def _eog_file_doc(local_hp=100, gls=900):
    def player(local, hp, units):
        return {"PUUID": SYNTH_UUID, "riotIdGameName": SYNTH_NAME, "riotIdTagLine": "X1",
                "summonerName": SYNTH_NAME, "playerId": 7, "companionName": "c",
                "isInteractable": local, "health": hp, "ffaStanding": 0,
                "augments": [], "boardPieces": units}
    return {"gameId": 1, "queueId": 1090, "statsBlock": {
        "gameLengthSeconds": gls, "setCoreName": "TFTSet18", "players": [
            player(False, 80, [{"championName": "DA_18_Kayle", "starLevel": 1,
                                "itemNames": [], "price": 2}]),
            player(True, local_hp, [
                {"championName": "DA_18_Draven", "starLevel": 2,
                 "itemNames": ["DA_ThiefsGloves"], "price": 5},
                {"championName": "DA_Taric18", "starLevel": 1, "itemNames": [],
                 "price": 5}]),
        ]}}


def test_eog_file_ground_truth_is_scrubbed_and_local_is_p1():
    players = acc.eog_file_players(_eog_file_doc())
    blob = json.dumps(players)
    assert SYNTH_NAME not in blob and SYNTH_UUID not in blob and "X1" not in blob
    assert set(players) == {"P1", "P2"}
    assert players["P1"]["hp"] == 100
    assert [u["unit"] for u in players["P1"]["board"]] == ["Draven", "Taric"]
    assert players["P1"]["board"][0]["star"] == 2
    assert players["P1"]["board"][0]["items"] == ["Thief's Gloves"]
    assert players["P2"]["board"][0]["unit"] == "Kayle"
    assert acc.eog_file_players({"statsBlock": {"players": "garbage"}}) == {}


def test_board_grading_against_eog_snapshot():
    gt = {"f": {"players": acc.eog_file_players(_eog_file_doc())}}
    pred = {"f": {"players": {"P1": {"hp": 100, "board": [
        {"unit": "Draven", "star": 1, "items": ["Thief's Gloves"]},   # star wrong
        {"unit": "Sejuani", "star": 1, "items": []}]}}}}               # Taric missed
    rows = acc.grade(gt, pred)["fields"]
    units = rows["board.units"]
    # Precision / recall count answered records only; P2's board, never
    # predicted, is a coverage miss, not a recall loss.
    assert (units["tp"], units["fp"], units["fn"]) == (1, 1, 1)
    assert units["present"] == 2 and units["answered"] == 1 and units["missed"] == 1
    stars = rows["board.stars"]
    assert (stars["tp"], stars["fp"], stars["fn"]) == (0, 2, 2)
    items = rows["board.items"]
    assert (items["tp"], items["fp"], items["fn"]) == (1, 0, 0)
    assert rows["hp"]["correct"] == 1 and rows["hp"]["missed"] == 1


def test_lcu_eog_final_boards_and_placement():
    doc = {"gameId": 1000000001, "localPlayer": {"isLocalPlayer": True},
           "players": [
               {"isLocalPlayer": False, "ffaStanding": 1, "health": 247,
                "riotIdGameName": SYNTH_NAME, "boardPieces": [
                    {"championId": "DA_Vi18", "name": "Vi", "level": 2, "items": []}]},
               {"isLocalPlayer": True, "ffaStanding": 2, "health": 0,
                "riotIdGameName": SYNTH_NAME, "boardPieces": [
                    {"championId": "DA_Draven18", "name": "Draven", "level": 2,
                     "items": [{"nameId": "DA_ThiefsGloves", "name": "Thief's Gloves"}]}]},
           ]}
    gt = acc.lcu_eog_ground_truth(doc)
    assert SYNTH_NAME not in json.dumps(gt)
    assert gt["placement"] == 2
    assert gt["players"]["P1"]["board"] == [
        {"unit": "Draven", "star": 2, "items": ["Thief's Gloves"]}]
    assert "hp" not in gt["players"]["P2"]   # non-local LCU health is not HP


def test_adapters_refuse_to_key_players_without_a_local_player():
    doc = _eog_file_doc()
    for p in doc["statsBlock"]["players"]:
        p["isInteractable"] = False
    assert acc.eog_file_players(doc) == {}
    assert acc.lcu_eog_ground_truth({"players": [
        {"isLocalPlayer": False, "boardPieces": []}] * 8}) == {}
    nine = _eog_file_doc()
    nine["statsBlock"]["players"] = nine["statsBlock"]["players"] * 5   # 10 rows
    assert acc.eog_file_players(nine) == {}


def test_two_argument_extractor_gets_frame_meta_not_labels(mini_corpus, tmp_path,
                                                          monkeypatch, capsys):
    corpus, labels = mini_corpus
    (corpus / "frames.jsonl").write_text("\n".join(json.dumps(
        {"t": 500.0 + i, "file": f"frames/{n}"}) for i, n in enumerate(FRAMES)),
        encoding="utf-8")
    seen = tmp_path / "seen.json"
    mod = tmp_path / "rc_tft06_meta.py"
    mod.write_text(textwrap.dedent(f"""
        import json
        SEEN = []
        def extract(frame_path, meta):
            SEEN.append(meta)
            open({str(seen)!r}, "w").write(json.dumps(SEEN))
            return {{}}
    """), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("rc_tft06_meta", None)
    assert acc.main(["--corpus", str(corpus), "--labels", str(labels),
                     "--extractor", "rc_tft06_meta:extract"]) == 0
    capsys.readouterr()
    metas = json.loads(seen.read_text())
    assert [m["frame"] for m in metas] == FRAMES
    assert [m["t"] for m in metas] == [500.0, 501.0, 502.0, 503.0]
    assert all(set(m) == {"frame", "t"} for m in metas)


def test_align_frames_to_latest_snapshot_within_a_round():
    frames = {"a.jpg": 100.0, "b.jpg": 165.0, "c.jpg": 400.0, "d.jpg": 50.0}
    idx = acc.align_frames(frames, [90.0, 160.0, 220.0], max_age_s=75.0)
    assert idx == {"a.jpg": 0, "b.jpg": 1}   # c too old, d before any snapshot


def test_cli_grades_boards_from_eog_snapshot_dir(mini_corpus, tmp_path, monkeypatch, capsys):
    corpus, labels = mini_corpus
    snaps = tmp_path / "eog"
    snaps.mkdir()
    doc = _eog_file_doc()
    doc["_rc_captured_at"] = 1000.0
    (snaps / "round_01.json").write_text(json.dumps(doc), encoding="utf-8")
    (corpus / "frames.jsonl").write_text("\n".join(json.dumps(
        {"t": 1010.0 + i, "file": f"frames/{n}"}) for i, n in enumerate(FRAMES)),
        encoding="utf-8")
    preds = tmp_path / "preds.json"
    board = {"P1": {"board": [{"unit": "Draven", "star": 2, "items": ["Thief's Gloves"]},
                              {"unit": "Taric", "star": 1, "items": []}]}}
    preds.write_text(json.dumps({k: {**v, "players": board} for k, v in _gt().items()}),
                     encoding="utf-8")
    out_json = tmp_path / "report.json"
    rc = acc.main(["--corpus", str(corpus), "--labels", str(labels),
                   "--predictions", str(preds), "--eog", str(snaps),
                   "--json-out", str(out_json)])
    out = capsys.readouterr().out
    assert rc == 0, out
    units = next(ln for ln in out.splitlines() if ln.split()[:1] == ["board.units"])
    assert "1.000" in units and "0.500" in units       # exact on P1, P2 uncovered
    row = json.loads(out_json.read_text(encoding="utf-8"))["fields"]["board.units"]
    assert row["tp"] == 8 and row["fp"] == 0 and row["fn"] == 0   # 4 frames x 2 units
    assert row["missed"] == 4                                      # P2, never predicted


def test_cli_no_labels_mode_grades_a_new_match_from_files_only(mini_corpus, tmp_path, capsys):
    """Post-match QA path: no hand labels, ground truth = per-round EoG + LCU EoG."""
    corpus, _labels = mini_corpus
    snaps = tmp_path / "eog"
    snaps.mkdir()
    doc = _eog_file_doc()
    doc["_rc_captured_at"] = 1000.0
    (snaps / "r1.json").write_text(json.dumps(doc), encoding="utf-8")
    (corpus / "frames.jsonl").write_text("\n".join(json.dumps(
        {"t": 1010.0 + i, "file": f"frames/{n}"}) for i, n in enumerate(FRAMES)),
        encoding="utf-8")
    lcu = tmp_path / "lcu.json"
    lcu.write_text(json.dumps({"players": [
        {"isLocalPlayer": True, "ffaStanding": 1, "health": 100, "boardPieces": [
            {"name": "Draven", "level": 2, "items": [{"name": "Thief's Gloves"}]}]}]}),
        encoding="utf-8")
    preds = tmp_path / "preds.json"
    pl = {"P1": {"hp": 100, "board": [{"unit": "Draven", "star": 2, "items": ["Thief's Gloves"]}]}}
    preds.write_text(json.dumps({**{n: {"players": pl} for n in FRAMES},
                                 "final": {"players": pl, "placement": 1}}), encoding="utf-8")
    out_json = tmp_path / "r.json"
    rc = acc.main(["--corpus", str(corpus), "--no-labels", "--eog", str(snaps),
                   "--lcu-eog", str(lcu), "--predictions", str(preds),
                   "--json-out", str(out_json), "--match-id", "m-new"])
    assert rc == 0, capsys.readouterr().out
    rep = json.loads(out_json.read_text(encoding="utf-8"))
    assert rep["labels"] is None and rep["frames_graded"] == 4
    assert rep["fields"]["placement"]["correct"] == 1
    assert rep["fields"]["hp"]["correct"] == 5          # 4 frames (P1) + final
    assert rep["fields"]["board.units"]["fn"] == 4      # Taric, on every frame


# ---------------------------------------------------------------------------
# the committed label set
# ---------------------------------------------------------------------------

def _fixture():
    return json.loads(LABELS_FIXTURE.read_text(encoding="utf-8"))


def test_label_fixture_is_valid_and_covers_half_the_corpus():
    doc = _fixture()
    assert acc.validate_labels(doc) == []
    names = [f["frame"] for f in doc["frames"]]
    assert len(names) >= 40                          # TFT-06: >= 40 of the 80 frames
    assert len(set(names)) == len(names)
    assert all(re.fullmatch(r"game_\d{4}_el\d{4}\.jpg", n) for n in names)
    assert all(re.fullmatch(r"[0-9a-f]{64}", f["sha256"]) for f in doc["frames"])
    # Every spec 3.4 C field is labelled on at least one frame with a real value.
    present = Counter()
    for f in doc["frames"]:
        for k, v in f["labels"].items():
            if v is not None:
                present[k] += 1
    for field in ("gold", "level", "xp_cur", "xp_max", "stage", "timer", "streak",
                  "odds", "shop", "traits", "scoreboard", "hp_local"):
        assert present[field] >= 20, field
    # ... and hidden panels are labelled absent on some frames, so a reader that
    # hallucinates a value on a collapsed shop is caught.
    assert sum(1 for f in doc["frames"] if f["labels"].get("gold", 0) is None) >= 4


def test_label_fixture_is_scrubbed():
    doc = _fixture()
    assert acc.scrub_problems(doc, acc.label_vocab(18)) == []
    blob = LABELS_FIXTURE.read_text(encoding="utf-8")
    assert blob.isascii()
    assert not re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                         r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", blob)
    # The guard itself is not vacuous: a smuggled name or identity key is caught.
    planted = json.loads(blob)
    planted["frames"][0]["labels"]["shop"] = [{"name": "SomePlayer#EUW", "cost": 1,
                                               "kind": "champion"}, None, None, None, None]
    planted["frames"][1]["riotIdGameName"] = "x"
    problems = " | ".join(acc.scrub_problems(planted, acc.label_vocab(18)))
    assert "SomePlayer#EUW" in problems and "riotIdGameName" in problems


def test_label_fixture_was_verified_by_a_second_labeller():
    ver = _fixture()["verification"]
    assert ver["author"] and ver["verifier"] and ver["author"] != ver["verifier"]
    assert ver["frames_compared"] == len(_fixture()["frames"])
    assert ver["values_compared"] > 0
    assert ver["adjudicated"] == ver["disagreements"]


def test_label_fixture_matches_the_local_corpus():
    frames_dir = REAL_CORPUS / "frames"
    if not frames_dir.is_dir():
        pytest.skip("local TFT corpus absent (gitignored ops/runtime/tft_qa)")
    problems = acc.frame_sha_problems(_fixture(), frames_dir)
    assert problems == []
