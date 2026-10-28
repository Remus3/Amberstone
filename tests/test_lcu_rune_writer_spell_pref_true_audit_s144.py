"""RM-1035 (s144 true-audit) - lcu/lcu_rune_writer.py spell-preference hardening.

The per-champion spell memory (RC2 E6) stored and served pairs that can
never be applied:

* save_champ_spell_pref ran int() over whatever it was handed, so a
  half-filled live pair (0, 4), a bool (True -> 1), a negative id, a float
  (4.9 -> 4) and even the STRING "47" (read as (4, 7)) were all written.
* load_champ_spell_pref accepted any isinstance(x, int), which lets bool,
  0 and negative ids through, so a stored [0, 4] came back as a
  "remembered" pair that set_summoner_spells refuses (RM-1034) - and it
  shadowed the WR / role default for that champion forever.
* _sync_spells treated any live pair other than (0, 0) as an operator
  change, so a half-filled (0, 12) read after RC's own push latched the
  manual override for the rest of the lock AND was remembered.
* the WR adapter passed a corpus pair through unchecked.
* mode_tag / resolve_spell_pair raised AttributeError on a non-str mode,
  save_spell_pref let any key (including "by_champ") be overwritten with
  any value, and a non-str champion was written as a JSON key.

Every test points the module at a tmp spell_prefs.json; nothing reads or
writes the repo's data/.
"""
from __future__ import annotations

import json

import pytest

import lcu.lcu_rune_writer as rw
from lcu.lcu_pregame import spells_for_role

_FLASH, _TELEPORT, _IGNITE, _HEAL = 4, 12, 14, 7


@pytest.fixture
def prefs_path(tmp_path, monkeypatch):
    p = tmp_path / "data" / "spell_prefs.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(json.dumps(
        {"aram_mode": "snowball", "sr_mode": "teleport"}).encode())
    monkeypatch.setattr(rw, "_SPELL_PREFS_PATH", p)
    return p


def _write(path, by_champ):
    data = json.loads(path.read_bytes())
    data["by_champ"] = by_champ
    path.write_bytes(json.dumps(data).encode())


def _read(path):
    return json.loads(path.read_bytes())


# --- save_champ_spell_pref ---------------------------------------------------

_BAD_PAIRS = [
    pytest.param((0, _FLASH), id="half-filled-0"),
    pytest.param((_FLASH, 0), id="half-filled-second"),
    pytest.param((True, _FLASH), id="bool"),
    pytest.param((-1, _FLASH), id="negative"),
    pytest.param((4.9, 12.2), id="float-truncates"),
    pytest.param("47", id="string-reads-as-4-7"),
    pytest.param((_FLASH, _FLASH), id="duplicate"),
    pytest.param(("4", "12"), id="numeric-strings"),
    pytest.param((_FLASH, _TELEPORT, _IGNITE), id="three-items"),
]


@pytest.mark.parametrize("pair", _BAD_PAIRS)
def test_save_refuses_a_pair_that_is_not_two_distinct_positive_ints(
        prefs_path, pair):
    rw.save_champ_spell_pref("Ahri", "CLASSIC", pair)
    assert "by_champ" not in _read(prefs_path)
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") is None


def test_save_control_a_real_pair_is_stored(prefs_path):
    rw.save_champ_spell_pref("Ahri", "CLASSIC", (_FLASH, _IGNITE))
    assert _read(prefs_path)["by_champ"] == {"SR": {"Ahri": [4, 14]}}
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") == (4, 14)


@pytest.mark.parametrize("champion", [5, ["Ahri"], None, ""])
def test_save_refuses_a_non_str_or_empty_champion(prefs_path, champion):
    rw.save_champ_spell_pref(champion, "CLASSIC", (_FLASH, _IGNITE))
    assert "by_champ" not in _read(prefs_path)


# --- load_champ_spell_pref ---------------------------------------------------

