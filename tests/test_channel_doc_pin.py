"""PORTABLE pin guard for the cross-repo channel doc.

This module is the half of the channel-doc guard that every participating
repository vendors BYTE-IDENTICAL, so it uses the standard library only and
reads NOTHING outside its own repository root. Every RC-only arm - the
sibling-name sweep, the responder grammar, the on-box mirror of the sibling
checkouts - lives in `tests/test_channel_doc_rc_gate.py`, which is never
vendored. A vendored file that reached for an RC-only tool or an RC-only
config shape would fail at import in every sibling tree, and each sibling
would then EDIT it - which is exactly the drift the pin exists to prevent.

Because this module reads only `docs/CHANNEL.md`, it has no skip arm anywhere:
all of its tests run in every checkout and in CI.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# A single-line, whitespace-free literal, so tools/md_guard_selector.py selects
# this module for the docs-guards workflow.
CHANNEL_DOC = "docs/CHANNEL.md"

# RE-PINNING IS A JOINT ACT. Never regenerate this digest from whatever the
# file happens to be locally - that turns the guard into a rubber stamp and
# would launder a unilateral drift into "agreed". Change the shared file on one
# side, hand every other side the exact bytes, re-hash in EVERY tree from its
# OWN disk, confirm they match, and only then write the new digest here and in
# every carrier's copy in the same round, bumping CHANNEL_VERSION with it.
#
# The digest is taken over LF-NORMALISED bytes, not raw bytes, deliberately:
# not every carrier pins `*.md` to LF in its .gitattributes, so a raw-byte pin
# would be red in a tree whose working copy checks out CRLF even though all of
# the git blobs are identical.
#
# CHANNEL_VERSION 1 is pinned in 1 of 5 trees today. That is the honest count,
# and it stays that way until a sibling vendors the bytes.
CHANNEL_PIN = {
    "version": 1,
    "sha256": "899f6eb957cc26ee25993d83d65d8ca291841fe4eec24a48f729c2dc005f4c6b",
}

_VERSION_RE = re.compile(r"^CHANNEL_VERSION: (\d+)$", re.MULTILINE)

# The five heading date shapes a sibling's dated-heading guard grades the
# identical copy against. A heading carrying any of them makes the file
# "dated", and an undeclared dated file is reported as drift THERE, in a tree
# that cannot edit these bytes without a joint re-pin.
_DATE_PATTERNS = (
    re.compile(r"\d{4}-\d{1,2}-\d{1,2}"),
    re.compile(r"\d{2}-\d{2}-\d{2}"),
    re.compile(r"\d{4}/\d{1,2}/\d{1,2}"),
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
    re.compile(
        r"(?:January|February|March|April|May|June|July|August|September"
        r"|October|November|December)[ ,]*\d{4}"
    ),
)

# A `---` (or `===`) rule that follows a non-blank line is a SETEXT heading to a
# strict markdown header scanner, which then stops reading the header early and
# reports the file as carrying no status declaration at all. Blank line before
# every rule.
_SETEXT_UNDERLINE = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$")

# A drive-rooted path in any spelling. The negative lookbehind keeps a bare
# `C:` inside a longer token from firing.
_DRIVE_ROOTED = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]")

# Mirror of the backticked bare-path shape a sibling's docs-citation guard
# enumerates over its own `git ls-files`. Every repo-relative path in the
# shared bytes has to resolve in EVERY tree, and only one of them does.
#
# The segment class admits a literal SPACE after a segment's first character,
# because a path may hold one and this is a BAN arm: a class without it let
# `docs/my notes/x.md` through while refusing its underscore twin. Space only -
# never a newline or a tab - so a match cannot pair backticks across lines, and
# a segment still has to START on a word character.
_BARE_PATH_RE = re.compile(
    r"`\.?[A-Za-z0-9_][A-Za-z0-9_. -]*"
    r"(?:/[A-Za-z0-9_][A-Za-z0-9_. -]*)+"
    r"\.(?:py|md|json|toml|yml|yaml|cfg|txt|ini)`"
)

# A line cite into the gitignored inbox: a note filename with a line number
# glued to it. The directory is absent from a fresh clone and every worktree,
# so such a cite can never resolve anywhere. Same space rule as the path arm:
# a literal space may sit inside the name, a newline, tab or backtick may not.
_INBOX_LINE_CITE = re.compile(r"-from-[A-Za-z]{2,4}-(?:[^\s`]| )*?\.md:\d+")

_PER_REPO_ALIAS = re.compile(r"\bSibling-[A-Z]\b")

ROSTER_CODES = ("CS", "LL", "LW", "RC", "RSC")


def _raw() -> bytes:
    return (REPO_ROOT / CHANNEL_DOC).read_bytes()


def _text() -> str:
    return _raw().decode("ascii")


def _roster_rows() -> list[str]:
    """The code cell of every data row of the roster table in section 0."""
    rows: list[str] = []
    in_roster = False
    past_header = False
    for line in _text().splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_roster = stripped.startswith("## 0.")
            past_header = False
            continue
        if not in_roster or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        # The separator row divides the header from the data; everything before
        # it is a column label, not a roster entry.
        if set(cells[0]) <= set("-: "):
            past_header = True
            continue
        if not past_header:
            continue
        rows.append(cells[0].strip("`"))
    return rows


def test_channel_doc_declares_exactly_one_version_line():
    text = _text()
    matches = _VERSION_RE.findall(text)
    assert len(matches) == 1, f"expected exactly one CHANNEL_VERSION line, found {len(matches)}"
    head = "\n".join(text.splitlines()[:10])
    assert _VERSION_RE.search(head), (
        "the CHANNEL_VERSION line must sit in the first 10 lines, where a reader and a header scanner both find it"
    )
    assert int(matches[0]) == CHANNEL_PIN["version"], (
        f"doc declares CHANNEL_VERSION {matches[0]} but the pin here says "
        f"{CHANNEL_PIN['version']}; a bump without a re-pin is red by design"
    )


def test_channel_doc_matches_the_pinned_cross_repo_digest():
    raw = _raw()
    got = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    assert got == CHANNEL_PIN["sha256"], (
        "docs/CHANNEL.md no longer matches CHANNEL_PIN.\n"
        "This is NOT fixed by pasting the local digest in. Re-sync every\n"
        "participating tree and re-pin all of them in the SAME round, bumping\n"
        "CHANNEL_VERSION with the bytes. Never regenerate this constant from\n"
        "local disk - both trees hashing equal IS the acceptance, not a note\n"
        f"claiming it.\n  pinned: {CHANNEL_PIN['sha256']}\n  on disk: {got}"
    )


def test_channel_doc_is_lf_and_seven_bit_ascii():
    raw = _raw()
    assert b"\r" not in raw, (
        "docs/CHANNEL.md carries CR bytes; write it with LF explicitly "
        "(a text write on Windows turns LF into CRLF and the digest then lies)"
    )
    assert max(raw) <= 127, "docs/CHANNEL.md must be 7-bit ASCII"


def test_channel_doc_carries_no_machine_specific_path():
    text = _text()
    hit = _DRIVE_ROOTED.search(text)
    assert hit is None, f"drive-rooted path in the shared bytes at offset {hit.start() if hit else -1}"
    assert "\\Users\\" not in text, "an expanded account home path is machine-specific"
    lowered = text.lower()
    assert lowered.count("localappdata") == text.count("%LOCALAPPDATA%"), (
        "every LOCALAPPDATA mention must be the unexpanded literal %LOCALAPPDATA%"
    )


def test_channel_doc_headings_carry_no_date_and_declares_live_before_the_first_h2():
    text = _text()
    lines = text.splitlines()
    for number, line in enumerate(lines, start=1):
        if not line.lstrip().startswith("#"):
            continue
        for pattern in _DATE_PATTERNS:
            assert not pattern.search(line), f"date shape in heading at line {number}: {line!r}"

    live = text.find("**Section status: LIVE")
    assert live != -1, "the shared doc must declare its section status"
    first_h2 = text.find("\n## ")
    assert first_h2 != -1, "the shared doc must carry at least one level-2 heading"
    assert live < first_h2, (
        "the LIVE declaration must precede the first '##' - a header scanner "
        "stops at the second heading and would report the file undeclared"
    )

    previous = ""
    for number, line in enumerate(lines, start=1):
        if previous.strip() and _SETEXT_UNDERLINE.match(line):
            raise AssertionError(
                f"line {number} is a setext underline following a non-blank "
                f"line; put a blank line before every rule: {line!r}"
            )
        previous = line


def _forbidden_repo_paths(text: str) -> list[str]:
    """Every backticked repo-relative path in `text` other than the doc itself.

    The single detector the ban arm below grades the shared bytes with, so the
    synthetic arms exercise exactly what the ban applies and cannot drift from it.
    """
    return [m.group(0) for m in _BARE_PATH_RE.finditer(text) if m.group(0) != f"`{CHANNEL_DOC}`"]


def _inbox_line_cites(text: str) -> list[str]:
    return [m.group(0) for m in _INBOX_LINE_CITE.finditer(text)]


def test_channel_doc_carries_no_repo_relative_path_or_line_cite():
    text = _text()
    found = _forbidden_repo_paths(text)
    assert found == [], (
        f"repo-relative path(s) {found} in the shared bytes; each resolves in "
        "at most one tree. Name RC-only artifacts by role or task name instead."
    )
    assert _inbox_line_cites(text) == [], (
        "inbox notes are cited by BARE filename - a line cite into a gitignored directory resolves nowhere"
    )


def test_ban_arm_refuses_a_repo_relative_path_with_a_space_in_it():
    """A space inside a path segment must not carry a token past the ban.

    A repository path may legally hold a space, and a detector whose segment
    class omits it lets `docs/my notes/x.md` through while refusing
    `docs/my_notes/x.md`. In a BAN arm a missed token is a forbidden thing that
    passes, so each shape here has to be refused, and the no-space twin is
    asserted alongside it so the arm cannot pass by refusing nothing.
    """
    spaced = (
        "`docs/my notes/x.md`",
        "`my dir/sub dir/file.json`",
        "`tools/a b.py`",
        "`.github/work flows/ci.yml`",
    )
    for token in spaced:
        twin = token.replace(" ", "_")
        assert _forbidden_repo_paths(f"see {twin} here\n") == [twin], f"control: {twin} must be refused"
        assert _forbidden_repo_paths(f"see {token} here\n") == [token], (
            f"spaced repo-relative path {token} passed the ban arm"
        )
    cite = "`2026-09-16-1200-from-RC-my note.md:12`"
    assert _inbox_line_cites(f"per {cite.replace(' ', '-')}\n"), "control: unspaced inbox line cite must be refused"
    assert _inbox_line_cites(f"per {cite}\n"), f"spaced inbox line cite {cite} passed the ban arm"


def test_ban_arm_does_not_flag_ordinary_prose_with_slashes_and_spaces():
    """Negative controls: widening the segment class must not reach prose."""
    prose = (
        "Use and/or here, with read/write access for the operator.\n"
        "The docs/ and tests/ directories both hold notes.md and CHANNEL.md.\n"
        "`and/or` and `read/write access` are not paths.\n"
        "`CHANNEL_VERSION` bumps with the bytes, see notes/x.md later.\n"
        "`a` then b/c d.md without a closing tick\n"
        "`docs/CHANNEL.md` names the doc itself.\n"
        "```\nsome/dir name\nfile.md`\n```\n"
        "a note-from-RC-topic is cited by name, and CHANNEL.md stays unnumbered\n"
    )
    assert _forbidden_repo_paths(prose) == [], _forbidden_repo_paths(prose)
    assert _inbox_line_cites(prose) == [], _inbox_line_cites(prose)


def test_channel_doc_names_no_per_repo_alias_and_rosters_five_codes_once():
    text = _text()
    alias = _PER_REPO_ALIAS.search(text)
    assert alias is None, (
        f"per-repo alias {alias.group(0) if alias else ''} in the shared bytes; "
        "aliases differ per tree, so an identical file cannot carry them"
    )
    rows = _roster_rows()
    for code in ROSTER_CODES:
        assert rows.count(code) == 1, f"roster names {code} {rows.count(code)} times; expected exactly 1"
    assert sorted(rows) == sorted(ROSTER_CODES), f"roster rows are {rows}, expected exactly {list(ROSTER_CODES)}"
