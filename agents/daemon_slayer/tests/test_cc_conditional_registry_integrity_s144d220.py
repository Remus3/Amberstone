"""S144-D-220..223 - the conditional-CC registry JSON is well-formed, every row
reaches its consumer, its coexistence flags say what the unconditional
registry holds, and CC_CONDITIONAL_NOTES.md records every row it ships.

WHY. ``cc_conditional_registry.json`` is the hand-authored source of the
conditional-CC axis (read by ``cc_pressure`` / ``compute_ehp`` / the hybrid
scorer / ``cc_pairing`` / the pick-ban route). Its two loaders in
``cc_conditional.py`` build plain dicts, so several authoring mistakes are
SILENT: no error, no warning, the per-champion wave tests stay green.

* S144-D-220. ``_build_per_spell_cc_conditional`` assigns
  ``registry.setdefault(champ, {})[spell] = entry`` and the forms builder
  assigns ``[(spell, form_index)]``: a duplicate slot row silently keeps only
  the LAST one. A champion id off the roster is never looked up. A primary row
  carrying an integer ``form_index`` (or a forms row carrying ``None``) breaks
  the "the two never collide by construction" claim the
  ``REGISTRY_TOTAL_ENTRIES`` comment rests on, and a ``None`` form index in
  the forms registry makes ``get_conditional_entries`` sort ``None`` against
  an int. Guards: roster ids, unique slot keys, the form-index split, and
  every JSON row reachable through ``get_conditional_entries``.
* S144-D-221. A forms row names a Meraki ``form_index``; one past the end of
  the spell's form list encodes a form the champion does not have. And a forms
  row on a slot that ALSO carries a primary (default-form) row must name a
  form OTHER than the one the engine serves there, or the same form is
  credited twice (``cc_pressure`` sums every ``coexists=False`` entry).
* S144-D-222. ``coexists_with_unconditional=True`` tells ``cc_pressure`` to
  credit MAX(unconditional, conditional) for the slot; with no unconditional
  ``_PER_SPELL_CC_DURATIONS`` entry the flag compares against 0 and means
  nothing. ``False`` on a slot that DOES hold an unconditional entry sums
  both. MEASURED 2026-11-09 (patch 16.22.1, ENGINE 1.291.0): every ``True``
  row has its unconditional slot, and exactly three ``False`` rows sit on an
  unconditional slot, each pre-dating the wave-18 flag (ENGINE 1.55.0) and
  each saying in its own notes that it coexists with the unconditional entry.
  They are pinned EXACTLY below; Renekton W and Neeko E are filed as a Tier-2
  double-credit question (S144-D-224), Singed E is a genuine sequential pair.
* S144-D-223. ``CC_CONDITIONAL_NOTES.md`` says it is "the canonical record of
  every entry's construction" and "New entries are hand-added to the JSON ...
  record their rationale here". MEASURED the same day: 72 of 73 rows carried
  a construction in the doc, field-for-field equal to the JSON; Ashe R (added
  at R14, ENGINE 1.150.0, ``74c6f1b63``) had none, and the R14
  ``durations_floor_s`` seeds were recorded nowhere in the doc. Fixed in the
  doc; guarded here both ways (no JSON row without a doc construction, no doc
  construction without a JSON row, every recorded field equal).

Every checker is a pure function over plain data, and each has a planted-defect
test so an empty enumeration cannot pass it.
"""

from __future__ import annotations

import ast
import json
import re
import textwrap
from pathlib import Path
from typing import Any, Optional

import pytest

from agents.daemon_slayer import _registries as registries
from agents.daemon_slayer import cc_conditional
from agents.daemon_slayer._per_spell_cc import _PER_SPELL_CC_DURATIONS
from agents.daemon_slayer.abilities import AbilitiesSnapshot
from agents.daemon_slayer.data_loader import DataSnapshot

_PKG = Path(cc_conditional.__file__).resolve().parent
REGISTRY_PATH = _PKG / "cc_conditional_registry.json"
NOTES_PATH = _PKG / "CC_CONDITIONAL_NOTES.md"

Row = dict[str, Any]
SlotKey = tuple[str, str, Optional[int]]

