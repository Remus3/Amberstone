"""Hardening pins for core/aram_tenacity_context.py (s144 true-audit, S144-T-712).

Each test names the defect it pins:

* DISPLAY NAMES (S144-T-142): the ARAM coach passes the Live Client
  ``championName``, which is the DISPLAY name ("Kha'Zix", "Nunu & Willump"),
  while the map is keyed by the DDragon id ("Khazix", "Nunu"). Measured at
  16.22.1: 2 of the 16 modified champions rendered no tenacity line, own or
  enemy, in every game.
* JUNK SHAPES: a non-object champions.json, a non-dict ``lolmath`` or
  ``aram_modifiers``, or a deeply nested document raised out of the
  module-level loader - i.e. out of ``import coaches.aram_coach``.
* VALUES: ``json.loads`` accepts NaN / Infinity; a NaN multiplier rendered
  "nanx", a zero or negative one rendered a CC window that cannot exist.
* CALLER INPUT: a non-str mode raised AttributeError, an unhashable champion
  or enemy entry raised TypeError, a padded mode was refused, a duplicated
  enemy was listed twice.
* SILENT FAILURE: a failed read returned {} with no log line.
"""
from __future__ import annotations

import json
import logging

import pytest

from core import aram_tenacity_context as mod


def _ds_dir(tmp_path, data, patch="16.99.9", current=None, raw=None):
    (tmp_path / "current.txt").write_text(
        patch if current is None else current, encoding="utf-8")
    (tmp_path / patch).mkdir(exist_ok=True)
    body = raw if raw is not None else json.dumps({"data": data})
    (tmp_path / patch / "champions.json").write_text(body, encoding="utf-8")
    return tmp_path


def _row(mult, name=None):
    row = {"lolmath": {"aram_modifiers": {"aramTenacity": mult}}}
    if name is not None:
        row["name"] = name
    return row


# ---------------------------------------------------------------- display names

def test_live_display_names_resolve_to_the_id_row():
    # Live snapshot (16.22.1): Khazix / Nunu carry 1.20 under their ids.
    assert mod.get_tenacity_mult("Kha'Zix") == pytest.approx(1.20)
    assert mod.get_tenacity_mult("Nunu & Willump") == pytest.approx(1.20)
    assert mod.get_tenacity_mult("kha'zix") == pytest.approx(1.20)
    assert mod.get_tenacity_mult("  Kha'Zix  ") == pytest.approx(1.20)
    # The id keeps working.
    assert mod.get_tenacity_mult("Khazix") == pytest.approx(1.20)


def test_own_line_renders_for_a_display_name():
    line = mod.aram_tenacity_line("Kha'Zix", "ARAM")
    assert line.startswith("ARAM tenacity: 1.20x")


def test_enemy_line_renders_display_names():
    line = mod.enemy_aram_tenacity_line(["Kha'Zix", "Nunu & Willump", "Garen"],
                                        "ARAM")
    assert "Kha'Zix 1.20x" in line
    assert "Nunu & Willump 1.20x" in line
    assert "Garen" not in line
    line.encode("ascii")


def test_shared_exact_display_name_maps_to_neither():
    data = {"A": _row(1.2, "Same"), "B": _row(1.1, "Same")}
    aliases = mod._aliases_from(data)
    assert "Same" not in aliases
    assert "same" not in aliases
    assert aliases["A"] == "A" and aliases["B"] == "B"


def test_display_name_equal_to_another_id_keeps_the_id():
    data = {"A": _row(1.2, "B"), "B": _row(1.1, "Bee")}
    aliases = mod._aliases_from(data)
    assert aliases["B"] == "B"


# ---------------------------------------------------------------- junk shapes

@pytest.mark.parametrize("raw", ["[]", '"text"', "5", "null"])
def test_non_object_document_is_empty_not_a_raise(tmp_path, monkeypatch, raw):
    monkeypatch.setattr(mod, "_DATA_DIR", _ds_dir(tmp_path, {}, raw=raw))
    assert mod._load_tenacity_map() == {}


@pytest.mark.parametrize("row", [
    {"lolmath": ["x"]},
    {"lolmath": "x"},
    {"lolmath": {"aram_modifiers": ["x"]}},
    {"lolmath": {"aram_modifiers": "x"}},
])
def test_junk_row_is_skipped_and_the_rest_load(tmp_path, monkeypatch, row):
    data = {"Bad": row, "Zed": _row(1.2, "Zed")}
    monkeypatch.setattr(mod, "_DATA_DIR", _ds_dir(tmp_path, data))
    assert mod._load_tenacity_map() == {"Zed": 1.2}


def test_deeply_nested_document_is_empty_not_a_raise(tmp_path, monkeypatch):
    raw = "[" * 100000 + "]" * 100000
    monkeypatch.setattr(mod, "_DATA_DIR", _ds_dir(tmp_path, {}, raw=raw))
    assert mod._load_tenacity_map() == {}


def test_build_maps_on_junk_never_raises(tmp_path, monkeypatch):
    # _build_maps is what the module runs at import.
    monkeypatch.setattr(mod, "_DATA_DIR", _ds_dir(tmp_path, {}, raw="[1]"))
    assert mod._build_maps() == ({}, {}, {})


