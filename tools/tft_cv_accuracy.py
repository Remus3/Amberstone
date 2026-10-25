#!/usr/bin/env python
"""TFT CV accuracy harness (docs/TFT_PROGRAM.md section 3.4, slice TFT-06).

Grades a computer-vision extractor field by field against ground truth and
prints per-field accuracy, coverage and confusion, so TFT-04 (OCR fields),
TFT-05 (board / icons) and TFT-18 (exemplars) can be measured and post-match QA
can report "vision accuracy this match".

Ground truth (any mix):

- ``--labels``: hand labels for recorded frames (oracle C), schema
  ``tft_cv_labels/1``. The committed set is
  ``tests/fixtures/tft_cv/labels_20261025-070350.json``: scrubbed (no player
  name anywhere, scoreboard rows positional, the local row flagged), closed
  vocabulary, authored by one agent and verified blind by a second. The frames
  themselves stay in the gitignored corpus (they show other players' names).
- ``--eog``: per-round ``TFTEoGStats.json`` snapshots (oracle A; a file or a
  directory of copies). Each frame is graded against the latest snapshot taken
  at or before it (frame times from the corpus ``frames.jsonl``; snapshot time =
  its ``_rc_captured_at`` key, else the file mtime) within ``--max-age`` s.
- ``--lcu-eog``: the LCU ``/lol-end-of-game/v1/tft-eog-stats`` document (oracle
  B): final boards + placement, graded against the prediction record ``final``
  (else the last graded frame that carries ``players``).

Players are keyed ``P1`` (local) .. ``P8``; the other keys follow the source
document's player order. Identity fields (PUUID, Riot id, summoner name,
player id, companion) are never read past the local flag, so nothing here can
copy one into a report.

Predictions come from ``--extractor pkg.module:function`` (called once per
frame with the frame path, plus a meta dict when it takes two arguments) or
from ``--predictions <json>`` (``{"frames": [{"frame", "fields"}]}`` or a plain
``{frame: fields}`` map). Fields use the label field names; any field may be an
envelope ``{"value": v, "conf": c}``; values below ``--gate`` count as absent.

Semantics: a label value is what the frame displays and a careful human can
read; ``null`` = labelled not visible / not readable (a reader must yield
absent); a missing key = not labelled (not graded). Per field: ``acc`` = correct
/ answered, ``cov`` = answered / labelled-present, ``abs_ok`` = share of
labelled-absent cases where the reader also yielded nothing (the rest are
``false_present`` hallucinations). Multiset fields (traits, occluders, boards)
add element precision / recall over answered records. The verdict applies the
corpus half of the SHOW / MARK / HIDE gates (show: acc >= 0.98; hide: cov <
0.5); the live half (>= 0.95 over 3 matches) is measured per match elsewhere.

Usage:
  python tools/tft_cv_accuracy.py                       # label inventory + frame check
  python tools/tft_cv_accuracy.py --extractor tft.cv.ocr_fields:extract
  python tools/tft_cv_accuracy.py --corpus <match dir> --no-labels --eog <dir> \
      --lcu-eog <eog.json> --extractor <spec> --json-out <report.json>

Exit codes: 0 ok (or SKIP when the local corpus is absent), 1 frame check failed
under --strict, 2 bad input.

Local dataset (gitignored, beside the frames): ``ops/runtime/tft_qa/<match>/labels/``
holds ``labels.json`` (byte-identical to the committed fixture) plus the
double-labelling evidence: ``author_compact.jsonl`` / ``blind_compact.jsonl`` (one
frame per line, compact keys f=frame scr=screen so=shop_open oc=occluders st=stage
tm=timer lv=level xp=[xp_cur, xp_max] g=gold sk=streak od=odds bx=buy_xp_cost
rr=reroll_cost hc=hud_counter shop=[[name, cost(, "special")] | null x5]
sb=[[hp, level(, 1 = local)]] hl=hp_local tr=[[trait, count, active]]
trm=traits_more aug=augment_offers io=item_offers), ``diff.json`` and
``adjudication.json``.
"""
from __future__ import annotations

import argparse
import bisect
import functools
import hashlib
import importlib
import inspect
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "tft_cv_labels/1"
REPORT_SCHEMA = "tft_cv_accuracy/1"
DEFAULT_LABELS = ROOT / "tests" / "fixtures" / "tft_cv" / "labels_20261025-070350.json"
DEFAULT_CORPUS = ROOT / "ops" / "runtime" / "tft_qa" / "20261025-070350"

ABSENT = "<absent>"
EMPTY_SLOT = "<empty>"
SHOW_ACCURACY = 0.98        # corpus half of the spec 3.4 SHOW gate
LIVE_SHOW_ACCURACY = 0.95   # live half (3 matches), measured per match, not here
HIDE_COVERAGE = 0.5
CONF_BINS = ((0.0, 0.5), (0.5, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.0))
CONFUSION_CAP = 25

SCREENS = ("board", "carousel", "augment_choice", "item_choice", "settings")
OCCLUDERS = ("inspect_panel", "damage_panel", "scoreboard_popup", "item_tooltip",
             "media_widget", "phase_banner", "settings_panel")
