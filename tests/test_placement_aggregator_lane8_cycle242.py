"""Lane 8 (true-audit) s144 cycle 242: tft/placement_aggregator.py.

Pins the hardening of the TFT placement heatmap builder:

- build_heatmap() / update_heatmap() resolve their default paths at CALL
  time, so a redirected module global (tests/conftest.py) is the directory
  actually read, and update_heatmap reads the same directory it creates;
- one malformed rating file (non-dict body, non-dict positions, junk cells,
  a non-string legacy placement) is skipped, never aborts the whole build;
- an unreadable file is logged with its name; an unexpected error still
  surfaces (the handler is narrowed, not blind);
- parse_unit_placement keeps a dotted name whole, refuses a two-digit
  column instead of reading it as the first digit, and returns {} for a
  non-string.

All files are synthetic and live under tmp_path.
"""
import json
import logging

import pytest

import tft.placement_aggregator as pa


def _rating(path, **fields):
    body = {"mode_category": "TFT"}
    body.update(fields)
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


# --- parse_unit_placement -------------------------------------------------

def test_parse_characterization_names_with_apostrophe_and_ampersand():
    got = pa.parse_unit_placement("Karma D3, Jhin D6, Cho'Gath A1, Nunu & Willump B2")
    assert got == {"Karma": "D3", "Jhin": "D6", "Cho'Gath": "A1", "Nunu & Willump": "B2"}


def test_parse_keeps_a_dotted_name_whole():
    got = pa.parse_unit_placement("Dr. Mundo A1, Jinx D7")
    assert got == {"Dr. Mundo": "A1", "Jinx": "D7"}


def test_parse_refuses_a_two_digit_column():
    # "D10" is off the 7-column board; it must not be read as D1.
    assert pa.parse_unit_placement("Jinx D10") == {}
    assert pa.parse_unit_placement("Jinx D10, Vi A2") == {"Vi": "A2"}


@pytest.mark.parametrize("junk", [None, 5, ["Jinx D7"], {"Jinx": "D7"}, b"Jinx D7"])
def test_parse_non_string_returns_empty(junk):
    assert pa.parse_unit_placement(junk) == {}


@pytest.mark.parametrize("sentinel", ["-", "N/A", "n/a", "none", "None", "  "])
def test_parse_sentinels_are_empty(sentinel):
    assert pa.parse_unit_placement(sentinel) == {}


def test_parse_one_letter_name_is_not_a_unit():
    assert pa.parse_unit_placement("X D7") == {}


def test_parse_lowercase_row_is_normalised():
    assert pa.parse_unit_placement("Jinx d7") == {"Jinx": "D7"}


# --- build_heatmap: default path resolution -------------------------------

def test_build_heatmap_default_dir_is_resolved_at_call_time(tmp_path, monkeypatch):
    d = tmp_path / "ratings"
    d.mkdir()
    _rating(d / "last_tft.json", tft_unit_positions={"Jinx": "D7"})
    monkeypatch.setattr(pa, "_RATINGS_DIR", d)
    heat = pa.build_heatmap()
    assert heat["games_counted"] == 1
    assert heat["positions"]["Jinx"]["top_cell"] == "D7"


def test_update_heatmap_reads_the_dir_it_creates(tmp_path, monkeypatch):
    d = tmp_path / "ratings"
    out = tmp_path / "heat.json"
    monkeypatch.setattr(pa, "_RATINGS_DIR", d)
    monkeypatch.setattr(pa, "_HEATMAP_FILE", out)
    d.mkdir()
    _rating(d / "last_tft.json", tft_unit_positions={"Jinx": "D7"})
    assert pa.update_heatmap() == 1
    assert json.loads(out.read_text(encoding="utf-8"))["games_counted"] == 1


def test_update_heatmap_explicit_paths(tmp_path):
    d = tmp_path / "r"
    out = tmp_path / "sub" / "h.json"
    n = pa.update_heatmap(ratings_dir=d, heatmap_file=out)
    assert n == 0
    assert d.is_dir()
    assert json.loads(out.read_text(encoding="utf-8"))["positions"] == {}


# --- build_heatmap: one bad file never aborts the build --------------------

