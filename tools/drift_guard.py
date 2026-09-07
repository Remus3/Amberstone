"""Per-session drift guard. Cheap invariant checks, run at every /done.

WHY THIS EXISTS
---------------
Drift in this repo does not announce itself. It accumulates silently across
sessions and then costs a WHOLE DEDICATED SESSION to unpick. Measured examples,
every one of which actually happened here:

  * ROADMAP.md silently breached its 80KB CI budget and SAT over it, forcing two
    emergency relocation passes in one session (LEDGER 1063).
  * ``tools/done.md`` and ``.claude/commands/done.md`` are two copies of the SAME
    ritual document. They diverged for a MONTH, preserving an
    ADR-012-decommissioned instruction that sessions kept following.
  * 27 orphaned docs accumulated before anyone noticed; archiving them took most
    of a session (LEDGER 1064).
  * 11 authored ``.claude/commands/*.md`` had ZERO version control for months,
    because the directory is gitignored.
  * An ENGINE bump left a stale version in ``docs/HEXCORE_offline.html`` - a
    FOURTH anchor site no checklist named - and it surfaced only 25 minutes into
    a full CI run (2026-07-26, ENGINE 1.259.0).
  * A release-history doc said "the fifteen most recent" above a list of twenty.

Each of those is seconds to DETECT and a session to REPAIR. That asymmetry is
the entire argument for this file.

WHY A SCRIPT AND NOT A CHECKLIST ITEM
-------------------------------------
Because a prose checklist is precisely what drifted. The mirror rule above sat
WRONG inside a document for a month while that same document instructed every
session to follow it. A check that executes cannot rot silently; a paragraph
telling a reader to remember something can, and did.

CONTRACT
--------
Exit 0 = clean, exit 1 = at least one breach. Every check is pure and takes its
roots as arguments so the test suite can exercise both the breach and the clean
path - a check that can only ever pass is worse than no check, because it buys
false confidence.

Usage:
    python tools/drift_guard.py                 # every session
    python tools/drift_guard.py 1.258.0         # after a bump: pass the OLD version
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ---- CONFIG - the only per-project section --------------------------------
# Budgets mirror the CI size checks. The guard warns at 90 percent because at
# 100 percent the relocation is already an emergency.
DOC_BUDGETS = {"ROADMAP.md": 81920, "CLAUDE.md": 61440}
BUDGET_WARN_PCT = 90.0

# Same-basename .md in both directories must be byte-identical.
MIRROR_PAIRS = [("tools", ".claude/commands")]

# Resolved under THIS account's home rather than baked in: a guard naming
# another account's home silently finds nothing, and a guard that finds nothing
# reports nothing.
MEMORY_DIR = (
    pathlib.Path.home() / ".claude" / "projects" / "C--Riot-Commander" / "memory"
)
MEMORY_INDEX = "MEMORY.md"
# The ~99 per-champion sweep memories are deliberately not indexed individually;
# MEMORY.md carries one line covering the closed 173/173 sweep instead.
# "_"-prefixed files are transient session scratch (hand-off notes, next-session
# cards), not memories - they carry no description frontmatter and are not
# meant to outlive their session, so the index does not track them.
MEMORY_UNINDEXED_OK = ("project_ds_sweep_", "_")

DOC_GLOBS = ("*.md", "docs/*.md", "docs/**/*.md", "docs/**/*.html")
# Files that legitimately name OLD versions forever.
HISTORICAL = re.compile(r"CHANGELOG|HISTORY|LEDGER|WAKEUP|_archive|ROADMAP_HISTORY", re.I)
EXCLUDE_PATH = ("_archive", "node_modules", ".git")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One breach. ``kind`` groups them; ``message`` is operator-facing."""

    kind: str
    message: str


def _iter_docs(root: pathlib.Path) -> list[pathlib.Path]:
    seen: set[pathlib.Path] = set()
    for pattern in DOC_GLOBS:
        for p in root.glob(pattern):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if any(x in rel for x in EXCLUDE_PATH):
                continue
            seen.add(p)
    return sorted(seen)


def check_doc_budgets(
    root: pathlib.Path, budgets: dict[str, int]
) -> list[Finding]:
    """A CI-budgeted doc that is over, or close enough that it will be soon."""
    out: list[Finding] = []
    for name, budget in budgets.items():
        p = root / name
        if not p.is_file() or budget <= 0:
            continue
        size = p.stat().st_size
        pct = 100.0 * size / budget
        if size > budget:
            out.append(Finding(
                "doc-budget",
                f"{name} is {size} bytes, OVER its {budget}-byte budget "
                f"({pct:.0f}%) - relocate content now",
            ))
        elif pct >= BUDGET_WARN_PCT:
            out.append(Finding(
                "doc-budget",
                f"{name} at {pct:.0f}% of its {budget}-byte budget - "
                "relocate before it breaches",
            ))
    return out