SHOP_KINDS = ("champion", "special")
SCALAR_INT = ("timer", "level", "xp_cur", "xp_max", "gold", "streak", "buy_xp_cost",
              "reroll_cost", "hud_counter", "hp_local", "traits_more")
LABEL_FIELDS = ("screen", "shop_open", "occluders", "stage", *SCALAR_INT, "odds", "shop",
                "scoreboard", "traits", "augment_offers", "item_offers")
GT_ONLY_FIELDS = ("players", "placement")    # from the EoG / LCU adapters
MULTISET_FAMILIES = frozenset({"traits", "traits.active", "occluders",
                               "board.units", "board.stars", "board.items"})
FIELD_ORDER = ("screen", "shop_open", "occluders", "stage", "timer", "level", "xp_cur",
               "xp_max", "gold", "streak", "odds", "odds.slot", "buy_xp_cost",
               "reroll_cost", "hud_counter", "shop", "shop.name", "shop.cost", "hp_local",
               "scoreboard.rows", "scoreboard.local_row", "scoreboard.hp",
               "scoreboard.level", "traits", "traits.active", "traits_more",
               "augment_offers", "item_offers", "hp", "board.units", "board.stars",
               "board.items", "placement")

# Shop cards read off the 2026-10-25 match that the tracked 16.21 extract lacks
# (the "Add 2 to your win streak" card). Closed vocabulary for the scrub guard.
EXTRA_SHOP_CARDS = frozenset({"Flood"})

IDENTITY_KEY = re.compile(r"puuid|riotid|gamename|tagline|summoner|playerid|displayname|"
                          r"companion|accountid", re.I)
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
STAGE_RE = re.compile(r"\d-\d")
SHA_RE = re.compile(r"[0-9a-f]{64}")
META_KEYS = frozenset({"schema", "match", "set", "frame_size", "source_size", "privacy",
                       "semantics", "verification", "frames"})
VERIFICATION_KEYS = frozenset({"method", "author", "verifier", "frames_compared",
                               "values_compared", "disagreements", "adjudicated"})
FRAME_KEYS = frozenset({"frame", "el", "sha256", "labels"})


