"""The two DS seam-override table builders reproduce their committed tables.

S144-D-240 .. S144-D-243 (2026-11-09, s144 ds lane cycle 891). The two
ops/audit/ds_perm_swarm builders that feed DEFAULT-OFF seams:

* ``build_marksman_offclass_exempt.py`` -> ``agents/daemon_slayer/
  marksman_offclass_exempt.json`` (``rank._offclass_win_exemptions``);
* ``build_aram_archetype_override.py`` -> ``core/aram_archetype_override.json``
  (``core.archetype_picks.aram_archetype_override``).

Measured before the fix: a fresh marksman build dropped the hand-seeded Quinn
row (A-20 / RM-89: Profane Hydra + Umbral Glaive) and the
``_manual_entries_comment`` that said a regeneration "MUST re-add it". The
builder's own docstring tells you to re-run it after a cross-eval refresh, so
following it silently shrank Quinn's exemption to nothing (S144-D-240). Neither
builder had a ``--check`` mode, so nothing compared the committed tables with a
fresh build (S144-D-241). Both stamp a top-level ``patch`` from
``data/daemon_slayer/current.txt`` that no loader reads (S144-D-242), and the
ARAM table was already a byte-exact fresh build apart from that stamp
(S144-D-243 pins it).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import rank
from core import archetype_picks as ap
from ops.audit.ds_perm_swarm import build_aram_archetype_override as aram
from ops.audit.ds_perm_swarm import build_marksman_offclass_exempt as mark
from ops.audit.ds_perm_swarm import credit_table_check

_REPO = Path(__file__).resolve().parent.parent
_DS_DATA = _REPO / "data" / "daemon_slayer"
_MARK = _REPO / "agents" / "daemon_slayer" / "marksman_offclass_exempt.json"
_ARAM = _REPO / "core" / "aram_archetype_override.json"
_BUILDERS = {"marksman": (mark, _MARK), "aram": (aram, _ARAM)}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _patch_key(patch: str) -> tuple[int, ...]:
    return tuple(int(p) for p in patch.split("."))


def _copy(path: Path, tmp_path: Path) -> Path:
    out = tmp_path / path.name
    out.write_bytes(path.read_bytes())
    return out


# ---------------------------------------------------------------- S144-D-240


def test_the_builder_keeps_the_hand_seeded_quinn_row():
    built = mark.with_manual_entries(mark.build_table())
    assert built["champions"]["Quinn"] == ["Profane Hydra", "Umbral Glaive"]
    assert "_manual_entries_comment" in built
    keys = list(built)
    assert keys.index("_manual_entries_comment") == keys.index("_comment") + 1


def test_the_computed_build_alone_does_not_reach_quinn():
    """The manual row is the only source of Quinn's exemption (not dead code)."""
    assert "Quinn" not in mark.build_table()["champions"]
    assert set(mark._MANUAL_ENTRIES) == {"Quinn"}


def test_manual_rows_union_with_computed_rows_and_stay_sorted():
    table = {"_comment": "c", "patch": "x", "champions": {
        "Quinn": ["Umbral Glaive", "Black Cleaver"], "Ezreal": ["Trinity Force"]}}
    out = mark.with_manual_entries(table)
    assert out["champions"]["Quinn"] == ["Black Cleaver", "Profane Hydra",
                                         "Umbral Glaive"]
    assert list(out["champions"]) == sorted(out["champions"])
    assert table["champions"]["Quinn"] == ["Umbral Glaive", "Black Cleaver"]


def test_every_manual_name_is_a_denied_offclass_name():
    for champ, names in mark._MANUAL_ENTRIES.items():
        assert names, champ
        assert set(names) <= set(rank.OFFCLASS_MARKSMAN_ITEM_NAMES), champ


def test_a_manual_name_outside_the_deny_set_raises(monkeypatch):
    monkeypatch.setattr(mark, "_MANUAL_ENTRIES", {"Quinn": ("Infinity Edge",)})
    with pytest.raises(ValueError, match="Infinity Edge"):
        mark.with_manual_entries({"_comment": "c", "champions": {}})


def test_write_mode_keeps_quinn(tmp_path, monkeypatch, capsys):
    out = tmp_path / _MARK.name
    monkeypatch.setattr(mark, "_OUT_PATH", out)
    assert mark.main([]) == 0
    assert _read(out)["champions"]["Quinn"] == ["Profane Hydra", "Umbral Glaive"]
    assert "Quinn" in capsys.readouterr().out