def check_mirror_parity(
    root: pathlib.Path, pairs: list[tuple[str, str]]
) -> list[Finding]:
    """Two copies of one document must not disagree.

    Only files present on BOTH sides are compared - a command that exists in one
    place only is normal, not drift.
    """
    out: list[Finding] = []
    for a, b in pairs:
        da, db = root / a, root / b
        if not (da.is_dir() and db.is_dir()):
            continue
        for fa in sorted(da.glob("*.md")):
            fb = db / fa.name
            if not fb.is_file():
                continue
            # Compare CONTENT, not raw bytes. .claude/ is gitignored
            # (.gitignore:116), so the *.md text eol=lf rule added for
            # RM-284 normalises the tools/ side and can never touch the
            # .claude/ side - a raw-byte compare would then report every
            # mirrored file as drifted on line endings alone. This guard
            # exists to catch two copies of a document DISAGREEING.
            _norm = lambda b: b.replace(b"\r\n", b"\n")
            if _norm(fa.read_bytes()) != _norm(fb.read_bytes()):
                newer = fa if fa.stat().st_mtime > fb.stat().st_mtime else fb
                out.append(Finding(
                    "mirror-drift",
                    f"{a}/{fa.name} != {b}/{fa.name} - promote the NEWER side "
                    f"({newer.relative_to(root).as_posix()}) and re-mirror",
                ))
    return out


def check_memory_index(
    memory_dir: pathlib.Path, exempt_prefixes: tuple[str, ...]
) -> list[Finding]:
    """An unindexed memory is invisible to the next session; a dead link lies."""
    out: list[Finding] = []
    if not memory_dir.is_dir():
        return out
    index = memory_dir / MEMORY_INDEX
    if not index.is_file():
        return [Finding("memory-index", f"no {MEMORY_INDEX} in {memory_dir}")]
    text = index.read_text(encoding="utf-8", errors="replace")
    files = {p.stem for p in memory_dir.glob("*.md") if p.name != MEMORY_INDEX}
    linked = set(re.findall(r"\]\(([A-Za-z0-9_\-]+)\.md\)", text))
    # MEMORY.md may delegate a whole section to a sub-index instead of linking
    # every memory individually (e.g. INDEX_ds.md carries the 73-entry Daemon
    # Slayer section - see MEMORY.md's own pointer line). Follow ONLY links
    # whose stem starts with "INDEX_", and only ONE level deep:
    #   - restricted to the INDEX_ prefix on purpose - ordinary memory bodies
    #     use [[wikilink]] syntax, not markdown ](name.md) links, so recursing
    #     into every linked file would find nothing there while risking
    #     treating an arbitrary memory as an index. Do not "simplify" this
    #     into a full recursion.
    #   - one level only - a sub-index linking a sub-sub-index is not a shape
    #     this repo has; do not build for it. Iterating a snapshot of
    #     `linked` taken BEFORE this loop starts (rather than the live set)
    #     is what keeps this to one level: a name added to `linked` by
    #     following one sub-index is never itself visited by this same loop.
    for name in sorted(linked):
        if not name.startswith("INDEX_"):
            continue
        sub = memory_dir / f"{name}.md"
        if not sub.is_file():
            continue
        sub_text = sub.read_text(encoding="utf-8", errors="replace")
        linked |= set(re.findall(r"\]\(([A-Za-z0-9_\-]+)\.md\)", sub_text))
    dead = sorted(linked - files)
    if dead:
        out.append(Finding(
            "memory-index",
            f"{len(dead)} dead index link(s) - target file missing: {dead[:5]}",
        ))
    unindexed = sorted(
        f for f in (files - linked) if not f.startswith(exempt_prefixes)
    )
    if unindexed:
        out.append(Finding(
            "memory-index",
            f"{len(unindexed)} memory file(s) not in {MEMORY_INDEX}: "
            f"{unindexed[:6]}",
        ))
    return out


# ``/`` joins a version PAIR the way ``->`` joins a transition: a line reading
# "(ENGINE 1.273.0 / 1.274.0)" is citing the two revisions a change landed
# across, which is provenance. A LIVE anchor names exactly one version, so any
# line naming two in one breath cannot be asserting which one is in force.
# Added 2026-08-04 after the 1.275.0 bump flagged the G2-47 gated row, whose
# two flags genuinely shipped at 1.273.0 and 1.274.0 respectively.
VERSION_TRANSITION = re.compile(r"\d+\.\d+\.\d+\s*(?:->|to|/)\s*\d+\.\d+\.\d+")
CLOSURE_MARKER = re.compile(
    r"~~|\b(?:shipped|closed|fixed|refuted|done|reverted|superseded)\b", re.I
)
# A markdown ATX heading, capturing its depth so a section's scope can be
# closed by the next heading at the same or a shallower level.
HEADING = re.compile(r"^(#{1,6})\s")
# A heading that DATES ITSELF, e.g. "## 1b. STATUS as of 2026-08-11". The ISO
# date is required: a bare "as of" is too easy to write by accident, and this
# exemption covers a whole section rather than one line.
DATED_STATUS_HEADING = re.compile(r"\bas of\b\s*:?\s*\d{4}-\d{2}-\d{2}", re.I)


