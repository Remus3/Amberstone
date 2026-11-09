"""tests/test_pickban_targets_hardening_s144t245.py - lane 8 true-audit of
core/pickban_targets.py (s144 cycle 245, S144-T-664).

Every test points the reader at a temp DS tree (monkeypatched ``_DS_DIR`` and
``_CURRENT_TXT``), never at the committed tables, except the backfill check at
the end, which reads the committed tables READ-ONLY to prove the hardening
leaves every valid table's output unchanged.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path

import pytest

import core.pickban_targets as pbt

_ROOT = Path(__file__).resolve().parent.parent

_ROWS = [
    {"champion": "Zed", "net_swing": -0.5, "rel": 0.30},
    {"champion": "Talon", "net_swing": -0.4, "rel": 0.25},
    {"champion": "Kassadin", "net_swing": -0.2, "rel": 0.20},
    {"champion": "Fizz", "net_swing": -0.15, "rel": 0.15},
    {"champion": "Diana", "net_swing": -0.1, "rel": 0.10},
    {"champion": "Akali", "net_swing": -0.05, "rel": 0.05},
]


def _db(counters=None, good=None, champ="Lux") -> dict:
    return {
        "patch": "16.11.1",
        "mode": "sr",
        "level": 9,
        "top_k": 8,
        "targets": {
            champ: {
                "counters": list(_ROWS if counters is None else counters),
                "good_against": list(
                    [{"champion": "Garen", "net_swing": 0.6, "rel": 0.4}]
                    if good is None else good),
            },
        },
    }


def _write(ds: Path, patch: str, payload) -> Path:
    d = ds / patch
    d.mkdir(parents=True, exist_ok=True)
    p = d / "pickban_targets.json"
    text = payload if isinstance(payload, str) else json.dumps(payload)
    p.write_bytes(text.encode("utf-8"))
    return p


@pytest.fixture
def ds(tmp_path, monkeypatch):
    root = tmp_path / "data" / "daemon_slayer"
    root.mkdir(parents=True)
    monkeypatch.setattr(pbt, "_DS_DIR", root)
    monkeypatch.setattr(pbt, "_CURRENT_TXT", root / "current.txt")
    pbt._CACHE.clear()
    yield root
    pbt._CACHE.clear()


# --- F1: patch is a path component; traversal and non-str refused ---------

def test_patch_dotdot_cannot_escape_ds_dir(ds):
    # A valid decoy table one directory ABOVE the DS dir.
    (ds.parent / "pickban_targets.json").write_text(
        json.dumps(_db()), encoding="utf-8")
    assert pbt.load_pickban_targets(patch="..") == {}
    assert pbt.counters_for("Lux", patch="..") == []


def test_patch_with_separator_refused(ds):
    _write(ds, "16.11.1", _db())
    assert pbt.load_pickban_targets(patch="16.11.1/../16.11.1") == {}
    assert pbt.load_pickban_targets(patch="16.11.1\\x") == {}


@pytest.mark.parametrize("bad", [16, 16.11, ["16.11.1"], {"p": 1}, b"16.11.1"])
def test_non_str_patch_never_raises(ds, bad):
    _write(ds, "16.11.1", _db())
    assert pbt.load_pickban_targets(patch=bad) == {}
    assert pbt.counters_for("Lux", patch=bad) == []


def test_valid_patch_still_loads(ds):
    _write(ds, "16.11.1", _db())
    assert pbt.load_pickban_targets(patch="16.11.1")["patch"] == "16.11.1"


# --- F2: current.txt BOM / junk, and the stale fallback -------------------

def test_current_txt_with_bom_resolves(ds):
    # current.txt names the OLDER table, so the newest-table fallback cannot
    # mask a BOM that was not stripped.
    _write(ds, "16.11.1", _db())
    _write(ds, "16.12.1", _db(counters=[{"champion": "New", "net_swing": -1}]))
    (ds / "current.txt").write_bytes(b"\xef\xbb\xbf16.11.1\r\n")
    assert [r["champion"] for r in pbt.counters_for("Lux", top_n=1)] == ["Zed"]


def test_junk_current_txt_falls_back_to_newest_table(ds):
    _write(ds, "16.9.1", _db(counters=[{"champion": "Old", "net_swing": -1}]))
    _write(ds, "16.10.1", _db(counters=[{"champion": "New", "net_swing": -1}]))
    (ds / "current.txt").write_text("../escape\n", encoding="utf-8")
    # Numeric ordering: 16.10.1 is newer than 16.9.1 (a string sort says not).
    assert [r["champion"] for r in pbt.counters_for("Lux")] == ["New"]


def test_missing_current_txt_falls_back_to_newest_table(ds):
    _write(ds, "16.9.1", _db(counters=[{"champion": "Old", "net_swing": -1}]))
    _write(ds, "16.10.1", _db(counters=[{"champion": "New", "net_swing": -1}]))
    assert [r["champion"] for r in pbt.counters_for("Lux")] == ["New"]


def test_no_tables_at_all_is_empty(ds):
    assert pbt.load_pickban_targets() == {}
    assert pbt.ban_suggestions("Lux") == []


# --- F3/F4/F7: wrong-typed champion, top_n, mode never raise --------------

@pytest.mark.parametrize("bad", [["Lux"], {"Lux": 1}, 123, None, b"Lux"])
def test_non_str_champion_never_raises(ds, bad):
    _write(ds, "16.11.1", _db())
    assert pbt.counters_for(bad, patch="16.11.1") == []
    assert pbt.good_against(bad, patch="16.11.1") == []
    assert pbt.ban_suggestions(bad, patch="16.11.1") == []


@pytest.mark.parametrize("bad", [None, "3", True, False, float("nan"),
                                 float("inf"), 2.5, -1, [3]])
def test_bad_top_n_is_empty_never_raises(ds, bad):
    _write(ds, "16.11.1", _db())
    assert pbt.counters_for("Lux", patch="16.11.1", top_n=bad) == []
    assert pbt.good_against("Lux", patch="16.11.1", top_n=bad) == []
    assert pbt.ban_suggestions("Lux", patch="16.11.1", top_n=bad) == []


@pytest.mark.parametrize("bad", [["sr"], {"m": 1}, None, 3])
def test_non_str_mode_never_raises(ds, bad):
    _write(ds, "16.11.1", _db())
    assert pbt.load_pickban_targets(mode=bad, patch="16.11.1") == {}
    assert pbt.counters_for("Lux", mode=bad, patch="16.11.1") == []


# --- F5: returned rows / payload are copies, never the cache --------------

def test_mutating_returned_rows_does_not_poison_cache(ds):
    _write(ds, "16.11.1", _db())
    out = pbt.counters_for("Lux", patch="16.11.1", top_n=1)
    out[0]["champion"] = "Mutated"
    out[0].clear()
    again = pbt.counters_for("Lux", patch="16.11.1", top_n=1)
    assert again[0]["champion"] == "Zed"
    assert again[0]["net_swing"] == -0.5


def test_mutating_loaded_payload_does_not_poison_cache(ds):
    _write(ds, "16.11.1", _db())
    payload = pbt.load_pickban_targets(patch="16.11.1")
    payload["targets"]["Lux"]["counters"].clear()
    payload["targets"].clear()
    assert pbt.counters_for("Lux", patch="16.11.1", top_n=1)[0][
        "champion"] == "Zed"


# --- F6: junk / duplicate / self rows dropped -----------------------------

def test_junk_rows_dropped(ds):
    rows = [
        {"champion": 5, "net_swing": -0.9},
        {"champion": "", "net_swing": -0.9},
        {"champion": None, "net_swing": -0.9},
        {"champion": ["Zed"], "net_swing": -0.9},
        {"champion": "Nan", "net_swing": float("nan")},
        {"champion": "Inf", "net_swing": -0.1, "rel": float("inf")},
        {"champion": "Str", "net_swing": "-0.5"},
        {"champion": "Bool", "net_swing": True},
        {"champion": "Zed", "net_swing": -0.5, "rel": 0.3},
        "Talon",
        {"champion": "Talon", "net_swing": -0.4},
    ]
    _write(ds, "16.11.1", json.dumps(_db(counters=rows)))
    out = pbt.counters_for("Lux", patch="16.11.1", top_n=10)
    assert [r["champion"] for r in out] == ["Zed", "Talon"]


def test_duplicate_rows_deduped_keep_first(ds):
    rows = [{"champion": "Zed", "net_swing": -0.5},
            {"champion": "Zed", "net_swing": -0.1},
            {"champion": "Talon", "net_swing": -0.4}]
    _write(ds, "16.11.1", _db(counters=rows))
    out = pbt.counters_for("Lux", patch="16.11.1", top_n=5)
    assert [(r["champion"], r["net_swing"]) for r in out] == [
        ("Zed", -0.5), ("Talon", -0.4)]
    # Dedupe happens BEFORE the cap: top_n=2 still yields two champions.
    assert len(pbt.counters_for("Lux", patch="16.11.1", top_n=2)) == 2


def test_self_row_dropped(ds):
    rows = [{"champion": "Lux", "net_swing": -0.9},
            {"champion": "Zed", "net_swing": -0.5}]
    _write(ds, "16.11.1", _db(counters=rows))
    assert [r["champion"] for r in pbt.counters_for(
        "Lux", patch="16.11.1")] == ["Zed"]
    assert [r["champion"] for r in pbt.ban_suggestions(
        "Lux", patch="16.11.1")] == ["Zed"]


def test_row_missing_rel_still_kept(ds):
    # Pre-de-bias tables carried no "rel": a missing score is not junk.
    _write(ds, "16.11.1", _db(counters=[{"champion": "Zed", "net_swing": -1}]))
    assert pbt.counters_for("Lux", patch="16.11.1") == [
        {"champion": "Zed", "net_swing": -1}]


# --- F8: ban_suggestions window and enemy_comp shape ----------------------

def test_ban_suggestions_window_survives_many_picked(ds):
    _write(ds, "16.11.1", _db())
    picked = ["Zed", "Talon", "Kassadin", "Fizz"]
    out = pbt.ban_suggestions("Lux", enemy_comp=picked, patch="16.11.1",
                              top_n=1)
    assert [r["champion"] for r in out] == ["Diana"]


def test_ban_suggestions_bare_string_enemy_is_one_id(ds):
    _write(ds, "16.11.1", _db())
    out = pbt.ban_suggestions("Lux", enemy_comp="Zed", patch="16.11.1",
                              top_n=2)
    assert [r["champion"] for r in out] == ["Talon", "Kassadin"]


@pytest.mark.parametrize("bad", [5, 2.5, True, object()])
def test_ban_suggestions_non_iterable_enemy_never_raises(ds, bad):
    _write(ds, "16.11.1", _db())
    out = pbt.ban_suggestions("Lux", enemy_comp=bad, patch="16.11.1",
                              top_n=2)
    assert [r["champion"] for r in out] == ["Zed", "Talon"]


def test_ban_suggestions_tuple_and_set_enemy_filter(ds):
    _write(ds, "16.11.1", _db())
    for comp in (("Zed",), {"Zed"}, frozenset({"Zed"}), ["Zed", 7, None]):
        out = pbt.ban_suggestions("Lux", enemy_comp=comp, patch="16.11.1",
                                  top_n=1)
        assert [r["champion"] for r in out] == ["Talon"], comp


# --- F9: cache identity is (mtime_ns, size), not a float mtime ------------

def test_same_mtime_rewrite_is_reloaded(ds):
    p = _write(ds, "16.11.1", _db(counters=[{"champion": "Zed",
                                              "net_swing": -1}]))
    st = p.stat()
    assert pbt.counters_for("Lux", patch="16.11.1")[0]["champion"] == "Zed"
    _write(ds, "16.11.1", _db(counters=[{"champion": "Talonxx",
                                         "net_swing": -1}]))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert pbt.counters_for("Lux", patch="16.11.1")[0][
        "champion"] == "Talonxx"


# --- F10: narrowed excepts; malformed logged once per file version --------

def test_malformed_db_logged_once_per_version(ds, caplog):
    _write(ds, "16.11.1", "{not json")
    with caplog.at_level(logging.DEBUG, logger="core.pickban_targets"):
        assert pbt.load_pickban_targets(patch="16.11.1") == {}
        assert pbt.load_pickban_targets(patch="16.11.1") == {}
    hits = [r for r in caplog.records if "JSONDecodeError" in r.getMessage()]
    assert len(hits) == 1
    assert hits[0].levelno == logging.WARNING


def test_deeply_nested_table_never_raises_through_the_copy(ds):
    # json.loads accepts ~990 levels; copy.deepcopy recurses out near ~500.
    # Verifier finding (cycle 245): the public copy must not raise on it.
    deep = "[" * 900 + "]" * 900
    _write(ds, "16.11.1", '{"patch": "16.11.1", "targets": {"Lux": '
                          '{"counters": ' + deep + '}}}')
    assert pbt.load_pickban_targets(patch="16.11.1") == {}
    assert pbt.counters_for("Lux", patch="16.11.1") == []
    assert pbt.ban_suggestions("Lux", patch="16.11.1") == []


def test_unexpected_read_error_surfaces(ds, monkeypatch):
    _write(ds, "16.11.1", _db())

    def boom(*a, **k):
        raise RuntimeError("not a read or parse failure")

    monkeypatch.setattr(pbt.json, "loads", boom)
    with pytest.raises(RuntimeError):
        pbt.load_pickban_targets(patch="16.11.1")


def test_oserror_read_not_cached(ds):
    p = _write(ds, "16.11.1", _db())
    real_bytes, real_text = Path.read_bytes, Path.read_text

    def locked_bytes(self, *a, **k):
        if self == p:
            raise PermissionError("locked")
        return real_bytes(self, *a, **k)

    def locked_text(self, *a, **k):
        if self == p:
            raise PermissionError("locked")
        return real_text(self, *a, **k)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(Path, "read_bytes", locked_bytes)
        m.setattr(Path, "read_text", locked_text)
        assert pbt.load_pickban_targets(patch="16.11.1") == {}
    # Same mtime, lock released: the real table loads (nothing was cached).
    assert pbt.load_pickban_targets(patch="16.11.1")["patch"] == "16.11.1"


# --- backfill check: every committed table reads the same as before -------

def _reference_slice(rows, top_n):
    """The pre-hardening slice rule, for byte-identity on valid tables."""
    out = []
    for row in rows:
        if isinstance(row, dict) and row.get("champion"):
            out.append(row)
        if len(out) >= top_n:
            break
    return out


def _committed_patches():
    ds = _ROOT / "data" / "daemon_slayer"
    return sorted(p.parent.name for p in ds.glob("*/pickban_targets.json"))


@pytest.mark.parametrize("patch", _committed_patches())
def test_committed_tables_read_unchanged(patch):
    pbt._CACHE.clear()
    raw = json.loads((_ROOT / "data" / "daemon_slayer" / patch
                      / "pickban_targets.json").read_text(encoding="utf-8"))
    targets = raw["targets"]
    assert targets
    for champ, entry in targets.items():
        for top_n in (1, 3, 5, 8):
            assert pbt.counters_for(champ, top_n=top_n, patch=patch) == \
                _reference_slice(entry["counters"], top_n)
            assert pbt.good_against(champ, top_n=top_n, patch=patch) == \
                _reference_slice(entry["good_against"], top_n)
        exp = [r for r in entry["counters"] if r["champion"] != "Zed"][:3]
        assert pbt.ban_suggestions(champ, enemy_comp=["Zed"], patch=patch) \
            == exp
        for rows in (entry["counters"], entry["good_against"]):
            for r in rows:
                assert all(isinstance(v, (int, float))
                           and not isinstance(v, bool) and math.isfinite(v)
                           for k, v in r.items() if k != "champion")
    pbt._CACHE.clear()
