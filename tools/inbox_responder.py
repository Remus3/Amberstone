#!/usr/bin/env python
r"""Cross-repo inbox responder - the deterministic half.

THE SPLIT, AND WHY IT IS THE WHOLE POINT. A headless session reads an incoming
note and PROPOSES a reply plus a list of actions. This module DISPOSES: it
checks each proposed action against the A1-A5 allowlist and refuses everything
else. The model never holds write authority.

That split exists because of a measured property of the runner. `ops/loop/
run_lane.ps1` spawns `claude -p --dangerously-skip-permissions`, which is
correct for the existing lanes - their prompts are operator-authored files in
`.claude/commands/`. The responder is categorically different: its input is a
note written by ANOTHER PARTY. Reusing that runner unchanged would make the
allowlist decorative, since the only thing standing between a hostile or merely
mistaken note and execution would be prompt text that the note itself is trying
to influence.

RSC's 1800 note supplied the framing and it is worth keeping verbatim: a
detector that trusts wrongly prints a wrong line, an executor that trusts
wrongly writes bytes.

THE LIST, as revised after RSC refuted all four of RC's original entries:

    A1  read-only measurement in own tree, reported back
    A2  own suite under a wall-clock timeout and ceilings on files and bytes;
        report the exit code and the counts the run printed, never a verdict
    A3  byte-verbatim vendor of a file already on the shared list, ONLY when
        the digest is corroborated by at least two INDEPENDENT carriers already
        cited on the channel. One sender's asserted digest is never sufficient
    A4  a pin moves ONLY in the same cycle as its own accepted A3 vendor, and
        the reply must carry the OLD and the NEW value
    A5  exactly ONE reply note, only into inboxes the incoming note named,
        never overwriting an existing note

Everything else is denied by D8. D1-D7 (history rewrites, visibility changes,
charter adoption, deletions, task/hook/service changes, frozen files, anything
the sender marked operator-gated) need no separate code path: they are simply
not on the allowlist, which is what default-deny means.

KNOWN LIMIT, stated rather than discovered later. A3 verifies the STRUCTURE of
a corroboration - two distinct carriers quoting the same digest - and cannot
yet verify that a cited note actually says what the proposal claims it says.
Closing that means reading the cited notes off disk and confirming the digest
string appears in them. It is the next increment and it is not shipped here, so
A3 currently trusts the citation while refusing the single-source case that
RSC's refutation was actually about.
"""
from __future__ import annotations

import json
import string
from dataclasses import dataclass, field
from pathlib import Path

# Files the cross-repo channel treats as byte-identical-by-contract. A3 may
# only ever target one of these, so a note cannot introduce a new shared file
# by asking - that stays a human act (see test_a3_first_time_vendor...).
SHARED_FILES: tuple[str, ...] = (
    "ops/loop/slots.py",
    "ops/loop/winmutex.py",
)

# Ceilings the PROPOSER cannot raise. RSC measured a fixture that sized itself
# from the value under test and became an amplifier for whatever that value
# became - it wrote 492674 files before it was killed. A bound chosen by the
# thing being bounded is not a bound.
_MAX_SUITE_TIMEOUT_S = 2400
_MAX_SUITE_FILES = 50_000
_MAX_SUITE_BYTES = 2_000_000_000
_MAX_BODY_BYTES = 200_000

# ALLOWLIST, never a denylist. A denylist is a list of the attacks already
# known; this is a list of the commands actually needed. Keyed on the first two
# argv elements, so `git log` cannot smuggle in `git push`.
_READ_ONLY_ARGV: frozenset[tuple[str, ...]] = frozenset({
    ("git", "ls-files"),
    ("git", "ls-remote"),
    ("git", "log"),
    ("git", "show"),
    ("git", "status"),
    ("git", "diff"),
    ("git", "for-each-ref"),
    ("git", "check-ignore"),
    ("git", "rev-parse"),
    ("git", "cat-file"),
})

# Even though actions are exec'd as a LIST and never through a shell, an argv
# carrying these is refused. It costs nothing and a proposal trying to chain is
# reporting its own intent.
_SHELL_META = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")

_ASCII_OK = set(string.printable)
_HEX = set("0123456789abcdefABCDEF")

