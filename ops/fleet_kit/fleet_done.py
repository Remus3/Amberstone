# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v9 - the /done marker (FLEET-COMMON item 15; UI/UX standard section 2).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: the operator wants a sure-fire "/done complete, safe to clear" that is
verified, persistent, and cleared only by the operator's next act - never by a
timer and never by parsing chat. The marker is the signal of record; the chat
line `Done ritual complete, safe to clear` stays as the human receipt.

    python fleet_done.py mark --session N --status done|failed [--reason TEXT] [--bg N]
        The LAST act of every tree's /done, after the commit and the hand-off
        are READ BACK, immediately before the chat line. A failed step still
        calls it with --status failed --reason "<the step that stopped it>".
        It reads HEAD and hashes the hand-off ITSELF (never takes them as
        arguments) and reads CLAUDE_CODE_SESSION_ID and CONSOLE_PANE from env.
        Writes <main checkout>/ops/loop/control/session_done.json atomically.
    python fleet_done.py validate [--session-id ID | --pane P]
        Prints DONE / FAIL / none with the reason; exit 0 only on DONE.
    python fleet_done.py stop-hook
        The kit Stop hook. Reads the Stop input on stdin; when the marker
        validates for this session it emits ONE terminalSequence: OSC 2 tab
        title `<CODE> DONE S<n> - safe to clear` plus one OSC 9 notification,
        once per marker (dedupe on `at`), only when background_tasks and
        session_crons are both empty; otherwise the title
        `<CODE> S<n> done, waiting <N> bg` and no notification. Silent (no
        bytes) otherwise. Never blocks, never exits 2, never writes
        additionalContext or systemMessage.

Validation (every client; all must hold, else show nothing):
  1. status done and safe_to_clear true (status failed -> FAIL, same rules 2-3);
  2. binding: session_id equals the client's session id (CLI), or pane equals
     the pane id (Console);
  3. repo HEAD equals `commit` and the sha256 of the hand-off on disk equals
     `handoff_sha256` (any later commit or hand-off edit = work after /done).

v16 (KIT-16):
    mark WARNS (never fails) when the hand-off is over HANDOFF_WARN_BYTES
        (30 KB): a second stdout line `warn: hand-off <N> KB > 30 KB; run
        fleet_done.py archive`. The marker's keys, the exit code and
        validation are unchanged.
    v18 (Fleet Insights 2026-10-16 item 5): the warning became a FAIL MODE.
        `mark --status done` on a hand-off over 30 KB writes the marker as
        status failed with the reason `hand-off <N> KB > 30 KB; archive closed
        blocks (fleet_done.py archive --apply)` - it can never validate - and
        exits 1; the second stdout line reads `fail: ...` with the same text.
        A `--status failed` mark is unchanged (exit 0, the size line printed).
    python fleet_done.py archive [--apply] [--keep N] [--root R]
        Moves CLOSED blocks out of the hand-off into
        docs/handoff-archive/<CODE>-<YYYY-MM-DD>.txt (appended when it
        exists). DRY-RUN by default: prints what it would move and changes
        nothing; --apply writes. A CLOSED BLOCK (conservative on purpose):
          - a FRAMED HEADING: a rule line (20 or more "=" and nothing else),
            then one heading line that is either followed by a second rule
            or is a starred banner `*** ... ***`; the block runs from the
            first rule to the line before the next framed heading's first
            rule (or the end of the file);
          - its heading, stripped of '*' and spaces and upper-cased, STARTS
            WITH "CLOSED" or contains " - CLOSED" (e.g. `CLOSED THIS SESSION`,
            `*** SESSION 4 (...) - CLOSED, WITH WHAT WAS READ BACK ***`);
          - its body has no line that says work is still open: NOT CLOSED,
            STILL OPEN, OPEN ITEM(S), CARRIED, CARRY FORWARD, TODO, NEXT
            ACTION, WAITING, BLOCKED, PENDING (whole words, any case). Such a
            block is listed as kept with the word that kept it;
          - the newest --keep closed blocks (default 1, the first ones in the
            file) stay, so the last session's read-back record is never moved.
        Each moved block leaves one line in its place:
        `(closed block "<heading>" archived to docs/handoff-archive/<file>)`.
        The archive is written and READ BACK before the hand-off is rewritten
        (atomic replace); nothing is deleted. A hand-off with no framed
        headings has nothing to archive.