# S144-D-222: coexists=False rows on a slot that also holds an unconditional
# _PER_SPELL_CC_DURATIONS entry (so cc_pressure SUMS the two). Pinned exactly.
COEXIST_FALSE_ON_UNCONDITIONAL_SLOT: dict[tuple[str, str], str] = {
    ("Neeko", "E"): (
        "empowered root on later spiral hits; per target it REPLACES the base "
        "root, so the sum may double-credit (filed S144-D-224, Tier-2)"
    ),
    ("Renekton", "W"): (
        "100-Fury stun 1.5s EXTENDS the 0.75s base stun; the sum credits the "
        "base portion twice (filed S144-D-224, Tier-2)"
    ),
    ("Singed", "E"): (
        "Fling displacement then the W-overlap root: two sequential CCs, so the sum is the intended credit"
    ),
}

# S144-D-223: doc constructions whose durations_s is a computed expression,
# not a literal (the value is then checked against the JSON by evaluating
# the doc's own arithmetic below).
NON_LITERAL_DOC_DURATIONS: frozenset[SlotKey] = frozenset({("Karma", "W", 1)})

_COMPARED_FIELDS = (
    "cc_kind",
    "durations_s",
    "condition",
    "probability",
    "coexists_with_unconditional",
    "notes",
)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _slot_key(row: Row) -> SlotKey:
    return (row["champion"], row["spell"], row.get("form_index"))


def _all_rows(reg: dict[str, Any]) -> list[Row]:
    return list(reg["primary"]) + list(reg["forms"])


@pytest.fixture(scope="module")
def reg() -> dict[str, Any]:
    return _registry()


@pytest.fixture(scope="module")
def roster() -> frozenset[str]:
    return frozenset(DataSnapshot.load().champions)


@pytest.fixture(scope="module")
def ab() -> AbilitiesSnapshot:
    return AbilitiesSnapshot.load()


# ---------------------------------------------------------------------------
# Pure checkers
# ---------------------------------------------------------------------------


def duplicate_slots(rows: list[Row], *, forms: bool) -> list[SlotKey]:
    """Slot keys the loader would silently collapse (last row wins)."""
    seen: set[tuple] = set()
    dups: list[SlotKey] = []
    for row in rows:
        key = (row["champion"], row["spell"], row["form_index"]) if forms else (row["champion"], row["spell"])
        if key in seen:
            dups.append(_slot_key(row))
        seen.add(key)
    return dups


def off_roster(rows: list[Row], roster: frozenset[str]) -> list[SlotKey]:
    return [_slot_key(r) for r in rows if r["champion"] not in roster]


def bad_form_index_split(reg: dict[str, Any]) -> list[tuple[str, SlotKey]]:
    out: list[tuple[str, SlotKey]] = []
    for row in reg["primary"]:
        if row.get("form_index") is not None:
            out.append(("primary", _slot_key(row)))
    for row in reg["forms"]:
        fi = row.get("form_index")
        if isinstance(fi, bool) or not isinstance(fi, int) or fi < 0:
            out.append(("forms", _slot_key(row)))
    return out


def dangling_forms(rows: list[Row], ab: AbilitiesSnapshot) -> list[SlotKey]:
    """Forms rows whose (champion, spell, form_index) is not a real form."""
    out: list[SlotKey] = []
    for row in rows:
        champ, spell, fi = row["champion"], row["spell"], row["form_index"]
        if not ab.has_champion(champ):
            out.append(_slot_key(row))
            continue
        forms = ab.get_abilities(champ).get(spell) or ()
        if not 0 <= fi < len(forms) or forms[fi].form_index != fi:
            out.append(_slot_key(row))
    return out


def served_form_doubles(reg: dict[str, Any]) -> list[SlotKey]:
    """Forms rows naming the SERVED form of a slot that has a primary row."""
    primary = {(r["champion"], r["spell"]) for r in reg["primary"]}
    out: list[SlotKey] = []
    for row in reg["forms"]:
        champ, spell = row["champion"], row["spell"]
        if (champ, spell) not in primary:
            continue
        served = registries.get_form_index_for(champ)[0].get(spell, 0)
        if row["form_index"] == served:
            out.append(_slot_key(row))
    return out


def coexist_true_without_unconditional(rows: list[Row], uncond: dict[str, dict[str, Any]]) -> list[SlotKey]:
    return [
        _slot_key(r)
        for r in rows
        if r["coexists_with_unconditional"] and not uncond.get(r["champion"], {}).get(r["spell"])
    ]


