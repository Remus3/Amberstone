"""S144-D-207..210 - the per-champion WIN-anchored DS tables name only live
champions and live items, and every row can reach the seam it feeds.

WHY. Six hand-built / rewind-built tables in ``agents/daemon_slayer/`` key a
per-champion row by champion and are read with a plain dict ``.get``:

* ``archetype_weights.json`` - ``hybrid.get_weights_for`` (alpha, beta)
* ``kit_axis_item_credit.json`` - ``kit_axis_credit`` (DSP11 seam)
* ``survivability_item_credit.json`` / ``_tank`` / ``_enchanter`` -
  ``survivability_credit`` (RF1 / RF3 / RF2 seams)
* ``marksman_offclass_exempt.json`` - ``rank._offclass_win_exemptions``

A row whose champion key, item id or item name is not live is SILENTLY inert:
no error, no warning, and the seam tests that pin one champion stay green.

* S144-D-207: every champion key is a DDragon roster id. The display-name
  fallback in the kit-axis / survivability / exemption loaders needs the
  caller's ``champ_rec``, and ``burst.py`` calls ``kit_axis_item_ids`` with
  the id alone, while ``hybrid.get_weights_for`` has no fallback at all; so
  the id is the only spelling every caller reaches.
* S144-D-208: every item row in the kit-axis and survivability tables names
  a live item id whose live name equals the row's name (``rank.py`` un-strips
  the kit-axis items by NAME and floats them by ID, so a drifted pair splits
  the seam), carries finite stats, meets the table's own ``min_rewind_n``,
  and is actually served by the module's loader for that champion.
* S144-D-209: every marksman off-class exemption is reachable - the champion
  is a ranged marksman at the live snapshot (the only class the deny set
  fires for) and every exempt name is in ``OFFCLASS_MARKSMAN_ITEM_NAMES``
  and is a live item name (the exemption is a set difference, so a name
  outside the deny set exempts nothing).
* S144-D-210: every archetype weight pair, and the default, is two finite
  non-negative numbers (bool refused). The table meta calls alpha + beta = 1.0 the
  recommended convention; every row measured holds it, so it is pinned here
  and a deliberate departure edits this test with its reason.

MEASURED 2026-11-09 (live snapshot, patch 16.22.1, ENGINE 1.291.0): 20 + 6 +
9 + 2 + 1 + 5 champion rows, ZERO dangling keys, ZERO dead item ids, ZERO
id/name drifts, ZERO rows under ``min_rewind_n``, ZERO unreachable
exemptions, every weight pair sums to 1.0. These guards are preventive.
Each checker is also run on a planted defect below, so an empty or blind
checker cannot pass.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path
from typing import Callable

from agents.daemon_slayer import hybrid, kit_axis_credit, rank, survivability_credit
from agents.daemon_slayer.data_loader import DataSnapshot

# table label -> (path the module reads, the module's per-champion id lookup)
_ITEM_TABLES: dict[str, tuple[Path, Callable[[str], frozenset[str]]]] = {
    "kit_axis": (kit_axis_credit._TABLE_PATH, kit_axis_credit.kit_axis_item_ids),
    "survivability": (
        survivability_credit._TABLE_PATH,
        survivability_credit.survivability_item_ids,
    ),
    "survivability_tank": (
        survivability_credit._TANK_TABLE_PATH,
        survivability_credit.survivability_item_ids_tank,
    ),
    "survivability_enchanter": (
        survivability_credit._ENCHANTER_TABLE_PATH,
        survivability_credit.survivability_item_ids_enchanter,
    ),
}
_WEIGHTS_PATH = hybrid._ARCHETYPE_WEIGHTS_PATH
_EXEMPT_PATH = rank._OFFCLASS_EXEMPT_PATH


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dangling_champion_keys(champions: dict, roster: frozenset[str]) -> list[str]:
    return sorted(k for k in champions if k not in roster)


def _bad_item_rows(table: dict, items: dict) -> list[str]:
    """Every defect in a kit-axis / survivability table, one line each."""
    out: list[str] = []
    min_n = (table.get("_meta") or {}).get("min_rewind_n")
    for champ, entry in (table.get("champions") or {}).items():
        rows = (entry or {}).get("items") or []
        if not rows:
            out.append(f"{champ}: no item rows")
        for row in rows:
            iid = str(row.get("id"))
            name = row.get("name")
            live = items.get(iid)
            if live is None:
                out.append(f"{champ}: dead item id {iid} ({name})")
            elif live.get("name") != name:
                out.append(
                    f"{champ}: id {iid} is {live.get('name')!r} live, row says {name!r}"
                )
            for key in ("lift", "rewind_n", "rewind_wr"):
                val = row.get(key)
                if (
                    isinstance(val, bool)
                    or not isinstance(val, (int, float))
                    or not math.isfinite(val)
                ):
                    out.append(f"{champ}: id {iid} {key}={val!r} not finite")
            wr = row.get("rewind_wr")
            if isinstance(wr, (int, float)) and not 0.0 <= wr <= 100.0:
                out.append(f"{champ}: id {iid} rewind_wr={wr!r} outside [0, 100]")
            n = row.get("rewind_n")
            if isinstance(min_n, int) and isinstance(n, (int, float)) and n < min_n:
                out.append(f"{champ}: id {iid} rewind_n={n} under min_rewind_n={min_n}")
    return out


def _unreachable_exemptions(
    exemptions: dict,
    champions: dict,
    deny: frozenset[str],
    live_names: frozenset[str],
) -> list[str]:
    out: list[str] = []
    for champ, names in exemptions.items():
        if not rank._is_ranged_marksman(champions.get(champ)):
            out.append(f"{champ}: not a ranged marksman, the deny set never fires")
        if not names:
            out.append(f"{champ}: empty exemption list")
        for name in names or ():
            if name not in deny:
                out.append(f"{champ}: {name!r} is not in the off-class deny set")
            if name not in live_names:
                out.append(f"{champ}: {name!r} is not a live item name")
    return out


def _bad_weight_pairs(table: dict) -> list[str]:
    out: list[str] = []
    pairs = {"default": table.get("default")}
    pairs.update(table.get("champions") or {})
    for champ, pair in pairs.items():
        if not isinstance(pair, list) or len(pair) != 2:
            out.append(f"{champ}: {pair!r} is not an (alpha, beta) pair")
            continue
        if not all(
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(v)
            and v >= 0.0
            for v in pair
        ):
            out.append(f"{champ}: {pair!r} is not two finite non-negative floats")
            continue
        if not math.isclose(pair[0] + pair[1], 1.0, abs_tol=1e-9):
            out.append(f"{champ}: {pair!r} breaks the alpha + beta = 1.0 convention")
    return out


class PerChampionWinTablesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        snap = DataSnapshot.load()
        cls.champions = snap.champions
        cls.roster = frozenset(snap.champions)
        cls.items = snap.items
        cls.live_names = frozenset(
            rec.get("name") for rec in snap.items.values() if isinstance(rec, dict)
        )
        cls.item_tables = {label: _read(p) for label, (p, _) in _ITEM_TABLES.items()}
        cls.weights = _read(_WEIGHTS_PATH)
        cls.exempt = _read(_EXEMPT_PATH)
        kit_axis_credit.reset_cache()
        survivability_credit.reset_cache()

    def test_enumeration_is_populated(self) -> None:
        # An empty roster, item map or table must not pass the checks below.
        self.assertGreater(len(self.roster), 150)
        self.assertGreater(len(self.items), 300)
        for label, table in self.item_tables.items():
            self.assertTrue(table.get("champions"), label)
            # The min_rewind_n check below is skipped without this.
            self.assertIsInstance((table.get("_meta") or {}).get("min_rewind_n"), int, label)
        self.assertGreaterEqual(len(self.weights.get("champions") or {}), 10)
        self.assertGreaterEqual(len(self.exempt.get("champions") or {}), 3)

    # S144-D-207
    def test_every_champion_key_is_a_roster_id(self) -> None:
        tables = {label: t["champions"] for label, t in self.item_tables.items()}
        tables["archetype_weights"] = self.weights["champions"]
        tables["marksman_offclass_exempt"] = self.exempt["champions"]
        bad = {
            label: _dangling_champion_keys(champs, self.roster)
            for label, champs in tables.items()
        }
        self.assertEqual({k: v for k, v in bad.items() if v}, {})

    def test_a_display_name_key_is_caught(self) -> None:
        # Wukong is the display name; the DDragon id is MonkeyKing.
        self.assertIn("MonkeyKing", self.roster)
        self.assertEqual(
            _dangling_champion_keys({"Wukong": [], "MonkeyKing": []}, self.roster),
            ["Wukong"],
        )

    # S144-D-208
    def test_every_item_row_is_live_and_sane(self) -> None:
        bad = {
            label: _bad_item_rows(table, self.items)
            for label, table in self.item_tables.items()
        }
        self.assertEqual({k: v for k, v in bad.items() if v}, {})

    def test_every_item_row_is_served_by_its_loader(self) -> None:
        for label, (_, lookup) in _ITEM_TABLES.items():
            for champ, entry in self.item_tables[label]["champions"].items():
                want = frozenset(str(r["id"]) for r in entry["items"])
                with self.subTest(table=label, champion=champ):
                    self.assertEqual(lookup(champ), want)

    def test_item_row_checker_catches_each_planted_defect(self) -> None:
        live_id, live = next(
            (i, r) for i, r in self.items.items() if isinstance(r, dict) and r.get("name")
        )
        dead_id = "999999"
        self.assertNotIn(dead_id, self.items)
        good = {"lift": 1.0, "rewind_n": 20, "rewind_wr": 50.0}
        table = {
            "_meta": {"min_rewind_n": 15},
            "champions": {
                "A": {"items": [dict(good, id=dead_id, name="Gone")]},
                "B": {"items": [dict(good, id=live_id, name=live["name"] + " (old)")]},
                "C": {"items": [dict(good, id=live_id, name=live["name"], lift=math.nan)]},
                "D": {"items": [dict(good, id=live_id, name=live["name"], rewind_n=3)]},
                "E": {"items": [dict(good, id=live_id, name=live["name"], rewind_wr=150.0)]},
                "F": {"items": []},
                "G": {"items": [dict(good, id=live_id, name=live["name"])]},
            },
        }
        hits = _bad_item_rows(table, self.items)
        flagged = {line.split(":", 1)[0] for line in hits}
        self.assertEqual(flagged, {"A", "B", "C", "D", "E", "F"}, hits)

    # S144-D-209
    def test_every_marksman_exemption_is_reachable(self) -> None:
        self.assertEqual(
            _unreachable_exemptions(
                self.exempt["champions"],
                self.champions,
                rank.OFFCLASS_MARKSMAN_ITEM_NAMES,
                self.live_names,
            ),
            [],
        )

    def test_exemption_checker_catches_each_planted_defect(self) -> None:
        marksman = next(iter(self.exempt["champions"]))
        in_deny = next(iter(sorted(rank.OFFCLASS_MARKSMAN_ITEM_NAMES & self.live_names)))
        not_deny = next(
            n for n in sorted(self.live_names) if n not in rank.OFFCLASS_MARKSMAN_ITEM_NAMES
        )
        # A melee fighter: the deny set never fires for it.
        self.assertFalse(rank._is_ranged_marksman(self.champions["Darius"]))
        hits = _unreachable_exemptions(
            {
                "Darius": [in_deny],
                marksman: [not_deny, "No Such Item"],
            },
            self.champions,
            rank.OFFCLASS_MARKSMAN_ITEM_NAMES,
            self.live_names,
        )
        self.assertEqual(
            hits,
            [
                "Darius: not a ranged marksman, the deny set never fires",
                f"{marksman}: {not_deny!r} is not in the off-class deny set",
                f"{marksman}: 'No Such Item' is not in the off-class deny set",
                f"{marksman}: 'No Such Item' is not a live item name",
            ],
        )

    # S144-D-210
    def test_every_archetype_weight_pair_is_sane(self) -> None:
        self.assertEqual(_bad_weight_pairs(self.weights), [])

    def test_weights_are_served_as_tabled(self) -> None:
        # Read the shipped file, not a cache another test may have overridden.
        saved = hybrid._WEIGHTS_CACHE
        hybrid._WEIGHTS_CACHE = None
        try:
            for champ, pair in self.weights["champions"].items():
                with self.subTest(champion=champ):
                    self.assertEqual(hybrid.get_weights_for(champ), tuple(pair))
        finally:
            hybrid._WEIGHTS_CACHE = saved

    def test_weight_checker_catches_each_planted_defect(self) -> None:
        hits = _bad_weight_pairs(
            {
                "default": [0.5, 0.5],
                "champions": {
                    "A": [0.5],
                    "B": [math.inf, 0.0],
                    "C": [-0.2, 1.2],
                    "D": [0.7, 0.7],
                    "E": [True, 0.0],
                    "F": [0.6, 0.4],
                },
            }
        )
        self.assertEqual(
            {line.split(":", 1)[0] for line in hits}, {"A", "B", "C", "D", "E"}, hits
        )


if __name__ == "__main__":
    unittest.main()
