#!/usr/bin/env python3
"""Outbound delivery reciprocity check for the cross-repo inbox channel.

THE DEFECT THIS EXISTS FOR
--------------------------
Measured in a sibling carrier tree on 2026-09-12: SEVEN outbound notes written
over two days reached ZERO recipients. They sat in the sender's OWN
``moon_sync_inbox/`` and were never copied anywhere - four recipient inboxes,
zero copies each. The sender's own tooling reported them as handled the whole
time, because on this channel the watcher classifies by FILENAME, and a
``from-<SELF>`` prefix in the name makes a note look outbound and answered from
the sender's side. Under this fleet's charter SILENCE READS AS DISSENT, so for
two days that sender's positions - including a measured answer to a direct
request - were being counted by four counterparties as refusals to engage.

**The generalisable root cause: a note written into your own inbox directory is
indistinguishable from a note you sent.** Nothing in the channel's design
separates "authored" from "delivered", so the two collapse, and the collapse is
silent in the direction that costs the most.

The carrier asked RC to run the check on ITSELF rather than take their word for
it. This tool is that check, and it answers exactly one question:

    for every note this repo has authored as outbound, does a copy exist in the
    recipient's inbox?

FOUR PROPERTIES, EACH LOAD-BEARING
----------------------------------
1. **THE FILENAME IS NOT THE EVIDENCE.** The whole defect is a name that lied
   about delivery, so a copy is scored on a sha256 of its CONTENT. A recipient
   holding the expected name over different bytes - a truncated write, a stale
   revision, an edit in place - scores ``NAME_ONLY``, which is not delivery. A
   name-only check here would reproduce the very error being audited.

2. **DEGRADE HONESTLY.** A sibling root that is absent, unreadable or simply not
   configured is UNKNOWN. Never "delivered", never "missing". A false MISSING on
   this channel is as damaging as a missed real one: it accuses a counterparty of
   dropping mail that in fact was never sent, and an accusation is expensive to
   withdraw. When NO slot is readable, every note is UNKNOWN and the run
   concludes nothing at all - because with nothing to compare against, a stranded
   note and a perfectly delivered one look identical.

3. **AN EMPTY UNIVERSE IS NOT A CLEAN BILL OF HEALTH.** Zero authored notes
   reports as ``EMPTY`` with its own exit code, and every rendered summary
   carries the DENOMINATOR - "0 undelivered out of N checked". This repo's
   standing rule is that an empty enumeration satisfying an assertion is how a
   guard turns silently always-green; a delivery auditor that reports "all clear"
   when it found nothing to audit is that failure wearing a badge.

4. **READ-ONLY ACROSS THE BOUNDARY.** This tool READS a sibling inbox and writes,
   creates, deletes and locks NOTHING outside this repository root. That is a
   standing halt boundary in ``CLAUDE.md`` and it binds this tool permanently.
   It is pinned at the syscall by an audit-hook test, not by inspection.

WHY REACH IS REPORTED BUT A SHORTFALL IS NOT A FAILURE
------------------------------------------------------
Not every note is a broadcast. A targeted reply legitimately has a fan-out of
one, and flagging that as undelivered would bury the real zero-reach notes under
noise until nobody reads the report - which is how the original defect survived.
So the FAILING condition is reach ZERO against at least one readable recipient,
and the reach histogram is carried alongside it so a broadcast that fell short is
still visible to a human reader without being asserted on.

THE BLIND SPOT, NAMED RATHER THAN GLOSSED
-----------------------------------------
MEASURED here 2026-09-12: this repo keeps NO local copy of its outbound mail.
All 87 notes it has authored on the channel were observed only in recipient
inboxes; zero carry ``in_local``, and this tree has neither a ``from-<SELF>``
entry in its own inbox nor a staging directory. That is a stronger position than
the carrier's - the defect they measured NEEDS a local copy to strand, and there
is nowhere here for one to sit - but it has a cost that must not be glossed:

    **a note authored here, delivered to nobody, and not kept, leaves no trace
    anywhere, and this tool cannot see it.**

So the honest claim after a clean run is "no authored note is stranded in this
tree, and every authored note that left a trace reached a recipient", never "no
outbound note was ever lost". The second sentence is not provable from this side
of the channel; it needs the recipients' own accounting. Reported this way on
purpose, because the failure being audited is precisely a report that was
comforting and wrong - and a tool whose green light overstates what it checked
is the same defect one layer up.

OUTPUT IS SAFE TO PASTE
-----------------------
This repository is PUBLIC and a sibling-name sweep gates every push. Following
the precedent set by ``tools/sibling_name_sweep.py``, this tool contains NO
sibling literal - roots are loaded at run time from the gitignored per-host
config - and its report prints SLOT INDICES and CONTENT DIGESTS, never a
configured path. It withholds note FILENAMES too unless ``--names`` is passed:
a note's slug is free text its author chose, so it is not categorically safe
merely because this repo wrote it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

INBOX_DIRNAME = "moon_sync_inbox"
CONFIG_RELATIVE = Path("ops") / "moon_sync_repos.json"
REPOS_ENV = "RC_MOON_SYNC_REPOS"
SELF_CODE_ENV = "RC_OUTBOUND_SELF_CODE"

# This repo's own counterparty code on the channel. NOT a sibling name - it is
# how THIS tree signs its outbound mail, and it was established by probing the
# notes on disk rather than inferred from prose: sibling inboxes carry dozens of
# `-from-RC-` entries, and a reply in this repo's own inbox cites
# `...-from-RC-port-block-reservation.md` as the note it answers. Overridable,
# because a code is a convention and conventions get renamed.
DEFAULT_SELF_CODE = "RC"

EXIT_CLEAN = 0
EXIT_UNDELIVERED = 2
EXIT_INCONCLUSIVE = 3

STATUS_DELIVERED = "DELIVERED"
STATUS_UNDELIVERED = "UNDELIVERED"
STATUS_NAME_ONLY = "NAME_ONLY"
STATUS_ABSENT = "ABSENT"
STATUS_UNKNOWN = "UNKNOWN"

VERDICT_CLEAN = "CLEAN"
VERDICT_UNDELIVERED = "UNDELIVERED"
VERDICT_EMPTY = "EMPTY"
VERDICT_UNKNOWN = "UNKNOWN"

# The authorship grammar, read off the files on disk rather than inferred from
# prose. Three real shapes occur in this tree:
#   2026-09-06-1702-from-RC-topic.md   a dated note
#   from-RC-verbatim/                  a directory payload
#   winmutex.py.from-lw                a single lifted file, code as a SUFFIX
# so the code may be preceded by a hyphen, a dot, or the start of the name, and
# it is compared case-insensitively because the suffix form is lower-cased.
_AUTHOR_RE = re.compile(r"(?:^|[-.])from-(?P<code>[A-Za-z0-9]+)", re.IGNORECASE)

# `_`-prefixed entries are STAGING. Every watcher on this channel skips them by
# construction (see `tools/rc_facts.py` `_inbox_entries`), which cuts both ways:
# a note parked in a RECIPIENT's staging directory has not been delivered to
# them - their watcher will never surface it - while a note in the SENDER's own
# staging is exactly the population the original defect hid in, so it belongs in
# the universe.
_STAGING_PREFIX = "_"


# ------------------------------------------------------------------ digests


def _file_digest(path: Path) -> str:
    """sha256 of one file's bytes, or a stable marker if it cannot be read.

    An unreadable file MOVES the digest rather than vanishing from it. If a read
    error contributed nothing, a payload that became unreadable would key
    identically to the one already delivered - the same reasoning
    ``tools/rc_facts.py`` ``_file_digest`` records, kept deliberately consistent
    with it so the two tools agree about what "the same note" means.
    """
    h = hashlib.sha256()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError as exc:
        return f"UNREADABLE:{type(exc).__name__}"
    return h.hexdigest()


def _dir_digest(path: Path) -> str:
    """One digest over a whole directory payload: every relative path and every
    file's own digest, in sorted order.

    A directory drop is ONE unit of mail, not N - the unit a reader acts on is
    the payload. Folding the relative paths in as well as the bytes means a
    payload that GROWS, or that is delivered with a file renamed, is not
    silently equal to the one already sent.
    """
    h = hashlib.sha256()
    try:
        members = sorted(p for p in path.rglob("*") if p.is_file())
    except OSError as exc:
        return f"UNREADABLE:{type(exc).__name__}"
    for member in members:
        try:
            rel = member.relative_to(path).as_posix()
        except ValueError:  # pragma: no cover - rglob cannot produce this
            continue
        h.update(rel.encode("utf-8", "surrogateescape"))
        h.update(b"\0")
        h.update(_file_digest(member).encode("ascii"))
        h.update(b"\n")
    return h.hexdigest()


def entry_digest(path: Path) -> str:
    """Content identity of one inbox entry, file or directory payload alike."""
    if path.is_dir():
        return _dir_digest(path)
    return _file_digest(path)


# ------------------------------------------------------------------ grammar


def author_code(name: str) -> Optional[str]:
    """The counterparty code a note name claims as its author, or None.

    A CLAIM, never a fact - which is the entire point of this module. The name
    is what the channel's watchers classify on and it is what lied in the
    measured defect, so nothing downstream of here treats it as evidence of
    anything except intent.
    """
    m = _AUTHOR_RE.search(name)
    return m.group("code") if m else None


def is_authored_by(name: str, self_code: str) -> bool:
    code = author_code(name)
    return bool(code) and code.casefold() == self_code.casefold()


# ------------------------------------------------------------------- config


def _split_roots(raw: str) -> list[str]:
    """Split the env override the way ``tools/sibling_name_sweep.py`` does.

    DELIBERATELY not a bare ``raw.split(os.pathsep)``. That is correct on
    Windows, where ``os.pathsep`` is ``;``, and it cuts every drive-letter path
    in half on Linux, where it is ``:`` - a defect that was measured in CI for
    the sweep. Same config, same failure available here, so the same handling.
    """
    try:
        from tools.sibling_name_sweep import split_repo_list
    except ImportError:  # pragma: no cover - only if the sweep is removed
        return [p.strip() for p in raw.split(os.pathsep) if p.strip()]
    return split_repo_list(raw)


def load_sibling_roots(
    root: Optional[Path] = None, env: Optional[Mapping[str, str]] = None
) -> list[Path]:
    """Sibling checkout roots, from per-host CONFIG - never from repo content.

    Mirrors ``tools/moon_sync_poller.py`` ``_load_repo_roots``: the gitignored
    ``ops/moon_sync_repos.json``, with ``RC_MOON_SYNC_REPOS`` winning over it.
    Which sibling checkouts exist, and where, differs per machine and names
    private projects that have no business in a public tree.

    An absent or unparseable config yields ZERO roots - and therefore an
    inconclusive run - rather than a guess. A guessed root that happens not to
    exist would read as UNKNOWN, which is harmless; a guessed root that happens
    to hit some unrelated directory would report confident nonsense.
    """
    base = Path(root) if root is not None else REPO_ROOT
    environ = os.environ if env is None else env

    raw = (environ.get(REPOS_ENV) or "").strip()
    if raw:
        return [Path(p) for p in _split_roots(raw)]

    try:
        blob = json.loads((base / CONFIG_RELATIVE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [Path(str(p)) for p in (blob.get("repos") or []) if str(p).strip()]


def resolve_self_code(env: Optional[Mapping[str, str]] = None) -> str:
    environ = os.environ if env is None else env
    return (environ.get(SELF_CODE_ENV) or "").strip() or DEFAULT_SELF_CODE


# ------------------------------------------------------------------ scanning


def _scan(inbox: Path, staging: bool) -> Optional[dict]:
    """``{name: digest}`` for one inbox, or None if it cannot be enumerated.

    None is the honest answer for "unreadable", and callers turn it into UNKNOWN
    rather than into an empty inbox. Treating an unreadable directory as empty
    would score every note against it as ABSENT, manufacturing undelivered rows
    out of a permissions error.

    `staging` selects WHICH half: the visible entries a recipient's watcher will
    actually report (the delivery surface), or the `_`-prefixed drafts.
    """
    if not inbox.is_dir():
        return None
    out: dict = {}
    try:
        children = sorted(inbox.iterdir())
    except OSError:
        return None
    for child in children:
        is_staged = child.name.startswith(_STAGING_PREFIX)
        if is_staged != staging:
            continue
        if staging and child.is_dir():
            # A staging DIRECTORY is a folder of drafts, not one payload: each
            # note inside it is its own unit of outbound mail.
            try:
                for member in sorted(child.iterdir()):
                    out[member.name] = entry_digest(member)
            except OSError:
                continue
            continue
        out[child.name] = entry_digest(child)
    return out


def scan_visible(inbox: Path) -> Optional[dict]:
    """Entries a recipient's watcher would report. The delivery surface."""
    return _scan(inbox, staging=False)


