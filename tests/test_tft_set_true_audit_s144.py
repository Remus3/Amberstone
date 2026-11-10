"""s144 true-audit of tft/tft_set.py (the live TFT set resolver).

Six findings, each reproduced on the pre-fix module before the fix:

1. parse_set_id raised ValueError on a non-ASCII digit string ("\\u00b2"
   passes str.isdigit but int() rejects it) and on a digit string past
   Python's int-string limit; it also read Arabic-Indic digits as a set id.
   Reachable from a dashboard query (?set=), the RC_TFT_SET env pin (which
   made EVERY resolve_set raise) and the LCU queue id (set_from_lcu,
   lcu_tft_queue_id). tft/engine/comps.py _set_id wrapped it in a try for
   exactly this reason.
2. ingested_sets read "tft_set0_*" as set 0 and "tft_set018_*" as set 18,
   neither of which the path builders can round-trip, so the newest
   "ingested" set could be one whose files do not exist.
3. meta_path / cdragon_path interpolated an unvalidated set_number into the
   file name ("../../x" walked out of data/meta, True became "tft_setTrue").
4. pbe_flag read any truthy value as PBE on, so {"pbe": "false"} routed the
   coach to the PBE twin.
5. noted_live_set read the set and its timestamp in two steps, so a note
   landing between them returned the OLD, expired set as live.
6. load_json_file let RecursionError (deeply nested JSON) escape although its
   contract is {} for an unreadable file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tft import tft_set


@pytest.fixture(autouse=True)
def _isolated_resolver(monkeypatch):
    monkeypatch.delenv(tft_set.ENV_PIN, raising=False)
    tft_set.clear_live_set()
    yield
    tft_set.clear_live_set()


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(obj).encode("ascii") + b"\n")


def _meta(root: Path) -> Path:
    return root / "data" / "meta"


# -- 1. junk set ids never raise ---------------------------------------------

@pytest.mark.parametrize("raw", [
    "\u00b2",                    # superscript two: isdigit() True, int() fails
    "1" * 5000,                  # past the int-string digit limit
    "\u0661\u0668",              # Arabic-Indic 18: not a set id spelling
    "Set\u0661\u0668",
    "TFTSet\u00b2",
    "TFTSet" + "1" * 5000,
])
def test_parse_set_id_never_raises_on_junk(raw):
    assert tft_set.parse_set_id(raw) is None


def test_parse_set_id_keeps_every_ascii_spelling():
    for raw, want in ((" 18 ", 18), ("TFTSet18", 18), ("set_17_x", 17),
                      (999, 999), ("999", 999), (1000, None), ("1000", None)):
        assert tft_set.parse_set_id(raw) == want, raw


@pytest.mark.parametrize("qid", ["\u00b2", "\u0666\u0661\u0661\u0660", "9" * 5000])
def test_lcu_queue_id_junk_never_raises(qid):
    assert tft_set.set_from_lcu("TFTSet18", qid) == 18
    session = {"gameData": {"queue": {"gameMode": "TFT", "id": qid}}}
    assert tft_set.lcu_tft_queue_id(session) is None


def test_ascii_string_queue_id_still_names_the_revival_set():
    assert tft_set.set_from_lcu("TFTSet18", " 6110 ") == 17
    session = {"gameData": {"queue": {"gameMode": "TFT", "id": "6110"}}}
    assert tft_set.lcu_tft_queue_id(session) == 6110


def test_a_junk_env_pin_never_breaks_resolve_set(tmp_path, monkeypatch):
    _write(_meta(tmp_path) / "tft_set18_meta.json", {})
    monkeypatch.setenv(tft_set.ENV_PIN, "\u00b2")
    assert tft_set.resolve_set(root=tmp_path) == 18
    assert tft_set.resolve_set("1" * 5000, root=tmp_path) == 18


# -- 2. only round-trippable set files count as ingested ----------------------

def test_unroundtrippable_set_file_names_are_not_ingested(tmp_path):
    meta = _meta(tmp_path)
    _write(meta / "tft_set17_meta.json", {"champions_set17": ["Jinx"]})
    _write(meta / "tft_set018_cdragon.json", {"champions": ["Ghost"]})
    _write(meta / "tft_set0_meta.json", {})
    _write(meta / "tft_set\u0661\u0669_meta.json", {})
    assert tft_set.ingested_sets(tmp_path) == [17]
    assert tft_set.resolve_set(root=tmp_path) == 17
    assert tft_set.roster(root=tmp_path) == ["Jinx"]


def test_every_ingested_set_round_trips_to_an_existing_file(tmp_path):
    meta = _meta(tmp_path)
    for name in ("tft_set17_meta.json", "tft_set18_cdragon.json",
                 "tft_set07_meta.json", "tft_set100_meta.json"):
        _write(meta / name, {})
    for n in tft_set.ingested_sets(tmp_path):
        assert (tft_set.meta_path(n, root=tmp_path).exists()
                or tft_set.cdragon_path(n, root=tmp_path).exists()), n


# -- 3. the path builders stay inside data/meta --------------------------------

@pytest.mark.parametrize("junk", [
    "../../x", "..\\..\\x", True, 18.0, "18/../17", -1, 0, 1000, [18], "",
])
def test_path_builders_never_leave_the_meta_dir_or_use_a_junk_name(tmp_path, junk):
    meta = _meta(tmp_path)
    _write(meta / "tft_set18_meta.json", {"_set": 18, "all_traits": ["Fae"]})
    _write(meta / "tft_set18_pbe_meta.json", {"_set": 18})
    _write(meta / "tft_set18_cdragon.json", {"champions": ["Kobuko"]})
    root_meta = meta.resolve()
    for p in (tft_set.meta_path(junk, root=tmp_path),
              tft_set.meta_path(junk, pbe=True, root=tmp_path),
              tft_set.cdragon_path(junk, root=tmp_path)):
        assert p.resolve().parent == root_meta, p
        assert not p.exists(), p.name
        assert tft_set.parse_set_id(p.name) is None
    # An explicit bad set never borrows the resolved (Set 18) data.
    assert tft_set.load_meta(junk, root=tmp_path) == {}
    assert tft_set.load_meta(junk, pbe=True, root=tmp_path) == {}
    assert tft_set.load_cdragon(junk, root=tmp_path) == {}
    assert tft_set.roster(junk, root=tmp_path) == []
    assert tft_set.trait_names(junk, root=tmp_path) == []
    assert tft_set.ingested_sets(tmp_path) == [18]


def test_none_still_means_the_resolved_set(tmp_path):
    _write(_meta(tmp_path) / "tft_set18_cdragon.json", {"champions": ["Kobuko"]})
    assert tft_set.cdragon_path(root=tmp_path).name == "tft_set18_cdragon.json"
    assert tft_set.roster(root=tmp_path) == ["Kobuko"]


def test_path_builders_accept_a_digit_string_set(tmp_path):
    assert tft_set.meta_path("17", root=tmp_path).name == "tft_set17_meta.json"
    assert tft_set.cdragon_path("TFTSet17", root=tmp_path).name == "tft_set17_cdragon.json"


def test_an_explicit_valid_set_still_never_borrows_another_sets_file(tmp_path):
    _write(_meta(tmp_path) / "tft_set18_meta.json", {"_set": 18})
    p = tft_set.meta_path(19, root=tmp_path)
    assert p.name == "tft_set19_meta.json"
    assert tft_set.load_meta(19, root=tmp_path) == {}


# -- 4. pbe_flag reads only a real "on" ----------------------------------------

@pytest.mark.parametrize("value,want", [
    (True, True), ("true", True), ("TRUE", True), (1, True), ("1", True),
    (False, False), ("false", False), ("0", False), (0, False), ("no", False),
    (None, False), ([], False), ({"x": 1}, False), ("garbage", False), (2, False),
])
def test_pbe_flag_is_strict(tmp_path, value, want):
    _write(tmp_path / "data" / "comp_state.json", {"pbe": value})
    assert tft_set.pbe_flag(tmp_path) is want


def test_pbe_enabled_takes_a_held_state_and_never_raises():
    assert tft_set.pbe_enabled({"pbe": "true"}) is True
    assert tft_set.pbe_enabled({"pbe": "false"}) is False
    assert tft_set.pbe_enabled({}) is False
    assert tft_set.pbe_enabled(None) is False
    assert tft_set.pbe_enabled(["pbe"]) is False


def test_coach_engine_selected_comp_block_uses_the_strict_pbe_read(monkeypatch, tmp_path):
    """tft/tft_coach_engine.py _build_prompt SELECTED COMP block held its own
    bool(comp_state["pbe"]), so a stringly "false" still asked for the twin."""
    from tft import tft_coach_engine as eng

    seen = []
    real = tft_set.meta_path

    def spy(set_number=None, *, pbe=False, root=None):
        seen.append(pbe)
        return real(set_number, pbe=pbe, root=tmp_path)

    monkeypatch.setattr(tft_set, "comp_state",
                        lambda root=None: {"selected": "X", "pbe": "false"})
    monkeypatch.setattr(tft_set, "meta_path", spy)
    eng._build_prompt({"level": 4})
    assert seen, "the SELECTED COMP block no longer reads the meta path"
    assert all(flag is False for flag in seen), seen


def test_pbe_flag_absent_or_non_object_state_is_off(tmp_path):
    assert tft_set.pbe_flag(tmp_path) is False
    _write(tmp_path / "data" / "comp_state.json", ["pbe"])
    assert tft_set.pbe_flag(tmp_path) is False


# -- 5. the noted live set is read as one consistent pair ----------------------

def test_a_note_landing_mid_read_is_not_answered_with_the_expired_set(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(tft_set, "_monotonic", lambda: clock[0])
    tft_set.note_live_set(17)
    clock[0] = tft_set.LIVE_TTL_S + 100.0   # the Set 17 note has expired

    real = tft_set._monotonic
    fired = []

    def clock_with_a_concurrent_note():
        # Another thread notes Set 18 while the reader is between reading
        # the set and reading its timestamp.
        if not fired:
            fired.append(1)
            tft_set.note_live_set(18)
        return real()

    monkeypatch.setattr(tft_set, "_monotonic", clock_with_a_concurrent_note)
    got = tft_set.noted_live_set()
    assert fired
    assert got in (None, 18)
    assert got != 17
    monkeypatch.setattr(tft_set, "_monotonic", real)
    assert tft_set.noted_live_set() == 18


def test_the_live_pair_is_only_touched_under_the_lock(monkeypatch):
    """Every read and write of the (set, at) pair holds _live_lock, so a
    writer thread and a reader thread can never interleave inside it."""
    lock = tft_set._live_lock
    touched = []

    class Guarded(dict):
        def __getitem__(self, key):
            touched.append(key)
            assert lock.locked(), f"read of {key} outside _live_lock"
            return dict.__getitem__(self, key)

        def __setitem__(self, key, value):
            touched.append(key)
            assert lock.locked(), f"write of {key} outside _live_lock"
            dict.__setitem__(self, key, value)

    clock = [0.0]
    monkeypatch.setattr(tft_set, "_monotonic", lambda: clock[0])
    monkeypatch.setattr(tft_set, "_live", Guarded({"set": None, "at": 0.0}))
    tft_set.note_live_set(17)
    assert tft_set.noted_live_set() == 17
    clock[0] = tft_set.LIVE_TTL_S + 1
    assert tft_set.noted_live_set() is None
    tft_set.note_live_set(18)
    tft_set.clear_live_set()
    assert tft_set.noted_live_set() is None
    assert {"set", "at"} <= set(touched)


def test_expiry_still_clears_and_a_fresh_note_still_reads(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(tft_set, "_monotonic", lambda: clock[0])
    assert tft_set.note_live_set("TFTSet17") == 17
    clock[0] = tft_set.LIVE_TTL_S - 1
    assert tft_set.noted_live_set() == 17
    clock[0] = tft_set.LIVE_TTL_S + 1
    assert tft_set.noted_live_set() is None
    assert tft_set.noted_live_set() is None
    assert tft_set.note_live_set(18) == 18
    assert tft_set.noted_live_set() == 18


# -- 6. an unreadable file is {} whatever the parser raises --------------------

def test_deeply_nested_json_is_unreadable_not_a_crash(tmp_path):
    p = _meta(tmp_path) / "tft_set18_cdragon.json"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"[" * 200000 + b"]" * 200000)
    assert tft_set.load_json_file(p) == {}
    assert tft_set.load_cdragon(18, root=tmp_path) == {}
    assert tft_set.roster(18, root=tmp_path) == []


def test_bom_and_non_object_json_contracts_kept(tmp_path):
    p = tmp_path / "x.json"
    p.write_bytes(b"\xef\xbb\xbf" + b'{"a": 1}')
    assert tft_set.load_json_file(p) == {"a": 1}
    p.write_bytes(b"[1, 2]")
    assert tft_set.load_json_file(p) == {}
    p.write_bytes(b"\xff\xfe junk")
    assert tft_set.load_json_file(p) == {}
    assert tft_set.load_json_file(tmp_path / "absent.json") == {}
