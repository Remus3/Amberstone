# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v13 - NO AI OR BOT ATTRIBUTION (FLEET-COMMON 17; GH-HYGIENE ruling
2026-10-08).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: GitHub lists a contributor for every identity in default-branch history,
including Co-Authored-By trailers. Claude and bot identities entered through
harness trailers, Claude-authored commits, Dependabot merges and workflow
pushes; settings alone did not stop them.

    python fleet_identity.py commit-msg <msgfile>     git commit-msg hook
    python fleet_identity.py pre-push <remote> <url>  git pre-push hook (stdin)
    python fleet_identity.py check <rev-range>        CI backstop / by hand

commit-msg: STRIPS forbidden attribution lines (a co-author / sign-off /
  co-developed trailer naming Claude, Anthropic or a bot, any `Claude-*:`
  trailer, a "Generated with Claude Code" line, a bare claude.ai session URL
  line) and logs one line with the count to ops/loop/control/identity.jsonl.
  It never rejects: a headless lane must not fail a commit over a trailer.
pre-push: REFUSES (exit 1) when any commit in a pushed range has an author or
  committer outside the operator identity set, or a forbidden attribution
  line. The operator set is read ONLY from the tree's LOCAL git config key
  `fleet.operatorIdent` (multi-valued; each value an address or
  `Name <address>`), never from a tracked file. No value set = refuse.
check: the same test over `git rev-list <rev-range>`; exit 1 on a violation.

Wiring (each tree's hooks path; MAIN keeps its refuse-every-push pre-push and
chains this inside its override branch):
    commit-msg:  python "<kit>/fleet_identity.py" commit-msg "$1" || true
    pre-push:    python "<kit>/fleet_identity.py" pre-push "$@" || exit 1
fleet_gitlock.py imports is_ai_or_bot() / operator_idents() and refuses a
commit whose resolved author or committer is a Claude or bot identity.
Messages name a commit by short hash and a class, never an address or name.
Pure stdlib. No machine path, account id, address or repo name in this file.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

LOG_REL = Path("ops/loop/control/identity.jsonl")
CONFIG_KEY = "fleet.operatorIdent"
ZERO = re.compile(r"^0+$")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# An identity (name or address) that is Claude / Anthropic or a bot / tool.
AI_RX = re.compile(r"claude|anthropic", re.I)
BOT_RX = re.compile(r"\[bot\]|dependabot|github-actions|renovate|copilot|"
                    r"(?:^|[\s<._+-])bot(?:$|[\s>@._+-])", re.I)
# Forbidden attribution lines in a commit message or PR body.
_TRAILER = re.compile(r"^\s*(?:co-authored-by|signed-off-by|co-developed-by)\s*:\s*(.*)$", re.I)
_CLAUDE_TRAILER = re.compile(r"^\s*claude-[a-z0-9-]+\s*:", re.I)
_GENERATED = re.compile(r"generated\s+(?:with|by)\s+\[?claude(?:\s+code)?\]?", re.I)
_SESSION_URL = re.compile(r"^\s*<?https?://claude\.ai/code/\S*>?\s*$", re.I)


def is_ai_or_bot(ident):
    """True when a name / address / `Name <address>` is Claude, Anthropic or a bot."""
    s = str(ident or "")
    return bool(AI_RX.search(s) or BOT_RX.search(s))


def forbidden_line(line):
    """The class of a forbidden attribution line, else ''."""
    m = _TRAILER.match(line)
    if m and is_ai_or_bot(m.group(1)):
        return "trailer"
    if _CLAUDE_TRAILER.match(line):
        return "claude-trailer"
    if _GENERATED.search(line):
        return "generated-line"
    if _SESSION_URL.match(line):
        return "session-url"
    return ""


def strip_message(text):
    """(new text, number of lines removed). Trailing blank lines collapse to
    one final newline; everything else is kept byte for byte."""
    lines = text.split("\n")
    keep = [ln for ln in lines if not forbidden_line(ln)]
    removed = len(lines) - len(keep)
    if not removed:
        return text, 0
    while keep and not keep[-1].strip():
        keep.pop()
    return ("\n".join(keep) + "\n") if keep else "", removed


def message_violations(text):
    return sorted({c for c in (forbidden_line(ln) for ln in text.split("\n")) if c})


# ---------------------------------------------------------------- operator set

