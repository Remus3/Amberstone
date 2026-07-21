"""Provenance guard for the champ-select PICK placeholder pad (2026-07-20).

Bug (measured live, SR draft, queue 400 TOP): the WHY THESE reason list read

    Quinn: 57% WR - 7 games - safe pick (performance)     <- real
    Jinx: last played in this queue - lost (last in queue) <- real
    Vayne: [no data] (mastery)                             <- fabricated
    Kai'Sa: [no data] (meta)                               <- fabricated

The last two are NOT a failed mastery lookup - champ_select.js never reads
lcu.mastery at all. They are the hardcoded _PB_PLACEHOLDERS.BOT champions
(champId 67 "Vayne" / 145 "Kai'Sa") that pad `roleMatchPicks` whenever the
backend returns fewer than 3 performance_picks. Reproduced live against
/api/champ-select/pickban-recs?role=TOP&queue=400&top=3&exclude=67 -> exactly
1 pick (Quinn 57% WR - 7 games) + last_in_queue Jinx, so slots #2/#3 padded.
The names merely COINCIDE with real mastery entries (67 / 145), which is what
made the bug read as an id-vs-name key mismatch.

Second half of the same block: the "(mastery)" / "(meta)" tags are positional
labels, not provenance. routes_pickban.py's docstring (lines 10-12) says the
mastery + meta sources were never built; all three role-match picks come from
ONE backend list (performance_picks, raw top-N by score). So a fat DB rendered
"(mastery)" / "(meta)" on picks that are pure performance rows.

Fix:
- padded slots carry champId 0 + champName "-" (cell keeps its geometry, is
  not clickable - a click on the old pad fired set_pick_intent for a hardcoded
  champion - and the WHY THESE loop skips it via its `if (!p.champId)` gate);
- each pick carries an explicit `provenance` string used for the reason tag.

Two layers, mirroring tests/test_champ_select_ban_provenance_dom.py.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAMP_SELECT_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
_NODE = shutil.which("node")

_OPENS = "([{"
_CLOSES = ")]}"


def _read_source() -> str:
    return CHAMP_SELECT_JS.read_text(encoding="utf-8")


def _match_all(src: str, j: int) -> int:
    depth = 0
    for k in range(j, len(src)):
        if src[k] in _OPENS:
            depth += 1
        elif src[k] in _CLOSES:
            depth -= 1
            if depth == 0:
                return k
    raise AssertionError("unbalanced bracket run")


def _map_statement(src: str, decl: str) -> str:
    """The whole `const <decl> = [0, 1, 2].map((i) => {...})` statement.
    Anchored on the `.map(` paren so the leading array literal does not close
    the balanced run early (same trick as the ban-provenance test)."""
    assert decl in src, f"declaration not found: {decl!r}"
    start = src.index(decl)
    paren = src.index(".map(", start) + len(".map(") - 1
    return src[start:_match_all(src, paren) + 1]


def _foreach_statement(src: str, anchor: str) -> str:
    assert anchor in src, f"anchor not found: {anchor!r}"
    start = src.index(anchor)
    paren = src.index("(", start)
    return src[start:_match_all(src, paren) + 1]


def _pick_fallback_block(src: str) -> str:
    return _map_statement(src, "const roleMatchPicks =")


class StaticSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read_source()

    def test_pick_pad_does_not_wire_placeholder_champion(self) -> None:
        block = _pick_fallback_block(self.src)
        self.assertIn("[no data]", block, "extracted the wrong block")
        for wired in ("fb.champId", "fb.champName"):
            self.assertNotIn(
                wired, block,
                "a padded pick slot must not fabricate a champion "
                f"(found {wired}); it renders champId 0 + \"-\"",
            )

    def test_reason_tag_uses_provenance_not_positional_source_key(self) -> None:
        block = _foreach_statement(self.src, "allPicks.forEach(")
        self.assertIn("provenance", block)
        self.assertNotIn(
            'p.sourceKey === "last" ? "last in queue" : p.sourceKey', block,
            "the reason tag must not print the positional sourceKey "
            "(mastery / meta are not real sources)",
        )

    def test_source_is_ascii(self) -> None:
        self.assertEqual(
            [b for b in CHAMP_SELECT_JS.read_bytes() if b > 0x7F], [])


@unittest.skipUnless(_NODE, "node not on PATH")
class PickProvenanceBehaviorTests(unittest.TestCase):
    """Extract the real placeholder table + pick-pad + reason-line loop and
    run them in node against the live-reproduced thin payload (1 pick) and a
    fat payload (3 picks)."""

    @classmethod
    def setUpClass(cls) -> None:
        src = _read_source()
        start = src.index("const _PB_PLACEHOLDERS =")
        pb = src[start:_match_all(src, src.index("{", start)) + 1]
        picks_block = _pick_fallback_block(src)
        expl_block = _foreach_statement(src, "allPicks.forEach(")
        harness = (
            pb + ";\n"
            + "function _mk(liveRoleMatch, ph) {\n"
            # Defined here so the pre-fix source (which reads fallbackPicks)
            # still runs under the harness and fails on the assertions, not
            # on a ReferenceError.
            + "  const fallbackPicks = [ph.performance, ph.mastery, ph.meta];\n"
            + "  void fallbackPicks;\n"
            + "  " + picks_block + ";\n"
            + "  const fourthPick = {champId: 222, champName: 'Jinx',"
            + " reason: 'last played in this queue - lost',"
            + " sourceKey: 'last', provenance: 'last in queue'};\n"
            + "  const allPicks = [...roleMatchPicks, fourthPick];\n"
            + "  const explanationLines = [];\n"
            + "  " + expl_block + ";\n"
            + "  return {picks: roleMatchPicks,"
            + " lines: explanationLines.map((l) => l.text)};\n"
            + "}\n"
            + "const thin = _mk([{champId: 133, champName: 'Quinn',"
            + " reason: '57% WR - 7 games - safe pick'}],"
            + " _PB_PLACEHOLDERS.BOT);\n"
            + "const fat = _mk(["
            + "{champId: 1, champName: 'A', reason: 'r1'},"
            + "{champId: 2, champName: 'B', reason: 'r2'},"
            + "{champId: 3, champName: 'C', reason: 'r3'}],"
            + " _PB_PLACEHOLDERS.BOT);\n"
            + "process.stdout.write(JSON.stringify({thin, fat}));\n"
        )
        cls._td = tempfile.mkdtemp()
        harness_path = Path(cls._td) / "pick_provenance_harness.mjs"
        harness_path.write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [_NODE, str(harness_path)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"node harness failed ({proc.returncode}): {proc.stderr}")
        cls.result = json.loads(proc.stdout)

    def test_thin_payload_pads_without_a_fabricated_champion(self) -> None:
        picks = self.result["thin"]["picks"]
        self.assertEqual(len(picks), 3, "the 4-cell geometry must survive")
        self.assertEqual(picks[0]["champName"], "Quinn")
        for pad in picks[1:]:
            self.assertEqual(pad["champId"], 0, "padded slot must not be clickable")
            self.assertEqual(pad["champName"], "-")
            self.assertEqual(pad["reason"], "[no data]")

    def test_thin_payload_reason_lines_carry_only_real_picks(self) -> None:
        lines = self.result["thin"]["lines"]
        joined = " | ".join(lines)
        self.assertNotIn("Vayne", joined)
        self.assertNotIn("Kai'Sa", joined)
        self.assertNotIn("[no data]", joined)
        self.assertEqual(
            lines,
            ["Quinn: 57% WR - 7 games - safe pick (performance)",
             "Jinx: last played in this queue - lost (last in queue)"],
        )

    def test_fat_payload_tags_every_role_match_pick_as_performance(self) -> None:
        # All three come from ONE backend list (performance_picks); the old
        # "(mastery)" / "(meta)" tags were positional labels, not provenance.
        lines = self.result["fat"]["lines"]
        self.assertEqual(len(lines), 4)
        for line in lines[:3]:
            self.assertTrue(
                line.endswith("(performance)"), f"mislabelled source: {line!r}")
        self.assertNotIn("(mastery)", " ".join(lines))
        self.assertNotIn("(meta)", " ".join(lines))
        self.assertTrue(lines[3].endswith("(last in queue)"))


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        self.assertEqual([b for b in Path(__file__).read_bytes() if b > 0x7F], [])

    def test_no_dash_glyph_drift_in_panel_source(self) -> None:
        banned = re.compile("[\\u2013\\u2014\\u2018\\u2019\\u201c\\u201d]")
        self.assertIsNone(banned.search(_read_source()))


if __name__ == "__main__":
    unittest.main()
