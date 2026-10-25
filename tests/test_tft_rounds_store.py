"""TFT-01 (docs/TFT_PROGRAM.md section 7): the per-round TFT store.

Acceptance, slice row TFT-01: schema v1 creates every section 1.5 table; a
synthetic 30-round match round-trips through the writer / read API; the
scrubbed fixture export passes the no-identity guard; `data/tft/` is ignored
(`git check-ignore`). Section 2 adds: WAL + one writer thread fed by a bounded
queue (the TFT poll thread never blocks on disk), fail-soft writes (an error
logs once per streak and drops the row, never raises), forward-only migrations
keyed on `schema_meta.schema_version`, and "target under 2 MB per match;
TFT-01 measures it".

Every API used here is the new `tft/rounds` package (no existing RC API is
called). The only repo data cited is the Set 18 unit / trait / augment api
names below, copied from tracked `data/meta/tft_set18_cdragon.json`
(`units[].apiName`, `traits[].apiName`, `augments[]`); the store never reads
that file, so this test does not either. The synthetic players are named
`SyntheticPlayer<i>#SYN<i>` ONLY to derive their player keys - those names
must never reach the store or a fixture (section 1.2).
"""
from __future__ import annotations

import ast
import json
import logging
import random
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tft.rounds import schema as rs
from tft.rounds import store as st
from tft.rounds.store import Env, RoundStore

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "tft" / "rounds"

SET18_UNITS = (  # data/meta/tft_set18_cdragon.json units[].apiName (cost)
    ("DA_18_Akali_AD", 1), ("DA_18_Camille", 1), ("DA_Cinderling18", 1),
    ("DA_Karma18", 1), ("DA_18_Kobuko", 1), ("DA_18_Leona", 1),
    ("DA_18_Ornn", 1), ("DA_18_Sentry", 1), ("DA_18_Rakan", 1),
    ("DA_18_RekSai", 1), ("DA_18_Varus", 1), ("DA_18_Veigar", 1),
    ("DA_18_Xayah", 1), ("DA_18_Yorick", 1),
)
SET18_TRAITS = ("DA_18_Adaptor", "DA_18_Blackthorn", "DA_18_Blossom",
                "DA_18_Brawler", "DA_18_Caustic", "DA_18_Coven")
SET18_AUGMENTS = ("DA_18_BigGrabBag", "DA_18_BlossomTraitAugment",
                  "DA_18_BranchingOut", "DA_18_CaretakersAlly",
                  "DA_18_CovenTraitAugment")
ITEMS = ("TFT_Item_BFSword", "TFT_Item_ChainVest", "TFT_Item_NeedlesslyLargeRod",
         "TFT_Item_InfinityEdge", "TFT_Item_GuinsoosRageblade")

