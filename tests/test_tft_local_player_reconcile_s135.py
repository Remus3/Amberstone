"""S135 N13 reconciled at the s135 landing: ONE local-player pick and ONE
alive rule (tft/local_player.py) at every site, including the two that landed
beside N13 rather than with it:

- the S134 TFT board panel (P0-F, tft/tft_standalone.py ``_lobby`` /
  ``_round_state`` / the synthesized allgamedata): its "you" row and local
  HP / standing / board came from the first ``isInteractable`` entry, and its
  value-only HP rule served every negative HP as unknown, so the lobby
  emptied at the first elimination (an eliminated player keeps a real
  standing and a health of -11..0);
- N8's final-board check (tft/tft_final_board.py ``per_round_is_final`` /
  ``per_round_record``), which decides whether N8 rates a game as finished.

Each site gets the measured human-lobby shape (all 8 entries flagged, the
local entry neither first nor last, picked by the LCU summoner id) and the
unknown case (no id: withheld, never a guess). A tree-wide guard keeps
``isInteractable`` reads inside tft/local_player.py.

Fixture: tests/fixtures/tft_eog_round_human_lobby_n13.json (SYNTHETIC,
anonymized; local = playerId 900004 at index 3, 2nd on 73 HP; five players
eliminated with negative HP and real standings).
"""
from __future__ import annotations

import ast
import copy
import json
import time
from pathlib import Path

import pytest

from tests import _repo_walk
from tft import local_player as lp
from tft import tft_final_board as fb
from tft import tft_standalone as ts

REPO_ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures" / "tft_eog_round_human_lobby_n13.json"
GID = 5000000013
LOCAL_SID = 900004
LOCAL_IDX = 3


def _doc() -> dict:
    return json.loads(FIX.read_text(encoding="utf-8"))


def _lcu(sid=LOCAL_SID) -> dict:
    d = {"phase": "InProgress", "game_id": str(GID), "game_queue_mode": "TFT"}
    if sid is not None:
        d["summoner_id"] = sid
    return d


def _summary(doc=None, sid=LOCAL_SID) -> dict:
    return ts.standalone_liveclient_summary(_lcu(sid), running=True,
                                            eog=_doc() if doc is None else doc)


def _synth(doc=None, sid=LOCAL_SID) -> dict:
    return ts.synth_allgamedata(lcu=_lcu(sid), running=True,
                                eog=_doc() if doc is None else doc, now=time.time())


@pytest.fixture(autouse=True)
def _clear_caches():
    ts._reset_caches_for_tests()
    yield
    ts._reset_caches_for_tests()


def test_fixture_is_the_human_lobby_with_eliminations():
    players = _doc()["statsBlock"]["players"]
    assert len(players) == 8 and all(p["isInteractable"] is True for p in players)
    assert players[LOCAL_IDX]["playerId"] == LOCAL_SID and LOCAL_IDX not in (0, 7)
    assert sum(1 for p in players if p["health"] < 0 and p["ffaStanding"] >= 1) == 5


# -- P0-F panel: tft_standalone _lobby / _round_state / synth ------------------------

def test_panel_you_row_is_the_summoner_id_entry_not_the_first():
    lc = _summary()
    yous = [r for r in lc["players"] if r["you"]]
    assert len(yous) == 1
    assert yous[0] == {"standing": 2, "health": 73, "you": True, "board_size": 10}
    assert lc["hp"] == 73 and lc["standing"] == 2 and lc["board_size"] == 10
    assert lc["eliminated"] is False


def test_panel_lobby_survives_eliminations_with_hp_zero():
    lc = _summary()
    rows = lc["players"]
    assert len(rows) == 8, "an elimination (negative HP, real standing) emptied the lobby"
    assert [r["standing"] for r in rows] == list(range(1, 9))
    assert all(r["health"] >= 0 for r in rows)
    assert sorted(r["health"] for r in rows) == [0, 0, 0, 0, 0, 20, 45, 73]
    assert lc["players_alive"] == 3


