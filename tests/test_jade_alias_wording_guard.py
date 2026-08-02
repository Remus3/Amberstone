"""RM-141 S5 guard: the REFUTED "Jade_ rows are aliases" read stays dead.

DDragon 16.15.1 shipped 60 ``Jade_<Champion>`` rows at ``base_key + 60000``.
An earlier session recorded them as ALIAS rows (name == base champion). That
read is REFUTED and the refutation is a MEASUREMENT, not an opinion:

    Jade_Ahri  key "60103"  name "Ahri"  hp 460
    Ahri       key "103"    name "Ahri"  hp 590

Same display name, different key, DIFFERENT stat line. They are throwback-mode
VARIANT rows carrying an older patch's stats, partitioned out at mirror time
(``scripts/data_pipeline.py``) and again at load time
(``agents/daemon_slayer/data_loader.py``). A name-keyed dedupe would absorb one
into the other and silently serve an older Ahri.

Two halves, and both are load-bearing:

* ``test_no_tracked_file_calls_the_jade_rows_aliases`` kills the wording.
* ``test_jade_variant_row_is_not_an_alias_of_the_base_row`` pins the
  MEASUREMENT that refutes it, so the refutation cannot silently rot back if
  the prose is ever reworded again.

SCOPE DECISION (stated per the spec, section 4.3). Two archives are EXEMPT
from the wording scan:

* ``docs/history_notes.md`` - an append-only archive of immutable session
  records. Correcting it in place would be a history rewrite (memory
  ``feedback_no_history_rewrite``), and it is outside this slice's file set.
  Its neighbouring entry already carries the correction in-line ("that read
  ... was WRONG"), so a reader of the archive is not left misled.
* ``docs/LEDGER.md`` - same append-only contract, same reasoning. Item 1126
  carries the original alias wording and is a dated record of what was
  believed that day.

Also exempt: ``docs/specs/RM-141_JADE_MODE.md`` (the spec that DIAGNOSES the
refuted wording and must quote it verbatim) and this file.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent

# The claim is made in prose and in comments/docstrings, so the scan is limited
# to text-bearing extensions. Data mirrors (champion.json et al) legitimately
# CONTAIN the Jade_ keys and are not making a claim about them.
_TEXT_SUFFIXES = {".md", ".py", ".js", ".mjs", ".txt", ".ps1", ".yml", ".yaml"}

_EXEMPT = {
    "docs/history_notes.md",
    "docs/LEDGER.md",
    "docs/specs/RM-141_JADE_MODE.md",
    "tests/test_jade_alias_wording_guard.py",
}

_ALIAS = re.compile(r"\balias(es)?\b", re.I)
_JADE = re.compile(r"Jade_")

# A mention is CORRECTING the refuted read rather than repeating it when the
# text immediately around it carries one of these. Checked over a joined
# window so a "They are NOT / aliases" line wrap still reads as a refutation.
# "variant" is deliberately NOT a marker. It is the CORRECT replacement word
# for these rows, so it is the term most likely to co-occur with a re-introduced
# alias claim - accepting it as a refutation is exactly the hole a verifier
# measured on 2026-08-02 ("The Jade_ variant rows are simply aliases of the base
# champion" passed). A real refutation has to say so, not merely say "variant".
_REFUTATION = re.compile(
    r"(refut|wrong|\bnot\b\s+(an\s+)?alias|never\s+alias)", re.I)

# How far an alias word may sit from a Jade_ mention and still be about it.
_WINDOW = 3
# How much context counts when looking for a refutation marker. Both are 0 on
# purpose: the refutation must sit on the SAME line as the alias word, so each
# occurrence carries its own. Allowing neighbouring lines let one legitimate
# correction excuse every re-introduction in the same paragraph - measured
# 2026-08-02, an injected "the Jade_ variant rows are simply aliases" passed
# because a corrected sentence two lines above said "NOT aliases".
_MARKER_BEFORE = 1
_MARKER_AFTER = 0
# ...but the previous line only counts when the alias word sits at the START of
# its own line, i.e. the sentence genuinely wrapped ("They are NOT / aliases").
# An alias word in mid-line is a fresh claim and must carry its own refutation.
_WRAP_COL = 30
# The marker must sit within this many CHARACTERS of the alias word, not just
# somewhere on the same line. BACKLOG.md rows run to 1400+ characters and an
# unrelated "Refuting cite:" elsewhere on the row would otherwise excuse the
# claim at the far end of it.
_MARKER_CHARS = 120

# Files this slice edits. Every one must be 7-bit clean.
_SLICE_FILES = (
    "BACKLOG.md",
    "ROADMAP.md",
    "docs/LIVE_GAME_GATED_SYNC.md",
    "tools/daemon_slayer_build_orders_generate.py",
    "tests/test_build_order_producer_fail_loud.py",
    "tests/test_jade_alias_wording_guard.py",
)

_CHAMPIONS = _REPO / "data" / "meta_build" / "ddragon" / "16.15.1" / "champion.json"


def _tracked_text_files_mentioning_jade():
    """Tracked, in-scope files whose text mentions ``Jade_``."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_REPO, capture_output=True, text=True, check=True)
    for rel in out.stdout.split("\0"):
        if not rel or rel in _EXEMPT:
            continue
        if Path(rel).suffix.lower() not in _TEXT_SUFFIXES:
            continue
        path = _REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _JADE.search(text):
            yield rel, text.splitlines()


