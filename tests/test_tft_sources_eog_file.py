"""TFT-02 (docs/TFT_PROGRAM.md section 7): the per-round EoG file source.

Acceptance, slice row TFT-02 (EoG half): from synthetic EoG snapshots, emit
per-round obs for all 8 players (HP, standing, board units / star / items)
into the TFT-01 round store; copy no identity key (the guard enumerates
them).

Fixtures: tests/fixtures/tft_sources/ - SYNTHETIC rewrites of
TFTEoGStats.json (every identity value is a Sentinel; shapes follow the live
file, measured 2026-10-25 and re-measured s135: the same 18 player keys and
5 board-piece keys). Each rewrite is written to a tmp file the P0 path seam
(tft/tft_standalone.py eog_stats_path, monkeypatched; tests/conftest.py pins
it to an absent file session-wide) points at, with the mtime from
timeline.json. Nothing here reads %LOCALAPPDATA%, data/ or logs/.

Local player: `isInteractable` does NOT mark it in a human lobby (s135
verifier: every end-of-game copy shows 8/8; mid-match the first interactable
row served the 8th-place player - bug N13), so the source never reads it.
The local player comes ONLY from the injected `local_player_id` (the LCU
summoner id, matched against a row's playerId, or a PUUID) and is unknown
otherwise - never a guess, never carried forward.
"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
from pathlib import Path

import pytest

from tft.rounds.store import RoundStore, player_key
from tft.sources import eog_file as ef

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "tft_sources"
SALT = b"tft02-synthetic-salt-0123456789ab"
LOCAL_UUID = "00000000-0000-4000-8000-00000000c0de"  # the fixture's sentinel PUUID
LOCAL_PLAYER_ID = 900002  # the fixture's sentinel playerId of that row (others: 0)
GAME_ID = 5000000123

# docs/TFT_PROGRAM.md section 0 item 2 - identity fields RC must never copy,
# transcribed by hand (not imported from the module, so the two are compared).
SPEC_IDENTITY = {"PUUID", "riotIdGameName", "riotIdTagLine", "summonerName", "playerId",
                 "companionContentId", "companionName", "companionSkinId"}


def _timeline():
    return json.loads((FIX / "timeline.json").read_text(encoding="ascii"))


def _rewrites():
    tl = _timeline()
    out = []
    for r in tl["rewrites"]:
        doc = json.loads((FIX / r["file"]).read_text(encoding="ascii"))
        out.append((doc, float(tl["t0_epoch"]) + float(r["t"])))
    return out


def _players(doc):
    return doc["statsBlock"]["players"]


class Clock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def eog_path(tmp_path, monkeypatch):
    p = tmp_path / "Logs" / "TFTEoGStats.json"
    p.parent.mkdir(parents=True)
    # the P0 path seam; tests/conftest.py pins it to an absent file session-wide
    monkeypatch.setattr(ef.p0, "eog_stats_path", lambda: p)
    return p


def _put(path: Path, doc, mtime: float, raw: bytes = None):
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(raw if raw is not None else json.dumps(doc, indent=1).encode("ascii"))
    tmp.replace(path)
    os.utime(path, (mtime, mtime))


@pytest.fixture
def store(tmp_path):
    s = RoundStore.open(tmp_path / "tft" / "tft_rounds.db")
    try:
        yield s
    finally:
        s.close()


def _replay(eog_path, ingest, clock, docs=None):
    """Write each rewrite, poll once; returns the written results."""
    out = []
    for doc, mtime in (docs or _rewrites()):
        _put(eog_path, doc, mtime)
        clock.now = mtime + 1.0
        out.append(ingest.poll())
    return out


def _expected_key(p):
    if p["PUUID"] == LOCAL_UUID:
        return player_key(LOCAL_UUID, SALT)
    return player_key(f"{p['riotIdGameName']}#{p['riotIdTagLine']}", SALT)


# ---------------------------------------------------------------- parse


def test_parse_emits_all_8_players_hp_standing_and_board():
    doc, mtime = _rewrites()[2]  # rewrite 03: player 7 eliminated (health -4, standing 8)
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    assert snap is not None
    assert (snap.game_id, snap.queue_id, snap.set_core_name, snap.set_id) == (GAME_ID, 1090, "TFTSet18", 18)
    assert snap.game_length_s == 105 and snap.mtime == mtime
    assert len(snap.players) == 8
    for got, raw in zip(snap.players, _players(doc)):
        assert got.player_key == _expected_key(raw)
        assert got.hp_raw == raw["health"]
        assert got.hp == max(raw["health"], 0)
        assert got.alive is (raw["health"] > 0)
        assert got.standing == (raw["ffaStanding"] or None)
        assert [(u.champion_api, u.star, list(u.items), u.cost) for u in got.board] == [
            (b["championName"], b["starLevel"], b["itemNames"], b["price"]) for b in raw["boardPieces"]]
    dead = snap.players[7]
    assert (dead.hp_raw, dead.hp, dead.alive, dead.standing) == (-4, 0, False, 8)


def _unknown(snap):
    return snap.local_key is None and all(p.is_local is None for p in snap.players)


def test_without_an_injected_id_the_local_player_is_unknown():
    doc, mtime = _rewrites()[0]  # exactly one isInteractable row: still NOT the local player
    assert sum(p["isInteractable"] for p in _players(doc)) == 1
    assert _unknown(ef.parse_eog(doc, salt=SALT, mtime=mtime))


@pytest.mark.parametrize("local_id", [LOCAL_PLAYER_ID, str(LOCAL_PLAYER_ID), LOCAL_UUID])
def test_the_injected_id_picks_the_matching_entry_whatever_isinteractable_says(local_id):
    doc, mtime = copy.deepcopy(_rewrites()[0])
    for p in _players(doc):
        p["isInteractable"] = p["PUUID"] != LOCAL_UUID  # the flags lie: ignored
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=local_id)
    assert snap.local_key == player_key(LOCAL_UUID, SALT)
    assert [p.is_local for p in snap.players] == [i == 2 for i in range(8)]


@pytest.mark.parametrize("local_id", [None, 0, "0", 123, "", "  ", True, 1.5, "nobody",
                                      "00000000-0000-0000-0000-000000000000", ["x"]])
def test_an_id_that_matches_no_single_entry_leaves_the_local_unknown(local_id):
    doc, mtime = _rewrites()[0]
    assert _unknown(ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=local_id))


@pytest.mark.parametrize("local_id", [0, "0", "000"])
def test_a_zero_id_never_selects_a_zero_player_id_row(local_id):
    doc, mtime = copy.deepcopy(_rewrites()[0])
    for i, p in enumerate(_players(doc)):  # live shape: non-zero ids, here one stray 0
        p["playerId"] = 0 if i == 4 else 800000 + i
    assert _unknown(ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=local_id))


def test_an_id_matching_two_entries_is_not_a_guess():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    _players(doc)[5]["playerId"] = LOCAL_PLAYER_ID
    assert _unknown(ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=LOCAL_PLAYER_ID))


def test_zero_puuid_falls_back_to_the_riot_id_and_keys_stay_distinct():
    doc, mtime = _rewrites()[0]
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    keys = [p.player_key for p in snap.players]
    assert len(set(keys)) == 8, "zeroed PUUIDs must not collapse 7 players into one key"
    assert keys == [_expected_key(p) for p in _players(doc)]


def test_a_real_puuid_keys_the_player():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    for i, p in enumerate(_players(doc)):
        p["PUUID"] = f"00000000-0000-4000-8000-0000000000{i:02d}"
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    assert [p.player_key for p in snap.players] == [
        player_key(f"00000000-0000-4000-8000-0000000000{i:02d}", SALT) for i in range(8)]


def test_no_identity_anywhere_falls_back_to_a_stable_slot_key():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    for p in _players(doc):
        for k in ("PUUID", "riotIdGameName", "riotIdTagLine", "summonerName"):
            p[k] = ""
    a = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    b = ef.parse_eog(doc, salt=SALT, mtime=mtime + 40)
    assert len({p.player_key for p in a.players}) == 8
    assert [p.player_key for p in a.players] == [p.player_key for p in b.players]


def test_eight_of_eight_interactable_is_unknown_without_the_id_and_exact_with_it():
    doc, mtime = copy.deepcopy(_rewrites()[5])
    for p in _players(doc):
        p["isInteractable"] = True  # the live end-of-game shape (measured s135)
    assert _unknown(ef.parse_eog(doc, salt=SALT, mtime=mtime))
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime, local_player_id=LOCAL_PLAYER_ID)
    assert [p.is_local for p in snap.players] == [i == 2 for i in range(8)]


def _poll_all(eog_path, src, clock, docs):
    out = []
    for doc, mtime in docs:
        _put(eog_path, doc, mtime)
        clock.now = mtime + 1
        out.append(src.poll())
    return out


def test_an_earlier_single_interactable_round_is_not_carried_forward(eog_path):
    docs = copy.deepcopy(_rewrites())
    for p in _players(docs[5][0]):
        p["isInteractable"] = True
    clock = Clock()
    snaps = _poll_all(eog_path, ef.EogFileSource(salt=SALT, clock=clock), clock, docs)
    assert [s.local_key for s in snaps] == [None] * 6  # rounds 1-5 had ONE interactable row


def test_a_late_or_lost_id_is_never_back_or_forward_filled(eog_path):
    local = player_key(LOCAL_UUID, SALT)
    ids = iter([None, LOCAL_PLAYER_ID, None, "boom", LOCAL_PLAYER_ID, None])

    def resolve():
        v = next(ids)
        if v == "boom":
            raise RuntimeError("helper failed")
        return v

    clock = Clock()
    src = ef.EogFileSource(salt=SALT, clock=clock, local_player_id=resolve)
    snaps = _poll_all(eog_path, src, clock, _rewrites())
    assert [s.local_key for s in snaps] == [None, local, None, None, local, None]


def test_malformed_values_are_dropped_never_raised():
    doc, mtime = copy.deepcopy(_rewrites()[0])
    p0 = _players(doc)[0]
    p0["health"] = "lots"
    p0["ffaStanding"] = 12
    p0["boardPieces"] = [
        {"championName": "SentinelGameName0", "starLevel": 1, "itemNames": [], "price": 1},
        {"championName": "DA_18_Yorick", "starLevel": 9, "price": "x",
         "itemNames": ["DA_GiantSlayer", "SentinelGameName0#ST00", 7, None]},
        "not-a-piece", None,
    ]
    snap = ef.parse_eog(doc, salt=SALT, mtime=mtime)
    got = snap.players[0]
    assert (got.hp_raw, got.hp, got.alive, got.standing) == (None, None, None, None)
    assert [(u.champion_api, u.star, u.items, u.cost) for u in got.board] == [
        ("DA_18_Yorick", None, ("DA_GiantSlayer",), None)]
    for bad in (None, [], "x", {"gameMode": "TFT"}, {"gameMode": "TFT", "statsBlock": "x"},
                {"gameMode": "CLASSIC", "statsBlock": {"players": _players(doc)}}):
        assert ef.parse_eog(bad, salt=SALT) is None


# ---------------------------------------------------------------- identity guard


def test_every_file_key_is_classified_and_identity_is_never_copied():
    """The guard ENUMERATES the file's keys: each one is copied, identity
    (read in memory for the HMAC key at most) or ignored - a new Riot field
    fails here until someone classifies it."""
    assert SPEC_IDENTITY <= ef.IDENTITY_KEYS
    assert not ef.IDENTITY_KEYS & (ef.PLAYER_FIELDS | ef.PIECE_FIELDS | ef.DOC_FIELDS | ef.STATS_FIELDS)
    assert set(ef.KEY_BASIS_FIELDS) <= ef.IDENTITY_KEYS
    assert set(ef.LOCAL_MATCH_FIELDS) <= ef.IDENTITY_KEYS
    # isInteractable is NOT a local-player signal (bug N13): never read
    assert "isInteractable" in ef.IGNORED_KEYS and "isInteractable" not in ef.PLAYER_FIELDS
    seen = {"doc": set(), "stats": set(), "player": set(), "piece": set()}
    for doc, _ in _rewrites():
        seen["doc"] |= set(doc)
        seen["stats"] |= set(doc["statsBlock"])
        for p in _players(doc):
            seen["player"] |= set(p)
            for b in p["boardPieces"]:
                seen["piece"] |= set(b)
    known = ef.IDENTITY_KEYS | ef.IGNORED_KEYS
    assert seen["doc"] <= ef.DOC_FIELDS | known
    assert seen["stats"] <= ef.STATS_FIELDS | known
    assert seen["player"] <= ef.PLAYER_FIELDS | known
    assert seen["piece"] <= ef.PIECE_FIELDS | known
    assert seen["player"] & ef.IDENTITY_KEYS == SPEC_IDENTITY | {"summonerIconID"}


def _canaried():
    """Every rewrite with each NON-copied value replaced by a unique canary.
    Identity values stay distinct per player so the keys stay distinct."""
    docs = copy.deepcopy(_rewrites())
    n = 0
    for doc, _ in docs:
        for k in list(doc):
            if k not in ef.DOC_FIELDS:
                doc[k] = f"CANARYdoc{k}"
        for k in list(doc["statsBlock"]):
            if k not in ef.STATS_FIELDS:
                doc["statsBlock"][k] = f"CANARYstats{k}"
        for i, p in enumerate(_players(doc)):
            for k in list(p):
                if k not in ef.PLAYER_FIELDS:
                    n += 1
                    p[k] = "" if k == "PUUID" and i != 2 else f"CANARY{k}{i}"
            for b in p["boardPieces"]:
                for k in list(b):
                    if k not in ef.PIECE_FIELDS:
                        b[k] = f"CANARYpiece{k}"
    assert n > 0
    return docs


def _db_bytes(path: Path) -> bytes:
    blob = b""
    for suffix in ("", "-wal"):
        p = Path(str(path) + suffix)
        if p.exists():
            blob += p.read_bytes()
    return blob


def test_no_identity_value_or_key_reaches_a_snapshot_or_the_store(eog_path, tmp_path, caplog):
    caplog.set_level("DEBUG")
    db = tmp_path / "guard" / "tft_rounds.db"
    st = RoundStore.open(db)
    clock = Clock()
    # the injected id is identity too: it may select the row, never be copied
    ing = ef.EogIngest(st, salt=SALT, source=ef.EogFileSource(
        salt=SALT, clock=clock, local_player_id="CANARYPUUID2"))
    docs = _canaried()
    results = _replay(eog_path, ing, clock, docs)
    assert all(r is not None and r.snapshot.local_key is not None for r in results)
    st.flush()
    reprs = repr([r.snapshot for r in results])
    doc = st.get_match(results[0].match_id)
    dump = json.dumps(doc, default=str)
    st.close()
    blob = _db_bytes(db)
    for text in (reprs, dump, caplog.text):
        assert "CANARY" not in text
        assert "Sentinel" not in text
    assert b"CANARY" not in blob and b"Sentinel" not in blob
    for key in sorted(ef.IDENTITY_KEYS):
        assert key not in dump, key
        assert key.encode("ascii") not in blob, key


# ---------------------------------------------------------------- source


def test_source_emits_each_rewrite_once(eog_path):
    clock = Clock()
    src = ef.EogFileSource(salt=SALT, clock=clock)
    assert src.poll() is None  # no file yet
    rw = _rewrites()
    _put(eog_path, rw[0][0], rw[0][1])
    clock.now = rw[0][1] + 1
    first = src.poll()
    assert first is not None and first.rewrite_index == 1
    assert src.poll() is None  # unchanged file
    _put(eog_path, rw[0][0], rw[0][1] + 3)  # same content, new mtime: no new round
    assert src.poll() is None
    _put(eog_path, None, rw[1][1], raw=b'{"gameId": 50000001')  # torn mid-write
    clock.now = rw[1][1] + 1
    assert src.poll() is None
    _put(eog_path, rw[1][0], rw[1][1])
    second = src.poll()
    assert second is not None and second.rewrite_index == 2
    assert src.stats["snapshots"] == 2


def test_a_content_change_at_the_same_game_length_updates_the_same_round(eog_path):
    clock = Clock()
    src = ef.EogFileSource(salt=SALT, clock=clock)
    doc, mtime = copy.deepcopy(_rewrites()[1])
    _put(eog_path, doc, mtime)
    clock.now = mtime + 1
    assert src.poll().rewrite_index == 1
    _players(doc)[0]["health"] = 50
    _put(eog_path, doc, mtime + 2)
    again = src.poll()
    assert again.rewrite_index == 1 and again.players[0].hp == 50


def test_a_stale_file_is_ignored_until_it_is_rewritten(eog_path):
    clock = Clock()
    src = ef.EogFileSource(salt=SALT, clock=clock)
    doc, mtime = _rewrites()[0]
    _put(eog_path, doc, mtime)
    clock.now = mtime + 10_000  # older than the P0 freshness window (a finished game)
    assert src.poll() is None
    assert src.stats["stale_or_torn"] == 1
    clock.now = mtime + 1
    assert src.poll().rewrite_index == 1


def test_an_oversized_file_is_never_read(eog_path, monkeypatch):
    clock = Clock()
    src = ef.EogFileSource(salt=SALT, clock=clock, max_bytes=4096)
    doc, mtime = _rewrites()[0]
    _put(eog_path, doc, mtime)  # 7.7 KB > the 4 KB cap
    clock.now = mtime + 1
    reads = []
    monkeypatch.setattr(ef.p0, "read_eog", lambda **kw: reads.append(kw) or None)
    assert src.poll() is None and src.poll() is None
    assert reads == [] and src.stats["oversize"] == 1


def test_a_new_game_id_restarts_the_rewrite_index(eog_path):
    clock = Clock()
    src = ef.EogFileSource(salt=SALT, clock=clock)
    rw = _rewrites()
    for doc, mtime in rw[:3]:
        _put(eog_path, doc, mtime)
        clock.now = mtime + 1
        last = src.poll()
    assert last.rewrite_index == 3
    nxt = copy.deepcopy(rw[0][0])
    nxt["gameId"] = GAME_ID + 1
    _put(eog_path, nxt, rw[3][1])
    clock.now = rw[3][1] + 1
    fresh = src.poll()
    assert (fresh.game_id, fresh.rewrite_index) == (GAME_ID + 1, 1)


# ---------------------------------------------------------------- into the round store


def _rows(db: Path, sql, args=()):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def test_ingest_hands_the_injected_id_to_its_default_source(store):
    ing = ef.EogIngest(store, salt=SALT, local_player_id=LOCAL_PLAYER_ID)
    assert ing.source.local_player_id == LOCAL_PLAYER_ID


def test_replay_writes_every_round_for_all_8_players(eog_path, store):
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(
        salt=SALT, clock=clock, local_player_id=LOCAL_PLAYER_ID))
    results = _replay(eog_path, ing, clock)
    assert [r.round_seq for r in results] == [1, 2, 3, 4, 5, 6]
    mid = results[0].match_id
    assert {r.match_id for r in results} == {mid} and mid == ef.match_id_for(GAME_ID, SALT)
    assert store.flush()
    doc = store.get_match(mid)
    m = doc["match"]
    assert (m["game_id"], m["queue_id"], m["queue_kind"], m["set_id"], m["set_core_name"]) == (
        GAME_ID, 1090, "normal", 18, "TFTSet18")
    assert m["started_at"] == pytest.approx(_rewrites()[0][1] - 45)
    assert m["extractor_version"] == ef.EXTRACTOR_VERSION

    raw = [_players(d) for d, _ in _rewrites()]
    keys = [_expected_key(p) for p in raw[0]]
    players = {p["player_key"]: p for p in doc["players"]}
    assert set(players) == set(keys)
    assert players[keys[2]]["slot"] == 1 and players[keys[2]]["is_local"] == 1
    assert sorted(players[k]["slot"] for k in keys if k != keys[2]) == list(range(2, 9))
    assert all(players[k]["is_local"] == 0 for k in keys if k != keys[2])
    final = {k: p["ffaStanding"] for k, p in zip(keys, raw[5])}
    for k in keys:
        assert players[k]["final_standing"] == final[k]
        assert players[k]["final_standing_src"] == "eog_file"
    elim = {k: p["eliminated_round_seq"] for k, p in players.items()}
    assert elim[keys[7]] == 3 and elim[keys[6]] == 4 and elim[keys[2]] is None
    assert all(elim[keys[i]] == 6 for i in (0, 1, 3, 4, 5))

    rounds = doc["rounds"]
    assert [r["round_seq"] for r in rounds] == [1, 2, 3, 4, 5, 6]
    for r, rp in zip(rounds, raw):
        assert r["hp_start"] == rp[2]["health"]
        assert (r["hp_start_conf"], r["hp_start_src"]) == (1.0, "eog_file")
        assert len(r["players"]) == 8
        by_key = {p["player_key"]: p for p in r["players"]}
        for k, p in zip(keys, rp):
            got = by_key[k]
            assert got["hp"] == max(p["health"], 0)
            assert got["alive"] == int(p["health"] > 0)
            assert got["standing"] == (p["ffaStanding"] or None)
            assert (got["conf"], got["src"]) == (1.0, "eog_file")
        units = r["units"]
        assert all(u["phase"] == "planning_start" and u["zone"] == "board"
                   and u["src"] == "eog_file" and u["conf"] == 1.0 for u in units)
        for k, p in zip(keys, rp):
            mine = [(u["champion_api"], u["star"], u["items"], u["cost"])
                    for u in units if u["player_key"] == k]
            assert mine == [(b["championName"], b["starLevel"], b["itemNames"], b["price"])
                            for b in p["boardPieces"]]
        obs = [o for o in r["obs"] if o["field"] == ef.OBS_PLAYER]
        assert len(obs) == 8 and all(o["src"] == "eog_file" and o["phase"] == "planning_start"
                                     for o in obs)
        assert {o["value"]["player_key"] for o in obs} == set(keys)
        hp_raw = {o["value"]["player_key"]: o["value"]["hp"] for o in obs}
        assert hp_raw == {k: p["health"] for k, p in zip(keys, rp)}  # obs keep the overkill
    for r, (d, mtime) in zip(rounds, _rewrites()):
        ev = [e for e in r["events"] if e["kind"] == "eog_rewrite"]
        assert len(ev) == 1 and ev[0]["src"] == "eog_file" and ev[0]["ts"] == mtime
        assert ev[0]["payload"] == {"rewrite_index": r["round_seq"],
                                    "game_length_s": d["statsBlock"]["gameLengthSeconds"]}
        meta = [o["value"] for o in r["obs"] if o["field"] == ef.OBS_ROUND]
        assert meta == [{"rewrite_index": r["round_seq"],
                         "game_length_s": d["statsBlock"]["gameLengthSeconds"],
                         "players": 8,
                         "players_alive": sum(p["health"] > 0 for p in _players(d)),
                         "local_known": True}]


def test_without_the_id_the_store_records_the_local_player_as_unknown(eog_path, store):
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    results = _replay(eog_path, ing, clock)
    assert store.flush()
    doc = store.get_match(results[0].match_id)
    assert len(doc["players"]) == 8
    assert all(p["is_local"] == 0 and p["slot"] is None for p in doc["players"])
    for r in doc["rounds"]:
        assert (r["hp_start"], r["hp_start_src"]) == (None, "absent")
        assert len(r["players"]) == 8  # all 8 players are still recorded
        ob = [o["value"] for o in r["obs"] if o["field"] == ef.OBS_PLAYER]
        assert len(ob) == 8 and all(v["is_local"] is None for v in ob)
        assert [o["value"]["local_known"] for o in r["obs"] if o["field"] == ef.OBS_ROUND] == [False]


def test_restart_resumes_the_same_match_without_duplicating_rounds(eog_path, store):
    rw = _rewrites()
    clock = Clock()
    a = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    first = _replay(eog_path, a, clock, rw[:3])
    assert store.flush()
    clock2 = Clock()
    b = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock2))
    # the restarted process first sees rewrite 03 again, then 04..06
    again = _replay(eog_path, b, clock2, rw[2:])
    assert [r.round_seq for r in again] == [3, 4, 5, 6]
    assert {r.match_id for r in first + again} == {first[0].match_id}
    assert store.flush()
    doc = store.get_match(first[0].match_id)
    assert [r["round_seq"] for r in doc["rounds"]] == [1, 2, 3, 4, 5, 6]
    assert sum(1 for r in doc["rounds"] for e in r["events"] if e["kind"] == "eog_rewrite") == 6
    # the re-seen rewrite 03 refreshes typed rows only: no duplicate raw evidence
    assert [len(r["obs"]) for r in doc["rounds"]] == [9] * 6
    keys = [_expected_key(p) for p in _players(rw[0][0])]
    elim = {p["player_key"]: p["eliminated_round_seq"] for p in doc["players"]}
    assert elim[keys[7]] == 3  # set before the restart, never moved to a later round
    assert len(store.list_matches()) == 1


def test_locate_maps_a_timestamp_to_its_round(eog_path, store):
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    assert ing.locate(0.0) is None  # no match yet
    rw = _rewrites()
    results = _replay(eog_path, ing, clock, rw)
    mid = results[0].match_id
    assert ing.locate(rw[0][1] - 20) == (mid, None)  # carousel before the first rewrite
    assert ing.locate(rw[0][1]) == (mid, 1)
    assert ing.locate(rw[1][1] - 0.5) == (mid, 1)
    assert ing.locate(rw[5][1] + 30) == (mid, 6)
    assert ing.locate(rw[5][1] + ef.ROUND_GAP_MAX_S + 1) is None  # long after: not this match
    assert ing.locate(rw[0][1] - 45 - ef.MATCH_START_SLACK_S - 1) is None  # before it began


def test_export_fixture_of_an_ingested_match_passes_the_scrub_guard(eog_path, store, tmp_path):
    clock = Clock()
    ing = ef.EogIngest(store, salt=SALT, source=ef.EogFileSource(
        salt=SALT, clock=clock, local_player_id=LOCAL_PLAYER_ID))
    results = _replay(eog_path, ing, clock)
    assert store.flush()
    out = store.export_fixture(results[0].match_id, tmp_path / "fx", name="tft02")
    fx = json.loads(out.read_text(encoding="ascii"))
    keys = {p["player_key"] for p in fx["players"]}
    assert keys == {f"P{i}" for i in range(1, 9)}
    assert "Sentinel" not in out.read_text(encoding="ascii")


def test_writes_are_fail_soft_on_a_closed_store(eog_path, tmp_path):
    st = RoundStore.open(tmp_path / "closed" / "tft_rounds.db")
    st.close()
    clock = Clock()
    ing = ef.EogIngest(st, salt=SALT, source=ef.EogFileSource(salt=SALT, clock=clock))
    doc, mtime = _rewrites()[0]
    _put(eog_path, doc, mtime)
    clock.now = mtime + 1
    res = ing.poll()  # must not raise
    assert res is None or res.round_seq == 1


def test_package_stays_stdlib_and_llm_free():
    src = "\n".join(p.read_text(encoding="ascii") for p in (ROOT / "tft" / "sources").glob("*.py"))
    for banned in ("anthropic", "requests", "urllib.request", "http.client", "socket"):
        assert f"import {banned}" not in src and f"from {banned}" not in src, banned
