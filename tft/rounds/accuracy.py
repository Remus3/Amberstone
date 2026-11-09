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
`min_conf` counts as not answered: a board with one such row is not answered
as a whole, and a value below it is not answered - the gate lowers coverage,
never accuracy, and never reaches back to an older round (section 3.4:
coverage = rounds with a value at or above the gate). A confidence must be
None or a finite number (a bool is not one).

The local fields need exactly ONE local player key (is_local exactly 1 / True,
as in milestones._local_key; a row without a usable text key is ignored); two
local keys grade no local field.

Row shape (the store's accuracy table): n = cases with ground truth, correct =
answered and equal, coverage = answered / n. Accuracy on the answered cases is
correct / (coverage * n). A field with no ground truth writes no row.

final_accuracy never raises on a malformed document: a non-dict row or a
non-list section is skipped, and an unhashable value compares equal to
nothing (that board is answered and wrong, the match is still graded).

ASCII-only, LLM-free, stdlib only.
"""
from __future__ import annotations

import math
import time
from collections import Counter
from typing import Any, Iterable, Optional

from tft.rounds.ground_truth import GT_SOURCE_ORDER

GRADED_SRCS = frozenset({"ocr", "icon", "geom", "derived"})
PHASE_ORDER = ("planning_end", "planning_start", "combat")
BOARD_FIELDS = ("final_board_units", "final_board_stars", "final_board_items")
FIELDS = (*BOARD_FIELDS, "final_level", "final_gold", "placement")


def _int(v) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _seq(v) -> tuple:
    """A store section (list of rows) as a tuple; anything else is empty."""
    return tuple(v) if isinstance(v, (list, tuple)) else ()


def _dicts(v) -> list:
    return [r for r in _seq(v) if isinstance(r, dict)]


def _key(v) -> Optional[str]:
    """A usable player_key (the schema's TEXT NOT NULL), or None."""
    return v if isinstance(v, str) and v else None


def _src_ok(src, srcs) -> bool:
    return isinstance(src, str) and src in srcs


def _conf_ok(conf, min_conf) -> bool:
    if conf is None:
        return True
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        return False
    try:
        return math.isfinite(conf) and conf >= min_conf
    except OverflowError:                 # an int too large for a float
        return False


def _ok(src, conf, srcs, min_conf) -> bool:
    return _src_ok(src, srcs) and _conf_ok(conf, min_conf)


def _atom(v):
    """v when hashable; unhashable junk becomes a fresh object, equal to nothing."""
    try:
        hash(v)
    except TypeError:
        return object()
    return v


def _local_key(players) -> Optional[str]:
    """The one local player's key; None when there is none or more than one."""
    keys = {_key(p.get("player_key")) for p in _dicts(players)
            if p.get("is_local") is True or _int(p.get("is_local")) == 1}
    keys.discard(None)
    return next(iter(keys)) if len(keys) == 1 else None


def _gt_boards(doc: dict) -> dict:
    """{player_key: [gt_board rows]} from each player's most trusted source."""
    by_key: dict = {}
    for r in _dicts(doc.get("gt_board")):
        key = _key(r.get("player_key"))
        if key is not None:
            by_key.setdefault(key, []).append(r)
    out = {}
    for key, rows in by_key.items():
        for src in GT_SOURCE_ORDER:
            picked = [r for r in rows if r.get("source") == src]
            if picked:
                out[key] = picked
                break
    return out


def _last_boards(rounds: Iterable, srcs, min_conf) -> dict:
    """{player_key: [unit rows]} - each player's board in their latest round
    with a graded board row. A player whose board there has a row below
    min_conf is left out (not answered), never read from an older round."""
    best: dict = {}
    for bundle in _dicts(rounds):
        seq = _int(bundle.get("round_seq"))
        if seq is None:
            continue
        per: dict = {}
        for u in _dicts(bundle.get("units")):
            phase, key = u.get("phase"), _key(u.get("player_key"))
            if (key is not None and u.get("zone") == "board" and phase in PHASE_ORDER
                    and _src_ok(u.get("src"), srcs)):
                per.setdefault(key, {}).setdefault(phase, []).append(u)
        for key, phases in per.items():
            phase = next(p for p in PHASE_ORDER if p in phases)
            if key not in best or seq > best[key][0]:
                best[key] = (seq, phases[phase])
    return {k: rows for k, (_, rows) in best.items()
            if all(_conf_ok(r.get("conf"), min_conf) for r in rows)}


def _last_value(rounds: Iterable, name: str, srcs, min_conf) -> Any:
    """`name` in the latest round with a graded value; None when there is
    none or that value is below min_conf (never an older round's value)."""
    best = None
    for bundle in _dicts(rounds):
        seq, val = _int(bundle.get("round_seq")), bundle.get(name)
        if seq is None or val is None or not _src_ok(bundle.get(name + "_src"), srcs):
            continue
        if best is None or seq > best[0]:
            best = (seq, val, bundle.get(name + "_conf"))
    return None if best is None or not _conf_ok(best[2], min_conf) else best[1]


def _items(r) -> tuple:
    items = r.get("items")
    return tuple(sorted(i for i in items if isinstance(i, str))) if isinstance(items, list) else ()


_BOARD_KEYS = {
    "final_board_units": lambda r: _atom(r.get("champion_api")),
    "final_board_stars": lambda r: (_atom(r.get("champion_api")), _atom(r.get("star"))),
    "final_board_items": lambda r: (_atom(r.get("champion_api")), _items(r)),
}


def _row(field: str, n: int, answered, correct) -> dict:
    answered, correct = int(answered), int(correct)      # bools from comparisons -> ints
    return {"field": field, "n": n, "correct": correct, "coverage": answered / n if n else 0.0}


def final_accuracy(doc: Optional[dict], *, srcs=GRADED_SRCS, min_conf: float = 0.0) -> list:
    """Accuracy rows for one store match document (RoundStore.get_match with
    its rounds); [] when there is no document."""
    if not isinstance(doc, dict) or not isinstance(doc.get("match"), dict):
        return []
    rounds = doc.get("rounds")
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
    local = _local_key(doc.get("players"))
    gt_local = next((p for p in _dicts(doc.get("gt_player")) if p.get("player_key") == local), None) \
        if local is not None else None
    if gt_local:
        for field, gt_name, value in (
                ("final_level", "level", _last_value(rounds, "level", srcs, min_conf)),
                ("final_gold", "gold_left", _last_value(rounds, "gold_end", srcs, min_conf))):
            if gt_local.get(gt_name) is not None:
                rows.append(_row(field, 1, value is not None, value == gt_local[gt_name]))
        m = doc["match"]
        if gt_local.get("placement") is not None and _src_ok(m.get("placement_src"), srcs):
            p = m.get("placement") if _ok(m.get("placement_src"), m.get("placement_conf"),
                                         srcs, min_conf) else None
            rows.append(_row("placement", 1, p is not None, p == gt_local["placement"]))
    return rows


def write_final_accuracy(store, match_id, *, extractor_version: str = "", srcs=GRADED_SRCS,
                         min_conf: float = 0.0, computed_at: Optional[float] = None) -> list:
    """Compute the rows for one stored match and write them (store.put_accuracy,
    enqueued; flush to wait). Returns the rows written ([] when nothing to
    grade, or when the store refused them - put_accuracy returned False)."""
    rows = final_accuracy(store.get_match(match_id), srcs=srcs, min_conf=min_conf)
    stamp = time.time() if computed_at is None else computed_at
    rows = [dict(r, extractor_version=extractor_version or None, computed_at=stamp) for r in rows]
    if rows and not store.put_accuracy(match_id, rows):
        return []
    return [dict(r, extractor_version=extractor_version) for r in rows]