# ---------------------------------------------------------------- S144-D-241


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_check_passes_on_the_committed_table(label, tmp_path, monkeypatch, capsys):
    mod, path = _BUILDERS[label]
    out = _copy(path, tmp_path)
    monkeypatch.setattr(mod, "_OUT_PATH", out)
    assert mod.main(["--check"]) == 0
    assert "in sync" in capsys.readouterr().out
    assert out.read_bytes() == path.read_bytes()


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_check_reports_content_drift(label, tmp_path, monkeypatch, capsys):
    mod, path = _BUILDERS[label]
    out = _copy(path, tmp_path)
    table = _read(out)
    table["champions"].pop(sorted(table["champions"])[0])
    out.write_text(json.dumps(table, indent=2, ensure_ascii=True) + "\n",
                   encoding="utf-8")
    before = out.read_bytes()
    monkeypatch.setattr(mod, "_OUT_PATH", out)
    assert mod.main(["--check"]) == 2
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("DRIFT"), err
    assert out.read_bytes() == before


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_check_reports_a_missing_table(label, tmp_path, monkeypatch):
    mod, _ = _BUILDERS[label]
    monkeypatch.setattr(mod, "_OUT_PATH", tmp_path / "absent.json")
    assert mod.main(["--check"]) == 2
    assert not (tmp_path / "absent.json").exists()


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_check_ignores_a_stamp_only_difference(label, tmp_path, monkeypatch):
    mod, path = _BUILDERS[label]
    out = _copy(path, tmp_path)
    text = out.read_text(encoding="utf-8")
    stamp = _read(out)["patch"]
    out.write_text(text.replace(f'"patch": "{stamp}"', '"patch": "1.1.1"', 1),
                   encoding="utf-8")
    monkeypatch.setattr(mod, "_OUT_PATH", out)
    assert mod.main(["--check"]) == 0


def test_the_stamp_rule_still_catches_format_drift(tmp_path):
    out = _copy(_ARAM, tmp_path)
    built = aram.build_table()
    assert credit_table_check.committed_matches_patch(out, built)
    out.write_text(json.dumps(_read(out), indent=1, ensure_ascii=True) + "\n",
                   encoding="utf-8")
    assert not credit_table_check.committed_matches_patch(out, built)
    out.write_text("{not json", encoding="utf-8")
    assert not credit_table_check.committed_matches_patch(out, built)


# ---------------------------------------------------------------- S144-D-242


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_patch_names_an_on_disk_snapshot_not_newer_than_current(label):
    _, path = _BUILDERS[label]
    stamp = _read(path)["patch"]
    assert isinstance(stamp, str) and re.fullmatch(r"\d+\.\d+\.\d+", stamp), stamp
    assert (_DS_DATA / stamp / "items.json").is_file(), stamp
    current = (_DS_DATA / "current.txt").read_text(encoding="utf-8").strip()
    assert _patch_key(stamp) <= _patch_key(current)


def test_the_marksman_loader_ignores_patch(tmp_path, monkeypatch):
    table = _read(_MARK)
    table["patch"] = ""
    copy = tmp_path / _MARK.name
    copy.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setattr(rank, "_OFFCLASS_EXEMPT_CACHE", None)
    before = dict(rank._load_offclass_exemptions())
    monkeypatch.setattr(rank, "_OFFCLASS_EXEMPT_CACHE", None)
    monkeypatch.setattr(rank, "_OFFCLASS_EXEMPT_PATH", copy)
    after = dict(rank._load_offclass_exemptions())
    monkeypatch.setattr(rank, "_OFFCLASS_EXEMPT_CACHE", None)
    assert before and after == before


def test_the_aram_loader_ignores_patch(tmp_path, monkeypatch):
    table = _read(_ARAM)
    table["patch"] = ""
    copy = tmp_path / _ARAM.name
    copy.write_text(json.dumps(table), encoding="utf-8")
    ap._invalidate_aram_overrides_cache()
    try:
        before = dict(ap._load_aram_overrides())
        monkeypatch.setattr(ap, "_ARAM_OVERRIDE_PATH", copy)
        ap._invalidate_aram_overrides_cache()
        after = dict(ap._load_aram_overrides())
    finally:
        monkeypatch.undo()
        ap._invalidate_aram_overrides_cache()
    assert before and after == before


# ---------------------------------------------------------------- S144-D-243


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_out_path_is_the_table_its_loader_reads(label):
    mod, path = _BUILDERS[label]
    assert Path(mod._OUT_PATH) == path
    loader_path = (rank._OFFCLASS_EXEMPT_PATH if label == "marksman"
                   else ap._ARAM_OVERRIDE_PATH)
    assert Path(loader_path) == path


@pytest.mark.parametrize("label", list(_BUILDERS))
def test_constants_in_the_table_match_the_builder(label):
    mod, path = _BUILDERS[label]
    table = _read(path)
    assert table["wr_margin"] == mod.WR_MARGIN
    if label == "marksman":
        assert table["min_usage"] == mod.MIN_USAGE
    else:
        assert table["min_item_n"] == mod.MIN_ITEM_N
    assert (_REPO / table["generated_from"].split("/{")[0]).is_dir()
