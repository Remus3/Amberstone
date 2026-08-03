"""Guard: the frozen-file hard list has FOUR representations - keep them tied.

The list is AUTHORED once, in the CLAUDE.md "Frozen files" bullet, and then
restated in three derived places. Until this module existed, only the authority
itself was guarded, and only shallowly: tests/test_constraint_single_source.py
:: test_frozen_files_list_present_and_canonical asserts the heading plus three
anchor substrings are present. It never parses the list, never checks the paths
resolve, and never relates any mirror back to the authority.

The four representations:

  1. CLAUDE.md "Frozen files" bullet   - THE AUTHORITY. Everything else follows
     it, never the reverse.
  2. tools/ci_watchdog.py FROZEN_FILES - a hardcoded mirror, consumed by
     touches_frozen(), which is what stops the CI watchdog auto-merging a fix
     into a frozen file. Nothing asserted the mirror still equalled the
     authority, so an entry added to CLAUDE.md alone left the watchdog silently
     auto-merging into a newly-frozen file. That is the same silent-mirror-drift
     class that ran for a month between tools/*.md and .claude/commands/*.md.
  3. the `# arch: ... | frozen=yes` file headers - DERIVED and deliberately
     incomplete (see test_frozen_arch_headers_are_a_subset_of_the_authority).
  4. ruff.toml [lint.per-file-ignores] - names frozen modules individually so
     BLE001 is baselined by config rather than by inline noqa.

This module READS THE CONTRACT OFF DISK. It deliberately does not hardcode the
paths: a literal expected list here would simply be a FIFTH representation and
would reproduce the exact drift class it is meant to close. The only hardcoded
number is the COUNT, because a change in the count is precisely the event that
should force a human to look.
"""
import os
import pathlib
import re

from tools import ci_watchdog as cw

ROOT = pathlib.Path(__file__).resolve().parents[1]

# A change to this number is not a test failure to "fix" - it means the frozen
# list gained or lost an entry, which is a decision that needs a human.
EXPECTED_FROZEN_COUNT = 16

# The `.py` entries on the authority list that carry NO `# arch: ... frozen=yes`
# header. This pins the CURRENT documented exception set; it is not a second
# source of truth for what is frozen.
HEADERLESS_FROZEN_PY = frozenset({
    "ops/rc_dev_runtime.py",
    "ops/rc_supervisor.py",
})

# Directories the `# arch:` header scan skips. Share/ is the Daemon Slayer
# distribution mirror and duplicates real modules verbatim, so scanning it would
# manufacture phantom frozen entries for mirror paths that are not - and must
# not be - on the authority list. The rest is VCS / vendor / build / archive
# noise. Keep this list minimal and justified: an over-broad exclusion is how
# live code gets misdiagnosed as absent.
HEADER_SCAN_SKIP_DIRS = frozenset({
    ".git",
    "_archive",
    "Share",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "rc-worktrees",
    "worktrees",
})

# gen_archmap.py reads only the first 8 lines when looking for a file-header
# marker; mirror that window so this guard and the generator agree on what
# counts as a header.
_HEADER_WINDOW = 8

_BACKTICKED = re.compile(r"`([^`]+)`")


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _parse_frozen_authority():
    """Return the frozen entries parsed out of the CLAUDE.md bullet, in order.

    The bullet is a marker line followed by indented continuation lines, each
    holding backticked, comma-separated paths. The block ends at the first blank
    or non-indented line.
    """
    lines = _read("CLAUDE.md").splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip("- ").startswith("**Frozen files**"):
            start = i
            break
    assert start is not None, (
        "CLAUDE.md has no '- **Frozen files**' bullet. The frozen list is the "
        "authority for tools/ci_watchdog.py FROZEN_FILES and for the "
        "'# arch: ... frozen=yes' headers - restore the bullet in CLAUDE.md "
        "rather than relaxing this guard."
    )
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip() or not line.startswith(" "):
            break
        block.append(line)
    return _BACKTICKED.findall(chr(10).join(block))