def scan_staged(inbox: Path) -> Optional[dict]:
    """`_`-prefixed drafts. Authored, but never evidence of delivery."""
    return _scan(inbox, staging=True)


# ------------------------------------------------------------------- model


@dataclass
class Note:
    """One authored note, identified by the bytes rather than by the name."""

    digest: str
    names: tuple = ()
    in_local: bool = False
    per_slot: dict = field(default_factory=dict)
    verdict: str = STATUS_UNKNOWN

    @property
    def reach(self) -> int:
        return sum(1 for v in self.per_slot.values() if v == STATUS_DELIVERED)

    @property
    def sha12(self) -> str:
        return self.digest[:12]


@dataclass
class Report:
    self_code: str
    slots_configured: int
    slots_readable: int
    slots_unknown: int
    notes: list = field(default_factory=list)
    verdict: str = VERDICT_UNKNOWN

    @property
    def notes_checked(self) -> int:
        return len(self.notes)

    @property
    def undelivered_count(self) -> int:
        return sum(1 for n in self.notes if n.verdict == STATUS_UNDELIVERED)

    @property
    def unknown_count(self) -> int:
        return sum(1 for n in self.notes if n.verdict == STATUS_UNKNOWN)

    @property
    def name_mismatch_count(self) -> int:
        return sum(
            1 for n in self.notes
            if any(v == STATUS_NAME_ONLY for v in n.per_slot.values())
        )

    @property
    def reach_histogram(self) -> dict:
        hist: dict = {}
        for n in self.notes:
            if n.verdict == STATUS_UNKNOWN:
                continue
            hist[n.reach] = hist.get(n.reach, 0) + 1
        return hist


