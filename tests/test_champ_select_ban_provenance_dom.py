"""Provenance guard for champ-select counter-ban placeholder rows
(audit 2026-07-09, Lane 2.2).

Bug: when the backend supplies fewer than 3 counter-bans, champ_select.js
padded the row with BOT placeholder bans (Draven 78 / Lucian 64 / Pyke 71)
whose fabricated pct carried through _csvBanReasonLabel as "beats you N%" -
invented percentages with a zero sample, violating the metric-provenance
rule. The pick path already forces "[no data]"; the ban path did not.

Fix: the placeholder counter-ban fallback forces pct:0, so
_csvBanReasonLabel returns "" and the cell renders name-only.

Two layers:
- StaticSourceGuards: the placeholder fallback block must not wire
  fbBan.pct into the row (grep-style, matches the repo's panel-DOM test
  convention). Red before the fix (source read fbBan.pct), green after.
- BanLabelBehaviorTests: extract the real _PB_PLACEHOLDERS +
  _csvBanReasonLabel + counterBans fragments from the source and run them in
  node - a <3-liveBans render must produce NO "beats you N%" on placeholder
  rows, while a real liveBan still renders its label (proves the fix only
  killed the fabricated path). Skipped when node is unavailable.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAMP_SELECT_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
_NODE = shutil.which("node")


def _read_source() -> str:
    return CHAMP_SELECT_JS.read_text(encoding="utf-8")


def _balanced_span(src: str, anchor: str, opens: str, closes: str) -> str:
    """Return the source span starting at `anchor` through the balanced
    close of the first opening bracket at/after it. `opens`/`closes` are the
    bracket kinds to track (e.g. "{"/"}" for a function body, "([{"/")]}" for
    a mixed expression). Relies on every bracket in these fragments being
    balanced - verified true for the extracted spans."""
    i = src.index(anchor)
    j = i
    while src[j] not in opens:
        j += 1
    depth = 0
    for k in range(j, len(src)):
        c = src[k]
        if c in opens:
            depth += 1
        elif c in closes:
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError(f"unbalanced span for anchor: {anchor!r}")


_OPENS = "([{"
_CLOSES = ")]}"


def _match_all(src: str, j: int) -> int:
    """Index of the bracket that balances the opening bracket at src[j],
    tracking all bracket kinds uniformly (every bracket in these fragments
    is balanced)."""
    depth = 0
    for k in range(j, len(src)):
        if src[k] in _OPENS:
            depth += 1
        elif src[k] in _CLOSES:
            depth -= 1
            if depth == 0:
                return k
    raise AssertionError("unbalanced bracket run")


def _counter_ban_fallback_block(src: str) -> str:
    # The whole `const counterBans = [0, 1, 2].map((i) => {...})` statement.
    # Anchor on the `.map(` paren so the leading `[0, 1, 2]` array does not
    # close the balanced run early.
    start = src.index("const counterBans =")
    paren = src.index(".map(", start) + len(".map(") - 1
    end = _match_all(src, paren)
    return src[start:end + 1]


class StaticSourceGuards(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.src = _read_source()

    def test_placeholder_fallback_does_not_wire_fbban_pct(self) -> None:
        block = _counter_ban_fallback_block(self.src)
        self.assertIn("fbBan", block, "extracted the wrong block")
        self.assertNotIn(
            "fbBan.pct", block,
            "placeholder counter-ban must force pct:0, not carry fbBan.pct",
        )

    def test_ban_label_guards_nonpositive_pct(self) -> None:
        label_fn = _balanced_span(
            self.src, "function _csvBanReasonLabel", "{", "}")
        # The guard that makes pct:0 render name-only.
        self.assertIn("pct <= 0", label_fn)
        self.assertIn('return "";', label_fn)


@unittest.skipUnless(_NODE, "node not on PATH")
class BanLabelBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        src = _read_source()
        pb = _balanced_span(src, "const _PB_PLACEHOLDERS =", "{", "}")
        label_fn = _balanced_span(
            src, "function _csvBanReasonLabel", "{", "}")
        counter = _counter_ban_fallback_block(src)
        harness = (
            pb + ";\n"
            + label_fn + "\n"
            + "function _mkRows(liveBans, ph) {\n"
            + counter + ";\n"
            + "  return counterBans.map(_csvBanReasonLabel);\n"
            + "}\n"
            + "const placeholder = _mkRows([], _PB_PLACEHOLDERS.BOT);\n"
            + "const real = _mkRows("
            + "[{champId: 200, name: 'X', pct: 60, encounters: 10, losses: 6}],"
            + " _PB_PLACEHOLDERS.BOT);\n"
            + "process.stdout.write(JSON.stringify({placeholder, real}));\n"
        )
        cls._td = tempfile.mkdtemp()
        cls._harness = Path(cls._td) / "ban_label_harness.mjs"
        cls._harness.write_text(harness, encoding="utf-8")
        proc = subprocess.run(
            [_NODE, str(cls._harness)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"node harness failed ({proc.returncode}): {proc.stderr}")
        cls.result = json.loads(proc.stdout)

    def test_placeholder_bans_have_no_beats_you_label(self) -> None:
        rows = self.result["placeholder"]
        self.assertEqual(len(rows), 3)
        for lbl in rows:
            self.assertEqual(
                lbl, "",
                f"placeholder ban rendered a label: {lbl!r}",
            )
        self.assertNotIn("beats you", "".join(rows))

    def test_real_liveban_still_renders_label(self) -> None:
        # The fix only kills the fabricated placeholder path; a real backend
        # ban row with a sample still shows its provenance label.
        rows = self.result["real"]
        self.assertEqual(rows[0], "beats you 60% (6/10)")
        # Rows 1 and 2 fall back to placeholders (name-only).
        self.assertEqual(rows[1], "")
        self.assertEqual(rows[2], "")


class AsciiHygieneTests(unittest.TestCase):
    def test_this_test_file_is_ascii(self) -> None:
        raw = Path(__file__).read_bytes()
        self.assertEqual([b for b in raw if b > 0x7F], [])


if __name__ == "__main__":
    unittest.main()
