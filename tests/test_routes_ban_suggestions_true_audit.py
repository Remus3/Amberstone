"""True-audit (s144 cycle 111, RM-1446) of dashboard/routes_ban_suggestions.py.

GET /api/champ-select/ban-suggestions reads two operator / pipeline files
(data/meta/global_top_bans.json and data/meta/ddragon_champions.json) and a
query string it did not author. Each test below pins one finding of the
audit and was RED against the pre-audit module:

  F1 the card icon URL was derived from the display name, so Wukong,
     Nunu & Willump and Renata Glasc pointed at PNGs that do not exist, and
     Kha'Zix / Cho'Gath / Vel'Koz / Bel'Veth / LeBlanc / Kai'Sa only worked
     through NTFS case-insensitivity. The DDragon slug is the icon name.
  F2 a failed DDragon load cached an EMPTY index for the life of the
     process, so one transient read error blanked every suggestion until a
     restart while the route kept answering ok:true.
  F3 a malformed bans document (a list, a null entry, a dict top_bans, a
     non-string patch) turned the whole panel into a 500 or echoed a
     non-string patch.
  F4 a champion listed twice (spelling variants) produced two cards with
     one champId.
  F5 the bans loader swallowed EVERY exception as "file empty"; an
     unexpected error now surfaces (the route's generic 500), while I/O and
     JSON errors still degrade to an empty list.
  F6 exclude ids accepted Python-literal forms ("1_000", "+5", "-3", "0")
     and counted them in excluded_count; only positive decimal ids count.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from dashboard import routes_ban_suggestions as rbsu

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "data" / "icons" / "champions"


class _StubHandler:
    def __init__(self, path: str):
        self.path = path
        self.responses: list[tuple[int, bytes, str]] = []

    def _send(self, code, body, ctype="application/json"):
        self.responses.append((code, body, ctype))

    @property
    def code(self) -> int:
        return self.responses[-1][0]

    @property
    def doc(self) -> dict:
        return json.loads(self.responses[-1][1].decode("utf-8"))


_DDRAGON = {
    "data": {
        "MonkeyKing": {"id": "MonkeyKing", "key": "62", "name": "Wukong"},
        "Nunu": {"id": "Nunu", "key": "20", "name": "Nunu & Willump"},
        "Renata": {"id": "Renata", "key": "888", "name": "Renata Glasc"},
        "Khazix": {"id": "Khazix", "key": "121", "name": "Kha'Zix"},
        "Kaisa": {"id": "Kaisa", "key": "145", "name": "Kai'Sa"},
        "Zed": {"id": "Zed", "key": "238", "name": "Zed"},
    }
}


def _reset_index(monkeypatch):
    monkeypatch.setattr(rbsu, "_CHAMP_INDEX", None)


@pytest.fixture
def champs_file(tmp_path, monkeypatch):
    p = tmp_path / "ddragon_champions.json"
    p.write_bytes(json.dumps(_DDRAGON).encode("utf-8"))
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", p)
    _reset_index(monkeypatch)
    return p


def _serve(path: str, bans_doc) -> _StubHandler:
    h = _StubHandler(path)
    with mock.patch.object(rbsu, "_load_bans_file", return_value=bans_doc):
        rbsu._serve_ban_suggestions(h)
    return h


# --- F1 -----------------------------------------------------------------

def test_icon_uses_ddragon_slug_not_display_name(champs_file):
    doc = {"patch": "1.1", "top_bans": [
        "Wukong", "Nunu & Willump", "Renata Glasc", "Kha'Zix"]}
    h = _serve("/api/champ-select/ban-suggestions?top=4", doc)
    assert h.code == 200
    icons = [s["icon"] for s in h.doc["suggestions"]]
    assert icons == [
        "/icons/champions/MonkeyKing.png",
        "/icons/champions/Nunu.png",
        "/icons/champions/Renata.png",
        "/icons/champions/Khazix.png",
    ]


def test_every_shipped_top_ban_icon_exists_case_exact(monkeypatch):
    # Real data files: every name in the shipped bans list must resolve and
    # its icon must name a PNG that exists with EXACT case (the NTFS
    # case-insensitive open hid the Kha'Zix -> KhaZix.png miss).
    _reset_index(monkeypatch)
    on_disk = set(os.listdir(ICON_DIR))
    bans = json.loads(rbsu._BANS_PATH.read_text(encoding="utf-8"))
    h = _serve("/api/champ-select/ban-suggestions?top=10",
               {"patch": "x", "top_bans": bans["top_bans"]})
    assert h.code == 200
    sugg = h.doc["suggestions"]
    assert len(sugg) == 10
    for s in sugg:
        fname = s["icon"].rsplit("/", 1)[1]
        assert fname in on_disk, (s["name"], fname)


# --- F2 -----------------------------------------------------------------

def test_failed_ddragon_load_is_not_cached(tmp_path, monkeypatch, champs_file):
    missing = tmp_path / "absent.json"
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", missing)
    assert rbsu._load_name_to_id() == {}
    # The file appears (pipeline finished, transient lock released): the
    # very next call must see it instead of the cached empty index.
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", champs_file)
    assert rbsu._load_name_to_id().get("Zed") == 238


def test_corrupt_ddragon_degrades_and_is_not_cached(tmp_path, monkeypatch,
                                                     champs_file):
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{not json")
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", bad)
    assert rbsu._load_name_to_id() == {}
    listy = tmp_path / "list.json"
    listy.write_bytes(b"[1, 2]")
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", listy)
    assert rbsu._load_name_to_id() == {}
    # A well-formed but EMPTY champion map (a half-written pipeline output)
    # is a failed load too: not cached.
    empty = tmp_path / "empty.json"
    empty.write_bytes(b'{"data": {}}')
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", empty)
    assert rbsu._load_name_to_id() == {}
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", champs_file)
    assert rbsu._load_name_to_id().get("Kai'Sa") == 145


def test_ddragon_entry_with_non_string_name_is_skipped(tmp_path, monkeypatch):
    p = tmp_path / "c.json"
    p.write_bytes(json.dumps({"data": {
        "Bad": {"id": "Bad", "key": "1", "name": 5},
        "Zed": {"id": "Zed", "key": "238", "name": "Zed"},
    }}).encode("utf-8"))
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", p)
    _reset_index(monkeypatch)
    # One malformed row must not abort the whole index (it used to raise
    # AttributeError inside the loop and cache whatever came before it).
    assert rbsu._load_name_to_id().get("Zed") == 238


@pytest.mark.parametrize("bad_key", [b"Infinity", b"-Infinity", b"1e400",
                                     b"NaN", b"true", b"0", b"-5", b"12.9",
                                     b'"1_000"', b'"+7"', b'"-7"', b"null",
                                     b'"' + b"9" * 5000 + b'"'])
def test_ddragon_row_with_unusable_key_is_skipped(tmp_path, monkeypatch,
                                                   bad_key):
    # float('inf') from JSON Infinity / 1e400 makes int() raise
    # OverflowError (verifier-found: the first rewrite answered 500).
    p = tmp_path / "c.json"
    p.write_bytes(b'{"data": {"Bad": {"id": "Bad", "key": ' + bad_key
                  + b', "name": "Bad"}, "Zed": {"id": "Zed", "key": "238",'
                  b' "name": "Zed"}}}')
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", p)
    _reset_index(monkeypatch)
    idx = rbsu._load_name_to_id()
    assert idx.get("Zed") == 238
    assert "Bad" not in idx
    h = _serve("/api/champ-select/ban-suggestions",
               {"patch": "1.1", "top_bans": ["Bad", "Zed"]})
    assert h.code == 200
    assert [s["champId"] for s in h.doc["suggestions"]] == [238]


def test_deeply_nested_ddragon_degrades_not_500(tmp_path, monkeypatch,
                                                champs_file):
    # json.loads raises RecursionError (not ValueError) past its stack depth
    # (verifier-found: the narrowed loader let it reach the 500).
    deep = tmp_path / "deep.json"
    deep.write_bytes(b"[" * 100000 + b"]" * 100000)
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", deep)
    assert rbsu._load_name_to_id() == {}
    h = _StubHandler("/api/champ-select/ban-suggestions")
    with mock.patch.object(rbsu, "_load_bans_file",
                           return_value={"patch": "1", "top_bans": ["Zed"]}):
        rbsu._serve_ban_suggestions(h)
    assert h.code == 200
    monkeypatch.setattr(rbsu, "_CHAMPS_PATH", champs_file)
    assert rbsu._load_name_to_id().get("Zed") == 238


# --- F3 -----------------------------------------------------------------

@pytest.mark.parametrize("doc", [
    ["Zed"],
    {"patch": "1.1", "top_bans": {"Zed": 1}},
    {"patch": "1.1", "top_bans": "Zed"},
    {"patch": "1.1"},
    None,
])
def test_malformed_bans_doc_degrades_to_empty_not_500(champs_file, doc):
    h = _serve("/api/champ-select/ban-suggestions", doc)
    assert h.code == 200
    assert h.doc["ok"] is True
    assert h.doc["suggestions"] == []
    assert isinstance(h.doc["patch"], str)


def test_non_string_entries_are_skipped_not_500(champs_file):
    doc = {"patch": "1.1", "top_bans": [None, 7, {"n": 1}, ["x"], "Zed"]}
    h = _serve("/api/champ-select/ban-suggestions", doc)
    assert h.code == 200
    sugg = h.doc["suggestions"]
    assert [s["champId"] for s in sugg] == [238]
    assert sugg[0]["rank"] == 5  # true source position survives the skips


@pytest.mark.parametrize("patch", [{"a": 1}, 16.1, None, ["16.1"]])
def test_non_string_patch_reported_as_unknown(champs_file, patch):
    h = _serve("/api/champ-select/ban-suggestions",
               {"patch": patch, "top_bans": ["Zed"]})
    assert h.code == 200
    assert h.doc["patch"] == "unknown"


# --- F4 -----------------------------------------------------------------

def test_duplicate_champion_listed_once(champs_file):
    doc = {"patch": "1.1", "top_bans": ["Kai'Sa", "KaiSa", "Zed"]}
    h = _serve("/api/champ-select/ban-suggestions?top=4", doc)
    sugg = h.doc["suggestions"]
    assert [s["champId"] for s in sugg] == [145, 238]
    assert [s["rank"] for s in sugg] == [1, 3]


# --- F5 -----------------------------------------------------------------

def test_bans_loader_degrades_on_io_and_json_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(rbsu, "_BANS_PATH", tmp_path / "absent.json")
    assert rbsu._load_bans_file() == {"top_bans": [], "patch": "unknown"}
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"\xff\xfe{")
    monkeypatch.setattr(rbsu, "_BANS_PATH", bad)
    assert rbsu._load_bans_file() == {"top_bans": [], "patch": "unknown"}
    bad.write_bytes(b"{nope")
    assert rbsu._load_bans_file() == {"top_bans": [], "patch": "unknown"}
    bad.write_bytes(b'{"top_bans": ' + b"[" * 100000 + b"]" * 100000 + b"}")
    assert rbsu._load_bans_file() == {"top_bans": [], "patch": "unknown"}


def test_bans_loader_unexpected_error_surfaces_as_generic_500(tmp_path,
                                                              monkeypatch):
    good = tmp_path / "b.json"
    good.write_bytes(b'{"top_bans": []}')
    monkeypatch.setattr(rbsu, "_BANS_PATH", good)
    secret = "SECRET-raw-text-should-not-leak"  # rc-credential-scan: allow-fixture
    with mock.patch.object(rbsu.json, "loads",
                           side_effect=RuntimeError(secret)):
        with pytest.raises(RuntimeError):
            rbsu._load_bans_file()
        h = _StubHandler("/api/champ-select/ban-suggestions")
        rbsu._serve_ban_suggestions(h)
    assert h.code == 500
    assert secret.encode() not in h.responses[-1][1]
    assert h.doc["ok"] is False


# --- F6 -----------------------------------------------------------------

def test_exclude_accepts_only_positive_decimal_ids():
    assert rbsu._parse_int_csv("238, 145 ,abc,-3,0,+5,1_000,,7.0") == {238, 145}


def test_oversized_digit_token_is_ignored_not_500(champs_file):
    # 5000 digits passes isdigit() but trips int()'s 4300-digit limit;
    # verifier-found regression of the first rewrite (it returned 500).
    h = _serve("/api/champ-select/ban-suggestions?exclude=238," + "9" * 5000,
               {"patch": "1.1", "top_bans": ["Zed", "Kai'Sa"]})
    assert h.code == 200
    assert h.doc["excluded_count"] == 1
    assert [s["champId"] for s in h.doc["suggestions"]] == [145]


def test_excluded_count_ignores_malformed_tokens(champs_file):
    h = _serve("/api/champ-select/ban-suggestions?exclude=238,-3,1_000,0",
               {"patch": "1.1", "top_bans": ["Zed", "Kai'Sa"]})
    assert h.doc["excluded_count"] == 1
    assert [s["champId"] for s in h.doc["suggestions"]] == [145]