def exit_code(report: Report) -> int:
    if report.verdict == VERDICT_UNDELIVERED:
        return EXIT_UNDELIVERED
    if report.verdict == VERDICT_CLEAN:
        return EXIT_CLEAN
    return EXIT_INCONCLUSIVE


# -------------------------------------------------------------------- check


def check(
    root: Path,
    roots: Optional[Sequence[Path]] = None,
    self_code: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> Report:
    """Score every self-authored note against every configured recipient.

    READ-ONLY throughout, including across the repository boundary: this
    function opens sibling files for reading and does nothing else to them.
    """
    root = Path(root)
    code = self_code or resolve_self_code(env)
    sibling_roots = (
        [Path(p) for p in roots] if roots is not None else load_sibling_roots(root, env)
    )

    # -- the recipients ---------------------------------------------------
    slot_entries: list = []  # index -> {name: digest} or None for UNKNOWN
    for sib in sibling_roots:
        slot_entries.append(scan_visible(Path(sib) / INBOX_DIRNAME))
    readable = [i for i, e in enumerate(slot_entries) if e is not None]

    # -- the universe -----------------------------------------------------
    #
    # Union of everything bearing this repo's authorship mark, wherever it can
    # be seen: the local inbox (the shape the defect took), the local staging
    # area (where a kept copy would live), and every readable recipient (which
    # is the only place an outbound note leaves a trace when the sender keeps no
    # copy at all - the case that turns out to apply here).
    by_digest: dict = {}

    def _admit(name: str, digest: str, local: bool) -> None:
        note = by_digest.get(digest)
        if note is None:
            note = Note(digest=digest)
            by_digest[digest] = note
        if name not in note.names:
            note.names = tuple(sorted(note.names + (name,)))
        note.in_local = note.in_local or local

    local_inbox = root / INBOX_DIRNAME
    for scan in (scan_visible(local_inbox), scan_staged(local_inbox)):
        for name, digest in (scan or {}).items():
            if is_authored_by(name, code):
                _admit(name, digest, local=True)
    for entries in slot_entries:
        for name, digest in (entries or {}).items():
            if is_authored_by(name, code):
                _admit(name, digest, local=False)

    # -- score ------------------------------------------------------------
    for note in by_digest.values():
        for slot, entries in enumerate(slot_entries):
            if entries is None:
                note.per_slot[slot] = STATUS_UNKNOWN
                continue
            if note.digest in entries.values():
                note.per_slot[slot] = STATUS_DELIVERED
            elif any(n in entries for n in note.names):
                # The name arrived and the bytes did not. THIS is the case a
                # name-based check calls delivered, and it is the reason this
                # one compares digests.
                note.per_slot[slot] = STATUS_NAME_ONLY
            else:
                note.per_slot[slot] = STATUS_ABSENT
        if not readable:
            note.verdict = STATUS_UNKNOWN
        elif note.reach > 0:
            note.verdict = STATUS_DELIVERED
        else:
            note.verdict = STATUS_UNDELIVERED

    notes = sorted(by_digest.values(), key=lambda n: (n.names, n.digest))
    report = Report(
        self_code=code,
        slots_configured=len(sibling_roots),
        slots_readable=len(readable),
        slots_unknown=len(sibling_roots) - len(readable),
        notes=notes,
    )

    # -- verdict ----------------------------------------------------------
    #
    # ORDER IS LOAD-BEARING. "Nothing readable" outranks "nothing found",
    # which outranks everything else: a run that could not see a single
    # recipient has not established that the universe is empty either, and an
    # empty universe is never CLEAN no matter how many recipients were readable.
    if not readable:
        report.verdict = VERDICT_UNKNOWN
    elif not notes:
        report.verdict = VERDICT_EMPTY
    elif report.undelivered_count:
        report.verdict = VERDICT_UNDELIVERED
    else:
        report.verdict = VERDICT_CLEAN
    return report


# ------------------------------------------------------------------- render


_VERDICT_NOTE = {
    VERDICT_CLEAN: "every authored note reached at least one readable recipient.",
    VERDICT_UNDELIVERED: "at least one authored note reached NOBODY.",
    VERDICT_EMPTY: "no authored notes were found. This is an ABSENCE OF EVIDENCE, "
                   "not a clean result - see the denominator above.",
    VERDICT_UNKNOWN: "no recipient inbox was readable, so nothing was established. "
                     "A stranded note and a delivered one are indistinguishable here.",
}


def render(report: Report, show_names: bool = False) -> str:
    """A summary safe to paste into a public tree.

    Slot INDICES and content DIGESTS only. No configured path ever reaches this
    string, and note filenames are withheld unless explicitly requested: a slug
    is free text its author chose, so it is not categorically safe merely
    because this repo wrote it. Same reasoning as the slot numbering in
    ``tools/sibling_name_sweep.py``, which prints a slot and resolves it to a
    literal only on demand, on the operator's own machine.
    """
    lines = [
        "# outbound reciprocity check",
        "",
        f"- self code: {report.self_code}",
        f"- recipient slots: {report.slots_configured} configured, "
        f"{report.slots_readable} readable, {report.slots_unknown} UNKNOWN",
        f"- {report.undelivered_count} undelivered out of {report.notes_checked} checked",
        f"- verdict: {report.verdict} - {_VERDICT_NOTE[report.verdict]}",
    ]
    if report.notes:
        hist = report.reach_histogram
        lines.append("")
        lines.append("## reach")
        for reach in sorted(hist):
            lines.append(f"- reached {reach} of {report.slots_readable} readable "
                         f"slot(s): {hist[reach]} note(s)")
        if report.unknown_count:
            lines.append(f"- verdict UNKNOWN (nothing readable): {report.unknown_count}")
        if report.name_mismatch_count:
            lines.append(f"- name present but CONTENT DIFFERS somewhere: "
                         f"{report.name_mismatch_count} note(s)")

    stranded = [n for n in report.notes if n.verdict == STATUS_UNDELIVERED]
    if stranded:
        lines.append("")
        lines.append(f"## UNDELIVERED - {len(stranded)} note(s) reached nobody")
        for n in stranded:
            per = " ".join(f"slot {s}:{v}" for s, v in sorted(n.per_slot.items()))
            label = f" {n.names[0]}" if (show_names and n.names) else ""
            lines.append(f"- {n.sha12}{label} | in_local={n.in_local} | {per}")
    elif report.notes:
        lines.append("")
        lines.append("## per-slot delivery")
        for slot in range(report.slots_configured):
            got = sum(1 for n in report.notes
                      if n.per_slot.get(slot) == STATUS_DELIVERED)
            state = "UNKNOWN" if any(
                n.per_slot.get(slot) == STATUS_UNKNOWN for n in report.notes) else "readable"
            lines.append(f"- slot {slot} ({state}): {got} of {report.notes_checked}")
    elif report.slots_configured:
        lines.append("")
        lines.append("## per-slot delivery")
        for slot in range(report.slots_configured):
            lines.append(f"- slot {slot}: nothing authored to compare")
    return "\n".join(lines) + "\n"


def to_dict(report: Report, show_names: bool = False) -> dict:
    return {
        "self_code": report.self_code,
        "verdict": report.verdict,
        "slots_configured": report.slots_configured,
        "slots_readable": report.slots_readable,
        "slots_unknown": report.slots_unknown,
        "notes_checked": report.notes_checked,
        "undelivered_count": report.undelivered_count,
        "unknown_count": report.unknown_count,
        "name_mismatch_count": report.name_mismatch_count,
        "reach_histogram": {str(k): v for k, v in sorted(report.reach_histogram.items())},
        "notes": [
            {
                "sha12": n.sha12,
                "verdict": n.verdict,
                "reach": n.reach,
                "in_local": n.in_local,
                "per_slot": {str(k): v for k, v in sorted(n.per_slot.items())},
                **({"names": list(n.names)} if show_names else {}),
            }
            for n in report.notes
        ],
    }


# ---------------------------------------------------------------------- cli


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Check that every note this repo authored as outbound "
                    "actually reached a recipient inbox. Read-only.")
    ap.add_argument("--root", default=str(REPO_ROOT),
                    help="this repository's root (default: the repo this file lives in)")
    ap.add_argument("--repo", action="append", default=None, dest="repos",
                    help="recipient checkout root (repeatable); "
                         "default: the gitignored per-host config")
    ap.add_argument("--self-code", default=None,
                    help=f"this repo's counterparty code (default: {DEFAULT_SELF_CODE}, "
                         f"or ${SELF_CODE_ENV})")
    ap.add_argument("--names", action="store_true",
                    help="include note filenames in the output. OFF by default: "
                         "this repo is public and a slug is free text.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = Path(args.root)
    roots = [Path(p) for p in args.repos] if args.repos else None
    report = check(root, roots=roots, self_code=args.self_code)

    if args.json:
        print(json.dumps(to_dict(report, show_names=args.names), indent=2))
    else:
        sys.stdout.write(render(report, show_names=args.names))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
