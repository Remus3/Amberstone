"""S144-D-236..239 - the four DS WIN-credit tables and their offline builders.

The DEFAULT-OFF seams ``prefer_kit_axis_by_win`` (DSP11) and
``prefer_survivability_by_win`` (RF1 / RF2 / RF3) read four tables in
``agents/daemon_slayer/``, each written by one builder in
``ops/audit/ds_perm_swarm/``. Every builder offers ``--check`` ("verify the
committed JSON matches a fresh build").

* S144-D-236: ``--check`` compared the whole text, and the builders stamp
  ``_meta.ds_patch`` from ``data/daemon_slayer/current.txt`` on every build. So
  from the first patch after a table was built, ``--check`` reported DRIFT for
  ever although the table was in sync. MEASURED 2026-11-09 (current 16.22.1):
  all three survivability builders exit 2 with ``champions`` byte-equal to a
  fresh build; the ONLY difference was the stamp (16.12.1 committed). The check
  now keeps the committed stamp: a content or format change still fails.
* S144-D-237: ``build_kit_axis_item_credit`` opened ``data/rewind_history.db``
  with a plain ``sqlite3.connect``. On a checkout without the (gitignored) DB,
  ``--check`` CREATED a 0-byte database there and died with a raw
  ``no such table`` traceback. MEASURED 2026-11-09 in the lane worktree. It now
  opens the DB read-only (the ``run_consolidate`` / ``run_harness`` shape),
  never creates it, and ``main`` exits 3 with a one-line reason.
* S144-D-238: each table's ``_meta.note`` makes exclusion claims (Cluster A
  excluded, boots / components excluded, kit axis only). Pinned against the
  builders' own constants and the live snapshot.
* S144-D-239: ``_meta`` is provenance only: no loader reads it (proved by
  loading a copy with ``_meta`` emptied), ``ds_patch`` names an on-disk DS
  snapshot no newer than the current patch, ``source`` names the builder whose
  ``_OUT`` is the loader's path, ``min_rewind_n`` / ``scorer_lane`` equal the
  builder's constants, and ``scorer_lane`` names the module that calls the
  table's lookup.
"""

from __future__ import annotations

import contextlib
import copy
import json
import re
import sqlite3
import sys
from pathlib import Path

import pytest

from agents.daemon_slayer import kit_axis_credit, survivability_credit
from agents.daemon_slayer.data_loader import DataSnapshot
from ops.audit.ds_perm_swarm import (
    build_kit_axis_item_credit as kit_b,
)
from ops.audit.ds_perm_swarm import (
    build_survivability_item_credit as rf1_b,
)
from ops.audit.ds_perm_swarm import (
    build_survivability_item_credit_enchanter as rf2_b,
)
from ops.audit.ds_perm_swarm import (
    build_survivability_item_credit_tank as rf3_b,
)

_REPO = Path(__file__).resolve().parents[1]
_DS_DATA = _REPO / "data" / "daemon_slayer"
_DS_PKG = _REPO / "agents" / "daemon_slayer"

# label -> (builder module, loader path, loader lookup)
_TABLES = {
    "kit_axis": (kit_b, kit_axis_credit._TABLE_PATH, kit_axis_credit.kit_axis_item_ids),
    "rf1": (
        rf1_b,
        survivability_credit._TABLE_PATH,
        survivability_credit.survivability_item_ids,
    ),
    "rf2": (
        rf2_b,
        survivability_credit._ENCHANTER_TABLE_PATH,
        survivability_credit.survivability_item_ids_enchanter,
    ),
    "rf3": (
        rf3_b,
        survivability_credit._TANK_TABLE_PATH,
        survivability_credit.survivability_item_ids_tank,
    ),
}
_SURV = ("rf1", "rf2", "rf3")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _patch_key(patch: str) -> tuple[int, ...]:
    return tuple(int(p) for p in patch.split("."))


def _run_check(mod, monkeypatch, out: Path) -> int:
    monkeypatch.setattr(mod, "_OUT", out)
    monkeypatch.setattr(sys, "argv", [mod.__name__, "--check"])
    return mod.main()


def _copy_table(path: Path, tmp_path: Path) -> Path:
    out = tmp_path / path.name
    out.write_bytes(path.read_bytes())
    return out


# ---------------------------------------------------------------- S144-D-236