# ---------------------------------------------------------------------------
# set data (names only; Riot art never enters this tool)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=4)
def _cdragon(set_number: int) -> dict:
    try:
        from tft import tft_set
        doc = tft_set.load_cdragon(set_number)
    except (ImportError, OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _rows(doc: dict, key: str) -> list:
    rows = doc.get(key)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


@functools.lru_cache(maxsize=4)
def _name_maps(set_number: int):
    doc = _cdragon(set_number)
    units = {r["apiName"]: r["name"] for r in _rows(doc, "units")
             if isinstance(r.get("apiName"), str) and isinstance(r.get("name"), str)}
    items = {r["apiName"]: r["name"] for r in _rows(doc, "items")
             if isinstance(r.get("apiName"), str) and isinstance(r.get("name"), str)}
    by_squash = {}
    for name in units.values():
        by_squash.setdefault(_squash(name), name)
    return units, items, by_squash


def _squash(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def unit_name(api, set_number: int = 18):
    """Display name for an EoG / LCU champion id (DA_18_Kayle, DA_Draven18, TFT18_X)."""
    if not isinstance(api, str) or not api.strip():
        return None
    units, _items, by_squash = _name_maps(set_number)
    if api in units:
        return units[api]
    token = re.sub(r"^(?:DA|TFT\d*)_", "", api.strip())
    token = re.sub(r"^\d+_", "", token)
    token = re.sub(r"\d+$", "", token).split("_")[0]
    return by_squash.get(_squash(token), token)


def item_name(api, set_number: int = 18):
    if not isinstance(api, str) or not api.strip():
        return None
    _units, items, _sq = _name_maps(set_number)
    if api in items:
        return items[api]
    return re.sub(r"^(?:DA|TFT\d*)_(?:Item_)?", "", api.strip())


def label_vocab(set_number: int = 18) -> frozenset:
    """Closed vocabulary every label string must come from (scrub guard)."""
    doc = _cdragon(set_number)
    words = set(EXTRA_SHOP_CARDS) | set(SCREENS) | set(OCCLUDERS) | set(SHOP_KINDS)
    for key in ("units", "traits", "items", "augments"):
        words.update(r["name"] for r in _rows(doc, key) if isinstance(r.get("name"), str))
    for key in ("champions", "all_traits"):
        vals = doc.get(key)
        if isinstance(vals, list):
            words.update(v for v in vals if isinstance(v, str))
    return frozenset(words)


# ---------------------------------------------------------------------------
# flattening: label / prediction fields -> gradeable sub-keys
# ---------------------------------------------------------------------------

def _norm(value):
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (list, tuple)):
        return tuple(_norm(v) for v in value)
    return value


def _envelope(value):
    if isinstance(value, dict) and "value" in value:
        conf = value.get("conf")
        ok = isinstance(conf, (int, float)) and not isinstance(conf, bool)
        return value.get("value"), (float(conf) if ok else 1.0)
    return value, 1.0


def family(subkey: str) -> str:
    return subkey.split("@", 1)[0].split("#", 1)[0]


def flatten(fields) -> tuple:
    """(flat, conf): sub-key -> normalised value (None = absent) and its conf."""
    flat, conf = {}, {}

    def put(key, value, c):
        flat[key] = value
        conf[key] = c

    for name, raw in (fields or {}).items():
        if name == "players":
            _flatten_players(raw, put)
            continue
        value, c = _envelope(raw)
        if name in ("screen", "shop_open", "stage", "placement", *SCALAR_INT):
            put(name, None if value is None else _norm(value), c)
        elif name == "odds":
            if value is None:
                put("odds", None, c)
            elif isinstance(value, (list, tuple)):
                put("odds", _norm(value), c)
                for i, v in enumerate(value):
                    if v is not None:
                        put(f"odds.slot#{i}", _norm(v), c)
        elif name == "shop":
            _flatten_shop(value, c, put)
        elif name == "scoreboard":
            _flatten_scoreboard(value, c, put)
        elif name == "traits":
            _flatten_traits(value, c, put)
        elif name == "occluders":
            put("occluders", None if value is None else tuple(sorted(_norm(list(value)))), c)
        elif name in ("augment_offers", "item_offers"):
            put(name, None if value is None else _norm(list(value)), c)
    return flat, conf


def _flatten_shop(value, c, put):
    if value is None:
        put("shop", None, c)
        return
    if not isinstance(value, (list, tuple)):
        return
    tokens = []
    for i, slot in enumerate(value):
        if isinstance(slot, dict) and slot.get("name") is not None:
            name, cost = _norm(slot.get("name")), _norm(slot.get("cost"))
            tokens.append(f"{name}/{cost}")
            put(f"shop.name#{i}", name, c)
            if cost is not None:
                put(f"shop.cost#{i}", cost, c)
        else:
            tokens.append(EMPTY_SLOT)
            put(f"shop.name#{i}", EMPTY_SLOT, c)
    put("shop", tuple(tokens), c)


def _flatten_scoreboard(value, c, put):
    if value is None:
        put("scoreboard.rows", None, c)
        return
    if not isinstance(value, (list, tuple)):
        return
    put("scoreboard.rows", len(value), c)
    local = None
    for i, row in enumerate(value):
        if not isinstance(row, dict):
            continue
        if row.get("hp") is not None:
            put(f"scoreboard.hp#{i}", _norm(row["hp"]), c)
        if row.get("level") is not None:
            put(f"scoreboard.level#{i}", _norm(row["level"]), c)
        if row.get("local"):
            local = i
    put("scoreboard.local_row", local, c)


def _flatten_traits(value, c, put):
    if value is None:
        put("traits", None, c)
        put("traits.active", None, c)
        return
    if not isinstance(value, (list, tuple)):
        return
    rows = [t for t in value if isinstance(t, dict) and t.get("name")]
    put("traits", tuple(f"{_norm(t['name'])}:{_norm(t.get('count'))}" for t in rows), c)
    if any("active" in t for t in rows):
        put("traits.active", tuple(_norm(t["name"]) for t in rows if t.get("active")), c)


def _flatten_players(players, put):
    if not isinstance(players, dict):
        return
    for key, player in players.items():
        if not isinstance(player, dict):
            continue
        if "hp" in player:
            hp, hc = _envelope(player["hp"])
            put(f"hp@{key}", None if hp is None else _norm(hp), hc)
        if "board" not in player:
            continue
        board, bc = _envelope(player["board"])
        if board is None:
            for fam in ("board.units", "board.stars", "board.items"):
                put(f"{fam}@{key}", None, bc)
            continue
        if not isinstance(board, (list, tuple)):
            continue
        pieces = [u for u in board if isinstance(u, dict) and u.get("unit")]
        units = [_norm(u["unit"]) for u in pieces]
        put(f"board.units@{key}", tuple(units), bc)
        if any("star" in u for u in pieces):
            put(f"board.stars@{key}", tuple(f"{_norm(u['unit'])}*{_norm(u.get('star'))}"
                                            for u in pieces), bc)
        if any("items" in u for u in pieces):
            put(f"board.items@{key}", tuple(f"{_norm(u['unit'])}:{_norm(it)}" for u in pieces
                                            for it in (u.get("items") or [])), bc)


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------

def _new_row(fam: str) -> dict:
    row = {"kind": "multiset" if fam in MULTISET_FAMILIES else "exact",
           "labelled": 0, "present": 0, "absent": 0, "answered": 0, "correct": 0,
           "wrong": 0, "missed": 0, "absent_ok": 0, "false_present": 0,
           "_confusion": Counter(), "_calib": {}}
    if fam in MULTISET_FAMILIES:
        row.update(tp=0, fp=0, fn=0)
    return row


def _text(value) -> str:
    if value is None:
        return ABSENT
    if isinstance(value, tuple):
        return "|".join(_text(v) for v in value) if value else "()"
    return str(value)


def _bin(conf: float) -> str:
    for lo, hi in CONF_BINS:
        if lo <= conf < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return f"{CONF_BINS[-1][0]:.2f}-{CONF_BINS[-1][1]:.2f}"


def _score(row, gval, pval, conf):
    if gval is None:
        row["absent"] += 1
        if pval is None:
            row["absent_ok"] += 1
        else:
            row["false_present"] += 1
            row["_confusion"][(ABSENT, _text(pval))] += 1
        return
    row["present"] += 1
    if pval is None:
        row["missed"] += 1
        row["_confusion"][(_text(gval), ABSENT)] += 1
        return
    row["answered"] += 1
    if row["kind"] == "multiset":
        g, p = Counter(gval), Counter(pval)
        row["tp"] += sum((g & p).values())
        row["fp"] += sum((p - g).values())
        row["fn"] += sum((g - p).values())
        ok = g == p
        for elem, n in (g - p).items():
            row["_confusion"][(str(elem), ABSENT)] += n
        for elem, n in (p - g).items():
            row["_confusion"][(ABSENT, str(elem))] += n
    else:
        ok = pval == gval
        if not ok:
            row["_confusion"][(_text(gval), _text(pval))] += 1
    row["correct" if ok else "wrong"] += 1
    cell = row["_calib"].setdefault(_bin(conf), [0, 0])
    cell[0] += 1
    cell[1] += int(ok)


def _ratio(num, den):
    return (num / den) if den else None


def _finish(row) -> dict:
    row["accuracy"] = _ratio(row["correct"], row["answered"])
    row["coverage"] = _ratio(row["answered"], row["present"])
    row["absent_accuracy"] = _ratio(row["absent_ok"], row["absent"])
    if row["kind"] == "multiset":
        row["precision"] = _ratio(row["tp"], row["tp"] + row["fp"])
        row["recall"] = _ratio(row["tp"], row["tp"] + row["fn"])
    row["verdict"] = verdict(row)
    pairs = sorted(row.pop("_confusion").items(), key=lambda kv: (-kv[1], kv[0]))
    row["confusion"] = [[g, p, n] for (g, p), n in pairs[:CONFUSION_CAP]]
    calib = row.pop("_calib")
    row["calibration"] = [{"bin": b, "answered": a, "correct": c, "accuracy": _ratio(c, a)}
                          for b, (a, c) in sorted(calib.items())]
    return row


def verdict(row) -> str:
    if not row["present"]:
        return "-"
    if (row["coverage"] or 0.0) < HIDE_COVERAGE:
        return "hide"
    if row["accuracy"] is not None and row["accuracy"] >= SHOW_ACCURACY:
        return "show"
    return "mark"


def _order(fam: str):
    return (FIELD_ORDER.index(fam), fam) if fam in FIELD_ORDER else (len(FIELD_ORDER), fam)


def grade(gt: dict, pred: dict, gate: float = 0.0) -> dict:
    """Grade predictions against ground truth, both {record_key: fields}."""
    rows = {}
    pred = pred or {}
    for key, gt_fields in gt.items():
        gflat, _ = flatten(gt_fields)
        pflat, pconf = flatten(pred.get(key) or {})
        for sub, gval in gflat.items():
            fam = family(sub)
            row = rows.setdefault(fam, _new_row(fam))
            row["labelled"] += 1
            pval, conf = pflat.get(sub), pconf.get(sub, 1.0)
            if pval is not None and conf < gate:
                pval = None
            _score(row, gval, pval, conf)
    fields = {fam: _finish(rows[fam]) for fam in sorted(rows, key=_order)}
    return {"records": len(gt), "gate": gate, "fields": fields}


def accuracy_rows(report: dict, match_id, extractor_version, computed_at=None) -> list:
    """Rows shaped like the store table accuracy(match_id, field, n, correct,
    coverage, extractor_version, computed_at) of docs/TFT_PROGRAM.md 1.5."""
    stamp = time.time() if computed_at is None else computed_at
    return [{"match_id": match_id, "field": fam, "n": row["present"], "correct": row["correct"],
             "coverage": row["coverage"], "extractor_version": extractor_version,
             "computed_at": stamp}
            for fam, row in report["fields"].items() if row["present"]]


# ---------------------------------------------------------------------------
# label documents
# ---------------------------------------------------------------------------

def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


_INT_RANGES = {"timer": (0, 99), "level": (1, 10), "xp_cur": (0, 200), "xp_max": (0, 200),
               "gold": (0, 999), "streak": (0, 99), "buy_xp_cost": (0, 20),
               "reroll_cost": (0, 20), "hud_counter": (0, 99), "hp_local": (-100, 100),
               "traits_more": (0, 30)}


def _check_field(name, value) -> list:
    if value is None:
        return []
    out = []
    if name == "screen" and value not in SCREENS:
        out.append(f"screen {value!r} not in {SCREENS}")
    elif name == "shop_open" and not isinstance(value, bool):
        out.append("shop_open must be a bool")
    elif name == "occluders":
        if not isinstance(value, list) or any(v not in OCCLUDERS for v in value):
            out.append(f"occluders {value!r} must list values from {OCCLUDERS}")
    elif name == "stage":
        if not isinstance(value, str) or not STAGE_RE.fullmatch(value):
            out.append(f"stage {value!r} must look like '3-2'")
    elif name in _INT_RANGES:
        lo, hi = _INT_RANGES[name]
        if not _is_int(value) or not lo <= value <= hi:
            out.append(f"{name} {value!r} must be an int in {lo}..{hi}")
    elif name == "odds":
        if (not isinstance(value, list) or len(value) != 5
                or not all(_is_int(v) and 0 <= v <= 100 for v in value)):
            out.append(f"odds {value!r} must be 5 ints 0..100")
        elif not 99 <= sum(value) <= 101:
            out.append(f"odds {value!r} sums to {sum(value)}, not 100")
    elif name == "shop":
        out.extend(_check_shop(value))
    elif name == "scoreboard":
        out.extend(_check_scoreboard(value))
    elif name == "traits":
        if not isinstance(value, list) or not all(
                isinstance(t, dict) and set(t) <= {"name", "count", "active"}
                and isinstance(t.get("name"), str) and t["name"].strip()
                and _is_int(t.get("count")) and isinstance(t.get("active"), bool)
                for t in value):
            out.append("traits rows must be {name, count, active}")
    elif name in ("augment_offers", "item_offers"):
        if not isinstance(value, list) or not 1 <= len(value) <= 6 or not all(
                isinstance(v, str) and v.strip() for v in value):
            out.append(f"{name} must be a list of 1..6 names")
    elif name == "placement" and not (_is_int(value) and 1 <= value <= 8):
        out.append("placement must be an int 1..8")
    elif name == "players" and not isinstance(value, dict):
        out.append("players must be an object keyed P1..P8")
    return out


def _check_shop(value) -> list:
    if not isinstance(value, list) or len(value) != 5:
        return ["shop must be a list of 5 slots"]
    out = []
    for i, slot in enumerate(value):
        if slot is None:
            continue
        if (not isinstance(slot, dict) or set(slot) != {"name", "cost", "kind"}
                or not isinstance(slot["name"], str) or not slot["name"].strip()
                or not (_is_int(slot["cost"]) and 0 <= slot["cost"] <= 20)
                or slot["kind"] not in SHOP_KINDS):
            out.append(f"shop slot {i} must be {{name, cost 0..20, kind}} or null")
    return out


def _check_scoreboard(value) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        return ["scoreboard must be a list of 1..8 rows"]
    out = []
    for i, row in enumerate(value):
        if (not isinstance(row, dict) or not set(row) <= {"hp", "level", "local"}
                or not (_is_int(row.get("hp")) and -100 <= row["hp"] <= 100)
                or not (_is_int(row.get("level")) and 1 <= row["level"] <= 10)
                or not isinstance(row.get("local", False), bool)):
            out.append(f"scoreboard row {i} must be {{hp -100..100, level 1..10, local?}}")
    locals_ = sum(1 for row in value if isinstance(row, dict) and row.get("local") is True)
    if locals_ != 1:
        out.append(f"scoreboard has {locals_} local rows, expected exactly 1")
    return out


def validate_labels(doc) -> list:
    """Schema problems of a label document (empty list = valid)."""
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA!r}"]
    frames = doc.get("frames")
    if not isinstance(frames, list) or not frames:
        return ["frames must be a non-empty list"]
    problems, seen = [], set()
    for i, row in enumerate(frames):
        name = row.get("frame") if isinstance(row, dict) else None
        if not isinstance(name, str) or not name.strip():
            problems.append(f"frames[{i}]: missing frame name")
            continue
        if name in seen:
            problems.append(f"{name}: duplicate frame")
        seen.add(name)
        sha = row.get("sha256")
        if sha is not None and not (isinstance(sha, str) and SHA_RE.fullmatch(sha)):
            problems.append(f"{name}: sha256 must be 64 lowercase hex")
        labels = row.get("labels")
        if not isinstance(labels, dict):
            problems.append(f"{name}: labels must be an object")
            continue
        for key, value in labels.items():
            if key not in LABEL_FIELDS and key not in GT_ONLY_FIELDS:
                problems.append(f"{name}: unknown field {key!r}")
                continue
            problems.extend(f"{name}: {msg}" for msg in _check_field(key, value))
        cur, top = labels.get("xp_cur"), labels.get("xp_max")
        if _is_int(cur) and _is_int(top) and cur > top:
            problems.append(f"{name}: xp_cur {cur} > xp_max {top}")
    return problems


