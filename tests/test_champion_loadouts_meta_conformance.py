"""Drift guard for champion_loadouts.json meta-conformance invariants.

Item-200 Slice A (2026-05-26) ship-time: lock the invariants that:

  SR + ARAM (non-bootsless champions):
    * each ``build_path`` carries EXACTLY ONE boots item
    * the boots item lives at ``items[1]`` (after the first core item,
      mirroring ``core.build_order._select_boots`` post-engine_call_i==1
      injection)

  Arena (all champions, all paths):
    * NO boots in ``items[*]`` (Cherry mode has no boot shop)

  Bootsless champions (``Yuumi`` + ``Cassiopeia``, pinned in
  ``core.build_order._BOOTSLESS_CHAMPS``):
    * NO boots in any mode

Test failure surfaces the exact (champion, mode_variant, path_key, items)
tuple so the operator can point ``tools/champion_loadout_validate_meta.py``
at the slice.

Sister to ``tests/test_champion_loadouts_no_unique_clash.py`` (item 167)
which locks the unique-passive no-double rule; both guards walk the same
``data/champion_loadouts.json`` source. This guard pins POSITION (boots
at items[1] post first-core), the other guard pins COMPOSITION.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOADOUTS = _ROOT / "data" / "champion_loadouts.json"


def _norm(s: str) -> str:
    """Strip to lowercase alphanumeric. Mirrors
    ``coaches.loadout_resolver._norm`` so name comparisons match the
    same fuzzy contract."""
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


# Display names that resolve to one of the 8 IDs in
# ``core.build_order._BOOTS_IDS``: {3006, 3009, 3010, 3020, 3047, 3111,
# 3117, 3158}. Maintained in lock-step with the migration tool
# ``tools/champion_loadout_validate_meta.py::_BOOTS_DISPLAY_NAMES``.
_BOOTS_DISPLAY_NAMES: frozenset[str] = frozenset({
    "Berserker's Greaves",
    "Boots of Swiftness",
    "Plated Steelcaps",
    "Mercury's Treads",
    "Sorcerer's Shoes",
    "Ionian Boots of Lucidity",
    "Mobility Boots",
    "Symbiotic Soles",
    "Synchronized Souls",
    "Slightly Magical Footwear",
})
_BOOTS_NORM: frozenset[str] = frozenset(_norm(n) for n in _BOOTS_DISPLAY_NAMES)

# Frozen in ``core.build_order._BOOTSLESS_CHAMPS``. Yuumi's bonded ally
# carries her; Cassiopeia's passive grants MS in lieu of boots.
_BOOTSLESS_CHAMPS: frozenset[str] = frozenset({"Yuumi", "Cassiopeia"})

_MODE_VARIANT_KEYS: tuple[str, ...] = (
    "sr-collapsed",
    "aram-collapsed",
    "arena-collapsed",
)


class ChampionLoadoutsMetaConformanceTests(unittest.TestCase):
    """Walk every champion x mode x build_path and enforce the boots
    invariants. Single test_*method per invariant; collects all failure
    sites so the operator sees the full diff in one pass."""

    @classmethod
    def setUpClass(cls) -> None:
        with _LOADOUTS.open("r", encoding="utf-8") as f:
            cls.loadouts = json.load(f)

    def _walk_paths(self, mode_variant: str):
        """Yield (champion, build_path) tuples for the given mode."""
        champs = (self.loadouts or {}).get("champions") or {}
        for cname, cdef in sorted(champs.items()):
            v = ((cdef or {}).get("variants") or {}).get(mode_variant)
            if not v:
                continue
            for p in v.get("build_paths") or []:
                yield cname, p

    def test_sr_non_bootsless_path_has_boots_at_index_1(self) -> None:
        """Every SR ``build_path`` on a non-bootsless champion must put
        boots at ``items[1]`` (the canonical injection slot)."""
        failures: list[str] = []
        for cname, p in self._walk_paths("sr-collapsed"):
            if cname in _BOOTSLESS_CHAMPS:
                continue
            items = list(p.get("items") or [])
            items_norm = [_norm(x) for x in items]
            boots_positions = [
                i for i, n in enumerate(items_norm) if n in _BOOTS_NORM
            ]
            key = p.get("key", "?")
            if not boots_positions:
                failures.append(
                    f"{cname} sr-collapsed/{key} NO_BOOTS items={items[:6]}"
                )
            elif boots_positions[0] != 1:
                failures.append(
                    f"{cname} sr-collapsed/{key} boots at index "
                    f"{boots_positions[0]} not 1 items={items[:6]}"
                )
            elif len(boots_positions) > 1:
                failures.append(
                    f"{cname} sr-collapsed/{key} MULTIPLE_BOOTS at "
                    f"{boots_positions} items={items[:6]}"
                )
        self.assertEqual(failures, [], "\n  ".join([""] + failures))

    def test_aram_non_bootsless_path_has_boots_at_index_1(self) -> None:
        """Every ARAM ``build_path`` on a non-bootsless champion must put
        boots at ``items[1]``."""
        failures: list[str] = []
        for cname, p in self._walk_paths("aram-collapsed"):
            if cname in _BOOTSLESS_CHAMPS:
                continue
            items = list(p.get("items") or [])
            items_norm = [_norm(x) for x in items]
            boots_positions = [
                i for i, n in enumerate(items_norm) if n in _BOOTS_NORM
            ]
            key = p.get("key", "?")
            if not boots_positions:
                failures.append(
                    f"{cname} aram-collapsed/{key} NO_BOOTS items={items[:6]}"
                )
            elif boots_positions[0] != 1:
                failures.append(
                    f"{cname} aram-collapsed/{key} boots at index "
                    f"{boots_positions[0]} not 1 items={items[:6]}"
                )
            elif len(boots_positions) > 1:
                failures.append(
                    f"{cname} aram-collapsed/{key} MULTIPLE_BOOTS at "
                    f"{boots_positions} items={items[:6]}"
                )
        self.assertEqual(failures, [], "\n  ".join([""] + failures))

    def test_arena_paths_have_no_boots(self) -> None:
        """Arena (Cherry mode mapId 30) has no boot shop. Every Arena
        ``build_path`` must have zero boots items."""
        failures: list[str] = []
        for mode in ("arena-collapsed",):
            for cname, p in self._walk_paths(mode):
                items = list(p.get("items") or [])
                items_norm = [_norm(x) for x in items]
                boots_hits = [items[i] for i, n in enumerate(items_norm)
                              if n in _BOOTS_NORM]
                if boots_hits:
                    key = p.get("key", "?")
                    failures.append(
                        f"{cname} {mode}/{key} HAS_BOOTS {boots_hits} "
                        f"(Arena Cherry has no boot shop)"
                    )
        self.assertEqual(failures, [], "\n  ".join([""] + failures))

    def test_bootsless_champions_have_no_boots_anywhere(self) -> None:
        """Yuumi + Cassiopeia (per ``core.build_order._BOOTSLESS_CHAMPS``)
        must carry no boots in any mode's build_paths."""
        failures: list[str] = []
        for mode in _MODE_VARIANT_KEYS:
            for cname, p in self._walk_paths(mode):
                if cname not in _BOOTSLESS_CHAMPS:
                    continue
                items = list(p.get("items") or [])
                items_norm = [_norm(x) for x in items]
                boots_hits = [items[i] for i, n in enumerate(items_norm)
                              if n in _BOOTS_NORM]
                if boots_hits:
                    key = p.get("key", "?")
                    failures.append(
                        f"{cname} {mode}/{key} BOOTSLESS_HAS_BOOTS "
                        f"{boots_hits} items={items[:6]}"
                    )
        self.assertEqual(failures, [], "\n  ".join([""] + failures))


