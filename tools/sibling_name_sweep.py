#!/usr/bin/env python3
"""RM-399 - RC's sibling-name sweep. The second half of an already-adopted gate.

WHAT THIS IS
------------
A pre-push gate that refuses to publish bytes which identify a SIBLING project.
This repository is PUBLIC. ``ops/moon_sync_repos.json`` is gitignored per-host
CONFIG and is the only artifact that resolves a counterparty CODE to a real
project name and a real checkout path. A sibling-identifying byte reaching the
remote is IRREVERSIBLE publication - a force-push does not reach
``refs/pull/N/head``, and a delete-and-recreate is the only known remedy.

THE CENTRAL DESIGN CONSTRAINT: THIS FILE MUST NOT CONTAIN WHAT IT GUARDS
-----------------------------------------------------------------------
Every needle is loaded at RUN TIME from the gitignored config. No sibling
literal appears in this file, in its test, or in anything either of them print.
That is also why the reporter prints a SLOT NUMBER and never the matched text:
hook stderr lands in CI logs and in pasted transcripts, so a report that spells
the name simply relocates the leak. ``--explain N`` resolves one finding to its
literal, on the operator's own machine, on demand.

WHAT IT DOES NOT CLAIM
----------------------
A sweep is a BETTER SHAPE, not a solved problem. The prior art in the sibling
tree records four shapes that escaped its own one-off sweep, and it ships a
documented bypass. The honest claim after this lands is "the sweep half is armed
with a measured escape rate above zero", never "sibling names cannot leak".
``--no-verify`` bypasses the whole hook and nothing here can prevent that.
RM-688: every sweep run appends one redacted JSONL run record, so a pushed range
with NO record is the after-the-fact signal of a skipped gate - not a real-time one.

TWO ARMS, AND WHY THERE ARE TWO
-------------------------------
1. The NEEDLE arm matches loaded names. It is the precise arm, and it is inert
   without the per-host config - which a fresh clone and CI both lack.
2. The STRUCTURAL arm is config-free: it extracts drive-rooted first path
   segments and subtracts an allowlist. It therefore still catches "a Windows
   path to a project nobody recognises" in a fresh clone. It runs in DEGRADED
   mode too, which is the whole reason DEGRADED is not silent. When ARMED it is
   handed the loaded slot names, and a segment starting with one is never
   subtracted, so a slot whose basename an allowlist placeholder matches keeps
   both arms. DEGRADED has no names: there, such a sibling is invisible to this
   arm - a declared residual.

THREE MODES
-----------
ARMED     - config parsed, needles loaded, both arms run.
DEGRADED  - no override AND no config file. The needle arm proves NOTHING and
            says so on EVERY push. The structural arm still runs.
FAULT     - config present but unparseable, a key this sweep reads that is
            malformed or mis-spelled (RM-799), zero usable paths, a failed git
            invocation, or zero bytes scanned against a non-empty diff. Exit 3.
            FAULT is never collapsed into HALT: "the gate fired" and "the gate
            could not run" are different facts and must stay different.

WHY THREE SOURCES ARE SCANNED
-----------------------------
A content diff alone misses two publication routes that were both measured here:
a RENAME publishes a new path with no content change, and a name in a COMMIT
SUBJECT is published permanently while appearing in no diff at all.

PER-SLOT NARROWING, FOR A PARTICIPANT WHOSE BASENAME IS AN ORDINARY WORD
------------------------------------------------------------------------
The needle arm matches a name in three shapes: a drive-rooted PATH, a github
URL, and the BARE spelling anywhere in prose. The bare arm is the right default
because a sibling checkout is normally named with a coined word that has no
business appearing in RC's own source at all.

It is the wrong arm for a participant whose basename is a dictionary word. Such
a word occurs freely in RC's own charters, schedulers and roadmap prose, none of
which identifies anybody, and a gate that halts on hundreds of those is a gate
that gets switched off within a day. Measured when the fifth slot was armed: 339
findings, every one of them RC's own prose.

The remedy is narrow and it is DECLARED:

* The declaration lives in the gitignored per-host config under
  ``narrowed_names`` - a list of checkout BASENAMES - or, on the env path, in
  ``RC_MOON_SYNC_NARROWED_NAMES`` (``RC_MOON_SYNC_REPOS`` carries paths only and
  cannot express it). A real name therefore never enters a tracked file.
* NOTHING is inferred. There is no heuristic here that asks whether a name
  "looks like" a dictionary word, because such a heuristic would silently
  weaken a slot nobody chose to weaken.
* A narrowed slot loses the BARE arm in BOTH views and KEEPS the DRIVE and URL
  arms in both. The path-shaped and repo-adjacent forms are the ones that
  actually identify a counterparty; they stay armed, and
  ``assert_non_vacuous`` refuses a needle that has lost either of them.
* The default is UNCHANGED full strength. A slot with no declaration, and a
  config with no key at all, keep every arm they have today. A declaration that
  matches no slot narrows nothing, so a typo fails CLOSED.
* It is NOT SILENT. Every surface that prints the ARMED line prints the
  narrowed COUNT with it, and says in capitals what a narrowed slot gave up. A
  weakened guard that does not announce itself is the failure mode this whole
  file exists to avoid.

This is a REDUCTION IN COVERAGE, stated plainly: a bare mention of a narrowed
participant's name, in prose, with no path and no URL around it, will not halt a
push. That form was judged not to identify a counterparty on its own. The forms
that do are all still armed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, NoReturn, Optional, Sequence

EXIT_CLEAN = 0
EXIT_USAGE = 1
EXIT_HALT = 2
EXIT_FAULT = 3

MODE_ARMED = "ARMED"
MODE_DEGRADED = "DEGRADED"
MODE_FAULT = "FAULT"

SEV_NAME = "NAME"
SEV_RESOLUTION = "RESOLUTION"
SEV_STRUCTURAL = "STRUCTURAL"

SHAPE_DRIVE = "S1S2_DRIVE"
SHAPE_BARE = "S3_BARE"
SHAPE_URL = "S7_URL"
SHAPE_STRUCTURAL = "STRUCT_DRIVE_ROOT"

VIEW_SPACE = "space"
VIEW_TIGHT = "tight"

# S4 spellings. SPACED is the plain name; the rest are the ways a name survives
# a filename, a URL slug, a query string or a python identifier.
VARIANT_FAMILIES = ("SPACED", "HYPHEN", "UNDER", "CONCAT", "PCT20")

# S8 window: how close a counterparty CODE must sit to a name hit before the
# pair is treated as PUBLISHING THE RESOLUTION rather than merely a name.
CODE_WINDOW = 80

# RM-477. How much of a blob is normalised at a time, and how much REAL context
# every window carries on each side of the region it is allowed to report from.
#
# The normalisation in `build_views` costs roughly 76x the blob's byte count at
# peak (measured on Legion 2026-09-20: 5,732,641 characters -> 434 MB), because
# it materialises one 1-char `str` and one distinct `int` PER CHARACTER, three
# times over. That is survivable for a diff hunk and fatal for a tree walk, and
# the tree walk is the arm that produced RC's five measured escapes.
#
# The cure is windowing, NEVER exclusion: a size cap that skips a file would
# blind the audit to precisely the files most likely to QUOTE a counterparty.
# CHUNK_GUARD is the overlap, and it is the only thing standing between a
# chunked scan and a silently weaker gate - see `_scan_windows`.
CHUNK_STEP = 1 << 20
CHUNK_GUARD = 1 << 15


class ChunkGuardExceeded(RuntimeError):
    """A single match spanned more ORIGINAL characters than CHUNK_GUARD.

    Raised rather than swallowed. A match wider than the overlap can fall
    between two windows, and a gate that quietly stops seeing a shape is the
    exact failure this whole tool exists to prevent - so the residual risk of
    the overlap is made LOUD and fail-closed instead of being hidden behind a
    comment claiming it cannot happen. It can: the URL shape's owner segment
    (`[A-Za-z0-9_.\\-]+`) is unbounded, so no static bound on match width
    exists. CHUNK_GUARD is sized so that reaching this is pathological.
    """


# U+FFFD, written as an escape on purpose: this file is 7-bit ASCII by repo rule.
_REPLACEMENT = chr(0xFFFD)

BYPASS_ENV = "RC_SIBLING_SWEEP_BYPASS"
BYPASS_LOG = Path("ops") / "runtime" / "sibling_sweep_bypass.log"
# RM-788: a non-empty value replaces REPO_ROOT / BYPASS_LOG (the test suite sets
# it per test, so a bypass run in a child process leaves the live log alone).
BYPASS_LOG_ENV = "RC_SIBLING_SWEEP_BYPASS_LOG"

# ---------------------------------------------------------------------------
# RM-688 RUN RECORD.
#
# WHY: before this, only the two BYPASS paths wrote anything. A clean pre-push
# run, a HALT and every FAULT left no trace, so a push that ran this gate and
# came back clean was indistinguishable, after the fact, from `git push
# --no-verify`, which skips .githooks/pre-push entirely. Every run now appends
# ONE line, and a pushed range with no matching record is a range the gate
# never saw. That is an AFTER-THE-FACT signal; it detects nothing in real time.
#
# The record must not become the leak it audits: every value is an enum, int,
# bool, ISO time or validated hex. Nothing derived from file content, a file
# path, a ref NAME, the remote name, the remote URL or a finding literal.
#
# Append-only, ONE os.write per record on an O_APPEND fd: no read-modify-write,
# no rolling, nothing a concurrent push can tear. It never raises and never
# changes an exit code. The path resolves to the MAIN checkout when this copy
# runs from a linked worktree (the hook runs the worktree's copy), so the record
# survives worktree cleanup. RUN_LOG_ENV overrides it (the test suite does).
# ---------------------------------------------------------------------------
RUN_LOG = Path("ops") / "runtime" / "sibling_sweep_runs.jsonl"
RUN_LOG_ENV = "RC_SIBLING_SWEEP_RUN_LOG"
RUN_RECORD_VERSION = 1
RUN_RANGE_MAX = 16

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# KNOWN OPEN HITS.
#
# Declared, named and visible - NEVER a silent allowlist. An entry here
# ANNOTATES a finding in the report; it never removes one, and it never changes
# the exit code. That property is what separates this register from a
# suppression list, and it is guarded by its own test.
#
# THE REGISTER IS EMPTY, AND THAT IS A MEASUREMENT RATHER THAN A DEFAULT.
# A tree-scope run (`--tree`) over the whole git index returns ZERO findings at
# this commit, so there is no open hit left to declare.
#
# The single entry that used to sit here named `tests/test_loop_concurrency.py`
# and justified itself with "this file is BYTE-PINNED across the participating
# repositories by SHARED_SHA256, so remediation is a JOINT act". That
# justification was FALSE, and it was false on the day it was written. The
# `SHARED_SHA256` dict pins exactly two files - `ops/loop/slots.py` and
# `ops/loop/winmutex.py` - and it hashes them as `ROOT / "ops" / "loop" /
# name`, so the PINNING FILE NEVER PINNED ITSELF. The hit was RC's to redact
# unilaterally all along; it was redacted in 86e4d4f0f, the two pinned digests
# were untouched, and `tests/test_loop_concurrency.py` stayed green across that
# edit. That green run is the disproof, not an argument about it.
#
# Two things this emptiness does NOT mean.
#   1. It does not undo PUBLICATION. The escapes reached the public remote and
#      no history was rewritten. Remediating HEAD is not recall.
#   2. It does not lower the escape rate, which stays measurably above zero.
#      LFS OBJECT content is never scanned, `--no-verify` bypasses the whole
#      hook, and the needle arm is inert without the per-host config.
#
# A future entry belongs here ONLY when a LIVE finding exists that RC genuinely
# cannot remediate alone - a hit inside one of the two byte-pinned files would
# qualify, because moving those bytes is a joint re-pin. Do NOT pre-declare an
# exception against a file that scans clean: an exception for a finding that
# does not exist is the same false declaration this block was just corrected
# for, merely pointed at a different path.
# ---------------------------------------------------------------------------
KNOWN_EXCEPTIONS: dict = {}


# ---------------------------------------------------------------------------
# Structural-arm allowlist, built from the negative-control classes.
#
# These are RC's OWN identity, RC's machine-local non-sibling directories, OS
# roots, and the redaction / fixture placeholders that already ship in the tree.
# Everything else that appears as a drive-rooted first segment is, by
# construction, a project this repo has not declared - which is the finding.
# ---------------------------------------------------------------------------
_ALLOW_SEGMENTS = frozenset(
    s.lower()
    for s in (
        # RC's own identity
        "Riot Commander",
        "RC",
        # RC's machine-local, non-sibling directories
        "Riot Games",
        "RC-Agent",
        "rc-worktrees",
        "RC-CIWatchdog",
        "RC-Recordings",
        "Peer-Bridge",
        # OS roots
        "Users",
        "Program Files",
        "Program Files (x86)",
        "ProgramData",
        "Windows",
        "temp",
        "tmp",
        "dev",
        "src",
        "path",
        "to",
    )
)

# Placeholder shapes: redaction markers and path-shaped test fixtures. A first
# segment matching any of these is a stand-in, not a project. Every entry below
# was MEASURED as a live structural hit on this tree, so this is the
# negative-control set the spec calls for, not a guess at one.
_ALLOW_PATTERNS = (
    re.compile(r"^sibling-[a-z0-9]+$", re.I),
    re.compile(r"^(some|another|example|your|my|fake|dummy|test|placeholder)\b", re.I),
    re.compile(r"^<.*>$"),
    re.compile(r"^\{+.*\}+$"),
    re.compile(r"^\.{1,2}$"),
    re.compile(r"^[a-z]$", re.I),
    # RC's own machine-local scaffolding: rc-*, Claude*, and the fu04 evidence
    # scratch. Each was measured as a live hit here and each is RC's own.
    re.compile(r"^rc[-_]", re.I),
    re.compile(r"^claude[a-z]*[-_]?[0-9]*$", re.I),
    re.compile(r"^fu[0-9]+[-_]", re.I),
    # Single-letter fixture filenames used as throwaway paths in tests.
    re.compile(r"^[a-z]\.[a-z0-9]{1,5}$", re.I),
    # Generic fixture roots used by tests and prose in this tree.
    re.compile(
        r"^(wt|bin|secret|logs?|fixtures?|nonexistent|evil|elsewhere|repo|private"
        r"|main|work|out|build|dist|data|project|user|riot|lockfile|leak\.[a-z]+"
        r"|definitely-not-.*|this-binary-does-not-exist.*)$",
        re.I,
    ),
)

# A NAMED false-positive class, not a catch-all. `"Ability R:\nShe will ..."` in
# a JSON ability description parses as drive `R:`, single backslash, first
# segment `nShe will ...`. The drive-letter lookbehind cannot help here because
# the character before `R` is itself a newline. Six live hits on this tree came
# from exactly this shape, so it is rejected explicitly rather than by widening
# the allowlist into uselessness.
_C_ESCAPE = re.compile(r"^[ntrfvb0](?=[A-Z ]|$)")

# A Windows first path segment is not a sentence. Three words is already
# generous - the longest legitimate one measured here is two.
_MAX_SEGMENT_WORDS = 3

# The lookbehind is LOAD-BEARING, not decoration. Without it the literal text
# `cooldown:\nUse Recall` parses as drive `n:` with first segment `nUse Recall`,
# and the structural arm fires on every coach string in the tree.
STRUCTURAL_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z]):[\\/]{1,2}([A-Za-z0-9 ()+._\-]{1,80})"
)
_SEP_RE = re.compile(r"[A-Za-z]:([\\/]{1,2})")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class SweepConfig:
    mode: str
    names: tuple = ()
    codes: tuple = ()
    participants: dict = field(default_factory=dict)
    source: str = ""
    detail: str = ""
    # Appended at the END with a default, per the repo's dataclass rule: a
    # mid-class required field breaks every existing positional construction.
    # Holds the CANONICAL slot spellings that resolved from the declaration, so
    # a declared name matching no slot simply is not here and narrows nothing.
    narrowed_names: tuple = ()
    # RM-799: one problem line per malformed / mis-spelled key, naming the key
    # and its expected shape, never its value. Non-empty only on a FAULT.
    malformed: tuple = ()


def _leaf(path_like: str) -> str:
    """Last path segment of a Windows or POSIX path, whitespace-trimmed."""
    text = str(path_like).strip().replace("\\", "/").rstrip("/")
    if not text:
        return ""
    leaf = text.rsplit("/", 1)[-1]
    # A bare drive ("C:") has no project name in it.
    if re.fullmatch(r"[A-Za-z]:", leaf):
        return ""
    return leaf.strip()


# A drive-letter path CONTAINS the POSIX path separator, and this gate does not
# run only on Windows: the tree is a Linux CI job away at all times.
_LONE_DRIVE = re.compile(r"^\s*[A-Za-z]\s*$")
_ROOTED = re.compile(r"^[\\/]")


def split_repo_list(raw: str, sep: Optional[str] = None) -> list:
    """Split an ``RC_MOON_SYNC_REPOS`` override into paths, drive-letter safe.

    MEASURED (CI run 34538335778, ubuntu runner): ``os.pathsep`` is ``;`` on
    Windows and ``:`` on POSIX, so the same override that loaded four paths here
    severed into EIGHT fragments there - every drive-letter path cut in two at
    its own colon - and the leading drive letter loaded as a fifth NAME. (No
    drive-rooted example is spelled out below, because this file is scanned by
    its own structural arm and an illustrative path is a live hit.) That is not a
    miscount to be waved through: a one-character needle compiles to
    ``(?<![A-Za-z0-9])C(?![A-Za-z0-9])``, which matches a standalone ``C``
    anywhere in the tree, so the gate would halt every push while pointing at
    nothing. Every sibling this repo coordinates with is a Windows checkout, so
    a Windows-shaped value arriving in a Linux process is the expected case, not
    an exotic one.

    The repair is narrow on purpose. Only when the separator is ``:`` does a
    fragment that is a lone letter, immediately followed by a fragment starting
    with ``\\`` or ``/``, get rejoined with its colon. An ordinary POSIX list is
    therefore untouched, because ``/srv/one`` is not a lone letter. The one
    genuinely ambiguous input - a relative POSIX directory literally named
    ``C`` sitting before an absolute path - resolves to the drive letter, which
    is the reading that matches every real caller of this tool.

    A lone drive that could NOT be rejoined (the override was a bare ``C:``)
    gets its colon back instead, so ``_leaf`` discards it by the rule it already
    has, rather than emitting that same catastrophic one-character needle.

    On a POSIX separator ``;`` is honoured as a delimiter too. A Windows-shaped
    VALUE usually arrives inside a Windows-shaped LIST, and without this the
    two-path form silently loses a sibling name into the middle of a fragment -
    an UNDER-detect, which is the one direction a leak gate must not fail in.
    A POSIX path may legally contain ``;``, so the cost is a possible extra
    needle: an over-detect, which halts loudly and is inspected on the spot.
    """
    separator = os.pathsep if sep is None else sep
    if separator != ":":
        return [p.strip() for p in (raw or "").split(separator) if p.strip()]
    out: list = []
    for chunk in (raw or "").split(";"):
        parts: list = []
        for frag in chunk.split(":"):
            if parts and _LONE_DRIVE.match(parts[-1]) and _ROOTED.match(frag):
                parts[-1] = parts[-1].strip() + ":" + frag
                continue
            parts.append(frag)
        parts = [p.strip() + ":" if _LONE_DRIVE.match(p) else p for p in parts]
        out.extend(p.strip() for p in parts if p.strip())
    return out


NARROWED_ENV = "RC_MOON_SYNC_NARROWED_NAMES"

# A Windows path COMPONENT may contain neither `;` nor `:`, so both are safe
# delimiters for a list of basenames on either platform. That is why this does
# NOT reuse `split_repo_list`: the repair that variable needs exists purely
# because a drive-letter PATH carries a colon of its own, and a basename does
# not.
_NARROWED_SEP = re.compile(r"[;:]")


def _narrow_key(name: str) -> str:
    """Comparison key for a declaration: case-folded, whitespace-collapsed."""
    return " ".join(str(name).split()).lower()


def _coded_slots(mapping: Optional[Mapping[str, Any]], names: list) -> list:
    """Arm the slots of a sweep-only ``{CODE: path | [path, bare name, ...]}``
    map (``retired``, ``supervisor``): every string value appends its leaf to
    ``names`` in place, and the non-blank codes are returned in map order. A
    non-dict map or a non-string value arms nothing and raises nothing HERE;
    ``load_config`` refuses such a shape as a FAULT before it reaches this
    (RM-799), so the skip only ever serves a direct ``config_from_parts`` call."""
    codes: list[str] = []
    for code, value in (mapping.items() if hasattr(mapping, "items") else ()):
        items = value if isinstance(value, (list, tuple)) else [value]
        for raw in items:
            leaf = _leaf(str(raw)) if isinstance(raw, str) else ""
            if leaf and leaf not in names:
                names.append(leaf)
        if str(code).strip():
            codes.append(str(code).strip())
    return codes


def config_from_parts(
    repos: Iterable[str],
    participants: Mapping[str, str],
    narrowed: Iterable[str] = (),
    retired: Optional[Mapping[str, Any]] = None,
    supervisor: Optional[Mapping[str, Any]] = None,
) -> SweepConfig:
    """Build an ARMED config from already-loaded parts. Used by tests and by
    the env-override path, which carries paths only and therefore no codes.

    ``narrowed`` is the DECLARED list of basenames whose bare-word arm is to be
    suppressed. It is resolved against the loaded slot names here rather than in
    ``build_needles`` so that the resolution happens exactly once, and so that a
    declaration naming no slot is visibly dropped instead of silently carried
    around. Appended at the END with a default, so every existing two-argument
    call - including the CI gate's - is unchanged.
    """
    names: list[str] = []
    for raw in repos:
        leaf = _leaf(raw)
        if leaf and leaf not in names:
            names.append(leaf)
    for raw in (participants or {}).values():
        leaf = _leaf(raw)
        if leaf and leaf not in names:
            names.append(leaf)
    # RETIRED siblings (MAIN order 2026-10-05: LL retired, "a retired sibling's
    # name is still a leak"). A retired tree leaves `participants`, because the
    # responder reads that map and must never address or spawn for it - but
    # every value here still arms a name slot and every key still arms a code.
    # A value is one path / bare name, or a list of them, so a project's
    # internal name can ride beside its checkout path. Appended at the END with
    # a default, so every existing call is unchanged.
    retired_codes = _coded_slots(retired, names)
    # RM-789: the SUPERVISOR tree (MAIN). Its checkout name is a leak like any
    # sibling's, but it can sit in none of the keys above, because each one has
    # another reader that acts on it: `repos` is polled, a `participants` path
    # outranks the arming record for delivery (ops/loop/inbox_tick.py
    # `_make_deliver`; MAIN 0327 RULING keeps the record as the one source of
    # MAIN's paths), and a `retired` code makes `validate_agreement` refuse the
    # whole record, since MAIN is always a counterparty. So it has its own
    # sweep-only key, same shape as `retired`. Appended at the END with a
    # default, so every existing call is unchanged.
    supervisor_codes = _coded_slots(supervisor, names)
    codes = tuple(str(c).strip() for c in (participants or {}) if str(c).strip())
    for extra in (retired_codes, supervisor_codes):
        codes += tuple(c for c in extra if c not in codes)
    declared = {_narrow_key(n) for n in (narrowed or ()) if str(n).strip()}
    narrowed_names = tuple(n for n in names if _narrow_key(n) in declared)
    return SweepConfig(
        mode=MODE_ARMED if names else MODE_FAULT,
        names=tuple(names),
        codes=codes,
        participants=dict(participants or {}),
        source="parts",
        detail="",
        narrowed_names=narrowed_names,
    )


CONFIG_RELATIVE = Path("ops") / "moon_sync_repos.json"


def _same_dir(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))
    except OSError:
        return False


def _read_link_line(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return None
    line = text.strip().splitlines()[0].strip() if text.strip() else ""
    return line or None


def main_working_tree(base: Path) -> Optional[Path]:
    """The MAIN working tree when ``base`` is the root of a LINKED worktree.

    MEASURED: the pre-push hook resolves this tool through ``git rev-parse
    --show-toplevel``, so a push from a worktree runs the worktree's copy, whose
    ``REPO_ROOT`` has no gitignored per-host config. Every such push ran
    DEGRADED and still exited 0.

    ``base`` must itself be a checkout TOP LEVEL. A directory that merely sits
    inside some repository does not resolve upward, so an odd ``--config-root``
    cannot arm itself from a repository it is not.

    RM-433: resolved from git's own on-disk worktree link, WITHOUT running git.
    This is now the shared resolver for every reader of the per-host config,
    and two of them must not create a process: the inbox responder resolves
    participants BEFORE its real-spawn guard, which promises no subprocess, and
    the poller resolves at import on a hook path, where a console child flashes.
    The link is ``<base>/.git`` as a FILE reading ``gitdir: <dir>``, and that
    dir's ``commondir`` names the shared ``.git`` (either may be relative). A
    submodule's ``.git`` file also names a gitdir, but one with NO
    ``commondir``, so it returns None here rather than resolving to its
    superproject. Returns None for the main tree itself (whose ``.git`` is a
    directory), a non-repository, a non-top-level directory, or any unreadable
    link.
    """
    base = Path(base)
    link = base / ".git"
    if not link.is_file():
        return None
    first = _read_link_line(link)
    if first is None or not first.startswith("gitdir:"):
        return None
    gitdir = Path(first[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = base / gitdir
    common = _read_link_line(gitdir / "commondir")
    if common is None:
        return None
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = gitdir / common_path
    # Collapse the `..` segments BEFORE taking the parent: git writes
    # `commondir` as `../..`, and `.parent` of an uncollapsed path is lexical,
    # which would name the `worktrees` dir instead of the checkout.
    common_path = Path(os.path.normpath(str(common_path)))
    main = common_path.parent
    if _same_dir(main, base) or not main.is_dir():
        return None
    # The shared dir must be the MAIN checkout's own `.git` directory; a bare
    # common dir has no working tree whose config could be borrowed.
    if not (main / ".git").is_dir() or not _same_dir(main / ".git", common_path):
        return None
    return main


def resolve_config_path(base: Path) -> Path:
    """THE resolver for the gitignored per-host sync config (RM-433).

    Every reader of ``ops/moon_sync_repos.json`` calls this, so a linked
    worktree - which never carries the gitignored file - reads the MAIN working
    tree's copy instead of silently degrading to zero siblings.

    Order: the checkout's own file when it exists, else the main working tree's
    file when THAT exists, else the checkout's own (absent) path, so a caller's
    existing absent-file handling stays the honest answer. The
    ``RC_MOON_SYNC_REPOS`` override is NOT consulted here: it carries only a
    repo list, each reader already checks it BEFORE touching the file, and that
    precedence is unchanged. No git process runs when the local file exists.
    """
    base = Path(base)
    local = base / CONFIG_RELATIVE
    if local.exists():
        return local
    main_tree = main_working_tree(base)
    if main_tree is not None and (main_tree / CONFIG_RELATIVE).exists():
        return main_tree / CONFIG_RELATIVE
    return local


# ---------------------------------------------------------------------------
# RM-799: a key this sweep cannot read is a FAULT, never a silently lost slot.
#
# MEASURED (the RM-789 verifier): a junk-shaped `supervisor` / `retired` value,
# a mis-cased key and any RC_MOON_SYNC_REPOS override each armed NOTHING and
# raised nothing; only the banner's slot count moved, and nobody compares that
# across pushes. The sweep already fails CLOSED on a broken config (unreadable
# JSON and zero usable names are both FAULT, exit 3), so a key it cannot read
# joins them rather than degrading with a warning a headless push never shows
# anyone. Each problem names the KEY and its expected SHAPE, never the value:
# the FAULT banner lands in hook stderr and CI logs.
# ---------------------------------------------------------------------------
_CODED_SHAPE = (
    "an object mapping a non-blank CODE to one path string or a non-empty list "
    "of path / name strings, each naming a checkout"
)
CONFIG_KEY_SHAPES = {
    "repos": "a list of path strings, each naming a checkout",
    "participants": "an object mapping a non-blank CODE to one path string naming a checkout",
    "narrowed_names": "a list of non-blank basename strings",
    "retired": _CODED_SHAPE,
    "supervisor": _CODED_SHAPE,
}
# The sweep-only coded keys: the only keys still read from the per-host file
# when RC_MOON_SYNC_REPOS supplies the repo list instead.
CODED_KEYS = ("retired", "supervisor")


def _names_checkout(raw: Any) -> bool:
    return isinstance(raw, str) and bool(_leaf(raw))


def _shape_ok(key: str, value: Any) -> bool:
    if key == "repos":
        return isinstance(value, list) and all(_names_checkout(v) for v in value)
    if key == "narrowed_names":
        return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)
    if not isinstance(value, dict) or not all(str(c).strip() for c in value):
        return False
    if key == "participants":
        return all(_names_checkout(v) for v in value.values())
    return all(
        (bool(v) and all(_names_checkout(x) for x in v)) if isinstance(v, list)
        else _names_checkout(v)
        for v in value.values()
    )


def config_problems(blob: Any, keys: Sequence[str] = tuple(CONFIG_KEY_SHAPES)) -> list:
    """One line per malformed or mis-spelled key among ``keys`` (RM-799).

    An absent key and an empty container are NOT problems: absence is the
    documented empty declaration. A key spelled differently from a known key
    only by case or surrounding whitespace is a problem, because it is never
    read. Lines name keys and shapes only, never a value.
    """
    if not isinstance(blob, dict):
        return ["the top level must be a JSON object"]
    problems: list = []
    for key in keys:
        if any(raw != key and str(raw).strip().lower() == key for raw in blob):
            problems.append(
                f"'{key}' is mis-spelled (key names are exact and case-sensitive), "
                "so that key is NOT read"
            )
        elif key in blob and not _shape_ok(key, blob[key]):
            problems.append(f"'{key}' must be {CONFIG_KEY_SHAPES[key]}")
    return problems


def _malformed_fault(source: str, problems: Sequence[str], lead: str) -> SweepConfig:
    detail = (
        f"{lead} has {len(problems)} malformed key(s) (RM-799): "
        + "; ".join(problems)
        + ". A key the sweep cannot read arms no slot, so the gate refuses to run "
        "rather than pass with a slot silently missing. Fix "
        f"{CONFIG_RELATIVE.as_posix()}; ops/moon_sync_repos.example.json shows every shape"
    )
    return SweepConfig(mode=MODE_FAULT, source=source, detail=detail, malformed=tuple(problems))


def _override_coded_parts(base: Path):
    """The per-host file's sweep-only coded keys, for the env path (RM-799).

    ``RC_MOON_SYNC_REPOS`` is a repos-only path list, so it cannot carry MAIN's
    ``supervisor`` slot or a ``retired`` slot; before RM-799 the env branch read
    neither and every one of those slots dropped whenever the override was set.
    They are read from the per-host file here, validated as the file path
    validates them, and armed BESIDE the override. The file's narrowing is
    filtered here to declarations naming a coded leaf, so a coded slot keeps its
    declared strength. ``load_config`` then drops any that ALSO name a leaf the
    override supplies (case-folded), because narrowing resolves over every
    loaded name: so a file declaration never weakens a slot the override itself
    supplies, and a coded slot sharing that key keeps full strength with it.
    An absent file contributes nothing (CI, a fresh clone).

    Returns ``(retired, supervisor, narrowed, fault)``; ``fault`` is a FAULT
    config or None.
    """
    config_path = resolve_config_path(base)
    if not config_path.exists():
        return {}, {}, [], None
    lead = "RC_MOON_SYNC_REPOS is set, and the per-host config beside it"
    try:
        blob = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, {}, [], SweepConfig(
            mode=MODE_FAULT,
            source=str(config_path),
            detail=f"{lead} is present but unreadable: {type(exc).__name__}, so its "
            "supervisor / retired slots cannot be armed",
        )
    problems = config_problems(blob, CODED_KEYS)
    if problems:
        return {}, {}, [], _malformed_fault(str(config_path), problems, lead)
    retired = blob.get("retired") or {}
    supervisor = blob.get("supervisor") or {}
    coded_leaves: list = []
    _coded_slots(retired, coded_leaves)
    _coded_slots(supervisor, coded_leaves)
    leaf_keys = {_narrow_key(n) for n in coded_leaves}
    declared = blob.get("narrowed_names")
    narrowed = [
        n for n in (declared if isinstance(declared, list) else [])
        if isinstance(n, str) and n.strip() and _narrow_key(n) in leaf_keys
    ]
    return retired, supervisor, narrowed, None


def load_config(
    root: Optional[Path] = None, env: Optional[Mapping[str, str]] = None
) -> SweepConfig:
    """Resolve needles, mirroring ``tools/moon_sync_poller.py`` ``_load_repo_roots``.

    Extended in exactly one way: the ``participants`` map is read when present,
    because a CODE next to a NAME publishes the resolution and must outrank a
    bare name hit. The poller ignores that key, so the two readers stay
    compatible with the same gitignored file.

    DELIBERATE DIVERGENCE from the poller, added after CI run 34538335778: the
    override is split by ``split_repo_list``, not by a bare ``raw.split(
    os.pathsep)``. The poller runs on Windows only, where ``os.pathsep`` is
    ``;`` and the naive split is correct; this gate additionally runs in a Linux
    CI job, where ``:`` cuts every drive-letter path in half. Same file, same
    keys, one reader that has to survive a platform the other never sees.

    RM-799: every key this sweep reads is shape-checked by ``config_problems``
    and a malformed or mis-spelled one is a FAULT, like an unreadable file. The
    override still REPLACES ``repos`` and carries no ``participants``, but the
    file's sweep-only ``supervisor`` / ``retired`` slots stay armed beside it
    (``_override_coded_parts``).
    """
    base = Path(root) if root is not None else REPO_ROOT
    environ = os.environ if env is None else env

    narrowed_env = [
        part.strip()
        for part in _NARROWED_SEP.split(environ.get(NARROWED_ENV) or "")
        if part.strip()
    ]

    raw = (environ.get("RC_MOON_SYNC_REPOS") or "").strip()
    if raw:
        paths = split_repo_list(raw)
        retired, supervisor, file_narrowed, fault = _override_coded_parts(base)
        if fault is not None:
            return fault
        # A file declaration never narrows a leaf the override supplies: the
        # declaration resolves over EVERY loaded name, so without this filter a
        # coded leaf it names would narrow a case-folded-equal override slot too.
        # Only RC_MOON_SYNC_NARROWED_NAMES (the override's own channel) may.
        override_keys = {_narrow_key(_leaf(p)) for p in paths if _leaf(p)}
        narrowed = narrowed_env + [
            n for n in file_narrowed
            if n not in narrowed_env and _narrow_key(n) not in override_keys
        ]
        cfg = config_from_parts(paths, {}, narrowed, retired, supervisor)
        cfg.source = "RC_MOON_SYNC_REPOS"
        if cfg.mode == MODE_FAULT:
            cfg.detail = "RC_MOON_SYNC_REPOS is set but yields zero usable names"
        return cfg

    # A linked worktree never carries the gitignored config, but the MAIN
    # working tree of the same repository does. Borrow it only when it exists
    # there; an absent file stays an honest DEGRADED.
    config_path = resolve_config_path(base)
    if not config_path.exists():
        return SweepConfig(
            mode=MODE_DEGRADED,
            source=str(config_path),
            detail="per-host config absent (fresh clone, CI, or a worktree)",
        )

    try:
        blob = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return SweepConfig(
            mode=MODE_FAULT,
            source=str(config_path),
            detail=f"config present but unreadable: {type(exc).__name__}",
        )
    problems = config_problems(blob)
    if problems:
        return _malformed_fault(str(config_path), problems, "config")

    repos = [str(p) for p in (blob.get("repos") or []) if str(p).strip()]
    participants = {
        str(k): str(v) for k, v in (blob.get("participants") or {}).items() if str(k).strip()
    }
    # An absent key means an empty declaration, which means FULL STRENGTH. That
    # is the whole compatibility story for a per-host config written before this
    # key existed, and it is the direction a leak gate must default in.
    narrowed = [str(n) for n in (blob.get("narrowed_names") or []) if str(n).strip()]
    narrowed += [n for n in narrowed_env if n not in narrowed]
    # Retired siblings: read by THIS sweep only, never by the responder or the
    # poller, so a retired code stays a needle without becoming a destination.
    # Shape-checked above (RM-799), so a non-object never reaches this.
    retired = blob.get("retired") or {}
    # RM-789: MAIN's checkout name, likewise read by THIS sweep only.
    supervisor = blob.get("supervisor") or {}
    cfg = config_from_parts(repos, participants, narrowed, retired, supervisor)
    cfg.source = str(config_path)
    if cfg.mode == MODE_FAULT:
        cfg.detail = "config parsed but yields zero usable sibling names"
    return cfg


def mode_banner(cfg: SweepConfig) -> str:
    """The ARMED line states the narrowed COUNT on every surface that prints it.

    The count is printed even when it is zero, so "nothing is narrowed here" is
    an assertion the reader can make rather than an absence they have to infer.
    No name is ever printed - a banner that spells a narrowed slot would
    relocate the very leak this gate exists to stop, into CI logs.
    """
    if cfg.mode == MODE_ARMED:
        narrowed = len(cfg.narrowed_names)
        line = (
            f"[sibling-sweep] ARMED - {len(cfg.names)} name slot(s) "
            f"({narrowed} NARROWED), {len(cfg.codes)} counterparty code(s) "
            "loaded from per-host config."
        )
        if narrowed:
            line += (
                " WEAKENED BY DECLARATION: a narrowed slot has its BARE-WORD arm "
                "suppressed in BOTH views, so a bare mention of that name in "
                "prose will NOT halt. Its drive-path and github URL arms stay "
                "armed in both views, and the structural arm is unaffected."
            )
        return line
    if cfg.mode == MODE_DEGRADED:
        return (
            "[sibling-sweep] DEGRADED - no per-host config on this machine, so "
            "the NEEDLE arm proved NOTHING about this push. It did not pass; it "
            "did not run. Only the config-free STRUCTURAL arm was evaluated. "
            "Restore ops/moon_sync_repos.json (see ops/moon_sync_repos.example.json) "
            "or set RC_MOON_SYNC_REPOS to arm it."
        )
    return f"[sibling-sweep] FAULT - {cfg.detail or 'the guard could not run'}."


# ---------------------------------------------------------------------------
# Needles
# ---------------------------------------------------------------------------
@dataclass
class CompiledShape:
    shape: str
    view: str
    regex: "re.Pattern"


@dataclass
class Needle:
    slot: int
    name: str
    variants: dict
    patterns: tuple
    # Appended at the END with a default (repo dataclass rule). True only when
    # the per-host config DECLARED this slot; never inferred from the name.
    narrowed: bool = False
    # F2 (session 124). A NECESSARY-condition regex from `build_prefilter`;
    # None means "no proof available, scan every window" (fail-safe).
    prefilter: Optional[Any] = None


def _variant_fragments(name: str) -> dict:
    """Regex fragments for one name, one per S4 family.

    SPACED tolerates the space being absent because the haystack is searched in
    a whitespace-collapsed view; that also makes the concatenated spelling fall
    out for free, which is deliberate belt-and-braces.
    """
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    esc = [re.escape(t) for t in tokens]
    return {
        "SPACED": " ?".join(esc),
        "HYPHEN": "-".join(esc),
        "UNDER": "_".join(esc),
        "CONCAT": "".join(esc),
        "PCT20": "%20".join(esc),
    }


_LEFT_EDGE = r"(?<![A-Za-z0-9])"
_RIGHT_EDGE = r"(?![A-Za-z0-9])"

# RM-813. The DRIVE arm is the one a NARROWED slot keeps, so every spelling of
# a drive root has to reach it, not only the drive-letter one: the WSL mount
# `/mnt/<x>/`, the POSIX-shell drive `/<x>/`, and the WSL UNC path
# `<lead>wsl$<sep><distro><sep>mnt<sep><x><sep>` (either host, the Win32 `?`
# long-path or `.` device step). A non-narrowed slot already halted on those
# through its bare arm. The head is only ever WIDENED by an alternative, so
# every earlier drive match is still a match (monotone by construction); the
# name, its right edge and the one-letter drive are unchanged. The lead is the
# same string as `tools/credential_patterns.py` `_WSL_UNC_LEAD`, pinned equal
# by tests/test_rm813_push_gate_mount_spellings.py.
_WSL_UNC_LEAD = (
    r"[\\/]{2,4}(?:[?.][\\/]{1,2}unc[\\/]{1,2})?wsl(?:\$|\.localhost)"
    r"[\\/]{1,2}[^\\/\s]{1,64}"
)
_DRIVE_HEAD = (
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]:[\\/]{1,2}|/mnt/[A-Za-z]/|/[A-Za-z]/|"
    + _WSL_UNC_LEAD
    + r"[\\/]{1,2}mnt[\\/]{1,2}[A-Za-z][\\/]{1,2})"
)


def build_needles(cfg: SweepConfig) -> list:
    narrowed_keys = {_narrow_key(n) for n in (cfg.narrowed_names or ())}
    needles: list = []
    for slot, name in enumerate(cfg.names):
        # PER-SLOT and EXPLICIT. The only input to this decision is the
        # declaration loaded from the gitignored config; the name itself is
        # never examined for "genericness".
        narrowed = _narrow_key(name) in narrowed_keys
        variants = _variant_fragments(name)
        tight = "".join(re.escape(t) for t in re.split(r"\s+", name.strip()) if t)
        shapes: list = []
        for family, frag in variants.items():
            # S1 + S2: drive letter, one or two separators, either slash, and
            # (RM-813) the mount spellings of the same drive root.
            shapes.append(
                CompiledShape(
                    f"{SHAPE_DRIVE}/{family}",
                    VIEW_SPACE,
                    re.compile(_DRIVE_HEAD + frag + _RIGHT_EDGE, re.I),
                )
            )
            # S7: github.com/<owner>/<spelling>
            shapes.append(
                CompiledShape(
                    f"{SHAPE_URL}/{family}",
                    VIEW_SPACE,
                    re.compile(
                        r"github\.com/[A-Za-z0-9_.\-]+/" + frag + _RIGHT_EDGE, re.I
                    ),
                )
            )
            # S3: the spelling anywhere in prose. THIS is the arm a narrowed
            # slot gives up, and the only one.
            if not narrowed:
                shapes.append(
                    CompiledShape(
                        f"{SHAPE_BARE}/{family}",
                        VIEW_SPACE,
                        re.compile(_LEFT_EDGE + frag + _RIGHT_EDGE, re.I),
                    )
                )
        # S6 tight view: the name reassembled after ALL whitespace and comment
        # continuation prefixes are removed. This is the arm that sees a name
        # split MID-TOKEN across a wrapped line, which no contiguous search can.
        #
        # NOTE, and this cost a red test to learn: word-boundary assertions are
        # MEANINGLESS in this view. Removing whitespace also removes every
        # boundary, so `(?<![A-Za-z0-9])` fails on "...with theQuicksilt..." and
        # the split form goes unseen - the exact miss the tight view exists to
        # catch. The boundaries are therefore re-checked against the ORIGINAL
        # text in `scan_text` instead, where they still mean something.
        # Suppression covers BOTH views or it covers nothing: leaving the tight
        # bare arm armed would halt on the same prose the space view was just
        # told to ignore, merely with a stranger error message.
        if not narrowed:
            shapes.append(
                CompiledShape(
                    f"{SHAPE_BARE}/CONCAT", VIEW_TIGHT, re.compile(tight, re.I)
                )
            )
        shapes.append(
            CompiledShape(
                f"{SHAPE_DRIVE}/CONCAT",
                VIEW_TIGHT,
                re.compile(_DRIVE_HEAD + tight, re.I),
            )
        )
        needles.append(
            Needle(
                slot=slot,
                name=name,
                variants=variants,
                patterns=tuple(shapes),
                narrowed=narrowed,
                prefilter=build_prefilter(name, variants),
            )
        )
    return needles


def assert_non_vacuous(needles: Sequence) -> None:
    """ADR-015 anchor. An empty enumeration and a clean tree are the same
    verdict to every consumer, so refuse to be silently vacuous.

    EXTENDED for per-slot narrowing, rather than bypassed for it. Narrowing is a
    deliberate reduction in coverage, and the way such a reduction goes wrong is
    by continuing past the point that was agreed. So:

    * EVERY needle, narrowed or not, must still carry a DRIVE shape and a URL
      shape. A narrowed-to-nothing slot therefore raises here rather than
      passing every push quietly.
    * A NON-narrowed needle must additionally carry its BARE shape. That catches
      the opposite accident - an arm lost with no declaration behind it - which
      no behavioural test can distinguish from a correct narrowing.
    * The pre-existing per-family variant bound is untouched and still applies
      to every slot: ``variants`` is built identically either way, because
      narrowing suppresses SHAPES, not spellings.
    """
    if not needles:
        raise AssertionError(
            "sibling-name sweep has ZERO needles. An empty needle set passes "
            "every push for the wrong reason - fix the loader, do not relax "
            "this bound."
        )
    for needle in needles:
        missing = [f for f in VARIANT_FAMILIES if not needle.variants.get(f)]
        if missing:
            raise AssertionError(
                f"needle slot {needle.slot} is missing variant families {missing}"
            )
        if not needle.patterns:
            raise AssertionError(f"needle slot {needle.slot} compiled zero patterns")
        families = {s.shape.split("/", 1)[0] for s in needle.patterns}
        required = {SHAPE_DRIVE, SHAPE_URL}
        if not getattr(needle, "narrowed", False):
            required.add(SHAPE_BARE)
        absent = sorted(required - families)
        if absent:
            raise AssertionError(
                f"needle slot {needle.slot} "
                f"(narrowed={bool(getattr(needle, 'narrowed', False))}) is "
                f"missing required shape(s) {absent}. Narrowing suppresses the "
                f"{SHAPE_BARE} arm and NOTHING else; a slot that has lost its "
                "drive-path or URL arm identifies a counterparty and no longer "
                "halts on it."
            )


# ---------------------------------------------------------------------------
# Haystack normalisation (S6)
# ---------------------------------------------------------------------------
_CONT_PREFIX = "#/*>-"

# ---------------------------------------------------------------------------
# F2 (session 124, RM-695 runtime half): a SOUND per-window prefilter.
#
# MEASURED at 01e951302: ARMED, `scan_text` cost ~1.3 s per MB because every
# window paid `build_views` plus all 113 compiled shapes, needle or not. The
# seven smudged 66 MB laning_scenarios LFS payloads took 84-85 s EACH, the tree
# ~750 s, and the CI gate's self-test blew the suite's 300 s timeout every run.
# Exclusion stays ruled out (RM-477); this skips WORK, never bytes.
#
# Why a window that fails the check cannot hold a match, in either view: both
# views are the window minus a subset of whitespace (`str.isspace`) and
# continuation-prefix characters, plus inserted single spaces. Deleting that
# whole class from the window AND from a match therefore leaves the match a
# substring. Every shape is `prefix + one family fragment [+ edge]`, and a
# fragment match, so reduced, is the name joined by that family's fixed
# separator, so reduced. re.I is applied by the SAME engine on both sides, and
# no character case-folds onto a deleted one. Each premise is pinned in
# tests/test_sibling_sweep_prefilter_f2.py, including filtered == unfiltered
# findings over every family, split forms, seams and re.I traps.
# ---------------------------------------------------------------------------
_PREFILTER_DROP = re.compile(r"[\s" + re.escape(_CONT_PREFIX) + r"]+")

# The literal separator each VARIANT_FAMILIES fragment joins tokens with.
_FAMILY_SEPARATORS = {
    "SPACED": " ",
    "HYPHEN": "-",
    "UNDER": "_",
    "CONCAT": "",
    "PCT20": "%20",
}


def build_prefilter(name: str, variants: Mapping[str, str]):
    """One case-insensitive regex that must hit a reduced window before any
    shape of this needle can. None (always scan) when a family is unknown or a
    reduced spelling is empty - no proof, no filter."""
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    literals = set()
    for family in variants:
        sep = _FAMILY_SEPARATORS.get(family)
        if sep is None:
            return None
        literal = _PREFILTER_DROP.sub("", sep.join(tokens))
        if not literal:
            return None
        literals.add(literal)
    if not literals:
        return None
    ordered = sorted(literals, key=lambda s: (-len(s), s))
    return re.compile("|".join(re.escape(s) for s in ordered), re.I)


def _strip_continuations(text: str, at_blob_start: bool = True):
    """Drop leading whitespace plus a comment-continuation prefix run from every
    line after the first. Returns (text, index map back into the original).

    ``at_blob_start`` exists for RM-477 windowing and is load-bearing. The
    "first line" carve-out is an assertion about the BLOB, not about the string
    this function happens to be handed: a window that starts at line 40 must
    strip line 40's continuation prefix, because the whole-blob view does. Left
    hard-coded to True, every window would preserve its own opening prefix and
    the tight view would lose exactly the wrapped-comment split form it exists
    to catch - at one seam per megabyte, invisibly.
    """
    chars: list = []
    idxs: list = []
    pos = 0
    first = at_blob_start
    for line in text.splitlines(keepends=True):
        start = pos
        pos += len(line)
        off = 0
        if not first:
            k = 0
            while k < len(line) and line[k] in " \t":
                k += 1
            m = k
            while m < len(line) and line[m] in _CONT_PREFIX:
                m += 1
            if m > k:
                while m < len(line) and line[m] in " \t":
                    m += 1
                off = m
        first = False
        for j in range(off, len(line)):
            chars.append(line[j])
            idxs.append(start + j)
    return "".join(chars), idxs


def _collapse(text: str, idxs: Sequence[int], drop_all: bool):
    out: list = []
    oidx: list = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            j = i
            while j < n and text[j].isspace():
                j += 1
            if not drop_all:
                out.append(" ")
                oidx.append(idxs[i])
            i = j
        else:
            out.append(text[i])
            oidx.append(idxs[i])
            i += 1
    return "".join(out), oidx


def build_views(text: str, at_blob_start: bool = True) -> dict:
    """Normalise ONE window. Indices map back into the string passed in, not
    into the enclosing blob - `scan_text` adds the window offset."""
    stripped, idxs = _strip_continuations(text, at_blob_start=at_blob_start)
    space_text, space_idx = _collapse(stripped, idxs, drop_all=False)
    tight_text, tight_idx = _collapse(stripped, idxs, drop_all=True)
    return {
        VIEW_SPACE: (space_text, space_idx),
        VIEW_TIGHT: (tight_text, tight_idx),
    }


def _scan_windows(text: str):
    """Yield ``(start, window_text, core_start, core_end, at_blob_start)``.

    THE CORES TILE THE BLOB EXACTLY and a finding is kept only when its
    ORIGINAL start falls inside the window's own core, so every offset in the
    blob belongs to exactly one window. That is what makes a windowed scan
    return the same finding SET as a whole-blob scan rather than a superset
    with a duplicate at every seam.

    Each window then carries ``CHUNK_GUARD`` characters of REAL text on both
    sides of its core, and both sides are load-bearing for a different reason:

    * LEFT. Every needle pattern opens with a ``(?<![A-Za-z0-9])`` lookbehind,
      and a lookbehind at offset 0 of a string succeeds trivially. A window that
      began at its own core would manufacture a hit in the middle of a word -
      chunking can INVENT a finding as easily as it can lose one.
    * RIGHT. A match, plus the ``CODE_WINDOW`` of context that decides whether
      it is a NAME or a RESOLUTION, has to fit inside the window that reports
      it. Without the right guard a name near a seam silently DOWNGRADES.

    The start is snapped BACK to a line boundary when one is within reach,
    because `_strip_continuations` treats the first line of what it is given
    specially. The snap is BOUNDED rather than unconditional on purpose: this
    tree carries multi-megabyte single-line JSON, and an unbounded search for a
    preceding newline would walk back to offset 0 on every window and restore
    the whole-blob memory profile this function exists to remove.
    """
    n = len(text)
    step = max(1, int(CHUNK_STEP))
    guard = max(1, int(CHUNK_GUARD))
    if n <= step + guard:
        yield 0, text, 0, n, True
        return
    core = 0
    while core < n:
        core_end = min(n, core + step)
        start = max(0, core - guard)
        if start > 0:
            nl = text.rfind("\n", max(0, start - guard), start)
            if nl >= 0:
                start = nl + 1
        end = min(n, core_end + guard)
        yield start, text[start:end], core, core_end, start == 0
        core = core_end


def _line_of(text: str, offset: int, base_line: int) -> int:
    return base_line + text.count("\n", 0, max(0, offset))


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    slot: int
    shape: str
    view: str
    source: str
    path: str
    line: int
    status: str
    severity: str
    literal: str = ""
    offset: int = 0

    def key(self):
        return (self.source, self.path, self.line, self.offset)


@dataclass
class ScanStats:
    scanned_bytes: int = 0
    unscanned_bytes: int = 0
    binary_blobs: int = 0
    lfs_pointers: int = 0
    decode_failures: int = 0
    commits: int = 0
    paths: int = 0
    files: int = 0
    diff_nonempty: bool = False
    # RM-491: untracked, not-ignored files the tree arm also scanned.
    untracked: int = 0


_SPECIFICITY = {SHAPE_DRIVE: 3, SHAPE_URL: 2, SHAPE_BARE: 1}


def _edges_clear(text: str, start: int, end: int) -> bool:
    """Re-apply word boundaries against the ORIGINAL text.

    The tight view has no boundaries left to assert on, so a tight-view hit is
    only a hit when the span it maps back to is not buried inside a longer word.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return not (before.isalnum() or after.isalnum())