def _strings(value, path):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, f"{path}[{i}]")


def _keys(value, path):
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}", str(k)
            yield from _keys(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _keys(v, f"{path}[{i}]")


def scrub_problems(doc, vocab) -> list:
    """Privacy guard for a committable label document: no identity key, no UUID,
    no key outside the schema, and every label string from the closed
    vocabulary (set data + the tool's own enums), so no player name can ride in."""
    problems = []
    if not isinstance(doc, dict):
        return ["label document must be an object"]
    for path, key in _keys(doc, "$"):
        if IDENTITY_KEY.search(key):
            problems.append(f"identity key at {path}: {key}")
    for path, text in _strings(doc, "$"):
        if UUID_RE.search(text):
            problems.append(f"UUID-shaped value at {path}")
    problems.extend(f"unexpected top-level key {k!r}" for k in sorted(set(doc) - META_KEYS))
    ver = doc.get("verification")
    if isinstance(ver, dict):
        problems.extend(f"unexpected verification key {k!r}"
                        for k in sorted(set(ver) - VERIFICATION_KEYS))
    for i, row in enumerate(doc.get("frames") or []):
        if not isinstance(row, dict):
            continue
        problems.extend(f"frames[{i}]: unexpected key {k!r}" for k in sorted(set(row) - FRAME_KEYS))
        name = row.get("frame")
        if not (isinstance(name, str) and re.fullmatch(r"game_\d{4}_el\d{4}\.jpg", name)):
            problems.append(f"frames[{i}]: frame name {name!r} is not game_NNNN_elNNNN.jpg")
        for path, text in _strings(row.get("labels") or {}, f"{name}"):
            if path.endswith(".stage") and STAGE_RE.fullmatch(text):
                continue
            if text not in vocab:
                problems.append(f"{path} not in the closed vocabulary: {text!r}")
    return problems


def frame_sha_problems(doc, frames_dir) -> list:
    out = []
    for row in doc.get("frames") or []:
        name = row.get("frame")
        path = Path(frames_dir) / str(name)
        if not path.is_file():
            out.append(f"{name}: missing from the corpus")
            continue
        want = row.get("sha256")
        if want and hashlib.sha256(path.read_bytes()).hexdigest() != want:
            out.append(f"{name}: sha256 mismatch")
    return out


def label_inventory(doc) -> list:
    """(field, frames with a value, frames labelled absent) per label field."""
    have, none = Counter(), Counter()
    for row in doc.get("frames") or []:
        for key, value in (row.get("labels") or {}).items():
            (none if value is None else have)[key] += 1
    return [(f, have[f], none[f]) for f in LABEL_FIELDS if have[f] or none[f]]


# ---------------------------------------------------------------------------
# ground-truth adapters (identity-free by construction)
# ---------------------------------------------------------------------------

def _int_or_none(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def eog_file_players(doc, set_number: int = 18) -> dict:
    """Per-round TFTEoGStats.json -> {"P1": {"hp", "board"}, ...}; P1 = the local
    player (isInteractable), the rest in file order. Only health, boardPieces
    (championName, starLevel, itemNames) and the local flag are read."""
    block = doc.get("statsBlock") if isinstance(doc, dict) else None
    plist = block.get("players") if isinstance(block, dict) else None
    if not isinstance(plist, list):
        return {}
    rows = [p for p in plist if isinstance(p, dict)]
    local = next((p for p in rows if p.get("isInteractable") is True), None)
    ordered = ([local] if local is not None else []) + [p for p in rows if p is not local]
    out = {}
    for n, p in enumerate(ordered, start=1 if local is not None else 2):
        board = []
        for piece in p.get("boardPieces") or []:
            if not isinstance(piece, dict):
                continue
            unit = unit_name(piece.get("championName"), set_number)
            if not unit:
                continue
            items = [item_name(x, set_number) for x in piece.get("itemNames") or []
                     if isinstance(x, str) and x.strip()]
            board.append({"unit": unit, "star": _int_or_none(piece.get("starLevel")),
                          "items": items})
        out[f"P{n}"] = {"hp": _int_or_none(p.get("health")), "board": board}
    return out


def lcu_eog_ground_truth(doc, set_number: int = 18) -> dict:
    """LCU tft-eog-stats -> {"players": {...}, "placement"}. Reads players[]
    (localPlayer carries an empty setCoreName, QA 2026-10-25); health is HP for
    the local player only, so non-local players carry boards but no hp."""
    plist = doc.get("players") if isinstance(doc, dict) else None
    if not isinstance(plist, list):
        return {}
    rows = [p for p in plist if isinstance(p, dict)]
    local = next((p for p in rows if p.get("isLocalPlayer") is True), None)
    ordered = ([local] if local is not None else []) + [p for p in rows if p is not local]
    players = {}
    for n, p in enumerate(ordered, start=1 if local is not None else 2):
        board = []
        for piece in p.get("boardPieces") or []:
            if not isinstance(piece, dict):
                continue
            unit = piece.get("name") or unit_name(piece.get("championId"), set_number)
            if not isinstance(unit, str) or not unit.strip():
                continue
            items = []
            for it in piece.get("items") or []:
                if isinstance(it, dict):
                    label = it.get("name") or item_name(it.get("nameId"), set_number)
                    if label:
                        items.append(label)
            board.append({"unit": unit, "star": _int_or_none(piece.get("level")),
                          "items": items})
        entry = {"board": board}
        if p is local:
            entry["hp"] = _int_or_none(p.get("health"))
        players[f"P{n}"] = entry
    out = {"players": players}
    if local is not None:
        place = _int_or_none(local.get("ffaStanding")) or _int_or_none(local.get("rank"))
        if place:
            out["placement"] = place
    return out


def _read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_eog_snapshots(path, set_number: int = 18) -> list:
    """[(time, players)] sorted by time from a snapshot file or directory."""
    path = Path(path)
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    snaps = []
    for f in files:
        try:
            doc = _read_json(f)
        except (OSError, ValueError):
            continue
        players = eog_file_players(doc, set_number)
        if not players:
            continue
        stamp = doc.get("_rc_captured_at") if isinstance(doc, dict) else None
        if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
            stamp = f.stat().st_mtime
        snaps.append((float(stamp), players))
    snaps.sort(key=lambda s: s[0])
    return snaps


def align_frames(frame_times: dict, snap_times: list, max_age_s: float = 75.0) -> dict:
    """{frame: index of the latest snapshot at or before it, within max_age_s}."""
    order = sorted(range(len(snap_times)), key=snap_times.__getitem__)
    stamps = [snap_times[i] for i in order]
    out = {}
    for name, t in frame_times.items():
        j = bisect.bisect_right(stamps, t) - 1
        if j >= 0 and t - stamps[j] <= max_age_s:
            out[name] = order[j]
    return out


def frame_times(corpus_root) -> dict:
    """{frame file name: capture epoch} from the recorder's frames.jsonl."""
    path = Path(corpus_root) / "frames.jsonl"
    out = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("file"), str) and \
                isinstance(row.get("t"), (int, float)):
            out[Path(row["file"]).name] = float(row["t"])
    return out


# ---------------------------------------------------------------------------
# predictions
# ---------------------------------------------------------------------------

def load_extractor(spec: str):
    mod_name, sep, attr = (spec or "").partition(":")
    if not sep or not mod_name or not attr:
        raise ValueError(f"extractor spec {spec!r} must be 'package.module:function'")
    fn = getattr(importlib.import_module(mod_name), attr)
    if not callable(fn):
        raise ValueError(f"{spec} is not callable")
    return fn


def _arity(fn) -> int:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return 1
    kinds = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    if any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params):
        return 2
    return sum(1 for p in params if p.kind in kinds)


