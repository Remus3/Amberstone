"""Guard: every agents/daemon_slayer/*.py module is named in the docs module map.

The docs/DAEMON_SLAYER.md module map carried a row for the scorer core and the
route-backing modules but none for 82 of the 123 package modules (measured at
ENGINE 1.290.0 by globbing the package and searching the doc): the ~60
underscore-prefixed override / grant registries and a score of plain helper
modules. A reader holding a module name found no doc line for it.

The map now carries family rows. This guard derives the module set from disk
(no hand-kept list) and fails when:

  * a package module is not named, in backticks, on any module-map table row
    (a new module is a one-line doc change, never a silent gap);
  * a module named on a family row does not exist (a rename or delete leaves a
    stale name behind);
  * an ``_item_*`` module is not on the item-keyed row, or a ``_rune_*`` module
    is not on the rune-keyed row, or a ``_passive_*`` / ``_champion_*`` module
    is on neither champion survivability / offense row.

The map is the section between the ``## Module map`` heading and the next
``## `` heading. ASCII only.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.test_docs_daemon_slayer_drift import _SERVER

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "DAEMON_SLAYER.md"
_PKG = _SERVER.parent
_MODULE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*\.py)`")
_FAMILY_HEADS = (
    "| Registry family: ability data",
    "| Registry family: champion survivability",
    "| Registry family: champion offense",
    "| Registry family: item-keyed",
    "| Registry family: rune-keyed",
    "| Coupling and credit seams",
    "| Shared helpers and loaders",
    "| Presentation, scenario and entry",
)


def _map_rows() -> list[str]:
    text = _DOC.read_text(encoding="utf-8")
    start = text.index("## Module map")
    end = text.index("\n## ", start + 1)
    return [ln for ln in text[start:end].splitlines() if ln.startswith("|")]


def _modules_on_disk() -> list[str]:
    return sorted(p.name for p in _PKG.glob("*.py"))


def _family_row(head: str) -> str:
    hits = [r for r in _map_rows() if r.startswith(head)]
    assert len(hits) == 1, f"expected exactly one {head!r} row, got {len(hits)}"
    return hits[0]


def _named(row: str) -> set[str]:
    return set(_MODULE.findall(row))


def test_enumerations_are_not_empty():
    mods = _modules_on_disk()
    assert "server.py" in mods and "_passive_heal_overrides.py" in mods
    assert len(_map_rows()) > 20
    for head in _FAMILY_HEADS:
        assert _named(_family_row(head)), f"{head!r} row names no module"


def test_every_package_module_is_named_on_a_map_row():
    named: set[str] = set()
    for row in _map_rows():
        named |= _named(row)
    missing = [m for m in _modules_on_disk() if m not in named]
    assert not missing, (
        f"{len(missing)} agents/daemon_slayer module(s) have no module-map row "
        f"or family-row mention in docs/DAEMON_SLAYER.md: {missing}"
    )


def test_family_rows_name_only_existing_modules():
    on_disk = set(_modules_on_disk())
    stale = []
    for head in _FAMILY_HEADS:
        stale += [f"{head}: {m}" for m in sorted(_named(_family_row(head)) - on_disk)]
    assert not stale, f"family rows name modules that do not exist: {stale}"


def test_prefixed_registries_sit_on_their_family_row():
    item = _named(_family_row("| Registry family: item-keyed"))
    rune = _named(_family_row("| Registry family: rune-keyed"))
    champ = _named(_family_row("| Registry family: champion survivability")) | _named(
        _family_row("| Registry family: champion offense")
    )
    mods = _modules_on_disk()
    wrong = [m for m in mods if m.startswith("_item_") and m not in item]
    wrong += [m for m in mods if m.startswith("_rune_") and m not in rune]
    wrong += [
        m for m in mods
        if m.startswith(("_passive_", "_champion_")) and m not in champ
        and m not in _named(_family_row("| Registry family: ability data"))
    ]
    assert not wrong, f"prefixed registries off their family row: {wrong}"