# The only roots a suite action may name. Not a path check - see _validate_suite.
_SUITE_ROOTS: frozenset[str] = frozenset({"tests", "agents/daemon_slayer"})

# Flags that turn a read-only verb into a writer.
_WRITING_FLAGS: tuple[str, ...] = ("--output", "-o=", "--output-file")


def _is_hex(s: str) -> bool:
    return all(ch in _HEX for ch in s)


# ---------------------------------------------------------------------------
# The decider. What fires, and what must never fire.
#
# THE SEPARATION THAT MATTERS. This module keeps its OWN record of what it has
# answered, in its OWN file, and never touches `sync_inbox_seen.json`. LL
# measured the opposite design this week: a session hook that marked mail seen,
# firing for every subagent start, so the first subagent consumed the
# operator's queue and the operator's own session then honestly reported
# "nothing new". An automated responder is that defect with a bigger engine -
# it would answer a note and, as a side effect, tell the operator there was
# nothing to read. Reporting, acknowledging and ANSWERING are three acts.

_STOP_FLAG = "INBOX_RESPONDER_STOP"
_STATE_NAME = "inbox_responder_answered.json"
_NOTE_SUFFIX = ".md"


def responder_state_path(root: Path) -> Path:
    """Deliberately NOT sync_inbox_seen.json. See the note above."""
    return Path(root) / "ops" / "runtime" / _STATE_NAME


def is_stopped(root: Path) -> bool:
    """Operator kill switch. Presence of the file is the whole protocol."""
    return (Path(root) / "ops" / "runtime" / _STOP_FLAG).exists()


def _sender_code(name: str) -> str | None:
    """Extract RSC from `2026-09-07-1800-from-RSC-topic.md`."""
    marker = "-from-"
    i = name.find(marker)
    if i < 0:
        return None
    rest = name[i + len(marker):]
    code, _, _ = rest.partition("-")
    return code or None


def _answered(root: Path) -> set[str] | None:
    """Notes already answered, or None if the record is unreadable.

    None means FAIL CLOSED at every call site. Failing open would answer the
    entire back catalogue in one burst the first time a crash truncates this
    file, and the back catalogue here is 97 notes.
    """
    p = responder_state_path(root)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text(encoding="utf-8")).get("answered", []))
    except (OSError, ValueError):
        return None


def record_responded(root: Path, name: str) -> None:
    """Add one note to THIS module's record. Touches nothing else."""
    p = responder_state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    known = _answered(root) or set()
    known.add(name)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps({"answered": sorted(known)}, indent=2), encoding="utf-8", newline="\n"
    )
    tmp.replace(p)


def pending_notes(inbox: Path, root: Path, *, participants: tuple[str, ...]) -> list[str]:
    """Notes this responder should answer, oldest ARRIVAL first.

    Ordered by mtime on the receiving disk, not by the sender's filename. RC
    retired its own filename tie-break after measuring the skew: LL's note was
    stamped 1815 and landed at 17:57:01 while RSC's stamped 1800 landed at
    17:59:53, so filename order was the exact reverse of arrival order. One
    clock beats five.
    """
    if is_stopped(root):
        return []
    answered = _answered(root)
    if answered is None:
        return []  # unreadable record: fail closed
    out = []
    try:
        entries = list(Path(inbox).iterdir())
    except OSError:
        return []
    for p in entries:
        if p.suffix != _NOTE_SUFFIX or p.name in answered:
            continue
        code = _sender_code(p.name)
        # "RC" is excluded even when present in `participants`: a responder that
        # answers its own note is a loop needing no second participant.
        if code == "RC":
            continue
        # A note from a repo outside this agreement stays invisible ON PURPOSE.
        # It is somebody else's correspondence, not a silent failure, and
        # admitting it would put a hold on a note RC was never asked to answer.
        if code is not None and code not in participants:
            continue
        # RM-385, and the two filters this replaces were BOTH silent-forever
        # conditions rather than skips. `Path.is_file()` is false for a
        # junction (always a reparse point), and `code is None` is true for a
        # name with its sender and date transposed - so either entry sat in
        # the inbox while every later tick reported `empty / none_pending`,
        # which is the responder saying nothing is pending while something is.
        # Admitting them here does NOT admit them to the model: gate 6 judges
        # every one and refuses anything that is not a plain file with a legal
        # name, so the entry becomes a refusal held for the operator. `lstat`
        # rather than `stat` so a reparse point is ordered by when the ENTRY
        # appeared and a dangling one cannot raise.
        try:
            out.append((p.lstat().st_mtime, p.name))
        except OSError:
            continue
    return [n for _, n in sorted(out)]


