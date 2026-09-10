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

TWO ARMS, AND WHY THERE ARE TWO
-------------------------------
1. The NEEDLE arm matches loaded names. It is the precise arm, and it is inert
   without the per-host config - which a fresh clone and CI both lack.
2. The STRUCTURAL arm is config-free: it extracts drive-rooted first path
   segments and subtracts an allowlist. It therefore still catches "a Windows
   path to a project nobody recognises" in a fresh clone. It runs in DEGRADED
   mode too, which is the whole reason DEGRADED is not silent.

THREE MODES
-----------
ARMED     - config parsed, needles loaded, both arms run.
DEGRADED  - no override AND no config file. The needle arm proves NOTHING and
            says so on EVERY push. The structural arm still runs.
FAULT     - config present but unparseable, zero usable paths, a failed git
            invocation, or zero bytes scanned against a non-empty diff. Exit 3.
            FAULT is never collapsed into HALT: "the gate fired" and "the gate
            could not run" are different facts and must stay different.

WHY THREE SOURCES ARE SCANNED
-----------------------------
A content diff alone misses two publication routes that were both measured here:
a RENAME publishes a new path with no content change, and a name in a COMMIT
SUBJECT is published permanently while appearing in no diff at all.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Mapping, NoReturn, Optional, Sequence

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

# U+FFFD, written as an escape on purpose: this file is 7-bit ASCII by repo rule.
_REPLACEMENT = chr(0xFFFD)

BYPASS_ENV = "RC_SIBLING_SWEEP_BYPASS"
BYPASS_LOG = Path("ops") / "runtime" / "sibling_sweep_bypass.log"

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# KNOWN OPEN HIT.
#
# Declared, named and visible - NOT a silent allowlist entry, and never excused
# as noise. It is a real hit whose remediation is not RC's to make alone.
# ---------------------------------------------------------------------------
KNOWN_EXCEPTIONS = {
    "tests/test_loop_concurrency.py": (
        "Carries a sibling name in the P4 split form (wrapped across a comment "
        "continuation). This file is BYTE-PINNED across the participating "
        "repositories by SHARED_SHA256, so editing it here breaks the pin "
        "everywhere. Remediation is a JOINT re-pin routed through the "
        "coordination step, not a unilateral edit. Reported on every run so it "
        "stays visible until that lands."
    ),
}


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


def config_from_parts(repos: Iterable[str], participants: Mapping[str, str]) -> SweepConfig:
    """Build an ARMED config from already-loaded parts. Used by tests and by
    the env-override path, which carries paths only and therefore no codes."""
    names: list[str] = []
    for raw in repos:
        leaf = _leaf(raw)
        if leaf and leaf not in names:
            names.append(leaf)
    for raw in (participants or {}).values():
        leaf = _leaf(raw)
        if leaf and leaf not in names:
            names.append(leaf)
    codes = tuple(str(c).strip() for c in (participants or {}) if str(c).strip())
    return SweepConfig(
        mode=MODE_ARMED if names else MODE_FAULT,
        names=tuple(names),
        codes=codes,
        participants=dict(participants or {}),
        source="parts",
        detail="",
    )


def load_config(
    root: Optional[Path] = None, env: Optional[Mapping[str, str]] = None
) -> SweepConfig:
    """Resolve needles, mirroring ``tools/moon_sync_poller.py`` ``_load_repo_roots``.

    Extended in exactly one way: the ``participants`` map is read when present,
    because a CODE next to a NAME publishes the resolution and must outrank a
    bare name hit. The poller ignores that key, so the two readers stay
    compatible with the same gitignored file.
    """
    base = Path(root) if root is not None else REPO_ROOT
    environ = os.environ if env is None else env

    raw = (environ.get("RC_MOON_SYNC_REPOS") or "").strip()
    if raw:
        paths = [p.strip() for p in raw.split(os.pathsep) if p.strip()]
        cfg = config_from_parts(paths, {})
        cfg.source = "RC_MOON_SYNC_REPOS"
        if cfg.mode == MODE_FAULT:
            cfg.detail = "RC_MOON_SYNC_REPOS is set but yields zero usable names"
        return cfg

    config_path = base / "ops" / "moon_sync_repos.json"
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

    repos = [str(p) for p in (blob.get("repos") or []) if str(p).strip()]
    participants = {
        str(k): str(v) for k, v in (blob.get("participants") or {}).items() if str(k).strip()
    }
    cfg = config_from_parts(repos, participants)
    cfg.source = str(config_path)
    if cfg.mode == MODE_FAULT:
        cfg.detail = "config parsed but yields zero usable sibling names"
    return cfg