@pytest.mark.parametrize("stored", [
    [True, _FLASH], [0, _FLASH], [-1, _FLASH], [_FLASH, _FLASH],
    [4.0, 12.0], ["4", "12"], [_FLASH], [_FLASH, _TELEPORT, _IGNITE],
    None, "4,12",
])
def test_load_treats_an_unusable_stored_pair_as_absent(prefs_path, stored):
    _write(prefs_path, {"SR": {"Ahri": stored}})
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") is None


def test_load_control_a_stored_real_pair_is_served(prefs_path):
    _write(prefs_path, {"SR": {"Ahri": [_FLASH, _TELEPORT]}})
    assert rw.load_champ_spell_pref("Ahri", "CLASSIC") == (4, 12)


@pytest.mark.parametrize("champion", [["Ahri"], {"a": 1}, 5])
def test_load_non_str_champion_is_absent_not_a_crash(prefs_path, champion):
    _write(prefs_path, {"SR": {"Ahri": [_FLASH, _TELEPORT]}})
    assert rw.load_champ_spell_pref(champion, "CLASSIC") is None


# --- fallback chain ----------------------------------------------------------

def _writer(wr_pair=None):
    w = rw.RuneWriter(object())
    w._wr_spell_pair = lambda champion, mode: wr_pair
    return w


def test_unusable_remembered_pair_falls_through_to_the_role_default(prefs_path):
    _write(prefs_path, {"SR": {"Caitlyn": [0, _FLASH]}})
    got = _writer()._resolve_intended_pair_for("Caitlyn", "CLASSIC", "BOTTOM")
    assert got == tuple(spells_for_role("BOTTOM"))
    assert 0 not in got


def test_unusable_remembered_pair_falls_through_to_wr(prefs_path):
    _write(prefs_path, {"SR": {"Caitlyn": [True, _FLASH]}})
    # The WR pair differs from the BOTTOM role default (4, 7) on purpose.
    w = _writer(wr_pair=(_FLASH, _IGNITE))
    assert w._resolve_intended_pair_for("Caitlyn", "CLASSIC", "BOTTOM") == (4, 14)
    assert w._resolve_intended_pair("Caitlyn", "CLASSIC") == (4, 14)


@pytest.mark.parametrize("corpus_pair", [(0, _FLASH), (-3, _FLASH),
                                         (_FLASH, _FLASH)])
def test_wr_adapter_refuses_an_unusable_corpus_pair(
        tmp_path, monkeypatch, corpus_pair):
    import dashboard.routes_adaptive_summoners as ras
    db = tmp_path / "postgame_stats.db"
    db.write_bytes(b"")
    monkeypatch.setattr(ras, "_postgame_db_path", lambda: db)
    monkeypatch.setattr(ras, "best_wr_spell_pair",
                        lambda conn, champion, mode: corpus_pair)
    w = rw.RuneWriter(object())
    assert w._wr_spell_pair("Caitlyn", "CLASSIC") is None


def test_wr_adapter_control_a_real_corpus_pair_is_served(tmp_path, monkeypatch):
    import dashboard.routes_adaptive_summoners as ras
    db = tmp_path / "postgame_stats.db"
    db.write_bytes(b"")
    monkeypatch.setattr(ras, "_postgame_db_path", lambda: db)
    monkeypatch.setattr(ras, "best_wr_spell_pair",
                        lambda conn, champion, mode: (_FLASH, _HEAL))
    w = rw.RuneWriter(object())
    assert w._wr_spell_pair("Caitlyn", "CLASSIC") == (4, 7)


# --- _sync_spells manual-change detection ------------------------------------

class _Lcu:
    def __init__(self):
        self.pushes = []

    def set_summoner_spells(self, s1, s2, *, current_pair=None):
        self.pushes.append((s1, s2))
        return True


def _session(s1, s2, position="BOTTOM"):
    return {"localPlayerCellId": 0,
            "myTeam": [{"cellId": 0, "championId": 51,
                        "assignedPosition": position,
                        "spell1Id": s1, "spell2Id": s2}]}


