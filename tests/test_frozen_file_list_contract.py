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
import ast
import pathlib
import re

from tests import _repo_walk

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

# There is deliberately NO local skip list here any more. The header scan used
# to hand-maintain HEADER_SCAN_SKIP_DIRS = {.git, _archive, .venv, venv,
# node_modules, __pycache__, rc-worktrees, worktrees} over an os.walk of the
# whole repo root. Every one of those eight names is now covered by
# tests/_repo_walk.EXCLUDED_DIRS, and the tracked-set filter in front of it
# removes far more besides - which is the actual fix for the defect this guard
# hit: ops/runtime/responder_export/<sha>/ is a full untracked COPY OF THE REPO
# written by the inbox responder, so twelve real frozen modules were being seen
# twice per export and reported as orphan frozen=yes headers on this box while
# CI (no exports on disk) stayed green.
#
# Nothing remains that is genuinely this guard's OWN scope choice: the original
# rationale - "the worktree entries duplicate real modules verbatim, so scanning
# one would manufacture phantom frozen entries for copy paths" - is exactly the
# duplicate-copy problem the shared walker exists to solve, for worktrees and
# for every other copy tree alike. Re-adding a name here (responder_export
# included) is the hand-list fix that RM-394 rejected: the next copy tree with a
# different name would reopen the same hole. If a future need really is local to
# this guard, apply it ON TOP of _repo_walk.repo_files, the way
# tests/test_riot_api_cache_eviction.py applies its own {tests, docs} skip.

# gen_archmap.py reads only the first 8 lines when looking for a file-header
# marker; mirror that window so this guard and the generator agree on what
# counts as a header.
_HEADER_WINDOW = 8

# The hand-maintained mirrors that MUST equal the authority exactly, as
# (module path, symbol name). Each is a literal frozenset of the same paths,
# kept in sync by hand, and each was unguarded until this module existed.
# Adding a sixth mirror without adding it here is the only way this drift class
# can recur - so add the row in the same commit that adds the mirror.
PARITY_MIRRORS = (
    ("tools/ci_watchdog.py", "FROZEN_FILES"),
    ("tools/strip_smart_quotes.py", "_FROZEN"),
    ("tools/repair_mojibake.py", "_FROZEN"),
    ("agents/agent1_lead/scheduler.py", "FROZEN_FILES"),
)

# core/hot_reload.py::_FROZEN_PATHS is a DELIBERATE SUBSET, not a parity mirror,
# and must never be forced to equality. It watches non-frozen `.py` files only
# (module docstring line 1; the watch dirs "only contain editable .py"), so a
# `.md` entry cannot be watched and therefore cannot be left unprotected by its
# absence. It gets a subset assertion plus a pin on which omissions are allowed.
SUBSET_MIRROR = ("core/hot_reload.py", "_FROZEN_PATHS")

_BACKTICKED = re.compile(r"`([^`]+)`")


def _literal_frozen_set(rel, symbol):
    """Return the string entries of a module-level frozenset/set literal.

    Parsed with `ast` rather than imported: these modules are mirrors of a hard
    rule, and a guard over them should not depend on any of them being safely
    importable. `tools/ci_watchdog.py` is import-clean today, but that is a
    property of one mirror and not of the class.
    """
    tree = ast.parse(_read(rel))
    for node in ast.walk(tree):
        # AnnAssign as well as Assign: core/hot_reload.py declares its set as
        # `_FROZEN_PATHS: set[str] = {...}`, and an Assign-only match skips it
        # entirely - which surfaces as "mirror not found" rather than a wrong
        # answer, but only because the not-found case raises instead of
        # returning an empty set.
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        if symbol not in names or node.value is None:
            continue
        value = node.value
        # frozenset({...}) / set({...}) wrap the literal in a call.
        if isinstance(value, ast.Call) and value.args:
            value = value.args[0]
        # Each element is walked rather than matched as a bare Constant: the
        # mirrors are not written the same way. core/hot_reload.py wraps every
        # entry as Path("x").as_posix() for cross-platform separators, so a
        # Constant-only match silently yields an EMPTY set - a pattern bug that
        # reads as "the mirror is empty" rather than "my parser missed".
        out = set()
        for el in getattr(value, "elts", []):
            for sub in ast.walk(el):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out.add(sub.value)
        return out
    raise AssertionError(
        "no module-level '" + symbol + "' literal found in " + rel
        + ". If the mirror was renamed or removed, update PARITY_MIRRORS in this "
        "guard in the same commit - a mirror this test cannot find is a mirror "
        "nobody is checking."
    )


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
    """Return the forward-slashed .py paths whose `# arch:` header says frozen=yes.

    Enumeration comes from tests/_repo_walk - the repo's canonical sweep - not
    from a local os.walk plus a hand-list. That means the git INDEX is the
    primary filter, with EXCLUDED_DIRS as the backstop when git is unavailable,
    so untracked copy trees (worktrees, vendored bytes, and the responder's
    ops/runtime/responder_export/<sha>/ repo copies) cannot manufacture phantom
    frozen entries. `tracked_relpaths` returns None rather than an empty set on
    a git failure, so a broken git degrades to the directory skips instead of
    silently reporting an empty tree.

    Everything the guard needs is preserved: the first-`_HEADER_WINDOW`-lines
    rule, the `# arch:` + `frozen=yes` predicate, forward-slashed repo-relative
    results, and tolerance of unreadable files.

    Non-vacuity: an empty scan and a clean tree are the same verdict to both
    consumers of this function, so the walker's own anchor check is called first
    and raises rather than letting the guards pass for the wrong reason.
    """
    _repo_walk.self_check(ROOT)
    found = set()
    for path in _repo_walk.iter_repo_files(ROOT, patterns=("*.py",)):
        try:
            head = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in head[:_HEADER_WINDOW]:
            stripped = line.strip()
            if stripped.startswith("# arch:") and "frozen=yes" in stripped:
                found.add(_repo_walk.relative_posix(path, ROOT))
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


