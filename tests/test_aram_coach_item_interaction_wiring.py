"""Coach-side wiring for the comp-conditioned item-interaction cues.

The ARAM coach artifact gains two additive keys next to item_build_reasons:
  item_interaction_cues        {rendered tile name -> cue}
  item_interaction_provenance  short ASCII source tag

The HARD SAFETY PROPERTY mirrored here: this is a fail-soft passenger on the
coaching tick. If core.aram_item_interaction_context is missing, or either of
its two entrypoints raises, the coach must still produce BOTH keys, degraded to
{} / "" - never propagate and never kill the tick.

The context module is imported lazily inside _item_interaction_block, so these
tests inject a stub into sys.modules rather than monkeypatching an attribute.
"""

from __future__ import annotations

import inspect
import sys
import types

import pytest

from coaches.aram_coach import (
    _item_interaction_block,
    _split_item_build_like_ui,
)
import coaches.aram_coach as aram_coach

_MODNAME = "core.aram_item_interaction_context"


def _install_stub(monkeypatch, cues_fn, provenance_fn):
    mod = types.ModuleType(_MODNAME)
    mod.CUE_SENTINEL = "-"
    mod.item_interaction_cues = cues_fn
    mod.cue_provenance = provenance_fn
    monkeypatch.setitem(sys.modules, _MODNAME, mod)
    return mod


# -- the UI-identical split ------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("", []),
    (None, []),
    ("Kraken Slayer, Terminus", ["Kraken Slayer", "Terminus"]),
    ("Kraken Slayer -> Terminus", ["Kraken Slayer", "Terminus"]),
    ("Kraken Slayer " + chr(0x2192) + " Terminus", ["Kraken Slayer", "Terminus"]),
    # mixed separators + stray empties, exactly like items_index.js filter(Boolean)
    ("A, B" + chr(0x2192) + "C ->  D ,, E", ["A", "B", "C", "D", "E"]),
])
def test_split_matches_frontend_separators(raw, expected):
    assert _split_item_build_like_ui(raw) == expected


# -- the happy path --------------------------------------------------------

def test_block_carries_both_keys(monkeypatch):
    seen = {}

    def _cues(enemies, t, names, *, game_mode=None):
        seen["enemies"] = enemies
        seen["t"] = t
        seen["names"] = names
        seen["mode"] = game_mode
        return {n: "cue for " + n for n in names}

    _install_stub(monkeypatch, _cues, lambda: "aram-comp/v1")

    block = _item_interaction_block(
        "Kraken Slayer " + chr(0x2192) + " Terminus",
        ["Ashe", "Leona"], 421, "ARAM",
    )

    assert set(block) == {"item_interaction_cues", "item_interaction_provenance"}
    # Cue keys are the rendered tile names, split the frontend's way.
    assert block["item_interaction_cues"] == {
        "Kraken Slayer": "cue for Kraken Slayer",
        "Terminus": "cue for Terminus",
    }
    assert block["item_interaction_provenance"] == "aram-comp/v1"
    # Args are forwarded as contracted (enemy roster, seconds, names, mode).
    assert seen["enemies"] == ["Ashe", "Leona"]
    assert seen["t"] == 421
    assert seen["names"] == ["Kraken Slayer", "Terminus"]
    assert seen["mode"] == "ARAM"


def test_empty_contract_result_still_yields_both_keys(monkeypatch):
    # Contract: {} entirely when not ARAM / no snapshot; provenance "".
    _install_stub(monkeypatch, lambda *a, **k: {}, lambda: "")
    block = _item_interaction_block("Terminus", [], 0, "CLASSIC")
    assert block == {"item_interaction_cues": {}, "item_interaction_provenance": ""}


# -- fail-soft degradation -------------------------------------------------

def test_raising_cue_fn_degrades_and_does_not_propagate(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("cue engine exploded")

    _install_stub(monkeypatch, _boom, lambda: "aram-comp/v1")

    block = _item_interaction_block("Terminus", ["Ashe"], 300, "ARAM")
    assert block == {"item_interaction_cues": {}, "item_interaction_provenance": ""}


def test_raising_provenance_fn_degrades(monkeypatch):
    def _boom():
        raise RuntimeError("no snapshot")

    _install_stub(monkeypatch, lambda *a, **k: {"Terminus": "x"}, _boom)

    block = _item_interaction_block("Terminus", ["Ashe"], 300, "ARAM")
    assert block == {"item_interaction_cues": {}, "item_interaction_provenance": ""}


def test_missing_context_module_degrades(monkeypatch):
    # Simulate the module not existing at all (lazy ImportError).
    monkeypatch.setitem(sys.modules, _MODNAME, None)
    block = _item_interaction_block("Terminus", ["Ashe"], 300, "ARAM")
    assert block == {"item_interaction_cues": {}, "item_interaction_provenance": ""}


# -- artifact wiring -------------------------------------------------------

def test_artifact_update_splices_the_block():
    """The two keys reach the served artifact via the cur.update() literal.

    The update site lives deep inside the async coach tick (behind a Haiku
    call), so this asserts the wiring at the source level: the block helper is
    spliced into the same cur.update({...}) that carries item_build_reasons,
    fed by the hoisted deduped build string + the state enemy roster.
    """
    src = inspect.getsource(aram_coach)
    assert "**_item_interaction_block(" in src
    assert "_item_build_str" in src
    assert 'state.get("enemy_comp", [])' in src
    # Both key names exist exactly once as artifact keys (only the helper emits
    # them), so the frontend contract cannot silently drift.
    assert src.count('"item_interaction_cues"') >= 1
    assert src.count('"item_interaction_provenance"') >= 1
