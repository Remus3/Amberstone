"""The CHANGELOG must gain an entry on every ENGINE_VERSION bump.

``agents/daemon_slayer/__init__.py`` mandates that a bump PREPENDS one entry to
``CHANGELOG.md``. Nothing enforced it, and two consecutive bumps slipped through
unnoticed - 1.224.0 (R132) and 1.225.0 (R136) both shipped with no entry, and the
gap was only found a session later while auditing something else. Across the whole
file eight versions that provably existed in git had no entry.

This is the cheapest guard that would have caught it: the NEWEST entry in the
changelog must name the CURRENT ENGINE_VERSION. A bump without a prepend fails
here immediately, in the same suite the bump already has to run.

Deliberately NOT asserted: full historical completeness. Eight older versions are
still missing entries and reconstructing them from commit diffs is a separate,
optional job - failing the suite on that backlog would train the rubber stamp
rather than protect the next bump.

Measured when this guard was written: 188 entries, newest 1.226.0, oldest 1.17.0,
zero duplicates, strict newest-first order. The ordering and duplicate assertions
below therefore start GREEN over the whole file and need no historical exemption.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve()
_PKG = _HERE.parent.parent
_CHANGELOG = _PKG / "CHANGELOG.md"

# An entry STARTS A PARAGRAPH with an engine semver followed by " (".
#
# Both halves of this pattern are load-bearing and were arrived at by measurement,
# not by guessing. A plain ^ anchor over \d+\.\d+\.\d+ over-matches TWICE on the
# live file: CHANGELOG.md:1691 wraps the prose "16.13.1 (items['3040'] passive ..."
# onto its own line, and :6979 wraps "1.25.0 (item 122). Engine-side math ...".
# Both are mid-paragraph continuations, not headers. Requiring a preceding blank
# line rejects both, and restricting the major to 1 keeps a patch stamp such as
# 16.13.1 from ever reading as an engine version.
_ENTRY_RE = re.compile(r"(?:^|\n)\n(1\.\d+\.\d+) \(")


def _engine_version() -> str:
    """Read the quoted literal without importing the package.

    Importing agents.daemon_slayer pulls the whole engine in; the literal is the
    single source of truth and a regex over it keeps this guard import-free.
    """
    src = (_PKG / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^ENGINE_VERSION\s*=\s*"([^"]+)"', src, re.M)
    assert m is not None, "ENGINE_VERSION literal not found in __init__.py"
    return m.group(1)


class ChangelogTracksEngineVersionTests(unittest.TestCase):

    def test_changelog_exists_and_has_entries(self):
        self.assertTrue(_CHANGELOG.is_file(), f"missing {_CHANGELOG}")
        entries = _ENTRY_RE.findall(_CHANGELOG.read_text(encoding="utf-8"))
        self.assertTrue(entries, "no changelog entries parsed - the entry format changed")

    def test_newest_entry_matches_current_engine_version(self):
        entries = _ENTRY_RE.findall(_CHANGELOG.read_text(encoding="utf-8"))
        current = _engine_version()
        self.assertEqual(
            entries[0], current,
            f"ENGINE_VERSION is {current} but the newest CHANGELOG entry is "
            f"{entries[0]}. Every bump must PREPEND an entry - see the module "
            f"docstring in agents/daemon_slayer/__init__.py.")

    def test_entries_are_newest_first(self):
        entries = _ENTRY_RE.findall(_CHANGELOG.read_text(encoding="utf-8"))
        keyed = [tuple(int(p) for p in e.split(".")) for e in entries]
        self.assertEqual(
            keyed, sorted(keyed, reverse=True),
            "changelog entries are not in strict newest-first order")

    def test_no_duplicate_entry_versions(self):
        entries = _ENTRY_RE.findall(_CHANGELOG.read_text(encoding="utf-8"))
        dupes = sorted({e for e in entries if entries.count(e) > 1})
        self.assertEqual(dupes, [], f"duplicate changelog entries: {dupes}")


if __name__ == "__main__":
    unittest.main()
