"""Synthetic history for the TFT engine tests (slice TFT-13), plus the tests
that pin the synthetic history itself.

Everything here is invented or is public game data: no player name, Riot id,
PUUID, summoner id or game id appears (the repo is PUBLIC). The other
tests/test_tft_engine_*.py modules import the builders below.

Two kinds of input:

* SYNTH_DOC - a tiny CommunityDragon-shaped set extract (12 units, 6 traits,
  5 components, 6 recipes). Logic tests use it so a re-fetch of the real
  Set 18 extract can never move their expectations.
* worked_example_record() - the operator's recorded Set 18 match of
  2026-10-25 (ops/runtime/tft_qa/20261025-070350/QA_REPORT.md section 5,
  gitignored), rebuilt as TFT-01 store rows: the level / econ table, the
  roll-downs at 5-3 and 5-5, the 4-2 level-plus-Draven spend that is NOT a
  roll-down, and the final EoG board (Set 18 apiNames, which are game data).
  Stage 1 and 2-1 were not captured, so the rows start at 2-2.
"""
from __future__ import annotations

import json

# --------------------------------------------------------------------------
# Synthetic set extract (same keys tft/tft_set.load_cdragon returns)
# --------------------------------------------------------------------------

SYNTH_SET_ID = 99

SYNTH_DOC = {
    "_set": SYNTH_SET_ID,
    "units": [
        {"apiName": "U_Ace", "name": "Ace", "cost": 1, "traits": ["Blade", "Ward"]},
        {"apiName": "U_Bolt", "name": "Bolt", "cost": 1, "traits": ["Mage", "Beast"]},
        {"apiName": "U_Cora", "name": "Cora", "cost": 2, "traits": ["Blade", "Mage"]},
        {"apiName": "U_Dune", "name": "Dune", "cost": 2, "traits": ["Ward", "Beast"]},
        {"apiName": "U_Echo", "name": "Echo", "cost": 3, "traits": ["Blade", "Crown"]},
        {"apiName": "U_Fang", "name": "Fang", "cost": 3, "traits": ["Beast", "Ward"]},
        {"apiName": "U_Gale", "name": "Gale", "cost": 4, "traits": ["Mage", "Blade"]},
        {"apiName": "U_Hex", "name": "Hex", "cost": 4, "traits": ["Beast"]},
        {"apiName": "U_Ira", "name": "Ira", "cost": 5, "traits": ["Solo"]},
        {"apiName": "U_Jinx", "name": "Jinx", "cost": 5, "traits": ["Mage", "Crown"]},
        {"apiName": "U_Kite", "name": "Kite", "cost": 2, "traits": ["Mage"]},
        {"apiName": "U_Lumen", "name": "Lumen", "cost": 3, "traits": ["Mage", "Ward"]},
    ],
    "traits": [
        {"apiName": "T_Blade", "name": "Blade", "breakpoints": [2, 4, 6]},
        {"apiName": "T_Ward", "name": "Ward", "breakpoints": [2, 4]},
        {"apiName": "T_Mage", "name": "Mage", "breakpoints": [3, 5]},
        {"apiName": "T_Beast", "name": "Beast", "breakpoints": [2, 3, 4]},
        {"apiName": "T_Solo", "name": "Solo", "breakpoints": [1]},
        {"apiName": "T_Crown", "name": "Crown", "breakpoints": [1, 2]},
    ],
    "items": [
        {"apiName": "C_Sword", "name": "Sword", "composition": []},
        {"apiName": "C_Bow", "name": "Bow", "composition": []},
        {"apiName": "C_Rod", "name": "Rod", "composition": []},
        {"apiName": "C_Vest", "name": "Vest", "composition": []},
        {"apiName": "C_Spat", "name": "Spat", "composition": []},
        {"apiName": "I_Edge", "name": "Edge", "composition": ["C_Sword", "C_Sword"]},
        {"apiName": "I_Rage", "name": "Rage", "composition": ["C_Bow", "C_Rod"]},
        {"apiName": "I_Staff", "name": "Staff", "composition": ["C_Rod", "C_Rod"]},
        {"apiName": "I_Plate", "name": "Plate", "composition": ["C_Vest", "C_Vest"]},
        {"apiName": "I_Cleave", "name": "Cleave", "composition": ["C_Sword", "C_Bow"]},
        {"apiName": "I_BladeEmblem", "name": "Blade Emblem", "composition": ["C_Spat", "C_Sword"]},
        {"apiName": "I_Relic", "name": "Relic", "composition": []},
    ],
    "augments": [
        {"apiName": "A_Rich", "name": "Rich Get Richer"},
        {"apiName": "A_Tank", "name": "Tank Up"},
    ],
}


