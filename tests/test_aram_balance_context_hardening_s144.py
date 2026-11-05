"""S144 true-audit cycle 115 - hardening pins for ``core/aram_balance_context``.

Each test names the weakness it reproduces. They were written RED against the
pre-audit module and each was mutation-checked against the fix.

* DISPLAY NAME - the ARAM coach passes the Live Client ``championName`` (a
  DISPLAY name: "Miss Fortune", "Kai'Sa", "Nunu & Willump") while the map is
  keyed by the DDragon id ("MissFortune", "Kaisa", "Nunu"). Measured on patch
  16.21.1: 15 of the 123 non-neutral champions rendered an EMPTY balance line
  in every ARAM game. The lookup now resolves a display name to its id from
  the same champions.json ``name`` field.
* JUNK SHAPE AT IMPORT - a top-level JSON list, a truthy non-dict ``lolmath``
  or a non-dict ``aram_modifiers`` raised AttributeError inside the loaders,
  which run at IMPORT, so one bad extract made ``coaches.aram_coach``
  unimportable. Now each degrades (the whole file, or that one champion).
* NON-FINITE / NONSENSE VALUES - ``json.loads`` accepts ``NaN`` and
  ``Infinity``; a NaN multiplier made ``aram_balance_line`` raise
  ValueError (``round(nan)``) and put a bare ``NaN`` into the grid route's
  JSON. A bool, zero or negative multiplier rendered "deal -100%". Such a
  value now falls back to neutral for that field.
* JUNK CALL ARGS - an unhashable champion raised TypeError and a non-str mode
  raised AttributeError; both now return the neutral / empty answer.
* PATCH TOKEN - ``current.txt`` holding a BOM (PowerShell 5.1 ``UTF8``
  writes one) silently emptied both maps, and one holding a path segment
  ("../x") read a champions.json OUTSIDE the data dir. The BOM is stripped;
  a token with a separator or ``..`` is refused.
* SILENT EMPTY - a failed load returned ``{}`` with no log line, so the
  coach lost its balance line with nothing to say why. It now logs one
  warning naming the cause class (never file contents).
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import pytest

from core import aram_balance_context as mod

PATCH = "16.99.9"


def _plant(tmp_path: Path, payload, *, patch_text: str = PATCH,
           raw: str | None = None) -> Path:
    """Write current.txt + <patch>/champions.json under tmp_path."""
    (tmp_path / "current.txt").write_text(patch_text, encoding="utf-8")
    pdir = tmp_path / PATCH
    pdir.mkdir(parents=True, exist_ok=True)
    body = raw if raw is not None else json.dumps(payload)
    (pdir / "champions.json").write_text(body, encoding="utf-8")
    return tmp_path


def _champ(cid: str, name: str, **mods) -> dict:
    return {cid: {"id": cid, "name": name,
                  "lolmath": {"aram_modifiers": dict(mods)}}}


def _reload_into(monkeypatch, data_dir: Path) -> None:
    """Point the module at data_dir and rebuild its import-time maps."""
    monkeypatch.setattr(mod, "_DATA_DIR", data_dir)
    balance, grid, aliases = mod._build_maps()
    monkeypatch.setattr(mod, "_BALANCE_MAP", balance)
    monkeypatch.setattr(mod, "_BALANCE_GRID_MAP", grid)
    monkeypatch.setattr(mod, "_ALIASES", aliases)


# --------------------------------------------------------------------------
# DISPLAY NAME
# --------------------------------------------------------------------------

def _display_fixture() -> dict:
    data: dict = {}
    data.update(_champ("MissFortune", "Miss Fortune",
                       aramDamageDealt=0.95, aramDamageTaken=1.05))
    data.update(_champ("Kaisa", "Kai'Sa", aramDamageDealt=1.05))
    data.update(_champ("Nunu", "Nunu & Willump", aramDamageTaken=0.9))
    data.update(_champ("DrMundo", "Dr. Mundo", aramHealing=0.8))
    data.update(_champ("Ahri", "Ahri", aramDamageDealt=1.1))
    return {"data": data}


def test_display_name_resolves_balance_line(tmp_path, monkeypatch):
    _reload_into(monkeypatch, _plant(tmp_path, _display_fixture()))
    assert mod.aram_balance_line("Miss Fortune", "ARAM") == (
        "ARAM balance: you deal -5%, take +5% damage")
    assert mod.aram_balance_line("Kai'Sa", "KIWI") == (
        "ARAM balance: you deal +5% damage")
    assert mod.get_balance_mults("Nunu & Willump") == (1.0, 0.9)


def test_display_name_resolves_grid(tmp_path, monkeypatch):
    _reload_into(monkeypatch, _plant(tmp_path, _display_fixture()))
    assert mod.balance_grid_for("Dr. Mundo") == {"aramHealing": 0.8}
    # The id form keeps working, and the full map stays keyed by id.
    assert mod.balance_grid_for("DrMundo") == {"aramHealing": 0.8}
    assert "DrMundo" in mod.balance_grid_map()
    assert "Dr. Mundo" not in mod.balance_grid_map()


def test_id_form_and_unknown_unchanged(tmp_path, monkeypatch):
    _reload_into(monkeypatch, _plant(tmp_path, _display_fixture()))
    assert mod.get_balance_mults("MissFortune") == (0.95, 1.05)
    assert mod.get_balance_mults("Ahri") == (1.1, 1.0)
    assert mod.get_balance_mults("NotAChampion") == (1.0, 1.0)
    assert mod.aram_balance_line("NotAChampion", "ARAM") == ""


def test_live_snapshot_display_names_resolve():
    """Against the shipped patch: every non-neutral champion whose display
    name differs from its id must render the same line under both forms."""
    assert mod._ALIASES, "live snapshot produced no alias map"
    patch = (mod._DATA_DIR / "current.txt").read_text(
        encoding="utf-8-sig").strip()
    rows = json.loads((mod._DATA_DIR / patch / "champions.json").read_text(
        encoding="utf-8"))["data"]
    checked = 0
    for cid in mod._BALANCE_MAP:
        display = (rows.get(cid) or {}).get("name") or cid
        if display == cid:
            continue
        checked += 1
        assert mod.aram_balance_line(display, "ARAM") == (
            mod.aram_balance_line(cid, "ARAM")), (cid, display)
        assert mod.aram_balance_line(display, "ARAM") != ""
    assert checked > 0


def test_ambiguous_normalised_alias_is_dropped(tmp_path, monkeypatch):
    data: dict = {}
    data.update(_champ("Foo", "Foo Bar", aramDamageDealt=1.1))
    data.update(_champ("FooBar", "Other", aramDamageDealt=0.9))
    _reload_into(monkeypatch, _plant(tmp_path, {"data": data}))
    # Exact id still wins for both.
    assert mod.get_balance_mults("Foo") == (1.1, 1.0)
    assert mod.get_balance_mults("FooBar") == (0.9, 1.0)
    # The exact display name of Foo resolves to Foo, not FooBar.
    assert mod.get_balance_mults("Foo Bar") == (1.1, 1.0)
    # A normalised form shared by two ids ("foobar") resolves to neither
    # by guess - only an exact match may answer.
    assert mod.get_balance_mults("foo bar") == (1.0, 1.0)


# --------------------------------------------------------------------------
# JUNK SHAPE AT IMPORT
# --------------------------------------------------------------------------

@pytest.mark.parametrize("loader", ["_load_balance_map", "_load_balance_grid_map"])
def test_top_level_list_degrades(tmp_path, monkeypatch, loader):
    monkeypatch.setattr(mod, "_DATA_DIR", _plant(tmp_path, [1, 2, 3]))
    assert getattr(mod, loader)() == {}


@pytest.mark.parametrize("loader", ["_load_balance_map", "_load_balance_grid_map"])
def test_non_dict_lolmath_skips_only_that_champ(tmp_path, monkeypatch, loader):
    data = {"Bad": {"lolmath": "oops"}, "Bad2": {"lolmath": [1]}}
    data.update(_champ("Good", "Good", aramDamageDealt=1.1))
    monkeypatch.setattr(mod, "_DATA_DIR", _plant(tmp_path, {"data": data}))
    out = getattr(mod, loader)()
    assert set(out) == {"Good"}


def test_non_dict_aram_modifiers_skips_champ(tmp_path, monkeypatch):
    data = {"Bad": {"lolmath": {"aram_modifiers": ["x"]}}}
    data.update(_champ("Good", "Good", aramDamageTaken=0.9))
    monkeypatch.setattr(mod, "_DATA_DIR", _plant(tmp_path, {"data": data}))
    assert set(mod._load_balance_map()) == {"Good"}


# --------------------------------------------------------------------------
# NON-FINITE / NONSENSE VALUES
# --------------------------------------------------------------------------

_JUNK_MULTS = ["NaN", "Infinity", "-Infinity", "true", "false", "0", "-0.5"]


@pytest.mark.parametrize("junk", _JUNK_MULTS)
def test_junk_multiplier_falls_back_neutral(tmp_path, monkeypatch, junk):
    raw = ('{"data": {"X": {"id": "X", "name": "X", "lolmath": '
           '{"aram_modifiers": {"aramDamageDealt": ' + junk + ', '
           '"aramDamageTaken": 0.9, "aramHealing": ' + junk + '}}}}}')
    _reload_into(monkeypatch, _plant(tmp_path, None, raw=raw))
    assert mod.get_balance_mults("X") == (1.0, 0.9)
    assert mod.aram_balance_line("X", "ARAM") == (
        "ARAM balance: you take -10% damage")
    grid = mod.balance_grid_for("X")
    assert grid == {"aramDamageTaken": 0.9}
    # The grid route serialises with json.dumps; strict JSON must hold.
    json.dumps(mod.balance_grid_map(), allow_nan=False)


@pytest.mark.parametrize("junk", ["NaN", "Infinity", "true"])
def test_junk_flat_ability_haste_dropped(tmp_path, monkeypatch, junk):
    raw = ('{"data": {"X": {"id": "X", "name": "X", "lolmath": '
           '{"aram_modifiers": {"aramAbilityHaste": ' + junk + ', '
           '"aramTenacity": 1.2}}}}}')
    _reload_into(monkeypatch, _plant(tmp_path, None, raw=raw))
    assert mod.balance_grid_for("X") == {"aramTenacity": 1.2}


def test_negative_ability_haste_kept(tmp_path, monkeypatch):
    """AH is additive flat: a negative value is a real ARAM nerf."""
    data = _champ("X", "X", aramAbilityHaste=-10)
    _reload_into(monkeypatch, _plant(tmp_path, {"data": data}))
    assert mod.balance_grid_for("X") == {"aramAbilityHaste": -10.0}


def test_every_live_value_is_finite():
    for dealt, taken in mod._BALANCE_MAP.values():
        assert math.isfinite(dealt) and dealt > 0
        assert math.isfinite(taken) and taken > 0
    json.dumps(mod.balance_grid_map(), allow_nan=False)


# --------------------------------------------------------------------------
# JUNK CALL ARGS
# --------------------------------------------------------------------------

@pytest.mark.parametrize("champ", [["Ahri"], {"a": 1}, 5, 1.5, True])
def test_non_str_champion_is_neutral(champ):
    assert mod.get_balance_mults(champ) == (1.0, 1.0)
    assert mod.balance_grid_for(champ) == {}
    assert mod.aram_balance_line(champ, "ARAM") == ""


@pytest.mark.parametrize("mode", [450, 2400, ["ARAM"], {"m": 1}, 1.0])
def test_non_str_mode_is_empty(mode):
    any_champ = next(iter(mod._BALANCE_MAP), "Ahri")
    assert mod.aram_balance_line(any_champ, mode) == ""


def test_mode_with_whitespace_still_gates(tmp_path, monkeypatch):
    _reload_into(monkeypatch, _plant(tmp_path, _display_fixture()))
    assert mod.aram_balance_line("Ahri", " aram ") == (
        "ARAM balance: you deal +10% damage")


# --------------------------------------------------------------------------
# PATCH TOKEN
# --------------------------------------------------------------------------

def test_bom_in_current_txt_still_loads(tmp_path, monkeypatch):
    data = _champ("Ahri", "Ahri", aramDamageDealt=1.1)
    _plant(tmp_path, {"data": data})
    (tmp_path / "current.txt").write_bytes(
        b"\xef\xbb\xbf" + PATCH.encode("ascii") + b"\r\n")
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    assert mod._load_balance_map() == {"Ahri": (1.1, 1.0)}


@pytest.mark.parametrize("token", ["../outside", "..", "a/b", "a\\b", "x/../y"])
def test_patch_token_with_path_segment_is_refused(tmp_path, monkeypatch, token):
    inner = tmp_path / "ds"
    inner.mkdir()
    (inner / "current.txt").write_text(token, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = {"data": _champ("Ahri", "Ahri", aramDamageDealt=1.1)}
    for d in (outside, inner / "a", inner / "x", inner / "y", tmp_path):
        d.mkdir(exist_ok=True)
        (d / "champions.json").write_text(json.dumps(payload),
                                          encoding="utf-8")
    (inner / "a" / "b").mkdir(exist_ok=True)
    (inner / "a" / "b" / "champions.json").write_text(
        json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(mod, "_DATA_DIR", inner)
    assert mod._load_balance_map() == {}
    assert mod._load_balance_grid_map() == {}


# --------------------------------------------------------------------------
# SILENT EMPTY
# --------------------------------------------------------------------------

def test_failed_load_logs_one_warning(tmp_path, monkeypatch, caplog):
    (tmp_path / "current.txt").write_text(PATCH, encoding="utf-8")
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    with caplog.at_level(logging.WARNING, logger=mod.log.name):
        balance, grid, aliases = mod._build_maps()
    assert (balance, grid, aliases) == ({}, {}, {})
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "champions.json" in warnings[0].getMessage()


def test_good_load_logs_nothing(tmp_path, monkeypatch, caplog):
    _plant(tmp_path, _display_fixture())
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    with caplog.at_level(logging.WARNING, logger=mod.log.name):
        balance, _grid, _aliases = mod._build_maps()
    assert "Ahri" in balance
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_build_maps_reads_champions_json_once(tmp_path, monkeypatch):
    _plant(tmp_path, _display_fixture())
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
    calls = []
    real = mod._read_champion_data

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(mod, "_read_champion_data", counting)
    mod._build_maps()
    assert len(calls) == 1