@pytest.mark.parametrize("label", _SURV)
def test_check_passes_on_the_committed_table(label, tmp_path, monkeypatch, capsys):
    mod, path, _ = _TABLES[label]
    out = _copy_table(path, tmp_path)
    before = out.read_bytes()
    assert _run_check(mod, monkeypatch, out) == 0, capsys.readouterr().err
    # --check never rewrites the file, the stamp included.
    assert out.read_bytes() == before


@pytest.mark.parametrize("label", _SURV)
def test_check_still_catches_a_content_drift(label, tmp_path, monkeypatch, capsys):
    mod, path, _ = _TABLES[label]
    table = _read(path)
    champ = sorted(table["champions"])[0]
    table["champions"][champ]["items"] = table["champions"][champ]["items"][:-1] or [
        {"id": "1001", "lift": 1.0, "name": "Boots", "rewind_n": 99, "rewind_wr": 50.0}
    ]
    out = tmp_path / path.name
    out.write_bytes(
        (json.dumps(table, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    )
    assert _run_check(mod, monkeypatch, out) == 2
    assert "DRIFT" in capsys.readouterr().err


@pytest.mark.parametrize("label", _SURV)
def test_check_still_catches_a_format_drift(label, tmp_path, monkeypatch):
    mod, path, _ = _TABLES[label]
    out = tmp_path / path.name
    out.write_bytes((json.dumps(_read(path), indent=1, sort_keys=True) + "\n").encode())
    assert _run_check(mod, monkeypatch, out) == 2


@pytest.mark.parametrize("label", _SURV)
def test_check_catches_a_missing_or_unparsable_table(label, tmp_path, monkeypatch):
    mod, _, _ = _TABLES[label]
    assert _run_check(mod, monkeypatch, tmp_path / "absent.json") == 2
    junk = tmp_path / "junk.json"
    junk.write_bytes(b"{not json\n")
    assert _run_check(mod, monkeypatch, junk) == 2


@pytest.mark.parametrize("label", _SURV)
def test_check_catches_a_stamp_that_is_not_a_string(label, tmp_path, monkeypatch):
    # Only a string stamp is carried over; any other value is a drift.
    mod, path, _ = _TABLES[label]
    table = _read(path)
    table["_meta"]["ds_patch"] = 1612
    out = tmp_path / path.name
    out.write_bytes(
        (json.dumps(table, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()
    )
    assert _run_check(mod, monkeypatch, out) == 2


def test_kit_axis_check_keeps_the_committed_stamp(tmp_path, monkeypatch):
    # The kit-axis build needs the gitignored rewind DB, so its build is stubbed
    # from the committed table at a different patch; the comparison is the same.
    committed = _read(kit_b._OUT)
    fresh = copy.deepcopy(committed)
    fresh["_meta"]["ds_patch"] = "99.99.1"
    monkeypatch.setattr(kit_b, "build", lambda: copy.deepcopy(fresh))
    out = _copy_table(kit_b._OUT, tmp_path)
    assert _run_check(kit_b, monkeypatch, out) == 0
    fresh["champions"].pop(sorted(fresh["champions"])[0])
    assert _run_check(kit_b, monkeypatch, out) == 2


@pytest.mark.parametrize("label", list(_TABLES))
def test_write_mode_stamps_the_current_patch(label, tmp_path, monkeypatch):
    # The fix is in --check only: a real (re)build still records today's patch.
    mod, path, _ = _TABLES[label]
    built = copy.deepcopy(_read(path))
    built["_meta"]["ds_patch"] = "99.99.1"
    monkeypatch.setattr(mod, "build", lambda: copy.deepcopy(built))
    out = tmp_path / path.name
    monkeypatch.setattr(mod, "_OUT", out)
    monkeypatch.setattr(sys, "argv", [mod.__name__])
    assert mod.main() == 0
    assert _read(out)["_meta"]["ds_patch"] == "99.99.1"


# ---------------------------------------------------------------- S144-D-237


def test_kit_axis_reads_never_create_an_absent_rewind_db(tmp_path, monkeypatch):
    absent = tmp_path / "dir with space" / "rewind_history.db"
    absent.parent.mkdir()
    monkeypatch.setattr(kit_b, "_REWIND", absent)
    with pytest.raises(FileNotFoundError):
        kit_b._champ_wr_all_modes("Corki")
    with pytest.raises(FileNotFoundError):
        kit_b._ezreal_from_rewind({})
    assert not absent.exists()


def test_kit_axis_main_exits_3_without_a_rewind_db(tmp_path, monkeypatch, capsys):
    absent = tmp_path / "rewind_history.db"
    monkeypatch.setattr(kit_b, "_REWIND", absent)
    out = _copy_table(kit_b._OUT, tmp_path)
    before = out.read_bytes()
    assert _run_check(kit_b, monkeypatch, out) == 3
    err = capsys.readouterr().err
    assert "rewind" in err.lower()
    assert "Traceback" not in err
    assert not absent.exists()
    assert out.read_bytes() == before


def test_kit_axis_main_exits_3_on_a_db_without_the_table(tmp_path, monkeypatch, capsys):
    db = tmp_path / "rewind_history.db"
    sqlite3.connect(str(db)).close()  # a real but empty database
    monkeypatch.setattr(kit_b, "_REWIND", db)
    assert _run_check(kit_b, monkeypatch, _copy_table(kit_b._OUT, tmp_path)) == 3
    assert "Traceback" not in capsys.readouterr().err


def test_kit_axis_reads_a_real_db_read_only(tmp_path, monkeypatch):
    db = tmp_path / "dir with space" / "rewind_history.db"
    db.parent.mkdir()
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE participants (champion_name TEXT, win INTEGER, item0 INTEGER,"
        " item1 INTEGER, item2 INTEGER, item3 INTEGER, item4 INTEGER, item5 INTEGER)"
    )
    conn.executemany(
        "INSERT INTO participants VALUES (?,?,?,?,?,?,?,?)",
        [("Corki", 1, 3078, 0, 0, 0, 0, 0), ("Corki", 0, 3078, 6676, 0, 0, 0, 0)],
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(kit_b, "_REWIND", db)
    base_wr, n, per = kit_b._champ_wr_all_modes("Corki")
    assert (base_wr, n) == (50.0, 2)
    assert per == {"3078": (2, 50.0), "6676": (1, 0.0)}
    with contextlib.closing(kit_b._open_rewind()) as ro, pytest.raises(
        sqlite3.OperationalError
    ):
        ro.execute("DELETE FROM participants")


# ---------------------------------------------------------------- S144-D-238


@pytest.fixture(scope="module")
def snap():
    return DataSnapshot.load()


def _surv_defects(table: dict, mod, items: dict) -> list[str]:
    bad = []
    for champ, entry in (table.get("champions") or {}).items():
        if champ in mod._EXCLUDE_CHAMPS:
            bad.append(f"{champ}: Cluster A champion tabled")
        if entry.get("axis") != "survivability":
            bad.append(f"{champ}: axis {entry.get('axis')!r}")
        for row in entry.get("items") or []:
            rec = items.get(str(row["id"])) or {}
            if row.get("name") not in mod._SURVIVABILITY_NAMES:
                bad.append(f"{champ}: {row.get('name')!r} off the survivability axis")
            if rec.get("into"):
                bad.append(f"{champ}: {row['id']} is a component (builds into)")
            if "Boots" in (rec.get("tags") or []):
                bad.append(f"{champ}: {row['id']} is boots")
    return bad


def _kit_defects(table: dict, items: dict) -> list[str]:
    bad = []
    for champ, entry in (table.get("champions") or {}).items():
        axis = kit_b._CHAMP_AXIS.get(champ)
        if axis is None:
            bad.append(f"{champ}: not a curated Cluster-B2 champion")
            continue
        if entry.get("axis") != axis:
            bad.append(f"{champ}: axis {entry.get('axis')!r}, builder says {axis!r}")
        for row in entry.get("items") or []:
            rec = items.get(str(row["id"])) or {}
            if str(row["id"]) not in kit_b._AXIS_ITEM_IDS[axis]:
                bad.append(f"{champ}: {row['id']} off the {axis} axis")
            if rec.get("into"):
                bad.append(f"{champ}: {row['id']} is a component (builds into)")
            if "Boots" in (rec.get("tags") or []):
                bad.append(f"{champ}: {row['id']} is boots")
    return bad


@pytest.mark.parametrize("label", _SURV)
def test_survivability_tables_honour_their_builder_filters(label, snap):
    mod, path, _ = _TABLES[label]
    table = _read(path)
    assert table["champions"], label
    assert _surv_defects(table, mod, snap.items) == []


def test_kit_axis_table_honours_its_builder_filters(snap):
    table = _read(kit_b._OUT)
    assert table["champions"]
    assert _kit_defects(table, snap.items) == []


def test_the_filter_checkers_are_not_blind(snap):
    boots = next(i for i, r in snap.items.items() if "Boots" in (r.get("tags") or []))
    comp = next(
        i for i, r in snap.items.items()
        if r.get("into") and "Boots" not in (r.get("tags") or [])
    )
    cluster_a = sorted(rf3_b._EXCLUDE_CHAMPS)[0]
    planted = {"champions": {cluster_a: {"axis": "tank", "items": [
        {"id": boots, "name": snap.items[boots]["name"]},
        {"id": comp, "name": "Thornmail"},
    ]}}}
    bad = _surv_defects(planted, rf3_b, snap.items)
    assert any("Cluster A" in b for b in bad)
    assert any("axis 'tank'" in b for b in bad)
    assert any("off the survivability axis" in b for b in bad)
    assert any("component" in b for b in bad)
    assert any("is boots" in b for b in bad)
    kit = {"champions": {
        "Garen": {"axis": "crit", "items": []},
        "Corki": {"axis": "crit", "items": [{"id": boots}, {"id": comp}]},
    }}
    bad = _kit_defects(kit, snap.items)
    assert any("Garen: not a curated" in b for b in bad)
    assert any("builder says 'manamune'" in b for b in bad)
    assert any("off the manamune axis" in b for b in bad)
    assert any("component" in b for b in bad)
    assert any("is boots" in b for b in bad)


# ---------------------------------------------------------------- S144-D-239


@pytest.mark.parametrize("label", list(_TABLES))
def test_meta_is_provenance_only(label, tmp_path, monkeypatch):
    mod, path, lookup = _TABLES[label]
    table = _read(path)
    loader = kit_axis_credit if label == "kit_axis" else survivability_credit
    attr = {
        "kit_axis": "_TABLE_PATH",
        "rf1": "_TABLE_PATH",
        "rf2": "_ENCHANTER_TABLE_PATH",
        "rf3": "_TANK_TABLE_PATH",
    }[label]
    loader.reset_cache()
    before = {c: lookup(c) for c in table["champions"]}
    stripped = dict(table, _meta={})
    alt = tmp_path / path.name
    alt.write_text(json.dumps(stripped), encoding="utf-8")
    monkeypatch.setattr(loader, attr, alt)
    loader.reset_cache()
    try:
        after = {c: lookup(c) for c in table["champions"]}
    finally:
        monkeypatch.undo()
        loader.reset_cache()
    assert all(before.values()), label
    assert after == before


@pytest.mark.parametrize("label", list(_TABLES))
def test_ds_patch_names_an_on_disk_snapshot_not_newer_than_current(label):
    _, path, _ = _TABLES[label]
    stamp = _read(path)["_meta"]["ds_patch"]
    assert isinstance(stamp, str) and re.fullmatch(r"\d+\.\d+\.\d+", stamp), stamp
    assert (_DS_DATA / stamp / "items.json").is_file(), stamp
    current = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    assert _patch_key(stamp) <= _patch_key(current)


@pytest.mark.parametrize("label", list(_TABLES))
def test_meta_names_its_builder_and_its_constants(label):
    mod, path, _ = _TABLES[label]
    meta = _read(path)["_meta"]
    builder_file = Path(mod.__file__).name
    assert meta["source"].split()[-1] == builder_file
    assert Path(mod._OUT) == path
    assert meta["min_rewind_n"] == mod._MIN_N
    anchor = meta["anchored_to"].split()[0].rstrip(",")
    assert (_REPO / anchor).is_file(), anchor
    assert (_REPO / anchor) == mod._REPORT


@pytest.mark.parametrize("label", _SURV)
def test_scorer_lane_names_the_module_that_reads_the_table(label):
    mod, path, lookup = _TABLES[label]
    lane = _read(path)["_meta"]["scorer_lane"]
    assert lane == mod._SCORER
    callers = sorted(
        p.stem
        for p in _DS_PKG.glob("*.py")
        if p.stem != "survivability_credit"
        and re.search(rf"\b{lookup.__name__}\(", p.read_text(encoding="utf-8"))
    )
    assert callers == [lane]
