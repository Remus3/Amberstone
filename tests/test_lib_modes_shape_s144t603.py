"""lib/modes.py - the Phase 3 mode list read from resolved_decisions.json
(S144-T-603, lane 8 true-audit).

PHASE3_MODES is built at IMPORT time from ``db.files`` in
agents/state/resolved_decisions.json, and every consumer turns a mode name
into a file name: coaches/_adaptation_common.py ``DB_DIR / f"{mode}.db"``,
agents/agent2_backend/pipeline/orchestrator.py
``COACH_CACHE_DIR / f"{mode}.json"`` (a WRITE), agents/agent4_coach_mentor/
analyzer.py. The supervisor calls verify_modes() at start().

Measured on the old module (Python 3.14, Windows):
- a missing / unreadable file raised a bare FileNotFoundError, a malformed
  one a JSONDecodeError, non-UTF-8 bytes a UnicodeDecodeError, a wrong-typed
  document or a missing key a TypeError / KeyError, a non-string entry an
  AttributeError - none of them named the file, and each one aborted the
  import of the supervisor, the analyzer, the pipeline and the coach
  adaptation hint;
- ``files`` given as a string was iterated per CHARACTER ("aram.db" read as
  seven one-letter modes), a dict read as its keys, an empty list gave an
  empty mode tuple so every mode loop silently did nothing;
- an entry without the ".db" suffix passed through unchanged, and an entry
  shaped as a path ("../x.db", "a/b.db", "c:x.db") became a mode name that
  the consumers join onto their directory - the pipeline writes its coach
  cache there;
- a Windows reserved device name ("con.db", "nul.db", "com1.db") became the
  mode "con", whose file name names a DEVICE on Windows 10;
- duplicates were kept, so a mode was refreshed / analysed twice.

Now every one of those is a ModesConfigError (a RuntimeError) naming the
file by NAME only and never echoing the bad value; valid input is unchanged.
"""
from __future__ import annotations

import json

import pytest

import lib.modes as modes

LIVE = ("sr_draft", "sr_ranked", "aram", "arena", "brawl")


def _write(tmp_path, payload) -> object:
    p = tmp_path / "resolved_decisions.json"
    if isinstance(payload, bytes):
        p.write_bytes(payload)
    elif isinstance(payload, str):
        p.write_bytes(payload.encode("utf-8"))
    else:
        p.write_bytes(json.dumps(payload).encode("utf-8"))
    return p


def _files(files) -> dict:
    return {"version": "phase3-1.1", "db": {"strategy": "x", "files": files}}


@pytest.fixture
def at(tmp_path, monkeypatch):
    """Point the module at a temp decisions file; return a writer."""

    def _point(payload):
        p = _write(tmp_path, payload)
        monkeypatch.setattr(modes, "_DECISIONS_PATH", p)
        return p

    return _point


def _refused(tmp_path) -> RuntimeError:
    with pytest.raises(RuntimeError) as ei:
        modes._load()
    err = ei.value
    msg = str(err)
    assert "resolved_decisions.json" in msg
    # The file is named, never located: no directory reaches the message.
    assert str(tmp_path) not in msg
    return err


# ---------------------------------------------------------------- unchanged


def test_live_tracked_file_gives_the_five_modes_in_order():
    assert modes.PHASE3_MODES == LIVE
    assert modes._load() == LIVE


def test_valid_custom_list_strips_suffix_and_keeps_order(at):
    at(_files(["brawl.db", "aram.db", "sr_ranked.db"]))
    assert modes._load() == ("brawl", "aram", "sr_ranked")


def test_names_with_digits_and_underscores_are_accepted(at):
    at(_files(["a.db", "mode_2.db", "x" * 32 + ".db"]))
    assert modes._load() == ("a", "mode_2", "x" * 32)


def test_verify_modes_passes_when_file_matches():
    modes.verify_modes()


def test_verify_modes_raises_on_drift_naming_both_lists(at):
    at(_files(["aram.db"]))
    with pytest.raises(RuntimeError) as ei:
        modes.verify_modes()
    msg = str(ei.value)
    assert "drift" in msg
    assert "'aram'" in msg and "'sr_draft'" in msg


def test_verify_modes_order_change_is_drift(at):
    at(_files([f"{m}.db" for m in reversed(LIVE)]))
    with pytest.raises(RuntimeError, match="drift"):
        modes.verify_modes()


def test_error_type_is_a_runtime_error():
    assert issubclass(modes.ModesConfigError, RuntimeError)


# ---------------------------------------------------- file / document shape


def test_missing_file_is_a_named_config_error(tmp_path, monkeypatch):
    monkeypatch.setattr(modes, "_DECISIONS_PATH", tmp_path / "resolved_decisions.json")
    err = _refused(tmp_path)
    assert isinstance(err, modes.ModesConfigError)
    assert isinstance(err.__cause__, OSError)


def test_directory_in_place_of_file_is_a_named_config_error(tmp_path, monkeypatch):
    d = tmp_path / "resolved_decisions.json"
    d.mkdir()
    monkeypatch.setattr(modes, "_DECISIONS_PATH", d)
    _refused(tmp_path)


def test_malformed_json_is_a_named_config_error(at, tmp_path):
    at("{not json")
    err = _refused(tmp_path)
    assert isinstance(err.__cause__, ValueError)


def test_non_utf8_bytes_are_a_named_config_error(at, tmp_path):
    at(b'{"db": {"files": ["ar\xffam.db"]}}')
    _refused(tmp_path)


