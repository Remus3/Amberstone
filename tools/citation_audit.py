"""Repo-wide `path:<N>` citation audit for the living docs (RM-171).

WHY THIS EXISTS
---------------
This repo's whole don't-redo discipline rests on being able to follow a
`path.py:<N>` citation to the thing its prose claims lives there. RM-171 was
filed after a measurement on ONE file: of the 8 places citing
`core/build_order_precompute.py:<N>`, only 2 pointed at what their text
claimed, and that was BEFORE the file was edited. Separately one reader
citation moved `:569` -> `:684` -> `:722` across two commits in a single
session. Line numbers rot silently: nothing in the toolchain reads them.

There is precedent (LEDGER 994, 2026-07-21): a verifier swept all 280
citations inside one package to 0 file-not-found / 0 past-EOF. That pass was
MANUAL and scoped to one directory. This module generalizes the same technique
to the living docs and makes it machine-checkable, so the count cannot silently
grow. It is the ONLY citation checker in the repo - extend it, do not write a
second one.

THREE CLASSES, AND WHY THE THIRD IS THE POINT
---------------------------------------------
* ``FILE_MISSING`` - the cited path does not resolve to a tracked file.
* ``PAST_EOF``     - the file exists but the line number is beyond its end.
* ``RESOLVES``     - the line exists.

RESOLVES IS NOT THE SAME AS CORRECT. A line number that exists but points at
unrelated code is exactly the failure that cost this repo a session, and it is
invisible to a file-exists + line-count check. So every RESOLVES citation is
further graded by asking whether the SYMBOL the surrounding prose names is
actually at or near the cited line:

* ``CONFIRMED``  - a claim token from the prose appears in the cited window.
* ``MOVED``      - no claim token in the window, but one occurs elsewhere in
                   the same file. Mechanically re-pointable.
* ``ABSENT``     - no claim token anywhere in the file. NOT auto-fixable; the
                   symbol may have been renamed, deleted, or the prose may
                   name something that was never a literal in the file.
* ``UNCHECKED``  - the prose offered no usable claim token. Silent, by design:
                   a guess here would be worse than an honest abstention.

HONEST MATCHER LIMITATIONS (read before quoting any number as exact)
--------------------------------------------------------------------
The claim matcher is a HEURISTIC over prose, not a parser. Its known error
modes, in both directions:

FALSE ``CONFIRMED`` (matcher says fine, citation may still be wrong):
  1. Substring matching. A claim token ``score`` matches ``score_by``,
     ``_scorer``, and the word ``score`` in a comment. Short and generic
     tokens are the main source of this, which is why ``_MIN_TOKEN_LEN``
     exists - it does not eliminate the class.
  2. The +/- ``_WINDOW`` line tolerance means a citation can be off by a few
     lines and still confirm. That is deliberate: an exact-line rule would
     flag every citation that survived a one-line insertion above it, which is
     drift the reader does not care about.
  3. A token that happens to appear in an unrelated nearby line confirms.

FALSE ``MOVED`` / ``ABSENT`` (matcher says wrong, citation is actually fine):
  4. Prose that describes a line WITHOUT naming any literal from it - "the
     guard at foo.py:120 is the backstop" - yields tokens that were never
     going to be in the file. These land in ABSENT and are listed for a human,
     never auto-fixed.
  5. Prose naming a CONCEPT rather than an identifier ("the retry loop at
     x.py:44") lands in ABSENT for the same reason.
  6. A citation whose named symbol legitimately appears many times in the file
     (a common method name) is reported MOVED with many candidates and is left
     for a human, because re-pointing it would be a guess.

  7. TOKEN BLEED, the dominant residual error and the one worth knowing about.
     Claims are attributed by PROXIMITY, not by parsing, so a doc line naming
     several files and several symbols hands every symbol to every citation on
     it. Two fences bound this - ``_starts_block`` stops the window crossing
     into a sibling bullet, and ``_COL_WINDOW`` bounds it within the line -
     but neither can separate two clauses of one bullet. MEASURED on the run
     that shipped this module: of 671 MOVED+ABSENT rows, 231 (34.4 percent)
     sit on a doc line carrying more than one citation and are therefore the
     MOST bleed-exposed.

     Do NOT read the remaining 440 sole-citation rows as clean. An
     independent adversarial sample put their true-positive rate at 14 of 18,
     about 78 percent, so roughly one in four or five is still a false
     positive - bleed happens WITHIN a clause too, not only across citations
     (one plan line carrying "do-not-flip-blind" was graded wrong because
     `callouts` bled from the same clause). Sole-citation rows are a
     majority-real, better-odds subset; they are not a verified list. Every
     MOVED/ABSENT row is a HINT to check by hand.

  8. RESOLUTION LENIENCY, and it is bigger than the mirror de-dup above.
     Only 1084 of the 2050 guarded citations resolve by EXACT tracked path;
     948 (46.2 percent) resolve by basename/suffix match. So a bare
     `foo.py:42`
     is checked against whatever single tracked `foo.py` happens to exist,
     which may not be the `foo.py` the author meant - and it then reads
     GREEN. This is why `_Index.candidates` returns a SET and a citation is
     only broken when NO candidate can host the line: the conservative
     reading. The cost of that conservatism is exactly this false-green
     class. Prefer writing repo-root-relative paths in new prose.

  9. FORMAT EVASION. The regex covers this repo's own convention
     (`path:<N>` / `path:<N>-<M>`) and nothing else. `foo.py#L42`,
     `foo.py line 42` and `foo.py :42` with a space are all invisible to it,
     as are targets whose extension is absent from ``_EXTS`` - `.xml`,
     `.svg`, `.vbs` and `.log` files all exist in the tree today. Nothing in
     the repo currently uses those forms, so this is a hole a FUTURE author
     can fall into rather than one already being exploited; a citation
     written that way is simply never checked and never counted.

Because of 4-9, ``MOVED`` and ``ABSENT`` counts are UPPER bounds on real rot,
and ``CONFIRMED`` is an upper bound on real correctness. Neither number is
exact. The only figures here that are exact are FILE_MISSING and PAST_EOF -
those are pure filesystem facts, and they are the only ones the guard
(``tests/test_citation_drift_guard_rm171.py``) is allowed to budget.

Tightening these fences moves counts toward ``UNCHECKED``, which is the
honest direction. MEASURED on the 1918-citation scope as it stood before
`docs/qa/`, `docs/handoff/` and `WAKEUP_NOTES.md` joined the budget: the first
cut of this matcher reported 545 MOVED / 524 CONFIRMED, and after both fences
landed the same corpus read 503 / 425 with 816 UNCHECKED. The extra
abstentions were over-claims, not lost findings. (Today's larger scope reads
525 / 435 / 907; the before-and-after pair above is quoted on the identical
corpus so the comparison stays like-for-like.)

SCOPE - THREE GROUPS, NOT TWO
------------------------------
``scope_of`` returns GUARDED, HISTORY or UNGUARDED, and the distinction
matters because collapsing it hid real breakage once already:

* GUARDED   - the living docs, budgeted by the guard. 2050 citations.
* HISTORY   - append-only by policy (``docs/_archive/**``, ``docs/LEDGER.md``,
              ``docs/history_notes.md``, the ROADMAP/ORCHESTRATION history
              files) PLUS the dated measurement artifacts ``docs/_rescore/**``
              and ``docs/_scratch_*.md``. A stale citation here is CORRECT - it
              records what was true when written, or it is a rot example the
              artifact exists to QUOTE - and editing it is a history rewrite
              (``feedback_no_history_rewrite``). Report-only, never budgeted.
* UNGUARDED - everything else: ``ops/**``, ``agents/**``, ``tools/*.md``.
              882 citations carrying 22 broken, including
              16 in ``ops/audit/P2_FINDINGS.md`` and one in
              ``ops/loop/director_prompt.md``, which is LIVE LOOP INPUT.
              These are NOT history and were never decided to be acceptable;
              they are simply not budgeted yet. ``main()`` prints them on
              every run so they cannot pass as history by omission.

Do not confuse a `file:line` citation with a COMMIT-HASH citation. The repo
already accepts that ~34 percent of pre-2026-07 8-hex commit citations are
unresolvable and that this is EXPECTED, not rot (CLAUDE.md Settled). This
module does not look at commit hashes at all.

USAGE
-----
    python tools/citation_audit.py            # census over the guarded scope
    python tools/citation_audit.py --all      # include immutable history
    python tools/citation_audit.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Extensions a citation target may carry. Deliberately explicit: an open-ended
# `\w+` suffix would swallow `127.0.0.1:8888`, `1.235.0:` prose, and clock
# times. Every entry here is a file type the repo actually cites.
_EXTS = (
    "py|js|mjs|cjs|ts|css|md|json|jsonl|html|ps1|psm1|yml|yaml|txt|bat|cmd"
    "|sh|ahk|toml|ini|cfg|sql|lock"
)

CITATION_RE = re.compile(
    # Left fence: not preceded by another path character, so `a/b.py:1` yields
    # one hit on the full path rather than also matching the bare `b.py:1`.
    r"(?<![\w/\\.-])"
    r"((?:[\w.-]+[/\\])*[\w.-]+\.(?:" + _EXTS + r"))"
    r":(\d+)(?:\s*-\s*(\d+))?"
    r"(?![\d\w])"
)

# Backticked spans are where this repo puts identifiers. Prose outside them is
# too noisy to mine without manufacturing false MOVED/ABSENT rows.
_BACKTICK_RE = re.compile(r"`([^`\n]{1,200})`")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# Below this length a token matches almost anything by substring. Raising it
# trades recall for precision; 6 was picked by inspecting the FP tail.
_MIN_TOKEN_LEN = 6

# Line tolerance around the cited line/range. See limitation 2 above.
_WINDOW = 3

# Character radius around a citation on its own line. Bounds intra-line
# token bleed on the dense one-bullet-many-files rows.
_COL_WINDOW = 160

# Tokens that are English, not code. A prose word inside backticks (this repo
# backticks emphasis as well as identifiers) would otherwise create noise in
# both directions.
_STOPWORDS = frozenset(
    """
    always append assert because before between change changed checked
    citation citations comment commit committed config constant contract
    correct current default defined definition delete deleted directory
    docstring during either engine except exists expected failure feature
    function guarded handler header import include instead itself library
    literal machine measured method missing module nothing number object
    operator package parallel parameter pattern present private problem
    process produce project property provide reader really record reference
    registry release removed rename renamed replace report require result
    return returns sample schema scoped script search section server session
    setting should signal single source status string structure subject
    support symbol system target test tests through timeout tracked
    trailing update updated usage useful value values verify version
    warning window without worker written
    """.split()
)

# THREE SCOPES, NOT TWO. An earlier cut of this module had only "in scope" and
# its negation, and presented the negation as "immutable history". That was
# misleading in a way that HID REAL BREAKAGE: 882 citations in `ops/**`,
# `agents/**` and `tools/*.md` are neither guarded nor
# append-only, and they carry 22 broken - 16 in `ops/audit/P2_FINDINGS.md` and
# one in `ops/loop/director_prompt.md`, which is LIVE LOOP INPUT. Reading
# "not guarded" as "history" would have retired those without anyone deciding
# to. Append-only-by-policy and not-yet-guarded are different facts and are
# now named separately.
GUARDED = "GUARDED"  # budgeted by tests/test_citation_drift_guard_rm171.py
HISTORY = "HISTORY"  # append-only by policy; a stale cite here is CORRECT
UNGUARDED = "UNGUARDED"  # neither - reported, not yet budgeted

# Append-only by policy. A stale citation in one of these records what was
# true when it was written; editing it is a history rewrite
# (`feedback_no_history_rewrite`).
#
# DATED MEASUREMENT ARTIFACTS belong to the same class and are listed here for
# the same reason, added 2026-09-12. `docs/_rescore/**` and `docs/_scratch_*.md`
# are single-run working files: a probe report, an adversarial cost arm, a
# per-chunk re-score. They are reports ABOUT citation rot, so they QUOTE broken
# citations as their SUBJECT MATTER, and two of those quotes
# (`core/NOSUCHFILE_zzz.py:12`, `core/polled_json.py:999999`) are FABRICATED
# NEEDLES - positive controls a false-positive measurement invented to prove
# its own detector fires. Baselining a fabricated needle would make the budget
# a record of fiction, and "repairing" a quoted rot example would destroy the
# measurement it documents. So the rule is a PREFIX CLASS, never a filename
# list: anything under the rescore working directory, and anything written to
# the `_scratch_` convention, is a dated artifact by construction.
#
# DELIBERATELY NARROW. This does NOT cover every `docs/_` name. A dated
# CONSOLIDATED evidence file (`docs/REFUTATION_GATE_BACKTEST_2026-09-12.md`) is
# a LIVING doc that supersedes its own scratch inputs, and the correspondence
# and refill files (`docs/_outbound_*`, `docs/_draft_*`,
# `docs/_research_refill_*`) carry zero broken citations and stay budgeted. A
# blanket `docs/_` rule would have bought nothing and surrendered coverage.
_HISTORY_PREFIXES = (
    "docs/_archive/",
    "docs/_rescore/",
    "docs/_scratch_",
)
_HISTORY_FILES = frozenset(
    {
        "docs/LEDGER.md",
        "docs/history_notes.md",
        "docs/ROADMAP_HISTORY.md",
        "docs/ORCHESTRATION_PLAN_HISTORY.md",
        "docs/ORCHESTRATION_FINDINGS_ARCHIVE.md",
        "docs/ORCHESTRATION_FINDINGS_R145_PRECISION.md",
    }
)

# The guarded surface: the docs a reader is expected to navigate FROM.
#
# `WAKEUP_NOTES.md` (3 citations / 0 broken) is guarded despite its churn: it
# is explicitly a LIVING doc that gets PRUNED to the last 2-3 sessions with the
# older half relocated to docs/history_notes.md, so it is not append-only.
# `docs/handoff/` (4 / 0) is guarded because it cost nothing to budget.
# `docs/qa/` (125 / 3) is guarded by DECISION rather than by exclusion: the
# three breaks are all `ops/runtime/ui_recon/recon.py:40`, a gitignored runtime
# path that was never tracked, so budgeting the tree costs three documented
# baseline entries and buys coverage of 122 live citations. A blanket
# exclusion would have been cheaper to write and strictly worse.
_SCOPE_FILES = frozenset(
    {"CLAUDE.md", "ROADMAP.md", "BACKLOG.md", "README.md", "WAKEUP_NOTES.md"}
)
_SCOPE_PREFIXES = ("docs/",)


def scope_of(relpath: str) -> str:
    """Classify a doc as GUARDED, HISTORY or UNGUARDED. Never two-valued."""
    relpath = relpath.replace("\\", "/")
    if relpath in _HISTORY_FILES:
        return HISTORY
    if any(relpath.startswith(p) for p in _HISTORY_PREFIXES):
        return HISTORY
    if relpath in _SCOPE_FILES:
        return GUARDED
    if any(relpath.startswith(p) for p in _SCOPE_PREFIXES):
        return GUARDED
    return UNGUARDED


def in_scope(relpath: str) -> bool:
    """True when `relpath` is a living doc whose citations the guard budgets."""
    return scope_of(relpath) == GUARDED


def tracked_files(root: Path) -> list[str]:
    """Every tracked path, via the git INDEX.

    Never a filesystem walk: an untracked scratch file, a build artifact, or a
    parallel agent's temp notes must not be able to change this census.
    """
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


@dataclass
class Citation:
    doc: str
    doc_line: int
    raw: str
    path: str
    start: int
    end: int
    col: int = 0
    resolved: str | None = None
    status: str = ""
    detail: str = ""
    claim_tokens: list[str] = field(default_factory=list)
    found_lines: list[int] = field(default_factory=list)
    ambiguous: int = 0

    @property
    def scope(self) -> str:
        """GUARDED / HISTORY / UNGUARDED. Deliberately not a boolean: see the
        three-scope note above for the breakage a two-valued split hid."""
        return scope_of(self.doc)


def extract_citations(text: str, doc: str) -> list[Citation]:
    """All `path:<N>` / `path:<N>-<M>` tokens in one document."""
    found: list[Citation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for m in CITATION_RE.finditer(line):
            path, a, b = m.group(1), int(m.group(2)), m.group(3)
            found.append(
                Citation(
                    doc=doc,
                    doc_line=lineno,
                    raw=m.group(0),
                    path=path.replace("\\", "/"),
                    start=a,
                    end=int(b) if b else a,
                    col=m.start(),
                )
            )
    return found


class _Index:
    """Tracked-path lookup: exact first, then basename/suffix match.

    One correction, measured on the first census run of this tool and worth
    stating because a naive index reports it as rot: genuine multi-candidate
    names survive (``server.py`` is in ``agents/daemon_slayer/``, ``dashboard/``
    and ``mc/``; ``main.js`` is in ``rc-shell/src/`` and ``web/js/``). Those are
    NOT failures. A citation is broken only when NO tracked candidate can host
    the cited line, so ``candidates()`` returns the whole set and the caller
    picks.
    """

    def __init__(self, paths: list[str]) -> None:
        self.exact = {p.replace("\\", "/") for p in paths}
        self.by_suffix: dict[str, list[str]] = {}
        for p in sorted(self.exact):
            parts = p.split("/")
            for i in range(len(parts)):
                self.by_suffix.setdefault("/".join(parts[i:]), []).append(p)

    def candidates(self, cited: str) -> list[str]:
        if cited in self.exact:
            return [cited]
        return self.by_suffix.get(cited, [])


# A line opening its own block: a list item, heading, table row, blockquote or
# numbered step. Text on such a line belongs to a DIFFERENT claim than the line
# above it, so the claim window must not cross it.
_BLOCK_START_RE = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|\||>|```)")


def _starts_block(line: str) -> bool:
    return bool(_BLOCK_START_RE.match(line))


def _claim_tokens(doc_lines: list[str], cite: Citation) -> list[str]:
    """Identifier-shaped tokens the prose around a citation names.

    Only backticked spans are mined - see limitation 4 in the module docstring
    for why prose words are not. The citation's own path is excluded so a doc
    never confirms itself.

    CONTEXT IS THE CITATION'S OWN LINE, plus the previous line ONLY when that
    line is a wrapped continuation rather than a sibling block. Measured on the
    first run of this tool: a naive two-line window turned BACKLOG.md - a dense
    one-line-per-bullet list - into a token-bleed machine. `hotkey_listener.py`
    was graded MOVED against tokens (`loop_controller`, `CODE_FILES`) that came
    from a completely unrelated neighbouring bullet. Every such row is a pure
    false positive, so the window is fenced on the block starters below.
    """
    cur = cite.doc_line - 1  # 0-indexed line the citation sits on
    # Intra-line fence. A single BACKLOG/ROADMAP bullet routinely names six
    # files and a dozen symbols on ONE line; without this, every citation on
    # that line inherits every symbol on it. Measured: `tools/hotkey_listener.py`
    # graded MOVED against `loop_controller` / `CODE_FILES` from a different
    # clause of the same bullet. Only backticked spans within _COL_WINDOW
    # characters of the citation count as ITS claim.
    own = doc_lines[cur]
    lo_c = max(0, cite.col - _COL_WINDOW)
    hi_c = min(len(own), cite.col + len(cite.raw) + _COL_WINDOW)
    lines = [own[lo_c:hi_c]]
    # Reach BACK only if the citation's own line is a continuation of the one
    # above it. If the citation's line opens its own block, the line above is
    # a sibling claim, not context.
    if cur - 1 >= 0 and not _starts_block(doc_lines[cur]):
        lines.insert(0, doc_lines[cur - 1])
    # Reach FORWARD only onto a line that is itself a continuation.
    if cur + 1 < len(doc_lines) and not _starts_block(doc_lines[cur + 1]):
        lines.append(doc_lines[cur + 1])
    context = " ".join(lines)
    toks: list[str] = []
    for span in _BACKTICK_RE.findall(context):
        if CITATION_RE.search(span):
            continue
        for ident in _IDENT_RE.findall(span):
            if len(ident) < _MIN_TOKEN_LEN:
                continue
            if ident.lower() in _STOPWORDS:
                continue
            # A bare module/file basename is a path fragment, not a claim
            # about the cited LINE.
            if ident in {Path(cite.path).stem, Path(cite.path).name}:
                continue
            toks.append(ident)
    # Stable order, de-duplicated.
    return list(dict.fromkeys(toks))


def _grade_resolving(cite: Citation, src_lines: list[str]) -> None:
    """Split a RESOLVES citation into CONFIRMED / MOVED / ABSENT / UNCHECKED."""
    if not cite.claim_tokens:
        cite.detail = "UNCHECKED"
        return
    lo = max(1, cite.start - _WINDOW)
    hi = min(len(src_lines), cite.end + _WINDOW)
    window = "\n".join(src_lines[lo - 1 : hi])
    if any(t in window for t in cite.claim_tokens):
        cite.detail = "CONFIRMED"
        return
    hits: list[int] = []
    for i, line in enumerate(src_lines, start=1):
        if any(t in line for t in cite.claim_tokens):
            hits.append(i)
    if hits:
        cite.detail = "MOVED"
        cite.found_lines = hits
    else:
        cite.detail = "ABSENT"


def audit(root: Path | None = None, include_immutable: bool = False) -> list[Citation]:
    """Census every citation in the living docs. Pure read; never writes."""
    root = root or REPO_ROOT
    paths = tracked_files(root)
    index = _Index(paths)
    docs = [p for p in paths if p.endswith(".md")]
    results: list[Citation] = []
    src_cache: dict[str, list[str]] = {}

    for doc in docs:
        rel = doc.replace("\\", "/")
        if not include_immutable and not in_scope(rel):
            continue
        try:
            text = (root / doc).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        doc_lines = text.splitlines()
        for cite in extract_citations(text, rel):
            cands = index.candidates(cite.path)
            if not cands:
                cite.status = "FILE_MISSING"
                cite.detail = "no tracked file"
                results.append(cite)
                continue

            def _lines(target: str) -> list[str]:
                if target not in src_cache:
                    try:
                        src_cache[target] = (
                            (root / target)
                            .read_text(encoding="utf-8", errors="replace")
                            .splitlines()
                        )
                    except OSError:
                        src_cache[target] = []
                return src_cache[target]

            cite.claim_tokens = _claim_tokens(doc_lines, cite)
            # Only candidates long enough to host the cited line can be the
            # referent. If none is, the citation is PAST_EOF against every
            # reading of it, which is a fact and not a heuristic.
            hosting = [c for c in cands if cite.end <= len(_lines(c))]
            if not hosting:
                longest = max(cands, key=lambda c: len(_lines(c)))
                cite.resolved = longest
                cite.status = "PAST_EOF"
                cite.detail = f"longest candidate {longest} has {len(_lines(longest))} lines"
                results.append(cite)
                continue

            # Among hosting candidates prefer the one whose window actually
            # carries a claim token; that is the reading most favourable to
            # the doc, which is the conservative choice for a guard.
            graded: list[tuple[int, str]] = []
            order = {"CONFIRMED": 0, "MOVED": 1, "UNCHECKED": 2, "ABSENT": 3}
            for c in hosting:
                probe = Citation(
                    doc=cite.doc,
                    doc_line=cite.doc_line,
                    raw=cite.raw,
                    path=cite.path,
                    start=cite.start,
                    end=cite.end,
                    col=cite.col,
                    claim_tokens=cite.claim_tokens,
                )
                _grade_resolving(probe, _lines(c))
                graded.append((order[probe.detail], c))
            graded.sort()
            best = graded[0][1]
            cite.resolved = best
            cite.status = "RESOLVES"
            _grade_resolving(cite, _lines(best))
            if len(cands) > 1:
                cite.ambiguous = len(cands)
            results.append(cite)
    return results


def summarize(rows: list[Citation]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
        if r.status == "RESOLVES":
            key = f"RESOLVES/{r.detail}"
            counts[key] = counts.get(key, 0) + 1
    counts["TOTAL"] = len(rows)
    return counts


def broken(rows: list[Citation]) -> list[Citation]:
    """The guard budget: hard filesystem failures only.

    MOVED/ABSENT are heuristic and are NOT part of the budget - a guard built
    on a heuristic would go red on a prose reword and get disabled.
    """
    return [r for r in rows if r.status in ("FILE_MISSING", "PAST_EOF")]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="include immutable history")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--detail", default="", help="print only this RESOLVES grade")
    args = ap.parse_args(argv)

    rows = audit(include_immutable=args.all)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "doc": r.doc,
                        "doc_line": r.doc_line,
                        "raw": r.raw,
                        "path": r.path,
                        "resolved": r.resolved,
                        "start": r.start,
                        "end": r.end,
                        "status": r.status,
                        "detail": r.detail,
                        "claim_tokens": r.claim_tokens,
                        "found_lines": r.found_lines[:20],
                        "scope": r.scope,
                    }
                    for r in rows
                ],
                indent=1,
            )
        )
        return 0

    counts = summarize(rows)
    print("citation census (scope: living docs%s)" % (" + history" if args.all else ""))
    for k in sorted(counts):
        print(f"  {k:24s} {counts[k]}")

    # Always report the UNGUARDED tree, even on a default (guarded-only) run.
    # It is the group most likely to be misread as history, so it does not get
    # to hide behind a flag.
    all_rows = rows if args.all else audit(include_immutable=True)
    by_scope: dict[str, list[Citation]] = {GUARDED: [], HISTORY: [], UNGUARDED: []}
    for r in all_rows:
        by_scope[r.scope].append(r)
    print("\nby scope (whole repo):")
    for s in (GUARDED, HISTORY, UNGUARDED):
        n_bad = len(broken(by_scope[s]))
        print(f"  {s:10s} {len(by_scope[s]):5d} citations  {n_bad:4d} broken")
    print(
        "  HISTORY is append-only by policy - a stale cite there is CORRECT.\n"
        "  UNGUARDED is NOT history: it is simply not budgeted yet."
    )
    ung = broken(by_scope[UNGUARDED])
    if ung:
        print(f"\n-- UNGUARDED broken ({len(ung)}), not budgeted --")
        for r in ung:
            print(f"  {r.doc}:{r.doc_line}  {r.raw}  {r.status}")
    if args.detail:
        print(f"\n-- RESOLVES/{args.detail} --")
        for r in rows:
            if r.status == "RESOLVES" and r.detail == args.detail:
                print(
                    f"  {r.doc}:{r.doc_line}  {r.raw}  tokens={r.claim_tokens[:4]}"
                    f"  found={r.found_lines[:6]}"
                )
    bad = broken(rows)
    if bad:
        print(f"\n-- BROKEN ({len(bad)}) --")
        for r in bad:
            print(f"  {r.doc}:{r.doc_line}  {r.raw}  {r.status}  ({r.detail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
