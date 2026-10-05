# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit - inbox cost discipline (FLEET-COMMON item 14, operator order 2026-10-05).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: measured 2026-10-05, about 60 percent of the second account's spend went to
inbox chatter between repos, not to build lanes. This file changes COST, never
AUTONOMY: the inbox is still read and acted on every tick, unattended.

The tick (folded into the tree's existing lane / loop tick - no separate
high-frequency responder when a lane loop exists):

    for path, d in scan(root, inbox_dir, CODE):          # unseen notes, by mtime
        if d.action == SKIP:   mark_seen(root, path, d)   # self / terminal
        elif d.action == ACK:  mark_seen(root, path, d)   # mechanical, no note
        elif d.action == WORK: escalate to a real work lane (ORDER/FIX/RULING)
        else:  # TRIAGE - one cheap look
            line = fleet_headless.spawn(..., kind="triage", **TRIAGE_SPAWN)
            v = parse_verdict(line["result"])             # NOREPLY | ACK | ANSWER
            ... collect ANSWER bodies, mark_seen(...)
    answers -> ONE batched note per destination per tick (batch_note), sent only
    if OutboundCap(root).allow(cls) and may_reply(...) for every part.

Rules enforced here:
- triage first on sonnet at effort low (TRIAGE_SPAWN), and only for notes the
  name/title cannot classify; ACK / INFORMATION / TERMINAL classes get a
  mechanical ack (a ledger line, never a note) or no reply; only ORDER / FIX /
  RULING escalate to a work lane;
- at most OUTBOUND_CAP (6) outbound notes per tree per local day; ORDER, FIX
  and RULING are exempt; several answers to one destination go in ONE note;
- never answer an answer; a note chain stops at MAX_HOPS (2) unless the reply
  carries new work (the `HOP: <n>` header line, absent = 1);
- cost_split() sorts usage lines into build / inbox / unattributed spend.

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import contextlib
import datetime as _dt
import json
import os
import re
import time
from pathlib import Path

INBOX_VERSION = 1
OUTBOUND_CAP = 6
MAX_HOPS = 2
EXEMPT = ("ORDER", "FIX", "RULING")
ACK_CLASSES = ("ACK", "INFORMATION", "TERMINAL", "CORRECTION-ACCEPTED",
               "POLL-ANSWER", "RECEIVED", "NO-REPLY", "NOREPLY")
ANSWER_CLASSES = ("ANSWER", "ACK", "RECEIVED", "POLL-ANSWER", "INFORMATION",
                  "CORRECTION-ACCEPTED", "RESPONDER", "REPLY")
TRIAGE_SPAWN = {"model": "sonnet", "effort": "low", "bare": True, "timeout": 300}
SKIP, ACK, WORK, TRIAGE = "skip", "ack", "work", "triage"
VERDICTS = ("NOREPLY", "ACK", "ANSWER")
KINDS = ("build", "inbox", "triage", "unattributed")
SEEN_REL = Path("ops/loop/control/inbox_seen.jsonl")
OUTBOUND_REL = Path("ops/loop/control/outbound_notes.jsonl")
USAGE_REL = Path("ops/loop/control/headless_usage.jsonl")
_SENDER = re.compile(r"(?:^|[-_])(?i:from)-([A-Z]+)-")
_CLASS = re.compile(r"(?:^|[-_])(?i:from)-[A-Z]+-([A-Za-z]+(?:-[A-Z]+)?)")
_TITLE = re.compile(r"^#+\s*(?i:from)\s+([A-Z]+)\b(?:\s*-\s*([A-Z][A-Za-z-]*))?")
_HOP = re.compile(r"^\s*HOP:\s*(\d+)\s*$", re.M)
_VERDICT = re.compile(r"^\s*VERDICT:\s*([A-Z-]+)\s*$", re.M)
_MARK = r"(?:TERMINAL|NO[-_ ]?REPLY)"
_MARKER = re.compile(r"^(?:CLASS\s+)?" + _MARK + r"(?:\s*[-.,:;/]?\s*" + _MARK +
                     r")*\s*[.!]?$")
TRIAGE_PROMPT = (
    "Inbox triage, effort low. Read ONLY the note below. Reply with the first line "
    "`VERDICT: NOREPLY` (nothing to say), `VERDICT: ACK` (seen, nothing owed) or "
    "`VERDICT: ANSWER` followed by the shortest answer text that settles it. Do no "
    "work, open no other file, never answer an answer. Note `{name}`:\n\n{body}")


class Decision:
    __slots__ = ("action", "cls", "sender", "reason", "hop")

    def __init__(self, action, cls, sender, reason, hop):
        self.action, self.cls, self.sender = action, cls, sender
        self.reason, self.hop = reason, hop

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return "Decision(%s)" % self.as_dict()