Pure stdlib. No machine path, account id or repo name appears in this file.
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

DONE_VERSION = 2
SCHEMA = 1
STATUSES = ("done", "failed")
MARKER_REL = Path("ops/loop/control/session_done.json")
SEEN_REL = Path("ops/loop/control/session_done.seen")
HANDOFF_SUFFIX = "-NEXT-SESSION.txt"
CHAT_LINE = "Done ritual complete, safe to clear"
REASON_MAX = 200
HANDOFF_WARN_BYTES = 30 * 1024
ARCHIVE_REL = Path("docs/handoff-archive")
_RULE = re.compile(r"^={20,}\s*$")
_OPEN_WORDS = re.compile(r"\b(NOT CLOSED|STILL OPEN|OPEN ITEMS?|CARRIED|CARRY FORWARD|TODO|"
                         r"NEXT ACTION|WAITING|BLOCKED|PENDING)\b", re.I)
# v11: three git calls at most per stop-hook run, so 3 x 10 s stays under the
# 45 s Stop hook timeout (v9-v10 used 15 s each = exactly 45 s).
GIT_TIMEOUT = 10
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- repo facts

def find_git(environ=None, cwd=None):
    """Absolute path of git from PATH, never a bare name and never from the
    working directory (v11, CS 1623 item 6; the same rule as fleet_lanes).
    Empty, relative and cwd-equal PATH entries are skipped; None if absent."""
    env = os.environ if environ is None else environ
    try:
        here = os.path.normcase(Path(cwd or Path.cwd()).resolve())
    except OSError:
        here = None
    exts = [""]
    if sys.platform == "win32":
        exts = [e for e in env.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";") if e]
    for entry in env.get("PATH", "").split(os.pathsep):
        d = entry.strip().strip('"')
        if not d or not Path(d).is_absolute():
            continue
        try:
            if os.path.normcase(Path(d).resolve()) == here:
                continue
        except OSError:
            continue
        for ext in exts:
            f = Path(d) / ("git" + ext)
            if f.is_file() and (sys.platform == "win32" or os.access(f, os.X_OK)):
                return str(f)
    return None


def _git(root, *args):
    exe = find_git()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-C", str(root), *args], capture_output=True,
                           text=True, timeout=GIT_TIMEOUT, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def main_checkout(path):
    """The MAIN working tree for path, even from a linked (lane) worktree."""
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        p = Path(common)
        if p.name == ".git":
            return p.parent
    top = _git(path, "rev-parse", "--show-toplevel")
    return Path(top) if top else Path(path).resolve()


def head(root):
    out = _git(root, "rev-parse", "HEAD")
    return out if out and _HEX40.match(out) else None


def find_handoff(root):
    """The one `<CODE>-NEXT-SESSION.txt` at the tree root, else None."""
    try:
        names = sorted(p.name for p in Path(root).iterdir()
                       if p.is_file() and p.name.endswith(HANDOFF_SUFFIX))
    except OSError:
        return None
    return names[0] if len(names) == 1 else None


def tree_code(handoff):
    return handoff[:-len(HANDOFF_SUFFIX)] if handoff else None