def _alias_claims(lines):
    """Yield ``(lineno, text)`` for alias wording that is about the Jade_ rows."""
    jade_lines = [i for i, ln in enumerate(lines) if _JADE.search(ln)]
    if not jade_lines:
        return
    for i, line in enumerate(lines):
        if not _ALIAS.search(line):
            continue
        if not any(abs(i - j) <= _WINDOW for j in jade_lines):
            continue
        prev = " ".join(lines[max(0, i - _MARKER_BEFORE):i])
        tail = " ".join(lines[i + 1:i + 1 + _MARKER_AFTER])
        for hit in _ALIAS.finditer(line):
            wrapped = bool(prev) and hit.start() <= _WRAP_COL
            head = prev if wrapped else ""
            window = (head + " " + line) if head else line
            if tail:
                window = window + " " + tail
            offset = len(head) + 1 if head else 0
            lo = max(0, offset + hit.start() - _MARKER_CHARS)
            hi = offset + hit.end() + _MARKER_CHARS
            if not _REFUTATION.search(window[lo:hi]):
                yield i + 1, line.strip()
                break


class JadeAliasWordingGuard(unittest.TestCase):

    def test_no_tracked_file_calls_the_jade_rows_aliases(self):
        offenders = []
        for rel, lines in _tracked_text_files_mentioning_jade():
            for lineno, text in _alias_claims(lines):
                offenders.append(f"{rel}:{lineno}: {text[:160]}")
        self.assertEqual(
            offenders, [],
            "the Jade_ rows are throwback-mode VARIANT rows at base_key + "
            "60000 carrying their own older-patch stat line, NOT aliases. "
            "Sites still repeating the refuted read:\n" + "\n".join(offenders))

    def test_jade_variant_row_is_not_an_alias_of_the_base_row(self):
        """The MEASUREMENT that refutes the alias read.

        Deliberately does NOT skip when the mirror is missing. The file is
        TRACKED, so its absence is a repo defect and must fail loudly - a skip
        here would be an always-passing guard, which is the whole point of
        tests/test_skip_condition_hygiene.py.
        """
        self.assertTrue(
            _CHAMPIONS.is_file(),
            f"tracked DDragon mirror is missing: {_CHAMPIONS}")
        data = json.loads(_CHAMPIONS.read_text(encoding="utf-8")).get("data", {})
        jade = data.get("Jade_Ahri")
        base = data.get("Ahri")
        self.assertIsInstance(jade, dict, "16.15.1 mirror carries no Jade_Ahri row")
        self.assertIsInstance(base, dict, "16.15.1 mirror carries no Ahri row")

        self.assertEqual(str(jade.get("key")), "60103")
        self.assertEqual(str(base.get("key")), "103")
        # Same display name is exactly why a name-keyed dedupe is unsafe.
        self.assertEqual(jade.get("name"), base.get("name"))
        # ... and this is why absorbing one into the other would serve an
        # older patch's Ahri: the stat lines are NOT the same row.
        jade_hp = jade.get("stats", {}).get("hp")
        base_hp = base.get("stats", {}).get("hp")
        self.assertIsNotNone(jade_hp)
        self.assertIsNotNone(base_hp)
        self.assertNotEqual(
            jade_hp, base_hp,
            "Jade_Ahri and Ahri report the same hp - if this ever passes, "
            "re-measure before calling these rows variants")

    def test_live_gated_rows_l1_through_l6_are_filed(self):
        doc = (_REPO / "docs" / "LIVE_GAME_GATED_SYNC.md").read_text(
            encoding="utf-8")
        for n in range(1, 7):
            # assertTrue, not assertIn: assertIn would dump the whole 2400-line
            # doc into the failure message.
            self.assertTrue(
                f"**G8-{n:02d}**" in doc,
                f"RM-141 live-gated row G8-{n:02d} is not filed in "
                "docs/LIVE_GAME_GATED_SYNC.md")

    def test_slice_files_are_seven_bit_ascii(self):
        for rel in _SLICE_FILES:
            path = _REPO / rel
            self.assertTrue(path.is_file(), f"missing slice file: {rel}")
            raw = path.read_bytes()
            bad = sorted({b for b in raw if b > 0x7F})
            self.assertEqual(
                bad, [], f"{rel} carries non-ASCII bytes: {bad[:8]}")


if __name__ == "__main__":
    unittest.main()
