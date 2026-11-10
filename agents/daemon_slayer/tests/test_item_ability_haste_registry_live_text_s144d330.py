"""S144-D-330..333 - the DS item Ability Haste registry matches the live text it cites.

WHY. ``_item_ability_haste`` copies each item's flat Ability Haste out of the
leading ``<stats>`` block of its DDragon description and names the item in a
row comment. The repo-level guard ``tests/test_item_ability_haste_ddragon_sync.py``
pins every VALUE to live DDragon; nothing pinned the row names, the notes about
the conditional grants the registry leaves out, the docstring's account of what
the derivation ignores, or the counts and stacking rule the prose recites.

* S144-D-330: every row comment starts with the item's live name. The one row
  whose live name is blank (Arena 226660) says so and names its base id.
* S144-D-331: the Imperial Mandate notes cite the live Control grant. Rows 4005
  and 324005 said "+15 cond." while their live text grants 20 Ability Haste for
  Immobilizing abilities (the Arena mirror 224005 grants 15), and 324005 was
  labelled "ARAM" though its live map flag is 11 only.
* S144-D-332: the docstring names every registry row whose description carries
  Ability Haste outside ``<stats>`` (the grants the static lane leaves out on
  purpose), names the Ornn masterworks the drift checker excludes, and states
  the live row count.
* S144-D-333: ``total_item_ability_haste`` said duplicate ids "contribute
  multiplicatively", but the code sums them. The drift checker and the sync
  guard docstrings still recited "220 items" after 226668 made it 221.

MEASURED 2026-11-09 (``data/daemon_slayer/current.txt`` = 16.22.1). Guards plus
docstring / comment fixes; no registry value changes, so scorer output is
byte-identical.
"""

from __future__ import annotations