def u(api, star=1, items=(), cost=None):
    """One board unit in the TFT-08 final-board / unit_obs shape."""
    row = {"champion_api": api, "star": star, "items": list(items)}
    if cost is not None:
        row["cost"] = cost
    return row


# Archetype A: Mage / Blade around Gale (the itemised carry).
def board_a(variant=0):
    flex = [["U_Lumen"], ["U_Echo"], ["U_Kite", "U_Echo"]][variant % 3]
    board = [
        u("U_Gale", 2, ["I_Rage", "I_Staff", "I_Edge"]),
        u("U_Jinx", 1, ["I_Staff"]),
        u("U_Cora", 2),
        u("U_Bolt", 3 if variant == 1 else 2),
        u("U_Kite", 2),
    ]
    for api in flex:
        if api not in {b["champion_api"] for b in board}:
            board.append(u(api, 2))
    return board


# Archetype B: Beast / Ward around Hex.
def board_b(variant=0):
    flex = [["U_Ace"], ["U_Lumen"], ["U_Ace", "U_Ira"]][variant % 3]
    board = [
        u("U_Hex", 2, ["I_Edge", "I_Cleave", "I_Rage"]),
        u("U_Fang", 2, ["I_Plate"]),
        u("U_Dune", 2),
        u("U_Bolt", 2),
    ]
    for api in flex:
        board.append(u(api, 2))
    return board


def synth_history():
    """Nine synthetic matches in set 99: five A-boards, four B-boards.

    A placements 1, 2, 3, 6, 4 (four top-4); B placements 5, 7, 2, 8 (one).
    One extra match is a Double Up game and one is from another set; the
    catalogue must skip both.
    """
    rows = []
    for i, place in enumerate([1, 2, 3, 6, 4]):
        rows.append({"match_id": f"m-a{i}", "set_id": SYNTH_SET_ID, "queue_kind": "ranked",
                     "placement": place, "final_board": board_a(i),
                     "augments": ["A_Rich"] if i % 2 == 0 else ["A_Tank"]})
    for i, place in enumerate([5, 7, 2, 8]):
        rows.append({"match_id": f"m-b{i}", "set_id": SYNTH_SET_ID, "queue_kind": "normal",
                     "placement": place, "final_board": board_b(i)})
    rows.append({"match_id": "m-du", "set_id": SYNTH_SET_ID, "queue_kind": "double_up",
                 "placement": 1, "final_board": board_a(0)})
    rows.append({"match_id": "m-old", "set_id": 98, "queue_kind": "ranked",
                 "placement": 1, "final_board": board_a(0)})
    return rows


# --------------------------------------------------------------------------
# Synthetic per-round store rows (TFT-01 schema v1, docs/TFT_PROGRAM.md 1.5)
# --------------------------------------------------------------------------

def stage_labels(first="2-2", last="6-1"):
    """Set 18 labels as measured (QA_REPORT section 2: 7 rounds in stages 2-5)."""
    out = []
    for stage in range(1, 8):
        for rnd in range(1, 8):
            out.append(f"{stage}-{rnd}")
    return out[out.index(first): out.index(last) + 1]