def _sync_writer(champion):
    lcu = _Lcu()
    w = rw.RuneWriter(lcu)
    w._wr_spell_pair = lambda c, m: None
    w._detect_my_champion = lambda session: champion
    return w, lcu


@pytest.mark.parametrize("partial", [(0, _TELEPORT), (_FLASH, 0),
                                     (True, _TELEPORT)])
def test_locked_half_filled_live_pair_is_not_an_operator_change(
        prefs_path, partial):
    w, lcu = _sync_writer("Caitlyn")
    want = tuple(spells_for_role("BOTTOM"))
    assert w._sync_spells(_session(*want), "CLASSIC") is True
    w._sync_spells(_session(*partial), "CLASSIC")
    assert w._spell_manual_override is False
    assert "by_champ" not in _read(prefs_path)
    # A real operator change after the transient is still detected + saved.
    w._sync_spells(_session(_FLASH, _IGNITE), "CLASSIC")
    assert w._spell_manual_override is True
    assert rw.load_champ_spell_pref("Caitlyn", "CLASSIC") == (4, 14)


def test_locked_real_operator_change_control(prefs_path):
    w, lcu = _sync_writer("Caitlyn")
    want = tuple(spells_for_role("BOTTOM"))
    w._sync_spells(_session(*want), "CLASSIC")
    w._sync_spells(_session(_FLASH, _IGNITE), "CLASSIC")
    assert w._spell_manual_override is True
    assert len(lcu.pushes) == 1


@pytest.mark.parametrize("partial", [(0, _TELEPORT), (_FLASH, 0)])
def test_midpick_half_filled_live_pair_is_not_an_operator_change(
        prefs_path, partial):
    w, lcu = _sync_writer("")
    want = tuple(spells_for_role("BOTTOM"))
    w._sync_spells(_session(*want), "CLASSIC")
    w._sync_spells(_session(*partial), "CLASSIC")
    assert w._midpick_manual_override is False
    w._sync_spells(_session(_FLASH, _IGNITE), "CLASSIC")
    assert w._midpick_manual_override is True


def test_infinite_live_spell_id_does_not_void_the_sync(prefs_path):
    # int(float("inf")) raised OverflowError, which the outer catch turned
    # into a silent False with no push at all on a fresh lock.
    w, lcu = _sync_writer("Caitlyn")
    assert w._sync_spells(_session(float("inf"), _TELEPORT), "CLASSIC") is True
    assert lcu.pushes == [tuple(spells_for_role("BOTTOM"))]


# --- mode handling and the generic writer -----------------------------------

@pytest.mark.parametrize("mode", [5, None, ["ARAM"]])
def test_mode_tag_and_resolve_tolerate_a_non_str_mode(mode):
    assert rw.mode_tag(mode) == "SR"
    assert rw.resolve_spell_pair("", mode) == rw.load_spell_pair("", False)


def test_mode_tag_control():
    assert rw.mode_tag("kiwi") == "ARAM"
    assert rw.mode_tag("ARAM_MAYHEM") == "ARAM"
    assert rw.mode_tag("CHERRY") == "ARENA"


@pytest.mark.parametrize("key,value", [
    ("by_champ", "ignite"), ("_note", "x"), ("sr_mode", 5),
    ("sr_mode", None), (5, "ignite"),
])
def test_save_spell_pref_refuses_unknown_keys_and_non_str_values(
        prefs_path, key, value):
    _write(prefs_path, {"SR": {"Ahri": [_FLASH, _TELEPORT]}})
    before = _read(prefs_path)
    rw.save_spell_pref(key, value)
    assert _read(prefs_path) == before


def test_save_spell_pref_control_known_key_is_written(prefs_path):
    rw.save_spell_pref("aram_mode", "exhaust")
    assert _read(prefs_path)["aram_mode"] == "exhaust"
    assert rw.load_spell_pair("ARAM", True) == (_FLASH, 3)