def coexist_false_on_unconditional(rows: list[Row], uncond: dict[str, dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        (r["champion"], r["spell"])
        for r in rows
        if not r["coexists_with_unconditional"] and uncond.get(r["champion"], {}).get(r["spell"])
    }


# ---- S144-D-223 doc parsing ------------------------------------------------


def _python_blocks(doc: str) -> list[str]:
    return re.findall(r"```python\n(.*?)```", doc, re.S)


def _cond_constants() -> dict[str, str]:
    return {
        name: getattr(cc_conditional, name)
        for name in dir(cc_conditional)
        if name.startswith("COND_") and isinstance(getattr(cc_conditional, name), str)
    }


def _eval_expr(node: ast.AST, names: dict[str, Any]) -> Any:
    """Evaluate a doc kwarg: literals, COND_* names, _p/_p_form seeds, and
    the one computed durations tuple (via the block's own assignments)."""
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise KeyError(node.id)
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("_p", "_p_form"):
        return ast.literal_eval(node.args[-1])
    return ast.literal_eval(node)


def _block_assignments(tree: ast.AST) -> dict[str, Any]:
    """Evaluate simple ``name = <expr>`` assignments in a doc block, in order,
    so a computed durations tuple (Karma W form 1) can be compared too."""
    builtins = {"round": round, "tuple": tuple}
    env: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            src = ast.unparse(node.value)
            try:
                # Globals, not locals: a generator expression resolves its
                # free names (mid_mantra_bonus) in the globals mapping.
                env[node.targets[0].id] = eval(  # noqa: S307
                    src, {"__builtins__": builtins, **env}
                )
            except Exception:  # noqa: BLE001, S112 - non-arithmetic lines are irrelevant
                continue
    return env


def doc_constructions(doc: str) -> tuple[dict[SlotKey, list[dict[str, Any]]], dict]:
    """Return ({slot_key: [kwargs, ...]}, floor_table) parsed from the doc."""
    consts = _cond_constants()
    calls: dict[SlotKey, list[dict[str, Any]]] = {}
    floors: dict = {}
    for block in _python_blocks(doc):
        # A post-A3 record block is a builder-body excerpt (indented).
        tree = ast.parse(textwrap.dedent(block))
        names = {**consts, **_block_assignments(tree)}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and getattr(node.targets[0], "id", "") == "DURATIONS_FLOOR_S"
            ):
                floors.update(ast.literal_eval(node.value))
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "ConditionalCcEntry"):
                continue
            kw: dict[str, Any] = {}
            for k in node.keywords:
                kw[k.arg] = _eval_expr(k.value, names)
                if k.arg == "durations_s" and isinstance(k.value, ast.Name):
                    kw["_durations_is_name"] = True
            key = (kw["champion"], kw["spell"], kw.get("form_index"))
            calls.setdefault(key, []).append(kw)
    return calls, floors


def doc_vs_json_diffs(rows: list[Row], calls: dict[SlotKey, list[dict[str, Any]]], floors: dict) -> list[tuple]:
    out: list[tuple] = []
    by_key = {_slot_key(r): r for r in rows}
    for key in sorted(set(by_key) - set(calls), key=str):
        out.append(("json-row-without-doc-construction", key))
    for key in sorted(set(calls) - set(by_key), key=str):
        out.append(("doc-construction-without-json-row", key))
    for key, kws in calls.items():
        if len(kws) > 1:
            out.append(("doc-construction-duplicated", key))
    for key in sorted(set(by_key) & set(calls), key=str):
        row, kw = by_key[key], calls[key][-1]
        for field in _COMPARED_FIELDS:
            want = row[field]
            got = kw.get(field, False if field == "coexists_with_unconditional" else None)
            if field == "durations_s":
                want, got = tuple(want), tuple(got) if got is not None else None
            if want != got:
                out.append(("field", key, field))
        if kw.get("_durations_is_name") and key not in NON_LITERAL_DOC_DURATIONS:
            out.append(("unpinned-non-literal-durations", key))
        if "durations_floor_s" in kw and kw["durations_floor_s"] != row.get("durations_floor_s"):
            out.append(("field", key, "durations_floor_s"))
    json_floors = {
        (r["champion"], r["spell"]): r["durations_floor_s"] for r in rows if r.get("durations_floor_s") is not None
    }
    if json_floors != floors:
        out.append(("floor-table", tuple(sorted(set(json_floors.items()) ^ set(floors.items())))))
    return out


# ---------------------------------------------------------------------------
# S144-D-220 - well-formed, unique, on the roster, every row reachable.
# ---------------------------------------------------------------------------


def test_registry_has_both_sections_and_is_not_empty(reg: dict[str, Any]) -> None:
    assert reg["primary"], "primary section is empty"
    assert reg["forms"], "forms section is empty"


def test_every_row_names_a_live_roster_champion(reg: dict[str, Any], roster: frozenset[str]) -> None:
    assert len(roster) > 100
    assert off_roster(_all_rows(reg), roster) == []


