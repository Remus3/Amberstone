#!/usr/bin/env python3
"""Post-merge bot-identity check for the default branch.

Source: MAIN ORDER 2026-10-19-0034 DEPENDABOT-MERGE-RULE section 2.2
(operator authority, FLEET-COMMON 6 and 17).

Why it exists: a merge done ON GitHub (the squash dialog, the merge button, a
GitHub-side PR merge from the CLI) never runs a local commit-msg hook, and the
commit is already on the remote before any pre-push hook sees anything. So
ops/fleet_kit/fleet_identity.py's two hooks cannot catch that path by
construction. This check closes it after the fact: it fetches the default
branch and scans the commits that are new since the last clean scan.

A commit is flagged - by short hash and class only, never a name or an
address - for:
  - an author or committer outside the operator set (LOCAL git config
    `fleet.operatorIdent`, read through the vendored fleet_identity, which is
    imported and never edited here): ai-or-bot-author, ai-or-bot-committer,
    web-merge-committer (the committer GitHub writes on a GitHub-side merge),
    non-operator-author, non-operator-committer;
  - ANY `Co-authored-by:` line (class co-authored-by). This is wider than the
    kit, which flags a co-author trailer only when it names an AI or a bot,
    while GitHub lists every co-author as a contributor;
  - the kit's other forbidden message lines (trailer, claude-trailer,
    session-url, generated-line).

A hit is appended to ops/loop/control/bot_merge_check.jsonl and exits 1. The
fix is ops/fleet_kit/fleet_rewrite.py (plan, bundle, run) under MAIN's
2026-10-18-2312 scope (bot identities only), never another path; a rewrite
force-pushes, so it waits at RC's halt boundary for the operator. A clean scan
advances the watermark ops/loop/control/bot_merge_check.json to the tip.

    python tools/bot_merge_check.py               fetch, scan <watermark>..origin/main
    python tools/bot_merge_check.py --all         scan the whole default branch
    python tools/bot_merge_check.py --range A..B  scan an explicit range
    python tools/bot_merge_check.py --init        record the tip as clean (no scan)
    options: --ref REF (default origin/main), --no-fetch

No watermark yet, or a watermark that is no longer an ancestor of the tip
(history rewritten), scans the whole branch. --init exists for the first run:
survey with --all, record its classes in the hand-off, then --init.
Exit: 0 clean, 1 hit, 2 usage / git failure / no operator set (fail closed).
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KIT_DIR = ROOT / "ops" / "fleet_kit"
STATE_REL = Path("ops/loop/control/bot_merge_check.json")
LOG_REL = Path("ops/loop/control/bot_merge_check.jsonl")
DEFAULT_REF = "origin/main"
CO_AUTHOR = re.compile(r"^\s*co-authored-by\s*:", re.I)
SHOW_MAX = 20
FIX_HINT = ("fix ONLY with ops/fleet_kit/fleet_rewrite.py (plan, bundle, run) under "
            "MAIN 2026-10-18-2312 scope; a rewrite force-pushes, so it waits for the "
            "operator")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _kit_module(stem):
    """A vendored fleet-kit module, loaded by path under the same
    `fleet_kit_<stem>` key tools/ci_watchdog.py uses (one instance)."""
    key = "fleet_kit_" + stem
    mod = sys.modules.get(key)
    if mod is None:
        spec = importlib.util.spec_from_file_location(key, KIT_DIR / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return mod


def _git(root, *args, timeout=120):
    """stdout of `git -C root ...`, or None on any failure (fail closed)."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           timeout=timeout, env=env, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def classify(rows, idents, ident=None):
    """[(short sha, class)] for commit rows shaped like fleet_identity.commits().
    The kit's own violations, plus ANY Co-authored-by line."""
    ident = ident or _kit_module("fleet_identity")
    out = []
    for r in rows:
        found = {c for _, c in ident.violations([r], idents)}
        if any(CO_AUTHOR.match(ln) for ln in r.get("msg", "").split("\n")):
            found.add("co-authored-by")
        out += [(r["sha"][:10], c) for c in sorted(found)]
    return out