def run_extractor(fn, frames_dir, names, meta=None) -> tuple:
    """({frame: fields}, error count). An extractor that raises on a frame scores
    that frame as all-absent; the run never stops on one bad frame."""
    two = _arity(fn) >= 2
    preds, errors = {}, 0
    for name in names:
        path = str(Path(frames_dir) / name)
        try:
            out = fn(path, (meta or {}).get(name, {})) if two else fn(path)
        except Exception:  # noqa: BLE001 - plug-in boundary: any extractor failure = absent
            errors += 1
            out = {}
        preds[name] = out if isinstance(out, dict) else {}
    return preds, errors


def load_predictions(path) -> dict:
    doc = _read_json(path)
    if isinstance(doc, dict) and isinstance(doc.get("frames"), list):
        return {r["frame"]: (r.get("fields") or r.get("labels") or {})
                for r in doc["frames"] if isinstance(r, dict) and isinstance(r.get("frame"), str)}
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if isinstance(v, dict)}
    raise ValueError("predictions must be {'frames': [...]} or {frame: fields}")


def resolve_frames_dir(corpus):
    if not corpus:
        return None
    root = Path(corpus)
    if (root / "frames").is_dir():
        return root / "frames"
    if root.is_dir() and any(root.glob("game_*.jpg")):
        return root
    return None


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def _f(v) -> str:
    return "-" if v is None else f"{v:.3f}"


