"""Every tracked file git normalizes to LF must BE LF on disk, not just in the blob.

WHY THIS EXISTS (RM-284, 2026-09-02; widened 2026-09-03). ``core.autocrlf=true``
on the Windows fleet stores LF in the blob but writes CRLF to the working tree.
Nothing is wrong with the CONTENT - the problem is that any size or digest taken
from disk then disagrees with the same file measured anywhere else, by exactly
one byte per line:

  * ``tests/test_doc_size_budget.py`` and ``tools/drift_guard.py`` both measure
    ``ROADMAP.md`` with ``stat().st_size``. Measured on a lane worktree (LF) it
    read 73718 bytes and the guard passed; the identical content on the main
    checkout (CRLF) was 73915 and the guard breached. A lane finished green and
    handed the merger a breach.
  * The inverse also shipped: a tool rewrote the file LF-only, it measured 81917
    and went green, and the real Windows checkout was 82134 - over budget. Linux
    CI would have stayed green throughout.

``.gitattributes`` pins the text types to ``eol=lf`` so on-disk equals blob
everywhere. This test is what keeps it true.

THE FILE SET IS ASKED OF GIT, NOT INFERRED. Two separate reasons, both learned
the hard way:

  * Hardcoding the pinned suffix list here would let this test and
    ``.gitattributes`` drift apart silently - a contract test that carries its
    own copy of the contract cannot detect the contract changing (memory
    ``feedback_contract_test_must_read_the_contract_from_disk``).
  * Filtering by SUFFIX is the wrong filter and produced a false failure on the
    first run. ``data/daemon_slayer/laning_scenarios/**/*.json`` matches
    ``*.json`` but carries ``-text`` from the LFS rule, so git deliberately does
    not convert it - 7 LFS payloads were reported as offenders when the tree was
    correct. The evaluator filter has to be the one the data actually uses,
    ``git check-attr`` (memory ``feedback_data_filter_vs_evaluator_filter``).

HONEST SCOPE, so nobody reads more into a green run than it earns: on Linux CI
every checkout is LF anyway, so this test is nearly VACUOUS there. It has teeth
on a Windows checkout, which is the only place the defect occurs. It also
catches a tool that writes a tracked, pinned file with ``write_text`` - text
mode emits CRLF on Windows, so a generator whose output is byte-compared must
write bytes rather than text.

DELIBERATELY NOT PINNED, and therefore not asserted: ``.bat`` / ``.cmd``
(Windows shell scripts - the tracked ``.bat`` are already LF and the ``.cmd``
are CRLF; pinning either way churns live launch scripts to buy nothing), and
``.log`` / ``.jsonl`` (immutable and append-only history, which CLAUDE.md
exempts from repo-wide sweeps). Their absence is intentional, not an oversight;
``test_bat_and_cmd_are_deliberately_unpinned`` is where anyone changing that
will be made to decide it consciously.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
NUL = "\x00"
_PIN = re.compile(r"^\*(\.[A-Za-z0-9]+)\s+text\s+eol=lf\s*$")


def pinned_suffixes() -> set[str]:
    """The `*.<ext> text eol=lf` pins, read from `.gitattributes` itself."""
    out: set[str] = set()
    raw = (ROOT / ".gitattributes").read_bytes().decode("utf-8")
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        m = _PIN.match(line)
        if m:
            out.add(m.group(1).lower())
    return out


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split(NUL) if p]


def lf_normalized_files() -> list[str]:
    """Files git will ACTUALLY write with LF - asked of git, never inferred."""
    files = tracked_files()
    proc = subprocess.run(
        ["git", "check-attr", "--stdin", "-z", "text", "eol"],
        cwd=ROOT, input=NUL.join(files),
        capture_output=True, text=True, check=True,
    )
    fields = proc.stdout.split(NUL)
    attrs: dict[str, dict[str, str]] = {}
    for i in range(0, len(fields) - 2, 3):
        path, attr, value = fields[i], fields[i + 1], fields[i + 2]
        if path:
            attrs.setdefault(path, {})[attr] = value
    return [f for f, a in attrs.items()
            if a.get("text") == "set" and a.get("eol") == "lf"]


class PinnedTextLineEndingTests(unittest.TestCase):
    def test_the_pin_list_parses_and_is_not_empty(self) -> None:
        # Guards the guard: a stale regex, an empty `git ls-files`, or a
        # check-attr that resolved nothing would each make the real assertion
        # below pass while inspecting zero bytes.
        pins = pinned_suffixes()
        self.assertIn(".md", pins, ".gitattributes should pin *.md - the regex "
                                   "in this test may have gone stale")
        self.assertGreaterEqual(
            len(pins), 10,
            f"expected the widened pin list, parsed only {sorted(pins)}",
        )
        self.assertGreater(len(tracked_files()), 1000)
        self.assertGreater(len(lf_normalized_files()), 1000)

    def test_bat_and_cmd_are_deliberately_unpinned(self) -> None:
        # Pinning these would churn live launch/restart scripts. If someone adds
        # the pin later that is a real decision, and this is where they are
        # asked to make it consciously rather than by autopilot.
        pins = pinned_suffixes()
        self.assertNotIn(".bat", pins)
        self.assertNotIn(".cmd", pins)
        self.assertNotIn(".jsonl", pins)
        self.assertNotIn(".log", pins)

    def test_lfs_payloads_are_excluded_from_normalization(self) -> None:
        # The LFS rule carries `-text`, and it must keep winning over `*.json`.
        # Without this, a reordering of .gitattributes would silently start
        # rewriting LFS payloads and this suite would not notice.
        lf = set(lf_normalized_files())
        lfs = [f for f in tracked_files()
               if f.startswith("data/daemon_slayer/laning_scenarios/")
               and f.endswith(".json")]
        self.assertTrue(lfs, "expected tracked LFS scenario payloads")
        self.assertEqual(
            [f for f in lfs if f in lf], [],
            "LFS payloads must keep `-text` and stay out of eol normalization",
        )

    def test_no_normalized_tracked_file_has_crlf_on_disk(self) -> None:
        offenders: list[tuple[str, int]] = []
        for rel in lf_normalized_files():
            p = ROOT / rel
            if not p.is_file():
                continue  # sparse checkout / case collision; not this test's job
            n = p.read_bytes().count(b"\r\n")
            if n:
                offenders.append((rel, n))
        offenders.sort(key=lambda t: -t[1])
        self.assertEqual(
            offenders, [],
            "tracked files git normalizes to LF carry CRLF on disk, so any size "
            "or digest taken from them disagrees with the blob by one byte per "
            f"line. {len(offenders)} file(s), worst first: {offenders[:5]}. "
            "Fix: re-materialize the working tree - "
            "`git ls-files -z | xargs -0 rm -f && git checkout -- .` - or, if a "
            "tool produced it, make that tool write bytes rather than text.",
        )


if __name__ == "__main__":
    unittest.main()