def class_counts(hits):
    """{class: distinct commit count}."""
    seen = {}
    for short, cls in hits:
        seen.setdefault(cls, set()).add(short)
    return {c: len(s) for c, s in sorted(seen.items())}


def _read_state(root):
    try:
        data = json.loads((Path(root) / STATE_REL).read_text(encoding="ascii"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("ascii"))
    tmp.replace(path)


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def write_state(root, ref, sha):
    _atomic_write(Path(root) / STATE_REL,
                  json.dumps({"ref": ref, "clean_through": sha, "updated": _now()},
                             sort_keys=True) + "\n")


def _log(root, row):
    path = Path(root) / LOG_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="ascii", errors="replace", newline="\n") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    except OSError:
        pass


def _say(msg):
    print("BOT-MERGE-CHECK: " + msg)


def _fetch(root, ref):
    remote, _, branch = ref.partition("/")
    if not branch:
        return True  # a local ref: nothing to fetch
    return _git(root, "fetch", "--quiet", remote, branch, timeout=300) is not None


def resolve_range(root, ref, tip, explicit=None, scan_all=False):
    """(rev args for git log, description)."""
    if explicit:
        return [explicit], explicit
    if scan_all:
        return [tip], "whole " + ref
    wm = _read_state(root).get("clean_through")
    if isinstance(wm, str) and re.fullmatch(r"[0-9a-f]{40}", wm):
        if _git(root, "merge-base", "--is-ancestor", wm, tip) is not None:
            return [wm + ".." + tip], "since watermark " + wm[:10]
        return [tip], f"whole {ref} (watermark {wm[:10]} not an ancestor of the tip)"
    return [tip], f"whole {ref} (no watermark yet)"


def run(root=ROOT, ref=DEFAULT_REF, explicit=None, scan_all=False, fetch=True, init=False):
    ident = _kit_module("fleet_identity")
    idents = ident.operator_idents(root)
    if not idents:
        _say(f"refused - local git config {ident.CONFIG_KEY} is not set; no operator set to check "
             "against")
        return 2
    if fetch and not explicit and not _fetch(root, ref):
        _say(f"refused - git fetch for {ref} failed")
        return 2
    tip = (_git(root, "rev-parse", "--verify", ref + "^{commit}") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tip):
        _say(f"refused - cannot resolve {ref}")
        return 2
    if init:
        write_state(root, ref, tip)
        _say(f"watermark set to {tip[:10]} ({ref}); nothing scanned")
        return 0
    revs, desc = resolve_range(root, ref, tip, explicit, scan_all)
    rows = ident.commits(root, ["--topo-order", *revs])
    if rows is None:
        _say(f"refused - could not list {desc}")
        return 2
    hits = classify(rows, idents, ident)
    if not hits:
        if not explicit:
            write_state(root, ref, tip)
        _say(f"{len(rows)} commit(s) scanned ({desc}): clean")
        return 0
    counts = class_counts(hits)
    for short, cls in hits[:SHOW_MAX]:
        _say(f"{short} {cls}")
    flagged = len({s for s, _ in hits})
    _say(f"{len(rows)} commit(s) scanned ({desc}): {flagged} flagged; classes {json.dumps(counts, sort_keys=True)}")
    _say(FIX_HINT)
    _log(root, {"at": _now(), "event": "bot-merge-check-hit", "ref": ref, "tip": tip[:10],
                "scanned": len(rows), "flagged": flagged, "classes": counts})
    return 1


def main(argv=None, root=ROOT):
    p = argparse.ArgumentParser(prog="bot_merge_check.py", description=__doc__.split("\n")[0])
    p.add_argument("--ref", default=DEFAULT_REF)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", dest="scan_all")
    mode.add_argument("--range", dest="explicit")
    mode.add_argument("--init", action="store_true")
    p.add_argument("--no-fetch", action="store_true")
    try:
        a = p.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    return run(root=root, ref=a.ref, explicit=a.explicit, scan_all=a.scan_all,
               fetch=not a.no_fetch, init=a.init)


if __name__ == "__main__":
    sys.exit(main())