def test_bom_prefixed_file_is_refused_like_the_supervisor_gate(at, tmp_path):
    # agents/_supervisor_common._verify_decisions_version reads the same file
    # with encoding="utf-8" and refuses a BOM as malformed JSON; this module
    # stays consistent with it rather than half-accepting the file.
    at(b"\xef\xbb\xbf" + json.dumps(_files(["aram.db"])).encode("utf-8"))
    _refused(tmp_path)


def test_deeply_nested_json_is_a_named_config_error(at, tmp_path):
    at("[" * 200000)
    _refused(tmp_path)


@pytest.mark.parametrize(
    "doc",
    [
        [],
        None,
        "x",
        3,
        {},
        {"db": None},
        {"db": []},
        {"db": "files"},
        {"db": {}},
        {"db": {"files": None}},
        {"db": {"files": 7}},
    ],
    ids=[
        "top-list", "top-null", "top-str", "top-int", "no-db", "db-null",
        "db-list", "db-str", "no-files", "files-null", "files-int",
    ],
)
def test_wrong_document_shape_is_a_named_config_error(at, tmp_path, doc):
    at(doc)
    _refused(tmp_path)


def test_files_as_a_string_is_not_iterated_per_character(at, tmp_path):
    at(_files("aram.db"))
    _refused(tmp_path)


def test_files_as_a_dict_is_not_read_as_its_keys(at, tmp_path):
    at(_files({"aram.db": 1}))
    _refused(tmp_path)


def test_empty_files_list_is_refused(at, tmp_path):
    at(_files([]))
    _refused(tmp_path)


# ---------------------------------------------------------- entry shape


@pytest.mark.parametrize(
    "entry",
    [None, 1, 1.5, True, ["aram.db"], {"a": 1}],
    ids=["none", "int", "float", "bool", "list", "dict"],
)
def test_non_string_entry_is_refused(at, tmp_path, entry):
    at(_files(["aram.db", entry]))
    _refused(tmp_path)


BAD_NAMES = [
    "aram",
    "aram.sqlite",
    "aram.DB",
    "ARAM.db",
    ".db",
    "",
    "../x.db",
    "..\\x.db",
    "a/b.db",
    "a\\b.db",
    "c:x.db",
    "/x.db",
    "\\\\srv\\share\\x.db",
    " aram.db",
    "aram.db ",
    "aram .db",
    "aram.db\n",
    "ar\nam.db",
    "ar\x00am.db",
    "aram.db.db",
    "1aram.db",
    "_aram.db",
    "ar-am.db",
    "\uff41ram.db",
    "\u0430ram.db",
    "x" * 33 + ".db",
    "con.db",
    "CON.db",
    "prn.db",
    "aux.db",
    "nul.db",
    "com1.db",
    "com9.db",
    "com0.db",
    "lpt1.db",
    "lpt9.db",
    "lpt0.db",
]


@pytest.mark.parametrize("name", BAD_NAMES, ids=[repr(n) for n in BAD_NAMES])
def test_bad_entry_name_is_refused(at, tmp_path, name):
    # The good entry shares no stem with any bad name, so the duplicate check
    # cannot mask a name check (a prefix-only match of "aram.db.db" would
    # otherwise read as a repeat of "aram.db" and be refused for that).
    at(_files(["sr_draft.db", name]))
    _refused(tmp_path)


@pytest.mark.parametrize("name", BAD_NAMES, ids=[repr(n) for n in BAD_NAMES])
def test_bad_entry_name_alone_is_refused(at, tmp_path, name):
    at(_files([name]))
    _refused(tmp_path)


def test_names_merely_containing_a_device_word_are_accepted(at):
    at(_files(["console.db", "nul_x.db", "com10.db", "lpt.db", "auxiliary.db"]))
    assert modes._load() == ("console", "nul_x", "com10", "lpt", "auxiliary")


def test_duplicate_entry_is_refused(at, tmp_path):
    at(_files(["aram.db", "arena.db", "aram.db"]))
    _refused(tmp_path)


def test_refusal_never_echoes_the_bad_value(at, tmp_path):
    bad = "<script>alert(1)</script>" + "Z" * 5000 + ".db"
    at(_files([bad]))
    msg = str(_refused(tmp_path))
    assert "<script>" not in msg
    assert "ZZZZ" not in msg
    assert len(msg) < 300


def test_refusal_names_the_entry_index(at, tmp_path):
    at(_files(["aram.db", "arena.db", "../x.db"]))
    assert "db.files[2]" in str(_refused(tmp_path))


def test_duplicate_refusal_names_the_entry_index(at, tmp_path):
    at(_files(["aram.db", "arena.db", "aram.db"]))
    assert "db.files[2]" in str(_refused(tmp_path))


# ------------------------------------------------------------ verify_modes


def test_verify_modes_surfaces_a_broken_file_as_config_error(at):
    at(_files(["../x.db"]))
    with pytest.raises(modes.ModesConfigError):
        modes.verify_modes()


def test_verify_modes_surfaces_a_missing_file_as_config_error(tmp_path, monkeypatch):
    monkeypatch.setattr(modes, "_DECISIONS_PATH", tmp_path / "gone.json")
    with pytest.raises(modes.ModesConfigError):
        modes.verify_modes()


def test_an_unexpected_programming_error_is_not_masked(at, monkeypatch):
    # Only the expected read / decode / shape failures become a config
    # error; anything else (here a broken json module) still surfaces as is.
    at(_files(["aram.db"]))

    def _boom(_text):
        raise ZeroDivisionError("boom")

    monkeypatch.setattr(modes.json, "loads", _boom)
    with pytest.raises(ZeroDivisionError):
        modes._load()
