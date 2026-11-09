"""S144-T-707: tools/live_flip_watcher.py hardening (lane 8 true-audit).

The watcher polls the dashboard's /api/state and the baked eyeball reports
under ops/audit/ds_perm_swarm/report/. Every test here is offline: urlopen,
the champion-id resolver, the report roots and operator_notify are stubbed.

Findings pinned (each was red before the fix):
1. A non-object /api/state body (a list, a string) or a wrong-shaped field
   inside it (mode_key not a str, liveclient / coach not an object,
   allPlayers not a list, a player not an object) raised AttributeError /
   TypeError out of _resolve_game and killed the poll loop.
2. When the coach's champion was not among allPlayers, my_team stayed None and
   EVERY player (allies and the operator) was listed as an enemy, so the
   preset was picked from the wrong comp.
3. A malformed baked report (not a list, a row without "champion", a non-dict
   row) raised at start-up; a malformed credit table raised mid-game.
4. A string "entered" was iterated per CHARACTER and a non-dict seam detail
   raised.
5. A champion absent from the base (tank) report but present in the comp
   preset report was announced as "no tabled seams - any build is baseline".
6. A non-tank comp with no baked preset row kept the base TANK DSP8 verdict
   and printed it under the squishy / bruiser label.
7. A champion in no baked report was announced as "byte-identical baseline",
   a claim nothing computed.
8. The verdict .md was written in place (the atomic-write hard rule) and any
   OSError from either verdict file killed the watcher.
9. _fetch_state swallowed EVERY exception (a programming error read as "the
   dashboard is down") and read an unbounded body.
"""
from __future__ import annotations

import json

import pytest

from tools import live_flip_watcher as w


# --- shared stubs -----------------------------------------------------------

@pytest.fixture
def ids(monkeypatch):
    """Canonical-id resolver stub: drop spaces, nothing else."""
    from core import archetype_picks

    def _canon(name):
        return name.replace(" ", "") if isinstance(name, str) else ""

    monkeypatch.setattr(archetype_picks, "canonical_champion_id", _canon)
    return _canon


@pytest.fixture
def notes(monkeypatch):
    from core import operator_notify
    sent: list[tuple[str, str]] = []

    def _notify(title, body, **_k):
        sent.append((title, body))
        return True, "stub"

    monkeypatch.setattr(operator_notify, "notify", _notify)
    return sent


@pytest.fixture
def verdict_paths(tmp_path, monkeypatch):
    md = tmp_path / "live_verdict.md"
    jl = tmp_path / "live_verdict.jsonl"
    monkeypatch.setattr(w, "_VERDICT_MD", md)
    monkeypatch.setattr(w, "_VERDICT_JSONL", jl)
    return md, jl


class _Resp:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, n: int = -1) -> bytes:
        return self._body if n is None or n < 0 else self._body[:n]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _seam(moves=True, entered=None):
    return {"moves": moves, "entered": list(entered or [])}


def _state(champ="Ahri", mode="sr", players=None):
    if players is None:
        players = [
            {"championName": "Ahri", "team": "ORDER"},
            {"championName": "Lux", "team": "ORDER"},
            {"championName": "Zed", "team": "CHAOS"},
            {"championName": "Tahm Kench", "team": "CHAOS"},
        ]
    return {"mode_key": mode, "coach": {"champion": champ},
            "liveclient": {"allPlayers": players}}


# --- 9. _fetch_state --------------------------------------------------------

def test_fetch_state_returns_an_object_body(monkeypatch):
    monkeypatch.setattr(w.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(b'{"mode_key": "sr"}'))
    assert w._fetch_state() == {"mode_key": "sr"}