def _rank(shape: str) -> int:
    return _SPECIFICITY.get(shape.split("/", 1)[0], 0)


def scan_text(
    needles: Sequence,
    codes: Sequence[str],
    text: str,
    *,
    path: str,
    source: str,
    status: str = "M",
    base_line: int = 1,
) -> list:
    """Run the NEEDLE arm over one blob. Never matches a code on its own.

    RM-477: the blob is walked in OVERLAPPING WINDOWS (`_scan_windows`) so peak
    memory is a function of CHUNK_STEP and not of the blob. Nothing is skipped -
    the cores tile the blob exactly - and the per-line collapse below is
    unchanged, so `--pre-push` and `--scan-file` see identical findings.

    Two things in here are ordered so that the window layout cannot leak into
    the RESULT, which is the whole parity claim:

    * A match is kept only when its ORIGINAL start lies in the reporting
      window's core, so each offset is considered exactly once.
    * The per-line winner is chosen by a TOTAL, order-INDEPENDENT key rather
      than by "whoever was seen first". A blob whose line is longer than one
      window is visited shape-major inside a window and window-major across
      them, so a first-wins tie-break would pick a different shape label
      depending on CHUNK_STEP. That is a difference nothing would have caught.
    """
    if not text or not needles:
        return []
    code_res = [
        re.compile(_LEFT_EDGE + re.escape(c) + _RIGHT_EDGE) for c in codes if c
    ]
    guard = max(1, int(CHUNK_GUARD))
    windowed = len(text) > max(1, int(CHUNK_STEP)) + guard
    best: dict = {}
    prev_start = 0
    nl_before = 0
    for chunk_start, chunk_text, core_start, core_end, at_start in _scan_windows(text):
        # Newlines before this window, carried forward rather than recounted
        # from offset 0 - the fallback keeps it correct if a bounded snap-back
        # ever walks a window start behind its predecessor.
        if chunk_start >= prev_start:
            nl_before += text.count("\n", prev_start, chunk_start)
        else:
            nl_before = text.count("\n", 0, chunk_start)
        prev_start = chunk_start
        # F2: only needles whose prefilter hits this window (or that carry no
        # prefilter) are scanned; a window with none skips `build_views`. The
        # previous window's views are released first (see the note below).
        views = view_text = view_idx = None
        reduced = None
        active = []
        for needle in needles:
            pre = getattr(needle, "prefilter", None)
            if pre is not None:
                if reduced is None:
                    reduced = _PREFILTER_DROP.sub("", chunk_text)
                if not pre.search(reduced):
                    continue
            active.append(needle)
        reduced = None
        if not active:
            continue
        # Drop the PREVIOUS window before building the next one, and drop the
        # UNPACKED views with it. Plain rebinding holds both generations alive
        # across the `build_views` call and doubles the peak - measured twice:
        # a 1.88x memory curve from the dict alone, and 131 MB where 76 was
        # expected because `view_text` / `view_idx` outlive the loop that
        # unpacked them. Clearing the dict without clearing those names fixes
        # half of it and looks like a fix.
        views = view_text = view_idx = None
        views = build_views(chunk_text, at_blob_start=at_start)
        for needle in active:
            for ordinal, shape in enumerate(needle.patterns):
                view_text, view_idx = views[shape.view]
                for m in shape.regex.finditer(view_text):
                    if m.start() >= len(view_idx):
                        continue
                    local_start = view_idx[m.start()]
                    end_i = min(m.end(), len(view_idx)) - 1
                    local_end = view_idx[end_i] + 1 if end_i >= 0 else local_start
                    orig_start = chunk_start + local_start
                    orig_end = chunk_start + local_end
                    if not (core_start <= orig_start < core_end):
                        continue
                    if windowed and orig_end - orig_start > guard:
                        raise ChunkGuardExceeded(
                            f"{path}: a match spans {orig_end - orig_start} "
                            f"characters, wider than CHUNK_GUARD={guard}. A "
                            "match wider than the overlap can fall between two "
                            "windows, so this halts rather than reporting a "
                            "clean scan it cannot justify. Raise CHUNK_GUARD."
                        )
                    if shape.view == VIEW_TIGHT and not _edges_clear(
                        text, orig_start, orig_end
                    ):
                        continue
                    severity = SEV_NAME
                    if code_res:
                        lo = max(0, m.start() - CODE_WINDOW)
                        hi = min(len(view_text), m.end() + CODE_WINDOW)
                        window = view_text[lo:hi]
                        if any(cre.search(window) for cre in code_res):
                            severity = SEV_RESOLUTION
                    finding = Finding(
                        slot=needle.slot,
                        shape=shape.shape,
                        view=shape.view,
                        source=source,
                        path=path,
                        line=base_line
                        + nl_before
                        + chunk_text.count("\n", 0, local_start),
                        status=status,
                        severity=severity,
                        literal=text[orig_start:orig_end],
                        offset=orig_start,
                    )
                    rankkey = (
                        _rank(shape.shape),
                        severity == SEV_RESOLUTION,
                        -ordinal,
                        -orig_start,
                    )
                    key = (path, source, finding.line, needle.slot)
                    prior = best.get(key)
                    if prior is None or rankkey > prior[0]:
                        best[key] = (rankkey, finding)
    return sorted(
        (f for _, f in best.values()), key=lambda f: (f.path, f.line, f.slot)
    )