def round_row(seq, label, level=None, gold_start=None, gold_end=None, hp=None, src="ocr", conf=0.95):
    stage, rnd = (int(x) for x in label.split("-"))
    row = {"round_seq": seq, "stage": stage, "stage_conf": 1.0, "stage_src": "ocr",
           "round": rnd, "round_conf": 1.0, "round_src": "ocr", "label": label}
    for field, value, fsrc in (("level", level, src), ("gold_start", gold_start, src),
                               ("gold_end", gold_end, src), ("hp_start", hp, "eog_file")):
        row[field] = value
        row[field + "_conf"] = None if value is None else (1.0 if fsrc == "eog_file" else conf)
        row[field + "_src"] = "absent" if value is None else fsrc
    return row


def refresh_rows(seq, causes_and_gold):
    """shop_refresh rows: [(cause, gold_before, gold_after), ...]."""
    out = []
    for idx, (cause, before, after) in enumerate(causes_and_gold):
        out.append({"round_seq": seq, "refresh_idx": idx, "cause": cause,
                    "gold_before": before, "gold_after": after, "conf": 0.9, "src": "ocr"})
    return out


def rerolls(seq, start_gold, n):
    """A round-start refresh then n rerolls of 2 gold each from start_gold."""
    rows = [("round_start", start_gold, start_gold)]
    gold = start_gold
    for _ in range(n):
        rows.append(("reroll", gold, gold - 2))
        gold -= 2
    return refresh_rows(seq, rows)


# QA_REPORT section 5 level / econ table, one level per label from 2-2.
_WORKED_LEVELS = {
    "2-2": 4, "2-3": 4, "2-4": 4, "2-5": 5, "2-6": 5, "2-7": 5,
    "3-1": 6, "3-2": 6, "3-3": 6, "3-4": 6, "3-5": 6, "3-6": 7, "3-7": 7,
    "4-1": 7, "4-2": 8, "4-3": 8, "4-4": 8, "4-5": 8, "4-6": 8, "4-7": 8,
    "5-1": 8, "5-2": 8, "5-3": 9, "5-4": 9, "5-5": 9, "5-6": 9, "5-7": 9, "6-1": 9,
}
_WORKED_GOLD = {  # (gold at planning start, gold at planning end)
    "2-2": (12, 12), "2-5": (28, 24), "2-7": (43, 43), "3-1": (56, 36), "3-2": (40, 40),
    "3-3": (57, 59), "3-5": (71, 50), "3-6": (64, 50), "4-1": (53, 68), "4-2": (57, 12),
    "4-6": (47, 47), "4-7": (72, 72), "5-1": (50, 50), "5-2": (52, 52), "5-3": (64, 3),
    "5-5": (12, 0), "5-7": (13, 13), "6-1": (31, 34),
}
WORKED_FINAL_BOARD = [
    u("DA_Draven18", 2, ["DA_ThiefsGloves", "DA_SteraksGage", "DA_KrakensFury"], 5),
    u("DA_Taric18", 2, [], 5),
    u("DA_18_Aphelios", 2, ["DA_NashorsTooth", "DA_GuinsoosRageblade", "DA_InfinityEdge"], 4),
    u("DA_18_Diana", 2, [], 3),
    u("DA_Fiddlesticks18", 2, [], 3),
    u("DA_18_Sejuani", 2, ["DA_18_EmblemPrimal", "DA_DragonsClaw", "DA_SpiritVisage"], 2),
    u("DA_18_Yunara", 2, ["DA_GuinsoosRageblade", "DA_18_EmblemSpellweaver", "DA_ArchangelsStaff"], 2),
    u("DA_Karma18", 2, ["DA_VoidStaff"], 1),
    u("DA_18_Yorick", 2, ["DA_18_EmblemFloraFatalis", "DA_Evenshroud", "DA_SteadfastHeart"], 1),
]