def mode_banner(cfg: SweepConfig) -> str:
    if cfg.mode == MODE_ARMED:
        return (
            f"[sibling-sweep] ARMED - {len(cfg.names)} name slot(s), "
            f"{len(cfg.codes)} counterparty code(s) loaded from per-host config."
        )
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


def build_needles(cfg: SweepConfig) -> list:
    needles: list = []
    for slot, name in enumerate(cfg.names):
        variants = _variant_fragments(name)
        tight = "".join(re.escape(t) for t in re.split(r"\s+", name.strip()) if t)
        shapes: list = []
        for family, frag in variants.items():
            # S1 + S2: drive letter, one or two separators, either slash.
            shapes.append(
                CompiledShape(
                    f"{SHAPE_DRIVE}/{family}",
                    VIEW_SPACE,
                    re.compile(
                        r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]{1,2}" + frag + _RIGHT_EDGE,
                        re.I,
                    ),
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
            # S3: the spelling anywhere in prose.
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
        shapes.append(
            CompiledShape(f"{SHAPE_BARE}/CONCAT", VIEW_TIGHT, re.compile(tight, re.I))
        )
        shapes.append(
            CompiledShape(
                f"{SHAPE_DRIVE}/CONCAT",
                VIEW_TIGHT,
                re.compile(r"(?<![A-Za-z0-9_])[A-Za-z]:[\\/]{1,2}" + tight, re.I),
            )
        )
        needles.append(
            Needle(slot=slot, name=name, variants=variants, patterns=tuple(shapes))
        )
    return needles


def assert_non_vacuous(needles: Sequence) -> None:
    """ADR-015 anchor. An empty enumeration and a clean tree are the same
    verdict to every consumer, so refuse to be silently vacuous."""
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


# ---------------------------------------------------------------------------
# Haystack normalisation (S6)
# ---------------------------------------------------------------------------
_CONT_PREFIX = "#/*>-"


def _strip_continuations(text: str):
    """Drop leading whitespace plus a comment-continuation prefix run from every
    line after the first. Returns (text, index map back into the original)."""
    chars: list = []
    idxs: list = []
    pos = 0
    first = True
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


def build_views(text: str) -> dict:
    stripped, idxs = _strip_continuations(text)
    space_text, space_idx = _collapse(stripped, idxs, drop_all=False)
    tight_text, tight_idx = _collapse(stripped, idxs, drop_all=True)
    return {
        VIEW_SPACE: (space_text, space_idx),
        VIEW_TIGHT: (tight_text, tight_idx),
    }


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
    """Run the NEEDLE arm over one blob. Never matches a code on its own."""
    if not text or not needles:
        return []
    views = build_views(text)
    code_res = [
        re.compile(_LEFT_EDGE + re.escape(c) + _RIGHT_EDGE) for c in codes if c
    ]
    best: dict = {}
    for needle in needles:
        for shape in needle.patterns:
            view_text, view_idx = views[shape.view]
            for m in shape.regex.finditer(view_text):
                if m.start() >= len(view_idx):
                    continue
                orig_start = view_idx[m.start()]
                end_i = min(m.end(), len(view_idx)) - 1
                orig_end = view_idx[end_i] + 1 if end_i >= 0 else orig_start
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
                    line=_line_of(text, orig_start, base_line),
                    status=status,
                    severity=severity,
                    literal=text[orig_start:orig_end],
                    offset=orig_start,
                )
                key = (path, source, finding.line, needle.slot)
                prior = best.get(key)
                if prior is None or (
                    _rank(shape.shape),
                    finding.severity == SEV_RESOLUTION,
                ) > (_rank(prior.shape), prior.severity == SEV_RESOLUTION):
                    best[key] = finding
    return sorted(best.values(), key=lambda f: (f.path, f.line, f.slot))


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


def structural_findings(
    text: str, *, path: str, source: str, status: str = "M", base_line: int = 1
) -> list:
    """Config-free arm: a drive-rooted first path segment that is not on the
    allowlist. This is what keeps the gate non-inert in a fresh clone and in CI.
    """
    out: list = []
    seen: set = set()
    for m in STRUCTURAL_RE.finditer(text or ""):
        segment = _trim(m.group(2))
        if not segment:
            continue
        # The `\n`-in-a-string class, rejected by name rather than by widening.
        # Only a SINGLE backslash can be a C-style escape, so the doubled form
        # (a genuine escaped Windows path) is deliberately left alone.
        sep = _SEP_RE.match(m.group(0)).group(1)
        if sep == "\\" and _C_ESCAPE.match(segment):
            continue
        words = segment.split()
        if len(words) > _MAX_SEGMENT_WORDS:
            continue
        # Test the whole segment AND every leading-word prefix: the charclass is
        # greedy, so an allowlisted root followed by prose ("Riot Commander) it
        # PASSES ...") arrives here as one long segment.
        if any(_is_allowed(" ".join(words[:cut])) for cut in range(len(words), 0, -1)):
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


