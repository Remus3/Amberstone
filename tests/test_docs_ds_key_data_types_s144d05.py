"""Guard (RM-957): the DS doc's data-type and CC-registry claims stay true.

``docs/DAEMON_SLAYER.md`` carried three stale claims, measured 2026-10-27:

* "Key data types" listed 12 ``CallContext`` fields and called them "the CORE
  originals", with newer fields "appended at the dataclass END". The live
  dataclass has 18 fields, and four of the six missing ones
  (``target_armor``, ``target_mr``, ``crit_chance``, ``target_bonus_hp``) sit
  in the MIDDLE of the declaration, so the list was neither complete nor a
  prefix;
* the module map said ``dps.py`` holds the ``CallContext`` dataclass, but it
  has lived in ``_effects_types.py`` since the s246 split and ``dps.py`` only
  imports it;
* the cc_conditional bullet said "72-entry registry"; R14 (ENGINE 1.150.0)
  added an Ashe R entry, so the registry holds 73 (65 primary + 8 form
  sidecar, 58 champions).

Every count is checked against the live module, not against a literal here.
ASCII only (CLAUDE.md hard rule).
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from agents.daemon_slayer import _effects_types, _per_spell_cc, cc_conditional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOC = _REPO_ROOT / "docs" / "DAEMON_SLAYER.md"

_TYPES = "## Key data types"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _section(heading: str) -> str:
    text = _text()
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end < 0 else text[start:end]


def _bullet(name: str) -> str:
    for line in _section(_TYPES).splitlines():
        if line.startswith(f"- **`{name}`**"):
            return line
    raise AssertionError(f"Key data types lost its {name} bullet")


def _names(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def _module_row(module: str) -> str:
    for line in _text().splitlines():
        if line.startswith(f"| `{module}` |"):
            return line
    raise AssertionError(f"module map lost its {module} row")


def test_callcontext_bullet_lists_every_field_in_declaration_order():
    line = _bullet("CallContext")
    m = re.search(r" - `([^`]+)`", line)
    assert m, "CallContext bullet lost its backticked field list"
    listed = [part.strip() for part in m.group(1).split(",")]
    assert listed == _names(_effects_types.CallContext)


def test_item_effect_and_periodic_proc_bullets_name_real_fields():
    for cls in (_effects_types.ItemEffect, _effects_types.PeriodicProc):
        fields = _names(cls)
        cited = re.findall(r"`([a-z_]+\*?)`", _bullet(cls.__name__))
        assert cited, f"{cls.__name__} bullet cites no field"
        for name in cited:
            if name.endswith("*"):
                assert any(f.startswith(name[:-1]) for f in fields), name
            else:
                assert name in fields, f"{cls.__name__} has no field {name}"


def test_key_data_types_says_the_three_dataclasses_are_frozen():
    for cls in (
        _effects_types.CallContext,
        _effects_types.ItemEffect,
        _effects_types.PeriodicProc,
    ):
        assert cls.__dataclass_params__.frozen, cls.__name__
    assert "frozen" in _bullet("ItemEffect")


def test_key_data_types_field_counts_match_the_dataclasses():
    body = _section(_TYPES)
    n_ctx = len(_names(_effects_types.CallContext))
    n_item = len(_names(_effects_types.ItemEffect))
    assert f"all {n_ctx} fields in declaration order" in body
    assert f"`ItemEffect` has {n_item} fields" in body


def test_key_data_types_drops_the_core_originals_prefix_claim():
    body = _section(_TYPES)
    assert "CORE originals" not in body
    assert "appended at the dataclass END" not in body


def test_module_map_puts_callcontext_in_effects_types_not_dps():
    import agents.daemon_slayer.dps as dps

    assert dps.CallContext is _effects_types.CallContext
    assert _effects_types.CallContext.__module__.endswith("_effects_types")
    assert "`CallContext` dataclass" not in _module_row("dps.py")
    assert "`CallContext`" in _module_row("_effects_types.py")


def test_cc_conditional_entry_counts_match_the_live_registry():
    primary = sum(len(v) for v in cc_conditional._PER_SPELL_CC_CONDITIONAL.values())
    forms = sum(
        len(v) for v in cc_conditional._PER_SPELL_CC_CONDITIONAL_FORMS.values()
    )
    assert primary + forms == cc_conditional.REGISTRY_TOTAL_ENTRIES
    text = _text()
    m = re.search(
        r"\*\*(\d+)-entry registry\*\* \((\d+) primary \+ (\d+) form-explicit"
        r" sidecar, (\d+) champions\)",
        text,
    )
    assert m, "cc_conditional bullet lost its 'N-entry registry (...)' figure"
    assert int(m.group(1)) == cc_conditional.REGISTRY_TOTAL_ENTRIES
    assert int(m.group(2)) == primary
    assert int(m.group(3)) == forms
    assert int(m.group(4)) == cc_conditional.REGISTRY_TOTAL_CHAMPIONS


def test_cc_conditional_tag_count_matches_the_live_module():
    tags = [n for n in dir(cc_conditional) if n.startswith("COND_")]
    m = re.search(r"ConditionalCcEntry dataclass \+ (\d+) condition tags", _text())
    assert m, "cc_conditional bullet lost its condition-tag count"
    assert int(m.group(1)) == len(tags)


def test_per_spell_cc_duration_counts_match_the_live_registry():
    reg = _per_spell_cc._PER_SPELL_CC_DURATIONS
    m = re.search(
        r"`_PER_SPELL_CC_DURATIONS` registry (\d+) entries / (\d+) champs", _text()
    )
    assert m, "the _PER_SPELL_CC_DURATIONS figure moved or was reworded"
    assert int(m.group(1)) == sum(len(v) for v in reg.values())
    assert int(m.group(2)) == len(reg)


def test_doc_is_ascii():
    _DOC.read_bytes().decode("ascii")
