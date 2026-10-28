"""RM-990: four DS readers picked the "newest" patch dir by STRING sort.

A string sort puts ``16.9.1`` above ``16.21.1`` and ``17.9.1`` above
``17.10.1``, and it ranks a non-patch dir such as ``laning_scenarios`` above
every patch, because a letter sorts after a digit. Each site below falls back
to the newest patch dir when its first choice is missing:

- ``tools/daemon_slayer_wiki_stats_extract.py`` ``_load_meta_champ_data``:
  the exact-patch DDragon ``champion.json`` is absent (a fresh patch whose
  mirror has not been refreshed yet);
- ``tools/ds_windup_offset_compare.py`` ``_resolve_patch``: ``current.txt``
  is absent; ``data/daemon_slayer/`` also holds ``build_orders/`` and
  ``laning_scenarios/``, so the string sort returned ``laning_scenarios``;
- ``tools/replay_build_order_validate.py`` ``_load_item_names``: the newest
  DDragon ``item.json`` for the carrier summary;
- ``core/personal_build_wr.py`` ``_item_meta``: the newest
  ``data/daemon_slayer/<patch>/items.json`` (found by the verifier's sibling
  sweep), whose gold totals decide which items count as completed.

Today every mirrored patch is 16.1x / 16.2x, so the defect is latent until a
one-digit minor sits beside a two-digit one (17.1 .. 17.9 next to 17.10).
The fix follows the numeric key the sibling tools already use
(``tools/ds_wiki_staleness_check.py``, ``tools/ddragon_mirror_refresh.py``):
semver dirs only, compared as integer tuples. Every test is synthetic and
writes only under tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import daemon_slayer_wiki_stats_extract as W  # noqa: E402
import ds_windup_offset_compare as WU  # noqa: E402
import replay_build_order_validate as R  # noqa: E402

from core import personal_build_wr as pbw  # noqa: E402
from core.failed_load_gate import FailedLoadGate  # noqa: E402


def _write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _champ_mirror(base: Path, patch: str) -> None:
    _write(base / patch / "champion.json", {"data": {"Ahri": {"name": f"Ahri {patch}"}}})


def test_wiki_stats_fallback_picks_numerically_newest_mirror(tmp_path, monkeypatch):
    for patch in ("16.9.1", "16.21.1", "16.3.1"):
        _champ_mirror(tmp_path, patch)
    monkeypatch.setattr(W, "META_DDRAGON_DIR", tmp_path)
    data = W._load_meta_champ_data("16.22.1")
    assert data["Ahri"]["name"] == "Ahri 16.21.1"


def test_wiki_stats_fallback_ignores_a_non_patch_dir(tmp_path, monkeypatch):
    _champ_mirror(tmp_path, "16.21.1")
    _champ_mirror(tmp_path, "scratch")
    monkeypatch.setattr(W, "META_DDRAGON_DIR", tmp_path)
    assert W._load_meta_champ_data("16.22.1")["Ahri"]["name"] == "Ahri 16.21.1"


def test_wiki_stats_exact_patch_still_wins(tmp_path, monkeypatch):
    for patch in ("16.9.1", "16.21.1"):
        _champ_mirror(tmp_path, patch)
    monkeypatch.setattr(W, "META_DDRAGON_DIR", tmp_path)
    assert W._load_meta_champ_data("16.9.1")["Ahri"]["name"] == "Ahri 16.9.1"


def test_windup_resolve_patch_without_current_txt_picks_newest_patch(tmp_path, monkeypatch):
    for name in ("16.9.1", "16.21.1", "build_orders", "laning_scenarios"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(WU, "DS_DATA", tmp_path)
    assert WU._resolve_patch(None) == "16.21.1"


def test_windup_resolve_patch_prefers_current_txt(tmp_path, monkeypatch):
    for name in ("16.9.1", "16.21.1"):
        (tmp_path / name).mkdir()
    (tmp_path / "current.txt").write_text("16.9.1\n", encoding="utf-8")
    monkeypatch.setattr(WU, "DS_DATA", tmp_path)
    assert WU._resolve_patch(None) == "16.9.1"


def test_personal_build_wr_item_meta_reads_the_numerically_newest_patch(tmp_path, monkeypatch):
    # The gold total feeds LEGENDARY_GOLD_FLOOR in _is_core, so a stale patch
    # can change which items are ranked, not only their display names.
    for patch, gold in (("16.9.1", 900), ("16.21.1", 3000)):
        _write(tmp_path / patch / "items.json",
               {"data": {"3089": {"name": f"Cap {patch}", "gold": {"total": gold}}}})
    _write(tmp_path / "scratch" / "items.json",
           {"data": {"3089": {"name": "Cap scratch", "gold": {"total": 1}}}})
    monkeypatch.setattr(pbw, "_DDRAGON_ROOT", tmp_path)
    monkeypatch.setattr(pbw, "_META_GATE", FailedLoadGate())
    pbw.reset_cache()
    try:
        assert pbw._item_meta() == {"3089": {"name": "Cap 16.21.1", "gold": 3000}}
    finally:
        pbw.reset_cache()


def test_replay_item_names_read_the_numerically_newest_mirror(tmp_path, monkeypatch):
    base = tmp_path / "data" / "meta_build" / "ddragon"
    for patch in ("16.9.1", "16.21.1"):
        _write(base / patch / "item.json", {"data": {"3089": {"name": f"Cap {patch}"}}})
    (base / "scratch").mkdir()
    _write(base / "scratch" / "item.json", {"data": {"3089": {"name": "Cap scratch"}}})
    monkeypatch.setattr(R, "_ROOT", tmp_path)
    assert R._load_item_names() == {"3089": "Cap 16.21.1"}
