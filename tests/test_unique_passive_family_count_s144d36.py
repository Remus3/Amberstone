"""RM-1152 - every living text that restates the unique-passive family
count, or names the family set, agrees with the engine.

The family set is the distinct non-empty ``unique_passive_key`` values over
``agents.daemon_slayer.effects.ITEM_EFFECTS`` - the keys ``collect_effects``
dedupes on and each ranker's ``current_unique_keys`` set filters on. It was
measured at nine on ENGINE 1.290.0 (fiendhunter_barrage, hellfire_char,
hydra_cleave, immolate, innervating_fill, last_whisper, lifeline,
spellblade, void_pen), while three living texts said six or seven:

* ``core/build_order.py`` module docstring - "the 7 unique-passive
  families", listing seven (no last_whisper, no void_pen), and "each spans
  SR + Arena (CHERRY) mirrors", false for the three one-item families;
* ``tests/test_build_order_no_double_guard.py`` module docstring - "SIX
  families today";
* ``tools/headless-ds.md`` section 2 - "The engine has 6 unique-passive
  families".

The count is DERIVED here, never written: if a later engine change adds or
drops a family, these tests go red and name the text to update. That is the
point - the texts restate the number, so the number must be re-checked
against the engine. ``core/build_order.py``'s CODE stays family-agnostic
(tests/test_build_order_no_double_guard.py Test A); only its docstring
names the families, to explain the design.
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from agents.daemon_slayer.effects import ITEM_EFFECTS

_REPO = Path(__file__).resolve().parent.parent
_BUILD_ORDER = _REPO / "core" / "build_order.py"
_NO_DOUBLE_GUARD = _REPO / "tests" / "test_build_order_no_double_guard.py"
_LANE_DOC = _REPO / "tools" / "headless-ds.md"

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12,
}


def _families() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for iid, eff in ITEM_EFFECTS.items():
        key = getattr(eff, "unique_passive_key", "")
        if key:
            out.setdefault(key, []).append(iid)
    return out


def _as_int(tok: str) -> int:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _WORDS[tok]


def _module_docstring(path: Path) -> str:
    doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    assert doc, f"{path.name} has no module docstring"
    return " ".join(doc.split())


def _stated_counts(text: str, pattern: str) -> list[int]:
    return [_as_int(m) for m in re.findall(pattern, text, flags=re.I)]


_NUM = r"(\d+|" + "|".join(_WORDS) + r")"


class EngineFamilySetTests(unittest.TestCase):
    def test_family_set_is_non_empty(self) -> None:
        # Anchor: an empty set would make every count check below vacuous.
        self.assertGreaterEqual(len(_families()), 6)


class BuildOrderDocstringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = _module_docstring(_BUILD_ORDER)
        self.fams = _families()

    def test_stated_count_matches_engine(self) -> None:
        counts = _stated_counts(
            self.doc, _NUM + r" unique-passive families")
        self.assertEqual(len(counts), 1, counts)
        self.assertEqual(
            counts[0], len(self.fams),
            f"core/build_order.py docstring says {counts[0]} unique-passive "
            f"families; the engine defines {len(self.fams)}: "
            f"{sorted(self.fams)}")

    def test_every_engine_family_is_named(self) -> None:
        missing = [f for f in sorted(self.fams)
                   if not re.search(r"\b" + re.escape(f) + r"\b", self.doc)]
        self.assertEqual(missing, [],
                         "core/build_order.py docstring lists the families "
                         "but omits these engine families")

    def test_one_item_families_claim_is_true(self) -> None:
        m = re.search(r"([a-z_, ]+?) are one item each", self.doc)
        self.assertIsNotNone(m, "the one-item-family sentence is gone")
        named = [n.strip() for n in re.split(r",|\band\b", m.group(1))
                 if n.strip()]
        expected = sorted(f for f, ids in self.fams.items() if len(ids) == 1)
        self.assertEqual(sorted(named), expected)

    def test_no_claim_that_every_family_has_a_mirror(self) -> None:
        self.assertNotIn("each spans SR + Arena", self.doc)

    def test_multi_item_families_carry_an_arena_mirror(self) -> None:
        # The docstring says the multi-item families span SR + Arena
        # (CHERRY) mirrors; an Arena mirror id is the 22xxxx form.
        multi = {f: ids for f, ids in self.fams.items() if len(ids) > 1}
        counts = _stated_counts(
            self.doc, r"The first " + _NUM + r" span SR \+ Arena")
        self.assertEqual(counts, [len(multi)])
        bare = [f for f, ids in sorted(multi.items())
                if not any(len(i) == 6 and i.startswith("22") for i in ids)]
        self.assertEqual(bare, [], "multi-item families with no Arena mirror")


class NoDoubleGuardDocstringTests(unittest.TestCase):
    def test_stated_count_matches_engine(self) -> None:
        doc = _module_docstring(_NO_DOUBLE_GUARD)
        counts = _stated_counts(doc, r"defines " + _NUM + r" families")
        self.assertEqual(len(counts), 1, counts)
        self.assertEqual(counts[0], len(_families()))


class LaneDocTests(unittest.TestCase):
    def test_stated_count_matches_engine(self) -> None:
        text = " ".join(_LANE_DOC.read_text(encoding="utf-8").split())
        counts = _stated_counts(
            text, r"The engine has " + _NUM + r" unique-passive families")
        self.assertEqual(len(counts), 1, counts)
        self.assertEqual(counts[0], len(_families()))


if __name__ == "__main__":
    unittest.main()