# ---------------------------------------------------------------- classify

def _base(name):
    return Path(str(name or "")).name


def _tokens(text):
    return [t for t in re.split(r"[^A-Z0-9]+", text.upper()) if t]


def _title(head):
    for line in (head or "").splitlines():
        if line.strip():
            return _TITLE.match(line.strip())
    return None


def sender(name, head=""):
    m = _SENDER.search(_base(name))
    if m:
        return m.group(1)
    t = _title(head)
    return t.group(1) if t else None


def note_class(name, head=""):
    """ORDER, FIX, ANSWER, ... from the name (`-from-XX-<CLASS>-`), else the title."""
    m = _CLASS.search(_base(name))
    if m:
        word = m.group(1).upper()
        return word if word in ACK_CLASSES else word.split("-")[0]
    t = _title(head)
    return t.group(2).upper().split("-")[0] if t and t.group(2) else None


def hop(head):
    """The `HOP: <n>` header line; absent = 1 (an original note)."""
    m = _HOP.search(head or "")
    return int(m.group(1)) if m else 1


def _terminal(name, head):
    toks = _tokens(_base(name))
    joined = "-" + "-".join(toks) + "-"
    if "TERMINAL" in toks or "NOREPLY" in toks or "-NO-REPLY-" in joined:
        return True
    for line in (head or "").splitlines():
        text = line.strip().lstrip("#*>- \t").rstrip("* \t").upper()
        if text and _MARKER.match(text):
            return True
    return False


def classify(name, own_code, head=""):
    """Zero-cost first pass. ORDER/FIX/RULING -> WORK (never damped); own note or
    TERMINAL/no-reply -> SKIP; an ACK-family or ANSWER class -> ACK (mechanical,
    no note: never answer an answer); a note past the hop limit -> ACK; anything
    else -> TRIAGE (sonnet, low)."""
    snd, cls, h = sender(name, head), note_class(name, head), hop(head)
    if snd == own_code:
        return Decision(SKIP, cls, snd, "self", h)
    if cls in EXEMPT:
        return Decision(WORK, cls, snd, "class %s escalates" % cls, h)
    if _terminal(name, head):
        return Decision(SKIP, cls, snd, "terminal", h)
    if cls in ACK_CLASSES:
        return Decision(ACK, cls, snd, "ack class %s" % cls, h)
    if cls in ANSWER_CLASSES:
        return Decision(ACK, cls, snd, "never answer an answer", h)
    if h >= MAX_HOPS:
        return Decision(ACK, cls, snd, "hop %d >= %d" % (h, MAX_HOPS), h)
    return Decision(TRIAGE, cls, snd, "unclassified", h)


def triage_prompt(name, body, limit=12000):
    return TRIAGE_PROMPT.format(name=_base(name), body=(body or "")[:limit])


def parse_verdict(text):
    """(verdict, answer_text). Unparseable output is ACK: a triage that cannot
    decide never generates a note (fail quiet, the note stays marked seen)."""
    m = _VERDICT.search(text or "")
    v = m.group(1) if m else "ACK"
    if v not in VERDICTS:
        v = "ACK"
    answer = (text or "")[m.end():].strip() if (m and v == "ANSWER") else ""
    if v == "ANSWER" and not answer:
        v = "ACK"
    return v, answer


def may_reply(incoming_cls, incoming_hop, new_work=False):
    """Never answer an answer; no chain beyond MAX_HOPS without new work."""
    if new_work:
        return True
    if incoming_cls in ANSWER_CLASSES:
        return False
    return incoming_hop < MAX_HOPS


def next_hop(incoming_hop, new_work=False):
    return 1 if new_work else incoming_hop + 1


# ---------------------------------------------------------------- ledgers

def _local_day(epoch):
    return _dt.datetime.fromtimestamp(epoch).strftime("%Y-%m-%d")


def _iso(epoch):
    return _dt.datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds")


def _append(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="ascii", newline="\n") as fh:
        fh.write(json.dumps(doc) + "\n")


def _lines(path):
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        with contextlib.suppress(ValueError):
            doc = json.loads(line)
            if isinstance(doc, dict):
                out.append(doc)
    return out


def seen(root):
    return {d.get("note") for d in _lines(Path(root) / SEEN_REL)}


def mark_seen(root, note, decision, verdict=None, clock=time.time):
    """The mechanical ack: one ledger line, no note sent."""
    doc = {"ts": _iso(clock()), "note": _base(note), "action": decision.action,
           "cls": decision.cls, "reason": decision.reason, "verdict": verdict}
    _append(Path(root) / SEEN_REL, doc)
    return doc