def _line_is_version_history(line: str) -> bool:
    """True when this LINE names a version as past, not as the one in force."""
    return bool(VERSION_TRANSITION.search(line) or CLOSURE_MARKER.search(line))


def check_version_anchors(
    root: pathlib.Path, old_version: str | None
) -> list[Finding]:
    """After a bump, no authored doc may still present the OLD version as live.

    Sweeps HTML as well as markdown - a ``*.md``-only grep is exactly how the
    ``docs/HEXCORE_offline.html`` anchor was missed on the 1.259.0 bump.
    Changelogs, ledgers and history files legitimately name old versions and are
    excluded by name.

    LINE-LEVEL CONTEXT, added 2026-07-26. Excluding historical FILES was not
    enough: history and live claims routinely share a doc. The 1.259.0 sweep
    reported three sites and ALL THREE were correct history - a release list
    reading ``- 1.259.0 -> 1.260.0 - ...``, the same
    transition inside an ``ORCHESTRATION_PLAN.md`` narrative row, and a ROADMAP
    fence recording that RM-91 CLOSED at ENGINE 1.258.0 + 1.259.0. A guard that
    cries wolf on every bump gets waved through on the bump where it is right,
    so the fix is a SMALLER check, not a looser one, and emphatically not a
    wider filename exclusion.

    Two markers make a line history, both past-tense by construction:
      * a release TRANSITION on the line (``N.N.N -> N.N.N``) - the version is
        being named as a step that was taken;
      * a CLOSURE keyword on the line (shipped / closed / fixed / refuted /
        done / reverted, or a struck-through ``~~`` entry) - the version is
        being named as the one some finished work landed at, which stays true
        forever.

    A third marker is BLOCK-scoped, added 2026-08-12 after the 1.277.0 bump
    reported ``docs/OVERLAY_COMPLIANCE_PLAN.md:35``. That line reads "in sync
    at engine 1.277.0, 533 files" - no transition, no closure keyword, so
    line-level context could not see it - but it sits under the heading
    ``## 1b. STATUS as of 2026-08-11``. It is a DATED SNAPSHOT: 1.277.0 was the
    live engine on that date, and rewriting it to the current version would
    make the record FALSE rather than fresh. So a heading that explicitly dates
    itself (``as of <YYYY-MM-DD>``) marks its own section historical.

    That exemption is deliberately the narrowest thing that works, because a
    block exemption is stronger than a line one:
      * it must be a HEADING line (``#``-prefixed), not any prose line;
      * the heading must carry an explicit ISO date, not a bare "as of";
      * scope ends at the next heading of the SAME OR HIGHER level, so a dated
        status section cannot silently shelter the rest of a document.
    Anything less specific re-opens the hole this check exists to close.

    KNOWN LIMIT: a line that asserts currency AND carries a closure keyword
    would be exempted. That shape has never occurred here, and the alternative -
    exempting the whole file - provably re-opens the hole this check exists to
    close. Findings name ``file:line`` so the adjudication is one glance.
    """
    if not old_version:
        return []
    hits: list[str] = []
    for p in _iter_docs(root):
        rel = p.relative_to(root).as_posix()
        if HISTORICAL.search(rel):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if old_version not in text:
            continue
        dated_depth: int | None = None
        for n, line in enumerate(text.splitlines(), start=1):
            head = HEADING.match(line)
            if head:
                depth = len(head.group(1))
                # Leaving the dated section: a heading at the same or a
                # shallower level ends its scope.
                if dated_depth is not None and depth <= dated_depth:
                    dated_depth = None
                if DATED_STATUS_HEADING.search(line):
                    dated_depth = depth
            if old_version not in line:
                continue
            if dated_depth is not None:
                continue
            if _line_is_version_history(line):
                continue
            hits.append(f"{rel}:{n}")
    if hits:
        return [Finding(
            "version-anchor",
            f"old version {old_version} still presented as live in {hits}",
        )]
    return []


_COUNT_WORDS = {
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "sixteen": 16, "eighteen": 18, "twenty": 20, "thirty": 30,
}