def test_no_slot_key_is_silently_collapsed(reg: dict[str, Any]) -> None:
    assert duplicate_slots(reg["primary"], forms=False) == []
    assert duplicate_slots(reg["forms"], forms=True) == []


def test_primary_rows_carry_no_form_index_and_forms_rows_an_int(
    reg: dict[str, Any],
) -> None:
    assert bad_form_index_split(reg) == []


def test_every_json_row_is_served_by_get_conditional_entries(
    reg: dict[str, Any],
) -> None:
    rows = _all_rows(reg)
    want: dict[str, list[SlotKey]] = {}
    for row in rows:
        want.setdefault(row["champion"], []).append(_slot_key(row))
    for champ, keys in sorted(want.items()):
        got = [(e.champion, e.spell, e.form_index) for e in cc_conditional.get_conditional_entries(champ)]
        assert sorted(got, key=str) == sorted(keys, key=str), champ
    assert len(rows) == cc_conditional.REGISTRY_TOTAL_ENTRIES
    assert len(want) == cc_conditional.REGISTRY_TOTAL_CHAMPIONS


def test_planted_duplicate_off_roster_and_split_defects_are_caught() -> None:
    row = {
        "champion": "Brand",
        "spell": "R",
        "form_index": None,
        "coexists_with_unconditional": False,
    }
    assert duplicate_slots([row, dict(row)], forms=False) == [("Brand", "R", None)]
    frow = dict(row, form_index=1)
    assert duplicate_slots([frow, dict(frow)], forms=True) == [("Brand", "R", 1)]
    assert off_roster([dict(row, champion="NotAChampion")], frozenset({"Brand"})) == [("NotAChampion", "R", None)]
    assert bad_form_index_split({"primary": [frow], "forms": [row]}) == [
        ("primary", ("Brand", "R", 1)),
        ("forms", ("Brand", "R", None)),
    ]
    assert bad_form_index_split({"primary": [], "forms": [dict(row, form_index=True)]}) == [
        ("forms", ("Brand", "R", True))
    ]


# ---------------------------------------------------------------------------
# S144-D-221 - forms rows name a real form, never the primary's served form.
# ---------------------------------------------------------------------------


def test_every_forms_row_resolves_to_a_live_meraki_form(reg: dict[str, Any], ab: AbilitiesSnapshot) -> None:
    assert dangling_forms(reg["forms"], ab) == []


def missing_spells(rows: list[Row], ab: AbilitiesSnapshot) -> list[SlotKey]:
    return [
        _slot_key(r)
        for r in rows
        if not ab.has_champion(r["champion"]) or not ab.get_abilities(r["champion"]).get(r["spell"])
    ]


def test_every_primary_row_names_a_spell_the_champion_has(reg: dict[str, Any], ab: AbilitiesSnapshot) -> None:
    assert missing_spells(reg["primary"], ab) == []


def test_planted_missing_spell_is_caught(reg: dict[str, Any], ab: AbilitiesSnapshot) -> None:
    brand = next(r for r in reg["primary"] if r["champion"] == "Brand")
    assert missing_spells([dict(brand, spell="X")], ab) == [("Brand", "X", None)]
    assert missing_spells([dict(brand, champion="NotAChampion")], ab) == [("NotAChampion", brand["spell"], None)]


def test_no_forms_row_double_credits_the_primary_served_form(
    reg: dict[str, Any],
) -> None:
    assert served_form_doubles(reg) == []


def test_planted_dangling_form_and_served_double_are_caught(reg: dict[str, Any], ab: AbilitiesSnapshot) -> None:
    karma = next(r for r in reg["forms"] if r["champion"] == "Karma")
    assert dangling_forms([dict(karma, form_index=9)], ab) == [("Karma", "W", 9)]
    assert dangling_forms([dict(karma, champion="NotAChampion")], ab) == [("NotAChampion", "W", 1)]
    served = registries.get_form_index_for("Karma")[0].get("W", 0)
    planted = {"primary": reg["primary"], "forms": [dict(karma, form_index=served)]}
    assert served_form_doubles(planted) == [("Karma", "W", served)]


# ---------------------------------------------------------------------------
# S144-D-222 - coexistence flags agree with the unconditional registry.
# ---------------------------------------------------------------------------


def test_every_coexists_true_row_has_an_unconditional_slot(
    reg: dict[str, Any],
) -> None:
    rows = _all_rows(reg)
    assert any(r["coexists_with_unconditional"] for r in rows)
    assert coexist_true_without_unconditional(rows, _PER_SPELL_CC_DURATIONS) == []


