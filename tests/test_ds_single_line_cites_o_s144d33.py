"""Guard: ``_rune_self_heal.py`` cites ``ehp`` by symbol, not line (RM-1053 part).

Measured 2026-10-30 at ENGINE 1.290.0. The module carried 10 line cites,
all into ``ehp.py``, and every one had rotted:

- ``ehp.py:356`` (x3) for ``_MISSING_HP_SHARE_FOR_HEALS = 0.5``; the constant
  now sits on :372.
- ``ehp.py:342`` (x3) for ``_FIGHT_WINDOW_S = 6.0``; now on :358.
- ``ehp.py:1501`` (x2) for ``missing_hp = hp * _MISSING_HP_SHARE_FOR_HEALS``;
  that line of ``compute_ehp`` now sits some 350 lines lower.
- ``ehp.py:791`` (x2) for the ``heal_amp_mult`` placement; that line is now
  an unrelated ``_MODE_MIRROR_ID_PREFIXES`` comment. The placement lives in
  ``compute_ehp``'s ``heal_total`` composition, which since R142 also carries
  this module's own ``rune_self_heal_hp`` term.

The tests below pin the cites and the claims they carried by symbol instead.
Sibling sweep: no other module or test outside these RM-1053 guards cites
those four ``ehp.py`` lines.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from agents.daemon_slayer import _rune_self_heal, ehp

REPO = Path(__file__).resolve().parent.parent
DS = REPO / "agents" / "daemon_slayer"
_LINE_CITE = re.compile(r"(?<![\w.])\w+\.py:\d|``:\d|\blines \d")

TARGETS = {
    "_rune_self_heal.py": (
        "``ehp._MISSING_HP_SHARE_FOR_HEALS = 0.5`` already defines",
        "resolves the pool ONCE inside ``ehp.compute_ehp`` (``missing_hp = hp * "
        "_MISSING_HP_SHARE_FOR_HEALS``)",
        "Same treatment for ``_FIGHT_WINDOW_S = 6.0`` (``ehp._FIGHT_WINDOW_S``).",
        "``_FIGHT_WINDOW_S = 6.0`` seconds (``ehp._FIGHT_WINDOW_S``, the same "
        "window the lifesteal heal pool accumulates over)",
        "BEFORE ``heal_amp_mult`` (the ``heal_total`` composition in "
        "``ehp.compute_ehp``)",
        "ehp._MISSING_HP_SHARE_FOR_HEALS - the Phase 6.5 mid-fight HP-share "
        "assumption",
        "ehp._FIGHT_WINDOW_S - the modeled sustained-engagement window",
        "defaults to the engine's existing ``ehp._MISSING_HP_SHARE_FOR_HEALS`` "
        "and is clamped",
        "the convention ``ehp.compute_ehp`` already resolves once as "
        "``missing_hp``",
    ),
}


def _flat(text: str) -> str:
    return " ".join(text.replace("#", " ").split())


def _compute_ehp_body() -> str:
    return " ".join(inspect.getsource(ehp.compute_ehp).split())


def test_pattern_matches_the_old_shapes():
    for sample in (
        "NOT RE-INVENTED. ``ehp.py:356`` already",
        "resolves the pool ONCE at ``ehp.py:1501`` (``missing_hp = hp *",
        "for ``_FIGHT_WINDOW_S = 6.0`` (``ehp.py:342``).",
        "``heal_total`` should add it BEFORE ``heal_amp_mult`` (``ehp.py:791``) so",
        "# ehp.py:356 - the Phase 6.5 mid-fight HP-share assumption",
        "# ehp.py:342 - the modeled sustained-engagement window in seconds",
    ):
        assert _LINE_CITE.search(sample), sample
    for symbols in TARGETS.values():
        for sample in symbols:
            assert not _LINE_CITE.search(sample), sample


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_no_line_cite_left(name):
    text = (DS / name).read_text(encoding="utf-8")
    hits = [
        f"{name}:{n}: {line.strip()}"
        for n, line in enumerate(text.splitlines(), 1)
        if _LINE_CITE.search(line)
    ]
    assert not hits, "cite by symbol, not line:\n" + "\n".join(hits)


@pytest.mark.parametrize("name", sorted(TARGETS))
def test_names_the_symbols(name):
    flat = _flat((DS / name).read_text(encoding="utf-8"))
    for symbol in TARGETS[name]:
        assert symbol in flat, f"{name}: {symbol}"


def test_cited_constants_exist_with_the_restated_values():
    assert ehp._MISSING_HP_SHARE_FOR_HEALS == 0.5
    assert ehp._FIGHT_WINDOW_S == 6.0
    share = ehp._MISSING_HP_SHARE_FOR_HEALS
    assert share == _rune_self_heal._MISSING_HP_SHARE_FOR_HEALS
    assert _rune_self_heal._FIGHT_WINDOW_S == ehp._FIGHT_WINDOW_S


def test_compute_ehp_resolves_missing_hp_once():
    src = inspect.getsource(ehp)
    assert src.count("missing_hp = hp * _MISSING_HP_SHARE_FOR_HEALS") == 1
    assert "missing_hp = hp * _MISSING_HP_SHARE_FOR_HEALS" in _compute_ehp_body()


def test_compute_ehp_folds_the_self_heal_before_heal_amp_mult():
    assert (
        "heal_total = ( heal_item_total + heal_lifesteal + rune_heal_hp + "
        "rune_self_heal_hp ) * heal_amp_mult"
    ) in _compute_ehp_body()