def check_counted_claims(root: pathlib.Path) -> list[Finding]:
    """A doc claiming "the N most recent" above a list of a different length."""
    out: list[Finding] = []
    for p in _iter_docs(root):
        if p.suffix != ".md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"[Tt]he (\w+) most recent", text)
        if not m:
            continue
        claimed = _COUNT_WORDS.get(m.group(1).lower())
        if claimed is None:
            continue
        actual = len(re.findall(r"^- \d+\.\d+\.\d+ ->", text[m.end():], re.M))
        if actual and actual != claimed:
            out.append(Finding(
                "count-claim",
                f"{p.relative_to(root).as_posix()} says '{m.group(1)} most "
                f"recent' but lists {actual}",
            ))
    return out


def check_untracked_authored(
    root: pathlib.Path, pairs: list[tuple[str, str]]
) -> list[Finding]:
    """Authored docs git is not tracking - the zero-version-control class.

    Checked in ONE ``git ls-files`` call rather than one per file; the per-file
    shape took long enough that it discouraged running the guard at all.
    """
    out: list[Finding] = []
    for a, _b in pairs:
        d = root / a
        if not d.is_dir():
            continue
        candidates = sorted(d.glob("*.md"))
        if not candidates:
            continue
        r = subprocess.run(
            ["git", "-C", str(root), "ls-files", f"{a}/"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            continue
        tracked = set(r.stdout.split())
        for f in candidates:
            rel = f.relative_to(root).as_posix()
            if rel not in tracked:
                out.append(Finding(
                    "untracked", f"{rel} is authored but NOT tracked by git"
                ))
    return out


def check_git_hooks_path(root: pathlib.Path) -> list[Finding]:
    """core.hooksPath must point at the TRACKED hooks directory.

    `.git/hooks/` is not version controlled. When core.hooksPath resolves there,
    the tracked hooks in `.githooks/` are inert and can drift indefinitely - which
    is exactly what happened before 2026-07-26: three tracked guards (py_compile,
    the ARCHITECTURE.md module map, the state_schema.js typedefs) had silently
    stopped running, and both generated artifacts had drifted. It also silently
    removes the banned-glyph gate from any headless
    `claude -p --permission-mode bypassPermissions` commit, which is how a banned
    em-dash reached a commit under test.
    """
    if not (root / ".githooks").is_dir():
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "config", "core.hooksPath"],
            capture_output=True, text=True,
        )
    except OSError:
        return []
    configured = out.stdout.strip()
    if configured.replace("\\", "/").rstrip("/").endswith(".githooks"):
        return []
    return [Finding(
        "git-hooks-path",
        f"core.hooksPath is {configured or '(unset)'}, not .githooks - the TRACKED "
        "hooks are inert. Run: python scripts/install_hooks.py",
    )]


def check_orphaned_git_hooks(root: pathlib.Path) -> list[Finding]:
    """A hook in .git/hooks with no counterpart in .githooks is now INERT.

    Flipping core.hooksPath to the tracked directory silently disables every
    hook that lives ONLY in the untracked one. Measured 2026-07-26: the flip
    orphaned `post-checkout`, `pre-push` (both Git LFS, and this repo has
    LFS-tracked files, so LFS checkout and LFS UPLOAD both break) and
    `post-commit`. Nothing reports it - git simply stops consulting them, pushes
    still look clean, and LFS content quietly never reaches the remote.

    Reported as a breach rather than a note because the failure is silent in
    exactly the direction that loses data.
    """
    tracked = root / ".githooks"
    untracked = root / ".git" / "hooks"
    if not (tracked.is_dir() and untracked.is_dir()):
        return []
    have = {p.name for p in tracked.iterdir() if p.is_file()}
    orphans = sorted(
        p.name for p in untracked.iterdir()
        if p.is_file() and not p.name.endswith(".sample") and p.name not in have
    )
    if not orphans:
        return []
    return [Finding(
        "orphaned-hook",
        f"{orphans} exist in .git/hooks but NOT in .githooks - core.hooksPath "
        "points at .githooks, so these are INERT. Port them or delete them.",
    )]


def run_all(
    root: pathlib.Path = ROOT, old_version: str | None = None
) -> list[Finding]:
    """Every check, in the order a reader would want them reported."""
    findings: list[Finding] = []
    findings += check_doc_budgets(root, DOC_BUDGETS)
    findings += check_mirror_parity(root, MIRROR_PAIRS)
    findings += check_memory_index(MEMORY_DIR, MEMORY_UNINDEXED_OK)
    findings += check_version_anchors(root, old_version)
    findings += check_counted_claims(root)
    findings += check_untracked_authored(root, MIRROR_PAIRS)
    findings += check_git_hooks_path(root)
    findings += check_orphaned_git_hooks(root)
    return findings


def main(argv: list[str]) -> int:
    old_version = argv[1] if len(argv) > 1 else None
    findings = run_all(ROOT, old_version)
    for f in findings:
        print(f"  BREACH [{f.kind}] {f.message}")
    if not findings:
        print("  clean - no drift detected")
    print(f"drift_guard: {len(findings)} breach(es)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