def test_bom_current_txt_is_read(tmp_path, monkeypatch):
    d = _ds_dir(tmp_path, {"Zed": _row(1.2)})
    (d / "current.txt").write_text(chr(0xFEFF) + "16.99.9\n",
                                   encoding="utf-8")
    monkeypatch.setattr(mod, "_DATA_DIR", d)
    assert mod._load_tenacity_map() == {"Zed": 1.2}


@pytest.mark.parametrize("token", ["../16.99.9", "a/b", "a\\b", "C:x", ".."])
def test_patch_token_naming_another_directory_is_refused(tmp_path, monkeypatch,
                                                         token):
    d = _ds_dir(tmp_path, {"Zed": _row(1.2)}, current=token)
    monkeypatch.setattr(mod, "_DATA_DIR", d)
    assert mod._load_tenacity_map() == {}


def test_patch_token_escaping_to_a_real_snapshot_is_refused(tmp_path,
                                                           monkeypatch):
    # The escape target EXISTS and is valid, so only the token guard can
    # stop the read (a missing target would read as empty anyway).
    ds = tmp_path / "ds"
    ds.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "champions.json").write_text(
        json.dumps({"data": {"Zed": _row(1.2)}}), encoding="utf-8")
    (ds / "current.txt").write_text("../other", encoding="utf-8")
    monkeypatch.setattr(mod, "_DATA_DIR", ds)
    assert mod._load_tenacity_map() == {}


# ---------------------------------------------------------------- values

@pytest.mark.parametrize("bad", [
    "NaN", "Infinity", "-Infinity", "true", "false", "0", "-1.2", '"nan"',
    '"inf"', "[1.2]", "{}",
])
def test_unusable_multiplier_is_neutral(tmp_path, monkeypatch, bad):
    raw = ('{"data": {"Bad": {"lolmath": {"aram_modifiers": '
           '{"aramTenacity": ' + bad + '}}}, "Zed": {"lolmath": '
           '{"aram_modifiers": {"aramTenacity": 1.2}}}}}')
    monkeypatch.setattr(mod, "_DATA_DIR", _ds_dir(tmp_path, {}, raw=raw))
    assert mod._load_tenacity_map() == {"Zed": 1.2}


def test_numeric_string_multiplier_still_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_DATA_DIR",
                        _ds_dir(tmp_path, {"Zed": _row("1.2")}))
    assert mod._load_tenacity_map() == {"Zed": 1.2}


def test_non_string_id_is_skipped(tmp_path, monkeypatch):
    # JSON object keys are always strings; guard the in-memory seam.
    assert mod._tenacity_from({5: _row(1.2), "Zed": _row(1.2)}) == {"Zed": 1.2}


# ---------------------------------------------------------------- caller input

@pytest.mark.parametrize("mode", [5, ["ARAM"], {"ARAM": 1}, b"ARAM", 1.5])
def test_non_str_mode_is_empty_not_a_raise(mode):
    assert mod.aram_tenacity_line("Zed", mode) == ""
    assert mod.enemy_aram_tenacity_line(["Zed"], mode) == ""


def test_padded_mode_is_accepted():
    assert mod.aram_tenacity_line("Zed", " aram ").startswith("ARAM tenacity")
    assert "Zed 1.20x" in mod.enemy_aram_tenacity_line(["Zed"], "KIWI\n")


@pytest.mark.parametrize("champ", [["Zed"], {"Zed": 1}, 5, b"Zed", 1.2])
def test_non_str_champion_is_neutral_not_a_raise(champ):
    assert mod.get_tenacity_mult(champ) == 1.0
    assert mod.aram_tenacity_line(champ, "ARAM") == ""


def test_unhashable_enemy_entry_is_skipped():
    line = mod.enemy_aram_tenacity_line([{"x": 1}, ["Talon"], "Zed"], "ARAM")
    assert line == "Enemy ARAM tenacity (your CC on them lasts longer): Zed 1.20x"


def test_bare_string_enemies_is_empty():
    assert mod.enemy_aram_tenacity_line("Zed", "ARAM") == ""


@pytest.mark.parametrize("enemies", [{"Zed": 1}, {"Zed"}, iter(["Zed"])])
def test_non_sequence_enemies_is_empty(enemies):
    # The contract is a list / tuple of names; a mapping would be read by
    # its keys and a set in no stable order.
    assert mod.enemy_aram_tenacity_line(enemies, "ARAM") == ""


def test_duplicate_enemy_listed_once():
    line = mod.enemy_aram_tenacity_line(["Zed", "zed", "Zed"], "ARAM")
    assert line.count("1.20x") == 1


def test_enemy_label_is_the_canonical_display_name():
    # An id or a mis-cased spelling renders as the snapshot display name.
    line = mod.enemy_aram_tenacity_line(["Khazix", "NUNU & WILLUMP"], "ARAM")
    assert "Kha'Zix 1.20x" in line
    assert "Nunu & Willump 1.20x" in line


# ---------------------------------------------------------------- silent failure

def test_failed_read_logs_one_warning_without_the_path(tmp_path, monkeypatch,
                                                       caplog):
    d = _ds_dir(tmp_path, {}, raw="{not json")
    monkeypatch.setattr(mod, "_DATA_DIR", d)
    with caplog.at_level(logging.WARNING, logger=mod.__name__):
        assert mod._build_maps() == ({}, {}, {})
    recs = [r for r in caplog.records if r.name == mod.__name__]
    assert len(recs) == 1
    msg = recs[0].getMessage()
    assert "champions.json" in msg
    assert str(tmp_path) not in msg
    assert "not json" not in msg