def _scan_frozen_headers():
    """Return the forward-slashed .py paths whose `# arch:` header says frozen=yes."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in HEADER_SCAN_SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = pathlib.Path(dirpath) / name
            try:
                head = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in head[:_HEADER_WINDOW]:
                stripped = line.strip()
                if stripped.startswith("# arch:") and "frozen=yes" in stripped:
                    found.add(path.relative_to(ROOT).as_posix())
                    break
    return found


def test_claude_md_frozen_list_parses_to_expected_shape():
    entries = _parse_frozen_authority()
    assert len(entries) == EXPECTED_FROZEN_COUNT, (
        "CLAUDE.md frozen list parsed to " + str(len(entries)) + " entries, expected "
        + str(EXPECTED_FROZEN_COUNT) + ". If the list genuinely changed, update "
        "EXPECTED_FROZEN_COUNT here AND tools/ci_watchdog.py FROZEN_FILES in the "
        "same commit; if it did not, the bullet formatting broke the parser. "
        "Parsed: " + repr(entries)
    )
    for entry in entries:
        assert chr(92) not in entry, (
            "frozen entry " + repr(entry) + " uses a backslash. Write frozen paths "
            "forward-slashed and repo-relative in CLAUDE.md - tools/ci_watchdog.py "
            "touches_frozen() normalises git output to forward slashes and would "
            "never match a backslashed entry."
        )
        assert entry.strip() == entry and " " not in entry, (
            "frozen entry " + repr(entry) + " contains whitespace. Give each path "
            "its own backticks in CLAUDE.md so the list parses one path per entry."
        )
        assert not entry.startswith("/") and ":" not in entry, (
            "frozen entry " + repr(entry) + " looks absolute. Frozen paths are "
            "repo-relative so they match git's changed-file output."
        )
    dupes = sorted({e for e in entries if entries.count(e) > 1})
    assert not dupes, (
        "duplicate frozen entries in CLAUDE.md: " + repr(dupes) + ". Remove the "
        "repeat - a duplicate inflates the count and hides a real addition."
    )


def test_every_frozen_entry_exists_on_disk():
    missing = [e for e in _parse_frozen_authority() if not (ROOT / e).is_file()]
    assert not missing, (
        "frozen entries name files that do not exist: " + repr(missing) + ". A "
        "frozen list pointing at a moved or deleted file is a dead guard - it "
        "protects nothing. Update the CLAUDE.md frozen list to the new path (and "
        "tools/ci_watchdog.py FROZEN_FILES with it), or drop the entry."
    )


def test_ci_watchdog_mirror_equals_claude_md_authority():
    """tools/ci_watchdog.py FROZEN_FILES must equal the CLAUDE.md list exactly.

    A plain import is used rather than an ast parse of the frozenset literal:
    ci_watchdog.py's own module docstring states nothing runs at import time, and
    tests/test_ci_watchdog.py already imports it the same way - so there are no
    import side effects to route around, and importing checks the real consumed
    value instead of a source-text lookalike.
    """
    authority = set(_parse_frozen_authority())
    mirror = set(cw.FROZEN_FILES)
    missing_from_mirror = sorted(authority - mirror)
    extra_in_mirror = sorted(mirror - authority)
    assert authority == mirror, (
        "tools/ci_watchdog.py FROZEN_FILES has drifted from the CLAUDE.md frozen "
        "list. In CLAUDE.md but NOT in the mirror: " + repr(missing_from_mirror)
        + ". In the mirror but NOT in CLAUDE.md: " + repr(extra_in_mirror)
        + ". Fix tools/ci_watchdog.py to match CLAUDE.md, never the reverse - "
        "CLAUDE.md is the authority. While they disagree, touches_frozen() lets "
        "the CI watchdog auto-merge a fix into a file the operator froze."
    )


def test_frozen_arch_headers_are_a_subset_of_the_authority():
    """Every `frozen=yes` header must name a file on the authority list.

    The direction is the whole point and is asymmetric ON PURPOSE. A header
    claiming frozen for a file that is NOT on the CLAUDE.md list is drift and
    fails here. The reverse - an authority entry with no header - is EXPECTED and
    must not fail: tools/gen_archmap.py:22-23 states the frozen-file list in
    CLAUDE.md is manually maintained because it includes non-Python files (.ps1,
    .json, .xml, .md) that cannot carry `# arch:` headers at all.

    So do NOT "fix" this by computing the frozen set from the headers. The header
    set is structurally incapable of expressing the authority.
    """
    authority = set(_parse_frozen_authority())
    headers = _scan_frozen_headers()
    orphans = sorted(headers - authority)
    assert not orphans, (
        "these files carry a '# arch: ... frozen=yes' header but are NOT on the "
        "CLAUDE.md frozen list: " + repr(orphans) + ". Either add them to the "
        "CLAUDE.md frozen bullet (and to tools/ci_watchdog.py FROZEN_FILES), or "
        "drop the frozen=yes claim from the header. A header nobody enforces "
        "reads as protection that does not exist."
    )


def test_header_less_frozen_python_entries_are_pinned():
    """Pin the .py authority entries that carry no `frozen=yes` header.

    Two modules are on the frozen list with docstring prose only and no
    `# arch:` header (ops/rc_supervisor.py line 2 reads "Phase 0 control plane
    (FROZEN)"). That is the documented status quo. Pinning it means a NEW
    header-less frozen module cannot be added silently.
    """
    py_entries = {e for e in _parse_frozen_authority() if e.endswith(".py")}
    headerless = py_entries - _scan_frozen_headers()
    assert headerless == set(HEADERLESS_FROZEN_PY), (
        "the set of frozen .py files without a 'frozen=yes' header changed: "
        + repr(sorted(headerless)) + ", pinned as " + repr(sorted(HEADERLESS_FROZEN_PY))
        + ". If you froze a new module, add the '# arch: <role> | section=<s> | "
        "frozen=yes' header to it (first 8 lines) so tools/gen_archmap.py picks it "
        "up - do NOT widen this pin. Widening it is how the header set silently "
        "stops describing what is frozen."
    )