@pytest.mark.parametrize("body", [b"[1, 2]", b'"sr"', b"7", b"null"])
def test_fetch_state_non_object_body_reads_idle(monkeypatch, body):
    monkeypatch.setattr(w.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    assert w._fetch_state() is None


@pytest.mark.parametrize("body", [b"{not json", b"\xff\xfe{}"])
def test_fetch_state_garbage_body_reads_idle(monkeypatch, body):
    monkeypatch.setattr(w.urllib.request, "urlopen", lambda *a, **k: _Resp(body))
    assert w._fetch_state() is None


def test_fetch_state_oversize_body_reads_idle(monkeypatch):
    monkeypatch.setattr(w, "_MAX_STATE_BYTES", 16, raising=False)
    # Trailing whitespace keeps EVERY prefix of the body valid JSON, so the
    # only thing that can refuse it is the byte cap itself (a truncated object
    # would read as idle for the wrong reason).
    monkeypatch.setattr(w.urllib.request, "urlopen",
                        lambda *a, **k: _Resp(b"{}" + b" " * 64))
    assert w._fetch_state() is None


def test_fetch_state_transport_error_reads_idle(monkeypatch):
    def _boom(*_a, **_k):
        raise ConnectionRefusedError("dashboard down")
    monkeypatch.setattr(w.urllib.request, "urlopen", _boom)
    assert w._fetch_state() is None


def test_fetch_state_programming_error_surfaces(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("a bug, not a down dashboard")
    monkeypatch.setattr(w.urllib.request, "urlopen", _boom)
    with pytest.raises(RuntimeError):
        w._fetch_state()


# --- 1 + 2. _resolve_game ---------------------------------------------------

def test_resolve_game_characterization(ids):
    assert w._resolve_game(_state()) == ("Ahri", "sr", ["Zed", "TahmKench"])


def test_resolve_game_not_live_mode(ids):
    assert w._resolve_game(_state(mode="lobby")) is None


@pytest.mark.parametrize("state", [
    [1, 2],
    "sr",
    {"mode_key": 5, "coach": {"champion": "Ahri"}, "liveclient": {"allPlayers": []}},
    {"mode_key": "sr", "coach": "Ahri", "liveclient": {"allPlayers": [{}]}},
    {"mode_key": "sr", "coach": {"champion": 7}, "liveclient": {"allPlayers": [{}]}},
    {"mode_key": "sr", "coach": {"champion": "Ahri"}, "liveclient": ["x"]},
    {"mode_key": "sr", "coach": {"champion": "Ahri"},
     "liveclient": {"allPlayers": {"Ahri": "ORDER"}}},
])
def test_resolve_game_malformed_shape_reads_not_live(ids, state):
    assert w._resolve_game(state) is None


def test_resolve_game_skips_malformed_player_entries(ids):
    players = [
        "Ahri",
        None,
        {"championName": None, "team": "CHAOS"},
        {"championName": "Ahri", "team": "ORDER"},
        {"championName": "Zed", "team": "CHAOS"},
    ]
    assert w._resolve_game(_state(players=players)) == ("Ahri", "sr", ["Zed"])


def test_resolve_game_my_champ_absent_is_not_resolved(ids):
    players = [
        {"championName": "Lux", "team": "ORDER"},
        {"championName": "Zed", "team": "CHAOS"},
    ]
    # Before: my_team None -> Lux (an ALLY) and Zed both listed as enemies.
    assert w._resolve_game(_state(players=players)) is None


# --- 3. baked report + credit tables ----------------------------------------

def test_load_report_characterization(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_REPORT", tmp_path)
    rows = [{"champion": "Ahri", "seams": {}}, {"champion": "Zed", "seams": {}}]
    (tmp_path / "live_flip_eyeball.json").write_text(json.dumps(rows), encoding="utf-8")
    assert sorted(w._load_report(None)) == ["Ahri", "Zed"]


@pytest.mark.parametrize("payload, want", [
    ({"champion": "Ahri"}, []),
    ("text", []),
    ([{"champion": "Ahri", "seams": {}}, {"seams": {}}, 5, None,
      {"champion": 7}, {"champion": ""}], ["Ahri"]),
])
def test_load_report_malformed_rows_are_skipped(tmp_path, monkeypatch, payload, want):
    monkeypatch.setattr(w, "_REPORT", tmp_path)
    (tmp_path / "live_flip_eyeball.json").write_text(json.dumps(payload), encoding="utf-8")
    assert sorted(w._load_report(None)) == want


def test_load_report_missing_reads_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_REPORT", tmp_path)
    assert w._load_report("squishy") == {}


def test_table_names_characterization(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    (tmp_path / "t.json").write_text(json.dumps({"champions": {
        "Ahri": {"items": [{"name": "Lich Bane"}, {"name": "Shadowflame"}]}}}),
        encoding="utf-8")
    (tmp_path / "m.json").write_text(json.dumps({"Jinx": ["Kraken Slayer"]}),
                                     encoding="utf-8")
    assert w._table_names("t.json", "Ahri") == {"Lich Bane", "Shadowflame"}
    assert w._table_names("m.json", "Jinx") == {"Kraken Slayer"}


@pytest.mark.parametrize("payload", [
    [1, 2],
    {"champions": ["Ahri"]},
    {"champions": {"Ahri": {"items": "Lich Bane"}}},
    {"champions": {"Ahri": "Lich Bane"}},
])
def test_table_names_malformed_table_reads_empty(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(w, "_DS", tmp_path)
    (tmp_path / "t.json").write_text(json.dumps(payload), encoding="utf-8")
    assert w._table_names("t.json", "Ahri") == set()


def test_table_names_drops_non_string_names(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    (tmp_path / "t.json").write_text(json.dumps({"champions": {
        "Ahri": {"items": [{"name": "Lich Bane"}, {}, {"name": None}, "x"]},
        "Jinx": ["Kraken Slayer", None, 3]}}), encoding="utf-8")
    # Before: {} contributed "" and a list entry None became the name "None".
    assert w._table_names("t.json", "Ahri") == {"Lich Bane"}
    assert w._table_names("t.json", "Jinx") == {"Kraken Slayer"}


# --- 4. _classify -----------------------------------------------------------

def test_classify_characterization(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    (tmp_path / "kit_axis_item_credit.json").write_text(json.dumps({"champions": {
        "Ahri": {"items": [{"name": "Lich Bane"}]}}}), encoding="utf-8")
    row = {"seams": {
        "DSP11_kit_axis_burst": _seam(entered=["Lich Bane"]),
        "DSP11_kit_axis_dps": _seam(entered=["Kraken Slayer"]),
        "DSV3_assume_squishy_target": _seam(entered=["Shadowflame"]),
        "DSV2_assume_takedown": _seam(moves=False),
    }}
    v = w._classify(row, None, "Ahri")
    assert v["flip_ready"] == [("DSP11_kit_axis_burst", "SANER", ["Lich Bane"]),
                               ("DSP11_kit_axis_dps", "REVIEW", ["Kraken Slayer"])]
    assert v["check"] == [("DSV3_assume_squishy_target", ["Shadowflame"])]
    assert v["n_moved"] == 3


def test_classify_string_entered_is_not_split_into_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    row = {"seams": {"DSV3_assume_squishy_target": {"moves": True,
                                                    "entered": "Lich Bane"}}}
    v = w._classify(row, None, "Ahri")
    # Before: the str was carried through and _emit joined it per CHARACTER
    # ("+L,i"). A seam detail whose "entered" is not a list is malformed and
    # makes no verdict claim at all.
    assert v == {"flip_ready": [], "check": [], "n_moved": 0}


def test_classify_drops_non_string_entered_items(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    row = {"seams": {"DSV3_assume_squishy_target": _seam(entered=["Eclipse", 3, None])}}
    assert w._classify(row, None, "Ahri")["check"] == [
        ("DSV3_assume_squishy_target", ["Eclipse"])]


@pytest.mark.parametrize("row", [
    {"seams": ["DSV3"]},
    {"seams": {"DSV3_assume_squishy_target": "moves"}},
    {"seams": {"DSV3_assume_squishy_target": None}},
    {},
])
def test_classify_malformed_seams_do_not_raise(tmp_path, monkeypatch, row):
    monkeypatch.setattr(w, "_DS", tmp_path)
    assert w._classify(row, None, "Ahri")["n_moved"] == 0


# --- 5 + 6 + 7. the per-game verdict ---------------------------------------

def _tank_row():
    return {"champion": "Ahri", "seams": {
        "DSP8_target_preset=tank": _seam(entered=["Thornmail"]),
        "DSV3_assume_squishy_target": _seam(entered=["Shadowflame"]),
    }}


def test_verdict_tank_uses_the_base_dsp8_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    v = w._verdict_for("Ahri", "tank", {"Ahri": _tank_row()}, {})
    assert ("DSP8_target_preset=tank", ["Thornmail"]) in v["check"]
    assert v["baked"] is True


def test_verdict_grafts_the_comp_preset_dsp8_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    squishy = {"Ahri": {"champion": "Ahri", "seams": {
        "DSP8_target_preset=squishy": _seam(entered=["Void Staff"])}}}
    v = w._verdict_for("Ahri", "squishy", {"Ahri": _tank_row()}, {"squishy": squishy})
    keys = [s for s, _e in v["check"]]
    assert "DSP8_target_preset=squishy" in keys
    assert "DSP8_target_preset=tank" not in keys


def test_verdict_drops_the_tank_dsp8_when_the_comp_row_is_not_baked(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    v = w._verdict_for("Ahri", "squishy", {"Ahri": _tank_row()}, {"squishy": {}})
    keys = [s for s, _e in v["check"]] + [s for s, _t, _e in v["flip_ready"]]
    # Before: the TANK verdict was printed under the [squishy] label.
    assert not any(k.startswith("DSP8_target_preset=") for k in keys)
    assert ("DSV3_assume_squishy_target", ["Shadowflame"]) in v["check"]


def test_verdict_falls_back_to_the_preset_row(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    squishy = {"Darius": {"champion": "Darius", "seams": {
        "DSP8_target_preset=squishy": _seam(entered=["Black Cleaver"]),
        "DSV3_assume_squishy_target": _seam(entered=["Eclipse"])}}}
    v = w._verdict_for("Darius", "squishy", {"Ahri": _tank_row()}, {"squishy": squishy})
    # Before: base.get("Darius") is None -> "no tabled seams, any build is baseline".
    assert v["baked"] is True
    assert v["n_moved"] == 2


def test_verdict_for_an_unbaked_champion_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "_DS", tmp_path)
    v = w._verdict_for("Teemo", "tank", {"Ahri": _tank_row()}, {"squishy": {}})
    assert v["baked"] is False
    assert v["n_moved"] == 0


def test_emit_unbaked_champion_does_not_claim_baseline(notes, verdict_paths):
    md, _jl = verdict_paths
    w._emit("Teemo", "sr", "tank",
            {"flip_ready": [], "check": [], "n_moved": 0, "baked": False}, ["Zed"])
    title, body = notes[-1]
    text = title + body + md.read_text(encoding="utf-8")
    assert "baseline" not in text.lower()
    assert "not baked" in text.lower()


def test_emit_baked_no_move_still_says_baseline(notes, verdict_paths):
    w._emit("Ahri", "sr", "tank",
            {"flip_ready": [], "check": [], "n_moved": 0, "baked": True}, ["Zed"])
    assert "baseline" in notes[-1][1].lower()


# --- 8. verdict writes ------------------------------------------------------

def test_emit_writes_the_md_atomically(notes, verdict_paths, monkeypatch):
    from core import polled_json
    md, _jl = verdict_paths
    calls: list = []
    real = polled_json.atomic_write_text

    def _rec(path, content):
        calls.append(path)
        real(path, content)

    monkeypatch.setattr(polled_json, "atomic_write_text", _rec)
    w._emit("Ahri", "sr", "tank",
            {"flip_ready": [], "check": [], "n_moved": 0, "baked": True}, ["Zed"])
    assert calls == [md]
    assert md.read_bytes().startswith(b"# Live-flip verdict - Ahri")


def test_emit_survives_an_unwritable_verdict_dir(notes, tmp_path, monkeypatch):
    # "gone" is a FILE, so neither verdict path can be created (the atomic
    # helper's own mkdir(parents=True) cannot paper over it).
    (tmp_path / "gone").write_text("not a dir", encoding="utf-8")
    monkeypatch.setattr(w, "_VERDICT_MD", tmp_path / "gone" / "v.md")
    monkeypatch.setattr(w, "_VERDICT_JSONL", tmp_path / "gone" / "v.jsonl")
    # Before: FileNotFoundError out of _emit killed the poll loop.
    w._emit("Ahri", "sr", "tank",
            {"flip_ready": [], "check": [], "n_moved": 0, "baked": True}, ["Zed"])
    assert notes, "the toast still goes out"


# --- end to end: the poll loop ----------------------------------------------

def test_main_loop_emits_once_per_game_and_rearms(tmp_path, monkeypatch, ids,
                                                  notes, verdict_paths):
    _md, jl = verdict_paths
    stop = tmp_path / "WATCHER_STOP"
    monkeypatch.setattr(w, "_STOP", stop)
    base = {"Ahri": _tank_row()}
    squishy = {"Darius": {"champion": "Darius", "seams": {
        "DSV3_assume_squishy_target": _seam(entered=["Eclipse"])}}}
    monkeypatch.setattr(w, "_load_report",
                        lambda d: {None: base, "squishy": squishy}.get(d, {}))
    monkeypatch.setattr(w, "_pick_preset", lambda _e: "squishy")
    darius = _state(champ="Darius", players=[
        {"championName": "Darius", "team": "ORDER"},
        {"championName": "Zed", "team": "CHAOS"}])
    script = [darius, darius, {"mode_key": "lobby"}, darius, [1], None]
    monkeypatch.setattr(w, "_fetch_state", lambda: script.pop(0) if script else None)

    def _sleep(_s):
        if not script:
            stop.write_text("x", encoding="utf-8")

    monkeypatch.setattr(w.time, "sleep", _sleep)
    assert w.main() == 0
    rows = [json.loads(r) for r in jl.read_text(encoding="utf-8").splitlines()]
    assert [r["champ"] for r in rows] == ["Darius", "Darius"]
    assert all(r["verdict"]["n_moved"] == 1 for r in rows)
    assert not stop.exists()
