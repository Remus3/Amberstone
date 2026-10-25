"""TFT-09 (docs/TFT_PROGRAM.md section 7): the TFT view routes on :8888.

Acceptance, slice row TFT-09: GET /api/tft/live, /api/tft/matches,
/api/tft/match/<id> (+ ?fixture=), /api/tft/icon/<cat>/<api> (404 when not
cached), POST /api/tft/match/<id>/export; route tests on a fixture store; no
raw upstream error surfaced. Session 134 adds: the scouting digest and the
engine outputs (recommend, milestones, planner choices), fail-soft, no
blocking call on the request thread.

Every store here is SYNTHETIC, written through the TFT-01 writer API
(tft/rounds/store.py) into tmp_path. Player keys come from the store's own
player_key() over the made-up names `SyntheticPlayer<i>` (never stored). Unit /
item api names are Set 18 game-data names from tracked
data/meta/tft_set18_cdragon.json (the same list tests/test_tft_rounds_store.py
cites). The RM-616 records come from the sanitised tracked fixtures
tests/fixtures/tft_eog_stats_set18.json / tft_match_history_set18.json via
tft_placement.parse_eog / parse_history (their placeholder game id 1000000001).
The icon file is 16 synthetic bytes with a PNG signature - no Riot art.
"""
from __future__ import annotations

import copy
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from core import live_game_gate
from dashboard import _dispatch
from dashboard import routes_tft as rt
from tft import engine as tft_engine
from tft import tft_placement as tp
from tft import tft_scouting
from tft.assets import icon_cache
from tft.rounds import store as st
from tft.rounds.store import Env, RoundStore
from tests._module_view import this_thread_only

REPO = Path(__file__).resolve().parent.parent
FIX = REPO / "tests" / "fixtures"
EOG_DOC = json.loads((FIX / "tft_eog_stats_set18.json").read_text(encoding="utf-8"))
HIST_DOC = json.loads((FIX / "tft_match_history_set18.json").read_text(encoding="utf-8"))
LOCAL_PUUID = "11111111-1111-1111-1111-111111111111"
FIXTURE_GAME_ID = 1000000001  # the placeholder game id of both RM-616 fixtures

SALT = b"tft09-synthetic-salt-0123456789ab"
KEYS = [st.player_key(f"SyntheticPlayer{i}", SALT) for i in range(1, 9)]
BOARD = (("DA_18_Yorick", 1, ["TFT_Item_BFSword"]), ("DA_18_Leona", 1, []),
         ("DA_18_Ornn", 1, ["TFT_Item_ChainVest"]), ("DA_18_Rakan", 1, []),
         ("DA_18_Varus", 1, ["TFT_Item_InfinityEdge"]))
OPP_BOARD = (("DA_18_Camille", 1, []), ("DA_18_Kobuko", 1, []), ("DA_18_Xayah", 1, []))
OFFERS = ("DA_18_Yorick", "DA_18_Veigar", "DA_18_Leona", "DA_18_Sentry", "DA_18_Akali_AD")


def _eog_local_board():
    """The local player's final board in the RM-616 EoG fixture, as store
    gt_board rows (built here from the parsed record, not by routes_tft)."""
    rec = tp.parse_eog(EOG_DOC, now=1700002110.0)
    local = next(p for p in rec["players"] if p.get("is_local"))
    return [{"champion_api": u["character_id"], "star": int(u.get("star") or 1),
             "items": [i["name_id"] for i in u.get("items") or [] if i.get("name_id")],
             "cost": u.get("cost")} for u in local["board"] if u.get("character_id")]


# A finished store match and its RM-616 record describe ONE game, so its
# ground-truth board is the record's board (they agree in real data).
GT_BOARD = _eog_local_board()


class _H:
    """Minimal BaseHTTPRequestHandler stand-in (the routes only call _send)."""

    def __init__(self, path):
        self.path = path
        self.status = None
        self.body = None
        self.ctype = None
        self.cache_control = None

    def _send(self, status, body, ctype, cache_control=None):
        self.status, self.body, self.ctype = status, body, ctype
        self.cache_control = cache_control

    def json(self):
        return json.loads(self.body)