_JUNK_BODIES = {
    "list_body": [1, 2, 3],
    "string_body": "TFT",
    "null_body": None,
    "positions_list": {"mode_category": "TFT", "tft_unit_positions": ["Jinx D7"]},
    "positions_string": {"mode_category": "TFT", "tft_unit_positions": "Jinx D7"},
    "cell_list": {"mode_category": "TFT", "tft_unit_positions": {"Ahri": ["D", 7]}},
    "cell_null": {"mode_category": "TFT", "tft_unit_positions": {"Ahri": None}},
    "placement_int": {"mode_category": "TFT", "tft_unit_placement": 5},
    "placement_list": {"mode_category": "TFT", "tft_unit_placement": ["Ahri D7"]},
}


@pytest.mark.parametrize("name", sorted(_JUNK_BODIES))
def test_one_malformed_file_does_not_abort_the_build(tmp_path, name):
    (tmp_path / f"a_{name}.json").write_text(json.dumps(_JUNK_BODIES[name]), encoding="utf-8")
    _rating(tmp_path / "z_good.json", tft_unit_positions={"Jinx": "D7"})
    heat = pa.build_heatmap(tmp_path)
    assert heat["games_counted"] == 1
    assert set(heat["positions"]) == {"Jinx"}


def test_off_board_cells_are_dropped_not_aggregated(tmp_path):
    _rating(tmp_path / "a.json", tft_unit_positions={
        "Jinx": "D7", "Vi": "bench", "Ahri": "E1", "Lux": "D8", "Zed": "A0", "Sona": "d3"})
    heat = pa.build_heatmap(tmp_path)
    assert heat["games_counted"] == 1
    assert set(heat["positions"]) == {"Jinx", "Sona"}
    assert heat["positions"]["Sona"]["top_cell"] == "D3"


def test_all_invalid_positions_fall_back_to_legacy_string(tmp_path):
    _rating(tmp_path / "a.json", tft_unit_positions={"Vi": "bench"},
            tft_unit_placement="Jinx D7")
    heat = pa.build_heatmap(tmp_path)
    assert heat["games_counted"] == 1
    assert set(heat["positions"]) == {"Jinx"}


def test_blank_unit_name_is_dropped(tmp_path):
    _rating(tmp_path / "a.json", tft_unit_positions={"  ": "D7", "Jinx": "D6"})
    heat = pa.build_heatmap(tmp_path)
    assert set(heat["positions"]) == {"Jinx"}


def test_unreadable_file_is_logged_by_name(tmp_path, caplog):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "badbytes.json").write_bytes(b"\xff\xfe\x00junk")
    caplog.set_level(logging.WARNING, logger="rc.tft.heatmap")
    heat = pa.build_heatmap(tmp_path)
    assert heat["games_counted"] == 0
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "broken.json" in text
    assert "badbytes.json" in text


def test_unexpected_error_surfaces(tmp_path, monkeypatch):
    _rating(tmp_path / "a.json", tft_unit_positions={"Jinx": "D7"})

    def _boom(*_a, **_k):
        raise RuntimeError("not a file-read failure")

    monkeypatch.setattr(pa.json, "loads", _boom)
    with pytest.raises(RuntimeError):
        pa.build_heatmap(tmp_path)


def test_missing_dir_is_an_empty_heatmap(tmp_path):
    heat = pa.build_heatmap(tmp_path / "absent")
    assert heat["games_counted"] == 0
    assert heat["positions"] == {}


# --- characterization of the aggregate shape -------------------------------

def test_aggregate_shape_and_percentages(tmp_path):
    _rating(tmp_path / "a.json", tft_unit_positions={"Jinx": "D7", "Vi": "A1"})
    _rating(tmp_path / "b.json", tft_unit_positions={"Jinx": "D7"})
    _rating(tmp_path / "c.json", tft_unit_placement="Jinx D1, Vi A1")
    (tmp_path / "d.json").write_text(json.dumps(
        {"mode_category": "SR", "tft_unit_positions": {"Jinx": "A1"}}), encoding="utf-8")
    heat = pa.build_heatmap(tmp_path)
    assert heat["version"] == 2
    assert heat["games_counted"] == 3
    jinx = heat["positions"]["Jinx"]
    assert jinx["games"] == 3
    assert jinx["top_cell"] == "D7"
    assert jinx["cells"] == {"D7": {"count": 2, "pct": 66.7}, "D1": {"count": 1, "pct": 33.3}}
    assert list(jinx["cells"]) == ["D7", "D1"]
    assert heat["positions"]["Vi"] == {"cells": {"A1": {"count": 2, "pct": 100.0}},
                                       "top_cell": "A1", "games": 2}