def format_table(report: dict, title: str, top: int = 3) -> str:
    head = (f"{'field':<22}{'n_gt':>6}{'absent':>8}{'answer':>8}{'correct':>9}{'acc':>8}"
            f"{'cov':>8}{'abs_ok':>8}{'P':>8}{'R':>8}  verdict")
    lines = [title, head]
    for fam, r in report["fields"].items():
        lines.append(f"{fam:<22}{r['present']:>6}{r['absent']:>8}{r['answered']:>8}"
                     f"{r['correct']:>9}{_f(r['accuracy']):>8}{_f(r['coverage']):>8}"
                     f"{_f(r['absent_accuracy']):>8}{_f(r.get('precision')):>8}"
                     f"{_f(r.get('recall')):>8}  {r['verdict']}")
    confused = [(fam, r["confusion"][:top]) for fam, r in report["fields"].items() if r["confusion"]]
    if confused and top > 0:
        lines.append("")
        lines.append(f"confusions (label -> read, top {top} per field):")
        for fam, pairs in confused:
            shown = "; ".join(f"{g} -> {p} x{n}" for g, p, n in pairs)
            lines.append(f"  {fam}: {shown}")
    return "\n".join(lines)


def _write_json(path: Path, doc: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Grade TFT CV extractors against ground truth "
                                             "(docs/TFT_PROGRAM.md 3.4).")
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS),
                    help="match dir holding frames/ (and frames.jsonl), or a frames dir")
    ap.add_argument("--labels", default=str(DEFAULT_LABELS), help="tft_cv_labels/1 JSON")
    ap.add_argument("--no-labels", action="store_true",
                    help="grade every corpus game frame against --eog / --lcu-eog only")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--extractor", help="package.module:function run on each frame")
    src.add_argument("--predictions", help="predictions JSON instead of running an extractor")
    ap.add_argument("--eog", help="TFTEoGStats.json snapshot file or directory (oracle A)")
    ap.add_argument("--lcu-eog", help="LCU tft-eog-stats JSON (oracle B, final boards)")
    ap.add_argument("--max-age", type=float, default=75.0,
                    help="max seconds between a snapshot and a frame graded against it")
    ap.add_argument("--set", type=int, default=18, dest="set_number")
    ap.add_argument("--gate", type=float, default=0.0, help="conf below this = absent")
    ap.add_argument("--confusion", type=int, default=3, help="confusions shown per field")
    ap.add_argument("--json-out", help="write the full report (incl. accuracy rows) here")
    ap.add_argument("--match-id", help="match id for the accuracy rows")
    ap.add_argument("--extractor-version", default="unversioned")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the frame check fails")
    return ap


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    frames_dir = resolve_frames_dir(args.corpus)
    if frames_dir is None and (args.no_labels or not args.predictions):
        print(f"SKIP: corpus not found: {args.corpus} (frames are local-only, gitignored)")
        return 0

    doc = None
    if args.no_labels:
        gt = {p.name: {} for p in sorted(frames_dir.glob("game_*.jpg"))}
    else:
        try:
            doc = _read_json(args.labels)
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot read labels {args.labels}: {exc}")
            return 2
        problems = validate_labels(doc)
        if problems:
            for msg in problems:
                print(f"LABELS: {msg}")
            return 2
        gt = {row["frame"]: dict(row["labels"]) for row in doc["frames"]}

    frame_failed = False
    if frames_dir is not None and doc is not None:
        sha = frame_sha_problems(doc, frames_dir)
        print(f"{len(gt)} labelled frames ({doc.get('match', '?')}); "
              f"frames ok {len(gt) - len(sha)}/{len(gt)}")
        for msg in sha:
            print(f"FRAME: {msg}")
        frame_failed = bool(sha)

    if not (args.extractor or args.predictions):
        if doc is not None:
            print(f"{'field':<16}{'value':>7}{'null':>7}")
            for name, have, none in label_inventory(doc):
                print(f"{name:<16}{have:>7}{none:>7}")
        return 1 if (args.strict and frame_failed) else 0

    errors = 0
    try:
        if args.extractor:
            preds, errors = run_extractor(load_extractor(args.extractor), frames_dir, list(gt))
        else:
            preds = load_predictions(args.predictions)
    except (ImportError, AttributeError, ValueError, OSError) as exc:
        print(f"ERROR: predictions: {exc}")
        return 2

    if args.eog:
        root = frames_dir.parent if frames_dir is not None and frames_dir.name == "frames" else frames_dir
        times = frame_times(root) if root is not None else {}
        snaps = load_eog_snapshots(args.eog, args.set_number)
        idx = align_frames({k: times[k] for k in gt if k in times}, [s[0] for s in snaps],
                           args.max_age)
        for name, i in idx.items():
            gt[name]["players"] = snaps[i][1]
        print(f"EOG: {len(snaps)} snapshots, {len(idx)}/{len(gt)} frames aligned")

    if args.lcu_eog:
        try:
            final = lcu_eog_ground_truth(_read_json(args.lcu_eog), args.set_number)
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot read LCU EoG {args.lcu_eog}: {exc}")
            return 2
        if final:
            gt["final"] = final
            if "final" not in preds:
                last = [k for k in sorted(preds) if isinstance(preds[k], dict)
                        and preds[k].get("players")]
                if last:
                    src = preds[last[-1]]
                    preds["final"] = {k: src[k] for k in ("players", "placement") if k in src}

    report = grade(gt, preds, gate=args.gate)
    match_id = args.match_id or (doc or {}).get("match") or Path(args.corpus).name
    spec = args.extractor or args.predictions
    frames_graded = sum(1 for k in gt if k != "final")
    title = (f"TFT CV accuracy | {match_id} | {frames_graded} frames | {spec} "
             f"({args.extractor_version}) | gate {args.gate:.2f} | extractor errors {errors}")
    print(format_table(report, title, top=args.confusion))
    if args.json_out:
        stamp = time.time()
        _write_json(Path(args.json_out), {
            "schema": REPORT_SCHEMA, "match_id": match_id,
            "labels": None if args.no_labels else str(args.labels), "predictions": spec,
            "extractor_version": args.extractor_version, "gate": args.gate,
            "frames_graded": frames_graded, "extractor_errors": errors, "computed_at": stamp,
            "fields": report["fields"],
            "accuracy_rows": accuracy_rows(report, match_id, args.extractor_version, stamp),
        })
    return 1 if (args.strict and frame_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
