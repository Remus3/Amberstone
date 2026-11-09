"""S144-D-215..218 - the eleven ``*_registry_notes.json`` provenance sidecars
name only live champions and say exactly what their engine registries hold.

WHY. Each roster fan-out axis (items 294-309) shipped a builder in
``tools/ds_<axis>_build.py`` that writes TWO things from one clean entry list:
the ``add(...)`` block in ``agents/daemon_slayer/<axis>.py`` (the engine
registry, through the builder's ``_emit``) and the sidecar
``agents/daemon_slayer/<axis>_registry_notes.json`` (champion, source/spell,
kind, numbers, source_quote). The sidecar is never loaded by the engine, but it
IS read as the authority for the kit numbers: the R17 / R39 ramp seeds and
their tests cite its ``source_quote`` verbatim (``test_antitank_ramp_r17.py``,
``test_antitank_ramp_current_hp_r39.py``). Nothing pinned the pair together,
and the registries have since been hand-edited (R93, R196, ...), so a reader
of a sidecar cannot tell a live row from a removed one.

* S144-D-215: every sidecar is well formed - ``count`` equals the number of
  entries, every entry's champion is a live DDragon roster id, every
  source / spell is in its builder's ``SOURCES`` / ``SPELLS`` tuple, no entry
  repeats its builder's dedupe key, and every entry keeps a source_quote.
* S144-D-216: every sidecar entry, projected through its builder's own
  ``_emit`` (the exact text the builder wrote into the module), equals the
  live registry entry for that champion, and every live registry entry has a
  sidecar entry - both directions, all eleven axes. The projection matters:
  the sustain builder drops ``duration_s`` from REGEN rows and the HP terms
  from vamp rows, and the mobility builder drops ``duration_s`` / ``ms_pct``
  from non-MS_STEROID rows, so a raw field compare reads 6 by-design drops
  as drift.
* S144-D-217: the only departures are the three pinned anti-tank rows, each
  still true and still explained in ``antitank.py``: Amumu P SHRED is
  DELIBERATELY UNREGISTERED (R196 - the passive lowers no resist), and
  Annie R / Darius E PERCENT_PEN were hand-added after the item-308 fan-out.
  A pin that stops being true fails, so the list cannot rot.
* S144-D-218: the four FULL-roster axes (objective damage and threat range
  are named full-roster in the objdamage / allyamp builder docstrings;
  scaling and wave clear measured so, 171 of 171 fan-out champions each)
  cover every live roster champion except the pinned set {Locke, Zaahen},
  which post-date the 171-champion fan-outs.
  A new champion, or a newly covered one, fails here instead of silently
  scoring 0.0.

MEASURED 2026-11-09 (live snapshot, patch 16.22.1, ENGINE 1.291.0): 2826
sidecar entries over 11 axes, ZERO dangling champion ids, ZERO duplicate keys,
ZERO empty quotes, every ``count`` true; raw field compare 9 mismatched rows,
of which 6 are the builder projection above and 3 are the pinned anti-tank
rows. The sidecar and drift checkers are also run on planted defects below,
so an empty or blind checker cannot pass; the drift compare is a set compare,
so both row lists are also asserted duplicate-free.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import re
import unittest
from pathlib import Path
from typing import Any

from agents.daemon_slayer.data_loader import DataSnapshot

_REPO = Path(__file__).resolve().parents[3]
_DS_DIR = _REPO / "agents" / "daemon_slayer"
_TOOLS_DIR = _REPO / "tools"

# axis -> (registry attribute, sidecar slot field, builder dedupe-key fields).
# The dedupe keys are copied from each builder's ``key = (...)`` line and
# re-checked against the builder source in test_dedupe_keys_match_builders.
_AXES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "allyamp": ("_ALLYAMP_REGISTRY", "source", ("champion", "source")),
    "antitank": ("_ANTITANK_REGISTRY", "source", ("champion", "source", "kind")),
    "cc_output": ("_CC_OUTPUT_REGISTRY", "spell", ("champion", "spell")),
    "extendedduel": (
        "_EXTENDEDDUEL_REGISTRY", "source", ("champion", "source", "kind"),
    ),
    "mobility": ("_MOBILITY_REGISTRY", "spell", ("champion", "spell")),
    "objdamage": ("_OBJDAMAGE_REGISTRY", "source", ("champion", "source")),
    "scaling": ("_SCALING_REGISTRY", "source", ("champion", "source")),
    "sustain": ("_SUSTAIN_REGISTRY", "spell", ("champion", "spell")),
    "threatrange": ("_THREATRANGE_REGISTRY", "source", ("champion", "source")),
    "waveclear": ("_WAVECLEAR_REGISTRY", "source", ("champion", "source")),
    "zonecontrol": ("_ZONECONTROL_REGISTRY", "source", ("champion", "source")),
}

# add() keyword -> entry field, where the module's add() renames a field
# (``cond`` is ``conditional`` on every axis).
_KWARG_FIELD: dict[str, dict[str, str]] = {
    "scaling": {"stage": "online_stage"},
    "waveclear": {"band": "range_band"},
}

# S144-D-217: (axis, row) departures, row = (champion, *shared fields in the
# registry dataclass order). Each side is asserted still true.
_SIDECAR_ONLY: dict[str, frozenset[tuple]] = {
    "antitank": frozenset({("Amumu", "P", "SHRED", "SUSTAINED", 0.6, False)}),
}
_REGISTRY_ONLY: dict[str, frozenset[tuple]] = {
    "antitank": frozenset({
        ("Annie", "R", "PERCENT_PEN", "SUSTAINED", 0.7, False),
        ("Darius", "E", "PERCENT_PEN", "SUSTAINED", 0.7, False),
    }),
}

# S144-D-218: axes whose builder targets the whole roster, and the champions
# the 171-champion fan-outs predate.
_FULL_ROSTER_AXES = ("objdamage", "scaling", "threatrange", "waveclear")
_UNCOVERED_ON_FULL_ROSTER_AXES = frozenset({"Locke", "Zaahen"})


def _sidecar(axis: str) -> dict:
    path = _DS_DIR / f"{axis}_registry_notes.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _builder(axis: str) -> Any:
    return importlib.import_module(f"tools.ds_{axis}_build")


def _registry(axis: str) -> dict:
    module = importlib.import_module(f"agents.daemon_slayer.{axis}")
    return getattr(module, _AXES[axis][0])


def _entry_fields(registry: dict, sidecar_keys: set[str]) -> list[dataclasses.Field]:
    """The registry dataclass fields the sidecar records, in declaration
    order. Fields added to an entry after its fan-out (the anti-tank ramp /
    ratio / axis fields) have no sidecar column and are not compared."""
    first = next(iter(registry.values()))[0]
    return [f for f in dataclasses.fields(first) if f.name in sidecar_keys]


def _all_fields(registry: dict) -> list[dataclasses.Field]:
    return list(dataclasses.fields(next(iter(registry.values()))[0]))


def _norm(value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    return round(float(value), 4)


def _registry_rows(registry: dict, names: list[str]) -> list[tuple]:
    return [
        (champ, *(_norm(getattr(entry, n)) for n in names))
        for champ, entries in registry.items()
        for entry in entries
    ]


def _parse_add_call(line: str) -> tuple[str, list[Any], dict[str, Any]]:
    """(champion, positional args after it, keyword args) of one add() line."""
    call = ast.parse(line.strip(), mode="eval").body
    if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "add"):
        raise AssertionError(f"not an add() call: {line!r}")
    args = [ast.literal_eval(a) for a in call.args]
    kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
    return args[0], args[1:], kwargs


def _projected_row(axis: str, entry: dict, fields: list[dataclasses.Field]) -> tuple:
    """The registry row (over ``fields``) the builder's emitted add() line
    constructs.

    Positional arguments after the champion fill the entry fields in
    declaration order, ``cond`` is ``conditional``, a ``_KWARG_FIELD`` keyword
    is its renamed field, every other keyword names its field, and a field the line does not set takes its dataclass default.
    cc_output's builder has no ``_emit`` (it writes all four fields
    positionally inline), so its projection is the sidecar row itself.
    """
    if axis == "cc_output":
        return (entry["champion"], *(_norm(entry[f.name]) for f in fields))
    champ, args, kwargs = _parse_add_call(_builder(axis)._emit(entry))
    every = _all_fields(_registry(axis))
    values: dict[str, Any] = {}
    for field, value in zip(every, args):
        values[field.name] = value
    rename = {"cond": "conditional", **_KWARG_FIELD.get(axis, {})}
    for key, value in kwargs.items():
        values[rename.get(key, key)] = value
    unknown = set(values) - {f.name for f in every}
    if unknown:
        raise AssertionError(f"{axis}: emitted keyword(s) {sorted(unknown)} name no field")
    row = [champ]
    for field in fields:
        if field.name in values:
            row.append(_norm(values[field.name]))
        else:
            row.append(_norm(field.default))
    return tuple(row)


def _row_drift(
    sidecar_rows: list[tuple], registry_rows: list[tuple],
) -> tuple[set[tuple], set[tuple]]:
    """(sidecar-only rows, registry-only rows)."""
    return set(sidecar_rows) - set(registry_rows), set(registry_rows) - set(sidecar_rows)


def _sidecar_defects(
    notes: dict, roster: frozenset[str], slots: tuple[str, ...],
    slot_field: str, key_fields: tuple[str, ...],
) -> list[str]:
    entries = notes.get("entries")
    if not isinstance(entries, list):
        return ["entries is not a list"]
    defects: list[str] = []
    if notes.get("count") != len(entries):
        defects.append(f"count {notes.get('count')!r} != {len(entries)} entries")
    seen: set[tuple] = set()
    for i, e in enumerate(entries):
        champ = e.get("champion")
        if champ not in roster:
            defects.append(f"entry {i}: champion {champ!r} is not a roster id")
        if e.get(slot_field) not in slots:
            defects.append(f"entry {i}: {slot_field} {e.get(slot_field)!r} not in {slots}")
        key = tuple(e.get(k) for k in key_fields)
        if key in seen:
            defects.append(f"entry {i}: duplicate key {key}")
        seen.add(key)
        quote = e.get("source_quote")
        if not (isinstance(quote, str) and quote.strip()):
            defects.append(f"entry {i}: empty source_quote")
    return defects


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.roster = frozenset(DataSnapshot.load().champions)


class TestSidecarsWellFormed(_Base):
    """S144-D-215."""

    def test_every_sidecar_is_well_formed(self) -> None:
        for axis, (_attr, slot_field, key_fields) in _AXES.items():
            with self.subTest(axis=axis):
                builder = _builder(axis)
                slots = getattr(builder, "SOURCES", None) or builder.SPELLS
                notes = _sidecar(axis)
                self.assertIsInstance(notes.get("item"), int)
                self.assertRegex(str(notes.get("engine")), r"^\d+\.\d+\.\d+$")
                self.assertGreater(len(notes["entries"]), 0)
                self.assertEqual(
                    _sidecar_defects(notes, self.roster, slots, slot_field, key_fields),
                    [],
                )

    def test_dedupe_keys_match_builders(self) -> None:
        for axis, (_attr, slot_field, key_fields) in _AXES.items():
            with self.subTest(axis=axis):
                src = (_TOOLS_DIR / f"ds_{axis}_build.py").read_text(encoding="utf-8")
                found = re.findall(r"^\s+key = \(([^)]*)\)", src, flags=re.M)
                self.assertEqual(len(found), 1, f"{axis}: one key = (...) line")
                names = tuple(n.strip() for n in found[0].split(","))
                # builder locals: champ / source|spell / kind
                local = {"champion": "champ", "source": "source",
                         "spell": "spell", "kind": "kind"}
                self.assertEqual(names, tuple(local[k] for k in key_fields))

    def test_checker_catches_planted_defects(self) -> None:
        roster = frozenset({"Aatrox", "Ahri"})
        good = {"champion": "Aatrox", "source": "Q", "kind": "X", "source_quote": "q"}
        notes = {
            "count": 4,
            "entries": [
                good,
                dict(good),  # duplicate key
                {**good, "champion": "Kled & Skaarl", "source": "W"},  # not an id
                {**good, "champion": "Ahri", "source": "Z", "source_quote": " "},
            ],
        }
        defects = _sidecar_defects(
            notes, roster, ("P", "Q", "W", "E", "R"), "source", ("champion", "source"),
        )
        joined = "\n".join(defects)
        self.assertIn("duplicate key", joined)
        self.assertIn("'Kled & Skaarl' is not a roster id", joined)
        self.assertIn("'Z' not in", joined)
        self.assertIn("empty source_quote", joined)
        notes["count"] = 5
        self.assertIn("count 5 != 4 entries", "\n".join(
            _sidecar_defects(notes, roster, ("Q", "W", "Z"), "source", ("champion",)),
        ))


class TestSidecarsMatchRegistries(_Base):
    """S144-D-216 / S144-D-217."""

    def _drift(self, axis: str) -> tuple[set[tuple], set[tuple]]:
        registry = _registry(axis)
        entries = _sidecar(axis)["entries"]
        fields = _entry_fields(registry, set(entries[0]))
        names = [f.name for f in fields]
        projected = [_projected_row(axis, e, fields) for e in entries]
        live = _registry_rows(registry, names)
        self.assertEqual(len(set(projected)), len(projected), f"{axis}: duplicate sidecar row")
        self.assertEqual(len(set(live)), len(live), f"{axis}: duplicate registry row")
        return _row_drift(projected, live)

    def test_every_sidecar_entry_is_its_registry_entry(self) -> None:
        for axis in _AXES:
            with self.subTest(axis=axis):
                sidecar_only, registry_only = self._drift(axis)
                self.assertEqual(
                    sidecar_only,
                    set(_SIDECAR_ONLY.get(axis, frozenset())),
                    f"{axis}: sidecar rows the registry does not hold",
                )
                self.assertEqual(
                    registry_only,
                    set(_REGISTRY_ONLY.get(axis, frozenset())),
                    f"{axis}: registry rows the sidecar does not record",
                )

    def test_projection_is_the_builder_projection(self) -> None:
        # The by-design drops are real: a raw compare of the sidecar numbers
        # against the registry DOES differ for these rows, and the builder's
        # _emit is what reconciles them.
        cases = {
            "sustain": ("Briar", "E", "duration_s", 1.0),
            "mobility": ("Fizz", "E", "duration_s", 0.75),
        }
        for axis, (champ, slot, field, raw) in cases.items():
            with self.subTest(axis=axis):
                registry = _registry(axis)
                fields = _entry_fields(registry, set(_sidecar(axis)["entries"][0]))
                slot_field = _AXES[axis][1]
                entry = next(
                    e for e in _sidecar(axis)["entries"]
                    if e["champion"] == champ and e[slot_field] == slot
                )
                self.assertEqual(entry[field], raw)
                live = next(r for r in registry[champ] if getattr(r, slot_field) == slot)
                self.assertNotEqual(getattr(live, field), raw)
                idx = 1 + [f.name for f in fields].index(field)
                self.assertEqual(
                    _projected_row(axis, entry, fields)[idx], _norm(getattr(live, field)),
                )

    def test_pinned_departures_are_still_explained(self) -> None:
        src = (_DS_DIR / "antitank.py").read_text(encoding="utf-8")
        self.assertIn("Amumu - DELIBERATELY UNREGISTERED (R196)", src)
        self.assertNotIn("Amumu", _registry("antitank"))
        self.assertIn('add("Annie", "R", "PERCENT_PEN"', src)
        self.assertIn('add("Darius", "E", "PERCENT_PEN"', src)

    def test_drift_checker_sees_both_directions(self) -> None:
        a = [("X", "Q", 1.0), ("Y", "W", 2.0)]
        b = [("X", "Q", 1.0), ("Z", "E", 3.0)]
        self.assertEqual(_row_drift(a, b), ({("Y", "W", 2.0)}, {("Z", "E", 3.0)}))
        self.assertEqual(_row_drift(a, list(a)), (set(), set()))

    def test_projection_reads_defaults_and_cond(self) -> None:
        registry = _registry("sustain")
        fields = _entry_fields(registry, set(_sidecar("sustain")["entries"][0]))
        row = _projected_row("sustain", {
            "champion": "Briar", "spell": "W", "kind": "SPELLVAMP",
            "vamp_pct": 0.4, "pct_max_hp": 0.05, "flat_hp": 0.0,
            "duration_s": 0.0, "conditional": True, "source_quote": "q",
        }, fields)
        names = [f.name for f in fields]
        self.assertEqual(row[0], "Briar")
        self.assertEqual(row[1 + names.index("pct_max_hp")], 0.0)  # dropped
        self.assertIs(row[1 + names.index("conditional")], True)


class TestFullRosterAxesCoverRoster(_Base):
    """S144-D-218."""

    def test_full_roster_axes_cover_the_roster(self) -> None:
        self.assertLessEqual(_UNCOVERED_ON_FULL_ROSTER_AXES, self.roster)
        for axis in _FULL_ROSTER_AXES:
            with self.subTest(axis=axis):
                covered = frozenset(_registry(axis))
                self.assertEqual(self.roster - covered, _UNCOVERED_ON_FULL_ROSTER_AXES)
                noted = frozenset(e["champion"] for e in _sidecar(axis)["entries"])
                self.assertEqual(noted, covered)


if __name__ == "__main__":
    unittest.main()
