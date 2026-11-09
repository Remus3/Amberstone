"""S144-P-569 - uncalled private helpers are gone (two in the post-game collector, one in the DS extractor); the live name maps stay.

``lcu/lcu_postgame_collector.py`` carried ``_item_name(item_id)`` and ``_rune_name(rune_id)``, thin readers over the
module caches ``_ITEM_MAP`` / ``_RUNE_MAP``. No module, test, script or doc calls either (measured 2026-11-09 with a
whole-word search over every tracked ``.py``, ``.js``, ``.mjs``, ``.md``, ``.ps1``, ``.json``, ``.txt``, ``.bat`` and
``.yml`` file: each name occurs only at its own definition, and the word census counts string literals too, so no
``getattr`` spelling hides a caller).

The caches themselves are NOT dead and this test pins that: ``PostgameCollector.__init__`` warms them and
``_save_eog`` / ``_save_item_events`` receive them as ``item_map`` / ``rune_map`` to fill the stored item and rune
names. A first draft of this slice removed the whole chain and the suite caught it, so the map half is pinned live.
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

from lcu import lcu_postgame_collector as lpc

_SRC = Path(lpc.__file__).read_text(encoding="utf-8")


def test_the_uncalled_name_wrappers_are_gone():
    for name in ("_item_name", "_rune_name"):
        assert not hasattr(lpc, name), name
        assert re.search(rf"\b{name}\b", _SRC) is None, name


def test_the_name_maps_and_their_loaders_stay_wired():
    assert callable(lpc._load_item_map)
    assert callable(lpc._load_rune_map)
    assert isinstance(lpc._ITEM_MAP, dict)
    assert isinstance(lpc._RUNE_MAP, dict)
    # the two readers of the caches: the save calls hand them to the writers
    assert re.search(r"_save_eog\([^)]*_ITEM_MAP,\s*_RUNE_MAP\)", _SRC)
    assert re.search(r"_save_item_events\([^)]*_ITEM_MAP\)", _SRC)


def test_construction_still_warms_the_maps(monkeypatch):
    items = mock.Mock(return_value={1: "a"})
    runes = mock.Mock(return_value={2: "b"})
    monkeypatch.setattr(lpc, "_ensure_schema", mock.Mock())
    monkeypatch.setattr(lpc, "_ITEM_MAP", {})
    monkeypatch.setattr(lpc, "_RUNE_MAP", {})
    monkeypatch.setattr(lpc, "_load_item_map", items)
    monkeypatch.setattr(lpc, "_load_rune_map", runes)
    lpc.PostgameCollector(mock.MagicMock())
    assert lpc._ITEM_MAP == {1: "a"}
    assert lpc._RUNE_MAP == {2: "b"}
    items.assert_called_once()
    runes.assert_called_once()


def test_the_uncalled_extractor_factory_helper_is_gone():
    """``tools/daemon_slayer_extract.py`` ``_extract_obj_factory`` had no caller either (same whole-word census); its
    sibling ``_extract_roles`` walks the same ``_OBJ_FACTORY_RE`` headers and stays."""
    from tools import daemon_slayer_extract as dse

    assert not hasattr(dse, "_extract_obj_factory")
    assert callable(dse._extract_roles)
    assert dse._OBJ_FACTORY_RE.search("1,(a,i,e)=>{i.exports={x:1}")
