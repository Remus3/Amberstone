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

DONE_VERSION = 1
SCHEMA = 1
STATUSES = ("done", "failed")
MARKER_REL = Path("ops/loop/control/session_done.json")
SEEN_REL = Path("ops/loop/control/session_done.seen")
HANDOFF_SUFFIX = "-NEXT-SESSION.txt"
CHAT_LINE = "Done ritual complete, safe to clear"
REASON_MAX = 200
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------- repo facts

def _git(root, *args):
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           text=True, timeout=15, creationflags=_NO_WINDOW)
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
    if status == "done" and not handoff:
        status, reason = "failed", "hand-off file not found at the tree root"
    elif status == "done" and not commit:
        status, reason = "failed", "HEAD could not be read"
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
        return 0 if doc["status"] == args.status else 1
    verdict, why = validate(root, session_id=args.session_id
                            or os.environ.get("CLAUDE_CODE_SESSION_ID"), pane=args.pane)
    stdout.write("{}: {}\n".format(verdict or "none", why))
    return 0 if verdict == "DONE" else 1


if __name__ == "__main__":
    sys.exit(main())