def test_every_parity_mirror_equals_claude_md_authority():
    """Each hand-maintained mirror in PARITY_MIRRORS must equal the authority.

    Checking only ONE mirror is what let this drift survive. Measured 2026-08-02:
    tools/ci_watchdog.py, tools/strip_smart_quotes.py and tools/repair_mojibake.py
    all held 16 and agreed, while agents/agent1_lead/scheduler.py held 13 - missing
    app/_loop.py, tools/diagnose.md and tools/caveman.md - and had been unchanged
    since the initial commit while the authority moved underneath it. Its own
    comment claims it is "Synced with CLAUDE.md", so the drift was invisible to a
    reader and to every test.

    The consequences differ per mirror and none of them fails loudly:
      ci_watchdog  - touches_frozen() stops the CI watchdog auto-merging a fix
                     into a frozen file. A missing entry means it merges.
      scheduler    - Scheduler.file_task() appends category 1, which maps to
                     NEEDS_APPROVAL and withholds the task from the ready heap.
                     A missing entry means an agent edits a frozen file with no
                     approval stop.
      strip_smart_quotes / repair_mojibake
                   - both skip frozen files when rewriting bytes repo-wide. A
                     missing entry means an unattended rewrite of a frozen file.
    """
    authority = set(_parse_frozen_authority())
    drifted = {}
    for rel, symbol in PARITY_MIRRORS:
        mirror = _literal_frozen_set(rel, symbol)
        if mirror != authority:
            drifted[rel + "::" + symbol] = {
                "in_claude_md_but_not_the_mirror": sorted(authority - mirror),
                "in_the_mirror_but_not_claude_md": sorted(mirror - authority),
            }
    assert not drifted, (
        "hand-maintained frozen-file mirror(s) have drifted from the CLAUDE.md "
        "frozen list: " + repr(drifted) + ". Fix the MIRROR to match CLAUDE.md, "
        "never the reverse - CLAUDE.md is the authority. Do not add a mirror to "
        "PARITY_MIRRORS-with-an-exception to make this pass; if a mirror is a "
        "deliberate subset, it belongs with core/hot_reload.py under the subset "
        "test below, with the reason written down."
    )


def test_hot_reload_subset_mirror_omits_only_non_python_entries():
    """core/hot_reload.py::_FROZEN_PATHS is a SUBSET on purpose - keep it one.

    It is not a parity mirror and must never be forced to equality. hot_reload
    watches non-frozen `.py` files only, and its watch dirs contain nothing else,
    so a `.md` on the authority list cannot be watched and therefore cannot be
    left unprotected by its absence. Forcing equality would be a wrong change
    made to satisfy a test.

    What IS checked: it may never contain anything absent from the authority, and
    the only entries it is allowed to omit are the non-`.py` ones. That catches
    the real risk - a frozen `.py` quietly dropping out of the watcher's skip set
    and becoming hot-reloadable.
    """
    authority = set(_parse_frozen_authority())
    rel, symbol = SUBSET_MIRROR
    mirror = _literal_frozen_set(rel, symbol)
    extra = sorted(mirror - authority)
    assert not extra, (
        rel + "::" + symbol + " names paths that are NOT on the CLAUDE.md frozen "
        "list: " + repr(extra) + ". Either add them to the CLAUDE.md bullet or "
        "drop them here."
    )
    omitted = sorted(authority - mirror)
    non_py = sorted(e for e in authority if not e.endswith(".py"))
    assert omitted == non_py, (
        rel + "::" + symbol + " omits " + repr(omitted) + " but the only omissions "
        "allowed are the non-.py authority entries " + repr(non_py) + ". A frozen "
        ".py missing from this set is hot-reloadable, which is exactly what the "
        "frozen rule forbids - add it back rather than widening this assertion."
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