class BootsConstantsLockStepTests(unittest.TestCase):
    """The boots display-name set in this guard must stay in lock-step
    with ``tools/champion_loadout_validate_meta.py``. If the migration
    tool's set changes, this guard's set MUST change too (or the
    drift-fix will silently leave a slice unprotected)."""

    def test_boots_names_match_migration_tool(self) -> None:
        """Sanity check: the migration tool's boots-name set is the
        same as this guard's set."""
        from tools.champion_loadout_validate_meta import _BOOTS_DISPLAY_NAMES as tool_set
        self.assertEqual(
            tool_set, _BOOTS_DISPLAY_NAMES,
            "Migration tool and drift guard boots-name sets diverged. "
            "Edit both in lock-step."
        )

    def test_bootsless_champs_match_engine(self) -> None:
        """Sanity check: the bootsless champion set matches the engine
        authority at ``core.build_order._BOOTSLESS_CHAMPS``."""
        from core.build_order import _BOOTSLESS_CHAMPS as engine_set
        self.assertEqual(
            engine_set, _BOOTSLESS_CHAMPS,
            "Engine and drift guard bootsless-champ sets diverged. "
            "core.build_order is authoritative; sync this guard."
        )


class AsciiHygieneTests(unittest.TestCase):
    """Hard-rule: this test file stays 7-bit ASCII per CLAUDE.md."""

    def test_this_file_is_ascii_clean(self) -> None:
        path = Path(__file__)
        with path.open("rb") as f:
            raw = f.read()
        non_ascii = [b for b in raw if b >= 0x80]
        self.assertEqual(
            len(non_ascii), 0,
            f"Found {len(non_ascii)} non-ASCII byte(s) in {path.name}; "
            "CLAUDE.md hard-rule violation."
        )


if __name__ == "__main__":
    unittest.main()