def sha256_file(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def _utc(epoch):
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_line(text):
    if text is None:
        return None
    line = " ".join(str(text).split())
    line = line.encode("ascii", "replace").decode("ascii")
    return line[:REASON_MAX] or None


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="ascii", newline="\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- mark

def mark(root, session, status, reason=None, bg=0, env=None, clock=None):
    """Write the marker. A done mark whose HEAD or hand-off cannot be read is
    written as failed (it could never validate), with the reason."""
    import time
    env = os.environ if env is None else env
    now = (clock or time.time)()
    if status not in STATUSES:
        raise ValueError("status {!r} not in {}".format(status, STATUSES))
    session = int(session)
    bg = max(0, int(bg or 0))
    root = Path(root)
    handoff = find_handoff(root)
    commit = head(root)
    digest = sha256_file(root / handoff) if handoff else None
    reason = _one_line(reason)
    too_big = size_reason(handoff_bytes(root / handoff)) if handoff else None
    if status == "done" and not handoff:
        status, reason = "failed", "hand-off file not found at the tree root"
    elif status == "done" and not commit:
        status, reason = "failed", "HEAD could not be read"
    elif status == "done" and too_big:
        status, reason = "failed", too_big
    if status == "failed" and not reason:
        reason = "unspecified step failed"
    if status == "done":
        reason = None
    doc = {"schema": SCHEMA, "tree": tree_code(handoff),
           "session": session,
           "session_id": env.get("CLAUDE_CODE_SESSION_ID") or None,
           "pane": env.get("CONSOLE_PANE") or None,
           "status": status,
           "safe_to_clear": status == "done" and bg == 0,
           "reason": reason, "commit": commit, "handoff": handoff,
           "handoff_sha256": digest, "background_tasks": bg,
           "at": _utc(now), "next_session": session + 1}
    _atomic_write(root / MARKER_REL, json.dumps(doc, indent=1) + "\n")
    return doc


def handoff_bytes(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return None


def size_reason(size, limit=HANDOFF_WARN_BYTES):
    """Why an oversized hand-off fails mark (v18), else None."""
    if size is None or size <= limit:
        return None
    return ("hand-off {} KB > {} KB; archive closed blocks "
            "(fleet_done.py archive --apply)").format((size + 1023) // 1024, limit // 1024)


def size_warning(size, limit=HANDOFF_WARN_BYTES):
    """The one-line stdout line for an oversized hand-off, else None (v16;
    v18: `fail:` - mark fails on it)."""
    why = size_reason(size, limit)
    return "fail: " + why if why else None


# ---------------------------------------------------------------- archive (v16)

def _heading_key(line):
    return " ".join(line.strip().strip("*").strip().upper().split())


def is_closed_heading(line):
    key = _heading_key(line)
    return key.startswith("CLOSED") or " - CLOSED" in key


def framed_blocks(lines):
    """[(start, end, heading)] for every framed heading: lines[start] is the
    first rule, lines[start + 1] the heading, lines[start + 2] the second
    rule; the block ends before the next framed heading (end exclusive)."""
    starts = [i for i in range(len(lines) - 1)
              if _RULE.match(lines[i]) and _is_heading(lines, i + 1)]
    out = []
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        out.append((i, end, lines[i + 1].strip()))
    return out


def _is_heading(lines, j):
    """lines[j] heads a block: framed by a second rule on j + 1, or a starred
    banner `*** ... ***` on its own line straight after the first rule."""
    line = lines[j].strip()
    if not line or _RULE.match(line):
        return False
    if j + 1 < len(lines) and _RULE.match(lines[j + 1]):
        return True
    return len(line) > 6 and line.startswith("***") and line.endswith("***")


def plan_archive(text, keep=1):
    """(moves, kept): moves = [(start, end, heading)] to archive; kept =
    [(heading, why)] for closed blocks that stay. Pure; the closed-block rule
    is in the module doc."""
    lines = text.split("\n")
    moves, kept, newest = [], [], 0
    for start, end, heading in framed_blocks(lines):
        if not is_closed_heading(heading):
            continue
        hit = next((m for m in (_OPEN_WORDS.search(b) for b in lines[start + 3:end]) if m),
                   None)
        if hit:
            kept.append((heading, "body says " + hit.group(1).upper()))
            continue
        if newest < keep:
            newest += 1
            kept.append((heading, "newest closed block"))
            continue
        moves.append((start, end, heading))
    return moves, kept


def archive(root, apply=False, keep=1, today=None, clock=None):
    """Plan, and with apply=True do, the move of closed blocks. Returns
    {handoff, archive, moved: [heading], kept: [(heading, why)], bytes_before,
    bytes_after, applied}. Raises ValueError (no hand-off) or OSError (a
    read-back that does not match; the hand-off is then left unchanged)."""
    import time
    root = Path(root)
    name = find_handoff(root)
    if not name:
        raise ValueError("hand-off file not found at the tree root")
    path = root / name
    raw = path.read_bytes()
    text = raw.decode("ascii")
    moves, kept = plan_archive(text, keep)
    day = today or _dt.date.today().isoformat()
    rel = ARCHIVE_REL / "{}-{}.txt".format(tree_code(name), day)
    lines = text.split("\n")
    out, chunks, i = [], [], 0
    for start, end, heading in moves:
        out.extend(lines[i:start])
        chunks.append("\n".join(lines[start:end]).rstrip("\n") + "\n")
        out.append('(closed block "{}" archived to {})'.format(
            _heading_key(heading)[:80], rel.as_posix()))
        out.append("")
        i = end
    out.extend(lines[i:])
    new = "\n".join(out)
    doc = {"handoff": name, "archive": rel.as_posix(), "moved": [m[2] for m in moves],
           "kept": kept, "bytes_before": len(raw), "bytes_after": len(new.encode("ascii")),
           "applied": False}
    if not apply or not moves:
        return doc
    dest = root / rel
    prior = dest.read_bytes() if dest.is_file() else b""
    stamp = "# archived from {} at {}\n".format(name, _utc((clock or time.time)()))
    add = (stamp + "".join(chunks)).encode("ascii")
    sep = b"" if not prior or prior.endswith(b"\n") else b"\n"
    _atomic_write(dest, (prior + sep + add).decode("ascii"))
    if not dest.read_bytes().endswith(add):
        raise OSError("archive read-back failed; hand-off left unchanged")
    if path.read_bytes() != raw:
        raise OSError("hand-off changed during the archive; hand-off left unchanged")
    _atomic_write(path, new)
    if path.read_bytes() != new.encode("ascii"):
        raise OSError("hand-off read-back failed after the archive")
    doc["applied"] = True
    return doc


def read_marker(root):
    try:
        doc = json.loads((Path(root) / MARKER_REL).read_text(encoding="ascii"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- validate

def validate(root, doc=None, session_id=None, pane=None, head_fn=head):
    """(verdict, why). verdict "DONE", "FAIL" or None (show nothing)."""
    doc = read_marker(root) if doc is None else doc
    if not doc:
        return None, "no marker"
    if doc.get("schema") != SCHEMA:
        return None, "schema {!r}".format(doc.get("schema"))
    status = doc.get("status")
    if status not in STATUSES:
        return None, "status {!r}".format(status)
    if status == "done" and doc.get("safe_to_clear") is not True:
        return None, "done but not safe to clear ({} bg)".format(doc.get("background_tasks"))
    if session_id:
        if doc.get("session_id") != session_id:
            return None, "other session"
    elif pane:
        if doc.get("pane") != pane:
            return None, "other pane"
    else:
        return None, "no binding given"
    commit, handoff, want = doc.get("commit"), doc.get("handoff"), doc.get("handoff_sha256")
    if not (isinstance(commit, str) and _HEX40.match(commit)):
        return None, "no commit"
    if not (isinstance(handoff, str) and handoff.endswith(HANDOFF_SUFFIX)
            and "/" not in handoff and "\\" not in handoff):
        return None, "no hand-off"
    if not (isinstance(want, str) and _HEX64.match(want)):
        return None, "no hand-off hash"
    if head_fn(root) != commit:
        return None, "HEAD moved after /done"
    if sha256_file(Path(root) / handoff) != want:
        return None, "hand-off changed after /done"
    if status == "failed":
        return "FAIL", doc.get("reason") or "failed"
    return "DONE", "S{} safe to clear".format(doc.get("session"))


# ---------------------------------------------------------------- stop hook

def _osc(n, text):
    return f"\x1b]{n};{text}\x07"


def stop_hook(data, root=None):
    """The Stop hook's JSON output as a dict; {} = print nothing."""
    data = data if isinstance(data, dict) else {}
    root = Path(root) if root else main_checkout(data.get("cwd") or os.getcwd())
    doc = read_marker(root)
    if not doc or doc.get("status") != "done":
        return {}
    verdict, _ = validate(root, doc, session_id=data.get("session_id"))
    if verdict != "DONE":
        return {}
    code, n = doc.get("tree") or "--", doc.get("session")
    waiting = len(data.get("background_tasks") or []) + len(data.get("session_crons") or [])
    if waiting:
        return {"terminalSequence": _osc(2, f"{code} S{n} done, waiting {waiting} bg")}
    seen = root / SEEN_REL
    try:
        if seen.read_text(encoding="ascii").strip() == doc.get("at"):
            return {}
    except OSError:
        pass
    try:
        _atomic_write(seen, "{}\n".format(doc.get("at")))
    except OSError:
        return {}
    title = "{} DONE S{} - safe to clear".format(code, n)
    return {"terminalSequence": _osc(2, title) + _osc(9, title)}


# ---------------------------------------------------------------- cli

def main(argv=None, stdin=None, stdout=None):
    stdout = stdout or sys.stdout
    ap = argparse.ArgumentParser(prog="fleet_done.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mark")
    m.add_argument("--session", type=int, required=True)
    m.add_argument("--status", choices=STATUSES, required=True)
    m.add_argument("--reason")
    m.add_argument("--bg", type=int, default=0)
    m.add_argument("--root")
    v = sub.add_parser("validate")
    v.add_argument("--session-id")
    v.add_argument("--pane")
    v.add_argument("--root")
    sub.add_parser("stop-hook")
    a = sub.add_parser("archive")
    a.add_argument("--apply", action="store_true")
    a.add_argument("--keep", type=int, default=1)
    a.add_argument("--root")
    args = ap.parse_args(argv)
    if args.cmd == "stop-hook":
        try:
            raw = (stdin or sys.stdin).read()
            out = stop_hook(json.loads(raw) if raw.strip() else {})
            if out:
                stdout.write(json.dumps(out) + "\n")
        except Exception:  # noqa: BLE001 - a Stop hook never fails the turn
            pass
        return 0
    root = Path(args.root) if args.root else main_checkout(os.getcwd())
    if args.cmd == "mark":
        doc = mark(root, args.session, args.status, args.reason, args.bg)
        stdout.write("session_done S{} {} safe_to_clear={}\n".format(
            doc["session"], doc["status"], str(doc["safe_to_clear"]).lower()))
        warn = size_warning(handoff_bytes(root / doc["handoff"]) if doc.get("handoff")
                            else None)
        if warn:
            stdout.write(warn + "\n")
        return 0 if doc["status"] == args.status else 1
    if args.cmd == "archive":
        try:
            doc = archive(root, apply=args.apply, keep=max(0, args.keep))
        except (OSError, ValueError) as exc:
            stdout.write("archive: refused - {}\n".format(_one_line(exc) or "error"))
            return 1
        verb = "moved" if doc["applied"] else "would move"
        stdout.write("archive {}: {} {} block(s) to {} ({} -> {} bytes)\n".format(
            "applied" if doc["applied"] else "dry-run", verb, len(doc["moved"]),
            doc["archive"], doc["bytes_before"], doc["bytes_after"]))
        for heading in doc["moved"]:
            stdout.write("  {}: {}\n".format(verb, _heading_key(heading)[:80]))
        for heading, why in doc["kept"]:
            stdout.write("  kept: {} ({})\n".format(_heading_key(heading)[:80], why))
        return 0
    verdict, why = validate(root, session_id=args.session_id
                            or os.environ.get("CLAUDE_CODE_SESSION_ID"), pane=args.pane)
    stdout.write("{}: {}\n".format(verdict or "none", why))
    return 0 if verdict == "DONE" else 1


if __name__ == "__main__":
    sys.exit(main())
