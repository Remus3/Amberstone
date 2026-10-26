"""Guard (RM-917): the DS module-map counts are re-derived from data, never recited.

``docs/DAEMON_SLAYER.md`` described ``enchanter_items.json`` as a "9 entries"
registry in two module-map rows (``hps.py`` and the data-file row). That was
true through patch 16.12.1 only: 16.13.1 added Forbidden Idol, and 16.14.1 added
Dawncore, Whispering Circlet and the R143 mirror rows (``22xxxx`` = the
Arena map-30 copy, ``32xxxx`` = the map-11-only copy), so every snapshot 16.14.1 .. 16.21.1 carries 34 rows
over 12 bare SR items. No test read either number, so the prose sat wrong in
every snapshot dir from 16.13.1 on. ``hps.py``'s own docstring said 10, a third value.

``tests/test_docs_ds_item_coverage_drift.py`` (RM-203) already re-derives the
item-coverage paragraph; this guard does the same for every other count the
module map states beside a data file: the enchanter registry, the bruiser
alpha/beta table, the ability snapshot, the spell cast-rate table, the
``ITEM_EFFECTS`` registry row, and the four per-champion override registries
(counted from their nested ``champions`` key, never the file's top level).
Each number is measured from the snapshot named by ``current.txt`` (or the
unversioned file the engine reads), so a patch refresh that moves one fails
here instead of rotting. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agents.daemon_slayer._effects_data import ITEM_EFFECTS

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_HPS = _REPO_ROOT / "agents" / "daemon_slayer" / "hps.py"
_DS_PKG = _REPO_ROOT / "agents" / "daemon_slayer"
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"

_MIRROR_PREFIXES = ("22", "32")
_REGISTRIES = {
    "block_index": "champion_block_index.json",
    "max_priority": "champion_max_priority.json",
    "combo_sequences": "champion_combo_sequences.json",
    "form_index": "champion_form_index.json",
}


def _patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _doc() -> str:
    return _DOC.read_text(encoding="utf-8")


def _row(prefix: str) -> str:
    rows = [ln for ln in _doc().splitlines() if ln.startswith(prefix)]
    assert len(rows) == 1, f"expected exactly one module-map row starting {prefix!r}, got {len(rows)}"
    return rows[0]


def _match(pattern: str, text: str, what: str) -> re.Match:
    m = re.search(pattern, text)
    assert m is not None, f"{what}: prose shape {pattern!r} not found - the count must be stated, not dropped"
    return m


def _enchanter_items() -> dict:
    return _load(_DATA_ROOT / _patch() / "enchanter_items.json")["items"]


def _bare_and_mirror_ids(items: dict) -> tuple[set, set]:
    bare = {i for i in items if len(i) <= 4}
    mirror = {i for i in items if len(i) == 6 and i[:2] in _MIRROR_PREFIXES}
    return bare, mirror


# --- enchanter registry -----------------------------------------------------


def test_enchanter_ids_partition_into_bare_and_mirror_rows():
    """Precondition for the counts below: every row is a bare id or a mirror of one."""
    items = _enchanter_items()
    bare, mirror = _bare_and_mirror_ids(items)
    assert bare, "no bare SR enchanter ids - the registry is empty"
    assert bare | mirror == set(items), f"unclassified ids: {sorted(set(items) - bare - mirror)}"
    orphans = sorted(i for i in mirror if i[2:] not in bare)
    assert orphans == [], f"mirror rows with no bare SR row: {orphans}"


def test_enchanter_data_row_counts_match_snapshot():
    row = _row("| `data/daemon_slayer/<patch>/enchanter_items.json` |")
    m = _match(
        r"(\d+) rows at patch (\d+\.\d+\.\d+): (\d+) bare SR items plus (\d+) mirror rows",
        row,
        "enchanter_items.json row",
    )
    items = _enchanter_items()
    bare, mirror = _bare_and_mirror_ids(items)
    assert m.group(2) == _patch()
    assert (int(m.group(1)), int(m.group(3)), int(m.group(4))) == (len(items), len(bare), len(mirror))


def test_hps_row_counts_and_names_every_bare_enchanter_item():
    row = _row("| `hps.py` |")
    m = _match(r"\((\d+) bare SR enchanter items hand-curated", row, "hps.py row")
    items = _enchanter_items()
    bare, _ = _bare_and_mirror_ids(items)
    assert int(m.group(1)) == len(bare)
    missing = sorted(items[i]["name"] for i in bare if items[i]["name"] not in row)
    assert missing == [], f"hps.py row omits curated items: {missing}"


def test_no_stale_nine_or_ten_entry_enchanter_recital():
    """The exact defect: a bare 9 / 10 count with no patch beside it."""
    stale = re.compile(r"\b(9|10) (entries|enchanter items)\b")
    assert stale.search(_row("| `hps.py` |")) is None
    assert stale.search(_row("| `data/daemon_slayer/<patch>/enchanter_items.json` |")) is None
    assert re.search(r"registry of \d+ enchanter items", _HPS.read_text(encoding="utf-8")) is None


# --- other module-map rows --------------------------------------------------


def test_archetype_weights_row_matches_table():
    row = _row("| `archetype_weights.json` |")
    m = _match(r"alpha/beta table - (\d+) entries", row, "archetype_weights.json row")
    assert int(m.group(1)) == len(_load(_DS_PKG / "archetype_weights.json")["champions"])


def test_abilities_row_matches_snapshot_and_roster():
    row = _row("| `abilities.py` |")
    m = _match(r"(\d+)/(\d+) champions x P/Q/W/E/R", row, "abilities.py row")
    abilities = _load(_DATA_ROOT / _patch() / "champion_abilities.json")["data"]
    roster = _load(_DATA_ROOT / _patch() / "champions.json")["data"]
    assert (int(m.group(1)), int(m.group(2))) == (len(abilities), len(roster))


def test_ult_rates_row_matches_spell_cast_rate_table():
    row = _row("| `ult_rates.py` |")
    m = _match(r"(\d+) champions x 4 spells over up to (\d+) mode buckets", row, "ult_rates.py row")
    table = _load(_DATA_ROOT / "spell_cast_rates.json")["by_champ_mode"]
    widest = max(len([k for k in modes if k != "global"]) for modes in table.values())
    assert (int(m.group(1)), int(m.group(2))) == (len(table), widest)


def test_effects_data_row_matches_item_effects():
    row = _row("| `_effects_data.py` |")
    m = _match(r"the `ItemEffect` registry: (\d+) entries", row, "_effects_data.py row")
    assert int(m.group(1)) == len(ITEM_EFFECTS)


# --- per-champion override registries ----------------------------------------


@pytest.fixture(scope="module")
def registry_champions() -> dict:
    return {k: set(_load(_DS_PKG / f)["champions"]) for k, f in _REGISTRIES.items()}


def test_override_registry_per_registry_counts(registry_champions):
    m = _match(
        r"Per registry: block_index (\d+), max_priority (\d+), combo_sequences (\d+), form_index (\d+)\.",
        _doc(),
        "per-registry counts",
    )
    stated = dict(zip(("block_index", "max_priority", "combo_sequences", "form_index"), map(int, m.groups())))
    assert stated == {k: len(c) for k, c in registry_champions.items()}


def test_override_registry_distinct_and_entry_totals(registry_champions):
    m = _match(r"(\d+) distinct champions / (\d+) \(champion, registry\) entries", _doc(), "registry totals")
    distinct = set().union(*registry_champions.values())
    entries = sum(len(c) for c in registry_champions.values())
    assert (int(m.group(1)), int(m.group(2))) == (len(distinct), entries)


def test_override_registry_coverage_percentages(registry_champions):
    m = _match(
        r"cover ([\d.]+)% of the (\d+)-champion abilities keyspace \(([\d.]+)% of the full (\d+) roster\)",
        _doc(),
        "registry coverage",
    )
    distinct = len(set().union(*registry_champions.values()))
    keyspace = len(_load(_DATA_ROOT / _patch() / "champion_abilities.json")["data"])
    roster = len(_load(_DATA_ROOT / _patch() / "champions.json")["data"])
    assert (int(m.group(2)), int(m.group(4))) == (keyspace, roster)
    assert m.group(1) == f"{100 * distinct / keyspace:.1f}"
    assert m.group(3) == f"{100 * distinct / roster:.1f}"
