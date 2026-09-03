"""Every tracked ``.md`` must be LF on disk, not just LF in the blob.

WHY THIS EXISTS (RM-284, 2026-09-02). ``core.autocrlf=true`` on the Windows
fleet stores LF in the blob but writes CRLF to the working tree. Nothing was
wrong with the CONTENT - the problem is that any size or digest taken from disk
then disagrees with the same file measured anywhere else, by exactly one byte
per line:

  * ``tests/test_doc_size_budget.py`` and ``tools/drift_guard.py`` both measure
    ``ROADMAP.md`` with ``stat().st_size``. Measured on a lane worktree (LF) it
    read 73718 bytes and the guard passed; the identical content on the main
    checkout (CRLF) was 73915 and the guard breached. A lane finished green and
    handed the merger a breach.
  * Lane 8 cycle 29 hit the inverse: a tool rewrote the file LF-only, it
    measured 81917 and shipped green, and the real Windows checkout was 82134 -
    over budget. Linux CI would have stayed green throughout.

``.gitattributes`` now carries ``*.md text eol=lf`` so on-disk equals blob
everywhere. This test is what keeps it true.

HONEST SCOPE, so nobody reads more into a green run than it earns: on Linux CI
every checkout is LF anyway, so this test is nearly VACUOUS there. It has teeth
on a Windows checkout, which is the only place the defect occurs. It also
catches a tool that writes a tracked ``.md`` with ``write_text`` (text mode on
Windows emits CRLF) - that is a real regression path and the reason
``ds_share_sync`` now writes ``MANIFEST.md`` as bytes.
"""
from __future__ import annotations

import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _tracked_md() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


class MarkdownLineEndingTests(unittest.TestCase):
    def test_tracked_md_files_are_tracked_at_all(self) -> None:
        # Guards the guard: an empty file list would make the real assertion
        # below pass without inspecting anything.
        self.assertGreater(
            len(_tracked_md()), 100,
            "expected hundreds of tracked .md files - `git ls-files` returned "
            "almost none, so the CRLF assertion below would be vacuous",
        )

    def test_no_tracked_md_has_crlf_on_disk(self) -> None:
        offenders = []
        for rel in _tracked_md():
            p = ROOT / rel
            if not p.is_file():
                continue  # sparse checkout / case-collision; not this test's job
            n = p.read_bytes().count(b"\r\n")
            if n:
                offenders.append((rel, n))
        offenders.sort(key=lambda t: -t[1])
        self.assertEqual(
            offenders, [],
            "tracked .md files carry CRLF on disk, so any size or digest taken "
            "from them disagrees with the blob by one byte per line. "
            f"{len(offenders)} file(s), worst first: {offenders[:5]}. "
            "Fix: confirm `.gitattributes` has `*.md text eol=lf`, then "
            "re-materialize the working tree "
            "(`git ls-files -z '*.md' | xargs -0 rm -f && git checkout -- .`). "
            "If a tool produced it, make that tool write bytes, not text.",
        )


if __name__ == "__main__":
    unittest.main()