def test_coexists_false_on_an_unconditional_slot_is_exactly_the_pinned_set(
    reg: dict[str, Any],
) -> None:
    got = coexist_false_on_unconditional(_all_rows(reg), _PER_SPELL_CC_DURATIONS)
    assert got == set(COEXIST_FALSE_ON_UNCONDITIONAL_SLOT)


@pytest.mark.parametrize("slot", sorted(COEXIST_FALSE_ON_UNCONDITIONAL_SLOT))
def test_each_pinned_row_still_declares_its_coexistence(reg: dict[str, Any], slot: tuple[str, str]) -> None:
    row = next(r for r in reg["primary"] if (r["champion"], r["spell"]) == slot)
    assert row["coexists_with_unconditional"] is False
    assert _PER_SPELL_CC_DURATIONS[slot[0]][slot[1]]
    assert "unconditional" in row["notes"].lower()


def test_planted_coexist_mismatches_are_caught() -> None:
    uncond = {"Brand": {"R": (1.0,)}}
    lone = {
        "champion": "Ahri",
        "spell": "E",
        "form_index": None,
        "coexists_with_unconditional": True,
    }
    assert coexist_true_without_unconditional([lone], uncond) == [("Ahri", "E", None)]
    summed = dict(lone, champion="Brand", spell="R", coexists_with_unconditional=False)
    assert coexist_false_on_unconditional([summed], uncond) == {("Brand", "R")}
    assert coexist_false_on_unconditional([dict(summed, coexists_with_unconditional=True)], uncond) == set()


# ---------------------------------------------------------------------------
# S144-D-223 - CC_CONDITIONAL_NOTES.md records every row, field for field.
# ---------------------------------------------------------------------------


def test_notes_doc_records_every_row_exactly(reg: dict[str, Any]) -> None:
    calls, floors = doc_constructions(NOTES_PATH.read_text(encoding="utf-8"))
    assert len(calls) == len(_all_rows(reg))
    assert doc_vs_json_diffs(_all_rows(reg), calls, floors) == []


def test_notes_doc_non_literal_durations_pin_is_live() -> None:
    calls, _ = doc_constructions(NOTES_PATH.read_text(encoding="utf-8"))
    named = {k for k, kws in calls.items() if kws[-1].get("_durations_is_name")}
    assert named == set(NON_LITERAL_DOC_DURATIONS)


def test_planted_doc_drift_is_caught(reg: dict[str, Any]) -> None:
    rows = _all_rows(reg)
    calls, floors = doc_constructions(NOTES_PATH.read_text(encoding="utf-8"))
    target = ("Brand", "R", None)
    assert target in calls

    missing = {k: v for k, v in calls.items() if k != target}
    assert ("json-row-without-doc-construction", target) in doc_vs_json_diffs(rows, missing, floors)

    extra = dict(calls)
    ghost = ("NotAChampion", "R", None)
    extra[ghost] = [dict(calls[target][-1], champion="NotAChampion")]
    assert ("doc-construction-without-json-row", ghost) in (doc_vs_json_diffs(rows, extra, floors))

    for field, bad in (
        ("cc_kind", "fear"),
        ("durations_s", (9.0,)),
        ("condition", "terrain"),
        ("probability", 0.01),
        ("coexists_with_unconditional", True),
        ("notes", "edited"),
    ):
        drifted = dict(calls)
        drifted[target] = [dict(calls[target][-1], **{field: bad})]
        assert ("field", target, field) in doc_vs_json_diffs(rows, drifted, floors)

    short_floors = dict(floors)
    short_floors.pop(next(iter(short_floors)))
    assert any(d[0] == "floor-table" for d in doc_vs_json_diffs(rows, calls, short_floors))

    doubled = dict(calls)
    doubled[target] = [calls[target][-1], calls[target][-1]]
    assert ("doc-construction-duplicated", target) in doc_vs_json_diffs(rows, doubled, floors)

    named = dict(calls)
    named[target] = [dict(calls[target][-1], _durations_is_name=True)]
    assert ("unpinned-non-literal-durations", target) in doc_vs_json_diffs(rows, named, floors)

    ashe = ("Ashe", "R", None)
    bad_floor = dict(calls)
    bad_floor[ashe] = [dict(calls[ashe][-1], durations_floor_s=0.1)]
    assert ("field", ashe, "durations_floor_s") in doc_vs_json_diffs(rows, bad_floor, floors)
