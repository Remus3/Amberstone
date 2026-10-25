"""Guard: a generic passive-PROSE number drift checker over every engine item row.

RM-808 (c). RM-804 guarded the passive-prose numbers of the 7 items the RM-766
verifier happened to list from the 16.20.1 -> 16.21.1 description diff; every
other engine item row had no guard, so the next patch that moves a number in a
passive clause (not the ``<stats>`` block, which the pen / AH checkers and the
extractor read) would again reach the engine silently.

``ops/audit/item_prose_drift_check.py`` compares, for EVERY ``ITEM_EFFECTS``
row, the ordered numbers of the DDragon passive prose (description minus the
``<stats>`` block, tags stripped) at ``current.txt`` against the previous
snapshot on disk. A moved row must carry a ``REVIEWED[<current patch>]`` entry
naming its new numbers; an unreviewed move, a row dropped from DDragon, or a
review entry that no longer matches the live prose fails.

This module pins:

  1. live: IN SYNC at current.txt (16.21.1: exactly the 10 RM-804 rows moved,
     every one reviewed), over a non-trivial row count;
  2. red on a planted drift (a synthetic data root), green once reviewed;
  3. scope: a non-engine item's drift and a ``<stats>``-only change are not
     prose drift; a dropped row is; a stale review entry fails;
  4. the previous snapshot is chosen by VERSION order (16.9.1 < 16.10.1), and
     a data root with no previous snapshot exits 2, never "in sync".

Repo-level (not agents/daemon_slayer/tests/) on purpose, like the pen / AH
guards: it imports the ops/audit tool. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import json
from pathlib import Path

import ops.audit.item_prose_drift_check as pdc

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data" / "daemon_slayer"

# Real engine rows used by the synthetic fixtures.
_BORK = "3153"
_HUBRIS = "6697"
_NOT_ENGINE = "999999"


def _write_patch(root: Path, patch: str, items: dict[str, str]) -> None:
    d = root / patch
    d.mkdir(parents=True)
    blob = {
        "version": patch,
        "data": {iid: {"name": f"item {iid}", "description": desc}
                 for iid, desc in items.items()},
    }
    (d / "items.json").write_text(json.dumps(blob), encoding="utf-8")


def _desc(stats: str, prose: str) -> str:
    return f"<mainText><stats>{stats}</stats><br><br><passive>P</passive><br>{prose}</mainText>"


def _fixture(tmp_path: Path, new_bork_prose: str, *, new_stats: str = "40 AD",
             extra_new: dict[str, str] | None = None,
             drop_hubris: bool = False) -> Path:
    root = tmp_path / "ds"
    old = {
        _BORK: _desc("40 AD", "Deal 9% current Health, 1.5 s, 30% slow"),
        _HUBRIS: _desc("55 AD", "gain 12 AD plus 3 per kill for 90 seconds"),
        _NOT_ENGINE: _desc("1 AP", "gain 5 things"),
    }
    new = dict(old)
    new[_BORK] = _desc(new_stats, new_bork_prose)
    if drop_hubris:
        del new[_HUBRIS]
    if extra_new:
        new.update(extra_new)
    _write_patch(root, "16.9.1", {k: v.replace("9%", "7%") for k, v in old.items()})
    _write_patch(root, "16.10.1", old)
    _write_patch(root, "16.11.1", new)
    (root / "current.txt").write_text("16.11.1\n", encoding="utf-8")
    return root


def _check(root: Path, reviewed=None):
    return pdc.check(data_root=root, engine_ids={_BORK, _HUBRIS},
                     reviewed={} if reviewed is None else reviewed)


# -- 1. live ------------------------------------------------------------------


def test_live_in_sync_at_current_patch() -> None:
    rep = pdc.check()
    current = (_DATA / "current.txt").read_text(encoding="utf-8").strip()
    assert rep.current == current
    assert rep.previous is not None
    # Non-vacuous: the engine registers hundreds of rows present in both snapshots.
    assert rep.compared > 500, rep.compared
    assert not rep.unreviewed, rep.unreviewed
    assert not rep.removed, rep.removed
    assert not rep.stale_reviews, rep.stale_reviews
    assert rep.drift is False
    assert pdc.main([]) == 0


def test_live_reviewed_set_is_the_rm804_set() -> None:
    # 16.20.1 -> 16.21.1 moved exactly the RM-804 rows; each is reviewed.
    rep = pdc.check()
    if rep.current != "16.21.1":
        return  # a later patch carries its own REVIEWED block (test 1 guards it)
    assert sorted(rep.reviewed_ok, key=int) == sorted(
        ["6621", "226621", "326621", "6697", "226697", "2520", "443079",
         "444636", "447100", "447110"], key=int)


# -- 2. planted drift ----------------------------------------------------------


def test_planted_drift_is_red(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 12% current Health, 1.5 s, 30% slow")
    rep = _check(root)
    assert rep.previous == "16.10.1"
    assert list(rep.unreviewed) == [_BORK]
    old, new = rep.unreviewed[_BORK]
    assert old == ("9", "1.5", "30") and new == ("12", "1.5", "30")
    assert rep.drift is True


def test_planted_drift_main_exit_code(tmp_path: Path, monkeypatch) -> None:
    root = _fixture(tmp_path, "Deal 12% current Health, 1.5 s, 30% slow")
    monkeypatch.setattr(pdc, "load_engine_ids", lambda: {_BORK, _HUBRIS})
    monkeypatch.setattr(pdc, "REVIEWED", {})
    assert pdc.main(["--data-root", str(root)]) == 1


def test_reviewed_drift_is_green(tmp_path: Path, monkeypatch) -> None:
    root = _fixture(tmp_path, "Deal 12% current Health, 1.5 s, 30% slow")
    reviewed = {"16.11.1": {_BORK: ("12", "1.5", "30")}}
    rep = _check(root, reviewed)
    assert rep.drift is False
    assert rep.reviewed_ok == [_BORK]
    monkeypatch.setattr(pdc, "load_engine_ids", lambda: {_BORK, _HUBRIS})
    monkeypatch.setattr(pdc, "REVIEWED", reviewed)
    assert pdc.main(["--data-root", str(root)]) == 0


def test_a_review_for_another_patch_does_not_cover_the_drift(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 12% current Health, 1.5 s, 30% slow")
    rep = _check(root, {"16.10.1": {_BORK: ("12", "1.5", "30")}})
    assert list(rep.unreviewed) == [_BORK]


# -- 3. scope -------------------------------------------------------------------


def test_non_engine_drift_is_ignored(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 9% current Health, 1.5 s, 30% slow",
                    extra_new={_NOT_ENGINE: _desc("1 AP", "gain 6 things")})
    rep = _check(root)
    assert rep.drift is False
    assert rep.compared == 2


def test_stats_block_only_change_is_not_prose_drift(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 9% current Health, 1.5 s, 30% slow",
                    new_stats="45 AD")
    assert _check(root).drift is False


def test_dropped_row_is_drift(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 9% current Health, 1.5 s, 30% slow",
                    drop_hubris=True)
    rep = _check(root)
    assert rep.removed == [_HUBRIS]
    assert rep.drift is True
    # A recorded removal (None) is a reviewed state.
    assert _check(root, {"16.11.1": {_HUBRIS: None}}).drift is False


def test_stale_review_entry_fails(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 12% current Health, 1.5 s, 30% slow")
    # Wrong numbers for the moved row.
    rep = _check(root, {"16.11.1": {_BORK: ("11", "1.5", "30")}})
    assert _BORK in rep.stale_reviews
    assert rep.drift is True
    # An entry for a row that did not move is also stale (keeps the table honest).
    rep2 = _check(root, {"16.11.1": {_BORK: ("12", "1.5", "30"),
                                     _HUBRIS: ("12", "3", "90")}})
    assert list(rep2.stale_reviews) == [_HUBRIS]
    assert rep2.drift is True


def test_prose_numbers_strip_the_stats_block_and_tags() -> None:
    desc = _desc("<attention>55</attention> AD", "gain <physicalDamage>12 AD</physicalDamage> for 1.5 s")
    assert pdc.prose_numbers(desc) == ("12", "1.5")
    assert pdc.prose_numbers("") == ()
    assert pdc.prose_numbers(None) == ()


# -- 4. snapshot selection -----------------------------------------------------


def test_previous_patch_uses_version_order(tmp_path: Path) -> None:
    root = _fixture(tmp_path, "Deal 9% current Health, 1.5 s, 30% slow")
    assert pdc.list_patches(root) == ["16.9.1", "16.10.1", "16.11.1"]
    assert pdc.previous_patch(root, "16.11.1") == "16.10.1"
    assert pdc.previous_patch(root, "16.10.1") == "16.9.1"
    assert pdc.previous_patch(root, "16.9.1") is None


def test_no_previous_snapshot_exits_2(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "ds"
    _write_patch(root, "16.11.1", {_BORK: _desc("40 AD", "9%")})
    (root / "current.txt").write_text("16.11.1\n", encoding="utf-8")
    monkeypatch.setattr(pdc, "load_engine_ids", lambda: {_BORK})
    assert pdc.main(["--data-root", str(root)]) == 2
    assert pdc.main(["--data-root", str(tmp_path / "missing")]) == 2


def test_default_data_root_tracks_current_txt() -> None:
    assert pdc.DATA_ROOT == _DATA
    assert pdc.check().current == (_DATA / "current.txt").read_text(encoding="utf-8").strip()