def _get(path):
    h = _H(path)
    assert _dispatch.dispatch_get(h) is True, f"no GET route matched {path}"
    return h


def _post(path, body):
    h = _H(path)
    assert _dispatch.dispatch_post(h, body) is True, f"no POST route matched {path}"
    return h


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "tft" / "tft_rounds.db"
    monkeypatch.setattr(rt, "ROUNDS_DB_PATH", db)
    monkeypatch.setattr(rt, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(rt, "FIXTURE_DIR", tmp_path / "fixtures")
    monkeypatch.setattr(tp, "_STORE_DIR", tmp_path / "tft_matches")
    monkeypatch.setattr(tft_scouting, "ARTIFACT_PATH", tmp_path / "tft_scouting.json")
    monkeypatch.setattr(icon_cache, "ROOT", tmp_path / "icons_root")
    # B4 predicate input pinned to tmp (absent = no live game), never the live file
    monkeypatch.setattr(live_game_gate, "HEALTH_PATH", tmp_path / "health.json")
    rt._reset_for_tests()
    yield tmp_path
    rt._reset_for_tests()


def _units(rows, star=2):
    # A placed unit carries its position envelope (the TFT-01 writer's absent
    # rule: a position pairs with a real pos_src, only a null one with absent).
    return [{"zone": "board", "hex_row": 0, "hex_col": i, "champion_api": api, "star": star,
             "items": list(items), "cost": cost, "conf": 1.0, "src": "eog_file",
             "pos_conf": 0.9, "pos_src": "geom"}
            for i, (api, cost, items) in enumerate(rows)]


def _write_match(store, *, match_id, t0, n_rounds, ended, placement=None, game_id=None,
                 round_ts=None, gt_board=None):
    meta = {"match_id": match_id, "set_id": 18, "set_core_name": "TFTSet18",
            "queue_id": 1100, "started_at": t0}
    if game_id is not None:
        meta["game_id"] = game_id
    mid = store.begin_match(meta)
    assert mid == match_id
    for i, k in enumerate(KEYS):
        assert store.upsert_player(mid, k, slot=i + 1, is_local=(i == 0))
    for r in range(1, n_rounds + 1):
        stage, rnd = 2 + (r - 1) // 7, 1 + (r - 1) % 7
        ts = (round_ts if round_ts is not None else t0) + r * 60.0
        assert store.upsert_round(
            mid, r, stage=Env(stage, 1.0, "tft_log"), round=Env(rnd, 0.97, "ocr"),
            label=f"{stage}-{rnd}", planning_ts=ts, combat_ts=ts + 30.0,
            level=Env(min(9, 3 + r), 0.99, "ocr"), gold_start=Env(10 + r, 0.95, "ocr"),
            gold_end=Env(8 + r, 0.9, "ocr"), hp_start=Env(100 - r, 1.0, "eog_file"),
            hp_end=Env(99 - r, 1.0, "eog_file"), verdict=Env("win", 0.9, "derived"),
            opponent_key=Env(KEYS[1], 0.85, "ocr"))
        assert store.put_units(mid, r, "planning_end", KEYS[0], _units(BOARD))
        assert store.put_units(mid, r, "planning_end", KEYS[1], _units(OPP_BOARD))
        offers = [{"slot": s, "kind": "champion", "champion_api": api, "cost": 1,
                   "bought": False, "bought_conf": 0.8, "bought_src": "derived",
                   "conf": 0.92, "src": "ocr"} for s, api in enumerate(OFFERS)]
        assert store.put_shop_refresh(mid, r, 0, cause="round_start", ts=ts + 2.0,
                                      gold_before=10 + r, gold_after=10 + r, conf=0.9,
                                      src="ocr", offers=offers)
        for i, k in enumerate(KEYS):
            assert store.put_player_round(mid, r, k, hp=100 - r * (i + 1), level_badge=3 + r,
                                          alive=True, standing=i + 1, conf=1.0, src="eog_file")
        assert store.record_obs(mid, r, "planning_start", "gold", 10 + r, 0.95, "ocr",
                                ts=ts + 1.0)
    if ended:
        rows = gt_board if gt_board is not None else [
            {"champion_api": api, "star": 2, "items": items, "cost": cost}
            for api, cost, items in BOARD]
        gt = [{"player_key": KEYS[0], **row} for row in rows]
        assert store.attach_ground_truth(mid, "lcu_eog", gt, [], gt_status="partial")
        assert store.end_match(mid, Env(placement, 1.0, "lcu") if placement else None,
                               ended_at=t0 + 1800.0)
    return mid


def _store(env_root, *, open_match=True, fresh=True, finished=2):
    s = RoundStore.open(env_root / "tft" / "tft_rounds.db")
    now = time.time()
    try:
        for i in range(finished):
            _write_match(s, match_id=f"m-done-{i}", t0=now - 86400 * (i + 1), n_rounds=4,
                         ended=True, placement=1 + i, game_id=FIXTURE_GAME_ID if i == 0 else None,
                         gt_board=GT_BOARD)
        if open_match:
            t0 = now - 600.0
            _write_match(s, match_id="m-open", t0=t0, n_rounds=3, ended=False,
                         round_ts=(now - 3 * 60.0 - 40.0) if fresh else t0 - 7200.0)
        assert s.flush()
    finally:
        s.close()


def _rm616(env_root, *, extra_game=False):
    store_dir = env_root / "tft_matches"
    assert tp.persist(tp.parse_eog(EOG_DOC, now=1700002110.0), store_dir=store_dir)
    assert tp.persist(tp.parse_history(HIST_DOC, LOCAL_PUUID)[0], store_dir=store_dir)
    if extra_game:
        doc = copy.deepcopy(EOG_DOC)
        doc["gameId"] = FIXTURE_GAME_ID + 1
        assert tp.persist(tp.parse_eog(doc, now=1700009000.0), store_dir=store_dir)


# ------------------------------------------------------------------ registry


def test_every_tft_route_is_registered_in_the_dispatcher():
    get_paths = ["/api/tft/live", "/api/tft/matches", "/api/tft/matches?limit=3",
                 "/api/tft/match/m-1", "/api/tft/icon/champion/DA_18_Yorick",
                 "/api/tft/scouting", "/api/tft/engine/recommend",
                 "/api/tft/engine/milestones", "/api/tft/engine/planner?set=18"]
    for path in get_paths:
        assert any(m(path) for m, _fn in _dispatch._gather_get()), path
    assert any(m("/api/tft/match/m-1/export") for m, _fn in _dispatch._gather_post())
    # the match matcher never swallows the list route or the export path
    assert not rt._is_match_path("/api/tft/matches")
    assert not rt._is_match_path("/api/tft/match/m-1/export")


# ------------------------------------------------------------------ live


def test_live_serves_the_open_match_latest_round(env):
    _store(env)
    body = _get("/api/tft/live").json()
    assert body["ok"] is True and body["status"] == "live" and body["fresh"] is True
    assert body["store"] == "ok"
    assert body["match"]["id"] == "m-open" and body["match"]["open"] is True
    assert body["local_key"] == KEYS[0]
    rnd = body["round"]
    assert rnd["round_seq"] == 3 and rnd["label"] == "2-3"
    assert "obs" not in rnd and "frames" not in rnd          # raw evidence stays out
    assert [o["champion_api"] for o in rnd["shop"][0]["offers"]] == list(OFFERS)
    assert [r["round_seq"] for r in body["series"]] == [1, 2, 3]
    assert "units" not in body["series"][0] and body["series"][0]["level"] == 4
    opp = body["opponents"]
    assert len(opp) == 8
    hps = [o["hp"] for o in opp]
    assert hps == sorted(hps, reverse=True)                   # by HP, highest first
    me = next(o for o in opp if o["is_local"])
    assert me["hp_series"] == [[1, 99], [2, 98], [3, 97]]
    assert [u["champion_api"] for u in me["last_board"]] == [b[0] for b in BOARD]
    assert me["last_board_round_seq"] == 3
    assert 0 <= body["age_s"] <= rt.LIVE_STALE_AFTER_S


def test_live_marks_an_old_round_stale(env):
    _store(env, fresh=False)
    body = _get("/api/tft/live").json()
    assert body["status"] == "stale" and body["fresh"] is False
    assert body["round"]["round_seq"] == 3


def test_live_is_empty_without_an_open_match_or_a_store(env):
    body = _get("/api/tft/live").json()
    assert body == {**rt._empty_live("no_match", "absent")}
    _store(env, open_match=False)
    rt._reset_for_tests()
    body = _get("/api/tft/live").json()
    assert body["status"] == "no_match" and body["store"] == "ok" and body["round"] is None


def test_a_corrupt_store_reads_empty_never_a_raw_error(env):
    db = env / "tft" / "tft_rounds.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"this is not a sqlite database - C:\\secret\\path " * 20)
    for path in ("/api/tft/live", "/api/tft/matches", "/api/tft/match/m-1"):
        h = _get(path)
        text = h.body.decode("ascii")
        assert "secret" not in text and "Traceback" not in text and "sqlite" not in text.lower()
        assert h.status in (200, 404)
        assert h.json()["store"] == "error"


# ------------------------------------------------------------------ matches


def test_matches_join_the_store_and_the_postgame_records(env):
    _store(env)
    _rm616(env, extra_game=True)
    body = _get("/api/tft/matches").json()
    assert body["ok"] is True and body["store"] == "ok" and body["postgame_store"] == "ok"
    rows = {r["id"]: r for r in body["matches"]}
    assert set(rows) == {"m-open", "m-done-0", "m-done-1", str(FIXTURE_GAME_ID + 1)}
    joined = rows["m-done-0"]
    assert joined["game_id"] == FIXTURE_GAME_ID
    assert joined["sources"] == ["rounds_db", "eog", "history"]
    assert joined["placement"] == 1 and joined["placement_src"] == "lcu"
    only = rows[str(FIXTURE_GAME_ID + 1)]
    assert only["match_id"] is None and only["sources"] == ["eog"]
    assert only["queue_kind"] == "normal" and only["set_id"] == 18
    order = [r["id"] for r in body["matches"]]
    assert order[0] == "m-open"                              # newest first
    assert _get("/api/tft/matches?limit=2").json()["count"] == 2


def test_matches_limit_is_clamped():
    assert rt._clamp_limit(None) == rt.MATCHES_DEFAULT_LIMIT
    assert rt._clamp_limit("0") == 1
    assert rt._clamp_limit("100000") == rt.MATCHES_MAX_LIMIT
    assert rt._clamp_limit("junk") == rt.MATCHES_DEFAULT_LIMIT


# ------------------------------------------------------------------ one match


def test_match_by_store_id_with_postgame_and_raw_toggle(env):
    _store(env)
    _rm616(env)
    body = _get("/api/tft/match/m-done-0").json()
    assert body["ok"] is True and body["found"] is True and body["source"] == "store"
    assert body["match"]["placement"] == 1
    doc = body["rounds_db"]
    assert doc["match"]["match_id"] == "m-done-0" and len(doc["rounds"]) == 4
    assert "obs" not in doc and all("obs" not in r for r in doc["rounds"])
    assert body["postgame"]["game_id"] == FIXTURE_GAME_ID
    assert body["engine"]["status"] in ("warming", "ready", "not_in_catalogue", "no_comp")
    raw = _get("/api/tft/match/m-done-0?raw=1").json()["rounds_db"]
    assert raw["rounds"][0]["obs"][0]["field"] == "gold"
    by_gid = _get(f"/api/tft/match/{FIXTURE_GAME_ID}").json()
    assert by_gid["found"] is True and by_gid["id"] == "m-done-0"


def test_match_known_only_to_the_postgame_store(env):
    _rm616(env, extra_game=True)
    body = _get(f"/api/tft/match/{FIXTURE_GAME_ID + 1}").json()
    assert body["found"] is True and body["rounds_db"] is None
    assert body["store"] == "absent"
    assert body["postgame"]["local_placement"] == 1


def test_unknown_or_malformed_match_id_is_a_clean_404(env):
    _store(env)
    for path in ("/api/tft/match/nope", "/api/tft/match/..%2F..%2Fsecret",
                 "/api/tft/match/%00x"):
        h = _get(path)
        assert h.status == 404
        assert h.json()["found"] is False and h.json()["ok"] is False


# ------------------------------------------------------------------ export + fixture


def test_export_writes_a_scrubbed_fixture_that_the_fixture_route_serves(env):
    _store(env)
    h = _post("/api/tft/match/m-done-1/export", {})
    assert h.status == 200, h.body
    body = h.json()
    assert body["ok"] is True and body["name"] == "tft-m-done-1"
    out = env / "exports" / "tft-m-done-1.json"
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert st.scrub_violations(doc) == []
    assert "SyntheticPlayer" not in out.read_text(encoding="utf-8")
    assert all(k not in out.read_text(encoding="utf-8") for k in KEYS)   # keys -> P1..P8
    served = _get("/api/tft/match/any?fixture=tft-m-done-1").json()
    assert served["source"] == "fixture" and served["found"] is True
    assert served["rounds_db"]["fixture"]["kind"] == "tft_rounds_fixture"
    assert {p["player_key"] for p in served["rounds_db"]["players"]} == {f"P{i}" for i in range(1, 9)}
    named = _post("/api/tft/match/m-done-1/export", {"name": "bug-1234"})
    assert named.json()["name"] == "bug-1234" and (env / "exports" / "bug-1234.json").is_file()


def test_export_refusals_are_clean(env):
    assert _post("/api/tft/match/m-done-0/export", {}).status == 503      # no store
    _store(env)
    assert _post("/api/tft/match/nope/export", {}).status == 404
    bad = _post("/api/tft/match/m-done-0/export", {"name": "../escape"})
    assert bad.status == 400 and bad.json()["error"] == "bad_name"
    assert not (env / "escape.json").exists()


def test_the_default_store_and_export_paths_are_redirected_out_of_the_tree():
    """No `env` fixture here on purpose: tests/conftest.py _PROD_PATH_GLOBALS
    must move the call-time defaults (None = the live data/tft/ store and
    exports) out of the repo for every test, or a route test that forgets
    `env` reads the live store and writes the live export dir. Resolved
    through the route's own helpers, so a deleted conftest row (None again)
    fails here instead of passing as 'not a repo path'."""
    for resolved in (rt._exports_dir(), rt._rounds_db_path()):
        assert not resolved.resolve().is_relative_to(REPO), resolved


def test_a_scrub_refusal_is_a_fixed_422_derived_from_no_exception(env, monkeypatch, caplog):
    """RM-835 rule: no :8888 reply is derived from an except-bound exception.
    A scrub refusal replies a FIXED 422 (two different violation lists give
    the same reply), names no violation path, writes nothing, and the detail
    (type name + the store's own value-free violation text) goes to the log."""
    _store(env)

    def refuse(violations):
        def _export(self, *_a, **_kw):
            raise st.ScrubError(violations)
        return _export

    replies = []
    for n, marker in ((1, "$.RM835SCRUBA.players[0]: identity key"),
                      (3, "$.RM835SCRUBB[1]: a raw 12-hex player key")):
        monkeypatch.setattr(RoundStore, "export_fixture",
                            refuse([f"{marker} {i}" for i in range(n)]))
        with caplog.at_level("WARNING", logger="rc.web_dashboard"):
            h = _post("/api/tft/match/m-done-1/export", {})
        assert h.status == 422, h.body
        assert "RM835SCRUB" not in h.body.decode("ascii")
        replies.append(h.json())
    assert replies[0] == replies[1] == {"ok": False, "error": "scrub_failed"}
    assert not (env / "exports" / "tft-m-done-1.json").exists()
    logged = [r.getMessage() for r in caplog.records if "scrub guard" in r.getMessage()]
    assert any("ScrubError" in m and "RM835SCRUBA" in m for m in logged), logged


def test_an_unscrubbed_fixture_is_never_served(env):
    fdir = env / "fixtures"
    fdir.mkdir()
    planted = {"fixture": {"kind": "tft_rounds_fixture", "schema_version": 1},
               "match": {"match_id": "planted"}, "players": [{"puuid": "x" * 36}]}
    (fdir / "planted.json").write_text(json.dumps(planted), encoding="utf-8")
    h = _get("/api/tft/match/planted?fixture=planted")
    assert h.status == 404 and h.json()["error"] == "fixture_not_found"
    assert _get("/api/tft/match/x?fixture=..%2Fsecret").status == 404


# ------------------------------------------------------------------ icons


def _icon_cache(env_root, data=b"\x89PNG\r\n\x1a\n" + b"synthetic"):
    base = env_root / "icons_root" / "data" / "tft" / "icon_cache" / "18"
    (base / "champion").mkdir(parents=True)
    (base / "champion" / "DA_18_Yorick.png").write_bytes(data)
    index = {"schema": icon_cache.INDEX_SCHEMA,
             "entries": {"champion": {"DA_18_Yorick": {"file": "champion/DA_18_Yorick.png",
                                                       "sha256": "0" * 64}}}}
    (base / icon_cache.INDEX_NAME).write_text(json.dumps(index), encoding="ascii")
    return data


def test_icon_served_from_the_cache_and_404_when_not_cached(env):
    data = _icon_cache(env)
    h = _get("/api/tft/icon/champion/DA_18_Yorick?set=18")
    assert h.status == 200 and h.body == data and h.ctype == "image/png"
    assert h.cache_control == rt.ICON_CACHE_CONTROL
    for path in ("/api/tft/icon/champion/DA_18_Leona?set=18",       # not in the index
                 "/api/tft/icon/champion/DA_18_Yorick?set=17",      # no cache for the set
                 "/api/tft/icon/emote/DA_18_Yorick?set=18",         # not a category
                 "/api/tft/icon/champion/..%2F..%2Findex.json?set=18"):
        miss = _get(path)
        assert miss.status == 404 and miss.json() == {"ok": False, "error": "not_cached"}


def test_icon_type_comes_from_the_bytes_and_non_images_are_never_served(env):
    _icon_cache(env, data=b"\xff\xd8\xff\xe0" + b"synthetic-jpeg")   # JPEG magic, .png name
    h = _get("/api/tft/icon/champion/DA_18_Yorick?set=18")
    assert h.status == 200 and h.ctype == "image/jpeg"
    rt._reset_for_tests()
    page = env / "icons_root" / "data" / "tft" / "icon_cache" / "18" / "champion" / "DA_18_Yorick.png"
    page.write_bytes(b"<html>error page C:\\secret</html>")
    miss = _get("/api/tft/icon/champion/DA_18_Yorick?set=18")
    assert miss.status == 404 and miss.json() == {"ok": False, "error": "not_cached"}


# ------------------------------------------------------------------ scouting


def test_scouting_digest_passthrough_and_fail_soft(env):
    assert _get("/api/tft/scouting").json() == {"ok": True, "available": False,
                                                 "age_s": None, "scouting": None}
    doc = {"schema": tft_scouting.SCHEMA, "status": "ready", "game_id": "1",
           "updated_at": time.time() - 5.0, "opponents": [{"slot": 2, "status": "ready"}]}
    tft_scouting.ARTIFACT_PATH.write_text(json.dumps(doc), encoding="ascii")
    body = _get("/api/tft/scouting").json()
    assert body["available"] is True and body["scouting"]["opponents"][0]["slot"] == 2
    assert 4.0 <= body["age_s"] < 60.0
    tft_scouting.ARTIFACT_PATH.write_text(json.dumps({**doc, "schema": "other"}), encoding="ascii")
    assert _get("/api/tft/scouting").json()["available"] is False
    tft_scouting.ARTIFACT_PATH.write_text("{not json", encoding="ascii")
    h = _get("/api/tft/scouting")
    assert h.status == 200 and h.json()["available"] is False


# ------------------------------------------------------------------ engine


def test_engine_routes_warm_then_serve_milestones_planner_and_recommend(env):
    _store(env)
    _rm616(env)
    first = _get("/api/tft/engine/milestones?set=18").json()
    assert first["status"] == "warming" and first["milestones"] is None
    assert first["engine"] == tft_engine.ENGINE_NAME
    rt._engine_join()
    ms = _get("/api/tft/engine/milestones?set=18").json()
    assert ms["status"] == "ready" and ms["set_id"] == 18
    assert ms["catalogue"] and ms["catalogue"][0]["top4_games"] >= 2
    comp_id = ms["catalogue"][0]["comp_id"]
    assert comp_id in ms["milestones"]["comps"]
    planner = _get("/api/tft/engine/planner?set=18").json()
    assert planner["status"] == "ready" and planner["live_status"] == "live"
    choice = planner["planner"]["choices"][0]
    assert choice["comp_id"] == comp_id and choice["digest"]
    assert choice["contest"] is not None                     # live lobby boards counted
    # B4 (RM-189): a fresh captured round means a game is running, so the
    # live-state recommendation (shop / slam / level advice) is withheld.
    rec = _get(f"/api/tft/engine/recommend?set=18&comp={comp_id}").json()
    assert rec["status"] == "ready" and rec["live_status"] == "live"
    assert rec["recommendation"] is None and rec["suppressed"] == "live_game"
    digest = _get("/api/tft/match/m-done-0").json()["engine"]
    assert digest["status"] == "ready" and digest["comp"]["comp_id"] == comp_id
    assert isinstance(digest["milestones"], list)


def test_engine_record_board_prefers_the_postgame_record_then_store_ground_truth(env):
    """Same precedence as tft/engine/milestones.records_from_store: an external
    final board (the LCU post-game record) wins over the store's gt_board rows;
    without one the store's own ground truth is the board."""
    s = RoundStore.open(env / "tft" / "tft_rounds.db")
    try:
        _write_match(s, match_id="m-x", t0=time.time() - 3600.0, n_rounds=2, ended=True,
                     placement=3, game_id=FIXTURE_GAME_ID)       # gt board = BOARD
        assert s.flush()
    finally:
        s.close()
    _rm616(env)
    store, status = rt._open_store()
    assert status == "ok"
    doc = store.get_match("m-x")
    rec = rt._rm616_load(FIXTURE_GAME_ID)
    with_rec = rt._store_record(doc, rec)
    assert [u["champion_api"] for u in with_rec["final_board"]] == \
        [u["champion_api"] for u in GT_BOARD]
    alone = rt._store_record(doc, None)
    assert [u["champion_api"] for u in alone["final_board"]] == [b[0] for b in BOARD]
    assert alone["placement"] == 3 and with_rec["placement"] == 3


def _ready_engine(env_root, *, fresh):
    _store(env_root, fresh=fresh)
    _rm616(env_root)
    _get("/api/tft/engine/milestones?set=18")
    rt._engine_join()
    ms = _get("/api/tft/engine/milestones?set=18").json()
    assert ms["status"] == "ready"
    return ms["catalogue"][0]["comp_id"]


def test_engine_recommend_answers_on_the_last_round_when_no_game_is_live(env):
    comp_id = _ready_engine(env, fresh=False)
    rec = _get(f"/api/tft/engine/recommend?set=18&comp={comp_id}").json()
    assert rec["status"] == "ready" and rec["live_status"] == "stale"
    assert rec["suppressed"] is None
    r = rec["recommendation"]
    assert r["target"]["comp_id"] == comp_id and r["engine"] == tft_engine.ENGINE_NAME
    assert set(r) >= {"target", "alternatives", "shop", "items", "level"}


@pytest.mark.parametrize("flag", ["tft_mode", "has_game"])
def test_engine_recommend_is_withheld_while_the_b4_gate_says_live(env, flag):
    comp_id = _ready_engine(env, fresh=False)
    (env / "health.json").write_text(json.dumps({flag: True}), encoding="ascii")
    rec = _get(f"/api/tft/engine/recommend?set=18&comp={comp_id}").json()
    assert rec["ok"] is True and rec["status"] == "ready"
    assert rec["recommendation"] is None and rec["suppressed"] == "live_game"
    # the operator-ordered in-game picker and own-history milestones still serve
    assert _get("/api/tft/engine/planner?set=18").json()["planner"]["choices"]
    assert _get("/api/tft/engine/milestones?set=18").json()["milestones"]


def test_engine_without_history_or_live_round(env):
    _get("/api/tft/engine/recommend?set=18")
    rt._engine_join()
    body = _get("/api/tft/engine/recommend?set=18").json()
    assert body["status"] == "no_history" and body["recommendation"] is None
    assert body["live_status"] == "no_match"


def test_engine_build_never_runs_on_the_request_thread(env, monkeypatch):
    gate = threading.Event()
    seen = {}

    def slow_build(n, key=None):
        seen["thread"] = threading.current_thread().name
        gate.wait(10.0)
        raise RuntimeError("build failed on purpose - C:\\secret")

    monkeypatch.setattr(rt, "build_engine_model", slow_build)
    t0 = time.monotonic()
    for path in ("/api/tft/engine/recommend", "/api/tft/engine/milestones",
                 "/api/tft/engine/planner"):
        body = _get(path).json()
        assert body["status"] == "warming"
    assert time.monotonic() - t0 < 2.0                        # nothing waited on the build
    gate.set()
    rt._engine_join()
    assert seen["thread"] == "tft-engine-refresh"
    body = _get("/api/tft/engine/milestones").json()          # a failed build stays warming
    assert body["status"] == "warming" and "secret" not in json.dumps(body)


# ------------------------------------------------------------------ cross-cutting


def test_no_route_opens_a_network_connection(env, monkeypatch):
    _store(env)
    _rm616(env)
    _icon_cache(env)

    def refuse(*_a, **_kw):
        raise AssertionError("network call on the request path")

    # this_thread_only, not a process-wide fake (RM-801 guard): a leftover
    # server thread of an earlier file keeps the real function. connect is a
    # CLASS attribute every socket instance shares (s135 C1: it was faked
    # process-wide here).
    monkeypatch.setattr(socket.socket, "connect",
                        this_thread_only(refuse, socket.socket.connect))
    monkeypatch.setattr(socket, "create_connection",
                        this_thread_only(refuse, socket.create_connection))
    paths = ["/api/tft/live", "/api/tft/matches", "/api/tft/match/m-done-0",
             f"/api/tft/match/{FIXTURE_GAME_ID}", "/api/tft/icon/champion/DA_18_Yorick?set=18",
             "/api/tft/scouting", "/api/tft/engine/recommend", "/api/tft/engine/milestones",
             "/api/tft/engine/planner"]
    for path in paths:
        assert _get(path).status == 200, path
    rt._engine_join()
    for path in paths[-3:]:
        assert _get(path).status == 200, path


def test_an_unexpected_failure_is_a_fixed_500_message(env, monkeypatch):
    def boom(*_a, **_kw):
        raise RuntimeError("raw upstream text C:\\Users\\secret 400 credit")

    monkeypatch.setattr(rt, "build_matches", boom)
    monkeypatch.setattr(rt, "build_live", boom)
    monkeypatch.setattr(rt, "export_match", boom)
    for h in (_get("/api/tft/matches"), _get("/api/tft/live"),
              _post("/api/tft/match/m-1/export", {})):
        assert h.status == 500 and h.json() == rt.INTERNAL_ERROR
        assert "secret" not in h.body.decode("ascii")


def test_responses_are_ascii_json(env):
    _store(env)
    _rm616(env)
    for path in ("/api/tft/live", "/api/tft/matches", "/api/tft/match/m-done-0"):
        h = _get(path)
        assert h.ctype == "application/json"
        h.body.decode("ascii")