def test_panel_local_unknown_without_an_id_lobby_kept_no_you():
    lc = _summary(sid=None)
    assert len(lc["players"]) == 8
    assert not any(r["you"] for r in lc["players"])
    assert "hp" not in lc and "board" not in lc and "standing" not in lc
    raw = _synth(sid=None)
    assert [p for p in raw["allPlayers"] if p["summonerName"] == ts.LOCAL_NAME] == []
    assert raw["rc_standalone"]["local"] == {}
    assert raw["rc_standalone"]["local_index"] is None


def test_synth_one_local_row_and_eliminated_rows_dead_at_hp_zero():
    raw = _synth()
    rows = raw["allPlayers"]
    local = [p for p in rows if p["summonerName"] == ts.LOCAL_NAME]
    assert len(local) == 1 and rows.index(local[0]) == LOCAL_IDX
    assert local[0]["health"] == 73 and local[0]["isDead"] is False
    assert raw["activePlayer"]["currentHP"] == 73
    dead = [p for p in rows if p["isDead"]]
    assert len(dead) == 5 and all(p["health"] == 0 for p in dead)


def test_start_of_game_placeholders_are_unknown_never_eliminated():
    doc = _doc()
    for p in doc["statsBlock"]["players"]:
        p["health"], p["ffaStanding"] = -1, -1
    lc = _summary(doc)
    assert "players" not in lc, "a lobby of placeholders was served"
    assert lc["players_alive"] is None
    assert lc["hp"] is None and lc["standing"] is None and lc["eliminated"] is None
    raw = _synth(doc)
    assert not any(p["isDead"] for p in raw["allPlayers"])
    assert all("health" not in p for p in raw["allPlayers"])
    assert "currentHP" not in raw["activePlayer"]


# -- N8 final-board check: tft_final_board -------------------------------------------

def _with(doc, idx_health):
    doc = copy.deepcopy(doc)
    for i, (hp, standing) in idx_health.items():
        doc["statsBlock"]["players"][i]["health"] = hp
        doc["statsBlock"]["players"][i]["ffaStanding"] = standing
    return doc


def test_final_check_reads_the_summoner_id_entry():
    doc = _doc()  # local alive on 73, two others alive: mid-game
    assert fb.per_round_is_final(doc, summoner_id=LOCAL_SID) is False
    won = _with(doc, {1: (-4, 2), 6: (-2, 3), LOCAL_IDX: (60, 1)})
    assert fb.per_round_is_final(won, summoner_id=LOCAL_SID) is True
    out = _with(doc, {LOCAL_IDX: (-5, 4)})
    assert fb.per_round_is_final(out, summoner_id=LOCAL_SID) is True


def test_final_check_unknown_local_is_never_final():
    won = _with(_doc(), {1: (-4, 2), 6: (-2, 3), LOCAL_IDX: (60, 1)})
    # all 8 flagged and no id: the first entry (eliminated, 8th) is NOT us
    assert fb.per_round_is_final(won, summoner_id=None) is False
    assert fb.per_round_is_final(won, summoner_id=123) is False


def test_final_check_placeholders_never_end_a_game():
    doc = _doc()
    for p in doc["statsBlock"]["players"]:
        p["health"], p["ffaStanding"] = -1, -1
    assert fb.per_round_is_final(doc, summoner_id=LOCAL_SID) is False


def test_per_round_record_passes_the_relay_summoner_id(monkeypatch):
    won = _with(_doc(), {1: (-4, 2), 6: (-2, 3), LOCAL_IDX: (60, 1)})
    monkeypatch.setattr(ts, "read_eog", lambda **_kw: won)
    monkeypatch.setattr(ts, "relay_lcu_snapshot", lambda: {"summoner_id": LOCAL_SID})
    rec = fb.per_round_record(now=time.time())
    assert rec["per_round_final"] is True
    assert rec["local_placement"] == 1 and rec["local_hp"] == 60
    monkeypatch.setattr(ts, "relay_lcu_snapshot", lambda: None)
    rec = fb.per_round_record(now=time.time())
    assert rec["per_round_final"] is False
    assert rec["local_placement"] is None