def worked_example_record(match_id="qa-20261025-070350"):
    rounds = []
    for seq, label in enumerate(stage_labels("2-2", "6-1"), start=1):
        gs, ge = _WORKED_GOLD.get(label, (None, None))
        rounds.append(round_row(seq, label, level=_WORKED_LEVELS[label],
                                gold_start=gs, gold_end=ge, hp=100))
    seq_of = {r["label"]: r["round_seq"] for r in rounds}
    shop = []
    shop += rerolls(seq_of["2-5"], 28, 0)
    shop += rerolls(seq_of["3-5"], 71, 1)
    # 4-2: 57 -> 12 is a level-up plus a 5-cost buy, with ONE reroll: not a roll-down.
    shop += rerolls(seq_of["4-2"], 57, 1)
    # 5-3: level 9, then the spend-down 30 -> 3 (13 rerolls).
    shop += refresh_rows(seq_of["5-3"], [("round_start", 64, 64)]
                         + [("reroll", 30 - 2 * i, 28 - 2 * i) for i in range(13)])
    # 5-5: 12 -> 0 on 6 rerolls (12 gold: below the 20-gold arm, at the 3-reroll arm).
    shop += rerolls(seq_of["5-5"], 12, 6)
    return {"match_id": match_id, "set_id": 18, "queue_kind": "normal", "placement": 1,
            "final_board": [dict(x) for x in WORKED_FINAL_BOARD], "rounds": rounds,
            "shop_refreshes": shop, "units": []}


def timeline_record(match_id, placement, levels, *, gold=None, hp=None, shop=None, units=None,
                    final_board=None, set_id=SYNTH_SET_ID, first="2-1", last="5-7"):
    """A synthetic match: levels = {label: level} applied forward from each label."""
    rounds = []
    current = None
    gold = gold or {}
    hp = hp or {}
    for seq, label in enumerate(stage_labels(first, last), start=1):
        if label in levels:
            current = levels[label]
        g = gold.get(label)
        rounds.append(round_row(seq, label, level=current, gold_start=g, gold_end=g, hp=hp.get(label)))
    return {"match_id": match_id, "set_id": set_id, "queue_kind": "ranked", "placement": placement,
            "final_board": final_board if final_board is not None else board_a(0),
            "rounds": rounds, "shop_refreshes": shop or [], "units": units or []}


def seq_for(label, first="2-1"):
    labels = stage_labels(first, "7-7")
    return labels.index(label) + 1


def obs(label, api, star=1, items=(), first="2-1", phase="planning_start", zone="board",
        conf=1.0, src="eog_file"):
    return {"round_seq": seq_for(label, first), "phase": phase, "player_key": "P1", "zone": zone,
            "champion_api": api, "star": star, "items_json": json.dumps(list(items)),
            "conf": conf, "src": src}


# --------------------------------------------------------------------------
# Tests that pin the synthetic history itself
# --------------------------------------------------------------------------

def test_stage_labels_follow_the_measured_set18_shape():
    labels = stage_labels("2-1", "3-1")
    assert labels == ["2-1", "2-2", "2-3", "2-4", "2-5", "2-6", "2-7", "3-1"]


def test_worked_example_rows_mirror_the_qa_timeline():
    rec = worked_example_record()
    rounds = rec["rounds"]
    assert rounds[0]["label"] == "2-2" and rounds[-1]["label"] == "6-1"
    assert len(rounds) == 28
    by_label = {r["label"]: r for r in rounds}
    assert by_label["3-1"]["level"] == 6 and by_label["3-6"]["level"] == 7
    assert by_label["4-2"]["level"] == 8 and by_label["5-3"]["level"] == 9
    assert by_label["4-2"]["gold_start"] == 57 and by_label["4-2"]["gold_end"] == 12
    assert by_label["2-3"]["gold_start"] is None and by_label["2-3"]["gold_start_src"] == "absent"


def test_synthetic_fixtures_carry_no_identity_keys():
    banned = ("puuid", "riotid", "summoner", "gamename", "tagline", "playerid", "accountid")
    blob = json.dumps([synth_history(), worked_example_record(), SYNTH_DOC]).lower()
    for key in banned:
        assert key not in blob, key
