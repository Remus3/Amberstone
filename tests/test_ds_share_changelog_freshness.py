"""Guard: the PUBLIC release history in ``Share/`` records the live engine.

R162 s5 (root-cause guard for a rot that has now accrued twice).

``tools/ds_share_sync.py --check`` is the CI gate that keeps the Share package
honest. It auto-restamps the MECHANICAL version/patch anchors in
``Share/README.md`` + ``Share/docs/*.md`` (``_doc_anchor_rules``,
tools/ds_share_sync.py:509) and it DELIBERATELY excludes changelog history from
that rewrite - correctly, because old versions in a release history are
legitimate and a rule that grabbed one would corrupt it (see the "STILL
EXCLUDED by design" list, tools/ds_share_sync.py:536).

The consequence is a hole with nothing behind it: no check anywhere fails when
a shipped ``ENGINE_VERSION`` never gets a release entry at all. Measured on
main at 70e5a466 - ``agents/daemon_slayer/__init__.py`` was at ``1.238.0`` while
the newest ``Share/CHANGELOG.md`` heading was ``## 1.235.0 -> 1.236.0``, so two
shipped releases (1.237.0, 1.238.0) were missing from the public record and
``--check`` read GREEN. The same rot was repaired by hand once already
(``docs/ORCHESTRATION_PLAN.md`` row R139, commit a4261c54) and came straight
back, which is why it needs a guard instead of a third manual fix.

Scope, and what is NOT duplicated here:
  * ``tests/test_ds_share_doc_anchors.py`` pins the FRESHNESS of the mechanical
    anchors the tool does rewrite, and asserts the changelog is excluded.
  * ``tests/test_ds_share_anchor_rule_coverage.py`` pins that the rule SET
    covers every mechanical anchor form the docs carry.
  * Neither looks at the release history itself. This file does, and only that.

The heading grammar asserted below is transcribed from the committed file, not
guessed: ``Share/CHANGELOG.md`` documents it in "How to read this file" (:52)
as ``## <previous ENGINE_VERSION> -> <new ENGINE_VERSION> (release date)``, and
:79 carries the live instance. ``test_changelog_grammar_still_parses`` re-derives
that shape from disk so a doc reflow that silently disarms the regex fails HERE
rather than turning this guard into a no-op - the exact failure mode that let
the anchor rules read green while blind.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import agents.daemon_slayer as ds

_REPO = Path(__file__).resolve().parent.parent
_SHARE = _REPO / "Share"
_CHANGELOG = _SHARE / "CHANGELOG.md"
_README = _SHARE / "README.md"

# `## <old> -> <new> (YYYY-MM-DD)` - a full release entry (Share/CHANGELOG.md:79).
_ENTRY_HEADING = re.compile(
    r"^## (?P<old>\d+\.\d+\.\d+) -> (?P<new>\d+\.\d+\.\d+) \((?P<date>\d{4}-\d{2}-\d{2})\)[ \t]*$",
    re.MULTILINE,
)
# `- <old> -> <new> - <prose>` under README "## Release history" (Share/README.md:290).
# Share/README.md's "Release history" moved from a bullet list to a two-column
# table on 2026-08-16 (the section had grown to 25 full CHANGELOG entries and was
# duplicating CHANGELOG.md at ~21 KB). Both shapes are accepted so this guard
# keeps its teeth across the restructure and would survive a revert:
#   bullet: "- 1.277.1 -> 1.278.0 - <prose>"
#   table:  "| 1.277.1 -> 1.278.0 (2026-08-15) | <prose> |"
_README_ENTRY = re.compile(
    r"^(?:- |\| )(?P<old>\d+\.\d+\.\d+) -> (?P<new>\d+\.\d+\.\d+)"
    r"(?: \(\d{4}-\d{2}-\d{2}\))? *(?:-|\|) ",
    re.MULTILINE,
)

_HOW_TO_FIX = (
    "Add the entry at the top of the 'Recent releases' section of "
    "Share/CHANGELOG.md, newest first, using the documented heading form "
    "'## <previous ENGINE_VERSION> -> <new ENGINE_VERSION> (YYYY-MM-DD)'. "
    "tools/ds_share_sync.py deliberately does NOT rewrite changelog history, "
    "so --check cannot catch this and will keep reading green."
)


def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(part) for part in v.split("."))


def _entries(text: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    """(old, new) release pairs, in file order (the files are newest-first)."""
    return [(m.group("old"), m.group("new")) for m in pattern.finditer(text)]


class ChangelogGrammarTests(unittest.TestCase):
    """The parse this guard depends on must keep matching the real file."""

    def test_changelog_exists(self):
        self.assertTrue(
            _CHANGELOG.is_file(),
            f"{_CHANGELOG} is missing - the Share package ships its own authored changelog",
        )

    def test_changelog_grammar_still_parses(self):
        entries = _entries(_CHANGELOG.read_text(encoding="utf-8"), _ENTRY_HEADING)
        self.assertGreater(
            len(entries), 4,
            "no '## <old> -> <new> (YYYY-MM-DD)' release headings parsed out of "
            "Share/CHANGELOG.md. Either the release history was emptied or the "
            "heading grammar changed. Do not delete this guard - update "
            "_ENTRY_HEADING to the new shape, or the freshness check below "
            "silently passes on every future release.",
        )


class ReleaseHistoryFreshnessTests(unittest.TestCase):
    """The public record names the version the engine actually ships."""

    def test_newest_changelog_entry_targets_live_engine_version(self):
        live = ds.ENGINE_VERSION
        entries = _entries(_CHANGELOG.read_text(encoding="utf-8"), _ENTRY_HEADING)
        self.assertTrue(entries, "no release headings parsed - see ChangelogGrammarTests")
        newest_old, newest_new = entries[0]
        self.assertEqual(
            newest_new, live,
            f"Share/CHANGELOG.md has no release entry for the live ENGINE_VERSION "
            f"{live!r}. Its newest entry is '## {newest_old} -> {newest_new}', so every "
            f"release after {newest_new} is missing from the public history. "
            f"Add the missing entry (newest heading should end at {live}, e.g. "
            f"'## {newest_new} -> {live} (YYYY-MM-DD)', or one entry per intervening "
            f"release). {_HOW_TO_FIX}",
        )

    def test_full_release_entries_are_contiguous(self):
        """Each full entry's `old` chains to the next-newer entry's `new`.

        Scoped to the full ``## `` entries only. The condensed
        "Earlier releases" bullets legitimately skip versions - the file says so
        outright at :70 ("Not every intermediate ENGINE_VERSION has an entry")
        and 13 such gaps exist below 1.217.0 - so they are NOT asserted here.
        Within the full-entry window the chain is unbroken, and this catches the
        adjacent failure mode the head check above cannot see: a release added
        on top that jumps the queue and leaves a hole behind it (heading
        '1.237.0 -> 1.238.0' landing directly over '1.235.0 -> 1.236.0' still
        satisfies the head check while 1.236.0 -> 1.237.0 goes unrecorded).
        """
        entries = _entries(_CHANGELOG.read_text(encoding="utf-8"), _ENTRY_HEADING)
        self.assertTrue(entries, "no release headings parsed - see ChangelogGrammarTests")
        for newer, older in zip(entries, entries[1:]):
            self.assertEqual(
                newer[0], older[1],
                f"Share/CHANGELOG.md release history has a hole: entry "
                f"'## {newer[0]} -> {newer[1]}' sits directly above "
                f"'## {older[0]} -> {older[1]}', so the releases between "
                f"{older[1]} and {newer[0]} have no entry. {_HOW_TO_FIX}",
            )

    def test_readme_release_history_names_live_engine_version(self):
        """Same rot, second public surface.

        ``Share/README.md`` carries its own "Release history" summary. The
        anchor rules restamp the README header (``**Engine version:**``) but
        explicitly skip this list as changelog history, so the header can read
        1.238.0 while the list below it stops at 1.236.0 - which is exactly what
        was measured on main at 70e5a466.
        """
        live = ds.ENGINE_VERSION
        entries = _entries(_README.read_text(encoding="utf-8"), _README_ENTRY)
        self.assertTrue(
            entries,
            "no '- <old> -> <new> - ' release bullets parsed out of "
            "Share/README.md. The 'Release history' section is a shipped part of "
            "the package; if it was restructured, update _README_ENTRY rather "
            "than dropping the check.",
        )
        newest = max((new for _, new in entries), key=_vtuple)
        self.assertEqual(
            newest, live,
            f"Share/README.md 'Release history' stops at {newest}, but the live "
            f"ENGINE_VERSION is {live}. The README header is auto-restamped and "
            f"already reads {live}, so the page contradicts itself. Add the "
            f"missing release(s) to that list (it names the most recent few) "
            f"alongside the Share/CHANGELOG.md entry.",
        )


if __name__ == "__main__":
    unittest.main()
