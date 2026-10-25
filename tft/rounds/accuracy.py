"""tft/rounds/accuracy.py - post-match per-field accuracy of the per-round
store against ground truth (docs/TFT_PROGRAM.md section 3.4 oracle B, slice
TFT-08).

Oracle B compares the LAST RESOLVED ROUND with the post-match ground truth that
tft/rounds/ground_truth.py attached (gt_board / gt_player): final boards of all
8, final level, final gold and placement. Fields, one accuracy row each:

  final_board_units  per player: the multiset of champion apiNames on board
  final_board_stars  per player: the multiset of (apiName, star)
  final_board_items  per player: the multiset of (apiName, sorted items)
  final_level        local player: the last round's `level` vs gt level
  final_gold         local player: the last round's `gold_end` vs gt gold_left
  placement          local player: match.placement vs gt placement - graded
                     only when the match placement came from a graded source
                     (the bridge's own lcu placement IS the oracle)

A player's predicted board is that player's unit_obs rows (zone 'board') in
the latest round that has any, preferring planning_end, then planning_start,
then combat. Only rows whose src is a GRADED source count (vision / derived;
GRADED_SRCS): eog_file and lcu rows are oracles and manual_label rows are
labels, so grading them would score a source against itself. A row below
`min_conf` counts as not answered.

Row shape (the store's accuracy table): n = cases with ground truth, correct =
answered and equal, coverage = answered / n. Accuracy on the answered cases is
correct / (coverage * n). A field with no ground truth writes no row.

ASCII-only, LLM-free, stdlib only.
"""
from __future__ import annotations

import time
from collections import Counter
from typing import Any, Iterable, Optional

from tft.rounds.ground_truth import GT_SOURCE_ORDER

GRADED_SRCS = frozenset({"ocr", "icon", "geom", "derived"})
PHASE_ORDER = ("planning_end", "planning_start", "combat")
BOARD_FIELDS = ("final_board_units", "final_board_stars", "final_board_items")
FIELDS = BOARD_FIELDS + ("final_level", "final_gold", "placement")


def _int(v) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _ok(src, conf, srcs, min_conf) -> bool:
    if src not in srcs:
        return False
    return conf is None or (isinstance(conf, (int, float)) and conf >= min_conf)


def _gt_boards(doc: dict) -> dict:
    """{player_key: [gt_board rows]} from each player's most trusted source."""
    by_key: dict = {}
    for r in doc.get("gt_board") or []:
        by_key.setdefault(r.get("player_key"), []).append(r)
    out = {}
    for key, rows in by_key.items():
        for src in GT_SOURCE_ORDER:
            picked = [r for r in rows if r.get("source") == src]
            if picked:
                out[key] = picked
                break
    return out


def _last_boards(rounds: Iterable, srcs, min_conf) -> dict:
    """{player_key: [unit rows]} - each player's board in their latest round."""
    best: dict = {}
    for bundle in rounds or []:
        seq = _int(bundle.get("round_seq")) if isinstance(bundle, dict) else None
        if seq is None:
            continue
        per: dict = {}
        for u in bundle.get("units") or []:
            if (isinstance(u, dict) and u.get("zone") == "board" and u.get("phase") in PHASE_ORDER
                    and _ok(u.get("src"), u.get("conf"), srcs, min_conf)):
                per.setdefault(u.get("player_key"), {}).setdefault(u["phase"], []).append(u)
        for key, phases in per.items():
            phase = next(p for p in PHASE_ORDER if p in phases)
            if key not in best or seq > best[key][0]:
                best[key] = (seq, phases[phase])
    return {k: v[1] for k, v in best.items()}


def _last_value(rounds: Iterable, name: str, srcs, min_conf) -> Any:
    seq_val = None
    for bundle in rounds or []:
        if not isinstance(bundle, dict):
            continue
        seq, val = _int(bundle.get("round_seq")), bundle.get(name)
        if seq is None or val is None:
            continue
        if not _ok(bundle.get(name + "_src"), bundle.get(name + "_conf"), srcs, min_conf):
            continue
        if seq_val is None or seq > seq_val[0]:
            seq_val = (seq, val)
    return None if seq_val is None else seq_val[1]


def _items(r) -> tuple:
    items = r.get("items")
    return tuple(sorted(i for i in items if isinstance(i, str))) if isinstance(items, list) else ()


_BOARD_KEYS = {
    "final_board_units": lambda r: r.get("champion_api"),
    "final_board_stars": lambda r: (r.get("champion_api"), r.get("star")),
    "final_board_items": lambda r: (r.get("champion_api"), _items(r)),
}


def _row(field: str, n: int, answered, correct) -> dict:
    answered, correct = int(answered), int(correct)      # bools from comparisons -> ints
    return {"field": field, "n": n, "correct": correct, "coverage": answered / n if n else 0.0}


def final_accuracy(doc: Optional[dict], *, srcs=GRADED_SRCS, min_conf: float = 0.0) -> list:
    """Accuracy rows for one store match document (RoundStore.get_match with
    its rounds); [] when there is no document."""
    if not isinstance(doc, dict) or not isinstance(doc.get("match"), dict):
        return []
    rounds = doc.get("rounds") or []
    truth = _gt_boards(doc)
    pred = _last_boards(rounds, srcs, min_conf)
    rows = []
    if truth:
        for field, keyfn in _BOARD_KEYS.items():
            answered = correct = 0
            for key, gt_rows in truth.items():
                if key not in pred:
                    continue
                answered += 1
                correct += int(Counter(map(keyfn, pred[key])) == Counter(map(keyfn, gt_rows)))
            rows.append(_row(field, len(truth), answered, correct))
    local = next((p.get("player_key") for p in doc.get("players") or [] if p.get("is_local")), None)
    gt_local = next((p for p in doc.get("gt_player") or [] if p.get("player_key") == local), None) \
        if local is not None else None
    if gt_local:
        for field, gt_name, value in (
                ("final_level", "level", _last_value(rounds, "level", srcs, min_conf)),
                ("final_gold", "gold_left", _last_value(rounds, "gold_end", srcs, min_conf))):
            if gt_local.get(gt_name) is not None:
                rows.append(_row(field, 1, value is not None, value == gt_local[gt_name]))
        m = doc["match"]
        if gt_local.get("placement") is not None and m.get("placement_src") in srcs:
            p = m.get("placement") if _ok(m.get("placement_src"), m.get("placement_conf"),
                                         srcs, min_conf) else None
            rows.append(_row("placement", 1, p is not None, p == gt_local["placement"]))
    return rows


def write_final_accuracy(store, match_id, *, extractor_version: str = "", srcs=GRADED_SRCS,
                         min_conf: float = 0.0, computed_at: Optional[float] = None) -> list:
    """Compute the rows for one stored match and write them (store.put_accuracy,
    enqueued; flush to wait). Returns the rows written ([] when nothing to grade)."""
    rows = final_accuracy(store.get_match(match_id), srcs=srcs, min_conf=min_conf)
    stamp = time.time() if computed_at is None else computed_at
    rows = [dict(r, extractor_version=extractor_version or None, computed_at=stamp) for r in rows]
    if rows:
        store.put_accuracy(match_id, rows)
    return [dict(r, extractor_version=extractor_version) for r in rows]