SALT = b"tft01-synthetic-salt-0123456789ab"
# a synthetic random base64url token the shape of an encrypted summoner id (47 chars)
ENCRYPTED_47 = "".join(random.Random(47).choice(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_") for _ in range(47))
NAMES = tuple(f"SyntheticPlayer{i}#SYN{i}" for i in range(1, 9))
GAME_ID = 5550001234
T0 = 1_761_000_000.0

# docs/TFT_PROGRAM.md section 1.1 - the closed src enum, transcribed.
SPEC_SRC = {"eog_file", "tft_log", "lcu", "riot_match_v1", "ocr", "icon", "geom",
            "derived", "llm_fallback", "manual_label", "absent"}


def _cs(*names):
    return [c for n in names for c in (n, n + "_conf", n + "_src")]


# docs/TFT_PROGRAM.md section 1.5 - the table contract, transcribed by hand
# (NOT derived from tft/rounds/schema.py, so the two are compared, not echoed).
SPEC_COLUMNS = {
    "schema_meta": ["key", "value"],
    "match": ["match_id", "game_id", "set_id", "set_core_name", "queue_id",
              "queue_kind", "started_at", "ended_at", *_cs("placement"),
              "capture_profile", "extractor_version", "rc_commit", "gt_status",
              "gt_sources"],
    "player": ["match_id", "player_key", "slot", "is_local", *_cs("final_standing"),
               "eliminated_round_seq"],
    "round": ["match_id", "round_seq", *_cs("stage", "round"), "label", *_cs("kind"),
              "planning_ts", "combat_ts", "end_ts",
              *_cs("gold_start", "gold_end", "level", "xp_cur", "xp_max", "hp_start",
                   "hp_end", "streak", "verdict", "damage_taken", "damage_dealt",
                   "opponent_key", "opponent_is_ghost")],
    "unit_obs": ["id", "match_id", "round_seq", "phase", "player_key", "zone",
                 "hex_row", "hex_col", "bench_idx", "champion_api", "star",
                 "items_json", "cost", "conf", "src", "pos_conf", "pos_src",
                 "frame_id"],
    "shop_refresh": ["match_id", "round_seq", "refresh_idx", "cause", "ts",
                     "gold_before", "gold_after", "conf", "src"],
    "shop_offer": ["match_id", "round_seq", "refresh_idx", "slot", "kind",
                   "champion_api", "name_text", "cost", "bought", "bought_conf",
                   "bought_src", "conf", "src"],
    "shop_odds": ["match_id", "round_seq", "level", "p1", "p2", "p3", "p4", "p5",
                  "conf", "src"],
    "trait_state": ["match_id", "round_seq", "phase", "player_key", "trait_api",
                    "count", "tier_index", "active", "conf", "src"],
    "augment": ["match_id", "round_seq", "pick_idx", "offered_json", "chosen_api",
                "conf", "src"],
    "player_round": ["match_id", "round_seq", "player_key", "hp", "level_badge",
                     "alive", "standing", "conf", "src"],
    "event": ["id", "match_id", "ts", "round_seq", "kind", "payload_json", "src"],
    "frame": ["frame_id", "match_id", "round_seq", "phase", "ts", "relpath",
              "sha256", "width", "height", "kept_reason"],
    "obs": ["id", "match_id", "round_seq", "phase", "field", "value_json", "conf",
            "src", "extractor_version", "frame_id", "ts"],
    "gt_board": ["match_id", "player_key", "source", "champion_api", "star",
                 "items_json", "cost"],
    "gt_player": ["match_id", "player_key", "placement", "level", "last_round",
                  "gold_left", "damage_to_players", "eliminated_at"],
    "accuracy": ["match_id", "field", "n", "correct", "coverage",
                 "extractor_version", "computed_at"],
}
SPEC_PKS = {
    "schema_meta": ["key"], "match": ["match_id"], "player": ["match_id", "player_key"],
    "round": ["match_id", "round_seq"], "unit_obs": ["id"],
    "shop_refresh": ["match_id", "round_seq", "refresh_idx"], "event": ["id"],
    "frame": ["frame_id"], "obs": ["id"],
}


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "tft" / "tft_rounds.db"


@pytest.fixture
def store(db_path):
    s = RoundStore.open(db_path)
    try:
        yield s
    finally:
        s.close()


def _raw(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _scalar(path, sql):
    conn = _raw(path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def _exec(path, sql, params=()):
    conn = _raw(path)
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- synthetic match


def _keys():
    return [st.player_key(n, SALT) for n in NAMES]


def _plan(rounds=30, seed=134):
    """A dense, deterministic match: all 8 boards at planning start / end, the
    opponent board at combat, the local bench, 3 shop refreshes of 5 offers,
    odds, traits, augments, all-8 HP, events, frames and 40 raw obs a round -
    denser than one real capture, so the size measurement is an upper bound."""
    rng = random.Random(seed)
    keys = _keys()
    plan = {"keys": keys, "rounds": []}
    hp = {k: 100 for k in keys}
    for r in range(1, rounds + 1):
        stage, rnd = 1 + (r - 1) // 7, 1 + (r - 1) % 7
        kind = "carousel" if rnd == 4 else ("pve" if stage == 1 else "pvp")
        opp = keys[1 + r % 7]
        lost = rng.random() < 0.5
        dmg_taken = rng.randint(2, 14) if lost and kind == "pvp" else 0
        hp_start = hp[keys[0]]
        hp[keys[0]] = hp_start - dmg_taken
        for k in keys[1:]:
            hp[k] -= rng.randint(0, 9)
        level = min(9, 2 + r // 4)
        env = {
            "stage": Env(stage, 1.0, "tft_log"), "round": Env(rnd, 0.97, "ocr"),
            "kind": (Env(kind, 1.0, "tft_log") if kind == "carousel"
                     else Env("unknown", 0.3, "derived")),
            "gold_start": Env(rng.randint(0, 60), 0.95, "ocr"),
            "gold_end": Env(rng.randint(0, 60), 0.9, "ocr"),
            "level": Env(level, 0.99, "ocr"),
            "xp_cur": Env(rng.randint(0, 30), 0.8, "ocr"),
            # every 5th round the XP bar is occluded: absent, never 0
            "xp_max": None if r % 5 == 0 else Env(36, 0.8, "ocr"),
            "hp_start": Env(hp_start, 1.0, "eog_file"),
            "hp_end": Env(hp[keys[0]], 1.0, "eog_file"),
            "streak": Env(rng.randint(-5, 5), 0.7, "ocr"),
            "verdict": Env("loss" if lost else "win", 0.9, "derived"),
            "damage_taken": Env(dmg_taken, 0.9, "derived"),
            "damage_dealt": Env(0 if lost else rng.randint(2, 12), 0.9, "derived"),
            "opponent_key": Env(opp, 0.85, "ocr"),
            "opponent_is_ghost": Env(r % 9 == 0, 0.85, "ocr"),
        }
        plain = {"label": f"{stage}-{rnd}", "planning_ts": T0 + r * 60.0,
                 "combat_ts": T0 + r * 60.0 + 30.0, "end_ts": T0 + r * 60.0 + 55.0}
        units = {}
        n_board = min(9, 2 + r // 3)
        for phase in ("planning_start", "planning_end"):
            for k in keys:
                hexes = rng.sample([(row, col) for row in range(4) for col in range(7)],
                                   n_board)
                rows = []
                for row, col in hexes:
                    api, cost = rng.choice(SET18_UNITS)
                    rows.append({"zone": "board", "hex_row": row, "hex_col": col,
                                 "bench_idx": None, "champion_api": api,
                                 "star": rng.randint(1, 3),
                                 "items": rng.sample(ITEMS, rng.randint(0, 3)),
                                 "cost": cost, "conf": 1.0, "src": "eog_file",
                                 "pos_conf": 0.8, "pos_src": "geom", "frame_id": None})
                if k == keys[0] and phase == "planning_start":
                    for b in range(3):
                        api, cost = rng.choice(SET18_UNITS)
                        rows.append({"zone": "bench", "hex_row": None, "hex_col": None,
                                     "bench_idx": b, "champion_api": api, "star": 1,
                                     "items": [], "cost": cost, "conf": 0.7, "src": "icon",
                                     "pos_conf": 0.9, "pos_src": "geom",
                                     "frame_id": f"f{r:02d}a"})
                units[(phase, k)] = rows
        units[("combat", opp)] = [dict(u) for u in units[("planning_end", opp)]]
        shop = []
        for idx in range(3):
            offers = []
            for slot in range(5):
                api, cost = rng.choice(SET18_UNITS)
                offers.append({"slot": slot, "kind": "champion", "champion_api": api,
                               "name_text": api.split("_")[-1], "cost": cost,
                               "bought": idx == 0 and slot == 0,
                               "bought_conf": 0.6, "bought_src": "derived",
                               "conf": 0.92, "src": "ocr"})
            shop.append({"refresh_idx": idx,
                         "cause": "round_start" if idx == 0 else "reroll",
                         "ts": T0 + r * 60.0 + 2 + idx, "gold_before": 30 - 2 * idx,
                         "gold_after": 28 - 2 * idx, "conf": 0.9, "src": "ocr",
                         "offers": offers})
        odds = {"level": level, "odds": (19, 30, 35, 15, 1), "conf": 0.95, "src": "ocr"}
        traits = {}
        for k in keys:
            traits[k] = [{"trait_api": t, "count": rng.randint(1, 6),
                          "tier_index": rng.randint(0, 3), "active": rng.random() < 0.6,
                          "conf": 0.9, "src": "derived"}
                         for t in rng.sample(SET18_TRAITS, 4)]
        augments = []
        if r in (5, 12, 19):
            offered = rng.sample(SET18_AUGMENTS, 3)
            augments.append({"pick_idx": (5, 12, 19).index(r), "offered": offered,
                             "chosen_api": offered[1], "conf": 0.88, "src": "icon"})
        players = [{"player_key": k, "hp": hp[k], "level_badge": level,
                    "alive": hp[k] > 0, "standing": i + 1, "conf": 1.0, "src": "eog_file"}
                   for i, k in enumerate(keys)]
        events = [{"kind": "phase", "ts": T0 + r * 60.0, "src": "tft_log",
                   "payload": {"phase": "PlanningDeparture"}},
                  {"kind": "eog_rewrite", "ts": T0 + r * 60.0 + 0.5, "src": "eog_file",
                   "payload": {"players": 8}}]
        if r % 10 == 0:
            events.append({"kind": "capture_skip", "ts": T0 + r * 60.0 + 1.0,
                           "src": "derived", "payload": {"reason": "not_foreground"}})
        frames = [{"frame_id": f"f{r:02d}{tag}", "phase": phase,
                   "ts": T0 + r * 60.0 + off, "relpath": f"m1/r{r:02d}_{phase}.jpg",
                   "sha256": f"{r:02d}{tag}" + "0" * 61, "width": 2560, "height": 1440,
                   "kept_reason": "low_confidence" if r == 7 else None}
                  for tag, phase, off in (("a", "planning_start", 1.5),
                                          ("b", "planning_end", 54.0))]
        obs = []
        for i in range(40):
            obs.append({"phase": "planning_start", "field": f"field_{i % 20}",
                        "value": rng.randint(0, 99) if i % 3 else [rng.randint(0, 9), "x"],
                        "conf": round(rng.random(), 3), "src": "ocr" if i % 2 else "icon",
                        "frame_id": f"f{r:02d}a", "ts": T0 + r * 60.0 + 1.5,
                        "extractor_version": "tft-cv-0"})
        plan["rounds"].append({"round_seq": r, "env": env, "plain": plain, "units": units,
                               "shop": shop, "odds": odds, "traits": traits,
                               "augments": augments, "players": players,
                               "events": events, "frames": frames, "obs": obs})
    plan["gt_boards"] = [{"player_key": k, "champion_api": SET18_UNITS[i][0], "star": 2,
                          "items": [ITEMS[i % 5]], "cost": SET18_UNITS[i][1]}
                         for k in keys for i in range(8)]
    plan["gt_players"] = [{"player_key": k, "placement": i + 1, "level": 8,
                           "last_round": 30 - i, "gold_left": i, "damage_to_players": 0,
                           "eliminated_at": None if i == 0 else 1800.0 - 60 * i}
                          for i, k in enumerate(keys)]
    return plan


def _write(store, plan, *, match_id=None):
    meta = {"game_id": GAME_ID, "set_id": 18, "set_core_name": "TFTSet18",
            "queue_id": 1090, "started_at": T0, "capture_profile": "2560x1440@ui1",
            "extractor_version": "tft-cv-0", "rc_commit": "0000000"}
    if match_id:
        meta["match_id"] = match_id
    mid = store.begin_match(meta)
    keys = plan["keys"]
    for i, k in enumerate(keys):
        assert store.upsert_player(mid, k, slot=i + 1, is_local=(i == 0))
    for rd in plan["rounds"]:
        r = rd["round_seq"]
        assert store.upsert_round(mid, r, **rd["env"], **rd["plain"])
        for (phase, k), rows in rd["units"].items():
            assert store.put_units(mid, r, phase, k, rows)
        for ref in rd["shop"]:
            assert store.put_shop_refresh(mid, r, ref["refresh_idx"], cause=ref["cause"],
                                          ts=ref["ts"], gold_before=ref["gold_before"],
                                          gold_after=ref["gold_after"], conf=ref["conf"],
                                          src=ref["src"], offers=ref["offers"])
        o = rd["odds"]
        assert store.put_shop_odds(mid, r, o["level"], o["odds"], conf=o["conf"],
                                   src=o["src"])
        for k, rows in rd["traits"].items():
            assert store.put_traits(mid, r, "planning_start", k, rows)
        for a in rd["augments"]:
            assert store.put_augment(mid, r, a["pick_idx"], a["offered"], a["chosen_api"],
                                     conf=a["conf"], src=a["src"])
        for p in rd["players"]:
            assert store.put_player_round(mid, r, p["player_key"], hp=p["hp"],
                                          level_badge=p["level_badge"], alive=p["alive"],
                                          standing=p["standing"], conf=p["conf"],
                                          src=p["src"])
        for e in rd["events"]:
            assert store.put_event(mid, e["kind"], e["payload"], ts=e["ts"], round_seq=r,
                                   src=e["src"])
        for f in rd["frames"]:
            assert store.put_frame(mid, r, f["phase"], f["relpath"], ts=f["ts"],
                                   sha256=f["sha256"], width=f["width"],
                                   height=f["height"], kept_reason=f["kept_reason"],
                                   frame_id=f["frame_id"]) == f["frame_id"]
        for ob in rd["obs"]:
            assert store.record_obs(mid, r, ob["phase"], ob["field"], ob["value"],
                                    ob["conf"], ob["src"], ob["frame_id"], ts=ob["ts"],
                                    extractor_version=ob["extractor_version"])
    assert store.put_event(mid, "planner_saved", {"count": 1}, ts=T0 + 5.0, src="tft_log")
    for i, k in enumerate(keys):
        assert store.upsert_player(mid, k, final_standing=Env(i + 1, 1.0, "lcu"),
                                   eliminated_round_seq=None if i == 0 else 30 - i)
    assert store.attach_ground_truth(mid, "lcu_eog", plan["gt_boards"], plan["gt_players"],
                                     gt_status="full")
    assert store.put_accuracy(mid, [{"field": "gold_start", "n": 30, "correct": 29,
                                     "coverage": 0.97, "extractor_version": "tft-cv-0",
                                     "computed_at": T0 + 2000.0}])
    return mid


def _proj(rows, keys):
    return [{k: r[k] for k in keys} for r in rows]


def _ints(rows, *names):
    return [{**r, **{n: int(r[n]) for n in names}} for r in rows]


UNIT_KEYS = ("zone", "hex_row", "hex_col", "bench_idx", "champion_api", "star", "items",
             "cost", "conf", "src", "pos_conf", "pos_src", "frame_id")
SHOP_KEYS = ("refresh_idx", "cause", "ts", "gold_before", "gold_after", "conf", "src")
OFFER_KEYS = ("slot", "kind", "champion_api", "name_text", "cost", "bought",
              "bought_conf", "bought_src", "conf", "src")
TRAIT_KEYS = ("trait_api", "count", "tier_index", "active", "conf", "src")
PR_KEYS = ("player_key", "hp", "level_badge", "alive", "standing", "conf", "src")
FRAME_KEYS = ("frame_id", "phase", "ts", "relpath", "sha256", "width", "height",
              "kept_reason")
OBS_KEYS = ("phase", "field", "value", "conf", "src", "frame_id", "ts", "extractor_version")


# ---------------------------------------------------------------- schema


def test_schema_v1_creates_every_section_1_5_table(store, db_path):
    assert store.ok and store.flush()
    conn = _raw(db_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'")}
        assert tables == set(SPEC_COLUMNS)
        for table, cols in SPEC_COLUMNS.items():
            info = conn.execute(f"PRAGMA table_info({table})").fetchall()
            assert [r["name"] for r in info] == cols, table
            pk = [r["name"] for r in sorted(info, key=lambda r: r["pk"]) if r["pk"]]
            if table in SPEC_PKS:
                assert pk == SPEC_PKS[table], table
        meta = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
        assert meta["schema_version"] == "1" == str(rs.SCHEMA_VERSION)
        assert float(meta["created_at"]) > 0
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_src_enum_is_the_closed_section_1_1_set(store):
    assert set(rs.SRC_VALUES) == SPEC_SRC
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    assert not store.upsert_round(mid, 1, gold_start=Env(10, 1.0, "guess"))
    assert not store.put_event(mid, "phase", {}, src="vision")
    assert store.stats()["invalid"] == 2
    assert store.upsert_round(mid, 1, gold_start=Env(10, 1.0, "ocr"))


def test_absent_is_null_never_zero(store):
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    assert store.upsert_round(mid, 1, gold_start=None, level=Env(3, 0.9, "ocr"))
    # a value claimed absent, or a measured value without a valid conf, is refused
    assert not store.upsert_round(mid, 1, gold_end=Env(0, None, "absent"))
    assert not store.upsert_round(mid, 1, gold_end=Env(5, None, "ocr"))
    assert not store.upsert_round(mid, 1, gold_end=Env(5, 1.2, "ocr"))
    assert not store.upsert_round(mid, 1, gold_end=Env(5, 0.9, "llm_fallback"))  # cap 0.5
    assert store.upsert_round(mid, 1, gold_end=Env(5, 0.5, "llm_fallback"))
    assert store.flush()
    (rd,) = list(store.iter_rounds(mid))
    assert (rd["gold_start"], rd["gold_start_conf"], rd["gold_start_src"]) == \
        (None, None, "absent")
    assert (rd["level"], rd["level_conf"], rd["level_src"]) == (3, 0.9, "ocr")
    # never-written envelopes default to absent too
    assert (rd["hp_end"], rd["hp_end_conf"], rd["hp_end_src"]) == (None, None, "absent")


def test_rows_obey_the_absent_rule_too(store):
    """A stored row is an observation (its src is never 'absent'); a row's
    optional sub-envelopes (position, bought) pair null with absent, only."""
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    k = _keys()[0]
    assert not store.put_player_round(mid, 1, k, hp=50, conf=None, src="absent")
    unit = {"zone": "board", "champion_api": "DA_18_Yorick", "star": 1, "conf": 1.0,
            "src": "eog_file"}
    assert not store.put_units(mid, 1, "planning_start", k, [{**unit, "hex_row": 1,
                                                              "hex_col": 2}])  # pos absent
    assert not store.put_units(mid, 1, "planning_start", k, [{**unit, "pos_conf": 0.9,
                                                              "pos_src": "geom"}])  # no pos
    offer = {"slot": 0, "kind": "champion", "champion_api": "DA_18_Yorick", "cost": 1,
             "conf": 0.9, "src": "ocr"}
    assert not store.put_shop_refresh(mid, 1, 0, cause="round_start", conf=0.9, src="ocr",
                                      offers=[{**offer, "bought": True}])  # bought absent
    assert not store.put_shop_odds(mid, 1, 3, (75, 25, 0, 0, 0), conf=None, src="absent")
    assert store.stats()["invalid"] == 5
    assert store.put_units(mid, 1, "planning_start", k, [unit])  # no position, absent: fine
    assert store.put_shop_refresh(mid, 1, 0, cause="round_start", conf=0.9, src="ocr",
                                  offers=[offer])  # bought unknown, absent: fine


def test_queue_kind_comes_from_the_queue_id():
    assert rs.queue_kind_for(1090) == "normal"
    assert rs.queue_kind_for(1100) == "ranked"
    assert rs.queue_kind_for(1130) == "hyper_roll"
    assert rs.queue_kind_for(1160) == "double_up"
    for q in (6110, 1220, 1230, None, 0):
        assert rs.queue_kind_for(q) == "other"


# ---------------------------------------------------------------- round trip


def test_synthetic_30_round_match_round_trips(store):
    plan = _plan()
    mid = _write(store, plan)
    assert store.flush()
    live = store.live_round()  # open match: its latest round
    assert (live["match_id"], live["round_seq"]) == (mid, 30)
    assert store.end_match(mid, Env(1, 1.0, "lcu"), ended_at=T0 + 1900.0)
    assert store.flush()
    stats = store.stats()
    assert stats["invalid"] == stats["queue_full"] == stats["write_errors"] == 0
    assert stats["written"] == stats["enqueued"] > 0
    assert store.live_round() is None  # no open match after end_match

    doc = store.get_match(mid)
    m = doc["match"]
    assert (m["game_id"], m["set_id"], m["set_core_name"], m["queue_id"],
            m["queue_kind"]) == (GAME_ID, 18, "TFTSet18", 1090, "normal")
    assert (m["placement"], m["placement_conf"], m["placement_src"]) == (1, 1.0, "lcu")
    assert (m["started_at"], m["ended_at"]) == (T0, T0 + 1900.0)
    assert (m["gt_status"], m["gt_sources"]) == ("full", ["lcu_eog"])
    keys = plan["keys"]
    assert [(p["player_key"], p["slot"], p["is_local"], p["final_standing"],
             p["final_standing_src"], p["eliminated_round_seq"]) for p in doc["players"]] \
        == [(k, i + 1, int(i == 0), i + 1, "lcu", None if i == 0 else 30 - i)
            for i, k in enumerate(keys)]
    assert _proj(doc["events"], ("kind", "payload", "round_seq")) == \
        [{"kind": "planner_saved", "payload": {"count": 1}, "round_seq": None}]
    assert _proj(doc["gt_board"], ("player_key", "champion_api", "star", "items",
                                   "cost")) == plan["gt_boards"]
    assert _proj(doc["gt_player"], ("player_key", "placement", "level", "last_round",
                                    "gold_left", "damage_to_players",
                                    "eliminated_at")) == plan["gt_players"]
    assert _proj(doc["accuracy"], ("field", "n", "correct", "coverage")) == \
        [{"field": "gold_start", "n": 30, "correct": 29, "coverage": 0.97}]

    rounds = doc["rounds"]
    assert [r["round_seq"] for r in rounds] == list(range(1, 31))
    assert rounds == list(store.iter_rounds(mid))
    for got, want in zip(rounds, plan["rounds"]):
        for name, e in want["env"].items():
            trip = (got[name], got[name + "_conf"], got[name + "_src"])
            if e is None:
                assert trip == (None, None, "absent"), name
            else:
                v = int(e.value) if isinstance(e.value, bool) else e.value
                assert trip == (v, e.conf, e.src), name
        for name, v in want["plain"].items():
            assert got[name] == v, name
        by_key = {}
        for u in got["units"]:
            by_key.setdefault((u["phase"], u["player_key"]), []).append(
                {k: u[k] for k in UNIT_KEYS})
        assert by_key == {k: _proj(v, UNIT_KEYS) for k, v in want["units"].items()}
        assert [{**_proj([s], SHOP_KEYS)[0], "offers": _proj(s["offers"], OFFER_KEYS)}
                for s in got["shop"]] == \
            [{**_proj([s], SHOP_KEYS)[0], "offers": _ints(s["offers"], "bought")}
             for s in want["shop"]]
        (odds,) = got["odds"]
        assert (odds["level"], (odds["p1"], odds["p2"], odds["p3"], odds["p4"], odds["p5"]),
                odds["conf"], odds["src"]) == tuple(want["odds"].values())
        got_traits = {}
        for t in got["traits"]:
            got_traits.setdefault(t["player_key"], []).append(_proj([t], TRAIT_KEYS)[0])
        assert got_traits == {k: sorted(_ints(v, "active"), key=lambda t: t["trait_api"])
                              for k, v in want["traits"].items()}
        assert _proj(got["augments"], ("pick_idx", "offered", "chosen_api", "conf",
                                       "src")) == want["augments"]
        assert _proj(got["players"], PR_KEYS) == \
            sorted(_ints(want["players"], "alive"), key=lambda p: p["player_key"])
        assert _proj(got["events"], ("kind", "ts", "src", "payload")) == \
            _proj(want["events"], ("kind", "ts", "src", "payload"))
        assert _proj(got["frames"], FRAME_KEYS) == want["frames"]
        assert _proj(got["obs"], OBS_KEYS) == want["obs"]


def test_list_matches_filters_newest_first(store):
    a = _write(store, _plan(rounds=2, seed=1), match_id="m-a")
    assert store.end_match(a, Env(6, 1.0, "lcu"), ended_at=T0 + 100)
    b = store.begin_match({"match_id": "m-b", "game_id": 2, "set_id": 17, "queue_id": 1100,
                           "started_at": T0 + 5000})
    assert store.end_match(b, Env(2, 1.0, "lcu"), ended_at=T0 + 6000)
    assert store.flush()
    assert [m["match_id"] for m in store.list_matches()] == ["m-b", "m-a"]
    assert [m["match_id"] for m in store.list_matches(set_id=18)] == ["m-a"]
    assert [m["match_id"] for m in store.list_matches(queue_kind="ranked")] == ["m-b"]
    assert [m["match_id"] for m in store.list_matches(top4_only=True)] == ["m-b"]
    assert store.get_match("nope") is None
    assert list(store.iter_rounds("nope")) == []


def test_rewrites_replace_rows_and_upserts_merge(store):
    plan = _plan(rounds=1)
    mid = _write(store, plan, match_id="m-x")
    k = plan["keys"][0]
    one = [{"zone": "board", "hex_row": 0, "hex_col": 0, "champion_api": "DA_18_Yorick",
            "star": 2, "items": [], "cost": 1, "conf": 1.0, "src": "eog_file",
            "pos_conf": 0.8, "pos_src": "geom"}]
    assert store.put_units(mid, 1, "planning_start", k, one)
    assert store.upsert_round(mid, 1, gold_start=Env(44, 0.5, "ocr"))
    # a zone-scoped rewrite leaves the other zone alone
    assert store.put_units(mid, 1, "planning_end", k, [], zone="bench")
    assert store.flush()
    (rd,) = list(store.iter_rounds(mid))
    mine = [u for u in rd["units"] if u["player_key"] == k and u["phase"] == "planning_start"]
    assert [(u["champion_api"], u["star"], u["bench_idx"]) for u in mine] == \
        [("DA_18_Yorick", 2, None)]
    assert (rd["gold_start"], rd["gold_start_src"]) == (44, "ocr")
    assert rd["level"] == plan["rounds"][0]["env"]["level"].value  # untouched
    end = [u for u in rd["units"] if u["player_key"] == k and u["phase"] == "planning_end"]
    assert len(end) == len(plan["rounds"][0]["units"][("planning_end", k)])


def test_a_child_row_creates_its_round(store):
    """A round is never invisible: any per-round write creates the round row
    (its envelopes absent), so iter_rounds shows data written before upsert_round."""
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    k = _keys()[0]
    assert store.put_player_round(mid, 4, k, hp=70, level_badge=5, alive=True, standing=3,
                                  conf=1.0, src="eog_file")
    assert store.record_obs(mid, 5, "planning_start", "gold", 12, 0.9, "ocr")
    assert store.flush()
    got = {r["round_seq"]: r for r in store.iter_rounds(mid)}
    assert sorted(got) == [4, 5]
    assert [p["hp"] for p in got[4]["players"]] == [70]
    assert (got[4]["gold_start"], got[4]["gold_start_src"]) == (None, "absent")
    assert [o["value"] for o in got[5]["obs"]] == [12]


# ---------------------------------------------------------------- fail-soft writer


def test_writes_never_raise_and_a_closed_store_drops(db_path):
    s = RoundStore.open(db_path)
    mid = s.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    s.close()
    assert not s.put_event(mid, "phase", {"phase": "x"}, src="tft_log")
    assert not s.upsert_round(mid, 1, level=Env(2, 1.0, "ocr"))
    assert s.stats()["closed"] == 2
    s.close()  # idempotent
    assert not any(t.name == st.WRITER_THREAD_NAME and t.is_alive()
                   for t in threading.enumerate())


def test_invalid_writes_log_once_per_streak(store, caplog):
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    with caplog.at_level(logging.INFO, logger=st.__name__):
        for _ in range(3):  # a raw name where a player key belongs
            assert not store.put_player_round(mid, 1, NAMES[0], hp=1, level_badge=1,
                                              alive=True, standing=1, conf=1.0, src="lcu")
        assert store.put_event(mid, "phase", {}, src="tft_log")
        assert not store.put_event(mid, "bogus_kind", {}, src="tft_log")
    mine = [r for r in caplog.records if r.name == st.__name__]
    warns = [r for r in mine if r.levelno == logging.WARNING]
    infos = [r for r in mine if r.levelno == logging.INFO]
    assert len(warns) == 2  # one per streak, not one per dropped row
    # section 1.2: the rejected name is never echoed into a log line
    assert "player_key" in warns[0].getMessage()
    assert not any("SyntheticPlayer" in r.getMessage() or "SYN" in r.getMessage()
                   for r in mine)
    assert len(infos) == 1 and "3" in infos[0].getMessage()
    assert store.stats()["invalid"] == 4


def test_db_error_drops_the_row_logs_once_and_keeps_writing(store, db_path, caplog):
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    assert store.flush()
    _exec(db_path, "DROP TABLE event")  # fault injection under the live writer
    k = _keys()[0]
    with caplog.at_level(logging.INFO, logger=st.__name__):
        for i in range(3):
            assert store.put_event(mid, "phase", {"i": i}, src="tft_log")  # enqueued
        assert store.flush()
        assert store.put_player_round(mid, 1, k, hp=90, level_badge=3, alive=True,
                                      standing=2, conf=1.0, src="eog_file")
        assert store.flush()
    assert store.stats()["write_errors"] == 3
    mine = [r for r in caplog.records if r.name == st.__name__]
    assert len([r for r in mine if r.levelno == logging.WARNING]) == 1
    assert len([r for r in mine if r.levelno == logging.INFO]) == 1  # the streak ended
    assert _scalar(db_path, "SELECT hp FROM player_round") == 90


def test_a_row_failing_midway_rolls_back_alone(store, db_path):
    """A replace that fails AFTER its delete must not lose the old rows: each
    row runs in its own savepoint, so the delete rolls back with the insert."""
    plan = _plan(rounds=1)
    mid = _write(store, plan, match_id="m-sp")
    k = plan["keys"][0]
    assert store.flush()
    before = [u["champion_api"] for u in next(store.iter_rounds(mid))["units"]
              if u["player_key"] == k and u["phase"] == "planning_end"]
    _exec(db_path, "CREATE TRIGGER inject_fail BEFORE INSERT ON unit_obs "
                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    one = [{"zone": "board", "champion_api": "DA_18_Yorick", "star": 1, "conf": 1.0,
            "src": "eog_file"}]
    assert store.put_units(mid, 1, "planning_end", k, one)
    assert store.put_event(mid, "phase", {"after": 1}, src="tft_log", round_seq=1)
    assert store.flush()
    assert store.stats()["write_errors"] == 1
    rd = next(store.iter_rounds(mid))
    assert [u["champion_api"] for u in rd["units"]
            if u["player_key"] == k and u["phase"] == "planning_end"] == before
    assert {"after": 1} in [e["payload"] for e in rd["events"]]  # the batch went on


def test_full_queue_drops_without_blocking_the_caller(db_path):
    s = RoundStore.open(db_path, queue_max=2)
    try:
        mid = s.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
        assert s.flush()
        s._run_gate.clear()  # test seam: stall the writer thread
        t = time.perf_counter()
        ok = [s.put_event(mid, "phase", {"i": i}, src="tft_log") for i in range(6)]
        assert time.perf_counter() - t < 0.5
        assert 0 < sum(ok) < 6
        assert s.stats()["queue_full"] == 6 - sum(ok)
        s._run_gate.set()
        assert s.flush()
        assert _scalar(db_path, "SELECT COUNT(*) FROM event") == sum(ok)
    finally:
        s._run_gate.set()
        s.close()


def test_identity_never_reaches_the_store(store):
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    k = _keys()[0]
    assert not store.upsert_player(mid, "SyntheticPlayer1", slot=1, is_local=True)
    assert not store.upsert_round(mid, 1, opponent_key=Env("SyntheticPlayer2", 0.9, "ocr"))
    assert not store.put_event(mid, "phase", {"puuid": "x" * 78}, src="tft_log")
    assert not store.put_event(mid, "phase", {"who": NAMES[1]}, src="tft_log")
    assert not store.record_obs(mid, 1, "planning_start", "banner", NAMES[2], 0.9, "ocr")
    assert not store.record_obs(mid, 1, "planning_start", "summonerName", "x", 0.9, "ocr")
    assert store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0,
                              "riotIdGameName": "x"}) is None
    assert store.upsert_player(mid, k, slot=1, is_local=True)
    assert store.stats()["invalid"] == 7
    # id-like fields share an id's character class with a UUID / PUUID, so they
    # get the shape check too; a stored event is never 'absent' either
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert not store.record_obs(mid, 1, "planning_start", uuid, 1, 0.9, "ocr")
    assert not store.put_accuracy(mid, [{"field": uuid, "n": 1, "correct": 1}])
    assert not store.put_frame(mid, 1, "planning_start", "m1/Big Al#NA1.jpg")
    assert store.put_frame(mid, 1, "planning_start", "m1/r01.jpg", frame_id="A" * 39 + "b" * 39) \
        is None
    assert not store.begin_match({"match_id": uuid, "game_id": 1, "queue_id": 1090})
    assert not store.put_event(mid, "phase", {"who": "Big Al#NA1"}, src="tft_log")
    assert not store.put_event(mid, "phase", {}, src="absent")
    assert store.stats()["invalid"] == 14


def test_an_identity_used_as_a_key_is_refused_and_scrubbed(store, db_path, tmp_path):
    """A dict KEY can carry an identity as well as a value can."""
    uuid = "123e4567-e89b-12d3-a456-426614174000"
    token = "A" * 39 + "b" * 39
    mid = store.begin_match({"game_id": 1, "queue_id": 1090, "started_at": T0})
    assert not store.record_obs(mid, 1, "planning_start", "scoreboard", {uuid: 5}, 0.9, "ocr")
    assert not store.put_event(mid, "phase", {NAMES[3]: 5}, src="tft_log")
    assert not store.put_event(mid, "phase", {"hp": {token: 5}}, src="tft_log")
    assert not store.record_obs(mid, 1, "planning_start", "eog", {"summoners": ["Bob"]}, 1.0,
                                "eog_file")
    assert store.stats()["invalid"] == 4
    # Riot's game-data name fields are not identities: an EoG-shaped board row stores
    assert store.record_obs(mid, 1, "planning_start", "eog_board",
                            {"championName": "DA_18_Yorick", "itemNames": ["TFT_Item_BFSword"],
                             "apiName": "DA_18_Summoner", "starLevel": 2}, 1.0, "eog_file")
    cases = (({uuid: 1}, uuid), ({NAMES[3]: 1}, "SyntheticPlayer"), ({token: 1}, token),
             ({"0123456789ab": 1}, "0123456789ab"), ({"riotId:SomeBody#EUW1": 1}, "SomeBody"),
             ({"x": {"Big Al#NA1": {"hp": 3}}}, "Big Al"))
    for doc, needle in cases:
        bad = st.scrub_violations(doc)
        assert bad, doc
        assert needle not in " ".join(bad) and needle not in str(st.ScrubError(bad)), doc
    # a store player key used as a payload key is mapped to its P-number on export
    k = _keys()
    for i, key in enumerate(k):
        assert store.upsert_player(mid, key, slot=i + 1, is_local=(i == 0))
    assert store.put_event(mid, "disagreement", {k[1]: {"hp": 40}, "note": f"opp={k[2]}",
                                                 "createdAt": T0 + 70.0, "time": 12.5},
                           src="derived", round_seq=1)
    assert store.put_traits(mid, 1, "planning_start", k[0],  # a real trait is not an identity
                            [{"trait_api": "DA_18_Summoner", "count": 2, "conf": 0.9,
                              "src": "derived"}])
    assert store.flush()
    fx = json.loads(store.export_fixture(mid, tmp_path / "fx", name="keys").read_text("ascii"))
    # whole or embedded, a key becomes Pn; a payload's own epoch becomes match-relative,
    # seconds-into-game stay as they are
    assert [e["payload"] for e in fx["rounds"][0]["events"]] == \
        [{"P2": {"hp": 40}, "note": "opp=P3", "createdAt": 70.0, "time": 12.5}]
    assert [t["trait_api"] for t in fx["rounds"][0]["traits"]] == ["DA_18_Summoner"]
    # and a raw row smuggling an identity key past the writer is refused on export
    _exec(db_path, "INSERT INTO obs(match_id, round_seq, field, value_json, conf, src) "
                   "VALUES (?, 1, 'scoreboard', ?, 0.9, 'ocr')", (mid, json.dumps({uuid: 5})))
    with pytest.raises(st.ScrubError):
        store.export_fixture(mid, tmp_path / "fx", name="keys_leak")
    assert not (tmp_path / "fx" / "keys_leak.json").exists()


# ---------------------------------------------------------------- open / migrate


def test_reopen_keeps_data_and_version(db_path):
    s = RoundStore.open(db_path)
    mid = _write(s, _plan(rounds=2))
    s.close()
    s2 = RoundStore.open(db_path)
    try:
        assert s2.ok
        assert len(list(s2.iter_rounds(mid))) == 2
        assert _scalar(db_path, "SELECT value FROM schema_meta "
                                "WHERE key = 'schema_version'") == "1"
    finally:
        s2.close()


def test_newer_schema_is_refused_fail_soft(db_path):
    db_path.parent.mkdir(parents=True)
    _exec(db_path, "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT)")
    _exec(db_path, "INSERT INTO schema_meta VALUES ('schema_version', '99')")
    s = RoundStore.open(db_path)
    try:
        assert not s.ok and "99" in s.error
        assert not s.put_event("m", "phase", {}, src="tft_log")
        assert s.list_matches() == []
    finally:
        s.close()
    assert _scalar(db_path, "SELECT COUNT(*) FROM sqlite_master") == 2  # untouched


def test_unopenable_path_is_fail_soft(tmp_path):
    bad = tmp_path / "is_a_dir.db"
    bad.mkdir()
    s = RoundStore.open(bad)
    try:
        assert not s.ok and s.error
        assert not s.put_event("m", "phase", {}, src="tft_log")
        assert s.list_matches() == [] and s.live_round() is None
        assert s.get_match("m") is None
    finally:
        s.close()


def test_readonly_store_reads_and_never_writes(db_path):
    s = RoundStore.open(db_path)
    mid = _write(s, _plan(rounds=1), match_id="m-ro")
    s.close()
    ro = RoundStore.open(db_path, readonly=True)
    try:
        assert not any(t.name == st.WRITER_THREAD_NAME for t in threading.enumerate())
        assert [m["match_id"] for m in ro.list_matches()] == [mid]
        assert not ro.put_event(mid, "phase", {}, src="tft_log")
    finally:
        ro.close()


def test_size_per_match_is_under_2_mb(db_path):
    s = RoundStore.open(db_path)
    _write(s, _plan())
    s.close()
    size = sum(p.stat().st_size for p in db_path.parent.glob(db_path.name + "*"))
    assert size < 2 * 1024 * 1024, f"one dense 30-round match = {size} bytes"


# ---------------------------------------------------------------- identity + exports


def test_player_key_is_a_salted_hmac_prefix(tmp_path):
    k = st.player_key(NAMES[0], SALT)
    assert len(k) == 12 and all(c in "0123456789abcdef" for c in k)
    assert k == st.player_key(NAMES[0], SALT) != st.player_key(NAMES[0], b"other-salt-xyz")
    assert st.player_key(NAMES[0], SALT) != st.player_key(NAMES[1], SALT)
    salt_path = tmp_path / "tft" / ".salt"
    salt = st.load_salt(salt_path)
    assert len(salt) == 32 and salt_path.read_bytes() == salt
    assert st.load_salt(salt_path) == salt


def test_fixture_export_is_scrubbed(store, tmp_path):
    plan = _plan()
    mid = _write(store, plan)
    assert store.end_match(mid, Env(1, 1.0, "lcu"), ended_at=T0 + 1900.0)
    assert store.flush()
    out = store.export_fixture(mid, tmp_path / "fx", name="synthetic_30")
    assert out == tmp_path / "fx" / "synthetic_30.json"
    raw = out.read_bytes()
    assert raw.isascii() and b"\r" not in raw
    text = raw.decode("ascii")
    for needle in (*NAMES, *plan["keys"], str(GAME_ID), mid, "SYN", "m1/r01"):
        assert needle not in text, needle
    doc = json.loads(text)
    assert st.scrub_violations(doc) == []
    assert doc["match"]["match_id"] == "synthetic_30"
    assert doc["match"]["game_id"] == st.FIXTURE_GAME_ID
    assert (doc["match"]["started_at"], doc["match"]["ended_at"]) == (0.0, 1900.0)
    assert [(p["player_key"], p["is_local"]) for p in doc["players"]] == \
        [(f"P{i}", int(i == 1)) for i in range(1, 9)]
    assert len(doc["rounds"]) == 30
    r1 = doc["rounds"][0]
    assert (r1["planning_ts"], r1["shop"][0]["ts"]) == (60.0, 62.0)
    assert r1["opponent_key"] == "P3"  # keys[1 + 1 % 7] = the 3rd player
    assert {u["player_key"] for u in r1["units"]} == {f"P{i}" for i in range(1, 9)}
    assert "frames" not in r1 and all(u["frame_id"] is None for u in r1["units"])
    assert all(o["frame_id"] is None for o in r1["obs"])
    # the export is the data, not a summary: the round-1 units survive whole
    assert len(r1["units"]) == len(store.get_match(mid)["rounds"][0]["units"])


def test_scrub_guard_catches_every_identity_shape():
    bad = [
        {"puuid": "x"}, {"riotIdGameName": "x"}, {"riotIdTagLine": "x"},
        {"summonerName": "x"}, {"summonerId": 1}, {"gameName": "x"}, {"playerId": 3},
        {"accountId": 1}, {"displayName": "x"}, {"name": "x"},
        {"v": "123e4567-e89b-12d3-a456-426614174000"},
        {"v": "SomeBody#EUW1"}, {"v": "summonerId=42"}, {"v": "riot id: x"},
        {"v": "A" * 39 + "b" * 39}, {"v": ENCRYPTED_47},
        {"v": "123e4567e89b12d3a456426614174000"},  # a UUID without dashes
        {"v": "NA1_1000000911"},  # a Riot match id finds all 8 players
        # any key holding a name / nick, and game / match id keys of a payload
        {"opponentName": "Bob"}, {"enemy_name": "Bob"}, {"names": ["Bob"]},
        {"nickname": "Bob"}, {"gameId": 1}, {"matchId": "x"},
        {"summoner": "Bob"}, {"summoners": ["Bob"]}, {"riotTag": "EUW"},
        {"DA_player_name": "Bob"}, {"TFT_opponentName": "Bob"},  # api-shaped smuggling
        {"".join(chr(0xFF00 + ord(c) - 0x20) for c in "name"): "Bob"},  # fullwidth key
        {"v": "na1_1000000911"}, {"v": "Euw1_1000000911"}, {"v": "2026-10-25T07:03:50Z"},
        {"t": T0}, {"t": T0 * 1000.0},  # an absolute epoch, seconds or ms
        {"player_key": "0123456789ab"}, {"opponent_key": "SomeBody"},
        [{"deep": [{"puuid": "x"}]}],
        # Riot game names may hold spaces / non-ASCII, and the hash may be fullwidth
        {"v": "Big Al#NA1"}, {"v": "Mr X#EUW"}, {"v": "SomeBody #EUW1"},
        {"v": "SomeBody" + chr(0xFF03) + "EUW1"}, {"v": "Mr X" + chr(0xFE5F) + "EUW"},
        {"v": "opp=0123456789ab"},  # a store key inside a longer string
    ]
    for doc in bad:
        assert st.scrub_violations(doc), doc
    # and no false positive on real game data: the longest measured TFT api names
    # (data/meta/tft_set18_cdragon.json), the Set 18 Summoner trait, schema keys
    ok = {"player_key": "P3", "opponent_key": None, "name_text": "Yorick",
          "champion_api": "DA_18_Yorick", "sha256": "0" * 64,
          "set_core_name": "TFTSet18", "label": "3-2", "trait_api": "DA_18_Summoner",
          "traits": {"DA_18_Summoner": 3}, "eliminated_at": 1740.0, "ts": 61.5,
          # Riot's own game-data name fields name data, never a player
          "apiName": "DA_18_Yorick", "itemNames": ["TFT_Item_BFSword"],
          "championName": "DA_18_Yorick", "traitName": "DA_18_Summoner",
          "nameId": "TFT_Item_BFSword", "bossName": "", "tft_set_core_name": "TFTSet18",
          "items": {"TFT_Item_BFSword": 1, "DA_KnickKnackBag18": 1},  # "nick" in an api id
          "augments": ["TFT_Augment_MirroredMonetization_TotalGoldTooltip",
                       "TFT_Augment_NoScoutNoPivot_TrackerTRAKEY_Holder",
                       "TFT_Augment_BronzeForLife_CurrentDamageAmp",
                       "TFT14_CypherArmoryItem_SpecificRadiantItems"]}
    assert st.scrub_violations(ok) == []


def test_export_refuses_a_store_row_that_carries_identity(store, db_path, tmp_path):
    mid = _write(store, _plan(rounds=1))
    assert store.flush()
    _exec(db_path, "INSERT INTO event(match_id, ts, kind, payload_json, src) "
                   "VALUES (?, ?, 'phase', ?, 'tft_log')",
          (mid, T0, json.dumps({"summonerName": "Leaked"})))  # bypasses the writer guard
    with pytest.raises(st.ScrubError):
        store.export_fixture(mid, tmp_path / "fx", name="leak")
    assert not (tmp_path / "fx" / "leak.json").exists()


def test_analysis_exports(store, tmp_path):
    mid = _write(store, _plan(rounds=3))
    assert store.flush()
    jl = store.export_jsonl([mid], tmp_path / "x" / "rounds.jsonl")
    recs = [json.loads(line) for line in jl.read_text(encoding="ascii").splitlines()]
    assert [r["record"] for r in recs] == ["match", "round", "round", "round"]
    assert all(r["match_id"] == mid for r in recs)
    paths = store.export_csv([mid], tmp_path / "csv")
    assert {"match.csv", "round.csv", "unit_obs.csv", "shop_offer.csv"} <= \
        {p.name for p in paths}
    rnd = (tmp_path / "csv" / "round.csv").read_text(encoding="ascii").splitlines()
    assert rnd[0].split(",")[:2] == ["match_id", "round_seq"] and len(rnd) == 4


def test_analysis_exports_default_under_data_tft_exports(store, tmp_path, monkeypatch):
    monkeypatch.setattr(st, "default_exports_dir", lambda: tmp_path / "exports")
    mid = _write(store, _plan(rounds=1))
    assert store.flush()
    jl = store.export_jsonl([mid])
    paths = store.export_csv([mid])
    assert jl.parent == tmp_path / "exports" and jl.name.startswith("tft-rounds-")
    assert {p.parent.parent for p in paths} == {tmp_path / "exports"}


# ---------------------------------------------------------------- repo hygiene


def _git(*args):
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def test_data_tft_is_gitignored_and_holds_no_tracked_file():
    for rel in ("data/tft/tft_rounds.db", "data/tft/.salt", "data/tft/frames/m1/r01.jpg",
                "data/tft/icon_cache/items/x.png", "data/tft/exports/round.csv",
                "data/tft/exemplars/DA_18_Yorick.png"):
        assert _git("check-ignore", "-q", "--", rel).returncode == 0, rel
    listed = _git("ls-files", "--", "data/tft")
    assert listed.returncode == 0 and listed.stdout.strip() == ""


def test_default_paths_are_under_gitignored_data_tft():
    assert st.default_db_path() == ROOT / "data" / "tft" / "tft_rounds.db"
    assert st.default_salt_path() == ROOT / "data" / "tft" / ".salt"
    assert st.default_exports_dir() == ROOT / "data" / "tft" / "exports"


def test_package_is_stdlib_only_llm_free_ascii_lf():
    """No LLM client, no coach, no DS: stdlib plus the one sanctioned atomic
    writer (core/polled_json.py `atomic_write_bytes`, RM-258 guard
    tests/test_atomic_write_guard_rm258_rm261.py). TFT-08's ground_truth.py
    also reads the RM-616 placement store through its read API
    (tft.tft_placement) and parses set ids with tft.tft_set; both are pinned
    below to stdlib plus the same core helpers, so the rule holds one hop out."""
    allowed = {"core.polled_json", "tft.tft_placement", "tft.tft_set"}
    files = sorted(PKG.glob("*.py"))
    assert {p.name for p in files} == {"__init__.py", "schema.py", "store.py",
                                       "ground_truth.py", "accuracy.py"}
    hop = [ROOT / "tft" / "tft_placement.py", ROOT / "tft" / "tft_set.py"]
    for p in hop:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module or ""]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            else:
                continue
            for m in mods:
                assert (m.split(".")[0] in sys.stdlib_module_names
                        or m in ("core.polled_json", "core.queue_modes")), (p, m)
    for p in [*files, Path(__file__)]:
        raw = p.read_bytes()
        assert raw.isascii() and b"\r" not in raw, p
    for p in files:
        for node in ast.walk(ast.parse(p.read_text(encoding="ascii"))):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                mods = [node.module or ""]
            else:
                continue
            for m in mods:
                top = m.split(".")[0]
                assert (top in sys.stdlib_module_names or m.startswith("tft.rounds")
                        or m in allowed), (p, m)