@dataclass
class Decision:
    """One verdict. `rule` names the entry that decided, so a refusal is auditable."""

    allowed: bool
    rule: str
    reason: str


@dataclass
class Cycle:
    """State for ONE incoming note.

    `reply_targets` is the set of repos the incoming note addressed, and is the
    only place a reply may go. A responder that could pick its own recipients
    would be a broadcast channel with no human in it.
    """

    reply_targets: tuple[str, ...]
    root: Path
    shared_files: tuple[str, ...] = SHARED_FILES
    accepted_vendors: set[str] = field(default_factory=set)
    replies_sent: int = 0


def _deny(rule: str, reason: str) -> Decision:
    return Decision(False, rule, reason)


def _safe_rel(root: Path, rel: object) -> Path | None:
    """Resolve `rel` inside `root`, or None if it escapes.

    Three separate checks because they catch different things: absolute paths,
    a literal `..` component, and a resolved path that lands outside anyway
    (symlinks, junctions - RSC measured `Path.is_symlink()` returning False for
    an NTFS junction this week, so containment is asserted after resolution
    rather than inferred before it).
    """
    if not isinstance(rel, str) or not rel:
        return None
    p = Path(rel)
    if p.is_absolute() or ".." in p.parts:
        return None
    try:
        resolved = (root / p).resolve()
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _validate_measure(a: dict, c: Cycle) -> Decision:
    argv = a.get("argv")
    if not isinstance(argv, list) or not argv:
        return _deny("A1", "argv must be a non-empty list; a string is a shell invocation")
    if not all(isinstance(x, str) for x in argv):
        return _deny("A1", "every argv element must be a string")
    if any(m in x for x in argv for m in _SHELL_META):
        return _deny("A1", "argv carries shell metacharacters")
    if tuple(argv[:2]) not in _READ_ONLY_ARGV:
        return _deny("A1", f"{argv[:2]} is not on the read-only allowlist")
    # A prefix allowlist checks the VERB and says nothing about the FLAGS.
    # `git diff --output=FILE` writes an arbitrary file, so a list of read-only
    # verbs quietly acquired a writer. Found by refuting this module's own
    # first version rather than by a report.
    if any(x.startswith(_WRITING_FLAGS) for x in argv[2:]):
        return _deny("A1", "a flag on this command redirects output to a file")
    return Decision(True, "A1", "read-only command on the allowlist")


def _validate_suite(a: dict, c: Cycle) -> Decision:
    # Containment is the WRONG question here and answering it alone is how
    # `pytest .` gets through: "." is inside the tree, and running the suite
    # from the repo root deleted the live supervisor lock in this repo once
    # already (memory reference_pytest_root_deletes_supervisor_lock). The
    # target is therefore an allowlist of known suite roots, not a path check.
    if a.get("target") not in _SUITE_ROOTS:
        return _deny("A2", f"{a.get('target')!r} is not a known suite root")
    if _safe_rel(c.root, a.get("target")) is None:
        return _deny("A2", "suite target must resolve inside the responder's own tree")
    bounds = (
        ("timeout_s", _MAX_SUITE_TIMEOUT_S),
        ("max_files", _MAX_SUITE_FILES),
        ("max_bytes", _MAX_SUITE_BYTES),
    )
    for key, ceiling in bounds:
        v = a.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            return _deny("A2", f"{key} is required and must be a positive int")
        if v > ceiling:
            return _deny("A2", f"{key}={v} exceeds the ceiling {ceiling}")
    return Decision(True, "A2", "bounded suite run")