import inspect
import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from agents.daemon_slayer import _item_ability_haste as ah_mod
from agents.daemon_slayer._item_ability_haste import (
    _ITEM_ABILITY_HASTE,
    item_ability_haste,
    total_item_ability_haste,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA = _REPO_ROOT / "data" / "daemon_slayer"
_DOC = ah_mod.__doc__ or ""
_SOURCE = inspect.getsource(ah_mod)

# Registry rows whose live description grants Ability Haste outside <stats>.
_PASSIVE_AH_ROWS = frozenset(
    {"4005", "224005", "324005", "4636", "6616", "226616", "326616", "6630", "6691", "226691"}
)

_ROW_RE = re.compile(r'^\s*"(\d{4,6})"\s*:\s*[\d.]+\s*,\s*#\s*(.+?)\s*$')
_STATS_RE = re.compile(r"<stats>(.*?)</stats>", re.DOTALL)
_STATS_AH_RE = re.compile(r"<attention>([0-9.]+)</attention>\s*Ability Haste")
_COND_RE = re.compile(r"\+(\d+) cond\.")
_COUNT_RE = re.compile(r"\((\d+)\s+items\)")


@cache
def _items() -> dict[str, Any]:
    patch = (_DATA / "current.txt").read_text(encoding="utf-8").strip()
    raw = json.loads((_DATA / patch / "items.json").read_text(encoding="utf-8"))
    return raw["data"]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _after_stats(item_id: str) -> str:
    desc = _items()[item_id].get("description", "") or ""
    return _plain(desc.split("</stats>", 1)[1]) if "</stats>" in desc else ""


def _passive_ah(item_id: str) -> list[float]:
    return [float(n) for n in re.findall(r"([0-9.]+) Ability Haste", _after_stats(item_id))]


def _live_maps(item_id: str) -> set[str]:
    return {m for m, on in (_items()[item_id].get("maps") or {}).items() if on}


def comment_rows(source: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for line in source.splitlines() if (m := _ROW_RE.match(line))}


def name_problems(rows: dict[str, str], items: dict[str, Any]) -> list[str]:
    problems = []
    for iid, comment in sorted(rows.items()):
        live = (items[iid].get("name") or "").strip()
        if live:
            if not (comment == live or comment.startswith(live + " (")):
                problems.append(f"{iid}: comment {comment!r} does not start with live name {live!r}")
            continue
        base = iid[-4:]
        base_name = (items.get(base, {}).get("name") or "").strip()
        if not (base_name and comment.startswith(base_name) and f"live name blank; base {base}" in comment):
            problems.append(f"{iid}: live name blank and the comment does not say so: {comment!r}")
    return problems


def note_problems(rows: dict[str, str]) -> list[str]:
    problems = []
    for iid, comment in sorted(rows.items()):
        for cited in _COND_RE.findall(comment):
            if float(cited) not in _passive_ah(iid):
                problems.append(f"{iid}: cites +{cited} cond., live passive grants {_passive_ah(iid)}")
        if "ARAM" in comment and "12" not in _live_maps(iid):
            problems.append(f"{iid}: says ARAM, live maps {sorted(_live_maps(iid))}")
    return problems


# ---------------------------------------------------------------- S144-D-330


def test_every_row_has_a_comment() -> None:
    assert set(comment_rows(_SOURCE)) == set(_ITEM_ABILITY_HASTE)


def test_row_comments_start_with_the_live_name() -> None:
    assert name_problems(comment_rows(_SOURCE), _items()) == []


def test_name_checker_catches_planted_defects() -> None:
    planted = dict(comment_rows(_SOURCE))
    planted["3110"] = "Frozen Hearth"
    planted["226660"] = "Bami's Cinder"
    problems = name_problems(planted, _items())
    assert any(p.startswith("3110:") for p in problems)
    assert any(p.startswith("226660:") for p in problems)


# ---------------------------------------------------------------- S144-D-331


def test_conditional_notes_and_mode_labels_match_live() -> None:
    assert note_problems(comment_rows(_SOURCE)) == []


def test_imperial_mandate_notes_name_the_live_control_grant() -> None:
    rows = comment_rows(_SOURCE)
    for iid, grant in (("4005", 20), ("324005", 20), ("224005", 15)):
        assert _passive_ah(iid) == [float(grant)], iid
        assert f"+{grant} cond." in rows[iid], (iid, rows[iid])


def test_note_checker_catches_planted_defects() -> None:
    planted = dict(comment_rows(_SOURCE))
    planted["4005"] = "Imperial Mandate (+15 cond. on immobilize excluded)"
    planted["223110"] = "Frozen Heart (ARAM)"
    problems = note_problems(planted)
    assert any(p.startswith("4005:") for p in problems)
    assert any(p.startswith("223110:") for p in problems)


# ---------------------------------------------------------------- S144-D-332


def test_passive_ah_rows_are_exactly_the_named_set() -> None:
    live = {iid for iid in _ITEM_ABILITY_HASTE if _passive_ah(iid)}
    assert live == _PASSIVE_AH_ROWS


def test_registry_carries_the_stats_value_not_the_passive_grant() -> None:
    for iid in sorted(_PASSIVE_AH_ROWS):
        block = _STATS_RE.search(_items()[iid]["description"]).group(1)
        assert _ITEM_ABILITY_HASTE[iid] == float(_STATS_AH_RE.search(block).group(1)), iid


def test_docstring_names_every_passive_ah_row() -> None:
    missing = sorted(iid for iid in _PASSIVE_AH_ROWS if iid not in _DOC)
    assert missing == []


def test_docstring_names_the_ornn_exclusions() -> None:
    ornn = sorted(
        iid
        for iid, row in _items().items()
        if "<ornnBonus>" in (row.get("description") or "")
        and (m := _STATS_RE.search(row["description"]))
        and "Ability Haste" in m.group(1)
    )
    assert ornn, "no Ornn masterwork carries Ability Haste in <stats>"
    assert not set(ornn) & set(_ITEM_ABILITY_HASTE)
    assert "Ornn" in _DOC
    assert [iid for iid in ornn if iid not in _DOC] == []


def test_docstring_states_the_live_row_count() -> None:
    assert f"{len(_ITEM_ABILITY_HASTE)} rows at" in _DOC


# ---------------------------------------------------------------- S144-D-333


def test_duplicate_ids_add_and_the_docstring_says_so() -> None:
    doc = total_item_ability_haste.__doc__ or ""
    assert "multiplicatively" not in doc
    assert "additively" in doc
    assert total_item_ability_haste(["3110", "3110"]) == 2 * item_ability_haste("3110")


def test_checker_and_guard_docstrings_recite_the_live_count() -> None:
    for rel in ("ops/audit/item_ah_drift_check.py", "tests/test_item_ability_haste_ddragon_sync.py"):
        text = (_REPO_ROOT / rel).read_text(encoding="utf-8")
        doc = text.split('"""', 2)[1]
        counts = [int(n) for n in _COUNT_RE.findall(doc)]
        assert counts, f"{rel} recites no item count"
        assert counts == [len(_ITEM_ABILITY_HASTE)] * len(counts), (rel, counts)