def _trim(segment: str) -> str:
    """Strip whitespace and trailing sentence punctuation from a captured
    segment. Without this, `Riot Commander)` misses the allowlist entry that
    `Riot Commander` matches, and the arm reports RC's own root as unknown."""
    return (segment or "").strip().strip(".,;:)]}\"'").strip()


def _is_allowed(candidate: str) -> bool:
    candidate = _trim(candidate)
    if not candidate:
        return False
    if candidate.lower() in _ALLOW_SEGMENTS:
        return True
    return any(p.match(candidate) for p in _ALLOW_PATTERNS)


def _slot_head_re(slot_names: Sequence[str]):
    """One regex matching a loaded slot name, in any S4 spelling, right-edged
    like the needle DRIVE arm, at the start of a captured first segment. None
    when no name is loaded."""
    frags = [
        frag
        for name in slot_names
        if str(name).strip()
        for frag in _variant_fragments(str(name)).values()
    ]
    if not frags:
        return None
    return re.compile(r"\s*(?:" + "|".join(frags) + ")" + _RIGHT_EDGE, re.I)


def structural_findings(
    text: str,
    *,
    path: str,
    source: str,
    status: str = "M",
    base_line: int = 1,
    slot_names: Sequence[str] = (),
) -> list:
    """Config-free arm: a drive-rooted first path segment that is not on the
    allowlist. This is what keeps the gate non-inert in a fresh clone and in CI.

    ``slot_names`` are the LOADED slot names (``cfg.names``); every ARMED gate
    path passes them. A first segment that starts with one is a finding, and
    none of the config-free skips below (the allowlist, the C-escape class, the
    word cap) subtracts it: the allowlist is placeholder spellings, and a
    configured checkout that shares one is still a sibling root. Without this,
    such a slot kept only the needle arm (measured on a live config by the
    junction pin, ``tests/test_junction_drive_spellings_pubrepo_f.py``).
    Narrowing plays no part here. With no names (DEGRADED, CI) the arm is
    exactly the config-free one, and that blind spot stays a declared residual.
    """
    out: list = []
    seen: set = set()
    slot_head = _slot_head_re(slot_names) if slot_names else None
    for m in STRUCTURAL_RE.finditer(text or ""):
        segment = _trim(m.group(2))
        if not segment:
            continue
        is_slot = slot_head is not None and slot_head.match(text, m.start(2)) is not None
        # The `\n`-in-a-string class, rejected by name rather than by widening.
        # Only a SINGLE backslash can be a C-style escape, so the doubled form
        # (a genuine escaped Windows path) is deliberately left alone.
        sep = _SEP_RE.match(m.group(0)).group(1)
        if not is_slot and sep == "\\" and _C_ESCAPE.match(segment):
            continue
        words = segment.split()
        if not is_slot and len(words) > _MAX_SEGMENT_WORDS:
            continue
        # Test the whole segment AND every leading-word prefix: the charclass is
        # greedy, so an allowlisted root followed by prose ("Riot Commander) it
        # PASSES ...") arrives here as one long segment.
        if not is_slot and any(
            _is_allowed(" ".join(words[:cut])) for cut in range(len(words), 0, -1)
        ):
            continue
        line = _line_of(text, m.start(), base_line)
        key = (path, line, segment.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Finding(
                slot=-1,
                shape=SHAPE_STRUCTURAL,
                view="raw",
                source=source,
                path=path,
                line=line,
                status=status,
                severity=SEV_STRUCTURAL,
                literal=m.group(0),
                offset=m.start(),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Push range resolution
# ---------------------------------------------------------------------------
_ZERO = re.compile(r"^0+$")
_SHA = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


@dataclass
class RangeSpec:
    local_ref: str
    args: list


def _needs_whole_remote(line: str, have: Optional[Callable[[str], bool]]) -> bool:
    """True for a line resolve_push_range scans against the WHOLE remote."""
    parts = (line or "").split()
    if len(parts) < 4 or _ZERO.match(parts[1]):
        return False
    return bool(_ZERO.match(parts[3])) or (have is not None and not have(parts[3]))


def resolve_push_range(
    line: str,
    remote_name: str,
    have: Optional[Callable[[str], bool]] = None,
    advertised: Optional[Sequence[str]] = None,
) -> Optional[RangeSpec]:
    """One pre-push stdin line -> the rev-list arguments for what it publishes.

    ``<local_ref> <local_sha> <remote_ref> <remote_sha>``

    - local_sha all zeros  -> ref DELETION. Publishes nothing. Skip, and this is
      not an error; treating it as one blocks every branch cleanup.
    - remote_sha all zeros -> first push of this ref: everything not already on
      the remote.
    - both non-zero        -> what the remote does not have. This is also the
      correct answer for a FORCE push.
    - remote_sha not in the local object store -> treat as the zeros case. Scan
      MORE, never less; a sha we cannot resolve must not silently narrow the
      range to nothing.

    "Already on the remote" is what the remote ADVERTISES (S1, kit v19 parity):
    with ``advertised`` (the ls-remote shas present locally, see
    ``remote_advertised``) the two whole-remote cases exclude only those
    (``<sha> ^a ^b ...``). The local remote-tracking refs are a cache: after a
    branch is deleted on the remote, or the remote is recreated or rewritten,
    an unpruned clone still names commits the remote does not have, and
    ``--not --remotes`` let a new branch built on one publish it unscanned.
    ``advertised=None`` keeps that legacy form for callers that cannot reach
    the remote; every push gate passes it via ``resolve_push_ranges``.
    """
    parts = (line or "").split()
    if len(parts) < 4:
        return None
    local_ref, local_sha, _remote_ref, remote_sha = parts[:4]
    if _ZERO.match(local_sha):
        return None
    if _needs_whole_remote(line, have):
        if advertised is not None:
            return RangeSpec(local_ref, [local_sha, *("^" + s for s in advertised)])
        return RangeSpec(local_ref, [local_sha, "--not", f"--remotes={remote_name}"])
    return RangeSpec(local_ref, [local_sha, "--not", remote_sha])


def remote_advertised(root: Path, remote_name: str) -> list:
    """The shas ``git ls-remote <remote>`` advertises that exist locally.

    Sorted and unique; commits and tags only (an absent sha cannot be excluded:
    ``^<absent>`` makes rev-list fail). An ls-remote that fails raises
    GitFault, so a new ref is never silently scanned against the local
    remote-tracking refs instead (fail closed, as the kit's identity gate).
    """
    try:
        out = _git(
            root, ["ls-remote", "--", remote_name],
            env={"GIT_TERMINAL_PROMPT": "0"}, timeout=120,
        )
    except GitFault as exc:
        raise GitFault(
            "could not read the remote's advertised refs (git ls-remote); a new "
            f"ref is never scanned against local remote-tracking refs: {exc}"
        )
    shas = sorted({
        ln.split()[0] for ln in out.splitlines() if ln.split() and _SHA.match(ln.split()[0])
    })
    if not shas:
        return []
    check = _git(
        root, ["cat-file", "--batch-check=%(objectname) %(objecttype)"], "\n".join(shas) + "\n"
    )
    return sorted({
        bits[0] for bits in (ln.split() for ln in check.splitlines())
        if len(bits) == 2 and bits[1] in ("commit", "tag")
    })


def resolve_push_ranges(
    root: Path,
    ref_lines: Sequence[str],
    remote_name: str,
    have: Optional[Callable[[str], bool]] = None,
) -> list:
    """Every pre-push stdin line -> its RangeSpec (deletions dropped).

    The ONE range resolver for every push gate (this sweep and
    ``tools/credential_history_scan.py``). ls-remote is read once, and only
    when some line needs the whole-remote exclusion; GitFault propagates.
    """
    if have is None:
        def have(sha: str) -> bool:
            return _has_object(root, sha)
    advertised = None
    if any(_needs_whole_remote(ln, have) for ln in ref_lines):
        advertised = remote_advertised(root, remote_name)
    specs = []
    for line in ref_lines:
        spec = resolve_push_range(line, remote_name, have=have, advertised=advertised)
        if spec is not None:
            specs.append(spec)
    return specs


def stdin_revs(args: Sequence[str]) -> Optional[str]:
    """``git <cmd> --stdin`` input for a plain-rev list, else None.

    One argv word per advertised sha would overrun the Windows command-line cap
    on a remote with many refs, so a list of plain revs (``sha`` / ``^sha``) is
    fed on stdin. A list carrying an option (``--not``) stays on argv: git
    before 2.42 rejects options in --stdin mode.
    """
    if not args or any(a.startswith("-") for a in args):
        return None
    return "\n".join(args) + "\n"


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------
# Console-flash guard (tests/test_no_console_flash_scheduled_tools.py): this
# module is reachable by IMPORT from an unattended entry point, where a bare
# git.exe child allocates and flashes a console.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class GitFault(RuntimeError):
    pass


def _git(
    root: Path,
    args: Sequence[str],
    stdin_text: str = "",
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> str:
    try:
        # RM-830: core.quotepath off, so a non-ASCII PATH / DIFF-ADDED name
        # reaches the scan as itself, not C-quoted (an allowlist match on the
        # quoted text failed closed). Output is decoded UTF-8 below.
        proc = subprocess.run(
            ["git", "-C", str(root), "-c", "core.quotepath=false", *args],
            input=stdin_text.encode("utf-8") if stdin_text else None,
            capture_output=True,
            creationflags=_NO_WINDOW,
            env=dict(os.environ, **env) if env else None,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise GitFault("git " + " ".join(args[:2]) + f" timed out after {timeout}s")
    except OSError as exc:
        raise GitFault(f"git could not be invoked: {exc}")
    if proc.returncode != 0:
        raise GitFault(
            "git " + " ".join(args[:2]) + f" exited {proc.returncode}: "
            + proc.stderr.decode("utf-8", errors="replace")[:200]
        )
    return proc.stdout.decode("utf-8", errors="replace")


def _has_object(root: Path, sha: str) -> bool:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", sha + "^{commit}"],
            capture_output=True,
            creationflags=_NO_WINDOW,
        )
    except OSError:
        return False
    return proc.returncode == 0


@dataclass
class Blob:
    source: str
    path: str
    status: str
    text: str
    base_line: int = 1


def collect_push_blobs(root: Path, ref_lines: Sequence[str], remote_name: str, stats: ScanStats):
    """Three sources, because a content diff alone misses two of them."""
    shas: list = []
    for spec in resolve_push_ranges(root, ref_lines, remote_name):
        feed = stdin_revs(spec.args)
        if feed is not None:
            out = _git(root, ["rev-list", "--stdin"], feed)
        else:
            out = _git(root, ["rev-list", *spec.args])
        for sha in out.split():
            if sha not in shas:
                shas.append(sha)
    stats.commits = len(shas)
    if not shas:
        return []

    blobs: list = []
    stdin_text = "\n".join(shas) + "\n"

    # (3) COMMIT MESSAGES - published permanently, present in no diff.
    msg_out = _git(
        root, ["log", "--no-walk", "--stdin", "--no-patch", "--format=%x01%H%x02%B"], stdin_text
    )
    for chunk in msg_out.split("\x01"):
        if not chunk.strip():
            continue
        sha, _, body = chunk.partition("\x02")
        blobs.append(Blob("COMMIT-MSG", sha.strip()[:12], "MSG", body))

    # (2) PATHS including renames, and (1) added diff lines - as TWO calls.
    #
    # MEASURED, and the single-call version shipped silently broken for one
    # iteration: `git log --name-status -p` prints the name-status list and
    # SUPPRESSES the patch entirely. The combined form reports "0 file(s)" over
    # a real multi-commit push and reads exactly like a clean diff.
    name_out = _git(
        root,
        [
            "log", "--no-walk", "--stdin", "--format=%x01%H",
            "--diff-filter=ACMR", "--find-renames", "--name-status",
        ],
        stdin_text,
    )
    patch_out = _git(
        root,
        [
            "log", "--no-walk", "--stdin", "--format=%x01%H", "--unified=0",
            "--diff-filter=ACMR", "--find-renames", "-p",
        ],
        stdin_text,
    )
    blobs.extend(_parse_diff(name_out, stats))
    blobs.extend(_parse_diff(patch_out, stats))
    return blobs


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_diff(out: str, stats: ScanStats):
    blobs: list = []
    cur_path = ""
    cur_status = "M"
    pending: list = []
    next_line = 1

    def flush():
        nonlocal pending
        if pending and cur_path:
            text = "\n".join(t for _, t in pending)
            blobs.append(Blob("DIFF-ADDED", cur_path, cur_status, text, pending[0][0]))
        pending = []

    for raw in out.splitlines():
        if raw.startswith("\x01"):
            flush()
            cur_path = ""
            continue
        if raw and raw[0] in "AMCDTUX" and "\t" in raw:
            # name-status record; renames publish a NEW PATH with no content.
            bits = raw.split("\t")
            status = bits[0]
            for p in bits[1:]:
                if p.strip():
                    stats.paths += 1
                    blobs.append(Blob("PATH", p.strip(), status, p.strip()))
            continue
        if raw.startswith("R") and "\t" in raw:
            bits = raw.split("\t")
            for p in bits[1:]:
                if p.strip():
                    stats.paths += 1
                    blobs.append(Blob("PATH", p.strip(), bits[0], p.strip()))
            continue
        if raw.startswith("diff --git "):
            flush()
            tail = raw[len("diff --git ") :]
            cur_path = tail.split(" b/", 1)[-1] if " b/" in tail else tail
            cur_status = "M"
            stats.files += 1
            continue
        if raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
            stats.binary_blobs += 1
            continue
        m = _HUNK.match(raw)
        if m:
            flush()
            next_line = int(m.group(1))
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            body = raw[1:]
            if body.startswith("version https://git-lfs.github.com/spec/"):
                stats.lfs_pointers += 1
            pending.append((next_line, body))
            next_line += 1
            continue
    flush()
    return blobs


def _tree_blob_stream(root: Path, rels: Sequence[str], stats: ScanStats):
    """One file's text live at a time. RM-477's second half.

    Windowing `scan_text` bounds the cost of scanning ONE blob; it does nothing
    about holding every blob at once. This tree's tracked files decode to about
    640 MB of text - including several multi-megabyte LFS payloads, which are
    SMUDGED in the working copy and so are read at full size here no matter what
    the 133-byte pointer in the object store says. Materialising that list made
    the peak the whole tree before the first window was ever built.
    """
    for rel in rels:
        target = root / rel
        try:
            raw = target.read_bytes()
        except OSError:
            stats.unscanned_bytes += 0
            continue
        if b"\0" in raw[:8192]:
            stats.binary_blobs += 1
            stats.unscanned_bytes += len(raw)
            yield Blob("PATH", rel, "T", rel)
            continue
        text = raw.decode("utf-8", errors="replace")
        del raw
        stats.decode_failures += text.count(_REPLACEMENT)
        if text.startswith("version https://git-lfs.github.com/spec/"):
            stats.lfs_pointers += 1
        yield Blob("TREE", rel, "T", text)
        yield Blob("PATH", rel, "T", rel)


def iter_tree_blobs(root: Path, stats: ScanStats):
    """Tree-wide arm. git index first (ADR-015), never a fresh rglob.

    The index read and the ADR-015 non-vacuity check are EAGER while the file
    walk is lazy. Folded into the generator body, that check would not run until
    the first `next()` - which happens inside `_run_scan`, outside `main`'s
    fault handler - and a vacuous tree walk would surface as a traceback rather
    than as the FAULT verdict the ADR requires.
    """
    out = _git(root, ["ls-files", "-z"])
    rels = [p for p in out.split("\0") if p.strip()]
    if not rels:
        raise GitFault("git ls-files returned nothing - a vacuous tree walk")
    # RM-491: the hand-run tree arm is what CLAUDE.md tells a session to run on
    # NEW work, and new work is untracked until `git add`. An index-only
    # universe proved nothing about it. Untracked, NOT-ignored files join the
    # universe (`--exclude-standard` keeps gitignored runtime state out, which
    # is never pushed). The vacuity check above stays on the TRACKED set.
    others = _git(root, ["ls-files", "-z", "--others", "--exclude-standard"])
    untracked = [p for p in others.split("\0") if p.strip()]
    stats.untracked = len(untracked)
    rels = rels + untracked
    stats.files = len(rels)
    return _tree_blob_stream(root, rels, stats)


def collect_tree_blobs(root: Path, stats: ScanStats):
    """Eager wrapper, kept for callers that genuinely want the list. Every
    scanning caller should take `iter_tree_blobs` instead."""
    return list(iter_tree_blobs(root, stats))


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def render_report(
    findings: Sequence,
    stats: ScanStats,
    cfg: SweepConfig,
    known_ok: bool = False,
    bypassed: bool = False,
) -> str:
    """NEVER prints a matched literal.

    Hook stderr lands in CI logs and in pasted transcripts. A report that spells
    the name it caught does not stop the leak, it relocates it - into a place
    with a wider audience and no gate at all.
    """
    lines: list = []
    lines.append("=" * 72)
    lines.append(
        "SIBLING-NAME SWEEP: PUSH HALTED"
        if not bypassed
        else "SIBLING-NAME SWEEP: BYPASS ENGAGED - THIS WOULD HAVE HALTED"
    )
    lines.append("=" * 72)
    lines.append(mode_banner(cfg))
    lines.append("")
    lines.append(
        "Findings (literals are NEVER printed - use --explain N to resolve one "
        "on this machine):"
    )
    lines.append(
        "  idx  slot  severity     shape                     status  file:line"
    )
    for i, f in enumerate(findings):
        slot = "struct" if f.slot < 0 else f"#{f.slot}"
        flag = ""
        if f.path in KNOWN_EXCEPTIONS:
            flag = "  [KNOWN]"
        lines.append(
            f"  {i:<4} {slot:<5} {f.severity:<12} {f.shape:<25} "
            f"{f.status:<7} {f.path}:{f.line}{flag}"
        )
    known_hit = sorted({f.path for f in findings if f.path in KNOWN_EXCEPTIONS})
    if known_hit or known_ok:
        lines.append("")
        lines.append("KNOWN, NAMED, VISIBLE EXCEPTIONS (reported, never silently allowed):")
        for rel in known_hit or list(KNOWN_EXCEPTIONS):
            lines.append(f"  {rel}")
            lines.append(f"    reason: {KNOWN_EXCEPTIONS.get(rel, 'undeclared')}")
    lines.append("")
    lines.append("COVERAGE, so a clean verdict is not mistaken for a complete one:")
    lines.append(
        f"  scanned {stats.scanned_bytes} bytes over {stats.files} file(s), "
        f"{stats.paths} path record(s), {stats.commits} commit message(s)"
    )
    lines.append(
        f"  {stats.binary_blobs} binary/LFS blobs not content-scanned "
        f"({stats.unscanned_bytes} bytes)"
    )
    lines.append(
        f"  {stats.lfs_pointers} LFS pointer(s) scanned as text. A pointer is "
        "plain text and scans clean TRUTHFULLY, but the OBJECT it points at is "
        "never seen by this sweep. That is a real blind spot, stated rather "
        "than hidden."
    )
    lines.append(f"  {stats.decode_failures} undecodable character(s) counted as unscanned")
    lines.append("")
    lines.append("WHAT HAPPENS NOW:")
    lines.append("  The push is halted and is waiting on the operator.")
    lines.append("  It will NOT proceed on a timeout. Nothing was pushed.")
    lines.append("  LFS upload did not run, so no LFS object left this machine either.")
    lines.append("")
    lines.append("TO PROCEED:")
    lines.append(
        "  1. Resolve one finding on THIS machine (never paste the output):"
    )
    lines.append(
        "       python tools/sibling_name_sweep.py --scan-file <file> --explain <idx>"
    )
    lines.append(
        "       python tools/sibling_name_sweep.py --tree --explain <idx>"
    )
    lines.append("  2. Remove or redact the byte, amend the commit, push again.")
    lines.append(
        f"  3. Deliberate override: {BYPASS_ENV}=1 proceeds and appends the full "
        f"would-have-halted report to {bypass_log_display()}."
    )
    lines.append(
        "  Note plainly: `git push --no-verify` bypasses the WHOLE hook, this "
        "sweep and the LFS upload alike. Nothing here can prevent that, and "
        "pretending otherwise would be the more dangerous claim."
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def explain_finding(findings: Sequence, index: int) -> str:
    if index < 0 or index >= len(findings):
        return f"no finding at index {index}"
    f = findings[index]
    return (
        f"finding {index}: {f.path}:{f.line} ({f.shape}, view={f.view}, "
        f"source={f.source}, severity={f.severity})\n"
        f"  matched literal: {f.literal!r}\n"
        "  This output is for THIS MACHINE only. Do not paste it anywhere."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _run_scan(cfg: SweepConfig, blobs: Sequence, stats: ScanStats):
    needles = build_needles(cfg) if cfg.mode == MODE_ARMED else []
    if cfg.mode == MODE_ARMED:
        assert_non_vacuous(needles)
    findings: list = []
    for blob in blobs:
        stats.scanned_bytes += len(blob.text.encode("utf-8", errors="replace"))
        if needles:
            findings.extend(
                scan_text(
                    needles,
                    cfg.codes,
                    blob.text,
                    path=blob.path,
                    source=blob.source,
                    status=blob.status,
                    base_line=blob.base_line,
                )
            )
        findings.extend(
            structural_findings(
                blob.text,
                path=blob.path,
                source=blob.source,
                status=blob.status,
                base_line=blob.base_line,
                slot_names=cfg.names if cfg.mode == MODE_ARMED else (),
            )
        )
    dedup: dict = {}
    for f in findings:
        dedup.setdefault(f.key(), f)
    return sorted(dedup.values(), key=lambda f: (f.severity != SEV_RESOLUTION, f.path, f.line))


def _emit(text: str) -> None:
    sys.stderr.write(text + "\n")


def bypass_log_path() -> Path:
    """Where a BYPASS report goes: a non-empty ``RC_SIBLING_SWEEP_BYPASS_LOG``,
    else ``REPO_ROOT / BYPASS_LOG`` (RM-788)."""
    override = (os.environ.get(BYPASS_LOG_ENV) or "").strip()
    return Path(override) if override else REPO_ROOT / BYPASS_LOG


def bypass_log_display() -> str:
    """``bypass_log_path()`` as the operator-facing text names it (RM-812: it
    printed BYPASS_LOG even when the override sent the write elsewhere):
    relative to the checkout root when inside it - the unchanged default text -
    else the path itself."""
    path = bypass_log_path()
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _append_bypass_log(text: str) -> None:
    try:
        log_path = bypass_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        _emit("[sibling-sweep] BYPASS log could not be written.")


def _bypass_env_set() -> bool:
    return os.environ.get(BYPASS_ENV, "").strip() not in ("", "0", "false", "False")


# RM-688 run record - see the RUN_LOG block at the top of this file.
_HEX = re.compile(r"^[0-9a-f]{1,40}$")
_HEX_FIELD = re.compile(r"^[0-9a-f]+$")


def run_log_path() -> Path:
    """Where this run's record goes. Never raises.

    ``RC_SIBLING_SWEEP_RUN_LOG`` wins when non-empty; otherwise the MAIN
    working tree's ``ops/runtime`` when ``REPO_ROOT`` is a linked worktree,
    else ``REPO_ROOT``'s own.
    """
    try:
        override = (os.environ.get(RUN_LOG_ENV) or "").strip()
        if override:
            return Path(override)
        return (main_working_tree(REPO_ROOT) or REPO_ROOT) / RUN_LOG
    except Exception:  # noqa: BLE001 - a record path must never break the gate
        return REPO_ROOT / RUN_LOG


def _run_record_failed() -> None:
    try:
        _emit("[sibling-sweep] run record could not be written.")
    except Exception:  # noqa: BLE001 - a dead stderr must not change the exit code
        pass


def _append_run_record(record: dict) -> None:
    """ONE append-mode write of one ASCII JSON line. Never raises."""
    try:
        line = json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        data = (line + "\n").encode("ascii")
        path = run_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
        fd = os.open(str(path), flags, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
    except Exception:  # noqa: BLE001 - the record is advisory; the exit code is the gate
        _run_record_failed()


@dataclass
class _RunContext:
    """What one sweep run reached. Counts and enums only - never text."""

    arm: str
    explain: bool
    cfg_mode: Optional[str] = None
    hits: int = 0
    stats: Optional[ScanStats] = None
    ref_lines: list = field(default_factory=list)
    bypassed: bool = False
    # RM-799: how many config keys were malformed (a count, never a key name).
    malformed: int = 0


def _hex_or_none(value: str) -> Optional[str]:
    return value if _HEX.match(value or "") else None


def _run_range(ref_lines: Sequence[str]) -> list:
    """``<remote_sha[:12]>..<local_sha[:12]>`` per hex-shaped ref line, capped.

    Only the 2nd and 4th fields are read; the ref NAMES never are.
    """
    out: list = []
    for line in ref_lines:
        parts = (line or "").split()
        if len(parts) < 4:
            continue
        local_sha, remote_sha = parts[1], parts[3]
        if not (_HEX_FIELD.match(local_sha) and _HEX_FIELD.match(remote_sha)):
            continue
        left, right = _hex_or_none(remote_sha[:12]), _hex_or_none(local_sha[:12])
        if left is None or right is None:
            continue
        out.append(f"{left}..{right}")
        if len(out) >= RUN_RANGE_MAX:
            break
    return out


def _run_head() -> Optional[str]:
    try:
        return _hex_or_none(_git(REPO_ROOT, ["rev-parse", "HEAD"]).strip()[:12])
    except Exception:  # noqa: BLE001 - no HEAD (or no git) records null, never fails
        return None


def _run_verdict(ctx: _RunContext, rc: Optional[int]) -> str:
    if rc is None or rc == EXIT_FAULT:
        return "fault"
    if ctx.bypassed:
        return "bypass"
    if ctx.explain:
        return "hit" if ctx.hits else "clean"
    if rc == EXIT_CLEAN:
        return "clean"
    if rc == EXIT_HALT:
        return "hit"
    return "fault"


def _record_run(ctx: _RunContext, rc: Optional[int]) -> None:
    """Build and append this run's record. Never raises."""
    try:
        stats = ctx.stats or ScanStats()
        record = {
            "v": RUN_RECORD_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "arm": ctx.arm,
            "explain": bool(ctx.explain),
            "cfg": ctx.cfg_mode if ctx.cfg_mode in (MODE_ARMED, MODE_DEGRADED, MODE_FAULT) else None,
            "verdict": _run_verdict(ctx, rc),
            "exit": rc if isinstance(rc, int) else None,
            "hits": int(ctx.hits),
            "commits": int(stats.commits),
            "files": int(stats.files),
            "bytes": int(stats.scanned_bytes),
            "range": _run_range(ctx.ref_lines) if ctx.arm == "pre-push" else [],
            "head": _run_head(),
            "worktree": main_working_tree(REPO_ROOT) is not None,
            "bypass_env": _bypass_env_set(),
            "malformed": int(ctx.malformed),
        }
    except Exception:  # noqa: BLE001 - the record is advisory; the exit code is the gate
        _run_record_failed()
        return
    _append_run_record(record)


class _UsageParser(argparse.ArgumentParser):
    """An ArgumentParser whose argument errors exit EXIT_USAGE, not 2.

    argparse's default failure code is 2, and 2 here means "sibling-identifying
    bytes are in this push". Left alone, a mistyped flag is indistinguishable
    from a leak in any log or script that reads the exit status - the tool's own
    usage check already returns 1, so only argparse's default was aliased. The
    exit-code contract is that the gate-caught-something code never collapses
    with anything else; fail-closed behaviour is unchanged either way, because a
    usage error still runs no scan and still refuses to report clean.
    """

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        _emit(f"[sibling-sweep] usage error: {message}")
        sys.exit(EXIT_USAGE)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _UsageParser(
        prog="sibling_name_sweep",
        description="RM-399 sibling-name sweep (pre-push gate).",
        add_help=True,
    )
    parser.add_argument("--pre-push", nargs="*", metavar="ARG",
                        help="pre-push mode: remote name (and url); refs are read from stdin")
    parser.add_argument("--tree", action="store_true", help="tree-wide arm over the git index")
    parser.add_argument("--scan-file", help="scan one file (test/diagnostic arm)")
    parser.add_argument("--config-root", help="override the root used to find the per-host config")
    parser.add_argument("--explain", type=int, help="resolve one finding to its literal, locally")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not (args.pre_push is not None or args.tree or args.scan_file):
        parser.print_usage(sys.stderr)
        _emit("[sibling-sweep] usage error: pick --pre-push, --tree or --scan-file.")
        return EXIT_USAGE

    # RM-688: a usage error above is not a sweep run and is not recorded. Every
    # run past this point is, including one an unexpected exception ends (that
    # exception still propagates unchanged; the record says verdict "fault",
    # exit null). The arm mirrors the blob-source precedence in `_sweep`.
    #
    # `_sweep` is NESTED in `main` on purpose: it is the post-parse body, and
    # tests/test_sibling_name_sweep.py guards that `main`'s own source walks the
    # tree arm LAZILY (RM-477), so the body has to stay inside `main`.
    arm = "scan-file" if args.scan_file else ("tree" if args.tree else "pre-push")
    ctx = _RunContext(arm=arm, explain=args.explain is not None)

    def _sweep() -> int:
        """The post-parse body. Same exit codes, same stderr as before RM-688."""
        root = Path(args.config_root) if args.config_root else REPO_ROOT
        cfg = load_config(root=root)
        ctx.cfg_mode = cfg.mode
        ctx.malformed = len(cfg.malformed)
        stats = ScanStats()
        ctx.stats = stats

        if cfg.mode == MODE_FAULT:
            _emit(mode_banner(cfg))
            _emit("[sibling-sweep] exit 3 (FAULT) - the gate could NOT run. This is "
                  "not a clean verdict and must not be read as one.")
            return EXIT_FAULT

        _emit(mode_banner(cfg))

        bypass = _bypass_env_set()

        # A DEGRADED run on the PUSH path is not a clean verdict, so it must not
        # exit like one. Scoped to --pre-push: CI runs the tree arm on a runner
        # with no config and relies on DEGRADED passing there.
        if args.pre_push is not None and cfg.mode == MODE_DEGRADED:
            notice = (
                "[sibling-sweep] PUSH HALTED - DEGRADED on the pre-push path: the "
                "per-host config was found neither in this checkout nor in the main "
                "working tree, so sibling-name matching did NOT run. Restore "
                "ops/moon_sync_repos.json in the main working tree or set "
                f"RC_MOON_SYNC_REPOS to arm it. Deliberate override: {BYPASS_ENV}=1 "
                f"proceeds and appends this notice to {bypass_log_display()}."
            )
            _emit(notice)
            if not bypass:
                return EXIT_FAULT
            ctx.bypassed = True
            _append_bypass_log(notice)
            _emit("[sibling-sweep] BYPASS engaged on a DEGRADED push - proceeding "
                  "with the structural arm only.")

        try:
            if args.scan_file:
                target = Path(args.scan_file)
                raw = target.read_bytes()
                text = raw.decode("utf-8", errors="replace")
                stats.decode_failures += text.count(_REPLACEMENT)
                stats.files = 1
                stats.diff_nonempty = bool(raw)
                blobs = [Blob("FILE", target.name, "A", text)]
            elif args.tree:
                # Lazy on purpose (RM-477): `bool()` on a generator proves nothing,
                # so the non-vacuity claim rests on the eager ls-files check inside
                # `iter_tree_blobs`, which has already raised if the index is empty.
                blobs = iter_tree_blobs(REPO_ROOT, stats)
                stats.diff_nonempty = True
            else:
                remote_name = (args.pre_push or ["origin"])[0] or "origin"
                ref_lines = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
                ctx.ref_lines = ref_lines
                blobs = collect_push_blobs(REPO_ROOT, ref_lines, remote_name, stats)
                stats.diff_nonempty = bool(blobs)
        except GitFault as exc:
            _emit(f"[sibling-sweep] FAULT - {exc}")
            return EXIT_FAULT
        except OSError as exc:
            _emit(f"[sibling-sweep] FAULT - {exc}")
            return EXIT_FAULT

        # The tree arm's blob source is now a GENERATOR, so its faults surface HERE
        # rather than above; `ChunkGuardExceeded` joins them because a scan that
        # cannot justify its own coverage must fail closed, never report clean.
        try:
            findings = _run_scan(cfg, blobs, stats)
            ctx.hits = len(findings)
        except ChunkGuardExceeded as exc:
            _emit(f"[sibling-sweep] FAULT - {exc}")
            return EXIT_FAULT
        except GitFault as exc:
            _emit(f"[sibling-sweep] FAULT - {exc}")
            return EXIT_FAULT
        except OSError as exc:
            _emit(f"[sibling-sweep] FAULT - {exc}")
            return EXIT_FAULT

        # Anti-vacuity: a non-empty diff that scanned zero bytes is a broken guard,
        # not a clean push.
        if stats.diff_nonempty and stats.scanned_bytes <= 0:
            _emit("[sibling-sweep] FAULT - a non-empty push scanned ZERO bytes. An "
                  "empty enumeration is never a clean verdict (ADR-015).")
            return EXIT_FAULT

        if args.explain is not None:
            _emit(explain_finding(findings, args.explain))
            return EXIT_CLEAN if not findings else EXIT_HALT

        if not findings:
            _emit(
                f"[sibling-sweep] clean: {stats.scanned_bytes} bytes, "
                f"{stats.files} file(s) ({stats.untracked} untracked), "
                f"{stats.commits} commit message(s), "
                f"{stats.binary_blobs} binary/LFS blobs not content-scanned."
            )
            return EXIT_CLEAN

        report = render_report(findings, stats, cfg, bypassed=bypass)
        _emit(report)
        if bypass:
            ctx.bypassed = True
            _append_bypass_log(report)
            _emit("[sibling-sweep] BYPASS engaged - proceeding anyway.")
            return EXIT_CLEAN
        return EXIT_HALT

    rc: Optional[int] = None
    try:
        rc = _sweep()
        return rc
    finally:
        _record_run(ctx, rc)


if __name__ == "__main__":
    sys.exit(main())
