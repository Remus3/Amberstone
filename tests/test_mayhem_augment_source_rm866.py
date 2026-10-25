"""RM-866: ARAM Mayhem augment magnitudes extracted from CommunityDragon.

The source is CommunityDragon's ``game/maps/modespecificdata/kiwi.bin.json``
(the Mayhem map's mode-specific bin). Each ``AugmentData`` row carries the
Riot augment id (``AugmentPlatformId``) and a ``RootSpell`` object path; the
``SpellObject`` at that path carries ``mSpell.DataValues`` - a list of
``{"name", "values"}`` entries with one value per rank.

Shapes measured on the live 16.21 bin (2026-10-25), each pinned below by a
trimmed fixture in the same shape:

* an AugmentData whose RootSpell resolves to a SpellObject with DataValues
  (219 of 249 rows);
* an AugmentData whose RootSpell path is not in the bin (0 at 16.21, the
  row's named shape);
* a SpellObject with NO DataValues key, only ``mSpellCalculations``
  (30 of 249), and the row's named EMPTY DataValues list;
* non-augment types in the same bin (VfxSystemDefinitionData, SpellObject,
  ResourceResolver, ...), which must be ignored;
* a DataValue entry with a name but no ``values`` key (8 entries at 16.21);
* a duplicated DataValue name inside one spell (id 2034, AttachDuration);
* a ``DataValuesModeOverride`` keyed ``cherry`` (Arena, 25 spells).

No test here touches the network: every fetch goes through a monkeypatched
``_http_get``.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

import core.mayhem_augment_source as M

_ROOT = Path(__file__).resolve().parents[1]

_AUG = "Maps/ModeSpecificData/Augments"


def _aug(name: str, pid, root_spell=None, **extra) -> tuple[str, dict]:
    path = f"{_AUG}/{name}"
    row = {
        "AugmentNameId": name,
        "NameTra": f"Kiwi_{name}_Name",
        "RootSpell": root_spell if root_spell is not None else f"{path}/Augment_{name}",
        "AugmentPlatformId": pid,
        "__type": "AugmentData",
    }
    row.update(extra)
    return path, row


def _spell(path: str, data_values=None, *, omit_dv=False, **mspell_extra) -> tuple[str, dict]:
    mspell: dict = {"__type": "SpellDataResource"}
    if not omit_dv:
        mspell["DataValues"] = data_values
    mspell.update(mspell_extra)
    return path, {
        "ObjectName": path.rsplit("/", 1)[-1],
        "objectPath": path,
        "mSpell": mspell,
        "__type": "SpellObject",
    }


def _dv(name, values=None, *, omit_values=False) -> dict:
    entry = {"name": name, "__type": "SpellDataValue"}
    if not omit_values:
        entry["values"] = values
    return entry


def _ranks(x: float) -> list[float]:
    return [x] * 7


def _fixture() -> dict:
    """A trimmed bin in the real shape: the four named shapes plus the
    measured variants."""
    bin_: dict = {}

    # (1) resolves, with DataValues (1088 Ultimate Revolution: Cooldown 75).
    p, a = _aug("ARAM_UltimateRevolution", 1088)
    bin_[p] = a
    sp, s = _spell(a["RootSpell"], [_dv("Cooldown", _ranks(75.0))])
    bin_[sp] = s

    # (2) RootSpell path not present in the bin.
    p, a = _aug("GhostSpell", 1500, root_spell=f"{_AUG}/GhostSpell/Augment_Missing")
    bin_[p] = a

    # (3a) EMPTY DataValues list.
    p, a = _aug("EmptyValues", 1600)
    bin_[p] = a
    sp, s = _spell(a["RootSpell"], [])
    bin_[sp] = s

    # (3b) NO DataValues key at all, only a calculation (real: SnapBack).
    p, a = _aug("SnapBack", 1700)
    bin_[p] = a
    sp, s = _spell(
        a["RootSpell"], omit_dv=True,
        mSpellCalculations={"SnapDamage": {"__type": "GameCalculation"}},
    )
    bin_[sp] = s

    # (4) non-augment types in the same bin.
    bin_["Maps/ModeSpecificData/Vfx/Thing"] = {"__type": "VfxSystemDefinitionData", "x": 1}
    bin_["Maps/ModeSpecificData/Augments/Loose/Augment_Loose"] = _spell(
        "Maps/ModeSpecificData/Augments/Loose/Augment_Loose", [_dv("Damage", _ranks(9.0))]
    )[1]
    bin_["Maps/ModeSpecificData/Res"] = {"__type": "ResourceResolver", "resourceMap": {}}
    bin_["{05c8aed6}"] = {"__type": "{05c8aed6}"}

    # A name with no values key next to a good one (real: 1149 ResistInc).
    p, a = _aug("PartialValues", 1149)
    bin_[p] = a
    sp, s = _spell(
        a["RootSpell"],
        [_dv("ResistInc", omit_values=True), _dv("Duration", _ranks(3.0))],
    )
    bin_[sp] = s

    # Duplicate DataValue name inside one spell (real: 2034 AttachDuration).
    p, a = _aug("Dupes", 2034)
    bin_[p] = a
    sp, s = _spell(
        a["RootSpell"],
        [_dv("AttachDuration", _ranks(2.0)), _dv("Range", _ranks(500.0)),
         _dv("AttachDuration", _ranks(4.0))],
    )
    bin_[sp] = s

    # Arena (cherry) mode override present; base values are the Mayhem ones.
    p, a = _aug("Sonata", 1420)
    bin_[p] = a
    sp, s = _spell(
        a["RootSpell"],
        [_dv("Cooldown", _ranks(10.0))],
        DataValuesModeOverride={
            "cherry": {
                "SpellDataValues": [_dv("Cooldown", _ranks(7.5))],
                "__type": "SpellDataValueVector",
            }
        },
    )
    bin_[sp] = s

    # Rank-varying values keep their order.
    p, a = _aug("Ramp", 3001)
    bin_[p] = a
    sp, s = _spell(a["RootSpell"], [_dv("Bonus", [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0])])
    bin_[sp] = s
    return bin_


def _rows() -> dict:
    return M.extract_rows(_fixture())[0]


# --- the four named shapes ----------------------------------------------------


def test_resolved_root_spell_yields_named_per_rank_values():
    row = _rows()["1088"]
    assert row["values"] == [{"name": "Cooldown", "per_rank": _ranks(75.0)}]
    assert row["reason"] is None
    assert row["name_id"] == "ARAM_UltimateRevolution"
    assert row["root_spell"].endswith("/Augment_ARAM_UltimateRevolution")


def test_missing_root_spell_is_kept_with_null_values_and_a_reason():
    row = _rows()["1500"]
    assert row["values"] is None
    assert row["reason"] == "root_spell_missing"


def test_empty_data_values_is_kept_with_null_values_and_a_reason():
    row = _rows()["1600"]
    assert row["values"] is None
    assert row["reason"] == "empty_data_values"


def test_absent_data_values_key_is_kept_with_null_values_and_a_reason():
    row = _rows()["1700"]
    assert row["values"] is None
    assert row["reason"] == "no_data_values"


def test_non_augment_types_are_ignored():
    rows = _rows()
    assert set(rows) == {"1088", "1500", "1600", "1700", "1149", "2034", "1420", "3001"}
    # The loose SpellObject's Damage value never leaks into any row.
    for row in rows.values():
        for entry in row["values"] or []:
            assert entry["name"] != "Damage"


# --- measured variants ---------------------------------------------------------


def test_entry_without_values_is_null_not_invented():
    row = _rows()["1149"]
    assert row["values"] == [
        {"name": "ResistInc", "per_rank": None},
        {"name": "Duration", "per_rank": _ranks(3.0)},
    ]
    assert row["reason"] is None


def test_a_row_whose_every_entry_lacks_values_has_no_values():
    bin_ = {}
    p, a = _aug("AllNull", 1336)
    bin_[p] = a
    sp, s = _spell(a["RootSpell"], [_dv("CritChance", omit_values=True)])
    bin_[sp] = s
    rows, _ = M.extract_rows(bin_)
    assert rows["1336"]["values"] == [{"name": "CritChance", "per_rank": None}]
    assert rows["1336"]["reason"] == "all_values_missing"
    snap = M.build_snapshot(bin_, rc_patch="99.1.1", source_url="u",
                            cdragon_patch="99.1", fetched_at="t")
    assert snap["with_values"] == 0


@pytest.mark.parametrize("bad", [
    "75", [75.0, "x"], [True] * 7, {"a": 1}, [None] * 7, 5.0,
])
def test_invalid_value_payloads_become_null(bad):
    bin_ = {}
    p, a = _aug("Bad", 1400)
    bin_[p] = a
    sp, s = _spell(a["RootSpell"], [_dv("X", bad), _dv("Y", _ranks(1.0))])
    bin_[sp] = s
    rows, _ = M.extract_rows(bin_)
    assert rows["1400"]["values"][0] == {"name": "X", "per_rank": None}
    assert rows["1400"]["values"][1] == {"name": "Y", "per_rank": _ranks(1.0)}


def test_duplicate_value_names_are_preserved_in_source_order():
    names = [e["name"] for e in _rows()["2034"]["values"]]
    assert names == ["AttachDuration", "Range", "AttachDuration"]
    assert _rows()["2034"]["values"][2]["per_rank"] == _ranks(4.0)


def test_rank_values_keep_their_order():
    assert _rows()["3001"]["values"][0]["per_rank"] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_mode_override_names_are_recorded_and_base_values_are_kept():
    row = _rows()["1420"]
    assert row["values"] == [{"name": "Cooldown", "per_rank": _ranks(10.0)}]
    assert row["override_modes"] == ["cherry"]
    assert _rows()["1088"]["override_modes"] == []


def test_root_spell_resolving_to_a_non_spell_object_is_null_with_a_reason():
    bin_ = {}
    p, a = _aug("Odd", 1450)
    bin_[p] = a
    bin_[a["RootSpell"]] = {"__type": "ResourceResolver"}
    rows, _ = M.extract_rows(bin_)
    assert rows["1450"]["values"] is None
    assert rows["1450"]["reason"] == "root_spell_not_a_spell_object"


def test_rows_without_an_integer_platform_id_are_skipped_and_counted():
    bin_ = {}
    for name, pid in (("NoId", None), ("StrId", "1001"), ("BoolId", True)):
        p, a = _aug(name, pid)
        if pid is None:
            del a["AugmentPlatformId"]
        bin_[p] = a
    p, a = _aug("Good", 1002)
    bin_[p] = a
    rows, stats = M.extract_rows(bin_)
    assert set(rows) == {"1002"}
    assert stats["skipped_no_id"] == 3


def test_duplicate_platform_ids_keep_the_first_by_object_path_and_are_counted():
    bin_ = {}
    pb, b = _aug("Bbb", 1010)
    pa, a = _aug("Aaa", 1010)
    bin_[pb] = b
    bin_[pa] = a
    rows, stats = M.extract_rows(bin_)
    assert rows["1010"]["name_id"] == "Aaa"
    assert stats["duplicate_ids"] == 1


# --- snapshot, ordering, serialization -------------------------------------------


def _snap(bin_=None) -> dict:
    return M.build_snapshot(
        _fixture() if bin_ is None else bin_,
        rc_patch="99.1.1",
        source_url=M.kiwi_bin_url("99.1"),
        cdragon_patch="99.1",
        fetched_at="2026-10-25T00:00:00+00:00",
    )


def test_snapshot_header_names_source_patch_and_fetch_time():
    snap = _snap()
    assert snap["schema"] == M.SCHEMA
    assert snap["source"] == (
        "https://raw.communitydragon.org/99.1/game/maps/modespecificdata/kiwi.bin.json"
    )
    assert snap["rc_patch"] == "99.1.1"
    assert snap["cdragon_patch"] == "99.1"
    assert snap["fetched_at"] == "2026-10-25T00:00:00+00:00"
    assert snap["count"] == 8
    # 1088, 1149, 2034, 1420, 3001 carry at least one number.
    assert snap["with_values"] == 5
    assert snap["null_reasons"] == {
        "empty_data_values": 1, "no_data_values": 1, "root_spell_missing": 1,
    }


def test_ordering_is_deterministic_regardless_of_input_order():
    base = M.serialize(_snap())
    items = list(_fixture().items())
    for seed in range(5):
        random.Random(seed).shuffle(items)
        assert M.serialize(_snap(dict(items))) == base


def test_serialized_rows_are_in_numeric_id_order():
    snap = json.loads(M.serialize(_snap()))
    keys = list(snap["augments"])
    assert keys == sorted(keys, key=int)


def test_serialized_bytes_are_ascii_lf_and_newline_terminated():
    bin_ = _fixture()
    # A non-ASCII name must not reach the file as a raw byte.
    p, a = _aug("Accent", 1999)
    a["AugmentNameId"] = "Caf" + chr(0xE9)
    bin_[p] = a
    data = M.serialize(_snap(bin_))
    data.decode("ascii")
    assert b"\r" not in data
    assert data.endswith(b"}\n")
    assert json.loads(data)["augments"]["1999"]["name_id"] == "Caf" + chr(0xE9)


def test_stamp_is_the_rc_patch_for_both_ds_guards():
    sys.path.insert(0, str(_ROOT))
    from agents.daemon_slayer.abilities import artifact_patch_marker
    from tools import ds_feed_index as fi

    snap = json.loads(M.serialize(_snap()))
    assert artifact_patch_marker(snap) == ("rc_patch", "99.1.1")
    assert fi.extract_stamp(snap) == ("rc_patch", "99.1.1")


# --- atomic write -------------------------------------------------------------


def test_write_is_atomic_a_failed_replace_leaves_the_old_file(tmp_path, monkeypatch):
    import core.polled_json as pj

    target = tmp_path / "99.1.1" / M.FILENAME
    target.parent.mkdir()
    target.write_bytes(b'{"old": true}\n')

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(pj, "_replace_with_retry", boom)
    with pytest.raises(OSError):
        M.write_snapshot(target, _snap())
    assert target.read_bytes() == b'{"old": true}\n'
    assert sorted(p.name for p in target.parent.iterdir()) == [M.FILENAME]


def test_write_leaves_no_scratch_file_and_round_trips(tmp_path):
    target = tmp_path / "99.1.1" / M.FILENAME
    snap = _snap()
    M.write_snapshot(target, snap)
    assert sorted(p.name for p in target.parent.iterdir()) == [M.FILENAME]
    assert target.read_bytes() == M.serialize(snap)


# --- refresh (fetch + floor + write), no network ------------------------------------


def _big_bin(rows: int, with_values: int) -> dict:
    bin_ = {}
    for i in range(rows):
        p, a = _aug(f"A{i}", 5000 + i)
        bin_[p] = a
        dvs = [_dv("V", _ranks(float(i)))] if i < with_values else []
        sp, s = _spell(a["RootSpell"], dvs)
        bin_[sp] = s
    return bin_


def test_refresh_fetches_the_patch_pinned_url_and_writes_beside_cherry(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, timeout_s):
        calls.append(url)
        return _big_bin(M.MIN_ROWS, M.MIN_WITH_VALUES)

    monkeypatch.setattr(M, "_http_get", fake_get)
    snap = M.refresh("99.1.1", data_dir=tmp_path)
    assert calls == [
        "https://raw.communitydragon.org/99.1/game/maps/modespecificdata/kiwi.bin.json"
    ]
    out = tmp_path / "99.1.1" / "mayhem_augments.json"
    assert out.read_bytes() == M.serialize(snap)
    assert snap["count"] == M.MIN_ROWS
    assert snap["with_values"] == M.MIN_WITH_VALUES


def test_refresh_accepts_an_explicit_cdragon_patch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        M, "_http_get",
        lambda url, timeout_s: calls.append(url) or _big_bin(M.MIN_ROWS, M.MIN_WITH_VALUES),
    )
    snap = M.refresh("99.1.1", cdragon_patch="latest", data_dir=tmp_path)
    assert calls[0].startswith("https://raw.communitydragon.org/latest/")
    assert snap["cdragon_patch"] == "latest"


@pytest.mark.parametrize("rows,with_values", [
    (5, 5),
    (300, 10),
])
def test_a_large_drop_fails_loudly_and_writes_nothing(tmp_path, monkeypatch, rows, with_values):
    target = tmp_path / "99.1.1" / M.FILENAME
    target.parent.mkdir()
    target.write_bytes(b'{"old": true}\n')
    monkeypatch.setattr(M, "_http_get", lambda url, timeout_s: _big_bin(rows, with_values))
    with pytest.raises(M.MayhemAugmentSourceError):
        M.refresh("99.1.1", data_dir=tmp_path)
    assert target.read_bytes() == b'{"old": true}\n'


@pytest.mark.parametrize("payload", [[], [1, 2], "x", {}])
def test_a_non_bin_payload_fails_loudly(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(M, "_http_get", lambda url, timeout_s: payload)
    with pytest.raises(M.MayhemAugmentSourceError):
        M.refresh("99.1.1", data_dir=tmp_path)
    assert not (tmp_path / "99.1.1" / M.FILENAME).exists()


def test_a_fetch_failure_propagates_and_writes_nothing(tmp_path, monkeypatch):
    def fail(url, timeout_s):
        raise M.AugmentSourceError("down")

    monkeypatch.setattr(M, "_http_get", fail)
    with pytest.raises(M.AugmentSourceError):
        M.refresh("99.1.1", data_dir=tmp_path)
    assert not (tmp_path / "99.1.1").exists()


@pytest.mark.parametrize("rc_patch,expected", [
    ("16.21.1", "16.21"), ("16.9.1", "16.9"), ("17.1.3", "17.1"),
])
def test_cdragon_patch_is_major_minor_of_the_rc_patch(rc_patch, expected):
    assert M.cdragon_patch_for(rc_patch) == expected


@pytest.mark.parametrize("bad", ["", "16", "latest", "16.x.1", "../16.21.1"])
def test_a_malformed_rc_patch_is_refused(bad):
    with pytest.raises(ValueError):
        M.cdragon_patch_for(bad)


# --- coverage census -------------------------------------------------------------


def test_coverage_counts_rows_values_and_an_id_subset():
    snap = _snap()
    cov = M.coverage(snap, ids={1088, 1500, 1149, 424242})
    assert cov["rows"] == 8
    assert cov["with_values"] == 5
    assert cov["ids"] == 4
    assert cov["ids_with_row"] == 3
    assert cov["ids_with_values"] == 2


def test_coverage_without_ids_has_no_subset_keys():
    cov = M.coverage(_snap())
    assert set(cov) == {"rows", "with_values"}


# --- the shipped file ---------------------------------------------------------------

_SHIPPED = _ROOT / "data" / "daemon_slayer" / "16.21.1" / "mayhem_augments.json"


def test_shipped_16_21_1_file_is_well_formed():
    data = _SHIPPED.read_bytes()
    data.decode("ascii")
    assert b"\r" not in data
    snap = json.loads(data)
    assert snap["schema"] == M.SCHEMA
    assert snap["rc_patch"] == "16.21.1"
    assert snap["source"].startswith("https://raw.communitydragon.org/")
    assert snap["count"] == len(snap["augments"]) >= M.MIN_ROWS
    assert snap["with_values"] >= M.MIN_WITH_VALUES
    for key, row in snap["augments"].items():
        assert key.isdigit()
        if row["values"] is None:
            assert row["reason"] in M.NULL_REASONS, key
        for entry in row["values"] or []:
            per = entry["per_rank"]
            assert per is None or all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in per
            ), key
    # Re-serializing the parsed file reproduces it byte for byte.
    assert M.serialize(snap) == data