# -- the shared rule ------------------------------------------------------------------

def test_player_status_eliminated_needs_a_real_standing():
    assert lp.player_status({"health": -11, "ffaStanding": 6}) == lp.ELIMINATED
    assert lp.player_status({"health": 0, "ffaStanding": 8}) == lp.ELIMINATED
    assert lp.player_status({"health": -1, "ffaStanding": -1}) is None
    assert lp.player_status({"health": 12, "ffaStanding": -1}) == lp.ALIVE


# -- tree-wide guard: isInteractable is read only in tft/local_player.py -------------

ALLOWED_FILE = "tft/local_player.py"
# tft/sources/eog_file.py may NAME the key only in its IGNORED_KEYS set (TFT-02)
IGNORED_KEYS_FILE = "tft/sources/eog_file.py"
KEY = "isInteractable"
WEB_PATTERNS = ("*.js", "*.mjs", "*.cjs", "*.ts", "*.html")


def _docstring_ids(tree) -> set:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def key_reads(src: str, rel: str) -> list:
    """Line numbers where ``src`` uses the literal key outside a docstring
    (a subscript, a .get(), a comparison - any code use), minus the allowed
    file and the IGNORED_KEYS set of the round-store source."""
    if rel == ALLOWED_FILE:
        return []
    tree = ast.parse(src)
    docs = _docstring_ids(tree)
    allowed = set()
    if rel == IGNORED_KEYS_FILE:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "IGNORED_KEYS" for t in node.targets):
                allowed |= {id(n) for n in ast.walk(node.value)}
    return [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and n.value == KEY
            and id(n) not in docs and id(n) not in allowed]


def _production(patterns) -> list:
    _repo_walk.self_check(REPO_ROOT)
    out = []
    for p in _repo_walk.repo_files(REPO_ROOT, patterns):
        rel = _repo_walk.relative_posix(p, REPO_ROOT)
        if rel.startswith("tests/"):
            continue  # fixtures WRITE the key; reading it is the concern
        out.append((p, rel))
    return out


def test_no_isinteractable_read_outside_local_player():
    files = _production(("*.py", "*.pyw"))
    assert len(files) > 500, f"enumeration collapsed: {len(files)} files"
    assert any(rel == ALLOWED_FILE for _p, rel in files), "tft/local_player.py not enumerated"
    offenders = {}
    for p, rel in files:
        src = p.read_text(encoding="utf-8", errors="replace")
        if KEY not in src:
            continue
        hits = key_reads(src, rel)
        if hits:
            offenders[rel] = hits
    assert offenders == {}, (
        f"{KEY} read outside {ALLOWED_FILE}: pick the local TFT player through "
        f"tft.local_player (local_player_index / local_player): {offenders}")


def test_no_isinteractable_in_web_or_shell_code():
    hits = [rel for p, rel in _production(WEB_PATTERNS)
            if KEY in p.read_text(encoding="utf-8", errors="replace")]
    assert hits == []


def test_guard_positive_control():
    planted = (
        'def pick(players):\n'
        '    """Docstring naming isInteractable is fine."""\n'
        '    # a comment naming isInteractable is fine\n'
        '    return next(p for p in players if p.get("isInteractable") is True)\n'
    )
    assert key_reads(planted, "tft/somewhere.py") == [4]
    assert key_reads('x = p["isInteractable"]\n', "tools/x.py") == [1]
    assert key_reads(planted, ALLOWED_FILE) == []
    src = 'IGNORED_KEYS = frozenset({"isInteractable", "isRanked"})\n'
    assert key_reads(src, IGNORED_KEYS_FILE) == []
    assert key_reads(src + 'y = d.get("isInteractable")\n', IGNORED_KEYS_FILE) == [2]