@dataclass
class RangeSpec:
    local_ref: str
    args: list


def resolve_push_range(
    line: str, remote_name: str, have: Optional[Callable[[str], bool]] = None
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
    """
    parts = (line or "").split()
    if len(parts) < 4:
        return None
    local_ref, local_sha, _remote_ref, remote_sha = parts[:4]
    if _ZERO.match(local_sha):
        return None
    if _ZERO.match(remote_sha) or (have is not None and not have(remote_sha)):
        return RangeSpec(local_ref, [local_sha, "--not", f"--remotes={remote_name}"])
    return RangeSpec(local_ref, [local_sha, "--not", remote_sha])


# ---------------------------------------------------------------------------
# Git plumbing
# ---------------------------------------------------------------------------
class GitFault(RuntimeError):
    pass


def _git(root: Path, args: Sequence[str], stdin_text: str = "") -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            input=stdin_text.encode("utf-8") if stdin_text else None,
            capture_output=True,
        )
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
    for line in ref_lines:
        spec = resolve_push_range(line, remote_name, have=lambda s: _has_object(root, s))
        if spec is None:
            continue
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


def collect_tree_blobs(root: Path, stats: ScanStats):
    """Tree-wide arm. git index first (ADR-015), never a fresh rglob."""
    out = _git(root, ["ls-files", "-z"])
    rels = [p for p in out.split("\0") if p.strip()]
    if not rels:
        raise GitFault("git ls-files returned nothing - a vacuous tree walk")
    blobs: list = []
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
            blobs.append(Blob("PATH", rel, "T", rel))
            continue
        text = raw.decode("utf-8", errors="replace")
        stats.decode_failures += text.count(_REPLACEMENT)
        if text.startswith("version https://git-lfs.github.com/spec/"):
            stats.lfs_pointers += 1
        blobs.append(Blob("TREE", rel, "T", text))
        blobs.append(Blob("PATH", rel, "T", rel))
    stats.files = len(rels)
    return blobs


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
        f"would-have-halted report to {BYPASS_LOG.as_posix()}."
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
            )
        )
    dedup: dict = {}
    for f in findings:
        dedup.setdefault(f.key(), f)
    return sorted(dedup.values(), key=lambda f: (f.severity != SEV_RESOLUTION, f.path, f.line))


def _emit(text: str) -> None:
    sys.stderr.write(text + "\n")


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

    root = Path(args.config_root) if args.config_root else REPO_ROOT
    cfg = load_config(root=root)
    stats = ScanStats()

    if cfg.mode == MODE_FAULT:
        _emit(mode_banner(cfg))
        _emit("[sibling-sweep] exit 3 (FAULT) - the gate could NOT run. This is "
              "not a clean verdict and must not be read as one.")
        return EXIT_FAULT

    _emit(mode_banner(cfg))

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
            blobs = collect_tree_blobs(REPO_ROOT, stats)
            stats.diff_nonempty = bool(blobs)
        else:
            remote_name = (args.pre_push or ["origin"])[0] or "origin"
            ref_lines = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
            blobs = collect_push_blobs(REPO_ROOT, ref_lines, remote_name, stats)
            stats.diff_nonempty = bool(blobs)
    except GitFault as exc:
        _emit(f"[sibling-sweep] FAULT - {exc}")
        return EXIT_FAULT
    except OSError as exc:
        _emit(f"[sibling-sweep] FAULT - {exc}")
        return EXIT_FAULT

    findings = _run_scan(cfg, blobs, stats)

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
            f"{stats.files} file(s), {stats.commits} commit message(s), "
            f"{stats.binary_blobs} binary/LFS blobs not content-scanned."
        )
        return EXIT_CLEAN

    bypass = os.environ.get(BYPASS_ENV, "").strip() not in ("", "0", "false", "False")
    report = render_report(findings, stats, cfg, bypassed=bypass)
    _emit(report)
    if bypass:
        try:
            log_path = REPO_ROOT / BYPASS_LOG
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(report + "\n")
        except OSError:
            _emit("[sibling-sweep] BYPASS log could not be written.")
        _emit("[sibling-sweep] BYPASS engaged - proceeding anyway.")
        return EXIT_CLEAN
    return EXIT_HALT


if __name__ == "__main__":
    sys.exit(main())
