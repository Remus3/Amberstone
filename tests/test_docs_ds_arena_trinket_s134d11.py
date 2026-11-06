"""Guard (RM-919): the DS doc's Arcane Sweeper and Meraki-cooldown claims are re-derived.

``docs/DAEMON_SLAYER.md`` "Arena-specific: Arcane Sweeper" said "The beam search
filters ``defensive_only`` items; Arcane Sweeper is handled separately". No
engine module reads ``defensive_only`` - it is a documentation flag on
``ItemEffect`` (``effects.py`` docstring) - so the sentence named a filter that
does not exist and hid the two gates that DO keep the trinket out: the
candidate pool's ``_is_purchasable`` (DDragon ``gold.purchasable`` false,
``gold.total`` 0) and ``strip_arena_trinkets`` over ``ARENA_TRINKET_IDS`` for
the caller's current items.

The section and the "Key insight" line are pinned WORD FOR WORD to a template
whose variable parts (ids, caller modules, value types) are measured here from
the engine source (AST, so comments and import aliases cannot fool it), the
live engine functions and the snapshot named by ``current.txt``. A patch
refresh, a refactor or a doc edit that moves a claim fails here instead of
rotting. ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from pathlib import Path

import pytest

from agents.daemon_slayer import rank, survivability_credit
from agents.daemon_slayer._effects_types import ItemEffect, PeriodicProc
from agents.daemon_slayer.data_loader import DataSnapshot

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"
_DATA_ROOT = _REPO_ROOT / "data" / "daemon_slayer"
_DS_PKG = _REPO_ROOT / "agents" / "daemon_slayer"
_SWEEPER = "3348"
# 1-based position of inject_ids, read from the live signature so it cannot stale.
_INJECT_POS = list(inspect.signature(rank._filter_candidates).parameters).index("inject_ids") + 1
_ARCHETYPE_RANKERS = ("_rank_mage.py", "burst.py", "ehp.py", "hps.py", "hybrid.py", "onhit_dps.py")


def _patch() -> str:
    return (_DATA_ROOT / "current.txt").read_text(encoding="utf-8").strip()


def _load(name: str) -> dict:
    return json.loads((_DATA_ROOT / _patch() / name).read_text(encoding="utf-8"))


def _section_lines(heading: str) -> list[str]:
    lines = _DOC.read_text(encoding="utf-8").splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == heading]
    assert len(starts) == 1, f"expected exactly one {heading!r} heading, got {len(starts)}"
    body: list[str] = []
    for ln in lines[starts[0] + 1:]:
        if ln.startswith("## "):
            break
        body.append(ln)
    return body


# --- AST helpers ------------------------------------------------------------

def _modules() -> dict[str, ast.Module]:
    mods = {}
    for path in sorted(_DS_PKG.rglob("*.py")):
        if "tests" in path.relative_to(_DS_PKG).parts:
            continue
        mods[path.relative_to(_DS_PKG).as_posix()] = ast.parse(path.read_text(encoding="utf-8"))
    assert "rank.py" in mods and "beam.py" in mods  # anchor: an empty walk must not pass
    return mods


def _local_names(tree: ast.Module, target: str) -> set[str]:
    """Every name ``target`` is reachable by in ``tree`` (itself plus import aliases)."""
    names = {target}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == target:
                    names.add(a.asname or a.name)
    return names


def _calls(tree: ast.Module, target: str) -> list[ast.Call]:
    names = _local_names(tree, target)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (isinstance(f, ast.Name) and f.id in names) or (
                isinstance(f, ast.Attribute) and f.attr == target):
            out.append(node)
    return out


def _strip_callers() -> set[str]:
    return {name for name, tree in _modules().items() if _calls(tree, "strip_arena_trinkets")}


def _passes_inject(call: ast.Call) -> bool:
    if any(k.arg in ("inject_ids", None) for k in call.keywords):  # None = **kwargs
        return True
    return len(call.args) >= _INJECT_POS or any(isinstance(a, ast.Starred) for a in call.args)


def _inject_callers() -> set[str]:
    return {name for name, tree in _modules().items()
            if any(_passes_inject(c) for c in _calls(tree, "_filter_candidates"))}


def _defensive_only_readers() -> set[str]:
    readers = set()
    for name, tree in _modules().items():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "defensive_only") or (
                    isinstance(node, ast.Constant) and node.value == "defensive_only"):
                readers.add(name)
    return readers


# --- expected doc text, built from measured facts ---------------------------

def _expected_sweeper_section() -> list[str]:
    callers = _strip_callers()
    archetypes = sorted(callers - {"rank.py", "beam.py"})
    arch = ", ".join(f"`{c}`" for c in archetypes)
    (inject_caller,) = sorted(_inject_callers())
    return [
        "",
        f"Every Arena player receives Arcane Sweeper ({_SWEEPER}) in the trinket slot, and the"
        f" live inventory poll returns it beside the {_SLOT_WORDS[rank.DEFAULT_SLOT_COUNT]} build"
        " slots. Two gates keep it out of DS:",
        "- the candidate pool: `rank._filter_candidates` keeps only items passing `_is_purchasable`,"
        " and the DDragon row has `gold.purchasable` false and `gold.total` 0. Its `inject_ids`"
        f" force-admit skips that gate; the only caller passing it is `{inject_caller}` (the tank"
        f" survivability table), which holds no {_SWEEPER};",
        "- the caller's current items: `rank.strip_arena_trinkets` removes `ARENA_TRINKET_IDS`"
        f" ({', '.join(sorted(rank.ARENA_TRINKET_IDS))}) when the mode is ARENA (case-insensitive),"
        " so the slot count and the baseline are not padded with a zero-stat row. It is called by"
        f" the carry ranker (`rank.py`), each archetype ranker ({arch}) and `beam.py`.",
        "",
        "`defensive_only` is a documentation flag on `ItemEffect`; no scorer and not the beam"
        " search reads it.",
    ]


_SLOT_WORDS = {6: "six"}


def _meraki_cooldown_kinds() -> list[str]:
    items = _load("items_meraki.json")["items"]
    assert "3041" in items  # anchor: ids live under "items", not the top level
    kinds = {type(p["cooldown"]).__name__
             for rec in items.values() for p in (rec.get("passives") or [])
             if "cooldown" in p}
    assert kinds, "no Meraki passive carries a cooldown key - the Key insight is dead"
    words = {"int": "int", "str": "string", "NoneType": "null"}
    return [words[k] for k in ("int", "str", "NoneType") if k in kinds] + sorted(
        k for k in kinds if k not in words)


def _expected_key_insight() -> str:
    kinds = _meraki_cooldown_kinds()
    shape = kinds[0] if len(kinds) == 1 else ", ".join(kinds[:-1]) + " or " + kinds[-1]
    return (
        "**Key insight**: check Meraki `passives[].cooldown` (under `items_meraki.json`"
        f' `items.<id>`; {shape}) before deferring any "ability-triggered" item. If an item'
        " CD exists, use `PeriodicProc.every_n_seconds` = CD - no ability-frequency data needed."
    )


# --- doc pins ---------------------------------------------------------------

def test_sweeper_section_matches_the_measured_template():
    assert _section_lines("## Arena-specific: Arcane Sweeper") == _expected_sweeper_section()


def test_key_insight_matches_the_measured_template():
    hits = [ln for ln in _section_lines("## Permanently deferred items (3)")
            if ln.startswith("**Key insight**")]
    assert hits == [_expected_key_insight()]


# --- the facts the template does not compute -------------------------------

def test_ast_probes_are_not_blind():
    # Positive controls: each probe must catch the shapes it claims to.
    alias = ast.parse("from .rank import strip_arena_trinkets as _s\nx = _s(a, b)\n")
    assert _calls(alias, "strip_arena_trinkets")
    commented = ast.parse("# strip_arena_trinkets(a, b)\nx = 1\n")
    assert not _calls(commented, "strip_arena_trinkets")
    for src in ("_filter_candidates(s, m, c, b, i, o, e, x)",
                "_filter_candidates(s, m, **kw)",
                "_filter_candidates(*a)",
                "_filter_candidates(s, m, c, b, i, o, inject_ids=x)"):
        (call,) = _calls(ast.parse(src), "_filter_candidates")
        assert _passes_inject(call), src
    (plain,) = _calls(ast.parse("_filter_candidates(s, m, c, b, i, o)"), "_filter_candidates")
    assert not _passes_inject(plain)


def test_defensive_only_is_a_documentation_flag():
    assert "defensive_only" in {f.name for f in dataclasses.fields(ItemEffect)}
    assert "defensive_only" not in {f.name for f in dataclasses.fields(PeriodicProc)}
    assert _defensive_only_readers() == set()


def test_sweeper_record_fails_the_purchasable_gate_and_has_no_stats():
    rec = _load("items.json")["data"][_SWEEPER]
    assert rec["name"] == "Arcane Sweeper"
    assert "Trinket" in rec["tags"]
    assert rec["gold"]["purchasable"] is False
    assert rec["gold"]["total"] == 0
    assert {m for m, on in rec["maps"].items() if on} == {"30"}
    assert not rec.get("stats")  # the "zero-stat row" claim
    assert rank._is_purchasable(rec) is False


@pytest.fixture(scope="module")
def snap() -> DataSnapshot:
    return DataSnapshot.load()


@pytest.mark.parametrize("mode", ["ARENA", "arena"])
def test_purchasable_gate_is_what_keeps_the_sweeper_out_of_the_pool(snap, mode):
    pool = {i for i, _ in rank._filter_candidates(snap, mode, set(), None, True, None)}
    assert "223031" in pool  # positive control: an ordinary Arena mirror is pooled
    assert _SWEEPER not in pool
    # Counterfactual: force-admitted past _is_purchasable it IS mode-legal and
    # pooled, so the purchasable gate (not a mode or terminal filter) is the one
    # keeping it out - and inject_ids really does skip that gate.
    forced = {i for i, _ in rank._filter_candidates(
        snap, mode, set(), None, True, None, inject_ids={_SWEEPER})}
    assert _SWEEPER in forced


def test_inject_ids_has_one_caller_whose_table_holds_no_sweeper():
    assert _inject_callers() == {"ehp.py"}
    injected = set().union(*survivability_credit._load_tank().values())
    assert injected, "tank survivability table is empty - the probe is blind"
    assert _SWEEPER not in injected


def test_strip_arena_trinkets_behaviour():
    assert frozenset({_SWEEPER}) == rank.ARENA_TRINKET_IDS
    for mode in ("ARENA", "arena", "Arena"):
        assert rank.strip_arena_trinkets(("3031", _SWEEPER), mode) == (("3031",), (_SWEEPER,))
    for mode in ("SR", "ARAM", "BRAWL"):
        assert rank.strip_arena_trinkets(("3031", _SWEEPER), mode) == (("3031", _SWEEPER), ())


def test_strip_callers_split_into_carry_archetypes_and_beam():
    callers = _strip_callers()
    assert callers == {"rank.py", "beam.py", *_ARCHETYPE_RANKERS}, sorted(callers)


def test_every_n_seconds_is_a_periodic_proc_field():
    assert "every_n_seconds" in {f.name for f in dataclasses.fields(PeriodicProc)}