def scan(root, inbox_dir, own_code, head_bytes=1500):
    """Unseen notes in inbox_dir, oldest mtime first (FLEET-COMMON 7), each with
    its classify() Decision. Directories (kit bundles) are skipped."""
    done = seen(root)
    rows = []
    with contextlib.suppress(OSError):
        for p in Path(inbox_dir).iterdir():
            if p.is_file() and p.suffix.lower() in (".md", ".txt") and p.name not in done \
                    and p.name.upper() != "README.TXT":
                rows.append((p.stat().st_mtime, p))
    out = []
    for _, p in sorted(rows):
        try:
            head = p.read_bytes()[:head_bytes].decode("utf-8", "replace")
        except OSError:
            continue
        out.append((p, classify(p.name, own_code, head)))
    return out


class OutboundCap:
    """At most `cap` outbound notes per local day; EXEMPT classes never count
    against it and are never refused."""

    def __init__(self, root, cap=OUTBOUND_CAP, clock=time.time):
        self.path, self.cap, self.clock = Path(root) / OUTBOUND_REL, cap, clock

    def used(self):
        day = _local_day(self.clock())
        return sum(1 for d in _lines(self.path)
                   if d.get("day") == day and d.get("cls") not in EXEMPT)

    def allow(self, cls):
        return cls in EXEMPT or self.used() < self.cap

    def record(self, name, cls, to, parts=1):
        if not self.allow(cls):
            return None
        now = self.clock()
        doc = {"ts": _iso(now), "day": _local_day(now), "note": _base(name),
               "cls": cls, "to": to, "parts": parts}
        _append(self.path, doc)
        return doc


def batch_note(code, to, answers, hop_n=2, stamp=None):
    """ONE note answering several notes: answers = [(note_name, text), ...].
    Returns (filename_slug, body). The body carries `HOP: <n>`, so the receiver's
    classify() stops the chain."""
    stamp = stamp or _dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    names = [_base(n) for n, _ in answers]
    slug = "%s-from-%s-ANSWER-to-%s-batched-%d-answers" % (stamp, code, to, len(answers))
    lines = ["# From %s - ANSWER to %s: %d batched answers" % (code, to, len(answers)), "",
             "HOP: %d" % hop_n, "TERMINAL no-reply.", ""]
    for name, text in answers:
        lines += ["## Re %s" % name, "", (text or "").strip(), ""]
    body = "\n".join(lines).rstrip() + "\n"
    body.encode("ascii")
    return slug + ".md", body, names


# ---------------------------------------------------------------- cost split

def run_kind(line):
    """build | inbox | triage | unattributed. An explicit "kind" (kit v8) wins;
    else a channel-note name (`-from-XX-`) is inbox, an empty note unattributed,
    and any other label (lane-*, drain-*, plan ids) build."""
    k = line.get("kind")
    if k in KINDS:
        return k
    note = _base(line.get("note") or "")
    if not note:
        return "unattributed"
    return "inbox" if _SENDER.search(note) else "build"


def _ts(line):
    try:
        return _dt.datetime.fromisoformat(line.get("ts")).timestamp()
    except (TypeError, ValueError):
        return None


def cost_split(lines, since=None, until=None):
    """{"build": {"usd", "runs"}, "inbox": ..., "triage": ..., "unattributed": ...,
    "total_usd", "inbox_share"} over usage lines with since <= ts < until (epoch).
    inbox_share counts inbox + triage against attributed spend."""
    out = {k: {"usd": 0.0, "runs": 0} for k in KINDS}
    for line in lines:
        t = _ts(line)
        if t is None or (since is not None and t < since) or (until is not None and t >= until):
            continue
        k = run_kind(line)
        out[k]["runs"] += 1
        out[k]["usd"] += float(line.get("cost_usd") or 0)
    for k in KINDS:
        out[k]["usd"] = round(out[k]["usd"], 2)
    total = sum(out[k]["usd"] for k in KINDS)
    attributed = total - out["unattributed"]["usd"]
    chatter = out["inbox"]["usd"] + out["triage"]["usd"]
    out["total_usd"] = round(total, 2)
    out["inbox_share"] = round(chatter / attributed, 3) if attributed > 0 else None
    return out


def repo_split(root, days=7, now=None):
    """cost_split of one tree's usage file over the last `days`; present False
    when the tree has no usage file (a tree that does not log is a finding)."""
    path = Path(root) / USAGE_REL
    if not path.is_file():
        return {"present": False}
    now = time.time() if now is None else now
    doc = cost_split(_lines(path), since=now - days * 86400, until=now + 1)
    doc["present"] = True
    return doc


if __name__ == "__main__":  # python fleet_inbox.py <root> [days]
    import sys
    r = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    print(json.dumps(repo_split(r, int(sys.argv[2]) if len(sys.argv) > 2 else 7), indent=1))