def _git(cwd, *args, timeout=60):
    git = os.environ.get("FLEET_GIT") or "git"
    try:
        r = subprocess.run([git, "-C", str(cwd), *args], capture_output=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def operator_idents(cwd, reader=None):
    """Lower-cased operator idents from LOCAL git config only. Each value adds
    itself and, for `Name <address>`, the bare address."""
    out = reader(cwd) if reader else _git(cwd, "config", "--local", "--get-all", CONFIG_KEY)
    found = set()
    for v in (out or "").splitlines():
        v = v.strip().lower()
        if not v:
            continue
        found.add(v)
        m = re.search(r"<([^>]+)>", v)
        if m:
            found.add(m.group(1).strip())
    return found


def is_operator(name, addr, idents):
    a = str(addr or "").strip().lower()
    full = "{} <{}>".format(str(name or "").strip().lower(), a)
    return bool(idents) and (full in idents or (bool(a) and a in idents))


# ---------------------------------------------------------------- commit scan

_SEP, _END = "\x00", "\x1e"


def commits(cwd, rev_args, runner=None):
    """[{sha, an, ae, cn, ce, msg}] for `git log <rev_args>`."""
    fmt = "%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e"
    out = runner(rev_args) if runner else _git(cwd, "log", "--format=" + fmt, *rev_args,
                                               timeout=300)
    if out is None:
        return None
    rows = []
    for chunk in out.split(_END):
        chunk = chunk.lstrip("\n")
        if not chunk:
            continue
        parts = chunk.split(_SEP, 5)
        if len(parts) < 6:
            continue
        rows.append(dict(zip(("sha", "an", "ae", "cn", "ce", "msg"), parts)))
    return rows


def violations(rows, idents):
    """[(short sha, class)] - classes: author, committer, ai-author, ...,
    plus the message line classes. Never an address or a name."""
    out = []
    for r in rows:
        short = r["sha"][:10]
        for role, n, a in (("author", r["an"], r["ae"]), ("committer", r["cn"], r["ce"])):
            if is_operator(n, a, idents):
                continue
            if is_ai_or_bot(n) or is_ai_or_bot(a):
                out.append((short, "ai-or-bot-" + role))
            else:
                out.append((short, "non-operator-" + role))
        for c in message_violations(r["msg"]):
            out.append((short, c))
    return out


def push_ranges(stdin_text, remote):
    """git rev-list argument lists for each pushed ref (deletes skipped)."""
    ranges = []
    for ln in (stdin_text or "").splitlines():
        parts = ln.split()
        if len(parts) != 4:
            continue
        _lref, lsha, _rref, rsha = parts
        if ZERO.match(lsha):
            continue
        if ZERO.match(rsha):
            ranges.append([lsha, "--not", "--remotes=" + remote] if remote else [lsha])
        else:
            ranges.append([rsha + ".." + lsha])
    return ranges


# ---------------------------------------------------------------- log

def _main_checkout(cwd):
    p = Path(cwd).resolve()
    for top in (p, *p.parents):
        dg = top / ".git"
        if dg.is_dir():
            return top
        if dg.is_file():
            try:
                raw = dg.read_text(encoding="utf-8").strip()
            except OSError:
                return top
            gd = Path(raw.split(":", 1)[1].strip()) if raw.startswith("gitdir:") else None
            if gd is not None and not gd.is_absolute():
                gd = (top / gd).resolve()
            return gd.parents[2] if gd is not None and gd.parent.name == "worktrees" else top
    return p


def _log(cwd, row):
    try:
        path = _main_checkout(cwd) / LOG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="ascii", errors="replace", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _say(msg):
    try:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


# ---------------------------------------------------------------- hooks

def commit_msg(msgfile, cwd=None):
    """Strip in place; always returns 0."""
    cwd = cwd or os.getcwd()
    try:
        raw = Path(msgfile).read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    new, removed = strip_message(text)
    if removed:
        try:
            Path(msgfile).write_bytes(new.encode("utf-8"))
        except OSError:
            return 0
        _log(cwd, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "commit-msg-strip",
                   "lines": removed})
    return 0


def _report(found, what):
    for short, cls in found[:20]:
        _say("IDENTITY: {} {}".format(short, cls))
    _say(f"IDENTITY: {what} refused - {len(found)} violation(s); no AI or bot "
         f"attribution and only the operator identity (local git config {CONFIG_KEY}) "
         "may reach a remote")


def pre_push(remote, stdin_text, cwd=None, idents=None, runner=None):
    cwd = cwd or os.getcwd()
    idents = operator_idents(cwd) if idents is None else idents
    if not idents:
        _say("IDENTITY: push refused - set the operator identity in LOCAL git config: "
             "git config --local --add {} \"Name <address>\"".format(CONFIG_KEY))
        return 1
    found = []
    for rng in push_ranges(stdin_text, remote):
        rows = commits(cwd, rng, runner)
        if rows is None:
            _say("IDENTITY: push refused - could not list the pushed commits")
            return 1
        found += violations(rows, idents)
    if found:
        _report(found, "push")
        _log(cwd, {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "event": "pre-push-refused",
                   "violations": len(found)})
        return 1
    return 0


def check(rev_range, cwd=None, idents=None, runner=None):
    cwd = cwd or os.getcwd()
    idents = operator_idents(cwd) if idents is None else idents
    if not idents:
        _say("IDENTITY: no {} in local git config".format(CONFIG_KEY))
        return 1
    rows = commits(cwd, [rev_range], runner)
    if rows is None:
        _say("IDENTITY: could not list {}".format(rev_range))
        return 1
    found = violations(rows, idents)
    if found:
        _report(found, "check")
        return 1
    print(f"IDENTITY: {len(rows)} commit(s) clean")
    return 0


def main(argv=None, stdin=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["commit-msg"] and len(argv) == 2:
        return commit_msg(argv[1])
    if argv[:1] == ["pre-push"]:
        remote = argv[1] if len(argv) > 1 else ""
        return pre_push(remote, (stdin or sys.stdin).read())
    if argv[:1] == ["check"] and len(argv) == 2:
        return check(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