def _validate_vendor(a: dict, c: Cycle) -> Decision:
    path = a.get("path")
    if path not in c.shared_files:
        return _deny("A3", f"{path!r} is not on the shared-file list")
    if _safe_rel(c.root, path) is None:
        return _deny("A3", "vendor target escapes the tree")
    digest = a.get("digest")
    if not isinstance(digest, str) or len(digest) != 64 or not _is_hex(digest):
        return _deny("A3", "a 64-character hex sha256 digest is required")

    corrs = a.get("corroborations")
    if not isinstance(corrs, list) or len(corrs) < 2:
        return _deny("A3", "two independent corroborations are required; one sender is not evidence")
    carriers, digests = set(), set()
    for entry in corrs:
        if not isinstance(entry, dict):
            return _deny("A3", "each corroboration must be an object")
        carrier, d = entry.get("carrier"), entry.get("digest")
        if not isinstance(carrier, str) or not isinstance(d, str):
            return _deny("A3", "each corroboration needs a carrier and a digest")
        carriers.add(carrier)
        digests.add(d)
    if len(carriers) < 2:
        return _deny("A3", "corroborations come from one carrier; that is one measurement")
    if digests != {digest}:
        return _deny("A3", "carriers disagree; a disagreement is a finding, not a tie to break")

    c.accepted_vendors.add(path)
    return Decision(True, "A3", f"{len(carriers)} independent carriers agree")


def _validate_pin(a: dict, c: Cycle) -> Decision:
    if _safe_rel(c.root, a.get("path")) is None:
        return _deny("A4", "pin target must resolve inside the tree")
    vendored = a.get("vendored")
    if vendored not in c.accepted_vendors:
        return _deny(
            "A4",
            "a pin moves only alongside its own accepted vendor this cycle; "
            "otherwise it closes a divergence window and tells nobody",
        )
    for key in ("old", "new"):
        if not isinstance(a.get(key), str) or not a[key]:
            return _deny("A4", f"{key} value is required; a pin move with no prior value is unreviewable")
    return Decision(True, "A4", "pin moves with its vendor and reports both values")


def _validate_reply(a: dict, c: Cycle) -> Decision:
    if c.replies_sent >= 1:
        return _deny("A5", "one reply per cycle; a second is a fan-out")
    if a.get("overwrite"):
        return _deny("A5", "a reply never overwrites an existing note")
    targets = a.get("targets")
    if not isinstance(targets, list) or not targets:
        return _deny("A5", "targets must be a non-empty list")
    extra = set(targets) - set(c.reply_targets)
    if extra:
        return _deny("A5", f"{sorted(extra)} were not named by the incoming note")
    body = a.get("body")
    if not isinstance(body, str) or not body:
        return _deny("A5", "a reply needs a body")
    if len(body.encode("utf-8", "replace")) > _MAX_BODY_BYTES:
        return _deny("A5", "body exceeds the size ceiling")
    if any(ch not in _ASCII_OK for ch in body):
        return _deny("A5", "body must be 7-bit ASCII (repo-wide rule, enforced before bytes leave)")
    c.replies_sent += 1
    return Decision(True, "A5", "single reply to named targets")


_VALIDATORS = {
    "measure": _validate_measure,
    "suite": _validate_suite,
    "vendor": _validate_vendor,
    "pin": _validate_pin,
    "reply": _validate_reply,
}


def validate_action(action: object, cycle: Cycle) -> Decision:
    """Judge ONE proposed action. Default deny.

    Deliberately takes structured fields and never free text. A denied action
    carrying operator-sounding justification stays denied, because no field
    here is read as an argument - the note is data, not instructions.
    """
    if not isinstance(action, dict):
        return _deny("D8", "an action must be an object")
    kind = action.get("kind")
    fn = _VALIDATORS.get(kind) if isinstance(kind, str) else None
    if fn is None:
        return _deny("D8", f"{kind!r} is not on the allowlist")
    return fn(action, cycle)


def validate_proposal(proposal: object, cycle: Cycle) -> list[Decision]:
    """Judge a whole proposal IN ORDER.

    Order matters and only in one direction: a pin may depend on a vendor
    accepted earlier in the same list, so a refused vendor must take its pin
    down with it rather than leaving a rejected copy free to move a digest.
    """
    if not isinstance(proposal, dict):
        return [_deny("D8", "a proposal must be an object")]
    actions = proposal.get("actions")
    if not isinstance(actions, list):
        return [_deny("D8", "proposal.actions must be a list")]
    return [validate_action(a, cycle) for a in actions]
